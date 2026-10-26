"""Project one world-law v1.1.0 row into legal-record/v1.

Rows with an archived or non-official source policy are dropped. A missing
``source_policy`` is not a drop. ``html`` is never copied into ``text``.
"""

from __future__ import annotations

from typing import Mapping

from ipfs_datasets_py.processors.legal_scrapers.world_law.document_role import (
    classify_document_role,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.schema import (
    WORLD_V11_COLUMNS,
    _DROP_POLICIES,
    _INSTRUMENTS,
    blank_record,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.textutil import (
    null_text,
    sha256_text,
    strip_markup,
)


def drop_reason(row: Mapping[str, object], *, drop_us: bool = False) -> str | None:
    policy = row.get("source_policy")
    if isinstance(policy, str) and policy in _DROP_POLICIES:
        return policy
    if row.get("source_official") is False:
        return "source_official_false"
    if drop_us and str(row.get("country_code") or "").upper() == "US":
        return "us_omitted"
    return None


def project_world_v11_row(
    row: Mapping[str, object],
    *,
    source_repo: str,
    source_revision: str,
    drop_us: bool = False,
    admin_level: str = "country",
) -> dict[str, object] | None:
    reason = drop_reason(row, drop_us=drop_us)
    if reason is not None:
        return None
    record = blank_record()
    provenance = record["provenance"]
    assert isinstance(provenance, dict)
    complete = row.get("content_complete") is not False and null_text(row.get("text")) is not None
    text = null_text(row.get("text")) if complete else None
    doc_type = null_text(row.get("doc_type")) or "statute"
    if doc_type not in _INSTRUMENTS:
        doc_type = "statute"
    title = strip_markup(row.get("title_native")) or strip_markup(row.get("html_title"))
    record.update(
        {
            "jurisdiction": null_text(row.get("country_code")),
            "admin_level": admin_level,
            "instrument_type": doc_type,
            "citation": null_text(row.get("number")) or null_text(row.get("official_citation")),
            "bluebook_citation": None,
            "title": title,
            "text": text,
            "language": null_text(row.get("language")),
            "published_date": null_text(row.get("published_date")),
            "effective_date": null_text(row.get("effective_date")),
            "authority": null_text(row.get("source_org")) or null_text(row.get("source_platform")),
            "source_url": null_text(row.get("source_url")) or null_text(row.get("original_url")),
            "content_sha256": sha256_text(text),
            "scraper_id": None,
            "normalizer_version": "world-law/v1.1.0+legal-record/v1",
            "source_repo": source_repo,
            "source_revision": source_revision,
            "entry_cid": null_text(row.get("cid")),
        }
    )
    for field in (
        "archive_source",
        "archive_crawl_id",
        "archive_timestamp",
        "archive_url",
        "license_note",
        "possibly_stale",
        "source_policy",
        "source_official",
        "in_force",
        "consolidated",
    ):
        provenance[field] = row.get(field)
    provenance["content_complete"] = bool(complete and text is not None)
    role, reason = classify_document_role(
        {
            "title": record.get("title"),
            "text": record.get("text"),
            "source_url": record.get("source_url"),
            "language": record.get("language"),
            "instrument_type": record.get("instrument_type"),
            "doc_type": row.get("doc_type"),
        }
    )
    provenance["document_role"] = role
    provenance["document_role_reason"] = reason
    if set(WORLD_V11_COLUMNS) and "html" in record:
        raise RuntimeError("world projector must not emit html")
    return record
