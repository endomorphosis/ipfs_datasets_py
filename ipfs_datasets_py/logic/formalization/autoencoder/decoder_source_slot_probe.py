"""Source-only fixed ridge probes of frozen representations, development only.

Eight complete scalar slots (including a structural ABSENT class) and an
independent count are always predicted. References never enter ``predict_probe``.
This does not train a decoder, produce formulas, or establish source fidelity for
unscored qualifiers. Global training RMS makes mean centered row norm squared
one across representation widths. Raw ridge scores are not probabilities.
"""
from copy import deepcopy
import hashlib
import math
import random
import time

from . import decoder_distillation_experiment as core
from . import decoder_source_fidelity as fidelity

SCHEMA = "decoder-source-slot-probe/v1"
FIELDS = ("actor", "action", "modality", "object")
MAX_SLOTS = 8
RIDGE_LAMBDA = .001
FALSE = dict(core.FALSE, decoder_training_executed=False, generation_executed=False,
    native_validation_executed=False, lake_executed=False, checkpoint_promoted=False,
    fresh_holdout=False, convergence_proven=False, encoder_context_changed=False,
    output_limit_changed=False, weight_selection_performed=False)
_require = core._require


def _clock(max_seconds, max_memory_bytes):
    _require(type(max_seconds) in (float, int) and math.isfinite(max_seconds) and 0 < max_seconds <= 300,
        "bounded positive probe deadline required")
    _require(type(max_memory_bytes) is int and 1048576 <= max_memory_bytes <= 8589934592,
        "bounded probe memory budget required")
    started = time.monotonic()
    def check():
        if time.monotonic() >= started+max_seconds:
            raise TimeoutError("source-slot probe deadline exceeded; no complete result")
    return started, check


def _features(rows, dimension):
    _require(type(rows) is list and 1 <= len(rows) <= 4096, "bounded nonempty feature rows required")
    seen = set()
    for row in rows:
        _require(type(row) is dict and set(row) == {"id", "source_sha256", "features"}, "closed feature row required")
        _require(type(row["id"]) is str and 0 < len(row["id"]) <= 512 and row["id"] not in seen,
            "unique bounded feature identity required")
        seen.add(row["id"])
        _require(type(row["source_sha256"]) is str and core._SHA.fullmatch(row["source_sha256"]),
            "feature source digest required")
        core._vector(row["features"], dimension)
    _require(len(core._raw(rows)) <= 67108864, "feature serialization exceeds bound")


def _spec(value):
    _require(type(value) is dict and set(value) == {"id", "kind", "dimension", "provenance"}, "closed feature specification required")
    dimensions = {"projected_source": 384, "conditioning": 48, "intercept": 0}
    _require(type(value["id"]) is str and 0 < len(value["id"]) <= 256
        and value["kind"] in dimensions and type(value["dimension"]) is int
        and value["dimension"] == dimensions[value["kind"]], "exact declared feature geometry required")
    _require(type(value["provenance"]) is dict and len(core._raw(value["provenance"])) <= 1048576,
        "bounded explicit feature provenance required")
    return value["dimension"]


def _references(features, references, validate_rule, validator_id):
    _require(type(references) is list and len(references) == len(features)
        and all(type(r) is dict and type(r.get("id")) is str for r in references), "complete reference rows required")
    _require(callable(validate_rule) and fidelity._name(validator_id), "explicit reference syntax validator required")
    _require(len(core._raw(references)) <= 67108864, "reference serialization exceeds bound")
    by_id = {r["id"]: r for r in references}
    _require(len(by_id) == len(references) and set(by_id) == {r["id"] for r in features}, "reference identities differ")
    for row in features:
        reference = by_id[row["id"]]
        source = reference.get("source_text")
        _require(type(source) is str and 0 < len(source.encode()) <= 1048576
            and hashlib.sha256(source.encode()).hexdigest() == row["source_sha256"]
            and reference.get("source_sha256", row["source_sha256"]) == row["source_sha256"],
            "reference source binding differs")
        target = reference.get("target")
        _require(type(target) is dict and set(target) == {"rules"} and type(target["rules"]) is list
            and 1 <= len(target["rules"]) <= MAX_SLOTS and type(reference.get("clause_count")) is int
            and reference["clause_count"] == len(target["rules"]), "complete reference exceeds eight-slot scope")
        _require(len(core._raw(target)) <= 1048576, "reference target exceeds bound")
        torch = core._torch()
        torch_rng, python_rng = torch.get_rng_state().clone(), random.getstate()
        try:
            for rule in target["rules"]:
                fidelity._rule(rule, validate_rule)
        finally:
            torch.set_rng_state(torch_rng); random.setstate(python_rng)
    return by_id


