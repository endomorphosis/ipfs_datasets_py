"""Focused contract vectors for additive environment invalidation."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Mapping

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_bytes,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.delta import (
    diff_repository_states,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import (
    stable_symbol_id,
    symbol_version_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.invalidation import (
    calculate_invalidation,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    DependencyEdge,
    InvalidationPlan,
    RelationType,
    RepositoryState,
    SourceSpan,
    SymbolKind,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.bindings import (
    build_environment_binding_set,
    relevant_binding_projection_for_symbol,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.invalidation import (
    SemanticInvalidationError,
    SemanticInvalidationReason,
    SemanticRemediation,
    environment_obligations,
    extend_semantic_invalidation,
    isi_obligations,
    load_environment_binding_set,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    BindingKind,
    BindingScope,
    EnvironmentBinding,
    EnvironmentBindingSet,
    ObligationOrigin,
    SemanticStateProducer,
    SemanticStateRoot,
    SortedPairIndex,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _symbol(
    name: str,
    source: str | None = None,
    *,
    module: str = "pkg/mod.py",
    namespace: str = "pkg",
    kind: SymbolKind = SymbolKind.FUNCTION,
) -> SymbolRecord:
    source = source or f"def {name}():\n    return 1\n"
    qualified = f"{namespace}.{name}"
    stable = stable_symbol_id(
        "repo:invalidation", "python", module, qualified, kind, namespace
    )
    node = ast.parse(source).body[0]
    version = symbol_version_cid(stable, node, {}, (), {})
    return SymbolRecord(
        stable,
        version,
        "repo:invalidation",
        "python",
        module,
        qualified,
        kind,
        namespace,
        cid_for_bytes(source.encode()),
        SourceSpan(module, 1, 0, 2, 20),
        AnalysisConfidence.EXACT,
        {},
        (),
        {},
        {},
        node,
    )


def _binding(
    binding_id: str,
    kind: BindingKind,
    *,
    version: str = "v1",
    scope: BindingScope = BindingScope.GLOBAL,
    subject_id: str | None = None,
    confidence: AnalysisConfidence = AnalysisConfidence.EXACT,
) -> EnvironmentBinding:
    return EnvironmentBinding(
        binding_id=binding_id,
        kind=kind,
        version_cid=_cid(f"{binding_id}:{version}"),
        scope=scope,
        extraction_authority="test",
        confidence=confidence,
        subject_id=subject_id,
    )


def _producer() -> SemanticStateProducer:
    return SemanticStateProducer(
        repository_state_cid=_cid("state"),
        repository_snapshot_cid=_cid("snapshot"),
        git_commit_oid_or_null="a" * 40,
        git_tree_oid_or_null="b" * 40,
        source_manifest_cid=_cid("manifest"),
        semantic_index_schema="ipfs-datasets.software-contracts.semantic-index@2",
        extractor_name="python-cpython-ast",
        extractor_version="1",
    )


def _index_cid() -> str:
    return SortedPairIndex(pairs=[("k", _cid("block"))]).index_cid


@dataclass(frozen=True)
class _View:
    root: SemanticStateRoot
    blocks: Mapping[str, bytes]

    def get_block(self, cid: str) -> bytes:
        try:
            return self.blocks[cid]
        except KeyError as exc:
            raise KeyError(cid) from exc


def _view_for(binding_set: EnvironmentBindingSet) -> _View:
    root = SemanticStateRoot(
        repository_id="repo:invalidation",
        producer=_producer(),
        symbol_fact_index_cid=_index_cid(),
        artifact_fact_index_cid=_index_cid(),
        semantic_link_index_cid=_index_cid(),
        symbol_node_index_cid=_index_cid(),
        capsule_index_cid=_index_cid(),
        environment_binding_set_cid=binding_set.binding_set_cid,
        analysis_limitation_index_cid=_index_cid(),
    )
    # Store identity payload under the root-bound CID.
    blocks = {
        binding_set.binding_set_cid: canonical_dag_json_bytes(
            binding_set.identity_payload()
        )
    }
    return _View(root=root, blocks=blocks)


def _extend(
    previous: RepositoryState,
    current: RepositoryState,
    prev_bindings: EnvironmentBindingSet,
    curr_bindings: EnvironmentBindingSet,
) -> object:
    delta = diff_repository_states(previous, current)
    plan = calculate_invalidation(previous, current, delta)
    return extend_semantic_invalidation(
        previous,
        current,
        delta,
        plan,
        _view_for(prev_bindings),
        _view_for(curr_bindings),
    )


def _env_subjects(plan: object) -> set[str]:
    return {
        item.subject_id
        for item in environment_obligations(plan)  # type: ignore[arg-type]
    }


def _env_reasons(plan: object) -> set[str]:
    return {
        item.reason_code
        for item in environment_obligations(plan)  # type: ignore[arg-type]
    }


def test_load_environment_binding_set_reverifies_cid() -> None:
    binding_set = build_environment_binding_set(
        [_binding("lock:poetry", BindingKind.DEPENDENCY_LOCK)]
    )
    view = _view_for(binding_set)
    loaded = load_environment_binding_set(view)
    assert loaded == binding_set
    assert loaded.binding_set_cid == binding_set.binding_set_cid


def test_extend_preserves_isi_obligations_and_origin() -> None:
    old = _symbol("target", "def target():\n    return 1\n")
    new = _symbol("target", "def target():\n    return 2\n")
    test = _symbol(
        "test_target",
        "def test_target():\n    assert target() == 1\n",
        kind=SymbolKind.TEST,
    )
    edges = (
        DependencyEdge(
            old.stable_id,
            test.stable_id,
            RelationType.TESTED_BY,
            "static",
            "exact",
            "1",
        ),
    )
    new_edges = (
        DependencyEdge(
            new.stable_id,
            test.stable_id,
            RelationType.TESTED_BY,
            "static",
            "exact",
            "1",
        ),
    )
    previous = RepositoryState(
        "repo:invalidation", symbols=(old, test), edges=edges
    )
    current = RepositoryState(
        "repo:invalidation", symbols=(new, test), edges=new_edges
    )
    # Identical bindings — only ISI source invalidation applies.
    bindings = build_environment_binding_set(
        [_binding("toolchain:python", BindingKind.PYTHON_TOOLCHAIN)]
    )
    plan = _extend(previous, current, bindings, bindings)
    isi = isi_obligations(plan)  # type: ignore[arg-type]
    assert isi
    assert all(item.origin == ObligationOrigin.ISI.value for item in isi)
    assert plan.isi_plan_cid is not None  # type: ignore[attr-defined]
    # No environment obligations when bindings are unchanged.
    assert environment_obligations(plan) == ()  # type: ignore[arg-type]


def test_changed_package_binding_stales_bound_not_disjoint() -> None:
    symbol_a = _symbol("alpha", module="pkg_a/mod.py", namespace="pkg_a")
    symbol_b = _symbol("beta", module="pkg_b/mod.py", namespace="pkg_b")
    test_a = _symbol(
        "test_alpha",
        "def test_alpha():\n    assert alpha() == 1\n",
        module="tests/test_a.py",
        namespace="tests",
        kind=SymbolKind.TEST,
    )
    edge = DependencyEdge(
        symbol_a.stable_id,
        test_a.stable_id,
        RelationType.TESTED_BY,
        "static",
        "exact",
        "1",
    )
    previous = RepositoryState(
        "repo:invalidation",
        symbols=(symbol_a, symbol_b, test_a),
        edges=(edge,),
    )
    current = previous  # source-identical; only bindings change

    prev_bindings = build_environment_binding_set(
        [
            _binding(
                "lock:pkg_a",
                BindingKind.DEPENDENCY_LOCK,
                version="1",
                scope=BindingScope.PACKAGE,
                subject_id="pkg_a",
            ),
            _binding(
                "lock:pkg_b",
                BindingKind.DEPENDENCY_LOCK,
                version="1",
                scope=BindingScope.PACKAGE,
                subject_id="pkg_b",
            ),
        ]
    )
    curr_bindings = build_environment_binding_set(
        [
            _binding(
                "lock:pkg_a",
                BindingKind.DEPENDENCY_LOCK,
                version="2",
                scope=BindingScope.PACKAGE,
                subject_id="pkg_a",
            ),
            _binding(
                "lock:pkg_b",
                BindingKind.DEPENDENCY_LOCK,
                version="1",
                scope=BindingScope.PACKAGE,
                subject_id="pkg_b",
            ),
        ]
    )
    plan = _extend(previous, current, prev_bindings, curr_bindings)
    env = environment_obligations(plan)  # type: ignore[arg-type]
    subjects = {item.subject_id for item in env}
    assert symbol_a.stable_id in subjects
    assert "lock:pkg_a" in subjects
    # Known disjoint package B capsule must not be staled by pkg_a lock change.
    assert symbol_b.stable_id not in subjects
    # Bound test derivative via tested_by edge is staled.
    assert test_a.stable_id in subjects
    assert SemanticInvalidationReason.DEPENDENCY_LOCK_CHANGED.value in {
        item.reason_code for item in env
    }
    assert SemanticInvalidationReason.STALE_BOUND_CAPSULE.value in {
        item.reason_code for item in env
    }
    # Projection confirms disjointness independently.
    proj_b = relevant_binding_projection_for_symbol(symbol_b, curr_bindings)
    assert "lock:pkg_a" not in proj_b.binding_ids


def test_unknown_scope_emits_visible_fallback_reason() -> None:
    symbol = _symbol("unit")
    previous = RepositoryState("repo:invalidation", symbols=(symbol,))
    current = previous
    prev = build_environment_binding_set(
        [
            _binding(
                "lock:unknown",
                BindingKind.DEPENDENCY_LOCK,
                version="1",
                scope=BindingScope.UNKNOWN,
            )
        ]
    )
    curr = build_environment_binding_set(
        [
            _binding(
                "lock:unknown",
                BindingKind.DEPENDENCY_LOCK,
                version="2",
                scope=BindingScope.UNKNOWN,
            )
        ]
    )
    plan = _extend(previous, current, prev, curr)
    env = environment_obligations(plan)  # type: ignore[arg-type]
    reasons = {item.reason_code for item in env}
    remediations = {item.remediation_kind for item in env}
    assert SemanticInvalidationReason.UNKNOWN_BINDING_SCOPE.value in reasons
    assert SemanticRemediation.FULL_PYTEST_FALLBACK.value in remediations
    # Conservative: the symbol is also staled.
    assert symbol.stable_id in {item.subject_id for item in env}


def test_pytest_plugin_change_forces_full_pytest_fallback() -> None:
    symbol = _symbol("unit")
    previous = RepositoryState("repo:invalidation", symbols=(symbol,))
    current = previous
    prev = build_environment_binding_set(
        [
            _binding(
                "plugin:xdist",
                BindingKind.PYTEST_PLUGIN,
                version="1",
                scope=BindingScope.GLOBAL,
            )
        ]
    )
    curr = build_environment_binding_set(
        [
            _binding(
                "plugin:xdist",
                BindingKind.PYTEST_PLUGIN,
                version="2",
                scope=BindingScope.GLOBAL,
            )
        ]
    )
    plan = _extend(previous, current, prev, curr)
    remediations = {
        item.remediation_kind for item in environment_obligations(plan)  # type: ignore[arg-type]
    }
    assert SemanticRemediation.FULL_PYTEST_FALLBACK.value in remediations


def test_policy_interface_generated_toolchain_rules() -> None:
    symbol = _symbol("svc", module="svc/api.py", namespace="svc")
    previous = RepositoryState("repo:invalidation", symbols=(symbol,))
    current = previous

    cases = [
        (
            BindingKind.POLICY,
            BindingScope.SYMBOL,
            symbol.stable_id,
            SemanticInvalidationReason.POLICY_CHANGED.value,
            SemanticRemediation.REVIEW_POLICY.value,
        ),
        (
            BindingKind.INTERFACE_DESCRIPTOR,
            BindingScope.MODULE,
            "svc/api.py",
            SemanticInvalidationReason.INTERFACE_DESCRIPTOR_CHANGED.value,
            SemanticRemediation.REVIEW_ADAPTER.value,
        ),
        (
            BindingKind.GENERATED_INPUT,
            BindingScope.PACKAGE,
            "svc",
            SemanticInvalidationReason.GENERATED_INPUT_CHANGED.value,
            SemanticRemediation.REBUILD_GENERATED.value,
        ),
        (
            BindingKind.PYTHON_TOOLCHAIN,
            BindingScope.GLOBAL,
            None,
            SemanticInvalidationReason.PYTHON_TOOLCHAIN_CHANGED.value,
            SemanticRemediation.REBUILD_BOUND_ARTIFACTS.value,
        ),
        (
            BindingKind.SEMANTIC_SCHEMA,
            BindingScope.GLOBAL,
            None,
            SemanticInvalidationReason.SEMANTIC_SCHEMA_CHANGED.value,
            SemanticRemediation.REBUILD_BOUND_ARTIFACTS.value,
        ),
        (
            BindingKind.SEMANTIC_COMPILER,
            BindingScope.GLOBAL,
            None,
            SemanticInvalidationReason.SEMANTIC_COMPILER_CHANGED.value,
            SemanticRemediation.REBUILD_BOUND_ARTIFACTS.value,
        ),
        (
            BindingKind.PROOF_CONFIG,
            BindingScope.GLOBAL,
            None,
            SemanticInvalidationReason.PROOF_CONFIG_CHANGED.value,
            SemanticRemediation.RERUN_PROOF.value,
        ),
        (
            BindingKind.PYTEST_CONFIG,
            BindingScope.GLOBAL,
            None,
            SemanticInvalidationReason.PYTEST_CONFIG_CHANGED.value,
            SemanticRemediation.RERUN_TEST.value,
        ),
    ]
    for kind, scope, subject, reason, remediation in cases:
        prev = build_environment_binding_set(
            [
                _binding(
                    f"b:{kind.value}",
                    kind,
                    version="1",
                    scope=scope,
                    subject_id=subject,
                )
            ]
        )
        curr = build_environment_binding_set(
            [
                _binding(
                    f"b:{kind.value}",
                    kind,
                    version="2",
                    scope=scope,
                    subject_id=subject,
                )
            ]
        )
        plan = _extend(previous, current, prev, curr)
        reasons = _env_reasons(plan)
        remediations = {
            item.remediation_kind
            for item in environment_obligations(plan)  # type: ignore[arg-type]
        }
        assert reason in reasons, kind
        assert remediation in remediations, kind
        assert symbol.stable_id in _env_subjects(plan)


def test_opaque_binding_requires_raw_source() -> None:
    symbol = _symbol("opaque_target")
    previous = RepositoryState("repo:invalidation", symbols=(symbol,))
    current = previous
    prev = build_environment_binding_set(
        [
            _binding(
                "lock:opaque",
                BindingKind.DEPENDENCY_LOCK,
                version="1",
                scope=BindingScope.GLOBAL,
                confidence=AnalysisConfidence.OPAQUE,
            )
        ]
    )
    curr = build_environment_binding_set(
        [
            _binding(
                "lock:opaque",
                BindingKind.DEPENDENCY_LOCK,
                version="2",
                scope=BindingScope.GLOBAL,
                confidence=AnalysisConfidence.OPAQUE,
            )
        ]
    )
    plan = _extend(previous, current, prev, curr)
    reasons = _env_reasons(plan)
    assert SemanticInvalidationReason.RAW_SOURCE_REQUIRED.value in reasons
    assert SemanticInvalidationReason.FULL_FALLBACK_REQUIRED.value in reasons or (
        SemanticRemediation.FULL_PYTEST_FALLBACK.value
        in {
            item.remediation_kind
            for item in environment_obligations(plan)  # type: ignore[arg-type]
        }
    )


def test_fabricated_isi_plan_is_rejected() -> None:
    old = _symbol("t", "def t():\n return 1\n")
    new = _symbol("t", "def t():\n return 2\n")
    previous = RepositoryState("repo:invalidation", symbols=(old,))
    current = RepositoryState("repo:invalidation", symbols=(new,))
    delta = diff_repository_states(previous, current)
    real_plan = calculate_invalidation(previous, current, delta)
    assert real_plan.obligations
    forged = InvalidationPlan(
        previous_state_cid=previous.state_cid,
        current_state_cid=current.state_cid,
        obligations=(),
    )
    bindings = build_environment_binding_set([])
    with pytest.raises(SemanticInvalidationError, match="ISI plan"):
        extend_semantic_invalidation(
            previous,
            current,
            delta,
            forged,
            _view_for(bindings),
            _view_for(bindings),
        )


def test_fabricated_delta_is_rejected() -> None:
    old = _symbol("t", "def t():\n return 1\n")
    new = _symbol("t", "def t():\n return 2\n")
    previous = RepositoryState("repo:invalidation", symbols=(old,))
    current = RepositoryState("repo:invalidation", symbols=(new,))
    real_delta = diff_repository_states(previous, current)
    plan = calculate_invalidation(previous, current, real_delta)
    # Fabricate by claiming no modified symbols while CIDs match states.
    from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
        RepositoryStateDelta,
    )

    forged_delta = RepositoryStateDelta(
        previous_state_cid=previous.state_cid,
        current_state_cid=current.state_cid,
        modified_symbol_ids=(),
        unchanged_symbol_ids=(old.stable_id,),
    )
    bindings = build_environment_binding_set([])
    with pytest.raises(SemanticInvalidationError, match="delta"):
        extend_semantic_invalidation(
            previous,
            current,
            forged_delta,
            plan,
            _view_for(bindings),
            _view_for(bindings),
        )


def test_proof_edge_bound_derivative_is_staled() -> None:
    target = _symbol("proved")
    proof = _symbol("proof_of_proved", "def proof_of_proved():\n pass\n")
    edge = DependencyEdge(
        proof.stable_id,
        target.stable_id,
        RelationType.PROOF_DEPENDS_ON,
        "static",
        "exact",
        "1",
    )
    state = RepositoryState(
        "repo:invalidation", symbols=(target, proof), edges=(edge,)
    )
    prev = build_environment_binding_set(
        [
            _binding(
                "schema:v",
                BindingKind.SEMANTIC_SCHEMA,
                version="1",
                scope=BindingScope.GLOBAL,
            )
        ]
    )
    curr = build_environment_binding_set(
        [
            _binding(
                "schema:v",
                BindingKind.SEMANTIC_SCHEMA,
                version="2",
                scope=BindingScope.GLOBAL,
            )
        ]
    )
    plan = _extend(state, state, prev, curr)
    subjects = _env_subjects(plan)
    assert proof.stable_id in subjects
    reasons = _env_reasons(plan)
    assert SemanticInvalidationReason.PROOF_RERUN.value in reasons


def test_plan_is_deterministic_and_sorted() -> None:
    symbol = _symbol("det")
    state = RepositoryState("repo:invalidation", symbols=(symbol,))
    prev = build_environment_binding_set(
        [
            _binding("a:lock", BindingKind.DEPENDENCY_LOCK, version="1"),
            _binding("b:policy", BindingKind.POLICY, version="1"),
        ]
    )
    curr = build_environment_binding_set(
        [
            _binding("a:lock", BindingKind.DEPENDENCY_LOCK, version="2"),
            _binding("b:policy", BindingKind.POLICY, version="2"),
        ]
    )
    plan1 = _extend(state, state, prev, curr)
    plan2 = _extend(state, state, prev, curr)
    assert plan1.plan_cid == plan2.plan_cid  # type: ignore[attr-defined]
    ids = [item.obligation_id for item in plan1.obligations]  # type: ignore[attr-defined]
    assert ids == sorted(ids)


def test_deleted_binding_stales_previous_members_only() -> None:
    symbol_a = _symbol("alpha", module="pkg_a/mod.py", namespace="pkg_a")
    symbol_b = _symbol("beta", module="pkg_b/mod.py", namespace="pkg_b")
    state = RepositoryState(
        "repo:invalidation", symbols=(symbol_a, symbol_b)
    )
    prev = build_environment_binding_set(
        [
            _binding(
                "lock:pkg_a",
                BindingKind.DEPENDENCY_LOCK,
                version="1",
                scope=BindingScope.PACKAGE,
                subject_id="pkg_a",
            )
        ]
    )
    curr = build_environment_binding_set([])
    plan = _extend(state, state, prev, curr)
    subjects = _env_subjects(plan)
    assert symbol_a.stable_id in subjects
    assert symbol_b.stable_id not in subjects
    assert "lock:pkg_a" in subjects
