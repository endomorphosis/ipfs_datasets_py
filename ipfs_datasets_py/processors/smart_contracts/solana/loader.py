"""Solana BPF/SBF loader state and upgrade authority (CRYPTOIR-G230).

Models loader version, executable/program-data account relation, and upgrade
authority as first-class deployment semantics.  Importing this module performs
no network I/O, secret resolution, or package installation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from ..artifacts import bytes_digest
from ..canonical import content_digest, freeze_json, thaw_json
from ..errors import InvalidRequestError
from ..models import ensure_secret_safe


LOADER_SCHEMA_VERSION = "smart-contract-solana-loader-v1"

# Canonical loader program ids (base58, 32-byte public keys).
BPF_LOADER_DEPRECATED = "BPFLoader1111111111111111111111111111111111"
BPF_LOADER_V2 = "BPFLoader2111111111111111111111111111111111"
BPF_LOADER_UPGRADEABLE = "BPFLoaderUpgradeab1e11111111111111111111111"
LOADER_V4 = "LoaderV411111111111111111111111111111111111"
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"

KNOWN_LOADERS: frozenset[str] = frozenset(
    {
        BPF_LOADER_DEPRECATED,
        BPF_LOADER_V2,
        BPF_LOADER_UPGRADEABLE,
        LOADER_V4,
    }
)

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX = {ch: i for i, ch in enumerate(_BASE58_ALPHABET)}


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


def decode_base58(value: object, *, field: str = "value") -> bytes:
    """Decode a Solana base58 string without optional dependencies."""

    if not isinstance(value, str) or not value:
        raise InvalidRequestError(f"{field} must be a non-empty base58 string")
    number = 0
    try:
        for character in value:
            number = number * 58 + _BASE58_INDEX[character]
    except KeyError as exc:
        raise InvalidRequestError(f"{field} contains non-base58 characters") from exc
    if number == 0:
        raw = b""
    else:
        length = (number.bit_length() + 7) // 8
        raw = number.to_bytes(length, "big")
    pad = 0
    for character in value:
        if character == "1":
            pad += 1
        else:
            break
    return b"\x00" * pad + raw


def encode_base58(data: bytes) -> str:
    """Encode bytes as Solana base58 (no checksum)."""

    if type(data) is not bytes:
        raise InvalidRequestError("base58 encode input must be bytes")
    number = int.from_bytes(data, "big")
    if number == 0:
        out = ""
    else:
        out = ""
        while number:
            number, rem = divmod(number, 58)
            out = _BASE58_ALPHABET[rem] + out
    pad = 0
    for byte in data:
        if byte == 0:
            pad += 1
        else:
            break
    return ("1" * pad) + (out or "1")


def normalize_pubkey(value: object, *, field: str = "pubkey") -> str:
    """Validate a 32-byte Solana public key and preserve its base58 spelling."""

    text = _required_text(str(value) if value is not None else "", field)
    if len(decode_base58(text, field=field)) != 32:
        raise InvalidRequestError(f"{field} must decode to exactly 32 bytes")
    return text


class LoaderVersion(StrEnum):
    """Known Solana program loader families."""

    BPF_DEPRECATED = "bpf_loader_deprecated"
    BPF_V2 = "bpf_loader_v2"
    BPF_UPGRADEABLE = "bpf_loader_upgradeable"
    LOADER_V4 = "loader_v4"
    UNKNOWN = "unknown"


class ProgramAccountKind(StrEnum):
    """Role of a Solana account in the loader layout."""

    EXECUTABLE_PROGRAM = "executable_program"
    PROGRAM_DATA = "program_data"
    BUFFER = "buffer"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class UpgradeAuthorityState(StrEnum):
    """Whether a program remains upgradeable and who holds authority."""

    AUTHORITY_SET = "authority_set"
    IMMUTABLE = "immutable"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


def classify_loader(loader_program_id: str) -> LoaderVersion:
    """Map a loader program id to a closed loader version enum."""

    loader = normalize_pubkey(loader_program_id, field="loader_program_id")
    if loader == BPF_LOADER_DEPRECATED:
        return LoaderVersion.BPF_DEPRECATED
    if loader == BPF_LOADER_V2:
        return LoaderVersion.BPF_V2
    if loader == BPF_LOADER_UPGRADEABLE:
        return LoaderVersion.BPF_UPGRADEABLE
    if loader == LOADER_V4:
        return LoaderVersion.LOADER_V4
    return LoaderVersion.UNKNOWN


@dataclass(frozen=True, slots=True)
class UpgradeAuthority:
    """Explicit upgrade-authority binding for a deployed program.

    Empty ``authority_pubkey`` with ``IMMUTABLE`` means the program data
    authority was revoked.  ``UNKNOWN`` never implies immutability.
    """

    state: UpgradeAuthorityState
    authority_pubkey: str = ""
    program_data_address: str = ""
    slot_observed: int | None = None
    diagnostics: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LOADER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        state = (
            self.state
            if isinstance(self.state, UpgradeAuthorityState)
            else UpgradeAuthorityState(str(self.state))
        )
        object.__setattr__(self, "state", state)
        if self.authority_pubkey:
            object.__setattr__(
                self,
                "authority_pubkey",
                normalize_pubkey(self.authority_pubkey, field="authority_pubkey"),
            )
        else:
            object.__setattr__(self, "authority_pubkey", "")
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
        if self.slot_observed is not None:
            object.__setattr__(
                self,
                "slot_observed",
                _non_negative(self.slot_observed, "slot_observed"),
            )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                _required_text(item, "diagnostics item") for item in self.diagnostics
            ),
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        if state is UpgradeAuthorityState.AUTHORITY_SET and not self.authority_pubkey:
            raise InvalidRequestError(
                "AUTHORITY_SET requires a non-empty authority_pubkey"
            )
        if state is UpgradeAuthorityState.IMMUTABLE and self.authority_pubkey:
            raise InvalidRequestError(
                "IMMUTABLE upgrade authority must not carry an authority_pubkey"
            )
        if state is UpgradeAuthorityState.UNKNOWN and not self.diagnostics:
            raise InvalidRequestError(
                "UNKNOWN upgrade authority requires diagnostics"
            )
        ensure_secret_safe(self.to_dict())

    @property
    def is_upgradeable(self) -> bool:
        return self.state is UpgradeAuthorityState.AUTHORITY_SET

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "authority_pubkey": self.authority_pubkey,
            "diagnostics": list(self.diagnostics),
            "program_data_address": self.program_data_address,
            "schema_version": self.schema_version,
            "slot_observed": self.slot_observed,
            "state": self.state.value
            if isinstance(self.state, UpgradeAuthorityState)
            else str(self.state),
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class ProgramAccountRelation:
    """Executable program account ↔ program-data account binding.

    For upgradeable loaders the executable account is a thin pointer; the
    binary lives in the program-data account.  Non-upgradeable loaders bind
    the binary directly on the program account.
    """

    program_id: str
    account_kind: ProgramAccountKind
    loader_version: LoaderVersion
    loader_program_id: str
    program_data_address: str = ""
    executable: bool = True
    owner_program_id: str = ""
    binary_digest: str = ""
    deployment_slot: int | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LOADER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "program_id", normalize_pubkey(self.program_id, field="program_id")
        )
        kind = (
            self.account_kind
            if isinstance(self.account_kind, ProgramAccountKind)
            else ProgramAccountKind(str(self.account_kind))
        )
        object.__setattr__(self, "account_kind", kind)
        loader = (
            self.loader_version
            if isinstance(self.loader_version, LoaderVersion)
            else LoaderVersion(str(self.loader_version))
        )
        object.__setattr__(self, "loader_version", loader)
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
        if not isinstance(self.executable, bool):
            raise InvalidRequestError("executable must be a bool")
        if self.owner_program_id:
            object.__setattr__(
                self,
                "owner_program_id",
                normalize_pubkey(self.owner_program_id, field="owner_program_id"),
            )
        else:
            object.__setattr__(self, "owner_program_id", self.loader_program_id)
        if self.binary_digest:
            digest = _required_text(self.binary_digest, "binary_digest")
            if not digest.startswith("sha256:"):
                raise InvalidRequestError("binary_digest must be a tagged sha256 digest")
            object.__setattr__(self, "binary_digest", digest)
        else:
            object.__setattr__(self, "binary_digest", "")
        if self.deployment_slot is not None:
            object.__setattr__(
                self,
                "deployment_slot",
                _non_negative(self.deployment_slot, "deployment_slot"),
            )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        # Upgradeable layout requires an explicit program-data pointer.
        if (
            loader is LoaderVersion.BPF_UPGRADEABLE
            and kind is ProgramAccountKind.EXECUTABLE_PROGRAM
            and not self.program_data_address
        ):
            raise InvalidRequestError(
                "upgradeable executable program requires program_data_address"
            )
        ensure_secret_safe(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_kind": self.account_kind.value
            if isinstance(self.account_kind, ProgramAccountKind)
            else str(self.account_kind),
            "attributes": thaw_json(self.attributes),
            "binary_digest": self.binary_digest,
            "deployment_slot": self.deployment_slot,
            "executable": self.executable,
            "loader_program_id": self.loader_program_id,
            "loader_version": self.loader_version.value
            if isinstance(self.loader_version, LoaderVersion)
            else str(self.loader_version),
            "owner_program_id": self.owner_program_id,
            "program_data_address": self.program_data_address,
            "program_id": self.program_id,
            "schema_version": self.schema_version,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


def bind_program_relation(
    *,
    program_id: str,
    loader_program_id: str,
    program_data_address: str = "",
    sbf_elf: bytes = b"",
    deployment_slot: int | None = None,
    executable: bool = True,
    account_kind: ProgramAccountKind | str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> ProgramAccountRelation:
    """Build an executable/program-data relation from observed loader fields."""

    loader_version = classify_loader(loader_program_id)
    kind: ProgramAccountKind
    if account_kind is not None:
        kind = (
            account_kind
            if isinstance(account_kind, ProgramAccountKind)
            else ProgramAccountKind(str(account_kind))
        )
    elif program_data_address and loader_version is LoaderVersion.BPF_UPGRADEABLE:
        kind = ProgramAccountKind.EXECUTABLE_PROGRAM
    elif loader_version is LoaderVersion.UNKNOWN:
        kind = ProgramAccountKind.UNKNOWN
    else:
        kind = ProgramAccountKind.EXECUTABLE_PROGRAM

    binary_digest = bytes_digest(sbf_elf) if sbf_elf else ""
    return ProgramAccountRelation(
        program_id=program_id,
        account_kind=kind,
        loader_version=loader_version,
        loader_program_id=loader_program_id,
        program_data_address=program_data_address,
        executable=executable,
        owner_program_id=loader_program_id,
        binary_digest=binary_digest,
        deployment_slot=deployment_slot,
        attributes=dict(attributes or {}),
    )


def bind_upgrade_authority(
    *,
    authority_pubkey: str | None = None,
    program_data_address: str = "",
    slot_observed: int | None = None,
    loader_version: LoaderVersion | str = LoaderVersion.BPF_UPGRADEABLE,
    attributes: Mapping[str, Any] | None = None,
) -> UpgradeAuthority:
    """Bind upgrade authority; ``None`` authority means immutable when upgradeable."""

    loader = (
        loader_version
        if isinstance(loader_version, LoaderVersion)
        else LoaderVersion(str(loader_version))
    )
    if loader not in {
        LoaderVersion.BPF_UPGRADEABLE,
        LoaderVersion.LOADER_V4,
    }:
        return UpgradeAuthority(
            state=UpgradeAuthorityState.NOT_APPLICABLE,
            program_data_address=program_data_address,
            slot_observed=slot_observed,
            diagnostics=(
                f"upgrade authority not applicable for loader {loader.value}",
            ),
            attributes=dict(attributes or {}),
        )
    if authority_pubkey is None:
        # Explicit absence vs empty string: None means "not observed" → UNKNOWN.
        return UpgradeAuthority(
            state=UpgradeAuthorityState.UNKNOWN,
            program_data_address=program_data_address,
            slot_observed=slot_observed,
            diagnostics=("upgrade authority not observed on program-data account",),
            attributes=dict(attributes or {}),
        )
    if authority_pubkey == "":
        return UpgradeAuthority(
            state=UpgradeAuthorityState.IMMUTABLE,
            program_data_address=program_data_address,
            slot_observed=slot_observed,
            attributes=dict(attributes or {}),
        )
    return UpgradeAuthority(
        state=UpgradeAuthorityState.AUTHORITY_SET,
        authority_pubkey=authority_pubkey,
        program_data_address=program_data_address,
        slot_observed=slot_observed,
        attributes=dict(attributes or {}),
    )


__all__ = [
    "BPF_LOADER_DEPRECATED",
    "BPF_LOADER_UPGRADEABLE",
    "BPF_LOADER_V2",
    "KNOWN_LOADERS",
    "LOADER_SCHEMA_VERSION",
    "LOADER_V4",
    "SYSTEM_PROGRAM_ID",
    "LoaderVersion",
    "ProgramAccountKind",
    "ProgramAccountRelation",
    "UpgradeAuthority",
    "UpgradeAuthorityState",
    "bind_program_relation",
    "bind_upgrade_authority",
    "classify_loader",
    "decode_base58",
    "encode_base58",
    "normalize_pubkey",
]
