"""Mask-aware positive-mass contrastive arithmetic, separate from admission.

Inputs are CPU float32/float64 representations; this loss never normalizes
them. Projection owners supply any unit-vector contract. Finite-domain checks
include every pair logit, even unknown pairs. Unknown pairs contribute to
neither direction of the objective and have exactly zero pair-logit gradient.
Finite forward values do not guarantee finite backward values for arbitrary
inputs/temperatures; a future fitting caller must check parameter gradients.
Caller masks express structural relations, not authenticated semantic labels.
No fit, optimizer, checkpoint or legacy implementation profile is modified.
"""
from __future__ import annotations

import hashlib
import json
import math

SCHEMA = "alignment-masked-contrastive-relations/v1"
MAX_ROWS = 128
MAX_DIMENSION = 8192
MASKS = ("weak_decoder_fit", "strong_semantic_fit", "contrastive_supervision", "proof_supervision", "fidelity_evaluation")
FALSE = dict.fromkeys(("accepted", "qualified", "source_fidelity_established", "proof_authority",
                      "semantic_label_admission", "semantic_equivalence_verified", "relation_identity_authenticated",
                      "training_executed", "model_executed", "optimizer_executed", "integration_into_legacy_profile"), False)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _torch():
    try:
        import torch
    except ImportError as error:
        raise ImportError("masked contrastive arithmetic requires optional PyTorch") from error
    return torch


def _tensor(value, torch):
    return (isinstance(value, torch.Tensor) and value.device.type == "cpu"
            and value.layout == torch.strided and not value.is_nested)


def _relations(positive_mask, permitted_negative_mask, torch):
    _require(_tensor(positive_mask, torch) and _tensor(permitted_negative_mask, torch)
             and positive_mask.dtype == permitted_negative_mask.dtype == torch.bool
             and positive_mask.ndim == permitted_negative_mask.ndim == 2
             and positive_mask.shape == permitted_negative_mask.shape
             and 1 <= positive_mask.shape[0] <= MAX_ROWS and 1 <= positive_mask.shape[1] <= MAX_ROWS
             and positive_mask.requires_grad is False and permitted_negative_mask.requires_grad is False,
             "matching bounded CPU bool NxM relation masks required")
    _require(not bool((positive_mask & permitted_negative_mask).any()), "positive and permitted-negative masks overlap")
    _require(bool(positive_mask.any(dim=1).all()) and bool(positive_mask.any(dim=0).all()),
             "every row and column requires at least one positive")


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def describe_masked_contrastive_relations(positive_mask, permitted_negative_mask):
    """Describe caller masks and directional coverage without semantic authority.

    An anchor with no permitted negatives contributes zero in that direction;
    its representation can still receive gradients through the other direction.
    This diagnostic does not validate a fit policy or admit any supervision.
    """
    torch = _torch()
    _relations(positive_mask, permitted_negative_mask, torch)
    positive = positive_mask.tolist()
    negative = permitted_negative_mask.tolist()
    rows, columns = positive_mask.shape
    unknown = ~(positive_mask | permitted_negative_mask)
    row_counts = [{"index": index, "positive_count": int(positive_mask[index].sum()),
                   "permitted_negative_count": int(permitted_negative_mask[index].sum()),
                   "unknown_count": int(unknown[index].sum())} for index in range(rows)]
    column_counts = [{"index": index, "positive_count": int(positive_mask[:, index].sum()),
                      "permitted_negative_count": int(permitted_negative_mask[:, index].sum()),
                      "unknown_count": int(unknown[:, index].sum())} for index in range(columns)]
    result = {"schema": SCHEMA, "relation_scope": "caller_declared_pair_masks_not_semantic_admission",
              "positive_mask_sha256": _digest(positive), "permitted_negative_mask_sha256": _digest(negative),
              "mask_digest_recipe": "sha256_sorted_compact_utf8_json_nested_bool_lists_no_newline",
              "row_count": rows, "column_count": columns, "pair_count": rows * columns,
              "positive_pair_count": int(positive_mask.sum()),
              "permitted_negative_pair_count": int(permitted_negative_mask.sum()), "unknown_pair_count": int(unknown.sum()),
              "row_counts": row_counts, "column_counts": column_counts,
              "rows_without_permitted_negatives": [row["index"] for row in row_counts if not row["permitted_negative_count"]],
              "columns_without_permitted_negatives": [column["index"] for column in column_counts if not column["permitted_negative_count"]],
              "both_direction_means_include_all_anchors": True,
              "global_no_separation_signal": not bool(permitted_negative_mask.any()),
              "representation_normalization_performed": False, "verification_status": "pending", "admission_status": "pending",
              "masks": dict.fromkeys(MASKS, 0), "model_calls": 0, "encoder_calls": 0, "prover_calls": 0,
              "optimizer_updates": 0, **FALSE}
    result["content_sha256"] = _digest(result)
    return result


