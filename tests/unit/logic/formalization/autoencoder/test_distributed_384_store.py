"""Real DuckDB ownership/durability tests; synthetic numerical payloads only."""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import RegistryError
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import contracts
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.local_store import (
    LocalTrainingStore, LocalTrainingStoreError, PLAN_SCHEMA, UPDATE_SCHEMA,
)


def campaign(tmp_path, count=3):
    base = tmp_path / "base.json"
    base.write_bytes(b'{"synthetic_checkpoint":true}')
    plan = {"schema": PLAN_SCHEMA, "domain_id": "security_ir",
            "base_checkpoint_sha256": hashlib.sha256(base.read_bytes()).hexdigest(),
            "dataset_sha256": "d" * 64, "recipe_sha256": "e" * 64,
            "description": "UTF-8 corpus: café",
            "shards": [{"shard_id": "s" + str(i), "rows_sha256": contracts.digest([i]),
                        "row_count": i + 1} for i in range(count)]}
    plan["plan_id"] = contracts.digest(plan)
    return plan, base


def update(plan, shard_id, *, changed=False):
    shard = next(s for s in plan["shards"] if s["shard_id"] == shard_id)
    value = {"schema": UPDATE_SCHEMA, **contracts.binding(plan), **shard,
             "statistics": {"synthetic_sum": 99 if changed else shard["row_count"]}}
    value["update_id"] = contracts.digest(value)
    return value


def put(tmp_path, value, name="update.json"):
    path = tmp_path / name
    path.write_bytes(contracts.raw(value))
    return path


def open_store(tmp_path):
    return LocalTrainingStore(tmp_path / "control.duckdb", tmp_path / "cas")


def finish(store, plan, tmp_path, shard_id):
    lease = store.claim(plan, shard_id, "worker-" + shard_id)
    path = put(tmp_path, update(plan, shard_id), shard_id + ".json")
    return lease, path, store.complete(plan, lease, path)


def test_registration_completion_restart_and_missing_work(tmp_path):
    plan, base = campaign(tmp_path)
    with open_store(tmp_path) as store:
        first = store.register_campaign(plan, base)
        assert first == store.register_campaign(copy.deepcopy(plan), base)
        assert store.completed(plan) == {}
        lease, path, receipt = finish(store, plan, tmp_path, "s0")
        assert store.complete(plan, lease, path) == receipt
        assert store.claim(plan, "s0", "other") is None
        assert store.pending(plan) == ["s1", "s2"]
        assert receipt["admitted"] is receipt["promoted"] is False
        # Numerical validation is deliberately outside this storage layer.
        result = store.registry.get_run(lease["run_id"])["result"]
        assert result["numerical_correctness_verified"] is False
        assert result["proof_authority"] is False
    with open_store(tmp_path) as store:
        assert store.register_campaign(plan, base) == first
        assert store.complete(plan, lease, path) == receipt
        paths = store.completed(plan)
        assert list(paths) == ["s0"]
        assert contracts.read_json(paths["s0"]) == update(plan, "s0")
        assert store.pending(plan) == ["s1", "s2"]
        assert store.registry.resolve_head(first["variant_id"], "main") is None


def test_equivalent_update_json_is_canonicalized_for_idempotence(tmp_path):
    plan, base = campaign(tmp_path, 1)
    with open_store(tmp_path) as store:
        store.register_campaign(plan, base)
        lease, path, receipt = finish(store, plan, tmp_path, "s0")
        path.write_text(json.dumps(update(plan, "s0"), indent=2))
        assert store.complete(plan, lease, path) == receipt


