"""Same four retained autonomous calls with the explicit branch policy boundary.

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

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_branch_selection_v1 as budget
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_persistent_runtime_v3 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_persistent_v1 as trained
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as tokens
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
MAX_PREFIX_INSPECTIONS_PER_DECISION = 32
MAX_PREFIX_INSPECTIONS_PER_GENERATION = 1024
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


def assert_saved_trace(report, checkpoint, vector, context, max_new_tokens,
        *, max_generation=MAX_PREFIX_INSPECTIONS_PER_GENERATION):
    """Replay saved scores/proof accounting only; no model/search replay."""
    no_authority(report)
    assert report["schema"] == subject.SCHEMA and report["profile"] == subject.PROFILE
    for key in ("weights_sha256", "codec_sha256", "conditioning_mode", "source_space"):
        assert report[key] == checkpoint[key]
    assert report["checkpoint_sha256"] == digest(checkpoint)
    assert report["context_raw_sha256"] == sha(context) and report["conditioning_sha256"] == digest(vector)
    assert report["initial_prefix_ids"] == [1]
    settings = report["settings"]
    assert settings["max_new_tokens"] == max_new_tokens
    assert settings["max_prefix_inspections_per_decision"] == MAX_PREFIX_INSPECTIONS_PER_DECISION
    assert settings["max_prefix_inspections_per_generation"] == max_generation
    assert settings["budget_policy"] == budget.POLICY
    assert settings["eos_counted_in_new_token_budget"] is True
    assert settings["incremental_hidden_state"] is True and settings["cross_call_model_cache"] is False
    assert report["status"] in {"complete", "blocked", "step_budget_exhausted",
        "report_budget_exhausted", "grammar_budget_exhausted"}
    assert report["live_checkpoint_runtime_verified"] is True
    for key in ("serving_view_contains_optimizer_state", "serving_view_contains_population",
                "serving_view_contains_training_targets", "supplied_prefix_target_access",
                "optimizer_constructed", "optimizer_state_restored", "training_executed"):
        assert report[key] is False
    assert report["actual_model_inputs"] == ["conditioning_vector", "fixed_BOS_and_generated_token_IDs"]
    root = report["initial_prefix_report"]
    no_authority(root)
    assert root["offered_ids"] == [1] and root["remaining_new_tokens"] == max_new_tokens
    assert root["context_raw_sha256"] == sha(context) and root["codec_sha256"] == checkpoint["codec_sha256"]
    current, raw_winners, singleton_count, work, witness_calls, removed_count = [1], [], 0, 1, 0, 0
    terminal = report["terminal_no_selection_trace"]
    steps = list(report["trace"]) + ([] if terminal is None else [terminal])
    for index, step in enumerate(steps):
        assert step["prefix_ids"] == current
        assert step["input_token_ids"] == [1 if index == 0 else current[-1]]
        assert step["consumed_prefix_positions"] == [len(current)]
        scores = step["logits"]
        assert len(scores) == 537 and all(type(x) is float and math.isfinite(x) for x in scores)
        assert step["logits_sha256"] == digest(scores)
        selected = step["selection_report"]
        no_authority(selected)
        assert selected["schema"] == budget.SCHEMA and selected["policy"] == budget.POLICY
        assert selected["offered_prefix_ids"] == current and selected["logits"] == scores
        assert selected["logits_sha256"] == digest(scores)
        assert selected["max_prefix_inspections"] == min(MAX_PREFIX_INSPECTIONS_PER_DECISION, max_generation-work)
        assert selected["baseline_prefix_report"]["remaining_new_tokens"] == max_new_tokens-len(raw_winners)
        assert selected["context_raw_sha256"] == sha(context) and selected["codec_sha256"] == checkpoint["codec_sha256"]
        assert selected["witness_suffix_injected"] is selected["model_or_future_score_queries"] is False
        assert selected["global_completability_proven"] is False
        assert selected["actual_prefix_inspections"] == 1 + sum(r["actual_prefix_inspections"] for r in selected["candidate_results"])
        assert 1 <= selected["actual_prefix_inspections"] <= selected["max_prefix_inspections"]
        work += selected["actual_prefix_inspections"]
        witness_calls += selected["witness_calls"]
        rows = selected["candidate_results"]
        baseline = selected["baseline_prefix_report"]["allowed_token_ids"]
        assert selected["candidate_order"] == sorted(baseline, key=lambda token: (-scores[token], token))
        removed = {r["token_id"] for r in rows if r["disposition"] == "remove_proven_dead_end"}
        assert removed == set(selected["removed_token_ids"])
        assert set(selected["allowed_token_ids"]) == set(baseline) - removed
        removed_count += len(removed)
        for row in rows:
            if row["certificate_retained"]:
                certificate = selected["certificates"][row["certificate_index"]]
                assert digest(certificate) == row["certificate_sha256"]
                assert certificate["actual_prefix_inspections"] == row["actual_prefix_inspections"]
                assert certificate["offered_ids"] == current+[row["token_id"]]
                assert certificate["remaining_new_tokens"] == max_new_tokens-len(raw_winners)-1
                no_authority(certificate)
                if row["token_id"] in removed:
                    assert certificate["status"] == "DEAD_END"
                    assert certificate["frontier_closed"] is certificate["exhaustive_relative_to_original_policy"] is True
                    assert certificate["unresolved_frontier_root_count"] == 0
                elif certificate["status"] == "WITNESS":
                    assert certificate["witness"]["syntactic_only"] is True
                    assert certificate["witness"]["model_generated_completion"] is False
            if not row["queried"]:
                assert row["actual_prefix_inspections"] == 0 and row["token_id"] not in removed
        raw_id = max(range(537), key=lambda token: (scores[token], -token))
        assert step["raw_argmax_token_id"] == selected["raw_argmax_token_id"] == raw_id
        allowed = selected["allowed_token_ids"]
        token = max(allowed, key=lambda token: (scores[token], -token)) if allowed else None
        assert step["selected_token_id"] == selected["selected_token_id"] == token
        if step is terminal:
            assert index == len(steps)-1 and token is None
            assert selected["status"] == "no_selection" and selected["next_prefix_ids"] == current
            assert report["status"] == "blocked"
        else:
            assert token is not None and selected["next_prefix_ids"] == current+[token]
            assert report["selected_token_ids"][index] == token
            raw_winners.append(raw_id)
            singleton_count += len(allowed) == 1
            current.append(token)
    assert report["generated_ids"] == current
    assert len(report["trace"]) == len(report["selected_token_ids"]) == report["selected_token_decisions"]
    assert report["terminal_no_selection_decisions"] == int(terminal is not None)
    assert report["numerical_forward_count"] == report["selector_decision_count"] == len(steps) <= max_new_tokens
    assert report["state_positions_consumed"] == len(current)-1+int(terminal is not None)
    assert report["model_restore_count"] == report["model_construction_count"] == int(bool(steps))
    assert report["state_installation_count"] == 2*report["model_restore_count"]
    accounting = report["grammar_accounting"]
    assert accounting["initial_root_prefix_inspections"] == 1
    assert accounting["decision_prefix_inspections"] == work-1
    assert accounting["actual_prefix_inspections"] == work <= max_generation
    assert accounting["remaining_prefix_inspections"] == max_generation-work
    assert accounting["witness_calls"] == witness_calls
    if report["status"] == "grammar_budget_exhausted":
        assert accounting["remaining_prefix_inspections"] == 0
    if 2 in report["selected_token_ids"]:
        assert report["selected_token_ids"][-1] == 2 and report["selected_token_ids"].count(2) == 1
        assert report["status"] == "complete" and terminal is None
    decoded = tokens.decode_compact_content_tokens_v1(current, context,
        expected_context_sha256=sha(context), codec=checkpoint["codec"],
        expected_codec_sha256=checkpoint["codec_sha256"])
    assert decoded == report["final_decoding"]
    assert (report["status"] == "complete") == (decoded["status"] == "valid_candidate")
    no_authority(decoded)
    return {"positions":len(steps), "selected_positions":len(raw_winners),
        "terminal_no_selection_positions":int(terminal is not None),
        "full_logit_coordinates":537*len(steps), "forced_singleton_positions":singleton_count,
        "non_singleton_positions":len(raw_winners)-singleton_count,
        "raw_argmax_matches_constrained_selection":sum(a==b for a,b in zip(raw_winners, report["selected_token_ids"],strict=True)),
        "saved_only_float_argmax_replay":True,"public_typed_decode_replayed":True,
        "actual_generation_prefix_inspections":work,"proven_dead_choices_removed":removed_count,
        "new_model_forwards_for_saved_validation":0,"new_search_queries_for_saved_validation":0}


@pytest.mark.parametrize("mode", list(MODES))
def test_retained_persistent_v3_autonomous_generation_and_saved_comparison(mode, cohort, tmp_path):
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
            max_new_tokens=max_new_tokens,
            max_prefix_inspections_per_decision=MAX_PREFIX_INSPECTIONS_PER_DECISION,
            max_prefix_inspections_per_generation=MAX_PREFIX_INSPECTIONS_PER_GENERATION)
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
                       {"max_new_tokens":101}, {"max_prefix_inspections_per_decision":True},
                       {"max_prefix_inspections_per_decision":0}, {"max_prefix_inspections_per_decision":1025}, {"max_prefix_inspections_per_generation":True}, {"max_prefix_inspections_per_generation":0}, {"max_prefix_inspections_per_generation":102402}):
            with pytest.raises(ValueError):
                generate(rows[0], **change)
        with pytest.raises(ValueError):
            subject.generate_from_bos(checkpoint["initial_checkpoint"], rows[0]["conditioning"], context,
                expected_checkpoint_sha256=digest(checkpoint["initial_checkpoint"]), expected_context_sha256=sha(context),
                expected_conditioning_mode=mode, expected_source_space=serving["source_space"],
                max_new_tokens=100,
                max_prefix_inspections_per_decision=MAX_PREFIX_INSPECTIONS_PER_DECISION,
                max_prefix_inspections_per_generation=MAX_PREFIX_INSPECTIONS_PER_GENERATION)
        with pytest.raises(TypeError):
            subject.generate_from_bos(checkpoint, rows[0]["conditioning"], context,
                expected_checkpoint_sha256=digest(checkpoint), expected_context_sha256=sha(context),
                expected_conditioning_mode=mode, expected_source_space=serving["source_space"],
                max_new_tokens=100, max_prefix_inspections_per_decision=MAX_PREFIX_INSPECTIONS_PER_DECISION,
                max_prefix_inspections_per_generation=MAX_PREFIX_INSPECTIONS_PER_GENERATION, target_ids=[1,2])
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

        stage["value"] = "initial_one_inspection_budget"
        grammar_blocked = generate(rows[0], max_prefix_inspections_per_generation=1)
        assert grammar_blocked["status"] == "grammar_budget_exhausted" and grammar_blocked["generated_ids"] == [1]
        assert grammar_blocked["model_restore_count"] == grammar_blocked["numerical_forward_count"] == 0
        assert_saved_trace(grammar_blocked, checkpoint, rows[0]["conditioning"], context, 100, max_generation=1)
        assert not any(counts.values())
        artifacts["initial-grammar-budget-blocked.json"] = write_exclusive(tmp_path/"initial-grammar-budget-blocked.json", wire(grammar_blocked))

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
            assert counts["selector_calls"]-before["selector_calls"] == report["selector_decision_count"]
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
        first_decision = (reports[0]["trace"][0] if reports[0]["trace"]
                          else reports[0]["terminal_no_selection_trace"])
        if first_decision is not None:
            parity_error = maximum_difference(first_decision["logits"], score["logits"][0])
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
        "max_prefix_inspections_per_decision":MAX_PREFIX_INSPECTIONS_PER_DECISION,
        "max_prefix_inspections_per_generation":MAX_PREFIX_INSPECTIONS_PER_GENERATION, "consumer_schema":subject.SCHEMA,
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
