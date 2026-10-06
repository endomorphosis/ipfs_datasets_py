"""Inspect generated rule tokens and score IR/text reconstruction separately.

These functions receive already-generated candidates. They never load a model,
feed reference targets to generation, infer omitted rules, or substitute source
text for failed decoding. CanonicalRoundTripIR@1 sorts its rules; the original
generated order is retained separately. Contract conformance and agreement with
a reference do not establish legal meaning, held-out quality or proof authority.
"""
from copy import deepcopy
import hashlib
import unicodedata

from . import decoder_source_fidelity as fidelity

INSPECTION_SCHEMA = "contextual-legal-generated-payload-inspection/v1"
EVALUATION_SCHEMA = "contextual-legal-reconstruction-evaluation/v1"
TEXT_SCHEMA = "legal-text-reconstruction-observation/v1"
MAX_ROWS = 64
MAX_TEXT_BYTES = 1024 * 1024
_PREDICTION_FIELDS = {"id", "token_ids", "generation_status", "eos_reached"}
_AUTHORITY = {"model_loaded": False, "model_inference_observed": False,
    "source_semantics_verified": False, "runtime_admitted": False,
    "teacher_qualified": False, "proof_authority": False, "fresh_holdout_qualified": False}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _identity(value):
    _require(type(value) is str and 0 < len(value) <= 512 and value.isprintable(),
             "bounded printable row identity required")
    return value


def _codec(codec):
    _require(type(codec) is dict and set(codec) == {"schema", "target_vocabulary"}
             and codec["schema"] == "typed-json-lexical/v1", "exact typed JSON lexical codec required")
    vocabulary = codec["target_vocabulary"]
    _require(type(vocabulary) is list and 4 <= len(vocabulary) <= 4096
             and vocabulary[:3] == ["<pad>", "<bos>", "<eos>"]
             and all(type(token) is str and 0 < len(token) <= 16384 for token in vocabulary)
             and len(set(vocabulary)) == len(vocabulary), "bounded ordered codec vocabulary required")
    _require(len(fidelity._raw(codec)) <= 4 * 1024 * 1024, "codec exceeds byte bound")
    return vocabulary


def _predictions(predictions):
    _require(type(predictions) is list and len(predictions) <= MAX_ROWS, "bounded generated row list required")
    seen = set()
    for row in predictions:
        _require(type(row) is dict and set(row) == _PREDICTION_FIELDS,
                 "closed generated token/status/EOS row required")
        _require(type(row["generation_status"]) is str
                 and row["generation_status"] in ("eos", "output_limit", "invalid_special_token", "deadline"),
                 "explicit supported generation status required")
        _identity(row["id"])
        _require(row["id"] not in seen, "duplicate generated identity")
        seen.add(row["id"])
    return deepcopy(predictions)


def _native_ir(value):
    # The real contract owner is separate from the decoder's restricted codec.
    from ...legal_ir.canonical_contracts import CanonicalRoundTripIR
    return CanonicalRoundTripIR.from_dict(deepcopy(value))


def _validate_rule(wrapper):
    _native_ir(wrapper)
    return {"valid": True}


