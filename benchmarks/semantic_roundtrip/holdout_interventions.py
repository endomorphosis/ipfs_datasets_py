"""PLAT2-035 freeze: preregister intervention roles, capabilities, and ablations.

Interfaces:
* ``Plateau2InterventionRegistry@1`` — outcome-independent residual → intervention
  plan bound to the PLAT2-025 experiment contract
* ``SemanticRoundtripCapabilityRecord@1`` — exact version/model/route/toolchain
  identity plus method status for every heterogeneous method

Doctrine (frozen):

* **Deterministic compiler / IR / decompiler** is the sole production edit target
  (``typed_deontic → IR → deterministic realizer``).
* **Autoencoder** is bounded causal guidance **only** when its reviewed adapter
  is ``scored_supported``; otherwise guided cells remain
  ``not_measured`` / ``terminal_unsupported``.
* **spaCy** is non-authoritative diagnostics.
* **SyMAI** is orchestration / routing only (no proof credit).
* **Leanstral** is a proposal teacher (direct route identity distinct from SyMAI).
* **Hammer / cvc5 / Lean** are declared structural gates with
  ``semantic_authority: false``.

Every method carries an exact identity and one of
``semantic_scored`` / ``not_measured`` / ``runtime_failed`` /
``terminal_unsupported`` / ``not_selected``, backed by PLAT evidence or a
bounded capability smoke. Health-only probes cannot establish model inference.

Each repair-development residual maps to the smallest preregistered
intervention, a negative control, and the per-wave / cumulative ablations
needed for attribution. Full matrix reruns require an explicit evidence-backed
override. Blind data and outcome-dependent selection are forbidden.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_dag_json,
    validate_cid,
)
from benchmarks.semantic_roundtrip.constructors.causal_autoencoder_guidance import (
    DEFAULT_QUALIFICATION_RELATIVE_PATH as AE_QUALIFICATION_RELATIVE_PATH,
    SCORED_SUPPORTED,
    TERMINAL_UNSUPPORTED as AE_TERMINAL_UNSUPPORTED,
    UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER,
)
from benchmarks.semantic_roundtrip.contracts import ContractError
from benchmarks.semantic_roundtrip.holdout_baseline import (
    DEFAULT_BASELINE_REPORT_RELATIVE_PATH,
    EVAL_STATUS_NOT_MEASURED,
    EVAL_STATUS_RUNTIME_FAILED,
    EVAL_STATUS_SEMANTIC_SCORED,
    EVAL_STATUS_UNSUPPORTED,
    EXPERIMENT_FAMILY,
    PLATEAU2_EXPERIMENT_CONTRACT_INTERFACE,
    POST_PLAT_BASELINE_E2E_MEAN,
    POST_PLAT_BASELINE_REPORT_CID,
    PRODUCTION_ARM_ID,
    PRODUCTION_CONSTRUCTOR_IDENTITY,
    PRODUCTION_REALIZER_IDENTITY,
    assert_blind_seal_unopened,
    load_repair_dev_baseline_report,
)
from benchmarks.semantic_roundtrip.holdout_protocol import (
    load_frozen_blind_holdout_seal,
)
from benchmarks.semantic_roundtrip.residual_catalog import (
    BASELINE_ARM_ID,
    BASELINE_CONSTRUCTOR_IDENTITY,
    DEFAULT_REPAIR_DEV_CATALOG_RELATIVE_PATH,
    HOLDOUT_BASELINE_REPORT_CID,
    POPULATION_KIND_REPAIR_DEVELOPMENT,
    load_repair_dev_residual_catalog,
)
from benchmarks.semantic_roundtrip_capabilities import (
    AUTOENCODER_STATE_CID,
    AUTOENCODER_STATE_SHA256,
    CAPABILITY_IDS,
    DEFAULT_OUTPUT as CAPABILITIES_DEFAULT_OUTPUT,
    LEANSTRAL_BACKEND,
    LEANSTRAL_ENDPOINT,
    LEANSTRAL_MODEL,
    LEANSTRAL_PROVIDER,
    SPACY_MODEL,
    SPACY_MODEL_VERSION,
    SPACY_VERSION,
    SYMAI_MODEL_ALIAS,
    SYMAI_PROVIDER,
    SYMAI_VERSION,
)


# ---------------------------------------------------------------------------
# Interfaces / schemas
# ---------------------------------------------------------------------------

PLATEAU2_INTERVENTION_REGISTRY_INTERFACE: Final = (
    "Plateau2InterventionRegistry@1"
)
PLATEAU2_INTERVENTION_REGISTRY_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-plateau2-intervention-registry.v1"
)
SEMANTIC_ROUNDTRIP_CAPABILITY_RECORD_INTERFACE: Final = (
    "SemanticRoundtripCapabilityRecord@1"
)
SEMANTIC_ROUNDTRIP_CAPABILITY_RECORD_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-capability-record.v1"
)
RESIDUAL_INTERVENTION_MAPPING_INTERFACE: Final = (
    "Plateau2ResidualInterventionMapping@1"
)
FULL_MATRIX_OVERRIDE_INTERFACE: Final = "Plateau2FullMatrixOverride@1"

REGISTRY_CID_SCOPE: Final = "payload_without_registry_cid"
CID_CODEC: Final = "dag-json"

DEFAULT_REGISTRY_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "repair_dev_intervention_registry.json"
)
DEFAULT_REGISTRY_DOCS_RELATIVE_PATH: Final = Path(
    "docs/benchmarks/semantic_roundtrip_plateau2_interventions.md"
)
CAPABILITIES_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/capabilities.json"
)

# ---------------------------------------------------------------------------
# Task identity
# ---------------------------------------------------------------------------

INTERVENTION_TASK_ID: Final = "PLAT2-035"
INTERVENTION_GOAL_ID: Final = "PLAT2-G035"
INTERVENTION_EVIDENCE_ID: Final = "PLAT2EV035INT"
INTERVENTION_REVISION: Final = 1
BOARD_NAMESPACE: Final = "semantic-roundtrip-plateau-holdout-v2"

# ---------------------------------------------------------------------------
# Method status taxonomy (mutually exclusive)
# ---------------------------------------------------------------------------

METHOD_STATUS_SEMANTIC_SCORED: Final = EVAL_STATUS_SEMANTIC_SCORED
METHOD_STATUS_NOT_MEASURED: Final = EVAL_STATUS_NOT_MEASURED
METHOD_STATUS_RUNTIME_FAILED: Final = EVAL_STATUS_RUNTIME_FAILED
METHOD_STATUS_TERMINAL_UNSUPPORTED: Final = "terminal_unsupported"
METHOD_STATUS_NOT_SELECTED: Final = "not_selected"
METHOD_STATUSES: Final = frozenset(
    {
        METHOD_STATUS_SEMANTIC_SCORED,
        METHOD_STATUS_NOT_MEASURED,
        METHOD_STATUS_RUNTIME_FAILED,
        METHOD_STATUS_TERMINAL_UNSUPPORTED,
        METHOD_STATUS_NOT_SELECTED,
    }
)

# Catalog uses ``unsupported``; method registry uses the more specific
# ``terminal_unsupported`` token from the PLAT matrix vocabulary.
assert METHOD_STATUS_TERMINAL_UNSUPPORTED != EVAL_STATUS_UNSUPPORTED

# ---------------------------------------------------------------------------
# Method roles (preregistered, outcome-independent)
# ---------------------------------------------------------------------------

ROLE_PRODUCTION_EDIT_TARGET: Final = "production_edit_target"
ROLE_CAUSAL_GUIDANCE: Final = "causal_guidance_only_when_scored_supported"
ROLE_NON_AUTHORITATIVE_DIAGNOSTICS: Final = "non_authoritative_diagnostics"
ROLE_ORCHESTRATION_ROUTING: Final = "orchestration_routing_only"
ROLE_PROPOSAL_TEACHER: Final = "proposal_teacher"
ROLE_STRUCTURAL_GATE: Final = "structural_gate"

METHOD_DETERMINISTIC_COMPILER: Final = "deterministic_compiler_ir_decompiler"
METHOD_AUTOENCODER: Final = "autoencoder"
METHOD_SPACY: Final = "spacy"
METHOD_SYMAI: Final = "symai"
METHOD_LEANSTRAL: Final = "leanstral"
METHOD_HAMMER: Final = "hammer"
METHOD_CVC5: Final = "cvc5"
METHOD_LEAN: Final = "lean"

METHOD_IDS: Final = (
    METHOD_DETERMINISTIC_COMPILER,
    METHOD_AUTOENCODER,
    METHOD_SPACY,
    METHOD_SYMAI,
    METHOD_LEANSTRAL,
    METHOD_HAMMER,
    METHOD_CVC5,
    METHOD_LEAN,
)

METHOD_ROLE_BY_ID: Final = MappingProxyType(
    {
        METHOD_DETERMINISTIC_COMPILER: ROLE_PRODUCTION_EDIT_TARGET,
        METHOD_AUTOENCODER: ROLE_CAUSAL_GUIDANCE,
        METHOD_SPACY: ROLE_NON_AUTHORITATIVE_DIAGNOSTICS,
        METHOD_SYMAI: ROLE_ORCHESTRATION_ROUTING,
        METHOD_LEANSTRAL: ROLE_PROPOSAL_TEACHER,
        METHOD_HAMMER: ROLE_STRUCTURAL_GATE,
        METHOD_CVC5: ROLE_STRUCTURAL_GATE,
        METHOD_LEAN: ROLE_STRUCTURAL_GATE,
    }
)

# Production edit target is the only method with semantic composition authority.
SEMANTIC_AUTHORITY_BY_METHOD: Final = MappingProxyType(
    {
        METHOD_DETERMINISTIC_COMPILER: True,
        METHOD_AUTOENCODER: False,
        METHOD_SPACY: False,
        METHOD_SYMAI: False,
        METHOD_LEANSTRAL: False,
        METHOD_HAMMER: False,
        METHOD_CVC5: False,
        METHOD_LEAN: False,
    }
)

# Capability inventory id ↔ registry method id (structural gates split).
CAPABILITY_ID_BY_METHOD: Final = MappingProxyType(
    {
        METHOD_AUTOENCODER: "autoencoder_state",
        METHOD_SPACY: "spacy_pipeline",
        METHOD_SYMAI: "symai_leanstral_route",
        METHOD_LEANSTRAL: "leanstral_direct",
        METHOD_HAMMER: "hammer_cvc5",
        METHOD_CVC5: "hammer_cvc5",
        METHOD_LEAN: "lean",
    }
)

# ---------------------------------------------------------------------------
# Intervention kinds / negative controls / ablations
# ---------------------------------------------------------------------------

INTERVENTION_DET_MISSING_RULE: Final = "det_compiler_missing_rule_hypothesis"
INTERVENTION_DET_FIELD_MISSING: Final = "det_compiler_field_fill_hypothesis"
INTERVENTION_DET_FIELD_CONTRADICTORY: Final = (
    "det_compiler_field_rewrite_hypothesis"
)
INTERVENTION_KINDS: Final = frozenset(
    {
        INTERVENTION_DET_MISSING_RULE,
        INTERVENTION_DET_FIELD_MISSING,
        INTERVENTION_DET_FIELD_CONTRADICTORY,
    }
)

NEGATIVE_CONTROL_NO_EDIT: Final = "nc_no_edit"
NEGATIVE_CONTROL_WITHHOLD_TEACHER: Final = "nc_withhold_optional_teacher"
NEGATIVE_CONTROL_IDS: Final = frozenset(
    {
        NEGATIVE_CONTROL_NO_EDIT,
        NEGATIVE_CONTROL_WITHHOLD_TEACHER,
    }
)

ADVISORY_SPACY_DIAGNOSTICS: Final = "adv_spacy_diagnostics"
ADVISORY_LEANSTRAL_PROPOSAL: Final = "adv_leanstral_proposal"
ADVISORY_AE_GUIDANCE: Final = "adv_ae_causal_guidance"
ADVISORY_IDS: Final = frozenset(
    {
        ADVISORY_SPACY_DIAGNOSTICS,
        ADVISORY_LEANSTRAL_PROPOSAL,
        ADVISORY_AE_GUIDANCE,
    }
)

STRUCTURAL_GATE_IDS: Final = frozenset(
    {METHOD_HAMMER, METHOD_CVC5, METHOD_LEAN}
)

RESIDUAL_KIND_MISSING_RULE: Final = "missing_rule"
RESIDUAL_KIND_FIELD_MISMATCH: Final = "field_mismatch"
RESIDUAL_KIND_EXTRA_RULE: Final = "extra_rule"
PROJECTABLE_RESIDUAL_KINDS: Final = frozenset(
    {
        RESIDUAL_KIND_MISSING_RULE,
        RESIDUAL_KIND_FIELD_MISMATCH,
        RESIDUAL_KIND_EXTRA_RULE,
    }
)

TRIGGER_MISSING: Final = "missing"
TRIGGER_CONTRADICTORY: Final = "contradictory"
TRIGGER_LOW_CONFIDENCE: Final = "low_confidence"

DEFAULT_ASSUMPTIONS: Final = (
    "production remains typed_deontic → IR → deterministic realizer",
    "deterministic compiler/IR/decompiler is the sole production edit target",
    "autoencoder is causal guidance only when reviewed adapter is scored_supported",
    "spaCy is non-authoritative diagnostics only",
    "SyMAI is orchestration/routing only and cannot receive proof credit",
    "Leanstral is a proposal teacher; direct and SyMAI route identities stay distinct",
    "Hammer/cvc5/Lean are structural gates with semantic_authority false",
    "health-only probes cannot establish model inference",
    "unsupported/not_measured/runtime_failed/terminal_unsupported never enter "
    "semantic score aggregates",
    "residual → intervention mapping is preregistered and outcome-independent",
    "full matrix reruns require an explicit evidence-backed override",
    "blind sources/gold/residuals remain inaccessible without post-freeze "
    "evaluator authorization",
    "no outcome-dependent selection or blind data may drive method choice",
)


class HoldoutInterventionError(ContractError):
    """Raised when the intervention registry fails validation."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _require(condition: object, message: str) -> None:
    if not condition:
        raise HoldoutInterventionError(message)


