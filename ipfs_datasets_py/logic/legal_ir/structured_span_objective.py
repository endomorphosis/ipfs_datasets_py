"""Opt-in order/overlap objective on one already computed span-head output.

This module opens no model and runs no forward. The caller owns the numerical
backend, labelled fit admission, checkpoint lineage and optimizer. Reference
presence gates the structured term; optional absent fields cannot lower the loss
by changing model presence predictions. These are geometric checks on supplied
labels, not independent legal review or proof authority.
"""
from __future__ import annotations

import math

SCHEMA = "source-span-order-overlap-probability/v1"
CE_ID = "equal_facet_modality_presence_mean_start_end/v1"
FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
OPTIONAL_FIELDS = FIELDS[2:]
MAX_BATCH = 32
MAX_TOKENS = 256
MAX_FLOAT32 = 3.4028234e38
ROUNDING_TOLERANCE = 1e-9


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _weight(value):
    _require(type(value) in (float, int) and math.isfinite(value) and 0 <= value <= 1,
             "structure_weight must be a finite number in [0, 1]")
    return float(value)


def _presence(value):
    _require(type(value) in (list, tuple) and len(value) == len(FIELDS)
             and all(type(item) is bool for item in value), "six boolean reference presence labels required")
    _require(value[0] and value[1], "reference actor and action must be present")
    return [index for index, present in enumerate(value) if present]


def reference_geometry(records):
    """Validate the retained owner's internal record geometry without Torch.

    This function checks token lengths, unique nonoverlapping reference intervals
    and explicit absent labels. It cannot replay full source bytes because those
    bytes are outside the retained owner's internal record schema.
    """
    _require(type(records) in (list, tuple) and 1 <= len(records) <= MAX_BATCH,
             "one to 32 internal reference records required")
    rows = []
    for record in records:
        _require(type(record) is dict and set(record) == {"tokens", "labels", "latent"},
                 "closed internal reference record schema required")
        tokens = record["tokens"]
        _require(type(tokens) is list and 1 <= len(tokens) <= MAX_TOKENS,
                 "one to 256 source tokens required")
        previous_end = -1
        for token in tokens:
            _require(type(token) is dict and set(token) == {"text", "start", "end", "byte_ids"},
                     "closed retained token schema required")
            text, start, end, byte_ids = (token[key] for key in ("text", "start", "end", "byte_ids"))
            _require(type(text) is str and text and type(start) is int and type(end) is int
                     and 0 <= start < end and start >= previous_end and end - start == len(text),
                     "reference token character geometry differs")
            _require(type(byte_ids) is list and 1 <= len(byte_ids) <= 2048
                     and all(type(value) is int and 1 <= value <= 256 for value in byte_ids)
                     and byte_ids == [value + 1 for value in text.casefold().encode("utf-8")],
                     "reference token byte encoding differs")
            previous_end = end
        latent = record["latent"]
        _require(type(latent) in (list, tuple) and len(latent) in (0, 384)
                 and all(type(value) in (float, int) and math.isfinite(value)
                         and abs(value) <= MAX_FLOAT32 for value in latent),
                 "finite zero-dimensional or 384-dimensional internal latent required")
        labels = record["labels"]
        _require(type(labels) is dict and set(labels) == {"modality", "presence", "spans"},
                 "closed reference label schema required")
        _require(type(labels["modality"]) is int and 0 <= labels["modality"] <= 2,
                 "reference modality index must be 0, 1 or 2")
        active = _presence(labels["presence"])
        spans = labels["spans"]
        _require(type(spans) in (list, tuple) and len(spans) == len(FIELDS),
                 "six reference intervals required")
        occupied = set()
        copied = []
        for index, interval in enumerate(spans):
            _require(type(interval) in (list, tuple) and len(interval) == 2
                     and all(type(value) is int for value in interval),
                     "reference interval must contain two integer indices")
            left, right = interval
            if index not in active:
                _require((left, right) == (-100, -100), "absent reference interval must be (-100, -100)")
                continue
            _require(0 <= left <= right < len(tokens), "present reference interval is outside token geometry")
            positions = set(range(left, right + 1))
            _require(not positions & occupied, "reference copied intervals overlap")
            occupied.update(positions)
            copied.append({"field": FIELDS[index], "token_start": left, "token_end_inclusive": right})
        rows.append({"token_count": len(tokens), "active_field_indices": active,
                     "active_fields": [FIELDS[index] for index in active],
                     "active_field_pairs": [[left, right] for at, left in enumerate(active)
                                            for right in active[at + 1:]],
                     "reference_intervals": copied})
    return {"schema": "source-span-reference-geometry/v1", "row_count": len(rows),
            "padded_token_count": max(row["token_count"] for row in rows), "rows": rows,
            "provided_label_geometry_valid": True, "full_source_bytes_replayed": False,
            "semantic_gold": False, "source_semantics_verified": False,
            "qualified": False, "proof_authority": False}


