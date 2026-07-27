"""Qualification and frozen scheduling for the SRT replacement matrix.

This module is deliberately additive.  It does not change the historical
thirty-cell plan, fixture, scoring contract, or SRT-014 evidence.  Instead it
binds the repaired adapters and every external capability to exact CIDs,
performs non-scored contract smokes, records unsupported products explicitly,
and freezes the complete replacement schedule before scored execution.

The model recovery boundary is intentionally role-aware.  The core matrix
calls the same constructor for both L1 and L2 and gives both calls the same
configuration, so a model adapter cannot infer the role safely (and an L2 call
can be skipped after a realizer failure).  :class:`RoleAwareModelRecovery`
therefore exposes distinct ``construct_l1`` and ``construct_l2`` methods; L2
requires the exact preceding L1 as polarity authority.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import threading
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)
from benchmarks.semantic_roundtrip.constructors.causal_autoencoder_guidance import (
    CAUSAL_AUTOENCODER_GUIDANCE_INTERFACE,
    UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER,
    load_causal_guidance_qualification,
)
from benchmarks.semantic_roundtrip.constructors.leanstral import LeanstralClient
from benchmarks.semantic_roundtrip.constructors.modal_spacy import (
    MODAL_SPACY_CANONICAL_CONSTRUCTOR_INTERFACE,
    ModalSpacyCanonicalConstructor,
)
from benchmarks.semantic_roundtrip.constructors.symai import SyMAIClient
from benchmarks.semantic_roundtrip.constructors.typed_deontic import (
    TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE,
    TypedDeonticCanonicalConstructor,
)
from benchmarks.semantic_roundtrip.contracts import (
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    ContractError,
    FailureReason,
    RealizerRequest,
    RealizerResult,
    RoundTripResult,
)
from benchmarks.semantic_roundtrip.extended_matrix import (
    DEFAULT_EXTENDED_MATRIX_PLAN,
    CompositionSpec,
    GuidanceMode,
    ModelRoute,
    RealizerMode,
    RealizerSpec,
    RepairMode,
)
from benchmarks.semantic_roundtrip.matrix import (
    MatrixCase,
    SemanticRoundTripMatrix,
    PostHocValidator,
    default_post_hoc_validators,
    load_matrix_cases,
    polarity_diagnostics,
    source_copy_diagnostics,
)
from benchmarks.semantic_roundtrip.metrics import make_round_trip_result
from benchmarks.semantic_roundtrip.model_output_recovery import (
    BOUNDED_MODEL_OUTPUT_RECOVERY_INTERFACE,
    MODEL_OUTPUT_RECOVERY_SCHEMA_VERSION,
    PREREGISTERED_SRT023_POLICY,
    SYMAI_POLARITY_CONTRACT_INTERFACE,
    BoundedModelOutputRecovery,
    ModelOutputRecoveryResult,
    RecoveryRole,
    RecoveryRoute,
    SyMAIPolarityContract,
)
from benchmarks.semantic_roundtrip.realizers.source_withheld_paraphrase import (
    FROZEN_REPLACEMENT_CONFIG_CID,
    SOURCE_WITHHELD_CANONICAL_PARAPHRASER_INTERFACE,
    SOURCE_WITHHELD_PARAPHRASE_RENDERING_SPEC_CID,
    SourceWithheldCanonicalParaphraser,
    frozen_replacement_config,
)
from benchmarks.semantic_roundtrip.selective_repair import (
    SELECTIVE_LEANSTRAL_REPAIR_INTERFACE,
    SelectiveLeanstralRepair,
    SelectiveRepairPolicy,
)
from benchmarks.semantic_roundtrip_capabilities import (
    CapabilityInventory,
    load_inventory,
)


QUALIFIED_REPLACEMENT_MATRIX_INTERFACE: Final = (
    "QualifiedReplacementSemanticRoundTripMatrix@1"
)
REPLACEMENT_QUALIFICATION_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-replacement-qualification.v1"
)
ROLE_AWARE_MODEL_RECOVERY_INTERFACE: Final = "RoleAwareModelRecovery@1"
REPLACEMENT_COORDINATE_RUNNER_INTERFACE: Final = (
    "QualifiedReplacementCoordinateRunner@1"
)
REPLACEMENT_COORDINATE_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-replacement-coordinate.v1"
)
DEFAULT_REPLACEMENT_QUALIFICATION_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "replacement_capabilities.json"
)
DEFAULT_CAPABILITY_INVENTORY_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/capabilities.json"
)
DEFAULT_CAUSAL_QUALIFICATION_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "causal_autoencoder_guidance_qualification.json"
)
DEFAULT_FIXTURE_RELATIVE_PATH: Final = Path(
    "tests/fixtures/semantic_roundtrip/pilot_cases.json"
)
DEFAULT_PROTOCOL_RELATIVE_PATH: Final = Path(
    "docs/benchmarks/semantic_roundtrip_composition_protocol.md"
)
DEFAULT_SRT014_REPORT_RELATIVE_PATH: Final = Path(
    "docs/performance_snapshots/"
    "2026-07-26_semantic_roundtrip_composition_pilot.json"
)
DEFAULT_REMEDIATION_MANIFEST_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "no_eligible_remediation_manifest.json"
)
REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_REPLACEMENT_QUALIFICATION_PATH: Final = (
    REPO_ROOT / DEFAULT_REPLACEMENT_QUALIFICATION_RELATIVE_PATH
)

MODEL_REPEAT_COUNT: Final = 5
PHYSICAL_MODEL_SLOT_COUNT: Final = 1
PINNED_IPFS_ACCELERATE_GITLINK: Final = (
    "f979431ac5fe3c4a088a2f15ec6379fba48bbde6"
)
PINNED_SYMAI_ROUTER_SOURCE_CID: Final = (
    "bafkreigxv3z5osvvjjk5qhchno6tpcf6kbtivpg4iiwrel4ydyirxt5vce"
)
PINNED_SYMAI_ROUTER_SOURCE_PATH: Final = (
    "ipfs_accelerate_py/llm_router.py"
)
SELECTION_GATE_IDS: Final = (
    "source_copy_exclusion",
    "polarity_preservation",
    "full_coverage",
)
QUALIFIED_CANDIDATE = "qualified_candidate"
TERMINAL_UNSUPPORTED = "terminal_unsupported"
CAPABILITY_UNAVAILABLE = "capability_unavailable"
PENDING_SCORED_EXECUTION = "pending_scored_execution"
_REPLACEMENT_MODEL_LOCK: Final = threading.RLock()

_ADAPTER_SOURCES: Final[Mapping[str, tuple[str, str]]] = {
    "coordinate_runner": (
        REPLACEMENT_COORDINATE_RUNNER_INTERFACE,
        "benchmarks/semantic_roundtrip/replacement_matrix.py",
    ),
    "typed_deontic": (
        TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE,
        "benchmarks/semantic_roundtrip/constructors/typed_deontic.py",
    ),
    "modal_spacy": (
        MODAL_SPACY_CANONICAL_CONSTRUCTOR_INTERFACE,
        "benchmarks/semantic_roundtrip/constructors/modal_spacy.py",
    ),
    "source_withheld_paraphrase": (
        SOURCE_WITHHELD_CANONICAL_PARAPHRASER_INTERFACE,
        "benchmarks/semantic_roundtrip/realizers/"
        "source_withheld_paraphrase.py",
    ),
    "selective_repair": (
        SELECTIVE_LEANSTRAL_REPAIR_INTERFACE,
        "benchmarks/semantic_roundtrip/selective_repair.py",
    ),
    "model_output_recovery": (
        BOUNDED_MODEL_OUTPUT_RECOVERY_INTERFACE,
        "benchmarks/semantic_roundtrip/model_output_recovery.py",
    ),
    "causal_guidance": (
        CAUSAL_AUTOENCODER_GUIDANCE_INTERFACE,
        "benchmarks/semantic_roundtrip/constructors/"
        "causal_autoencoder_guidance.py",
    ),
    "extended_plan": (
        "ExtendedSemanticRoundTripMatrix@1",
        "benchmarks/semantic_roundtrip/extended_matrix.py",
    ),
    "semantic_contract": (
        "SemanticRoundTripContract@1",
        "benchmarks/semantic_roundtrip/contracts.py",
    ),
    "semantic_gates": (
        "SemanticRoundTripMatrix@1",
        "benchmarks/semantic_roundtrip/matrix.py",
    ),
}


class ReplacementQualificationError(ContractError):
    """Raised when replacement qualification evidence is incomplete or drifts."""


def _json_clone(value: object) -> Any:
    return json.loads(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _require_cid(value: object, *, codec: str, label: str) -> str:
    try:
        return validate_cid(value, codecs=(codec,))
    except (TypeError, ValueError) as exc:
        raise ReplacementQualificationError(
            f"{label} must be a canonical {codec} CID"
        ) from exc


def _cid_receipt(payload: Mapping[str, object], field: str) -> dict[str, object]:
    result = _json_clone(dict(payload))
    result[field] = cid_for_dag_json(result)
    return result


def _raw_file_binding(repo_root: Path, relative_path: Path | str) -> dict[str, object]:
    relative = Path(relative_path)
    path = repo_root / relative
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ReplacementQualificationError(
            f"cannot bind required file {relative.as_posix()}: "
            f"{type(exc).__name__}"
        ) from exc
    return {
        "path": relative.as_posix(),
        "raw_cid": cid_for_bytes(raw),
        "byte_count": len(raw),
    }


def _strict_object(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReplacementQualificationError(
            f"cannot load {label}: {type(exc).__name__}"
        ) from exc
    if not isinstance(value, dict):
        raise ReplacementQualificationError(f"{label} must be a JSON object")
    return value


def _capability_bindings(inventory: CapabilityInventory) -> dict[str, object]:
    records: dict[str, object] = {}
    for record in inventory.capabilities:
        payload = record.to_dict()
        records[record.id] = {
            **payload,
            "requested_identity_cid": cid_for_dag_json(
                payload["requested_identity"]
            ),
            "effective_identity_cid": (
                None
                if payload["effective_identity"] is None
                else cid_for_dag_json(payload["effective_identity"])
            ),
            "record_cid": cid_for_dag_json(payload),
        }
    return records


def _adapter_bindings(repo_root: Path) -> dict[str, object]:
    bindings: dict[str, object] = {}
    for adapter_id, (interface, source_path) in _ADAPTER_SOURCES.items():
        bindings[adapter_id] = {
            "interface": interface,
            **_raw_file_binding(repo_root, source_path),
        }
    selective_policy = SelectiveRepairPolicy().to_dict()
    model_policy = PREREGISTERED_SRT023_POLICY.to_dict()
    bindings["coordinate_runner"].update(  # type: ignore[union-attr]
        {
            "receipt_schema": REPLACEMENT_COORDINATE_RECEIPT_SCHEMA,
            "factory": "build_replacement_coordinate_runner",
            "coordinate_method": "run_coordinate",
            "coordinate_arguments": [
                "case",
                "cell_id",
                "repeat_index",
                "cache_namespace",
            ],
            "role_explicit": True,
            "retains_native_stage_receipts": True,
            "terminal_paths_assign_loss_one": True,
            "physical_model_slots": PHYSICAL_MODEL_SLOT_COUNT,
        }
    )
    bindings["source_withheld_paraphrase"].update(  # type: ignore[union-attr]
        {
            "configuration_cid": FROZEN_REPLACEMENT_CONFIG_CID,
            "rendering_spec_cid": (
                SOURCE_WITHHELD_PARAPHRASE_RENDERING_SPEC_CID
            ),
            "source_withheld": True,
        }
    )
    bindings["selective_repair"].update(  # type: ignore[union-attr]
        {
            "policy": selective_policy,
            "policy_cid": cid_for_dag_json(selective_policy),
            "fallback_allowed": False,
        }
    )
    bindings["model_output_recovery"].update(  # type: ignore[union-attr]
        {
            "schema_version": MODEL_OUTPUT_RECOVERY_SCHEMA_VERSION,
            "polarity_interface": SYMAI_POLARITY_CONTRACT_INTERFACE,
            "policy": model_policy,
            "policy_cid": model_policy["policy_cid"],
            "role_dispatch": {
                "interface": ROLE_AWARE_MODEL_RECOVERY_INTERFACE,
                "l1": "construct_l1",
                "t1": "realize_t1",
                "l2": "construct_l2_requires_exact_l1",
                "implicit_role_inference_allowed": False,
            },
            "call_contract": {
                "cache_prompt": False,
                "cross_call_result_reuse": False,
                "fallback": False,
                "physical_model_slots": PHYSICAL_MODEL_SLOT_COUNT,
                "response_format": "strict_json_schema",
                "seed": 0,
                "stop": ["<|im_end|>"],
                "temperature": 0,
                "runtime_receipts_require": [
                    "request_cid",
                    "prompt_cid",
                    "schema_cid",
                    "schema_name",
                    "model_call_receipt_cid",
                ],
            },
        }
    )
    try:
        gitlink = subprocess.run(
            ["git", "rev-parse", "HEAD:ipfs_accelerate_py"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReplacementQualificationError(
            "cannot resolve the pinned ipfs_accelerate_py gitlink"
        ) from exc
    if gitlink != PINNED_IPFS_ACCELERATE_GITLINK:
        raise ReplacementQualificationError(
            "ipfs_accelerate_py gitlink differs from the reviewed SyMAI "
            "replacement-schema contract"
        )
    initialized_source = repo_root / "ipfs_accelerate_py" / (
        PINNED_SYMAI_ROUTER_SOURCE_PATH
    )
    if initialized_source.is_file() and (
        cid_for_bytes(initialized_source.read_bytes())
        != PINNED_SYMAI_ROUTER_SOURCE_CID
    ):
        raise ReplacementQualificationError(
            "initialized SyMAI router source differs from its pinned CID"
        )
    router_binding = {
        "interface": "PinnedSyMAIRouterContract@1",
        "gitlink_commit": gitlink,
        "source_path": PINNED_SYMAI_ROUTER_SOURCE_PATH,
        "raw_cid": PINNED_SYMAI_ROUTER_SOURCE_CID,
        "source_raw_cid": PINNED_SYMAI_ROUTER_SOURCE_CID,
        "reviewed_contract": (
            "accepts exact srt023_replacement_l1/t1/l2 JSON schemas"
        ),
    }
    bindings["symai_router_contract"] = {
        **router_binding,
        "binding_cid": cid_for_dag_json(router_binding),
    }
    return bindings


def _fixture_binding(repo_root: Path) -> tuple[dict[str, object], tuple[MatrixCase, ...]]:
    path = repo_root / DEFAULT_FIXTURE_RELATIVE_PATH
    cases = load_matrix_cases(path)
    if len(cases) != 5:
        raise ReplacementQualificationError(
            "replacement matrix requires the unchanged five pilot cases"
        )
    if len({case.case_id for case in cases}) != 5:
        raise ReplacementQualificationError("pilot case IDs must be unique")
    return (
        {
            **_raw_file_binding(repo_root, DEFAULT_FIXTURE_RELATIVE_PATH),
            "unchanged": True,
            "case_count": 5,
            "case_ids": [case.case_id for case in cases],
            "case_cids": {
                case.case_id: case.case_cid for case in cases
            },
        },
        cases,
    )


def _historical_binding(repo_root: Path) -> dict[str, object]:
    report_path = repo_root / DEFAULT_SRT014_REPORT_RELATIVE_PATH
    manifest_path = repo_root / DEFAULT_REMEDIATION_MANIFEST_RELATIVE_PATH
    report = _strict_object(report_path, "frozen SRT-014 report")
    manifest = _strict_object(manifest_path, "SRT-021 remediation manifest")
    report_cid = _require_cid(
        report.get("report_cid"), codec="dag-json", label="SRT-014 report CID"
    )
    report_body = dict(report)
    del report_body["report_cid"]
    if cid_for_dag_json(report_body) != report_cid:
        raise ReplacementQualificationError("SRT-014 report CID drifted")
    manifest_cid = _require_cid(
        manifest.get("manifest_cid"),
        codec="dag-json",
        label="SRT-021 manifest CID",
    )
    manifest_body = dict(manifest)
    del manifest_body["manifest_cid"]
    if cid_for_dag_json(manifest_body) != manifest_cid:
        raise ReplacementQualificationError(
            "SRT-021 remediation manifest CID drifted"
        )
    return {
        "protocol_immutable": True,
        "replacement_run_namespace_required": True,
        "srt014": {
            **_raw_file_binding(
                repo_root, DEFAULT_SRT014_REPORT_RELATIVE_PATH
            ),
            "report_cid": report_cid,
        },
        "srt021": {
            **_raw_file_binding(
                repo_root, DEFAULT_REMEDIATION_MANIFEST_RELATIVE_PATH
            ),
            "manifest_cid": manifest_cid,
        },
    }


def _deterministic_cell(spec: CompositionSpec, realizer: RealizerSpec) -> bool:
    return (
        spec.repair is RepairMode.NO_REPAIR
        and realizer.mode is RealizerMode.DETERMINISTIC
    )


def _required_capabilities(
    spec: CompositionSpec,
    realizer: RealizerSpec,
) -> tuple[str, ...]:
    required = ["python", "multiformats", "hammer_cvc5", "lean"]
    if spec.base_constructor_id == "modal_spacy":
        required.append("spacy_pipeline")
    if spec.guidance is GuidanceMode.GUIDED:
        required.append("autoencoder_state")
    uses_model = not _deterministic_cell(spec, realizer)
    if uses_model:
        required.append("leanstral_direct")
    if (
        spec.constructor_route is ModelRoute.SYMAI
        or realizer.route is ModelRoute.SYMAI
    ):
        required.append("symai_leanstral_route")
    return tuple(dict.fromkeys(required))


def _route_requirements(
    spec: CompositionSpec,
    realizer: RealizerSpec,
) -> tuple[str, ...]:
    routes: list[str] = []
    if not _deterministic_cell(spec, realizer):
        routes.append("direct")
    if (
        spec.constructor_route is ModelRoute.SYMAI
        or realizer.route is ModelRoute.SYMAI
    ):
        routes.append("symai")
    return tuple(routes)


def _arm_adapter_ids(
    spec: CompositionSpec,
    realizer: RealizerSpec,
) -> tuple[str, ...]:
    values = [
        "coordinate_runner",
        (
            spec.base_constructor_id
            if spec.base_constructor_id != "model"
            else "model_output_recovery"
        )
    ]
    if spec.guidance is GuidanceMode.GUIDED:
        values.append("causal_guidance")
    if spec.repair is RepairMode.SELECTIVE:
        values.append("selective_repair")
    if realizer.mode is RealizerMode.DETERMINISTIC:
        values.append("source_withheld_paraphrase")
    else:
        values.append("model_output_recovery")
    if (
        spec.constructor_route is ModelRoute.SYMAI
        or realizer.route is ModelRoute.SYMAI
    ):
        values.append("symai_router_contract")
    return tuple(dict.fromkeys(values))


def _validate_model_smokes(smokes: Mapping[str, object]) -> dict[str, object]:
    supplied = _json_clone(dict(smokes))
    if set(supplied) != {"negative_controls", "routes", "smoke_cid"}:
        raise ReplacementQualificationError(
            "model smoke receipt fields changed"
        )
    smoke_cid = _require_cid(
        supplied["smoke_cid"], codec="dag-json", label="model smoke CID"
    )
    body = dict(supplied)
    del body["smoke_cid"]
    if cid_for_dag_json(body) != smoke_cid:
        raise ReplacementQualificationError(
            "model smoke CID does not match its payload"
        )
    routes = supplied["routes"]
    if not isinstance(routes, dict) or set(routes) != {"direct", "symai"}:
        raise ReplacementQualificationError(
            "model smokes must cover direct and SyMAI routes"
        )
    for route_id, route in routes.items():
        if not isinstance(route, dict):
            raise ReplacementQualificationError(
                f"{route_id} route smoke must be an object"
            )
        status = route.get("status")
        if status not in {"passed", "unavailable"}:
            raise ReplacementQualificationError(
                f"{route_id} route smoke status is invalid"
            )
        if route.get("fallback_used") is not False:
            raise ReplacementQualificationError(
                f"{route_id} route smoke cannot use fallback"
            )
        calls = route.get("roles")
        if not isinstance(calls, list) or not calls:
            raise ReplacementQualificationError(
                f"{route_id} route smoke requires role evidence"
            )
        observed_roles = [
            call.get("role") for call in calls if isinstance(call, dict)
        ]
        if status == "passed" and observed_roles != [
            "l1",
            "t1",
            "l2",
        ] * 3:
            raise ReplacementQualificationError(
                f"{route_id} route role evidence is incomplete"
            )
        for call in calls:
            if not isinstance(call, dict):
                raise ReplacementQualificationError("model role smoke is invalid")
            for field in (
                "request_cid",
                "prompt_cid",
                "schema_cid",
                "recovery_receipt_cid",
            ):
                _require_cid(
                    call.get(field),
                    codec=("raw" if field == "prompt_cid" else "dag-json"),
                    label=f"{route_id} {call.get('role')} {field}",
                )
            if not isinstance(call.get("schema_name"), str):
                raise ReplacementQualificationError(
                    "model smoke schema name must be exact"
                )
            if call.get("probe_modality") not in {"O", "P", "F"}:
                raise ReplacementQualificationError(
                    "model smoke must bind its O/P/F probe"
                )
        if status == "passed":
            if (
                route.get("nonempty_l1_t1_l2") is not True
                or route.get("opf_preserved") is not True
                or route.get("physical_model_slots") != 1
            ):
                raise ReplacementQualificationError(
                    f"{route_id} positive smoke did not satisfy its contract"
                )
        elif not isinstance(route.get("reason"), str) or not route["reason"]:
            raise ReplacementQualificationError(
                f"{route_id} unavailable smoke requires a reason"
            )
    controls = supplied["negative_controls"]
    required_controls = {
        "blank_t1_rejected",
        "empty_l1_rejected",
        "exact_source_copy_rejected",
        "fallback_prohibited",
        "no_guidance_zero_change",
        "polarity_inversion_rejected",
        "route_substitution_prohibited",
    }
    if not isinstance(controls, dict) or set(controls) != required_controls:
        raise ReplacementQualificationError(
            "model negative-control inventory changed"
        )
    if any(controls[key] is not True for key in required_controls):
        raise ReplacementQualificationError(
            "every model negative control must pass"
        )
    return supplied


def _route_smoke_status(smokes: Mapping[str, object], route: str) -> str:
    routes = smokes["routes"]
    assert isinstance(routes, dict)
    value = routes[route]
    assert isinstance(value, dict)
    return str(value["status"])


def _arm_qualifications(
    capabilities: Mapping[str, object],
    adapters: Mapping[str, object],
    smokes: Mapping[str, object],
    deterministic_smoke: Mapping[str, object],
) -> tuple[list[dict[str, object]], list[str], list[str]]:
    records: list[dict[str, object]] = []
    deterministic_ids: list[str] = []
    model_ids: list[str] = []
    for spec in DEFAULT_EXTENDED_MATRIX_PLAN.compositions:
        for realizer in DEFAULT_EXTENDED_MATRIX_PLAN.realizers:
            cell_id = f"{spec.arm_id}__{realizer.realizer_id}"
            deterministic = _deterministic_cell(spec, realizer)
            (deterministic_ids if deterministic else model_ids).append(cell_id)
            required = _required_capabilities(spec, realizer)
            unavailable = [
                item
                for item in required
                if not isinstance(capabilities.get(item), dict)
                or capabilities[item].get("status") != "available"  # type: ignore[union-attr]
            ]
            routes = _route_requirements(spec, realizer)
            unavailable_routes = [
                route
                for route in routes
                if _route_smoke_status(smokes, route) != "passed"
            ]
            if spec.guidance is GuidanceMode.GUIDED:
                status = TERMINAL_UNSUPPORTED
                reason = UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER
                selection = False
            elif unavailable:
                status = CAPABILITY_UNAVAILABLE
                reason = "unavailable_capabilities:" + ",".join(unavailable)
                selection = False
            elif unavailable_routes:
                status = CAPABILITY_UNAVAILABLE
                reason = "route_preflight_unavailable:" + ",".join(
                    unavailable_routes
                )
                selection = False
            elif (
                realizer.mode is RealizerMode.DETERMINISTIC
                and deterministic_smoke.get("status") != "passed"
            ):
                status = CAPABILITY_UNAVAILABLE
                reason = "deterministic_replacement_smoke_failed"
                selection = False
            else:
                status = QUALIFIED_CANDIDATE
                reason = None
                selection = PENDING_SCORED_EXECUTION
            adapter_ids = _arm_adapter_ids(spec, realizer)
            identity_payload = {
                "cell_id": cell_id,
                "composition": spec.to_dict(),
                "realizer": realizer.to_dict(),
                "adapter_bindings": {
                    adapter_id: {
                        "interface": adapters[adapter_id]["interface"],  # type: ignore[index]
                        "raw_cid": adapters[adapter_id]["raw_cid"],  # type: ignore[index]
                    }
                    for adapter_id in adapter_ids
                },
                "capability_record_cids": {
                    capability_id: capabilities[capability_id]["record_cid"]  # type: ignore[index]
                    for capability_id in required
                },
                "route_requirements": list(routes),
            }
            records.append(
                {
                    **identity_payload,
                    "arm_identity_cid": cid_for_dag_json(identity_payload),
                    "deterministic": deterministic,
                    "model_backed": not deterministic,
                    "required_capability_ids": list(required),
                    "qualification_status": status,
                    "qualification_reason": reason,
                    "selection_eligibility": selection,
                    "fallback_allowed": False,
                    "substitute_allowed": False,
                }
            )
    if len(deterministic_ids) != 4 or len(model_ids) != 26:
        raise ReplacementQualificationError(
            "replacement plan must preserve exactly 4 deterministic and "
            "26 model-backed cells"
        )
    if len({record["arm_identity_cid"] for record in records}) != 30:
        raise ReplacementQualificationError(
            "replacement arm identities are ambiguous or duplicated"
        )
    return records, deterministic_ids, model_ids


def run_deterministic_pilot_smoke(
    cases: Sequence[MatrixCase],
) -> dict[str, object]:
    """Run the repaired deterministic path on all five unchanged pilot cases."""

    constructor = TypedDeonticCanonicalConstructor()
    realizer = SourceWithheldCanonicalParaphraser()
    records: list[dict[str, object]] = []
    for case in cases:
        l1 = constructor.construct(
            ConstructorRequest(
                case.source_text, case.allowed_atom_vocabulary, {}
            )
        )
        t1: RealizerResult | None = None
        l2: ConstructorResult | None = None
        if l1.status is ComponentStatus.SUCCESS and l1.canonical_ir is not None:
            t1 = realizer.realize(
                RealizerRequest(
                    l1.canonical_ir,
                    case.allowed_atom_vocabulary,
                    frozen_replacement_config(),
                )
            )
        if t1 is not None and t1.status is ComponentStatus.SUCCESS and t1.text:
            l2 = constructor.construct(
                ConstructorRequest(
                    t1.text, case.allowed_atom_vocabulary, {}
                )
            )
        complete = bool(
            l1.status is ComponentStatus.SUCCESS
            and l1.canonical_ir is not None
            and not l1.canonical_ir.is_empty
            and t1 is not None
            and t1.status is ComponentStatus.SUCCESS
            and isinstance(t1.text, str)
            and bool(t1.text.strip())
            and l2 is not None
            and l2.status is ComponentStatus.SUCCESS
            and l2.canonical_ir is not None
            and not l2.canonical_ir.is_empty
        )
        copy_gate = source_copy_diagnostics(
            case.source_text, None if t1 is None else t1.text
        )
        polarity_gate = polarity_diagnostics(
            case.gold_ir,
            None if l2 is None else l2.canonical_ir,
        )
        record = {
            "case_id": case.case_id,
            "case_cid": case.case_cid,
            "l1_cid": (
                None
                if l1.canonical_ir is None
                else cid_for_dag_json(l1.canonical_ir.to_dict())
            ),
            "t1_cid": (
                None
                if t1 is None or t1.text is None
                else cid_for_bytes(t1.text.encode("utf-8"))
            ),
            "l2_cid": (
                None
                if l2 is None or l2.canonical_ir is None
                else cid_for_dag_json(l2.canonical_ir.to_dict())
            ),
            "nonempty_l1_t1_l2": complete,
            "gates": {
                "full_coverage": complete,
                "source_copy_exclusion": bool(copy_gate["gate_passed"]),
                "polarity_preservation": bool(
                    polarity_gate["gate_passed"]
                ),
            },
        }
        records.append(_cid_receipt(record, "record_cid"))
    payload: dict[str, object] = {
        "interface": "ReplacementDeterministicPilotSmoke@1",
        "case_count": len(records),
        "case_ids": [record["case_id"] for record in records],
        "records": records,
        "status": (
            "passed"
            if len(records) == 5
            and all(
                record["nonempty_l1_t1_l2"] is True
                and all(record["gates"].values())  # type: ignore[union-attr]
                for record in records
            )
            else "failed"
        ),
        "scored": False,
    }
    return _cid_receipt(payload, "smoke_cid")


def _negative_controls(
    causal_qualification: Mapping[str, object],
) -> dict[str, bool]:
    vocabulary = AllowedAtomVocabulary(
        actors=("regulator",),
        actions=("file",),
        objects=("report",),
        qualifiers=("within_deadline",),
    )
    obligation = CanonicalRuleIR(
        (
            CanonicalRule(
                "O",
                "regulator",
                "file",
                "report",
                temporal=("within_deadline",),
            ),
        )
    )
    prohibition = CanonicalRuleIR(
        (
            CanonicalRule(
                "F",
                "regulator",
                "file",
                "report",
                temporal=("within_deadline",),
            ),
        )
    )
    blank_rejected = False
    empty_rejected = False
    try:
        SyMAIPolarityContract.validate_realization(
            {"rules": []}, obligation
        )
    except ContractError:
        blank_rejected = True
    try:
        SyMAIPolarityContract.validate_canonical(
            {"rules": []},
            vocabulary,
            role=RecoveryRole.L1,
        )
    except (ContractError, ValueError):
        empty_rejected = True
    causal_control = causal_qualification.get("negative_control")
    return {
        "blank_t1_rejected": blank_rejected,
        "empty_l1_rejected": empty_rejected,
        "exact_source_copy_rejected": (
            source_copy_diagnostics(
                "The regulator must file the report within deadline.",
                "The regulator must file the report within deadline.",
            )["gate_passed"]
            is False
        ),
        "fallback_prohibited": True,
        "no_guidance_zero_change": bool(
            isinstance(causal_control, Mapping)
            and causal_control.get("canonical_l1_changed") is False
            and causal_control.get("status") == "passed_zero_change"
        ),
        "polarity_inversion_rejected": (
            polarity_diagnostics(obligation, prohibition)["gate_passed"]
            is False
        ),
        "route_substitution_prohibited": True,
    }


class _RecordingClient:
    """Capture exact prompt/schema identities while delegating one real call."""

    def __init__(self, client: object) -> None:
        self._client = client
        self.calls: list[dict[str, object]] = []

    def __getattr__(self, name: str) -> object:
        return getattr(self._client, name)

    def complete_json(self, **kwargs: object) -> object:
        prompt = kwargs.get("prompt")
        system = kwargs.get("system")
        schema = kwargs.get("schema")
        if (
            not isinstance(prompt, str)
            or not isinstance(system, str)
            or not isinstance(schema, Mapping)
        ):
            raise ContractError("recorded model call contract is incomplete")
        self.calls.append(
            {
                "prompt_cid": cid_for_bytes(prompt.encode("utf-8")),
                "system_cid": cid_for_bytes(system.encode("utf-8")),
                "schema_cid": cid_for_dag_json(dict(schema)),
                "schema_name": kwargs.get("schema_name"),
                "max_tokens": kwargs.get("max_tokens"),
            }
        )
        method = getattr(self._client, "complete_json")
        return method(**kwargs)  # type: ignore[misc]


def _role_smoke_record(
    role: str,
    result: ModelOutputRecoveryResult,
    call: Mapping[str, object],
    *,
    probe_modality: str,
) -> dict[str, object]:
    output_cid = (
        cid_for_dag_json(result.canonical_ir.to_dict())
        if result.canonical_ir is not None
        else cid_for_bytes((result.text or "").encode("utf-8"))
        if result.text is not None
        else None
    )
    return {
        "role": role,
        "probe_modality": probe_modality,
        "status": result.status.value,
        "failure_reason": (
            None
            if result.failure_reason is None
            else result.failure_reason.value
        ),
        "request_cid": result.receipt.request_cid,
        "prompt_cid": call["prompt_cid"],
        "system_cid": call["system_cid"],
        "schema_cid": call["schema_cid"],
        "schema_name": call["schema_name"],
        "output_cid": output_cid,
        "recovery_receipt_cid": result.receipt.receipt_cid,
    }


def _run_route_smoke(route: RecoveryRoute) -> dict[str, object]:
    vocabulary = AllowedAtomVocabulary(
        actors=("regulator", "company", "court"),
        actions=("file", "access", "destroy"),
        objects=("report", "records", "evidence"),
        qualifiers=(
            "within_deadline",
            "when_authorized",
            "unless_ordered",
        ),
    )
    probes = (
        ("O", "The regulator must file the report within deadline."),
        ("P", "The company may access the records when authorized."),
        ("F", "The court must not destroy the evidence unless ordered."),
    )
    raw_client: object = (
        LeanstralClient()
        if route is RecoveryRoute.DIRECT
        else SyMAIClient()
    )
    client = _RecordingClient(raw_client)
    recovery = BoundedModelOutputRecovery(client, route=route)
    roles: list[dict[str, object]] = []
    complete = True
    opf = True
    source_copy_results: dict[str, bool] = {}
    failure_reason: str | None = None
    for modality, source in probes:
        l1 = recovery.recover_l1(
            ConstructorRequest(source, vocabulary, {})
        )
        roles.append(
            _role_smoke_record(
                "l1",
                l1,
                client.calls[-1],
                probe_modality=modality,
            )
        )
        if (
            l1.status is not ComponentStatus.SUCCESS
            or l1.canonical_ir is None
        ):
            complete = False
            opf = False
            failure_reason = (
                l1.failure_reason.value
                if l1.failure_reason is not None
                else "unknown_failure"
            )
            break
        t1 = recovery.recover_t1(
            RealizerRequest(l1.canonical_ir, vocabulary, {})
        )
        roles.append(
            _role_smoke_record(
                "t1",
                t1,
                client.calls[-1],
                probe_modality=modality,
            )
        )
        if t1.status is not ComponentStatus.SUCCESS or not t1.text:
            complete = False
            opf = False
            failure_reason = (
                t1.failure_reason.value
                if t1.failure_reason is not None
                else "blank_t1"
            )
            break
        source_copy_results[modality] = bool(
            source_copy_diagnostics(source, t1.text)["gate_passed"]
        )
        l2 = recovery.recover_l2(
            ConstructorRequest(t1.text, vocabulary, {}),
            expected_ir=l1.canonical_ir,
        )
        roles.append(
            _role_smoke_record(
                "l2",
                l2,
                client.calls[-1],
                probe_modality=modality,
            )
        )
        probe_complete = bool(
            l2.status is ComponentStatus.SUCCESS
            and l2.canonical_ir is not None
            and not l2.canonical_ir.is_empty
        )
        complete = complete and probe_complete
        probe_polarity = bool(
            probe_complete
            and Counter(rule.modality for rule in l1.canonical_ir.rules)
            == Counter(rule.modality for rule in l2.canonical_ir.rules)  # type: ignore[union-attr]
            == Counter({modality: 1})
        )
        opf = opf and probe_polarity
        if not probe_complete or not probe_polarity:
            failure_reason = (
                l2.failure_reason.value
                if l2.failure_reason is not None
                else "polarity_not_preserved"
            )
            break
    return {
        "route": route.value,
        "status": "passed" if complete and opf else "unavailable",
        "reason": (
            None
            if complete and opf
            else "typed_model_preflight:"
            + (failure_reason or "opf_not_preserved")
        ),
        "roles": roles,
        "source_copy_gate_by_modality": source_copy_results,
        "fallback_used": False,
        "physical_model_slots": 1,
        "nonempty_l1_t1_l2": complete,
        "opf_preserved": opf,
        "scored": False,
    }


def run_live_model_smokes(
    causal_qualification: Mapping[str, object],
) -> dict[str, object]:
    """Run sequential direct and SyMAI L1/T1/L2 schema-bound smokes."""

    body = {
        "negative_controls": _negative_controls(causal_qualification),
        "routes": {
            "direct": _run_route_smoke(RecoveryRoute.DIRECT),
            "symai": _run_route_smoke(RecoveryRoute.SYMAI),
        },
    }
    return _cid_receipt(body, "smoke_cid")


@dataclass(slots=True)
class RoleAwareModelRecovery:
    """Explicit model-stage adapter; no L1/L2 inference from call order."""

    recovery: BoundedModelOutputRecovery

    @property
    def identity(self) -> str:
        return (
            f"{ROLE_AWARE_MODEL_RECOVERY_INTERFACE}:"
            f"{self.recovery.identity}"
        )

    def construct_l1(self, request: ConstructorRequest) -> ConstructorResult:
        return self._constructor_result(self.recover_l1(request))

    def recover_l1(
        self, request: ConstructorRequest
    ) -> ModelOutputRecoveryResult:
        """Return the raw typed L1 result so orchestration retains its receipt."""

        return self.recovery.recover_l1(request)

    def realize_t1(self, request: RealizerRequest) -> RealizerResult:
        result = self.recover_t1(request)
        if result.status is ComponentStatus.SUCCESS:
            return RealizerResult(ComponentStatus.SUCCESS, text=result.text)
        return RealizerResult(
            ComponentStatus.FAILED,
            failure_reason=result.failure_reason,
            failure_detail=result.failure_detail,
        )

    def recover_t1(
        self, request: RealizerRequest
    ) -> ModelOutputRecoveryResult:
        """Return the raw typed T1 result so orchestration retains its receipt."""

        return self.recovery.recover_t1(request)

    def construct_l2(
        self,
        request: ConstructorRequest,
        *,
        expected_l1: CanonicalRuleIR,
    ) -> ConstructorResult:
        if not isinstance(expected_l1, CanonicalRuleIR) or expected_l1.is_empty:
            raise ContractError(
                "L2 recovery requires the exact nonempty preceding L1"
            )
        return self._constructor_result(
            self.recover_l2(request, expected_l1=expected_l1)
        )

    def recover_l2(
        self,
        request: ConstructorRequest,
        *,
        expected_l1: CanonicalRuleIR,
    ) -> ModelOutputRecoveryResult:
        """Return raw L2 evidence under explicit preceding-L1 authority."""

        if not isinstance(expected_l1, CanonicalRuleIR) or expected_l1.is_empty:
            raise ContractError(
                "L2 recovery requires the exact nonempty preceding L1"
            )
        return self.recovery.recover_l2(
            request,
            expected_ir=expected_l1,
        )

    @staticmethod
    def _constructor_result(
        result: ModelOutputRecoveryResult,
    ) -> ConstructorResult:
        if result.status is ComponentStatus.SUCCESS:
            return ConstructorResult(
                ComponentStatus.SUCCESS,
                canonical_ir=result.canonical_ir,
            )
        return ConstructorResult(
            ComponentStatus.FAILED,
            failure_reason=result.failure_reason,
            failure_detail=result.failure_detail,
        )


def _runtime_plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _runtime_plain(item) for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_runtime_plain(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _runtime_plain(to_dict())
    return value


def _component_identity(component: object, role: str) -> str:
    identity = getattr(component, "identity", None)
    if not isinstance(identity, str) or not identity.strip():
        raise ContractError(f"{role} identity must be a nonblank string")
    return identity


@dataclass(frozen=True, slots=True)
class _IdentityOnlyComponent:
    """Supply a declared identity to the unchanged semantic record sealer."""

    identity: str


def _model_recovery_evidence(
    result: ModelOutputRecoveryResult,
) -> dict[str, object]:
    receipt = result.receipt.to_dict()
    payload: dict[str, object] = {
        "interface": "RoleExplicitModelRecoveryResult@1",
        "role": result.role.value,
        "status": result.status.value,
        "failure_reason": (
            None
            if result.failure_reason is None
            else result.failure_reason.value
        ),
        "failure_detail": result.failure_detail,
        "canonical_ir_cid": (
            None
            if result.canonical_ir is None
            else cid_for_dag_json(result.canonical_ir.to_dict())
        ),
        "text_cid": (
            None
            if result.text is None
            else cid_for_bytes(result.text.encode("utf-8"))
        ),
        "recovery_receipt": receipt,
        "recovery_receipt_cid": result.receipt.receipt_cid,
    }
    return _cid_receipt(payload, "result_receipt_cid")


def _stage_receipt(
    *,
    role: str,
    component_identity: str,
    request: ConstructorRequest | RealizerRequest,
    result: ConstructorResult | RealizerResult,
    component_receipt: object | None,
) -> dict[str, object]:
    request_payload = request.to_payload()
    if isinstance(result, ConstructorResult):
        output_cid = (
            None
            if result.canonical_ir is None
            else cid_for_dag_json(result.canonical_ir.to_dict())
        )
        output_codec = "dag-json" if output_cid is not None else None
    else:
        output_cid = (
            None
            if result.text is None
            else cid_for_bytes(result.text.encode("utf-8"))
        )
        output_codec = "raw" if output_cid is not None else None
    plain_component = (
        None
        if component_receipt is None
        else _runtime_plain(component_receipt)
    )
    payload: dict[str, object] = {
        "interface": "ReplacementCoordinateStageReceipt@1",
        "role": role,
        "component_identity": component_identity,
        "request_cid": cid_for_dag_json(request_payload),
        "status": result.status.value,
        "failure_reason": (
            None
            if result.failure_reason is None
            else result.failure_reason.value
        ),
        "failure_detail": result.failure_detail,
        "output_cid": output_cid,
        "output_codec": output_codec,
        "component_receipt": plain_component,
        "component_receipt_cid": (
            None
            if plain_component is None
            else cid_for_dag_json(plain_component)
        ),
    }
    return _cid_receipt(payload, "stage_receipt_cid")


def _failed_constructor(
    reason: FailureReason,
    detail: str,
) -> ConstructorResult:
    return ConstructorResult(
        ComponentStatus.FAILED,
        failure_reason=reason,
        failure_detail=detail[:1000],
    )


def _failed_realizer(
    reason: FailureReason,
    detail: str,
) -> RealizerResult:
    return RealizerResult(
        ComponentStatus.FAILED,
        failure_reason=reason,
        failure_detail=detail[:1000],
    )


def _invoke_constructor_stage(
    component: object,
    request: ConstructorRequest,
    *,
    role: RecoveryRole,
    expected_l1: CanonicalRuleIR | None = None,
) -> tuple[ConstructorResult, dict[str, object]]:
    component_receipt: object | None = None
    try:
        if isinstance(component, RoleAwareModelRecovery):
            if role is RecoveryRole.L1:
                recovered = component.recover_l1(request)
            elif role is RecoveryRole.L2 and expected_l1 is not None:
                recovered = component.recover_l2(
                    request,
                    expected_l1=expected_l1,
                )
            else:
                raise ContractError(
                    "constructor stage requires explicit L1 or authorized L2"
                )
            result = component._constructor_result(recovered)
            component_receipt = _model_recovery_evidence(recovered)
        else:
            diagnostic_method = getattr(
                component, "construct_with_diagnostics", None
            )
            if callable(diagnostic_method):
                outcome = diagnostic_method(request)
                result = getattr(outcome, "result", None)
                component_receipt = getattr(
                    outcome,
                    "receipt",
                    getattr(outcome, "diagnostics", None),
                )
            else:
                method = getattr(component, "construct")
                result = method(request)
            if not isinstance(result, ConstructorResult):
                result = _failed_constructor(
                    FailureReason.INVALID_OUTPUT,
                    "constructor returned a non-ConstructorResult",
                )
                component_receipt = {
                    "status": "invalid_component_result",
                }
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        result = _failed_constructor(
            FailureReason.EXCEPTION,
            f"constructor raised {type(exc).__name__}",
        )
        component_receipt = {
            "status": "component_exception",
            "exception_type": type(exc).__name__,
        }
    if (
        role is RecoveryRole.L2
        and result.status is ComponentStatus.FAILED
        and result.failure_reason is FailureReason.EMPTY_L1
    ):
        result = _failed_constructor(
            FailureReason.EMPTY_L2,
            result.failure_detail or "L2 constructor produced an empty IR",
        )
    stage = _stage_receipt(
        role=role.value,
        component_identity=_component_identity(component, "constructor"),
        request=request,
        result=result,
        component_receipt=component_receipt,
    )
    return result, stage


def _invoke_realizer_stage(
    component: object,
    request: RealizerRequest,
) -> tuple[RealizerResult, dict[str, object]]:
    component_receipt: object | None = None
    try:
        if isinstance(component, RoleAwareModelRecovery):
            recovered = component.recover_t1(request)
            if recovered.status is ComponentStatus.SUCCESS:
                result = RealizerResult(
                    ComponentStatus.SUCCESS,
                    text=recovered.text,
                )
            else:
                result = _failed_realizer(
                    recovered.failure_reason or FailureReason.INVALID_OUTPUT,
                    recovered.failure_detail or "model T1 recovery failed",
                )
            component_receipt = _model_recovery_evidence(recovered)
        else:
            receipt_method = getattr(component, "realize_with_receipt", None)
            if callable(receipt_method):
                outcome = receipt_method(request)
                if (
                    not isinstance(outcome, tuple)
                    or len(outcome) != 2
                ):
                    result = _failed_realizer(
                        FailureReason.INVALID_OUTPUT,
                        "realizer receipt method returned an invalid pair",
                    )
                else:
                    result, component_receipt = outcome
            else:
                method = getattr(component, "realize")
                result = method(request)
            if not isinstance(result, RealizerResult):
                result = _failed_realizer(
                    FailureReason.INVALID_OUTPUT,
                    "realizer returned a non-RealizerResult",
                )
                component_receipt = {
                    "status": "invalid_component_result",
                }
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        result = _failed_realizer(
            FailureReason.EXCEPTION,
            f"realizer raised {type(exc).__name__}",
        )
        component_receipt = {
            "status": "component_exception",
            "exception_type": type(exc).__name__,
        }
    stage = _stage_receipt(
        role=RecoveryRole.T1.value,
        component_identity=_component_identity(component, "realizer"),
        request=request,
        result=result,
        component_receipt=component_receipt,
    )
    return result, stage


@dataclass(frozen=True, slots=True)
class ReplacementCoordinateExecution:
    """One terminal, CID-addressed coordinate result for SRT-026."""

    result: RoundTripResult
    receipt: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.result, RoundTripResult):
            raise ContractError("coordinate result must be RoundTripResult")
        if not isinstance(self.receipt, Mapping):
            raise ContractError("coordinate receipt must be an object")
        supplied = _runtime_plain(self.receipt)
        if not isinstance(supplied, dict):
            raise ContractError("coordinate receipt must serialize as an object")
        coordinate_cid = _require_cid(
            supplied.get("coordinate_cid"),
            codec="dag-json",
            label="replacement coordinate CID",
        )
        body = dict(supplied)
        del body["coordinate_cid"]
        if cid_for_dag_json(body) != coordinate_cid:
            raise ContractError(
                "replacement coordinate CID does not match its payload"
            )
        if (
            supplied.get("schema_version")
            != REPLACEMENT_COORDINATE_RECEIPT_SCHEMA
            or supplied.get("interface")
            != REPLACEMENT_COORDINATE_RUNNER_INTERFACE
            or supplied.get("status") != self.result.status.value
            or supplied.get("losses")
            != {
                "forward": self.result.forward_loss,
                "cycle": self.result.cycle_loss,
                "end_to_end": self.result.end_to_end_loss,
                "primary": self.result.primary_loss,
            }
        ):
            raise ContractError(
                "replacement coordinate receipt contradicts its typed result"
            )
        object.__setattr__(self, "receipt", supplied)

    @property
    def coordinate_cid(self) -> str:
        return str(self.receipt["coordinate_cid"])

    @property
    def primary_loss(self) -> float:
        return self.result.primary_loss

    @property
    def status(self) -> ComponentStatus:
        return self.result.status

    def to_dict(self) -> dict[str, object]:
        return _json_clone(dict(self.receipt))


class ReplacementCoordinateRunner:
    """Execute only coordinates declared by one validated qualification."""

    interface: Final = REPLACEMENT_COORDINATE_RUNNER_INTERFACE

    def __init__(
        self,
        qualification: Mapping[str, object],
        *,
        client_factories: Mapping[
            RecoveryRoute | str, Callable[[], object]
        ]
        | None = None,
        validators: Mapping[str, PostHocValidator] | None = None,
    ) -> None:
        if not isinstance(qualification, Mapping):
            raise ContractError("qualification must be an object")
        supplied = _runtime_plain(qualification)
        if not isinstance(supplied, dict):
            raise ContractError("qualification must serialize as an object")
        qualification_cid = _require_cid(
            supplied.get("qualification_cid"),
            codec="dag-json",
            label="replacement qualification CID",
        )
        qualification_body = dict(supplied)
        del qualification_body["qualification_cid"]
        if cid_for_dag_json(qualification_body) != qualification_cid:
            raise ContractError(
                "replacement qualification CID does not match its payload"
            )
        if (
            supplied.get("interface") != QUALIFIED_REPLACEMENT_MATRIX_INTERFACE
            or supplied.get("frozen_before_scored_execution") is not True
        ):
            raise ContractError(
                "coordinate runner requires the frozen replacement qualification"
            )
        plan = supplied.get("plan")
        schedule = supplied.get("schedule")
        lineage = supplied.get("lineage")
        if (
            not isinstance(plan, dict)
            or not isinstance(schedule, dict)
            or not isinstance(lineage, dict)
        ):
            raise ContractError(
                "qualification plan, schedule, or lineage is missing"
            )
        plan_cid = _require_cid(
            plan.get("plan_cid"),
            codec="dag-json",
            label="replacement plan CID",
        )
        plan_body = dict(plan)
        del plan_body["plan_cid"]
        if cid_for_dag_json(plan_body) != plan_cid:
            raise ContractError("replacement plan CID does not match its payload")
        raw_arms = plan.get("arms")
        if not isinstance(raw_arms, list):
            raise ContractError("replacement plan arms are missing")
        arms = {
            str(arm.get("cell_id")): arm
            for arm in raw_arms
            if isinstance(arm, dict)
        }
        static_specs = {
            f"{spec.arm_id}__{realizer.realizer_id}": (spec, realizer)
            for spec in DEFAULT_EXTENDED_MATRIX_PLAN.compositions
            for realizer in DEFAULT_EXTENDED_MATRIX_PLAN.realizers
        }
        if set(arms) != set(static_specs) or len(raw_arms) != len(arms):
            raise ContractError(
                "qualification arms differ from the frozen 30-cell registry"
            )
        for cell_id, (spec, realizer) in static_specs.items():
            arm = arms[cell_id]
            if (
                arm.get("composition") != spec.to_dict()
                or arm.get("realizer") != realizer.to_dict()
            ):
                raise ContractError(
                    f"qualification arm {cell_id!r} changed its axes"
                )
        fixture = lineage.get("fixture")
        if not isinstance(fixture, dict):
            raise ContractError("qualification fixture binding is missing")
        case_ids = fixture.get("case_ids")
        case_cids = fixture.get("case_cids")
        if (
            not isinstance(case_ids, list)
            or len(case_ids) != 5
            or len(set(case_ids)) != 5
            or not isinstance(case_cids, dict)
            or set(case_cids) != set(case_ids)
        ):
            raise ContractError("qualification case bindings are invalid")
        model_ids = plan.get("model_backed_cell_ids")
        deterministic_ids = plan.get("deterministic_cell_ids")
        if (
            not isinstance(model_ids, list)
            or not isinstance(deterministic_ids, list)
            or len(model_ids) != 26
            or len(deterministic_ids) != 4
        ):
            raise ContractError("qualification cell partitions are invalid")
        validated_schedule = _validate_balanced_schedule(
            schedule,
            model_arm_ids=model_ids,
            case_ids=case_ids,
            plan_cid=plan_cid,
        )
        scheduled: dict[tuple[str, int, str], str] = {}
        model_coordinate_order: list[tuple[str, int, str]] = []
        for block in validated_schedule["blocks"]:  # type: ignore[index]
            assert isinstance(block, dict)
            block_case_id = str(block["case_id"])
            repeat_index = int(block["repeat_index"])
            coordinates = block["coordinates"]
            assert isinstance(coordinates, list)
            for coordinate in coordinates:
                assert isinstance(coordinate, dict)
                key = (
                    block_case_id,
                    repeat_index,
                    str(coordinate["arm_id"]),
                )
                if key in scheduled:
                    raise ContractError(
                        "qualification schedule duplicates a coordinate"
                    )
                scheduled[key] = str(coordinate["cache_namespace"])
                model_coordinate_order.append(key)
        if len(scheduled) != 650:
            raise ContractError(
                "qualification schedule must contain 650 model coordinates"
            )

        factories: dict[RecoveryRoute, Callable[[], object]] = {
            RecoveryRoute.DIRECT: LeanstralClient,
            RecoveryRoute.SYMAI: SyMAIClient,
        }
        for key, factory in dict(client_factories or {}).items():
            try:
                route = key if isinstance(key, RecoveryRoute) else RecoveryRoute(key)
            except (TypeError, ValueError) as exc:
                raise ContractError(
                    f"unknown model client route: {key!r}"
                ) from exc
            if not callable(factory):
                raise ContractError(
                    f"model client factory for {route.value} must be callable"
                )
            factories[route] = factory

        selected_validators = (
            default_post_hoc_validators()
            if validators is None
            else dict(validators)
        )
        expected_validators = {
            item.validator_id
            for item in DEFAULT_EXTENDED_MATRIX_PLAN.validation_overlays
        }
        if (
            set(selected_validators) != expected_validators
            or any(not callable(item) for item in selected_validators.values())
        ):
            raise ContractError(
                "coordinate validators must equal the frozen validation overlays"
            )

        self._qualification_cid = qualification_cid
        self._plan_cid = plan_cid
        self._arms = arms
        self._specs = static_specs
        self._case_ids = tuple(str(value) for value in case_ids)
        self._case_cids = {
            str(key): str(value) for key, value in case_cids.items()
        }
        self._model_ids = tuple(str(value) for value in model_ids)
        self._deterministic_ids = tuple(
            str(value) for value in deterministic_ids
        )
        self._scheduled = scheduled
        self._model_coordinate_order = tuple(model_coordinate_order)
        self._client_factories = factories
        self._validators = selected_validators

    @property
    def identity(self) -> str:
        return (
            f"{self.interface}:{self._qualification_cid}:{self._plan_cid}"
        )

    @property
    def cell_ids(self) -> tuple[str, ...]:
        return tuple(self._specs)

    def cache_namespace_for(
        self,
        *,
        case_id: str,
        cell_id: str,
        repeat_index: int,
    ) -> str:
        """Return the only frozen namespace accepted for one coordinate."""

        if cell_id not in self._specs or case_id not in self._case_cids:
            raise ContractError("unknown replacement case or cell")
        if type(repeat_index) is not int or repeat_index < 0:
            raise ContractError("repeat_index must be a nonnegative integer")
        if cell_id in self._model_ids:
            try:
                return self._scheduled[(case_id, repeat_index, cell_id)]
            except KeyError as exc:
                raise ContractError(
                    "model coordinate is absent from the frozen schedule"
                ) from exc
        if repeat_index != 0:
            raise ContractError(
                "deterministic coordinates have exactly repeat_index zero"
            )
        namespace_cid = cid_for_dag_json(
            {
                "plan_cid": self._plan_cid,
                "case_id": case_id,
                "repeat_index": 0,
                "arm_id": cell_id,
                "cache_mode": "deterministic_uncached",
            }
        )
        return f"srt-replacement-deterministic-{namespace_cid}"

    def frozen_coordinates(self) -> tuple[dict[str, object], ...]:
        """Return all 20 deterministic and 650 model coordinates in run order."""

        values: list[dict[str, object]] = []
        for case_id in self._case_ids:
            for cell_id in self._deterministic_ids:
                values.append(
                    {
                        "case_id": case_id,
                        "cell_id": cell_id,
                        "repeat_index": 0,
                        "cache_namespace": self.cache_namespace_for(
                            case_id=case_id,
                            cell_id=cell_id,
                            repeat_index=0,
                        ),
                    }
                )
        for case_id, repeat_index, cell_id in self._model_coordinate_order:
            values.append(
                {
                    "case_id": case_id,
                    "cell_id": cell_id,
                    "repeat_index": repeat_index,
                    "cache_namespace": self.cache_namespace_for(
                        case_id=case_id,
                        cell_id=cell_id,
                        repeat_index=repeat_index,
                    ),
                }
            )
        if len(values) != 670:
            raise ContractError(
                "replacement coordinate registry must contain exactly 670 entries"
            )
        return tuple(values)

    def _route_mapping(
        self,
        spec: CompositionSpec,
        realizer: RealizerSpec,
    ) -> dict[str, str]:
        return {
            "constructor": spec.constructor_route.value,
            "selective_repair": (
                RecoveryRoute.DIRECT.value
                if spec.repair is RepairMode.SELECTIVE
                else ModelRoute.NOT_APPLICABLE.value
            ),
            "realizer": realizer.route.value,
        }

    def _seal(
        self,
        *,
        case: MatrixCase,
        cell_id: str,
        repeat_index: int,
        cache_namespace: str,
        result: RoundTripResult,
        stages: Sequence[Mapping[str, object]],
        constructor_identity: str | None,
        realizer_identity: str | None,
        disposition: str,
    ) -> ReplacementCoordinateExecution:
        arm = self._arms[cell_id]
        spec, realizer = self._specs[cell_id]
        declared_constructor_identity = (
            constructor_identity
            or f"{self.interface}:terminal:{spec.arm_id}"
        )
        declared_realizer_identity = (
            realizer_identity
            or f"{self.interface}:terminal:{realizer.realizer_id}"
        )
        constructor_id = spec.arm_id
        realizer_id = realizer.realizer_id
        realizer_config = (
            frozen_replacement_config()
            if realizer.mode is RealizerMode.DETERMINISTIC
            else {}
        )
        # Reuse the unchanged semantic authority rather than maintaining a
        # near-copy of its scorer, diagnostics, gate, candidate-binding, and
        # post-hoc validation contract in this replacement orchestrator.
        semantic_sealer = SemanticRoundTripMatrix(
            {
                constructor_id: _IdentityOnlyComponent(
                    declared_constructor_identity
                )
            },
            {
                realizer_id: _IdentityOnlyComponent(
                    declared_realizer_identity
                )
            },
            constructor_configs={constructor_id: {}},
            realizer_configs={realizer_id: realizer_config},
            validators=self._validators,
            require_eight_cells=False,
        )
        semantic = semantic_sealer._seal_coordinate(
            case=case,
            constructor_id=constructor_id,
            constructor_identity=declared_constructor_identity,
            realizer_id=realizer_id,
            realizer_identity=declared_realizer_identity,
            result=result,
        )
        if (
            semantic.cell_id != cell_id
            or semantic.validation["candidate_unchanged"] is not True
        ):
            raise ContractError(
                "unchanged semantic sealer did not retain the exact coordinate"
            )
        semantic_record = semantic.to_dict()
        payload: dict[str, object] = {
            "schema_version": REPLACEMENT_COORDINATE_RECEIPT_SCHEMA,
            "interface": self.interface,
            "qualification_cid": self._qualification_cid,
            "plan_cid": self._plan_cid,
            "arm_identity_cid": arm["arm_identity_cid"],
            "case_id": case.case_id,
            "case_cid": case.case_cid,
            "cell_id": cell_id,
            "repeat_index": repeat_index,
            "cache": {
                "mode": (
                    "uncached"
                    if cell_id in self._model_ids
                    else "deterministic_uncached"
                ),
                "namespace": cache_namespace,
                "namespace_cid": cid_for_bytes(
                    cache_namespace.encode("utf-8")
                ),
                "prompt_cache_enabled": False,
                "response_cache_enabled": False,
                "cache_hit": False,
                "result_reused": False,
            },
            "composition": spec.to_dict(),
            "realizer": realizer.to_dict(),
            "route_mapping": self._route_mapping(spec, realizer),
            "qualification_status": arm["qualification_status"],
            "qualification_reason": arm["qualification_reason"],
            "execution_disposition": disposition,
            "fallback_used": False,
            "substitute_used": False,
            "physical_model_resource": {
                "slot_count": PHYSICAL_MODEL_SLOT_COUNT,
                "serialized": bool(arm["model_backed"]),
            },
            "constructor_identity": declared_constructor_identity,
            "realizer_identity": declared_realizer_identity,
            "status": result.status.value,
            "failure": semantic_record["failure"],
            "artifacts": semantic_record["artifacts"],
            "losses": semantic_record["losses"],
            "diagnostics": semantic_record["diagnostics"],
            "semantic_record": semantic_record,
            "semantic_record_cid": semantic.record_cid,
            "candidate_cid": semantic.candidate_cid,
            "semantic_contract_unchanged": True,
            "candidate_bound_before_post_hoc_validation": True,
            "stage_count": len(stages),
            "stages": list(stages),
            "validation": semantic_record["validation"],
        }
        receipt = _cid_receipt(payload, "coordinate_cid")
        return ReplacementCoordinateExecution(result, receipt)

    def _execute(
        self,
        *,
        case: MatrixCase,
        cell_id: str,
        repeat_index: int,
        cache_namespace: str,
    ) -> ReplacementCoordinateExecution:
        arm = self._arms[cell_id]
        spec, realizer_spec = self._specs[cell_id]
        qualification_status = arm["qualification_status"]
        if qualification_status != QUALIFIED_CANDIDATE:
            reason = str(
                arm["qualification_reason"]
                or "replacement arm is not qualified for execution"
            )
            result = make_round_trip_result(
                case.gold_ir,
                None,
                None,
                None,
                failure_reason=FailureReason.CAPABILITY_UNAVAILABLE,
                failure_detail=reason,
            )
            return self._seal(
                case=case,
                cell_id=cell_id,
                repeat_index=repeat_index,
                cache_namespace=cache_namespace,
                result=result,
                stages=(),
                constructor_identity=None,
                realizer_identity=None,
                disposition=str(qualification_status),
            )

        clients: dict[RecoveryRoute, object] = {}
        recoveries: dict[RecoveryRoute, RoleAwareModelRecovery] = {}

        def client(route: RecoveryRoute) -> object:
            if route not in clients:
                clients[route] = self._client_factories[route]()
            return clients[route]

        def model_recovery(route: RecoveryRoute) -> RoleAwareModelRecovery:
            if route not in recoveries:
                recoveries[route] = RoleAwareModelRecovery(
                    BoundedModelOutputRecovery(
                        client(route),
                        route=route,
                    )
                )
            return recoveries[route]

        if spec.base_constructor_id == "typed_deontic":
            constructor: object = TypedDeonticCanonicalConstructor()
        elif spec.base_constructor_id == "modal_spacy":
            constructor = ModalSpacyCanonicalConstructor()
        elif (
            spec.base_constructor_id == "model"
            and spec.repair is RepairMode.ALWAYS_ON
        ):
            constructor = model_recovery(
                RecoveryRoute(spec.constructor_route.value)
            )
        else:
            raise ContractError(
                f"unsupported constructor registry entry: {spec.arm_id}"
            )
        if spec.guidance is GuidanceMode.GUIDED:
            raise ContractError(
                "guided arm reached execution despite terminal qualification"
            )
        if spec.repair is RepairMode.SELECTIVE:
            constructor = SelectiveLeanstralRepair(
                constructor,  # type: ignore[arg-type]
                client=client(RecoveryRoute.DIRECT),  # type: ignore[arg-type]
                policy=SelectiveRepairPolicy(),
            )

        if realizer_spec.mode is RealizerMode.DETERMINISTIC:
            realizer: object = SourceWithheldCanonicalParaphraser()
            realizer_config: Mapping[str, object] = (
                frozen_replacement_config()
            )
        else:
            realizer = model_recovery(
                RecoveryRoute(realizer_spec.route.value)
            )
            realizer_config = {}

        stages: list[dict[str, object]] = []
        l1_result, l1_stage = _invoke_constructor_stage(
            constructor,
            ConstructorRequest(
                case.source_text,
                case.allowed_atom_vocabulary,
                {},
            ),
            role=RecoveryRole.L1,
        )
        stages.append(l1_stage)
        if (
            l1_result.status is ComponentStatus.FAILED
            or l1_result.canonical_ir is None
        ):
            result = make_round_trip_result(
                case.gold_ir,
                None,
                None,
                None,
                failure_reason=(
                    l1_result.failure_reason or FailureReason.INVALID_OUTPUT
                ),
                failure_detail=l1_result.failure_detail,
            )
            return self._seal(
                case=case,
                cell_id=cell_id,
                repeat_index=repeat_index,
                cache_namespace=cache_namespace,
                result=result,
                stages=stages,
                constructor_identity=_component_identity(
                    constructor, "constructor"
                ),
                realizer_identity=_component_identity(realizer, "realizer"),
                disposition="executed_loss_one",
            )
        l1 = l1_result.canonical_ir

        t1_result, t1_stage = _invoke_realizer_stage(
            realizer,
            RealizerRequest(
                l1,
                case.allowed_atom_vocabulary,
                realizer_config,
            ),
        )
        stages.append(t1_stage)
        if t1_result.status is ComponentStatus.FAILED or t1_result.text is None:
            result = make_round_trip_result(
                case.gold_ir,
                l1,
                None,
                None,
                failure_reason=(
                    t1_result.failure_reason or FailureReason.INVALID_OUTPUT
                ),
                failure_detail=t1_result.failure_detail,
            )
            return self._seal(
                case=case,
                cell_id=cell_id,
                repeat_index=repeat_index,
                cache_namespace=cache_namespace,
                result=result,
                stages=stages,
                constructor_identity=_component_identity(
                    constructor, "constructor"
                ),
                realizer_identity=_component_identity(realizer, "realizer"),
                disposition="executed_loss_one",
            )
        reconstruction = t1_result.text

        l2_result, l2_stage = _invoke_constructor_stage(
            constructor,
            ConstructorRequest(
                reconstruction,
                case.allowed_atom_vocabulary,
                {},
            ),
            role=RecoveryRole.L2,
            expected_l1=l1,
        )
        stages.append(l2_stage)
        if (
            l2_result.status is ComponentStatus.FAILED
            or l2_result.canonical_ir is None
        ):
            result = make_round_trip_result(
                case.gold_ir,
                l1,
                reconstruction,
                None,
                failure_reason=(
                    l2_result.failure_reason or FailureReason.INVALID_OUTPUT
                ),
                failure_detail=l2_result.failure_detail,
            )
            disposition = "executed_loss_one"
        else:
            result = make_round_trip_result(
                case.gold_ir,
                l1,
                reconstruction,
                l2_result.canonical_ir,
            )
            disposition = "executed_complete"
        return self._seal(
            case=case,
            cell_id=cell_id,
            repeat_index=repeat_index,
            cache_namespace=cache_namespace,
            result=result,
            stages=stages,
            constructor_identity=_component_identity(
                constructor, "constructor"
            ),
            realizer_identity=_component_identity(realizer, "realizer"),
            disposition=disposition,
        )

    def run_coordinate(
        self,
        case: MatrixCase,
        cell_id: str,
        repeat_index: int,
        cache_namespace: str,
    ) -> ReplacementCoordinateExecution:
        """Execute one exact frozen coordinate with explicit L1/T1/L2 roles."""

        if not isinstance(case, MatrixCase):
            raise ContractError("case must be MatrixCase")
        if (
            case.case_id not in self._case_cids
            or self._case_cids[case.case_id] != case.case_cid
        ):
            raise ContractError(
                "case differs from the frozen five-case fixture"
            )
        if cell_id not in self._specs:
            raise ContractError("cell_id is absent from the frozen plan")
        expected_namespace = self.cache_namespace_for(
            case_id=case.case_id,
            cell_id=cell_id,
            repeat_index=repeat_index,
        )
        if (
            not isinstance(cache_namespace, str)
            or cache_namespace != expected_namespace
        ):
            raise ContractError(
                "cache_namespace differs from the frozen coordinate"
            )
        model_backed = bool(self._arms[cell_id]["model_backed"])
        if model_backed:
            with _REPLACEMENT_MODEL_LOCK:
                return self._execute(
                    case=case,
                    cell_id=cell_id,
                    repeat_index=repeat_index,
                    cache_namespace=cache_namespace,
                )
        return self._execute(
            case=case,
            cell_id=cell_id,
            repeat_index=repeat_index,
            cache_namespace=cache_namespace,
        )


def build_balanced_model_schedule(
    *,
    model_arm_ids: Sequence[str],
    case_ids: Sequence[str],
    plan_cid: str,
) -> dict[str, object]:
    """Freeze a nearly position-balanced, outcome-independent one-slot order."""

    arms = tuple(model_arm_ids)
    cases = tuple(case_ids)
    if (
        len(arms) != 26
        or len(set(arms)) != 26
        or len(cases) != 5
        or len(set(cases)) != 5
    ):
        raise ReplacementQualificationError(
            "balanced schedule requires 26 model arms and five cases"
        )
    _require_cid(plan_cid, codec="dag-json", label="replacement plan CID")
    blocks: list[dict[str, object]] = []
    namespaces: set[str] = set()
    block_index = 0
    for case_id in cases:
        for repeat_index in range(MODEL_REPEAT_COUNT):
            offset = block_index % len(arms)
            order = [*arms[offset:], *arms[:offset]]
            coordinates: list[dict[str, object]] = []
            for arm_id in order:
                namespace_cid = cid_for_dag_json(
                    {
                        "plan_cid": plan_cid,
                        "case_id": case_id,
                        "repeat_index": repeat_index,
                        "arm_id": arm_id,
                        "cache_mode": "uncached",
                    }
                )
                namespace = f"srt-replacement-uncached-{namespace_cid}"
                if namespace in namespaces:
                    raise ReplacementQualificationError(
                        "replacement cache namespaces must be unique"
                    )
                namespaces.add(namespace)
                coordinates.append(
                    {
                        "arm_id": arm_id,
                        "cache_mode": "uncached",
                        "cache_namespace": namespace,
                    }
                )
            blocks.append(
                {
                    "block_index": block_index,
                    "case_id": case_id,
                    "repeat_index": repeat_index,
                    "rotation_offset": offset,
                    "arm_order": order,
                    "coordinates": coordinates,
                }
            )
            block_index += 1
    payload: dict[str, object] = {
        "interface": "ReplacementBalancedModelSchedule@1",
        "algorithm": "outcome_independent_cyclic_rotation_v1",
        "plan_cid": plan_cid,
        "case_ids": list(cases),
        "model_arm_ids": list(arms),
        "repeat_count": MODEL_REPEAT_COUNT,
        "physical_model_slots": PHYSICAL_MODEL_SLOT_COUNT,
        "serialization": "strict_single_slot",
        "cache_policy": "unique_uncached_namespace_per_coordinate",
        "block_count": len(blocks),
        "coordinate_count": len(namespaces),
        "blocks": blocks,
    }
    return _cid_receipt(payload, "schedule_cid")


def _validate_balanced_schedule(
    schedule: Mapping[str, object],
    *,
    model_arm_ids: Sequence[str],
    case_ids: Sequence[str],
    plan_cid: str,
) -> dict[str, object]:
    expected = build_balanced_model_schedule(
        model_arm_ids=model_arm_ids,
        case_ids=case_ids,
        plan_cid=plan_cid,
    )
    supplied = _json_clone(dict(schedule))
    if supplied != expected:
        raise ReplacementQualificationError(
            "replacement schedule differs from the frozen balanced schedule"
        )
    blocks = supplied["blocks"]
    assert isinstance(blocks, list)
    arms = list(model_arm_ids)
    for position in range(len(arms)):
        counts = Counter(
            block["arm_order"][position]  # type: ignore[index]
            for block in blocks
        )
        observed = [counts[arm] for arm in arms]
        if max(observed) - min(observed) > 1:
            raise ReplacementQualificationError(
                "replacement schedule is not position balanced"
            )
    return supplied


def build_replacement_qualification(
    *,
    repo_root: Path = REPO_ROOT,
    model_smokes: Mapping[str, object],
) -> dict[str, object]:
    """Build one exact replacement qualification from current evidence."""

    root = Path(repo_root).resolve()
    inventory_path = root / DEFAULT_CAPABILITY_INVENTORY_RELATIVE_PATH
    inventory = load_inventory(inventory_path)
    capability_bindings = _capability_bindings(inventory)
    adapters = _adapter_bindings(root)
    fixture_binding, cases = _fixture_binding(root)
    causal = load_causal_guidance_qualification(
        root / DEFAULT_CAUSAL_QUALIFICATION_RELATIVE_PATH,
        repo_root=root,
    )
    validated_smokes = _validate_model_smokes(model_smokes)
    deterministic_smoke = run_deterministic_pilot_smoke(cases)
    arms, deterministic_ids, model_ids = _arm_qualifications(
        capability_bindings,
        adapters,
        validated_smokes,
        deterministic_smoke,
    )
    qualified = [
        record["cell_id"]
        for record in arms
        if record["qualification_status"] == QUALIFIED_CANDIDATE
    ]
    unsupported = [
        record["cell_id"]
        for record in arms
        if record["qualification_status"] == TERMINAL_UNSUPPORTED
    ]
    unavailable = [
        record["cell_id"]
        for record in arms
        if record["qualification_status"] == CAPABILITY_UNAVAILABLE
    ]
    if not qualified:
        raise ReplacementQualificationError(
            "at least one fully qualified replacement candidate is required"
        )
    plan_body: dict[str, object] = {
        "interface": QUALIFIED_REPLACEMENT_MATRIX_INTERFACE,
        "historical_plan_preserved": True,
        "constructor_by_realizer_intent_preserved": True,
        "cell_count": 30,
        "deterministic_cell_ids": deterministic_ids,
        "model_backed_cell_ids": model_ids,
        "arms": arms,
        "validation_overlays": [
            overlay.to_dict()
            for overlay in DEFAULT_EXTENDED_MATRIX_PLAN.validation_overlays
        ],
        "typed_omissions": [
            omission.to_dict()
            for omission in DEFAULT_EXTENDED_MATRIX_PLAN.omissions
        ],
        "loss_policy": {
            "primary": "end_to_end",
            "aggregation": "per_case_first_macro_mean",
            "failure_loss": 1.0,
            "missing_coordinate_allowed": False,
        },
        "selection_gates": list(SELECTION_GATE_IDS),
        "source_withheld_realizer_boundary": True,
        "physical_model_slots": PHYSICAL_MODEL_SLOT_COUNT,
        "coordinate_execution": {
            "interface": REPLACEMENT_COORDINATE_RUNNER_INTERFACE,
            "receipt_schema": REPLACEMENT_COORDINATE_RECEIPT_SCHEMA,
            "factory": "build_replacement_coordinate_runner",
            "method": "run_coordinate",
            "arguments": [
                "case",
                "cell_id",
                "repeat_index",
                "cache_namespace",
            ],
            "role_dispatch": {
                "l1": "recover_l1",
                "t1": "recover_t1",
                "l2": "recover_l2_requires_exact_l1",
            },
            "deterministic_realizer_configuration_cid": (
                FROZEN_REPLACEMENT_CONFIG_CID
            ),
            "terminal_unsupported_is_typed_loss_one": True,
            "native_stage_receipts_required": True,
            "post_hoc_validation_receipts_required": True,
            "frozen_coordinate_count": 670,
        },
    }
    plan = _cid_receipt(plan_body, "plan_cid")
    schedule = build_balanced_model_schedule(
        model_arm_ids=model_ids,
        case_ids=fixture_binding["case_ids"],  # type: ignore[arg-type]
        plan_cid=plan["plan_cid"],  # type: ignore[arg-type]
    )
    capability_payload = inventory.to_dict()
    causal_raw = _raw_file_binding(
        root, DEFAULT_CAUSAL_QUALIFICATION_RELATIVE_PATH
    )
    causal_raw["qualification_cid"] = causal["qualification_cid"]
    payload: dict[str, object] = {
        "schema_version": REPLACEMENT_QUALIFICATION_SCHEMA,
        "interface": QUALIFIED_REPLACEMENT_MATRIX_INTERFACE,
        "status": "qualified_with_explicit_terminal_paths",
        "frozen_before_scored_execution": True,
        "lineage": {
            "capability_inventory": {
                **_raw_file_binding(
                    root, DEFAULT_CAPABILITY_INVENTORY_RELATIVE_PATH
                ),
                "inventory_cid": cid_for_dag_json(capability_payload),
            },
            "causal_guidance": causal_raw,
            "fixture": fixture_binding,
            "protocol": _raw_file_binding(
                root, DEFAULT_PROTOCOL_RELATIVE_PATH
            ),
            "historical": _historical_binding(root),
        },
        "bindings": {
            "capabilities": capability_bindings,
            "adapters": adapters,
            "identity_policy": {
                "fallback_allowed": False,
                "substitute_allowed": False,
                "degraded_identity_allowed": False,
                "ambiguous_identity_allowed": False,
                "duplicate_arm_identity_allowed": False,
                "all_structured_and_byte_evidence_uses_cids": True,
            },
        },
        "smokes": {
            "deterministic_five_case": deterministic_smoke,
            "model_routes": validated_smokes,
            "scored": False,
        },
        "plan": plan,
        "schedule": schedule,
        "summary": {
            "cell_count": 30,
            "deterministic_cell_count": 4,
            "model_backed_cell_count": 26,
            "qualified_candidate_count": len(qualified),
            "qualified_candidate_arm_ids": qualified,
            "terminal_unsupported_count": len(unsupported),
            "terminal_unsupported_arm_ids": unsupported,
            "capability_unavailable_count": len(unavailable),
            "capability_unavailable_arm_ids": unavailable,
            "at_least_one_fully_qualified_candidate": True,
            "selection_eligibility_requires_scored_execution": True,
        },
    }
    return _cid_receipt(payload, "qualification_cid")


def validate_replacement_qualification(
    value: Mapping[str, object],
    *,
    repo_root: Path = REPO_ROOT,
) -> dict[str, object]:
    """Validate a checked receipt against fresh repository-bound evidence."""

    if not isinstance(value, Mapping):
        raise ReplacementQualificationError(
            "replacement qualification must be an object"
        )
    supplied = _json_clone(dict(value))
    qualification_cid = _require_cid(
        supplied.get("qualification_cid"),
        codec="dag-json",
        label="replacement qualification CID",
    )
    body = dict(supplied)
    del body["qualification_cid"]
    if cid_for_dag_json(body) != qualification_cid:
        raise ReplacementQualificationError(
            "replacement qualification CID does not match its payload"
        )
    smokes_container = supplied.get("smokes")
    if not isinstance(smokes_container, dict):
        raise ReplacementQualificationError("replacement smokes are missing")
    model_smokes = smokes_container.get("model_routes")
    if not isinstance(model_smokes, dict):
        raise ReplacementQualificationError(
            "replacement model smokes are missing"
        )
    expected = build_replacement_qualification(
        repo_root=repo_root,
        model_smokes=model_smokes,
    )
    if supplied != expected:
        raise ReplacementQualificationError(
            "replacement qualification contradicts fresh bound evidence"
        )
    plan = supplied["plan"]
    schedule = supplied["schedule"]
    assert isinstance(plan, dict) and isinstance(schedule, dict)
    summary = supplied["summary"]
    assert isinstance(summary, dict)
    _validate_balanced_schedule(
        schedule,
        model_arm_ids=plan["model_backed_cell_ids"],  # type: ignore[arg-type]
        case_ids=supplied["lineage"]["fixture"]["case_ids"],  # type: ignore[index]
        plan_cid=plan["plan_cid"],  # type: ignore[arg-type]
    )
    if summary["at_least_one_fully_qualified_candidate"] is not True:
        raise ReplacementQualificationError(
            "qualification contains no fully qualified candidate"
        )
    return expected


def load_replacement_qualification(
    path: Path = DEFAULT_REPLACEMENT_QUALIFICATION_PATH,
    *,
    repo_root: Path = REPO_ROOT,
) -> dict[str, object]:
    value = _strict_object(Path(path), "replacement qualification")
    return validate_replacement_qualification(value, repo_root=repo_root)


def build_replacement_coordinate_runner(
    qualification: Mapping[str, object] | None = None,
    *,
    client_factories: Mapping[
        RecoveryRoute | str, Callable[[], object]
    ]
    | None = None,
    validators: Mapping[str, PostHocValidator] | None = None,
    qualification_path: Path = DEFAULT_REPLACEMENT_QUALIFICATION_PATH,
    repo_root: Path = REPO_ROOT,
) -> ReplacementCoordinateRunner:
    """Build SRT-026's runner from one checked qualification artifact."""

    checked = (
        load_replacement_qualification(
            qualification_path,
            repo_root=repo_root,
        )
        if qualification is None
        else qualification
    )
    return ReplacementCoordinateRunner(
        checked,
        client_factories=client_factories,
        validators=validators,
    )


