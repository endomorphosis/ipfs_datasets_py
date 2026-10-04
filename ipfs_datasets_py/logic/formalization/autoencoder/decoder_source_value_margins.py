"""Read-only actual-prefix attribution of the private source-value decoder.

Rollout receives source tensors only and follows the existing greedy policy.
Reference alignment is a separate post-rollout operation. Inherited logits and
the causally selected scalar residual must sum exactly to the actual logits;
no alternate decoding policy, training, or qualification is performed here.
"""
from copy import deepcopy
import hashlib
import random
import sys
import time

from . import decoder_distillation_experiment as core
from . import decoder_prefix_diagnostics as prefix
from . import decoder_source_fidelity as fidelity
from . import source_value_decoder_experiment as values
from .decoder_gradient_replay import gradient_digest

SCHEMA = "decoder-source-value-margins/v1"
FALSE = dict(core.FALSE, training_executed=False, optimizer_executed=False, fresh_holdout=False,
    convergence_proven=False, lake_executed=False, native_validation_executed=False,
    checkpoint_promoted=False, encoder_context_changed=False, output_limit_changed=False,
    reference_prefix_access=False, source_text_used_for_decoding=False)
_require = core._require


def _site(grammar, description):
    """Classify next-token context from consumed grammar, without references."""
    phase, _, pending, count, _, _ = grammar
    scalar = phase == 8 and pending < 4
    field = values.cardinality.FIELDS[pending] if scalar else None
    kind = ("invalid_prefix" if phase == values.cardinality._INVALID else
        "scalar_value" if scalar else "rule_boundary" if phase == 13 else
        "qualifier_atom_or_close" if phase in (10, 12) else "eos" if phase == 16 else "grammar")
    reason = ("invalid_prefix" if phase == values.cardinality._INVALID else
        "not_scalar_site" if not scalar else "beyond_slot_limit" if count >= description["max_rules"] else
        "guidance_disabled" if not description["guidance"] else "active")
    return dict(kind=kind, guidance_status=reason, rule_slot=count if scalar else None, field=field,
        completed_rules=count, causal_grammar_phase=phase)


def _rollout(torch, model, data, *, cap, size, check):
    """Target-free replay; no reference, saved output, source text, or ID input."""
    description = model.describe()
    # Tables are not needed to select a site: the actual inherited recognizer's
    # updated state already identifies the next scalar position causally.
    projected = model.project(data)
    _require(projected.shape == data.shape and core._finite(torch, projected), "invalid traced projection")
    state = model.start(projected)
    current = torch.ones((len(data), 1), dtype=torch.long)
    active = [True] * len(data)
    outputs, events = [[] for _ in data], [[] for _ in data]
    statuses = ["output_limit"] * len(data)
    raw = torch.empty((3, len(data), cap-1, size), dtype=torch.float32)
    for step in range(cap-1):
        check()
        inherited, inherited_next = model.body.next_logits(current, state[:5])
        actual, updated = model.next_logits(current, state)
        _require(tuple(actual.shape) == (len(data), 1, size) and core._finite(torch, actual)
            and core._finite(torch, inherited) and core._finite(torch, updated), "invalid traced decoder output")
        _require(all(torch.equal(a, b) for a, b in zip(inherited_next, updated[:5])),
            "inherited recurrent state differs from actual decoder")
        _require(updated[-1] is state[-1], "source head scores must remain explicit immutable sequence state")
        sites = [_site(grammar, description) for grammar in updated[4].tolist()]
        residual = torch.zeros_like(actual)
        for index, site in enumerate(sites):
            if site["guidance_status"] == "active":
                field = values.SOURCE_FIELDS.index(site["field"])
                residual[index, 0] = state[-1][index, site["rule_slot"], field]
        _require(torch.equal(inherited + residual, actual), "source residual decomposition differs from actual logits")
        check()
        raw[0, :, step] = inherited[:, 0]
        raw[1, :, step] = residual[:, 0]
        raw[2, :, step] = actual[:, 0]
        chosen = actual[:, 0].argmax(-1).tolist()
        base_chosen = inherited[:, 0].argmax(-1).tolist()
        head_chosen = residual[:, 0].argmax(-1).tolist()
        nonconstant = (residual[:, 0].max(-1).values != residual[:, 0].min(-1).values).tolist()
        nonzero = (residual[:, 0] != 0).any(-1).tolist()
        for index, token in enumerate(chosen):
            if not active[index]:
                continue
            site = sites[index]
            enabled = site["guidance_status"] == "active"
            events[index].append(dict(position=step+1, consumed_token_id=int(current[index, 0]),
                emitted_token_id=token, inherited_winner_token_id=base_chosen[index],
                source_winner_token_id=head_chosen[index] if enabled else None,
                source_residual_nonconstant=bool(nonconstant[index]), source_residual_nonzero=bool(nonzero[index]),
                combined_winner_token_id=token, inherited_choice_changed=token != base_chosen[index],
                source_winner_emitted=enabled and token == head_chosen[index],
                decomposition_exact=True, **site))
            if token in (0, 1, 2):
                statuses[index] = "eos" if token == 2 else "invalid_special_token"
                active[index] = False
            else:
                outputs[index].append(token)
        state = updated
        if not any(active):
            break
        # Inactive rows continue participating exactly as in core._greedy.
        current = torch.tensor(chosen, dtype=torch.long).unsqueeze(1)
    check()
    return dict(outputs=outputs, statuses=statuses, events=events, raw_logits=raw)


