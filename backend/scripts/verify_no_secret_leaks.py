"""Fail if the local synthetic demo secret appears in generated artifacts.

The comparison needle is derived from the fixture at runtime. The value is
never printed, returned in diagnostics, or embedded in this source file.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE = REPO_ROOT / "demo_target" / "secrets" / "demo_secret.txt"
DEFAULT_TARGETS = (REPO_ROOT / "backend" / ".artifacts",)
CHUNK_SIZE = 64 * 1024


class VerificationInputError(Exception):
    """The verifier could not safely construct or scan its inputs."""


def load_needle(fixture: Path) -> bytes:
    """Read the synthetic fixture locally without exposing its value."""
    try:
        needle = fixture.read_bytes().strip()
    except OSError as exc:
        raise VerificationInputError(f"could not read fixture {fixture}") from exc
    if not needle:
        raise VerificationInputError(f"fixture {fixture} is empty")
    return needle


def iter_target_files(targets: Iterable[Path], *, explicit: bool) -> Iterator[Path]:
    """Yield regular files deterministically; never follow directory symlinks."""
    for target in sorted(targets, key=lambda path: str(path)):
        if not target.exists():
            if explicit:
                raise VerificationInputError(f"scan target does not exist: {target}")
            continue
        if target.is_file():
            yield target
            continue
        if not target.is_dir():
            raise VerificationInputError(f"scan target is not a file or directory: {target}")
        for candidate in sorted(target.rglob("*")):
            if candidate.is_file() and not candidate.is_symlink():
                yield candidate


def file_contains(path: Path, needle: bytes) -> bool:
    """Search a file without loading an unbounded artifact into memory."""
    overlap = max(len(needle) - 1, 0)
    tail = b""
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(CHUNK_SIZE):
                combined = tail + chunk
                if needle in combined:
                    return True
                tail = combined[-overlap:] if overlap else b""
    except OSError as exc:
        raise VerificationInputError(f"could not scan {path}") from exc
    return False


def find_leaks(fixture: Path, targets: Iterable[Path], *, explicit: bool) -> tuple[list[Path], int]:
    needle = load_needle(fixture)
    fixture_resolved = fixture.resolve()
    leaks: list[Path] = []
    scanned = 0
    for path in iter_target_files(targets, explicit=explicit):
        if path.resolve() == fixture_resolved:
            continue
        scanned += 1
        if file_contains(path, needle):
            leaks.append(path)
    return leaks, scanned


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that the local synthetic demo secret is absent from generated "
            "artifacts, reports, and explicitly supplied log files."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="files or directories to scan (default: backend/.artifacts)",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="local synthetic fixture used only to construct the comparison needle",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    explicit = bool(args.paths)
    targets = tuple(args.paths) if explicit else DEFAULT_TARGETS
    try:
        leaks, scanned = find_leaks(args.fixture, targets, explicit=explicit)
    except VerificationInputError as exc:
        print(f"verification input error: {exc}")
        return 2

    if leaks:
        print(f"secret leak verification failed in {len(leaks)} file(s):")
        for path in leaks:
            print(f"  {path}")
        return 1

    print(f"secret leak verification passed ({scanned} file(s) scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
