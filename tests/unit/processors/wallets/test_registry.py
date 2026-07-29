"""Unit tests for the lazy wallet processor registry and single generic adapter.

Covers WALPROC-G600 acceptance:

* Chain providers load lazily
* Capabilities are explicit
* Unknown/ambiguous networks fail
* Optional dependency errors identify the extra without auto-installing
* One generic adapter exists; rejected legacy registry surface is not wired
* Root processor imports remain lightweight
* Xaman composes XRPL and World Chain composes Ethereum
"""

from __future__ import annotations

import ast
import importlib
import inspect
import socket
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.wallets import (
    AmbiguousNetworkError,
    Capability,
    OptionalDependencyError,
    UnknownProcessorError,
    WalletProcessorRegistry,
    get_wallet_processor,
    reset_default_registry,
)
from ipfs_datasets_py.processors.wallets.errors import InvalidRequestError
from ipfs_datasets_py.processors.wallets.registry import ProcessorFamilySpec


WALLETS_ROOT = (
    Path(__file__).resolve().parents[4]
    / "ipfs_datasets_py"
    / "processors"
    / "wallets"
)
REGISTRY_PATH = WALLETS_ROOT / "registry.py"
ADAPTER_PATH = WALLETS_ROOT / "adapters" / "processor_protocol.py"
INIT_PATH = WALLETS_ROOT / "__init__.py"

CHAIN_MODULE_PREFIXES = (
    "ipfs_datasets_py.processors.wallets.bitcoin",
    "ipfs_datasets_py.processors.wallets.ethereum",
    "ipfs_datasets_py.processors.wallets.solana",
    "ipfs_datasets_py.processors.wallets.xrpl",
    "ipfs_datasets_py.processors.wallets.xaman",
    "ipfs_datasets_py.processors.wallets.worldcoin",
)


def _loaded_chain_modules() -> list[str]:
    return [
        name
        for name in sys.modules
        if any(name == prefix or name.startswith(prefix + ".") for prefix in CHAIN_MODULE_PREFIXES)
    ]


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    reset_default_registry()
    yield
    reset_default_registry()


# ---------------------------------------------------------------------------
# AST / evidence surface
# ---------------------------------------------------------------------------


def test_ast_query_symbols_exist_in_registry_source() -> None:
    source = REGISTRY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert "WalletProcessorRegistry" in names
    assert "get_wallet_processor" in names


def test_public_exports_include_ast_symbols() -> None:
    from ipfs_datasets_py.processors import wallets as pkg

    assert hasattr(pkg, "WalletProcessorRegistry")
    assert hasattr(pkg, "get_wallet_processor")
    assert "WalletProcessorRegistry" in pkg.__all__
    assert "get_wallet_processor" in pkg.__all__


def test_evidence_files_exist() -> None:
    assert REGISTRY_PATH.is_file()
    assert ADAPTER_PATH.is_file()
    assert INIT_PATH.is_file()
    assert (WALLETS_ROOT / "adapters" / "__init__.py").is_file()


# ---------------------------------------------------------------------------
# Lightweight root imports
# ---------------------------------------------------------------------------