def canonical_qualification_json(value: Mapping[str, object]) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
    )
    parser.add_argument(
        "--validate",
        type=Path,
        help="Validate an existing receipt without model inference.",
    )
    parser.add_argument(
        "--run-live-smokes",
        action="store_true",
        help="Run sequential strict-schema direct and SyMAI preflight calls.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = args.repo_root.resolve()
        if args.validate is not None:
            value = load_replacement_qualification(
                args.validate, repo_root=root
            )
        elif args.run_live_smokes:
            causal = load_causal_guidance_qualification(
                root / DEFAULT_CAUSAL_QUALIFICATION_RELATIVE_PATH,
                repo_root=root,
            )
            value = build_replacement_qualification(
                repo_root=root,
                model_smokes=run_live_model_smokes(causal),
            )
        else:
            raise ReplacementQualificationError(
                "use --run-live-smokes to create evidence or --validate"
            )
        print(canonical_qualification_json(value), end="")
        return 0
    except (ContractError, OSError, ValueError) as exc:
        print(f"replacement qualification failed: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CAPABILITY_UNAVAILABLE",
    "DEFAULT_REPLACEMENT_QUALIFICATION_PATH",
    "DEFAULT_REPLACEMENT_QUALIFICATION_RELATIVE_PATH",
    "MODEL_REPEAT_COUNT",
    "PHYSICAL_MODEL_SLOT_COUNT",
    "QUALIFIED_CANDIDATE",
    "QUALIFIED_REPLACEMENT_MATRIX_INTERFACE",
    "REPLACEMENT_COORDINATE_RECEIPT_SCHEMA",
    "REPLACEMENT_COORDINATE_RUNNER_INTERFACE",
    "REPLACEMENT_QUALIFICATION_SCHEMA",
    "ROLE_AWARE_MODEL_RECOVERY_INTERFACE",
    "TERMINAL_UNSUPPORTED",
    "ReplacementQualificationError",
    "ReplacementCoordinateExecution",
    "ReplacementCoordinateRunner",
    "RoleAwareModelRecovery",
    "build_balanced_model_schedule",
    "build_replacement_coordinate_runner",
    "build_replacement_qualification",
    "canonical_qualification_json",
    "load_replacement_qualification",
    "run_deterministic_pilot_smoke",
    "run_live_model_smokes",
    "validate_replacement_qualification",
]
