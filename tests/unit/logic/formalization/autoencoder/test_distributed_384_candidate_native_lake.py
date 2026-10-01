"""Audited program extension, exact replay and process-local build evidence."""
from copy import deepcopy
import importlib
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import candidate_native_lake as gate
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import legal_ui_inputs
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.projection_context_contract import bind_context
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v7 as family
from tests.unit.logic.formalization.autoencoder.test_distributed_384_projection_inputs import sample, security_inputs, prepare
from tests.unit.logic.formalization.autoencoder.test_distributed_384_legal_ui_inputs import ui_sample


def case(domain="security_ir", families=None, *, formula=False):
    row = sample(domain)
    if domain == "security_ir":
        inputs = security_inputs(row)
        if formula:
            inputs["formula_inputs"] = [{"requirement_id": "FOL", "formula": "forall x. Reports(x)"}]
        source = prepare(domain, row, inputs)
    elif domain == "intent_ir":
        source = prepare(domain, row, {})
    else:
        source = legal_ui_inputs.prepare_source_inputs(domain, row["target"], row["source_text"])
    selected = families if families is not None else (["program", "first_order"] if formula else
        ["program"] if domain == "security_ir" else ["frame_logic"] if domain == "ui_ux_ir" else ["deontic"])
    report = family.prepare_family_training_targets_v7(domain, requested_families=selected, **source)
    return report, dict(source_inputs=source, source_text=row["source_text"], candidate=row["target"])


@pytest.mark.parametrize("domain", ["legal_ir", "ui_ux_ir", "intent_ir"])
def test_unrelated_native_rows_and_lean_remain_identical(domain):
    report, kwargs = case(domain)
    original = gate.previous.prepare_native_family_lean(report, source_inputs=kwargs["source_inputs"])
    current = gate.prepare_native_family_lean(report, **kwargs)
    assert current["per_projection"] == original["per_projection"]
    assert current["lean_source"] == original["lean_source"]
    assert current["extended_projection_count"] == 0
    assert not current["backend_executed"]
    assert all(current[key] is False for key in gate.FALSE)


def test_only_source_joined_program_blocker_is_extended_and_archived():
    report, kwargs = case(formula=True)
    saved = deepcopy(report)
    original = gate.previous.prepare_native_family_lean(report, source_inputs=kwargs["source_inputs"])
    current = gate.prepare_native_family_lean(report, **kwargs)
    assert current["extended_projection_count"] == 1
    assert report == saved
    for before, after in zip(original["per_projection"], current["per_projection"]):
        if before["projection_id"] == "program.program_ir/v1":
            assert before["reason"] == "program_metadata_requires_explicit_semantics_review"
            assert after["previous_lowering_observation"] == before
            assert after["semantic_lowering_supported"] and after["parser_status"] == "passed"
            assert after["lake_status"] == "not_run"
            assert after["lowering"]["source_join_audit"]["inverse_source_join_verified"]
        else:
            assert before == after
    assert "distributedCodeUnitJoinedProgramJSON" in current["lean_source"]
    assert "sourceEvidenceEffectAuditJSON" in current["lean_source"]
    assert str(Path(gate.__file__).resolve()) in current["producer"]
    assert str(Path(gate.program.__file__).resolve()) in current["producer"]


@pytest.mark.parametrize("part", ["source", "candidate", "typed_inputs", "report"])
def test_changed_native_inputs_cannot_borrow_program_lowering(part):
    report, kwargs = case()
    if part == "source":
        kwargs["source_text"] += "\n"
    elif part == "candidate":
        kwargs["candidate"]["document"]["operator"] = ">"
    elif part == "typed_inputs":
        kwargs["source_inputs"]["typed_inputs"] = []
    else:
        report["projections"][0]["payload"]["metadata"]["effect_summary_audit"] = {}
    with pytest.raises(ValueError):
        gate.prepare_native_family_lean(report, **kwargs)


@pytest.mark.parametrize("domain", ["legal_ir", "ui_ux_ir", "intent_ir"])
def test_raw_wrapper_cannot_attach_an_unrelated_valid_candidate(domain):
    report, kwargs = case(domain)
    if domain == "legal_ir":
        kwargs["candidate"]["rules"][0]["action"] = "archive"
    elif domain == "ui_ux_ir":
        kwargs["candidate"]["document"]["purpose"] = "Different purpose"
    else:
        kwargs["candidate"]["document"]["actor"] = "registrar"
    with pytest.raises(ValueError):
        gate.prepare_native_family_lean(report, **kwargs)


def test_canonical_intent_candidate_document_cannot_claim_foreign_source():
    from ipfs_datasets_py.logic.intent_ir.formalize.rich_logic import project_rich_intent_logic
    from ipfs_datasets_py.logic.intent_ir.decoder import decode_intent_ir
    row = sample("intent_ir")
    target = project_rich_intent_logic(row["target"]["document"], instruction=row["source_text"])["native_intent_ir"]
    target["sources"][0]["content_sha256"] = "0" * 64
    source = dict(document=decode_intent_ir(target), source_text=row["source_text"])
    report = family.prepare_family_training_targets_v7("intent_ir", requested_families=["deontic"], **source)
    with pytest.raises(ValueError, match="candidate source hash differs"):
        gate.prepare_native_family_lean(report, source_inputs=source, source_text=row["source_text"], candidate=target)


def test_security_candidate_join_is_checked_when_program_family_is_not_requested():
    report, kwargs = case(families=["first_order"], formula=True)
    assert all(p["logic_family"] != "program" for p in report["projections"])
    kwargs["candidate"]["document"]["operator"] = ">"
    with pytest.raises(ValueError, match="candidate must match exact source"):
        gate.prepare_native_family_lean(report, **kwargs)


