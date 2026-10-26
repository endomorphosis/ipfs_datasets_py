"""Normalize endomorphosis/ipfs_*_laws into a CID-keyed canonical corpus.

Prefer article/section as the retrieval unit; fall back to law-level when
articles are missing or empty. Strip leftover HTML, then detect multilingual
title/chapter/article/section headings (Oregon-style) when present. Never
invent legal text or a hierarchy that is not in the source.

Public Hub reads only (token=False). No Hugging Face token is read or stored.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
from huggingface_hub import dataset_info, hf_hub_download
from huggingface_hub.errors import EntryNotFoundError

from . import ENTRY_IDENTITY_SCHEMA, LAW_IDENTITY_SCHEMA, SCHEMA_VERSION
from .auth import configure_hf, public_token
from .cidutil import cid_of_json, sha256_file, sha256_hex
from .schema import SchemaError, validate_articles, validate_laws
from .reconstruct import (
    article_sort_key,
    parent_needs_reconstruct,
    reconstruct_on,
    reconstruct_parent,
)
from .structure import normalize_legal_text, split_structured_units

COLLECTOR_DEFAULT = "endomorphosis/ipfs_datasets_py"
EMPTY_ARTICLE_COLUMNS = (
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


def _empty_articles() -> pd.DataFrame:
    return pd.DataFrame(columns=list(EMPTY_ARTICLE_COLUMNS))


def normalize_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return normalize_legal_text(value)


def _s(value: Any) -> str:
    return normalize_text(value)


def _download(repo_id: str, filename: str, cache_dir: Path) -> Path:
    configure_hf()
    path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        repo_type="dataset",
        token=public_token(),
        cache_dir=str(cache_dir / "hf"),
    )
    return Path(path)


def _repo_filenames(info: Any) -> set[str]:
    return {str(getattr(s, "rfilename", "") or "") for s in (getattr(info, "siblings", None) or [])}


def _pick_repo_file(filenames: set[str], name: str) -> str | None:
    for cand in (f"data/{name}.parquet", f"{name}.parquet"):
        if cand in filenames:
            return cand
    return None


def _resolve_local_parquet(root: Path, name: str, *, required: bool = True) -> Path | None:
    """Accept either <root>/data/<name>.parquet or <root>/<name>.parquet."""
    for cand in (root / "data" / f"{name}.parquet", root / f"{name}.parquet"):
        if cand.is_file():
            return cand
    if required:
        raise FileNotFoundError(f"missing {name}.parquet under {root} (tried data/ and root)")
    return None


def load_local_source(local_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Load a local country-laws pack (filtered preprocess layout)."""
    local_dir = Path(local_dir).resolve()
    laws_path = _resolve_local_parquet(local_dir, "laws")
    articles_path = _resolve_local_parquet(local_dir, "articles", required=False)
    laws = pd.read_parquet(laws_path)
    articles = pd.read_parquet(articles_path) if articles_path is not None else _empty_articles()
    validate_laws(laws)
    validate_articles(articles)
    pack_meta: dict[str, Any] = {}
    meta_path = local_dir / "pack_meta.json"
    if meta_path.is_file():
        try:
            pack_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pack_meta = {}
    source_dataset = (
        pack_meta.get("source_dataset")
        or pack_meta.get("repo")
        or f"local/{local_dir.name}"
    )
    source_revision = str(
        pack_meta.get("source_revision")
        or pack_meta.get("revision")
        or f"local:{local_dir.name}"
    )
    meta = {
        "source_dataset": source_dataset,
        "source_revision": source_revision,
        "laws_path": str(laws_path),
        "articles_path": str(articles_path) if articles_path is not None else None,
        "laws_sha256": sha256_file(laws_path),
        "articles_sha256": sha256_file(articles_path) if articles_path is not None else None,
        "n_laws_source": int(len(laws)),
        "n_articles_source": int(len(articles)),
        "laws_columns": list(map(str, laws.columns)),
        "articles_columns": list(map(str, articles.columns)),
        "article_count_dtype": str(laws["article_count"].dtype) if "article_count" in laws.columns else None,
        "schema_surprises": _schema_surprises(laws, articles),
        "local_source_dir": str(local_dir),
        "pack_meta": pack_meta,
    }
    return laws, articles, meta


