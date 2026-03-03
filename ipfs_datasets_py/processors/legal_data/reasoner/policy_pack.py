"""Policy Pack schema definition and validator.

A policy pack is a bundle of policies applied to legal reasoning.
Schema version: 1.0
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


POLICY_PACK_SCHEMA_VERSION = "1.0"


POLICY_PACK_ERROR_CODES: Dict[str, str] = {
    "missing_jurisdiction": "PP_ERR_MISSING_JURISDICTION",
    "missing_effective_date": "PP_ERR_MISSING_EFFECTIVE_DATE",
    "missing_priority_policy": "PP_ERR_MISSING_PRIORITY_POLICY",
    "missing_exception_policy": "PP_ERR_MISSING_EXCEPTION_POLICY",
    "missing_temporal_policy": "PP_ERR_MISSING_TEMPORAL_POLICY",
    "invalid_effective_date_format": "PP_ERR_INVALID_EFFECTIVE_DATE_FORMAT",
    "invalid_priority_policy_type": "PP_ERR_INVALID_PRIORITY_POLICY_TYPE",
    "invalid_exception_policy_type": "PP_ERR_INVALID_EXCEPTION_POLICY_TYPE",
    "invalid_temporal_policy_type": "PP_ERR_INVALID_TEMPORAL_POLICY_TYPE",
}


class PolicyPackValidationError(ValueError):
    """Raised when a policy pack fails validation in strict mode."""

    def __init__(self, message: str, errors: List[str], error_codes: List[str]) -> None:
        super().__init__(message)
        self.errors = errors
        self.error_codes = error_codes


@dataclass
class PolicyPack:
    """A validated bundle of policies applied to legal reasoning."""

    jurisdiction: str
    effective_date: str
    priority_policy: dict
    exception_policy: dict
    temporal_policy: dict
    schema_version: str = POLICY_PACK_SCHEMA_VERSION
    pack_id: Optional[str] = None
    attrs: dict = field(default_factory=dict)


def validate_policy_pack(pack_data: dict, *, strict: bool = True) -> Dict[str, Any]:
    """Validate a policy pack dict.

    Args:
        pack_data: Raw dict representing the policy pack.
        strict: If True, raise PolicyPackValidationError on any error.

    Returns:
        Validation result with keys ``valid``, ``schema_version``,
        ``errors``, and ``error_codes``.

    Raises:
        PolicyPackValidationError: If strict=True and validation fails.
    """
    errors: List[str] = []
    error_codes: List[str] = []

    def _add_error(key: str, message: str) -> None:
        errors.append(message)
        error_codes.append(POLICY_PACK_ERROR_CODES[key])

    # Required string field: jurisdiction
    if not pack_data.get("jurisdiction"):
        _add_error("missing_jurisdiction", "Missing required field: jurisdiction")

    # Required string field: effective_date
    effective_date = pack_data.get("effective_date")
    if not effective_date:
        _add_error("missing_effective_date", "Missing required field: effective_date")
    else:
        # Validate ISO-8601 date format (YYYY-MM-DD)
        try:
            datetime.strptime(effective_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            _add_error(
                "invalid_effective_date_format",
                f"Invalid effective_date format '{effective_date}'; expected YYYY-MM-DD",
            )

    # Required dict field: priority_policy
    if "priority_policy" not in pack_data or pack_data["priority_policy"] is None:
        _add_error("missing_priority_policy", "Missing required field: priority_policy")
    elif not isinstance(pack_data["priority_policy"], dict):
        _add_error(
            "invalid_priority_policy_type",
            "priority_policy must be a dict",
        )

    # Required dict field: exception_policy
    if "exception_policy" not in pack_data or pack_data["exception_policy"] is None:
        _add_error("missing_exception_policy", "Missing required field: exception_policy")
    elif not isinstance(pack_data["exception_policy"], dict):
        _add_error(
            "invalid_exception_policy_type",
            "exception_policy must be a dict",
        )

    # Required dict field: temporal_policy
    if "temporal_policy" not in pack_data or pack_data["temporal_policy"] is None:
        _add_error("missing_temporal_policy", "Missing required field: temporal_policy")
    elif not isinstance(pack_data["temporal_policy"], dict):
        _add_error(
            "invalid_temporal_policy_type",
            "temporal_policy must be a dict",
        )

    result: Dict[str, Any] = {
        "valid": len(errors) == 0,
        "schema_version": POLICY_PACK_SCHEMA_VERSION,
        "errors": errors,
        "error_codes": error_codes,
    }

    if strict and errors:
        raise PolicyPackValidationError(
            f"Policy pack validation failed: {errors}",
            errors=errors,
            error_codes=error_codes,
        )

    return result


def build_policy_pack(pack_data: dict) -> PolicyPack:
    """Validate and build a PolicyPack dataclass from a raw dict.

    Args:
        pack_data: Raw dict representing the policy pack.

    Returns:
        A validated PolicyPack instance.

    Raises:
        PolicyPackValidationError: If validation fails.
    """
    validate_policy_pack(pack_data, strict=True)
    return PolicyPack(
        jurisdiction=pack_data["jurisdiction"],
        effective_date=pack_data["effective_date"],
        priority_policy=pack_data["priority_policy"],
        exception_policy=pack_data["exception_policy"],
        temporal_policy=pack_data["temporal_policy"],
        schema_version=pack_data.get("schema_version", POLICY_PACK_SCHEMA_VERSION),
        pack_id=pack_data.get("pack_id"),
        attrs=pack_data.get("attrs", {}),
    )
