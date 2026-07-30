"""Chaos: missing and slow shards (KGP-031).

Missing shards surface NOT_FOUND; slow shards surface TIMEOUT (retryable)
under partial policy, and raise under fail-fast.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.knowledge_graphs.storage.sharding.runtime import (
    FailurePolicy,
    ShardedQueryError,
    open_sharded_query,
)

from tests.chaos.knowledge_graphs.helpers import make_sample_published


class TestMissingShard:
    def test_missing_shard_partial_policy(self) -> None:
        published = make_sample_published(n_entities=24, shards=4, seed="missing")
        phys = published.manifest.physical_shards[0]
        published.store.remove(cid=phys.car_cid)

        rt = open_sharded_query(published, failure_policy=FailurePolicy.PARTIAL)
        failures = []
        frag = rt.load_physical_shard(phys.physical_shard_id, failures=failures)
        assert frag is None
        assert failures and failures[0].code == "NOT_FOUND"

    def test_missing_shard_fail_fast(self) -> None:
        published = make_sample_published(n_entities=24, shards=4, seed="missing-ff")
        phys = published.manifest.physical_shards[1]
        published.store.remove(cid=phys.car_cid)

        rt = open_sharded_query(published, failure_policy=FailurePolicy.FAIL_FAST)
        with pytest.raises(ShardedQueryError) as ei:
            rt.load_physical_shard(phys.physical_shard_id)
        assert ei.value.code == "NOT_FOUND"

    def test_other_shards_still_readable_under_partial(self) -> None:
        published = make_sample_published(n_entities=32, shards=4, seed="missing-partial")
        phys = published.manifest.physical_shards[0]
        published.store.remove(cid=phys.car_cid)

        rt = open_sharded_query(published, failure_policy=FailurePolicy.PARTIAL)
        survivors = [
            p
            for p in published.manifest.physical_shards
            if p.physical_shard_id != phys.physical_shard_id
        ]
        assert survivors
        frag = rt.load_physical_shard(survivors[0].physical_shard_id)
        assert frag is not None


class TestSlowShard:
    def test_slow_shard_timeout_partial(self) -> None:
        published = make_sample_published(n_entities=24, shards=4, seed="slow")
        phys = published.manifest.physical_shards[0]
        published.store.set_latency(0.2, cid=phys.car_cid)

        rt = open_sharded_query(
            published,
            failure_policy=FailurePolicy.PARTIAL,
            shard_fetch_timeout_seconds=0.01,
        )
        failures = []
        frag = rt.load_physical_shard(phys.physical_shard_id, failures=failures)
        assert frag is None
        assert failures and failures[0].code == "TIMEOUT"
        assert failures[0].retryable is True

    def test_slow_shard_timeout_fail_fast(self) -> None:
        published = make_sample_published(n_entities=24, shards=4, seed="slow-ff")
        phys = published.manifest.physical_shards[0]
        published.store.set_latency(0.2, cid=phys.car_cid)

        rt = open_sharded_query(
            published,
            failure_policy=FailurePolicy.FAIL_FAST,
            shard_fetch_timeout_seconds=0.01,
        )
        with pytest.raises(ShardedQueryError) as ei:
            rt.load_physical_shard(phys.physical_shard_id)
        assert ei.value.code == "TIMEOUT"

    def test_clearing_latency_recovers_shard(self) -> None:
        published = make_sample_published(n_entities=16, shards=2, seed="slow-recover")
        phys = published.manifest.physical_shards[0]
        published.store.set_latency(0.15, cid=phys.car_cid)
        rt_slow = open_sharded_query(
            published,
            failure_policy=FailurePolicy.PARTIAL,
            shard_fetch_timeout_seconds=0.01,
        )
        failures = []
        assert rt_slow.load_physical_shard(phys.physical_shard_id, failures=failures) is None
        assert failures[0].code == "TIMEOUT"

        published.store.set_latency(0.0, cid=phys.car_cid)
        rt_ok = open_sharded_query(
            published,
            failure_policy=FailurePolicy.FAIL_FAST,
            shard_fetch_timeout_seconds=5.0,
        )
        frag = rt_ok.load_physical_shard(phys.physical_shard_id)
        assert frag is not None
