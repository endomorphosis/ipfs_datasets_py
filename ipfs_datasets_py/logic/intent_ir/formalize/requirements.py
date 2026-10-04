"""Source accounting and candidate requirements from existing IntentIR reports.

This adapter does no inference. It retains native statements and rich compound
expressions exactly as reported, and gives unsupported source regions a durable
identity. Rebuilding a ledger checks its bindings and structure; it does not
replay numerical inference or verify a translation's meaning.
"""
from __future__ import annotations

import hashlib
import json
import math

SCHEMA = "intent-requirement-ledger@1"
REVIEWED_REPORT_SCHEMA = "intent-reviewed-source-report@1"
MAX_SOURCE_BYTES = 1_048_576
MAX_REPORT_BYTES = 32 * 1_048_576
MAX_SCOPE_EXPANSION_BYTES = MAX_REPORT_BYTES
MAX_UNITS = 4096
MAX_REQUIREMENTS = 4096
_AUTHORITY = {"semantic_alignment_verified": False, "proof_authority": False,
              "execution_authority": False, "completion_authority": False}
_REVIEW_FIELDS = {"schema", "source_sha256", "source_bytes", "source_characters",
    "producer", "interpretation_status", "units", "candidates", "proof_authority",
    "execution_authority", "completion_authority", "source_semantics_verified", "report_sha256"}
_REVIEW_UNIT_FIELDS = {"unit_id", "start_char", "end_char", "start_byte", "end_byte",
                       "text", "sha256", "disposition", "reason"}
_DOCUMENT_FIELDS = {"schema", "status", "source_sha256", "source_characters", "selection",
    "checkpoint_descriptor", "search_recovery", "units", "candidates", "counts",
    "continue_planning", "raw_instruction_preserved", "complete_document_formalization",
    "training_steps", "provider_calls", "download_calls", "producer_pins", "producer_sha256",
    "limitations", "proof_authority", "execution_authority", "completion_authority",
    "omission_authority", "source_semantics_verified", "combination_semantics_verified",
    "report_sha256"}
_RICH_FIELDS = {"schema", "status", "projection_mode", "composition_recovery",
    "grammar_search_recovery", "beam_width", "source_sha256", "checkpoint_descriptor",
    "selection", "units", "candidates", "counts", "lake_checks", "requested_families",
    "family_inventory", "raw_instruction_preserved", "training_steps", "llm_calls",
    "proof_authority", "execution_authority", "source_semantics_verified",
    "whole_document_formalized", "report_sha256"}
_SOURCE_FIELDS = {"schema", "source_path", "source_format", "language", "source_sha256",
    "source_bytes", "selection", "whole_source_context_supplied", "recover_context", "intent",
    "security_regions", "project_logic_families", "intent_family_projection", "routing_frontiers",
    "candidates", "lake_checks", "counts", "whole_document_formalized",
    "source_semantics_verified", "proof_authority", "execution_authority", "training_steps",
    "llm_calls", "download_calls", "status", "limitations", "report_sha256", "rich_intent",
    "rich_projection_enabled_by_checkpoint", "intent_family_validation"}
_DOCUMENT_UNIT_FIELDS = {"unit_id", "text", "normalized_text", "start_char", "end_char",
    "start_byte", "end_byte", "source_span", "block_kind", "full_block", "heading_context",
    "structural_context", "complete_source_unit", "status", "reason", "scope", "inference",
    "source_agreement", "greedy_inference", "model_input_normalization", "accepted",
    "proof_authority", "execution_authority", "completion_authority", "omission_authority",
    "source_semantics_verified", "combination_semantics_verified"}
_RICH_UNIT_FIELDS = {"unit_id", "text", "normalized_text", "start_char", "end_char", "start_byte",
    "end_byte", "accepted", "inference", "scope", "status", "reason", "selected_projections",
    "atomic_family_projection", "selected_native_targets", "decoding_method"}
_NATIVE_CANDIDATE_FIELDS = {"unit_id", "start_char", "end_char", "candidate_intent_ir", "projections",
    "extended_projections", "inference_report_sha256", "proof_authority", "execution_authority",
    "completion_authority", "omission_authority", "source_semantics_verified",
    "combination_semantics_verified"}
