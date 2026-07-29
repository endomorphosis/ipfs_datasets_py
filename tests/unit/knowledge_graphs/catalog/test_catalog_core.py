"""Unit tests for durable graph catalog control-plane behavior (KGP-005).

Covers lifecycle, uniqueness, immutable revisions, branch-head CAS, tombstones,
leases, idempotency, pin roots, restart reopen, and typed conflicts without
process-cache authority.
"""

from __future__ import annotations

import concurrent.futures
import threading
from pathlib import Path
from typing import List

import pytest

from ipfs_datasets_py.knowledge_graphs.catalog import (
    CatalogError,
    GraphCatalog,
    bootstrap_revision_id,
    open_catalog,
)


@pytest.fixture
def catalog_path(tmp_path: Path) -> Path:
    return tmp_path / "catalog.sqlite"


@pytest.fixture
def catalog(catalog_path: Path) -> GraphCatalog:
    cat = open_catalog(catalog_path)
    yield cat
    cat.close()


def test_create_graph_registers_bootstrap_revision_and_default_branch(
    catalog: GraphCatalog,
) -> None:
    g = catalog.create_graph(
        "acme",
        "skills",
        storage_profile="hybrid",
        graph_kind="skills",
        pin_root="bafybootstrap0000000000000000000000000000000000000000000001",
    )
    assert g.tenant == "acme"
    assert g.graph_id == "skills"
    assert g.storage_profile == "hybrid"
    assert g.status == "active"
    assert g.uri == "kg://acme/skills"

    boot = bootstrap_revision_id("acme", "skills")
    branch = catalog.get_branch("acme", "skills", "main")
    assert branch.head_revision == boot
    rev = catalog.get_revision("acme", "skills", boot)
    assert rev.parent_revision is None
    assert rev.metadata.get("bootstrap") is True
    pins = catalog.list_pin_roots("acme", "skills", revision_id=boot)
    assert len(pins) == 1
    assert pins[0].root_cid.startswith("bafy")


def test_create_graph_uniqueness_conflict(catalog: GraphCatalog) -> None:
    catalog.create_graph("t1", "g1")
    with pytest.raises(CatalogError) as excinfo:
        catalog.create_graph("t1", "g1")
    assert excinfo.value.code == "ALREADY_EXISTS"
    assert excinfo.value.retryable is False


def test_create_graph_idempotent_replay(catalog: GraphCatalog) -> None:
    first = catalog.create_graph(
        "t1",
        "g1",
        idempotency_key="create-1",
        storage_profile="parquet",
    )
    second = catalog.create_graph(
        "t1",
        "g1",
        idempotency_key="create-1",
        storage_profile="parquet",
    )
    assert first.to_dict() == second.to_dict()
    # Different body with same key is a typed conflict.
    with pytest.raises(CatalogError) as excinfo:
        catalog.create_graph(
            "t1",
            "g1",
            idempotency_key="create-1",
            storage_profile="hybrid",
        )
    assert excinfo.value.code == "CONFLICT"


def test_tenant_isolation_and_list(catalog: GraphCatalog) -> None:
    catalog.create_graph("alpha", "g1")
    catalog.create_graph("alpha", "g2")
    catalog.create_graph("beta", "g1")
    alpha = catalog.list_graphs("alpha")
    beta = catalog.list_graphs("beta")
    assert {g.graph_id for g in alpha} == {"g1", "g2"}
    assert {g.graph_id for g in beta} == {"g1"}
    assert all(g.tenant == "alpha" for g in alpha)


def test_describe_includes_heads_and_branches(catalog: GraphCatalog) -> None:
    catalog.create_graph("acme", "skills", graph_kind="skills")
    desc = catalog.describe_graph("acme", "skills")
    assert desc.uri == "kg://acme/skills"
    assert desc.head_revision == bootstrap_revision_id("acme", "skills")
    assert len(desc.branches) == 1
    assert desc.branches[0]["branch"] == "main"


def test_invalid_slugs_raise_invalid_target(catalog: GraphCatalog) -> None:
    with pytest.raises(CatalogError) as excinfo:
        catalog.create_graph("ACME", "g1")
    assert excinfo.value.code == "INVALID_TARGET"
    with pytest.raises(CatalogError):
        catalog.create_graph("acme", "bad/id")
    with pytest.raises(CatalogError):
        catalog.create_graph("acme", "g1", storage_profile="s3")


