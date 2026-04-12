from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"[A-Za-z0-9]+", str(text or "").lower()) if len(token) >= 4]


EMAIL_FOCUSED_TERMS = {
    "notice": 4,
    "letter": 3,
    "email": 3,
    "message": 3,
    "portal": 2,
    "hearing": 4,
    "grievance": 4,
    "appeal": 4,
    "review": 3,
    "decision": 4,
    "denial": 4,
    "termination": 4,
    "response": 4,
    "respond": 3,
    "timeline": 3,
    "chronology": 3,
    "date": 3,
    "dates": 3,
    "request": 3,
    "informal": 2,
    "follow": 2,
    "staff": 2,
    "title": 2,
    "sent": 2,
    "received": 2,
}


def build_email_seed_plan(
    *,
    complaint_package_path: str | Path,
    worksheet_path: str | Path,
) -> dict[str, Any]:
    package = _load_json(complaint_package_path)
    worksheet = _load_json(worksheet_path)

    summary = str(package.get("summary") or worksheet.get("summary") or "").strip()
    factual_allegations = [str(item or "").strip() for item in list(package.get("factual_allegations") or []) if str(item or "").strip()]
    supporting_evidence = [str(item or "").strip() for item in list(package.get("supporting_evidence") or []) if str(item or "").strip()]
    outstanding_gaps = [str(item or "").strip() for item in list(worksheet.get("outstanding_intake_gaps") or []) if str(item or "").strip()]
    follow_up_items = [dict(item) for item in list(worksheet.get("follow_up_items") or []) if isinstance(item, dict)]

    weighted_terms: dict[str, int] = {}
    for term, weight in EMAIL_FOCUSED_TERMS.items():
        weighted_terms[term] = weight

    def _bump(text: str, base_weight: int = 1) -> None:
        lowered = str(text or "").lower()
        for token in _tokenize(lowered):
            if token in EMAIL_FOCUSED_TERMS:
                weighted_terms[token] = weighted_terms.get(token, 0) + base_weight + EMAIL_FOCUSED_TERMS[token]
        for phrase in ("hearing request", "informal review", "final decision", "written notice", "review request"):
            if phrase in lowered:
                for token in _tokenize(phrase):
                    weighted_terms[token] = weighted_terms.get(token, 0) + base_weight + 4

    _bump(summary, 1)
    for line in factual_allegations:
        _bump(line, 2)
    for line in supporting_evidence:
        _bump(line, 2)
    for line in outstanding_gaps:
        _bump(line, 3)
    for item in follow_up_items:
        _bump(str(item.get("objective") or ""), 2)
        _bump(str(item.get("question") or ""), 4)
        _bump(str(item.get("gap") or ""), 3)

    ranked_terms = [term for term, _score in sorted(weighted_terms.items(), key=lambda item: (-item[1], item[0]))]
    top_terms = ranked_terms[:12]
    subject_phrases = []
    for phrase in (
        "written notice",
        "hearing request",
        "informal review",
        "review decision",
        "final decision",
        "response letter",
    ):
        if all(token in weighted_terms for token in _tokenize(phrase)):
            subject_phrases.append(phrase)
    if not subject_phrases:
        for index in range(0, min(len(top_terms), 6), 2):
            phrase = " ".join(top_terms[index : index + 2]).strip()
            if phrase:
                subject_phrases.append(phrase)

    complaint_query = " ".join(top_terms[:10]).strip()
    target_artifacts = [
        "written notice",
        "hearing request email or letter",
        "review or appeal response",
        "final decision notice",
        "follow-up asking for response",
        "messages naming staff or decision-makers",
    ]
    return {
        "summary": summary,
        "outstanding_intake_gaps": outstanding_gaps,
        "blocker_objectives": [str(item.get("objective") or "").strip() for item in follow_up_items if str(item.get("objective") or "").strip()],
        "complaint_email_query": complaint_query,
        "complaint_email_keywords": top_terms,
        "recommended_subject_phrases": subject_phrases[:6],
        "target_artifacts": target_artifacts,
        "follow_up_questions": [
            str(item.get("question") or "").strip()
            for item in follow_up_items
            if str(item.get("question") or "").strip()
        ],
    }


__all__ = ["build_email_seed_plan"]
