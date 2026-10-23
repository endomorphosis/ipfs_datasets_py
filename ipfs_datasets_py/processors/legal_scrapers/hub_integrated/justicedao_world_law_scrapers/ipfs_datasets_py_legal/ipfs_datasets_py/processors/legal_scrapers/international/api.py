"""Unified legal scrape API across native US/NL scrapers and harvested gazette collectors."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Optional

from .catalog import (
    get_snapshot_corpus,
    list_snapshot_corpora,
    snapshot_catalog_summary,
)
from .harvest import (
    harvest_all_dataset_collectors,
    harvest_catalog_collectors,
    harvest_dataset_collectors,
    harvest_legal_scrapers_repo,
    harvest_result_to_dict,
    missing_catalog_collectors,
)
from .helpers.paths import corpora_root
from .runtime import PACKAGE_HARVESTED_ROOT, run_harvested_collector

NATIVE_SOURCES: dict[str, dict[str, Any]] = {
    "us": {"kind": "native_family", "handler": "us", "aliases": ("united_states", "usa")},
    "federal": {"kind": "native", "handler": "federal", "aliases": ("federal_laws", "federal_register")},
    "us_code": {"kind": "native", "handler": "us_code", "aliases": ("usc", "united_states_code")},
    "state": {"kind": "native", "handler": "state", "aliases": ("state_laws",)},
    "state_admin": {"kind": "native", "handler": "state_admin", "aliases": ("state_admin_rules",)},
    "municipal": {"kind": "native", "handler": "municipal", "aliases": ("municipal_laws", "municipal_codes")},
    "recap": {"kind": "native", "handler": "recap", "aliases": ("pacer", "courtlistener")},
    "netherlands": {"kind": "native", "handler": "netherlands", "aliases": ("nl", "netherlands_laws", "bwbr")},
}


@dataclass(frozen=True)
class LegalSource:
    key: str
    kind: str
    handler: str
    display_name: str
    country_code: str
    dataset_id: Optional[str] = None
    collector: Optional[str] = None
    quality: Optional[str] = None
    aliases: tuple[str, ...] = ()


def _normalize(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_").replace("/", "_")


def _native_index() -> dict[str, LegalSource]:
    index: dict[str, LegalSource] = {}
    labels = {
        "us": ("United States", "US"),
        "federal": ("United States Federal Laws", "US"),
        "us_code": ("United States Code", "US"),
        "state": ("United States State Laws", "US"),
        "state_admin": ("United States State Administrative Rules", "US"),
        "municipal": ("United States Municipal Laws", "US"),
        "recap": ("RECAP / PACER court documents", "US"),
        "netherlands": ("Netherlands", "NL"),
    }
    for key, spec in NATIVE_SOURCES.items():
        display, country = labels[key]
        source = LegalSource(
            key=key,
            kind=str(spec["kind"]),
            handler=str(spec["handler"]),
            display_name=display,
            country_code=country,
            quality="production",
            aliases=tuple(spec.get("aliases") or ()),
        )
        index[_normalize(key)] = source
        for alias in source.aliases:
            index.setdefault(_normalize(alias), source)
        index.setdefault(_normalize(country) if key != "netherlands" else "us" if country == "US" else _normalize(country), source)
    # Keep NL native preferred over snapshot when key is nl/netherlands.
    return index


def resolve_legal_source(key: str) -> LegalSource:
    normalized = _normalize(key)
    native = _native_index()
    if normalized in native:
        return native[normalized]
    from ipfs_datasets_py.processors.legal_scrapers.regions.mapping import REGION_DISPLAY_NAMES, REGION_IDS

    if normalized in REGION_IDS:
        display = REGION_DISPLAY_NAMES[normalized]
        return LegalSource(
            key=normalized,
            kind="region_family",
            handler="region",
            display_name=display,
            country_code="",
            quality="production",
            aliases=(),
        )
    try:
        entry = get_snapshot_corpus(key)
    except KeyError as exc:
        available = ", ".join(sorted(set(native))[:20])
        raise KeyError(f"Unknown legal source {key!r}. Native examples: {available}.") from exc
    return LegalSource(
        key=entry.key,
        kind="snapshot",
        handler="harvested",
        display_name=entry.display_name,
        country_code=entry.country_code,
        dataset_id=entry.source_dataset_id,
        collector=entry.collector,
        quality=entry.quality,
        aliases=entry.aliases(),
    )


def list_legal_sources(*, include_snapshots: bool = True) -> list[LegalSource]:
    sources = []
    seen: set[str] = set()
    for source in _native_index().values():
        if source.key in seen:
            continue
        seen.add(source.key)
        sources.append(source)
    if include_snapshots:
        for entry in list_snapshot_corpora(include_aliases=False):
            if entry.core_corpus_key == "netherlands_laws":
                continue
            if entry.key in seen:
                continue
            seen.add(entry.key)
            sources.append(
                LegalSource(
                    key=entry.key,
                    kind="snapshot",
                    handler="harvested",
                    display_name=entry.display_name,
                    country_code=entry.country_code,
                    dataset_id=entry.source_dataset_id,
                    collector=entry.collector,
                    quality=entry.quality,
                    aliases=entry.aliases(),
                )
            )
    return sources


def load_published_snapshot(
    key: str,
    *,
    dest_dir: Path | str | None = None,
    download: bool = True,
) -> dict[str, Any]:
    try:
        entry = get_snapshot_corpus(key)
        dataset_id = entry.source_dataset_id
        country_code = entry.country_code
        quality = entry.quality
    except KeyError as exc:
        source = resolve_legal_source(key)
        if source.kind != "snapshot" or not source.dataset_id:
            raise KeyError(f"{key} does not have a parked endomorphosis snapshot") from exc
        dataset_id = source.dataset_id
        country_code = source.country_code
        quality = source.quality
    dest = Path(dest_dir).expanduser().resolve() if dest_dir else (corpora_root() / country_code.lower() / "hf_snapshot")
    dest.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    if download:
        try:
            from huggingface_hub import hf_hub_download
        except ImportError as exc:
            raise RuntimeError("huggingface_hub is required to download published snapshots") from exc
        for name in ("data/laws.parquet", "data/articles.parquet", "README.md", "MANIFEST.md"):
            try:
                local = hf_hub_download(
                    repo_id=dataset_id,
                    filename=name,
                    repo_type="dataset",
                    local_dir=str(dest),
                )
                files[name] = str(local)
            except Exception:
                continue
    return {
        "status": "snapshot",
        "jurisdiction": country_code,
        "dataset_id": dataset_id,
        "output_dir": str(dest),
        "files": files,
        "quality": quality,
        "not_legal_advice": True,
    }


async def _call_native(handler: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api as api

    dispatch: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {
        "federal": api.scrape_federal_laws_from_parameters,
        "us_code": api.scrape_us_code_from_parameters,
        "state": api.scrape_state_laws_from_parameters,
        "state_admin": api.scrape_state_admin_rules_from_parameters,
        "municipal": api.scrape_municipal_codes_from_parameters,
        "recap": api.scrape_recap_archive_from_parameters,
        "netherlands": api.scrape_netherlands_laws_from_parameters,
    }
    if handler == "us":
        return {
            "status": "error",
            "error": "US is a family of scrapers. Use us_code, federal, state, municipal, or recap.",
            "data": [],
        }
    func = dispatch.get(handler)
    if func is None:
        return {"status": "error", "error": f"No native scraper handler {handler}", "data": []}
    return await func(dict(parameters))


def scrape_legal_data(
    jurisdiction: str,
    *,
    mode: str = "snapshot",
    output_dir: Path | str | None = None,
    collectors_dir: Path | str | None = None,
    parameters: Optional[Mapping[str, Any]] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Scrape or load legal data for one jurisdiction.

    Modes:
    - ``snapshot``: download the parked Hugging Face parquet snapshot
    - ``collect``: run the harvested official-gazette collector
    - ``resume``: resume a harvested collector
    - ``native``: force the in-repo US/Netherlands scrapers
    - ``inspect``: describe the source without fetching
    """

    source = resolve_legal_source(jurisdiction)
    params = dict(parameters or {})
    if output_dir is not None:
        params.setdefault("output_dir", str(output_dir))
    normalized_mode = str(mode or "snapshot").strip().lower()
    if normalized_mode == "inspect":
        payload = {
            "status": "success",
            "mode": "inspect",
            "source": asdict(source),
            "not_legal_advice": True,
        }
        if source.kind == "region_family":
            from ipfs_datasets_py.processors.legal_scrapers.regions import get_region

            payload["region"] = get_region(source.key).summary()
            payload["sources"] = get_region(source.key).sources()
        return payload
    if source.kind == "region_family":
        from ipfs_datasets_py.processors.legal_scrapers.regions import get_region

        region = get_region(source.key)
        return {
            "status": "success",
            "mode": normalized_mode,
            "source": asdict(source),
            "region": region.summary(),
            "sources": region.sources(),
            "note": f"Choose a country in {region.display_name} (for example {region.sources()[0]['slug'] if region.sources() else 'n/a'}).",
            "not_legal_advice": True,
        }
    if normalized_mode != "native" and source.handler == "netherlands" and normalized_mode == "snapshot":
        if dry_run:
            return {
                "status": "dry_run",
                "mode": "snapshot",
                "source": asdict(source),
                "dataset_id": "endomorphosis/ipfs_netherlands_laws",
                "not_legal_advice": True,
            }
        snapshot = load_published_snapshot("netherlands", dest_dir=output_dir, download=True)
        snapshot["native_pipeline"] = "justicedao/ipfs_netherlands_laws"
        return snapshot

    if source.kind.startswith("native") or normalized_mode == "native":
        import anyio

        return anyio.run(_call_native, source.handler, params)

    if normalized_mode == "snapshot":
        if dry_run:
            return {
                "status": "dry_run",
                "mode": "snapshot",
                "source": asdict(source),
                "output_dir": str(output_dir or corpora_root() / source.country_code.lower() / "hf_snapshot"),
                "not_legal_advice": True,
            }
        return load_published_snapshot(jurisdiction, dest_dir=output_dir, download=True)

    if normalized_mode in {"collect", "resume"}:
        result = run_harvested_collector(
            jurisdiction,
            output_dir=output_dir,
            collectors_dir=collectors_dir,
            argv=["--resume"] if normalized_mode == "resume" else list(params.get("argv") or []),
            dry_run=dry_run,
            sync_huggingface=bool(params.get("sync_huggingface", True)),
            force_resync=bool(params.get("force_resync", False)),
        )
        payload = asdict(result)
        payload["mode"] = normalized_mode
        payload["source"] = asdict(source)
        payload["not_legal_advice"] = True
        return payload

    if normalized_mode in {"sync", "sync-state", "sync_state"}:
        from .scrape_state import sync_published_scrape_state

        if dry_run:
            from .scrape_state import load_published_scrape_state

            cached = load_published_scrape_state(source.country_code, corpora_dir=output_dir)
            return {
                "status": "dry_run",
                "mode": "sync",
                "source": asdict(source),
                "huggingface_scrape_state": None if cached is None else cached.to_dict(),
                "not_legal_advice": True,
            }
        state = sync_published_scrape_state(
            jurisdiction,
            corpora_dir=output_dir,
            force=bool(params.get("force_resync", False)),
            download=True,
        )
        payload = state.to_dict()
        payload["status"] = "ok" if not state.error else "error"
        payload["mode"] = "sync"
        payload["source"] = asdict(source)
        payload["not_legal_advice"] = True
        return payload

    raise ValueError(f"Unknown scrape mode {mode!r}")


