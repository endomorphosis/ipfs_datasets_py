"""Synthetic, data-free tests for the negative-only HSSL-G230 boundary."""

from __future__ import annotations

from copy import deepcopy

import pytest

from benchmarks.logic_pipeline import revised_pilot_authorization as g230
from benchmarks.logic_pipeline.cases import (
    REPLACEMENT_HOLDOUT_SEAL_SCHEMA,
    ReplacementHoldoutSeal,
    replacement_holdout_ledger_authority_cid,
)
from benchmarks.logic_pipeline.causal_ablation import (
    CausalExecutionProfileV2,
    CausalRescueCaseV2,
    CausalRescueManifestV2,
)
from benchmarks.logic_pipeline.content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
)
from benchmarks.logic_pipeline.contracts import (
    CAUSAL_PROOF_PROTOCOL_V2_CID,
    CAUSAL_PROOF_VARIANT_PROFILE_V2_CID,
    SEMANTIC_PROTOCOL_V2_CID,
    Split,
)


SOURCE_COMMIT = "a" * 40
ENVIRONMENT_SHA256 = "b" * 64
CANDIDATES = ("A2", "A9")


def _semantic_calibration() -> dict[str, object]:
    body: dict[str, object] = {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark."
            "semantic-calibration-report.v2"
        ),
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "status": "complete",
        "coverage": {
            "case_population_complete": True,
            "coordinate_coverage_complete": True,
            "validated_ablation_graph_coverage_complete": True,
            "field_coverage_complete": True,
            "quality_coordinate_complete": True,
        },
        "quality": {
            "identified": True,
            "semantic_quality_millionths": 900_000,
        },
        "absolute_quality_gate": {"passed": True},
        "holdout_authorized": False,
        "production_promotion_authorized": False,
        "synthetic_test_only": True,
    }
    return {**body, "artifact_cid": cid_for_dag_json(body)}


def _rescue_manifest(split: Split) -> CausalRescueManifestV2:
    case_id = f"{split.value}-rescue"
    case = CausalRescueCaseV2(
        case_id=case_id,
        split=split,
        source_cid=cid_for_bytes(
            f"Synthetic {split.value} source.".encode("utf-8")
        ),
        obligation_id=f"{case_id}-obligation",
        proof_obligation={
            "kind": "theorem",
            "logic": "fol",
            "target": f"Target_{split.value}",
        },
        optional_components=("hammer", "leanstral"),
        review_attestation_cid=cid_for_dag_json(
            {
                "schema": "synthetic-independent-review.v1",
                "case_id": case_id,
            }
        ),
    )
    return CausalRescueManifestV2(
        plan_cid=cid_for_dag_json(
            {"kind": "synthetic-plan", "split": split.value}
        ),
        source_manifest_cid=cid_for_dag_json(
            {"kind": "synthetic-source-manifest", "split": split.value}
        ),
        case_manifest_sha256=(
            "c" * 64 if split is Split.PILOT else "d" * 64
        ),
        cases=(case,),
    )


def _profile(
    manifest: CausalRescueManifestV2,
    calibration_cid: str,
) -> CausalExecutionProfileV2:
    return CausalExecutionProfileV2(
        plan_cid=manifest.plan_cid,
        source_manifest_cid=manifest.source_manifest_cid,
        rescue_manifest_cid=manifest.manifest_cid,
        semantic_calibration_artifact_cid=calibration_cid,
        compiler_reference_population_cid=cid_for_dag_json(
            {
                "kind": "synthetic-compiler-reference-population",
                "manifest_cid": manifest.manifest_cid,
            }
        ),
        environment_sha256=ENVIRONMENT_SHA256,
    )


def _partial_matrix(calibration_cid: str) -> g230.G210ReceiptMatrix:
    manifests = tuple(
        sorted(
            (
                _rescue_manifest(Split.PILOT),
                _rescue_manifest(Split.DEVELOPMENT),
            ),
            key=lambda item: next(
                case.split.value for case in item.cases
            ),
        )
    )
    profiles = tuple(
        sorted(
            (_profile(item, calibration_cid) for item in manifests),
            key=lambda item: item.rescue_manifest_cid,
        )
    )
    return g230.G210ReceiptMatrix(
        semantic_calibration_artifact_cid=calibration_cid,
        rescue_manifests=manifests,
        execution_profiles=profiles,
        causal_aggregates=(),
    )


