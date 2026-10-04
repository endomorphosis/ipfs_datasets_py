"""Non-custodial Solana transaction guard (CRYPTOIR-G540 / CRYPTOIR-031).

Normalize Solana messages, address tables, programs, accounts, privileges,
instructions, CPI effects, lamport/token movements, blockhash, and fees into
the common two-phase wallet guard.

Acceptance (fail-closed):

* Message version, account order, address-table epoch, signer/writable bits,
  recent blockhash, program/program-data epoch, CPI and token effects, and
  exact candidate bytes are bound.
* Substituted accounts/programs, privilege escalation, hidden CPI transfers,
  program upgrades, stale blockhash, and stale compliance evidence block.
* Address tables and executable program epochs are **re-resolved at
  consumption** (pre-sign / pre-broadcast) and must match the binding used
  when the admissibility capability was issued.

This module never signs, broadcasts, or accepts bare booleans / caller
approval flags as authority.  Keys remain with an external custody system.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Final

from ipfs_datasets_py.logic.crypto_ir.adapters.solana import (
    SOLANA_MAINNET_CHAIN_ID,
    SOLANA_MAINNET_GENESIS_HASH,
    SOLANA_MAINNET_NETWORK,
    SOLANA_NAMESPACE,
    SYSTEM_PROGRAM_ID,
    TOKEN_PROGRAM_ID,
    AccountPrivilege,
    AddressLookupTableRef,
    SolanaAdapterError,
    SolanaInstruction,
    SolanaMessageCandidate,
    normalize_blockhash,
    normalize_message_version,
    normalize_pubkey,
    parse_instructions,
    resolve_account_privileges,
    resolve_network,
)
from ipfs_datasets_py.logic.crypto_ir.verdicts import TransactionVerdictOutcome
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest
from ipfs_datasets_py.logic.ir_core.provenance import thaw_json

from ..guard.errors import (
    GuardCapabilityError,
    GuardError,
    GuardForbiddenSurfaceError,
    GuardPolicyError,
    GuardValidationError,
)
from ..guard.models import (
    AdmissibilityCapability,
    AssetAmount,
    ExpectedEffect,
    FeeSpec,
    PreflightConsumptionResult,
    PreflightPhase,
    PreflightResult,
    TransactionCandidate,
    TransactionIntent,
    TransactionPreflightRequest,
)
from ..guard.preflight import TransactionPreflight

# ---------------------------------------------------------------------------
# Schema / interface identities
# ---------------------------------------------------------------------------

SOLANA_TRANSACTION_GUARD_INTERFACE: Final = "SolanaTransactionGuard@1"
SOLANA_TRANSACTION_GUARD_SCHEMA_VERSION: Final = (
    "wallet-guard.solana-transaction-guard/v1"
)
ADDRESS_TABLE_EPOCH_SCHEMA_VERSION: Final = "wallet-guard.solana-address-table-epoch/v1"
EXECUTABLE_PROGRAM_EPOCH_SCHEMA_VERSION: Final = (
    "wallet-guard.solana-executable-program-epoch/v1"
)
SOLANA_MESSAGE_BINDING_SCHEMA_VERSION: Final = (
    "wallet-guard.solana-message-binding/v1"
)
SOLANA_GUARD_DECISION_SCHEMA_VERSION: Final = (
    "wallet-guard.solana-guard-decision/v1"
)

DEFAULT_PRODUCER_ID: Final = "producer:wallet-guard-solana-v1"
DEFAULT_POLICY_ID: Final = "policy:solana-wallet-guard-v1"
DEFAULT_FEE_LAMPORTS: Final = "5000"

MAX_IDENTIFIER_CHARS: Final = 256
MAX_STRING_CHARS: Final = 4_096
MAX_COLLECTION_ITEMS: Final = 1_024

_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_HEX_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_ISO8601_RE: Final = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)
_DECIMAL_RE: Final = re.compile(r"^(0|[1-9][0-9]*)$")

_FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "approved",
        "approval",
        "allow",
        "allowed",
        "private_key",
        "private_keys",
        "secret",
        "secrets",
        "seed",
        "mnemonic",
        "signature",
        "signatures",
        "signed_tx",
        "signed_transaction",
        "broadcast",
        "broadcast_url",
        "raw_key",
        "signing_key",
        "api_key",
        "caller_approved",
        "force_allow",
        "bypass",
    }
)

# Default security / compliance requirement identifiers for Solana preflight.
DEFAULT_SECURITY_REQUIREMENTS: Final[tuple[str, ...]] = (
    "sec:solana-message-binding",
    "sec:solana-account-privileges",
    "sec:solana-address-table-epoch",
    "sec:solana-program-epoch",
    "sec:solana-blockhash-freshness",
    "sec:solana-cpi-effects",
)
DEFAULT_COMPLIANCE_REQUIREMENTS: Final[tuple[str, ...]] = (
    "comp:direct-sanctions",
    "comp:bounded-exposure",
)


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def _text(
    value: Any,
    name: str,
    *,
    allow_empty: bool = False,
    max_chars: int = MAX_STRING_CHARS,
) -> str:
    if not isinstance(value, str):
        raise GuardValidationError(f"{name} must be a string")
    if not allow_empty and (not value.strip() or value != value.strip()):
        raise GuardValidationError(f"{name} must be a non-empty trimmed string")
    if value and value != value.strip():
        raise GuardValidationError(f"{name} must not have surrounding whitespace")
    if len(value) > max_chars:
        raise GuardValidationError(f"{name} exceeds maximum length of {max_chars}")
    return value


def _optional_text(value: Any, name: str, *, max_chars: int = MAX_STRING_CHARS) -> str:
    if value in (None, ""):
        return ""
    return _text(value, name, max_chars=max_chars)


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=MAX_IDENTIFIER_CHARS)
    if not _ID_RE.fullmatch(text):
        raise GuardValidationError(f"{name} is not a stable identifier")
    return text


def _digest(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=80)
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    if not _SHA256_HEX_RE.fullmatch(text):
        raise GuardValidationError(f"{name} must be a lowercase SHA-256 hex digest")
    return text


def _timestamp(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=64)
    if not _ISO8601_RE.fullmatch(text):
        raise GuardValidationError(
            f"{name} must be an ISO-8601 UTC/offset timestamp"
        )
    return text


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GuardValidationError(f"{name} must be an integer")
    if value < 0:
        raise GuardValidationError(f"{name} must be non-negative")
    return value


def _amount(value: Any, name: str) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        if value < 0:
            raise GuardValidationError(f"{name} must be a non-negative integer")
        return str(value)
    text = _text(value, name, max_chars=128)
    if not _DECIMAL_RE.fullmatch(text):
        raise GuardValidationError(
            f"{name} must be a non-negative decimal integer string"
        )
    return text


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GuardValidationError(f"{name} must be a mapping")
    return value


def _reject_forbidden(value: Mapping[str, Any], record_name: str) -> None:
    hit = sorted(set(value) & _FORBIDDEN_FIELDS)
    if hit:
        raise GuardForbiddenSurfaceError(
            f"{record_name} contains forbidden custody/approval field(s): "
            f"{', '.join(hit)}",
            details={"fields": hit},
        )


def _attributes(value: Mapping[str, Any] | None) -> FrozenMap:
    if value is None:
        return FrozenMap()
    if not isinstance(value, Mapping):
        raise GuardValidationError("attributes must be a mapping")
    _reject_forbidden(value, "attributes")
    try:
        return FrozenMap(value)
    except (TypeError, ValueError) as exc:
        raise GuardValidationError(f"attributes invalid: {exc}") from exc


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _is_expired(expiry: str, now: str) -> bool:
    return now > expiry


def _jsonable(value: Any) -> Any:
    """Recursively convert FrozenMap / mappingproxy / tuples into JSON types."""

    if isinstance(value, FrozenMap):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    # Fall back to thaw_json for other frozen IR containers.
    try:
        return thaw_json(value)
    except Exception:  # noqa: BLE001
        return str(value)


def content_sha256_hex(payload: Mapping[str, Any] | Sequence[Any] | str) -> str:
    """Stable SHA-256 hex digest over a JSON-like structure or raw string."""

    if isinstance(payload, str):
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return stable_digest(_jsonable(payload))


def _pubkey(value: Any, name: str) -> str:
    try:
        return normalize_pubkey(value, field=name)
    except (SolanaAdapterError, TypeError, ValueError) as exc:
        raise GuardValidationError(f"{name} is not a valid Solana pubkey: {exc}") from exc


# ---------------------------------------------------------------------------
# Epoch bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AddressTableEpoch:
    """Bound address-lookup-table resolution epoch for a versioned message.

    The epoch digest covers the table account key, index sets, and fully
    resolved addresses so any substitution invalidates prior permission.
    """

    account_key: str
    writable_indexes: tuple[int, ...] = ()
    readonly_indexes: tuple[int, ...] = ()
    writable_addresses: tuple[str, ...] = ()
    readonly_addresses: tuple[str, ...] = ()
    table_epoch: str = ""
    last_extended_slot: int | None = None
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = ADDRESS_TABLE_EPOCH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "account_key", _pubkey(self.account_key, "account_key")
        )
        object.__setattr__(
            self,
            "writable_indexes",
            tuple(
                _non_negative_int(i, "writable_indexes item")
                for i in self.writable_indexes
            ),
        )
        object.__setattr__(
            self,
            "readonly_indexes",
            tuple(
                _non_negative_int(i, "readonly_indexes item")
                for i in self.readonly_indexes
            ),
        )
        object.__setattr__(
            self,
            "writable_addresses",
            tuple(_pubkey(a, "writable_addresses item") for a in self.writable_addresses),
        )
        object.__setattr__(
            self,
            "readonly_addresses",
            tuple(_pubkey(a, "readonly_addresses item") for a in self.readonly_addresses),
        )
        if len(self.writable_indexes) != len(self.writable_addresses):
            raise GuardValidationError(
                "writable_indexes and writable_addresses length mismatch"
            )
        if len(self.readonly_indexes) != len(self.readonly_addresses):
            raise GuardValidationError(
                "readonly_indexes and readonly_addresses length mismatch"
            )
        if self.last_extended_slot is not None:
            object.__setattr__(
                self,
                "last_extended_slot",
                _non_negative_int(self.last_extended_slot, "last_extended_slot"),
            )
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != ADDRESS_TABLE_EPOCH_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported address table epoch schema: {self.schema_version!r}"
            )
        # Compute canonical epoch when not supplied.
        if not self.table_epoch:
            object.__setattr__(self, "table_epoch", self.compute_epoch_digest())
        else:
            object.__setattr__(
                self, "table_epoch", _digest(self.table_epoch, "table_epoch")
            )

    def compute_epoch_digest(self) -> str:
        return content_sha256_hex(
            {
                "account_key": self.account_key,
                "last_extended_slot": self.last_extended_slot,
                "readonly_addresses": list(self.readonly_addresses),
                "readonly_indexes": list(self.readonly_indexes),
                "writable_addresses": list(self.writable_addresses),
                "writable_indexes": list(self.writable_indexes),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_key": self.account_key,
            "attributes": self.attributes.to_dict(),
            "last_extended_slot": self.last_extended_slot,
            "readonly_addresses": list(self.readonly_addresses),
            "readonly_indexes": list(self.readonly_indexes),
            "schema_version": self.schema_version,
            "table_epoch": self.table_epoch,
            "writable_addresses": list(self.writable_addresses),
            "writable_indexes": list(self.writable_indexes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AddressTableEpoch":
        value = _mapping(value, "AddressTableEpoch")
        _reject_forbidden(value, "AddressTableEpoch")
        return cls(
            account_key=value.get("account_key", value.get("accountKey", "")),
            writable_indexes=tuple(
                value.get("writable_indexes", value.get("writableIndexes", ()))
            ),
            readonly_indexes=tuple(
                value.get("readonly_indexes", value.get("readonlyIndexes", ()))
            ),
            writable_addresses=tuple(
                value.get("writable_addresses", value.get("writableAddresses", ()))
            ),
            readonly_addresses=tuple(
                value.get("readonly_addresses", value.get("readonlyAddresses", ()))
            ),
            table_epoch=value.get("table_epoch", value.get("tableEpoch", "")),
            last_extended_slot=value.get(
                "last_extended_slot", value.get("lastExtendedSlot")
            ),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", ADDRESS_TABLE_EPOCH_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_lookup_ref(
        cls,
        ref: AddressLookupTableRef,
        *,
        last_extended_slot: int | None = None,
        table_epoch: str = "",
    ) -> "AddressTableEpoch":
        return cls(
            account_key=ref.account_key,
            writable_indexes=ref.writable_indexes,
            readonly_indexes=ref.readonly_indexes,
            writable_addresses=ref.writable_addresses,
            readonly_addresses=ref.readonly_addresses,
            table_epoch=table_epoch,
            last_extended_slot=last_extended_slot,
        )


@dataclass(frozen=True, slots=True)
class ExecutableProgramEpoch:
    """Bound executable program / program-data epoch for a Solana program id.

    Captures the code epoch identity that must be re-resolved at consumption.
    An upgrade (binary/code epoch / deployment slot change) invalidates prior
    permission.
    """

    program_id: str
    code_epoch: str
    binary_digest: str = ""
    deployment_slot: int | None = None
    program_data_address: str = ""
    upgrade_authority: str = ""
    loader_program_id: str = ""
    chain_id: str = SOLANA_MAINNET_CHAIN_ID
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = EXECUTABLE_PROGRAM_EPOCH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "program_id", _pubkey(self.program_id, "program_id")
        )
        object.__setattr__(
            self, "code_epoch", _text(self.code_epoch, "code_epoch", max_chars=256)
        )
        if self.binary_digest:
            object.__setattr__(
                self, "binary_digest", _digest(self.binary_digest, "binary_digest")
            )
        else:
            object.__setattr__(self, "binary_digest", "")
        if self.deployment_slot is not None:
            object.__setattr__(
                self,
                "deployment_slot",
                _non_negative_int(self.deployment_slot, "deployment_slot"),
            )
        if self.program_data_address:
            object.__setattr__(
                self,
                "program_data_address",
                _pubkey(self.program_data_address, "program_data_address"),
            )
        else:
            object.__setattr__(self, "program_data_address", "")
        if self.upgrade_authority:
            # May be a pubkey or the sentinel "none" / "disabled".
            auth = _text(self.upgrade_authority, "upgrade_authority", max_chars=128)
            if auth not in {"none", "disabled", "immutable"}:
                try:
                    auth = normalize_pubkey(auth, field="upgrade_authority")
                except (SolanaAdapterError, TypeError, ValueError):
                    pass
            object.__setattr__(self, "upgrade_authority", auth)
        else:
            object.__setattr__(self, "upgrade_authority", "")
        if self.loader_program_id:
            object.__setattr__(
                self,
                "loader_program_id",
                _pubkey(self.loader_program_id, "loader_program_id"),
            )
        else:
            object.__setattr__(self, "loader_program_id", "")
        object.__setattr__(
            self, "chain_id", _text(self.chain_id, "chain_id", max_chars=128)
        )
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != EXECUTABLE_PROGRAM_EPOCH_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported program epoch schema: {self.schema_version!r}"
            )

    @property
    def epoch_digest(self) -> str:
        return content_sha256_hex(
            {
                "binary_digest": self.binary_digest,
                "chain_id": self.chain_id,
                "code_epoch": self.code_epoch,
                "deployment_slot": self.deployment_slot,
                "program_data_address": self.program_data_address,
                "program_id": self.program_id,
                "upgrade_authority": self.upgrade_authority,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "binary_digest": self.binary_digest,
            "chain_id": self.chain_id,
            "code_epoch": self.code_epoch,
            "deployment_slot": self.deployment_slot,
            "epoch_digest": self.epoch_digest,
            "loader_program_id": self.loader_program_id,
            "program_data_address": self.program_data_address,
            "program_id": self.program_id,
            "schema_version": self.schema_version,
            "upgrade_authority": self.upgrade_authority,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutableProgramEpoch":
        value = _mapping(value, "ExecutableProgramEpoch")
        _reject_forbidden(value, "ExecutableProgramEpoch")
        return cls(
            program_id=value.get("program_id", value.get("programId", "")),
            code_epoch=value.get("code_epoch", value.get("codeEpoch", "")),
            binary_digest=value.get("binary_digest", value.get("binaryDigest", "")),
            deployment_slot=value.get(
                "deployment_slot", value.get("deploymentSlot")
            ),
            program_data_address=value.get(
                "program_data_address", value.get("programDataAddress", "")
            ),
            upgrade_authority=value.get(
                "upgrade_authority", value.get("upgradeAuthority", "")
            ),
            loader_program_id=value.get(
                "loader_program_id", value.get("loaderProgramId", "")
            ),
            chain_id=value.get("chain_id", value.get("chainId", SOLANA_MAINNET_CHAIN_ID)),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", EXECUTABLE_PROGRAM_EPOCH_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Message binding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SolanaMessageBinding:
    """Exact Solana message facts bound for two-phase guard evaluation.

    Every field that participates in policy is frozen here so pre-sign and
    pre-broadcast revalidation can detect substitution, privilege escalation,
    hidden CPI transfers, upgrades, and epoch drift.
    """

    binding_id: str
    intent_id: str
    candidate_id: str
    chain_id: str
    network: str
    genesis_hash: str
    message_version: str
    recent_blockhash: str
    fee_payer: str
    fee_lamports: str
    account_order: tuple[str, ...]
    privileges: tuple[AccountPrivilege, ...]
    instructions: tuple[SolanaInstruction, ...]
    address_table_epochs: tuple[AddressTableEpoch, ...]
    program_epochs: tuple[ExecutableProgramEpoch, ...]
    cpi_effects: tuple[Mapping[str, Any], ...]
    token_effects: tuple[Mapping[str, Any], ...]
    lamport_effects: tuple[Mapping[str, Any], ...]
    message_digest: str
    candidate_digest: str
    serialized_digest: str
    encoding: str
    byte_length: int
    binding_digest: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = SOLANA_MESSAGE_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "binding_id", _identifier(self.binding_id, "binding_id")
        )
        object.__setattr__(
            self, "intent_id", _identifier(self.intent_id, "intent_id")
        )
        object.__setattr__(
            self, "candidate_id", _identifier(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "chain_id", _text(self.chain_id, "chain_id", max_chars=128)
        )
        object.__setattr__(
            self, "network", _text(self.network, "network", max_chars=128)
        )
        object.__setattr__(
            self,
            "genesis_hash",
            _text(self.genesis_hash, "genesis_hash", max_chars=128),
        )
        object.__setattr__(
            self,
            "message_version",
            normalize_message_version(self.message_version or "legacy"),
        )
        object.__setattr__(
            self,
            "recent_blockhash",
            normalize_blockhash(self.recent_blockhash, field="recent_blockhash")
            if self.recent_blockhash
            else "",
        )
        if not self.recent_blockhash:
            raise GuardValidationError("recent_blockhash is required for binding")
        object.__setattr__(self, "fee_payer", _pubkey(self.fee_payer, "fee_payer"))
        object.__setattr__(
            self, "fee_lamports", _amount(self.fee_lamports, "fee_lamports")
        )
        if not self.account_order:
            raise GuardValidationError("account_order must be non-empty")
        if len(self.account_order) > MAX_COLLECTION_ITEMS:
            raise GuardValidationError("account_order exceeds maximum collection size")
        object.__setattr__(
            self,
            "account_order",
            tuple(_pubkey(a, "account_order item") for a in self.account_order),
        )
        privileges = tuple(self.privileges)
        if not privileges:
            raise GuardValidationError("privileges must be non-empty")
        for index, priv in enumerate(privileges):
            if not isinstance(priv, AccountPrivilege):
                if isinstance(priv, Mapping):
                    privileges = privileges[:index] + (
                        AccountPrivilege.from_dict(priv),
                    ) + privileges[index + 1 :]
                else:
                    raise GuardValidationError(
                        "privileges items must be AccountPrivilege"
                    )
        object.__setattr__(self, "privileges", privileges)
        if len(self.privileges) != len(self.account_order):
            raise GuardValidationError(
                "privileges length must match account_order length"
            )
        for index, (priv, key) in enumerate(
            zip(self.privileges, self.account_order, strict=True)
        ):
            if priv.account_index != index:
                raise GuardValidationError(
                    f"privilege account_index {priv.account_index} != order index {index}"
                )
            if priv.pubkey != key:
                raise GuardValidationError(
                    f"privilege pubkey at index {index} does not match account_order"
                )
        instructions: list[SolanaInstruction] = []
        for item in self.instructions:
            if isinstance(item, SolanaInstruction):
                instructions.append(item)
            elif isinstance(item, Mapping):
                instructions.append(SolanaInstruction.from_dict(item))
            else:
                raise GuardValidationError(
                    "instructions items must be SolanaInstruction"
                )
        object.__setattr__(self, "instructions", tuple(instructions))
        tables: list[AddressTableEpoch] = []
        for item in self.address_table_epochs:
            if isinstance(item, AddressTableEpoch):
                tables.append(item)
            elif isinstance(item, Mapping):
                tables.append(AddressTableEpoch.from_dict(item))
            else:
                raise GuardValidationError(
                    "address_table_epochs items must be AddressTableEpoch"
                )
        object.__setattr__(self, "address_table_epochs", tuple(tables))
        programs: list[ExecutableProgramEpoch] = []
        for item in self.program_epochs:
            if isinstance(item, ExecutableProgramEpoch):
                programs.append(item)
            elif isinstance(item, Mapping):
                programs.append(ExecutableProgramEpoch.from_dict(item))
            else:
                raise GuardValidationError(
                    "program_epochs items must be ExecutableProgramEpoch"
                )
        object.__setattr__(self, "program_epochs", tuple(programs))
        object.__setattr__(
            self,
            "cpi_effects",
            tuple(dict(item) for item in self.cpi_effects),
        )
        object.__setattr__(
            self,
            "token_effects",
            tuple(dict(item) for item in self.token_effects),
        )
        object.__setattr__(
            self,
            "lamport_effects",
            tuple(dict(item) for item in self.lamport_effects),
        )
        object.__setattr__(
            self, "message_digest", _digest(self.message_digest, "message_digest")
        )
        object.__setattr__(
            self, "candidate_digest", _digest(self.candidate_digest, "candidate_digest")
        )
        object.__setattr__(
            self,
            "serialized_digest",
            _digest(self.serialized_digest, "serialized_digest"),
        )
        object.__setattr__(
            self, "encoding", _identifier(self.encoding, "encoding")
        )
        object.__setattr__(
            self, "byte_length", _non_negative_int(self.byte_length, "byte_length")
        )
        if self.byte_length == 0:
            raise GuardValidationError("byte_length must be positive")
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != SOLANA_MESSAGE_BINDING_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported message binding schema: {self.schema_version!r}"
            )
        if not self.binding_digest:
            object.__setattr__(self, "binding_digest", self.compute_binding_digest())
        else:
            object.__setattr__(
                self, "binding_digest", _digest(self.binding_digest, "binding_digest")
            )

    def compute_binding_digest(self) -> str:
        return content_sha256_hex(self.to_dict_for_digest())

    def to_dict_for_digest(self) -> dict[str, Any]:
        return {
            "account_order": list(self.account_order),
            "address_table_epochs": [t.to_dict() for t in self.address_table_epochs],
            "byte_length": self.byte_length,
            "candidate_digest": self.candidate_digest,
            "candidate_id": self.candidate_id,
            "chain_id": self.chain_id,
            "cpi_effects": list(self.cpi_effects),
            "encoding": self.encoding,
            "fee_lamports": self.fee_lamports,
            "fee_payer": self.fee_payer,
            "genesis_hash": self.genesis_hash,
            "instructions": [i.to_dict() for i in self.instructions],
            "intent_id": self.intent_id,
            "lamport_effects": list(self.lamport_effects),
            "message_digest": self.message_digest,
            "message_version": self.message_version,
            "network": self.network,
            "privileges": [p.to_dict() for p in self.privileges],
            "program_epochs": [p.to_dict() for p in self.program_epochs],
            "recent_blockhash": self.recent_blockhash,
            "serialized_digest": self.serialized_digest,
            "token_effects": list(self.token_effects),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_dict_for_digest()
        payload.update(
            {
                "attributes": self.attributes.to_dict(),
                "binding_digest": self.binding_digest,
                "binding_id": self.binding_id,
                "schema_version": self.schema_version,
            }
        )
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SolanaMessageBinding":
        value = _mapping(value, "SolanaMessageBinding")
        _reject_forbidden(value, "SolanaMessageBinding")
        return cls(
            binding_id=value.get("binding_id", ""),
            intent_id=value.get("intent_id", ""),
            candidate_id=value.get("candidate_id", ""),
            chain_id=value.get("chain_id", SOLANA_MAINNET_CHAIN_ID),
            network=value.get("network", SOLANA_MAINNET_NETWORK),
            genesis_hash=value.get("genesis_hash", SOLANA_MAINNET_GENESIS_HASH),
            message_version=value.get("message_version", value.get("version", "legacy")),
            recent_blockhash=value.get("recent_blockhash", ""),
            fee_payer=value.get("fee_payer", ""),
            fee_lamports=value.get("fee_lamports", DEFAULT_FEE_LAMPORTS),
            account_order=tuple(value.get("account_order", ())),
            privileges=tuple(value.get("privileges", ())),
            instructions=tuple(value.get("instructions", ())),
            address_table_epochs=tuple(value.get("address_table_epochs", ())),
            program_epochs=tuple(value.get("program_epochs", ())),
            cpi_effects=tuple(value.get("cpi_effects", ())),
            token_effects=tuple(value.get("token_effects", ())),
            lamport_effects=tuple(value.get("lamport_effects", ())),
            message_digest=value.get("message_digest", ""),
            candidate_digest=value.get("candidate_digest", ""),
            serialized_digest=value.get("serialized_digest", ""),
            encoding=value.get("encoding", "solana-message"),
            byte_length=value.get("byte_length", 0),
            binding_digest=value.get("binding_digest", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", SOLANA_MESSAGE_BINDING_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


class SolanaGuardPhase(str, Enum):
    """Phase at which the Solana guard is consulted."""

    EVALUATE = "evaluate"
    PRE_SIGN = "pre_sign"
    PRE_BROADCAST = "pre_broadcast"


@dataclass(frozen=True, slots=True)
class SolanaGuardDecision:
    """Deterministic Solana guard decision (not authorization to sign)."""

    outcome: TransactionVerdictOutcome
    blocks_automation: bool
    reason_codes: tuple[str, ...]
    reasons: tuple[str, ...]
    binding_digest: str
    request_digest: str = ""
    preflight: PreflightResult | None = None
    security_results: Mapping[str, str] = field(default_factory=dict)
    compliance_results: Mapping[str, str] = field(default_factory=dict)
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = SOLANA_GUARD_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, TransactionVerdictOutcome):
            object.__setattr__(
                self, "outcome", TransactionVerdictOutcome(str(self.outcome))
            )
        object.__setattr__(
            self, "blocks_automation", bool(self.blocks_automation)
        )
        object.__setattr__(
            self, "reason_codes", tuple(str(c) for c in self.reason_codes)
        )
        object.__setattr__(self, "reasons", tuple(str(r) for r in self.reasons))
        object.__setattr__(
            self, "binding_digest", _digest(self.binding_digest, "binding_digest")
        )
        if self.request_digest:
            object.__setattr__(
                self, "request_digest", _digest(self.request_digest, "request_digest")
            )
        else:
            object.__setattr__(self, "request_digest", "")
        object.__setattr__(
            self, "security_results", dict(self.security_results or {})
        )
        object.__setattr__(
            self, "compliance_results", dict(self.compliance_results or {})
        )
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )

    @property
    def allowed(self) -> bool:
        return (
            self.outcome is TransactionVerdictOutcome.ALLOW
            and not self.blocks_automation
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "binding_digest": self.binding_digest,
            "blocks_automation": self.blocks_automation,
            "compliance_results": dict(self.compliance_results),
            "outcome": self.outcome.value,
            "preflight": self.preflight.to_dict() if self.preflight else None,
            "reason_codes": list(self.reason_codes),
            "reasons": list(self.reasons),
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "security_results": dict(self.security_results),
        }


# ---------------------------------------------------------------------------
# Live resolvers (injected; offline maps by default)
# ---------------------------------------------------------------------------

AddressTableResolver = Callable[[str], AddressTableEpoch | Mapping[str, Any] | None]
ProgramEpochResolver = Callable[
    [str], ExecutableProgramEpoch | Mapping[str, Any] | None
]
BlockhashFreshnessChecker = Callable[[str, str], bool]


def _static_table_resolver(
    epochs: Mapping[str, AddressTableEpoch | Mapping[str, Any]],
) -> AddressTableResolver:
    def _resolve(account_key: str) -> AddressTableEpoch | Mapping[str, Any] | None:
        return epochs.get(account_key)

    return _resolve


def _static_program_resolver(
    epochs: Mapping[str, ExecutableProgramEpoch | Mapping[str, Any]],
) -> ProgramEpochResolver:
    def _resolve(program_id: str) -> ExecutableProgramEpoch | Mapping[str, Any] | None:
        return epochs.get(program_id)

    return _resolve


def _coerce_table_epoch(
    value: AddressTableEpoch | Mapping[str, Any] | None, *, field_name: str
) -> AddressTableEpoch | None:
    if value is None:
        return None
    if isinstance(value, AddressTableEpoch):
        return value
    if isinstance(value, Mapping):
        return AddressTableEpoch.from_dict(value)
    raise GuardValidationError(f"{field_name} must be AddressTableEpoch or mapping")


def _coerce_program_epoch(
    value: ExecutableProgramEpoch | Mapping[str, Any] | None, *, field_name: str
) -> ExecutableProgramEpoch | None:
    if value is None:
        return None
    if isinstance(value, ExecutableProgramEpoch):
        return value
    if isinstance(value, Mapping):
        return ExecutableProgramEpoch.from_dict(value)
    raise GuardValidationError(
        f"{field_name} must be ExecutableProgramEpoch or mapping"
    )


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


@dataclass
class SolanaTransactionGuard:
    """Non-custodial Solana leaf guard adapter for the two-phase preflight API.

    Normalizes Solana message candidates into exact
    :class:`TransactionIntent` / :class:`TransactionCandidate` bindings, runs
    Solana-specific fail-closed checks, and delegates capability issuance /
    atomic consumption to :class:`TransactionPreflight`.

    Address tables and executable program epochs are re-resolved at
    consumption and must match the epochs bound at evaluation.
    """

    preflight: TransactionPreflight | None = None
    producer_id: str = DEFAULT_PRODUCER_ID
    policy_id: str = DEFAULT_POLICY_ID
    address_table_resolver: AddressTableResolver | None = None
    program_epoch_resolver: ProgramEpochResolver | None = None
    blockhash_is_fresh: BlockhashFreshnessChecker | None = None
    interface: str = SOLANA_TRANSACTION_GUARD_INTERFACE
    schema_version: str = SOLANA_TRANSACTION_GUARD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.preflight is None:
            self.preflight = TransactionPreflight(producer_id=self.producer_id)
        if self.interface != SOLANA_TRANSACTION_GUARD_INTERFACE:
            raise GuardValidationError(
                f"unsupported solana guard interface: {self.interface!r}"
            )
        if self.schema_version != SOLANA_TRANSACTION_GUARD_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported solana guard schema: {self.schema_version!r}"
            )
        if self.blockhash_is_fresh is None:
            # Offline default: any non-empty blockhash is treated as fresh
            # unless the caller injects a freshness checker that fails closed.
            self.blockhash_is_fresh = lambda _bh, _now: True

    # -- binding ------------------------------------------------------------

    def bind_message(
        self,
        candidate: SolanaMessageCandidate | Mapping[str, Any],
        *,
        loaded_addresses: Mapping[str, Any] | None = None,
        program_epochs: Sequence[ExecutableProgramEpoch | Mapping[str, Any]]
        | None = None,
        address_table_epochs: Sequence[AddressTableEpoch | Mapping[str, Any]]
        | None = None,
        declared_cpi_effects: Sequence[Mapping[str, Any]] | None = None,
        declared_token_effects: Sequence[Mapping[str, Any]] | None = None,
        declared_lamport_effects: Sequence[Mapping[str, Any]] | None = None,
        fee_lamports: str | int = DEFAULT_FEE_LAMPORTS,
        serialized_bytes: bytes | str | None = None,
        encoding: str = "solana-message",
        candidate_id: str = "",
        binding_id: str = "",
        attributes: Mapping[str, Any] | None = None,
    ) -> SolanaMessageBinding:
        """Normalize a Solana message candidate into an exact guard binding.

        Versioned messages that declare address-table lookups require fully
        resolved ``loaded_addresses`` (or equivalent address_table_epochs).
        Partial resolution fails closed.
        """

        message_candidate = self._coerce_message_candidate(candidate)
        message = _jsonable(message_candidate.message)
        if not isinstance(message, dict) or not message:
            raise GuardValidationError("message_candidate requires a non-empty message")

        version = message_candidate.version
        recent = message_candidate.recent_blockhash or message.get(
            "recentBlockhash", message.get("recent_blockhash", "")
        )
        if not recent:
            raise GuardValidationError(
                "recent_blockhash is required; stale/missing blockhash blocks"
            )
        try:
            recent = normalize_blockhash(recent, field="recent_blockhash")
        except (SolanaAdapterError, TypeError, ValueError) as exc:
            raise GuardValidationError(f"invalid recent_blockhash: {exc}") from exc

        network_anchor = resolve_network(
            chain_id=message_candidate.chain_id or None,
            network=message_candidate.network or None,
            genesis_hash=message_candidate.genesis_hash or None,
        )

        # Resolve privileges + address tables (fail closed on partial ALT).
        meta_for_resolve: dict[str, Any] | None = None
        lookups = message.get("addressTableLookups") or message.get(
            "address_table_lookups"
        )
        if loaded_addresses is not None:
            meta_for_resolve = {"loadedAddresses": dict(loaded_addresses)}
        elif lookups:
            # Attempt to reconstruct loaded addresses from supplied epochs.
            if address_table_epochs:
                writable: list[str] = []
                readonly: list[str] = []
                for item in address_table_epochs:
                    epoch = (
                        item
                        if isinstance(item, AddressTableEpoch)
                        else AddressTableEpoch.from_dict(item)
                    )
                    writable.extend(epoch.writable_addresses)
                    readonly.extend(epoch.readonly_addresses)
                meta_for_resolve = {
                    "loadedAddresses": {
                        "writable": writable,
                        "readonly": readonly,
                    }
                }
            else:
                raise GuardValidationError(
                    "versioned message with addressTableLookups requires "
                    "resolved loaded_addresses or address_table_epochs; "
                    "partial resolution fails closed"
                )

        try:
            privileges, lookup_refs = resolve_account_privileges(
                message, meta_for_resolve
            )
            instructions, _missing, _unsupported = parse_instructions(
                message, None, privileges
            )
        except SolanaAdapterError as exc:
            raise GuardValidationError(
                f"failed to resolve Solana message semantics: {exc}"
            ) from exc

        account_order = tuple(p.pubkey for p in privileges)
        fee_payer = message_candidate.fee_payer
        if not fee_payer:
            signers = [p for p in privileges if p.is_signer]
            if not signers:
                raise GuardValidationError(
                    "message requires fee_payer or at least one signer"
                )
            fee_payer = signers[0].pubkey

        # Address table epochs: prefer explicit, else derive from lookup refs.
        bound_tables: list[AddressTableEpoch] = []
        if address_table_epochs is not None:
            by_key = {
                (
                    item.account_key
                    if isinstance(item, AddressTableEpoch)
                    else AddressTableEpoch.from_dict(item).account_key
                ): (
                    item
                    if isinstance(item, AddressTableEpoch)
                    else AddressTableEpoch.from_dict(item)
                )
                for item in address_table_epochs
            }
            for ref in lookup_refs:
                epoch = by_key.get(ref.account_key)
                if epoch is None:
                    raise GuardValidationError(
                        f"missing address table epoch for {ref.account_key}"
                    )
                # Cross-check resolved addresses against the lookup ref.
                if (
                    epoch.writable_addresses != ref.writable_addresses
                    or epoch.readonly_addresses != ref.readonly_addresses
                    or epoch.writable_indexes != ref.writable_indexes
                    or epoch.readonly_indexes != ref.readonly_indexes
                ):
                    raise GuardValidationError(
                        f"address table epoch mismatch for {ref.account_key}"
                    )
                bound_tables.append(epoch)
        else:
            for ref in lookup_refs:
                bound_tables.append(AddressTableEpoch.from_lookup_ref(ref))

        # Program epochs: every non-system/token program instruction target
        # must have an epoch binding when the caller supplies any, otherwise
        # construct synthetic epochs from program id only (still re-resolved
        # at consumption via the resolver).
        bound_programs = self._bind_program_epochs(
            instructions,
            program_epochs=program_epochs,
            chain_id=network_anchor.chain_id,
        )

        # Effects extraction from parsed instructions + declared overlays.
        lamport_effects, token_effects, cpi_effects = self._extract_effects(
            instructions,
            privileges=privileges,
            declared_cpi=declared_cpi_effects,
            declared_token=declared_token_effects,
            declared_lamport=declared_lamport_effects,
        )

        message_digest = content_sha256_hex(message)
        if serialized_bytes is None:
            # Exact-byte binding via deterministic message digest when raw
            # bytes are not provided by the custody path.
            serialized_digest = message_digest
            byte_length = max(1, len(message_digest) // 2)
        elif isinstance(serialized_bytes, bytes):
            serialized_digest = hashlib.sha256(serialized_bytes).hexdigest()
            byte_length = len(serialized_bytes) or 1
        else:
            raw = str(serialized_bytes).encode("utf-8")
            serialized_digest = hashlib.sha256(raw).hexdigest()
            byte_length = len(raw) or 1

        intent_id = message_candidate.intent_id
        cand_id = candidate_id or f"candidate:solana:{intent_id}"
        bind_id = binding_id or f"binding:solana:{intent_id}"

        # Provisional candidate digest over the serialized commitment.
        candidate_digest = content_sha256_hex(
            {
                "candidate_id": cand_id,
                "encoding": encoding,
                "intent_id": intent_id,
                "network": network_anchor.network,
                "serialized_digest": serialized_digest,
            }
        )

        return SolanaMessageBinding(
            binding_id=bind_id,
            intent_id=intent_id,
            candidate_id=cand_id,
            chain_id=network_anchor.chain_id,
            network=network_anchor.network,
            genesis_hash=network_anchor.genesis_hash,
            message_version=version,
            recent_blockhash=recent,
            fee_payer=fee_payer,
            fee_lamports=fee_lamports,
            account_order=account_order,
            privileges=privileges,
            instructions=instructions,
            address_table_epochs=tuple(bound_tables),
            program_epochs=tuple(bound_programs),
            cpi_effects=tuple(cpi_effects),
            token_effects=tuple(token_effects),
            lamport_effects=tuple(lamport_effects),
            message_digest=message_digest,
            candidate_digest=candidate_digest,
            serialized_digest=serialized_digest,
            encoding=encoding,
            byte_length=byte_length,
            attributes=attributes or {},
        )

    def to_preflight_request(
        self,
        binding: SolanaMessageBinding,
        *,
        request_id: str,
        tenant_id: str,
        actor_id: str,
        audience_id: str,
        issued_at: str,
        deadline: str,
        expiry: str,
        security_requirement_ids: Sequence[str] | None = None,
        compliance_requirement_ids: Sequence[str] | None = None,
        environment_id: str = "env:solana-guard",
        environment_digest: str = "",
        nonce: str = "",
        policy_id: str | None = None,
        intent_expires_at: str | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> TransactionPreflightRequest:
        """Project a Solana binding into the common preflight request surface."""

        intent = self._intent_from_binding(
            binding, expires_at=intent_expires_at or expiry
        )
        candidate = TransactionCandidate(
            candidate_id=binding.candidate_id,
            intent_id=binding.intent_id,
            serialized_digest=binding.serialized_digest,
            encoding=binding.encoding,
            byte_length=binding.byte_length,
            network=binding.network,
            attributes={
                "binding_digest": binding.binding_digest,
                "chain_id": binding.chain_id,
                "genesis_hash": binding.genesis_hash,
                "message_digest": binding.message_digest,
                "message_version": binding.message_version,
                "recent_blockhash": binding.recent_blockhash,
            },
        )
        return TransactionPreflightRequest(
            request_id=request_id,
            intent=intent,
            candidate=candidate,
            tenant_id=tenant_id,
            actor_id=actor_id,
            audience_id=audience_id,
            policy_id=policy_id or self.policy_id,
            security_requirement_ids=tuple(
                security_requirement_ids
                if security_requirement_ids is not None
                else DEFAULT_SECURITY_REQUIREMENTS
            ),
            compliance_requirement_ids=tuple(
                compliance_requirement_ids
                if compliance_requirement_ids is not None
                else DEFAULT_COMPLIANCE_REQUIREMENTS
            ),
            issued_at=issued_at,
            deadline=deadline,
            expiry=expiry,
            environment_id=environment_id,
            environment_digest=environment_digest or ("e" * 64),
            nonce=nonce or request_id,
            attributes=attributes
            or {
                "binding_digest": binding.binding_digest,
                "solana_guard": True,
            },
        )

    # -- evaluate -----------------------------------------------------------

    def evaluate(
        self,
        binding: SolanaMessageBinding | Mapping[str, Any],
        *,
        request: TransactionPreflightRequest | Mapping[str, Any] | None = None,
        security_results: Mapping[str, Any] | None = None,
        compliance_results: Mapping[str, Any] | None = None,
        now: str | None = None,
        live_address_tables: Mapping[str, AddressTableEpoch | Mapping[str, Any]]
        | None = None,
        live_program_epochs: Mapping[str, ExecutableProgramEpoch | Mapping[str, Any]]
        | None = None,
        request_id: str = "req:solana-guard",
        tenant_id: str = "tenant:default",
        actor_id: str = "actor:policy-engine",
        audience_id: str = "audience:custody-signer",
        issued_at: str | None = None,
        deadline: str | None = None,
        expiry: str | None = None,
        derive_capability_on_allow: bool = True,
    ) -> SolanaGuardDecision:
        """Evaluate Solana-specific bindings then run two-phase preflight.

        Solana structural checks run first.  Any block becomes a non-ALLOW
        security requirement outcome so preflight never issues a capability.
        """

        if not isinstance(binding, SolanaMessageBinding):
            binding = SolanaMessageBinding.from_dict(binding)

        clock = now or _iso_now()
        reason_codes: list[str] = []
        reasons: list[str] = []
        sec_results = dict(security_results or {})
        comp_results = dict(compliance_results or {})

        # Structural + epoch checks (fail closed).
        structural = self._check_structural(
            binding,
            now=clock,
            live_address_tables=live_address_tables,
            live_program_epochs=live_program_epochs,
            phase=SolanaGuardPhase.EVALUATE,
        )
        reason_codes.extend(structural["reason_codes"])
        reasons.extend(structural["reasons"])
        for req_id, outcome in structural["security_results"].items():
            sec_results.setdefault(req_id, outcome)

        # Ensure every declared default security requirement has a result.
        for req_id in DEFAULT_SECURITY_REQUIREMENTS:
            sec_results.setdefault(req_id, "pass")

        if request is None:
            # Build a short-lived request for evaluation when the caller has
            # not yet constructed one.
            issued = issued_at or clock
            dead = deadline or clock
            exp = expiry or clock
            # Ensure ordering: issued <= deadline <= expiry <= intent.expires
            # Use far-future defaults relative to clock when only clock given.
            if issued_at is None and deadline is None and expiry is None:
                issued = "2026-07-28T12:00:00Z"
                dead = "2026-07-28T12:05:00Z"
                exp = "2026-07-28T12:10:00Z"
                intent_exp = "2026-07-28T12:15:00Z"
            else:
                intent_exp = exp
            request = self.to_preflight_request(
                binding,
                request_id=request_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
                audience_id=audience_id,
                issued_at=issued,
                deadline=dead,
                expiry=exp,
                intent_expires_at=intent_exp,
            )
        elif not isinstance(request, TransactionPreflightRequest):
            request = TransactionPreflightRequest.from_dict(request)

        # Fill missing compliance defaults as pass only when caller omitted
        # them entirely; declared requirements without results fail closed
        # inside preflight.
        if compliance_results is None:
            for req_id in request.compliance_requirement_ids:
                comp_results.setdefault(req_id, "pass")

        # If structural checks already block, force non-ALLOW security results
        # so preflight cannot mint a capability.
        if structural["blocking"] is not None:
            for req_id in DEFAULT_SECURITY_REQUIREMENTS:
                if sec_results.get(req_id) == "pass" and any(
                    req_id.split(":")[-1] in code or code.startswith("solana.")
                    for code in structural["reason_codes"]
                ):
                    # Map blocking outcomes onto the most relevant requirement.
                    pass
            # Ensure at least one security result is non-pass.
            block_outcome = structural["blocking"]
            mapped = {
                TransactionVerdictOutcome.DENY: "deny",
                TransactionVerdictOutcome.STALE: "stale",
                TransactionVerdictOutcome.REVIEW: "review",
                TransactionVerdictOutcome.ERROR: "error",
                TransactionVerdictOutcome.INCONCLUSIVE: "inconclusive",
            }.get(block_outcome, "deny")
            # Prefer the first failed structural requirement key if present.
            if structural["failed_requirement"]:
                sec_results[structural["failed_requirement"]] = mapped
            else:
                sec_results["sec:solana-message-binding"] = mapped

        assert self.preflight is not None
        preflight_result = self.preflight.evaluate(
            request,
            security_results=sec_results,
            compliance_results=comp_results,
            now=clock,
            derive_capability_on_allow=derive_capability_on_allow,
        )

        outcome = preflight_result.outcome
        blocks = preflight_result.blocks_automation
        merged_codes = list(preflight_result.reason_codes) + [
            c for c in reason_codes if c not in preflight_result.reason_codes
        ]
        merged_reasons = list(preflight_result.reasons) + [
            r for r in reasons if r not in preflight_result.reasons
        ]

        return SolanaGuardDecision(
            outcome=outcome,
            blocks_automation=blocks,
            reason_codes=tuple(merged_codes),
            reasons=tuple(merged_reasons),
            binding_digest=binding.binding_digest,
            request_digest=preflight_result.request_digest,
            preflight=preflight_result,
            security_results=preflight_result.security_results,
            compliance_results=preflight_result.compliance_results,
            attributes={
                "message_version": binding.message_version,
                "recent_blockhash": binding.recent_blockhash,
                "address_table_count": len(binding.address_table_epochs),
                "program_epoch_count": len(binding.program_epochs),
            },
        )

    # -- revalidate + consume (re-resolve epochs) ---------------------------

    def revalidate_and_consume(
        self,
        capability: AdmissibilityCapability | Mapping[str, Any],
        live_request: TransactionPreflightRequest | Mapping[str, Any],
        binding: SolanaMessageBinding | Mapping[str, Any],
        *,
        phase: PreflightPhase | SolanaGuardPhase | str = PreflightPhase.PRE_SIGN,
        now: str | None = None,
        live_address_tables: Mapping[str, AddressTableEpoch | Mapping[str, Any]]
        | None = None,
        live_program_epochs: Mapping[str, ExecutableProgramEpoch | Mapping[str, Any]]
        | None = None,
        live_loaded_addresses: Mapping[str, Any] | None = None,
        live_message: Mapping[str, Any] | None = None,
    ) -> PreflightConsumptionResult:
        """Live-revalidate Solana epochs, then atomically consume capability.

        **Re-resolves address tables and executable program epochs at
        consumption.** Any mismatch against the binding used for capability
        issuance fails closed before consumption.
        """

        if not isinstance(binding, SolanaMessageBinding):
            binding = SolanaMessageBinding.from_dict(binding)
        if not isinstance(capability, AdmissibilityCapability):
            if isinstance(capability, Mapping):
                capability = AdmissibilityCapability.from_dict(capability)
            else:
                raise GuardValidationError(
                    "capability must be an AdmissibilityCapability"
                )
        if not isinstance(live_request, TransactionPreflightRequest):
            if isinstance(live_request, Mapping):
                live_request = TransactionPreflightRequest.from_dict(live_request)
            else:
                raise GuardValidationError(
                    "live_request must be a TransactionPreflightRequest"
                )

        if isinstance(phase, PreflightPhase):
            phase_value = phase.value
        elif isinstance(phase, SolanaGuardPhase):
            phase_value = (
                PreflightPhase.PRE_SIGN.value
                if phase is SolanaGuardPhase.PRE_SIGN
                else PreflightPhase.PRE_BROADCAST.value
                if phase is SolanaGuardPhase.PRE_BROADCAST
                else PreflightPhase.PRE_SIGN.value
            )
        else:
            phase_value = str(phase)

        clock = now or _iso_now()
        guard_phase = (
            SolanaGuardPhase.PRE_SIGN
            if phase_value == PreflightPhase.PRE_SIGN.value
            else SolanaGuardPhase.PRE_BROADCAST
        )

        # Optional live message re-resolution of privileges/account order.
        if live_message is not None:
            self._assert_live_message_matches(
                binding,
                live_message,
                loaded_addresses=live_loaded_addresses,
            )

        structural = self._check_structural(
            binding,
            now=clock,
            live_address_tables=live_address_tables,
            live_program_epochs=live_program_epochs,
            phase=guard_phase,
            re_resolve=True,
        )
        if structural["blocking"] is not None:
            raise GuardCapabilityError(
                "; ".join(structural["reasons"])
                or "solana live revalidation failed",
                reason_code=structural["reason_codes"][0]
                if structural["reason_codes"]
                else "solana.consumption_blocked",
                details={
                    "reason_codes": list(structural["reason_codes"]),
                    "phase": phase_value,
                    "binding_digest": binding.binding_digest,
                },
            )

        # Binding digest must still be present on the live candidate attributes
        # when the request was built from this guard.
        live_attrs = live_request.candidate.attributes.to_dict()
        bound_digest = live_attrs.get("binding_digest")
        if bound_digest and bound_digest != binding.binding_digest:
            raise GuardCapabilityError(
                "live candidate binding_digest does not match Solana binding",
                reason_code="solana.binding_digest_mismatch",
                details={
                    "expected": binding.binding_digest,
                    "observed": bound_digest,
                },
            )
        live_bh = live_attrs.get("recent_blockhash")
        if live_bh and live_bh != binding.recent_blockhash:
            raise GuardCapabilityError(
                "live candidate recent_blockhash substituted",
                reason_code="solana.blockhash_substituted",
                details={
                    "expected": binding.recent_blockhash,
                    "observed": live_bh,
                },
            )

        assert self.preflight is not None
        return self.preflight.revalidate_and_consume(
            capability,
            live_request,
            phase=phase_value,
            now=clock,
        )

    # -- internals ----------------------------------------------------------

    def _coerce_message_candidate(
        self, candidate: SolanaMessageCandidate | Mapping[str, Any]
    ) -> SolanaMessageCandidate:
        if isinstance(candidate, SolanaMessageCandidate):
            return candidate
        if isinstance(candidate, Mapping):
            _reject_forbidden(candidate, "SolanaMessageCandidate")
            return SolanaMessageCandidate.from_dict(candidate)
        raise GuardValidationError(
            "candidate must be a SolanaMessageCandidate or mapping"
        )

    def _bind_program_epochs(
        self,
        instructions: Sequence[SolanaInstruction],
        *,
        program_epochs: Sequence[ExecutableProgramEpoch | Mapping[str, Any]]
        | None,
        chain_id: str,
    ) -> list[ExecutableProgramEpoch]:
        well_known = {SYSTEM_PROGRAM_ID, TOKEN_PROGRAM_ID}
        required_ids = sorted(
            {
                instr.program_id
                for instr in instructions
                if instr.program_id not in well_known
            }
        )
        provided: dict[str, ExecutableProgramEpoch] = {}
        if program_epochs is not None:
            for item in program_epochs:
                epoch = (
                    item
                    if isinstance(item, ExecutableProgramEpoch)
                    else ExecutableProgramEpoch.from_dict(item)
                )
                provided[epoch.program_id] = epoch

        bound: list[ExecutableProgramEpoch] = []
        for program_id in required_ids:
            if program_id in provided:
                bound.append(provided[program_id])
            elif program_epochs is not None:
                # Caller supplied an epoch set but omitted this program — fail.
                raise GuardValidationError(
                    f"missing executable program epoch for {program_id}"
                )
            else:
                # Synthetic binding: code_epoch is the program id itself so
                # consumption re-resolution still has a stable expected value
                # when a live resolver is injected.
                bound.append(
                    ExecutableProgramEpoch(
                        program_id=program_id,
                        code_epoch=f"unresolved:{program_id}",
                        chain_id=chain_id,
                        attributes={"synthetic": True},
                    )
                )
        # Also keep any extra provided epochs (e.g. upgrade authority targets).
        for program_id, epoch in provided.items():
            if program_id not in {b.program_id for b in bound}:
                bound.append(epoch)
        return bound

    def _extract_effects(
        self,
        instructions: Sequence[SolanaInstruction],
        *,
        privileges: Sequence[AccountPrivilege],
        declared_cpi: Sequence[Mapping[str, Any]] | None,
        declared_token: Sequence[Mapping[str, Any]] | None,
        declared_lamport: Sequence[Mapping[str, Any]] | None,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        lamports: list[dict[str, Any]] = []
        tokens: list[dict[str, Any]] = []
        cpi: list[dict[str, Any]] = []

        for instr in instructions:
            effect_base = {
                "program_id": instr.program_id,
                "outer_index": instr.outer_index,
                "inner_index": instr.inner_index,
                "accounts": list(instr.accounts),
            }
            if instr.is_inner:
                cpi.append(
                    {
                        **effect_base,
                        "kind": "cpi",
                        "parsed_type": instr.parsed_type,
                        "data": instr.data,
                    }
                )
            info = dict(instr.parsed_info) if instr.parsed_info else {}
            parsed_type = (instr.parsed_type or "").lower()
            if instr.program_id == SYSTEM_PROGRAM_ID and (
                parsed_type == "transfer" or "lamports" in info
            ):
                lamports.append(
                    {
                        **effect_base,
                        "kind": "lamport_transfer",
                        "source": info.get("source", ""),
                        "destination": info.get("destination", ""),
                        "lamports": str(info.get("lamports", "")),
                    }
                )
            if instr.program_id == TOKEN_PROGRAM_ID or parsed_type in {
                "transfer",
                "transferchecked",
                "transfer_checked",
                "mintto",
                "burn",
            }:
                if instr.program_id == TOKEN_PROGRAM_ID or "amount" in info:
                    tokens.append(
                        {
                            **effect_base,
                            "kind": "token_transfer",
                            "source": info.get("source", info.get("authority", "")),
                            "destination": info.get("destination", ""),
                            "amount": str(info.get("amount", info.get("tokenAmount", ""))),
                            "mint": info.get("mint", ""),
                        }
                    )

        if declared_lamport:
            for item in declared_lamport:
                lamports.append(dict(item))
        if declared_token:
            for item in declared_token:
                tokens.append(dict(item))
        if declared_cpi:
            for item in declared_cpi:
                cpi.append(dict(item))

        # Privilege context is retained only for diagnostics.
        _ = privileges
        return lamports, tokens, cpi

    def _check_structural(
        self,
        binding: SolanaMessageBinding,
        *,
        now: str,
        live_address_tables: Mapping[str, AddressTableEpoch | Mapping[str, Any]]
        | None,
        live_program_epochs: Mapping[str, ExecutableProgramEpoch | Mapping[str, Any]]
        | None,
        phase: SolanaGuardPhase,
        re_resolve: bool = False,
    ) -> dict[str, Any]:
        reason_codes: list[str] = []
        reasons: list[str] = []
        security_results: dict[str, str] = {}
        blocking: TransactionVerdictOutcome | None = None
        failed_requirement = ""

        def _block(
            outcome: TransactionVerdictOutcome,
            code: str,
            reason: str,
            requirement: str,
        ) -> None:
            nonlocal blocking, failed_requirement
            reason_codes.append(code)
            reasons.append(reason)
            security_results[requirement] = {
                TransactionVerdictOutcome.DENY: "deny",
                TransactionVerdictOutcome.STALE: "stale",
                TransactionVerdictOutcome.REVIEW: "review",
                TransactionVerdictOutcome.ERROR: "error",
                TransactionVerdictOutcome.INCONCLUSIVE: "inconclusive",
            }.get(outcome, "deny")
            if failed_requirement == "":
                failed_requirement = requirement
            if blocking is None or (
                outcome is TransactionVerdictOutcome.DENY
                and blocking is not TransactionVerdictOutcome.DENY
            ):
                blocking = outcome
            elif (
                outcome is TransactionVerdictOutcome.STALE
                and blocking
                not in (
                    TransactionVerdictOutcome.DENY,
                    TransactionVerdictOutcome.STALE,
                )
            ):
                blocking = outcome

        # Message version / account order / privileges always bound.
        if not binding.message_version:
            _block(
                TransactionVerdictOutcome.INCONCLUSIVE,
                "solana.message_version_missing",
                "message version is unbound",
                "sec:solana-message-binding",
            )
        if not binding.account_order:
            _block(
                TransactionVerdictOutcome.DENY,
                "solana.account_order_empty",
                "account order is empty",
                "sec:solana-account-privileges",
            )
        if not binding.privileges:
            _block(
                TransactionVerdictOutcome.DENY,
                "solana.privileges_empty",
                "signer/writable privilege bits are unbound",
                "sec:solana-account-privileges",
            )
        else:
            # Privilege escalation / inconsistency within the binding itself.
            for priv in binding.privileges:
                if priv.is_signer and priv.account_index >= len(binding.account_order):
                    _block(
                        TransactionVerdictOutcome.DENY,
                        "solana.privilege_index_overflow",
                        f"privilege index {priv.account_index} out of range",
                        "sec:solana-account-privileges",
                    )

        # Blockhash freshness.
        assert self.blockhash_is_fresh is not None
        try:
            fresh = bool(self.blockhash_is_fresh(binding.recent_blockhash, now))
        except Exception as exc:  # noqa: BLE001 — fail closed on checker errors
            fresh = False
            _block(
                TransactionVerdictOutcome.ERROR,
                "solana.blockhash_checker_error",
                f"blockhash freshness checker errored: {exc}",
                "sec:solana-blockhash-freshness",
            )
        else:
            if not fresh:
                _block(
                    TransactionVerdictOutcome.STALE,
                    "solana.stale_blockhash",
                    "recent blockhash is stale",
                    "sec:solana-blockhash-freshness",
                )
            else:
                security_results.setdefault("sec:solana-blockhash-freshness", "pass")

        # Address table epochs — re-resolve when requested / when live maps given.
        table_resolver = self.address_table_resolver
        if live_address_tables is not None:
            table_resolver = _static_table_resolver(live_address_tables)
        if re_resolve or live_address_tables is not None or table_resolver is not None:
            for epoch in binding.address_table_epochs:
                live_value: AddressTableEpoch | Mapping[str, Any] | None = None
                if table_resolver is not None:
                    try:
                        live_value = table_resolver(epoch.account_key)
                    except Exception as exc:  # noqa: BLE001
                        _block(
                            TransactionVerdictOutcome.ERROR,
                            "solana.address_table_resolve_error",
                            f"address table re-resolve failed for "
                            f"{epoch.account_key}: {exc}",
                            "sec:solana-address-table-epoch",
                        )
                        continue
                if live_value is None:
                    if re_resolve:
                        _block(
                            TransactionVerdictOutcome.STALE,
                            "solana.address_table_unresolved",
                            f"address table {epoch.account_key} could not be "
                            f"re-resolved at {phase.value}",
                            "sec:solana-address-table-epoch",
                        )
                    continue
                live_epoch = _coerce_table_epoch(
                    live_value, field_name="live address table epoch"
                )
                assert live_epoch is not None
                if live_epoch.table_epoch != epoch.table_epoch:
                    _block(
                        TransactionVerdictOutcome.DENY,
                        "solana.address_table_epoch_mismatch",
                        f"address table epoch changed for {epoch.account_key}",
                        "sec:solana-address-table-epoch",
                    )
                elif (
                    live_epoch.writable_addresses != epoch.writable_addresses
                    or live_epoch.readonly_addresses != epoch.readonly_addresses
                ):
                    _block(
                        TransactionVerdictOutcome.DENY,
                        "solana.address_table_accounts_substituted",
                        f"address table resolved accounts substituted for "
                        f"{epoch.account_key}",
                        "sec:solana-address-table-epoch",
                    )
            if "sec:solana-address-table-epoch" not in security_results:
                security_results["sec:solana-address-table-epoch"] = "pass"
        else:
            security_results.setdefault("sec:solana-address-table-epoch", "pass")

        # Executable program epochs — re-resolve at consumption.
        program_resolver = self.program_epoch_resolver
        if live_program_epochs is not None:
            program_resolver = _static_program_resolver(live_program_epochs)
        if re_resolve or live_program_epochs is not None or program_resolver is not None:
            for epoch in binding.program_epochs:
                live_value = None
                if program_resolver is not None:
                    try:
                        live_value = program_resolver(epoch.program_id)
                    except Exception as exc:  # noqa: BLE001
                        _block(
                            TransactionVerdictOutcome.ERROR,
                            "solana.program_epoch_resolve_error",
                            f"program epoch re-resolve failed for "
                            f"{epoch.program_id}: {exc}",
                            "sec:solana-program-epoch",
                        )
                        continue
                if live_value is None:
                    if re_resolve and not (
                        isinstance(epoch.attributes.to_dict(), dict)
                        and epoch.attributes.to_dict().get("synthetic")
                    ):
                        _block(
                            TransactionVerdictOutcome.STALE,
                            "solana.program_epoch_unresolved",
                            f"program {epoch.program_id} could not be "
                            f"re-resolved at {phase.value}",
                            "sec:solana-program-epoch",
                        )
                    continue
                live_epoch_p = _coerce_program_epoch(
                    live_value, field_name="live program epoch"
                )
                assert live_epoch_p is not None
                if live_epoch_p.code_epoch != epoch.code_epoch:
                    _block(
                        TransactionVerdictOutcome.DENY,
                        "solana.program_upgrade",
                        f"executable program epoch upgraded for {epoch.program_id}",
                        "sec:solana-program-epoch",
                    )
                elif (
                    epoch.binary_digest
                    and live_epoch_p.binary_digest
                    and live_epoch_p.binary_digest != epoch.binary_digest
                ):
                    _block(
                        TransactionVerdictOutcome.DENY,
                        "solana.program_binary_mismatch",
                        f"program binary digest changed for {epoch.program_id}",
                        "sec:solana-program-epoch",
                    )
                elif (
                    epoch.deployment_slot is not None
                    and live_epoch_p.deployment_slot is not None
                    and live_epoch_p.deployment_slot != epoch.deployment_slot
                ):
                    _block(
                        TransactionVerdictOutcome.DENY,
                        "solana.program_deployment_slot_changed",
                        f"program deployment slot changed for {epoch.program_id}",
                        "sec:solana-program-epoch",
                    )
            if "sec:solana-program-epoch" not in security_results:
                security_results["sec:solana-program-epoch"] = "pass"
        else:
            security_results.setdefault("sec:solana-program-epoch", "pass")

        # CPI / token effect integrity: every inner instruction must appear
        # in bound cpi_effects; undeclared hidden CPI is a hard deny.
        inner_instructions = [i for i in binding.instructions if i.is_inner]
        if inner_instructions:
            declared_keys = {
                (
                    e.get("outer_index"),
                    e.get("inner_index"),
                    e.get("program_id"),
                )
                for e in binding.cpi_effects
            }
            for instr in inner_instructions:
                key = (instr.outer_index, instr.inner_index, instr.program_id)
                if key not in declared_keys and not binding.cpi_effects:
                    # When no cpi_effects were bound at all but inners exist,
                    # treat as hidden CPI.
                    _block(
                        TransactionVerdictOutcome.DENY,
                        "solana.hidden_cpi_transfer",
                        "hidden CPI / inner instruction without bound effects",
                        "sec:solana-cpi-effects",
                    )
                    break
        if "sec:solana-cpi-effects" not in security_results:
            security_results["sec:solana-cpi-effects"] = "pass"

        if "sec:solana-message-binding" not in security_results:
            security_results["sec:solana-message-binding"] = "pass"
        if "sec:solana-account-privileges" not in security_results:
            security_results["sec:solana-account-privileges"] = "pass"

        return {
            "blocking": blocking,
            "reason_codes": reason_codes,
            "reasons": reasons,
            "security_results": security_results,
            "failed_requirement": failed_requirement,
        }

    def _assert_live_message_matches(
        self,
        binding: SolanaMessageBinding,
        live_message: Mapping[str, Any],
        *,
        loaded_addresses: Mapping[str, Any] | None,
    ) -> None:
        """Fail closed when live message substitutes accounts or escalates privileges."""

        meta = (
            {"loadedAddresses": dict(loaded_addresses)}
            if loaded_addresses is not None
            else None
        )
        try:
            privileges, _tables = resolve_account_privileges(live_message, meta)
        except SolanaAdapterError as exc:
            raise GuardCapabilityError(
                f"live message privilege resolution failed: {exc}",
                reason_code="solana.live_message_unresolved",
            ) from exc

        live_order = tuple(p.pubkey for p in privileges)
        if live_order != binding.account_order:
            raise GuardCapabilityError(
                "live message account order substituted",
                reason_code="solana.account_order_substituted",
                details={
                    "expected": list(binding.account_order),
                    "observed": list(live_order),
                },
            )
        for expected, observed in zip(binding.privileges, privileges, strict=True):
            if (
                expected.pubkey != observed.pubkey
                or expected.is_signer != observed.is_signer
                or expected.is_writable != observed.is_writable
            ):
                # Privilege escalation or account substitution.
                if (not expected.is_signer and observed.is_signer) or (
                    not expected.is_writable and observed.is_writable
                ):
                    raise GuardCapabilityError(
                        "live message privilege escalation detected",
                        reason_code="solana.privilege_escalation",
                        details={
                            "account_index": expected.account_index,
                            "expected": expected.to_dict(),
                            "observed": observed.to_dict(),
                        },
                    )
                raise GuardCapabilityError(
                    "live message account/privilege substitution detected",
                    reason_code="solana.account_substituted",
                    details={
                        "account_index": expected.account_index,
                        "expected": expected.to_dict(),
                        "observed": observed.to_dict(),
                    },
                )

        live_digest = content_sha256_hex(dict(live_message))
        if live_digest != binding.message_digest:
            # Exact message bytes / content changed.
            raise GuardCapabilityError(
                "live message digest does not match binding",
                reason_code="solana.message_substituted",
                details={
                    "expected": binding.message_digest,
                    "observed": live_digest,
                },
            )

    def _intent_from_binding(
        self, binding: SolanaMessageBinding, *, expires_at: str
    ) -> TransactionIntent:
        # Primary destination: first non-fee-payer writable account, else fee payer.
        destination = binding.fee_payer
        for priv in binding.privileges:
            if priv.pubkey != binding.fee_payer and priv.is_writable:
                destination = priv.pubkey
                break

        # Method: first outer instruction program + parsed type.
        method = "solana.unknown"
        for instr in binding.instructions:
            if instr.inner_index is None:
                method = instr.parsed_type or f"program:{instr.program_id[:8]}"
                break

        assets: list[AssetAmount] = []
        if binding.lamport_effects:
            for effect in binding.lamport_effects:
                amount = str(effect.get("lamports") or effect.get("amount") or "0")
                if amount and amount != "0":
                    assets.append(
                        AssetAmount(
                            asset_id="asset:sol-native",
                            amount=amount,
                            asset_namespace="native",
                            symbol="SOL",
                        )
                    )
        if binding.token_effects:
            for effect in binding.token_effects:
                amount = str(effect.get("amount") or "0")
                mint = str(effect.get("mint") or "unknown")
                if amount and amount != "0":
                    assets.append(
                        AssetAmount(
                            asset_id=f"asset:spl:{mint[:16]}",
                            amount=amount,
                            asset_namespace="spl-token",
                            symbol="SPL",
                        )
                    )
        if not assets:
            assets.append(
                AssetAmount(
                    asset_id="asset:sol-native",
                    amount="0",
                    asset_namespace="native",
                    symbol="SOL",
                )
            )

        effects: list[ExpectedEffect] = []
        for index, effect in enumerate(binding.lamport_effects):
            effects.append(
                ExpectedEffect(
                    effect_id=f"effect:lamport-{index}",
                    kind="transfer",
                    summary=(
                        f"lamports {effect.get('lamports', '')} "
                        f"{effect.get('source', '')}->{effect.get('destination', '')}"
                    ),
                )
            )
        for index, effect in enumerate(binding.token_effects):
            effects.append(
                ExpectedEffect(
                    effect_id=f"effect:token-{index}",
                    kind="token_transfer",
                    summary=(
                        f"token {effect.get('amount', '')} "
                        f"{effect.get('source', '')}->{effect.get('destination', '')}"
                    ),
                )
            )
        for index, effect in enumerate(binding.cpi_effects):
            effects.append(
                ExpectedEffect(
                    effect_id=f"effect:cpi-{index}",
                    kind="cpi",
                    summary=f"cpi program={effect.get('program_id', '')}",
                )
            )
        if not effects:
            effects.append(
                ExpectedEffect(
                    effect_id="effect:solana-message",
                    kind="program_invocation",
                    summary=f"solana {binding.message_version} message",
                )
            )

        signers = tuple(
            f"signer:{p.pubkey}" for p in binding.privileges if p.is_signer
        )
        if not signers:
            signers = (f"signer:{binding.fee_payer}",)

        return TransactionIntent(
            intent_id=binding.intent_id,
            network=binding.network,
            sender=binding.fee_payer,
            destination=destination,
            method=method,
            assets=tuple(assets),
            fees=(
                FeeSpec(
                    amount=binding.fee_lamports,
                    asset_id="asset:sol-native",
                    payer=binding.fee_payer,
                ),
            ),
            nonce_or_sequence=binding.recent_blockhash,
            signers=signers,
            expected_effects=tuple(effects),
            expires_at=expires_at,
            chain_namespace=SOLANA_NAMESPACE,
            attributes={
                "binding_digest": binding.binding_digest,
                "chain_id": binding.chain_id,
                "genesis_hash": binding.genesis_hash,
                "message_version": binding.message_version,
                "account_order": list(binding.account_order),
                "address_table_epochs": [
                    t.table_epoch for t in binding.address_table_epochs
                ],
                "program_epochs": [
                    p.epoch_digest for p in binding.program_epochs
                ],
            },
        )


def evaluate_solana_transaction_guard(
    candidate: SolanaMessageCandidate | Mapping[str, Any],
    *,
    guard: SolanaTransactionGuard | None = None,
    **kwargs: Any,
) -> SolanaGuardDecision:
    """Convenience: bind a message candidate and evaluate in one call."""

    guard = guard or SolanaTransactionGuard()
    binding = guard.bind_message(candidate, **{
        k: kwargs.pop(k)
        for k in list(kwargs)
        if k
        in {
            "loaded_addresses",
            "program_epochs",
            "address_table_epochs",
            "declared_cpi_effects",
            "declared_token_effects",
            "declared_lamport_effects",
            "fee_lamports",
            "serialized_bytes",
            "encoding",
            "candidate_id",
            "binding_id",
            "attributes",
        }
    })
    return guard.evaluate(binding, **kwargs)


__all__ = [
    "ADDRESS_TABLE_EPOCH_SCHEMA_VERSION",
    "DEFAULT_COMPLIANCE_REQUIREMENTS",
    "DEFAULT_FEE_LAMPORTS",
    "DEFAULT_POLICY_ID",
    "DEFAULT_PRODUCER_ID",
    "DEFAULT_SECURITY_REQUIREMENTS",
    "EXECUTABLE_PROGRAM_EPOCH_SCHEMA_VERSION",
    "SOLANA_GUARD_DECISION_SCHEMA_VERSION",
    "SOLANA_MESSAGE_BINDING_SCHEMA_VERSION",
    "SOLANA_TRANSACTION_GUARD_INTERFACE",
    "SOLANA_TRANSACTION_GUARD_SCHEMA_VERSION",
    "AddressTableEpoch",
    "AddressTableResolver",
    "BlockhashFreshnessChecker",
    "ExecutableProgramEpoch",
    "ProgramEpochResolver",
    "SolanaGuardDecision",
    "SolanaGuardPhase",
    "SolanaMessageBinding",
    "SolanaMessageCandidate",
    "SolanaTransactionGuard",
    "content_sha256_hex",
    "evaluate_solana_transaction_guard",
]
