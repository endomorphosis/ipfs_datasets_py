"""Training-only compositional action features; no generation or selection policy.

The temperature below scales a supervised contrastive loss, not sampling.
Generation remains the inherited deterministic, full-vocabulary path. Unique
literal clause sources in the current decoder batch supply features; only
authenticated training references supply actor/action labels. No new rows are
drawn. This objective is not a formalization, proof, or qualification gate.
"""
import hashlib
import math
import time

from . import decoder_distillation_experiment as core
from . import source_value_decoder_experiment as values

SCHEMA = "training-action-contrastive/v1"
MODEL_SCHEMA = "action-factorized-clause-source-decoder-development/v1"
TEMPERATURE = 0.1
NORMALIZATION_EPSILON = 1e-12
FEATURE_DIMENSION = 64


def _deadline(deadline):
    core._require(type(deadline) in (int, float) and math.isfinite(deadline), "finite contrastive deadline required")
    if time.monotonic() >= deadline:
        raise TimeoutError("action contrastive deadline")


def prepare_training_inventory(rows, references, *, contexts, codec, validate_rule):
    """Authenticate training targets and their literal source clause positions.

    Call once after the trainer's disjoint split checks. This function accepts
    only the training split, and returns no source vectors or reference text.
    Repeated clause sources must have identical actor/action labels.
    """
    from . import clause_source_context
    context_receipt = clause_source_context.validate_contexts(rows, contexts)
    labels = values.reference_source_values(rows, references, codec, validate_rule=validate_rule)
    inventory, source_labels = {}, {}
    for row in rows:
        segments = contexts[row["id"]]["segments"]
        records = labels[row["id"]]
        core._require(len(segments) == sum(record[0] >= 0 for record in records),
            "training clause/reference count mismatch")
        clauses = []
        for slot, segment in enumerate(segments):
            actor, action = records[slot][:2]
            sha = segment["source_sha256"]
            core._require(sha not in source_labels or source_labels[sha] == (actor, action),
                "one training clause source has conflicting actor/action labels")
            source_labels[sha] = actor, action
            clauses.append(dict(source_sha256=sha, actor_token_id=actor, action_token_id=action))
        inventory[row["id"]] = dict(source_sha256=hashlib.sha256(row["source_text"].encode()).hexdigest(),
            input_sha256=core.digest(row["input"]), clauses=clauses)
    result = dict(schema=SCHEMA, training_rows_sha256=core.digest(rows),
        training_references_sha256=core.digest(references), training_contexts_sha256=core.digest(contexts),
        codec_sha256=core.digest(codec), dimension=context_receipt["dimension"], rows=inventory,
        unique_training_clauses=len(source_labels), training_clause_occurrences=sum(len(r["clauses"]) for r in inventory.values()),
        target_access="authenticated_training_reference_labels_only", reference_documents_passed_to_model=False,
        validation_rows_used=False, admitted=False, qualified=False)
    result["inventory_sha256"] = core.digest(result)
    return result


def _batch_inventory(rows, inventory):
    core._require(type(inventory) is dict and inventory.get("schema") == SCHEMA
        and inventory.get("inventory_sha256") == core.digest({k:v for k,v in inventory.items() if k != "inventory_sha256"}),
        "authenticated training action inventory required")
    core._require(type(rows) is list and 1 <= len(rows) <= 64
        and all(type(row) is dict and type(row.get("id")) is str for row in rows)
        and len({row["id"] for row in rows}) == len(rows), "bounded distinct training batch identities required")
    unique, positions, seen, counts = [], [], {}, []
    for row_index, row in enumerate(rows):
        record = inventory["rows"].get(row["id"])
        core._require(record is not None and record["source_sha256"] == hashlib.sha256(row["source_text"].encode()).hexdigest()
            and record["input_sha256"] == core.digest(row["input"]), "batch row differs from authenticated training source")
        counts.append(len(record["clauses"]))
        for slot, clause in enumerate(record["clauses"]):
            sha = clause["source_sha256"]
            site = dict(row_id=row["id"], slot=slot)
            if sha in seen:
                unique[seen[sha]]["occurrences"].append(site)
            else:
                seen[sha] = len(unique)
                unique.append(dict(clause, first_site=site, occurrences=[site]))
                positions.append((row_index, slot))
    return unique, positions, counts