def _heads(references):
    inventories = {field: sorted({rule[field] for r in references for rule in r["target"]["rules"]}) for field in FIELDS}
    _require(all(1 <= len(v) <= 512 for v in inventories.values()), "bounded training-only facet inventories required")
    heads, offset = [], 0
    for slot in range(MAX_SLOTS):
        for field in FIELDS:
            classes = [dict(kind="absent")]+[dict(kind="value", value=v) for v in inventories[field]]
            heads.append(dict(name=f"slot:{slot}:{field}", slot_index=slot, field=field,
                start=offset, stop=offset+len(classes), classes=classes))
            offset += len(classes)
    classes = [dict(kind="count", value=i) for i in range(1, MAX_SLOTS+1)]
    heads.append(dict(name="count", slot_index=None, field=None, start=offset, stop=offset+len(classes), classes=classes))
    return heads, inventories


def _label(reference, head):
    if head["name"] == "count":
        return dict(kind="count", value=reference["clause_count"])
    slot = head["slot_index"]
    rules = reference["target"]["rules"]
    return dict(kind="value", value=rules[slot][head["field"]]) if slot < len(rules) else dict(kind="absent")


def _budget(n, dimension, columns, input_bytes, max_memory_bytes, *, fitting):
    # Python input copies/result floats + CPU float64 matrices/factorization.
    cells = n*dimension+n*columns+dimension*columns
    estimate = input_bytes*3+cells*120+(n*n*8*8 if fitting else 0)+1048576
    _require(estimate <= max_memory_bytes, "probe memory estimate exceeds budget")
    return estimate


def _seal(report, check, started):
    check()
    report["elapsed_seconds"] = time.monotonic()-started
    report["report_sha256"] = core.digest(report)
    check()
    return report