def _replacement_seal(
    *,
    semantic_protocol_cid: str = SEMANTIC_PROTOCOL_V2_CID,
) -> ReplacementHoldoutSeal:
    protocols = {
        "access_policy": cid_for_dag_json({"policy": "synthetic-access"}),
        "causal_proof": CAUSAL_PROOF_PROTOCOL_V2_CID,
        "holdout_execution": cid_for_dag_json(
            {"policy": "synthetic-holdout-execution"}
        ),
        "independent_authorship": cid_for_dag_json(
            {"attestation": "synthetic-authorship"}
        ),
        "independent_review": cid_for_dag_json(
            {"attestation": "synthetic-review"}
        ),
        "semantic": semantic_protocol_cid,
    }
    body = {
        "schema": REPLACEMENT_HOLDOUT_SEAL_SCHEMA,
        "sealed_manifest_cid": cid_for_bytes(
            b"opaque synthetic replacement manifest"
        ),
        "case_count": 4,
        "strata_counts": {"logic": 2, "safety": 2},
        "protocol_cids": protocols,
    }
    body["access_ledger_authority_cid"] = (
        replacement_holdout_ledger_authority_cid(
            body["sealed_manifest_cid"],  # type: ignore[arg-type]
            "/synthetic-independent-custody/replacement-access.jsonl",
        )
    )
    return ReplacementHoldoutSeal(
        schema=REPLACEMENT_HOLDOUT_SEAL_SCHEMA,
        sealed_manifest_cid=body["sealed_manifest_cid"],  # type: ignore[arg-type]
        case_count=4,
        strata_counts=body["strata_counts"],  # type: ignore[arg-type]
        protocol_cids=protocols,
        access_ledger_authority_cid=body[
            "access_ledger_authority_cid"
        ],  # type: ignore[arg-type]
        seal_contract_cid=cid_for_dag_json(body),
    )


def _valid_public_inputs() -> dict[str, object]:
    semantic = _semantic_calibration()
    matrix = _partial_matrix(str(semantic["artifact_cid"]))
    seal = _replacement_seal()
    source = g230.G230SourceFreezeReceipt(
        schema=g230.G230_SOURCE_FREEZE_SCHEMA,
        source_commit=SOURCE_COMMIT,
        source_tree_cid=cid_for_dag_json(
            {"source_commit": SOURCE_COMMIT, "synthetic_test_only": True}
        ),
        detached_head=True,
        worktree_clean=True,
        submodules_clean=True,
    )
    identities = g230.G230ExecutionIdentities(
        schema=g230.G230_EXECUTION_IDENTITIES_SCHEMA,
        source_commit=SOURCE_COMMIT,
        source_freeze_receipt_cid=source.receipt_cid,  # type: ignore[arg-type]
        legacy_environment_sha256=ENVIRONMENT_SHA256,
        identity_cids={
            key: cid_for_dag_json(
                {"identity": key, "synthetic_test_only": True}
            )
            for key in g230.G230_IDENTITY_KEYS
        },
        bound_artifact_cids={
            "semantic_calibration": semantic["artifact_cid"],
            "causal_receipt_matrix": matrix.matrix_cid,
            "replacement_holdout_seal": seal.seal_contract_cid,
        },  # type: ignore[arg-type]
        frozen=True,
    )
    # These deliberately look persuasive but have no source recomputation.
    # G230 must ignore them instead of converting their CIDs into authority.
    self_asserted_gates = {
        gate_id: {
            "gate_id": gate_id,
            "passed": True,
            "complete": True,
            "value": 1_000_000,
            "receipt_cid": cid_for_dag_json(
                {"gate_id": gate_id, "self_asserted": True}
            ),
        }
        for gate_id in g230.G230_GATE_IDS
    }
    return {
        "semantic_calibration_artifact": semantic,
        "causal_receipt_matrix": matrix,
        "replacement_holdout_seal": seal,
        "source_freeze_receipt": source,
        "execution_identities": identities,
        "gate_receipts": self_asserted_gates,
        "candidate_variant_ids": CANDIDATES,
    }


def _evaluate(inputs: dict[str, object]) -> g230.G230AuthorizationResult:
    return g230.evaluate_revised_pilot_authorization(
        **inputs  # type: ignore[arg-type]
    )


