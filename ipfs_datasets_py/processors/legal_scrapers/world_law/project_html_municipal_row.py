"""Project a 19-column HTML municipal scraper row into legal-record/v1.

This function does not call the 34-column world projector and does not parse
``html`` into ``text``. A missing ``source_policy`` keeps the row.
"""

from __future__ import annotations

from typing import Mapping

from ipfs_datasets_py.processors.legal_data.iso_slug_crosswalk import html_country_code
from ipfs_datasets_py.processors.legal_scrapers.world_law.schema import (
    _INSTRUMENTS,
    blank_record,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.textutil import (
    calendar_date,
    null_text,
    sha256_text,
    strip_markup,
)

_PROVENANCE_ONLY = (
    "doc_id",
    "regeling_id",
    "regeling_work_id",
    "jurisdiction_id",
    "structural_path",
    "node_label",
    "doc_order",
    "xml_url",
    "date_modified",
    "retrieved",
    "tipo",
)


def project_html_municipal_row(
    row: Mapping[str, object],
    *,
    source_repo: str,
    source_revision: str,
) -> dict[str, object] | None:
    country = html_country_code(row.get("country"))
    if country is None:
        return None
    record = blank_record()
    provenance = record["provenance"]
    assert isinstance(provenance, dict)
    text = null_text(row.get("text"))
    title = _title(row.get("title"), row.get("html_title"))
    tipo = null_text(row.get("tipo"))
    instrument = "ordinance"
    if tipo is not None and tipo in _INSTRUMENTS:
        instrument = tipo
    record.update(
        {
            "jurisdiction": country,
            "admin_level": "municipality",
            "instrument_type": instrument,
            "citation": None,
            "bluebook_citation": None,
            "title": title,
            "text": text,
            "language": null_text(row.get("language")),
            "published_date": None,
            "effective_date": calendar_date(row.get("date_effective")),
            "authority": null_text(row.get("jurisdiction_name")),
            "source_url": null_text(row.get("source_url")),
            "content_sha256": sha256_text(text),
            "scraper_id": None,
            "normalizer_version": "html-municipal-scraper/v1+legal-record/v1",
            "source_repo": source_repo,
            "source_revision": source_revision,
            "entry_cid": null_text(row.get("cid")),
        }
    )
    provenance["content_complete"] = text is not None
    provenance["source_policy"] = None
    provenance["source_official"] = None
    for key in _PROVENANCE_ONLY:
        provenance[key] = row.get(key)
    text_value = record["text"]
    html_value = row.get("html")
    copied = (
        isinstance(text_value, str)
        and isinstance(html_value, str)
        and text_value == html_value
    )
    if "html" in record or copied:
        raise RuntimeError("html must not be copied into a legal record")
    return record


def _title(title: object, html_title: object) -> str | None:
    raw = null_text(title)
    if raw is not None and "<" not in raw:
        cleaned = strip_markup(raw)
        if cleaned is not None:
            return cleaned
    return strip_markup(html_title)