def fit_probe(feature_rows, references, *, feature_specification, validate_rule, validator_id,
        ridge_lambda=RIDGE_LAMBDA, max_seconds=30., max_memory_bytes=536870912):
    """Fit one fixed ridge protocol on training features/references only.

    Mean squared one-hot regression plus lambda*||W||²; intercept is unpenalized.
    No validation data, hyperparameter selection, decoder or pretrained model is
    accepted by this function. Float64 dual solve exports primal coefficients.
    """
    started, check = _clock(max_seconds, max_memory_bytes)
    _require(type(ridge_lambda) in (int, float) and ridge_lambda == RIDGE_LAMBDA,
        "this preregistered probe fixes mean-objective ridge lambda to .001")
    dimension = _spec(feature_specification)
    _features(feature_rows, dimension)
    by_id = _references(feature_rows, references, validate_rule, validator_id)
    ordered_refs = [by_id[r["id"]] for r in feature_rows]
    heads, inventories = _heads(ordered_refs)
    n, columns = len(feature_rows), heads[-1]["stop"]
    input_bytes = len(core._raw([feature_rows, references, feature_specification]))
    estimate = _budget(n, dimension, columns, input_bytes, max_memory_bytes, fitting=True)
    check()
    torch = core._torch()
    torch_rng, python_rng = torch.get_rng_state().clone(), random.getstate()
    try:
        with torch.inference_mode():
            x = torch.tensor([r["features"] for r in feature_rows], dtype=torch.float64).reshape(n, dimension)
            mean = x.mean(0)
            centered = x-mean
            energy = float(centered.square().sum()/n)
            _require(math.isfinite(energy) and energy >= 0, "nonfinite training feature energy")
            constant = energy == 0
            _require(not constant or not bool(centered.any()), "training RMS underflow")
            scale = 1. if constant else math.sqrt(energy)
            z = centered/scale
            labels = [[head["classes"].index(_label(r, head)) for head in heads] for r in ordered_refs]
            y = torch.zeros((n, columns), dtype=torch.float64)
            for i, row_labels in enumerate(labels):
                for head, label in zip(heads, row_labels):
                    y[i, head["start"]+label] = 1.
            bias = y.mean(0)
            yc = y-bias
            check()
            gram = z@z.T+n*ridge_lambda*torch.eye(n, dtype=torch.float64)
            condition_number = float(torch.linalg.cond(gram))
            dual = torch.linalg.solve(gram, yc)
            weights = z.T@dual
            check()
            residual = z.T@(z@weights-yc)/n+ridge_lambda*weights
            rhs = z.T@yc/n
            residual_max = float(residual.abs().max()) if residual.numel() else 0.
            rhs_max = float(rhs.abs().max()) if rhs.numel() else 0.
            tolerance = 1e-10*(1.+rhs_max)
            _require(all(bool(torch.isfinite(t).all()) for t in (weights, bias, residual))
                and math.isfinite(condition_number) and residual_max <= tolerance,
                "ridge normal-equation certificate failed")
            train_scores = z@weights+bias
            objective = float((train_scores-y).square().sum()/n+ridge_lambda*weights.square().sum())
            transform = dict(origin="training_only", mean=mean.tolist(), scale=scale,
                normalization="center_then_global_RMS_of_row_L2_norm", constant_training_features=constant,
                mean_training_centered_row_squared_norm=float(z.square().sum()/n))
            probe = dict(schema=SCHEMA, feature_specification=deepcopy(feature_specification),
                dimension=dimension, max_slots=MAX_SLOTS, fields=list(FIELDS), ridge_lambda=ridge_lambda,
                objective="sum_all_head_squared_errors_per_training_row_plus_lambda_frobenius_weight_squared",
                coefficients=weights.tolist(), intercept=bias.tolist(), coefficient_shape=[dimension, columns],
                heads=heads, training_facet_inventories=inventories, transform=transform,
                training_feature_rows_sha256=core.digest(feature_rows), training_references_sha256=core.digest(references),
                training_ids=[r["id"] for r in feature_rows], validator_id=validator_id,
                class_order="ABSENT first then training Unicode-sorted values; counts1..8; lowest index wins ties",
                inference_gold_count_access=False, inference_reference_prefix_access=False,
                score_interpretation="unconstrained ridge scores, not probabilities", **FALSE)
            probe["probe_sha256"] = core.digest(probe)
            report = dict(schema="decoder-source-slot-probe-fit/v1", complete=True, probe_sha256=probe["probe_sha256"],
                feature_specification=deepcopy(feature_specification), training_rows=n, feature_dimension=dimension,
                output_columns=columns, coefficient_shape=[dimension, columns], dtype="float64",
                raw_training_feature_matrix=x.tolist(), training_onehot_matrix=y.tolist(),
                training_row_ids=[r["id"] for r in feature_rows], training_class_indices=labels,
                training_feature_rows_sha256=core.digest(feature_rows), training_references_sha256=core.digest(references),
                transform=transform, heads=deepcopy(heads), coefficients=weights.tolist(), intercept=bias.tolist(),
                mean_objective=objective, ridge_lambda=ridge_lambda,
                normal_equation=dict(definition="Z.T@(Z@W-(Y-meanY))/n + lambda*W = 0",
                    max_abs_residual=residual_max, rhs_max_abs=rhs_max, absolute_tolerance=tolerance,
                    verified=True, strictly_convex_weight_objective=True),
                dual_condition_number=condition_number, dual_diagonal_regularizer=n*ridge_lambda,
                intercept_penalized=False, validation_rows_used_for_fitting=0,
                probe_fitting_executed=True, existing_model_weights_modified=False,
                memory_work_estimate_bytes=estimate, memory_estimate_excludes_python_import_allocator_rss=True,
                scope="training_only_fixed_linear_readout_diagnostic", **FALSE)
    finally:
        torch.set_rng_state(torch_rng); random.setstate(python_rng)
    report = _seal(report, check, started)
    return dict(probe=probe, report=report)


