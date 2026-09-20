"""Verify the optional RunPod/vLLM endpoint without exposing credentials.

Run from the repository root:

    backend/.venv/bin/python -m workswarm.check_runpod
"""

from __future__ import annotations

import argparse
import json
from typing import Any
from urllib.parse import urlsplit

from workswarm.config import ModelConfig, resolve_runpod_model
from workswarm.runpod_verify import RunPodVerifier, StartupResult, VerificationReport


def report_payload(
    model: ModelConfig,
    report: VerificationReport,
    startup: StartupResult | None = None,
) -> dict[str, Any]:
    """Build credential-free output suitable for logs and bug reports."""
    first = report.first_completion.probe if report.first_completion else None
    warm = report.warm_completion.probe if report.warm_completion else None
    models = report.models
    return {
        "ready": report.ready,
        "endpoint_host": urlsplit(model.api_base).hostname or "",
        "model": model.model_name,
        "cold_start_ms": startup.cold_start_ms if startup else None,
        "startup_attempts": startup.attempts if startup else None,
        "health": {
            "ok": report.health.ok,
            "status_code": report.health.status_code,
            "latency_ms": report.health.latency_ms,
            "detail": report.health.detail,
        },
        "models": {
            "ok": models.probe.ok if models else False,
            "status_code": models.probe.status_code if models else None,
            "latency_ms": models.probe.latency_ms if models else None,
            "expected_model_found": models.expected_model_found if models else False,
            "advertised_ids": list(models.model_ids) if models else [],
        },
        "first_completion": {
            "ok": first.ok if first else False,
            "status_code": first.status_code if first else None,
            "latency_ms": first.latency_ms if first else None,
        },
        "warm_completion": {
            "ok": warm.ok if warm else False,
            "status_code": warm.status_code if warm else None,
            "latency_ms": warm.latency_ms if warm else None,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=0,
        help="poll /health for this long and report cold-start time",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=2,
        help="health polling interval used with --wait-seconds",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    model = resolve_runpod_model()
    if model is None:
        print(json.dumps({"ready": False, "reason": "RUNPOD_MODEL_BASE_URL is not configured"}))
        return 2

    verifier = RunPodVerifier(model)
    startup = None
    try:
        if args.wait_seconds > 0:
            startup = verifier.wait_for_health(
                max_wait_s=args.wait_seconds,
                poll_interval_s=max(0, args.poll_seconds),
            )
        report = verifier.verify()
    finally:
        verifier.close()

    print(json.dumps(report_payload(model, report, startup), indent=2, sort_keys=True))
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
