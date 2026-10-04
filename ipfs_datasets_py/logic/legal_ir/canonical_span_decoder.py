"""Opt-in source preflight around retained dimensional span inference.

Inputs contain exact sources, declared context and already produced vectors.
Controls are joined before any source is filtered. The unchanged decoder emits
unaccepted proposals; source warnings and receipt integrity establish neither
source fidelity nor proof authority. This module loads no model or vocabulary.
Its validator replays deterministic preparation, never numerical inference.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import struct

from .canonical_decoder_preflight import analyze_decoder_source

SCHEMA = "canonical-span-decoder-preflight-inference/v1"
LINEAGE = "native_dimensional_source_span_v1"
EXECUTION_POLICY = "source_preflight_then_unaccepted_decoder_proposals"
VALIDATION_SCOPE = "deterministic_inputs_and_bound_decoder_receipt_no_model_replay"
_CONTROLS = ("none", "zero", "disabled", "rotate")
_FALSE = {field: False for field in (
    "target_access", "teacher_forcing", "training_executed", "context_applied",
    "source_fidelity_established", "qualified", "proof_authority", "accepted")}
_NATIVE_FALSE = {field: False for field in (
    "qualified", "admitted", "formalized", "roundtrip_ok", "proof_authority",
    "semantic_correctness_verified", "promotion_performed", "publication_performed")}
_META = {"lineage_id", "checkpoint_sha256", "source_parent_checkpoint_sha256",
         "context_contract_sha256", "input_dimension", "latent_enabled", "model_state_sha256"}
_REQUEST = {"id", "source_text", "context_text", "requires_context_resolution"}
_RECORD = {"schema", "decoder_metadata", "requested_control", "owner_control", "rows",
           "input_count", "eligible_count", "submitted_positions", "decoder_call_count",
           "decoder_completion_count", "backend_result", "backend_exception_type",
           "execution_policy", "validation_scope", "content_sha256", *_FALSE}
_BASE_ROW = {"source_sha256", "latent_sha256", "status", "canonical_ir", "formal_outputs",
             "formula_text", "teacher_forcing", "target_access", "training_executed",
             "source_input_conditioned", "learned_formula_generation", "sample_memory_used",
             "family_syntax_checked", "latent_input_enabled", *_NATIVE_FALSE}
_DIAGNOSTIC = {"present", "presence_logit_margin", "token_start", "token_end_inclusive",
               "char_start", "char_end", "text", "span_logit_margin"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value, *, ascii=False):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=ascii, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("strict finite UTF8 JSON required") from error


def _digest(value, *, ascii=False):
    return hashlib.sha256(_raw(value, ascii=ascii)).hexdigest()


def _hash(value, field):
    _require(type(value) is str and len(value) == 64
             and all(character in "0123456789abcdef" for character in value),
             field + " requires lowercase SHA256")


def _keys(value, expected, field):
    _require(type(value) is dict and set(value) == expected, field + " has unknown or missing fields")


def _native():
    # The retained tokenizer and grammar have no numerical import at module load.
    from ...optimizers.logic_theorem_optimizer import legal_span_formula
    return legal_span_formula


def _metadata(decoder):
    checkpoint = decoder.checkpoint
    _require(type(checkpoint) is dict, "decoder checkpoint metadata required")
    config = checkpoint.get("config")
    _require(type(config) is dict, "decoder configuration required")
    metadata = {"lineage_id": checkpoint.get("lineage_id", LINEAGE),
                "checkpoint_sha256": decoder.checkpoint_sha256,
                "source_parent_checkpoint_sha256": checkpoint.get("source_parent_checkpoint_sha256"),
                "context_contract_sha256": checkpoint.get("context_contract_sha256"),
                "input_dimension": config.get("latent_dimension"),
                "latent_enabled": config.get("latent_enabled"),
                "model_state_sha256": _digest(checkpoint.get("model_state"), ascii=True)}
    _validate_metadata(metadata)
    _require(type(checkpoint.get("model_state")) is dict, "saved model state required")
    _require(metadata["checkpoint_sha256"] == _digest(checkpoint, ascii=True),
             "decoder checkpoint content binding differs")
    return metadata


def _validate_metadata(metadata):
    _keys(metadata, _META, "decoder metadata")
    _require(metadata["lineage_id"] == LINEAGE, "decoder lineage differs")
    dimension = metadata["input_dimension"]
    _require(type(dimension) is int and dimension in (0, 8, 384, 768), "native decoder dimension required")
    _require(type(metadata["latent_enabled"]) is bool, "latent_enabled must be boolean")
    for field in _META - {"lineage_id", "input_dimension", "latent_enabled"}:
        _hash(metadata[field], field)


def _prepare(requests, latents, metadata, control):
    _validate_metadata(metadata)
    _require(control in _CONTROLS and type(control) is str, "unsupported latent control")
    _require(type(requests) in (list, tuple) and 1 <= len(requests) <= 128, "one to 128 requests required")
    _require(control != "rotate" or len(requests) >= 2, "rotate requires at least two requests")
    native = _native()
    dimension = metadata["input_dimension"]
    if dimension:
        _require(type(latents) in (list, tuple) and len(latents) == len(requests),
                 "one native vector per original request required")
        try:
            vectors = [native._vector(vector, dimension) for vector in latents]
        except OverflowError as error:
            raise ValueError("latent contains a number outside finite float32 range") from error
    else:
        _require(latents is None, "source-only decoder does not accept vectors")
        vectors = [[] for _ in requests]
    effective = [[0.] * dimension for _ in vectors] if control == "zero" else copy.deepcopy(vectors)
    donors = list(range(len(requests)))
    if control == "rotate":
        effective = effective[1:] + effective[:1]
        donors = donors[1:] + donors[:1]
    preflights, seen = [], set()
    for request in requests:
        _keys(request, _REQUEST, "source decoder request")
        identity = request["id"]
        _require(type(identity) is str and 0 < len(identity) <= 256 and bool(identity.strip()),
                 "request id must be nonblank text of at most 256 characters")
        _raw(identity)
        _require(identity not in seen, "request IDs must be unique")
        seen.add(identity)
        preflight = analyze_decoder_source(request["source_text"], context_text=request["context_text"],
            requires_context_resolution=request["requires_context_resolution"])
        preflights.append(preflight)
    rows, positions = [], []
    for position, (request, preflight) in enumerate(zip(requests, preflights, strict=True)):
        encoding = {"outcome": "not_assessed", "token_count": None,
                    "token_input_sha256": None, "reason": None}
        outcome = "clarification_required" if preflight["outcome"] == "clarification_required" else "source_blocked"
        submitted = None
        if preflight["outcome"] == "unassessed":
            try:
                tokens = native.tokenize_source(request["source_text"])
            except ValueError as error:
                outcome = "source_encoding_unavailable"
                encoding.update(outcome="unavailable", reason=str(error))
            else:
                encoding.update(outcome="admitted", token_count=len(tokens), token_input_sha256=_digest(tokens))
                outcome = "decoder_unavailable"
                submitted = len(positions)
                positions.append(position)
        rows.append({"id": request["id"], "position": position,
            "source_sha256": preflight["source_sha256"], "context_sha256": preflight["context"]["sha256"],
            "request_sha256": _digest(request), "preflight": preflight, "encoding": encoding,
            "original_latent_sha256": _digest(vectors[position], ascii=True),
            "effective_latent_sha256": _digest(effective[position], ascii=True),
            "latent_donor_id": requests[donors[position]]["id"], "latent_donor_position": donors[position],
            "latent_input_enabled": control != "disabled" and metadata["latent_enabled"] and dimension != 0,
            "submitted_position": submitted, "outcome": outcome, "decoder_row": None})
    owner_control = "disabled" if control == "disabled" else "none"
    return rows, positions, effective, owner_control


def _finite(value, field, *, margin=False):
    _require(type(value) in (int, float) and abs(value) <= 3.4028234e38 and math.isfinite(value)
             and (not margin or value > 1e-7), field + " must be finite" + (" with an unambiguous margin" if margin else ""))


def _validate_diagnostics(diagnostics, source, *, decoded):
    native = _native()
    _keys(diagnostics, {"tokens", "facets", "modality_logits"}, "span diagnostics")
    tokens = native.tokenize_source(source)
    expected = [{key: token[key] for key in ("text", "start", "end")} for token in tokens]
    _require(_raw(diagnostics["tokens"]) == _raw(expected), "diagnostic source tokens differ")
    logits = diagnostics["modality_logits"]
    _require(type(logits) is list and len(logits) == 3, "three modality logits required")
    for value in logits:
        _finite(value, "modality logit")
    facets = diagnostics["facets"]
    _require(type(facets) is dict and set(facets) <= set(native.SPAN_FIELDS), "unexpected diagnostic facets")
    _require(not decoded or set(facets) == set(native.SPAN_FIELDS), "decoded facets incomplete")
    occupied = set()
    for field, diagnostic in facets.items():
        _keys(diagnostic, _DIAGNOSTIC, "facet diagnostic")
        _require(type(diagnostic["present"]) is bool, "facet presence must be boolean")
        if field in native.OPTIONAL_FIELDS:
            _finite(diagnostic["presence_logit_margin"], "presence margin", margin=True)
        else:
            _require(diagnostic["present"] is True and diagnostic["presence_logit_margin"] is None,
                     "required facet presence differs")
        coordinates = ("token_start", "token_end_inclusive", "char_start", "char_end", "text", "span_logit_margin")
        if not diagnostic["present"]:
            _require(all(diagnostic[key] is None for key in coordinates), "absent facet has a copied span")
            continue
        left, right = diagnostic["token_start"], diagnostic["token_end_inclusive"]
        _require(type(left) is int and type(right) is int and 0 <= left <= right < len(tokens),
                 "facet token span invalid")
        begin, end = tokens[left]["start"], tokens[right]["end"]
        _require(type(diagnostic["char_start"]) is int and type(diagnostic["char_end"]) is int
                 and diagnostic["char_start"] == begin and diagnostic["char_end"] == end
                 and diagnostic["text"] == source[begin:end], "facet literal source binding differs")
        if diagnostic["span_logit_margin"] is not None:
            _finite(diagnostic["span_logit_margin"], "span margin", margin=True)
        else:
            _require(len(tokens) == 1, "span margin missing for multiple candidates")
        locations = set(range(left, right + 1))
        _require(not decoded or not occupied & locations, "decoded facet spans overlap")
        occupied.update(locations)
    return facets


def _validate_decoder_row(row, prepared, request):
    _require(type(row) is dict, "decoder row required")
    decoded = row.get("status") == "decoded"
    _require(row.get("status") in ("decoded", "abstained"), "unknown decoder row status")
    reason = row.get("reason")
    if decoded:
        extras = {"reason", "minimum_decision_logit_margin", "span_diagnostics", "syntax_scope"}
    elif reason == "nonfinite_decoder_scores":
        extras = {"reason"}
    elif reason in ("ambiguous_decoder_scores", "copied_spans_overlap"):
        extras = {"reason", "span_diagnostics"}
    elif reason == "generated_ir_rejected":
        extras = {"reason", "detail", "span_diagnostics"}
        _require(type(row.get("detail")) is str and len(row["detail"]) <= 65_536, "bounded decoder rejection detail required")
    else:
        raise ValueError("unexpected decoder abstention reason after source admission")
    _keys(row, _BASE_ROW | extras, "decoder row")
    _require(row["source_sha256"] == prepared["source_sha256"]
             and row["latent_sha256"] == prepared["effective_latent_sha256"], "decoder source/vector join differs")
    for field in (*_NATIVE_FALSE, "target_access", "teacher_forcing", "training_executed", "sample_memory_used"):
        _require(row[field] is False, "decoder authority or input policy differs: " + field)
    _require(row["source_input_conditioned"] is True and row["learned_formula_generation"] is True,
             "retained learned source decoder provenance differs")
    _require(row["latent_input_enabled"] is prepared["latent_input_enabled"], "effective latent gate differs")
    _require(row["family_syntax_checked"] is decoded, "family syntax claim differs")
    facets = None
    if "span_diagnostics" in row:
        facets = _validate_diagnostics(row["span_diagnostics"], request["source_text"], decoded=decoded)
    if not decoded:
        _require(row["canonical_ir"] is None and row["formula_text"] is None
                 and row["formal_outputs"] == [], "abstention contains a candidate")
        return
    native = _native()
    rule = native.codec_module._rule(row["canonical_ir"])
    _require(all(len(rule[field]) <= 1 for field in native.codec_module.QUALIFIERS),
             "decoded qualifier cardinality exceeds retained span contract")
    _require(reason is None and row["syntax_scope"] == "single_canonical_deontic_rule_with_one_copied_span_per_facet",
             "decoded syntax scope differs")
    _finite(row["minimum_decision_logit_margin"], "minimum decision margin", margin=True)
    logits = row["span_diagnostics"]["modality_logits"]
    ranking = sorted(range(len(logits)), key=lambda index: -logits[index])
    _require(rule["modality"] == native.MODALITIES[ranking[0]], "decoded modality differs from diagnostic logits")
    # The retained owner subtracts float32 tensors before converting to Python.
    try:
        modality_margin = struct.unpack("f", struct.pack("f", logits[ranking[0]] - logits[ranking[1]]))[0]
    except (OverflowError, struct.error) as error:
        raise ValueError("diagnostic modality margin overflows float32") from error
    _finite(modality_margin, "modality decision margin", margin=True)
    margins = [modality_margin]
    for diagnostic in facets.values():
        margins += [diagnostic[field] for field in ("presence_logit_margin", "span_logit_margin")
                    if diagnostic[field] is not None]
    _require(row["minimum_decision_logit_margin"] == min(margins),
             "minimum decision margin differs from diagnostic margins")
    display = json.dumps(row["canonical_ir"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    _require(row["formula_text"] == display, "decoded display differs from full AST")
    for field in native.SPAN_FIELDS:
        diagnostic = facets[field]
        atom = diagnostic["text"] if diagnostic["present"] else ""
        expected = ([atom] if diagnostic["present"] else []) if field in native.codec_module.QUALIFIERS else atom
        _require(rule[field] == expected, "decoded facet differs from its exact source span")
    expected_outputs = [{"family": "deontic", "format": "typed-deontic-rule/v1", "payload": rule,
        "formula_text": display, "formula_text_role": "display_only_full_ast_is_authoritative",
        "origin": "learned_source_span_formula_decoder", **_NATIVE_FALSE}]
    _require(_raw(row["formal_outputs"]) == _raw(expected_outputs), "decoded formal output differs")


def _bind_backend(backend, rows, positions, requests, metadata, owner_control):
    expected_keys = {"schema", "lineage_id", "checkpoint_sha256", "source_parent_checkpoint_sha256",
        "context_contract_sha256", "input_dimension", "rows", "decoded_count", "status", "latent_ablation",
        "target_access", "teacher_forcing", "training_executed", "model_state_unchanged", *_NATIVE_FALSE}
    _keys(backend, expected_keys, "native decoder batch")
    _require(backend["schema"] == "native-dimensional-source-span-inference/v1", "native decoder schema differs")
    for field in ("lineage_id", "checkpoint_sha256", "source_parent_checkpoint_sha256", "context_contract_sha256", "input_dimension"):
        _require(type(backend[field]) is type(metadata[field]) and backend[field] == metadata[field],
                 "native decoder metadata differs: " + field)
    _require(backend["latent_ablation"] == owner_control and backend["model_state_unchanged"] is True,
             "native control or immutable-state guard differs")
    for field in (*_NATIVE_FALSE, "target_access", "teacher_forcing", "training_executed"):
        _require(backend[field] is False, "native batch authority or input policy differs: " + field)
    _require(type(backend["rows"]) is list and len(backend["rows"]) == len(positions), "native row count differs")
    count = 0
    for position, raw in zip(positions, backend["rows"], strict=True):
        _validate_decoder_row(raw, rows[position], requests[position])
        count += raw["status"] == "decoded"
        rows[position]["decoder_row"] = copy.deepcopy(raw)
        rows[position]["outcome"] = "decoder_proposal" if raw["status"] == "decoded" else "decoder_abstained"
    expected_status = "decoded" if count == len(positions) else "partial" if count else "abstained"
    _require(type(backend["decoded_count"]) is int and backend["decoded_count"] == count
             and backend["status"] == expected_status, "native batch count or status differs")


def _assemble(requests, latents, metadata, control, backend, exception):
    rows, positions, _, owner_control = _prepare(requests, latents, metadata, control)
    _require(exception is None or exception in ("ImportError", "OSError", "RuntimeError"),
             "unknown operational exception category")
    _require(positions or backend is None and exception is None, "blocked batch contains backend execution")
    if positions:
        _require((backend is None) is (exception is not None), "decoder completion and exception disagree")
        if backend is not None:
            _bind_backend(backend, rows, positions, requests, metadata, owner_control)
    result = {"schema": SCHEMA, "decoder_metadata": copy.deepcopy(metadata),
        "requested_control": control, "owner_control": owner_control, "rows": rows,
        "input_count": len(rows), "eligible_count": len(positions), "submitted_positions": positions,
        "decoder_call_count": int(bool(positions)), "decoder_completion_count": int(backend is not None),
        "backend_result": copy.deepcopy(backend), "backend_exception_type": exception,
        "execution_policy": EXECUTION_POLICY, "validation_scope": VALIDATION_SCOPE, **_FALSE}
    result["content_sha256"] = _digest(result)
    return result


def decode_with_preflight(decoder, requests, latents=None, *, latent_ablation="none"):
    """Invoke the existing owner once for eligible inputs; never accept outputs.

    The caller supplies an already constructed decoder. Operational failures
    expose only their base exception category. Owner contract errors propagate.
    No grammar proposals, target vocabulary or context interpretation run here.
    """
    requests, latents = copy.deepcopy(requests), copy.deepcopy(latents)
    metadata = _metadata(decoder)
    _, positions, effective, owner_control = _prepare(requests, latents, metadata, latent_ablation)
    backend, exception = None, None
    if positions:
        texts = [requests[position]["source_text"] for position in positions]
        vectors = [effective[position] for position in positions] if metadata["input_dimension"] else None
        try:
            backend = decoder.decode_formal_logic(texts, vectors, latent_ablation=owner_control)
        except ImportError:
            exception = "ImportError"
        except OSError:
            exception = "OSError"
        except RuntimeError:
            exception = "RuntimeError"
        _require(_raw(_metadata(decoder)) == _raw(metadata), "decoder metadata changed during invocation")
    return _assemble(requests, latents, metadata, latent_ablation, backend, exception)


def validate_preflight_decoding(record, requests, latents=None):
    """Check detached saved evidence without loading a decoder or replaying ML.

    Integrity and recomputation reject changed joins, fields or authority even
    after resealing. Saved native predictions and metadata remain bound evidence,
    rather than independently recomputed numerical observations or attestation.
    """
    _keys(record, _RECORD, "source-preflight decoder receipt")
    expected = _assemble(copy.deepcopy(requests), copy.deepcopy(latents), record["decoder_metadata"],
                         record["requested_control"], record["backend_result"], record["backend_exception_type"])
    _require(_raw(record) == _raw(expected), "receipt differs from deterministic preparation and bound native output")
    return expected


__all__ = ["decode_with_preflight", "validate_preflight_decoding"]
