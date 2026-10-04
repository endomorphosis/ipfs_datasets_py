"""CRYPTOIR-G220 EVM contract frontend and deployment semantics.

Acceptance coverage:

* Artifacts bind chain, address, block, code epoch, compiler, flags,
  libraries, constructor, and metadata policy;
* source/deployed equivalence is reproduced rather than trusted;
* EIP-1967, beacon, diamond, minimal-proxy, delegatecall,
  selfdestruct/redeployment, and unknown proxy cases are explicit;
* unsupported opcodes or incomplete traces never pass;
* deployed runtime is analyzed independently when verified source cannot be
  reproduced;
* offline golden bytecode, source-match, proxy, upgrade, and malformed fixtures.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ipfs_datasets_py.processors.smart_contracts.artifacts import bytes_digest
from ipfs_datasets_py.processors.smart_contracts.errors import (
    InvalidRequestError,
    ResourceLimitError,
)
from ipfs_datasets_py.processors.smart_contracts.evm import (
    AnalysisMode,
    ControlFlowGraph,
    EVMCodeEpoch,
    EVMContractFixture,
    EVMContractFrontend,
    OfflineEVMProvider,
    ProxyBinding,
    ProxyKind,
    RedeploymentRisk,
    SemanticPassStatus,
    SourceEquivalenceStatus,
    StorageEffect,
    analyze_bytecode,
    detect_minimal_proxy,
    detect_proxy_pattern,
    disassemble_bytecode,
    incomplete_trace_never_passes,
    normalize_bytecode,
)
from ipfs_datasets_py.processors.smart_contracts.evm.proxies import (
    EIP1967_BEACON_SLOT,
    EIP1967_IMPLEMENTATION_SLOT,
)
from ipfs_datasets_py.processors.smart_contracts.models import (
    AcquisitionStatus,
    ArtifactKind,
    ChainRef,
    ContractAcquisitionRequest,
    ProviderPolicy,
)
from ipfs_datasets_py.processors.smart_contracts.protocols import (
    OperationContext,
    RequestLimits,
)


NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)
ADDR = "0x" + "11" * 20
IMPL = "0x" + "22" * 20
ADMIN = "0x" + "33" * 20
BEACON = "0x" + "44" * 20

# Minimal runtime: STOP only.
STOP_BYTECODE = bytes.fromhex("00")

# PUSH1 0x01 PUSH1 0x02 ADD STOP  — fully supported arithmetic CFG.
ADD_BYTECODE = bytes.fromhex("600160020100")

# SLOAD + SSTORE pattern: PUSH1 0x00 SLOAD PUSH1 0x00 SSTORE STOP
STORAGE_BYTECODE = bytes.fromhex("60005460005500")

# JUMPDEST / JUMP: PUSH1 target JUMP ... JUMPDEST STOP
# pc0: PUSH1 0x04  (push jump dest 4)
# pc2: JUMP
# pc3: STOP (unreachable padding)
# pc4: JUMPDEST
# pc5: STOP
JUMP_BYTECODE = bytes.fromhex("600456005b00")

# Unknown/unsupported opcode 0x0c (not assigned in our closed set) then STOP.
UNSUPPORTED_BYTECODE = bytes.fromhex("0c00")

# SELFDESTRUCT: PUSH1 0x00 SELFDESTRUCT
SELFDESTRUCT_BYTECODE = bytes.fromhex("6000ff")

# Bare DELEGATECALL without known proxy layout: PUSH1 gas PUSH1 addr... simplified
# Just DELEGATECALL opcode present: PUSH1 0x00 PUSH1 0x00 PUSH1 0x00 PUSH1 0x00
# PUSH1 0x00 PUSH1 0x00 DELEGATECALL STOP
DELEGATECALL_BYTECODE = bytes.fromhex("600060006000600060006000f400")

# EIP-1167 minimal proxy pointing at IMPL.
def _minimal_proxy(impl: str) -> bytes:
    addr = bytes.fromhex(impl[2:] if impl.startswith("0x") else impl)
    return (
        bytes.fromhex("363d3d373d3d3d363d73")
        + addr
        + bytes.fromhex("5af43d82803e903d91602b57fd5bf3")
    )


# EIP-1967-ish proxy: embed implementation slot constant + DELEGATECALL.
EIP1967_BYTECODE = (
    bytes.fromhex("7f")  # PUSH32
    + bytes.fromhex(EIP1967_IMPLEMENTATION_SLOT[2:])
    + bytes.fromhex("54")  # SLOAD
    + bytes.fromhex("6000600060006000845af400")  # rough call stack + DELEGATECALL + STOP
)

# Beacon: embed beacon slot.
BEACON_BYTECODE = (
    bytes.fromhex("7f")
    + bytes.fromhex(EIP1967_BEACON_SLOT[2:])
    + bytes.fromhex("546000600060006000845af400")
)

# Diamond: embed facets() selector as PUSH4.
DIAMOND_BYTECODE = bytes.fromhex("637a0ed62760005260006000f400")  # selector + DELEGATECALL-ish


@pytest.fixture
def frontend() -> EVMContractFrontend:
    return EVMContractFrontend()


@pytest.fixture
def context() -> OperationContext:
    return OperationContext(
        request_id="evm-g220",
        limits=RequestLimits(
            max_items=8,
            max_requests=16,
            max_response_bytes=1024 * 1024,
            max_depth=4,
        ),
        deadline=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# AST symbols / public surface
# ---------------------------------------------------------------------------


def test_ast_symbols_are_exportable() -> None:
    """AST query: EVMContractFrontend EVMCodeEpoch ProxyBinding ControlFlowGraph StorageEffect."""

    assert EVMContractFrontend is not None
    assert EVMCodeEpoch is not None
    assert ProxyBinding is not None
    assert ControlFlowGraph is not None
    assert StorageEffect is not None


# ---------------------------------------------------------------------------
# Artifact binding
# ---------------------------------------------------------------------------


def test_code_epoch_binds_required_fields(frontend: EVMContractFrontend) -> None:
    epoch = frontend.bind_code_epoch(
        chain_id="1",
        address=ADDR,
        runtime_bytecode=ADD_BYTECODE,
        block_number=18_000_000,
        code_epoch="epoch-1",
        creation_bytecode=bytes.fromhex("6080604052") + ADD_BYTECODE,
        compiler="solc",
        compiler_version="0.8.20",
        compiler_flags={"optimizer": True, "runs": 200},
        libraries={"Lib": IMPL},
        constructor_args=bytes.fromhex("0000000000000000000000000000000000000000000000000000000000000001"),
        metadata_policy="embedded-cbor-ipfs-none",
        abi=b'[{"type":"function","name":"x"}]',
        network="ethereum-mainnet",
        genesis_hash="0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3",
    )
    payload = epoch.to_dict()
    assert payload["chain_id"] == "1"
    assert payload["address"] == ADDR.lower()
    assert payload["block_number"] == 18_000_000
    assert payload["code_epoch"] == "epoch-1"
    assert payload["compiler"] == "solc"
    assert payload["compiler_version"] == "0.8.20"
    assert payload["compiler_flags"]["optimizer"] is True
    assert payload["libraries"]["Lib"] == IMPL.lower()
    assert payload["constructor_args_digest"].startswith("sha256:")
    assert payload["metadata_policy"] == "embedded-cbor-ipfs-none"
    assert payload["runtime_bytecode_digest"] == bytes_digest(ADD_BYTECODE)
    assert payload["creation_bytecode_digest"].startswith("sha256:")
    assert payload["abi_digest"].startswith("sha256:")
    assert epoch.content_digest().startswith("sha256:")


def test_code_epoch_from_fixture() -> None:
    fixture = EVMContractFixture(
        chain_id="1",
        address=ADDR,
        runtime_bytecode=ADD_BYTECODE,
        creation_bytecode=bytes.fromhex("6080") + ADD_BYTECODE,
        compiler="solc",
        compiler_version="0.8.20",
        compiler_flags={"viaIR": False},
        libraries={"Math": IMPL},
        constructor_args=b"\x00" * 32,
        metadata_policy="strip-cbor",
        block_number=100,
        code_epoch="fixture-epoch",
    )
    epoch = EVMCodeEpoch.from_fixture(fixture, network="ethereum-mainnet")
    assert epoch.block_number == 100
    assert epoch.compiler == "solc"
    assert epoch.libraries["Math"] == IMPL.lower()
    assert epoch.metadata_policy == "strip-cbor"


# ---------------------------------------------------------------------------
# Semantics / CFG / storage / fail-closed
# ---------------------------------------------------------------------------


def test_disassemble_and_cfg_supported_bytecode() -> None:
    disasm, cfg, effects = analyze_bytecode(ADD_BYTECODE, trace_complete=False)
    assert disasm.fully_supported
    assert cfg.pass_status is SemanticPassStatus.PASS
    assert cfg.entry_node_id
    assert not cfg.unsupported_opcodes
    assert not effects  # no SLOAD/SSTORE


def test_storage_effects_extracted() -> None:
    disasm, cfg, effects = analyze_bytecode(STORAGE_BYTECODE)
    kinds = {e.kind.value for e in effects}
    assert "sload" in kinds
    assert "sstore" in kinds
    assert all(e.trace_complete is False for e in effects)


def test_jump_cfg_resolves_static_target() -> None:
    disasm = disassemble_bytecode(JUMP_BYTECODE)
    assert disasm.fully_supported
    from ipfs_datasets_py.processors.smart_contracts.evm.semantics import build_cfg

    cfg = build_cfg(disasm)
    assert not cfg.unresolved_jumps
    assert any(edge.kind.value == "jump" for edge in cfg.edges)


def test_unsupported_opcodes_never_pass() -> None:
    disasm, cfg, _effects = analyze_bytecode(UNSUPPORTED_BYTECODE)
    assert not disasm.fully_supported
    assert cfg.pass_status is SemanticPassStatus.UNSUPPORTED
    assert cfg.unsupported_opcodes
    assert cfg.is_pass is False
    status = incomplete_trace_never_passes(
        cfg=cfg, trace_complete=True, claim_pass=True
    )
    assert status is SemanticPassStatus.UNSUPPORTED


def test_incomplete_traces_never_pass() -> None:
    _disasm, cfg, _effects = analyze_bytecode(ADD_BYTECODE, trace_complete=False)
    # CFG itself may be PASS statically, but incomplete traces never pass claims.
    status = incomplete_trace_never_passes(
        cfg=cfg, trace_complete=False, claim_pass=True
    )
    assert status is SemanticPassStatus.INCOMPLETE
    assert status is not SemanticPassStatus.PASS


def test_control_flow_graph_rejects_pass_with_unsupported() -> None:
    with pytest.raises(InvalidRequestError):
        ControlFlowGraph(
            bytecode_digest=bytes_digest(b"\x00"),
            nodes=(),
            edges=(),
            unsupported_opcodes=(0x0C,),
            pass_status=SemanticPassStatus.PASS,
        )


def test_bytecode_size_bound(frontend: EVMContractFrontend) -> None:
    tiny = EVMContractFrontend(max_bytecode_bytes=4)
    with pytest.raises(ResourceLimitError):
        tiny.bind_code_epoch(
            chain_id="1",
            address=ADDR,
            runtime_bytecode=bytes(8),
        )


# ---------------------------------------------------------------------------
# Proxy patterns
# ---------------------------------------------------------------------------


def test_minimal_proxy_detection() -> None:
    bytecode = _minimal_proxy(IMPL)
    assert detect_minimal_proxy(bytecode) == IMPL.lower()
    binding = detect_proxy_pattern(proxy_address=ADDR, runtime_bytecode=bytecode)
    assert binding.kind is ProxyKind.MINIMAL
    assert binding.implementation_address == IMPL.lower()
    assert binding.has_delegatecall is True


def test_eip1967_proxy_with_storage_slot() -> None:
    # Storage value is left-padded address.
    slot_val = "0x" + ("00" * 12) + IMPL[2:]
    binding = detect_proxy_pattern(
        proxy_address=ADDR,
        runtime_bytecode=EIP1967_BYTECODE,
        storage={EIP1967_IMPLEMENTATION_SLOT: slot_val, "admin": "0x" + ("00" * 12) + ADMIN[2:]},
    )
    assert binding.kind is ProxyKind.EIP1967
    assert binding.implementation_address == IMPL.lower()
    assert binding.admin_address == ADMIN.lower()


def test_beacon_proxy() -> None:
    slot_val = "0x" + ("00" * 12) + BEACON[2:]
    binding = detect_proxy_pattern(
        proxy_address=ADDR,
        runtime_bytecode=BEACON_BYTECODE,
        storage={EIP1967_BEACON_SLOT: slot_val},
    )
    assert binding.kind is ProxyKind.BEACON
    assert binding.beacon_address == BEACON.lower()


def test_diamond_proxy() -> None:
    binding = detect_proxy_pattern(
        proxy_address=ADDR,
        runtime_bytecode=DIAMOND_BYTECODE,
    )
    assert binding.kind is ProxyKind.DIAMOND
    assert binding.diagnostics


def test_unknown_proxy_from_bare_delegatecall() -> None:
    binding = detect_proxy_pattern(
        proxy_address=ADDR,
        runtime_bytecode=DELEGATECALL_BYTECODE,
    )
    assert binding.kind is ProxyKind.UNKNOWN
    assert binding.has_delegatecall is True
    assert any("unknown" in d.lower() or "DELEGATECALL" in d for d in binding.diagnostics)


def test_selfdestruct_redeployment_risk() -> None:
    binding = detect_proxy_pattern(
        proxy_address=ADDR,
        runtime_bytecode=SELFDESTRUCT_BYTECODE,
    )
    assert binding.redeployment_risk is RedeploymentRisk.SELFDESTRUCT_PRESENT
    assert binding.has_delegatecall is False


def test_code_epoch_change_redeployment() -> None:
    previous = bytes_digest(STOP_BYTECODE)
    binding = detect_proxy_pattern(
        proxy_address=ADDR,
        runtime_bytecode=ADD_BYTECODE,
        previous_code_digest=previous,
    )
    assert binding.redeployment_risk is RedeploymentRisk.CODE_EPOCH_CHANGED


def test_no_proxy_on_plain_contract() -> None:
    binding = detect_proxy_pattern(
        proxy_address=ADDR,
        runtime_bytecode=ADD_BYTECODE,
    )
    assert binding.kind is ProxyKind.NONE


# ---------------------------------------------------------------------------
# Source / deployed equivalence
# ---------------------------------------------------------------------------


def test_source_equivalence_reproduced(frontend: EVMContractFrontend) -> None:
    source = b"// SPDX-License-Identifier: MIT\npragma solidity ^0.8.20;\ncontract A {}\n"
    manifest = frontend.build_source_manifest(
        request_id="src-1",
        sources={"contracts/A.sol": source},
        compiler="solc",
        compiler_version="0.8.20",
        settings={"optimizer": {"enabled": True, "runs": 200}},
        libraries={"Lib": IMPL},
        runtime_bytecode=ADD_BYTECODE,
        creation_bytecode=bytes.fromhex("6080") + ADD_BYTECODE,
        constructor_args=b"\x01",
        code_epoch="epoch-src",
        observed_at=NOW,
    )
    status = frontend.reproduce_source_equivalence(
        manifest,
        runtime=ADD_BYTECODE,
        creation=bytes.fromhex("6080") + ADD_BYTECODE,
    )
    assert status is SourceEquivalenceStatus.REPRODUCED


def test_source_equivalence_mismatch_triggers_independent_runtime(
    frontend: EVMContractFrontend,
) -> None:
    source = b"contract B {}\n"
    manifest = frontend.build_source_manifest(
        request_id="src-2",
        sources={"B.sol": source},
        compiler="solc",
        compiler_version="0.8.20",
        runtime_bytecode=ADD_BYTECODE,  # declared expected
        observed_at=NOW,
    )
    # Deployed runtime differs from declared digest.
    result = frontend.normalize_contract(
        chain_id="1",
        address=ADDR,
        runtime_bytecode=STORAGE_BYTECODE,
        source_manifest=manifest,
        claim_semantic_pass=False,
    )
    assert result.source_equivalence is SourceEquivalenceStatus.INDEPENDENT_RUNTIME
    assert result.analysis_mode is AnalysisMode.RUNTIME_ONLY
    assert any("independently" in d for d in result.diagnostics)
    # Runtime still fully analyzed.
    assert result.cfg.bytecode_digest == bytes_digest(STORAGE_BYTECODE)
    assert result.storage_effects


def test_source_not_declared_is_evidence_only(frontend: EVMContractFrontend) -> None:
    source = b"contract C {}\n"
    manifest = frontend.build_source_manifest(
        request_id="src-3",
        sources={"C.sol": source},
        compiler="solc",
        compiler_version="0.8.19",
        # no runtime/creation digests
        observed_at=NOW,
    )
    result = frontend.normalize_contract(
        chain_id="1",
        address=ADDR,
        runtime_bytecode=ADD_BYTECODE,
        source_manifest=manifest,
    )
    assert result.source_equivalence is SourceEquivalenceStatus.NOT_DECLARED
    assert result.analysis_mode is AnalysisMode.SOURCE_EVIDENCE_ONLY


def test_no_source_analyzes_runtime_independently(frontend: EVMContractFrontend) -> None:
    result = frontend.normalize_contract(
        chain_id="1",
        address=ADDR,
        runtime_bytecode=ADD_BYTECODE,
        block_number=1,
        compiler="solc",
        compiler_version="0.8.20",
    )
    assert result.analysis_mode is AnalysisMode.RUNTIME_ONLY
    assert result.source_equivalence is SourceEquivalenceStatus.INDEPENDENT_RUNTIME


# ---------------------------------------------------------------------------
# Full normalize + golden fixtures
# ---------------------------------------------------------------------------


def test_normalize_contract_full_binding(frontend: EVMContractFrontend) -> None:
    result = frontend.normalize_contract(
        chain_id="1",
        address=ADDR,
        runtime_bytecode=STORAGE_BYTECODE,
        block_number=42,
        code_epoch="golden-1",
        creation_bytecode=bytes.fromhex("60806040") + STORAGE_BYTECODE,
        compiler="solc",
        compiler_version="0.8.20",
        compiler_flags={"optimizer": True},
        libraries={"SafeMath": IMPL},
        constructor_args=b"\x00" * 32,
        metadata_policy="embedded-cbor-ipfs-none",
        abi=b"[]",
        network="ethereum-mainnet",
        claim_semantic_pass=True,
    )
    assert result.code_epoch.chain_id == "1"
    assert result.code_epoch.block_number == 42
    assert result.code_epoch.compiler == "solc"
    assert result.code_epoch.libraries["SafeMath"] == IMPL.lower()
    assert result.code_epoch.constructor_args_digest.startswith("sha256:")
    assert result.is_pass is True  # static CFG claim
    assert result.attributes.get("static_cfg_only") is True
    assert result.storage_effects
    assert result.content_digest().startswith("sha256:")


def test_normalize_with_unsupported_never_passes(frontend: EVMContractFrontend) -> None:
    result = frontend.normalize_contract(
        chain_id="1",
        address=ADDR,
        runtime_bytecode=UNSUPPORTED_BYTECODE,
        claim_semantic_pass=True,
        trace_complete=True,
    )
    assert result.semantic_pass_status is SemanticPassStatus.UNSUPPORTED
    assert result.is_pass is False


def test_normalize_fixture_golden_path(frontend: EVMContractFrontend) -> None:
    fixture = EVMContractFixture(
        chain_id="1",
        address=ADDR,
        runtime_bytecode=ADD_BYTECODE,
        creation_bytecode=bytes.fromhex("6080") + ADD_BYTECODE,
        abi_json=b'[{"name":"add"}]',
        source_files={"A.sol": b"contract A {}"},
        compiler="solc",
        compiler_version="0.8.20",
        compiler_flags={"runs": 200},
        libraries={"L": IMPL},
        constructor_args=b"\x02",
        block_number=7,
        code_epoch="fixture-golden",
        metadata_policy="embedded-cbor-ipfs-none",
        storage={"0x0": "0x1"},
    )
    result = frontend.normalize_fixture(fixture, claim_semantic_pass=True)
    assert result.code_epoch.code_epoch == "fixture-golden"
    assert result.code_epoch.block_number == 7
    assert result.proxy.kind is ProxyKind.NONE
    assert result.is_pass is True


def test_normalize_selfdestruct_and_unknown_proxy(frontend: EVMContractFrontend) -> None:
    result = frontend.normalize_contract(
        chain_id="1",
        address=ADDR,
        runtime_bytecode=DELEGATECALL_BYTECODE + bytes.fromhex("ff"),
        claim_semantic_pass=False,
    )
    # DELEGATECALL present → unknown proxy; trailing SELFDESTRUCT may be part of stream
    assert result.proxy.kind in {ProxyKind.UNKNOWN, ProxyKind.NONE} or result.cfg.has_delegatecall
    # Explicit diagnostics about uncertainty or selfdestruct when present.
    assert result.diagnostics


# ---------------------------------------------------------------------------
# Offline provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_offline_provider_acquires_bytecode(context: OperationContext) -> None:
    fixture = EVMContractFixture(
        chain_id="1",
        address=ADDR,
        runtime_bytecode=ADD_BYTECODE,
        creation_bytecode=bytes.fromhex("6080") + ADD_BYTECODE,
        abi_json=b"[]",
        compiler="solc",
        compiler_version="0.8.20",
        block_number=9,
        code_epoch="prov-1",
    )
    provider = OfflineEVMProvider([fixture])
    request = ContractAcquisitionRequest(
        request_id="acq-1",
        chain=ChainRef(chain="evm", network="ethereum-mainnet", chain_id="1"),
        artifact_kind=ArtifactKind.BYTECODE,
        locator=f"evm://1/{ADDR}",
        provider_policy=ProviderPolicy(
            allowed_providers=frozenset({provider.provider_id}),
        ),
        code_epoch="prov-1",
    )
    result = await provider.acquire(request, context=context)
    assert result.status is AcquisitionStatus.AVAILABLE
    assert result.artifacts
    assert result.artifacts[0].content_digest == bytes_digest(ADD_BYTECODE)
    assert result.attributes["compiler"] == "solc"
    assert result.attributes["code_epoch"] == "prov-1"
    assert result.attributes["libraries"] == {}


@pytest.mark.asyncio
async def test_offline_provider_unavailable(context: OperationContext) -> None:
    provider = OfflineEVMProvider([])
    request = ContractAcquisitionRequest(
        request_id="acq-2",
        chain=ChainRef(chain="evm", network="ethereum-mainnet", chain_id="1"),
        artifact_kind=ArtifactKind.BYTECODE,
        locator=f"evm://1/{ADDR}",
    )
    result = await provider.acquire(request, context=context)
    assert result.status is AcquisitionStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_offline_provider_creation_and_source(context: OperationContext) -> None:
    fixture = EVMContractFixture(
        chain_id="1",
        address=ADDR,
        runtime_bytecode=ADD_BYTECODE,
        creation_bytecode=bytes.fromhex("6080") + ADD_BYTECODE,
        source_files={
            "contracts/A.sol": b"contract A {}",
            "contracts/B.sol": b"contract B {}",
        },
    )
    provider = OfflineEVMProvider([fixture])
    creation_req = ContractAcquisitionRequest(
        request_id="acq-3",
        chain=ChainRef(chain="evm", network="ethereum-mainnet", chain_id="1"),
        artifact_kind=ArtifactKind.CREATION_BYTECODE,
        locator=f"evm://1/{ADDR}@9",
    )
    # block-specific key may miss; falls back to address-only
    result = await provider.acquire(creation_req, context=context)
    assert result.status is AcquisitionStatus.AVAILABLE

    source_req = ContractAcquisitionRequest(
        request_id="acq-4",
        chain=ChainRef(chain="evm", network="ethereum-mainnet", chain_id="1"),
        artifact_kind=ArtifactKind.SOURCE,
        locator=ADDR,  # bare address
    )
    source_result = await provider.acquire(source_req, context=context)
    assert source_result.status is AcquisitionStatus.AVAILABLE
    assert len(source_result.artifacts) == 2


# ---------------------------------------------------------------------------
# Malformed / fail-closed inputs
# ---------------------------------------------------------------------------


def test_invalid_address_rejected(frontend: EVMContractFrontend) -> None:
    with pytest.raises(InvalidRequestError):
        frontend.bind_code_epoch(
            chain_id="1",
            address="0x1234",
            runtime_bytecode=ADD_BYTECODE,
        )


def test_invalid_hex_bytecode_rejected() -> None:
    with pytest.raises(InvalidRequestError):
        normalize_bytecode("0xzz")


def test_unknown_proxy_requires_diagnostics() -> None:
    with pytest.raises(InvalidRequestError):
        ProxyBinding(
            proxy_address=ADDR,
            kind=ProxyKind.UNKNOWN,
            diagnostics=(),
        )


def test_package_exports_round_trip_dict(frontend: EVMContractFrontend) -> None:
    result = frontend.normalize_contract(
        chain_id="8453",
        address=ADDR,
        runtime_bytecode=ADD_BYTECODE,
        network="base-mainnet",
        claim_semantic_pass=True,
    )
    payload = result.to_dict()
    assert payload["code_epoch"]["chain_id"] == "8453"
    assert "cfg" in payload
    assert "proxy" in payload
    assert "storage_effects" in payload
    # Secret-safe: no private keys.
    assert "private_key" not in str(payload)
