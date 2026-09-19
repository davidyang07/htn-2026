#!/usr/bin/env python3
"""Runs the golden demo (Priority 2) and writes a narrative report to
backend/.artifacts/golden_demo/. Pass --model-provider vllm together with
--model-name to use a real Qwen/vLLM endpoint (requires VLLM_BASE_URL set --
see README's "Real (LLM-backed) agents" section); defaults to the
deterministic mock provider.
"""

import argparse
import json
from pathlib import Path

from app.benchmark.golden_demo import run_golden_demo, summarize_golden_demo_narrative

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / ".artifacts" / "golden_demo"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-provider", choices=["mock", "vllm"], default="mock")
    parser.add_argument(
        "--model-name",
        default=None,
        help="Model id the vLLM server serves (e.g. Qwen/Qwen2.5-7B-Instruct). "
        "Required with --model-provider vllm: the default config value is a "
        "mock placeholder that a real server rejects with a 404.",
    )
    args = parser.parse_args()
    if args.model_provider == "vllm" and args.model_name is None:
        parser.error("--model-name is required with --model-provider vllm")

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    result = run_golden_demo(model_provider=args.model_provider, model_name=args.model_name)
    key_beats = summarize_golden_demo_narrative(result.narrative)

    lines = ["# AgentShield Golden Demo", "", "## Key beats", ""]
    lines.extend(key_beats)
    lines.extend(["", "## Full narrative", ""])
    lines.extend(result.narrative)
    (ARTIFACTS_DIR / "report.md").write_text("\n".join(lines))

    summary = {
        "baseline_metrics": result.baseline.metrics,
        "recommendation": result.recommendation.description if result.recommendation else None,
        "rerun_metrics": result.rerun.metrics if result.rerun else None,
    }
    (ARTIFACTS_DIR / "result.json").write_text(json.dumps(summary, indent=2))

    print("\n".join(key_beats))
    print(f"\nWrote {ARTIFACTS_DIR / 'report.md'} and {ARTIFACTS_DIR / 'result.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
