"""Normalize endomorphosis/ipfs_*_laws into a CID-keyed canonical corpus.

Prefer article/section as the retrieval unit; fall back to law-level when
articles are missing or empty. Normalize (NFKC + whitespace collapse) BEFORE
GraphRAG. Never invent legal text or identifiers.

Public Hub reads only (token=False). No Hugging Face token is read or stored.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
from huggingface_hub import dataset_info, hf_hub_download

from . import ENTRY_IDENTITY_SCHEMA, LAW_IDENTITY_SCHEMA, SCHEMA_VERSION
from .auth import configure_hf, public_token
from .cidutil import cid_of_json, sha256_file, sha256_hex
from .schema import SchemaError, validate_articles, validate_laws

_WS_RE = re.compile(r"\s+", re.UNICODE)
COLLECTOR_DEFAULT = "endomorphosis/ipfs_datasets_py"


def normalize_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = _WS_RE.sub(" ", text).strip()
    return text


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


def load_source(repo_id: str, cache_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    configure_hf()
    os.environ.setdefault("HF_HOME", str(cache_dir / "hf"))
    info = dataset_info(repo_id, token=public_token())
    revision = info.sha
    laws_path = _download(repo_id, "data/laws.parquet", cache_dir)
    articles_path = _download(repo_id, "data/articles.parquet", cache_dir)
    laws = pd.read_parquet(laws_path)
    articles = pd.read_parquet(articles_path)
    validate_laws(laws)
    validate_articles(articles)
    meta = {
        "source_dataset": repo_id,
        "source_revision": revision,
        "laws_path": str(laws_path),
        "articles_path": str(articles_path),
        "laws_sha256": sha256_file(laws_path),
        "articles_sha256": sha256_file(articles_path),
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


def _coverage_from(row: pd.Series, meta: dict[str, Any], articles_empty: bool) -> str:
    for key in ("coverage", "coverage_note"):
        if key in meta and meta[key]:
            return normalize_text(meta[key])
    status = normalize_text(meta.get("article_extraction_status") or "")
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
        "unit": "article" if not articles_empty else "law",
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
    }

    entries: list[dict[str, Any]] = []

    if not articles_empty:
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
                    },
                )
            )
    else:
        for instrument_id, parent in law_map.items():
            body = parent["body"]
            if not body:
                report["drops"]["empty_body"] += 1
                if len(report["drop_samples"]["empty_body"]) < 20:
                    report["drop_samples"]["empty_body"].append(instrument_id)
                continue
            meta = parent["metadata"]
            entries.append(
                _base_record(
                    record_type="law",
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
                    coverage=_coverage_from(parent["row"], meta, articles_empty=True),
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
                    },
                )
            )

    entries.sort(
        key=lambda r: (
            r["instrument_id"],
            r.get("article_number") or "",
            r["source_id"],
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
        "all_source_article_counts_zero": all_article_count_zero,
        "article_extraction_status_counts": dict(extraction_statuses),
        "missing_date": bool("date" in laws.columns and laws["date"].isna().all()) if len(laws) else False,
        "missing_date_issued": bool("date_issued" in laws.columns and laws["date_issued"].isna().all()) if len(laws) else False,
        "eli_present": bool("eli" in laws.columns and laws["eli"].notna().any()) if len(laws) else False,
        "never_invented_legal_text": True,
        "empty_bodies_dropped": report["drops"]["empty_body"],
        "duplicate_cids_dropped": report["drops"]["duplicate_cid"],
    }
    df.attrs["normalization_report"] = report
    return df, report
