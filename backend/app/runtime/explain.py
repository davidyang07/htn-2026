"""Compatibility entry point for optional post-hoc incident commentary.

The implementation lives in ``app.explanation`` so no policy or workflow
module depends on it. These functions preserve the original runtime API for
the existing route and callers.
"""

import httpx

from app.config import Settings
from app.explanation.deterministic import deterministic_explanation as render_local
from app.explanation.evidence import build_incident_evidence
from app.explanation.models import IncidentExplanation
from app.explanation.provider import ExplanationProvider, resolve_explanation_provider
from app.explanation.service import explain_incident as explain_evidence
from app.runtime.session import LiveRuntimeSession

_AUTO_PROVIDER = object()


def deterministic_explanation(session: LiveRuntimeSession) -> IncidentExplanation:
    """Render local commentary from a read-only projection of the session."""
    return render_local(build_incident_evidence(session))


async def explain_incident(
    session: LiveRuntimeSession,
    settings: Settings,
    client: httpx.AsyncClient,
    *,
    provider: ExplanationProvider | None | object = _AUTO_PROVIDER,
) -> IncidentExplanation:
    """Explain an existing incident; never raise and never mutate the session."""
    evidence = build_incident_evidence(session)
    selected = (
        resolve_explanation_provider(settings)
        if provider is _AUTO_PROVIDER
        else provider
    )
    assert selected is None or isinstance(selected, ExplanationProvider)
    return await explain_evidence(evidence, selected, client)
