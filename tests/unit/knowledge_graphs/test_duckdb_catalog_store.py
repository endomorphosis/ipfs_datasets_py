"""Differential and durability tests for DuckDB graph catalog (DQK-015).

Validates that:

* SQLite and DuckDB traces yield equivalent control-plane results
* Branch-head CAS conflicts fail without partial mutation
* Pins, leases, tombstones, and idempotency survive catalog reopen
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pytest

from ipfs_datasets_py.knowledge_graphs.catalog import (
    CatalogError,
    bootstrap_revision_id,
)
from ipfs_datasets_py.knowledge_graphs.catalog.store import (
    GraphCatalog,
    open_catalog as open_sqlite_catalog,
)

duckdb = pytest.importorskip("duckdb")

from ipfs_datasets_py.knowledge_graphs.catalog.duckdb_store import (  # noqa: E402
    DUCKDB_CATALOG_SCHEMA,
    DuckDBGraphCatalog,
    open_duckdb_catalog,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_path(tmp_path: Path) -> Path:
    return tmp_path / "catalog.sqlite"


@pytest.fixture
def duckdb_path(tmp_path: Path) -> Path:
    return tmp_path / "catalog.duckdb"


@pytest.fixture
def sqlite_catalog(sqlite_path: Path) -> GraphCatalog:
    cat = open_sqlite_catalog(sqlite_path)
    yield cat
    cat.close()


@pytest.fixture
def duckdb_catalog(duckdb_path: Path) -> DuckDBGraphCatalog:
    cat = open_duckdb_catalog(duckdb_path)
    yield cat
    cat.close()


CatalogFactory = Callable[[Path], Any]


def _open_sqlite(path: Path) -> GraphCatalog:
    return open_sqlite_catalog(path)


def _open_duckdb(path: Path) -> DuckDBGraphCatalog:
    return open_duckdb_catalog(path)


# ---------------------------------------------------------------------------
# Normalization helpers for differential comparison
# ---------------------------------------------------------------------------


def _strip_volatile(obj: Any) -> Any:
    """Drop timestamps / generated ids that legitimately differ across engines."""
    if isinstance(obj, dict):
        skip = {
            "created_at",
            "updated_at",
            "tombstoned_at",
            "expires_at",
            "renewed_at",
            "pin_id",
            "lease_id",
        }
        return {
            k: _strip_volatile(v)
            for k, v in sorted(obj.items())
            if k not in skip
        }
    if isinstance(obj, list):
        return [_strip_volatile(x) for x in obj]
    if isinstance(obj, tuple):
        return [_strip_volatile(x) for x in obj]
    return obj


def _record_dict(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, list):
        return [_record_dict(v) for v in value]
    return value


def _error_payload(exc: CatalogError) -> Dict[str, Any]:
    return {
        "code": exc.code,
        "retryable": exc.retryable,
        "details": _strip_volatile(dict(exc.details)),
        "message_has_content": bool(exc.message),
    }


# ---------------------------------------------------------------------------
# Shared operation traces
# ---------------------------------------------------------------------------


def _run_lifecycle_trace(catalog: Any) -> Dict[str, Any]:
    """Execute a multi-step control-plane scenario; return normalized snapshot."""
    out: Dict[str, Any] = {"steps": [], "errors": []}

    def step(name: str, fn: Callable[[], Any]) -> Any:
        try:
            result = fn()
            payload = _strip_volatile(_record_dict(result))
            out["steps"].append({"name": name, "ok": True, "result": payload})
            return result
        except CatalogError as exc:
            out["steps"].append(
                {"name": name, "ok": False, "error": _error_payload(exc)}
            )
            out["errors"].append({"name": name, **_error_payload(exc)})
            return None

    g = step(
        "create_graph",
        lambda: catalog.create_graph(
            "acme",
            "skills",
            storage_profile="hybrid",
            graph_kind="skills",
            pin_root="bafybootstrap0000000000000000000000000000000000000000000001",
            metadata={"env": "test"},
        ),
    )
    assert g is not None
    boot = bootstrap_revision_id("acme", "skills")

    step(
        "create_duplicate",
        lambda: catalog.create_graph("acme", "skills"),
    )

    step(
        "create_idempotent_first",
        lambda: catalog.create_graph(
            "acme",
            "other",
            storage_profile="parquet",
            idempotency_key="create-1",
        ),
    )
    step(
        "create_idempotent_replay",
        lambda: catalog.create_graph(
            "acme",
            "other",
            storage_profile="parquet",
            idempotency_key="create-1",
        ),
    )
    step(
        "create_idempotent_conflict",
        lambda: catalog.create_graph(
            "acme",
            "other",
            storage_profile="hybrid",
            idempotency_key="create-1",
        ),
    )

    step("list_graphs", lambda: catalog.list_graphs("acme"))
    step("describe", lambda: catalog.describe_graph("acme", "skills"))
    step("get_branch", lambda: catalog.get_branch("acme", "skills", "main"))
    step("get_revision", lambda: catalog.get_revision("acme", "skills", boot))
    step(
        "list_pins_bootstrap",
        lambda: catalog.list_pin_roots("acme", "skills", revision_id=boot),
    )

    step(
        "put_rev1",
        lambda: catalog.put_revision(
            "acme",
            "skills",
            "rev-1",
            parent_revision=boot,
            checksum="a" * 64,
        ),
    )
    step(
        "put_rev1_replay",
        lambda: catalog.put_revision(
            "acme",
            "skills",
            "rev-1",
            parent_revision=boot,
            checksum="a" * 64,
        ),
    )
    step(
        "put_rev1_conflict",
        lambda: catalog.put_revision(
            "acme",
            "skills",
            "rev-1",
            parent_revision=boot,
            checksum="b" * 64,
        ),
    )
    step(
        "put_rev2",
        lambda: catalog.put_revision(
            "acme", "skills", "rev-2", parent_revision="rev-1"
        ),
    )

    step(
        "cas_success",
        lambda: catalog.cas_set_head(
            "acme",
            "skills",
            "main",
            expected_revision=boot,
            new_revision="rev-1",
            pin_root="bafyhead1",
            idempotency_key="cas-1",
        ),
    )
    step(
        "cas_replay",
        lambda: catalog.cas_set_head(
            "acme",
            "skills",
            "main",
            expected_revision=boot,
            new_revision="rev-1",
            pin_root="bafyhead1",
            idempotency_key="cas-1",
        ),
    )
    step(
        "cas_conflict",
        lambda: catalog.cas_set_head(
            "acme",
            "skills",
            "main",
            expected_revision=boot,
            new_revision="rev-2",
        ),
    )
    step(
        "cas_missing_rev",
        lambda: catalog.cas_set_head(
            "acme",
            "skills",
            "main",
            expected_revision="rev-1",
            new_revision="missing-rev",
        ),
    )
    step(
        "cas_to_rev2",
        lambda: catalog.cas_set_head(
            "acme",
            "skills",
            "main",
            expected_revision="rev-1",
            new_revision="rev-2",
        ),
    )

    step(
        "create_branch",
        lambda: catalog.create_branch(
            "acme", "skills", "feature", from_revision="rev-2"
        ),
    )
    step(
        "delete_branch",
        lambda: catalog.delete_branch("acme", "skills", "feature", reason="done"),
    )
    step(
        "delete_default_branch",
        lambda: catalog.delete_branch("acme", "skills", "main"),
    )

    lease = step(
        "acquire_lease",
        lambda: catalog.acquire_lease(
            "acme", "skills", "main", holder="writer-a", ttl_seconds=120.0
        ),
    )
    step(
        "acquire_lease_conflict",
        lambda: catalog.acquire_lease(
            "acme", "skills", "main", holder="writer-b", ttl_seconds=60.0
        ),
    )
    if lease is not None:
        step(
            "cas_fenced",
            lambda: catalog.cas_set_head(
                "acme",
                "skills",
                "main",
                expected_revision="rev-2",
                new_revision="rev-1",
                lease_id=lease.lease_id,
                lease_epoch=0,
            ),
        )
        # Move head back requires a new revision parent path; put rev-3 from rev-2.
        step(
            "put_rev3",
            lambda: catalog.put_revision(
                "acme", "skills", "rev-3", parent_revision="rev-2"
            ),
        )
        step(
            "cas_with_lease",
            lambda: catalog.cas_set_head(
                "acme",
                "skills",
                "main",
                expected_revision="rev-2",
                new_revision="rev-3",
                lease_id=lease.lease_id,
                lease_epoch=lease.epoch,
            ),
        )
        step(
            "release_lease",
            lambda: catalog.release_lease(
                "acme",
                "skills",
                "main",
                lease_id=lease.lease_id,
                lease_epoch=lease.epoch,
            ),
        )

    step(
        "set_pin",
        lambda: catalog.set_pin_root(
            "acme",
            "skills",
            "rev-3" if lease is not None else "rev-2",
            "bafyroot000000000000000000000000000000000000000000000000001",
            pin_kind="manifest",
        ),
    )
    step(
        "list_pins",
        lambda: catalog.list_pin_roots("acme", "skills"),
    )

    step(
        "delete_other",
        lambda: catalog.delete_graph("acme", "other", reason="retired"),
    )
    step("list_after_delete", lambda: catalog.list_graphs("acme"))
    step(
        "list_tombstones",
        lambda: catalog.list_tombstones("acme", graph_id="other"),
    )
    step(
        "get_tombstoned",
        lambda: catalog.get_graph("acme", "other", allow_tombstoned=True),
    )
    step("not_found", lambda: catalog.describe_graph("nope", "missing"))

    # Final durable snapshot fields used for engine-to-engine equality.
    out["snapshot"] = _strip_volatile(
        {
            "graphs": _record_dict(catalog.list_graphs("acme")),
            "branches": _record_dict(
                catalog.list_branches("acme", "skills", include_tombstoned=True)
            ),
            "revisions": _record_dict(catalog.list_revisions("acme", "skills")),
            "pins": [
                {
                    "revision_id": p.revision_id,
                    "root_cid": p.root_cid,
                    "pin_kind": p.pin_kind,
                }
                for p in catalog.list_pin_roots("acme", "skills")
            ],
            "tombstones": _record_dict(catalog.list_tombstones("acme")),
            "lease": _record_dict(catalog.get_lease("acme", "skills", "main")),
            "head": catalog.get_branch("acme", "skills", "main").head_revision,
        }
    )
    return out


# ---------------------------------------------------------------------------
# Differential: SQLite vs DuckDB
# ---------------------------------------------------------------------------


def test_sqlite_and_duckdb_traces_are_equivalent(
    sqlite_path: Path, duckdb_path: Path
) -> None:
    with open_sqlite_catalog(sqlite_path) as sqlite_cat:
        sqlite_trace = _run_lifecycle_trace(sqlite_cat)
    with open_duckdb_catalog(duckdb_path) as duck_cat:
        duck_trace = _run_lifecycle_trace(duck_cat)

    # Step sequence and outcomes (codes / stripped payloads) must match.
    assert len(sqlite_trace["steps"]) == len(duck_trace["steps"])
    for s_step, d_step in zip(sqlite_trace["steps"], duck_trace["steps"]):
        assert s_step["name"] == d_step["name"], s_step["name"]
        assert s_step["ok"] == d_step["ok"], s_step["name"]
        if s_step["ok"]:
            assert s_step["result"] == d_step["result"], s_step["name"]
        else:
            assert s_step["error"]["code"] == d_step["error"]["code"], s_step[
                "name"
            ]
            assert (
                s_step["error"]["retryable"] == d_step["error"]["retryable"]
            ), s_step["name"]
            # Detail keys that matter for CAS/fencing should match.
            s_details = s_step["error"]["details"]
            d_details = d_step["error"]["details"]
            for key in (
                "expected_revision",
                "current_revision",
                "new_revision",
                "tenant",
                "graph_id",
                "branch",
                "operation",
            ):
                if key in s_details or key in d_details:
                    assert s_details.get(key) == d_details.get(key), (
                        s_step["name"],
                        key,
                        s_details,
                        d_details,
                    )

    assert sqlite_trace["snapshot"] == duck_trace["snapshot"]


def test_duckdb_schema_id_recorded(duckdb_catalog: DuckDBGraphCatalog) -> None:
    assert isinstance(duckdb_catalog.path, Path)
    row = duckdb_catalog._fetchone(  # noqa: SLF001 — schema authority check
        duckdb_catalog._conn,  # noqa: SLF001
        "SELECT value FROM catalog_meta WHERE key = ?",
        ["schema_id"],
    )
    assert row is not None
    assert row["value"] == DUCKDB_CATALOG_SCHEMA


# ---------------------------------------------------------------------------
# CAS atomicity: conflict leaves no partial mutation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "opener,filename",
    [
        (_open_sqlite, "cas.sqlite"),
        (_open_duckdb, "cas.duckdb"),
    ],
)
def test_cas_conflict_fails_without_partial_mutation(
    tmp_path: Path,
    opener: CatalogFactory,
    filename: str,
) -> None:
    path = tmp_path / filename
    cat = opener(path)
    try:
        cat.create_graph("t", "g")
        boot = bootstrap_revision_id("t", "g")
        cat.put_revision("t", "g", "rev-1", parent_revision=boot)
        cat.put_revision("t", "g", "rev-2", parent_revision="rev-1")
        cat.cas_set_head(
            "t", "g", "main", expected_revision=boot, new_revision="rev-1"
        )

        pins_before = {
            (p.revision_id, p.root_cid, p.pin_kind)
            for p in cat.list_pin_roots("t", "g")
        }
        head_before = cat.get_branch("t", "g", "main").head_revision
        graph_updated_before = cat.get_graph("t", "g").updated_at
        rev2_before = cat.get_revision("t", "g", "rev-2")

        with pytest.raises(CatalogError) as excinfo:
            cat.cas_set_head(
                "t",
                "g",
                "main",
                expected_revision=boot,  # stale expected
                new_revision="rev-2",
                pin_root="bafy-must-not-appear",
            )
        err = excinfo.value
        assert err.code == "CONFLICT"
        assert err.retryable is True
        assert err.details["current_revision"] == "rev-1"
        assert err.details["expected_revision"] == boot

        # No head move, no new pin, revision unchanged.
        assert cat.get_branch("t", "g", "main").head_revision == head_before
        pins_after = {
            (p.revision_id, p.root_cid, p.pin_kind)
            for p in cat.list_pin_roots("t", "g")
        }
        assert pins_after == pins_before
        assert all(p.root_cid != "bafy-must-not-appear" for p in cat.list_pin_roots("t", "g"))
        rev2_after = cat.get_revision("t", "g", "rev-2")
        assert rev2_after.pin_root == rev2_before.pin_root
        # Graph metadata timestamp may only change on successful mutation.
        assert cat.get_graph("t", "g").updated_at == graph_updated_before
    finally:
        cat.close()


def test_duckdb_cas_conflict_is_transactional(duckdb_path: Path) -> None:
    """Failed CAS rolls back; subsequent correct CAS still works cleanly."""
    with open_duckdb_catalog(duckdb_path) as cat:
        cat.create_graph("t", "g")
        boot = bootstrap_revision_id("t", "g")
        cat.put_revision("t", "g", "rev-1", parent_revision=boot)
        cat.put_revision("t", "g", "rev-2", parent_revision="rev-1")
        cat.cas_set_head(
            "t", "g", "main", expected_revision=boot, new_revision="rev-1"
        )
        with pytest.raises(CatalogError) as excinfo:
            cat.cas_set_head(
                "t",
                "g",
                "main",
                expected_revision=boot,
                new_revision="rev-2",
                pin_root="bafy-nope",
            )
        assert excinfo.value.code == "CONFLICT"
        moved = cat.cas_set_head(
            "t",
            "g",
            "main",
            expected_revision="rev-1",
            new_revision="rev-2",
            pin_root="bafy-yes",
        )
        assert moved.head_revision == "rev-2"
        pins = cat.list_pin_roots("t", "g", revision_id="rev-2")
        assert any(p.root_cid == "bafy-yes" for p in pins)
        assert not any(p.root_cid == "bafy-nope" for p in cat.list_pin_roots("t", "g"))


# ---------------------------------------------------------------------------
# Restart durability: pins, leases, tombstones, idempotency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "opener,filename",
    [
        (_open_sqlite, "restart.sqlite"),
        (_open_duckdb, "restart.duckdb"),
    ],
)
def test_pins_leases_tombstones_idempotency_survive_restart(
    tmp_path: Path,
    opener: CatalogFactory,
    filename: str,
) -> None:
    path = tmp_path / filename
    with opener(path) as cat1:
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
        lease = cat1.acquire_lease(
            "acme", "skills", "main", holder="w1", ttl_seconds=120.0
        )
        cat1.create_graph("acme", "other", idempotency_key="idemp-restart")
        cat1.create_graph("acme", "doomed")
        cat1.delete_graph("acme", "doomed", reason="gc")
        cat1.set_pin_root(
            "acme",
            "skills",
            "rev-1",
            "bafymanifest",
            pin_kind="manifest",
        )
        lease_id = lease.lease_id
        lease_epoch = lease.epoch

    # Fresh instance — no ambient process cache.
    with opener(path) as cat2:
        desc = cat2.describe_graph("acme", "skills")
        assert desc.head_revision == "rev-1"
        assert desc.storage_profile == "ipfs_ipld"

        branch = cat2.get_branch("acme", "skills", "main")
        assert branch.head_revision == "rev-1"

        pins = cat2.list_pin_roots("acme", "skills", revision_id="rev-1")
        cids = {p.root_cid for p in pins}
        assert "bafy1" in cids
        assert "bafymanifest" in cids

        lease2 = cat2.get_lease("acme", "skills", "main")
        assert lease2 is not None
        assert lease2.holder == "w1"
        assert lease2.lease_id == lease_id
        assert lease2.epoch == lease_epoch

        # Idempotency survives restart.
        g = cat2.create_graph("acme", "other", idempotency_key="idemp-restart")
        assert g.graph_id == "other"
        graphs = cat2.list_graphs("acme")
        assert {x.graph_id for x in graphs} == {"skills", "other"}

        tombs = cat2.list_tombstones("acme", graph_id="doomed")
        assert any(t.entity_type == "graph" and t.reason == "gc" for t in tombs)
        soft = cat2.get_graph("acme", "doomed", allow_tombstoned=True)
        assert soft.status == "tombstoned"


def test_duckdb_idempotency_lookup_after_restart(duckdb_path: Path) -> None:
    with open_duckdb_catalog(duckdb_path) as cat:
        cat.create_graph(
            "t",
            "g",
            idempotency_key="k-restart",
            storage_profile="parquet",
        )
        rec = cat.get_idempotency("k-restart")
        assert rec is not None
        assert rec.operation == "create_graph"

    with open_duckdb_catalog(duckdb_path) as cat2:
        rec2 = cat2.get_idempotency("k-restart")
        assert rec2 is not None
        assert rec2.request_hash == rec.request_hash
        again = cat2.create_graph(
            "t",
            "g",
            idempotency_key="k-restart",
            storage_profile="parquet",
        )
        assert again.graph_id == "g"


# ---------------------------------------------------------------------------
# DuckDB-native behavioral coverage (mirrors core SQLite guarantees)
# ---------------------------------------------------------------------------


def test_duckdb_create_graph_bootstrap_and_uniqueness(
    duckdb_catalog: DuckDBGraphCatalog,
) -> None:
    g = duckdb_catalog.create_graph(
        "acme",
        "skills",
        storage_profile="hybrid",
        graph_kind="skills",
        pin_root="bafybootstrap0000000000000000000000000000000000000000000001",
    )
    assert g.uri == "kg://acme/skills"
    boot = bootstrap_revision_id("acme", "skills")
    assert duckdb_catalog.get_branch("acme", "skills", "main").head_revision == boot
    pins = duckdb_catalog.list_pin_roots("acme", "skills", revision_id=boot)
    assert len(pins) == 1

    with pytest.raises(CatalogError) as excinfo:
        duckdb_catalog.create_graph("acme", "skills")
    assert excinfo.value.code == "ALREADY_EXISTS"
    assert excinfo.value.retryable is False


def test_duckdb_leases_fencing_and_release(
    duckdb_catalog: DuckDBGraphCatalog,
) -> None:
    duckdb_catalog.create_graph("t", "g")
    boot = bootstrap_revision_id("t", "g")
    duckdb_catalog.put_revision("t", "g", "rev-1", parent_revision=boot)

    lease = duckdb_catalog.acquire_lease(
        "t", "g", "main", holder="writer-a", ttl_seconds=60.0
    )
    assert lease.epoch == 1

    with pytest.raises(CatalogError) as excinfo:
        duckdb_catalog.acquire_lease(
            "t", "g", "main", holder="writer-b", ttl_seconds=60.0
        )
    assert excinfo.value.code == "CONFLICT"

    with pytest.raises(CatalogError) as excinfo:
        duckdb_catalog.cas_set_head(
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

    moved = duckdb_catalog.cas_set_head(
        "t",
        "g",
        "main",
        expected_revision=boot,
        new_revision="rev-1",
        lease_id=lease.lease_id,
        lease_epoch=lease.epoch,
    )
    assert moved.head_revision == "rev-1"

    duckdb_catalog.release_lease(
        "t",
        "g",
        "main",
        lease_id=lease.lease_id,
        lease_epoch=lease.epoch,
    )
    assert duckdb_catalog.get_lease("t", "g", "main") is None


def test_duckdb_expired_lease_steal(
    duckdb_catalog: DuckDBGraphCatalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ipfs_datasets_py.knowledge_graphs.catalog.duckdb_store as dmod

    duckdb_catalog.create_graph("t", "g")
    lease = duckdb_catalog.acquire_lease(
        "t", "g", "main", holder="a", ttl_seconds=0.001
    )
    monkeypatch.setattr(dmod, "is_expired", lambda *a, **k: True)
    stolen = duckdb_catalog.acquire_lease(
        "t", "g", "main", holder="b", ttl_seconds=30.0
    )
    assert stolen.holder == "b"
    assert stolen.epoch == lease.epoch + 1
    assert stolen.lease_id != lease.lease_id


def test_duckdb_invalid_slugs(duckdb_catalog: DuckDBGraphCatalog) -> None:
    with pytest.raises(CatalogError) as excinfo:
        duckdb_catalog.create_graph("ACME", "g1")
    assert excinfo.value.code == "INVALID_TARGET"
    with pytest.raises(CatalogError):
        duckdb_catalog.create_graph("acme", "bad/id")
    with pytest.raises(CatalogError):
        duckdb_catalog.create_graph("acme", "g1", storage_profile="s3")


def test_duckdb_reopen_rejects_future_schema(
    duckdb_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with open_duckdb_catalog(duckdb_path) as cat:
        cat.create_graph("t", "g")
        cat._conn.execute(  # noqa: SLF001
            "UPDATE catalog_meta SET value = ? WHERE key = 'schema_version'",
            ["999"],
        )

    import ipfs_datasets_py.knowledge_graphs.catalog.duckdb_store as dmod

    # Ensure version gate uses module constant.
    assert dmod._SCHEMA_VERSION < 999  # noqa: SLF001
    with pytest.raises(CatalogError) as excinfo:
        open_duckdb_catalog(duckdb_path)
    assert excinfo.value.code == "STORAGE"
    assert "newer" in excinfo.value.message


def test_duckdb_class_exports() -> None:
    assert issubclass(DuckDBGraphCatalog, object)
    assert callable(open_duckdb_catalog)
    assert DUCKDB_CATALOG_SCHEMA.startswith("ipfs_datasets_py/")
