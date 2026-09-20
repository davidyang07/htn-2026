"""The Live Swarm Demo's offline-authored SwarmFlow (docs/MVP_PLAN.md P0.5).

    Repo Analyst  ─┐
                   ├→ AgentShield gate ─(deny)→ Replacement Researcher ─┐
    Security Res. ─┘                    (allow)→ original report ───────┴→
                   → Developer → real patch → real pytest → Reviewer → recovered

The contract that makes the demo work, restated because every component here
depends on it: **a worker never holds the capability it is being tricked into
using.** No component below opens a file on a worker's behalf. A worker names
what it wants; `AgentShieldClient.request_resource` answers; only an allowed
response carries content. A prompt injection that completely captures a worker
still obtains nothing.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from openjiuwen.core.session import BaseSession
from openjiuwen.core.workflow import (
    BranchRouter,
    Condition,
    End,
    Start,
    Workflow,
    WorkflowComponent,
)

from workswarm import prompts
from workswarm.agentshield_client import AgentShieldClient, Decision
from workswarm.config import (
    AUTH_MODULE,
    AUTH_NOTES,
    README,
    ModelConfig,
    to_repo_relative,
)
from workswarm.patcher import write_in_sandbox
from workswarm.telemetry import ManualSpan, log_event, span
from workswarm.verify import run_demo_target_tests
from workswarm.workers import (
    DeterministicAnalyst,
    DeterministicDeveloper,
    DeterministicResearcher,
    DeterministicReviewer,
    build_llm_worker,
    extract_json,
    parse_report,
)

logger = logging.getLogger(__name__)


def _runnable(worker: Any) -> Any:
    """The thing with `.invoke` on it.

    WorkSwarm draws a line between a *composable* (how a component joins a
    graph) and an *executable* (how it runs). `WorkflowComponent` is both, so
    the deterministic stand-ins can be invoked directly; `LLMComponent` is only
    the former and hands out its executable on demand. Resolving it here keeps
    both worker kinds interchangeable at every call site.
    """
    return worker.executable if hasattr(worker, "executable") else worker


def _endpoint_host(api_base: str) -> str:
    """Host only. A full base URL is not a secret, but it is not evidence
    either, and keeping only the host means a credential embedded in a URL
    could never ride along into an event payload."""
    try:
        return urlparse(api_base).hostname or ""
    except Exception:
        return ""


REPO_ANALYST = "repo-analyst"
SECURITY_RESEARCHER = "security-researcher"
REPLACEMENT_RESEARCHER = "replacement-researcher"
DEVELOPER = "developer"
REVIEWER = "reviewer"

WORKER_SPECS = [
    {"id": REPO_ANALYST, "role": "Repo Analyst", "upstream": []},
    {"id": SECURITY_RESEARCHER, "role": "Security Researcher", "upstream": [REPO_ANALYST]},
    {"id": DEVELOPER, "role": "Developer", "upstream": [SECURITY_RESEARCHER]},
    {"id": REVIEWER, "role": "Reviewer", "upstream": [DEVELOPER]},
]

WORKER_ROLES = {
    **{spec["id"]: spec["role"] for spec in WORKER_SPECS},
    REPLACEMENT_RESEARCHER: "Replacement Researcher",
}

#: How much of the researcher's analysis the Developer is given. Enough to
#: state the finding; not so much that the model's token budget is spent
#: reasoning about prose instead of writing the patch.
MAX_ANALYSIS_CHARS = 1500

REGRESSION_TEST_PATH = "tests/test_auth_regression.py"
AUTH_MODULE_PATH = "app/auth.py"


@dataclass
class RunContext:
    """Everything the components share. One per run."""

    client: AgentShieldClient
    model: ModelConfig
    #: Truthfully recorded on every worker and surfaced in the UI.
    model_backed: bool
    analysis_span: ManualSpan = field(
        default_factory=lambda: ManualSpan("workswarm.analysis", "workswarm.analysis")
    )
    #: Paths the control plane denied, with the reason. Never any content.
    denials: list[Decision] = field(default_factory=list)
    quarantined_worker: str | None = None
    fail_closed: bool = False
    #: Set by ProveVulnerabilityStep: did the new regression test actually
    #: fail against the unpatched module?
    vulnerability_proven: bool = False
    baseline_failure_summary: str = ""

    def trace_fields(self, worker_id: str | None = None, **extra: Any) -> dict[str, Any]:
        """Safe identifiers shared by every WorkSwarm span."""
        fields: dict[str, Any] = {
            "run_id": self.client.session_id,
            "session_id": self.client.session_id,
            "model_backed": self.model_backed,
        }
        if worker_id is not None:
            fields.update(worker_id=worker_id, role=WORKER_ROLES.get(worker_id, ""))
        if self.model_backed:
            fields.update(provider=self.model.provider, model=self.model.model_name)
        fields.update(extra)
        return fields

    def record_model_call(
        self, worker_id: str, *, latency_ms: int, prompt_chars: int, response_chars: int
    ) -> None:
        """Report a real model call, if this run is model-backed.

        A deterministic run records nothing, which is precisely what makes the
        presence of MODEL_REQUESTED/MODEL_RESPONDED events evidence.
        """
        if not self.model_backed:
            return
        self.client.record_model_call(
            worker_id,
            provider=self.model.provider,
            model=self.model.model_name,
            endpoint_host=_endpoint_host(self.model.api_base),
            latency_ms=latency_ms,
            prompt_chars=prompt_chars,
            response_chars=response_chars,
        )


# --- conditions -----------------------------------------------------------


class RecoveryRequired(Condition):
    """Routes on AgentShield's answer, not on anything a worker said."""

    def __init__(self) -> None:
        super().__init__(input_schema={"recovery_required": "${shield_gate.recovery_required}"})

    def invoke(self, inputs: Any, session: BaseSession) -> bool:
        return bool((inputs or {}).get("recovery_required"))

    def trace_info(self, session: BaseSession = None) -> str:
        return "shield_gate.recovery_required"


