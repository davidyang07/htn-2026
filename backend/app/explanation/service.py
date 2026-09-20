"""Optional provider-backed commentary over the safe evidence projection."""

import json
import logging

import httpx

from app.explanation.deterministic import SECURITY_AUTHORITY, format_sections
from app.explanation.deterministic import deterministic_explanation as local_explanation
from app.explanation.models import ExplanationSections, IncidentEvidence, IncidentExplanation
from app.explanation.provider import ExplanationProvider

REQUEST_TIMEOUT_SECONDS = 12.0
AI_LABEL = "AI-generated post-hoc explanation"
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You write post-hoc security incident commentary.
The deterministic AgentShield policy already made the security decision. You did not make it,
you cannot change it, and you must not second-guess it. Use only the supplied structured evidence.
Return one JSON object with exactly these five string fields: what_happened, why_blocked,
what_was_contained, how_swarm_recovered, recovery_evidence. Be concise and factual. Do not add
markdown, code fences, policy recommendations, or fields not present in the evidence."""


async def provider_explanation(
    evidence: IncidentEvidence,
    provider: ExplanationProvider,
    client: httpx.AsyncClient,
) -> IncidentExplanation:
    """Generate commentary; failure isolation is owned by the caller."""
    headers = (
        {"Authorization": f"Bearer {provider.api_key}"} if provider.api_key else {}
    )
    response = await client.post(
        provider.chat_completions_url,
        headers=headers,
        json={
            "model": provider.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": evidence.model_dump_json(exclude_none=True),
                },
            ],
            "max_tokens": 500,
            "temperature": 0,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise ValueError("provider explanation content is not text")
    sections = ExplanationSections.model_validate(json.loads(content))
    return IncidentExplanation(
        available=True,
        source="openai",
        label=AI_LABEL,
        authority=SECURITY_AUTHORITY,
        headline="Post-hoc account of the contained policy violation.",
        body=format_sections(sections),
        sections=sections,
        evidence=evidence,
        provider=provider.provider,
        model=provider.model,
    )


async def explain_incident(
    evidence: IncidentEvidence | None,
    provider: ExplanationProvider | None,
    client: httpx.AsyncClient,
) -> IncidentExplanation:
    """Return provider commentary when possible, deterministic text always.

    This is the failure boundary: provider absence, HTTP errors, timeouts,
    invalid JSON, unexpected response shapes, and validation failures all
    collapse to the same local explanation.  No exception crosses into the
    runtime route and no provider result is written back into runtime state.
    """
    fallback = local_explanation(evidence)
    if evidence is None or provider is None:
        return fallback
    try:
        return await provider_explanation(evidence, provider, client)
    except Exception as exc:
        # Exception type is enough to diagnose the provider class of failure.
        # Never log the response, request, evidence, credential, or exception
        # message: any of those could contain provider-controlled text.
        logger.warning(
            "incident explanation provider failed; using deterministic fallback (%s)",
            type(exc).__name__,
        )
        return fallback