def _checked_probe(probe):
    _require(type(probe) is dict and probe.get("schema") == SCHEMA
        and probe.get("probe_sha256") == core.digest({k:v for k,v in probe.items() if k != "probe_sha256"}),
        "probe schema/digest differs")
    d = _spec(probe["feature_specification"])
    _require(probe.get("dimension") == d and probe.get("max_slots") == MAX_SLOTS
        and probe.get("fields") == list(FIELDS) and probe.get("ridge_lambda") == RIDGE_LAMBDA
        and all(probe.get(k) is False for k in FALSE), "probe geometry/policy differs")
    heads = probe["heads"]
    _require(type(heads) is list and len(heads) == MAX_SLOTS*len(FIELDS)+1, "complete eight-slot heads required")
    inventories = probe["training_facet_inventories"]
    _require(type(inventories) is dict and set(inventories) == set(FIELDS), "training-only field inventories required")
    offset = 0
    for i, head in enumerate(heads):
        slot, field = divmod(i, len(FIELDS))
        if i < MAX_SLOTS*len(FIELDS):
            name = FIELDS[field]
            values = inventories[name]
            _require(type(values) is list and 1 <= len(values) <= 512 and all(type(v) is str for v in values)
                and values == sorted(set(values)), "invalid training field classes")
            classes = [dict(kind="absent")]+[dict(kind="value", value=v) for v in values]
            expected = dict(name=f"slot:{slot}:{name}", slot_index=slot, field=name,
                start=offset, stop=offset+len(classes), classes=classes)
        else:
            classes = [dict(kind="count", value=j) for j in range(1, MAX_SLOTS+1)]
            expected = dict(name="count", slot_index=None, field=None, start=offset, stop=offset+8, classes=classes)
        _require(head == expected, "probe class inventory/head slices differ")
        offset = expected["stop"]
    _require(probe["coefficient_shape"] == [d, offset] and type(probe["coefficients"]) is list
        and len(probe["coefficients"]) == d, "coefficient shape differs")
    for row in probe["coefficients"]:
        core._vector(row, offset)
    core._vector(probe["intercept"], offset)
    transform = probe["transform"]
    _require(type(transform) is dict and set(transform) == {"origin", "mean", "scale", "normalization",
        "constant_training_features", "mean_training_centered_row_squared_norm"}
        and transform["origin"] == "training_only" and transform["normalization"] == "center_then_global_RMS_of_row_L2_norm"
        and type(transform["scale"]) in (int, float) and math.isfinite(transform["scale"]) and transform["scale"] > 0,
        "training-only normalization required")
    core._vector(transform["mean"], d)
    return d, offset


def predict_probe(probe, feature_rows, *, zero_features=False, max_seconds=30., max_memory_bytes=536870912):
    """Predict every slot and count, without references or a gold-count mask.

    ``zero_features`` zeros normalized features, equivalent to supplying the
    training feature mean. It is an intercept-prior control, not the historical
    decoder's zero-source wrapper. No source text/token prefixes are accepted.
    """
    started, check = _clock(max_seconds, max_memory_bytes)
    _require(type(zero_features) is bool, "explicit zero-feature control required")
    dimension, columns = _checked_probe(probe)
    _features(feature_rows, dimension)
    n = len(feature_rows)
    estimate = _budget(n, dimension, columns, len(core._raw([feature_rows, probe])), max_memory_bytes, fitting=False)
    check()
    torch = core._torch()
    torch_rng, python_rng = torch.get_rng_state().clone(), random.getstate()
    try:
        with torch.inference_mode():
            x = torch.tensor([r["features"] for r in feature_rows], dtype=torch.float64).reshape(n, dimension)
            mean = torch.tensor(probe["transform"]["mean"], dtype=torch.float64)
            z = torch.zeros_like(x) if zero_features else (x-mean)/probe["transform"]["scale"]
            weights = torch.tensor(probe["coefficients"], dtype=torch.float64).reshape(dimension, columns)
            intercept = torch.tensor(probe["intercept"], dtype=torch.float64)
            scores = z@weights+intercept
            _require(bool(torch.isfinite(scores).all()), "nonfinite source probe scores")
            check()
            predictions = []
            for row, values in zip(feature_rows, scores.tolist()):
                selected = [max(range(h["stop"]-h["start"]), key=lambda i: values[h["start"]+i]) for h in probe["heads"]]
                classes = [deepcopy(h["classes"][i]) for h,i in zip(probe["heads"], selected)]
                slots = [{field: classes[slot*4+j] for j,field in enumerate(FIELDS)} for slot in range(MAX_SLOTS)]
                count = classes[-1]["value"]
                consistent = all(all(v["kind"] == ("value" if i < count else "absent") for v in slot.values())
                    for i,slot in enumerate(slots))
                predictions.append(dict(id=row["id"], source_sha256=row["source_sha256"], scores=values,
                    class_indices=selected, slots=slots, predicted_count=count,
                    count_and_slot_presence_consistent=consistent))
            report = dict(schema="decoder-source-slot-probe-predictions/v1", complete=True,
                probe_sha256=probe["probe_sha256"], feature_rows_sha256=core.digest(feature_rows),
                rows=n, output_slots_per_row=MAX_SLOTS, gold_count_access=False, reference_prefix_access=False,
                zero_features=zero_features, zero_scope="normalized_zero_equals_training_mean_features_intercept_only",
                predictions_sha256=core.digest(predictions), score_dtype="float64",
                score_interpretation="unconstrained ridge scores, not probabilities",
                tie_policy="first class in preregistered class order", probe_fitting_executed=False,
                memory_work_estimate_bytes=estimate, memory_estimate_excludes_python_import_allocator_rss=True, **FALSE)
    finally:
        torch.set_rng_state(torch_rng); random.setstate(python_rng)
    return dict(report=_seal(report, check, started), predictions=predictions)


