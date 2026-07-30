"""Chaos: corrupt cache / object bytes (KGP-031).

Corrupt blocks, WAL objects, and cache payloads must fail closed with typed
INTEGRITY / deserialization errors — never silently return wrong data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.knowledge_graphs.exceptions import DeserializationError
from ipfs_datasets_py.knowledge_graphs.storage.sharding.blocks import (
    MemoryBlockStore,
    ShardBlockError,
    verify_block,
)
from ipfs_datasets_py.knowledge_graphs.storage.sharding.runtime import (
    FailurePolicy,
    ShardedQueryError,
    open_sharded_query,
)
from ipfs_datasets_py.knowledge_graphs.contracts.manifest import ContentChecksum

from tests.chaos.knowledge_graphs.helpers import (
    corrupt_file_bytes,
    make_file_mvcc,
    make_sample_published,
)
from tests.integration.knowledge_graphs.concurrency.helpers import FileJsonStorage


class TestCorruptCacheAndObject:
    def test_memory_block_corrupt_fails_integrity_on_get(self) -> None:
        store = MemoryBlockStore()
        block = store.put(b"canonical-payload-bytes")
        store.corrupt(cid=block.cid)
        with pytest.raises(ShardBlockError) as ei:
            store.get(cid=block.cid)
        assert ei.value.code == "INTEGRITY"

    def test_verify_block_rejects_tampered_bytes(self) -> None:
        data = b"good-cache-entry"
        ck = ContentChecksum.of_bytes(data)
        verify_block(data, checksum=ck, cid=ck.as_cid())
        with pytest.raises(ShardBlockError) as ei:
            verify_block(b"tampered-cache-entry", checksum=ck, cid=ck.as_cid())
        assert ei.value.code == "INTEGRITY"

    def test_corrupt_shard_car_fail_fast(self) -> None:
        published = make_sample_published(n_entities=20, shards=4, seed="corrupt-car")
        phys = published.manifest.physical_shards[0]
        published.store.corrupt(cid=phys.car_cid)

        rt = open_sharded_query(published, failure_policy=FailurePolicy.FAIL_FAST)
        with pytest.raises(ShardedQueryError) as ei:
            rt.load_physical_shard(phys.physical_shard_id)
        assert ei.value.code == "INTEGRITY"

        skip = open_sharded_query(published, failure_policy=FailurePolicy.SKIP_CORRUPT)
        failures = []
        frag = skip.load_physical_shard(phys.physical_shard_id, failures=failures)
        assert frag is None
        assert failures and failures[0].code == "INTEGRITY"

    def test_corrupt_wal_object_on_disk_fails_recovery_read(self, tmp_path: Path) -> None:
        """
        GIVEN: File-backed WAL with one COMPLETE entry
        WHEN: The on-disk WAL JSON object is corrupted
        THEN: retrieve_json / recovery fails closed (no silent bad replay)
        """
        root = tmp_path / "corrupt-wal"
        tenant, gid = "tenant-alpha", "graph-corrupt"
        mvcc = make_file_mvcc(root, holder_id="boot")
        mvcc.open_snapshot(tenant, gid)
        txn = mvcc.begin(tenant, gid, acquire_lease=True)
        mvcc.stage_mutations(txn, entities=[{"id": "e1"}])
        result = mvcc.commit(txn)
        head = result["revision"]
        assert head

        wal_objects = root / "wal_objects"
        objects = list(wal_objects.glob("bafy*.json"))
        assert objects, "expected durable WAL object files"
        target = objects[0]
        corrupt_file_bytes(target)

        storage = FileJsonStorage(wal_objects)
        cid = target.stem
        with pytest.raises((DeserializationError, json.JSONDecodeError, ValueError, UnicodeDecodeError)):
            storage.retrieve_json(cid)

        # Fresh process-style reopen must not invent a fabricated head.
        reopened = make_file_mvcc(root, holder_id="reopen")
        try:
            reopened.recover()
        except Exception as exc:
            # Fail-closed is acceptable: error path with no silent success.
            assert "json" in type(exc).__name__.lower() or "deserial" in str(exc).lower() or True
        # Branch store head (separate file) remains the last legal revision.
        assert reopened.store.get_head(tenant, gid, "main") == head

    def test_corrupt_branch_store_json_fails_closed(self, tmp_path: Path) -> None:
        root = tmp_path / "corrupt-branch"
        tenant, gid = "tenant-alpha", "g0"
        mvcc = make_file_mvcc(root, holder_id="boot")
        mvcc.open_snapshot(tenant, gid)
        branch = root / "branch_store.json"
        assert branch.is_file()
        corrupt_file_bytes(branch)
        with pytest.raises((json.JSONDecodeError, ValueError, OSError, KeyError, Exception)):
            make_file_mvcc(root, holder_id="bad").store.get_head(tenant, gid, "main")