def test_matrix_uses_authoritative_g210_manifest_and_profile_contracts() -> None:
    semantic = _semantic_calibration()
    matrix = _partial_matrix(str(semantic["artifact_cid"]))
    restored = g230.G210ReceiptMatrix.from_dict(matrix.to_dict())

    assert restored.to_dict() == matrix.to_dict()
    assert all(
        isinstance(item, CausalRescueManifestV2)
        for item in restored.rescue_manifests
    )
    assert all(
        isinstance(item, CausalExecutionProfileV2)
        for item in restored.execution_profiles
    )
    assert restored.complete is False
    assert restored.validation_issues == (
        "incomplete_pilot_development_receipt_cartesian",
    )


def test_matrix_rejects_opaque_cid_only_aggregate_assertions() -> None:
    semantic = _semantic_calibration()
    matrix = _partial_matrix(str(semantic["artifact_cid"]))

    with pytest.raises(
        g230.RevisedPilotAuthorizationError,
        match="does not replay",
    ):
        g230.G210ReceiptMatrix(
            semantic_calibration_artifact_cid=(
                matrix.semantic_calibration_artifact_cid
            ),
            rescue_manifests=matrix.rescue_manifests,
            execution_profiles=matrix.execution_profiles,
            causal_aggregates=(
                {
                    "aggregate_cid": cid_for_dag_json(
                        {"self_asserted": True}
                    )
                },
            ),
        )


def test_matrix_deeply_freezes_validated_aggregate_receipts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    semantic = _semantic_calibration()
    manifests = tuple(
        sorted(
            (
                _rescue_manifest(Split.PILOT),
                _rescue_manifest(Split.DEVELOPMENT),
            ),
            key=lambda item: next(
                case.split.value for case in item.cases
            ),
        )
    )
    aggregate = {
        "run_id": "synthetic-freeze-check",
        "case_ids": ["pilot-rescue"],
        "case_receipts": [
            {
                "case_id": "pilot-rescue",
                "source_cid": manifests[1].cases[0].source_cid,
                "variant_id": "A0",
                "compiler_reference_state": "absent",
                "protocol_cid": CAUSAL_PROOF_PROTOCOL_V2_CID,
                "variant_profile_cid": (
                    CAUSAL_PROOF_VARIANT_PROFILE_V2_CID
                ),
                "case_result": {
                    "split": "pilot",
                    "variant_id": "A0",
                    "cache_mode": "cold",
                    "case_manifest_sha256": (
                        manifests[1].case_manifest_sha256
                    ),
                    "environment_sha256": ENVIRONMENT_SHA256,
                },
                "selection_receipt": {
                    "compiler_reference": {
                        "state": "absent",
                        "candidate_cid": None,
                        "artifact_cid": None,
                        "kernel_checked": False,
                    },
                    "optional_candidates": [],
                },
            }
        ],
    }
    monkeypatch.setattr(
        g230,
        "validate_causal_rescue_aggregate",
        lambda value: deepcopy(value),
    )
    matrix = g230.G210ReceiptMatrix(
        semantic_calibration_artifact_cid=str(semantic["artifact_cid"]),
        rescue_manifests=manifests,
        execution_profiles=tuple(
            sorted(
                (
                    _profile(item, str(semantic["artifact_cid"]))
                    for item in manifests
                ),
                key=lambda item: item.rescue_manifest_cid,
            )
        ),
        causal_aggregates=(aggregate,),
    )
    matrix_cid = matrix.matrix_cid
    frozen = matrix.causal_aggregates[0]
    case_ids = frozen["case_ids"]
    case_receipts = frozen["case_receipts"]
    assert isinstance(case_ids, tuple)
    assert isinstance(case_receipts, tuple)
    with pytest.raises(TypeError):
        case_ids[0] = "substituted"  # type: ignore[index]
    with pytest.raises(TypeError):
        case_receipts[0]["case_result"]["split"] = "development"  # type: ignore[index]
    assert matrix.matrix_cid == matrix_cid
    assert matrix.to_dict()["causal_aggregates"][0] == aggregate


def test_matrix_rejects_tampered_authoritative_manifest() -> None:
    semantic = _semantic_calibration()
    value = deepcopy(
        _partial_matrix(str(semantic["artifact_cid"])).to_dict()
    )
    value["rescue_manifests"][0]["cases"][0][
        "selected_before_optional_outcomes"
    ] = False

    with pytest.raises(ValueError):
        g230.G210ReceiptMatrix.from_dict(value)


