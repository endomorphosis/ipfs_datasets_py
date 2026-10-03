"""Training-only boundary supervision after complete source-only generation.

Collection knows neither the site-selection policy nor the reference counts.
The loss selects first/last sites or the first wrong decision only afterward.
All vocabulary classes remain available, including during prefix replay. This
cardinality objective does not establish semantic reconstruction or admission.
"""
import math
import random
import time

from . import decoder_cardinality_experiment as cardinality
from . import decoder_distillation_experiment as core
from . import generated_boundary_training as legacy

SCHEMA = "contextual-generated-source-boundary-collection/v1"
LOSS_SCHEMA = "contextual-generated-source-boundary-loss/v1"
SITE_POLICIES = ("first_last", "first_wrong")
REPLAY_ATOL = 2e-5
REPLAY_RTOL = 2e-5
FALSE = dict(legacy.FALSE)
_require = core._require
_check_deadline = legacy._check_deadline
_state_versions = legacy._state_versions


def _specification(model, codec):
    """Explicit trainable architectures only; inference controls are excluded."""
    description = model.describe()
    schema = description.get("schema")
    if schema == "shared-slot-source-decoder-development/v1":
        from . import shared_slot_source_decoder_experiment as owner
        contextual, state_size = False, 6
    elif schema == "clause-source-decoder-development/v1":
        from . import clause_source_decoder_experiment as owner
        contextual, state_size = True, 6
    elif schema == "action-factorized-clause-source-decoder-development/v1":
        from . import action_factorized_clause_decoder_experiment as owner
        contextual, state_size = True, 6
    elif schema == "ordered-clause-recurrent-source-decoder-development/v1":
        from . import ordered_clause_recurrent_decoder_experiment as owner
        contextual, state_size = True, 7
    else:
        raise ValueError("explicit supported trainable boundary architecture required")
    return owner.checked_specification(model, codec), contextual, state_size


def _sources(rows, dimension, contextual, source_contexts):
    _require(type(rows) is list and 1 <= len(rows) <= 128, "bounded source-only collection required")
    keys = {"id", "input", "source_text"} if contextual else {"id", "input"}
    identities = set()
    for row in rows:
        _require(type(row) is dict and set(row) == keys,
            "closed source-only rows exclude targets, counts and prefixes")
        identity = row["id"]
        _require(type(identity) is str and 0 < len(identity) <= 512 and identity not in identities,
            "unique bounded source identity required")
        identities.add(identity)
        core._vector(row["input"], dimension)
    _require(contextual == (source_contexts is not None), "architecture and explicit source contexts must be paired")
    if contextual:
        from . import clause_source_context
        receipt = clause_source_context.validate_contexts(rows, source_contexts)
        _require(receipt["dimension"] == dimension, "source context dimension differs")


def _snapshot(model, torch):
    return (core.tensor_digest(model), _state_versions(model),
        {name: module.training for name, module in model.named_modules()},
        torch.get_rng_state().clone(), random.getstate())


def _preserved(model, torch, snapshot):
    digest, versions, modes, rng, python_rng = snapshot
    for name, module in model.named_modules():
        module.training = modes[name]
    _require(core.tensor_digest(model) == digest and _state_versions(model) == versions,
        "boundary operation mutated caller weights or gradients")
    _require(torch.equal(torch.get_rng_state(), rng) and random.getstate() == python_rng,
        "boundary operation changed ambient RNG")


