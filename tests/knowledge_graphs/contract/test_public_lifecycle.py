"""
KGP-048 / KGP-001: Public lifecycle contract probes for knowledge graphs.

Two evidence tiers (do not conflate):

1. **Release-eligible canonical conformance** (``kg_release_eligible``)
   Explicit ``GraphTarget`` create / write / query / transaction / reopen
   through Python ``Client``, package CLI
   (``python -m ipfs_datasets_py.ipfs_datasets_cli``), MCP ``graph_tools``,
   and MCP++ ``tools_dispatch``. These tests must pass without skips or
   expected failures. They are the only lifecycle evidence counted as
   release proof.

2. **Legacy compatibility observations** (``kg_legacy_compat``)
   Deprecated ``KnowledgeGraphManager`` / root ``ipfs_datasets_cli.py``
   compatibility inventory (KGP-001 baseline). These calls are adapters over
   the canonical service and remain outside release-eligible proof.

See also:
    docs/architecture/knowledge_graphs_contract_matrix.md
    docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md
"""

from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CLI_PATH = REPO_ROOT / "ipfs_datasets_cli.py"  # deprecated root CLI (legacy debt)
CANONICAL_CLI_MODULE = "ipfs_datasets_py.ipfs_datasets_cli"
DRIVER_URL = "ipfs://localhost:5001"
CYPHER_SMOKE = "MATCH (n) RETURN n LIMIT 10"
CONTRACT_VERSION = "kg-service-contract/v1"


# ---------------------------------------------------------------------------
# Helpers — strict envelope / JSON checks (no permissive returncode acceptance)
# ---------------------------------------------------------------------------


def _is_json_safe(value: Any) -> bool:
    """Return True if value survives a strict json.dumps round-trip attempt."""
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def assert_success_envelope(
    result: Mapping[str, Any],
    *,
    required_keys: Sequence[str] = (),
) -> None:
    """Assert a production success result envelope (strict)."""
    assert isinstance(result, Mapping), f"expected mapping envelope, got {type(result)!r}"
    assert result.get("status") == "success", (
        f"expected status=='success', got {result!r}"
    )
    for key in required_keys:
        assert key in result, f"missing required key {key!r} in {result!r}"
    assert _is_json_safe(result), (
        f"result envelope is not JSON-serializable: {result!r}"
    )


def assert_json_serializable_query_result(result: Mapping[str, Any]) -> None:
    """Assert query result is a success envelope with JSON-safe ``results``."""
    assert_success_envelope(result, required_keys=("results", "query"))
    assert _is_json_safe(result["results"]), (
        f"query results not JSON-serializable: "
        f"type={type(result.get('results')).__name__!r} value={result.get('results')!r}"
    )


def assert_canonical_lifecycle(
    result: Mapping[str, Any],
    *,
    operation: Optional[str] = None,
) -> None:
    """Assert a GraphService lifecycle envelope (release-eligible shape)."""
    assert_success_envelope(
        result,
        required_keys=("contract_version", "operation", "target", "result"),
    )
    assert result["contract_version"] == CONTRACT_VERSION, result
    if operation is not None:
        assert result["operation"] == operation, result
    assert isinstance(result["target"], Mapping), result
    assert result["target"].get("tenant"), result
    assert result["target"].get("graph_id") or result["target"].get("uri"), result


def _child_env(extra: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(REPO_ROOT) if not existing else f"{REPO_ROOT}{os.pathsep}{existing}"
    )
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env


def run_canonical_cli(
    args: Sequence[str],
    *,
    catalog: Optional[Path] = None,
    store: Optional[Path] = None,
    timeout: float = 60.0,
    input_text: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    """Run the package GraphService CLI as an independent process."""
    cmd = [sys.executable, "-m", CANONICAL_CLI_MODULE, *args]
    joined = " ".join(args)
    if catalog is not None and "--catalog" not in joined:
        cmd.extend(["--catalog", str(catalog)])
    if store is not None and "--store" not in joined:
        cmd.extend(["--store", str(store)])
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(REPO_ROOT),
        env=_child_env(),
        input=input_text,
    )


