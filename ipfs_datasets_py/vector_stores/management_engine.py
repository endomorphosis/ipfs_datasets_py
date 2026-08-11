"""
Vector Store Management Engine — reusable core module.

Contains ``VectorStoreManager`` extracted from ``vector_store_management.py``.
Import this module directly to use vector-store operations outside of the MCP
tool layer.

Also hosts the DuckDB vector **shadow catalog** (DQK-062): collection, model,
chunk, mapping, generation, shard, tombstone, and build producers route
lifecycle metadata through DuckDB while legacy adapters remain authoritative.
Shadow failures quarantine without changing legacy results.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional backend imports
# ---------------------------------------------------------------------------

try:
    import faiss  # type: ignore
    FAISS_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    FAISS_AVAILABLE = False
    faiss = None  # type: ignore

try:
    from qdrant_client import QdrantClient  # type: ignore
    from qdrant_client.http import models as qdrant_models  # type: ignore
    QDRANT_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    QDRANT_AVAILABLE = False
    QdrantClient = None  # type: ignore
    qdrant_models = None  # type: ignore

try:
    from elasticsearch import Elasticsearch  # type: ignore
    ELASTICSEARCH_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    ELASTICSEARCH_AVAILABLE = False
    Elasticsearch = None  # type: ignore

try:
    from ipfs_datasets_py.embeddings.embeddings_engine import AdvancedIPFSEmbeddings  # type: ignore
    EMBEDDINGS_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    EMBEDDINGS_AVAILABLE = False
    AdvancedIPFSEmbeddings = None  # type: ignore

_INDEXES_DIR = "./vector_indexes"

# ---------------------------------------------------------------------------
# DuckDB vector shadow catalog (DQK-062)
# ---------------------------------------------------------------------------

VECTOR_SHADOW_DOMAIN: str = "vectors"
VECTOR_SHADOW_SCHEMA: str = (
    "ipfs_datasets_py/vector-stores-duckdb-shadow-catalog@1"
)
VECTOR_SHADOW_OWNER_TASK: str = "DQK-062"

_SLUG_SAFE = re.compile(r"^[a-z0-9]([a-z0-9_-]{0,62}[a-z0-9])?$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,191}$")

_process_catalog_lock = threading.RLock()
_process_catalog: Optional["VectorShadowCatalog"] = None


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _digest(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(payload)).hexdigest()


def _new_op_id(prefix: str = "op") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def sanitize_collection_slug(name: str) -> str:
    """Map free-form collection names onto DuckDB slug constraints."""

    raw = (name or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-_")
    if not cleaned:
        cleaned = "collection"
    if len(cleaned) > 64:
        cleaned = cleaned[:64].rstrip("-_")
    if not _SLUG_SAFE.fullmatch(cleaned):
        # Single-char or trailing separator edge cases.
        cleaned = re.sub(r"^[^a-z0-9]+|[^a-z0-9]+$", "", cleaned) or "collection"
        if len(cleaned) == 1 and cleaned.isalnum():
            return cleaned
        if not _SLUG_SAFE.fullmatch(cleaned):
            digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
            cleaned = f"col-{digest}"
    return cleaned


def sanitize_id(value: str, *, prefix: str = "id") -> str:
    text = (value or "").strip()
    if text and _SAFE_ID.fullmatch(text):
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


@dataclass
class ShadowParityView:
    """Legacy vs shadow mapping/count/query view for one collection."""

    collection_key: str
    matched: bool
    mapping_matched: bool
    count_matched: bool
    query_matched: bool
    identity_matched: bool
    legacy: Dict[str, Any] = field(default_factory=dict)
    shadow: Dict[str, Any] = field(default_factory=dict)
    mismatch_reason: str = ""
    quarantined: bool = False
    authority: str = "legacy"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": VECTOR_SHADOW_SCHEMA,
            "collection_key": self.collection_key,
            "matched": self.matched,
            "mapping_matched": self.mapping_matched,
            "count_matched": self.count_matched,
            "query_matched": self.query_matched,
            "identity_matched": self.identity_matched,
            "legacy": dict(self.legacy),
            "shadow": dict(self.shadow),
            "mismatch_reason": self.mismatch_reason,
            "quarantined": self.quarantined,
            "authority": self.authority,
        }


@dataclass
class ShadowCreateResult:
    """Outcome of a shadow create/delete/list producer call."""

    ok: bool
    authority: str = "legacy"
    collection_id: str = ""
    generation_id: Optional[int] = None
    operation_id: str = ""
    parity: Optional[ShadowParityView] = None
    quarantined: bool = False
    quarantine_id: str = ""
    error: str = ""
    shadow_payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": VECTOR_SHADOW_SCHEMA,
            "ok": self.ok,
            "authority": self.authority,
            "collection_id": self.collection_id,
            "generation_id": self.generation_id,
            "operation_id": self.operation_id,
            "parity": self.parity.to_dict() if self.parity else None,
            "quarantined": self.quarantined,
            "quarantine_id": self.quarantine_id,
            "error": self.error,
            "shadow_payload": dict(self.shadow_payload),
        }


class VectorShadowCatalog:
    """DuckDB vector lifecycle shadow catalog for producer entrypoints (DQK-062).

    * **Legacy is authority** — callers always keep their existing create/list/
      delete results; this catalog never replaces them.
    * **Shadow projection** — collection/model/chunk/mapping/generation/shard/
      tombstone/build metadata is dual-written into :class:`DuckDBVectorStore`.
    * **Parity** — mapping ids, live counts, and query-visible ids are compared
      after each mutating operation and after restart.
    * **Quarantine** — shadow failures and parity mismatches quarantine without
      mutating legacy state or promoting authority.
    """

    DOMAIN = VECTOR_SHADOW_DOMAIN
    SCHEMA = VECTOR_SHADOW_SCHEMA

    def __init__(
        self,
        catalog_path: Union[str, Path, None] = None,
        *,
        enabled: bool = True,
        authority_port: Any = None,
        writer_id: str = "writer:vector-shadow-catalog",
    ) -> None:
        self._enabled = bool(enabled)
        self._path = (
            ":memory:"
            if catalog_path in (None, ":memory:")
            else str(Path(catalog_path))
        )
        self._lock = threading.RLock()
        self._store: Any = None
        self._port = authority_port
        self._writer_id = writer_id
        # Logical producer name → catalog collection_id
        self._logical_to_collection: Dict[str, str] = {}
        # collection_id → last legacy parity snapshot
        self._legacy_snapshots: Dict[str, Dict[str, Any]] = {}
        self._closed = False
        if self._enabled:
            self._open_store()
            if self._port is None:
                self._port = self._build_default_port()

    # -- lifecycle ----------------------------------------------------------

    def _build_default_port(self) -> Any:
        from ipfs_datasets_py.duckdb_control.authority_transition import (
            AuthorityMode,
            MemoryAuthorityBackend,
            build_authority_port,
        )

        return build_authority_port(
            MemoryAuthorityBackend(),
            domain=self.DOMAIN,
            initial_mode=AuthorityMode.SHADOW,
            writer_id=self._writer_id,
        )

    def _open_store(self) -> None:
        from ipfs_datasets_py.vector_stores.duckdb_store import DuckDBVectorStore

        self._store = DuckDBVectorStore(self._path)
        self._closed = False

    @property
    def enabled(self) -> bool:
        return self._enabled and not self._closed

    @property
    def path(self) -> str:
        return self._path

    @property
    def store(self) -> Any:
        return self._store

    @property
    def authority_port(self) -> Any:
        return self._port

    @property
    def mode(self) -> str:
        if self._port is None:
            return "disabled"
        try:
            return self._port.mode.value
        except Exception:  # noqa: BLE001
            return "unknown"

    def close(self) -> None:
        with self._lock:
            if self._store is not None:
                try:
                    self._store.close()
                except Exception:  # noqa: BLE001
                    pass
                self._store = None
            self._closed = True

    def reopen(self) -> "VectorShadowCatalog":
        """Close and reopen the file-backed catalog (restart simulation)."""

        with self._lock:
            if self._path == ":memory:":
                raise RuntimeError("cannot restart an in-memory shadow catalog")
            logical = dict(self._logical_to_collection)
            legacy = dict(self._legacy_snapshots)
            port = self._port
            self.close()
            self._open_store()
            self._logical_to_collection = logical
            self._legacy_snapshots = legacy
            self._port = port
            self._closed = False
            return self

    # -- quarantine helpers -------------------------------------------------

    def _quarantine(
        self,
        *,
        key: str,
        operation_id: str,
        reason: str,
        legacy_digest: str = "",
        db_digest: str = "",
    ) -> str:
        if self._port is None:
            logger.warning(
                "vector shadow quarantine (no port): key=%s reason=%s",
                key,
                reason,
            )
            return ""
        try:
            rec = self._port.quarantine_disagreement(
                key=key,
                operation_id=operation_id or _new_op_id("shadow"),
                reason=reason[:500],
                legacy_digest=legacy_digest or None,
                db_digest=db_digest or None,
            )
            return getattr(rec, "quarantine_id", "") or ""
        except Exception as exc:  # noqa: BLE001 — never fail the producer
            logger.warning("vector shadow quarantine failed: %s", exc)
            return ""

    def list_open_quarantines(self) -> List[Dict[str, Any]]:
        if self._port is None:
            return []
        try:
            records = self._port.backend.list_open_quarantine(self.DOMAIN)
            return [
                {
                    "quarantine_id": r.quarantine_id,
                    "key": r.key,
                    "reason": r.reason,
                    "operation_id": r.operation_id,
                    "resolved": r.resolved,
                }
                for r in records
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("list_open_quarantines failed: %s", exc)
            return []

    # -- identity / payload helpers -----------------------------------------

    @staticmethod
    def _default_identities(
        *,
        dimension: int,
        dtype: str = "float32",
        model_name: str = "shadow-model",
        model_provider: str = "shadow",
        model_revision: str = "r1",
        chunking_identity: Optional[str] = None,
        normalization_identity: Optional[str] = None,
        source_revision: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        mid = model_id or sanitize_id(
            f"model_{model_provider}_{model_name}_{model_revision}_{dimension}_{dtype}",
            prefix="model",
        )
        return {
            "model_id": mid,
            "model_name": model_name,
            "model_provider": model_provider,
            "model_revision": model_revision,
            "dimension": int(dimension),
            "dtype": (dtype or "float32").lower(),
            "chunking_identity": chunking_identity or "chunk:default@1",
            "normalization_identity": normalization_identity or "norm:none@1",
            "source_revision": source_revision or "src-0",
        }

    def _ensure_model(self, identities: Mapping[str, Any]) -> str:
        assert self._store is not None
        model_id = str(identities["model_id"])
        try:
            self._store.get_embedding_model(model_id)
            return model_id
        except Exception:
            pass
        self._store.create_embedding_model(
            name=str(identities["model_name"]),
            provider=str(identities["model_provider"]),
            revision=str(identities["model_revision"]),
            dtype=str(identities["dtype"]),
            dimension=int(identities["dimension"]),
            model_id=model_id,
            metadata={"shadow": True, "owner_task": VECTOR_SHADOW_OWNER_TASK},
        )
        return model_id

    def _legacy_key(self, logical_name: str, backend: str) -> str:
        return f"{backend}:{logical_name}"

    def _snapshot_from_store(self, collection_id: str) -> Dict[str, Any]:
        assert self._store is not None
        col = self._store.get_collection(collection_id)
        visible = self._store.list_query_visible_chunks(collection_id)
        mapping = {c.chunk_id: c.ordinal for c in visible}
        query_ids = sorted(c.chunk_id for c in visible)
        return {
            "collection_id": col.collection_id,
            "name": col.name,
            "dimension": col.dimension,
            "dtype": col.dtype,
            "model_id": col.model_id,
            "chunking_identity": col.chunking_identity,
            "normalization_identity": col.normalization_identity,
            "source_revision": col.source_revision,
            "published_generation": col.published_generation,
            "status": col.status,
            "count": len(visible),
            "mapping": mapping,
            "query_ids": query_ids,
        }

    def _compare_parity(
        self,
        *,
        collection_key: str,
        legacy: Mapping[str, Any],
        shadow: Mapping[str, Any],
    ) -> ShadowParityView:
        leg_map = {
            str(k): v for k, v in dict(legacy.get("mapping") or {}).items()
        }
        sh_map = {
            str(k): v for k, v in dict(shadow.get("mapping") or {}).items()
        }
        mapping_matched = set(leg_map.keys()) == set(sh_map.keys())
        count_matched = int(legacy.get("count", -1)) == int(
            shadow.get("count", -2)
        )
        leg_q = sorted(str(x) for x in (legacy.get("query_ids") or []))
        sh_q = sorted(str(x) for x in (shadow.get("query_ids") or []))
        query_matched = leg_q == sh_q
        identity_fields = (
            "dimension",
            "dtype",
            "model_id",
            "chunking_identity",
            "normalization_identity",
            "source_revision",
        )
        identity_matched = all(
            legacy.get(f) == shadow.get(f) for f in identity_fields
        )
        matched = (
            mapping_matched
            and count_matched
            and query_matched
            and identity_matched
        )
        reason = ""
        if not matched:
            parts = []
            if not mapping_matched:
                parts.append("mapping")
            if not count_matched:
                parts.append("count")
            if not query_matched:
                parts.append("query")
            if not identity_matched:
                parts.append("identity")
            reason = "mismatch:" + ",".join(parts)
        return ShadowParityView(
            collection_key=collection_key,
            matched=matched,
            mapping_matched=mapping_matched,
            count_matched=count_matched,
            query_matched=query_matched,
            identity_matched=identity_matched,
            legacy=dict(legacy),
            shadow=dict(shadow),
            mismatch_reason=reason,
            authority="legacy",
        )

    # -- producer entrypoints -----------------------------------------------

    def shadow_create(
        self,
        *,
        logical_name: str,
        backend: str,
        dimension: int,
        dtype: str = "float32",
        mapping: Optional[Mapping[str, Any]] = None,
        vectors: Optional[Sequence[Sequence[float]]] = None,
        vector_ids: Optional[Sequence[str]] = None,
        model_name: str = "shadow-model",
        model_provider: str = "shadow",
        model_revision: str = "r1",
        chunking_identity: Optional[str] = None,
        normalization_identity: Optional[str] = None,
        source_revision: Optional[str] = None,
        model_id: Optional[str] = None,
        metadata_json: Optional[Mapping[str, Any]] = None,
        shard_manifest: Optional[Mapping[str, Any]] = None,
        index_build: Optional[Mapping[str, Any]] = None,
        operation_id: Optional[str] = None,
    ) -> ShadowCreateResult:
        """Project a legacy create into the DuckDB shadow catalog.

        Always leaves legacy authority untouched. Returns a result describing
        shadow success/parity/quarantine; never raises to callers for shadow
        failures.
        """

        op_id = operation_id or _new_op_id("create")
        logical = (logical_name or "").strip()
        backend = (backend or "unknown").strip().lower()
        key = self._legacy_key(logical, backend)

        # Build the caller-visible legacy snapshot (authority).
        # Chunk ids are global in DuckDBVectorStore — namespace by backend/logical.
        def _namespaced(raw: str) -> str:
            return sanitize_id(f"{backend}_{logical}_{raw}", prefix="vec")

        ids: List[str] = []
        map_payload: Dict[str, Any] = {}
        if mapping:
            for k, v in mapping.items():
                vid = _namespaced(str(k))
                map_payload[vid] = v
            ids = list(map_payload.keys())
        elif vector_ids:
            ids = [_namespaced(str(v)) for v in vector_ids]
            map_payload = {vid: i for i, vid in enumerate(ids)}
        elif vectors:
            ids = [_namespaced(str(i)) for i in range(len(vectors))]
            map_payload = {vid: i for i, vid in enumerate(ids)}

        identities = self._default_identities(
            dimension=int(dimension),
            dtype=dtype,
            model_name=model_name,
            model_provider=model_provider,
            model_revision=model_revision,
            chunking_identity=chunking_identity,
            normalization_identity=normalization_identity,
            source_revision=source_revision,
            model_id=model_id,
        )
        legacy_snapshot: Dict[str, Any] = {
            "logical_name": logical,
            "backend": backend,
            "collection_id": "",  # filled after shadow id assignment
            "name": sanitize_collection_slug(logical),
            "dimension": identities["dimension"],
            "dtype": identities["dtype"],
            "model_id": identities["model_id"],
            "chunking_identity": identities["chunking_identity"],
            "normalization_identity": identities["normalization_identity"],
            "source_revision": identities["source_revision"],
            "count": len(ids),
            "mapping": map_payload,
            "query_ids": sorted(ids),
            "metadata_json": dict(metadata_json or {}),
            "shard_manifest": dict(shard_manifest or {}),
            "status": "active",
        }

        if not self.enabled:
            return ShadowCreateResult(
                ok=True,
                authority="legacy",
                operation_id=op_id,
                shadow_payload={"enabled": False},
            )

        with self._lock:
            try:
                assert self._store is not None
                self._ensure_model(identities)
                base_slug = sanitize_collection_slug(logical)
                # Always allocate a unique catalog id + slug so recreate is safe.
                suffix = uuid.uuid4().hex[:8]
                collection_id = sanitize_id(
                    f"{backend}_{base_slug}_{suffix}", prefix="col"
                )
                # Soft-delete any prior active shadow for this logical key.
                prior_id = self._logical_to_collection.get(key)
                if prior_id:
                    try:
                        for chunk in list(
                            self._store.list_query_visible_chunks(prior_id)
                        ):
                            self._store.delete_chunk(
                                collection_id=prior_id,
                                chunk_id=chunk.chunk_id,
                                reason="shadow_replace",
                            )
                        with self._store._lock:
                            self._store._conn.execute(
                                """
                                UPDATE vector_collections
                                SET status = 'deleted', updated_at = ?
                                WHERE collection_id = ?
                                """,
                                [
                                    __import__("datetime")
                                    .datetime.now(
                                        __import__("datetime").timezone.utc
                                    )
                                    .strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    prior_id,
                                ],
                            )
                    except Exception:
                        pass

                # Slug must be unique among active collections.
                unique_slug = sanitize_collection_slug(
                    f"{base_slug}-{suffix}"
                )
                col = self._store.create_collection(
                    name=unique_slug,
                    dimension=identities["dimension"],
                    dtype=identities["dtype"],
                    model_id=identities["model_id"],
                    chunking_identity=identities["chunking_identity"],
                    normalization_identity=identities[
                        "normalization_identity"
                    ],
                    source_revision=identities["source_revision"],
                    collection_id=collection_id,
                    metadata={
                        "shadow": True,
                        "backend": backend,
                        "logical_name": logical,
                        "owner_task": VECTOR_SHADOW_OWNER_TASK,
                        "metadata_json": dict(metadata_json or {}),
                    },
                )
                # Align legacy snapshot name with the exact catalog name.
                legacy_snapshot["name"] = col.name
                gen = self._store.open_generation(col.collection_id)
                doc = self._store.add_document(
                    collection_id=col.collection_id,
                    generation_id=gen.generation_id,
                    source={
                        "kind": "shadow_producer",
                        "backend": backend,
                        "logical_name": logical,
                    },
                    document_id=sanitize_id(
                        f"doc_{backend}_{base_slug}_{suffix}", prefix="doc"
                    ),
                )
                vec_list = list(vectors or [])
                for i, vid in enumerate(ids):
                    if i < len(vec_list):
                        values = [float(x) for x in vec_list[i]]
                    else:
                        # Deterministic unit stub for mapping-only shadow.
                        values = [0.0] * identities["dimension"]
                        if identities["dimension"] > 0:
                            values[0] = 1.0
                    if len(values) != identities["dimension"]:
                        # Pad / trim to contract dimension.
                        if len(values) < identities["dimension"]:
                            values = list(values) + [0.0] * (
                                identities["dimension"] - len(values)
                            )
                        else:
                            values = list(values)[: identities["dimension"]]
                    self._store.add_chunk(
                        collection_id=col.collection_id,
                        generation_id=gen.generation_id,
                        document_id=doc.document_id,
                        vector=values,
                        ordinal=int(map_payload.get(vid, i)),
                        chunk_id=vid,
                        source={"vector_id": vid, "backend": backend},
                        text="",
                        metadata={"legacy_id": vid},
                    )

                if shard_manifest:
                    self._store.register_shard(
                        collection_id=col.collection_id,
                        generation_id=gen.generation_id,
                        shard_index=int(shard_manifest.get("shard_index", 0)),
                        vector_count=int(
                            shard_manifest.get("vector_count", len(ids))
                        ),
                        content_digest=shard_manifest.get("content_digest"),
                        shard_id=sanitize_id(
                            str(
                                shard_manifest.get(
                                    "shard_id",
                                    f"shard_{backend}_{base_slug}_{suffix}",
                                )
                            ),
                            prefix="shard",
                        ),
                        metadata=dict(shard_manifest),
                    )

                if index_build:
                    self._store.record_index_build(
                        collection_id=col.collection_id,
                        generation_id=gen.generation_id,
                        index_kind=str(
                            index_build.get("index_kind", "shadow")
                        ),
                        status=str(index_build.get("status", "completed")),
                        build_id=sanitize_id(
                            str(
                                index_build.get(
                                    "build_id",
                                    f"build_{backend}_{base_slug}_{suffix}",
                                )
                            ),
                            prefix="build",
                        ),
                        metadata=dict(index_build),
                    )

                published = self._store.publish_generation(
                    col.collection_id, gen.generation_id
                )
                shadow_snap = self._snapshot_from_store(col.collection_id)
                legacy_snapshot["collection_id"] = col.collection_id
                legacy_snapshot["published_generation"] = (
                    published.generation_id
                )

                # Authority port: legacy + shadow projection digests.
                if self._port is not None:
                    try:
                        self._port.write(
                            key,
                            {
                                "legacy": legacy_snapshot,
                                "shadow": shadow_snap,
                                "operation": "create",
                                "backend": backend,
                            },
                            operation_id=op_id,
                        )
                        self._port.emit_parity_receipt(
                            key, operation_id=op_id
                        )
                    except Exception as port_exc:  # noqa: BLE001
                        qid = self._quarantine(
                            key=key,
                            operation_id=op_id,
                            reason=f"authority_port_write_failed: {port_exc}",
                        )
                        return ShadowCreateResult(
                            ok=False,
                            authority="legacy",
                            collection_id=col.collection_id,
                            generation_id=published.generation_id,
                            operation_id=op_id,
                            quarantined=True,
                            quarantine_id=qid,
                            error=str(port_exc),
                        )

                parity = self._compare_parity(
                    collection_key=key,
                    legacy=legacy_snapshot,
                    shadow=shadow_snap,
                )
                if not parity.matched:
                    qid = self._quarantine(
                        key=key,
                        operation_id=op_id,
                        reason=parity.mismatch_reason or "parity_mismatch",
                        legacy_digest=_digest(legacy_snapshot),
                        db_digest=_digest(shadow_snap),
                    )
                    parity.quarantined = True
                    self._logical_to_collection[key] = col.collection_id
                    self._legacy_snapshots[key] = legacy_snapshot
                    return ShadowCreateResult(
                        ok=False,
                        authority="legacy",
                        collection_id=col.collection_id,
                        generation_id=published.generation_id,
                        operation_id=op_id,
                        parity=parity,
                        quarantined=True,
                        quarantine_id=qid,
                        error=parity.mismatch_reason,
                        shadow_payload=shadow_snap,
                    )

                self._logical_to_collection[key] = col.collection_id
                self._legacy_snapshots[key] = legacy_snapshot
                return ShadowCreateResult(
                    ok=True,
                    authority="legacy",
                    collection_id=col.collection_id,
                    generation_id=published.generation_id,
                    operation_id=op_id,
                    parity=parity,
                    shadow_payload=shadow_snap,
                )
            except Exception as exc:  # noqa: BLE001 — quarantine, keep legacy
                logger.warning(
                    "vector shadow create failed for %s: %s", key, exc
                )
                qid = self._quarantine(
                    key=key,
                    operation_id=op_id,
                    reason=f"shadow_create_failed: {exc}",
                )
                return ShadowCreateResult(
                    ok=False,
                    authority="legacy",
                    operation_id=op_id,
                    quarantined=True,
                    quarantine_id=qid,
                    error=str(exc),
                )

    def shadow_delete(
        self,
        *,
        logical_name: str,
        backend: str,
        operation_id: Optional[str] = None,
    ) -> ShadowCreateResult:
        """Shadow-delete (soft) a collection; legacy authority unchanged."""

        op_id = operation_id or _new_op_id("delete")
        logical = (logical_name or "").strip()
        backend = (backend or "unknown").strip().lower()
        key = self._legacy_key(logical, backend)

        if not self.enabled:
            return ShadowCreateResult(
                ok=True, authority="legacy", operation_id=op_id
            )

        with self._lock:
            try:
                collection_id = self._logical_to_collection.get(key)
                if collection_id and self._store is not None:
                    try:
                        # Tombstone all query-visible chunks then mark deleted.
                        for chunk in list(
                            self._store.list_query_visible_chunks(collection_id)
                        ):
                            self._store.delete_chunk(
                                collection_id=collection_id,
                                chunk_id=chunk.chunk_id,
                                reason="shadow_delete",
                            )
                        with self._store._lock:
                            self._store._conn.execute(
                                """
                                UPDATE vector_collections
                                SET status = 'deleted', updated_at = ?
                                WHERE collection_id = ?
                                """,
                                [
                                    __import__("datetime")
                                    .datetime.now(
                                        __import__("datetime").timezone.utc
                                    )
                                    .strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    collection_id,
                                ],
                            )
                    except Exception as inner:  # noqa: BLE001
                        qid = self._quarantine(
                            key=key,
                            operation_id=op_id,
                            reason=f"shadow_delete_store_failed: {inner}",
                        )
                        return ShadowCreateResult(
                            ok=False,
                            authority="legacy",
                            collection_id=collection_id or "",
                            operation_id=op_id,
                            quarantined=True,
                            quarantine_id=qid,
                            error=str(inner),
                        )

                legacy_snap = {
                    "logical_name": logical,
                    "backend": backend,
                    "status": "deleted",
                    "count": 0,
                    "mapping": {},
                    "query_ids": [],
                    "collection_id": collection_id or "",
                }
                if self._port is not None:
                    try:
                        self._port.write(
                            key,
                            {
                                "legacy": legacy_snap,
                                "shadow": {
                                    "status": "deleted",
                                    "count": 0,
                                    "mapping": {},
                                    "query_ids": [],
                                },
                                "operation": "delete",
                                "backend": backend,
                            },
                            operation_id=op_id,
                        )
                        self._port.emit_parity_receipt(
                            key, operation_id=op_id
                        )
                    except Exception as port_exc:  # noqa: BLE001
                        qid = self._quarantine(
                            key=key,
                            operation_id=op_id,
                            reason=f"delete_port_failed: {port_exc}",
                        )
                        return ShadowCreateResult(
                            ok=False,
                            authority="legacy",
                            collection_id=collection_id or "",
                            operation_id=op_id,
                            quarantined=True,
                            quarantine_id=qid,
                            error=str(port_exc),
                        )

                self._legacy_snapshots[key] = legacy_snap
                if key in self._logical_to_collection:
                    del self._logical_to_collection[key]
                parity = ShadowParityView(
                    collection_key=key,
                    matched=True,
                    mapping_matched=True,
                    count_matched=True,
                    query_matched=True,
                    identity_matched=True,
                    legacy=legacy_snap,
                    shadow={
                        "status": "deleted",
                        "count": 0,
                        "mapping": {},
                        "query_ids": [],
                    },
                )
                return ShadowCreateResult(
                    ok=True,
                    authority="legacy",
                    collection_id=collection_id or "",
                    operation_id=op_id,
                    parity=parity,
                    shadow_payload=legacy_snap,
                )
            except Exception as exc:  # noqa: BLE001
                qid = self._quarantine(
                    key=key,
                    operation_id=op_id,
                    reason=f"shadow_delete_failed: {exc}",
                )
                return ShadowCreateResult(
                    ok=False,
                    authority="legacy",
                    operation_id=op_id,
                    quarantined=True,
                    quarantine_id=qid,
                    error=str(exc),
                )

    def shadow_list(self, *, backend: Optional[str] = None) -> Dict[str, Any]:
        """List active shadow collections (for parity with legacy list)."""

        if not self.enabled or self._store is None:
            return {
                "status": "success",
                "authority": "legacy",
                "shadow_enabled": False,
                "collections": [],
            }
        with self._lock:
            try:
                cols = self._store.list_collections()
                items = []
                for col in cols:
                    if backend:
                        meta = col.metadata or {}
                        if str(meta.get("backend", "")).lower() != backend.lower():
                            continue
                    snap = self._snapshot_from_store(col.collection_id)
                    items.append(snap)
                return {
                    "status": "success",
                    "authority": "legacy",
                    "shadow_enabled": True,
                    "schema": self.SCHEMA,
                    "collections": items,
                    "count": len(items),
                }
            except Exception as exc:  # noqa: BLE001
                qid = self._quarantine(
                    key=f"list:{backend or 'all'}",
                    operation_id=_new_op_id("list"),
                    reason=f"shadow_list_failed: {exc}",
                )
                return {
                    "status": "quarantined",
                    "authority": "legacy",
                    "shadow_enabled": True,
                    "collections": [],
                    "quarantine_id": qid,
                    "error": str(exc),
                }

    def parity_for(
        self, *, logical_name: str, backend: str
    ) -> Optional[ShadowParityView]:
        """Recompute mapping/count/query parity for one producer collection."""

        key = self._legacy_key(logical_name, backend)
        with self._lock:
            legacy = self._legacy_snapshots.get(key)
            collection_id = self._logical_to_collection.get(key)
            if legacy is None or collection_id is None or self._store is None:
                return None
            try:
                shadow = self._snapshot_from_store(collection_id)
            except Exception as exc:  # noqa: BLE001
                qid = self._quarantine(
                    key=key,
                    operation_id=_new_op_id("parity"),
                    reason=f"parity_snapshot_failed: {exc}",
                )
                view = ShadowParityView(
                    collection_key=key,
                    matched=False,
                    mapping_matched=False,
                    count_matched=False,
                    query_matched=False,
                    identity_matched=False,
                    legacy=dict(legacy),
                    shadow={},
                    mismatch_reason=str(exc),
                    quarantined=True,
                )
                view.quarantined = True
                return view
            view = self._compare_parity(
                collection_key=key, legacy=legacy, shadow=shadow
            )
            if not view.matched:
                self._quarantine(
                    key=key,
                    operation_id=_new_op_id("parity"),
                    reason=view.mismatch_reason or "parity_mismatch",
                    legacy_digest=_digest(legacy),
                    db_digest=_digest(shadow),
                )
                view.quarantined = True
            return view

    def parity_across_restart(
        self, *, logical_name: str, backend: str
    ) -> ShadowParityView:
        """Close/reopen the catalog and re-check parity (restart proof)."""

        key = self._legacy_key(logical_name, backend)
        legacy = dict(self._legacy_snapshots.get(key) or {})
        collection_id = self._logical_to_collection.get(key)
        if not legacy or not collection_id:
            return ShadowParityView(
                collection_key=key,
                matched=False,
                mapping_matched=False,
                count_matched=False,
                query_matched=False,
                identity_matched=False,
                mismatch_reason="unknown_collection",
            )
        if self._path == ":memory:":
            # In-memory cannot restart; re-read current store as best-effort.
            shadow = self._snapshot_from_store(collection_id)
            return self._compare_parity(
                collection_key=key, legacy=legacy, shadow=shadow
            )
        self.reopen()
        # After reopen, re-bind logical map and re-read from store.
        try:
            shadow = self._snapshot_from_store(collection_id)
            self._logical_to_collection[key] = collection_id
            view = self._compare_parity(
                collection_key=key, legacy=legacy, shadow=shadow
            )
            if not view.matched:
                self._quarantine(
                    key=key,
                    operation_id=_new_op_id("restart-parity"),
                    reason=view.mismatch_reason or "restart_parity_mismatch",
                )
                view.quarantined = True
            return view
        except Exception as exc:  # noqa: BLE001
            self._quarantine(
                key=key,
                operation_id=_new_op_id("restart-parity"),
                reason=f"restart_parity_failed: {exc}",
            )
            return ShadowParityView(
                collection_key=key,
                matched=False,
                mapping_matched=False,
                count_matched=False,
                query_matched=False,
                identity_matched=False,
                legacy=legacy,
                mismatch_reason=str(exc),
                quarantined=True,
            )

    def shadow_shard_manifest(
        self,
        *,
        logical_name: str,
        backend: str,
        shard_manifest: Mapping[str, Any],
        operation_id: Optional[str] = None,
    ) -> ShadowCreateResult:
        """Project a shard manifest for an existing shadow collection.

        Prefer registering shards during :meth:`shadow_create` (draft
        generation). This method records the manifest on the authority port
        and collection metadata without republishing an empty generation.
        """

        op_id = operation_id or _new_op_id("shard")
        key = self._legacy_key(logical_name, backend)
        if not self.enabled:
            return ShadowCreateResult(
                ok=True, authority="legacy", operation_id=op_id
            )
        with self._lock:
            collection_id = self._logical_to_collection.get(key)
            if not collection_id or self._store is None:
                qid = self._quarantine(
                    key=key,
                    operation_id=op_id,
                    reason="shard_manifest_unknown_collection",
                )
                return ShadowCreateResult(
                    ok=False,
                    authority="legacy",
                    operation_id=op_id,
                    quarantined=True,
                    quarantine_id=qid,
                    error="unknown_collection",
                )
            try:
                col = self._store.get_collection(collection_id)
                payload = {
                    "collection_id": collection_id,
                    "logical_name": logical_name,
                    "backend": backend,
                    "shard_manifest": dict(shard_manifest),
                    "published_generation": col.published_generation,
                    "dimension": col.dimension,
                    "dtype": col.dtype,
                    "model_id": col.model_id,
                    "source_revision": col.source_revision,
                }
                if self._port is not None:
                    self._port.write(
                        f"{key}:shard",
                        {
                            "legacy": payload,
                            "shadow": payload,
                            "operation": "shard_manifest",
                        },
                        operation_id=op_id,
                    )
                    self._port.emit_parity_receipt(
                        f"{key}:shard", operation_id=op_id
                    )
                # Keep latest manifest on the in-memory legacy snapshot.
                snap = self._legacy_snapshots.get(key) or {}
                snap = dict(snap)
                snap["shard_manifest"] = dict(shard_manifest)
                self._legacy_snapshots[key] = snap
                return ShadowCreateResult(
                    ok=True,
                    authority="legacy",
                    collection_id=collection_id,
                    generation_id=col.published_generation,
                    operation_id=op_id,
                    shadow_payload=payload,
                )
            except Exception as exc:  # noqa: BLE001
                qid = self._quarantine(
                    key=key,
                    operation_id=op_id,
                    reason=f"shard_manifest_failed: {exc}",
                )
                return ShadowCreateResult(
                    ok=False,
                    authority="legacy",
                    collection_id=collection_id or "",
                    operation_id=op_id,
                    quarantined=True,
                    quarantine_id=qid,
                    error=str(exc),
                )

    def shadow_knn_mapping(
        self,
        *,
        logical_name: str,
        mapping: Mapping[str, Any],
        dimension: int,
        dtype: str = "float32",
        source_revision: str = "knn-1",
        operation_id: Optional[str] = None,
    ) -> ShadowCreateResult:
        """Shadow IPFS KNN id mappings as a catalog collection."""

        return self.shadow_create(
            logical_name=logical_name,
            backend="ipfs_knn",
            dimension=dimension,
            dtype=dtype,
            mapping=mapping,
            source_revision=source_revision,
            model_name="ipfs-knn",
            model_provider="ipfs",
            model_revision="1",
            chunking_identity="chunk:knn@1",
            normalization_identity="norm:knn@1",
            metadata_json={"producer": "ipfs_knn_index"},
            operation_id=operation_id,
        )

    def get_exact_identities(
        self, *, logical_name: str, backend: str
    ) -> Optional[Dict[str, Any]]:
        """Return exact dimension/dtype/model/chunking/norm/source revision."""

        key = self._legacy_key(logical_name, backend)
        collection_id = self._logical_to_collection.get(key)
        if not collection_id or self._store is None:
            return None
        try:
            col = self._store.get_collection(collection_id)
            return {
                "collection_id": col.collection_id,
                "dimension": col.dimension,
                "dtype": col.dtype,
                "model_id": col.model_id,
                "chunking_identity": col.chunking_identity,
                "normalization_identity": col.normalization_identity,
                "source_revision": col.source_revision,
                "published_generation": col.published_generation,
            }
        except Exception:
            return None


# -- process-local catalog registry ----------------------------------------


def configure_vector_shadow_catalog(
    catalog_path: Union[str, Path, None] = None,
    *,
    enabled: bool = True,
    authority_port: Any = None,
    replace: bool = True,
) -> VectorShadowCatalog:
    """Install the process-local shadow catalog used by all producers."""

    global _process_catalog
    with _process_catalog_lock:
        if _process_catalog is not None and not replace:
            return _process_catalog
        if _process_catalog is not None:
            try:
                _process_catalog.close()
            except Exception:  # noqa: BLE001
                pass
        _process_catalog = VectorShadowCatalog(
            catalog_path,
            enabled=enabled,
            authority_port=authority_port,
        )
        return _process_catalog


def get_vector_shadow_catalog(
    *, create_if_missing: bool = False, catalog_path: Union[str, Path, None] = None
) -> Optional[VectorShadowCatalog]:
    """Return the process-local shadow catalog (optionally create)."""

    global _process_catalog
    with _process_catalog_lock:
        if _process_catalog is None and create_if_missing:
            _process_catalog = VectorShadowCatalog(catalog_path)
        return _process_catalog


def reset_vector_shadow_catalog() -> None:
    """Drop the process-local catalog (tests)."""

    global _process_catalog
    with _process_catalog_lock:
        if _process_catalog is not None:
            try:
                _process_catalog.close()
            except Exception:  # noqa: BLE001
                pass
        _process_catalog = None


def safe_shadow_create(**kwargs: Any) -> Optional[ShadowCreateResult]:
    """Best-effort shadow create for producers (never raises)."""

    catalog = get_vector_shadow_catalog()
    if catalog is None or not catalog.enabled:
        return None
    try:
        return catalog.shadow_create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("safe_shadow_create failed: %s", exc)
        return ShadowCreateResult(
            ok=False, authority="legacy", error=str(exc), quarantined=True
        )


def safe_shadow_delete(
    *, logical_name: str, backend: str
) -> Optional[ShadowCreateResult]:
    catalog = get_vector_shadow_catalog()
    if catalog is None or not catalog.enabled:
        return None
    try:
        return catalog.shadow_delete(
            logical_name=logical_name, backend=backend
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("safe_shadow_delete failed: %s", exc)
        return ShadowCreateResult(
            ok=False, authority="legacy", error=str(exc), quarantined=True
        )


def safe_shadow_list(*, backend: Optional[str] = None) -> Optional[Dict[str, Any]]:
    catalog = get_vector_shadow_catalog()
    if catalog is None or not catalog.enabled:
        return None
    try:
        return catalog.shadow_list(backend=backend)
    except Exception as exc:  # noqa: BLE001
        logger.warning("safe_shadow_list failed: %s", exc)
        return {
            "status": "error",
            "authority": "legacy",
            "error": str(exc),
            "collections": [],
        }


class VectorStoreManager:
    """
    Manages vector store indexes across FAISS, Qdrant, and Elasticsearch backends.

    All methods that require embedding generation or I/O are async; pure
    routing/listing methods are sync.

    When a process-local :class:`VectorShadowCatalog` is configured, create /
    list / delete entrypoints dual-write lifecycle metadata into DuckDB while
    legacy on-disk / remote backends remain the authority (DQK-062).
    """

    def __init__(
        self,
        indexes_dir: str = _INDEXES_DIR,
        *,
        shadow_catalog: Optional[VectorShadowCatalog] = None,
    ) -> None:
        """Initialise the manager with the on-disk FAISS index directory."""
        self.indexes_dir = indexes_dir
        self.shadow_catalog = shadow_catalog
    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_index(
        self,
        index_name: str,
        documents: List[Dict[str, Any]],
        backend: str = "faiss",
        vector_dim: int = 384,
        distance_metric: str = "cosine",
        index_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a vector index on the requested backend."""
        if backend == "faiss":
            return await self._create_faiss_index(
                index_name, documents, vector_dim, distance_metric, index_config
            )
        if backend == "qdrant":
            return await self._create_qdrant_index(
                index_name, documents, vector_dim, distance_metric, index_config
            )
        if backend == "elasticsearch":
            return await self._create_elasticsearch_index(
                index_name, documents, vector_dim, distance_metric, index_config
            )
        return {
            "status": "error",
            "error": f"Unsupported backend: {backend}",
            "supported_backends": ["faiss", "qdrant", "elasticsearch"],
        }

    async def _create_faiss_index(
        self,
        index_name: str,
        documents: List[Dict[str, Any]],
        vector_dim: int,
        distance_metric: str,
        config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Create a FAISS vector index."""
        if not FAISS_AVAILABLE:
            return {
                "status": "error",
                "error": "FAISS not available. Install with: pip install faiss-cpu",
            }
        if not EMBEDDINGS_AVAILABLE:
            return {"status": "error", "error": "Embeddings engine not available"}
        try:
            import numpy as np  # type: ignore

            index = (
                faiss.IndexFlatIP(vector_dim)
                if distance_metric in ("cosine", "dot_product")
                else faiss.IndexFlatL2(vector_dim)
            )
            texts = [doc.get("text", "") for doc in documents]
            resources = {"local_endpoints": [["thenlper/gte-small", "cpu", 512]]}
            engine = AdvancedIPFSEmbeddings(resources, {})
            embeddings = await engine.generate_embeddings(texts, "thenlper/gte-small")
            if distance_metric == "cosine":
                faiss.normalize_L2(embeddings)
            index.add(embeddings)

            index_dir = os.path.join(self.indexes_dir, index_name)
            os.makedirs(index_dir, exist_ok=True)
            faiss.write_index(index, os.path.join(index_dir, "index.faiss"))
            metadata: Dict[str, Any] = {
                "index_name": index_name,
                "backend": "faiss",
                "vector_dim": vector_dim,
                "distance_metric": distance_metric,
                "document_count": len(documents),
                "documents": documents,
            }
            with open(os.path.join(index_dir, "metadata.json"), "w") as fh:
                json.dump(metadata, fh, indent=2)
            result = {
                "status": "success",
                "index_name": index_name,
                "backend": "faiss",
                "vector_dim": vector_dim,
                "document_count": len(documents),
                "index_path": index_dir,
            }
            shadow = self._shadow_after_create(
                logical_name=index_name,
                backend="faiss",
                dimension=vector_dim,
                vector_ids=[f"doc_{i}" for i in range(len(documents))],
                vectors=[
                    emb.tolist() if hasattr(emb, "tolist") else list(emb)
                    for emb in embeddings
                ],
                metadata_json=metadata,
                normalization_identity=(
                    "norm:l2@1"
                    if distance_metric == "cosine"
                    else "norm:none@1"
                ),
                index_build={
                    "index_kind": "faiss",
                    "status": "completed",
                    "distance_metric": distance_metric,
                },
            )
            if shadow is not None:
                result["shadow"] = shadow.to_dict()
            return result
        except (OSError, ValueError, RuntimeError) as e:
            logger.error(f"Error creating FAISS index: {e}")
            return {"status": "error", "error": str(e), "backend": "faiss"}

    async def _create_qdrant_index(
        self,
        index_name: str,
        documents: List[Dict[str, Any]],
        vector_dim: int,
        distance_metric: str,
        config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Create a Qdrant collection."""
        if not QDRANT_AVAILABLE:
            return {
                "status": "error",
                "error": "Qdrant client not available. Install with: pip install qdrant-client",
            }
        if not EMBEDDINGS_AVAILABLE:
            return {"status": "error", "error": "Embeddings engine not available"}
        try:
            url = (config or {}).get("url", "localhost")
            port = (config or {}).get("port", 6333)
            client = QdrantClient(host=url, port=port)
            distance_map = {
                "cosine": qdrant_models.Distance.COSINE,
                "euclidean": qdrant_models.Distance.EUCLID,
                "dot_product": qdrant_models.Distance.DOT,
            }
            client.create_collection(
                collection_name=index_name,
                vectors_config=qdrant_models.VectorParams(
                    size=vector_dim,
                    distance=distance_map.get(distance_metric, qdrant_models.Distance.COSINE),
                ),
            )
            texts = [doc.get("text", "") for doc in documents]
            resources = {"local_endpoints": [["thenlper/gte-small", "cpu", 512]]}
            engine = AdvancedIPFSEmbeddings(resources, {})
            embeddings = await engine.generate_embeddings(texts, "thenlper/gte-small")
            points = [
                qdrant_models.PointStruct(
                    id=i,
                    vector=emb.tolist(),
                    payload={"text": doc.get("text", ""), "metadata": doc.get("metadata", {})},
                )
                for i, (doc, emb) in enumerate(zip(documents, embeddings))
            ]
            client.upsert(collection_name=index_name, points=points)
            result = {
                "status": "success",
                "index_name": index_name,
                "backend": "qdrant",
                "vector_dim": vector_dim,
                "document_count": len(documents),
                "collection_name": index_name,
            }
            shadow = self._shadow_after_create(
                logical_name=index_name,
                backend="qdrant",
                dimension=vector_dim,
                vector_ids=[str(i) for i in range(len(documents))],
                vectors=[
                    emb.tolist() if hasattr(emb, "tolist") else list(emb)
                    for emb in embeddings
                ],
                metadata_json={
                    "index_name": index_name,
                    "backend": "qdrant",
                    "vector_dim": vector_dim,
                    "document_count": len(documents),
                },
                index_build={
                    "index_kind": "qdrant",
                    "status": "completed",
                    "distance_metric": distance_metric,
                },
            )
            if shadow is not None:
                result["shadow"] = shadow.to_dict()
            return result
        except (OSError, ValueError, RuntimeError) as e:
            logger.error(f"Error creating Qdrant index: {e}")
            return {"status": "error", "error": str(e), "backend": "qdrant"}

    async def _create_elasticsearch_index(
        self,
        index_name: str,
        documents: List[Dict[str, Any]],
        vector_dim: int,
        distance_metric: str,
        config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Create an Elasticsearch vector index."""
        if not ELASTICSEARCH_AVAILABLE:
            return {
                "status": "error",
                "error": "Elasticsearch not available. Install with: pip install elasticsearch",
            }
        if not EMBEDDINGS_AVAILABLE:
            return {"status": "error", "error": "Embeddings engine not available"}
        try:
            es_url = (config or {}).get("url", "localhost:9200")
            es = Elasticsearch([es_url])
            mapping = {
                "mappings": {
                    "properties": {
                        "text": {"type": "text"},
                        "vector": {
                            "type": "dense_vector",
                            "dims": vector_dim,
                            "index": True,
                            "similarity": "cosine" if distance_metric == "cosine" else "l2_norm",
                        },
                        "metadata": {"type": "object"},
                    }
                }
            }
            es.indices.create(index=index_name, body=mapping)
            texts = [doc.get("text", "") for doc in documents]
            resources = {"local_endpoints": [["thenlper/gte-small", "cpu", 512]]}
            engine = AdvancedIPFSEmbeddings(resources, {})
            embeddings = await engine.generate_embeddings(texts, "thenlper/gte-small")
            for i, (doc, emb) in enumerate(zip(documents, embeddings)):
                es.index(
                    index=index_name,
                    id=i,
                    body={
                        "text": doc.get("text", ""),
                        "vector": emb.tolist(),
                        "metadata": doc.get("metadata", {}),
                    },
                )
            es.indices.refresh(index=index_name)
            result = {
                "status": "success",
                "index_name": index_name,
                "backend": "elasticsearch",
                "vector_dim": vector_dim,
                "document_count": len(documents),
                "es_index": index_name,
            }
            shadow = self._shadow_after_create(
                logical_name=index_name,
                backend="elasticsearch",
                dimension=vector_dim,
                vector_ids=[str(i) for i in range(len(documents))],
                vectors=[
                    emb.tolist() if hasattr(emb, "tolist") else list(emb)
                    for emb in embeddings
                ],
                metadata_json={
                    "index_name": index_name,
                    "backend": "elasticsearch",
                    "vector_dim": vector_dim,
                    "document_count": len(documents),
                },
                index_build={
                    "index_kind": "elasticsearch",
                    "status": "completed",
                    "distance_metric": distance_metric,
                },
            )
            if shadow is not None:
                result["shadow"] = shadow.to_dict()
            return result
        except (OSError, ValueError, RuntimeError) as e:
            logger.error(f"Error creating Elasticsearch index: {e}")
            return {"status": "error", "error": str(e), "backend": "elasticsearch"}

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search_index(
        self,
        index_name: str,
        query: str,
        backend: str = "faiss",
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Search a vector index for similar documents."""
        if backend == "faiss":
            return await self._search_faiss_index(index_name, query, top_k, config)
        if backend in ("qdrant", "elasticsearch"):
            return {
                "status": "error",
                "error": f"Backend '{backend}' search is not implemented in this build",
                "index_name": index_name,
                "backend": backend,
            }
        return {"status": "error", "error": f"Unsupported backend: {backend}"}

    async def _search_faiss_index(
        self,
        index_name: str,
        query: str,
        top_k: int,
        config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Search a FAISS index."""
        if not FAISS_AVAILABLE:
            return {"status": "error", "error": "FAISS not available"}
        if not EMBEDDINGS_AVAILABLE:
            return {"status": "error", "error": "Embeddings engine not available"}
        try:
            index_dir = os.path.join(self.indexes_dir, index_name)
            faiss_path = os.path.join(index_dir, "index.faiss")
            if not os.path.exists(faiss_path):
                return {"status": "error", "error": f"FAISS index not found: {index_name}"}
            index = faiss.read_index(faiss_path)
            with open(os.path.join(index_dir, "metadata.json")) as fh:
                metadata = json.load(fh)
            resources = {"local_endpoints": [["thenlper/gte-small", "cpu", 512]]}
            engine = AdvancedIPFSEmbeddings(resources, {})
            qemb = await engine.generate_embeddings([query], "thenlper/gte-small")
            q_vec = qemb[0].reshape(1, -1)
            if metadata.get("distance_metric") == "cosine":
                faiss.normalize_L2(q_vec)
            scores, indices = index.search(q_vec, top_k)
            docs = metadata.get("documents", [])
            results = [
                {"document": docs[idx], "score": float(score), "index": int(idx)}
                for score, idx in zip(scores[0], indices[0])
                if idx < len(docs)
            ]
            return {
                "status": "success",
                "query": query,
                "results": results,
                "total_results": len(results),
                "backend": "faiss",
                "index_name": index_name,
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error(f"Error searching FAISS index: {e}")
            return {"status": "error", "error": str(e), "backend": "faiss"}

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def list_indexes(self, backend: str = "all") -> Dict[str, Any]:
        """List available vector indexes (FAISS only in this build)."""
        try:
            indexes: Dict[str, Any] = {}
            if backend in ("all", "faiss"):
                faiss_indexes: List[Dict[str, Any]] = []
                if os.path.exists(self.indexes_dir):
                    for item in os.listdir(self.indexes_dir):
                        item_path = os.path.join(self.indexes_dir, item)
                        faiss_path = os.path.join(item_path, "index.faiss")
                        if os.path.isdir(item_path) and os.path.exists(faiss_path):
                            meta_path = os.path.join(item_path, "metadata.json")
                            if os.path.exists(meta_path):
                                with open(meta_path) as fh:
                                    meta = json.load(fh)
                                faiss_indexes.append({
                                    "name": item,
                                    "backend": "faiss",
                                    "vector_dim": meta.get("vector_dim"),
                                    "document_count": meta.get("document_count"),
                                    "distance_metric": meta.get("distance_metric"),
                                })
                indexes["faiss"] = faiss_indexes
            result = {
                "status": "success",
                "backend": backend,
                "indexes": indexes,
            }
            shadow_list = self._shadow_list(
                backend=None if backend == "all" else backend
            )
            if shadow_list is not None:
                result["shadow"] = shadow_list
            return result
        except OSError as e:
            logger.error(f"Error listing vector indexes: {e}")
            return {"status": "error", "error": str(e), "backend": backend}

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_index(
        self,
        index_name: str,
        backend: str = "faiss",
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Delete a vector index."""
        try:
            if backend == "faiss":
                index_dir = os.path.join(self.indexes_dir, index_name)
                if os.path.exists(index_dir):
                    shutil.rmtree(index_dir)
                    result = {
                        "status": "success",
                        "message": f"FAISS index {index_name} deleted",
                        "backend": "faiss",
                    }
                    shadow = self._shadow_after_delete(
                        logical_name=index_name, backend="faiss"
                    )
                    if shadow is not None:
                        result["shadow"] = shadow.to_dict()
                    return result
                return {
                    "status": "error",
                    "error": f"FAISS index {index_name} not found",
                    "backend": "faiss",
                }

            if backend == "qdrant":
                if not QDRANT_AVAILABLE:
                    return {"status": "error", "error": "Qdrant client not available"}
                url = (config or {}).get("url", "localhost")
                port = (config or {}).get("port", 6333)
                client = QdrantClient(host=url, port=port)
                client.delete_collection(collection_name=index_name)
                result = {
                    "status": "success",
                    "message": f"Qdrant collection {index_name} deleted",
                    "backend": "qdrant",
                }
                shadow = self._shadow_after_delete(
                    logical_name=index_name, backend="qdrant"
                )
                if shadow is not None:
                    result["shadow"] = shadow.to_dict()
                return result

            if backend == "elasticsearch":
                if not ELASTICSEARCH_AVAILABLE:
                    return {"status": "error", "error": "Elasticsearch not available"}
                es_url = (config or {}).get("url", "localhost:9200")
                es = Elasticsearch([es_url])
                es.indices.delete(index=index_name)
                result = {
                    "status": "success",
                    "message": f"Elasticsearch index {index_name} deleted",
                    "backend": "elasticsearch",
                }
                shadow = self._shadow_after_delete(
                    logical_name=index_name, backend="elasticsearch"
                )
                if shadow is not None:
                    result["shadow"] = shadow.to_dict()
                return result

            return {"status": "error", "error": f"Unsupported backend: {backend}"}

        except (OSError, ValueError, RuntimeError) as e:
            logger.error(f"Error deleting vector index: {e}")
            return {
                "status": "error",
                "error": str(e),
                "index_name": index_name,
                "backend": backend,
            }

    # ------------------------------------------------------------------
    # DuckDB shadow catalog helpers (DQK-062)
    # ------------------------------------------------------------------

    def _resolve_shadow(self) -> Optional[VectorShadowCatalog]:
        if self.shadow_catalog is not None:
            return self.shadow_catalog
        return get_vector_shadow_catalog()

    def _shadow_after_create(self, **kwargs: Any) -> Optional[ShadowCreateResult]:
        catalog = self._resolve_shadow()
        if catalog is None or not catalog.enabled:
            return None
        try:
            return catalog.shadow_create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("shadow create failed (legacy unchanged): %s", exc)
            return ShadowCreateResult(
                ok=False, authority="legacy", error=str(exc), quarantined=True
            )

    def _shadow_after_delete(
        self, *, logical_name: str, backend: str
    ) -> Optional[ShadowCreateResult]:
        catalog = self._resolve_shadow()
        if catalog is None or not catalog.enabled:
            return None
        try:
            return catalog.shadow_delete(
                logical_name=logical_name, backend=backend
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("shadow delete failed (legacy unchanged): %s", exc)
            return ShadowCreateResult(
                ok=False, authority="legacy", error=str(exc), quarantined=True
            )

    def _shadow_list(
        self, *, backend: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        catalog = self._resolve_shadow()
        if catalog is None or not catalog.enabled:
            return None
        try:
            return catalog.shadow_list(backend=backend)
        except Exception as exc:  # noqa: BLE001
            logger.warning("shadow list failed (legacy unchanged): %s", exc)
            return {
                "status": "error",
                "authority": "legacy",
                "error": str(exc),
                "collections": [],
            }


__all__ = [
    "VectorStoreManager",
    "VectorShadowCatalog",
    "ShadowCreateResult",
    "ShadowParityView",
    "VECTOR_SHADOW_DOMAIN",
    "VECTOR_SHADOW_SCHEMA",
    "VECTOR_SHADOW_OWNER_TASK",
    "configure_vector_shadow_catalog",
    "get_vector_shadow_catalog",
    "reset_vector_shadow_catalog",
    "safe_shadow_create",
    "safe_shadow_delete",
    "safe_shadow_list",
    "sanitize_collection_slug",
    "sanitize_id",
    "FAISS_AVAILABLE",
    "QDRANT_AVAILABLE",
    "ELASTICSEARCH_AVAILABLE",
    "EMBEDDINGS_AVAILABLE",
]
