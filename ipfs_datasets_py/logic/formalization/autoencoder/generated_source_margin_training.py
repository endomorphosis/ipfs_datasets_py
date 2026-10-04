"""Opt-in source-correct margin preservation on actual generated prefixes.

Collection sees sources only. The authenticated training inventory is consulted
after greedy generation. Margin targets are detached cached source logits, not
new labels or a second model pass. Callers must restrict auxiliary gradients to
``recurrent_auxiliary_parameters``; a direct backward on margin_loss would also
differentiate shared source heads. This module never updates parameters.
"""
import math
import struct
import time

from . import generated_field_training as fields
from . import contextual_generated_boundary_training as boundary
from . import decoder_distillation_experiment as core
from . import source_value_decoder_experiment as scalar

SCHEMA = "generated-source-margin-collection/v1"
LOSS_SCHEMA = "generated-source-margin-loss/v1"
FIELDS = scalar.SOURCE_FIELDS
POLICY = "first_source_correct_positive_margin_eroded_per_scalar_field"
FALSE = dict(fields.FALSE)
_require = core._require
_deadline = boundary._check_deadline
prepare_training_inventory = fields.prepare_training_inventory

RECURRENT_PARAMETER_NAMES = (
    "body.body.body.condition.weight", "body.body.body.condition.bias",
    "body.body.body.target_embedding.weight",
    "body.body.body.decoder.weight_ih_l0", "body.body.body.decoder.weight_hh_l0",
    "body.body.body.decoder.bias_ih_l0", "body.body.body.decoder.bias_hh_l0",
    "body.body.body.output.weight", "body.body.body.output.bias",
    "body.body.source_to_embedding.weight", "clause_to_embedding.weight",
)
SOURCE_KEYS = {"source_logits", "source_slot_available", "source_guidance_active", "source_clause_sha256"}


def recurrent_auxiliary_parameters(model):
    """Return exact ordered (name, Parameter) pairs for auxiliary gradients.

    Includes initial/paragraph/clause conditioning, token embedding, GRU and
    output. Excludes scalar, action and count heads and both projection layers.
    Excluded ordinary gradients are unchanged before the caller's global clip;
    a changed shared clipping factor can still affect their final updates.
    """
    torch = core._torch()
    core._model(model, torch)
    _require(model.describe().get("schema") == "ordered-clause-recurrent-source-decoder-development/v1",
        "ordered recurrent architecture required for auxiliary parameter whitelist")
    raw = model.body.body.body
    _require(type(raw.decoder) is torch.nn.GRU and raw.decoder.num_layers == 1
        and not raw.decoder.bidirectional and raw.decoder.batch_first
        and raw.decoder.input_size == 16 and raw.decoder.hidden_size == 32,
        "exact one-layer recurrent geometry required")
    size = raw.target_embedding.num_embeddings
    dimension = model.dimension
    shapes = ((32, dimension), (32,), (size, 16), (96, 16), (96, 32), (96,), (96,),
        (size, 32), (size,), (16, dimension), (16, 128))
    parameters = dict(model.named_parameters())
    result = []
    for name, shape in zip(RECURRENT_PARAMETER_NAMES, shapes):
        parameter = parameters.get(name)
        _require(isinstance(parameter, torch.nn.Parameter) and parameter.requires_grad
            and tuple(parameter.shape) == shape and parameter.dtype == torch.float32
            and parameter.device.type == "cpu" and core._finite(torch, parameter),
            "auxiliary recurrent parameter differs: "+name)
        result.append((name, parameter))
    _require(len({id(p) for _, p in result}) == len(result), "auxiliary parameter aliases are forbidden")
    return result


def _f32(value):
    try:
        result = struct.unpack("<f", struct.pack("<f", value))[0]
    except (OverflowError, struct.error):
        raise ValueError("finite float32 source margin required") from None
    _require(math.isfinite(result), "finite float32 source margin required")
    return result


def _margin(values, target):
    competitor = max((i for i in range(len(values)) if i != target), key=values.__getitem__)
    return _f32(values[target]-values[competitor]), competitor


