"""Python package API conformance (KGP-017).

Acceptance:
  Export versioned Client/AsyncClient, GraphTarget, transactions, results, and
  typed errors. Clients share configured service/catalog state, reopen after
  restart, expose sync/async streaming and context management, and do not make
  optional backends import-time requirements.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _child_env() -> dict:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT) if not existing else f"{_REPO_ROOT}{os.pathsep}{existing}"
    )
    return env


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "kg_catalog.sqlite", tmp_path / "kg_payloads"


# ---------------------------------------------------------------------------
# Public export surface
# ---------------------------------------------------------------------------


class TestStableExports:
    def test_package_exports_versioned_client_surface(self) -> None:
        import ipfs_datasets_py.knowledge_graphs as kg

        assert kg.CLIENT_API_VERSION == "kg-python-client/v1"
        assert kg.CONTRACT_VERSION == "kg-service-contract/v1"
        assert kg.QUERY_ENVELOPE_VERSION == "kg-query-envelope/v1"

        for name in (
            "Client",
            "AsyncClient",
            "GraphTarget",
            "Transaction",
            "LifecycleResult",
            "LifecycleRequest",
            "QueryResultEnvelope",
            "TypedError",
            "ServiceError",
            "GraphTargetError",
            "StreamPage",
            "ClientConfig",
            "GraphService",
            "raise_for_status",
            "TYPED_ERROR_CODES",
        ):
            assert name in kg.__all__, f"{name} missing from __all__"
            assert hasattr(kg, name), f"{name} not importable from package root"

    def test_star_import_includes_stable_api_not_legacy_convenience(self) -> None:
        ns: Dict[str, object] = {}
        exec("from ipfs_datasets_py.knowledge_graphs import *", {}, ns)

        assert "Client" in ns
        assert "AsyncClient" in ns
        assert "GraphTarget" in ns
        assert "LifecycleResult" in ns
        assert "TypedError" in ns
        assert "ServiceError" in ns
        assert "Transaction" in ns
        assert "KnowledgeGraphError" in ns
        assert "QueryParseError" in ns

        # Convenience legacy symbols must not be star-exported.
        assert "GraphDatabase" not in ns
        assert "GraphEngine" not in ns
        assert "Entity" not in ns

    def test_client_module_reexports_contract_types(self) -> None:
        from ipfs_datasets_py.knowledge_graphs import client as client_mod

        assert client_mod.CLIENT_API_VERSION == "kg-python-client/v1"
        assert client_mod.Client is not None
        assert client_mod.AsyncClient is not None
        assert client_mod.GraphTarget is not None
        assert client_mod.TypedError is not None
        assert client_mod.LifecycleResult is not None
        assert client_mod.QueryResultEnvelope is not None


# ---------------------------------------------------------------------------
# No optional backends at import time
# ---------------------------------------------------------------------------


class TestImportTimeOptionalBackends:
    def test_root_and_client_import_skip_optional_backends(self) -> None:
        """Importing the stable API must not require optional ML/graph backends."""
        script = r"""
import sys
# Ensure optional modules are not already loaded from parent env noise.
for name in list(sys.modules):
    top = name.split(".", 1)[0]
    if top in {
        "spacy", "transformers", "openai", "anthropic", "neo4j",
        "networkx", "torch", "tensorflow", "ipfs_kit_py", "ipfs_kit",
    }:
        del sys.modules[name]

