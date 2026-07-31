"""Classic XRPL account address validation (base58check).

No signing, seed derivation, or secret material is handled here. X-addresses
and Xaman-specific encodings are out of scope for the ledger provider.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..errors import InvalidRequestError, NormalizationError
from .networks import XRPLNetwork

# XRPL base58 alphabet (ripple alphabet).
_ALPHABET = "rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz"
_ALPHABET_INDEX = {ch: i for i, ch in enumerate(_ALPHABET)}
# Full alphabet is valid after the leading 'r' (ripple alphabet includes 'r').
_CLASSIC_RE = re.compile(r"^r[" + re.escape(_ALPHABET) + r"]{24,34}$")


class AccountEncoding(StrEnum):
    CLASSIC = "classic"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AccountDescriptor:
    """Validated classic account address for a configured network."""

    address: str
    encoding: AccountEncoding
    network: XRPLNetwork
    account_id_hex: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "address": self.address,
            "encoding": self.encoding.value,
            "network": self.network.value,
        }
        if self.account_id_hex is not None:
            result["account_id_hex"] = self.account_id_hex
        return result


def _b58decode(value: str) -> bytes:
    n = 0
    for ch in value:
        try:
            n = n * 58 + _ALPHABET_INDEX[ch]
        except KeyError as exc:
            raise NormalizationError("address contains invalid base58 character") from exc
    # Convert to bytes without losing leading zero digits (alphabet[0] == 'r' is
    # not a zero pad; classic XRPL addresses do not use leading-zero padding the
    # same way as Bitcoin. We size to payload length from decoded bit length.
    raw = n.to_bytes((n.bit_length() + 7) // 8 or 1, "big")
    # XRPL classic addresses always start with 'r' (version 0 payload); decoded
    # payload is 25 bytes (1 version + 20 account id + 4 checksum).
    if len(raw) < 25:
        raw = raw.rjust(25, b"\x00")
    return raw


def _double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def validate_classic_address(
    address: str,
    *,
    network: XRPLNetwork,
    require_checksum: bool = True,
) -> AccountDescriptor:
    """Validate a classic ``r…`` account for *network*.

    Network is required so callers bind identity; classic addresses themselves
    are not network-tagged, so mismatch is a caller configuration error only
    when combined with chain-scoped ingestion.
    """

    if not isinstance(network, XRPLNetwork):
        raise InvalidRequestError("network must be an XRPLNetwork")
    if not isinstance(address, str) or not address.strip():
        raise NormalizationError("address must not be empty")
    text = address.strip()
    if text.startswith("X") or text.startswith("T"):
        raise NormalizationError(
            "X-address encoding is not supported by the XRPL ledger provider; "
            "use classic r-addresses (Xaman payload concerns stay out of scope)"
        )
    if not _CLASSIC_RE.fullmatch(text):
        raise NormalizationError("address is not a classic XRPL r-address")
    if not require_checksum:
        return AccountDescriptor(
            address=text,
            encoding=AccountEncoding.CLASSIC,
            network=network,
        )
    try:
        decoded = _b58decode(text)
    except NormalizationError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise NormalizationError("address could not be base58-decoded") from exc
    if len(decoded) != 25:
        raise NormalizationError("classic address payload must be 25 bytes")
    payload, checksum = decoded[:-4], decoded[-4:]
    if payload[0] != 0x00:
        raise NormalizationError("classic address version byte must be 0x00")
    expected = _double_sha256(payload)[:4]
    if checksum != expected:
        raise NormalizationError("classic address checksum mismatch")
    account_id = payload[1:].hex()
    return AccountDescriptor(
        address=text,
        encoding=AccountEncoding.CLASSIC,
        network=network,
        account_id_hex=account_id,
    )


def describe_account(
    address: str,
    *,
    network: XRPLNetwork,
) -> AccountDescriptor:
    """Alias for :func:`validate_classic_address` used by processors."""

    return validate_classic_address(address, network=network)


__all__ = [
    "AccountDescriptor",
    "AccountEncoding",
    "describe_account",
    "validate_classic_address",
]
