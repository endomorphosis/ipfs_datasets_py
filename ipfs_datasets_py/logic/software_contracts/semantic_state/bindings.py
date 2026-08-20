"""Environment binding set construction, projection, and delta algorithms.

This module is the sole owner of :func:`relevant_binding_projection`.  Capsule
compilation must consume the projection record produced here and must not
rediscover binding scope or reimplement the algorithm.

Repository-local lock, test-config, generated-file, and schema inputs come only
from final-ISI artifact records and typed edges.  External policy, toolchain,
and interface descriptors are injected as already-validated
:class:`EnvironmentBinding` values.  This package never performs a second
filesystem discovery pass.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    ArtifactRecord,
    RepositoryState,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    BindingKind,
    BindingScope,
    EnvironmentBinding,
    EnvironmentBindingSet,
    RelevantBindingProjection,
    SemanticBindingDelta,
)


class BindingsError(ValueError):
    """Raised when environment binding inputs are malformed or inconsistent."""


# Toolchain / schema / compiler contracts project to every capsule that can
# consume them, independent of incidental package/module subject labels.
_GLOBAL_CONTRACT_KINDS: Final[frozenset[str]] = frozenset(
    {
        BindingKind.PYTHON_TOOLCHAIN.value,
        BindingKind.SEMANTIC_SCHEMA.value,
        BindingKind.SEMANTIC_COMPILER.value,
    }
)

# Closed artifact recognition — exact kinds and basenames only (no path
# substring matching).
_ARTIFACT_KIND_TO_BINDING: Final[Mapping[str, str]] = MappingProxyType(
    {
        "dependency_lock": BindingKind.DEPENDENCY_LOCK.value,
        "dependency-lock": BindingKind.DEPENDENCY_LOCK.value,
        "lockfile": BindingKind.DEPENDENCY_LOCK.value,
        "lock_file": BindingKind.DEPENDENCY_LOCK.value,
        "requirements": BindingKind.DEPENDENCY_LOCK.value,
        "environment": BindingKind.DEPENDENCY_LOCK.value,
        "environment_lock": BindingKind.DEPENDENCY_LOCK.value,
        "dependency_manifest": BindingKind.DEPENDENCY_MANIFEST.value,
        "dependency-manifest": BindingKind.DEPENDENCY_MANIFEST.value,
        "manifest": BindingKind.DEPENDENCY_MANIFEST.value,
        "pytest_config": BindingKind.PYTEST_CONFIG.value,
        "pytest-config": BindingKind.PYTEST_CONFIG.value,
        "conftest": BindingKind.PYTEST_CONFIG.value,
        "test_config": BindingKind.PYTEST_CONFIG.value,
        "test-config": BindingKind.PYTEST_CONFIG.value,
        "pytest_plugin": BindingKind.PYTEST_PLUGIN.value,
        "pytest-plugin": BindingKind.PYTEST_PLUGIN.value,
        "proof_config": BindingKind.PROOF_CONFIG.value,
        "proof-config": BindingKind.PROOF_CONFIG.value,
        "policy": BindingKind.POLICY.value,
        "security_policy": BindingKind.POLICY.value,
        "interface_descriptor": BindingKind.INTERFACE_DESCRIPTOR.value,
        "interface-descriptor": BindingKind.INTERFACE_DESCRIPTOR.value,
        "generated_input": BindingKind.GENERATED_INPUT.value,
        "generated-input": BindingKind.GENERATED_INPUT.value,
        "generated": BindingKind.GENERATED_INPUT.value,
        "python_toolchain": BindingKind.PYTHON_TOOLCHAIN.value,
        "python-toolchain": BindingKind.PYTHON_TOOLCHAIN.value,
        "toolchain": BindingKind.PYTHON_TOOLCHAIN.value,
        "semantic_schema": BindingKind.SEMANTIC_SCHEMA.value,
        "semantic-schema": BindingKind.SEMANTIC_SCHEMA.value,
        "semantic_compiler": BindingKind.SEMANTIC_COMPILER.value,
        "semantic-compiler": BindingKind.SEMANTIC_COMPILER.value,
    }
)

_LOCK_BASENAMES: Final[frozenset[str]] = frozenset(
    {
        "poetry.lock",
        "pipfile.lock",
        "requirements.txt",
        "requirements-dev.txt",
        "requirements-test.txt",
        "uv.lock",
        "pdm.lock",
        "cargo.lock",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "composer.lock",
        "gemfile.lock",
        "go.sum",
    }
)
_MANIFEST_BASENAMES: Final[frozenset[str]] = frozenset(
    {
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
        "package.json",
        "cargo.toml",
        "go.mod",
        "pipfile",
    }
)
_PYTEST_CONFIG_BASENAMES: Final[frozenset[str]] = frozenset(
    {
        "pytest.ini",
        "tox.ini",
        "conftest.py",
    }
)


def _basename(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).name.lower()


def _artifact_binding_kind(artifact: ArtifactRecord) -> str | None:
    """Map one ISI artifact to a closed :class:`BindingKind` value, or None."""
    kind = artifact.kind.lower().replace("_", "-")
    normalized = kind.replace("-", "_")
    if normalized in _ARTIFACT_KIND_TO_BINDING:
        return _ARTIFACT_KIND_TO_BINDING[normalized]
    # Also try hyphen form keys.
    if kind in _ARTIFACT_KIND_TO_BINDING:
        return _ARTIFACT_KIND_TO_BINDING[kind]
    metadata = dict(artifact.metadata or {})
    meta_kind = metadata.get("binding_kind") or metadata.get("environment_binding_kind")
    if isinstance(meta_kind, str) and meta_kind:
        try:
            return BindingKind(meta_kind).value
        except ValueError:
            pass
    if metadata.get("environment_bound") or metadata.get("dependency_lock"):
        return BindingKind.DEPENDENCY_LOCK.value
    if metadata.get("pytest_config") or metadata.get("test_configuration"):
        return BindingKind.PYTEST_CONFIG.value
    if metadata.get("generated_input") or metadata.get("generated"):
        return BindingKind.GENERATED_INPUT.value
    base = _basename(artifact.path)
    if base in _LOCK_BASENAMES:
        return BindingKind.DEPENDENCY_LOCK.value
    if base in _MANIFEST_BASENAMES and not (
        base == "pyproject.toml" and metadata.get("pytest_config")
    ):
        # pyproject.toml may also be pytest config when marked; otherwise
        # treat as dependency manifest.
        if base in {"pytest.ini", "tox.ini", "conftest.py"}:
            return BindingKind.PYTEST_CONFIG.value
        if base == "pyproject.toml" and metadata.get("has_pytest_section"):
            return BindingKind.PYTEST_CONFIG.value
        return BindingKind.DEPENDENCY_MANIFEST.value
    if base in _PYTEST_CONFIG_BASENAMES:
        return BindingKind.PYTEST_CONFIG.value
    return None


def _artifact_scope(artifact: ArtifactRecord, kind: str) -> str:
    """Derive a binding scope from artifact metadata with conservative fallback."""
    metadata = dict(artifact.metadata or {})
    raw = metadata.get("binding_scope") or metadata.get("scope")
    if isinstance(raw, str) and raw:
        try:
            return BindingScope(raw).value
        except ValueError as exc:
            raise BindingsError(
                f"artifact {artifact.artifact_id!r} has unsupported binding scope {raw!r}"
            ) from exc
    if kind in _GLOBAL_CONTRACT_KINDS:
        return BindingScope.GLOBAL.value
    # Lock/manifest/config with no explicit subject map conservatively to
    # UNKNOWN so uncertainty remains visible rather than silently global.
    subject = metadata.get("subject_id") or metadata.get("package") or metadata.get("module")
    if subject:
        if metadata.get("package") and not metadata.get("module"):
            return BindingScope.PACKAGE.value
        if metadata.get("module") or metadata.get("module_path"):
            return BindingScope.MODULE.value
        return BindingScope.SYMBOL.value
    # Repository-local locks without a declared subject still affect the whole
    # environment when they are classic root lockfiles; otherwise unknown.
    if kind in {
        BindingKind.DEPENDENCY_LOCK.value,
        BindingKind.DEPENDENCY_MANIFEST.value,
        BindingKind.PYTHON_TOOLCHAIN.value,
        BindingKind.SEMANTIC_SCHEMA.value,
        BindingKind.SEMANTIC_COMPILER.value,
    } and PurePosixPath(artifact.path.replace("\\", "/")).parent == PurePosixPath("."):
        return BindingScope.GLOBAL.value
    return BindingScope.UNKNOWN.value


def _artifact_subject(artifact: ArtifactRecord, scope: str) -> str | None:
    metadata = dict(artifact.metadata or {})
    for key in ("subject_id", "package", "module", "module_path", "stable_symbol_id"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    if scope in {BindingScope.GLOBAL.value, BindingScope.UNKNOWN.value}:
        return None
    return None


def _binding_from_artifact(artifact: ArtifactRecord) -> EnvironmentBinding | None:
    kind = _artifact_binding_kind(artifact)
    if kind is None:
        return None
    scope = _artifact_scope(artifact, kind)
    version_cid = artifact.source_cid
    if version_cid is None:
        # Content-address the path+kind when the producer recorded no source CID
        # so the binding still has a stable version identity.
        version_cid = cid_for_bytes(
            f"artifact-binding:{artifact.artifact_id}:{kind}:{artifact.path}".encode("utf-8")
        )
    confidence = artifact.confidence
    if confidence not in {
        AnalysisConfidence.EXACT.value,
        AnalysisConfidence.CONSERVATIVE.value,
        AnalysisConfidence.HEURISTIC.value,
        AnalysisConfidence.OPAQUE.value,
    }:
        confidence = AnalysisConfidence.CONSERVATIVE.value
    return EnvironmentBinding(
        binding_id=f"artifact:{artifact.artifact_id}",
        kind=kind,
        version_cid=version_cid,
        scope=scope,
        extraction_authority="isi-artifact",
        confidence=confidence,
        subject_id=_artifact_subject(artifact, scope),
        content_cid=artifact.source_cid,
        metadata={
            "artifact_id": artifact.artifact_id,
            "path": artifact.path,
            "artifact_kind": artifact.kind,
        },
    )


def _validate_binding(binding: EnvironmentBinding) -> EnvironmentBinding:
    if not isinstance(binding, EnvironmentBinding):
        raise BindingsError("bindings must be EnvironmentBinding values")
    # EnvironmentBinding already validates kind/scope/CIDs in __post_init__.
    return binding


def build_environment_binding_set(
    bindings: Sequence[EnvironmentBinding] = (),
    *,
    repository_state: RepositoryState | None = None,
) -> EnvironmentBindingSet:
    """Build a closed, sorted :class:`EnvironmentBindingSet`.

    Explicit ``bindings`` are authoritative for their ``binding_id``.  When
    ``repository_state`` is supplied, ISI artifacts that match closed
    lock/config/generated/toolchain kinds are admitted as
    ``extraction_authority="isi-artifact"`` bindings unless an explicit binding
    already claims the same id.
    """
    if not isinstance(bindings, Sequence) or isinstance(bindings, (str, bytes)):
        raise BindingsError("bindings must be a sequence of EnvironmentBinding values")
    by_id: dict[str, EnvironmentBinding] = {}
    if repository_state is not None:
        if not isinstance(repository_state, RepositoryState):
            raise BindingsError("repository_state must be a RepositoryState or None")
        for artifact in repository_state.artifacts:
            derived = _binding_from_artifact(artifact)
            if derived is not None:
                by_id[derived.binding_id] = derived
    for item in bindings:
        binding = _validate_binding(item)
        by_id[binding.binding_id] = binding
    return EnvironmentBindingSet(bindings=tuple(by_id.values()))


def _package_of(
    *,
    symbol_package: str | None,
    symbol_namespace: str | None,
    module_path: str | None,
    package: str | None,
) -> str | None:
    if package:
        return package
    if symbol_package:
        return symbol_package
    if symbol_namespace:
        return symbol_namespace
    if module_path:
        parts = PurePosixPath(module_path.replace("\\", "/")).parts
        if parts:
            return parts[0]
    return None


def binding_applies_to_symbol(
    binding: EnvironmentBinding,
    stable_symbol_id: str,
    *,
    package: str | None = None,
    module_path: str | None = None,
    symbol_namespace: str | None = None,
) -> tuple[bool, bool]:
    """Return ``(applies, forces_global_projection_flag)`` for one binding.

    ``forces_global_projection_flag`` is True when the binding is GLOBAL,
    UNKNOWN, an unmappable scoped binding, or a global toolchain contract —
    i.e. when the projection must report ``includes_global=True``.
    """
    if not isinstance(binding, EnvironmentBinding):
        raise BindingsError("binding must be an EnvironmentBinding")
    if type(stable_symbol_id) is not str or not stable_symbol_id:
        raise BindingsError("stable_symbol_id must be a nonempty string")

    kind = str(binding.kind)
    scope = str(binding.scope)
    subject = binding.subject_id

    # Inherent global contracts always project.
    if kind in _GLOBAL_CONTRACT_KINDS:
        return True, True

    if scope == BindingScope.GLOBAL.value:
        return True, True

    if scope == BindingScope.UNKNOWN.value:
        return True, True

    if scope == BindingScope.SYMBOL.value:
        if subject is None:
            # Unknown mapping — conservative global.
            return True, True
        return subject == stable_symbol_id, False

    if scope == BindingScope.MODULE.value:
        if subject is None:
            return True, True
        if module_path is None:
            # Cannot decide membership without module context → conservative.
            return True, True
        return subject == module_path or module_path.startswith(subject.rstrip("/") + "/"), False

    if scope == BindingScope.PACKAGE.value:
        if subject is None:
            return True, True
        pkg = _package_of(
            symbol_package=package,
            symbol_namespace=symbol_namespace,
            module_path=module_path,
            package=package,
        )
        if pkg is None:
            return True, True
        return subject == pkg or pkg.startswith(subject + ".") or subject.startswith(pkg + "."), False

    # Unknown enum value is rejected by EnvironmentBinding construction; defend.
    return True, True


def relevant_binding_projection(
    stable_symbol_id: str,
    binding_set: EnvironmentBindingSet,
    *,
    package: str | None = None,
    module_path: str | None = None,
    symbol_namespace: str | None = None,
) -> RelevantBindingProjection:
    """Compute the deterministic per-symbol relevant binding projection.

    Capsules bind only this projection.  A known disjoint policy, interface, or
    lock therefore changes the state root without changing unrelated capsule
    CIDs.  UNKNOWN or GLOBAL scope (and unmappable scoped bindings) deliberately
    project to all possibly affected capsules via ``includes_global``.
    """
    if not isinstance(binding_set, EnvironmentBindingSet):
        raise BindingsError("binding_set must be an EnvironmentBindingSet")
    if type(stable_symbol_id) is not str or not stable_symbol_id:
        raise BindingsError("stable_symbol_id must be a nonempty string")

    selected: list[str] = []
    includes_global = False
    for binding in binding_set.bindings:
        applies, global_flag = binding_applies_to_symbol(
            binding,
            stable_symbol_id,
            package=package,
            module_path=module_path,
            symbol_namespace=symbol_namespace,
        )
        if applies:
            selected.append(binding.binding_id)
            if global_flag:
                includes_global = True
    return RelevantBindingProjection(
        stable_symbol_id=stable_symbol_id,
        binding_ids=selected,
        includes_global=includes_global,
        binding_set_cid=binding_set.binding_set_cid,
    )


def relevant_binding_projection_for_symbol(
    symbol: object,
    binding_set: EnvironmentBindingSet,
) -> RelevantBindingProjection:
    """Project bindings for an ISI :class:`SymbolRecord`-like object."""
    stable_id = getattr(symbol, "stable_id", None)
    if type(stable_id) is not str or not stable_id:
        raise BindingsError("symbol must expose a nonempty stable_id string")
    return relevant_binding_projection(
        stable_id,
        binding_set,
        package=getattr(symbol, "namespace", None) or None,
        module_path=getattr(symbol, "module_path", None) or None,
        symbol_namespace=getattr(symbol, "namespace", None) or None,
    )


def diff_environment_bindings(
    previous: EnvironmentBindingSet | None,
    current: EnvironmentBindingSet,
) -> SemanticBindingDelta:
    """Compare environment bindings by stable ID and old/new version CIDs."""
    if not isinstance(current, EnvironmentBindingSet):
        raise BindingsError("current must be an EnvironmentBindingSet")
    if previous is not None and not isinstance(previous, EnvironmentBindingSet):
        raise BindingsError("previous must be an EnvironmentBindingSet or None")

    prev_map: dict[str, EnvironmentBinding] = {}
    if previous is not None:
        prev_map = {item.binding_id: item for item in previous.bindings}
    curr_map = {item.binding_id: item for item in current.bindings}

    prev_ids = set(prev_map)
    curr_ids = set(curr_map)
    added = sorted(curr_ids - prev_ids)
    deleted = sorted(prev_ids - curr_ids)
    shared = prev_ids & curr_ids
    modified: list[str] = []
    unchanged: list[str] = []
    for binding_id in sorted(shared):
        if prev_map[binding_id].version_cid != curr_map[binding_id].version_cid:
            modified.append(binding_id)
        else:
            # Kind/scope/confidence drift with identical version_cid is still a
            # semantic change of the binding record itself.
            if prev_map[binding_id].record_cid != curr_map[binding_id].record_cid:
                modified.append(binding_id)
            else:
                unchanged.append(binding_id)

    prev_versions = {
        binding_id: prev_map[binding_id].version_cid for binding_id in sorted(prev_ids)
    }
    curr_versions = {
        binding_id: curr_map[binding_id].version_cid for binding_id in sorted(curr_ids)
    }
    return SemanticBindingDelta(
        previous_binding_set_cid=None if previous is None else previous.binding_set_cid,
        current_binding_set_cid=current.binding_set_cid,
        added_binding_ids=added,
        deleted_binding_ids=deleted,
        modified_binding_ids=modified,
        unchanged_binding_ids=unchanged,
        previous_version_cids=prev_versions,
        current_version_cids=curr_versions,
    )


def changed_binding_ids(delta: SemanticBindingDelta) -> tuple[str, ...]:
    """Return sorted added, deleted, and modified binding IDs."""
    if not isinstance(delta, SemanticBindingDelta):
        raise BindingsError("delta must be a SemanticBindingDelta")
    return tuple(
        sorted(
            set(delta.added_binding_ids)
            | set(delta.deleted_binding_ids)
            | set(delta.modified_binding_ids)
        )
    )


def bindings_by_id(
    binding_set: EnvironmentBindingSet | None,
) -> dict[str, EnvironmentBinding]:
    """Index bindings by stable binding_id."""
    if binding_set is None:
        return {}
    if not isinstance(binding_set, EnvironmentBindingSet):
        raise BindingsError("binding_set must be an EnvironmentBindingSet or None")
    return {item.binding_id: item for item in binding_set.bindings}


def iter_affected_symbol_ids(
    binding: EnvironmentBinding,
    binding_set: EnvironmentBindingSet,
    symbols: Iterable[object],
) -> tuple[str, ...]:
    """Return stable symbol IDs whose relevant projection includes ``binding``.

    Known disjoint symbols are omitted.  Unknown/global/unmappable scope yields
    every supplied symbol (conservative).
    """
    if not isinstance(binding, EnvironmentBinding):
        raise BindingsError("binding must be an EnvironmentBinding")
    if not isinstance(binding_set, EnvironmentBindingSet):
        raise BindingsError("binding_set must be an EnvironmentBindingSet")
    affected: list[str] = []
    for symbol in symbols:
        stable_id = getattr(symbol, "stable_id", None)
        if type(stable_id) is not str or not stable_id:
            continue
        projection = relevant_binding_projection_for_symbol(symbol, binding_set)
        if binding.binding_id in projection.binding_ids:
            affected.append(stable_id)
    return tuple(sorted(set(affected)))


__all__ = [
    "BindingsError",
    "binding_applies_to_symbol",
    "bindings_by_id",
    "build_environment_binding_set",
    "changed_binding_ids",
    "diff_environment_bindings",
    "iter_affected_symbol_ids",
    "relevant_binding_projection",
    "relevant_binding_projection_for_symbol",
]
