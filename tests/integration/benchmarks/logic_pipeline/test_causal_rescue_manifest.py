from __future__ import annotations

import copy
from pathlib import Path

import pytest

from benchmarks.logic_pipeline.ablation import (
    AblationCase,
    build_semantic_ablation_plan,
)
from benchmarks.logic_pipeline.causal_ablation import (
    CAUSAL_REFERENCE_FAILURE_CONDITION_V2,
    CausalAblationError,
    CausalRescueCaseV2,
    CausalRescueManifestV2,
    build_causal_rescue_manifest_v2,
    execute_causal_proof_ablation_v2,
    revalidate_semantic_calibration_prerequisite_v2,
    validate_semantic_calibration_prerequisite_v2,
)
from benchmarks.logic_pipeline.content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
)
from benchmarks.logic_pipeline.contracts import (
    SEMANTIC_PROTOCOL_V2_CID,
    CacheMode,
    FailureCode,
    Split,
)
from benchmarks.logic_pipeline.runtime import (
    CausalKernelCheck,
    CausalProofCandidate,
    CausalProofGraphController,
)


def _plan():
    return build_semantic_ablation_plan(
        "causal-rescue-test",
        (
            AblationCase.create(
                "rescue-hammer",
                {"text": "Every archivist is careful. Ada is an archivist."},
                split=Split.PILOT,
            ),
            AblationCase.create(
                "rescue-leanstral",
                {"text": "Every reviewer is patient. Bea is a reviewer."},
                split=Split.PILOT,
            ),
        ),
        case_manifest_sha256="a" * 64,
        split=Split.PILOT,
        seed=19,
        variant_ids=("A0", "A2", "A9"),
        cache_modes=(CacheMode.COLD,),
        environment_sha256="b" * 64,
    )


def _case(
    case_id: str,
    source: str,
    component: str,
) -> CausalRescueCaseV2:
    return CausalRescueCaseV2(
        case_id=case_id,
        split=Split.PILOT,
        source_cid=cid_for_bytes(source.encode("utf-8")),
        obligation_id=f"{case_id}-obligation",
        proof_obligation={
            "kind": "theorem",
            "logic": "fol",
            "target": f"ReviewedTarget_{case_id.replace('-', '_')}",
        },
        optional_components=(component,),
        review_attestation_cid=cid_for_dag_json(
            {
                "schema": "synthetic-independent-review.v1",
                "case_id": case_id,
                "reviewed": True,
            }
        ),
    )


def _cases() -> tuple[CausalRescueCaseV2, ...]:
    return (
        _case(
            "rescue-hammer",
            "Every archivist is careful. Ada is an archivist.",
            "hammer",
        ),
        _case(
            "rescue-leanstral",
            "Every reviewer is patient. Bea is a reviewer.",
            "leanstral",
        ),
    )


def test_rescue_manifest_is_cid_bound_source_only_and_round_trips() -> None:
    manifest = build_causal_rescue_manifest_v2(_plan(), _cases())
    restored = CausalRescueManifestV2.from_dict(manifest.to_dict())

    assert restored == manifest
    assert restored.manifest_cid.startswith("b")
    assert restored.component_case_counts == {"hammer": 1, "leanstral": 1}
    assert restored.split_counts == {"pilot": 2, "development": 0}
    assert all(
        case.deterministic_reference_condition
        == CAUSAL_REFERENCE_FAILURE_CONDITION_V2
        for case in restored.cases
    )
    assert restored.cases[0].proof_context == {
        "obligation_id": "rescue-hammer-obligation",
        "proof_obligation": {
            "kind": "theorem",
            "logic": "fol",
            "target": "ReviewedTarget_rescue_hammer",
        },
    }
    wire = restored.to_dict()
    forbidden = {
        "expected_class",
        "expected_ir",
        "kernel_accepted",
        "kernel_outcome",
        "optional_component_outcome",
        "source_text",
    }

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value).union(
                *(keys(item) for item in value.values())
            )
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value), set())
        return set()

    assert not forbidden.intersection(keys(wire))


def test_rescue_manifest_rejects_source_rebinding() -> None:
    cases = list(_cases())
    cases[0] = _case(
        "rescue-hammer",
        "This is not the scheduled source.",
        "hammer",
    )

    with pytest.raises(CausalAblationError, match="differs from its source"):
        build_causal_rescue_manifest_v2(_plan(), cases)


def test_rescue_manifest_requires_both_optional_component_populations() -> None:
    only_hammer = tuple(
        _case(
            case.case_id,
            (
                "Every archivist is careful. Ada is an archivist."
                if case.case_id == "rescue-hammer"
                else "Every reviewer is patient. Bea is a reviewer."
            ),
            "hammer",
        )
        for case in _cases()
    )

    with pytest.raises(CausalAblationError, match="Hammer and Leanstral"):
        build_causal_rescue_manifest_v2(_plan(), only_hammer)


def test_rescue_case_cid_rejects_outcome_informed_flag_tampering() -> None:
    value = copy.deepcopy(_cases()[0].to_dict())
    value["selected_before_optional_outcomes"] = False

    with pytest.raises(CausalAblationError, match="selected before outcomes"):
        CausalRescueCaseV2.from_dict(value)


def test_rescue_manifest_cid_rejects_derived_count_tampering() -> None:
    value = copy.deepcopy(
        build_causal_rescue_manifest_v2(_plan(), _cases()).to_dict()
    )
    value["component_case_counts"]["hammer"] = 2

    with pytest.raises(CausalAblationError, match="derived fields"):
        CausalRescueManifestV2.from_dict(value)


