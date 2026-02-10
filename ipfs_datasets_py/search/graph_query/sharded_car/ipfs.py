from __future__ import annotations

import json
from typing import Optional

from .... import ipfs_backend_router as ipfs_router

from .manifest import GraphShardManifest


def load_manifest_from_ipfs(
    manifest_cid: str,
    *,
    backend: Optional[str] = None,
    backend_instance: Optional[ipfs_router.IPFSBackend] = None,
) -> GraphShardManifest:
    """Load a GraphShardManifest stored as JSON bytes on IPFS.

    v1 assumption: the manifest CID resolves to UTF-8 JSON.
    (Later we can support dag-cbor/dag-json.)
    """

    data = ipfs_router.cat(manifest_cid, backend=backend, backend_instance=backend_instance)
    obj = json.loads(data.decode("utf-8"))
    return GraphShardManifest.from_dict(obj)


def sharded_car_backend_from_manifest_cid(
    manifest_cid: str,
    *,
    backend: Optional[str] = None,
    backend_instance: Optional[ipfs_router.IPFSBackend] = None,
    cache_size: int = 8,
    car_fetch_mode: str = "auto",
):
    """Create a ShardedCARBackend by loading a manifest from IPFS.

    v1 assumptions:
    - The manifest CID resolves to UTF-8 JSON.
    - Each shard entry's `car_cid` points to CAR bytes retrievable from IPFS.

    `car_fetch_mode` controls how shard CAR bytes are fetched:
    - "cat": `ipfs cat <cid>`
    - "block_get": `ipfs block get <cid>`
    - "dag_export": `ipfs dag export <cid>`
    - "auto": try cat, then block_get, then dag_export
    """

    from ..backends.sharded_car import CARBytesShardLoader, IPFSBytesFetcher, IPFSCarFetcher, ShardedCARBackend

    manifest = load_manifest_from_ipfs(manifest_cid, backend=backend, backend_instance=backend_instance)
    fetcher = IPFSCarFetcher(
        backend=backend,
        backend_instance=backend_instance,
        mode=car_fetch_mode,
    )
    index_fetcher = IPFSBytesFetcher(
        backend=backend,
        backend_instance=backend_instance,
        mode="auto",
    )
    loader = CARBytesShardLoader(fetcher=fetcher)
    return ShardedCARBackend(manifest, loader=loader, index_fetcher=index_fetcher, cache_size=cache_size)
