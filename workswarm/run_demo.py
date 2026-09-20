"""The single command that runs the Live Swarm Demo.

    python workswarm/run_demo.py

Requires AgentShield's backend to be reachable (``AGENTSHIELD_BASE_URL``,
default ``http://localhost:8100``). Everything else -- a model endpoint, a
Sentry DSN, an OpenAI key, a RunPod pod -- is optional, and the run says which
of them were actually in play.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
import sys
import time
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workswarm import telemetry  # noqa: E402
from workswarm.agentshield_client import (  # noqa: E402
    AgentShieldClient,
    AgentShieldUnavailable,
)
from workswarm.config import (  # noqa: E402
    DEMO_TARGET,
    OBJECTIVE,
    agentshield_base_url,
    enforce_real_model_mode,
    require_real_models,
    resolve_model,
)
from workswarm.outcome import denied_worker_requests  # noqa: E402

if TYPE_CHECKING:
    from workswarm.flows.auth_fix_flow import RunContext

logger = logging.getLogger("workswarm.run_demo")

#: Whole-workflow budget. Five real model calls on a reasoning model,
#: plus two real pytest runs, comfortably.
WORKFLOW_TIMEOUT_S = float(os.environ.get("AGENTSHIELD_DEMO_TIMEOUT_S", "1800"))


# The WorkSwarm engine emits two JSON lines per graph vertex at INFO, plus
# alembic/chromadb/parser registration chatter at import. The demo's own
# narration is what a reader needs from this terminal.
_NOISY_LOGGERS = frozenset(
    {
        "openjiuwen",
        "jiuwenswarm",
        "httpx",
        "httpcore",
        "common",
        "graph",
        "workflow",
        "session",
        "component",
        "model",
        "runner",
        "llm",
        "alembic",
        "chromadb",
    }
)

_HARMLESS_WARNING_PREFIXES = (
    "OpenRouter explicit prompt caching is enabled but unsupported for model ",
)


class _QuietWorkSwarm(logging.Filter):
    """Drop sub-WARNING records from WorkSwarm's own loggers.

    A filter rather than `setLevel`, because these loggers are configured by
    the library at import time and a level set afterwards does not stick.
    Applied to the root handler, so it also covers loggers created later.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.getMessage().startswith(_HARMLESS_WARNING_PREFIXES):
            return False
        if record.levelno >= logging.WARNING:
            return True
        return record.name.split(".", 1)[0] not in _NOISY_LOGGERS