_RICH_CANDIDATE_FIELDS = {"unit_id", "start_char", "end_char", "rich_ir", "inference_report_sha256"}
_SOURCE_BASE_FIELDS = _SOURCE_FIELDS - {"status", "limitations", "rich_intent",
    "rich_projection_enabled_by_checkpoint", "intent_family_validation"}


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _bounded_json(value, *, max_bytes=MAX_REPORT_BYTES):
    """Reject non-JSON values, cycles, excessive nesting, and non-string keys."""
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 64 or count > 500_000:
            raise ValueError("bounded JSON structure required")
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ValueError("JSON object keys must be strings")
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) not in (str, int, float, bool, type(None)):
            raise ValueError("exact JSON types required")
        elif type(item) is float and not math.isfinite(item):
            raise ValueError("finite JSON numbers required")
    raw = _wire(value)
    if len(raw) > max_bytes:
        raise ValueError("JSON envelope exceeds its byte limit")
    return json.loads(raw)


def _require_text(value, label, *, maximum=1024):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError(f"bounded nonempty {label} required")
    return value


def _identity(source_identity):
    if type(source_identity) is str:
        return _require_text(source_identity, "source identity", maximum=4096)
    if type(source_identity) is not dict or not source_identity:
        raise ValueError("nonempty source identity string or object required")
    return _bounded_json(source_identity, max_bytes=16_384)


def _check_report(report, source_text):
    schema = report.get("schema")
    if type(schema) is not str:
        raise ValueError("declared source report schema required")
    fields = {REVIEWED_REPORT_SCHEMA: _REVIEW_FIELDS,
              "intent-document-roundtrip/v1": _DOCUMENT_FIELDS,
              "intent-rich-document/v1": _RICH_FIELDS,
              "source-document-autoencoder/v1": _SOURCE_FIELDS}.get(schema)
    mandatory = {REVIEWED_REPORT_SCHEMA: _REVIEW_FIELDS,
                 "intent-document-roundtrip/v1": _DOCUMENT_FIELDS,
                 "intent-rich-document/v1": _RICH_FIELDS,
                 "source-document-autoencoder/v1": _SOURCE_BASE_FIELDS}.get(schema, set())
    if fields is None or set(report) - fields or not mandatory <= set(report):
        raise ValueError("supported closed Intent source report required")
    if report.get("source_sha256") != _sha(source_text.encode("utf-8")):
        raise ValueError("source report is bound to a different original source")
    for key in ("source_bytes", "source_characters"):
        if key in report:
            expected = len(source_text.encode("utf-8")) if key == "source_bytes" else len(source_text)
            if type(report[key]) is not int or report[key] != expected:
                raise ValueError("source report size differs from the original source")
    for key in ("proof_authority", "execution_authority", "completion_authority",
                "source_semantics_verified", "omission_authority", "combination_semantics_verified"):
        if key in report and report[key] is not False:
            raise ValueError("source report must retain candidate-only authority")
    if report.get("report_sha256") != _sha(_wire({k: v for k, v in report.items() if k != "report_sha256"})):
        raise ValueError("source report identity mismatch")
    if "selection" in report:
        selection = report["selection"]
        if type(selection) is not dict:
            raise ValueError("exact source report selection required")
        left, right = selection.get("start_char"), selection.get("end_char")
        if (type(left) is not int or type(right) is not int
                or not 0 <= left <= right <= len(source_text)):
            raise ValueError("exact source report selection span required")
        selection_fields = {"start_char", "end_char", "start_byte", "end_byte", "sha256"}
        if schema != "source-document-autoencoder/v1":
            selection_fields.update({"text", "normalized_text"})
            if schema == "intent-rich-document/v1":
                selection_fields.remove("sha256")
        if set(selection) != selection_fields:
            raise ValueError("complete closed source report selection required")
        expected = {"start_byte": len(source_text[:left].encode()),
                    "end_byte": len(source_text[:right].encode()),
                    "text": source_text[left:right], "sha256": _sha(source_text[left:right].encode())}
        for key, value in expected.items():
            if key in selection and (type(selection[key]) is not type(value) or selection[key] != value):
                raise ValueError("source report selection differs from original source")
    if schema == REVIEWED_REPORT_SCHEMA:
        if set(report) != _REVIEW_FIELDS or report["interpretation_status"] != "reviewed_candidate":
            raise ValueError("closed reviewed candidate report required")
        producer = report["producer"]
        if type(producer) is not dict or set(producer) != {"name", "revision"}:
            raise ValueError("explicit reviewed report producer required")
        for key in producer:
            _require_text(producer[key], "producer " + key)
        if "PromptIntentAdapter" in producer["name"]:
            raise ValueError("whole prompt wrappers cannot qualify requirement decomposition")
    return schema


