"""Run harvested collectors against a parameterized corpora root."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import runpy
import sys
from typing import Any, Mapping, Optional

from .catalog import SnapshotCorpus, get_snapshot_corpus
from .helpers.paths import collectors_root, corpora_root
from .harvest import rewrite_sandbox_source


LAW_FIELDS = (
    "id",
    "title",
    "text",
    "source_url",
    "source_type",
    "jurisdiction",
    "country",
    "language",
    "eli",
    "date",
    "date_issued",
    "retrieved_at",
    "license",
    "law_status",
    "identifier",
    "official_identifier",
    "article_count",
    "json_path",
    "metadata_json",
)

ARTICLE_FIELDS = (
    "law_id",
    "id",
    "title",
    "text",
    "source_url",
    "document_number",
    "article_number",
    "record_type",
    "metadata_json",
)


@dataclass(frozen=True)
class CollectorRunResult:
    country_code: str
    slug: str
    collector: str
    status: str
    output_dir: str
    law_count: int = 0
    article_count: int = 0
    error: Optional[str] = None
    details: Mapping[str, Any] | None = None


PACKAGE_HARVESTED_ROOT = Path(__file__).resolve().parent / "harvested"


def collector_path_for(entry: SnapshotCorpus, *, dest_root: Path | None = None) -> Path:
    roots = [collectors_root(dest_root)]
    if dest_root is None and PACKAGE_HARVESTED_ROOT not in roots:
        roots.append(PACKAGE_HARVESTED_ROOT)
    for root in roots:
        for candidate in (
            root / "shared" / entry.collector,
            root / "datasets" / entry.source_dataset_id.replace("/", "__") / "scrapers" / entry.collector,
            root / "legal_scrapers" / "scrapers" / entry.collector,
        ):
            if candidate.is_file():
                return candidate
    return roots[0] / "shared" / entry.collector


def load_instrument_records(country_code: str, *, output_dir: Path | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = Path(output_dir).expanduser().resolve() if output_dir else corpora_root()
    instruments = root / country_code.lower() / "instruments"
    laws: list[dict[str, Any]] = []
    articles: list[dict[str, Any]] = []
    if not instruments.is_dir():
        return laws, articles
    for path in sorted(instruments.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(record, dict):
            continue
        docs = list(record.get("documents") or [])
        law_row = {field: record.get(field) for field in LAW_FIELDS if field not in {"json_path", "metadata_json", "article_count"}}
        law_row["json_path"] = str(path)
        law_row["article_count"] = record.get("article_count") if record.get("article_count") is not None else len(docs)
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        law_row["metadata_json"] = json.dumps(metadata, ensure_ascii=False)
        laws.append(law_row)
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            articles.append(
                {
                    "law_id": record.get("id"),
                    "id": doc.get("id"),
                    "title": doc.get("title"),
                    "text": doc.get("text") or "",
                    "source_url": doc.get("source_url") or record.get("source_url"),
                    "document_number": doc.get("document_number"),
                    "article_number": doc.get("article_number"),
                    "record_type": doc.get("record_type") or "article",
                    "metadata_json": json.dumps(doc.get("metadata") or {}, ensure_ascii=False),
                }
            )
    return laws, articles


def _prepare_env(corpora: Path, collectors: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["IPFS_DATASETS_LEGAL_CORPORA_ROOT"] = str(corpora)
    env["IPFS_DATASETS_LEGAL_COLLECTORS_ROOT"] = str(collectors)
    return env


def run_harvested_collector(
    key: str,
    *,
    output_dir: Path | str | None = None,
    collectors_dir: Path | str | None = None,
    argv: Optional[list[str]] = None,
    dry_run: bool = False,
    sync_huggingface: bool = True,
    force_resync: bool = False,
) -> CollectorRunResult:
    entry = get_snapshot_corpus(key)
    corpora = corpora_root(output_dir)
    collectors = collectors_root(collectors_dir)
    path = collector_path_for(entry, dest_root=collectors)
    hf_state: dict[str, Any] = {}
    if sync_huggingface:
        from .scrape_state import load_skip_keys, sync_published_scrape_state

        state = sync_published_scrape_state(
            entry.canonical_slug,
            corpora_dir=corpora,
            force=force_resync,
            download=not dry_run,
        )
        hf_state = state.to_dict()
        hf_state["skip_key_count"] = state.skip_key_count or len(
            load_skip_keys(entry.country_code, corpora_dir=corpora)
        )
        if state.error:
            hf_state["error"] = state.error
    if dry_run:
        return CollectorRunResult(
            country_code=entry.country_code,
            slug=entry.canonical_slug,
            collector=entry.collector,
            status="dry_run",
            output_dir=str(corpora / entry.country_code.lower()),
            details={
                "collector_path": str(path),
                "exists": path.is_file(),
                "huggingface_scrape_state": hf_state,
            },
        )
    if not path.is_file():
        return CollectorRunResult(
            country_code=entry.country_code,
            slug=entry.canonical_slug,
            collector=entry.collector,
            status="missing_collector",
            output_dir=str(corpora / entry.country_code.lower()),
            error=f"Collector {entry.collector} has not been harvested to {path}",
        )
    source = rewrite_sandbox_source(path.read_text(encoding="utf-8"))
    module_name = f"ipfs_datasets_harvested_{path.stem}"
    spec = importlib.util.spec_from_loader(module_name, loader=None)
    if spec is None:
        raise RuntimeError(f"Unable to load collector {path}")
    module = importlib.util.module_from_spec(spec)
    env = _prepare_env(corpora, collectors)
    old_env = dict(os.environ)
    old_argv = list(sys.argv)
    shared_dirs = [
        PACKAGE_HARVESTED_ROOT / "shared",
        collectors / "shared",
        path.parent,
    ]
    inserted: list[str] = []
    for shared in shared_dirs:
        if shared.is_dir():
            sys.path.insert(0, str(shared))
            inserted.append(str(shared))
    try:
        os.environ.clear()
        os.environ.update(env)
        sys.argv = [str(path), *(argv or [])]
        exec(compile(source, str(path), "exec"), module.__dict__)
        if argv is None and hasattr(module, "main") and callable(module.main):
            module.main()
        elif argv is not None:
            runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if int(getattr(exc, "code", 0) or 0) not in {0, None}:
            laws, articles = load_instrument_records(entry.country_code, output_dir=corpora)
            return CollectorRunResult(
                country_code=entry.country_code,
                slug=entry.canonical_slug,
                collector=entry.collector,
                status="error",
                output_dir=str(corpora / entry.country_code.lower()),
                law_count=len(laws),
                article_count=len(articles),
                error=str(exc),
            )
    except Exception as exc:
        return CollectorRunResult(
            country_code=entry.country_code,
            slug=entry.canonical_slug,
            collector=entry.collector,
            status="error",
            output_dir=str(corpora / entry.country_code.lower()),
            error=str(exc),
        )
    finally:
        os.environ.clear()
        os.environ.update(old_env)
        sys.argv = old_argv
        for item in inserted:
            if item in sys.path:
                sys.path.remove(item)
    laws, articles = load_instrument_records(entry.country_code, output_dir=corpora)
    return CollectorRunResult(
        country_code=entry.country_code,
        slug=entry.canonical_slug,
        collector=entry.collector,
        status="ok",
        output_dir=str(corpora / entry.country_code.lower()),
        law_count=len(laws),
        article_count=len(articles),
        details={"huggingface_scrape_state": hf_state} if hf_state else None,
    )


__all__ = [
    "ARTICLE_FIELDS",
    "CollectorRunResult",
    "LAW_FIELDS",
    "PACKAGE_HARVESTED_ROOT",
    "collector_path_for",
    "load_instrument_records",
    "run_harvested_collector",
]
