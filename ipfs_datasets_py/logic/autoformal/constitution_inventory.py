"""Span inventory for the Constitution text. Does not compile and does not call a model."""
from __future__ import annotations

import re
from typing import Any


_HEADING = re.compile(
    r"^(?:article\.?\s+[ivxlc\d]+\.?|section\.?\s+\d+\.?|amendment\s+[ivxlc\d]+|amendment\s+[ivxlc]+)$",
    re.I,
)
_CHROME = re.compile(
    r"^(?:snippet|shop the|national archives store)$"
    r"|permanent display|last reviewed|being interlined|erazure"
    r"|passed by congress|was modified by|was superseded by|was affected by"
    r"|^\s*note:\s*$"
    r"|^\s*amendments\s+\d"
    r"|^\s*\*?\s*superseded by\b"
    r"|shop the archives|nationalarchivesstore"
    r"|originally proposed"
    r"|back to constitution"
    r"|changed by section"
    r"|about the bill of rights"
    r"|read a transcript"
    r"|bill of rights transcript"
    r"|on this page"
    r"|^\s*\d{1,2},\s+\d{4}\.?$",
    re.I,
)
_SIGNATURE = re.compile(r"^(?:attest\b|done in convention\b)", re.I)
_REPEAL = re.compile(
    r"\bthe\s+(?P<which>[a-z0-9][a-z0-9\-\s]*?)\s+article\s+of\s+amendment\b[\s\S]{0,80}?\bis\s+hereby\s+repealed\b",
    re.I,
)
_ORDINAL = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12,
    "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16,
    "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20,
    "thirtieth": 30,
}
_TENS = {"twenty": 20, "thirty": 30}


_FACET_RULES = (
    ("qualification_swallowed", re.compile(r"who shall not have attained|years a citizen|inhabitant of that state", re.I)),
    ("repeal_or_amend", re.compile(r"is hereby repealed", re.I)),
    ("structure", re.compile(r"shall be vested in|shall consist of", re.I)),
    ("definition", re.compile(r"\bmeans\b|\bincludes\b", re.I)),
    ("cross_reference", re.compile(r"as provided in|article of amendment", re.I)),
    ("penalty", re.compile(r"\bpunish|\bfine\b|\bimprison", re.I)),
    ("procedure", re.compile(r"may by law|shall be prescribed|trial\b", re.I)),
    ("mental_state", re.compile(r"\bknowingly\b|\bwillfully\b", re.I)),
)


def retag_other(ledger: dict[str, Any], inspect) -> dict[str, Any]:
    """Replace facet `other` from parser slots. Does not mark a span roundtrip_ok."""

    for span in ledger.get("spans") or []:
        if span.get("status") != "gap" or span.get("facet") != "other":
            continue
        span["facet"] = str(inspect(str(span.get("text") or "")) or "other")
        if span["status"] == "roundtrip_ok":
            span["status"] = "gap"
    counts: dict[str, int] = {}
    for span in ledger.get("spans") or []:
        if span.get("status") != "gap":
            continue
        facet = str(span.get("facet") or "other")
        counts[facet] = counts.get(facet, 0) + 1
    ledger["facet_counts"] = counts
    return ledger


def tag_facets(ledger: dict[str, Any]) -> dict[str, Any]:
    """Name each gap. Does not call a model and does not recompile."""

    counts: dict[str, int] = {}
    for span in ledger.get("spans") or []:
        if span.get("status") != "gap":
            continue
        facet = _facet(str(span.get("text") or ""), str(span.get("reason") or ""))
        fields = [str(item) for item in span.get("unsupported_fields") or [] if str(item)]
        if facet == "other" and fields:
            facet = fields[0]
        span["facet"] = facet
        counts[facet] = counts.get(facet, 0) + 1
    ledger["facet_counts"] = counts
    return ledger


def _facet(text: str, reason: str) -> str:
    if reason == "no_parser_elements" or "no_parser_elements" in reason:
        return "no_parser_elements"
    for name, pattern in _FACET_RULES:
        if pattern.search(text):
            return name
    return "other"


def census_ledger(ledger: dict[str, Any], compile_one) -> dict[str, Any]:
    """Compile each uncompiled span. Abstain becomes a named gap. No repair and no Lake."""

    for span in ledger.get("spans") or []:
        if span.get("status") != "uncompiled":
            continue
        try:
            outcome = compile_one(str(span.get("text") or ""))
        except (ImportError, OSError) as exc:
            span["compiler_status"] = "failed"
            span["reason"] = type(exc).__name__
            return {"stopped": True, "error": type(exc).__name__, "ledger": ledger}
        compiler_status = str(outcome.get("compiler_status") or "abstain")
        span["compiler_status"] = compiler_status
        span["reason"] = str(outcome.get("reason") or "")
        fields = [str(item) for item in outcome.get("fields") or [] if str(item)]
        if fields:
            span["unsupported_fields"] = fields
        if outcome.get("decompiled"):
            span["decompiled"] = str(outcome["decompiled"])
        if isinstance(outcome.get("rule"), dict):
            span["rule"] = dict(outcome["rule"])
        if outcome.get("roundtrip") is True:
            span["roundtrip"] = True
        if compiler_status == "compiled":
            span["status"] = "compiled"
        elif compiler_status == "repeal":
            span["status"] = "repeal"
            span["admitted"] = False
        else:
            span["status"] = "gap"
            if not span["reason"]:
                span["reason"] = "abstain"
    return {"stopped": False, "error": "", "ledger": ledger}