def test_partial_registration_can_resume_exact_missing_runs(tmp_path, monkeypatch):
    plan, base = campaign(tmp_path)
    with open_store(tmp_path) as store:
        native_create = store.registry.create_run
        count = 0
        def interrupted(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise RuntimeError("interrupted registration")
            return native_create(*args, **kwargs)
        monkeypatch.setattr(store.registry, "create_run", interrupted)
        with pytest.raises(RuntimeError, match="interrupted"):
            store.register_campaign(plan, base)
        monkeypatch.setattr(store.registry, "create_run", native_create)
        registered = store.register_campaign(plan, base)
        assert len(registered["run_ids"]) == 3
        assert store.pending(plan) == ["s0", "s1", "s2"]


def test_lost_completion_response_recovers_exact_durable_result(tmp_path, monkeypatch):
    plan, base = campaign(tmp_path, 1)
    with open_store(tmp_path) as store:
        store.register_campaign(plan, base)
        lease = store.claim(plan, "s0", "one")
        path = put(tmp_path, update(plan, "s0"))
        native_complete = store.registry.complete_run
        observed = []
        def lose_response(*args, **kwargs):
            observed.append(native_complete(*args, **kwargs))
            raise ConnectionError("lost after commit")
        monkeypatch.setattr(store.registry, "complete_run", lose_response)
        with pytest.raises(ConnectionError, match="lost after commit"):
            store.complete(plan, lease, path)
        assert store.complete(plan, lease, path) == observed[0]
        assert len(observed) == 1


def test_live_duplicate_claim_is_stable_and_other_worker_is_rejected(tmp_path):
    plan, base = campaign(tmp_path)
    with open_store(tmp_path) as store:
        store.register_campaign(plan, base)
        lease = store.claim(plan, "s0", "one")
        assert lease == store.claim(plan, "s0", "one")
        with pytest.raises(RegistryError, match="already leased"):
            store.claim(plan, "s0", "two")


@pytest.mark.parametrize("duration", [True, 0, -1, float("inf"), float("nan"), 86401])
def test_invalid_claim_duration_rejected_even_for_live_duplicate(tmp_path, duration):
    plan, base = campaign(tmp_path, 1)
    with open_store(tmp_path) as store:
        store.register_campaign(plan, base)
        store.claim(plan, "s0", "one")
        with pytest.raises(LocalTrainingStoreError, match="lease_seconds"):
            store.claim(plan, "s0", "one", lease_seconds=duration)


def test_owner_restart_fences_unfinished_lease_and_allows_reclaim(tmp_path):
    plan, base = campaign(tmp_path, 1)
    path = put(tmp_path, update(plan, "s0"))
    with open_store(tmp_path) as store:
        store.register_campaign(plan, base)
        old = store.claim(plan, "s0", "one")
    with open_store(tmp_path) as store:
        with pytest.raises(RegistryError, match="stale"):
            store.complete(plan, old, path)
        with pytest.raises(RegistryError, match="stale"):
            store.renew(plan, old)
        new = store.claim(plan, "s0", "two")
        assert new["owner_generation"] > old["owner_generation"]
        assert new["fence"] > old["fence"]
        assert new["attempt"] > old["attempt"]
        store.complete(plan, new, path)
        with pytest.raises(RegistryError, match="conflicts"):
            store.complete(plan, old, path)


def test_expiry_and_renewal_fence_previous_lease_without_sleep(tmp_path):
    plan, base = campaign(tmp_path, 1)
    with open_store(tmp_path) as store:
        store.registry._clock = lambda: 1000.0
        store.register_campaign(plan, base)
        old = store.claim(plan, "s0", "one", lease_seconds=10)
        store.registry._clock = lambda: 1005.0
        renewed = store.renew(plan, old, lease_seconds=20)
        assert renewed["expires_at"] == 1025.0
        path = put(tmp_path, update(plan, "s0"))
        with pytest.raises(RegistryError, match="stale"):
            store.complete(plan, old, path)
        store.registry._clock = lambda: 1025.0
        with pytest.raises(RegistryError, match="stale"):
            store.complete(plan, renewed, path)
        replacement = store.claim(plan, "s0", "two")
        store.complete(plan, replacement, path)


def test_parallel_claims_and_updates_preserve_all_shards(tmp_path):
    plan, base = campaign(tmp_path, 12)
    with open_store(tmp_path) as store:
        store.register_campaign(plan, base)
        def worker(shard):
            name = shard["shard_id"]
            lease, path, receipt = finish(store, plan, tmp_path, name)
            return name, receipt
        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts = dict(pool.map(worker, plan["shards"]))
        assert set(store.completed(plan)) == set(receipts)
        assert len({r["version_id"] for r in receipts.values()}) == 12
        assert store.pending(plan) == []


def test_parallel_workers_contending_for_one_shard_have_one_winner(tmp_path):
    plan, base = campaign(tmp_path, 1)
    with open_store(tmp_path) as store:
        store.register_campaign(plan, base)
        def claim(i):
            try:
                return store.claim(plan, "s0", "worker-" + str(i))
            except RegistryError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(claim, range(8)))
        assert sum(r is not None for r in results) == 1


