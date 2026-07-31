"""MCP / MCP++ graph surface conformance (KGP-019).

Routes every MCP graph tool through a persistent, server-owned GraphService.
Strict assertions — no permissive success-or-failure checks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from ipfs_datasets_py.mcp_server.graph_service_registry import (
    open_graph_service,
    reset_graph_service_registry,
)


@pytest.fixture
def mcp_service(tmp_path: Path):
    reset_graph_service_registry()
    catalog = tmp_path / "conformance_catalog.sqlite"
    store = tmp_path / "conformance_payloads"
    binding = open_graph_service(catalog, storage_path=store, force=True)
    try:
        yield binding
    finally:
        reset_graph_service_registry()


def _json_safe(payload: Dict[str, Any]) -> None:
    json.dumps(payload, allow_nan=False)


def _ok(payload: Dict[str, Any], *, op: str) -> Dict[str, Any]:
    assert payload["status"] == "success", payload
    assert payload["operation"] == op
    assert payload["contract_version"] == "kg-service-contract/v1"
    _json_safe(payload)
    return payload


class TestMcpSurfaceParity:
    @pytest.mark.asyncio
    async def test_create_write_query_reopen_vector(self, mcp_service) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_add_entity,
            graph_add_relationship,
            graph_create,
            graph_describe,
            graph_list,
            graph_query_cypher,
            graph_search_hybrid,
            graph_write,
            query_knowledge_graph,
        )

        created = await graph_create(
            target="kg://acme/skills/branches/main",
            idempotency_key="conf-create",
            storage_profile="parquet",
        )
        _ok(created, op="create")
        assert created["result"]["graph_id"] == "skills"
        assert created["result"]["uri"] in {
            "kg://acme/skills",
            "kg://acme/skills/branches/main",
        }
        assert created["target"]["tenant"] == "acme"
        assert created["target"]["uri"] == "kg://acme/skills/branches/main"

        w1 = await graph_add_entity(
            entity_id="ada",
            entity_type="Person",
            properties={"name": "Ada"},
            target="kg://acme/skills/branches/main",
            idempotency_key="conf-e1",
        )
        _ok(w1, op="write")

        w2 = await graph_add_entity(
            entity_id="grace",
            entity_type="Person",
            properties={"name": "Grace"},
            target="kg://acme/skills/branches/main",
            idempotency_key="conf-e2",
        )
        _ok(w2, op="write")

        rel = await graph_add_relationship(
            source_id="ada",
            target_id="grace",
            relationship_type="KNOWS",
            target="kg://acme/skills/branches/main",
            idempotency_key="conf-rel",
        )
        _ok(rel, op="write")

        listed = await graph_list(tenant="acme")
        _ok(listed, op="list")
        assert any(g["graph_id"] == "skills" for g in listed["result"]["graphs"])

        described = await graph_describe(tenant="acme", graph_id="skills")
        _ok(described, op="describe")
        head = described["result"]["head_revision"]
        assert head

        scanned = await graph_search_hybrid(
            query="",
            target="kg://acme/skills/branches/main",
            language="scan",
            limit=50,
        )
        _ok(scanned, op="query")
        assert scanned["result"]["envelope_version"] == "kg-query-envelope/v1"
        assert scanned["result"]["row_count"] == 2
        names = {row[2] for row in scanned["result"]["rows"]}
        assert names == {"Ada", "Grace"}

        cypher = await graph_query_cypher(
            query="MATCH (n:Person) RETURN n",
            target="kg://acme/skills/branches/main",
        )
        _ok(cypher, op="query")
        assert cypher["result"]["row_count"] >= 1
        # Result must be pure JSON (no neo4j Result objects).
        _json_safe(cypher)

        qkg = await query_knowledge_graph(
            target="kg://acme/skills/branches/main",
            query="",
            query_type="scan",
            max_results=50,
        )
        _ok(qkg, op="query")
        assert qkg["result"]["row_count"] == 2

        # Bulk write still works on the same shared service.
        bulk = await graph_write(
            target="kg://acme/skills/branches/main",
            entities=[{"id": "linus", "type": "Person", "name": "Linus"}],
            idempotency_key="conf-bulk",
        )
        _ok(bulk, op="write")
        assert bulk["result"]["mutation_count"] == 1

        final = await graph_search_hybrid(
            query="",
            target="kg://acme/skills/branches/main",
            language="scan",
        )
        _ok(final, op="query")
        assert final["result"]["row_count"] == 3

    @pytest.mark.asyncio
    async def test_transaction_survives_independent_tool_calls(
        self, mcp_service
    ) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_create,
            graph_search_hybrid,
            graph_transaction_begin,
            graph_transaction_commit,
            graph_write,
        )

        await graph_create(
            target="kg://acme/tx/branches/main",
            idempotency_key="conf-tx-c",
        )
        begin = await graph_transaction_begin(target="kg://acme/tx/branches/main")
        _ok(begin, op="begin_tx")
        tx_id = begin["result"]["transaction_id"]

        staged = await graph_write(
            target="kg://acme/tx/branches/main",
            entities=[{"id": "s1", "type": "Thing", "name": "held"}],
            transaction_id=tx_id,
            idempotency_key="conf-tx-stage",
        )
        _ok(staged, op="write")
        assert staged["result"]["staged"] is True

        pre = await graph_search_hybrid(
            query="",
            target="kg://acme/tx/branches/main",
            language="scan",
        )
        _ok(pre, op="query")
        assert pre["result"]["row_count"] == 0

        commit = await graph_transaction_commit(
            transaction_id=tx_id,
            target="kg://acme/tx/branches/main",
            idempotency_key="conf-tx-commit",
        )
        _ok(commit, op="commit_tx")

        post = await graph_search_hybrid(
            query="",
            target="kg://acme/tx/branches/main",
            language="scan",
        )
        _ok(post, op="query")
        assert post["result"]["row_count"] == 1
        assert post["result"]["rows"][0][2] == "held"

    @pytest.mark.asyncio
    async def test_streaming_cursor_and_cancel(self, mcp_service) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_create,
            graph_query_stream,
            graph_stream_cancel,
            graph_write,
        )

        await graph_create(
            target="kg://acme/stream/branches/main",
            idempotency_key="conf-stream-c",
        )
        await graph_write(
            target="kg://acme/stream/branches/main",
            entities=[
                {"id": f"e{i}", "type": "Person", "name": f"n{i}"} for i in range(6)
            ],
            idempotency_key="conf-stream-w",
        )

        pages: List[Dict[str, Any]] = []
        cursor = None
        for _ in range(10):
            page = await graph_query_stream(
                target="kg://acme/stream/branches/main",
                language="scan",
                page_size=2,
                cursor=cursor,
            )
            _ok(page, op="query")
            pages.append(page)
            cursor = page["result"].get("cursor")
            if page["result"]["exhausted"]:
                break
        assert sum(p["result"]["row_count"] for p in pages) == 6
        assert pages[-1]["result"]["exhausted"] is True

        # Fresh stream then cancel mid-way.
        first = await graph_query_stream(
            target="kg://acme/stream/branches/main",
            language="scan",
            page_size=2,
        )
        _ok(first, op="query")
        cur = first["result"]["cursor"]
        assert cur
        cancelled = await graph_stream_cancel(
            cursor=cur,
            target="kg://acme/stream/branches/main",
        )
        _ok(cancelled, op="query")
        assert cancelled["result"]["cancelled"] is True
        blocked = await graph_query_stream(
            target="kg://acme/stream/branches/main",
            cursor=cur,
        )
        assert blocked["status"] == "error"
        assert blocked["error"]["code"] in {"BUDGET_EXCEEDED", "NOT_FOUND"}

    @pytest.mark.asyncio
    async def test_tenant_isolation_between_clients(self, mcp_service) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_create,
            graph_list,
            graph_search_hybrid,
            graph_write,
        )

        await graph_create(
            target="kg://tenant-a/private/branches/main",
            idempotency_key="iso-c-a",
        )
        await graph_write(
            target="kg://tenant-a/private/branches/main",
            entities=[{"id": "s", "type": "Secret", "name": "hidden"}],
            idempotency_key="iso-w-a",
        )
        await graph_create(
            target="kg://tenant-b/open/branches/main",
            idempotency_key="iso-c-b",
        )

        denied = await graph_search_hybrid(
            query="",
            target="kg://tenant-a/private/branches/main",
            language="scan",
            auth={
                "principal": "b-client",
                "tenant": "tenant-b",
                "abilities": ["graph/query", "graph/read", "graph/list"],
            },
        )
        assert denied["status"] == "error"
        assert denied["error"]["code"] == "FORBIDDEN"
        _json_safe(denied)

        # Ability denial
        no_query = await graph_search_hybrid(
            query="",
            target="kg://tenant-b/open/branches/main",
            language="scan",
            auth={
                "principal": "b-client",
                "tenant": "tenant-b",
                "abilities": ["graph/list"],  # no graph/query
            },
        )
        assert no_query["status"] == "error"
        assert no_query["error"]["code"] == "FORBIDDEN"

        own = await graph_list(
            tenant="tenant-b",
            auth={
                "principal": "b-client",
                "tenant": "tenant-b",
                "abilities": ["graph/list"],
            },
        )
        _ok(own, op="list")
        ids = {g["graph_id"] for g in own["result"]["graphs"]}
        assert "private" not in ids
        assert "open" in ids

    @pytest.mark.asyncio
    async def test_missing_target_and_typed_errors(self, mcp_service) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_create,
            graph_query_cypher,
            graph_write,
        )

        missing = await graph_create()
        assert missing["status"] == "error"
        assert missing["error"]["code"] in {"INVALID_TARGET", "INVALID_REQUEST"}
        assert isinstance(missing["error"]["retryable"], bool)
        _json_safe(missing)

        bad_slug = await graph_create(
            tenant="ACME",  # uppercase invalid
            graph_id="x",
            branch="main",
        )
        assert bad_slug["status"] == "error"
        assert bad_slug["error"]["code"] == "INVALID_TARGET"

        # Write without create → NOT_FOUND or similar typed error.
        orphan = await graph_write(
            target="kg://acme/missing/branches/main",
            entities=[{"id": "e", "type": "T", "name": "n"}],
            idempotency_key="orphan-w",
        )
        assert orphan["status"] == "error"
        assert orphan["error"]["code"] in {
            "NOT_FOUND",
            "INVALID_TARGET",
            "STORAGE",
            "INVALID_REQUEST",
        }

        # Query without target.
        q = await graph_query_cypher(query="MATCH (n) RETURN n")
        assert q["status"] == "error"
        assert q["error"]["code"] in {"INVALID_TARGET", "INVALID_REQUEST"}

    def test_mcp_plus_metadata_complete(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            GRAPH_TOOL_FUNCTIONS,
            iter_mcp_plus_metadata,
        )

        metas = dict(iter_mcp_plus_metadata())
        assert len(metas) == len(GRAPH_TOOL_FUNCTIONS)
        for name, meta in metas.items():
            assert meta["mcp_plus_version"] == "kg-mcp-plus/v1"
            assert meta["requires_explicit_target"] is True
            assert meta["ability"].startswith("graph/")
            assert meta["effects"]
            assert "kg://" in meta["resource_template"]
            assert meta["contract_version"] == "kg-service-contract/v1"

    def test_no_fresh_manager_per_call(self, mcp_service) -> None:
        """Independent tool resolutions share the same GraphService instance."""
        from ipfs_datasets_py.mcp_server.graph_service_registry import (
            get_graph_service,
        )
        from ipfs_datasets_py.mcp_server.tools.graph_tools._bridge import (
            resolve_binding,
        )

        b1, e1 = resolve_binding(operation="create")
        b2, e2 = resolve_binding(operation="query")
        assert e1 is None and e2 is None
        assert b1 is not None and b2 is not None
        assert b1.service is b2.service
        assert b1.service is get_graph_service()
        assert b1.service is mcp_service.service
