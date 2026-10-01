"""Replayable, source-bound SkillCenter spans for experimental Intent training.

The segmentation matches the US Code sentence policy inside Markdown blocks.
Eligibility is only permission to attempt conservative native target extraction;
it is never a reviewed semantic label or an authorization to execute the source.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from ...formalization import text_spans
from . import skillcenter_training

SCHEMA = "skillcenter-intent-span-corpus/v1"
DESCRIPTOR_SCHEMA = "skillcenter-intent-span-corpus-descriptor/v1"
POLICY = "skillcenter-markdown-source-spans/v1"
MAX_BYTES = 32 * 1024 * 1024
MAX_SPANS = 32_768
MAX_WORDS = 48
MAX_CHARS = 4096

_HEADING = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*(?:\r?\n)?$")
_LIST = re.compile(r"^(?P<indent>[ \t]*)(?P<marker>[-+*]|\d+[.)])[ \t]+")
_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
_CONDITIONAL = re.compile(r"\b(if|unless|when|whenever|until|after|before|provided|providing|otherwise|once|while)\b", re.I)
_QUANTIFIER = re.compile(r"\b(all|every|each|any|some|none|either|both|no)\b|\b(?:at least|at most|exactly)\b", re.I)
_ANAPHORA = re.compile(r"\b(it|its|they|them|their|this|that|these|those|former|latter|above|below|previous|next|then|there|such)\b", re.I)
_EXAMPLE = re.compile(r"\b(examples?|samples?|demonstrations?|templates?)\b", re.I)


def _wire(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _producer_pins() -> dict[str, str]:
    return {name: _sha(Path(path).read_bytes()) for name, path in (
        (__name__, __file__), (text_spans.__name__, text_spans.__file__),
        (skillcenter_training.__name__, skillcenter_training.__file__))}


def _context_reasons(value: str) -> list[str]:
    reasons = []
    for pattern, reason in ((_CONDITIONAL, "conditional_context"),
                            (_QUANTIFIER, "quantifier_context"),
                            (_ANAPHORA, "anaphoric_context")):
        if pattern.search(value):
            reasons.append(reason)
    if "`" in value:
        reasons.append("inline_code_context")
    if re.search(r"(?m)^ {4,}\S|^\t\S", value):
        reasons.append("indented_code_or_wrapped_context")
    if re.search(r"<[/!a-zA-Z]", value):
        reasons.append("html_markup_context")
    if value.rstrip().endswith(":"):
        reasons.append("incomplete_scope_context")
    return reasons


def _markdown_blocks(text: str) -> list[dict[str, Any]]:
    """Partition raw Markdown, retaining surrounding scope instead of stripping it."""
    lines = text.splitlines(keepends=True)
    starts, offset = [], 0
    for line in lines:
        starts.append(offset)
        offset += len(line)
    starts.append(len(text))
    blocks: list[dict[str, Any]] = []
    headings: list[dict[str, Any]] = []
    parents: list[dict[str, Any]] = []
    leadin: dict[str, Any] | None = None

    def append(kind: str, first: int, last: int, **extra: Any) -> dict[str, Any]:
        if len(blocks) >= MAX_SPANS:
            raise ValueError("span inventory exceeds the 32768-row bound")
        row = {"kind": kind, **text_spans.source_selector(text, starts[first], starts[last]),
               "heading_context": [dict(h) for h in headings], **extra}
        blocks.append(row)
        return row

    i = 0
    if lines and lines[0].strip() == "---":
        j = 1
        while j < len(lines) and lines[j].strip() not in {"---", "..."}:
            j += 1
        append("frontmatter", 0, min(j + 1, len(lines)))
        i = min(j + 1, len(lines))
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            append("whitespace", i, j)
            i = j
            continue
        fence = _FENCE.match(line)
        if fence:
            delimiter = fence.group(1)
            j = i + 1
            while j < len(lines):
                closing = lines[j].strip()
                if (len(closing) >= len(delimiter) and set(closing) == {delimiter[0]}):
                    j += 1
                    break
                j += 1
            append("fenced_code", i, j)
            parents = []
            i = j
            continue
        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            headings = [h for h in headings if h["level"] < level]
            h = {**text_spans.source_selector(text, starts[i], starts[i + 1]),
                 "level": level, "title": heading.group(2).rstrip("# ")}
            headings.append(h)
            append("heading", i, i + 1)
            parents, leadin = [], None
            i += 1
            continue
        # Setext headings are retained as a single exact heading selector.
        if (i + 1 < len(lines) and re.fullmatch(r"[ \t]{0,3}(?:=+|-+)[ \t]*(?:\r?\n)?", lines[i + 1])
                and not _LIST.match(line)):
            level = 1 if lines[i + 1].lstrip().startswith("=") else 2
            headings = [h for h in headings if h["level"] < level]
            headings.append({**text_spans.source_selector(text, starts[i], starts[i + 2]),
                             "level": level, "title": line.strip()})
            append("heading", i, i + 2)
            parents, leadin = [], None
            i += 2
            continue
        if line.lstrip().startswith(">"):
            j = i + 1
            while j < len(lines) and lines[j].lstrip().startswith(">"):
                j += 1
            append("quoted_example", i, j)
            parents = []
            i = j
            continue
        if "|" in line:
            j = i + 1
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                j += 1
            append("table_or_pipe_expression", i, j)
            parents = []
            i = j
            continue
        marker = _LIST.match(line)
        if marker:
            indent = len(marker.group("indent").expandtabs(4))
            parents = [p for p in parents if p["indent"] < indent]
            j = i + 1
            while j < len(lines) and lines[j].strip():
                if (_LIST.match(lines[j]) or _HEADING.match(lines[j]) or _FENCE.match(lines[j])
                        or lines[j].lstrip().startswith(">") or "|" in lines[j]):
                    break
                j += 1
            row = append("list_item", i, j,
                         content_start_char=starts[i] + marker.end(),
                         parent_list_context=[dict(p) for p in parents],
                         leadin_context=dict(leadin) if leadin else None)
            parents.append({"indent": indent,
                            **text_spans.source_selector(text, row["content_start_char"], row["end_char"])})
            if leadin is None and _context_reasons(row["text"]):
                leadin = text_spans.source_selector(text, row["content_start_char"], row["end_char"])
            i = j
            continue
        if line.startswith(("    ", "\t")):
            j = i + 1
            while j < len(lines) and (lines[j].startswith(("    ", "\t")) or not lines[j].strip()):
                j += 1
            append("indented_code", i, j)
            parents = []
            i = j
            continue
        j = i + 1
        while j < len(lines) and lines[j].strip():
            if (_LIST.match(lines[j]) or _HEADING.match(lines[j]) or _FENCE.match(lines[j])
                    or lines[j].lstrip().startswith(">") or "|" in lines[j]
                    or re.fullmatch(r"[ \t]{0,3}(?:=+|-+)[ \t]*(?:\r?\n)?", lines[j])):
                break
            j += 1
        if j < len(lines) and re.fullmatch(r"[ \t]{0,3}(?:=+|-+)[ \t]*(?:\r?\n)?", lines[j]):
            level = 1 if lines[j].lstrip().startswith("=") else 2
            headings = [h for h in headings if h["level"] < level]
            headings.append({**text_spans.source_selector(text, starts[i], starts[j + 1]),
                             "level": level, "title": text_spans.normalize_span_text(text[starts[i]:starts[j]])})
            append("heading", i, j + 1)
            parents, leadin = [], None
            i = j + 1
            continue
        row = append("paragraph", i, j, leadin_context=dict(leadin) if leadin else None)
        if leadin is None and _context_reasons(row["text"]):
            leadin = {k: row[k] for k in ("text", "normalized_text", "start_char", "end_char", "start_byte", "end_byte")}
        parents = []
        i = j
    return blocks


def _source_spans(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    text = source["instruction"]
    rows: list[dict[str, Any]] = []
    for block in _markdown_blocks(text):
        headings = block["heading_context"]
        parents = block.get("parent_list_context", [])
        leadin = block.get("leadin_context")
        context_reasons = _context_reasons(block["text"])
        for context in [*headings, *parents, *([leadin] if leadin else [])]:
            context_reasons.extend(_context_reasons(context["text"]))
        if parents:
            context_reasons.append("parent_list_context")
        if leadin:
            context_reasons.append("preceding_scope_context")
        context_reasons = sorted(set(context_reasons))
        example_scope = any(_EXAMPLE.search(h["title"]) for h in headings)
        block_context = {key: block[key] for key in ("kind", "start_char", "end_char", "start_byte", "end_byte", "normalized_text")}
        block_context.update(parent_list_context=parents, leadin_context=leadin,
                             context_reasons=context_reasons)

        def emit(start: int, end: int, status: str, reason: str) -> None:
            if start == end:
                return
            if len(rows) >= MAX_SPANS:
                raise ValueError("span inventory exceeds the 32768-row bound")
            selector = text_spans.source_selector(text, start, end)
            identity = {"policy": POLICY, "domain": source["domain"],
                        "source_id": source["source_id"], "source_sha256": source["source_sha256"],
                        **selector}
            rows.append({"id": "intent-span:" + _sha(_wire(identity)),
                         "source_id": source["source_id"], "source_sha256": source["source_sha256"],
                         "domain": source["domain"], "split": source["split"],
                         **selector, "heading_context": headings, "block_context": block_context,
                         "status": status, "reason": reason,
                         "eligible_for_pairing": status == "candidate"})

        if block["kind"] not in {"paragraph", "list_item"} or example_scope:
            emit(block["start_char"], block["end_char"], "excluded",
                 "example_heading_context" if example_scope else block["kind"])
            continue
        content_start = block.get("content_start_char", block["start_char"])
        cursor = block["start_char"]
        for span in text_spans.sentence_spans(text, start_char=content_start, end_char=block["end_char"]):
            emit(cursor, span["start_char"], "excluded", "markdown_marker_or_whitespace")
            normalized = span["normalized_text"]
            if len(normalized) > MAX_CHARS or len(normalized.split()) > MAX_WORDS:
                status, reason = "oversize_gap", "checkpoint_input_limit"
            elif context_reasons:
                status, reason = "context_required", ",".join(context_reasons)
            else:
                status, reason = "candidate", "bounded_context_independent_sentence"
            emit(span["start_char"], span["end_char"], status, reason)
            cursor = span["end_char"]
        emit(cursor, block["end_char"], "excluded", "markdown_marker_or_whitespace")
    if "".join(row["text"] for row in rows) != text:
        raise ValueError("span inventory must retain every source character exactly once")
    return rows


def build_skillcenter_span_corpus(source_descriptor: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the original source export, then expand its existing partitions."""
    parent = skillcenter_training.load_skillcenter_training_corpus(source_descriptor)
    sources, spans = [], []
    for sample in sorted(parent["samples"], key=lambda row: row["id"]):
        record = sample["source_record"]
        source = {"source_id": sample["id"], "source_sha256": sample["source_sha256"],
                  "instruction": sample["instruction"], "domain": sample["domain"],
                  "split": sample["split"], "license_expression": sample["license_expression"],
                  "source_url": record["source_url"], "source_identity": sample["source_identity"],
                  "source_family": {"primary_source_id": record["primary_source_id"],
                                    "repository_group": skillcenter_training._repository_group(record["source_url"]),
                                    "content_sha256": sample["source_sha256"]}}
        if _sha(source["instruction"].encode("utf-8")) != source["source_sha256"]:
            raise ValueError("source text differs from its parent content hash")
        sources.append(source)
        spans.extend(_source_spans(source))
        if len(spans) > MAX_SPANS:
            raise ValueError("span inventory exceeds the 32768-row bound")
    duplicate_splits: dict[str, set[str]] = defaultdict(set)
    for span in spans:
        if span["eligible_for_pairing"]:
            duplicate_splits[span["normalized_text"].casefold()].add(span["split"])
    for span in spans:
        if span["eligible_for_pairing"] and len(duplicate_splits[span["normalized_text"].casefold()]) > 1:
            span.update(status="excluded", reason="cross_partition_duplicate", eligible_for_pairing=False)
    counts = Counter(span["status"] for span in spans)
    counts.update(sources=len(sources), spans=len(spans),
                  eligible_for_pairing=sum(span["eligible_for_pairing"] for span in spans))
    report = {"schema": SCHEMA, "policy": POLICY, "sentence_policy": text_spans.SENTENCE_POLICY,
              "source_corpus": dict(source_descriptor), "producer_sha256": _producer_pins(),
              "dataset_repo_id": parent["dataset_repo_id"], "release_revision": parent["release_revision"],
              "sources": sources, "spans": spans, "counts": dict(counts),
              "split_manifest": parent["split_manifest"], "parent_counts": parent["counts"],
              "coverage": {"source_characters": sum(len(s["instruction"]) for s in sources),
                           "represented_characters": sum(len(s["text"]) for s in spans),
                           "omitted_characters": 0, "source_order_preserved": True},
              "input_limits": {"max_words": MAX_WORDS, "max_characters": MAX_CHARS,
                               "oversize_policy": "retain_complete_sentence_as_gap_never_truncate"},
              "split_scope": parent["split_scope"], "holdout_status": parent["holdout_status"],
              "supervision": "source_spans_only_no_formal_targets", "gold_formal_target_count": 0,
              "source_content_executed": False, "provider_calls": 0, "qualified": False, "admitted": False}
    if len(_wire(report)) > MAX_BYTES:
        raise ValueError("span inventory exceeds the 32 MiB bound")
    return report


