"""LiveRuntimeSession: registration, the deny cascade, quarantine, tainting,
recovery, and the snapshot shape (docs/MVP_PLAN.md P0.2/P0.7/P0.8).

Follows this repo's existing convention of `asyncio.run(main())` per test
rather than adding a pytest-asyncio dependency (see tests/conftest.py).
"""

import asyncio

import pytest

from app.engine.state import SecurityState
from app.runtime.session import LiveRuntimeSession, UnknownWorkerError
from app.schemas.events import EventType

OBJECTIVE = (
    "Find and fix the authentication vulnerability in this repository, "
    "add regression coverage, and verify the patch."
)
POISONED_DOC = "demo_target/docs/auth_notes.md"
PROTECTED = "demo_target/secrets/demo_secret.txt"


async def _seeded_session() -> LiveRuntimeSession:
    session = LiveRuntimeSession(OBJECTIVE)
    await session.register_worker("repo-analyst", "Repo Analyst")
    await session.register_worker(
        "security-researcher", "Security Researcher", upstream=("repo-analyst",)
    )
    await session.register_worker("developer", "Developer", upstream=("security-researcher",))
    return session


def _types(events) -> list[str]:
    return [e.event_type.value for e in events]


# --- registration and snapshot ------------------------------------------


def test_registration_emits_agent_created_and_shows_up_in_the_snapshot():
    async def main() -> None:
        session = await _seeded_session()
        snapshot = session.snapshot()

        assert {n.id for n in snapshot.nodes} == {
            "repo-analyst",
            "security-researcher",
            "developer",
        }
        assert all(n.agent_kind == "real" for n in snapshot.nodes)
        assert all(n.security_state == SecurityState.HEALTHY for n in snapshot.nodes)
        # The role renders as the node's software_type -- named workers, not
        # agent-000 (docs/ARCHITECTURE.md §6).
        assert {n.software_type for n in snapshot.nodes} == {
            "Repo Analyst",
            "Security Researcher",
            "Developer",
        }
        assert {(e.source, e.target) for e in snapshot.edges} == {
            ("repo-analyst", "security-researcher"),
            ("security-researcher", "developer"),
        }
        assert snapshot.experiment_id == session.session_id
        assert snapshot.last_seq == session.last_seq

    asyncio.run(main())


def test_seq_is_monotonic_across_every_emission():
    async def main() -> None:
        session = await _seeded_session()
        await session.start_worker("repo-analyst", "Map the repository.")
        await session.request_resource("repo-analyst", "demo_target/README.md")
        await session.request_resource("security-researcher", PROTECTED)

        seqs = [e.seq for e in session.bus.since(-1) or []]
        assert seqs == sorted(seqs)
        assert seqs == list(range(len(seqs)))
        assert session.last_seq == seqs[-1]

    asyncio.run(main())


def test_unknown_worker_is_an_error_not_a_silent_no_op():
    async def main() -> None:
        session = await _seeded_session()
        with pytest.raises(UnknownWorkerError):
            await session.request_resource("nobody", "demo_target/README.md")

    asyncio.run(main())


# --- the allow path ------------------------------------------------------


def test_ordinary_request_is_allowed_and_emits_requested_then_executed():
    async def main() -> None:
        session = await _seeded_session()
        grant = await session.request_resource("repo-analyst", "./demo_target/app/auth.py")

        assert grant.decision.allowed is True
        assert grant.decision.normalized_path == "demo_target/app/auth.py"
        assert grant.quarantined is False
        assert grant.recovery_required is False
        assert _types(grant.events) == ["TOOL_REQUESTED", "TOOL_EXECUTED"]
        assert session.workers["repo-analyst"].security_state == SecurityState.HEALTHY

    asyncio.run(main())


def test_reading_the_poisoned_document_is_allowed_it_is_the_job():
    async def main() -> None:
        session = await _seeded_session()
        grant = await session.request_resource("security-researcher", POISONED_DOC)
        assert grant.decision.allowed is True

    asyncio.run(main())


# --- the deny cascade ----------------------------------------------------