def _selector(source_text, left, right):
    if (type(left) is not int or type(right) is not int
            or not 0 <= left < right <= len(source_text)):
        raise ValueError("exact nonempty source unit character span required")
    text = source_text[left:right]
    return {"start_char": left, "end_char": right,
            "start_byte": len(source_text[:left].encode("utf-8")),
            "end_byte": len(source_text[:right].encode("utf-8")),
            "text": text, "sha256": _sha(text.encode("utf-8"))}


def _native(document, unit, source_text, *, reviewed):
    from ..decoder import decode_intent_ir
    from ..canonicalize import canonical_intent_ir_bytes

    native = decode_intent_ir(document)
    if not native.statements or any(not statement.source_ref_ids for statement in native.statements):
        raise ValueError("native requirements need source-bound statements")
    # The generic prompt adapter records a request with an opaque whole prompt
    # goal and no predicate. That wrapper is not requirement extraction.
    if (any(action.actor == "user" and action.verb == "request" for action in native.actions)
            and all(not statement.predicate for statement in native.statements)):
        raise ValueError("whole prompt wrappers cannot qualify requirement decomposition")
    unit_text = unit["text"]
    normalized = " ".join(unit_text.split())
    hashes = {_sha(unit_text.encode()), _sha(normalized.encode())}
    full_hash = _sha(source_text.encode())
    referenced = {ref for statement in native.statements for ref in statement.source_ref_ids}
    for source in native.sources:
        if source.ref_id not in referenced:
            continue
        span = source.span
        if span is None:
            raise ValueError("native requirement references need explicit source spans")
        local = (source.content_sha256 in hashes and span.start_char == 0
                 and span.end_char in {len(unit_text), len(normalized)})
        global_ = (source.content_sha256 == full_hash
                   and unit["start_char"] <= span.start_char < span.end_char <= unit["end_char"])
        if not local and not global_:
            raise ValueError("native requirement source reference is not bound to its source unit")
    if not reviewed:
        # Reuse the native codec's bounded lexical check; do not infer slots.
        from .roundtrip import intent_ir_to_frame
        from .document_roundtrip import assess_frame_source_agreement
        frame = intent_ir_to_frame(native)
        if not assess_frame_source_agreement(normalized, frame)["matched"]:
            raise ValueError("native requirement differs from its reported source surface")
    return native, _sha(canonical_intent_ir_bytes(native))


def _native_scope(native):
    """Keep action/control relations visible until a planner supports them."""
    if (len(native.actions) <= 1 and not native.control_edges
            and all(not getattr(action, field) for action in native.actions
                    for field in ("precondition_ids", "effect_ids", "verification_ids",
                                  "tool_refs", "input_refs", "output_refs"))):
        return None
    return {"schema": "intent-native-requirement-scope@1",
            "actions": [action.to_dict() for action in native.actions],
            "control_edges": [edge.to_dict() for edge in native.control_edges],
            "entry_action_ids": list(native.entry_action_ids),
            "terminal_action_ids": list(native.terminal_action_ids)}


def _requirement(unit_id, *, representation, document_hash, document_id,
                 statement_ids, kind, modality, status, compound):
    record = {"source_unit_id": unit_id, "representation": representation,
              "native_document_sha256": document_hash, "native_document_id": document_id,
              "statement_ids": statement_ids, "kind": kind, "modality": modality,
              "semantic_support": "candidate", "interpretation_status": status,
              "compound": compound}
    return {"requirement_id": "intent-requirement:" + _sha(_wire(record)), **record}