class _Collector:
    def __init__(self, model, tables, deadline, state_size):
        self.model, self.tables, self.deadline, self.state_size = model, tables, deadline, state_size

    def project(self, data):
        return self.model.project(data)

    def start(self, projected, *, source_context=None):
        state = self.model.start(projected, **({} if source_context is None else {"source_context": source_context}))
        _require(type(state) is tuple and len(state) == self.state_size, "explicit causal boundary state required")
        self.active = [True]*len(projected)
        self.prefixes = [[] for _ in projected]
        self.sites = [[] for _ in projected]
        self.invalid = [None]*len(projected)
        self.previous = None
        self.steps = 0
        return state

    def next_logits(self, tokens, state):
        _check_deadline(self.deadline)
        _require(tuple(tokens.shape) == (len(self.active), 1), "actual incremental greedy path required")
        if self.previous is not None:
            _require(tokens[:, 0].tolist() == self.previous, "collection differs from actual previous argmax")
        before = state[4].tolist()
        final, _ = cardinality._scan_prefix(tokens.tolist(), before, self.tables)
        logits, updated = self.model.next_logits(tokens, state)
        _require(type(updated) is tuple and len(updated) == self.state_size and final == updated[4].tolist(),
            "collection causal grammar differs")
        chosen = logits[:, -1].argmax(-1).tolist()
        for index, token in enumerate(tokens[:, 0].tolist()):
            if not self.active[index]:
                continue
            self.prefixes[index].append(token)
            grammar = final[index]
            if grammar[0] == cardinality._INVALID and self.invalid[index] is None:
                self.invalid[index] = len(self.prefixes[index])-1
            if before[index][0] == 9 and grammar[0] == 13 and grammar[3] == before[index][3]+1:
                self.sites[index].append(dict(position=len(self.prefixes[index])-1, completed_rules=grammar[3],
                    actual_next_token_id=chosen[index], collection_logits=logits[index, -1].detach().tolist()))
            if chosen[index] in (0, 1, 2):
                self.active[index] = False
        self.previous = chosen
        self.steps += 1
        return logits, updated


def collect_source_boundary_prefixes(model, source_rows, *, codec, input_transform, source_contexts=None,
        max_target_tokens=512, batch_size=8, deadline, max_sites_per_row=2):
    """Observe all actual greedy boundaries; never access policy or labels.

Context vectors are supplied separately and bound by digest, not repeated in
the collection. ``max_sites_per_row`` bounds the later loss, not observation.
"""
    started = time.monotonic()
    _check_deadline(deadline)
    _require(type(max_target_tokens) is int and 4 <= max_target_tokens <= 512, "fixed512 output ceiling required")
    _require(type(batch_size) is int and 1 <= batch_size <= 128, "bounded generation batch required")
    _require(type(max_sites_per_row) is int and max_sites_per_row == 2, "fixed two-site loss ceiling required")
    torch = core._torch()
    core._model(model, torch)
    description, contextual, state_size = _specification(model, codec)
    _sources(source_rows, model.dimension, contextual, source_contexts)
    legacy._transform(input_transform, model.dimension)
    tables = cardinality._tables(codec, len(codec["target_vocabulary"]), torch)
    snapshot = _snapshot(model, torch)
    predictions, records, steps = [], [], 0
    try:
        model.eval()
        with torch.no_grad():
            for offset in range(0, len(source_rows), batch_size):
                _check_deadline(deadline)
                part = source_rows[offset:offset+batch_size]
                observer = _Collector(model, tables, deadline, state_size)
                generated = core._greedy(torch, observer, legacy._data(torch, part, input_transform),
                    max_target_tokens, len(codec["target_vocabulary"]), deadline,
                    **core._source_context_kwargs(torch, part, source_contexts, input_transform))
                if generated is None:
                    raise TimeoutError("generated boundary deadline exceeded")
                steps += observer.steps
                for index, (row, tokens, status) in enumerate(zip(part, generated[1], generated[2])):
                    prefix, sites = observer.prefixes[index], observer.sites[index]
                    _require(prefix == [1]+tokens[:len(prefix)-1], "actual prefix does not match generated output")
                    predictions.append(dict(id=row["id"], token_ids=tokens, generation_status=status, eos_reached=status == "eos"))
                    records.append(dict(id=row["id"], consumed_prefix=prefix, available_sites=sites,
                        available_site_count=len(sites), first_invalid_prefix_position=observer.invalid[index], batch_offset=offset))
    finally:
        _preserved(model, torch, snapshot)
    _check_deadline(deadline)
    result = dict(schema=SCHEMA, complete=True, model_tensor_sha256=snapshot[0], model_schema=description["schema"],
        codec_sha256=core.digest(codec), input_transform_sha256=core.digest(input_transform),
        source_contexts_sha256=None if source_contexts is None else core.digest(source_contexts),
        source_rows=[dict(row, input=list(row["input"])) for row in source_rows], predictions=predictions, rows=records,
        batch_size=batch_size, max_target_tokens=max_target_tokens, max_sites_per_row=2,
        available_sites=sum(row["available_site_count"] for row in records),
        rows_without_sites=sum(not row["available_sites"] for row in records), greedy_batch_steps=steps,
        generation_temperature=0, reference_count_access=False, reference_prefix_access=False,
        reference_documents_passed_to_model=False, site_policy_access=False, source_only=True, collection_no_grad=True,
        source_context_target_access=False, full_vocabulary_retained=True, syntax_mask=False, forced_closure=False,
        complete_rollout_before_site_selection=True, model_copied=False, caller_state_preserved=True,
        elapsed_seconds=time.monotonic()-started, deadline_cooperative=True, **FALSE)
    result["collection_sha256"] = core.digest(result)
    return result


