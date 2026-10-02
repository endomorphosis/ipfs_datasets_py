"""Snapshot-bound structural codebase IR and bounded repository preparation.

This first profile composes the existing snapshot, semantic index, AST catalog
and immutable CAS. It has structural authority only: neither parsing nor a
stored manifest establishes a behavioral property or a proof. Preparation uses
shared resource admission by default and never imports the repository it scans.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ipfs_datasets_py.duckdb_control.codebase_catalog import (
        CodebaseCatalog, CodebaseHead, CodebasePublicationReceipt,
    )

from .cache import ImmutableCAS
from .ast_ir import ASTRecord
from .content import cid_for_structured, validate_cid
from .duckdb_ast_store import ASTCatalogProjection
from .duckdb_ingest import DuckDBASTIngestor
from .semantic_index.models import RepositoryState
from .semantic_index.scanner import RepositoryScanner
from .semantic_index.snapshot import RepositorySnapshot, snapshot_repository

CODEBASE_IR_SCHEMA = "codebase-ir-structural-manifest@1"
CODEBASE_UNIT_SCHEMA = "codebase-ir-structural-unit@1"
_UNIT_FIELDS = frozenset({
    "schema", "source_key", "entry_cid", "ast_cid", "parse_status",
})
_MANIFEST_FIELDS = frozenset({
    "schema", "authority", "snapshot", "semantic_state", "ast_revision_id",
    "units", "coverage",
})


class CodebaseIRError(ValueError):
    """A codebase artifact has invalid or unavailable source/index bindings."""


class StaleCodebaseError(CodebaseIRError):
    """A recorded structural head no longer matches the catalog or source."""


@dataclass(frozen=True, slots=True)
class CodebaseScanLimits:
    """Small-repository profile; bounds are cooperative, not an RSS guarantee."""

    max_entries: int = 256
    max_file_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        for name in ("max_entries", "max_file_bytes"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise CodebaseIRError(f"{name} must be a positive exact integer")

    def validate_reservation(self, memory_mb: int) -> None:
        if type(memory_mb) is not int or memory_mb <= 0:
            raise CodebaseIRError("memory_mb must be a positive exact integer")
        # Account for simultaneous captured bytes, parser/semantic structures,
        # serialization and database work. This is an admission estimate only.
        if self.max_entries * self.max_file_bytes > memory_mb * 1024 * 1024 // 16:
            raise CodebaseIRError("source bounds exceed the preparation memory envelope")


@dataclass(frozen=True, slots=True)
class CodebaseUnit:
    source_key: str
    entry_cid: str
    ast_cid: str | None
    parse_status: str

    def __post_init__(self) -> None:
        if type(self.source_key) is not str or not self.source_key.startswith("raw:"):
            raise CodebaseIRError("source_key must identify a captured raw path")
        validate_cid(self.entry_cid, codecs={"dag-json"})
        if self.ast_cid is not None:
            validate_cid(self.ast_cid, codecs={"dag-json"})
        if self.parse_status not in {"ok", "partial", "failed", "opaque", "unindexed"}:
            raise CodebaseIRError("unsupported structural parse status")
        if (self.ast_cid is None) != (self.parse_status in {"opaque", "unindexed"}):
            raise CodebaseIRError("AST identity and parse status disagree")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": CODEBASE_UNIT_SCHEMA, "source_key": self.source_key,
                "entry_cid": self.entry_cid, "ast_cid": self.ast_cid,
                "parse_status": self.parse_status}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CodebaseUnit:
        if not isinstance(value, Mapping) or set(value) != _UNIT_FIELDS:
            raise CodebaseIRError("invalid codebase unit fields")
        if value["schema"] != CODEBASE_UNIT_SCHEMA:
            raise CodebaseIRError("unsupported codebase unit schema")
        return cls(**{key: value[key] for key in _UNIT_FIELDS - {"schema"}})


@dataclass(frozen=True, slots=True)
class CodebaseIRManifest:
    """Complete admitted inventory with source-bound structural projections."""

    snapshot: RepositorySnapshot
    semantic_state: RepositoryState
    ast_revision_id: str
    units: Sequence[CodebaseUnit]

    def __post_init__(self) -> None:
        if type(self.snapshot) is not RepositorySnapshot or type(self.semantic_state) is not RepositoryState:
            raise CodebaseIRError("manifest requires canonical snapshot and semantic state")
        if self.semantic_state.repository_id != self.snapshot.repository_id:
            raise CodebaseIRError("semantic state belongs to another repository")
        evidence = [item for item in self.semantic_state.artifacts
                    if item.artifact_id == "artifact:snapshot-evidence"]
        if len(evidence) != 1 or evidence[0].source_cid != self.snapshot.snapshot_cid:
            raise CodebaseIRError("semantic state is not bound to this snapshot")
        if evidence[0].to_dict()["metadata"].get("snapshot") != self.snapshot.to_dict():
            raise CodebaseIRError("semantic snapshot evidence does not match")
        by_path = {entry.path: entry for entry in self.snapshot.entries}
        by_raw = {entry.raw_path_hex: entry for entry in self.snapshot.entries}
        for symbol in self.semantic_state.symbols:
            entry = by_path.get(symbol.module_path)
            if entry is None or entry.is_opaque or symbol.source_cid != entry.source_cid:
                raise CodebaseIRError("semantic symbol is not bound to captured source")
        for artifact in self.semantic_state.artifacts:
            if artifact.artifact_id == "artifact:snapshot-evidence" or artifact.source_cid is None:
                continue
            entry = by_path.get(artifact.path)
            if entry is None and artifact.kind == "opaque":
                entry = by_raw.get(artifact.metadata.get("raw_path_hex"))
            if entry is None or artifact.source_cid != entry.source_cid:
                raise CodebaseIRError("semantic artifact is not bound to captured source")
        expected_revision = f"rev:{self.snapshot.repository_id}:snapshot:{self.snapshot.snapshot_cid}"
        if self.ast_revision_id != expected_revision:
            raise CodebaseIRError("AST revision does not bind the captured snapshot")
        units = tuple(self.units)
        if any(type(unit) is not CodebaseUnit for unit in units):
            raise CodebaseIRError("units must be canonical CodebaseUnit records")
        by_key = {unit.source_key: unit for unit in units}
        entries = {entry.source_key: entry for entry in self.snapshot.entries}
        if len(by_key) != len(units) or set(by_key) != set(entries):
            raise CodebaseIRError("units must account for the entire snapshot exactly once")
        for key, entry in entries.items():
            unit = by_key[key]
            if unit.entry_cid != entry.entry_cid:
                raise CodebaseIRError("unit does not bind its exact snapshot entry")
            if (unit.parse_status == "opaque") != entry.is_opaque:
                raise CodebaseIRError("opaque entry cannot acquire an AST projection")
        object.__setattr__(self, "units", tuple(sorted(units, key=lambda unit: unit.source_key)))

    @property
    def coverage(self) -> dict[str, int]:
        return {
            "inventory_entries": len(self.units),
            "captured_entries": sum(not entry.is_opaque for entry in self.snapshot.entries),
            "ast_ok": sum(unit.parse_status == "ok" for unit in self.units),
            "ast_partial": sum(unit.parse_status == "partial" for unit in self.units),
            "ast_failed": sum(unit.parse_status == "failed" for unit in self.units),
            "opaque_entries": sum(unit.parse_status == "opaque" for unit in self.units),
            "unindexed_entries": sum(unit.parse_status == "unindexed" for unit in self.units),
            "semantic_symbols": len(self.semantic_state.symbols),
            "formalized_properties": 0,
            "checked_properties": 0,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"schema": CODEBASE_IR_SCHEMA, "authority": "structural_only",
                "snapshot": self.snapshot.to_dict(),
                "semantic_state": self.semantic_state.to_dict(),
                "ast_revision_id": self.ast_revision_id,
                "units": [unit.to_dict() for unit in self.units],
                "coverage": self.coverage}

    @property
    def cid(self) -> str:
        return cid_for_structured(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CodebaseIRManifest:
        if not isinstance(value, Mapping) or set(value) != _MANIFEST_FIELDS:
            raise CodebaseIRError("invalid codebase manifest fields")
        if value["schema"] != CODEBASE_IR_SCHEMA or value["authority"] != "structural_only":
            raise CodebaseIRError("unsupported codebase manifest schema or authority")
        result = cls(RepositorySnapshot.from_dict(value["snapshot"]),
                     RepositoryState.from_dict(value["semantic_state"]),
                     value["ast_revision_id"],
                     tuple(CodebaseUnit.from_dict(unit) for unit in value["units"]))
        if value["coverage"] != result.coverage:
            raise CodebaseIRError("coverage does not recompute from the complete inventory")
        return result


@dataclass(frozen=True, slots=True)
class CodebaseObservation:
    """Point-in-time structural observation, without behavioral authority.

    This record does not lock a checkout against later edits. Consumers must
    reobserve it at their completion/admission boundary.
    """

    head: CodebaseHead
    manifest: CodebaseIRManifest


class RepositoryCodebaseIndex:
    """Explicit preparation API; reads never train, infer or scan a live tree.

    Inject an owner-managed DuckDBASTIngestor and ImmutableCAS for durable use.
    Without a catalog, preparation returns historical manifests. Inject the
    native codebase catalog to publish an expected-head transition; that path
    owns both the structural head and AST projection in one SQL transaction.
    """

    def __init__(self, *, ingestor: DuckDBASTIngestor | None = None,
                 artifacts: ImmutableCAS | None = None,
                 catalog: CodebaseCatalog | None = None) -> None:
        self.ingestor = ingestor if ingestor is not None else DuckDBASTIngestor()
        self.artifacts = artifacts
        if catalog is not None:
            from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
            if (type(catalog) is not CodebaseCatalog or catalog.store is not self.ingestor.store
                    or catalog.artifacts is not artifacts):
                raise CodebaseIRError("catalog must share the exact AST store and artifact owner")
        self.catalog = catalog

    def prepare(
        self, repository: str | Path, *, repository_id: str | None = None,
        previous: CodebaseIRManifest | None = None,
        limits: CodebaseScanLimits | None = None,
        exclusions: Sequence[str] | None = None,
        scheduler: Any = None, parent_lease: Any = None, cancel_event: Any = None,
        admission_timeout_seconds: float = 30.0, timeout_seconds: float = 120.0,
        memory_mb: int = 512,
    ) -> CodebaseIRManifest:
        """Prepare a historical structural manifest without changing a catalog head."""
        if self.catalog is not None:
            raise CodebaseIRError("catalog-owned indexes require prepare_current with an expected head")
        return self._prepare(
            repository, repository_id=repository_id, previous=previous,
            limits=limits, exclusions=exclusions, scheduler=scheduler,
            parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds,
            timeout_seconds=timeout_seconds, memory_mb=memory_mb,
        )

    def prepare_current(
        self, repository: str | Path, *, repository_id: str,
        operation_id: str, expected_head: CodebaseHead | None,
        limits: CodebaseScanLimits | None = None,
        exclusions: Sequence[str] | None = None,
        scheduler: Any = None, parent_lease: Any = None, cancel_event: Any = None,
        admission_timeout_seconds: float = 30.0, timeout_seconds: float = 120.0,
        memory_mb: int = 512,
    ) -> CodebasePublicationReceipt:
        """Atomically publish a structural head and its complete AST projection.

        ``repository_id`` explicitly names one repository view. Use distinct IDs
        for independent worktrees. Exact operation retries return the original
        receipt, which can be historical if a successor was already published.
        Use ``observe_current`` before treating a receipt as current evidence.
        """
        from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
        if self.catalog is None or self.artifacts is None:
            raise CodebaseIRError("current publication requires a durable catalog and artifacts")
        if type(repository_id) is not str or not repository_id or repository_id != repository_id.strip():
            raise CodebaseIRError("repository_id must explicitly identify a repository view")
        if expected_head is not None and (
            type(expected_head) is not CodebaseHead or expected_head.repository_id != repository_id
        ):
            raise CodebaseIRError("expected head belongs to another repository view")
        receipts = []

        def publish(manifest: CodebaseIRManifest, publication: Any, checkpoint: Any) -> None:
            # Reobserve after extraction/artifact work. This is a source fence,
            # not a filesystem lock: consumers must also check when using it.
            checkpoint()
            captured = manifest.snapshot
            observed = snapshot_repository(
                repository, repository_id=repository_id,
                max_file_bytes=captured.max_file_bytes, max_entries=captured.max_entries,
                exclusions=captured.exclusions,
            )
            checkpoint()
            if observed.snapshot_cid != captured.snapshot_cid:
                raise StaleCodebaseError("repository changed before head publication")
            # Only the durable owner may derive prior-generation invalidation.
            # The ingestor's optional process-local history is not authoritative.
            receipts.append(self.catalog.publish(
                operation_id=operation_id, manifest=manifest, expected_head=expected_head,
                projections=publication.projections, checkpoint=checkpoint,
            ))

        self._prepare(
            repository, repository_id=repository_id, limits=limits, exclusions=exclusions,
            scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds,
            timeout_seconds=timeout_seconds, memory_mb=memory_mb, publisher=publish,
        )
        if len(receipts) != 1:
            raise CodebaseIRError("catalog did not return exactly one publication receipt")
        return receipts[0]

    def _prepare(
        self, repository: str | Path, *, repository_id: str | None = None,
        previous: CodebaseIRManifest | None = None,
        limits: CodebaseScanLimits | None = None,
        exclusions: Sequence[str] | None = None,
        scheduler: Any = None, parent_lease: Any = None, cancel_event: Any = None,
        admission_timeout_seconds: float = 30.0, timeout_seconds: float = 120.0,
        memory_mb: int = 512, publisher: Any = None,
    ) -> CodebaseIRManifest:
        """Capture, extract, persist and return an exact structural manifest.

        Deadlines/cancellation are checked between stages and ingestion files;
        active Python extraction and Git commands are not forcibly preempted.
        Database threads/memory/temp-space remain the injected owner's policy.
        Prior manifests check repository lineage. Their semantic facts are
        re-extracted: content identity alone does not authenticate a producer.
        Parser-context-bound AST shards retain their own incremental reuse.
        """
        from .codebase_resources import acquire_codebase_resources
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
            LeaseCancelledError, LeaseTimeoutError,
        )

        bounds = limits if limits is not None else CodebaseScanLimits()
        if type(bounds) is not CodebaseScanLimits:
            raise CodebaseIRError("limits must be CodebaseScanLimits")
        bounds.validate_reservation(memory_mb)
        if type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise CodebaseIRError("timeout_seconds must be finite and positive")
        if type(admission_timeout_seconds) not in {int, float} or not math.isfinite(admission_timeout_seconds) or admission_timeout_seconds < 0:
            raise CodebaseIRError("admission_timeout_seconds must be finite and nonnegative")
        if previous is not None and type(previous) is not CodebaseIRManifest:
            raise CodebaseIRError("previous must be a CodebaseIRManifest")
        deadline = time.monotonic() + timeout_seconds
        with acquire_codebase_resources(
            scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            timeout_seconds=min(admission_timeout_seconds, timeout_seconds), memory_mb=memory_mb,
        ) as lease:
            cancelled = lease.combined_cancellation_signal(cancel_event)

            def checkpoint() -> None:
                if cancelled.is_set():
                    raise LeaseCancelledError("codebase preparation cancelled")
                if time.monotonic() >= deadline:
                    raise LeaseTimeoutError("codebase preparation deadline exceeded")

            checkpoint()
            snapshot = snapshot_repository(
                repository, repository_id=repository_id,
                max_file_bytes=bounds.max_file_bytes, max_entries=bounds.max_entries,
                exclusions=exclusions,
            )
            checkpoint()
            if previous is not None and previous.snapshot.repository_id != snapshot.repository_id:
                raise CodebaseIRError("previous manifest belongs to another repository")
            sources = {entry.source_key: entry.captured_bytes for entry in snapshot.entries
                       if not entry.is_opaque and entry.captured_bytes is not None}
            state = RepositoryScanner(repository_id=snapshot.repository_id).scan_snapshot(
                snapshot, sources,
            )
            checkpoint()
            # Seal input bytes first. Failed preparation can leave immutable,
            # unreferenced CAS objects, but never returns a partial manifest.
            if self.artifacts is not None:
                for raw in sources.values():
                    checkpoint()
                    self.artifacts.put_bytes(raw)
            prepared: list[CodebaseIRManifest] = []

            def seal_manifest(publication: Any) -> None:
                checkpoint()
                projections = {item.source_file.path: item for item in publication.projections}
                units = []
                for entry in snapshot.entries:
                    projection = projections.get(entry.path)
                    units.append(CodebaseUnit(
                        entry.source_key, entry.entry_cid,
                        None if projection is None else projection.ast_cid,
                        "opaque" if entry.is_opaque else "unindexed" if projection is None
                        else projection.ast_blob.parse_status,
                    ))
                manifest = CodebaseIRManifest(snapshot, state, publication.revision_id, tuple(units))
                if self.artifacts is not None:
                    for projection in publication.projections:
                        checkpoint()
                        body_cid = self.artifacts.put(json.loads(projection.ast_blob.payload_json))
                        if body_cid != projection.ast_cid:
                            raise CodebaseIRError("AST artifact identity does not verify")
                    self.artifacts.put(manifest.to_dict())
                checkpoint()
                prepared.append(manifest)

            # Seal the immutable manifest before the AST transaction. A failed
            # CAS write cannot invalidate the previous active AST generation.
            # A later SQL failure may leave an orphan manifest; loading a
            # manifest alone never asserts that its SQL projections are active.
            self.ingestor.ingest_snapshot(
                snapshot, checkpoint=checkpoint, before_publish=seal_manifest,
                publish_batch=(None if publisher is None else
                               lambda publication: publisher(prepared[0], publication, checkpoint)),
            )
            checkpoint()
            if len(prepared) != 1:
                raise CodebaseIRError("ingestor did not prepare exactly one manifest")
            manifest = prepared[0]
            return manifest

    def current(self, repository_id: str) -> CodebaseHead | None:
        """Read the durable head; this does not inspect current source bytes."""
        if self.catalog is None:
            raise CodebaseIRError("current lookup requires a durable catalog")
        return self.catalog.current(repository_id)

    def observe_current(
        self, repository: str | Path, *, expected_head: CodebaseHead,
        scheduler: Any = None, parent_lease: Any = None, cancel_event: Any = None,
        admission_timeout_seconds: float = 30.0, timeout_seconds: float = 120.0,
        memory_mb: int = 512,
    ) -> CodebaseObservation:
        """Verify head, immutable evidence, active ASTs and current admitted bytes.

        Uses the manifest's exact capture profile under default shared admission.
        No parsing, inference, training or SQL mutation occurs. Opaque entries
        remain unknown; excluded source remains outside the observation scope.
        """
        from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
        from .codebase_resources import acquire_codebase_resources
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
            LeaseCancelledError, LeaseTimeoutError,
        )
        if type(expected_head) is not CodebaseHead or self.catalog is None or self.artifacts is None:
            raise CodebaseIRError("observation requires a catalog head and artifact owner")
        if type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise CodebaseIRError("timeout_seconds must be finite and positive")
        if type(admission_timeout_seconds) not in {int, float} or not math.isfinite(admission_timeout_seconds) or admission_timeout_seconds < 0:
            raise CodebaseIRError("admission_timeout_seconds must be finite and nonnegative")
        deadline = time.monotonic() + timeout_seconds
        with acquire_codebase_resources(
            scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            timeout_seconds=min(admission_timeout_seconds, timeout_seconds), memory_mb=memory_mb,
        ) as lease:
            cancelled = lease.combined_cancellation_signal(cancel_event)

            def checkpoint() -> None:
                if cancelled.is_set():
                    raise LeaseCancelledError("codebase observation cancelled")
                if time.monotonic() >= deadline:
                    raise LeaseTimeoutError("codebase observation deadline exceeded")

            def require_head() -> None:
                if self.current(expected_head.repository_id) != expected_head:
                    raise StaleCodebaseError("catalog head changed")

            checkpoint()
            require_head()
            manifest = self.load(expected_head.manifest_cid)
            if (manifest.snapshot.repository_id != expected_head.repository_id
                    or manifest.snapshot.snapshot_cid != expected_head.snapshot_cid
                    or manifest.ast_revision_id != expected_head.ast_revision_id):
                raise CodebaseIRError("catalog head does not bind its manifest")
            captured = manifest.snapshot
            CodebaseScanLimits(captured.max_entries, captured.max_file_bytes).validate_reservation(memory_mb)
            for entry in captured.entries:
                checkpoint()
                if not entry.is_opaque:
                    self.artifacts.get_bytes(entry.source_cid)
                self.lookup(manifest, entry.path)
                self.load_ast_artifact(manifest, entry.path)
            checkpoint()
            observed = snapshot_repository(
                repository, repository_id=expected_head.repository_id,
                max_file_bytes=captured.max_file_bytes, max_entries=captured.max_entries,
                exclusions=captured.exclusions,
            )
            checkpoint()
            if observed.snapshot_cid != captured.snapshot_cid:
                raise StaleCodebaseError("current repository differs from the published snapshot")
            require_head()
            checkpoint()
            return CodebaseObservation(expected_head, manifest)

    def load(self, manifest_cid: str) -> CodebaseIRManifest:
        if self.artifacts is None:
            raise CodebaseIRError("loading a manifest requires an immutable artifact store")
        value = self.artifacts.get(manifest_cid, expected_schema=CODEBASE_IR_SCHEMA)
        manifest = CodebaseIRManifest.from_dict(value)
        if manifest.cid != manifest_cid:
            raise CodebaseIRError("manifest identity does not verify")
        return manifest

    def lookup(self, manifest: CodebaseIRManifest, path: str) -> ASTCatalogProjection | None:
        """Return an exact active AST projection; missing expected evidence fails."""
        entry = next((item for item in manifest.snapshot.entries if item.path == path), None)
        if entry is None:
            raise CodebaseIRError("path is outside the captured inventory")
        unit = next(item for item in manifest.units if item.source_key == entry.source_key)
        if unit.ast_cid is None:
            return None
        found = self.ingestor.store.get_by_ast_cid(unit.ast_cid)
        if found is None:
            raise CodebaseIRError("AST projection is missing or invalidated")
        if (found.source_cid != entry.source_cid or found.source_file.path != path
                or found.source_revision.revision_id != manifest.ast_revision_id
                or found.ast_blob.parse_status != unit.parse_status):
            raise CodebaseIRError("AST projection does not match the manifest")
        return found

    def load_ast_artifact(self, manifest: CodebaseIRManifest, path: str) -> ASTRecord | None:
        """Read immutable AST history without asserting active index eligibility."""
        if self.artifacts is None:
            raise CodebaseIRError("reading an AST artifact requires an immutable artifact store")
        entry = next((item for item in manifest.snapshot.entries if item.path == path), None)
        if entry is None:
            raise CodebaseIRError("path is outside the captured inventory")
        unit = next(item for item in manifest.units if item.source_key == entry.source_key)
        if unit.ast_cid is None:
            return None
        record = ASTRecord.from_dict(self.artifacts.get(unit.ast_cid))
        provenance = record.provenance
        if (provenance.source_cid != entry.source_cid or provenance.path != path
                or provenance.repository_id != manifest.snapshot.repository_id
                or provenance.revision != "snapshot:" + manifest.snapshot.snapshot_cid
                or provenance.repository_tree_cid != manifest.snapshot.snapshot_cid):
            raise CodebaseIRError("AST artifact does not match the manifest")
        return record


__all__ = ["CODEBASE_IR_SCHEMA", "CodebaseIRError", "StaleCodebaseError", "CodebaseScanLimits",
           "CodebaseUnit", "CodebaseIRManifest", "CodebaseObservation", "RepositoryCodebaseIndex"]
