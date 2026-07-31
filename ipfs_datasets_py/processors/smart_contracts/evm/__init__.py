"""EVM smart-contract frontend package (CRYPTOIR-G220).

Bounded offline acquisition and normalization of EVM creation/runtime
bytecode, source, ABI, compiler metadata, proxies, opcodes, CFG, and storage
effects.  Importing this package performs no network I/O, secret resolution,
or package installation.
"""

from __future__ import annotations

from .frontend import (
    FRONTEND_ID,
    FRONTEND_SCHEMA_VERSION,
    FRONTEND_VERSION,
    AnalysisMode,
    EVMCodeEpoch,
    EVMContractFrontend,
    EVMNormalizationResult,
    SourceEquivalenceStatus,
)
from .provider import (
    EVM_PROVIDER_ID,
    PROVIDER_SCHEMA_VERSION,
    EVMArtifactProvider,
    EVMContractFixture,
    OfflineEVMProvider,
)
from .proxies import (
    EIP1822_PROXIABLE_SLOT,
    EIP1967_ADMIN_SLOT,
    EIP1967_BEACON_SLOT,
    EIP1967_IMPLEMENTATION_SLOT,
    PROXY_SCHEMA_VERSION,
    ProxyBinding,
    ProxyKind,
    RedeploymentRisk,
    bind_implementation,
    detect_minimal_proxy,
    detect_proxy_pattern,
    normalize_address,
)
from .semantics import (
    DEFAULT_MAX_BYTECODE_BYTES,
    KNOWN_OPCODES,
    SEMANTICS_SCHEMA_VERSION,
    CfgEdge,
    CfgEdgeKind,
    CfgNode,
    ControlFlowGraph,
    DecodedInstruction,
    DisassemblyResult,
    SemanticPassStatus,
    StorageAccessKind,
    StorageEffect,
    analyze_bytecode,
    build_cfg,
    disassemble_bytecode,
    extract_storage_effects,
    incomplete_trace_never_passes,
    normalize_bytecode,
)

__all__ = [
    # Frontend
    "FRONTEND_ID",
    "FRONTEND_SCHEMA_VERSION",
    "FRONTEND_VERSION",
    "AnalysisMode",
    "EVMCodeEpoch",
    "EVMContractFrontend",
    "EVMNormalizationResult",
    "SourceEquivalenceStatus",
    # Provider
    "EVM_PROVIDER_ID",
    "PROVIDER_SCHEMA_VERSION",
    "EVMArtifactProvider",
    "EVMContractFixture",
    "OfflineEVMProvider",
    # Proxies
    "EIP1822_PROXIABLE_SLOT",
    "EIP1967_ADMIN_SLOT",
    "EIP1967_BEACON_SLOT",
    "EIP1967_IMPLEMENTATION_SLOT",
    "PROXY_SCHEMA_VERSION",
    "ProxyBinding",
    "ProxyKind",
    "RedeploymentRisk",
    "bind_implementation",
    "detect_minimal_proxy",
    "detect_proxy_pattern",
    "normalize_address",
    # Semantics
    "DEFAULT_MAX_BYTECODE_BYTES",
    "KNOWN_OPCODES",
    "SEMANTICS_SCHEMA_VERSION",
    "CfgEdge",
    "CfgEdgeKind",
    "CfgNode",
    "ControlFlowGraph",
    "DecodedInstruction",
    "DisassemblyResult",
    "SemanticPassStatus",
    "StorageAccessKind",
    "StorageEffect",
    "analyze_bytecode",
    "build_cfg",
    "disassemble_bytecode",
    "extract_storage_effects",
    "incomplete_trace_never_passes",
    "normalize_bytecode",
]
