"""Complaint-oriented email relevance helpers."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_QUERY_TERMS: tuple[str, ...] = (
    "termination",
    "eviction",
    "hearing",
    "grievance",
    "appeal",
    "retaliation",
    "accommodation",
    "notice",
    "denial",
    "review",
)


def tokenize_relevance_text(value: str) -> list[str]:
    return [token for token in re.findall(r"[A-Za-z0-9]+", str(value or "").lower()) if len(token) >= 3]


def load_keyword_lines(raw_keywords: Iterable[str], keyword_files: Iterable[str]) -> list[str]:
    values = [str(item or "").strip() for item in raw_keywords if str(item or "").strip()]
    for file_path in keyword_files:
        path = Path(file_path).expanduser().resolve()
        values.extend(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    return values


def build_complaint_terms(
    *,
    complaint_query: str | None = None,
    complaint_keywords: Sequence[str] = (),
    complaint_keyword_files: Sequence[str] = (),
) -> list[str]:
    terms = tokenize_relevance_text(str(complaint_query or ""))
    for keyword in load_keyword_lines(complaint_keywords, complaint_keyword_files):
        terms.extend(tokenize_relevance_text(keyword))
    if not terms and complaint_query:
        terms.extend(DEFAULT_QUERY_TERMS)
    counts = Counter(terms)
    return [term for term, _count in counts.most_common()]


def collect_email_relevance_text(
    *,
    subject: str = "",
    sender: str = "",
    recipient: str = "",
    cc: str = "",
    reply_to: str = "",
    body_text: str = "",
    attachment_names: Sequence[str] = (),
) -> dict[str, str]:
    return {
        "subject": str(subject or ""),
        "headers": "\n".join(part for part in (sender, recipient, cc, reply_to) if str(part or "").strip()),
        "body": str(body_text or ""),
        "attachments": "\n".join(str(item or "") for item in attachment_names if str(item or "").strip()),
    }


def score_email_relevance(
    *,
    complaint_terms: Sequence[str],
    subject: str = "",
    sender: str = "",
    recipient: str = "",
    cc: str = "",
    reply_to: str = "",
    body_text: str = "",
    attachment_names: Sequence[str] = (),
) -> dict[str, Any]:
    if not complaint_terms:
        return {"score": 0.0, "matched_terms": [], "matched_fields": []}

    collected = collect_email_relevance_text(
        subject=subject,
        sender=sender,
        recipient=recipient,
        cc=cc,
        reply_to=reply_to,
        body_text=body_text,
        attachment_names=attachment_names,
    )
    field_weights = {
        "subject": 3.0,
        "attachments": 2.0,
        "body": 1.0,
        "headers": 0.5,
    }
    matched_terms: list[str] = []
    matched_fields: list[str] = []
    score = 0.0
    for field_name, text in collected.items():
        tokens = set(tokenize_relevance_text(text))
        field_matches = [term for term in complaint_terms if term in tokens]
        if not field_matches:
            continue
        score += len(field_matches) * field_weights[field_name]
        matched_terms.extend(term for term in field_matches if term not in matched_terms)
        matched_fields.append(field_name)
    return {
        "score": float(score),
        "matched_terms": matched_terms,
        "matched_fields": matched_fields,
    }


def generate_email_search_plan(
    *,
    complaint_query: str | None = None,
    complaint_keywords: Sequence[str] = (),
    complaint_keyword_files: Sequence[str] = (),
    addresses: Sequence[str] = (),
    date_after: str | None = None,
    date_before: str | None = None,
    max_subject_terms: int = 6,
) -> dict[str, Any]:
    complaint_terms = build_complaint_terms(
        complaint_query=complaint_query,
        complaint_keywords=complaint_keywords,
        complaint_keyword_files=complaint_keyword_files,
    )
    subject_terms = [term for term in complaint_terms if len(term) >= 5][:max_subject_terms]
    recommended_subject_phrases = [
        " ".join(subject_terms[index : index + 2]).strip()
        for index in range(0, min(len(subject_terms), max_subject_terms), 2)
        if " ".join(subject_terms[index : index + 2]).strip()
    ]
    address_filters = [str(value or "").strip().lower() for value in addresses if str(value or "").strip()]
    return {
        "complaint_query": str(complaint_query or "").strip(),
        "complaint_terms": complaint_terms,
        "address_filters": address_filters,
        "date_after": str(date_after or "").strip(),
        "date_before": str(date_before or "").strip(),
        "recommended_subject_terms": subject_terms,
        "recommended_subject_phrases": recommended_subject_phrases,
        "recommended_cli_flags": {
            "complaint_query": str(complaint_query or "").strip(),
            "complaint_keywords": list(complaint_keywords),
            "address_filters": address_filters,
            "date_after": str(date_after or "").strip(),
            "date_before": str(date_before or "").strip(),
        },
        "scoring_weights": {
            "subject": 3.0,
            "attachments": 2.0,
            "body": 1.0,
            "headers": 0.5,
        },
    }


__all__ = [
    "DEFAULT_QUERY_TERMS",
    "build_complaint_terms",
    "collect_email_relevance_text",
    "generate_email_search_plan",
    "load_keyword_lines",
    "score_email_relevance",
    "tokenize_relevance_text",
]
