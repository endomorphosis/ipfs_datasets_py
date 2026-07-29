"""Exact drop and issued-currency arithmetic for XRPL amounts.

XRP is always integer drops (base units). Issued currency values are decimal
strings projected to integer base units with an explicit scale. Binary floats
are rejected.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any

from ..errors import InvalidRequestError, NormalizationError
from ..models import ExactAmount
from .networks import DROPS_PER_XRP, ISSUED_MAX_DECIMALS, XRP_DECIMALS

_CANONICAL_INT = re.compile(r"^(?:0|[1-9][0-9]*)$")
_MAX_DROPS = 100_000_000_000 * DROPS_PER_XRP  # 1e11 XRP absolute ledger bound


def parse_drops(value: Any, *, field: str = "amount") -> int:
    """Parse an XRP quantity expressed as integer drops."""

    if isinstance(value, bool):
        raise NormalizationError(f"{field} must not be a boolean")
    if isinstance(value, float):
        raise InvalidRequestError(
            f"{field} must not be a binary float; use integer drops"
        )
    if isinstance(value, int):
        drops = value
    elif isinstance(value, str):
        text = value.strip()
        if not _CANONICAL_INT.fullmatch(text):
            raise NormalizationError(
                f"{field} must be a canonical decimal integer string of drops"
            )
        drops = int(text, 10)
    else:
        raise NormalizationError(f"{field} must be an int or decimal integer string")
    if drops < 0:
        raise NormalizationError(f"{field} must not be negative")
    if drops > _MAX_DROPS:
        raise NormalizationError(f"{field} exceeds maximum XRPL drop bound")
    return drops


def exact_drops(value: Any, *, field: str = "amount") -> ExactAmount:
    """Return an :class:`ExactAmount` with 6 decimal places (drops)."""

    return ExactAmount.from_int(parse_drops(value, field=field), decimals=XRP_DECIMALS)


def parse_issued_value(
    value: Any,
    *,
    field: str = "value",
    max_decimals: int = ISSUED_MAX_DECIMALS,
) -> tuple[int, int]:
    """Parse an issued currency value into ``(base_units, decimals)``.

    XRPL issued amounts are decimal strings. We keep exact scale up to
    *max_decimals* fractional digits (ROUND_DOWN beyond that) so the
    projection is deterministic and free of binary floats.
    """

    if isinstance(value, bool):
        raise NormalizationError(f"{field} must not be a boolean")
    if isinstance(value, float):
        raise InvalidRequestError(
            f"{field} must not be a binary float; use a decimal string"
        )
    if isinstance(value, int):
        if value < 0:
            raise NormalizationError(f"{field} must not be negative")
        return value, 0
    if not isinstance(value, str):
        raise NormalizationError(f"{field} must be a decimal string or int")
    text = value.strip()
    if not text:
        raise NormalizationError(f"{field} must not be empty")
    try:
        dec = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise NormalizationError(f"{field} is not a valid decimal") from exc
    if dec.is_nan() or dec.is_infinite():
        raise NormalizationError(f"{field} must be a finite decimal")
    if dec < 0:
        raise NormalizationError(f"{field} must not be negative")

    sign, digits, exponent = dec.as_tuple()
    if sign != 0:
        raise NormalizationError(f"{field} must not be negative")
    if exponent >= 0:
        # Integer value with trailing zeros in scientific form.
        base = int(dec)
        return base, 0
    scale = -int(exponent)
    if scale > max_decimals:
        quant = Decimal(10) ** -max_decimals
        dec = dec.quantize(quant, rounding=ROUND_DOWN)
        scale = max_decimals
    base = int(dec * (Decimal(10) ** scale))
    return base, scale


def exact_issued(
    value: Any,
    *,
    field: str = "value",
    max_decimals: int = ISSUED_MAX_DECIMALS,
) -> ExactAmount:
    """Return an :class:`ExactAmount` for an issued currency value string."""

    base, decimals = parse_issued_value(
        value, field=field, max_decimals=max_decimals
    )
    return ExactAmount.from_int(base, decimals=decimals)


def require_no_float_amount(value: Any, *, field: str = "amount") -> None:
    if isinstance(value, float):
        raise InvalidRequestError(
            f"{field} must not be a binary float; use integer drops or a decimal string"
        )


__all__ = [
    "exact_drops",
    "exact_issued",
    "parse_drops",
    "parse_issued_value",
    "require_no_float_amount",
]
