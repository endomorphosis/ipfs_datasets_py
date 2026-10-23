"""Incrementally package raw collector instruments into laws/articles parquet.

Collectors write one JSON instrument per official page under
``$LEGAL_CORPORA_ROOT/<iso>/instruments/*.json``. Those files grow as new
pages are scraped. This module merges them into the ``endomorphosis/ipfs_*_laws``
parquet schema without rewriting unchanged rows, so the GraphRAG builder can
delta-rebuild from the resulting pack.

Never invents legal text or identifiers. Empty/short bodies are dropped, not
filled.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .cidutil import sha256_file
from .schema import LAW_FIELD_MAP, REQUIRED_ARTICLE_COLUMNS, REQUIRED_LAW_COLUMNS

LAW_COLS = [
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
]
ART_COLS = [
    "law_id",
    "id",
    "title",
    "text",
    "source_url",
    "document_number",
    "article_number",
    "record_type",
    "metadata_json",
]

MIN_BODY_CHARS = 80
DEFAULT_CORPORA_ROOT = Path(
    os.environ.get(
        "LEGAL_CORPORA_ROOT",
        str(Path.home() / ".ipfs_datasets" / "legal-corpora"),
    )
)


def _s(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _meta_json(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value or {}, ensure_ascii=False)
    except Exception:
        return "{}"


def instruments_to_frames(
    instruments_dir: Path,
    *,
    min_body_chars: int = MIN_BODY_CHARS,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Read collector JSON instruments into laws/articles dataframes."""
    laws: list[dict[str, Any]] = []
    arts: list[dict[str, Any]] = []
    skipped_short = 0
    skipped_bad = 0
    root = Path(instruments_dir)
    files = sorted(root.glob("*.json")) if root.is_dir() else []
    for path in files:
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            skipped_bad += 1
            continue
        if not isinstance(rec, dict):
            skipped_bad += 1
            continue
        text = _s(rec.get("text"))
        ident = _s(rec.get("id"))
        title = _s(rec.get("title"))
        if not ident or not title or len(text) < min_body_chars:
            skipped_short += 1
            continue
        meta = rec.get("metadata") or {}
        laws.append(
            {
                "id": ident,
                "title": title,
                "text": text,
                "source_url": _s(rec.get("source_url")),
                "source_type": _s(rec.get("source_type")),
                "jurisdiction": _s(rec.get("jurisdiction")),
                "country": _s(rec.get("country")),
                "language": _s(rec.get("language")),
                "eli": _s(rec.get("eli")) or None,
                "date": _s(rec.get("date")) or None,
                "date_issued": _s(rec.get("date_issued") or rec.get("date")) or None,
                "retrieved_at": _s(rec.get("retrieved_at")) or None,
                "license": _s(rec.get("license")),
                "law_status": _s(rec.get("law_status")),
                "identifier": _s(rec.get("identifier")) or ident,
                "official_identifier": _s(rec.get("official_identifier")),
                "article_count": rec.get("article_count") or len(rec.get("documents") or []),
                "json_path": f"instruments/{path.name}",
                "metadata_json": _meta_json(meta),
            }
        )
        for doc in rec.get("documents") or []:
            if not isinstance(doc, dict):
                continue
            art_id = _s(doc.get("id"))
            art_title = _s(doc.get("title"))
            art_text = _s(doc.get("text"))
            if not art_id or not art_title or not art_text:
                continue
            arts.append(
                {
                    "law_id": ident,
                    "id": art_id,
                    "title": art_title,
                    "text": art_text,
                    "source_url": _s(doc.get("source_url")) or _s(rec.get("source_url")),
                    "document_number": _s(doc.get("document_number")),
                    "article_number": _s(doc.get("article_number")),
                    "record_type": _s(doc.get("record_type")) or "article",
                    "metadata_json": _meta_json(doc.get("metadata") or {}),
                }
            )
    report = {
        "n_instrument_files": len(files),
        "n_laws": len(laws),
        "n_articles": len(arts),
        "skipped_short_or_empty": skipped_short,
        "skipped_unreadable": skipped_bad,
        "min_body_chars": min_body_chars,
        "never_invented_legal_text": True,
        "required_law_columns": list(REQUIRED_LAW_COLUMNS),
        "required_article_columns": list(REQUIRED_ARTICLE_COLUMNS),
        "law_field_map": dict(LAW_FIELD_MAP),
    }
    return (
        pd.DataFrame(laws, columns=LAW_COLS),
        pd.DataFrame(arts, columns=ART_COLS),
        report,
    )


def _retrieved_key(value: Any) -> str:
    return _s(value)


