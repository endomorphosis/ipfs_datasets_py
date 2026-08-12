"""Additive environment invalidation over preserved ISI obligation plans.

The semantic invalidation layer first recomputes or verifies the supplied ISI
delta/plan through the final public API, preserves every ISI obligation and
supporting edge, and then appends only environment obligations.  It never
rewrites dependent source, invents test/proof/adapter/receipt IDs without an
authoritative edge or explicit binding, or floods every relation both ways.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Final, Iterable, Mapping, Protocol, Sequence, runtime_checkable

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    decode_and_recompute_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.delta import (
    diff_repository_states,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.invalidation import (
    calculate_invalidation,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    DependencyEdge,
    InvalidationObligation,
    InvalidationPlan,
    RelationType,
    RepositoryState,
    RepositoryStateDelta,
    SymbolKind,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.bindings import (
    BindingsError,
    bindings_by_id,
    build_environment_binding_set,
    changed_binding_ids,
    diff_environment_bindings,
    iter_affected_symbol_ids,
    relevant_binding_projection_for_symbol,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    ENVIRONMENT_BINDING_SET_SCHEMA,
    BindingKind,
    BindingScope,
    EnvironmentBinding,
    EnvironmentBindingSet,
    ObligationOrigin,
    SemanticInvalidationObligation,
    SemanticInvalidationPlan,
    SemanticStateRoot,
)


class SemanticInvalidationError(ValueError):
    """Raised when semantic invalidation inputs fail closed verification."""


class SemanticInvalidationReason(str, Enum):
    """Closed vocabulary for environment (and preserved ISI) reason codes."""

    # ISI-preserving codes (copied verbatim when origin=isi; listed for docs).
    NEW_CAPSULE = "new_capsule"
    PROOF_RERUN = "proof_rerun"
    STALE_TEST_RECEIPT = "stale_test_receipt"
    CALLER_SIGNATURE_MISMATCH = "caller_signature_mismatch"
    OBSOLETE_SCHEMA_ADAPTER = "obsolete_schema_adapter"
    EFFECT_ASSUMPTION_STALE = "effect_assumption_stale"
    EXCEPTION_RECOVERY_STALE = "exception_recovery_stale"
    PURITY_SECURITY_REVIEW = "purity_security_review"
    ENVIRONMENT_RECEIPT_STALE = "environment_receipt_stale"
    DELETED_SYMBOL_DEPENDENCY = "deleted_symbol_dependency"
    RAW_SOURCE_REQUIRED = "raw_source_requirement"

    # Environment-binding additive codes.
    DEPENDENCY_LOCK_CHANGED = "dependency_lock_changed"
    DEPENDENCY_MANIFEST_CHANGED = "dependency_manifest_changed"
    PYTEST_CONFIG_CHANGED = "pytest_config_changed"
    PYTEST_PLUGIN_CHANGED = "pytest_plugin_changed"
    PROOF_CONFIG_CHANGED = "proof_config_changed"
    POLICY_CHANGED = "policy_changed"
    INTERFACE_DESCRIPTOR_CHANGED = "interface_descriptor_changed"
    GENERATED_INPUT_CHANGED = "generated_input_changed"
    PYTHON_TOOLCHAIN_CHANGED = "python_toolchain_changed"
    SEMANTIC_SCHEMA_CHANGED = "semantic_schema_changed"
    SEMANTIC_COMPILER_CHANGED = "semantic_compiler_changed"
    ENVIRONMENT_BINDING_CHANGED = "environment_binding_changed"
    UNKNOWN_BINDING_SCOPE = "unknown_binding_scope"
    UNMAPPED_BINDING_SUBJECT = "unmapped_binding_subject"
    STALE_BOUND_CAPSULE = "stale_bound_capsule"
    STALE_BOUND_RECEIPT = "stale_bound_receipt"
    FULL_FALLBACK_REQUIRED = "full_fallback_required"


class SemanticInvalidationRule(str, Enum):
    """Finite environment invalidation rule families."""

    DEPENDENCY = "dependency"
    PYTEST_CONFIG = "pytest_config"
    PROOF_CONFIG = "proof_config"
    POLICY = "policy"
    INTERFACE = "interface"
    GENERATED = "generated"
    TOOLCHAIN = "toolchain"
    SCHEMA = "schema"
    COMPILER = "compiler"
    OPAQUE = "opaque"
    FALLBACK = "fallback"
    ISI_PRESERVED = "isi_preserved"


class SemanticRemediation(str, Enum):
    """Closed remediation vocabulary for additive environment obligations."""

    STALE_BOUND_RECEIPTS = "stale_bound_receipts"
    STALE_BOUND_CAPSULES = "stale_bound_capsules"
    RERUN_TEST = "rerun_test"
    RERUN_PROOF = "rerun_proof"
    REVIEW_POLICY = "review_policy"
    REVIEW_ADAPTER = "review_adapter"
    REBUILD_GENERATED = "rebuild_generated"
    REBUILD_BOUND_ARTIFACTS = "rebuild_bound_artifacts"
    RETRIEVE_RAW_SOURCE = "retrieve_raw_source"
    FULL_PYTEST_FALLBACK = "full_pytest_fallback"
    FULL_PROOFS_FALLBACK = "full_proofs_fallback"
    FULL_FALLBACK = "full_fallback"


MAX_SEMANTIC_INVALIDATION_OBLIGATIONS: Final[int] = 2_000

_CONFIDENCE_RANK: Final[dict[str, int]] = {
    "exact": 0,
    "conservative": 1,
    "heuristic": 2,
    "opaque": 3,
}

_TEST_RELATIONS: Final[frozenset[str]] = frozenset(
    {
        RelationType.TESTED_BY.value,
        RelationType.USES_FIXTURE.value,
        RelationType.CONFIGURED_BY.value,
    }
)
_PROOF_RELATION: Final[str] = RelationType.PROOF_DEPENDS_ON.value
_ADAPTER_RELATIONS: Final[frozenset[str]] = frozenset(
    {
        RelationType.SERIALIZES.value,
        RelationType.DESERIALIZES.value,
        RelationType.VALIDATES.value,
        RelationType.IMPLEMENTS.value,
    }
)
_GENERATED_RELATION: Final[str] = RelationType.GENERATED_FROM.value

_KIND_REASON: Final[Mapping[str, str]] = {
    BindingKind.DEPENDENCY_LOCK.value: SemanticInvalidationReason.DEPENDENCY_LOCK_CHANGED.value,
    BindingKind.DEPENDENCY_MANIFEST.value: SemanticInvalidationReason.DEPENDENCY_MANIFEST_CHANGED.value,
    BindingKind.PYTEST_CONFIG.value: SemanticInvalidationReason.PYTEST_CONFIG_CHANGED.value,
    BindingKind.PYTEST_PLUGIN.value: SemanticInvalidationReason.PYTEST_PLUGIN_CHANGED.value,
    BindingKind.PROOF_CONFIG.value: SemanticInvalidationReason.PROOF_CONFIG_CHANGED.value,
    BindingKind.POLICY.value: SemanticInvalidationReason.POLICY_CHANGED.value,
    BindingKind.INTERFACE_DESCRIPTOR.value: SemanticInvalidationReason.INTERFACE_DESCRIPTOR_CHANGED.value,
    BindingKind.GENERATED_INPUT.value: SemanticInvalidationReason.GENERATED_INPUT_CHANGED.value,
    BindingKind.PYTHON_TOOLCHAIN.value: SemanticInvalidationReason.PYTHON_TOOLCHAIN_CHANGED.value,
    BindingKind.SEMANTIC_SCHEMA.value: SemanticInvalidationReason.SEMANTIC_SCHEMA_CHANGED.value,
    BindingKind.SEMANTIC_COMPILER.value: SemanticInvalidationReason.SEMANTIC_COMPILER_CHANGED.value,
}

_KIND_RULE: Final[Mapping[str, str]] = {
    BindingKind.DEPENDENCY_LOCK.value: SemanticInvalidationRule.DEPENDENCY.value,
    BindingKind.DEPENDENCY_MANIFEST.value: SemanticInvalidationRule.DEPENDENCY.value,
    BindingKind.PYTEST_CONFIG.value: SemanticInvalidationRule.PYTEST_CONFIG.value,
    BindingKind.PYTEST_PLUGIN.value: SemanticInvalidationRule.PYTEST_CONFIG.value,
    BindingKind.PROOF_CONFIG.value: SemanticInvalidationRule.PROOF_CONFIG.value,
    BindingKind.POLICY.value: SemanticInvalidationRule.POLICY.value,
    BindingKind.INTERFACE_DESCRIPTOR.value: SemanticInvalidationRule.INTERFACE.value,
    BindingKind.GENERATED_INPUT.value: SemanticInvalidationRule.GENERATED.value,
    BindingKind.PYTHON_TOOLCHAIN.value: SemanticInvalidationRule.TOOLCHAIN.value,
    BindingKind.SEMANTIC_SCHEMA.value: SemanticInvalidationRule.SCHEMA.value,
    BindingKind.SEMANTIC_COMPILER.value: SemanticInvalidationRule.COMPILER.value,
}

_KIND_REMEDIATION: Final[Mapping[str, str]] = {
    BindingKind.DEPENDENCY_LOCK.value: SemanticRemediation.STALE_BOUND_RECEIPTS.value,
    BindingKind.DEPENDENCY_MANIFEST.value: SemanticRemediation.STALE_BOUND_RECEIPTS.value,
    BindingKind.PYTEST_CONFIG.value: SemanticRemediation.RERUN_TEST.value,
    BindingKind.PYTEST_PLUGIN.value: SemanticRemediation.FULL_PYTEST_FALLBACK.value,
    BindingKind.PROOF_CONFIG.value: SemanticRemediation.RERUN_PROOF.value,
    BindingKind.POLICY.value: SemanticRemediation.REVIEW_POLICY.value,
    BindingKind.INTERFACE_DESCRIPTOR.value: SemanticRemediation.REVIEW_ADAPTER.value,
    BindingKind.GENERATED_INPUT.value: SemanticRemediation.REBUILD_GENERATED.value,
    BindingKind.PYTHON_TOOLCHAIN.value: SemanticRemediation.REBUILD_BOUND_ARTIFACTS.value,
    BindingKind.SEMANTIC_SCHEMA.value: SemanticRemediation.REBUILD_BOUND_ARTIFACTS.value,
    BindingKind.SEMANTIC_COMPILER.value: SemanticRemediation.REBUILD_BOUND_ARTIFACTS.value,
}


@runtime_checkable
class SemanticIndexForCapsules(Protocol):
    """Minimal ISI view required by :func:`extend_semantic_invalidation`."""

    @property
    def state_cid(self) -> str: ...

    @property
    def symbols(self) -> Sequence[SymbolRecord]: ...

    @property
    def artifacts(self) -> Sequence: ...

    @property
    def edges(self) -> Sequence[DependencyEdge]: ...

    @property
    def repository_id(self) -> str: ...


@runtime_checkable
class SemanticStateView(Protocol):
    """Read-only verified semantic-state view used for binding retrieval."""

    @property
    def root(self) -> SemanticStateRoot: ...

    def get_block(self, cid: str) -> bytes: ...


def _least_confident(*values: str) -> str:
    return max(values, key=lambda value: _CONFIDENCE_RANK.get(value, 3))


def _as_repository_state(index: object, name: str) -> RepositoryState:
    if isinstance(index, RepositoryState):
        return index
    # Duck-typed SemanticIndexForCapsules → materialize a RepositoryState.
    try:
        return RepositoryState(
            repository_id=index.repository_id,  # type: ignore[attr-defined]
            symbols=tuple(index.symbols),  # type: ignore[attr-defined]
            artifacts=tuple(index.artifacts),  # type: ignore[attr-defined]
            edges=tuple(index.edges),  # type: ignore[attr-defined]
        )
    except Exception as exc:
        raise SemanticInvalidationError(
            f"{name} must be a RepositoryState or SemanticIndexForCapsules"
        ) from exc


def _is_test(symbol: SymbolRecord | None) -> bool:
    return symbol is not None and str(symbol.kind) == SymbolKind.TEST.value


def load_environment_binding_set(
    view: SemanticStateView,
    *,
    fallback: EnvironmentBindingSet | None = None,
) -> EnvironmentBindingSet:
    """Load and reverify the environment binding set bound by ``view.root``."""
    if not hasattr(view, "root") or not hasattr(view, "get_block"):
        raise SemanticInvalidationError("view must provide root and get_block")
    root = view.root
    if not isinstance(root, SemanticStateRoot):
        raise SemanticInvalidationError("view.root must be a SemanticStateRoot")
    cid = root.environment_binding_set_cid
    try:
        data = view.get_block(cid)
    except Exception as exc:
        if fallback is not None:
            if fallback.binding_set_cid != cid:
                raise SemanticInvalidationError(
                    "fallback binding set CID does not match root"
                ) from exc
            return fallback
        raise SemanticInvalidationError(
            f"missing environment binding set block {cid}"
        ) from exc
    if type(data) is not bytes:
        raise SemanticInvalidationError("binding set block must be bytes")
    try:
        obj = json.loads(data.decode("utf-8"))
        if not isinstance(obj, dict):
            raise SemanticInvalidationError(
                f"binding set block {cid} must be a JSON object"
            )
        # Root binds the identity-payload CID (without binding_set_cid).
        # Accept either the identity payload or a full to_dict document.
        if "binding_set_cid" in obj:
            result = EnvironmentBindingSet.from_dict(obj)
        else:
            if obj.get("schema") != ENVIRONMENT_BINDING_SET_SCHEMA:
                raise SemanticInvalidationError(
                    "unsupported EnvironmentBindingSet schema version"
                )
            if canonical_dag_json_bytes(obj) != data:
                raise SemanticInvalidationError(
                    f"binding set block {cid} is not canonical"
                )
            decode_and_recompute_structured(cid, obj)
            bindings = tuple(
                EnvironmentBinding.from_dict(item)
                for item in obj.get("bindings", ())
            )
            result = EnvironmentBindingSet(bindings=bindings)
        if result.binding_set_cid != cid:
            raise SemanticInvalidationError(
                f"environment binding set CID does not verify for {cid}"
            )
        # Always reverify the identity payload against the root-bound CID.
        decode_and_recompute_structured(cid, result.identity_payload())
        return result
    except SemanticInvalidationError:
        raise
    except Exception as exc:
        raise SemanticInvalidationError(
            f"forged or malformed environment binding set {cid}"
        ) from exc


def _isi_to_semantic(obligation: InvalidationObligation) -> SemanticInvalidationObligation:
    details = dict(obligation.details) if obligation.details else {}
    details.setdefault("rule", SemanticInvalidationRule.ISI_PRESERVED.value)
    return SemanticInvalidationObligation(
        subject_id=obligation.subject_id,
        reason_code=obligation.reason_code,
        remediation_kind=obligation.remediation_kind,
        confidence=obligation.confidence,
        origin=ObligationOrigin.ISI,
        old_identity=obligation.old_identity,
        new_identity=obligation.new_identity,
        supporting_edge_ids=obligation.supporting_edge_ids,
        supporting_link_cids=(),
        details=details,
    )


def _reason_for_kind(kind: str) -> str:
    return _KIND_REASON.get(kind, SemanticInvalidationReason.ENVIRONMENT_BINDING_CHANGED.value)


def _rule_for_kind(kind: str) -> str:
    return _KIND_RULE.get(kind, SemanticInvalidationRule.DEPENDENCY.value)


def _remediation_for_kind(kind: str) -> str:
    return _KIND_REMEDIATION.get(
        kind, SemanticRemediation.STALE_BOUND_RECEIPTS.value
    )


def _scope_requires_fallback(binding: EnvironmentBinding) -> bool:
    scope = str(binding.scope)
    if scope == BindingScope.UNKNOWN.value:
        return True
    if scope in {
        BindingScope.SYMBOL.value,
        BindingScope.MODULE.value,
        BindingScope.PACKAGE.value,
    } and binding.subject_id is None:
        return True
    if str(binding.kind) == BindingKind.PYTEST_PLUGIN.value:
        # Uncontrolled plugins force full pytest fallback.
        return True
    if str(binding.confidence) in {
        AnalysisConfidence.OPAQUE.value,
        AnalysisConfidence.HEURISTIC.value,
    }:
        return True
    return False


def _fallback_remediation(binding: EnvironmentBinding) -> str:
    kind = str(binding.kind)
    if kind in {
        BindingKind.PROOF_CONFIG.value,
        BindingKind.SEMANTIC_SCHEMA.value,
        BindingKind.SEMANTIC_COMPILER.value,
    }:
        return SemanticRemediation.FULL_PROOFS_FALLBACK.value
    if kind in {
        BindingKind.PYTEST_CONFIG.value,
        BindingKind.PYTEST_PLUGIN.value,
        BindingKind.DEPENDENCY_LOCK.value,
        BindingKind.DEPENDENCY_MANIFEST.value,
        BindingKind.PYTHON_TOOLCHAIN.value,
    }:
        return SemanticRemediation.FULL_PYTEST_FALLBACK.value
    if kind in {
        BindingKind.POLICY.value,
        BindingKind.INTERFACE_DESCRIPTOR.value,
        BindingKind.GENERATED_INPUT.value,
    }:
        return SemanticRemediation.FULL_FALLBACK.value
    return SemanticRemediation.FULL_FALLBACK.value


def _test_subjects_for_edge(
    edge: DependencyEdge,
    changed_id: str,
    symbols: Mapping[str, SymbolRecord],
) -> list[str]:
    """Return only the test/receipt side of a test-related relation."""
    subjects: list[str] = []
    if edge.relation == RelationType.TESTED_BY.value:
        if edge.source_id == changed_id:
            subjects.append(edge.target_id)
    elif edge.relation == RelationType.USES_FIXTURE.value:
        if edge.target_id == changed_id:
            subjects.append(edge.source_id)
        elif edge.source_id == changed_id and _is_test(symbols.get(edge.source_id)):
            subjects.append(edge.source_id)
    elif edge.relation == RelationType.CONFIGURED_BY.value:
        if edge.target_id == changed_id:
            subjects.append(edge.source_id)
        elif edge.source_id == changed_id and _is_test(symbols.get(edge.source_id)):
            subjects.append(edge.source_id)
    else:
        candidate = edge.source_id if edge.target_id == changed_id else edge.target_id
        if _is_test(symbols.get(candidate)):
            subjects.append(candidate)
    return subjects


def extend_semantic_invalidation(
    previous_index: RepositoryState | SemanticIndexForCapsules,
    current_index: RepositoryState | SemanticIndexForCapsules,
    delta: RepositoryStateDelta,
    plan: InvalidationPlan,
    previous_state: SemanticStateView,
    current_state: SemanticStateView,
    *,
    previous_bindings: EnvironmentBindingSet | None = None,
    current_bindings: EnvironmentBindingSet | None = None,
    max_obligations: int = MAX_SEMANTIC_INVALIDATION_OBLIGATIONS,
) -> SemanticInvalidationPlan:
    """Preserve ISI obligations and append environment-binding obligations.

    Parameters
    ----------
    previous_index, current_index:
        Final ISI repository states (or duck-typed index views).
    delta:
        Exact recomputed :class:`RepositoryStateDelta` for the two indexes.
    plan:
        Exact recomputed ISI :class:`InvalidationPlan` for that delta.
    previous_state, current_state:
        Semantic-state views whose roots bind environment binding set CIDs.
    previous_bindings, current_bindings:
        Optional already-loaded sets used when the view block store is sparse
        (tests and cold-path callers).  CIDs must still match the roots.
    """
    previous = _as_repository_state(previous_index, "previous_index")
    current = _as_repository_state(current_index, "current_index")
    if not isinstance(delta, RepositoryStateDelta):
        raise SemanticInvalidationError("delta must be a RepositoryStateDelta")
    if not isinstance(plan, InvalidationPlan):
        raise SemanticInvalidationError("plan must be an InvalidationPlan")
    if previous.repository_id != current.repository_id:
        raise SemanticInvalidationError(
            "repository indexes must have the same repository_id"
        )
    if (delta.previous_state_cid, delta.current_state_cid) != (
        previous.state_cid,
        current.state_cid,
    ):
        raise SemanticInvalidationError(
            "delta state CIDs must match the supplied indexes"
        )
    if type(max_obligations) is not int or not 1 <= max_obligations <= MAX_SEMANTIC_INVALIDATION_OBLIGATIONS:
        raise SemanticInvalidationError(
            f"max_obligations must be between 1 and {MAX_SEMANTIC_INVALIDATION_OBLIGATIONS}"
        )

    # Recompute and reject fabricated deltas/plans fail-closed.
    expected_delta = diff_repository_states(previous, current)
    if delta.delta_cid != expected_delta.delta_cid:
        raise SemanticInvalidationError(
            "fabricated or incomplete delta rejected; recompute from the two indexes"
        )
    expected_plan = calculate_invalidation(previous, current, expected_delta)
    if plan.plan_cid != expected_plan.plan_cid:
        raise SemanticInvalidationError(
            "fabricated or incomplete ISI plan rejected; recompute from the two indexes"
        )

    if not hasattr(previous_state, "root") or not hasattr(current_state, "root"):
        raise SemanticInvalidationError(
            "previous_state and current_state must be SemanticStateView values"
        )
    previous_root = previous_state.root
    current_root = current_state.root
    if not isinstance(previous_root, SemanticStateRoot) or not isinstance(
        current_root, SemanticStateRoot
    ):
        raise SemanticInvalidationError("state roots must be SemanticStateRoot values")
    if previous_root.repository_id != current_root.repository_id:
        raise SemanticInvalidationError(
            "semantic state roots must share repository_id"
        )
    if previous_root.repository_id != previous.repository_id:
        raise SemanticInvalidationError(
            "semantic state repository_id must match ISI indexes"
        )

    prev_bindings = load_environment_binding_set(
        previous_state, fallback=previous_bindings
    )
    curr_bindings = load_environment_binding_set(
        current_state, fallback=current_bindings
    )
    if previous_bindings is not None and previous_bindings.binding_set_cid != prev_bindings.binding_set_cid:
        raise SemanticInvalidationError(
            "previous_bindings CID does not match loaded set"
        )
    if current_bindings is not None and current_bindings.binding_set_cid != curr_bindings.binding_set_cid:
        raise SemanticInvalidationError(
            "current_bindings CID does not match loaded set"
        )

    binding_delta = diff_environment_bindings(prev_bindings, curr_bindings)
    prev_by_id = bindings_by_id(prev_bindings)
    curr_by_id = bindings_by_id(curr_bindings)

    # Union of symbols from both indexes so deletion evidence is retained.
    symbols: dict[str, SymbolRecord] = {
        item.stable_id: item for item in previous.symbols
    }
    symbols.update({item.stable_id: item for item in current.symbols})
    symbol_list = tuple(symbols.values())

    edges_by_id: dict[str, DependencyEdge] = {}
    adjacent: dict[str, list[DependencyEdge]] = {}
    for edge in (*previous.edges, *current.edges):
        edges_by_id[edge.edge_id] = edge
        adjacent.setdefault(edge.source_id, []).append(edge)
        adjacent.setdefault(edge.target_id, []).append(edge)

    obligations: dict[str, SemanticInvalidationObligation] = {}

    def emit(obligation: SemanticInvalidationObligation) -> None:
        obligations[obligation.obligation_id] = obligation

    # 1) Preserve every ISI obligation with origin=isi.
    for item in plan.obligations:
        emit(_isi_to_semantic(item))

    def emit_env(
        subject_id: str,
        reason: str,
        remediation: str,
        confidence: str,
        *,
        old_identity: str | None,
        new_identity: str | None,
        edges: Iterable[DependencyEdge] = (),
        details: Mapping[str, object] | None = None,
    ) -> None:
        edge_items = tuple(
            sorted(
                {edge.edge_id: edge for edge in edges}.values(),
                key=lambda edge: edge.edge_id,
            )
        )
        conf = confidence
        if edge_items:
            conf = _least_confident(conf, *(str(edge.confidence) for edge in edge_items))
        payload_details = dict(details or {})
        emit(
            SemanticInvalidationObligation(
                subject_id=subject_id,
                reason_code=reason,
                remediation_kind=remediation,
                confidence=conf,
                origin=ObligationOrigin.ENVIRONMENT,
                old_identity=old_identity,
                new_identity=new_identity,
                supporting_edge_ids=tuple(edge.edge_id for edge in edge_items),
                supporting_link_cids=(),
                details=payload_details,
            )
        )

    def emit_bound_derivatives(
        binding: EnvironmentBinding,
        *,
        old_identity: str | None,
        new_identity: str | None,
        # Projection set used to decide membership (current for added/modified,
        # previous for deleted).
        membership_set: EnvironmentBindingSet,
        # Symbols considered for membership (current∪previous).
        candidates: Sequence[SymbolRecord],
    ) -> set[str]:
        """Stale every known bound derivative; return affected symbol IDs."""
        kind = str(binding.kind)
        reason = _reason_for_kind(kind)
        rule = _rule_for_kind(kind)
        base_remediation = _remediation_for_kind(kind)
        confidence = str(binding.confidence)
        affected = set(
            iter_affected_symbol_ids(binding, membership_set, candidates)
        )

        # Also mark the binding itself so receipts keyed by binding_id surface.
        emit_env(
            binding.binding_id,
            reason,
            base_remediation,
            confidence,
            old_identity=old_identity,
            new_identity=new_identity,
            details={
                "rule": rule,
                "binding_id": binding.binding_id,
                "binding_kind": kind,
                "binding_scope": str(binding.scope),
            },
        )

        for symbol_id in sorted(affected):
            emit_env(
                symbol_id,
                SemanticInvalidationReason.STALE_BOUND_CAPSULE.value,
                SemanticRemediation.STALE_BOUND_CAPSULES.value,
                confidence,
                old_identity=old_identity,
                new_identity=new_identity,
                details={
                    "rule": rule,
                    "trigger_binding_id": binding.binding_id,
                    "binding_kind": kind,
                    "reason": reason,
                },
            )
            # Relation-specific derivative walk (tests, proofs, adapters,
            # generated artifacts) — never invent IDs without edges.
            for edge in adjacent.get(symbol_id, ()):
                if edge.relation in _TEST_RELATIONS:
                    for subject in _test_subjects_for_edge(edge, symbol_id, symbols):
                        emit_env(
                            subject,
                            SemanticInvalidationReason.STALE_BOUND_RECEIPT.value,
                            SemanticRemediation.RERUN_TEST.value,
                            edge.confidence,
                            old_identity=old_identity,
                            new_identity=new_identity,
                            edges=(edge,),
                            details={
                                "rule": rule,
                                "trigger_binding_id": binding.binding_id,
                                "trigger_symbol_id": symbol_id,
                            },
                        )
                elif edge.relation == _PROOF_RELATION:
                    # proof (source) depends on subject (target).
                    if edge.target_id == symbol_id:
                        proof_id = edge.source_id
                    elif edge.source_id == symbol_id:
                        proof_id = edge.source_id
                    else:
                        continue
                    emit_env(
                        proof_id,
                        SemanticInvalidationReason.PROOF_RERUN.value,
                        SemanticRemediation.RERUN_PROOF.value,
                        edge.confidence,
                        old_identity=old_identity,
                        new_identity=new_identity,
                        edges=(edge,),
                        details={
                            "rule": rule,
                            "trigger_binding_id": binding.binding_id,
                            "trigger_symbol_id": symbol_id,
                        },
                    )
                elif edge.relation in _ADAPTER_RELATIONS:
                    adapter = (
                        edge.source_id
                        if edge.target_id == symbol_id
                        else edge.target_id
                    )
                    if adapter == symbol_id:
                        continue
                    emit_env(
                        adapter,
                        SemanticInvalidationReason.OBSOLETE_SCHEMA_ADAPTER.value,
                        SemanticRemediation.REVIEW_ADAPTER.value,
                        edge.confidence,
                        old_identity=old_identity,
                        new_identity=new_identity,
                        edges=(edge,),
                        details={
                            "rule": rule,
                            "trigger_binding_id": binding.binding_id,
                            "trigger_symbol_id": symbol_id,
                        },
                    )
                elif edge.relation == _GENERATED_RELATION:
                    # generated_from: generated artifact/symbol (source) ← input.
                    if edge.target_id != symbol_id and edge.source_id != symbol_id:
                        continue
                    emit_env(
                        edge.source_id,
                        SemanticInvalidationReason.GENERATED_INPUT_CHANGED.value,
                        SemanticRemediation.REBUILD_GENERATED.value,
                        edge.confidence,
                        old_identity=old_identity,
                        new_identity=new_identity,
                        edges=(edge,),
                        details={
                            "rule": SemanticInvalidationRule.GENERATED.value,
                            "trigger_binding_id": binding.binding_id,
                            "trigger_symbol_id": symbol_id,
                        },
                    )

            if confidence == AnalysisConfidence.OPAQUE.value:
                emit_env(
                    symbol_id,
                    SemanticInvalidationReason.RAW_SOURCE_REQUIRED.value,
                    SemanticRemediation.RETRIEVE_RAW_SOURCE.value,
                    AnalysisConfidence.OPAQUE.value,
                    old_identity=old_identity,
                    new_identity=new_identity,
                    details={
                        "rule": SemanticInvalidationRule.OPAQUE.value,
                        "trigger_binding_id": binding.binding_id,
                    },
                )

        return affected

    def emit_fallback(binding: EnvironmentBinding, *, old_identity: str | None, new_identity: str | None) -> None:
        kind = str(binding.kind)
        scope = str(binding.scope)
        if scope == BindingScope.UNKNOWN.value:
            reason = SemanticInvalidationReason.UNKNOWN_BINDING_SCOPE.value
        elif binding.subject_id is None and scope != BindingScope.GLOBAL.value:
            reason = SemanticInvalidationReason.UNMAPPED_BINDING_SUBJECT.value
        elif str(binding.kind) == BindingKind.PYTEST_PLUGIN.value:
            reason = SemanticInvalidationReason.PYTEST_PLUGIN_CHANGED.value
        elif str(binding.confidence) in {
            AnalysisConfidence.OPAQUE.value,
            AnalysisConfidence.HEURISTIC.value,
        }:
            reason = SemanticInvalidationReason.FULL_FALLBACK_REQUIRED.value
        else:
            reason = SemanticInvalidationReason.FULL_FALLBACK_REQUIRED.value
        emit_env(
            binding.binding_id,
            reason,
            _fallback_remediation(binding),
            str(binding.confidence),
            old_identity=old_identity,
            new_identity=new_identity,
            details={
                "rule": SemanticInvalidationRule.FALLBACK.value,
                "binding_id": binding.binding_id,
                "binding_kind": kind,
                "binding_scope": scope,
                "fallback_reason": reason,
            },
        )

    changed_ids = changed_binding_ids(binding_delta)

    for binding_id in changed_ids:
        prev_b = prev_by_id.get(binding_id)
        curr_b = curr_by_id.get(binding_id)
        active = curr_b or prev_b
        if active is None:
            continue
        old_identity = None if prev_b is None else prev_b.version_cid
        new_identity = None if curr_b is None else curr_b.version_cid

        # Membership uses the set that still knows the binding id.
        if curr_b is not None:
            membership = curr_bindings
            membership_prev = prev_bindings
        else:
            membership = prev_bindings
            membership_prev = prev_bindings

        affected = emit_bound_derivatives(
            active,
            old_identity=old_identity,
            new_identity=new_identity,
            membership_set=membership,
            candidates=symbol_list,
        )
        if curr_b is not None and prev_b is not None:
            # Symbols that previously projected the binding but no longer do
            # (scope tightened) still need a stale obligation once.
            prev_affected = set(
                iter_affected_symbol_ids(prev_b, membership_prev, symbol_list)
            )
            for symbol_id in sorted(prev_affected - affected):
                emit_env(
                    symbol_id,
                    SemanticInvalidationReason.STALE_BOUND_CAPSULE.value,
                    SemanticRemediation.STALE_BOUND_CAPSULES.value,
                    str(prev_b.confidence),
                    old_identity=old_identity,
                    new_identity=new_identity,
                    details={
                        "rule": _rule_for_kind(str(prev_b.kind)),
                        "trigger_binding_id": binding_id,
                        "binding_kind": str(prev_b.kind),
                        "note": "previous_projection_membership",
                    },
                )
                affected.add(symbol_id)

        # Fail closed if we ever emit a bound-capsule obligation for a symbol
        # whose previous and current projections both omit this binding.
        for item in list(obligations.values()):
            if item.origin != ObligationOrigin.ENVIRONMENT.value:
                continue
            if item.details.get("trigger_binding_id") != binding_id:
                continue
            if item.reason_code != SemanticInvalidationReason.STALE_BOUND_CAPSULE.value:
                continue
            symbol = symbols.get(item.subject_id)
            if symbol is None:
                continue
            proj_curr = relevant_binding_projection_for_symbol(symbol, curr_bindings)
            proj_prev = relevant_binding_projection_for_symbol(symbol, prev_bindings)
            if (
                binding_id not in proj_curr.binding_ids
                and binding_id not in proj_prev.binding_ids
            ):
                raise SemanticInvalidationError(
                    f"environment obligation incorrectly targets known-disjoint "
                    f"subject {item.subject_id!r} for binding {binding_id!r}"
                )

        if _scope_requires_fallback(active):
            emit_fallback(
                active, old_identity=old_identity, new_identity=new_identity
            )

    ordered = tuple(sorted(obligations.values(), key=lambda item: item.obligation_id))
    if len(ordered) > max_obligations:
        raise SemanticInvalidationError(
            f"semantic invalidation plan exceeds max_obligations={max_obligations}"
        )

    return SemanticInvalidationPlan(
        previous_root_cid=previous_root.root_cid,
        current_root_cid=current_root.root_cid,
        isi_plan_cid=plan.plan_cid,
        obligations=ordered,
    )


def environment_obligations(
    plan: SemanticInvalidationPlan,
) -> tuple[SemanticInvalidationObligation, ...]:
    """Return only environment-origin obligations from a plan."""
    if not isinstance(plan, SemanticInvalidationPlan):
        raise SemanticInvalidationError("plan must be a SemanticInvalidationPlan")
    return tuple(
        item
        for item in plan.obligations
        if item.origin == ObligationOrigin.ENVIRONMENT.value
    )


def isi_obligations(
    plan: SemanticInvalidationPlan,
) -> tuple[SemanticInvalidationObligation, ...]:
    """Return only ISI-preserved obligations from a plan."""
    if not isinstance(plan, SemanticInvalidationPlan):
        raise SemanticInvalidationError("plan must be a SemanticInvalidationPlan")
    return tuple(
        item for item in plan.obligations if item.origin == ObligationOrigin.ISI.value
    )


def build_bindings_for_indexes(
    previous_index: RepositoryState | None,
    current_index: RepositoryState,
    *,
    extra_previous: Sequence[EnvironmentBinding] = (),
    extra_current: Sequence[EnvironmentBinding] = (),
) -> tuple[EnvironmentBindingSet, EnvironmentBindingSet]:
    """Convenience helper: build previous/current binding sets from indexes."""
    try:
        prev = build_environment_binding_set(
            extra_previous,
            repository_state=previous_index,
        )
        curr = build_environment_binding_set(
            extra_current,
            repository_state=current_index,
        )
    except BindingsError as exc:
        raise SemanticInvalidationError(str(exc)) from exc
    return prev, curr


__all__ = [
    "MAX_SEMANTIC_INVALIDATION_OBLIGATIONS",
    "SemanticIndexForCapsules",
    "SemanticInvalidationError",
    "SemanticInvalidationReason",
    "SemanticInvalidationRule",
    "SemanticRemediation",
    "SemanticStateView",
    "build_bindings_for_indexes",
    "environment_obligations",
    "extend_semantic_invalidation",
    "isi_obligations",
    "load_environment_binding_set",
]