def _validate_collection(model, collection, codec, input_transform, source_contexts, torch, deadline):
    _require(type(collection) is dict and collection.get("schema") == SCHEMA and collection.get("complete") is True,
        "complete actual source collection required")
    _require(collection.get("collection_sha256") == core.digest({k: v for k, v in collection.items() if k != "collection_sha256"}),
        "source collection digest differs")
    description, contextual, _ = _specification(model, codec)
    _require(collection["model_tensor_sha256"] == core.tensor_digest(model)
        and collection["model_schema"] == description["schema"] and collection["codec_sha256"] == core.digest(codec)
        and collection["input_transform_sha256"] == core.digest(input_transform)
        and collection["source_contexts_sha256"] == (None if source_contexts is None else core.digest(source_contexts)),
        "stale model/codec/transform/context collection")
    _require(collection["max_sites_per_row"] == 2 and collection["generation_temperature"] == 0
        and collection["source_only"] is True and collection["reference_count_access"] is False
        and collection["reference_prefix_access"] is False and collection["site_policy_access"] is False
        and collection["complete_rollout_before_site_selection"] is True,
        "source-only complete rollout required before label-dependent selection")
    _require(type(collection["batch_size"]) is int and 1 <= collection["batch_size"] <= 128
        and type(collection["max_target_tokens"]) is int and 4 <= collection["max_target_tokens"] <= 512,
        "bounded recorded generation limits required")
    sources = collection["source_rows"]
    _sources(sources, model.dimension, contextual, source_contexts)
    _require([row["id"] for row in collection["rows"]] == [row["id"] for row in sources]
        == [row["id"] for row in collection["predictions"]], "complete ordered source rows required")
    size = len(codec["target_vocabulary"])
    tables = cardinality._tables(codec, size, torch)
    for row, prediction in zip(collection["rows"], collection["predictions"]):
        _check_deadline(deadline)
        prefix, output = row["consumed_prefix"], prediction["token_ids"]
        _require(type(prefix) is list and 1 <= len(prefix) < collection["max_target_tokens"]
            and prefix[0] == 1 and all(type(token) is int and 0 <= token < size for token in prefix),
            "bounded actual consumed prefix required")
        _require(type(output) is list and all(type(token) is int and 3 <= token < size for token in output)
            and prefix == [1]+output[:len(prefix)-1], "prefix/output binding differs")
        status = prediction["generation_status"]
        _require(status in ("eos", "invalid_special_token", "output_limit")
            and prediction["eos_reached"] == (status == "eos")
            and len(output) == len(prefix)-(status != "output_limit")
            and (status != "output_limit" or len(prefix) == collection["max_target_tokens"]-1),
            "complete actual generation status differs")
        state, expected, invalid = [[0]*6], [], None
        for position, token in enumerate(prefix):
            if position % 32 == 0:
                _check_deadline(deadline)
            updated, _ = cardinality._scan_prefix([[token]], state, tables)
            if state[0][0] == 9 and updated[0][0] == 13 and updated[0][3] == state[0][3]+1:
                expected.append((position, updated[0][3]))
            if updated[0][0] == cardinality._INVALID and invalid is None:
                invalid = position
            state = updated
        sites = row["available_sites"]
        _require(type(sites) is list and len(sites) == len(expected) == row["available_site_count"]
            and row["first_invalid_prefix_position"] == invalid, "actual available boundaries differ")
        for site, (position, count) in zip(sites, expected):
            _require(type(site) is dict and set(site) == {"position", "completed_rules", "actual_next_token_id", "collection_logits"}
                and type(site["position"]) is int and type(site["completed_rules"]) is int
                and (site["position"], site["completed_rules"]) == (position, count), "actual boundary position/count differs")
            logits, chosen = site["collection_logits"], site["actual_next_token_id"]
            _require(type(logits) is list and len(logits) == size and all(type(value) in (int, float) and math.isfinite(value) for value in logits)
                and type(chosen) is int and chosen == max(range(size), key=logits.__getitem__), "actual boundary argmax/logits differ")
            _require(chosen == output[position] if position < len(output) else
                chosen == 2 if status == "eos" else chosen in (0, 1) if status == "invalid_special_token" else False,
                "boundary choice differs from actual generated output")
    _require(collection["available_sites"] == sum(row["available_site_count"] for row in collection["rows"])
        and collection["rows_without_sites"] == sum(not row["available_sites"] for row in collection["rows"]),
        "available boundary totals differ")
    return tables