def _control(rows, source_rows, references, control, dimension):
    _features(rows, dimension); _features(source_rows, dimension)
    ids = [r["id"] for r in rows]
    _require([r["id"] for r in source_rows] == ids, "original feature identity/order differs")
    _require(type(control) is dict and set(control) == {"kind", "source_assignment"}
        and control["kind"] in ("conditioned", "source_shuffle", "cross_length_shuffle", "zero_features"),
        "closed feature-control descriptor required")
    assignment = control["source_assignment"]
    _require(type(assignment) is dict and set(assignment) == set(ids)
        and all(type(v) is str for v in assignment.values()) and set(assignment.values()) == set(ids),
        "control must preserve all source identities")
    shuffled = control["kind"] in ("source_shuffle", "cross_length_shuffle")
    originals = {r["id"]: r for r in source_rows}
    for row in rows:
        identity = row["id"]; assigned = assignment[identity]
        _require((assigned != identity) if shuffled else (assigned == identity), "control identity assignment differs")
        _require(row["source_sha256"] == originals[identity]["source_sha256"]
            and row["features"] == originals[assigned]["features"], "assigned source features differ")
        if shuffled:
            same = references[identity]["clause_count"] == references[assigned]["clause_count"]
            _require(same if control["kind"] == "source_shuffle" else not same, "control count stratum differs")
    return deepcopy(control)


def _summarize(rows):
    present = [s for r in rows for s in r["scalar_slots"] if s["expected"]["kind"] == "value"]
    absent = [s for r in rows for s in r["scalar_slots"] if s["expected"]["kind"] == "absent"]
    def score(items):
        correct = sum(s["correct"] for s in items)
        return dict(total=len(items), correct=correct, accuracy=correct/len(items) if items else None,
            out_of_training_inventory=sum(s["out_of_training_inventory"] for s in items))
    classes = {}
    for field in FIELDS:
        entries = [s for s in present if s["field"] == field]
        values = sorted({s["expected"]["value"] for s in entries})
        classes[field] = [dict(value=v, support=sum(s["expected"]["value"] == v for s in entries),
            correct=sum(s["expected"]["value"] == v and s["correct"] for s in entries),
            recall=sum(s["expected"]["value"] == v and s["correct"] for s in entries)/sum(s["expected"]["value"] == v for s in entries)) for v in values]
    return dict(rows=len(rows), gold_present_scalar_values=score(present), gold_absent_slots=score(absent),
        by_facet={field: score([s for s in present if s["field"] == field]) for field in FIELDS},
        by_slot_index={str(slot): score([s for s in present if s["slot_index"] == slot]) for slot in range(MAX_SLOTS)},
        per_class_recall=classes, count_correct=sum(r["count_correct"] for r in rows),
        count_by_class={str(k): dict(total=sum(r["expected_count"] == k for r in rows),
            correct=sum(r["expected_count"] == k and r["count_correct"] for r in rows)) for k in range(1,MAX_SLOTS+1)},
        scalar_slots_and_count_exact=sum(r["scalar_slots_and_count_exact"] for r in rows),
        count_and_slot_presence_consistent=sum(r["prediction"]["count_and_slot_presence_consistent"] for r in rows))


