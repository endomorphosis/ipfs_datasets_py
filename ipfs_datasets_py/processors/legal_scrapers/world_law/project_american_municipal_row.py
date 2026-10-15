"""Project the 5-column American municipal frame into legal-record/v1.

``text`` is always null and ``content_complete`` is always false. ``html`` is
not copied into ``text`` or into the returned record.
"""

from __future__ import annotations

from typing import Mapping

from ipfs_datasets_py.processors.legal_scrapers.world_law.schema import blank_record
from ipfs_datasets_py.processors.legal_scrapers.world_law.textutil import (
    null_text,
    strip_markup,
)


def project_american_municipal_row(
    row: Mapping[str, object],
    *,
    source_repo: str,
    source_revision: str,
) -> dict[str, object]:
    record = blank_record()
    provenance = record["provenance"]
    assert isinstance(provenance, dict)
    record.update(
        {
            "jurisdiction": "US",
            "admin_level": "us-municipal",
            "instrument_type": "ordinance",
            "title": strip_markup(row.get("html_title")),
            "text": None,
            "authority": None,
            "content_sha256": None,
            "normalizer_version": "american-municipal-html/v1+legal-record/v1",
            "source_repo": source_repo,
            "source_revision": source_revision,
            "entry_cid": null_text(row.get("cid")),
        }
    )
    provenance["content_complete"] = False
    provenance["source_policy"] = None
    provenance["source_official"] = None
    provenance["doc_id"] = row.get("doc_id")
    provenance["doc_order"] = row.get("doc_order")
    return record
