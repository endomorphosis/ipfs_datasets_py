"""Formal output access for every explicitly versioned legal autoencoder.

These checkpoints decode embeddings, not formula tokens. The supported formal
route is the existing deterministic modal compiler conditioned on model
guidance. It retains the complete emitted AST and labels this dependence; an
independent learned decoder request abstains instead of borrowing a target.
No training, checkpoint loading, external prover or Lake invocation occurs.
"""
from __future__ import annotations

import hashlib
import importlib
from itertools import islice
import json
import re
import time

from .autoencoder_lineages._contract import (
    LineageModelContract, require_canonical_modules, validate_sample,
)
from .legacy_span_guided_compiler import GuidedLegacyCompiler

SCHEMA = "legal-autoencoder-formal-decode/v1"
MAX_BATCH_SAMPLES = 128
MAX_BATCH_RESULT_BYTES = 64 * 1024 * 1024
FALSE = {"independent": False, "learned_formula_generation": False,
         "qualified": False, "admitted": False, "formalized": False,
         "promotion_performed": False, "training_executed": False}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _name(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", value) else _json(value)


def _display(payload):
    """Readable modal notation; full AST remains the authoritative output.

    Conditions/exceptions are opaque ordered scope atoms, not automatically
    converted into an implication, negation, or temporal logic translation.
    JSON quoting distinguishes literal names from executable formula syntax.
    """
    operator, predicate = payload["operator"], payload["predicate"]
    head = (_name(operator["symbol"]) + "[" + _name(operator["family"])
            + ":" + _name(operator.get("system", "")) + "]")
    atom = _name(predicate["name"]) + "(" + ", ".join(
        _name(argument) for argument in predicate.get("arguments", [])) + ")"
    scope = {key: payload[key] for key in ("conditions", "exceptions") if payload.get(key)}
    annotations = {"predicate_role": predicate.get("role"), "metadata": payload.get("metadata", {})}
    return (head + "(" + atom + ")" + (" scope=" + _json(scope) if scope else "")
            + " annotations=" + _json(annotations))


def _canonical_observation(sample):
    """Strict compiler with parser-owned vocabulary; no partial or repair path."""
    from ...logic.autoformal import vocabulary_from_clause
    from ...logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler
    from ...logic.legal_ir.canonical_contracts import CanonicalAtomVocabulary, CompilerRequest
    from ...logic.legal_ir.canonical_decompiler import decompile_rule
    started = time.perf_counter()
    vocabulary = vocabulary_from_clause(sample.text)
    result = TypedDeonticCanonicalCompiler().compile(CompilerRequest(
        source_text=sample.text, request_id=sample.sample_id,
        atom_vocabulary=CanonicalAtomVocabulary(**(vocabulary or {})),
        allow_explicit_partial=False))
    outputs = []
    for rule in result.canonical_ir.rules if result.canonical_ir is not None else ():
        payload = rule.to_dict()
        scope = {key: payload[key] for key in ("conditions", "exceptions", "temporal") if payload[key]}
        display = (rule.modality + "(" + _name(rule.action) + "(" + _name(rule.actor)
                   + ", " + _name(rule.object) + "))" + (" scope=" + _json(scope) if scope else ""))
        outputs.append({"family": "deontic", "format": "typed-deontic-rule/v1",
                        "payload": payload, "expression": _json(payload),
                        "expression_format": "typed-deontic-rule/v1", "formula_text": display,
                        "formula_text_role": "display_only_full_ast_is_authoritative",
                        "origin": "canonical_compiler", "independent": False,
                        "target_conditioned": False, "syntax_status": "compiler_accepted",
                        "decompiled_text": decompile_rule(rule)})
    return {"origin": "canonical_compiler", "vocabulary_source": "deontic_parser_string_atoms",
            "vocabulary": vocabulary, "status": result.status.value,
            "formal_outputs": outputs, "receipt": result.to_dict(),
            "elapsed_seconds": time.perf_counter() - started, **FALSE}


def _scope_text(value):
    text = " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).split())
    return re.sub(r"\b(days|weeks|months|years|hours|minutes|seconds)\b", lambda m: m[0][:-1], text)


def _compare_canonical(outputs, canonical):
    """Detect overt single-rule disagreements; never assert equivalence.

    The modal and canonical IRs have different vocabularies. Only explicit
    deontic symbols and exception fields are compared directly. Conditions and
    temporal atoms get a conservative textual coverage report, not a theorem.
    """
    expected = canonical["formal_outputs"]
    actual = [row for row in outputs if row["payload"]["operator"].get("family") == "deontic"]
    base = {"method": "single_rule_explicit_operator_and_scope/v1",
            "semantic_equivalence_verified": False, "conflicts": [], "coverage_gaps": []}
    if len(expected) != 1 or len(actual) != 1 or len(outputs) != 1:
        return {**base, "status": "not_comparable", "reason": "requires_one_rule_from_each_compiler"}
    canonical_rule, modal = expected[0]["payload"], actual[0]["payload"]
    conflicts, gaps = [], []
    canonical_symbol, symbol = canonical_rule["modality"], modal["operator"].get("symbol")
    if symbol in {"O", "P", "F"} and symbol != canonical_symbol:
        conflicts.append({"field": "modality", "canonical": canonical_symbol, "guided": symbol})
    elif symbol not in {"O", "P", "F"}:
        gaps.append({"field": "modality", "reason": "guided_symbol_not_comparable"})
    if [_scope_text(atom) for atom in canonical_rule["exceptions"]] != [
            _scope_text(atom) for atom in modal.get("exceptions", [])]:
        conflicts.append({"field": "exceptions", "canonical": canonical_rule["exceptions"],
                          "guided": modal.get("exceptions", [])})
    explicit_scope = _scope_text(_json({key: modal.get(key) for key in ("predicate", "conditions", "exceptions")}))
    for field in ("conditions", "temporal"):
        missing = [atom for atom in canonical_rule[field] if _scope_text(atom) not in explicit_scope]
        if missing:
            gaps.append({"field": field, "canonical_atoms_not_explicit_in_guided_scope": missing})
    return {**base, "status": "semantic_conflict" if conflicts else "comparison_incomplete" if gaps
            else "no_detected_conflict", "conflicts": conflicts, "coverage_gaps": gaps,
            "canonical_modality": canonical_symbol, "guided_modality": symbol}


class LegalFormalDecoder:
    """One caller-owned legal model and cached compiler; serialize its calls.

    This facade supports frozen 8D, optimized 8D, and current 384D models. The
    canonical compiler tree is shared and checked before any observer call.
    The checkpoint identity describes the initially loaded file; a training
    state modified since loading is not re-attested by that identity.
    """

    def __init__(self, model, *, mode="guided_compiler", top_k=8, include_observation_documents=False):
        if not isinstance(model, LineageModelContract):
            raise TypeError("formal decoding requires an explicit legal lineage facade")
        if mode not in {"guided_compiler", "canonical_compiler", "independent"}:
            raise ValueError("formal decoder mode must be guided_compiler, canonical_compiler or independent")
        if type(top_k) is not int or not 1 <= top_k <= 32:
            raise ValueError("formal decoder top_k must be an integer from 1 to 32")
        if type(include_observation_documents) is not bool:
            raise ValueError("include_observation_documents must be a boolean")
        require_canonical_modules(model._implementation_class.__module__)
        self.model, self.mode = model, mode
        self.include_observation_documents = include_observation_documents
        self.observer = GuidedLegacyCompiler(model, top_k=top_k,
                                            model_identity=model.describe().get("checkpoint_identity"))

    def decode(self, sample):
        """Return actual compiler-guided ASTs, or a specific bounded abstention."""
        require_canonical_modules(self.model._implementation_class.__module__)
        self.model._validate_state(self.model.state)
        validate_sample(sample, self.model.DIMENSION)
        text, sample_id = getattr(sample, "text", None), getattr(sample, "sample_id", None)
        if not isinstance(text, str) or not text.strip() or len(text) > 16384:
            raise ValueError("formal decoding requires one nonempty source span up to 16384 characters")
        if not isinstance(sample_id, str) or not sample_id:
            raise ValueError("formal decoding requires a nonempty sample identity")
        base = {"schema": SCHEMA, "domain": "legal_ir", "mode": self.mode,
                "sample_id": sample_id, "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "lineage_id": self.model.LINEAGE_ID, "dimension": self.model.DIMENSION,
                "formal_outputs": [], "formula_count": 0, "syntax_status": "not_checked",
                "semantic_equivalence_status": "not_checked",
                "lake": {"status": "not_run", "admitted": False}, **FALSE}
        if self.mode == "independent":
            return {**base, "status": "unsupported",
                    "reason": "checkpoint_has_no_learned_formula_decoder"}
        if self.mode == "guided_compiler":
            parser_module = importlib.import_module(
                self.model._implementation_class.__module__.rsplit(".", 1)[0] + ".legal_modal_parser")
            normalized = parser_module.LegalModalParser().normalize_text(text)
            parsed = getattr(sample, "modal_ir", None)
            if (getattr(sample, "normalized_text", None) != normalized
                    or getattr(parsed, "normalized_text", None) != normalized
                    or getattr(parsed, "document_id", None) != sample_id):
                raise ValueError("guidance parser features must bind the same sample identity and normalized source")
        canonical = _canonical_observation(sample)
        if self.mode == "canonical_compiler":
            outputs = canonical["formal_outputs"]
            return {**base, "status": "compiled" if outputs else "abstained",
                    "reason": None if outputs else canonical["status"], "origin": "canonical_compiler",
                    "formal_outputs": outputs, "formula_count": len(outputs),
                    "syntax_status": "compiler_accepted" if outputs else "not_checked",
                    "model_used": False, "complete_span_semantics_verified": False,
                    "canonical_observation": canonical}
        observation = self.observer.observe(sample)
        outputs = observation.get("guided_formal_outputs", [])
        # The complete native AST, including temporal/scope metadata, is copied
        # verbatim. Display notation is not substituted for executable syntax.
        outputs = json.loads(_json(outputs))
        for row in outputs:
            payload = row["payload"]
            row["expression"] = _json(payload)
            row["expression_format"] = "modal-ir-formula/v1"
            row["formula_text"] = _display(payload)
            row["formula_text_role"] = "display_only_full_ast_is_authoritative"
            force = payload.get("metadata", {}).get("compiler_guidance_deontic_force")
            label = payload["operator"].get("label")
            row["semantic_warnings"] = (["operator_label_and_guidance_force_differ"]
                                        if force and label and force != label else [])
        comparison = _compare_canonical(outputs, canonical)
        status = ("semantic_conflict" if comparison["status"] == "semantic_conflict" else
                  "decoded_guided" if outputs else "abstained")
        reason = (None if outputs else "compiler_emitted_no_formulas"
                  if observation.get("status") == "captured" else observation.get("status", "error"))
        omitted = []
        if not self.include_observation_documents:
            # Full codec documents contain megabytes of duplicate frame/context
            # triples. All emitted formulas, guidance, document hashes and byte
            # counts remain; callers can explicitly retain full documents too.
            omitted = [key for key in ("document", "direct_document", "source_parser_document")
                       if key in observation]
            observation = {key: value for key, value in observation.items() if key not in omitted}
        return {**base, "status": status, "reason": reason,
                "origin": "autoencoder_guided_compiler", "formal_outputs": outputs,
                "formula_count": len(outputs), "target_conditioned": observation.get("target_conditioned"),
                "guidance_uses_input_parser_features": True,
                "sample_parser_features_independently_verified": False,
                "guidance_target_cache_conditioned": observation.get("target_conditioned"),
                "complete_span_semantics_verified": False,
                "canonical_observation": canonical, "canonical_comparison": comparison,
                "observation_documents_omitted": omitted,
                "observation": observation}


def decode_legal_formulas(model, samples, *, mode="guided_compiler", top_k=8,
                          include_observation_documents=False):
    """Bound one batch and validate every width before doing compiler work."""
    if not isinstance(model, LineageModelContract):
        raise TypeError("formal decoding requires an explicit legal lineage facade")
    bounded = list(islice(iter(samples), MAX_BATCH_SAMPLES + 1))
    if len(bounded) > MAX_BATCH_SAMPLES:
        raise ValueError("formal decode batch exceeds 128 samples; use incremental batches")
    for sample in bounded:
        validate_sample(sample, model.DIMENSION)
    decoder = LegalFormalDecoder(model, mode=mode, top_k=top_k,
                                 include_observation_documents=include_observation_documents)
    rows, result_bytes = [], 0
    for sample in bounded:
        row = decoder.decode(sample)
        result_bytes += len(_json(row).encode())
        if result_bytes > MAX_BATCH_RESULT_BYTES:
            raise ValueError("formal decode result exceeds 64 MiB; use smaller incremental batches")
        rows.append(row)
    return {"schema": SCHEMA, "domain": "legal_ir", "mode": mode,
            "sample_count": len(rows), "formula_count": sum(row["formula_count"] for row in rows),
            "rows": rows, **FALSE}


__all__ = ["LegalFormalDecoder", "decode_legal_formulas", "SCHEMA"]
