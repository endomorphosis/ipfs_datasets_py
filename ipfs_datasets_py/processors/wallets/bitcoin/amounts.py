"""Exact satoshi arithmetic for Bitcoin amounts.

Amounts are always integer satoshis (base units). Binary floats are rejected.
"""

from __future__ import annotations

import re
from typing import Any

from ..errors import InvalidRequestError, NormalizationError
from ..models import ExactAmount
from .networks import BTC_DECIMALS

_MAX_MONEY_SATS = 21_000_000 * 100_000_000
_CANONICAL_INT = re.compile(r"^(?:0|[1-9][0-9]*)$")


def parse_sats(value: Any, *, field: str = "amount") -> int:
    """Parse a satoshi quantity from int or canonical decimal-integer string."""

    if isinstance(value, bool):
        raise NormalizationError(f"{field} must not be a boolean")
    if isinstance(value, float):
        raise InvalidRequestError(
            f"{field} must not be a binary float; use integer satoshis"
        )
    if isinstance(value, int):
        sats = value
    elif isinstance(value, str):
        text = value.strip()
        if not _CANONICAL_INT.fullmatch(text):
            raise NormalizationError(f"{field} must be a canonical decimal integer string")
        sats = int(text, 10)
    else:
        raise NormalizationError(f"{field} must be an int or decimal integer string")
    if sats < 0:
        raise NormalizationError(f"{field} must not be negative")
    if sats > _MAX_MONEY_SATS:
        raise NormalizationError(f"{field} exceeds maximum Bitcoin supply in sats")
    return sats


def exact_sats(value: Any, *, field: str = "amount") -> ExactAmount:
    """Return an :class:`ExactAmount` with 8 decimal places."""

    return ExactAmount.from_int(parse_sats(value, field=field), decimals=BTC_DECIMALS)


def require_no_float_amount(value: Any, *, field: str = "amount") -> None:
    if isinstance(value, float):
        raise InvalidRequestError(
            f"{field} must not be a binary float; use integer satoshis"
        )


__all__ = [
    "exact_sats",
    "parse_sats",
    "require_no_float_amount",
]