def harvest_legal_collectors(
    *,
    jurisdiction: Optional[str] = None,
    dest_root: Path | str | None = None,
    include_legal_scrapers: bool = True,
    limit: Optional[int] = None,
    missing_only: bool = True,
    max_workers: int = 8,
) -> dict[str, Any]:
    dest = Path(dest_root).expanduser().resolve() if dest_root else PACKAGE_HARVESTED_ROOT
    if jurisdiction:
        source = resolve_legal_source(jurisdiction)
        if source.kind.startswith("native"):
            return {"status": "skipped", "reason": "native scraper, no HF collector harvest required", "source": asdict(source)}
        if not source.dataset_id:
            raise KeyError(f"No dataset id for {jurisdiction}")
        result = harvest_dataset_collectors(source.dataset_id, dest_root=dest, skip_existing=True)
        if include_legal_scrapers and not (dest / "legal_scrapers" / "scrapers").is_dir():
            base = harvest_legal_scrapers_repo(dest_root=dest)
            result.files.extend(base.files)
            result.errors.extend(base.errors)
        payload = harvest_result_to_dict(result)
        payload["status"] = "ok" if result.failure_count == 0 else "partial"
        payload["missing_collectors"] = missing_catalog_collectors(dest_root=dest)
        return payload
    entries = [
        {
            "slug": entry.slug,
            "collector": entry.collector,
            "source_dataset_id": entry.source_dataset_id,
        }
        for entry in list_snapshot_corpora(include_aliases=False)
    ]
    if limit is not None:
        entries = entries[: max(0, int(limit))]
    if include_legal_scrapers and not (dest / "legal_scrapers" / "scrapers").is_dir():
        base = harvest_legal_scrapers_repo(dest_root=dest)
    else:
        from .harvest import HarvestResult

        base = HarvestResult(collectors_root=str(dest), corpora_root=str(corpora_root()))
    part = harvest_all_dataset_collectors(
        entries,
        dest_root=dest,
        skip_existing=True,
        missing_only=missing_only,
        max_workers=max_workers,
    )
    part.files[0:0] = list(base.files)
    part.errors[0:0] = list(base.errors)
    result = part
    payload = harvest_result_to_dict(result)
    payload["status"] = "ok" if result.failure_count == 0 else "partial"
    payload["catalog"] = snapshot_catalog_summary()
    payload["missing_collectors"] = missing_catalog_collectors(dest_root=dest)
    return payload


def get_jurisdiction_wrapper(key: str):
    source = resolve_legal_source(key)
    if source.handler == "netherlands":
        from ipfs_datasets_py.processors.legal_scrapers.legal_corpus import get_jurisdiction

        return get_jurisdiction("netherlands")
    from .adapters import SnapshotLegalCorpusJurisdiction
    from .catalog import get_snapshot_corpus

    return SnapshotLegalCorpusJurisdiction(get_snapshot_corpus(key))


__all__ = [
    "LegalSource",
    "NATIVE_SOURCES",
    "get_jurisdiction_wrapper",
    "harvest_legal_collectors",
    "list_legal_sources",
    "load_published_snapshot",
    "resolve_legal_source",
    "scrape_legal_data",
    "snapshot_catalog_summary",
]
