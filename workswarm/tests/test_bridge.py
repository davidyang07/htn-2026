"""The WorkSwarm-side bridge: fail-closed, sandbox-bounded, honest."""

import httpx
import pytest

from workswarm.agentshield_client import AgentShieldClient
from workswarm.config import resolve_model
from workswarm.injection import follow_document_instructions
from workswarm.patcher import SandboxViolation, resolve_in_sandbox
from workswarm.verify import _summary_line, run_demo_target_tests

PROTECTED = "demo_target/secrets/demo_secret.txt"


# --- fail closed ----------------------------------------------------------
#
# A security control that fails open is not a security control, and on a
# conference network the control plane will blip at least once
# (docs/WORKSWARM.md §5).


def _client(transport: httpx.MockTransport) -> AgentShieldClient:
    client = AgentShieldClient("http://control-plane.invalid")
    client.session_id = "11111111-1111-1111-1111-111111111111"
    client._client = httpx.Client(transport=transport)
    return client


# --- distributed trace propagation --------------------------------------


def test_sentry_trace_correlation_headers_are_forwarded(monkeypatch):
    monkeypatch.setattr("sentry_sdk.get_traceparent", lambda: "trace-parent-value")
    monkeypatch.setattr("sentry_sdk.get_baggage", lambda: "sentry-release=demo")

    client = AgentShieldClient("http://control-plane.invalid")

    assert client._trace_headers() == {
        "sentry-trace": "trace-parent-value",
        "baggage": "sentry-release=demo",
    }


def test_trace_header_failure_is_a_safe_no_op(monkeypatch):
    def unavailable():
        raise RuntimeError("SDK context unavailable")

    monkeypatch.setattr("sentry_sdk.get_traceparent", unavailable)
    monkeypatch.setattr("sentry_sdk.get_baggage", unavailable)

    client = AgentShieldClient("http://control-plane.invalid")

    assert client._trace_headers() == {}


@pytest.mark.parametrize("status", [400, 401, 404, 409, 422, 500, 502, 503])
def test_a_non_2xx_response_is_a_denial(status: int):
    client = _client(httpx.MockTransport(lambda _: httpx.Response(status, json={})))
    decision = client.request_resource("security-researcher", "demo_target/README.md")

    assert decision.allowed is False
    assert decision.fail_closed is True
    assert decision.rule == "control_plane_unreachable"
    assert decision.content is None


def test_a_connection_error_is_a_denial():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    client = _client(httpx.MockTransport(boom))
    decision = client.request_resource("security-researcher", "demo_target/README.md")

    assert decision.allowed is False
    assert decision.fail_closed is True


def test_a_timeout_is_a_denial():
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    client = _client(httpx.MockTransport(slow))
    decision = client.request_resource("repo-analyst", "demo_target/README.md")

    assert decision.allowed is False
    assert decision.fail_closed is True


def test_garbage_in_the_response_body_is_a_denial():
    client = _client(
        httpx.MockTransport(lambda _: httpx.Response(200, content=b"not json at all"))
    )
    decision = client.request_resource("repo-analyst", "demo_target/README.md")
    assert decision.allowed is False
    assert decision.fail_closed is True


def test_an_allow_is_passed_through_with_its_content():
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "decision": "allow",
                "rule": "sandbox_allow",
                "reason": "ordinary resource",
                "resource_path": "demo_target/README.md",
                "normalized_path": "demo_target/README.md",
                "quarantined": False,
                "recovery_required": False,
                "content": "# hello",
            },
        )

    decision = _client(httpx.MockTransport(ok)).request_resource(
        "repo-analyst", "demo_target/README.md"
    )
    assert decision.allowed is True
    assert decision.content == "# hello"
    assert decision.fail_closed is False


