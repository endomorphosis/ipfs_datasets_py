"""Bounded, source-bound candidate retrieval for unresolved semantic slots.

Retrieval suggests context; it does not choose an interpretation. Provisional
fixtures remain assumptions, even when a conditional formula passes Lake.
This module has no model, network, supervisor, database or proof side effects.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from time import monotonic

from ..ir_core.provenance import SourceRef, SourceSpan
from ...processors.retrieval import build_bm25_index, search_bm25_index

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_PRODUCER_PINS = {name: hashlib.sha256((_PACKAGE_ROOT / name).read_bytes()).hexdigest() for name in (
    "logic/formalization/context_resolution.py", "logic/ir_core/provenance.py", "processors/retrieval.py")}

SCHEMA = "formalization-context-candidates/v1"
SLOT_SORTS = frozenset({"referent", "temporal_anchor", "temporal_model", "scope",
    "definition", "confirmation_policy", "trace_scope"})
RELATIONS = frozenset({"parent", "citation", "definition", "policy", "supports"})
AUTHORITY = {"source_semantics_verified": False, "qualified": False, "admitted": False,
    "formalized": False, "roundtrip_ok": False, "supervisor_importable": False}


def context_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _guard_producers():
    for name, expected in _PRODUCER_PINS.items():
        _require(hashlib.sha256((_PACKAGE_ROOT / name).read_bytes()).hexdigest() == expected,
            "context_producer_changed_since_import:" + name)


def _text(value, name, maximum=4096):
    _require(type(value) is str and 0 < len(value.encode("utf-8")) <= maximum, name)
    return value


@dataclass(frozen=True, init=False)
class ContextSpan:
    """Verified excerpt; native source and byte-range identities stay intact.

    Construct with ``from_source`` so the exact container bytes are checked.
    The index consumes detached JSON records, not mutable caller dictionaries.
    """
    _json: str

    def __init__(self, *args, **kwargs):
        raise TypeError("Use ContextSpan.from_source with the exact source bytes")

    @classmethod
    def from_source(cls, *, source_ref: SourceRef, span: SourceSpan,
                    source_text: str, partition: str):
        source_ref.validate()
        span.validate()
        _require(source_ref.review_status.value not in {"rejected", "quarantined"}, "source_review_refuses_context")
        _text(partition, "partition_required", 256)
        _require(type(source_text) is str, "source_text_required")
        raw = source_text.encode("utf-8")
        _require(len(raw) <= 4_000_000, "source_byte_limit")
        _require(hashlib.sha256(raw).hexdigest() == source_ref.content_sha256, "source_hash_mismatch")
        _require(span.source_ref_id == source_ref.ref_id, "foreign_span_source")
        _require(0 <= span.start_byte < span.end_byte <= len(raw), "span_bounds")
        try:
            text = raw[span.start_byte:span.end_byte].decode("utf-8")
            prefix = raw[:span.start_byte].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("span_splits_unicode") from exc
        if span.start_char is not None or span.end_char is not None:
            _require(span.start_char == len(prefix) and span.end_char == len(prefix) + len(text), "span_character_bounds")
        _require(len(text.encode()) <= 131072, "excerpt_byte_limit")
        record = {"source_ref": source_ref.to_dict(), "span": span.to_dict(),
            "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "partition": partition}
        result = object.__new__(cls)
        object.__setattr__(result, "_json", json.dumps(record, sort_keys=True, ensure_ascii=True, allow_nan=False))
        return result

    def to_dict(self):
        return json.loads(self._json)


@dataclass(frozen=True)
class ContextLimits:
    max_candidates_per_slot: int = 8
    max_context_bytes: int = 32768
    max_graph_hops: int = 2
    max_graph_visits: int = 128
    neighbor_radius: int = 1
    max_seconds: float = 5.0

    def validate(self):
        for key, low, high in (("max_candidates_per_slot", 1, 32), ("max_context_bytes", 1, 262144),
                ("max_graph_hops", 0, 2), ("max_graph_visits", 1, 512), ("neighbor_radius", 0, 3)):
            value = getattr(self, key)
            _require(type(value) is int and low <= value <= high, "invalid_limit:" + key)
        _require(type(self.max_seconds) in (int, float) and 0 < self.max_seconds <= 30, "invalid_deadline")


class BoundedContextIndex:
    """Reusable small context shard with BM25 and explicit directed links.

    ``revision`` identifies the exported corpus/index revision. Graph edges are
    declared retrieval links, not logical premises. Partition isolation is
    enforced before BM25 scoring and at every graph hop. Build once per worker;
    no full-corpus load or all-pairs graph is required.
    """

    def __init__(self, spans, *, edges=(), revision):
        _text(revision, "index_revision_required", 256)
        _require(type(spans) in (list, tuple) and 0 < len(spans) <= 4096, "bounded_spans_required")
        _require(type(edges) in (list, tuple) and len(edges) <= 8192, "bounded_edges_required")
        records = {}
        documents = {}
        total = 0
        for item in spans:
            _require(type(item) is ContextSpan, "verified_context_span_required")
            row = item.to_dict()
            # Source bytes were checked at construction; recheck native wire
            # shapes and excerpt identity at the index boundary.
            ref = SourceRef.from_dict(row["source_ref"])
            span = SourceSpan.from_dict(row["span"])
            _require(ref.to_dict() == row["source_ref"] and span.to_dict() == row["span"], "context_wire_changed")
            _require(ref.review_status.value not in {"rejected", "quarantined"}, "source_review_refuses_context")
            _require(span.source_ref_id == ref.ref_id, "foreign_span_source")
            _text(row["partition"], "partition_required", 256)
            _require(hashlib.sha256(row["text"].encode()).hexdigest() == row["text_sha256"], "excerpt_hash_mismatch")
            _require(span.end_byte - span.start_byte == len(row["text"].encode()), "excerpt_bounds_mismatch")
            _require(span.span_id not in records, "duplicate_span_id")
            version = (ref.source_revision, ref.content_sha256)
            _require(ref.source_id not in documents or documents[ref.source_id] == version,
                "mixed_document_revisions")
            documents[ref.source_id] = version
            total += len(item._json.encode())
            _require(total <= 16_000_000, "context_index_byte_limit")
            records[span.span_id] = row
        links = []
        for edge in edges:
            _require(type(edge) is dict and set(edge) == {"source_span_id", "target_span_id", "relation"}, "closed_context_edge_required")
            _require(edge["source_span_id"] in records and edge["target_span_id"] in records, "dangling_context_edge")
            _require(edge["relation"] in RELATIONS, "unsupported_context_relation")
            links.append(dict(edge))
        links = sorted(links, key=lambda e: (e["source_span_id"], e["relation"], e["target_span_id"]))
        _require(len({context_digest(e) for e in links}) == len(links), "duplicate_context_edge")
        self._wire = json.dumps({"revision": revision, "spans": records, "edges": links}, sort_keys=True)
        self.index_sha256 = context_digest(json.loads(self._wire))
        self._lexical = {}
        for partition in sorted({r["partition"] for r in records.values()}):
            self._lexical[partition] = build_bm25_index([
                {"id": key, "text": row["text"]} for key, row in sorted(records.items()) if row["partition"] == partition])

    def to_dict(self):
        return json.loads(self._wire)

    def search(self, query, *, partition, top_k):
        return search_bm25_index(query, self._lexical[partition], top_k=top_k)


def _slots(slots):
    _require(type(slots) is list and 0 < len(slots) <= 32, "bounded_slots_required")
    result = []
    for slot in slots:
        _require(type(slot) is dict and set(slot) == {"slot_id", "question", "sort", "projection_ids"}, "closed_slot_required")
        _text(slot["slot_id"], "slot_id_required", 256)
        _text(slot["question"], "slot_question_required")
        _require(slot["sort"] in SLOT_SORTS, "unsupported_semantic_slot_sort")
        _require(type(slot["projection_ids"]) is list and 0 < len(slot["projection_ids"]) <= 40, "bounded_projection_ids_required")
        for projection in slot["projection_ids"]:
            _text(projection, "projection_id_required", 256)
        _require(len(set(slot["projection_ids"])) == len(slot["projection_ids"]), "duplicate_projection_id")
        result.append(json.loads(json.dumps(slot)))
    _require(len({s["slot_id"] for s in result}) == len(result), "duplicate_slot_id")
    return result


def prepare_context_bundle(index, *, source_span_id, slots, fixtures=(), sparse_observations=(), limits=None):
    """Return candidates plus optional explicit assumptions, never filled truth.

    The byte budget is global across slots; each excerpt is stored once. Local
    neighbors are ordered excerpts of the same exact document revision, not an
    assertion of governance. Graph traversal never invents a missing edge.
    """
    _guard_producers()
    _require(type(index) is BoundedContextIndex, "bounded_context_index_required")
    limits = limits or ContextLimits()
    limits.validate()
    declared = _slots(slots)
    _require(type(fixtures) in (list, tuple) and len(fixtures) <= len(declared), "bounded_fixtures_required")
    assumptions = {}
    for fixture in fixtures:
        _require(type(fixture) is dict and set(fixture) == {"slot_id", "value", "rationale"}, "closed_fixture_required")
        key = fixture["slot_id"]
        _require(key in {s["slot_id"] for s in declared} and key not in assumptions, "unknown_or_duplicate_fixture_slot")
        _text(fixture["rationale"], "fixture_rationale_required")
        _require(fixture["value"] is not None, "fixture_value_required")
        raw = json.dumps(fixture["value"], sort_keys=True, allow_nan=False)
        _require(len(raw.encode()) <= 4096, "fixture_value_byte_limit")
        assumptions[key] = {"origin": "provisional_fixture", "value": json.loads(raw),
            "rationale": fixture["rationale"], "source_backed": False}
    started = monotonic()
    data = index.to_dict()
    _require(source_span_id in data["spans"], "missing_selected_span")
    selected = data["spans"][source_span_id]
    partition = selected["partition"]
    _require(type(sparse_observations) in (list, tuple) and len(sparse_observations) <= 32, "bounded_sparse_observations_required")
    sparse = {}
    sparse_bytes = 0
    for observation in sparse_observations:
        _require(type(observation) is dict and observation.get("schema") == "pinned-sparse-context-retrieval/v1", "sparse_context_observation_required")
        sparse_bytes += len(json.dumps(observation, allow_nan=False).encode())
        _require(sparse_bytes <= 1_000_000, "sparse_observation_byte_limit")
        _require(context_digest({k: v for k, v in observation.items() if k != "report_sha256"}) == observation.get("report_sha256"), "sparse_observation_hash_mismatch")
        _require(observation.get("authority") == "context_only" and
            all(observation.get(k) is False for k in ("proof_authority", "qualified", "admitted", "source_semantics_verified", "slots_filled")),
            "sparse_context_cannot_grant_authority")
        _require(type(observation.get("revision")) is str and re.fullmatch(r"[0-9a-f]{40}", observation["revision"]) is not None,
            "pinned_sparse_revision_required")
        query = observation.get("query")
        _require(query in {s["question"] for s in declared} and query not in sparse, "unmatched_or_duplicate_sparse_query")
        _require(observation.get("partition") == partition, "foreign_sparse_partition")
        _require(type(observation.get("candidates")) is list and len(observation["candidates"]) <= 100, "bounded_sparse_candidates_required")
        for hit in observation["candidates"]:
            _require(type(hit) is dict and hit.get("span_id") in data["spans"], "unregistered_sparse_context")
            row = data["spans"][hit["span_id"]]
            _require(row["partition"] == partition and all(hit.get(k) == row[k] for k in ("text", "source_ref", "span", "partition")), "sparse_context_differs_from_index")
            _require(hit.get("excerpt_sha256") == row["text_sha256"], "sparse_excerpt_hash_mismatch")
            _require(hit.get("authority") == "context_only" and
                all(hit.get(k) is False for k in ("proof_authority", "qualified", "admitted", "source_semantics_verified", "slots_filled")),
                "sparse_candidate_cannot_grant_authority")
            _require(hit.get("corpus_repo_id") == observation.get("repo_id") and hit.get("corpus_revision") == observation["revision"],
                "sparse_candidate_corpus_mismatch")
            _require(type(hit.get("score")) in (int, float) and math.isfinite(hit["score"]), "finite_sparse_score_required")
        # Integrity is checked, but caller-supplied ranking provenance is not
        # upgraded to proof or source truth by this join.
        sparse[query] = json.loads(json.dumps(observation))
    candidates = {}
    diagnostics = []
    stats = {"bm25_queries": 0, "graph_visits": 0, "unique_context_bytes": 0}
    expired = lambda: monotonic() - started >= limits.max_seconds
    adjacency = {}
    for edge in data["edges"]:
        adjacency.setdefault(edge["source_span_id"], []).append(edge)
    shared = []
    same_source = sorted([key for key, row in data["spans"].items()
        if row["source_ref"] == selected["source_ref"] and row["partition"] == partition],
        key=lambda k: (data["spans"][k]["span"]["start_byte"], k))
    offset = same_source.index(source_span_id)
    for key in same_source[max(0, offset - limits.neighbor_radius):offset + limits.neighbor_radius + 1]:
        if key != source_span_id:
            shared.append((key, {"method": "neighbor", "relation": "adjacent_excerpt", "governing_scope_verified": False}))
    queue = deque([(source_span_id, [])])
    visited = {source_span_id}
    while queue and stats["graph_visits"] < limits.max_graph_visits and not expired():
        key, path = queue.popleft()
        stats["graph_visits"] += 1
        if len(path) >= limits.max_graph_hops:
            continue
        for edge in adjacency.get(key, []):
            target = edge["target_span_id"]
            if data["spans"][target]["partition"] != partition or target in visited:
                continue
            if len(visited) >= limits.max_graph_visits:
                diagnostics.append("graph_visit_limit")
                break
            visited.add(target)
            target_path = path + [edge]
            queue.append((target, target_path))
            shared.append((target, {"method": "explicit_graph", "path": target_path,
                "governing_scope_verified": False}))
    if queue:
        diagnostics.append("graph_traversal_incomplete")
    results = []
    lexical_cache = {}
    for slot in declared:
        found = []
        hits = []
        if not expired():
            if slot["question"] not in lexical_cache:
                stats["bm25_queries"] += 1
                lexical_cache[slot["question"]] = index.search(slot["question"], partition=partition,
                    top_k=min(4096, limits.max_candidates_per_slot + 1))
            hits = lexical_cache[slot["question"]]
        external = sparse.get(slot["question"])
        external_hits = [] if external is None else external["candidates"]
        if external is not None and external.get("status") == "partial":
            diagnostics.append("partial_sparse_retrieval:" + slot["slot_id"])
        proposed = shared + [(h["span_id"], {"method": "pinned_sparse_bm25", "score": h["score"],
            "observation_sha256": external["report_sha256"], "governing_scope_verified": False}) for h in external_hits]
        proposed += [(h["id"], {"method": "bm25", "score": h["score"],
            "governing_scope_verified": False}) for h in hits]
        positions = {}
        for key, reason in proposed:
            if expired():
                break
            if key == source_span_id:
                continue
            if key in positions:
                positions[key]["retrieval"].append(reason)
                continue
            if len(found) >= limits.max_candidates_per_slot:
                diagnostics.append("candidate_limit:" + slot["slot_id"])
                continue
            row = data["spans"][key]
            digest = context_digest(row)
            size = len(row["text"].encode())
            if digest not in candidates:
                if stats["unique_context_bytes"] + size > limits.max_context_bytes:
                    diagnostics.append("context_byte_limit")
                    continue
                candidates[digest] = row
                stats["unique_context_bytes"] += size
            candidate = {"span_id": key, "artifact_sha256": digest, "retrieval": [reason],
                "binding_status": "candidate_only"}
            positions[key] = candidate
            found.append(candidate)
        results.append({**slot, "status": "provisional" if slot["slot_id"] in assumptions else "unresolved",
            "source_resolved": False, "assumption": assumptions.get(slot["slot_id"]), "candidates": found})
    if expired():
        diagnostics.append("deadline_exhausted")
    request = {"source_span_id": source_span_id, "slots": declared,
        "fixtures": list(fixtures), "sparse_observations": list(sparse_observations), "limits": vars(limits)}
    report = {"schema": SCHEMA, "index_sha256": index.index_sha256,
        "producer_pins": dict(_PRODUCER_PINS),
        "index_revision": data["revision"], "request": request, "selected_source": selected,
        "artifacts": candidates, "slots": results, "diagnostics": sorted(set(diagnostics)),
        "telemetry": stats, "status": "incomplete" if diagnostics else "prepared",
        "source_resolved_slot_count": 0, "fixture_slot_count": len(assumptions),
        "external_index_partition_isolation_verified": False,
        "next_action": "review_scope_and_formalize_link_before_target_preparation", **AUTHORITY}
    report["bundle_sha256"] = context_digest(report)
    _guard_producers()
    return report


def validate_context_bundle(bundle, *, index):
    """Replay original indexed bytes, request and assumptions before consuming.

    Self-hashes are integrity identifiers, not trust. Budget-exhausted bundles
    cannot be consumed as complete. This validates retrieval, not interpretation.
    """
    _require(type(bundle) is dict and bundle.get("schema") == SCHEMA, "context_bundle_required")
    _require(bundle.get("status") == "prepared", "complete_context_retrieval_required")
    request = bundle["request"]
    expected = prepare_context_bundle(index, source_span_id=request["source_span_id"],
        slots=request["slots"], fixtures=request["fixtures"], sparse_observations=request["sparse_observations"],
        limits=ContextLimits(**request["limits"]))
    _require(expected == bundle, "context_bundle_differs_from_index_replay")
    return True
