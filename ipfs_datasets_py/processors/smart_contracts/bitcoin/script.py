"""Bitcoin Script decoding and stack/spending-path semantics (CRYPTOIR-G250).

Models **spend conditions** for UTXO locking scripts — not account contracts.
Legacy Script, SegWit v0 redeem/witness programs, stack effects, prevout
bindings, sighash flags, timelocks, hashlocks, and resource bounds are first
class and fail closed when incomplete.

Importing this module performs no network I/O, secret resolution, or package
installation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Any

from ..artifacts import bytes_digest
from ..canonical import content_digest, freeze_json, thaw_json
from ..errors import InvalidRequestError, ResourceLimitError
from ..models import ensure_secret_safe


SCRIPT_SCHEMA_VERSION = "smart-contract-bitcoin-script-v1"
DEFAULT_MAX_SCRIPT_BYTES = 10_000
DEFAULT_MAX_OPS = 201
DEFAULT_MAX_STACK_ITEMS = 1_000
DEFAULT_MAX_WITNESS_ITEMS = 100
DEFAULT_MAX_PUSH_BYTES = 520

_HEX_RE = re.compile(r"^(?:[0-9a-fA-F]{2})*$")


class ScriptVersion(StrEnum):
    """Script execution version / witness program class."""

    LEGACY = "legacy"
    SEG_WIT_V0 = "segwit_v0"
    TAPSCRIPT = "tapscript"
    UNKNOWN = "unknown"


class ScriptForm(StrEnum):
    """Standard locking / redeem script forms."""

    P2PKH = "p2pkh"
    P2SH = "p2sh"
    P2WPKH = "p2wpkh"
    P2WSH = "p2wsh"
    P2TR = "p2tr"
    P2PK = "p2pk"
    MULTISIG = "multisig"
    NULL_DATA = "null_data"
    TIMELOCK = "timelock"
    HASHLOCK = "hashlock"
    UNKNOWN = "unknown"
    COINBASE = "coinbase"


class SemanticPassStatus(StrEnum):
    """Outcome of a stack/spending-path semantic claim."""

    PASS = "pass"
    FAIL_CLOSED = "fail_closed"
    INCOMPLETE = "incomplete"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class SighashFlag(IntEnum):
    """BIP-143 / BIP-341 sighash type bits (single-byte type)."""

    ALL = 0x01
    NONE = 0x02
    SINGLE = 0x03
    ANYONECANPAY = 0x80
    DEFAULT = 0x00  # Taproot key-path default (treated as ALL for binding)


# Opcode mnemonics for a closed, offline decoder (not a full Script VM).
KNOWN_OPCODES: Mapping[int, str] = MappingProxyType(
    {
        0x00: "OP_0",
        0x4C: "OP_PUSHDATA1",
        0x4D: "OP_PUSHDATA2",
        0x4E: "OP_PUSHDATA4",
        0x51: "OP_1",
        0x52: "OP_2",
        0x53: "OP_3",
        0x54: "OP_4",
        0x55: "OP_5",
        0x56: "OP_6",
        0x57: "OP_7",
        0x58: "OP_8",
        0x59: "OP_9",
        0x5A: "OP_10",
        0x5B: "OP_11",
        0x5C: "OP_12",
        0x5D: "OP_13",
        0x5E: "OP_14",
        0x5F: "OP_15",
        0x60: "OP_16",
        0x61: "OP_NOP",
        0x63: "OP_IF",
        0x64: "OP_NOTIF",
        0x67: "OP_ELSE",
        0x68: "OP_ENDIF",
        0x69: "OP_VERIFY",
        0x6A: "OP_RETURN",
        0x6B: "OP_TOALTSTACK",
        0x6C: "OP_FROMALTSTACK",
        0x6D: "OP_2DROP",
        0x6E: "OP_2DUP",
        0x6F: "OP_3DUP",
        0x70: "OP_2OVER",
        0x71: "OP_2ROT",
        0x72: "OP_2SWAP",
        0x73: "OP_IFDUP",
        0x74: "OP_DEPTH",
        0x75: "OP_DROP",
        0x76: "OP_DUP",
        0x77: "OP_NIP",
        0x78: "OP_OVER",
        0x79: "OP_PICK",
        0x7A: "OP_ROLL",
        0x7B: "OP_ROT",
        0x7C: "OP_SWAP",
        0x7D: "OP_TUCK",
        0x82: "OP_SIZE",
        0x87: "OP_EQUAL",
        0x88: "OP_EQUALVERIFY",
        0x8B: "OP_1ADD",
        0x8C: "OP_1SUB",
        0x93: "OP_ADD",
        0x94: "OP_SUB",
        0x9A: "OP_BOOLAND",
        0x9B: "OP_BOOLOR",
        0x9C: "OP_NUMEQUAL",
        0x9D: "OP_NUMEQUALVERIFY",
        0x9E: "OP_NUMNOTEQUAL",
        0x9F: "OP_LESSTHAN",
        0xA0: "OP_GREATERTHAN",
        0xA1: "OP_LESSTHANOREQUAL",
        0xA2: "OP_GREATERTHANOREQUAL",
        0xA3: "OP_MIN",
        0xA4: "OP_MAX",
        0xA5: "OP_WITHIN",
        0xA6: "OP_RIPEMD160",
        0xA7: "OP_SHA1",
        0xA8: "OP_SHA256",
        0xA9: "OP_HASH160",
        0xAA: "OP_HASH256",
        0xAB: "OP_CODESEPARATOR",
        0xAC: "OP_CHECKSIG",
        0xAD: "OP_CHECKSIGVERIFY",
        0xAE: "OP_CHECKMULTISIG",
        0xAF: "OP_CHECKMULTISIGVERIFY",
        0xB1: "OP_CHECKLOCKTIMEVERIFY",
        0xB2: "OP_CHECKSEQUENCEVERIFY",
        0xBA: "OP_CHECKSIGADD",  # Tapscript
    }
)

# Opcodes treated as "unsupported" for pass claims (malleability / softfork
# ambiguity or deliberately not modeled).
UNSUPPORTED_FOR_PASS: frozenset[int] = frozenset(
    {
        0x50,  # OP_RESERVED
        0x62,  # OP_VER
        0x65,  # OP_VERIF
        0x66,  # OP_VERNOTIF
        0x89,  # OP_RESERVED1
        0x8A,  # OP_RESERVED2
        0xB0,  # OP_NOP1
        0xB3,  # OP_NOP4
        0xB4,  # OP_NOP5
        0xB5,  # OP_NOP6
        0xB6,  # OP_NOP7
        0xB7,  # OP_NOP8
        0xB8,  # OP_NOP9
        0xB9,  # OP_NOP10
    }
)

# Weak sighash types that enable unintended co-sign / replay surface.
WEAK_SIGHASH_FLAGS: frozenset[int] = frozenset(
    {
        int(SighashFlag.NONE),
        int(SighashFlag.SINGLE),
        int(SighashFlag.NONE) | int(SighashFlag.ANYONECANPAY),
        int(SighashFlag.SINGLE) | int(SighashFlag.ANYONECANPAY),
        int(SighashFlag.ANYONECANPAY),  # ANYONECANPAY alone is non-standard but weak
    }
)


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


def _positive(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{name} must be a positive integer")
    return value


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidRequestError(f"{name} must be a bool")
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


def normalize_script_bytes(value: bytes | str | None) -> bytes:
    """Normalize script bytes from raw bytes or even-length hex."""

    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("0x", "0X")):
            text = text[2:]
        if not text:
            return b""
        if not _HEX_RE.fullmatch(text):
            raise InvalidRequestError("script must be even-length hex")
        return bytes.fromhex(text)
    raise InvalidRequestError("script must be bytes or hex string")


def normalize_txid(value: str, *, field: str = "txid") -> str:
    """Normalize a display-form transaction id (64 hex chars, lowercased)."""

    text = _required_text(value, field).lower()
    if text.startswith("0x"):
        text = text[2:]
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise InvalidRequestError(f"{field} must be 64 hex characters")
    return text


def opcode_name(code: int) -> str:
    """Return a stable mnemonic for a known opcode, else OP_UNKNOWN_0xNN."""

    if not isinstance(code, int) or isinstance(code, bool):
        raise InvalidRequestError("opcode must be an integer")
    if code in KNOWN_OPCODES:
        return KNOWN_OPCODES[code]
    if 1 <= code <= 75:
        return f"OP_PUSHBYTES_{code}"
    return f"OP_UNKNOWN_0x{code:02x}"


@dataclass(frozen=True, slots=True)
class DecodedOp:
    """One decoded script instruction with optional push payload."""

    offset: int
    opcode: int
    name: str
    push_data: bytes = b""
    is_push: bool = False
    known: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "offset", _non_negative(self.offset, "offset"))
        if (
            isinstance(self.opcode, bool)
            or not isinstance(self.opcode, int)
            or not 0 <= self.opcode <= 0xFF
        ):
            raise InvalidRequestError("opcode must be a byte value 0..255")
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        if type(self.push_data) is not bytes:
            raise InvalidRequestError("push_data must be bytes")
        object.__setattr__(self, "is_push", _bool(self.is_push, "is_push"))
        object.__setattr__(self, "known", _bool(self.known, "known"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_push": self.is_push,
            "known": self.known,
            "name": self.name,
            "offset": self.offset,
            "opcode": self.opcode,
            "push_data_digest": bytes_digest(self.push_data) if self.push_data else "",
            "push_data_len": len(self.push_data),
        }


@dataclass(frozen=True, slots=True)
class ScriptProgram:
    """Decoded script program with form, version, and resource bounds.

    This is the primary Crypto IR binding for a locking, redeem, or witness
    script.  It never pretends Bitcoin is an account machine — only spend
    conditions and stack structure are modeled.
    """

    script_digest: str
    script_hex: str
    form: ScriptForm
    version: ScriptVersion
    ops: tuple[DecodedOp, ...]
    op_count: int
    byte_length: int
    fully_decoded: bool
    unsupported_opcodes: tuple[int, ...] = ()
    witness_version: int | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCRIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "script_digest",
            _optional_digest(self.script_digest, "script_digest")
            if self.script_digest
            else "",
        )
        hex_text = self.script_hex.strip().lower() if self.script_hex else ""
        if hex_text.startswith("0x"):
            hex_text = hex_text[2:]
        if hex_text and not _HEX_RE.fullmatch(hex_text):
            raise InvalidRequestError("script_hex must be even-length hex")
        object.__setattr__(self, "script_hex", hex_text)
        form = self.form if isinstance(self.form, ScriptForm) else ScriptForm(str(self.form))
        object.__setattr__(self, "form", form)
        version = (
            self.version
            if isinstance(self.version, ScriptVersion)
            else ScriptVersion(str(self.version))
        )
        object.__setattr__(self, "version", version)
        ops = tuple(self.ops)
        for index, op in enumerate(ops):
            if not isinstance(op, DecodedOp):
                raise InvalidRequestError(f"ops[{index}] must be a DecodedOp")
        object.__setattr__(self, "ops", ops)
        object.__setattr__(self, "op_count", _non_negative(self.op_count, "op_count"))
        object.__setattr__(
            self, "byte_length", _non_negative(self.byte_length, "byte_length")
        )
        object.__setattr__(
            self, "fully_decoded", _bool(self.fully_decoded, "fully_decoded")
        )
        unsupported = tuple(int(x) for x in self.unsupported_opcodes)
        object.__setattr__(self, "unsupported_opcodes", unsupported)
        if self.witness_version is not None:
            if (
                isinstance(self.witness_version, bool)
                or not isinstance(self.witness_version, int)
                or not 0 <= self.witness_version <= 16
            ):
                raise InvalidRequestError("witness_version must be 0..16")
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        if not self.script_digest and self.script_hex:
            object.__setattr__(
                self, "script_digest", bytes_digest(bytes.fromhex(self.script_hex))
            )
        ensure_secret_safe(self.to_dict())

    @property
    def is_segwit(self) -> bool:
        return self.form in {ScriptForm.P2WPKH, ScriptForm.P2WSH, ScriptForm.P2TR}

    @property
    def is_taproot(self) -> bool:
        return self.form is ScriptForm.P2TR

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "byte_length": self.byte_length,
            "form": self.form.value,
            "fully_decoded": self.fully_decoded,
            "is_segwit": self.is_segwit,
            "is_taproot": self.is_taproot,
            "op_count": self.op_count,
            "ops": [op.to_dict() for op in self.ops],
            "schema_version": self.schema_version,
            "script_digest": self.script_digest,
            "script_hex": self.script_hex,
            "unsupported_opcodes": list(self.unsupported_opcodes),
            "version": self.version.value,
            "witness_version": self.witness_version,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class PrevoutBinding:
    """Exact previous-output binding required for spend-path semantics.

    Amount (satoshis), outpoint, and scriptPubKey digest are authoritative.
    Missing any of these leaves the path incomplete — never silently defaulted.
    """

    txid: str
    vout: int
    value_sats: int
    script_pubkey_digest: str
    script_pubkey_hex: str = ""
    script_form: ScriptForm = ScriptForm.UNKNOWN
    known: bool = True
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCRIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "txid", normalize_txid(self.txid))
        if (
            isinstance(self.vout, bool)
            or not isinstance(self.vout, int)
            or not 0 <= self.vout <= 0xFFFFFFFF
        ):
            raise InvalidRequestError("vout must be a uint32 integer")
        object.__setattr__(
            self, "value_sats", _non_negative(self.value_sats, "value_sats")
        )
        object.__setattr__(
            self,
            "script_pubkey_digest",
            _optional_digest(self.script_pubkey_digest, "script_pubkey_digest")
            if self.script_pubkey_digest
            else "",
        )
        hex_text = (
            self.script_pubkey_hex.strip().lower() if self.script_pubkey_hex else ""
        )
        if hex_text.startswith("0x"):
            hex_text = hex_text[2:]
        if hex_text and not _HEX_RE.fullmatch(hex_text):
            raise InvalidRequestError("script_pubkey_hex must be even-length hex")
        object.__setattr__(self, "script_pubkey_hex", hex_text)
        if hex_text and not self.script_pubkey_digest:
            object.__setattr__(
                self,
                "script_pubkey_digest",
                bytes_digest(bytes.fromhex(hex_text)),
            )
        form = (
            self.script_form
            if isinstance(self.script_form, ScriptForm)
            else ScriptForm(str(self.script_form))
        )
        object.__setattr__(self, "script_form", form)
        object.__setattr__(self, "known", _bool(self.known, "known"))
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        if not self.known or not self.script_pubkey_digest:
            # Incomplete prevout is allowed as an explicit incomplete record.
            pass
        ensure_secret_safe(self.to_dict())

    @property
    def outpoint_key(self) -> str:
        return f"{self.txid}:{self.vout}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "known": self.known,
            "outpoint_key": self.outpoint_key,
            "schema_version": self.schema_version,
            "script_form": self.script_form.value,
            "script_pubkey_digest": self.script_pubkey_digest,
            "script_pubkey_hex": self.script_pubkey_hex,
            "txid": self.txid,
            "value_sats": self.value_sats,
            "vout": self.vout,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class SighashCommitment:
    """Sighash type and bound commitment surface for one input.

    Weak flags (NONE, SINGLE, ANYONECANPAY variants) are flagged as hazards.
    The commitment digest is a content hash over the declared bound fields —
    not a full BIP-143 preimage computation (offline fixtures supply digests).
    """

    sighash_type: int
    input_index: int
    prevout_digest: str = ""
    amount_sats: int | None = None
    script_code_digest: str = ""
    sequence: int | None = None
    locktime: int | None = None
    commitment_digest: str = ""
    is_weak: bool = False
    anyone_can_pay: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCRIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            isinstance(self.sighash_type, bool)
            or not isinstance(self.sighash_type, int)
            or not 0 <= self.sighash_type <= 0xFF
        ):
            raise InvalidRequestError("sighash_type must be a byte value 0..255")
        object.__setattr__(
            self, "input_index", _non_negative(self.input_index, "input_index")
        )
        base = self.sighash_type & 0x1F
        acp = bool(self.sighash_type & int(SighashFlag.ANYONECANPAY))
        object.__setattr__(self, "anyone_can_pay", acp)
        weak = self.sighash_type in WEAK_SIGHASH_FLAGS or base in {
            int(SighashFlag.NONE),
            int(SighashFlag.SINGLE),
        }
        # DEFAULT (0x00) is Taproot key-path — not weak.
        if self.sighash_type == int(SighashFlag.DEFAULT):
            weak = False
        if self.sighash_type == int(SighashFlag.ALL):
            weak = False
        if self.sighash_type == (int(SighashFlag.ALL) | int(SighashFlag.ANYONECANPAY)):
            weak = True  # ALL|ANYONECANPAY still weakens input set
        object.__setattr__(self, "is_weak", weak)
        object.__setattr__(
            self,
            "prevout_digest",
            _optional_digest(self.prevout_digest, "prevout_digest")
            if self.prevout_digest
            else "",
        )
        if self.amount_sats is not None:
            object.__setattr__(
                self, "amount_sats", _non_negative(self.amount_sats, "amount_sats")
            )
        object.__setattr__(
            self,
            "script_code_digest",
            _optional_digest(self.script_code_digest, "script_code_digest")
            if self.script_code_digest
            else "",
        )
        if self.sequence is not None:
            if (
                isinstance(self.sequence, bool)
                or not isinstance(self.sequence, int)
                or not 0 <= self.sequence <= 0xFFFFFFFF
            ):
                raise InvalidRequestError("sequence must be a uint32 integer")
        if self.locktime is not None:
            if (
                isinstance(self.locktime, bool)
                or not isinstance(self.locktime, int)
                or not 0 <= self.locktime <= 0xFFFFFFFF
            ):
                raise InvalidRequestError("locktime must be a uint32 integer")
        if not self.commitment_digest:
            digest = content_digest(
                {
                    "amount_sats": self.amount_sats,
                    "input_index": self.input_index,
                    "locktime": self.locktime,
                    "prevout_digest": self.prevout_digest,
                    "script_code_digest": self.script_code_digest,
                    "sequence": self.sequence,
                    "sighash_type": self.sighash_type,
                }
            )
            object.__setattr__(self, "commitment_digest", digest)
        else:
            object.__setattr__(
                self,
                "commitment_digest",
                _optional_digest(self.commitment_digest, "commitment_digest"),
            )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    @property
    def base_type(self) -> int:
        return self.sighash_type & 0x1F

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount_sats": self.amount_sats,
            "anyone_can_pay": self.anyone_can_pay,
            "attributes": thaw_json(self.attributes),
            "base_type": self.base_type,
            "commitment_digest": self.commitment_digest,
            "input_index": self.input_index,
            "is_weak": self.is_weak,
            "locktime": self.locktime,
            "prevout_digest": self.prevout_digest,
            "schema_version": self.schema_version,
            "script_code_digest": self.script_code_digest,
            "sequence": self.sequence,
            "sighash_type": self.sighash_type,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class TimelockConstraint:
    """CLTV (absolute) or CSV (relative) timelock constraint from a script."""

    kind: str  # "cltv" | "csv" | "unknown"
    value: int
    source_opcode: str
    sequence_bound: int | None = None
    locktime_bound: int | None = None
    satisfied: bool | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind = _required_text(self.kind, "kind").lower()
        if kind not in {"cltv", "csv", "unknown"}:
            raise InvalidRequestError("kind must be cltv, csv, or unknown")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "value", _non_negative(self.value, "value"))
        object.__setattr__(
            self, "source_opcode", _required_text(self.source_opcode, "source_opcode")
        )
        if self.sequence_bound is not None:
            object.__setattr__(
                self,
                "sequence_bound",
                _non_negative(self.sequence_bound, "sequence_bound"),
            )
        if self.locktime_bound is not None:
            object.__setattr__(
                self,
                "locktime_bound",
                _non_negative(self.locktime_bound, "locktime_bound"),
            )
        if self.satisfied is not None and not isinstance(self.satisfied, bool):
            raise InvalidRequestError("satisfied must be bool or None")
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "kind": self.kind,
            "locktime_bound": self.locktime_bound,
            "satisfied": self.satisfied,
            "sequence_bound": self.sequence_bound,
            "source_opcode": self.source_opcode,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class HashlockConstraint:
    """Hash preimage lock (HASH160/SHA256 equal-verify pattern)."""

    hash_function: str  # hash160 | sha256 | hash256 | ripemd160 | unknown
    commitment_digest: str
    preimage_known: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        fn = _required_text(self.hash_function, "hash_function").lower()
        if fn not in {"hash160", "sha256", "hash256", "ripemd160", "unknown"}:
            raise InvalidRequestError("unsupported hash_function")
        object.__setattr__(self, "hash_function", fn)
        object.__setattr__(
            self,
            "commitment_digest",
            _optional_digest(self.commitment_digest, "commitment_digest")
            if self.commitment_digest
            else "",
        )
        object.__setattr__(
            self, "preimage_known", _bool(self.preimage_known, "preimage_known")
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "commitment_digest": self.commitment_digest,
            "hash_function": self.hash_function,
            "preimage_known": self.preimage_known,
        }


@dataclass(frozen=True, slots=True)
class WitnessStack:
    """Witness stack items for a SegWit/Taproot input."""

    items: tuple[bytes, ...]
    item_digests: tuple[str, ...]
    item_count: int
    total_bytes: int
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        items = tuple(self.items)
        for index, item in enumerate(items):
            if type(item) is not bytes:
                raise InvalidRequestError(f"witness items[{index}] must be bytes")
        object.__setattr__(self, "items", items)
        digests = tuple(bytes_digest(item) for item in items)
        object.__setattr__(self, "item_digests", digests)
        object.__setattr__(self, "item_count", len(items))
        object.__setattr__(self, "total_bytes", sum(len(item) for item in items))
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "item_count": self.item_count,
            "item_digests": list(self.item_digests),
            "item_lengths": [len(item) for item in self.items],
            "total_bytes": self.total_bytes,
        }


@dataclass(frozen=True, slots=True)
class StackSemanticRecord:
    """Bounded stack/spending-path semantic summary for one program.

    Incomplete witnesses, missing prevouts, unsupported opcodes, or weak
    sighash never claim PASS.
    """

    program: ScriptProgram
    prevout: PrevoutBinding | None
    sighash: SighashCommitment | None
    witness: WitnessStack | None
    timelocks: tuple[TimelockConstraint, ...]
    hashlocks: tuple[HashlockConstraint, ...]
    pass_status: SemanticPassStatus
    diagnostics: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCRIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.program, ScriptProgram):
            raise InvalidRequestError("program must be a ScriptProgram")
        if self.prevout is not None and not isinstance(self.prevout, PrevoutBinding):
            raise InvalidRequestError("prevout must be a PrevoutBinding or None")
        if self.sighash is not None and not isinstance(self.sighash, SighashCommitment):
            raise InvalidRequestError("sighash must be a SighashCommitment or None")
        if self.witness is not None and not isinstance(self.witness, WitnessStack):
            raise InvalidRequestError("witness must be a WitnessStack or None")
        timelocks = tuple(self.timelocks)
        for index, item in enumerate(timelocks):
            if not isinstance(item, TimelockConstraint):
                raise InvalidRequestError(
                    f"timelocks[{index}] must be a TimelockConstraint"
                )
        object.__setattr__(self, "timelocks", timelocks)
        hashlocks = tuple(self.hashlocks)
        for index, item in enumerate(hashlocks):
            if not isinstance(item, HashlockConstraint):
                raise InvalidRequestError(
                    f"hashlocks[{index}] must be a HashlockConstraint"
                )
        object.__setattr__(self, "hashlocks", hashlocks)
        status = (
            self.pass_status
            if isinstance(self.pass_status, SemanticPassStatus)
            else SemanticPassStatus(str(self.pass_status))
        )
        object.__setattr__(self, "pass_status", status)
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_required_text(d, "diagnostics item") for d in self.diagnostics),
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        # Invariant: incomplete / unsupported / weak never pass.
        if status is SemanticPassStatus.PASS:
            if not self.program.fully_decoded or self.program.unsupported_opcodes:
                raise InvalidRequestError(
                    "semantic pass forbidden with incomplete decode or unsupported opcodes"
                )
            if self.prevout is None or not self.prevout.known:
                raise InvalidRequestError(
                    "semantic pass requires a known prevout binding"
                )
            if self.sighash is not None and self.sighash.is_weak:
                raise InvalidRequestError(
                    "semantic pass forbidden with weak sighash flags"
                )
        ensure_secret_safe(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "diagnostics": list(self.diagnostics),
            "hashlocks": [item.to_dict() for item in self.hashlocks],
            "pass_status": self.pass_status.value,
            "prevout": self.prevout.to_dict() if self.prevout else None,
            "program": self.program.to_dict(),
            "schema_version": self.schema_version,
            "sighash": self.sighash.to_dict() if self.sighash else None,
            "timelocks": [item.to_dict() for item in self.timelocks],
            "witness": self.witness.to_dict() if self.witness else None,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


def decode_script(
    script: bytes | str,
    *,
    version: ScriptVersion | str = ScriptVersion.LEGACY,
    max_script_bytes: int = DEFAULT_MAX_SCRIPT_BYTES,
    max_ops: int = DEFAULT_MAX_OPS,
    max_push_bytes: int = DEFAULT_MAX_PUSH_BYTES,
) -> ScriptProgram:
    """Decode a script into a :class:`ScriptProgram` with bounded offline ops.

    This is a structural decoder, not a full Script VM.  Branching (IF/ELSE)
    is recorded as opcodes but not executed.
    """

    data = normalize_script_bytes(script)
    max_script_bytes = _positive(max_script_bytes, "max_script_bytes")
    max_ops = _positive(max_ops, "max_ops")
    max_push_bytes = _positive(max_push_bytes, "max_push_bytes")
    if len(data) > max_script_bytes:
        raise ResourceLimitError("script exceeds max_script_bytes")

    ver = version if isinstance(version, ScriptVersion) else ScriptVersion(str(version))
    ops: list[DecodedOp] = []
    unsupported: list[int] = []
    fully = True
    i = 0
    while i < len(data):
        if len(ops) >= max_ops:
            raise ResourceLimitError("script exceeds max_ops")
        code = data[i]
        offset = i
        i += 1
        if code == 0x00:
            ops.append(
                DecodedOp(
                    offset=offset,
                    opcode=code,
                    name="OP_0",
                    push_data=b"",
                    is_push=True,
                    known=True,
                )
            )
            continue
        if 1 <= code <= 75:
            push_len = code
            if i + push_len > len(data):
                fully = False
                ops.append(
                    DecodedOp(
                        offset=offset,
                        opcode=code,
                        name=opcode_name(code),
                        push_data=data[i:],
                        is_push=True,
                        known=False,
                    )
                )
                break
            payload = data[i : i + push_len]
            i += push_len
            if push_len > max_push_bytes:
                raise ResourceLimitError("push data exceeds max_push_bytes")
            ops.append(
                DecodedOp(
                    offset=offset,
                    opcode=code,
                    name=opcode_name(code),
                    push_data=payload,
                    is_push=True,
                    known=True,
                )
            )
            continue
        if code == 0x4C:  # OP_PUSHDATA1
            if i >= len(data):
                fully = False
                break
            push_len = data[i]
            i += 1
            if i + push_len > len(data):
                fully = False
                break
            payload = data[i : i + push_len]
            i += push_len
            if push_len > max_push_bytes:
                raise ResourceLimitError("push data exceeds max_push_bytes")
            ops.append(
                DecodedOp(
                    offset=offset,
                    opcode=code,
                    name="OP_PUSHDATA1",
                    push_data=payload,
                    is_push=True,
                    known=True,
                )
            )
            continue
        if code == 0x4D:  # OP_PUSHDATA2
            if i + 2 > len(data):
                fully = False
                break
            push_len = int.from_bytes(data[i : i + 2], "little")
            i += 2
            if i + push_len > len(data):
                fully = False
                break
            payload = data[i : i + push_len]
            i += push_len
            if push_len > max_push_bytes:
                raise ResourceLimitError("push data exceeds max_push_bytes")
            ops.append(
                DecodedOp(
                    offset=offset,
                    opcode=code,
                    name="OP_PUSHDATA2",
                    push_data=payload,
                    is_push=True,
                    known=True,
                )
            )
            continue
        if code == 0x4E:  # OP_PUSHDATA4
            if i + 4 > len(data):
                fully = False
                break
            push_len = int.from_bytes(data[i : i + 4], "little")
            i += 4
            if push_len > max_push_bytes:
                raise ResourceLimitError("push data exceeds max_push_bytes")
            if i + push_len > len(data):
                fully = False
                break
            payload = data[i : i + push_len]
            i += push_len
            ops.append(
                DecodedOp(
                    offset=offset,
                    opcode=code,
                    name="OP_PUSHDATA4",
                    push_data=payload,
                    is_push=True,
                    known=True,
                )
            )
            continue

        name = opcode_name(code)
        is_unknown = name.startswith("OP_UNKNOWN_")
        is_reserved = code in UNSUPPORTED_FOR_PASS
        known = (code in KNOWN_OPCODES) and not is_reserved
        if is_unknown or is_reserved:
            unsupported.append(code)
            known = False
        ops.append(
            DecodedOp(
                offset=offset,
                opcode=code,
                name=name,
                push_data=b"",
                is_push=False,
                known=known,
            )
        )

    # De-dupe unsupported while preserving order.
    seen: set[int] = set()
    uniq_unsupported: list[int] = []
    for code in unsupported:
        if code not in seen:
            seen.add(code)
            uniq_unsupported.append(code)

    form = classify_script_form(data)
    witness_version: int | None = None
    if form is ScriptForm.P2WPKH or form is ScriptForm.P2WSH:
        witness_version = 0
        ver = ScriptVersion.SEG_WIT_V0 if ver is ScriptVersion.LEGACY else ver
    elif form is ScriptForm.P2TR:
        witness_version = 1
        if ver is ScriptVersion.LEGACY:
            ver = ScriptVersion.TAPSCRIPT

    return ScriptProgram(
        script_digest=bytes_digest(data) if data else "",
        script_hex=data.hex(),
        form=form,
        version=ver,
        ops=tuple(ops),
        op_count=len(ops),
        byte_length=len(data),
        fully_decoded=fully and i >= len(data),
        unsupported_opcodes=tuple(uniq_unsupported),
        witness_version=witness_version,
    )


def classify_script_form(script: bytes | str) -> ScriptForm:
    """Best-effort classification of a locking script."""

    data = normalize_script_bytes(script)
    if not data:
        return ScriptForm.UNKNOWN
    # P2PKH: OP_DUP OP_HASH160 <20> OP_EQUALVERIFY OP_CHECKSIG
    if (
        len(data) == 25
        and data[0] == 0x76
        and data[1] == 0xA9
        and data[2] == 0x14
        and data[23] == 0x88
        and data[24] == 0xAC
    ):
        return ScriptForm.P2PKH
    # P2SH: OP_HASH160 <20> OP_EQUAL
    if len(data) == 23 and data[0] == 0xA9 and data[1] == 0x14 and data[22] == 0x87:
        return ScriptForm.P2SH
    # P2WPKH: OP_0 <20>
    if len(data) == 22 and data[0] == 0x00 and data[1] == 0x14:
        return ScriptForm.P2WPKH
    # P2WSH: OP_0 <32>
    if len(data) == 34 and data[0] == 0x00 and data[1] == 0x20:
        return ScriptForm.P2WSH
    # P2TR: OP_1 <32>
    if len(data) == 34 and data[0] == 0x51 and data[1] == 0x20:
        return ScriptForm.P2TR
    # OP_RETURN
    if data[0] == 0x6A:
        return ScriptForm.NULL_DATA
    # Bare multisig: OP_m <keys...> OP_n OP_CHECKMULTISIG
    if data[-1] == 0xAE and 0x51 <= data[0] <= 0x60:
        return ScriptForm.MULTISIG
    # P2PK: <33|65> OP_CHECKSIG
    if data[-1] == 0xAC and data[0] in (33, 65) and len(data) == data[0] + 2:
        return ScriptForm.P2PK
    # Hashlock-ish: OP_HASH160/SHA256 ... OP_EQUAL
    if any(b in data for b in (0xA8, 0xA9, 0xAA, 0xA6)) and 0x87 in data:
        return ScriptForm.HASHLOCK
    # Timelock-ish
    if 0xB1 in data or 0xB2 in data:
        return ScriptForm.TIMELOCK
    return ScriptForm.UNKNOWN


def extract_timelocks(program: ScriptProgram) -> tuple[TimelockConstraint, ...]:
    """Extract CLTV/CSV constraints from decoded opcodes and preceding pushes."""

    results: list[TimelockConstraint] = []
    ops = program.ops
    for index, op in enumerate(ops):
        if op.opcode == 0xB1:  # CLTV
            value = 0
            if index > 0 and ops[index - 1].is_push and ops[index - 1].push_data:
                value = int.from_bytes(ops[index - 1].push_data, "little")
            elif index > 0 and 0x51 <= ops[index - 1].opcode <= 0x60:
                value = ops[index - 1].opcode - 0x50
            results.append(
                TimelockConstraint(
                    kind="cltv",
                    value=value,
                    source_opcode="OP_CHECKLOCKTIMEVERIFY",
                )
            )
        elif op.opcode == 0xB2:  # CSV
            value = 0
            if index > 0 and ops[index - 1].is_push and ops[index - 1].push_data:
                value = int.from_bytes(ops[index - 1].push_data, "little")
            elif index > 0 and 0x51 <= ops[index - 1].opcode <= 0x60:
                value = ops[index - 1].opcode - 0x50
            results.append(
                TimelockConstraint(
                    kind="csv",
                    value=value,
                    source_opcode="OP_CHECKSEQUENCEVERIFY",
                )
            )
    return tuple(results)


def extract_hashlocks(program: ScriptProgram) -> tuple[HashlockConstraint, ...]:
    """Extract hash-equal patterns (HASH160/SHA256 + push + EQUAL)."""

    results: list[HashlockConstraint] = []
    ops = program.ops
    hash_ops = {
        0xA6: "ripemd160",
        0xA8: "sha256",
        0xA9: "hash160",
        0xAA: "hash256",
    }
    for index, op in enumerate(ops):
        if op.opcode not in hash_ops:
            continue
        # Look for push then EQUAL/EQUALVERIFY shortly after.
        commitment = b""
        for j in range(index + 1, min(index + 4, len(ops))):
            if ops[j].is_push and ops[j].push_data:
                commitment = ops[j].push_data
            if ops[j].opcode in (0x87, 0x88):
                results.append(
                    HashlockConstraint(
                        hash_function=hash_ops[op.opcode],
                        commitment_digest=bytes_digest(commitment) if commitment else "",
                        preimage_known=False,
                    )
                )
                break
    return tuple(results)


def bind_prevout(
    *,
    txid: str,
    vout: int,
    value_sats: int,
    script_pubkey: bytes | str,
    known: bool = True,
    attributes: Mapping[str, Any] | None = None,
) -> PrevoutBinding:
    """Bind exact outpoint, amount, and scriptPubKey for spend semantics."""

    data = normalize_script_bytes(script_pubkey)
    return PrevoutBinding(
        txid=txid,
        vout=vout,
        value_sats=value_sats,
        script_pubkey_digest=bytes_digest(data) if data else "",
        script_pubkey_hex=data.hex(),
        script_form=classify_script_form(data),
        known=known and bool(data),
        attributes=dict(attributes or {}),
    )


def bind_sighash(
    *,
    sighash_type: int,
    input_index: int,
    prevout: PrevoutBinding | None = None,
    script_code: bytes | str = b"",
    sequence: int | None = None,
    locktime: int | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> SighashCommitment:
    """Construct a :class:`SighashCommitment` from bound fields."""

    script_bytes = normalize_script_bytes(script_code) if script_code else b""
    return SighashCommitment(
        sighash_type=sighash_type,
        input_index=input_index,
        prevout_digest=prevout.content_digest() if prevout else "",
        amount_sats=prevout.value_sats if prevout else None,
        script_code_digest=bytes_digest(script_bytes) if script_bytes else "",
        sequence=sequence,
        locktime=locktime,
        attributes=dict(attributes or {}),
    )


def bind_witness(
    items: Sequence[bytes | str],
    *,
    max_items: int = DEFAULT_MAX_WITNESS_ITEMS,
    max_total_bytes: int = DEFAULT_MAX_SCRIPT_BYTES,
) -> WitnessStack:
    """Normalize witness stack items with resource bounds."""

    max_items = _positive(max_items, "max_items")
    max_total_bytes = _positive(max_total_bytes, "max_total_bytes")
    normalized: list[bytes] = []
    total = 0
    for index, item in enumerate(items):
        if index >= max_items:
            raise ResourceLimitError("witness exceeds max_items")
        if isinstance(item, bytes):
            data = item
        elif isinstance(item, str):
            data = normalize_script_bytes(item)
        else:
            raise InvalidRequestError(f"witness items[{index}] must be bytes or hex")
        total += len(data)
        if total > max_total_bytes:
            raise ResourceLimitError("witness exceeds max_total_bytes")
        normalized.append(data)
    return WitnessStack(items=tuple(normalized), item_digests=(), item_count=0, total_bytes=0)


def incomplete_spend_never_passes(
    *,
    fully_decoded: bool,
    unsupported_opcodes: Sequence[int],
    prevout_known: bool,
    weak_sighash: bool,
    hidden_branch: bool = False,
    claim_pass: bool = False,
) -> SemanticPassStatus:
    """Fail-closed gate for spending-path semantic claims."""

    if not fully_decoded or unsupported_opcodes or not prevout_known or weak_sighash:
        if claim_pass:
            return SemanticPassStatus.FAIL_CLOSED
        if unsupported_opcodes:
            return SemanticPassStatus.UNSUPPORTED
        return SemanticPassStatus.INCOMPLETE
    if hidden_branch:
        return SemanticPassStatus.INCOMPLETE
    if claim_pass:
        return SemanticPassStatus.PASS
    return SemanticPassStatus.INCOMPLETE


def analyze_stack_semantics(
    program: ScriptProgram,
    *,
    prevout: PrevoutBinding | None = None,
    sighash: SighashCommitment | None = None,
    witness: WitnessStack | None = None,
    claim_pass: bool = False,
    sequence: int | None = None,
    locktime: int | None = None,
) -> StackSemanticRecord:
    """Build a fail-closed stack/spending-path semantic record."""

    timelocks = extract_timelocks(program)
    # Bind sequence/locktime satisfaction when provided.
    bound_timelocks: list[TimelockConstraint] = []
    for tl in timelocks:
        satisfied: bool | None = None
        if tl.kind == "cltv" and locktime is not None:
            satisfied = locktime >= tl.value
        elif tl.kind == "csv" and sequence is not None:
            # Simplified: relative locktime compares low 16 bits when disable
            # flag (bit 31) is clear.
            if sequence & (1 << 31):
                satisfied = False
            else:
                satisfied = (sequence & 0xFFFF) >= (tl.value & 0xFFFF)
        bound_timelocks.append(
            TimelockConstraint(
                kind=tl.kind,
                value=tl.value,
                source_opcode=tl.source_opcode,
                sequence_bound=sequence,
                locktime_bound=locktime,
                satisfied=satisfied,
            )
        )
    hashlocks = extract_hashlocks(program)
    diagnostics: list[str] = []
    if not program.fully_decoded:
        diagnostics.append("script decode incomplete")
    if program.unsupported_opcodes:
        diagnostics.append(
            "unsupported opcodes: "
            + ",".join(f"0x{c:02x}" for c in program.unsupported_opcodes)
        )
    if prevout is None or not prevout.known:
        diagnostics.append("prevout unknown or unbound")
    if sighash is not None and sighash.is_weak:
        diagnostics.append("weak sighash flags present")
    for tl in bound_timelocks:
        if tl.satisfied is False:
            diagnostics.append(f"timelock {tl.kind}={tl.value} not satisfied")
        elif tl.satisfied is None:
            diagnostics.append(f"timelock {tl.kind}={tl.value} satisfaction unknown")

    timelock_failed = any(tl.satisfied is False for tl in bound_timelocks)
    status = incomplete_spend_never_passes(
        fully_decoded=program.fully_decoded,
        unsupported_opcodes=program.unsupported_opcodes,
        prevout_known=bool(prevout and prevout.known),
        weak_sighash=bool(sighash and sighash.is_weak),
        claim_pass=claim_pass and not timelock_failed,
    )
    if timelock_failed:
        status = (
            SemanticPassStatus.FAIL_CLOSED
            if claim_pass
            else SemanticPassStatus.INCOMPLETE
        )
        if claim_pass:
            diagnostics.append("timelock failure forces fail-closed")

    return StackSemanticRecord(
        program=program,
        prevout=prevout,
        sighash=sighash,
        witness=witness,
        timelocks=tuple(bound_timelocks),
        hashlocks=hashlocks,
        pass_status=status,
        diagnostics=tuple(diagnostics),
    )


__all__ = [
    "DEFAULT_MAX_OPS",
    "DEFAULT_MAX_PUSH_BYTES",
    "DEFAULT_MAX_SCRIPT_BYTES",
    "DEFAULT_MAX_STACK_ITEMS",
    "DEFAULT_MAX_WITNESS_ITEMS",
    "KNOWN_OPCODES",
    "SCRIPT_SCHEMA_VERSION",
    "UNSUPPORTED_FOR_PASS",
    "WEAK_SIGHASH_FLAGS",
    "DecodedOp",
    "HashlockConstraint",
    "PrevoutBinding",
    "ScriptForm",
    "ScriptProgram",
    "ScriptVersion",
    "SemanticPassStatus",
    "SighashCommitment",
    "SighashFlag",
    "StackSemanticRecord",
    "TimelockConstraint",
    "WitnessStack",
    "analyze_stack_semantics",
    "bind_prevout",
    "bind_sighash",
    "bind_witness",
    "classify_script_form",
    "decode_script",
    "extract_hashlocks",
    "extract_timelocks",
    "incomplete_spend_never_passes",
    "normalize_script_bytes",
    "normalize_txid",
    "opcode_name",
]
