"""Declared native output for an unchanged, saved structured span proposal.

No model, checkpoint tensors, source files or labels are read. ``digest`` is a
canonical JSON *content* digest, never a claim about an on-disk JSON file SHA.
File callers must pin their bytes separately and use ``parse_json_bytes``.
The full original report remains in the detached packet, including refusals.

Only the sealed deontic route and the existing ground-null-context native
deontic_fol bridge are supported. Cue intervals and qualifier expressions are
caller declarations; matching bytes and compiling Lean establish no legal gold,
review authentication, model authentication, source truth or proof authority.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import json
import math
import re

SCHEMA = "saved-span-family-pending/v1"
DECLARATION_SCHEMA = "saved-span-family-declaration/v1"
OUTPUT_SCHEMA = "saved-span-native-family-output/v1"
RAW_SCHEMA = "objective-resumed-source-span-inference/v1"
JOINT_SCHEMA = "structured-span-exposed-law-joint-diagnostic/v1"
LINEAGE = "objective_resumed_source_span_v1"
PROFILE = "ground-null-context/v1"
MAX_ROWS = 128
MAX_SOURCE_BYTES = 32 * 1024
MAX_REPORT_BYTES = 16 * 1024**2
MAX_PACKET_BYTES = 32 * 1024**2
FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
QUALIFIERS = FIELDS[3:]
_SHA = re.compile(r"[0-9a-f]{64}\Z")
FALSE = dict.fromkeys(("qualified", "admitted", "formalized", "proof_authority",
    "source_semantics_verified", "reviewer_authenticated", "semantic_gold",
    "training_masks_emitted", "training_executed", "model_executed", "encoder_executed",
    "Lake_executed", "family_qualified", "all_logic_families_supported",
    "source_context_custody_verified", "target_access"), False)
_RAW_FIELDS = {"schema", "lineage_id", "checkpoint_sha256", "historical_parent_sha256",
    "objective", "progress", "rows", "control", "same_forward_scores", "additional_model_forwards",
    "actual_source_forwards", "weights_unchanged", "optimizer_moments_unchanged",
    "ambient_CPU_RNG_preserved", "optimizer_updates", "native_encoder_executed", "legal_accuracy",
    "family_bridge_admitted", "Lake_executed", "qualified", "admitted", "formalized", "roundtrip_ok",
    "proof_authority", "semantic_correctness_verified", "promotion_performed", "publication_performed",
    "target_access", "teacher_forcing", "training_executed"}
_ROW_FIELDS = {"id", "position", "source_sha256", "effective_latent_sha256", "latent_donor_id",
    "latent_donor_position", "decoder_row", "scores"}
_RAW_BASE = {"source_sha256", "latent_sha256", "status", "canonical_ir", "formal_outputs",
    "formula_text", "teacher_forcing", "target_access", "training_executed", "source_input_conditioned",
    "learned_formula_generation", "sample_memory_used", "family_syntax_checked", "latent_input_enabled",
    "qualified", "admitted", "formalized", "roundtrip_ok", "proof_authority", "semantic_correctness_verified",
    "promotion_performed", "publication_performed", "reason"}
_FALSE_REPORT = {"training_executed", "target_access", "teacher_forcing", "native_encoder_executed",
    "family_bridge_admitted", "Lake_executed", "qualified", "admitted", "formalized", "roundtrip_ok",
    "proof_authority", "semantic_correctness_verified", "promotion_performed", "publication_performed"}
_FALSE_ROW = {"teacher_forcing", "target_access", "training_executed", "sample_memory_used",
    "qualified", "admitted", "formalized", "roundtrip_ok", "proof_authority",
    "semantic_correctness_verified", "promotion_performed", "publication_performed"}
_JOINT_FIELDS = {"schema", "origin", "status", "reason", "source_sha256", "scores_sha256",
    "input_token_count", "top_k", "max_search_nodes", "ambiguity_guard", "objective",
    "candidate_domain_truncated", "candidate_summary", "fixed_decisions", "independent_greedy",
    "search", "canonical_ir", "span_diagnostics", "formal_outputs", "canonical_rule_valid",
    "family_syntax_checked", "readout_policy_changed", "raw_output_repaired", "qualified", "admitted",
    "formalized", "roundtrip_ok", "proof_authority", "semantic_correctness_verified", "promotion_performed",
    "publication_performed", "default_promoted", "target_access", "teacher_forcing", "training_executed",
    "model_execution_performed", "encoder_execution_performed", "Lake_executed"}


class SavedSpanFamilyError(ValueError):
    """Malformed, unsupported or unfilled saved-proposal transport."""


def _require(condition, message):
    if not condition:
        raise SavedSpanFamilyError(message)


def _closed(value, keys, label):
    _require(type(value) is dict and set(value) == set(keys), "closed " + label + " required")


def _wire(value, bound=MAX_PACKET_BYTES):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise SavedSpanFamilyError("finite bounded JSON required") from error
    _require(len(raw) <= bound, "JSON byte bound exceeded")
    return raw


def digest(value):
    """SHA256 of sorted, compact, finite, ensure_ascii=False JSON content."""
    return hashlib.sha256(_wire(value)).hexdigest()


def parse_json_bytes(raw):
    """Strict packet/report/declaration transport, bounded by MAX_PACKET_BYTES.

    Report APIs separately enforce their smaller MAX_REPORT_BYTES bound. File
    SHA is deliberately a caller concern; canonical output is ``_wire(value)``.
    """
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_PACKET_BYTES, "bounded JSON bytes required")

    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise SavedSpanFamilyError("nonfinite JSON literal: " + value)

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise SavedSpanFamilyError("strict finite JSON bytes required") from error
    _wire(value, MAX_PACKET_BYTES)
    return value


def _sha(value, label):
    _require(type(value) is str and _SHA.fullmatch(value) is not None, label + " SHA256 required")


def _text(value, label, maximum=512):
    _require(type(value) is str and value.strip() and len(value.encode("utf-8")) <= maximum,
             "bounded nonblank " + label + " required")


def _integer(value, label, minimum=0, maximum=None):
    _require(type(value) is int and value >= minimum and (maximum is None or value <= maximum),
             "integer " + label + " required")


def _number(value, label):
    _require(type(value) in (int, float) and math.isfinite(value) and abs(value) <= 3.4028234e38,
             "finite float32-range " + label + " required")


def _owners():
    # Explicit pure operations only. Neither owner constructs a model here.
    return (importlib.import_module("ipfs_datasets_py.logic.autoformal.legal_source_family_bridge"),
            importlib.import_module("ipfs_datasets_py.logic.legal_ir.typed_adapter"),
            importlib.import_module("ipfs_datasets_py.logic.legal_ir.joint_span_selection"))


def _source(value):
    _require(type(value) is dict and set(value) in ({"id", "source_text", "source_sha256"},
        {"id", "source_text", "source_sha256", "physical_occurrence"}), "closed explicit source required")
    _text(value["id"], "source ID")
    _text(value["source_text"], "complete source", MAX_SOURCE_BYTES)
    _sha(value["source_sha256"], "source")
    text = value["source_text"]
    _require(hashlib.sha256(text.encode("utf-8")).hexdigest() == value["source_sha256"], "source text SHA differs")
    physical = value.get("physical_occurrence")
    if physical is not None:
        _closed(physical, {"occurrence_id", "context_identity"}, "declared physical occurrence")
        _text(physical["occurrence_id"], "physical occurrence ID")
        context = physical["context_identity"]
        if context is not None:
            _closed(context, {"document_id", "artifact_sha256", "selected_char_start", "selected_char_end",
                "selected_utf8_byte_start", "selected_utf8_byte_end"}, "declared context identity")
            _text(context["document_id"], "context document ID")
            _sha(context["artifact_sha256"], "context artifact")
            for field in ("selected_char_start", "selected_char_end", "selected_utf8_byte_start", "selected_utf8_byte_end"):
                _integer(context[field], field)
            _require(context["selected_char_end"] - context["selected_char_start"] == len(text)
                and context["selected_utf8_byte_end"] - context["selected_utf8_byte_start"] == len(text.encode("utf-8")),
                "declared physical selected interval length differs")
    return dict(id=value["id"], source_text=text, source_sha256=value["source_sha256"],
                physical_occurrence=deepcopy(physical))


def _raw_report(report, expected, checkpoint):
    _wire(report, MAX_REPORT_BYTES)
    _sha(expected, "expected report content")
    _sha(checkpoint, "expected checkpoint content")
    _require(digest(report) == expected, "raw report canonical content digest differs")
    _closed(report, _RAW_FIELDS, "structured source inference report")
    _require(report["schema"] == RAW_SCHEMA and report["lineage_id"] == LINEAGE, "raw report lineage differs")
    _require(report["checkpoint_sha256"] == checkpoint, "checkpoint canonical content binding differs")
    _sha(report["historical_parent_sha256"], "historical parent")
    _require(all(report[k] is False for k in _FALSE_REPORT), "raw report authority/target/execution differs")
    _require(report["legal_accuracy"] is None, "raw report has semantic accuracy claim")
    for key in ("weights_unchanged", "optimizer_moments_unchanged", "ambient_CPU_RNG_preserved"):
        _require(report[key] is True, "saved read-only runtime assertion missing")
    _require(type(report["same_forward_scores"]) is bool, "score capture flag differs")
    _integer(report["optimizer_updates"], "inference updates", maximum=0)
    _integer(report["additional_model_forwards"], "extra forwards", maximum=0)
    _require(report["control"] in ("none", "zero", "disabled", "rotate"), "unknown source control")
    _closed(report["objective"], {"schema", "structure_weight", "accumulator", "active_fields", "authority", "base_ce", "total"}, "objective metadata")
    _require(report["objective"]["schema"] == "source-span-order-overlap-probability/v1"
        and type(report["objective"]["structure_weight"]) in (int, float)
        and report["objective"]["structure_weight"] in (0.0, 0.1), "objective lineage differs")
    objective_literals = {"accumulator": "float64_probability_terms_from_CPU_float32_heads",
        "active_fields": "authored_reference_presence_only; actor_and_action_required",
        "authority": "authored_engineering_geometry; no_legal_semantic_qualification",
        "base_ce": "equal_facet_modality_presence_mean_start_end/v1",
        "total": "CE + weight * (validity + overlap) / 2"}
    _require(all(report["objective"][k] == v for k, v in objective_literals.items()), "objective descriptor differs")
    _closed(report["progress"], {"absolute_optimizer_steps", "epochs_completed", "inherited_optimizer_steps", "new_optimizer_steps", "row_cursor"}, "progress metadata")
    for key, value in report["progress"].items():
        _integer(value, key)
    _require(report["progress"]["absolute_optimizer_steps"] == report["progress"]["inherited_optimizer_steps"] + report["progress"]["new_optimizer_steps"], "progress counters differ")
    _require(report["progress"]["inherited_optimizer_steps"] == 400
        and report["progress"]["new_optimizer_steps"] <= 32 and report["progress"]["epochs_completed"] == 4
        and report["progress"]["row_cursor"] == 192 + 12 * report["progress"]["new_optimizer_steps"],
        "bounded continuation progress lineage differs")
    rows = report["rows"]
    _require(type(rows) is list and 1 <= len(rows) <= MAX_ROWS, "one to128 complete report rows required")
    identities = []
    for position, row in enumerate(rows):
        _closed(row, _ROW_FIELDS, "saved source row")
        _text(row["id"], "row ID")
        _require(row["id"] not in identities, "duplicate report source ID")
        identities.append(row["id"])
        _integer(row["position"], "row position")
        _require(row["position"] == position, "report position/order differs")
        for field in ("source_sha256", "effective_latent_sha256"):
            _sha(row[field], field)
        decoder = row["decoder_row"]
        _require(type(decoder) is dict and _RAW_BASE <= set(decoder)
            and set(decoder) <= _RAW_BASE | {"span_diagnostics", "minimum_decision_logit_margin", "syntax_scope", "detail"},
            "closed saved decoder row required")
        _require(decoder["source_sha256"] == row["source_sha256"]
            and decoder["latent_sha256"] == row["effective_latent_sha256"], "row source/latent binding differs")
        _require(all(decoder[k] is False for k in _FALSE_ROW), "decoder authority/target differs")
        _require(decoder["source_input_conditioned"] is True and decoder["learned_formula_generation"] is True
            and type(decoder["latent_input_enabled"]) is bool, "saved decoder source mode differs")
        _require(report["control"] != "disabled" or decoder["latent_input_enabled"] is False,
                 "disabled control has enabled latent input")
        if decoder["status"] == "decoded":
            _closed(decoder, _RAW_BASE | {"span_diagnostics", "minimum_decision_logit_margin", "syntax_scope"}, "decoded row")
            _require(decoder["reason"] is None and decoder["family_syntax_checked"] is True, "decoded row status differs")
            _number(decoder["minimum_decision_logit_margin"], "minimum decision margin")
            _require(decoder["minimum_decision_logit_margin"] > 1e-7
                and decoder["syntax_scope"] == "single_canonical_deontic_rule_with_one_copied_span_per_facet",
                "decoded margin/syntax profile differs")
            ir = decoder["canonical_ir"]
            _closed(ir, {"rules"}, "decoded canonical IR")
            _require(type(ir["rules"]) is list and len(ir["rules"]) == 1, "one decoded rule required")
            display = _wire(ir).decode("utf-8")
            _require(decoder["formula_text"] == display, "raw display/canonical IR differs")
            outputs = decoder["formal_outputs"]
            _require(type(outputs) is list and len(outputs) == 1, "one unchanged typed display output required")
            output = outputs[0]
            flags = _FALSE_ROW - {"teacher_forcing", "target_access", "training_executed", "sample_memory_used"}
            _closed(output, flags | {"family", "format", "payload", "formula_text", "formula_text_role", "origin"}, "raw typed formal output")
            _require(all(output[k] is False for k in flags)
                and output["family"] == "deontic" and output["format"] == "typed-deontic-rule/v1"
                and output["payload"] == ir["rules"][0] and output["formula_text"] == display
                and output["formula_text_role"] == "display_only_full_ast_is_authoritative"
                and output["origin"] == "learned_source_span_formula_decoder", "raw typed formal output differs")
        else:
            _require(decoder["status"] == "abstained" and type(decoder["reason"]) is str and decoder["reason"], "explicit raw refusal required")
            _require(decoder["canonical_ir"] is None and decoder["formula_text"] is None
                and decoder["formal_outputs"] == [] and decoder["family_syntax_checked"] is False, "refusal emitted a candidate")
        if report["same_forward_scores"] and decoder["reason"] not in ("source_too_long", "source_encoding_rejected"):
            _require(type(row["scores"]) is dict, "captured forward is missing scores")
        else:
            _require(row["scores"] is None, "uncaptured row has scores")
    for position, row in enumerate(rows):
        donor = (position + 1) % len(rows) if report["control"] == "rotate" else position
        _integer(row["latent_donor_position"], "donor position")
        _require(row["latent_donor_position"] == donor and row["latent_donor_id"] == identities[donor], "cross-control donor binding differs")
    _require(report["control"] != "rotate" or len(rows) > 1, "rotate needs multiple source rows")
    forwards = sum(row["decoder_row"]["reason"] not in ("source_too_long", "source_encoding_rejected") for row in rows)
    _integer(report["actual_source_forwards"], "source forwards")
    _require(report["actual_source_forwards"] == forwards, "source forward coverage differs")
    return rows


def _geometry(source, tokens, literal, span):
    _closed(span, {"token_start", "token_end_inclusive", "char_start", "char_end", "text"}, "saved facet geometry")
    for key in ("token_start", "token_end_inclusive", "char_start", "char_end"):
        _integer(span[key], key)
    left, right = span["token_start"], span["token_end_inclusive"]
    _require(left <= right < len(tokens), "facet token interval differs")
    start, end = tokens[left]["start"], tokens[right]["end"]
    _require(span["char_start"] == start and span["char_end"] == end
        and source[start:end] == span["text"] == literal, "exact facet source slice differs")
    return dict(start_char=start, end_char=end, source_text=literal, canonical_value=literal,
        utf8_byte_start=len(source[:start].encode("utf-8")), utf8_byte_end=len(source[:end].encode("utf-8")),
        token_start=left, token_end_inclusive=right)


def _candidate_geometry(source, selected, lane):
    bridge, _, joint = _owners()
    tokens = [{k: token[k] for k in ("text", "start", "end")} for token in joint._owner().tokenize_source(source)]
    ir = selected["canonical_ir"]
    _closed(ir, {"rules"}, "canonical IR")
    _require(type(ir["rules"]) is list and len(ir["rules"]) == 1, "unchanged one-rule proposal required")
    rule = ir["rules"][0]
    _closed(rule, set(FIELDS) | {"modality"}, "canonical rule")
    _require(bridge.CanonicalRoundTripIR.from_dict(ir).to_dict() == ir, "canonicalization would alter candidate")
    for field in QUALIFIERS:
        _require(type(rule[field]) is list and len(rule[field]) <= 1, "current one-span qualifier profile required")
    _require(not rule["temporal"], "unsupported temporal/calendar profile")
    geometry = {}
    diagnostics = selected["span_diagnostics"]
    if lane == "raw":
        _closed(diagnostics, {"tokens", "facets", "modality_logits"}, "raw span diagnostics")
        _require(diagnostics["tokens"] == tokens, "complete source token diagnostics differ")
        logits = diagnostics["modality_logits"]
        _require(type(logits) is list and len(logits) == 3, "modality logits differ")
        for value in logits:
            _number(value, "modality logit")
        ranking = sorted(range(3), key=lambda i: (-logits[i], i))
        _require(logits[ranking[0]] - logits[ranking[1]] > 1e-7
            and ("O", "P", "F")[ranking[0]] == rule["modality"], "modality saved decision differs")
        facets = diagnostics["facets"]
    else:
        facets = diagnostics
    _closed(facets, FIELDS, "six complete saved facets")
    occupied = set()
    for field in FIELDS:
        literal = rule[field][0] if field in QUALIFIERS and rule[field] else rule[field] if field not in QUALIFIERS else ""
        present = bool(literal)
        _require(field not in FIELDS[:2] or present, "required facet missing")
        diagnostic = facets[field]
        if lane == "raw":
            _closed(diagnostic, {"present", "presence_logit_margin", "token_start", "token_end_inclusive",
                "char_start", "char_end", "text", "span_logit_margin"}, "raw facet")
            span = {key: diagnostic[key] for key in ("token_start", "token_end_inclusive", "char_start", "char_end", "text")}
        else:
            _closed(diagnostic, {"present", "span"}, "joint facet")
            span = diagnostic["span"]
            if span is not None:
                _closed(span, {"token_start", "token_end_inclusive", "char_start", "char_end", "utf8_byte_start", "utf8_byte_end", "text", "span_score_float32"}, "joint copied span")
                _number(span["span_score_float32"], "joint span score")
                span = {key: span[key] for key in ("token_start", "token_end_inclusive", "char_start", "char_end", "text")}
        _require(diagnostic["present"] is present, "facet presence/canonical value differs")
        if lane == "raw":
            margin = diagnostic["presence_logit_margin"]
            if field in FIELDS[:2]:
                _require(margin is None, "required facet has invented presence margin")
            else:
                _number(margin, "presence margin")
                _require(margin > 1e-7, "ambiguous raw presence margin")
            span_margin = diagnostic["span_logit_margin"]
            if present and span_margin is not None:
                _number(span_margin, "span margin")
                _require(span_margin > 1e-7, "ambiguous raw span margin")
            if not present:
                _require(span_margin is None, "absent facet has span margin")
        if not present:
            _require(span is None if lane == "joint" else all(v is None for v in span.values()), "absent facet has interval")
            geometry[field] = None
            continue
        geom = _geometry(source, tokens, literal, span)
        positions = set(range(geom["token_start"], geom["token_end_inclusive"] + 1))
        _require(not occupied & positions, "copied facet intervals overlap")
        occupied.update(positions)
        geometry[field] = geom
    return deepcopy(ir), geometry


def _replay_greedy(source, row):
    _, _, joint = _owners()
    scores = joint._validated(source, row["scores"])
    rankings = {field: joint._rank_spans(scores, field) for field in FIELDS}
    greedy = joint._greedy(source, scores, rankings)
    raw = row["decoder_row"]
    diagnostics = raw.get("span_diagnostics")
    _closed(diagnostics, {"tokens", "facets", "modality_logits"}, "raw scored diagnostics")
    _require(diagnostics["tokens"] == scores["tokens"]
        and diagnostics["modality_logits"] == scores["modality_logits"]
        and type(diagnostics["facets"]) is dict and set(diagnostics["facets"]) == set(greedy["facets"]),
        "raw scored token/head/partial coverage differs")
    _require(greedy["status"] == raw["status"] and greedy["reason"] == raw["reason"]
        and greedy["canonical_ir"] == raw["canonical_ir"], "saved scores/raw decision replay differs")
    if greedy["status"] == "decoded":
        _require(raw["minimum_decision_logit_margin"] == greedy["minimum_decision_logit_margin"],
                 "raw minimum saved decision margin differs")
    for field, diagnostic in greedy["facets"].items():
        actual = raw.get("span_diagnostics", {}).get("facets", {}).get(field)
        _require(type(actual) is dict and actual["present"] is diagnostic["present"], "raw score facet presence differs")
        _require(actual["presence_logit_margin"] == diagnostic["presence_logit_margin"]
            and actual["span_logit_margin"] == diagnostic["span_logit_margin"], "raw score margins differ")
        for key in ("token_start", "token_end_inclusive", "char_start", "char_end", "text"):
            _require(actual[key] == (diagnostic["span"][key] if diagnostic["span"] else None), "raw score geometry differs")
    return True


def prepare_pending(source, raw_report, *, expected_report_sha256, expected_checkpoint_sha256,
                    row_id, joint_report=None, expected_joint_report_sha256=None):
    """Detach full reports and bind one unchanged raw or separate joint proposal.

    Report SHA values use this module's canonical-content ``digest``. Checkpoint
    SHA is the checkpoint owner's externally authenticated canonical digest,
    matched to the report (not recomputed with this module's JSON convention).
    No checkpoint file or tensor is read or restored here.
    Optional physical/context metadata is caller-declared, not revalidated here.
    """
    source = _source(source)
    rows = _raw_report(raw_report, expected_report_sha256, expected_checkpoint_sha256)
    _require(row_id == source["id"], "source/selected row ID differs")
    matches = [row for row in rows if row["id"] == row_id]
    _require(len(matches) == 1, "selected row ID absent")
    row = matches[0]
    _require(row["source_sha256"] == source["source_sha256"], "source/report SHA differs")
    lane, selected = "raw", row["decoder_row"]
    replayed = row["scores"] is not None
    if replayed:
        _replay_greedy(source["source_text"], row)
    if joint_report is not None:
        _sha(expected_joint_report_sha256, "expected joint report content")
        _wire(joint_report, MAX_REPORT_BYTES)
        _require(digest(joint_report) == expected_joint_report_sha256, "joint report canonical content digest differs")
        _closed(joint_report, {"schema", "rows", "top_k", "max_search_nodes", "learned_presence_and_modality_fixed",
            "raw_greedy_preserved", "qualified", "semantic_accuracy", "used_for_updates_or_selection"}, "joint report")
        _require(joint_report["schema"] == JOINT_SCHEMA and joint_report["learned_presence_and_modality_fixed"] is True
            and joint_report["raw_greedy_preserved"] is True and joint_report["qualified"] is False
            and joint_report["semantic_accuracy"] is None and joint_report["used_for_updates_or_selection"] is False,
            "joint report status/authority differs")
        _require(type(joint_report["rows"]) is list and len(joint_report["rows"]) == len(rows), "joint full row coverage differs")
        for raw, item in zip(rows, joint_report["rows"], strict=True):
            _closed(item, {"id", "result"}, "joint result row")
            _require(item["id"] == raw["id"], "joint row order/ID differs")
            result = item["result"]
            _require(type(result) is dict and _JOINT_FIELDS <= set(result)
                and set(result) <= _JOINT_FIELDS | {"detail"}, "closed complete joint result required")
            _require(result["schema"] == "joint-copied-span-selection/v1"
                and result["origin"] == "bounded_joint_source_span_selector"
                and result["source_sha256"] == raw["source_sha256"]
                and result["top_k"] == joint_report["top_k"]
                and result["max_search_nodes"] == joint_report["max_search_nodes"], "joint row profile/source differs")
            false_fields = (_FALSE_ROW - {"sample_memory_used"}) | {"default_promoted", "model_execution_performed",
                "encoder_execution_performed", "Lake_executed", "raw_output_repaired"}
            _require(all(result[k] is False for k in false_fields), "joint result authority/target differs")
            _require(result["readout_policy_changed"] is True, "joint origin is not a separate policy")
            _require(result["status"] in ("selected", "abstained"), "unknown joint disposition")
            if result["status"] == "abstained":
                _require(result["canonical_ir"] is None and result["formal_outputs"] == [], "joint refusal emitted candidate")
        _require(replayed and raw_report["same_forward_scores"] is True, "joint requires paired same-forward saved scores")
        selected = joint_report["rows"][row["position"]]["result"]
        _, _, joint = _owners()
        regenerated = joint.select_joint_spans(source["source_text"], row["scores"],
            top_k=joint_report["top_k"], max_search_nodes=joint_report["max_search_nodes"])
        _require(_wire(regenerated) == _wire(selected), "joint authoritative saved-score replay differs")
        lane = "joint"
    else:
        _require(expected_joint_report_sha256 is None, "joint digest without joint report")
    _require(selected.get("status") == ("decoded" if lane == "raw" else "selected"),
             "saved " + lane + " proposal refused: " + str(selected.get("reason")))
    ir, geometry = _candidate_geometry(source["source_text"], selected, lane)
    bridge, typed, _ = _owners()
    route = typed.resolve_legal_route("deontic")
    _require(route.family_id == "deontic" and route.profile_id == "", "sealed deontic route differs")
    candidate = dict(candidate_id=row_id + "::" + expected_checkpoint_sha256 + "::" + raw_report["control"] + "::" + lane,
        source_text=source["source_text"], source_sha256=source["source_sha256"], canonical_ir=ir)
    # Apply existing bounded non-temporal profile checks; do not fill expressions.
    bridge.interpretation_skeleton(candidate)
    packet = dict(schema=SCHEMA, profile=PROFILE, source=source, raw_report=deepcopy(raw_report),
        joint_report=deepcopy(joint_report), candidate=candidate, facet_geometry=geometry,
        binding=dict(row_id=row_id, position=row["position"], checkpoint_sha256=expected_checkpoint_sha256,
            raw_report_content_sha256=expected_report_sha256, joint_report_content_sha256=expected_joint_report_sha256,
            raw_row_content_sha256=digest(row), selected_content_sha256=digest(selected), lane=lane,
            lineage_id=raw_report["lineage_id"], control=raw_report["control"]),
        sealed_route=dict(route_id=route.route_id, family_id=route.family_id, profile_id=route.profile_id),
        artifact_consistency_only=True, saved_head_replay_performed=replayed,
        physical_context_status="absent" if source["physical_occurrence"] is None else "caller_declared_not_authenticated",
        original_raw_report_preserved=True, raw_output_repaired=False, **FALSE)
    _wire(packet)
    return deepcopy(packet)


def validate_pending(packet, *, expected_packet_sha256):
    """Recreate every derived field from the full detached source/report snapshots."""
    _closed(packet, set(FALSE) | {"schema", "profile", "source", "raw_report", "joint_report", "candidate",
        "facet_geometry", "binding", "sealed_route", "artifact_consistency_only", "saved_head_replay_performed",
        "physical_context_status", "original_raw_report_preserved", "raw_output_repaired"}, "pending packet")
    _sha(expected_packet_sha256, "expected packet content")
    _require(digest(packet) == expected_packet_sha256, "pending packet content digest differs")
    binding = packet["binding"]
    _closed(binding, {"row_id", "position", "checkpoint_sha256", "raw_report_content_sha256",
        "joint_report_content_sha256", "raw_row_content_sha256", "selected_content_sha256", "lane", "lineage_id", "control"},
        "pending report binding")
    rebuilt = prepare_pending(packet["source"], packet["raw_report"],
        expected_report_sha256=binding["raw_report_content_sha256"],
        expected_checkpoint_sha256=binding["checkpoint_sha256"], row_id=binding["row_id"],
        joint_report=packet["joint_report"], expected_joint_report_sha256=binding["joint_report_content_sha256"])
    _require(_wire(packet) == _wire(rebuilt), "pending packet authoritative replay differs")
    return True


def declaration_skeleton(packet):
    """Unfilled declarations; no cue matching, literal search or meaning guesses."""
    validate_pending(packet, expected_packet_sha256=digest(packet))
    bridge, _, _ = _owners()
    return dict(schema=DECLARATION_SCHEMA, packet_sha256=digest(packet),
        declaration_scope=bridge.DECLARATION_SCOPE, interpretation=bridge.interpretation_skeleton(packet["candidate"]),
        occurrence=dict(occurrence_id=None, start_char=None, end_char=None, source_text=None,
            modality_anchor=dict(start_char=None, end_char=None, source_text=None,
                                 canonical_value=packet["candidate"]["canonical_ir"]["rules"][0]["modality"])))


def prepare_family(packet, declaration, *, expected_packet_sha256, family="deontic"):
    """Emit existing native AST/Lean under complete explicit caller declarations.

    This never builds Lean or upgrades review/training/semantic authority.
    Family is a sealed family ID, not a parser alias or operation-role name.
    """
    validate_pending(packet, expected_packet_sha256=expected_packet_sha256)
    _require(type(family) is str, "exact sealed family ID required")
    if family == "tdfol":
        raise SavedSpanFamilyError("tdfol registered temporal_first_order profile is not qualified by ground-null-context")
    if family in ("dcec", "event_calculus"):
        raise SavedSpanFamilyError("DCEC composition/event/modal metadata gap; parser label is not family qualification")
    _require(family == "deontic", "unsupported sealed family for this bounded profile")
    bridge, typed, _ = _owners()
    _require(typed.resolve_legal_route(family).route_id == packet["sealed_route"]["route_id"], "sealed route binding differs")
    skeleton = declaration_skeleton(packet)
    _closed(declaration, skeleton, "caller declaration")
    _require(declaration["schema"] == DECLARATION_SCHEMA and declaration["packet_sha256"] == expected_packet_sha256
        and declaration["declaration_scope"] == bridge.DECLARATION_SCOPE, "declaration identity/scope differs")
    occurrence = declaration["occurrence"]
    _closed(occurrence, skeleton["occurrence"], "caller occurrence")
    _text(occurrence["occurrence_id"], "caller occurrence ID")
    for field in ("start_char", "end_char"):
        _integer(occurrence[field], "caller " + field)
    source = packet["source"]["source_text"]
    start, end = occurrence["start_char"], occurrence["end_char"]
    _require(start < end <= len(source) and source[start:end] == occurrence["source_text"], "complete caller occurrence differs")
    anchor = occurrence["modality_anchor"]
    _closed(anchor, skeleton["occurrence"]["modality_anchor"], "caller modality anchor")
    left, right = anchor["start_char"], anchor["end_char"]
    _integer(left, "modality start")
    _integer(right, "modality end")
    _require(start <= left < right <= end and source[left:right] == anchor["source_text"]
        and anchor["canonical_value"] == packet["candidate"]["canonical_ir"]["rules"][0]["modality"],
        "explicit modality interval/value differs")
    facets = {"modality": deepcopy(anchor)}
    for field, span in packet["facet_geometry"].items():
        if span is not None:
            _require(start <= span["start_char"] < span["end_char"] <= end, "caller occurrence excludes learned facet")
            _require(span["end_char"] <= left or right <= span["start_char"], "modality anchor overlaps learned facet")
        native = None if span is None else {key: span[key] for key in ("start_char", "end_char", "source_text", "canonical_value")}
        facets[field] = ([native] if native else []) if field in QUALIFIERS else native
    request = dict(candidate=deepcopy(packet["candidate"]), interpretation=deepcopy(declaration["interpretation"]),
        occurrence_bindings=[dict(occurrence_id=occurrence["occurrence_id"], rule_index=0,
            start_char=start, end_char=end, source_text=occurrence["source_text"], facets=facets)])
    native = bridge.prepare_source_family(**request, family="deontic_fol")
    result = dict(schema=OUTPUT_SCHEMA, packet_sha256=expected_packet_sha256, declaration_sha256=digest(declaration),
        binding=deepcopy(packet["binding"]), sealed_route=deepcopy(packet["sealed_route"]),
        native_parser_profile="deontic_fol", profile=PROFILE, request=request, native_bridge=native,
        canonical_ir=deepcopy(packet["candidate"]["canonical_ir"]), native_syntax_checked=True,
        lean_source_prepared=True, backend_build_required="lake build legal", declaration_scope=bridge.DECLARATION_SCOPE,
        raw_output_repaired=False, modality_anchor_utf8_bytes=[len(source[:left].encode("utf-8")), len(source[:right].encode("utf-8"))],
        physical_context_status=packet["physical_context_status"], **FALSE)
    _wire(result)
    return deepcopy(result)


def validate_family(result, packet, declaration, *, expected_packet_sha256, family="deontic"):
    """Replay native AST, full interpretation, exact source spans and emitted Lean."""
    expected = prepare_family(packet, declaration, expected_packet_sha256=expected_packet_sha256, family=family)
    _require(_wire(result) == _wire(expected), "native output authoritative replay differs")
    return True


__all__ = ["prepare_pending", "validate_pending", "declaration_skeleton", "prepare_family", "validate_family",
           "digest", "parse_json_bytes", "SavedSpanFamilyError", "SCHEMA", "DECLARATION_SCHEMA", "OUTPUT_SCHEMA"]
