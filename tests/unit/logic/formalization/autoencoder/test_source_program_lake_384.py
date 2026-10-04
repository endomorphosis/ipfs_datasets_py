"""Execution receipt, source binding, and mixed-batch Lake contracts."""
from copy import deepcopy
import hashlib

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import source_program_lake_384 as subject
from ipfs_datasets_py.logic.software_verification.program import ProgramExpression

ORIGINAL_GUARD = subject._guard


@pytest.fixture(autouse=True)
def allow_unit_executor_substitutions(monkeypatch):
    # Deliberate mocks are not live producer identity evidence. The independent
    # test below calls the real guard and actual builds use it unmodified.
    monkeypatch.setattr(subject, "_guard", lambda: None)


def test_real_loaded_producer_guard_rejects_code_drift(monkeypatch):
    monkeypatch.setattr(subject, "_guard", ORIGINAL_GUARD)
    ORIGINAL_GUARD()
    monkeypatch.setattr(subject.emitter, "emit_program", lambda payload: ("", {}))
    with pytest.raises(ValueError, match="executed code changed"):
        ORIGINAL_GUARD()


def row(identity="sample", *, operator="+", source_operator=None, temporary=False):
    operands = ("expr:left", "expr:right")
    kind = "boolean" if operator in ("<", ">", "==") else "integer"
    expression = f"left {source_operator or operator} right"
    source = "def compute(left: int, right: int) -> " + ("bool" if kind == "boolean" else "int") + ":\n"
    source += f"    answer = {expression}\n    return answer\n" if temporary else f"    return {expression}\n"
    target = dict(kind="program_expression", document=ProgramExpression("expr:result", "binary", kind,
        operand_ids=operands, evaluation_order=operands, operator=operator, source_ref_ids=("source",)).to_dict())
    return dict(id=identity, source_text=source, candidate_ir=target)


def successful_unit_execution(*args):
    # Unit-only executor substitution is not retained as real benchmark evidence.
    return dict(status="passed", backend_executed=True, returncode=0)


def test_preparation_preserves_metadata_and_complete_effects_without_execution():
    rows = [row(temporary=True)]
    before = deepcopy(rows)
    report = subject.prepare_source_program_lean(rows)
    assert rows == before and report["backend_executed"] is False
    assert "sourceEvidenceMetadataJSON" in report["lean_source"]
    assert "sourceEvidence_commands_reads" in report["lean_source"]
    compiled = report["rows"][0]
    assert compiled["semantic_lowering_supported"] is True
    assert compiled["lowering"]["complete_read_write_summaries_checked"] is True
    assert compiled["lowering"]["original_program_modified"] is False
    assert compiled["proof_authority"] is False


def test_all_mismatches_never_compile_an_empty_module(monkeypatch):
    def forbidden(*args):
        pytest.fail("unsupported candidates reached Lake")
    monkeypatch.setattr(subject.executor, "_execute", forbidden)
    rows = [row(source_operator="-")]
    receipt = subject.verify_source_program_lake(subject.build_source_program_lake(rows, lake_executable="unused"), rows)
    assert receipt["status"] == "blocked"
    assert receipt["backend_executed"] is False and receipt["supported_count"] == 0
    assert receipt["rows"][0]["source_qualification"]["status"] == "mismatch"


def test_mixed_batch_does_not_promote_subset_success(monkeypatch):
    monkeypatch.setattr(subject.executor, "_execute", successful_unit_execution)
    rows = [row("valid"), row("wrong", source_operator="-")]
    receipt = subject.verify_source_program_lake(subject.build_source_program_lake(rows, lake_executable="unit-only"), rows)
    assert receipt["status"] == "partial" and receipt["all_candidates_compiled"] is False
    assert receipt["supported_count"] == 1 and receipt["count"] == 2
    assert [r["lake_status"] for r in receipt["rows"]] == ["passed", "blocked"]
    assert not receipt["proof_authority"] and not receipt["source_semantics_verified"]


def test_failed_and_unavailable_executor_never_count_as_pass(monkeypatch):
    for status in ("failed", "unavailable"):
        monkeypatch.setattr(subject.executor, "_execute", lambda *args: dict(status=status, backend_executed=status == "failed"))
        rows = [row()]
        report = subject.build_source_program_lake(rows, lake_executable="unit-only").to_dict()
        assert report["status"] == status and report["all_candidates_compiled"] is False


def test_receipts_require_live_handle_and_exact_unchanged_inputs(monkeypatch):
    monkeypatch.setattr(subject.executor, "_execute", successful_unit_execution)
    rows = [row()]
    handle = subject.build_source_program_lake(rows, lake_executable="unit-only")
    with pytest.raises(ValueError, match="live issued"):
        subject.verify_source_program_lake(handle.to_dict(), rows)
    with pytest.raises(ValueError, match="unissued"):
        subject.SourceProgramLakeExecution().to_dict()
    changed = deepcopy(rows)
    changed[0]["source_text"] += "\n"
    with pytest.raises(ValueError, match="input identity"):
        subject.verify_source_program_lake(handle, changed)
    changed = handle.to_dict()
    changed["proof_authority"] = True
    assert handle.to_dict()["proof_authority"] is False


def test_fresh_output_and_gold_fields_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(subject.executor, "_execute", successful_unit_execution)
    with pytest.raises(ValueError, match="fresh"):
        subject.build_source_program_lake([row()], lake_executable="unit-only", output_directory=tmp_path)
    with pytest.raises(ValueError, match="gold targets"):
        subject.prepare_source_program_lean([{**row(), "target": {}}])
    with pytest.raises(ValueError, match="duplicate"):
        subject.prepare_source_program_lean([row(), row()])


def test_emitter_rejection_does_not_fall_through(monkeypatch):
    def reject(payload):
        raise ValueError("explicit metadata mismatch")
    monkeypatch.setattr(subject.emitter, "emit_program", reject)
    report = subject.prepare_source_program_lean([row()])
    assert report["rows"][0]["reason"] == "explicit metadata mismatch"
    assert report["rows"][0]["semantic_lowering_supported"] is False


def test_execution_tool_identity_is_rechecked(tmp_path, monkeypatch):
    executable = tmp_path / "lake"
    executable.write_bytes(b"unit-test-not-a-real-executable")
    executable.chmod(0o700)
    (tmp_path / "lean").write_bytes(b"unit-test-not-a-real-compiler")
    monkeypatch.setattr(subject.executor, "_execute", lambda *args: dict(status="passed", backend_executed=True,
        executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(), command=[str(executable), "build"]))
    rows = [row()]
    handle = subject.build_source_program_lake(rows, lake_executable=executable)
    executable.write_bytes(b"changed")
    with pytest.raises(ValueError, match="executable changed"):
        subject.verify_source_program_lake(handle, rows)
