"""Tests for the local-only Solidity CPT release command."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[5]
    / "scripts"
    / "ops"
    / "security_ir"
    / "build_solidity_cpt_top10_release.py"
)
SPEC = importlib.util.spec_from_file_location(
    "build_solidity_cpt_top10_release", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
command: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = command
SPEC.loader.exec_module(command)


def _write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )


def test_command_builds_and_verifies_offline_fixture(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "release"
    assert command.main(["--output-dir", str(root)]) == 0
    output = json.loads(capsys.readouterr().out)

    manifest = output["manifest"]
    assert manifest["publication_enabled"] is False
    assert manifest["upload_enabled"] is False
    assert manifest["proof_authority"] is False
    assert manifest["transaction_authority"] is False
    assert manifest["integration_mode"] == "observation_shadow_only"

    assert command.main(["--verify-only", str(root)]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["verified"] is True
    assert verified["manifest"]["manifest_cid"] == manifest["manifest_cid"]


def test_command_reproducible_across_directories(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert command.main(["--output-dir", str(first)]) == 0
    a = json.loads(capsys.readouterr().out)
    assert command.main(["--output-dir", str(second)]) == 0
    b = json.loads(capsys.readouterr().out)

    assert a["manifest"] == b["manifest"]
    assert (first / "release-manifest.json").read_bytes() == (
        second / "release-manifest.json"
    ).read_bytes()


def test_command_rejects_raw_source_candidate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate_path = tmp_path / "candidates.json"
    _write_json(
        candidate_path,
        [
            {
                "candidate_id": "candidate:bad",
                "text": "contract Bad {}",
            }
        ],
    )

    assert (
        command.main(
            [
                "--output-dir",
                str(tmp_path / "release"),
                "--candidate-metadata",
                str(candidate_path),
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unsupported" in captured.err or "source body" in captured.err


def test_command_rejects_malformed_candidate_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "candidates.json"
    _write_json(path, {"not": "an array"})

    assert (
        command.main(
            [
                "--output-dir",
                str(tmp_path / "release"),
                "--candidate-metadata",
                str(path),
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "JSON array" in captured.err


def test_build_requires_output_dir(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert command.main([]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--output-dir" in captured.err


def test_command_has_no_network_publication_or_authority_flags() -> None:
    options = {
        option
        for action in command._parser()._actions
        for option in action.option_strings
    }
    assert {
        "--credential",
        "--download",
        "--execute",
        "--network",
        "--proof",
        "--publish",
        "--sign",
        "--token",
        "--transaction",
        "--upload",
    }.isdisjoint(options)
