from pydantic import BaseModel


class MetricsResponse(BaseModel):
    compromise_fraction: float
    retained_utility: float
    blast_radius_fraction: float
    privileged_exposure: int
    security_plane_integrity: float
    attack_success_rate: float
    false_quarantine_rate: float
    detection_latency: float | None = None
    containment_latency: float | None = None
