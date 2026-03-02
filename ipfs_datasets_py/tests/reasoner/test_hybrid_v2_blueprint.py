"""Tests for V3 IR Schema, ID Validator, and Optimizer Drift Gate.

Covers issues #1164 (V3 IR Schema + ID Validator) and #1170 (Optimizer Drift Gate).
"""
from __future__ import annotations

import copy
import dataclasses

import pytest

# Path is set up by the layered conftest.py files (root, tests/, and this directory)
from reasoner.hybrid_v2_blueprint import (
    LegalIRV2, parse_cnl_to_ir_with_diagnostics, parse_cnl_to_ir,
    compile_ir_to_dcec, compile_ir_to_temporal_deontic_fol,
    normalize_ir, validate_ir_v2_contract, validate_v2_canonical_id_registry,
    CNLParseError, run_v2_pipeline_with_defaults, generate_cnl_from_ir,
    build_v2_compiler_parity_report, check_compliance, find_violations,
    explain_proof, clear_v2_proof_store, IRContractValidationError,
    IDRegistryValidationError, DefaultOptimizerHookV2, DefaultKGHookV2,
    RegistryProverHookV2, run_v2_pipeline, CanonicalIdV2, TemporalRelationV2,
    TemporalExprV2, TemporalConstraintV2, FrameV2, FrameKindV2, NormV2,
    DeonticOpV2, EntityV2, SourceRefV2, RuleV2,
)
from reasoner.serialization import (
    validate_v3_ir_payload, map_v2_payload_to_v3, deterministic_v3_canonical_id,
    SUPPORTED_V3_IR_VERSION, SUPPORTED_V3_CNL_VERSION,
    proof_to_dict, proof_from_dict,
)
from reasoner.optimizer_policy import (
    build_optimizer_acceptance_decision, build_optimizer_chain_plan,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def parsed_ir():
    return parse_cnl_to_ir("Contractor shall submit the report")


@pytest.fixture
def parsed_ir_temporal():
    return parse_cnl_to_ir("Vendor shall deliver the goods within 7 days")


@pytest.fixture
def v3_payload(parsed_ir):
    ir_dict = dataclasses.asdict(parsed_ir)
    return map_v2_payload_to_v3(ir_dict)


# ---------------------------------------------------------------------------
# TestV3IRSchema (#1164)
# ---------------------------------------------------------------------------

class TestV3IRSchema:
    def test_v3_validator_accepts_valid_payload(self, v3_payload):
        # GIVEN a valid V3 payload derived from a parsed IR
        # WHEN validated
        result = validate_v3_ir_payload(v3_payload, strict=True)
        # THEN it passes without warnings
        assert result["ok"] is True

    def test_v3_validator_rejects_missing_refs(self, v3_payload):
        # GIVEN a payload where a norm points to a non-existent frame
        bad_payload = copy.deepcopy(v3_payload)
        norm_key = list(bad_payload["norms"].keys())[0]
        bad_payload["norms"][norm_key]["target_frame_ref"] = "frm:doesnotexist"
        # WHEN validated strictly
        # THEN a ValueError is raised
        with pytest.raises(ValueError, match="unknown_target_frame_ref"):
            validate_v3_ir_payload(bad_payload, strict=True)

    def test_v3_validator_rejects_orphan_ids(self, v3_payload):
        # GIVEN a payload with an orphan frame not referenced by any norm
        bad_payload = copy.deepcopy(v3_payload)
        bad_payload["frames"]["frm:orphan_999"] = {
            "id": "frm:orphan_999",
            "kind": "action",
            "predicate": "orphan",
            "roles": {},
        }
        # WHEN validated strictly
        # THEN a ValueError about orphan frame is raised
        with pytest.raises(ValueError, match="orphan_frame_id"):
            validate_v3_ir_payload(bad_payload, strict=True)

    def test_v3_canonical_id_deterministic(self):
        # GIVEN the same namespace and label
        # WHEN deterministic_v3_canonical_id is called twice
        id1 = deterministic_v3_canonical_id("ent", "vendor")
        id2 = deterministic_v3_canonical_id("ent", "vendor")
        # THEN both calls return the same result
        assert id1 == id2
        assert id1.startswith("ent:")

    def test_v3_canonical_id_invalid_namespace(self):
        # GIVEN an invalid namespace
        # WHEN deterministic_v3_canonical_id is called
        # THEN a ValueError is raised
        with pytest.raises((ValueError, KeyError)):
            deterministic_v3_canonical_id("invalid_ns", "label")

    def test_v3_map_v2_to_v3(self, parsed_ir):
        # GIVEN a parsed LegalIRV2
        # WHEN mapped to V3
        ir_dict = dataclasses.asdict(parsed_ir)
        payload = map_v2_payload_to_v3(ir_dict)
        # THEN the payload has valid V3 shape
        assert "ir_version" in payload
        assert "norms" in payload
        assert "frames" in payload
        assert "entities" in payload
        result = validate_v3_ir_payload(payload, strict=True)
        assert result["ok"] is True

    def test_v3_id_namespaces(self, parsed_ir):
        # GIVEN a parsed IR
        # WHEN we check the canonical IDs in the IR
        # THEN all five namespaces are present
        assert any(k.startswith("ent:") for k in parsed_ir.entities.keys())
        assert any(k.startswith("frm:") for k in parsed_ir.frames.keys())
        assert any(k.startswith("nrm:") for k in parsed_ir.norms.keys())
        assert any(k.startswith("src:") for k in parsed_ir.provenance.keys())


# ---------------------------------------------------------------------------
# TestV2ContractValidation
# ---------------------------------------------------------------------------

class TestV2ContractValidation:
    def test_validate_ir_v2_contract_passes_for_parsed_ir(self, parsed_ir):
        # GIVEN a properly parsed IR
        # WHEN validate_ir_v2_contract is called
        result = validate_ir_v2_contract(parsed_ir, strict=True)
        # THEN it returns ok=True
        assert result["ok"] is True
        assert result["strict"] is True

    def test_validate_ir_v2_contract_rejects_on_unknown_frame_ref(self, parsed_ir):
        # GIVEN an IR where a norm's target_frame_ref points to a non-existent frame
        bad_ir = copy.deepcopy(parsed_ir)
        norm_ref = list(bad_ir.norms.keys())[0]
        bad_ir.norms[norm_ref].target_frame_ref = "frm:nonexistent"
        # WHEN validate_ir_v2_contract is called
        # THEN IRContractValidationError is raised
        with pytest.raises(IRContractValidationError):
            validate_ir_v2_contract(bad_ir, strict=True)

    def test_validate_v2_canonical_id_registry_passes(self, parsed_ir):
        # GIVEN a properly parsed IR
        # WHEN validate_v2_canonical_id_registry is called
        result = validate_v2_canonical_id_registry(parsed_ir, strict=True)
        # THEN it returns ok=True with counts
        assert result["ok"] is True
        assert "counts" in result


# ---------------------------------------------------------------------------
# TestOptimizerDriftGate (#1170)
# ---------------------------------------------------------------------------

class ModalityMutatingOptimizer:
    """Test optimizer that changes O->P on all norms (should be rejected)."""

    def optimize_ir(self, ir):
        mutated = copy.deepcopy(ir)
        for norm in mutated.norms.values():
            norm.op = DeonticOpV2.P
        report = {
            "optimizer": "modality_mutator",
            "accepted": True,
            "drift_score": 0.0,
            "semantic_equivalence_assertion": True,
            "rejection_reasons": [],
        }
        return mutated, report


class TargetFrameMutatingOptimizer:
    """Test optimizer that changes norm target_frame_ref (should be rejected)."""

    def optimize_ir(self, ir):
        mutated = copy.deepcopy(ir)
        for norm in mutated.norms.values():
            norm.target_frame_ref = "frm:injected_fake_frame"
        report = {
            "optimizer": "target_frame_mutator",
            "accepted": True,
            "drift_score": 0.0,
            "semantic_equivalence_assertion": True,
            "rejection_reasons": [],
        }
        return mutated, report


class TestOptimizerDriftGate:
    def test_optimizer_accepts_safe_mutation(self):
        # GIVEN the default optimizer hook with no mutation
        # WHEN run_v2_pipeline is called with the default optimizer
        result = run_v2_pipeline(
            "Contractor shall submit the report",
            optimizer_hook=DefaultOptimizerHookV2(),
        )
        opt = result["optimizer_report"]
        # THEN optimizer is applied and accepted
        assert opt["applied"] is True
        assert opt["rejected"] is False

    def test_optimizer_rejects_modality_change(self):
        # GIVEN an optimizer that changes O->P
        # WHEN run_v2_pipeline is called with that optimizer
        result = run_v2_pipeline(
            "Contractor shall submit the report",
            optimizer_hook=ModalityMutatingOptimizer(),
        )
        opt = result["optimizer_report"]
        # THEN the optimizer change is rejected with modality_changed code
        assert opt["rejected"] is True
        assert "modality_changed" in opt["rejected_reason_codes"]

    def test_optimizer_rejects_target_frame_change(self):
        # GIVEN an optimizer that changes target_frame_ref to a fake value
        # WHEN run_v2_pipeline is called
        result = run_v2_pipeline(
            "Contractor shall submit the report",
            optimizer_hook=TargetFrameMutatingOptimizer(),
        )
        opt = result["optimizer_report"]
        # THEN the change is rejected
        assert opt["rejected"] is True
        assert len(opt["rejected_reason_codes"]) > 0

    def test_optimizer_drift_score_deterministic(self):
        # GIVEN the same input sentence and optimizer
        # WHEN run_v2_pipeline is called twice
        r1 = run_v2_pipeline(
            "Contractor shall submit the report",
            optimizer_hook=DefaultOptimizerHookV2(),
        )
        r2 = run_v2_pipeline(
            "Contractor shall submit the report",
            optimizer_hook=DefaultOptimizerHookV2(),
        )
        # THEN the decision_id is the same
        assert r1["optimizer_report"]["decision_id"] == r2["optimizer_report"]["decision_id"]

    def test_optimizer_decision_has_required_fields(self):
        # GIVEN the default optimizer
        # WHEN run_v2_pipeline is called
        result = run_v2_pipeline(
            "Contractor shall submit the report",
            optimizer_hook=DefaultOptimizerHookV2(),
        )
        opt = result["optimizer_report"]
        # THEN all required fields are present
        for field in ("applied", "rejected", "rejected_reason_codes", "failure_count", "decision_id"):
            assert field in opt, f"Missing field: {field}"
