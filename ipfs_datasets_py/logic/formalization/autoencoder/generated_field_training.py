"""Training-only scalar-field and boundary losses on one actual greedy rollout.

Only the training inventory and loss see references. Collection receives closed
source rows and explicit clause contexts. Positional alignment is an authored
training contract, not inferred statutory semantics. Generation keeps its full
vocabulary; no desired token, count or prefix is supplied to the model.
"""
import hashlib
import math
import time

from . import contextual_generated_boundary_training as boundary
from . import decoder_distillation_experiment as core
from . import source_value_decoder_experiment as scalar

SCHEMA = "generated-source-field-collection/v1"
INVENTORY_SCHEMA = "generated-source-field-training-inventory/v1"
LOSS_SCHEMA = "generated-source-field-loss/v2"
FIELDS = scalar.SOURCE_FIELDS
FIELD_POLICY = "first_wrong_per_scalar_field"
ALIGNMENT = "authenticated_source_segment_ordinal_to_training_reference_rule"
FALSE = dict(boundary.FALSE)
_require = core._require
_deadline = boundary._check_deadline


def prepare_training_inventory(rows, training_references, *, contexts, codec, validate_rule):
    """Authenticate one-to-one positioned source/rule labels, once per fit.

This accepts the training split only. Repeated literal source clauses must
have consistent scalar-field labels, but remain separate positioned instances.
Neither reference text nor vectors are retained in the resulting inventory.
"""
    from . import clause_source_context
    context_receipt = clause_source_context.validate_contexts(rows, contexts)
    _require(context_receipt["dimension"] in (8, 384, 768), "supported native clause width required")
    labels = scalar.reference_source_values(rows, training_references, codec, validate_rule=validate_rule)
    records, source_labels = {}, {}
    for row in rows:
        segments, row_labels = contexts[row["id"]]["segments"], labels[row["id"]]
        _require(len(segments) == sum(record[0] >= 0 for record in row_labels),
            "explicit one-source-clause per training rule required")
        clauses = []
        for slot, segment in enumerate(segments):
            targets = dict(zip(FIELDS, row_labels[slot]))
            sha = segment["source_sha256"]
            _require(sha not in source_labels or source_labels[sha] == targets,
                "ambiguous training clause source has conflicting scalar-field labels")
            source_labels[sha] = targets
            clauses.append(dict(slot=slot, reference_rule_index=slot, source_sha256=sha,
                embedding_sha256=segment["embedding_sha256"],
                **{name: segment[name] for name in ("char_start", "char_end", "byte_start", "byte_end")},
                target_token_ids=targets))
        records[row["id"]] = dict(source_sha256=hashlib.sha256(row["source_text"].encode()).hexdigest(),
            input_sha256=core.digest(row["input"]), source_context_sha256=core.digest(contexts[row["id"]]),
            clauses=clauses, rule_count=len(clauses))
    result = dict(schema=INVENTORY_SCHEMA, alignment_policy=ALIGNMENT, dimension=context_receipt["dimension"],
        fields=list(FIELDS), rows=records, training_rows_sha256=core.digest(rows),
        training_references_sha256=core.digest(training_references), training_contexts_sha256=core.digest(contexts),
        codec_sha256=core.digest(codec), unique_training_clauses=len(source_labels),
        clause_occurrences=sum(record["rule_count"] for record in records.values()),
        reference_documents_passed_to_model=False, validation_rows_used=False,
        source_alignment_inferred=False, statutory_alignment_verified=False, **FALSE)
    result["inventory_sha256"] = core.digest(result)
    return result


def _specification(model, codec):
    description, contextual, state_size = boundary._specification(model, codec)
    _require(contextual and model.dimension in (8, 384, 768),
        "explicit contextual clause/action/recurrent model at native width8/384/768 required")
    return description, state_size


