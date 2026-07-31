"""EVM contract frontend and deployment semantics (CRYPTOIR-G220).

Normalizes creation/runtime bytecode, source, ABI, compiler/build metadata,
storage, proxies, opcodes, CFG, and storage effects into explicit, fail-closed
records.  Source/deployed equivalence is **reproduced** (digest match) rather
than trusted from provider claims.  When verified source cannot be reproduced,
deployed runtime is analyzed independently.

Importing this module performs no network I/O, secret resolution, or package
installation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from ..artifacts import bytes_digest
from ..canonical import content_digest, freeze_json, thaw_json
from ..errors import (
    ArtifactInconsistentError,
    InvalidRequestError,
    ResourceLimitError,
)
from ..models import ensure_secret_safe
from ..source import SourceManifest, ToolchainPin
from .proxies import (
    ProxyBinding,
    ProxyKind,
    RedeploymentRisk,
    detect_proxy_pattern,
    normalize_address,
)
from .provider import EVMContractFixture, OfflineEVMProvider
from .semantics import (
    ControlFlowGraph,
    DisassemblyResult,
    SemanticPassStatus,
    StorageEffect,
    analyze_bytecode,
    incomplete_trace_never_passes,
    normalize_bytecode,
)


FRONTEND_SCHEMA_VERSION = "smart-contract-evm-frontend-v1"
FRONTEND_ID = "smart-contracts.evm.frontend"
FRONTEND_VERSION = "1.0.0"


class SourceEquivalenceStatus(StrEnum):
    """Whether source was reproducibly bound to deployed bytecode."""

    REPRODUCED = "reproduced"
    NOT_DECLARED = "not_declared"
    MISMATCH = "mismatch"
    INDEPENDENT_RUNTIME = "independent_runtime"
    UNAVAILABLE = "unavailable"


class AnalysisMode(StrEnum):
    """How the frontend treated source relative to deployed code."""

    SOURCE_AND_RUNTIME = "source_and_runtime"
    RUNTIME_ONLY = "runtime_only"
    SOURCE_EVIDENCE_ONLY = "source_evidence_only"


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must not be empty")
    if value != value.strip():
        raise InvalidRequestError(f"{name} must not have surrounding whitespace")
    return value


def _non_negative(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"{name} must be a non-negative integer")
    return value


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    frozen = freeze_json(dict(value or {}))
    if not isinstance(frozen, Mapping):
        raise InvalidRequestError("attributes must be a mapping")
    ensure_secret_safe(frozen)
    return frozen


def _optional_digest(value: str, name: str) -> str:
    if not value:
        return ""
    text = _required_text(value, name)
    if not text.startswith("sha256:"):
        raise InvalidRequestError(f"{name} must be a tagged sha256 digest")
    return text


@dataclass(frozen=True, slots=True)
class EVMCodeEpoch:
    """Bound code epoch for one contract deployment at a chain coordinate.

    Artifacts bind chain, address, block, code epoch, compiler, flags,
    libraries, constructor, and metadata policy.  Empty optional fields mean
    "unbound evidence" rather than a silent default.
    """

    chain_id: str
    address: str
    runtime_bytecode_digest: str
    block_number: int | None = None
    code_epoch: str = ""
    creation_bytecode_digest: str = ""
    compiler: str = ""
    compiler_version: str = ""
    compiler_flags: Mapping[str, Any] = field(default_factory=dict)
    libraries: Mapping[str, str] = field(default_factory=dict)
    constructor_args_digest: str = ""
    metadata_policy: str = "embedded-cbor-ipfs-none"
    abi_digest: str = ""
    network: str = ""
    genesis_hash: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = FRONTEND_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "chain_id", _required_text(self.chain_id, "chain_id"))
        object.__setattr__(self, "address", normalize_address(self.address))
        object.__setattr__(
            self,
            "runtime_bytecode_digest",
            _optional_digest(self.runtime_bytecode_digest, "runtime_bytecode_digest")
            if self.runtime_bytecode_digest
            else "",
        )
        if not self.runtime_bytecode_digest and not self.creation_bytecode_digest:
            # Allow empty runtime only when creation is also empty (pre-deploy);
            # for normal epochs runtime is required.
            pass
        if self.block_number is not None:
            object.__setattr__(
                self, "block_number", _non_negative(self.block_number, "block_number")
            )
        object.__setattr__(
            self, "code_epoch", self.code_epoch.strip() if self.code_epoch else ""
        )
        object.__setattr__(
            self,
            "creation_bytecode_digest",
            _optional_digest(self.creation_bytecode_digest, "creation_bytecode_digest")
            if self.creation_bytecode_digest
            else "",
        )
        object.__setattr__(
            self, "compiler", self.compiler.strip() if self.compiler else ""
        )
        object.__setattr__(
            self,
            "compiler_version",
            self.compiler_version.strip() if self.compiler_version else "",
        )
        object.__setattr__(
            self, "compiler_flags", _freeze_mapping(self.compiler_flags)
        )
        libraries = {
            _required_text(k, "library name"): normalize_address(v)
            for k, v in dict(self.libraries).items()
        }
        object.__setattr__(self, "libraries", MappingProxyType(libraries))
        object.__setattr__(
            self,
            "constructor_args_digest",
            _optional_digest(self.constructor_args_digest, "constructor_args_digest")
            if self.constructor_args_digest
            else "",
        )
        object.__setattr__(
            self,
            "metadata_policy",
            _required_text(self.metadata_policy, "metadata_policy"),
        )
        object.__setattr__(
            self,
            "abi_digest",
            _optional_digest(self.abi_digest, "abi_digest") if self.abi_digest else "",
        )
        object.__setattr__(
            self, "network", self.network.strip() if self.network else ""
        )
        object.__setattr__(
            self, "genesis_hash", self.genesis_hash.strip() if self.genesis_hash else ""
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    @property
    def record_id(self) -> str:
        return content_digest(
            {
                "address": self.address,
                "block_number": self.block_number,
                "chain_id": self.chain_id,
                "code_epoch": self.code_epoch,
                "runtime_bytecode_digest": self.runtime_bytecode_digest,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "abi_digest": self.abi_digest,
            "address": self.address,
            "attributes": thaw_json(self.attributes),
            "block_number": self.block_number,
            "chain_id": self.chain_id,
            "code_epoch": self.code_epoch,
            "compiler": self.compiler,
            "compiler_flags": thaw_json(self.compiler_flags),
            "compiler_version": self.compiler_version,
            "constructor_args_digest": self.constructor_args_digest,
            "creation_bytecode_digest": self.creation_bytecode_digest,
            "genesis_hash": self.genesis_hash,
            "libraries": dict(self.libraries),
            "metadata_policy": self.metadata_policy,
            "network": self.network,
            "runtime_bytecode_digest": self.runtime_bytecode_digest,
            "schema_version": self.schema_version,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())

    @classmethod
    def from_fixture(
        cls,
        fixture: EVMContractFixture,
        *,
        network: str = "",
        genesis_hash: str = "",
    ) -> "EVMCodeEpoch":
        """Build an epoch binding from an offline fixture (no network)."""

        if not isinstance(fixture, EVMContractFixture):
            raise InvalidRequestError("fixture must be an EVMContractFixture")
        runtime_digest = (
            bytes_digest(fixture.runtime_bytecode) if fixture.runtime_bytecode else ""
        )
        creation_digest = (
            bytes_digest(fixture.creation_bytecode) if fixture.creation_bytecode else ""
        )
        if not runtime_digest and not creation_digest:
            raise InvalidRequestError(
                "fixture must provide runtime or creation bytecode for a code epoch"
            )
        code_epoch = fixture.code_epoch
        if not code_epoch and runtime_digest:
            code_epoch = f"code:{runtime_digest}"
        return cls(
            chain_id=fixture.chain_id,
            address=fixture.address,
            runtime_bytecode_digest=runtime_digest,
            block_number=fixture.block_number,
            code_epoch=code_epoch,
            creation_bytecode_digest=creation_digest,
            compiler=fixture.compiler,
            compiler_version=fixture.compiler_version,
            compiler_flags=dict(fixture.compiler_flags),
            libraries=dict(fixture.libraries),
            constructor_args_digest=bytes_digest(fixture.constructor_args)
            if fixture.constructor_args
            else "",
            metadata_policy=fixture.metadata_policy,
            abi_digest=bytes_digest(fixture.abi_json) if fixture.abi_json else "",
            network=network,
            genesis_hash=genesis_hash,
            attributes=dict(fixture.attributes),
        )


@dataclass(frozen=True, slots=True)
class EVMNormalizationResult:
    """Full frontend output for one contract observation."""

    code_epoch: EVMCodeEpoch
    proxy: ProxyBinding
    disassembly: DisassemblyResult
    cfg: ControlFlowGraph
    storage_effects: tuple[StorageEffect, ...]
    source_equivalence: SourceEquivalenceStatus
    analysis_mode: AnalysisMode
    semantic_pass_status: SemanticPassStatus
    diagnostics: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = FRONTEND_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.code_epoch, EVMCodeEpoch):
            raise InvalidRequestError("code_epoch must be an EVMCodeEpoch")
        if not isinstance(self.proxy, ProxyBinding):
            raise InvalidRequestError("proxy must be a ProxyBinding")
        if not isinstance(self.disassembly, DisassemblyResult):
            raise InvalidRequestError("disassembly must be a DisassemblyResult")
        if not isinstance(self.cfg, ControlFlowGraph):
            raise InvalidRequestError("cfg must be a ControlFlowGraph")
        effects = tuple(self.storage_effects)
        for index, effect in enumerate(effects):
            if not isinstance(effect, StorageEffect):
                raise InvalidRequestError(
                    f"storage_effects[{index}] must be a StorageEffect"
                )
        object.__setattr__(self, "storage_effects", effects)
        object.__setattr__(
            self,
            "source_equivalence",
            self.source_equivalence
            if isinstance(self.source_equivalence, SourceEquivalenceStatus)
            else SourceEquivalenceStatus(str(self.source_equivalence)),
        )
        object.__setattr__(
            self,
            "analysis_mode",
            self.analysis_mode
            if isinstance(self.analysis_mode, AnalysisMode)
            else AnalysisMode(str(self.analysis_mode)),
        )
        object.__setattr__(
            self,
            "semantic_pass_status",
            self.semantic_pass_status
            if isinstance(self.semantic_pass_status, SemanticPassStatus)
            else SemanticPassStatus(str(self.semantic_pass_status)),
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_required_text(item, "diagnostics item") for item in self.diagnostics),
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        # Invariant: unsupported opcodes / incomplete traces never pass.
        if self.semantic_pass_status is SemanticPassStatus.PASS:
            if self.cfg.unsupported_opcodes or self.cfg.unresolved_jumps:
                raise InvalidRequestError(
                    "semantic pass forbidden with unsupported opcodes or unresolved jumps"
                )
            if not self.attributes.get("trace_complete", False):
                # Static CFG-only pass is allowed only when explicitly marked
                # as static_cfg_pass in attributes; default is fail-closed for
                # execution-trace claims.
                if not self.attributes.get("static_cfg_only", False):
                    raise InvalidRequestError(
                        "semantic pass requires complete trace or static_cfg_only=True"
                    )
        ensure_secret_safe(self.to_dict())

    @property
    def is_pass(self) -> bool:
        return self.semantic_pass_status is SemanticPassStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_mode": self.analysis_mode.value
            if isinstance(self.analysis_mode, AnalysisMode)
            else str(self.analysis_mode),
            "attributes": thaw_json(self.attributes),
            "cfg": self.cfg.to_dict(),
            "code_epoch": self.code_epoch.to_dict(),
            "diagnostics": list(self.diagnostics),
            "disassembly": self.disassembly.to_dict(),
            "proxy": self.proxy.to_dict(),
            "schema_version": self.schema_version,
            "semantic_pass_status": self.semantic_pass_status.value
            if isinstance(self.semantic_pass_status, SemanticPassStatus)
            else str(self.semantic_pass_status),
            "source_equivalence": self.source_equivalence.value
            if isinstance(self.source_equivalence, SourceEquivalenceStatus)
            else str(self.source_equivalence),
            "storage_effects": [item.to_dict() for item in self.storage_effects],
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


class EVMContractFrontend:
    """Acquire/normalize EVM contracts into Crypto IR-oriented records.

    Designed for offline fixtures by default.  An optional
    :class:`OfflineEVMProvider` may be injected; the frontend itself never
    opens sockets.
    """

    def __init__(
        self,
        *,
        provider: OfflineEVMProvider | None = None,
        max_bytecode_bytes: int = 24_576,
        max_instructions: int = 65_536,
    ) -> None:
        if (
            isinstance(max_bytecode_bytes, bool)
            or not isinstance(max_bytecode_bytes, int)
            or max_bytecode_bytes <= 0
        ):
            raise InvalidRequestError("max_bytecode_bytes must be a positive integer")
        if (
            isinstance(max_instructions, bool)
            or not isinstance(max_instructions, int)
            or max_instructions <= 0
        ):
            raise InvalidRequestError("max_instructions must be a positive integer")
        self._provider = provider
        self._max_bytecode_bytes = max_bytecode_bytes
        self._max_instructions = max_instructions

    @property
    def frontend_id(self) -> str:
        return FRONTEND_ID

    @property
    def version(self) -> str:
        return FRONTEND_VERSION

    @property
    def provider(self) -> OfflineEVMProvider | None:
        return self._provider

    def bind_code_epoch(
        self,
        *,
        chain_id: str,
        address: str,
        runtime_bytecode: bytes | str,
        block_number: int | None = None,
        code_epoch: str = "",
        creation_bytecode: bytes | str = b"",
        compiler: str = "",
        compiler_version: str = "",
        compiler_flags: Mapping[str, Any] | None = None,
        libraries: Mapping[str, str] | None = None,
        constructor_args: bytes | str = b"",
        metadata_policy: str = "embedded-cbor-ipfs-none",
        abi: bytes | str = b"",
        network: str = "",
        genesis_hash: str = "",
        attributes: Mapping[str, Any] | None = None,
    ) -> EVMCodeEpoch:
        """Bind chain/address/block/code epoch and build metadata to digests."""

        runtime = normalize_bytecode(runtime_bytecode)
        if len(runtime) > self._max_bytecode_bytes:
            raise ResourceLimitError("runtime bytecode exceeds max_bytecode_bytes")
        creation = normalize_bytecode(creation_bytecode) if creation_bytecode else b""
        if creation and len(creation) > self._max_bytecode_bytes:
            raise ResourceLimitError("creation bytecode exceeds max_bytecode_bytes")
        ctor = normalize_bytecode(constructor_args) if constructor_args else b""
        abi_bytes: bytes
        if isinstance(abi, bytes):
            abi_bytes = abi
        elif isinstance(abi, str) and abi:
            abi_bytes = abi.encode("utf-8")
        else:
            abi_bytes = b""

        runtime_digest = bytes_digest(runtime) if runtime else ""
        if not runtime_digest:
            raise InvalidRequestError("runtime bytecode is required for code epoch binding")
        epoch_label = code_epoch.strip() if code_epoch else f"code:{runtime_digest}"
        return EVMCodeEpoch(
            chain_id=chain_id,
            address=address,
            runtime_bytecode_digest=runtime_digest,
            block_number=block_number,
            code_epoch=epoch_label,
            creation_bytecode_digest=bytes_digest(creation) if creation else "",
            compiler=compiler,
            compiler_version=compiler_version,
            compiler_flags=dict(compiler_flags or {}),
            libraries=dict(libraries or {}),
            constructor_args_digest=bytes_digest(ctor) if ctor else "",
            metadata_policy=metadata_policy,
            abi_digest=bytes_digest(abi_bytes) if abi_bytes else "",
            network=network,
            genesis_hash=genesis_hash,
            attributes=dict(attributes or {}),
        )

    def reproduce_source_equivalence(
        self,
        source_manifest: SourceManifest,
        *,
        runtime: bytes | str | None = None,
        creation: bytes | str | None = None,
    ) -> SourceEquivalenceStatus:
        """Reproduce source/deployed equivalence; never trust provider claims alone.

        Returns:

        * ``REPRODUCED`` — declared digests match supplied bytecode
        * ``NOT_DECLARED`` — no digests declared on the manifest
        * ``MISMATCH`` — declared digests disagree with bytecode
        * ``UNAVAILABLE`` — bytecode not supplied for a declared binding
        """

        if not isinstance(source_manifest, SourceManifest):
            raise InvalidRequestError("source_manifest must be a SourceManifest")

        runtime_bytes = (
            normalize_bytecode(runtime) if runtime is not None else None
        )
        creation_bytes = (
            normalize_bytecode(creation) if creation is not None else None
        )

        has_declared = bool(
            source_manifest.runtime_bytecode_digest
            or source_manifest.creation_bytecode_digest
        )
        if not has_declared:
            return SourceEquivalenceStatus.NOT_DECLARED

        if runtime_bytes is None and creation_bytes is None:
            return SourceEquivalenceStatus.UNAVAILABLE

        try:
            source_manifest.assert_deployed_equivalence(
                creation=creation_bytes,
                runtime=runtime_bytes,
            )
        except ArtifactInconsistentError:
            return SourceEquivalenceStatus.MISMATCH
        return SourceEquivalenceStatus.REPRODUCED

    def analyze_runtime(
        self,
        runtime_bytecode: bytes | str,
        *,
        trace_complete: bool = False,
        claim_pass: bool = False,
    ) -> tuple[DisassemblyResult, ControlFlowGraph, tuple[StorageEffect, ...], SemanticPassStatus]:
        """Analyze deployed runtime independently of any source claim."""

        disasm, cfg, effects = analyze_bytecode(
            runtime_bytecode,
            max_bytes=self._max_bytecode_bytes,
            max_instructions=self._max_instructions,
            trace_complete=trace_complete,
        )
        status = incomplete_trace_never_passes(
            cfg=cfg,
            trace_complete=trace_complete,
            claim_pass=claim_pass,
        )
        # Even complete traces fail closed on unsupported opcodes.
        if cfg.unsupported_opcodes:
            status = SemanticPassStatus.UNSUPPORTED
        return disasm, cfg, effects, status

    def detect_proxy(
        self,
        *,
        address: str,
        runtime_bytecode: bytes | str,
        storage: Mapping[str, str] | None = None,
        previous_code_digest: str = "",
    ) -> ProxyBinding:
        """Classify proxy layout; unknown and selfdestruct cases stay explicit."""

        return detect_proxy_pattern(
            proxy_address=address,
            runtime_bytecode=runtime_bytecode,
            storage=storage,
            previous_code_digest=previous_code_digest,
        )

    def normalize_contract(
        self,
        *,
        chain_id: str,
        address: str,
        runtime_bytecode: bytes | str,
        block_number: int | None = None,
        code_epoch: str = "",
        creation_bytecode: bytes | str = b"",
        compiler: str = "",
        compiler_version: str = "",
        compiler_flags: Mapping[str, Any] | None = None,
        libraries: Mapping[str, str] | None = None,
        constructor_args: bytes | str = b"",
        metadata_policy: str = "embedded-cbor-ipfs-none",
        abi: bytes | str = b"",
        network: str = "",
        genesis_hash: str = "",
        storage: Mapping[str, str] | None = None,
        source_manifest: SourceManifest | None = None,
        previous_code_digest: str = "",
        trace_complete: bool = False,
        claim_semantic_pass: bool = False,
        attributes: Mapping[str, Any] | None = None,
    ) -> EVMNormalizationResult:
        """Full normalization: epoch binding, proxy, CFG, effects, source policy.

        When *source_manifest* is absent or equivalence cannot be reproduced,
        deployed runtime is analyzed independently
        (:attr:`AnalysisMode.RUNTIME_ONLY` /
        :attr:`SourceEquivalenceStatus.INDEPENDENT_RUNTIME`).
        """

        runtime = normalize_bytecode(runtime_bytecode)
        creation = normalize_bytecode(creation_bytecode) if creation_bytecode else b""

        epoch = self.bind_code_epoch(
            chain_id=chain_id,
            address=address,
            runtime_bytecode=runtime,
            block_number=block_number,
            code_epoch=code_epoch,
            creation_bytecode=creation,
            compiler=compiler,
            compiler_version=compiler_version,
            compiler_flags=compiler_flags,
            libraries=libraries,
            constructor_args=constructor_args,
            metadata_policy=metadata_policy,
            abi=abi,
            network=network,
            genesis_hash=genesis_hash,
            attributes=attributes,
        )

        proxy = self.detect_proxy(
            address=address,
            runtime_bytecode=runtime,
            storage=storage,
            previous_code_digest=previous_code_digest,
        )

        disasm, cfg, effects, semantic_status = self.analyze_runtime(
            runtime,
            trace_complete=trace_complete,
            claim_pass=claim_semantic_pass,
        )

        diagnostics: list[str] = list(cfg.diagnostics)
        diagnostics.extend(proxy.diagnostics)

        # Source equivalence policy.
        if source_manifest is None:
            source_status = SourceEquivalenceStatus.INDEPENDENT_RUNTIME
            analysis_mode = AnalysisMode.RUNTIME_ONLY
            diagnostics.append(
                "no source manifest; analyzing deployed runtime independently"
            )
        else:
            source_status = self.reproduce_source_equivalence(
                source_manifest,
                runtime=runtime,
                creation=creation if creation else None,
            )
            if source_status is SourceEquivalenceStatus.REPRODUCED:
                analysis_mode = AnalysisMode.SOURCE_AND_RUNTIME
                diagnostics.append("source/deployed equivalence reproduced by digest match")
            elif source_status is SourceEquivalenceStatus.MISMATCH:
                analysis_mode = AnalysisMode.RUNTIME_ONLY
                source_status = SourceEquivalenceStatus.INDEPENDENT_RUNTIME
                diagnostics.append(
                    "source claim failed reproduction; analyzing runtime independently"
                )
            elif source_status is SourceEquivalenceStatus.NOT_DECLARED:
                analysis_mode = AnalysisMode.SOURCE_EVIDENCE_ONLY
                diagnostics.append(
                    "source present without declared deployment digests; evidence only"
                )
            else:
                analysis_mode = AnalysisMode.RUNTIME_ONLY
                diagnostics.append(
                    "source binding unavailable; analyzing runtime independently"
                )

        # Static-only CFG pass: allowed only when caller claims static_cfg and
        # the CFG itself has pass status with no unsupported ops.
        attrs = dict(attributes or {})
        if claim_semantic_pass and trace_complete and semantic_status is SemanticPassStatus.PASS:
            attrs["trace_complete"] = True
        elif (
            claim_semantic_pass
            and not trace_complete
            and cfg.pass_status is SemanticPassStatus.PASS
            and not cfg.unsupported_opcodes
            and not cfg.unresolved_jumps
        ):
            # Reinterpret as static CFG-only pass (not execution-trace pass).
            semantic_status = SemanticPassStatus.PASS
            attrs["static_cfg_only"] = True
            attrs["trace_complete"] = False
            diagnostics.append(
                "static CFG pass only; execution-trace pass not claimed"
            )
        elif claim_semantic_pass:
            if semantic_status is SemanticPassStatus.PASS:
                semantic_status = SemanticPassStatus.FAIL_CLOSED
            diagnostics.append("semantic pass claim rejected by fail-closed gate")
            attrs["trace_complete"] = trace_complete
        else:
            attrs["trace_complete"] = trace_complete
            # Default: never advertise PASS without an explicit claim.
            if semantic_status is SemanticPassStatus.PASS:
                semantic_status = SemanticPassStatus.INCOMPLETE
                attrs["static_cfg_only"] = True

        # Proxy unknown / selfdestruct always surface in diagnostics (already).
        if proxy.kind is ProxyKind.UNKNOWN:
            diagnostics.append("proxy layout is unknown; implementation not trusted")
        if proxy.redeployment_risk is RedeploymentRisk.SELFDESTRUCT_PRESENT:
            diagnostics.append("selfdestruct/redeployment risk remains explicit")
        if proxy.redeployment_risk is RedeploymentRisk.CODE_EPOCH_CHANGED:
            diagnostics.append("code epoch change / redeployment observed")

        return EVMNormalizationResult(
            code_epoch=epoch,
            proxy=proxy,
            disassembly=disasm,
            cfg=cfg,
            storage_effects=effects,
            source_equivalence=source_status,
            analysis_mode=analysis_mode,
            semantic_pass_status=semantic_status,
            diagnostics=tuple(dict.fromkeys(diagnostics)),
            attributes=attrs,
        )

    def normalize_fixture(
        self,
        fixture: EVMContractFixture,
        *,
        source_manifest: SourceManifest | None = None,
        previous_code_digest: str = "",
        network: str = "",
        genesis_hash: str = "",
        trace_complete: bool = False,
        claim_semantic_pass: bool = False,
    ) -> EVMNormalizationResult:
        """Normalize an offline fixture (golden bytecode path)."""

        if not isinstance(fixture, EVMContractFixture):
            raise InvalidRequestError("fixture must be an EVMContractFixture")
        if not fixture.runtime_bytecode:
            raise InvalidRequestError("fixture runtime_bytecode is required")

        # Optionally build a source manifest from fixture compiler pins when
        # sources and digests are both present and no external manifest given.
        manifest = source_manifest
        if manifest is None and fixture.source_files and fixture.compiler:
            # Source is evidence only unless caller supplies expected digests
            # via a SourceManifest; we do not invent reproduction claims.
            pass

        return self.normalize_contract(
            chain_id=fixture.chain_id,
            address=fixture.address,
            runtime_bytecode=fixture.runtime_bytecode,
            block_number=fixture.block_number,
            code_epoch=fixture.code_epoch,
            creation_bytecode=fixture.creation_bytecode,
            compiler=fixture.compiler,
            compiler_version=fixture.compiler_version,
            compiler_flags=dict(fixture.compiler_flags),
            libraries=dict(fixture.libraries),
            constructor_args=fixture.constructor_args,
            metadata_policy=fixture.metadata_policy,
            abi=fixture.abi_json,
            network=network,
            genesis_hash=genesis_hash,
            storage=dict(fixture.storage),
            source_manifest=manifest,
            previous_code_digest=previous_code_digest,
            trace_complete=trace_complete,
            claim_semantic_pass=claim_semantic_pass,
            attributes=dict(fixture.attributes),
        )

    def build_source_manifest(
        self,
        *,
        request_id: str,
        sources: Mapping[str, bytes],
        compiler: str,
        compiler_version: str,
        settings: Mapping[str, Any] | None = None,
        libraries: Mapping[str, str] | None = None,
        runtime_bytecode: bytes | str = b"",
        creation_bytecode: bytes | str = b"",
        constructor_args: bytes | str = b"",
        metadata_policy: str = "embedded-cbor-ipfs-none",
        code_epoch: str = "",
        observed_at: datetime | None = None,
    ) -> SourceManifest:
        """Build a reproducible source manifest binding expected deployment digests."""

        from ..source import SourceFileRecord

        files = tuple(
            SourceFileRecord.from_bytes(path, payload, language="solidity")
            for path, payload in sorted(sources.items())
        )
        toolchain = ToolchainPin(
            compiler=compiler,
            compiler_version=compiler_version,
            settings=dict(settings or {}),
            libraries={
                name: normalize_address(addr)
                for name, addr in dict(libraries or {}).items()
            },
            target="evm",
        )
        runtime = normalize_bytecode(runtime_bytecode) if runtime_bytecode else b""
        creation = normalize_bytecode(creation_bytecode) if creation_bytecode else b""
        ctor = normalize_bytecode(constructor_args) if constructor_args else b""
        return SourceManifest(
            files=files,
            toolchain=toolchain,
            request_id=request_id,
            observed_at=observed_at or datetime.now(timezone.utc),
            creation_bytecode_digest=bytes_digest(creation) if creation else "",
            runtime_bytecode_digest=bytes_digest(runtime) if runtime else "",
            constructor_args_digest=bytes_digest(ctor) if ctor else "",
            metadata_policy=metadata_policy,
            code_epoch=code_epoch,
        )


__all__ = [
    "FRONTEND_ID",
    "FRONTEND_SCHEMA_VERSION",
    "FRONTEND_VERSION",
    "AnalysisMode",
    "EVMCodeEpoch",
    "EVMContractFrontend",
    "EVMNormalizationResult",
    "SourceEquivalenceStatus",
]