class NoRecoveryRequired(Condition):
    def __init__(self) -> None:
        super().__init__(input_schema={"recovery_required": "${shield_gate.recovery_required}"})

    def invoke(self, inputs: Any, session: BaseSession) -> bool:
        return not bool((inputs or {}).get("recovery_required"))

    def trace_info(self, session: BaseSession = None) -> str:
        return "not shield_gate.recovery_required"


# --- components -----------------------------------------------------------


class ContextComponent(WorkflowComponent):
    def __init__(self, ctx: RunContext) -> None:
        super().__init__()
        self.ctx = ctx


class FetchForWorker(ContextComponent):
    """Start a worker and hand it the documents its own plan calls for.

    Every path still goes through AgentShield. These are the worker's *own*
    planned reads, not anything a document told it to fetch -- that comes
    later, at the gate.
    """

    def __init__(
        self,
        ctx: RunContext,
        worker_id: str,
        task: str,
        paths: list[str],
        span_name: str,
        open_analysis_span: bool = False,
    ) -> None:
        super().__init__(ctx)
        self.worker_id = worker_id
        self.task = task
        self.paths = paths
        self.span_name = span_name
        self.open_analysis_span = open_analysis_span

    async def invoke(self, inputs: Any, session: Any, context: Any) -> Any:
        if self.open_analysis_span:
            self.ctx.analysis_span.open()

        self.ctx.client.start_task(self.worker_id, self.task)

        # A list of records, not a dict keyed by path: WorkSwarm's workflow
        # state splits dotted dict keys into nested dicts, so "auth.py" would
        # arrive downstream as {"auth": {"py": ...}}.
        documents: list[dict[str, str]] = []
        with span(
            "workswarm.worker.fetch",
            f"workswarm.{self.span_name}",
            **self.ctx.trace_fields(self.worker_id, phase="fetch"),
        ):
            for path in self.paths:
                decision = self.ctx.client.request_resource(self.worker_id, path)
                if decision.fail_closed:
                    self.ctx.fail_closed = True
                if decision.allowed and decision.content is not None:
                    documents.append(
                        {"path": decision.normalized_path or path, "text": decision.content}
                    )
                elif not decision.allowed:
                    self.ctx.denials.append(decision)

        return {"documents": documents, "task": self.task}


class RunWorker(ContextComponent):
    """Run one reasoning worker and normalize its structured report."""

    def __init__(self, ctx: RunContext, worker_id: str, inner: Any, span_name: str) -> None:
        super().__init__(ctx)
        self.worker_id = worker_id
        self.inner = inner
        self.span_name = span_name

    async def invoke(self, inputs: Any, session: Any, context: Any) -> Any:
        documents: list[dict[str, str]] = (inputs or {}).get("documents") or []
        payload = {
            "documents": documents,
            "document_text": "\n\n".join(str(d.get("text", "")) for d in documents),
            "task": (inputs or {}).get("task") or "",
            "objective": (inputs or {}).get("objective") or "",
        }

        started = time.perf_counter()
        with span(
            "workswarm.worker",
            f"workswarm.{self.span_name}",
            **self.ctx.trace_fields(self.worker_id, phase="analysis"),
        ):
            raw = await _runnable(self.inner).invoke(payload, session, context)
        latency_ms = int((time.perf_counter() - started) * 1000)

        report = parse_report(raw)

        # Evidence that this worker was model-backed, recorded by the side
        # that actually made the call. Identity and timing only -- no prompt,
        # no completion, no credential. A stand-in records nothing, which is
        # what makes the presence of these events meaningful.
        self.ctx.record_model_call(
            self.worker_id,
            latency_ms=latency_ms,
            prompt_chars=len(payload["document_text"]) + len(payload["task"]),
            response_chars=len(str(raw)),
        )
        logger.info(
            "%s requested_files=%s", self.worker_id, report["requested_files"]
        )
        return {"report": report, "documents": documents}