def evaluate_probe(probe, feature_rows, references, *, source_features, control, validate_rule, validator_id,
        max_seconds=30., max_memory_bytes=536870912):
    """Evaluate fixed source-only predictions; gold-present metrics are conditional.

    Full-slot/count exactness uses all eight unmasked predictions, including
    ABSENT and independent predicted count. It is not complete Legal IR fidelity:
    conditions, exceptions and temporal semantics are deliberately unscored.
    """
    started, check = _clock(max_seconds, max_memory_bytes)
    dimension, columns = _checked_probe(probe)
    _features(feature_rows, dimension)
    by_id = _references(feature_rows, references, validate_rule, validator_id)
    checked_control = _control(feature_rows, source_features, by_id, control, dimension)
    estimate = _budget(len(feature_rows), dimension, columns,
        len(core._raw([feature_rows, source_features, references, probe])), max_memory_bytes, fitting=False)
    estimate += len(feature_rows)*MAX_SLOTS*len(FIELDS)*1600
    _require(estimate <= max_memory_bytes, "probe evaluation/report memory exceeds budget")
    check()
    remaining = max_seconds-(time.monotonic()-started)
    predicted = predict_probe(probe, feature_rows, zero_features=control["kind"] == "zero_features",
        max_seconds=remaining, max_memory_bytes=max_memory_bytes)
    rows = []
    for prediction in predicted["predictions"]:
        reference = by_id[prediction["id"]]
        observations = []
        for head, index in zip(probe["heads"][:-1], prediction["class_indices"][:-1]):
            expected = _label(reference, head)
            actual = head["classes"][index]
            observations.append(dict(slot_index=head["slot_index"], field=head["field"], expected=expected,
                predicted=deepcopy(actual), correct=actual == expected,
                out_of_training_inventory=expected not in head["classes"]))
        count_correct = prediction["predicted_count"] == reference["clause_count"]
        rows.append(dict(id=prediction["id"], source_sha256=prediction["source_sha256"],
            assigned_source_id=control["source_assignment"][prediction["id"]],
            prediction=prediction, expected_count=reference["clause_count"], count_correct=count_correct,
            scalar_slots=observations, scalar_slots_and_count_exact=count_correct and all(s["correct"] for s in observations)))
        check()
    report = dict(schema="decoder-source-slot-probe-evaluation/v1", complete=True,
        probe_sha256=probe["probe_sha256"], feature_rows_sha256=core.digest(feature_rows),
        source_features_sha256=core.digest(source_features), references_sha256=core.digest(references),
        control=checked_control, control_execution_verified=True,
        source_vector_binding_intentionally_broken=control["kind"] in ("source_shuffle", "cross_length_shuffle"),
        normalized_zero_is_training_mean_control=control["kind"] == "zero_features",
        count_labels_preserved_by_assignment=control["kind"] != "cross_length_shuffle",
        prediction_report=predicted["report"], rows_sha256=core.digest(rows), aggregates=_summarize(rows),
        by_length={str(k): _summarize([r for r in rows if r["expected_count"] == k]) for k in sorted({r["expected_count"] for r in rows})},
        metric_scope="ordered actor/action/modality/object scalar slots and separate count only",
        unscored_facets=list(fidelity.FACETS[4:]), full_legal_ir_exactness_measured=False,
        gold_present_metrics_are_conditional=True, full_slot_prediction_count_is_fixed=MAX_SLOTS,
        oracle_count_mask_applied=False, probe_fitting_executed=False,
        memory_work_estimate_bytes=estimate, memory_estimate_excludes_python_import_allocator_rss=True, **FALSE)
    return dict(report=_seal(report, check, started), rows=rows)