def test_put_revision_is_immutable(catalog: GraphCatalog) -> None:
    catalog.create_graph("t", "g")
    catalog.put_revision(
        "t",
        "g",
        "rev-a",
        parent_revision=bootstrap_revision_id("t", "g"),
        checksum="a" * 64,
    )
    # Exact replay ok.
    again = catalog.put_revision(
        "t",
        "g",
        "rev-a",
        parent_revision=bootstrap_revision_id("t", "g"),
        checksum="a" * 64,
    )
    assert again.revision_id == "rev-a"
    with pytest.raises(CatalogError) as excinfo:
        catalog.put_revision(
            "t",
            "g",
            "rev-a",
            parent_revision=bootstrap_revision_id("t", "g"),
            checksum="b" * 64,
        )
    assert excinfo.value.code == "CONFLICT"


def test_cas_set_head_atomic_success_and_conflict(catalog: GraphCatalog) -> None:
    catalog.create_graph("t", "g")
    boot = bootstrap_revision_id("t", "g")
    catalog.put_revision("t", "g", "rev-1", parent_revision=boot)
    catalog.put_revision("t", "g", "rev-2", parent_revision="rev-1")

    moved = catalog.cas_set_head(
        "t",
        "g",
        "main",
        expected_revision=boot,
        new_revision="rev-1",
    )
    assert moved.head_revision == "rev-1"

    with pytest.raises(CatalogError) as excinfo:
        catalog.cas_set_head(
            "t",
            "g",
            "main",
            expected_revision=boot,
            new_revision="rev-2",
        )
    err = excinfo.value
    assert err.code == "CONFLICT"
    assert err.retryable is True
    assert err.details["current_revision"] == "rev-1"
    assert err.details["expected_revision"] == boot

    moved2 = catalog.cas_set_head(
        "t",
        "g",
        "main",
        expected_revision="rev-1",
        new_revision="rev-2",
    )
    assert moved2.head_revision == "rev-2"
    assert catalog.get_branch("t", "g", "main").head_revision == "rev-2"


def test_cas_requires_registered_revision(catalog: GraphCatalog) -> None:
    catalog.create_graph("t", "g")
    boot = bootstrap_revision_id("t", "g")
    with pytest.raises(CatalogError) as excinfo:
        catalog.cas_set_head(
            "t",
            "g",
            "main",
            expected_revision=boot,
            new_revision="missing-rev",
        )
    assert excinfo.value.code == "NOT_FOUND"


def test_cas_idempotent_replay(catalog: GraphCatalog) -> None:
    catalog.create_graph("t", "g")
    boot = bootstrap_revision_id("t", "g")
    catalog.put_revision("t", "g", "rev-1", parent_revision=boot)
    a = catalog.cas_set_head(
        "t",
        "g",
        "main",
        expected_revision=boot,
        new_revision="rev-1",
        idempotency_key="cas-1",
    )
    b = catalog.cas_set_head(
        "t",
        "g",
        "main",
        expected_revision=boot,
        new_revision="rev-1",
        idempotency_key="cas-1",
    )
    assert a.to_dict() == b.to_dict()
    assert catalog.get_branch("t", "g", "main").head_revision == "rev-1"


def test_create_branch_from_revision_and_delete_branch(
    catalog: GraphCatalog,
) -> None:
    catalog.create_graph("t", "g")
    boot = bootstrap_revision_id("t", "g")
    catalog.put_revision("t", "g", "rev-1", parent_revision=boot)
    catalog.cas_set_head(
        "t", "g", "main", expected_revision=boot, new_revision="rev-1"
    )
    feature = catalog.create_branch(
        "t", "g", "feature", from_revision="rev-1"
    )
    assert feature.head_revision == "rev-1"
    tomb = catalog.delete_branch("t", "g", "feature", reason="done")
    assert tomb.entity_type == "branch"
    assert tomb.branch == "feature"
    with pytest.raises(CatalogError) as excinfo:
        catalog.get_branch("t", "g", "feature")
    assert excinfo.value.code == "NOT_FOUND"
    # Default branch cannot be deleted.
    with pytest.raises(CatalogError) as excinfo:
        catalog.delete_branch("t", "g", "main")
    assert excinfo.value.code == "INVALID_REQUEST"


