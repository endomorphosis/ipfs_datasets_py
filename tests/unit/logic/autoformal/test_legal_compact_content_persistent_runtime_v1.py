"""Retained persistent BOS generation, without fitting or target-prefix input.

Only a configured owned qualification supplies the private retained-input
manifest. All four autonomous outputs are durable before the module teardown
opens the separate exposed reference targets. No held-out or statutory accuracy
claim follows from this engineering population.
"""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import stat

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_completion_budget_v1 as budget
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_persistent_runtime_v1 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_persistent_v1 as trained
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as tokens
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical


MODES = ("every_step", "first_step")
MAX_NEW_TOKENS = 100
COUNTERS = ("gru_constructions", "state_restores", "gru_forwards", "selector_calls",
    "adam_constructions", "cross_entropy_calls", "autograd_grad_calls", "backward_calls",
    "clip_calls", "optimizer_updates")


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def read_reference(pin, maximum=4*1024**2):
    assert type(pin) is dict and set(pin) == {"path", "bytes", "sha256"}
    path = Path(pin["path"])
    assert path.is_absolute() and path.resolve(strict=True) == path
    with os.fdopen(os.open(path, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1
        assert 0 < before.st_size == pin["bytes"] <= maximum
        raw = stream.read(maximum+1)
        after = os.fstat(stream.fileno())
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    assert identity(before) == identity(after) == identity(path.lstat())
    assert len(raw) == pin["bytes"] and sha(raw) == pin["sha256"]
    return raw


def write_exclusive(path, raw):
    with path.open("xb") as stream:
        assert stream.write(raw) == len(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY|os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}


def no_authority(value):
    assert value["authority"] and all(flag is False for flag in value["authority"].values())
    assert type(value["training_mask"]) is int and value["training_mask"] == 0
    assert type(value["evaluation_gold_mask"]) is int and value["evaluation_gold_mask"] == 0


def maximum_difference(a, b):
    assert len(a) == len(b) == 537
    return max(abs(x-y) for x, y in zip(a, b, strict=True))


@pytest.fixture(scope="module", autouse=True)
def one_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        yield
    finally:
        torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def cohort(tmp_path_factory):
    spelling = os.environ.get("LEGAL_IR_PERSISTENT_GENERATION_INPUTS")
    if not spelling:
        pytest.skip("Owned retained-checkpoint generation input manifest is not configured")
    manifest_path = Path(spelling)
    assert manifest_path.is_absolute() and manifest_path.resolve(strict=True) == manifest_path
    raw = manifest_path.read_bytes()
    assert 0 < len(raw) <= 1024**2
    manifest = json.loads(raw)
    assert manifest["schema"] == "legal-ir-persistent-generation-inputs/v1"
    assert manifest["modes"] == list(MODES) and set(manifest["donors"]) == set(MODES)
    assert manifest["max_new_tokens"] == MAX_NEW_TOKENS and manifest["generation_calls_per_mode"] == 2
    assert manifest["reference_open_policy"] == "after_all_four_generation_outputs_are_durable"
    assert manifest["exposed_authored_fixtures"] is True and manifest["independent_legal_gold"] is False
    serving_raw = read_reference(manifest["serving_panel"])
    serving = json.loads(serving_raw)
    assert serving["schema"] == "legal-ir-persistent-generation-serving-panel/v1"
    assert serving["contains_reference_targets"] is False and serving["training_mask"] == serving["evaluation_gold_mask"] == 0
    assert all(set(row) == {"id", "source_group", "source_utf8", "conditioning"} for row in serving["rows"])
    assert len(serving["rows"]) == len({row["id"] for row in serving["rows"]}) == 2
    assert len({row["source_group"] for row in serving["rows"]}) == 2
    context = serving["context_utf8"].encode("utf-8")
    assert sha(context) == serving["context_sha256"]
    directory = tmp_path_factory.mktemp("persistent-generation-cohort", numbered=False)
    shared = {"manifest": manifest, "serving": serving, "context": context,
        "records": [], "mode_panels": [], "reference_targets_opened": False,
        "directory": directory, "serving_raw": serving_raw}
    yield shared

    # This barrier is the only point that parses reference IDs or target ASTs.
    # It runs after both parameterized modes have durably saved their outputs.
    records = shared["records"]
    assert len(records) == 4
    assert {(r["mode"], r["row_id"]) for r in records} == {
        (mode, row["id"]) for mode in MODES for row in serving["rows"]}
    durable_reports = []
    for record in records:
        raw = read_reference(record["report"], maximum=64*1024**2)
        durable_reports.append((record, json.loads(raw)))
    barrier = {"schema": "persistent-generation-output-durability-barrier/v1",
        "durable_report_count": 4, "reference_comparison_started": False,
        "durable_reports": [record["report"] for record, _ in durable_reports]}
    barrier_ref = write_exclusive(directory/"four-output-durability-barrier.json", wire(barrier))
    shared["reference_targets_opened"] = True
    reference_raw = read_reference(manifest["reference_targets"])
    references = json.loads(reference_raw)
    assert references["schema"] == "legal-ir-persistent-generation-exposed-references/v1"
    by_id = {row["id"]: row for row in references["rows"]}
    assert set(by_id) == {row["id"] for row in serving["rows"]}
    comparisons = []
    for record, report in durable_reports:
        reference = by_id[record["row_id"]]
        decoded = report["final_decoding"]
        valid = decoded["status"] == "valid_candidate"
        content = decoded["prediction"]["content"] if valid else None
        comparisons.append({"mode": record["mode"], "row_id": record["row_id"],
            "source_group": record["source_group"], "status": report["status"],
            "typed_candidate": valid, "exact_token_ids": report["generated_ids"] == reference["target_ids"],
            "exact_compact_content": valid and content == reference["content"],
            "generated_ids_sha256": digest(report["generated_ids"]),
            "reference_ids_sha256": digest(reference["target_ids"]),
            "generated_content_sha256": digest(content) if valid else None,
            "reference_content_sha256": digest(reference["content"]),
            "report": record["report"]})
    comparison_ref = write_exclusive(directory/"post-durability-reference-comparison.json", wire(comparisons))
    panel = {"schema": "authored-persistent-generation-cohort-panel/v1",
        "modes": list(MODES), "enrolled_generation_calls": 4, "source_rows": 2, "source_groups": 2,
        "mode_panels": shared["mode_panels"], "durability_barrier": barrier_ref,
        "post_durability_comparison": comparison_ref,
        "reference_targets": manifest["reference_targets"], "reference_opened_after_durable_reports": 4,
        "typed_candidates": sum(row["typed_candidate"] for row in comparisons),
        "exact_token_id_matches": sum(row["exact_token_ids"] for row in comparisons),
        "exact_compact_content_matches": sum(row["exact_compact_content"] for row in comparisons),
        "comparisons": comparisons, "exposed_authored_fixtures": True,
        "heldout_evaluated": False, "source_semantics_verified": False,
        "training_gain_established": False, "evaluation_gold_mask": 0, "training_mask": 0}
    write_exclusive(directory/"authored-persistent-generation-cohort-panel-v1.json", wire(panel))


def assert_saved_trace(report, checkpoint, vector, context, max_new_tokens):
    no_authority(report)
    assert report["checkpoint_sha256"] == digest(checkpoint)
    assert report["weights_sha256"] == checkpoint["weights_sha256"]
    assert report["codec_sha256"] == checkpoint["codec_sha256"]
    assert report["conditioning_mode"] == checkpoint["conditioning_mode"]
    assert report["source_space"] == checkpoint["source_space"]
    assert report["context_raw_sha256"] == sha(context) and report["conditioning_sha256"] == digest(vector)
    assert report["initial_prefix_ids"] == [1]
    assert report["settings"]["max_new_tokens"] == max_new_tokens
    assert report["settings"]["eos_counted_in_new_token_budget"] is True
    assert report["settings"]["incremental_hidden_state"] is True
    assert report["settings"]["cross_call_model_cache"] is False
    assert report["live_checkpoint_runtime_verified"] is True
    assert report["status"] in {"complete", "blocked", "step_budget_exhausted", "report_budget_exhausted"}
    assert report["serving_view_contains_optimizer_state"] is False
    assert report["serving_view_contains_population"] is False
    assert report["serving_view_contains_training_targets"] is False
    assert report["supplied_prefix_target_access"] is False
    assert report["optimizer_constructed"] is report["optimizer_state_restored"] is report["training_executed"] is False
    assert report["actual_model_inputs"] == ["conditioning_vector", "fixed_BOS_and_generated_token_IDs"]
    current, raw_winners, singleton_count = [1], [], 0
    for index, step in enumerate(report["trace"]):
        assert step["prefix_ids"] == current
        assert step["input_token_ids"] == [1 if index == 0 else report["selected_token_ids"][index-1]]
        assert step["consumed_prefix_positions"] == [len(current)]
        scores = step["logits"]
        assert len(scores) == 537 and all(type(x) is float and math.isfinite(x) for x in scores)
        assert step["logits_sha256"] == digest(scores)
        prefix = step["budget_prefix_report"]
        no_authority(prefix)
        assert prefix["offered_ids"] == current
        assert prefix["remaining_new_tokens"] == max_new_tokens-index
        assert prefix["context_raw_sha256"] == sha(context) and prefix["codec_sha256"] == checkpoint["codec_sha256"]
        allowed = prefix["allowed_token_ids"]
        assert allowed and set(allowed) <= set(prefix["baseline_prefix_report"]["allowed_token_ids"])
        raw_id = max(range(537), key=lambda i: (scores[i], -i))
        selected = max(allowed, key=lambda i: (scores[i], -i))
        assert step["raw_argmax_token_id"] == raw_id and step["selected_token_id"] == selected
        assert report["selected_token_ids"][index] == selected
        raw_winners.append(raw_id)
        singleton_count += len(allowed) == 1
        current.append(selected)
    assert report["generated_ids"] == current
    assert len(report["trace"]) == len(report["selected_token_ids"]) == report["numerical_forward_count"] <= max_new_tokens
    assert report["state_positions_consumed"] == len(current)-1
    assert report["model_restore_count"] == report["model_construction_count"] == int(bool(report["trace"]))
    assert report["state_installation_count"] == 2*report["model_restore_count"]
    if 2 in report["selected_token_ids"]:
        assert report["selected_token_ids"][-1] == 2 and report["selected_token_ids"].count(2) == 1
        assert report["status"] == "complete"
    assert report["final_prefix_report"]["offered_ids"] == current
    assert report["final_prefix_report"]["remaining_new_tokens"] == max_new_tokens-len(report["trace"])
    decoded = tokens.decode_compact_content_tokens_v1(current, context,
        expected_context_sha256=sha(context), codec=checkpoint["codec"],
        expected_codec_sha256=checkpoint["codec_sha256"])
    assert decoded == report["final_decoding"]
    assert (report["status"] == "complete") == (decoded["status"] == "valid_candidate")
    no_authority(decoded)
    if decoded["status"] == "valid_candidate":
        no_authority(decoded["prediction"])
    return {"positions": len(report["trace"]), "full_logit_coordinates": 537*len(report["trace"]),
        "forced_singleton_positions": singleton_count,
        "non_singleton_positions": len(report["trace"])-singleton_count,
        "raw_argmax_matches_constrained_selection": sum(a == b for a,b in zip(raw_winners,report["selected_token_ids"])),
        "saved_only_float_argmax_replay": True, "public_typed_decode_replayed": True,
        "new_model_forwards_for_saved_validation": 0}


@pytest.mark.parametrize("mode", list(MODES))
def test_retained_persistent_autonomous_generation_and_saved_comparison(mode, cohort, tmp_path):
    manifest, serving = cohort["manifest"], cohort["serving"]
    donor_raw = read_reference(manifest["donors"][mode])
    donor = json.loads(donor_raw)
    checkpoint = donor["checkpoint"]
    assert checkpoint["conditioning_mode"] == mode
    assert checkpoint["source_space"] == serving["source_space"]
    assert checkpoint["progress"] == {"optimizer_steps": 5, "epochs_completed": 1, "row_cursor": 1}
    original_checkpoint, original_serving = deepcopy(checkpoint), deepcopy(serving)
    assert cohort["reference_targets_opened"] is False
    context = cohort["context"]
    rows = serving["rows"]
    counts = dict.fromkeys(COUNTERS, 0)
    events, records = [], []
    stage = {"value": "closed_refusals"}
    real_gru_init, real_load, real_forward = torch.nn.GRU.__init__, torch.nn.Module.load_state_dict, torch.nn.GRU.forward
    real_select = budget.select_token

    def gru_init(model, *args, **kwargs):
        result = real_gru_init(model, *args, **kwargs)
        counts["gru_constructions"] += 1
        events.append({"stage": stage["value"], "event": "gru_construction"})
        return result

    def restore(model, *args, **kwargs):
        result = real_load(model, *args, **kwargs)
        counts["state_restores"] += 1
        events.append({"stage": stage["value"], "event": "state_restore", "names": list(model.state_dict())})
        return result

    def forward(model, inputs, *args, **kwargs):
        result = real_forward(model, inputs, *args, **kwargs)
        counts["gru_forwards"] += 1
        assert list(inputs.shape) == [1, 1, checkpoint["config"]["token_embedding_dim"]]
        events.append({"stage": stage["value"], "event": "gru_forward", "input_shape": list(inputs.shape)})
        return result

    def select(*args, **kwargs):
        result = real_select(*args, **kwargs)
        counts["selector_calls"] += 1
        events.append({"stage": stage["value"], "event": "budget_selector", "selected": result["selected_token_id"]})
        return result

    def forbidden(name):
        def stopped(*args, **kwargs):
            counts[name] += 1
            pytest.fail("Generation reached forbidden optimizer/loss/backward/training work: "+name)
        return stopped

    def generate(row, *, max_new_tokens=MAX_NEW_TOKENS, **changes):
        args = dict(expected_checkpoint_sha256=digest(checkpoint), expected_context_sha256=sha(context),
            expected_conditioning_mode=mode, expected_source_space=serving["source_space"], max_new_tokens=max_new_tokens)
        args.update(changes)
        return subject.generate_from_bos(checkpoint, row["conditioning"], context, **args)

    rng = torch.get_rng_state().clone()
    artifacts = {}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(torch.nn.GRU, "__init__", gru_init)
        patch.setattr(torch.nn.Module, "load_state_dict", restore)
        patch.setattr(torch.nn.GRU, "forward", forward)
        patch.setattr(budget, "select_token", select)
        for owner, name, counter in ((torch.optim.Adam, "__init__", "adam_constructions"),
                (torch.optim.Optimizer, "__init__", "adam_constructions"),
                (torch.optim.Adam, "step", "optimizer_updates"),
                (torch.nn.functional, "cross_entropy", "cross_entropy_calls"),
                (torch.autograd, "grad", "autograd_grad_calls"),
                (torch.Tensor, "backward", "backward_calls"),
                (torch.nn.utils, "clip_grad_norm_", "clip_calls"),
                (numerical, "_optimizer", "adam_constructions"),
                (trained, "train_compact_content_persistent_v1", "optimizer_updates")):
            patch.setattr(owner, name, forbidden(counter))
        wrong_mode = "first_step" if mode == "every_step" else "every_step"
        for change in ({"expected_conditioning_mode":wrong_mode},
                       {"expected_source_space":"different-unverified-space"},
                       {"expected_context_sha256":"0"*64}, {"max_new_tokens":True}):
            with pytest.raises(ValueError):
                generate(rows[0], **change)
        with pytest.raises(ValueError):
            subject.generate_from_bos(checkpoint["initial_checkpoint"], rows[0]["conditioning"], context,
                expected_checkpoint_sha256=digest(checkpoint["initial_checkpoint"]), expected_context_sha256=sha(context),
                expected_conditioning_mode=mode, expected_source_space=serving["source_space"], max_new_tokens=100)
        with pytest.raises(TypeError):
            subject.generate_from_bos(checkpoint, rows[0]["conditioning"], context,
                expected_checkpoint_sha256=digest(checkpoint), expected_context_sha256=sha(context),
                expected_conditioning_mode=mode, expected_source_space=serving["source_space"],
                max_new_tokens=100, target_ids=[1,2])
        assert not any(counts.values())

        stage["value"] = "initial_one_token_budget"
        blocked = generate(rows[0], max_new_tokens=1)
        assert blocked["status"] == "blocked" and blocked["generated_ids"] == [1]
        assert blocked["model_restore_count"] == blocked["numerical_forward_count"] == 0
        assert blocked["live_checkpoint_runtime_verified"] is True
        assert_saved_trace(blocked, checkpoint, rows[0]["conditioning"], context, 1)
        assert not any(counts.values())
        artifacts["initial-budget-blocked.json"] = write_exclusive(tmp_path/"initial-budget-blocked.json", wire(blocked))

        reports = []
        for index, row in enumerate(rows):
            stage["value"] = "autonomous_row_"+str(index)
            before = dict(counts)
            report = generate(row)
            no_authority(report)
            assert report["model_restore_count"] == 1 and report["numerical_forward_count"] >= 1
            name = "generation-row-"+str(index)+".json"
            report_ref = write_exclusive(tmp_path/name, wire(report))
            assert read_reference(report_ref, maximum=64*1024**2) == wire(report)
            artifacts[name] = report_ref
            assert subject.generation_sha256(report) == digest(report)
            assert counts["gru_constructions"]-before["gru_constructions"] == report["model_restore_count"]
            assert counts["state_restores"]-before["state_restores"] == 2*report["model_restore_count"]
            assert counts["gru_forwards"]-before["gru_forwards"] == report["numerical_forward_count"]
            assert counts["selector_calls"]-before["selector_calls"] == len(report["trace"])
            assert not cohort["reference_targets_opened"]
            record = {"mode":mode, "row_id":row["id"], "source_group":row["source_group"], "report":report_ref}
            cohort["records"].append(record)
            records.append(record)
            reports.append(report)

        stage["value"] = "saved_trace_and_typed_decode"
        before = dict(counts)
        checks = [assert_saved_trace(report, checkpoint, row["conditioning"], context, MAX_NEW_TOKENS)
                  for report,row in zip(reports,rows,strict=True)]
        assert counts == before and not cohort["reference_targets_opened"]
        artifacts["saved-trace-validation.json"] = write_exclusive(tmp_path/"saved-trace-validation.json", wire(checks))

        stage["value"] = "independent_qualified_BOS_score"
        before = dict(counts)
        score = trained.score_compact_content_persistent_v1(checkpoint, rows[0]["conditioning"], [1],
            expected_checkpoint_sha256=digest(checkpoint), expected_conditioning_mode=mode,
            expected_source_space=serving["source_space"])
        assert counts["gru_constructions"]-before["gru_constructions"] == 1
        assert counts["state_restores"]-before["state_restores"] == 2
        assert counts["gru_forwards"]-before["gru_forwards"] == 1
        no_authority(score)
        assert len(score["logits"]) == 1 and len(score["logits"][0]) == 537
        parity_error = None
        if reports[0]["trace"]:
            parity_error = maximum_difference(reports[0]["trace"][0]["logits"], score["logits"][0])
            assert parity_error <= 1e-6
        artifacts["independent-bos-score.json"] = write_exclusive(tmp_path/"independent-bos-score.json", wire(score))

    assert torch.equal(rng, torch.get_rng_state()) and torch.get_num_threads() == 1
    assert checkpoint == original_checkpoint and serving == original_serving
    actual_restores = sum(report["model_restore_count"] for report in reports)
    actual_forwards = sum(report["numerical_forward_count"] for report in reports)
    assert counts["gru_constructions"] == actual_restores+1 <= 3
    assert counts["state_restores"] == 2*(actual_restores+1) <= 6
    assert counts["gru_forwards"] == actual_forwards+1 <= 201
    assert counts["selector_calls"] == actual_forwards <= 200
    assert all(counts[key] == 0 for key in COUNTERS if key not in
               ("gru_constructions", "state_restores", "gru_forwards", "selector_calls"))
    artifacts["observed-events.json"] = write_exclusive(tmp_path/"observed-events.json", wire(events))
    panel = {"schema":"authored-persistent-generation-mode-panel/v1", "mode":mode,
        "counts":counts, "generation_calls":2, "max_new_tokens":100,
        "generation_model_restore_count":actual_restores,
        "generation_forward_count":actual_forwards, "qualified_score_reference_forward_count":1,
        "BOS_score_max_absolute_error":parity_error, "artifacts":artifacts,
        "generation_reports":[record["report"] for record in records],
        "checkpoint_sha256":digest(checkpoint), "weights_sha256":checkpoint["weights_sha256"],
        "donor":manifest["donors"][mode], "source_space":serving["source_space"],
        "serving_panel":manifest["serving_panel"],
        "references_opened_during_generation_or_mode_case":False,
        "all_outputs_saved_before_reference_comparison":True,
        "scope":{"exposed_authored_fixtures":True,"heldout_evaluated":False,
            "training_executed":False,"source_encoder_executed":False,"generation_executed":bool(actual_forwards),
            "unconstrained_autoregression_measured":False,"source_semantics_verified":False,
            "training_gain_established":False,"graph_admitted":False,"Lean_executed":False,
            "training_mask":0,"evaluation_gold_mask":0}}
    pin = write_exclusive(tmp_path/"authored-persistent-generation-mode-panel-v1.json", wire(panel))
    cohort["mode_panels"].append(pin)
