"""Geography checker: validates that a citation's state matches the GNIS record."""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def check_geography(citation: dict, reference_db) -> Optional[str]:
    """Validate that the place name and state in the citation match the GNIS reference data.

    Args:
        citation: Citation dict.  Must contain ``gnis`` and
            ``bluebook_state_code`` fields.
        reference_db: An open database connection whose ``locations`` table
            has a ``state_code`` column keyed by ``gnis``.

    Returns:
        ``None`` when the geography is valid; an error string otherwise.
    """
    gnis = citation.get("gnis")
    # Bug #21 fix: use 'bluebook_state_code', NOT 'state'
    cited_state = citation.get("bluebook_state_code")

    if gnis is None or cited_state is None:
        return "Missing gnis or bluebook_state_code in citation"

    try:
        # Parameterized query — never interpolate user data into SQL strings
        result = reference_db.execute(
            "SELECT state_code FROM locations WHERE gnis = ?", [int(gnis)]
        ).fetchone()
    except Exception as exc:
        logger.error("Database error during geography check for gnis %s: %s", gnis, exc)
        return f"Database error checking geography for gnis {gnis}: {exc}"

    if result is None:
        return f"GNIS {gnis} not found in reference database"

    actual_state = result[0]
    if str(cited_state).strip().lower() != str(actual_state).strip().lower():
        return (
            f"State mismatch for gnis {gnis}: "
            f"citation says '{cited_state}', reference says '{actual_state}'"
        )

    return None  # valid