def _scores(logits, *, expected, emitted, source_winner):
    winner = max(range(len(logits)), key=logits.__getitem__)
    def rank(token):
        return None if token is None else 1 + sum(value > logits[token] for value in logits)
    def margin(left, right):
        return None if left is None or right is None else logits[left] - logits[right]
    return dict(winner_token_id=winner, winner_tie_count=sum(value == logits[winner] for value in logits),
        expected_rank=rank(expected), emitted_rank=rank(emitted), source_winner_rank=rank(source_winner),
        expected_minus_emitted=margin(expected, emitted), expected_minus_winner=margin(expected, winner),
        source_winner_minus_emitted=margin(source_winner, emitted))


def _summarize_events(events):
    counts = dict(steps=len(events), scalar_sites=0, boundary_sites=0, active_residual_sites=0,
        nonzero_residual_sites=0, nonconstant_residual_sites=0, inherited_choice_changed=0,
        source_winner_emitted=0, decomposition_exact_steps=0)
    kinds, reasons = {}, {}
    for event in events:
        counts["scalar_sites"] += event["kind"] == "scalar_value"
        counts["boundary_sites"] += event["kind"] == "rule_boundary"
        counts["active_residual_sites"] += event["guidance_status"] == "active"
        counts["nonzero_residual_sites"] += event["source_residual_nonzero"]
        counts["nonconstant_residual_sites"] += event["source_residual_nonconstant"]
        counts["inherited_choice_changed"] += event["inherited_choice_changed"]
        counts["source_winner_emitted"] += event["source_winner_emitted"]
        counts["decomposition_exact_steps"] += event["decomposition_exact"]
        kinds[event["kind"]] = kinds.get(event["kind"], 0) + 1
        reasons[event["guidance_status"]] = reasons.get(event["guidance_status"], 0) + 1
    return dict(**counts, by_kind=kinds, by_guidance_status=reasons,
        comparison_scope="actual emitted prefixes; no reference accuracy after divergence")


def _posthoc(annotation, events, raw, prediction):
    expected = annotation[1:]
    mismatch = next((index for index, event in enumerate(events)
        if index >= len(expected) or event["emitted_token_id"] != expected[index]["token_id"]), None)
    matched = len(events) if mismatch is None else mismatch
    exact = mismatch is None and len(events) == len(expected) and prediction["eos_reached"]
    status = "exact_with_explicit_eos" if exact else "token_mismatch" if mismatch is not None else "prefix_exhausted_without_eos"
    selected = {}
    if mismatch is not None:
        selected.setdefault(mismatch, []).append("first_divergence")
    for kind, label in (("scalar_value", "first_scalar_site"), ("rule_boundary", "first_rule_boundary")):
        index = next((index for index, event in enumerate(events) if event["kind"] == kind), None)
        if index is not None:
            selected.setdefault(index, []).append(label)
    captures = []
    for index, reasons in sorted(selected.items()):
        event = events[index]
        # Only the first-divergence capture is compared with a reference token.
        reference = deepcopy(expected[index]) if index == mismatch and index < len(expected) else None
        token = None if reference is None else reference["token_id"]
        vectors = {name: raw[lane, index].tolist() for lane, name in enumerate(("inherited", "source_residual", "combined"))}
        captures.append(dict(position=index+1, reasons=reasons, event=deepcopy(event),
            expected_annotation=reference, raw_logits=vectors,
            scores={name: _scores(vector, expected=token, emitted=event["emitted_token_id"],
                source_winner=event["source_winner_token_id"]) for name, vector in vectors.items()}))
    divergence = dict(status=status, matched_prefix_tokens=matched,
        position=None if mismatch is None else mismatch+1,
        expected_annotation=None if mismatch is None or mismatch >= len(expected) else deepcopy(expected[mismatch]),
        emitted_token_id=None if mismatch is None else events[mismatch]["emitted_token_id"],
        actual_special_token_identified=True, comparison_after_rollout=True)
    return divergence, captures


