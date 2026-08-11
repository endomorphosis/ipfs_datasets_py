"""Unit tests for DuckDB graph catalog (DQK-015)."""

from __future__ import annotations

from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from ipfs_datasets_py.knowledge_graphs.catalog.duckdb_store import DuckDBGraphCatalog
from ipfs_datasets_py.knowledge_graphs.catalog.errors import CatalogError
from ipfs_datasets_py.knowledge_graphs.catalog.store import GraphCatalog


@pytest.fixture
def duck(tmp_path: Path) -> DuckDBGraphCatalog:
    cat = DuckDBGraphCatalog(tmp_path / "catalog.duckdb")
    yield cat
    cat.close()


@pytest.fixture
def sqlite(tmp_path: Path) -> GraphCatalog:
    cat = GraphCatalog(tmp_path / "catalog.sqlite")
    yield cat
    cat.close()


def _trace(catalog) -> list[tuple]:
    """Run a fixed control-plane trace; return comparable tuples."""

    g = catalog.create_graph(
        "t1",
        "g1",
        storage_profile="parquet",
        idempotency_key="create:g1",
    )
    # Idempotent create returns same graph.
    g2 = catalog.create_graph(
        "t1",
        "g1",
        storage_profile="parquet",
        idempotency_key="create:g1",
    )
    assert g.graph_id == g2.graph_id
    bootstrap = catalog.get_branch("t1", "g1", "main").head_revision
    r2 = catalog.put_revision(
        "t1",
        "g1",
        "rev-2",
        parent_revision=bootstrap,
        storage_profile="parquet",
        checksum="sha256:" + ("ab" * 32),
    )
    lease = catalog.acquire_lease(
        "t1", "g1", "main", holder="writer-a", ttl_seconds=60
    )
    head = catalog.cas_set_head(
        "t1",
        "g1",
        "main",
        expected_revision=bootstrap,
        new_revision=r2.revision_id,
        lease_id=lease.lease_id,
        lease_epoch=lease.epoch,
        idempotency_key="cas:1",
    )
    # CAS conflict
    with pytest.raises(CatalogError) as exc:
        catalog.cas_set_head(
            "t1",
            "g1",
            "main",
            expected_revision=bootstrap,
            new_revision=r2.revision_id,
            lease_id=lease.lease_id,
            lease_epoch=lease.epoch,
        )
    assert exc.value.code == "CONFLICT"
    pin = catalog.set_pin_root(
        "t1", "g1", r2.revision_id, root_cid="bafytestpinroot01"
    )
    return [
        ("graph", g.tenant, g.graph_id, g.status, g.default_branch),
        ("head", head.branch, head.head_revision),
        ("lease", lease.holder, lease.epoch),
        ("pin", pin.root_cid, pin.revision_id),
    ]


def test_sqlite_and_duckdb_traces_equivalent(duck, sqlite) -> None:
    assert _trace(duck) == _trace(sqlite)


def test_cas_conflict_no_partial_mutation(duck: DuckDBGraphCatalog) -> None:
    duck.create_graph("t", "g", storage_profile="parquet")
    boot = duck.get_branch("t", "g", "main").head_revision
    duck.put_revision(
        "t", "g", "rev-x", parent_revision=boot, storage_profile="parquet"
    )
    duck.put_revision(
        "t", "g", "rev-y", parent_revision=boot, storage_profile="parquet"
    )
    lease = duck.acquire_lease("t", "g", "main", holder="w", ttl_seconds=30)
    duck.cas_set_head(
        "t",
        "g",
        "main",
        expected_revision=boot,
        new_revision="rev-x",
        lease_id=lease.lease_id,
        lease_epoch=lease.epoch,
    )
    with pytest.raises(CatalogError) as exc:
        duck.cas_set_head(
            "t",
            "g",
            "main",
            expected_revision=boot,
            new_revision="rev-y",
            lease_id=lease.lease_id,
            lease_epoch=lease.epoch,
        )
    assert exc.value.code == "CONFLICT"
    assert duck.get_branch("t", "g", "main").head_revision == "rev-x"


def test_pins_leases_idempotency_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "persist.duckdb"
    with DuckDBGraphCatalog(path) as cat:
        cat.create_graph(
            "t", "g", storage_profile="parquet", idempotency_key="idem-create"
        )
        boot = cat.get_branch("t", "g", "main").head_revision
        cat.put_revision(
            "t", "g", "rev-2", parent_revision=boot, storage_profile="parquet"
        )
        lease = cat.acquire_lease(
            "t", "g", "main", holder="persist-holder", ttl_seconds=120
        )
        cat.cas_set_head(
            "t",
            "g",
            "main",
            expected_revision=boot,
            new_revision="rev-2",
            lease_id=lease.lease_id,
            lease_epoch=lease.epoch,
            idempotency_key="idem-cas",
        )
        cat.set_pin_root("t", "g", "rev-2", root_cid="bafypinrestart")
        pins_before = cat.list_pin_roots("t", "g")
        idem_before = cat.get_idempotency("idem-create")

    with DuckDBGraphCatalog(path) as cat2:
        assert cat2.get_branch("t", "g", "main").head_revision == "rev-2"
        pins_after = cat2.list_pin_roots("t", "g")
        assert len(pins_after) == len(pins_before) == 1
        assert pins_after[0].root_cid == "bafypinrestart"
        idem_after = cat2.get_idempotency("idem-create")
        assert idem_after is not None and idem_before is not None
        assert idem_after.request_hash == idem_before.request_hash
        # Lease row still present until release.
        renewed = cat2.renew_lease(lease.lease_id, ttl_seconds=60)
        assert renewed.holder == "persist-holder"
        assert renewed.epoch == lease.epoch
