"""Bitcoin script and address descriptors without optional crypto SDKs.

Pure-Python classification for Legacy (P2PKH/P2SH), SegWit (P2WPKH/P2WSH), and
Taproot (P2TR). Ownership/change clustering is intentionally unsupported.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..errors import InvalidRequestError, NormalizationError
from .networks import BitcoinNetwork, BitcoinNetworkProfile, network_profile

_BASE58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_HEX_RE = re.compile(r"^(?:[0-9a-fA-F]{2})+$")


class ScriptType(StrEnum):
    """Standard Bitcoin script forms recognized by the processor."""

    P2PKH = "p2pkh"
    P2SH = "p2sh"
    P2WPKH = "p2wpkh"
    P2WSH = "p2wsh"
    P2TR = "p2tr"
    P2PK = "p2pk"
    MULTISIG = "multisig"
    NULL_DATA = "null_data"
    UNKNOWN = "unknown"
    COINBASE = "coinbase"


class AddressEncoding(StrEnum):
    BASE58CHECK = "base58check"
    BECH32 = "bech32"
    BECH32M = "bech32m"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class ScriptDescriptor:
    """Versioned description of a locking script and optional address.

    Descriptors never assert multi-address ownership clustering or change
    detection. They only classify script form and network binding when an
    address is present.
    """

    script_type: ScriptType
    script_hex: str | None = None
    address: str | None = None
    encoding: AddressEncoding = AddressEncoding.NONE
    witness_version: int | None = None
    network: BitcoinNetwork | None = None
    is_standard: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.script_type, ScriptType):
            raise InvalidRequestError("script_type must be a ScriptType")
        if not isinstance(self.encoding, AddressEncoding):
            raise InvalidRequestError("encoding must be an AddressEncoding")
        if self.script_hex is not None:
            if not isinstance(self.script_hex, str) or not _HEX_RE.fullmatch(
                self.script_hex
            ):
                raise InvalidRequestError("script_hex must be even-length hex")
            object.__setattr__(self, "script_hex", self.script_hex.lower())
        if self.address is not None and not str(self.address).strip():
            raise InvalidRequestError("address must not be empty when provided")
        if self.witness_version is not None and (
            isinstance(self.witness_version, bool)
            or not isinstance(self.witness_version, int)
            or self.witness_version < 0
            or self.witness_version > 16
        ):
            raise InvalidRequestError("witness_version must be 0..16")

    @property
    def is_segwit(self) -> bool:
        return self.script_type in {
            ScriptType.P2WPKH,
            ScriptType.P2WSH,
            ScriptType.P2TR,
        }

    @property
    def is_taproot(self) -> bool:
        return self.script_type is ScriptType.P2TR

    @property
    def is_legacy(self) -> bool:
        return self.script_type in {ScriptType.P2PKH, ScriptType.P2SH, ScriptType.P2PK}

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "script_type": self.script_type.value,
            "encoding": self.encoding.value,
            "is_standard": self.is_standard,
            "is_segwit": self.is_segwit,
            "is_taproot": self.is_taproot,
            "is_legacy": self.is_legacy,
        }
        if self.script_hex is not None:
            result["script_hex"] = self.script_hex
        if self.address is not None:
            result["address"] = self.address
        if self.witness_version is not None:
            result["witness_version"] = self.witness_version
        if self.network is not None:
            result["network"] = self.network.value
        return result


def _b58decode(value: str) -> bytes:
    if not value:
        raise InvalidRequestError("empty base58 string")
    num = 0
    for char in value.encode("ascii"):
        try:
            digit = _BASE58_ALPHABET.index(char)
        except ValueError as exc:
            raise InvalidRequestError("invalid base58 character") from exc
        num = num * 58 + digit
    combined = num.to_bytes((num.bit_length() + 7) // 8 or 1, "big")
    pad = 0
    for char in value:
        if char == "1":
            pad += 1
        else:
            break
    return b"\x00" * pad + combined


def _b58check_decode(value: str) -> bytes:
    raw = _b58decode(value)
    if len(raw) < 5:
        raise InvalidRequestError("base58check payload too short")
    payload, checksum = raw[:-4], raw[-4:]
    expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if checksum != expected:
        raise InvalidRequestError("base58check checksum mismatch")
    return payload


def _bech32_polymod(values: list[int]) -> int:
    generator = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for value in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ value
        for i in range(5):
            if (top >> i) & 1:
                chk ^= generator[i]
    return chk


def _bech32_hrp_expand(hrp: str) -> list[int]:
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_verify(hrp: str, data: list[int], *, spec: str) -> bool:
    const = 1 if spec == "bech32" else 0x2BC830A3
    return _bech32_polymod(_bech32_hrp_expand(hrp) + data) == const


def _convertbits(
    data: list[int],
    from_bits: int,
    to_bits: int,
    *,
    pad: bool = True,
) -> list[int] | None:
    acc = 0
    bits = 0
    result: list[int] = []
    maxv = (1 << to_bits) - 1
    for value in data:
        if value < 0 or (value >> from_bits):
            return None
        acc = (acc << from_bits) | value
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            result.append((acc >> bits) & maxv)
    if pad:
        if bits:
            result.append((acc << (to_bits - bits)) & maxv)
    elif bits >= from_bits or ((acc << (to_bits - bits)) & maxv):
        return None
    return result


def _decode_segwit_address(address: str) -> tuple[str, int, bytes, AddressEncoding]:
    lower = address.lower()
    if address != lower and address != address.upper():
        raise InvalidRequestError("mixed-case bech32 address is invalid")
    address = lower
    if address.count("1") != 1:
        raise InvalidRequestError("invalid bech32 separator")
    hrp, data_part = address.rsplit("1", 1)
    if not hrp or len(data_part) < 6:
        raise InvalidRequestError("invalid bech32 address length")
    try:
        data = [_BECH32_CHARSET.index(c) for c in data_part]
    except ValueError as exc:
        raise InvalidRequestError("invalid bech32 character") from exc
    if _bech32_verify(hrp, data, spec="bech32"):
        encoding = AddressEncoding.BECH32
    elif _bech32_verify(hrp, data, spec="bech32m"):
        encoding = AddressEncoding.BECH32M
    else:
        raise InvalidRequestError("bech32 checksum mismatch")
    witver = data[0]
    decoded = _convertbits(data[1:-6], 5, 8, pad=False)
    if decoded is None or witver > 16:
        raise InvalidRequestError("invalid witness program")
    program = bytes(decoded)
    if len(program) < 2 or len(program) > 40:
        raise InvalidRequestError("invalid witness program length")
    if witver == 0 and len(program) not in (20, 32):
        raise InvalidRequestError("invalid v0 witness program length")
    if witver == 0 and encoding is not AddressEncoding.BECH32:
        raise InvalidRequestError("v0 witness addresses must use bech32")
    if witver != 0 and encoding is not AddressEncoding.BECH32M:
        raise InvalidRequestError("v1+ witness addresses must use bech32m")
    return hrp, witver, program, encoding


def classify_script_hex(script_hex: str | None) -> ScriptType:
    """Best-effort classification of a locking script hex string."""

    if script_hex is None:
        return ScriptType.UNKNOWN
    if not _HEX_RE.fullmatch(script_hex):
        raise InvalidRequestError("script_hex must be even-length hex")
    script = bytes.fromhex(script_hex)
    # P2PKH: OP_DUP OP_HASH160 <20> OP_EQUALVERIFY OP_CHECKSIG
    if (
        len(script) == 25
        and script[0] == 0x76
        and script[1] == 0xA9
        and script[2] == 0x14
        and script[23] == 0x88
        and script[24] == 0xAC
    ):
        return ScriptType.P2PKH
    # P2SH: OP_HASH160 <20> OP_EQUAL
    if (
        len(script) == 23
        and script[0] == 0xA9
        and script[1] == 0x14
        and script[22] == 0x87
    ):
        return ScriptType.P2SH
    # P2WPKH: 0 <20>
    if len(script) == 22 and script[0] == 0x00 and script[1] == 0x14:
        return ScriptType.P2WPKH
    # P2WSH: 0 <32>
    if len(script) == 34 and script[0] == 0x00 and script[1] == 0x20:
        return ScriptType.P2WSH
    # P2TR: 1 <32>
    if len(script) == 34 and script[0] == 0x51 and script[1] == 0x20:
        return ScriptType.P2TR
    # OP_RETURN
    if script and script[0] == 0x6A:
        return ScriptType.NULL_DATA
    # bare multisig (m <keys...> n OP_CHECKMULTISIG)
    if script and script[-1] == 0xAE:
        return ScriptType.MULTISIG
    # compressed/uncompressed P2PK
    if (
        len(script) in (35, 67)
        and script[-1] == 0xAC
        and script[0] in (33, 65)
    ):
        return ScriptType.P2PK
    return ScriptType.UNKNOWN


def _profile_for_hrp(hrp: str) -> BitcoinNetworkProfile | None:
    for profile in (
        network_profile(BitcoinNetwork.MAINNET),
        network_profile(BitcoinNetwork.TESTNET),
        network_profile(BitcoinNetwork.SIGNET),
        network_profile(BitcoinNetwork.REGTEST),
    ):
        if profile.hrp == hrp:
            # Prefer testnet over signet when HRP collides (both use "tb").
            if hrp == "tb" and profile.network is BitcoinNetwork.SIGNET:
                continue
            return profile
    if hrp == "tb":
        return network_profile(BitcoinNetwork.TESTNET)
    return None


def describe_address(
    address: str,
    *,
    network: BitcoinNetwork | str | None = None,
) -> ScriptDescriptor:
    """Validate and classify an address for an optional expected network."""

    if not isinstance(address, str) or not address.strip():
        raise InvalidRequestError("address must not be empty")
    address = address.strip()
    expected = network_profile(network) if network is not None else None

    # SegWit / Taproot
    if "1" in address and address.split("1", 1)[0].lower() in {
        "bc",
        "tb",
        "bcrt",
    }:
        hrp, witver, program, encoding = _decode_segwit_address(address)
        profile = _profile_for_hrp(hrp)
        if profile is None:
            raise NormalizationError(f"unsupported bech32 HRP: {hrp!r}")
        if expected is not None and profile.hrp != expected.hrp:
            raise NormalizationError(
                f"address network mismatch: address uses hrp={hrp!r}, "
                f"configured network is {expected.network.value}"
            )
        if expected is not None and expected.network is BitcoinNetwork.SIGNET:
            # Explicit signet selection is allowed with tb HRP.
            profile = expected
        if witver == 0 and len(program) == 20:
            script_type = ScriptType.P2WPKH
        elif witver == 0 and len(program) == 32:
            script_type = ScriptType.P2WSH
        elif witver == 1 and len(program) == 32:
            script_type = ScriptType.P2TR
        else:
            script_type = ScriptType.UNKNOWN
        return ScriptDescriptor(
            script_type=script_type,
            address=address if address == address.lower() else address.lower(),
            encoding=encoding,
            witness_version=witver,
            network=profile.network if expected is None else expected.network,
            is_standard=script_type is not ScriptType.UNKNOWN,
        )

    # Legacy Base58Check
    try:
        payload = _b58check_decode(address)
    except InvalidRequestError as exc:
        raise NormalizationError(f"invalid Bitcoin address: {address!r}") from exc
    if len(payload) != 21:
        raise NormalizationError("legacy address payload must be 21 bytes")
    version = payload[0]
    matched: BitcoinNetworkProfile | None = None
    script_type = ScriptType.UNKNOWN
    for candidate in (
        BitcoinNetwork.MAINNET,
        BitcoinNetwork.TESTNET,
        BitcoinNetwork.SIGNET,
        BitcoinNetwork.REGTEST,
    ):
        profile = network_profile(candidate)
        if version in profile.legacy_p2pkh_versions:
            matched = profile
            script_type = ScriptType.P2PKH
            break
        if version in profile.legacy_p2sh_versions:
            matched = profile
            script_type = ScriptType.P2SH
            break
    if matched is None:
        raise NormalizationError(f"unknown legacy address version: {version}")
    # Prefer testnet over signet/regtest for ambiguous version bytes.
    if matched.network in {BitcoinNetwork.SIGNET, BitcoinNetwork.REGTEST}:
        matched = network_profile(BitcoinNetwork.TESTNET)
        if version in matched.legacy_p2pkh_versions:
            script_type = ScriptType.P2PKH
        else:
            script_type = ScriptType.P2SH
    if expected is not None:
        if version not in expected.legacy_p2pkh_versions and version not in (
            expected.legacy_p2sh_versions
        ):
            raise NormalizationError(
                f"address network mismatch for configured network "
                f"{expected.network.value}"
            )
        matched = expected
        if version in expected.legacy_p2pkh_versions:
            script_type = ScriptType.P2PKH
        else:
            script_type = ScriptType.P2SH
    return ScriptDescriptor(
        script_type=script_type,
        address=address,
        encoding=AddressEncoding.BASE58CHECK,
        network=matched.network,
        is_standard=True,
    )


def describe_script(
    *,
    script_hex: str | None = None,
    address: str | None = None,
    network: BitcoinNetwork | str | None = None,
    coinbase: bool = False,
) -> ScriptDescriptor:
    """Build a :class:`ScriptDescriptor` from script hex and/or address."""

    if coinbase:
        return ScriptDescriptor(
            script_type=ScriptType.COINBASE,
            script_hex=script_hex.lower() if script_hex else None,
            address=None,
            encoding=AddressEncoding.NONE,
            network=network_profile(network).network if network else None,
            is_standard=False,
        )
    if address is not None:
        descriptor = describe_address(address, network=network)
        if script_hex is not None:
            classified = classify_script_hex(script_hex)
            if (
                classified is not ScriptType.UNKNOWN
                and classified is not descriptor.script_type
            ):
                raise NormalizationError(
                    "script_hex classification disagrees with address type "
                    f"({classified.value} vs {descriptor.script_type.value})"
                )
            return ScriptDescriptor(
                script_type=descriptor.script_type,
                script_hex=script_hex.lower(),
                address=descriptor.address,
                encoding=descriptor.encoding,
                witness_version=descriptor.witness_version,
                network=descriptor.network,
                is_standard=descriptor.is_standard,
            )
        return descriptor
    if script_hex is not None:
        return ScriptDescriptor(
            script_type=classify_script_hex(script_hex),
            script_hex=script_hex.lower(),
            encoding=AddressEncoding.NONE,
            network=network_profile(network).network if network else None,
        )
    raise InvalidRequestError("script_hex or address is required")


__all__ = [
    "AddressEncoding",
    "ScriptDescriptor",
    "ScriptType",
    "classify_script_hex",
    "describe_address",
    "describe_script",
]