class _Collector(boundary._Collector):
    def start(self, projected, *, source_context=None):
        state = super().start(projected, source_context=source_context)
        self.field_sites = [[] for _ in projected]
        return state

    def next_logits(self, tokens, state):
        _deadline(self.deadline)
        _require(tuple(tokens.shape) == (len(self.active), 1), "actual incremental greedy path required")
        if self.previous is not None:
            _require(tokens[:, 0].tolist() == self.previous, "collection differs from actual previous argmax")
        before = state[4].tolist()
        # One observer scan records both kinds of site. The model retains its
        # existing internal recognizer; no NLP parse or second rollout occurs.
        final, field_sites = scalar._scan_value_prefix(tokens.tolist(), before, self.tables, 32)
        fields = {batch: (slot, field) for batch, offset, slot, field in field_sites
            if scalar.SOURCE_FIELDS[field] in FIELDS}
        logits, updated = self.model.next_logits(tokens, state)
        _require(type(updated) is tuple and len(updated) == self.state_size and final == updated[4].tolist(),
            "collection causal scalar/boundary grammar differs")
        chosen = logits[:, -1].argmax(-1).tolist()
        for index, token in enumerate(tokens[:, 0].tolist()):
            if not self.active[index]:
                continue
            self.prefixes[index].append(token)
            grammar = final[index]
            position = len(self.prefixes[index])-1
            if grammar[0] == boundary.cardinality._INVALID and self.invalid[index] is None:
                self.invalid[index] = position
            if before[index][0] == 9 and grammar[0] == 13 and grammar[3] == before[index][3]+1:
                self.sites[index].append(dict(position=position, completed_rules=grammar[3],
                    actual_next_token_id=chosen[index], collection_logits=logits[index, -1].detach().tolist()))
            if index in fields:
                slot, field = fields[index]
                self.field_sites[index].append(dict(position=position, slot=slot, field=scalar.SOURCE_FIELDS[field],
                    actual_next_token_id=chosen[index], collection_logits=logits[index, -1].detach().tolist()))
            if chosen[index] in (0, 1, 2):
                self.active[index] = False
        self.previous = chosen
        self.steps += 1
        return logits, updated


def collect_source_generated_sites(model, source_rows, *, codec, input_transform, source_contexts,
        max_target_tokens=512, batch_size=8, deadline):
    """Complete one unchanged source-only rollout and record all visited sites."""
    started = time.monotonic()
    _deadline(deadline)
    _require(type(max_target_tokens) is int and 4 <= max_target_tokens <= 512, "fixed512 output ceiling required")
    _require(type(batch_size) is int and 1 <= batch_size <= 128, "bounded generation batch required")
    torch = core._torch()
    core._model(model, torch)
    description, state_size = _specification(model, codec)
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
                    raise TimeoutError("generated field deadline exceeded")
                steps += observer.steps
                for index, (row, tokens, status) in enumerate(zip(part, generated[1], generated[2])):
                    prefix = observer.prefixes[index]
                    _require(prefix == [1]+tokens[:len(prefix)-1], "actual prefix does not match generated output")
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
        rollout_count=1, elapsed_seconds=time.monotonic()-started, deadline_cooperative=True, **FALSE)
    result["collection_sha256"] = core.digest(result)
    return result


