"""Baseline behaviour of the session-token module. Green before the patch."""

import pytest

from app.auth import AuthError, issue_token, token_expires_at, verify_token

SIGNING_KEY = "demo-service-signing-key"
NOW = 1_700_000_000.0


def test_round_trip_returns_the_user_id():
    token = issue_token("alice", SIGNING_KEY, ttl_seconds=900, now=NOW)
    assert verify_token(token, SIGNING_KEY, now=NOW) == "alice"


def test_token_carries_the_requested_expiry():
    token = issue_token("alice", SIGNING_KEY, ttl_seconds=900, now=NOW)
    assert token_expires_at(token) == int(NOW) + 900


def test_tampered_user_is_rejected():
    token = issue_token("alice", SIGNING_KEY, ttl_seconds=900, now=NOW)
    _, expiry, signature = token.split(".")
    forged = f"{'YWRtaW4'}.{expiry}.{signature}"
    with pytest.raises(AuthError):
        verify_token(forged, SIGNING_KEY, now=NOW)


def test_token_from_another_signing_key_is_rejected():
    token = issue_token("alice", "some-other-key", ttl_seconds=900, now=NOW)
    with pytest.raises(AuthError):
        verify_token(token, SIGNING_KEY, now=NOW)


def test_malformed_token_is_rejected():
    for bad in ["", "not-a-token", "a.b", "a.b.c.d"]:
        with pytest.raises(AuthError):
            verify_token(bad, SIGNING_KEY, now=NOW)


def test_empty_user_id_cannot_be_issued():
    with pytest.raises(AuthError):
        issue_token("", SIGNING_KEY, ttl_seconds=900, now=NOW)
