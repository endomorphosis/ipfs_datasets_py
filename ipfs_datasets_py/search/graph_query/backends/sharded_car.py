from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import gzip
import json
import hashlib
from typing import Any, Mapping, Protocol, Sequence

from .... import ipfs_backend_router as ipfs_router
from ....data_transformation.ipld.knowledge_graph import IPLDKnowledgeGraph
from ipfs_datasets_py.search.graph_query.backend import (
    EntityHeader,
    GraphBackend,
    NeighborEdge,
    NeighborPage,
    ScanPage,
)
from ipfs_datasets_py.search.graph_query.sharded_car.bloom import BloomFilter
from ipfs_datasets_py.search.graph_query.sharded_car.manifest import GraphShardManifest, ShardInfo
from ipfs_datasets_py.search.graph_query.sharded_car.routing import stable_shard_index

try:
    import ipld_car  # type: ignore

    HAVE_IPLD_CAR = True
except Exception:
    HAVE_IPLD_CAR = False


class CarFetcher(Protocol):
    def fetch(self, car_cid: str) -> bytes:
        ...


class BytesFetcher(Protocol):
    def fetch(self, cid: str) -> bytes:
        ...


@dataclass(frozen=True)
class InMemoryCarFetcher(CarFetcher):
    cars: Mapping[str, bytes]

    def fetch(self, car_cid: str) -> bytes:
        data = self.cars.get(car_cid)
        if data is None:
            raise KeyError(f"No CAR bytes for cid={car_cid}")
        return data


@dataclass(frozen=True)
class IPFSCarFetcher(CarFetcher):
    """Fetch CAR bytes from IPFS via the ipfs_backend_router.

    The common case is that `car_cid` is a CID of a stored CAR file, so
    `cat(car_cid)` returns the CAR bytes.

    For some backends/workflows, `car_cid` may instead be a DAG root and the
    CAR is produced via `dag_export`. The `mode` can be used to control this.
    """

    backend: str | None = None
    backend_instance: ipfs_router.IPFSBackend | None = None
    mode: str = "auto"  # auto|cat|block_get|dag_export

    def fetch(self, car_cid: str) -> bytes:
        last_err: Exception | None = None
        mode = (self.mode or "auto").strip().lower()

        def _try(op: str) -> bytes | None:
            nonlocal last_err
            try:
                if op == "cat":
                    return ipfs_router.cat(car_cid, backend=self.backend, backend_instance=self.backend_instance)
                if op == "block_get":
                    return ipfs_router.block_get(car_cid, backend=self.backend, backend_instance=self.backend_instance)
                if op == "dag_export":
                    return ipfs_router.dag_export(car_cid, backend=self.backend, backend_instance=self.backend_instance)
                raise ValueError(f"Unknown fetch op: {op}")
            except Exception as e:  # pragma: no cover - depends on backend availability
                last_err = e
                return None

        if mode == "cat":
            out = _try("cat")
            if out is not None:
                return out
        elif mode == "block_get":
            out = _try("block_get")
            if out is not None:
                return out
        elif mode == "dag_export":
            out = _try("dag_export")
            if out is not None:
                return out
        else:
            for op in ("cat", "block_get", "dag_export"):
                out = _try(op)
                if out is not None:
                    return out

        raise RuntimeError(f"Failed to fetch CAR bytes for cid={car_cid}") from last_err


@dataclass(frozen=True)
class IPFSBytesFetcher(BytesFetcher):
    """Fetch arbitrary bytes from IPFS via the ipfs_backend_router."""

    backend: str | None = None
    backend_instance: ipfs_router.IPFSBackend | None = None
    mode: str = "auto"  # auto|cat|block_get|dag_export

    def fetch(self, cid: str) -> bytes:
        # Reuse the same retrieval strategies as CAR fetching.
        return IPFSCarFetcher(
            backend=self.backend,
            backend_instance=self.backend_instance,
            mode=self.mode,
        ).fetch(cid)