def _validate_collection(model, collection, codec, input_transform, source_contexts, torch, deadline):
    _require(type(collection) is dict and collection.get("schema") == SCHEMA and collection.get("complete") is True,
        "complete actual generated-site collection required")
    _require(collection.get("collection_sha256") == core.digest({k: v for k, v in collection.items() if k != "collection_sha256"}),
        "generated-site collection digest differs")
    description, _ = _specification(model, codec)
    _require(collection["model_tensor_sha256"] == core.tensor_digest(model) and collection["model_schema"] == description["schema"]
        and collection["codec_sha256"] == core.digest(codec) and collection["input_transform_sha256"] == core.digest(input_transform)
        and collection["source_contexts_sha256"] == core.digest(source_contexts), "stale model/codec/transform/context collection")
    _require(collection["generation_temperature"] == 0 and collection["source_only"] is True
        and collection["reference_count_access"] is False and collection["reference_prefix_access"] is False
        and collection["site_policy_access"] is False and collection["inventory_access"] is False
        and collection["complete_rollout_before_site_selection"] is True, "source-only completed rollout required")
    _require(type(collection["batch_size"]) is int and 1 <= collection["batch_size"] <= 128
        and type(collection["max_target_tokens"]) is int and 4 <= collection["max_target_tokens"] <= 512,
        "bounded recorded generation limits required")
    sources = collection["source_rows"]
    boundary._sources(sources, model.dimension, True, source_contexts)
    _require([row["id"] for row in collection["rows"]] == [row["id"] for row in sources]
        == [row["id"] for row in collection["predictions"]], "complete ordered source rows required")
    size = len(codec["target_vocabulary"])
    tables = boundary.cardinality._tables(codec, size, torch)
    for row_index, (row, prediction) in enumerate(zip(collection["rows"], collection["predictions"])):
        _deadline(deadline)
        _require(type(row.get("batch_offset")) is int
            and row["batch_offset"] == row_index//collection["batch_size"]*collection["batch_size"],
            "actual original collection batch offset differs")
        prefix, output, status = row["consumed_prefix"], prediction["token_ids"], prediction["generation_status"]
        _require(type(prefix) is list and 1 <= len(prefix) < collection["max_target_tokens"] and prefix[0] == 1
            and all(type(token) is int and 0 <= token < size for token in prefix), "bounded actual consumed prefix required")
        _require(type(output) is list and all(type(token) is int and 3 <= token < size for token in output)
            and prefix == [1]+output[:len(prefix)-1], "prefix/output binding differs")
        _require(status in ("eos", "invalid_special_token", "output_limit") and prediction["eos_reached"] == (status == "eos")
            and len(output) == len(prefix)-(status != "output_limit")
            and (status != "output_limit" or len(prefix) == collection["max_target_tokens"]-1), "complete generation status differs")
        grammar, expected_boundaries, expected_fields, invalid = [[0]*6], [], [], None
        for position, token in enumerate(prefix):
            if position % 32 == 0:
                _deadline(deadline)
            updated, sites = scalar._scan_value_prefix([[token]], grammar, tables, 32)
            if grammar[0][0] == 9 and updated[0][0] == 13 and updated[0][3] == grammar[0][3]+1:
                expected_boundaries.append(dict(position=position, completed_rules=updated[0][3]))
            expected_fields.extend(dict(position=position, slot=slot, field=scalar.SOURCE_FIELDS[field])
                for _, _, slot, field in sites if scalar.SOURCE_FIELDS[field] in FIELDS)
            if updated[0][0] == boundary.cardinality._INVALID and invalid is None:
                invalid = position
            grammar = updated
        _require(row["first_invalid_prefix_position"] == invalid, "actual invalid prefix differs")
        for key, countkey, expected in (("available_sites", "available_site_count", expected_boundaries),
                ("available_field_sites", "available_field_site_count", expected_fields)):
            sites = row[key]
            _require(type(sites) is list and len(sites) == len(expected) == row[countkey], "actual available site inventory differs")
            for site, identity in zip(sites, expected):
                _require(type(site) is dict and set(site) == set(identity)|{"actual_next_token_id", "collection_logits"}
                    and all(type(site[k]) is type(v) and site[k] == v for k, v in identity.items()), "actual causal site identity differs")
                logits, chosen, position = site["collection_logits"], site["actual_next_token_id"], site["position"]
                _require(type(logits) is list and len(logits) == size and all(type(value) in (int, float) and math.isfinite(value) for value in logits)
                    and type(chosen) is int and chosen == max(range(size), key=logits.__getitem__), "actual site argmax/logits differ")
                _require(chosen == output[position] if position < len(output) else
                    chosen == 2 if status == "eos" else chosen in (0, 1) if status == "invalid_special_token" else False,
                    "site choice differs from actual generated output")
    for total, key in (("available_sites", "available_site_count"), ("available_field_sites", "available_field_site_count")):
        _require(collection[total] == sum(row[key] for row in collection["rows"]), "available site totals differ")
    return tables


