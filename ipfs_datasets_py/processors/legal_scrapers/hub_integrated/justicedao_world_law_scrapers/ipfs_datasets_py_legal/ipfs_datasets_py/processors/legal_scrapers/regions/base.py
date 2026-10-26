"""Shared regional gazette class used by Americas, Europe, MENA, Africa, Asia-Pacific."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from .mapping import REGION_DISPLAY_NAMES, countries_for_region, normalize_region_id


@dataclass(frozen=True)
class LegalRegion:
    """One geographic class of official-gazette collectors."""

    region_id: str
    display_name: str
    aliases: tuple[str, ...] = ()

    def country_codes(self) -> tuple[str, ...]:
        return tuple(sorted(countries_for_region(self.region_id)))

    def corpora(self, *, include_aliases: bool = False):
        from ipfs_datasets_py.processors.legal_scrapers.international.catalog import list_snapshot_corpora

        allowed = set(self.country_codes())
        return [
            entry
            for entry in list_snapshot_corpora(include_aliases=include_aliases)
            if entry.country_code in allowed
        ]

    def get(self, key: str):
        from ipfs_datasets_py.processors.legal_scrapers.international.catalog import get_snapshot_corpus

        entry = get_snapshot_corpus(key)
        if entry.country_code not in set(self.country_codes()):
            raise KeyError(f"{key!r} is not in the {self.display_name} region")
        return entry

    def contains(self, key: str) -> bool:
        try:
            self.get(key)
            return True
        except KeyError:
            return False

    def sources(self) -> list[dict[str, Any]]:
        return [
            {
                "key": entry.key,
                "slug": entry.canonical_slug,
                "country_code": entry.country_code,
                "display_name": entry.display_name,
                "collector": entry.collector,
                "dataset_id": entry.source_dataset_id,
                "quality": entry.quality,
                "region": self.region_id,
            }
            for entry in self.corpora(include_aliases=False)
        ]

    def summary(self) -> dict[str, Any]:
        entries = self.corpora(include_aliases=False)
        by_quality: dict[str, int] = {}
        for entry in entries:
            by_quality[entry.quality] = by_quality.get(entry.quality, 0) + 1
        return {
            "region_id": self.region_id,
            "display_name": self.display_name,
            "country_codes": list(self.country_codes()),
            "corpus_count": len(entries),
            "by_quality": dict(sorted(by_quality.items())),
            "not_legal_advice": True,
        }

    def scrape(
        self,
        jurisdiction: str,
        *,
        mode: str = "snapshot",
        output_dir: Path | str | None = None,
        dry_run: bool = False,
        parameters: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        entry = self.get(jurisdiction)
        from ipfs_datasets_py.processors.legal_scrapers.international.api import scrape_legal_data

        return scrape_legal_data(
            entry.canonical_slug,
            mode=mode,
            output_dir=output_dir,
            dry_run=dry_run,
            parameters=parameters,
        )

    def harvest(self, jurisdiction: Optional[str] = None, **kwargs: Any) -> dict[str, Any]:
        from ipfs_datasets_py.processors.legal_scrapers.international.api import harvest_legal_collectors

        if jurisdiction:
            entry = self.get(jurisdiction)
            return harvest_legal_collectors(jurisdiction=entry.canonical_slug, **kwargs)
        payload = harvest_legal_collectors(jurisdiction=None, missing_only=True, **kwargs)
        allowed = {entry.source_dataset_id for entry in self.corpora(include_aliases=False)}
        missing = [
            item
            for item in list(payload.get("missing_collectors") or [])
            if item.get("source_dataset_id") in allowed
        ]
        payload["region_id"] = self.region_id
        payload["missing_collectors"] = missing
        return payload

    def sync(self, jurisdiction: str, **kwargs: Any) -> dict[str, Any]:
        return self.scrape(jurisdiction, mode="sync", **kwargs)


def region_from_id(region_id: str) -> LegalRegion:
    normalized = normalize_region_id(region_id)
    display = REGION_DISPLAY_NAMES.get(normalized)
    if not display:
        raise KeyError(f"Unknown legal scraper region: {region_id}")
    return LegalRegion(region_id=normalized, display_name=display)


__all__ = ["LegalRegion", "region_from_id"]