def load_source(repo_id: str, cache_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Load Hub dataset id OR a local directory with laws/articles parquet."""
    local = Path(repo_id)
    if local.is_dir() and (
        (local / "data" / "laws.parquet").is_file() or (local / "laws.parquet").is_file()
    ):
        return load_local_source(local)

    configure_hf()
    os.environ.setdefault("HF_HOME", str(cache_dir / "hf"))
    info = dataset_info(repo_id, token=public_token())
    revision = info.sha
    filenames = _repo_filenames(info)
    laws_file = _pick_repo_file(filenames, "laws") or "data/laws.parquet"
    articles_file = _pick_repo_file(filenames, "articles")
    laws_path = _download(repo_id, laws_file, cache_dir)
    articles_path: Path | None = None
    if articles_file is not None:
        try:
            articles_path = _download(repo_id, articles_file, cache_dir)
        except EntryNotFoundError:
            articles_path = None
    laws = pd.read_parquet(laws_path)
    articles = pd.read_parquet(articles_path) if articles_path is not None else _empty_articles()
    validate_laws(laws)
    validate_articles(articles)
    meta = {
        "source_dataset": repo_id,
        "source_revision": revision,
        "laws_path": str(laws_path),
        "articles_path": str(articles_path) if articles_path is not None else None,
        "laws_sha256": sha256_file(laws_path),
        "articles_sha256": sha256_file(articles_path) if articles_path is not None else None,
        "n_laws_source": int(len(laws)),
        "n_articles_source": int(len(articles)),
        "laws_columns": list(map(str, laws.columns)),
        "articles_columns": list(map(str, articles.columns)),
        "article_count_dtype": str(laws["article_count"].dtype) if "article_count" in laws.columns else None,
        "schema_surprises": _schema_surprises(laws, articles),
    }
    return laws, articles, meta


def _schema_surprises(laws: pd.DataFrame, articles: pd.DataFrame) -> list[str]:
    notes: list[str] = []
    if articles is None or articles.empty:
        notes.append("articles.parquet has 0 rows; corpus falls back to law-level units")
    if "article_count" in laws.columns:
        dtype = str(laws["article_count"].dtype)
        notes.append(f"laws.article_count dtype={dtype}")
        try:
            if int((laws["article_count"].fillna(0) == 0).sum()) == len(laws):
                notes.append("every law has article_count=0")
        except Exception:
            pass
    for col in ("date", "date_issued"):
        if col in laws.columns and laws[col].isna().all():
            notes.append(f"laws.{col} is entirely null")
    if "eli" in laws.columns:
        n_eli = int(laws["eli"].notna().sum()) if hasattr(laws["eli"], "notna") else 0
        notes.append(f"laws.eli non-null={n_eli}/{len(laws)}")
    if "language" in laws.columns:
        langs = sorted({str(x) for x in laws["language"].dropna().unique()})
        notes.append(f"laws.language values={langs}")
    return notes


def _parse_meta(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _law_cid(instrument_id: str, instrument_title: str, jurisdiction: str, language: str, source_dataset: str) -> str:
    identity = {
        "schema": LAW_IDENTITY_SCHEMA,
        "source_dataset": source_dataset,
        "instrument_id": instrument_id,
        "instrument_title": instrument_title,
        "jurisdiction": jurisdiction,
        "language": language,
    }
    return cid_of_json(identity)


def _entry_cid(record: dict[str, Any]) -> str:
    identity = {
        "schema": ENTRY_IDENTITY_SCHEMA,
        "record_type": record["record_type"],
        "source_dataset": record["source_dataset"],
        "instrument_id": record["instrument_id"],
        "article_number": record.get("article_number") or "",
        "article_title": record.get("article_title") or "",
        "body_sha256": record["body_sha256"],
        "language": record.get("language") or "",
        "jurisdiction": record.get("jurisdiction") or "",
        "source_url": record.get("source_url") or "",
    }
    return cid_of_json(identity)


def _row_get(row: pd.Series, col: str, default: str = "") -> str:
    if col not in row.index:
        return default
    return _s(row[col])


def _coverage_from(
    row: pd.Series,
    meta: dict[str, Any],
    articles_empty: bool,
    sparse_fallback: bool = False,
) -> str:
    for key in ("coverage", "coverage_note"):
        if key in meta and meta[key]:
            return normalize_text(meta[key])
    status = normalize_text(meta.get("article_extraction_status") or "")
    if sparse_fallback:
        note = "law-level (article coverage below 10% of laws; sparse articles table)"
        if status:
            return f"{note}; extraction_status={status}"
        return note
    if articles_empty:
        if status:
            return f"law-level (articles empty or unavailable in source snapshot); extraction_status={status}"
        return "law-level (articles empty or unavailable in source snapshot)"
    if status:
        return f"article-level; extraction_status={status}"
    return "article-level"


def _snapshot_date(row: pd.Series, meta: dict[str, Any], source_meta: dict[str, Any]) -> str:
    for col in ("retrieved_at", "date_issued", "date"):
        val = _row_get(row, col)
        if val:
            return val[:10] if len(val) >= 10 and val[4] == "-" else val
    for key in ("snapshot_date", "retrieved_at"):
        if key in meta and meta[key]:
            return normalize_text(str(meta[key]))[:10]
    nested = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    for key in ("snapshot_date", "retrieved_at"):
        if nested.get(key):
            return normalize_text(str(nested[key]))[:10]
    return ""


def _hierarchy_fields(
    title: str, body: str, article_number: str, *, language: str = ""
) -> dict[str, Any]:
    """Best-effort hierarchy from a single already-split article/section body."""
    units = split_structured_units(
        f"{title}\n{body}" if title else body, language=language
    )
    if not units:
        return {
            "hierarchy_kind": "article" if article_number else "law",
            "hierarchy_path": "",
            "title_number": "",
            "chapter_number": "",
            "part_number": "",
            "section_number": "",
            "subsections": [],
        }
    unit = units[0]
    return {
        "hierarchy_kind": unit.kind,
        "hierarchy_path": unit.hierarchy_path,
        "title_number": unit.title_number,
        "chapter_number": unit.chapter_number,
        "part_number": unit.part_number,
        "section_number": unit.section_number,
        "subsections": list(unit.subsections),
    }


def _compact_line(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def _is_title_shell(body: str, title: str) -> bool:
    """True when the article row is only its heading, repeated once."""
    folded_body = _compact_line(body)
    folded_title = _compact_line(title)
    if len(folded_title) < 24 or not folded_body:
        return False
    return folded_body == folded_title or folded_body == f"{folded_title} {folded_title}"


_NOTICE_RE = re.compile(
    r"(?i)(\bnewsletter\b|\bblog\b|press release|communiqu[eé]|"
    r"\bnews item\b|\bnotice board\b)"
)


def _instrument_record_type(metadata: dict[str, Any], title: str) -> str:
    """A normative instrument is a law, even when its title says Article.

    Newsletters, blogs, and press notices are not laws. A provision inside a
    law stays an article; this label is only for the instrument itself.
    """
    meta = metadata or {}
    document_type = str(meta.get("document_type") or "").strip().casefold()
    meta_type = str(meta.get("record_type") or "").strip().casefold()
    if _NOTICE_RE.search(title or "") or document_type in {
        "newsletter",
        "blog",
        "press",
        "press_release",
        "notice",
    }:
        return "notice"
    if document_type in {"gazette", "gazette_pdf"} and meta_type not in {
        "law",
        "statute",
        "constitution",
    }:
        return "notice"
    return "law"


def _unit_record_type(unit: Any, instrument_type: str, *, n_units: int, parent_body: str) -> str:
    """One unit that is the whole instrument keeps the instrument label."""
    if instrument_type == "notice":
        return "notice"
    if (
        n_units == 1
        and parent_body
        and len(getattr(unit, "body", "") or "") >= int(0.8 * len(parent_body))
    ):
        return "law"
    kind = getattr(unit, "kind", "") or ""
    if kind in {"article", "section"}:
        return kind
    return "article"


def _children_are_rich(kids: list[dict[str, Any]], parent_body: str) -> bool:
    """True when the article rows already carry the statute, not just headings."""
    if not kids:
        return False
    total = sum(len((kid.get("body") or "").strip()) for kid in kids)
    if total >= max(int(len(parent_body) * 0.5), 200):
        return True
    return any(
        len((kid.get("body") or "").strip()) >= 80
        and not _is_title_shell(kid.get("body") or "", kid.get("title") or "")
        for kid in kids
    )


def _needs_parent_split(kids: list[dict[str, Any]], parent_body: str) -> bool:
    """Split the parent when it holds the text and the article rows do not."""
    if len(parent_body) < 250 or len(parent_body) > 1_200_000:
        return False
    return not _children_are_rich(kids, parent_body)


def _expand_title_shell(parent: str, title: str, sibling_titles: set[str]) -> str | None:
    """Copy the parent span from this heading to the next sibling heading.

    The span is taken only from lines already in the parent. A short heading
    such as "Article 1" is left alone, because it matches too many lines.
    """
    key = _compact_line(title)
    peers = {item for item in sibling_titles if item and item != key and len(item) >= 24}
    if len(key) < 24 or not peers or not parent:
        return None
    lines = [ln.strip() for ln in parent.splitlines() if ln.strip()]
    compact = [_compact_line(ln) for ln in lines]
    best = ""
    for index, folded in enumerate(compact):
        if folded != key:
            continue
        chunk = [lines[index]]
        for later, later_folded in zip(lines[index + 1 :], compact[index + 1 :]):
            if later_folded in peers:
                break
            chunk.append(later)
        text = "\n".join(chunk).strip()
        if len(text) > len(best):
            best = text
    # The heading alone is not enough. Require a following sentence from the parent.
    if len(best) < len(key) + 40:
        return None
    return best


def _collector(meta: dict[str, Any], source_dataset: str) -> str:
    nested = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    for blob in (meta, nested):
        for key in ("collector", "collector_id", "harvester"):
            if blob.get(key):
                return normalize_text(blob[key])
    return f"{COLLECTOR_DEFAULT} ({source_dataset})"


def laws_index(laws: pd.DataFrame, source_dataset: str) -> dict[str, dict[str, Any]]:
    """Map instrument_id -> law facet fields (always computed; not always corpus units)."""
    out: dict[str, dict[str, Any]] = {}
    for _, row in laws.iterrows():
        instrument_id = _row_get(row, "id")
        instrument_title = _row_get(row, "title")
        jurisdiction = _row_get(row, "jurisdiction") or _row_get(row, "country")
        language = _row_get(row, "language")
        law_cid = _law_cid(instrument_id, instrument_title, jurisdiction, language, source_dataset)
        meta = _parse_meta(_row_get(row, "metadata_json"))
        out[instrument_id] = {
            "instrument_id": instrument_id,
            "instrument_title": instrument_title,
            "law_cid": law_cid,
            "jurisdiction": jurisdiction,
            "language": language,
            "source_url": _row_get(row, "source_url"),
            "license": _row_get(row, "license"),
            "eli": _row_get(row, "eli"),
            "identifier": _row_get(row, "identifier") or instrument_id,
            "official_identifier": _row_get(row, "official_identifier"),
            "source_type": _row_get(row, "source_type"),
            "country": _row_get(row, "country"),
            "law_status": _row_get(row, "law_status"),
            "body": _row_get(row, "text"),
            "metadata": meta,
            "row": row,
        }
    return out


def _base_record(
    *,
    record_type: str,
    source_dataset: str,
    source_revision: str,
    instrument_id: str,
    instrument_title: str,
    law_cid: str,
    article_number: str,
    article_title: str,
    body: str,
    jurisdiction: str,
    language: str,
    source_url: str,
    snapshot_date: str,
    coverage: str,
    license_expr: str,
    collector: str,
    source_id: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    title_for_bm25 = article_title if record_type == "article" and article_title else instrument_title
    rec: dict[str, Any] = {
        "record_type": record_type,
        "source_dataset": source_dataset,
        "source_revision": source_revision,
        "source_id": source_id,
        "instrument_id": instrument_id,
        "instrument_title": instrument_title,
        "law_id": instrument_id,
        "law_cid": law_cid,
        "article_number": article_number,
        "article_title": article_title,
        "title": title_for_bm25,
        "body": body,
        "body_sha256": sha256_hex(body.encode("utf-8")),
        "jurisdiction": jurisdiction,
        "language": language,
        "source_url": source_url,
        "snapshot_date": snapshot_date,
        "coverage": coverage,
        "license": license_expr,
        "collector": collector,
        "schema_version": SCHEMA_VERSION,
        "entry_identity_schema_version": ENTRY_IDENTITY_SCHEMA,
    }
    if extra:
        rec.update(extra)
    from .citations import assign_citation, citation_fields

    slug = ""
    if source_dataset.startswith("endomorphosis/ipfs_") and source_dataset.endswith("_laws"):
        slug = source_dataset.split("ipfs_", 1)[1].removesuffix("_laws")
    year = ""
    if snapshot_date and len(snapshot_date) >= 4 and snapshot_date[:4].isdigit():
        year = snapshot_date[:4]
    extra = extra or {}
    rec.update(
        citation_fields(
            assign_citation(
                eli=str(rec.get("eli") or extra.get("eli") or ""),
                official_identifier=str(
                    rec.get("official_identifier") or extra.get("official_identifier") or ""
                ),
                identifier=str(rec.get("identifier") or extra.get("identifier") or ""),
                instrument_title=instrument_title,
                article_number=article_number,
                section_number=str(extra.get("section_number") or ""),
                record_type=record_type,
                jurisdiction=jurisdiction,
                country=str(extra.get("country") or ""),
                slug=slug,
                year=year,
            )
        )
    )
    rec["entry_cid"] = _entry_cid(rec)
    rec["title_length"] = len(title_for_bm25)
    rec["body_length"] = len(body)
    rec["document_length"] = len(title_for_bm25) + len(body)
    return rec


def build_corpus(
    laws: pd.DataFrame,
    articles: pd.DataFrame,
    source_meta: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    source_dataset = source_meta["source_dataset"]
    source_revision = source_meta["source_revision"]
    law_map = laws_index(laws, source_dataset)
    articles_empty = articles is None or articles.empty
    n_laws = int(len(laws))
    n_arts = int(len(articles) if articles is not None else 0)
    article_law_coverage = (n_arts / n_laws) if n_laws else 0.0
    # Empty articles.parquet already falls back. Also fall back when the table is
    # present but covers under ~10% as many rows as laws (Estonia: 2 vs 3484).
    sparse_fallback = (not articles_empty) and article_law_coverage < 0.10
    use_articles = (not articles_empty) and not sparse_fallback

    extraction_statuses: Counter[str] = Counter()
    for parent in law_map.values():
        st = normalize_text(parent["metadata"].get("article_extraction_status") or "")
        if st:
            extraction_statuses[st] += 1

    report: dict[str, Any] = {
        "source_dataset": source_dataset,
        "source_revision": source_revision,
        "laws_sha256": source_meta.get("laws_sha256"),
        "articles_sha256": source_meta.get("articles_sha256"),
        "n_laws_in": int(len(laws)),
        "n_articles_in": int(len(articles) if articles is not None else 0),
        "unit": "article" if use_articles else "law",
        "article_law_coverage": article_law_coverage,
        "sparse_article_fallback": sparse_fallback,
        "drops": {
            "empty_body": 0,
            "missing_instrument": 0,
            "duplicate_cid": 0,
            "duplicate_source_kept_first": 0,
        },
        "drop_samples": {
            "empty_body": [],
            "missing_instrument": [],
            "duplicate_cid": [],
        },
        "language_breakdown": {},
        "quality_flags": {},
        "schema_surprises": list(source_meta.get("schema_surprises") or []),
        "n_out": 0,
        "never_invented_legal_text": True,
        "n_reconstructed_parents": 0,
        "n_reconstructed_truncated": 0,
        "n_reconstructed_stubs": 0,
        "n_empty_parents_with_articles_not_reconstructed": 0,
        "n_thin_instruments_replaced": 0,
    }

    entries: list[dict[str, Any]] = []
    slug = ""
    if source_dataset.startswith("endomorphosis/ipfs_") and source_dataset.endswith("_laws"):
        slug = source_dataset.split("ipfs_", 1)[1].removesuffix("_laws")

    children_by_law: dict[str, list[dict[str, Any]]] = {}
    if not articles_empty:
        for _, row in articles.iterrows():
            lid = _row_get(row, "law_id")
            if not lid:
                continue
            children_by_law.setdefault(lid, []).append(
                {
                    "id": _row_get(row, "id"),
                    "title": _row_get(row, "title"),
                    "article_number": _row_get(row, "article_number"),
                    "body": _row_get(row, "text"),
                    "row": row,
                }
            )

    reconstructed_ids: set[str] = set()
    running_extra_bytes = 0

    def _append_law_row(
        instrument_id: str,
        parent: dict[str, Any],
        recon=None,
    ) -> None:
        body = parent["body"]
        recon_extra: dict[str, Any] = {}
        coverage = _coverage_from(
            parent["row"],
            parent["metadata"],
            articles_empty=articles_empty,
            sparse_fallback=sparse_fallback,
        )
        if recon is not None and recon.reconstructed_from_articles:
            body = recon.body
            recon_extra = recon.extra_fields()
            coverage = f"{coverage}; reconstructed_from_articles"
        if not body:
            kids = children_by_law.get(instrument_id) or []
            if kids:
                report["n_empty_parents_with_articles_not_reconstructed"] += 1
            report["drops"]["empty_body"] += 1
            if len(report["drop_samples"]["empty_body"]) < 20:
                report["drop_samples"]["empty_body"].append(instrument_id)
            return
        meta = parent["metadata"]
        entries.append(
            _base_record(
                record_type=_instrument_record_type(meta, parent["instrument_title"]),
                source_dataset=source_dataset,
                source_revision=source_revision,
                instrument_id=instrument_id,
                instrument_title=parent["instrument_title"],
                law_cid=parent["law_cid"],
                article_number="",
                article_title="",
                body=body,
                jurisdiction=parent["jurisdiction"],
                language=parent["language"],
                source_url=parent["source_url"],
                snapshot_date=_snapshot_date(parent["row"], meta, source_meta),
                coverage=coverage,
                license_expr=parent["license"],
                collector=_collector(meta, source_dataset),
                source_id=instrument_id,
                extra={
                    "eli": parent["eli"],
                    "identifier": parent["identifier"],
                    "official_identifier": parent["official_identifier"],
                    "source_type": parent["source_type"],
                    "country": parent["country"],
                    "law_status": parent["law_status"],
                    "parent_law_id": "",
                    "article_id": "",
                    "reconstructed_from_articles": False,
                    **_hierarchy_fields(
                        parent["instrument_title"], body, "", language=parent["language"]
                    ),
                    **recon_extra,
                },
            )
        )

    if sparse_fallback:
        report["schema_surprises"].append(
            f"article coverage {article_law_coverage:.4f} < 0.10 of laws; falling back to law-level units"
        )

    for instrument_id, parent in law_map.items():
        kids = children_by_law.get(instrument_id) or []
        recon = None
        if reconstruct_on() and parent_needs_reconstruct(parent["body"], len(kids)):
            recon = reconstruct_parent(
                slug=slug,
                parent_body=parent["body"],
                parent_title=parent["instrument_title"],
                children=[
                    {
                        "id": k["id"],
                        "title": k["title"],
                        "article_number": k["article_number"],
                        "body": k["body"],
                    }
                    for k in kids
                ],
                running_extra_bytes=running_extra_bytes,
                sha256_hex=sha256_hex,
            )
            running_extra_bytes += recon.extra_bytes
            reconstructed_ids.add(instrument_id)
            report["n_reconstructed_parents"] += 1
            if recon.reconstruction_truncated:
                report["n_reconstructed_truncated"] += 1
            if recon.is_stub:
                report["n_reconstructed_stubs"] += 1
        _append_law_row(instrument_id, parent, recon)

    emit_articles = use_articles or bool(reconstructed_ids)
    skip_body_split = emit_articles
    sibling_titles = {
        instrument_id: {_compact_line(kid["title"]) for kid in kids}
        for instrument_id, kids in children_by_law.items()
    }
    promoted: dict[str, list[Any]] = {}
    if emit_articles:
        for instrument_id, parent in law_map.items():
            kids = children_by_law.get(instrument_id) or []
            if not _needs_parent_split(kids, parent["body"]):
                continue
            units = split_structured_units(parent["body"], language=parent["language"])
            covered = sum(len(unit.body) for unit in units)
            if len(units) >= 2 and covered >= int(0.35 * len(parent["body"])):
                promoted[instrument_id] = units
        if promoted:
            report["n_thin_instruments_replaced"] = len(promoted)
            report["schema_surprises"].append(
                "parent headings used for "
                f"{len(promoted)} instruments whose article rows were missing or thin"
            )

    if emit_articles:
        for _, row in articles.iterrows():
            source_id = _row_get(row, "id")
            instrument_id = _row_get(row, "law_id")
            body = _row_get(row, "text")
            article_title = _row_get(row, "title")
            article_number = _row_get(row, "article_number")
            if not body:
                report["drops"]["empty_body"] += 1
                if len(report["drop_samples"]["empty_body"]) < 20:
                    report["drop_samples"]["empty_body"].append(source_id)
                continue
            parent = law_map.get(instrument_id)
            if instrument_id in promoted:
                continue
            if parent and _is_title_shell(body, article_title):
                expanded = _expand_title_shell(
                    parent["body"],
                    article_title,
                    sibling_titles.get(instrument_id) or set(),
                )
                if expanded:
                    body = expanded
            if not parent:
                report["drops"]["missing_instrument"] += 1
                if len(report["drop_samples"]["missing_instrument"]) < 20:
                    report["drop_samples"]["missing_instrument"].append(
                        {"article_id": source_id, "law_id": instrument_id}
                    )
                continue
            meta = parent["metadata"]
            art_meta = _parse_meta(_row_get(row, "metadata_json"))
            merged_meta = {**meta, **art_meta}
            entries.append(
                _base_record(
                    record_type="article",
                    source_dataset=source_dataset,
                    source_revision=source_revision,
                    instrument_id=instrument_id,
                    instrument_title=parent["instrument_title"],
                    law_cid=parent["law_cid"],
                    article_number=article_number,
                    article_title=article_title,
                    body=body,
                    jurisdiction=parent["jurisdiction"],
                    language=parent["language"] or _row_get(row, "language"),
                    source_url=_row_get(row, "source_url") or parent["source_url"],
                    snapshot_date=_snapshot_date(parent["row"], merged_meta, source_meta),
                    coverage=_coverage_from(parent["row"], merged_meta, articles_empty=False),
                    license_expr=parent["license"],
                    collector=_collector(merged_meta, source_dataset),
                    source_id=source_id,
                    extra={
                        "eli": parent["eli"],
                        "identifier": parent["identifier"],
                        "official_identifier": parent["official_identifier"],
                        "source_type": parent["source_type"],
                        "country": parent["country"],
                        "law_status": parent["law_status"],
                        "parent_law_id": instrument_id,
                        "article_id": source_id,
                        **_hierarchy_fields(
                            article_title, body, article_number, language=parent["language"]
                        ),
                    },
                )
            )
        for instrument_id, units in promoted.items():
            parent = law_map[instrument_id]
            meta = parent["metadata"]
            report["unit"] = "structured"
            instrument_type = _instrument_record_type(meta, parent["instrument_title"])
            for unit in units:
                entries.append(
                    _base_record(
                        record_type=_unit_record_type(
                            unit,
                            instrument_type,
                            n_units=len(units),
                            parent_body=parent["body"],
                        ),
                        source_dataset=source_dataset,
                        source_revision=source_revision,
                        instrument_id=instrument_id,
                        instrument_title=parent["instrument_title"],
                        law_cid=parent["law_cid"],
                        article_number=unit.article_number or unit.number,
                        article_title=unit.heading,
                        body=unit.body,
                        jurisdiction=parent["jurisdiction"],
                        language=parent["language"],
                        source_url=parent["source_url"],
                        snapshot_date=_snapshot_date(parent["row"], meta, source_meta),
                        coverage="structured (thin article rows replaced from the parent law)",
                        license_expr=parent["license"],
                        collector=_collector(meta, source_dataset),
                        source_id=f"{instrument_id}-{unit.kind}-{unit.number}",
                        extra={
                            "eli": parent["eli"],
                            "identifier": parent["identifier"],
                            "official_identifier": parent["official_identifier"],
                            "source_type": parent["source_type"],
                            "country": parent["country"],
                            "law_status": parent["law_status"],
                            "parent_law_id": instrument_id,
                            "article_id": "",
                            "hierarchy_kind": unit.kind,
                            "hierarchy_path": unit.hierarchy_path,
                            "title_number": unit.title_number,
                            "chapter_number": unit.chapter_number,
                            "part_number": unit.part_number,
                            "section_number": unit.section_number,
                            "subsections": list(unit.subsections),
                        },
                    )
                )
    elif not skip_body_split:
        for instrument_id, parent in law_map.items():
            body = parent["body"]
            if not body:
                continue
            meta = parent["metadata"]
            units = split_structured_units(body, language=parent["language"])
            if units:
                report["unit"] = "structured"
                instrument_type = _instrument_record_type(meta, parent["instrument_title"])
                for unit in units:
                    entries.append(
                        _base_record(
                            record_type=_unit_record_type(
                                unit,
                                instrument_type,
                                n_units=len(units),
                                parent_body=body,
                            ),
                            source_dataset=source_dataset,
                            source_revision=source_revision,
                            instrument_id=instrument_id,
                            instrument_title=parent["instrument_title"],
                            law_cid=parent["law_cid"],
                            article_number=unit.article_number or unit.number,
                            article_title=unit.heading,
                            body=unit.body,
                            jurisdiction=parent["jurisdiction"],
                            language=parent["language"],
                            source_url=parent["source_url"],
                            snapshot_date=_snapshot_date(parent["row"], meta, source_meta),
                            coverage="structured (headings detected in law body)",
                            license_expr=parent["license"],
                            collector=_collector(meta, source_dataset),
                            source_id=f"{instrument_id}-{unit.kind}-{unit.number}",
                            extra={
                                "eli": parent["eli"],
                                "identifier": parent["identifier"],
                                "official_identifier": parent["official_identifier"],
                                "source_type": parent["source_type"],
                                "country": parent["country"],
                                "law_status": parent["law_status"],
                                "parent_law_id": instrument_id,
                                "article_id": "",
                                "hierarchy_kind": unit.kind,
                                "hierarchy_path": unit.hierarchy_path,
                                "title_number": unit.title_number,
                                "chapter_number": unit.chapter_number,
                                "part_number": unit.part_number,
                                "section_number": unit.section_number,
                                "subsections": list(unit.subsections),
                            },
                        )
                    )

    entries.sort(
        key=lambda r: (
            r["instrument_id"],
            article_sort_key(r.get("article_number") or "", r["source_id"]),
        )
    )
    n_before = len(entries)
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for rec in entries:
        cid = rec["entry_cid"]
        if cid in seen:
            report["drops"]["duplicate_cid"] += 1
            report["drops"]["duplicate_source_kept_first"] += 1
            if len(report["drop_samples"]["duplicate_cid"]) < 20:
                report["drop_samples"]["duplicate_cid"].append(rec["source_id"])
            continue
        seen.add(cid)
        deduped.append(rec)
    for i, rec in enumerate(deduped):
        rec["document_index"] = i
        rec["corpus_index"] = i

    df = pd.DataFrame(deduped)
    if not df.empty and df["entry_cid"].duplicated().any():
        raise SchemaError("Duplicate entry_cid remained after dedupe")
    report["n_before_dedupe"] = n_before
    report["n_out"] = int(len(df))
    if not df.empty and "record_type" in df.columns:
        n_law_rows = int((df["record_type"] == "law").sum())
        n_child_rows = int(df["record_type"].isin(["article", "section"]).sum())
        report["n_law_rows"] = n_law_rows
        report["n_child_rows"] = n_child_rows
        report["n_instruments"] = int(df["instrument_id"].nunique()) if "instrument_id" in df.columns else n_law_rows
        if n_law_rows and n_child_rows:
            report["unit"] = (
                "law+structured" if report.get("unit") == "structured" else "law+article"
            )
        elif n_law_rows:
            report["unit"] = "law"
        elif n_child_rows:
            report["unit"] = "article"
    report["n_dropped_total"] = (
        report["drops"]["empty_body"]
        + report["drops"]["missing_instrument"]
        + report["drops"]["duplicate_cid"]
    )
    if not df.empty:
        report["language_breakdown"] = {
            str(k): int(v) for k, v in df["language"].fillna("").value_counts().items()
        }
        report["record_type_breakdown"] = {
            str(k): int(v) for k, v in df["record_type"].value_counts().items()
        }
        report["jurisdiction_breakdown"] = {
            str(k): int(v) for k, v in df["jurisdiction"].fillna("").value_counts().items()
        }
        snapshot_dates = sorted({str(x) for x in df["snapshot_date"].fillna("") if str(x)})
        report["snapshot_dates"] = snapshot_dates
    else:
        report["language_breakdown"] = {}
        report["record_type_breakdown"] = {}
        report["jurisdiction_breakdown"] = {}
        report["snapshot_dates"] = []

    all_article_count_zero = False
    if "article_count" in laws.columns and len(laws):
        try:
            all_article_count_zero = int((laws["article_count"].fillna(0) == 0).sum()) == len(laws)
        except Exception:
            all_article_count_zero = False

    report["quality_flags"] = {
        "articles_table_empty": bool(articles_empty),
        "sparse_article_fallback": bool(sparse_fallback),
        "article_law_coverage": article_law_coverage,
        "all_source_article_counts_zero": all_article_count_zero,
        "article_extraction_status_counts": dict(extraction_statuses),
        "missing_date": bool("date" in laws.columns and laws["date"].isna().all()) if len(laws) else False,
        "missing_date_issued": bool("date_issued" in laws.columns and laws["date_issued"].isna().all()) if len(laws) else False,
        "eli_present": bool("eli" in laws.columns and laws["eli"].notna().any()) if len(laws) else False,
        "never_invented_legal_text": True,
        "empty_bodies_dropped": report["drops"]["empty_body"],
        "duplicate_cids_dropped": report["drops"]["duplicate_cid"],
    }
    from .profiles import majority_language, score_heading_languages

    sample_text = ""
    if not df.empty and "body" in df.columns:
        sample_text = "\n".join(str(x) for x in df["body"].head(40).tolist())
        if "title" in df.columns:
            sample_text = "\n".join(str(x) for x in df["title"].head(40).tolist()) + "\n" + sample_text
    heading_langs = score_heading_languages(sample_text)
    report["heading_language_counts"] = dict(heading_langs)
    report["heading_language_majority"] = majority_language(heading_langs)
    report["document_language_majority"] = None
    if report.get("language_breakdown"):
        report["document_language_majority"] = max(
            report["language_breakdown"].items(), key=lambda kv: kv[1]
        )[0]
    from .verify import verify_normalized_corpus

    report["verification"] = verify_normalized_corpus(df, report)
    df.attrs["normalization_report"] = report
    return df, report
