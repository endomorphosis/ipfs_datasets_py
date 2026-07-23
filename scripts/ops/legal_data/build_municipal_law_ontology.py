#!/usr/bin/env python3
"""Build an LLM-assisted municipal-law ontology artifact."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pyarrow.parquet as pq  # noqa: E402

from ipfs_datasets_py.processors.legal_scrapers.municipal_law_ontology import (  # noqa: E402
    build_base_municipal_ontology,
    extract_json_object,
    merge_llm_ontology_extensions,
)


def _row_score(row: Dict[str, Any]) -> int:
    text = str(row.get("text") or "")
    signals = (
        "shall",
        "must",
        "may",
        "permit",
        "license",
        "appeal",
        "employee",
        "worker",
        "owner",
        "applicant",
        "means",
        "violation",
        "penalty",
    )
    return len(text) + sum(250 for signal in signals if signal in text.lower())


def _sample_rows(rows: List[Dict[str, Any]], max_rows: int, max_chars: int) -> List[Dict[str, str]]:
    ranked = sorted(rows, key=_row_score, reverse=True)[: max(1, int(max_rows or 1))]
    out: List[Dict[str, str]] = []
    for row in ranked:
        out.append(
            {
                "ipfs_cid": str(row.get("ipfs_cid") or ""),
                "identifier": str(row.get("identifier") or row.get("official_cite") or ""),
                "title": str(row.get("title") or row.get("name") or ""),
                "text": str(row.get("text") or "")[: max(500, int(max_chars or 2500))],
            }
        )
    return out


def _aggregate_bm25_terms(path: str, *, top_k: int) -> List[Dict[str, int]]:
    if not str(path or "").strip():
        return []
    table = pq.read_table(Path(path).expanduser(), columns=["term_frequencies"])
    tf: Counter[str] = Counter()
    df: Counter[str] = Counter()
    for row in table.to_pylist():
        seen: set[str] = set()
        for item in list(row.get("term_frequencies") or []):
            if not isinstance(item, dict):
                continue
            term = str(item.get("term") or "").strip().lower()
            if not term:
                continue
            try:
                count = int(item.get("tf") or 0)
            except Exception:
                count = 0
            if count <= 0:
                continue
            tf[term] += count
            seen.add(term)
        df.update(seen)

    stop_terms = {
        "the", "of", "and", "or", "to", "a", "in", "for", "by", "is", "be", "as", "this", "that",
        "with", "on", "from", "any", "all", "an", "are", "not", "shall", "must", "may", "will",
        "city", "code", "section", "chapter", "title", "portland", "oregon", "label", "effective",
        "ordinance", "amended", "b", "c", "d", "e", "s", "1", "2", "3", "4", "5", "6", "10",
    }
    terms: List[Dict[str, int]] = []
    for term, count in tf.most_common(max(1, int(top_k or 200)) * 3):
        if term in stop_terms or len(term) < 3:
            continue
        terms.append({"term": term, "tf": int(count), "df": int(df[term])})
        if len(terms) >= max(1, int(top_k or 200)):
            break
    return terms


def _build_prompt(base: Dict[str, Any], samples: List[Dict[str, str]], bm25_terms: List[Dict[str, int]]) -> str:
    allowed_classes = [str(item.get("id") or "") for item in list(base.get("classes") or [])]
    return (
        "Return strict JSON only. You are designing a municipal-code ontology for knowledge graphs, "
        "frame logic, deontic logic, temporal deontic FOL, and permit/workflow reasoning.\n"
        "Given the base ontology and Portland code samples, propose conservative extensions only when useful.\n"
        "Do not duplicate existing terms. Do not invent facts. Prefer reusable role and subject terms.\n"
        "Allowed top-level keys: classes, predicates, actor_lexicon, subject_lexicon, rationale.\n"
        "classes: array of {id,label,parent}; parent must be one of the existing class IDs.\n"
        "predicates: array of {id,domain,range,flogic}; id must be uppercase snake case.\n"
        "actor_lexicon and subject_lexicon: object mapping lowercase phrase to an existing or proposed class id.\n"
        f"Existing class IDs: {allowed_classes}\n"
        f"Base actor lexicon: {json.dumps(base.get('actor_lexicon'), sort_keys=True)}\n"
        f"Base subject lexicon: {json.dumps(base.get('subject_lexicon'), sort_keys=True)}\n"
        "Full-corpus BM25 bag-of-words vocabulary sample, sorted by corpus frequency. "
        "Use these terms to identify missing actor, regulated-subject, process, instrument, sanction, temporal, or public-service concepts. "
        "Ignore generic function words and section-number artifacts.\n"
        f"{json.dumps(bm25_terms, ensure_ascii=False)}\n"
        "Portland code samples:\n"
        f"{json.dumps(samples, ensure_ascii=False)}\n"
    )


def _derive_with_llm(prompt: str, *, provider: str, model_name: str, max_tokens: int) -> Dict[str, Any]:
    from ipfs_datasets_py.llm_router import generate_text, get_last_generation_trace

    raw = generate_text(
        prompt,
        provider=provider or None,
        model_name=model_name or None,
        temperature=0.0,
        max_new_tokens=int(max_tokens or 1200),
        max_tokens=int(max_tokens or 1200),
        allow_local_fallback=False,
        disable_model_retry=True,
    )
    payload = extract_json_object(str(raw or "")) or {}
    payload["_llm_trace"] = get_last_generation_trace()
    payload["_raw_preview"] = str(raw or "")[:500]
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build municipal-law ontology JSON artifact.")
    parser.add_argument("--input", required=True, help="Canonical municipal parquet.")
    parser.add_argument("--output", required=True, help="Ontology JSON output path.")
    parser.add_argument("--bm25-input", default="", help="Optional BM25 bag-of-words parquet used for corpus-wide ontology term review.")
    parser.add_argument("--bm25-top-k", type=int, default=220, help="Top BM25 terms sent to LLM.")
    parser.add_argument("--provider", default="codex_cli", help="llm_router provider.")
    parser.add_argument("--model", default="gpt-5.3-codex-spark", help="llm_router model.")
    parser.add_argument("--max-rows", type=int, default=24, help="Sample rows sent to LLM.")
    parser.add_argument("--max-chars", type=int, default=2200, help="Max chars per sample.")
    parser.add_argument("--max-tokens", type=int, default=1600, help="LLM output token budget.")
    parser.add_argument("--no-llm", action="store_true", help="Write base ontology without LLM extension.")
    parser.add_argument("--json", action="store_true", help="Print summary JSON.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    rows = pq.read_table(Path(args.input).expanduser()).to_pylist()
    base = build_base_municipal_ontology()
    samples = _sample_rows(rows, max_rows=int(args.max_rows), max_chars=int(args.max_chars))
    bm25_terms = _aggregate_bm25_terms(str(args.bm25_input or ""), top_k=int(args.bm25_top_k))
    llm_payload: Dict[str, Any] = {}
    if not args.no_llm:
        llm_payload = _derive_with_llm(
            _build_prompt(base, samples, bm25_terms),
            provider=str(args.provider or ""),
            model_name=str(args.model or ""),
            max_tokens=int(args.max_tokens),
        )
    extension = {k: v for k, v in llm_payload.items() if not str(k).startswith("_")}
    ontology = merge_llm_ontology_extensions(base, extension)
    ontology["source_corpus"] = str(Path(args.input).expanduser().resolve())
    ontology["bm25_source"] = str(Path(args.bm25_input).expanduser().resolve()) if str(args.bm25_input or "").strip() else ""
    ontology["bm25_review_term_count"] = len(bm25_terms)
    ontology["bm25_review_terms"] = bm25_terms
    ontology["sample_count"] = len(samples)
    ontology["llm_derivation"] = {
        "enabled": not bool(args.no_llm),
        "provider": str(args.provider or ""),
        "model": str(args.model or ""),
        "trace": llm_payload.get("_llm_trace", {}),
        "raw_preview": llm_payload.get("_raw_preview", ""),
        "rationale": llm_payload.get("rationale", ""),
    }
    out_path = Path(args.output).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ontology, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")
    summary = {
        "output": str(out_path.resolve()),
        "classes": len(ontology.get("classes") or []),
        "predicates": len(ontology.get("predicates") or []),
        "actor_terms": len(ontology.get("actor_lexicon") or {}),
        "subject_terms": len(ontology.get("subject_lexicon") or {}),
        "llm_extension": ontology.get("llm_extension"),
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
