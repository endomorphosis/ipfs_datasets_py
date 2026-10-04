"""Fixed-state reference-prefix diagnostics, never generation or training.

Gold prefixes are supplied only to this explicitly teacher-forced diagnostic.
Archived greedy outputs remain a separate observation. JSON positions are
annotated by traversal of the complete reference structure, never by token text
alone. Caller-declared archive hashes establish consistency, not authenticity.
"""
from copy import deepcopy
import hashlib
import json
import math
import random
import sys
import time

from . import decoder_cardinality_experiment as cardinality
from . import decoder_distillation_experiment as core
from . import decoder_source_fidelity as fidelity
from .decoder_gradient_replay import gradient_digest

SCHEMA = "decoder-prefix-diagnostics/v1"
ARCHIVE_SCHEMA = "decoder-prefix-archive/v1"
FALSE = dict(core.FALSE, admitted=False, training_executed=False, generation_executed=False,
    optimizer_executed=False, fresh_holdout=False, convergence_proven=False,
    lake_executed=False, native_validation_executed=False, checkpoint_promoted=False,
    encoder_context_changed=False, output_limit_changed=False)
_require = core._require


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def annotate_target(target, codec):
    """Lossless canonical lexical annotation, including unscored BOS and EOS.

    Scalar strings (including escaped strings) are one lexical token in this
    codec. A ``value_id`` joins all tokens of a semantic value if a future
    explicitly versioned codec supports finer tokenization; this owner does not.
    """
    vocabulary = codec["target_vocabulary"]
    lookup = {token: i for i, token in enumerate(vocabulary)}
    _require(type(target) is dict and set(target) == {"rules"} and type(target["rules"]) is list
        and 1 <= len(target["rules"]) <= 32, "complete bounded rules target required")
    for rule in target["rules"]:
        _require(type(rule) is dict and set(rule) == set(fidelity.FACETS), "exact seven-facet rule required")
        _require(all(type(rule[k]) is str for k in fidelity.FACETS[:4])
            and all(type(rule[k]) is list and len(rule[k]) <= 128
                and all(type(v) is str for v in rule[k]) for k in fidelity.FACETS[4:]),
            "complete string facets required")
    result = []

    def emit(token, kind, path, *, boundary=None):
        _require(token in lookup, "complete reference outside inherited vocabulary")
        rule_index = path[1] if len(path) >= 2 and path[0] == "rules" and type(path[1]) is int else None
        field = path[2] if len(path) >= 3 and path[2] in fidelity.FACETS else None
        semantic = kind in ("scalar_value", "qualifier_atom")
        result.append(dict(position=len(result), token=token, token_id=lookup[token], kind=kind,
            path=list(path), rule_index=rule_index, field=field, meaningful_value=semantic,
            value_id=_json(path) if semantic else None, boundary_after_rule=boundary))

    def walk(value, path=()):
        if type(value) is dict:
            emit("{", "syntax", path)
            for index, key in enumerate(sorted(value)):
                if index:
                    emit(",", "syntax", path)
                emit(_json(key), "field_key", (*path, key))
                emit(":", "syntax", (*path, key))
                walk(value[key], (*path, key))
            emit("}", "syntax", path)
        elif type(value) is list:
            empty_qualifier = not value and len(path) == 3 and path[2] in fidelity.FACETS[4:]
            kind = "fixed_empty_qualifier" if empty_qualifier else "syntax"
            emit("[", kind, path)
            for index, child in enumerate(value):
                if index:
                    emit(",", "rule_boundary" if path == ("rules",) else "syntax", path,
                        boundary=index-1 if path == ("rules",) else None)
                walk(child, (*path, index))
            emit("]", "rule_boundary" if path == ("rules",) else kind, path,
                boundary=len(value)-1 if path == ("rules",) else None)
        else:
            kind = "scalar_value" if len(path) == 3 else "qualifier_atom"
            emit(_json(value), kind, path)

    emit("<bos>", "bos", ())
    walk(target)
    emit("<eos>", "eos", ())
    _require("".join(row["token"] for row in result[1:-1]) == _json(target),
        "reference annotation lost canonical content")
    return result


