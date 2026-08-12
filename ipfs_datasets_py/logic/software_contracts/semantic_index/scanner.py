"""Deterministic assembly of a repository's pre-resolution semantic state.

The scanner is intentionally a thin coordinator: snapshots decide which bytes
are inputs, and the Python/pytest frontends decide what those bytes mean.  It
never imports target modules.  In particular, ``previous_state`` is only an
optional record-reuse cache; all output is still derived from the current,
CID-verified snapshot inputs.

Verified incremental reuse (ISI-040): when ``previous_state`` matches the
current repository, schema, and extractor identities, source files whose
snapshot member ``source_cid`` still matches the prior verified records skip
Python re-analysis.  Pytest unification and graph resolution always rerun so
dependent edges recompute against the live inventory.  Reuse diagnostics live
on the scanner instance only and never enter the durable state root.

Identity unification (ISI-036): a pytest test/fixture never clones a second
stable ID beside the Python logical binding.  Pytest facts are merged into
that binding (reclassified as ``test``/``fixture``) before version CIDs and
the public state root are computed.  Lexical edge targets are resolved
through :mod:`symbol_graph` so the returned state never relies on parallel
``lexical:`` targets for resolvable calls.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import (
    stable_symbol_id,
    symbol_version_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    SEMANTIC_INDEX_SCHEMA,
    AnalysisConfidence,
    ArtifactRecord,
    DependencyEdge,
    RelationType,
    RepositoryState,
    SymbolKind,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.python_analysis import (
    PythonSemanticAnalyzer,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.pytest_analysis import (
    PYTEST_ANALYZER_VERSION,
    PytestAnalyzer,
    PytestFixtureFacts,
    PytestTestFacts,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import (
    RepositorySnapshot,
    SnapshotEntry,
    _git_root,
    snapshot_repository,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.symbol_graph import (
    build_symbol_graph,
)


SCANNER_NAME = "semantic-repository-scanner"
SCANNER_VERSION = "1"
SCAN_REUSE_DIAGNOSTICS_SCHEMA = (
    "ipfs-datasets.software-contracts.semantic-index-scan-reuse@1"
)
_CONFIDENCE_RANK = {"exact": 0, "conservative": 1, "heuristic": 2, "opaque": 3}
_LOCK_KINDS = frozenset({"dependency-lock"})
# Edges produced by pytest analysis or scanner lock wiring are always rebuilt.
_NON_REUSABLE_RELATIONS = frozenset({
    RelationType.TESTED_BY.value,
    RelationType.USES_FIXTURE.value,
    RelationType.CONFIGURED_BY.value,
})
_NON_REUSABLE_EXTRACTION = frozenset({
    "static-test-call-reversal",
    "static-dependency-lock",
})


class RepositoryScannerError(ValueError):
    """Raised for invalid scanner inputs rather than silently changing scope."""


@dataclass(frozen=True, slots=True)
class ScanReuseDiagnostics:
    """Ephemeral measurements of verified ``previous_state`` reuse.

    These fields deliberately never participate in :class:`RepositoryState`
    identity.  Callers inspect them after a scan to prove which sources skipped
    re-analysis; durable consumers must ignore them.
    """

    schema: str = SCAN_REUSE_DIAGNOSTICS_SCHEMA
    previous_state_accepted: bool = False
    reject_reason: str | None = None
    reused_paths: tuple[str, ...] = ()
    analyzed_paths: tuple[str, ...] = ()
    reused_symbol_ids: tuple[str, ...] = ()
    recomputed_symbol_ids: tuple[str, ...] = ()
    reused_artifact_paths: tuple[str, ...] = ()
    resolution_recomputed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "previous_state_accepted": self.previous_state_accepted,
            "reject_reason": self.reject_reason,
            "reused_paths": list(self.reused_paths),
            "analyzed_paths": list(self.analyzed_paths),
            "reused_symbol_ids": list(self.reused_symbol_ids),
            "recomputed_symbol_ids": list(self.recomputed_symbol_ids),
            "reused_artifact_paths": list(self.reused_artifact_paths),
            "resolution_recomputed": self.resolution_recomputed,
        }


def _artifact_id(path: str) -> str:
    return "artifact:" + path


def _artifact_path(entry: SnapshotEntry) -> str:
    """Models intentionally admit only normalized source paths.

    Raw snapshot names are nevertheless retained verbatim in entry evidence;
    unsafe names get a private display path and a raw-name-derived identity.
    """
    # SnapshotEntry has already proved that a safe path is the exact UTF-8
    # decoding of its raw bytes.  Models reject backslash/NFD projections, so
    # those remain opaque without ever being used as a lookup key.
    import unicodedata
    try:
        safe = bytes.fromhex(entry.raw_path_hex or "").decode("utf-8", "strict") == entry.path
    except (ValueError, UnicodeDecodeError):
        safe = False
    if safe and "\\" not in entry.path and unicodedata.normalize("NFC", entry.path) == entry.path:
        return entry.path
    return "@snapshot-entry/raw/" + (entry.raw_path_hex or "")


def _opaque_artifact(entry: SnapshotEntry, reason: str, *, source_cid: str | None = None) -> ArtifactRecord:
    return ArtifactRecord(
        _artifact_id("raw/" + (entry.raw_path_hex or entry.path.encode().hex())), "opaque", _artifact_path(entry),
        entry.source_cid if source_cid is None else source_cid,
        AnalysisConfidence.OPAQUE,
        {"snapshot_kind": entry.kind, "opaque_reason": reason,
         "raw_path_hex": entry.raw_path_hex, "disposition": entry.disposition},
    )


def _typed_artifact(entry: SnapshotEntry) -> ArtifactRecord:
    return ArtifactRecord(
        _artifact_id("raw/" + (entry.raw_path_hex or entry.path.encode().hex())), entry.kind, _artifact_path(entry), entry.source_cid,
        AnalysisConfidence.EXACT, {"snapshot_kind": entry.kind,
                                   "raw_path_hex": entry.raw_path_hex,
                                   "disposition": entry.disposition},
    )


def _input_root(repository: Path) -> Path:
    """Use the Git worktree root when a caller supplied one of its subpaths."""
    return _git_root(repository) or repository


def _witness_matches(root: Path, entry: SnapshotEntry) -> bool:
    """Detect replacement without opening a selected input for content."""
    if entry.witness is None:
        return True
    try:
        observed = (root / os.fsdecode(bytes.fromhex(entry.raw_path_hex or ""))).stat(follow_symlinks=False)
    except (OSError, ValueError):
        return False
    return entry.witness == (observed.st_dev, observed.st_ino, observed.st_size,
                             observed.st_mtime_ns, observed.st_ctime_ns)


def _merge_confidence(*values: str) -> str:
    return max((AnalysisConfidence(value).value for value in values), key=_CONFIDENCE_RANK.__getitem__)


def _module_name(path: str) -> str:
    parts = list(PurePosixPath(path.replace("\\", "/")).parts)
    if parts and parts[-1].endswith((".py", ".pyi")):
        parts[-1] = parts[-1].rsplit(".", 1)[0]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or "__main__"


def _python_qualified(path: str, local_qualified: str) -> str:
    """Map a pytest-local qualified name onto the Python module binding name."""
    module = _module_name(path)
    if not local_qualified:
        return module
    if local_qualified == module or local_qualified.startswith(module + "."):
        return local_qualified
    return f"{module}.{local_qualified}"


def _pytest_projection(facts: PytestTestFacts | PytestFixtureFacts) -> dict[str, Any]:
    """Closed DAG-JSON facet bound into the unified symbol version."""
    if isinstance(facts, PytestTestFacts):
        return {
            "kind": "test",
            "fixture_parameters": list(facts.fixture_parameters),
            "usefixtures": list(facts.usefixtures),
            "markers": list(facts.version_markers),
            "function_markers": list(facts.markers),
            "module_markers": list(facts.module_markers),
            "class_markers": list(facts.class_markers),
            "parametrizations": [list(group) for group in facts.parametrizations],
            "all_parameters": list(facts.all_parameters),
        }
    return {
        "kind": "fixture",
        "name": facts.name,
        "dependencies": list(facts.dependencies),
        "scope": facts.scope,
        "autouse": facts.autouse,
        "params": list(facts.params),
    }


def _thaw(value: Any) -> Any:
    """Detach frozen SymbolRecord mappings/tuples into strict DAG-JSON."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _reissue_pytest_symbol(
    python: SymbolRecord,
    facts: PytestTestFacts | PytestFixtureFacts,
    kind: SymbolKind,
) -> SymbolRecord:
    """One logical binding: Python body/signature plus pytest receipt facts."""
    annotations = _thaw(python.annotations)
    projection = _pytest_projection(facts)
    annotations["pytest"] = projection
    metadata = _thaw(python.metadata)
    metadata["pytest"] = projection
    if isinstance(facts, PytestFixtureFacts):
        metadata["fixture_name"] = facts.name
    confidence = _merge_confidence(python.confidence, str(facts.confidence))
    signature = _thaw(python.signature)
    normalized = _thaw(python.normalized_ast)
    stable = stable_symbol_id(
        python.repository_id, python.language, python.module_path,
        python.qualified_name, kind, python.namespace,
    )
    version = symbol_version_cid(
        stable,
        normalized,
        signature,
        tuple(python.decorators),
        annotations,
        extractor_name=python.extractor_name,
        extractor_version=python.extractor_version,
        property_role=python.property_role,
    )
    return SymbolRecord(
        stable, version, python.repository_id, python.language, python.module_path,
        python.qualified_name, kind, python.namespace, python.source_cid, facts.span or python.span,
        confidence, signature, tuple(python.decorators), annotations, metadata,
        normalized, python.extractor_name, python.extractor_version,
        python.property_role,
    )


