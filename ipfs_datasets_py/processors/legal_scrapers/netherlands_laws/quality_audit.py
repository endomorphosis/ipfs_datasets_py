"""Corpus quality audits for the Netherlands legal pipeline."""

from __future__ import annotations

import hashlib
import json
import random
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.dataset as ds
import pyarrow.parquet as pq

from .builders.common import PARSER_NOISE_PHRASES, clean_legal_text, read_jsonl, write_json
from .builders.ipfs_indexes import tokenise
from .paths import (
    BM25_INDEX_DATASET_NAME,
    HF_DATA_DIR,
    IPFS_DATASET_NAME,
    KNOWLEDGE_GRAPH_DATASET_NAME,
    OPERATIONS_DATA_DIR,
    PACKAGE_RAW_OUTPUT_DIR,
    VECTOR_INDEX_DATASET_NAME,
)


STATUS_VALUES = ["current", "historical", "repealed", "superseded", "unknown"]
GENERATED_FIELDS = {"cid", "content_address", "law_cid", "index_row_cid", "doc_row_cid", "node_cid", "edge_cid"}
HIERARCHY_ORDER = {
    "boek": 10,
    "titel": 20,
    "hoofdstuk": 30,
    "afdeling": 40,
    "paragraaf": 50,
    "artikel": 60,
}
HIERARCHY_FIELD_BY_KIND = {
    "boek": "book_label",
    "titel": "title_label",
    "hoofdstuk": "chapter_label",
    "afdeling": "division_label",
    "paragraaf": "paragraph_label",
    "artikel": "article_label",
}
COMMON_BM25_SKIP_TOKENS = {
    "artikel",
    "regeling",
    "wordt",
    "zoals",
    "bedoeld",
    "eerste",
    "tweede",
    "derde",
    "onderdeel",
    "minister",
    "hoofdstuk",
    "paragraaf",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sample(items: list[Any], limit: int) -> list[Any]:
    return items[:limit]


def _row_ref(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "law_identifier": row.get("law_identifier"),
        "article_identifier": row.get("article_identifier"),
        "citation": row.get("citation"),
        "cid": row.get("cid") or row.get("source_cid"),
    }


def _normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_text_key(value: Any) -> str:
    text = _normalize_space(value).casefold()
    return re.sub(r"[^\wÀ-ÿ]+", " ", text, flags=re.UNICODE).strip()


def _article_sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("law_identifier") or ""), str(row.get("article_identifier") or ""))


