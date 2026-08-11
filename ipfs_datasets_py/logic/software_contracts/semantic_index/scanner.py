"""Deterministic assembly of a repository's pre-resolution semantic state.

The scanner is intentionally a thin coordinator: snapshots decide which bytes
are inputs, and the Python/pytest frontends decide what those bytes mean.  It
never imports target modules.  In particular, ``previous_state`` is only an
optional record-reuse cache; all output is still derived from the current,
CID-verified snapshot inputs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import symbol_version_cid
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    ArtifactRecord,
    RepositoryState,
    SymbolKind,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.python_analysis import (
    PythonSemanticAnalyzer,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.pytest_analysis import PytestAnalyzer
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import (
    RepositorySnapshot,
    SnapshotEntry,
    snapshot_repository,
)


SCANNER_NAME = "semantic-repository-scanner"
SCANNER_VERSION = "1"


class RepositoryScannerError(ValueError):
    """Raised for invalid scanner inputs rather than silently changing scope."""


def _artifact_id(path: str) -> str:
    return "artifact:" + path


def _opaque_artifact(entry: SnapshotEntry, reason: str, *, source_cid: str | None = None) -> ArtifactRecord:
    return ArtifactRecord(
        _artifact_id(entry.path), "opaque", entry.path,
        entry.source_cid if source_cid is None else source_cid,
        AnalysisConfidence.OPAQUE,
        {"snapshot_kind": entry.kind, "opaque_reason": reason},
    )


def _typed_artifact(entry: SnapshotEntry) -> ArtifactRecord:
    return ArtifactRecord(
        _artifact_id(entry.path), entry.kind, entry.path, entry.source_cid,
        AnalysisConfidence.EXACT, {"snapshot_kind": entry.kind},
    )


@dataclass(slots=True)
class RepositoryScanner:
    """Build a deterministic :class:`RepositoryState` without target execution."""

    repository_id: str | None = None
    namespace: str | None = None
    extractor_name: str = SCANNER_NAME
    extractor_version: str = SCANNER_VERSION

    def scan(
        self,
        repository: str | os.PathLike[str],
        *,
        previous_state: RepositoryState | None = None,
        snapshot: RepositorySnapshot | None = None,
    ) -> RepositoryState:
        current = snapshot or snapshot_repository(repository, repository_id=self.repository_id)
        if self.repository_id is not None and current.repository_id != self.repository_id:
            raise RepositoryScannerError("snapshot repository_id does not match scanner repository_id")
        sources: dict[str, bytes] = {}
        unavailable: dict[str, str] = {}
        for entry in current.entries:
            if entry.is_opaque or entry.source_cid is None:
                continue
            # Snapshot acquisition owns the sole content-byte read.  A scanner
            # gets only that immutable capture, so filters and path mutation
            # cannot cause parse bytes to diverge from manifest evidence.
            data = entry.captured_bytes
            if data is None:
                unavailable[entry.path] = "captured_source_unavailable"
            elif cid_for_bytes(data) != entry.source_cid:
                unavailable[entry.path] = "source_cid_mismatch"
            else:
                sources[entry.path] = data
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
        """
        if not isinstance(snapshot, RepositorySnapshot):
            raise RepositoryScannerError("snapshot must be a RepositorySnapshot")
        if self.repository_id is not None and snapshot.repository_id != self.repository_id:
            raise RepositoryScannerError("snapshot repository_id does not match scanner repository_id")
        previous_by_key: dict[tuple[str, str, str], SymbolRecord] = {}
        if previous_state is not None:
            if not isinstance(previous_state, RepositoryState):
                raise RepositoryScannerError("previous_state must be a RepositoryState")
            if previous_state.repository_id != snapshot.repository_id:
                raise RepositoryScannerError("previous_state repository_id does not match snapshot")
            previous_by_key = {(item.stable_id, item.source_cid or "", item.version_cid): item for item in previous_state.symbols}

        artifacts: list[ArtifactRecord] = []
        symbols: list[SymbolRecord] = []
        edges = []
        verified: dict[str, bytes] = {}
        failures = dict(unavailable or {})
        entries_by_path = {entry.path: entry for entry in snapshot.entries}
        # Bind the durable state root to the exact acquisition evidence,
        # including commit/tree and each Git blob OID.  This deliberately is
        # an artifact rather than a mutable side channel in RepositoryState.
        artifacts.append(ArtifactRecord(
            "artifact:@snapshot-evidence", "snapshot-evidence", "@snapshot-evidence", None,
            AnalysisConfidence.EXACT, snapshot.identity_payload(),
        ))
        for entry in snapshot.entries:
            if entry.is_opaque:
                artifacts.append(_opaque_artifact(entry, entry.opaque_reason or "opaque_snapshot"))
                continue
            supplied = sources.get(entry.path)
            if supplied is None:
                failures.setdefault(entry.path, "source_bytes_unavailable")
                continue
            raw = supplied.encode("utf-8") if isinstance(supplied, str) else supplied
            if type(raw) is not bytes:
                raise RepositoryScannerError("source values must be str or bytes")
            if cid_for_bytes(raw) != entry.source_cid:
                failures.setdefault(entry.path, "source_cid_mismatch")
                continue
            verified[entry.path] = raw

        for path in sorted(failures):
            entry = entries_by_path.get(path)
            if entry is not None:
                artifacts.append(_opaque_artifact(entry, failures[path]))

        python = PythonSemanticAnalyzer(repository_id=snapshot.repository_id, namespace=self.namespace)
        pytest = PytestAnalyzer(repository_id=snapshot.repository_id, namespace="pytest")
        pytest_sources: dict[str, bytes] = {}
        for path, raw in sorted(verified.items()):
            entry = entries_by_path[path]
            if entry.kind == "python":
                analysis = python.analyze(raw, path)
                if analysis.diagnostics:
                    artifacts.append(ArtifactRecord(_artifact_id(path), "python-analysis", path, entry.source_cid, "opaque", {"diagnostics": list(analysis.diagnostics)}))
                else:
                    for fact in analysis.symbols:
                        record = fact.symbol
                        symbols.append(previous_by_key.get((record.stable_id, record.source_cid or "", record.version_cid), record))
                        edges.extend(fact.edges)
                pytest_sources[path] = raw
            elif entry.kind == "pytest-config":
                pytest_sources[path] = raw
            else:
                artifacts.append(_typed_artifact(entry))

        pytest_analysis = pytest.analyze_files(pytest_sources)
        # Configuration artifacts are richer than a generic artifact; Python
        # sources stay represented by their module symbol instead.
        artifacts.extend(pytest_analysis.artifacts)
        for facts, kind in ((item, SymbolKind.TEST) for item in pytest_analysis.tests):
            symbols.append(self._pytest_symbol(facts, kind, snapshot.repository_id))
        for facts, kind in ((item, SymbolKind.FIXTURE) for item in pytest_analysis.fixtures):
            symbols.append(self._pytest_symbol(facts, kind, snapshot.repository_id))
        edges.extend(pytest_analysis.edges)

        # A Python file that pytest inspected but which had no configuration
        # remains represented by its module; config artifacts are deliberately
        # emitted by the pytest frontend only, avoiding duplicate IDs.
        return RepositoryState(snapshot.repository_id, symbols, artifacts, edges, self.extractor_name, self.extractor_version)

    def _pytest_symbol(self, facts: object, kind: SymbolKind, repository_id: str) -> SymbolRecord:
        payload = {
            "qualified_name": facts.qualified_name, "fixture_parameters": list(getattr(facts, "fixture_parameters", ())),
            "usefixtures": list(getattr(facts, "usefixtures", ())), "markers": list(getattr(facts, "markers", ())),
            "dependencies": list(getattr(facts, "dependencies", ())), "name": getattr(facts, "name", None),
        }
        stable_id = facts.symbol_id
        version = symbol_version_cid(stable_id, payload, extractor_name="pytest-static-ast", extractor_version="1")
        return SymbolRecord(stable_id, version, repository_id, "python", facts.path, facts.qualified_name, kind, "pytest", facts.source_cid, facts.span, facts.confidence, {}, (), {}, {"pytest": payload})


def scan_repository_state(
    repository: str | os.PathLike[str],
    *,
    repository_id: str | None = None,
    namespace: str | None = None,
    previous_state: RepositoryState | None = None,
) -> RepositoryState:
    """Convenience entry point for a cold or incremental repository scan."""
    return RepositoryScanner(repository_id=repository_id, namespace=namespace).scan(repository, previous_state=previous_state)


__all__ = ["SCANNER_NAME", "SCANNER_VERSION", "RepositoryScanner", "RepositoryScannerError", "scan_repository_state"]