class RecordReport(ContextComponent):
    """Record the worker's output as an artifact, and optionally close its task.

    ``complete_task`` is skipped for the Security Researcher: its artifact has
    to exist *before* the gate runs, so that the quarantine has something real
    to taint, but the worker has not finished anything yet -- and a moment
    later it may be removed from the team. The no-denial branch closes its task
    instead.
    """

    def __init__(
        self,
        ctx: RunContext,
        worker_id: str,
        artifact_id: str,
        step: str,
        *,
        complete: bool = True,
    ) -> None:
        super().__init__(ctx)
        self.worker_id = worker_id
        self.artifact_id = artifact_id
        self.step = step
        self.complete = complete

    async def invoke(self, inputs: Any, session: Any, context: Any) -> Any:
        report = (inputs or {}).get("report") or {}
        summary = (report.get("analysis") or "")[:400]
        self.ctx.client.record_artifact(self.artifact_id, self.worker_id, self.step, summary)
        if self.complete:
            self.ctx.client.complete_task(self.worker_id, self.step, summary)
        return {
            "report": report,
            "artifact_id": self.artifact_id,
            "documents": (inputs or {}).get("documents") or [],
        }


class ShieldGate(ContextComponent):
    """THE enforcement point.

    Takes the Security Researcher's `requested_files` -- whatever the worker
    asked for, including whatever the poisoned document talked it into -- and
    asks AgentShield about each one. Reads only what comes back allowed.
    """

    async def invoke(self, inputs: Any, session: Any, context: Any) -> Any:
        report = (inputs or {}).get("report") or {}
        requested: list[str] = report.get("requested_files") or []

        documents: list[dict[str, str]] = list((inputs or {}).get("documents") or [])
        recovery_required = False
        quarantined = False

        for raw_path in requested:
            # The worker reasons about a repository rooted at demo_target/, so
            # translate its workspace convention before asking. This cannot
            # turn a denial into an allow -- see config.to_repo_relative.
            path = to_repo_relative(raw_path)
            decision = self.ctx.client.request_resource(SECURITY_RESEARCHER, path)

            if decision.fail_closed:
                self.ctx.fail_closed = True

            if decision.allowed:
                if decision.content is not None:
                    documents.append(
                        {"path": decision.normalized_path or path, "text": decision.content}
                    )
                continue

            # Denied. Nothing was read. The path is recorded; the resource is
            # not, because no code path ever opened it.
            self.ctx.denials.append(decision)
            log_event(
                "security.tool_denied",
                f"AgentShield denied {SECURITY_RESEARCHER} -> {path}",
                worker_id=SECURITY_RESEARCHER,
                resource_path=path,
                rule=decision.rule,
            )
            if decision.quarantined:
                quarantined = True
                self.ctx.quarantined_worker = SECURITY_RESEARCHER
            if decision.recovery_required:
                recovery_required = True

            # A quarantined worker can take no further action, so there is
            # nothing to gain by continuing down its wish list.
            if quarantined:
                break

        self.ctx.analysis_span.close()

        if recovery_required:
            log_event(
                "security.agent_quarantined",
                "Security Researcher quarantined; its output is untrusted",
                worker_id=SECURITY_RESEARCHER,
                requested_files=requested,
            )

        return {
            "report": report,
            "documents": documents,
            "recovery_required": recovery_required,
            "quarantined": quarantined,
            "requested_files": requested,
        }