def _extract(source_text, report):
    schema = _check_report(report, source_text)
    if schema == "source-document-autoencoder/v1":
        if report.get("rich_intent") is not None and report.get("intent") is not None:
            raise ValueError("source report cannot silently select between two Intent inventories")
        selected = report.get("rich_intent") or report.get("intent")
        if selected is None:
            return [], []
        if type(selected) is not dict:
            raise ValueError("nested Intent report required")
        expected_schema = "intent-rich-document/v1" if report.get("rich_intent") is not None else "intent-document-roundtrip/v1"
        if selected.get("schema") != expected_schema:
            raise ValueError("native source report needs its declared native Intent frontend")
        return _extract(source_text, selected)
    if type(report.get("units")) is not list or len(report["units"]) > MAX_UNITS:
        raise ValueError("bounded source unit inventory required")
    if type(report.get("candidates")) is not list or len(report["candidates"]) > MAX_REQUIREMENTS:
        raise ValueError("bounded candidate inventory required")
    reviewed = schema == REVIEWED_REPORT_SCHEMA
    units, lookup = [], {}
    previous_end = 0
    for original in report["units"]:
        if type(original) is not dict:
            raise ValueError("source unit object required")
        if not {"unit_id", "start_char", "end_char", "start_byte", "end_byte", "text"} <= set(original):
            raise ValueError("complete exact source unit selector required")
        if original.get("inference") is not None and type(original["inference"]) is not dict:
            raise ValueError("source unit inference must be an object or null")
        if reviewed and set(original) != _REVIEW_UNIT_FIELDS:
            raise ValueError("closed reviewed source unit required")
        allowed_unit_fields = _REVIEW_UNIT_FIELDS if reviewed else (
            _RICH_UNIT_FIELDS if schema == "intent-rich-document/v1" else _DOCUMENT_UNIT_FIELDS)
        required_unit_fields = allowed_unit_fields - ({"decoding_method"} if schema == "intent-rich-document/v1" else set())
        if set(original) - allowed_unit_fields or not required_unit_fields <= set(original):
            raise ValueError("complete closed source unit fields required")
        unit_id = _require_text(original.get("unit_id"), "source unit ID")
        if unit_id in lookup:
            raise ValueError("duplicate source unit ID")
        selector = _selector(source_text, original.get("start_char"), original.get("end_char"))
        selection = report.get("selection")
        if selection is not None and not selection["start_char"] <= selector["start_char"] < selector["end_char"] <= selection["end_char"]:
            raise ValueError("source unit lies outside the report selection")
        if selector["start_char"] < previous_end:
            raise ValueError("source units must be ordered and nonoverlapping")
        for key, expected in selector.items():
            if key in original and (type(original[key]) is not type(expected) or original[key] != expected):
                raise ValueError("source unit selector differs from exact original slice")
        previous_end = selector["end_char"]
        reason = original.get("reason") or original.get("status") or "source_unit_not_interpreted"
        _require_text(reason, "source unit reason", maximum=4096)
        disposition = (original["disposition"] if reviewed else
                       "non_requirement" if not selector["text"].strip() else "unsupported")
        if type(disposition) is not str or disposition not in {"interpreted_candidate", "unsupported", "non_requirement"}:
            raise ValueError("declared source unit disposition required")
        unit = {"unit_id": unit_id, **selector, "disposition": disposition,
                "unsupported_reason": None if disposition == "non_requirement" else reason,
                "requirement_ids": []}
        units.append(unit)
        lookup[unit_id] = (unit, original)
    requirements, candidate_ids = [], set()
    scope_expansion_bytes = 0
    for candidate in report["candidates"]:
        if type(candidate) is not dict:
            raise ValueError("candidate object required")
        unit_id = _require_text(candidate.get("unit_id"), "candidate source unit ID")
        if unit_id not in lookup:
            raise ValueError("candidate references a dangling source unit ID")
        if unit_id in candidate_ids:
            raise ValueError("duplicate candidate source unit ID")
        candidate_ids.add(unit_id)
        unit, original = lookup[unit_id]
        allowed_candidate_fields = ({"unit_id", "candidate_intent_ir"} if reviewed else
            _RICH_CANDIDATE_FIELDS
            if schema == "intent-rich-document/v1" else _NATIVE_CANDIDATE_FIELDS)
        if set(candidate) != allowed_candidate_fields:
            raise ValueError("complete closed candidate fields required")
        for key in ("proof_authority", "execution_authority", "completion_authority", "omission_authority",
                    "source_semantics_verified", "combination_semantics_verified"):
            if key in candidate and candidate[key] is not False:
                raise ValueError("candidate must retain candidate-only authority")
        if reviewed:
            if set(candidate) != {"unit_id", "candidate_intent_ir"} or unit["disposition"] != "interpreted_candidate":
                raise ValueError("closed reviewed candidate and interpreted unit required")
        elif original.get("accepted") is not True:
            raise ValueError("candidate references an unaccepted source unit")
        if not reviewed:
            inference = original["inference"]
            if type(inference) is not dict or candidate["inference_report_sha256"] != inference.get("report_sha256"):
                raise ValueError("candidate needs its explicitly bound inference report")
            if type(original["scope"]) is not dict or original["scope"].get("eligible_for_inference") is not True:
                raise ValueError("candidate needs an explicitly eligible source scope")
            if schema == "intent-rich-document/v1":
                if original["scope"] != {"eligible_for_inference": True, "complete_source_consumption": True}:
                    raise ValueError("rich candidate needs complete source scope")
            elif (original["complete_source_unit"] is not True
                  or type(original["source_agreement"]) is not dict
                  or original["source_agreement"].get("matched") is not True):
                raise ValueError("native candidate needs complete source and declared source agreement")
        for key in ("start_char", "end_char"):
            if key in candidate and (type(candidate[key]) is not int or candidate[key] != unit[key]):
                raise ValueError("candidate source span differs from its unit")
        status = "reviewed_candidate" if reviewed else "source_supported_candidate"
        if "rich_ir" in candidate:
            from .rich_grammar import validate_ast, parse_instruction
            rich = candidate["rich_ir"]
            if type(rich) is not dict or set(rich) != {"schema", "ast", "source_sha256"} or rich["schema"] != "intent-rich-ir/v1":
                raise ValueError("closed rich candidate required")
            ast = validate_ast(rich["ast"])
            if original["inference"].get("rich_ir") != rich:
                raise ValueError("rich candidate differs from its source unit inference")
            normalized = " ".join(unit["text"].split())
            if rich["source_sha256"] != _sha(normalized.encode()) or ast != parse_instruction(normalized):
                raise ValueError("rich candidate differs from its reported source surface")
            logic = (original.get("inference") or {}).get("logic")
            if logic is not None and type(logic) is not dict:
                raise ValueError("rich inference logic must be an object or null")
            native_wire = (logic or {}).get("native_intent_ir")
            native, digest = (None, None)
            if native_wire is not None:
                native, digest = _native(native_wire, unit, source_text, reviewed=True)
                if ast["kind"] not in {"atom", "then"}:
                    raise ValueError("rich compound cannot acquire a flattened native document")
                from .rich_logic import _native_document
                if native.to_dict() != _native_document(ast, normalized).to_dict():
                    raise ValueError("rich candidate native view differs from its AST")
            if ast["kind"] == "atom" and native is not None:
                for statement in native.statements:
                    requirements.append(_requirement(unit_id, representation="native_statement",
                        document_hash=digest, document_id=native.document_id,
                        statement_ids=[statement.statement_id], kind=statement.kind.value,
                        modality=statement.modality.value, status=status, compound=None))
            else:
                requirements.append(_requirement(unit_id, representation="rich_ast",
                    document_hash=digest, document_id=native.document_id if native else None,
                    statement_ids=[s.statement_id for s in native.statements] if native else [],
                    kind=ast["kind"], modality="compound", status=status, compound=rich))
        else:
            if "candidate_intent_ir" not in candidate:
                raise ValueError("native candidate document required")
            inference = original.get("inference")
            if inference is not None and inference.get("candidate_intent_ir") != candidate["candidate_intent_ir"]:
                raise ValueError("native candidate differs from its source unit inference")
            native, digest = _native(candidate["candidate_intent_ir"], unit, source_text, reviewed=reviewed)
            scope = _native_scope(native)
            if scope is not None:
                # Reserve half the ledger bound for embedded source evidence
                # and other fields. Check repetition before hashing each row.
                scope_expansion_bytes += len(_wire(scope)) * len(native.statements)
                if scope_expansion_bytes > MAX_SCOPE_EXPANSION_BYTES:
                    raise ValueError("native requirement scope expansion exceeds its byte limit")
            for statement in native.statements:
                requirements.append(_requirement(unit_id, representation="native_statement",
                    document_hash=digest, document_id=native.document_id,
                    statement_ids=[statement.statement_id], kind=statement.kind.value,
                    modality=statement.modality.value, status=status, compound=scope))
        unit_requirements = [r["requirement_id"] for r in requirements if r["source_unit_id"] == unit_id]
        if not unit_requirements:
            raise ValueError("interpreted source unit needs at least one requirement")
        unit.update(disposition="interpreted_candidate", unsupported_reason=None, requirement_ids=unit_requirements)
    if any(u["disposition"] == "interpreted_candidate" and not u["requirement_ids"] for u in units):
        raise ValueError("interpreted source unit has no candidate")
    return units, requirements