def source_action_contrastive_loss(torch, model, projected, rows, *, source_context, inventory, deadline):
    """Loss for current source clauses; no references are passed to the model.

    Same-action/different-actor clauses are positives; other actions are
    negatives. Same-action/same-actor pairs are excluded. An anchor needs both
    a positive and a negative. Repeated source hashes contribute once, in
    first-observed batch order. No eligible anchors means no feature forward
    or attached graph. ``features`` is a private branch retained only so the
    caller can report its weighted gradient after its single normal backward.
    """
    _deadline(deadline)
    core._require(callable(getattr(model, "source_action_features", None))
        and model.describe().get("schema") in (MODEL_SCHEMA, "ordered-clause-recurrent-source-decoder-development/v1"), "explicit action-factorized model required")
    unique, positions, counts = _batch_inventory(rows, inventory)
    core._require(type(source_context) is dict and set(source_context) == {"vectors", "mask"},
        "explicit source-only context packet required")
    mask = source_context["mask"]
    core._require(isinstance(mask, torch.Tensor) and mask.dtype == torch.bool and mask.device.type == "cpu"
        and tuple(mask.shape) == (len(rows), values.MAX_RULES)
        and mask.tolist() == [[slot < count for slot in range(values.MAX_RULES)] for count in counts],
        "context mask differs from authenticated source clause inventory")
    pairs = []
    for i, anchor in enumerate(unique):
        positives = [j for j, other in enumerate(unique) if j != i
            and other["action_token_id"] == anchor["action_token_id"]
            and other["actor_token_id"] != anchor["actor_token_id"]]
        negatives = [j for j, other in enumerate(unique) if j != i
            and other["action_token_id"] != anchor["action_token_id"]]
        pairs.append(dict(anchor=i, positive_indices=positives, negative_indices=negatives,
            eligible=bool(positives and negatives)))
    active = [pair for pair in pairs if pair["eligible"]]
    receipt = dict(schema=SCHEMA, inventory_sha256=inventory["inventory_sha256"],
        row_ids=[row["id"] for row in rows], unique_clauses=unique, pair_sets=pairs,
        clause_occurrences=sum(counts), unique_clause_count=len(unique),
        duplicate_clause_occurrences=sum(counts)-len(unique), active_anchor_count=len(active),
        directed_positive_pairs=sum(len(pair["positive_indices"]) for pair in active),
        directed_negative_pairs=sum(len(pair["negative_indices"]) for pair in active),
        temperature=TEMPERATURE, temperature_scope="contrastive_loss_only_not_generation",
        normalization_epsilon=NORMALIZATION_EPSILON, feature_dimension=FEATURE_DIMENSION,
        aggregation="mean_positive_negative_log_probability_then_mean_active_anchor",
        normalized_features=None, unnormalized_feature_norms=None, loss=None,
        feature_forward_executed=False, reference_documents_passed_to_model=False,
        validation_rows_used=False, used_for_selection=False, admitted=False, qualified=False)
    if not active:
        _deadline(deadline)
        return dict(loss=None, features=None, receipt=receipt)
    features = model.source_action_features(projected, source_context=source_context)
    core._require(isinstance(features, torch.Tensor) and features.dtype == torch.float32
        and features.device.type == "cpu" and tuple(features.shape) == (len(rows), values.MAX_RULES, FEATURE_DIMENSION)
        and core._finite(torch, features) and features.requires_grad,
        "finite differentiable CPU action features required")
    selected = features[[position[0] for position in positions], [position[1] for position in positions]]
    selected.retain_grad()
    normalized = torch.nn.functional.normalize(selected, dim=-1, eps=NORMALIZATION_EPSILON)
    scores = normalized @ normalized.transpose(0, 1) / TEMPERATURE
    losses = []
    for pair in active:
        positive, negative = pair["positive_indices"], pair["negative_indices"]
        scores_i = scores[pair["anchor"]]
        value = torch.logsumexp(scores_i[positive+negative], dim=0)-scores_i[positive].mean()
        losses.append(value)
        pair["loss"] = float(value.detach())
    loss = torch.stack(losses).mean()
    core._require(core._finite(torch, loss), "nonfinite action contrastive loss")
    receipt.update(normalized_features=normalized.detach().tolist(),
        unnormalized_feature_norms=selected.detach().norm(dim=-1).tolist(), loss=float(loss.detach()),
        feature_forward_executed=True)
    _deadline(deadline)
    return dict(loss=loss, features=selected, receipt=receipt)


def record_feature_gradient(torch, result, *, weight):
    """Record the contrastive-only feature branch after weighted backward.

    Parameter gradients also contain the unchanged decoder objectives; this
    deliberately reports a feature gradient, not an isolated parameter norm.
    """
    core._require(type(weight) in (int, float) and math.isfinite(weight) and 0 < weight <= 1,
        "positive bounded contrastive gradient weight required")
    receipt = result["receipt"]
    receipt["weight"] = weight
    receipt["weighted_feature_gradient_norm_scope"] = "unique_raw_action_features_contrastive_branch_only_before_parameter_clipping"
    if result["features"] is None:
        receipt["weighted_feature_gradient_norm"] = None
        return
    gradient = result["features"].grad
    core._require(gradient is not None and core._finite(torch, gradient), "finite weighted feature gradient required")
    receipt["weighted_feature_gradient_norm"] = float(gradient.detach().norm())