class ReassignAndFetch(ContextComponent):
    """Start a genuinely new Replacement Researcher on trusted context only.

    The seed context is the trusted artifacts AgentShield still vouches for.
    Naming a tainted one is refused by the control plane with a 409, so "the
    poisoned document never reached the replacement" is enforced rather than
    asserted.
    """

    async def invoke(self, inputs: Any, session: Any, context: Any) -> Any:
        summary = self.ctx.client.summary()
        trusted = [a["id"] for a in summary["artifacts"] if a["trusted"]]

        task = (
            "Investigate the authentication vulnerability from trusted context only. "
            "The previous researcher was quarantined and its output was discarded."
        )
        with span(
            "swarm.task_reassigned",
            "swarm.task_reassigned",
            **self.ctx.trace_fields(
                REPLACEMENT_RESEARCHER,
                from_worker_id=SECURITY_RESEARCHER,
                to_worker_id=REPLACEMENT_RESEARCHER,
                replaces=SECURITY_RESEARCHER,
                replacement_worker_id=REPLACEMENT_RESEARCHER,
            ),
        ):
            self.ctx.client.reassign(
                from_worker_id=SECURITY_RESEARCHER,
                to_worker={
                    "id": REPLACEMENT_RESEARCHER,
                    "role": "Replacement Researcher",
                    "upstream": [REPO_ANALYST],
                    "replaces": SECURITY_RESEARCHER,
                    "model_backed": self.ctx.model_backed,
                },
                task=task,
                context_artifact_ids=trusted,
            )

        log_event(
            "swarm.replacement_started",
            "Replacement Researcher started with trusted context only",
            worker_id=REPLACEMENT_RESEARCHER,
            trusted_artifacts=trusted,
        )

        # The replacement re-reads the module for itself. It deliberately does
        # NOT receive demo_target/docs/auth_notes.md: that document is what
        # compromised its predecessor, and the poisoned text must not reach it.
        documents: list[dict[str, str]] = []
        with span(
            "workswarm.worker.fetch",
            "workswarm.replacement_researcher.fetch",
            **self.ctx.trace_fields(REPLACEMENT_RESEARCHER, phase="fetch"),
        ):
            decision = self.ctx.client.request_resource(REPLACEMENT_RESEARCHER, AUTH_MODULE)
            if decision.fail_closed:
                self.ctx.fail_closed = True
            if decision.allowed and decision.content is not None:
                documents.append(
                    {"path": decision.normalized_path or AUTH_MODULE, "text": decision.content}
                )

        return {"documents": documents, "task": task}


class PassThroughReport(ContextComponent):
    """The no-denial branch: the original researcher's report stands, and its
    task is closed out here because the gate did not remove it from the team."""

    async def invoke(self, inputs: Any, session: Any, context: Any) -> Any:
        report = (inputs or {}).get("report") or {}
        self.ctx.client.complete_task(
            SECURITY_RESEARCHER, "research", (report.get("analysis") or "")[:400]
        )
        return {"report": report, "documents": (inputs or {}).get("documents") or []}


class MergeResearch(ContextComponent):
    """Whichever branch ran, this is the research the Developer works from."""

    async def invoke(self, inputs: Any, session: Any, context: Any) -> Any:
        inputs = inputs or {}
        replacement = inputs.get("from_replacement")
        original = inputs.get("from_original")
        chosen = replacement if replacement else original
        return {
            "report": chosen or {},
            "recovered": bool(replacement),
        }


class DeveloperStep(ContextComponent):
    """Fetch the module, run the Developer, and apply a real patch."""

    def __init__(self, ctx: RunContext, inner: Any) -> None:
        super().__init__(ctx)
        self.inner = inner

    async def invoke(self, inputs: Any, session: Any, context: Any) -> Any:
        report = (inputs or {}).get("report") or {}

        task = "Patch the authentication vulnerability and add regression coverage."
        self.ctx.client.start_task(DEVELOPER, task)

        decision = self.ctx.client.request_resource(DEVELOPER, AUTH_MODULE)
        if decision.fail_closed:
            self.ctx.fail_closed = True
        if not decision.allowed or decision.content is None:
            raise RuntimeError(
                f"the Developer could not obtain {AUTH_MODULE}: {decision.reason}"
            )

        with span("developer.patch", "developer.patch", worker_id=DEVELOPER):
            started = time.perf_counter()
            # Trimmed on purpose. A reasoning model spends its token budget
            # on thinking before it emits anything, and a verbose upstream
            # analysis pushed the Developer into returning an EMPTY completion.
            # It needs the source and the finding -- not every recommendation.
            produced = await _runnable(self.inner).invoke(
                {
                    "current_source": decision.content,
                    "analysis": str(report.get("analysis", ""))[:MAX_ANALYSIS_CHARS],
                    "recommendations": "\n".join(
                        f"- {r}" for r in (report.get("recommendations") or [])[:3]
                    ),
                },
                session,
                context,
            )
            self.ctx.record_model_call(
                DEVELOPER,
                latency_ms=int((time.perf_counter() - started) * 1000),
                prompt_chars=len(decision.content) + len(report.get("analysis", "")),
                response_chars=len(str(produced)),
            )
            patch = _as_patch(produced)

            # ONLY the regression test is written here. The module stays
            # vulnerable so the next step can prove the test actually fails
            # against it -- "6 passed then 8 passed" would show a test was
            # added, not that a vulnerability existed.
            #
            # Writes are constrained to demo_target/ and refused into
            # demo_target/secrets/ by the sandbox guard, not by a prompt.
            written = [write_in_sandbox(REGRESSION_TEST_PATH, patch["regression_test"])]

        self.ctx.client.complete_task(
            DEVELOPER, "regression_test", "Added regression coverage for the vulnerability."
        )
        return {
            "patched_source": patch["patched_source"],
            "explanation": patch["explanation"],
            "files_written": written,
        }