def _standalone_pytest_symbol(
    facts: PytestTestFacts | PytestFixtureFacts,
    kind: SymbolKind,
    repository_id: str,
    namespace: str,
) -> SymbolRecord:
    """Fallback when no Python binding exists (should be rare for valid AST)."""
    qualified = _python_qualified(facts.path, facts.qualified_name)
    module_namespace = namespace or _module_name(facts.path).split(".")[0]
    projection = _pytest_projection(facts)
    annotations = {"pytest": projection}
    # Minimal location-free projection so v2 identity verifies without a body.
    normalized = {
        "_type": "PytestBinding",
        "qualified_name": qualified,
        "pytest": projection,
    }
    stable = stable_symbol_id(
        repository_id, "python", facts.path, qualified, kind, module_namespace,
    )
    version = symbol_version_cid(
        stable, normalized, {}, (), annotations,
        extractor_name="pytest-static-ast", extractor_version=PYTEST_ANALYZER_VERSION,
    )
    metadata: dict[str, Any] = {"pytest": projection, "standalone_pytest": True}
    if isinstance(facts, PytestFixtureFacts):
        metadata["fixture_name"] = facts.name
    return SymbolRecord(
        stable, version, repository_id, "python", facts.path, qualified, kind,
        module_namespace, facts.source_cid, facts.span, facts.confidence,
        {}, (), annotations, metadata, normalized,
        "pytest-static-ast", PYTEST_ANALYZER_VERSION,
    )