class _Collector(fields._Collector):
    def start(self, projected, *, source_context=None):
        state = super().start(projected, source_context=source_context)
        self.source_mask = source_context["mask"].tolist()
        return state

    def next_logits(self, tokens, state):
        counts = [len(sites) for sites in self.field_sites]
        logits, updated = super().next_logits(tokens, state)
        for index, previous in enumerate(counts):
            for site in self.field_sites[index][previous:]:
                slot = site["slot"]
                routed = slot < state[5].shape[1]
                available = routed and bool(self.source_mask[index][slot])
                source = state[5][index, slot, FIELDS.index(site["field"])].detach() if routed else logits[index, 0].new_zeros(logits.shape[-1])
                _require(available or bool((source == 0).all()), "unavailable source slot has nonzero guidance")
                site.update(source_logits=source.tolist(), source_slot_available=available,
                    source_guidance_active=routed)
        return logits, updated


def collect_source_margin_sites(model, source_rows, *, codec, input_transform, source_contexts,
        max_target_tokens=512, batch_size=8, deadline):
    """One unchanged greedy rollout, recording cached source and combined logits."""
    started = time.monotonic()
    _deadline(deadline)
    _require(type(max_target_tokens) is int and 4 <= max_target_tokens <= 512, "fixed512 output ceiling required")
    _require(type(batch_size) is int and 1 <= batch_size <= 128, "bounded generation batch required")
    torch = core._torch()
    core._model(model, torch)
    description, state_size = fields._specification(model, codec)
    _require(description.get("guidance") is True, "actual source guidance required")
    boundary._sources(source_rows, model.dimension, True, source_contexts)
    boundary.legacy._transform(input_transform, model.dimension)
    tables = boundary.cardinality._tables(codec, len(codec["target_vocabulary"]), torch)
    snapshot = boundary._snapshot(model, torch)
    predictions, records, steps = [], [], 0
    try:
        model.eval()
        with torch.no_grad():
            for offset in range(0, len(source_rows), batch_size):
                _deadline(deadline)
                part = source_rows[offset:offset+batch_size]
                observer = _Collector(model, tables, deadline, state_size)
                generated = core._greedy(torch, observer, boundary.legacy._data(torch, part, input_transform),
                    max_target_tokens, len(codec["target_vocabulary"]), deadline,
                    **core._source_context_kwargs(torch, part, source_contexts, input_transform))
                if generated is None:
                    raise TimeoutError("generated source margin deadline exceeded")
                steps += observer.steps
                for index, (row, tokens, status) in enumerate(zip(part, generated[1], generated[2])):
                    prefix = observer.prefixes[index]
                    _require(prefix == [1]+tokens[:len(prefix)-1], "actual prefix differs from generated output")
                    segments = source_contexts[row["id"]]["segments"]
                    for site in observer.field_sites[index]:
                        site["source_clause_sha256"] = segments[site["slot"]]["source_sha256"] if site["source_slot_available"] else None
                    predictions.append(dict(id=row["id"], token_ids=tokens, generation_status=status, eos_reached=status == "eos"))
                    records.append(dict(id=row["id"], consumed_prefix=prefix, available_sites=observer.sites[index],
                        available_field_sites=observer.field_sites[index], available_site_count=len(observer.sites[index]),
                        available_field_site_count=len(observer.field_sites[index]),
                        first_invalid_prefix_position=observer.invalid[index], batch_offset=offset))
    finally:
        boundary._preserved(model, torch, snapshot)
    _deadline(deadline)
    result = dict(schema=SCHEMA, complete=True, model_tensor_sha256=snapshot[0], model_schema=description["schema"],
        codec_sha256=core.digest(codec), input_transform_sha256=core.digest(input_transform),
        source_contexts_sha256=core.digest(source_contexts), source_rows=[dict(row, input=list(row["input"])) for row in source_rows],
        predictions=predictions, rows=records, batch_size=batch_size, max_target_tokens=max_target_tokens,
        available_sites=sum(row["available_site_count"] for row in records),
        available_field_sites=sum(row["available_field_site_count"] for row in records), greedy_batch_steps=steps,
        generation_temperature=0, reference_count_access=False, reference_prefix_access=False,
        reference_documents_passed_to_model=False, inventory_access=False, site_policy_access=False,
        source_only=True, collection_no_grad=True, source_context_target_access=False,
        full_vocabulary_retained=True, syntax_mask=False, forced_closure=False,
        complete_rollout_before_site_selection=True, model_copied=False, caller_state_preserved=True,
        source_head_extra_evaluations=0, extra_model_passes=0, source_logits_from_actual_cached_state=True,
        rollout_count=1, elapsed_seconds=time.monotonic()-started, deadline_cooperative=True, **FALSE)
    result["collection_sha256"] = core.digest(result)
    return result