def _validate_inventory(inventory, sources, contexts, codec, dimension, deadline):
    _require(type(inventory) is dict and inventory.get("schema") == INVENTORY_SCHEMA
        and inventory.get("inventory_sha256") == core.digest({k: v for k, v in inventory.items() if k != "inventory_sha256"}),
        "authenticated generated-field training inventory required")
    _require(inventory.get("alignment_policy") == ALIGNMENT and inventory.get("fields") == list(FIELDS)
        and inventory.get("codec_sha256") == core.digest(codec) and inventory.get("dimension") == dimension
        and inventory.get("validation_rows_used") is False and inventory.get("source_alignment_inferred") is False,
        "explicit training-only positioned source/rule alignment required")
    size = len(codec["target_vocabulary"])
    rows = inventory.get("rows")
    _require(type(rows) is dict and 1 <= len(rows) <= 4096, "bounded inventory rows required")
    for row in sources:
        _deadline(deadline)
        record = rows.get(row["id"])
        segments = contexts[row["id"]]["segments"]
        _require(type(record) is dict and record.get("source_sha256") == hashlib.sha256(row["source_text"].encode()).hexdigest()
            and record.get("input_sha256") == core.digest(row["input"])
            and record.get("source_context_sha256") == core.digest(contexts[row["id"]])
            and type(record.get("rule_count")) is int and record["rule_count"] == len(segments)
            and type(record.get("clauses")) is list and len(record["clauses"]) == len(segments),
            "training inventory differs from exact source/context occurrence")
        for slot, (clause, segment) in enumerate(zip(record["clauses"], segments)):
            keys = ("source_sha256", "embedding_sha256", "char_start", "char_end", "byte_start", "byte_end")
            _require(type(clause) is dict and type(clause.get("slot")) is int and clause["slot"] == slot
                and type(clause.get("reference_rule_index")) is int and clause["reference_rule_index"] == slot
                and all(type(clause.get(k)) is type(segment[k]) and clause[k] == segment[k] for k in keys),
                "training rule/source segment alignment differs")
            targets = clause.get("target_token_ids")
            _require(type(targets) is dict and set(targets) == set(FIELDS)
                and all(type(token) is int and 3 <= token < size for token in targets.values()),
                "authenticated full-vocabulary field labels required")
    return rows


def _select_fields(sites, clauses):
    selected, scored, unscored, seen = [], [], [], set()
    for site in sites:
        if site["slot"] >= len(clauses):
            unscored.append(dict(position=site["position"], slot=site["slot"], field=site["field"], reason="source_clause_and_reference_slot_unavailable"))
            continue
        clause = clauses[site["slot"]]
        target = clause["target_token_ids"][site["field"]]
        record = dict(site, target_token_id=target, source_sha256=clause["source_sha256"], reference_rule_index=clause["reference_rule_index"])
        scored.append(record)
        if site["actual_next_token_id"] != target and site["field"] not in seen:
            selected.append(record)
            seen.add(site["field"])
    return sorted(selected, key=lambda site: site["position"]), scored, unscored


def _bulk_replay(torch, model, source_part, prefixes, *, codec, input_transform, source_contexts, deadline):
    """The fast complete-prefix path; the caller checks every selected logit."""
    _deadline(deadline)
    width = max(map(len, prefixes))
    tokens = torch.tensor([prefix+[0]*(width-len(prefix)) for prefix in prefixes], dtype=torch.long)
    _, logits = core._logits(torch, model, boundary.legacy._data(torch, source_part, input_transform),
        tokens, len(codec["target_vocabulary"]),
        **core._source_context_kwargs(torch, source_part, source_contexts, input_transform))
    _deadline(deadline)
    return logits


