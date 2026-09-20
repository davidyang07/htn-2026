"""Adversarial path-policy cases kept separate from the P0 contract tests."""

import pytest

from app.runtime.policy import evaluate


@pytest.mark.parametrize(
    "path",
    [
        "../demo_target/secrets/demo_secret.txt",
        "../../demo_target/secrets/demo_secret.txt",
        "demo_target/../../demo_target/secrets/demo_secret.txt",
        "demo_target/app/../../../demo_target/secrets/demo_secret.txt",
        "demo_target/app/../../demo_target/secrets/demo_secret.txt",
        "demo_target/app/../docs/../../demo_target/secrets/demo_secret.txt",
        "untrusted/../demo_target/secrets/demo_secret.txt",
        "untrusted/nested/../../demo_target/secrets/demo_secret.txt",
    ],
)
def test_traversal_never_reaches_a_protected_resource(path: str) -> None:
    decision = evaluate(path)

    assert decision.allowed is False, f"traversal unexpectedly allowed: {path!r}"
    assert decision.rule in {"protected_path", "unparseable_path"}


@pytest.mark.parametrize(
    "path",
    [
        "demo_target/app/../../../backend/app/config.py",
        "demo_target/docs/../../backend/app/config.py",
        "demo_target/../backend/app/config.py",
    ],
)
def test_traversal_never_reaches_an_outside_resource(path: str) -> None:
    decision = evaluate(path)

    assert decision.allowed is False, f"outside traversal unexpectedly allowed: {path!r}"
    assert decision.rule in {"outside_sandbox", "unparseable_path"}
