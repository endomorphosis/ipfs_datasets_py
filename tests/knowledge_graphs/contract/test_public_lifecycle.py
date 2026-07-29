"""
KGP-001: Public lifecycle contract probes for knowledge graphs.

Black-box probes for create / add / query / reopen / transaction across:

* Python API (``KnowledgeGraphManager``)
* CLI (``ipfs_datasets_cli.py graph …``)
* MCP tools (``graph_tools.*``)
* MCP++ dispatch (``tools_dispatch("graph_tools", …)``)

Each surface is exercised with independent calls. Assertions demand the
production contract (success envelopes, JSON-serializable query results,
durable identity across reopen). Known baseline failures are marked with
strict, issue-linked ``xfail`` markers so exit-code-1 / arbitrary-error
permissiveness is never accepted.

See also:
    docs/architecture/knowledge_graphs_contract_matrix.md
    docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md
"""

from __future__ import annotations

import inspect
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

import pytest

# ---------------------------------------------------------------------------
# Issue-linked xfail reasons (strict). IDs map to the contract matrix.
# ---------------------------------------------------------------------------

ISSUE_MISSING_CREATE_GRAPH = (
    "KGP-001-CREATE-GRAPH: KnowledgeGraphManager has no create_graph; "
    "CLI calls manager.create_graph while MCP uses manager.initialize. "
    "Plan: docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md"
)

ISSUE_ENTITY_SIGNATURE = (
    "KGP-001-ENTITY-SIG: KnowledgeGraphManager.add_entity constructs "
    "Entity(id=…, type=…) but storage.Entity requires entity_id/entity_type/name. "
    "Plan: docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md"
)

ISSUE_RELATIONSHIP_SIGNATURE = (
    "KGP-001-REL-SIG: KnowledgeGraphManager.add_relationship constructs "
    "Relationship(…, type=…) but storage.Relationship requires relationship_type. "
    "Plan: docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md"
)

ISSUE_QUERY_NON_JSON = (
    "KGP-001-QUERY-JSON: query_cypher returns neo4j_compat Result objects that "
    "are not JSON serializable; CLI --json print_result raises TypeError. "
    "Plan: docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md"
)

ISSUE_FRESH_MANAGER = (
    "KGP-001-FRESH-MANAGER: MCP/MCP++ graph tools construct a new "
    "KnowledgeGraphManager per call; writes, transactions, and reopen cannot "
    "share durable state. "
    "Plan: docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md"
)

ISSUE_TX_MANAGER_CTOR = (
    "KGP-001-TX-CTOR: transaction_begin instantiates TransactionManager() "
    "without required graph_engine and storage_backend; ImportError mock path "
    "never runs. "
    "Plan: docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md"
)

ISSUE_CLI_METHOD_DRIFT = (
    "KGP-001-CLI-METHOD-DRIFT: CLI graph search/index/constraint call "
    "search_hybrid/create_index/add_constraint; manager exposes "
    "hybrid_search/index_create/constraint_add. "
    "Plan: docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md"
)