def first_divergence(annotation, prediction, *, vocabulary, output_limit):
    """Compare only actually archived tokens; an absent EOS is not an emitted ID.

    Position excludes BOS (which greedy generation did not emit). Invalid
    special-token receipts do not identify which token was chosen, so the
    unknown special token is reported as a status with no guessed token ID.
    """
    if prediction is None:
        return dict(status="prediction_missing", available=False, matched_prefix_tokens=0,
            expected_position=None, emitted_token_id=None, emitted_token=None,
            explicit_eos_appended=False, missing_eos=True, archive_errors=["prediction_missing"])
    _require(type(prediction) is dict, "archived prediction must be a mapping")
    tokens = prediction.get("token_ids")
    _require(type(tokens) is list and len(tokens) <= output_limit-1 and all(type(token) is int
        and 3 <= token < len(vocabulary) for token in tokens), "invalid archived content tokens")
    eos = prediction.get("eos_reached")
    status = prediction.get("generation_status")
    _require(type(eos) is bool and status in ("eos", "output_limit", "invalid_special_token")
        and (status == "eos") == eos, "explicit consistent archived EOS/status required")
    _require(not eos or len(tokens)+2 <= output_limit, "archived EOS exceeds output budget")
    observed = tokens + ([2] if eos else [])
    expected = annotation[1:]
    matched = 0
    while matched < min(len(observed), len(expected)) and observed[matched] == expected[matched]["token_id"]:
        matched += 1
    if matched < min(len(observed), len(expected)):
        outcome = "token_mismatch"
    elif len(observed) > len(expected):
        outcome = "extra_emitted_token"
    elif len(observed) == len(expected) and eos:
        outcome = "exact_with_explicit_eos"
    else:
        outcome = "invalid_special_token_unidentified" if status == "invalid_special_token" else "prefix_exhausted_without_eos"
    expected_record = deepcopy(expected[matched]) if matched < len(expected) else None
    emitted = observed[matched] if matched < len(observed) else None
    return dict(status=outcome, available=True, matched_prefix_tokens=matched,
        expected_position=expected_record, emitted_token_id=emitted,
        emitted_token=None if emitted is None else vocabulary[emitted],
        explicit_eos_appended=eos, missing_eos=not eos, archived_generation_status=status,
        archived_content_sha256=core.digest(tokens), archived_prediction_sha256=core.digest(prediction),
        archived_content_tokens=len(tokens), archive_errors=[])


def _control_rows(rows, source_rows, references, control, dimension, vocabulary, cap):
    core._rows(rows, dimension, vocabulary, cap)
    core._rows(source_rows, dimension, vocabulary, cap)
    ids = [row["id"] for row in rows]
    _require([row["id"] for row in source_rows] == ids, "original source row order/IDs differ")
    _require(type(references) is list and len(references) == len(rows), "complete reference inventory required")
    _require(all(type(r) is dict and type(r.get("id")) is str for r in references),
        "complete reference identities required")
    by_reference = {r["id"]: r for r in references}
    _require(len(by_reference) == len(references) and set(by_reference) == set(ids), "reference IDs differ")
    checked = fidelity._control(control, ids)
    originals = {r["id"]: r for r in source_rows}
    same_length = True
    for row in rows:
        original = originals[row["id"]]
        reference = by_reference[row["id"]]
        _require(type(reference.get("source_text")) is str and reference["source_text"] == row["source_text"],
            "explicit reference source differs")
        _require(all(row[key] == original[key] for key in ("id", "source_text", "target_ids")),
            "control changed row identity, source or target")
        assignment = checked["source_assignment"][row["id"]]
        _require(row["input"] == originals[assignment]["input"], "control input does not match assigned original source")
        same_length &= reference["clause_count"] == by_reference[assignment]["clause_count"]
    return checked, by_reference, bool(same_length)


def _archive(value, predictions, model_digest, rows, codec, control, cap):
    _require(type(value) is dict and value.get("schema") == ARCHIVE_SCHEMA, "explicit archive provenance required")
    common = {"schema", "status", "split", "rows_sha256", "control_sha256", "output_limit"}
    _require(type(value.get("split")) is str and 0 < len(value["split"]) <= 128, "explicit source split required")
    _require(value.get("rows_sha256") == core.digest(rows) and value.get("control_sha256") == core.digest(control)
        and value.get("output_limit") == cap, "archive inputs/control/output limit differ")
    if value.get("status") == "unavailable":
        _require(set(value) == common | {"reason"} and predictions is None
            and type(value["reason"]) is str and 0 < len(value["reason"]) <= 512, "invalid unavailable archive receipt")
        return False
    _require(value.get("status") == "available" and set(value) == common | {"predictions_sha256",
        "prior_report_sha256", "executed_model_weights_sha256", "codec_sha256"}, "closed archive provenance required")
    _require(type(predictions) is list and value["predictions_sha256"] == core.digest(predictions)
        and value["executed_model_weights_sha256"] == model_digest
        and value["codec_sha256"] == core.digest(codec), "archive predictions/model/codec digest differs")
    _require(type(value["prior_report_sha256"]) is str and core._SHA.fullmatch(value["prior_report_sha256"]),
        "prior archived report digest required")
    return True