def _validate_collection(model, collection, codec, input_transform, contexts, torch, deadline):
    _require(type(collection) is dict and collection.get("schema") == SCHEMA and collection.get("complete") is True
        and collection.get("collection_sha256") == core.digest({k: v for k, v in collection.items() if k != "collection_sha256"}),
        "complete authenticated source-margin collection required")
    _require(collection.get("source_logits_from_actual_cached_state") is True
        and collection.get("source_head_extra_evaluations") == 0 and collection.get("extra_model_passes") == 0,
        "cached single-rollout source logits required")
    view = dict(collection, schema=fields.SCHEMA, rows=[dict(row, available_field_sites=[
        {k: v for k, v in site.items() if k not in SOURCE_KEYS} for site in row["available_field_sites"]])
        for row in collection["rows"]])
    view["collection_sha256"] = core.digest({k: v for k, v in view.items() if k != "collection_sha256"})
    tables = fields._validate_collection(model, view, codec, input_transform, contexts, torch, deadline)
    description, _ = fields._specification(model, codec)
    _require(description.get("guidance") is True, "actual source guidance required")
    size = len(codec["target_vocabulary"])
    for row in collection["rows"]:
        segments = contexts[row["id"]]["segments"]
        for site in row["available_field_sites"]:
            _deadline(deadline)
            _require(SOURCE_KEYS <= set(site), "complete cached source site required")
            values = site["source_logits"]
            routed = site["slot"] < 8
            available = routed and site["slot"] < len(segments)
            _require(type(site["source_slot_available"]) is bool and site["source_slot_available"] == available
                and type(site["source_guidance_active"]) is bool and site["source_guidance_active"] == routed
                and site["source_clause_sha256"] == (segments[site["slot"]]["source_sha256"] if available else None),
                "cached source slot provenance differs")
            _require(type(values) is list and len(values) == size and all(type(v) is float and math.isfinite(v)
                and _f32(v) == v for v in values), "full finite float32 source logits required")
            _require(available or all(v == 0. for v in values), "unavailable source has nonzero guidance")
    return tables


def _select_margin_sites(sites, clauses):
    selected, scored, unscored, seen = [], [], [], set()
    for site in sites:
        if not site["source_slot_available"] or site["slot"] >= len(clauses):
            unscored.append(dict(position=site["position"], slot=site["slot"], field=site["field"],
                reason="source_clause_and_reference_slot_unavailable"))
            continue
        clause = clauses[site["slot"]]
        target = clause["target_token_ids"][site["field"]]
        source_margin, source_other = _margin(site["source_logits"], target)
        combined_margin, combined_other = _margin(site["collection_logits"], target)
        source_correct = max(range(len(site["source_logits"])), key=site["source_logits"].__getitem__) == target
        eligible = source_correct and source_margin > 0
        eroded = eligible and combined_margin < source_margin
        record = dict(site, target_token_id=target, source_sha256=clause["source_sha256"],
            reference_rule_index=clause["reference_rule_index"], source_margin=source_margin,
            source_best_other_token_id=source_other, collection_margin=combined_margin,
            collection_best_other_token_id=combined_other, source_correct=source_correct,
            source_positive_margin_eligible=eligible, source_margin_eroded=eroded)
        # All full vectors already live in available_field_sites. Retain only
        # scalar eligibility diagnostics here, avoiding duplicate trace arrays.
        scored.append({k: v for k, v in record.items() if k not in ("source_logits", "collection_logits")})
        if eroded and site["field"] not in seen:
            selected.append(record)
            seen.add(site["field"])
    return sorted(selected, key=lambda site: site["position"]), scored, unscored