class _BlockMapStorage:
    """Minimal storage adapter for IPLDKnowledgeGraph.from_cid.

    IPLDKnowledgeGraph.from_cid only requires a `get(cid)->bytes` method.
    """

    def __init__(self, blocks: Mapping[str, bytes]):
        self._blocks = blocks

    def get(self, cid: str) -> bytes:
        data = self._blocks.get(cid)
        if data is None:
            raise ValueError(f"Missing block cid={cid}")
        return data


class ShardLoader(Protocol):
    def load_kg(self, shard: ShardInfo) -> IPLDKnowledgeGraph:
        ...


@dataclass(frozen=True)
class InMemoryShardLoader(ShardLoader):
    """Test/dev loader that serves pre-constructed shard graphs."""

    shards: Mapping[str, IPLDKnowledgeGraph]

    def load_kg(self, shard: ShardInfo) -> IPLDKnowledgeGraph:
        kg = self.shards.get(shard.shard_id)
        if kg is None:
            raise KeyError(f"No in-memory shard for shard_id={shard.shard_id}")
        return kg


@dataclass(frozen=True)
class CARBytesShardLoader(ShardLoader):
    """Loads a shard by decoding a CAR byte stream."""

    fetcher: CarFetcher

    def load_kg(self, shard: ShardInfo) -> IPLDKnowledgeGraph:
        if not HAVE_IPLD_CAR:
            raise ImportError("ipld_car is required to load shards from CAR bytes")

        car_bytes = self.fetcher.fetch(shard.car_cid)
        roots, blocks = ipld_car.decode(car_bytes)
        if not roots:
            raise ValueError("CAR has no roots")

        def _cid_str(cid_obj: Any) -> str:
            # multiformats.CID can encode to specific multibase.
            if hasattr(cid_obj, "encode"):
                try:
                    return cid_obj.encode("base32")
                except Exception:
                    return str(cid_obj)
            return str(cid_obj)

        root_cid = _cid_str(roots[0])
        if hasattr(blocks, "items"):
            pairs = list(blocks.items())
        else:
            pairs = list(blocks)
        block_map = {_cid_str(cid): data for cid, data in pairs}
        storage = _BlockMapStorage(block_map)
        return IPLDKnowledgeGraph.from_cid(root_cid, storage=storage)


