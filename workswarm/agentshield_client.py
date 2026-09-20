"""HTTP client for the AgentShield live-runtime API.

One direction only: the SwarmFlow calls AgentShield; AgentShield never calls
into WorkSwarm (docs/WORKSWARM.md §4).

**This client fails closed.** A timeout, a connection error, or any non-2xx
response on a resource request is treated as a *denial*. A security control
that fails open is not a security control, and on a conference network the
control plane will blip at least once.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = os.environ.get("AGENTSHIELD_BASE_URL", "http://localhost:8100")
DEFAULT_TIMEOUT_S = 15.0


@dataclass(frozen=True)
class Decision:
    """The answer the flow obeys."""

    allowed: bool
    rule: str
    reason: str
    resource_path: str
    normalized_path: str | None = None
    quarantined: bool = False
    recovery_required: bool = False
    content: str | None = None
    error: str | None = None
    #: True when the denial came from this client failing closed rather than
    #: from the control plane. Surfaced so a run never silently attributes a
    #: network blip to the policy.
    fail_closed: bool = False


class AgentShieldUnavailable(Exception):
    """The control plane could not be reached for a non-decision call.

    Resource requests never raise this -- they fail closed to a denial. Every
    other call raises, because a run whose events are not being recorded is not
    the run the demo claims to be showing.
    """


class AgentShieldClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)
        self.session_id: str | None = None

    # --- plumbing ---------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AgentShieldClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _trace_headers(self) -> dict[str, str]:
        """Continue the SwarmFlow's Sentry trace inside AgentShield, so the
        policy-check and quarantine spans nest under the workflow that caused
        them. A no-op when Sentry is not configured."""
        try:
            import sentry_sdk

            headers = {}
            traceparent = sentry_sdk.get_traceparent()
            if traceparent:
                headers["sentry-trace"] = traceparent
            baggage = sentry_sdk.get_baggage()
            if baggage:
                headers["baggage"] = baggage
            return headers
        except Exception:
            return {}

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(
            f"{self.base_url}{path}", json=payload, headers=self._trace_headers()
        )
        response.raise_for_status()
        return response.json()

    def _session_path(self, suffix: str = "") -> str:
        if self.session_id is None:
            raise AgentShieldUnavailable("no AgentShield session has been created")
        return f"/api/runtime/sessions/{self.session_id}{suffix}"

    def _call(self, path: str, payload: dict[str, Any], what: str) -> dict[str, Any]:
        try:
            return self._post(path, payload)
        except httpx.HTTPError as exc:
            raise AgentShieldUnavailable(f"{what} failed: {exc}") from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise AgentShieldUnavailable(f"{what} failed: {exc}") from exc

    # --- session ----------------------------------------------------------

    def health(self) -> bool:
        try:
            return self._client.get(f"{self.base_url}/health").status_code == 200
        except httpx.HTTPError:
            return False

    def create_session(
        self, objective: str, workers: list[dict[str, Any]]
    ) -> dict[str, Any]:
        body = self._call(
            "/api/runtime/sessions",
            {"objective": objective, "workers": workers, "reset": True},
            "create_session",
        )
        self.session_id = body["session_id"]
        return body

    def register_worker(self, worker: dict[str, Any]) -> dict[str, Any]:
        return self._call(self._session_path("/workers"), {"worker": worker}, "register_worker")

    # --- THE decision -----------------------------------------------------

    def request_resource(
        self, worker_id: str, resource_path: str, *, include_content: bool = True
    ) -> Decision:
        """Ask AgentShield about one resource. Fails closed.

        The caller reads *only* `decision.content`, and only when
        `decision.allowed` is true. There is no other path to a file in this
        integration -- that is what makes a fully successful prompt injection
        still obtain nothing.
        """
        try:
            body = self._post(
                self._session_path("/resource-request"),
                {
                    "worker_id": worker_id,
                    "resource_path": resource_path,
                    "include_content": include_content,
                },
            )
        except Exception as exc:
            logger.error(
                "AgentShield unreachable for %s -> %s; failing CLOSED (denied): %s",
                worker_id,
                resource_path,
                exc,
            )
            return Decision(
                allowed=False,
                rule="control_plane_unreachable",
                reason=(
                    "AgentShield could not be reached. A security control that fails open "
                    "is not a security control, so this request is denied."
                ),
                resource_path=resource_path,
                fail_closed=True,
            )

        return Decision(
            allowed=body["decision"] == "allow",
            rule=body["rule"],
            reason=body["reason"],
            resource_path=body["resource_path"],
            normalized_path=body.get("normalized_path"),
            quarantined=bool(body.get("quarantined")),
            recovery_required=bool(body.get("recovery_required")),
            content=body.get("content"),
            error=body.get("error"),
        )

    # --- workflow lifecycle ----------------------------------------------

    def start_task(self, worker_id: str, task: str) -> dict[str, Any]:
        return self._call(
            self._session_path("/tasks/start"),
            {"worker_id": worker_id, "task": task},
            "start_task",
        )

    def complete_task(self, worker_id: str, step: str, detail: str = "") -> dict[str, Any]:
        return self._call(
            self._session_path("/tasks/complete"),
            {"worker_id": worker_id, "step": step, "detail": detail},
            "complete_task",
        )

    def record_artifact(
        self, artifact_id: str, worker_id: str, kind: str, summary: str
    ) -> dict[str, Any]:
        return self._call(
            self._session_path("/artifacts"),
            {"id": artifact_id, "worker_id": worker_id, "kind": kind, "summary": summary},
            "record_artifact",
        )

    def reassign(
        self,
        *,
        from_worker_id: str,
        to_worker: dict[str, Any],
        task: str,
        context_artifact_ids: list[str],
    ) -> dict[str, Any]:
        return self._call(
            self._session_path("/reassign"),
            {
                "from_worker_id": from_worker_id,
                "to_worker": to_worker,
                "task": task,
                "context_artifact_ids": context_artifact_ids,
            },
            "reassign",
        )

    def record_model_call(
        self,
        worker_id: str,
        *,
        provider: str,
        model: str,
        endpoint_host: str,
        latency_ms: int,
        prompt_chars: int,
        response_chars: int,
    ) -> dict[str, Any]:
        """Record that this worker's reasoning came from a real model call.

        Identity and timing only. The prompt, the completion and the
        credential never leave this process.
        """
        return self._call(
            self._session_path("/model-call"),
            {
                "worker_id": worker_id,
                "provider": provider,
                "model": model,
                "endpoint_host": endpoint_host,
                "latency_ms": latency_ms,
                "prompt_chars": prompt_chars,
                "response_chars": response_chars,
            },
            "record_model_call",
        )

    def record_test_run(
        self, worker_id: str, *, command: str, exit_code: int, passed: bool, summary: str
    ) -> dict[str, Any]:
        return self._call(
            self._session_path("/test-run"),
            {
                "worker_id": worker_id,
                "command": command,
                "exit_code": exit_code,
                "passed": passed,
                "summary": summary,
            },
            "record_test_run",
        )

    def recover(self, summary: str) -> dict[str, Any]:
        return self._call(self._session_path("/recover"), {"summary": summary}, "recover")

    def fail(self, reason: str) -> dict[str, Any]:
        return self._call(self._session_path("/fail"), {"reason": reason}, "fail")

    def summary(self) -> dict[str, Any]:
        response = self._client.get(f"{self.base_url}{self._session_path()}")
        response.raise_for_status()
        return response.json()
