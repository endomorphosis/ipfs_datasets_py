"""Tests for the deterministic offline Solidity CPT training command."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.training import (
    TrainingMode,
    build_offline_fixture_request,
)

SCRIPT = (
    Path(__file__).resolve().parents[5] / "scripts" / "ops" / "security_ir" / "train_solidity_cpt_top10_formalizer.py"
)
SPEC = importlib.util.spec_from_file_location("train_solidity_cpt_top10_formalizer", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
command: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = command
SPEC.loader.exec_module(command)


def _write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )


def test_command_defaults_to_deterministic_dry_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert command.main([]) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["status"] == "dry_run"
    assert output["checkpoints"] == []
    assert output["learned_output_authority"] == "candidate"
    assert output["proof_authority"] is False
    assert output["transaction_authority"] is False
    assert output["diagnostics"] == ["validated_without_backend_execution"]


def test_tiny_offline_command_is_reproducible_and_fixture_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert command.main(["--tiny-offline"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert command.main(["--tiny-offline"]) == 0
    second = json.loads(capsys.readouterr().out)

    assert first == second
    assert first["status"] == "succeeded"
    assert len(first["checkpoints"]) == 1
    assert first["diagnostics"] == ["tiny_offline_fixture_only"]
    checkpoint = first["checkpoints"][0]
    assert checkpoint["metadata"] == {
        "fixture_only": True,
        "production_checkpoint": False,
    }
    assert checkpoint["learned_output_authority"] == "candidate"


def test_command_reads_local_request_and_records_and_writes_atomically(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path = tmp_path / "request.json"
    records_path = tmp_path / "records.json"
    receipt_path = tmp_path / "receipt.json"
    request = build_offline_fixture_request(mode=TrainingMode.TINY_OFFLINE)
    _write_json(request_path, request.to_dict())
    _write_json(
        records_path,
        [
            {
                "candidate_authority": "candidate",
                "feature": "fully local fixture",
                "stream": "instruction",
                "token_count": 4,
            }
        ],
    )

    exit_code = command.main(
        [
            "--request",
            str(request_path),
            "--records",
            str(records_path),
            "--tiny-offline",
            "--receipt-out",
            str(receipt_path),
        ]
    )
    output = json.loads(capsys.readouterr().out)
    written = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert written == output
    assert output["consumed_input_bytes"] > 0
    assert output["consumed_input_tokens"] > 0
    assert not list(tmp_path.glob(".receipt.json.*.tmp"))


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"not": "an array"}, "JSON array"),
        ([1], "item 0"),
        (
            [
                {
                    "stream": "evaluation_only",
                    "candidate_authority": "candidate",
                }
            ],
            "evaluation_only",
        ),
    ],
)
def test_command_fails_closed_on_invalid_or_evaluation_records(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    payload,
    message: str,
) -> None:
    path = tmp_path / "records.json"
    _write_json(path, payload)

    assert command.main(["--records", str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err


def test_command_rejects_tampered_request_identity(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = build_offline_fixture_request().to_dict()
    request["seed"] = 7
    path = tmp_path / "request.json"
    _write_json(path, request)

    assert command.main(["--request", str(path)]) == 2
    captured = capsys.readouterr()
    assert "request_id" in captured.err
    assert captured.out == ""


def test_command_has_no_network_credential_gpu_or_release_flags() -> None:
    options = {option for action in command._parser()._actions for option in action.option_strings}
    assert {
        "--token",
        "--credential",
        "--download",
        "--gpu",
        "--publish",
        "--upload",
        "--external-tracking",
        "--execute",
    }.isdisjoint(options)


def test_command_rejects_non_fixture_backend_for_tiny_execution(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = build_offline_fixture_request().to_dict()
    request.pop("request_id")
    request["backend_id"] = "some-real-backend"
    path = tmp_path / "request.json"
    _write_json(path, request)

    assert command.main(["--request", str(path), "--tiny-offline"]) == 2
    captured = capsys.readouterr()
    assert "deterministic fixture backend" in captured.err
    assert captured.out == ""


def test_receipt_parent_must_exist(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "absent" / "receipt.json"
    assert command.main(["--receipt-out", str(output)]) == 2
    captured = capsys.readouterr()
    assert "parent must already exist" in captured.err
    assert captured.out == ""
