"""Offline-first XRPL ledger artifact provider (CRYPTOIR-G240).

Fixture-backed acquisition of native ledger state snapshots, metadata, and
amendment/capability records.  Live network clients are never constructed by
import.  Acquisition is read-only and separately injectable from parse/analyze.

XRPL is modeled as native ledger objects — never as Ethereum-style bytecode.
"""

from __future__ import annotations

import json
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
    AcquisitionProvenance,
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
from .semantics import (
    XRPL_MAINNET_CHAIN_ID,
    HookCapability,
    HookCapabilityState,
    IssuerPolicy,
    ValidatedLedgerEpoch,
    is_ripple_evm_sidechain,
    normalize_classic_address,
    resolve_xrpl_chain_id,
    xrpl_network_anchor,
)


PROVIDER_SCHEMA_VERSION = "smart-contract-xrpl-provider-v1"
XRPL_PROVIDER_ID = "smart-contracts.xrpl.offline"


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
    if kind is ArtifactKind.STATE_SNAPSHOT:
        return "application/json"
    if kind is ArtifactKind.METADATA:
        return "application/json"
    if kind is ArtifactKind.SOURCE:
        return "text/plain"
    if kind is ArtifactKind.BUILD_MANIFEST:
        return "application/json"
    # XRPL does not acquire EVM bytecode as a native ledger artifact.
    return "application/json"