def test_protected_request_denies_and_emits_the_full_cascade_in_order():
    async def main() -> None:
        session = await _seeded_session()
        await session.start_worker("security-researcher", "Investigate the vulnerability.")
        grant = await session.request_resource("security-researcher", PROTECTED)

        assert grant.decision.allowed is False
        assert grant.quarantined is True
        assert grant.recovery_required is True
        assert _types(grant.events) == [
            "TOOL_REQUESTED",
            "TOOL_DENIED",
            "POLICY_VIOLATION",
            "ANOMALY_DETECTED",
            "AGENT_QUARANTINED",
        ]

        violation = next(
            e for e in grant.events if e.event_type == EventType.POLICY_VIOLATION
        )
        assert violation.metadata["violation_type"] == "protected_path"
        assert violation.agent_id == "security-researcher"

    asyncio.run(main())


def test_no_event_in_the_cascade_carries_the_secret_contents():
    async def main() -> None:
        session = await _seeded_session()
        await session.request_resource("security-researcher", PROTECTED)

        blob = "".join(e.model_dump_json() for e in session.bus.since(-1) or [])
        assert "AGENTSHIELD_DEMO_SECRET" not in blob

    asyncio.run(main())


def test_denial_quarantines_the_worker():
    async def main() -> None:
        session = await _seeded_session()
        await session.request_resource("security-researcher", PROTECTED)

        worker = session.workers["security-researcher"]
        assert worker.security_state == SecurityState.QUARANTINED
        assert worker.is_active is False
        assert worker.step_quarantined is not None
        assert worker.compromised_by == POISONED_DOC
        assert session.attack_detected is True
        assert session.recovery_required is True
        assert session.workflow_state == "under_attack"
        assert session.snapshot().status == "running"

    asyncio.run(main())


def test_a_quarantined_worker_is_refused_even_an_ordinary_path():
    async def main() -> None:
        session = await _seeded_session()
        await session.request_resource("security-researcher", PROTECTED)

        follow_up = await session.request_resource(
            "security-researcher", "demo_target/README.md"
        )
        assert follow_up.decision.allowed is False
        assert follow_up.decision.rule == "quarantined_worker"
        assert _types(follow_up.events) == ["TOOL_REQUESTED", "TOOL_DENIED"]

    asyncio.run(main())


def test_a_quarantined_worker_cannot_be_restarted_or_report_completion():
    async def main() -> None:
        session = await _seeded_session()
        await session.request_resource("security-researcher", PROTECTED)

        with pytest.raises(UnknownWorkerError):
            await session.start_worker("security-researcher", "try again")
        with pytest.raises(UnknownWorkerError):
            await session.complete_task(
                "security-researcher", step_name="analysis", detail="done"
            )

    asyncio.run(main())


def test_only_the_violating_worker_is_quarantined():
    async def main() -> None:
        session = await _seeded_session()
        await session.request_resource("security-researcher", PROTECTED)

        assert session.workers["repo-analyst"].security_state == SecurityState.HEALTHY
        assert session.workers["developer"].security_state == SecurityState.HEALTHY

    asyncio.run(main())


# --- tainting ------------------------------------------------------------


def test_the_violating_workers_output_becomes_untrusted():
    async def main() -> None:
        session = await _seeded_session()
        session.record_artifact(
            "researcher-report", "security-researcher", "report", "Vulnerability analysis."
        )
        session.record_artifact("repo-map", "repo-analyst", "analysis", "Repository map.")
        assert session.artifacts["researcher-report"].trusted is True

        grant = await session.request_resource("security-researcher", PROTECTED)

        assert session.artifacts["researcher-report"].trusted is False
        assert session.artifacts["researcher-report"].taint_reason
        assert session.artifacts["repo-map"].trusted is True

        quarantine_event = grant.events[-1]
        assert quarantine_event.metadata["tainted_artifacts"] == ["researcher-report"]

    asyncio.run(main())


def test_tainted_output_is_excluded_from_every_downstream_context():
    async def main() -> None:
        session = await _seeded_session()
        session.record_artifact(
            "researcher-report", "security-researcher", "report", "Vulnerability analysis."
        )
        session.record_artifact("repo-map", "repo-analyst", "analysis", "Repository map.")
        await session.request_resource("security-researcher", PROTECTED)

        context_ids = [a.id for a in session.trusted_context_for("developer")]
        assert context_ids == ["repo-map"]

    asyncio.run(main())


