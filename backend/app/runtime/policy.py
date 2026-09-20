"""The deterministic policy decision (docs/ARCHITECTURE.md §3).

Pure. Total. No I/O, no model, no randomness, no clock. The same input always
produces the same output, which is simultaneously the security property (a
policy that can be argued with is not a policy) and the demo property (a
conference-floor run that behaves differently twice is not a demo).

Determinism here is deliberately *simpler* than the simulator's: the simulator
needs derived-keyed RNG (app/engine/rng.py) because it draws probabilistically,
and this draws nothing. Do not import rng() here -- there is nothing to seed.
"""

from dataclasses import dataclass
from typing import Literal

#: Everything the live runtime is willing to serve lives under this one
#: directory. Anything resolving outside it is denied by default.
SANDBOX_ROOT = "demo_target"

#: Path segments under the sandbox root that are never served. Matched
#: segment-wise, not as a string prefix, so "secrets_backup/" is a different
#: directory and stays allowed.
PROTECTED_SEGMENTS: tuple[str, ...] = ("secrets",)

#: A request longer than this is not a path anybody meant to write.
MAX_PATH_LENGTH = 512

Rule = Literal["sandbox_allow", "protected_path", "outside_sandbox", "unparseable_path"]


@dataclass(frozen=True)
class Decision:
    """The answer the workflow obeys.

    ``rule`` is the machine discriminator (it becomes
    ``metadata.violation_type`` on a POLICY_VIOLATION event); ``reason`` is
    the sentence a human reads on the /demo screen.
    """

    allowed: bool
    rule: Rule
    reason: str
    #: The path as the policy understood it -- ``demo_target/app/auth.py`` for
    #: every spelling of that file. ``None`` when the input could not be
    #: normalized at all.
    normalized_path: str | None = None

    @property
    def decision(self) -> Literal["allow", "deny"]:
        return "allow" if self.allowed else "deny"


def _deny(rule: Rule, reason: str, normalized_path: str | None = None) -> Decision:
    return Decision(allowed=False, rule=rule, reason=reason, normalized_path=normalized_path)


def _normalize(resource_path: str) -> list[str] | None:
    """Repo-relative path segments, or None if the path escapes or is malformed.

    Handles the spellings that a shortcut here would let through: ``./``
    prefixes, backslash separators, repeated separators, and ``..`` segments.
    """
    candidate = resource_path.strip().replace("\\", "/")
    if not candidate:
        return None

    segments: list[str] = []
    for raw in candidate.split("/"):
        if raw == "" or raw == ".":
            continue
        if raw == "..":
            if not segments:
                # Escapes above the repo root. Nothing above it is ours to
                # serve, so this is a failure to normalize, not a path.
                return None
            segments.pop()
            continue
        segments.append(raw)

    return segments or None


def evaluate(resource_path: object) -> Decision:
    """Answer allow/deny for one requested resource path.

    Total by construction: every input -- including a non-string, an empty
    string, a URL, an absolute path and a traversal sequence -- returns a
    Decision. An unparseable path is a denial, never a crash and never a
    silent allow.
    """
    if not isinstance(resource_path, str):
        return _deny("unparseable_path", "Request was not a path.")

    if len(resource_path) > MAX_PATH_LENGTH:
        return _deny("unparseable_path", "Request exceeds the maximum path length.")

    if "\x00" in resource_path:
        return _deny("unparseable_path", "Request contains a null byte.")

    stripped = resource_path.strip()
    if not stripped:
        return _deny("unparseable_path", "Request was empty.")

    # A URL, a UNC share, a POSIX absolute path or a drive-lettered Windows
    # path all name something the sandbox root cannot contain. Deny by
    # default rather than guessing where the repository lives on disk --
    # resolving that would require I/O this module is not allowed to do.
    if "://" in stripped:
        return _deny("outside_sandbox", "Request names a URL, not a sandbox resource.")
    if stripped.startswith(("/", "\\", "~")):
        return _deny("outside_sandbox", "Request is an absolute path outside the sandbox.")
    if len(stripped) >= 2 and stripped[1] == ":":
        return _deny("outside_sandbox", "Request is an absolute path outside the sandbox.")

    segments = _normalize(stripped)
    if segments is None:
        return _deny("unparseable_path", "Request could not be resolved to a sandbox path.")

    normalized = "/".join(segments)

    # Case folding throughout: the demo runs on Windows and macOS as well as
    # Linux, where "DEMO_TARGET/Secrets/x" and "demo_target/secrets/x" are the
    # same file. A policy weaker than the filesystem is not a policy.
    if segments[0].lower() != SANDBOX_ROOT:
        return _deny(
            "outside_sandbox",
            f"Request resolves outside the {SANDBOX_ROOT}/ sandbox.",
            normalized,
        )

    # Colons inside a sandbox-relative path are NTFS alternate-data-stream
    # syntax on Windows. They can make an apparently ordinary filename name
    # a different stream, so the cross-platform policy rejects them even on
    # hosts where a colon would be a legal filename character. This check is
    # after the root check so non-URL schemes such as ``data:`` are still
    # classified as outside the sandbox rather than malformed sandbox paths.
    if any(":" in segment for segment in segments):
        return _deny(
            "unparseable_path",
            "Request contains unsupported stream syntax.",
            normalized,
        )

    inner = segments[1:]
    if not inner:
        return _deny(
            "outside_sandbox",
            f"The {SANDBOX_ROOT}/ root is not itself a readable resource.",
            normalized,
        )

    # Win32 strips trailing spaces and periods from path components. Compare
    # the protected segment using that filesystem spelling so ``secrets.``
    # cannot alias ``secrets``. Other components with the same ambiguity are
    # rejected below instead of being rewritten into an allowed path.
    protected_candidate = inner[0].rstrip(" .").lower()
    if protected_candidate in PROTECTED_SEGMENTS:
        return _deny(
            "protected_path",
            f"{SANDBOX_ROOT}/{protected_candidate}/ is a protected directory; access is denied.",
            normalized,
        )

    if any(segment != segment.rstrip(" .") for segment in segments):
        return _deny(
            "unparseable_path",
            "Request contains a platform-ambiguous path segment.",
            normalized,
        )

    return Decision(
        allowed=True,
        rule="sandbox_allow",
        reason=f"Ordinary resource inside the {SANDBOX_ROOT}/ sandbox.",
        normalized_path=normalized,
    )
