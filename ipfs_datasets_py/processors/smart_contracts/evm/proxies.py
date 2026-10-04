"""EVM proxy pattern detection and binding (CRYPTOIR-G220).

Recognizes EIP-1967 implementation/admin/beacon slots, EIP-1822 UUPS,
EIP-1167 minimal proxies (clones), EIP-2535 diamond facets, raw
``DELEGATECALL`` without a known layout (unknown), and
``SELFDESTRUCT``/redeployment risk.  Importing this module performs no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from ..artifacts import bytes_digest
from ..canonical import content_digest, freeze_json, thaw_json
from ..errors import InvalidRequestError
from ..models import ensure_secret_safe
from .semantics import (
    DisassemblyResult,
    disassemble_bytecode,
    normalize_bytecode,
)


PROXY_SCHEMA_VERSION = "smart-contract-evm-proxy-v1"

# EIP-1967 slots (bytes32(uint256(keccak256("eip1967.proxy.*")) - 1)).
EIP1967_IMPLEMENTATION_SLOT = (
    "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
)
EIP1967_ADMIN_SLOT = (
    "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"
)
EIP1967_BEACON_SLOT = (
    "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"
)

# EIP-1822 UUPS proxiable UUID slot: keccak256("PROXIABLE")
EIP1822_PROXIABLE_SLOT = (
    "0xc5f16f0fcc639fa48a6947836d9850f504798523bf8c9a3a87d5876cf622bcf7"
)

# EIP-1167 minimal proxy prefix/suffix around the 20-byte implementation.
# 363d3d373d3d3d363d73 <20 bytes> 5af43d82803e903d91602b57fd5bf3
_MINIMAL_PREFIX = bytes.fromhex("363d3d373d3d3d363d73")
_MINIMAL_SUFFIX = bytes.fromhex("5af43d82803e903d91602b57fd5bf3")
_MINIMAL_TOTAL_LEN = len(_MINIMAL_PREFIX) + 20 + len(_MINIMAL_SUFFIX)

# OpenZeppelin transparent/UUPS often embed the implementation slot constant.
_EIP1967_IMPL_SLOT_BYTES = bytes.fromhex(EIP1967_IMPLEMENTATION_SLOT[2:])
_EIP1967_ADMIN_SLOT_BYTES = bytes.fromhex(EIP1967_ADMIN_SLOT[2:])
_EIP1967_BEACON_SLOT_BYTES = bytes.fromhex(EIP1967_BEACON_SLOT[2:])
_EIP1822_SLOT_BYTES = bytes.fromhex(EIP1822_PROXIABLE_SLOT[2:])

# Diamond Loupe facet selectors (partial; presence is a hint, not proof).
_DIAMOND_SELECTORS = frozenset(
    {
        bytes.fromhex("7a0ed627"),  # facets()
        bytes.fromhex("adfca15e"),  # facetFunctionSelectors(address)
        bytes.fromhex("52ef6b2c"),  # facetAddresses()
        bytes.fromhex("cdffacc6"),  # facetAddress(bytes4)
        bytes.fromhex("1f931c1c"),  # diamondCut(...)
    }
)

_ADDRESS_RE_HEX = 40


class ProxyKind(StrEnum):
    """Closed vocabulary of recognized EVM proxy layouts."""

    NONE = "none"
    EIP1967 = "eip1967"
    BEACON = "beacon"
    DIAMOND = "diamond"
    MINIMAL = "minimal"
    UUPS = "uups"
    UNKNOWN = "unknown"


class RedeploymentRisk(StrEnum):
    """Whether selfdestruct/redeployment risk is observed."""

    NONE = "none"
    SELFDESTRUCT_PRESENT = "selfdestruct_present"
    CODE_EPOCH_CHANGED = "code_epoch_changed"
    UNKNOWN = "unknown"


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


def normalize_address(value: str) -> str:
    """Normalize a 20-byte address to lowercase ``0x``-prefixed hex."""

    text = _required_text(value, "address")
    if text.startswith(("0x", "0X")):
        text = text[2:]
    if len(text) != _ADDRESS_RE_HEX:
        raise InvalidRequestError("address must be 20 bytes (40 hex chars)")
    try:
        bytes.fromhex(text)
    except ValueError as exc:
        raise InvalidRequestError("address is not valid hex") from exc
    return "0x" + text.lower()


def _slot_value_to_address(value: str | bytes) -> str | None:
    """Extract a 20-byte address from a 32-byte storage slot value if present."""

    if isinstance(value, bytes):
        raw = value
    else:
        text = value.strip()
        if text.startswith(("0x", "0X")):
            text = text[2:]
        if len(text) != 64:
            return None
        try:
            raw = bytes.fromhex(text)
        except ValueError:
            return None
    if len(raw) != 32:
        return None
    # Address is the rightmost 20 bytes of a 32-byte word.
    return "0x" + raw[-20:].hex()


@dataclass(frozen=True, slots=True)
class ProxyBinding:
    """Explicit binding of a contract address to a proxy layout and targets.

    Unknown layouts and missing implementation targets remain explicit; they
    never silently collapse to a trusted implementation address.
    """

    proxy_address: str
    kind: ProxyKind
    implementation_address: str = ""
    admin_address: str = ""
    beacon_address: str = ""
    facet_addresses: tuple[str, ...] = ()
    storage_slots: Mapping[str, str] = field(default_factory=dict)
    bytecode_digest: str = ""
    has_delegatecall: bool = False
    redeployment_risk: RedeploymentRisk = RedeploymentRisk.NONE
    confidence: str = "static"
    diagnostics: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PROXY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "proxy_address", normalize_address(self.proxy_address)
        )
        kind = self.kind if isinstance(self.kind, ProxyKind) else ProxyKind(str(self.kind))
        object.__setattr__(self, "kind", kind)
        if self.implementation_address:
            object.__setattr__(
                self,
                "implementation_address",
                normalize_address(self.implementation_address),
            )
        else:
            object.__setattr__(self, "implementation_address", "")
        if self.admin_address:
            object.__setattr__(
                self, "admin_address", normalize_address(self.admin_address)
            )
        else:
            object.__setattr__(self, "admin_address", "")
        if self.beacon_address:
            object.__setattr__(
                self, "beacon_address", normalize_address(self.beacon_address)
            )
        else:
            object.__setattr__(self, "beacon_address", "")
        facets = tuple(
            normalize_address(item) for item in self.facet_addresses if item
        )
        object.__setattr__(self, "facet_addresses", facets)
        slots = {
            _required_text(key, "storage slot key"): _required_text(
                val, "storage slot value"
            )
            for key, val in dict(self.storage_slots).items()
        }
        object.__setattr__(self, "storage_slots", MappingProxyType(slots))
        if self.bytecode_digest:
            digest = _required_text(self.bytecode_digest, "bytecode_digest")
            if not digest.startswith("sha256:"):
                raise InvalidRequestError(
                    "bytecode_digest must be a tagged sha256 digest"
                )
            object.__setattr__(self, "bytecode_digest", digest)
        else:
            object.__setattr__(self, "bytecode_digest", "")
        risk = (
            self.redeployment_risk
            if isinstance(self.redeployment_risk, RedeploymentRisk)
            else RedeploymentRisk(str(self.redeployment_risk))
        )
        object.__setattr__(self, "redeployment_risk", risk)
        object.__setattr__(
            self,
            "confidence",
            _required_text(self.confidence, "confidence"),
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_required_text(item, "diagnostics item") for item in self.diagnostics),
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        # Unknown with no diagnostics is invalid — always explain.
        if kind is ProxyKind.UNKNOWN and not self.diagnostics:
            raise InvalidRequestError(
                "unknown proxy binding requires diagnostics explaining uncertainty"
            )
        ensure_secret_safe(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "admin_address": self.admin_address,
            "attributes": thaw_json(self.attributes),
            "beacon_address": self.beacon_address,
            "bytecode_digest": self.bytecode_digest,
            "confidence": self.confidence,
            "diagnostics": list(self.diagnostics),
            "facet_addresses": list(self.facet_addresses),
            "has_delegatecall": self.has_delegatecall,
            "implementation_address": self.implementation_address,
            "kind": self.kind.value if isinstance(self.kind, ProxyKind) else str(self.kind),
            "proxy_address": self.proxy_address,
            "redeployment_risk": self.redeployment_risk.value
            if isinstance(self.redeployment_risk, RedeploymentRisk)
            else str(self.redeployment_risk),
            "schema_version": self.schema_version,
            "storage_slots": dict(self.storage_slots),
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


def detect_minimal_proxy(bytecode: bytes) -> str | None:
    """Return implementation address if *bytecode* matches EIP-1167, else None."""

    data = normalize_bytecode(bytecode)
    if len(data) != _MINIMAL_TOTAL_LEN:
        return None
    if not data.startswith(_MINIMAL_PREFIX):
        return None
    if not data.endswith(_MINIMAL_SUFFIX):
        return None
    impl = data[len(_MINIMAL_PREFIX) : len(_MINIMAL_PREFIX) + 20]
    return "0x" + impl.hex()


def _contains_bytes(haystack: bytes, needle: bytes) -> bool:
    return needle in haystack


def _diamond_hints(bytecode: bytes, disasm: DisassemblyResult | None) -> bool:
    """Heuristic: diamond loupe selectors appear as PUSH4 immediates."""

    if any(sel in bytecode for sel in _DIAMOND_SELECTORS):
        return True
    if disasm is None:
        return False
    for ins in disasm.instructions:
        if ins.mnemonic == "PUSH4" and ins.immediate in _DIAMOND_SELECTORS:
            return True
    return False


def detect_proxy_pattern(
    *,
    proxy_address: str,
    runtime_bytecode: bytes | str,
    storage: Mapping[str, str] | None = None,
    previous_code_digest: str = "",
    disassembly: DisassemblyResult | None = None,
) -> ProxyBinding:
    """Classify proxy layout from runtime bytecode and optional storage slots.

    Storage values are treated as evidence, not authority: a claimed
    implementation address is only recorded when present.  Absence remains
    explicit.
    """

    address = normalize_address(proxy_address)
    data = normalize_bytecode(runtime_bytecode)
    digest = bytes_digest(data)
    slots = {str(k): str(v) for k, v in dict(storage or {}).items()}
    diagnostics: list[str] = []

    if disassembly is None and data:
        disassembly = disassemble_bytecode(data)

    has_delegatecall = False
    has_selfdestruct = False
    if disassembly is not None:
        for ins in disassembly.instructions:
            if ins.opcode == 0xF4:
                has_delegatecall = True
            if ins.opcode == 0xFF:
                has_selfdestruct = True
    else:
        has_delegatecall = b"\xf4" in data
        has_selfdestruct = b"\xff" in data

    redeployment = RedeploymentRisk.NONE
    if has_selfdestruct:
        redeployment = RedeploymentRisk.SELFDESTRUCT_PRESENT
        diagnostics.append("SELFDESTRUCT present; redeployment risk is explicit")
    if previous_code_digest:
        if not previous_code_digest.startswith("sha256:"):
            raise InvalidRequestError(
                "previous_code_digest must be a tagged sha256 digest"
            )
        if previous_code_digest != digest:
            redeployment = RedeploymentRisk.CODE_EPOCH_CHANGED
            diagnostics.append(
                "runtime bytecode digest differs from previous code epoch"
            )

    # 1. EIP-1167 minimal proxy (exact layout).
    minimal_impl = detect_minimal_proxy(data)
    if minimal_impl is not None:
        return ProxyBinding(
            proxy_address=address,
            kind=ProxyKind.MINIMAL,
            implementation_address=minimal_impl,
            bytecode_digest=digest,
            has_delegatecall=True,
            redeployment_risk=redeployment,
            confidence="bytecode_pattern",
            diagnostics=tuple(diagnostics)
            + ("EIP-1167 minimal proxy pattern matched",),
            storage_slots=slots,
        )

    # Pull addresses from known slots when supplied.
    impl_from_slot = None
    admin_from_slot = None
    beacon_from_slot = None
    uups_from_slot = None
    for key, value in slots.items():
        key_l = key.lower()
        if key_l in {
            EIP1967_IMPLEMENTATION_SLOT.lower(),
            "eip1967.proxy.implementation",
            "implementation",
        }:
            impl_from_slot = _slot_value_to_address(value) or impl_from_slot
        elif key_l in {
            EIP1967_ADMIN_SLOT.lower(),
            "eip1967.proxy.admin",
            "admin",
        }:
            admin_from_slot = _slot_value_to_address(value) or admin_from_slot
        elif key_l in {
            EIP1967_BEACON_SLOT.lower(),
            "eip1967.proxy.beacon",
            "beacon",
        }:
            beacon_from_slot = _slot_value_to_address(value) or beacon_from_slot
        elif key_l in {
            EIP1822_PROXIABLE_SLOT.lower(),
            "proxiable",
            "uups",
        }:
            uups_from_slot = _slot_value_to_address(value) or uups_from_slot

    # 2. Beacon (EIP-1967 beacon slot present).
    beacon_hint = _contains_bytes(data, _EIP1967_BEACON_SLOT_BYTES) or bool(
        beacon_from_slot
    )
    if beacon_hint:
        if not beacon_from_slot:
            diagnostics.append(
                "beacon slot constant or label present without resolved beacon address"
            )
        return ProxyBinding(
            proxy_address=address,
            kind=ProxyKind.BEACON,
            implementation_address=impl_from_slot or "",
            admin_address=admin_from_slot or "",
            beacon_address=beacon_from_slot or "",
            bytecode_digest=digest,
            has_delegatecall=has_delegatecall,
            redeployment_risk=redeployment,
            confidence="slot_or_bytecode" if beacon_from_slot else "bytecode_hint",
            diagnostics=tuple(diagnostics) + ("EIP-1967 beacon proxy pattern",),
            storage_slots=slots,
        )

    # 3. Diamond (EIP-2535).
    if _diamond_hints(data, disassembly):
        facets: list[str] = []
        for key, value in slots.items():
            if "facet" in key.lower():
                addr = _slot_value_to_address(value)
                if addr:
                    facets.append(addr)
        diagnostics.append("EIP-2535 diamond loupe selectors or facet slots observed")
        return ProxyBinding(
            proxy_address=address,
            kind=ProxyKind.DIAMOND,
            implementation_address=impl_from_slot or "",
            admin_address=admin_from_slot or "",
            facet_addresses=tuple(dict.fromkeys(facets)),
            bytecode_digest=digest,
            has_delegatecall=has_delegatecall,
            redeployment_risk=redeployment,
            confidence="selector_hint",
            diagnostics=tuple(diagnostics),
            storage_slots=slots,
        )

    # 4. UUPS (EIP-1822 proxiable slot).
    uups_hint = _contains_bytes(data, _EIP1822_SLOT_BYTES) or bool(uups_from_slot)
    if uups_hint:
        return ProxyBinding(
            proxy_address=address,
            kind=ProxyKind.UUPS,
            implementation_address=uups_from_slot or impl_from_slot or "",
            admin_address=admin_from_slot or "",
            bytecode_digest=digest,
            has_delegatecall=has_delegatecall,
            redeployment_risk=redeployment,
            confidence="slot_or_bytecode",
            diagnostics=tuple(diagnostics) + ("EIP-1822 UUPS proxiable pattern",),
            storage_slots=slots,
        )

    # 5. EIP-1967 transparent / standard implementation slot.
    eip1967_hint = (
        _contains_bytes(data, _EIP1967_IMPL_SLOT_BYTES)
        or _contains_bytes(data, _EIP1967_ADMIN_SLOT_BYTES)
        or bool(impl_from_slot)
        or bool(admin_from_slot)
    )
    if eip1967_hint:
        if not impl_from_slot:
            diagnostics.append(
                "EIP-1967 indicators present without resolved implementation address"
            )
        return ProxyBinding(
            proxy_address=address,
            kind=ProxyKind.EIP1967,
            implementation_address=impl_from_slot or "",
            admin_address=admin_from_slot or "",
            bytecode_digest=digest,
            has_delegatecall=has_delegatecall,
            redeployment_risk=redeployment,
            confidence="slot_or_bytecode" if impl_from_slot else "bytecode_hint",
            diagnostics=tuple(diagnostics) + ("EIP-1967 proxy pattern",),
            storage_slots=slots,
        )

    # 6. DELEGATECALL present without a known layout → UNKNOWN (explicit).
    if has_delegatecall:
        diagnostics.append(
            "DELEGATECALL present without recognized proxy layout; classified unknown"
        )
        return ProxyBinding(
            proxy_address=address,
            kind=ProxyKind.UNKNOWN,
            bytecode_digest=digest,
            has_delegatecall=True,
            redeployment_risk=redeployment,
            confidence="delegatecall_only",
            diagnostics=tuple(diagnostics),
            storage_slots=slots,
        )

    # 7. No proxy indicators.
    if not data:
        diagnostics.append("empty runtime bytecode; no proxy pattern")
    return ProxyBinding(
        proxy_address=address,
        kind=ProxyKind.NONE,
        bytecode_digest=digest,
        has_delegatecall=False,
        redeployment_risk=redeployment,
        confidence="none",
        diagnostics=tuple(diagnostics) or ("no proxy pattern detected",),
        storage_slots=slots,
    )


def bind_implementation(
    binding: ProxyBinding,
    *,
    implementation_address: str,
    implementation_bytecode_digest: str = "",
) -> ProxyBinding:
    """Return a new binding with an explicit implementation address filled in."""

    impl = normalize_address(implementation_address)
    attrs = dict(thaw_json(binding.attributes))
    if implementation_bytecode_digest:
        if not implementation_bytecode_digest.startswith("sha256:"):
            raise InvalidRequestError(
                "implementation_bytecode_digest must be a tagged sha256 digest"
            )
        attrs["implementation_bytecode_digest"] = implementation_bytecode_digest
    return ProxyBinding(
        proxy_address=binding.proxy_address,
        kind=binding.kind,
        implementation_address=impl,
        admin_address=binding.admin_address,
        beacon_address=binding.beacon_address,
        facet_addresses=binding.facet_addresses,
        storage_slots=dict(binding.storage_slots),
        bytecode_digest=binding.bytecode_digest,
        has_delegatecall=binding.has_delegatecall,
        redeployment_risk=binding.redeployment_risk,
        confidence=binding.confidence,
        diagnostics=binding.diagnostics + ("implementation bound explicitly",),
        attributes=attrs,
    )


__all__ = [
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
]
