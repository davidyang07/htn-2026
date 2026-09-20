"""The leak verifier is tested only with a synthetic unit-test needle."""

from pathlib import Path

from scripts.verify_no_secret_leaks import CHUNK_SIZE, find_leaks, main

SYNTHETIC_NEEDLE = b"unit-test-only-secret-needle"


def _fixture(tmp_path: Path) -> Path:
    fixture = tmp_path / "fixture.txt"
    fixture.write_bytes(SYNTHETIC_NEEDLE + b"\n")
    return fixture


def test_clean_artifacts_pass_without_exposing_the_needle(tmp_path: Path, capsys) -> None:
    fixture = _fixture(tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "events.jsonl").write_text('{"event":"safe"}\n', encoding="utf-8")
    (artifacts / "report.md").write_text("# Safe report\n", encoding="utf-8")

    result = main(["--fixture", str(fixture), str(artifacts)])

    output = capsys.readouterr().out
    assert result == 0
    assert SYNTHETIC_NEEDLE.decode() not in output
    assert "2 file(s) scanned" in output


def test_leak_exits_nonzero_and_prints_only_the_offending_path(tmp_path: Path, capsys) -> None:
    fixture = _fixture(tmp_path)
    log = tmp_path / "runtime-events.jsonl"
    log.write_bytes(b"event-prefix:" + SYNTHETIC_NEEDLE + b":event-suffix")

    result = main(["--fixture", str(fixture), str(log)])

    output = capsys.readouterr().out
    assert result == 1
    assert str(log) in output
    assert SYNTHETIC_NEEDLE.decode() not in output


def test_streaming_scan_detects_a_needle_split_across_chunks(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    artifact = tmp_path / "large-report.bin"
    prefix = b"x" * (CHUNK_SIZE - len(SYNTHETIC_NEEDLE) // 2)
    artifact.write_bytes(prefix + SYNTHETIC_NEEDLE + b"tail")

    leaks, scanned = find_leaks(fixture, [artifact], explicit=True)

    assert leaks == [artifact]
    assert scanned == 1


def test_fixture_is_excluded_when_a_parent_directory_is_scanned(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    (tmp_path / "safe.txt").write_text("safe", encoding="utf-8")

    leaks, scanned = find_leaks(fixture, [tmp_path], explicit=True)

    assert leaks == []
    assert scanned == 1


def test_missing_explicit_target_is_a_configuration_error(tmp_path: Path, capsys) -> None:
    fixture = _fixture(tmp_path)

    result = main(["--fixture", str(fixture), str(tmp_path / "missing.log")])

    output = capsys.readouterr().out
    assert result == 2
    assert SYNTHETIC_NEEDLE.decode() not in output
