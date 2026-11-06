"""Opt-in full-span conditions margin on caller-supplied logits.

No model, encoder, checkpoint, optimizer or forward is opened here. The caller
owns supervision, fit admission, unchanged CE/teacher terms and model freezing.
This separate profile preserves the whole-file identity of the retained
``structured_span_objective`` checkpoint dependency. It admits no legal gold.
"""
from __future__ import annotations

import math
import struct

SCHEMA = "conditions-fullspan-margin/v1"
MAX_BATCH = 32
MAX_TOKENS = 256
MARGIN = 1.0


def _require(value, message):
    if not value:
        raise ValueError(message)


def _weight(value):
    _require(type(value) in (float, int) and value in (0.0, 0.25),
             "weight must be the fixed zero or 0.25 matched arm")
    return float(value)


def _targets(targets):
    _require(type(targets) in (list, tuple) and 1 <= len(targets) <= MAX_BATCH,
             "one to 32 supplied target rows required")
    rows = []
    for target in targets:
        _require(type(target) is dict and set(target) == {"token_count", "present", "span"},
                 "closed conditions target schema required")
        count, present, span = (target[key] for key in ("token_count", "present", "span"))
        _require(type(count) is int and 1 <= count <= MAX_TOKENS,
                 "one to 256 actual tokens required")
        _require(type(present) is bool, "boolean gold conditions presence required")
        _require(type(span) in (list, tuple) and len(span) == 2
                 and all(type(value) is int for value in span), "two integer target coordinates required")
        left, right = span
        _require((0 <= left <= right < count) if present else ((left, right) == (-100, -100)),
                 "present target must be valid; absent target must be (-100, -100)")
        rows.append((count, present, (left, right)))
    return rows


def _f32(value):
    _require(type(value) in (float, int), "finite float32 value required")
    try:
        _require(math.isfinite(value), "finite float32 value required")
        result = struct.unpack("!f", struct.pack("!f", value))[0]
    except (OverflowError, struct.error) as error:
        raise ValueError("float32 arithmetic overflow") from error
    _require(math.isfinite(result), "float32 arithmetic overflow")
    return result


def _result(weight, rows, loss, weighted, diagnostics):
    return {"schema": SCHEMA, "margin": MARGIN, "weight": weight,
            "normalization": "full_batch_mean", "batch_size": len(rows),
            "present_count": sum(present for _, present, _ in rows),
            "margin_computed": weight != 0, "loss": loss, "weighted_loss": weighted,
            "row_diagnostics": diagnostics, "semantic_gold": False, "qualified": False,
            "proof_authority": False, "model_execution_performed": False,
            "training_executed": False}


