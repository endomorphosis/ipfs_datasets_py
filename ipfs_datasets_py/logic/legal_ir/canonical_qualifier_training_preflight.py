"""Complete-cohort qualifier transport diagnosis, never label admission.

The existing word codec fits only the complete supplied TRAIN cohort. Its
64-token limits and the byte codec's explicit 512-token limit remain distinct.
Received scope and review declarations are replayed by their original owners;
their structural validity never authenticates meanings or enables training.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from ...optimizers.logic_theorem_optimizer import legal_formula_codec as word_codec_owner
from . import canonical_byte_codec as byte_codec
from . import canonical_label_evidence_intake as intake
from . import canonical_statement_scope as scope

SCHEMA = "canonical-qualifier-training-preflight/v1"
OUTPUT_CAP = 512
MAX_ROWS = 64
MAX_BYTES = 16 * 1024 * 1024
FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
QUALIFIERS = FACETS[4:]
_REQUIRED = {"id", "split", "source_text", "canonical_ir"}
_OPTIONAL = {"context", "scope_declaration", "byte_proposal"}
_FALSE = dict.fromkeys(("train_eligible", "qualified", "admitted", "Lean_admitted", "formalized",
                       "proof_authority", "source_semantics_verified", "training_executed",
                       "model_executed", "encoder_executed", "Lake_executed", "downloads_performed"), False)


def _raw(value):
    """Bound ordinary input before recursive owner validation."""
    remaining = 100_000

    def visit(node, depth=0):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 32:
            raise ValueError("preflight JSON node/depth bound exceeded")
        if type(node) is dict:
            if any(type(key) is not str for key in node):
                raise ValueError("plain JSON keys required")
            for key, item in node.items():
                visit(key, depth + 1)
                visit(item, depth + 1)
        elif type(node) is list:
            for item in node:
                visit(item, depth + 1)
        elif node is not None and type(node) not in (str, int, float, bool):
            raise ValueError("plain JSON values required")

    visit(value)
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")
    if len(data) > MAX_BYTES:
        raise ValueError("preflight input byte bound exceeded")
    return data


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _context(row):
    value = row.get("context", {"role": "none_required", "text": "", "bindings": {},
                                "sha256": hashlib.sha256(b"").hexdigest()})
    request = {"source_text": row["source_text"], "context": value}
    scope._input(request)
    return request


def _scope_matches(declaration, canonical_ir):
    """Compare flat leaves in original order; never sort, deduplicate or drop."""
    table = {item["occurrence_id"]: item["canonical_symbol"] for item in declaration["occurrences"]}

    def leaves(node):
        if node is None:
            return []
        if node["op"] == "leaf":
            return [table[node["occurrence_id"]]]
        return [value for child in node["children"] for value in leaves(child)]

    rules = []
    for rule in declaration["rules"]:
        value = {facet: table[ref] if ref is not None else "" for facet, ref in rule["body"].items()}
        value.update({facet: leaves(rule["qualifiers"][facet]) for facet in QUALIFIERS})
        rules.append(value)
    return {"rules": rules} == canonical_ir


def _review(review_inputs):
    if review_inputs is None:
        return {"status": "not_supplied", "replayed": False, "train_eligible": False}
    expected = {"packet", "recording", "package", "expected_bindings", "selected_process_binding"}
    if type(review_inputs) is not dict or set(review_inputs) != expected:
        return {"status": "invalid", "replayed": False, "train_eligible": False,
                "reason": "complete existing label-intake replay inputs required; a receipt alone is not authority"}
    try:
        receipt = intake.validate_label_evidence_intake(**review_inputs)
    except (ValueError, TypeError, KeyError) as error:
        return {"status": "invalid", "replayed": False, "train_eligible": False, "reason": str(error)}
    # The existing intake is diagnostic only. Even declared acceptance and
    # mechanical agreement retain pending verification/admission and zero masks.
    return {"status": receipt["status"], "replayed": True, "train_eligible": False,
            "receipt_sha256": receipt["content_sha256"], "verification_status": receipt["verification_status"],
            "admission_status": receipt["admission_status"], "masks": deepcopy(receipt["masks"]),
            "formal_targets_admitted": receipt["formal_targets_admitted"],
            "item_count": receipt["item_count"], "declared_package_item_count": receipt["declared_package_item_count"]}


def preflight_qualifier_cohort(rows, *, word_codec=None, review_inputs=None):
    """Retain every row and diagnose complete flat versus occurrence transport.

    Rows have id, train/tuning split, source_text and complete canonical_ir.
    Optional exact context, scope_declaration and byte_proposal are checked,
    never generated from source prose. A supplied word codec is validated;
    otherwise all TRAIN rows must be representable before fitting its vocabulary.
    No rejected TRAIN row is omitted to manufacture a smaller successful cohort.
    """
    if type(rows) is not list or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError("one through 64 explicit cohort rows required")
    _raw([rows, word_codec, review_inputs])
    records, ids, sources, training = [], set(), {}, []
    facet_counts = dict.fromkeys(QUALIFIERS, 0)
    total_rules = 0
    for index, row in enumerate(rows):
        record = {"row_index": index, "id": None, "split": None, "issues": [],
                  "word_transport": {"supported": False, "codec_source_cap": word_codec_owner.MAX_SOURCE_TOKENS,
                      "codec_target_cap": word_codec_owner.MAX_TARGET_TOKENS, "task_output_cap": OUTPUT_CAP},
                  "byte_transport": {"supported": False,
                  "configured_output_cap": OUTPUT_CAP}, "scope_transport": {"supplied": False}, **_FALSE}
        records.append(record)
        # Counts describe every supplied label shape, including rows later
        # rejected for identity, source, scope or vocabulary. Missing shapes
        # remain explicit rather than becoming apparent empty qualifiers.
        ir = row.get("canonical_ir") if type(row) is dict else None
        rules = ir.get("rules") if type(ir) is dict else None
        record["rule_count_observed"] = len(rules) if type(rules) is list else None
        record["qualifier_value_counts_observed"] = dict.fromkeys(QUALIFIERS, 0)
        record["qualifier_facets_unavailable"] = [] if type(rules) is list else ["/rules"]
        if type(rules) is list:
            total_rules += len(rules)
            for rule_index, rule in enumerate(rules):
                if type(rule) is dict:
                    for facet in QUALIFIERS:
                        if type(rule.get(facet)) is list:
                            count = len(rule[facet])
                            facet_counts[facet] += count
                            record["qualifier_value_counts_observed"][facet] += count
                        else:
                            record["qualifier_facets_unavailable"].append(f"/rules/{rule_index}/{facet}")
                else:
                    record["qualifier_facets_unavailable"].append(f"/rules/{rule_index}")
        try:
            if type(row) is not dict or not _REQUIRED <= set(row) or set(row) - _REQUIRED - _OPTIONAL:
                raise ValueError("closed cohort row fields required; no receipt or authority flags")
            record.update(id=row["id"], split=row["split"])
            if type(row["id"]) is not str or not 1 <= len(row["id"]) <= 512 or not row["id"].strip() or row["id"] in ids:
                raise ValueError("unique nonempty row id required")
            ids.add(row["id"])
            if row["split"] not in ("train", "tuning"):
                raise ValueError("explicit train or tuning split required")
            request = _context(row)
            record["input_sha256"] = _digest(request)
            source_key = " ".join(row["source_text"].casefold().split())
            if source_key in sources:
                raise ValueError("duplicate source or TRAIN/tuning source overlap")
            sources[source_key] = row["split"]
            ir = row["canonical_ir"]
            word_codec_owner._rule(ir)
            record["source_token_count"] = len(word_codec_owner._source_tokens(row["source_text"]))
            if request["context"]["role"] != "none_required":
                raise ValueError("context resolution has no qualified flat transport; no concatenation performed")
            declaration = row.get("scope_declaration")
            if declaration is not None:
                validated = scope.validate_scope_declaration(request, declaration, expected_input_sha256=record["input_sha256"])
                compatibility = scope.assess_flat_profile_compatibility(declaration, byte_output_cap=OUTPUT_CAP)
                record["scope_transport"] = {"supplied": True, "validation_sha256": validated["content_sha256"],
                                             "compatibility": compatibility}
                profile = compatibility["profiles"]["canonical_roundtrip_ir_v1"]
                if not profile["facet_transport_compatible_without_normalization"]:
                    raise ValueError("occurrence-aware transport required; flat normalization/lowering is forbidden")
                if not _scope_matches(declaration, ir):
                    raise ValueError("complete scope leaves differ from supplied seven-facet target")
            record["structure_supported"] = True
            if row["split"] == "train":
                training.append({key: row[key] for key in ("id", "source_text", "canonical_ir")})
        except (ValueError, TypeError, KeyError) as error:
            record["structure_supported"] = False
            record["issues"].append(str(error))
            record["word_transport"]["reason"] = "structure_or_scope_unrepresentable"
            record["byte_transport"]["reason"] = "structure_or_scope_unrepresentable"
    codec = None
    codec_error = None
    try:
        if word_codec is not None:
            word_codec_owner.validate_codec(word_codec)
            codec = word_codec
        elif any(not record["structure_supported"] and not (
                    type(row) is dict and type(row.get("split")) is str and row["split"] == "tuning")
                 for row, record in zip(rows, records, strict=True)):
            raise ValueError("complete TRAIN cohort is unrepresentable or unclassified; no failed row was discarded")
        elif not training:
            raise ValueError("no complete TRAIN cohort for vocabulary fitting")
        else:
            codec = word_codec_owner.fit_codec(training)
    except (ValueError, TypeError, KeyError) as error:
        codec_error = str(error)
    for row, record in zip(rows, records, strict=True):
        if not record["structure_supported"]:
            continue
        try:
            if codec is None:
                raise ValueError(codec_error)
            source_ids = word_codec_owner.encode_source(codec, row["source_text"])
            target_ids = word_codec_owner.encode_target(codec, row["canonical_ir"])
            if word_codec_owner.decode_target(codec, target_ids) != row["canonical_ir"]:
                raise ValueError("complete seven-facet target roundtrip differs")
            record["word_transport"] = {"supported": True, "source_token_count": len(source_ids),
                "required_target_token_count": len(target_ids), "codec_source_cap": word_codec_owner.MAX_SOURCE_TOKENS,
                "codec_target_cap": word_codec_owner.MAX_TARGET_TOKENS, "task_output_cap": OUTPUT_CAP}
        except (ValueError, TypeError) as error:
            record["word_transport"]["reason"] = str(error)
        proposal = row.get("byte_proposal")
        if proposal is None:
            record["byte_transport"]["reason"] = "exact source-anchored proposal not supplied; none inferred"
        else:
            try:
                if proposal.get("canonical_ir") != row["canonical_ir"]:
                    raise ValueError("byte proposal differs from complete seven-facet target")
                inspection = byte_codec.inspect_encoding(proposal, row["source_text"], output_cap=OUTPUT_CAP)
                record["byte_transport"] = {**inspection, "supported": inspection["outcome"] == "encoding_admitted"}
            except (ValueError, TypeError, AttributeError) as error:
                record["byte_transport"]["reason"] = str(error)
    from ..formalization.autoencoder.native_formula_evidence import named_logic_routes

    result = {"schema": SCHEMA, "rows": records, "cohort_row_count": len(rows), "reported_row_count": len(records),
              "complete_rule_count_observed": total_rules, "qualifier_value_counts_observed": facet_counts,
              "rows_with_unavailable_qualifier_counts": sum(bool(row["qualifier_facets_unavailable"]) for row in records),
              "structure_supported_rows": sum(row["structure_supported"] for row in records),
              "word_supported_rows": sum(row["word_transport"]["supported"] for row in records),
              "byte_supported_rows": sum(row["byte_transport"]["supported"] for row in records),
              "cohort_word_representable": all(row["word_transport"]["supported"] for row in records),
              "cohort_byte_representable": all(row["byte_transport"]["supported"] for row in records),
              "word_codec_sha256": None if codec is None else _digest(codec), "word_codec_error": codec_error,
              "word_vocabulary_origin": "explicit_supplied_codec" if word_codec is not None else "complete_TRAIN_only",
              "source_context_limit_unchanged": 512, "output_limit": OUTPUT_CAP,
              "review": _review(review_inputs), "review_to_cohort_binding_assessed": False,
              "review_replay_is_training_authority": False, "minimum_native_family_floor": named_logic_routes(),
              "native_family_floor_assessed": False, "family_applicability_assessed": False,
              "source_codec_profile_is_native_family_evidence": False, "normalization_performed": False,
              "rows_discarded": 0, "scope": "representation_diagnosis_only_not_training_or_semantic_admission", **_FALSE}
    result["content_sha256"] = _digest(result)
    return result


__all__ = ["preflight_qualifier_cohort"]
