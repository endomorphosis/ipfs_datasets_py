"""Catalog of parked endomorphosis official-gazette snapshots and collectors."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Iterable, Optional

_DATA_DIR = Path(__file__).resolve().parent / "data"
_CATALOG_PATH = _DATA_DIR / "snapshot_catalog.json"
_INVENTORY_PATH = _DATA_DIR / "collector_inventory.json"


@dataclass(frozen=True)
class SnapshotCorpus:
    slug: str
    canonical_slug: str
    country_code: str
    display_name: str
    language: str
    collector: str
    source_dataset_id: str
    ir_dataset_id: str
    branch: str
    quality: str
    core_corpus_key: Optional[str] = None
    alias_of: Optional[str] = None

    @property
    def key(self) -> str:
        return f"{self.canonical_slug}_laws"

    @property
    def is_alias(self) -> bool:
        return bool(self.alias_of)

    @property
    def region(self) -> str:
        from ipfs_datasets_py.processors.legal_scrapers.regions.mapping import region_for_country

        return region_for_country(self.country_code)

    def aliases(self) -> tuple[str, ...]:
        values = {
            self.slug,
            self.canonical_slug,
            self.country_code,
            self.key,
            self.display_name,
            self.source_dataset_id,
            self.ir_dataset_id,
            f"ipfs_{self.slug}_laws",
            f"ipfs_{self.canonical_slug}_laws",
        }
        return tuple(sorted({_normalize_key(value) for value in values if str(value).strip()}))


def _normalize_key(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_").replace("/", "_")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_snapshot_catalog() -> tuple[SnapshotCorpus, ...]:
    payload = _load_json(_CATALOG_PATH)
    entries = []
    for item in payload.get("entries") or []:
        entries.append(
            SnapshotCorpus(
                slug=str(item.get("slug") or ""),
                canonical_slug=str(item.get("canonical_slug") or item.get("slug") or ""),
                country_code=str(item.get("country_code") or "").upper(),
                display_name=str(item.get("display_name") or ""),
                language=str(item.get("language") or "en"),
                collector=str(item.get("collector") or ""),
                source_dataset_id=str(item.get("source_dataset_id") or ""),
                ir_dataset_id=str(item.get("ir_dataset_id") or ""),
                branch=str(item.get("branch") or "international"),
                quality=str(item.get("quality") or "snapshot"),
                core_corpus_key=str(item.get("core_corpus_key") or "") or None,
                alias_of=str(item.get("alias_of") or "") or None,
            )
        )
    return tuple(entries)


@lru_cache(maxsize=1)
def load_collector_inventory() -> dict[str, Any]:
    if not _INVENTORY_PATH.is_file():
        return {}
    return _load_json(_INVENTORY_PATH)


def list_snapshot_corpora(*, include_aliases: bool = True) -> list[SnapshotCorpus]:
    entries = list(load_snapshot_catalog())
    if include_aliases:
        return entries
    return [entry for entry in entries if not entry.is_alias]


def get_snapshot_corpus(key: str) -> SnapshotCorpus:
    normalized = _normalize_key(key)
    if not normalized:
        raise KeyError("Unknown snapshot corpus: ")
    canonical: dict[str, SnapshotCorpus] = {}
    for entry in load_snapshot_catalog():
        if entry.is_alias:
            continue
        canonical[entry.canonical_slug] = entry
        for alias in entry.aliases():
            canonical.setdefault(alias, entry)
    for entry in load_snapshot_catalog():
        if not entry.is_alias:
            continue
        target = canonical.get(entry.canonical_slug)
        if target is None:
            continue
        for alias in entry.aliases():
            canonical.setdefault(alias, target)
        canonical.setdefault(_normalize_key(entry.slug), target)
    if normalized not in canonical:
        raise KeyError(f"Unknown snapshot corpus: {key}")
    return canonical[normalized]


def infer_snapshot_corpus_for_dataset_id(dataset_id: str) -> SnapshotCorpus:
    normalized = str(dataset_id or "").strip().lower()
    if not normalized:
        raise KeyError("Unknown snapshot corpus dataset id: ")
    for entry in load_snapshot_catalog():
        source = entry.source_dataset_id.lower()
        ir = entry.ir_dataset_id.lower()
        if normalized == source or normalized.startswith(f"{source}_") or normalized.startswith(f"{source}-"):
            return get_snapshot_corpus(entry.canonical_slug)
        if normalized == ir or normalized.startswith(f"{ir}_") or normalized.startswith(f"{ir}-"):
            return get_snapshot_corpus(entry.canonical_slug)
        slug = entry.slug
        if normalized.endswith(f"/ipfs_{slug}_laws") or f"/ipfs_{slug}_laws_" in normalized or f"/ipfs_{slug}_laws-" in normalized:
            return get_snapshot_corpus(entry.canonical_slug)
    raise KeyError(f"Unknown snapshot corpus dataset id: {dataset_id}")


def snapshot_catalog_summary() -> dict[str, Any]:
    entries = list_snapshot_corpora(include_aliases=True)
    canonical = list_snapshot_corpora(include_aliases=False)
    by_quality: dict[str, int] = {}
    by_branch: dict[str, int] = {}
    by_region: dict[str, int] = {}
    for entry in canonical:
        by_quality[entry.quality] = by_quality.get(entry.quality, 0) + 1
        by_branch[entry.branch] = by_branch.get(entry.branch, 0) + 1
        by_region[entry.region] = by_region.get(entry.region, 0) + 1
    inventory = load_collector_inventory()
    return {
        "dataset_count": len(entries),
        "canonical_count": len(canonical),
        "collector_count": len(inventory.get("collectors") or []),
        "by_quality": dict(sorted(by_quality.items())),
        "by_branch": dict(sorted(by_branch.items())),
        "by_region": dict(sorted(by_region.items())),
        "source_repo": inventory.get("source_repo") or LEGAL_SCRAPERS_REPO_FALLBACK,
    }


def list_snapshot_corpora_by_region(region_id: str, *, include_aliases: bool = False) -> list[SnapshotCorpus]:
    from ipfs_datasets_py.processors.legal_scrapers.regions.mapping import countries_for_region

    allowed = countries_for_region(region_id)
    return [
        entry
        for entry in list_snapshot_corpora(include_aliases=include_aliases)
        if entry.country_code in allowed
    ]


LEGAL_SCRAPERS_REPO_FALLBACK = "endomorphosis/legal_scrapers"


def snapshot_corpus_to_dict(entry: SnapshotCorpus) -> dict[str, Any]:
    payload = asdict(entry)
    payload["key"] = entry.key
    payload["aliases"] = list(entry.aliases())
    return payload


def iter_collectors(entries: Optional[Iterable[SnapshotCorpus]] = None) -> list[str]:
    values: list[str] = []
    for entry in entries or list_snapshot_corpora(include_aliases=False):
        name = str(entry.collector or "").strip()
        if name and name not in values:
            values.append(name)
    return values


__all__ = [
    "SnapshotCorpus",
    "get_snapshot_corpus",
    "infer_snapshot_corpus_for_dataset_id",
    "iter_collectors",
    "list_snapshot_corpora",
    "load_collector_inventory",
    "load_snapshot_catalog",
    "snapshot_catalog_summary",
    "snapshot_corpus_to_dict",
]