def _one_case_plan(*, variants: tuple[str, ...] = ("A0", "A3")):
    return build_semantic_ablation_plan(
        "causal-executor-test",
        (
            AblationCase.create(
                "rescue-shared",
                {"text": "Every clerk is calm. Cora is a clerk."},
                split=Split.PILOT,
            ),
        ),
        case_manifest_sha256="c" * 64,
        split=Split.PILOT,
        seed=23,
        variant_ids=variants,
        cache_modes=(CacheMode.COLD,),
        environment_sha256="d" * 64,
    )


def _one_case_manifest(plan) -> CausalRescueManifestV2:
    return build_causal_rescue_manifest_v2(
        plan,
        (
            CausalRescueCaseV2(
                case_id="rescue-shared",
                split=Split.PILOT,
                source_cid=cid_for_bytes(
                    b"Every clerk is calm. Cora is a clerk."
                ),
                obligation_id="rescue-shared-obligation",
                proof_obligation={
                    "kind": "theorem",
                    "logic": "fol",
                    "target": "ReviewedTarget_rescue_shared",
                },
                optional_components=("hammer", "leanstral"),
                review_attestation_cid=cid_for_dag_json(
                    {
                        "schema": "synthetic-independent-review.v1",
                        "case_id": "rescue-shared",
                        "reviewed": True,
                    }
                ),
            ),
        ),
    )


def _passing_calibration() -> dict[str, object]:
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
            "semantic_quality_millionths": 800_000,
        },
        "absolute_quality_gate": {"passed": True},
        "holdout_authorized": False,
        "production_promotion_authorized": False,
        "synthetic_test_only": True,
    }
    return {**body, "artifact_cid": cid_for_dag_json(body)}


def _compiler_candidate(certificate: bytes = b"exact compiler proof"):
    return CausalProofCandidate(
        source="compiler",
        certificate=certificate,
        artifact_cid=cid_for_dag_json(
            {"schema": "synthetic-compiler-artifact.v1"}
        ),
    )


def _optional_maps(
    plan,
    *,
    hammer,
    leanstral,
):
    result = {}
    for job in plan.jobs:
        optional = {}
        if job.variant_id in {"A2", "A3"}:
            optional["hammer"] = hammer
        if job.variant_id == "A3":
            optional["leanstral"] = leanstral
        result[job.job_id] = optional
    return result


def _controller_factory(
    plan,
    *,
    accepted_certificates: set[bytes],
):
    def factory(job, _context):
        def check(candidate):
            accepted = candidate.certificate in accepted_certificates
            receipt = {
                "schema": "synthetic-native-kernel-receipt.v1",
                "run_id": plan.run_id,
                "case_id": job.case.case_id,
                "variant_id": job.variant_id,
                "independent": True,
                "accepted": accepted,
            }
            return CausalKernelCheck(
                candidate_cid=candidate.candidate_cid,
                accepted=accepted,
                receipt=receipt,
                failure_code=(
                    None if accepted else FailureCode.KERNEL_REJECTION
                ),
            )

        return CausalProofGraphController(
            kernel_checker=check,
            kernel_receipt_validator=lambda candidate, checked: (
                checked.candidate_cid == candidate.candidate_cid
                and checked.receipt["independent"] is True
            ),
        )

    return factory


def test_selection_only_batch_executor_is_disabled_before_optional_work(
    tmp_path: Path,
) -> None:
    plan = _one_case_plan(variants=("A0", "A3"))
    compiler = _compiler_candidate()
    calls = {"hammer": 0, "leanstral": 0}

    def hammer():
        calls["hammer"] += 1
        raise AssertionError("accepted compiler must suppress Hammer")

    def leanstral():
        calls["leanstral"] += 1
        raise AssertionError("accepted compiler must suppress Leanstral")

    root = tmp_path / "run"
    with pytest.raises(
        CausalAblationError,
        match="selection-only G210 batch execution is disabled",
    ):
        execute_causal_proof_ablation_v2(
            plan,
            _one_case_manifest(plan),
            {("rescue-shared", CacheMode.COLD): compiler},
            _optional_maps(
                plan, hammer=hammer, leanstral=leanstral
            ),
            _controller_factory(
                plan, accepted_certificates={b"exact compiler proof"}
            ),
            semantic_reviewed_cases=(),
            semantic_evidence_sources=(),
            output_root=root,
            resume=False,
        )

    assert calls == {"hammer": 0, "leanstral": 0}
    assert not root.exists()


def test_source_revalidation_rejects_missing_persisted_graphs(
) -> None:
    with pytest.raises(
        CausalAblationError,
        match="source evidence failed independent revalidation",
    ):
        revalidate_semantic_calibration_prerequisite_v2(
            reviewed_cases=(),
            evidence_sources=(),
        )


def test_incomplete_self_cid_g200_report_fails_shape_validation(
) -> None:
    calibration = _passing_calibration()
    calibration["absolute_quality_gate"]["passed"] = False
    body = {
        key: value
        for key, value in calibration.items()
        if key != "artifact_cid"
    }
    calibration["artifact_cid"] = cid_for_dag_json(body)
    with pytest.raises(CausalAblationError, match="fields changed"):
        validate_semantic_calibration_prerequisite_v2(calibration)
