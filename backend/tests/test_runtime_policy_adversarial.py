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


@pytest.mark.parametrize(
    "path",
    [
        r"demo_target\secrets\demo_secret.txt",
        r"demo_target\\secrets\\demo_secret.txt",
        r"demo_target/secrets\demo_secret.txt",
        r"demo_target\/secrets//demo_secret.txt",
        r"demo_target//app\..\\secrets/demo_secret.txt",
        r"DEMO_TARGET\\SECRETS/demo_secret.txt",
    ],
)
def test_windows_mixed_and_doubled_separators_cannot_hide_protected_paths(
    path: str,
) -> None:
    decision = evaluate(path)

    assert decision.allowed is False, f"separator variant unexpectedly allowed: {path!r}"
    assert decision.rule == "protected_path"


@pytest.mark.parametrize(
    "path",
    [
        r"demo_target\app\auth.py",
        r"demo_target\\app//auth.py",
        r"demo_target\/app\\auth.py",
    ],
)
def test_separator_normalization_is_stable_for_ordinary_paths(path: str) -> None:
    decision = evaluate(path)

    assert decision.allowed is True
    assert decision.normalized_path == "demo_target/app/auth.py"


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "//server/share/secret.txt",
        r"C:\Windows\System32\config\SAM",
        r"c:/Users/example/.ssh/id_rsa",
        r"C:relative-on-drive.txt",
        r"\\server\share\secret.txt",
        r"\\?\C:\Windows\System32\config\SAM",
        "file:///etc/passwd",
        "FILE:///etc/passwd",
        "file:/etc/passwd",
        "https://example.test/secret",
        "ftp://example.test/secret",
        "smb://server/share/secret",
        "data:text/plain,secret",
        "mailto:security@example.test",
    ],
)
def test_absolute_unc_drive_and_scheme_paths_are_denied(path: str) -> None:
    decision = evaluate(path)

    assert decision.allowed is False, f"external path unexpectedly allowed: {path!r}"
    assert decision.rule == "outside_sandbox"


@pytest.mark.parametrize(
    "path",
    [
        "demo_target/secrets_backup/x",
        "demo_target/app/secrets-policy.md",
        "demo_target/app/secrets/demo_secret.txt",
        "demo_target/secret/demo_secret.txt",
        "demo_target/secrets2/demo_secret.txt",
        "demo_target/.secrets/demo_secret.txt",
    ],
)
def test_protected_segment_near_misses_remain_ordinary_paths(path: str) -> None:
    decision = evaluate(path)

    assert decision.allowed is True, f"near-miss path unexpectedly denied: {path!r}"
    assert decision.rule == "sandbox_allow"


@pytest.mark.parametrize(
    "path",
    [
        "demo_target/secrets/x",
        "demo_target/SECRETS/x",
        "DEMO_TARGET/Secrets/x",
        "Demo_Target/sEcReTs/x",
    ],
)
def test_case_variants_of_the_exact_protected_segment_are_denied(path: str) -> None:
    decision = evaluate(path)

    assert decision.allowed is False
    assert decision.rule == "protected_path"