def conditions_fullspan_margin_reference(start_logits, end_logits, targets, *, weight=0.25):
    """Scalar reference for synthetic/saved supplied scores, without Torch.

    Pair addition and hinge association round to float32 at each operation.
    The final reference mean uses binary64 fsum then rounds to float32; it is a
    tolerance oracle for the backend reduction, not a bitwise reduction proof.
    Padded values must be finite but are never candidates. No targets are admitted.
    """
    weight, rows = _weight(weight), _targets(targets)
    _require(type(start_logits) in (list, tuple) and type(end_logits) in (list, tuple)
             and len(start_logits) == len(end_logits) == len(rows), "matched score batch required")
    _require(type(start_logits[0]) in (list, tuple), "score vectors required")
    width = len(start_logits[0])
    _require(1 <= width <= MAX_TOKENS and all(count <= width for count, _, _ in rows),
             "actual token count exceeds bounded score width")
    vectors = []
    for batch in (start_logits, end_logits):
        converted = []
        for vector in batch:
            _require(type(vector) in (list, tuple) and len(vector) == width, "matched padded score width required")
            converted.append([_f32(value) for value in vector])
        vectors.append(converted)
    if weight == 0:
        return _result(weight, rows, 0.0, 0.0, [])
    terms, diagnostics = [], []
    for index, (count, present, gold) in enumerate(rows):
        best, chosen, ties = None, None, 0
        if present:
            for left in range(count):
                for right in range(left, count):
                    if (left, right) == gold:
                        continue
                    score = _f32(vectors[0][index][left] + vectors[1][index][right])
                    if best is None or score > best:
                        best, chosen, ties = score, (left, right), 1
                    elif score == best:
                        ties += 1
        gold_score, term = None, 0.0
        if chosen is not None:
            gold_score = _f32(vectors[0][index][gold[0]] + vectors[1][index][gold[1]])
            term = max(0.0, _f32(_f32(MARGIN + best) - gold_score))
        terms.append(term)
        diagnostics.append({"token_count": count, "present": present, "gold_span": list(gold),
            "wrong_span": list(chosen) if chosen is not None else None,
            "wrong_score": best, "gold_score": gold_score, "max_tie_count": ties,
            "wrong_domain_count": count * (count + 1) // 2 - 1 if present else 0, "hinge": term})
    loss = _f32(math.fsum(terms) / len(rows))
    return _result(weight, rows, loss, _f32(weight * loss), diagnostics)


def conditions_fullspan_margin_from_logits(torch, start_logits, end_logits, targets, *, weight=0.25):
    """Differentiate only the selected wrong/gold scores on supplied BxT logits.

    Inputs are CPU float32 conditions heads, with explicit actual lengths and
    gold-presence labels. Selection is detached over ALL unpadded upper-triangle
    pairs except exact gold, with earliest row-major coordinate on exact ties.
    No overlap filter or inference top-k restricts negatives. Recomputed tensor
    scores use ``relu((1 + wrong) - gold)``. Absent/empty-domain rows contribute
    graph-connected zero and remain in the FULL batch denominator. The zero arm
    skips candidate arithmetic. This term never replaces or renormalizes CE/KL.
    """
    weight, rows = _weight(weight), _targets(targets)
    for value in (start_logits, end_logits):
        _require(torch.is_tensor(value) and value.ndim == 2 and value.dtype == torch.float32
                 and value.device.type == "cpu", "CPU float32 BxT conditions logits required")
    _require(start_logits.shape == end_logits.shape and start_logits.shape[0] == len(rows)
             and 1 <= start_logits.shape[1] <= MAX_TOKENS
             and all(count <= start_logits.shape[1] for count, _, _ in rows), "conditions score geometry differs")
    _require(bool(torch.isfinite(start_logits).all()) and bool(torch.isfinite(end_logits).all()),
             "nonfinite supplied conditions logits")
    terms, diagnostics = [], []
    for index, (count, present, gold) in enumerate(rows):
        start, end = start_logits[index, :count], end_logits[index, :count]
        # Multiply before reducing: finite extreme inputs cannot overflow a zero.
        zero = (start * 0).sum() + (end * 0).sum()
        if weight == 0:
            terms.append(zero)
            continue
        chosen, best, gold_score, ties = None, None, None, 0
        term = zero
        domain_count = count * (count + 1) // 2 - 1 if present else 0
        if domain_count:
            pairs = start.detach()[:, None] + end.detach()[None, :]
            positions = torch.arange(count)
            allowed = positions[:, None] <= positions[None, :]
            allowed[gold[0], gold[1]] = False
            _require(bool(torch.isfinite(pairs[allowed]).all()), "float32 pair-score overflow")
            maximum = pairs[allowed].max()
            tied = (pairs == maximum) & allowed
            flat_positions = torch.arange(count * count).reshape(count, count)
            chosen_flat = int(flat_positions[tied].min())
            chosen = (chosen_flat // count, chosen_flat % count)
            ties = int(tied.sum())
            wrong = start[chosen[0]] + end[chosen[1]]
            gold_tensor = start[gold[0]] + end[gold[1]]
            shifted_wrong = MARGIN + wrong
            raw_hinge = shifted_wrong - gold_tensor
            _require(all(bool(torch.isfinite(value)) for value in (gold_tensor, shifted_wrong, raw_hinge)),
                     "float32 hinge overflow")
            term = torch.relu(raw_hinge)
            best, gold_score = float(wrong.detach()), float(gold_tensor.detach())
        terms.append(term)
        diagnostics.append({"token_count": count, "present": present, "gold_span": list(gold),
            "wrong_span": list(chosen) if chosen is not None else None,
            "wrong_score": best, "gold_score": gold_score, "max_tie_count": ties,
            "wrong_domain_count": domain_count, "hinge": float(term.detach())})
    loss = torch.stack(terms).mean()
    weighted = loss * weight
    _require(bool(torch.isfinite(loss)) and bool(torch.isfinite(weighted)), "nonfinite margin reduction")
    return _result(weight, rows, loss, weighted, diagnostics)


__all__ = ["conditions_fullspan_margin_reference", "conditions_fullspan_margin_from_logits", "SCHEMA"]
