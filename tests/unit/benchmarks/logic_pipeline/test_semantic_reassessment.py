"""Independent, source-bound semantic reassessment evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

import pytest

from benchmarks.logic_pipeline import frontend_report
from benchmarks.logic_pipeline import semantic_reassessment as semantic
from benchmarks.logic_pipeline.cases import (
    FROZEN_CORPUS_MANIFEST_SHA256,
    BenchmarkCase,
    ExpectedClass,
    load_unsealed_pilot_development,
)
from benchmarks.logic_pipeline.contracts import (
    DEFAULT_PROTOCOL_SHA256,
    NATIVE_KERNEL_RECEIPT_SCHEMA,
    STAGE_PROVENANCE_SCHEMA,
    CacheMode,
    CaseResultRecord,
    FailureCode,
    ResourceLane,
    Split,
    StageName,
    StageProvenance,
    StageRecord,
    StageStatus,
    TelemetryRecord,
    canonical_json,
)
from benchmarks.logic_pipeline.reassessment_namespace import (
    ReassessmentRunLayout,
)
from benchmarks.logic_pipeline.semantic_reassessment import (
    EXPECTED_SEMANTIC_COORDINATE_COUNT,
    SemanticReassessmentError,
    build_semantic_reassessment,
    evaluate_frontend_case_results,
    validate_semantic_reassessment,
)
from benchmarks.logic_pipeline.variants import VARIANT_REGISTRY


RUN_ID = "semantic-reassessment-test"
ENVIRONMENT_SHA256 = "e" * 64
MATRIX_SHA256 = "a" * 64
MATRIX_BINDING = {
    "path": "results/matrix-execution-v2.json",
    "bytes_sha256": "b" * 64,
    "artifact_sha256": MATRIX_SHA256,
}
_LANES = {
    StageName.COMPILER: ResourceLane.CPU,
    StageName.SPACY: ResourceLane.CPU,
    StageName.SYMAI: ResourceLane.MODEL,
    StageName.HAMMER: ResourceLane.SOLVER,
    StageName.LEANSTRAL: ResourceLane.MODEL,
    StageName.KERNEL: ResourceLane.KERNEL,
}


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _source_input_sha256(case: BenchmarkCase) -> str:
    return _sha({"text": case.source_text})


def _frontend_capabilities() -> dict[str, object]:
    return {
        key: {"status": "available", "reason": ""}
        for key in frontend_report.CAPABILITY_KEYS
    }


def _semantic_terms(case: BenchmarkCase) -> tuple[str, ...]:
    return (*case.required_predicates, *case.required_entities)


def _kernel_rejection_receipt(
    case: BenchmarkCase,
    variant_id: str,
    cache_mode: CacheMode,
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema": NATIVE_KERNEL_RECEIPT_SCHEMA,
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "run_id": RUN_ID,
        "case_id": case.case_id,
        "case_manifest_sha256": FROZEN_CORPUS_MANIFEST_SHA256,
        "variant_id": variant_id,
        "split": case.split.value,
        "cache_mode": cache_mode.value,
        "input_sha256": _source_input_sha256(case),
        "environment_sha256": ENVIRONMENT_SHA256,
        "independent": True,
        "accepted": False,
        "active_process_count": 0,
        "reason": "semantic_reassessment_fixture_not_verified",
    }
    return {**body, "receipt_sha256": _sha(body)}


def _stage_payload(
    stage: StageName,
    case: BenchmarkCase,
    *,
    suppress_symai: bool,
    wrong_symai: bool,
) -> Mapping[str, object]:
    expected_ir = dict(case.expected_ir)
    if stage is StageName.COMPILER:
        return {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark.compiler-output.v1"
            ),
            "modal_ir": expected_ir,
            "modal_ir_sha256": _sha(expected_ir),
        }
    if stage is StageName.SPACY:
        return {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark.spacy-evidence.v1"
            ),
            "modal_ir": expected_ir,
            "tokens": [
                {"text": term, "lemma": term, "lower": term}
                for term in _semantic_terms(case)
            ],
            "entities": [
                {"text": entity} for entity in case.required_entities
            ],
            "semantic_roles": [
                {"predicate": predicate}
                for predicate in case.required_predicates
            ],
            "modal_cues": [{"family": expected_ir["logic"]}],
        }
    if stage is StageName.SYMAI and suppress_symai:
        return {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark.policy-decision.v1"
            ),
            "stage": "symai",
            "invoked": False,
            "reason": "frontend_ambiguity_gate_closed",
            "invocation_index": 2,
        }
    if stage is StageName.SYMAI:
        candidate = (
            {"logic": "fol", "target": "wrong_target"}
            if wrong_symai
            else expected_ir
        )
        return {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark.symai-evidence.v1"
            ),
            "candidate_ir": candidate,
            "candidate_ir_sha256": _sha(candidate),
            "normalized_predicates": (
                [] if wrong_symai else list(case.required_predicates)
            ),
            "entities": [] if wrong_symai else list(case.required_entities),
            "ambiguity_flags": (
                ["semantic_ambiguity"]
                if case.expected_class is ExpectedClass.AMBIGUOUS
                else []
            ),
            "validation_errors": (
                ["unsupported_construct"]
                if case.expected_class is ExpectedClass.UNSUPPORTED
                else []
            ),
        }
    if stage is StageName.HAMMER:
        return {"proof_candidate": None, "reconstruction": None}
    if stage is StageName.LEANSTRAL:
        return {"draft": {"proof": "by assumption"}, "repair_attempts": 0}
    return {"accepted": False}


def _case_result(
    case: BenchmarkCase,
    variant_id: str,
    cache_mode: CacheMode,
    *,
    wrong_symai: bool = False,
    unavailable: bool = False,
    failed: bool = False,
    omit_graph_invoked: bool = False,
) -> CaseResultRecord:
    definition = VARIANT_REGISTRY[variant_id]
    route = definition.stages[:1] if unavailable or failed else definition.stages
    suppress_symai = (
        definition.symai_policy.value == "ambiguity_gated"
        and case.expected_class is not ExpectedClass.AMBIGUOUS
    )
    stages: list[StageRecord] = []
    for stage_name in route:
        terminal = not stages and (unavailable or failed)
        graph_invoked = not (
            stage_name is StageName.SYMAI and suppress_symai
        )
        effective_identity: dict[str, object] = {
            "component": stage_name.value,
        }
        if not omit_graph_invoked:
            effective_identity["graph_invoked"] = graph_invoked
        stages.append(
            StageRecord.create(
                protocol_sha256=DEFAULT_PROTOCOL_SHA256,
                run_id=RUN_ID,
                case_id=case.case_id,
                case_manifest_sha256=FROZEN_CORPUS_MANIFEST_SHA256,
                variant_id=variant_id,
                split=case.split,
                cache_mode=cache_mode,
                stage=stage_name,
                adapter_version="1",
                status=(
                    StageStatus.UNAVAILABLE
                    if unavailable and terminal
                    else StageStatus.FAILED
                    if failed and terminal
                    else StageStatus.SUCCESS
                ),
                provenance=StageProvenance(
                    schema=STAGE_PROVENANCE_SCHEMA,
                    adapter_id=f"{stage_name.value}-adapter",
                    adapter_version="1",
                    source=("semantic-reassessment-test",),
                    requested_identity={"component": stage_name.value},
                    effective_identity=effective_identity,
                    input_sha256=_source_input_sha256(case),
                    environment_sha256=ENVIRONMENT_SHA256,
                    upstream_stage_digests=tuple(
                        stage.digest for stage in stages
                    ),
                ),
                telemetry=TelemetryRecord(
                    wall_time_ms=2.0,
                    cpu_time_ms=1.0,
                    peak_memory_bytes=256,
                    input_items=1,
                    output_items=0 if terminal else 1,
                    model_calls=int(
                        not terminal
                        and graph_invoked
                        and stage_name
                        in {StageName.SYMAI, StageName.LEANSTRAL}
                    ),
                    resource_lane=_LANES[stage_name],
                ),
                data=(
                    {}
                    if terminal
                    else _kernel_rejection_receipt(
                        case,
                        variant_id,
                        cache_mode,
                    )
                    if (
                        stage_name is StageName.KERNEL
                        and not omit_graph_invoked
                    )
                    else _stage_payload(
                        stage_name,
                        case,
                        suppress_symai=suppress_symai,
                        wrong_symai=wrong_symai,
                    )
                ),
                failure_code=(
                    FailureCode.CAPABILITY_UNAVAILABLE
                    if unavailable and terminal
                    else FailureCode.CANONICAL_IR_REJECTION
                    if failed and terminal
                    else None
                ),
                failure_detail=(
                    "requested compiler capability unavailable"
                    if unavailable and terminal
                    else "compiler rejected semantic input"
                    if failed and terminal
                    else None
                ),
            )
        )
    return CaseResultRecord.from_stages(stages)


@pytest.fixture(scope="module")
def cases() -> tuple[BenchmarkCase, ...]:
    _manifest, values = load_unsealed_pilot_development()
    return values


@pytest.fixture(scope="module")
def results(cases: tuple[BenchmarkCase, ...]) -> tuple[CaseResultRecord, ...]:
    return tuple(
        _case_result(case, variant_id, cache_mode)
        for split in (Split.PILOT, Split.DEVELOPMENT)
        for cache_mode in (CacheMode.COLD, CacheMode.WARM)
        for variant_id in frontend_report.FRONTEND_VARIANT_IDS
        for case in cases
        if case.split is split
    )


def _replace(
    results: tuple[CaseResultRecord, ...],
    replacement: CaseResultRecord,
) -> tuple[CaseResultRecord, ...]:
    coordinate = (
        replacement.split,
        replacement.cache_mode,
        replacement.variant_id,
        replacement.case_id,
    )
    return tuple(
        replacement
        if (
            result.split,
            result.cache_mode,
            result.variant_id,
            result.case_id,
        )
        == coordinate
        else result
        for result in results
    )


def _evaluate(results: tuple[CaseResultRecord, ...]):
    return evaluate_frontend_case_results(
        run_id=RUN_ID,
        capabilities=_frontend_capabilities(),
        case_results=results,
        matrix_artifact_sha256=MATRIX_SHA256,
    )


def test_builds_complete_source_bound_receipts_with_gated_zero_calls(
    results: tuple[CaseResultRecord, ...],
) -> None:
    evidence = _evaluate(results)

    assert len(evidence.receipts) == EXPECTED_SEMANTIC_COORDINATE_COUNT
    assert len(evidence.observations) == EXPECTED_SEMANTIC_COORDINATE_COUNT
    assert evidence.report["execution_mode"] == "measured"
    assert all(
        receipt["matrix_artifact_sha256"] == MATRIX_SHA256
        and receipt["evaluation_boundary"][
            "validator_invoked_adapter_or_model"
        ]
        is False
        and receipt["holdout_accessed"] is False
        for receipt in evidence.receipts
    )

    coordinate = ("pilot", "cold", "A4", "pilot-p01")
    observation = next(
        row
        for row in evidence.observations
        if (
            row["split"],
            row["cache_mode"],
            row["variant_id"],
            row["case_id"],
        )
        == coordinate
    )
    receipt = next(
        row
        for row in evidence.receipts
        if tuple(row["coordinate"][key] for key in (
            "split",
            "cache_mode",
            "variant_id",
            "case_id",
        ))
        == coordinate
    )
    assert observation["symai_invoked"] is False
    assert observation["symai_model_calls"] == 0
    assert receipt["semantic_source"]["selected_stage"] == "spacy"
    symai_binding = next(
        binding
        for binding in receipt["front_end_stage_bindings"]
        if binding["stage"] == "symai"
    )
    assert symai_binding["graph_invoked"] is False


def test_semantic_observations_include_symai_setup_cost_once(
    results: tuple[CaseResultRecord, ...],
    monkeypatch,
) -> None:
    setup = TelemetryRecord(
        wall_time_ms=11.0,
        model_calls=2,
        cache_misses=1,
        resource_lane=ResourceLane.MODEL,
    )

    def setup_for(stage: StageRecord) -> TelemetryRecord | None:
        return (
            setup
            if stage.stage is StageName.SYMAI
            and stage.cache_mode is CacheMode.WARM
            and stage.provenance.effective_identity.get("graph_invoked")
            is True
            else None
        )

    monkeypatch.setattr(
        semantic,
        "extract_symai_cache_setup_telemetry",
        setup_for,
    )
    monkeypatch.setattr(
        frontend_report,
        "extract_symai_cache_setup_telemetry",
        setup_for,
    )
    evidence = _evaluate(results)
    warm = next(
        row
        for row in evidence.observations
        if (
            row["split"],
            row["cache_mode"],
            row["variant_id"],
            row["case_id"],
        )
        == ("pilot", "warm", "A5", "pilot-p01")
    )
    warm_result = CaseResultRecord.from_dict(warm["case_result"])
    assert warm["symai_model_calls"] == 3
    assert warm["model_calls"] == (
        sum(
            stage.telemetry.model_calls
            for stage in warm_result.stages
        )
        + 2
    )
    assert warm["total_wall_time_ms"] == (
        sum(
            stage.telemetry.wall_time_ms
            for stage in warm_result.stages
        )
        + 11.0
    )
    cold = next(
        row
        for row in evidence.observations
        if (
            row["split"],
            row["cache_mode"],
            row["variant_id"],
            row["case_id"],
        )
        == ("pilot", "cold", "A5", "pilot-p01")
    )
    cold_result = CaseResultRecord.from_dict(cold["case_result"])
    assert cold["model_calls"] == sum(
        stage.telemetry.model_calls for stage in cold_result.stages
    )


def test_distinguishes_incorrect_semantics_from_capability_missingness(
    cases: tuple[BenchmarkCase, ...],
    results: tuple[CaseResultRecord, ...],
) -> None:
    by_id = {case.case_id: case for case in cases}
    changed = _replace(
        results,
        _case_result(
            by_id["pilot-p01"],
            "A5",
            CacheMode.COLD,
            wrong_symai=True,
        ),
    )
    changed = _replace(
        changed,
        _case_result(
            by_id["development-d01"],
            "A1",
            CacheMode.WARM,
            unavailable=True,
        ),
    )

    evidence = _evaluate(changed)
    by_coordinate = {
        tuple(receipt["coordinate"][key] for key in (
            "split",
            "cache_mode",
            "variant_id",
            "case_id",
        )): receipt
        for receipt in evidence.receipts
    }
    incorrect = by_coordinate[
        ("pilot", "cold", "A5", "pilot-p01")
    ]
    missing = by_coordinate[
        ("development", "warm", "A1", "development-d01")
    ]
    assert incorrect["evaluation"]["status"] == "semantically_incorrect"
    assert incorrect["evaluation"]["normalized_ir_exact_match"] is False
    assert incorrect["evaluation"]["structured_coverage"][
        "missing_predicates"
    ]
    assert missing["evaluation"]["status"] == "unavailable"
    assert missing["evaluation"]["structured_coverage"] is None
    assert missing["evaluation"]["missing_reason"]
    assert missing["receipt_sha256"]


def test_rejects_duplicate_incomplete_unbound_and_unrepresentable_inputs(
    cases: tuple[BenchmarkCase, ...],
    results: tuple[CaseResultRecord, ...],
) -> None:
    with pytest.raises(
        SemanticReassessmentError, match="duplicate coordinates"
    ):
        _evaluate((*results, results[0]))
    with pytest.raises(
        SemanticReassessmentError, match="complete 240-coordinate"
    ):
        _evaluate(results[:-1])

    first = cases[0]
    no_invocation_receipt = _replace(
        results,
        _case_result(
            first,
            "A0",
            CacheMode.COLD,
            omit_graph_invoked=True,
        ),
    )
    with pytest.raises(
        SemanticReassessmentError, match="explicit graph_invoked"
    ):
        _evaluate(no_invocation_receipt)

    rejected_without_semantics = _replace(
        results,
        _case_result(
            first,
            "A0",
            CacheMode.COLD,
            failed=True,
        ),
    )
    with pytest.raises(
        SemanticReassessmentError,
        match="cannot truthfully represent stage-level semantic missingness",
    ):
        _evaluate(rejected_without_semantics)


def test_persists_write_once_index_and_detects_receipt_tampering(
    tmp_path: Path,
    results: tuple[CaseResultRecord, ...],
) -> None:
    benchmark_root = tmp_path / "benchmark-runs"
    index = build_semantic_reassessment(
        run_id=RUN_ID,
        capabilities=_frontend_capabilities(),
        case_results=results,
        matrix_binding=MATRIX_BINDING,
        repository_root=tmp_path,
        benchmark_root=benchmark_root,
    )
    layout = ReassessmentRunLayout.for_run(
        RUN_ID, benchmark_root=benchmark_root
    )

    assert index["scope"]["coordinate_count"] == 240
    assert len(index["receipts"]) == 240
    assert layout.frontend_report.is_file()
    assert layout.frontend_receipt_index.is_file()
    assert layout.frontend_receipt_directory.is_dir()
    assert all(
        str(ref["path"]).startswith("receipts/semantic-validation/")
        for ref in index["receipts"]
    )
    assert str(tmp_path) not in canonical_json(index)
    assert validate_semantic_reassessment(
        run_id=RUN_ID,
        capabilities=_frontend_capabilities(),
        case_results=results,
        matrix_binding=MATRIX_BINDING,
        repository_root=tmp_path,
        benchmark_root=benchmark_root,
    ) == index
    with pytest.raises(
        SemanticReassessmentError, match="already exists"
    ):
        build_semantic_reassessment(
            run_id=RUN_ID,
            capabilities=_frontend_capabilities(),
            case_results=results,
            matrix_binding=MATRIX_BINDING,
            repository_root=tmp_path,
            benchmark_root=benchmark_root,
        )

    receipt_directory = layout.frontend_receipt_directory
    real_receipt_directory = receipt_directory.with_name(
        "semantic-validation-real"
    )
    receipt_directory.rename(real_receipt_directory)
    receipt_directory.symlink_to(
        real_receipt_directory,
        target_is_directory=True,
    )
    with pytest.raises(
        SemanticReassessmentError, match="must not use a symlink"
    ):
        validate_semantic_reassessment(
            run_id=RUN_ID,
            capabilities=_frontend_capabilities(),
            case_results=results,
            matrix_binding=MATRIX_BINDING,
            repository_root=tmp_path,
            benchmark_root=benchmark_root,
        )
    receipt_directory.unlink()
    real_receipt_directory.rename(receipt_directory)

    first_ref = index["receipts"][0]
    receipt_path = layout.run_paths.run_root / str(first_ref["path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["holdout_accessed"] = True
    receipt_path.write_text(
        canonical_json(receipt) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        SemanticReassessmentError, match="receipt changed"
    ):
        validate_semantic_reassessment(
            run_id=RUN_ID,
            capabilities=_frontend_capabilities(),
            case_results=results,
            matrix_binding=MATRIX_BINDING,
            repository_root=tmp_path,
            benchmark_root=benchmark_root,
        )

    with pytest.raises(
        SemanticReassessmentError, match="published immutable evidence"
    ):
        build_semantic_reassessment(
            run_id="reassessment-v2",
            capabilities=_frontend_capabilities(),
            case_results=results,
            matrix_binding=MATRIX_BINDING,
            repository_root=tmp_path,
            benchmark_root=benchmark_root,
        )


def test_external_matrix_results_are_confined_to_the_matrix_namespace(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "source"
    repository.mkdir()
    result_root = tmp_path / "external-run" / "results"
    result_path = result_root / "matrix/pilot/cold/A0/pilot-p01.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text("{}\n", encoding="utf-8")
    index_path = result_root / "matrix-execution-v2.json"
    index_path.write_text("{}\n", encoding="utf-8")

    assert semantic._safe_matrix_result_path(
        repository=repository,
        index_path=index_path,
        relative_path="matrix/pilot/cold/A0/pilot-p01.json",
    ) == result_path

    real_matrix = result_root / "matrix-real"
    (result_root / "matrix").rename(real_matrix)
    (result_root / "matrix").symlink_to(real_matrix, target_is_directory=True)
    with pytest.raises(
        SemanticReassessmentError, match="must not use a symlink"
    ):
        semantic._safe_matrix_result_path(
            repository=repository,
            index_path=index_path,
            relative_path="matrix/pilot/cold/A0/pilot-p01.json",
        )


@pytest.mark.parametrize(
    "path",
    (
        "/tmp/matrix-execution-v2.json",
        "../results/matrix-execution-v2.json",
        "results/../matrix-execution-v2.json",
        r"results\matrix-execution-v2.json",
    ),
)
def test_rejects_nonportable_matrix_binding_paths(path: str) -> None:
    with pytest.raises(
        SemanticReassessmentError,
        match="canonical relative POSIX path",
    ):
        semantic._matrix_binding({**MATRIX_BINDING, "path": path})


def test_module_imports_only_the_unsealed_corpus_loader() -> None:
    import benchmarks.logic_pipeline.semantic_reassessment as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "load_unsealed_pilot_development" in source
    assert "load_reviewed_corpus" not in source
    assert "load_holdout" not in source