def _read_base_rows(base_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    laws = read_jsonl(base_dir / "data/laws/ipfs_netherlands_laws.jsonl")
    articles = read_jsonl(base_dir / "data/articles/ipfs_netherlands_laws_articles.jsonl")
    cid_index = read_jsonl(base_dir / "data/cid_index/ipfs_netherlands_laws_cid_index.jsonl")
    return laws, articles, cid_index


def _read_parquet_rows(path: Path, columns: list[str]) -> list[dict[str, Any]]:
    return pq.read_table(path, columns=columns).to_pylist()


def _duplicate_groups(
    rows: list[dict[str, Any]],
    *,
    fields: list[str] | None = None,
    exclude_fields: set[str] | None = None,
    sample_limit: int = 20,
) -> dict[str, Any]:
    exclude_fields = exclude_fields or set()
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if fields is None:
            payload = {key: value for key, value in row.items() if key not in exclude_fields}
        else:
            payload = {key: row.get(key) for key in fields}
        groups[_sha256_text(_compact_json(payload))].append(row)
    duplicates = [(key, group) for key, group in groups.items() if len(group) > 1]
    duplicate_rows = sum(len(group) for _, group in duplicates)
    return {
        "group_count": len(duplicates),
        "row_count": duplicate_rows,
        "samples": [
            {
                "hash": key,
                "row_count": len(group),
                "rows": [_row_ref(row) for row in _sample(group, 10)],
            }
            for key, group in _sample(duplicates, sample_limit)
        ],
    }


def _identifier_duplicates(rows: list[dict[str, Any]], field: str, sample_limit: int = 20) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = str(row.get(field) or "")
        if value:
            groups[value].append(row)
    duplicates = [(key, group) for key, group in groups.items() if len(group) > 1]
    return {
        "field": field,
        "group_count": len(duplicates),
        "row_count": sum(len(group) for _, group in duplicates),
        "samples": [
            {"value": key, "row_count": len(group), "rows": [_row_ref(row) for row in _sample(group, 10)]}
            for key, group in _sample(duplicates, sample_limit)
        ],
    }


def _duplicate_text_groups(articles: list[dict[str, Any]], sample_limit: int = 20) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    previews: dict[str, str] = {}
    for row in articles:
        key_text = _normalize_text_key(row.get("text"))
        if not key_text:
            continue
        key = _sha256_text(key_text)
        groups[key].append(row)
        previews.setdefault(key, _normalize_space(row.get("text"))[:500])
    duplicates: list[tuple[str, list[dict[str, Any]]]] = []
    for key, group in groups.items():
        identifiers = {str(row.get("article_identifier") or "") for row in group}
        if len(group) > 1 and len(identifiers) > 1:
            duplicates.append((key, sorted(group, key=_article_sort_key)))
    duplicates.sort(key=lambda item: len(item[1]), reverse=True)
    return {
        "group_count": len(duplicates),
        "row_count": sum(len(group) for _, group in duplicates),
        "samples": [
            {
                "text_hash": key,
                "row_count": len(group),
                "text_preview": previews.get(key, ""),
                "rows": [_row_ref(row) for row in _sample(group, 12)],
            }
            for key, group in _sample(duplicates, sample_limit)
        ],
    }


def _duplicate_report(laws: list[dict[str, Any]], articles: list[dict[str, Any]], cid_index: list[dict[str, Any]]) -> dict[str, Any]:
    all_cids: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in laws + articles + cid_index:
        cid = str(row.get("cid") or "")
        if cid:
            all_cids[cid].append(row)
    duplicate_cids = [(cid, group) for cid, group in all_cids.items() if len(group) > 2]
    duplicate_cids.sort(key=lambda item: len(item[1]), reverse=True)
    return {
        "generated_at": _now(),
        "records": {"laws": len(laws), "articles": len(articles), "cid_index": len(cid_index)},
        "laws": {
            "duplicate_identifiers": _identifier_duplicates(laws, "law_identifier"),
            "duplicate_logical_rows": _duplicate_groups(laws, exclude_fields=GENERATED_FIELDS),
            "duplicate_text_groups": _duplicate_groups(laws, fields=["text"]),
        },
        "articles": {
            "duplicate_identifiers": _identifier_duplicates(articles, "article_identifier"),
            "duplicate_logical_rows": _duplicate_groups(articles, exclude_fields=GENERATED_FIELDS),
            "duplicate_text_under_different_identifiers": _duplicate_text_groups(articles),
        },
        "cids": {
            "duplicate_cid_groups": len(duplicate_cids),
            "duplicate_cid_rows": sum(len(group) for _, group in duplicate_cids),
            "note": "Rows are expected to appear once in their table and once in cid_index; groups larger than two indicate duplicate CID output.",
            "samples": [
                {"cid": cid, "row_count": len(group), "rows": [_row_ref(row) for row in _sample(group, 12)]}
                for cid, group in _sample(duplicate_cids, 20)
            ],
        },
    }


def _noise_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pattern_rows: dict[str, int] = {}
    pattern_occurrences: dict[str, int] = {}
    rows_with_noise = 0
    for phrase in PARSER_NOISE_PHRASES:
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        row_count = 0
        occurrence_count = 0
        for row in rows:
            text = str(row.get("text") or "")
            occurrences = len(pattern.findall(text))
            if occurrences:
                row_count += 1
                occurrence_count += occurrences
        pattern_rows[phrase] = row_count
        pattern_occurrences[phrase] = occurrence_count
    for row in rows:
        text = str(row.get("text") or "")
        if any(re.search(re.escape(phrase), text, re.IGNORECASE) for phrase in PARSER_NOISE_PHRASES):
            rows_with_noise += 1
    return {
        "rows": len(rows),
        "rows_with_noise": rows_with_noise,
        "pattern_rows": pattern_rows,
        "pattern_occurrences": pattern_occurrences,
        "total_occurrences": sum(pattern_occurrences.values()),
    }


def _cleaning_effect(rows: list[dict[str, Any]]) -> dict[str, Any]:
    changed = 0
    before_chars = 0
    after_chars = 0
    samples: list[dict[str, Any]] = []
    for row in rows:
        before = str(row.get("text") or "")
        after = clean_legal_text(before)
        before_chars += len(before)
        after_chars += len(after)
        if before != after:
            changed += 1
            if len(samples) < 20:
                samples.append(
                    {
                        **_row_ref(row),
                        "before_preview": _normalize_space(before)[:300],
                        "after_preview": _normalize_space(after)[:300],
                    }
                )
    return {
        "rows_changed": changed,
        "before_chars": before_chars,
        "after_chars": after_chars,
        "chars_removed": before_chars - after_chars,
        "samples": samples,
    }


def _parser_noise_report(
    laws: list[dict[str, Any]],
    articles: list[dict[str, Any]],
    *,
    raw_dir: Path | None,
) -> dict[str, Any]:
    raw_section: dict[str, Any] = {"available": False}
    if raw_dir:
        raw_laws_path = raw_dir / "netherlands_laws_index_latest.jsonl"
        raw_articles_path = raw_dir / "netherlands_laws_articles_index_latest.jsonl"
        if raw_laws_path.exists() and raw_articles_path.exists():
            raw_laws = read_jsonl(raw_laws_path)
            raw_articles = read_jsonl(raw_articles_path)
            raw_section = {
                "available": True,
                "raw_dir": str(raw_dir),
                "laws": _noise_counts(raw_laws),
                "articles": _noise_counts(raw_articles),
                "cleaning_effect_laws": _cleaning_effect(raw_laws),
                "cleaning_effect_articles": _cleaning_effect(raw_articles),
            }
    return {
        "generated_at": _now(),
        "noise_phrases": PARSER_NOISE_PHRASES,
        "packaged": {
            "laws": _noise_counts(laws),
            "articles": _noise_counts(articles),
        },
        "raw_source": raw_section,
        "status": "clean" if _noise_counts(laws)["total_occurrences"] == 0 and _noise_counts(articles)["total_occurrences"] == 0 else "noise_remaining",
    }


def _percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    index = (len(values) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    if lower == upper:
        return float(values[lower])
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


def _article_quality(articles: list[dict[str, Any]]) -> dict[str, Any]:
    char_lengths = [len(str(row.get("text") or "").strip()) for row in articles]
    token_lengths = [len(tokenise(str(row.get("text") or ""))) for row in articles]
    short = [row for row, length, tokens in zip(articles, char_lengths, token_lengths) if length < 40 or tokens < 5]
    long_threshold = max(20000, int(_percentile(char_lengths, 0.99) * 2))
    long_rows = [row for row, length in zip(articles, char_lengths) if length > long_threshold]
    empty_rows = [row for row, length in zip(articles, char_lengths) if length == 0]
    return {
        "article_count": len(articles),
        "char_length": {
            "average": round(statistics.mean(char_lengths), 2) if char_lengths else 0,
            "median": round(statistics.median(char_lengths), 2) if char_lengths else 0,
            "min": min(char_lengths) if char_lengths else 0,
            "max": max(char_lengths) if char_lengths else 0,
            "p01": round(_percentile(char_lengths, 0.01), 2),
            "p05": round(_percentile(char_lengths, 0.05), 2),
            "p95": round(_percentile(char_lengths, 0.95), 2),
            "p99": round(_percentile(char_lengths, 0.99), 2),
            "suspicious_long_threshold": long_threshold,
        },
        "token_length": {
            "average": round(statistics.mean(token_lengths), 2) if token_lengths else 0,
            "median": round(statistics.median(token_lengths), 2) if token_lengths else 0,
            "min": min(token_lengths) if token_lengths else 0,
            "max": max(token_lengths) if token_lengths else 0,
            "p99": round(_percentile(token_lengths, 0.99), 2),
        },
        "empty_articles": {"count": len(empty_rows), "samples": [_row_ref(row) for row in _sample(empty_rows, 20)]},
        "suspiciously_short_articles": {
            "threshold": "chars < 40 or tokens < 5",
            "count": len(short),
            "samples": [{**_row_ref(row), "text": _normalize_space(row.get("text"))[:300]} for row in _sample(short, 30)],
        },
        "suspiciously_long_articles": {
            "threshold_chars": long_threshold,
            "count": len(long_rows),
            "samples": [
                {**_row_ref(row), "char_length": len(str(row.get("text") or "")), "text_preview": _normalize_space(row.get("text"))[:300]}
                for row in _sample(long_rows, 30)
            ],
        },
    }


def _hierarchy_report(articles: list[dict[str, Any]]) -> dict[str, Any]:
    kind_counts: Counter[str] = Counter()
    level_presence: Counter[str] = Counter()
    unknown_kind: list[dict[str, Any]] = []
    missing_path: list[dict[str, Any]] = []
    missing_article_level: list[dict[str, Any]] = []
    inconsistent_order: list[dict[str, Any]] = []
    path_text_mismatch: list[dict[str, Any]] = []
    label_field_mismatch: list[dict[str, Any]] = []
    number_mismatch: list[dict[str, Any]] = []

    for row in articles:
        path = row.get("hierarchy_path") or []
        if not path:
            missing_path.append(row)
            continue

        ranks: list[int] = []
        labels: list[str] = []
        path_by_kind: dict[str, dict[str, Any]] = {}
        for item in path:
            kind = str((item or {}).get("kind") or "").strip().casefold()
            label = str((item or {}).get("label") or "").strip()
            kind_counts[kind or "missing"] += 1
            labels.append(label)
            if kind in HIERARCHY_ORDER:
                ranks.append(HIERARCHY_ORDER[kind])
                path_by_kind[kind] = item
                level_presence[kind] += 1
            elif len(unknown_kind) < 50:
                unknown_kind.append({**_row_ref(row), "kind": kind, "label": label})

        if str((path[-1] or {}).get("kind") or "").strip().casefold() != "artikel":
            missing_article_level.append(row)
        if any(next_rank < rank for rank, next_rank in zip(ranks, ranks[1:])):
            inconsistent_order.append(row)

        expected_path_text = " > ".join(label for label in labels if label)
        if _normalize_space(row.get("hierarchy_path_text")) != _normalize_space(expected_path_text):
            path_text_mismatch.append(row)

        for kind, field in HIERARCHY_FIELD_BY_KIND.items():
            expected = _normalize_space((path_by_kind.get(kind) or {}).get("label"))
            actual = _normalize_space(row.get(field))
            if expected and actual != expected:
                label_field_mismatch.append({**row, "_mismatch_kind": kind, "_expected_label": expected, "_actual_label": actual})
                break

        article_path_number = _normalize_space((path[-1] or {}).get("number")) if path else ""
        article_number = _normalize_space(row.get("article_number"))
        if article_path_number and article_number and article_path_number != article_number:
            number_mismatch.append(row)

    return {
        "generated_at": _now(),
        "article_count": len(articles),
        "kind_counts": dict(sorted(kind_counts.items())),
        "level_presence": {kind: level_presence.get(kind, 0) for kind in HIERARCHY_ORDER},
        "missing_hierarchy_path": {"count": len(missing_path), "samples": [_row_ref(row) for row in _sample(missing_path, 30)]},
        "missing_article_level": {"count": len(missing_article_level), "samples": [_row_ref(row) for row in _sample(missing_article_level, 30)]},
        "unknown_hierarchy_kinds": {"count": sum(count for kind, count in kind_counts.items() if kind not in HIERARCHY_ORDER), "samples": unknown_kind},
        "inconsistent_nesting_order": {"count": len(inconsistent_order), "samples": [_row_ref(row) for row in _sample(inconsistent_order, 30)]},
        "path_text_mismatches": {"count": len(path_text_mismatch), "samples": [_row_ref(row) for row in _sample(path_text_mismatch, 30)]},
        "label_field_mismatches": {
            "count": len(label_field_mismatch),
            "samples": [
                {
                    **_row_ref(row),
                    "kind": row.get("_mismatch_kind"),
                    "expected": row.get("_expected_label"),
                    "actual": row.get("_actual_label"),
                }
                for row in _sample(label_field_mismatch, 30)
            ],
        },
        "article_number_mismatches": {"count": len(number_mismatch), "samples": [_row_ref(row) for row in _sample(number_mismatch, 30)]},
    }


def _citation_report(articles: list[dict[str, Any]]) -> dict[str, Any]:
    citation_mismatch: list[dict[str, Any]] = []
    path_not_in_citation: list[dict[str, Any]] = []
    identifier_mismatch: list[dict[str, Any]] = []
    for row in articles:
        labels = [str(label or "") for label in (row.get("hierarchy_labels") or []) if str(label or "").strip()]
        expected = ", ".join([part for part in [row.get("document_citation"), *labels] if str(part or "").strip()])
        if _normalize_space(row.get("citation")) != _normalize_space(expected):
            citation_mismatch.append({**row, "_expected_citation": expected})
        citation_norm = _normalize_space(row.get("citation")).casefold()
        if any(_normalize_space(label).casefold() not in citation_norm for label in labels):
            path_not_in_citation.append(row)
        law_identifier = str(row.get("law_identifier") or "")
        article_identifier = str(row.get("article_identifier") or "")
        if law_identifier and article_identifier and not article_identifier.startswith(f"{law_identifier}:"):
            identifier_mismatch.append(row)
    return {
        "citation_reconstruction_mismatches": {
            "count": len(citation_mismatch),
            "samples": [
                {**_row_ref(row), "expected_citation": row.get("_expected_citation")}
                for row in _sample(citation_mismatch, 30)
            ],
        },
        "hierarchy_labels_missing_from_citation": {
            "count": len(path_not_in_citation),
            "samples": [_row_ref(row) for row in _sample(path_not_in_citation, 30)],
        },
        "article_identifier_law_prefix_mismatches": {
            "count": len(identifier_mismatch),
            "samples": [_row_ref(row) for row in _sample(identifier_mismatch, 30)],
        },
    }


def _status_report(laws: list[dict[str, Any]], articles: list[dict[str, Any]]) -> dict[str, Any]:
    law_status_counts = Counter(str(row.get("law_status") or "unknown") for row in laws)
    article_status_counts = Counter(str(row.get("law_status") or "unknown") for row in articles)
    ambiguous: list[dict[str, Any]] = []
    inconsistent: list[dict[str, Any]] = []
    for row in laws:
        status = str(row.get("law_status") or "unknown")
        confidence = str(row.get("status_confidence") or "").casefold()
        is_current = row.get("is_current")
        valid_to = str(row.get("valid_to") or "")
        if status == "unknown" or confidence in {"", "low"}:
            ambiguous.append(row)
        if (status == "current" and is_current is False) or (status != "current" and is_current is True):
            inconsistent.append(row)
        elif status == "current" and valid_to:
            inconsistent.append(row)
    law_by_id = {row.get("law_identifier"): row for row in laws}
    inheritance_drift: list[dict[str, Any]] = []
    inherited_fields = [
        "law_status",
        "is_current",
        "valid_from",
        "valid_to",
        "effective_date",
        "retrieved_at",
        "status_source",
        "status_confidence",
        "status_note",
        "version_start_date",
        "version_end_date",
    ]
    for row in articles:
        law = law_by_id.get(row.get("law_identifier"))
        if not law:
            continue
        if any(row.get(field) != law.get(field) for field in inherited_fields):
            inheritance_drift.append(row)
    return {
        "laws": {status: law_status_counts.get(status, 0) for status in STATUS_VALUES},
        "articles": {status: article_status_counts.get(status, 0) for status in STATUS_VALUES},
        "ambiguous_laws": {
            "count": len(ambiguous),
            "criteria": "law_status == unknown or status_confidence is blank/low",
            "samples": [
                {
                    **_row_ref(row),
                    "law_status": row.get("law_status"),
                    "status_confidence": row.get("status_confidence"),
                    "status_source": row.get("status_source"),
                    "status_note": row.get("status_note"),
                }
                for row in _sample(ambiguous, 50)
            ],
        },
        "status_consistency_issues": {"count": len(inconsistent), "samples": [_row_ref(row) for row in _sample(inconsistent, 50)]},
        "article_status_inheritance_drift": {"count": len(inheritance_drift), "samples": [_row_ref(row) for row in _sample(inheritance_drift, 50)]},
    }


def _measured_size(value: Any) -> int:
    return len(_compact_json(value))


def _field_size_report(rows: list[dict[str, Any]], limit: int = 25) -> list[dict[str, Any]]:
    field_sizes: Counter[str] = Counter()
    nonnull: Counter[str] = Counter()
    for row in rows:
        for key, value in row.items():
            if value not in (None, "", [], {}):
                field_sizes[key] += _measured_size(value)
                nonnull[key] += 1
    total = sum(field_sizes.values())
    return [
        {
            "field": key,
            "total_bytes": size,
            "pct_of_measured_fields": round(100 * size / total, 2) if total else 0.0,
            "nonnull_rows": nonnull[key],
            "avg_bytes_when_present": round(size / nonnull[key], 1) if nonnull[key] else 0.0,
        }
        for key, size in sorted(field_sizes.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def _package_file_sizes(root: Path) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            sizes[path.relative_to(root).as_posix()] = path.stat().st_size
    return sizes


def _packaging_report(base_dir: Path, laws: list[dict[str, Any]], articles: list[dict[str, Any]], cid_index: list[dict[str, Any]]) -> dict[str, Any]:
    repeated_article_metadata_fields = [
        "law_identifier",
        "law_version_identifier",
        "version_specific_identifier",
        "document_identifier",
        "document_version_identifier",
        "document_citation",
        "law_status",
        "is_current",
        "valid_from",
        "valid_to",
        "effective_date",
        "retrieved_at",
        "status_source",
        "status_confidence",
        "status_note",
        "version_start_date",
        "version_end_date",
    ]
    repeated_bytes = sum(
        _measured_size(row.get(field))
        for row in articles
        for field in repeated_article_metadata_fields
        if row.get(field) not in (None, "", [], {})
    )
    law_text_bytes = sum(len(str(row.get("text") or "").encode("utf-8")) for row in laws)
    article_text_bytes = sum(len(str(row.get("text") or "").encode("utf-8")) for row in articles)
    return {
        "records": {"laws": len(laws), "articles": len(articles), "cid_index": len(cid_index)},
        "file_sizes": _package_file_sizes(base_dir),
        "field_size_top_laws": _field_size_report(laws),
        "field_size_top_articles": _field_size_report(articles),
        "field_size_top_cid_index": _field_size_report(cid_index),
        "repeated_article_metadata": {
            "fields": repeated_article_metadata_fields,
            "estimated_json_bytes": repeated_bytes,
            "estimated_avg_bytes_per_article": round(repeated_bytes / len(articles), 2) if articles else 0.0,
        },
        "text_payload": {
            "law_text_utf8_bytes": law_text_bytes,
            "article_text_utf8_bytes": article_text_bytes,
            "law_to_article_text_byte_ratio": round(law_text_bytes / article_text_bytes, 4) if article_text_bytes else None,
        },
        "normalization_improvements_without_logical_content_change": [
            "Keep article text in article rows, but consider storing law-level full text as an optional derived artifact because it repeats much of the article corpus.",
            "Move repeated law/version/status metadata in article rows into a law/version dimension table for analytics packages while preserving the denormalized CID package.",
            "Store hierarchy path as canonical structured nodes plus compact IDs in retrieval-optimized indexes.",
            "Keep vector embeddings out of user-facing row payloads when a FAISS artifact plus CID-to-row mapping is sufficient.",
        ],
    }


def _pick_bm25_probe_tokens(row: dict[str, Any], limit: int = 2) -> list[str]:
    tokens = {
        token
        for token in tokenise(str(row.get("text") or ""))
        if len(token) >= 8 and not token.isdigit() and token not in COMMON_BM25_SKIP_TOKENS
    }
    return sorted(tokens, key=lambda token: (-len(token), token))[:limit]


def _bm25_term_probe(
    bm25_terms_path: Path,
    sample_rows: list[dict[str, Any]],
    *,
    term_sample_size: int,
) -> dict[str, Any]:
    token_to_cids: dict[str, set[str]] = defaultdict(set)
    cid_to_tokens: dict[str, list[str]] = {}
    for row in sample_rows[:term_sample_size]:
        tokens = _pick_bm25_probe_tokens(row)
        if not tokens:
            continue
        cid = str(row.get("cid") or "")
        cid_to_tokens[cid] = tokens
        for token in tokens:
            token_to_cids[token].add(cid)
    if not token_to_cids:
        return {"checked": 0, "ok": True, "failures": [], "note": "No suitable probe tokens found."}

    try:
        dataset = ds.dataset(bm25_terms_path)
        term_table = dataset.to_table(
            columns=["term", "postings"],
            filter=ds.field("term").isin(sorted(token_to_cids)),
        )
        term_rows = term_table.to_pylist()
    except Exception as exc:
        return {"checked": 0, "ok": False, "failures": [{"error": str(exc)}], "note": "Could not read BM25 term postings."}

    postings_by_term: dict[str, set[str]] = {}
    for term_row in term_rows:
        term = str(term_row.get("term") or "")
        wanted = token_to_cids.get(term, set())
        postings_by_term[term] = {
            str(posting.get("source_cid") or "")
            for posting in (term_row.get("postings") or [])
            if str(posting.get("source_cid") or "") in wanted
        }

    failures: list[dict[str, Any]] = []
    checked = 0
    for row in sample_rows[:term_sample_size]:
        cid = str(row.get("cid") or "")
        tokens = cid_to_tokens.get(cid, [])
        if not tokens:
            continue
        checked += 1
        if not any(cid in postings_by_term.get(token, set()) for token in tokens):
            failures.append({**_row_ref(row), "probe_tokens": tokens})
    return {"checked": checked, "ok": not failures, "failures": failures[:50]}


def _faiss_probe(vector_dir: Path, vector_rows: list[dict[str, Any]], sample_rows: list[dict[str, Any]], *, sample_size: int) -> dict[str, Any]:
    try:
        import faiss
        import numpy as np
    except Exception as exc:
        return {"checked": 0, "ok": False, "failures": [{"error": str(exc)}], "note": "faiss/numpy unavailable."}

    try:
        index_bytes = (vector_dir / "artifacts/faiss.index").read_bytes()
        index = faiss.deserialize_index(np.frombuffer(index_bytes, dtype="uint8"))
    except Exception as exc:
        return {"checked": 0, "ok": False, "failures": [{"error": str(exc)}], "note": "Could not load FAISS index."}

    source_cids = [str(row.get("source_cid") or "") for row in vector_rows]
    cid_to_pos = {cid: pos for pos, cid in enumerate(source_cids)}
    failures: list[dict[str, Any]] = []
    tie_warnings: list[dict[str, Any]] = []
    checked = 0
    if index.ntotal != len(source_cids):
        failures.append({"error": "FAISS index row count does not match vector mapping.", "index_ntotal": index.ntotal, "mapping_rows": len(source_cids)})
    k = min(50, max(1, index.ntotal))
    for row in sample_rows[:sample_size]:
        cid = str(row.get("cid") or "")
        pos = cid_to_pos.get(cid)
        if pos is None:
            failures.append({**_row_ref(row), "error": "CID missing from vector mapping."})
            continue
        try:
            vector = index.reconstruct(pos)
            query = np.asarray([vector], dtype="float32")
            self_score = float(index.search(query, 1)[0][0][0])
            scores, indices = index.search(query, k)
            top_pos = int(indices[0][0])
            checked += 1
            returned_positions = {int(item) for item in indices[0] if int(item) >= 0}
            if pos in returned_positions:
                if top_pos != pos and len(tie_warnings) < 50:
                    tie_warnings.append(
                        {
                            **_row_ref(row),
                            "expected_position": pos,
                            "top_position": top_pos,
                            "top_cid": source_cids[top_pos],
                            "score": float(scores[0][0]),
                            "note": "Expected CID was returned within top-k; another row tied or nearly tied at top-1.",
                        }
                    )
                continue
            top_score = float(scores[0][0])
            if abs(top_score - self_score) <= 1e-6:
                if len(tie_warnings) < 50:
                    tie_warnings.append(
                        {
                            **_row_ref(row),
                            "expected_position": pos,
                            "top_position": top_pos,
                            "top_cid": source_cids[top_pos],
                            "score": top_score,
                            "note": "Top-k was saturated by equal-score rows; direct CID-to-vector mapping is present.",
                        }
                    )
                continue
            failures.append({**_row_ref(row), "expected_position": pos, "top_position": top_pos, "top_cid": source_cids[top_pos], "score": top_score})
        except Exception as exc:
            failures.append({**_row_ref(row), "error": str(exc)})
    return {"checked": checked, "ok": not failures, "failures": failures[:50], "tie_warnings": tie_warnings}


def _retrieval_validation_report(
    base_dir: Path,
    vector_dir: Path,
    bm25_dir: Path,
    kg_dir: Path,
    articles: list[dict[str, Any]],
    cid_index: list[dict[str, Any]],
    *,
    sample_size: int,
    seed: int,
) -> dict[str, Any]:
    rng = random.Random(seed)
    sample_rows = rng.sample(articles, min(sample_size, len(articles))) if articles else []
    vector_rows = _read_parquet_rows(vector_dir / "parquet/mapping/train-00000-of-00001.parquet", ["source_cid", "law_cid", "record_type", "law_identifier", "article_identifier", "law_status"])
    bm25_rows = _read_parquet_rows(bm25_dir / "parquet/documents/train-00000-of-00001.parquet", ["source_cid", "law_cid", "record_type", "law_identifier", "article_identifier", "law_status"])
    kg_nodes = _read_parquet_rows(kg_dir / "parquet/nodes/train-00000-of-00001.parquet", ["source_cid", "jsonld_id", "record_type", "law_identifier", "article_identifier", "law_status"])
    kg_edges = _read_parquet_rows(kg_dir / "parquet/edges/train-00000-of-00001.parquet", ["source_cid", "target_cid", "law_identifier", "article_identifier"])

    cid_by_cid = {str(row.get("cid") or ""): row for row in cid_index}
    vector_by_cid = {str(row.get("source_cid") or ""): row for row in vector_rows}
    bm25_by_cid = {str(row.get("source_cid") or ""): row for row in bm25_rows}
    kg_node_by_cid = {str(row.get("source_cid") or ""): row for row in kg_nodes}
    kg_edge_by_source = {str(row.get("source_cid") or ""): row for row in kg_edges}

    failures: list[dict[str, Any]] = []
    for row in sample_rows:
        cid = str(row.get("cid") or "")
        law_cid = str(row.get("law_cid") or "")
        row_failures: list[str] = []
        cid_row = cid_by_cid.get(cid)
        vector_row = vector_by_cid.get(cid)
        bm25_row = bm25_by_cid.get(cid)
        kg_node = kg_node_by_cid.get(cid)
        kg_edge = kg_edge_by_source.get(cid)
        if not cid_row or cid_row.get("article_identifier") != row.get("article_identifier"):
            row_failures.append("cid_index")
        if not vector_row or vector_row.get("article_identifier") != row.get("article_identifier"):
            row_failures.append("vector_mapping")
        if not bm25_row or bm25_row.get("article_identifier") != row.get("article_identifier"):
            row_failures.append("bm25_documents")
        if not kg_node or kg_node.get("article_identifier") != row.get("article_identifier") or kg_node.get("jsonld_id") != row.get("content_address"):
            row_failures.append("jsonld_node")
        if not kg_edge or kg_edge.get("target_cid") != law_cid:
            row_failures.append("jsonld_edge")
        if law_cid not in cid_by_cid:
            row_failures.append("parent_law_cid_index")
        for index_name, index_row in [("vector_status", vector_row), ("bm25_status", bm25_row), ("kg_status", kg_node)]:
            if index_row and index_row.get("law_status") != row.get("law_status"):
                row_failures.append(index_name)
        if row_failures:
            failures.append({**_row_ref(row), "failed_checks": row_failures})

    faiss = _faiss_probe(vector_dir, vector_rows, sample_rows, sample_size=min(100, len(sample_rows)))
    bm25_terms = _bm25_term_probe(
        bm25_dir / "parquet/terms/train-00000-of-00001.parquet",
        sample_rows,
        term_sample_size=min(100, len(sample_rows)),
    )
    return {
        "generated_at": _now(),
        "sample_size_requested": sample_size,
        "sample_size": len(sample_rows),
        "seed": seed,
        "row_resolution": {
            "checked": len(sample_rows),
            "ok": not failures,
            "failures": failures[:100],
        },
        "faiss_self_lookup": faiss,
        "bm25_term_posting_lookup": bm25_terms,
        "index_counts": {
            "cid_index": len(cid_index),
            "vector_mapping": len(vector_rows),
            "bm25_documents": len(bm25_rows),
            "kg_nodes": len(kg_nodes),
            "kg_edges": len(kg_edges),
        },
        "ok": not failures and faiss.get("ok") and bm25_terms.get("ok"),
    }


def run_quality_audit(
    *,
    base_dir: Path | None = None,
    vector_dir: Path | None = None,
    bm25_dir: Path | None = None,
    kg_dir: Path | None = None,
    raw_dir: Path | None = None,
    out_dir: Path | None = None,
    sample_size: int = 500,
    seed: int = 42,
) -> dict[str, Any]:
    base_dir = base_dir or HF_DATA_DIR / IPFS_DATASET_NAME
    vector_dir = vector_dir or HF_DATA_DIR / VECTOR_INDEX_DATASET_NAME
    bm25_dir = bm25_dir or HF_DATA_DIR / BM25_INDEX_DATASET_NAME
    kg_dir = kg_dir or HF_DATA_DIR / KNOWLEDGE_GRAPH_DATASET_NAME
    raw_dir = raw_dir or PACKAGE_RAW_OUTPUT_DIR
    out_dir = out_dir or OPERATIONS_DATA_DIR / "quality_audit"
    out_dir.mkdir(parents=True, exist_ok=True)

    laws, articles, cid_index = _read_base_rows(base_dir)
    duplicate_report = _duplicate_report(laws, articles, cid_index)
    parser_noise_report = _parser_noise_report(laws, articles, raw_dir=raw_dir)
    hierarchy_report = _hierarchy_report(articles)
    citation_report = _citation_report(articles)
    status_report = _status_report(laws, articles)
    article_quality = _article_quality(articles)
    packaging_report = _packaging_report(base_dir, laws, articles, cid_index)
    retrieval_report = _retrieval_validation_report(
        base_dir,
        vector_dir,
        bm25_dir,
        kg_dir,
        articles,
        cid_index,
        sample_size=sample_size,
        seed=seed,
    )

    issue_summary = {
        "duplicate_cid_groups": duplicate_report["cids"]["duplicate_cid_groups"],
        "duplicate_law_identifier_groups": duplicate_report["laws"]["duplicate_identifiers"]["group_count"],
        "duplicate_article_identifier_groups": duplicate_report["articles"]["duplicate_identifiers"]["group_count"],
        "duplicate_article_text_groups": duplicate_report["articles"]["duplicate_text_under_different_identifiers"]["group_count"],
        "packaged_parser_noise_occurrences": parser_noise_report["packaged"]["laws"]["total_occurrences"]
        + parser_noise_report["packaged"]["articles"]["total_occurrences"],
        "empty_articles": article_quality["empty_articles"]["count"],
        "suspiciously_short_articles": article_quality["suspiciously_short_articles"]["count"],
        "suspiciously_long_articles": article_quality["suspiciously_long_articles"]["count"],
        "missing_hierarchy_path": hierarchy_report["missing_hierarchy_path"]["count"],
        "missing_article_level": hierarchy_report["missing_article_level"]["count"],
        "citation_reconstruction_mismatches": citation_report["citation_reconstruction_mismatches"]["count"],
        "ambiguous_laws": status_report["ambiguous_laws"]["count"],
        "status_inheritance_drift": status_report["article_status_inheritance_drift"]["count"],
        "retrieval_validation_ok": retrieval_report["ok"],
    }
    quality_report = {
        "generated_at": _now(),
        "source_dirs": {
            "base": str(base_dir),
            "vector": str(vector_dir),
            "bm25": str(bm25_dir),
            "knowledge_graph": str(kg_dir),
            "raw": str(raw_dir),
        },
        "records": {"laws": len(laws), "articles": len(articles), "cid_index": len(cid_index)},
        "issue_summary": issue_summary,
        "article_quality": article_quality,
        "citation_audit": citation_report,
        "status_audit": status_report,
        "packaging_audit": packaging_report,
        "quality_gate_recommendation": {
            "minimum_before_next_large_batch": [
                "duplicate_cid_groups == 0",
                "packaged_parser_noise_occurrences == 0 for known UI chrome phrases",
                "retrieval_validation_ok == true on at least 500 sampled articles",
                "status_inheritance_drift == 0",
                "all citation/hierarchy mismatch categories reviewed or explained",
                "duplicate article text groups reviewed, especially status-only or empty-provision articles",
            ],
            "current_gate_pass": (
                issue_summary["duplicate_cid_groups"] == 0
                and issue_summary["packaged_parser_noise_occurrences"] == 0
                and issue_summary["status_inheritance_drift"] == 0
                and bool(issue_summary["retrieval_validation_ok"])
            ),
        },
    }

    reports = {
        "quality_report": quality_report,
        "duplicate_report": duplicate_report,
        "parser_noise_report": parser_noise_report,
        "hierarchy_report": hierarchy_report,
        "retrieval_validation_report": retrieval_report,
    }
    paths: dict[str, str] = {}
    for name, report in reports.items():
        path = out_dir / f"{name}.json"
        write_json(path, report)
        paths[name] = str(path)

    return {
        "generated_at": _now(),
        "out_dir": str(out_dir),
        "reports": paths,
        "issue_summary": issue_summary,
        "quality_gate_pass": quality_report["quality_gate_recommendation"]["current_gate_pass"],
    }