def _bounded_probability(value, label):
    _require(math.isfinite(value) and -ROUNDING_TOLERANCE <= value <= 1 + ROUNDING_TOLERANCE,
             label + " is outside probability bounds")
    return min(1.0, max(0.0, value))


def _logsumexp(values):
    largest = max(values)
    return largest + math.log(math.fsum(math.exp(value - largest) for value in values))


def probability_reference(start_logits, end_logits, presence):
    """Small float64 scalar oracle for inert tests, with no model or backend.

    All six pointer vectors have the same *actual* token length; padded logits
    must be removed by the caller. This oracle evaluates one synthetic/saved row
    and does not compute gradients or admit any labels.
    """
    active = _presence(presence)
    _require(type(start_logits) in (list, tuple) and type(end_logits) in (list, tuple)
             and len(start_logits) == len(end_logits) == len(FIELDS), "six pointer vectors required")
    _require(type(start_logits[0]) in (list, tuple) and 1 <= len(start_logits[0]) <= MAX_TOKENS,
             "one to 256 actual token scores required")
    count = len(start_logits[0])
    for vector in [*start_logits, *end_logits]:
        _require(type(vector) in (list, tuple) and len(vector) == count
                 and all(type(value) in (float, int) and math.isfinite(value)
                         and abs(value) <= MAX_FLOAT32 for value in vector), "finite matched float32-range pointers required")
    marginals, valid_mass, order = {}, {}, []
    for index in active:
        start, end = start_logits[index], end_logits[index]
        start_shift, end_shift = max(start), max(end)
        shifted_start = [value - start_shift for value in start]
        shifted_end = [value - end_shift for value in end]
        start_norm, end_norm = _logsumexp(shifted_start), _logsumexp(shifted_end)
        entries = [(left, right, (shifted_start[left] - start_norm) + (shifted_end[right] - end_norm))
                   for left in range(count) for right in range(left, count)]
        shift = max(value for _, _, value in entries)
        relative_norm = _logsumexp([value - shift for _, _, value in entries])
        log_mass = shift + relative_norm
        _require(math.isfinite(log_mass) and log_mass <= ROUNDING_TOLERANCE, "invalid reference order mass")
        order.append(max(0.0, -log_mass))
        valid_mass[FIELDS[index]] = _bounded_probability(math.exp(log_mass), "reference valid order mass")
        starts, ends = [0.0] * count, [0.0] * count
        for left, right, value in entries:
            # Normalize before adding the large shift back. This also keeps
            # equal extreme valid scores normalized when log(2) is below the
            # accumulator's spacing at the absolute log-mass magnitude.
            probability = math.exp((value - shift) - relative_norm)
            starts[left] += probability
            ends[right] += probability
        _require(abs(math.fsum(starts) - 1) <= ROUNDING_TOLERANCE
                 and abs(math.fsum(ends) - 1) <= ROUNDING_TOLERANCE,
                 "reference valid interval distribution is not normalized")
        marginals[index] = (starts, ends)
    overlaps = []
    pair_values = []
    for at, left in enumerate(active):
        for right in active[at + 1:]:
            starts_left, ends_left = marginals[left]
            starts_right, ends_right = marginals[right]
            cdf_left, cdf_right, before_left, before_right = 0.0, 0.0, [], []
            for token in range(count):
                before_left.append(cdf_left)
                before_right.append(cdf_right)
                cdf_left += ends_left[token]
                cdf_right += ends_right[token]
            value = _bounded_probability(1 - math.fsum(a * b for a, b in zip(before_left, starts_right))
                                         - math.fsum(a * b for a, b in zip(before_right, starts_left)),
                                         "reference overlap")
            overlaps.append(value)
            pair_values.append({"fields": [FIELDS[left], FIELDS[right]], "overlap_probability": value})
    order_loss = math.fsum(order) / len(order)
    overlap_loss = math.fsum(overlaps) / len(overlaps) if overlaps else 0.0
    return {"schema": SCHEMA, "order_loss": order_loss, "overlap_loss": overlap_loss,
            "unweighted_structure": (order_loss + overlap_loss) / 2,
            "valid_order_mass": valid_mass, "field_pairs": pair_values,
            "active_fields": [FIELDS[index] for index in active],
            "semantic_gold": False, "qualified": False, "proof_authority": False}