class ShardedCARBackend(GraphBackend):
    """GraphBackend implementation over a sharded graph described by a manifest.

    v1 behavior:
    - `ScanType` uses per-shard bloom filters to choose candidate shards.
    - `neighbors`/`headers` use deterministic routing (sha256(entity_id) mod N).

    Notes:
    - `scope` is interpreted as an optional allow-list of shard_ids.
    - This backend intentionally keeps the storage/index design pluggable.
    """

    def __init__(
        self,
        manifest: GraphShardManifest,
        *,
        loader: ShardLoader,
        index_fetcher: BytesFetcher | None = None,
        cache_size: int = 8,
    ) -> None:
        if not manifest.shards:
            raise ValueError("manifest must contain at least one shard")
        self._manifest = manifest
        self._loader = loader
        self._index_fetcher = index_fetcher
        self._cache_size = max(0, int(cache_size))
        self._kg_cache: "OrderedDict[str, IPLDKnowledgeGraph]" = OrderedDict()

        self._headers_cache: dict[str, dict[str, EntityHeader]] = {}
        # Headers index caches:
        # - v1: shard_id -> {entity_id -> EntityHeader}
        # - v2: shard_id -> (prefix_len, {bucket_key -> bucket_cid})
        self._headers_index_v2_meta_cache: dict[str, tuple[int, dict[str, str]]] = {}
        self._headers_bucket_cache: "OrderedDict[str, dict[str, EntityHeader]]" = OrderedDict()
        self._headers_bucket_cache_size: int = 256
        # Type index caches:
        # - v1: shard_id -> {entity_type -> [entity_id]}
        # - v2: shard_id -> {entity_type -> [page_cid]}
        self._type_index_cache: dict[str, dict[str, list[str]]] = {}
        self._type_index_pages_cache: dict[str, dict[str, list[str]]] = {}
        self._type_index_page_data_cache: "OrderedDict[str, list[str]]" = OrderedDict()
        self._type_index_page_data_cache_size: int = 256
        # Neighbors index caches:
        # - v1: shard_id -> {entity_id -> adjacency_cid}
        # - v2: shard_id -> (prefix_len, {bucket_key -> bucket_cid})
        self._neighbors_index_cache: dict[str, dict[str, str]] = {}
        self._neighbors_index_v2_meta_cache: dict[str, tuple[int, dict[str, str]]] = {}
        self._neighbors_bucket_cache: "OrderedDict[str, dict[str, str]]" = OrderedDict()
        self._neighbors_bucket_cache_size: int = 256

        # Deterministic routing depends on a stable shard ordering.
        self._shards_sorted = sorted(manifest.shards, key=lambda s: s.shard_id)
        self._shard_by_id = {s.shard_id: s for s in self._shards_sorted}

    def _fetch_json(self, cid: str) -> Any:
        if self._index_fetcher is None:
            raise RuntimeError("index_fetcher is required to load shard indexes")
        data = self._index_fetcher.fetch(cid)
        # Index blocks may be stored as plain UTF-8 JSON or gzip-compressed JSON.
        if len(data) >= 2 and data[0:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return json.loads(data.decode("utf-8"))

    def _get_shard_headers(self, shard_id: str) -> dict[str, EntityHeader] | None:
        if shard_id in self._headers_cache:
            return self._headers_cache[shard_id]

        shard = self._shard_by_id.get(shard_id)
        if shard is None or not shard.headers_cid:
            return None
        try:
            obj = self._fetch_json(shard.headers_cid)
        except Exception:
            return None

        if not isinstance(obj, dict):
            return None

        # v2 bucketed index is handled by _get_shard_headers_v2.
        if int(obj.get("v", 1)) == 2:
            return None
        headers: dict[str, EntityHeader] = {}
        for eid, h in obj.items():
            if not isinstance(h, dict):
                continue
            headers[str(eid)] = EntityHeader(
                id=str(eid),
                type=str(h.get("type") or ""),
                name=h.get("name"),
                cid=h.get("cid"),
                properties=h.get("properties") if isinstance(h.get("properties"), dict) else None,
            )
        self._headers_cache[shard_id] = headers
        return headers

    def _get_shard_headers_v2(self, shard_id: str) -> tuple[int, dict[str, str]] | None:
        if shard_id in self._headers_index_v2_meta_cache:
            return self._headers_index_v2_meta_cache[shard_id]

        shard = self._shard_by_id.get(shard_id)
        if shard is None or not shard.headers_cid:
            return None

        try:
            obj = self._fetch_json(shard.headers_cid)
        except Exception:
            return None

        if not isinstance(obj, dict) or int(obj.get("v", 1)) != 2:
            return None

        prefix_len = int(obj.get("prefix_len", 0))
        buckets = obj.get("buckets")
        if prefix_len <= 0 or not isinstance(buckets, dict):
            return None

        bucket_map: dict[str, str] = {}
        for k, v in buckets.items():
            if isinstance(k, str) and isinstance(v, str):
                bucket_map[k] = v

        meta = (prefix_len, bucket_map)
        self._headers_index_v2_meta_cache[shard_id] = meta
        return meta

    def _bucket_key(self, entity_id: str, *, prefix_len: int) -> str:
        # Use sha256(entity_id) hex prefix for stable, balanced buckets.
        digest = hashlib.sha256(entity_id.encode("utf-8", errors="strict")).hexdigest()
        return digest[: max(1, int(prefix_len))]

    def _get_headers_bucket(self, bucket_cid: str) -> dict[str, EntityHeader] | None:
        if bucket_cid in self._headers_bucket_cache:
            m = self._headers_bucket_cache.pop(bucket_cid)
            self._headers_bucket_cache[bucket_cid] = m
            return m

        try:
            obj = self._fetch_json(bucket_cid)
        except Exception:
            return None

        if not isinstance(obj, dict):
            return None

        m: dict[str, EntityHeader] = {}
        for eid, h in obj.items():
            if not isinstance(eid, str) or not isinstance(h, dict):
                continue
            m[eid] = EntityHeader(
                id=eid,
                type=str(h.get("type") or ""),
                name=h.get("name"),
                cid=h.get("cid"),
                properties=h.get("properties") if isinstance(h.get("properties"), dict) else None,
            )

        self._headers_bucket_cache[bucket_cid] = m
        while len(self._headers_bucket_cache) > self._headers_bucket_cache_size:
            self._headers_bucket_cache.popitem(last=False)

        return m

    def _get_shard_type_index_v1(self, shard_id: str) -> dict[str, list[str]] | None:
        if shard_id in self._type_index_cache:
            return self._type_index_cache[shard_id]

        shard = self._shard_by_id.get(shard_id)
        if shard is None or not shard.type_index_cid:
            return None
        try:
            obj = self._fetch_json(shard.type_index_cid)
        except Exception:
            return None

        if not isinstance(obj, dict):
            return None

        # v2 is handled by _get_shard_type_index_pages.
        if int(obj.get("v", 1)) == 2:
            return None

        idx: dict[str, list[str]] = {}
        for et, ids in obj.items():
            if not isinstance(ids, list):
                continue
            idx[str(et)] = [str(x) for x in ids]
        self._type_index_cache[shard_id] = idx
        return idx

    def _get_shard_type_index_pages(self, shard_id: str) -> dict[str, list[str]] | None:
        if shard_id in self._type_index_pages_cache:
            return self._type_index_pages_cache[shard_id]

        shard = self._shard_by_id.get(shard_id)
        if shard is None or not shard.type_index_cid:
            return None

        try:
            obj = self._fetch_json(shard.type_index_cid)
        except Exception:
            return None

        if not isinstance(obj, dict) or int(obj.get("v", 1)) != 2:
            return None

        types = obj.get("types")
        if not isinstance(types, dict):
            return None

        pages: dict[str, list[str]] = {}
        for et, page_cids in types.items():
            if not isinstance(page_cids, list):
                continue
            pages[str(et)] = [str(x) for x in page_cids if isinstance(x, str) or x is not None]

        self._type_index_pages_cache[shard_id] = pages
        return pages

    def _get_type_index_page_ids(self, page_cid: str) -> list[str] | None:
        if page_cid in self._type_index_page_data_cache:
            ids = self._type_index_page_data_cache.pop(page_cid)
            self._type_index_page_data_cache[page_cid] = ids
            return ids

        try:
            obj = self._fetch_json(page_cid)
        except Exception:
            return None

        if not isinstance(obj, list):
            return None
        ids = [str(x) for x in obj]

        self._type_index_page_data_cache[page_cid] = ids
        while len(self._type_index_page_data_cache) > self._type_index_page_data_cache_size:
            self._type_index_page_data_cache.popitem(last=False)

        return ids

    def _get_shard_neighbors_index(self, shard_id: str) -> dict[str, str] | None:
        if shard_id in self._neighbors_index_cache:
            return self._neighbors_index_cache[shard_id]

        shard = self._shard_by_id.get(shard_id)
        if shard is None or not shard.neighbors_index_cid:
            return None
        try:
            obj = self._fetch_json(shard.neighbors_index_cid)
        except Exception:
            return None

        if not isinstance(obj, dict):
            return None

        # v2 bucketed index is handled by _get_shard_neighbors_index_v2.
        if int(obj.get("v", 1)) == 2:
            return None
        idx: dict[str, str] = {}
        for eid, cid in obj.items():
            if isinstance(cid, str):
                idx[str(eid)] = cid
        self._neighbors_index_cache[shard_id] = idx
        return idx

    def _get_shard_neighbors_index_v2(self, shard_id: str) -> tuple[int, dict[str, str]] | None:
        if shard_id in self._neighbors_index_v2_meta_cache:
            return self._neighbors_index_v2_meta_cache[shard_id]

        shard = self._shard_by_id.get(shard_id)
        if shard is None or not shard.neighbors_index_cid:
            return None

        try:
            obj = self._fetch_json(shard.neighbors_index_cid)
        except Exception:
            return None

        if not isinstance(obj, dict) or int(obj.get("v", 1)) != 2:
            return None

        prefix_len = int(obj.get("prefix_len", 0))
        buckets = obj.get("buckets")
        if prefix_len <= 0 or not isinstance(buckets, dict):
            return None

        bucket_map: dict[str, str] = {}
        for k, v in buckets.items():
            if isinstance(k, str) and isinstance(v, str):
                bucket_map[k] = v

        meta = (prefix_len, bucket_map)
        self._neighbors_index_v2_meta_cache[shard_id] = meta
        return meta

    def _neighbors_bucket_key(self, entity_id: str, *, prefix_len: int) -> str:
        return self._bucket_key(entity_id, prefix_len=prefix_len)

    def _get_neighbors_bucket(self, bucket_cid: str) -> dict[str, str] | None:
        if bucket_cid in self._neighbors_bucket_cache:
            m = self._neighbors_bucket_cache.pop(bucket_cid)
            self._neighbors_bucket_cache[bucket_cid] = m
            return m

        try:
            obj = self._fetch_json(bucket_cid)
        except Exception:
            return None

        if not isinstance(obj, dict):
            return None

        m: dict[str, str] = {}
        for eid, cid in obj.items():
            if isinstance(eid, str) and isinstance(cid, str):
                m[eid] = cid

        self._neighbors_bucket_cache[bucket_cid] = m
        while len(self._neighbors_bucket_cache) > self._neighbors_bucket_cache_size:
            self._neighbors_bucket_cache.popitem(last=False)

        return m

    def _get_kg(self, shard_id: str) -> IPLDKnowledgeGraph:
        if shard_id in self._kg_cache:
            kg = self._kg_cache.pop(shard_id)
            self._kg_cache[shard_id] = kg
            return kg

        shard = self._shard_by_id.get(shard_id)
        if shard is None:
            raise KeyError(f"Unknown shard_id={shard_id}")

        kg = self._loader.load_kg(shard)

        if self._cache_size > 0:
            self._kg_cache[shard_id] = kg
            while len(self._kg_cache) > self._cache_size:
                self._kg_cache.popitem(last=False)

        return kg

    def _route_entity(self, entity_id: str) -> str:
        idx = stable_shard_index(entity_id, num_shards=len(self._shards_sorted))
        return self._shards_sorted[idx].shard_id

    def seed_exists(self, entity_id: str) -> bool:
        shard_id = self._route_entity(entity_id)
        headers = self._get_shard_headers(shard_id)
        if headers is not None:
            return entity_id in headers

        v2 = self._get_shard_headers_v2(shard_id)
        if v2 is not None:
            prefix_len, buckets = v2
            bkey = self._bucket_key(entity_id, prefix_len=prefix_len)
            bucket_cid = buckets.get(bkey)
            if bucket_cid:
                bucket = self._get_headers_bucket(bucket_cid)
                if bucket is not None:
                    h = bucket.get(entity_id)
                    return h is not None and bool(h.type)

        kg = self._get_kg(shard_id)
        return kg.get_entity(entity_id) is not None

    def get_entity_headers(self, entity_ids: Sequence[str]) -> dict[str, EntityHeader]:
        out: dict[str, EntityHeader] = {}

        # Group IDs by routed shard for more efficient index access.
        by_shard: dict[str, list[str]] = {}
        for eid in entity_ids:
            by_shard.setdefault(self._route_entity(eid), []).append(eid)

        for shard_id, eids in by_shard.items():
            headers = self._get_shard_headers(shard_id)
            if headers is not None:
                for eid in eids:
                    h = headers.get(eid)
                    if h is not None and h.type:
                        out[eid] = h
                continue

            v2 = self._get_shard_headers_v2(shard_id)
            if v2 is not None:
                prefix_len, buckets = v2
                # Group by bucket so we fetch each bucket at most once.
                by_bucket: dict[str, list[str]] = {}
                for eid in eids:
                    by_bucket.setdefault(self._bucket_key(eid, prefix_len=prefix_len), []).append(eid)

                for bkey, bucket_eids in by_bucket.items():
                    bucket_cid = buckets.get(bkey)
                    if not bucket_cid:
                        continue
                    bucket = self._get_headers_bucket(bucket_cid)
                    if bucket is None:
                        continue
                    for eid in bucket_eids:
                        h = bucket.get(eid)
                        if h is not None and h.type:
                            out[eid] = h
                continue

            kg = self._get_kg(shard_id)
            for eid in eids:
                ent = kg.get_entity(eid)
                if ent is None:
                    continue
                out[eid] = EntityHeader(
                    id=ent.id,
                    type=ent.type,
                    name=ent.name,
                    cid=getattr(ent, "cid", None),
                    properties=dict(ent.properties) if ent.properties is not None else None,
                )

        return out

    def get_entity_headers_with_stats(self, entity_ids: Sequence[str]) -> tuple[dict[str, EntityHeader], int]:
        # Count unique routed shards as a conservative estimate of shards touched.
        by_shard: dict[str, list[str]] = {}
        for eid in entity_ids:
            by_shard.setdefault(self._route_entity(eid), []).append(eid)
        return self.get_entity_headers(entity_ids), len(by_shard)

    def _candidate_shards_for_type(self, entity_type: str) -> list[str]:
        candidates: list[str] = []
        for shard in self._shards_sorted:
            if shard.entity_type_bloom is None:
                # No bloom metadata: must conservatively include.
                candidates.append(shard.shard_id)
                continue
            bf = BloomFilter.from_dict(shard.entity_type_bloom)
            if bf.might_contain(entity_type):
                candidates.append(shard.shard_id)
        return candidates

    def scan_type(
        self,
        entity_type: str,
        *,
        scope: Sequence[str] | None = None,
        limit: int = 100,
        cursor: str | None = None,
        shard_hints: Sequence[str] | None = None,
    ) -> ScanPage:
        _ = shard_hints
        limit = max(0, int(limit))

        allowlist = set(scope) if scope else None

        candidate_ids = self._candidate_shards_for_type(entity_type)
        if allowlist is not None:
            candidate_ids = [sid for sid in candidate_ids if sid in allowlist]

        if not candidate_ids or limit == 0:
            return ScanPage(entity_ids=[], next_cursor=None, shards_touched=0, shards_touched_ids=[])

        # Cursor format (opaque to callers):
        # v1: {"v":1,"shard_id":"S0","offset":123}
        # v2 (paged type-index): {"v":2,"shard_id":"S0","page":0,"offset":123}
        start_shard_id: str | None = None
        offset = 0
        page = 0
        cursor_v = 1
        if cursor:
            try:
                c = json.loads(cursor)
                if isinstance(c, dict):
                    cursor_v = int(c.get("v", 1))
                    if cursor_v not in {1, 2}:
                        raise ValueError("Invalid cursor")
                    start_shard_id = c.get("shard_id")
                    offset = int(c.get("offset", 0))
                    page = int(c.get("page", 0)) if cursor_v == 2 else 0
            except Exception:
                raise ValueError("Invalid cursor")

        shard_pos = 0
        if start_shard_id:
            try:
                shard_pos = candidate_ids.index(start_shard_id)
            except ValueError:
                raise ValueError("Cursor shard_id not in candidate set")

        entity_ids: list[str] = []
        shards_touched = 0
        touched_ids: list[str] = []

        def _scan_ids_for_shard_v1(sid: str) -> list[str] | None:
            idx = self._get_shard_type_index_v1(sid)
            if idx is None:
                return None
            return list(idx.get(entity_type, []))

        def _scan_ids_for_shard_paged(
            sid: str,
            *,
            start_page: int,
            start_offset: int,
            remaining: int,
        ) -> tuple[list[str], str | None]:
            pages_by_type = self._get_shard_type_index_pages(sid)
            if pages_by_type is None:
                return [], None

            page_cids = pages_by_type.get(entity_type) or []
            if not page_cids or remaining <= 0:
                return [], None

            out: list[str] = []
            p = max(0, int(start_page))
            off = max(0, int(start_offset))

            while p < len(page_cids) and len(out) < remaining:
                ids = self._get_type_index_page_ids(page_cids[p])
                if not ids:
                    # If the page is unreadable, stop paging and let caller fall back.
                    return [], None

                if off >= len(ids):
                    p += 1
                    off = 0
                    continue

                take = min(remaining - len(out), len(ids) - off)
                out.extend(ids[off : off + take])
                off += take

                if len(out) >= remaining:
                    more_in_page = off < len(ids)
                    if more_in_page:
                        next_cursor = json.dumps({"v": 2, "shard_id": sid, "page": p, "offset": off})
                        return out, next_cursor
                    # Advance to next page within this shard.
                    p += 1
                    off = 0
                    if p < len(page_cids):
                        next_cursor = json.dumps({"v": 2, "shard_id": sid, "page": p, "offset": 0})
                        return out, next_cursor
                    return out, None

                # Not full yet: go to next page.
                p += 1
                off = 0

            return out, None

        # Iterate shards until we fill `limit` or exhaust.
        while shard_pos < len(candidate_ids) and len(entity_ids) < limit:
            sid = candidate_ids[shard_pos]
            shards_touched += 1
            touched_ids.append(sid)
            remaining = limit - len(entity_ids)

            if cursor_v == 2:
                page_ids, next_cur = _scan_ids_for_shard_paged(
                    sid,
                    start_page=page,
                    start_offset=offset,
                    remaining=remaining,
                )
                if page_ids:
                    entity_ids.extend(page_ids)
                    if next_cur is not None:
                        return ScanPage(
                            entity_ids=entity_ids,
                            next_cursor=next_cur,
                            shards_touched=shards_touched,
                            shards_touched_ids=touched_ids,
                        )

                # Exhausted this shard's pages or paging not available; move to next shard.
                shard_pos += 1
                offset = 0
                page = 0
                cursor_v = 2
                if len(entity_ids) >= limit:
                    break
                continue

            # v1 index path (single list per type)
            ids = _scan_ids_for_shard_v1(sid)
            if ids is None:
                # If no v1 index, try paged v2 index.
                page_ids, next_cur = _scan_ids_for_shard_paged(
                    sid,
                    start_page=0,
                    start_offset=0,
                    remaining=remaining,
                )
                if page_ids:
                    entity_ids.extend(page_ids)
                    if next_cur is not None and len(entity_ids) >= limit:
                        return ScanPage(
                            entity_ids=entity_ids,
                            next_cursor=next_cur,
                            shards_touched=shards_touched,
                            shards_touched_ids=touched_ids,
                        )
                    # Not full yet: proceed to next shard.
                    shard_pos += 1
                    offset = 0
                    page = 0
                    cursor_v = 2
                    continue

                # Final fallback: load shard KG.
                kg = self._get_kg(sid)
                ids = [ent.id for ent in kg.get_entities_by_type(entity_type)]

            if offset < 0:
                offset = 0
            if offset >= len(ids):
                shard_pos += 1
                offset = 0
                continue

            take = min(remaining, len(ids) - offset)
            entity_ids.extend(ids[offset : offset + take])
            offset += take

            if len(entity_ids) >= limit:
                more_in_shard = offset < len(ids)
                if more_in_shard:
                    next_cursor = json.dumps({"v": 1, "shard_id": sid, "offset": offset})
                    return ScanPage(
                        entity_ids=entity_ids,
                        next_cursor=next_cursor,
                        shards_touched=shards_touched,
                        shards_touched_ids=touched_ids,
                    )

                shard_pos += 1
                offset = 0
                if shard_pos < len(candidate_ids):
                    next_cursor = json.dumps({"v": 1, "shard_id": candidate_ids[shard_pos], "offset": 0})
                    return ScanPage(
                        entity_ids=entity_ids,
                        next_cursor=next_cursor,
                        shards_touched=shards_touched,
                        shards_touched_ids=touched_ids,
                    )
                return ScanPage(entity_ids=entity_ids, next_cursor=None, shards_touched=shards_touched, shards_touched_ids=touched_ids)

            shard_pos += 1
            offset = 0

        return ScanPage(entity_ids=entity_ids, next_cursor=None, shards_touched=shards_touched, shards_touched_ids=touched_ids)

    def neighbors(
        self,
        entity_id: str,
        *,
        relationship_types: Sequence[str] | None = None,
        direction: str = "both",
        limit: int = 1000,
        cursor: str | None = None,
    ) -> NeighborPage:
        limit = max(0, int(limit))

        offset = 0
        if cursor:
            try:
                c = json.loads(cursor)
                if not isinstance(c, dict) or int(c.get("v", 1)) != 1:
                    raise ValueError("Invalid cursor")
                if c.get("entity_id") != entity_id:
                    raise ValueError("Cursor entity_id mismatch")
                if c.get("direction") != direction:
                    raise ValueError("Cursor direction mismatch")
                expected_types = list(relationship_types) if relationship_types is not None else None
                if c.get("relationship_types") != expected_types:
                    raise ValueError("Cursor relationship_types mismatch")
                offset = int(c.get("offset", 0))
            except Exception as e:
                raise ValueError("Invalid cursor") from e

        shard_id = self._route_entity(entity_id)

        rels: list[Any] = []
        used_index = False

        neighbors_idx = self._get_shard_neighbors_index(shard_id)
        if neighbors_idx is not None:
            adj_cid = neighbors_idx.get(entity_id)
        else:
            # Try v2 bucketed index.
            v2 = self._get_shard_neighbors_index_v2(shard_id)
            adj_cid = None
            if v2 is not None:
                prefix_len, buckets = v2
                bkey = self._neighbors_bucket_key(entity_id, prefix_len=prefix_len)
                bucket_cid = buckets.get(bkey)
                if bucket_cid:
                    bucket_map = self._get_neighbors_bucket(bucket_cid)
                    if bucket_map is not None:
                        adj_cid = bucket_map.get(entity_id)

        if adj_cid:
            try:
                adj_obj = self._fetch_json(adj_cid)
                if isinstance(adj_obj, dict):
                    if direction == "outgoing":
                        rels = list(adj_obj.get("outgoing") or [])
                    elif direction == "incoming":
                        rels = list(adj_obj.get("incoming") or [])
                    else:
                        rels = list(adj_obj.get("outgoing") or []) + list(adj_obj.get("incoming") or [])
                    used_index = True
            except Exception:
                used_index = False

        if not used_index:
            kg = self._get_kg(shard_id)
            rels = kg.get_entity_relationships(
                entity_id,
                direction=direction,
                relationship_types=list(relationship_types) if relationship_types is not None else None,
            )

        # Apply relationship type filter for index-backed rels.
        if used_index and relationship_types is not None:
            rels = [r for r in rels if isinstance(r, dict) and r.get("relationship_type") in set(relationship_types)]

        edges: list[NeighborEdge] = []
        if offset < 0:
            offset = 0
        if offset >= len(rels):
            # Count the shard that served adjacency for this entity.
            return NeighborPage(edges=[], next_cursor=None, shards_touched=1, shards_touched_ids=[shard_id])

        slice_rels = rels[offset : offset + limit]
        for rel in slice_rels:
            if used_index:
                if not isinstance(rel, dict):
                    continue
                edges.append(
                    NeighborEdge(
                        relationship_type=str(rel.get("relationship_type") or ""),
                        source_id=str(rel.get("source_id") or ""),
                        target_id=str(rel.get("target_id") or ""),
                        relationship_id=rel.get("relationship_id"),
                    )
                )
            else:
                edges.append(
                    NeighborEdge(
                        relationship_type=rel.type,
                        source_id=rel.source_id,
                        target_id=rel.target_id,
                        relationship_id=rel.id,
                    )
                )

        next_offset = offset + len(slice_rels)
        next_cursor = None
        if next_offset < len(rels) and len(slice_rels) > 0:
            next_cursor = json.dumps(
                {
                    "v": 1,
                    "entity_id": entity_id,
                    "direction": direction,
                    "relationship_types": list(relationship_types) if relationship_types is not None else None,
                    "offset": next_offset,
                }
            )

        # Shards touched: the shard that served adjacency plus any distinct
        # routed shards needed to resolve the other endpoint IDs.
        touched: set[str] = {shard_id}
        for e in edges:
            other = e.target_id if e.source_id == entity_id else e.source_id
            if other:
                touched.add(self._route_entity(other))

        return NeighborPage(
            edges=edges,
            next_cursor=next_cursor,
            shards_touched=len(touched),
            shards_touched_ids=sorted(touched),
        )