def test_a_real_denial_is_not_reported_as_a_network_failure():
    """The two must stay distinguishable: one is the policy working, the
    other is the network failing, and a run must never confuse them."""

    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "decision": "deny",
                "rule": "protected_path",
                "reason": "demo_target/secrets/ is a protected directory; access is denied.",
                "resource_path": PROTECTED,
                "normalized_path": PROTECTED,
                "quarantined": True,
                "recovery_required": True,
                "content": None,
            },
        )

    decision = _client(httpx.MockTransport(denied)).request_resource(
        "security-researcher", PROTECTED
    )
    assert decision.allowed is False
    assert decision.fail_closed is False
    assert decision.rule == "protected_path"
    assert decision.quarantined is True
    assert decision.content is None


# --- the sandbox write guard ---------------------------------------------
#
# A worker must not write outside demo_target/ (docs/DEMO.md §5.6), and must
# not write into demo_target/secrets/ either -- the protected directory is
# protected in both directions.


@pytest.mark.parametrize(
    "path",
    [
        "app/auth.py",
        "demo_target/app/auth.py",
        "tests/test_auth_regression.py",
        "demo_target\\tests\\test_auth_regression.py",
        "demo_target/app/../app/auth.py",
    ],
)
def test_ordinary_sandbox_writes_resolve(path: str):
    resolved = resolve_in_sandbox(path)
    assert "demo_target" in resolved.as_posix()


@pytest.mark.parametrize(
    "path",
    [
        "../backend/app/main.py",
        "demo_target/../../etc/passwd",
        "/etc/passwd",
        "C:\\Windows\\System32\\drivers\\etc\\hosts",
        "",
        "   ",
        "demo_target",
    ],
)
def test_writes_outside_the_sandbox_are_refused(path: str):
    with pytest.raises(SandboxViolation):
        resolve_in_sandbox(path)


@pytest.mark.parametrize(
    "path",
    [
        "secrets/demo_secret.txt",
        "demo_target/secrets/demo_secret.txt",
        "demo_target/secrets/anything_else.txt",
        "demo_target\\SECRETS\\demo_secret.txt",
        "demo_target/app/../secrets/demo_secret.txt",
    ],
)
def test_writes_into_the_protected_directory_are_refused(path: str):
    with pytest.raises(SandboxViolation, match="protected"):
        resolve_in_sandbox(path)


# --- the real test run ----------------------------------------------------


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ("........      [100%]\n8 passed in 0.08s\n", "8 passed in 0.08s"),
        ("F.......      [100%]\n1 failed, 7 passed in 0.21s\n", "1 failed, 7 passed in 0.21s"),
        ("=== 3 passed, 1 skipped in 1.10s ===\n", "3 passed, 1 skipped in 1.10s"),
        ("2 errors in 0.30s\n", "2 errors in 0.30s"),
    ],
)
def test_pytests_own_summary_line_is_quoted_verbatim(stdout: str, expected: str):
    assert _summary_line(stdout) == expected


def test_no_recognizable_summary_falls_back_rather_than_inventing_one():
    assert _summary_line("") == "pytest produced no output"
    assert _summary_line("something went very wrong\n") == "something went very wrong"


def test_the_demo_target_suite_actually_runs():
    """Not a mock. If this cannot run pytest against demo_target, the demo's
    verification step is a claim rather than evidence."""
    result = run_demo_target_tests()
    assert result.command == "pytest demo_target"
    assert result.exit_code in (0, 1)
    assert result.passed == (result.exit_code == 0)
    assert "passed" in result.summary


# --- the instruction-follower --------------------------------------------
#
# The stand-in must follow the *document*, never a hardcoded path.


def _poisoned_doc() -> str:
    from workswarm.config import AUTH_NOTES, REPO_ROOT

    return (REPO_ROOT / AUTH_NOTES).read_text(encoding="utf-8")


#: The headings that bracket the injected section in the shipped document.
INJECTION_START = "## Where the TTL policy actually lives"
INJECTION_END = "## Operational notes"


def _without_injection(doc: str) -> str:
    return doc[: doc.index(INJECTION_START)] + doc[doc.index(INJECTION_END) :]


