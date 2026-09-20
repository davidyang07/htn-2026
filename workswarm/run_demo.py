"""The single command that runs the Live Swarm Demo.

    python workswarm/run_demo.py

Requires AgentShield's backend to be reachable (``AGENTSHIELD_BASE_URL``,
default ``http://localhost:8100``). Everything else -- a model endpoint, a
Sentry DSN, an OpenAI key, a RunPod pod -- is optional, and the run says which
of them were actually in play.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from openjiuwen.core.session import WORKFLOW_EXECUTE_TIMEOUT  # noqa: E402
from openjiuwen.core.workflow import create_workflow_session  # noqa: E402

from workswarm import telemetry  # noqa: E402
from workswarm.agentshield_client import (  # noqa: E402
    AgentShieldClient,
    AgentShieldUnavailable,
)
from workswarm.config import (  # noqa: E402
    DEMO_TARGET,
    OBJECTIVE,
    agentshield_base_url,
    require_real_models,
    resolve_model,
    workswarm_config_path,
)
from workswarm.flows.auth_fix_flow import WORKER_SPECS, RunContext, build_flow  # noqa: E402

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


class _QuietWorkSwarm(logging.Filter):
    """Drop sub-WARNING records from WorkSwarm's own loggers.

    A filter rather than `setLevel`, because these loggers are configured by
    the library at import time and a level set afterwards does not stick.
    Applied to the root handler, so it also covers loggers created later.
    """

    def filter(self, record: logging.LogRecord) -> bool:
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
        logging.getLogger(name).setLevel(logging.WARNING)


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


async def _run() -> int:
    model = resolve_model()
    model_backed = model.configured

    # A verification run must not quietly demonstrate something weaker than it
    # claims. With AGENTSHIELD_DEMO_REAL_MODELS set, an unresolved endpoint is
    # a hard failure rather than a silent fallback to deterministic stand-ins.
    if require_real_models() and not model_backed:
        config_path = workswarm_config_path()
        raise SystemExit(
            "\n".join(
                [
                    "AGENTSHIELD_DEMO_REAL_MODELS is set, but no model endpoint could",
                    "be resolved, so this run would have used deterministic stand-ins.",
                    "",
                    "Resolution order (first configured wins):",
                    "  1. AGENTSHIELD_MODEL_BASE_URL (+ _API_KEY / _NAME / _PROVIDER)",
                    f"  2. WorkSwarm's own config.yaml -- {config_path or 'not found'}",
                    "  3. RUNPOD_MODEL_BASE_URL",
                    "  4. OPENAI_API_KEY",
                    "",
                    "Configure one of those, or unset AGENTSHIELD_DEMO_REAL_MODELS",
                    "to run with deterministic workers.",
                ]
            )
        )

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
    return _report(result, ctx)


def _report(result: dict, ctx: RunContext) -> int:
    outcome = result.get("outcome")
    print()
    print("  ---------------------------------------------------------------")
    print(f"  attack detected   : {'yes' if ctx.denials else 'NO'}")
    print(f"  denied paths      : {result.get('denied_paths') or '(none)'}")
    print(f"  quarantined       : {result.get('quarantined_worker') or '(none)'}")
    print(f"  vuln proven       : {result.get('vulnerability_proven')}")
    print(f"    before the fix  : {result.get('baseline_summary')}   <- regression test RED")
    print(f"    after the fix   : {result.get('test_summary')}   <- regression test GREEN")
    print(f"  tests passed      : {result.get('tests_passed')}")
    print(f"  reviewer verdict  : {result.get('verdict')}")
    print(f"  outcome           : {outcome}")
    print(f"  model-backed      : {ctx.model_backed}")
    if ctx.model_backed:
        print(f"  model             : {ctx.model.describe()}")
    print("  ---------------------------------------------------------------")
    print()

    if result.get("fail_closed"):
        print("  NOTE: at least one request was denied because AgentShield could not")
        print("        be reached. The control plane fails closed by design, but this")
        print("        run's denial was a network failure, not the policy.")
        print()

    if not ctx.denials:
        print("  The injection did not land this run: the Security Researcher never")
        print("  requested a protected path, so there was nothing for the policy to")
        print("  deny. Re-run, or tune demo_target/docs/auth_notes.md -- never")
        print("  hardcode the request.")
        print()

    return 0 if outcome == "recovered" else 1


def main() -> int:
    _configure_logging()
    telemetry.init()
    with telemetry.transaction("agentshield.demo", op="agentshield.demo"):
        return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
