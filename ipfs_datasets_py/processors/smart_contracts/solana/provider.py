"""Offline-first Solana program artifact provider (CRYPTOIR-G230).

Fixture-backed acquisition of SBF ELF, program/program-data accounts, IDL,
source, build manifests, and loader state.  Live network clients are never
constructed by import.  Acquisition is read-only and separately injectable
from parse/analyze.
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
from .loader import (
    BPF_LOADER_UPGRADEABLE,
    LoaderVersion,
    UpgradeAuthorityState,
    bind_program_relation,
    bind_upgrade_authority,
    classify_loader,
    normalize_pubkey,
)
from .semantics import normalize_elf_bytes


PROVIDER_SCHEMA_VERSION = "smart-contract-solana-provider-v1"
SOLANA_PROVIDER_ID = "smart-contracts.solana.offline"


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
    if kind in {ArtifactKind.PROGRAM, ArtifactKind.BYTECODE}:
        return "application/octet-stream"
    if kind is ArtifactKind.IDL:
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
class SolanaProgramFixture:
    """One offline Solana program fixture keyed by cluster + program id + slot."""

    chain_id: str
    program_id: str
    sbf_elf: bytes = b""
    idl_json: bytes = b""
    source_files: Mapping[str, bytes] = field(default_factory=dict)
    build_manifest_json: bytes = b""
    metadata_json: bytes = b""
    loader_program_id: str = BPF_LOADER_UPGRADEABLE
    program_data_address: str = ""
    upgrade_authority: str | None = None
    deployment_slot: int | None = None
    code_epoch: str = ""
    compiler: str = ""
    compiler_version: str = ""
    compiler_flags: Mapping[str, Any] = field(default_factory=dict)
    account_owners: Mapping[str, str] = field(default_factory=dict)
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "chain_id", _required_text(self.chain_id, "chain_id"))
        object.__setattr__(
            self, "program_id", normalize_pubkey(self.program_id, field="program_id")
        )
        for name in (
            "sbf_elf",
            "idl_json",
            "build_manifest_json",
            "metadata_json",
        ):
            raw = getattr(self, name)
            if type(raw) is not bytes:
                raise InvalidRequestError(f"{name} must be exact bytes")
        # Normalize ELF from accidental hex strings is not needed (bytes only).
        sources = {
            _required_text(path, "source path"): payload
            for path, payload in dict(self.source_files).items()
        }
        for path, payload in sources.items():
            if type(payload) is not bytes:
                raise InvalidRequestError(f"source_files[{path}] must be exact bytes")
            if path.startswith("/") or ".." in path.split("/"):
                raise InvalidRequestError(
                    "source path must be relative without traversal"
                )
        object.__setattr__(self, "source_files", MappingProxyType(sources))
        object.__setattr__(
            self,
            "loader_program_id",
            normalize_pubkey(self.loader_program_id, field="loader_program_id"),
        )
        if self.program_data_address:
            object.__setattr__(
                self,
                "program_data_address",
                normalize_pubkey(
                    self.program_data_address, field="program_data_address"
                ),
            )
        else:
            object.__setattr__(self, "program_data_address", "")
        # upgrade_authority: None = unknown, "" = immutable, pubkey = set
        if self.upgrade_authority is not None and self.upgrade_authority != "":
            object.__setattr__(
                self,
                "upgrade_authority",
                normalize_pubkey(
                    self.upgrade_authority, field="upgrade_authority"
                ),
            )
        if self.deployment_slot is not None:
            if (
                isinstance(self.deployment_slot, bool)
                or not isinstance(self.deployment_slot, int)
                or self.deployment_slot < 0
            ):
                raise InvalidRequestError(
                    "deployment_slot must be a non-negative integer"
                )
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
        owners = {
            normalize_pubkey(k, field="account"): normalize_pubkey(v, field="owner")
            for k, v in dict(self.account_owners).items()
        }
        object.__setattr__(self, "account_owners", MappingProxyType(owners))
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        ensure_secret_safe(self.to_dict())

    @property
    def fixture_key(self) -> str:
        slot = "" if self.deployment_slot is None else str(self.deployment_slot)
        return f"{self.chain_id}:{self.program_id}:{slot}"

    @property
    def loader_version(self) -> LoaderVersion:
        return classify_loader(self.loader_program_id)

    @property
    def sbf_elf_digest(self) -> str:
        return bytes_digest(self.sbf_elf) if self.sbf_elf else ""

    def program_relation(self):
        return bind_program_relation(
            program_id=self.program_id,
            loader_program_id=self.loader_program_id,
            program_data_address=self.program_data_address,
            sbf_elf=self.sbf_elf,
            deployment_slot=self.deployment_slot,
        )

    def upgrade_authority_record(self):
        return bind_upgrade_authority(
            authority_pubkey=self.upgrade_authority,
            program_data_address=self.program_data_address,
            slot_observed=self.deployment_slot,
            loader_version=self.loader_version,
        )

    def artifact_for(self, kind: ArtifactKind) -> StoredArtifact | None:
        """Return stored bytes for *kind*, or ``None`` when unavailable."""

        if kind in {ArtifactKind.PROGRAM, ArtifactKind.BYTECODE}:
            if not self.sbf_elf:
                return None
            return StoredArtifact(
                raw_bytes=self.sbf_elf,
                kind=ArtifactKind.PROGRAM if kind is ArtifactKind.PROGRAM else kind,
                media_type=_kind_media_type(ArtifactKind.PROGRAM),
                label="sbf_elf",
            )
        if kind is ArtifactKind.IDL:
            if not self.idl_json:
                return None
            return StoredArtifact(
                raw_bytes=self.idl_json,
                kind=ArtifactKind.IDL,
                media_type=_kind_media_type(kind),
                label="idl",
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
        if kind is ArtifactKind.BUILD_MANIFEST:
            if not self.build_manifest_json:
                return None
            return StoredArtifact(
                raw_bytes=self.build_manifest_json,
                kind=ArtifactKind.BUILD_MANIFEST,
                media_type=_kind_media_type(kind),
                label="build_manifest",
            )
        if kind is ArtifactKind.SOURCE:
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
            import json

            payload_obj = {
                "account_owners": dict(self.account_owners),
                "deployment_slot": self.deployment_slot,
                "loader_program_id": self.loader_program_id,
                "program_data_address": self.program_data_address,
                "upgrade_authority": self.upgrade_authority
                if self.upgrade_authority is not None
                else None,
            }
            payload = json.dumps(payload_obj, sort_keys=True).encode("utf-8")
            return StoredArtifact(
                raw_bytes=payload,
                kind=ArtifactKind.STATE_SNAPSHOT,
                media_type=_kind_media_type(kind),
                label="loader_state",
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_owners": dict(self.account_owners),
            "attributes": thaw_json(self.attributes),
            "build_manifest_digest": bytes_digest(self.build_manifest_json)
            if self.build_manifest_json
            else "",
            "chain_id": self.chain_id,
            "code_epoch": self.code_epoch,
            "compiler": self.compiler,
            "compiler_flags": thaw_json(self.compiler_flags),
            "compiler_version": self.compiler_version,
            "deployment_slot": self.deployment_slot,
            "idl_digest": bytes_digest(self.idl_json) if self.idl_json else "",
            "loader_program_id": self.loader_program_id,
            "metadata_digest": bytes_digest(self.metadata_json)
            if self.metadata_json
            else "",
            "program_data_address": self.program_data_address,
            "program_id": self.program_id,
            "sbf_elf_digest": self.sbf_elf_digest,
            "source_digests": {
                path: bytes_digest(payload)
                for path, payload in self.source_files.items()
            },
            "upgrade_authority": self.upgrade_authority,
        }


class OfflineSolanaProvider:
    """Bounded, fixture-only :class:`~..protocols.ArtifactProvider` for Solana.

    Locators accepted:

    * ``solana://{chain_id}/{program_id}``
    * ``solana://{chain_id}/{program_id}@{slot}``
    * bare base58 program id (requires ``chain.chain_id`` on the request)
    """

    def __init__(
        self,
        fixtures: Sequence[SolanaProgramFixture] = (),
        *,
        provider_id: str = SOLANA_PROVIDER_ID,
    ) -> None:
        self._provider_id = _required_text(provider_id, "provider_id")
        index: dict[str, SolanaProgramFixture] = {}
        for fixture in fixtures:
            if not isinstance(fixture, SolanaProgramFixture):
                raise InvalidRequestError(
                    "fixtures must be SolanaProgramFixture instances"
                )
            keys = {
                f"{fixture.chain_id}:{fixture.program_id}",
                fixture.fixture_key,
            }
            if fixture.deployment_slot is not None:
                keys.add(
                    f"{fixture.chain_id}:{fixture.program_id}@{fixture.deployment_slot}"
                )
            for key in keys:
                if key in index and index[key] is not fixture:
                    raise InvalidRequestError(f"duplicate Solana fixture key: {key}")
                index[key] = fixture
        self._fixtures: Mapping[str, SolanaProgramFixture] = MappingProxyType(index)
        self._capabilities = Capabilities(
            provider=self._provider_id,
            chain_namespaces=frozenset({"solana"}),
            features=frozenset(
                {
                    Capability.ACQUIRE_PROGRAM,
                    Capability.ACQUIRE_BYTECODE,
                    Capability.ACQUIRE_SOURCE,
                    Capability.ACQUIRE_IDL,
                    Capability.ACQUIRE_METADATA,
                    Capability.ACQUIRE_BUILD_MANIFEST,
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

    def register_fixture(self, fixture: SolanaProgramFixture) -> None:
        """Register an additional fixture (mutates the provider index)."""

        if not isinstance(fixture, SolanaProgramFixture):
            raise InvalidRequestError("fixture must be a SolanaProgramFixture")
        current: MutableMapping[str, SolanaProgramFixture] = dict(self._fixtures)
        keys = {
            f"{fixture.chain_id}:{fixture.program_id}",
            fixture.fixture_key,
        }
        if fixture.deployment_slot is not None:
            keys.add(
                f"{fixture.chain_id}:{fixture.program_id}@{fixture.deployment_slot}"
            )
        for key in keys:
            current[key] = fixture
        self._fixtures = MappingProxyType(current)

    def get_fixture(
        self,
        *,
        chain_id: str,
        program_id: str,
        deployment_slot: int | None = None,
    ) -> SolanaProgramFixture | None:
        program_id = normalize_pubkey(program_id, field="program_id")
        chain_id = _required_text(chain_id, "chain_id")
        if deployment_slot is not None:
            key = f"{chain_id}:{program_id}@{deployment_slot}"
            if key in self._fixtures:
                return self._fixtures[key]
        return self._fixtures.get(f"{chain_id}:{program_id}")

    def parse_locator(
        self,
        locator: str,
        *,
        chain_id: str = "",
    ) -> tuple[str, str, int | None]:
        """Return ``(chain_id, program_id, deployment_slot)`` from a locator."""

        text = _required_text(locator, "locator")
        slot: int | None = None
        if text.startswith("solana://"):
            rest = text[len("solana://") :]
            parts = rest.split("/", 1)
            if len(parts) != 2:
                raise InvalidRequestError(
                    "solana locator must be solana://{chain_id}/{program_id}"
                )
            chain_part, prog_part = parts
            if "@" in prog_part:
                prog_part, slot_s = prog_part.rsplit("@", 1)
                if not slot_s.isdigit():
                    raise InvalidRequestError("slot must be decimal digits")
                slot = int(slot_s)
            return (
                _required_text(chain_part, "chain_id"),
                normalize_pubkey(prog_part, field="program_id"),
                slot,
            )
        # Bare base58 program id.
        try:
            program_id = normalize_pubkey(text, field="program_id")
        except InvalidRequestError as exc:
            raise InvalidRequestError("unsupported Solana locator form") from exc
        if not chain_id:
            raise InvalidRequestError(
                "bare program id locator requires request chain_id"
            )
        return _required_text(chain_id, "chain_id"), program_id, None

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

        try:
            ensure_secret_safe(request.to_dict())
        except SigningForbiddenError:
            raise
        except Exception as exc:
            raise InvalidRequestError(str(exc)) from exc

        chain_id = request.chain.chain_id or request.chain.network or ""
        try:
            parsed_chain, program_id, slot = self.parse_locator(
                request.locator, chain_id=chain_id
            )
        except InvalidRequestError as exc:
            return ContractAcquisitionResult(
                request_id=request.request_id,
                status=AcquisitionStatus.ERROR,
                diagnostics=(str(exc),),
            )

        fixture = self.get_fixture(
            chain_id=parsed_chain, program_id=program_id, deployment_slot=slot
        )
        if fixture is None:
            return ContractAcquisitionResult(
                request_id=request.request_id,
                status=AcquisitionStatus.UNAVAILABLE,
                diagnostics=(
                    f"no offline fixture for {parsed_chain}:{program_id}",
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

        total_bytes = sum(item.byte_length for _, item in stored_entries)
        if total_bytes > request.bounds.max_response_bytes:
            raise ResourceLimitError("fixture payload exceeds max_response_bytes")
        if len(stored_entries) > request.bounds.max_items:
            raise ResourceLimitError("fixture item count exceeds max_items")

        now = datetime.now(timezone.utc)
        authority = fixture.upgrade_authority_record()
        evidence = TransportEvidence(
            request_digest=bytes_digest(
                f"{request.request_id}:{request.locator}:{kind.value}".encode("utf-8")
            ),
            response_digest=bytes_digest(
                b"".join(item.raw_bytes for _, item in stored_entries)
            ),
            final_url_digest=bytes_digest(
                f"offline://{self._provider_id}/{parsed_chain}/{program_id}".encode(
                    "utf-8"
                )
            ),
            status_code=200,
            byte_length=total_bytes,
            transport="offline_fixture",
            attributes={
                "deployment_slot": fixture.deployment_slot,
                "code_epoch": fixture.code_epoch or request.code_epoch,
                "loader_version": fixture.loader_version.value,
                "upgrade_authority_state": authority.state.value
                if isinstance(authority.state, UpgradeAuthorityState)
                else str(authority.state),
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
                "program_id": fixture.program_id,
                "chain_id": fixture.chain_id,
                "compiler": fixture.compiler,
                "compiler_version": fixture.compiler_version,
                "loader_program_id": fixture.loader_program_id,
                "program_data_address": fixture.program_data_address,
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
                "chain_id": fixture.chain_id,
                "code_epoch": fixture.code_epoch,
                "compiler": fixture.compiler,
                "compiler_flags": thaw_json(fixture.compiler_flags),
                "compiler_version": fixture.compiler_version,
                "deployment_slot": fixture.deployment_slot,
                "loader_program_id": fixture.loader_program_id,
                "loader_version": fixture.loader_version.value,
                "program_data_address": fixture.program_data_address,
                "program_id": fixture.program_id,
                "sbf_elf_digest": fixture.sbf_elf_digest,
                "upgrade_authority": fixture.upgrade_authority,
                "upgrade_authority_state": authority.state.value
                if isinstance(authority.state, UpgradeAuthorityState)
                else str(authority.state),
            },
        )


# Alias matching EVM naming for package surface symmetry.
SolanaArtifactProvider = OfflineSolanaProvider


__all__ = [
    "PROVIDER_SCHEMA_VERSION",
    "SOLANA_PROVIDER_ID",
    "OfflineSolanaProvider",
    "SolanaArtifactProvider",
    "SolanaProgramFixture",
    "normalize_elf_bytes",
]
