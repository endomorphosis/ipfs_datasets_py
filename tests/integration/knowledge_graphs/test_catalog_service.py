"""Integration tests: durable catalog restart, multi-identity concurrency, CAS.

KGP-005 acceptance:
  Persist tenant/graph lifecycle, branches, immutable revision records, head
  CAS, tombstones, leases, idempotency, and pin roots. Prove restart behavior,
  concurrent graph identity, uniqueness, atomic head movement, and deterministic
  typed conflicts without relying on process caches.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import List

import pytest

from ipfs_datasets_py.knowledge_graphs.catalog import (
    CatalogError,
    bootstrap_revision_id,
    open_catalog,
)

# Repo root so child processes can import the package without relying on
# pytest's pythonpath injection (process boundary / restart proofs).
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _child_env() -> dict:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT) if not existing else f"{_REPO_ROOT}{os.pathsep}{existing}"
    )
    return env


def _catalog_path(tmp_path: Path, name: str = "kg_catalog.sqlite") -> Path:
    return tmp_path / name


def _run_child(script: str, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
    """Run a child Python process (true process boundary; no shared caches)."""
    return subprocess.run(
        [sys.executable, "-c", script, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=_child_env(),
        cwd=str(_REPO_ROOT),
    )


_CHILD_CREATE = r"""
import json, sys
from ipfs_datasets_py.knowledge_graphs.catalog import open_catalog, bootstrap_revision_id
path, tenant, graph_id = sys.argv[1], sys.argv[2], sys.argv[3]
cat = open_catalog(path)
try:
    cat.create_graph(tenant, graph_id, storage_profile="parquet")
    boot = bootstrap_revision_id(tenant, graph_id)
    cat.put_revision(tenant, graph_id, "rev-proc-1", parent_revision=boot, pin_root="bafyproc1", checksum="c"*64)
    branch = cat.cas_set_head(tenant, graph_id, "main", expected_revision=boot, new_revision="rev-proc-1", pin_root="bafyproc1", idempotency_key=f"cas-{tenant}-{graph_id}")
    lease = cat.acquire_lease(tenant, graph_id, "main", holder="proc-writer", ttl_seconds=300.0)
    print(json.dumps({"head": branch.head_revision, "lease_epoch": lease.epoch, "lease_id": lease.lease_id}))
finally:
    cat.close()
"""

_CHILD_DESCRIBE = r"""
import json, sys
from ipfs_datasets_py.knowledge_graphs.catalog import open_catalog
path, tenant, graph_id = sys.argv[1], sys.argv[2], sys.argv[3]
cat = open_catalog(path)
try:
    desc = cat.describe_graph(tenant, graph_id)
    lease = cat.get_lease(tenant, graph_id, "main")
    pins = cat.list_pin_roots(tenant, graph_id, revision_id=desc.head_revision)
    idem = cat.get_idempotency(f"cas-{tenant}-{graph_id}")
    print(json.dumps({
        "head": desc.head_revision,
        "status": desc.status,
        "storage_profile": desc.storage_profile,
        "branch_count": len(desc.branches),
        "lease_holder": None if lease is None else lease.holder,
        "pin_count": len(pins),
        "idempotency_present": idem is not None,
    }))
finally:
    cat.close()
"""

_CHILD_TRY_CREATE = r"""
import json, sys
from ipfs_datasets_py.knowledge_graphs.catalog import open_catalog, CatalogError
path, tenant, graph_id = sys.argv[1], sys.argv[2], sys.argv[3]
cat = open_catalog(path)
try:
    try:
        cat.create_graph(tenant, graph_id)
        print(json.dumps(["ok", None]))
    except CatalogError as exc:
        print(json.dumps(["err", exc.code]))
finally:
    cat.close()
"""

_CHILD_TRY_CAS = r"""
import json, sys
from ipfs_datasets_py.knowledge_graphs.catalog import open_catalog, CatalogError
path, tenant, graph_id, expected, new_rev = sys.argv[1:6]
cat = open_catalog(path)
try:
    try:
        cat.cas_set_head(tenant, graph_id, "main", expected_revision=expected, new_revision=new_rev)
        print(json.dumps(["ok", new_rev]))
    except CatalogError as exc:
        print(json.dumps(["err", exc.code]))