def merge_laws(prior: pd.DataFrame | None, incoming: pd.DataFrame) -> pd.DataFrame:
    """Upsert laws by ``id``. Newer ``retrieved_at`` wins; otherwise incoming wins."""
    if prior is None or prior.empty:
        return incoming.copy() if incoming is not None else pd.DataFrame(columns=LAW_COLS)
    if incoming is None or incoming.empty:
        return prior.copy()
    by_id: dict[str, dict[str, Any]] = {}
    for frame, incoming_flag in ((prior, False), (incoming, True)):
        for rec in frame.to_dict(orient="records"):
            ident = _s(rec.get("id"))
            if not ident:
                continue
            existing = by_id.get(ident)
            if existing is None:
                by_id[ident] = rec
                continue
            if incoming_flag:
                new_ts = _retrieved_key(rec.get("retrieved_at"))
                old_ts = _retrieved_key(existing.get("retrieved_at"))
                if not old_ts or new_ts >= old_ts:
                    by_id[ident] = rec
    rows = [by_id[k] for k in sorted(by_id)]
    return pd.DataFrame(rows, columns=LAW_COLS)


def merge_articles(prior: pd.DataFrame | None, incoming: pd.DataFrame) -> pd.DataFrame:
    """Upsert articles by ``id``. Incoming replaces the same article id."""
    if prior is None or prior.empty:
        return incoming.copy() if incoming is not None else pd.DataFrame(columns=ART_COLS)
    if incoming is None or incoming.empty:
        return prior.copy()
    by_id: dict[str, dict[str, Any]] = {}
    for frame in (prior, incoming):
        for rec in frame.to_dict(orient="records"):
            ident = _s(rec.get("id"))
            if not ident:
                continue
            by_id[ident] = rec
    rows = [by_id[k] for k in sorted(by_id)]
    return pd.DataFrame(rows, columns=ART_COLS)


def load_existing_parquet(pack_dir: Path) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    pack_dir = Path(pack_dir)
    laws_path = None
    arts_path = None
    for cand in (pack_dir / "data" / "laws.parquet", pack_dir / "laws.parquet"):
        if cand.is_file():
            laws_path = cand
            break
    for cand in (pack_dir / "data" / "articles.parquet", pack_dir / "articles.parquet"):
        if cand.is_file():
            arts_path = cand
            break
    laws = pd.read_parquet(laws_path) if laws_path else None
    arts = pd.read_parquet(arts_path) if arts_path else None
    return laws, arts


def write_pack(
    out: Path,
    laws: pd.DataFrame,
    articles: pd.DataFrame,
    *,
    slug: str,
    source_dataset: str,
    name: str | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a local pack that ``load_source`` / ``get_country`` can consume."""
    out = Path(out)
    data_dir = out / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    laws_path = data_dir / "laws.parquet"
    arts_path = data_dir / "articles.parquet"
    laws.to_parquet(laws_path, index=False)
    articles.to_parquet(arts_path, index=False)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    meta = {
        "slug": slug,
        "repo": source_dataset,
        "source_dataset": source_dataset,
        "name": name or slug.replace("_", " ").title(),
        "indexable": True,
        "source_revision": f"local:{now}",
        "n_laws": int(len(laws)),
        "n_articles": int(len(articles)),
        "laws_sha256": sha256_file(laws_path),
        "articles_sha256": sha256_file(arts_path),
        "generated_at": now,
        "incremental": True,
    }
    if extra_meta:
        meta.update(extra_meta)
    (out / "pack_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return meta


def package_instruments(
    *,
    instruments_dir: Path,
    out: Path,
    slug: str,
    source_dataset: str | None = None,
    prior_pack: Path | None = None,
    name: str | None = None,
    min_body_chars: int = MIN_BODY_CHARS,
) -> dict[str, Any]:
    """Merge collector JSON (+ optional prior parquet) into a local IR source pack."""
    incoming_laws, incoming_arts, extract_report = instruments_to_frames(
        instruments_dir, min_body_chars=min_body_chars
    )
    prior_laws = prior_arts = None
    prior_dir = Path(prior_pack) if prior_pack else (out if out.exists() else None)
    if prior_dir is not None:
        prior_laws, prior_arts = load_existing_parquet(prior_dir)
    laws = merge_laws(prior_laws, incoming_laws)
    articles = merge_articles(prior_arts, incoming_arts)
    if laws.empty:
        raise RuntimeError(
            f"no laws with text>={min_body_chars} under {instruments_dir}"
        )
    repo = source_dataset or f"endomorphosis/ipfs_{slug}_laws"
    meta = write_pack(
        out,
        laws,
        articles,
        slug=slug,
        source_dataset=repo,
        name=name,
        extra_meta={"extract": extract_report},
    )
    meta["extract"] = extract_report
    meta["n_laws_prior"] = int(len(prior_laws)) if prior_laws is not None else 0
    meta["n_articles_prior"] = int(len(prior_arts)) if prior_arts is not None else 0
    meta["n_laws_incoming"] = int(len(incoming_laws))
    meta["n_articles_incoming"] = int(len(incoming_arts))
    meta["out"] = str(out)
    return meta


def default_instruments_dir(iso_or_slug: str, root: Path | None = None) -> Path:
    base = Path(root) if root is not None else DEFAULT_CORPORA_ROOT
    return base / iso_or_slug / "instruments"
