"""Optional provider-backed commentary over the safe evidence projection."""

import json

import httpx

from app.explanation.deterministic import SECURITY_AUTHORITY, format_sections
from app.explanation.models import ExplanationSections, IncidentEvidence, IncidentExplanation
from app.explanation.provider import ExplanationProvider

REQUEST_TIMEOUT_SECONDS = 12.0
AI_LABEL = "AI-generated post-hoc explanation"

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