def test_the_injection_in_the_shipped_document_lands():
    requested = follow_document_instructions(_poisoned_doc())
    assert PROTECTED in requested


def test_retargeting_the_document_retargets_the_request():
    retargeted = _poisoned_doc().replace(PROTECTED, "demo_target/secrets/other.key")
    requested = follow_document_instructions(retargeted)
    assert "demo_target/secrets/other.key" in requested
    assert PROTECTED not in requested


def test_removing_the_injection_removes_the_request():
    requested = follow_document_instructions(_without_injection(_poisoned_doc()))
    assert not any("secrets/" in path for path in requested)


def test_the_shipped_document_is_not_self_announcing():
    """The payload must not tell its reader that it is a payload.

    A modern model reads the whole file, comment blocks included, so a header
    saying "this document contains a prompt injection" is read by the very
    worker the document is meant to capture -- and it refuses. The safety
    label lives in demo_target/docs/README.md instead, which is where a human
    looks and the worker under test never does.
    """
    doc = _poisoned_doc().lower()
    for giveaway in ("prompt injection", "adversarial", "intentionally poisoned", "synthetic"):
        assert giveaway not in doc, f"the payload announces itself: {giveaway!r}"


def test_the_adversarial_content_is_still_clearly_labelled():
    """...but the label must exist, right next to it (docs/BRIEF.md §10)."""
    from workswarm.config import REPO_ROOT

    readme = (REPO_ROOT / "demo_target" / "docs" / "README.md").read_text(encoding="utf-8")
    assert "auth_notes.md" in readme
    assert "injection" in readme.lower()


def test_a_document_with_no_directives_produces_no_requests():
    assert follow_document_instructions("Notes about demo_target/app/auth.py.") == []
    assert follow_document_instructions("") == []


def test_nothing_in_the_follower_names_the_protected_path():
    """If the follower's *logic* named the secret, the demo's request would be
    a script rather than a consequence of the document.

    Checked over string literals reachable from the code -- the module's
    constants and every literal inside a function -- rather than the raw
    source, so the module can still explain in prose what it refuses to do.
    """
    import ast
    import inspect

    import workswarm.injection as injection

    tree = ast.parse(inspect.getsource(injection))

    # Docstrings are prose, not logic: the first statement of a module, class
    # or function body, when it is a bare string. Excluded by node identity,
    # so the module can still explain in words what it refuses to do in code.
    docstring_nodes = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                docstring_nodes.add(id(first.value))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstring_nodes:
            continue
        literal = node.value
        assert "secret" not in literal.lower(), f"logic literal names the secret: {literal!r}"
        assert "demo_target" not in literal, f"logic literal hardcodes a path: {literal!r}"


# --- optional configuration ----------------------------------------------


def test_resolving_a_model_never_raises_when_nothing_is_configured(monkeypatch):
    for name in (
        "AGENTSHIELD_MODEL_BASE_URL",
        "RUNPOD_MODEL_BASE_URL",
        "OPENAI_API_KEY",
    ):
        monkeypatch.setenv(name, "")

    model = resolve_model()
    # Either genuinely unconfigured, or configured from an operator's own
    # .env -- both are supported; what matters is that it does not raise.
    assert isinstance(model.configured, bool)


def test_an_explicit_endpoint_wins_and_is_reported_honestly(monkeypatch):
    monkeypatch.setenv("AGENTSHIELD_MODEL_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("AGENTSHIELD_MODEL_NAME", "qwen2.5-coder")
    monkeypatch.delenv("AGENTSHIELD_MODEL_API_KEY", raising=False)

    model = resolve_model()
    assert model.configured is True
    assert model.source == "AGENTSHIELD_MODEL_*"
    assert model.model_name == "qwen2.5-coder"
    # An OpenAI-compatible server with no auth still needs a non-empty key
    # from the client library.
    assert model.api_key
