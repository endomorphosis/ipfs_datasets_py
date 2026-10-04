"""Independent current-tree tests for DOEP-083 Craig-interpolation planning assistance.

These tests exercise the canonical interpolation module rather than treating a
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

from ipfs_datasets_py.logic.backends.smt.compiler import (  # noqa: E402
    SmtTerm,
    SmtTermKind,
    term_and,
    term_int,
    term_symbol,
)
from ipfs_datasets_py.logic.backends.smt.interpolation import (  # noqa: E402
    INTERPOLATION_INTERFACE,
    NONQUALIFIED_ASSISTANCE_LIMITATIONS,
    PLANNING_ASSISTANCE_ALGORITHM,
    PLANNING_ASSISTANCE_ALGORITHM_VERSION,
    PLANNING_ASSISTANCE_FORBIDDEN_FIELDS,
    PLANNING_ASSISTANCE_HINT_SCHEMA,
    PLANNING_ASSISTANCE_INTERFACE,
    PLANNING_ASSISTANCE_LIMITATIONS,
    PLANNING_ASSISTANCE_SCHEMA,
    PLANNING_ASSISTANCE_SCHEMA_VERSION,
    BoundedCraigInterpolationPlanningAssistance,
    InterpolationError,
    InterpolationPlanningPredicateHint,
    InterpolationStatus,
    PlanningAssistanceStatus,
    PlanningHintOrigin,
    ValidatedInterpolantReceipt,
    admit_interpolant,
    assist_planning_from_interpolant,
    assist_planning_where_qualified,
    compute_and_validate_interpolant,
    probe_interpolation_support,
    validate_planning_assistance,
)

MODULE_PATH = (
    DATASETS_ROOT / "ipfs_datasets_py/logic/backends/smt/interpolation.py"
)
TEST_PATH = Path(__file__).resolve()
OUTPUT_PATH = (
    DATASETS_ROOT
    / "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-083.json"
)
RECEIPT_PATH = (
    DATASETS_ROOT
    / "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-083.json"
)
OWNER_RELATIVE_OUTPUTS = (
    "ipfs_datasets_py/logic/backends/smt/interpolation.py",
    "tests/doep/test_doep_083_add_bounded_craig_interpolation_planning_assistance_.py",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-083.json",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-083.json",
)
TASK_CID = "sha256:b3c8e41242eb5ecede2e2b91a91c77e2001ba857adfc6ba110c9ffe2c6d0f70d"
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


def _range(symbol: str, lower: int, upper: int) -> SmtTerm:
    value = term_symbol(symbol)
    return term_and(
        SmtTerm(SmtTermKind.GE, arguments=(value, term_int(lower))),
        SmtTerm(SmtTermKind.LE, arguments=(value, term_int(upper))),
    )


def _le(symbol: str, upper: int) -> SmtTerm:
    return SmtTerm(SmtTermKind.LE, arguments=(term_symbol(symbol), term_int(upper)))


def _disjoint_unsat() -> tuple[SmtTerm, SmtTerm]:
    return _range("x", 0, 10), _range("x", 20, 30)


def test_declared_outputs_exist() -> None:
    for relative in OWNER_RELATIVE_OUTPUTS:
        assert (DATASETS_ROOT / relative).is_file(), relative


def test_planning_assistance_extends_interpolation_without_competing_subsystem() -> None:
    assert PLANNING_ASSISTANCE_INTERFACE == (
        "BoundedCraigInterpolationPlanningAssistance@1"
    )
    assert PLANNING_ASSISTANCE_SCHEMA == (
        "ipfs_datasets_py/logic/bounded-craig-interpolation-planning-assistance@1"
    )
    assert PLANNING_ASSISTANCE_SCHEMA_VERSION == (
        "bounded-craig-interpolation-planning-assistance/v1"
    )
    assert PLANNING_ASSISTANCE_HINT_SCHEMA == (
        "ipfs_datasets_py/logic/interpolation-planning-predicate-hint@1"
    )
    assert PLANNING_ASSISTANCE_ALGORITHM == (
        "deterministic_bounded_craig_interpolation_planning_assistance"
    )
    assert PLANNING_ASSISTANCE_ALGORITHM_VERSION == (
        "bounded-craig-interpolation-planning-assistance/1.0.0"
    )
    assert dataclasses.is_dataclass(BoundedCraigInterpolationPlanningAssistance)
    assert dataclasses.is_dataclass(InterpolationPlanningPredicateHint)
    assert INTERPOLATION_INTERFACE == "ValidatedCraigInterpolation@1"
    source = MODULE_PATH.read_text(encoding="utf-8").lower()
    assert "not a new planner" in source
    assert "not a competing cegar subsystem" in source
    assert "cannot grant completion authority" in source
    assert "independently verif" in source
    assert "where qualified" in source or "assistance where qualified" in source
    assert "cegar_engine" not in source or "cegar_engine" in PLANNING_ASSISTANCE_FORBIDDEN_FIELDS
    assert "class cegarplanner" not in source
    assert "second_planner" not in source
    assert "lease_id" in PLANNING_ASSISTANCE_FORBIDDEN_FIELDS
    assert "authorizes_full_replan" in PLANNING_ASSISTANCE_FORBIDDEN_FIELDS
    assert "admission_receipt_cid" in PLANNING_ASSISTANCE_FORBIDDEN_FIELDS
    # Keep the extension inside the interpolation module; do not pull accelerate.
    assert "ipfs_accelerate_py" not in MODULE_PATH.read_text(encoding="utf-8")


def test_assist_planning_from_validated_interpolant_is_deterministic() -> None:
    partition_a, partition_b = _disjoint_unsat()
    admitted = admit_interpolant(partition_a, partition_b, _le("x", 15))
    assert admitted.status is InterpolationStatus.VALIDATED
    first = assist_planning_from_interpolant(admitted)
    second = assist_planning_from_interpolant(admitted)
    assert first.status is PlanningAssistanceStatus.QUALIFIED
    assert first.qualified is True
    assert first.validated_interpolant is True
    assert first.completion_authoritative is False
    assert first.extends == INTERPOLATION_INTERFACE
    assert first.interpolant_cid == admitted.interpolant_cid
    assert first.interpolant_receipt_cid == admitted.receipt_cid
    assert "symbol:x" in first.affected_region_ids
    origins = {hint.origin for hint in first.predicate_hints}
    assert PlanningHintOrigin.VALIDATED_INTERPOLANT in origins
    assert PlanningHintOrigin.SHARED_VOCABULARY in origins
    assert "planning_assistance_cannot_grant_completion_authority" in first.limitations
    assert set(PLANNING_ASSISTANCE_LIMITATIONS) <= set(first.limitations)
    assert first.to_dict() == second.to_dict()
    assert validate_planning_assistance(first.to_dict()).to_dict() == first.to_dict()
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.predicate_hints = ()  # type: ignore[misc]


def test_assist_planning_where_qualified_reuses_interpolation_path() -> None:
    partition_a, partition_b = _disjoint_unsat()
    receipt = compute_and_validate_interpolant(partition_a, partition_b)
    assistance = assist_planning_where_qualified(partition_a, partition_b)
    expected = assist_planning_from_interpolant(receipt)
    assert assistance.to_dict() == expected.to_dict()
    capability = probe_interpolation_support()
    if receipt.status is InterpolationStatus.VALIDATED:
        assert assistance.status is PlanningAssistanceStatus.QUALIFIED
        assert assistance.qualified is True
        assert assistance.validated_interpolant is True
        assert assistance.predicate_hints
    else:
        assert assistance.qualified is False
        assert assistance.validated_interpolant is False
        assert assistance.predicate_hints == ()
        assert assistance.status is not PlanningAssistanceStatus.QUALIFIED
        assert set(NONQUALIFIED_ASSISTANCE_LIMITATIONS) <= set(assistance.limitations)
        # Absent producer/API is still a typed non-qualified disposition.
        if not (
            capability.provider_installed
            and capability.provider_qualified
            and capability.interpolation_api
            and capability.theory_qualified
        ):
            assert assistance.status in {
                PlanningAssistanceStatus.FALLBACK,
                PlanningAssistanceStatus.UNAVAILABLE,
                PlanningAssistanceStatus.UNKNOWN,
            }


def test_nonqualified_and_authority_paths_fail_closed() -> None:
    partition_a, partition_b = _disjoint_unsat()
    admitted = admit_interpolant(partition_a, partition_b, _le("x", 15))
    qualified = assist_planning_from_interpolant(admitted)
    with pytest.raises(InterpolationError, match="completion authority"):
        BoundedCraigInterpolationPlanningAssistance.from_dict(
            {**qualified.to_dict(), "completion_authoritative": True}
        )
    with pytest.raises(InterpolationError, match="operational authority field"):
        BoundedCraigInterpolationPlanningAssistance.from_dict(
            {**qualified.to_dict(), "lease_id": "lease:x"}
        )
    with pytest.raises(InterpolationError, match="operational authority field"):
        BoundedCraigInterpolationPlanningAssistance.from_dict(
            {**qualified.to_dict(), "authorizes_full_replan": True}
        )
    with pytest.raises(InterpolationError, match="unknown planning assistance field"):
        BoundedCraigInterpolationPlanningAssistance.from_dict(
            {**qualified.to_dict(), "mystery_field": "forbidden"}
        )
    with pytest.raises(InterpolationError, match="authority is elevated"):
        InterpolationPlanningPredicateHint(
            predicate_id="predicate:bad",
            statement="Shared symbol x is implicated.",
            origin=PlanningHintOrigin.SHARED_VOCABULARY,
            authority="proof",
        )

    unavailable = compute_and_validate_interpolant(
        partition_a, partition_b, provider="absent-provider"
    )
    assert unavailable.status in {
        InterpolationStatus.FALLBACK,
        InterpolationStatus.UNAVAILABLE,
        InterpolationStatus.UNKNOWN,
    }
    assistance = assist_planning_from_interpolant(unavailable)
    assert assistance.qualified is False
    assert assistance.validated_interpolant is False
    assert assistance.predicate_hints == ()
    assert assistance.interpolant_cid == ""
    assert assistance.status is not PlanningAssistanceStatus.QUALIFIED
    with pytest.raises(InterpolationError, match="validated interpolant"):
        BoundedCraigInterpolationPlanningAssistance.from_dict(
            {
                **assistance.to_dict(),
                "qualified": True,
                "validated_interpolant": True,
            }
        )


def test_existing_interpolation_surface_remains_required() -> None:
    partition_a, partition_b = _disjoint_unsat()
    admitted = admit_interpolant(partition_a, partition_b, _le("x", 15))
    assert isinstance(admitted, ValidatedInterpolantReceipt)
    assert admitted.interface == INTERPOLATION_INTERFACE
    assert admitted.admission_checks_passed is True
    capability = probe_interpolation_support()
    assert capability.theory == "QF_LIA"
    # Planning assistance must reuse receipt identity rather than invent a parallel one.
    assistance = assist_planning_from_interpolant(admitted)
    assert assistance.interpolant_receipt_cid == admitted.receipt_cid
    assert assistance.interpolant_cid == admitted.interpolant_cid


def test_output_manifest_and_candidate_receipt_bind_the_current_tree() -> None:
    manifest = _load_json(OUTPUT_PATH)
    receipt = _load_json(RECEIPT_PATH)
    assert manifest["schema"] == "ipfs_accelerate_py/agent-supervisor/doep-task-output@1"
    assert receipt["schema"] == "ipfs_accelerate_py/agent-supervisor/doep-task-receipt@1"
    assert manifest["task_id"] == receipt["task_id"] == "DOEP-083"
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
    contract = manifest["bounded_craig_interpolation_planning_assistance"]
    assert contract["module"] == (
        "ipfs_datasets_py.logic.backends.smt.interpolation"
    )
    assert contract["interface"] == PLANNING_ASSISTANCE_INTERFACE
    assert contract["schema"] == PLANNING_ASSISTANCE_SCHEMA
    assert contract["schema_version"] == PLANNING_ASSISTANCE_SCHEMA_VERSION
    assert contract["class_name"] == "BoundedCraigInterpolationPlanningAssistance"
    assert contract["hint_class"] == "InterpolationPlanningPredicateHint"
    assert contract["entrypoints"] == [
        "assist_planning_from_interpolant",
        "assist_planning_where_qualified",
        "validate_planning_assistance",
    ]
    assert contract["extends"] == INTERPOLATION_INTERFACE
    assert contract["algorithm"] == PLANNING_ASSISTANCE_ALGORITHM
    assert contract["algorithm_version"] == PLANNING_ASSISTANCE_ALGORITHM_VERSION
    assert contract["competing_subsystem_created"] is False
    assert contract["completion_authoritative"] is False
    assert contract["assistance_requires_validated_interpolant"] is True
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
