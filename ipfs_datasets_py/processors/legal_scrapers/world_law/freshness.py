"""Decide whether a justicedao export still matches the raw scrape.

endomorphosis holds the raw scrape. A new law changes that dataset's SHA.
justicedao holds the normalized tree built from one raw SHA. Retrieval reads
justicedao and does not read the raw org. When the two SHAs differ, the
export is stale and must be normalized again before it is treated as current.
"""

from __future__ import annotations

import re
from typing import Mapping

_SHA = re.compile(r"^[0-9a-f]{40}$")


def export_freshness(
    *,
    raw_revision: object,
    exported_source_revision: object,
) -> dict[str, object]:
    """Compare the current raw SHA with the SHA recorded on the export.

    ``current`` means the justicedao manifest was built from this raw scrape.
    ``stale`` means the scraper has a newer SHA, so the export needs another
    normalize. ``missing`` means there is no export SHA yet. ``unproven``
    means the raw SHA itself is not a 40-hex revision, so this check must
    not start a normalize.
    """

    raw = _sha(raw_revision)
    exported = _sha(exported_source_revision)
    if raw is None:
        status = "unproven"
        renormalize = False
    elif exported is None:
        status = "missing"
        renormalize = True
    elif raw == exported:
        status = "current"
        renormalize = False
    else:
        status = "stale"
        renormalize = True
    return {
        "status": status,
        "raw_org": "endomorphosis",
        "retrieve_from": "justicedao",
        "raw_revision": raw,
        "exported_source_revision": exported,
        "renormalize": renormalize,
    }


def exported_source_revision(manifest: Mapping[str, object] | None) -> str | None:
    """Raw SHA recorded by a legal-record/v1 manifest or an older IR manifest."""

    if not isinstance(manifest, Mapping):
        return None
    source = manifest.get("source")
    nested = source.get("source_revision") if isinstance(source, Mapping) else None
    for candidate in (
        manifest.get("source_revision"),
        manifest.get("dataset_revision"),
        nested,
    ):
        sha = _sha(candidate)
        if sha is not None:
            return sha
    return None


def freshness_from_manifest(
    manifest: Mapping[str, object] | None,
    raw_revision: object,
) -> dict[str, object]:
    """Freshness of one local or Hub manifest against the raw scrape SHA."""

    return export_freshness(
        raw_revision=raw_revision,
        exported_source_revision=exported_source_revision(manifest),
    )


def _sha(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if _SHA.fullmatch(text) is None:
        return None
    return text
