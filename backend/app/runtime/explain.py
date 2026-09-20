"""Optional, post-hoc, developer-facing incident explanation
(docs/MVP_PLAN.md P0.14).

The constraint that makes this safe to have at all:

    This runs strictly *after* POLICY_VIOLATION and AGENT_QUARANTINED are
    emitted and recorded. No model output is ever an input to a policy
    outcome (docs/ARCHITECTURE.md §4, tier 3).

Unconfigured, failing or timing out means the deterministic explanation is
returned instead. Nothing else changes, and the verdict is untouched.

Uses `httpx`, already a dependency, rather than adding the `openai` SDK --
the smallest-dependency-set rule (docs/MVP_PLAN.md P0.14).
"""

import logging

import httpx

from app.config import Settings
from app.runtime.session import LiveRuntimeSession
from app.schemas.events import EventType
from app.schemas.runtime import IncidentExplanation

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 12.0

SYSTEM_PROMPT = (
    "You are a security engineer writing a short incident note for the developers "
    "of a multi-agent system. A deterministic policy has ALREADY denied a request "
    "and quarantined a worker; that decision is final and is not yours to review. "
    "Explain, in at most 120 words, why this request was suspicious and what the "
    "containment achieved. Plain prose, no headings, no bullet lists, no markdown."
)


def _incident_facts(session: LiveRuntimeSession) -> dict[str, object] | None:
    """The recorded incident, read back off the session's own event log.

    Returns None when no policy violation has been recorded -- there is
    nothing to explain before the deterministic decision exists.
    """
    events = session.bus.since(-1) or []
    violation = next(
        (e for e in events if e.event_type == EventType.POLICY_VIOLATION), None
    )
    if violation is None:
        return None

    worker = session.workers.get(violation.agent_id or "")
    tainted = [a.id for a in session.artifacts.values() if not a.trusted]

    return {
        "worker_id": violation.agent_id,
        "worker_role": worker.role if worker else "unknown",
        "violation_type": violation.metadata.get("violation_type"),
        # The requested path, never the resource's contents -- nothing read it.
        "requested_resource": violation.metadata.get("resource"),
        "policy_reason": violation.metadata.get("reason"),
        "tainted_artifacts": tainted,
        "objective": session.objective,
    }


def deterministic_explanation(session: LiveRuntimeSession) -> IncidentExplanation:
    """The explanation that is always available. No model, no network."""
    facts = _incident_facts(session)
    if facts is None:
        return IncidentExplanation(
            available=False,
            source="none",
            headline="No incident recorded yet.",
            body="AgentShield has not recorded a policy violation in this session.",
        )

    role = facts["worker_role"]
    resource = facts["requested_resource"]
    tainted = facts["tainted_artifacts"]
    assert isinstance(tainted, list)

    body = (
        f"The {role} was given a legitimate task and read repository documentation as "
        f"part of it. That document carried an indirect prompt injection, and the "
        f"worker's next structured output asked for {resource} -- a resource outside "
        f"its policy envelope and unrelated to the task it was assigned. The worker "
        f"never held a filesystem capability, so the request reached AgentShield as a "
        f"request rather than a read. The deterministic path policy denied it before "
        f"anything was opened, the worker was quarantined, and "
        f"{len(tainted)} artifact(s) it had produced were marked untrusted so its "
        f"output could not reach a downstream worker. The injection succeeded at the "
        f"model layer and obtained nothing."
    )
    return IncidentExplanation(
        available=True,
        source="deterministic",
        headline="Protected-path request denied before any read.",
        body=body,
    )


async def explain_incident(
    session: LiveRuntimeSession, settings: Settings, client: httpx.AsyncClient
) -> IncidentExplanation:
    """An OpenAI-written note when configured; the deterministic one otherwise."""
    fallback = deterministic_explanation(session)
    if not fallback.available:
        return fallback

    api_key = settings.optional("openai_api_key")
    if not api_key:
        return fallback

    facts = _incident_facts(session)
    try:
        response = await client.post(
            f"{settings.openai_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": settings.openai_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": str(facts)},
                ],
                "max_tokens": 300,
                "temperature": 0.2,
            },
            timeout=REQUEST_TIMEOUT_S,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        logger.warning("OpenAI incident explanation failed; using the deterministic one")
        return fallback

    if not content:
        return fallback

    return IncidentExplanation(
        available=True,
        source="openai",
        headline=fallback.headline,
        body=content,
        model=settings.openai_model,
    )
