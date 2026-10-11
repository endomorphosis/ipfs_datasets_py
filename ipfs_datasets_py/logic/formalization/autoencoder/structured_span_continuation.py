"""Explicit objective continuation of an exact retained source-span checkpoint.

The current state has its own schema: it is never serialized as a legacy span
checkpoint. Only a private, temporary topology view enters the retained restore
and greedy decoder helpers. Historical constructor ``loss``/``from_scratch``
strings describe topology, not this continuation's objective or initialization.
Targets remain external authored supervision; copying and geometry confer no
legal authority. Torch is imported only by explicit numerical operations.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import stat
import time

SCHEMA = "objective-resumed-source-span-checkpoint/v1"
LINEAGE_ID = "objective_resumed_source_span_v1"
OBJECTIVE_SCHEMA = "source-span-order-overlap-probability/v1"
MAX_BYTES = 128 * 1024 * 1024
MAX_NEW_STEPS = 32
TRAIN_COUNT, TUNING_COUNT, BATCH_SIZE = 1152, 96, 12
INHERITED_STEPS, INITIAL_EPOCH, INITIAL_CURSOR = 400, 4, 192
SPAN_FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
OPTIONAL_FIELDS = ("object", "conditions", "exceptions", "temporal")
FALSE = dict(qualified=False, admitted=False, formalized=False, roundtrip_ok=False,
    proof_authority=False, semantic_correctness_verified=False,
    promotion_performed=False, publication_performed=False)
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_INITIALIZATION = dict(mode="exact_retained_warm_parent_model_and_full_Adam_resumption",
    all_parent_model_tensors_copied=True, parent_optimizer_moments_transferred=True,
    parent_epoch_and_cursor_transferred=True, fresh_optimizer=False,
    historical_parent_hash_scope="canonical_checkpoint_digest; original_file_bytes_require_separate_caller_pin",
    legacy_config_scope="historical_constructor_and_topology_only; outer_objective_and_lineage_are_authoritative")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def _wire(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("finite bounded checkpoint JSON required") from error
    _require(len(raw) <= MAX_BYTES, "checkpoint exceeds byte bound")
    return raw


def digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _hash(value, label):
    _require(type(value) is str and _SHA.fullmatch(value), "invalid " + label + " hash")


def _owners():
    # No numerical dependency is imported by this module's import itself.
    from ....optimizers.logic_theorem_optimizer import legal_span_formula as span
    from ....optimizers.logic_theorem_optimizer import legal_span_continuation as warm
    from ...legal_ir import structured_span_objective as objective
    return span, warm, objective


def _implementation():
    _require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_SHA,
        "worker source changed since import")
    span, warm, objective = _owners()
    return dict(worker_sha256=_SELF_SHA, base_span=span._implementation(),
        retained_warm_owner=warm._implementation(),
        objective_sha256=hashlib.sha256(Path(objective.__file__).read_bytes()).hexdigest())


def _objective(weight):
    _require(type(weight) in (int, float) and math.isfinite(weight) and weight in (0., .1),
        "only predeclared CE0 or probability0.1 objective weights permitted")
    return dict(schema=OBJECTIVE_SCHEMA, structure_weight=float(weight),
        base_ce="equal_facet_modality_presence_mean_start_end/v1",
        total="CE + weight * (validity + overlap) / 2",
        active_fields="authored_reference_presence_only; actor_and_action_required",
        accumulator="float64_probability_terms_from_CPU_float32_heads",
        authority="authored_engineering_geometry; no_legal_semantic_qualification")


def _moment_state(state, absolute_steps):
    _closed(state, {"model_state", "optimizer_state"}, "current numerical state")
    weights = state["model_state"]
    _require(type(weights) is dict and weights, "model state required")
    optimizer = state["optimizer_state"]
    _closed(optimizer, {"schema", "parameters"}, "Adam state")
    _require(optimizer["schema"] == "adam-default-betas-eps/v1" and
        type(optimizer["parameters"]) is dict and set(optimizer["parameters"]) == set(weights),
        "full inherited Adam parameter identity differs")

    def finite(value, nonnegative=False):
        if type(value) is list:
            _require(value, "empty model/moment tensor dimension")
            for item in value:
                finite(item, nonnegative)
        else:
            _require(type(value) in (int, float) and math.isfinite(value)
                and abs(value) <= 3.4028234e38 and (not nonnegative or value >= 0),
                "nonfinite or invalid float32 model/moment value")

    for value in weights.values():
        finite(value)
    for name, moment in optimizer["parameters"].items():
        _closed(moment, {"step", "exp_avg", "exp_avg_sq"}, "Adam parameter moment")
        _require(type(moment["step"]) is int and moment["step"] == absolute_steps,
            "absolute Adam moment step differs")
        finite(moment["exp_avg"])
        finite(moment["exp_avg_sq"], True)


def _parent_metadata(parent, expected_sha256):
    """Check canonical parent digest; external file-byte custody is caller-owned."""
    span, warm, _ = _owners()
    fields = {"schema", "lineage_id", "initialization", "implementation", "source_parent_checkpoint",
        "source_parent_checkpoint_sha256", "source_parent_optimizer_steps", "initial_model_state_sha256",
        "initial_base_checkpoint_sha256", "context_contract", "context_contract_sha256", "base_checkpoint",
        "parent_checkpoint_sha256", *FALSE}
    _closed(parent, fields, "historical warm parent")
    _hash(expected_sha256, "expected parent")
    _require(digest(parent) == expected_sha256, "exact historical parent hash differs")
    _require(parent["schema"] == warm.SCHEMA and parent["lineage_id"] == warm.LINEAGE_ID
        and all(parent[k] is False for k in FALSE), "retained warm parent schema/authority differs")
    _require(parent["implementation"] == warm._implementation()
        and parent["initialization"] == warm._INITIALIZATION, "retained warm parent owner/provenance differs")
    base_fields = {"schema", "lineage_id", "config", "implementation", "training_manifest_sha256",
        "training_count", "tuning_manifest_sha256", "tuning_count", "model_state", "optimizer_state",
        "progress", "parent_checkpoint_sha256", *FALSE}
    source = parent["source_parent_checkpoint"]
    _closed(source, base_fields, "historical original source parent")
    _closed(source["progress"], {"epochs_completed", "row_cursor", "optimizer_steps"}, "historical source progress")
    _require(source["schema"] == span.SCHEMA and source["lineage_id"] == span.LINEAGE_ID
        and source["implementation"] == span._implementation() and all(source[k] is False for k in FALSE),
        "historical original source owner/schema/authority differs")
    _require(type(source) is dict and parent["source_parent_checkpoint_sha256"] == digest(source)
        and type(parent["source_parent_optimizer_steps"]) is int
        and parent["source_parent_optimizer_steps"] == source.get("progress", {}).get("optimizer_steps")
        and parent["source_parent_optimizer_steps"] > 0
        and parent["initial_model_state_sha256"] == digest(source.get("model_state")),
        "historical source parent identities differ")
    base = parent["base_checkpoint"]
    _closed(base, base_fields, "historical span base")
    _require(base["schema"] == span.SCHEMA and base["lineage_id"] == span.LINEAGE_ID
        and all(base[k] is False for k in FALSE) and base["implementation"] == span._implementation(),
        "historical base schema/owner/authority differs")
    config = base["config"]
    _require(type(config) is dict and config.get("seed") == 1729 and type(config.get("seed")) is int
        and config.get("batch_size") == BATCH_SIZE and type(config.get("batch_size")) is int
        and config.get("latent_dimension") == 384 and type(config.get("latent_dimension")) is int
        and type(config.get("latent_enabled")) is bool and config.get("learning_rate") == .001
        and config.get("device") == "cpu" and config.get("dtype") == "float32"
        and config.get("initialization") == "from_scratch"
        and config.get("loss") == "equal_facet_modality_presence_mean_start_end/v1",
        "retained pilot topology/configuration differs")
    _require(type(base["training_count"]) is int and base["training_count"] == TRAIN_COUNT
        and type(base["tuning_count"]) is int and base["tuning_count"] == TUNING_COUNT,
        "retained authored TRAIN/TUNE population differs")
    _require(base["progress"] == dict(epochs_completed=INITIAL_EPOCH,
        row_cursor=INITIAL_CURSOR, optimizer_steps=INHERITED_STEPS)
        and all(type(v) is int for v in base["progress"].values()), "retained400/e4/c192 boundary differs")
    _moment_state({k: base[k] for k in ("model_state", "optimizer_state")}, INHERITED_STEPS)
    _require(parent["context_contract_sha256"] == digest(parent["context_contract"])
        and warm._context_contract(parent["context_contract"])["dimension"] == 384,
        "retained context identity differs")
    for key in ("training_manifest_sha256", "tuning_manifest_sha256"):
        _hash(base[key], key)
    reconstructed = warm._initial_base(base, source)
    _require(parent["initial_base_checkpoint_sha256"] == digest(reconstructed),
        "historical warm initialization binding differs")
    _hash(parent["parent_checkpoint_sha256"], "historical previous warm checkpoint")
    return base


def validate_checkpoint(checkpoint):
    """Validate bounded inert metadata/state; explicit open validates Torch shapes."""
    fields = {"schema", "lineage_id", "implementation", "objective", "initialization",
        "historical_parent", "historical_parent_sha256", "context_contract", "context_contract_sha256",
        "training_manifest_sha256", "training_count", "tuning_manifest_sha256", "tuning_count",
        "initial_model_state_sha256", "initial_optimizer_state_sha256", "state", "progress",
        "previous_checkpoint_sha256", *FALSE}
    _closed(checkpoint, fields, "objective continuation checkpoint")
    _wire(checkpoint)
    _require(checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID
        and all(checkpoint[k] is False for k in FALSE), "distinct continuation schema/authority differs")
    _require(checkpoint["implementation"] == _implementation()
        and _wire(checkpoint["initialization"]) == _wire(_INITIALIZATION), "worker implementation/initialization differs")
    objective = checkpoint["objective"]
    _require(type(objective) is dict and "structure_weight" in objective
        and _wire(objective) == _wire(_objective(objective["structure_weight"])), "authoritative probability objective differs")
    parent = _parent_metadata(checkpoint["historical_parent"], checkpoint["historical_parent_sha256"])
    for name in ("training_manifest_sha256", "training_count", "tuning_manifest_sha256", "tuning_count"):
        _require(type(checkpoint[name]) is type(parent[name]) and checkpoint[name] == parent[name],
            "inherited manifest/count differs: " + name)
    _require(checkpoint["context_contract"] == checkpoint["historical_parent"]["context_contract"]
        and checkpoint["context_contract_sha256"] == digest(checkpoint["context_contract"]),
        "inherited source context contract differs")
    for key, state_key in (("initial_model_state_sha256", "model_state"),
                           ("initial_optimizer_state_sha256", "optimizer_state")):
        _require(checkpoint[key] == digest(parent[state_key]), "initial full parent state identity differs")
    progress = checkpoint["progress"]
    _closed(progress, {"inherited_optimizer_steps", "new_optimizer_steps", "absolute_optimizer_steps",
        "epochs_completed", "row_cursor"}, "objective continuation progress")
    _require(all(type(v) is int and 0 <= v <= 10**9 for v in progress.values()), "integer progress required")
    _require(progress["inherited_optimizer_steps"] == INHERITED_STEPS
        and 0 <= progress["new_optimizer_steps"] <= MAX_NEW_STEPS
        and progress["absolute_optimizer_steps"] == INHERITED_STEPS + progress["new_optimizer_steps"],
        "inherited/new/absolute optimizer counters differ")
    cursor = progress["row_cursor"]
    _require(cursor < TRAIN_COUNT and cursor % BATCH_SIZE == 0 and progress["absolute_optimizer_steps"] ==
        progress["epochs_completed"] * (TRAIN_COUNT // BATCH_SIZE) + cursor // BATCH_SIZE,
        "absolute optimizer/epoch/cursor identity differs")
    _moment_state(checkpoint["state"], progress["absolute_optimizer_steps"])
    previous = checkpoint["previous_checkpoint_sha256"]
    if progress["new_optimizer_steps"]:
        _hash(previous, "previous objective checkpoint")
    else:
        _require(previous is None and checkpoint["state"] == {k: parent[k] for k in
            ("model_state", "optimizer_state")}, "zero-new-step state must equal complete retained parent")
    return deepcopy(checkpoint)


def prepare_checkpoint(parent, training_examples, tuning_examples, *, structure_weight,
                       expected_parent_sha256, expected_training_sha256, expected_tuning_sha256):
    """Fork an exact parent with full Adam400 and original schedule, without fit.

    ``expected_parent_sha256`` is ``digest(parent)``, a canonical checkpoint
    digest. It is NOT the SHA of arbitrary original on-disk JSON serialization;
    callers must separately authenticate that original file's bytes and path.
    TRAIN/TUNE hashes are likewise canonical example-manifest digests.
    """
    base = _parent_metadata(parent, expected_parent_sha256)
    for examples, expected, field, count in ((training_examples, expected_training_sha256,
            "training_manifest_sha256", TRAIN_COUNT), (tuning_examples, expected_tuning_sha256,
            "tuning_manifest_sha256", TUNING_COUNT)):
        _hash(expected, field)
        _require(type(examples) in (list, tuple) and len(examples) == count
            and digest(examples) == expected == base[field], "exact authored split manifest differs")
    span, _, objective = _owners()
    records, tuning = span._splits(training_examples, tuning_examples, 384)
    for population in (records, tuning):
        for offset in range(0, len(population), BATCH_SIZE):
            objective.reference_geometry(population[offset:offset + BATCH_SIZE])
    result = dict(schema=SCHEMA, lineage_id=LINEAGE_ID, implementation=_implementation(),
        objective=_objective(structure_weight), initialization=deepcopy(_INITIALIZATION),
        historical_parent=deepcopy(parent), historical_parent_sha256=expected_parent_sha256,
        context_contract=deepcopy(parent["context_contract"]),
        context_contract_sha256=parent["context_contract_sha256"],
        training_manifest_sha256=expected_training_sha256, training_count=TRAIN_COUNT,
        tuning_manifest_sha256=expected_tuning_sha256, tuning_count=TUNING_COUNT,
        initial_model_state_sha256=digest(base["model_state"]),
        initial_optimizer_state_sha256=digest(base["optimizer_state"]),
        state={k: deepcopy(base[k]) for k in ("model_state", "optimizer_state")},
        progress=dict(inherited_optimizer_steps=INHERITED_STEPS, new_optimizer_steps=0,
            absolute_optimizer_steps=INHERITED_STEPS, epochs_completed=INITIAL_EPOCH, row_cursor=INITIAL_CURSOR),
        previous_checkpoint_sha256=None, **FALSE)
    validate_checkpoint(result)
    return result


def _base_view(checkpoint):
    """Private restore/greedy topology adapter; never published as legacy state."""
    base = deepcopy(checkpoint["historical_parent"]["base_checkpoint"])
    base.update(deepcopy(checkpoint["state"]))
    p = checkpoint["progress"]
    base["progress"] = dict(epochs_completed=p["epochs_completed"], row_cursor=p["row_cursor"],
        optimizer_steps=p["absolute_optimizer_steps"])
    return base


def _bound_examples(checkpoint, examples, *, tuning=False):
    field = "tuning" if tuning else "training"
    _require(type(examples) in (list, tuple) and len(examples) == checkpoint[field + "_count"]
        and digest(examples) == checkpoint[field + "_manifest_sha256"], "bound " + field + " examples differ")


def next_batch_ids(checkpoint, training_examples, *, steps=1):
    """Pure ordered schedule witness; CE/structured arms share exact batches."""
    validate_checkpoint(checkpoint)
    _bound_examples(checkpoint, training_examples)
    _require(type(steps) is int and 0 <= steps <= MAX_NEW_STEPS
        and checkpoint["progress"]["new_optimizer_steps"] + steps <= MAX_NEW_STEPS, "bounded new step count required")
    epoch, cursor = checkpoint["progress"]["epochs_completed"], checkpoint["progress"]["row_cursor"]
    schedule = []
    for _ in range(steps):
        order = list(range(TRAIN_COUNT))
        random.Random(1729 + epoch).shuffle(order)
        indices = order[cursor:cursor + BATCH_SIZE]
        schedule.append([training_examples[index]["id"] for index in indices])
        cursor += len(indices)
        if cursor == TRAIN_COUNT:
            epoch, cursor = epoch + 1, 0
    return schedule


def _seconds(value):
    _require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 300,
        "soft seconds must be within0..300")


def _components(torch, result):
    keys = ("ce", "validity", "overlap", "structure", "weighted_structure", "total")
    _require(type(result) is dict and all(key in result for key in keys), "objective components missing")
    values = {}
    for key in keys:
        value = result[key]
        _require(torch.is_tensor(value) and value.numel() == 1 and bool(torch.isfinite(value).all()),
            "nonfinite objective component: " + key)
        values[key] = float(value.detach())
    return values


def _restore_current(checkpoint):
    span, warm, _ = _owners()
    warm.validate_checkpoint(checkpoint["historical_parent"])
    torch, model, optimizer = span._restore(_base_view(checkpoint))
    weights, moments = span._pack(model, optimizer)
    _require(weights == checkpoint["state"]["model_state"] and moments == checkpoint["state"]["optimizer_state"],
        "exact restore changed model/Adam representation")
    return torch, model, optimizer


def train_decoder(checkpoint, training_examples, tuning_examples, *, max_steps=32, max_seconds=60):
    """Bounded actual updates using one unchanged forward and explicit objective."""
    validate_checkpoint(checkpoint)
    _bound_examples(checkpoint, training_examples)
    _bound_examples(checkpoint, tuning_examples, tuning=True)
    _require(type(max_steps) is int and 0 <= max_steps <= MAX_NEW_STEPS
        and checkpoint["progress"]["new_optimizer_steps"] + max_steps <= MAX_NEW_STEPS,
        "at most32 total new updates permitted")
    _seconds(max_seconds)
    span, _, objective = _owners()
    records, _ = span._splits(training_examples, tuning_examples, 384)
    schedule = next_batch_ids(checkpoint, training_examples, steps=max_steps)
    by_id = {row["id"]: index for index, row in enumerate(training_examples)}
    import torch
    ambient = torch.get_rng_state().clone()
    started = time.monotonic()
    deadline = started + max_seconds
    losses, batches, gradient_max = [], [], 0.
    progress = deepcopy(checkpoint["progress"])
    reason = "step_limit"
    with torch.random.fork_rng(devices=[]):
        _, model, optimizer = _restore_current(checkpoint)
        for identifiers in schedule:
            if time.monotonic() >= deadline:
                reason = "deadline_before_batch"
                break
            batch = [records[by_id[identifier]] for identifier in identifiers]
            model.train()
            optimizer.zero_grad(set_to_none=True)
            output = model(*span._batch(torch, batch))
            result = objective.objective_from_output(torch, output, batch,
                structure_weight=checkpoint["objective"]["structure_weight"])
            components = _components(torch, result)
            result["total"].backward()
            parameters = list(model.parameters())
            _require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all())
                for parameter in parameters), "missing/nonfinite gradients")
            gradient_max = max(gradient_max, float(torch.nn.utils.clip_grad_norm_(parameters, 5., error_if_nonfinite=True)))
            optimizer.step()
            _require(all(bool(torch.isfinite(parameter).all()) for parameter in parameters), "nonfinite updated parameters")
            _require(all(bool(torch.isfinite(value).all()) for moment in optimizer.state.values()
                for value in moment.values() if torch.is_tensor(value)), "nonfinite Adam moments")
            progress["new_optimizer_steps"] += 1
            progress["absolute_optimizer_steps"] += 1
            progress["row_cursor"] += len(identifiers)
            if progress["row_cursor"] == TRAIN_COUNT:
                progress["epochs_completed"] += 1
                progress["row_cursor"] = 0
            losses.append(components)
            batches.append(list(identifiers))
        model.eval()
        weights, moments = span._pack(model, optimizer)
    _require(torch.equal(torch.get_rng_state(), ambient), "ambient CPU RNG changed")
    if losses:
        updated = {**deepcopy(checkpoint), "state": dict(model_state=weights, optimizer_state=moments),
            "progress": progress, "previous_checkpoint_sha256": digest(checkpoint)}
    else:
        _require(weights == checkpoint["state"]["model_state"] and moments == checkpoint["state"]["optimizer_state"],
            "zero-update restore changed model/moments")
        updated = deepcopy(checkpoint)
    validate_checkpoint(updated)
    _require(digest(updated["historical_parent"]) == checkpoint["historical_parent_sha256"], "historical parent changed")
    report = dict(schema="objective-resumed-source-span-training/v1", lineage_id=LINEAGE_ID,
        checkpoint_sha256=digest(updated), previous_checkpoint_sha256=digest(checkpoint),
        historical_parent_sha256=checkpoint["historical_parent_sha256"], objective=deepcopy(checkpoint["objective"]),
        actual_new_updates=len(losses), requested_new_updates=max_steps,
        actual_TRAIN_rows=sum(map(len, batches)), batch_ids=batches, batch_ids_sha256=digest(batches),
        batch_components=losses, progress=deepcopy(progress), gradient_norm_max=gradient_max,
        complete=len(losses) == max_steps, stopped_reason=reason, training_executed=bool(losses),
        changed_parameter_names=[name for name, value in weights.items() if value != checkpoint["state"]["model_state"][name]],
        inherited_full_Adam_preserved_at_entry=True, historical_parent_unchanged=True,
        ambient_CPU_RNG_preserved=True, tuning_used_for_updates=False, targets_embedded_in_new_state=False,
        elapsed_seconds=time.monotonic() - started,
        deadline_scope="soft_check_before_each_batch; restore_forward_backward_pack_not_interruptible", **FALSE)
    return dict(checkpoint=updated, report=report)


def evaluate(checkpoint, tuning_examples, *, max_seconds=60):
    """Labeled authored TUNE loss only; never used for updates by this worker."""
    validate_checkpoint(checkpoint)
    _bound_examples(checkpoint, tuning_examples, tuning=True)
    _seconds(max_seconds)
    span, _, objective = _owners()
    records, _, _ = span._records(tuning_examples, 384)
    import torch
    ambient = torch.get_rng_state().clone()
    started = time.monotonic()
    deadline = started + max_seconds
    totals = {key: 0. for key in ("ce", "validity", "overlap", "structure", "weighted_structure", "total")}
    measured, batches = 0, []
    with torch.random.fork_rng(devices=[]):
        _, model, _ = _restore_current(checkpoint)
        model.eval()
        with torch.no_grad():
            for offset in range(0, len(records), BATCH_SIZE):
                if time.monotonic() >= deadline:
                    break
                batch = records[offset:offset + BATCH_SIZE]
                output = model(*span._batch(torch, batch))
                result = objective.objective_from_output(torch, output, batch,
                    structure_weight=checkpoint["objective"]["structure_weight"])
                components = _components(torch, result)
                for key, value in components.items():
                    totals[key] += value * len(batch)
                measured += len(batch)
                batches.append(components)
    _require(torch.equal(torch.get_rng_state(), ambient), "ambient CPU RNG changed")
    _require(_implementation() == checkpoint["implementation"], "worker source changed during authored evaluation")
    return dict(schema="objective-resumed-source-span-authored-evaluation/v1", checkpoint_sha256=digest(checkpoint),
        objective=deepcopy(checkpoint["objective"]), rows_evaluated=measured, expected_rows=TUNING_COUNT,
        complete=measured == TUNING_COUNT, losses={key: value / measured if measured else None for key, value in totals.items()},
        batch_components=batches, teacher_forcing=True, reference_access=True, used_for_updates=False,
        training_executed=False, ambient_CPU_RNG_preserved=True,
        elapsed_seconds=time.monotonic() - started, semantics="exposed_authored_construction_targets_only", **FALSE)


class StructuredSpanRuntime:
    """Opened new-lineage state; inference accepts no target/reference fields."""
    def __init__(self, checkpoint):
        validate_checkpoint(checkpoint)
        self._checkpoint = deepcopy(checkpoint)
        self.checkpoint_sha256 = digest(checkpoint)
        import torch
        ambient = torch.get_rng_state().clone()
        with torch.random.fork_rng(devices=[]):
            self.torch, self.model, self.optimizer = _restore_current(checkpoint)
        _require(torch.equal(torch.get_rng_state(), ambient), "ambient CPU RNG changed on open")

    @property
    def checkpoint(self):
        return deepcopy(self._checkpoint)

    def infer(self, source_rows, *, control="none", capture_scores=True):
        _require(type(source_rows) is list and 1 <= len(source_rows) <= 128,
            "one to128 source-only inference rows required")
        _require(type(capture_scores) is bool and control in ("none", "zero", "disabled", "rotate"), "inference control differs")
        _require(control != "rotate" or len(source_rows) > 1, "rotate requires multiple sources")
        _require(_implementation() == self._checkpoint["implementation"], "worker source drift")
        span, _, _ = _owners()
        vectors, seen = [], set()
        for row in source_rows:
            _closed(row, {"id", "source_text", "latent"}, "target-free source inference row")
            _require(type(row["id"]) is str and 0 < len(row["id"].strip()) <= 512 and row["id"] not in seen,
                "bounded unique source occurrence ID required")
            _require(type(row["source_text"]) is str and row["source_text"].strip(), "nonempty source text required")
            vectors.append(span._vector(row["latent"], 384))
            seen.add(row["id"])
        if control == "zero":
            vectors = [[0.] * 384 for _ in vectors]
        elif control == "rotate":
            vectors = vectors[1:] + vectors[:1]
        torch = self.torch
        ambient = torch.get_rng_state().clone()
        before_weights, before_moments = span._pack(self.model, self.optimizer)
        _require(before_weights == self._checkpoint["state"]["model_state"]
            and before_moments == self._checkpoint["state"]["optimizer_state"], "opened state differs from checkpoint")
        _require(not getattr(self.model, "_forward_hooks", {}) and not getattr(self.model, "_forward_pre_hooks", {}),
            "unmodified top-level model hooks required")
        # Allocate only the retained greedy implementation; its legacy report is
        # never exposed as the authoritative new-lineage outer report.
        decoder = object.__new__(span.SpanLegalFormulaDecoder)
        decoder.torch, decoder.model = torch, self.model
        decoder.checkpoint = _base_view(self._checkpoint)
        captures, rows = [], []
        current = [None]

        def hook(module, inputs, output):
            _require(module is self.model and type(output) is dict
                and set(output) == {"modality", "presence", "start", "end"}, "closed same-forward score heads required")
            tokens = current[0]
            _require(tokens is not None, "unexpected forward outside source row")
            size = len(tokens)
            shapes = {"modality": (1, 3), "presence": (1, 4, 2), "start": (1, 6, size), "end": (1, 6, size)}
            for name, value in output.items():
                _require(tuple(value.shape) == shapes[name] and str(value.dtype) == "torch.float32"
                    and value.device.type == "cpu" and not value.requires_grad and bool(torch.isfinite(value).all()),
                    "finite same-forward CPU float32 score geometry required")
            captures.append(dict(schema="joint-source-span-scores/v1",
                tokens=[{key: token[key] for key in ("text", "start", "end")} for token in tokens],
                modality_logits=output["modality"][0].detach().tolist(),
                presence_logits=dict(zip(OPTIONAL_FIELDS, output["presence"][0].detach().tolist(), strict=True)),
                start_logits=dict(zip(SPAN_FIELDS, output["start"][0].detach().tolist(), strict=True)),
                end_logits=dict(zip(SPAN_FIELDS, output["end"][0].detach().tolist(), strict=True))))
            return None

        handle = self.model.register_forward_hook(hook) if capture_scores else None
        try:
            with torch.random.fork_rng(devices=[]):
                for position, (row, vector) in enumerate(zip(source_rows, vectors, strict=True)):
                    try:
                        tokens = span.tokenize_source(row["source_text"])
                    except ValueError:
                        tokens = None
                    current[0] = tokens
                    offset = len(captures)
                    raw = span.SpanLegalFormulaDecoder._decode(decoder, row["source_text"], vector, enabled=control != "disabled")
                    expected_forward = int(tokens is not None)
                    _require(not capture_scores or len(captures) == offset + expected_forward, "same-forward capture count differs")
                    donor = (position + 1) % len(source_rows) if control == "rotate" else position
                    rows.append(dict(id=row["id"], position=position,
                        source_sha256=hashlib.sha256(row["source_text"].encode("utf-8")).hexdigest(),
                        effective_latent_sha256=digest(vector), latent_donor_id=source_rows[donor]["id"],
                        latent_donor_position=donor, decoder_row=raw,
                        scores=deepcopy(captures[-1]) if capture_scores and expected_forward else None))
        finally:
            if handle is not None:
                handle.remove()
            _require(not getattr(self.model, "_forward_hooks", {}), "temporary capture hook remained")
        after_weights, after_moments = span._pack(self.model, self.optimizer)
        _require(after_weights == before_weights and after_moments == before_moments, "inference changed model/Adam state")
        _require(torch.equal(torch.get_rng_state(), ambient), "inference changed ambient CPU RNG")
        _require(_implementation() == self._checkpoint["implementation"], "worker source changed during inference")
        return dict(schema="objective-resumed-source-span-inference/v1", lineage_id=LINEAGE_ID,
            checkpoint_sha256=self.checkpoint_sha256, historical_parent_sha256=self._checkpoint["historical_parent_sha256"],
            objective=deepcopy(self._checkpoint["objective"]), progress=deepcopy(self._checkpoint["progress"]),
            rows=rows, control=control, same_forward_scores=capture_scores, additional_model_forwards=0,
            actual_source_forwards=sum(row["decoder_row"].get("reason") not in
                ("source_too_long", "source_encoding_rejected") for row in rows),
            weights_unchanged=True, optimizer_moments_unchanged=True, ambient_CPU_RNG_preserved=True,
            training_executed=False, optimizer_updates=0, target_access=False, teacher_forcing=False,
            native_encoder_executed=False, legal_accuracy=None, family_bridge_admitted=False, Lake_executed=False, **FALSE)


def open_checkpoint(checkpoint):
    return StructuredSpanRuntime(checkpoint)


def save_checkpoint(checkpoint, path):
    validate_checkpoint(checkpoint)
    raw = _wire(checkpoint)
    path = Path(path).absolute()
    _require(path.parent.resolve(strict=True) == path.parent, "canonical existing output parent required")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), schema=SCHEMA)


def load_checkpoint(path, *, expected_sha256):
    """Read this new schema against an exact file-byte SHA, then validate it."""
    _hash(expected_sha256, "expected file")
    path = Path(path).absolute()
    _require(path.resolve(strict=True) == path, "canonical input checkpoint required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= MAX_BYTES,
            "bounded regular independent checkpoint required")
        raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    _require(len(raw) <= MAX_BYTES and (before.st_size, before.st_mtime_ns, before.st_ino) ==
        (after.st_size, after.st_mtime_ns, after.st_ino), "checkpoint changed while reading")
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "checkpoint file hash differs")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate checkpoint JSON key")
            result[key] = value
        return result

    def reject(value):
        raise ValueError("invalid JSON constant: " + value)

    result = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    validate_checkpoint(result)
    return result


__all__ = ["SCHEMA", "LINEAGE_ID", "OBJECTIVE_SCHEMA", "digest", "prepare_checkpoint",
    "validate_checkpoint", "next_batch_ids", "train_decoder", "evaluate", "StructuredSpanRuntime",
    "open_checkpoint", "save_checkpoint", "load_checkpoint"]