def _select(sites, count, tables, policy):
    if policy == "first_last":
        return sites if len(sites) <= 1 else [sites[0], sites[-1]]
    return next(([site] for site in sites
        if site["actual_next_token_id"] != tables[0]["," if site["completed_rules"] < count else "]"]), [])


def generated_boundary_loss(torch, model, collection, training_counts_by_id, *, codec, input_transform,
        source_contexts=None, deadline, site_policy="first_last", gradient_scope="all_trainable"):
    """Score selected actual generated prefixes after collection, never update.

Both policies use authenticated training counts only here. First-wrong selects
at most one site per row, and correct/no-site rows attach no loss graph. Prefix
replay sees the original source context and all vocabulary classes.
"""
    started = time.monotonic()
    _check_deadline(deadline)
    _require(type(site_policy) is str and site_policy in SITE_POLICIES, "explicit supported boundary site policy required")
    _require(gradient_scope == "all_trainable", "contextual boundary loss supports all_trainable gradients only")
    core._model(model, torch)
    legacy._transform(input_transform, model.dimension)
    tables = _validate_collection(model, collection, codec, input_transform, source_contexts, torch, deadline)
    _require(type(training_counts_by_id) is dict and 1 <= len(training_counts_by_id) <= 4096
        and all(type(identity) is str and type(count) is int and 1 <= count <= 32 for identity, count in training_counts_by_id.items())
        and {row["id"] for row in collection["source_rows"]} <= set(training_counts_by_id),
        "authenticated actual training counts1..32 required")
    sources = {row["id"]: row for row in collection["source_rows"]}
    selections = []
    for row in collection["rows"]:
        _check_deadline(deadline)
        selected = _select(row["available_sites"], training_counts_by_id[row["id"]], tables, site_policy)
        selections.append(dict(row, selected_sites=selected, selected_site_count=len(selected),
            ignored_site_count=len(row["available_sites"])-len(selected),
            replay_prefix_tokens=selected[-1]["position"]+1 if selected else 0))
    active = [row for row in selections if row["selected_sites"]]
    selected_total = sum(row["selected_site_count"] for row in selections)
    receipt = dict(schema=LOSS_SCHEMA, collection_sha256=collection["collection_sha256"],
        training_counts_sha256=core.digest(training_counts_by_id), rows=len(sources), active_rows=len(active),
        rows_without_sites=collection["rows_without_sites"], rows_without_selected_sites=len(sources)-len(active),
        available_sites=collection["available_sites"], selected_sites=selected_total,
        ignored_sites=collection["available_sites"]-selected_total, selection_policy=site_policy,
        site_cap_per_row=2 if site_policy == "first_last" else 1,
        reduction="mean_selected_sites_within_row_then_mean_active_rows", vocabulary_size=len(codec["target_vocabulary"]),
        full_vocabulary_cross_entropy=True, reference_counts_used_only_in_loss=True,
        target_prefixes_used=False, student_generated_prefix_replay=True, additional_optimizer_steps=0,
        rows_replayed_once=True, gradient_scope=gradient_scope, events=[], row_losses=[], stop_labels=0,
        continue_labels=0, replay_prefix_tokens=0, mean_loss=None, replay_logits_match_collection=True,
        replay_logits_atol=REPLAY_ATOL, replay_logits_rtol=REPLAY_RTOL, maximum_replay_logit_absolute_difference=0., **FALSE)
    receipt["generation"] = dict(max_target_tokens=collection["max_target_tokens"], batch_size=collection["batch_size"],
        greedy_batch_steps=collection["greedy_batch_steps"], elapsed_seconds=collection["elapsed_seconds"],
        model_tensor_sha256=collection["model_tensor_sha256"], source_contexts_sha256=collection["source_contexts_sha256"],
        source_only=True, reference_count_access=False, site_policy_access=False, complete_rollout_before_site_selection=True,
        rows=[dict(**row, prediction=prediction, input_sha256=core.digest(sources[row["id"]]["input"]),
            **({} if source_contexts is None else dict(source_context_sha256=core.digest(source_contexts[row["id"]]),
                source_text_sha256=source_contexts[row["id"]]["source_sha256"])))
            for row, prediction in zip(selections, collection["predictions"])])
    if not active:
        _check_deadline(deadline)
        receipt["elapsed_seconds"] = time.monotonic()-started
        return dict(loss=None, receipt=receipt)
    snapshot = _snapshot(model, torch)
    row_losses = []
    try:
        model.eval()
        for offset in range(0, len(active), collection["batch_size"]):
            _check_deadline(deadline)
            part = active[offset:offset+collection["batch_size"]]
            source_part = [sources[row["id"]] for row in part]
            prefixes = [row["consumed_prefix"][:row["replay_prefix_tokens"]] for row in part]
            width = max(map(len, prefixes))
            tokens = torch.tensor([prefix+[0]*(width-len(prefix)) for prefix in prefixes], dtype=torch.long)
            _, logits = core._logits(torch, model, legacy._data(torch, source_part, input_transform), tokens,
                len(codec["target_vocabulary"]), **core._source_context_kwargs(torch, source_part, source_contexts, input_transform))
            _check_deadline(deadline)
            for index, row in enumerate(part):
                sites, count = row["selected_sites"], training_counts_by_id[row["id"]]
                targets = [tables[0]["," if site["completed_rules"] < count else "]"] for site in sites]
                observed = logits[index, [site["position"] for site in sites]]
                original = torch.tensor([site["collection_logits"] for site in sites], dtype=observed.dtype)
                _require(torch.allclose(observed.detach(), original, atol=REPLAY_ATOL, rtol=REPLAY_RTOL),
                    "replayed boundary logits differ from actual collected decisions")
                receipt["maximum_replay_logit_absolute_difference"] = max(receipt["maximum_replay_logit_absolute_difference"],
                    float((observed.detach()-original).abs().max()))
                losses = torch.nn.functional.cross_entropy(observed, torch.tensor(targets, dtype=torch.long), reduction="none")
                _require(core._finite(torch, losses), "nonfinite generated boundary loss")
                row_losses.append(losses.mean())
                receipt["row_losses"].append(dict(id=row["id"], sites=len(sites), mean_ce=float(losses.mean().detach())))
                receipt["replay_prefix_tokens"] += row["replay_prefix_tokens"]
                for site, target, ce, raw_logits in zip(sites, targets, losses.detach().tolist(), observed.detach().tolist()):
                    stop = site["completed_rules"] >= count
                    receipt["stop_labels" if stop else "continue_labels"] += 1
                    receipt["events"].append(dict(id=row["id"], position=site["position"], completed_rules=site["completed_rules"],
                        actual_next_token_id=site["actual_next_token_id"], training_count=count, target_token_id=target,
                        consumed_prefix_length=site["position"]+1,
                        consumed_prefix_sha256=core.digest(row["consumed_prefix"][:site["position"]+1]),
                        action="stop" if stop else "continue", cross_entropy=ce, replay_logits=raw_logits,
                        mean_loss_coefficient=1./len(active)/len(sites)))
        loss = torch.stack(row_losses).mean()
        _require(core._finite(torch, loss), "nonfinite mean boundary loss")
        receipt["mean_loss"] = float(loss.detach())
    finally:
        _preserved(model, torch, snapshot)
    _check_deadline(deadline)
    receipt["elapsed_seconds"] = time.monotonic()-started
    return dict(loss=loss, receipt=receipt)
