"""Opt-in batched inference for existing source-pinned latent formula heads.

The original module retains checkpoint validation, numerical architecture and
source pins. This worker-private subclass batches recurrent inference and
reports its own implementation separately, without converting a checkpoint
or changing its digest. Batched float32 operations may round confidence margins
differently; grammar, stable ties and the existing abstention threshold apply
to each row independently. No inference result grants semantic admission.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from . import modal_latent_formula as learning

codec_module = learning.codec_module
FALSE = learning.FALSE
PROJECTION_ID = learning.PROJECTION_ID
_require = learning._require
_rows = learning._rows
_display = learning._display
checkpoint_digest = learning.checkpoint_digest


def _source_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


_SOURCE_AT_IMPORT = _source_sha256()


def inference_implementation():
    """Describe this inference implementation without altering model pins."""
    _require(_source_sha256() == _SOURCE_AT_IMPORT, "batched latent decoder implementation changed since import")
    return {"schema": "modal-latent-formula-inference-implementation/v1",
            "architecture": "active-row-batched-recurrence/v1",
            "source_sha256": _SOURCE_AT_IMPORT, "checkpoint_conversion_performed": False,
            "confidence_margin_parity": "float32_numerical_not_bitwise",
            "batching_policy": "singleton_recurrence_through_sixteen_rows_batched_above_sixteen",
            "grammar_cache_scope": "one_inference_request",
            "completed_rule_cache_scope": "one_inference_request_codec_content_and_tokens",
            "autograd_policy": "inference_mode"}


class BatchedLatentFormulaDecoder(learning.LatentFormulaDecoder):
    """Reuse original checkpoint validation and guards with batched decoding."""
    @property
    def inference_implementation(self):
        return inference_implementation()

    def _check(self):
        super()._check()
        return inference_implementation()

    def _base(self, row, projection_id):
        return {"id": row["id"], "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
            "latent_sha256": checkpoint_digest(row["latent"]), "projection_id": projection_id,
            "status": "abstained", "reason": None, "canonical_ir": None, "formula_text": None, "formal_outputs": [],
            "teacher_forcing": False, "target_access": False, "training_executed": False,
            "source_text_is_neural_input": False, "latent_input_conditioned": True, "independent_text_to_logic": False,
            "learned_formula_generation": True, "sample_memory_used": False, "family_syntax_checked": False,
            "temperature": 0, **FALSE}

    def _decoded(self, base, prefix, minimum_margin, completed_cache=None):
        try:
            # Repeated completed sequences in a batch require the same exact
            # canonical validation, including its rule CID construction. Keep
            # the original validator and cache only its successful result for
            # this request. Codec content is part of the key so a nested write
            # cannot reuse validation under a different grammar or vocabulary.
            key = (checkpoint_digest(self._codec), tuple(prefix)) if completed_cache is not None else None
            cached = completed_cache.get(key) if completed_cache is not None else None
            validator = codec_module.decode_target
            if cached is not None and cached[0] is validator:
                # JSON preserves content but treats lists and tuples alike;
                # Python tuple keys also equate integer and float token IDs.
                # Re-run the original strict codec/prefix checks on every hit.
                # Only the expensive canonical rule/CID validation is reused.
                codec_module._prefix(self._codec, prefix)
                canonical_ir = copy.deepcopy(cached[1])
            else:
                canonical_ir = validator(self._codec, prefix)
                if completed_cache is not None:
                    completed_cache[key] = (validator, copy.deepcopy(canonical_ir))
        except ValueError as error:
            return {**base, "reason": "generated_ir_rejected", "detail": str(error), "generated_token_ids": prefix}
        display = _display(canonical_ir)
        output = {"family": "deontic", "format": "typed-deontic-rule/v1",
            "payload": canonical_ir["rules"][0], "formula_text": display,
            "formula_text_role": "display_only_full_ast_is_authoritative",
            "syntax_scope": "canonical_rule_schema_and_decoder_grammar",
            "origin": "learned_latent_conditioned_formula_decoder", **FALSE}
        return {**base, "status": "decoded", "canonical_ir": canonical_ir, "formula_text": display,
            "formal_outputs": [output], "generated_token_ids": prefix,
            "minimum_decision_logit_margin": minimum_margin,
            "syntax_scope": "canonical_rule_schema_and_decoder_grammar"}

    def _decode_scalar(self, row, projection_id, allowed_cache, *, projected=None, completed_cache=None):
        # Keep singleton float32 operations and stable ranking exactly as in
        # the original scalar decoder, sharing only immutable grammar choices.
        base = self._base(row, projection_id)
        if projection_id != PROJECTION_ID:
            return {**base, "reason": "unsupported_formula_projection"}
        if not self._checkpoint["progress"]["optimizer_steps"]:
            return {**base, "reason": "untrained_formula_head"}
        if not bool(self.model.output.weight.detach().any()) and not bool(self.model.output.bias.detach().any()):
            return {**base, "reason": "zero_output_head"}
        torch = self.torch
        prefix, minimum_margin = [codec_module.TARGET_BOS], None
        self.model.eval()
        with torch.inference_mode():
            if projected is None:
                projected = self.model.project(torch.tensor([row["latent"]], dtype=torch.float32))
            if not bool(torch.isfinite(projected).all()):
                return {**base, "reason": "nonfinite_learned_projection"}
            hidden = self.model.start(projected)
            if not bool(torch.isfinite(hidden).all()):
                return {**base, "reason": "nonfinite_decoder_condition"}
            for _ in range(63):
                key = tuple(prefix)
                if key not in allowed_cache:
                    allowed_cache[key] = tuple(codec_module.allowed_token_ids(self._codec, prefix))
                allowed = allowed_cache[key]
                if not allowed:
                    return {**base, "reason": "no_allowed_grammar_token", "generated_token_ids": prefix}
                logits, hidden = self.model.next_logits(torch.tensor([[prefix[-1]]], dtype=torch.long), hidden)
                scores = logits[0, -1, list(allowed)]
                if not bool(torch.isfinite(scores).all()):
                    return {**base, "reason": "nonfinite_decoder_scores"}
                ranking = torch.argsort(scores, descending=True, stable=True)
                if len(allowed) > 1:
                    margin = float(scores[ranking[0]] - scores[ranking[1]])
                    minimum_margin = margin if minimum_margin is None else min(minimum_margin, margin)
                    if margin <= 1e-7:
                        return {**base, "reason": "ambiguous_decoder_scores", "generated_token_ids": prefix}
                prefix.append(allowed[int(ranking[0])])
                if prefix[-1] == codec_module.TARGET_EOS:
                    return self._decoded(base, prefix, minimum_margin, completed_cache)
        return {**base, "reason": "generation_length_limit", "generated_token_ids": prefix}

    def _decode_batch(self, rows, projection_id, *, projected=None, completed_cache=None):
        # Grammar and confidence decisions remain independent for every row.
        # Only the numerical projection, conditioning and recurrent step are
        # batched; finished or abstaining rows leave the active batch.
        bases = [self._base(row, projection_id) for row in rows]
        if projection_id != PROJECTION_ID:
            return [{**base, "reason": "unsupported_formula_projection"} for base in bases]
        if not self._checkpoint["progress"]["optimizer_steps"]:
            return [{**base, "reason": "untrained_formula_head"} for base in bases]
        if not bool(self.model.output.weight.detach().any()) and not bool(self.model.output.bias.detach().any()):
            return [{**base, "reason": "zero_output_head"} for base in bases]
        torch = self.torch
        results = [None] * len(rows)
        prefixes = [[codec_module.TARGET_BOS] for row in rows]
        margins = [None] * len(rows)
        # A batch often follows the same grammar prefixes. Reusing their
        # allowed IDs avoids validating and parsing that identical prefix
        # once per row. This cache lasts only for this inference request.
        allowed_cache = {}
        self.model.eval()
        with torch.inference_mode():
            if projected is None:
                projected = self.model.project(torch.tensor([row["latent"] for row in rows], dtype=torch.float32))
            finite = torch.isfinite(projected).all(dim=1).tolist()
            active = []
            for index, valid in enumerate(finite):
                if valid:
                    active.append(index)
                else:
                    results[index] = {**bases[index], "reason": "nonfinite_learned_projection"}
            if not active:
                return results
            hidden = self.model.start(projected[active])
            finite = torch.isfinite(hidden).all(dim=2).all(dim=0).tolist()
            keep = []
            for slot, index in enumerate(active):
                if finite[slot]:
                    keep.append(slot)
                else:
                    results[index] = {**bases[index], "reason": "nonfinite_decoder_condition"}
            if len(keep) != len(active):
                active = [active[slot] for slot in keep]
                hidden = hidden[:, keep, :]
            for _ in range(63):
                if not active:
                    break
                keep, allowed_rows = [], []
                for slot, index in enumerate(active):
                    key = tuple(prefixes[index])
                    if key not in allowed_cache:
                        allowed_cache[key] = codec_module.allowed_token_ids(self._codec, prefixes[index])
                    allowed = allowed_cache[key]
                    if allowed:
                        keep.append(slot)
                        allowed_rows.append(allowed)
                    else:
                        results[index] = {**bases[index], "reason": "no_allowed_grammar_token",
                                          "generated_token_ids": prefixes[index]}
                if len(keep) != len(active):
                    active = [active[slot] for slot in keep]
                    hidden = hidden[:, keep, :]
                if not active:
                    break
                tokens = torch.tensor([[prefixes[index][-1]] for index in active], dtype=torch.long)
                logits, hidden = self.model.next_logits(tokens, hidden)
                # Rows with the same grammar choices can also share one
                # finite-score check and stable sort. Masking still ignores
                # all disallowed logits, exactly as the original decoder.
                groups = {}
                for slot, allowed in enumerate(allowed_rows):
                    groups.setdefault(tuple(allowed), []).append(slot)
                decision_finite = [False] * len(active)
                decision_tokens = [None] * len(active)
                decision_margins = [None] * len(active)
                for allowed, slots in groups.items():
                    scores = logits[slots, -1, :][:, list(allowed)]
                    finite = torch.isfinite(scores).all(dim=1).tolist()
                    if len(allowed) == 1:
                        chosen, group_margins = [allowed[0]] * len(slots), [None] * len(slots)
                    else:
                        ranking = torch.argsort(scores, dim=1, descending=True, stable=True)
                        chosen = [allowed[rank] for rank in ranking[:, 0].tolist()]
                        top = scores.gather(1, ranking[:, :2])
                        group_margins = (top[:, 0] - top[:, 1]).tolist()
                    for slot, valid, token, margin in zip(slots, finite, chosen, group_margins):
                        decision_finite[slot], decision_tokens[slot], decision_margins[slot] = valid, token, margin
                keep = []
                for slot, index in enumerate(active):
                    base, prefix = bases[index], prefixes[index]
                    if not decision_finite[slot]:
                        results[index] = {**base, "reason": "nonfinite_decoder_scores"}
                        continue
                    margin = decision_margins[slot]
                    if margin is not None:
                        margins[index] = margin if margins[index] is None else min(margins[index], margin)
                        if margin <= 1e-7:
                            results[index] = {**base, "reason": "ambiguous_decoder_scores", "generated_token_ids": prefix}
                            continue
                    prefix.append(decision_tokens[slot])
                    if prefix[-1] != codec_module.TARGET_EOS:
                        keep.append(slot)
                        continue
                    results[index] = self._decoded(base, prefix, margins[index], completed_cache)
                if len(keep) != len(active):
                    active = [active[slot] for slot in keep]
                    hidden = hidden[:, keep, :]
            for index in active:
                results[index] = {**bases[index], "reason": "generation_length_limit",
                                  "generated_token_ids": prefixes[index]}
        return results

    def infer(self, rows, *, projection_id=PROJECTION_ID):
        return self._infer(rows, projection_id=projection_id, include_projection=False)

    def infer_with_projection(self, rows, *, projection_id=PROJECTION_ID):
        """Return ``(report, vectors)`` from one guarded projection/decode.

        Every returned vector is the same projected tensor used to condition
        its formula. Full source and tensor-value checks enclose both stages,
        including writes through ``tensor.data`` that bypass version counters.
        Like :meth:`project`, nonfinite projected vectors fail closed.
        """
        return self._infer(rows, projection_id=projection_id, include_projection=True)

    def _infer(self, rows, *, projection_id, include_projection):
        self._check()
        _require(type(projection_id) is str and 0 < len(projection_id) <= 256, "bounded projection id required")
        _require(type(rows) in (list, tuple) and 1 <= len(rows) <= 128, "one to 128 inference rows required")
        validated = _rows(rows, self._checkpoint["binding"]["dimension"], training=False)
        # Small GRU batches have more CPU overhead than singleton steps on
        # the released head. Retain the original scalar path for them.
        execution = "scalar" if len(validated) <= 16 else "batched"
        projected, vectors = None, None
        if include_projection:
            torch = self.torch
            self.model.eval()
            with torch.inference_mode():
                # Singleton projection retains exact scalar decisions for
                # small requests, including margins near abstention limits.
                if execution == "scalar":
                    projected = torch.cat([self.model.project(torch.tensor([row["latent"]], dtype=torch.float32))
                                           for row in validated], dim=0)
                else:
                    projected = self.model.project(torch.tensor([row["latent"] for row in validated], dtype=torch.float32))
                _require(bool(torch.isfinite(projected).all()), "nonfinite learned projection")
                vectors = projected.tolist()
        completed_cache = {}
        if execution == "scalar":
            allowed_cache = {}
            results = [self._decode_scalar(row, projection_id, allowed_cache,
                       projected=projected[index:index + 1] if projected is not None else None,
                       completed_cache=completed_cache)
                       for index, row in enumerate(validated)]
        else:
            results = self._decode_batch(validated, projection_id, projected=projected, completed_cache=completed_cache)
        evidence = self._check()
        count = sum(row["status"] == "decoded" for row in results)
        result = {"schema": "modal-latent-formula-inference/v1", "binding": copy.deepcopy(self._checkpoint["binding"]),
            "checkpoint_sha256": self.checkpoint_sha256, "rows": results, "decoded_count": count,
            "inference_implementation": {**evidence, "execution": execution},
            "status": "decoded" if count == len(rows) else "partial" if count else "abstained",
            "decoded_formulas_generated": count > 0, "training_executed": False,
            "source_text_is_neural_input": False, "latent_input_conditioned": True,
            "teacher_forcing": False, "target_access": False, "learned_formula_generation": True,
            "independent_text_to_logic": False, "sample_memory_used": False, **FALSE}
        return (result, vectors) if include_projection else result


def infer(checkpoint, rows, *, expected_binding=None, projection_id=PROJECTION_ID):
    return BatchedLatentFormulaDecoder(checkpoint, expected_binding=expected_binding).infer(
        rows, projection_id=projection_id)


__all__ = ["BatchedLatentFormulaDecoder", "infer", "inference_implementation"]
