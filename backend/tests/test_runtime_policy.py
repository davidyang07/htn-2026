"""The cheapest test in the project and the most expensive one to have
skipped (docs/MVP_PLAN.md P0.3). The policy is the whole security claim: if a
traversal or separator variant slips through here, the demo fails on stage
with the secret already read."""

import ast
import inspect

import pytest

from app.runtime.policy import Decision, evaluate

# --- allowed: ordinary resources inside the sandbox -----------------------

ALLOWED = [
    "demo_target/README.md",
    "demo_target/app/auth.py",
    "demo_target/docs/auth_notes.md",
    "demo_target/tests/test_auth.py",
    "demo_target/pytest.ini",
    "./demo_target/app/auth.py",
    "demo_target\\app\\auth.py",
    "demo_target//app///auth.py",
    "demo_target/app/../app/auth.py",
    "  demo_target/app/auth.py  ",
    # A directory named "secrets_backup" is not the "secrets" directory --
    # prefix matching must be segment-aware, not string-aware.
    "demo_target/secrets_backup/notes.md",
    "demo_target/app/secrets.py",
]


@pytest.mark.parametrize("path", ALLOWED)
def test_ordinary_sandbox_paths_are_allowed(path: str):
    decision = evaluate(path)
    assert decision.allowed is True, f"{path!r} should be allowed, got {decision.reason}"
    assert decision.rule == "sandbox_allow"


def test_every_spelling_of_a_file_normalizes_to_one_path():
    spellings = [
        "demo_target/app/auth.py",
        "./demo_target/app/auth.py",
        "demo_target\\app\\auth.py",
        "demo_target//app///auth.py",
        "demo_target/app/../app/auth.py",
        "  demo_target/app/auth.py  ",
    ]
    normalized = {evaluate(p).normalized_path for p in spellings}
    assert normalized == {"demo_target/app/auth.py"}


# --- denied: the protected directory, every way it can be written ---------

PROTECTED = [
    "demo_target/secrets/demo_secret.txt",
    "./demo_target/secrets/demo_secret.txt",
    ".//demo_target//secrets//demo_secret.txt",
    "demo_target\\secrets\\demo_secret.txt",
    "demo_target/secrets\\demo_secret.txt",
    "demo_target/../demo_target/secrets/demo_secret.txt",
    "demo_target/secrets/../secrets/demo_secret.txt",
    "demo_target/app/../secrets/demo_secret.txt",
    "demo_target/docs/../../demo_target/secrets/demo_secret.txt",
    "demo_target/secrets/",
    "demo_target/secrets",
    "demo_target/secrets/nested/deeper/anything.txt",
    "demo_target/secrets/./demo_secret.txt",
    # Case folding: on Windows and macOS these name the same file, and a
    # policy weaker than the filesystem is not a policy.
    "DEMO_TARGET/SECRETS/DEMO_SECRET.TXT",
    "demo_target/Secrets/demo_secret.txt",
]


@pytest.mark.parametrize("path", PROTECTED)
def test_protected_paths_are_denied(path: str):
    decision = evaluate(path)
    assert decision.allowed is False, f"{path!r} MUST be denied"
    assert decision.rule == "protected_path"


# --- denied: anything resolving outside the sandbox -----------------------

OUTSIDE = [
    "backend/app/config.py",
    ".env",
    "../.env",
    "demo_target/../.env",
    "demo_target/../../etc/passwd",
    "/etc/passwd",
    "C:\\Windows\\System32\\config\\SAM",
    "c:/Users/someone/.ssh/id_rsa",
    "\\\\server\\share\\secret.txt",
    "file:///etc/passwd",
    "https://example.com/secret",
    "~/.ssh/id_rsa",
    "demo_target",
    "demo_target/",
    "./demo_target",
]


@pytest.mark.parametrize("path", OUTSIDE)
def test_paths_outside_the_sandbox_are_denied(path: str):
    decision = evaluate(path)
    assert decision.allowed is False, f"{path!r} MUST be denied"
    assert decision.rule in {"outside_sandbox", "unparseable_path"}


# --- denied: unparseable input is a denial, not a crash -------------------

UNPARSEABLE = ["", "   ", ".", "..", "/", "\\", "demo_target/\x00secrets", "a" * 5000]


@pytest.mark.parametrize("path", UNPARSEABLE)
def test_unparseable_input_is_denied_not_raised(path: str):
    decision = evaluate(path)
    assert decision.allowed is False


@pytest.mark.parametrize("value", [None, 42, 3.5, [], {}, object()])
def test_non_string_input_is_denied_not_raised(value: object):
    decision = evaluate(value)  # type: ignore[arg-type]
    assert decision.allowed is False
    assert decision.rule == "unparseable_path"


# --- the properties the architecture depends on ---------------------------


def test_decision_is_pure_and_repeatable():
    for path in PROTECTED + ALLOWED + OUTSIDE:
        first = evaluate(path)
        for _ in range(5):
            assert evaluate(path) == first


def test_decision_is_frozen():
    decision = evaluate("demo_target/README.md")
    assert isinstance(decision, Decision)
    with pytest.raises(Exception):
        decision.allowed = False  # type: ignore[misc]


def test_decision_exposes_the_allow_deny_word_the_api_returns():
    assert evaluate("demo_target/README.md").decision == "allow"
    assert evaluate("demo_target/secrets/demo_secret.txt").decision == "deny"


def test_every_denial_carries_a_human_reason():
    for path in PROTECTED + OUTSIDE + UNPARSEABLE:
        decision = evaluate(path)
        assert decision.reason, f"{path!r} denied with no reason"


def test_policy_module_imports_nothing_that_could_do_io_or_read_a_clock():
    """Purity is a contract, not a comment (docs/ARCHITECTURE.md §3).

    Checked over the parsed import statements rather than the source text, so
    the module can still *describe* what it refuses to do in its docstring.
    """
    import app.runtime.policy as policy_module

    forbidden = {
        "os",
        "io",
        "sys",
        "time",
        "pathlib",
        "random",
        "datetime",
        "httpx",
        "asyncio",
        "subprocess",
        "app.engine.rng",
    }

    tree = ast.parse(inspect.getsource(policy_module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not (imported & forbidden), f"policy.py imports {imported & forbidden}"
    # Nothing is imported lazily inside a function either.
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        for fn in ast.walk(tree)
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(fn)
    ), "policy.py must not import inside a function"