before = set(sys.modules)
import ipfs_datasets_py.knowledge_graphs as kg
from ipfs_datasets_py.knowledge_graphs.client import Client, AsyncClient
after = set(sys.modules) - before
pulled = sorted({
    m.split(".", 1)[0]
    for m in after
    if m.split(".", 1)[0] in {
        "spacy", "transformers", "openai", "anthropic", "neo4j",
        "networkx", "torch", "tensorflow", "ipfs_kit_py", "ipfs_kit",
    }
})
assert not pulled, f"optional backends imported: {pulled}"
assert kg.Client is Client
assert AsyncClient is not None
print("ok")
"""
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
            env=_child_env(),
            cwd=str(_REPO_ROOT),
        )
        assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
        assert "ok" in proc.stdout


# ---------------------------------------------------------------------------
# Shared service / catalog state + context management
# ---------------------------------------------------------------------------


class TestClientLifecycleAndSharing:
    def test_context_manager_and_no_ambient_graph(self, tmp_path: Path) -> None:
        from ipfs_datasets_py.knowledge_graphs import Client, GraphTarget

        catalog_path, storage_path = _paths(tmp_path)
        with Client.open(catalog_path, storage_path=storage_path) as client:
            assert client.api_version == "kg-python-client/v1"
            assert client.contract_version == "kg-service-contract/v1"
            assert not client.closed
            assert client.config is not None
            assert client.config.catalog_path == catalog_path.resolve()
            # No ambient graph on a fresh client.
            listed = client.list(GraphTarget(tenant="acme", graph_id="list"))
            assert listed.ok
            assert listed.result is not None
            assert listed.result["graphs"] == []
            assert client.service._open_handles == {}  # noqa: SLF001
        assert client.closed

    def test_shared_clients_share_service_state(self, tmp_path: Path) -> None:
        from ipfs_datasets_py.knowledge_graphs import Client, GraphTarget

        catalog_path, storage_path = _paths(tmp_path)
        with Client.open(catalog_path, storage_path=storage_path) as primary:
            shared = primary.share()
            assert shared.service is primary.service
            assert shared is not primary
            assert not shared._owns_service  # noqa: SLF001

            target = GraphTarget(tenant="acme", graph_id="shared", branch="main")
            created = primary.create(target, idempotency_key="share-create")
            assert created.ok, created.to_json_dict()

            # Shared handle sees the same catalog immediately.
            described = shared.describe(target)
            assert described.ok
            assert described.result is not None
            assert described.result["uri"] == "kg://acme/shared"
            assert described.result["head_revision"]
            assert described.target is not None
            assert described.target.graph_id == "shared"

            # Closing the shared handle must not close the primary service.
            shared.close()
            assert shared.closed
            assert not primary.closed
            listed = primary.list(GraphTarget(tenant="acme", graph_id="list"))
            assert listed.ok
            assert any(g["graph_id"] == "shared" for g in listed.result["graphs"])

    def test_from_service_wraps_existing_service(self, tmp_path: Path) -> None:
        from ipfs_datasets_py.knowledge_graphs import Client, GraphService, GraphTarget

        catalog_path, storage_path = _paths(tmp_path)
        with GraphService.open(catalog_path, storage_path=storage_path) as svc:
            client = Client.from_service(svc, owns_service=False)
            try:
                t = GraphTarget(tenant="wrap", graph_id="g1", branch="main")
                r = client.create(t, idempotency_key="wrap-1")
                assert r.ok
            finally:
                client.close()
            # Service still usable after non-owning client close.
            d = svc.describe(GraphTarget(tenant="wrap", graph_id="g1", branch="main"))
            assert d.ok


# ---------------------------------------------------------------------------
# Reopen after restart
# ---------------------------------------------------------------------------


class TestReopenAfterRestart:
    def test_new_client_reopens_committed_graph(self, tmp_path: Path) -> None:
        from ipfs_datasets_py.knowledge_graphs import Client, GraphTarget

        catalog_path, storage_path = _paths(tmp_path)
        target = GraphTarget(tenant="acme", graph_id="durable", branch="main")

        with Client.open(catalog_path, storage_path=storage_path) as c1:
            assert c1.create(target, idempotency_key="dur-c").ok
            w = c1.write(
                target,
                idempotency_key="dur-w",
                params={
                    "entities": [
                        {"id": "e1", "type": "Person", "name": "Ada"},
                    ]
                },
            )
            assert w.ok, w.to_json_dict()
            rev = w.result["revision"]

        # Brand-new client — no process-local caches.
        with Client.open(catalog_path, storage_path=storage_path) as c2:
            assert c2.service._open_handles == {}  # noqa: SLF001
            opened = c2.open_graph(target)
            assert opened.ok, opened.to_json_dict()
            assert opened.result["revision"] == rev
            q = c2.query(target, params={"language": "scan"})
            assert q.ok
            assert q.result["row_count"] == 1
            assert q.result["rows"][0][2] == "Ada"
            # Results are JSON-safe.
            json.dumps(q.to_json_dict(), allow_nan=False)

    def test_subprocess_reopen_boundary(self, tmp_path: Path) -> None:
        catalog_path, storage_path = _paths(tmp_path)
        cat, store = str(catalog_path), str(storage_path)

        writer = r"""
import json, sys
from ipfs_datasets_py.knowledge_graphs import Client, GraphTarget
cat, store = sys.argv[1], sys.argv[2]
with Client.open(cat, storage_path=store) as client:
    t = GraphTarget(tenant="mp", graph_id="g1", branch="main")
    c = client.create(t, idempotency_key="mp-create")
    assert c.status == "success", c.to_json_dict()
    w = client.write(
        t,
        idempotency_key="mp-write",
        params={"entities": [{"id": "n1", "type": "T", "name": "proc"}]},
    )
    assert w.status == "success", w.to_json_dict()
    print(json.dumps({"revision": w.result["revision"]}))
