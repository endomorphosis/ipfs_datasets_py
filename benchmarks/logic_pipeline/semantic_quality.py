"""Source-recomputed semantic quality evidence for the revised pilot.

The revision-2 semantic calibration report is intentionally a derived value:
neither its CID nor a reduced aggregate is sufficient evidence for a gate.
This module carries the complete, label-blind G201 execution sources in a
portable CID-addressed index and replays them before joining reviewed
pilot/development targets to G210 full-runtime receipts.

No function in this module opens a corpus, fixture, manifest, or holdout.  The
reviewed target manifest and source-only execution records must be injected by
the caller.  Ground truth is read only by the downstream validators here; it
is never placed in a producer request or SyMAI cache-key preimage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import re
from types import MappingProxyType
from typing import Final, Mapping, Sequence, Self

from .ablation import AblationPlan, AblationValidationError
from .adapters import (
    StageRequest,
    SymaiAdapterConfig,
    _symai_cache_key,
    _symai_cache_namespace,
)
from .cases import SPLIT_MANIFEST_SCHEMA, normalized_source_sha256
from .content_addressing import cid_for_bytes, cid_for_dag_json, validate_cid
from .contracts import (
    SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2,
    SEMANTIC_CALIBRATION_CASE_COUNT_V2,
    SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2,
    SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID,
    SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID,
    SEMANTIC_NORMALIZATION_V2_CID,
    SEMANTIC_PRODUCER_IDS_V2,
    SEMANTIC_PRODUCER_REGISTRY_V2_CID,
    SEMANTIC_PROJECTION_SCHEMA_V2_CID,
    SEMANTIC_PROMPT_SCHEMA_V2,
    SEMANTIC_PROMPT_V2_CID,
    SEMANTIC_PROTOCOL_V2_CID,
    SEMANTIC_RESPONSE_SCHEMA_V2_CID,
    SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID,
    CacheMode,
    CaseResultRecord,
    ProtocolContractError,
    Split,
    StageName,
    StageRecord,
    canonical_json,
    semantic_calibration_route_manifest_v2,
)
from .revised_pilot_authorization import (
    G210_CACHE_MODES,
    G210_SPLITS,
    G210_VARIANT_IDS,
    G210RuntimeReceiptMatrixV2,
    RevisedPilotAuthorizationError,
)
from .semantic_reassessment import (
    SEMANTIC_TARGET_MANIFEST_SCHEMA_V2,
    SemanticCalibrationCoordinateV2,
    SemanticCalibrationGraphBindingV2,
    SemanticCalibrationTargetV2,
    SemanticReassessmentError,
    _evaluate_semantic_calibration_coordinate_v2,
    _evaluate_semantic_calibration_v2,
    _stage_invoked,
    validate_source_only_semantic_input_v2,
)
from .variants import VARIANT_REGISTRY, VARIANT_REGISTRY_SHA256


G201_SEMANTIC_EVIDENCE_INDEX_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g201-semantic-evidence-index.v2"
)
G201_SEMANTIC_SOURCE_COORDINATE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g201-semantic-source-coordinate.v2"
)
G201_SEMANTIC_PREFLIGHT_PLAN_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g201-semantic-preflight-plan.v2"
)
G235_RUNTIME_SEMANTIC_OBSERVATION_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g235-runtime-semantic-observation.v2"
)
G235_SEMANTIC_QUALITY_GATE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g235-semantic-quality-gate.v2"
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REQUIRED_CALIBRATION_VARIANTS: Final = frozenset(
    {"A0", "A1", "A5", "A7", "A8"}
)
_FRONTEND_STAGES: Final = frozenset(
    {StageName.COMPILER, StageName.SPACY, StageName.SYMAI}
)
_PROOF_STAGES: Final = frozenset(
    {StageName.HAMMER, StageName.LEANSTRAL, StageName.KERNEL}
)
_SEMANTIC_FIELDS: Final = (
    "logic_family",
    "target",
    "class",
    "predicates",
    "entities",
)


class SemanticQualityError(ValueError):
    """Raised when G201/G235 evidence cannot be source-recomputed."""


def HSSLEV2350C27() -> str:
    """Return AST-verifiable evidence for the bounded G235 validator lane."""

    return (
        "CID-native G201 source replay with label-blind producer/cache "
        "proofs and per-arm non-vacuous absolute semantic quality"
    )


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return _plain(value.value)
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_plain(item) for item in value]
    return value


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise SemanticQualityError("DAG-JSON object keys must be strings")
        return MappingProxyType(
            {
                str(key): _freeze(item)
                for key, item in sorted(value.items())
            }
        )
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return tuple(_freeze(item) for item in value)
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise SemanticQualityError(
        f"unsupported DAG-JSON value: {type(value).__name__}"
    )


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise SemanticQualityError(f"{field_name} must be an object")
    return value


def _array(value: object, field_name: str) -> list[object]:
    if not isinstance(value, (list, tuple)):
        raise SemanticQualityError(f"{field_name} must be an array")
    return list(value)


def _exact(
    value: Mapping[str, object],
    expected: set[str],
    field_name: str,
) -> None:
    if set(value) != expected:
        raise SemanticQualityError(
            f"{field_name} fields changed; "
            f"missing={sorted(expected - set(value))}, "
            f"unknown={sorted(set(value) - expected)}"
        )


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise SemanticQualityError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return value


def _cid(
    value: object,
    field_name: str,
    *,
    codecs: tuple[str, ...] = ("dag-json",),
) -> str:
    try:
        return validate_cid(value, codecs=codecs)
    except (TypeError, ValueError) as exc:
        raise SemanticQualityError(
            f"{field_name} must be a canonical CID"
        ) from exc


def _protocol_identities() -> dict[str, str]:
    return {
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "projection_schema_cid": SEMANTIC_PROJECTION_SCHEMA_V2_CID,
        "normalization_cid": SEMANTIC_NORMALIZATION_V2_CID,
        "response_schema_cid": SEMANTIC_RESPONSE_SCHEMA_V2_CID,
        "prompt_cid": SEMANTIC_PROMPT_V2_CID,
        "producer_registry_cid": SEMANTIC_PRODUCER_REGISTRY_V2_CID,
        "calibration_route_manifest_cid": (
            SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID
        ),
        "calibration_metric_spec_cid": (
            SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID
        ),
        "reviewed_target_source_cid": (
            SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID
        ),
    }


def _target_manifest(
    value: object,
    targets: Sequence[SemanticCalibrationTargetV2],
) -> Mapping[str, object]:
    manifest = _mapping(value, "reviewed target manifest")
    expected_fields = {
        "schema",
        "semantic_protocol_cid",
        "producer_registry_cid",
        "reviewed_target_source_cid",
        "case_manifest_sha256",
        "reviewed_split_identities",
        "case_count",
        "splits",
        "cases",
        "ground_truth_phase",
        "holdout_accessed",
        "target_manifest_cid",
    }
    _exact(manifest, expected_fields, "reviewed target manifest")
    body = {
        key: _plain(item)
        for key, item in manifest.items()
        if key != "target_manifest_cid"
    }
    if (
        manifest.get("schema") != SEMANTIC_TARGET_MANIFEST_SCHEMA_V2
        or manifest.get("semantic_protocol_cid")
        != SEMANTIC_PROTOCOL_V2_CID
        or manifest.get("producer_registry_cid")
        != SEMANTIC_PRODUCER_REGISTRY_V2_CID
        or manifest.get("reviewed_target_source_cid")
        != SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID
        or manifest.get("case_count")
        != SEMANTIC_CALIBRATION_CASE_COUNT_V2
        or manifest.get("splits")
        != {"pilot": 10, "development": 10, "holdout": 0}
        or manifest.get("ground_truth_phase")
        != "post_execution_reviewed_validation"
        or manifest.get("holdout_accessed") is not False
        or _cid(
            manifest.get("target_manifest_cid"),
            "target_manifest_cid",
        )
        != cid_for_dag_json(body)
    ):
        raise SemanticQualityError(
            "reviewed target manifest identity or frozen policy drifted"
        )
    case_manifest_sha256 = _sha256(
        manifest.get("case_manifest_sha256"),
        "reviewed target case_manifest_sha256",
    )

    if (
        len(targets) != SEMANTIC_CALIBRATION_CASE_COUNT_V2
        or len({target.case_id for target in targets}) != len(targets)
    ):
        raise SemanticQualityError(
            "G201 requires exactly twenty distinct semantic targets"
        )
    catalog = {target.case_id: target for target in targets}
    entries = _array(manifest.get("cases"), "reviewed target cases")
    if len(entries) != SEMANTIC_CALIBRATION_CASE_COUNT_V2:
        raise SemanticQualityError(
            "reviewed target manifest does not contain twenty cases"
        )
    parsed_entries: dict[str, Mapping[str, object]] = {}
    entry_order: list[str] = []
    entry_fields = {
        "case_id",
        "split",
        "reviewed_case_cid",
        "reviewed_case_sha256",
        "source_cid",
        "expected_semantics",
        "review_attestation_cid",
    }
    for raw_entry in entries:
        entry = _mapping(raw_entry, "reviewed target case")
        _exact(entry, entry_fields, "reviewed target case")
        case_id = entry.get("case_id")
        split = entry.get("split")
        if (
            not isinstance(case_id, str)
            or case_id in parsed_entries
            or case_id not in catalog
            or split not in {"pilot", "development"}
        ):
            raise SemanticQualityError(
                "reviewed target case identity or split is invalid"
            )
        target = catalog[case_id]
        if (
            entry.get("source_cid") != target.source_cid
            or _plain(entry.get("expected_semantics"))
            != target.semantic_fields()
        ):
            raise SemanticQualityError(
                "reviewed target fields differ from their source target"
            )
        _cid(entry.get("reviewed_case_cid"), "reviewed_case_cid")
        _cid(
            entry.get("review_attestation_cid"),
            "review_attestation_cid",
        )
        _sha256(entry.get("reviewed_case_sha256"), "reviewed_case_sha256")
        parsed_entries[case_id] = entry
        entry_order.append(case_id)
    if set(parsed_entries) != set(catalog) or entry_order != sorted(entry_order):
        raise SemanticQualityError(
            "reviewed target cases must be the exact sorted target population"
        )

    split_identities = _mapping(
        manifest.get("reviewed_split_identities"),
        "reviewed split identities",
    )
    if set(split_identities) != {"pilot", "development"}:
        raise SemanticQualityError(
            "reviewed target manifest must bind pilot and development"
        )
    assigned: set[str] = set()
    split_identity_fields = {
        "schema",
        "corpus_manifest_sha256",
        "split",
        "case_ids",
        "case_sha256s",
        "source_sha256s",
        "normalized_source_sha256s",
        "split_manifest_cid",
        "split_sha256",
    }
    for split in ("pilot", "development"):
        identity = _mapping(
            split_identities[split],
            f"reviewed {split} split identity",
        )
        _exact(
            identity,
            split_identity_fields,
            f"reviewed {split} split identity",
        )
        case_ids = _array(identity.get("case_ids"), f"{split}.case_ids")
        case_sha256s = _array(
            identity.get("case_sha256s"), f"{split}.case_sha256s"
        )
        source_sha256s = _array(
            identity.get("source_sha256s"), f"{split}.source_sha256s"
        )
        normalized_sha256s = _array(
            identity.get("normalized_source_sha256s"),
            f"{split}.normalized_source_sha256s",
        )
        if (
            identity.get("schema") != SPLIT_MANIFEST_SCHEMA
            or identity.get("corpus_manifest_sha256")
            != case_manifest_sha256
            or identity.get("split") != split
            or len(case_ids)
            != len(case_sha256s)
            != len(source_sha256s)
            != len(normalized_sha256s)
            != 10
            or len(set(case_ids)) != 10
            or any(
                not isinstance(case_id, str)
                or case_id not in parsed_entries
                or parsed_entries[case_id].get("split") != split
                for case_id in case_ids
            )
        ):
            raise SemanticQualityError(
                f"reviewed {split} split population is invalid"
            )
        for index, case_id in enumerate(case_ids):
            target = catalog[str(case_id)]
            entry = parsed_entries[str(case_id)]
            expected_source_sha256 = hashlib.sha256(
                target.source_text.encode("utf-8")
            ).hexdigest()
            if (
                case_sha256s[index] != entry.get("reviewed_case_sha256")
                or source_sha256s[index] != expected_source_sha256
                or normalized_sha256s[index]
                != normalized_source_sha256(target.source_text)
            ):
                raise SemanticQualityError(
                    f"reviewed {split} split source identity changed"
                )
        split_body = {
            key: _plain(item)
            for key, item in identity.items()
            if key not in {"split_manifest_cid", "split_sha256"}
        }
        split_sha256 = hashlib.sha256(
            canonical_json(split_body).encode("utf-8")
        ).hexdigest()
        if (
            _cid(
                identity.get("split_manifest_cid"),
                f"{split}.split_manifest_cid",
            )
            != cid_for_dag_json(split_body)
            or _sha256(
                identity.get("split_sha256"), f"{split}.split_sha256"
            )
            != split_sha256
        ):
            raise SemanticQualityError(
                f"reviewed {split} split identity did not recompute"
            )
        assigned.update(str(case_id) for case_id in case_ids)
    if assigned != set(catalog):
        raise SemanticQualityError(
            "reviewed split identities do not cover the target population"
        )
    return _freeze(_plain(manifest))  # type: ignore[return-value]


def _routes() -> dict[str, Mapping[str, object]]:
    manifest = semantic_calibration_route_manifest_v2()
    if (
        cid_for_dag_json(manifest)
        != SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID
    ):
        raise SemanticQualityError(
            "semantic calibration route manifest CID drifted"
        )
    routes = {
        str(route["producer_id"]): route
        for route in _array(manifest.get("routes"), "semantic routes")
        if isinstance(route, Mapping)
    }
    if set(routes) != set(SEMANTIC_PRODUCER_IDS_V2):
        raise SemanticQualityError(
            "semantic calibration routes do not cover every producer"
        )
    return routes


def build_g201_semantic_preflight_plan_v2(
    *,
    target_manifest: Mapping[str, object],
    targets: Sequence[
        SemanticCalibrationTargetV2 | Mapping[str, object]
    ],
    plans: Sequence[AblationPlan],
) -> Mapping[str, object]:
    """Address only the reviewed targets and source-only G201 schedules.

    This boundary deliberately cannot accept a ``CaseResultRecord`` or a
    ``G201SemanticEvidenceIndexV2``.  It is therefore safe to call before the
    first semantic producer runs.  The post-run G231 join rebuilds this exact
    preflight value from the source members carried by the complete G201
    evidence index.
    """

    try:
        parsed_targets = tuple(
            sorted(
                (
                    item
                    if isinstance(item, SemanticCalibrationTargetV2)
                    else SemanticCalibrationTargetV2.from_dict(item)
                    for item in targets
                ),
                key=lambda item: item.case_id,
            )
        )
        parsed_plans = tuple(
            sorted(
                (
                    AblationPlan.from_dict(_plain(item.to_dict()))
                    for item in plans
                ),
                key=lambda item: item.split.value,
            )
        )
    except (
        AblationValidationError,
        SemanticReassessmentError,
        TypeError,
        ValueError,
        KeyError,
    ) as exc:
        raise SemanticQualityError(
            "G201 preflight sources failed strict parsing"
        ) from exc
    manifest = _target_manifest(target_manifest, parsed_targets)
    catalog = {target.case_id: target for target in parsed_targets}
    if (
        len(parsed_targets) != SEMANTIC_CALIBRATION_CASE_COUNT_V2
        or len(catalog) != len(parsed_targets)
        or len(parsed_plans) != 2
        or {plan.split for plan in parsed_plans}
        != {Split.PILOT, Split.DEVELOPMENT}
        or any(len(plan.case_ids) != 10 for plan in parsed_plans)
    ):
        raise SemanticQualityError(
            "G201 preflight requires the exact twenty-target, two-plan "
            "pilot/development population"
        )
    shared = {
        (
            plan.run_id,
            plan.case_manifest_sha256,
            plan.environment_sha256,
            plan.registry_sha256,
            frozenset(plan.variant_ids),
            tuple(mode.value for mode in plan.cache_modes),
        )
        for plan in parsed_plans
    }
    if (
        len(shared) != 1
        or any(plan.environment_sha256 is None for plan in parsed_plans)
        or any(
            plan.registry_sha256 != VARIANT_REGISTRY_SHA256
            for plan in parsed_plans
        )
        or any(
            frozenset(plan.variant_ids)
            != _REQUIRED_CALIBRATION_VARIANTS
            or tuple(plan.cache_modes) != (CacheMode.COLD,)
            or plan.holdout_access_log_id is not None
            or plan.case_manifest_sha256
            != manifest.get("case_manifest_sha256")
            for plan in parsed_plans
        )
    ):
        raise SemanticQualityError(
            "G201 preflight plans do not share the frozen "
            "source/environment/calibration matrix"
        )
    split_identities = _mapping(
        manifest.get("reviewed_split_identities"),
        "reviewed split identities",
    )
    planned_case_ids: set[str] = set()
    plan_cids: dict[str, str] = {}
    split_case_ids: dict[str, list[str]] = {}
    job_count = 0
    for plan in parsed_plans:
        split = plan.split.value
        identity = _mapping(
            split_identities[split],
            f"{split} split identity",
        )
        if tuple(
            _array(identity.get("case_ids"), f"{split}.case_ids")
        ) != plan.case_ids:
            raise SemanticQualityError(
                f"G201 {split} preflight order differs from reviewed targets"
            )
        for job in plan.jobs:
            target = catalog.get(job.case_id)
            if (
                target is None
                or not isinstance(job.input_data, Mapping)
                or set(job.input_data) != {"text"}
                or job.input_data.get("text") != target.source_text
            ):
                raise SemanticQualityError(
                    "G201 preflight producer job is not the exact "
                    "label-blind source envelope"
                )
        planned_case_ids.update(plan.case_ids)
        plan_cids[split] = cid_for_dag_json(_plain(plan.to_dict()))
        split_case_ids[split] = list(plan.case_ids)
        job_count += len(plan.jobs)
    if (
        planned_case_ids != set(catalog)
        or job_count != SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2
    ):
        raise SemanticQualityError(
            "G201 preflight schedules do not cover the exact 100-coordinate "
            "target population"
        )
    target_set_body = {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark."
            "g201-reviewed-target-set.v2"
        ),
        "target_manifest_cid": manifest["target_manifest_cid"],
        "targets": [
            {
                "case_id": target.case_id,
                "source_cid": target.source_cid,
                "target_cid": cid_for_dag_json(target.to_dict()),
            }
            for target in parsed_targets
        ],
        "holdout_included": False,
    }
    plan_set_body = {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark."
            "g201-source-only-plan-set.v2"
        ),
        "plan_cids": {
            split: plan_cids[split]
            for split in ("pilot", "development")
        },
        "split_case_ids": {
            split: split_case_ids[split]
            for split in ("pilot", "development")
        },
        "coordinate_count": job_count,
        "holdout_included": False,
    }
    first_plan = parsed_plans[0]
    body = {
        "schema": G201_SEMANTIC_PREFLIGHT_PLAN_SCHEMA_V2,
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "protocol_identities": _protocol_identities(),
        "run_id": first_plan.run_id,
        "case_manifest_sha256": first_plan.case_manifest_sha256,
        "environment_sha256": first_plan.environment_sha256,
        "target_set_cid": cid_for_dag_json(target_set_body),
        "plan_set_cid": cid_for_dag_json(plan_set_body),
        "target_manifest_cid": manifest["target_manifest_cid"],
        "target_count": len(parsed_targets),
        "coordinate_count": job_count,
        "result_count": 0,
        "result_objects_accepted": False,
        "source_only": True,
        "holdout_included": False,
        "holdout_accessed": False,
    }
    result = {
        **body,
        "preflight_plan_cid": cid_for_dag_json(body),
    }
    frozen = _freeze(result)
    assert isinstance(frozen, Mapping)
    return frozen


def _result_coordinate(
    result: CaseResultRecord,
) -> tuple[str, str, str, str]:
    return (
        result.split.value,
        result.case_id,
        result.variant_id,
        result.cache_mode.value,
    )


def _plan_coordinate(
    plan: AblationPlan,
    case_id: str,
    variant_id: str,
    cache_mode: str,
) -> tuple[str, str, str, str]:
    return (plan.split.value, case_id, variant_id, cache_mode)


def _symai_cache_binding(
    stage: StageRecord,
    source_text: str,
) -> Mapping[str, object]:
    payload = _mapping(stage.data, "SyMAI semantic payload")
    cache = _mapping(payload.get("cache"), "SyMAI cache receipt")
    provenance = _mapping(
        payload.get("backend_provenance"), "SyMAI backend provenance"
    )
    semantic_context = _mapping(
        payload.get("semantic_context"), "SyMAI semantic context"
    )
    context_cid_value = semantic_context.get("context_cid")
    context_cid = (
        None
        if context_cid_value is None
        else _cid(context_cid_value, "SyMAI semantic context CID")
    )
    if (
        semantic_context.get("source_cid")
        != cid_for_bytes(source_text.encode("utf-8"))
        or stage.provenance.effective_identity.get(
            "semantic_context_cid"
        )
        != context_cid
    ):
        raise SemanticQualityError(
            "SyMAI semantic context is not bound to the source bytes"
        )
    raw_metadata = provenance.get("router_metadata", {})
    metadata = _mapping(raw_metadata, "SyMAI router metadata")
    inner_keys = (
        "resolved_provider_name",
        "resolved_model_name",
        "service_endpoint",
        "routing_backend",
    )
    inner = tuple(metadata.get(key) for key in inner_keys)
    if any(item is not None for item in inner) and not all(
        isinstance(item, str) and item for item in inner
    ):
        raise SemanticQualityError(
            "SyMAI inner-route cache identity is incomplete"
        )
    provider = provenance.get("requested_provider")
    model = provenance.get("requested_model")
    effective_provider = provenance.get("effective_provider")
    effective_model = provenance.get("effective_model")
    dry_run = provenance.get("dry_run")
    if (
        not isinstance(provider, str)
        or not isinstance(model, str)
        or not isinstance(effective_provider, str)
        or not isinstance(effective_model, str)
        or type(dry_run) is not bool
        or stage.provenance.effective_identity.get("requested_provider")
        != provider
        or stage.provenance.effective_identity.get("requested_model")
        != model
        or stage.provenance.effective_identity.get("effective_provider")
        != effective_provider
        or stage.provenance.effective_identity.get("effective_model")
        != effective_model
    ):
        raise SemanticQualityError(
            "SyMAI provider/model identities are invalid or inconsistent"
        )
    try:
        config = SymaiAdapterConfig(
            provider=provider,
            model=model,
            dry_run=dry_run,
            expected_inner_provider=(
                None if inner[0] is None else str(inner[0])
            ),
            expected_inner_model=(
                None if inner[1] is None else str(inner[1])
            ),
            expected_inner_endpoint=(
                None if inner[2] is None else str(inner[2])
            ),
            expected_inner_backend=(
                None if inner[3] is None else str(inner[3])
            ),
            semantic_protocol_cid=SEMANTIC_PROTOCOL_V2_CID,
        )
        request = StageRequest(
            run_id=stage.run_id,
            case_id=stage.case_id,
            case_manifest_sha256=stage.case_manifest_sha256,
            variant_id=stage.variant_id,
            split=stage.split,
            cache_mode=stage.cache_mode,
            input_data={"text": source_text},
            requested_identity=_plain(
                stage.provenance.requested_identity
            ),  # type: ignore[arg-type]
            environment_sha256=stage.provenance.environment_sha256,
            source=stage.provenance.source,
            upstream_stage_digests=(
                stage.provenance.upstream_stage_digests
            ),
            semantic_protocol_cid=SEMANTIC_PROTOCOL_V2_CID,
        )
        namespace = _symai_cache_namespace(request)
        key = _symai_cache_key(
            request,
            config,
            namespace,
            {"context_cid": context_cid},
        )
    except (ProtocolContractError, TypeError, ValueError) as exc:
        raise SemanticQualityError(
            "SyMAI cache-key source reconstruction failed"
        ) from exc
    if (
        cache.get("namespace") != namespace
        or cache.get("key") != key
        or cache.get("mode") != stage.cache_mode.value
        or stage.provenance.effective_identity.get("cache_namespace")
        != namespace
        or stage.provenance.effective_identity.get("cache_key") != key
    ):
        raise SemanticQualityError(
            "SyMAI cache namespace/key differs from its label-blind preimage"
        )
    preimage = {
        "schema": SEMANTIC_PROMPT_SCHEMA_V2,
        "namespace": namespace,
        "case_id": stage.case_id,
        "source_cid": request.source_cid,
        "semantic_context_cid": context_cid,
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "semantic_prompt_cid": SEMANTIC_PROMPT_V2_CID,
        "semantic_response_schema_cid": (
            SEMANTIC_RESPONSE_SCHEMA_V2_CID
        ),
        "semantic_producer_registry_cid": (
            SEMANTIC_PRODUCER_REGISTRY_V2_CID
        ),
        "provider": provider,
        "model": model,
        "inner_route": {
            key_name: value
            for key_name, value in zip(
                (
                    "resolved_provider_name",
                    "resolved_model_name",
                    "service_endpoint",
                    "routing_backend",
                ),
                inner,
                strict=True,
            )
        },
        "dry_run": dry_run,
    }
    return {
        "namespace": namespace,
        "key": key,
        "preimage_cid": cid_for_dag_json(preimage),
        "preimage": preimage,
        "requested_provider": provider,
        "requested_model": model,
        "effective_provider": effective_provider,
        "effective_model": effective_model,
        "inner_route": preimage["inner_route"],
        "source_only": True,
        "reviewed_answers_absent": True,
    }


def _label_blind_receipts(
    stages: Sequence[StageRecord],
    source_text: str,
) -> list[Mapping[str, object]]:
    receipts: list[Mapping[str, object]] = []
    for stage in stages:
        if stage.stage not in _FRONTEND_STAGES or not _stage_invoked(stage):
            continue
        validated = validate_source_only_semantic_input_v2(
            stage, source_text
        )
        body: dict[str, object] = {
            "stage": stage.stage.value,
            "stage_cid": cid_for_dag_json(_plain(stage.to_dict())),
            "requested_identity_cid": cid_for_dag_json(
                _plain(stage.provenance.requested_identity)
            ),
            "effective_identity_cid": cid_for_dag_json(
                _plain(stage.provenance.effective_identity)
            ),
            "environment_sha256": stage.provenance.environment_sha256,
            "input_envelope_cid": cid_for_dag_json({"text": source_text}),
            "input_sha256": validated["input_sha256"],
            "source_cid": validated["source_cid"],
            "semantic_protocol_cid": validated[
                "semantic_protocol_cid"
            ],
            "proof_context_cid": None,
            "reviewed_answers_absent": True,
            "cache_binding": None,
        }
        if stage.stage is StageName.SYMAI:
            body["cache_binding"] = _symai_cache_binding(
                stage, source_text
            )
        receipts.append(
            {**body, "receipt_cid": cid_for_dag_json(body)}
        )
    return receipts


def _derive_g201(
    *,
    target_manifest: Mapping[str, object],
    targets: Sequence[SemanticCalibrationTargetV2],
    plans: Sequence[AblationPlan],
    results: Sequence[CaseResultRecord],
) -> dict[str, object]:
    catalog = {target.case_id: target for target in targets}
    routes = _routes()
    if (
        len(plans) != 2
        or {plan.split for plan in plans}
        != {Split.PILOT, Split.DEVELOPMENT}
        or any(len(plan.case_ids) != 10 for plan in plans)
    ):
        raise SemanticQualityError(
            "G201 requires exact ten-case pilot and development plans"
        )
    shared = {
        (
            plan.run_id,
            plan.case_manifest_sha256,
            plan.environment_sha256,
            plan.registry_sha256,
            frozenset(plan.variant_ids),
            tuple(mode.value for mode in plan.cache_modes),
        )
        for plan in plans
    }
    if (
        len(shared) != 1
        or any(plan.environment_sha256 is None for plan in plans)
        or any(plan.registry_sha256 != VARIANT_REGISTRY_SHA256 for plan in plans)
        or any(
            frozenset(plan.variant_ids)
            != _REQUIRED_CALIBRATION_VARIANTS
            or tuple(plan.cache_modes) != (CacheMode.COLD,)
            or plan.holdout_access_log_id is not None
            for plan in plans
        )
        or any(
            plan.case_manifest_sha256
            != target_manifest.get("case_manifest_sha256")
            for plan in plans
        )
    ):
        raise SemanticQualityError(
            "G201 plans do not share the frozen source/environment/matrix"
        )
    split_identities = _mapping(
        target_manifest.get("reviewed_split_identities"),
        "reviewed split identities",
    )
    plan_by_split = {plan.split.value: plan for plan in plans}
    for split, plan in plan_by_split.items():
        identity = _mapping(
            split_identities[split], f"{split} split identity"
        )
        if tuple(_array(identity.get("case_ids"), "case_ids")) != plan.case_ids:
            raise SemanticQualityError(
                f"G201 {split} plan order differs from reviewed targets"
            )
    all_plan_case_ids = {
        case_id for plan in plans for case_id in plan.case_ids
    }
    if all_plan_case_ids != set(catalog):
        raise SemanticQualityError(
            "G201 plans differ from the reviewed target population"
        )

    jobs: dict[
        tuple[str, str, str, str], tuple[AblationPlan, object]
    ] = {}
    for plan in plans:
        for job in plan.jobs:
            coordinate = _plan_coordinate(
                plan,
                job.case_id,
                job.variant_id,
                job.cache_mode.value,
            )
            if coordinate in jobs:
                raise SemanticQualityError(
                    "G201 plans contain duplicate source coordinates"
                )
            target = catalog.get(job.case_id)
            if (
                target is None
                or not isinstance(job.input_data, Mapping)
                or set(job.input_data) != {"text"}
                or job.input_data.get("text") != target.source_text
            ):
                raise SemanticQualityError(
                    "G201 producer job is not the exact label-blind source "
                    "envelope"
                )
            jobs[coordinate] = (plan, job)
    if len(jobs) != SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2:
        raise SemanticQualityError(
            "G201 plans do not form the exact 100-coordinate matrix"
        )

    result_index: dict[
        tuple[str, str, str, str], CaseResultRecord
    ] = {}
    for result in results:
        coordinate = _result_coordinate(result)
        if coordinate in result_index:
            raise SemanticQualityError(
                "G201 contains duplicate source result coordinates"
            )
        result_index[coordinate] = result
    if set(result_index) != set(jobs):
        raise SemanticQualityError(
            "G201 source results do not cover the exact planned matrix"
        )

    source_coordinates: list[dict[str, object]] = []
    calibration_coordinates: list[SemanticCalibrationCoordinateV2] = []
    target_manifest_cid = str(target_manifest["target_manifest_cid"])
    for case_id in sorted(catalog):
        target = catalog[case_id]
        for producer_id in SEMANTIC_PRODUCER_IDS_V2:
            route = routes[producer_id]
            variant_id = str(route["variant_id"])
            coordinate_key = (
                next(
                    plan.split.value
                    for plan in plans
                    if case_id in plan.case_ids
                ),
                case_id,
                variant_id,
                "cold",
            )
            plan, job = jobs[coordinate_key]
            result = result_index[coordinate_key]
            if (
                result.run_id != plan.run_id
                or result.protocol_sha256 != plan.protocol_sha256
                or result.case_manifest_sha256
                != plan.case_manifest_sha256
                or result.split is not plan.split
                or result.variant_id != job.variant_id
                or result.cache_mode is not job.cache_mode
                or result.case_id != job.case_id
                or any(
                    stage.provenance.environment_sha256
                    != plan.environment_sha256
                    for stage in result.stages
                )
            ):
                raise SemanticQualityError(
                    "G201 result identity differs from its scheduled source"
                )
            definition = VARIANT_REGISTRY[variant_id]
            if any(
                stage.stage not in definition.stages
                for stage in result.stages
            ):
                raise SemanticQualityError(
                    "G201 result contains a stage outside its frozen route"
                )
            prefix = tuple(str(item) for item in route["stage_prefix"])
            selected = tuple(result.stages[: len(prefix)])
            if (
                tuple(stage.stage.value for stage in selected) != prefix
                or selected[-1].stage.value != route["selected_stage"]
                or any(not _stage_invoked(stage) for stage in selected)
            ):
                raise SemanticQualityError(
                    "G201 result lacks the exact invoked calibration prefix"
                )
            expected_upstream: tuple[str, ...] = ()
            for stage in selected:
                if (
                    stage.provenance.upstream_stage_digests
                    != expected_upstream
                ):
                    raise SemanticQualityError(
                        "G201 selected stage prefix has a broken digest chain"
                    )
                requested = definition.requested_identity(stage.stage)
                if any(
                    stage.provenance.requested_identity.get(key)
                    != _plain(value)
                    for key, value in requested.items()
                ):
                    raise SemanticQualityError(
                        "G201 requested route identity drifted"
                    )
                expected_upstream = (*expected_upstream, stage.digest)
            if any(
                _stage_invoked(stage)
                for stage in result.stages
                if stage.stage in _PROOF_STAGES
            ):
                raise SemanticQualityError(
                    "G201 semantic calibration invoked a proof stage"
                )
            label_blind = _label_blind_receipts(
                result.stages, target.source_text
            )
            binding = SemanticCalibrationGraphBindingV2(
                plan_cid=cid_for_dag_json(_plain(plan.to_dict())),
                plan_sha256=plan.digest,
                case_result_cid=cid_for_dag_json(
                    _plain(result.to_dict())
                ),
                case_result_sha256=result.digest,
                run_id=result.run_id,
                variant_id=result.variant_id,
                split=result.split.value,
                cache_mode=result.cache_mode.value,
                environment_sha256=str(plan.environment_sha256),
                case_manifest_sha256=result.case_manifest_sha256,
                producer_registry_cid=SEMANTIC_PRODUCER_REGISTRY_V2_CID,
                calibration_route_manifest_cid=(
                    SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID
                ),
                calibration_metric_spec_cid=(
                    SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID
                ),
                reviewed_target_source_cid=(
                    SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID
                ),
                reviewed_target_manifest_cid=target_manifest_cid,
                proof_stages_suppressed=True,
            )
            semantic_coordinate = SemanticCalibrationCoordinateV2(
                case_id=case_id,
                producer_id=producer_id,
                stages=selected,
                graph_binding=binding,
            )
            observation = _evaluate_semantic_calibration_coordinate_v2(
                target,
                semantic_coordinate,
                validated_ablation_graph=True,
            )
            calibration_coordinates.append(semantic_coordinate)
            source_body: dict[str, object] = {
                "schema": G201_SEMANTIC_SOURCE_COORDINATE_SCHEMA_V2,
                "case_id": case_id,
                "producer_id": producer_id,
                "split": result.split.value,
                "cache_mode": result.cache_mode.value,
                "variant_id": variant_id,
                "variant_profile_cid": cid_for_dag_json(
                    _plain(definition.to_dict())
                ),
                "protocol_identities": _protocol_identities(),
                "target_manifest_cid": target_manifest_cid,
                "target_source_cid": target.source_cid,
                "plan_cid": binding.plan_cid,
                "case_result_cid": binding.case_result_cid,
                "coordinate": {
                    "case_id": semantic_coordinate.case_id,
                    "producer_id": semantic_coordinate.producer_id,
                    "stages": [
                        _plain(stage.to_dict())
                        for stage in semantic_coordinate.stages
                    ],
                    "graph_binding": binding.to_dict(),
                },
                "label_blind_input_receipts": label_blind,
                "reviewed_answers_in_producer_inputs_or_cache_keys": False,
                "legacy_sha256_joins_authoritative": False,
                "semantic_observation": _plain(observation),
            }
            source_coordinates.append(
                {
                    **source_body,
                    "coordinate_cid": cid_for_dag_json(source_body),
                }
            )
    if (
        len(source_coordinates)
        != SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2
    ):
        raise SemanticQualityError(
            "G201 did not derive every semantic calibration coordinate"
        )
    report = _evaluate_semantic_calibration_v2(
        targets=targets,
        coordinates=calibration_coordinates,
        validated_ablation_graph=True,
        reviewed_target_manifest=target_manifest,
    )
    coverage = _mapping(report.get("coverage"), "G201 report coverage")
    if (
        report.get("status") != "complete"
        or coverage.get("coordinate_coverage_complete") is not True
        or coverage.get("validated_ablation_graph_coverage_complete")
        is not True
        or coverage.get("field_coverage_complete") is not True
        or coverage.get("quality_coordinate_complete") is not True
    ):
        raise SemanticQualityError(
            "G201 source evidence did not produce a complete calibration"
        )
    return {
        "protocol_identities": _protocol_identities(),
        "plan_cids": [
            cid_for_dag_json(_plain(plan.to_dict()))
            for plan in plans
        ],
        "case_result_cids": [
            cid_for_dag_json(_plain(result.to_dict()))
            for result in results
        ],
        "source_coordinates": source_coordinates,
        "source_coordinate_cids": [
            str(item["coordinate_cid"]) for item in source_coordinates
        ],
        "calibration_report": _plain(report),
        "calibration_report_cid": str(report["artifact_cid"]),
        "source_recomputed": True,
        "label_blind_producer_inputs": True,
        "legacy_manifest_sha256_joins_authoritative": False,
        "holdout_accessed": False,
    }


@dataclass(frozen=True, slots=True)
class G201SemanticEvidenceIndexV2:
    """Portable full-source index for the bounded G201 semantic lane."""

    target_manifest: Mapping[str, object]
    targets: tuple[SemanticCalibrationTargetV2, ...]
    plans: tuple[AblationPlan, ...]
    results: tuple[CaseResultRecord, ...]
    schema: str = G201_SEMANTIC_EVIDENCE_INDEX_SCHEMA_V2
    _derived: Mapping[str, object] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.schema != G201_SEMANTIC_EVIDENCE_INDEX_SCHEMA_V2:
            raise SemanticQualityError(
                "unsupported G201 semantic evidence index schema"
            )
        try:
            targets = tuple(
                item
                if isinstance(item, SemanticCalibrationTargetV2)
                else SemanticCalibrationTargetV2.from_dict(item)
                for item in self.targets
            )
            targets = tuple(sorted(targets, key=lambda item: item.case_id))
            plans = tuple(
                sorted(
                    (
                        AblationPlan.from_dict(_plain(item.to_dict()))
                        if isinstance(item, AblationPlan)
                        else AblationPlan.from_dict(item)
                        for item in self.plans
                    ),
                    key=lambda item: item.split.value,
                )
            )
            results = tuple(
                sorted(
                    (
                        CaseResultRecord.from_dict(_plain(item.to_dict()))
                        if isinstance(item, CaseResultRecord)
                        else CaseResultRecord.from_dict(item)
                        for item in self.results
                    ),
                    key=_result_coordinate,
                )
            )
        except (
            AblationValidationError,
            ProtocolContractError,
            SemanticReassessmentError,
            TypeError,
            ValueError,
            KeyError,
        ) as exc:
            raise SemanticQualityError(
                "G201 semantic evidence source failed strict parsing"
            ) from exc
        manifest = _target_manifest(self.target_manifest, targets)
        derived = _derive_g201(
            target_manifest=manifest,
            targets=targets,
            plans=plans,
            results=results,
        )
        object.__setattr__(self, "target_manifest", manifest)
        object.__setattr__(self, "targets", targets)
        object.__setattr__(self, "plans", plans)
        object.__setattr__(self, "results", results)
        object.__setattr__(self, "_derived", _freeze(derived))

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "target_manifest": _plain(self.target_manifest),
            "targets": [target.to_dict() for target in self.targets],
            "plans": [_plain(plan.to_dict()) for plan in self.plans],
            "results": [_plain(result.to_dict()) for result in self.results],
            **_plain(self._derived),  # type: ignore[arg-type]
        }

    @property
    def index_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    @property
    def calibration_report(self) -> Mapping[str, object]:
        return _mapping(
            self._derived["calibration_report"],
            "G201 calibration report",
        )

    @property
    def absolute_quality_passed(self) -> bool:
        absolute = _mapping(
            self.calibration_report.get("absolute_quality_gate"),
            "G201 absolute quality gate",
        )
        return absolute.get("passed") is True

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "index_cid": self.index_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G201 semantic evidence index")
        expected = {
            "schema",
            "target_manifest",
            "targets",
            "plans",
            "results",
            "protocol_identities",
            "plan_cids",
            "case_result_cids",
            "source_coordinates",
            "source_coordinate_cids",
            "calibration_report",
            "calibration_report_cid",
            "source_recomputed",
            "label_blind_producer_inputs",
            "legacy_manifest_sha256_joins_authoritative",
            "holdout_accessed",
            "index_cid",
        }
        _exact(data, expected, "G201 semantic evidence index")
        result = cls(
            schema=data["schema"],  # type: ignore[arg-type]
            target_manifest=_mapping(
                data["target_manifest"], "target_manifest"
            ),
            targets=tuple(
                SemanticCalibrationTargetV2.from_dict(item)
                for item in _array(data["targets"], "targets")
            ),
            plans=tuple(
                AblationPlan.from_dict(item)
                for item in _array(data["plans"], "plans")
            ),
            results=tuple(
                CaseResultRecord.from_dict(item)
                for item in _array(data["results"], "results")
            ),
        )
        if _plain(data) != result.to_dict():
            raise SemanticQualityError(
                "G201 semantic evidence index did not source-recompute"
            )
        return result


def build_g201_semantic_evidence_index_v2(
    *,
    target_manifest: Mapping[str, object],
    targets: Sequence[SemanticCalibrationTargetV2 | Mapping[str, object]],
    plans: Sequence[AblationPlan],
    results: Sequence[CaseResultRecord],
) -> G201SemanticEvidenceIndexV2:
    """Build a portable G201 index from complete source records."""

    return G201SemanticEvidenceIndexV2(
        target_manifest=target_manifest,
        targets=tuple(
            target
            if isinstance(target, SemanticCalibrationTargetV2)
            else SemanticCalibrationTargetV2.from_dict(target)
            for target in targets
        ),
        plans=tuple(plans),
        results=tuple(results),
    )


def validate_g201_semantic_evidence_index_v2(
    value: object,
) -> G201SemanticEvidenceIndexV2:
    """Replay every source value; derived reports and CIDs have no authority."""

    if isinstance(value, G201SemanticEvidenceIndexV2):
        value = value.to_dict()
    try:
        return G201SemanticEvidenceIndexV2.from_dict(value)
    except SemanticQualityError:
        raise
    except (
        AblationValidationError,
        ProtocolContractError,
        SemanticReassessmentError,
        TypeError,
        ValueError,
        KeyError,
    ) as exc:
        raise SemanticQualityError(
            "G201 semantic evidence index failed source replay"
        ) from exc


def _runtime_producer(
    stages: Sequence[StageRecord],
) -> tuple[str, tuple[StageRecord, ...]]:
    frontends = tuple(
        stage
        for stage in stages
        if stage.stage in _FRONTEND_STAGES and _stage_invoked(stage)
    )
    if not frontends:
        raise SemanticQualityError(
            "runtime coordinate contains no invoked semantic frontend"
        )
    terminal = frontends[-1]
    if terminal.stage is StageName.COMPILER:
        producer_id = "compiler"
    elif terminal.stage is StageName.SYMAI:
        producer_id = "symai"
    else:
        producer_id = {
            "full_model": "spacy_full_model",
            "regex_legal": "spacy_regex_legal",
            "blank_model": "spacy_blank_model",
        }.get(terminal.provenance.effective_identity.get("mode"), "")
    if producer_id not in SEMANTIC_PRODUCER_IDS_V2:
        raise SemanticQualityError(
            "runtime frontend producer identity is not registered"
        )
    terminal_index = tuple(stages).index(terminal)
    prefix = tuple(stages[: terminal_index + 1])
    if any(
        stage.stage in _FRONTEND_STAGES
        and not _stage_invoked(stage)
        for stage in prefix
    ):
        raise SemanticQualityError(
            "runtime semantic prefix contains a suppressed frontend"
        )
    return producer_id, prefix


def _runtime_observation(
    *,
    index: G201SemanticEvidenceIndexV2,
    matrix: G210RuntimeReceiptMatrixV2,
    evidence: object | None,
    expected_split: str,
    expected_case_id: str,
    expected_variant_id: str,
    expected_cache_mode: str,
) -> Mapping[str, object]:
    target = next(
        (
            item
            for item in index.targets
            if item.case_id == expected_case_id
        ),
        None,
    )
    manifest_entry = next(
        (
            _mapping(item, "reviewed target case")
            for item in _array(
                index.target_manifest.get("cases"),
                "reviewed target cases",
            )
            if isinstance(item, Mapping)
            and item.get("case_id") == expected_case_id
        ),
        None,
    )
    environments = {
        plan.environment_sha256 for plan in index.plans
    }
    if len(environments) != 1 or None in environments:
        raise SemanticQualityError(
            "G201 index does not expose one exact environment identity"
        )
    expected_environment = next(iter(environments))
    expected_manifest_sha256 = index.target_manifest.get(
        "case_manifest_sha256"
    )
    failures: list[str] = []
    semantic_receipt: Mapping[str, object] | None = None
    label_blind: list[Mapping[str, object]] = []
    runtime_receipt_cid: str | None = None
    case_result_cid: str | None = None
    producer_id: str | None = None
    result: CaseResultRecord | None = None
    source_cid: str | None = None if target is None else target.source_cid
    if target is None:
        failures.append("reviewed_target_missing")
    elif manifest_entry is None or manifest_entry.get("split") != expected_split:
        failures.append("reviewed_target_split_identity_mismatch")
    if evidence is None:
        failures.append("runtime_coordinate_missing")
    else:
        runtime_receipt_cid = str(getattr(evidence, "receipt_cid"))
        raw_result = getattr(evidence, "case_result", None)
        if isinstance(raw_result, CaseResultRecord):
            result = raw_result
            case_result_cid = cid_for_dag_json(
                _plain(result.to_dict())
            )
        else:
            failures.append("runtime_case_result_missing")
    if result is not None and target is not None:
        source_text = getattr(evidence, "source_text", None)
        compiler_exposure = getattr(evidence, "compiler_exposure", None)
        if (
            result.split.value != expected_split
            or result.case_id != expected_case_id
            or result.variant_id != expected_variant_id
            or result.cache_mode.value != expected_cache_mode
            or result.case_manifest_sha256 != expected_manifest_sha256
            or source_text != target.source_text
            or getattr(compiler_exposure, "source_cid", None)
            != target.source_cid
            or {
                stage.provenance.environment_sha256
                for stage in result.stages
            }
            != {expected_environment}
        ):
            failures.append("runtime_source_or_coordinate_identity_mismatch")
        else:
            try:
                producer_id, prefix = _runtime_producer(result.stages)
                definition = VARIANT_REGISTRY[expected_variant_id]
                if (
                    any(
                        stage.stage in _FRONTEND_STAGES
                        and stage.stage not in definition.stages
                        for stage in result.stages
                    )
                    or any(
                        stage.provenance.requested_identity.get(key)
                        != _plain(value)
                        for stage in prefix
                        for key, value in definition.requested_identity(
                            stage.stage
                        ).items()
                    )
                ):
                    raise SemanticQualityError(
                        "runtime semantic route identity drifted"
                    )
                label_blind = _label_blind_receipts(
                    prefix, target.source_text
                )
                semantic_receipt = (
                    _evaluate_semantic_calibration_coordinate_v2(
                        target,
                        SemanticCalibrationCoordinateV2(
                            case_id=target.case_id,
                            producer_id=producer_id,
                            stages=prefix,
                        ),
                        validated_ablation_graph=False,
                    )
                )
            except (
                SemanticQualityError,
                SemanticReassessmentError,
                ProtocolContractError,
                TypeError,
                ValueError,
                KeyError,
            ):
                failures.append("runtime_semantic_source_replay_failed")
    measured = bool(
        semantic_receipt is not None
        and semantic_receipt.get("quality_millionths") is not None
    )
    if semantic_receipt is not None:
        if semantic_receipt.get("projection_available") is not True:
            failures.append("runtime_semantic_projection_missing")
        if semantic_receipt.get("projection_nonvacuous") is not True:
            failures.append("runtime_semantic_projection_vacuous")
    definition = VARIANT_REGISTRY[expected_variant_id]
    body: dict[str, object] = {
        "schema": G235_RUNTIME_SEMANTIC_OBSERVATION_SCHEMA_V2,
        "g201_index_cid": index.index_cid,
        "g210_runtime_matrix_cid": matrix.runtime_matrix_cid,
        "protocol_identities": _protocol_identities(),
        "split": expected_split,
        "case_id": expected_case_id,
        "variant_id": expected_variant_id,
        "cache_mode": expected_cache_mode,
        "variant_profile_cid": cid_for_dag_json(
            _plain(definition.to_dict())
        ),
        "source_cid": source_cid,
        "runtime_receipt_cid": runtime_receipt_cid,
        "case_result_cid": case_result_cid,
        "producer_id": producer_id,
        "label_blind_input_receipts": label_blind,
        "reviewed_answers_in_producer_inputs_or_cache_keys": False,
        "semantic_receipt": (
            None if semantic_receipt is None else _plain(semantic_receipt)
        ),
        "quality_millionths": (
            None
            if semantic_receipt is None
            else semantic_receipt.get("quality_millionths")
        ),
        "projection_nonvacuous": (
            None
            if semantic_receipt is None
            else semantic_receipt.get("projection_nonvacuous")
        ),
        "validation_error_precedence_applied": (
            None
            if semantic_receipt is None
            else semantic_receipt.get(
                "validation_error_precedence_applied"
            )
        ),
        "validation_error_precedence_verified": (
            semantic_receipt is not None
            and type(
                semantic_receipt.get(
                    "validation_error_precedence_applied"
                )
            )
            is bool
        ),
        "measured": measured,
        "failure_codes": sorted(set(failures)),
        "holdout_accessed": False,
    }
    return {**body, "observation_cid": cid_for_dag_json(body)}


def _arm_metrics(
    variant_id: str,
    observations: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    rows = [
        row for row in observations if row["variant_id"] == variant_id
    ]
    measured = [row for row in rows if row["measured"] is True]
    values = [
        int(row["quality_millionths"])
        for row in measured
        if row["quality_millionths"] is not None
    ]
    complete = len(rows) == len(measured) == len(values)
    quality_millionths = (
        None if not complete else sum(values) // len(values)
    )
    body: dict[str, object] = {
        "variant_id": variant_id,
        "variant_profile_cid": cid_for_dag_json(
            _plain(VARIANT_REGISTRY[variant_id].to_dict())
        ),
        "scheduled_coordinate_count": len(rows),
        "measured_coordinate_count": len(measured),
        "missing_coordinate_count": len(rows) - len(measured),
        "semantic_quality_millionths": quality_millionths,
        "semantic_quality_rate": (
            None
            if not complete
            else int(quality_millionths) / 1_000_000
        ),
        "absolute_quality_minimum_millionths": (
            SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2
        ),
        "absolute_quality_passed": bool(
            quality_millionths is not None
            and quality_millionths
            >= SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2
        ),
        "nonvacuous_coordinate_count": sum(
            row["projection_nonvacuous"] is True for row in rows
        ),
        "validation_error_precedence_verified_count": sum(
            row["validation_error_precedence_verified"] is True
            for row in rows
        ),
        "validation_error_precedence_applied_count": sum(
            row["validation_error_precedence_applied"] is True
            for row in rows
        ),
        "complete": complete,
    }
    return {**body, "metrics_cid": cid_for_dag_json(body)}


def build_g235_semantic_quality_gate_v2(
    index: G201SemanticEvidenceIndexV2,
    matrix: G210RuntimeReceiptMatrixV2,
    candidate_variant_ids: Sequence[str],
) -> Mapping[str, object]:
    """Recompute G201 calibration and every selected G210 semantic output."""

    source_index = validate_g201_semantic_evidence_index_v2(index)
    if not isinstance(matrix, G210RuntimeReceiptMatrixV2):
        raise SemanticQualityError(
            "G235 requires a G210RuntimeReceiptMatrixV2"
        )
    try:
        matrix = G210RuntimeReceiptMatrixV2.from_dict(matrix.to_dict())
    except (RevisedPilotAuthorizationError, TypeError, ValueError) as exc:
        raise SemanticQualityError(
            "G235 runtime matrix failed source replay"
        ) from exc
    candidates = tuple(candidate_variant_ids)
    if (
        not candidates
        or len(set(candidates)) != len(candidates)
        or any(
            not isinstance(item, str)
            or item not in VARIANT_REGISTRY
            or item in {"A0", "S1"}
            or VARIANT_REGISTRY[item].paired_against != "A0"
            or VARIANT_REGISTRY[item].primary_candidate is not True
            or VARIANT_REGISTRY[item].safety_diagnostic_only is True
            for item in candidates
        )
    ):
        raise SemanticQualityError(
            "G235 candidates must be distinct frozen primary A0-paired arms"
        )
    candidate_set = set(candidates)
    candidates = tuple(
        variant_id
        for variant_id in G210_VARIANT_IDS
        if variant_id in candidate_set
    )
    selected = ("A0", *candidates)
    evidence_by_coordinate = {
        (
            item.case_result.split.value,
            item.case_result.case_id,
            item.case_result.variant_id,
            item.case_result.cache_mode.value,
        ): item
        for item in matrix.runtime_evidence
    }
    expected_coordinates: list[tuple[str, str, str, str]] = []
    for manifest in matrix.receipt_matrix.rescue_manifests:
        for rescue_case in manifest.cases:
            split = rescue_case.split.value
            if split not in G210_SPLITS:
                raise SemanticQualityError(
                    "G235 runtime matrix contains a non-selection split"
                )
            for variant_id in selected:
                for cache_mode in G210_CACHE_MODES:
                    expected_coordinates.append(
                        (
                            split,
                            rescue_case.case_id,
                            variant_id,
                            cache_mode,
                        )
                    )
    observations = [
        _runtime_observation(
            index=source_index,
            matrix=matrix,
            evidence=evidence_by_coordinate.get(coordinate),
            expected_split=coordinate[0],
            expected_case_id=coordinate[1],
            expected_variant_id=coordinate[2],
            expected_cache_mode=coordinate[3],
        )
        for coordinate in sorted(expected_coordinates)
    ]
    metrics = [
        _arm_metrics(variant_id, observations)
        for variant_id in selected
    ]
    failures: list[str] = []
    if not source_index.absolute_quality_passed:
        failures.append("g201_absolute_quality_condition_failed")
    if not matrix.complete:
        failures.append("g210_runtime_matrix_incomplete")
    if len(observations) != len(expected_coordinates) or any(
        row["runtime_receipt_cid"] is None for row in observations
    ):
        failures.append("runtime_semantic_population_incomplete")
    if any(row["source_cid"] is None for row in observations):
        failures.append("reviewed_runtime_target_missing")
    if any(row["failure_codes"] for row in observations):
        failures.append("runtime_semantic_source_replay_failed")
    if any(metric["complete"] is not True for metric in metrics):
        failures.append("runtime_semantic_measurement_incomplete")
    if any(
        metric["nonvacuous_coordinate_count"]
        != metric["scheduled_coordinate_count"]
        for metric in metrics
    ):
        failures.append("runtime_semantic_nonvacuity_failed")
    if any(
        metric["validation_error_precedence_verified_count"]
        != metric["scheduled_coordinate_count"]
        for metric in metrics
    ):
        failures.append(
            "runtime_validation_error_precedence_coverage_incomplete"
        )
    if any(metric["absolute_quality_passed"] is not True for metric in metrics):
        failures.append("runtime_arm_absolute_quality_failed")
    incomplete_codes = {
        "g210_runtime_matrix_incomplete",
        "runtime_semantic_population_incomplete",
        "reviewed_runtime_target_missing",
        "runtime_semantic_measurement_incomplete",
    }
    status = (
        "incomplete"
        if incomplete_codes.intersection(failures)
        else ("failed" if failures else "passed")
    )
    body: dict[str, object] = {
        "schema": G235_SEMANTIC_QUALITY_GATE_SCHEMA_V2,
        "gate_id": "semantic_quality",
        "g201_index_cid": source_index.index_cid,
        "g201_calibration_report_cid": source_index.calibration_report[
            "artifact_cid"
        ],
        "g210_runtime_matrix_cid": matrix.runtime_matrix_cid,
        "protocol_identities": _protocol_identities(),
        "candidate_variant_ids": list(candidates),
        "selected_variant_ids": list(selected),
        "expected_coordinate_count": len(expected_coordinates),
        "observed_coordinate_count": len(observations),
        "status": status,
        "complete": status != "incomplete",
        "passed": status == "passed",
        "failure_codes": sorted(set(failures)),
        "absolute_quality_condition": _plain(
            source_index.calibration_report["absolute_quality_gate"]
        ),
        "runtime_arm_absolute_quality_minimum_millionths": (
            SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2
        ),
        "per_arm_metrics": metrics,
        "observations": observations,
        "source_recomputed": True,
        "missing_is_never_zero": True,
        "validation_error_precedence_enforced": True,
        "reviewed_answers_in_producer_inputs_or_cache_keys": False,
        "legacy_manifest_sha256_joins_authoritative": False,
        "holdout_accessed": False,
        "production_promotion_authorized": False,
    }
    return _freeze(
        {**body, "receipt_cid": cid_for_dag_json(body)}
    )  # type: ignore[return-value]


def validate_g235_semantic_quality_gate_v2(
    value: object,
    index: G201SemanticEvidenceIndexV2,
    matrix: G210RuntimeReceiptMatrixV2,
) -> Mapping[str, object]:
    """Rebuild G235 from full G201/G210 sources and compare every field."""

    data = _mapping(value, "G235 semantic quality gate")
    expected = {
        "schema",
        "gate_id",
        "g201_index_cid",
        "g201_calibration_report_cid",
        "g210_runtime_matrix_cid",
        "protocol_identities",
        "candidate_variant_ids",
        "selected_variant_ids",
        "expected_coordinate_count",
        "observed_coordinate_count",
        "status",
        "complete",
        "passed",
        "failure_codes",
        "absolute_quality_condition",
        "runtime_arm_absolute_quality_minimum_millionths",
        "per_arm_metrics",
        "observations",
        "source_recomputed",
        "missing_is_never_zero",
        "validation_error_precedence_enforced",
        "reviewed_answers_in_producer_inputs_or_cache_keys",
        "legacy_manifest_sha256_joins_authoritative",
        "holdout_accessed",
        "production_promotion_authorized",
        "receipt_cid",
    }
    _exact(data, expected, "G235 semantic quality gate")
    candidates = tuple(
        str(item)
        for item in _array(
            data.get("candidate_variant_ids"),
            "G235 candidate_variant_ids",
        )
    )
    rebuilt = build_g235_semantic_quality_gate_v2(
        index, matrix, candidates
    )
    if _plain(data) != _plain(rebuilt):
        raise SemanticQualityError(
            "G235 semantic quality gate did not source-recompute"
        )
    return rebuilt


__all__ = [
    "G201_SEMANTIC_EVIDENCE_INDEX_SCHEMA_V2",
    "G201_SEMANTIC_PREFLIGHT_PLAN_SCHEMA_V2",
    "G201_SEMANTIC_SOURCE_COORDINATE_SCHEMA_V2",
    "G201SemanticEvidenceIndexV2",
    "G235_RUNTIME_SEMANTIC_OBSERVATION_SCHEMA_V2",
    "G235_SEMANTIC_QUALITY_GATE_SCHEMA_V2",
    "HSSLEV2350C27",
    "SemanticQualityError",
    "build_g201_semantic_evidence_index_v2",
    "build_g201_semantic_preflight_plan_v2",
    "build_g235_semantic_quality_gate_v2",
    "validate_g201_semantic_evidence_index_v2",
    "validate_g235_semantic_quality_gate_v2",
]