def _configure_logging() -> None:
    # A real model writes prose, and prose contains characters the Windows
    # console's default cp1252 cannot encode (an arrow in a docstring is
    # enough). Without this, logging a model response raises
    # UnicodeEncodeError and takes the run down with it.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    # OpenJiuwen owns a separate logging stack, so stdlib logger levels and
    # handler filters do not silence it. At INFO that stack records complete
    # model requests and responses (including reasoning text) and also writes
    # them to ./logs/. Configure the public logging API before the workflow is
    # built: WARNING keeps actionable engine failures, while console-only
    # output ensures prompts/completions never become demo log files.
    # Importing OpenJiuwen initializes optional connector/parser registries,
    # which emit dozens of INFO lines before its public logging API can be
    # configured. Capture only that import-time chatter. The immediately
    # following reconfiguration replaces those temporary stream handlers.
    import_output = io.StringIO()
    with contextlib.redirect_stdout(import_output), contextlib.redirect_stderr(
        import_output
    ):
        from openjiuwen.core.common.logging.log_config import configure_log_config

    configure_log_config(
        {
            "backend": "default",
            "level": "WARNING",
            "output": ["console"],
            "interface_output": ["console"],
            "performance_output": ["console"],
            "loggers": {},
        }
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-5s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    quiet = _QuietWorkSwarm()
    for handler in logging.getLogger().handlers:
        handler.addFilter(quiet)
    for name in _NOISY_LOGGERS:
        noisy_logger = logging.getLogger(name)
        noisy_logger.setLevel(logging.WARNING)
        # Logger-level filtering also covers handlers WorkSwarm creates lazily
        # after this setup (notably the `llm` logger on the first model call).
        noisy_logger.addFilter(quiet)


def _preflight(client: AgentShieldClient) -> None:
    if not client.health():
        raise SystemExit(
            f"AgentShield is not reachable at {client.base_url}.\n"
            "Start it first:\n"
            "  cd backend && .venv/Scripts/uvicorn app.main:app --port 8100\n"
            "or set AGENTSHIELD_BASE_URL to wherever it is running."
        )

    auth_module = DEMO_TARGET / "app" / "auth.py"
    if "token expired" in auth_module.read_text(encoding="utf-8"):
        raise SystemExit(
            "\n".join(
                [
                    "demo_target/app/auth.py is already patched from a previous run.",
                    "Reset it first:",
                    "  python workswarm/reset_demo.py",
                ]
            )
        )


async def _run(started_at: float) -> int:
    # Kept lazy so _configure_logging runs before WorkSwarm imports initialize
    # connector, vector-store and document-parser registries. WorkSwarm's
    # optional integrations also import deprecated third-party APIs; hide only
    # those import-time deprecation notices, not runtime or security warnings.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from openjiuwen.core.session import WORKFLOW_EXECUTE_TIMEOUT
        from openjiuwen.core.workflow import create_workflow_session

        from workswarm.flows.auth_fix_flow import WORKER_SPECS, RunContext, build_flow

    model = resolve_model()
    model_backed = model.configured

    # A verification run must not quietly demonstrate something weaker than it
    # claims. With AGENTSHIELD_DEMO_REAL_MODELS set, an unresolved endpoint is
    # a hard failure rather than a silent fallback to deterministic stand-ins.
    try:
        enforce_real_model_mode(model)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    client = AgentShieldClient(agentshield_base_url())
    _preflight(client)

    print()
    print("  AgentShield Live Swarm Demo")
    print(f"  control plane : {client.base_url}")
    print(
        "  workers       : "
        + (
            f"MODEL-BACKED -- {model.describe()}"
            if model_backed
            else "deterministic stand-ins (no model endpoint configured)"
        )
    )
    if require_real_models():
        print("  real models   : REQUIRED (AGENTSHIELD_DEMO_REAL_MODELS is set)")
    print(f"  telemetry     : {'Sentry enabled' if telemetry.is_enabled() else 'Sentry off'}")
    print(f"  objective     : {OBJECTIVE}")
    print()

    ctx = RunContext(client=client, model=model, model_backed=model_backed)

    specs = [{**spec, "model_backed": model_backed} for spec in WORKER_SPECS]
    session = client.create_session(OBJECTIVE, specs)
    print(f"  session       : {session['session_id']}")
    print("  watch it at   : http://localhost:3000/demo")
    print()

    flow = build_flow(ctx)
    # WorkSwarm's default workflow timeout is 60 seconds, which is fine for
    # deterministic stand-ins and far too short for five real model calls --
    # the sponsor model is a reasoning model and spends thousands of tokens
    # thinking before its first output token.
    workflow_session = create_workflow_session(
        envs={WORKFLOW_EXECUTE_TIMEOUT: WORKFLOW_TIMEOUT_S}
    )

    try:
        output = await flow.invoke({"objective": OBJECTIVE}, workflow_session)
    except Exception as exc:
        logger.exception("the SwarmFlow raised")
        try:
            client.fail(reason=f"The workflow raised: {exc}")
        except AgentShieldUnavailable:
            pass
        return 1
    finally:
        ctx.analysis_span.close()

    result = (output.result or {}).get("output") or {}
    return _report(result, ctx, elapsed_s=time.perf_counter() - started_at)


def _report(result: dict, ctx: RunContext, *, elapsed_s: float) -> int:
    outcome = result.get("outcome")
    denied_paths = [decision.resource_path for decision in ctx.denials]
    attack_paths = denied_worker_requests(ctx.researcher_requested_paths, denied_paths)
    request_source = (
        "real model output" if ctx.model_backed else "document-driven deterministic stand-in"
    )
    print()
    print("  ---------------------------------------------------------------")
    print(f"  attack landed     : {'yes' if attack_paths else 'NO'}")
    print(f"  request source    : {request_source}")
    print(f"  researcher asked  : {ctx.researcher_requested_paths or '(none)'}")
    print(f"  denied paths      : {result.get('denied_paths') or '(none)'}")
    print(f"  quarantined       : {result.get('quarantined_worker') or '(none)'}")
    print(f"  trusted artifacts : {ctx.trusted_artifact_ids or '(none)'}")
    print(f"  tainted artifacts : {ctx.tainted_artifact_ids or '(none)'}")
    print(f"  vuln proven       : {result.get('vulnerability_proven')}")
    print(f"    before the fix  : {result.get('baseline_summary')}   <- regression test RED")
    print(f"    after the fix   : {result.get('test_summary')}   <- regression test GREEN")
    print(f"  tests passed      : {result.get('tests_passed')}")
    print(f"  reviewer verdict  : {result.get('verdict')}")
    print(f"  outcome           : {outcome}")
    print(f"  model-backed      : {ctx.model_backed}")
    if ctx.model_backed:
        print(f"  model             : {ctx.model.describe()}")
    print(f"  wall-clock        : {elapsed_s:.3f} seconds")
    print("  ---------------------------------------------------------------")
    print()

    if result.get("fail_closed"):
        print("  NOTE: at least one request was denied because AgentShield could not")
        print("        be reached. The control plane fails closed by design, but this")
        print("        run's denial was a network failure, not the policy.")
        print()

    if not attack_paths:
        print("  The injection did not land this run: the Security Researcher never")
        print("  requested a protected path, so there was nothing for the policy to")
        print("  deny. Re-run, or tune demo_target/docs/auth_notes.md -- never")
        print("  hardcode the request.")
        print()

    return 0 if outcome == "recovered" else 1


def main() -> int:
    started_at = time.perf_counter()
    _configure_logging()
    telemetry.init()
    with telemetry.transaction("agentshield.demo", op="agentshield.demo"):
        return asyncio.run(_run(started_at))


if __name__ == "__main__":
    raise SystemExit(main())