"""
        reader = r"""
import json, sys
from ipfs_datasets_py.knowledge_graphs import Client, GraphTarget
cat, store, expected = sys.argv[1], sys.argv[2], sys.argv[3]
with Client.open(cat, storage_path=store) as client:
    assert client.service._open_handles == {}
    t = GraphTarget(tenant="mp", graph_id="g1", branch="main")
    o = client.open_graph(t)
    assert o.status == "success", o.to_json_dict()
    q = client.query(t, params={"language": "scan"})
    assert q.status == "success", q.to_json_dict()
    print(json.dumps({
        "revision": o.result["revision"],
        "row_count": q.result["row_count"],
        "name": q.result["rows"][0][2] if q.result["rows"] else None,
    }))
"""
        w = subprocess.run(
            [sys.executable, "-c", writer, cat, store],
            capture_output=True,
            text=True,
            timeout=60,
            env=_child_env(),
            cwd=str(_REPO_ROOT),
        )
        assert w.returncode == 0, w.stdout + w.stderr
        rev = json.loads(w.stdout.strip())["revision"]

        r = subprocess.run(
            [sys.executable, "-c", reader, cat, store, rev],
            capture_output=True,
            text=True,
            timeout=60,
            env=_child_env(),
            cwd=str(_REPO_ROOT),
        )
        assert r.returncode == 0, r.stdout + r.stderr
        payload = json.loads(r.stdout.strip())
        assert payload["revision"] == rev
        assert payload["row_count"] == 1
        assert payload["name"] == "proc"


# ---------------------------------------------------------------------------
# Transactions + typed errors + results
# ---------------------------------------------------------------------------


class TestTransactionsResultsAndErrors:
    def test_transaction_context_manager_commit(self, tmp_path: Path) -> None:
        from ipfs_datasets_py.knowledge_graphs import Client, GraphTarget

        catalog_path, storage_path = _paths(tmp_path)
        target = GraphTarget(tenant="acme", graph_id="txg", branch="main")
        with Client.open(catalog_path, storage_path=storage_path) as client:
            assert client.create(target, idempotency_key="tx-create").ok
            with client.transaction(
                target, idempotency_key="tx-commit-1", raise_on_error=True
            ) as tx:
                assert tx.transaction_id is not None
                assert tx.state == "open"
                staged = tx.stage(
                    entities=[{"id": "t1", "type": "Thing", "name": "staged"}]
                )
                assert staged.ok, staged.to_json_dict()
            assert tx.state == "committed"
            assert tx.commit_result is not None and tx.commit_result.ok
            q = client.query(target, params={"language": "scan"})
            assert q.ok
            assert q.result["row_count"] == 1

    def test_transaction_rollback_on_exception(self, tmp_path: Path) -> None:
        from ipfs_datasets_py.knowledge_graphs import Client, GraphTarget

        catalog_path, storage_path = _paths(tmp_path)
        target = GraphTarget(tenant="acme", graph_id="txrb", branch="main")
        with Client.open(catalog_path, storage_path=storage_path) as client:
            assert client.create(target, idempotency_key="txrb-create").ok
            with pytest.raises(RuntimeError, match="boom"):
                with client.transaction(
                    target, idempotency_key="txrb-1", raise_on_error=True
                ) as tx:
                    tx.stage(
                        entities=[{"id": "x", "type": "T", "name": "nope"}]
                    )
                    raise RuntimeError("boom")
            assert tx.state == "rolled_back"
            q = client.query(target, params={"language": "scan"})
            assert q.ok
            assert q.result["row_count"] == 0

    def test_typed_errors_and_raise_for_status(self, tmp_path: Path) -> None:
        from ipfs_datasets_py.knowledge_graphs import (
            Client,
            GraphTarget,
            ServiceError,
            raise_for_status,
        )

        catalog_path, storage_path = _paths(tmp_path)
        with Client.open(catalog_path, storage_path=storage_path) as client:
            missing = client.open_graph(
                GraphTarget(tenant="acme", graph_id="missing", branch="main")
            )
            assert not missing.ok
            assert missing.error is not None
            assert missing.error.code in ("NOT_FOUND", "INVALID_TARGET")
            assert isinstance(missing.error.retryable, bool)
            with pytest.raises(ServiceError) as ei:
                raise_for_status(missing)
            assert ei.value.code == missing.error.code
            assert ei.value.to_json_dict()["code"] == missing.error.code

            # Invalid target validation surfaces as typed error / exception path.
            with pytest.raises(Exception):
                GraphTarget(tenant="", graph_id="x")


# ---------------------------------------------------------------------------
# Sync / async streaming
# ---------------------------------------------------------------------------


class TestStreaming:
    def _seed(self, tmp_path: Path, n: int = 5):
        from ipfs_datasets_py.knowledge_graphs import Client, GraphTarget

        catalog_path, storage_path = _paths(tmp_path)
        target = GraphTarget(tenant="acme", graph_id="stream", branch="main")
        client = Client.open(catalog_path, storage_path=storage_path)
        assert client.create(target, idempotency_key="stream-c").ok
        entities = [
            {"id": f"e{i}", "type": "Person", "name": f"n{i}"} for i in range(n)
        ]
        w = client.write(
            target, idempotency_key="stream-w", params={"entities": entities}
        )
        assert w.ok, w.to_json_dict()
        return client, target

    def test_sync_stream_query_and_rows(self, tmp_path: Path) -> None:
        client, target = self._seed(tmp_path, n=5)
        try:
            pages = list(
                client.stream_query(
                    target,
                    params={"language": "scan"},
                    page_size=2,
                )
            )
            assert len(pages) == 3  # 2+2+1
            assert pages[-1].exhausted
            total_rows = sum(p.row_count for p in pages)
            assert total_rows == 5
            for page in pages:
                json.dumps(page.to_json_dict(), allow_nan=False)

            rows = list(
                client.stream_rows(target, params={"language": "scan"})
            )
            assert len(rows) == 5
            names = {r[2] for r in rows}
            assert names == {f"n{i}" for i in range(5)}
        finally:
            client.close()

    def test_async_client_lifecycle_and_streaming(self, tmp_path: Path) -> None:
        from ipfs_datasets_py.knowledge_graphs import AsyncClient, GraphTarget

        catalog_path, storage_path = _paths(tmp_path)

        async def _run() -> None:
            async with await AsyncClient.open(
                catalog_path, storage_path=storage_path
            ) as client:
                assert client.api_version == "kg-python-client/v1"
                target = GraphTarget(
                    tenant="async", graph_id="g1", branch="main"
                )
                created = await client.create(
                    target, idempotency_key="async-create"
                )
                assert created.ok
                written = await client.write(
                    target,
                    idempotency_key="async-write",
                    params={
                        "entities": [
                            {"id": "a1", "type": "T", "name": "alpha"},
                            {"id": "a2", "type": "T", "name": "beta"},
                            {"id": "a3", "type": "T", "name": "gamma"},
                        ]
                    },
                )
                assert written.ok

                # Shared async handle sees same service.
                shared = client.share()
                try:
                    listed = await shared.list(
                        GraphTarget(tenant="async", graph_id="list")
                    )
                    assert listed.ok
                    assert any(
                        g["graph_id"] == "g1" for g in listed.result["graphs"]
                    )
                finally:
                    await shared.close()

                pages: List[Any] = []
                async for page in client.stream_query(
                    target,
                    params={"language": "scan"},
                    page_size=2,
                ):
                    pages.append(page)
                assert len(pages) == 2
                assert sum(p.row_count for p in pages) == 3

                names: List[str] = []
                async for row in client.stream_rows(
                    target, params={"language": "scan"}
                ):
                    names.append(row[2])
                assert set(names) == {"alpha", "beta", "gamma"}

                # Reopen snapshot after writes.
                opened = await client.open_graph(target)
                assert opened.ok
                assert opened.result["entity_count"] == 3

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# GraphTarget URI round-trip (exported type)
# ---------------------------------------------------------------------------


class TestGraphTargetExport:
    def test_uri_round_trip(self) -> None:
        from ipfs_datasets_py.knowledge_graphs import GraphTarget

        t = GraphTarget(tenant="acme", graph_id="skills", branch="main")
        assert t.uri == "kg://acme/skills/branches/main"
        back = GraphTarget.from_uri(t.uri)
        assert back.tenant == t.tenant
        assert back.graph_id == t.graph_id
        assert back.branch == t.branch
        assert back.revision is None
        payload = t.to_json_dict()
        json.dumps(payload, allow_nan=False)
        assert payload["uri"] == t.uri