def _remap_edge(edge: DependencyEdge, remap: Mapping[str, str]) -> DependencyEdge:
    source = remap.get(edge.source_id, edge.source_id)
    target = remap.get(edge.target_id, edge.target_id)
    if source == edge.source_id and target == edge.target_id:
        return edge
    return DependencyEdge(
        source, target, edge.relation, edge.extraction_method, edge.confidence,
        edge.extractor_version, edge.span, edge.metadata,
    )


def unify_pytest_identities(
    symbols: Sequence[SymbolRecord],
    edges: Sequence[DependencyEdge],
    tests: Sequence[PytestTestFacts],
    fixtures: Sequence[PytestFixtureFacts],
    pytest_edges: Sequence[DependencyEdge],
    *,
    repository_id: str,
    namespace: str | None,
) -> tuple[list[SymbolRecord], list[DependencyEdge], dict[str, str]]:
    """Merge pytest facts into the one Python logical binding per declaration.

    Never clones a second TEST/FIXTURE identity alongside a FUNCTION/METHOD
    binding for the same path and qualified name.  Call/import edge sources
    that previously pointed at the function identity are remapped to the
    unified test/fixture stable ID.
    """
    by_path_qn: dict[tuple[str, str], SymbolRecord] = {
        (item.module_path, item.qualified_name): item for item in symbols
    }
    remap: dict[str, str] = {}
    replaced: set[str] = set()
    unified: list[SymbolRecord] = []

    def absorb(facts: PytestTestFacts | PytestFixtureFacts, kind: SymbolKind) -> SymbolRecord:
        python_qn = _python_qualified(facts.path, facts.qualified_name)
        python = by_path_qn.get((facts.path, python_qn))
        if python is None:
            # Match by trailing local qualified name within the same module.
            for (path, qn), candidate in by_path_qn.items():
                if path == facts.path and (qn == python_qn or qn.endswith("." + facts.qualified_name)):
                    python = candidate
                    break
        if python is not None and python.stable_id not in replaced:
            record = _reissue_pytest_symbol(python, facts, kind)
            remap[python.stable_id] = record.stable_id
            remap[facts.symbol_id] = record.stable_id
            replaced.add(python.stable_id)
            return record
        record = _standalone_pytest_symbol(facts, kind, repository_id, namespace or "pytest")
        remap[facts.symbol_id] = record.stable_id
        return record

    for item in tests:
        unified.append(absorb(item, SymbolKind.TEST))
    for item in fixtures:
        unified.append(absorb(item, SymbolKind.FIXTURE))

    for item in symbols:
        if item.stable_id not in replaced:
            unified.append(item)

    # Collapse any accidental duplicate stable IDs (should not occur).
    by_stable: dict[str, SymbolRecord] = {}
    for item in unified:
        by_stable[item.stable_id] = item
    merged_symbols = list(by_stable.values())

    remapped_edges = [_remap_edge(edge, remap) for edge in (*edges, *pytest_edges)]
    # Deduplicate after remap (edge_id changes with source/target).
    edge_by_id = {edge.edge_id: edge for edge in remapped_edges}
    return merged_symbols, list(edge_by_id.values()), remap


