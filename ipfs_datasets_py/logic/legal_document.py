"""Segment a legal instrument and classify operative numeric patterns.

A statute, a contract, and any other text use the same path. Clause edges
are data on the document. This module does not emit Lean and does not treat
a deontic result or a Legal IR receipt as proved.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable


_MODAL = re.compile(r"\b(?:shall|must|may|required)\b", re.I)
_TOKEN = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)?|\d+")
_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12,
}
_UNITS = {
    "dollar": "money", "dollars": "money", "day": "day", "days": "day",
    "year": "year", "years": "year",
}
_EXTRA = frozenset({"additional", "fee", "penalty", "surcharge"})
_CEILING = re.compile(
    r"\b(?:more than|no more than|not exceeding|exceeding|at most|within|less than|longer\b.{0,40}\bthan)\b",
    re.I,
)
_MINIMUM = re.compile(r"\b(?:attained|at least|or older|not less than|no less than|minimum)\b", re.I)
_DATE_DAY = re.compile(r"\bday of\b", re.I)
Segmenter = Callable[[str], list[str]]


@dataclass
class Hit:
    value: int
    unit: str
    index: int
    after: bool
    extra: bool


@dataclass
class Clause:
    id: str
    text: str
    start: int
    end: int
    disposition: str = "pending"
    reason: str = ""
    pattern: dict[str, Any] | None = None
    error: str = ""
    source_selector: dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    id: str
    text: str
    jurisdiction: str
    document_type: str
    clauses: list[Clause] = field(default_factory=list)
    edges: list[dict[str, str]] = field(default_factory=list)


def segment_paragraphs(text: str) -> list[str]:
    """Split on blank lines and on a short heading. Does not interpret the text."""

    chunks: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            chunks.append(body)
        buf.clear()

    for line in str(text or "").splitlines():
        if not line.strip():
            flush()
            continue
        if buf and _heading(line):
            flush()
        buf.append(line)
    flush()
    sentences: list[str] = []
    for chunk in chunks:
        sentences.extend(_split_sentences(chunk))
    return _merge_amount_pairs(sentences)


def _split_sentences(chunk: str) -> list[str]:
    stripped = chunk.strip()
    if _heading(stripped) and "\n" not in stripped:
        return [stripped]
    flat = re.sub(r"[ \t]+", " ", chunk).replace("\n", " ")
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", flat) if part.strip()]
    return parts or [stripped]


def _merge_amount_pairs(parts: list[str]) -> list[str]:
    """Join two adjacent sentences only when together they are one fee-after-day rule."""

    merged: list[str] = []
    index = 0
    while index < len(parts):
        if index + 1 < len(parts):
            both = classify_clause(parts[index] + " " + parts[index + 1])
            left = classify_clause(parts[index])
            right = classify_clause(parts[index + 1])
            pattern = both.get("pattern") or {}
            if pattern.get("kind") == "amount" and left.get("disposition") != "pending" and right.get("disposition") != "pending":
                merged.append(parts[index] + " " + parts[index + 1])
                index += 2
                continue
        merged.append(parts[index])
        index += 1
    return merged


def _heading(line: str) -> bool:
    stripped = line.strip()
    words = stripped.split()
    if not words or len(words) > 6 or len(stripped) > 60 or not stripped[0].isupper():
        return False
    if _MODAL.search(stripped):
        return False
    if stripped[-1] not in ".;,:":
        return True
    return all(re.fullmatch(r"[A-Z0-9IVXLC]+[.)]?", word) or word.endswith(".") for word in words)


def _parse_number(tokens: list[str], index: int) -> tuple[int, int] | None:
    token = tokens[index].lower()
    if "-" in token:
        parts = token.split("-")
        if len(parts) == 2 and parts[0] in _TENS and parts[1] in _ONES:
            return _TENS[parts[0]] + _ONES[parts[1]], index + 1
    if token.isdigit():
        return int(token), index + 1
    if token in _ORDINALS:
        return _ORDINALS[token], index + 1
    if token in _ONES:
        if index + 1 < len(tokens) and tokens[index + 1].lower() == "hundred":
            total = _ONES[token] * 100
            nxt = index + 2
            rest = _parse_number(tokens, nxt) if nxt < len(tokens) else None
            if rest is not None and rest[0] < 100:
                return total + rest[0], rest[1]
            return total, nxt
        return _ONES[token], index + 1
    if token in _TENS:
        if index + 1 < len(tokens) and tokens[index + 1].lower() in _ONES:
            return _TENS[token] + _ONES[tokens[index + 1].lower()], index + 2
        return _TENS[token], index + 1
    if token == "hundred":
        return 100, index + 1
    return None


def find_hits(text: str) -> list[Hit]:
    tokens = _TOKEN.findall(text)
    hits: list[Hit] = []
    index = 0
    while index < len(tokens):
        parsed = _parse_number(tokens, index)
        if parsed is None:
            index += 1
            continue
        value, nxt = parsed
        unit = ""
        for look in range(nxt, min(len(tokens), nxt + 4)):
            unit = _UNITS.get(tokens[look].lower(), "")
            if unit:
                break
        if not unit:
            index = nxt
            continue
        window = [item.lower() for item in tokens[max(0, index - 4):index]]
        hits.append(Hit(
            value=value,
            unit=unit,
            index=index,
            after="after" in window,
            extra=any(item in _EXTRA for item in window),
        ))
        index = nxt
    return hits


def classify_clause(text: str) -> dict[str, Any]:
    """One general pattern for one clause, or an abstain reason. Not a proof."""

    hits = find_hits(text)
    if not hits:
        reason = "no_pattern" if not _MODAL.search(text or "") else "no_numeric_pattern"
        return {"disposition": "abstain", "reason": reason, "pattern": None}
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text)) if part.strip()]
    busy = [sentence for sentence in sentences if find_hits(sentence) or _MODAL.search(sentence)]
    money = [hit for hit in hits if hit.unit == "money"]
    days = [hit for hit in hits if hit.unit == "day"]
    years = [hit for hit in hits if hit.unit == "year"]
    extra = [hit for hit in money if hit.extra]
    base = [hit for hit in money if not hit.extra]
    late = [hit for hit in days if hit.after]
    amount = bool(base and extra and late and not years and len(base) == 1 and len(extra) == 1 and len(late) == 1)
    if len(busy) > 1 and not amount:
        return {"disposition": "abstain", "reason": "mixed_patterns", "pattern": None}
    pieces = [part.strip() for part in re.split(r";\s+", text) if part.strip()]
    if len(pieces) > 1 and not amount:
        return {"disposition": "abstain", "reason": "mixed_patterns", "pattern": None}
    if _CEILING.search(text) and not amount:
        return {"disposition": "abstain", "reason": "unsupported_pattern", "pattern": None}
    if amount and base[0].value > 0 and late[0].value > 0:
        return _pending({
            "kind": "amount",
            "base": base[0].value,
            "extra": extra[0].value,
            "cutoff": late[0].value,
            "late_day": late[0].value + 1,
            "late_amount": base[0].value + extra[0].value,
        })
    if not _MINIMUM.search(text) or _DATE_DAY.search(text):
        return {"disposition": "abstain", "reason": "unsupported_pattern", "pattern": None}
    if len(years) == 2 and years[0].value != years[1].value and not money and not days and re.search(r"\band\b", text, re.I):
        return _pending({"kind": "conjunction", "bounds": [years[0].value, years[1].value], "unit": "year"})
    single = None
    if len(years) == 1 and not money and not days:
        single = years[0]
    elif len(days) == 1 and not money and not years:
        single = days[0]
    if single is not None and single.value > 0:
        meet = single.value + 1 if single.after else single.value
        fail = single.value if single.after else single.value - 1
        if fail < 0:
            return {"disposition": "abstain", "reason": "no_failing_integer", "pattern": None}
        return _pending({"kind": "threshold", "fail": fail, "meet": meet, "unit": single.unit, "after": single.after})
    return {"disposition": "abstain", "reason": "unsupported_pattern", "pattern": None}


def _pending(pattern: dict[str, Any]) -> dict[str, Any]:
    return {"disposition": "pending", "reason": "", "pattern": pattern}


def _clause_selector(
    source: str, part: str, cursor: int, byte_offsets: list[int], source_sha256: str,
) -> dict[str, Any] | None:
    """Align unchanged non-whitespace text to its next source occurrence.

    Segmentation may replace line breaks, collapse spaces or join two sentences.
    Keep that existing clause text, and record each whitespace replacement rather
    than claiming its offsets index the raw source. Searching from the previous
    clause's end keeps repeated clauses distinct. Custom segmenters that rewrite
    non-whitespace content or reorder clauses cannot supply a valid selector.
    """

    pieces = list(re.finditer(r"\s+|\S+", part))
    if not pieces:
        return None
    pattern = "".join(
        r"(\s+)" if piece.group().isspace() else "(" + re.escape(piece.group()) + ")"
        for piece in pieces
    )
    matched = re.compile(pattern).search(source, cursor)
    if matched is None:
        return None
    start, end = matched.span()
    mappings = []
    for index, piece in enumerate(pieces, start=1):
        raw_start, raw_end = matched.span(index)
        mappings.append({
            "text_start": piece.start(), "text_end": piece.end(),
            "source_start": raw_start, "source_end": raw_end,
            "source_start_byte": byte_offsets[raw_start],
            "source_end_byte": byte_offsets[raw_end],
        })
    return {
        "schema_version": "legal-clause-selector-v1",
        "normalization": "whitespace-alignment-v1",
        "offset_unit": "unicode_codepoint",
        "encoding": "utf-8",
        "start": start, "end": end,
        "start_byte": byte_offsets[start], "end_byte": byte_offsets[end],
        "source_text_sha256": source_sha256,
        "raw_span_sha256": hashlib.sha256(source[start:end].encode("utf-8")).hexdigest(),
        "clause_text_sha256": hashlib.sha256(part.encode("utf-8")).hexdigest(),
        "mapping": mappings,
    }


class DocumentStore:
    """In-memory documents. Classification is not a proof."""

    def __init__(self) -> None:
        self.documents: dict[str, Document] = {}

    def open_document(
        self,
        text: str,
        *,
        jurisdiction: str = "us",
        document_type: str = "statute",
        segmenter: Segmenter | str = "paragraphs",
        edges: list[dict[str, str]] | None = None,
        document_id: str = "",
        classify: bool = True,
    ) -> dict[str, Any]:
        if not str(text or "").strip():
            return {"error": "empty_document"}
        split = segment_paragraphs if segmenter in ("paragraphs", "", None) else segmenter
        if not callable(split):
            return {"error": "unknown_segmenter"}
        parts = split(text)
        if not parts:
            return {"error": "empty_document"}
        source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        doc_id = document_id or f"doc-{source_sha256[:12]}"
        byte_offsets = [0]
        for character in text:
            byte_offsets.append(byte_offsets[-1] + len(character.encode("utf-8")))
        clauses: list[Clause] = []
        cursor = 0
        for index, part in enumerate(parts):
            selector = _clause_selector(text, part, cursor, byte_offsets, source_sha256)
            if selector is None:
                return {"error": "unresolvable_clause_selector", "clause_index": index}
            clauses.append(Clause(
                id=f"{doc_id}-c{index}", text=part,
                start=selector["start"], end=selector["end"],
                source_selector=selector,
            ))
            cursor = selector["end"]
        doc = Document(
            id=doc_id,
            text=text,
            jurisdiction=str(jurisdiction or "general"),
            document_type=str(document_type or "general"),
            clauses=clauses,
        )
        self.documents[doc_id] = doc
        self._apply_edges(doc, edges or [])
        if not classify:
            for clause in doc.clauses:
                if clause.disposition != "inactive":
                    clause.disposition = "pending"
                    clause.pattern = None
            return {"document_id": doc_id, "clauses": [self._public_clause(clause) for clause in clauses]}
        for clause in doc.clauses:
            if clause.disposition == "inactive":
                continue
            classified = classify_clause(clause.text)
            clause.disposition = str(classified["disposition"])
            clause.reason = str(classified["reason"])
            clause.pattern = classified["pattern"]
        return {"document_id": doc_id, "clauses": [self._public_clause(clause) for clause in clauses]}

    def _apply_edges(self, doc: Document, edges: list[dict[str, str]]) -> None:
        by_index = {str(index): clause.id for index, clause in enumerate(doc.clauses)}
        by_id = {clause.id: clause for clause in doc.clauses}
        for edge in edges:
            if not isinstance(edge, dict) or edge.get("kind") != "repeal":
                continue
            source = by_index.get(str(edge.get("source")), str(edge.get("source") or ""))
            target = by_index.get(str(edge.get("target")), str(edge.get("target") or ""))
            if source not in by_id or target not in by_id or source == target:
                continue
            doc.edges.append({"kind": "repeal", "source": source, "target": target})
            by_id[target].disposition = "inactive"
            by_id[target].reason = "repealed"
            by_id[target].pattern = None

    def clause(self, document_id: str, clause_id: str) -> Clause | None:
        doc = self.documents.get(document_id)
        if doc is None:
            return None
        for clause in doc.clauses:
            if clause.id == clause_id:
                return clause
        return None

    def clause_view(self, document_id: str, clause_id: str) -> dict[str, Any]:
        doc = self.documents.get(document_id)
        clause = self.clause(document_id, clause_id)
        if doc is None or clause is None:
            return {"error": "not_found"}
        view = self._public_clause(clause)
        view["edges"] = [edge for edge in doc.edges if clause.id in (edge["source"], edge["target"])]
        view["text"] = clause.text
        return view

    def obligations(self, document_id: str, clause_id: str) -> dict[str, Any]:
        clause = self.clause(document_id, clause_id)
        if clause is None:
            return {"error": "not_found"}
        if clause.disposition == "inactive":
            return {"disposition": "inactive", "reason": clause.reason, "pattern": None}
        if clause.disposition == "abstain" or not clause.pattern:
            return {"disposition": "abstain", "reason": clause.reason or "no_pattern", "pattern": None}
        return {"disposition": "pending", "reason": "", "pattern": dict(clause.pattern)}

    def deontic_analyze(self, document_id: str, clause_id: str) -> dict[str, Any]:
        doc = self.documents.get(document_id)
        clause = self.clause(document_id, clause_id)
        if doc is None or clause is None:
            return {"error": "not_found"}
        try:
            from ipfs_datasets_py.logic.deontic import DeonticConverter
        except ImportError as exc:
            return {"status": "unavailable", "reason": type(exc).__name__, "admitted": False}
        converter = DeonticConverter(
            jurisdiction=doc.jurisdiction,
            document_type=doc.document_type,
            use_ml=False,
            use_cache=False,
            enable_monitoring=False,
        )
        try:
            result = converter.convert(clause.text)
        except Exception as exc:  # noqa: BLE001 — converter failure abstains
            return {"status": "abstain", "reason": type(exc).__name__, "operators": [], "admitted": False}
        output = getattr(result, "output", None)
        operators = [str(item) for item in (getattr(output, "operators", []) or [])][:8]
        success = bool(getattr(result, "success", False))
        return {
            "status": "structured" if success and operators else "abstain",
            "operators": operators,
            "confidence": getattr(result, "confidence", None),
            "admitted": False,
        }

    def legal_ir_compile(self, document_id: str, clause_id: str) -> dict[str, Any]:
        clause = self.clause(document_id, clause_id)
        if clause is None:
            return {"error": "not_found"}
        try:
            from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler
            from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
                CanonicalAtomVocabulary,
                CompilerRequest,
            )
        except ImportError as exc:
            return {"status": "unavailable", "reason": type(exc).__name__, "admitted": False}
        try:
            result = TypedDeonticCanonicalCompiler().compile(CompilerRequest(
                source_text=clause.text,
                request_id=clause.id,
                atom_vocabulary=CanonicalAtomVocabulary(),
            ))
        except Exception as exc:  # noqa: BLE001 — IR failure abstains
            return {"status": "abstain", "reason": type(exc).__name__, "admitted": False}
        status = getattr(result.status, "value", result.status)
        return {"status": str(status), "ir": result.canonical_ir is not None, "admitted": False}

    def mark(self, document_id: str, clause_id: str, disposition: str, error: str = "") -> None:
        clause = self.clause(document_id, clause_id)
        if clause is None or clause.disposition == "inactive":
            return
        if disposition not in {"admitted", "failed", "pending", "abstain"}:
            return
        clause.disposition = disposition
        clause.error = error

    def coverage(self, document_id: str) -> dict[str, Any]:
        doc = self.documents.get(document_id)
        if doc is None:
            return {"error": "not_found"}
        rows = [self._public_clause(clause) for clause in doc.clauses]
        counts = {"admitted": 0, "abstain": 0, "inactive": 0, "failed": 0, "pending": 0}
        for row in rows:
            key = str(row["disposition"])
            if key in counts:
                counts[key] += 1
        return {"document_id": doc.id, "counts": counts, "clauses": rows}

    def _public_clause(self, clause: Clause) -> dict[str, Any]:
        return {
            "id": clause.id,
            "disposition": clause.disposition,
            "reason": clause.reason,
            "error": clause.error,
            "start": clause.start,
            "end": clause.end,
            "source_selector": {
                **clause.source_selector,
                "mapping": [dict(item) for item in clause.source_selector.get("mapping", ())],
            },
        }


STORE = DocumentStore()


def reset_documents() -> None:
    STORE.documents.clear()