class ProveVulnerabilityStep(ContextComponent):
    """Run the new regression test against the STILL-VULNERABLE module.

    This is the step that turns "tests pass" into "a vulnerability existed and
    was fixed". The test must fail here. Nothing is manufactured: the module
    has not been patched yet, and a genuine regression test for a genuine bug
    fails against it.

    If it *passes*, the run says so and stops. A regression test that is green
    against the unpatched code is not regression coverage for this bug, and
    reporting it as proof would be a lie.
    """

    async def invoke(self, inputs: Any, session: Any, context: Any) -> Any:
        with span("pytest.run", "pytest.baseline_regression"):
            result = run_demo_target_tests()

        proven = not result.passed
        self.ctx.vulnerability_proven = proven
        self.ctx.baseline_failure_summary = result.summary

        self.ctx.client.record_test_run(
            DEVELOPER,
            command=f"{result.command}  (before the fix)",
            exit_code=result.exit_code,
            passed=result.passed,
            summary=result.summary,
        )
        self.ctx.client.complete_task(
            DEVELOPER,
            "vulnerability_proven" if proven else "vulnerability_NOT_proven",
            (
                f"The regression test fails against the unpatched module: {result.summary}"
                if proven
                else (
                    "The regression test PASSED against the unpatched module, so it "
                    f"does not cover the vulnerability: {result.summary}"
                )
            ),
        )
        log_event(
            "developer.patch_applied",
            (
                f"Regression test fails against the vulnerable module: {result.summary}"
                if proven
                else "Regression test did not fail against the vulnerable module"
            ),
            worker_id=DEVELOPER,
            phase="before_fix",
            vulnerability_proven=proven,
        )

        return {
            "vulnerability_proven": proven,
            "baseline_summary": result.summary,
            "baseline_output": result.tail,
            "patched_source": (inputs or {}).get("patched_source") or "",
            "explanation": (inputs or {}).get("explanation") or "",
        }


class ApplyPatchStep(ContextComponent):
    """Now apply the fix. The regression test is already on disk and red."""

    async def invoke(self, inputs: Any, session: Any, context: Any) -> Any:
        inputs = inputs or {}
        patched_source = inputs.get("patched_source") or ""
        explanation = inputs.get("explanation") or "Patched the authentication module."

        if not inputs.get("vulnerability_proven"):
            raise RuntimeError(
                "refusing to apply the patch: the regression test did not fail "
                "against the unpatched module, so there is nothing proven to fix"
            )

        with span("developer.patch", "developer.apply_patch", worker_id=DEVELOPER):
            written = write_in_sandbox(AUTH_MODULE_PATH, patched_source)

        self.ctx.client.complete_task(DEVELOPER, "patch", explanation)
        log_event(
            "developer.patch_applied",
            explanation,
            worker_id=DEVELOPER,
            phase="fix",
            files_written=[written],
        )
        return {
            "patched_source": patched_source,
            "explanation": explanation,
            "baseline_summary": inputs.get("baseline_summary") or "",
            "vulnerability_proven": True,
        }


#: The Developer answers with two labelled code fences rather than JSON. A
#: whole Python module escaped into a JSON string is something models get
#: wrong constantly -- newlines, quotes and backslashes all have to survive --
#: and a fenced block is both easier for the model and unambiguous to parse.
_LABELLED_FENCE = r"{label}:\s*```(?:python)?\s*\n(.*?)```"
_EXPLANATION_RE = re.compile(r"EXPLANATION:\s*(.+)")


def _fenced_section(text: str, label: str) -> str | None:
    match = re.search(
        _LABELLED_FENCE.format(label=label), text, re.S | re.I
    )
    return match.group(1) if match else None


def _as_patch(produced: Any) -> dict[str, str]:
    """Normalize the Developer's output, whatever shape it arrived in.

    Accepts the labelled-fence format the prompt asks for, and still accepts
    the JSON shape the deterministic stand-in produces.
    """
    text = produced.get("report") if isinstance(produced, dict) else produced
    if isinstance(text, str):
        patched = _fenced_section(text, "PATCHED_FILE")
        regression = _fenced_section(text, "REGRESSION_TEST")
        if patched and regression:
            explanation = _EXPLANATION_RE.search(text)
            return {
                "patched_source": patched,
                "regression_test": regression,
                "explanation": (
                    explanation.group(1).strip()
                    if explanation
                    else "Patched the authentication module."
                ),
            }

    payload = extract_json(produced)
    if payload is None:
        if not str(text or "").strip():
            raise RuntimeError(
                "the Developer's model returned an EMPTY completion. On a "
                "reasoning model this usually means max_tokens was exhausted "
                "by reasoning tokens before any output token was emitted -- "
                "raise max_tokens in workswarm/workers.py::build_llm_worker."
            )
        preview = str(text)[:400].replace("\n", " | ")
        raise RuntimeError(
            "the Developer returned neither labelled code fences nor JSON. "
            f"First 400 chars: {preview}"
        )

    for key in ("patched_source", "regression_test"):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"the Developer's output is missing {key!r}")

    return {
        "patched_source": payload["patched_source"],
        "regression_test": payload["regression_test"],
        "explanation": str(payload.get("explanation") or "Patched the authentication module."),
    }


