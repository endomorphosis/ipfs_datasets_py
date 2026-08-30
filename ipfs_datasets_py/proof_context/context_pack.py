"""Datasets-owned v0.1 ContextPack construction authority (PCCE-012 / ASEH-030).

This module is the sole production builder for ContextPack identity,
coverage view, and pre-execution sufficiency. It extends
``DatasetsContextPackAuthority@0.1`` rather than minting a competing type
such as ``SupervisorContextPack@1``. Accelerator may only consume the
existing ``ContextPack@1`` contract; it must not remint Datasets identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence
import json
import re
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_obj,
    cid_for_structured,
    decode_and_recompute_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.audit_contracts import (
    ContextCoverageManifest,
    CoveredArtifactKind,
    GraphPath,
    IncludedArtifactRecord,
    InclusionKind,
    RouteTier,
    SourceSpan,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.base import (
    AssumptionKind,
    ArtifactProvenance,
    AuthoritySource,
    ExecutionMode,
    GeneratorIdentity,
    GovernorArtifactHeader,
    GovernorAssumption,
    GovernorTerminalStatus,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.policy_contracts import (
    TaskClassAcceptanceRequirements,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.sufficiency import (
    ContextPackView,
    RepositoryStateView,
    VerificationPolicyView,
    evaluate_context_sufficiency,
)
from ipfs_datasets_py.proof_context.contracts import (
    InsufficientContextError,
    OpaqueSourceRequiredError,
    PORT_SCHEMA,
    PRODUCER_REPOSITORY,
    StaleContextError,
    UnavailableContextError,
)

AUTHORITY = "ipfs_datasets_py.proof_context.context_pack"
INTERFACE = "DatasetsContextPackAuthority@0.1"
GENERATOR_ID = "datasets_v01_context_pack"
CONTEXT_PACK_SCHEMA = "ipfs-datasets.proof-context.context-pack@0.1"
CONSUMER_INTERFACE = "ContextPack@1"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "context_pack.schema.json"

FORBIDDEN_INTERFACES: Final[frozenset[str]] = frozenset(
    {"SupervisorContextPack@1", "SupervisorContextPack"}
)
IDENTITY_KINDS: Final[tuple[str, ...]] = ("live", "fixture", "synthetic")
EVIDENCE_KINDS: Final[tuple[str, ...]] = ("real", "fixture", "synthetic")
EXECUTION_MODES: Final[tuple[str, ...]] = ("live", "simulated", "replay")
ROUTE_TIERS: Final[tuple[str, ...]] = tuple(item.value for item in RouteTier)
FRESHNESS_MINTABLE: Final[frozenset[str]] = frozenset({"fresh"})
REQUIRED_SOURCE_KEYS: Final[tuple[str, ...]] = (
    "target_source",
    "surrounding_source",
    "test_source",
)

_GIT_OID_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")
_MAX_TEXT: Final[int] = 16_384
_MAX_LIST: Final[int] = 4_096
_JSON_MAX_INT: Final[int] = 9_007_199_254_740_991

IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    "schema_and_interface_version",
    "repository_identity",
    "commit",
    "tree",
    "objective_identity",
    "objective_revision",
    "policy_identity",
    "builder_identity",
    "creation_time",
    "content_cid",
    "parent_context_pack_cid",
)
SCOPE_FIELDS: Final[tuple[str, ...]] = (
    "affected_files",
    "affected_symbols",
    "dependency_cone",
    "reverse_dependencies",
    "explicitly_excluded_paths",
    "changed_interfaces_and_schemas",
    "semantic_diff_summary",
)
CONTRACT_FIELDS: Final[tuple[str, ...]] = (
    "applicable_api_contracts",
    "assumptions_and_guarantees",
    "invariants",
    "security_constraints",
    "side_effect_classes",
    "allowed_mutation_scope",
)
VALIDATION_FIELDS: Final[tuple[str, ...]] = (
    "known_tests",
    "selected_tests",
    "type_static_schema_checks",
    "proof_obligations",
    "required_full_suite_conditions",
    "current_authoritative_receipts",
)
HISTORY_FIELDS: Final[tuple[str, ...]] = (
    "relevant_prior_failures",
    "relevant_counterexamples",
    "prior_accepted_patches",
    "stale_or_invalidated_receipts",
    "retry_and_rescue_history",
)
QUESTION_FIELDS: Final[tuple[str, ...]] = (
    "named_unresolved_questions",
    "missing_evidence",
    "completeness_witness",
    "expansion_references",
)
BUDGET_FIELDS: Final[tuple[str, ...]] = (
    "maximum_bytes",
    "maximum_tokens",
    "maximum_retrieval_operations",
    "maximum_model_class",
    "maximum_wall_time",
    "validation_reserve_models_cannot_consume",
)
FRESHNESS_BINDING_FIELDS: Final[tuple[str, ...]] = (
    "file_and_symbol_identities",
    "schema_identities",
    "toolchain_identities",
    "environment_requirements",
    "reusable_until_conditions",
)
INVALIDATION_FIELDS: Final[tuple[str, ...]] = (
    "invalidation_triggers",
    "reusable_until_conditions",
)
PARENT_FIELDS: Final[tuple[str, ...]] = ("parent_context_pack_cid",)
DELTA_FIELDS: Final[tuple[str, ...]] = (
    "delta_cid",
    "incremental",
    "named_missing",
)
CANONICAL_FIELDS: Final[tuple[str, ...]] = (
    "schema",
    "interface",
    "producer",
    "repository_state_cid",
    "task_id",
    "task_class",
    "risk_class",
    "route_tier",
    "required_source_cids",
    "capsule_cids",
    "scanned_tree_oid",
    "source_tree_oid",
    "opaque",
    "freshness",
    "execution_mode",
    "identity_kind",
    "evidence_kind",
    "identity",
    "scope",
    "contracts",
    "validation",
    "history",
    "questions",
    "budgets",
    "freshness_bindings",
    "invalidation",
    "parent",
    "delta",
)
ENVELOPE_EXTRA_FIELDS: Final[tuple[str, ...]] = (
    "pack_cid",
    "sufficiency_state",
    "expansion_required",
)
ENVELOPE_FIELDS: Final[tuple[str, ...]] = CANONICAL_FIELDS + ENVELOPE_EXTRA_FIELDS

_CONSISTENT_KINDS: Final[frozenset[tuple[str, str, str]]] = frozenset(
    {
        ("live", "real", "live"),
        ("live", "real", "replay"),
        ("fixture", "fixture", "simulated"),
        ("synthetic", "synthetic", "simulated"),
    }
)


class ContextPackConstructionError(RuntimeError):
    reason = "invalid"


def _error(message: str) -> ContextPackConstructionError:
    return ContextPackConstructionError(message)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


def _nfc(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise _error(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise _error(f"{name} must be trimmed NFC text")
    if len(value) > _MAX_TEXT or any(not char.isprintable() for char in value):
        raise _error(f"{name} contains invalid text")
    return value


def _optional_nfc(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _nfc(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise _error(f"{name} must be a boolean")
    return value


def _closed(data: Any, fields: Sequence[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise _error(f"{name} must be a mapping")
    expected = set(fields)
    actual = set(data)
    missing = expected - actual
    extra = actual - expected
    if missing:
        raise _error(f"{name} omitted view input {sorted(missing)}")
    if extra:
        raise _error(f"{name} unknown field {sorted(extra)}")
    return {key: data[key] for key in fields}


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise _error(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _git_oid(value: Any, name: str) -> str:
    text = _nfc(value, name)
    if _GIT_OID_RE.fullmatch(text) is None:
        raise _error(f"{name} must be a lowercase git object id")
    return text


def _optional_git_oid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _git_oid(value, name)


def _enum_member(value: Any, allowed: Iterable[str], name: str) -> str:
    if hasattr(value, "value"):
        value = value.value
    text = _nfc(value, name)
    admitted = tuple(allowed)
    if text not in admitted:
        raise _error(f"{name} has unsupported value {text!r}")
    return text


def _string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise _error(f"{name} must be a list")
    if len(value) > _MAX_LIST:
        raise _error(f"{name} exceeds maximum length")
    items = [_nfc(item, name) for item in value]
    if len(items) != len(set(items)):
        raise _error(f"{name} must not contain duplicates")
    return sorted(items)


def _cid_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise _error(f"{name} must be a list")
    if len(value) > _MAX_LIST:
        raise _error(f"{name} exceeds maximum length")
    items = [_cid(item, name) for item in value]
    if len(items) != len(set(items)):
        raise _error(f"{name} must not contain duplicates")
    return sorted(items)


def _optional_nonneg_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise _error(f"{name} must be a nonnegative integer or unavailable null")
    if value > _JSON_MAX_INT:
        raise _error(f"{name} exceeds the JSON-safe integer bound")
    return value


def _ordered(payload: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    return {key: payload[key] for key in fields}


def _normalize_section(
    provided: Mapping[str, Any] | None,
    defaults: Mapping[str, Any],
    fields: Sequence[str],
    name: str,
    *,
    derived: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    derived = dict(derived or {})
    if provided is None:
        payload = dict(defaults)
        payload.update(derived)
        return _ordered(payload, fields)
    allowed = set(fields)
    if not isinstance(provided, Mapping):
        raise _error(f"{name} must be a mapping")
    extra = set(provided) - allowed
    if extra:
        raise _error(f"{name} unknown field {sorted(extra)}")
    missing = allowed - set(provided) - set(derived)
    if missing:
        raise _error(f"{name} omitted view input {sorted(missing)}")
    payload = dict(defaults)
    payload.update(dict(provided))
    for key, value in derived.items():
        claimed = provided.get(key, value)
        if key in provided and provided[key] != value:
            raise _error(f"{name}.{key} does not match derived identity")
        payload[key] = claimed if key in provided else value
    return _ordered(_closed(payload, fields, name), fields)


def _cid_label(label: str) -> str:
    from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes

    return cid_for_bytes(label.encode("utf-8"))


def _path(*nodes: str) -> GraphPath:
    return GraphPath(nodes=nodes or ("target",), edge_relation="depends_on")


def _span(path: str) -> SourceSpan:
    return SourceSpan(path=path, start_line=1, end_line=1, start_col=1, end_col=1)


def _header(
    *,
    repository_state_cid: str,
    context_pack_cid: str,
    execution_mode: str,
    policy_cid: str,
) -> GovernorArtifactHeader:
    mode = ExecutionMode(execution_mode)
    terminal = (
        GovernorTerminalStatus.SIMULATED
        if mode is ExecutionMode.SIMULATED
        else GovernorTerminalStatus.COMPLETE
    )
    return GovernorArtifactHeader(
        artifact_kind="context_coverage_manifest",
        repository_state_cid=repository_state_cid,
        context_pack_cid=context_pack_cid,
        verification_bundle_cid=_cid_label("verification-bundle"),
        generator=GeneratorIdentity(
            generator_id=GENERATOR_ID,
            generator_version="0.1.0",
            interface_id=INTERFACE,
        ),
        provenance=ArtifactProvenance(
            producer_id=AUTHORITY,
            producer_version="0.1",
            execution_mode=mode,
            authority_source=AuthoritySource.DETERMINISTIC,
            input_cids=(repository_state_cid,),
            tool_ids=("proof_context.context_pack",),
            policy_cid=policy_cid,
            notes=None,
        ),
        terminal_status=terminal,
        assumptions=(
            GovernorAssumption(
                assumption_id="datasets_owned_pack",
                kind=AssumptionKind.COVERAGE,
                statement="ContextPack identity is datasets-owned",
                supporting_cids=(repository_state_cid,),
            ),
        ),
        metadata={},
    )


def _inclusion(
    *,
    artifact_id: str,
    path: str,
    artifact_cid: str,
    inclusion_kind: InclusionKind,
    symbol_id: str,
    token_cost: int,
) -> IncludedArtifactRecord:
    return IncludedArtifactRecord(
        artifact_id=artifact_id,
        artifact_kind=CoveredArtifactKind.SYMBOL,
        inclusion_kind=inclusion_kind,
        token_cost=token_cost,
        symbol_id=symbol_id,
        path=path,
        artifact_cid=artifact_cid,
        confidence_bp=10_000,
        dependency_path=_path(symbol_id),
        source_span=_span(path),
        notes=None,
    )


def _bind_kinds(
    identity_kind: str, evidence_kind: str, execution_mode: str
) -> tuple[str, str, str]:
    identity_kind = _enum_member(identity_kind, IDENTITY_KINDS, "identity_kind")
    evidence_kind = _enum_member(evidence_kind, EVIDENCE_KINDS, "evidence_kind")
    execution_mode = _enum_member(execution_mode, EXECUTION_MODES, "execution_mode")
    pair = (identity_kind, evidence_kind, execution_mode)
    if pair not in _CONSISTENT_KINDS:
        if identity_kind == "fixture" or evidence_kind == "fixture":
            raise _error("fixture/live identities must remain distinct")
        if identity_kind == "synthetic" or evidence_kind == "synthetic":
            raise _error("synthetic/real identities must remain distinct")
        raise _error(
            "identity_kind, evidence_kind, and execution_mode are inconsistent"
        )
    return pair


def _bind_freshness(freshness: str) -> str:
    status = _nfc(freshness, "freshness")
    if status == "stale":
        raise StaleContextError("stale capsules cannot mint a v0.1 ContextPack")
    if status not in FRESHNESS_MINTABLE:
        raise _error(f"weak freshness {status!r} cannot mint a ContextPack")
    return status


def _bind_required_sources(
    target_source_cid: str,
    surrounding_source_cid: str,
    test_source_cid: str,
) -> dict[str, str]:
    return {
        "target_source": _cid(target_source_cid, "target_source_cid"),
        "surrounding_source": _cid(surrounding_source_cid, "surrounding_source_cid"),
        "test_source": _cid(test_source_cid, "test_source_cid"),
    }


def _bind_scope(provided: Mapping[str, Any] | None) -> dict[str, Any]:
    defaults = {
        "affected_files": [],
        "affected_symbols": [],
        "dependency_cone": [],
        "reverse_dependencies": [],
        "explicitly_excluded_paths": [],
        "changed_interfaces_and_schemas": [],
        "semantic_diff_summary": None,
    }
    raw = _normalize_section(provided, defaults, SCOPE_FIELDS, "scope")
    return {
        "affected_files": _string_list(raw["affected_files"], "scope.affected_files"),
        "affected_symbols": _string_list(
            raw["affected_symbols"], "scope.affected_symbols"
        ),
        "dependency_cone": _string_list(raw["dependency_cone"], "scope.dependency_cone"),
        "reverse_dependencies": _string_list(
            raw["reverse_dependencies"], "scope.reverse_dependencies"
        ),
        "explicitly_excluded_paths": _string_list(
            raw["explicitly_excluded_paths"], "scope.explicitly_excluded_paths"
        ),
        "changed_interfaces_and_schemas": _string_list(
            raw["changed_interfaces_and_schemas"],
            "scope.changed_interfaces_and_schemas",
        ),
        "semantic_diff_summary": _optional_nfc(
            raw["semantic_diff_summary"], "scope.semantic_diff_summary"
        ),
    }


def _bind_contracts(provided: Mapping[str, Any] | None) -> dict[str, Any]:
    defaults = {field: [] for field in CONTRACT_FIELDS}
    raw = _normalize_section(provided, defaults, CONTRACT_FIELDS, "contracts")
    return {
        field: _string_list(raw[field], f"contracts.{field}")
        for field in CONTRACT_FIELDS
    }


def _bind_validation(provided: Mapping[str, Any] | None) -> dict[str, Any]:
    defaults = {field: [] for field in VALIDATION_FIELDS}
    raw = _normalize_section(provided, defaults, VALIDATION_FIELDS, "validation")
    return {
        field: _string_list(raw[field], f"validation.{field}")
        for field in VALIDATION_FIELDS
    }


def _bind_history(provided: Mapping[str, Any] | None) -> dict[str, Any]:
    defaults = {field: [] for field in HISTORY_FIELDS}
    raw = _normalize_section(provided, defaults, HISTORY_FIELDS, "history")
    return {
        field: _string_list(raw[field], f"history.{field}") for field in HISTORY_FIELDS
    }


def _bind_questions(
    provided: Mapping[str, Any] | None,
    *,
    identity_kind: str,
) -> dict[str, Any]:
    defaults = {
        "named_unresolved_questions": [],
        "missing_evidence": [],
        "completeness_witness": None,
        "expansion_references": [],
    }
    raw = _normalize_section(provided, defaults, QUESTION_FIELDS, "questions")
    witness = _optional_cid(
        raw["completeness_witness"], "questions.completeness_witness"
    )
    if identity_kind == "synthetic" and witness is not None:
        raise _error("synthetic identity cannot be accepted as complete")
    return {
        "named_unresolved_questions": _string_list(
            raw["named_unresolved_questions"], "questions.named_unresolved_questions"
        ),
        "missing_evidence": _string_list(
            raw["missing_evidence"], "questions.missing_evidence"
        ),
        "completeness_witness": witness,
        "expansion_references": _string_list(
            raw["expansion_references"], "questions.expansion_references"
        ),
    }


def _bind_budgets(provided: Mapping[str, Any] | None) -> dict[str, Any]:
    defaults = {
        "maximum_bytes": None,
        "maximum_tokens": None,
        "maximum_retrieval_operations": None,
        "maximum_model_class": None,
        "maximum_wall_time": None,
        "validation_reserve_models_cannot_consume": True,
    }
    raw = _normalize_section(provided, defaults, BUDGET_FIELDS, "budgets")
    reserve = _bool(
        raw["validation_reserve_models_cannot_consume"],
        "budgets.validation_reserve_models_cannot_consume",
    )
    if reserve is not True:
        raise _error("validation reserve cannot be consumed by models")
    model_class = raw["maximum_model_class"]
    if model_class is not None:
        model_class = _enum_member(
            model_class, ROUTE_TIERS, "budgets.maximum_model_class"
        )
    return {
        "maximum_bytes": _optional_nonneg_int(
            raw["maximum_bytes"], "budgets.maximum_bytes"
        ),
        "maximum_tokens": _optional_nonneg_int(
            raw["maximum_tokens"], "budgets.maximum_tokens"
        ),
        "maximum_retrieval_operations": _optional_nonneg_int(
            raw["maximum_retrieval_operations"],
            "budgets.maximum_retrieval_operations",
        ),
        "maximum_model_class": model_class,
        "maximum_wall_time": _optional_nonneg_int(
            raw["maximum_wall_time"], "budgets.maximum_wall_time"
        ),
        "validation_reserve_models_cannot_consume": True,
    }


def _bind_freshness_bindings(provided: Mapping[str, Any] | None) -> dict[str, Any]:
    defaults = {field: [] for field in FRESHNESS_BINDING_FIELDS}
    raw = _normalize_section(
        provided, defaults, FRESHNESS_BINDING_FIELDS, "freshness_bindings"
    )
    return {
        field: _string_list(raw[field], f"freshness_bindings.{field}")
        for field in FRESHNESS_BINDING_FIELDS
    }


def _bind_invalidation(provided: Mapping[str, Any] | None) -> dict[str, Any]:
    defaults = {field: [] for field in INVALIDATION_FIELDS}
    raw = _normalize_section(provided, defaults, INVALIDATION_FIELDS, "invalidation")
    return {
        field: _string_list(raw[field], f"invalidation.{field}")
        for field in INVALIDATION_FIELDS
    }


def _bind_parent(
    provided: Mapping[str, Any] | None, parent_context_pack_cid: str | None
) -> dict[str, Any]:
    defaults = {"parent_context_pack_cid": parent_context_pack_cid}
    raw = _normalize_section(provided, defaults, PARENT_FIELDS, "parent")
    bound = _optional_cid(raw["parent_context_pack_cid"], "parent.parent_context_pack_cid")
    if parent_context_pack_cid is not None and bound != parent_context_pack_cid:
        raise _error("parent.parent_context_pack_cid does not match parent input")
    return {"parent_context_pack_cid": bound}


def _bind_delta(
    provided: Mapping[str, Any] | None,
    *,
    delta_cid: str | None,
    incremental: bool,
    parent_cid: str | None,
) -> dict[str, Any]:
    defaults = {
        "delta_cid": delta_cid,
        "incremental": incremental,
        "named_missing": [],
    }
    raw = _normalize_section(provided, defaults, DELTA_FIELDS, "delta")
    bound_delta = _optional_cid(raw["delta_cid"], "delta.delta_cid")
    bound_incremental = _bool(raw["incremental"], "delta.incremental")
    named_missing = _string_list(raw["named_missing"], "delta.named_missing")
    if bound_incremental:
        if parent_cid is None or bound_delta is None:
            raise _error("incremental packs require parent and delta identity")
    elif parent_cid is not None or bound_delta is not None:
        raise _error("non-incremental packs cannot bind parent or delta identity")
    return {
        "delta_cid": bound_delta,
        "incremental": bound_incremental,
        "named_missing": named_missing,
    }


def _bind_identity(
    provided: Mapping[str, Any] | None,
    *,
    repository_identity: str,
    commit: str | None,
    tree: str,
    objective_identity: str,
    objective_revision: str,
    policy_identity: str,
    creation_time: str,
    content_cid: str,
    parent_context_pack_cid: str | None,
) -> dict[str, Any]:
    defaults = {
        "schema_and_interface_version": INTERFACE,
        "repository_identity": repository_identity,
        "commit": commit,
        "tree": tree,
        "objective_identity": objective_identity,
        "objective_revision": objective_revision,
        "policy_identity": policy_identity,
        "builder_identity": INTERFACE,
        "creation_time": creation_time,
        "parent_context_pack_cid": parent_context_pack_cid,
    }
    raw = _normalize_section(
        provided,
        defaults,
        IDENTITY_FIELDS,
        "identity",
        derived={"content_cid": content_cid},
    )
    interface_version = _nfc(
        raw["schema_and_interface_version"], "identity.schema_and_interface_version"
    )
    builder = _nfc(raw["builder_identity"], "identity.builder_identity")
    if (
        interface_version in FORBIDDEN_INTERFACES
        or builder in FORBIDDEN_INTERFACES
        or interface_version != INTERFACE
        or builder != INTERFACE
    ):
        raise _error("ownership drift: DatasetsContextPackAuthority is the sole type")
    bound_parent = _optional_cid(
        raw["parent_context_pack_cid"], "identity.parent_context_pack_cid"
    )
    if bound_parent != parent_context_pack_cid:
        raise _error("identity.parent_context_pack_cid does not match parent input")
    tree_value = _git_oid(raw["tree"], "identity.tree")
    if tree_value != tree:
        raise _error("identity.tree does not match scanned_tree_oid")
    commit_value = raw["commit"]
    if commit_value is not None:
        try:
            commit_value = _cid(commit_value, "identity.commit")
        except ContextPackConstructionError:
            commit_value = _git_oid(commit_value, "identity.commit")
    return {
        "schema_and_interface_version": interface_version,
        "repository_identity": _nfc(
            raw["repository_identity"], "identity.repository_identity"
        ),
        "commit": commit_value,
        "tree": tree_value,
        "objective_identity": _nfc(
            raw["objective_identity"], "identity.objective_identity"
        ),
        "objective_revision": _nfc(
            raw["objective_revision"], "identity.objective_revision"
        ),
        "policy_identity": _cid(raw["policy_identity"], "identity.policy_identity"),
        "builder_identity": builder,
        "creation_time": _nfc(raw["creation_time"], "identity.creation_time"),
        "content_cid": _cid(raw["content_cid"], "identity.content_cid"),
        "parent_context_pack_cid": bound_parent,
    }


def _canonical_dict(payload: Mapping[str, Any]) -> dict[str, Any]:
    canonical = _ordered(_closed(payload, CANONICAL_FIELDS, "canonical payload"), CANONICAL_FIELDS)
    try:
        validate_structured_value(canonical, path="canonical")
    except ContextPackConstructionError:
        raise
    except Exception as exc:
        raise _error(f"canonical payload is not a closed structured identity: {exc}") from exc
    return canonical


def load_context_pack_schema() -> dict[str, Any]:
    """Load the closed ContextPack JSON Schema from package data."""

    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def canonical_payload_from_envelope(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Return the CID input subset of a closed envelope."""

    closed = _closed(envelope, ENVELOPE_FIELDS, "context pack envelope")
    return {key: closed[key] for key in CANONICAL_FIELDS}