def test_delete_graph_tombstone_and_list_exclusion(catalog: GraphCatalog) -> None:
    catalog.create_graph("t", "g1")
    catalog.create_graph("t", "g2")
    tomb = catalog.delete_graph("t", "g1", reason="retired")
    assert tomb.entity_type == "graph"
    assert tomb.tombstoned_at
    listed = catalog.list_graphs("t")
    assert {g.graph_id for g in listed} == {"g2"}
    with pytest.raises(CatalogError) as excinfo:
        catalog.get_graph("t", "g1")
    assert excinfo.value.code == "NOT_FOUND"
    soft = catalog.get_graph("t", "g1", allow_tombstoned=True)
    assert soft.status == "tombstoned"
    tombs = catalog.list_tombstones("t", graph_id="g1")
    assert len(tombs) >= 1


def test_leases_fencing_and_cas_gate(catalog: GraphCatalog) -> None:
    catalog.create_graph("t", "g")
    boot = bootstrap_revision_id("t", "g")
    catalog.put_revision("t", "g", "rev-1", parent_revision=boot)

    lease = catalog.acquire_lease(
        "t", "g", "main", holder="writer-a", ttl_seconds=60.0
    )
    assert lease.epoch == 1

    with pytest.raises(CatalogError) as excinfo:
        catalog.acquire_lease(
            "t", "g", "main", holder="writer-b", ttl_seconds=60.0
        )
    assert excinfo.value.code == "CONFLICT"

    # Stale epoch is fenced.
    with pytest.raises(CatalogError) as excinfo:
        catalog.cas_set_head(
            "t",
            "g",
            "main",
            expected_revision=boot,
            new_revision="rev-1",
            lease_id=lease.lease_id,
            lease_epoch=0,
        )
    assert excinfo.value.code == "FENCED"
    assert excinfo.value.retryable is False

    moved = catalog.cas_set_head(
        "t",
        "g",
        "main",
        expected_revision=boot,
        new_revision="rev-1",
        lease_id=lease.lease_id,
        lease_epoch=lease.epoch,
    )
    assert moved.head_revision == "rev-1"

    catalog.release_lease(
        "t",
        "g",
        "main",
        lease_id=lease.lease_id,
        lease_epoch=lease.epoch,
    )
    assert catalog.get_lease("t", "g", "main") is None


