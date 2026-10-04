"""Context binding and replay around an independently supplied base candidate."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import runpy

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import extended_preplanning as wrapper
from ipfs_datasets_py.logic.intent_ir.formalize import extended_projections as projections
from ipfs_datasets_py.logic.intent_ir.formalize import roundtrip
from ipfs_datasets_py.logic.intent_ir.formalize.projection_contracts import canonical_bytes
from ipfs_datasets_py.logic.intent_ir.formalize.projection_request import (
    make_intent_projection_request, validate_intent_projection_request, validate_projection_request_shape,
)

INSTRUCTION = "agent must read cache."
CHECKPOINT = "a" * 64


def document():
    return roundtrip.frame_to_intent_ir(
        {"actor": "agent", "action": "read", "object": "cache", "modality": "required"},
        instruction=INSTRUCTION)


def request():
    return make_intent_projection_request(INSTRUCTION, document(), checkpoint_sha256=CHECKPOINT,
        requested_families=["tdfol"], context={"modal": {"temporal_bindings": [
            {"statement_id": "goal", "operator": "always", "evidence_ref": "source"}]}})


def resign(value, field):
    value = deepcopy(value)
    value.pop(field, None)
    value[field] = hashlib.sha256(canonical_bytes(value)).hexdigest()
    return value


@pytest.fixture
def base_candidate(monkeypatch):
    # Unit isolation: numerical inference is qualified separately by consumer
    # tests. These tests exercise actual native IR and projection implementations.
    base = {"status": "semantic_candidate_advice", "schema": "intent-instruction-roundtrip/v1",
        "candidate_intent_ir": document().to_dict(), "checkpoint_sha256": CHECKPOINT,
        "gaps": ["source_meaning_not_verified"], "proof_authority": False}
    base = resign(base, "report_sha256")
    monkeypatch.setattr(roundtrip, "prepare_roundtrip_intent_instruction", lambda *a, **k: deepcopy(base))
    return base


def test_request_binds_all_inputs_and_copies_mutable_context():
    selected = request()
    checked = validate_intent_projection_request(selected, instruction=INSTRUCTION,
        document=document(), checkpoint_sha256=CHECKPOINT)
    assert selected == checked
    checked["context"]["modal"]["temporal_bindings"][0]["operator"] = "eventually"
    assert selected["context"]["modal"]["temporal_bindings"][0]["operator"] == "always"


@pytest.mark.parametrize("field", ["instruction_sha256", "source_ir_sha256", "checkpoint_sha256"])
def test_rehashed_request_cannot_retarget_instruction_candidate_or_checkpoint(field):
    selected = request(); selected[field] = "b" * 64
    selected = resign(selected, "request_sha256")
    validate_projection_request_shape(selected)
    with pytest.raises(ValueError, match="exact instruction"):
        validate_intent_projection_request(selected, instruction=INSTRUCTION,
            document=document(), checkpoint_sha256=CHECKPOINT)


@pytest.mark.parametrize("families", [[], ["dcec", "dcec"], "dcec", ["first_order"], [True], [[]]])
def test_malformed_or_unsupported_family_selection_rejected(families):
    with pytest.raises(ValueError):
        make_intent_projection_request(INSTRUCTION, document(), checkpoint_sha256=CHECKPOINT,
            requested_families=families)


def test_extra_authority_fields_and_oversized_requests_are_rejected():
    selected = request()
    with pytest.raises(ValueError, match="closed"):
        validate_projection_request_shape(resign({**selected, "proof_authority": True}, "request_sha256"))
    selected["context"]["modal"]["padding"] = "x" * 65536
    with pytest.raises(ValueError, match="byte bound"):
        validate_projection_request_shape(resign(selected, "request_sha256"))


def test_contextual_wrapper_preserves_temporal_scope_and_replays(base_candidate):
    selected = request()
    report = wrapper.prepare_extended_intent_instruction(INSTRUCTION, projection_request=selected)
    assert report["schema"] == wrapper.CONTEXT_SCHEMA
    assert report["base_report_sha256"] == base_candidate["report_sha256"]
    assert report["projection_request"] == selected
    rows = report["extended_projections"]["projections"]
    assert len(rows) == 1 and rows[0]["family_id"] == "tdfol"
    formula = rows[0]["representation"]["payload"]["formulas"][0]
    assert formula["ast"]["node_type"] == "TemporalFormula"
    assert formula["ast"]["formula"]["node_type"] == "DeonticFormula"
    assert wrapper.validate_extended_intent_report(report, instruction=INSTRUCTION) == report


@pytest.mark.parametrize("fault", ["wrong_source", "unselected_context", "bad_digest", "unknown_field"])
def test_invalid_optional_request_keeps_independent_base_advice(base_candidate, fault):
    selected = request()
    if fault == "wrong_source": selected["source_ir_sha256"] = "b" * 64
    if fault == "unselected_context": selected["context"]["state"] = {}
    if fault == "unknown_field": selected["authority"] = "approved"
    selected = resign(selected, "request_sha256")
    if fault == "bad_digest": selected["request_sha256"] = "0" * 64
    report = wrapper.prepare_extended_intent_instruction(INSTRUCTION, projection_request=selected)
    assert report["status"] == "semantic_candidate_advice"
    assert report["extension_status"] == "fail_open_projection_error"
    assert report["extended_projections"] is None
    assert report["candidate_intent_ir"] == base_candidate["candidate_intent_ir"]
    assert report["base_report_sha256"] == base_candidate["report_sha256"]
    assert wrapper.validate_extended_intent_report(report, instruction=INSTRUCTION) == report


def test_transient_contextual_projector_failure_remains_replayable(base_candidate, monkeypatch):
    real = projections.project_intent_families
    def unavailable(*a, **k): raise RuntimeError("temporary fixture failure")
    monkeypatch.setattr(projections, "project_intent_families", unavailable)
    report = wrapper.prepare_extended_intent_instruction(INSTRUCTION, projection_request=request())
    assert report["extension_status"] == "fail_open_projection_error"
    monkeypatch.setattr(projections, "project_intent_families", real)
    assert wrapper.validate_extended_intent_report(report, instruction=INSTRUCTION) == report


@pytest.mark.parametrize("contextual", [False, True])
@pytest.mark.parametrize("payload", ["x" * 262144, "\u2603" * 50000])
def test_oversized_extension_retains_base_and_replays_after_recovery(base_candidate, monkeypatch, contextual, payload):
    real = projections.project_intent_families
    monkeypatch.setattr(projections, "project_intent_families", lambda *a, **k: {"large_fixture": payload})
    selected = request() if contextual else None
    report = wrapper.prepare_extended_intent_instruction(INSTRUCTION, projection_request=selected)
    assert report["status"] == "semantic_candidate_advice"
    assert report["extension_status"] == "fail_open_projection_error"
    assert report["extended_projections"] is None
    assert report["gaps"][-1] == "extended_projection_error_category:ProjectionReportBudgetExceeded"
    assert report["candidate_intent_ir"] == base_candidate["candidate_intent_ir"]
    assert report["base_report_sha256"] == base_candidate["report_sha256"]
    if contextual:
        assert report["projection_request"] == selected
    assert len(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()) <= wrapper.MAX_ADVISORY_REPORT_BYTES
    monkeypatch.setattr(projections, "project_intent_families", real)
    assert wrapper.validate_extended_intent_report(report, instruction=INSTRUCTION) == report


def test_contextual_report_cannot_drop_request_or_change_formula_with_fresh_hash(base_candidate):
    report = wrapper.prepare_extended_intent_instruction(INSTRUCTION, projection_request=request())
    dropped = resign({**report, "projection_request": None}, "report_sha256")
    with pytest.raises(ValueError, match="selected request"):
        wrapper.validate_extended_intent_report(dropped, instruction=INSTRUCTION)
    report["extended_projections"]["projections"][0]["representation"]["source"] = "forged"
    with pytest.raises(ValueError, match="replay"):
        wrapper.validate_extended_intent_report(resign(report, "report_sha256"), instruction=INSTRUCTION)


def test_default_wrapper_keeps_v1_schema(base_candidate):
    report = wrapper.prepare_extended_intent_instruction(INSTRUCTION)
    assert report["schema"] == wrapper.SCHEMA and "projection_request" not in report
    assert wrapper.validate_extended_intent_report(report, instruction=INSTRUCTION) == report


def test_native_parsers_are_in_projection_source_pins():
    pins = projections.projection_producer_pins()
    for name in ("CEC.native.dcec_integration", "TDFOL.tdfol_parser", "parsers.event_calculus",
                 "parsers.flogic", "parsers.rules"):
        assert "ipfs_datasets_py.logic." + name in pins


def test_qualification_cli_exports_the_exact_portable_request(base_candidate, tmp_path):
    root = Path(__file__).resolve().parents[5]
    main = runpy.run_path(str(root / "scripts/validation/qualify_intent_projections.py"))["main"]
    source = tmp_path / "instruction.txt"; source.write_text(INSTRUCTION)
    descriptor = tmp_path / "descriptor.json"; descriptor.write_text("{}")
    context = tmp_path / "context.json"; context.write_text(json.dumps(request()["context"]))
    output = tmp_path / "qualification"
    assert main(["--instruction-file", str(source), "--checkpoint-descriptor", str(descriptor),
        "--context", str(context), "--family", "tdfol", "--output", str(output)]) == 0
    raw = (output / "projection-request.json").read_bytes()
    assert raw == canonical_bytes(request())
    validate_intent_projection_request(json.loads(raw), instruction=INSTRUCTION,
        document=document(), checkpoint_sha256=CHECKPOINT)
    receipt = json.loads((output / "qualification.json").read_text())
    row = next(f for f in receipt["files"] if f["name"] == "projection-request.json")
    assert row["sha256"] == hashlib.sha256(raw).hexdigest()