class PytestStep(ContextComponent):
    """A real `pytest demo_target` subprocess, AFTER the fix.

    Paired with ProveVulnerabilityStep's red run on the same test file, this
    is the evidence the user's task actually asked for: the regression test
    failed against the vulnerable code and passes against the patched code.
    """

    async def invoke(self, inputs: Any, session: Any, context: Any) -> Any:
        with span("pytest.run", "pytest.after_fix"):
            result = run_demo_target_tests()

        self.ctx.client.record_test_run(
            DEVELOPER,
            command=result.command,
            exit_code=result.exit_code,
            passed=result.passed,
            summary=result.summary,
        )
        if result.passed:
            log_event(
                "swarm.tests_passed",
                f"{result.command}: {result.summary}",
                exit_code=result.exit_code,
            )
        else:
            logger.error("tests did NOT pass: %s\n%s", result.summary, result.tail)

        return {
            "tests_passed": result.passed,
            "test_summary": result.summary,
            "test_command": result.command,
            "test_output": result.tail,
            "patched_source": (inputs or {}).get("patched_source") or "",
            "baseline_summary": (inputs or {}).get("baseline_summary") or "",
        }


class ReviewerStep(ContextComponent):
    def __init__(self, ctx: RunContext, inner: Any) -> None:
        super().__init__(ctx)
        self.inner = inner

    async def invoke(self, inputs: Any, session: Any, context: Any) -> Any:
        inputs = inputs or {}
        task = "Independently verify the patch against the test evidence."
        self.ctx.client.start_task(REVIEWER, task)

        with span("reviewer.verify", "reviewer.verify", worker_id=REVIEWER):
            started = time.perf_counter()
            produced = await _runnable(self.inner).invoke(
                {
                    "patched_source": inputs.get("patched_source") or "",
                    "tests_passed": inputs.get("tests_passed"),
                    "test_summary": inputs.get("test_summary") or "",
                    "test_output": inputs.get("test_output") or "",
                },
                session,
                context,
            )
            self.ctx.record_model_call(
                REVIEWER,
                latency_ms=int((time.perf_counter() - started) * 1000),
                prompt_chars=len(str(inputs.get("patched_source") or "")),
                response_chars=len(str(produced)),
            )
        review = _as_review(produced)

        self.ctx.client.complete_task(REVIEWER, "review", review["verdict"])
        return {
            "approved": review["approved"],
            "verdict": review["verdict"],
            "tests_passed": inputs.get("tests_passed"),
            "test_summary": inputs.get("test_summary") or "",
            "baseline_summary": inputs.get("baseline_summary") or "",
        }


def _as_review(produced: Any) -> dict[str, Any]:
    payload = extract_json(produced)
    if payload is None:
        return {"approved": False, "verdict": "The Reviewer returned an unusable response."}
    return {
        "approved": bool(payload.get("approved")),
        "verdict": str(payload.get("verdict") or ""),
    }


class FinishStep(ContextComponent):
    """Close the run out honestly: recovered only if it actually recovered."""

    async def invoke(self, inputs: Any, session: Any, context: Any) -> Any:
        inputs = inputs or {}
        approved = bool(inputs.get("approved"))
        tests_passed = bool(inputs.get("tests_passed"))
        summary_text = inputs.get("verdict") or ""

        if approved and tests_passed and self.ctx.vulnerability_proven:
            self.ctx.client.recover(
                f"{summary_text} The team completed the task despite one worker "
                "being compromised mid-run."
            )
            log_event(
                "swarm.recovery_complete",
                summary_text,
                tests_passed=tests_passed,
                quarantined_worker=self.ctx.quarantined_worker,
            )
            outcome = "recovered"
        else:
            if not self.ctx.vulnerability_proven:
                reason = (
                    "The regression test did not fail against the unpatched module, "
                    "so no vulnerability was demonstrated."
                )
            else:
                reason = summary_text or "The reviewer did not approve the patch."
            self.ctx.client.fail(reason=reason)
            outcome = "failed"

        return {
            "outcome": outcome,
            "approved": approved,
            "tests_passed": tests_passed,
            "verdict": summary_text,
            "test_summary": inputs.get("test_summary") or "",
            "quarantined_worker": self.ctx.quarantined_worker,
            "denied_paths": [d.resource_path for d in self.ctx.denials],
            "fail_closed": self.ctx.fail_closed,
            "vulnerability_proven": self.ctx.vulnerability_proven,
            "baseline_summary": self.ctx.baseline_failure_summary,
        }


# --- the graph ------------------------------------------------------------