def _incremental_replay(torch, model, collection, active_rows, *, codec, input_transform, source_contexts, deadline):
    """Retry one original batch, preserving its causal greedy execution shape.

    Every original row remains present. Actual argmax tokens continue inactive
    rows exactly as in collection; all available consumed prefixes are checked.
    No reference token, closure rule, mask or tolerance change enters this path.
    """
    _deadline(deadline)
    offsets = {row["batch_offset"] for row in active_rows}
    _require(len(offsets) == 1, "retry must preserve one original collection batch")
    offset = next(iter(offsets))
    original_rows = [row for row in collection["rows"] if row["batch_offset"] == offset]
    sources = {row["id"]: row for row in collection["source_rows"]}
    source_part = [sources[row["id"]] for row in original_rows]
    desired = {row["id"]: set(row["union_replay_positions"]) for row in active_rows}
    steps = max(row["replay_prefix_tokens"] for row in active_rows)
    projected = model.project(boundary.legacy._data(torch, source_part, input_transform))
    state = model.start(projected,
        **core._source_context_kwargs(torch, source_part, source_contexts, input_transform))
    tokens = torch.ones((len(original_rows), 1), dtype=torch.long)
    selected = {row["id"]: {} for row in active_rows}
    for position in range(steps):
        _deadline(deadline)
        for index, row in enumerate(original_rows):
            if position < len(row["consumed_prefix"]):
                _require(int(tokens[index, 0]) == row["consumed_prefix"][position],
                    "incremental retry differs from actual collected prefix")
        logits, state = model.next_logits(tokens, state)
        _require(tuple(logits.shape) == (len(original_rows), 1, len(codec["target_vocabulary"]))
            and core._finite(torch, logits) and core._finite(torch, state), "invalid incremental retry state")
        for index, row in enumerate(original_rows):
            if position in desired.get(row["id"], ()):
                selected[row["id"]][position] = logits[index, 0]
        tokens = logits[:, -1].detach().argmax(-1).unsqueeze(1)
    _deadline(deadline)
    return selected


def _replay_parity(torch, selected, rows, *, kind, original_rows, elapsed_seconds):
    """Inspect the complete selected union before creating any component CE."""
    records, mismatches, maximum = [], [], 0.
    for row in rows:
        by_position = {site["position"]: site for site in
            [*row["selected_boundary_sites"], *row["selected_field_sites"]]}
        for position in row["union_replay_positions"]:
            observed = selected[row["id"]][position].detach()
            original = torch.tensor(by_position[position]["collection_logits"], dtype=observed.dtype)
            _require(observed.shape == original.shape and core._finite(torch, observed), "invalid selected replay logits")
            difference = (observed-original).abs()
            maximum = max(maximum, float(difference.max()))
            tolerance = boundary.REPLAY_ATOL+boundary.REPLAY_RTOL*original.abs()
            records.append(dict(id=row["id"], position=position, logits=observed.tolist()))
            for coordinate in (difference > tolerance).nonzero().flatten().tolist():
                mismatches.append(dict(id=row["id"], position=position, vocabulary_index=coordinate,
                    collected=float(original[coordinate]), replayed=float(observed[coordinate]),
                    absolute_difference=float(difference[coordinate]), allowed_difference=float(tolerance[coordinate])))
    steps = max(row["replay_prefix_tokens"] for row in rows)
    physical_rows = rows if kind == "bulk" else original_rows
    return dict(kind=kind, row_ids=[row["id"] for row in physical_rows], active_row_ids=[row["id"] for row in rows],
        original_batch_offset=rows[0]["batch_offset"], prefix_steps=steps,
        prefix_lengths=[row["replay_prefix_tokens"] for row in rows],
        prefix_lengths_scope="active_row_ids",
        physical_row_tokens=len(physical_rows)*steps, forward_calls=1 if kind == "bulk" else steps,
        selected_logits=records, parity_passed=not mismatches, used_for_loss=False,
        maximum_absolute_difference=maximum, mismatches=mismatches, elapsed_seconds=elapsed_seconds,
        elapsed_seconds_scope="forward_and_selected_tensor_gather_excluding_parity_check_and_component_losses",
        before_component_cross_entropy=True, original_batch_membership_preserved=kind == "incremental_retry",
        collected_prefix_checked=kind == "incremental_retry")


