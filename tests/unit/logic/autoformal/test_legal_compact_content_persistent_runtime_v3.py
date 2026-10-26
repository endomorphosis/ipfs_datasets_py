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


# Additional boundary-only selectors use their own target-free fixture. They do
# not request cohort or change its original four-output reference barrier above.
from contextlib import contextmanager as _boundary_contextmanager
import builtins as _boundary_builtins
import io as _boundary_io
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_completion_budget_v1 as _boundary_prefix
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_completion_budget_v3 as _boundary_witness
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment_v2 as _boundary_adapter


@pytest.fixture
def boundary_inputs(monkeypatch, tmp_path):
    spelling = controls.os.environ.get("LEGAL_IR_PERSISTENT_GENERATION_INPUTS")
    if not spelling:
        pytest.skip("Owned retained-checkpoint boundary inputs are not configured")
    path = Path(spelling)
    assert path.is_absolute() and path.resolve(strict=True) == path
    metadata_raw = path.read_bytes()
    assert len(metadata_raw) == 5437
    assert sha(metadata_raw) == "98cfa7f8513754e9ee8f178a0767b4fad92ada541781fa85cac4e68152c64397"
    manifest = json.loads(metadata_raw)
    assert manifest["schema"] == "legal-ir-persistent-generation-inputs/v1"
    assert manifest["modes"] == list(MODES)
    assert manifest["exposed_authored_fixtures"] is True and manifest["independent_legal_gold"] is False
    forbidden_path = Path(manifest["reference_targets"]["path"])
    assert forbidden_path.is_absolute()
    reference_attempts = []
    real_builtin, real_io, real_os = _boundary_builtins.open, _boundary_io.open, controls.os.open

    def forbid_reference(file):
        if isinstance(file, (str, bytes, controls.os.PathLike)):
            offered = Path(controls.os.fsdecode(file)).absolute()
            if offered == forbidden_path or offered.resolve(strict=False) == forbidden_path:
                reference_attempts.append(str(offered))
                raise AssertionError("boundary controls must never open reference target payloads")

    def builtin_open(file, *args, **kwargs):
        forbid_reference(file)
        return real_builtin(file, *args, **kwargs)

    def io_open(file, *args, **kwargs):
        forbid_reference(file)
        return real_io(file, *args, **kwargs)

    def os_open(file, *args, **kwargs):
        forbid_reference(file)
        return real_os(file, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(_boundary_builtins, "open", builtin_open)
        patch.setattr(_boundary_io, "open", io_open)
        patch.setattr(controls.os, "open", os_open)
        serving_raw = read_reference(manifest["serving_panel"])
        serving = json.loads(serving_raw)
        assert serving["schema"] == "legal-ir-persistent-generation-serving-panel/v1"
        assert serving["contains_reference_targets"] is False
        assert serving["training_mask"] == serving["evaluation_gold_mask"] == 0
        assert len(serving["rows"]) == 2
        assert all(set(row) == {"id", "source_group", "source_utf8", "conditioning"} for row in serving["rows"])
        context = serving["context_utf8"].encode("utf-8")
        assert sha(context) == serving["context_sha256"]
        assert [len(symbol["domain"]) for symbol in json.loads(context)["signature"]["symbols"]] == [2]
        donor_raw = read_reference(manifest["donors"]["every_step"])
        checkpoint = json.loads(donor_raw)["checkpoint"]
        assert checkpoint["conditioning_mode"] == "every_step"
        assert checkpoint["source_space"] == serving["source_space"]
        assert checkpoint["progress"] == {"optimizer_steps": 5, "epochs_completed": 1, "row_cursor": 1}
        shared = dict(checkpoint=checkpoint, row=serving["rows"][0], context=context,
            reference_targets_opened=False, reference_open_attempts=reference_attempts)
        yield shared
        assert not reference_attempts and shared["reference_targets_opened"] is False
        assert path.read_bytes() == metadata_raw
        assert read_reference(manifest["serving_panel"]) == serving_raw
        assert read_reference(manifest["donors"]["every_step"]) == donor_raw
        write_exclusive(tmp_path / "boundary-input-closeout.json", wire(dict(
            schema="persistent-runtime-v3-boundary-input-closeout/v1",
            input_manifest_sha256=sha(metadata_raw),
            serving_panel=manifest["serving_panel"], donor=manifest["donors"]["every_step"],
            raw_reference_payload_forbidden=True, reference_open_attempts=0,
            reference_targets_opened=False, primary_quality_comparison_performed=False,
            retained_inputs_unchanged=True)))


@_boundary_contextmanager
def _boundary_observations():
    counts = dict.fromkeys(COUNTERS, 0)
    observed = dict(counts=counts, events=[], prefixes=[], selectors=[], searches=[], decodes=[])
    real_gru, real_load, real_forward = torch.nn.GRU.__init__, torch.nn.Module.load_state_dict, torch.nn.GRU.forward
    real_prefix, real_select = _boundary_prefix.allowed_token_ids, budget.select_token
    real_search, real_decode = _boundary_witness.find_completion_witness, tokens.decode_compact_content_tokens_v1

    def gru(*args, **kwargs):
        value = real_gru(*args, **kwargs)
        counts['gru_constructions'] += 1
        observed['events'].append(dict(event='gru_construction'))
        return value

    def load(*args, **kwargs):
        value = real_load(*args, **kwargs)
        counts['state_restores'] += 1
        observed['events'].append(dict(event='state_installation'))
        return value

    def forward(model, inputs, *args, **kwargs):
        value = real_forward(model, inputs, *args, **kwargs)
        counts['gru_forwards'] += 1
        observed['events'].append(dict(event='gru_forward', input_shape=list(inputs.shape)))
        return value

    def prefix(*args, **kwargs):
        report = real_prefix(*args, **kwargs)
        observed['prefixes'].append(dict(offered_ids=list(args[0]),
            remaining_new_tokens=kwargs['remaining_new_tokens'], status=report['status'], reason=report['reason'],
            allowed_token_ids=list(report['allowed_token_ids']), report_sha256=digest(report)))
        return report

    def search(*args, **kwargs):
        begin = len(observed['prefixes'])
        report = real_search(*args, **kwargs)
        observed['searches'].append(dict(report=report, prefix_begin=begin,
            prefix_end=len(observed['prefixes']), actual_allowance=kwargs['max_prefix_inspections']))
        return report

    def select(*args, **kwargs):
        begin, search_begin = len(observed['prefixes']), len(observed['searches'])
        report = real_select(*args, **kwargs)
        counts['selector_calls'] += 1
        observed['selectors'].append(dict(report=report, prefix_begin=begin,
            prefix_end=len(observed['prefixes']), search_begin=search_begin,
            search_end=len(observed['searches']), actual_allowance=kwargs['max_prefix_inspections']))
        return report

    def decode(*args, **kwargs):
        report = real_decode(*args, **kwargs)
        observed['decodes'].append(report)
        return report

    def forbidden(name):
        def refuse(*args, **kwargs):
            counts[name] += 1
            pytest.fail('v3 generation reached forbidden training operation: ' + name)
        return refuse

    with pytest.MonkeyPatch.context() as patch:
        for owner, name, function in ((torch.nn.GRU, '__init__', gru),
                (torch.nn.Module, 'load_state_dict', load), (torch.nn.GRU, 'forward', forward),
                (_boundary_prefix, 'allowed_token_ids', prefix), (budget, 'select_token', select),
                (_boundary_witness, 'find_completion_witness', search),
                (tokens, 'decode_compact_content_tokens_v1', decode)):
            patch.setattr(owner, name, function)
        for owner, name, counter in ((torch.optim.Adam, '__init__', 'adam_constructions'),
                (torch.optim.Optimizer, '__init__', 'adam_constructions'),
                (torch.optim.Adam, 'step', 'optimizer_updates'),
                (torch.nn.functional, 'cross_entropy', 'cross_entropy_calls'),
                (torch.autograd, 'grad', 'autograd_grad_calls'),
                (torch.Tensor, 'backward', 'backward_calls'),
                (torch.nn.utils, 'clip_grad_norm_', 'clip_calls'),
                (numerical, '_optimizer', 'adam_constructions'),
                (trained, 'train_compact_content_persistent_v1', 'optimizer_updates')):
            patch.setattr(owner, name, forbidden(counter))
        yield observed
    assert all(counts[key] == 0 for key in COUNTERS if key not in
               ('gru_constructions', 'state_restores', 'gru_forwards', 'selector_calls'))


def _boundary_mask_ids(encoded):
    assert type(encoded) is str and len(encoded) == 135 and encoded == encoded.lower()
    value = int(encoded, 16)
    assert value >> 537 == 0
    return [token for token in range(537) if value & (1 << token)]


def _boundary_assert_search_observations(search, prefixes):
    report = search['report']
    actual = prefixes[search['prefix_begin']:search['prefix_end']]
    assert len(actual) == report['actual_prefix_inspections'] <= search['actual_allowance']
    assert report['max_prefix_inspections'] == search['actual_allowance']
    assert len(report['trace']) + report['unrecorded_inspections'] == len(actual)
    paths = {}
    by_hash = {item['report_sha256']: item for item in actual}
    for node in report['trace']:
        parent = node['parent_id']
        ids = list(report['offered_ids']) if parent is None else paths[parent] + [node['via_token_id']]
        assert node['node_id'] not in paths
        paths[node['node_id']] = ids
        item = by_hash[node['owner_report_sha256']]
        assert item['offered_ids'] == ids and item['remaining_new_tokens'] == node['remaining_new_tokens']
        assert item['status'] == node['status'] and item['reason'] == node['reason']
        assert _boundary_mask_ids(node['allowed_mask_hex']) == item['allowed_token_ids']
    if report['status'] == 'DEAD_END':
        assert report['frontier_closed'] is report['exhaustive_relative_to_original_policy'] is True
        assert report['pending_nodes'] == report['unexpanded_parents'] == []
        assert report['unrecorded_inspections'] == report['unresolved_frontier_root_count'] == 0
        for node in report['trace']:
            children = sorted(child['via_token_id'] for child in report['trace'] if child['parent_id'] == node['node_id'])
            assert children == _boundary_mask_ids(node['allowed_mask_hex'])
    elif report['status'] == 'UNKNOWN':
        assert report['frontier_closed'] is False and report['unresolved_frontier_root_count'] > 0
    else:
        assert report['status'] == 'WITNESS'
        assert report['witness']['token_ids'] == paths[report['witness']['node_id']]
        assert report['witness']['syntactic_only'] is True and report['witness']['model_generated_completion'] is False


def _boundary_assert_saved_trace(report, checkpoint, vector, context, max_new_tokens,
        *, max_decision, max_generation):
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
    assert settings["max_prefix_inspections_per_decision"] == max_decision
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
        assert selected["max_prefix_inspections"] == min(max_decision, max_generation-work)
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



def _boundary_capture(inputs, *, max_new_tokens, max_decision, max_generation):
    checkpoint, row, context = inputs["checkpoint"], inputs["row"], inputs["context"]
    original = deepcopy((checkpoint, row))
    rng = torch.get_rng_state().clone()
    with _boundary_observations() as observed:
        report = subject.generate_from_bos(checkpoint, row["conditioning"], context,
            expected_checkpoint_sha256=digest(checkpoint), expected_context_sha256=sha(context),
            expected_conditioning_mode=checkpoint["conditioning_mode"],
            expected_source_space=checkpoint["source_space"], max_new_tokens=max_new_tokens,
            max_prefix_inspections_per_decision=max_decision,
            max_prefix_inspections_per_generation=max_generation)
    assert torch.equal(rng, torch.get_rng_state()) and torch.get_num_threads() == 1
    assert (checkpoint, row) == original
    return report, observed


def _boundary_save(tmp_path, stem, inputs, report, observed, *, max_new_tokens,
        max_decision, max_generation, classification):
    pin = write_exclusive(tmp_path / (stem + ".json"), wire(report))
    assert read_reference(pin, maximum=64 * 1024**2) == wire(report)
    assert subject.generation_sha256(report) == digest(report)
    validation = _boundary_assert_saved_trace(report, inputs["checkpoint"],
        inputs["row"]["conditioning"], inputs["context"], max_new_tokens,
        max_decision=max_decision, max_generation=max_generation)
    steps = report["trace"] + ([] if report["terminal_no_selection_trace"] is None
        else [report["terminal_no_selection_trace"]])
    assert [item["report"] for item in observed["selectors"]] == [item["selection_report"] for item in steps]
    assert len(observed["prefixes"]) == report["grammar_accounting"]["actual_prefix_inspections"]
    assert len(observed["searches"]) == report["grammar_accounting"]["witness_calls"]
    assert len(observed["decodes"]) == 1
    assert observed["counts"]["gru_constructions"] == report["model_construction_count"] == 1
    assert observed["counts"]["state_restores"] == report["state_installation_count"] == 2
    assert observed["counts"]["gru_forwards"] == observed["counts"]["selector_calls"] == len(steps)
    for search in observed["searches"]:
        _boundary_assert_search_observations(search, observed["prefixes"])
    write_exclusive(tmp_path / (stem + ".validation.json"), wire(validation))
    write_exclusive(tmp_path / (stem + ".observations.json"), wire(dict(
        classification=classification, counts=observed["counts"], events=observed["events"],
        actual_public_prefix_observations=observed["prefixes"],
        selector_calls=len(observed["selectors"]), witness_calls=len(observed["searches"]),
        runtime_public_typed_decode_calls=len(observed["decodes"]),
        reference_targets_opened=False, primary_comparison_record_added=False,
        learned_accuracy_credit=False)))
    return pin


def test_retained_persistent_v3_first_forward_proof_backed_no_selection_boundary(boundary_inputs, tmp_path):
    report, observed = _boundary_capture(boundary_inputs,
        max_new_tokens=28, max_decision=32, max_generation=64)
    pin = _boundary_save(tmp_path, "genuine-first-forward-boundary", boundary_inputs,
        report, observed, max_new_tokens=28, max_decision=32, max_generation=64,
        classification="genuine_model_first_forward_mechanics_not_primary_accuracy")
    assert report["status"] == "blocked"
    assert report["generated_ids"] == [1] and report["selected_token_ids"] == []
    assert report["trace"] == [] and report["selected_token_decisions"] == 0
    assert report["terminal_no_selection_decisions"] == 1
    assert report["numerical_forward_count"] == report["state_positions_consumed"] == 1
    terminal = report["terminal_no_selection_trace"]
    assert terminal["prefix_ids"] == terminal["input_token_ids"] == [1]
    selected = terminal["selection_report"]
    assert terminal["selected_token_id"] is selected["selected_token_id"] is None
    assert selected["status"] == "no_selection" and selected["allowed_token_ids"] == []
    baseline = selected["baseline_prefix_report"]["allowed_token_ids"]
    assert baseline and set(selected["removed_token_ids"]) == set(baseline)
    assert len(selected["candidate_results"]) == len(baseline)
    for row in selected["candidate_results"]:
        assert row["queried"] is row["certificate_retained"] is True
        assert row["disposition"] == "remove_proven_dead_end"
        certificate = selected["certificates"][row["certificate_index"]]
        assert certificate["status"] == "DEAD_END" and certificate["frontier_closed"] is True
        assert certificate["exhaustive_relative_to_original_policy"] is True
        assert certificate["unresolved_frontier_root_count"] == 0
    assert boundary_inputs["reference_targets_opened"] is False
    write_exclusive(tmp_path / "boundary-mechanics-panel.json", wire(dict(
        schema="persistent-runtime-v3-boundary-mechanics-panel/v1", report=pin,
        classification="genuine_current_scores_first_forward_no_selection",
        actual_prefix_inspections=report["grammar_accounting"]["actual_prefix_inspections"],
        numerical_forward_count=1, emitted_IDs=0, reference_targets_opened=False,
        primary_quality_comparison_performed=False, learned_accuracy_credit=False)))


def test_retained_persistent_v3_score_replaced_eos_boundary(boundary_inputs, tmp_path, monkeypatch):
    checkpoint, context = boundary_inputs["checkpoint"], boundary_inputs["context"]
    content = dict(schema="legal-relational-compact-content/v1", tree=["forall", 0,
        ["predicate", 0, [["variable", 0], ["variable", 0]]]])
    raw = wire(content)
    encoded = tokens.encode_compact_content_tokens_v1(raw, context,
        expected_content_sha256=sha(raw), expected_context_sha256=sha(context),
        codec=checkpoint["codec"], expected_codec_sha256=checkpoint["codec_sha256"])
    complete = encoded["target_ids"]
    assert len(complete) - 1 == 34 and complete[0] == 1 and complete[-1] == 2
    real_bind = _boundary_adapter.bind_persistent_model
    script_events = []

    def bind(*args, **kwargs):
        model = real_bind(*args, **kwargs)
        real_next = model.next_logits

        def scripted(offered, state):
            index = int(state[2][0])
            assert offered.tolist() == [[complete[index]]] and index < len(complete) - 1
            actual_logits, updated = real_next(offered, state)
            scores = torch.full_like(actual_logits, -50.0)
            scores[..., complete[index + 1]] = 50.0
            script_events.append(dict(position=index, input_token_id=complete[index],
                selected_control_token_id=complete[index + 1],
                genuine_current_logits_sha256=digest(actual_logits[0, -1].tolist()),
                replaced_current_logits_sha256=digest(scores[0, -1].tolist())))
            return scores, updated

        model.next_logits = scripted
        return model

    with monkeypatch.context() as patch:
        patch.setattr(_boundary_adapter, "bind_persistent_model", bind)
        report, observed = _boundary_capture(boundary_inputs,
            max_new_tokens=34, max_decision=1, max_generation=35)
    assert _boundary_adapter.bind_persistent_model is real_bind
    pin = _boundary_save(tmp_path, "score-replaced-eos-boundary", boundary_inputs,
        report, observed, max_new_tokens=34, max_decision=1, max_generation=35,
        classification="explicitly_replaced_current_scores_instrumentation_not_learned_generation")
    assert report["status"] == "complete" and report["generated_ids"] == complete
    assert report["numerical_forward_count"] == report["state_positions_consumed"] == 34
    assert len(script_events) == report["selected_token_decisions"] == 34
    assert report["terminal_no_selection_trace"] is None and report["terminal_no_selection_decisions"] == 0
    assert report["selected_token_ids"].count(2) == 1 and report["selected_token_ids"][-1] == 2
    assert report["trace"][-1]["selected_token_id"] == 2
    assert all(step["input_token_ids"] != [2] for step in report["trace"])
    assert all(step["selection_report"]["witness_suffix_injected"] is False for step in report["trace"])
    for step, event in zip(report["trace"], script_events, strict=True):
        assert step["input_token_ids"] == [event["input_token_id"]]
        assert step["selected_token_id"] == event["selected_control_token_id"]
        assert step["logits_sha256"] == event["replaced_current_logits_sha256"]
    assert report["grammar_accounting"]["actual_prefix_inspections"] == 35
    assert report["final_decoding"]["status"] == "valid_candidate"
    assert report["final_decoding"]["prediction"]["content"] == content
    assert boundary_inputs["reference_targets_opened"] is False
    write_exclusive(tmp_path / "boundary-instrumentation-panel.json", wire(dict(
        schema="persistent-runtime-v3-boundary-instrumentation-panel/v1", report=pin,
        classification="explicitly_replaced_current_scores_not_model_accuracy",
        genuine_model_forward_per_scripted_step=True, script_events=script_events,
        numerical_forward_count=34, reference_targets_opened=False,
        primary_quality_comparison_performed=False, learned_accuracy_credit=False,
        independently_authored_content_sha256=sha(raw), scripted_IDs_sha256=digest(complete))))