def _aggregate(records):
    summary = _summarize_events([event for row in records for event in row["events"]])
    divergences, fields, statuses = {}, {}, {}
    active_first = dict(rows=0, source_prefers_expected=0, inherited_prefers_expected=0,
        source_prefers_expected_but_emitted_other=0, source_and_inherited_both_prefer_other=0,
        source_winner_emitted=0)
    for row in records:
        divergence = row["first_divergence"]
        statuses[divergence["status"]] = statuses.get(divergence["status"], 0) + 1
        annotation = divergence["expected_annotation"]
        kind = "none" if annotation is None else annotation["kind"]
        divergences[kind] = divergences.get(kind, 0) + 1
        if annotation is not None and annotation["field"] is not None:
            field = annotation["field"]
            fields[field] = fields.get(field, 0) + 1
        capture = next((c for c in row["captures"] if "first_divergence" in c["reasons"]), None)
        if capture is None or annotation is None or capture["event"]["guidance_status"] != "active":
            continue
        event, target = capture["event"], annotation["token_id"]
        source_right = event["source_winner_token_id"] == target
        inherited_right = event["inherited_winner_token_id"] == target
        active_first["rows"] += 1
        active_first["source_prefers_expected"] += source_right
        active_first["inherited_prefers_expected"] += inherited_right
        active_first["source_prefers_expected_but_emitted_other"] += source_right and event["emitted_token_id"] != target
        active_first["source_and_inherited_both_prefer_other"] += not source_right and not inherited_right
        active_first["source_winner_emitted"] += event["source_winner_emitted"]
    return dict(rows=len(records), events=summary, first_divergence_by_expected_kind=divergences,
        first_divergence_by_expected_field=fields, divergence_statuses=statuses,
        active_scalar_first_divergence=active_first)