finally:
    cat.close()
"""


class TestCatalogLifecycleIntegration:
    def test_full_lifecycle_create_branch_cas_tombstone(
        self, tmp_path: Path
    ) -> None:
        path = _catalog_path(tmp_path)
        with open_catalog(path) as cat:
            g = cat.create_graph(
                "acme",
                "skills",
                branch="main",
                storage_profile="hybrid",
                graph_kind="skills",
                metadata={"owner": "team-a"},
            )
            assert g.uri == "kg://acme/skills"
            boot = bootstrap_revision_id("acme", "skills")

            cat.put_revision(
                "acme",
                "skills",
                "rev-1",
                parent_revision=boot,
                manifest_json=json.dumps({"n": 1}),
                pin_root="bafyrev1",
            )
            cat.put_revision(
                "acme",
                "skills",
                "rev-2",
                parent_revision="rev-1",
                pin_root="bafyrev2",
            )

            cat.cas_set_head(
                "acme",
                "skills",
                "main",
                expected_revision=boot,
                new_revision="rev-1",
            )
            feature = cat.create_branch(
                "acme", "skills", "feature", from_branch="main"
            )
            assert feature.head_revision == "rev-1"
            cat.cas_set_head(
                "acme",
                "skills",
                "feature",
                expected_revision="rev-1",
                new_revision="rev-2",
            )

            desc_main = cat.describe_graph("acme", "skills", branch="main")
            assert desc_main.head_revision == "rev-1"
            desc_feat = cat.describe_graph("acme", "skills", branch="feature")
            assert desc_feat.head_revision == "rev-2"

            tomb_branch = cat.delete_branch(
                "acme", "skills", "feature", reason="merged"
            )
            assert tomb_branch.entity_type == "branch"
            tomb_graph = cat.delete_graph("acme", "skills", reason="archive")
            assert tomb_graph.entity_type == "graph"
            assert cat.list_graphs("acme") == []
            assert (
                cat.get_graph("acme", "skills", allow_tombstoned=True).status
                == "tombstoned"
            )


class TestCatalogRestartIntegration:
    def test_reopen_same_path_after_close(self, tmp_path: Path) -> None:
        path = _catalog_path(tmp_path)
        with open_catalog(path) as cat:
            cat.create_graph("t", "g", idempotency_key="create-g")
            boot = bootstrap_revision_id("t", "g")
            cat.put_revision("t", "g", "r1", parent_revision=boot)
            cat.cas_set_head(
                "t", "g", "main", expected_revision=boot, new_revision="r1"
            )
            cat.set_pin_root("t", "g", "r1", "bafypin1", pin_kind="manifest")

        # Brand-new object — proves durability, not cache.
        with open_catalog(path) as cat2:
            assert cat2.get_branch("t", "g", "main").head_revision == "r1"
            assert cat2.get_idempotency("create-g") is not None
            assert len(cat2.list_pin_roots("t", "g")) >= 1
            g = cat2.create_graph("t", "g", idempotency_key="create-g")
            assert g.graph_id == "g"

    def test_subprocess_restart_boundary(self, tmp_path: Path) -> None:
        path = str(_catalog_path(tmp_path))
        created = _run_child(_CHILD_CREATE, path, "tenant-mp", "graph-mp")
        assert created.returncode == 0, created.stderr
        payload = json.loads(created.stdout.strip())
        assert payload["head"] == "rev-proc-1"

        seen_proc = _run_child(_CHILD_DESCRIBE, path, "tenant-mp", "graph-mp")
        assert seen_proc.returncode == 0, seen_proc.stderr
        seen = json.loads(seen_proc.stdout.strip())
        assert seen["head"] == "rev-proc-1"
        assert seen["status"] == "active"
        assert seen["lease_holder"] == "proc-writer"
        assert seen["pin_count"] >= 1
        assert seen["idempotency_present"] is True
        assert seen["branch_count"] == 1


class TestCatalogConcurrencyIntegration:
    def test_concurrent_distinct_graph_identities(self, tmp_path: Path) -> None:
        path = _catalog_path(tmp_path)
        n = 16
        barrier = threading.Barrier(n)
        errors: List[BaseException] = []

        def worker(i: int) -> None:
            cat = open_catalog(path)
            try:
                barrier.wait(timeout=15)
                cat.create_graph("shared-tenant", f"graph-{i:02d}")
                boot = bootstrap_revision_id("shared-tenant", f"graph-{i:02d}")
                cat.put_revision(
                    "shared-tenant",
                    f"graph-{i:02d}",
                    f"rev-{i}",
                    parent_revision=boot,
                )
                cat.cas_set_head(
                    "shared-tenant",
                    f"graph-{i:02d}",
                    "main",
                    expected_revision=boot,
                    new_revision=f"rev-{i}",
                )
            except BaseException as exc:  # noqa: BLE001 — collect for assert
                errors.append(exc)
            finally:
                cat.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
            assert not t.is_alive()
        assert errors == []

        with open_catalog(path) as cat:
            graphs = cat.list_graphs("shared-tenant")
            assert len(graphs) == n
            for i in range(n):
                head = cat.get_branch(
                    "shared-tenant", f"graph-{i:02d}", "main"
                ).head_revision
                assert head == f"rev-{i}"

    def test_concurrent_same_identity_one_winner(self, tmp_path: Path) -> None:
        path = str(_catalog_path(tmp_path))
        n = 6
        # Launch overlapping child processes for true multi-process uniqueness.
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", _CHILD_TRY_CREATE, path, "uniq", "only-one"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=_child_env(),
                cwd=str(_REPO_ROOT),
            )
            for _ in range(n)
        ]
        results = []
        for p in procs:
            out, err = p.communicate(timeout=60)
            assert p.returncode == 0, err
            results.append(json.loads(out.strip()))

        oks = [r for r in results if r[0] == "ok"]
        errs = [r for r in results if r[0] == "err"]
        assert len(oks) == 1
        assert len(errs) == n - 1
        assert all(code == "ALREADY_EXISTS" for _, code in errs)

        with open_catalog(path) as cat:
            assert len(cat.list_graphs("uniq")) == 1

    def test_concurrent_cas_atomic_single_head(self, tmp_path: Path) -> None:
        path = str(_catalog_path(tmp_path))
        with open_catalog(path) as setup:
            setup.create_graph("cas", "g")
            boot = bootstrap_revision_id("cas", "g")
            for i in range(6):
                setup.put_revision(
                    "cas", "g", f"cand-{i}", parent_revision=boot
                )

        procs = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    _CHILD_TRY_CAS,
                    path,
                    "cas",
                    "g",
                    boot,
                    f"cand-{i}",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=_child_env(),
                cwd=str(_REPO_ROOT),
            )
            for i in range(6)
        ]
        results = []
        for p in procs:
            out, err = p.communicate(timeout=60)
            assert p.returncode == 0, err
            results.append(json.loads(out.strip()))

        oks = [r for r in results if r[0] == "ok"]
        errs = [r for r in results if r[0] == "err"]
        assert len(oks) == 1
        assert len(errs) == 5
        assert all(code == "CONFLICT" for _, code in errs)

        winner = oks[0][1]
        with open_catalog(path) as cat:
            assert cat.get_branch("cas", "g", "main").head_revision == winner
            with pytest.raises(CatalogError) as excinfo:
                cat.cas_set_head(
                    "cas",
                    "g",
                    "main",
                    expected_revision=boot,
                    new_revision="cand-0" if winner != "cand-0" else "cand-1",
                )
            assert excinfo.value.code == "CONFLICT"
            assert excinfo.value.details["current_revision"] == winner


class TestCatalogLeaseAndIdempotencyIntegration:
    def test_lease_fences_stale_writer_after_steal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import ipfs_datasets_py.knowledge_graphs.catalog.store as store_mod
        from ipfs_datasets_py.knowledge_graphs.catalog.identity import (
            is_expired as real_is_expired,
        )

        path = _catalog_path(tmp_path)
        with open_catalog(path) as cat:
            cat.create_graph("t", "g")
            boot = bootstrap_revision_id("t", "g")
            cat.put_revision("t", "g", "r1", parent_revision=boot)
            cat.put_revision("t", "g", "r2", parent_revision="r1")
            old = cat.acquire_lease(
                "t", "g", "main", holder="old", ttl_seconds=1.0
            )

        # Force-expire only for the steal acquisition; restore real checks for CAS.
        monkeypatch.setattr(store_mod, "is_expired", lambda *a, **k: True)
        with open_catalog(path) as cat:
            new = cat.acquire_lease(
                "t", "g", "main", holder="new", ttl_seconds=60.0
            )
            assert new.epoch == old.epoch + 1

        monkeypatch.setattr(store_mod, "is_expired", real_is_expired)
        with open_catalog(path) as cat:
            with pytest.raises(CatalogError) as excinfo:
                cat.cas_set_head(
                    "t",
                    "g",
                    "main",
                    expected_revision=boot,
                    new_revision="r1",
                    lease_id=old.lease_id,
                    lease_epoch=old.epoch,
                )
            assert excinfo.value.code == "FENCED"
            moved = cat.cas_set_head(
                "t",
                "g",
                "main",
                expected_revision=boot,
                new_revision="r1",
                lease_id=new.lease_id,
                lease_epoch=new.epoch,
            )
            assert moved.head_revision == "r1"

    def test_idempotent_cas_does_not_double_apply(self, tmp_path: Path) -> None:
        path = _catalog_path(tmp_path)
        with open_catalog(path) as cat:
            cat.create_graph("t", "g")
            boot = bootstrap_revision_id("t", "g")
            cat.put_revision("t", "g", "r1", parent_revision=boot)
            cat.put_revision("t", "g", "r2", parent_revision="r1")
            first = cat.cas_set_head(
                "t",
                "g",
                "main",
                expected_revision=boot,
                new_revision="r1",
                idempotency_key="write-1",
            )
        with open_catalog(path) as cat:
            second = cat.cas_set_head(
                "t",
                "g",
                "main",
                expected_revision=boot,
                new_revision="r1",
                idempotency_key="write-1",
            )
            assert second.head_revision == first.head_revision == "r1"
            assert cat.get_branch("t", "g", "main").head_revision == "r1"
            with pytest.raises(CatalogError) as excinfo:
                cat.cas_set_head(
                    "t",
                    "g",
                    "main",
                    expected_revision=boot,
                    new_revision="r2",
                    idempotency_key="write-1",
                )
            assert excinfo.value.code == "CONFLICT"


class TestCatalogTypedConflicts:
    def test_deterministic_error_codes(self, tmp_path: Path) -> None:
        path = _catalog_path(tmp_path)
        with open_catalog(path) as cat:
            cat.create_graph("t", "g")
            boot = bootstrap_revision_id("t", "g")

            with pytest.raises(CatalogError) as e1:
                catalog_create = cat.create_graph
                catalog_create("t", "g")
            assert e1.value.code == "ALREADY_EXISTS"

            with pytest.raises(CatalogError) as e2:
                cat.get_graph("t", "missing")
            assert e2.value.code == "NOT_FOUND"

            cat.put_revision("t", "g", "r1", parent_revision=boot)
            cat.cas_set_head(
                "t", "g", "main", expected_revision=boot, new_revision="r1"
            )
            with pytest.raises(CatalogError) as e3:
                cat.cas_set_head(
                    "t",
                    "g",
                    "main",
                    expected_revision=boot,
                    new_revision="r1",
                )
            assert e3.value.code == "CONFLICT"
            assert e3.value.retryable is True

            with pytest.raises(CatalogError) as e4:
                cat.create_graph("Bad Tenant", "g2")
            assert e4.value.code == "INVALID_TARGET"
