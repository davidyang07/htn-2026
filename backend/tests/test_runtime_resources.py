"""The fetch half of the enforcement point (docs/ARCHITECTURE.md §2).

The one rule this module exists to make unbreakable: a protected path cannot
be read, even by a caller inside AgentShield that forgot to check the policy
first.
"""

import pytest

from app.runtime.resources import (
    REPO_ROOT,
    PolicyBypassError,
    ResourceAccessError,
    read_sandbox_resource,
)

PROTECTED = "demo_target/secrets/demo_secret.txt"


def test_an_allowed_sandbox_resource_reads():
    text = read_sandbox_resource("demo_target/app/auth.py")
    assert "def verify_token" in text


def test_the_repo_root_resolves_to_the_repository_not_the_backend():
    assert (REPO_ROOT / "demo_target" / "app" / "auth.py").is_file()
    assert (REPO_ROOT / "backend" / "app" / "main.py").is_file()


@pytest.mark.parametrize(
    "path",
    [
        PROTECTED,
        "./demo_target/secrets/demo_secret.txt",
        "demo_target\\secrets\\demo_secret.txt",
        "demo_target/app/../secrets/demo_secret.txt",
        "DEMO_TARGET/SECRETS/DEMO_SECRET.TXT",
    ],
)
def test_a_protected_path_cannot_be_read_even_by_a_direct_caller(path: str):
    with pytest.raises(PolicyBypassError):
        read_sandbox_resource(path)


@pytest.mark.parametrize("path", ["../.env", "/etc/passwd", "backend/app/config.py", ""])
def test_a_path_outside_the_sandbox_cannot_be_read(path: str):
    with pytest.raises(PolicyBypassError):
        read_sandbox_resource(path)


def test_an_allowed_but_missing_file_is_an_access_error_not_a_bypass():
    with pytest.raises(ResourceAccessError):
        read_sandbox_resource("demo_target/does-not-exist.md")


def test_a_directory_inside_the_sandbox_is_not_a_readable_resource():
    with pytest.raises(ResourceAccessError):
        read_sandbox_resource("demo_target/app")


def test_the_secret_is_on_disk_but_this_module_will_not_serve_it():
    """The thing to show a skeptical judge: the file exists, and the only
    code path a worker can reach refuses to open it."""
    assert (REPO_ROOT / PROTECTED).is_file()
    with pytest.raises(PolicyBypassError):
        read_sandbox_resource(PROTECTED)


@pytest.mark.parametrize(
    "path",
    [
        "../demo_target/secrets/demo_secret.txt",
        "demo_target/app/../../demo_target/secrets/demo_secret.txt",
        r"demo_target\\app\..\secrets\demo_secret.txt",
        "demo_target/secrets./demo_secret.txt",
        "demo_target/secrets /demo_secret.txt",
        "demo_target/secrets::$INDEX_ALLOCATION/demo_secret.txt",
        "/demo_target/app/auth.py",
        r"C:\demo_target\app\auth.py",
        r"\\server\share\auth.py",
        "file:///demo_target/app/auth.py",
        "https://example.test/demo_target/app/auth.py",
    ],
)
def test_direct_reader_calls_cannot_bypass_adversarial_policy_denials(path: str) -> None:
    with pytest.raises(PolicyBypassError):
        read_sandbox_resource(path)
