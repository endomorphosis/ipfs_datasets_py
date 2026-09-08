"""Read endomorphosis/ipfs_<country>_laws parquet into a CID-keyed corpus."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd
from huggingface_hub import hf_hub_download, dataset_info

from .auth import configure_hf, load_token

from . import ENTRY_IDENTITY_SCHEMA, SCHEMA_VERSION
from .cidutil import cid_of_json, sha256_hex
from .schema import SchemaError, validate_articles, validate_laws


def _s(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if pd.isna(value):
        return ""
    return str(value)


def _download(repo_id: str, filename: str, cache_dir: Path) -> Path:
    configure_hf()
    path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        repo_type="dataset",
        token=load_token(),
        cache_dir=str(cache_dir / "hf"),
    )
    return Path(path)


def load_source(repo_id: str, cache_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    configure_hf()
    info = dataset_info(repo_id, token=load_token())
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
        "n_laws_source": int(len(laws)),
        "n_articles_source": int(len(articles)),
        "laws_columns": list(map(str, laws.columns)),
        "articles_columns": list(map(str, articles.columns)),
        "article_count_dtype": str(laws["article_count"].dtype) if "article_count" in laws.columns else None,
    }
    return laws, articles, meta


def _entry_cid(record: dict[str, Any]) -> str:
    identity = {
        "schema": ENTRY_IDENTITY_SCHEMA,
        "record_type": record["record_type"],
        "source_dataset": record["source_dataset"],
        "source_id": record["source_id"],
        "law_id": record.get("law_id") or record["source_id"],
        "title": record["title"],
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


def laws_to_entries(laws: pd.DataFrame, source_dataset: str, source_revision: str) -> list[dict[str, Any]]:
    entries = []
    for _, row in laws.iterrows():
        body = _row_get(row, "text")
        title = _row_get(row, "title")
        source_id = _row_get(row, "id")
        rec = {
            "record_type": "law",
            "source_dataset": source_dataset,
            "source_revision": source_revision,
            "source_id": source_id,
            "law_id": source_id,
            "article_id": "",
            "parent_law_id": "",
            "title": title,
            "body": body,
            "body_sha256": sha256_hex(body.encode("utf-8")),
            "source_url": _row_get(row, "source_url"),
            "source_type": _row_get(row, "source_type"),
            "jurisdiction": _row_get(row, "jurisdiction"),
            "country": _row_get(row, "country"),
            "language": _row_get(row, "language"),
            "eli": _row_get(row, "eli"),
            "date": _row_get(row, "date"),
            "date_issued": _row_get(row, "date_issued"),
            "retrieved_at": _row_get(row, "retrieved_at"),
            "license_expression": _row_get(row, "license"),
            "law_status": _row_get(row, "law_status"),
            "identifier": _row_get(row, "identifier"),
            "official_identifier": _row_get(row, "official_identifier"),
            "article_number": "",
            "document_number": "",
            "article_count": int(row["article_count"]) if "article_count" in row.index and pd.notna(row["article_count"]) else 0,
            "metadata_json": _row_get(row, "metadata_json"),
        }
        rec["entry_cid"] = _entry_cid(rec)
        rec["entry_sha256"] = hashlib.sha256(rec["entry_cid"].encode()).hexdigest()
        rec["title_length"] = len(title)
        rec["body_length"] = len(body)
        rec["document_length"] = len(title) + len(body)
        rec["schema_version"] = SCHEMA_VERSION
        rec["entry_identity_schema_version"] = ENTRY_IDENTITY_SCHEMA
        entries.append(rec)
    return entries


def articles_to_entries(
    articles: pd.DataFrame,
    source_dataset: str,
    source_revision: str,
    law_ids: set[str],
) -> list[dict[str, Any]]:
    if articles is None or articles.empty:
        return []
    entries = []
    for _, row in articles.iterrows():
        body = _row_get(row, "text")
        title = _row_get(row, "title")
        source_id = _row_get(row, "id")
        law_id = _row_get(row, "law_id")
        rec = {
            "record_type": "article",
            "source_dataset": source_dataset,
            "source_revision": source_revision,
            "source_id": source_id,
            "law_id": law_id,
            "article_id": source_id,
            "parent_law_id": law_id if law_id in law_ids else "",
            "title": title,
            "body": body,
            "body_sha256": sha256_hex(body.encode("utf-8")),
            "source_url": _row_get(row, "source_url"),
            "source_type": "",
            "jurisdiction": "",
            "country": "",
            "language": "",
            "eli": "",
            "date": "",
            "date_issued": "",
            "retrieved_at": "",
            "license_expression": "",
            "law_status": "",
            "identifier": source_id,
            "official_identifier": _row_get(row, "article_number") or source_id,
            "article_number": _row_get(row, "article_number"),
            "document_number": _row_get(row, "document_number"),
            "article_count": 0,
            "metadata_json": _row_get(row, "metadata_json"),
        }
        rec["entry_cid"] = _entry_cid(rec)
        rec["entry_sha256"] = hashlib.sha256(rec["entry_cid"].encode()).hexdigest()
        rec["title_length"] = len(title)
        rec["body_length"] = len(body)
        rec["document_length"] = len(title) + len(body)
        rec["schema_version"] = SCHEMA_VERSION
        rec["entry_identity_schema_version"] = ENTRY_IDENTITY_SCHEMA
        entries.append(rec)
    return entries


def inherit_law_facets(entries: list[dict[str, Any]]) -> None:
    by_law: dict[str, dict[str, Any]] = {
        e["law_id"]: e for e in entries if e["record_type"] == "law"
    }
    facet_keys = (
        "source_type",
        "jurisdiction",
        "country",
        "language",
        "eli",
        "license_expression",
        "law_status",
    )
    for e in entries:
        if e["record_type"] != "article":
            continue
        parent = by_law.get(e["law_id"])
        if not parent:
            continue
        for k in facet_keys:
            if not e.get(k):
                e[k] = parent.get(k) or ""


def build_corpus(laws: pd.DataFrame, articles: pd.DataFrame, source_meta: dict[str, Any]) -> pd.DataFrame:
    source_dataset = source_meta["source_dataset"]
    source_revision = source_meta["source_revision"]
    law_entries = laws_to_entries(laws, source_dataset, source_revision)
    law_ids = {e["law_id"] for e in law_entries}
    art_entries = articles_to_entries(articles, source_dataset, source_revision, law_ids)
    inherit_law_facets(art_entries)
    all_entries = law_entries + art_entries
    all_entries.sort(key=lambda r: (r["record_type"] != "law", r["law_id"], r["article_number"], r["source_id"]))
    for i, rec in enumerate(all_entries):
        rec["document_index"] = i
        rec["corpus_index"] = i
    df = pd.DataFrame(all_entries)
    n_before = len(df)
    # Source corpora sometimes repeat the same article row. Identical identity
    # JSON => identical CID; drop extras instead of inventing a new id.
    df = df.drop_duplicates(subset=["entry_cid"], keep="first").reset_index(drop=True)
    n_dropped = n_before - len(df)
    if n_dropped:
        print(f"dropped {n_dropped} duplicate-CID rows (kept first)", flush=True)
        df["document_index"] = range(len(df))
        df["corpus_index"] = range(len(df))
    if df["entry_cid"].duplicated().any():
        raise SchemaError("Duplicate entry_cid remained after dedupe")
    df.attrs["n_duplicate_cid_dropped"] = int(n_dropped)
    return df
