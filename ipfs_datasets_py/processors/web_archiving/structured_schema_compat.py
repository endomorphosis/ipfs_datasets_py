"""Structured field schema compatibility helpers.

This module provides a narrow normalization layer so downstream callers always
receive a stable v1-shaped payload, even when extraction logic evolves.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple


_SUPPORTED_DOMAINS = {"general", "legal", "finance", "medical"}
_DOMAIN_ALIASES = {
    "law": "legal",
    "laws": "legal",
    "financial": "finance",
    "fin": "finance",
    "health": "medical",
    "clinical": "medical",
}

_GENERAL_SCHEMA = "general_v1"
_LEGAL_SCHEMA = "legal_v1"
_FINANCE_SCHEMA = "finance_v1"
_MEDICAL_SCHEMA = "medical_v1"

_SCHEMA_BY_DOMAIN = {
    "general": _GENERAL_SCHEMA,
    "legal": _LEGAL_SCHEMA,
    "finance": _FINANCE_SCHEMA,
    "medical": _MEDICAL_SCHEMA,
}

_REQUIRED_KEYS_BY_SCHEMA = {
    _GENERAL_SCHEMA: {
        "schema",
        "section_headers",
        "dates",
        "legal_citations",
        "statute_identifiers",
        "monetary_amounts",
        "is_pdf_content",
    },
    _LEGAL_SCHEMA: {
        "schema",
        "section_headers",
        "dates",
        "legal_citations",
        "statute_identifiers",
        "monetary_amounts",
        "case_citations",
        "effective_dates",
        "parties",
        "is_pdf_content",
    },
    _FINANCE_SCHEMA: {
        "schema",
        "dates",
        "monetary_amounts",
        "percentages",
        "ticker_symbols",
        "accounting_terms",
        "is_pdf_content",
    },
    _MEDICAL_SCHEMA: {
        "schema",
        "dates",
        "diagnoses",
        "medications",
        "dosages",
        "procedures",
        "is_pdf_content",
    },
}

_DEFAULTS_BY_SCHEMA = {
    _GENERAL_SCHEMA: {
        "schema": _GENERAL_SCHEMA,
        "section_headers": [],
        "dates": [],
        "legal_citations": [],
        "statute_identifiers": [],
        "monetary_amounts": [],
        "is_pdf_content": False,
    },
    _LEGAL_SCHEMA: {
        "schema": _LEGAL_SCHEMA,
        "section_headers": [],
        "dates": [],
        "legal_citations": [],
        "statute_identifiers": [],
        "monetary_amounts": [],
        "case_citations": [],
        "effective_dates": [],
        "parties": [],
        "is_pdf_content": False,
    },
    _FINANCE_SCHEMA: {
        "schema": _FINANCE_SCHEMA,
        "dates": [],
        "monetary_amounts": [],
        "percentages": [],
        "ticker_symbols": [],
        "accounting_terms": [],
        "is_pdf_content": False,
    },
    _MEDICAL_SCHEMA: {
        "schema": _MEDICAL_SCHEMA,
        "dates": [],
        "diagnoses": [],
        "medications": [],
        "dosages": [],
        "procedures": [],
        "is_pdf_content": False,
    },
}


def normalize_domain(domain: str) -> str:
    """Normalize incoming domain strings to known values."""
    raw = (domain or "general").strip().lower()
    if raw in _DOMAIN_ALIASES:
        raw = _DOMAIN_ALIASES[raw]
    if raw not in _SUPPORTED_DOMAINS:
        return "general"
    return raw


def normalize_structured_fields(
    *,
    fields: Dict[str, Any],
    requested_domain: str,
    source_type: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Normalize structured fields to a stable v1 schema envelope.

    Returns:
        (normalized_fields, migration_meta)
    """
    normalized_domain = normalize_domain(requested_domain)
    expected_schema = _SCHEMA_BY_DOMAIN[normalized_domain]

    payload = dict(fields or {})
    source_schema = str(payload.get("schema") or "").strip().lower()
    source_schema = source_schema or expected_schema

    defaults = dict(_DEFAULTS_BY_SCHEMA[expected_schema])
    for key in defaults:
        if key in payload:
            defaults[key] = payload[key]

    # Keep a safe boolean for clients relying on this flag.
    defaults["is_pdf_content"] = bool(defaults.get("is_pdf_content") or source_type == "pdf")

    # Force contract schema to requested-domain version.
    defaults["schema"] = expected_schema

    migration_meta = {
        "requested_domain": normalized_domain,
        "expected_schema": expected_schema,
        "source_schema": source_schema,
        "schema_migration_applied": source_schema != expected_schema,
        "structured_fields_contract": "v1",
    }
    return defaults, migration_meta


def validate_structured_fields_contract(fields: Dict[str, Any]) -> bool:
    """Return True when payload keys exactly match a supported contract schema."""
    schema = str((fields or {}).get("schema") or "").strip().lower()
    required = _REQUIRED_KEYS_BY_SCHEMA.get(schema)
    if required is None:
        return False
    return set((fields or {}).keys()) == required


__all__ = [
    "normalize_domain",
    "normalize_structured_fields",
    "validate_structured_fields_contract",
]
