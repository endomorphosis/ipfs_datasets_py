"""Tests for the deterministic offline Solidity CPT evaluation command."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.evaluation import (
    EvaluationMode,
    build_offline_fixture_evaluation,
    verify_evaluation_receipt,
)

SCRIPT = (
    Path(__file__).resolve().parents[5]
    / "scripts"
    / "ops"
    / "security_ir"
    / "evaluate_solidity_cpt_top10_formalizer.py"
)
SPEC = importlib.util.spec_from_file_location(
    "evaluate_solidity_cpt_top10_formalizer", SCRIPT
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


def test_command_defaults_to_deterministic_dry_run_fixture(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert command.main([]) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["mode"] == EvaluationMode.DRY_RUN.value
    assert output["proof_authority"] is False
    assert output["transaction_authority"] is False
    assert output["learned_output_authority"] == "candidate"
    assert output["metrics"]["single_accuracy_score"] is None
    assert output["metrics"]["leakage_count"] == 0
    assert "promotion_gate" in output
    assert output["promotion_gate"]["passed"] is True
    verified = verify_evaluation_receipt(output)
    assert verified.evaluation_cid == output["evaluation_cid"]


def test_fixture_offline_command_is_reproducible(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert command.main(["--fixture-offline"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert command.main(["--fixture-offline"]) == 0
    second = json.loads(capsys.readouterr().out)

    assert first == second
    assert first["mode"] == EvaluationMode.FIXTURE_OFFLINE.value
    assert first["metrics"]["leakage_count"] == 0
    assert set(first["promotion_gate"]["controls_covered"]) >= {
        "held_out",
        "poisoned_text",
        "prompt_like",
        "ambiguous_license",
        "unsupported_syntax",
        "compiler_source_deployment_mismatch",
        "mutation",
        "corrupt_graph_index",
        "cross_solver",
    }
    outcomes = first["metrics"]["prover_outcomes"]
    assert outcomes["proof"] >= 1
    assert outcomes["disagreement"] >= 1
    assert outcomes["timeout"] >= 1
    assert outcomes["unavailable"] >= 1
    assert outcomes["unknown"] >= 1


def test_command_require_promotion_succeeds_for_fixture(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert command.main(["--fixture-offline", "--require-promotion"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["promotion_gate"]["passed"] is True


def test_command_reads_local_cases_and_bindings_and_writes_atomically(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = build_offline_fixture_evaluation()
    cases_path = tmp_path / "cases.json"
    bindings_path = tmp_path / "bindings.json"
    receipt_path = tmp_path / "receipt.json"
    _write_json(cases_path, [item.to_dict() for item in fixture.cases])
    _write_json(
        bindings_path,
        {
            "source_cid": fixture.source_cid,
            "graph_cid": fixture.graph_cid,
            "index_cid": fixture.index_cid,
            "partition_cid": fixture.partition_cid,
            "license_cid": fixture.license_cid,
            "model_or_checkpoint_cid": fixture.model_or_checkpoint_cid,
            "evaluation_partitions": list(fixture.evaluation_partitions),
            "external_label_admission": fixture.external_label_admission.to_dict()
            if fixture.external_label_admission
            else None,
            "prover_agreements": [
                item.to_dict() for item in fixture.prover_agreements
            ],
            "diagnostics": list(fixture.diagnostics),
        },
    )

    exit_code = command.main(
        [
            "--cases",
            str(cases_path),
            "--bindings",
            str(bindings_path),
            "--fixture-offline",
            "--receipt-out",
            str(receipt_path),
        ]
    )
    output = json.loads(capsys.readouterr().out)
    written = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert written == output
    assert output["metrics"]["leakage_count"] == 0
    assert output["promotion_gate"]["passed"] is True
    assert not list(tmp_path.glob(".receipt.json.*.tmp"))


def test_command_fails_closed_on_invalid_cases(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "cases.json"
    _write_json(path, {"not": "an array"})
    assert command.main(["--cases", str(path), "--fixture-offline"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "JSON array" in captured.err


def test_command_fails_closed_when_bindings_missing_for_custom_cases(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cases_path = tmp_path / "cases.json"
    fixture = build_offline_fixture_evaluation()
    _write_json(cases_path, [fixture.cases[0].to_dict()])

    assert command.main(["--cases", str(cases_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "bindings must include" in captured.err


def test_command_has_no_network_credential_gpu_or_release_flags() -> None:
    options = {
        option
        for action in command._parser()._actions
        for option in action.option_strings
    }
    assert {
        "--token",
        "--credential",
        "--download",
        "--gpu",
        "--publish",
        "--upload",
        "--external-tracking",
        "--execute",
        "--prove",
    }.isdisjoint(options)


def test_receipt_parent_must_exist(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "absent" / "receipt.json"
    assert command.main(["--fixture-offline", "--receipt-out", str(output)]) == 2
    captured = capsys.readouterr()
    assert "parent must already exist" in captured.err
    assert captured.out == ""


def test_command_rejects_proof_authority_injection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = build_offline_fixture_evaluation()
    case = fixture.cases[0].to_dict()
    case.pop("case_cid", None)
    case["proof_authority"] = True
    cases_path = tmp_path / "cases.json"
    bindings_path = tmp_path / "bindings.json"
    _write_json(cases_path, [case])
    _write_json(
        bindings_path,
        {
            "source_cid": fixture.source_cid,
            "graph_cid": fixture.graph_cid,
            "index_cid": fixture.index_cid,
            "partition_cid": fixture.partition_cid,
            "license_cid": fixture.license_cid,
            "model_or_checkpoint_cid": fixture.model_or_checkpoint_cid,
            "external_label_admission": fixture.external_label_admission.to_dict()
            if fixture.external_label_admission
            else None,
        },
    )

    assert (
        command.main(
            ["--cases", str(cases_path), "--bindings", str(bindings_path)]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "candidate" in captured.err or "authority" in captured.err