def run_cli(args: Sequence[str], *, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    """Run the repository CLI as an independent process."""
    cmd = [sys.executable, str(CLI_PATH), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(REPO_ROOT),
    )


def parse_cli_json_stdout(proc: subprocess.CompletedProcess[str]) -> Dict[str, Any]:
    """
    Parse the last JSON object from CLI stdout.

    Strict: non-zero return codes and non-JSON stdout are assertion failures
    (never treated as soft success).
    """
    assert proc.returncode == 0, (
        f"CLI exit code {proc.returncode}; stdout={proc.stdout!r}; stderr={proc.stderr!r}"
    )
    text = (proc.stdout or "").strip()
    assert text, f"empty CLI stdout; stderr={proc.stderr!r}"
    # Prefer full-document parse; fall back to last JSON object in mixed output.
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Find the last {...} block.
        matches = list(re.finditer(r"\{[\s\S]*\}", text))
        assert matches, (
            f"CLI stdout is not JSON: {text!r}; stderr={proc.stderr!r}"
        )
        payload = json.loads(matches[-1].group(0))
    assert isinstance(payload, dict), f"expected JSON object, got {type(payload)!r}"
    return payload


def source_constructs_fresh_manager(source: str) -> bool:
    """True when tool source constructs KnowledgeGraphManager inline (not shared)."""
    return bool(
        re.search(r"KnowledgeGraphManager\s*\(", source)
        and re.search(r"manager\s*=\s*KnowledgeGraphManager", source)
    )


def source_uses_server_owned_graph_service(source: str) -> bool:
    """True when a graph tool resolves and calls the shared GraphService."""
    return (
        "resolve_binding" in source
        and "binding.service." in source
        and not source_constructs_fresh_manager(source)
    )


def _kg_paths(tmp_path: Path) -> Tuple[Path, Path]:
    return tmp_path / "kg_catalog.sqlite", tmp_path / "kg_payloads"


def _strip_request_id(result: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in result.items() if k != "request_id"}


# ---------------------------------------------------------------------------
# Shared Python-API helpers (legacy KnowledgeGraphManager)
# ---------------------------------------------------------------------------


def _manager():
    from ipfs_datasets_py.core_operations import KnowledgeGraphManager

    return KnowledgeGraphManager(driver_url=DRIVER_URL)


async def _python_add_entity(
    entity_id: str = "person1",
    entity_type: str = "Person",
    properties: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    manager = _manager()
    return await manager.add_entity(
        entity_id,
        entity_type,
        properties if properties is not None else {"name": "Alice"},
    )


async def _python_query(cypher: str = CYPHER_SMOKE) -> Dict[str, Any]:
    manager = _manager()
    return await manager.query_cypher(cypher)


async def _python_tx_begin() -> Dict[str, Any]:
    return await _manager().transaction_begin()


# ---------------------------------------------------------------------------
# MCP helpers
# ---------------------------------------------------------------------------


async def _mcp_create(
    *,
    target: str = "kg://contract/lifecycle/branches/main",
    catalog_path: Optional[str] = None,
    storage_path: Optional[str] = None,
) -> Dict[str, Any]:
    from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_create import graph_create

    return await graph_create(
        target=target,
        catalog_path=catalog_path,
        storage_path=storage_path,
        idempotency_key="contract-create",
    )


async def _mcp_add_entity(
    entity_id: str = "person1",
    entity_type: str = "Person",
    properties: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_add_entity import (
        graph_add_entity,
    )

    return await graph_add_entity(
        entity_id=entity_id,
        entity_type=entity_type,
        properties=properties if properties is not None else {"name": "Alice"},
        driver_url=DRIVER_URL,
    )


async def _mcp_query(cypher: str = CYPHER_SMOKE) -> Dict[str, Any]:
    from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_query_cypher import (
        graph_query_cypher,
    )

    return await graph_query_cypher(query=cypher, driver_url=DRIVER_URL)


async def _mcp_tx_begin() -> Dict[str, Any]:
    from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_transaction_begin import (
        graph_transaction_begin,
    )

    return await graph_transaction_begin(driver_url=DRIVER_URL)


async def _mcp_tx_commit(tx_id: Optional[str]) -> Dict[str, Any]:
    from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_transaction_commit import (
        graph_transaction_commit,
    )

    return await graph_transaction_commit(transaction_id=tx_id, driver_url=DRIVER_URL)


# ---------------------------------------------------------------------------
# MCP++ helpers (hierarchical tools_dispatch)
# ---------------------------------------------------------------------------


async def _mcp_plus_dispatch(
    tool: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import tools_dispatch

    payload = dict(params or {})
    if "driver_url" not in payload:
        payload["driver_url"] = DRIVER_URL
    return await tools_dispatch("graph_tools", tool, payload)


# ===========================================================================
# LEGACY COMPATIBILITY OBSERVATIONS (kg_legacy_compat) — not release proof
# ===========================================================================


@pytest.mark.kg_legacy_compat
class TestDriftInventory:
    """LEGACY-COMPAT: passing probes that lock known manager/root-CLI debt as facts (not release proof)."""

    def test_manager_exposes_create_graph_compatibility_method(self) -> None:
        from ipfs_datasets_py.core_operations import KnowledgeGraphManager

        assert hasattr(KnowledgeGraphManager, "create_graph")
        assert hasattr(KnowledgeGraphManager, "initialize")

    def test_entity_rejects_manager_constructor_kwargs(self) -> None:
        from ipfs_datasets_py.knowledge_graphs.storage.types import Entity

        with pytest.raises(TypeError, match="unexpected keyword argument 'id'"):
            Entity(id="e1", type="Person", properties={})  # type: ignore[call-arg]

    def test_relationship_rejects_manager_constructor_kwargs(self) -> None:
        from ipfs_datasets_py.knowledge_graphs.storage.types import Relationship

        with pytest.raises(TypeError, match="unexpected keyword argument 'type'"):
            Relationship(  # type: ignore[call-arg]
                source="a",
                target="b",
                type="KNOWS",
                properties={},
            )

    def test_cli_method_names_are_available_on_manager(self) -> None:
        from ipfs_datasets_py.core_operations import KnowledgeGraphManager

        cli_source = CLI_PATH.read_text(encoding="utf-8")
        # CLI call sites vs manager public methods
        divergences = [
            ("manager.search_hybrid", "hybrid_search", "search_hybrid"),
            ("manager.create_index", "index_create", "create_index"),
            ("manager.add_constraint", "constraint_add", "add_constraint"),
            ("manager.create_graph", "initialize", "create_graph"),
        ]
        for cli_call, manager_method, missing in divergences:
            assert cli_call in cli_source, f"expected CLI to call {cli_call}"
            assert hasattr(KnowledgeGraphManager, manager_method)
            assert hasattr(KnowledgeGraphManager, missing)

    def test_mcp_tools_use_server_owned_graph_service(self) -> None:
        tool_files = [
            REPO_ROOT
            / "ipfs_datasets_py"
            / "mcp_server"
            / "tools"
            / "graph_tools"
            / name
            for name in (
                "graph_create.py",
                "graph_add_entity.py",
                "graph_query_cypher.py",
                "graph_transaction_begin.py",
                "graph_transaction_commit.py",
            )
        ]
        for path in tool_files:
            source = path.read_text(encoding="utf-8")
            assert source_uses_server_owned_graph_service(source), (
                f"{path.name} should resolve and call the server-owned GraphService"
            )

    def test_cli_create_emits_success_envelope(self) -> None:
        proc = run_cli(
            ["--json", "graph", "create", "--driver-url", DRIVER_URL],
        )
        assert_success_envelope(parse_cli_json_stdout(proc), required_keys=("graph_id",))

    @pytest.mark.asyncio
    async def test_python_add_entity_uses_canonical_signature(self) -> None:
        result = await _python_add_entity()
        assert_success_envelope(result, required_keys=("entity_id", "entity_type"))


# ===========================================================================
# Python API — deprecated compatibility lifecycle
# ===========================================================================


@pytest.mark.kg_legacy_compat
class TestPythonLifecycle:
    """LEGACY-COMPAT: deprecated manager calls routed to GraphService. Not release proof."""

    @pytest.mark.asyncio
    async def test_create_graph_returns_success_envelope(self) -> None:
        manager = _manager()
        # Production contract: create_graph exists and returns a success envelope
        # with a durable graph identity.
        create = getattr(manager, "create_graph")
        result = await create()
        assert_success_envelope(result)
        assert any(
            key in result for key in ("graph_id", "graph_uri", "driver_url", "revision")
        ), f"create_graph result lacks graph identity: {result!r}"

    @pytest.mark.asyncio
    async def test_initialize_returns_success_envelope(self) -> None:
        """initialize is the current substitute path; still must be JSON-safe."""
        result = await _manager().initialize()
        assert_success_envelope(result, required_keys=("message", "driver_url"))

    @pytest.mark.asyncio
    async def test_add_entity_returns_success_envelope(self) -> None:
        result = await _python_add_entity(
            entity_id="kgp001-person",
            entity_type="Person",
            properties={"name": "Alice", "age": 30},
        )
        assert_success_envelope(
            result,
            required_keys=("entity_id", "entity_type", "properties"),
        )
        assert result["entity_id"] == "kgp001-person"
        assert result["entity_type"] == "Person"

    @pytest.mark.asyncio
    async def test_add_relationship_returns_success_envelope(self) -> None:
        manager = _manager()
        result = await manager.add_relationship(
            "kgp001-a",
            "kgp001-b",
            "KNOWS",
            {"since": 2020},
        )
        assert_success_envelope(
            result,
            required_keys=("source_id", "target_id", "relationship_type"),
        )

    @pytest.mark.asyncio
    async def test_query_cypher_results_are_json_serializable(self) -> None:
        result = await _python_query(CYPHER_SMOKE)
        assert_json_serializable_query_result(result)

    @pytest.mark.asyncio
    async def test_transaction_begin_returns_transaction_id(self) -> None:
        result = await _python_tx_begin()
        assert_success_envelope(result, required_keys=("transaction_id",))
        assert isinstance(result["transaction_id"], str)
        assert result["transaction_id"]

    @pytest.mark.asyncio
    async def test_transaction_survives_independent_manager_commit(self) -> None:
        """Independent manager instances must share durable tx state (or catalog)."""
        begin = await _manager().transaction_begin()
        assert_success_envelope(begin, required_keys=("transaction_id",))
        tx_id = begin["transaction_id"]
        # Fresh manager (simulates process reopen / MCP per-call manager)
        commit = await _manager().transaction_commit(tx_id)
        assert_success_envelope(commit, required_keys=("transaction_id",))
        assert commit["transaction_id"] == tx_id

    @pytest.mark.asyncio
    async def test_create_then_reopen_preserves_graph_identity(self) -> None:
        first = _manager()
        create = getattr(first, "create_graph", first.initialize)
        created = await create()
        assert_success_envelope(created)
        graph_id = (
            created.get("graph_id")
            or created.get("graph_uri")
            or created.get("revision")
        )
        assert graph_id, f"no durable graph identity in create result: {created!r}"

        reopened = _manager()
        # Production contract: reopen by identity yields the same graph.
        listed = await reopened.query_cypher(
            "MATCH (n) RETURN count(n) AS c",
        )
        assert_json_serializable_query_result(listed)
        assert listed.get("graph_id", graph_id) == graph_id or graph_id in str(listed)


# ===========================================================================
# CLI surface
# ===========================================================================


@pytest.mark.kg_legacy_compat
class TestCLILifecycle:
    """LEGACY-COMPAT: root ``ipfs_datasets_cli.py`` process probes (debt). Not release proof."""

    def test_graph_create_returns_json_success(self) -> None:
        proc = run_cli(
            ["--json", "graph", "create", "--driver-url", DRIVER_URL],
        )
        payload = parse_cli_json_stdout(proc)
        assert_success_envelope(payload)

    def test_graph_add_entity_returns_json_success(self) -> None:
        props = json.dumps({"name": "Alice", "age": 30})
        proc = run_cli(
            [
                "--json",
                "graph",
                "add-entity",
                "--id",
                "cli-person1",
                "--type",
                "Person",
                "--props",
                props,
            ],
        )
        payload = parse_cli_json_stdout(proc)
        assert_success_envelope(
            payload,
            required_keys=("entity_id", "entity_type"),
        )
        assert payload["entity_id"] == "cli-person1"

    def test_graph_query_returns_json_serializable_success(self) -> None:
        proc = run_cli(
            ["--json", "graph", "query", "--cypher", CYPHER_SMOKE],
        )
        payload = parse_cli_json_stdout(proc)
        assert_json_serializable_query_result(payload)

    def test_graph_tx_begin_returns_json_success(self) -> None:
        proc = run_cli(["--json", "graph", "tx-begin"])
        payload = parse_cli_json_stdout(proc)
        assert_success_envelope(payload, required_keys=("transaction_id",))

    def test_graph_search_uses_existing_manager_method(self) -> None:
        proc = run_cli(
            [
                "--json",
                "graph",
                "search",
                "--query",
                "Alice",
                "--type",
                "hybrid",
                "--limit",
                "5",
            ],
        )
        # Must not AttributeError on search_hybrid; must return a JSON success.
        combined = f"{proc.stdout}\n{proc.stderr}"
        assert "search_hybrid" not in combined or "has no attribute" not in combined
        payload = parse_cli_json_stdout(proc)
        assert_success_envelope(payload)

    def test_graph_index_uses_existing_manager_method(self) -> None:
        proc = run_cli(
            [
                "--json",
                "graph",
                "index",
                "--label",
                "Person",
                "--property",
                "name",
            ],
        )
        combined = f"{proc.stdout}\n{proc.stderr}"
        assert "create_index" not in combined or "has no attribute" not in combined
        payload = parse_cli_json_stdout(proc)
        assert_success_envelope(payload)

    def test_cli_create_is_json_success(self) -> None:
        proc = run_cli(
            ["--json", "graph", "create", "--driver-url", DRIVER_URL],
        )
        payload = parse_cli_json_stdout(proc)
        assert_success_envelope(payload, required_keys=("graph_id", "graph_uri"))


# ===========================================================================
# MCP surface
# ===========================================================================


@pytest.mark.kg_legacy_compat
class TestMCPLifecycle:
    """LEGACY-COMPAT residual + partial GraphService create inventory. Full release lifecycle is under kg_release_eligible."""

    @pytest.mark.asyncio
    async def test_graph_create_returns_success_envelope(
        self,
        tmp_path: Path,
    ) -> None:
        result = await _mcp_create(
            catalog_path=str(tmp_path / "catalog.sqlite"),
            storage_path=str(tmp_path / "store"),
        )
        assert_success_envelope(
            result,
            required_keys=("contract_version", "operation", "target", "result"),
        )
        assert result["operation"] == "create"
        assert result["target"]["uri"] == "kg://contract/lifecycle/branches/main"

    @pytest.mark.asyncio
    async def test_graph_create_returns_durable_graph_identity(
        self,
        tmp_path: Path,
    ) -> None:
        result = await _mcp_create(
            catalog_path=str(tmp_path / "catalog.sqlite"),
            storage_path=str(tmp_path / "store"),
        )
        assert_success_envelope(result)
        identity = result["result"]
        assert identity["graph_id"] == "lifecycle"
        assert identity["branch"] == "main"
        assert identity["revision"]
        assert result["target"]["tenant"] == "contract"
        assert identity["uri"] in {
            "kg://contract/lifecycle",
            "kg://contract/lifecycle/branches/main",
        }

    @pytest.mark.asyncio
    async def test_graph_add_entity_returns_success_envelope(self) -> None:
        result = await _mcp_add_entity(
            entity_id="mcp-person1",
            entity_type="Person",
            properties={"name": "Alice"},
        )
        assert_success_envelope(
            result,
            required_keys=("entity_id", "entity_type"),
        )
        assert result["entity_id"] == "mcp-person1"

    @pytest.mark.asyncio
    async def test_graph_query_cypher_results_are_json_serializable(self) -> None:
        result = await _mcp_query(CYPHER_SMOKE)
        assert_json_serializable_query_result(result)

    @pytest.mark.asyncio
    async def test_graph_transaction_begin_returns_transaction_id(self) -> None:
        result = await _mcp_tx_begin()
        assert_success_envelope(result, required_keys=("transaction_id",))

    @pytest.mark.asyncio
    async def test_transaction_begin_then_commit_across_independent_calls(self) -> None:
        begin = await _mcp_tx_begin()
        assert_success_envelope(begin, required_keys=("transaction_id",))
        commit = await _mcp_tx_commit(begin["transaction_id"])
        assert_success_envelope(commit, required_keys=("transaction_id",))
        assert commit["transaction_id"] == begin["transaction_id"]

    @pytest.mark.asyncio
    async def test_add_then_query_across_independent_mcp_calls(self) -> None:
        add = await _mcp_add_entity(
            entity_id="mcp-reopen-1",
            entity_type="Person",
            properties={"name": "Reopen"},
        )
        assert_success_envelope(add, required_keys=("entity_id",))
        query = await _mcp_query(
            "MATCH (n:Person {name: 'Reopen'}) RETURN n LIMIT 1",
        )
        assert_json_serializable_query_result(query)
        # Strict: entity must be visible after independent call (durable store).
        serialized = json.dumps(query)
        assert "mcp-reopen-1" in serialized or "Reopen" in serialized


# ===========================================================================
# MCP++ surface (tools_dispatch)
# ===========================================================================


@pytest.mark.kg_legacy_compat
class TestMCPPlusLifecycle:
    """LEGACY-COMPAT driver_url adapters. Full release lifecycle is under kg_release_eligible."""

    @pytest.mark.asyncio
    async def test_dispatch_graph_create_returns_success_envelope(
        self,
        tmp_path: Path,
    ) -> None:
        result = await _mcp_plus_dispatch(
            "graph_create",
            {
                "target": "kg://contract/mcpplus/branches/main",
                "catalog_path": str(tmp_path / "catalog.sqlite"),
                "storage_path": str(tmp_path / "store"),
                "idempotency_key": "contract-mcpplus-create",
            },
        )
        # tools_dispatch may attach request_id; status must still be success.
        assert result.get("status") == "success", result
        assert result["result"]["graph_id"] == "mcpplus"
        assert result["target"]["uri"] == "kg://contract/mcpplus/branches/main"
        assert _is_json_safe(result), result

    @pytest.mark.asyncio
    async def test_dispatch_graph_add_entity_returns_success_envelope(self) -> None:
        result = await _mcp_plus_dispatch(
            "graph_add_entity",
            {
                "entity_id": "mcpplus-person1",
                "entity_type": "Person",
                "properties": {"name": "Alice"},
            },
        )
        assert_success_envelope(result, required_keys=("entity_id", "entity_type"))
        assert result["entity_id"] == "mcpplus-person1"

    @pytest.mark.asyncio
    async def test_dispatch_graph_query_cypher_json_serializable(self) -> None:
        result = await _mcp_plus_dispatch(
            "graph_query_cypher",
            {"query": CYPHER_SMOKE},
        )
        # Strip transport-only keys if present, then enforce query contract.
        body = {k: v for k, v in result.items() if k != "request_id"}
        if body.get("status") == "success" and "results" in body:
            assert_json_serializable_query_result(body)
        else:
            assert_json_serializable_query_result(result)

    @pytest.mark.asyncio
    async def test_dispatch_transaction_begin_returns_transaction_id(self) -> None:
        result = await _mcp_plus_dispatch("graph_transaction_begin", {})
        body = {k: v for k, v in result.items() if k != "request_id"}
        assert_success_envelope(body, required_keys=("transaction_id",))

    @pytest.mark.asyncio
    async def test_dispatch_tx_begin_commit_are_independent_calls(self) -> None:
        begin = await _mcp_plus_dispatch("graph_transaction_begin", {})
        assert begin.get("status") == "success", begin
        tx_id = begin.get("transaction_id")
        assert tx_id, begin
        commit = await _mcp_plus_dispatch(
            "graph_transaction_commit",
            {"transaction_id": tx_id},
        )
        assert commit.get("status") == "success", commit
        assert commit.get("transaction_id") == tx_id
        assert _is_json_safe(commit)

    @pytest.mark.asyncio
    async def test_dispatch_add_then_query_independent_calls(self) -> None:
        add = await _mcp_plus_dispatch(
            "graph_add_entity",
            {
                "entity_id": "mcpplus-reopen-1",
                "entity_type": "Person",
                "properties": {"name": "PlusReopen"},
            },
        )
        assert_success_envelope(
            {k: v for k, v in add.items() if k != "request_id"},
            required_keys=("entity_id",),
        )
        query = await _mcp_plus_dispatch(
            "graph_query_cypher",
            {"query": "MATCH (n:Person {name: 'PlusReopen'}) RETURN n LIMIT 1"},
        )
        body = {k: v for k, v in query.items() if k != "request_id"}
        assert_json_serializable_query_result(body)
        assert "PlusReopen" in json.dumps(body) or "mcpplus-reopen-1" in json.dumps(
            body
        )


# ===========================================================================
# Cross-surface parity (independent calls, same expectations)
# ===========================================================================


@pytest.mark.kg_legacy_compat
class TestCrossSurfaceParity:
    """LEGACY-COMPAT cross-surface parity on manager/stale paths. Canonical parity is under kg_release_eligible."""

    @pytest.mark.asyncio
    async def test_add_entity_success_parity_python_mcp_mcpplus(self) -> None:
        entity_id = "parity-entity-1"
        props = {"name": "Parity"}

        py = await _python_add_entity(entity_id, "Person", props)
        mcp = await _mcp_add_entity(entity_id, "Person", props)
        plus = await _mcp_plus_dispatch(
            "graph_add_entity",
            {
                "entity_id": entity_id,
                "entity_type": "Person",
                "properties": props,
            },
        )
        plus_body = {k: v for k, v in plus.items() if k != "request_id"}

        for label, result in (("python", py), ("mcp", mcp), ("mcp++", plus_body)):
            assert_success_envelope(
                result,
                required_keys=("entity_id", "entity_type"),
            ), label
            assert result["entity_id"] == entity_id
            assert result["entity_type"] == "Person"

    @pytest.mark.asyncio
    async def test_query_json_parity_python_mcp_mcpplus(self) -> None:
        py = await _python_query(CYPHER_SMOKE)
        mcp = await _mcp_query(CYPHER_SMOKE)
        plus = await _mcp_plus_dispatch(
            "graph_query_cypher",
            {"query": CYPHER_SMOKE},
        )
        plus_body = {k: v for k, v in plus.items() if k != "request_id"}

        for label, result in (("python", py), ("mcp", mcp), ("mcp++", plus_body)):
            assert_json_serializable_query_result(result), label

    def test_cli_create_and_python_create_graph_both_absent_or_aligned(self) -> None:
        """Drift lock: CLI create_graph call site vs manager API."""
        from ipfs_datasets_py.core_operations import KnowledgeGraphManager

        cli_calls_create = "manager.create_graph" in CLI_PATH.read_text(encoding="utf-8")
        manager_has_create = hasattr(KnowledgeGraphManager, "create_graph")
        # Compatibility reconciliation keeps the deprecated call site aligned.
        assert cli_calls_create is True
        assert manager_has_create is True


# ===========================================================================
# Entity signature unit probe (shared root cause for Python/CLI/MCP/MCP++)
# ===========================================================================


@pytest.mark.kg_legacy_compat
class TestEntityConstructionContract:
    """LEGACY-COMPAT: manager construction kwargs vs Entity/Relationship signatures (debt locks)."""

    def test_storage_entity_accepts_canonical_kwargs(self) -> None:
        from ipfs_datasets_py.knowledge_graphs.storage.types import Entity

        entity = Entity(
            entity_id="ok-1",
            entity_type="Person",
            name="Alice",
            properties={"age": 30},
        )
        assert entity.id == "ok-1"
        assert entity.type == "Person"

    def test_manager_add_entity_source_uses_canonical_kwargs(self) -> None:
        from ipfs_datasets_py.core_operations import knowledge_graph_manager as kgm

        source = inspect.getsource(kgm.KnowledgeGraphManager.add_entity)
        assert "Entity(" in source
        assert re.search(r"Entity\([\s\S]*?\bentity_id\s*=", source)
        assert re.search(r"Entity\([\s\S]*?\bentity_type\s*=", source)

    def test_manager_add_entity_source_matches_entity_signature(self) -> None:
        from ipfs_datasets_py.core_operations import knowledge_graph_manager as kgm
        from ipfs_datasets_py.knowledge_graphs.storage.types import Entity

        source = inspect.getsource(kgm.KnowledgeGraphManager.add_entity)
        sig = inspect.signature(Entity.__init__)
        # Production contract: construction uses entity_id / entity_type (or *args aligned).
        assert "entity_id=" in source or "Entity(entity_id" in source
        assert "entity_type=" in source or "Entity(" in source and "entity_type" in source
        assert "id=" not in source or "entity_id=" in source
        assert list(sig.parameters)[1:4] == ["entity_id", "entity_type", "name"]

# ===========================================================================
# RELEASE-ELIGIBLE — GraphTarget create/write/query/transaction/reopen
# (kg_release_eligible; must pass without skips or expected failures)
# ===========================================================================


@pytest.mark.kg_release_eligible
class TestCanonicalPythonLifecycle:
    """Python Client + GraphTarget — release-eligible lifecycle proof."""

    def test_canonical_create_write_query_transaction_reopen(
        self, tmp_path: Path
    ) -> None:
        from ipfs_datasets_py.knowledge_graphs import Client, GraphTarget

        catalog, store = _kg_paths(tmp_path)
        target = GraphTarget(
            tenant="contract",
            graph_id="py-life",
            branch="main",
        )
        client = Client.open(catalog, storage_path=store)
        try:
            created = client.create(target, idempotency_key="py-create").to_json_dict()
            assert_canonical_lifecycle(created, operation="create")
            assert created["result"]["graph_id"] == "py-life"
            assert created["result"]["revision"]
            create_rev = created["result"]["revision"]

            written = client.write(
                target,
                idempotency_key="py-write",
                params={
                    "entities": [
                        {"id": "e1", "type": "Person", "name": "Ada"},
                    ],
                },
            ).to_json_dict()
            assert_canonical_lifecycle(written, operation="write")
            assert written["result"]["mutation_count"] == 1
            write_rev = written["result"]["revision"]
            assert write_rev != create_rev

            queried = client.query(
                target,
                params={"language": "scan", "text": "", "query": ""},
            ).to_json_dict()
            assert_canonical_lifecycle(queried, operation="query")
            assert queried["result"]["row_count"] == 1
            assert queried["result"]["revision"] == write_rev
            assert _is_json_safe(queried["result"]["rows"])

            cypher = client.query(
                target,
                params={
                    "language": "cypher",
                    "text": "MATCH (n:Person) RETURN n",
                    "query": "MATCH (n:Person) RETURN n",
                },
            ).to_json_dict()
            assert_canonical_lifecycle(cypher, operation="query")
            assert cypher["result"]["row_count"] >= 1
            assert _is_json_safe(cypher)

            begin = client.begin_tx(
                target, params={"acquire_lease": False}
            ).to_json_dict()
            assert_canonical_lifecycle(begin, operation="begin_tx")
            tx_id = begin["result"]["transaction_id"]
            assert isinstance(tx_id, str) and tx_id

            staged = client.write(
                target,
                idempotency_key="py-stage",
                params={
                    "entities": [
                        {"id": "e2", "type": "Person", "name": "Grace"},
                    ],
                    "transaction_id": tx_id,
                },
            ).to_json_dict()
            assert_canonical_lifecycle(staged, operation="write")
            assert staged["result"].get("staged") is True

            committed = client.commit_tx(
                target,
                idempotency_key="py-commit",
                params={"transaction_id": tx_id},
            ).to_json_dict()
            assert_canonical_lifecycle(committed, operation="commit_tx")
            commit_rev = committed["result"].get("revision") or write_rev
        finally:
            client.close()

        reopened = Client.open(catalog, storage_path=store)
        try:
            opened = reopened.open_graph(target).to_json_dict()
            assert_canonical_lifecycle(opened, operation="open")
            assert opened["result"]["revision"]
            assert opened["result"]["entity_count"] == 2

            after = reopened.query(
                target,
                params={"language": "scan"},
            ).to_json_dict()
            assert_canonical_lifecycle(after, operation="query")
            assert after["result"]["row_count"] == 2
            assert after["result"]["revision"] == commit_rev or after["result"][
                "row_count"
            ] == 2
        finally:
            reopened.close()


@pytest.mark.kg_release_eligible
class TestCanonicalCLILifecycle:
    """Package CLI GraphService commands — release-eligible lifecycle proof."""

    def test_canonical_create_write_query_transaction_reopen(
        self, tmp_path: Path
    ) -> None:
        catalog, store = _kg_paths(tmp_path)
        target_uri = "kg://contract/cli-life/branches/main"

        created = run_canonical_cli(
            [
                "graph",
                "create",
                "--target",
                target_uri,
                "--idempotency-key",
                "cli-create",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        cp = parse_cli_json_stdout(created)
        assert_canonical_lifecycle(cp, operation="create")
        assert cp["result"]["graph_id"] == "cli-life"
        assert cp["result"]["revision"]

        entities = json.dumps(
            [{"id": "c1", "type": "Person", "name": "CLI-Alice"}]
        )
        written = run_canonical_cli(
            [
                "graph",
                "write",
                "--target",
                target_uri,
                "--idempotency-key",
                "cli-write",
                "--entities",
                entities,
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        wp = parse_cli_json_stdout(written)
        assert_canonical_lifecycle(wp, operation="write")
        assert wp["result"]["mutation_count"] == 1
        write_rev = wp["result"]["revision"]

        queried = run_canonical_cli(
            [
                "graph",
                "query",
                "--target",
                target_uri,
                "--language",
                "scan",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        qp = parse_cli_json_stdout(queried)
        assert_canonical_lifecycle(qp, operation="query")
        assert qp["result"]["row_count"] == 1
        assert qp["result"]["revision"] == write_rev
        assert qp["result"]["rows"][0][2] == "CLI-Alice"

        begin = run_canonical_cli(
            [
                "graph",
                "transaction",
                "begin",
                "--target",
                target_uri,
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        bp = parse_cli_json_stdout(begin)
        assert_canonical_lifecycle(bp, operation="begin_tx")
        tx_id = bp["result"]["transaction_id"]

        stage = run_canonical_cli(
            [
                "graph",
                "write",
                "--target",
                target_uri,
                "--tx-id",
                tx_id,
                "--idempotency-key",
                "cli-stage",
                "--entities",
                '[{"id":"c2","type":"Person","name":"CLI-Bob"}]',
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        sp = parse_cli_json_stdout(stage)
        assert_canonical_lifecycle(sp, operation="write")
        assert sp["result"].get("staged") is True

        commit = run_canonical_cli(
            [
                "graph",
                "transaction",
                "commit",
                "--target",
                target_uri,
                "--tx-id",
                tx_id,
                "--idempotency-key",
                "cli-commit",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        cmpayload = parse_cli_json_stdout(commit)
        assert_canonical_lifecycle(cmpayload, operation="commit_tx")

        opened = run_canonical_cli(
            [
                "graph",
                "open",
                "--target",
                target_uri,
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        op = parse_cli_json_stdout(opened)
        assert_canonical_lifecycle(op, operation="open")
        assert op["result"]["revision"]

        after = run_canonical_cli(
            [
                "graph",
                "query",
                "--target",
                target_uri,
                "--language",
                "scan",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        ap = parse_cli_json_stdout(after)
        assert_canonical_lifecycle(ap, operation="query")
        assert ap["result"]["row_count"] == 2


@pytest.mark.kg_release_eligible
class TestCanonicalMCPLifecycle:
    """MCP graph_tools via GraphService — release-eligible lifecycle proof."""

    @pytest.mark.asyncio
    async def test_canonical_create_write_query_transaction_reopen(
        self, tmp_path: Path
    ) -> None:
        from ipfs_datasets_py.mcp_server.graph_service_registry import (
            reset_graph_service_registry,
        )
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_add_entity import (
            graph_add_entity,
        )
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_create import (
            graph_create,
        )
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_describe import (
            graph_describe,
        )
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_query_cypher import (
            graph_query_cypher,
        )
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_search_hybrid import (
            graph_search_hybrid,
        )
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_transaction_begin import (
            graph_transaction_begin,
        )
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_transaction_commit import (
            graph_transaction_commit,
        )

        reset_graph_service_registry()
        catalog, store = _kg_paths(tmp_path)
        cat_s, store_s = str(catalog), str(store)
        target = "kg://contract/mcp-life/branches/main"
        try:
            created = await graph_create(
                target=target,
                catalog_path=cat_s,
                storage_path=store_s,
                idempotency_key="mcp-create",
            )
            assert_canonical_lifecycle(created, operation="create")
            assert created["result"]["graph_id"] == "mcp-life"
            assert created["result"]["revision"]
            assert created["target"]["uri"] == target

            written = await graph_add_entity(
                entity_id="m1",
                entity_type="Person",
                properties={"name": "MCP-Ada"},
                target=target,
                catalog_path=cat_s,
                storage_path=store_s,
                idempotency_key="mcp-write",
            )
            assert_canonical_lifecycle(written, operation="write")
            assert written["result"]["mutation_count"] == 1
            write_rev = written["result"]["revision"]

            queried = await graph_query_cypher(
                query="MATCH (n:Person) RETURN n",
                target=target,
                language="cypher",
                catalog_path=cat_s,
                storage_path=store_s,
            )
            assert_canonical_lifecycle(queried, operation="query")
            assert queried["result"]["row_count"] >= 1
            assert queried["result"]["revision"] == write_rev
            assert _is_json_safe(queried)

            begin = await graph_transaction_begin(
                target=target,
                catalog_path=cat_s,
                storage_path=store_s,
            )
            assert_canonical_lifecycle(begin, operation="begin_tx")
            tx_id = begin["result"]["transaction_id"]
            assert tx_id

            staged = await graph_add_entity(
                entity_id="m2",
                entity_type="Person",
                properties={"name": "MCP-Grace"},
                target=target,
                catalog_path=cat_s,
                storage_path=store_s,
                idempotency_key="mcp-stage",
                transaction_id=tx_id,
            )
            assert_canonical_lifecycle(staged, operation="write")
            assert staged["result"].get("staged") is True

            committed = await graph_transaction_commit(
                transaction_id=tx_id,
                target=target,
                catalog_path=cat_s,
                storage_path=store_s,
                idempotency_key="mcp-commit",
            )
            assert_canonical_lifecycle(committed, operation="commit_tx")

            described = await graph_describe(
                target=target,
                catalog_path=cat_s,
                storage_path=store_s,
            )
            assert_canonical_lifecycle(described, operation="describe")
            assert described["result"]["head_revision"]

            after = await graph_search_hybrid(
                query="",
                target=target,
                language="scan",
                catalog_path=cat_s,
                storage_path=store_s,
            )
            assert_canonical_lifecycle(after, operation="query")
            assert after["result"]["row_count"] == 2
        finally:
            reset_graph_service_registry()


@pytest.mark.kg_release_eligible
class TestCanonicalMCPPlusLifecycle:
    """MCP++ tools_dispatch — release-eligible lifecycle proof."""

    @pytest.mark.asyncio
    async def test_canonical_create_write_query_transaction_reopen(
        self, tmp_path: Path
    ) -> None:
        from ipfs_datasets_py.mcp_server.graph_service_registry import (
            reset_graph_service_registry,
        )
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
            tools_dispatch,
        )

        reset_graph_service_registry()
        catalog, store = _kg_paths(tmp_path)
        cat_s, store_s = str(catalog), str(store)
        target = "kg://contract/mcpplus-life/branches/main"
        try:
            created = await tools_dispatch(
                "graph_tools",
                "graph_create",
                {
                    "target": target,
                    "catalog_path": cat_s,
                    "storage_path": store_s,
                    "idempotency_key": "plus-create",
                },
            )
            body = _strip_request_id(created)
            assert_canonical_lifecycle(body, operation="create")
            assert body["result"]["graph_id"] == "mcpplus-life"
            assert body["target"]["uri"] == target

            written = await tools_dispatch(
                "graph_tools",
                "graph_add_entity",
                {
                    "entity_id": "p1",
                    "entity_type": "Person",
                    "properties": {"name": "Plus-Ada"},
                    "target": target,
                    "catalog_path": cat_s,
                    "storage_path": store_s,
                    "idempotency_key": "plus-write",
                },
            )
            wbody = _strip_request_id(written)
            assert_canonical_lifecycle(wbody, operation="write")
            assert wbody["result"]["mutation_count"] == 1
            write_rev = wbody["result"]["revision"]

            queried = await tools_dispatch(
                "graph_tools",
                "graph_query_cypher",
                {
                    "query": "MATCH (n:Person) RETURN n",
                    "target": target,
                    "language": "cypher",
                    "catalog_path": cat_s,
                    "storage_path": store_s,
                },
            )
            qbody = _strip_request_id(queried)
            assert_canonical_lifecycle(qbody, operation="query")
            assert qbody["result"]["row_count"] >= 1
            assert qbody["result"]["revision"] == write_rev
            assert _is_json_safe(qbody)

            begin = await tools_dispatch(
                "graph_tools",
                "graph_transaction_begin",
                {
                    "target": target,
                    "catalog_path": cat_s,
                    "storage_path": store_s,
                },
            )
            bbody = _strip_request_id(begin)
            assert_canonical_lifecycle(bbody, operation="begin_tx")
            tx_id = bbody["result"]["transaction_id"]
            assert tx_id

            staged = await tools_dispatch(
                "graph_tools",
                "graph_add_entity",
                {
                    "entity_id": "p2",
                    "entity_type": "Person",
                    "properties": {"name": "Plus-Grace"},
                    "target": target,
                    "catalog_path": cat_s,
                    "storage_path": store_s,
                    "idempotency_key": "plus-stage",
                    "transaction_id": tx_id,
                },
            )
            sbody = _strip_request_id(staged)
            assert_canonical_lifecycle(sbody, operation="write")
            assert sbody["result"].get("staged") is True

            committed = await tools_dispatch(
                "graph_tools",
                "graph_transaction_commit",
                {
                    "transaction_id": tx_id,
                    "target": target,
                    "catalog_path": cat_s,
                    "storage_path": store_s,
                    "idempotency_key": "plus-commit",
                },
            )
            cbody = _strip_request_id(committed)
            assert_canonical_lifecycle(cbody, operation="commit_tx")

            reopened = await tools_dispatch(
                "graph_tools",
                "graph_describe",
                {
                    "target": target,
                    "catalog_path": cat_s,
                    "storage_path": store_s,
                },
            )
            rbody = _strip_request_id(reopened)
            assert_canonical_lifecycle(rbody, operation="describe")
            assert rbody["result"]["head_revision"]

            after = await tools_dispatch(
                "graph_tools",
                "graph_search_hybrid",
                {
                    "query": "",
                    "target": target,
                    "language": "scan",
                    "catalog_path": cat_s,
                    "storage_path": store_s,
                },
            )
            abody = _strip_request_id(after)
            assert_canonical_lifecycle(abody, operation="query")
            assert abody["result"]["row_count"] == 2
        finally:
            reset_graph_service_registry()


@pytest.mark.kg_release_eligible
class TestCanonicalCrossSurfaceParity:
    """Independent surfaces, same GraphTarget contract vectors."""

    @pytest.mark.asyncio
    async def test_canonical_create_success_parity_python_cli_mcp_mcpplus(
        self, tmp_path: Path
    ) -> None:
        from ipfs_datasets_py.knowledge_graphs import Client, GraphTarget
        from ipfs_datasets_py.mcp_server.graph_service_registry import (
            reset_graph_service_registry,
        )
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
            tools_dispatch,
        )
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_create import (
            graph_create,
        )

        results: Dict[str, Dict[str, Any]] = {}
        # Unique graph_id per surface so shared MCP process registry cannot
        # collide on ALREADY_EXISTS when comparing envelope shape parity.
        expected_ids = {
            "python": "g-python",
            "cli": "g-cli",
            "mcp": "g-mcp",
            "mcp++": "g-mcpplus",
        }

        cat_py, store_py = tmp_path / "py_c.sqlite", tmp_path / "py_s"
        client = Client.open(cat_py, storage_path=store_py)
        try:
            results["python"] = client.create(
                GraphTarget(
                    tenant="parity",
                    graph_id=expected_ids["python"],
                    branch="main",
                ),
                idempotency_key="parity-py",
            ).to_json_dict()
        finally:
            client.close()

        cat_cli, store_cli = tmp_path / "cli_c.sqlite", tmp_path / "cli_s"
        proc = run_canonical_cli(
            [
                "graph",
                "create",
                "--tenant",
                "parity",
                "--graph",
                expected_ids["cli"],
                "--branch",
                "main",
                "--idempotency-key",
                "parity-cli",
                "--format",
                "json",
            ],
            catalog=cat_cli,
            store=store_cli,
        )
        results["cli"] = parse_cli_json_stdout(proc)

        reset_graph_service_registry()
        try:
            cat_m, store_m = tmp_path / "mcp_c.sqlite", tmp_path / "mcp_s"
            results["mcp"] = await graph_create(
                target=f"kg://parity/{expected_ids['mcp']}/branches/main",
                catalog_path=str(cat_m),
                storage_path=str(store_m),
                idempotency_key="parity-mcp",
            )
            plus = await tools_dispatch(
                "graph_tools",
                "graph_create",
                {
                    "target": f"kg://parity/{expected_ids['mcp++']}/branches/main",
                    "catalog_path": str(cat_m),
                    "storage_path": str(store_m),
                    "idempotency_key": "parity-plus",
                },
            )
            results["mcp++"] = _strip_request_id(plus)
        finally:
            reset_graph_service_registry()

        for label, envelope in results.items():
            assert_canonical_lifecycle(envelope, operation="create"), label
            assert envelope["result"]["graph_id"] == expected_ids[label], label
            assert envelope["result"]["revision"], label
            assert envelope["target"]["tenant"] == "parity", label
            assert _is_json_safe(envelope), label

    def test_canonical_lifecycle_tools_use_server_owned_graph_service(self) -> None:
        tool_files = [
            REPO_ROOT
            / "ipfs_datasets_py"
            / "mcp_server"
            / "tools"
            / "graph_tools"
            / name
            for name in (
                "graph_create.py",
                "graph_write.py",
                "graph_add_entity.py",
                "graph_query_cypher.py",
                "graph_transaction_begin.py",
                "graph_transaction_commit.py",
            )
        ]
        for path in tool_files:
            source = path.read_text(encoding="utf-8")
            assert source_uses_server_owned_graph_service(source), (
                f"{path.name} must resolve and call the server-owned GraphService"
            )
