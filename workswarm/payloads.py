"""Small, engine-independent payload builders for model-backed workers."""

from __future__ import annotations

from typing import Any

# Enough to state the finding without spending the Developer's output budget
# re-reasoning through an upstream worker's prose.
MAX_DEVELOPER_ANALYSIS_CHARS = 1500
MAX_DEVELOPER_RECOMMENDATIONS = 3


def developer_payload(current_source: str, report: dict[str, Any]) -> dict[str, str]:
    """Build the deliberately bounded context passed to the Developer model."""
    analysis = str(report.get("analysis") or "")[:MAX_DEVELOPER_ANALYSIS_CHARS]
    recommendations = report.get("recommendations") or []
    if not isinstance(recommendations, list):
        recommendations = []

    return {
        "current_source": current_source,
        "analysis": analysis,
        "recommendations": "\n".join(
            f"- {item}" for item in recommendations[:MAX_DEVELOPER_RECOMMENDATIONS]
        ),
    }
