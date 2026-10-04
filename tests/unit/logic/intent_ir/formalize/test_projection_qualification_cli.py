"""Qualification CLI artifacts and process exit codes retain projection limits."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize.extended_projections import validate_intent_family_report
from ipfs_datasets_py.logic.intent_ir.formalize.projection_contracts import source_ir_sha256
from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip import frame_to_intent_ir
from ipfs_datasets_py.logic.intent_ir.schema import (
    ControlEdgeKind, IntentControlEdge, IntentKind, NodeGrounding,
)

ROOT = Path(__file__).resolve().parents[5]
CLI = ROOT / "scripts/validation/qualify_intent_projections.py"


@pytest.fixture
def document():
    return frame_to_intent_ir(
        {"actor": "agent", "action": "read", "object": "cache", "modality": "required"},
        instruction="The agent must read the cache.")


def _write(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _run(tmp_path, document, *options, output=None, context=None):
    input_path = _write(tmp_path / "input-intent.json", document.to_dict())
    output = output or tmp_path / "qualification"
    argv = [sys.executable, str(CLI), "--intent-ir", str(input_path), "--output", str(output)]
    if context is not None:
        argv.extend(("--context", str(_write(tmp_path / "context.json", context))))
    argv.extend(str(option) for option in options)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    environment.update(CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    result = subprocess.run(argv, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60)
    return result, output


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_pure_typed_cli_exports_digest_bound_artifacts_without_tools(tmp_path, document):
    result, output = _run(tmp_path, document,
        "--lake-executable", tmp_path / "missing-lake", "--java-executable", tmp_path / "missing-java")
    assert result.returncode == 0, result.stderr
    summary = _read(output / "qualification.json")
    assert json.loads(result.stdout) == summary
    assert summary["schema"] == "intent-projection-qualification/v1"
    assert summary["source_ir_sha256"] == source_ir_sha256(document)
    assert summary["external_checks"] == [] and not summary["all_requested_checks_passed"]
    assert summary["proof_authority"] is summary["source_semantics_verified"] is False
    assert summary["program_correctness_verified"] is False
    report = _read(output / "projections.json")
    assert validate_intent_family_report(report, document) == report
    assert _read(output / "intent-ir.json") == document.to_dict()
    assert _read(output / "syntax-checks.json") == []
    assert not (output / "inference.json").exists()
    assert (output / "IntentProjection.lean").is_file()
    assert len(list(output.glob("*.tla"))) == len(list(output.glob("*.cfg"))) == 1
    entries = {entry["name"]: entry for entry in summary["files"]}
    assert set(entries) == {p.name for p in output.iterdir() if p.name != "qualification.json"}
    for name, entry in entries.items():
        raw = (output / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
        assert len(raw) == entry["bytes"]


@pytest.mark.parametrize("checker", ["lean", "tla", "both"])
def test_requested_checker_with_unselected_family_returns_two(tmp_path, document, checker):
    options = ["--family", "frame_logic"]
    if checker in {"lean", "both"}:
        options += ["--check-lean", "--lake-executable", str(tmp_path / "missing-lake")]
    if checker in {"tla", "both"}:
        options += ["--check-tla", "--tla-jar", str(tmp_path / "missing.jar")]
    result, output = _run(tmp_path, document, *options)
    assert result.returncode == 2, result.stderr
    checks = _read(output / "syntax-checks.json")
    assert len(checks) == (2 if checker == "both" else 1)
    assert all(row["status"] == "not_run" and row["reason"] == "family_not_selected" for row in checks)
    summary = _read(output / "qualification.json")
    assert summary["all_requested_checks_passed"] is False
    assert summary["projections"][0]["family"] == "frame_logic"
    assert not list(output.glob("*.lean")) and not list(output.glob("*.tla"))


@pytest.mark.parametrize("context", [
    {"pretend_verified": {}},
    {"state": {"max_steps": 0}},
    {"structural": {"requested_families": ["frame_logic"]}},
    {"structural": {"refinement_evidence": {"source_ir_sha256": "a" * 64, "document": {}}}},
])
def test_invalid_context_fails_before_creating_qualification_output(tmp_path, document, context):
    result, output = _run(tmp_path, document, context=context)
    assert result.returncode != 0
    assert not output.exists()
    assert not result.stdout.strip()


@pytest.mark.parametrize("family,context", [
    ("higher_order", {"state": {"max_steps": 0}}),
    ("frame_logic", {"modal": {"proof_authority": True}}),
    ("tdfol", {"structural": {"refinement_evidence": {"document": {}}}}),
    ("datalog", {"structural": {"refinement_evidence": {"document": {}}}}),
])
def test_supplied_context_is_not_silently_ignored_for_unselected_families(tmp_path, document, family, context):
    result, output = _run(tmp_path, document, "--family", family, context=context)
    assert result.returncode != 0
    assert not output.exists()


def test_existing_qualification_directory_and_files_are_never_overwritten(tmp_path, document):
    result, output = _run(tmp_path, document, "--family", "frame_logic")
    assert result.returncode == 0, result.stderr
    sentinel = output / "owner-notes.txt"
    sentinel.write_bytes(b"preserve existing reviewed qualification\n")
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    result, same = _run(tmp_path, replace(document, title="different source"),
                        "--family", "higher_order", output=output)
    assert result.returncode != 0 and same == output
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before
    assert "FileExistsError" in result.stderr


def test_partial_tla_export_stays_partial_and_missing_backend_is_not_passed(tmp_path, document):
    result, output = _run(tmp_path, document, "--family", "transition_system",
                          "--check-tla", "--tla-jar", tmp_path / "missing.jar")
    assert result.returncode == 2, result.stderr
    report = _read(output / "projections.json")
    assert report["all_requested_families_projected"] is False
    assert all(row["status"] == "partial" and row["unsupported"] for row in report["projections"])
    assert all(row["proof_authority"] is False for row in report["projections"])
    checks = _read(output / "syntax-checks.json")
    assert len(checks) == 1 and checks[0]["status"] == "unavailable"
    assert checks[0]["runs"] == [] and checks[0]["proof_authority"] is False
    summary = _read(output / "qualification.json")
    assert summary["all_requested_checks_passed"] is False
    assert all(row["status"] == "partial" and row["unsupported_count"] > 0 for row in summary["projections"])


def test_unsupported_tla_branch_never_passes_or_exports_a_fabricated_model(tmp_path, document):
    second = replace(document.actions[0], action_id="second", verb="update")
    edge = IntentControlEdge("conditional", "action", "second", ControlEdgeKind.CONDITIONAL,
                             source_ref_ids=("source",), grounding=NodeGrounding.INFERRED)
    document = replace(document, intent_kind=IntentKind.PROCEDURE,
        actions=(*document.actions, second), control_edges=(edge,), terminal_action_ids=("second",))
    result, output = _run(tmp_path, document, "--family", "transition_system",
                          "--model-check", "--tla-jar", tmp_path / "missing.jar")
    assert result.returncode == 2, result.stderr
    checks = _read(output / "syntax-checks.json")
    assert len(checks) == 1 and checks[0]["status"] == "unsupported"
    assert checks[0]["reason"] == "no_supported_state_model"
    assert checks[0]["proof_authority"] is False
    assert not list(output.glob("*.tla")) and not list(output.glob("*.cfg"))
    summary = _read(output / "qualification.json")
    assert summary["all_requested_checks_passed"] is False
    assert all(row["status"] == "unsupported" for row in summary["projections"])


def test_real_installed_lake_cli_validates_types_without_asserting_program_correctness(tmp_path, document):
    native = Path.home() / ".elan/toolchains/leanprover--lean4---v4.34.1/bin/lake"
    if not native.is_file():
        pytest.skip("explicit installed Lean 4.34.1 required; this test never downloads a toolchain")
    result, output = _run(tmp_path, document, "--family", "higher_order", "--check-lean",
                          "--lake-executable", native, "--lean-toolchain", "leanprover/lean4:v4.34.1",
                          "--timeout-seconds", "30")
    assert result.returncode == 0, result.stderr + result.stdout
    checks = _read(output / "syntax-checks.json")
    assert len(checks) == 1 and checks[0]["status"] == "passed"
    assert checks[0]["backend_executed"] is True
    assert checks[0]["syntax_valid"] is checks[0]["typecheck_valid"] is True
    assert checks[0]["proof_authority"] is checks[0]["proof_obligations_discharged"] is False
    assert checks[0]["source_semantics_verified"] is checks[0]["program_correctness_verified"] is False
    assert all(row["returncode"] == 0 for row in checks[0]["observations"])
    summary = _read(output / "qualification.json")
    assert summary["all_requested_checks_passed"] is True
    assert summary["program_correctness_verified"] is summary["proof_authority"] is False
    assert summary["projections"][0]["status"] == "partial"
    assert summary["projections"][0]["unsupported_count"] > 0


@pytest.mark.parametrize("options", [
    ["--instruction-file", "missing.txt"],  # mutually exclusive with --intent-ir
    ["--checkpoint-descriptor", "missing.json"],
    ["--check-tla"], ["--model-check"], ["--timeout-seconds", "0"],
    ["--timeout-seconds", "61"], ["--family", "not_a_logic_family"],
])
def test_invalid_cli_combinations_cannot_create_success_artifacts(tmp_path, document, options):
    result, output = _run(tmp_path, document, *options)
    assert result.returncode != 0
    assert not output.exists()
