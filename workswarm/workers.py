"""The demo's workers, and the one honest fallback when no model is configured.

Every worker in this flow is a real WorkSwarm workflow component. When a model
endpoint is configured (see `workswarm/config.py`) the reasoning workers are
WorkSwarm's own ``LLMComponent``, with a structured JSON contract:

    {"analysis": "...", "requested_files": [...], "recommendations": [...]}

When no endpoint is configured the same components are replaced by
``DeterministicResearcher``/``DeterministicAnalyst``, which are *not* scripts
of the demo. They are a deliberately naive instruction-follower: they read the
document AgentShield handed them and extract the file paths that the document
instructs the reader to fetch. If the poisoned paragraph is edited to name a
different path, the stand-in asks for that path instead; if the paragraph is
deleted, it asks for nothing. Nothing here hardcodes
``demo_target/secrets/demo_secret.txt``.

That distinction matters, and it is surfaced rather than hidden: every worker
is registered with ``model_backed`` set truthfully, the /demo screen labels it,
and `docs/DEMO.md` says which mode a given run was in.

The contract that makes any of this safe is the same in both modes: **the
worker has no filesystem capability.** It can only name the resources it wants.
Every name goes to AgentShield, and only what comes back allowed is ever read.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from openjiuwen.core.foundation.llm import ModelClientConfig, ModelRequestConfig
from openjiuwen.core.workflow import (
    LLMCompConfig,
    LLMComponent,
    WorkflowComponent,
)

from workswarm.config import ModelConfig
from workswarm.injection import follow_document_instructions
from workswarm.replacement_provider import ProviderUse, ReplacementFailover

logger = logging.getLogger(__name__)

#: The structured contract every reasoning worker answers with.
REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "analysis": {"type": "string"},
        "requested_files": {"type": "array", "items": {"type": "string"}},
        "recommendations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["analysis", "requested_files", "recommendations"],
}


def build_llm_worker(
    model: ModelConfig, system_prompt: str, user_prompt: str
) -> LLMComponent:
    """A genuine WorkSwarm LLM worker with the structured report contract.

    `model.extras` carries whatever the resolved endpoint needs beyond the
    basics -- `endpoint_profile` in particular, which is how WorkSwarm routes
    an OpenAI-compatible provider such as OpenRouter. Passing it through is
    what lets the demo reuse WorkSwarm's own configured model instead of
    duplicating the credential.
    """
    client_kwargs: dict[str, Any] = {
        "client_provider": model.provider,
        "api_key": model.api_key,
        "api_base": model.api_base,
        "timeout": 120.0,
    }
    client_kwargs.update(model.extras)

    return LLMComponent(
        LLMCompConfig(
            model_client_config=ModelClientConfig(**client_kwargs),
            model_config=ModelRequestConfig(
                model=model.model_name,
                temperature=0.2,
                # Generous on purpose. A reasoning model counts its thinking
                # against this budget -- the sponsor model spent 5224 reasoning
                # tokens before its first output token on the Developer's task,
                # and budgets of 4000 and 16000 both produced silently EMPTY
                # completions once the upstream analysis grew. The Developer's
                # prompt is trimmed as well (see auth_fix_flow.DeveloperStep);
                # both were needed.
                max_tokens=32000,
            ),
            template_content=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            # Text, not `{"type": "json"}`, for two reasons. First, the three
            # worker kinds answer with three *different* shapes (a report, a
            # patch, a review), so one component-level JSON schema cannot
            # describe them all. Second, a real model routinely wraps JSON in
            # a markdown fence or a sentence of preamble, and rejecting the
            # whole response for that is brittle -- `extract_json` below is
            # tolerant of exactly those habits while still refusing anything
            # that is not actually JSON.
            response_format={"type": "text"},
            output_config={"report": {"type": "string", "required": True}},
        )
    )


class FailoverWorker(WorkflowComponent):
    """Run the replacement on RunPod, with the normal P0 worker as backup."""

    def __init__(
        self,
        primary: Any,
        fallback: Any,
        *,
        runpod_model: ModelConfig,
        fallback_model: ModelConfig,
    ) -> None:
        super().__init__()
        self.primary = primary
        self.fallback = fallback
        self.failover = ReplacementFailover(runpod_model, fallback_model)

    @property
    def provider_use(self) -> ProviderUse | None:
        return self.failover.last_use

    async def invoke(self, inputs: Any, session: Any, context: Any) -> Any:
        async def call(worker: Any) -> Any:
            runnable = worker.executable if hasattr(worker, "executable") else worker
            return await runnable.invoke(inputs, session, context)

        return await self.failover.invoke(
            lambda: call(self.primary),
            lambda: call(self.fallback),
        )


#: A fenced code block, with or without a language tag.
_FENCE_RE = re.compile(r"```(?:json|python)?\s*(.*?)```", re.S | re.I)


def extract_json(raw: Any) -> dict[str, Any] | None:
    """Pull a JSON object out of whatever a model actually returned.

    Handles the three things models reliably do to JSON: wrap it in a markdown
    fence, put a sentence in front of it, and put a sentence after it. What it
    does *not* do is guess: if nothing parses as a JSON object, it returns None
    and the caller decides how to fail.
    """
    if isinstance(raw, dict):
        # The component's own output envelope, or an already-parsed payload.
        if set(raw) == {"report"}:
            return extract_json(raw["report"])
        return raw
    if not isinstance(raw, str):
        return None

    candidates: list[str] = []
    candidates.extend(match.strip() for match in _FENCE_RE.findall(raw))
    candidates.append(raw.strip())

    # Last resort: the outermost {...} span in the text.
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        candidates.append(raw[start : end + 1])

    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


# --- the deterministic stand-in -------------------------------------------


class DeterministicWorker(WorkflowComponent):
    """Base for the no-model workers. Still a real WorkSwarm component: it is
    scheduled, retried and traced by the same workflow engine."""

    def __init__(self, worker_id: str) -> None:
        super().__init__()
        self.worker_id = worker_id


class DeterministicAnalyst(DeterministicWorker):
    """Summarizes whatever documents AgentShield allowed it to receive."""

    async def invoke(self, inputs: Any, session: Any, context: Any) -> Any:
        documents: list[dict[str, str]] = (inputs or {}).get("documents") or []
        lines = [
            f"{d.get('path')}: {len(str(d.get('text', '')).splitlines())} lines"
            for d in documents
        ]
        return {
            "report": json.dumps(
                {
                    "analysis": (
                        "Mapped the repository from the documents the control plane released: "
                        + ("; ".join(lines) if lines else "no documents were released.")
                    ),
                    "requested_files": [],
                    "recommendations": [
                        "The session-token module is the only authentication surface.",
                    ],
                }
            )
        }


class DeterministicResearcher(DeterministicWorker):
    """Investigates the vulnerability, and follows whatever the documents say.

    The second half is the point: this worker treats directives found *inside
    repository content* as if they came from its operator. That is exactly the
    failure an indirect prompt injection exploits in a real model, reproduced
    here without one.
    """

    async def invoke(self, inputs: Any, session: Any, context: Any) -> Any:
        documents: list[dict[str, str]] = (inputs or {}).get("documents") or []

        followed: list[str] = []
        for document in documents:
            for path in follow_document_instructions(str(document.get("text", ""))):
                if path not in followed:
                    followed.append(path)

        # The worker's own legitimate plan, independent of any document.
        plan = ["demo_target/app/auth.py"]
        requested = plan + [p for p in followed if p not in plan]

        analysis = (
            "verify_token() checks the HMAC signature but never enforces the token's "
            "expires_at, even though it accepts a `now` argument for exactly that purpose. "
            "Every token the service has ever issued is therefore valid forever."
        )
        return {
            "report": json.dumps(
                {
                    "analysis": analysis,
                    "requested_files": requested,
                    "recommendations": [
                        "Compare the decoded expires_at against `now` and raise AuthError "
                        "when it has passed.",
                        "Add regression coverage: one expired token rejected, one "
                        "still-valid token accepted.",
                    ],
                }
            )
        }


class DeterministicDeveloper(DeterministicWorker):
    """Produces the patch by transforming the module's actual current source."""

    async def invoke(self, inputs: Any, session: Any, context: Any) -> Any:
        from workswarm.patcher import deterministic_auth_patch

        patched_source, regression_test = deterministic_auth_patch()
        return {
            "patched_source": patched_source,
            "regression_test": regression_test,
            "explanation": (
                "Enforced token expiry in verify_token(): the decoded expires_at is now "
                "compared against `now` and an expired token raises AuthError."
            ),
        }