def _component(name, rows, selected, available, policy, cap, size):
    active = sum(bool(selected[row["id"]]) for row in rows)
    return dict(component=name, selection_policy=policy, site_cap_per_row=cap, rows=len(rows), active_rows=active,
        selected_sites=sum(len(sites) for sites in selected.values()), available_sites=available,
        rows_without_selected_sites=len(rows)-active, reduction="mean_selected_sites_within_row_then_mean_active_rows",
        full_vocabulary_cross_entropy=True, vocabulary_size=size, mean_loss=None, events=[], row_losses=[],
        replay_row_tokens=0, gradient_scope="all_trainable")


def generated_site_losses(torch, model, collection, inventory, *, codec, input_transform, source_contexts,
        deadline, boundary_site_policy="first_last"):
    """Select after rollout and share one accepted gradient pass between two CEs.

    The fixed field policy selects the first wrong decision for each scalar
    field (actor, action, modality, object), at most four sites per row, using
    the authenticated source/rule ordinal. Unavailable or unvisited slots
    receive no invented labels. Each component averages sites within an active
    row, then its own active rows. The caller owns weights and the single
    optimizer step. A rejected bulk graph is discarded before a strict causal
    retry, which preserves original batch membership and the same tolerance.
    """
    started = time.monotonic()
    _deadline(deadline)
    _require(type(boundary_site_policy) is str and boundary_site_policy in boundary.SITE_POLICIES,
        "explicit supported boundary site policy required")
    core._model(model, torch)
    boundary.legacy._transform(input_transform, model.dimension)
    tables = _validate_collection(model, collection, codec, input_transform, source_contexts, torch, deadline)
    sources = {row["id"]: row for row in collection["source_rows"]}
    reference_rows = _validate_inventory(inventory, collection["source_rows"], source_contexts, codec, model.dimension, deadline)
    boundary_selected, field_selected, rows = {}, {}, []
    for row in collection["rows"]:
        _deadline(deadline)
        record = reference_rows[row["id"]]
        selected = boundary._select(row["available_sites"], record["rule_count"], tables, boundary_site_policy)
        boundary_selected[row["id"]] = [dict(site, training_count=record["rule_count"],
            target_token_id=tables[0]["," if site["completed_rules"] < record["rule_count"] else "]"])
            for site in selected]
        selected_fields, scored_fields, unscored_fields = _select_fields(row["available_field_sites"], record["clauses"])
        field_selected[row["id"]] = selected_fields
        positions = sorted({site["position"] for site in [*boundary_selected[row["id"]], *selected_fields]})
        rows.append(dict(row, selected_boundary_sites=boundary_selected[row["id"]], selected_field_sites=selected_fields,
            scored_field_sites=len(scored_fields), correct_field_sites=sum(site["actual_next_token_id"] == site["target_token_id"] for site in scored_fields),
            wrong_field_sites=sum(site["actual_next_token_id"] != site["target_token_id"] for site in scored_fields),
            unscored_field_sites=unscored_fields, training_count=record["rule_count"],
            union_replay_positions=positions, replay_prefix_tokens=positions[-1]+1 if positions else 0))
    size = len(codec["target_vocabulary"])
    components = dict(boundary=_component("boundary", rows, boundary_selected, collection["available_sites"], boundary_site_policy,
            2 if boundary_site_policy == "first_last" else 1, size),
        field=_component("field", rows, field_selected, collection["available_field_sites"], FIELD_POLICY, len(FIELDS), size))
    components["boundary"].update(stop_labels=0, continue_labels=0)
    components["field"].update(fields=list(FIELDS), scored_sites=sum(row["scored_field_sites"] for row in rows),
        unscored_sites=sum(len(row["unscored_field_sites"]) for row in rows),
        correct_sites=sum(row["correct_field_sites"] for row in rows), wrong_sites=sum(row["wrong_field_sites"] for row in rows),
        labels_by_field={field: 0 for field in FIELDS}, alignment_policy=ALIGNMENT)
    active = [row for row in rows if row["union_replay_positions"]]
    receipt = dict(schema=LOSS_SCHEMA, collection_sha256=collection["collection_sha256"], inventory_sha256=inventory["inventory_sha256"],
        boundary=components["boundary"], field=components["field"], union_active_rows=len(active),
        union_replay_positions=sum(len(row["union_replay_positions"]) for row in rows), union_replay_prefix_tokens=0,
        one_union_replay_per_active_row=True, replay_batch_count=0, additional_optimizer_steps=0,
        one_union_gradient_replay_per_active_row=True, replay_batch_count_scope="logical_active_batches",
        replay_strategy="bulk_then_original_batch_incremental_retry_on_logit_mismatch",
        retry_limit_per_original_batch=1, replay_attempts=[], bulk_replay_batch_count=0,
        discarded_bulk_batch_count=0, incremental_retry_batch_count=0, incremental_retry_forward_steps=0,
        bulk_attempted_row_tokens=0, retry_attempted_row_tokens=0,
        physical_replay_forward_calls=0, physical_replay_row_tokens=0,
        full_vocabulary_cross_entropy=True, reference_labels_used_only_after_rollout=True,
        reference_documents_passed_to_model=False, target_prefixes_used=False, validation_rows_used=False,
        replay_logits_match_collection=True, replay_logits_atol=boundary.REPLAY_ATOL, replay_logits_rtol=boundary.REPLAY_RTOL,
        maximum_replay_logit_absolute_difference=0., model_copied=False, gradient_scope="all_trainable", **FALSE)
    receipt["generation"] = dict(max_target_tokens=collection["max_target_tokens"], batch_size=collection["batch_size"],
        greedy_batch_steps=collection["greedy_batch_steps"], elapsed_seconds=collection["elapsed_seconds"], rollout_count=1,
        model_tensor_sha256=collection["model_tensor_sha256"], source_contexts_sha256=collection["source_contexts_sha256"],
        codec_sha256=collection["codec_sha256"], input_transform_sha256=collection["input_transform_sha256"],
        source_only=True, reference_count_access=False, site_policy_access=False, inventory_access=False,
        complete_rollout_before_site_selection=True,
        rows=[dict(**row, prediction=prediction, input_sha256=core.digest(sources[row["id"]]["input"]),
            source_context_sha256=core.digest(source_contexts[row["id"]]), source_text_sha256=source_contexts[row["id"]]["source_sha256"])
            for row, prediction in zip(rows, collection["predictions"])])
    if not active:
        _deadline(deadline)
        receipt["elapsed_seconds"] = time.monotonic()-started
        return dict(boundary_loss=None, field_loss=None, receipt=receipt)
    snapshot = boundary._snapshot(model, torch)
    row_losses = dict(boundary=[], field=[])
    selected_by_component = dict(boundary=boundary_selected, field=field_selected)
    try:
        model.eval()
        for offset in sorted({row["batch_offset"] for row in active}):
            _deadline(deadline)
            part = [row for row in active if row["batch_offset"] == offset]
            original_rows = [row for row in rows if row["batch_offset"] == offset]
            source_part = [sources[row["id"]] for row in part]
            prefixes = [row["consumed_prefix"][:row["replay_prefix_tokens"]] for row in part]
            attempt_started = time.monotonic()
            logits = _bulk_replay(torch, model, source_part, prefixes, codec=codec,
                input_transform=input_transform, source_contexts=source_contexts, deadline=deadline)
            selected = {row["id"]: {position: logits[index, position] for position in row["union_replay_positions"]}
                for index, row in enumerate(part)}
            attempt = _replay_parity(torch, selected, part, kind="bulk", original_rows=original_rows,
                elapsed_seconds=time.monotonic()-attempt_started)
            receipt["replay_attempts"].append(attempt)
            receipt["bulk_replay_batch_count"] += 1
            receipt["bulk_attempted_row_tokens"] += attempt["physical_row_tokens"]
            receipt["physical_replay_forward_calls"] += attempt["forward_calls"]
            receipt["physical_replay_row_tokens"] += attempt["physical_row_tokens"]
            if not attempt["parity_passed"]:
                # Drop every reference to the rejected graph before constructing
                # the retry. No CE, backward or optimizer step used that graph.
                del selected, logits
                receipt["discarded_bulk_batch_count"] += 1
                receipt["one_union_replay_per_active_row"] = False
                attempt_started = time.monotonic()
                selected = _incremental_replay(torch, model, collection, part, codec=codec,
                    input_transform=input_transform, source_contexts=source_contexts, deadline=deadline)
                attempt = _replay_parity(torch, selected, part, kind="incremental_retry", original_rows=original_rows,
                    elapsed_seconds=time.monotonic()-attempt_started)
                receipt["replay_attempts"].append(attempt)
                receipt["incremental_retry_batch_count"] += 1
                receipt["incremental_retry_forward_steps"] += attempt["forward_calls"]
                receipt["retry_attempted_row_tokens"] += attempt["physical_row_tokens"]
                receipt["physical_replay_forward_calls"] += attempt["forward_calls"]
                receipt["physical_replay_row_tokens"] += attempt["physical_row_tokens"]
                _require(attempt["parity_passed"], "replayed generated-site logits differ from actual collected decisions")
            else:
                del logits
            attempt["used_for_loss"] = True
            accepted_raw = {(item["id"], item["position"]): item["logits"] for item in attempt["selected_logits"]}
            receipt["maximum_replay_logit_absolute_difference"] = max(receipt["maximum_replay_logit_absolute_difference"],
                attempt["maximum_absolute_difference"])
            receipt["replay_batch_count"] += 1
            _deadline(deadline)
            for index, row in enumerate(part):
                receipt["union_replay_prefix_tokens"] += row["replay_prefix_tokens"]
                for name, component in components.items():
                    sites = selected_by_component[name][row["id"]]
                    if not sites:
                        continue
                    observed = torch.stack([selected[row["id"]][site["position"]] for site in sites])
                    targets = torch.tensor([site["target_token_id"] for site in sites], dtype=torch.long)
                    losses = torch.nn.functional.cross_entropy(observed, targets, reduction="none")
                    _require(core._finite(torch, losses), "nonfinite generated-site loss")
                    row_losses[name].append(losses.mean())
                    component["row_losses"].append(dict(id=row["id"], sites=len(sites), mean_ce=float(losses.mean().detach())))
                    component["replay_row_tokens"] += sites[-1]["position"]+1
                    for site, ce in zip(sites, losses.detach().tolist()):
                        event = dict(id=row["id"], **{k: v for k, v in site.items() if k != "collection_logits"},
                            consumed_prefix_length=site["position"]+1,
                            consumed_prefix_sha256=core.digest(row["consumed_prefix"][:site["position"]+1]),
                            cross_entropy=ce, replay_logits=accepted_raw[(row["id"], site["position"])],
                            mean_loss_coefficient=1./component["active_rows"]/len(sites))
                        if name == "boundary":
                            stop = site["completed_rules"] >= row["training_count"]
                            event["action"] = "stop" if stop else "continue"
                            component["stop_labels" if stop else "continue_labels"] += 1
                        else:
                            component["labels_by_field"][site["field"]] += 1
                        component["events"].append(event)
        losses = {name: torch.stack(rows).mean() if rows else None for name, rows in row_losses.items()}
        for name, loss in losses.items():
            if loss is not None:
                _require(core._finite(torch, loss), "nonfinite mean generated-site loss")
                components[name]["mean_loss"] = float(loss.detach())
    finally:
        boundary._preserved(model, torch, snapshot)
    _deadline(deadline)
    receipt["elapsed_seconds"] = time.monotonic()-started
    return dict(boundary_loss=losses["boundary"], field_loss=losses["field"], receipt=receipt)
