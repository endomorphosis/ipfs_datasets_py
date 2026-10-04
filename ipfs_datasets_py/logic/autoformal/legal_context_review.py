"""Source-first document review packets, without inventing legal references.

Structural coverage means every pinned paragraph is retained.  A locator edge
does not establish a semantic attachment.  Caller proposals remain unreviewed;
this module cannot authenticate reviewers, resolve legal meaning, or admit data.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

from . import legal_statutory_context as context
from . import legal_statutory_routing as routing

SCHEMA = "legal-document-context-review-packet/v1"
PROPOSAL_SCHEMA = "legal-document-attachment-proposals/v1"
EDGE_KINDS = ("definition_use", "exception", "condition", "applicability",
              "event_anchor", "coordination")
IDENTITY_KEYS = ("document_id", "legal_id", "edition", "source_url", "heading",
                 "html_sha256", "document_text_sha256", "offset_coordinate_system")
MAX_BYTES = 32 * 1024 * 1024


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def wire(value: Any) -> str:
    """Bound strict finite JSON, retaining bool/int/float distinctions."""
    def check(item):
        require(type(item) in (type(None), bool, int, float, str, list, dict), "JSON-native values required")
        if type(item) is dict:
            require(all(type(key) is str for key in item), "JSON string keys required")
            for child in item.values(): check(child)
        elif type(item) is list:
            for child in item: check(child)
    try:
        check(value)
        result = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (RecursionError, TypeError, OverflowError) as error:
        raise ValueError("bounded finite JSON required") from error
    require(len(result.encode("utf-8")) <= MAX_BYTES, "in-memory JSON exceeds byte budget")
    return result


def digest(value: Any) -> str:
    return context.sha(wire(value))


def file_ref(path: str | Path) -> dict:
    path = Path(path).resolve()
    require(path.is_file() and path.stat().st_size <= MAX_BYTES, "bounded local artifact required")
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def read_ref(pin: dict) -> Any:
    require(type(pin) is dict and set(pin) == {"path", "sha256", "bytes"}, "closed file reference required")
    require(wire(file_ref(pin["path"])) == wire(pin), "pinned artifact bytes differ")
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def nonfinite(_):
        raise ValueError("nonfinite JSON constant")
    return json.loads(Path(pin["path"]).read_text(), object_pairs_hook=unique, parse_constant=nonfinite)


def _pin_projection(pin: dict) -> dict:
    return {key: pin[key] for key in ("path", "sha256", "bytes")}


def _load_manifest(pin: dict) -> tuple[dict, list, dict]:
    manifest = read_ref(pin)
    require(manifest.get("schema") == "legal-official-uscode-diagnostic-manifest/v1",
            "official source manifest required")
    require(all(manifest.get(key) is False for key in
                ("views_are_independent_examples", "source_context_closed", "statutory_accuracy_available", "training_qualified")),
            "manifest authority or independence claim differs")
    documents, expected_sources = {}, []
    require(type(manifest["documents"]) is list and 0 < len(manifest["documents"]) <= 100,
            "bounded nonempty document inventory required")
    for item in manifest["documents"]:
        require(set(item) == {"document", "raw_html"}, "closed source document binding required")
        document = read_ref(item["document"])
        require(file_ref(item["raw_html"]["path"]) == item["raw_html"], "HTML bytes changed")
        raw = Path(item["raw_html"]["path"]).read_bytes()
        context.validate_document(document, raw)
        reconstructed = context.extract_document(raw, url=document["source_url"], edition=document["edition"],
                                                  legal_id=document["legal_id"])
        # BeautifulSoup's producer-owned class lists are list subclasses. Replay
        # their documented JSON representation; never normalize caller values.
        reconstructed = json.loads(json.dumps(reconstructed, ensure_ascii=False, allow_nan=False))
        require(wire(document) == wire(reconstructed), "document JSON types or source reconstruction differ")
        identity = document["document_id"]
        require(identity not in documents, "duplicate document identity")
        paths = [p["subsection_path"] for p in document["paragraphs"] if p["subsection_path"]]
        require(len(paths) == len(set(paths)), "ambiguous subsection locators require another profile")
        documents[identity] = (document, raw, item)
        expected_sources.extend(dict(row, document=item["document"])
                                for row in routing._expected_views(document))
    sources = read_ref(manifest["sources"])
    require(wire(sources) == wire(expected_sources), "source view inventory differs from complete document extraction")
    counts = {"documents": len(documents), "views": len(sources),
              "view_kinds": dict(Counter(s["kind"] for s in sources)),
              "distinct_texts": len({s["source_sha256"] for s in sources})}
    require(wire(manifest["counts"]) == wire(counts), "source manifest denominators differ")
    for producer in manifest["implementation"]:
        require(file_ref(producer["path"]) == producer, "source producer changed")
    return manifest, sources, documents


def _observation_inventory(audit_ref: dict | None, documents: dict) -> dict | None:
    if audit_ref is None:
        return None
    audit = read_ref(audit_ref)
    require(audit.get("schema") == "legal-uscode-source-context-recovery/v1"
            and audit.get("independent_gold") is False and audit.get("training_qualified") is False,
            "unreviewed recovered source audit required")
    observations_ref = _pin_projection(audit["artifacts"]["observations"])
    observations = read_ref(observations_ref)
    require(type(observations) is list and len(observations) <= 1000, "bounded observation inventory required")
    rows, seen, raw_cache = [], set(), {}
    for row in observations:
        identity = row["source_span_id"]
        require(type(identity) is str and identity and identity not in seen, "duplicate source observation identity")
        seen.add(identity)
        text = row["source_text"]
        require(context.sha(text) == row["source_text_sha256"], "observation source hash differs")
        require(row["independent_gold"] is False and row["training_qualified"] is False
                and row["legal_meaning_reference"] is None, "observation claims reviewed meaning")
        occurrences = row["exact_occurrences"]
        require(type(row["occurrence_count"]) is int and len(occurrences) == row["occurrence_count"] and len(occurrences) > 0,
                "observation occurrence count differs")
        occurrence_keys = set()
        for occurrence in occurrences:
            ref = _pin_projection(occurrence["raw_text_ref"])
            if ref["path"] not in raw_cache:
                require(file_ref(ref["path"]) == ref, "recovered raw source changed")
                raw_cache[ref["path"]] = (ref, Path(ref["path"]).read_text())
            require(raw_cache[ref["path"]][0] == ref, "conflicting raw source reference")
            raw = raw_cache[ref["path"]][1]
            start, end = occurrence["char_start"], occurrence["char_end"]
            require(type(start) is int and type(end) is int and 0 <= start < end <= len(raw)
                    and raw[start:end] == text, "recovered observation offset differs")
            require(all(type(occurrence[key]) is int for key in ("utf8_byte_start", "utf8_byte_end", "parquet_row_index"))
                    and occurrence["parquet_row_index"] >= 0
                    and occurrence["utf8_byte_start"] == len(raw[:start].encode())
                    and occurrence["utf8_byte_end"] == len(raw[:end].encode()), "raw byte/character coordinate mismatch")
            key = (ref["sha256"], occurrence["parquet_row_index"], start, end)
            require(key not in occurrence_keys, "duplicate exact occurrence")
            occurrence_keys.add(key)
        status = "unique_exact_occurrence" if len(occurrences) == 1 else "ambiguous_exact_occurrences"
        require(row["source_occurrence_status"] == status, "occurrence ambiguity status differs")
        selected = row["selected_occurrence"]
        require(selected is None if len(occurrences) > 1 else selected is None or wire(selected) == wire(occurrences[0]),
                "ambiguous occurrence must remain unselected")
        rows.append({"source_span_id": identity, "source_text": text,
                     "source_text_sha256": row["source_text_sha256"], "legal_ids": row["legal_ids"],
                     "source_occurrence_status": status, "exact_occurrences": occurrences,
                     "selected_occurrence": selected,
                     "candidate_official_document_ids": sorted(did for did, (d, _, _) in documents.items()
                                                                if d["legal_id"] in row["legal_ids"]),
                     "official_coordinate_mapping_verified": False,
                     "independent_gold": False, "training_qualified": False})
    counts = dict(Counter(r["source_occurrence_status"] for r in rows))
    require(wire(audit["counts"]["source_observations"]) == wire(len(rows))
            and wire(audit["counts"]["occurrence_status"]) == wire(counts), "recovery audit counts differ")
    return {"audit": audit_ref, "observations": observations_ref, "rows": rows,
            "counts": {"observations": len(rows), "distinct_source_texts": len({r["source_text_sha256"] for r in rows}),
                       "occurrence_status": counts},
            "join_policy": "Legal identity supplies candidate documents only; raw-parent offsets are not official visible-text offsets. Duplicate text and ambiguous occurrences retain separate identities."}


def _assemble(manifest_ref: dict, observation_audit_ref: dict | None) -> dict:
    manifest, sources, documents = _load_manifest(manifest_ref)
    packets = []
    for identity, (document, raw, pins) in documents.items():
        body = [p for p in document["paragraphs"] if p["kind"] == "codified_body"]
        by_path = {p["subsection_path"]: p for p in body if p["subsection_path"]}
        edges = []
        for paragraph in body:
            parent = paragraph["parent_path"]
            if parent is not None:
                require(parent in by_path, "missing structural parent")
                edges.append({"kind": "structural_parent", "parent_paragraph_index": by_path[parent]["paragraph_index"],
                              "child_paragraph_index": paragraph["paragraph_index"],
                              "semantic_attachment_inferred": False})
        references = routing._reference_evidence(document, body, origin="complete_codified_body")
        dependencies = []
        for reference in references:
            dependencies.append({"dependency_id": "dependency:" + digest({"document_id": identity, **reference}),
                                 **reference, "review_status": "unreviewed"})
        views = []
        for source in sources:
            if source["document_id"] == identity:
                route = routing.route_source(source, document, raw)
                views.append({"source": source, "routing_evidence": route,
                              "review_status": "awaiting_source_first_review"})
        packets.append({"identity": {key: document[key] for key in IDENTITY_KEYS}, "source_pins": pins,
                        "document_text": document["document_text"],
                        "codified_body": body,
                        "source_credits": [p for p in document["paragraphs"] if p["kind"] == "source_credit"],
                        "notes_or_other": [p for p in document["paragraphs"] if p["kind"] == "notes_or_other"],
                        "blocks": document["blocks"], "structural_edges": edges,
                        "dependency_inventory": dependencies, "diagnostic_views": views,
                        "proposed_attachments": [], "reviewer_records": [], "adjudication": None,
                        "reference_ir": None, "reference_logic_families": None,
                        "semantic_closure_verified": False, "training_qualified": False})
    return {"schema": SCHEMA, "source_manifest": manifest_ref,
            "implementation": [file_ref(__file__), file_ref(context.__file__), file_ref(routing.__file__)],
            "documents": packets, "observation_inventory": _observation_inventory(observation_audit_ref, documents),
            "counts": {"documents": len(packets), "body_paragraphs": sum(len(p["codified_body"]) for p in packets),
                       "source_credits": sum(len(p["source_credits"]) for p in packets),
                       "notes_or_other": sum(len(p["notes_or_other"]) for p in packets),
                       "diagnostic_views": len(sources), "distinct_view_texts": manifest["counts"]["distinct_texts"],
                       "structural_edges": sum(len(p["structural_edges"]) for p in packets),
                       "dependency_mentions": sum(len(p["dependency_inventory"]) for p in packets)},
            "candidate_predictions_included": False, "semantic_attachments_inferred": False,
            "review_status": "awaiting_external_source_first_review", "gold_available": False,
            "source_semantics_verified": False, "training_qualified": False,
            "all_documents_exposed_for_engineering": True, "heldout_accuracy_partition": False,
            "limitations": ["Structural completeness is not semantic completeness or external-reference closure.",
                            "Dependency mentions are a bounded lexical inventory, not exhaustive reference detection; full paragraph text and HTML links remain available for review.",
                            "All notes are retained separately; notes may themselves have legal effect.",
                            "Local reference resolution binds locators only, not legal dependencies.",
                            "Caller-proposed attachments require separate legal and formal-method review; identities and independence are not authenticated here.",
                            "Existing source-only decoders do not automatically consume these context bundles."]}


def build_packet(manifest_path: str | Path, *, observation_audit_path: str | Path | None = None) -> dict:
    result = _assemble(file_ref(manifest_path), file_ref(observation_audit_path) if observation_audit_path else None)
    wire(result)
    return result


def validate_packet(packet: dict, *, expected_manifest_ref: dict,
                    expected_observation_audit_ref: dict | None = None) -> dict:
    """Replay trusted input pins, including all paragraphs, descendants and views."""
    actual_wire = wire(packet)
    expected = _assemble(expected_manifest_ref, expected_observation_audit_ref)
    require(actual_wire == wire(expected), "packet differs from complete pinned source reconstruction")
    return {"schema": "legal-document-context-review-validation/v1", "packet_content_sha256": digest(packet),
            "source_manifest": expected_manifest_ref, "counts": packet["counts"],
            "all_paragraphs_and_views_replayed": True, "source_identity_verified": True,
            "independent_review_verified": False, "semantic_correctness_verified": False,
            "gold_targets_created": 0, "training_qualified": False}


def source_span(packet: dict, document_id: str, paragraph_index: int,
                char_start: int, char_end: int) -> dict:
    """Make a source coordinate record; calling this does not validate its meaning."""
    require(type(paragraph_index) is int, "integer paragraph identity required")
    matches = [d for d in packet["documents"] if d["identity"]["document_id"] == document_id]
    require(len(matches) == 1, "unambiguous packet document required")
    document = matches[0]
    paragraphs = document["codified_body"] + document["source_credits"] + document["notes_or_other"]
    matches = [p for p in paragraphs if p["paragraph_index"] == paragraph_index]
    require(len(matches) == 1, "unambiguous paragraph required")
    paragraph = matches[0]
    require(type(char_start) is int and type(char_end) is int
            and paragraph["char_start"] <= char_start < char_end <= paragraph["char_end"],
            "source span must be inside one exact paragraph")
    text = document["document_text"][char_start:char_end]
    return {"document_id": document_id, "edition": document["identity"]["edition"],
            "section_heading": document["identity"]["heading"], "source_url": document["identity"]["source_url"],
            "html_sha256": document["identity"]["html_sha256"],
            "document_text_sha256": document["identity"]["document_text_sha256"],
            "paragraph_index": paragraph_index, "char_start": char_start, "char_end": char_end,
            "text": text, "text_sha256": context.sha(text)}


def validate_attachment_proposals(packet: dict, proposals: dict, *, expected_manifest_ref: dict,
                                  expected_observation_audit_ref: dict | None = None) -> dict:
    """Validate proposed graph bindings, never adjudicate attachments or truth.

