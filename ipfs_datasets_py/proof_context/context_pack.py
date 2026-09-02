"""Datasets-owned v0.1 ContextPack construction authority (PCCE-012).

This module is the sole production builder for ContextPack identity,
coverage view, and pre-execution sufficiency. It does not implement a
new analyzer or capsule compiler. Accelerator may only delegate.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import cid_for_obj
from ipfs_datasets_py.logic.software_contracts.semantic_governor.audit_contracts import (
    ContextCoverageManifest,
    CoveredArtifactKind,
    ExcludedArtifactRecord,
    ExclusionReason,
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
    StaleContextError,
    UnavailableContextError,
)

AUTHORITY = "ipfs_datasets_py.proof_context.context_pack"
INTERFACE = "DatasetsContextPackAuthority@0.1"
GENERATOR_ID = "datasets_v01_context_pack"

# PCPR-014 canonical ContextPack contract. v0.1 remains importable as
# compatibility-only and must not silently remint @1 identity.
CANONICAL_INTERFACE: Final = "DatasetsContextPack@1"
CANONICAL_SCHEMA: Final = "ipfs_datasets_py/datasets-context-pack@1"
CANONICAL_DOMAIN: Final = "datasets.context-pack"
CANONICAL_VERSION: Final = "1"
V01_INTERFACE: Final = INTERFACE
V01_MATURITY: Final = "compatibility_only"
DATASETS_CONTEXT_PACK_CANONICAL: Final = True

_EXECUTABLE_MINT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "backend_request",
        "cegar_receipt",
        "interpolant",
        "proof_result",
        "smt_session",
        "solver_result",
    }
)
_REQUIRED_CONTEXT_PACK_FIELDS: Final[tuple[str, ...]] = (
    "repository_state_cid",
    "scanned_tree_oid",
    "surrounding_source_cid",
    "target_source_cid",
    "task_id",
    "test_source_cid",
)
_ALLOWED_CONTEXT_PACK_FIELDS: Final[frozenset[str]] = frozenset(
    _REQUIRED_CONTEXT_PACK_FIELDS
) | frozenset(
    {
        "advisory",
        "bounds",
        "capsule_cids",
        "executable",
        "freshness",
        "interface",
        "opaque",
        "risk_class",
        "route_tier",
        "schema",
        "source_tree_oid",
        "task_class",
        "unavailable",
    }
)


class ContextPackConstructionError(RuntimeError):
    reason = "invalid"


class ContextPackAdmissionError(ContextPackConstructionError):
    """Raised when a ContextPack request is free-form, advisory, or executable."""

    reason = "rejected"


def _cid_label(label: str) -> str:
    from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes

    return cid_for_bytes(label.encode("utf-8"))


def _path(*nodes: str) -> GraphPath:
    return GraphPath(nodes=nodes or ("target",), edge_relation="depends_on")


def _span(path: str) -> SourceSpan:
    return SourceSpan(path=path, start_line=1, end_line=1, start_col=1, end_col=1)


def _header(*, repository_state_cid: str, context_pack_cid: str) -> GovernorArtifactHeader:
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
            execution_mode=ExecutionMode.LIVE,
            authority_source=AuthoritySource.DETERMINISTIC,
            input_cids=(repository_state_cid,),
            tool_ids=("proof_context.context_pack",),
            policy_cid=_cid_label("policy"),
            notes=None,
        ),
        terminal_status=GovernorTerminalStatus.COMPLETE,
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
    producer: str = AUTHORITY
    schema: str = PORT_SCHEMA

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": PORT_SCHEMA,
            "interface": INTERFACE,
            "pack_cid": self.pack_cid,
            "repository_state_cid": self.repository_state_cid,
            "sufficiency_state": self.sufficiency_state,
            "expansion_required": self.expansion_required,
            "capsule_cids": list(self.capsule_cids),
            "required_source_cids": dict(self.required_source_cids),
            "producer": self.producer,
        }


def _require_cid_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value.strip() != value:
        raise ContextPackAdmissionError(f"{name} must be a non-empty exact CID string")
    if any(ch.isspace() for ch in value):
        raise ContextPackAdmissionError(f"{name} must not contain whitespace")
    return value


def _require_task_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or value.strip() != value:
        raise ContextPackAdmissionError("task_id must be a non-empty exact string")
    return value


def context_pack_v1_identity_payload(
    *,
    repository_state_cid: str,
    task_id: str,
    task_class: str,
    required_source_cids: Mapping[str, str],
    capsule_cids: Sequence[str],
    scanned_tree_oid: str,
    freshness: str,
    opaque: bool,
) -> dict[str, Any]:
    """Canonical @1 identity preimage. Order is stable JSON map-key order."""

    return {
        "capsule_cids": list(capsule_cids),
        "freshness": freshness,
        "interface": CANONICAL_INTERFACE,
        "opaque": opaque,
        "repository_state_cid": repository_state_cid,
        "required_source_cids": dict(required_source_cids),
        "scanned_tree_oid": scanned_tree_oid,
        "schema": CANONICAL_SCHEMA,
        "task_class": task_class,
        "task_id": task_id,
    }


@dataclass(frozen=True)
class DatasetsContextPack:
    """Datasets-owned canonical ContextPack@1 identity.

    Construction is identity minting, not executable solver work. Advisory
    material cannot authorize a pack. v0.1 CIDs are not reminted as @1.
    """

    pack_cid: str
    repository_state_cid: str
    required_source_cids: Mapping[str, str]
    capsule_cids: tuple[str, ...]
    scanned_tree_oid: str
    task_id: str
    task_class: str
    freshness: str
    opaque: bool
    producer: str = AUTHORITY
    interface: str = CANONICAL_INTERFACE
    schema: str = CANONICAL_SCHEMA
    v01_compatibility_interface: str = V01_INTERFACE
    v01_maturity: str = V01_MATURITY

    def identity_payload(self) -> dict[str, Any]:
        return context_pack_v1_identity_payload(
            repository_state_cid=self.repository_state_cid,
            task_id=self.task_id,
            task_class=self.task_class,
            required_source_cids=self.required_source_cids,
            capsule_cids=self.capsule_cids,
            scanned_tree_oid=self.scanned_tree_oid,
            freshness=self.freshness,
            opaque=self.opaque,
        )


def admit_datasets_context_pack(payload: Mapping[str, Any]) -> DatasetsContextPack:
    """Admit a DatasetsContextPack@1 request.

    Free-form, advisory-as-authority, and executable-minting payloads fail
    closed. Stale, unavailable, and opaque-without-exact-source stay typed
    errors. Identities are deterministic under ``ir-canonical-identity-v1``.
    """
    if not isinstance(payload, Mapping):
        raise ContextPackAdmissionError("DatasetsContextPack@1 payload must be a mapping")
    extra = sorted(set(payload) - _ALLOWED_CONTEXT_PACK_FIELDS)
    if extra:
        raise ContextPackAdmissionError(
            f"free-form ContextPack field(s) cannot mint DatasetsContextPack@1: {extra[0]}"
        )
    minted = sorted(set(payload) & _EXECUTABLE_MINT_KEYS)
    if minted:
        raise ContextPackAdmissionError(
            f"field {minted[0]!r} cannot mint executable work from a ContextPack request"
        )
    if payload.get("advisory") is True:
        raise ContextPackAdmissionError(
            "advisory ContextPack material is non-authoritative and cannot mint DatasetsContextPack@1"
        )
    if payload.get("executable") is True:
        raise ContextPackAdmissionError(
            "ContextPack construction is identity minting, not executable work"
        )
    if payload.get("unavailable") is True:
        raise UnavailableContextError("unavailable ContextPack inputs are not success")
    freshness = payload.get("freshness", "fresh")
    if not isinstance(freshness, str) or not freshness:
        raise ContextPackAdmissionError("freshness must be a non-empty string")
    if freshness == "stale":
        raise StaleContextError("stale capsules cannot mint a DatasetsContextPack@1")
    opaque = bool(payload.get("opaque", False))
    scanned_tree_oid = _require_cid_text(payload.get("scanned_tree_oid"), "scanned_tree_oid")
    source_tree_oid = payload.get("source_tree_oid")
    if opaque:
        if not isinstance(source_tree_oid, str) or source_tree_oid != scanned_tree_oid:
            raise OpaqueSourceRequiredError(
                "opaque content requires the exact scanned-tree source"
            )
    declared_interface = payload.get("interface")
    if declared_interface not in (None, CANONICAL_INTERFACE, V01_INTERFACE):
        raise ContextPackAdmissionError(
            f"unsupported ContextPack interface {declared_interface!r}"
        )
    declared_schema = payload.get("schema")
    if declared_schema not in (None, CANONICAL_SCHEMA, PORT_SCHEMA):
        raise ContextPackAdmissionError(
            f"unsupported ContextPack schema {declared_schema!r}"
        )
    missing = [name for name in _REQUIRED_CONTEXT_PACK_FIELDS if not payload.get(name)]
    if missing:
        raise ContextPackAdmissionError(
            f"DatasetsContextPack@1 requires {missing[0]}"
        )
    required = {
        "surrounding_source": _require_cid_text(
            payload.get("surrounding_source_cid"), "surrounding_source_cid"
        ),
        "target_source": _require_cid_text(
            payload.get("target_source_cid"), "target_source_cid"
        ),
        "test_source": _require_cid_text(
            payload.get("test_source_cid"), "test_source_cid"
        ),
    }
    capsule_raw = payload.get("capsule_cids", ())
    if isinstance(capsule_raw, (str, bytes, bytearray)) or not isinstance(
        capsule_raw, Sequence
    ):
        raise ContextPackAdmissionError("capsule_cids must be a sequence of CID strings")
    capsule_cids = tuple(_require_cid_text(item, "capsule_cids") for item in capsule_raw)
    task_class = payload.get("task_class", "local_bug")
    if not isinstance(task_class, str) or not task_class.strip():
        raise ContextPackAdmissionError("task_class must be a non-empty string")
    identity_payload = context_pack_v1_identity_payload(
        repository_state_cid=_require_cid_text(
            payload.get("repository_state_cid"), "repository_state_cid"
        ),
        task_id=_require_task_id(payload.get("task_id")),
        task_class=task_class,
        required_source_cids=required,
        capsule_cids=capsule_cids,
        scanned_tree_oid=scanned_tree_oid,
        freshness=freshness,
        opaque=opaque,
    )
    from ipfs_datasets_py.logic.ir_core.identity import canonical_identity

    identity = canonical_identity(
        identity_payload,
        domain=CANONICAL_DOMAIN,
        schema_version=CANONICAL_SCHEMA,
    )
    return DatasetsContextPack(
        pack_cid=identity.cid,
        repository_state_cid=identity_payload["repository_state_cid"],
        required_source_cids=MappingProxyType(required),
        capsule_cids=capsule_cids,
        scanned_tree_oid=scanned_tree_oid,
        task_id=identity_payload["task_id"],
        task_class=task_class,
        freshness=freshness,
        opaque=opaque,
    )


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
) -> ContextPackRecord:
    """Construct the v0.1 ContextPack identity from exact source CIDs.

    Stale, unavailable, and opaque-without-exact-source fail closed. Token
    budgeting remains an accelerator consumer concern.
    """
    if unavailable:
        raise UnavailableContextError("unavailable ContextPack inputs are not success")
    if freshness == "stale":
        raise StaleContextError("stale capsules cannot mint a v0.1 ContextPack")
    if opaque:
        if not source_tree_oid or source_tree_oid != scanned_tree_oid:
            raise OpaqueSourceRequiredError(
                "opaque content requires the exact scanned-tree source"
            )

    required = {
        "target_source": target_source_cid,
        "surrounding_source": surrounding_source_cid,
        "test_source": test_source_cid,
    }
    identity = {
        "schema": PORT_SCHEMA,
        "interface": INTERFACE,
        "repository_state_cid": repository_state_cid,
        "task_id": task_id,
        "task_class": task_class,
        "risk_class": risk_class,
        "required_source_cids": required,
        "capsule_cids": list(capsule_cids),
        "scanned_tree_oid": scanned_tree_oid,
        "freshness": freshness,
        "opaque": opaque,
    }
    pack_cid = cid_for_obj(identity)

    inclusions = [
        _inclusion(
            artifact_id="inc_target",
            path="target.py",
            artifact_cid=target_source_cid,
            inclusion_kind=InclusionKind.RAW_SOURCE,
            symbol_id="target",
            token_cost=100,
        ),
        _inclusion(
            artifact_id="inc_surrounding",
            path="surrounding.py",
            artifact_cid=surrounding_source_cid,
            inclusion_kind=InclusionKind.RAW_SOURCE,
            symbol_id="surrounding",
            token_cost=40,
        ),
        _inclusion(
            artifact_id="inc_test",
            path="test_target.py",
            artifact_cid=test_source_cid,
            inclusion_kind=InclusionKind.RAW_SOURCE,
            symbol_id="test",
            token_cost=40,
        ),
    ]
    for index, capsule_cid in enumerate(capsule_cids):
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
    exclusions: tuple[ExcludedArtifactRecord, ...] = ()
    raw_count = sum(
        1 for item in inclusions if item.inclusion_kind in {InclusionKind.RAW_SOURCE, "raw_source"}
    )
    capsule_count = len(tuple(capsule_cids))
    manifest = ContextCoverageManifest(
        header=_header(
            repository_state_cid=repository_state_cid,
            context_pack_cid=pack_cid,
        ),
        manifest_id="manifest_" + "".join(
            ch.lower() if ch.isalnum() or ch in "._:/+-" else "_"
            for ch in task_id
        ).lstrip("_") or "pack",
        target_symbol_ids=("target",),
        inclusions=tuple(inclusions),
        exclusions=exclusions,
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
        policy_cid=_cid_label("policy"),
        notes=None,
        metadata={"authority": AUTHORITY},
    )
    view = ContextPackView(
        context_pack_cid=pack_cid,
        coverage_manifest=manifest,
        task_class=task_class,
        risk_class=risk_class,
        route_tier=route_tier,
    )
    repo = RepositoryStateView(
        repository_state_cid=repository_state_cid,
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
            task_class=task_class,
            risk_class=risk_class,
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
        repository_state_cid=repository_state_cid,
        view=view,
        sufficiency_state=state_text,
        expansion_required=expansion_required,
        capsule_cids=tuple(capsule_cids),
        required_source_cids=required,
    )
