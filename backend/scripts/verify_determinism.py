#!/usr/bin/env python3
"""Runs the canonical seed=42 experiment twice, headless, and diffs the
deterministic projection of the two event sequences (SPEC §6.2 step 5)."""

import json
import sys
from pathlib import Path
from uuid import uuid4

from app.engine.simulate import run_full
from app.events.emitter import EventEmitter
from app.schemas.experiment import ExperimentConfig

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / ".artifacts"

# Matches SPEC §6.2's canonical demo config.
CANONICAL_CONFIG = ExperimentConfig(seed=42, node_count=60)

DETERMINISM_FIELDS = (
    "seq",
    "sim_tick",
    "event_type",
    "agent_id",
    "source_agent_id",
    "target_agent_id",
    "metadata",
)


def _run() -> list[dict]:
    drafts = run_full(CANONICAL_CONFIG)
    events = EventEmitter(experiment_id=uuid4()).emit(drafts)
    return [json.loads(e.model_dump_json()) for e in events]


def main() -> int:
    ARTIFACTS_DIR.mkdir(exist_ok=True)

    run1 = _run()
    run2 = _run()

    (ARTIFACTS_DIR / "run-1.jsonl").write_text("\n".join(json.dumps(e) for e in run1) + "\n")
    (ARTIFACTS_DIR / "run-2.jsonl").write_text("\n".join(json.dumps(e) for e in run2) + "\n")

    proj1 = [tuple(e[f] for f in DETERMINISM_FIELDS) for e in run1]
    proj2 = [tuple(e[f] for f in DETERMINISM_FIELDS) for e in run2]

    if proj1 != proj2:
        print("FAIL: event sequences differ between the two seed=42 runs", file=sys.stderr)
        for i, (a, b) in enumerate(zip(proj1, proj2, strict=False)):
            if a != b:
                print(
                    f"  first divergence at index {i}:\n    run1={a}\n    run2={b}",
                    file=sys.stderr,
                )
                break
        if len(proj1) != len(proj2):
            print(f"  length mismatch: run1={len(proj1)} run2={len(proj2)}", file=sys.stderr)
        return 1

    print(f"PASS: {len(proj1)} events identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
