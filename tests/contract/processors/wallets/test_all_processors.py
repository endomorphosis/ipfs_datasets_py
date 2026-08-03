"""WALPROC-G620 cross-chain conformance for every processor family.

Parameterizes all five ledger families through the shared
:class:`WalletProcessorConformance` contract without exemptions that hide
required shared behavior. Also proves cross-chain schema queries preserve
chain identity and exact quantities, and that the deterministic conformance
report records two consecutive clean current-tree runs.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import socket
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.wallets.bitcoin import MAINNET_GENESIS as BITCOIN_GENESIS
from ipfs_datasets_py.processors.wallets.canonical import deterministic_id
from ipfs_datasets_py.processors.wallets.ethereum import ETHEREUM_MAINNET_GENESIS_HASH
from ipfs_datasets_py.processors.wallets.models import (
    AccountKind,
    AccountRef,
    ChainRef,
    ExactAmount,
)
from ipfs_datasets_py.processors.wallets.registry import WalletProcessorRegistry
from ipfs_datasets_py.processors.wallets.solana import SOLANA_MAINNET_GENESIS_HASH
from ipfs_datasets_py.processors.wallets.xrpl import MAINNET_GENESIS as XRPL_GENESIS

_CONTRACT_DIR = Path(__file__).resolve().parent
if str(_CONTRACT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTRACT_DIR))

from conformance import (  # noqa: E402
    REQUIRED_SHARED_CHECKS,
    ConformanceResult,
    FixtureTransport,
    ProviderContract,
    WalletProcessorConformance,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
REPORT_PATH = (
    REPO_ROOT
    / "data"
    / "wallet_processor_migration"
    / "validation"
    / "conformance-report.json"
)

# Five ledger/processor families that must pass the shared contract.
# Worldcoin identity/protocol is covered by test_worldcoin_differential.py.
FAMILY_NAMES: tuple[str, ...] = (
    "bitcoin",
    "ethereum",
    "solana",
    "xrpl",
    "xaman",
)

SHARED_CHECK_LIST: tuple[str, ...] = tuple(sorted(REQUIRED_SHARED_CHECKS))


def _bitcoin_contract() -> ProviderContract:
    return ProviderContract(
        name="bitcoin-mainnet",
        chain_namespace="bip122",
        network="bitcoin-mainnet",
        chain_id=BITCOIN_GENESIS[:32],
        genesis_hash=BITCOIN_GENESIS,
        fixture_subdir="bitcoin",
        provider_name="bitcoin-esplora",
        import_modules=(
            "ipfs_datasets_py.processors.wallets.bitcoin",
            "ipfs_datasets_py.processors.wallets.bitcoin.provider",
            "ipfs_datasets_py.processors.wallets.bitcoin.normalizer",
        ),
        metadata={"family": "bitcoin", "goal_id": "WALPROC-G400", "utxo_model": True},
    )


def _ethereum_contract() -> ProviderContract:
    return ProviderContract(
        name="ethereum-mainnet",
        chain_namespace="eip155",
        network="ethereum-mainnet",
        chain_id="1",
        genesis_hash=ETHEREUM_MAINNET_GENESIS_HASH,
        fixture_subdir="ethereum",
        provider_name="fixture-ethereum-rpc",
        import_modules=(
            "ipfs_datasets_py.processors.wallets.ethereum",
            "ipfs_datasets_py.processors.wallets.ethereum.rpc",
            "ipfs_datasets_py.processors.wallets.ethereum.normalizer",
            "ipfs_datasets_py.processors.wallets.ethereum.finality",
        ),
        metadata={"family": "ethereum", "goal_id": "WALPROC-G300", "read_only": True},
    )


def _solana_contract() -> ProviderContract:
    return ProviderContract(
        name="solana-mainnet-beta",
        chain_namespace="solana",
        network="solana-mainnet-beta",
        chain_id="mainnet-beta",
        genesis_hash=SOLANA_MAINNET_GENESIS_HASH,
        fixture_subdir="solana",
        provider_name="solana-json-rpc",
        import_modules=(
            "ipfs_datasets_py.processors.wallets.solana",
            "ipfs_datasets_py.processors.wallets.solana.provider",
            "ipfs_datasets_py.processors.wallets.solana.normalizer",
        ),
        metadata={"family": "solana", "goal_id": "WALPROC-G500", "read_only": True},
    )


def _xrpl_contract() -> ProviderContract:
    return ProviderContract(
        name="xrpl-mainnet",
        chain_namespace="xrpl",
        network="xrpl-mainnet",
        chain_id="0",
        genesis_hash=XRPL_GENESIS,
        fixture_subdir="xrpl",
        provider_name="xrpl-json-rpc",
        import_modules=(
            "ipfs_datasets_py.processors.wallets.xrpl",
            "ipfs_datasets_py.processors.wallets.xrpl.provider",
            "ipfs_datasets_py.processors.wallets.xrpl.normalizer",
        ),
        metadata={"family": "xrpl", "goal_id": "WALPROC-G200", "xaman_payloads": False},
    )


def _xaman_contract() -> ProviderContract:
    # Xaman composes XRPL settlement; shared checks still apply via XRPL chain identity.
    return ProviderContract(
        name="xaman-payloads",
        chain_namespace="xrpl",
        network="xrpl-mainnet",
        chain_id="0",
        genesis_hash=XRPL_GENESIS,
        fixture_subdir="xaman",
        provider_name="xaman-payload-api",
        import_modules=(
            "ipfs_datasets_py.processors.wallets.xaman",
            "ipfs_datasets_py.processors.wallets.xaman.provider",
            "ipfs_datasets_py.processors.wallets.xaman.processor",
            "ipfs_datasets_py.processors.wallets.xrpl",
        ),
        metadata={
            "family": "xaman",
            "goal_id": "WALPROC-G210",
            "composes": "xrpl",
            "supports_sign": False,
            "supports_submit": False,
            "supports_approve": False,
        },
    )


FAMILY_CONTRACT_BUILDERS: dict[str, Any] = {
    "bitcoin": _bitcoin_contract,
    "ethereum": _ethereum_contract,
    "solana": _solana_contract,
    "xrpl": _xrpl_contract,
    "xaman": _xaman_contract,
}


def family_contract(family: str) -> ProviderContract:
    try:
        builder = FAMILY_CONTRACT_BUILDERS[family]
    except KeyError as exc:
        raise KeyError(f"unknown processor family {family!r}") from exc
    return builder()


def run_family_shared(family: str) -> list[ConformanceResult]:
    suite = WalletProcessorConformance(family_contract(family), FixtureTransport())
    suite.assert_cannot_weaken_shared_checks()
    return suite.run_shared_checks()


def results_to_mapping(results: Sequence[ConformanceResult]) -> dict[str, Any]:
    return {
        "checks": [item.to_dict() for item in results],
        "passed": all(item.passed for item in results),
        "check_names": sorted(item.name for item in results),
        "failed": [
            {"name": item.name, "detail": item.detail}
            for item in results
            if not item.passed
        ],
    }


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "uninstalled"


def dependency_versions() -> dict[str, str]:
    """Record runtime dependency versions for the conformance report."""

    names = (
        "ipfs_datasets_py",
        "pytest",
        "web3",
        "solana",
        "solders",
        "xrpl-py",
        "xumm-sdk-py",
        "bitcoinlib",
        "eth-account",
        "eth-utils",
    )
    return {name: _package_version(name) for name in names}


def _load_report() -> dict[str, Any]:
    assert REPORT_PATH.is_file(), f"missing conformance report: {REPORT_PATH}"
    with REPORT_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    assert isinstance(payload, dict)
    return payload


# ---------------------------------------------------------------------------
# Catalog / registration surface
# ---------------------------------------------------------------------------


def test_five_families_are_registered_and_cataloged() -> None:
    assert len(FAMILY_NAMES) == 5
    assert set(FAMILY_NAMES) == set(FAMILY_CONTRACT_BUILDERS)
    registry = WalletProcessorRegistry()
    known = set(registry.list_families())
    for family in FAMILY_NAMES:
        assert family in known, f"registry missing family {family}"
        contract = family_contract(family)
        assert contract.metadata.get("family") == family
        assert contract.chain_namespace
        assert contract.genesis_hash
        # Extra checks may only extend; empty is allowed for the aggregate suite.
        assert contract.extra_checks == ()


def test_required_shared_checks_catalog_is_complete() -> None:
    assert SHARED_CHECK_LIST == tuple(sorted(REQUIRED_SHARED_CHECKS))
    # Refinement: chain suites may not shrink this set via exemptions.
    assert "exact_amounts" in REQUIRED_SHARED_CHECKS
    assert "address_network_identity" in REQUIRED_SHARED_CHECKS
    assert "secret_leaks" in REQUIRED_SHARED_CHECKS
    assert "no_network_imports" in REQUIRED_SHARED_CHECKS


# ---------------------------------------------------------------------------
# Parameterized shared conformance (no hidden exemptions)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("family", FAMILY_NAMES)
def test_family_passes_every_shared_check_without_exemptions(family: str) -> None:
    results = run_family_shared(family)
    failed = [item for item in results if not item.passed]
    assert not failed, f"{family} failed: " + "; ".join(
        f"{item.name}: {item.detail}" for item in failed
    )
    names = {item.name for item in results}
    assert names == REQUIRED_SHARED_CHECKS
    # No skip/xfail markers hide required coverage on this aggregate surface.
    assert len(results) == len(REQUIRED_SHARED_CHECKS)


@pytest.mark.parametrize("family", FAMILY_NAMES)
def test_family_cannot_weaken_shared_checks(family: str) -> None:
    suite = WalletProcessorConformance(family_contract(family))
    suite.assert_cannot_weaken_shared_checks()


@pytest.mark.parametrize("family", FAMILY_NAMES)
def test_family_fixture_manifest_is_offline_and_present(family: str) -> None:
    transport = FixtureTransport()
    contract = family_contract(family)
    transport.assert_manifest_provenance(contract.fixture_subdir)
    manifest = transport.load_manifest(contract.fixture_subdir)
    assert manifest["classification"]["offline_default"] is True
    for relative in manifest.get("files") or []:
        path = transport.path(contract.fixture_subdir, relative)
        assert path.is_file(), path


# ---------------------------------------------------------------------------
# Two consecutive clean full validation passes
# ---------------------------------------------------------------------------


def test_two_consecutive_clean_runs_across_all_families() -> None:
    """Acceptance: report records two consecutive clean current-tree runs."""

    runs: list[dict[str, Any]] = []
    for run_index in (1, 2):
        family_payloads: dict[str, Any] = {}
        for family in FAMILY_NAMES:
            results = run_family_shared(family)
            mapped = results_to_mapping(results)
            assert mapped["passed"] is True, (
                f"run {run_index} family {family} failed: {mapped['failed']}"
            )
            family_payloads[family] = mapped
        fingerprint = hashlib.sha256(
            json.dumps(family_payloads, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        runs.append(
            {
                "run_id": run_index,
                "status": "clean",
                "families": FAMILY_NAMES,
                "shared_checks": SHARED_CHECK_LIST,
                "family_results": {
                    name: {
                        "passed": payload["passed"],
                        "check_names": payload["check_names"],
                    }
                    for name, payload in family_payloads.items()
                },
                "result_fingerprint": f"sha256:{fingerprint}",
            }
        )

    # Both consecutive runs must agree and be clean.
    assert runs[0]["status"] == "clean"
    assert runs[1]["status"] == "clean"
    assert runs[0]["result_fingerprint"] == runs[1]["result_fingerprint"]

    report = _load_report()
    assert report["goal_id"] == "WALPROC-G620"
    assert report["task_id"] == "WALPROC-027"
    assert report["schema"] == "wallet_processor_migration/conformance-report@1"
    assert len(report["runs"]) >= 2
    for recorded in report["runs"][:2]:
        assert recorded["status"] == "clean"
        assert set(recorded["families"]) == set(FAMILY_NAMES)
        assert set(recorded["shared_checks"]) == REQUIRED_SHARED_CHECKS
    assert report["runs"][0]["result_fingerprint"] == report["runs"][1]["result_fingerprint"]
    assert report["summary"]["all_families_passed"] is True
    assert report["summary"]["consecutive_clean_runs"] >= 2
    assert report["summary"]["exemptions_hiding_required_behavior"] is False


def test_conformance_report_records_dependency_versions() -> None:
    report = _load_report()
    deps = report["dependency_versions"]
    assert isinstance(deps, Mapping)
    assert "ipfs_datasets_py" in deps
    assert "pytest" in deps
    # Live tree versions must match the report for packages that are installed.
    live = dependency_versions()
    for name in ("ipfs_datasets_py", "pytest"):
        assert deps[name] == live[name], f"dependency version drift for {name}"
    # Optional chain packages are allowed to be uninstalled; report must note them.
    for optional in ("web3", "solana", "solders", "xrpl-py", "bitcoinlib"):
        assert optional in deps


# ---------------------------------------------------------------------------
# Cross-chain schema queries: identity + exact quantities
# ---------------------------------------------------------------------------


def test_cross_chain_schema_queries_preserve_identity_and_exact_quantities() -> None:
    """Normalized queries must not collapse chains or coerce amounts to floats."""

    contracts = {name: family_contract(name) for name in FAMILY_NAMES}
    chain_ids = {
        name: contracts[name].chain_ref().chain_ref_id for name in FAMILY_NAMES
    }

    # Distinct namespaces must never share a chain_ref_id.
    by_namespace: dict[str, set[str]] = {}
    for name, contract in contracts.items():
        by_namespace.setdefault(contract.chain_namespace, set()).add(chain_ids[name])
    assert "bip122" in by_namespace and "eip155" in by_namespace
    assert "solana" in by_namespace and "xrpl" in by_namespace
    assert chain_ids["bitcoin"] != chain_ids["ethereum"]
    assert chain_ids["ethereum"] != chain_ids["solana"]
    assert chain_ids["solana"] != chain_ids["xrpl"]
    # Xaman composes XRPL and intentionally shares XRPL chain identity.
    assert chain_ids["xaman"] == chain_ids["xrpl"]

    # Same address bytes on different chains must produce distinct account ids.
    address = "0x1111111111111111111111111111111111111111"
    eth_account = AccountRef(
        contracts["ethereum"].chain_ref(), address, AccountKind.ADDRESS
    )
    # Bitcoin uses a different address form; prove network separation via chain refs.
    btc_chain = contracts["bitcoin"].chain_ref()
    eth_chain = contracts["ethereum"].chain_ref()
    assert btc_chain.chain_ref_id != eth_chain.chain_ref_id
    assert eth_account.account_id.startswith("urn:wallet:account:")

    # Exact amounts stay integer base units under serialization.
    amount = ExactAmount(base_units="18446744073709551615", decimals=18)
    serialized = amount.to_dict()
    assert serialized["base_units"] == "18446744073709551615"
    assert isinstance(serialized["base_units"], str)
    assert "." not in serialized["base_units"]
    assert not isinstance(serialized["base_units"], float)

    # Deterministic record ids include chain identity coordinates.
    payload_a = {
        "chain": eth_chain.identity_dict(),
        "coordinates": {"hash": "0xabc", "index": 0},
    }
    payload_b = {
        "chain": btc_chain.identity_dict(),
        "coordinates": {"hash": "0xabc", "index": 0},
    }
    id_a = deterministic_id("transfer", payload_a)
    id_b = deterministic_id("transfer", payload_b)
    assert id_a != id_b

    # Shared harness identity vectors also prove cross-network separation.
    transport = FixtureTransport()
    vectors = transport.load_shared("identity_vectors.json")
    built: dict[str, str] = {}
    for item in vectors["vectors"]:
        if item.get("expect_valid") is False:
            continue
        chain_data = item["chain"]
        chain = ChainRef(
            namespace=chain_data["namespace"],
            network=chain_data["network"],
            chain_id=chain_data["chain_id"],
            genesis_hash=chain_data["genesis_hash"],
        )
        account = AccountRef(
            chain, item["address"], AccountKind(item.get("kind") or "address")
        )
        built[item["id"]] = account.account_id
        if "must_differ_from" in item:
            assert built[item["id"]] != built[item["must_differ_from"]]


def test_no_network_or_secret_regressions_on_family_imports() -> None:
    original_socket = socket.socket
    original_create = socket.create_connection

    def _blocked(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("network I/O during multi-family conformance import")

    socket.socket = _blocked  # type: ignore[assignment,misc]
    socket.create_connection = _blocked  # type: ignore[assignment]
    try:
        for family in FAMILY_NAMES:
            suite = WalletProcessorConformance(family_contract(family))
            suite.check_no_network_imports()
            suite.check_secret_leaks()
    finally:
        socket.socket = original_socket  # type: ignore[assignment]
        socket.create_connection = original_create  # type: ignore[assignment]


def test_report_lists_every_family_and_shared_check() -> None:
    report = _load_report()
    assert report["families"] == list(FAMILY_NAMES)
    assert set(report["required_shared_checks"]) == REQUIRED_SHARED_CHECKS
    family_status = report["family_status"]
    for family in FAMILY_NAMES:
        assert family_status[family]["passed"] is True
        assert set(family_status[family]["shared_checks_passed"]) == REQUIRED_SHARED_CHECKS
        assert family_status[family]["exemptions"] == []
    assert report["worldcoin_differential"]["covered_by"] == (
        "ipfs_datasets_py/tests/contract/processors/wallets/test_worldcoin_differential.py"
    )
    assert report["acceptance"]["five_families_pass_without_exemptions"] is True
    assert report["acceptance"]["two_consecutive_clean_runs"] is True
    assert report["acceptance"]["cross_chain_identity_and_exact_amounts"] is True
    assert report["acceptance"]["no_import_network_secret_regressions"] is True


def test_ast_symbol_wallet_processor_conformance_is_reachable() -> None:
    """Objective AST query: WalletProcessorConformance."""

    assert WalletProcessorConformance is not None
    suite = WalletProcessorConformance(family_contract("ethereum"))
    assert suite.required_checks == REQUIRED_SHARED_CHECKS
    assert callable(suite.run_shared_checks)
    assert callable(suite.run_all)

__all__ = [
    "FAMILY_NAMES",
    "dependency_versions",
    "family_contract",
    "run_family_shared",
    "results_to_mapping",
]