class _Replay:
    """Capture the already-computed source cache in the original replay shape."""
    def __init__(self, model):
        self.model, self.source = model, None

    def project(self, data):
        return self.model.project(data)

    def start(self, projected, *, source_context):
        state = self.model.start(projected, source_context=source_context)
        self.source = state[5].detach()
        return state

    def next_logits(self, tokens, state):
        return self.model.next_logits(tokens, state)


def _source_parity(torch, attempt, cache, physical_rows, active_rows, deadline):
    _require(cache is not None and cache.ndim == 4 and cache.shape[0] == len(physical_rows),
        "actual replay source cache required")
    indices = {row["id"]: i for i, row in enumerate(physical_rows)}
    records, mismatches, maximum = [], [], 0.
    for row in active_rows:
        _deadline(deadline)
        for site in row["selected_field_sites"]:
            observed = cache[indices[row["id"]], site["slot"], FIELDS.index(site["field"])]
            original = torch.tensor(site["source_logits"], dtype=observed.dtype)
            _require(observed.shape == original.shape and core._finite(torch, observed), "invalid replay source logits")
            difference = (observed-original).abs()
            maximum = max(maximum, float(difference.max()))
            tolerance = boundary.REPLAY_ATOL+boundary.REPLAY_RTOL*original.abs()
            records.append(dict(id=row["id"], position=site["position"], logits=observed.tolist()))
            for coordinate in (difference > tolerance).nonzero().flatten().tolist():
                mismatches.append(dict(id=row["id"], position=site["position"], vocabulary_index=coordinate,
                    collected=float(original[coordinate]), replayed=float(observed[coordinate]),
                    absolute_difference=float(difference[coordinate]), allowed_difference=float(tolerance[coordinate])))
    attempt.update(source_selected_logits=records, source_mismatches=mismatches,
        maximum_source_absolute_difference=maximum, combined_parity_passed=attempt["parity_passed"],
        source_parity_passed=not mismatches)
    attempt["parity_passed"] = attempt["parity_passed"] and not mismatches


def _margin_tensor(torch, logits, target, detached_source_margin):
    others = [i for i in range(logits.shape[0]) if i != target]
    best, offset = logits[others].max(dim=0)
    margin = logits[target]-best
    teacher = logits.new_tensor(detached_source_margin).detach()
    loss = torch.relu(teacher-margin)
    return loss, margin, others[int(offset.detach())]


