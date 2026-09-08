"""Datasets-owned v0.1 ContextPack construction authority (PCCE-012).

This module is the sole production builder for ContextPack identity,
coverage view, and pre-execution sufficiency. It does not implement a
new analyzer or capsule compiler. Accelerator may only delegate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

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


class ContextPackConstructionError(RuntimeError):
    reason = "invalid"


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
