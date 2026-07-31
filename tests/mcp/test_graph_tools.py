"""MCP graph tools tests (KGP-019).

Acceptance coverage:
  * Every graph tool requires an explicit target
  * Canonical JSON-safe envelopes / typed errors
  * Transactions and cursors preserved across calls
  * Streaming and cancellation
  * MCP++ resource / effect metadata declared
  * Independent clients cannot observe another tenant without authorization
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from ipfs_datasets_py.mcp_server.graph_service_registry import (
    open_graph_service,
    reset_graph_service_registry,
)


@pytest.fixture
def kg_binding(tmp_path: Path):
    reset_graph_service_registry()
    catalog = tmp_path / "kg_catalog.sqlite"
    store = tmp_path / "kg_payloads"
    binding = open_graph_service(catalog, storage_path=store, force=True)
    try:
        yield binding, catalog, store
    finally:
        reset_graph_service_registry()


def _assert_json_safe(payload: Dict[str, Any]) -> None:
    raw = json.dumps(payload, allow_nan=False)
    assert isinstance(json.loads(raw), dict)


def _assert_lifecycle(payload: Dict[str, Any], *, op: str | None = None) -> None:
    assert "status" in payload
    assert "contract_version" in payload
    assert payload["contract_version"] == "kg-service-contract/v1"
    if op is not None:
        assert payload.get("operation") == op
    _assert_json_safe(payload)


# ---------------------------------------------------------------------------
# Explicit target required
# ---------------------------------------------------------------------------


class TestExplicitTargetRequired:
    @pytest.mark.asyncio
    async def test_create_without_target_errors(self, kg_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_create

        result = await graph_create()
        _assert_lifecycle(result, op="create")
        assert result["status"] == "error"
        assert result["error"]["code"] in {"INVALID_TARGET", "INVALID_REQUEST"}

    @pytest.mark.asyncio
    async def test_add_entity_without_target_errors(self, kg_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_add_entity

        result = await graph_add_entity(entity_id="e1", entity_type="Person")
        assert result["status"] == "error"
        assert result["error"]["code"] in {"INVALID_TARGET", "INVALID_REQUEST"}

    @pytest.mark.asyncio
    async def test_query_without_target_errors(self, kg_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_query_cypher

        result = await graph_query_cypher(query="MATCH (n) RETURN n")
        assert result["status"] == "error"
        assert result["error"]["code"] in {"INVALID_TARGET", "INVALID_REQUEST"}

    @pytest.mark.asyncio
    async def test_all_tools_declare_requires_explicit_target(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            GRAPH_TOOL_FUNCTIONS,
            iter_mcp_plus_metadata,
        )

        metas = dict(iter_mcp_plus_metadata())
        assert len(metas) == len(GRAPH_TOOL_FUNCTIONS)
        for name, meta in metas.items():
            assert meta.get("requires_explicit_target") is True, name
            assert meta.get("ability"), name
            assert meta.get("effects"), name
            assert meta.get("resource_template", "").startswith("kg://"), name


# ---------------------------------------------------------------------------
# Lifecycle via persistent service
# ---------------------------------------------------------------------------


class TestPersistentLifecycle:
    @pytest.mark.asyncio
    async def test_create_write_query_across_calls(self, kg_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_add_entity,
            graph_create,
            graph_query_cypher,
            graph_search_hybrid,
        )

        created = await graph_create(
            target="kg://acme/skills/branches/main",
            idempotency_key="mcp-c1",
        )
        _assert_lifecycle(created, op="create")
        assert created["status"] == "success"
        assert created["result"]["graph_id"] == "skills"
        assert created["result"]["revision"]
        assert created["target"]["uri"] == "kg://acme/skills/branches/main"

        written = await graph_add_entity(
            entity_id="e1",
            entity_type="Person",
            properties={"name": "Ada"},
            target="kg://acme/skills/branches/main",
            idempotency_key="mcp-w1",
        )
        _assert_lifecycle(written, op="write")
        assert written["status"] == "success"
        assert written["result"]["mutation_count"] == 1
        rev = written["result"]["revision"]

        # Independent tool call — same process service preserves state.
        scanned = await graph_search_hybrid(
            query="",
            target="kg://acme/skills/branches/main",
            language="scan",
            limit=10,
        )
        _assert_lifecycle(scanned, op="query")
        assert scanned["status"] == "success"
        assert scanned["result"]["row_count"] == 1
        assert scanned["result"]["revision"] == rev
        assert scanned["result"]["rows"][0][2] == "Ada"

        cypher = await graph_query_cypher(
            query="MATCH (n:Person) RETURN n",
            target="kg://acme/skills/branches/main",
            language="cypher",
        )
        assert cypher["status"] == "success"
        assert cypher["result"]["row_count"] >= 1
        _assert_json_safe(cypher)

    @pytest.mark.asyncio
    async def test_list_and_describe(self, kg_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_create,
            graph_describe,
            graph_list,
        )

        await graph_create(
            tenant="acme",
            graph_id="g1",
            branch="main",
            idempotency_key="list-c",
        )
        listed = await graph_list(tenant="acme")
        assert listed["status"] == "success"
        assert any(g["graph_id"] == "g1" for g in listed["result"]["graphs"])

        described = await graph_describe(tenant="acme", graph_id="g1", branch="main")
        assert described["status"] == "success"
        assert described["result"]["head_revision"]


# ---------------------------------------------------------------------------
# Transactions preserved across tool calls
# ---------------------------------------------------------------------------


class TestTransactionsAcrossCalls:
    @pytest.mark.asyncio
    async def test_begin_stage_commit(self, kg_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_add_entity,
            graph_create,
            graph_search_hybrid,
            graph_transaction_begin,
            graph_transaction_commit,
        )

        await graph_create(
            target="kg://acme/txg/branches/main",
            idempotency_key="tx-c",
        )
        begin = await graph_transaction_begin(
            target="kg://acme/txg/branches/main",
        )
        assert begin["status"] == "success", begin
        tx_id = begin["result"]["transaction_id"]
        assert tx_id

        staged = await graph_add_entity(
            entity_id="t1",
            entity_type="Thing",
            properties={"name": "staged"},
            target="kg://acme/txg/branches/main",
            transaction_id=tx_id,
            idempotency_key="tx-stage",
        )
        assert staged["status"] == "success", staged
        assert staged["result"].get("staged") is True

        # Before commit the durable head must not include the staged entity.
        pre = await graph_search_hybrid(
            query="",
            target="kg://acme/txg/branches/main",
            language="scan",
        )
        assert pre["status"] == "success"
        assert pre["result"]["row_count"] == 0

        committed = await graph_transaction_commit(
            transaction_id=tx_id,
            target="kg://acme/txg/branches/main",
            idempotency_key="tx-commit",
        )
        assert committed["status"] == "success", committed
        assert committed["result"]["state"] in {"committed", "open"} or committed[
            "result"
        ].get("revision")

        post = await graph_search_hybrid(
            query="",
            target="kg://acme/txg/branches/main",
            language="scan",
        )
        assert post["status"] == "success"
        assert post["result"]["row_count"] == 1
        assert post["result"]["rows"][0][2] == "staged"

    @pytest.mark.asyncio
    async def test_begin_rollback(self, kg_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_add_entity,
            graph_create,
            graph_search_hybrid,
            graph_transaction_begin,
            graph_transaction_rollback,
        )

        await graph_create(
            target="kg://acme/txrb/branches/main",
            idempotency_key="txrb-c",
        )
        begin = await graph_transaction_begin(target="kg://acme/txrb/branches/main")
        tx_id = begin["result"]["transaction_id"]
        await graph_add_entity(
            entity_id="x",
            entity_type="T",
            properties={"name": "nope"},
            target="kg://acme/txrb/branches/main",
            transaction_id=tx_id,
            idempotency_key="txrb-stage",
        )
        rb = await graph_transaction_rollback(
            transaction_id=tx_id,
            target="kg://acme/txrb/branches/main",
        )
        assert rb["status"] == "success", rb
        post = await graph_search_hybrid(
            query="",
            target="kg://acme/txrb/branches/main",
            language="scan",
        )
        assert post["result"]["row_count"] == 0


# ---------------------------------------------------------------------------
# Streaming + cancellation + cursors
# ---------------------------------------------------------------------------


class TestStreamingAndCancellation:
    @pytest.mark.asyncio
    async def test_stream_pages_and_cursor_resume(self, kg_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_create,
            graph_query_stream,
            graph_write,
        )

        await graph_create(
            target="kg://acme/stream/branches/main",
            idempotency_key="stream-c",
        )
        entities = [
            {"id": f"e{i}", "type": "Person", "name": f"n{i}"} for i in range(5)
        ]
        w = await graph_write(
            target="kg://acme/stream/branches/main",
            entities=entities,
            idempotency_key="stream-w",
        )
        assert w["status"] == "success", w

        page1 = await graph_query_stream(
            target="kg://acme/stream/branches/main",
            language="scan",
            page_size=2,
        )
        assert page1["status"] == "success", page1
        assert page1["result"]["row_count"] == 2
        assert page1["result"]["streaming"] is True
        cursor = page1["result"]["cursor"]
        assert cursor
        assert page1["result"]["exhausted"] is False

        page2 = await graph_query_stream(
            target="kg://acme/stream/branches/main",
            cursor=cursor,
            page_size=2,
        )
        assert page2["status"] == "success", page2
        assert page2["result"]["row_count"] == 2
        cursor2 = page2["result"]["cursor"]

        page3 = await graph_query_stream(
            target="kg://acme/stream/branches/main",
            cursor=cursor2,
            page_size=2,
        )
        assert page3["status"] == "success", page3
        assert page3["result"]["row_count"] == 1
        assert page3["result"]["exhausted"] is True
        assert page3["result"]["cursor"] is None
        total = (
            page1["result"]["row_count"]
            + page2["result"]["row_count"]
            + page3["result"]["row_count"]
        )
        assert total == 5

    @pytest.mark.asyncio
    async def test_stream_cancel(self, kg_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_create,
            graph_query_stream,
            graph_stream_cancel,
            graph_write,
        )

        await graph_create(
            target="kg://acme/cancel/branches/main",
            idempotency_key="cancel-c",
        )
        await graph_write(
            target="kg://acme/cancel/branches/main",
            entities=[{"id": f"e{i}", "type": "T", "name": f"n{i}"} for i in range(4)],
            idempotency_key="cancel-w",
        )
        page1 = await graph_query_stream(
            target="kg://acme/cancel/branches/main",
            language="scan",
            page_size=1,
        )
        cursor = page1["result"]["cursor"]
        assert cursor

        cancelled = await graph_stream_cancel(
            cursor=cursor,
            target="kg://acme/cancel/branches/main",
            reason="test-cancel",
        )
        assert cancelled["status"] == "success"
        assert cancelled["result"]["cancelled"] is True

        resume = await graph_query_stream(
            target="kg://acme/cancel/branches/main",
            cursor=cursor,
        )
        assert resume["status"] == "error"
        assert resume["error"]["code"] in {"BUDGET_EXCEEDED", "NOT_FOUND"}


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_cross_tenant_forbidden_with_scoped_auth(self, kg_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_create,
            graph_list,
            graph_search_hybrid,
            graph_write,
        )

        await graph_create(
            target="kg://tenant-a/private/branches/main",
            idempotency_key="iso-a-c",
        )
        await graph_write(
            target="kg://tenant-a/private/branches/main",
            entities=[{"id": "secret", "type": "Secret", "name": "classified"}],
            idempotency_key="iso-a-w",
        )
        await graph_create(
            target="kg://tenant-b/public/branches/main",
            idempotency_key="iso-b-c",
        )

        # Client bound to tenant-b must not read tenant-a.
        denied = await graph_search_hybrid(
            query="",
            target="kg://tenant-a/private/branches/main",
            language="scan",
            auth={
                "principal": "client-b",
                "tenant": "tenant-b",
                "abilities": ["graph/query", "graph/list", "graph/read"],
            },
        )
        assert denied["status"] == "error"
        assert denied["error"]["code"] == "FORBIDDEN"

        # Same client can list its own tenant.
        listed = await graph_list(
            tenant="tenant-b",
            auth={
                "principal": "client-b",
                "tenant": "tenant-b",
                "abilities": ["graph/list"],
            },
        )
        assert listed["status"] == "success"
        assert all(g["graph_id"] != "private" for g in listed["result"]["graphs"])

        # tenant-a principal can read its graph.
        allowed = await graph_search_hybrid(
            query="",
            target="kg://tenant-a/private/branches/main",
            language="scan",
            auth={
                "principal": "client-a",
                "tenant": "tenant-a",
                "abilities": ["graph/query"],
            },
        )
        assert allowed["status"] == "success"
        assert allowed["result"]["row_count"] == 1

    @pytest.mark.asyncio
    async def test_cursor_cannot_cross_tenant(self, kg_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_create,
            graph_query_stream,
            graph_write,
        )

        await graph_create(
            target="kg://tenant-a/s1/branches/main",
            idempotency_key="cur-a-c",
        )
        await graph_write(
            target="kg://tenant-a/s1/branches/main",
            entities=[{"id": f"e{i}", "type": "T", "name": f"n{i}"} for i in range(3)],
            idempotency_key="cur-a-w",
        )
        page = await graph_query_stream(
            target="kg://tenant-a/s1/branches/main",
            language="scan",
            page_size=1,
            auth={"principal": "a", "tenant": "tenant-a"},
        )
        cursor = page["result"]["cursor"]
        assert cursor

        # Attempt resume under a different tenant target.
        hijack = await graph_query_stream(
            target="kg://tenant-b/other/branches/main",
            cursor=cursor,
            auth={"principal": "b", "tenant": "tenant-b"},
        )
        assert hijack["status"] == "error"
        assert hijack["error"]["code"] in {"FORBIDDEN", "NOT_FOUND", "INVALID_TARGET"}


# ---------------------------------------------------------------------------
# MCP++ metadata
# ---------------------------------------------------------------------------


class TestMcpPlusMetadata:
    def test_every_tool_has_resource_and_effects(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            GRAPH_TOOL_FUNCTIONS,
            iter_mcp_plus_metadata,
        )

        for fn in GRAPH_TOOL_FUNCTIONS:
            assert hasattr(fn, "_mcp_plus")
            assert hasattr(fn, "_mcp_plus_ability")
            assert hasattr(fn, "_mcp_plus_effects")
            assert hasattr(fn, "_mcp_plus_resource")
            assert fn._mcp_plus_resource.startswith("kg://")  # type: ignore[attr-defined]
            assert len(fn._mcp_plus_effects) >= 1  # type: ignore[attr-defined]

        stream_meta = dict(iter_mcp_plus_metadata())["graph_query_stream"]
        assert stream_meta["streaming"] is True
        assert stream_meta["cancellable"] is True

        cancel_meta = dict(iter_mcp_plus_metadata())["graph_stream_cancel"]
        assert "graph.cancel" in cancel_meta["effects"]

    def test_service_registry_shared_instance(self, kg_binding) -> None:
        binding, _, _ = kg_binding
        from ipfs_datasets_py.mcp_server.graph_service_registry import (
            get_graph_service,
        )

        svc = get_graph_service()
        assert svc is binding.service