class DeterministicReviewer(DeterministicWorker):
    """Verifies the patch against the evidence, and only against the evidence."""

    async def invoke(self, inputs: Any, session: Any, context: Any) -> Any:
        tests_passed = bool((inputs or {}).get("tests_passed"))
        summary = (inputs or {}).get("test_summary") or "no test run reported"
        patched_source = (inputs or {}).get("patched_source") or ""

        findings: list[str] = []
        if "token expired" not in patched_source:
            findings.append("The patch does not appear to reject expired tokens.")
        if not tests_passed:
            findings.append(f"The test run did not pass: {summary}")

        return {
            "approved": not findings,
            "verdict": (
                f"Patch verified against a real test run: {summary}."
                if not findings
                else "Rejected: " + " ".join(findings)
            ),
            "findings": findings,
        }


def parse_report(raw: Any) -> dict[str, Any]:
    """Normalize a worker's report into the structured contract.

    Accepts the stand-in's JSON string and whatever a real model actually
    emitted. A worker that returns something unusable yields an empty report
    rather than an exception -- a malformed model response must not take the
    run down, and an empty `requested_files` is a perfectly valid answer.
    """
    payload = extract_json(raw)
    if payload is None:
        text = raw["report"] if isinstance(raw, dict) and "report" in raw else raw
        logger.warning("worker report was not valid JSON; treating it as analysis text")
        return {"analysis": str(text), "requested_files": [], "recommendations": []}

    requested = payload.get("requested_files") or []
    if not isinstance(requested, list):
        requested = []

    recommendations = payload.get("recommendations") or []
    if not isinstance(recommendations, list):
        recommendations = []

    return {
        "analysis": str(payload.get("analysis") or ""),
        "requested_files": [str(p) for p in requested],
        "recommendations": [str(r) for r in recommendations],
    }
