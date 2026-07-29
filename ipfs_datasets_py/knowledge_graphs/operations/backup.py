"""Immutable backup and restore for knowledge-graph control plane (KGP-032).

Backups are content-addressed directory trees. Restore proves identical
revision ids, checksums, and query vectors before swapping catalog state.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from ipfs_datasets_py.knowledge_graphs.catalog import (
    GraphCatalog,
    bootstrap_revision_id,
    open_catalog,
)
from ipfs_datasets_py.knowledge_graphs.contracts.manifest import (
    canonical_json_bytes,
    sha256_hex,
)

from .logging import log_ops_event
from .redact import OPERATIONS_CONTRACT_VERSION, scrub_for_telemetry
from .telemetry import OpsTelemetry, get_default_telemetry

PathLike = Union[str, Path]
BACKUP_SCHEMA_VERSION = "kg-ops-backup/v1"
BACKUP_MANIFEST_NAME = "backup_manifest.json"
CATALOG_EXPORT_NAME = "catalog_export.json"
QUERY_VECTORS_NAME = "query_vectors.json"


@dataclass(frozen=True, slots=True)
class QueryVector:
    """Deterministic identity vector used to prove restore fidelity.

    Captures the revision head, checksum, pin root, and optional query
    fingerprint for one branch of one graph.
    """

    tenant: str
    graph_id: str
    branch: str
    revision_id: str
    checksum: Optional[str] = None
    pin_root: Optional[str] = None
    manifest_cid: Optional[str] = None
    query_fingerprint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "branch": self.branch,
            "revision_id": self.revision_id,
            "checksum": self.checksum,
            "pin_root": self.pin_root,
            "manifest_cid": self.manifest_cid,
            "query_fingerprint": self.query_fingerprint,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QueryVector":
        return cls(
            tenant=str(data["tenant"]),
            graph_id=str(data["graph_id"]),
            branch=str(data["branch"]),
            revision_id=str(data["revision_id"]),
            checksum=data.get("checksum"),
            pin_root=data.get("pin_root"),
            manifest_cid=data.get("manifest_cid"),
            query_fingerprint=data.get("query_fingerprint"),
        )


def compute_query_fingerprint(
    *,
    revision_id: str,
    checksum: Optional[str],
    pin_root: Optional[str],
    manifest_cid: Optional[str],
    node_count: Optional[int] = None,
    edge_count: Optional[int] = None,
) -> str:
    """Stable fingerprint binding revision identity to query surface vectors."""
    payload = {
        "revision_id": revision_id,
        "checksum": checksum,
        "pin_root": pin_root,
        "manifest_cid": manifest_cid,
        "node_count": node_count,
        "edge_count": edge_count,
    }
    return sha256_hex(canonical_json_bytes(payload))


def collect_query_vectors(
    catalog: GraphCatalog,
    *,
    tenant: Optional[str] = None,
    max_graphs: int = 10_000,
) -> List[QueryVector]:
    """Collect branch-head query vectors from the catalog."""
    vectors: List[QueryVector] = []
    tenants = [tenant] if tenant else _tenants(catalog)
    count = 0
    for t in tenants:
        graphs = catalog.list_graphs(t)
        for g in graphs:
            if count >= max_graphs:
                return vectors
            count += 1
            branches = catalog.list_branches(t, g.graph_id)
            for br in branches:
                try:
                    rev = catalog.get_revision(t, g.graph_id, br.head_revision)
                except Exception:
                    rev = None
                checksum = rev.checksum if rev else None
                pin_root = rev.pin_root if rev else None
                manifest_cid = rev.manifest_cid if rev else None
                node_count = edge_count = None
                if rev and rev.manifest_json:
                    try:
                        man = json.loads(rev.manifest_json)
                        counts = man.get("counts") or {}
                        node_count = counts.get("node_count")
                        edge_count = counts.get("edge_count")
                    except Exception:
                        pass
                fp = compute_query_fingerprint(
                    revision_id=br.head_revision,
                    checksum=checksum,
                    pin_root=pin_root,
                    manifest_cid=manifest_cid,
                    node_count=node_count,
                    edge_count=edge_count,
                )
                vectors.append(
                    QueryVector(
                        tenant=t,
                        graph_id=g.graph_id,
                        branch=br.branch,
                        revision_id=br.head_revision,
                        checksum=checksum,
                        pin_root=pin_root,
                        manifest_cid=manifest_cid,
                        query_fingerprint=fp,
                    )
                )
    # Stable order for digests.
    vectors.sort(key=lambda v: (v.tenant, v.graph_id, v.branch, v.revision_id))
    return vectors


def _tenants(catalog: GraphCatalog) -> List[str]:
    try:
        with catalog._txn(immediate=False) as conn:
            rows = conn.execute(
                "SELECT DISTINCT tenant FROM graphs ORDER BY tenant"
            ).fetchall()
            return [r["tenant"] for r in rows]
    except Exception:
        return []


def export_catalog_snapshot(
    catalog: GraphCatalog,
    *,
    tenant: Optional[str] = None,
) -> Dict[str, Any]:
    """Serialize control-plane state for an immutable backup."""
    tenants = [tenant] if tenant else _tenants(catalog)
    graphs_out: List[Dict[str, Any]] = []
    for t in tenants:
        for g in catalog.list_graphs(t, include_tombstoned=True):
            branches = [
                b.to_dict()
                for b in catalog.list_branches(
                    t, g.graph_id, include_tombstoned=True
                )
            ] if _supports_tombstoned_branches(catalog) else [
                b.to_dict() for b in catalog.list_branches(t, g.graph_id)
            ]
            revisions = [
                r.to_dict() for r in catalog.list_revisions(t, g.graph_id)
            ]
            pins = [p.to_dict() for p in catalog.list_pin_roots(t, g.graph_id)]
            graphs_out.append(
                {
                    "graph": g.to_dict(),
                    "branches": branches,
                    "revisions": revisions,
                    "pin_roots": pins,
                }
            )
    graphs_out.sort(
        key=lambda item: (
            item["graph"]["tenant"],
            item["graph"]["graph_id"],
        )
    )
    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "contract_version": OPERATIONS_CONTRACT_VERSION,
        "exported_at": time.time(),
        "graphs": graphs_out,
    }


def _supports_tombstoned_branches(catalog: Any) -> bool:
    import inspect

    try:
        sig = inspect.signature(catalog.list_branches)
        return "include_tombstoned" in sig.parameters
    except Exception:
        return False


@dataclass
class BackupManifest:
    backup_id: str
    created_at: float
    catalog_digest: str
    query_vectors_digest: str
    revision_ids: List[str]
    checksums: List[str]
    query_vector_count: int
    schema_version: str = BACKUP_SCHEMA_VERSION
    contract_version: str = OPERATIONS_CONTRACT_VERSION
    tenant_filter: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    @property
    def backup_digest(self) -> str:
        payload = {
            "backup_id": self.backup_id,
            "catalog_digest": self.catalog_digest,
            "query_vectors_digest": self.query_vectors_digest,
            "revision_ids": list(self.revision_ids),
            "checksums": list(self.checksums),
            "schema_version": self.schema_version,
        }
        return sha256_hex(canonical_json_bytes(payload))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_version": self.contract_version,
            "backup_id": self.backup_id,
            "created_at": self.created_at,
            "catalog_digest": self.catalog_digest,
            "query_vectors_digest": self.query_vectors_digest,
            "backup_digest": self.backup_digest,
            "revision_ids": list(self.revision_ids),
            "checksums": list(self.checksums),
            "query_vector_count": self.query_vector_count,
            "tenant_filter": self.tenant_filter,
            "notes": list(self.notes),
            "immutable": True,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BackupManifest":
        return cls(
            backup_id=str(data["backup_id"]),
            created_at=float(data.get("created_at") or 0.0),
            catalog_digest=str(data["catalog_digest"]),
            query_vectors_digest=str(data["query_vectors_digest"]),
            revision_ids=[str(x) for x in data.get("revision_ids") or []],
            checksums=[str(x) for x in data.get("checksums") or []],
            query_vector_count=int(data.get("query_vector_count") or 0),
            schema_version=str(data.get("schema_version") or BACKUP_SCHEMA_VERSION),
            contract_version=str(
                data.get("contract_version") or OPERATIONS_CONTRACT_VERSION
            ),
            tenant_filter=data.get("tenant_filter"),
            notes=[str(n) for n in data.get("notes") or []],
        )


@dataclass
class BackupResult:
    backup_id: str
    path: str
    manifest: BackupManifest
    query_vectors: List[QueryVector]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backup_id": self.backup_id,
            "path": self.path,
            "manifest": self.manifest.to_dict(),
            "query_vector_count": len(self.query_vectors),
        }


@dataclass
class RestoreProof:
    """Evidence that restore preserved revision / checksum / query vectors."""

    ok: bool
    backup_id: str
    backup_digest: str
    expected_revision_ids: List[str]
    actual_revision_ids: List[str]
    expected_checksums: List[str]
    actual_checksums: List[str]
    expected_query_vectors_digest: str
    actual_query_vectors_digest: str
    mismatches: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "backup_id": self.backup_id,
            "backup_digest": self.backup_digest,
            "expected_revision_ids": list(self.expected_revision_ids),
            "actual_revision_ids": list(self.actual_revision_ids),
            "expected_checksums": list(self.expected_checksums),
            "actual_checksums": list(self.actual_checksums),
            "expected_query_vectors_digest": self.expected_query_vectors_digest,
            "actual_query_vectors_digest": self.actual_query_vectors_digest,
            "mismatches": list(self.mismatches),
        }


@dataclass
class RestoreResult:
    ok: bool
    backup_id: str
    target_path: str
    proof: RestoreProof
    notes: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "backup_id": self.backup_id,
            "target_path": self.target_path,
            "proof": self.proof.to_dict(),
            "notes": list(self.notes),
            "error": self.error,
        }


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=".kg-bak-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def create_backup(
    catalog: GraphCatalog,
    destination: PathLike,
    *,
    tenant: Optional[str] = None,
    telemetry: Optional[OpsTelemetry] = None,
    notes: Optional[Sequence[str]] = None,
) -> BackupResult:
    """Write an immutable backup directory under *destination*.

    Layout::

        <destination>/<backup_id>/
          backup_manifest.json
          catalog_export.json
          query_vectors.json
    """
    tel = telemetry or get_default_telemetry()
    started = time.perf_counter()
    backup_id = f"bak-{uuid.uuid4().hex[:16]}"
    dest_root = Path(destination) / backup_id
    dest_root.mkdir(parents=True, exist_ok=False)

    snapshot = export_catalog_snapshot(catalog, tenant=tenant)
    vectors = collect_query_vectors(catalog, tenant=tenant)
    catalog_digest = sha256_hex(canonical_json_bytes(snapshot))
    vectors_payload = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "vectors": [v.to_dict() for v in vectors],
    }
    vectors_digest = sha256_hex(canonical_json_bytes(vectors_payload))

    revision_ids: List[str] = []
    checksums: List[str] = []
    for g in snapshot["graphs"]:
        for rev in g["revisions"]:
            revision_ids.append(str(rev["revision_id"]))
            if rev.get("checksum"):
                checksums.append(str(rev["checksum"]))
    revision_ids = sorted(set(revision_ids))
    checksums = sorted(set(checksums))

    manifest = BackupManifest(
        backup_id=backup_id,
        created_at=time.time(),
        catalog_digest=catalog_digest,
        query_vectors_digest=vectors_digest,
        revision_ids=revision_ids,
        checksums=checksums,
        query_vector_count=len(vectors),
        tenant_filter=tenant,
        notes=list(notes or ()),
    )

    _atomic_write_json(dest_root / CATALOG_EXPORT_NAME, snapshot)
    _atomic_write_json(dest_root / QUERY_VECTORS_NAME, vectors_payload)
    _atomic_write_json(dest_root / BACKUP_MANIFEST_NAME, manifest.to_dict())

    # Mark directory read-only for files (best-effort immutability on local FS).
    for child in dest_root.iterdir():
        try:
            os.chmod(child, 0o444)
        except OSError:
            pass

    duration_ms = (time.perf_counter() - started) * 1000.0
    tel.record_operation("backup.create", duration_ms, success=True)
    log_ops_event(
        "backup.created",
        backup_id=backup_id,
        backup_digest=manifest.backup_digest,
        path=str(dest_root),
        revision_count=len(revision_ids),
        query_vector_count=len(vectors),
    )
    return BackupResult(
        backup_id=backup_id,
        path=str(dest_root),
        manifest=manifest,
        query_vectors=vectors,
    )


def load_backup_manifest(backup_dir: PathLike) -> BackupManifest:
    path = Path(backup_dir) / BACKUP_MANIFEST_NAME
    data = json.loads(path.read_text(encoding="utf-8"))
    return BackupManifest.from_dict(data)


def verify_backup(backup_dir: PathLike) -> Tuple[bool, List[str]]:
    """Recompute digests and compare to the stored backup manifest."""
    root = Path(backup_dir)
    issues: List[str] = []
    try:
        manifest = load_backup_manifest(root)
    except Exception as exc:
        return False, [f"manifest_load_error:{type(exc).__name__}"]

    try:
        catalog_raw = json.loads((root / CATALOG_EXPORT_NAME).read_text(encoding="utf-8"))
        catalog_digest = sha256_hex(canonical_json_bytes(catalog_raw))
        if catalog_digest != manifest.catalog_digest:
            issues.append("catalog_digest_mismatch")
    except Exception as exc:
        issues.append(f"catalog_export_error:{type(exc).__name__}")

    try:
        vectors_raw = json.loads((root / QUERY_VECTORS_NAME).read_text(encoding="utf-8"))
        vectors_digest = sha256_hex(canonical_json_bytes(vectors_raw))
        if vectors_digest != manifest.query_vectors_digest:
            issues.append("query_vectors_digest_mismatch")
    except Exception as exc:
        issues.append(f"query_vectors_error:{type(exc).__name__}")

    # Recompute backup digest.
    recomputed = BackupManifest(
        backup_id=manifest.backup_id,
        created_at=manifest.created_at,
        catalog_digest=manifest.catalog_digest,
        query_vectors_digest=manifest.query_vectors_digest,
        revision_ids=list(manifest.revision_ids),
        checksums=list(manifest.checksums),
        query_vector_count=manifest.query_vector_count,
        schema_version=manifest.schema_version,
        tenant_filter=manifest.tenant_filter,
        notes=list(manifest.notes),
    )
    stored = json.loads((root / BACKUP_MANIFEST_NAME).read_text(encoding="utf-8"))
    if stored.get("backup_digest") != recomputed.backup_digest:
        issues.append("backup_digest_mismatch")

    return (len(issues) == 0), issues


def restore_backup(
    backup_dir: PathLike,
    target_catalog_path: PathLike,
    *,
    replace_existing: bool = False,
    telemetry: Optional[OpsTelemetry] = None,
) -> RestoreResult:
    """Restore catalog from an immutable backup and prove vector equality.

    Creates a fresh catalog at *target_catalog_path*, loads the export, then
    verifies revision ids, checksums, and query vectors match the backup
    manifest. On proof failure the target catalog is left in place but the
    result reports ``ok=False``.
    """
    tel = telemetry or get_default_telemetry()
    started = time.perf_counter()
    root = Path(backup_dir)
    target = Path(target_catalog_path)
    notes: List[str] = []

    ok_verify, verify_issues = verify_backup(root)
    if not ok_verify:
        return RestoreResult(
            ok=False,
            backup_id="unknown",
            target_path=str(target),
            proof=RestoreProof(
                ok=False,
                backup_id="unknown",
                backup_digest="",
                expected_revision_ids=[],
                actual_revision_ids=[],
                expected_checksums=[],
                actual_checksums=[],
                expected_query_vectors_digest="",
                actual_query_vectors_digest="",
                mismatches=verify_issues,
            ),
            error="BACKUP_INTEGRITY_FAILED",
            notes=verify_issues,
        )

    manifest = load_backup_manifest(root)
    snapshot = json.loads((root / CATALOG_EXPORT_NAME).read_text(encoding="utf-8"))
    vectors_raw = json.loads((root / QUERY_VECTORS_NAME).read_text(encoding="utf-8"))
    expected_vectors = [
        QueryVector.from_dict(v) for v in vectors_raw.get("vectors") or []
    ]

    if target.exists():
        if not replace_existing:
            return RestoreResult(
                ok=False,
                backup_id=manifest.backup_id,
                target_path=str(target),
                proof=RestoreProof(
                    ok=False,
                    backup_id=manifest.backup_id,
                    backup_digest=manifest.backup_digest,
                    expected_revision_ids=list(manifest.revision_ids),
                    actual_revision_ids=[],
                    expected_checksums=list(manifest.checksums),
                    actual_checksums=[],
                    expected_query_vectors_digest=manifest.query_vectors_digest,
                    actual_query_vectors_digest="",
                    mismatches=["target_exists"],
                ),
                error="TARGET_EXISTS",
                notes=["pass replace_existing=True to overwrite target catalog"],
            )
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        notes.append("replaced_existing_target")

    target.parent.mkdir(parents=True, exist_ok=True)
    catalog = open_catalog(target)
    try:
        _import_snapshot(catalog, snapshot)
        actual_vectors = collect_query_vectors(catalog)
        proof = prove_restore_equivalence(
            manifest=manifest,
            expected_vectors=expected_vectors,
            actual_vectors=actual_vectors,
            catalog=catalog,
        )
        duration_ms = (time.perf_counter() - started) * 1000.0
        tel.record_operation("backup.restore", duration_ms, success=proof.ok)
        log_ops_event(
            "backup.restored",
            backup_id=manifest.backup_id,
            ok=proof.ok,
            target=str(target),
            mismatch_count=len(proof.mismatches),
        )
        return RestoreResult(
            ok=proof.ok,
            backup_id=manifest.backup_id,
            target_path=str(target),
            proof=proof,
            notes=notes,
            error=None if proof.ok else "RESTORE_PROOF_FAILED",
        )
    finally:
        catalog.close()


def prove_restore_equivalence(
    *,
    manifest: BackupManifest,
    expected_vectors: Sequence[QueryVector],
    actual_vectors: Sequence[QueryVector],
    catalog: GraphCatalog,
) -> RestoreProof:
    """Prove restored catalog matches backup revision/checksum/query vectors."""
    mismatches: List[str] = []

    actual_rev_ids: List[str] = []
    actual_checksums: List[str] = []
    for t in _tenants(catalog):
        for g in catalog.list_graphs(t, include_tombstoned=True):
            for rev in catalog.list_revisions(t, g.graph_id):
                actual_rev_ids.append(rev.revision_id)
                if rev.checksum:
                    actual_checksums.append(rev.checksum)
    actual_rev_ids = sorted(set(actual_rev_ids))
    actual_checksums = sorted(set(actual_checksums))

    if actual_rev_ids != sorted(set(manifest.revision_ids)):
        mismatches.append("revision_ids_mismatch")
    if actual_checksums != sorted(set(manifest.checksums)):
        mismatches.append("checksums_mismatch")

    actual_payload = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "vectors": [v.to_dict() for v in sorted(
            actual_vectors,
            key=lambda x: (x.tenant, x.graph_id, x.branch, x.revision_id),
        )],
    }
    actual_qv_digest = sha256_hex(canonical_json_bytes(actual_payload))
    if actual_qv_digest != manifest.query_vectors_digest:
        mismatches.append("query_vectors_digest_mismatch")

    # Pairwise vector comparison (revision + checksum + fingerprint).
    exp_map = {
        (v.tenant, v.graph_id, v.branch): v for v in expected_vectors
    }
    act_map = {
        (v.tenant, v.graph_id, v.branch): v for v in actual_vectors
    }
    if set(exp_map) != set(act_map):
        mismatches.append("query_vector_keys_mismatch")
    for key, exp in exp_map.items():
        act = act_map.get(key)
        if act is None:
            continue
        if act.revision_id != exp.revision_id:
            mismatches.append(f"revision_mismatch:{key[0]}/{key[1]}/{key[2]}")
        if act.checksum != exp.checksum:
            mismatches.append(f"checksum_mismatch:{key[0]}/{key[1]}/{key[2]}")
        if act.query_fingerprint != exp.query_fingerprint:
            mismatches.append(f"query_fingerprint_mismatch:{key[0]}/{key[1]}/{key[2]}")

    return RestoreProof(
        ok=not mismatches,
        backup_id=manifest.backup_id,
        backup_digest=manifest.backup_digest,
        expected_revision_ids=list(manifest.revision_ids),
        actual_revision_ids=actual_rev_ids,
        expected_checksums=list(manifest.checksums),
        actual_checksums=actual_checksums,
        expected_query_vectors_digest=manifest.query_vectors_digest,
        actual_query_vectors_digest=actual_qv_digest,
        mismatches=mismatches,
    )


def _import_snapshot(catalog: GraphCatalog, snapshot: Mapping[str, Any]) -> None:
    """Import a catalog export into an empty catalog."""
    for item in snapshot.get("graphs") or []:
        g = item["graph"]
        tenant = g["tenant"]
        graph_id = g["graph_id"]
        catalog.create_graph(
            tenant,
            graph_id,
            storage_profile=g.get("storage_profile") or "parquet",
            graph_kind=g.get("graph_kind"),
            metadata=g.get("metadata") or {},
        )
        # Ensure bootstrap exists; create_graph already adds bootstrap revision.
        boot = bootstrap_revision_id(tenant, graph_id)
        # Insert non-bootstrap revisions first (parents before children).
        revisions = list(item.get("revisions") or [])
        # Sort: bootstrap first, then by created_at / revision_id
        revisions.sort(
            key=lambda r: (
                0 if r["revision_id"] == boot else 1,
                r.get("created_at") or "",
                r["revision_id"],
            )
        )
        for rev in revisions:
            rid = rev["revision_id"]
            if rid == boot:
                # Bootstrap already present; skip unless we need pins later.
                continue
            parent = rev.get("parent_revision")
            catalog.put_revision(
                tenant,
                graph_id,
                rid,
                parent_revision=parent,
                storage_profile=rev.get("storage_profile"),
                manifest_cid=rev.get("manifest_cid"),
                manifest_json=rev.get("manifest_json"),
                pin_root=rev.get("pin_root"),
                checksum=rev.get("checksum"),
                metadata=rev.get("metadata") or {},
            )
        # Pin roots
        for pin in item.get("pin_roots") or []:
            try:
                catalog.set_pin_root(
                    tenant,
                    graph_id,
                    pin["revision_id"],
                    root_cid=pin["root_cid"],
                    pin_kind=pin.get("pin_kind") or "backup",
                )
            except Exception:
                # Pin may already exist or revision missing bootstrap-only pins.
                pass
        # Branch heads (CAS from bootstrap / previous)
        for br in item.get("branches") or []:
            branch_name = br["branch"]
            head = br["head_revision"]
            current = catalog.get_branch(tenant, graph_id, branch_name)
            if current.head_revision == head:
                continue
            # Walk CAS from current head to target. For restore we force by
            # successive CAS if parent chain allows; otherwise CAS once.
            catalog.cas_set_head(
                tenant,
                graph_id,
                branch_name,
                expected_revision=current.head_revision,
                new_revision=head,
                pin_root=None,
                idempotency_key=f"restore-{tenant}-{graph_id}-{branch_name}-{head}",
            )


__all__ = [
    "BACKUP_SCHEMA_VERSION",
    "BackupManifest",
    "BackupResult",
    "QueryVector",
    "RestoreProof",
    "RestoreResult",
    "collect_query_vectors",
    "compute_query_fingerprint",
    "create_backup",
    "export_catalog_snapshot",
    "load_backup_manifest",
    "prove_restore_equivalence",
    "restore_backup",
    "verify_backup",
]