def _evaluate_previous_state(
    previous_state: RepositoryState | None,
    *,
    repository_id: str,
    extractor_name: str,
    extractor_version: str,
) -> tuple[RepositoryState | None, str | None]:
    """Return an accepted previous state or ``(None, reason)`` without raising.

    Type errors still raise: a non-state value is a programming mistake, not a
    forged optimization input.  Repository/schema/extractor mismatches refuse
    reuse and force a cold analysis path.
    """
    if previous_state is None:
        return None, None
    if not isinstance(previous_state, RepositoryState):
        raise RepositoryScannerError("previous_state must be a RepositoryState")
    if previous_state.repository_id != repository_id:
        return None, "repository_id_mismatch"
    if previous_state.schema != SEMANTIC_INDEX_SCHEMA:
        return None, "schema_mismatch"
    if previous_state.extractor_name != extractor_name:
        return None, "extractor_name_mismatch"
    if previous_state.extractor_version != extractor_version:
        return None, "extractor_version_mismatch"
    return previous_state, None


def _python_frontend_edge(edge: DependencyEdge) -> bool:
    """Whether an edge is eligible to ride along with reused Python analysis."""
    if edge.relation in _NON_REUSABLE_RELATIONS:
        return False
    if edge.extraction_method in _NON_REUSABLE_EXTRACTION:
        return False
    return True


def _reusable_path_symbols(
    previous: RepositoryState,
    path: str,
    source_cid: str,
) -> tuple[SymbolRecord, ...] | None:
    """Return prior symbols for ``path`` when every record matches ``source_cid``."""
    items = tuple(item for item in previous.symbols if item.module_path == path)
    if not items:
        return None
    if any(item.source_cid != source_cid for item in items):
        return None
    if any(item.semantic_index_schema != SEMANTIC_INDEX_SCHEMA for item in items):
        return None
    if any(item.repository_id != previous.repository_id for item in items):
        return None
    return items


def _reusable_opaque_python_artifact(
    previous: RepositoryState,
    path: str,
    source_cid: str,
) -> ArtifactRecord | None:
    """Return a prior opaque python-analysis artifact for the same bytes."""
    for artifact in previous.artifacts:
        if (
            artifact.path == path
            and artifact.kind == "python-analysis"
            and artifact.source_cid == source_cid
            and artifact.confidence == AnalysisConfidence.OPAQUE.value
        ):
            return artifact
    return None


