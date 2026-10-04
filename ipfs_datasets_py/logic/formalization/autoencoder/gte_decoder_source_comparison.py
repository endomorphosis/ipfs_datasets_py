"""Compare preserved decoders using source vectors and generated prefixes only.

Original exposed validation and authored training diagnostics remain regression
evidence. Saved reports can be inspected without numerical dependencies; exact
execution replay requires this runner and independently loaded private models.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

SCHEMA = "gte-decoder-source-comparison/v1"
VARIANTS = ("original_donor", "original_initialization", "aligned_initialization", "trained_interfaces")
HEADS = ("primary384", "legacy8")
FALSE_FLAGS = ("training_executed", "distillation_executed", "encoder_inference_executed",
    "download_executed", "teacher_qualified", "production_kd_eligible", "source_fidelity_qualified",
    "proof_authority", "independent_holdout_evaluated", "reference_prefix_used")
TRUE_FLAGS = ("original_inputs_unchanged", "all_inherited_tensors_unchanged", "private_storage_disjoint",
    "references_used_only_for_scoring", "failures_retained_in_denominator")
MAX_BYTES = 128 * 1024 * 1024


def _helper(name):
    spec = importlib.util.spec_from_file_location("_gte_source_comparison_" + name,
                                                Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _implementation():
    names = ("gte_decoder_source_comparison", "gte_decoder_source_evaluation", "gte_decoder_source_generation")
    return {name + ".py": hashlib.sha256(Path(__file__).with_name(name + ".py").read_bytes()).hexdigest()
            for name in names}


def _admit(evaluation, initialization, native_plan, batch, replay, pins, primary, legacy,
           aligned_checkpoint, alignment_pins, trained_checkpoint):
    source = _helper("gte_decoder_source_evaluation")
    source.inspect_source_evaluation(evaluation, initialization, native_plan, batch, replay,
                                     expected_donor_pins=pins)
    reuse = _helper("gte_decoder_reuse")
    reuse.inspect_dual_decoder(initialization, expected_donor_pins=pins)
    legacy_snapshot = _helper("gte_decoder_transfer_replay")._admit_originals(
        initialization, primary, legacy, pins, reuse)
    _require((aligned_checkpoint is None) == (alignment_pins is None),
             "aligned checkpoint and external file pins must be supplied together")
    if aligned_checkpoint is not None:
        _helper("gte_aligned_decoder").inspect_aligned_decoder(aligned_checkpoint,
            expected_file_pins=alignment_pins, expected_donor_pins=pins)
        _require(aligned_checkpoint["initialization"] == initialization,
                 "aligned generation uses a different original initialization")
        _require(aligned_checkpoint["source_profile_id"] == native_plan["profile_id"]
                 and aligned_checkpoint["plan"]["asset_manifest_sha256"] == native_plan["asset_manifest_sha256"],
                 "aligned generation and native inputs require the same source profile and encoder assets")
    arguments = {"initialization": initialization, "plan": native_plan, "batch": batch, "replay": replay,
        "expected_donor_pins": pins, "aligned_checkpoint": aligned_checkpoint,
        "expected_alignment_file_pins": alignment_pins}
    if trained_checkpoint is not None:
        _require(aligned_checkpoint is not None, "trained generation requires its authenticated aligned start")
        _helper("gte_aligned_interface_checkpoint").inspect_interface_checkpoint(trained_checkpoint, **arguments)
    identities = {"original_donor": {name: pins[key] for name, key in (
        ("primary384", "teacher384_checkpoint_sha256"), ("legacy8", "legacy8_checkpoint_sha256"))},
        "original_initialization": {name: initialization["representation_id"] for name in HEADS},
        "aligned_initialization": {name: aligned_checkpoint["representation_id"] if aligned_checkpoint else None for name in HEADS},
        "trained_interfaces": {name: trained_checkpoint["representation_id"] if trained_checkpoint else None for name in HEADS}}
    return source, legacy_snapshot, arguments, identities


def _head_summary(rows):
    evaluated = [row for row in rows if row["status"] == "evaluated"]
    count = len(evaluated)
    result = {"selected_row_count": len(rows), "evaluated_row_count": count,
        "missing_native_row_count": sum(row["status"] == "missing_native" for row in rows),
        "quarantined_native_row_count": sum(row["status"] == "quarantined_native" for row in rows),
        "model_unavailable_row_count": sum(row["status"] == "model_unavailable" for row in rows)}
    for label, metric in (("exact_target_match_count", "exact_target_match"), ("syntax_valid_count", "syntax_valid"),
                          ("invalid_generation_count", "invalid_generation"), ("terminated_count", "terminated"),
                          ("truncated_count", "truncated")):
        result[label] = sum(row["score"][metric] for row in evaluated)
    result["exact_match_rate_on_evaluated_rows"] = result["exact_target_match_count"] / count if count else None
    result["exact_match_rate_on_selected_rows"] = result["exact_target_match_count"] / len(rows) if rows else None
    result["coverage_fraction"] = count / len(rows) if rows else None
    result["complete_cohort_evaluated"] = count == len(rows)
    return result


def _model_state_identities(initialization, primary, snapshot, aligned, trained):
    original_state = _helper("gte_decoder_native_objective")._expected_state(initialization)
    return {"original_donor": {"primary384": digest(primary["model_state"]), "legacy8": digest(snapshot["model_state"])},
        "original_initialization": {name: digest(original_state) for name in HEADS},
        "aligned_initialization": {name: aligned["model_state_sha256"] if aligned is not None else None for name in HEADS},
        "trained_interfaces": {name: trained["model_state_sha256"] if trained is not None else None for name in HEADS}}


def _envelope(evaluation, identities, variants):
    native_count = sum(head["summary"]["evaluated_row_count"] for label, value in variants.items()
                       if label != "original_donor" for head in value["heads"].values())
    status = "donor_baseline_only_unqualified" if native_count == 0 else "partial_comparison_unqualified"
    if native_count and all(variants[label]["available"] and all(head["summary"]["complete_cohort_evaluated"]
                            for head in variants[label]["heads"].values()) for label in VARIANTS):
        status = "complete_comparison_unqualified"
    return {"schema": SCHEMA, "status": status, "evaluation_plan_sha256": evaluation["plan_sha256"],
        "native_plan_sha256": evaluation["native_plan_sha256"], "donor_pins": deepcopy(evaluation["donor_pins"]),
        "model_identities": identities, "variants": variants, "implementation": _implementation(),
        "numerical_profile": {"device": "cpu", "dtype": "float32", "threads": 1, "evaluation_mode": True,
            "decoding": "greedy_unmasked_argmax", "prefix_origin": "previously_generated_tokens_only"},
        "decoder_inference_executed": True, "native768_inputs_used": native_count > 0,
        "optimizer_created": False, "optimizer_steps": 0,
        **{name: False for name in FALSE_FLAGS}, **{name: True for name in TRUE_FLAGS}}


def compare_source_decoders(evaluation, *, initialization, native_plan, batch, replay, expected_donor_pins,
                            primary_checkpoint, legacy8_checkpoint, aligned_checkpoint=None,
                            expected_alignment_file_pins=None, trained_checkpoint=None):
    """Execute privately admitted original donors and available 768D generations.

    No reference, target length, or source text enters the generation call. A
    missing native receipt never receives padded or projected old coordinates.
    """
    values = deepcopy((evaluation, initialization, native_plan, batch, replay, expected_donor_pins,
                       primary_checkpoint, legacy8_checkpoint, aligned_checkpoint,
                       expected_alignment_file_pins, trained_checkpoint))
    original_digest = digest(values)
    ev, init, plan, transfer, retained, pins, primary, legacy, aligned, alignment_pins, trained = values
    source, snapshot, arguments, identities = _admit(*values)
    generation = _helper("gte_decoder_source_generation")
    preserved = _helper("gte_decoder_transfer_replay")
    import torch
    with preserved._numerical_context(torch):
        donors = {"primary384": preserved._original_primary_model(torch, primary),
            "legacy8": _helper("gte_legacy8_decoder_donor").load_private_legacy8_decoder_snapshot(snapshot,
                expected_source_checkpoint_sha256=pins["legacy8_checkpoint_sha256"],
                expected_source_model_state_sha256=pins["legacy8_weights_sha256"])["model"]}
        models = {}
        if ev["native_ready_row_count"]:
            models["original_initialization"] = _helper("gte_decoder_reuse").load_dual_decoder(init, expected_donor_pins=pins)
            if aligned is not None:
                models["aligned_initialization"] = _helper("gte_aligned_decoder").load_aligned_decoder(aligned,
                    expected_file_pins=alignment_pins, expected_donor_pins=pins)
            if trained is not None:
                models["trained_interfaces"] = _helper("gte_aligned_interface_checkpoint").load_interface_checkpoint(trained, **arguments)
        inherited = _helper("gte_decoder_native_objective")._expected_state(init)
        interface_names = set(_helper("gte_decoder_native_objective").INTERFACES)
        all_models = [*donors.values(), *models.values()]
        pointers = []
        before = {}
        for index, model in enumerate(all_models):
            before[index] = digest({name: value.detach().tolist() for name, value in model.state_dict().items()})
            pointers.extend(parameter.untyped_storage().data_ptr() for parameter in model.parameters())
            _require(all(parameter.grad is None for parameter in model.parameters()), "fresh private gradients required")
        _require(len(set(pointers)) == len(pointers), "all independently loaded model parameter storage must be disjoint")
        for model in models.values():
            parameters = dict(model.named_parameters())
            for name, values_ in inherited.items():
                if name not in interface_names:
                    _require(torch.equal(parameters[name].detach(), torch.tensor(values_, dtype=torch.float32)),
                             "inherited student decoder tensor changed")
        variants = {}
        for label in VARIANTS:
            available = all(value is not None for value in identities[label].values())
            heads = {}
            for name in HEADS:
                head = ev["heads"][name]
                codec = init["primary" if name == "primary384" else "legacy8"]["codec"]
                rows = []
                for row in head["rows"]:
                    status = "evaluated" if label == "original_donor" else ("model_unavailable" if not available else
                        "evaluated" if row["native_status"] == "ready" else row["native_status"] + "_native")
                    entry = {"id": row["id"], "source_sha256": row["source_sha256"],
                        "evaluation_role": row["evaluation_role"], "reference_sha256": row["reference"]["target_sha256"],
                        "status": status, "input_sha256": None, "generation": None, "score": None}
                    if status == "evaluated":
                        selected = row["generation_input"] if label == "original_donor" else row["native_generation_input"]
                        receipt = generation.generate_source_only(donors[name] if label == "original_donor" else models[label],
                            variant=("donor384" if name == "primary384" else "legacy8") if label == "original_donor" else "student768",
                            head=name, input_vector=selected["input_vector"], max_new_tokens=head["max_new_tokens"],
                            inherited_max_target_tokens=head["inherited_max_target_tokens"])
                        generation.inspect_source_only_generation(receipt)
                        score = source.score_generation({key: receipt[key] for key in ("generated_ids", "terminated", "truncated")},
                            row["reference"], codec, name)
                        entry.update(input_sha256=selected["input_sha256"], generation=receipt, score=score)
                    rows.append(entry)
                heads[name] = {"codec_sha256": head["codec_sha256"], "summary": _head_summary(rows), "rows": rows}
            variants[label] = {"available": available, "heads": heads}
        for index, model in enumerate(all_models):
            _require(before[index] == digest({name: value.detach().tolist() for name, value in model.state_dict().items()})
                     and all(parameter.grad is None for parameter in model.parameters()), "source comparison modified model state or gradients")
    _require(original_digest == digest(values) == digest((evaluation, initialization, native_plan, batch, replay,
        expected_donor_pins, primary_checkpoint, legacy8_checkpoint, aligned_checkpoint, expected_alignment_file_pins,
        trained_checkpoint)), "source comparison modified original inputs")
    result = _envelope(ev, identities, variants)
    _require(len(_raw(result)) <= MAX_BYTES, "bounded source comparison output required")
    return result


def inspect_source_comparison(report, evaluation, *, initialization, native_plan, batch, replay,
                              expected_donor_pins, primary_checkpoint, legacy8_checkpoint,
                              aligned_checkpoint=None, expected_alignment_file_pins=None, trained_checkpoint=None):
    """Reconstruct scoring/accounting, without claiming numerical execution."""
    source, snapshot, _, identities = _admit(evaluation, initialization, native_plan, batch, replay, expected_donor_pins,
        primary_checkpoint, legacy8_checkpoint, aligned_checkpoint, expected_alignment_file_pins, trained_checkpoint)
    state_identities = _model_state_identities(initialization, primary_checkpoint, snapshot, aligned_checkpoint, trained_checkpoint)
    _require(type(report) is dict and len(_raw(report)) <= MAX_BYTES and type(report.get("variants")) is dict
             and set(report["variants"]) == set(VARIANTS), "closed bounded source comparison variants required")
    generation = _helper("gte_decoder_source_generation")
    variants = {}
    for label in VARIANTS:
        value = report["variants"][label]
        available = all(identity is not None for identity in identities[label].values())
        _require(type(value) is dict and set(value) == {"available", "heads"} and type(value["heads"]) is dict
                 and set(value["heads"]) == set(HEADS), "closed source comparison head inventory required")
        heads = {}
        for name in HEADS:
            head = value["heads"][name]
            selected_head = evaluation["heads"][name]
            _require(type(head) is dict and set(head) == {"codec_sha256", "summary", "rows"}
                     and type(head["rows"]) is list and len(head["rows"]) == len(selected_head["rows"]),
                     "all selected comparison rows required")
            codec = initialization["primary" if name == "primary384" else "legacy8"]["codec"]
            rows = []
            for actual, original in zip(head["rows"], selected_head["rows"]):
                status = "evaluated" if label == "original_donor" else ("model_unavailable" if not available else
                    "evaluated" if original["native_status"] == "ready" else original["native_status"] + "_native")
                expected = {"id": original["id"], "source_sha256": original["source_sha256"],
                    "evaluation_role": original["evaluation_role"], "reference_sha256": original["reference"]["target_sha256"],
                    "status": status, "input_sha256": None, "generation": None, "score": None}
                if status == "evaluated":
                    _require(type(actual) is dict and "generation" in actual, "saved generation required")
                    receipt = actual["generation"]
                    generation.inspect_source_only_generation(receipt)
                    selected = original["generation_input"] if label == "original_donor" else original["native_generation_input"]
                    variant = ("donor384" if name == "primary384" else "legacy8") if label == "original_donor" else "student768"
                    _require(receipt["head"] == name and receipt["variant"] == variant
                             and receipt["input_vector_sha256"] == selected["input_sha256"]
                             and receipt["numerical_input_sha256"] == digest([struct.unpack("!f", struct.pack("!f", value))[0]
                                                                           for value in selected["input_vector"]])
                             and receipt["model_state_sha256_before"] == receipt["model_state_sha256_after"]
                                 == state_identities[label][name]
                             and receipt["max_new_tokens"] == selected_head["max_new_tokens"]
                             and receipt["inherited_max_target_tokens"] == selected_head["inherited_max_target_tokens"],
                             "generation input, head or fixed budget differs")
                    expected.update(input_sha256=selected["input_sha256"], generation=receipt,
                        score=source.score_generation({key: receipt[key] for key in ("generated_ids", "terminated", "truncated")},
                            original["reference"], codec, name))
                _require(_raw(actual) == _raw(expected), "saved source row scoring, input or accounting differs")
                rows.append(expected)
            heads[name] = {"codec_sha256": selected_head["codec_sha256"], "summary": _head_summary(rows), "rows": rows}
        variants[label] = {"available": available, "heads": heads}
    expected = _envelope(evaluation, identities, variants)
    _require(_raw(report) == _raw(expected), "saved source comparison envelope or metrics differ")
    return {"schema": "gte-decoder-source-comparison-inspection/v1", "status": report["status"],
        "report_content_sha256": digest(report), "evaluation_plan_sha256": evaluation["plan_sha256"],
        "scoring_reconstructed": True, "numerical_execution_authenticated": False,
        "optimizer_steps": 0, **{name: False for name in FALSE_FLAGS}}


__all__ = ["compare_source_decoders", "inspect_source_comparison", "digest", "SCHEMA"]