ISSUE_NO_DURABLE_GRAPH_ID = (
    "KGP-001-NO-GRAPH-ID: create/initialize returns no durable graph identity "
    "(tenant/graph/branch/revision); reopen cannot target a stable graph. "
    "Plan: docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md"
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CLI_PATH = REPO_ROOT / "ipfs_datasets_cli.py"
DRIVER_URL = "ipfs://localhost:5001"
CYPHER_SMOKE = "MATCH (n) RETURN n LIMIT 10"


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


# ---------------------------------------------------------------------------
# Shared Python-API helpers
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


async def _mcp_create() -> Dict[str, Any]:
    from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_create import graph_create

    return await graph_create(driver_url=DRIVER_URL)


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
# Diagnostic inventory (pass today — lock observed drift for the matrix)
# ===========================================================================


class TestDriftInventory:
    """Passing probes that record the known baseline failures as facts."""

    def test_manager_lacks_create_graph_method(self) -> None:
        from ipfs_datasets_py.core_operations import KnowledgeGraphManager

        assert not hasattr(KnowledgeGraphManager, "create_graph")
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

    def test_cli_method_names_diverge_from_manager(self) -> None:
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
            assert not hasattr(KnowledgeGraphManager, missing)

    def test_mcp_tools_construct_fresh_managers(self) -> None:
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
            assert source_constructs_fresh_manager(source), (
                f"{path.name} should construct a fresh KnowledgeGraphManager per call"
            )

    def test_cli_create_emits_attribute_error_message(self) -> None:
        """Observe create_graph AttributeError without treating exit 1 as OK."""
        proc = run_cli(
            ["graph", "create", "--driver-url", DRIVER_URL],
        )
        combined = f"{proc.stdout}\n{proc.stderr}"
        assert "create_graph" in combined
        assert "has no attribute" in combined or "AttributeError" in combined

    @pytest.mark.asyncio
    async def test_python_add_entity_error_mentions_unexpected_id(self) -> None:
        result = await _python_add_entity()
        assert result.get("status") == "error"
        assert "unexpected keyword argument 'id'" in str(result.get("message", ""))


# ===========================================================================
# Python API — aspirational lifecycle contracts (strict xfail where broken)
# ===========================================================================


class TestPythonLifecycle:
    """Direct KnowledgeGraphManager contracts."""

    @pytest.mark.xfail(strict=True, reason=ISSUE_MISSING_CREATE_GRAPH)
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

    @pytest.mark.xfail(strict=True, reason=ISSUE_ENTITY_SIGNATURE)
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

    @pytest.mark.xfail(strict=True, reason=ISSUE_RELATIONSHIP_SIGNATURE)
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

    @pytest.mark.xfail(strict=True, reason=ISSUE_QUERY_NON_JSON)
    @pytest.mark.asyncio
    async def test_query_cypher_results_are_json_serializable(self) -> None:
        result = await _python_query(CYPHER_SMOKE)
        assert_json_serializable_query_result(result)

    @pytest.mark.xfail(strict=True, reason=ISSUE_TX_MANAGER_CTOR)
    @pytest.mark.asyncio
    async def test_transaction_begin_returns_transaction_id(self) -> None:
        result = await _python_tx_begin()
        assert_success_envelope(result, required_keys=("transaction_id",))
        assert isinstance(result["transaction_id"], str)
        assert result["transaction_id"]

    @pytest.mark.xfail(strict=True, reason=ISSUE_FRESH_MANAGER)
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

    @pytest.mark.xfail(strict=True, reason=ISSUE_NO_DURABLE_GRAPH_ID)
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


class TestCLILifecycle:
    """Independent CLI process probes."""

    @pytest.mark.xfail(strict=True, reason=ISSUE_MISSING_CREATE_GRAPH)
    def test_graph_create_returns_json_success(self) -> None:
        proc = run_cli(
            ["--json", "graph", "create", "--driver-url", DRIVER_URL],
        )
        payload = parse_cli_json_stdout(proc)
        assert_success_envelope(payload)

    @pytest.mark.xfail(strict=True, reason=ISSUE_ENTITY_SIGNATURE)
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

    @pytest.mark.xfail(strict=True, reason=ISSUE_QUERY_NON_JSON)
    def test_graph_query_returns_json_serializable_success(self) -> None:
        proc = run_cli(
            ["--json", "graph", "query", "--cypher", CYPHER_SMOKE],
        )
        payload = parse_cli_json_stdout(proc)
        assert_json_serializable_query_result(payload)

    @pytest.mark.xfail(strict=True, reason=ISSUE_TX_MANAGER_CTOR)
    def test_graph_tx_begin_returns_json_success(self) -> None:
        proc = run_cli(["--json", "graph", "tx-begin"])
        payload = parse_cli_json_stdout(proc)
        assert_success_envelope(payload, required_keys=("transaction_id",))

    @pytest.mark.xfail(strict=True, reason=ISSUE_CLI_METHOD_DRIFT)
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

    @pytest.mark.xfail(strict=True, reason=ISSUE_CLI_METHOD_DRIFT)
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

    def test_cli_create_failure_is_not_silent_success_json(self) -> None:
        """
        Guard: CLI currently swallows AttributeError and may exit 0.

        Strict contract forbids treating bare exit code as success without a
        parseable success envelope.
        """
        proc = run_cli(
            ["--json", "graph", "create", "--driver-url", DRIVER_URL],
        )
        # Either non-zero exit OR stdout is not a success envelope.
        if proc.returncode == 0:
            text = (proc.stdout or "").strip()
            try:
                payload = json.loads(text) if text else None
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                assert payload.get("status") != "success" or "create_graph" in str(
                    payload
                ), "create must not report success while create_graph is missing"
            else:
                # Non-JSON / error text path — observed baseline.
                assert "create_graph" in f"{proc.stdout}\n{proc.stderr}"


# ===========================================================================
# MCP surface
# ===========================================================================


class TestMCPLifecycle:
    """Independent MCP tool function calls."""

    @pytest.mark.asyncio
    async def test_graph_create_returns_success_envelope(self) -> None:
        """MCP graph_create uses initialize(); shallow success is accepted today."""
        result = await _mcp_create()
        assert_success_envelope(result, required_keys=("message", "driver_url"))

    @pytest.mark.xfail(strict=True, reason=ISSUE_NO_DURABLE_GRAPH_ID)
    @pytest.mark.asyncio
    async def test_graph_create_returns_durable_graph_identity(self) -> None:
        result = await _mcp_create()
        assert_success_envelope(result)
        assert any(
            key in result for key in ("graph_id", "graph_uri", "revision", "branch")
        ), f"MCP create lacks durable graph identity: {result!r}"

    @pytest.mark.xfail(strict=True, reason=ISSUE_ENTITY_SIGNATURE)
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

    @pytest.mark.xfail(strict=True, reason=ISSUE_QUERY_NON_JSON)
    @pytest.mark.asyncio
    async def test_graph_query_cypher_results_are_json_serializable(self) -> None:
        result = await _mcp_query(CYPHER_SMOKE)
        assert_json_serializable_query_result(result)

    @pytest.mark.xfail(strict=True, reason=ISSUE_TX_MANAGER_CTOR)
    @pytest.mark.asyncio
    async def test_graph_transaction_begin_returns_transaction_id(self) -> None:
        result = await _mcp_tx_begin()
        assert_success_envelope(result, required_keys=("transaction_id",))

    @pytest.mark.xfail(strict=True, reason=ISSUE_FRESH_MANAGER)
    @pytest.mark.asyncio
    async def test_transaction_begin_then_commit_across_independent_calls(self) -> None:
        begin = await _mcp_tx_begin()
        assert_success_envelope(begin, required_keys=("transaction_id",))
        commit = await _mcp_tx_commit(begin["transaction_id"])
        assert_success_envelope(commit, required_keys=("transaction_id",))
        assert commit["transaction_id"] == begin["transaction_id"]

    @pytest.mark.xfail(strict=True, reason=ISSUE_FRESH_MANAGER)
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


class TestMCPPlusLifecycle:
    """MCP++ hierarchical dispatch is an independent call surface."""

    @pytest.mark.asyncio
    async def test_dispatch_graph_create_returns_success_envelope(self) -> None:
        result = await _mcp_plus_dispatch("graph_create", {})
        # tools_dispatch may attach request_id; status must still be success.
        assert result.get("status") == "success", result
        assert _is_json_safe(result), result

    @pytest.mark.xfail(strict=True, reason=ISSUE_ENTITY_SIGNATURE)
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

    @pytest.mark.xfail(strict=True, reason=ISSUE_QUERY_NON_JSON)
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

    @pytest.mark.xfail(strict=True, reason=ISSUE_TX_MANAGER_CTOR)
    @pytest.mark.asyncio
    async def test_dispatch_transaction_begin_returns_transaction_id(self) -> None:
        result = await _mcp_plus_dispatch("graph_transaction_begin", {})
        body = {k: v for k, v in result.items() if k != "request_id"}
        assert_success_envelope(body, required_keys=("transaction_id",))

    @pytest.mark.xfail(strict=True, reason=ISSUE_FRESH_MANAGER)
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

    @pytest.mark.xfail(strict=True, reason=ISSUE_FRESH_MANAGER)
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


class TestCrossSurfaceParity:
    """Each surface independently evaluated against the same contract vector."""

    @pytest.mark.xfail(strict=True, reason=ISSUE_ENTITY_SIGNATURE)
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

    @pytest.mark.xfail(strict=True, reason=ISSUE_QUERY_NON_JSON)
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
        # Today: CLI calls it, manager lacks it — recorded as drift.
        assert cli_calls_create is True
        assert manager_has_create is False


# ===========================================================================
# Entity signature unit probe (shared root cause for Python/CLI/MCP/MCP++)
# ===========================================================================


class TestEntityConstructionContract:
    """Manager construction kwargs must match Entity/Relationship signatures."""

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

    def test_manager_add_entity_source_uses_wrong_kwargs(self) -> None:
        from ipfs_datasets_py.core_operations import knowledge_graph_manager as kgm

        source = inspect.getsource(kgm.KnowledgeGraphManager.add_entity)
        assert "Entity(" in source
        # Observed drift: keyword names ``id`` / ``type`` rather than entity_id / entity_type.
        assert re.search(r"Entity\([\s\S]*?\bid\s*=", source)
        assert re.search(r"Entity\([\s\S]*?\btype\s*=", source)

    @pytest.mark.xfail(strict=True, reason=ISSUE_ENTITY_SIGNATURE)
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
