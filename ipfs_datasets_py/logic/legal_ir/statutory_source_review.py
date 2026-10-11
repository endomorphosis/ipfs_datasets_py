"""Blank physical US Code source/context packets and copied-span geometry.

This distinct raw-section profile is neither the authored binding-review v1
profile nor the official-HTML context profile. It replays a pinned archived
view-provenance record and exact local UTF8 view bytes. The original Parquet
bytes, current legal authority, semantic attachments, reviewer declarations,
and completeness of historical exposure are not authenticated here.

Packets contain no candidate, target, completed review, or admission. A separate
explicit geometry API accepts caller-declared reviewed proposals; successful
geometry never verifies that review or promotes a training/evaluation mask.
No numerical library, encoder, model, parser, or compiler is executed. The two
lazy dependencies supply the unchanged SourceSpan type and lexical tokenizer.
File callers must reject duplicate JSON keys before passing dictionary inputs.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import unicodedata

SCHEMA = "statutory-physical-source-context-review-packet/v1"
VALIDATION_SCHEMA = "statutory-physical-source-context-review-validation/v1"
TEMPLATE_SCHEMA = "statutory-physical-source-context-review-template/v1"
GEOMETRY_SCHEMA = "statutory-caller-declared-review-geometry/v1"
GEOMETRY_PROFILE = "one-flat-deontic-exact-unique-nonoverlap-copied-facets/v1"
DIGEST_RECIPE = "sha256_sorted_compact_utf8_json_no_nan_no_newline"
NORMALIZED_GROUP_RECIPE = "NFKC_casefold_collapsed_whitespace_UTF8_SHA256"
ORIGIN_SCHEMA = "archived-uscode-raw-section-view-provenance/v1"
MAX_ROWS = 32
MAX_CONTEXT_ARTIFACTS = 16
MAX_CONTEXT_BYTES = 1024 * 1024
MAX_SELECTED_BYTES = 32 * 1024
MAX_METADATA_ARTIFACTS = 16
MAX_METADATA_BYTES = 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_JSON_NODES = 1_000_000
MAX_JSON_DEPTH = 24
SPAN_FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
EXPOSURE_STAGES = ("arbitrary-native384-input", "frozen-normative32-diagnostic",
    "frozen-retained-pointer-comparison", "source-only-review-packet-authored",
    "source-context-engineering-inspection", "declared-historical-exposure")
MASK_FIELDS = ("weak_decoder_fit", "strong_semantic_fit", "contrastive_supervision",
               "proof_supervision", "fidelity_evaluation")
REVIEW_FIELDS = ("normative_eligibility", "definition_status", "multi_rule_status",
    "interpretation_status", "normative_rules", "source_role_anchors",
    "qualifier_attachments", "trigger", "ambiguity", "unsupported_meaning",
    "freeform_qualifier_scope", "notes", "reviewer_id", "reviewed_at_utc")
CONTEXT_REVIEW_FIELDS = ("context_required_for_interpretation",
    "operative_versus_editorial_boundaries", "governing_definitions",
    "cross_references", "unresolved_dependencies", "context_sufficiency",
    "source_authority_or_currentness_evidence")
TARGET_FIELDS = ("target_codec", "target_sha256", "proposed_target", "facet_intervals",
                 "interpretation_profile", "reviewed_context_sha256", "decision")
AUTHORITY_FIELDS = ("qualified", "accepted", "admitted", "training_qualified",
    "semantic_gold", "source_semantics_verified", "source_authority_authenticated",
    "official_current_law_authenticated", "reviewer_identity_authenticated",
    "reviewer_independence_authenticated", "independent_review_completed",
    "actual_training_or_evaluation_admission", "fresh_holdout_qualified",
    "global_unseen_verified", "proof_authority", "family_bridge_admitted",
    "Lake_qualified", "model_executed", "encoder_executed", "training_executed")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ROW_FIELDS = {"id", "source_text", "source", "physical_origin", "context", "exposure"}
_SPAN_FIELDS = {"artifact", "source_kind", "release_id", "document_id", "language",
                "citation", "byte_start", "byte_end", "normalization"}
_CONTEXT_FIELDS = {"artifact", "selected_char_start", "selected_char_end",
                   "complete_raw_section", "normalization"}
_EXPOSURE_FIELDS = {"status", "prior_exposure_complete", "events"}
_EVENT_FIELDS = {"stage", "case_id", "source_text_sha256", "evidence_artifact"}
_ORIGIN_TOP_FIELDS = {"SourceSpan_contract_note", "all_selected_raw_spans_equal_historical_normalized_text",
    "artifacts", "findings", "historical_normalized_to_raw_crossjoin_checked_per_occurrence",
    "observed_at_utc", "original_pilot", "parent_parquet", "passed", "projected_read", "qualification",
    "raw_section_and_byte_slice_verified_before_writes", "rows", "schema", "source_count",
    "source_document_view_byte_cap", "source_document_view_total_bytes", "source_document_views_complete",
    "source_requests", "source_span_schema_owner"}
_ORIGIN_ROW_FIELDS = {"admitted", "citation", "complete_context_now_available_by_source_view",
    "encoder_token_limit_checked", "entry_cid", "formalized", "frontend", "historical_census_occurrence_id",
    "historical_document_batch_index", "historical_normalization_separate_from_request_normalization",
    "historical_normalized_source_sha256", "historical_source_section_span_ordinal", "historical_source_span_id",
    "historical_span_ordinal", "legal_id", "literal_newline_clause_policy", "native_cache_generated",
    "original_pilot_context_snippets_truncated", "parent_parquet", "physical_source_section_offset",
    "proof_authority", "raw_request_text_sha256", "raw_section_sha256", "raw_span_char_offsets",
    "raw_span_sha256", "raw_span_sha256_equals_historical_normalized_source_sha256",
    "raw_span_text_equals_historical_normalized_source_text", "raw_span_utf8_byte_offsets",
    "raw_span_utf8_bytes", "request_id", "request_literal_double_newline_segment_count",
    "request_text_equals_exact_raw_span", "section", "source_authority_authenticated", "source_kind",
    "source_semantics_verified", "source_view", "source_view_complete_raw_section", "source_view_normalization",
    "source_view_truncated", "target_attached", "title", "token_count", "training_qualified"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def _ordinary(value):
    remaining = MAX_JSON_NODES

    def visit(node, depth):
        nonlocal remaining
        remaining -= 1
        _require(remaining >= 0 and depth <= MAX_JSON_DEPTH, "bounded ordinary JSON required")
        if type(node) is dict:
            _require(all(type(key) is str for key in node), "ordinary JSON string keys required")
            for key, child in node.items():
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(node) is list:
            for child in node:
                visit(child, depth + 1)
        else:
            _require(node is None or type(node) in (str, int, bool),
                     "source-only ordinary JSON without floating scores required")

    visit(value, 0)


def _wire(value):
    _ordinary(value)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("bounded ordinary UTF8 JSON required") from error
    _require(len(raw) <= MAX_JSON_BYTES, "review JSON byte budget exceeded")
    return raw


def digest(value):
    """Canonical content SHA256; distinct from an original file-byte hash."""
    return hashlib.sha256(_wire(value)).hexdigest()


def _parse(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate JSON field")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (UnicodeError, RecursionError, ValueError, OverflowError) as error:
        raise ValueError("strict metadata UTF8 JSON required") from error
    _wire(value)
    return value


def _text(value, label, maximum=4096):
    _require(type(value) is str and value.strip() and "\x00" not in value,
             label + " must be nonempty text without NUL")
    try:
        _require(len(value.encode("utf-8")) <= maximum, label + " byte budget exceeded")
    except UnicodeError as error:
        raise ValueError(label + " must be valid UTF8") from error


def _sha(value, label):
    _require(type(value) is str and _SHA.fullmatch(value), label + " requires lowercase SHA256")


def _integer(value, label, minimum=0):
    _require(type(value) is int and minimum <= value < 2**63, label + " requires a bounded integer")


def _artifact(value, maximum, label):
    _closed(value, {"sha256", "bytes"}, label)
    _sha(value["sha256"], label + ".sha256")
    _integer(value["bytes"], label + ".bytes", 1)
    _require(value["bytes"] <= maximum, label + " byte budget exceeded")
    return deepcopy(value)


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _read(ref, resolver, maximum):
    """Bounded exact ordinary-file snapshot; paths are not content identities."""
    _artifact(ref, maximum, "local artifact")
    _require(callable(resolver), "artifact_resolver must be callable")
    try:
        supplied = resolver(deepcopy(ref))
        _require(type(supplied) in (str, Path) or isinstance(supplied, Path),
                 "resolver must return a local path, not bytes")
        path = Path(supplied)
        _require(path.is_absolute() and str(path.resolve(strict=True)) == str(path),
                 "canonical absolute artifact path required")
        for part in (path, *path.parents):
            _require(not part.is_symlink(), "artifact path aliases refused")
        before = os.lstat(path)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                 and before.st_size == ref["bytes"], "ordinary singly linked artifact of exact size required")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            _require(_identity(os.fstat(fd)) == _identity(before), "artifact changed before read")
            parts, count = [], 0
            while True:
                block = os.read(fd, min(1024 * 1024, ref["bytes"] - count + 1))
                if not block:
                    break
                count += len(block)
                _require(count <= ref["bytes"], "artifact grew during read")
                parts.append(block)
            _require(_identity(os.fstat(fd)) == _identity(before) == _identity(os.lstat(path)),
                     "artifact changed during read")
        finally:
            os.close(fd)
    except (OSError, TypeError, RuntimeError) as error:
        raise ValueError("artifact snapshot could not be read") from error
    raw = b"".join(parts)
    _require(len(raw) == ref["bytes"] and hashlib.sha256(raw).hexdigest() == ref["sha256"],
             "artifact bytes/SHA256 mismatch")
    return raw


def _source(value):
    _closed(value, _SPAN_FIELDS, "typed SourceSpan")
    _artifact(value["artifact"], MAX_CONTEXT_BYTES, "SourceSpan artifact")
    for field in _SPAN_FIELDS - {"artifact", "byte_start", "byte_end"}:
        _text(value[field], "SourceSpan " + field)
    for field in ("byte_start", "byte_end"):
        _integer(value[field], "SourceSpan " + field)
    # SourceSpan itself is a pure dataclass; its owner does not open a model.
    from ...optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import SourceSpan
    span = asdict(SourceSpan.from_dict(value))
    _require(_wire(span) == _wire(value), "typed SourceSpan serialization differs")
    _require(span["source_kind"] == "us_code" and span["normalization"] == "identity",
             "raw identity us_code SourceSpan required; frontend aliases refused")
    return span


def _lexical(text):
    # Reuse the actual retained source-token recipe, not an encoder tokenizer.
    from ...optimizers.logic_theorem_optimizer import legal_span_formula as owner
    result, byte_offset, char_offset = [], 0, 0
    for index, match in enumerate(owner._TOKEN_RE.finditer(text)):
        start = byte_offset + len(text[char_offset:match.start()].encode("utf-8"))
        end = start + len(match.group().encode("utf-8"))
        encoded = match.group().casefold().encode("utf-8")
        result.append({"index": index, "text": match.group(), "char_start": match.start(),
            "char_end": match.end(), "utf8_byte_start": start, "utf8_byte_end": end,
            "casefold_utf8_byte_ids": [value + 1 for value in encoded]})
        byte_offset = end
        char_offset = match.end()
    reasons = []
    if len(text) > owner.MAX_SOURCE_CHARACTERS:
        reasons.append("native_source_character_limit")
    if not result or len(result) > owner.MAX_SOURCE_TOKENS:
        reasons.append("native_source_lexical_token_limit")
    if any(len(token["casefold_utf8_byte_ids"]) > owner.MAX_TOKEN_BYTES for token in result):
        reasons.append("native_source_token_byte_limit")
    if not reasons:
        native = owner.tokenize_source(text)
        _require(native == [{"text": token["text"], "start": token["char_start"],
            "end": token["char_end"], "byte_ids": token["casefold_utf8_byte_ids"]} for token in result],
            "native lexical recipe replay differs")
    return {"recipe": "retained_Unicode_word_or_nonspace_punctuation_casefold_UTF8_byte_ids/v1",
        "recipe_owner_module": owner.__name__,
        "recipe_owner_code_sha256": hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest(),
        "token_coordinate_space": "selected_source_unicode_characters_and_UTF8_bytes",
        "tokens": result, "token_count": len(result), "truncated": False,
        "native_encoder_token_count": None, "native_encoder_token_limit_verified": False,
        "within_retained_lexical_transport_limits": not reasons, "transport_limit_issues": reasons,
        "semantics_or_target_representability_inferred": False}


def _origin(value, row, source, context, load_metadata):
    _closed(value, {"provenance_artifact", "provenance_record_id"}, "physical origin input")
    ref = _artifact(value["provenance_artifact"], MAX_METADATA_BYTES, "origin provenance artifact")
    _require(value["provenance_record_id"] == row["id"], "origin record and requested case ID differ")
    provenance = load_metadata(ref)
    _require(type(provenance) is dict and provenance.get("schema") == ORIGIN_SCHEMA
        and set(provenance) <= _ORIGIN_TOP_FIELDS
        and provenance.get("passed") is True
        and provenance.get("raw_section_and_byte_slice_verified_before_writes") is True
        and provenance.get("source_document_views_complete") is True,
        "pinned archived raw-section provenance profile required")
    records = provenance.get("rows")
    _require(type(records) is list and 1 <= len(records) <= MAX_ROWS,
             "bounded archived provenance rows required")
    _require(all(type(record) is dict and set(record) <= _ORIGIN_ROW_FIELDS
                 and type(record.get("request_id")) is str for record in records)
             and len({record["request_id"] for record in records}) == len(records),
             "unique archived provenance case IDs required")
    matches = [record for record in records if record["request_id"] == row["id"]]
    _require(len(matches) == 1, "physical source provenance case join missing")
    record = matches[0]
    fields = {"parent_parquet", "physical_source_section_offset", "raw_section_sha256",
        "raw_span_char_offsets", "raw_span_utf8_byte_offsets", "raw_span_sha256",
        "source_view", "legal_id", "citation", "source_kind", "source_view_normalization",
        "source_view_complete_raw_section", "source_view_truncated", "request_text_equals_exact_raw_span",
        "historical_census_occurrence_id", "historical_source_span_id",
        "historical_normalized_source_sha256", "raw_span_sha256_equals_historical_normalized_source_sha256",
        "raw_span_text_equals_historical_normalized_source_text", "frontend"}
    _require(fields <= set(record), "archived physical provenance fields missing")
    for name in ("admitted", "formalized", "proof_authority", "source_authority_authenticated",
                 "source_semantics_verified", "target_attached", "training_qualified"):
        _require(record.get(name) is False, "archived provenance must remain source-only unqualified")
    parent = record["parent_parquet"]
    _require(type(parent) is dict and {"sha256", "bytes", "repository_id", "revision", "release_id"} <= set(parent),
             "original export content pin and repository release required")
    parent_artifact = _artifact({key: parent[key] for key in ("sha256", "bytes")}, 2**63 - 1,
                                "original parent export identity")
    for name in ("repository_id", "release_id"):
        _text(parent[name], "original parent " + name)
    _require(type(parent["revision"]) is str and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", parent["revision"]),
             "immutable original parent revision required")
    _integer(record["physical_source_section_offset"], "physical source section offset")
    for name in ("historical_census_occurrence_id", "historical_source_span_id", "frontend"):
        _text(record[name], name)
    for name in ("raw_section_sha256", "raw_span_sha256", "historical_normalized_source_sha256"):
        _sha(record[name], name)
    raw_sha = hashlib.sha256(row["source_text"].encode("utf-8")).hexdigest()
    _require(record["raw_span_sha256"] == raw_sha
        and record["raw_section_sha256"] == source["artifact"]["sha256"]
        and record["legal_id"] == source["document_id"] and record["citation"] == source["citation"]
        and record["source_kind"] == source["source_kind"] and parent["release_id"] == source["release_id"],
        "physical provenance source identity mismatch")
    view = record["source_view"]
    _require(type(view) is dict and {"sha256", "bytes"} <= set(view)
        and _wire({key: view[key] for key in ("sha256", "bytes")}) == _wire(source["artifact"]),
        "physical provenance complete view identity mismatch")
    _require(record["source_view_normalization"] == "identity"
        and record["source_view_complete_raw_section"] is True and record["source_view_truncated"] is False
        and record["request_text_equals_exact_raw_span"] is True,
        "complete raw identity view declaration required")
    char_offsets = [context["selected_char_start"], context["selected_char_end"]]
    byte_offsets = [source["byte_start"], source["byte_end"]]
    _require(_wire(record["raw_span_char_offsets"]) == _wire(char_offsets)
        and _wire(record["raw_span_utf8_byte_offsets"]) == _wire(byte_offsets),
        "physical provenance selector mismatch")
    same_hash = raw_sha == record["historical_normalized_source_sha256"]
    _require(type(record["raw_span_sha256_equals_historical_normalized_source_sha256"]) is bool
        and record["raw_span_sha256_equals_historical_normalized_source_sha256"] is same_hash
        and type(record["raw_span_text_equals_historical_normalized_source_text"]) is bool,
        "historical normalized/raw crossjoin declaration mismatch")
    _require(not record["raw_span_text_equals_historical_normalized_source_text"] or same_hash,
             "declared historical/raw text equality disagrees with hashes")
    return {"provenance_artifact": ref, "provenance_record_id": row["id"],
        "parent_artifact": parent_artifact, "parent_repository_id": parent["repository_id"],
        "parent_revision": parent["revision"], "parent_release_id": parent["release_id"],
        "physical_source_section_offset": record["physical_source_section_offset"],
        "raw_section_sha256": record["raw_section_sha256"], "raw_span_char_offsets": char_offsets,
        "raw_span_utf8_byte_offsets": byte_offsets,
        "historical_occurrence_id": record["historical_census_occurrence_id"],
        "historical_source_span_id": record["historical_source_span_id"],
        "historical_normalized_source_sha256": record["historical_normalized_source_sha256"],
        "historical_normalized_and_raw_hash_equal": same_hash,
        "historical_normalized_and_raw_text_equal_declared":
            record["raw_span_text_equals_historical_normalized_source_text"],
        "frontend_provenance_only": record["frontend"], "view_bytes_and_selector_replayed": True,
        "origin_provenance_record_replayed": True, "parent_export_bytes_reverified": False,
        "original_export_locator_relationship_independently_verified": False,
        "historical_normalized_text_bytes_reverified": False,
        "official_HTML_coordinate_mapping_verified": False}


def _exposure(value, row, source_sha):
    _closed(value, _EXPOSURE_FIELDS, "source-only exposure ledger")
    _require(value["status"] in ("previously_exposed_development", "exposure_unknown_review_only")
        and value["prior_exposure_complete"] is False, "no unseen or complete-exposure claim supported")
    events = value["events"]
    _require(type(events) is list and len(events) <= 32, "bounded source exposure events required")
    _require(value["status"] != "previously_exposed_development" or events,
             "previous exposure requires declared linked events")
    identities = set()
    for event in events:
        _closed(event, _EVENT_FIELDS, "source-only exposure event")
        _require(type(event["stage"]) is str and event["stage"] in EXPOSURE_STAGES,
                 "closed source-only exposure stage required")
        _require(event["case_id"] == row["id"] and event["source_text_sha256"] == source_sha,
                 "exposure case/source linkage mismatch")
        # Pin metadata only: prediction bodies never enter a blank review packet.
        _artifact(event["evidence_artifact"], 2**63 - 1, "exposure evidence identity")
        identity = (event["stage"], event["evidence_artifact"]["sha256"])
        _require(identity not in identities, "duplicate source exposure event")
        identities.add(identity)
    return {**deepcopy(value), "evidence_bodies_opened": False,
        "evidence_content_case_join_verified": False, "claim_scope": "caller_declared_case_source_linkage_only",
        "model_candidate_content_included": False, "reviewer_blindness_verified": False,
        "evaluation_role": "review_only_development_source_not_independent_confirmation"}


def _false():
    return dict.fromkeys(AUTHORITY_FIELDS, False)


def _masks():
    return dict.fromkeys(MASK_FIELDS, 0)


def _instructions():
    return {"task": "Read the selected literal source and complete raw section before proposing interpretations.",
        "unanswered": "Null means unanswered. Empty lists or explicit absent findings require a later declared review; no such findings are assigned here.",
        "context": "Raw archived section bytes are available. Definitions, cross-references, operative/editorial boundaries, currentness and semantic sufficiency remain unanswered.",
        "coordinates": "Role anchors, if later proposed, use selected-source Unicode character half-open offsets. Full-context and SourceSpan UTF8 selectors remain separate.",
        "exposure": "Prior exposure is caller-declared and not exhaustively closed. No global unseen, reviewer-blindness or heldout claim is made.",
        "authority": "Byte checks, review declarations, agreement, geometry, family syntax and compiler checks cannot create legal gold or training/evaluation/proof admission.",
        "no_answers": "No candidate, target, parser answer, compiler proposal or suggested semantic annotation is supplied."}


def create_blank_packet(rows, *, artifact_resolver):
    """Create a bounded, portable blank packet from exact raw physical rows.

    Closed rows are documented in ``statutory-review-build.json``. The resolver
    accepts a path-free ``{sha256, bytes}`` content reference and returns an exact
    ordinary absolute path. Only raw section views and origin provenance JSON
    are read; original export and exposure-evidence bodies are never opened.
    """
    rows = _parse(_wire(rows))  # Detached immutable input snapshot; no caller aliases.
    _require(type(rows) is list and 1 <= len(rows) <= MAX_ROWS, "one to32 physical source rows required")
    contexts, metadata, items = {}, {}, []
    seen_cases, seen_physical, selected_bytes = set(), set(), 0

    def load_metadata(ref):
        key = ref["sha256"]
        if key not in metadata:
            _require(len(metadata) < MAX_METADATA_ARTIFACTS
                and sum(value["ref"]["bytes"] for value in metadata.values()) + ref["bytes"] <= MAX_METADATA_BYTES,
                "origin metadata closure exceeds budget")
            metadata[key] = {"ref": ref, "raw": _read(ref, artifact_resolver, MAX_METADATA_BYTES)}
        _require(metadata[key]["ref"] == ref, "metadata SHA/size drift")
        return _parse(metadata[key]["raw"])

    for row in rows:
        _closed(row, _ROW_FIELDS, "raw physical review row")
        _text(row["id"], "case ID", 512)
        _require(row["id"] not in seen_cases, "duplicate source case ID")
        _text(row["source_text"], "selected source", MAX_SELECTED_BYTES)
        selected = row["source_text"].encode("utf-8")
        selected_bytes += len(selected)
        _require(selected_bytes <= MAX_SELECTED_BYTES, "selected source aggregate budget exceeded")
        source = _source(row["source"])
        context = row["context"]
        _closed(context, _CONTEXT_FIELDS, "complete raw section context")
        ref = _artifact(context["artifact"], MAX_CONTEXT_BYTES, "complete context artifact")
        _require(ref == source["artifact"] and context["complete_raw_section"] is True
            and context["normalization"] == "identity", "same complete raw identity section context required")
        for field in ("selected_char_start", "selected_char_end"):
            _integer(context[field], "context " + field)
        key = ref["sha256"]
        if key not in contexts:
            _require(len(contexts) < MAX_CONTEXT_ARTIFACTS
                and sum(value["artifact"]["bytes"] for value in contexts.values()) + ref["bytes"] <= MAX_CONTEXT_BYTES,
                "complete context closure exceeds budget")
            raw = _read(ref, artifact_resolver, MAX_CONTEXT_BYTES)
            try:
                text = raw.decode("utf-8")
            except UnicodeError as error:
                raise ValueError("complete context must be strict UTF8") from error
            _require("\x00" not in text, "complete context NUL refused")
            contexts[key] = {"artifact": ref, "text": text, "raw": raw}
        _require(contexts[key]["artifact"] == ref, "context SHA/size drift")
        complete = contexts[key]["text"]
        start, end = context["selected_char_start"], context["selected_char_end"]
        _require(start < end <= len(complete) and complete[start:end] == row["source_text"],
                 "complete context character selector mismatch")
        _require(len(complete[:start].encode("utf-8")) == source["byte_start"]
            and len(complete[:end].encode("utf-8")) == source["byte_end"]
            and contexts[key]["raw"][source["byte_start"]:source["byte_end"]] == selected,
            "complete context UTF8 byte selector mismatch")
        origin = _origin(row["physical_origin"], row, source, context, load_metadata)
        physical = {"parent_artifact": origin["parent_artifact"],
            "physical_source_section_offset": origin["physical_source_section_offset"],
            "raw_section_sha256": origin["raw_section_sha256"],
            "raw_span_char_offsets": origin["raw_span_char_offsets"],
            "raw_span_utf8_byte_offsets": origin["raw_span_utf8_byte_offsets"]}
        physical_sha = digest(physical)
        _require(physical_sha not in seen_physical, "duplicate physical occurrence or cached source alias")
        source_sha = hashlib.sha256(selected).hexdigest()
        normalized = " ".join(unicodedata.normalize("NFKC", row["source_text"]).casefold().split())
        item_id = "statutory-physical-review-" + physical_sha
        items.append({"item_id": item_id, "input": deepcopy(row),
            "input_sha256": digest(row), "physical_identity_sha256": physical_sha,
            "source_text_sha256": source_sha,
            "normalized_source_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            "source": source, "physical_origin": origin,
            "context": {**deepcopy(context), "context_view_id": "sha256:" + key,
                "context_coordinate_space": "complete_raw_section_unicode_characters",
                "source_selector_coordinate_space": "complete_raw_section_UTF8_bytes",
                "complete_view_truncated": False, "context_semantically_adjudicated": False,
                "encoder_has_encoded_full_context": False},
            "lexical_source": _lexical(row["source_text"]),
            "prior_exposure": _exposure(row["exposure"], row, source_sha),
            "review": dict.fromkeys(REVIEW_FIELDS), "context_review": dict.fromkeys(CONTEXT_REVIEW_FIELDS),
            "target_binding": {"assignment_status": "unassigned", **dict.fromkeys(TARGET_FIELDS)},
            "representability": {"profile": GEOMETRY_PROFILE, "status": "not_assessed_no_reviewed_proposal",
                "source_interval_geometry_representable": None, "semantic_representability_verified": False},
            "reviewer_authentication": {"identity_evidence": None, "independence_evidence": None,
                                        "adjudication_evidence": None},
            "admission_masks": _masks(), **_false()})
        seen_cases.add(row["id"])
        seen_physical.add(physical_sha)
    # Recheck original bytes after all joins, not merely at the first read.
    for value in contexts.values():
        _require(_read(value["artifact"], artifact_resolver, MAX_CONTEXT_BYTES) == value["raw"],
                 "context changed across packet construction")
    for value in metadata.values():
        _require(_read(value["ref"], artifact_resolver, MAX_METADATA_BYTES) == value["raw"],
                 "origin metadata changed across packet construction")
    items.sort(key=lambda item: item["item_id"])
    duplicate_groups = {}
    for label, key in (("exact_source", "source_text_sha256"), ("normalized_source", "normalized_source_sha256")):
        groups = {}
        for item in items:
            groups.setdefault(item[key], []).append(item["item_id"])
        duplicate_groups[label] = [{"sha256": sha, "item_ids": ids} for sha, ids in sorted(groups.items()) if len(ids) > 1]
    body = {"schema": SCHEMA, "source_only": True, "instructions": _instructions(),
        "digest_recipe": DIGEST_RECIPE, "input_snapshot_policy": "canonical_input_copy_and_opening_closing_artifact_byte_checks",
        "items": items, "item_count": len(items), "selected_source_bytes": selected_bytes,
        "complete_context_bytes": sum(value["artifact"]["bytes"] for value in contexts.values()),
        "context_views": [{"context_view_id": "sha256:" + key, "artifact": value["artifact"],
            "text": value["text"], "normalization": "identity", "complete_raw_section": True,
            "semantic_sufficiency_verified": False} for key, value in sorted(contexts.items())],
        "origin_provenance_artifacts": [value["ref"] for _, value in sorted(metadata.items())],
        "duplicate_inventory": {"normalized_recipe": NORMALIZED_GROUP_RECIPE,
            **duplicate_groups, "physical_occurrences_merged": False,
            "source_section_family_split_independence_verified": False,
            "cross_reference_dependency_closure_verified": False, "global_duplicate_closure_verified": False},
        "human_labels": 0, "review_submissions": 0, "reviews_authenticated": 0,
        "admission_masks": _masks(), "authored_binding_v1_compatible": False,
        "official_HTML_context_profile_compatible": False, **_false()}
    return {**body, "content_sha256": digest(body)}


def validate_blank_packet(packet, *, expected_packet_sha256, artifact_resolver):
    """Exact reconstruction of the pinned blank snapshot and source closure."""
    packet = _parse(_wire(packet))
    _sha(expected_packet_sha256, "expected canonical packet SHA256")
    _require(digest(packet) == expected_packet_sha256, "blank packet canonical content pin mismatch")
    _require(type(packet) is dict and packet.get("schema") == SCHEMA and type(packet.get("items")) is list,
             "distinct physical source/context packet required")
    _require(all(type(item) is dict and "input" in item for item in packet["items"]),
             "blank packet source inputs missing")
    rebuilt = create_blank_packet([item["input"] for item in packet["items"]], artifact_resolver=artifact_resolver)
    _require(_wire(rebuilt) == _wire(packet), "blank packet reconstruction differs; annotations/masks/authority must remain blank")
    return {"schema": VALIDATION_SCHEMA, "status": "validated_blank_physical_source_context_only",
        "packet_sha256": expected_packet_sha256, "packet_content_sha256": packet["content_sha256"],
        "item_count": packet["item_count"], "complete_context_bytes": packet["complete_context_bytes"],
        "selected_source_bytes": packet["selected_source_bytes"], "local_source_bytes_and_selectors_verified": True,
        "origin_provenance_records_replayed": True, "original_export_bytes_reverified": False,
        "exposure_evidence_bodies_opened": False, "human_labels": 0,
        "admission_masks": _masks(), **_false()}


def review_template(packet, *, expected_packet_sha256, artifact_resolver):
    """Detached blank guidance, not a completed submission/admission API."""
    packet = _parse(_wire(packet))
    validate_blank_packet(packet, expected_packet_sha256=expected_packet_sha256,
                          artifact_resolver=artifact_resolver)
    return {"schema": TEMPLATE_SCHEMA, "packet_sha256": expected_packet_sha256,
        "instructions": _instructions(), "submission_recording_supported": False,
        "items": [{"item_id": item["item_id"], "source_text_sha256": item["source_text_sha256"],
            "context_artifact": deepcopy(item["context"]["artifact"]),
            "review": dict.fromkeys(REVIEW_FIELDS), "context_review": dict.fromkeys(CONTEXT_REVIEW_FIELDS),
            "target_binding": {"assignment_status": "unassigned", **dict.fromkeys(TARGET_FIELDS)},
            "representability_assessment": None,
            "reviewer_authentication": {"identity_evidence": None, "independence_evidence": None,
                                        "adjudication_evidence": None},
            "admission_masks": _masks(), **_false()} for item in packet["items"]],
        "absent_versus_unanswered": "null is unanswered; explicit absent findings have not been supplied",
        "admission_masks": _masks(), **_false()}


def assess_representability(packet, proposals, *, expected_packet_sha256, artifact_resolver):
    """Check only interval geometry of explicitly caller-declared review proposals.

    Proposals are separate from the immutable blank packet. Declaration and
    evidence bytes do not authenticate a reviewer, independence, legal truth,
    completeness, or eligibility. No canonical target or labels are produced.
    Anchors use selected-source Unicode character half-open coordinates.
    """
    packet = _parse(_wire(packet))
    validate_blank_packet(packet, expected_packet_sha256=expected_packet_sha256,
                          artifact_resolver=artifact_resolver)
    proposals = _parse(_wire(proposals))
    _require(type(proposals) is list and len(proposals) <= MAX_ROWS, "bounded explicit proposal list required")
    by_id = {item["item_id"]: item for item in packet["items"]}
    seen, results, evidence = set(), [], {}
    for proposal in proposals:
        _closed(proposal, {"item_id", "packet_sha256", "review_declaration", "interpretation_status", "rules"},
                "caller-declared reviewed geometry proposal")
        identity = proposal["item_id"]
        _text(identity, "proposal physical item ID", 512)
        _require(identity in by_id and identity not in seen and proposal["packet_sha256"] == expected_packet_sha256,
                 "proposal item/packet join mismatch or duplicate")
        item = by_id[identity]
        declaration = proposal["review_declaration"]
        _closed(declaration, {"status", "reviewer_id", "reviewed_at_utc", "evidence_artifact",
                              "source_text_sha256", "context_artifact_sha256"}, "unverified review declaration")
        _require(declaration["status"] == "caller_declared_source_context_reviewed_proposal",
                 "explicit source/context reviewed-proposal declaration required")
        for field in ("reviewer_id", "reviewed_at_utc"):
            _text(declaration[field], "declared " + field, 512)
        _require(declaration["source_text_sha256"] == item["source_text_sha256"]
            and declaration["context_artifact_sha256"] == item["context"]["artifact"]["sha256"],
            "review declaration source/context hash join mismatch")
        ref = _artifact(declaration["evidence_artifact"], MAX_METADATA_BYTES, "review declaration evidence")
        if ref["sha256"] not in evidence:
            _require(len(evidence) < MAX_METADATA_ARTIFACTS
                and sum(value["ref"]["bytes"] for value in evidence.values()) + ref["bytes"] <= MAX_METADATA_BYTES,
                "review declaration evidence closure exceeds budget")
            evidence[ref["sha256"]] = {"ref": ref, "raw": _read(ref, artifact_resolver, MAX_METADATA_BYTES)}
        _require(evidence[ref["sha256"]]["ref"] == ref, "review evidence SHA/size drift")
        status, rules = proposal["interpretation_status"], proposal["rules"]
        _require(status in ("normative", "no_normative_rule", "ambiguous", "unsupported"),
                 "explicit declared interpretation status required")
        _require(type(rules) is list and len(rules) <= 64, "bounded declared rule list required")
        _require(status == "normative" or not rules, "non-normative declaration must not supply rules")
        text, tokens = item["input"]["source_text"], item["lexical_source"]["tokens"]
        starts = {token["char_start"]: token["index"] for token in tokens}
        ends = {token["char_end"]: token["index"] for token in tokens}
        issues = list(item["lexical_source"]["transport_limit_issues"])
        if status == "normative" and len(rules) != 1:
            issues.append("requires_exactly_one_rule")
        for rule in rules:
            _closed(rule, {"modality", *SPAN_FIELDS}, "declared geometry rule")
            if rule["modality"] not in ("O", "P", "F") or type(rule["modality"]) is not str:
                issues.append("unsupported_modality")
            occupied = set()
            for facet in SPAN_FIELDS:
                anchors = rule[facet]
                _require(type(anchors) is list and len(anchors) <= 16, "bounded facet anchor list required")
                required_single = facet in ("actor", "action")
                if (required_single and len(anchors) != 1) or (not required_single and len(anchors) > 1):
                    issues.append("facet_cardinality:" + facet)
                for anchor in anchors:
                    _closed(anchor, {"coordinate_space", "char_start", "char_end", "text"}, "literal role anchor")
                    _require(anchor["coordinate_space"] == "selected_source_unicode_characters",
                             "selected-source character coordinate space required")
                    left, right = anchor["char_start"], anchor["char_end"]
                    _integer(left, "anchor char_start")
                    _integer(right, "anchor char_end")
                    _text(anchor["text"], "anchor literal text", MAX_SELECTED_BYTES)
                    _require(left < right <= len(text) and text[left:right] == anchor["text"],
                             "literal role anchor source selector mismatch")
                    if left not in starts or right not in ends:
                        issues.append("not_token_aligned:" + facet)
                        continue
                    matches, cursor = [], 0
                    while True:
                        offset = text.find(anchor["text"], cursor)
                        if offset < 0:
                            break
                        if offset in starts and offset + len(anchor["text"]) in ends:
                            matches.append(offset)
                        cursor = offset + 1
                    if len(matches) != 1:
                        issues.append("ambiguous_copied_surface:" + facet)
                    positions = set(range(starts[left], ends[right] + 1))
                    if occupied & positions:
                        issues.append("overlapping_copied_facets:" + facet)
                    occupied.update(positions)
        results.append({"item_id": identity, "proposal_sha256": digest(proposal),
            "review_declaration_evidence_artifact": ref, "review_declaration_verified": False,
            "geometry_status": "assessed_caller_declared_normative_geometry" if status == "normative"
                else "not_assessed_non_normative_declaration",
            "source_interval_geometry_representable": not issues if status == "normative" else None,
            "issues": sorted(set(issues)) if status == "normative" else [],
            "semantic_representability_verified": False, "target_created": False,
            "admission_masks": _masks(), **_false()})
        seen.add(identity)
    for value in evidence.values():
        _require(_read(value["ref"], artifact_resolver, MAX_METADATA_BYTES) == value["raw"],
                 "review evidence changed across geometry assessment")
    return {"schema": GEOMETRY_SCHEMA, "profile": GEOMETRY_PROFILE,
        "packet_sha256": expected_packet_sha256, "proposals_sha256": digest(proposals),
        "items": results, "not_assessed_item_ids": sorted(set(by_id) - seen),
        "review_declarations_authenticated": 0, "human_labels_created": 0,
        "admission_masks": _masks(), **_false()}
