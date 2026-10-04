"""MCP tool tests for wallet_processor_tools (WALPROC-G610).

Validates thin MCP adapters share typed API semantics: finite bounds,
untrusted allowlists, default finalized export, no signing verbs, and
sanitized receipts without wallet payloads/secrets.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.mcp_server.tools.wallet_processor_tools import (
    wallet_export,
    wallet_ingest,
    wallet_processor_capabilities,
    wallet_processor_export,
    wallet_processor_list_families,
    wallet_processor_resume,
    wallet_processor_status,
    wallet_processor_verify_manifest,
)
from ipfs_datasets_py.mcp_server.tools.wallet_processor_tools._helpers import (
    reset_mcp_api,
)
from ipfs_datasets_py.processors.wallets.models import (
    AccountKind,
    AccountRef,
    ChainRef,
    Finality,
    LedgerPosition,
    Provenance,
    TransactionRecord,
    TransactionStatus,
)


NOW = __import__("datetime").datetime(2025, 6, 1, 12, 0, 0, tzinfo=__import__("datetime").timezone.utc)
GENESIS = "0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3"

TOOLS_DIR = (
    Path(__file__).resolve().parents[2]
    / "ipfs_datasets_py"
    / "mcp_server"
    / "tools"
    / "wallet_processor_tools"
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_shared_api(monkeypatch):
    reset_mcp_api()
    # Default empty allowlist for untrusted MCP.
    monkeypatch.delenv("WALLET_PROCESSOR_MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("WALLET_PROCESSOR_MCP_ALLOWED_SECRET_PREFIXES", raising=False)
    yield
    reset_mcp_api()


@pytest.fixture
def chain_dict() -> dict[str, str]:
    return {
        "namespace": "eip155",
        "network": "ethereum-mainnet",
        "chain_id": "1",
        "genesis_hash": GENESIS,
    }


def _record_dict(chain_dict: dict[str, str]) -> dict[str, Any]:
    chain = ChainRef(
        namespace=chain_dict["namespace"],
        network=chain_dict["network"],
        chain_id=chain_dict["chain_id"],
        genesis_hash=chain_dict["genesis_hash"],
    )
    rec = TransactionRecord(
        chain=chain,
        provenance=Provenance(
            provider="fixture-rpc",
            provider_kind="json-rpc",
            request_id="mcp-1",
            scope="wallet:0xabc",
            observed_at=NOW,
        ),
        ledger_position=LedgerPosition(
            sequence=1,
            hash="0x" + "ab" * 32,
            transaction_index=0,
        ),
        finality=Finality.FINALIZED,
        transaction_hash="0x" + "cd" * 32,
        status=TransactionStatus.SUCCEEDED,
        participants=(AccountRef(chain, "0xabc", AccountKind.ADDRESS),),
    )
    return rec.to_dict()


# ---------------------------------------------------------------------------
# Package / registration conventions
# ---------------------------------------------------------------------------


def test_tool_package_exists_and_exports_expected_callables() -> None:
    assert TOOLS_DIR.is_dir()
    assert (TOOLS_DIR / "category.json").is_file()
    assert callable(wallet_ingest)
    assert callable(wallet_export)
    assert callable(wallet_processor_export)
    assert callable(wallet_processor_list_families)
    assert callable(wallet_processor_capabilities)
    assert callable(wallet_processor_status)
    assert callable(wallet_processor_resume)
    assert callable(wallet_processor_verify_manifest)


def test_tools_are_async_and_documented() -> None:
    for fn in (
        wallet_ingest,
        wallet_export,
        wallet_processor_export,
        wallet_processor_list_families,
        wallet_processor_capabilities,
        wallet_processor_status,
        wallet_processor_resume,
        wallet_processor_verify_manifest,
    ):
        assert inspect.iscoroutinefunction(fn)
        assert fn.__doc__ and fn.__doc__.strip()


def test_no_sign_or_broadcast_tool_modules() -> None:
    names = {p.stem for p in TOOLS_DIR.glob("*.py")}
    forbidden = {"sign", "broadcast", "submit", "wallet_sign", "wallet_broadcast"}
    assert not (names & forbidden)
    for path in TOOLS_DIR.glob("*.py"):
        if path.name.startswith("_"):
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name not in {"sign", "broadcast", "submit"}


def test_directory_import_registration_skips_helpers() -> None:
    """Mirrors MCP server import_tools_from_directory conventions."""
    import importlib
    import sys

    tools: dict[str, Any] = {}
    for item in TOOLS_DIR.iterdir():
        valid = (
            item.is_file()
            and item.suffix == ".py"
            and not item.name.startswith(".")
            and not item.name.startswith("_")
        )
        if not valid:
            continue
        module_name = (
            "ipfs_datasets_py.mcp_server.tools.wallet_processor_tools." + item.stem
        )
        module = importlib.import_module(module_name)
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                callable(attr)
                and not attr_name.startswith("_")
                and hasattr(attr, "__module__")
                and hasattr(attr, "__doc__")
                and attr.__module__ == module.__name__
                and not isinstance(attr, type)
            ):
                tools[attr_name] = attr
    assert "wallet_ingest" in tools
    assert "wallet_export" in tools
    assert "wallet_processor_list_families" in tools
    # Helpers not registered
    assert "mcp_api" not in tools
    assert "parse_chain" not in tools


# ---------------------------------------------------------------------------
# Capabilities / list families (no chain extras)
# ---------------------------------------------------------------------------


def test_list_families_and_capabilities() -> None:
    listing = _run(wallet_processor_list_families())
    assert listing["status"] == "success"
    assert listing["supports_sign"] is False
    assert listing["supports_broadcast"] is False
    assert listing["families"]
    caps = _run(wallet_processor_capabilities(family="ethereum"))
    assert caps["status"] == "success"
    assert caps["selected"] is not None
    assert caps["selected"]["supports_sign"] is False


# ---------------------------------------------------------------------------
# Allowlists / untrusted MCP
# ---------------------------------------------------------------------------


def test_wallet_ingest_rejects_provider_url_outside_allowlist(
    chain_dict: dict[str, str],
) -> None:
    result = _run(
        wallet_ingest(
            scope="wallet:0xabc",
            chain=chain_dict,
            bounds={
                "max_items": 10,
                "max_pages": 2,
                "max_requests": 2,
                "max_response_bytes": 1024,
                "max_time_seconds": 30,
                "max_retries": 1,
            },
            provider_url="https://evil.example.net/rpc",
        )
    )
    assert result["status"] == "error"
    assert "allowlist" in result["message"].lower() or result["error"] == "InvalidRequestError"


def test_wallet_ingest_rejects_inline_secret(
    chain_dict: dict[str, str], monkeypatch
) -> None:
    # secret_reference without allowlisted prefix
    result = _run(
        wallet_ingest(
            scope="wallet:0xabc",
            chain=chain_dict,
            secret_reference="env://API_KEY",
        )
    )
    assert result["status"] == "error"


def test_wallet_ingest_allowlisted_host_still_needs_processor(
    chain_dict: dict[str, str],
) -> None:
    """Allowlisted host passes trust gate; missing processor fails closed."""
    result = _run(
        wallet_ingest(
            scope="wallet:0xabc",
            chain=chain_dict,
            bounds={"max_items": 5, "max_pages": 1, "max_requests": 1},
            provider_url="https://rpc.example.com/v1",
            allowed_provider_hosts=["rpc.example.com"],
        )
    )
    # Trust gate passed; no injected processor in MCP default API.
    assert result["status"] == "error"
    assert result["error"] in {
        "UnsupportedCapabilityError",
        "InvalidRequestError",
    }


# ---------------------------------------------------------------------------
# Export (finalized default, provisional/raw explicit)
# ---------------------------------------------------------------------------


def test_wallet_export_default_finalized(
    chain_dict: dict[str, str], tmp_path: Path
) -> None:
    out = tmp_path / "export-out"
    result = _run(
        wallet_export(
            scope="wallet:0xabc",
            chain=chain_dict,
            output_dir=str(out),
            bounds={"max_items": 100},
            records=[_record_dict(chain_dict)],
            mode="finalized",
        )
    )
    assert result["status"] == "success"
    assert result.get("operation_status") == "complete"
    assert result["mode"] == "finalized"
    assert result["partial"] is False
    assert result["record_count"] == 1
    assert "records" not in result or result.get("records") in (None, "<omitted>")
    assert (out / "export-manifest.json").is_file()

    verified = _run(
        wallet_processor_verify_manifest(path=str(out / "export-manifest.json"))
    )
    assert verified["status"] == "success"
    assert verified["ok"] is True


def test_wallet_export_provisional_and_raw_explicit(
    chain_dict: dict[str, str], tmp_path: Path
) -> None:
    prov = _run(
        wallet_processor_export(
            scope="wallet:0xabc",
            chain=chain_dict,
            output_dir=str(tmp_path / "prov"),
            records=[_record_dict(chain_dict)],
            mode="provisional",
        )
    )
    assert prov["status"] == "success"
    assert prov["mode"] == "provisional"
    assert prov["partial"] is True
    assert prov.get("operation_status") == "partial"

    raw_bad = _run(
        wallet_processor_export(
            scope="wallet:0xabc",
            chain=chain_dict,
            output_dir=str(tmp_path / "raw-bad"),
            records=[_record_dict(chain_dict)],
            mode="raw",
            raw_payload_policy="omitted",
        )
    )
    assert raw_bad["status"] == "error"

    raw_ok = _run(
        wallet_processor_export(
            scope="wallet:0xabc",
            chain=chain_dict,
            output_dir=str(tmp_path / "raw"),
            records=[_record_dict(chain_dict)],
            mode="raw",
            raw_payload_policy="referenced",
        )
    )
    assert raw_ok["status"] == "success"
    assert raw_ok["mode"] == "raw"


def test_status_unknown_job_is_sanitized_error() -> None:
    result = _run(wallet_processor_status(job_id="job-does-not-exist"))
    assert result["status"] == "error"
    # Must not echo secrets-shaped fields
    assert "api_key" not in result
    assert "password" not in result


def test_resume_unknown_job() -> None:
    result = _run(wallet_processor_resume(job_id="job-missing"))
    assert result["status"] == "error"


def test_verify_manifest_bad_accounting() -> None:
    result = _run(
        wallet_processor_verify_manifest(
            manifest={
                "manifest_id": "m1",
                "record_count": 3,
                "partitions": [{"record_count": 1}],
                "finality_counts": {"finalized": 1},
                "warning_count": 0,
                "warnings": [],
                "status": "complete",
            }
        )
    )
    assert result["status"] == "success"
    assert result["ok"] is False
    assert result["errors"]
    assert result.get("operation_status") == "complete"


def test_package_does_not_import_chain_extras() -> None:
    """Importing the tool package must not pull bitcoin/ethereum/etc."""
    import sys

    # Clear chain modules if present from other tests.
    prefixes = (
        "ipfs_datasets_py.processors.wallets.bitcoin",
        "ipfs_datasets_py.processors.wallets.ethereum",
        "ipfs_datasets_py.processors.wallets.solana",
        "ipfs_datasets_py.processors.wallets.xrpl",
        "ipfs_datasets_py.processors.wallets.xaman",
        "ipfs_datasets_py.processors.wallets.worldcoin",
    )
    before = {
        name
        for name in sys.modules
        if any(name == p or name.startswith(p + ".") for p in prefixes)
    }
    importlib.reload(
        importlib.import_module(
            "ipfs_datasets_py.mcp_server.tools.wallet_processor_tools"
        )
    )
    after = {
        name
        for name in sys.modules
        if any(name == p or name.startswith(p + ".") for p in prefixes)
    }
    # Reload may not add new chain modules.
    assert after <= before or not (after - before)