@dataclass(frozen=True, slots=True)
class XRPLLedgerFixture:
    """One offline XRPL ledger fixture keyed by chain + account + ledger index.

    Fixtures capture native ledger state (account root, trust lines, escrows,
    amendments, reserves) — never EVM runtime bytecode.
    """

    chain_id: str
    account: str
    ledger_index: int | None = None
    ledger_hash: str = ""
    state_snapshot_json: bytes = b""
    metadata_json: bytes = b""
    account_flags: int = 0
    sequence: int | None = None
    owner_count: int | None = None
    balance_drops: str = ""
    base_reserve_drops: str = "10000000"
    owner_reserve_drops: str = "2000000"
    trust_lines: tuple[Mapping[str, Any], ...] = ()
    escrows: tuple[Mapping[str, Any], ...] = ()
    offers: tuple[Mapping[str, Any], ...] = ()
    payment_channels: tuple[Mapping[str, Any], ...] = ()
    checks: tuple[Mapping[str, Any], ...] = ()
    signer_list: Mapping[str, Any] | None = None
    amms: tuple[Mapping[str, Any], ...] = ()
    nfts: tuple[Mapping[str, Any], ...] = ()
    enabled_amendments: tuple[str, ...] = ()
    hooks_capability_present: bool = False
    hooks_capability_evidence: str = ""
    allow_trustline_clawback: bool = False
    require_auth: bool = False
    global_freeze: bool = False
    no_freeze: bool = False
    default_ripple: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if is_ripple_evm_sidechain(self.chain_id):
            raise InvalidRequestError(
                "XRPLLedgerFixture must not use Ripple EVM sidechain chain_id; "
                "sidechain fixtures belong to the EVM provider"
            )
        resolved = resolve_xrpl_chain_id(self.chain_id)
        object.__setattr__(self, "chain_id", resolved)
        object.__setattr__(
            self, "account", normalize_classic_address(self.account, field="account")
        )
        for name in ("state_snapshot_json", "metadata_json"):
            raw = getattr(self, name)
            if type(raw) is not bytes:
                raise InvalidRequestError(f"{name} must be exact bytes")
        if self.ledger_index is not None:
            if (
                isinstance(self.ledger_index, bool)
                or not isinstance(self.ledger_index, int)
                or self.ledger_index < 0
            ):
                raise InvalidRequestError(
                    "ledger_index must be a non-negative integer"
                )
        object.__setattr__(
            self, "ledger_hash", self.ledger_hash.strip() if self.ledger_hash else ""
        )
        object.__setattr__(
            self, "account_flags", int(self.account_flags) if self.account_flags else 0
        )
        if self.account_flags < 0:
            raise InvalidRequestError("account_flags must be non-negative")
        if self.sequence is not None:
            if (
                isinstance(self.sequence, bool)
                or not isinstance(self.sequence, int)
                or self.sequence < 0
            ):
                raise InvalidRequestError("sequence must be a non-negative integer")
        if self.owner_count is not None:
            if (
                isinstance(self.owner_count, bool)
                or not isinstance(self.owner_count, int)
                or self.owner_count < 0
            ):
                raise InvalidRequestError("owner_count must be a non-negative integer")
        object.__setattr__(
            self,
            "balance_drops",
            str(self.balance_drops).strip() if self.balance_drops else "",
        )
        object.__setattr__(
            self,
            "base_reserve_drops",
            str(self.base_reserve_drops).strip() or "10000000",
        )
        object.__setattr__(
            self,
            "owner_reserve_drops",
            str(self.owner_reserve_drops).strip() or "2000000",
        )
        for seq_name in (
            "trust_lines",
            "escrows",
            "offers",
            "payment_channels",
            "checks",
            "amms",
            "nfts",
        ):
            items = getattr(self, seq_name)
            frozen_items: list[Mapping[str, Any]] = []
            for index, item in enumerate(items):
                if not isinstance(item, Mapping):
                    raise InvalidRequestError(f"{seq_name}[{index}] must be a mapping")
                frozen_items.append(_freeze_mapping(item))
            object.__setattr__(self, seq_name, tuple(frozen_items))
        if self.signer_list is not None:
            if not isinstance(self.signer_list, Mapping):
                raise InvalidRequestError("signer_list must be a mapping or None")
            object.__setattr__(self, "signer_list", _freeze_mapping(self.signer_list))
        object.__setattr__(
            self,
            "enabled_amendments",
            tuple(
                _required_text(item, "amendment") for item in self.enabled_amendments
            ),
        )
        for flag_name in (
            "hooks_capability_present",
            "allow_trustline_clawback",
            "require_auth",
            "global_freeze",
            "no_freeze",
            "default_ripple",
        ):
            object.__setattr__(
                self, flag_name, bool(getattr(self, flag_name))
            )
        object.__setattr__(
            self,
            "hooks_capability_evidence",
            self.hooks_capability_evidence.strip()
            if self.hooks_capability_evidence
            else "",
        )
        if self.hooks_capability_present and not self.hooks_capability_evidence:
            raise InvalidRequestError(
                "hooks_capability_present requires hooks_capability_evidence"
            )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        ensure_secret_safe(self.to_dict())

    @property
    def fixture_key(self) -> str:
        ledger = "" if self.ledger_index is None else str(self.ledger_index)
        return f"{self.chain_id}:{self.account}:{ledger}"

    def issuer_policy(self) -> IssuerPolicy:
        return IssuerPolicy(
            issuer=self.account,
            require_auth=self.require_auth,
            default_ripple=self.default_ripple,
            global_freeze=self.global_freeze,
            no_freeze=self.no_freeze,
            allow_trustline_clawback=self.allow_trustline_clawback,
            account_flags=self.account_flags,
            enabled_amendments=self.enabled_amendments,
        )

    def hook_capability(self) -> HookCapability:
        if self.hooks_capability_present:
            return HookCapability.proven(
                self.chain_id,
                capability_evidence=self.hooks_capability_evidence,
                ledger_index=self.ledger_index,
            )
        return HookCapability.absent(self.chain_id)

    def validated_epoch(self) -> ValidatedLedgerEpoch | None:
        if self.ledger_index is None or not self.ledger_hash:
            return None
        return ValidatedLedgerEpoch(
            chain_id=self.chain_id,
            ledger_index=self.ledger_index,
            ledger_hash=self.ledger_hash,
            validated=True,
            base_reserve_drops=self.base_reserve_drops,
            owner_reserve_drops=self.owner_reserve_drops,
            enabled_amendments=self.enabled_amendments,
        )

    def built_state_snapshot(self) -> bytes:
        """Return explicit snapshot bytes, or synthesize from structured fields."""

        if self.state_snapshot_json:
            return self.state_snapshot_json
        def _jsonable(value: Any) -> Any:
            if isinstance(value, Mapping):
                return {str(k): _jsonable(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [_jsonable(v) for v in value]
            return value

        payload = {
            "account": self.account,
            "account_flags": self.account_flags,
            "amms": _jsonable(self.amms),
            "balance_drops": self.balance_drops,
            "base_reserve_drops": self.base_reserve_drops,
            "chain_id": self.chain_id,
            "checks": _jsonable(self.checks),
            "enabled_amendments": list(self.enabled_amendments),
            "escrows": _jsonable(self.escrows),
            "hooks_capability_present": self.hooks_capability_present,
            "ledger_hash": self.ledger_hash,
            "ledger_index": self.ledger_index,
            "nfts": _jsonable(self.nfts),
            "offers": _jsonable(self.offers),
            "owner_count": self.owner_count,
            "owner_reserve_drops": self.owner_reserve_drops,
            "payment_channels": _jsonable(self.payment_channels),
            "sequence": self.sequence,
            "signer_list": _jsonable(self.signer_list)
            if self.signer_list is not None
            else None,
            "trust_lines": _jsonable(self.trust_lines),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )

    def artifact_for(self, kind: ArtifactKind) -> StoredArtifact | None:
        if kind is ArtifactKind.STATE_SNAPSHOT:
            payload = self.built_state_snapshot()
            return StoredArtifact(
                raw_bytes=payload,
                kind=ArtifactKind.STATE_SNAPSHOT,
                media_type=_kind_media_type(kind),
                label="ledger_state",
            )
        if kind is ArtifactKind.METADATA:
            if self.metadata_json:
                payload = self.metadata_json
            else:
                meta = {
                    "account": self.account,
                    "chain_id": self.chain_id,
                    "enabled_amendments": list(self.enabled_amendments),
                    "hooks_capability_present": self.hooks_capability_present,
                    "ledger_index": self.ledger_index,
                }
                payload = json.dumps(
                    meta, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            return StoredArtifact(
                raw_bytes=payload,
                kind=ArtifactKind.METADATA,
                media_type=_kind_media_type(kind),
                label="metadata",
            )
        # Native XRPL fixtures do not expose EVM bytecode / program / ABI.
        if kind in {
            ArtifactKind.BYTECODE,
            ArtifactKind.CREATION_BYTECODE,
            ArtifactKind.PROGRAM,
            ArtifactKind.ABI,
            ArtifactKind.IDL,
        }:
            return None
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "account_flags": self.account_flags,
            "allow_trustline_clawback": self.allow_trustline_clawback,
            "amms_count": len(self.amms),
            "attributes": thaw_json(self.attributes),
            "balance_drops": self.balance_drops,
            "base_reserve_drops": self.base_reserve_drops,
            "chain_id": self.chain_id,
            "checks_count": len(self.checks),
            "default_ripple": self.default_ripple,
            "enabled_amendments": list(self.enabled_amendments),
            "escrows_count": len(self.escrows),
            "global_freeze": self.global_freeze,
            "hooks_capability_evidence": self.hooks_capability_evidence,
            "hooks_capability_present": self.hooks_capability_present,
            "ledger_hash": self.ledger_hash,
            "ledger_index": self.ledger_index,
            "metadata_digest": bytes_digest(self.metadata_json)
            if self.metadata_json
            else "",
            "nfts_count": len(self.nfts),
            "no_freeze": self.no_freeze,
            "offers_count": len(self.offers),
            "owner_count": self.owner_count,
            "owner_reserve_drops": self.owner_reserve_drops,
            "payment_channels_count": len(self.payment_channels),
            "require_auth": self.require_auth,
            "sequence": self.sequence,
            "signer_list_present": self.signer_list is not None,
            "state_snapshot_digest": bytes_digest(self.built_state_snapshot()),
            "trust_lines_count": len(self.trust_lines),
        }


class OfflineXRPLProvider:
    """Bounded, fixture-only :class:`~..protocols.ArtifactProvider` for XRPL.

    Locators accepted:

    * ``xrpl://{chain_id}/{account}``
    * ``xrpl://{chain_id}/{account}@{ledger_index}``
    * bare classic r-address (requires ``chain.chain_id`` on the request)

    Ripple EVM sidechain locators are rejected (must use the EVM provider).
    """

    def __init__(
        self,
        fixtures: Sequence[XRPLLedgerFixture] = (),
        *,
        provider_id: str = XRPL_PROVIDER_ID,
    ) -> None:
        self._provider_id = _required_text(provider_id, "provider_id")
        index: dict[str, XRPLLedgerFixture] = {}
        for fixture in fixtures:
            if not isinstance(fixture, XRPLLedgerFixture):
                raise InvalidRequestError(
                    "fixtures must be XRPLLedgerFixture instances"
                )
            keys = {
                f"{fixture.chain_id}:{fixture.account}",
                fixture.fixture_key,
            }
            if fixture.ledger_index is not None:
                keys.add(
                    f"{fixture.chain_id}:{fixture.account}@{fixture.ledger_index}"
                )
            for key in keys:
                if key in index and index[key] is not fixture:
                    raise InvalidRequestError(f"duplicate XRPL fixture key: {key}")
                index[key] = fixture
        self._fixtures: Mapping[str, XRPLLedgerFixture] = MappingProxyType(index)
        self._capabilities = Capabilities(
            provider=self._provider_id,
            chain_namespaces=frozenset({"xrpl"}),
            features=frozenset(
                {
                    Capability.ACQUIRE_STATE_SNAPSHOT,
                    Capability.ACQUIRE_METADATA,
                    Capability.CAPABILITY_DISCOVERY,
                    Capability.CODE_EPOCH,
                    Capability.FINALITY,
                }
            ),
            metadata={
                "offline": True,
                "schema_version": PROVIDER_SCHEMA_VERSION,
                "fixture_count": len(fixtures),
                "native_ledger_only": True,
                "evm_bytecode_acquisition": False,
            },
        )

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def register_fixture(self, fixture: XRPLLedgerFixture) -> None:
        if not isinstance(fixture, XRPLLedgerFixture):
            raise InvalidRequestError("fixture must be a XRPLLedgerFixture")
        current: MutableMapping[str, XRPLLedgerFixture] = dict(self._fixtures)
        keys = {
            f"{fixture.chain_id}:{fixture.account}",
            fixture.fixture_key,
        }
        if fixture.ledger_index is not None:
            keys.add(
                f"{fixture.chain_id}:{fixture.account}@{fixture.ledger_index}"
            )
        for key in keys:
            current[key] = fixture
        self._fixtures = MappingProxyType(current)

    def get_fixture(
        self,
        *,
        chain_id: str,
        account: str,
        ledger_index: int | None = None,
    ) -> XRPLLedgerFixture | None:
        account = normalize_classic_address(account, field="account")
        chain_id = resolve_xrpl_chain_id(chain_id)
        if ledger_index is not None:
            key = f"{chain_id}:{account}@{ledger_index}"
            if key in self._fixtures:
                return self._fixtures[key]
        return self._fixtures.get(f"{chain_id}:{account}")

    def parse_locator(
        self,
        locator: str,
        *,
        chain_id: str = "",
    ) -> tuple[str, str, int | None]:
        """Return ``(chain_id, account, ledger_index)`` from a locator."""

        text = _required_text(locator, "locator")
        if is_ripple_evm_sidechain(text) or text.startswith("eip155://"):
            raise InvalidRequestError(
                "Ripple EVM sidechain locators must use the EVM provider; "
                "never silently treated as XRPL mainnet"
            )
        ledger: int | None = None
        if text.startswith("xrpl://"):
            rest = text[len("xrpl://") :]
            parts = rest.split("/", 1)
            if len(parts) != 2:
                raise InvalidRequestError(
                    "xrpl locator must be xrpl://{chain_id}/{account}"
                )
            chain_part, acct_part = parts
            if is_ripple_evm_sidechain(chain_part):
                raise InvalidRequestError(
                    "Ripple EVM sidechain must not be acquired via XRPL provider"
                )
            if "@" in acct_part:
                acct_part, ledger_s = acct_part.rsplit("@", 1)
                if not ledger_s.isdigit():
                    raise InvalidRequestError("ledger_index must be decimal digits")
                ledger = int(ledger_s)
            return (
                resolve_xrpl_chain_id(chain_part),
                normalize_classic_address(acct_part, field="account"),
                ledger,
            )
        # Bare classic address
        try:
            account = normalize_classic_address(text, field="account")
        except InvalidRequestError as exc:
            raise InvalidRequestError("unsupported XRPL locator form") from exc
        if not chain_id:
            raise InvalidRequestError(
                "bare account locator requires request chain_id"
            )
        return resolve_xrpl_chain_id(chain_id), account, None

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

        # Reject EVM sidechain chain refs early.
        req_chain = request.chain.chain_id or request.chain.network or ""
        if is_ripple_evm_sidechain(req_chain, request.chain.network or ""):
            return ContractAcquisitionResult(
                request_id=request.request_id,
                status=AcquisitionStatus.UNSUPPORTED,
                diagnostics=(
                    "Ripple EVM sidechain must use the EVM frontend/provider; "
                    "not XRPL native ledger acquisition",
                ),
                coverage_notes=(f"{self._provider_id}:sidechain_rejected",),
            )

        kind = (
            request.artifact_kind
            if isinstance(request.artifact_kind, ArtifactKind)
            else ArtifactKind(str(request.artifact_kind))
        )
        # Never invent EVM-style bytecode acquisition for XRPL mainnet.
        if kind in {
            ArtifactKind.BYTECODE,
            ArtifactKind.CREATION_BYTECODE,
            ArtifactKind.PROGRAM,
            ArtifactKind.ABI,
            ArtifactKind.IDL,
        }:
            return ContractAcquisitionResult(
                request_id=request.request_id,
                status=AcquisitionStatus.UNSUPPORTED,
                diagnostics=(
                    f"XRPL native ledger does not acquire {kind.value}; "
                    "use STATE_SNAPSHOT / METADATA or EVM sidechain lane",
                ),
            )

        try:
            parsed_chain, account, ledger = self.parse_locator(
                request.locator, chain_id=req_chain
            )
        except InvalidRequestError as exc:
            status = (
                AcquisitionStatus.UNSUPPORTED
                if "sidechain" in str(exc).lower()
                else AcquisitionStatus.UNAVAILABLE
            )
            return ContractAcquisitionResult(
                request_id=request.request_id,
                status=status,
                diagnostics=(str(exc),),
            )

        fixture = self.get_fixture(
            chain_id=parsed_chain, account=account, ledger_index=ledger
        )
        if fixture is None:
            return ContractAcquisitionResult(
                request_id=request.request_id,
                status=AcquisitionStatus.UNAVAILABLE,
                diagnostics=(
                    f"no offline fixture for {parsed_chain}:{account}",
                ),
            )

        artifact = fixture.artifact_for(kind)
        if artifact is None:
            return ContractAcquisitionResult(
                request_id=request.request_id,
                status=AcquisitionStatus.UNAVAILABLE,
                diagnostics=(f"fixture lacks artifact kind {kind.value}",),
                coverage_notes=(f"{self._provider_id}:partial_fixture",),
            )

        total_bytes = artifact.byte_length
        if total_bytes > request.bounds.max_response_bytes:
            raise ResourceLimitError("fixture payload exceeds max_response_bytes")

        now = datetime.now(timezone.utc)
        stored_entries = [(artifact.label or kind.value, artifact)]
        evidence = TransportEvidence(
            request_digest=bytes_digest(
                f"{request.request_id}:{request.locator}:{kind.value}".encode("utf-8")
            ),
            response_digest=bytes_digest(artifact.raw_bytes),
            final_url_digest=bytes_digest(
                f"offline://{self._provider_id}/{parsed_chain}/{account}".encode(
                    "utf-8"
                )
            ),
            status_code=200,
            byte_length=total_bytes,
            transport="offline_fixture",
            attributes={
                "ledger_index": fixture.ledger_index,
                "hooks_capability_present": fixture.hooks_capability_present,
                "enabled_amendments": list(fixture.enabled_amendments),
            },
        )
        anchor = xrpl_network_anchor(parsed_chain)
        manifest = ArtifactManifest.from_stored(
            stored_entries,
            request_id=request.request_id,
            observed_at=now,
            transport_evidence=(evidence,),
            provider_ids=(self._provider_id,),
            code_epoch=(
                f"xrpl:{parsed_chain}:{fixture.ledger_index}"
                if fixture.ledger_index is not None
                else request.code_epoch
            ),
            attributes={
                "account": fixture.account,
                "chain_id": fixture.chain_id,
                "network": anchor["network"],
                "native_ledger": True,
            },
        )
        refs: tuple[ArtifactRef, ...] = manifest.artifact_refs()
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
                "account": fixture.account,
                "chain_id": fixture.chain_id,
                "fixture_key": fixture.fixture_key,
                "hooks_capability": fixture.hook_capability().to_dict(),
                "ledger_index": fixture.ledger_index,
                "network": anchor["network"],
            },
        )


# Re-export for type checkers / convenience
__all__ = [
    "PROVIDER_SCHEMA_VERSION",
    "XRPL_PROVIDER_ID",
    "XRPLLedgerFixture",
    "OfflineXRPLProvider",
    "XRPL_MAINNET_CHAIN_ID",
    "HookCapabilityState",
]
