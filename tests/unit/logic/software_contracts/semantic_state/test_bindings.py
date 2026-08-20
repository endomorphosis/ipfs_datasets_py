"""Focused contract vectors for environment binding set / projection / delta."""

from __future__ import annotations

import ast

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import (
    stable_symbol_id,
    symbol_version_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    ArtifactRecord,
    RepositoryState,
    SourceSpan,
    SymbolKind,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.bindings import (
    BindingsError,
    binding_applies_to_symbol,
    build_environment_binding_set,
    changed_binding_ids,
    diff_environment_bindings,
    iter_affected_symbol_ids,
    relevant_binding_projection,
    relevant_binding_projection_for_symbol,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    BindingKind,
    BindingScope,
    EnvironmentBinding,
    EnvironmentBindingSet,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _symbol(
    name: str,
    *,
    module: str = "pkg/mod.py",
    namespace: str = "pkg",
    kind: SymbolKind = SymbolKind.FUNCTION,
) -> SymbolRecord:
    qualified = f"{namespace}.{name}"
    stable = stable_symbol_id(
        "repo:bindings", "python", module, qualified, kind, namespace
    )
    source = f"def {name}():\n    return 1\n"
    node = ast.parse(source).body[0]
    version = symbol_version_cid(stable, node, {}, (), {})
    return SymbolRecord(
        stable,
        version,
        "repo:bindings",
        "python",
        module,
        qualified,
        kind,
        namespace,
        cid_for_bytes(source.encode()),
        SourceSpan(module, 1, 0, 2, 12),
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


def test_build_environment_binding_set_sorts_and_deduplicates_by_id() -> None:
    a = _binding("lock:poetry", BindingKind.DEPENDENCY_LOCK, version="a")
    b = _binding("policy:sec", BindingKind.POLICY, version="b")
    a2 = _binding("lock:poetry", BindingKind.DEPENDENCY_LOCK, version="a2")
    built = build_environment_binding_set([b, a, a2])
    assert [item.binding_id for item in built.bindings] == ["lock:poetry", "policy:sec"]
    # Explicit later binding wins on id collision within the sequence (last write).
    assert built.bindings[0].version_cid == a2.version_cid
    assert EnvironmentBindingSet.from_dict(built.to_dict()) == built


def test_build_from_isi_artifacts_admits_closed_kinds_only() -> None:
    lock = ArtifactRecord(
        "art:lock",
        "dependency_lock",
        "poetry.lock",
        source_cid=_cid("lock-bytes"),
    )
    noise = ArtifactRecord(
        "art:readme",
        "documentation",
        "README.md",
        source_cid=_cid("readme"),
    )
    pytest_cfg = ArtifactRecord(
        "art:pytest",
        "pytest_config",
        "pytest.ini",
        source_cid=_cid("pytest-ini"),
        metadata={"binding_scope": "global"},
    )
    state = RepositoryState(
        "repo:bindings",
        artifacts=(lock, noise, pytest_cfg),
    )
    built = build_environment_binding_set(repository_state=state)
    ids = {item.binding_id for item in built.bindings}
    assert "artifact:art:lock" in ids
    assert "artifact:art:pytest" in ids
    assert "artifact:art:readme" not in ids
    lock_binding = next(item for item in built.bindings if item.binding_id.endswith("lock"))
    assert lock_binding.kind == BindingKind.DEPENDENCY_LOCK.value
    assert lock_binding.extraction_authority == "isi-artifact"


def test_explicit_bindings_override_artifact_derived_ids() -> None:
    artifact = ArtifactRecord(
        "art:lock",
        "dependency_lock",
        "uv.lock",
        source_cid=_cid("uv"),
    )
    state = RepositoryState("repo:bindings", artifacts=(artifact,))
    override = EnvironmentBinding(
        binding_id="artifact:art:lock",
        kind=BindingKind.DEPENDENCY_LOCK,
        version_cid=_cid("override"),
        scope=BindingScope.GLOBAL,
        extraction_authority="injected",
    )
    built = build_environment_binding_set([override], repository_state=state)
    assert len(built.bindings) == 1
    assert built.bindings[0].extraction_authority == "injected"
    assert built.bindings[0].version_cid == override.version_cid


def test_relevant_projection_excludes_known_disjoint_package_bindings() -> None:
    lock_pkg_a = _binding(
        "lock:pkg-a",
        BindingKind.DEPENDENCY_LOCK,
        scope=BindingScope.PACKAGE,
        subject_id="pkg_a",
    )
    lock_pkg_b = _binding(
        "lock:pkg-b",
        BindingKind.DEPENDENCY_LOCK,
        scope=BindingScope.PACKAGE,
        subject_id="pkg_b",
    )
    toolchain = _binding(
        "toolchain:python",
        BindingKind.PYTHON_TOOLCHAIN,
        scope=BindingScope.GLOBAL,
    )
    binding_set = build_environment_binding_set([lock_pkg_a, lock_pkg_b, toolchain])

    symbol_a = _symbol("alpha", module="pkg_a/mod.py", namespace="pkg_a")
    symbol_b = _symbol("beta", module="pkg_b/mod.py", namespace="pkg_b")

    proj_a = relevant_binding_projection_for_symbol(symbol_a, binding_set)
    proj_b = relevant_binding_projection_for_symbol(symbol_b, binding_set)

    assert "lock:pkg-a" in proj_a.binding_ids
    assert "lock:pkg-b" not in proj_a.binding_ids
    assert "toolchain:python" in proj_a.binding_ids
    assert proj_a.includes_global is True

    assert "lock:pkg-b" in proj_b.binding_ids
    assert "lock:pkg-a" not in proj_b.binding_ids

    # Deterministic CID: same inputs produce the same projection.
    assert (
        relevant_binding_projection_for_symbol(symbol_a, binding_set).projection_cid
        == proj_a.projection_cid
    )


def test_symbol_and_module_scope_projection() -> None:
    symbol = _symbol("target")
    symbol_binding = _binding(
        "policy:target",
        BindingKind.POLICY,
        scope=BindingScope.SYMBOL,
        subject_id=symbol.stable_id,
    )
    other_symbol_binding = _binding(
        "policy:other",
        BindingKind.POLICY,
        scope=BindingScope.SYMBOL,
        subject_id=_cid("other-symbol"),
    )
    module_binding = _binding(
        "iface:mod",
        BindingKind.INTERFACE_DESCRIPTOR,
        scope=BindingScope.MODULE,
        subject_id="pkg/mod.py",
    )
    binding_set = build_environment_binding_set(
        [symbol_binding, other_symbol_binding, module_binding]
    )
    proj = relevant_binding_projection_for_symbol(symbol, binding_set)
    assert set(proj.binding_ids) == {"policy:target", "iface:mod"}
    assert proj.includes_global is False


def test_unknown_scope_projects_to_all_and_sets_includes_global() -> None:
    unknown = _binding(
        "lock:mystery",
        BindingKind.DEPENDENCY_LOCK,
        scope=BindingScope.UNKNOWN,
    )
    binding_set = build_environment_binding_set([unknown])
    symbol = _symbol("anywhere")
    proj = relevant_binding_projection_for_symbol(symbol, binding_set)
    assert list(proj.binding_ids) == ["lock:mystery"]
    assert proj.includes_global is True
    applies, global_flag = binding_applies_to_symbol(
        unknown, symbol.stable_id, module_path=symbol.module_path
    )
    assert applies and global_flag


def test_unmapped_package_scope_is_conservative() -> None:
    unmapped = _binding(
        "lock:no-subject",
        BindingKind.DEPENDENCY_LOCK,
        scope=BindingScope.PACKAGE,
        subject_id=None,
    )
    binding_set = build_environment_binding_set([unmapped])
    symbol = _symbol("x")
    proj = relevant_binding_projection_for_symbol(symbol, binding_set)
    assert "lock:no-subject" in proj.binding_ids
    assert proj.includes_global is True


def test_diff_environment_bindings_classifies_added_deleted_modified() -> None:
    prev = build_environment_binding_set(
        [
            _binding("lock:poetry", BindingKind.DEPENDENCY_LOCK, version="1"),
            _binding("policy:sec", BindingKind.POLICY, version="1"),
            _binding("toolchain:python", BindingKind.PYTHON_TOOLCHAIN, version="1"),
        ]
    )
    curr = build_environment_binding_set(
        [
            _binding("lock:poetry", BindingKind.DEPENDENCY_LOCK, version="2"),
            _binding("toolchain:python", BindingKind.PYTHON_TOOLCHAIN, version="1"),
            _binding("iface:api", BindingKind.INTERFACE_DESCRIPTOR, version="1"),
        ]
    )
    delta = diff_environment_bindings(prev, curr)
    assert list(delta.added_binding_ids) == ["iface:api"]
    assert list(delta.deleted_binding_ids) == ["policy:sec"]
    assert list(delta.modified_binding_ids) == ["lock:poetry"]
    assert list(delta.unchanged_binding_ids) == ["toolchain:python"]
    assert delta.previous_binding_set_cid == prev.binding_set_cid
    assert delta.current_binding_set_cid == curr.binding_set_cid
    assert set(changed_binding_ids(delta)) == {
        "iface:api",
        "policy:sec",
        "lock:poetry",
    }
    cold = diff_environment_bindings(None, curr)
    assert set(cold.added_binding_ids) == {
        "lock:poetry",
        "toolchain:python",
        "iface:api",
    }
    assert list(cold.deleted_binding_ids) == []


def test_iter_affected_symbol_ids_skips_disjoint_capsules() -> None:
    binding = _binding(
        "gen:pkg_a",
        BindingKind.GENERATED_INPUT,
        scope=BindingScope.PACKAGE,
        subject_id="pkg_a",
    )
    binding_set = build_environment_binding_set([binding])
    a = _symbol("a", module="pkg_a/a.py", namespace="pkg_a")
    b = _symbol("b", module="pkg_b/b.py", namespace="pkg_b")
    affected = iter_affected_symbol_ids(binding, binding_set, [a, b])
    assert affected == (a.stable_id,)


def test_build_rejects_non_binding_inputs() -> None:
    with pytest.raises(BindingsError, match="EnvironmentBinding"):
        build_environment_binding_set([object()])  # type: ignore[list-item]
    with pytest.raises(BindingsError, match="sequence"):
        build_environment_binding_set("not-a-sequence")  # type: ignore[arg-type]


def test_relevant_projection_requires_binding_set() -> None:
    with pytest.raises(BindingsError, match="EnvironmentBindingSet"):
        relevant_binding_projection(_cid("s"), object())  # type: ignore[arg-type]


def test_toolchain_kind_always_projects_globally() -> None:
    """Compiler/toolchain contracts project even if labeled with a package scope."""
    toolchain = _binding(
        "toolchain:py",
        BindingKind.PYTHON_TOOLCHAIN,
        scope=BindingScope.PACKAGE,
        subject_id="other_pkg",
    )
    binding_set = build_environment_binding_set([toolchain])
    symbol = _symbol("local", namespace="pkg", module="pkg/x.py")
    proj = relevant_binding_projection_for_symbol(symbol, binding_set)
    assert "toolchain:py" in proj.binding_ids
    assert proj.includes_global is True
