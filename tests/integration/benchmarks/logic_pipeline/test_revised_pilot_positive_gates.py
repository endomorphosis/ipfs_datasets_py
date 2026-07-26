"""Source-safe synthetic tests for bounded positive-gate validator slices.

These tests construct their own runtime receipts and temporary persistence
roots.  They never load a benchmark fixture, corpus, manifest, or holdout.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from pathlib import Path

import pytest

from benchmarks.logic_pipeline import adapters, contracts, runtime, variants
from benchmarks.logic_pipeline import revised_pilot_authorization as g230
from benchmarks.logic_pipeline.causal_ablation import (
    CausalExecutionProfileV2,
    CausalRescueCaseV2,
    CausalRescueManifestV2,
)
from benchmarks.logic_pipeline.causal_runtime import (
    CompilerReferenceExposureV2,
    execute_causal_runtime_case_v2,
)
from benchmarks.logic_pipeline.content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
)
from benchmarks.logic_pipeline.contracts import Split
from benchmarks.logic_pipeline.metrics import (
    aggregate_causal_rescue_receipts,
)
from tests.integration.benchmarks.logic_pipeline.test_causal_runtime import (
    ENVIRONMENT_SHA256,
    MANIFEST_SHA256,
    PROOF_CONTEXT,
    SOURCE_TEXT,
    _SyntheticKernelSupervisor,
    _compiler_payload,
    _execute_compiler_path,
)
from tests.integration.benchmarks.logic_pipeline.test_causal_runtime_batch import (
    _persist as _persist_g211_batch,
)
from tests.integration.benchmarks.logic_pipeline._semantic_quality_support import (
    projection_payload,
    semantic_target,
)


COMPLETE_RUN_ID = "synthetic-g231-complete"


def _runtime_matrix(tmp_path) -> g230.G210RuntimeReceiptMatrixV2:
    evidence, _supervisor = _execute_compiler_path(tmp_path)
    rescue_case = CausalRescueCaseV2(
        case_id=evidence.case_result.case_id,
        split=Split.PILOT,
        source_cid=evidence.compiler_exposure.source_cid,
        obligation_id=str(PROOF_CONTEXT["obligation_id"]),
        proof_obligation=PROOF_CONTEXT["proof_obligation"],  # type: ignore[arg-type]
        optional_components=("hammer", "leanstral"),
        review_attestation_cid=cid_for_dag_json(
            {
                "schema": "synthetic-independent-review.v1",
                "case_id": evidence.case_result.case_id,
            }
        ),
    )
    manifest = CausalRescueManifestV2(
        plan_cid=cid_for_dag_json({"kind": "synthetic-g210-plan"}),
        source_manifest_cid=cid_for_dag_json(
            {"kind": "synthetic-g210-source-manifest"}
        ),
        case_manifest_sha256=MANIFEST_SHA256,
        cases=(rescue_case,),
    )
    calibration_cid = cid_for_dag_json(
        {"kind": "synthetic-source-recomputed-g200-calibration"}
    )
    profile = CausalExecutionProfileV2(
        plan_cid=manifest.plan_cid,
        source_manifest_cid=manifest.source_manifest_cid,
        rescue_manifest_cid=manifest.manifest_cid,
        semantic_calibration_artifact_cid=calibration_cid,
        compiler_reference_population_cid=cid_for_dag_json(
            {
                "kind": "synthetic-full-compiler-exposure-population",
                "exposure_cid": evidence.compiler_exposure.receipt_cid,
            }
        ),
        environment_sha256=ENVIRONMENT_SHA256,
    )
    persisted_evidence = evidence.to_dict()
    aggregate = aggregate_causal_rescue_receipts(
        (persisted_evidence["causal_case_receipt"],)
    )
    reduced = g230.G210ReceiptMatrix(
        semantic_calibration_artifact_cid=calibration_cid,
        rescue_manifests=(manifest,),
        execution_profiles=(profile,),
        causal_aggregates=(aggregate,),
    )
    return g230.G210RuntimeReceiptMatrixV2(
        receipt_matrix=reduced,
        runtime_evidence=(evidence,),
    )


def _compiler_record(
    payload: Mapping[str, object],
    *,
    case_id: str,
    source_text: str,
    split: contracts.Split,
    cache_mode: contracts.CacheMode,
    variant_id: str,
) -> contracts.StageRecord:
    target = semantic_target(case_id, source_text=source_text)
    semantic_payload, _projection = projection_payload(target, "compiler")
    combined_payload = {**payload, **semantic_payload}
    definition = variants.get_variant_definition(variant_id)
    request = adapters.StageRequest(
        run_id=COMPLETE_RUN_ID,
        case_id=case_id,
        case_manifest_sha256=MANIFEST_SHA256,
        variant_id=variant_id,
        split=split,
        cache_mode=cache_mode,
        input_data={"text": source_text},
        requested_identity=definition.requested_identity(
            contracts.StageName.COMPILER
        ),
        environment_sha256=ENVIRONMENT_SHA256,
        source=("synthetic-g231-efficacy-test",),
        semantic_protocol_cid=contracts.SEMANTIC_PROTOCOL_V2_CID,
    )
    adapter = adapters.StageAdapter(
        contracts.StageName.COMPILER,
        handler=lambda _request: adapters.StageOutput(
            data=combined_payload,
            effective_identity={
                **dict(
                    definition.requested_identity(
                        contracts.StageName.COMPILER
                    )
                ),
                "implementation": "synthetic-g231-compiler",
                "graph_invoked": True,
            },
        ),
        adapter_version="2",
    )
    return adapter.run(request)


def _semantic_result(
    payload: Mapping[str, object],
    exposure: CompilerReferenceExposureV2,
    *,
    case_id: str,
    source_text: str,
    split: contracts.Split,
    cache_mode: contracts.CacheMode,
    variant_id: str,
    symai_validation_errors: tuple[str, ...] = (),
) -> contracts.CaseResultRecord:
    if variant_id == "A0":
        return contracts.CaseResultRecord.from_stages(
            (exposure.compiler_record,)
        )
    compiler = _compiler_record(
        payload,
        case_id=case_id,
        source_text=source_text,
        split=split,
        cache_mode=cache_mode,
        variant_id=variant_id,
    )
    definition = variants.get_variant_definition(variant_id)
    target = semantic_target(case_id, source_text=source_text)
    request = adapters.StageRequest(
        run_id=COMPLETE_RUN_ID,
        case_id=case_id,
        case_manifest_sha256=MANIFEST_SHA256,
        variant_id=variant_id,
        split=split,
        cache_mode=cache_mode,
        input_data={"text": source_text},
        requested_identity=definition.requested_identity(
            contracts.StageName.SPACY
        ),
        environment_sha256=ENVIRONMENT_SHA256,
        upstream_stage_digests=(compiler.digest,),
        source=("synthetic-g231-efficacy-test",),
        semantic_protocol_cid=contracts.SEMANTIC_PROTOCOL_V2_CID,
    )
    spacy = adapters.StageAdapter(
        contracts.StageName.SPACY,
        handler=lambda _request: adapters.StageOutput(
            data=projection_payload(
                target,
                {
                    "full_model": "spacy_full_model",
                    "regex_legal": "spacy_regex_legal",
                    "blank_model": "spacy_blank_model",
                }[definition.spacy_mode.value],
            )[0],
            effective_identity={
                **dict(
                    definition.requested_identity(
                        contracts.StageName.SPACY
                    )
                ),
                "implementation": "synthetic-g231-spacy",
                "graph_invoked": True,
            },
        ),
        adapter_version="2",
    ).run(request)
    records = [compiler, spacy]
    if contracts.StageName.SYMAI in definition.stages:
        symai_request = adapters.StageRequest(
            run_id=COMPLETE_RUN_ID,
            case_id=case_id,
            case_manifest_sha256=MANIFEST_SHA256,
            variant_id=variant_id,
            split=split,
            cache_mode=cache_mode,
            input_data={"text": source_text},
            requested_identity=definition.requested_identity(
                contracts.StageName.SYMAI
            ),
            environment_sha256=ENVIRONMENT_SHA256,
            upstream_stage_digests=tuple(
                record.digest for record in records
            ),
            source=("synthetic-g231-efficacy-test",),
            semantic_protocol_cid=contracts.SEMANTIC_PROTOCOL_V2_CID,
        )
        symai_payload, _projection = projection_payload(
            target,
            "symai",
            validation_errors=symai_validation_errors,
        )
        context_body = {
            "schema": "synthetic-g231-semantic-context.v2",
            "source_cid": target.source_cid,
            "upstream_stage_cids": [
                cid_for_dag_json(_plain(record.to_dict()))
                for record in records
            ],
        }
        context_cid = cid_for_dag_json(context_body)
        symai_config = adapters.SymaiAdapterConfig(
            provider="synthetic_provider",
            model="synthetic-model",
            dry_run=False,
            semantic_protocol_cid=contracts.SEMANTIC_PROTOCOL_V2_CID,
        )
        namespace = adapters._symai_cache_namespace(symai_request)
        cache_key = adapters._symai_cache_key(
            symai_request,
            symai_config,
            namespace,
            {"context_cid": context_cid},
        )
        symai_payload = {
            **symai_payload,
            "backend_provenance": {
                "requested_provider": symai_config.provider,
                "effective_provider": symai_config.provider,
                "requested_model": symai_config.model,
                "effective_model": symai_config.model,
                "dry_run": symai_config.dry_run,
                "router_metadata": {},
            },
            "cache": {
                "namespace": namespace,
                "key": cache_key,
                "mode": cache_mode.value,
                "hit": cache_mode is contracts.CacheMode.WARM,
            },
            "semantic_context": {
                "schema": (
                    "ipfs-datasets.logic-pipeline-benchmark."
                    "semantic-context-binding.v2"
                ),
                "context_cid": context_cid,
                "source_cid": target.source_cid,
                "artifact_cids": [],
            },
        }
        symai = adapters.StageAdapter(
            contracts.StageName.SYMAI,
            handler=lambda _request: adapters.StageOutput(
                data=symai_payload,
                effective_identity={
                    **dict(
                        definition.requested_identity(
                            contracts.StageName.SYMAI
                        )
                    ),
                    "implementation": "synthetic-g231-symai",
                    "graph_invoked": True,
                    "requested_provider": symai_config.provider,
                    "effective_provider": symai_config.provider,
                    "requested_model": symai_config.model,
                    "effective_model": symai_config.model,
                    "dry_run": symai_config.dry_run,
                    "cache_namespace": namespace,
                    "cache_key": cache_key,
                    "semantic_context_cid": context_cid,
                },
            ),
            adapter_version="2",
        ).run(symai_request)
        records.append(symai)
    return contracts.CaseResultRecord.from_stages(tuple(records))


def _failed_optional_adapter(
    stage: contracts.StageName,
) -> adapters.StageAdapter:
    if stage is contracts.StageName.HAMMER:
        output = adapters.StageOutput(
            status=contracts.StageStatus.FAILED,
            failure_code=contracts.FailureCode.PREMISE_SELECTION_MISS,
            failure_detail="synthetic premise-selection miss",
        )
    else:
        output = adapters.StageOutput(
            data={"safe_failure_class": "timed_out"},
            status=contracts.StageStatus.FAILED,
            failure_code=(
                contracts.FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
            ),
            failure_detail="synthetic model timeout",
        )
    return adapters.StageAdapter(
        stage,
        handler=lambda _request: output,
    )


def _coordinate_evidence(
    tmp_path: Path,
    *,
    case_id: str,
    source_text: str,
    proof_context: Mapping[str, object],
    split: contracts.Split,
    cache_mode: contracts.CacheMode,
    variant_ids: tuple[str, ...] = g230.G210_VARIANT_IDS,
    compiler_note: str = "synthetic-g231",
    symai_validation_error_variant_ids: tuple[str, ...] = (),
) -> tuple[object, ...]:
    payload, certificate = _compiler_payload(
        source_text,
        dict(proof_context),
        include_candidate=True,
        non_ascii_note=compiler_note,
    )
    assert certificate is not None
    exposure = CompilerReferenceExposureV2.from_compiler_record(
        _compiler_record(
            payload,
            case_id=case_id,
            source_text=source_text,
            split=split,
            cache_mode=cache_mode,
            variant_id="A0",
        ),
        source_text=source_text,
    )
    evidence = []
    for variant_id in variant_ids:
        coordinate_root = (
            tmp_path
            / "complete-g231"
            / split.value
            / cache_mode.value
            / variant_id
        )
        coordinate_root.mkdir(parents=True)
        runner = runtime.NativeKernelRunner(
            "/synthetic/lean",
            ENVIRONMENT_SHA256,
            coordinate_root / "kernel-state",
        )
        supervisor = _SyntheticKernelSupervisor(
            coordinate_root,
            expected_proof=certificate,
            returncode=1,
        )
        runner._supervisor = supervisor
        route = {
            stage: _failed_optional_adapter(stage)
            for stage in variants.get_causal_proof_variant_profile(
                variant_id
            ).optional_order
        }
        route[contracts.StageName.KERNEL] = adapters.StageAdapter(
            contracts.StageName.KERNEL,
            handler=runner,
        )
        item = execute_causal_runtime_case_v2(
            _semantic_result(
                payload,
                exposure,
                case_id=case_id,
                source_text=source_text,
                split=split,
                cache_mode=cache_mode,
                variant_id=variant_id,
                symai_validation_errors=(
                    ("synthetic_contract_error",)
                    if variant_id
                    in set(symai_validation_error_variant_ids)
                    else ()
                ),
            ),
            source_text,
            proof_context,
            exposure,
            route,
        )
        assert item.case_result.status is contracts.OutcomeStatus.REJECTED
        evidence.append(item)
    return tuple(evidence)


def _complete_runtime_matrix(
    tmp_path: Path,
    *,
    symai_validation_error_coordinate: tuple[
        contracts.Split, contracts.CacheMode, str
    ]
    | None = None,
    symai_validation_error_coordinates: tuple[
        tuple[contracts.Split, contracts.CacheMode, str], ...
    ] = (),
) -> g230.G210RuntimeReceiptMatrixV2:
    calibration_cid = cid_for_dag_json(
        {"kind": "synthetic-source-recomputed-g200-calibration"}
    )
    manifests = []
    profiles = []
    all_evidence = []
    aggregates = []
    for split in (contracts.Split.PILOT, contracts.Split.DEVELOPMENT):
        case_id = f"synthetic-g231-{split.value}"
        source_text = SOURCE_TEXT
        proof_context = dict(PROOF_CONTEXT)
        split_evidence = []
        for cache_mode in (
            contracts.CacheMode.COLD,
            contracts.CacheMode.WARM,
        ):
            split_evidence.extend(
                _coordinate_evidence(
                    tmp_path,
                    case_id=case_id,
                    source_text=source_text,
                    proof_context=proof_context,
                    split=split,
                    cache_mode=cache_mode,
                    symai_validation_error_variant_ids=(
                        tuple(
                            coordinate[2]
                            for coordinate in (
                                (
                                    symai_validation_error_coordinate,
                                )
                                if symai_validation_error_coordinate
                                is not None
                                else ()
                            )
                            + symai_validation_error_coordinates
                            if coordinate[:2] == (split, cache_mode)
                        )
                    ),
                )
            )
        rescue_case = CausalRescueCaseV2(
            case_id=case_id,
            split=split,
            source_cid=cid_for_bytes(source_text.encode("utf-8")),
            obligation_id=str(proof_context["obligation_id"]),
            proof_obligation=proof_context["proof_obligation"],  # type: ignore[arg-type]
            optional_components=("hammer", "leanstral"),
            review_attestation_cid=cid_for_dag_json(
                {
                    "schema": "synthetic-independent-review.v1",
                    "case_id": case_id,
                }
            ),
        )
        manifest = CausalRescueManifestV2(
            plan_cid=cid_for_dag_json(
                {"kind": "synthetic-g231-plan", "split": split.value}
            ),
            source_manifest_cid=cid_for_dag_json(
                {
                    "kind": "synthetic-g231-source-manifest",
                    "split": split.value,
                }
            ),
            case_manifest_sha256=MANIFEST_SHA256,
            cases=(rescue_case,),
        )
        manifests.append(manifest)
        profiles.append(
            CausalExecutionProfileV2(
                plan_cid=manifest.plan_cid,
                source_manifest_cid=manifest.source_manifest_cid,
                rescue_manifest_cid=manifest.manifest_cid,
                semantic_calibration_artifact_cid=calibration_cid,
                compiler_reference_population_cid=cid_for_dag_json(
                    {
                        "kind": "synthetic-g231-compiler-population",
                        "split": split.value,
                        "exposure_cids": sorted(
                            {
                                item.compiler_exposure.receipt_cid
                                for item in split_evidence
                            }
                        ),
                    }
                ),
                environment_sha256=ENVIRONMENT_SHA256,
            )
        )
        all_evidence.extend(split_evidence)
        aggregates.extend(
            aggregate_causal_rescue_receipts(
                (item.to_dict()["causal_case_receipt"],)
            )
            for item in split_evidence
        )
    reduced = g230.G210ReceiptMatrix(
        semantic_calibration_artifact_cid=calibration_cid,
        rescue_manifests=tuple(
            sorted(manifests, key=lambda item: item.cases[0].split.value)
        ),
        execution_profiles=tuple(
            sorted(profiles, key=lambda item: item.rescue_manifest_cid)
        ),
        causal_aggregates=tuple(
            sorted(
                aggregates,
                key=lambda item: (
                    item["case_receipts"][0]["case_result"]["split"],
                    item["variant_id"],
                    item["case_receipts"][0]["case_result"]["cache_mode"],
                ),
            )
        ),
    )
    matrix = g230.G210RuntimeReceiptMatrixV2(
        receipt_matrix=reduced,
        runtime_evidence=tuple(all_evidence),
    )
    assert matrix.validation_issues == ()
    return matrix


@pytest.fixture(scope="module")
def complete_runtime_matrix(
    tmp_path_factory: pytest.TempPathFactory,
) -> g230.G210RuntimeReceiptMatrixV2:
    return _complete_runtime_matrix(
        tmp_path_factory.mktemp("complete-g231-efficacy")
    )


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return _plain(value.value)
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def test_runtime_matrix_replays_full_receipt_and_joins_reduced_aggregate(
    tmp_path,
) -> None:
    matrix = _runtime_matrix(tmp_path)

    assert matrix.complete is False
    assert "runtime_receipt_cartesian_incomplete" in matrix.validation_issues
    assert "runtime_reduced_receipt_join_mismatch" not in (
        matrix.validation_issues
    )
    assert "runtime_rescue_source_binding_mismatch" not in (
        matrix.validation_issues
    )
    assert (
        g230.G210RuntimeReceiptMatrixV2.from_dict(
            matrix.to_dict()
        ).runtime_matrix_cid
        == matrix.runtime_matrix_cid
    )


def test_runtime_matrix_rejects_rebased_full_evidence(tmp_path) -> None:
    matrix = _runtime_matrix(tmp_path)
    persisted = matrix.to_dict()
    runtime = persisted["runtime_evidence"]
    assert isinstance(runtime, list)
    runtime[0]["source_text_utf8"] = "substituted source"  # type: ignore[index]

    with pytest.raises(
        (g230.RevisedPilotAuthorizationError, ValueError),
        match="source|evidence",
    ):
        g230.G210RuntimeReceiptMatrixV2.from_dict(persisted)


def test_authoritative_builder_requires_both_persisted_splits(
    tmp_path,
) -> None:
    *_inputs, pilot_batch = _persist_g211_batch(tmp_path)

    with pytest.raises(
        g230.RevisedPilotAuthorizationError,
        match="pilot and development",
    ):
        g230.build_g210_runtime_receipt_matrix_v2(
            pilot_batch, pilot_batch
        )


def test_reliability_and_routing_are_recomputed_but_incomplete(
    tmp_path,
) -> None:
    matrix = _runtime_matrix(tmp_path)
    reliability = g230.build_g234_reliability_gate_v2(matrix, ("A1",))
    routing = g230.build_g234_routing_gate_v2(matrix, ("A1",))

    assert reliability["status"] == "incomplete"
    assert routing["status"] == "incomplete"
    assert reliability["evidence"]["source_recomputed"] is True
    assert routing["evidence"]["source_recomputed"] is True
    assert (
        g230.validate_g234_reliability_gate_v2(
            reliability, matrix
        )["receipt_cid"]
        == reliability["receipt_cid"]
    )
    assert (
        g230.validate_g234_routing_gate_v2(
            routing, matrix
        )["receipt_cid"]
        == routing["receipt_cid"]
    )

    tampered = _plain(reliability)
    tampered["evidence"]["terminal_receipt_count"] = 99  # type: ignore[index]
    with pytest.raises(
        g230.RevisedPilotAuthorizationError,
        match="source-recompute",
    ):
        g230.validate_g234_reliability_gate_v2(tampered, matrix)


def test_g234_reliability_and_routing_pass_complete_runtime_matrix(
    complete_runtime_matrix: g230.G210RuntimeReceiptMatrixV2,
) -> None:
    matrix = complete_runtime_matrix
    reliability = g230.build_g234_reliability_gate_v2(
        matrix, ("A12",)
    )
    routing = g230.build_g234_routing_gate_v2(matrix, ("A12",))

    assert reliability["schema"] == g230.G234_RUNTIME_GATE_RECEIPT_SCHEMA
    assert routing["schema"] == g230.G234_RUNTIME_GATE_RECEIPT_SCHEMA
    assert reliability["status"] == routing["status"] == "passed"
    assert reliability["complete"] is routing["complete"] is True
    assert reliability["passed"] is routing["passed"] is True
    assert reliability["failure_codes"] == routing["failure_codes"] == ()
    assert reliability["evidence"]["terminal_receipt_count"] == 8
    assert reliability["evidence"]["status_counts"]["rejected"] == 8
    assert routing["evidence"]["compiler_exposure_equal"] is True
    assert routing["evidence"]["fallback_or_substitution_count"] == 0
    assert (
        g230.validate_g234_reliability_gate_v2(
            reliability, matrix
        )["receipt_cid"]
        == reliability["receipt_cid"]
    )
    assert (
        g230.validate_g234_routing_gate_v2(
            routing, matrix
        )["receipt_cid"]
        == routing["receipt_cid"]
    )

    tampered = _plain(routing)
    tampered["evidence"]["compiler_exposure_equal"] = False  # type: ignore[index]
    with pytest.raises(
        g230.RevisedPilotAuthorizationError,
        match="source-recompute",
    ):
        g230.validate_g234_routing_gate_v2(tampered, matrix)


def test_receipt_replay_never_claims_detached_execution_replay(
    tmp_path,
) -> None:
    matrix = _runtime_matrix(tmp_path)
    replay = g230.build_g230_receipt_replay_assessment_v2(
        matrix, ("A1",)
    )

    assert replay["status"] == "incomplete"
    assert (
        replay["schema"]
        == g230.G230_RECEIPT_REPLAY_ASSESSMENT_SCHEMA
    )
    assert replay["passed"] is False
    assert (
        replay["evidence"]["detached_execution_replay_complete"]
        is False
    )
    assert "detached_execution_replay_unavailable" in (
        replay["failure_codes"]
    )
    assert (
        g230.validate_g230_receipt_replay_assessment_v2(
            replay, matrix
        )["receipt_cid"]
        == replay["receipt_cid"]
    )


def test_efficacy_gate_complete_measured_zero_passes_with_cid_pairs(
    complete_runtime_matrix: g230.G210RuntimeReceiptMatrixV2,
) -> None:
    matrix = complete_runtime_matrix
    gate = g230.build_g234_efficacy_gate_v2(
        matrix, ("A1", "A12")
    )

    assert matrix.complete is True
    assert gate["schema"] == g230.G234_RUNTIME_GATE_RECEIPT_SCHEMA
    assert gate["status"] == "passed"
    assert gate["complete"] is True
    assert gate["passed"] is True
    assert gate["failure_codes"] == ()
    assert gate["evidence"]["comparison_count"] == 8
    assert gate["evidence"]["scheduled_pair_count"] == 8
    assert gate["evidence"]["measured_pair_count"] == 8
    assert gate["evidence"]["missing_pair_count"] == 0
    assert gate["evidence"]["performance_threshold_applied"] is False
    comparisons = gate["evidence"]["comparisons"]
    assert {
        (
            comparison["candidate_variant_id"],
            comparison["split"],
            comparison["cache_mode"],
        )
        for comparison in comparisons
    } == {
        (candidate, split, cache)
        for candidate in ("A1", "A12")
        for split in g230.G210_SPLITS
        for cache in g230.G210_CACHE_MODES
    }
    assert all(
        comparison["net_verified_delta"] == 0.0
        and comparison["baseline_verified_count"] == 0
        and comparison["candidate_verified_count"] == 0
        for comparison in comparisons
    )
    runtime_cids = {
        item.receipt_cid for item in matrix.runtime_evidence
    }
    pair_cids = set()
    for comparison in comparisons:
        assert (
            comparison["schema"]
            == g230.G234_PAIRED_EFFICACY_COMPARISON_SCHEMA
        )
        for pair in comparison["pairs"]:
            assert pair["schema"] == g230.G234_PAIRED_EFFICACY_PAIR_SCHEMA
            pair_cids.add(pair["pair_cid"])
            assert pair["measured"] is True
            assert pair["baseline_value"] == 0
            assert pair["candidate_value"] == 0
            assert pair["baseline_runtime_receipt_cid"] in runtime_cids
            assert pair["candidate_runtime_receipt_cid"] in runtime_cids
            assert str(pair["rescue_manifest_cid"]).startswith("b")
            assert (
                pair["baseline_compiler_reference_exposure_cid"]
                == pair["candidate_compiler_reference_exposure_cid"]
            )
            assert str(pair["pair_cid"]).startswith("b")
            assert str(pair["baseline_case_result_cid"]).startswith("b")
            assert str(pair["candidate_case_result_cid"]).startswith("b")
    assert len(pair_cids) == 8
    assert (
        g230.validate_g234_efficacy_gate_v2(gate, matrix)[
            "receipt_cid"
        ]
        == gate["receipt_cid"]
    )


def test_efficacy_gate_partial_pairs_remain_null(tmp_path: Path) -> None:
    matrix = _runtime_matrix(tmp_path)
    gate = g230.build_g234_efficacy_gate_v2(matrix, ("A1",))

    assert gate["status"] == "incomplete"
    assert gate["complete"] is False
    assert set(gate["failure_codes"]) >= {
        "source_runtime_matrix_incomplete",
        "paired_efficacy_population_incomplete",
        "paired_efficacy_outcomes_missing",
    }
    assert gate["evidence"]["expected_comparison_count"] == 4
    assert gate["evidence"]["comparison_count"] == 2
    assert gate["evidence"]["scheduled_pair_count"] == 2
    assert gate["evidence"]["measured_pair_count"] == 0
    assert gate["evidence"]["missing_pair_count"] == 2
    for comparison in gate["evidence"]["comparisons"]:
        assert comparison["net_verified_delta"] is None
        for pair in comparison["pairs"]:
            assert pair["measured"] is False
            assert pair["baseline_value"] is None
            assert pair["candidate_value"] is None
    assert (
        g230.validate_g234_efficacy_gate_v2(gate, matrix)[
            "receipt_cid"
        ]
        == gate["receipt_cid"]
    )


def test_efficacy_gate_rejects_tampered_pair_and_aggregate(
    complete_runtime_matrix: g230.G210RuntimeReceiptMatrixV2,
) -> None:
    gate = g230.build_g234_efficacy_gate_v2(
        complete_runtime_matrix, ("A1",)
    )
    tampered = _plain(gate)
    comparison = tampered["evidence"]["comparisons"][0]  # type: ignore[index]
    comparison["net_verified_delta"] = 1.0
    comparison["pairs"][0]["candidate_runtime_receipt_cid"] = (  # type: ignore[index]
        cid_for_dag_json({"kind": "forged-runtime-receipt"})
    )

    with pytest.raises(
        g230.RevisedPilotAuthorizationError,
        match="source-recompute",
    ):
        g230.validate_g234_efficacy_gate_v2(
            tampered, complete_runtime_matrix
        )


def test_efficacy_gate_nulls_unequal_compiler_exposure(
    complete_runtime_matrix: g230.G210RuntimeReceiptMatrixV2,
    tmp_path: Path,
) -> None:
    case_id = "synthetic-g231-pilot"
    source_text = SOURCE_TEXT
    proof_context = dict(PROOF_CONTEXT)
    replacement = _coordinate_evidence(
        tmp_path,
        case_id=case_id,
        source_text=source_text,
        proof_context=proof_context,
        split=contracts.Split.PILOT,
        cache_mode=contracts.CacheMode.COLD,
        variant_ids=("A1",),
        compiler_note="rebased-compiler-exposure",
    )[0]
    evidence = tuple(
        replacement
        if (
            item.case_result.split is contracts.Split.PILOT
            and item.case_result.cache_mode is contracts.CacheMode.COLD
            and item.case_result.variant_id == "A1"
        )
        else item
        for item in complete_runtime_matrix.runtime_evidence
    )
    matrix = g230.G210RuntimeReceiptMatrixV2(
        receipt_matrix=complete_runtime_matrix.receipt_matrix,
        runtime_evidence=evidence,
    )
    gate = g230.build_g234_efficacy_gate_v2(matrix, ("A1",))

    assert "runtime_unequal_compiler_exposure" in matrix.validation_issues
    assert "paired_efficacy_identity_mismatch" in gate["failure_codes"]
    assert gate["status"] == "incomplete"
    mismatched = [
        pair
        for comparison in gate["evidence"]["comparisons"]
        for pair in comparison["pairs"]
        if pair["identity_valid"] is False
    ]
    assert len(mismatched) == 1
    assert mismatched[0]["measured"] is False
    assert mismatched[0]["baseline_value"] is None
    assert mismatched[0]["candidate_value"] is None
    assert mismatched[0]["missing_reasons"] == (
        "pair_identity_mismatch",
    )


@pytest.mark.parametrize("candidate_ids", [("A0",), ("S1",), ("unknown",)])
def test_efficacy_gate_rejects_nonpaired_candidate_identity(
    tmp_path: Path,
    candidate_ids: tuple[str, ...],
) -> None:
    with pytest.raises(
        g230.RevisedPilotAuthorizationError,
        match="candidate_variant_ids",
    ):
        g230.build_g234_efficacy_gate_v2(
            _runtime_matrix(tmp_path), candidate_ids
        )