def validate_context_pack_envelope(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed on unknown fields, omitted view inputs, and forged CIDs."""

    closed = _closed(envelope, ENVELOPE_FIELDS, "context pack envelope")
    if closed["schema"] != CONTEXT_PACK_SCHEMA or closed["interface"] != INTERFACE:
        raise _error("ownership drift: envelope is not DatasetsContextPackAuthority")
    if closed["producer"] != AUTHORITY:
        raise _error("ownership drift: producer is not the datasets authority")
    if closed["interface"] in FORBIDDEN_INTERFACES:
        raise _error("ownership drift: competing ContextPack type")
    canonical = {key: closed[key] for key in CANONICAL_FIELDS}
    try:
        validate_structured_value(canonical, path="canonical")
    except Exception as exc:
        raise _error(f"canonical payload is not a closed structured identity: {exc}") from exc
    claimed = _cid(closed["pack_cid"], "pack_cid")
    recomputed = cid_for_structured(canonical)
    if claimed != recomputed:
        raise _error("pack_cid does not match recomputed canonical identity")
    if type(closed["expansion_required"]) is not bool:
        raise _error("expansion_required must be a boolean")
    _nfc(closed["sufficiency_state"], "sufficiency_state")
    return _thaw(closed)


@dataclass(frozen=True)
class ContextPackRecord:
    """Datasets-owned v0.1 ContextPack identity."""

    pack_cid: str
    repository_state_cid: str
    view: ContextPackView
    sufficiency_state: str
    expansion_required: bool
    capsule_cids: tuple[str, ...]
    required_source_cids: Mapping[str, str]
    canonical: Mapping[str, Any]
    producer: str = AUTHORITY
    schema: str = CONTEXT_PACK_SCHEMA

    def canonical_payload(self) -> dict[str, Any]:
        return _thaw(self.canonical)

    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.canonical_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.canonical_payload()
        payload["pack_cid"] = self.pack_cid
        payload["sufficiency_state"] = self.sufficiency_state
        payload["expansion_required"] = self.expansion_required
        return payload

    def identity_payload(self) -> dict[str, Any]:
        return self.to_dict()

    def verify_identity(self) -> str:
        return decode_and_recompute_structured(self.pack_cid, self.canonical_payload())


class DatasetsContextPackAuthority:
    """Sole datasets-owned ContextPack construction authority.

    Reconciles ``DatasetsContextPackAuthority@0.1`` with the accelerator
    ``ContextPack@1`` consumer contract. This is not a competing
    ``SupervisorContextPack`` type.
    """

    schema: ClassVar[str] = CONTEXT_PACK_SCHEMA
    interface: ClassVar[str] = INTERFACE
    producer: ClassVar[str] = AUTHORITY
    consumer_interface: ClassVar[str] = CONSUMER_INTERFACE
    port_schema: ClassVar[str] = PORT_SCHEMA

    def build(self, **kwargs: Any) -> ContextPackRecord:
        return build_context_pack(**kwargs)

    def canonical_bytes(self, record: ContextPackRecord) -> bytes:
        return record.canonical_bytes()

    def verify(self, record: ContextPackRecord) -> str:
        return record.verify_identity()

    def validate_envelope(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        return validate_context_pack_envelope(envelope)


def get_authority() -> DatasetsContextPackAuthority:
    return DatasetsContextPackAuthority()


def build_context_pack(
    *,
    repository_state_cid: str,
    task_id: str,
    task_class: str = "local_bug",
    risk_class: str = "low",
    route_tier: str | RouteTier = RouteTier.SMALL,
    target_source_cid: str,
    surrounding_source_cid: str,
    test_source_cid: str,
    scanned_tree_oid: str,
    source_tree_oid: str | None = None,
    capsule_cids: Sequence[str] = (),
    freshness: str = "fresh",
    opaque: bool = False,
    unavailable: bool = False,
    execution_mode: str | ExecutionMode = ExecutionMode.LIVE,
    identity_kind: str = "live",
    evidence_kind: str = "real",
    repository_identity: str = PRODUCER_REPOSITORY,
    commit: str | None = None,
    objective_identity: str | None = None,
    objective_revision: str = "unavailable",
    policy_identity: str | None = None,
    creation_time: str = "unavailable",
    parent_context_pack_cid: str | None = None,
    delta_cid: str | None = None,
    incremental: bool = False,
    identity: Mapping[str, Any] | None = None,
    scope: Mapping[str, Any] | None = None,
    contracts: Mapping[str, Any] | None = None,
    validation: Mapping[str, Any] | None = None,
    history: Mapping[str, Any] | None = None,
    questions: Mapping[str, Any] | None = None,
    budgets: Mapping[str, Any] | None = None,
    freshness_bindings: Mapping[str, Any] | None = None,
    invalidation: Mapping[str, Any] | None = None,
    parent: Mapping[str, Any] | None = None,
    delta: Mapping[str, Any] | None = None,
) -> ContextPackRecord:
    """Construct the v0.1 ContextPack identity from exact source CIDs.

    Stale, unavailable, opaque-without-exact-source, omitted view inputs,
    unknown fields, fixture-as-live, synthetic-as-complete, and competing
    types fail closed. Token budgeting remains an accelerator consumer
    concern; bound budget fields are identity only.
    """
    if unavailable:
        raise UnavailableContextError("unavailable ContextPack inputs are not success")
    freshness_status = _bind_freshness(freshness)
    opaque = _bool(opaque, "opaque")
    if opaque:
        if not source_tree_oid or source_tree_oid != scanned_tree_oid:
            raise OpaqueSourceRequiredError(
                "opaque content requires the exact scanned-tree source"
            )

    identity_kind, evidence_kind, execution_mode = _bind_kinds(
        identity_kind, evidence_kind, execution_mode
    )
    route_tier_value = _enum_member(route_tier, ROUTE_TIERS, "route_tier")
    task_id_value = _nfc(task_id, "task_id")
    task_class_value = _nfc(task_class, "task_class")
    risk_class_value = _nfc(risk_class, "risk_class")
    repository_state = _cid(repository_state_cid, "repository_state_cid")
    scanned_tree = _git_oid(scanned_tree_oid, "scanned_tree_oid")
    source_tree = _optional_git_oid(source_tree_oid, "source_tree_oid")
    required = _bind_required_sources(
        target_source_cid, surrounding_source_cid, test_source_cid
    )
    capsules = _cid_list(list(capsule_cids), "capsule_cids")
    parent_cid = _optional_cid(parent_context_pack_cid, "parent_context_pack_cid")
    bound_parent = _bind_parent(parent, parent_cid)
    parent_cid = bound_parent["parent_context_pack_cid"]
    bound_delta = _bind_delta(
        delta,
        delta_cid=_optional_cid(delta_cid, "delta_cid"),
        incremental=_bool(incremental, "incremental"),
        parent_cid=parent_cid,
    )
    bound_scope = _bind_scope(scope)
    bound_contracts = _bind_contracts(contracts)
    bound_validation = _bind_validation(validation)
    bound_history = _bind_history(history)
    bound_questions = _bind_questions(questions, identity_kind=identity_kind)
    bound_budgets = _bind_budgets(budgets)
    bound_freshness = _bind_freshness_bindings(freshness_bindings)
    bound_invalidation = _bind_invalidation(invalidation)
    content = {
        "scope": bound_scope,
        "contracts": bound_contracts,
        "validation": bound_validation,
        "history": bound_history,
        "questions": bound_questions,
        "budgets": bound_budgets,
        "required_source_cids": dict(required),
        "capsule_cids": list(capsules),
    }
    content_cid = cid_for_obj(content)
    policy_cid = (
        _cid(policy_identity, "policy_identity")
        if policy_identity is not None
        else _cid_label("policy")
    )
    bound_identity = _bind_identity(
        identity,
        repository_identity=_nfc(repository_identity, "repository_identity"),
        commit=commit,
        tree=scanned_tree,
        objective_identity=_nfc(
            objective_identity if objective_identity is not None else task_id_value,
            "objective_identity",
        ),
        objective_revision=_nfc(objective_revision, "objective_revision"),
        policy_identity=policy_cid,
        creation_time=_nfc(creation_time, "creation_time"),
        content_cid=content_cid,
        parent_context_pack_cid=parent_cid,
    )
    canonical = _canonical_dict(
        {
            "schema": CONTEXT_PACK_SCHEMA,
            "interface": INTERFACE,
            "producer": AUTHORITY,
            "repository_state_cid": repository_state,
            "task_id": task_id_value,
            "task_class": task_class_value,
            "risk_class": risk_class_value,
            "route_tier": route_tier_value,
            "required_source_cids": dict(required),
            "capsule_cids": list(capsules),
            "scanned_tree_oid": scanned_tree,
            "source_tree_oid": source_tree,
            "opaque": opaque,
            "freshness": freshness_status,
            "execution_mode": execution_mode,
            "identity_kind": identity_kind,
            "evidence_kind": evidence_kind,
            "identity": bound_identity,
            "scope": bound_scope,
            "contracts": bound_contracts,
            "validation": bound_validation,
            "history": bound_history,
            "questions": bound_questions,
            "budgets": bound_budgets,
            "freshness_bindings": bound_freshness,
            "invalidation": bound_invalidation,
            "parent": bound_parent,
            "delta": bound_delta,
        }
    )
    pack_cid = cid_for_obj(canonical)

    inclusions = [
        _inclusion(
            artifact_id="inc_target",
            path="target.py",
            artifact_cid=required["target_source"],
            inclusion_kind=InclusionKind.RAW_SOURCE,
            symbol_id="target",
            token_cost=100,
        ),
        _inclusion(
            artifact_id="inc_surrounding",
            path="surrounding.py",
            artifact_cid=required["surrounding_source"],
            inclusion_kind=InclusionKind.RAW_SOURCE,
            symbol_id="surrounding",
            token_cost=40,
        ),
        _inclusion(
            artifact_id="inc_test",
            path="test_target.py",
            artifact_cid=required["test_source"],
            inclusion_kind=InclusionKind.RAW_SOURCE,
            symbol_id="test",
            token_cost=40,
        ),
    ]
    for index, capsule_cid in enumerate(capsules):
        inclusions.append(
            _inclusion(
                artifact_id=f"inc_capsule_{index}",
                path=f"dep_{index}.py",
                artifact_cid=capsule_cid,
                inclusion_kind=InclusionKind.EXACT_CAPSULE,
                symbol_id=f"dep_{index}",
                token_cost=20,
            )
        )
    raw_count = sum(
        1 for item in inclusions if item.inclusion_kind in {InclusionKind.RAW_SOURCE, "raw_source"}
    )
    capsule_count = len(tuple(capsules))
    manifest = ContextCoverageManifest(
        header=_header(
            repository_state_cid=repository_state,
            context_pack_cid=pack_cid,
            execution_mode=execution_mode,
            policy_cid=policy_cid,
        ),
        manifest_id="manifest_" + "".join(
            ch.lower() if ch.isalnum() or ch in "._:/+-" else "_"
            for ch in task_id_value
        ).lstrip("_") or "pack",
        target_symbol_ids=("target",),
        inclusions=tuple(inclusions),
        exclusions=(),
        context_budget_tokens=500,
        minimum_safe_tokens=80,
        total_included_tokens=sum(item.token_cost for item in inclusions),
        total_excluded_tokens=0,
        raw_inclusion_count=raw_count,
        capsule_inclusion_count=capsule_count,
        exclusion_count=0,
        known_gaps=(),
        opaque_dependency_ids=(),
        dependency_paths=(_path("target"),),
        policy_cid=policy_cid,
        notes=None,
        metadata={"authority": AUTHORITY},
    )
    view = ContextPackView(
        context_pack_cid=pack_cid,
        coverage_manifest=manifest,
        task_class=task_class_value,
        risk_class=risk_class_value,
        route_tier=route_tier_value,
    )
    repo = RepositoryStateView(
        repository_state_cid=repository_state,
        stale_capsule_ids=(),
        unresolved_invalidation_ids=(),
        opaque_critical_dependency_ids=(),
        conflicting_evidence=False,
        policy_boundary=False,
        disclosure_overflow=False,
    )
    policy = VerificationPolicyView(
        selected_tests=True,
        full_suite=True,
        static_checks=True,
        type_checks=True,
        proofs=False,
        human_review=False,
        acceptance_requirements=TaskClassAcceptanceRequirements(
            task_class=task_class_value,
            risk_class=risk_class_value,
            require_selected_tests=True,
            require_full_suite_fallback=True,
            require_static_checks=True,
            require_type_checks=True,
            require_proofs=False,
            require_human_review=False,
        ),
        verification_passed=False,
    )
    claim = evaluate_context_sufficiency(view, repo, policy)
    state = getattr(claim, "state", None) or getattr(claim, "sufficiency_state", "unknown")
    if hasattr(state, "value"):
        state = state.value
    state_text = str(state)
    expansion_required = state_text not in {"sufficient", "SUFFICIENT"}
    if state_text in {"insufficient", "INSUFFICIENT"}:
        raise InsufficientContextError("insufficient context cannot be promoted")
    return ContextPackRecord(
        pack_cid=pack_cid,
        repository_state_cid=repository_state,
        view=view,
        sufficiency_state=state_text,
        expansion_required=expansion_required,
        capsule_cids=tuple(capsules),
        required_source_cids=required,
        canonical=canonical,
    )