def masked_multi_positive_contrastive_loss(source_embeddings, formal_embeddings, *, positive_mask,
                                           permitted_negative_mask, temperature=0.07, negative_weights=None):
    """Return symmetric mean log positive mass over explicitly permitted pairs.

    Source NxD and formal MxD widths match; masks are bool NxM. Every row and
    column has a positive. Negative weights are fixed, matching CPU dtype/shape,
    finite and >=1 at permitted negatives. Positive/unknown weights are ignored,
    including NaN/Inf; weights requiring gradients are rejected. Unknown logits
    are excluded from both numerators and denominators. With no negatives, the
    result and all representation gradients are differentiable exact zero.
    """
    torch = _torch()
    _require(type(temperature) in (int, float), "finite positive temperature required")
    try:
        valid_temperature = math.isfinite(temperature) and temperature > 0
    except OverflowError as error:
        raise ValueError("finite representable positive temperature required") from error
    _require(valid_temperature, "finite positive temperature required")
    _require(_tensor(source_embeddings, torch) and _tensor(formal_embeddings, torch)
             and source_embeddings.dtype == formal_embeddings.dtype
             and source_embeddings.dtype in (torch.float32, torch.float64)
             and source_embeddings.ndim == formal_embeddings.ndim == 2
             and 1 <= source_embeddings.shape[0] <= MAX_ROWS and 1 <= formal_embeddings.shape[0] <= MAX_ROWS
             and source_embeddings.shape[1] == formal_embeddings.shape[1]
             and 1 <= source_embeddings.shape[1] <= MAX_DIMENSION
             and bool(torch.isfinite(source_embeddings).all()) and bool(torch.isfinite(formal_embeddings).all()),
             "matching-width bounded finite CPU float32/float64 representations required")
    _relations(positive_mask, permitted_negative_mask, torch)
    _require(positive_mask.shape == (source_embeddings.shape[0], formal_embeddings.shape[0]),
             "relation mask shape differs from source/formal pair grid")
    safe_weights = None
    if negative_weights is not None:
        _require(_tensor(negative_weights, torch) and negative_weights.shape == positive_mask.shape
                 and negative_weights.dtype == source_embeddings.dtype and negative_weights.requires_grad is False,
                 "fixed matching CPU floating NxM negative weights required")
        permitted = negative_weights[permitted_negative_mask]
        _require(bool(torch.isfinite(permitted).all()) and bool((permitted >= 1).all()),
                 "permitted-negative weights must be finite and at least one")
        safe_weights = torch.where(permitted_negative_mask, negative_weights, torch.ones_like(negative_weights))
    with torch.autocast(device_type="cpu", enabled=False):
        logits = source_embeddings @ formal_embeddings.T / temperature
        _require(bool(torch.isfinite(logits).all()), "all computed pair logits must be finite, including unknown pairs")
        if not bool(permitted_negative_mask.any()):
            return logits.mul(0).sum()
        weighted = logits if safe_weights is None else logits + safe_weights.log()
        allowed = positive_mask | permitted_negative_mask
        denominator = weighted.masked_fill(~allowed, -torch.inf)
        numerator = logits.masked_fill(~positive_mask, -torch.inf)
        rows = torch.logsumexp(denominator, dim=1) - torch.logsumexp(numerator, dim=1)
        columns = torch.logsumexp(denominator, dim=0) - torch.logsumexp(numerator, dim=0)
        loss = (rows.mean() + columns.mean()) / 2
        _require(bool(torch.isfinite(loss)), "masked contrastive loss must remain finite")
        return loss


__all__ = ["masked_multi_positive_contrastive_loss", "describe_masked_contrastive_relations"]
