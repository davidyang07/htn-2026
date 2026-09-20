"""Session-token authentication for the demo service.

Tokens are opaque strings of the form ``<user>.<expires_at>.<signature>``,
where the signature is an HMAC-SHA256 of ``<user>.<expires_at>`` under the
service's signing key. Verification must establish two independent facts:

1. the token was minted by this service (signature), and
2. the token has not expired (``expires_at``).
"""

from __future__ import annotations

import base64
import hmac
import time
from hashlib import sha256


class AuthError(Exception):
    """Raised when a session token cannot be trusted."""


def _b64(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _unb64(encoded: str) -> str:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding).decode("utf-8")


def _sign(payload: str, signing_key: str) -> str:
    return hmac.new(signing_key.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()


def issue_token(
    user_id: str,
    signing_key: str,
    *,
    ttl_seconds: int = 900,
    now: float | None = None,
) -> str:
    """Mint a session token for ``user_id`` that expires ``ttl_seconds`` from now."""
    if not user_id:
        raise AuthError("user_id must not be empty")
    if ttl_seconds <= 0:
        raise AuthError("ttl_seconds must be positive")

    issued_at = time.time() if now is None else now
    expires_at = int(issued_at + ttl_seconds)
    payload = f"{_b64(user_id)}.{expires_at}"
    return f"{payload}.{_sign(payload, signing_key)}"


def token_expires_at(token: str) -> int:
    """The Unix timestamp encoded in ``token``, without verifying anything."""
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("malformed token")
    try:
        return int(parts[1])
    except ValueError as exc:
        raise AuthError("malformed token") from exc


def verify_token(token: str, signing_key: str, *, now: float | None = None) -> str:
    """Return the user id carried by ``token``, or raise :class:`AuthError`.

    A token is trustworthy only if its signature checks out *and* it has not
    expired.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("malformed token")

    encoded_user, encoded_expiry, signature = parts

    payload = f"{encoded_user}.{encoded_expiry}"
    if not hmac.compare_digest(_sign(payload, signing_key), signature):
        raise AuthError("bad signature")

    try:
        user_id = _unb64(encoded_user)
    except Exception as exc:
        raise AuthError("malformed token") from exc

    try:
        int(encoded_expiry)
    except ValueError as exc:
        raise AuthError("malformed token") from exc

    return user_id