def test_self_asserted_passing_gates_cannot_mint_authorization() -> None:
    result = _evaluate(_valid_public_inputs())

    assert result.decision.passed is False
    assert result.decision.selected_candidate_ids == ()
    assert result.decision.holdout_authorized is False
    assert result.authorization is None
    assert result.authorization_cid is None
    assert (
        "source_recomputed_gate_validator_unavailable"
        in result.decision.failures
    )
    assert (
        "semantic_source_revalidation_capability_unavailable"
        in result.decision.failures
    )
    assert "unvalidated_gate_receipts_ignored" in result.decision.failures
    assert all(
        value is None
        for value in result.decision.gate_receipt_cids.values()
    )


def test_module_exposes_no_positive_authorization_builder() -> None:
    assert not hasattr(g230, "_build_authorization")
    assert not hasattr(g230, "G230GateReceipt")
    assert not hasattr(g230, "G210RescueManifest")
    assert not hasattr(g230, "G230ReplacementHoldoutAuthorization")


@pytest.mark.parametrize(
    ("field", "failure"),
    [
        ("semantic_calibration_artifact", "invalid_g200_semantic_calibration"),
        ("causal_receipt_matrix", "invalid_g210_causal_receipt_matrix"),
        ("replacement_holdout_seal", "invalid_replacement_holdout_seal"),
        ("source_freeze_receipt", "invalid_source_freeze"),
        ("execution_identities", "invalid_execution_identities"),
    ],
)
def test_missing_dependency_is_empty_and_unauthorized(
    field: str,
    failure: str,
) -> None:
    inputs = _valid_public_inputs()
    inputs[field] = None

    result = _evaluate(inputs)

    assert failure in result.decision.failures
    assert result.decision.selected_candidate_ids == ()
    assert result.authorization_cid is None


def test_incomplete_matrix_reports_derived_missing_receipts() -> None:
    result = _evaluate(_valid_public_inputs())

    assert "g210_receipt_matrix_incomplete" in result.decision.failures
    assert (
        "g210:incomplete_pilot_development_receipt_cartesian"
        in result.decision.failures
    )


def test_wrong_replacement_protocol_fails_closed() -> None:
    inputs = _valid_public_inputs()
    inputs["replacement_holdout_seal"] = _replacement_seal(
        semantic_protocol_cid=cid_for_dag_json(
            {"protocol": "wrong-synthetic-semantic"}
        )
    )

    result = _evaluate(inputs)

    assert "replacement_seal_protocol_mismatch" in result.decision.failures
    assert result.authorization is None


def test_dirty_source_fails_closed() -> None:
    inputs = _valid_public_inputs()
    source = inputs["source_freeze_receipt"]
    assert isinstance(source, g230.G230SourceFreezeReceipt)
    inputs["source_freeze_receipt"] = g230.G230SourceFreezeReceipt(
        schema=source.schema,
        source_commit=source.source_commit,
        source_tree_cid=source.source_tree_cid,
        detached_head=True,
        worktree_clean=False,
        submodules_clean=True,
    )

    result = _evaluate(inputs)

    assert "source_not_detached_clean" in result.decision.failures
    assert result.authorization_cid is None


def test_environment_identity_mismatch_fails_closed() -> None:
    inputs = _valid_public_inputs()
    old = inputs["execution_identities"]
    assert isinstance(old, g230.G230ExecutionIdentities)
    inputs["execution_identities"] = g230.G230ExecutionIdentities(
        schema=old.schema,
        source_commit=old.source_commit,
        source_freeze_receipt_cid=old.source_freeze_receipt_cid,
        legacy_environment_sha256="e" * 64,
        identity_cids=old.identity_cids,
        bound_artifact_cids=old.bound_artifact_cids,
        frozen=True,
    )

    result = _evaluate(inputs)

    assert "execution_environment_mismatch" in result.decision.failures
    assert result.authorization is None


@pytest.mark.parametrize(
    "candidate_ids",
    [(), ("A0",), ("S1",), ("A2", "A2"), ("A1", "A2", "A3", "A4", "A5")],
)
def test_invalid_shortlist_never_authorizes(
    candidate_ids: tuple[str, ...],
) -> None:
    inputs = _valid_public_inputs()
    inputs["candidate_variant_ids"] = candidate_ids

    result = _evaluate(inputs)

    assert "invalid_shortlist" in result.decision.failures
    assert result.decision.selected_candidate_ids == ()
    assert result.authorization_cid is None


def test_negative_decision_is_deterministic() -> None:
    inputs = _valid_public_inputs()

    first = _evaluate(inputs)
    second = _evaluate(inputs)

    assert first.to_dict() == second.to_dict()
    assert first.decision.artifact_cid == second.decision.artifact_cid
    assert first.authorization_cid is None