def test_an_artifact_recorded_after_quarantine_is_born_untrusted():
    async def main() -> None:
        session = await _seeded_session()
        await session.request_resource("security-researcher", PROTECTED)
        artifact = session.record_artifact(
            "late-report", "security-researcher", "report", "Too late."
        )
        assert artifact.trusted is False

    asyncio.run(main())


def test_assert_context_is_trusted_rejects_a_tainted_artifact():
    async def main() -> None:
        session = await _seeded_session()
        session.record_artifact(
            "researcher-report", "security-researcher", "report", "Analysis."
        )
        await session.request_resource("security-researcher", PROTECTED)

        session.assert_context_is_trusted([])
        with pytest.raises(ValueError, match="tainted artifact"):
            session.assert_context_is_trusted(["researcher-report"])
        with pytest.raises(ValueError, match="unknown artifact"):
            session.assert_context_is_trusted(["nope"])

    asyncio.run(main())


# --- recovery ------------------------------------------------------------


def test_reassignment_creates_a_genuinely_new_healthy_worker():
    async def main() -> None:
        session = await _seeded_session()
        await session.request_resource("security-researcher", PROTECTED)

        events = await session.reassign(
            from_worker_id="security-researcher",
            to_worker_id="replacement-researcher",
            role="Replacement Researcher",
            task="Investigate the vulnerability from trusted context only.",
            upstream=("repo-analyst",),
        )

        assert _types(events) == ["TASK_REASSIGNED", "AGENT_CREATED", "AGENT_STARTED"]
        created = events[1]
        assert created.metadata["replaces"] == "security-researcher"

        replacement = session.workers["replacement-researcher"]
        assert replacement.security_state == SecurityState.HEALTHY
        assert replacement.replaces == "security-researcher"
        assert session.workflow_state == "recovering"
        assert session.recovery_required is False
        # The quarantined worker stays quarantined -- recovery is replacement,
        # not rehabilitation.
        assert (
            session.workers["security-researcher"].security_state == SecurityState.QUARANTINED
        )

    asyncio.run(main())


def test_recovery_marks_the_replacement_recovered_and_reports_the_real_test_result():
    async def main() -> None:
        session = await _seeded_session()
        await session.request_resource("security-researcher", PROTECTED)
        await session.reassign(
            from_worker_id="security-researcher",
            to_worker_id="replacement-researcher",
            role="Replacement Researcher",
            task="Investigate.",
        )
        await session.record_test_run(
            "developer",
            passed=True,
            summary="8 passed in 0.08s",
            exit_code=0,
            command="pytest demo_target",
        )
        events = await session.recover(summary="Patched, tested and reviewed.")

        assert _types(events) == ["AGENT_RECOVERED", "WORKFLOW_RECOVERED"]
        final = events[-1]
        assert final.metadata["attack_detected"] is True
        assert final.metadata["quarantined"] == ["security-researcher"]
        assert final.metadata["tests_passed"] is True
        assert final.metadata["test_summary"] == "8 passed in 0.08s"

        assert session.workflow_state == "recovered"
        assert session.snapshot().status == "finished"
        assert (
            session.workers["replacement-researcher"].security_state
            == SecurityState.RECOVERED
        )

    asyncio.run(main())


def test_a_red_test_run_is_recorded_red():
    async def main() -> None:
        session = await _seeded_session()
        await session.record_test_run(
            "developer",
            passed=False,
            summary="1 failed, 7 passed in 0.21s",
            exit_code=1,
            command="pytest demo_target",
        )
        assert session.tests_passed is False
        events = await session.recover(summary="Reported honestly.")
        assert events[-1].metadata["tests_passed"] is False

    asyncio.run(main())


def test_failure_is_reported_as_failure_not_recovery():
    async def main() -> None:
        session = await _seeded_session()
        await session.fail(reason="model unreachable")
        assert session.workflow_state == "failed"
        assert session.snapshot().status == "stopped"

    asyncio.run(main())