def _position_metrics(torch, logits, labels, annotation, vocabulary):
    """One full row; positions align to logits predicting content then EOS."""
    n = len(annotation)-1
    scores = logits[:n]
    log_probs = torch.log_softmax(scores, -1)
    _require(core._finite(torch, log_probs), "nonfinite per-position log probabilities")
    chosen = scores.argmax(-1)
    target = labels[:n]
    target_log_probs = log_probs.gather(1, target[:, None]).squeeze(1)
    target_scores = scores.gather(1, target[:, None])
    ranks = (scores > target_scores).sum(-1)+1
    values, predicted, order = target_log_probs.tolist(), chosen.tolist(), ranks.tolist()
    raw_logits = scores.tolist()
    stop, continuation = vocabulary.index("]"), vocabulary.index(",")
    positions, boundaries = [], []
    for i, reference in enumerate(annotation[1:]):
        row = dict(reference, raw_logits=raw_logits[i], log_probability=values[i], rank=order[i], argmax_token_id=predicted[i],
            argmax_token=vocabulary[predicted[i]], correct=predicted[i] == reference["token_id"])
        positions.append(row)
        if reference["boundary_after_rule"] is not None:
            ls, lc = float(log_probs[i, stop]), float(log_probs[i, continuation])
            ps, pc = math.exp(ls), math.exp(lc)
            margin = float(scores[i, stop])-float(scores[i, continuation])
            choice = "stop" if margin > 0 else "continue" if margin < 0 else "tie"
            expected = "stop" if reference["token_id"] == stop else "continue"
            boundaries.append(dict(position=reference["position"], rule_index=reference["boundary_after_rule"],
                expected=expected, argmax_token_id=predicted[i], argmax_token=vocabulary[predicted[i]],
                full_vocabulary_correct=predicted[i] == reference["token_id"],
                stop_log_probability=ls, continue_log_probability=lc, stop_probability=ps, continue_probability=pc,
                other_probability=max(0., 1.-ps-pc), stop_minus_continue_logit=margin,
                two_way_choice=choice, two_way_correct=choice == expected,
                scope="reference_prefix_binary_comparison_not_grammar_validation"))
    return positions, boundaries


def _bucket(positions):
    n = len(positions)
    correct = sum(row["correct"] for row in positions)
    return dict(tokens=n, correct=correct, accuracy=correct/n if n else None,
        mean_negative_log_probability=-sum(row["log_probability"] for row in positions)/n if n else None)


def _aggregate(records):
    positions = [p for row in records for p in row["positions"]]
    values = [p for p in positions if p["meaningful_value"]]
    by_kind = {k: _bucket([p for p in positions if p["kind"] == k]) for k in sorted({p["kind"] for p in positions})}
    by_facet = {k: _bucket([p for p in values if p["field"] == k]) for k in fidelity.FACETS}
    by_rule = {str(k): _bucket([p for p in values if p["rule_index"] == k])
        for k in sorted({p["rule_index"] for p in values})}
    whole_values = []
    for row in records:
        groups = {}
        for p in row["positions"]:
            if p["meaningful_value"]:
                groups.setdefault(p["value_id"], []).append(p)
        whole_values.extend(dict(token_count=len(group), correct=all(p["correct"] for p in group))
            for group in groups.values())
    boundaries = [b for row in records for b in row["boundaries"]]
    divergence = [r["first_divergence"] for r in records if r["first_divergence"]["available"]]
    return dict(tokens=_bucket(positions), semantic_values=_bucket(values), by_kind=by_kind,
        by_facet=by_facet, by_rule_index=by_rule,
        whole_value=dict(values=len(whole_values), correct=sum(v["correct"] for v in whole_values),
            token_counts=sorted(set(v["token_count"] for v in whole_values)),
            scope="complete_JSON_string_atom_not_whitespace_word"),
        boundaries=dict(count=len(boundaries), full_vocabulary_correct=sum(b["full_vocabulary_correct"] for b in boundaries),
            two_way_correct=sum(b["two_way_correct"] for b in boundaries),
            by_expected={k: dict(count=sum(b["expected"] == k for b in boundaries),
                full_vocabulary_correct=sum(b["expected"] == k and b["full_vocabulary_correct"] for b in boundaries),
                two_way_correct=sum(b["expected"] == k and b["two_way_correct"] for b in boundaries)) for k in ("stop", "continue")}),
        archived_first_divergence=dict(available_rows=len(divergence), unavailable_rows=len(records)-len(divergence),
            by_status={k: sum(d["status"] == k for d in divergence) for k in sorted({d["status"] for d in divergence})},
            availability_statuses={k: sum(r["first_divergence"]["status"] == k for r in records)
                for k in sorted({r["first_divergence"]["status"] for r in records})}))