def inspect_contextual_legal_predictions(predictions, *, codec, output_limit=512):
    """Parse only generated content; preserve errors, EOS and original order.

    Token IDs exclude BOS/EOS; the output limit includes both. A valid complete
    document without an EOS receipt stays an incomplete candidate. The native
    canonical form is an additional observation, never a replacement for the
    original ordered model output.
    """
    _require(type(output_limit) is int and 4 <= output_limit <= 512, "bounded explicit output limit required")
    vocabulary = _codec(codec)
    rows = _predictions(predictions)
    observed = []
    for prediction in rows:
        evidence = fidelity._prediction(prediction, vocabulary, output_limit)
        errors = list(evidence["errors"])
        canonical = None
        if evidence["rules"] is not None and not errors:
            try:
                # Reuse complete seven-facet validation; no evaluator reference
                # or source fallback is available on this parsing path.
                for rule in evidence["rules"]:
                    fidelity._rule(rule, _validate_rule)
                canonical = _native_ir(evidence["parsed"])
            except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError) as error:
                errors.append(str(error)[:512])
        ordered = deepcopy(evidence["parsed"])
        canonical_payload = None if canonical is None else canonical.to_dict()
        valid = canonical is not None and not errors
        observed.append({"id": prediction["id"], "generation_status": evidence["status"],
            "eos_reached": evidence["eos"], "generated_token_ids": evidence["token_ids"],
            "ordered_generated_ir": ordered, "canonical_contract_ir": canonical_payload,
            "canonical_contract_ir_cid": None if canonical is None else canonical.ir_cid,
            "canonical_contract_valid": valid, "complete_candidate": valid and evidence["eos"],
            "canonicalization_changed_payload": canonical_payload is not None and canonical_payload != ordered,
            "errors": errors, "authority": dict(_AUTHORITY)})
    return {"schema": INSPECTION_SCHEMA, "codec_sha256": fidelity.digest(codec),
        "output_limit": output_limit, "canonical_contract_interface": "CanonicalRoundTripIR@1",
        "rows": observed, "candidate_count": len(observed),
        "complete_candidates": sum(row["complete_candidate"] for row in observed),
        "canonical_contract_valid_candidates": sum(row["canonical_contract_valid"] for row in observed),
        "scope": "Generated token parsing and actual canonical contract conformance; no source-meaning or proof validation.",
        "authority": dict(_AUTHORITY)}


def score_contextual_legal_predictions(references, predictions, *, codec, output_limit=512):
    """Score generated output with fixed reference denominators after inference.

    Ordered exactness and all seven facet counts reuse the existing fidelity
    owner. Canonical contract exactness additionally compares its sorted native
    payloads. It is equivalence under this bounded contract, not arbitrary legal
    semantic equivalence. Source-text reconstruction is unmeasured here.
    """
    _require(type(references) is list and 1 <= len(references) <= MAX_ROWS,
             "bounded separate reference rows required")
    allowed = {"id", "target", "clause_count", "source_text", "source_sha256"}
    for row in references:
        _require(type(row) is dict and {"id", "target", "clause_count"} <= set(row)
                 and set(row) <= allowed, "closed separate IR reference row required")
    inspected = inspect_contextual_legal_predictions(predictions, codec=codec, output_limit=output_limit)
    report = fidelity.score_predictions(deepcopy(references), _predictions(predictions), codec=deepcopy(codec),
        validate_rule=_validate_rule, output_limit=output_limit,
        validator_id="CanonicalRule@CanonicalRoundTripIR@1")
    indexed = {row["id"]: row for row in inspected["rows"]}
    canonical_rows = []
    for reference in references:
        native_reference = _native_ir(reference["target"])
        candidate = indexed.get(reference["id"])
        exact = bool(candidate is not None and candidate["complete_candidate"]
                     and candidate["canonical_contract_ir"] == native_reference.to_dict())
        canonical_rows.append({"id": reference["id"], "canonical_contract_exact": exact,
            "reference_canonical_ir_cid": native_reference.ir_cid,
            "candidate_canonical_ir_cid": None if candidate is None else candidate["canonical_contract_ir_cid"]})
    return {"schema": EVALUATION_SCHEMA, "reference_agreement": report,
        "generated_payload_inspection": inspected, "canonical_contract_rows": canonical_rows,
        "canonical_contract_exact": sum(row["canonical_contract_exact"] for row in canonical_rows),
        "reference_count": len(references), "source_text_reconstruction_measured": False,
        "source_semantic_equivalence_measured": False,
        "scope": "Reference IR agreement measured after source-only generation; exposed panels do not establish fresh holdout.",
        "authority": dict(_AUTHORITY)}


