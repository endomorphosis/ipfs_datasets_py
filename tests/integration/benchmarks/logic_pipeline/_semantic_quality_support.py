"""Synthetic-only builders for G201/G235 source-replay tests."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence

from benchmarks.logic_pipeline.ablation import (
    AblationCase,
    build_semantic_ablation_plan,
)
from benchmarks.logic_pipeline.adapters import (
    StageAdapter,
    StageOutput,
    StageRequest,
    SymaiAdapterConfig,
    _symai_cache_key,
    _symai_cache_namespace,
)
from benchmarks.logic_pipeline.cases import (
    SPLIT_MANIFEST_SCHEMA,
    normalized_source_sha256,
)
from benchmarks.logic_pipeline.content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
)
from benchmarks.logic_pipeline.contracts import (
    SEMANTIC_PRODUCER_REGISTRY_V2_CID,
    SEMANTIC_PROTOCOL_V2_CID,
    SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID,
    CacheMode,
    CaseResultRecord,
    SemanticProjection,
    Split,
    StageName,
    canonical_json,
)
from benchmarks.logic_pipeline.semantic_quality import (
    G201SemanticEvidenceIndexV2,
    build_g201_semantic_evidence_index_v2,
)
from benchmarks.logic_pipeline.semantic_reassessment import (
    SEMANTIC_TARGET_MANIFEST_SCHEMA_V2,
    SemanticCalibrationTargetV2,
)
from benchmarks.logic_pipeline.variants import VARIANT_REGISTRY


SYNTHETIC_MANIFEST_SHA256 = "b" * 64
SYNTHETIC_ENVIRONMENT_SHA256 = "e" * 64
SYNTHETIC_RUN_ID = "synthetic-g201-source-replay"
CALIBRATION_VARIANTS = ("A0", "A1", "A5", "A7", "A8")


def _plain(value: object) -> object:
    """Thaw contract enums/proxies through their canonical JSON wire form."""

    return json.loads(canonical_json(value))


def semantic_target(
    case_id: str,
    *,
    source_text: str | None = None,
) -> SemanticCalibrationTargetV2:
    token = case_id.replace("-", "_")
    target = f"publish_{token}"
    return SemanticCalibrationTargetV2(
        case_id=case_id,
        source_text=(
            source_text
            if source_text is not None
            else f"Agency {token} must publish its notice."
        ),
        logic_family="deontic",
        target=target,
        semantic_class="proved",
        predicates=(target,),
        entities=(f"agency_{token}", f"notice_{token}"),
    )


def target_population(
    *,
    runtime_source_text: str | None = None,
    manifest_sha256: str = SYNTHETIC_MANIFEST_SHA256,
) -> tuple[
    tuple[SemanticCalibrationTargetV2, ...],
    Mapping[str, object],
]:
    pilot_ids = ["synthetic-g231-pilot"] + [
        f"synthetic-g201-pilot-{index:02d}" for index in range(9)
    ]
    development_ids = ["synthetic-g231-development"] + [
        f"synthetic-g201-development-{index:02d}" for index in range(9)
    ]
    targets = tuple(
        semantic_target(
            case_id,
            source_text=(
                runtime_source_text
                if case_id
                in {
                    "synthetic-g231-pilot",
                    "synthetic-g231-development",
                }
                else None
            ),
        )
        for case_id in (*pilot_ids, *development_ids)
    )
    by_id = {target.case_id: target for target in targets}
    entries = []
    reviewed_sha256s: dict[str, str] = {}
    for target in sorted(targets, key=lambda item: item.case_id):
        split = (
            "pilot" if target.case_id in set(pilot_ids) else "development"
        )
        reviewed_case = {
            "schema": "synthetic-reviewed-case.v1",
            "case_id": target.case_id,
            "split": split,
            "source_cid": target.source_cid,
            "expected_semantics": target.semantic_fields(),
        }
        reviewed_sha256 = hashlib.sha256(
            canonical_json(reviewed_case).encode("utf-8")
        ).hexdigest()
        reviewed_sha256s[target.case_id] = reviewed_sha256
        entries.append(
            {
                "case_id": target.case_id,
                "split": split,
                "reviewed_case_cid": cid_for_dag_json(reviewed_case),
                "reviewed_case_sha256": reviewed_sha256,
                "source_cid": target.source_cid,
                "expected_semantics": target.semantic_fields(),
                "review_attestation_cid": cid_for_dag_json(
                    {
                        "schema": "synthetic-review-attestation.v1",
                        "case_id": target.case_id,
                        "reviewed": True,
                    }
                ),
            }
        )

    split_identities: dict[str, Mapping[str, object]] = {}
    for split, case_ids in (
        ("pilot", pilot_ids),
        ("development", development_ids),
    ):
        split_body: dict[str, object] = {
            "schema": SPLIT_MANIFEST_SCHEMA,
            "corpus_manifest_sha256": manifest_sha256,
            "split": split,
            "case_ids": case_ids,
            "case_sha256s": [
                reviewed_sha256s[case_id] for case_id in case_ids
            ],
            "source_sha256s": [
                hashlib.sha256(
                    by_id[case_id].source_text.encode("utf-8")
                ).hexdigest()
                for case_id in case_ids
            ],
            "normalized_source_sha256s": [
                normalized_source_sha256(by_id[case_id].source_text)
                for case_id in case_ids
            ],
        }
        split_identities[split] = {
            **split_body,
            "split_manifest_cid": cid_for_dag_json(split_body),
            "split_sha256": hashlib.sha256(
                canonical_json(split_body).encode("utf-8")
            ).hexdigest(),
        }
    manifest_body: dict[str, object] = {
        "schema": SEMANTIC_TARGET_MANIFEST_SCHEMA_V2,
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "producer_registry_cid": SEMANTIC_PRODUCER_REGISTRY_V2_CID,
        "reviewed_target_source_cid": (
            SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID
        ),
        "case_manifest_sha256": manifest_sha256,
        "reviewed_split_identities": split_identities,
        "case_count": 20,
        "splits": {"pilot": 10, "development": 10, "holdout": 0},
        "cases": entries,
        "ground_truth_phase": "post_execution_reviewed_validation",
        "holdout_accessed": False,
    }
    return targets, {
        **manifest_body,
        "target_manifest_cid": cid_for_dag_json(manifest_body),
    }


def projection_payload(
    target: SemanticCalibrationTargetV2,
    producer_id: str,
    *,
    validation_errors: Sequence[str] = (),
) -> tuple[Mapping[str, object], SemanticProjection]:
    completeness = {
        "logic_family": True,
        "target": True,
        "class": True,
        "predicates": True,
        "entities": True,
    }
    if producer_id == "symai":
        response = {
            "logic_family": target.logic_family,
            "target": target.target,
            "class": target.semantic_class,
            "predicates": list(target.predicates),
            "entities": list(target.entities),
            "completeness": completeness,
            "ambiguity_flags": [],
            "confidence_millionths": 950_000,
            "validation_errors": sorted(set(validation_errors)),
        }
        evidence_cid = cid_for_dag_json(response)
    else:
        modal_ir = {
            "formulas": [
                {
                    "operator": {"family": target.logic_family},
                    "predicate": {
                        "name": target.target,
                        "arguments": list(target.entities),
                    },
                }
            ]
        }
        evidence_cid = cid_for_dag_json(modal_ir)
    projection = SemanticProjection.create(
        producer_id=producer_id,
        source_text=target.source_text,
        logic_family=target.logic_family,
        target=target.target,
        semantic_class=target.semantic_class,
        predicates=target.predicates,
        entities=target.entities,
        completeness=completeness,
        confidence_millionths=950_000,
        validation_errors=validation_errors,
        evidence_cid=evidence_cid,
    )
    if producer_id == "compiler":
        return {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark.compiler-output.v2"
            ),
            "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
            "source_cid": target.source_cid,
            "modal_ir": modal_ir,
            "modal_ir_cid": evidence_cid,
            "retained_modal_ir_cid": evidence_cid,
            "semantic_projection": projection.to_dict(),
        }, projection
    if producer_id.startswith("spacy_"):
        return {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark.spacy-evidence.v2"
            ),
            "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
            "document": {"source_cid": target.source_cid},
            "modal_ir": modal_ir,
            "modal_ir_cid": evidence_cid,
            "semantic_projection": projection.to_dict(),
        }, projection
    raw_output = canonical_json(response)
    return {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark.symai-evidence.v2"
        ),
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "source_cid": target.source_cid,
        "raw_output": raw_output,
        "raw_output_cid": cid_for_bytes(raw_output.encode("utf-8")),
        "validated_response": response,
        "validated_response_cid": evidence_cid,
        "semantic_projection": projection.to_dict(),
    }, projection


def _stage(
    target: SemanticCalibrationTargetV2,
    *,
    split: Split,
    variant_id: str,
    stage_name: StageName,
    producer_id: str,
    upstream: tuple[object, ...],
    validation_errors: Sequence[str] = (),
    manifest_sha256: str = SYNTHETIC_MANIFEST_SHA256,
    environment_sha256: str = SYNTHETIC_ENVIRONMENT_SHA256,
) -> object:
    definition = VARIANT_REGISTRY[variant_id]
    request = StageRequest(
        run_id=SYNTHETIC_RUN_ID,
        case_id=target.case_id,
        case_manifest_sha256=manifest_sha256,
        variant_id=variant_id,
        split=split,
        cache_mode=CacheMode.COLD,
        input_data={"text": target.source_text},
        requested_identity=definition.requested_identity(stage_name),
        environment_sha256=environment_sha256,
        source=("synthetic-g201-source-safe",),
        upstream_stage_digests=tuple(
            item.digest for item in upstream
        ),
        semantic_protocol_cid=SEMANTIC_PROTOCOL_V2_CID,
    )
    payload, _projection = projection_payload(
        target,
        producer_id,
        validation_errors=validation_errors,
    )
    effective_identity = {
        **dict(definition.requested_identity(stage_name)),
        "implementation": f"synthetic-{producer_id}",
        "graph_invoked": True,
    }
    if stage_name is StageName.SYMAI:
        context_body = {
            "schema": "synthetic-semantic-context.v2",
            "source_cid": target.source_cid,
            "upstream_stage_cids": [
                cid_for_dag_json(_plain(item.to_dict()))
                for item in upstream
            ],
        }
        context_cid = cid_for_dag_json(context_body)
        config = SymaiAdapterConfig(
            provider="synthetic_provider",
            model="synthetic-model",
            dry_run=False,
            semantic_protocol_cid=SEMANTIC_PROTOCOL_V2_CID,
        )
        namespace = _symai_cache_namespace(request)
        cache_key = _symai_cache_key(
            request,
            config,
            namespace,
            {"context_cid": context_cid},
        )
        payload = {
            **payload,
            "backend_provenance": {
                "requested_provider": config.provider,
                "effective_provider": config.provider,
                "requested_model": config.model,
                "effective_model": config.model,
                "dry_run": config.dry_run,
                "router_metadata": {},
            },
            "cache": {
                "namespace": namespace,
                "key": cache_key,
                "mode": request.cache_mode.value,
                "hit": False,
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
        effective_identity.update(
            {
                "requested_provider": config.provider,
                "effective_provider": config.provider,
                "requested_model": config.model,
                "effective_model": config.model,
                "dry_run": config.dry_run,
                "cache_namespace": namespace,
                "cache_key": cache_key,
                "semantic_context_cid": context_cid,
            }
        )
    return StageAdapter(
        stage_name,
        handler=lambda _request: StageOutput(
            data=payload,
            effective_identity=effective_identity,
        ),
        adapter_version="2",
        source=("synthetic-g201-adapter",),
    ).run(request)


def result_for_route(
    target: SemanticCalibrationTargetV2,
    *,
    split: Split,
    variant_id: str,
    symai_validation_error: bool = False,
    all_validation_error: bool = False,
    manifest_sha256: str = SYNTHETIC_MANIFEST_SHA256,
    environment_sha256: str = SYNTHETIC_ENVIRONMENT_SHA256,
) -> CaseResultRecord:
    compiler = _stage(
        target,
        split=split,
        variant_id=variant_id,
        stage_name=StageName.COMPILER,
        producer_id="compiler",
        upstream=(),
        validation_errors=(
            ("synthetic_contract_error",)
            if all_validation_error
            else ()
        ),
        manifest_sha256=manifest_sha256,
        environment_sha256=environment_sha256,
    )
    records = [compiler]
    if variant_id != "A0":
        producer_id = {
            "A1": "spacy_full_model",
            "A5": "spacy_full_model",
            "A7": "spacy_regex_legal",
            "A8": "spacy_blank_model",
        }[variant_id]
        spacy = _stage(
            target,
            split=split,
            variant_id=variant_id,
            stage_name=StageName.SPACY,
            producer_id=producer_id,
            upstream=tuple(records),
            validation_errors=(
                ("synthetic_contract_error",)
                if all_validation_error
                else ()
            ),
            manifest_sha256=manifest_sha256,
            environment_sha256=environment_sha256,
        )
        records.append(spacy)
    if variant_id == "A5":
        symai = _stage(
            target,
            split=split,
            variant_id=variant_id,
            stage_name=StageName.SYMAI,
            producer_id="symai",
            upstream=tuple(records),
            validation_errors=(
                ("synthetic_contract_error",)
                if symai_validation_error or all_validation_error
                else ()
            ),
            manifest_sha256=manifest_sha256,
            environment_sha256=environment_sha256,
        )
        records.append(symai)
    return CaseResultRecord.from_stages(tuple(records))


def complete_g201_index(
    *,
    runtime_source_text: str | None = None,
    symai_validation_error_case_id: str | None = None,
    validation_error_case_ids: Sequence[str] = (),
    manifest_sha256: str = SYNTHETIC_MANIFEST_SHA256,
    environment_sha256: str = SYNTHETIC_ENVIRONMENT_SHA256,
) -> G201SemanticEvidenceIndexV2:
    targets, manifest = target_population(
        runtime_source_text=runtime_source_text,
        manifest_sha256=manifest_sha256,
    )
    split_identities = manifest["reviewed_split_identities"]
    by_id = {target.case_id: target for target in targets}
    plans = []
    results = []
    for split in (Split.PILOT, Split.DEVELOPMENT):
        case_ids = split_identities[split.value]["case_ids"]
        cases = tuple(
            AblationCase.create(
                case_id,
                {"text": by_id[case_id].source_text},
                split=split,
            )
            for case_id in case_ids
        )
        plan = build_semantic_ablation_plan(
            SYNTHETIC_RUN_ID,
            cases,
            case_manifest_sha256=manifest_sha256,
            split=split,
            seed=31,
            variant_ids=CALIBRATION_VARIANTS,
            cache_modes=(CacheMode.COLD,),
            environment_sha256=environment_sha256,
        )
        plans.append(plan)
        for job in plan.jobs:
            results.append(
                result_for_route(
                    by_id[job.case_id],
                    split=split,
                    variant_id=job.variant_id,
                    symai_validation_error=(
                        job.case_id == symai_validation_error_case_id
                    ),
                    all_validation_error=(
                        job.case_id in set(validation_error_case_ids)
                    ),
                    manifest_sha256=manifest_sha256,
                    environment_sha256=environment_sha256,
                )
            )
    return build_g201_semantic_evidence_index_v2(
        target_manifest=manifest,
        targets=targets,
        plans=plans,
        results=results,
    )


def mutable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): mutable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [mutable(item) for item in value]
    if isinstance(value, list):
        return [mutable(item) for item in value]
    return value