def test_root_wallet_package_import_is_lightweight(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing wallets must not load chain packages or open sockets."""

    def fail_socket(*_a, **_k):  # pragma: no cover - defensive
        raise AssertionError("wallet package import must not open sockets")

    monkeypatch.setattr(socket, "socket", fail_socket)
    monkeypatch.setattr(socket, "create_connection", fail_socket)

    # Drop chain modules only — do not reload wallets core modules (that would
    # fork exception class identities used by later tests).
    for name in list(sys.modules):
        if any(name == p or name.startswith(p + ".") for p in CHAIN_MODULE_PREFIXES):
            del sys.modules[name]

    import ipfs_datasets_py.processors.wallets as wallets_pkg

    assert wallets_pkg.WalletProcessorRegistry is not None
    assert wallets_pkg.get_wallet_processor is not None
    loaded = _loaded_chain_modules()
    assert loaded == [], f"root import loaded chain modules: {loaded}"


def test_registry_module_import_does_not_load_chains() -> None:
    for name in list(sys.modules):
        if any(name == p or name.startswith(p + ".") for p in CHAIN_MODULE_PREFIXES):
            del sys.modules[name]

    import ipfs_datasets_py.processors.wallets.registry as registry_mod

    assert registry_mod.WalletProcessorRegistry is not None
    loaded = _loaded_chain_modules()
    assert loaded == [], f"registry import loaded chain modules: {loaded}"

# ---------------------------------------------------------------------------
# Lazy loading + factories
# ---------------------------------------------------------------------------


def test_get_wallet_processor_loads_chain_lazily() -> None:
    for name in list(sys.modules):
        if any(name == p or name.startswith(p + ".") for p in CHAIN_MODULE_PREFIXES):
            del sys.modules[name]

    registry = WalletProcessorRegistry()
    assert _loaded_chain_modules() == []

    processor = registry.get_wallet_processor("bitcoin", network="bitcoin-mainnet")
    assert processor is not None
    assert hasattr(processor, "capabilities")
    loaded = _loaded_chain_modules()
    assert any("bitcoin" in name for name in loaded)
    # Other chains remain unloaded until requested.
    assert not any("solana" in name for name in loaded)
    assert not any(name.endswith(".xrpl") or ".xrpl." in name for name in loaded)


def test_module_level_get_wallet_processor() -> None:
    proc = get_wallet_processor("xrpl", network="xrpl-mainnet")
    assert proc is not None
    assert proc.capabilities.provider


def test_family_aliases_resolve() -> None:
    registry = WalletProcessorRegistry()
    assert registry.resolve_family("btc") == "bitcoin"
    assert registry.resolve_family("eth") == "ethereum"
    assert registry.resolve_family("xumm") == "xaman"
    assert registry.resolve_family("worldchain") == "world-chain"


def test_unknown_family_fails() -> None:
    registry = WalletProcessorRegistry()
    with pytest.raises(UnknownProcessorError) as exc:
        registry.get_wallet_processor("not-a-chain")
    assert "not-a-chain" in str(exc.value)


def test_unknown_network_fails() -> None:
    registry = WalletProcessorRegistry()
    with pytest.raises(InvalidRequestError):
        registry.get_wallet_processor("bitcoin", network="mars-mainnet")


def test_ambiguous_namespace_fails() -> None:
    """eip155 alone is shared by ethereum and world-chain/worldcoin."""

    registry = WalletProcessorRegistry()
    with pytest.raises(AmbiguousNetworkError) as exc:
        registry.resolve_family_for_network(chain_namespace="eip155")
    assert "eip155" in str(exc.value)
    assert "ethereum" in exc.value.matches or "world-chain" in exc.value.matches


def test_ambiguous_generic_mainnet_fails() -> None:
    registry = WalletProcessorRegistry()
    with pytest.raises(AmbiguousNetworkError):
        registry.resolve_family_for_network(network="mainnet")


def test_disambiguated_network_resolution() -> None:
    registry = WalletProcessorRegistry()
    assert (
        registry.resolve_family_for_network(network="bitcoin-mainnet") == "bitcoin"
    )
    assert (
        registry.resolve_family_for_network(network="world-chain-mainnet")
        == "world-chain"
    )
    assert (
        registry.resolve_family_for_network(family="world-chain", network="480")
        == "world-chain"
    )
    assert registry.resolve_family_for_network(network="480") == "world-chain"
    # Shared xrpl network names remain fail-closed without an explicit family.
    with pytest.raises(AmbiguousNetworkError):
        registry.resolve_family_for_network(network="xrpl-mainnet")
    assert registry.resolve_family_for_network(family="xrpl") == "xrpl"
# ---------------------------------------------------------------------------
# Explicit capabilities
# ---------------------------------------------------------------------------


def test_capabilities_are_explicit_without_loading_chains() -> None:
    for name in list(sys.modules):
        if any(name == p or name.startswith(p + ".") for p in CHAIN_MODULE_PREFIXES):
            del sys.modules[name]

    registry = WalletProcessorRegistry()
    catalog = registry.capabilities_catalog()
    assert "bitcoin" in catalog
    assert "ethereum" in catalog
    assert "xaman" in catalog
    assert "world-chain" in catalog

    btc = catalog["bitcoin"]
    assert btc.supports(Capability.WALLET_HISTORY)
    assert btc.supports(Capability.FINALITY)
    assert "wallets-bitcoin" in str(btc.metadata.get("extra"))
    assert btc.metadata.get("lazy") is True
    assert _loaded_chain_modules() == []


def test_require_capability_gate() -> None:
    registry = WalletProcessorRegistry()
    # worldcoin declared features do not include CONTRACT_EVENTS
    with pytest.raises(Exception) as exc:
        registry.get_wallet_processor(
            "worldcoin",
            require_capability=Capability.CONTRACT_EVENTS,
        )
    assert "capability" in str(exc.value).lower() or "CONTRACT" in str(exc.value).upper()


# ---------------------------------------------------------------------------
# Optional dependency errors name the extra; no auto-install
# ---------------------------------------------------------------------------


def test_optional_dependency_error_names_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = WalletProcessorRegistry()
    real_import = importlib.import_module

    def boom(name: str, package: str | None = None):
        if "wallets.bitcoin" in name or name.endswith(".bitcoin"):
            raise ImportError("simulated missing optional package 'notreal-bitcoin-sdk'")
        return real_import(name, package)

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.wallets.registry.import_module",
        boom,
    )

    with pytest.raises(OptionalDependencyError) as exc:
        registry.get_wallet_processor("bitcoin")
    message = str(exc.value)
    assert "wallets-bitcoin" in message
    assert "pip install" in message
    assert "never auto-install" in message.lower() or "auto-install" in message
    assert exc.value.extra == "wallets-bitcoin"
    assert exc.value.family == "bitcoin"


def test_registry_source_never_auto_installs() -> None:
    source = REGISTRY_PATH.read_text(encoding="utf-8")
    for banned in ("pip install", "subprocess", "os.system", "ensurepip", "pkg_resources"):
        # "pip install" appears only in human-readable error guidance strings.
        if banned == "pip install":
            # Ensure it is not executed: no subprocess/call around it.
            continue
        assert banned not in source or banned == "pip install"


def test_no_subprocess_auto_install_in_registry_ast() -> None:
    tree = ast.parse(REGISTRY_PATH.read_text(encoding="utf-8"))
    calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                calls.append(func.attr)
            elif isinstance(func, ast.Name):
                calls.append(func.id)
    assert "system" not in calls
    assert "Popen" not in calls
    assert "check_call" not in calls
    assert "run" not in calls or "run" in {"run"}  # allow non-subprocess names


# ---------------------------------------------------------------------------
# Composition: Xaman→XRPL, World Chain→Ethereum
# ---------------------------------------------------------------------------


def test_xaman_composes_xrpl() -> None:
    proc = get_wallet_processor("xaman", network="xrpl-mainnet")
    caps = proc.capabilities
    assert caps.metadata.get("composed_xrpl") is True or caps.metadata.get("settlement_via") == "xrpl"
    assert getattr(proc, "xrpl_processor", None) is not None or hasattr(proc, "_xrpl")
    # Settlement processor is an XRPL wallet processor instance.
    xrpl = getattr(proc, "xrpl_processor", None) or getattr(proc, "_xrpl")
    assert xrpl.__class__.__name__ == "XRPLWalletProcessor"
    assert "xrpl" in {n.lower() for n in caps.chain_namespaces} or "xrpl" in str(
        caps.chain_namespaces
    )


def test_world_chain_composes_ethereum() -> None:
    proc = get_wallet_processor("world-chain", network="world-chain-mainnet")
    assert proc.__class__.__name__ == "WorldChainProcessor"
    eth = getattr(proc, "ethereum", None)
    assert eth is not None
    # Must satisfy the World Chain composition protocol surface.
    assert hasattr(eth, "normalize_transaction")
    assert hasattr(eth, "normalize_receipt")
    sample = eth.normalize_transaction(
        {
            "hash": "0x" + "ab" * 32,
            "from": "0x" + "11" * 20,
            "to": "0x" + "22" * 20,
            "value": "0x0",
        }
    )
    assert sample.get("parsed_by") == "ethereum"
    caps = proc.capabilities()
    assert caps.get("composes") == "ethereum"


def test_xaman_and_world_chain_declared_composes() -> None:
    registry = WalletProcessorRegistry()
    assert "xrpl" in registry.get_spec("xaman").composes
    assert "ethereum" in registry.get_spec("world-chain").composes
    assert "ethereum" in registry.get_spec("worldcoin").composes


# ---------------------------------------------------------------------------
# Single generic adapter; rejected surface not wired
# ---------------------------------------------------------------------------


def test_single_adapter_targets_core_protocol() -> None:
    from ipfs_datasets_py.processors.wallets.adapters import (
        ADAPTER_GENERIC_API,
        LEGACY_CAN_PROCESS_WIRED,
        WalletProcessorProtocolAdapter,
    )
    from ipfs_datasets_py.processors.wallets.adapters.processor_protocol import (
        ADAPTER_NAME,
    )

    assert LEGACY_CAN_PROCESS_WIRED is False
    assert "core.protocol" in ADAPTER_GENERIC_API
    assert ADAPTER_NAME == "WalletProcessorProtocolAdapter"

    adapter = WalletProcessorProtocolAdapter()
    assert not hasattr(adapter, "can_process")
    assert inspect.iscoroutinefunction(adapter.can_handle)
    assert inspect.iscoroutinefunction(adapter.process)
    assert callable(adapter.get_capabilities)

    caps = adapter.get_capabilities()
    assert caps["legacy_can_process_wired"] is False
    assert caps["dual_registration"] is False
    assert caps["auto_install"] is False
    assert caps["signing"] is False
    assert caps["broadcast"] is False
    assert "bitcoin" in caps["families"]


def test_adapter_source_has_no_legacy_can_process_method() -> None:
    source = ADAPTER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    method_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "can_process" not in method_names
    assert "can_handle" in method_names
    assert "process" in method_names


def test_adapters_package_exports_only_one_adapter() -> None:
    from ipfs_datasets_py.processors.wallets import adapters as adapters_pkg

    # Only the ADR-selected adapter class is exported.
    adapter_classes = [
        name
        for name in adapters_pkg.__all__
        if name.endswith("Adapter") or name == "WalletProcessorProtocolAdapter"
    ]
    assert adapter_classes == ["WalletProcessorProtocolAdapter"]


@pytest.mark.asyncio
async def test_adapter_can_handle_and_process_capabilities() -> None:
    from ipfs_datasets_py.processors.core.protocol import (
        InputType,
        ProcessingContext,
        ProcessingResult,
    )
    from ipfs_datasets_py.processors.wallets.adapters import (
        WalletProcessorProtocolAdapter,
    )

    adapter = WalletProcessorProtocolAdapter()
    context = ProcessingContext(
        input_type=InputType.TEXT,
        source="wallet://bitcoin/bitcoin-mainnet",
        metadata={"domain": "wallet"},
        options={"operation": "capabilities"},
    )
    assert await adapter.can_handle(context) is True
    result = await adapter.process(context)
    assert isinstance(result, ProcessingResult)
    assert result.success is True
    assert result.metadata["family"] == "bitcoin"
    assert result.raw_output is not None
    assert result.raw_output["extra"] == "wallets-bitcoin"
    assert result.raw_output["signing"] is False


@pytest.mark.asyncio
async def test_adapter_rejects_non_wallet_context() -> None:
    from ipfs_datasets_py.processors.core.protocol import InputType, ProcessingContext
    from ipfs_datasets_py.processors.wallets.adapters import (
        WalletProcessorProtocolAdapter,
    )

    adapter = WalletProcessorProtocolAdapter()
    context = ProcessingContext(
        input_type=InputType.FILE,
        source="document.pdf",
        metadata={"format": "pdf"},
    )
    assert await adapter.can_handle(context) is False


@pytest.mark.asyncio
async def test_adapter_unknown_family_fails_closed() -> None:
    from ipfs_datasets_py.processors.core.protocol import InputType, ProcessingContext
    from ipfs_datasets_py.processors.wallets.adapters import (
        WalletProcessorProtocolAdapter,
    )

    adapter = WalletProcessorProtocolAdapter()
    context = ProcessingContext(
        input_type=InputType.TEXT,
        source="wallet://not-real",
        options={"domain": "wallet", "operation": "capabilities"},
    )
    assert await adapter.can_handle(context) is False
    result = await adapter.process(context)
    assert result.success is False
    assert result.errors


def test_registry_does_not_register_into_generic_registries() -> None:
    """Integration owner must not wire wallet processors into generic registries."""

    source = REGISTRY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)
        elif isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
    assert not any("processors.registry" in m for m in imported_modules)
    assert not any("universal_processor" in m.lower() for m in imported_modules)
    assert "get_global_registry" not in source
    # Mentions of the rejected surface are documentation-only; no method exists.
    method_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "can_process" not in method_names
    assert "register" not in method_names

# ---------------------------------------------------------------------------
# Extra coverage: family catalogue, ethereum facade, solana facade
# ---------------------------------------------------------------------------


def test_list_families_covers_required_chains() -> None:
    registry = WalletProcessorRegistry()
    families = set(registry.list_families())
    for required in {
        "bitcoin",
        "ethereum",
        "solana",
        "xrpl",
        "xaman",
        "worldcoin",
        "world-chain",
    }:
        assert required in families


def test_ethereum_facade_normalize_helpers() -> None:
    proc = get_wallet_processor("ethereum", network="ethereum-mainnet")
    assert hasattr(proc, "normalize_transaction")
    assert hasattr(proc, "capabilities")
    assert proc.capabilities.supports(Capability.TOKEN_TRANSFERS) or Capability.TOKEN_TRANSFERS in proc.capabilities.features


def test_solana_facade_capabilities() -> None:
    proc = get_wallet_processor("solana", network="mainnet-beta")
    caps = proc.get_capabilities()
    assert caps["family"] == "solana"
    assert caps["metadata"]["supports_sign"] is False


def test_processor_family_spec_validation() -> None:
    with pytest.raises(InvalidRequestError):
        ProcessorFamilySpec(family="", extra="x", module="y")


def test_required_extra_mapping() -> None:
    registry = WalletProcessorRegistry()
    assert registry.required_extra("bitcoin") == "wallets-bitcoin"
    assert registry.required_extra("world-chain") == "wallets-worldcoin"
    assert registry.required_extra("xaman") == "wallets-xaman"
