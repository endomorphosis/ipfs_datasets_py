"""Lossless source spans for CVEfixes prose, code bodies, and unified diffs.

These are source selectors, not SecurityIR labels or parsed compilation units.
Localized descriptions are decoded by the caller; their offsets refer to that
exact value, never to its surrounding serialized description container.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from ...formalization import text_spans

SCHEMA = "security-ir-source-span/v1"
POLICY_ID = "cvefixes-security-source-spans/v1"
MAX_CANDIDATE_WORDS = 48
MAX_CANDIDATE_CHARACTERS = 4096
PROSE_FIELDS = frozenset({"cve_description", "cwe_description", "commit_message"})
CODE_FIELDS = frozenset({"vulnerable_code", "fixed_code"})
FIELDS = PROSE_FIELDS | CODE_FIELDS | {"diff_with_context"}
_HUNK = re.compile(
    r"@@ -[0-9]+(?:,(?P<old_count>[0-9]+))? "
    r"\+[0-9]+(?:,(?P<new_count>[0-9]+))? @@(?:[ \t][^\r\n]*)?(?:\r?\n)?\Z"
)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def describe_source_span_profile() -> dict:
    """Describe the deterministic policy, including its source-level limits."""
    return {
        "schema": "security-ir-source-span-profile/v1", "span_schema": SCHEMA,
        "policy_id": POLICY_ID, "fields": sorted(FIELDS),
        "prose_policy": text_spans.SENTENCE_POLICY,
        "candidate_limits": {"words": MAX_CANDIDATE_WORDS,
                             "characters": MAX_CANDIDATE_CHARACTERS},
        "selectors": "half-open Unicode character and UTF-8 byte offsets in the exact field value",
        "localized_descriptions": "field_index identifies the caller-decoded value; offsets are not serialized-container offsets",
        "code_policy": "whole source body; no sentence splitting or AST inference",
        "diff_policy": "unified @@ headers and counted hunk lines; file headers and other preamble remain context",
        "normalization_role": "auxiliary whitespace-normalized retrieval text; text remains the exact source",
        "whitespace": "retained as excluded_whitespace spans; no characters omitted",
        "oversize": "retained without truncation; code and diff always require context",
        "read_bounds": "caller-owned; this segmentation function does not truncate fields",
        "complete_compilation_unit_asserted": False, "semantic_targets_generated": False,
        "producer_pins": {name: _sha(Path(path).read_bytes()) for name, path in (
            (__name__, __file__), (text_spans.__name__, text_spans.__file__))},
    }


def _prose_intervals(text):
    cursor = 0
    for sentence in text_spans.sentence_spans(text):
        start, end = sentence["start_char"], sentence["end_char"]
        if cursor < start:
            yield "whitespace", cursor, start
        yield "prose_sentence", start, end
        cursor = end
    if cursor < len(text):
        yield "whitespace", cursor, len(text)


def _diff_intervals(text):
    """Partition actual LF/CRLF hunk lines without treating payload as headers.

    Counts distinguish hunk payload from subsequent file headers. Malformed or
    incomplete material remains source context; no diff validity is asserted.
    """
    start, kind, remaining = 0, "diff_context", None
    for line in re.finditer(r"[^\n]*\n|[^\n]+$", text):
        raw, offset = line[0], line.start()
        header = _HUNK.fullmatch(raw)
        counts = None
        if header:
            try:
                counts = (int(header["old_count"] or "1"), int(header["new_count"] or "1"))
            except ValueError:
                # Unrepresentable range counts cannot erase their source text.
                header = None
        if header:
            if start < offset:
                yield kind, start, offset
            start, kind, remaining = offset, "diff_hunk", counts
            continue
        if kind == "diff_hunk":
            if raw.rstrip("\r\n") == "\\ No newline at end of file":
                continue
            old, new = remaining
            delta = {" ": (1, 1), "-": (1, 0), "+": (0, 1)}.get(raw[:1])
            if delta is not None and old >= delta[0] and new >= delta[1] and (old or new):
                remaining = (old - delta[0], new - delta[1])
                continue
            if start < offset:
                yield kind, start, offset
            start, kind, remaining = offset, "diff_context", None
    if start < len(text):
        yield kind, start, len(text)


def build_source_spans(text: str, field: str, source_cid: str, *, field_index: int = 0) -> list[dict]:
    """Return a lossless inventory with source-bound identities and exact offsets.

    ``source_cid`` is the caller's opaque parent identity. Nonzero field indexes
    distinguish repeated localized CVE descriptions. This function does not
    decode description containers, decide licensing, or construct formal labels.
    """
    if type(text) is not str:
        raise ValueError("source span text must be an exact string")
    if type(field) is not str or field not in FIELDS:
        raise ValueError("unsupported CVEfixes source span field")
    if type(source_cid) is not str or not source_cid.strip():
        raise ValueError("a nonempty source CID string is required")
    if (type(field_index) is not int or field_index < 0
            or field != "cve_description" and field_index != 0):
        raise ValueError("nonnegative field_index is supported only for localized CVE descriptions")
    raw_body_sha256 = _sha(text.encode("utf-8"))
    if field in PROSE_FIELDS:
        intervals = _prose_intervals(text)
    elif field in CODE_FIELDS:
        intervals = [("code_context", 0, len(text))] if text else []
    else:
        intervals = _diff_intervals(text)
    result = []
    for kind, start, end in intervals:
        selector = text_spans.source_selector(text, start, end)
        raw = selector["text"]
        if not raw.strip():
            kind = "whitespace"
        words, chars = len(raw.split()), len(raw)
        exceeds = words > MAX_CANDIDATE_WORDS or chars > MAX_CANDIDATE_CHARACTERS
        if kind == "whitespace":
            status, reasons = "excluded_whitespace", ["whitespace_only"]
        elif kind == "prose_sentence":
            reasons = (["prose_word_limit"] if words > MAX_CANDIDATE_WORDS else [])
            reasons += ["prose_character_limit"] if chars > MAX_CANDIDATE_CHARACTERS else []
            status = "oversize" if exceeds else "candidate"
        else:
            status, reasons = "context_required", ["requires_file_context"]
        identity = {"schema": SCHEMA, "policy_id": POLICY_ID, "source_cid": source_cid,
            "field": field, "field_index": field_index, "raw_body_sha256": raw_body_sha256,
            "selector": {key: selector[key] for key in ("start_char", "end_char", "start_byte", "end_byte")}}
        result.append({**{key: value for key, value in identity.items() if key != "selector"},
            **selector, "span_id": "sha256:" + _sha(_wire(identity)),
            "span_text_sha256": _sha(raw.encode("utf-8")), "kind": kind, "status": status,
            "candidate_eligible": status == "candidate", "word_count": words, "char_count": chars,
            "exceeds_candidate_limit": exceeds, "reasons": reasons,
            "requires_file_context": field not in PROSE_FIELDS,
            "complete_compilation_unit": False, "source_semantics_verified": False, "truncated": False})
    return result
