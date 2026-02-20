"""Code-type checker: validates Municipal / County Code type against GNIS class_code."""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Bug #22 fix: use class_code values (C1-C7, H1/H4-H6, C8), NOT feature_class strings.
_MUNICIPAL_CLASS_CODES: frozenset[str] = frozenset({"C1", "C2", "C3", "C4", "C5", "C6", "C7"})
_COUNTY_CLASS_CODES: frozenset[str] = frozenset({"H1", "H4", "H5", "H6"})
_CONSOLIDATED_CLASS_CODES: frozenset[str] = frozenset({"C8"})


def check_code_type(citation: dict, reference_db) -> Optional[str]:
    """Validate that the citation's code type (Municipal/County/City Code) matches the GNIS class_code.

    Per the Bluebook PRD:
    - ``C1``–``C7``  → Municipal Code
    - ``H1``, ``H4``–``H6`` → County Code
    - ``C8``         → consolidated city (accepts either Municipal or County Code)

    Args:
        citation: Citation dict.  Must contain ``gnis`` and ``code_type`` fields.
        reference_db: An open database connection whose ``locations`` table has a
            ``class_code`` column keyed by ``gnis``.

    Returns:
        ``None`` when the code type is valid; an error string otherwise.
    """
    gnis = citation.get("gnis")
    cited_code_type = citation.get("code_type") or citation.get("bluebook_code_type")

    if gnis is None or not cited_code_type:
        return "Missing gnis or code_type in citation"

    try:
        result = reference_db.execute(
            "SELECT class_code FROM locations WHERE gnis = ?", [int(gnis)]
        ).fetchone()
    except Exception as exc:
        logger.error("Database error during code-type check for gnis %s: %s", gnis, exc)
        return f"Database error checking code type for gnis {gnis}: {exc}"

    if result is None:
        return f"GNIS {gnis} not found in reference database"

    class_code: str = str(result[0]).strip()
    cited_code_type = cited_code_type.strip()

    if class_code in _MUNICIPAL_CLASS_CODES:
        expected = "Municipal Code"
    elif class_code in _COUNTY_CLASS_CODES:
        expected = "County Code"
    elif class_code in _CONSOLIDATED_CLASS_CODES:
        # Consolidated city-counties are valid as either type.
        if cited_code_type in ("Municipal Code", "County Code", "City Code"):
            return None
        return (
            f"Code type '{cited_code_type}' not valid for consolidated city "
            f"(class_code={class_code}); expected 'Municipal Code' or 'County Code'"
        )
    else:
        return f"Unknown class_code '{class_code}' for gnis {gnis}"

    if cited_code_type != expected:
        return (
            f"Code type mismatch for gnis {gnis} (class_code={class_code}): "
            f"citation says '{cited_code_type}', should be '{expected}'"
        )

    return None  # valid
