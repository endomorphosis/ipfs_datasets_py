"""Independent current-tree tests for DOEP-082 counterexample/unsat-core refinement.

These tests exercise the canonical explanation module rather than treating a
worker assertion as acceptance evidence.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

DATASETS_ROOT = Path(__file__).resolve().parents[2]
if str(DATASETS_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASETS_ROOT))

from ipfs_datasets_py.logic.software_verification.counterexamples.explanation import (  # noqa: E402
    COUNTEREXAMPLE_EXPLANATION_INTERFACE,
    COUNTEREXAMPLE_REFINEMENT_FORBIDDEN_FIELDS,
    COUNTEREXAMPLE_REFINEMENT_SCHEMA,
    COUNTEREXAMPLE_REFINEMENT_SCHEMA_VERSION,
    COUNTEREXAMPLE_UNSAT_CORE_REFINEMENT_INTERFACE,
    CoreMinimality,
    CounterexampleRefinement,
    ExplanationError,
    PredicateHintOrigin,
    REFINEMENT_ALGORITHM_NAME,
    REFINEMENT_ALGORITHM_VERSION,
    RefinementSourceKind,
    UNSAT_CORE_REFINEMENT_SCHEMA,
    UnsatCoreRefinement,
    explain_counterexample,
    refine_from_counterexample,
    refine_from_unsat_core,
    refine_unsat_core,
    validate_counterexample_refinement,
)

MODULE_PATH = (
    DATASETS_ROOT
    / "ipfs_datasets_py/logic/software_verification/counterexamples/explanation.py"
)
TEST_PATH = Path(__file__).resolve()
OUTPUT_PATH = (
    DATASETS_ROOT
    / "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-082.json"
)
RECEIPT_PATH = (
    DATASETS_ROOT
    / "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-082.json"
)
OWNER_RELATIVE_OUTPUTS = (
    "ipfs_datasets_py/logic/software_verification/counterexamples/explanation.py",
    "tests/doep/test_doep_082_add_counterexample_and_unsat_core_refinement.py",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-082.json",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-082.json",
)
TASK_CID = "sha256:0a527074471981146fcf6d795d5c8f1981e382a0281b9739aa0adb82e41f6656"
PLAN_CID = "sha256:6c197a4b92682b3b813656123e09956846dc4f5abadf417f37fb7cc0133ddba4"
BASE_REPOSITORIES = {
    "ipfs_accelerate_py": {
        "commit": "87715e9295626e7918f7fc8a7b1a1531ab04208f",
        "tree": "1c9a399cc7a599d5904e5be2ae58c6be3650cff7",
    },
    "ipfs_datasets_py": {
        "commit": "3668b8857a9aa7b1a3c847be12725b5cd057d2e7",
        "tree": "456e09b51d6a07a3a5873436df24054768195320",
    },
    "ipfs_kit_py": {
        "commit": "b6c65ba732733d7e33852713ba18aa3b12235668",
        "tree": "14da7d92e130b7ba3523d0d6741a3ef7ef1e1bc2",
    },
    "lift_coding": {
        "commit": "bb8869ed72eb7002434345d9969efee729c4f7f6",
        "tree": "99e85bfe584b7688ffbeff86da1e612dd6893a42",
    },
}


def _load_json(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(result, dict)
    return result


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _smt_core_witness(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "smt_unsat_core",
        "core": ["assert:bound", "assert:transition", "assert:invariant", "assert:noise"],
        "violated_property": "prop:resource-invariant",
        "property_id": "prop:resource-invariant",
        "assumption_ids": ["asm:finite-domain"],
        "finite_bounds": {"timeout_ms": 250, "max_depth": 8},
        "tool_id": "solver.z3",
        "tool_version": "4.12.0",
        "provider_id": "solver.z3",
        "tree_id": "tree:doep-082@1",
        "policy_id": "policy:public-counterexample-drop@1",
        "summary": "unsat core implicates the invariant under finite bound",
        "source_map": {
            "ast_scope_ids": ["symbol:invariant"],
            "source_ref_ids": ["source:resource.py"],
            "span_ids": ["span:invariant-check"],
            "tree_ids": ["tree:doep-082@1"],
        },
        "content_id": "sha256:" + ("cd" * 32),
        "counterexample_id": "cex:doep-082-unsat-1",
        "repair_classes": ["constrain_ast_scope_or_model_bound"],
    }
    payload.update(overrides)
    return payload


def _still_unsat(members: Any) -> bool:
    required = {"assert:bound", "assert:invariant"}
    return required.issubset(set(members))


def test_declared_outputs_exist() -> None:
    for relative in OWNER_RELATIVE_OUTPUTS:
        assert (DATASETS_ROOT / relative).is_file(), relative


def test_refinement_extends_explanation_without_competing_subsystem() -> None:
    assert COUNTEREXAMPLE_UNSAT_CORE_REFINEMENT_INTERFACE == (
        "CounterexampleUnsatCoreRefinement@1"
    )
    assert COUNTEREXAMPLE_REFINEMENT_SCHEMA == (
        "ipfs_datasets_py/logic/counterexample-unsat-core-refinement@1"
    )
    assert COUNTEREXAMPLE_REFINEMENT_SCHEMA_VERSION == (
        "counterexample-unsat-core-refinement/v1"
    )
    assert UNSAT_CORE_REFINEMENT_SCHEMA == (
        "ipfs_datasets_py/logic/unsat-core-refinement@1"
    )
    assert REFINEMENT_ALGORITHM_NAME == (
        "deterministic_counterexample_unsat_core_refinement"
    )
    assert REFINEMENT_ALGORITHM_VERSION == (
        "counterexample-unsat-core-refinement/1.0.0"
    )
    assert dataclasses.is_dataclass(CounterexampleRefinement)
    assert dataclasses.is_dataclass(UnsatCoreRefinement)
    assert COUNTEREXAMPLE_EXPLANATION_INTERFACE == "CounterexampleExplanation@1"
    source = MODULE_PATH.read_text(encoding="utf-8").lower()
    assert "not a new planner" in source
    assert "not a competing cegar subsystem" in source
    assert "not a second minimizer" in source
    assert "never called an interpolant" in source or "never claim" in source
    assert "cannot grant completion authority" in source
    assert "independently verif" in source
    assert "cegar_engine" not in source
    assert "class cegarrefiner" not in source
    assert "second_minimizer" not in source
    assert "authorizes_full_replan" in COUNTEREXAMPLE_REFINEMENT_FORBIDDEN_FIELDS
    assert "interpolant_cid" in COUNTEREXAMPLE_REFINEMENT_FORBIDDEN_FIELDS
    assert "lease_id" in COUNTEREXAMPLE_REFINEMENT_FORBIDDEN_FIELDS
    # Keep the extension inside the explanation module; do not pull accelerate.
    assert "ipfs_accelerate_py" not in MODULE_PATH.read_text(encoding="utf-8")


def test_refine_unsat_core_is_deterministic_and_subset_minimal_under_oracle() -> None:
    core = [
        "assert:bound",
        "assert:transition",
        "assert:invariant",
        "assert:noise",
        "assert:bound",
    ]
    unvalidated = refine_unsat_core(core)
    assert unvalidated.original_core == (
        "assert:bound",
        "assert:transition",
        "assert:invariant",
        "assert:noise",
    )
    assert unvalidated.refined_core == unvalidated.original_core
    assert unvalidated.minimality is CoreMinimality.UNVALIDATED
    assert unvalidated.claims_interpolant is False
    assert unvalidated.completion_authoritative is False

    reduced = refine_unsat_core(
        core,
        still_unsat=_still_unsat,
        core_validated=True,
        validation_receipt_id="receipt:doep-082-core",
    )
    assert reduced.refined_core == ("assert:bound", "assert:invariant")
    assert reduced.dropped_members == ("assert:transition", "assert:noise")
    assert reduced.minimality is CoreMinimality.ORACLE_MINIMAL
    assert reduced.core_validated is True
    assert validate_counterexample_refinement(
        refine_from_unsat_core(reduced, counterexample_id="cex:core-only")
    ).source_kind is RefinementSourceKind.UNSAT_CORE

    again = refine_unsat_core(
        core,
        still_unsat=_still_unsat,
        core_validated=True,
        validation_receipt_id="receipt:doep-082-core",
    )
    assert again.to_dict() == reduced.to_dict()


def test_refine_from_counterexample_combines_explanation_and_core() -> None:
    explanation = explain_counterexample(
        _smt_core_witness(),
        violated_property="prop:resource-invariant",
    )
    assert explanation.witness_kind == "smt_core"
    refinement = refine_from_counterexample(
        explanation,
        unsat_core=explanation.decoded_values
        and [item.name for item in explanation.decoded_values],
        still_unsat=_still_unsat,
        core_validated=True,
        validation_receipt_id="receipt:doep-082-core",
    )
    assert refinement.source_kind is RefinementSourceKind.COMBINED
    assert refinement.interface == COUNTEREXAMPLE_UNSAT_CORE_REFINEMENT_INTERFACE
    assert refinement.schema == COUNTEREXAMPLE_REFINEMENT_SCHEMA
    assert refinement.explanation_id == explanation.explanation_id
    assert refinement.explanation_content_id == explanation.content_id
    assert refinement.completion_authoritative is False
    assert refinement.claims_interpolant is False
    assert refinement.unsat_core is not None
    assert refinement.unsat_core.refined_core == (
        "assert:bound",
        "assert:invariant",
    )
    origins = {hint.origin for hint in refinement.predicate_hints}
    assert PredicateHintOrigin.COUNTEREXAMPLE_DIVERGENCE in origins
    assert PredicateHintOrigin.UNSAT_CORE_MEMBER in origins
    assert PredicateHintOrigin.DECODED_CORE_MEMBER in origins
    assert "span:invariant-check" in refinement.affected_region_ids
    payload = refinement.to_dict()
    assert "raw" not in payload
    assert validate_counterexample_refinement(payload).to_dict() == payload
    with pytest.raises(dataclasses.FrozenInstanceError):
        refinement.predicate_hints = ()  # type: ignore[misc]


def test_unsat_core_is_never_an_interpolant_and_authority_fails_closed() -> None:
    with pytest.raises(ExplanationError, match="interpolant"):
        UnsatCoreRefinement(
            original_core=("a",),
            refined_core=("a",),
            claims_interpolant=True,
        )
    with pytest.raises(ExplanationError, match="completion authority"):
        UnsatCoreRefinement(
            original_core=("a",),
            refined_core=("a",),
            completion_authoritative=True,
        )
    with pytest.raises(ExplanationError, match="core_validated"):
        UnsatCoreRefinement(
            original_core=("a", "b"),
            refined_core=("a",),
            minimality=CoreMinimality.ORACLE_MINIMAL,
            core_validated=False,
        )
    with pytest.raises(ExplanationError, match="subset"):
        UnsatCoreRefinement(
            original_core=("a",),
            refined_core=("a", "b"),
        )
    with pytest.raises(ExplanationError, match="empty"):
        refine_unsat_core([])
    with pytest.raises(ExplanationError, match="not unsatisfiable"):
        refine_unsat_core(
            ["assert:noise"],
            still_unsat=_still_unsat,
            core_validated=True,
            validation_receipt_id="receipt:bad",
        )

    explanation = explain_counterexample(_smt_core_witness())
    refinement = refine_from_counterexample(explanation)
    with pytest.raises(ExplanationError, match="completion authority"):
        CounterexampleRefinement.from_dict(
            {**refinement.to_dict(), "completion_authoritative": True}
        )
    with pytest.raises(ExplanationError, match="operational authority field"):
        CounterexampleRefinement.from_dict(
            {**refinement.to_dict(), "interpolant_cid": "cid:fabricated"}
        )
    with pytest.raises(ExplanationError, match="operational authority field"):
        CounterexampleRefinement.from_dict(
            {**refinement.to_dict(), "lease_id": "lease:x"}
        )
    with pytest.raises(ExplanationError, match="operational authority field"):
        CounterexampleRefinement.from_dict(
            {**refinement.to_dict(), "policy_pointer": "forbidden"}
        )
    with pytest.raises(ExplanationError, match="unknown counterexample refinement field"):
        CounterexampleRefinement.from_dict(
            {**refinement.to_dict(), "mystery_field": "forbidden"}
        )
    with pytest.raises(ExplanationError, match="interpolant"):
        CounterexampleRefinement.from_dict(
            {**refinement.to_dict(), "claims_interpolant": True}
        )


def test_existing_explanation_surface_remains_required() -> None:
    explanation = explain_counterexample(_smt_core_witness())
    assert explanation.interface == COUNTEREXAMPLE_EXPLANATION_INTERFACE
    assert explanation.redacted is True
    assert explanation.first_divergence.path == "core[0]"
    assert explanation.to_public_dict().get("raw") is None
    # Refinement must reuse the explanation identity rather than invent a parallel one.
    refinement = refine_from_counterexample(explanation)
    assert refinement.explanation_id == explanation.explanation_id
    assert refinement.counterexample_id == explanation.counterexample_id


def test_output_manifest_and_candidate_receipt_bind_the_current_tree() -> None:
    manifest = _load_json(OUTPUT_PATH)
    receipt = _load_json(RECEIPT_PATH)
    assert manifest["schema"] == "ipfs_accelerate_py/agent-supervisor/doep-task-output@1"
    assert receipt["schema"] == "ipfs_accelerate_py/agent-supervisor/doep-task-receipt@1"
    assert manifest["task_id"] == receipt["task_id"] == "DOEP-082"
    assert manifest["task_cid"] == receipt["task_cid"] == TASK_CID
    assert manifest["plan_cid"] == receipt["plan_cid"] == PLAN_CID
    assert list(manifest["declared_outputs"]) == list(OWNER_RELATIVE_OUTPUTS)
    assert receipt["expected_outputs"] == list(OWNER_RELATIVE_OUTPUTS)
    assert receipt["changed_paths"] == list(OWNER_RELATIVE_OUTPUTS)
    assert receipt["write_scope"] == list(OWNER_RELATIVE_OUTPUTS)
    assert manifest["completion_authoritative"] is False
    assert receipt["worker_completion_insufficient"] is True
    assert manifest["no_competing_subsystem_created"] is True
    assert receipt["no_competing_subsystem_created"] is True
    assert manifest["base_repositories"] == BASE_REPOSITORIES
    assert manifest["primary_output"] == OWNER_RELATIVE_OUTPUTS[0]
    contract = manifest["counterexample_unsat_core_refinement"]
    assert contract["module"] == (
        "ipfs_datasets_py.logic.software_verification.counterexamples.explanation"
    )
    assert contract["interface"] == COUNTEREXAMPLE_UNSAT_CORE_REFINEMENT_INTERFACE
    assert contract["schema"] == COUNTEREXAMPLE_REFINEMENT_SCHEMA
    assert contract["schema_version"] == COUNTEREXAMPLE_REFINEMENT_SCHEMA_VERSION
    assert contract["class_name"] == "CounterexampleRefinement"
    assert contract["unsat_core_class"] == "UnsatCoreRefinement"
    assert contract["entrypoints"] == [
        "refine_from_counterexample",
        "refine_from_unsat_core",
        "refine_unsat_core",
        "validate_counterexample_refinement",
    ]
    assert contract["extends"] == "CounterexampleExplanation@1"
    assert contract["competing_subsystem_created"] is False
    assert contract["claims_interpolant"] is False
    assert contract["completion_authoritative"] is False
    assert contract["operational_admission_owner"] == "ipfs_accelerate_py"
    assert contract["semantic_identity_owner"] == "ipfs_datasets_py"
    assert receipt["outputs_present"] == {
        path: True for path in OWNER_RELATIVE_OUTPUTS
    }
    assert receipt["path_digests"] == {
        OWNER_RELATIVE_OUTPUTS[0]: _digest(MODULE_PATH),
        OWNER_RELATIVE_OUTPUTS[1]: _digest(TEST_PATH),
        OWNER_RELATIVE_OUTPUTS[2]: _digest(OUTPUT_PATH),
    }
    assert "Worker or model assertion alone is insufficient." in (
        receipt["required_evidence"]["limitations"]
    )