def test_expired_lease_can_be_stolen_with_new_epoch(
    catalog: GraphCatalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ipfs_datasets_py.knowledge_graphs.catalog import identity as idmod

    catalog.create_graph("t", "g")
    # Force very short TTL then advance "now" via is_expired monkeypatch.
    lease = catalog.acquire_lease(
        "t", "g", "main", holder="a", ttl_seconds=0.001
    )
    # Mark as expired by patching is_expired to always True for steal path.
    monkeypatch.setattr(idmod, "is_expired", lambda *a, **k: True)
    # Re-import path used inside store — store imports is_expired at module load.
    import ipfs_datasets_py.knowledge_graphs.catalog.store as store_mod

    monkeypatch.setattr(store_mod, "is_expired", lambda *a, **k: True)

    stolen = catalog.acquire_lease(
        "t", "g", "main", holder="b", ttl_seconds=30.0
    )
    assert stolen.holder == "b"
    assert stolen.epoch == lease.epoch + 1
    assert stolen.lease_id != lease.lease_id


def test_pin_roots_persist(catalog: GraphCatalog) -> None:
    catalog.create_graph("t", "g")
    boot = bootstrap_revision_id("t", "g")
    catalog.put_revision("t", "g", "rev-1", parent_revision=boot)
    pin = catalog.set_pin_root(
        "t",
        "g",
        "rev-1",
        "bafyroot000000000000000000000000000000000000000000000000001",
        pin_kind="manifest",
    )
    pins = catalog.list_pin_roots("t", "g")
    assert any(p.pin_id == pin.pin_id for p in pins)
    # Idempotent same pin.
    again = catalog.set_pin_root(
        "t",
        "g",
        "rev-1",
        "bafyroot000000000000000000000000000000000000000000000000001",
        pin_kind="manifest",
    )
    assert again.pin_id == pin.pin_id


def test_restart_reopens_committed_state_without_process_cache(
    catalog_path: Path,
) -> None:
    """New process/instance is the source of truth — no ambient memory."""
    with open_catalog(catalog_path) as cat1:
        cat1.create_graph("acme", "skills", storage_profile="ipfs_ipld")
        boot = bootstrap_revision_id("acme", "skills")
        cat1.put_revision(
            "acme",
            "skills",
            "rev-1",
            parent_revision=boot,
            pin_root="bafy1",
        )
        cat1.cas_set_head(
            "acme",
            "skills",
            "main",
            expected_revision=boot,
            new_revision="rev-1",
            pin_root="bafy1",
        )
        cat1.acquire_lease(
            "acme", "skills", "main", holder="w1", ttl_seconds=120.0
        )
        cat1.create_graph(
            "acme", "other", idempotency_key="idemp-restart"
        )

    # Fresh instance — nothing held from cat1.
    with open_catalog(catalog_path) as cat2:
        desc = cat2.describe_graph("acme", "skills")
        assert desc.head_revision == "rev-1"
        assert desc.storage_profile == "ipfs_ipld"
        branch = cat2.get_branch("acme", "skills", "main")
        assert branch.head_revision == "rev-1"
        rev = cat2.get_revision("acme", "skills", "rev-1")
        assert rev.pin_root == "bafy1" or any(
            p.root_cid == "bafy1"
            for p in cat2.list_pin_roots("acme", "skills", revision_id="rev-1")
        )
        lease = cat2.get_lease("acme", "skills", "main")
        assert lease is not None
        assert lease.holder == "w1"
        # Idempotency survives restart.
        g = cat2.create_graph(
            "acme", "other", idempotency_key="idemp-restart"
        )
        assert g.graph_id == "other"
        graphs = cat2.list_graphs("acme")
        assert {x.graph_id for x in graphs} == {"skills", "other"}


def test_concurrent_create_unique_winner(catalog_path: Path) -> None:
    """Only one concurrent create for the same identity succeeds."""
    barrier = threading.Barrier(8)
    results: List[object] = []
    lock = threading.Lock()

    def worker() -> None:
        cat = open_catalog(catalog_path)
        try:
            barrier.wait(timeout=10)
            try:
                g = cat.create_graph("race", "g1")
                with lock:
                    results.append(("ok", g.graph_id))
            except CatalogError as exc:
                with lock:
                    results.append(("err", exc.code))
        finally:
            cat.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive()

    oks = [r for r in results if r[0] == "ok"]
    errs = [r for r in results if r[0] == "err"]
    assert len(oks) == 1
    assert len(errs) == 7
    assert all(code == "ALREADY_EXISTS" for _, code in errs)

    with open_catalog(catalog_path) as cat:
        assert len(cat.list_graphs("race")) == 1


def test_concurrent_cas_single_winner(catalog_path: Path) -> None:
    with open_catalog(catalog_path) as setup:
        setup.create_graph("race", "g")
        boot = bootstrap_revision_id("race", "g")
        for i in range(8):
            setup.put_revision(
                "race",
                "g",
                f"rev-{i}",
                parent_revision=boot,
            )

    barrier = threading.Barrier(8)
    outcomes: List[str] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        cat = open_catalog(catalog_path)
        try:
            barrier.wait(timeout=10)
            try:
                cat.cas_set_head(
                    "race",
                    "g",
                    "main",
                    expected_revision=boot,
                    new_revision=f"rev-{i}",
                )
                with lock:
                    outcomes.append(f"ok:{i}")
            except CatalogError as exc:
                with lock:
                    outcomes.append(f"err:{exc.code}")
        finally:
            cat.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(worker, i) for i in range(8)]
        for f in concurrent.futures.as_completed(futs, timeout=60):
            f.result()

    oks = [o for o in outcomes if o.startswith("ok:")]
    errs = [o for o in outcomes if o.startswith("err:")]
    assert len(oks) == 1
    assert len(errs) == 7
    assert all(o == "err:CONFLICT" for o in errs)

    winner = int(oks[0].split(":")[1])
    with open_catalog(catalog_path) as cat:
        assert cat.get_branch("race", "g", "main").head_revision == f"rev-{winner}"


def test_not_found_for_unknown_graph(catalog: GraphCatalog) -> None:
    with pytest.raises(CatalogError) as excinfo:
        catalog.describe_graph("nope", "missing")
    assert excinfo.value.code == "NOT_FOUND"


def test_error_to_dict_is_json_safe(catalog: GraphCatalog) -> None:
    catalog.create_graph("t", "g")
    try:
        catalog.create_graph("t", "g")
    except CatalogError as exc:
        payload = exc.to_dict()
        assert payload["code"] == "ALREADY_EXISTS"
        assert isinstance(payload["retryable"], bool)
        assert isinstance(payload["details"], dict)
    else:
        pytest.fail("expected ALREADY_EXISTS")