def test_live_unavailable_attempt_is_bound_and_archived_or_unissued_handles_fail(tmp_path):
    report, kwargs = case()
    handle = gate.build_native_family_lake(report, **kwargs, lake_executable="/absent/native/lake",
        output_directory=tmp_path / "evidence")
    receipt = gate.verify_native_family_lake(handle, report, **kwargs)
    assert receipt["status"] == "unavailable" and not receipt["backend_executed"]
    assert not receipt["all_requested_projections_passed"]
    assert (tmp_path / "evidence" / "SecurityIR.lean").read_text() == receipt["lean_source"]
    assert gate.verify_native_family_lake(handle, report, "program.program_ir/v1", **kwargs)["lake_status"] == "unavailable"
    for fake in (receipt, gate.CandidateNativeLakeExecution(), gate.previous.NativeFamilyLakeExecution()):
        with pytest.raises(ValueError, match="live issued"):
            gate.verify_native_family_lake(fake, report, **kwargs)
    detached = handle.to_dict()
    detached["status"] = "passed"
    assert handle.to_dict()["status"] == "unavailable"
    with pytest.raises(ValueError, match="fresh"):
        gate.build_native_family_lake(report, **kwargs, lake_executable="/absent/native/lake",
            output_directory=tmp_path / "evidence")
    with pytest.raises(ValueError, match="no bound"):
        gate.verify_native_family_lake(handle, report, "missing", **kwargs)


@pytest.mark.parametrize("part", ["source", "candidate", "report", "typed_inputs"])
def test_verify_requires_original_candidate_source_report_and_native_inputs(part):
    report, kwargs = case("legal_ir")
    handle = gate.build_native_family_lake(report, **kwargs, lake_executable="/absent/native/lake")
    if part == "source":
        kwargs["source_text"] += " Changed."
    elif part == "candidate":
        kwargs["candidate"]["rules"][0]["action"] = "archive"
    elif part == "report":
        report["source_digest"] = "0" * 64
    else:
        kwargs["source_inputs"]["source_text"] += " Changed."
    with pytest.raises(ValueError):
        gate.verify_native_family_lake(handle, report, **kwargs)


def installed_lake():
    candidates = [Path("/home/barberb/.elan/toolchains/leanprover--lean4---v4.34.1/bin/lake"),
                  Path("/home/barberb/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lake")]
    lake = next((p for p in candidates if p.is_file()), None)
    if lake is None:
        pytest.skip("installed native Lake unavailable; no download attempted")
    return str(lake)


def test_successful_subset_cannot_hide_missing_requested_family():
    report, kwargs = case(families=["program", "first_order"])
    handle = gate.build_native_family_lake(report, **kwargs, lake_executable=installed_lake())
    result = gate.verify_native_family_lake(handle, report, **kwargs)
    assert result["status"] == "partial"
    assert "first_order" in result["missing_requested_families"]
    assert not result["all_requested_projections_passed"]
    assert all(result[key] is False for key in gate.FALSE)


def test_replacing_backend_code_prevents_issuance(monkeypatch):
    report, kwargs = case()
    def execute(*args):
        kwargs["candidate"]["document"]["operator"] = ">"
        return {"status": "passed", "backend_executed": True}
    monkeypatch.setattr(gate.previous, "_execute", execute)
    with pytest.raises(ValueError, match="imported producer source or executed code changed"):
        gate.build_native_family_lake(report, **kwargs, lake_executable="unused")


def test_later_unrelated_native_import_does_not_change_candidate_evidence_identity():
    report, kwargs = case("legal_ir")
    handle = gate.build_native_family_lake(report, **kwargs, lake_executable="/absent/native/lake")
    before = handle.to_dict()
    importlib.import_module("ipfs_datasets_py.logic.parsers.finite_field")
    after = gate.verify_native_family_lake(handle, report, **kwargs)
    assert after == before


def test_required_sany_check_remains_blocking_even_when_lake_succeeds():
    target, text, row = ui_sample()
    source = legal_ui_inputs.prepare_source_inputs("ui_ux_ir", target, text,
        context=bind_context("ui_ux_ir", target, text, {"ui_training_row": row}))
    report = family.prepare_family_training_targets_v7("ui_ux_ir", requested_families=["transition_system"], **source)
    kwargs = dict(source_inputs=source, source_text=text, candidate=target)
    handle = gate.build_native_family_lake(report, **kwargs, lake_executable=installed_lake(),
        java_executable="/absent/java", tla2tools_jar="/absent/tla2tools.jar")
    result = gate.verify_native_family_lake(handle, report, **kwargs)
    assert result["execution"]["status"] == "passed" and result["status"] == "partial"
    assert not result["all_requested_projections_passed"]
    assert any(row["reason"] == "required_native_syntax_checker_not_passed" for row in result["per_projection"])


def test_real_native_lake_build_and_live_verified_program_receipt(tmp_path):
    report, kwargs = case(formula=True)
    handle = gate.build_native_family_lake(report, **kwargs, lake_executable=installed_lake(),
        output_directory=tmp_path / "real-lake", timeout_seconds=30)
    result = gate.verify_native_family_lake(handle, report, **kwargs)
    assert result["backend_executed"] and result["status"] == "passed", result["execution"]
    assert result["all_requested_projections_passed"]
    assert result["execution"]["command"][-2:] == ["build", "SecurityIR"]
    assert all(result[key] is False for key in gate.FALSE)