def diagnose_prefixes(model, rows, references, *, codec, input_transform, lineage,
        archived_predictions, archive_provenance, source_rows, control=None, validate_rule,
        validator_id, max_target_tokens=512, batch_size=8, max_seconds=30., max_memory_bytes=536870912):
    """Score fixed reference prefixes and archived outputs on a private CPU copy.

    The original cardinality model is always supplied, including zero-source
    controls. The same published zero-source wrapper is applied here privately.
    ``source_rows`` is the unmodified original inventory; shuffled ``rows`` may
    change only input vectors according to the complete explicit assignment.
    Missing archived panels use ``archived_predictions=None`` and an unavailable
    receipt, not fabricated predictions. No batch is accepted after the deadline.
    """
    started = time.monotonic()
    options = core._config(dict(max_seconds=max_seconds, batch_size=batch_size,
        max_target_tokens=max_target_tokens, max_memory_bytes=max_memory_bytes))
    deadline = started+options["max_seconds"]
    def check():
        if time.monotonic() >= deadline:
            raise TimeoutError("prefix diagnostic deadline exceeded; no complete report")
    torch = core._torch()
    core._model(model, torch)
    vocabulary = core._validate(codec, input_transform, lineage, model.dimension)
    _require(lineage["domain"] == "legal_ir", "this owner diagnoses Legal rule facets only")
    _require(callable(getattr(model, "describe", None)) and model.describe().get("schema") == cardinality.SCHEMA
        and model.describe().get("codec_sha256") == core.digest(codec), "original cardinality model and exact codec required")
    checked_control, by_reference, same_length = _control_rows(rows, source_rows, references, control,
        model.dimension, vocabulary, max_target_tokens)
    _require(type(archived_predictions) is list or archived_predictions is None, "explicit archived predictions or unavailable panel required")
    serialized = sum(len(core._raw(x)) for x in (rows, source_rows, references, archived_predictions, archive_provenance))
    _require(serialized <= 134217728, "diagnostic input serialization exceeds bound")
    width = max(len(row["target_ids"]) for row in rows)
    token_count = sum(len(row["target_ids"])-1 for row in rows)
    parameter_bytes = sum(t.numel()*t.element_size() for t in model.state_dict().values())
    # Bounds private weights, logits/logprobs/ranks, recurrent work and report
    # position metadata. This is not an import/allocator/process-RSS guarantee.
    estimate = 6*parameter_bytes+24*batch_size*width*len(vocabulary)*4+serialized*3+token_count*(2400+40*len(vocabulary))
    _require(estimate <= max_memory_bytes, "prefix diagnostic memory estimate exceeds budget")
    check()
    before = core.tensor_digest(model)
    gradients = gradient_digest(model)
    modes = {n: m.training for n, m in model.named_modules()}
    trainable = {n: p.requires_grad for n, p in model.named_parameters()}
    torch_rng, python_rng = torch.get_rng_state().clone(), random.getstate()
    result = None
    try:
        working = cardinality.bind_zero_condition_model(model) if checked_control["kind"] == "zero_condition" else deepcopy(model)
        working.eval()
        executed_digest = core.tensor_digest(working)
        archive_available = _archive(archive_provenance, archived_predictions, executed_digest, rows, codec,
            checked_control, max_target_tokens)
        # Existing scorer validates complete rules, source hashes, duplicate IDs,
        # and mutation-free validator behavior. It never generates predictions.
        scored = fidelity.score_predictions(references, archived_predictions or [], codec=codec,
            validate_rule=validate_rule, output_limit=max_target_tokens, validator_id=validator_id, control=checked_control)
        annotations = {}
        for row in rows:
            check()
            annotation = annotate_target(by_reference[row["id"]]["target"], codec)
            _require([a["token_id"] for a in annotation] == row["target_ids"],
                "complete reference token sequence differs from numerical target")
            annotations[row["id"]] = annotation
        indexed = {p["id"]: p for p in archived_predictions or []}
        records, ce_sum = [], 0.
        with torch.inference_mode():
            for offset in range(0, len(rows), batch_size):
                check()
                part = rows[offset:offset+batch_size]
                data, labels = core._batch(torch, part, input_transform)
                _, logits = core._logits(torch, working, data, labels[:, :-1], len(vocabulary))
                ce = torch.nn.functional.cross_entropy(logits.flatten(0, 1), labels[:, 1:].flatten(),
                    ignore_index=0, reduction="sum")
                _require(core._finite(torch, ce), "nonfinite full-target cross-entropy")
                ce_sum += float(ce)
                for index, row in enumerate(part):
                    check()
                    annotation = annotations[row["id"]]
                    positions, boundaries = _position_metrics(torch, logits[index], labels[index, 1:], annotation, vocabulary)
                    divergence = first_divergence(annotation, indexed.get(row["id"]), vocabulary=vocabulary,
                        output_limit=max_target_tokens) if archive_available else dict(status="archive_panel_unavailable",
                            available=False, matched_prefix_tokens=None, expected_position=None,
                            emitted_token_id=None, reason=archive_provenance["reason"])
                    records.append(dict(id=row["id"], clause_count=by_reference[row["id"]]["clause_count"],
                        source_sha256=hashlib.sha256(row["source_text"].encode()).hexdigest(),
                        assigned_source_id=checked_control["source_assignment"][row["id"]],
                        input_sha256=core.digest(row["input"]), reference_sha256=core.digest(by_reference[row["id"]]),
                        full_target_ids_sha256=core.digest(row["target_ids"]), annotation=annotation,
                        positions=positions, boundaries=boundaries, eos=deepcopy(positions[-1]),
                        first_divergence=divergence))
                check()
        aggregate = _aggregate(records)
        ce = ce_sum/token_count
        positional_ce = aggregate["tokens"]["mean_negative_log_probability"]
        _require(math.isclose(ce, positional_ce, rel_tol=1e-6, abs_tol=1e-6), "position CE does not reconcile full-target evaluator")
        result = dict(schema=SCHEMA, complete=True, scope="exposed_fixed_state_reference_prefix_diagnostic",
            aggregates=aggregate, diagnostic_rows_sha256=core.digest(records),
            raw_logits_dtype="float32", target_vocabulary=deepcopy(vocabulary),
            by_length={str(k): _aggregate([r for r in records if r["clause_count"] == k])
                for k in sorted({r["clause_count"] for r in records})},
            numerical=dict(token_cross_entropy=ce, target_token_count=token_count, count=len(rows),
                positional_token_cross_entropy=positional_ce, ce_reconciled=True,
                reconciliation_absolute_tolerance=1e-6, reconciliation_relative_tolerance=1e-6,
                reduction="sum nonpadding content+EOS CE / all nonpadding content+EOS tokens; BOS excluded",
                batch_size=batch_size, ce_teacher_forced=True),
            model_weights_sha256=before, executed_model_weights_sha256=executed_digest,
            rows_sha256=core.digest(rows), source_rows_sha256=core.digest(source_rows),
            references_sha256=core.digest(references), codec_sha256=core.digest(codec),
            input_transform_sha256=core.digest(input_transform), lineage=deepcopy(lineage),
            archive_provenance=deepcopy(archive_provenance), archive_consistency_verified=True,
            archive_authenticity_verified=False, archived_fidelity_report_sha256=scored["report_sha256"],
            archived_fidelity_metrics=scored["metrics"] if archive_available else None,
            control=checked_control, control_execution_verified=True,
            source_vector_binding_intentionally_broken=checked_control["kind"] == "source_shuffle",
            count_labels_preserved_by_assignment=same_length,
            count_shuffle_scope="same-length assignments cannot validate source/count association" if same_length else "cross-length assignment",
            source_text_used_for_decoding=False, reference_prefix_access=True, forward_executed=True,
            generation_temperature=0, meaningful_value_scope="four scalar fields plus nonempty qualifier string atoms",
            whole_value_scope="full lexical string atom; grammar/key/empty-qualifier tokens excluded",
            output_limit=max_target_tokens, full_targets_truncated=False,
            memory_work_estimate_bytes=estimate, memory_estimate_excludes_python_import_allocator_rss=True,
            deadline_scope="cooperative, includes final caller-integrity/RNG verification", **FALSE)
    finally:
        torch.set_rng_state(torch_rng)
        random.setstate(python_rng)
        pending_exception = sys.exc_info()[0] is not None
        try:
            _require(core.tensor_digest(model) == before and gradient_digest(model) == gradients
                and modes == {n: m.training for n, m in model.named_modules()}
                and trainable == {n: p.requires_grad for n, p in model.named_parameters()},
                "diagnostic changed caller model, gradients or modes")
        except Exception:
            if not pending_exception:
                raise
    check()
    result["elapsed_seconds"] = time.monotonic()-started
    result["report_sha256"] = core.digest(result)
    check()
    return dict(report=result, rows=records)