def _reusable_path_edges(
    previous: RepositoryState,
    symbol_ids: set[str],
) -> list[DependencyEdge]:
    """Reuse non-pytest edges sourced from verified path symbols."""
    return [
        edge for edge in previous.edges
        if edge.source_id in symbol_ids and _python_frontend_edge(edge)
    ]


def _lock_configuration_edges(
    symbols: Sequence[SymbolRecord],
    artifacts: Sequence[ArtifactRecord],
) -> list[DependencyEdge]:
    """Emit source-rooted configured_by edges from tests to explicit lockfiles.

    Dependency/lock artifacts are statically present snapshot kinds.  Every
    test receipt is treated as environment-sensitive when a lock/dependency
    artifact exists in the same repository state; this is explicit presence,
    not a guessed import graph.
    """
    locks = [item for item in artifacts if item.kind in _LOCK_KINDS or item.kind == "dependency-lock"]
    if not locks:
        # Also accept artifacts whose path is a known lock basename.
        lock_names = {
            "poetry.lock", "pdm.lock", "uv.lock", "requirements.txt",
            "requirements-dev.txt", "Pipfile.lock", "package-lock.json",
            "yarn.lock", "pnpm-lock.yaml",
        }
        locks = [
            item for item in artifacts
            if PurePosixPath(item.path).name in lock_names
            or item.metadata.get("snapshot_kind") == "dependency-lock"
        ]
    if not locks:
        return []
    edges: list[DependencyEdge] = []
    tests = [item for item in symbols if item.kind == SymbolKind.TEST.value]
    for test in tests:
        for lock in locks:
            edges.append(DependencyEdge(
                test.stable_id, lock.artifact_id, RelationType.CONFIGURED_BY,
                "static-dependency-lock", "exact", SCANNER_VERSION, test.span,
                {"config_path": lock.path, "source_bound": True, "lock": True},
            ))
    return edges