def test_second_process_cannot_open_owner_database(tmp_path):
    with open_store(tmp_path):
        code = """
import sys
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.local_store import LocalTrainingStore
from ipfs_datasets_py.duckdb_control.autoencoder_registry import RegistryError
try:
    LocalTrainingStore(sys.argv[1], sys.argv[2])
except RegistryError as exc:
    assert 'already has an owner' in str(exc)
else:
    raise AssertionError('second writer acquired the database')
"""
        env = {**os.environ, "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
               "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0", "PYTHONPATH": str(Path.cwd())}
        result = subprocess.run([sys.executable, "-c", code, str(tmp_path / "control.duckdb"),
                                 str(tmp_path / "cas")], env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("field,value", [
    ("plan_id", "b" * 64), ("base_checkpoint_sha256", "b" * 64),
    ("dataset_sha256", "b" * 64), ("recipe_sha256", "b" * 64),
    ("rows_sha256", "b" * 64), ("row_count", True), ("shard_id", "s1"),
    ("domain_id", "intent_ir"),
])
def test_stale_or_foreign_update_bindings_are_rejected(tmp_path, field, value):
    plan, base = campaign(tmp_path)
    with open_store(tmp_path) as store:
        store.register_campaign(plan, base)
        lease = store.claim(plan, "s0", "one")
        payload = update(plan, "s0")
        payload[field] = value
        payload["update_id"] = contracts.digest({k: v for k, v in payload.items() if k != "update_id"})
        with pytest.raises(LocalTrainingStoreError, match="binding differs"):
            store.complete(plan, lease, put(tmp_path, payload))
        assert store.completed(plan) == {}


def test_altered_statistics_and_duplicate_keys_are_rejected(tmp_path):
    plan, base = campaign(tmp_path, 1)
    with open_store(tmp_path) as store:
        store.register_campaign(plan, base)
        lease = store.claim(plan, "s0", "one")
        payload = update(plan, "s0")
        payload["statistics"]["synthetic_sum"] = 999
        with pytest.raises(LocalTrainingStoreError, match="identity differs"):
            store.complete(plan, lease, put(tmp_path, payload))
        path = tmp_path / "duplicate.json"
        path.write_bytes(contracts.raw(update(plan, "s0"))[:-1] + b',"statistics":{}}')
        with pytest.raises(LocalTrainingStoreError, match="unambiguous"):
            store.complete(plan, lease, path)


def test_conflicting_completed_update_preserves_original(tmp_path):
    plan, base = campaign(tmp_path, 1)
    with open_store(tmp_path) as store:
        store.register_campaign(plan, base)
        lease, _, _ = finish(store, plan, tmp_path, "s0")
        with pytest.raises(LocalTrainingStoreError, match="conflicts"):
            store.complete(plan, lease, put(tmp_path, update(plan, "s0", changed=True)))
        assert contracts.read_json(store.completed(plan)["s0"]) == update(plan, "s0")


def test_missing_or_corrupt_cas_update_is_not_reported_complete(tmp_path):
    plan, base = campaign(tmp_path, 1)
    with open_store(tmp_path) as store:
        store.register_campaign(plan, base)
        finish(store, plan, tmp_path, "s0")
        path = store.completed(plan)["s0"]
        path.write_bytes(b"corruption")
        with pytest.raises(RegistryError, match="digest mismatch"):
            store.completed(plan)
        with pytest.raises(RegistryError, match="digest mismatch"):
            store.claim(plan, "s0", "new")


def test_changed_plan_extensions_and_wrong_base_are_rejected(tmp_path):
    plan, base = campaign(tmp_path, 1)
    with open_store(tmp_path) as store:
        store.register_campaign(plan, base)
        changed = {**plan, "description": "changed"}
        with pytest.raises(LocalTrainingStoreError, match="plan content identity"):
            store.completed(changed)
        base.write_bytes(b"different checkpoint")
        with pytest.raises(LocalTrainingStoreError, match="base checkpoint"):
            store.register_campaign(plan, base)


def test_aggregate_requires_complete_inputs_and_is_immutable_child(tmp_path):
    plan, base = campaign(tmp_path, 2)
    cp = put(tmp_path, {"synthetic_checkpoint": "aggregate"}, "aggregate.json")
    evidence = {"synthetic_owner_observation": "all rows included"}
    with open_store(tmp_path) as store:
        registered = store.register_campaign(plan, base)
        finish(store, plan, tmp_path, "s0")
        with pytest.raises(LocalTrainingStoreError, match="all shard"):
            store.record_checkpoint(plan, cp, evidence)
        finish(store, plan, tmp_path, "s1")
        version = store.record_checkpoint(plan, cp, evidence)
        assert store.record_checkpoint(plan, cp, evidence) == version
        assert version["parent_version_id"] == registered["base_version_id"]
        assert version["metadata"]["shard_count"] == 2
        assert version["metadata"]["numerical_correctness_verified"] is False
        assert version["metadata"]["admitted"] is False
        assert store.registry.resolve_head(registered["variant_id"], "main") is None
        record = contracts.read_json(store.registry.artifact_path(version["metadata"]["aggregation_artifact"]))
        assert [row["shard_id"] for row in record["updates"]] == ["s0", "s1"]
        with pytest.raises(RegistryError, match="operation ID reused"):
            store.record_checkpoint(plan, cp, {"changed_evidence": True})
        cp.write_bytes(b"changed checkpoint")
        with pytest.raises(RegistryError, match="operation ID reused"):
            store.record_checkpoint(plan, cp, evidence)


def test_publication_outbox_resumes_without_claiming_upload_or_promotion(tmp_path):
    plan, base = campaign(tmp_path, 1)
    publication_plan = put(tmp_path, {"synthetic_delivery": "immutable update refs"}, "publication.json")
    with open_store(tmp_path) as store:
        store.register_campaign(plan, base)
        finish(store, plan, tmp_path, "s0")
        version = store.record_checkpoint(plan, base, {"fixture": True})
        event = store.enqueue_publication(plan, version["version_id"], publication_plan)
        assert event["uploaded"] is False
        assert store.enqueue_publication(plan, version["version_id"], publication_plan) == event
        old = store.claim_publication(event["event_id"], "publisher")
        assert store.claim_publication(event["event_id"], "publisher") == old
    with open_store(tmp_path) as store:
        with pytest.raises(RegistryError, match="stale"):
            store.ack_publication(event["event_id"], old["lease"], {"synthetic": True})
        delivery = store.claim_publication(event["event_id"], "publisher")
        receipt = {"synthetic_transport_receipt": "not actual Hub execution"}
        ack = store.ack_publication(event["event_id"], delivery["lease"], receipt)
        assert store.ack_publication(event["event_id"], delivery["lease"], receipt) == ack
        assert store.publication_status(event["event_id"])["status"] == "acknowledged"
        assert store.publication_status(event["event_id"])["receipt"] == receipt