def render_contextual_legal_text_candidates(predictions, *, codec, output_limit=512):
    """Render complete generated IR through the existing source-withheld owner.

    This deterministic baseline receives only generated canonical IR and a row
    identity. It has no originating source, lexical residual, reference IR or
    trained text head. Its output can be compared with original text using the
    separate scorer below; rendering alone does not establish a round trip.
    """
    from ...legal_ir.canonical_contracts import DecompilerRequest, OperationStatus
    from ...legal_ir.canonical_decompiler import SourceWithheldCanonicalDecompiler

    inspection = inspect_contextual_legal_predictions(predictions, codec=codec, output_limit=output_limit)
    owner = SourceWithheldCanonicalDecompiler()
    texts, receipts, refusals = [], [], []
    for row in inspection["rows"]:
        if not row["complete_candidate"]:
            refusals.append({"id": row["id"], "reason": "generated_IR_is_not_a_complete_contract_valid_candidate"})
            continue
        request = DecompilerRequest(canonical_ir=_native_ir(row["canonical_contract_ir"]), request_id=row["id"])
        result = owner.decompile(request)
        if result.status != OperationStatus.SUCCESS:
            refusals.append({"id": row["id"], "reason": "source_withheld_decompiler_refused"})
            continue
        texts.append({"id": row["id"], "reconstructed_text": result.text})
        receipts.append({"id": row["id"], "request_cid": request.request_cid,
            "canonical_ir_cid": request.canonical_ir.ir_cid,
            "result": result.to_dict()})
    return {"schema": "contextual-legal-source-withheld-rendering/v1",
        "generated_payload_inspection": inspection, "reconstructions": texts,
        "rendering_receipts": receipts, "refusals": refusals,
        "decompiler_interface": owner.identity, "decompiler_uses_model": owner.uses_model,
        "originating_source_passed_to_decompiler": False, "reference_IR_passed_to_decompiler": False,
        "scope": "Existing deterministic source-withheld canonical paraphrase baseline, not a trained original-prose decoder.",
        "authority": dict(_AUTHORITY)}


def score_legal_text_reconstructions(references, reconstructions):
    """Measure original-text bytes and NFC/whitespace equality separately.

    References are ``{id, source_text}``; reconstructions are
    ``{id, reconstructed_text}``. Missing predictions count as failed rows.
    Case, punctuation and word order remain significant in both metrics.
    Neither comparison measures equivalent legal meaning.
    """
    _require(type(references) is list and 1 <= len(references) <= MAX_ROWS
             and type(reconstructions) is list and len(reconstructions) <= len(references),
             "bounded explicit text references/reconstructions required")

    def text(value):
        _require(type(value) is str, "explicit text string required")
        raw = value.encode("utf-8")
        _require(len(raw) <= MAX_TEXT_BYTES, "text exceeds byte bound")
        return raw

    def normalized(value):
        return " ".join(unicodedata.normalize("NFC", value).split())

    by_id = {}
    for row in references:
        _require(type(row) is dict and set(row) == {"id", "source_text"}, "closed original-text reference required")
        _identity(row["id"])
        _require(row["id"] not in by_id, "duplicate original-text reference")
        _require(bool(text(row["source_text"])), "nonempty original text required")
        by_id[row["id"]] = row["source_text"]
    generated = {}
    for row in reconstructions:
        _require(type(row) is dict and set(row) == {"id", "reconstructed_text"}, "closed reconstructed-text row required")
        _identity(row["id"])
        _require(row["id"] in by_id and row["id"] not in generated, "unknown or duplicate reconstructed identity")
        text(row["reconstructed_text"])
        generated[row["id"]] = row["reconstructed_text"]
    rows = []
    for row in references:
        original = row["source_text"]
        output = generated.get(row["id"])
        rows.append({"id": row["id"], "prediction_present": output is not None,
            "source_utf8_sha256": hashlib.sha256(text(original)).hexdigest(),
            "reconstructed_utf8_sha256": None if output is None else hashlib.sha256(text(output)).hexdigest(),
            "verbatim_utf8_exact": output is not None and text(output) == text(original),
            "nfc_whitespace_exact": output is not None and normalized(output) == normalized(original)})
    return {"schema": TEXT_SCHEMA, "rows": rows, "reference_count": len(rows),
        "prediction_count": len(generated), "missing_prediction_count": len(rows) - len(generated),
        "verbatim_utf8_exact": sum(row["verbatim_utf8_exact"] for row in rows),
        "nfc_whitespace_exact": sum(row["nfc_whitespace_exact"] for row in rows),
        "normalization_policy": "Unicode NFC followed by whitespace collapse; case, punctuation and word order preserved",
        "legal_meaning_equivalence_measured": False, "decoder_execution_observed": False,
        "authority": dict(_AUTHORITY)}


__all__ = ["inspect_contextual_legal_predictions", "score_contextual_legal_predictions",
           "render_contextual_legal_text_candidates", "score_legal_text_reconstructions"]