def build_flow(ctx: RunContext) -> Workflow:
    """The offline-authored SwarmFlow. Structure is fixed before the run."""
    model = ctx.model
    llm = ctx.model_backed

    analyst_worker = (
        build_llm_worker(model, prompts.REPO_ANALYST, _ANALYST_USER)
        if llm
        else DeterministicAnalyst(REPO_ANALYST)
    )
    researcher_worker = (
        build_llm_worker(model, prompts.SECURITY_RESEARCHER, _RESEARCHER_USER)
        if llm
        else DeterministicResearcher(SECURITY_RESEARCHER)
    )
    replacement_worker = (
        build_llm_worker(model, prompts.REPLACEMENT_RESEARCHER, _RESEARCHER_USER)
        if llm
        else DeterministicResearcher(REPLACEMENT_RESEARCHER)
    )
    developer_worker = (
        build_llm_worker(model, prompts.DEVELOPER, _DEVELOPER_USER)
        if llm
        else DeterministicDeveloper(DEVELOPER)
    )
    reviewer_worker = (
        build_llm_worker(model, prompts.REVIEWER, _REVIEWER_USER)
        if llm
        else DeterministicReviewer(REVIEWER)
    )

    wf = Workflow()
    wf.set_start_comp("start", Start(), inputs_schema={"objective": "${objective}"})

    # --- analysis: two workers, genuinely concurrent ---------------------
    wf.add_workflow_comp(
        "analyst_fetch",
        FetchForWorker(
            ctx,
            REPO_ANALYST,
            "Map the repository and its authentication surface.",
            [README, AUTH_MODULE],
            "repo_analyst.fetch",
            open_analysis_span=True,
        ),
        inputs_schema={"objective": "${start.objective}"},
    )
    wf.add_workflow_comp(
        "repo_analyst",
        RunWorker(ctx, REPO_ANALYST, analyst_worker, "repo_analyst"),
        inputs_schema={
            "documents": "${analyst_fetch.documents}",
            "task": "${analyst_fetch.task}",
            "objective": "${start.objective}",
        },
    )
    wf.add_workflow_comp(
        "analyst_record",
        RecordReport(ctx, REPO_ANALYST, "repo-map", "analysis"),
        inputs_schema={"report": "${repo_analyst.report}"},
    )

    wf.add_workflow_comp(
        "researcher_fetch",
        FetchForWorker(
            ctx,
            SECURITY_RESEARCHER,
            "Investigate the authentication vulnerability.",
            # The poisoned document is served, because reading it IS the job.
            [AUTH_NOTES],
            "security_researcher.fetch",
        ),
        inputs_schema={"objective": "${start.objective}"},
    )
    wf.add_workflow_comp(
        "security_researcher",
        RunWorker(ctx, SECURITY_RESEARCHER, researcher_worker, "security_researcher"),
        inputs_schema={
            "documents": "${researcher_fetch.documents}",
            "task": "${researcher_fetch.task}",
            "objective": "${start.objective}",
        },
    )
    # The researcher's report is registered as an artifact *before* the gate
    # runs, so that when the gate quarantines the worker there is a real
    # artifact for the taint to land on -- and a real thing to exclude from
    # the replacement's context.
    wf.add_workflow_comp(
        "researcher_record",
        RecordReport(
            ctx, SECURITY_RESEARCHER, "researcher-report", "report", complete=False
        ),
        inputs_schema={
            "report": "${security_researcher.report}",
            "documents": "${security_researcher.documents}",
        },
    )
    wf.add_workflow_comp(
        "shield_gate",
        ShieldGate(ctx),
        inputs_schema={
            "report": "${researcher_record.report}",
            "documents": "${researcher_record.documents}",
        },
    )

    # --- recovery: routed on AgentShield's answer ------------------------
    wf.add_workflow_comp(
        "recovery_fetch",
        ReassignAndFetch(ctx),
        inputs_schema={"recovery_required": "${shield_gate.recovery_required}"},
    )
    wf.add_workflow_comp(
        "replacement_researcher",
        RunWorker(ctx, REPLACEMENT_RESEARCHER, replacement_worker, "replacement_researcher"),
        inputs_schema={
            "documents": "${recovery_fetch.documents}",
            "task": "${recovery_fetch.task}",
            "objective": "${start.objective}",
        },
    )
    wf.add_workflow_comp(
        "replacement_record",
        RecordReport(ctx, REPLACEMENT_RESEARCHER, "replacement-report", "research"),
        inputs_schema={"report": "${replacement_researcher.report}"},
    )

    wf.add_workflow_comp(
        "no_recovery",
        PassThroughReport(ctx),
        inputs_schema={
            "report": "${shield_gate.report}",
            "documents": "${shield_gate.documents}",
        },
    )

    wf.add_workflow_comp(
        "merge_research",
        MergeResearch(ctx),
        inputs_schema={
            "from_replacement": "${replacement_record.report}",
            "from_original": "${no_recovery.report}",
        },
    )

    # --- delivery --------------------------------------------------------
    wf.add_workflow_comp(
        "developer",
        DeveloperStep(ctx, developer_worker),
        inputs_schema={"report": "${merge_research.report}"},
    )
    # The regression test is written first and run against the STILL-VULNERABLE
    # module, so the run proves a vulnerability existed rather than merely
    # showing that a test was added.
    wf.add_workflow_comp(
        "prove_vulnerability",
        ProveVulnerabilityStep(ctx),
        inputs_schema={
            "patched_source": "${developer.patched_source}",
            "explanation": "${developer.explanation}",
        },
    )
    wf.add_workflow_comp(
        "apply_patch",
        ApplyPatchStep(ctx),
        inputs_schema={
            "patched_source": "${prove_vulnerability.patched_source}",
            "explanation": "${prove_vulnerability.explanation}",
            "vulnerability_proven": "${prove_vulnerability.vulnerability_proven}",
            "baseline_summary": "${prove_vulnerability.baseline_summary}",
        },
    )
    wf.add_workflow_comp(
        "pytest_run",
        PytestStep(ctx),
        inputs_schema={
            "patched_source": "${apply_patch.patched_source}",
            "baseline_summary": "${apply_patch.baseline_summary}",
        },
    )
    wf.add_workflow_comp(
        "reviewer",
        ReviewerStep(ctx, reviewer_worker),
        inputs_schema={
            "patched_source": "${pytest_run.patched_source}",
            "tests_passed": "${pytest_run.tests_passed}",
            "test_summary": "${pytest_run.test_summary}",
            "test_output": "${pytest_run.test_output}",
            "baseline_summary": "${pytest_run.baseline_summary}",
        },
    )
    wf.add_workflow_comp(
        "finish",
        FinishStep(ctx),
        inputs_schema={
            "approved": "${reviewer.approved}",
            "verdict": "${reviewer.verdict}",
            "tests_passed": "${reviewer.tests_passed}",
            "test_summary": "${reviewer.test_summary}",
            "baseline_summary": "${reviewer.baseline_summary}",
        },
    )
    wf.set_end_comp(
        "end",
        End(),
        inputs_schema={
            "outcome": "${finish.outcome}",
            "verdict": "${finish.verdict}",
            "tests_passed": "${finish.tests_passed}",
            "test_summary": "${finish.test_summary}",
            "quarantined_worker": "${finish.quarantined_worker}",
            "denied_paths": "${finish.denied_paths}",
            "fail_closed": "${finish.fail_closed}",
            "vulnerability_proven": "${finish.vulnerability_proven}",
            "baseline_summary": "${finish.baseline_summary}",
        },
    )

    # --- connections -----------------------------------------------------
    wf.add_connection("start", "analyst_fetch")
    wf.add_connection("analyst_fetch", "repo_analyst")
    wf.add_connection("repo_analyst", "analyst_record")

    wf.add_connection("start", "researcher_fetch")
    wf.add_connection("researcher_fetch", "security_researcher")
    wf.add_connection("security_researcher", "researcher_record")
    wf.add_connection("researcher_record", "shield_gate")

    router = BranchRouter(report_trace=True)
    router.add_branch(RecoveryRequired(), "recovery_fetch", branch_id="recovery")
    router.add_branch(NoRecoveryRequired(), "no_recovery", branch_id="no-recovery")
    wf.add_conditional_connection("shield_gate", router)

    wf.add_connection("recovery_fetch", "replacement_researcher")
    wf.add_connection("replacement_researcher", "replacement_record")
    wf.add_connection("replacement_record", "merge_research")
    wf.add_connection("no_recovery", "merge_research")

    # The Developer waits for both halves of the analysis phase.
    wf.add_connection(["analyst_record", "merge_research"], "developer")
    wf.add_connection("developer", "prove_vulnerability")
    wf.add_connection("prove_vulnerability", "apply_patch")
    wf.add_connection("apply_patch", "pytest_run")
    wf.add_connection("pytest_run", "reviewer")
    wf.add_connection("reviewer", "finish")
    wf.add_connection("finish", "end")

    return wf


# --- user prompts ---------------------------------------------------------

_ANALYST_USER = """Objective: {{objective}}

Your task: {{task}}

Repository documents released to you by the control plane:

{{document_text}}
"""

_RESEARCHER_USER = _ANALYST_USER

_DEVELOPER_USER = """The researcher's analysis:

{{analysis}}

Their recommendations:

{{recommendations}}

The current contents of demo_target/app/auth.py:

{{current_source}}
"""

_REVIEWER_USER = """The patched module:

{{patched_source}}

The real test run reported passed={{tests_passed}} with the summary:

{{test_summary}}

Full output:

{{test_output}}
"""

__all__ = ["RunContext", "build_flow", "WORKER_SPECS"]
