"""Tapscript leaves, control blocks, and Taproot commitments (CRYPTOIR-G250).

Hidden or unavailable script-path branches remain **incomplete** — they never
pass.  Control-block depth, leaf version, internal key, and merkle path
completeness are first-class fields.

Importing this module performs no network I/O, secret resolution, or package
installation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from types import MappingProxyType
from typing import Any

from ..artifacts import bytes_digest
from ..canonical import content_digest, freeze_json, thaw_json
from ..errors import InvalidRequestError, ResourceLimitError
from ..models import ensure_secret_safe
from .script import (
    SCRIPT_SCHEMA_VERSION,
    ScriptProgram,
    ScriptVersion,
    SemanticPassStatus,
    decode_script,
    normalize_script_bytes,
)


TAPSCRIPT_SCHEMA_VERSION = "smart-contract-bitcoin-tapscript-v1"
DEFAULT_MAX_CONTROL_BLOCK_BYTES = 412  # 33 + 32*ceil(128/?) practical bound
DEFAULT_MAX_MERKLE_DEPTH = 128
LEAF_VERSION_TAPSCRIPT = 0xC0

# BIP-340/341 tagged hash helpers (pure Python, offline).
_TAG_TAP_LEAF = sha256(b"TapLeaf").digest()
_TAG_TAP_BRANCH = sha256(b"TapBranch").digest()
_TAG_TAP_TWEAK = sha256(b"TapTweak").digest()


class LeafAvailability(StrEnum):
    """Whether a tapscript leaf/path is available for analysis."""

    AVAILABLE = "available"
    HIDDEN = "hidden"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class SpendPathKind(StrEnum):
    """Taproot spend path classification."""

    KEY_PATH = "key_path"
    SCRIPT_PATH = "script_path"
    UNKNOWN = "unknown"


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


def tagged_hash(tag_digest: bytes, *parts: bytes) -> bytes:
    """BIP-340 tagged hash with a precomputed SHA256(tag) digest."""

    if type(tag_digest) is not bytes or len(tag_digest) != 32:
        raise InvalidRequestError("tag_digest must be 32 bytes")
    h = sha256()
    h.update(tag_digest)
    h.update(tag_digest)
    for part in parts:
        if type(part) is not bytes:
            raise InvalidRequestError("tagged_hash parts must be bytes")
        h.update(part)
    return h.digest()


def tapleaf_hash(script: bytes, *, leaf_version: int = LEAF_VERSION_TAPSCRIPT) -> bytes:
    """Compute BIP-341 TapLeaf hash for a script."""

    if (
        isinstance(leaf_version, bool)
        or not isinstance(leaf_version, int)
        or not 0 <= leaf_version <= 0xFF
    ):
        raise InvalidRequestError("leaf_version must be a byte value")
    if type(script) is not bytes:
        raise InvalidRequestError("script must be bytes")
    # Compact size for script length (Bitcoin-style, for lengths < 253).
    if len(script) < 0xFD:
        size = bytes([len(script)])
    elif len(script) <= 0xFFFF:
        size = b"\xfd" + len(script).to_bytes(2, "little")
    else:
        size = b"\xfe" + len(script).to_bytes(4, "little")
    return tagged_hash(_TAG_TAP_LEAF, bytes([leaf_version]), size + script)


def tapbranch_hash(left: bytes, right: bytes) -> bytes:
    """Compute BIP-341 TapBranch hash; order is lexicographic."""

    if type(left) is not bytes or type(right) is not bytes:
        raise InvalidRequestError("branch sides must be bytes")
    if len(left) != 32 or len(right) != 32:
        raise InvalidRequestError("branch sides must be 32-byte hashes")
    if left <= right:
        return tagged_hash(_TAG_TAP_BRANCH, left, right)
    return tagged_hash(_TAG_TAP_BRANCH, right, left)


def tap_tweak(internal_key: bytes, merkle_root: bytes | None = None) -> bytes:
    """Compute BIP-341 TapTweak from internal key and optional merkle root."""

    if type(internal_key) is not bytes or len(internal_key) != 32:
        raise InvalidRequestError("internal_key must be 32 bytes (x-only)")
    if merkle_root is None:
        return tagged_hash(_TAG_TAP_TWEAK, internal_key)
    if type(merkle_root) is not bytes or len(merkle_root) != 32:
        raise InvalidRequestError("merkle_root must be 32 bytes or None")
    return tagged_hash(_TAG_TAP_TWEAK, internal_key, merkle_root)


@dataclass(frozen=True, slots=True)
class TapscriptLeaf:
    """One Tapscript leaf with version, script digest, and availability.

    Hidden leaves (present in the tree but not revealed in the witness) stay
    incomplete and cannot claim semantic pass for their path.
    """

    leaf_version: int
    script_digest: str
    script_hex: str = ""
    leaf_hash: str = ""
    availability: LeafAvailability = LeafAvailability.AVAILABLE
    program: ScriptProgram | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = TAPSCRIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            isinstance(self.leaf_version, bool)
            or not isinstance(self.leaf_version, int)
            or not 0 <= self.leaf_version <= 0xFF
        ):
            raise InvalidRequestError("leaf_version must be a byte value 0..255")
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
        object.__setattr__(self, "script_hex", hex_text)
        if hex_text and not self.script_digest:
            object.__setattr__(
                self, "script_digest", bytes_digest(bytes.fromhex(hex_text))
            )
        if self.leaf_hash:
            object.__setattr__(
                self, "leaf_hash", _optional_digest(self.leaf_hash, "leaf_hash")
            )
        elif hex_text:
            raw = tapleaf_hash(
                bytes.fromhex(hex_text), leaf_version=self.leaf_version
            )
            object.__setattr__(self, "leaf_hash", f"sha256:{raw.hex()}")
        avail = (
            self.availability
            if isinstance(self.availability, LeafAvailability)
            else LeafAvailability(str(self.availability))
        )
        object.__setattr__(self, "availability", avail)
        if self.program is not None and not isinstance(self.program, ScriptProgram):
            raise InvalidRequestError("program must be a ScriptProgram or None")
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    @property
    def is_hidden(self) -> bool:
        return self.availability in {
            LeafAvailability.HIDDEN,
            LeafAvailability.UNAVAILABLE,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "availability": self.availability.value,
            "is_hidden": self.is_hidden,
            "leaf_hash": self.leaf_hash,
            "leaf_version": self.leaf_version,
            "program": self.program.to_dict() if self.program else None,
            "schema_version": self.schema_version,
            "script_digest": self.script_digest,
            "script_hex": self.script_hex,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class ControlBlock:
    """BIP-341 control block for a script-path spend.

    Layout: ``leaf_version || parity`` (1 byte) + internal key (32) +
    optional 32-byte merkle nodes.
    """

    raw_digest: str
    leaf_version: int
    parity: int
    internal_key_hex: str
    merkle_nodes: tuple[str, ...]  # hex hashes
    depth: int
    complete: bool
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = TAPSCRIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "raw_digest",
            _optional_digest(self.raw_digest, "raw_digest") if self.raw_digest else "",
        )
        if (
            isinstance(self.leaf_version, bool)
            or not isinstance(self.leaf_version, int)
            or not 0 <= self.leaf_version <= 0xFF
        ):
            raise InvalidRequestError("leaf_version must be a byte value")
        if self.parity not in (0, 1):
            raise InvalidRequestError("parity must be 0 or 1")
        key = self.internal_key_hex.strip().lower()
        if key.startswith("0x"):
            key = key[2:]
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise InvalidRequestError("internal_key_hex must be 32-byte hex")
        object.__setattr__(self, "internal_key_hex", key)
        nodes = tuple(n.strip().lower() for n in self.merkle_nodes)
        for index, node in enumerate(nodes):
            if len(node) != 64 or any(c not in "0123456789abcdef" for c in node):
                raise InvalidRequestError(
                    f"merkle_nodes[{index}] must be 32-byte hex"
                )
        object.__setattr__(self, "merkle_nodes", nodes)
        object.__setattr__(self, "depth", _non_negative(self.depth, "depth"))
        object.__setattr__(self, "complete", _bool(self.complete, "complete"))
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "complete": self.complete,
            "depth": self.depth,
            "internal_key_hex": self.internal_key_hex,
            "leaf_version": self.leaf_version,
            "merkle_nodes": list(self.merkle_nodes),
            "parity": self.parity,
            "raw_digest": self.raw_digest,
            "schema_version": self.schema_version,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class TaprootCommitment:
    """Taproot output commitment: internal key, merkle root, output key.

    When script-path leaves are only partially revealed, ``hidden_branches``
    stays non-empty and semantic pass is incomplete for unrevealed paths.
    """

    internal_key_hex: str
    output_key_hex: str = ""
    merkle_root_hex: str = ""
    tweak_digest: str = ""
    spend_path: SpendPathKind = SpendPathKind.UNKNOWN
    revealed_leaves: tuple[TapscriptLeaf, ...] = ()
    hidden_branches: tuple[str, ...] = ()
    control_block: ControlBlock | None = None
    commitment_complete: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = TAPSCRIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        key = self.internal_key_hex.strip().lower()
        if key.startswith("0x"):
            key = key[2:]
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise InvalidRequestError("internal_key_hex must be 32-byte hex")
        object.__setattr__(self, "internal_key_hex", key)
        out = self.output_key_hex.strip().lower() if self.output_key_hex else ""
        if out.startswith("0x"):
            out = out[2:]
        if out and (len(out) != 64 or any(c not in "0123456789abcdef" for c in out)):
            raise InvalidRequestError("output_key_hex must be 32-byte hex when set")
        object.__setattr__(self, "output_key_hex", out)
        root = self.merkle_root_hex.strip().lower() if self.merkle_root_hex else ""
        if root.startswith("0x"):
            root = root[2:]
        if root and (len(root) != 64 or any(c not in "0123456789abcdef" for c in root)):
            raise InvalidRequestError("merkle_root_hex must be 32-byte hex when set")
        object.__setattr__(self, "merkle_root_hex", root)
        if self.tweak_digest:
            object.__setattr__(
                self, "tweak_digest", _optional_digest(self.tweak_digest, "tweak_digest")
            )
        else:
            internal = bytes.fromhex(key)
            merkle = bytes.fromhex(root) if root else None
            object.__setattr__(
                self,
                "tweak_digest",
                f"sha256:{tap_tweak(internal, merkle).hex()}",
            )
        path = (
            self.spend_path
            if isinstance(self.spend_path, SpendPathKind)
            else SpendPathKind(str(self.spend_path))
        )
        object.__setattr__(self, "spend_path", path)
        leaves = tuple(self.revealed_leaves)
        for index, leaf in enumerate(leaves):
            if not isinstance(leaf, TapscriptLeaf):
                raise InvalidRequestError(
                    f"revealed_leaves[{index}] must be a TapscriptLeaf"
                )
        object.__setattr__(self, "revealed_leaves", leaves)
        hidden = tuple(
            _required_text(item, "hidden_branches item") for item in self.hidden_branches
        )
        object.__setattr__(self, "hidden_branches", hidden)
        if self.control_block is not None and not isinstance(
            self.control_block, ControlBlock
        ):
            raise InvalidRequestError("control_block must be a ControlBlock or None")
        object.__setattr__(
            self,
            "commitment_complete",
            _bool(self.commitment_complete, "commitment_complete"),
        )
        # Invariant: hidden branches force incomplete commitment.
        if hidden and self.commitment_complete:
            raise InvalidRequestError(
                "commitment_complete forbidden when hidden_branches are present"
            )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "commitment_complete": self.commitment_complete,
            "control_block": self.control_block.to_dict()
            if self.control_block
            else None,
            "hidden_branches": list(self.hidden_branches),
            "internal_key_hex": self.internal_key_hex,
            "merkle_root_hex": self.merkle_root_hex,
            "output_key_hex": self.output_key_hex,
            "revealed_leaves": [leaf.to_dict() for leaf in self.revealed_leaves],
            "schema_version": self.schema_version,
            "spend_path": self.spend_path.value,
            "tweak_digest": self.tweak_digest,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


def parse_control_block(
    control: bytes | str,
    *,
    max_bytes: int = DEFAULT_MAX_CONTROL_BLOCK_BYTES,
    max_depth: int = DEFAULT_MAX_MERKLE_DEPTH,
) -> ControlBlock:
    """Parse a BIP-341 control block; incomplete length stays incomplete."""

    data = normalize_script_bytes(control)
    if len(data) > max_bytes:
        raise ResourceLimitError("control block exceeds max_bytes")
    if len(data) < 33:
        raise InvalidRequestError("control block must be at least 33 bytes")
    remainder = len(data) - 33
    if remainder % 32 != 0:
        # Malformed — record as incomplete rather than inventing nodes.
        leaf_version = data[0] & 0xFE
        parity = data[0] & 1
        internal = data[1:33].hex()
        return ControlBlock(
            raw_digest=bytes_digest(data),
            leaf_version=leaf_version,
            parity=parity,
            internal_key_hex=internal,
            merkle_nodes=(),
            depth=0,
            complete=False,
            attributes={"malformed_length": True, "raw_len": len(data)},
        )
    depth = remainder // 32
    if depth > max_depth:
        raise ResourceLimitError("control block merkle depth exceeds max_depth")
    leaf_version = data[0] & 0xFE
    parity = data[0] & 1
    internal = data[1:33]
    nodes: list[str] = []
    for i in range(depth):
        start = 33 + i * 32
        nodes.append(data[start : start + 32].hex())
    return ControlBlock(
        raw_digest=bytes_digest(data),
        leaf_version=leaf_version,
        parity=parity,
        internal_key_hex=internal.hex(),
        merkle_nodes=tuple(nodes),
        depth=depth,
        complete=True,
    )


def bind_tapscript_leaf(
    script: bytes | str,
    *,
    leaf_version: int = LEAF_VERSION_TAPSCRIPT,
    availability: LeafAvailability | str = LeafAvailability.AVAILABLE,
    decode: bool = True,
    attributes: Mapping[str, Any] | None = None,
) -> TapscriptLeaf:
    """Bind a revealed or hidden tapscript leaf."""

    data = normalize_script_bytes(script)
    avail = (
        availability
        if isinstance(availability, LeafAvailability)
        else LeafAvailability(str(availability))
    )
    program: ScriptProgram | None = None
    if decode and data and avail is LeafAvailability.AVAILABLE:
        program = decode_script(data, version=ScriptVersion.TAPSCRIPT)
    leaf_hash_raw = tapleaf_hash(data, leaf_version=leaf_version) if data else b""
    return TapscriptLeaf(
        leaf_version=leaf_version,
        script_digest=bytes_digest(data) if data else "",
        script_hex=data.hex(),
        leaf_hash=f"sha256:{leaf_hash_raw.hex()}" if leaf_hash_raw else "",
        availability=avail,
        program=program,
        attributes=dict(attributes or {}),
    )


def bind_taproot_commitment(
    *,
    internal_key: bytes | str,
    output_key: bytes | str = b"",
    revealed_leaves: Sequence[TapscriptLeaf] = (),
    control_block: ControlBlock | None = None,
    hidden_branch_digests: Sequence[str] = (),
    spend_path: SpendPathKind | str = SpendPathKind.UNKNOWN,
    attributes: Mapping[str, Any] | None = None,
) -> TaprootCommitment:
    """Construct a Taproot commitment record with hidden-branch tracking."""

    internal = normalize_script_bytes(internal_key)
    if len(internal) != 32:
        raise InvalidRequestError("internal_key must be 32 bytes")
    out = normalize_script_bytes(output_key) if output_key else b""
    if out and len(out) != 32:
        raise InvalidRequestError("output_key must be 32 bytes when set")

    leaves = tuple(revealed_leaves)
    hidden = list(hidden_branch_digests)
    for leaf in leaves:
        if leaf.is_hidden:
            label = leaf.leaf_hash or leaf.script_digest or "hidden-leaf"
            if label not in hidden:
                hidden.append(label)

    merkle_root = b""
    if control_block is not None and control_block.complete and leaves:
        # Reconstruct root from first revealed leaf + merkle path nodes.
        leaf = leaves[0]
        if leaf.leaf_hash.startswith("sha256:"):
            current = bytes.fromhex(leaf.leaf_hash[7:])
            for node_hex in control_block.merkle_nodes:
                node = bytes.fromhex(node_hex)
                current = tapbranch_hash(current, node)
            merkle_root = current

    path = (
        spend_path
        if isinstance(spend_path, SpendPathKind)
        else SpendPathKind(str(spend_path))
    )
    if path is SpendPathKind.UNKNOWN:
        if control_block is not None:
            path = SpendPathKind.SCRIPT_PATH
        elif not leaves and not hidden:
            path = SpendPathKind.KEY_PATH

    complete = (
        not hidden
        and (
            path is SpendPathKind.KEY_PATH
            or (control_block is not None and control_block.complete and bool(leaves))
        )
    )

    return TaprootCommitment(
        internal_key_hex=internal.hex(),
        output_key_hex=out.hex() if out else "",
        merkle_root_hex=merkle_root.hex() if merkle_root else "",
        spend_path=path,
        revealed_leaves=leaves,
        hidden_branches=tuple(hidden),
        control_block=control_block,
        commitment_complete=complete,
        attributes=dict(attributes or {}),
    )


def tapscript_path_status(
    commitment: TaprootCommitment,
    *,
    claim_pass: bool = False,
) -> SemanticPassStatus:
    """Fail-closed status for a taproot spend path."""

    if commitment.hidden_branches:
        return SemanticPassStatus.INCOMPLETE
    if commitment.spend_path is SpendPathKind.SCRIPT_PATH:
        if commitment.control_block is None or not commitment.control_block.complete:
            return SemanticPassStatus.INCOMPLETE
        if not commitment.revealed_leaves:
            return SemanticPassStatus.INCOMPLETE
        for leaf in commitment.revealed_leaves:
            if leaf.is_hidden:
                return SemanticPassStatus.INCOMPLETE
            if leaf.program is not None and (
                not leaf.program.fully_decoded or leaf.program.unsupported_opcodes
            ):
                return (
                    SemanticPassStatus.UNSUPPORTED
                    if leaf.program.unsupported_opcodes
                    else SemanticPassStatus.INCOMPLETE
                )
    if claim_pass and commitment.commitment_complete:
        return SemanticPassStatus.PASS
    if claim_pass and not commitment.commitment_complete:
        return SemanticPassStatus.FAIL_CLOSED
    return SemanticPassStatus.INCOMPLETE


__all__ = [
    "DEFAULT_MAX_CONTROL_BLOCK_BYTES",
    "DEFAULT_MAX_MERKLE_DEPTH",
    "LEAF_VERSION_TAPSCRIPT",
    "TAPSCRIPT_SCHEMA_VERSION",
    "ControlBlock",
    "LeafAvailability",
    "SpendPathKind",
    "TaprootCommitment",
    "TapscriptLeaf",
    "bind_taproot_commitment",
    "bind_tapscript_leaf",
    "parse_control_block",
    "tagged_hash",
    "tap_tweak",
    "tapbranch_hash",
    "tapleaf_hash",
    "tapscript_path_status",
]
