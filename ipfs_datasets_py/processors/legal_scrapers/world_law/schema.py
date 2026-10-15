"""Column contracts. The 34 world columns live only in this module."""

from __future__ import annotations

WORLD_V11_COLUMNS: tuple[str, ...] = (
    "cid",
    "doc_id",
    "doc_order",
    "html_title",
    "html",
    "place_id",
    "country_code",
    "gnis",
    "source_platform",
    "source_url",
    "doc_type",
    "language",
    "title_native",
    "number",
    "adopted_date",
    "published_date",
    "effective_date",
    "in_force",
    "consolidated",
    "content_format",
    "text",
    "retrieved_at",
    "archive_source",
    "archive_crawl_id",
    "archive_timestamp",
    "archive_url",
    "original_url",
    "content_complete",
    "possibly_stale",
    "source_policy",
    "source_official",
    "source_org",
    "license_note",
    "extra_metadata",
)

LEGAL_RECORD_FIELDS: tuple[str, ...] = (
    "jurisdiction",
    "admin_level",
    "instrument_type",
    "citation",
    "bluebook_citation",
    "title",
    "text",
    "language",
    "published_date",
    "effective_date",
    "authority",
    "source_url",
    "content_sha256",
    "scraper_id",
    "normalizer_version",
    "source_repo",
    "source_revision",
    "entry_cid",
    "provenance",
)

PROVENANCE_FIELDS: tuple[str, ...] = (
    "archive_source",
    "archive_crawl_id",
    "archive_timestamp",
    "archive_url",
    "license_note",
    "content_complete",
    "possibly_stale",
    "source_policy",
    "source_official",
    "in_force",
    "consolidated",
    "coverage",
)

_INSTRUMENTS = frozenset({
    "statute",
    "regulation",
    "gazette_act",
    "ordinance",
    "code_section",
    "decision",
    "case",
    "register",
    "patent",
})

_DROP_POLICIES = frozenset({
    "archived_robots_disallowed",
    "noarchive_meta",
    "noindex_meta",
    "robots_unreachable",
})


def blank_record() -> dict[str, object]:
    record: dict[str, object] = {field: None for field in LEGAL_RECORD_FIELDS}
    record["provenance"] = {field: None for field in PROVENANCE_FIELDS}
    return record
