"""Republication review for one source row.

Writer drops and review findings are separate. A finding does not change
``export_norm`` filter counts. This module does not upload and does not read
a Hugging Face token.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, MutableSet

from ipfs_datasets_py.processors.legal_data.iso_slug_crosswalk import (
    html_country_code,
    resolve_jurisdiction,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.project_world_v11_row import (
    drop_reason,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.schema import WORLD_V11_COLUMNS
from ipfs_datasets_py.processors.legal_scrapers.world_law.textutil import (
    calendar_date,
    null_text,
)

HTML_MUNICIPAL_COLUMNS: tuple[str, ...] = (
    "cid",
    "jurisdiction_id",
    "jurisdiction_name",
    "country",
    "doc_id",
    "regeling_id",
    "regeling_work_id",
    "doc_order",
    "title",
    "structural_path",
    "node_label",
    "html_title",
    "html",
    "text",
    "source_url",
    "xml_url",
    "date_effective",
    "date_modified",
    "retrieved",
)

AMERICAN_COLUMNS: tuple[str, ...] = (
    "cid",
    "doc_id",
    "doc_order",
    "html_title",
    "html",
)

_FAMILIES = frozenset({
    "world-national",
    "world-municipal",
    "html-municipal-19",
    "american-5",
})

_COLUMNS = {
    "world-national": WORLD_V11_COLUMNS,
    "world-municipal": WORLD_V11_COLUMNS,
    "html-municipal-19": HTML_MUNICIPAL_COLUMNS,
    "american-5": AMERICAN_COLUMNS,
}

_ADMIN_LEVEL = {
    "world-national": "country",
    "world-municipal": "municipality",
    "html-municipal-19": "municipality",
    "american-5": "us-municipal",
}

_FINDING_ORDER = (
    "schema_invalid",
    "unresolved_country_code",
    "license_note_missing",
    "language_missing",
    "temporal_missing",
    "duplicate_identity",
)


@dataclass(frozen=True)
class ReviewDecision:
    safe_to_copy: bool
    writer_drop_reason: str | None
    findings: tuple[str, ...]
    admin_level: str


def review_row(
    row: Mapping[str, object],
    *,
    family: str,
    seen: MutableSet[tuple[str, ...]] | None = None,
) -> ReviewDecision:
    """Review one row. ``seen`` records identities already reviewed.

    The second row with the same identity gets ``duplicate_identity``. The
    writer does not dedupe, so that finding leaves ``safe_to_copy`` unchanged.
    """

    if family not in _FAMILIES:
        raise ValueError(f"unknown review family: {family}")
    found: set[str] = set()
    if set(row) != set(_COLUMNS[family]):
        found.add("schema_invalid")
    if family in {"world-national", "world-municipal"}:
        code = row.get("country_code")
        token = code if isinstance(code, str) else ""
        if resolve_jurisdiction(token) is None:
            found.add("unresolved_country_code")
        if null_text(row.get("license_note")) is None:
            found.add("license_note_missing")
        if null_text(row.get("language")) is None:
            found.add("language_missing")
        if null_text(row.get("published_date")) is None and null_text(row.get("effective_date")) is None:
            found.add("temporal_missing")
        reason = drop_reason(row, drop_us=True)
        safe = reason is None
    elif family == "html-municipal-19":
        reason = None if html_country_code(row.get("country")) is not None else "unknown_country"
        found.add("license_note_missing")
        if null_text(row.get("language")) is None:
            found.add("language_missing")
        if calendar_date(row.get("date_effective")) is None:
            found.add("temporal_missing")
        safe = reason is None
    else:
        reason = None
        found.add("license_note_missing")
        found.add("language_missing")
        found.add("temporal_missing")
        safe = "schema_invalid" not in found
    if seen is not None:
        identity = _identity(row, family)
        if identity in seen:
            found.add("duplicate_identity")
        else:
            seen.add(identity)
    findings = tuple(name for name in _FINDING_ORDER if name in found)
    return ReviewDecision(
        safe_to_copy=safe,
        writer_drop_reason=reason,
        findings=findings,
        admin_level=_ADMIN_LEVEL[family],
    )


def _identity(row: Mapping[str, object], family: str) -> tuple[str, ...]:
    if family in {"world-national", "world-municipal"}:
        keys = ("country_code", "cid", "doc_id", "doc_order")
    elif family == "html-municipal-19":
        keys = ("country", "cid", "doc_id", "doc_order")
    else:
        keys = ("cid", "doc_id", "doc_order")
    return tuple("" if row.get(key) is None else str(row.get(key)) for key in keys)
