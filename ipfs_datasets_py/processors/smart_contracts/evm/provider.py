"""Offline-first EVM artifact provider (CRYPTOIR-G220).

Fixture-backed acquisition of runtime/creation bytecode, ABI, source, and
metadata.  Live network clients are never constructed by import.  Acquisition
is read-only and separately injectable from parse/analyze.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any

from ..artifacts import (
    ArtifactManifest,
    StoredArtifact,
    TransportEvidence,
    bytes_digest,
)
from ..canonical import freeze_json, thaw_json
from ..errors import (
    InvalidRequestError,
    ProviderError,
    ResourceLimitError,
    SigningForbiddenError,
)
from ..models import (
    AcquisitionStatus,
    ArtifactKind,
    ArtifactRef,
    ContractAcquisitionRequest,
    ContractAcquisitionResult,
    ensure_secret_safe,
)
from ..protocols import (
    Capabilities,
    Capability,
    OperationContext,
)
from .proxies import normalize_address


PROVIDER_SCHEMA_VERSION = "smart-contract-evm-provider-v1"
EVM_PROVIDER_ID = "smart-contracts.evm.offline"


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must not be empty")
    if value != value.strip():
        raise InvalidRequestError(f"{name} must not have surrounding whitespace")
    return value


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    frozen = freeze_json(dict(value or {}))
    if not isinstance(frozen, Mapping):
        raise InvalidRequestError("attributes must be a mapping")
    ensure_secret_safe(frozen)
    return frozen


def _kind_media_type(kind: ArtifactKind) -> str:
    if kind in {ArtifactKind.BYTECODE, ArtifactKind.CREATION_BYTECODE}:
        return "application/octet-stream"
    if kind is ArtifactKind.ABI:
        return "application/json"
    if kind is ArtifactKind.SOURCE:
        return "text/plain"
    if kind is ArtifactKind.METADATA:
        return "application/json"
    if kind is ArtifactKind.BUILD_MANIFEST:
        return "application/json"
    if kind is ArtifactKind.STATE_SNAPSHOT:
        return "application/json"
    return "application/octet-stream"


@dataclass(frozen=True, slots=True)
class EVMContractFixture:
    """One offline contract fixture keyed by chain + address + optional block."""

    chain_id: str
    address: str
    runtime_bytecode: bytes = b""
    creation_bytecode: bytes = b""
    abi_json: bytes = b""
    source_files: Mapping[str, bytes] = field(default_factory=dict)
    metadata_json: bytes = b""
    storage: Mapping[str, str] = field(default_factory=dict)
    block_number: int | None = None
    code_epoch: str = ""
    compiler: str = ""
    compiler_version: str = ""
    compiler_flags: Mapping[str, Any] = field(default_factory=dict)
    libraries: Mapping[str, str] = field(default_factory=dict)
    constructor_args: bytes = b""
    metadata_policy: str = "embedded-cbor-ipfs-none"
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "chain_id", _required_text(self.chain_id, "chain_id"))
        object.__setattr__(self, "address", normalize_address(self.address))
        for name in (
            "runtime_bytecode",
            "creation_bytecode",
            "abi_json",
            "metadata_json",
            "constructor_args",
        ):
            raw = getattr(self, name)
            if type(raw) is not bytes:
                raise InvalidRequestError(f"{name} must be exact bytes")
        sources = {
            _required_text(path, "source path"): payload
            for path, payload in dict(self.source_files).items()
        }
        for path, payload in sources.items():
            if type(payload) is not bytes:
                raise InvalidRequestError(f"source_files[{path}] must be exact bytes")
            if path.startswith("/") or ".." in path.split("/"):
                raise InvalidRequestError("source path must be relative without traversal")
        object.__setattr__(self, "source_files", MappingProxyType(sources))
        storage = {
            _required_text(k, "storage key"): _required_text(v, "storage value")
            for k, v in dict(self.storage).items()
        }
        object.__setattr__(self, "storage", MappingProxyType(storage))
        if self.block_number is not None:
            if (
                isinstance(self.block_number, bool)
                or not isinstance(self.block_number, int)
                or self.block_number < 0
            ):
                raise InvalidRequestError("block_number must be a non-negative integer")
        object.__setattr__(
            self, "code_epoch", self.code_epoch.strip() if self.code_epoch else ""
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
            "metadata_policy",
            _required_text(self.metadata_policy, "metadata_policy"),
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        ensure_secret_safe(self.to_dict())

    @property
    def fixture_key(self) -> str:
        block = "" if self.block_number is None else str(self.block_number)
        return f"{self.chain_id}:{self.address}:{block}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "attributes": thaw_json(self.attributes),
            "block_number": self.block_number,
            "chain_id": self.chain_id,
            "code_epoch": self.code_epoch,
            "compiler": self.compiler,
            "compiler_flags": thaw_json(self.compiler_flags),
            "compiler_version": self.compiler_version,
            "constructor_args_digest": bytes_digest(self.constructor_args)
            if self.constructor_args
            else "",
            "creation_bytecode_digest": bytes_digest(self.creation_bytecode)
            if self.creation_bytecode
            else "",
            "libraries": dict(self.libraries),
            "metadata_digest": bytes_digest(self.metadata_json)
            if self.metadata_json
            else "",
            "metadata_policy": self.metadata_policy,
            "runtime_bytecode_digest": bytes_digest(self.runtime_bytecode)
            if self.runtime_bytecode
            else "",
            "source_digests": {
                path: bytes_digest(payload)
                for path, payload in self.source_files.items()
            },
            "storage": dict(self.storage),
        }

    def artifact_for(self, kind: ArtifactKind) -> StoredArtifact | None:
        """Return stored bytes for *kind*, or ``None`` when unavailable."""

        if kind is ArtifactKind.BYTECODE:
            if not self.runtime_bytecode:
                return None
            return StoredArtifact(
                raw_bytes=self.runtime_bytecode,
                kind=ArtifactKind.BYTECODE,
                media_type=_kind_media_type(kind),
                label="runtime",
            )
        if kind is ArtifactKind.CREATION_BYTECODE:
            if not self.creation_bytecode:
                return None
            return StoredArtifact(
                raw_bytes=self.creation_bytecode,
                kind=ArtifactKind.CREATION_BYTECODE,
                media_type=_kind_media_type(kind),
                label="creation",
            )
        if kind is ArtifactKind.ABI:
            if not self.abi_json:
                return None
            return StoredArtifact(
                raw_bytes=self.abi_json,
                kind=ArtifactKind.ABI,
                media_type=_kind_media_type(kind),
                label="abi",
            )
        if kind is ArtifactKind.METADATA:
            if not self.metadata_json:
                return None
            return StoredArtifact(
                raw_bytes=self.metadata_json,
                kind=ArtifactKind.METADATA,
                media_type=_kind_media_type(kind),
                label="metadata",
            )
        if kind is ArtifactKind.SOURCE:
            # Multi-file sources are returned as a single concatenated manifest
            # payload only when exactly one file is present; otherwise callers
            # use list_source_artifacts.
            if len(self.source_files) == 1:
                path, payload = next(iter(self.source_files.items()))
                return StoredArtifact(
                    raw_bytes=payload,
                    kind=ArtifactKind.SOURCE,
                    media_type=_kind_media_type(kind),
                    label=path,
                )
            return None
        if kind is ArtifactKind.STATE_SNAPSHOT:
            if not self.storage:
                return None
            import json

            payload = json.dumps(dict(self.storage), sort_keys=True).encode("utf-8")
            return StoredArtifact(
                raw_bytes=payload,
                kind=ArtifactKind.STATE_SNAPSHOT,
                media_type=_kind_media_type(kind),
                label="storage",
            )
        return None

    def list_source_artifacts(self) -> tuple[tuple[str, StoredArtifact], ...]:
        return tuple(
            (
                path,
                StoredArtifact(
                    raw_bytes=payload,
                    kind=ArtifactKind.SOURCE,
                    media_type="text/plain",
                    label=path,
                ),
            )
            for path, payload in sorted(self.source_files.items())
        )


class OfflineEVMProvider:
    """Bounded, fixture-only :class:`~..protocols.ArtifactProvider` for EVM.

    Locators accepted:

    * ``evm://{chain_id}/{address}``
    * ``evm://{chain_id}/{address}@{block}``
    * bare ``0x`` address (requires ``chain.chain_id`` on the request)
    """

    def __init__(
        self,
        fixtures: Sequence[EVMContractFixture] = (),
        *,
        provider_id: str = EVM_PROVIDER_ID,
    ) -> None:
        self._provider_id = _required_text(provider_id, "provider_id")
        index: dict[str, EVMContractFixture] = {}
        for fixture in fixtures:
            if not isinstance(fixture, EVMContractFixture):
                raise InvalidRequestError("fixtures must be EVMContractFixture instances")
            keys = {
                f"{fixture.chain_id}:{fixture.address}",
                fixture.fixture_key,
            }
            if fixture.block_number is not None:
                keys.add(
                    f"{fixture.chain_id}:{fixture.address}@{fixture.block_number}"
                )
            for key in keys:
                if key in index and index[key] is not fixture:
                    raise InvalidRequestError(f"duplicate EVM fixture key: {key}")
                index[key] = fixture
        self._fixtures: Mapping[str, EVMContractFixture] = MappingProxyType(index)
        self._capabilities = Capabilities(
            provider=self._provider_id,
            chain_namespaces=frozenset({"eip155", "evm"}),
            features=frozenset(
                {
                    Capability.ACQUIRE_BYTECODE,
                    Capability.ACQUIRE_CREATION_BYTECODE,
                    Capability.ACQUIRE_SOURCE,
                    Capability.ACQUIRE_ABI,
                    Capability.ACQUIRE_METADATA,
                    Capability.ACQUIRE_STATE_SNAPSHOT,
                    Capability.CAPABILITY_DISCOVERY,
                    Capability.CODE_EPOCH,
                }
            ),
            metadata={
                "offline": True,
                "schema_version": PROVIDER_SCHEMA_VERSION,
                "fixture_count": len(fixtures),
            },
        )

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def register_fixture(self, fixture: EVMContractFixture) -> None:
        """Register an additional fixture (mutates the provider index)."""

        if not isinstance(fixture, EVMContractFixture):
            raise InvalidRequestError("fixture must be an EVMContractFixture")
        # Replace MappingProxy with a mutable copy then re-freeze.
        current: MutableMapping[str, EVMContractFixture] = dict(self._fixtures)
        keys = {
            f"{fixture.chain_id}:{fixture.address}",
            fixture.fixture_key,
        }
        if fixture.block_number is not None:
            keys.add(f"{fixture.chain_id}:{fixture.address}@{fixture.block_number}")
        for key in keys:
            current[key] = fixture
        self._fixtures = MappingProxyType(current)

    def get_fixture(
        self,
        *,
        chain_id: str,
        address: str,
        block_number: int | None = None,
    ) -> EVMContractFixture | None:
        address = normalize_address(address)
        chain_id = _required_text(chain_id, "chain_id")
        if block_number is not None:
            key = f"{chain_id}:{address}@{block_number}"
            if key in self._fixtures:
                return self._fixtures[key]
        return self._fixtures.get(f"{chain_id}:{address}")

    def parse_locator(
        self,
        locator: str,
        *,
        chain_id: str = "",
    ) -> tuple[str, str, int | None]:
        """Return ``(chain_id, address, block_number)`` from a locator string."""

        text = _required_text(locator, "locator")
        block: int | None = None
        if text.startswith("evm://"):
            rest = text[len("evm://") :]
            parts = rest.split("/", 1)
            if len(parts) != 2:
                raise InvalidRequestError("evm locator must be evm://{chain_id}/{address}")
            chain_part, addr_part = parts
            if "@" in addr_part:
                addr_part, block_s = addr_part.rsplit("@", 1)
                if not block_s.isdigit():
                    raise InvalidRequestError("block number must be decimal digits")
                block = int(block_s)
            return _required_text(chain_part, "chain_id"), normalize_address(addr_part), block
        if text.startswith(("0x", "0X")):
            if not chain_id:
                raise InvalidRequestError(
                    "bare address locator requires request chain_id"
                )
            return _required_text(chain_id, "chain_id"), normalize_address(text), None
        raise InvalidRequestError("unsupported EVM locator form")

    async def acquire(
        self,
        request: ContractAcquisitionRequest,
        *,
        context: OperationContext,
    ) -> ContractAcquisitionResult:
        """Acquire a single artifact kind from offline fixtures."""

        context.check_active()
        if request.provider_policy.allowed_providers and not (
            request.provider_policy.permits_provider(self._provider_id)
        ):
            return ContractAcquisitionResult(
                request_id=request.request_id,
                status=AcquisitionStatus.UNSUPPORTED,
                diagnostics=(
                    f"provider {self._provider_id!r} is not allowlisted",
                ),
            )

        # Reject signing surfaces even if they leak into attributes.
        try:
            ensure_secret_safe(request.to_dict())
        except SigningForbiddenError:
            raise
        except Exception as exc:
            raise InvalidRequestError(str(exc)) from exc

        chain_id = request.chain.chain_id or request.chain.namespace or ""
        try:
            parsed_chain, address, block = self.parse_locator(
                request.locator, chain_id=chain_id
            )
        except InvalidRequestError as exc:
            return ContractAcquisitionResult(
                request_id=request.request_id,
                status=AcquisitionStatus.ERROR,
                diagnostics=(str(exc),),
            )

        fixture = self.get_fixture(
            chain_id=parsed_chain, address=address, block_number=block
        )
        if fixture is None:
            return ContractAcquisitionResult(
                request_id=request.request_id,
                status=AcquisitionStatus.UNAVAILABLE,
                diagnostics=(
                    f"no offline fixture for {parsed_chain}:{address}",
                ),
            )

        kind = (
            request.artifact_kind
            if isinstance(request.artifact_kind, ArtifactKind)
            else ArtifactKind(str(request.artifact_kind))
        )

        stored_entries: list[tuple[str, StoredArtifact]] = []
        if kind is ArtifactKind.SOURCE and len(fixture.source_files) > 1:
            stored_entries.extend(fixture.list_source_artifacts())
        else:
            artifact = fixture.artifact_for(kind)
            if artifact is None:
                return ContractAcquisitionResult(
                    request_id=request.request_id,
                    status=AcquisitionStatus.UNAVAILABLE,
                    diagnostics=(f"fixture lacks artifact kind {kind.value}",),
                    coverage_notes=(f"{self._provider_id}:partial_fixture",),
                )
            path = artifact.label or kind.value
            stored_entries.append((path, artifact))

        # Enforce response byte budget.
        total_bytes = sum(item.byte_length for _, item in stored_entries)
        if total_bytes > request.bounds.max_response_bytes:
            raise ResourceLimitError("fixture payload exceeds max_response_bytes")
        if len(stored_entries) > request.bounds.max_items:
            raise ResourceLimitError("fixture item count exceeds max_items")

        now = datetime.now(timezone.utc)
        evidence = TransportEvidence(
            request_digest=bytes_digest(
                f"{request.request_id}:{request.locator}:{kind.value}".encode("utf-8")
            ),
            response_digest=bytes_digest(
                b"".join(item.raw_bytes for _, item in stored_entries)
            ),
            final_url_digest=bytes_digest(
                f"offline://{self._provider_id}/{parsed_chain}/{address}".encode("utf-8")
            ),
            status_code=200,
            byte_length=total_bytes,
            transport="offline_fixture",
            attributes={
                "block_number": fixture.block_number,
                "code_epoch": fixture.code_epoch or request.code_epoch,
            },
        )
        manifest = ArtifactManifest.from_stored(
            stored_entries,
            request_id=request.request_id,
            observed_at=now,
            transport_evidence=(evidence,),
            provider_ids=(self._provider_id,),
            code_epoch=fixture.code_epoch or request.code_epoch,
            attributes={
                "address": fixture.address,
                "chain_id": fixture.chain_id,
                "compiler": fixture.compiler,
                "compiler_version": fixture.compiler_version,
                "libraries": dict(fixture.libraries),
                "metadata_policy": fixture.metadata_policy,
            },
        )
        refs: tuple[ArtifactRef, ...] = manifest.artifact_refs()
        from ..models import AcquisitionProvenance

        provenance = AcquisitionProvenance(
            provider_id=self._provider_id,
            transport="offline_fixture",
            observed_at=now,
            request_digest=evidence.request_digest,
            response_digest=evidence.response_digest,
            endpoint_id=evidence.final_url_digest,
            attributes={"status_code": 200},
        )
        return ContractAcquisitionResult(
            request_id=request.request_id,
            status=AcquisitionStatus.AVAILABLE,
            artifacts=refs,
            provenances=(provenance,),
            coverage_notes=(f"{self._provider_id}:offline_fixture",),
            attributes={
                "address": fixture.address,
                "block_number": fixture.block_number,
                "chain_id": fixture.chain_id,
                "code_epoch": fixture.code_epoch,
                "compiler": fixture.compiler,
                "compiler_flags": thaw_json(fixture.compiler_flags),
                "compiler_version": fixture.compiler_version,
                "libraries": dict(fixture.libraries),
                "manifest_digest": manifest.manifest_digest,
                "metadata_policy": fixture.metadata_policy,
            },
        )


# Alias matching the predicted public name.
EVMArtifactProvider = OfflineEVMProvider


__all__ = [
    "EVM_PROVIDER_ID",
    "PROVIDER_SCHEMA_VERSION",
    "EVMArtifactProvider",
    "EVMContractFixture",
    "OfflineEVMProvider",
]
