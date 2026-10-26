"""Same four retained autonomous calls with the explicit v2 policy boundary.

The original exact owning-test module supplies its module-scoped cohort and
four-output durability/reference gate. No targets, donors or inputs are copied,
encoded or interpreted by this candidate preparation. Execution is not enrolled
until the pure-policy qualification and original resource closeout are accepted.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import stat

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_completion_budget_v2 as budget
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_persistent_runtime_v2 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_persistent_v1 as trained
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical

_HELPER_PATH = Path(__file__).absolute().with_name("test_legal_compact_content_persistent_runtime_v1.py")
_HELPER_SHA = "fb2608cd31c79d9912d287bd3612a88e47e92cbc5e08e3d85ff3a4b4cfe36726"


def _helper_source():
    info = _HELPER_PATH.lstat()
    assert _HELPER_PATH.resolve(strict=True) == _HELPER_PATH
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == 23822
    assert hashlib.sha256(_HELPER_PATH.read_bytes()).hexdigest() == _HELPER_SHA


_helper_source()
from tests.unit.logic.autoformal import test_legal_compact_content_persistent_runtime_v1 as controls
assert Path(controls.__file__).absolute() == _HELPER_PATH
_helper_source()

MODES = controls.MODES
MAX_NEW_TOKENS = controls.MAX_NEW_TOKENS
MAX_FORCED_TOKENS = 8
COUNTERS = controls.COUNTERS
cohort = controls.cohort
one_thread = controls.one_thread
wire, sha, digest = controls.wire, controls.sha, controls.digest
read_reference, write_exclusive = controls.read_reference, controls.write_exclusive
no_authority, maximum_difference = controls.no_authority, controls.maximum_difference


@pytest.fixture(scope="module", autouse=True)
def original_helper_source_fence():
    _helper_source()
    yield
    _helper_source()


def assert_saved_trace(report, checkpoint, vector, context, max_new_tokens):
    observed = controls.assert_saved_trace(report, checkpoint, vector, context, max_new_tokens)
    assert report["schema"] == subject.SCHEMA and report["profile"] == subject.PROFILE
    assert report["settings"]["max_forced_tokens"] == MAX_FORCED_TOKENS
    assert report["settings"]["budget_policy"] == budget.POLICY
    assert report["settings"]["forced_lookahead_opt_in"] is True
    assert report["settings"]["forced_horizon_excludes_initial_choice"] is True
    removals = 0
    for prefix in [step["budget_prefix_report"] for step in report["trace"]] + [report["final_prefix_report"]]:
        assert prefix["schema"] == budget.PREFIX_SCHEMA and prefix["policy"] == budget.POLICY
        assert prefix["max_forced_tokens"] == MAX_FORCED_TOKENS
        assert prefix["forced_horizon_excludes_initial_choice"] is True
        assert prefix["global_completability_proven"] is False
        assert prefix["branch_search_performed"] is prefix["model_or_future_score_queries"] is False
        original = prefix["baseline_prefix_report"]
        assert set(prefix["allowed_token_ids"]) <= set(original["allowed_token_ids"])
        rows = prefix["candidate_lookahead"]
        assert [row["token_id"] for row in rows] == original["allowed_token_ids"]
        removed = {row["token_id"] for row in rows if row["disposition"] == "remove_proven_dead_end"}
        assert removed == set(original["allowed_token_ids"]) - set(prefix["allowed_token_ids"])
        assert removed == set(prefix["removed_token_ids"])
        removals += len(removed)
        for row in rows:
            assert len(row["forced_token_ids"]) <= MAX_FORCED_TOKENS
            assert row["terminal_remaining_new_tokens"] == prefix["remaining_new_tokens"] - 1 - len(row["forced_token_ids"])
            assert row["terminal_prefix_ids"] == prefix["offered_ids"] + [row["token_id"]] + row["forced_token_ids"]
            if row["disposition"] == "remove_proven_dead_end":
                assert row["terminal_status"] != "complete" and row["terminal_allowed_token_ids"] == []
                assert row["completion_witness"] is None
            elif row["disposition"] == "keep_witness":
                assert row["terminal_status"] == "complete" and row["terminal_prefix_ids"][-1] == 2
                assert row["completion_witness"]["model_generated_completion"] is False
            else:
                assert row["disposition"] == "keep_unknown" and row["completion_witness"] is None
    return dict(observed, max_forced_tokens=MAX_FORCED_TOKENS,
                forced_lookahead_removed_choices=removals,
                new_numerical_forwards_for_witness_validation=0)


@pytest.mark.parametrize("mode", list(MODES))
def test_retained_persistent_v2_autonomous_generation_and_saved_comparison(mode, cohort, tmp_path):
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
            expected_conditioning_mode=mode, expected_source_space=serving["source_space"],
            max_new_tokens=max_new_tokens, max_forced_tokens=MAX_FORCED_TOKENS)
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
                       {"expected_context_sha256":"0"*64}, {"max_new_tokens":True},
                       {"max_new_tokens":101}, {"max_forced_tokens":True},
                       {"max_forced_tokens":-1}, {"max_forced_tokens":17}):
            with pytest.raises(ValueError):
                generate(rows[0], **change)
        with pytest.raises(ValueError):
            subject.generate_from_bos(checkpoint["initial_checkpoint"], rows[0]["conditioning"], context,
                expected_checkpoint_sha256=digest(checkpoint["initial_checkpoint"]), expected_context_sha256=sha(context),
                expected_conditioning_mode=mode, expected_source_space=serving["source_space"],
                max_new_tokens=100, max_forced_tokens=MAX_FORCED_TOKENS)
        with pytest.raises(TypeError):
            subject.generate_from_bos(checkpoint, rows[0]["conditioning"], context,
                expected_checkpoint_sha256=digest(checkpoint), expected_context_sha256=sha(context),
                expected_conditioning_mode=mode, expected_source_space=serving["source_space"],
                max_new_tokens=100, max_forced_tokens=MAX_FORCED_TOKENS, target_ids=[1,2])
        with pytest.raises(TypeError):
            subject.generate_from_bos(checkpoint, rows[0]["conditioning"], context,
                expected_checkpoint_sha256=digest(checkpoint), expected_context_sha256=sha(context),
                expected_conditioning_mode=mode, expected_source_space=serving["source_space"],
                max_new_tokens=100)
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
        "max_forced_tokens":MAX_FORCED_TOKENS, "consumer_schema":subject.SCHEMA,
        "consumer_profile":subject.PROFILE, "budget_policy":budget.POLICY,
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