def generated_margin_losses(torch, model, collection, inventory, *, codec, input_transform,
        source_contexts, deadline, boundary_site_policy="first_last"):
    """Shared accepted union replay for boundary CE and detached margin hinge.

    No backward/optimizer call occurs. The caller must obtain auxiliary grads
    only for the declared recurrent parameters, while ordinary boundary CE may
    differentiate all trainable parameters. Zero-weight diagnostic callers use
    this exact selection/replay policy and omit the auxiliary gradient update.
    """
    started = time.monotonic()
    _deadline(deadline)
    _require(type(boundary_site_policy) is str and boundary_site_policy in boundary.SITE_POLICIES,
        "explicit supported boundary site policy required")
    core._model(model, torch)
    boundary.legacy._transform(input_transform, model.dimension)
    tables = _validate_collection(model, collection, codec, input_transform, source_contexts, torch, deadline)
    sources = {row["id"]: row for row in collection["source_rows"]}
    references = fields._validate_inventory(inventory, collection["source_rows"], source_contexts, codec, model.dimension, deadline)
    boundary_selected, margin_selected, rows = {}, {}, []
    for row in collection["rows"]:
        _deadline(deadline)
        reference = references[row["id"]]
        boundary_selected[row["id"]] = [dict(site, training_count=reference["rule_count"],
            target_token_id=tables[0]["," if site["completed_rules"] < reference["rule_count"] else "]"])
            for site in boundary._select(row["available_sites"], reference["rule_count"], tables, boundary_site_policy)]
        chosen, scored, unscored = _select_margin_sites(row["available_field_sites"], reference["clauses"])
        margin_selected[row["id"]] = chosen
        positions = sorted({site["position"] for site in [*boundary_selected[row["id"]], *chosen]})
        visited = {(site["slot"], site["field"]) for site in scored}
        unvisited = [dict(slot=slot, field=field, reason="reference_scalar_site_not_visited")
            for slot in range(reference["rule_count"]) for field in FIELDS if (slot, field) not in visited]
        # The internal field key lets the unchanged union parity/retry utility
        # validate margin positions. No generated-field CE is constructed.
        rows.append(dict(row, selected_boundary_sites=boundary_selected[row["id"]], selected_field_sites=chosen,
            selected_margin_sites=chosen, scored_margin_sites=scored, unscored_margin_sites=unscored,
            unvisited_reference_sites=unvisited,
            training_count=reference["rule_count"], union_replay_positions=positions,
            replay_prefix_tokens=positions[-1]+1 if positions else 0))
    size = len(codec["target_vocabulary"])
    components = dict(boundary=fields._component("boundary", rows, boundary_selected, collection["available_sites"],
            boundary_site_policy, 2 if boundary_site_policy == "first_last" else 1, size),
        margin=fields._component("margin", rows, margin_selected, collection["available_field_sites"], POLICY, len(FIELDS), size))
    components["boundary"].update(stop_labels=0, continue_labels=0)
    components["margin"].update(full_vocabulary_cross_entropy=False, objective="relu(detached_source_margin-replayed_combined_margin)",
        source_margin_ratio=1., source_margin_cap=None, teacher_detached=True, margin_dtype="float32",
        competitor_policy="full_vocabulary_excluding_target_first_max_index", fields=list(FIELDS),
        gradient_scope="caller_must_restrict_auxiliary_to_declared_recurrent_parameters",
        recurrent_parameter_names=list(RECURRENT_PARAMETER_NAMES), labels_by_field={field: 0 for field in FIELDS},
        scored_sites=sum(len(row["scored_margin_sites"]) for row in rows),
        unscored_sites=sum(len(row["unscored_margin_sites"]) for row in rows),
        unvisited_reference_sites=sum(len(row["unvisited_reference_sites"]) for row in rows),
        eligible_sites=sum(site["source_positive_margin_eligible"] for row in rows for site in row["scored_margin_sites"]),
        eroded_sites=sum(site["source_margin_eroded"] for row in rows for site in row["scored_margin_sites"]),
        source_wrong_combined_correct=sum(not site["source_correct"] and site["actual_next_token_id"] == site["target_token_id"]
            for row in rows for site in row["scored_margin_sites"]), alignment_policy=fields.ALIGNMENT)
    components["margin"]["eligibility_by_field"] = {field: dict(
        scored=sum(site["field"] == field for row in rows for site in row["scored_margin_sites"]),
        eligible=sum(site["field"] == field and site["source_positive_margin_eligible"] for row in rows for site in row["scored_margin_sites"]),
        eroded=sum(site["field"] == field and site["source_margin_eroded"] for row in rows for site in row["scored_margin_sites"]),
        source_wrong_combined_correct=sum(site["field"] == field and not site["source_correct"]
            and site["actual_next_token_id"] == site["target_token_id"] for row in rows for site in row["scored_margin_sites"]))
        for field in FIELDS}
    active = [row for row in rows if row["union_replay_positions"]]
    receipt = dict(schema=LOSS_SCHEMA, collection_sha256=collection["collection_sha256"], inventory_sha256=inventory["inventory_sha256"],
        boundary=components["boundary"], margin=components["margin"], union_active_rows=len(active),
        union_replay_positions=sum(len(row["union_replay_positions"]) for row in rows), union_replay_prefix_tokens=0,
        one_union_replay_per_active_row=True, one_union_gradient_replay_per_active_row=True,
        replay_batch_count=0, replay_batch_count_scope="logical_active_batches", additional_optimizer_steps=0,
        replay_strategy="bulk_then_original_batch_incremental_retry_on_logit_mismatch", retry_limit_per_original_batch=1,
        replay_attempts=[], bulk_replay_batch_count=0, discarded_bulk_batch_count=0,
        incremental_retry_batch_count=0, incremental_retry_forward_steps=0,
        bulk_attempted_row_tokens=0, retry_attempted_row_tokens=0, physical_replay_forward_calls=0,
        physical_replay_row_tokens=0, full_vocabulary_retained=True,
        reference_labels_used_only_after_rollout=True, reference_documents_passed_to_model=False,
        target_prefixes_used=False, validation_rows_used=False, replay_logits_match_collection=True,
        source_replay_logits_match_collection=True, replay_logits_atol=boundary.REPLAY_ATOL,
        replay_logits_rtol=boundary.REPLAY_RTOL, maximum_replay_logit_absolute_difference=0.,
        maximum_source_replay_logit_absolute_difference=0., model_copied=False, source_head_extra_evaluations=0,
        generation=dict(max_target_tokens=collection["max_target_tokens"], batch_size=collection["batch_size"],
            greedy_batch_steps=collection["greedy_batch_steps"], elapsed_seconds=collection["elapsed_seconds"], rollout_count=1,
            model_tensor_sha256=collection["model_tensor_sha256"], source_contexts_sha256=collection["source_contexts_sha256"],
            codec_sha256=collection["codec_sha256"], input_transform_sha256=collection["input_transform_sha256"],
            source_only=True, reference_count_access=False, site_policy_access=False, inventory_access=False,
            complete_rollout_before_site_selection=True,
            rows=[dict({k: v for k, v in row.items() if k != "selected_field_sites"},
                prediction=prediction, input_sha256=core.digest(sources[row["id"]]["input"]),
                source_context_sha256=core.digest(source_contexts[row["id"]]),
                source_text_sha256=source_contexts[row["id"]]["source_sha256"])
                for row, prediction in zip(rows, collection["predictions"])]), **FALSE)
    if not active:
        _deadline(deadline)
        receipt["elapsed_seconds"] = time.monotonic()-started
        return dict(boundary_loss=None, margin_loss=None, receipt=receipt)
    snapshot = boundary._snapshot(model, torch)
    row_losses = dict(boundary=[], margin=[])
    selections = dict(boundary=boundary_selected, margin=margin_selected)
    try:
        model.eval()
        for offset in sorted({row["batch_offset"] for row in active}):
            _deadline(deadline)
            part = [row for row in active if row["batch_offset"] == offset]
            original_rows = [row for row in rows if row["batch_offset"] == offset]
            source_part = [sources[row["id"]] for row in part]
            prefixes = [row["consumed_prefix"][:row["replay_prefix_tokens"]] for row in part]
            proxy = _Replay(model)
            attempt_started = time.monotonic()
            logits = fields._bulk_replay(torch, proxy, source_part, prefixes, codec=codec,
                input_transform=input_transform, source_contexts=source_contexts, deadline=deadline)
            selected = {row["id"]: {position: logits[index, position] for position in row["union_replay_positions"]}
                for index, row in enumerate(part)}
            attempt = fields._replay_parity(torch, selected, part, kind="bulk", original_rows=original_rows,
                elapsed_seconds=time.monotonic()-attempt_started)
            _source_parity(torch, attempt, proxy.source, part, part, deadline)
            receipt["replay_attempts"].append(attempt)
            receipt["bulk_replay_batch_count"] += 1
            receipt["bulk_attempted_row_tokens"] += attempt["physical_row_tokens"]
            receipt["physical_replay_forward_calls"] += attempt["forward_calls"]
            receipt["physical_replay_row_tokens"] += attempt["physical_row_tokens"]
            if not attempt["parity_passed"]:
                del selected, logits, proxy
                receipt["discarded_bulk_batch_count"] += 1
                receipt["one_union_replay_per_active_row"] = False
                proxy = _Replay(model)
                attempt_started = time.monotonic()
                selected = fields._incremental_replay(torch, proxy, collection, part, codec=codec,
                    input_transform=input_transform, source_contexts=source_contexts, deadline=deadline)
                attempt = fields._replay_parity(torch, selected, part, kind="incremental_retry", original_rows=original_rows,
                    elapsed_seconds=time.monotonic()-attempt_started)
                _source_parity(torch, attempt, proxy.source, original_rows, part, deadline)
                receipt["replay_attempts"].append(attempt)
                receipt["incremental_retry_batch_count"] += 1
                receipt["incremental_retry_forward_steps"] += attempt["forward_calls"]
                receipt["retry_attempted_row_tokens"] += attempt["physical_row_tokens"]
                receipt["physical_replay_forward_calls"] += attempt["forward_calls"]
                receipt["physical_replay_row_tokens"] += attempt["physical_row_tokens"]
                _require(attempt["parity_passed"], "replayed source-margin logits differ from actual collected decisions")
            else:
                del logits
            del proxy
            attempt["used_for_loss"] = True
            raw = {(item["id"], item["position"]): item["logits"] for item in attempt["selected_logits"]}
            source_raw = {(item["id"], item["position"]): item["logits"] for item in attempt["source_selected_logits"]}
            receipt["maximum_replay_logit_absolute_difference"] = max(receipt["maximum_replay_logit_absolute_difference"], attempt["maximum_absolute_difference"])
            receipt["maximum_source_replay_logit_absolute_difference"] = max(receipt["maximum_source_replay_logit_absolute_difference"], attempt["maximum_source_absolute_difference"])
            receipt["replay_batch_count"] += 1
            _deadline(deadline)
            for row in part:
                receipt["union_replay_prefix_tokens"] += row["replay_prefix_tokens"]
                for name, component in components.items():
                    sites = selections[name][row["id"]]
                    if not sites:
                        continue
                    losses, measured = [], []
                    for site in sites:
                        observed = selected[row["id"]][site["position"]]
                        if name == "boundary":
                            loss = torch.nn.functional.cross_entropy(observed[None, :],
                                torch.tensor([site["target_token_id"]], dtype=torch.long))
                            detail = dict(cross_entropy=float(loss.detach()))
                        else:
                            loss, margin, competitor = _margin_tensor(torch, observed, site["target_token_id"], site["source_margin"])
                            detail = dict(margin_loss=float(loss.detach()), replayed_combined_margin=float(margin.detach()),
                                replayed_best_other_token_id=competitor,
                                replayed_source_logits=source_raw[(row["id"], site["position"])])
                        _require(core._finite(torch, loss), "nonfinite generated source-margin component")
                        losses.append(loss)
                        measured.append(detail)
                    mean = torch.stack(losses).mean()
                    row_losses[name].append(mean)
                    component["row_losses"].append(dict(id=row["id"], sites=len(sites), mean_loss=float(mean.detach())))
                    component["replay_row_tokens"] += sites[-1]["position"]+1
                    for site, detail in zip(sites, measured):
                        event = dict(id=row["id"], **{k: v for k, v in site.items() if k != "collection_logits"}, **detail,
                            consumed_prefix_length=site["position"]+1,
                            consumed_prefix_sha256=core.digest(row["consumed_prefix"][:site["position"]+1]),
                            replay_logits=raw[(row["id"], site["position"])],
                            mean_loss_coefficient=1./component["active_rows"]/len(sites))
                        if name == "boundary":
                            stop = site["completed_rules"] >= row["training_count"]
                            event["action"] = "stop" if stop else "continue"
                            component["stop_labels" if stop else "continue_labels"] += 1
                        else:
                            component["labels_by_field"][site["field"]] += 1
                        component["events"].append(event)
        result = {name: torch.stack(values).mean() if values else None for name, values in row_losses.items()}
        for name, loss in result.items():
            if loss is not None:
                _require(core._finite(torch, loss), "nonfinite mean generated source-margin component")
                components[name]["mean_loss"] = float(loss.detach())
    finally:
        boundary._preserved(model, torch, snapshot)
    _deadline(deadline)
    receipt["elapsed_seconds"] = time.monotonic()-started
    return dict(boundary_loss=result["boundary"], margin_loss=result["margin"], receipt=receipt)