@dataclass(slots=True)
class RepositoryScanner:
    """Build a deterministic :class:`RepositoryState` without target execution.

    After each :meth:`scan` / :meth:`scan_snapshot`, :attr:`last_reuse_diagnostics`
    reports which source paths reused verified prior analysis.  Diagnostics are
    ephemeral process state and are excluded from durable root identity.
    """

    repository_id: str | None = None
    namespace: str | None = None
    extractor_name: str = SCANNER_NAME
    extractor_version: str = SCANNER_VERSION
    exclusions: Iterable[str] | None = None
    last_reuse_diagnostics: ScanReuseDiagnostics | None = field(default=None, repr=False)

    def scan(
        self,
        repository: str | os.PathLike[str],
        *,
        previous_state: RepositoryState | None = None,
        snapshot: RepositorySnapshot | None = None,
    ) -> RepositoryState:
        root = Path(repository).resolve()
        current = snapshot or snapshot_repository(root, repository_id=self.repository_id, exclusions=self.exclusions)
        root = _input_root(root)
        if self.repository_id is not None and current.repository_id != self.repository_id:
            raise RepositoryScannerError("snapshot repository_id does not match scanner repository_id")
        sources: dict[str, bytes] = {}
        unavailable: dict[str, str] = {}
        for entry in current.entries:
            if entry.is_opaque or entry.source_cid is None:
                continue
            # Content bytes were captured by snapshot acquisition.  The
            # witness check deliberately reads metadata only; it preserves the
            # historical race signal without a second content-byte read.
            if current.mode != "git-clean" and not _witness_matches(root, entry):
                unavailable[entry.source_key] = "source_cid_mismatch"
            elif entry.captured_bytes is None:
                unavailable[entry.source_key] = "source_bytes_unavailable"
            else:
                sources[entry.source_key] = entry.captured_bytes
        return self.scan_snapshot(current, sources, previous_state=previous_state, unavailable=unavailable)

    def scan_snapshot(
        self,
        snapshot: RepositorySnapshot,
        sources: Mapping[str, str | bytes],
        *,
        previous_state: RepositoryState | None = None,
        unavailable: Mapping[str, str] | None = None,
    ) -> RepositoryState:
        """Assemble a state from a snapshot plus bytes keyed by relative path.

        Supplying bytes explicitly makes this suitable for immutable object
        stores.  Every supplied byte sequence is checked against the snapshot;
        absent or mismatched bytes become an explicit opaque artifact.

        The returned state is fully identity-unified and edge-resolved: call
        targets that uniquely match inventory symbols are stable CIDs, never
        a parallel ``lexical:`` residual for the same binding.

        ``previous_state`` may skip Python re-analysis for paths whose verified
        ``source_cid`` and extractor/schema identities still match.  Graph
        resolution always recomputes against the current inventory.
        """
        if not isinstance(snapshot, RepositorySnapshot):
            raise RepositoryScannerError("snapshot must be a RepositorySnapshot")
        if self.repository_id is not None and snapshot.repository_id != self.repository_id:
            raise RepositoryScannerError("snapshot repository_id does not match scanner repository_id")

        accepted_previous, reject_reason = _evaluate_previous_state(
            previous_state,
            repository_id=snapshot.repository_id,
            extractor_name=self.extractor_name,
            extractor_version=self.extractor_version,
        )
        previous_by_key: dict[tuple[str, str, str], SymbolRecord] = {}
        if accepted_previous is not None:
            previous_by_key = {
                (item.stable_id, item.source_cid or "", item.version_cid): item
                for item in accepted_previous.symbols
            }

        artifacts: list[ArtifactRecord] = []
        symbols: list[SymbolRecord] = []
        edges: list[DependencyEdge] = []
        verified: dict[str, bytes] = {}
        failures = dict(unavailable or {})
        entries_by_key = {entry.source_key: entry for entry in snapshot.entries}
        reused_paths: list[str] = []
        analyzed_paths: list[str] = []
        reused_symbol_ids: list[str] = []
        recomputed_symbol_ids: list[str] = []
        reused_artifact_paths: list[str] = []

        # State roots must bind the complete acquisition authority, not merely
        # the parsed source subset.  This has a fixed identity so a real file
        # named @snapshot-evidence cannot collide with it.
        artifacts.append(ArtifactRecord(
            "artifact:snapshot-evidence", "snapshot-evidence", "@snapshot-evidence",
            snapshot.snapshot_cid, AnalysisConfidence.EXACT,
            {"snapshot": snapshot.to_dict(), "acquisition": snapshot.mode,
             "exclusions": list(snapshot.exclusions)},
        ))
        for entry in snapshot.entries:
            if entry.is_opaque:
                artifacts.append(_opaque_artifact(entry, entry.opaque_reason or "opaque_snapshot"))
                continue
            # Raw-domain keys are required for unsafe names.  A safe display
            # path remains a compatibility convenience for external callers.
            supplied = sources.get(entry.source_key)
            if supplied is None and _artifact_path(entry) == entry.path:
                supplied = sources.get(entry.path)
            if supplied is None:
                failures.setdefault(entry.source_key, "source_bytes_unavailable")
                continue
            raw = supplied.encode("utf-8") if isinstance(supplied, str) else supplied
            if type(raw) is not bytes:
                raise RepositoryScannerError("source values must be str or bytes")
            if cid_for_bytes(raw) != entry.source_cid:
                failures.setdefault(entry.source_key, "source_cid_mismatch")
                continue
            verified[entry.source_key] = raw

        for key in sorted(failures):
            entry = entries_by_key.get(key)
            if entry is not None:
                artifacts.append(_opaque_artifact(entry, failures[key]))

        python = PythonSemanticAnalyzer(repository_id=snapshot.repository_id, namespace=self.namespace)
        pytest = PytestAnalyzer(repository_id=snapshot.repository_id, namespace="pytest")
        pytest_sources: dict[str, bytes] = {}
        for key, raw in sorted(verified.items()):
            entry = entries_by_key[key]
            path = entry.path
            if _artifact_path(entry) != entry.path:
                artifacts.append(_opaque_artifact(entry, "raw_path_not_model_safe"))
                continue
            if entry.kind == "python":
                reused = False
                if accepted_previous is not None and entry.source_cid is not None:
                    prior_symbols = _reusable_path_symbols(
                        accepted_previous, path, entry.source_cid,
                    )
                    if prior_symbols is not None:
                        symbols.extend(prior_symbols)
                        edges.extend(_reusable_path_edges(
                            accepted_previous, {item.stable_id for item in prior_symbols},
                        ))
                        reused_paths.append(path)
                        reused_symbol_ids.extend(item.stable_id for item in prior_symbols)
                        reused = True
                    else:
                        prior_opaque = _reusable_opaque_python_artifact(
                            accepted_previous, path, entry.source_cid,
                        )
                        if prior_opaque is not None:
                            artifacts.append(prior_opaque)
                            reused_paths.append(path)
                            reused_artifact_paths.append(path)
                            reused = True
                if not reused:
                    analysis = python.analyze(raw, path)
                    analyzed_paths.append(path)
                    if analysis.diagnostics:
                        artifacts.append(ArtifactRecord(
                            _artifact_id(path), "python-analysis", path, entry.source_cid, "opaque",
                            {"diagnostics": list(analysis.diagnostics)},
                        ))
                    else:
                        for fact in analysis.symbols:
                            record = fact.symbol
                            cached = previous_by_key.get(
                                (record.stable_id, record.source_cid or "", record.version_cid),
                                record,
                            )
                            symbols.append(cached)
                            edges.extend(fact.edges)
                            recomputed_symbol_ids.append(cached.stable_id)
                pytest_sources[path] = raw
            elif entry.kind == "pytest-config":
                pytest_sources[path] = raw
            else:
                artifacts.append(_typed_artifact(entry))

        pytest_analysis = pytest.analyze_files(pytest_sources)
        # Configuration artifacts are richer than a generic artifact; Python
        # sources stay represented by their module symbol instead.
        artifacts.extend(pytest_analysis.artifacts)

        symbols, edges, _remap = unify_pytest_identities(
            symbols, edges,
            pytest_analysis.tests, pytest_analysis.fixtures, pytest_analysis.edges,
            repository_id=snapshot.repository_id, namespace=self.namespace,
        )

        # Explicit lock/dependency artifacts configure test receipts.
        edges.extend(_lock_configuration_edges(symbols, artifacts))

        # Resolution must run before state-root computation so the public
        # state commits stable symbol CIDs for resolvable call targets.
        # Dependent resolution always recomputes even when file analysis reused.
        graph = build_symbol_graph(symbols, artifacts, edges)
        # Prefer previously verified records only when identities still match.
        final_symbols: list[SymbolRecord] = []
        for record in graph.symbols:
            cached = previous_by_key.get(
                (record.stable_id, record.source_cid or "", record.version_cid)
            )
            final_symbols.append(cached if cached is not None else record)

        self.last_reuse_diagnostics = ScanReuseDiagnostics(
            previous_state_accepted=accepted_previous is not None,
            reject_reason=reject_reason,
            reused_paths=tuple(sorted(set(reused_paths))),
            analyzed_paths=tuple(sorted(set(analyzed_paths))),
            reused_symbol_ids=tuple(sorted(set(reused_symbol_ids))),
            recomputed_symbol_ids=tuple(sorted(set(recomputed_symbol_ids))),
            reused_artifact_paths=tuple(sorted(set(reused_artifact_paths))),
            resolution_recomputed=True,
        )

        return RepositoryState(
            snapshot.repository_id,
            final_symbols,
            graph.artifacts,
            graph.edges,
            self.extractor_name,
            self.extractor_version,
        )


def scan_repository_state(
    repository: str | os.PathLike[str],
    *,
    repository_id: str | None = None,
    namespace: str | None = None,
    previous_state: RepositoryState | None = None,
    exclusions: Iterable[str] | None = None,
) -> RepositoryState:
    """Convenience entry point for a cold or incremental repository scan."""
    return RepositoryScanner(
        repository_id=repository_id, namespace=namespace, exclusions=exclusions,
    ).scan(repository, previous_state=previous_state)


__all__ = [
    "SCANNER_NAME",
    "SCANNER_VERSION",
    "SCAN_REUSE_DIAGNOSTICS_SCHEMA",
    "ScanReuseDiagnostics",
    "RepositoryScanner",
    "RepositoryScannerError",
    "scan_repository_state",
    "unify_pytest_identities",
]