def trace_predictions(model, rows, references, *, codec, input_transform, lineage,
        expected_predictions, validate_rule, validator_id, source_rows=None, control=None,
        max_target_tokens=512, max_seconds=30., batch_size=8, max_memory_bytes=536870912):
    """Replay saved greedy predictions privately, then classify their first error.

    ``source_rows``/``control`` authenticate source assignments; reference tokens
    never reach ``_rollout``. Expected prediction hashes are consistency checks,
    not evidence that the caller authenticated their original artifact.
    """
    started = time.monotonic()
    options = core._config(dict(max_seconds=max_seconds, batch_size=batch_size,
        max_target_tokens=max_target_tokens, max_memory_bytes=max_memory_bytes))
    deadline = started + options["max_seconds"]
    def check():
        if time.monotonic() >= deadline:
            raise TimeoutError("source-value margin deadline exceeded; no complete report")
    torch = core._torch()
    core._model(model, torch)
    vocabulary = core._validate(codec, input_transform, lineage, model.dimension)
    description = model.describe()
    _require(lineage["domain"] == "legal_ir" and description.get("schema") == values.SCHEMA
        and description.get("codec_sha256") == core.digest(codec), "actual source-value decoder and inherited codec required")
    original_rows = rows if source_rows is None else source_rows
    checked_control, by_reference, same_length = prefix._control_rows(rows, original_rows, references,
        control, model.dimension, vocabulary, max_target_tokens)
    _require(checked_control["kind"] in ("conditioned", "source_shuffle"), "explicit conditioned or source-shuffle trace required")
    _require(type(expected_predictions) is list and len(expected_predictions) == len(rows)
        and all(type(p) is dict and type(p.get("id")) is str for p in expected_predictions), "complete archived predictions required")
    expected_by_id = {p["id"]: p for p in expected_predictions}
    _require(len(expected_by_id) == len(rows) and set(expected_by_id) == {r["id"] for r in rows},
        "archived prediction identities differ")
    serialized = sum(len(core._raw(value)) for value in (rows, original_rows, references, expected_predictions))
    _require(serialized <= 134217728, "trace input serialization exceeds bound")
    parameter_bytes = sum(t.numel()*t.element_size() for t in model.state_dict().values())
    estimate = (6*parameter_bytes + serialized*3 + 6*batch_size*(max_target_tokens-1)*len(vocabulary)*4
        + len(rows)*(max_target_tokens-1)*2200 + len(rows)*3*(16000 + len(vocabulary)*320))
    _require(estimate <= max_memory_bytes, "source-value trace memory estimate exceeds budget")
    check()
    before, gradients = core.tensor_digest(model), gradient_digest(model)
    modes = {name: module.training for name, module in model.named_modules()}
    trainable = {name: p.requires_grad for name, p in model.named_parameters()}
    torch_rng, python_rng = torch.get_rng_state().clone(), random.getstate()
    result, records = None, []
    try:
        working = deepcopy(model)
        working.eval()
        # Validate complete references and saved status receipts without model
        # access. References remain outside the target-free rollout signature.
        scored = fidelity.score_predictions(references, expected_predictions, codec=codec,
            validate_rule=validate_rule, validator_id=validator_id, output_limit=max_target_tokens,
            control=checked_control)
        with torch.inference_mode():
            for offset in range(0, len(rows), batch_size):
                check()
                part = rows[offset:offset+batch_size]
                data = torch.tensor([row["input"] for row in part], dtype=torch.float32)
                data = (data-torch.tensor(input_transform["mean"], dtype=torch.float32))/input_transform["scale"]
                replay = _rollout(torch, working, data, cap=max_target_tokens, size=len(vocabulary), check=check)
                for index, row in enumerate(part):
                    check()
                    prediction = dict(id=row["id"], token_ids=replay["outputs"][index],
                        generation_status=replay["statuses"][index], eos_reached=replay["statuses"][index] == "eos")
                    archived = expected_by_id[row["id"]]
                    _require(all(prediction[key] == archived.get(key) for key in prediction),
                        "actual greedy output differs from archived prediction: " + row["id"])
                    annotation = prefix.annotate_target(by_reference[row["id"]]["target"], codec)
                    _require([a["token_id"] for a in annotation] == row["target_ids"], "complete reference target tokens differ")
                    divergence, captures = _posthoc(annotation, replay["events"][index], replay["raw_logits"][:, index], prediction)
                    records.append(dict(id=row["id"], clause_count=by_reference[row["id"]]["clause_count"],
                        source_sha256=hashlib.sha256(row["source_text"].encode()).hexdigest(),
                        input_sha256=core.digest(row["input"]), reference_sha256=core.digest(by_reference[row["id"]]),
                        assigned_source_id=checked_control["source_assignment"][row["id"]],
                        target_ids_sha256=core.digest(row["target_ids"]), archived_prediction_sha256=core.digest(archived),
                        prediction=prediction, archived_prediction_matches=True, first_divergence=divergence,
                        events=replay["events"][index], captures=captures))
                del replay
                check()
        _require(core.tensor_digest(working) == before, "trace changed private model weights")
        result = dict(schema=SCHEMA, complete=True, scope="exposed_fixed_state_actual_greedy_prefix_attribution",
            aggregates=_aggregate(records), by_length={str(n): _aggregate([r for r in records if r["clause_count"] == n])
                for n in sorted({r["clause_count"] for r in records})},
            diagnostic_rows_sha256=core.digest(records), raw_logits_dtype="float32",
            raw_capture_policy=["first_divergence", "first_scalar_site", "first_rule_boundary"],
            target_vocabulary=deepcopy(vocabulary), model_weights_sha256=before,
            rows_sha256=core.digest(rows), source_rows_sha256=core.digest(original_rows),
            references_sha256=core.digest(references), expected_predictions_sha256=core.digest(expected_predictions),
            codec_sha256=core.digest(codec), input_transform_sha256=core.digest(input_transform), lineage=deepcopy(lineage),
            control=checked_control, source_assignment_verified=True, count_labels_preserved_by_assignment=same_length,
            archived_predictions_match=True, archive_authenticity_verified=False,
            archived_fidelity_metrics=scored["metrics"], archived_fidelity_report_sha256=scored["report_sha256"],
            decomposition_exact=True, maximum_decomposition_error=0.,
            inherited_state_parity_verified=True, generation_executed=True, generation_temperature=0,
            generation_scope="unchanged greedy replay; inherited attribution forward does not choose rollout tokens",
            reference_access="after complete batch rollout for first divergence only; separate preflight validates reference documents",
            optimizer_steps=0, output_limit=max_target_tokens, batch_size=batch_size,
            memory_work_estimate_bytes=estimate, memory_estimate_excludes_python_import_allocator_rss=True,
            deadline_scope="cooperative including final caller integrity and report hashing", **FALSE)
    finally:
        torch.set_rng_state(torch_rng)
        random.setstate(python_rng)
        pending = sys.exc_info()[0] is not None
        try:
            _require(core.tensor_digest(model) == before and gradient_digest(model) == gradients
                and modes == {n: m.training for n, m in model.named_modules()}
                and trainable == {n: p.requires_grad for n, p in model.named_parameters()},
                "trace changed caller weights, gradients, modes or trainability")
        except Exception:
            if not pending:
                raise
    check()
    result["elapsed_seconds"] = time.monotonic()-started
    result["report_sha256"] = core.digest(result)
    check()
    return dict(report=result, rows=records)
