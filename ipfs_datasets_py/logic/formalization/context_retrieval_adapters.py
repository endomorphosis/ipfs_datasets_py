"""Join pinned sparse retrieval hits to previously verified context spans.

The caller explicitly injects an existing search client; this module never
opens a client, downloads an index, embeds text, or invents canonical spans.
Ranking supplies context candidates only. It does not fill semantic slots.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re

SCHEMA = "pinned-sparse-context-retrieval/v1"
MAX_SPANS = 2048
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_RETURN_BYTES = 1024 * 1024
_REVISION = re.compile(r"[0-9a-f]{40}")
_FALSE = {"proof_authority": False, "source_semantics_verified": False,
          "slots_filled": False, "qualified": False, "admitted": False,
          "formalized": False, "enqueued": False, "roundtrip_ok": False,
          "execution_authority": False, "supervisor_importable": False}


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


@dataclass(frozen=True)
class SparseContextObservation:
    """Immutable detached retrieval observation, never validation authority."""
    _bytes: bytes

    def to_dict(self):
        return json.loads(self._bytes)

    def ranked_span_ids(self):
        """Existing context-index IDs and scores, with no fabricated span IDs."""
        return tuple((row["span_id"], row["score"]) for row in self.to_dict()["candidates"])


class PinnedSparseContextRetriever:
    """Adapt a public sparse BM25 method to an exact local context inventory.

    ``searcher`` is an explicitly supplied bound method such as
    ``OpenUsLawQueryClient.bm25_search`` or ``RemoteSearchClient.bm25_search``.
    Its owner must configure its own I/O/time limits and transport. This
    adapter bounds returned evidence; it cannot cancel arbitrary injected
    Python callables or retroactively bound their I/O.

    Entry bindings are exact ``{entry_cid, span_id}`` mappings scoped to one
    immutable repository revision. One corpus entry may bind several already
    verified spans. Hydrated source bytes must match every joined SourceRef.
    """

    def __init__(self, *, searcher, spans, entry_bindings, repo_id, revision):
        from .context_resolution import ContextSpan
        from ..ir_core.provenance import SourceRef, SourceSpan

        _require(callable(searcher), "explicit callable sparse searcher required")
        _require(type(repo_id) is str and 0 < len(repo_id) <= 512,
                 "explicit bounded corpus repository required")
        _require(type(revision) is str and _REVISION.fullmatch(revision) is not None,
                 "immutable forty-hex corpus revision required")
        _require(type(spans) in (list, tuple) and 0 < len(spans) <= MAX_SPANS,
                 "bounded verified context span inventory required")
        _require(all(type(span) is ContextSpan for span in spans), "native verified ContextSpan inputs required")
        by_id = {}
        inventory_bytes = 0
        for span in spans:
            wire = span.to_dict()
            ref, location = SourceRef.from_dict(wire["source_ref"]), SourceSpan.from_dict(wire["span"])
            _require(ref.to_dict() == wire["source_ref"] and location.to_dict() == wire["span"],
                     "context native provenance changed")
            _require(ref.review_status.value not in {"rejected", "quarantined"}
                     and location.source_ref_id == ref.ref_id, "context source binding refused")
            _require(type(wire["text"]) is str and _sha(wire["text"].encode()) == wire["text_sha256"]
                     and location.end_byte - location.start_byte == len(wire["text"].encode()),
                     "registered context excerpt identity differs")
            inventory_bytes += len(_raw(wire))
            _require(inventory_bytes <= MAX_RESPONSE_BYTES, "context inventory exceeds byte bound")
            identity = wire["span"]["span_id"]
            _require(identity not in by_id, "unique context span identities required")
            by_id[identity] = wire
        _require(type(entry_bindings) in (list, tuple) and 0 < len(entry_bindings) <= MAX_SPANS,
                 "bounded explicit corpus-entry bindings required")
        seen, entries = set(), {}
        for binding in entry_bindings:
            _require(type(binding) is dict and set(binding) == {"entry_cid", "span_id"},
                     "closed entry-to-span binding required")
            entry, span_id = binding["entry_cid"], binding["span_id"]
            _require(type(entry) is str and 0 < len(entry) <= 512 and span_id in by_id,
                     "existing context span and corpus entry identity required")
            _require((entry, span_id) not in seen, "duplicate entry-to-span binding")
            seen.add((entry, span_id))
            entries.setdefault(entry, []).append(span_id)
        self._searcher = searcher
        self._inventory = _raw(by_id)
        self._entries = _raw({key: sorted(value) for key, value in entries.items()})
        self._repo_id, self._revision = repo_id, revision
        self._binding_sha256 = _sha(_raw({"repo_id": repo_id, "revision": revision,
            "spans": by_id, "entry_bindings": json.loads(self._entries)}))

    def search(self, query, *, partition, top_k=8, max_bytes=64 * 1024):
        """Search once and return exact joined spans or explicit unresolved gaps.

        ``top_k`` bounds both requested remote hits and returned local spans.
        ``max_bytes`` bounds the complete serialized candidate rows, including
        their exact excerpts/provenance. Full remote response has a separate
        hard 16 MiB bound. Partial/budget-limited backend results stay partial.
        """
        _require(type(query) is str and 0 < len(query.encode()) <= 8192,
                 "bounded nonempty lexical query required")
        _require(type(partition) is str and 0 < len(partition) <= 256, "explicit retrieval partition required")
        _require(type(top_k) is int and 1 <= top_k <= 100, "top_k must be an integer from 1 to 100")
        _require(type(max_bytes) is int and 1 <= max_bytes <= MAX_RETURN_BYTES,
                 "bounded returned context bytes required")
        # No normalization, strip, lower, NFKC or synthesized text enters the
        # source identity path. The existing searcher may tokenize for ranking.
        response = self._searcher(query, top_k=top_k, hydrate=True, include_content=True)
        payload = response.to_dict() if hasattr(response, "to_dict") else response
        _require(type(payload) is dict, "structured sparse search result required")
        response_raw = _raw(payload)
        _require(len(response_raw) <= MAX_RESPONSE_BYTES, "sparse search response exceeds byte bound")
        payload = json.loads(response_raw)
        _require(payload.get("mode") == "bm25" and payload.get("query") == query,
                 "sparse result mode or exact query differs")
        trace = payload.get("fetch_trace")
        _require(type(trace) is dict and trace.get("repo_id") == self._repo_id
                 and trace.get("revision") == self._revision,
                 "sparse result corpus revision differs")
        _require(trace.get("route_justified") is True and trace.get("verification_state") in {"verified", "empty"},
                 "verified sparse fetch provenance required")
        rows = payload.get("results")
        _require(type(rows) is list and len(rows) <= top_k,
                 "sparse result exceeds requested top_k")
        _require(type(payload.get("complete")) is bool, "explicit sparse result completeness required")
        entries, inventory = json.loads(self._entries), json.loads(self._inventory)
        candidates, exclusions, encountered = [], [], set()
        for row in rows:
            _require(type(row) is dict, "structured sparse hit required")
            entry = row.get("entry_cid")
            _require(type(entry) is str and entry and entry not in encountered,
                     "unique explicit corpus entry hits required")
            encountered.add(entry)
            score = row.get("score")
            _require(type(score) in (int, float) and math.isfinite(score), "finite numeric retrieval score required")
            if entry not in entries:
                exclusions.append({"entry_cid": entry, "reason": "entry_not_bound_to_existing_context_inventory"})
                continue
            text = row.get("text")
            _require(type(text) is str, "raw hydrated corpus text required for a bound entry")
            source_bytes = text.encode()
            for span_id in entries[entry]:
                span = inventory[span_id]
                if span["partition"] != partition:
                    exclusions.append({"entry_cid": entry, "span_id": span_id, "reason": "partition_excluded"})
                    continue
                _require(_sha(source_bytes) == span["source_ref"]["content_sha256"],
                         "hydrated corpus bytes differ from registered source")
                offsets = span["span"]
                excerpt = source_bytes[offsets["start_byte"]:offsets["end_byte"]]
                _require(excerpt.decode() == span["text"], "hydrated excerpt differs from registered context span")
                candidates.append({"span_id": span_id, "entry_cid": entry, "score": score,
                    "retrieval_method": "pinned_sparse_bm25", "source_ref": span["source_ref"],
                    "span": offsets, "text": span["text"], "partition": span["partition"],
                    "corpus_repo_id": self._repo_id, "corpus_revision": self._revision,
                    "raw_source_sha256": _sha(source_bytes), "excerpt_sha256": _sha(excerpt),
                    "authority": "context_only", **_FALSE})
        candidates.sort(key=lambda item: (-item["score"], item["span_id"], item["entry_cid"]))
        accepted, used, bounded, seen_spans = [], 0, False, set()
        for candidate in candidates:
            if candidate["span_id"] in seen_spans:
                exclusions.append({"entry_cid": candidate["entry_cid"], "span_id": candidate["span_id"],
                    "reason": "duplicate_existing_context_span"})
                continue
            seen_spans.add(candidate["span_id"])
            size = len(_raw(candidate))
            if len(accepted) >= top_k or used + size > max_bytes:
                bounded = True
                exclusions.append({"entry_cid": candidate["entry_cid"], "span_id": candidate["span_id"],
                    "reason": "returned_context_top_k_or_byte_bound"})
                continue
            used += size
            accepted.append(candidate)
        result = {"schema": SCHEMA, "query": query, "partition": partition, "repo_id": self._repo_id, "revision": self._revision,
            "inventory_binding_sha256": self._binding_sha256, "backend_response_sha256": _sha(response_raw),
            "status": "partial" if bounded or not payload["complete"] else "candidates" if accepted else "unresolved",
            "backend_complete": payload["complete"], "backend_stop_reason": payload.get("stop_reason"),
            "backend_limits": payload.get("limits", {}), "backend_usage": payload.get("usage", {}),
            "fetch_trace": trace, "candidates": accepted, "exclusions": exclusions,
            "candidate_bytes": used, "max_candidate_bytes": max_bytes, "top_k": top_k,
            "search_calls": 1, "authority": "context_only", "transport_scope": "explicit_injected_client",
            "candidate_partition_filtered": True, "index_partition_isolated": False,
            "holdout_safe_claim": False,
            "slot_binding_policy": "retrieval_never_selects_a_semantic_interpretation",
            **_FALSE}
        result["report_sha256"] = _sha(_raw(result))
        return SparseContextObservation(_raw(result))


__all__ = ["SCHEMA", "PinnedSparseContextRetriever", "SparseContextObservation"]