def _nonblank(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HoldoutInterventionError(f"{path} must be a nonblank string")
    return value.strip()


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HoldoutInterventionError(f"{path} must be an object")
    return value


def _array(value: object, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise HoldoutInterventionError(f"{path} must be an array")
    return value


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(k): _plain_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    if isinstance(value, Path):
        return str(value).replace("\\", "/")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _cid(value: object, path: str) -> str:
    text = _nonblank(value, path)
    try:
        return validate_cid(text, codecs=(CID_CODEC, "raw"))
    except (TypeError, ValueError) as exc:
        raise HoldoutInterventionError(
            f"{path} must be a canonical content-addressed CID"
        ) from exc


def residual_identity_key(residual: Mapping[str, Any]) -> str:
    """Stable residual identity for mapping / ablation ordering."""

    case_id = _nonblank(residual.get("case_id"), "residual.case_id")
    field_path = _nonblank(residual.get("field_path"), "residual.field_path")
    residual_kind = _nonblank(
        residual.get("residual_kind"), "residual.residual_kind"
    )
    return f"{case_id}::{field_path}::{residual_kind}"


def residual_mapping_id(residual: Mapping[str, Any]) -> str:
    """Content-addressed residual mapping id (short dag-json CID)."""

    payload = {
        "case_id": residual.get("case_id"),
        "field_path": residual.get("field_path"),
        "residual_kind": residual.get("residual_kind"),
        "canonical_field": residual.get("canonical_field"),
        "suggested_trigger_kind": residual.get("suggested_trigger_kind"),
        "candidate_rule_index": residual.get("candidate_rule_index"),
        "gold_rule_index": residual.get("gold_rule_index"),
        "loss_contribution": residual.get("loss_contribution"),
    }
    return cid_for_dag_json(_plain_json(payload))


# ---------------------------------------------------------------------------
# Health-only / model-inference policy
# ---------------------------------------------------------------------------


def health_only_establishes_model_inference(
    *,
    health_only: bool,
    model_inference_performed: bool | None,
) -> bool:
    """Return True only when non-health-only smoke established inference.

    Health-only probes **cannot** establish model inference (fail-closed).
    """

    if health_only:
        return False
    return model_inference_performed is True


def assert_health_only_cannot_establish_model_inference(
    record: Mapping[str, Any],
    *,
    path: str = "capability_record",
) -> None:
    """Reject capability/method records that claim inference from health-only."""

    checks = record.get("checks")
    if not isinstance(checks, Mapping):
        checks = {}
    identity = record.get("identity")
    if not isinstance(identity, Mapping):
        identity = {}
    health_only = bool(
        checks.get("health_only")
        or identity.get("health_only")
        or record.get("health_only")
    )
    inference_claim = (
        checks.get("model_inference_performed")
        if "model_inference_performed" in checks
        else record.get("model_inference_established")
    )
    if health_only and inference_claim is True:
        raise HoldoutInterventionError(
            f"{path}: health-only probes cannot establish model inference"
        )


# ---------------------------------------------------------------------------
# Capability inventory load (frozen PLAT smoke; no live probes)
# ---------------------------------------------------------------------------


def load_frozen_capability_inventory(
    path: str | Path | None = None,
    *,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Load the frozen PLAT capability inventory without re-probing."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    inventory_path = (
        Path(path)
        if path is not None
        else root / CAPABILITIES_RELATIVE_PATH
    )
    if not inventory_path.is_file():
        # Fall back to module default absolute path if relative missing.
        inventory_path = CAPABILITIES_DEFAULT_OUTPUT
    _require(
        inventory_path.is_file(),
        f"capability inventory missing at {inventory_path}",
    )
    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    data = dict(_mapping(payload, "capability inventory"))
    caps = _array(data.get("capabilities"), "capabilities")
    by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(caps):
        row = dict(_mapping(item, f"capabilities[{index}]"))
        cap_id = _nonblank(row.get("id"), f"capabilities[{index}].id")
        by_id[cap_id] = row
    for required in CAPABILITY_IDS:
        _require(
            required in by_id,
            f"capability inventory missing required id {required!r}",
        )
    data["_by_id"] = by_id
    return data


def load_ae_qualification(
    path: str | Path | None = None,
    *,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Load the frozen causal autoencoder guidance qualification receipt."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    qual_path = (
        Path(path)
        if path is not None
        else root / AE_QUALIFICATION_RELATIVE_PATH
    )
    _require(qual_path.is_file(), f"AE qualification missing at {qual_path}")
    payload = json.loads(qual_path.read_text(encoding="utf-8"))
    return dict(_mapping(payload, "ae qualification"))


def _capability_checks(cap: Mapping[str, Any]) -> dict[str, Any]:
    checks = cap.get("checks")
    if isinstance(checks, Mapping):
        return dict(checks)
    return {}


def _capability_effective(cap: Mapping[str, Any]) -> dict[str, Any]:
    effective = cap.get("effective_identity")
    if isinstance(effective, Mapping):
        return dict(effective)
    return {}


def _capability_requested(cap: Mapping[str, Any]) -> dict[str, Any]:
    requested = cap.get("requested_identity")
    if isinstance(requested, Mapping):
        return dict(requested)
    return {}


def _model_inference_from_capability(cap: Mapping[str, Any]) -> bool:
    checks = _capability_checks(cap)
    health_only = bool(checks.get("health_only"))
    performed = checks.get("model_inference_performed")
    return health_only_establishes_model_inference(
        health_only=health_only,
        model_inference_performed=(
            performed if isinstance(performed, bool) else None
        ),
    )


def _status_from_capability_availability(
    cap: Mapping[str, Any],
    *,
    role_status_when_available: str,
) -> tuple[str, str]:
    """Map inventory availability to a method status + reason."""

    status = str(cap.get("status") or "")
    reason = cap.get("reason")
    reason_text = (
        str(reason).strip()
        if isinstance(reason, str) and reason.strip()
        else ""
    )
    if status == "available":
        if role_status_when_available not in METHOD_STATUSES:
            raise HoldoutInterventionError(
                f"invalid role_status_when_available: {role_status_when_available!r}"
            )
        return role_status_when_available, (
            reason_text or "capability_available_role_not_production_edit"
        )
    # Unavailable — classify failure mode when possible.
    lower = reason_text.lower()
    if any(
        token in lower
        for token in (
            "timeout",
            "connection",
            "runtime",
            "exception",
            "error",
            "failed",
        )
    ):
        return METHOD_STATUS_RUNTIME_FAILED, (
            reason_text or "capability_runtime_failed"
        )
    if any(
        token in lower
        for token in ("unsupported", "terminal", "unavailable", "missing")
    ):
        return METHOD_STATUS_TERMINAL_UNSUPPORTED, (
            reason_text or "capability_terminal_unsupported"
        )
    return METHOD_STATUS_NOT_MEASURED, (
        reason_text or "capability_not_measured"
    )


# ---------------------------------------------------------------------------
# Method / capability records
# ---------------------------------------------------------------------------


def build_method_capability_record(
    method_id: str,
    *,
    inventory: Mapping[str, Any] | None = None,
    ae_qualification: Mapping[str, Any] | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Build one ``SemanticRoundtripCapabilityRecord@1`` for a registry method."""

    _require(method_id in METHOD_IDS, f"unknown method_id: {method_id!r}")
    root = Path(repo_root) if repo_root is not None else _repo_root()
    inv = (
        dict(inventory)
        if inventory is not None
        else load_frozen_capability_inventory(repo_root=root)
    )
    by_id = inv.get("_by_id")
    if not isinstance(by_id, Mapping):
        by_id = {
            item["id"]: item
            for item in inv.get("capabilities", [])
            if isinstance(item, Mapping) and "id" in item
        }
    ae_qual = (
        dict(ae_qualification)
        if ae_qualification is not None
        else load_ae_qualification(repo_root=root)
    )

    role = METHOD_ROLE_BY_ID[method_id]
    semantic_authority = bool(SEMANTIC_AUTHORITY_BY_METHOD[method_id])

    if method_id == METHOD_DETERMINISTIC_COMPILER:
        record = {
            "interface": SEMANTIC_ROUNDTRIP_CAPABILITY_RECORD_INTERFACE,
            "schema_version": SEMANTIC_ROUNDTRIP_CAPABILITY_RECORD_SCHEMA,
            "method_id": method_id,
            "role": role,
            "semantic_authority": semantic_authority,
            "may_substitute_for_e2e": True,
            "is_production_edit_target": True,
            "status": METHOD_STATUS_SEMANTIC_SCORED,
            "status_reason": "post_plat_deterministic_baseline_semantic_scored",
            "identity": {
                "arm_id": PRODUCTION_ARM_ID,
                "constructor_identity": PRODUCTION_CONSTRUCTOR_IDENTITY,
                "realizer_identity": PRODUCTION_REALIZER_IDENTITY,
                "toolchain": "typed_deontic_compiler_ir_deterministic_realizer",
                "route": "not_applicable",
                "model": None,
                "version": "TypedDeonticCanonicalConstructor@1+"
                "CanonicalDeterministicRealizer@1",
            },
            "evidence": {
                "kind": "plat_baseline",
                "post_plat_baseline_e2e_mean": POST_PLAT_BASELINE_E2E_MEAN,
                "post_plat_baseline_report_cid": POST_PLAT_BASELINE_REPORT_CID,
                "baseline_arm_id": BASELINE_ARM_ID,
                "baseline_constructor_identity": BASELINE_CONSTRUCTOR_IDENTITY,
                "holdout_baseline_report_cid": HOLDOUT_BASELINE_REPORT_CID,
            },
            "health_only": False,
            "model_inference_established": False,
            "model_inference_required_for_role": False,
            "capability_inventory_id": None,
            "checks": {
                "health_only": False,
                "production_edit_target": True,
                "semantic_scored_on_deterministic_path": True,
            },
        }
        assert_health_only_cannot_establish_model_inference(
            record, path=f"method[{method_id}]"
        )
        return record

    if method_id == METHOD_AUTOENCODER:
        cap = dict(by_id.get("autoencoder_state") or {})
        eval_status = str(ae_qual.get("evaluation_status") or "")
        eval_reason = str(ae_qual.get("evaluation_status_reason") or "")
        causal = ae_qual.get("causal_contract")
        causal_map = dict(causal) if isinstance(causal, Mapping) else {}
        preregistered = bool(causal_map.get("preregistered"))
        reviewed_adapter = causal_map.get("reviewed_adapter_id")
        # Scored_supported requires a reviewed causal L1 adapter.
        guided = ae_qual.get("guided_coordinates")
        guided_map = dict(guided) if isinstance(guided, Mapping) else {}
        any_scored = False
        coordinates = guided_map.get("coordinates")
        if isinstance(coordinates, list):
            for coord in coordinates:
                if not isinstance(coord, Mapping):
                    continue
                if (
                    coord.get("status") == SCORED_SUPPORTED
                    or coord.get("evaluation_status") == SCORED_SUPPORTED
                ):
                    any_scored = True
                    break
        if any_scored and preregistered and reviewed_adapter:
            status = METHOD_STATUS_SEMANTIC_SCORED
            status_reason = "reviewed_causal_l1_adapter_scored_supported"
        elif eval_reason == AE_TERMINAL_UNSUPPORTED or (
            not preregistered
        ):
            status = METHOD_STATUS_TERMINAL_UNSUPPORTED
            status_reason = (
                eval_reason
                or UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER
            )
        elif eval_status == METHOD_STATUS_NOT_MEASURED:
            status = METHOD_STATUS_NOT_MEASURED
            status_reason = (
                eval_reason or UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER
            )
        else:
            status = METHOD_STATUS_TERMINAL_UNSUPPORTED
            status_reason = UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER

        effective = _capability_effective(cap)
        requested = _capability_requested(cap)
        record = {
            "interface": SEMANTIC_ROUNDTRIP_CAPABILITY_RECORD_INTERFACE,
            "schema_version": SEMANTIC_ROUNDTRIP_CAPABILITY_RECORD_SCHEMA,
            "method_id": method_id,
            "role": role,
            "semantic_authority": False,
            "may_substitute_for_e2e": False,
            "is_production_edit_target": False,
            "status": status,
            "status_reason": status_reason,
            "identity": {
                "state_cid": effective.get("cid")
                or requested.get("cid")
                or AUTOENCODER_STATE_CID,
                "state_sha256": effective.get("sha256")
                or requested.get("sha256")
                or AUTOENCODER_STATE_SHA256,
                "state_schema_version": effective.get("state_schema_version")
                or requested.get("state_schema_version"),
                "declared_architecture_version": effective.get(
                    "declared_architecture_version"
                )
                or requested.get("declared_architecture_version"),
                "effective_architecture_version": effective.get(
                    "effective_architecture_version"
                )
                or requested.get("effective_architecture_version"),
                "access": "read_only",
                "route": "causal_guidance_adapter",
                "model": "modal_autoencoder_stable_feature_export",
                "version": effective.get("state_schema_version")
                or "modal-autoencoder-state-v1",
                "toolchain": "frozen_autoencoder_state_read_only",
                "reviewed_adapter_id": reviewed_adapter,
                "preregistered": preregistered,
            },
            "evidence": {
                "kind": "plat_ae_qualification_and_capability_smoke",
                "qualification_path": str(
                    AE_QUALIFICATION_RELATIVE_PATH
                ).replace("\\", "/"),
                "evaluation_status": eval_status,
                "evaluation_status_reason": eval_reason,
                "capability_status": cap.get("status"),
                "scored_supported_required_for_guidance": True,
                "guidance_eligible": status == METHOD_STATUS_SEMANTIC_SCORED
                and status_reason.endswith("scored_supported"),
            },
            "health_only": False,
            "model_inference_established": False,
            "model_inference_required_for_role": False,
            "capability_inventory_id": "autoencoder_state",
            "checks": {
                "health_only": False,
                "reviewed_adapter_present": bool(reviewed_adapter),
                "preregistered": preregistered,
                "scored_supported": any_scored,
            },
        }
        assert_health_only_cannot_establish_model_inference(
            record, path=f"method[{method_id}]"
        )
        return record

    # Capability-backed methods
    cap_id = CAPABILITY_ID_BY_METHOD[method_id]
    cap = dict(by_id.get(cap_id) or {})
    _require(cap, f"capability {cap_id!r} missing for method {method_id!r}")
    effective = _capability_effective(cap)
    requested = _capability_requested(cap)
    checks = _capability_checks(cap)
    health_only = bool(checks.get("health_only"))
    model_inference = _model_inference_from_capability(cap)

    if method_id == METHOD_SPACY:
        status, status_reason = _status_from_capability_availability(
            cap, role_status_when_available=METHOD_STATUS_NOT_SELECTED
        )
        identity = {
            "distribution": effective.get("distribution") or "spacy",
            "version": effective.get("version") or SPACY_VERSION,
            "model": effective.get("model") or SPACY_MODEL,
            "model_version": effective.get("model_version")
            or SPACY_MODEL_VERSION,
            "pipeline": list(effective.get("pipeline") or []),
            "language": effective.get("language") or "en",
            "route": "modal_spacy_diagnostics",
            "toolchain": "spacy_full_pipeline_no_blank_fallback",
        }
        model_required = False
    elif method_id == METHOD_SYMAI:
        status, status_reason = _status_from_capability_availability(
            cap, role_status_when_available=METHOD_STATUS_NOT_SELECTED
        )
        identity = {
            "distribution": effective.get("distribution") or "symbolicai",
            "version": effective.get("version") or SYMAI_VERSION,
            "provider": effective.get("provider") or SYMAI_PROVIDER,
            "model_alias": effective.get("model_alias") or SYMAI_MODEL_ALIAS,
            "route": effective.get("route") or "symai_router",
            "resolved_model": effective.get("resolved_model")
            or LEANSTRAL_MODEL,
            "resolved_endpoint": effective.get("resolved_endpoint")
            or LEANSTRAL_ENDPOINT,
            "resolved_backend": effective.get("resolved_backend")
            or LEANSTRAL_BACKEND,
            "resolved_provider": effective.get("resolved_provider")
            or LEANSTRAL_PROVIDER,
            "independent_model": bool(effective.get("independent_model")),
            "toolchain": "symai_router_orchestration_only",
            "proof_credit": False,
        }
        # Orchestration may use a live route smoke; health-only still fails closed.
        model_required = True
        if health_only:
            # Force reclassification: health-only cannot establish inference.
            model_inference = False
            if status == METHOD_STATUS_NOT_SELECTED and cap.get("status") == "available":
                # Capability claimed available only via health — fail closed for
                # model-backed scheduling of the teacher path.
                status = METHOD_STATUS_NOT_MEASURED
                status_reason = "health_only_probe_cannot_establish_model_inference"
    elif method_id == METHOD_LEANSTRAL:
        status, status_reason = _status_from_capability_availability(
            cap, role_status_when_available=METHOD_STATUS_NOT_SELECTED
        )
        identity = {
            "provider": effective.get("provider") or LEANSTRAL_PROVIDER,
            "model": effective.get("model") or LEANSTRAL_MODEL,
            "endpoint": effective.get("endpoint") or LEANSTRAL_ENDPOINT,
            "backend": effective.get("backend") or LEANSTRAL_BACKEND,
            "route": effective.get("route")
            or "direct_openai_compatible_http",
            "version": effective.get("model") or LEANSTRAL_MODEL,
            "toolchain": "leanstral_local_llama_cpp",
            "capacity": effective.get("capacity")
            or {"model_instances": 1, "parallel_slots": 1},
        }
        model_required = True
        if health_only:
            model_inference = False
            if status == METHOD_STATUS_NOT_SELECTED and cap.get("status") == "available":
                status = METHOD_STATUS_NOT_MEASURED
                status_reason = "health_only_probe_cannot_establish_model_inference"
        elif not model_inference and cap.get("status") == "available":
            # Available without established inference → not fair for teacher.
            status = METHOD_STATUS_NOT_MEASURED
            status_reason = "model_inference_not_established_by_bounded_smoke"
    elif method_id == METHOD_HAMMER:
        status, status_reason = _status_from_capability_availability(
            cap, role_status_when_available=METHOD_STATUS_NOT_SELECTED
        )
        identity = {
            "hammer_distribution": effective.get("hammer_distribution"),
            "hammer_module": effective.get("hammer_module"),
            "hammer_version": effective.get("hammer_version"),
            "solver": effective.get("solver") or "cvc5",
            "solver_version": effective.get("solver_version"),
            "solver_path": effective.get("solver_path"),
            "route": "structural_admission_hammer",
            "toolchain": "hammer_cvc5_bounded_smoke",
            "version": effective.get("hammer_version") or "0.2.0",
            "model": None,
        }
        model_required = False
    elif method_id == METHOD_CVC5:
        status, status_reason = _status_from_capability_availability(
            cap, role_status_when_available=METHOD_STATUS_NOT_SELECTED
        )
        identity = {
            "solver": effective.get("solver") or "cvc5",
            "solver_version": effective.get("solver_version"),
            "solver_path": effective.get("solver_path"),
            "solver_executable_sha256": effective.get(
                "solver_executable_sha256"
            ),
            "route": "structural_admission_cvc5",
            "toolchain": "cvc5_bounded_smt2_smoke",
            "version": effective.get("solver_version") or "unknown",
            "model": None,
        }
        model_required = False
    elif method_id == METHOD_LEAN:
        status, status_reason = _status_from_capability_availability(
            cap, role_status_when_available=METHOD_STATUS_NOT_SELECTED
        )
        identity = {
            "path": effective.get("path"),
            "toolchain": effective.get("toolchain") or "Lean 4",
            "version": effective.get("version"),
            "executable_sha256": effective.get("executable_sha256"),
            "route": "structural_admission_lean",
            "model": None,
        }
        model_required = False
    else:  # pragma: no cover - closed method set
        raise HoldoutInterventionError(f"unhandled method_id: {method_id!r}")

    record = {
        "interface": SEMANTIC_ROUNDTRIP_CAPABILITY_RECORD_INTERFACE,
        "schema_version": SEMANTIC_ROUNDTRIP_CAPABILITY_RECORD_SCHEMA,
        "method_id": method_id,
        "role": role,
        "semantic_authority": semantic_authority,
        "may_substitute_for_e2e": False,
        "is_production_edit_target": False,
        "status": status,
        "status_reason": status_reason,
        "identity": identity,
        "evidence": {
            "kind": "plat_capability_smoke",
            "capability_inventory_id": cap_id,
            "capability_status": cap.get("status"),
            "capability_reason": cap.get("reason"),
            "requested_identity": requested,
            "effective_identity": effective,
            "checks": checks,
        },
        "health_only": health_only,
        "model_inference_established": model_inference,
        "model_inference_required_for_role": model_required,
        "capability_inventory_id": cap_id,
        "checks": {
            "health_only": health_only,
            "model_inference_performed": model_inference,
            "schedulable_for_scored_matrix": bool(
                checks.get("schedulable_for_scored_matrix")
            ),
            "bounded_smoke_passed": bool(
                checks.get("bounded_smoke_passed")
                or checks.get("loaded_full_pipeline")
                or model_inference
            ),
        },
    }
    assert_health_only_cannot_establish_model_inference(
        record, path=f"method[{method_id}]"
    )
    return record


def build_all_method_records(
    *,
    inventory: Mapping[str, Any] | None = None,
    ae_qualification: Mapping[str, Any] | None = None,
    repo_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Build capability records for every preregistered method (canonical order)."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    inv = (
        dict(inventory)
        if inventory is not None
        else load_frozen_capability_inventory(repo_root=root)
    )
    ae_qual = (
        dict(ae_qualification)
        if ae_qualification is not None
        else load_ae_qualification(repo_root=root)
    )
    return [
        build_method_capability_record(
            method_id,
            inventory=inv,
            ae_qualification=ae_qual,
            repo_root=root,
        )
        for method_id in METHOD_IDS
    ]


def parse_method_capability_record(value: object) -> dict[str, Any]:
    """Validate one ``SemanticRoundtripCapabilityRecord@1``."""

    data = dict(_mapping(value, "capability record"))
    _require(
        data.get("interface")
        == SEMANTIC_ROUNDTRIP_CAPABILITY_RECORD_INTERFACE,
        "capability record interface mismatch",
    )
    _require(
        data.get("schema_version")
        == SEMANTIC_ROUNDTRIP_CAPABILITY_RECORD_SCHEMA,
        "capability record schema mismatch",
    )
    method_id = _nonblank(data.get("method_id"), "method_id")
    _require(method_id in METHOD_IDS, f"unknown method_id: {method_id!r}")
    role = _nonblank(data.get("role"), "role")
    _require(
        role == METHOD_ROLE_BY_ID[method_id],
        f"role for {method_id} must be {METHOD_ROLE_BY_ID[method_id]!r}",
    )
    status = _nonblank(data.get("status"), "status")
    _require(status in METHOD_STATUSES, f"invalid method status: {status!r}")
    _nonblank(data.get("status_reason"), "status_reason")
    identity = dict(_mapping(data.get("identity"), "identity"))
    _require(identity, "identity must be nonempty")
    expected_auth = bool(SEMANTIC_AUTHORITY_BY_METHOD[method_id])
    _require(
        data.get("semantic_authority") is expected_auth,
        f"semantic_authority for {method_id} must be {expected_auth}",
    )
    if method_id == METHOD_DETERMINISTIC_COMPILER:
        _require(
            data.get("is_production_edit_target") is True,
            "deterministic compiler must be production edit target",
        )
        _require(
            status == METHOD_STATUS_SEMANTIC_SCORED,
            "deterministic compiler must be semantic_scored",
        )
    else:
        _require(
            data.get("is_production_edit_target") is False,
            f"{method_id} must not be production edit target",
        )
        _require(
            data.get("may_substitute_for_e2e") is False,
            f"{method_id} must not substitute for e2e",
        )
    if method_id == METHOD_AUTOENCODER:
        # Guidance eligibility only when scored_supported.
        if status == METHOD_STATUS_SEMANTIC_SCORED:
            _require(
                "scored_supported" in str(data.get("status_reason") or ""),
                "autoencoder semantic_scored requires scored_supported reason",
            )
        else:
            _require(
                status
                in {
                    METHOD_STATUS_NOT_MEASURED,
                    METHOD_STATUS_TERMINAL_UNSUPPORTED,
                    METHOD_STATUS_RUNTIME_FAILED,
                    METHOD_STATUS_NOT_SELECTED,
                },
                "autoencoder without scored_supported must not be semantic_scored",
            )
    assert_health_only_cannot_establish_model_inference(
        data, path=f"method[{method_id}]"
    )
    if data.get("health_only") is True:
        _require(
            data.get("model_inference_established") is not True,
            "health-only probes cannot establish model inference",
        )
    return data


# ---------------------------------------------------------------------------
# Residual → intervention mapping
# ---------------------------------------------------------------------------


def select_primary_intervention_kind(
    residual: Mapping[str, Any],
) -> str:
    """Preregistered smallest intervention kind for one residual (outcome-free)."""

    residual_kind = _nonblank(
        residual.get("residual_kind"), "residual.residual_kind"
    )
    _require(
        residual_kind in PROJECTABLE_RESIDUAL_KINDS
        or residual_kind
        in {RESIDUAL_KIND_MISSING_RULE, RESIDUAL_KIND_FIELD_MISMATCH},
        f"unsupported residual_kind for intervention map: {residual_kind!r}",
    )
    if residual_kind in {RESIDUAL_KIND_MISSING_RULE, RESIDUAL_KIND_EXTRA_RULE}:
        return INTERVENTION_DET_MISSING_RULE
    trigger = str(residual.get("suggested_trigger_kind") or TRIGGER_MISSING)
    if trigger == TRIGGER_CONTRADICTORY:
        return INTERVENTION_DET_FIELD_CONTRADICTORY
    # missing / low_confidence / default → field fill on deterministic path
    return INTERVENTION_DET_FIELD_MISSING


def advisory_methods_for_residual(
    residual: Mapping[str, Any],
    *,
    method_records_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Optional advisory methods eligible for a residual (never edit targets)."""

    advisories: list[dict[str, Any]] = []
    spacy = method_records_by_id.get(METHOD_SPACY)
    if spacy is not None and spacy.get("status") in {
        METHOD_STATUS_NOT_SELECTED,
        METHOD_STATUS_SEMANTIC_SCORED,
    }:
        advisories.append(
            {
                "advisory_id": ADVISORY_SPACY_DIAGNOSTICS,
                "method_id": METHOD_SPACY,
                "role": ROLE_NON_AUTHORITATIVE_DIAGNOSTICS,
                "semantic_authority": False,
                "eligible": True,
                "reason": "non_authoritative_diagnostics_when_pipeline_available",
            }
        )
    leanstral = method_records_by_id.get(METHOD_LEANSTRAL)
    if leanstral is not None and leanstral.get("status") == METHOD_STATUS_NOT_SELECTED:
        if leanstral.get("model_inference_established") is True:
            advisories.append(
                {
                    "advisory_id": ADVISORY_LEANSTRAL_PROPOSAL,
                    "method_id": METHOD_LEANSTRAL,
                    "role": ROLE_PROPOSAL_TEACHER,
                    "semantic_authority": False,
                    "eligible": True,
                    "reason": "proposal_teacher_when_inference_established",
                }
            )
        else:
            advisories.append(
                {
                    "advisory_id": ADVISORY_LEANSTRAL_PROPOSAL,
                    "method_id": METHOD_LEANSTRAL,
                    "role": ROLE_PROPOSAL_TEACHER,
                    "semantic_authority": False,
                    "eligible": False,
                    "reason": "model_inference_not_established",
                }
            )
    ae = method_records_by_id.get(METHOD_AUTOENCODER)
    if ae is not None:
        eligible = (
            ae.get("status") == METHOD_STATUS_SEMANTIC_SCORED
            and "scored_supported" in str(ae.get("status_reason") or "")
        )
        advisories.append(
            {
                "advisory_id": ADVISORY_AE_GUIDANCE,
                "method_id": METHOD_AUTOENCODER,
                "role": ROLE_CAUSAL_GUIDANCE,
                "semantic_authority": False,
                "eligible": bool(eligible),
                "reason": (
                    "causal_guidance_when_scored_supported"
                    if eligible
                    else str(
                        ae.get("status_reason")
                        or UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER
                    )
                ),
            }
        )
    # SyMAI never receives advisory proof credit; record orchestration-only.
    symai = method_records_by_id.get(METHOD_SYMAI)
    if symai is not None:
        advisories.append(
            {
                "advisory_id": "adv_symai_orchestration",
                "method_id": METHOD_SYMAI,
                "role": ROLE_ORCHESTRATION_ROUTING,
                "semantic_authority": False,
                "eligible": False,
                "reason": "orchestration_routing_only_no_proof_credit",
            }
        )
    # Touch residual fields so mapping is residual-bound (no outcome selection).
    _ = residual.get("field_path")
    return advisories


def structural_gates_for_residual(
    *,
    method_records_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Declared structural gates (Hammer/cvc5/Lean) for attribution receipts."""

    gates: list[dict[str, Any]] = []
    for gate_id in (METHOD_HAMMER, METHOD_CVC5, METHOD_LEAN):
        record = method_records_by_id.get(gate_id)
        if record is None:
            continue
        gates.append(
            {
                "method_id": gate_id,
                "role": ROLE_STRUCTURAL_GATE,
                "semantic_authority": False,
                "status": record.get("status"),
                "status_reason": record.get("status_reason"),
                "may_substitute_for_e2e": False,
            }
        )
    return gates


def map_residual_to_intervention(
    residual: Mapping[str, Any],
    *,
    method_records: Sequence[Mapping[str, Any]],
    wave_index: int,
    prior_mapping_ids: Sequence[str],
) -> dict[str, Any]:
    """Map one repair-development residual to intervention + ablations."""

    residual = dict(_mapping(residual, "residual"))
    case_id = _nonblank(residual.get("case_id"), "residual.case_id")
    field_path = _nonblank(residual.get("field_path"), "residual.field_path")
    residual_kind = _nonblank(
        residual.get("residual_kind"), "residual.residual_kind"
    )
    mapping_id = residual_mapping_id(residual)
    identity_key = residual_identity_key(residual)
    intervention_kind = select_primary_intervention_kind(residual)

    by_id = {
        str(item["method_id"]): dict(item)
        for item in method_records
        if isinstance(item, Mapping) and "method_id" in item
    }
    det = by_id[METHOD_DETERMINISTIC_COMPILER]
    _require(
        det.get("status") == METHOD_STATUS_SEMANTIC_SCORED,
        "edit target must be semantic_scored deterministic compiler",
    )

    primary = {
        "intervention_id": intervention_kind,
        "method_id": METHOD_DETERMINISTIC_COMPILER,
        "role": ROLE_PRODUCTION_EDIT_TARGET,
        "semantic_authority": True,
        "edit_target": True,
        "scope": {
            "case_id": case_id,
            "field_path": field_path,
            "residual_kind": residual_kind,
            "canonical_field": residual.get("canonical_field"),
            "candidate_rule_index": residual.get("candidate_rule_index"),
            "gold_rule_index": residual.get("gold_rule_index"),
            "suggested_trigger_kind": residual.get("suggested_trigger_kind"),
        },
        "selection_rule": (
            "smallest_preregistered_deterministic_hypothesis_for_residual_kind"
        ),
        "outcome_dependent_selection": False,
    }

    negative_controls = [
        {
            "control_id": NEGATIVE_CONTROL_NO_EDIT,
            "description": (
                "hold residual fixed; run baseline arm without compiler edit"
            ),
            "method_id": METHOD_DETERMINISTIC_COMPILER,
            "arm_id": PRODUCTION_ARM_ID,
        },
        {
            "control_id": NEGATIVE_CONTROL_WITHHOLD_TEACHER,
            "description": (
                "run the same deterministic hypothesis without optional "
                "spaCy/Leanstral/AE advisory inputs"
            ),
            "method_id": METHOD_DETERMINISTIC_COMPILER,
            "arm_id": PRODUCTION_ARM_ID,
        },
    ]

    advisories = advisory_methods_for_residual(
        residual, method_records_by_id=by_id
    )
    gates = structural_gates_for_residual(method_records_by_id=by_id)

    per_wave_ablation = {
        "wave_index": wave_index,
        "wave_id": f"wave_{wave_index:03d}_{case_id}",
        "units": [
            {
                "unit_id": f"wave_{wave_index:03d}_treatment",
                "kind": "treatment",
                "intervention_id": intervention_kind,
                "mapping_id": mapping_id,
            },
            {
                "unit_id": f"wave_{wave_index:03d}_negative_control",
                "kind": "negative_control",
                "control_id": NEGATIVE_CONTROL_NO_EDIT,
                "mapping_id": mapping_id,
            },
            {
                "unit_id": f"wave_{wave_index:03d}_teacher_withheld",
                "kind": "negative_control",
                "control_id": NEGATIVE_CONTROL_WITHHOLD_TEACHER,
                "mapping_id": mapping_id,
            },
        ],
        "attribution": (
            "per_wave_isolates_single_residual_deterministic_hypothesis"
        ),
    }

    cumulative_ids = list(prior_mapping_ids) + [mapping_id]
    cumulative_ablation = {
        "wave_index": wave_index,
        "included_mapping_ids": cumulative_ids,
        "included_count": len(cumulative_ids),
        "units": [
            {
                "unit_id": f"cum_{wave_index:03d}_all_prior_plus_current",
                "kind": "cumulative_treatment",
                "mapping_ids": cumulative_ids,
            },
            {
                "unit_id": f"cum_{wave_index:03d}_drop_current",
                "kind": "leave_one_out_control",
                "mapping_ids": list(prior_mapping_ids),
            },
        ],
        "attribution": (
            "cumulative_ablation_attributes_gain_to_current_residual_vs_priors"
        ),
    }

    return {
        "interface": RESIDUAL_INTERVENTION_MAPPING_INTERFACE,
        "mapping_id": mapping_id,
        "identity_key": identity_key,
        "case_id": case_id,
        "field_path": field_path,
        "residual_kind": residual_kind,
        "canonical_field": residual.get("canonical_field"),
        "loss_contribution": residual.get("loss_contribution"),
        "suggested_trigger_kind": residual.get("suggested_trigger_kind"),
        "primary_intervention": primary,
        "negative_controls": negative_controls,
        "optional_advisories": advisories,
        "structural_gates": gates,
        "per_wave_ablation": per_wave_ablation,
        "cumulative_ablation": cumulative_ablation,
        "population_kind": POPULATION_KIND_REPAIR_DEVELOPMENT,
        "blind_data_used": False,
        "outcome_dependent_selection": False,
    }


def build_residual_intervention_mappings(
    residuals: Sequence[Mapping[str, Any]],
    *,
    method_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Map every repair-development residual in stable attribution order."""

    ordered = sorted(
        (dict(item) for item in residuals),
        key=lambda row: (
            str(row.get("case_id") or ""),
            str(row.get("field_path") or ""),
            str(row.get("residual_kind") or ""),
        ),
    )
    mappings: list[dict[str, Any]] = []
    prior_ids: list[str] = []
    for wave_index, residual in enumerate(ordered):
        mapping = map_residual_to_intervention(
            residual,
            method_records=method_records,
            wave_index=wave_index,
            prior_mapping_ids=prior_ids,
        )
        mappings.append(mapping)
        prior_ids.append(str(mapping["mapping_id"]))
    return mappings


# ---------------------------------------------------------------------------
# Full matrix override policy
# ---------------------------------------------------------------------------


def full_matrix_override_policy() -> dict[str, Any]:
    """Preregistered policy: full matrix reruns need explicit evidence override."""

    return {
        "interface": FULL_MATRIX_OVERRIDE_INTERFACE,
        "full_matrix_rerun_default_allowed": False,
        "requires_explicit_evidence_backed_override": True,
        "required_override_fields": [
            "override_id",
            "evidence_cid",
            "justification",
            "authorizer",
            "residual_mapping_ids_in_scope",
            "experiment_id",
            "registry_cid",
        ],
        "forbidden_without_override": [
            "cartesian_method_matrix_rerun",
            "outcome_dependent_arm_selection",
            "blind_population_probe",
        ],
        "selection_rule": (
            "smallest_preregistered_residual_intervention_not_full_matrix"
        ),
        "override_validation": (
            "override payload must be CID-bound, cite residual mappings, "
            "and must not depend on blind outcomes or post-hoc scores"
        ),
    }


def validate_full_matrix_override(
    override: Mapping[str, Any],
    *,
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate an explicit full-matrix override against a frozen registry."""

    data = dict(_mapping(override, "full_matrix_override"))
    policy = full_matrix_override_policy()
    for field in policy["required_override_fields"]:
        _require(
            field in data and data[field] not in (None, "", []),
            f"full matrix override missing required field {field!r}",
        )
    _cid(data.get("evidence_cid"), "override.evidence_cid")
    _nonblank(data.get("justification"), "override.justification")
    _nonblank(data.get("authorizer"), "override.authorizer")
    _require(
        data.get("registry_cid") == registry.get("registry_cid"),
        "override.registry_cid must match frozen registry_cid",
    )
    _require(
        data.get("experiment_id") == registry.get("experiment_id"),
        "override.experiment_id must match frozen experiment_id",
    )
    mapping_ids = _array(
        data.get("residual_mapping_ids_in_scope"),
        "override.residual_mapping_ids_in_scope",
    )
    known = {
        str(item.get("mapping_id"))
        for item in registry.get("residual_mappings", [])
        if isinstance(item, Mapping)
    }
    for mid in mapping_ids:
        mid_text = _nonblank(mid, "override residual mapping id")
        _require(
            mid_text in known,
            f"override references unknown residual mapping {mid_text!r}",
        )
    _require(
        data.get("outcome_dependent_selection") is not True,
        "full matrix override cannot use outcome-dependent selection",
    )
    _require(
        data.get("blind_data_used") is not True,
        "full matrix override cannot use blind data",
    )
    return data


# ---------------------------------------------------------------------------
# Registry build / parse / write
# ---------------------------------------------------------------------------


def _bindings_from_artifacts(
    repo_root: Path,
) -> dict[str, Any]:
    catalog = load_repair_dev_residual_catalog(
        repo_root / DEFAULT_REPAIR_DEV_CATALOG_RELATIVE_PATH,
        repo_root=repo_root,
    )
    baseline_report = load_repair_dev_baseline_report(
        repo_root / DEFAULT_BASELINE_REPORT_RELATIVE_PATH,
        repo_root=repo_root,
    )
    blind = assert_blind_seal_unopened(repo_root)
    seal = load_frozen_blind_holdout_seal(repository_root=repo_root)
    return {
        "baseline_report_cid": baseline_report.get("report_cid"),
        "blind_holdout": blind,
        "blind_seal_cid": seal.seal_cid,
        "catalog_cid": catalog.get("catalog_cid"),
        "contract_cid": baseline_report.get("contract_cid"),
        "experiment_id": baseline_report.get("experiment_id"),
        "population_cid": catalog.get("population_cid"),
        "population_kind": catalog.get("population_kind")
        or POPULATION_KIND_REPAIR_DEVELOPMENT,
        "residuals": list(catalog.get("residuals") or []),
        "tree_cid": catalog.get("tree_cid"),
    }


def build_intervention_registry(
    repo_root: str | Path | None = None,
    *,
    inventory: Mapping[str, Any] | None = None,
    ae_qualification: Mapping[str, Any] | None = None,
    residuals: Sequence[Mapping[str, Any]] | None = None,
    experiment_id: str | None = None,
    contract_cid: str | None = None,
    catalog_cid: str | None = None,
    population_cid: str | None = None,
    tree_cid: str | None = None,
    baseline_report_cid: str | None = None,
    blind_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the CID-bound ``Plateau2InterventionRegistry@1`` freeze."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    root = root.resolve()

    bindings = _bindings_from_artifacts(root)
    residual_rows = (
        [dict(item) for item in residuals]
        if residuals is not None
        else [dict(item) for item in bindings["residuals"]]
    )
    _require(residual_rows, "repair-development residual catalog is empty")

    inv = (
        dict(inventory)
        if inventory is not None
        else load_frozen_capability_inventory(repo_root=root)
    )
    ae_qual = (
        dict(ae_qualification)
        if ae_qualification is not None
        else load_ae_qualification(repo_root=root)
    )
    methods = build_all_method_records(
        inventory=inv, ae_qualification=ae_qual, repo_root=root
    )
    for method in methods:
        parse_method_capability_record(method)

    mappings = build_residual_intervention_mappings(
        residual_rows, method_records=methods
    )
    _require(
        len(mappings) == len(residual_rows),
        "residual mapping count must match residual count",
    )

    blind = (
        dict(blind_status)
        if blind_status is not None
        else dict(bindings["blind_holdout"])
    )
    _require(
        blind.get("access_receipt_count") == 0,
        "blind access ledger must have zero receipts for intervention freeze",
    )
    _require(
        blind.get("blind_seal_unopened") is True,
        "blind seal must remain unopened for intervention freeze",
    )

    # Role summary for quick doctrine checks.
    role_summary = {
        method["method_id"]: {
            "role": method["role"],
            "semantic_authority": method["semantic_authority"],
            "status": method["status"],
            "status_reason": method["status_reason"],
        }
        for method in methods
    }

    payload: dict[str, Any] = {
        "assumptions": list(DEFAULT_ASSUMPTIONS),
        "baseline_report_cid": baseline_report_cid
        or bindings["baseline_report_cid"],
        "blind_holdout": _plain_json(blind),
        "board_namespace": BOARD_NAMESPACE,
        "catalog_cid": catalog_cid or bindings["catalog_cid"],
        "contract_cid": contract_cid or bindings["contract_cid"],
        "doctrine": {
            "autoencoder": ROLE_CAUSAL_GUIDANCE,
            "deterministic_compiler_ir_decompiler": ROLE_PRODUCTION_EDIT_TARGET,
            "hammer_cvc5_lean": ROLE_STRUCTURAL_GATE,
            "leanstral": ROLE_PROPOSAL_TEACHER,
            "production_path": "typed_deontic → IR → deterministic realizer",
            "spacy": ROLE_NON_AUTHORITATIVE_DIAGNOSTICS,
            "symai": ROLE_ORCHESTRATION_ROUTING,
        },
        "evidence_id": INTERVENTION_EVIDENCE_ID,
        "experiment_family": EXPERIMENT_FAMILY,
        "experiment_id": experiment_id or bindings["experiment_id"],
        "experiment_contract_interface": PLATEAU2_EXPERIMENT_CONTRACT_INTERFACE,
        "full_matrix_policy": full_matrix_override_policy(),
        "goal_id": INTERVENTION_GOAL_ID,
        "interface": PLATEAU2_INTERVENTION_REGISTRY_INTERFACE,
        "method_records": methods,
        "method_roles": role_summary,
        "method_statuses": sorted(METHOD_STATUSES),
        "population_cid": population_cid or bindings["population_cid"],
        "population_kind": POPULATION_KIND_REPAIR_DEVELOPMENT,
        "residual_mappings": mappings,
        "revision": INTERVENTION_REVISION,
        "schema_version": PLATEAU2_INTERVENTION_REGISTRY_SCHEMA,
        "selection_policy": {
            "blind_data_permitted": False,
            "outcome_dependent_selection_permitted": False,
            "primary_edit_method": METHOD_DETERMINISTIC_COMPILER,
            "rule": (
                "map_each_residual_to_smallest_preregistered_deterministic_"
                "intervention_plus_negative_controls_and_ablations"
            ),
            "full_matrix_requires_override": True,
        },
        "task_id": INTERVENTION_TASK_ID,
        "tree_cid": tree_cid or bindings["tree_cid"],
    }

    # Bind CIDs for referenced artifacts when present.
    for key in (
        "baseline_report_cid",
        "catalog_cid",
        "contract_cid",
        "experiment_id",
        "population_cid",
        "tree_cid",
    ):
        if payload.get(key):
            payload[key] = _cid(payload[key], key)

    identity = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "registry_cid",
            "registry_cid_codec",
            "registry_cid_scope",
        }
    }
    registry_cid = cid_for_dag_json(_plain_json(identity))
    payload["registry_cid"] = registry_cid
    payload["registry_cid_codec"] = CID_CODEC
    payload["registry_cid_scope"] = REGISTRY_CID_SCOPE
    return payload


def parse_intervention_registry(value: object) -> dict[str, Any]:
    """Validate a ``Plateau2InterventionRegistry@1`` payload."""

    data = dict(_mapping(value, "intervention registry"))
    _require(
        data.get("interface") == PLATEAU2_INTERVENTION_REGISTRY_INTERFACE,
        "intervention registry interface mismatch",
    )
    _require(
        data.get("schema_version") == PLATEAU2_INTERVENTION_REGISTRY_SCHEMA,
        "intervention registry schema mismatch",
    )
    _require(
        data.get("task_id") == INTERVENTION_TASK_ID,
        "intervention registry task_id mismatch",
    )
    _require(
        data.get("goal_id") == INTERVENTION_GOAL_ID,
        "intervention registry goal_id mismatch",
    )
    _require(
        data.get("evidence_id") == INTERVENTION_EVIDENCE_ID,
        "intervention registry evidence_id mismatch",
    )
    _require(
        data.get("population_kind") == POPULATION_KIND_REPAIR_DEVELOPMENT,
        "registry population must be repair_development",
    )
    _require(
        data.get("board_namespace") == BOARD_NAMESPACE,
        "board_namespace mismatch",
    )

    methods = _array(data.get("method_records"), "method_records")
    parsed_methods = [
        parse_method_capability_record(item) for item in methods
    ]
    method_ids = [item["method_id"] for item in parsed_methods]
    _require(
        tuple(method_ids) == METHOD_IDS,
        "method_records must list every method exactly once in canonical order",
    )

    # Doctrine checks on roles.
    by_id = {item["method_id"]: item for item in parsed_methods}
    _require(
        by_id[METHOD_DETERMINISTIC_COMPILER]["role"]
        == ROLE_PRODUCTION_EDIT_TARGET,
        "deterministic compiler must be production edit target",
    )
    _require(
        by_id[METHOD_AUTOENCODER]["role"] == ROLE_CAUSAL_GUIDANCE,
        "autoencoder role mismatch",
    )
    _require(
        by_id[METHOD_SPACY]["role"] == ROLE_NON_AUTHORITATIVE_DIAGNOSTICS,
        "spaCy role mismatch",
    )
    _require(
        by_id[METHOD_SYMAI]["role"] == ROLE_ORCHESTRATION_ROUTING,
        "SyMAI role mismatch",
    )
    _require(
        by_id[METHOD_LEANSTRAL]["role"] == ROLE_PROPOSAL_TEACHER,
        "Leanstral role mismatch",
    )
    for gate in (METHOD_HAMMER, METHOD_CVC5, METHOD_LEAN):
        _require(
            by_id[gate]["role"] == ROLE_STRUCTURAL_GATE,
            f"{gate} must be structural_gate",
        )
        _require(
            by_id[gate]["semantic_authority"] is False,
            f"{gate} must have semantic_authority false",
        )

    # AE guidance gate.
    ae = by_id[METHOD_AUTOENCODER]
    if ae["status"] == METHOD_STATUS_SEMANTIC_SCORED:
        _require(
            "scored_supported" in str(ae.get("status_reason") or ""),
            "AE semantic_scored requires scored_supported adapter",
        )

    mappings = _array(data.get("residual_mappings"), "residual_mappings")
    _require(mappings, "residual_mappings must be nonempty")
    seen_keys: set[str] = set()
    for index, raw in enumerate(mappings):
        row = dict(_mapping(raw, f"residual_mappings[{index}]"))
        _require(
            row.get("interface") == RESIDUAL_INTERVENTION_MAPPING_INTERFACE,
            f"residual_mappings[{index}] interface mismatch",
        )
        mid = _nonblank(row.get("mapping_id"), f"residual_mappings[{index}].mapping_id")
        key = _nonblank(
            row.get("identity_key"), f"residual_mappings[{index}].identity_key"
        )
        _require(key not in seen_keys, f"duplicate residual identity_key {key}")
        seen_keys.add(key)
        primary = dict(
            _mapping(
                row.get("primary_intervention"),
                f"residual_mappings[{index}].primary_intervention",
            )
        )
        _require(
            primary.get("method_id") == METHOD_DETERMINISTIC_COMPILER,
            f"residual_mappings[{index}] edit target must be deterministic compiler",
        )
        _require(
            primary.get("edit_target") is True,
            f"residual_mappings[{index}] primary must be edit_target",
        )
        _require(
            primary.get("outcome_dependent_selection") is False,
            f"residual_mappings[{index}] forbids outcome-dependent selection",
        )
        _require(
            row.get("blind_data_used") is False,
            f"residual_mappings[{index}] must not use blind data",
        )
        _require(
            row.get("outcome_dependent_selection") is False,
            f"residual_mappings[{index}] must not use outcome-dependent selection",
        )
        controls = _array(
            row.get("negative_controls"),
            f"residual_mappings[{index}].negative_controls",
        )
        control_ids = {
            str(item.get("control_id"))
            for item in controls
            if isinstance(item, Mapping)
        }
        _require(
            NEGATIVE_CONTROL_NO_EDIT in control_ids,
            f"residual_mappings[{index}] missing no-edit negative control",
        )
        per_wave = dict(
            _mapping(
                row.get("per_wave_ablation"),
                f"residual_mappings[{index}].per_wave_ablation",
            )
        )
        _require(
            _array(per_wave.get("units"), "per_wave_ablation.units"),
            f"residual_mappings[{index}] per_wave_ablation.units required",
        )
        cumulative = dict(
            _mapping(
                row.get("cumulative_ablation"),
                f"residual_mappings[{index}].cumulative_ablation",
            )
        )
        included = _array(
            cumulative.get("included_mapping_ids"),
            "cumulative_ablation.included_mapping_ids",
        )
        _require(
            mid in {str(x) for x in included},
            f"residual_mappings[{index}] cumulative ablation must include self",
        )

    selection = dict(_mapping(data.get("selection_policy"), "selection_policy"))
    _require(
        selection.get("blind_data_permitted") is False,
        "selection_policy must forbid blind data",
    )
    _require(
        selection.get("outcome_dependent_selection_permitted") is False,
        "selection_policy must forbid outcome-dependent selection",
    )
    _require(
        selection.get("full_matrix_requires_override") is True,
        "selection_policy must require override for full matrix",
    )
    _require(
        selection.get("primary_edit_method") == METHOD_DETERMINISTIC_COMPILER,
        "primary edit method must be deterministic compiler",
    )

    matrix_policy = dict(
        _mapping(data.get("full_matrix_policy"), "full_matrix_policy")
    )
    _require(
        matrix_policy.get("full_matrix_rerun_default_allowed") is False,
        "full matrix must not be allowed by default",
    )
    _require(
        matrix_policy.get("requires_explicit_evidence_backed_override") is True,
        "full matrix must require evidence-backed override",
    )

    blind = dict(_mapping(data.get("blind_holdout"), "blind_holdout"))
    _require(
        blind.get("access_receipt_count") == 0,
        "blind access_receipt_count must be zero",
    )
    _require(
        blind.get("blind_seal_unopened") is True,
        "blind seal must remain unopened",
    )

    for key in (
        "baseline_report_cid",
        "catalog_cid",
        "contract_cid",
        "experiment_id",
        "population_cid",
        "tree_cid",
        "registry_cid",
    ):
        if data.get(key) is not None:
            _cid(data.get(key), key)

    identity = {
        key: value
        for key, value in data.items()
        if key
        not in {
            "registry_cid",
            "registry_cid_codec",
            "registry_cid_scope",
        }
    }
    expected = cid_for_dag_json(_plain_json(identity))
    _require(
        data.get("registry_cid") == expected,
        "registry_cid does not match payload identity",
    )
    return data


def load_intervention_registry(
    path: str | Path | None = None,
    *,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    registry_path = (
        Path(path)
        if path is not None
        else root / DEFAULT_REGISTRY_RELATIVE_PATH
    )
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    return parse_intervention_registry(payload)


def write_intervention_registry(
    path: str | Path,
    *,
    registry: Mapping[str, Any] | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Write the intervention registry atomically and return the sealed payload."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    payload = (
        dict(registry)
        if registry is not None
        else build_intervention_registry(root)
    )
    parse_intervention_registry(payload)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=".repair_dev_intervention_registry.",
        suffix=".json",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return payload


def method_record_by_id(
    registry: Mapping[str, Any], method_id: str
) -> dict[str, Any]:
    for item in registry.get("method_records", []):
        if isinstance(item, Mapping) and item.get("method_id") == method_id:
            return dict(item)
    raise HoldoutInterventionError(f"method {method_id!r} not in registry")


def mapping_for_residual_key(
    registry: Mapping[str, Any], identity_key: str
) -> dict[str, Any]:
    for item in registry.get("residual_mappings", []):
        if isinstance(item, Mapping) and item.get("identity_key") == identity_key:
            return dict(item)
    raise HoldoutInterventionError(
        f"residual mapping {identity_key!r} not in registry"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "PLAT2-035 freeze intervention roles, capabilities, and ablations"
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="repository root (default: inferred from module path)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="path for repair_dev_intervention_registry.json",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="print registry JSON to stdout without writing",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = args.repo_root or _repo_root()
    registry = build_intervention_registry(root)
    parse_intervention_registry(registry)

    if args.print_only:
        print(json.dumps(registry, indent=2, sort_keys=True))
        return 0

    out = args.output or (root / DEFAULT_REGISTRY_RELATIVE_PATH)
    write_intervention_registry(out, registry=registry, repo_root=root)
    print(
        json.dumps(
            {
                "registry_cid": registry["registry_cid"],
                "experiment_id": registry["experiment_id"],
                "catalog_cid": registry["catalog_cid"],
                "residual_mapping_count": len(registry["residual_mappings"]),
                "method_count": len(registry["method_records"]),
                "path": str(out),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ADVISORY_AE_GUIDANCE",
    "ADVISORY_LEANSTRAL_PROPOSAL",
    "ADVISORY_SPACY_DIAGNOSTICS",
    "DEFAULT_REGISTRY_RELATIVE_PATH",
    "FULL_MATRIX_OVERRIDE_INTERFACE",
    "HoldoutInterventionError",
    "INTERVENTION_DET_FIELD_CONTRADICTORY",
    "INTERVENTION_DET_FIELD_MISSING",
    "INTERVENTION_DET_MISSING_RULE",
    "INTERVENTION_EVIDENCE_ID",
    "INTERVENTION_GOAL_ID",
    "INTERVENTION_TASK_ID",
    "METHOD_AUTOENCODER",
    "METHOD_CVC5",
    "METHOD_DETERMINISTIC_COMPILER",
    "METHOD_HAMMER",
    "METHOD_IDS",
    "METHOD_LEAN",
    "METHOD_LEANSTRAL",
    "METHOD_ROLE_BY_ID",
    "METHOD_SPACY",
    "METHOD_STATUS_NOT_MEASURED",
    "METHOD_STATUS_NOT_SELECTED",
    "METHOD_STATUS_RUNTIME_FAILED",
    "METHOD_STATUS_SEMANTIC_SCORED",
    "METHOD_STATUS_TERMINAL_UNSUPPORTED",
    "METHOD_STATUSES",
    "METHOD_SYMAI",
    "NEGATIVE_CONTROL_NO_EDIT",
    "NEGATIVE_CONTROL_WITHHOLD_TEACHER",
    "PLATEAU2_INTERVENTION_REGISTRY_INTERFACE",
    "PLATEAU2_INTERVENTION_REGISTRY_SCHEMA",
    "ROLE_CAUSAL_GUIDANCE",
    "ROLE_NON_AUTHORITATIVE_DIAGNOSTICS",
    "ROLE_ORCHESTRATION_ROUTING",
    "ROLE_PRODUCTION_EDIT_TARGET",
    "ROLE_PROPOSAL_TEACHER",
    "ROLE_STRUCTURAL_GATE",
    "SEMANTIC_ROUNDTRIP_CAPABILITY_RECORD_INTERFACE",
    "SEMANTIC_ROUNDTRIP_CAPABILITY_RECORD_SCHEMA",
    "assert_health_only_cannot_establish_model_inference",
    "build_all_method_records",
    "build_intervention_registry",
    "build_method_capability_record",
    "build_residual_intervention_mappings",
    "full_matrix_override_policy",
    "health_only_establishes_model_inference",
    "load_ae_qualification",
    "load_frozen_capability_inventory",
    "load_intervention_registry",
    "main",
    "map_residual_to_intervention",
    "mapping_for_residual_key",
    "method_record_by_id",
    "parse_intervention_registry",
    "parse_method_capability_record",
    "residual_identity_key",
    "residual_mapping_id",
    "select_primary_intervention_kind",
    "validate_full_matrix_override",
    "write_intervention_registry",
]