def inventory_constitution(text: str) -> dict[str, Any]:
    """One row per span. Operative rows stay uncompiled. No compiler and no model."""

    units = _units(text)
    spans: list[dict[str, Any]] = []
    for unit in units:
        sentences = _sentences(unit["body"]) if unit["body"] else []
        if not sentences and unit["kind"] == "preamble":
            sentences = [unit["label"]] if unit["label"] else []
        for index, sentence in enumerate(sentences, start=1):
            span_id = f"{unit['id']}.span-{index}" if unit["id"] else f"span-{index}"
            status = "non_operative" if unit["kind"] in {"preamble", "signature", "note"} or _CHROME.search(sentence) or _SIGNATURE.search(sentence) else "uncompiled"
            spans.append({
                "id": span_id,
                "unit_id": unit["id"],
                "text": sentence,
                "status": status,
                "reason": unit["kind"] if status == "non_operative" else "",
            })
    edges = _repeal_edges(spans)
    inactive = {edge["target"] for edge in edges}
    for span in spans:
        unit_id = str(span["unit_id"])
        repealed = any(unit_id == target or unit_id.startswith(target + ".") for target in inactive)
        if repealed and span["status"] == "uncompiled":
            span["status"] = "inactive"
            span["reason"] = "repealed"
    return {"spans": spans, "edges": edges, "compiled": False}


def _units(text: str) -> list[dict[str, str]]:
    units: list[dict[str, str]] = []
    kind = "preamble"
    label = "preamble"
    unit_id = "preamble"
    context = ""
    body: list[str] = []
    signature = False

    def flush() -> None:
        chunk = " ".join(part.strip() for part in body if part.strip()).strip()
        if chunk or kind == "preamble":
            units.append({"id": unit_id, "kind": kind, "label": label, "body": chunk})
        body.clear()

    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if signature and not _HEADING.match(line) and line.upper() != "BILL OF RIGHTS":
            body.append(line)
            continue
        if _SIGNATURE.match(line):
            flush()
            signature = True
            kind, label, unit_id = "signature", "signature", "signature"
            body.append(line)
            continue
        if line.upper() == "BILL OF RIGHTS":
            flush()
            signature = False
            kind, label, unit_id = "note", "bill-of-rights", "bill-of-rights"
            continue
        if _HEADING.match(line):
            flush()
            signature = False
            unit_id = _nested_id(line, context)
            if unit_id.startswith("art-") or unit_id.startswith("amend-"):
                context = unit_id.split(".sec-", 1)[0]
            kind = "operative"
            label = line
            continue
        if _CHROME.search(line):
            flush()
            saved = (kind, label, unit_id)
            signature = False
            kind, label, unit_id = "note", "note", f"note-{len(units) + 1}"
            body.append(line)
            flush()
            kind, label, unit_id = saved
            continue
        body.append(line)
    flush()
    return [unit for unit in units if unit["body"] or unit["kind"] == "preamble"]


def _nested_id(heading: str, context: str) -> str:
    match = re.match(r"section\.?\s+(\d+)", heading, re.I)
    if match:
        section = f"sec-{int(match.group(1))}"
        return f"{context}.{section}" if context else section
    return _unit_id(heading)


def _unit_id(heading: str) -> str:
    match = re.match(r"article\.?\s+([ivxlc\d]+)", heading, re.I)
    if match:
        return f"art-{_roman_or_int(match.group(1))}"
    match = re.match(r"section\.?\s+(\d+)", heading, re.I)
    if match:
        return f"sec-{int(match.group(1))}"
    match = re.match(r"amendment\s+([ivxlc\d]+)", heading, re.I)
    if match:
        return f"amend-{_roman_or_int(match.group(1))}"
    return "unit"


def _roman_or_int(token: str) -> int:
    text = token.strip().lower()
    if text.isdigit():
        return int(text)
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
    total = 0
    previous = 0
    for char in reversed(text):
        value = values.get(char, 0)
        if value < previous:
            total -= value
        else:
            total += value
            previous = value
    return total


def _sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text).strip()
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", flat) if part.strip()]
    return parts


def _repeal_edges(spans: list[dict[str, Any]]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    units = {str(span["unit_id"]) for span in spans}
    for span in spans:
        match = _REPEAL.search(str(span["text"]))
        if not match:
            continue
        number = _amendment_number(match.group("which"))
        target = f"amend-{number}" if number else ""
        if not target or target == span["unit_id"] or not any(
            unit_id == target or unit_id.startswith(target + ".") for unit_id in units
        ):
            continue
        edges.append({"kind": "repeal", "source": str(span["id"]), "target": target})
    return edges


def _amendment_number(words: str) -> int | None:
    text = re.sub(r"[^a-z0-9\-\s]", "", words.lower())
    text = text.replace(" ", "-").strip("-")
    if text.isdigit():
        return int(text)
    if text in _ORDINAL:
        return _ORDINAL[text]
    if "-" in text:
        left, right = text.split("-", 1)
        if left in _TENS and right in _ORDINAL:
            return _TENS[left] + _ORDINAL[right]
    return None
