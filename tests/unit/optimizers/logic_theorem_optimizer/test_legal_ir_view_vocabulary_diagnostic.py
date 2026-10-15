"""Fixed compiler-lane diagnostics on synthetic observations, never gold labels.

The mathematical oracle below does not call the autoencoder's loss or softmax.
Real adapter fixtures use authored text and deterministic mock 8D embeddings.
Existing nonview-projection tests retain the actual training/rollback coverage.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as ma
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_view_vocabulary_diagnostic as diagnostic
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample


ROOT = Path(__file__).resolve().parents[4]
LANES = [
    "CEC.native", "deontic.ir", "external_provers.router", "modal.frame_logic",
    "TDFOL.prover", "knowledge_graphs.neo4j_compat", "zkp.circuits",
]


def wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(wire(value)).hexdigest()


@pytest.fixture
def profile():
    return diagnostic.build_bridge_contract_view_profile()


def score(profile, logits, target=None):
    return diagnostic.score_fixed_view_logits(
        [{"sample_id": "authored-numeric-row", "logits": logits,
          "target_distribution": {"deontic.ir": 1.0} if target is None else target}],
        profile=profile, expected_profile_sha256=diagnostic.view_profile_sha256(profile),
    )


def oracle(logits, target):
    """Independent seven-class log-sum-exp calculation, without a CE floor."""
    values = [float(logits.get(label, 0.0)) for label in LANES]
    maximum = max(values)
    log_normalizer = maximum + math.log(sum(math.exp(value - maximum) for value in values))
    mass = sum(target.values())
    q = {label: target.get(label, 0.0) / mass for label in LANES}
    probabilities = {label: math.exp(value - log_normalizer) for label, value in zip(LANES, values)}
    ce = sum(q[label] * (log_normalizer - value) for label, value in zip(LANES, values))
    entropy = -sum(value * math.log(value) for value in q.values() if value)
    return probabilities, ce, entropy


def assert_unsigned(report):
    assert report["used_for_acceptance"] is False
    assert report["changes_training"] is False
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert not {"accepted", "promoted", "gold_admitted"}.intersection(report)


def assert_same_readout(left, right):
    assert left["rows"] == right["rows"]
    assert left["metrics"] == right["metrics"]
    assert left["profile_sha256"] == right["profile_sha256"]


def actual_case(profile):
    sample = build_us_code_sample(
        title="999", section="synthetic-1",
        text="Fictional numerical fixture: The agency shall retain records.",
        citation="Authored test fixture; not an enacted provision",
    )
    assert len(sample.embedding_vector) == 8
    model = ma.AdaptiveModalAutoencoder(compute_device="python", max_codec_feature_keys=0)
    model.state.legal_ir_view_logits.update({"deontic.ir": 0.4, "TDFOL.prover": -0.2})
    targets = [{"sample_id": sample.sample_id, "distribution": {"deontic.ir": 3., "TDFOL.prover": 1.}}]
    context = {
        "ir_family": "legal_ir", "ir_schema_version": "authored-numeric-fixture/v1",
        "decoder_task": "compiler-contract-view-diagnostic", "embedding_dimensions": 8,
        "encoder_model": sample.embedding_model, "encoder_revision": "mock-fixture/v1",
        "token_profile": "authored-short-fixture", "max_tokens": 512,
        "checkpoint_sha256": hashlib.sha256(model.state.to_json().encode("utf-8")).hexdigest(),
    }
    return {"model": model, "samples": [sample], "targets": targets, "profile": profile,
            "context": context}


def evaluate(case, **overrides):
    arguments = {
        "profile": case["profile"],
        "expected_profile_sha256": diagnostic.view_profile_sha256(case["profile"]),
        "expected_state_identity": case["model"].state.state_identity(),
        "checkpoint_context": case["context"], "expected_targets_sha256": sha(case["targets"]),
    }
    arguments.update(overrides)
    return diagnostic.evaluate_fixed_view_vocabulary(
        case["model"], case["samples"], case["targets"], **arguments,
    )


def test_profile_declares_actual_optimizer_lanes_and_pinned_mapper(profile):
    assert profile["schema"] == "legal-ir-bridge-contract-view-profile/v1"
    assert profile["namespace"] == "optimizer_bridge_contract_lane"
    assert profile["labels"] == LANES
    assert "modal.ir_decompiler" not in profile["labels"]
    assert "modal.autoencoder" not in profile["labels"]
    pins = {row["path"]: row for row in profile["producer_sources"]}
    assert "ipfs_datasets_py/logic/bridge/multiview.py" in pins
    for path, pin in pins.items():
        raw = (ROOT / path).read_bytes()
        assert len(raw) == pin["bytes"]
        assert hashlib.sha256(raw).hexdigest() == pin["sha256"]
    assert diagnostic.view_profile_sha256(profile) == sha(profile)


def test_zero_keys_and_mapping_order_preserve_fixed_support(profile):
    sparse = score(profile, {"deontic.ir": .3}, {"deontic.ir": 2., "TDFOL.prover": 1.})
    dense = score(profile, {label: .3 if label == "deontic.ir" else 0. for label in reversed(LANES)},
                  {"zkp.circuits": 0., "TDFOL.prover": 1., "deontic.ir": 2.})
    assert_same_readout(sparse, dense)
    assert list(sparse["rows"][0]["logits"]) == LANES
    assert sparse["rows"][0]["target_support"] == ["deontic.ir", "TDFOL.prover"]
    assert_unsigned(sparse)


@pytest.mark.parametrize("epsilon", [-1e-8, -1e-12, 1e-12, 1e-8])
def test_epsilon_continuity_matches_independent_log_sum_exp(profile, epsilon):
    logits = {"deontic.ir": epsilon}
    target = {"deontic.ir": 3., "TDFOL.prover": 1.}
    row = score(profile, logits, target)["rows"][0]
    probabilities, ce, entropy = oracle(logits, target)
    assert row["predicted_distribution"] == pytest.approx(probabilities, abs=1e-15)
    assert row["cross_entropy"] == pytest.approx(ce, abs=1e-14)
    assert row["entropy"] == pytest.approx(entropy, abs=1e-14)
    assert row["excess_cross_entropy"] == pytest.approx(ce - entropy, abs=1e-14)
    assert abs(row["cross_entropy"] - math.log(7)) <= 2 * abs(epsilon) + 1e-14


def test_seventh_zkp_class_and_extreme_logits_have_finite_unclamped_loss(profile):
    uniform = score(profile, {}, {"zkp.circuits": 1.})["rows"][0]
    assert uniform["cross_entropy"] == pytest.approx(math.log(7))
    row = score(profile, {"deontic.ir": 1000., "zkp.circuits": -1000.},
                {"zkp.circuits": 1.})["rows"][0]
    assert row["cross_entropy"] == pytest.approx(2000.)
    assert math.isfinite(row["cross_entropy"])
    assert row["target_support"] == ["zkp.circuits"]


@pytest.mark.parametrize("bad", [
    "unknown_zero_logit", "raw_decompiler_target", "negative_target", "zero_target",
    "nan_logit", "boolean_logit", "extra_field", "duplicate_id",
])
def test_closed_finite_rows_refuse_invalid_observations(profile, bad):
    row = {"sample_id": "one", "logits": {}, "target_distribution": {"deontic.ir": 1.}}
    rows = [row]
    if bad == "unknown_zero_logit":
        row["logits"]["ui_ux_ir"] = 0.
    elif bad == "raw_decompiler_target":
        row["target_distribution"] = {"modal.ir_decompiler": 1.}
    elif bad == "negative_target":
        row["target_distribution"]["TDFOL.prover"] = -1.
    elif bad == "zero_target":
        row["target_distribution"] = {"zkp.circuits": 0.}
    elif bad == "nan_logit":
        row["logits"]["deontic.ir"] = float("nan")
    elif bad == "boolean_logit":
        row["logits"]["deontic.ir"] = True
    elif bad == "extra_field":
        row["accepted"] = True
    else:
        rows.append(deepcopy(row))
    with pytest.raises(ValueError):
        diagnostic.score_fixed_view_logits(rows, profile=profile,
            expected_profile_sha256=diagnostic.view_profile_sha256(profile))


@pytest.mark.parametrize("count", [0, 257])
def test_score_row_bounds_refuse_without_a_partial_result(profile, count):
    rows = [{"sample_id": str(index), "logits": {}, "target_distribution": {"deontic.ir": 1.}}
            for index in range(count)]
    with pytest.raises(ValueError):
        diagnostic.score_fixed_view_logits(rows, profile=profile,
            expected_profile_sha256=diagnostic.view_profile_sha256(profile))


@pytest.mark.parametrize("mutation", ["wrong_pin", "resealed_labels", "resealed_producer"])
def test_profile_commitment_and_current_generation_are_both_required(profile, mutation):
    offered = deepcopy(profile)
    expected = diagnostic.view_profile_sha256(profile)
    if mutation == "wrong_pin":
        expected = "0" * 64
    elif mutation == "resealed_labels":
        offered["labels"][-1] = "modal.ir_decompiler"
        expected = diagnostic.view_profile_sha256(offered)
    else:
        offered["producer_sources"][0]["sha256"] = "0" * 64
        expected = diagnostic.view_profile_sha256(offered)
    with pytest.raises(ValueError):
        diagnostic.score_fixed_view_logits(
            [{"sample_id": "one", "logits": {}, "target_distribution": {"deontic.ir": 1.}}],
            profile=offered, expected_profile_sha256=expected)


@pytest.mark.parametrize("location", ["global", "active_feature", "inactive_feature"])
def test_actual_adapter_zero_key_insertion_preserves_predictions(profile, location):
    case = actual_case(profile)
    model, sample = case["model"], case["samples"][0]
    active = model._legal_ir_view_feature_keys_for(sample)[0]
    inactive = "authored-feature-not-present-in-sample"
    assert inactive not in model._legal_ir_view_feature_keys_for(sample)
    if location != "global":
        model.state.feature_legal_ir_view_logits[active if location == "active_feature" else inactive] = {
            "deontic.ir": .2,
        }
    before = evaluate(case)
    if location == "global":
        model.state.legal_ir_view_logits["zkp.circuits"] = 0.
    else:
        model.state.feature_legal_ir_view_logits[active if location == "active_feature" else inactive]["zkp.circuits"] = 0.
    after = evaluate(case)
    assert_same_readout(before, after)
    assert before["state_identity"] != after["state_identity"]
    assert_unsigned(after)


def test_actual_head_scale_changes_effective_logits_and_matches_math(profile):
    case = actual_case(profile)
    case["model"].legal_ir_view_logit_scale = .5
    report = evaluate(case)
    row = report["rows"][0]
    expected = {"deontic.ir": .2, "TDFOL.prover": -.1}
    probabilities, ce, _ = oracle(expected, case["targets"][0]["distribution"])
    assert row["logits"] == {label: expected.get(label, 0.) for label in LANES}
    assert row["predicted_distribution"] == pytest.approx(probabilities)
    assert row["cross_entropy"] == pytest.approx(ce)
    case["model"].legal_ir_view_logit_scale = 0.
    disabled = evaluate(case)
    assert disabled["metrics"]["cross_entropy"] == pytest.approx(math.log(7))
    assert disabled["head_activity"]["legal_ir_view_logits"]["active"] is False
    assert disabled["model_configuration_sha256"] != report["model_configuration_sha256"]


def test_actual_adapter_tiny_nonzero_update_has_continuous_readout(profile):
    case = actual_case(profile)
    before = evaluate(case)
    case["model"].state.legal_ir_view_logits["zkp.circuits"] = 1e-10
    after = evaluate(case)
    assert abs(after["metrics"]["cross_entropy"] - before["metrics"]["cross_entropy"]) < 1e-9
    probabilities, ce, _ = oracle(after["rows"][0]["logits"], case["targets"][0]["distribution"])
    assert after["rows"][0]["predicted_distribution"] == pytest.approx(probabilities, abs=1e-15)
    assert after["metrics"]["cross_entropy"] == pytest.approx(ce, abs=1e-14)


def test_warm_stale_support_cache_and_cold_state_replay_agree_after_revision(profile):
    case = actual_case(profile)
    model = case["model"]
    original = model._legal_ir_view_family_candidates()
    assert "zkp.circuits" not in original
    before = evaluate(case)
    old_pin = model.state.state_identity()
    model.state.legal_ir_view_logits["zkp.circuits"] = 2.
    # This existing cache is deliberately left stale; it cannot define vocabulary.
    assert model._legal_ir_view_family_candidates_cache == original
    with pytest.raises(ValueError):
        evaluate(case, expected_state_identity=old_pin)
    warm = evaluate(case)
    cold_case = actual_case(profile)
    cold_case["model"].state = ma.ModalAutoencoderTrainingState.from_dict(json.loads(model.state.to_json()))
    cold = evaluate(cold_case)
    assert_same_readout(warm, cold)
    assert warm["rows"][0]["predicted_distribution"]["zkp.circuits"] > before["rows"][0]["predicted_distribution"]["zkp.circuits"]
    assert model._legal_ir_view_family_candidates_cache == original


def test_caller_state_and_actual_cache_objects_remain_untouched(profile):
    case = actual_case(profile)
    model, sample = case["model"], case["samples"][0]
    model._legal_ir_view_feature_keys_for(sample)
    model._legal_ir_view_family_candidates()
    # Real caller-owned cache contents need not supply targets to the diagnostic.
    model._legal_ir_view_target_cache["authored-sentinel"] = {"zkp.circuits": .75}
    names = ["_sample_feature_cache", "_legal_ir_loss_target_cache", "_legal_ir_view_target_cache",
             "_legal_ir_view_family_candidates_cache", "_cuda_residency_reports"]
    refs = {name: getattr(model, name) for name in names}
    values = deepcopy(refs)
    state_json = model.state.to_json()
    revision = model.state.state_revision_token()
    report = evaluate(case)
    assert model.state.to_json() == state_json
    assert model.state.state_revision_token() == revision
    for name in names:
        assert getattr(model, name) is refs[name]
        assert getattr(model, name) == values[name]
    assert report["caller_state_unchanged"] is True
    assert report["caller_caches_untouched"] is True


def transition_case(profile):
    """Two authored real formula objects; their order is an input, not a review."""
    case = actual_case(profile)
    sample = case["samples"][0]
    base = sample.modal_ir.formulas[0]
    first = replace(base, formula_id="authored-a",
                    operator=replace(base.operator, family="deontic", symbol="O"))
    second = replace(base, formula_id="authored-b",
                     operator=replace(base.operator, family="temporal", symbol="F"))
    case["samples"] = [replace(sample, modal_ir=replace(sample.modal_ir, formulas=[first, second]))]
    case["model"].state.feature_legal_ir_view_logits[
        "legal-ir:modal-transition:deontic->temporal"
    ] = {"deontic.ir": 3.}
    return case


def test_ordered_formula_transition_changes_sample_pin_and_real_head_readout(profile):
    case = transition_case(profile)
    sample = case["samples"][0]
    legacy_sorted_serialization = sample.to_dict()
    before = evaluate(case)
    sample.modal_ir.formulas.reverse()
    # Existing document serialization sorts IDs, so it cannot pin this input.
    assert sample.to_dict() == legacy_sorted_serialization
    after = evaluate(case)
    assert before["samples_sha256"] != after["samples_sha256"]
    assert before["state_identity"] == after["state_identity"]
    assert before["rows"][0]["logits"]["deontic.ir"] > after["rows"][0]["logits"]["deontic.ir"]
    assert before["rows"][0]["predicted_distribution"]["deontic.ir"] > after["rows"][0]["predicted_distribution"]["deontic.ir"]
    assert_unsigned(after)


def test_caller_formula_reversal_during_actual_readout_refuses_closing(profile, monkeypatch):
    case = transition_case(profile)
    sample = case["samples"][0]
    before = sample.to_dict()
    original = ma.AdaptiveModalAutoencoder._legal_ir_view_logits_for
    observed = []
    def read_and_reverse(isolated, isolated_sample, families, *, use_sample_memory):
        assert isolated is not case["model"]
        result = original(isolated, isolated_sample, families, use_sample_memory=use_sample_memory)
        observed.append(isolated_sample.sample_id)
        sample.modal_ir.formulas.reverse()
        return result
    # Cooperative actual-head callback; no substituted model or instance method.
    monkeypatch.setattr(ma.AdaptiveModalAutoencoder, "_legal_ir_view_logits_for", read_and_reverse)
    with pytest.raises(ValueError, match="samples changed"):
        evaluate(case)
    assert observed == [sample.sample_id]
    assert sample.to_dict() == before
    assert [formula.formula_id for formula in sample.modal_ir.formulas] == ["authored-b", "authored-a"]


@pytest.mark.parametrize("mismatch", ["state", "targets", "dimension", "encoder"])
def test_adapter_refuses_stale_pins_or_incompatible_context(profile, mismatch):
    case = actual_case(profile)
    overrides = {}
    if mismatch == "state":
        overrides["expected_state_identity"] = "0" * 64
    elif mismatch == "targets":
        overrides["expected_targets_sha256"] = "0" * 64
    elif mismatch == "dimension":
        case["context"]["embedding_dimensions"] = 384
    else:
        case["context"]["encoder_model"] = "declared-different-encoder"
    with pytest.raises(ValueError):
        evaluate(case, **overrides)


@pytest.mark.parametrize("bucket", ["global", "inactive_feature", "disabled_signature"])
def test_unknown_checkpoint_labels_refuse_even_in_inactive_heads(profile, bucket):
    case = actual_case(profile)
    model = case["model"]
    if bucket == "global":
        model.state.legal_ir_view_logits["modal.autoencoder"] = 0.
    elif bucket == "inactive_feature":
        model.state.feature_legal_ir_view_logits["not-an-active-feature"] = {"ui_ux_ir": 0.}
    else:
        assert model.logic_signature_legal_ir_view_logit_scale == 0.
        model.state.logic_signature_legal_ir_view_logits["not-an-active-signature"] = {"modal.ir_decompiler": 0.}
    with pytest.raises(ValueError):
        evaluate(case)


@pytest.mark.parametrize("value", [float("nan"), float("inf")], ids=["nan", "inf"])
def test_nonfinite_disabled_head_is_rejected_before_any_readout(profile, value):
    case = actual_case(profile)
    model = case["model"]
    expected = model.state.state_identity()
    assert model.logic_signature_legal_ir_view_logit_scale == 0.
    model.state.logic_signature_legal_ir_view_logits["inactive"] = {"deontic.ir": value}
    # Supply the last valid identity directly: rejection belongs to the adapter,
    # rather than to this test helper computing a hash of invalid state first.
    with pytest.raises(ValueError):
        diagnostic.evaluate_fixed_view_vocabulary(
            model, case["samples"], case["targets"], profile=profile,
            expected_profile_sha256=diagnostic.view_profile_sha256(profile),
            expected_state_identity=expected, checkpoint_context=case["context"],
            expected_targets_sha256=sha(case["targets"]))


@pytest.mark.parametrize("unsupported", ["codec", "backend"])
def test_adapter_refuses_unsupported_profiles_without_loading_a_backend(profile, unsupported):
    case = actual_case(profile)
    if unsupported == "codec":
        case["model"].max_codec_feature_keys = 1
    else:
        # A declaration control: no GPU, optional library, or backend is opened.
        case["model"].compute_backend = "torch_cuda"
    with pytest.raises(ValueError):
        evaluate(case)


def test_changed_producer_observation_refuses_without_mutating_caller(profile, monkeypatch):
    case = actual_case(profile)
    original = diagnostic._source_rows
    calls = []
    def observe(names):
        rows = original(names)
        if any(name.endswith("modal_autoencoder.py") for name in names):
            calls.append(tuple(names))
            if len(calls) > 1:
                rows[0]["sha256"] = "0" * 64
        return rows
    before = case["model"].state.to_json()
    monkeypatch.setattr(diagnostic, "_source_rows", observe)
    with pytest.raises(ValueError, match="producer changed"):
        evaluate(case)
    assert len(calls) >= 2
    assert case["model"].state.to_json() == before


def test_strong_bad_actual_head_update_still_fails_existing_official_guard(profile):
    case = actual_case(profile)
    model = case["model"]
    model.state.legal_ir_view_logits.update({label: 0. for label in LANES})
    model.state.legal_ir_view_logits["deontic.ir"] = 4.
    case["targets"][0]["distribution"] = {"deontic.ir": 1.}
    good = evaluate(case)
    model.state.legal_ir_view_logits["deontic.ir"] = -4.
    model.state.legal_ir_view_logits["zkp.circuits"] = 4.
    bad = evaluate(case)
    assert bad["metrics"]["cross_entropy"] > good["metrics"]["cross_entropy"] + 5.
    def official(ce, cosine):
        return ma.AutoencoderEvaluation(
            sample_count=1, embedding_cosine_similarity=cosine, cosine_loss=1. - cosine,
            reconstruction_loss=0., cross_entropy_loss=0., frame_ranking_loss=0.,
            symbolic_validity_penalty=0., decoded_embeddings={},
            legal_ir_losses={"legal_ir_view_cross_entropy_loss": ce},
        )
    # An embedding improvement cannot bypass the existing IR regression guard.
    assert ma._evaluation_improved_for_training(
        official(good["metrics"]["cross_entropy"], .5),
        official(bad["metrics"]["cross_entropy"], 1.),
    ) is False
    assert_unsigned(bad)


def test_checkpoint_context_stays_an_explicit_declaration_with_unknown_legacy_metadata(profile):
    case = actual_case(profile)
    first = evaluate(case)
    case["context"]["checkpoint_sha256"] = "a" * 64
    for key in ("encoder_model", "encoder_revision", "token_profile", "max_tokens"):
        case["context"][key] = None
    declared = evaluate(case)
    assert_same_readout(first, declared)
    assert first["checkpoint_context_sha256"] != declared["checkpoint_context_sha256"]
    assert declared["checkpoint_context"] == case["context"]
    assert declared["checkpoint_context_is_caller_declaration"] is True
    assert declared["checkpoint_file_independently_authenticated"] is False


def test_pure_diagnostic_replays_in_fresh_process_without_optional_models_or_children(profile, tmp_path):
    program = r'''
import builtins, importlib, json, math, subprocess, sys
real_import = builtins.__import__
forbidden = {"symai", "torch", "transformers", "tensorflow"}
def checked_import(name, *args, **kwargs):
    if name.split(".")[0] in forbidden:
        raise AssertionError("optional model import: " + name)
    return real_import(name, *args, **kwargs)
builtins.__import__ = checked_import
def no_child(*args, **kwargs):
    raise AssertionError("nested process attempted")
subprocess.Popen = no_child
owner = importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_view_vocabulary_diagnostic")
payload = json.loads(sys.stdin.read())
result = owner.score_fixed_view_logits(payload["rows"], profile=payload["profile"],
    expected_profile_sha256=payload["profile_sha256"])
assert not forbidden.intersection(sys.modules)
assert all(value is False for value in result["authority"].values())
print(json.dumps({"row_count": result["row_count"], "metrics": result["metrics"]}, sort_keys=True))
'''
    payload = {"profile": profile, "profile_sha256": diagnostic.view_profile_sha256(profile),
               "rows": [{"sample_id": "cold", "logits": {}, "target_distribution": {"zkp.circuits": 1.}}]}
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["TMPDIR"] = str(tmp_path)
    completed = subprocess.run([sys.executable, "-B", "-c", program], input=wire(payload),
        capture_output=True, check=False, timeout=45, cwd=tmp_path, env=env)
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    result = json.loads(completed.stdout)
    assert result["row_count"] == 1
    assert result["metrics"]["cross_entropy"] == pytest.approx(math.log(7))
