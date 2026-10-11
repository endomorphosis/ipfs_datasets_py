"""Case-preserving selection controls, without numerical models or corpora."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

_PATH = Path(__file__).resolve().parents[3] / (
    "ipfs_datasets_py/logic/formalization/autoencoder/legal_scope_retention_selection.py")
_SPEC = importlib.util.spec_from_file_location("_pure_legal_retention_selection", _PATH)
policy = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = policy
_SPEC.loader.exec_module(policy)
CONFIG = policy.SelectionConfig(positive_count=4, negative_count=4, source_parent_groups=4)


def source_id(name):
    return "source:" + sha256(("fixture:" + name).encode()).hexdigest()


def cases():
    result = []
    for prefix, supported in (("p", True), ("n", False)):
        for index in range(4):
            identity = source_id(prefix + str(index))
            result.append(dict(id=identity, source_sha256=identity[7:], source_group="group:" + str(index),
                supported=supported, emitted=index < 2, whole_exact=supported and index == 0,
                learned_refusal=index == (3 if supported else 2)))
    return result


def panel(rows=None):
    return policy.make_panel(cases() if rows is None else rows, CONFIG)


def changed(**changes):
    rows = cases()
    for name, updates in changes.items():
        next(row for row in rows if row["id"] == source_id(name)).update(updates)
    return panel(rows)


def candidate(step, measured):
    return dict(completed_updates=step, panel=measured,
                checkpoint_sha256=sha256(("actual-cold-or-fitted-state:" + str(step)).encode()).hexdigest())


def test_same_whole_count_cannot_replace_a_baseline_exact_positive():
    baseline = panel()
    swap = changed(p0=dict(whole_exact=False), p1=dict(whole_exact=True))
    assert swap["summary"]["positive_exact_count"] == baseline["summary"]["positive_exact_count"]
    report = policy.retention_report(swap, baseline, CONFIG)
    assert report["paired_case_ids"]["whole_lost"] == [source_id("p0")]
    assert report["paired_case_ids"]["whole_gained"] == [source_id("p1")]
    assert report["failures"] == ["baseline_exact_positive_ids_retained"]
    fallback = candidate(0, baseline)
    chosen, decision = policy.select([fallback, candidate(120, swap)], baseline, CONFIG)
    assert chosen is fallback and not decision["selected_fitted_gain"]


def test_same_emission_count_cannot_replace_a_baseline_emitted_positive():
    baseline = panel()
    swap = changed(p1=dict(emitted=False), p2=dict(emitted=True))
    assert swap["summary"]["positive_emitted_proposal_count"] == baseline["summary"]["positive_emitted_proposal_count"]
    report = policy.retention_report(swap, baseline, CONFIG)
    assert report["paired_case_ids"]["positive_emission_lost"] == [source_id("p1")]
    assert report["failures"] == ["baseline_emitted_positive_ids_retained"]


def test_negative_id_substitution_fails_even_with_same_aggregate_count():
    baseline = panel()
    swap = changed(n1=dict(emitted=False, learned_refusal=True), n3=dict(emitted=True))
    assert swap["summary"]["negative_emitted_proposal_count"] == baseline["summary"]["negative_emitted_proposal_count"]
    report = policy.retention_report(swap, baseline, CONFIG)
    assert report["paired_case_ids"]["negative_emission_lost"] == [source_id("n1")]
    assert report["paired_case_ids"]["negative_emission_gained"] == [source_id("n3")]
    assert report["failures"] == ["no_new_negative_emission_ids"]
    assert not report["has_selection_gain"]


def test_reject_all_has_best_negative_rank_but_is_ineligible():
    baseline = panel()
    rows = cases()
    for row in rows:
        row.update(emitted=False, whole_exact=False, learned_refusal=True)
    reject_all = panel(rows)
    assert policy.rank(reject_all, 120, CONFIG) > policy.rank(baseline, 0, CONFIG)
    assert not policy.eligible(reject_all, baseline, CONFIG)
    fallback = candidate(0, baseline)
    assert policy.select([fallback, candidate(120, reject_all)], baseline, CONFIG)[0] is fallback


@pytest.mark.parametrize("zero_emissions", [False, True])
def test_baseline_needs_nonzero_whole_and_emission_before_fit(zero_emissions):
    rows = cases()
    for row in rows:
        if row["supported"]:
            row["whole_exact"] = False
            if zero_emissions:
                row.update(emitted=False, learned_refusal=True)
    empty_baseline = panel(rows)
    with pytest.raises(ValueError, match="nonzero baseline"):
        policy.select([candidate(0, empty_baseline)], empty_baseline, CONFIG)


@pytest.mark.parametrize("change, floor", [
    ({"p0": dict(whole_exact=False)}, "positive_whole_count_retained"),
    ({"p1": dict(emitted=False)}, "positive_emission_count_retained"),
    ({"p2": dict(learned_refusal=True)}, "positive_learned_refusal_count_not_increased"),
    ({"n3": dict(emitted=True)}, "negative_emission_count_not_increased"),
])
def test_all_original_aggregate_floors_remain(change, floor):
    report = policy.retention_report(changed(**change), panel(), CONFIG)
    assert not report["eligible"] and floor in report["failures"]


@pytest.mark.parametrize("gain", [
    {"n1": dict(emitted=False, learned_refusal=True)},
    {"p1": dict(whole_exact=True)},
])
def test_a_genuine_paired_gain_can_select_a_fitted_state(gain):
    baseline, measured = panel(), changed(**gain)
    fitted = candidate(120, measured)
    chosen, decision = policy.select([candidate(0, baseline), fitted], baseline, CONFIG)
    assert chosen is fitted and decision["selected_fitted_gain"]
    assert decision["candidates"][1]["fitted_selection_gain"]
    assert not any(decision[key] for key in (
        "final_retention_guaranteed", "source_semantics_verified", "proof_authority", "training_admission"))


def test_fewer_negatives_outrank_more_whole_exact_positives():
    baseline = panel()
    safer = candidate(120, changed(n1=dict(emitted=False, learned_refusal=True)))
    more_whole = candidate(240, changed(p1=dict(whole_exact=True)))
    assert policy.select([candidate(0, baseline), safer, more_whole], baseline, CONFIG)[0] is safer


def test_learned_negative_refusal_rank_gain_is_not_declared_whole_or_negative_gain():
    baseline = panel()
    more_refusals = candidate(120, changed(n3=dict(learned_refusal=True)))
    chosen, decision = policy.select([candidate(0, baseline), more_refusals], baseline, CONFIG)
    assert chosen is more_refusals
    assert decision["candidates"][1]["eligible"]
    assert not decision["candidates"][1]["has_selection_gain"]
    assert not decision["selected_fitted_gain"]


def test_ties_are_deterministic_and_the_actual_cold_zero_is_preserved():
    baseline = panel()
    fallback = candidate(0, baseline)
    rows = [fallback, candidate(120, deepcopy(baseline)), candidate(240, deepcopy(baseline))]
    before = deepcopy(rows)
    chosen, decision = policy.select(rows, baseline, CONFIG)
    assert chosen is fallback and rows == before
    assert not decision["selected_fitted_gain"]
    gain = changed(p1=dict(whole_exact=True))
    earlier, later = candidate(120, gain), candidate(240, deepcopy(gain))
    assert policy.select([fallback, earlier, later], baseline, CONFIG)[0] is earlier


def test_case_order_can_change_but_source_membership_cannot():
    baseline = panel()
    reversed_panel = deepcopy(baseline)
    reversed_panel["cases"].reverse()
    assert policy.eligible(reversed_panel, baseline, CONFIG)
    rows = cases()
    for row in rows:
        if row["source_group"] == "group:0":
            identity = source_id("replacement-" + str(row["supported"]))
            row.update(id=identity, source_sha256=identity[7:])
    with pytest.raises(ValueError, match="membership/group"):
        policy.eligible(panel(rows), baseline, CONFIG)


def test_group_reassignment_and_positive_negative_relabeling_are_rejected():
    baseline = panel()
    rows = cases()
    for row in rows:
        if row["source_group"] in ("group:0", "group:1"):
            row["source_group"] = "group:" + str(1 - int(row["source_group"][-1]))
    with pytest.raises(ValueError, match="membership/group"):
        policy.eligible(panel(rows), baseline, CONFIG)
    rows = cases()
    for row in rows:
        if row["source_group"] == "group:2":
            row.update(supported=not row["supported"], whole_exact=False)
    with pytest.raises(ValueError, match="membership/group"):
        policy.eligible(panel(rows), baseline, CONFIG)


@pytest.mark.parametrize("fault", [
    "missing", "duplicate", "mismatched_id_hash", "duplicate_hash", "unpaired_group",
    "group_count", "nonboolean", "whole_on_negative", "whole_on_refusal", "emission_and_refusal",
    "target_field", "unknown_panel_field", "unknown_summary_field", "source_group_ledger",
    "id_set_substitution", "id_set_duplicate", "count_drift", "profile",
])
def test_malformed_complete_coverage_is_refused(fault):
    measured = panel()
    row = measured["cases"][0]
    if fault == "missing": measured["cases"].pop()
    elif fault == "duplicate": measured["cases"][1] = deepcopy(row)
    elif fault == "mismatched_id_hash": row["source_sha256"] = "a" * 64
    elif fault == "duplicate_hash": measured["cases"][1]["source_sha256"] = row["source_sha256"]
    elif fault == "unpaired_group": row["source_group"] = "group:new"
    elif fault == "group_count":
        for item in measured["cases"]:
            if item["source_group"] == "group:0": item["source_group"] = "group:1"
    elif fault == "nonboolean": row["emitted"] = 1
    elif fault == "whole_on_negative":
        next(item for item in measured["cases"] if not item["supported"])["whole_exact"] = True
    elif fault == "whole_on_refusal":
        next(item for item in measured["cases"] if item["whole_exact"]).update(emitted=False, learned_refusal=True)
    elif fault == "emission_and_refusal": row.update(emitted=True, learned_refusal=True)
    elif fault == "target_field": row["gold"] = {}
    elif fault == "unknown_panel_field": measured["final_references"] = []
    elif fault == "unknown_summary_field": measured["summary"]["claimed_eligible"] = True
    elif fault == "source_group_ledger": measured["summary"]["source_groups"]["group:0"]["positive_ids"] = []
    elif fault == "id_set_substitution": measured["summary"]["positive_exact_ids"] = [source_id("p1")]
    elif fault == "id_set_duplicate": measured["summary"]["negative_ids"][0] = measured["summary"]["negative_ids"][1]
    elif fault == "count_drift": measured["summary"]["positive_count"] += 1
    elif fault == "profile": measured["source_profile"] = "foreign-profile/v1"
    with pytest.raises(ValueError):
        policy.validate_panel(measured, CONFIG)


@pytest.mark.parametrize("counter", policy._COUNTERS)
@pytest.mark.parametrize("bad_value", [True, 1.0, -1, "1", None])
def test_every_counter_requires_an_ordinary_nonnegative_integer(counter, bad_value):
    measured = panel()
    measured["summary"][counter] = bad_value
    with pytest.raises(ValueError, match="ordinary integer"):
        policy.validate_panel(measured, CONFIG)


@pytest.mark.parametrize("steps", [-1, True, 0.0, 1, 119, 121, 241, 10_000_001])
def test_only_the_three_actual_checkpoint_steps_are_ranked(steps):
    with pytest.raises(ValueError, match="completed updates"):
        policy.rank(panel(), steps, CONFIG)


def test_cold_baseline_and_strictly_increasing_actual_checkpoints_are_required():
    baseline = panel()
    fallback = candidate(0, baseline)
    for rows in ([], [candidate(120, baseline)],
                 [candidate(0, changed(p1=dict(whole_exact=True)))],
                 [fallback, candidate(0, baseline)],
                 [fallback, candidate(240, baseline), candidate(120, baseline)]):
        with pytest.raises(ValueError):
            policy.select(rows, baseline, CONFIG)
    assert policy.select([fallback], baseline, CONFIG)[0] is fallback
    invalid = candidate(120, baseline)
    invalid["checkpoint_sha256"] = "not-a-real-pin"
    with pytest.raises(ValueError, match="checkpoint SHA256"):
        policy.select([fallback, invalid], baseline, CONFIG)
    invalid = candidate(120, baseline)
    invalid["claimed_gain"] = True
    with pytest.raises(ValueError, match="closed measured candidate"):
        policy.select([fallback, invalid], baseline, CONFIG)


def test_configuration_is_closed_and_requires_one_positive_negative_pair_per_group():
    assert policy.SelectionConfig.from_dict(CONFIG.to_dict()) == CONFIG
    invalid = CONFIG.to_dict()
    invalid["allow_case_swaps"] = True
    with pytest.raises(ValueError, match="closed selection config"):
        policy.SelectionConfig.from_dict(invalid)
    for change in (dict(positive_count=True), dict(negative_count=3),
                   dict(source_parent_groups=3), dict(source_profile="other/v1")):
        with pytest.raises(ValueError):
            policy.SelectionConfig.from_dict({**CONFIG.to_dict(), **change})


def test_selector_imports_no_numeric_models_in_an_isolated_process():
    code = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location('pure_retention', sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert module.SelectionConfig().to_dict()['source_parent_groups'] == 64
assert not any(name.split('.')[0] in {'torch', 'numpy', 'transformers', 'ipfs_datasets_py'} for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(_PATH)],
                            capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