def build_intent_requirement_ledger(source_text, *, source_report, source_identity):
    """Build a bounded candidate ledger without running a parser or model frontend.

    Supported inputs are existing native document/rich/source-document reports,
    or an explicitly labeled reviewed native fixture. The complete report is
    embedded so validation can deterministically reconstruct the ledger.
    """
    if type(source_text) is not str or not source_text or len(source_text.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("bounded exact UTF-8 source text required")
    if type(source_report) is not dict:
        raise ValueError("source report object required")
    report = _bounded_json(source_report)
    identity = _identity(source_identity)
    units, requirements = _extract(source_text, report)
    # Partial reports and unsupported source formats still account for the whole
    # original source. A missing region remains visible as an unresolved frontier.
    complete_units, cursor = [], 0
    for unit in units:
        if cursor < unit["start_char"]:
            selector = _selector(source_text, cursor, unit["start_char"])
            complete_units.append({"unit_id": "intent-unreported-unit:" + _sha(_wire(selector)),
                **selector, "disposition": "non_requirement" if not selector["text"].strip() else "unsupported",
                "unsupported_reason": None if not selector["text"].strip() else "outside_reported_intent_inventory",
                "requirement_ids": []})
        complete_units.append(unit)
        cursor = unit["end_char"]
    if cursor < len(source_text):
        selector = _selector(source_text, cursor, len(source_text))
        complete_units.append({"unit_id": "intent-unreported-unit:" + _sha(_wire(selector)),
            **selector, "disposition": "non_requirement" if not selector["text"].strip() else "unsupported",
            "unsupported_reason": None if not selector["text"].strip() else "outside_reported_intent_inventory",
            "requirement_ids": []})
    if len(complete_units) > MAX_UNITS or len(requirements) > MAX_REQUIREMENTS:
        raise ValueError("ledger exceeds bounded unit or requirement limit")
    if len({u["unit_id"] for u in complete_units}) != len(complete_units):
        raise ValueError("duplicate source unit ID after source accounting")
    if len({r["requirement_id"] for r in requirements}) != len(requirements):
        raise ValueError("duplicate requirement ID")
    ledger = {"schema": SCHEMA,
        "source": {"sha256": _sha(source_text.encode("utf-8")), "bytes": len(source_text.encode("utf-8")),
                   "characters": len(source_text), "source_identity": identity},
        "source_report": report, "source_report_sha256": _sha(_wire(report)),
        "source_report_schema": report["schema"], "source_units": complete_units,
        "requirements": requirements, "source_accounting_complete": True,
        "semantic_support_complete": False, **_AUTHORITY}
    ledger["ledger_sha256"] = _sha(_wire(ledger))
    _bounded_json(ledger, max_bytes=2 * MAX_REPORT_BYTES)
    return ledger


def validate_intent_requirement_ledger(ledger, *, source_text, source_report=None):
    """Rebuild exact bindings; this verifies structure, not source semantics."""
    if type(ledger) is not dict:
        raise ValueError("requirement ledger object required")
    _bounded_json(ledger, max_bytes=2 * MAX_REPORT_BYTES)
    source = ledger.get("source")
    if type(source) is not dict or set(source) != {"sha256", "bytes", "characters", "source_identity"}:
        raise ValueError("closed ledger source identity required")
    embedded = ledger.get("source_report")
    if source_report is not None and _wire(source_report) != _wire(embedded):
        raise ValueError("supplied source report differs from embedded report")
    expected = build_intent_requirement_ledger(source_text, source_report=embedded,
                                             source_identity=source["source_identity"])
    if _wire(ledger) != _wire(expected):
        raise ValueError("requirement ledger differs from exact source/report reconstruction")
    return ledger


__all__ = ["SCHEMA", "REVIEWED_REPORT_SCHEMA", "build_intent_requirement_ledger",
           "validate_intent_requirement_ledger"]