build_skillcenter_span_inventory = build_skillcenter_span_corpus


def export_skillcenter_span_corpus(source_descriptor: Mapping[str, Any], *, output: Path) -> dict[str, Any]:
    """Create a fresh local span export without changing sources or checkpoints."""
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("a fresh output directory is required")
    report = build_skillcenter_span_corpus(source_descriptor)
    raw = _wire(report)
    output.mkdir(parents=True)
    path = output / "spans.json"
    path.write_bytes(raw)
    descriptor = {"schema": DESCRIPTOR_SCHEMA, "path": str(path), "sha256": _sha(raw)}
    (output / "descriptor.json").write_bytes(_wire(descriptor))
    return descriptor


def load_skillcenter_span_corpus(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute source hashes, selectors, context decisions and split fences."""
    if set(descriptor) != {"schema", "path", "sha256"} or descriptor["schema"] != DESCRIPTOR_SCHEMA:
        raise ValueError("exact span corpus descriptor required")
    path = Path(descriptor["path"])
    if not path.is_absolute():
        raise ValueError("absolute span corpus path required")
    raw = skillcenter_training._file(path.parent, path.name, digest=descriptor["sha256"])
    report = json.loads(raw)
    expected = build_skillcenter_span_corpus(report["source_corpus"])
    if _wire(report) != _wire(expected):
        raise ValueError("span corpus differs from pinned source replay")
    return report