All dependencies of each participating full document remain explicitly pending,
including locally resolved locators. External dependencies cannot be relabelled
resolved by a caller. Proposals cannot replace the source-first blank packet.
"""
    wire(proposals)
    validate_packet(packet, expected_manifest_ref=expected_manifest_ref,
                    expected_observation_audit_ref=expected_observation_audit_ref)
    require(type(proposals) is dict and set(proposals) == {"schema", "packet_content_sha256", "edges"}
            and proposals["schema"] == PROPOSAL_SCHEMA and proposals["packet_content_sha256"] == digest(packet),
            "closed source-bound proposal bundle required")
    require(type(proposals["edges"]) is list and len(proposals["edges"]) <= 1000, "bounded proposal edges required")
    documents = {d["identity"]["document_id"]: d for d in packet["documents"]}
    edge_ids = set()
    for edge in proposals["edges"]:
        require(type(edge) is dict and set(edge) == {"edge_id", "kind", "from_span", "to_spans", "evidence_spans",
                "context_document_ids", "unresolved_dependency_ids", "interpretation_note", "status", "semantic_verified"},
                "closed attachment edge required")
        require(type(edge["edge_id"]) is str and 0 < len(edge["edge_id"]) <= 192
                and edge["edge_id"] not in edge_ids, "duplicate or invalid attachment identity")
        edge_ids.add(edge["edge_id"])
        require(edge["kind"] in EDGE_KINDS, "unsupported attachment kind")
        require(edge["status"] == "caller_proposed_unreviewed" and edge["semantic_verified"] is False,
                "caller cannot claim reviewed attachment")
        require(type(edge["interpretation_note"]) is str and 0 < len(edge["interpretation_note"].strip()) <= 4000,
                "bounded proposed interpretation explanation required")
        require(type(edge["to_spans"]) is list and 1 <= len(edge["to_spans"]) <= 128
                and type(edge["evidence_spans"]) is list and 1 <= len(edge["evidence_spans"]) <= 128,
                "attachment targets and evidence required")
        spans = [edge["from_span"]] + edge["to_spans"] + edge["evidence_spans"]
        for span in spans:
            require(type(span) is dict, "source span object required")
            expected = source_span(packet, span["document_id"], span["paragraph_index"], span["char_start"], span["char_end"])
            require(wire(span) == wire(expected), "attachment source/version/heading/span binding differs")
        for key in ("to_spans", "evidence_spans"):
            require(len({digest(s) for s in edge[key]}) == len(edge[key]), "duplicate attachment span")
        participating = sorted({s["document_id"] for s in spans})
        require(edge["context_document_ids"] == participating, "complete participating document contexts required")
        pending = sorted(r["dependency_id"] for did in participating for r in documents[did]["dependency_inventory"])
        require(edge["unresolved_dependency_ids"] == pending, "all document dependencies must remain pending")
    return {"schema": "legal-document-attachment-validation/v1", "packet_content_sha256": digest(packet),
            "proposal_content_sha256": digest(proposals), "edge_count": len(edge_ids),
            "source_bindings_verified": True, "semantic_attachments_verified": False,
            "independent_review_verified": False, "reference_ir": None, "training_qualified": False}
