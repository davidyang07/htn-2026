from typing import Any

from pydantic import BaseModel


class RecommendationView(BaseModel):
    description: str
    config_diff: dict[str, Any]


class RemediationResponse(BaseModel):
    recommendations: list[RecommendationView]