def _validate_output(torch, output, geometry):
    _require(type(output) is dict and set(output) == {"modality", "presence", "start", "end"},
             "closed retained span output schema required")
    count, width = geometry["row_count"], geometry["padded_token_count"]
    shapes = {"modality": (count, 3), "presence": (count, 4, 2),
              "start": (count, 6, width), "end": (count, 6, width)}
    for field, shape in shapes.items():
        value = output[field]
        _require(torch.is_tensor(value) and tuple(value.shape) == shape
                 and value.dtype == torch.float32 and value.device.type == "cpu",
                 "CPU float32 span output geometry differs: " + field)
        _require(bool(torch.isfinite(value).all()), "nonfinite retained span output: " + field)


def objective_from_output(torch, output, records, *, structure_weight=0.1):
    """Return differentiable losses on one caller-owned output; never forward.

    ``records`` is the unchanged span owner's internal ``_records`` format.
    CE reproduces that owner's arithmetic, including finite padding and absent
    pointer masking. Structured probabilities use actual token counts and
    float64 accumulation. Weight zero returns CE directly and skips structure.
    """
    weight = _weight(structure_weight)
    geometry = reference_geometry(records)
    _validate_output(torch, output, geometry)
    labels = [row["labels"] for row in records]
    modality = torch.nn.functional.cross_entropy(output["modality"], torch.tensor([row["modality"] for row in labels]))
    facets = []
    for index, field in enumerate(FIELDS):
        present = torch.tensor([row["presence"][index] for row in labels], dtype=torch.bool)
        start = torch.tensor([row["spans"][index][0] for row in labels], dtype=torch.long)
        end = torch.tensor([row["spans"][index][1] for row in labels], dtype=torch.long)
        pointer = (torch.nn.functional.cross_entropy(output["start"][:, index], start,
                   ignore_index=-100, reduction="none") +
                   torch.nn.functional.cross_entropy(output["end"][:, index], end,
                   ignore_index=-100, reduction="none")) * .5
        if field in OPTIONAL_FIELDS:
            presence = torch.nn.functional.cross_entropy(output["presence"][:, OPTIONAL_FIELDS.index(field)],
                       present.to(torch.long), reduction="none")
            facets.append((presence + pointer).mean())
        else:
            facets.append(pointer.mean())
    ce = (modality + sum(facets)) / 7
    _require(bool(torch.isfinite(ce)), "nonfinite copied CE objective")
    if weight == 0:
        zero = ce * 0
        return {"schema": SCHEMA, "ce": ce, "validity": zero, "overlap": zero,
                "structure": zero, "weighted_structure": zero, "total": ce,
                "structure_weight": weight, "structure_computed": False,
                "reference_geometry": geometry, "row_diagnostics": [],
                "qualified": False, "semantic_gold": False, "proof_authority": False}
    # Graph-connected zero also handles a future zero-pair row without changing
    # parameter participation; current required actor/action gives at least one.
    zero = (output["start"].to(torch.float64).sum() + output["end"].to(torch.float64).sum()) * 0
    row_order, row_overlap, diagnostics, masks = [], [], [], {}
    for row_index, row in enumerate(geometry["rows"]):
        count, active = row["token_count"], row["active_field_indices"]
        if count not in masks:
            masks[count] = torch.triu(torch.ones((count, count), dtype=torch.bool, device="cpu"))
        mask = masks[count]
        marginals, orders, masses = {}, [], {}
        for index in active:
            start = torch.nn.functional.log_softmax(output["start"][row_index, index, :count].to(torch.float64), dim=0)
            end = torch.nn.functional.log_softmax(output["end"][row_index, index, :count].to(torch.float64), dim=0)
            log_pairs = (start[:, None] + end[None, :]).masked_fill(~mask, -math.inf)
            shift = log_pairs[mask].max()
            relative_pairs = log_pairs - shift
            relative_norm = torch.logsumexp(relative_pairs.reshape(-1), dim=0)
            log_mass = shift + relative_norm
            scalar_mass = float(log_mass.detach())
            _require(math.isfinite(scalar_mass) and scalar_mass <= ROUNDING_TOLERANCE,
                     "invalid structured valid-order log mass")
            orders.append((-log_mass).clamp(min=0))
            masses[FIELDS[index]] = _bounded_probability(math.exp(scalar_mass), "structured valid order mass")
            probabilities = torch.exp(relative_pairs - relative_norm)
            starts, ends = probabilities.sum(dim=1), probabilities.sum(dim=0)
            _require(bool(torch.isfinite(probabilities).all())
                     and abs(float(starts.detach().sum()) - 1) <= ROUNDING_TOLERANCE
                     and abs(float(ends.detach().sum()) - 1) <= ROUNDING_TOLERANCE,
                     "structured valid interval distribution is not normalized")
            before_end = torch.cat((ends.new_zeros((1,)), ends.cumsum(dim=0)[:-1]))
            marginals[index] = (starts, before_end)
        overlaps, pair_values = [], []
        for left, right in row["active_field_pairs"]:
            starts_left, before_left = marginals[left]
            starts_right, before_right = marginals[right]
            value = 1 - (before_left * starts_right).sum() - (before_right * starts_left).sum()
            _bounded_probability(float(value.detach()), "structured overlap")
            value = value.clamp(min=0, max=1)
            overlaps.append(value)
            pair_values.append({"fields": [FIELDS[left], FIELDS[right]],
                                "overlap_probability": float(value.detach())})
        order = torch.stack(orders).mean() if orders else zero
        overlap = torch.stack(overlaps).mean() if overlaps else zero
        row_order.append(order)
        row_overlap.append(overlap)
        diagnostics.append({"token_count": count, "active_fields": list(row["active_fields"]),
                            "valid_order_mass": masses, "field_pairs": pair_values,
                            "validity": float(order.detach()), "overlap": float(overlap.detach())})
    validity, overlap = torch.stack(row_order).mean(), torch.stack(row_overlap).mean()
    structure = (validity + overlap) / 2
    weighted = structure * weight
    total = ce.to(torch.float64) + weighted
    _require(all(bool(torch.isfinite(value)) for value in (validity, overlap, structure, weighted, total)),
             "nonfinite structured objective")
    return {"schema": SCHEMA, "ce": ce, "validity": validity, "overlap": overlap,
            "structure": structure, "weighted_structure": weighted, "total": total,
            "structure_weight": weight, "structure_computed": True,
            "reference_geometry": geometry, "row_diagnostics": diagnostics,
            "qualified": False, "semantic_gold": False, "proof_authority": False}


__all__ = ["objective_from_output", "reference_geometry", "probability_reference", "SCHEMA", "CE_ID", "FIELDS"]
