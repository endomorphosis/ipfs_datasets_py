from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from .email_corpus import build_email_graphrag_artifacts
from .email_relevance import (
    build_complaint_terms,
    generate_email_search_plan,
    score_email_relevance,
)


def _require_duckdb():
    try:
        import duckdb  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ImportError("duckdb is required for email_agentic_search") from exc
    return duckdb


def _slugify(value: str, *, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip(".-")
    return cleaned[:80] or fallback


def _normalize_items(values: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        value = str(item or "").strip()
        lowered = value.lower()
        if not value or lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(value)
    return normalized


def _normalize_subject_for_thread(subject: str) -> str:
    cleaned = str(subject or "").strip()
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = re.sub(r"^(?:re|fw|fwd)\s*:\s*", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned or "untitled-email-thread"


def _parse_email_datetime(value: Any) -> tuple[str, datetime | None]:
    raw = str(value or "").strip()
    if not raw:
        return "", None
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat(), parsed.astimezone(UTC)
    except Exception:
        return raw, None


def _resolve_messages_parquet_path(index_path: str | Path) -> Path:
    path = Path(index_path).expanduser().resolve()
    if path.is_dir():
        candidate = path / "email_messages.parquet"
        if candidate.exists():
            return candidate
    if path.suffix.lower() == ".parquet" and path.exists():
        return path
    if path.suffix.lower() == ".duckdb":
        candidate = path.parent / "email_messages.parquet"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Could not resolve email_messages.parquet from {path}")


def _resolve_output_dir(index_path: str | Path, output_dir: str | Path | None) -> Path:
    if output_dir is not None:
        return Path(output_dir).expanduser().resolve()
    return _resolve_messages_parquet_path(index_path).parent / "agentic_email_search"


def _load_candidate_rows(
    *,
    messages_parquet_path: Path,
    search_phrases: Sequence[str],
) -> list[dict[str, Any]]:
    duckdb = _require_duckdb()
    parquet_literal = str(messages_parquet_path).replace("'", "''")
    relation = f"read_parquet('{parquet_literal}')"
    conn = duckdb.connect()
    try:
        clauses: list[str] = []
        params: list[str] = []
        for phrase in search_phrases:
            clauses.append(
                "("
                "lower(coalesce(subject,'')) LIKE '%' || lower(?) || '%' "
                "OR lower(coalesce(sender,'')) LIKE '%' || lower(?) || '%' "
                "OR lower(coalesce(recipient,'')) LIKE '%' || lower(?) || '%' "
                "OR lower(coalesce(cc,'')) LIKE '%' || lower(?) || '%' "
                "OR lower(coalesce(participants_json,'')) LIKE '%' || lower(?) || '%' "
                "OR lower(coalesce(corpus_text,'')) LIKE '%' || lower(?) || '%'"
                ")"
            )
            params.extend([phrase, phrase, phrase, phrase, phrase, phrase])
        where_clause = " OR ".join(clauses) if clauses else "TRUE"
        rows = conn.execute(
            f"""
            SELECT
                message_key,
                subject,
                sender,
                recipient,
                cc,
                date,
                message_id_header,
                bundle_dir,
                eml_path,
                metadata_path,
                raw_size_bytes,
                relevance_score,
                attachment_paths_json,
                participants_json,
                corpus_text
            FROM {relation}
            WHERE {where_clause}
            """,
            params,
        ).fetchall()
    finally:
        conn.close()
    payloads: list[dict[str, Any]] = []
    for row in rows:
        payloads.append(
            {
                "message_key": str(row[0] or ""),
                "subject": str(row[1] or ""),
                "sender": str(row[2] or ""),
                "recipient": str(row[3] or ""),
                "cc": str(row[4] or ""),
                "date": str(row[5] or ""),
                "message_id_header": str(row[6] or ""),
                "bundle_dir": str(row[7] or ""),
                "eml_path": str(row[8] or ""),
                "metadata_path": str(row[9] or ""),
                "raw_size_bytes": int(row[10] or 0),
                "relevance_score": float(row[11] or 0.0),
                "attachment_paths": json.loads(str(row[12] or "[]")),
                "participants": json.loads(str(row[13] or "[]")),
                "corpus_text": str(row[14] or ""),
            }
        )
    return payloads


def _seed_match_score(row: dict[str, Any], seed_phrases: Sequence[str]) -> tuple[float, list[str]]:
    subject = str(row.get("subject") or "").lower()
    sender = str(row.get("sender") or "").lower()
    recipient = str(row.get("recipient") or "").lower()
    cc = str(row.get("cc") or "").lower()
    participants = " ".join(str(item or "").lower() for item in list(row.get("participants") or []))
    corpus = str(row.get("corpus_text") or "").lower()
    score = 0.0
    matched: list[str] = []
    for phrase in seed_phrases:
        lowered = str(phrase or "").strip().lower()
        if not lowered:
            continue
        phrase_score = 0.0
        if lowered in subject:
            phrase_score += 8.0
        if lowered in sender or lowered in recipient or lowered in cc:
            phrase_score += 5.0
        if lowered in participants:
            phrase_score += 5.0
        if lowered in corpus:
            phrase_score += 2.0
        if phrase_score > 0:
            score += phrase_score
            matched.append(phrase)
    return score, matched


def _row_text_fields(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    sender = str(row.get("sender") or "").lower()
    recipient = str(row.get("recipient") or "").lower()
    cc = str(row.get("cc") or "").lower()
    participants = " ".join(str(item or "").lower() for item in list(row.get("participants") or []))
    corpus = str(row.get("corpus_text") or "").lower()
    return sender, recipient, cc, participants, corpus


def _row_matches_required_domains(row: dict[str, Any], required_participant_domains: Sequence[str]) -> bool:
    if not required_participant_domains:
        return True
    sender, recipient, cc, participants, corpus = _row_text_fields(row)
    haystacks = [sender, recipient, cc, participants, corpus]
    for domain in required_participant_domains:
        lowered = str(domain or "").strip().lower().lstrip("@")
        if not lowered:
            continue
        if any(lowered in haystack for haystack in haystacks):
            return True
    return False


def _build_ranked_hits(
    *,
    candidate_rows: Sequence[dict[str, Any]],
    complaint_terms: Sequence[str],
    seed_phrases: Sequence[str],
    required_participant_domains: Sequence[str],
    min_seed_phrase_matches: int,
    result_limit: int,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for row in candidate_rows:
        attachment_names = [Path(item).name for item in list(row.get("attachment_paths") or [])]
        complaint_relevance = score_email_relevance(
            complaint_terms=complaint_terms,
            subject=str(row.get("subject") or ""),
            sender=str(row.get("sender") or ""),
            recipient=str(row.get("recipient") or ""),
            cc=str(row.get("cc") or ""),
            body_text=str(row.get("corpus_text") or ""),
            attachment_names=attachment_names,
        )
        seed_score, matched_seed_phrases = _seed_match_score(row, seed_phrases)
        if len(matched_seed_phrases) < max(1, int(min_seed_phrase_matches or 1)):
            continue
        if not _row_matches_required_domains(row, required_participant_domains):
            continue
        iso_date, parsed_dt = _parse_email_datetime(row.get("date"))
        thread_subject = _normalize_subject_for_thread(str(row.get("subject") or ""))
        total_score = float(row.get("relevance_score") or 0.0) + float(complaint_relevance["score"]) + float(seed_score)
        ranked.append(
            {
                **row,
                "thread_subject": thread_subject,
                "email_date_iso": iso_date,
                "email_date_sort": parsed_dt.timestamp() if parsed_dt is not None else 0.0,
                "complaint_relevance_score": float(complaint_relevance["score"]),
                "complaint_matched_terms": list(complaint_relevance["matched_terms"]),
                "complaint_matched_fields": list(complaint_relevance["matched_fields"]),
                "seed_match_score": float(seed_score),
                "matched_seed_phrases": matched_seed_phrases,
                "agentic_score": float(total_score),
            }
        )
    ranked.sort(
        key=lambda item: (
            -float(item.get("agentic_score") or 0.0),
            -float(item.get("email_date_sort") or 0.0),
            str(item.get("subject") or ""),
        )
    )
    return ranked[: max(1, int(result_limit or 1))]


def _summarize_chains(hits: Sequence[dict[str, Any]], *, chain_limit: int) -> list[dict[str, Any]]:
    chains: dict[str, dict[str, Any]] = {}
    for hit in hits:
        key = str(hit.get("thread_subject") or "untitled-email-thread")
        chain = chains.setdefault(
            key,
            {
                "thread_subject": key,
                "email_count": 0,
                "participants": set(),
                "senders": set(),
                "first_date_iso": "",
                "last_date_iso": "",
                "top_agentic_score": 0.0,
                "matched_seed_phrases": set(),
                "sample_eml_paths": [],
            },
        )
        chain["email_count"] += 1
        chain["participants"].update(list(hit.get("participants") or []))
        sender = str(hit.get("sender") or "").strip()
        if sender:
            chain["senders"].add(sender)
        chain["matched_seed_phrases"].update(list(hit.get("matched_seed_phrases") or []))
        chain["top_agentic_score"] = max(float(chain["top_agentic_score"] or 0.0), float(hit.get("agentic_score") or 0.0))
        if hit.get("eml_path") and len(chain["sample_eml_paths"]) < 3:
            chain["sample_eml_paths"].append(str(hit.get("eml_path")))
        hit_date = str(hit.get("email_date_iso") or "")
        if hit_date:
            if not chain["first_date_iso"] or hit_date < chain["first_date_iso"]:
                chain["first_date_iso"] = hit_date
            if not chain["last_date_iso"] or hit_date > chain["last_date_iso"]:
                chain["last_date_iso"] = hit_date
    summarized: list[dict[str, Any]] = []
    for chain in chains.values():
        summarized.append(
            {
                "thread_subject": chain["thread_subject"],
                "email_count": int(chain["email_count"] or 0),
                "participants": sorted(chain["participants"]),
                "senders": sorted(chain["senders"]),
                "first_date_iso": chain["first_date_iso"],
                "last_date_iso": chain["last_date_iso"],
                "top_agentic_score": float(chain["top_agentic_score"] or 0.0),
                "matched_seed_phrases": sorted(chain["matched_seed_phrases"]),
                "sample_eml_paths": list(chain["sample_eml_paths"]),
            }
        )
    summarized.sort(
        key=lambda item: (
            -int(item.get("email_count") or 0),
            -float(item.get("top_agentic_score") or 0.0),
            str(item.get("last_date_iso") or ""),
        )
    )
    return summarized[: max(1, int(chain_limit or 1))]


def _build_timeline_candidates(hits: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    for hit in sorted(hits, key=lambda item: (float(item.get("email_date_sort") or 0.0), str(item.get("subject") or ""))):
        summary = (
            f"{str(hit.get('sender') or '').strip()} sent '{str(hit.get('subject') or '').strip()}' "
            f"to {str(hit.get('recipient') or '').strip()}."
        ).strip()
        timeline.append(
            {
                "event_type": "email_chain_event",
                "thread_subject": str(hit.get("thread_subject") or ""),
                "subject": str(hit.get("subject") or ""),
                "email_date": str(hit.get("date") or ""),
                "email_date_iso": str(hit.get("email_date_iso") or ""),
                "sender": str(hit.get("sender") or ""),
                "recipient": str(hit.get("recipient") or ""),
                "participants": list(hit.get("participants") or []),
                "summary": summary,
                "matched_seed_phrases": list(hit.get("matched_seed_phrases") or []),
                "agentic_score": float(hit.get("agentic_score") or 0.0),
                "eml_path": str(hit.get("eml_path") or ""),
                "metadata_path": str(hit.get("metadata_path") or ""),
            }
        )
    return timeline


def search_email_corpus_agentic(
    *,
    index_path: str | Path,
    complaint_query: str = "",
    complaint_keywords: Sequence[str] = (),
    seed_terms: Sequence[str] = (),
    seed_participants: Sequence[str] = (),
    required_participant_domains: Sequence[str] = (),
    min_seed_phrase_matches: int = 1,
    result_limit: int = 150,
    chain_limit: int = 20,
    output_dir: str | Path | None = None,
    emit_graphrag: bool = True,
) -> dict[str, Any]:
    messages_parquet_path = _resolve_messages_parquet_path(index_path)
    output_root = _resolve_output_dir(index_path, output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    search_plan = generate_email_search_plan(
        complaint_query=complaint_query,
        complaint_keywords=complaint_keywords,
        addresses=seed_participants,
    )
    complaint_terms = build_complaint_terms(
        complaint_query=complaint_query,
        complaint_keywords=complaint_keywords,
    )
    seed_phrases = _normalize_items(
        [
            complaint_query,
            *complaint_keywords,
            *seed_terms,
            *seed_participants,
            *list(search_plan.get("recommended_subject_phrases") or []),
            *list(search_plan.get("recommended_subject_terms") or [])[:12],
        ]
    )
    candidate_rows = _load_candidate_rows(messages_parquet_path=messages_parquet_path, search_phrases=seed_phrases)
    ranked_hits = _build_ranked_hits(
        candidate_rows=candidate_rows,
        complaint_terms=complaint_terms,
        seed_phrases=seed_phrases,
        required_participant_domains=_normalize_items(required_participant_domains),
        min_seed_phrase_matches=int(min_seed_phrase_matches or 1),
        result_limit=result_limit,
    )
    chain_summaries = _summarize_chains(ranked_hits, chain_limit=chain_limit)
    timeline_candidates = _build_timeline_candidates(ranked_hits)

    hits_path = output_root / "matched_emails.json"
    chains_path = output_root / "chain_summaries.json"
    timeline_path = output_root / "timeline_candidates.json"
    hits_path.write_text(json.dumps(ranked_hits, indent=2, ensure_ascii=False), encoding="utf-8")
    chains_path.write_text(json.dumps(chain_summaries, indent=2, ensure_ascii=False), encoding="utf-8")
    timeline_path.write_text(json.dumps(timeline_candidates, indent=2, ensure_ascii=False), encoding="utf-8")

    graphrag_summary: dict[str, Any] | None = None
    focused_manifest_path: Path | None = None
    if emit_graphrag and ranked_hits:
        focused_manifest_path = output_root / "focused_email_manifest.json"
        focused_manifest_payload = {
            "status": "success",
            "email_count": len(ranked_hits),
            "emails": [
                {
                    "subject": str(hit.get("subject") or ""),
                    "from": str(hit.get("sender") or ""),
                    "to": str(hit.get("recipient") or ""),
                    "cc": str(hit.get("cc") or ""),
                    "date": str(hit.get("date") or ""),
                    "participants": list(hit.get("participants") or []),
                    "message_id_header": str(hit.get("message_id_header") or ""),
                    "bundle_dir": str(hit.get("bundle_dir") or ""),
                    "attachment_paths": list(hit.get("attachment_paths") or []),
                    "relevance_score": float(hit.get("agentic_score") or 0.0),
                    "matched_terms": list(hit.get("complaint_matched_terms") or []),
                    "matched_fields": list(hit.get("complaint_matched_fields") or []),
                    "eml_path": str(hit.get("eml_path") or ""),
                    "metadata_path": str(hit.get("metadata_path") or ""),
                }
                for hit in ranked_hits
            ],
        }
        focused_manifest_path.write_text(json.dumps(focused_manifest_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        graphrag_summary = build_email_graphrag_artifacts(
            manifest_path=focused_manifest_path,
            output_dir=output_root / "graphrag",
            emit_duckdb_index=False,
            append_duckdb_index=False,
        )

    summary = {
        "status": "success",
        "index_path": str(Path(index_path).expanduser().resolve()),
        "messages_parquet_path": str(messages_parquet_path),
        "output_dir": str(output_root),
        "complaint_query": str(complaint_query or "").strip(),
        "complaint_terms": complaint_terms,
        "seed_phrases": seed_phrases,
        "required_participant_domains": _normalize_items(required_participant_domains),
        "min_seed_phrase_matches": int(min_seed_phrase_matches or 1),
        "candidate_count": len(candidate_rows),
        "result_count": len(ranked_hits),
        "chain_count": len(chain_summaries),
        "timeline_candidate_count": len(timeline_candidates),
        "matched_emails_path": str(hits_path),
        "chain_summaries_path": str(chains_path),
        "timeline_candidates_path": str(timeline_path),
        "focused_manifest_path": str(focused_manifest_path) if focused_manifest_path is not None else "",
        "graphrag_summary": graphrag_summary,
        "top_threads": [
            {
                "thread_subject": item.get("thread_subject"),
                "email_count": item.get("email_count"),
                "first_date_iso": item.get("first_date_iso"),
                "last_date_iso": item.get("last_date_iso"),
            }
            for item in chain_summaries[:5]
        ],
    }
    summary_path = output_root / "agentic_email_search_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary


__all__ = ["search_email_corpus_agentic"]
