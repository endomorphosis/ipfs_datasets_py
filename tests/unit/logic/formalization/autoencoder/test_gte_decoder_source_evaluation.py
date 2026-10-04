"""Source-only evaluation contracts with genuine original-archive fixture closure."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[5]
PATH = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_source_evaluation.py"


def read_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = read_module("gte_source_evaluation_test_subject", PATH)
original = read_module("gte_source_evaluation_native_fixture", Path(__file__).with_name("test_gte_decoder_native_batch.py"))


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    return original.decoder_native_fixture(tmp_path_factory)


def prepare(fixture, native_plan=None, **changes):
    return subject.prepare_source_evaluation(fixture.initialization,
        fixture.plan if native_plan is None else native_plan, fixture.batch, fixture.replay,
        expected_donor_pins=fixture.donor_pins, **changes)


def inspect(fixture, plan, native_plan=None):
    return subject.inspect_source_evaluation(plan, fixture.initialization,
        fixture.plan if native_plan is None else native_plan, fixture.batch, fixture.replay,
        expected_donor_pins=fixture.donor_pins)


def generation(reference, **changes):
    value = {"generated_ids": deepcopy(reference["token_ids"]), "terminated": True, "truncated": False}
    value.update(changes)
    return value


def score(fixture, head, generated=None, reference=None):
    row = prepare(fixture)["heads"][head]["rows"][0]
    reference = row["reference"] if reference is None else reference
    codec = fixture.initialization["primary" if head == "primary384" else "legacy8"]["codec"]
    return subject.score_generation(generation(reference) if generated is None else generated,
                                    reference, codec, head)


def test_ready_training_does_not_make_native_validation_ready(fixture):
    assert fixture.plan["status"] == "ready"
    plan = prepare(fixture)
    assert plan["status"] == "partial"
    assert plan["selected_row_count"] == plan["donor_ready_row_count"] == 62
    assert plan["native_ready_row_count"] == 2
    assert plan["native_missing_row_count"] == 60
    assert plan["native_quarantined_row_count"] == 0
    assert plan["heads"]["primary384"]["status"] == "unavailable"
    assert plan["heads"]["legacy8"]["status"] == "ready"
    assert inspect(fixture, plan)["full_original_audit_row_count"] == 242


def test_original_validation_and_legacy_raw_inputs_are_reused_exactly(fixture):
    plan = prepare(fixture)
    primary = plan["heads"]["primary384"]
    for row, original_row in zip(primary["rows"], fixture.plan["audit_rows"][180:240]):
        assert row["split"] == "validation"
        assert row["evaluation_role"] == "original_validation_exposed_regression_only"
        assert row["id"] == original_row["id"]
        assert row["generation_input"]["input_dimension"] == 384
        assert row["generation_input"]["input_vector"] == original_row["embedding"]
        assert row["generation_input"]["input_sha256"] == subject.digest(original_row["embedding"])
        assert row["reference"]["target"] == original_row["reference_target"]
        assert row["native_generation_input"] is None
        assert not any("reference" in field or "target" in field or "prefix" in field
                       for field in row["generation_input"])
    _, originals = subject._NATIVE._legacy_sources(fixture.plan["legacy8_inputs"])
    auxiliary = plan["heads"]["legacy8"]
    for row, original_row in zip(auxiliary["rows"], originals):
        assert row["split"] == "train"
        assert row["evaluation_role"] == "legacy_training_diagnostic_only"
        assert row["generation_input"]["input_vector"] == original_row["latent"]
        assert row["generation_input"]["input_vector"] != original_row["embedding"]
        assert row["native_generation_input"]["input_dimension"] == 768
        assert row["native_generation_input"]["input_vector"] == row["native_receipt"]["embedding"]
    assert primary["inherited_max_target_tokens"] == 512 and primary["max_new_tokens"] == 511
    assert auxiliary["inherited_max_target_tokens"] == 64 and auxiliary["max_new_tokens"] == 63
    assert primary["max_new_tokens"] > len(primary["rows"][0]["reference"]["token_ids"])


def test_all_cached_tasks_make_distinct_evaluation_ready_without_training(fixture):
    receipts = [original.receipt(task, index) for index, task in enumerate(fixture.empty_plan["task_manifest"]["tasks"])]
    native = original.prepare(fixture, receipts_768=receipts)
    plan = prepare(fixture, native)
    assert plan["status"] == "ready"
    assert plan["native_ready_row_count"] == 62 and plan["native_missing_row_count"] == 0
    assert inspect(fixture, plan, native)["status"] == "ready"
    for flag in ("teacher_qualified", "production_kd_eligible", "training_executed", "distillation_executed",
                 "generation_executed", "validation_is_independent_holdout", "proof_authority"):
        assert plan[flag] is False


def test_empty_cache_keeps_all_donor_rows_and_missing_native_tasks(fixture):
    plan = prepare(fixture, fixture.empty_plan)
    assert plan["status"] == "unavailable"
    assert plan["donor_ready_row_count"] == plan["native_missing_row_count"] == 62
    assert plan["native_ready_row_count"] == 0
    assert inspect(fixture, plan, fixture.empty_plan)["selected_row_count"] == 62


def test_one_native_validation_receipt_is_not_a_training_receipt(fixture):
    task = next(task for task in fixture.empty_plan["task_manifest"]["tasks"] if task["metadata"]["split"] == "validation")
    native = original.prepare(fixture, receipts_768=[original.receipt(task)])
    assert native["ready_row_count"] == 0
    plan = prepare(fixture, native)
    assert plan["native_ready_row_count"] == 1 and plan["native_missing_row_count"] == 61
    assert plan["heads"]["primary384"]["native_ready_row_count"] == 1
    assert inspect(fixture, plan, native)["status"] == "partial"


def test_quarantined_validation_is_retained_in_evaluation_denominator(fixture):
    archive = deepcopy(fixture.primary_validation_archive)
    archive["rows"][0]["group_id"] = fixture.primary_archive["rows"][0]["group_id"]
    native = original.prepare(fixture, primary_validation_archive=archive)
    plan = prepare(fixture, native)
    assert plan["selected_row_count"] == plan["donor_ready_row_count"] == 62
    assert plan["native_quarantined_row_count"] == 1 and plan["native_missing_row_count"] == 61
    row = plan["heads"]["primary384"]["rows"][0]
    assert row["native_status"] == "quarantined"
    assert row["quarantine_reasons"] == ["cross_split_connected_component"]
    assert row["embedding_task"] is None and row["native_receipt"] is None
    assert row["generation_input"]["input_vector"] == archive["rows"][0]["embedding"]
    assert inspect(fixture, plan, native)["native_quarantined_row_count"] == 1


@pytest.mark.parametrize("limits", [(True, 2), (0, 2), (61, 2), (60, True), (60, 0), (60, 3)])
def test_bounded_selection_rejects_wrong_types_and_overflow(fixture, limits):
    with pytest.raises(ValueError):
        prepare(fixture, max_primary_rows=limits[0], max_auxiliary_rows=limits[1])


def test_bounded_selection_preserves_original_order_and_fixed_generation_caps(fixture):
    plan = prepare(fixture, max_primary_rows=3, max_auxiliary_rows=1)
    assert plan["selected_row_count"] == 4 and plan["native_ready_row_count"] == 1
    assert [row["id"] for row in plan["heads"]["primary384"]["rows"]] == [row["id"] for row in fixture.plan["audit_rows"][180:183]]
    assert plan["heads"]["primary384"]["max_new_tokens"] == 511
    assert inspect(fixture, plan)["selected_row_count"] == 4


@pytest.mark.parametrize("mutation", ["source", "vector", "raw8", "reference", "native", "split", "role",
    "count", "cap", "flag", "boolean_flag", "ancestor", "extra", "digest"])
def test_inspection_reconstructs_all_source_and_reference_bindings(fixture, mutation):
    plan = prepare(fixture)
    row = plan["heads"]["primary384"]["rows"][0]
    legacy = plan["heads"]["legacy8"]["rows"][0]
    if mutation == "source": row["source_text"] += "changed"
    elif mutation == "vector": row["generation_input"]["input_vector"][0] += .1
    elif mutation == "raw8": legacy["generation_input"]["input_vector"][0] += .1
    elif mutation == "reference": row["reference"]["token_ids"][1] = 0
    elif mutation == "native": legacy["native_generation_input"]["input_vector"][0] += .1
    elif mutation == "split": row["split"] = "test"
    elif mutation == "role": row["evaluation_role"] = "independent_holdout"
    elif mutation == "count": plan["native_ready_row_count"] = 62
    elif mutation == "cap": plan["heads"]["primary384"]["max_new_tokens"] = len(row["reference"]["token_ids"])
    elif mutation == "flag": plan["teacher_qualified"] = True
    elif mutation == "boolean_flag": plan["archived_inputs_reused"] = 1
    elif mutation == "ancestor": plan["native_plan_sha256"] = "a" * 64
    elif mutation == "extra": row["prefix_ids"] = row["reference"]["token_ids"][:-1]
    elif mutation == "digest": plan["plan_sha256"] = "a" * 64
    if mutation != "digest":
        plan["plan_sha256"] = subject.digest({key: value for key, value in plan.items() if key != "plan_sha256"})
    with pytest.raises(ValueError):
        inspect(fixture, plan)


def test_entire_original_audit_is_admitted_before_small_selection(fixture):
    native = deepcopy(fixture.plan)
    native["audit_rows"][179]["embedding"][0] += .1
    with pytest.raises(ValueError):
        prepare(fixture, native, max_primary_rows=1, max_auxiliary_rows=1)


@pytest.mark.parametrize("head", ["primary384", "legacy8"])
def test_exact_canonical_generation_scores_all_original_facets(fixture, head):
    result = score(fixture, head)
    assert result["terminated"] is True and result["truncated"] is False
    assert result["syntax_valid"] is True and result["invalid_generation"] is False
    assert result["exact_target_match"] is True
    assert result["field_match_count"] == result["field_count"] == 7
    assert result["token_edit_distance"] == result["normalized_token_edit_distance"] == 0
    assert result["reason"] is None
    assert result["teacher_qualified"] is False and result["proof_authority"] is False


@pytest.mark.parametrize("head", ["primary384", "legacy8"])
@pytest.mark.parametrize("kind", ["early_eos", "pad", "bos", "unknown", "capped", "wrong_start"])
def test_invalid_raw_generation_is_scored_without_dropping_row(fixture, head, kind):
    reference = prepare(fixture)["heads"][head]["rows"][0]["reference"]
    raw = generation(reference)
    if kind == "early_eos": raw["generated_ids"] = [1, 2]
    elif kind == "pad": raw["generated_ids"][1] = 0
    elif kind == "bos": raw["generated_ids"][1] = 1
    elif kind == "unknown": raw["generated_ids"][1] = 50000
    elif kind == "capped": raw.update(generated_ids=raw["generated_ids"][:-1], terminated=False, truncated=True)
    elif kind == "wrong_start": raw["generated_ids"][0] = 0
    result = score(fixture, head, raw)
    assert result["syntax_valid"] is False and result["invalid_generation"] is True
    assert result["exact_target_match"] is False and result["field_match_count"] == 0
    assert result["token_edit_distance"] > 0
    assert result["reason"] is not None


def test_valid_alternate_target_has_measured_facet_and_token_error(fixture):
    reference = prepare(fixture)["heads"]["legacy8"]["rows"][0]["reference"]
    alternate = deepcopy(reference["target"])
    objects = {"notices", "reports"}
    alternate["rules"][0]["object"] = next(iter(objects - {alternate["rules"][0]["object"]}))
    codec = fixture.initialization["legacy8"]["codec"]
    raw = generation(reference, generated_ids=subject._BATCH._encode(alternate, codec["target_vocabulary"], "legacy8"))
    result = score(fixture, "legacy8", raw)
    assert result["syntax_valid"] is True and result["exact_target_match"] is False
    assert result["field_match_count"] == 6 and result["token_edit_distance"] == 1


@pytest.mark.parametrize("mutation", ["boolean_id", "negative_id", "empty", "extra", "stop_flags", "false_eos", "true_missing_eos", "reference_hash", "reference_bool_token"])
def test_malformed_scoring_receipt_is_rejected(fixture, mutation):
    reference = deepcopy(prepare(fixture)["heads"]["primary384"]["rows"][0]["reference"])
    raw = generation(reference)
    if mutation == "boolean_id": raw["generated_ids"][0] = True
    elif mutation == "negative_id": raw["generated_ids"][1] = -1
    elif mutation == "empty": raw["generated_ids"] = []
    elif mutation == "extra": raw["reference_prefix"] = reference["token_ids"][:-1]
    elif mutation == "stop_flags": raw["truncated"] = 0
    elif mutation == "false_eos": raw.update(terminated=False, truncated=True)
    elif mutation == "true_missing_eos": raw["generated_ids"] = raw["generated_ids"][:-1]
    elif mutation == "reference_hash": reference["target_sha256"] = "a" * 64
    elif mutation == "reference_bool_token": reference["token_ids"][0] = True
    with pytest.raises(ValueError):
        score(fixture, "primary384", raw, reference)


def test_plan_outputs_and_scoring_outputs_do_not_alias_original_assets(fixture):
    before = deepcopy((fixture.initialization, fixture.plan, fixture.batch, fixture.replay))
    plan = prepare(fixture)
    plan["heads"]["primary384"]["rows"][0]["generation_input"]["input_vector"][0] += 1.
    plan["heads"]["legacy8"]["rows"][0]["reference"]["target"]["rules"][0]["actor"] = "changed"
    plan["heads"]["legacy8"]["rows"][0]["native_receipt"]["embedding"][0] += 1.
    result = score(fixture, "legacy8")
    result["decoded_target"]["rules"][0]["actor"] = "changed"
    assert before == (fixture.initialization, fixture.plan, fixture.batch, fixture.replay)


def test_isolated_import_preparation_and_scoring_stay_stdlib(fixture, tmp_path):
    payload = {"initialization": fixture.initialization, "native_plan": fixture.plan,
        "batch": fixture.batch, "replay": fixture.replay, "expected_donor_pins": fixture.donor_pins}
    path = tmp_path / "source-evaluation-inputs.json"
    path.write_text(json.dumps(payload))
    code = """import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('isolated_source_evaluation',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
payload=json.load(open(sys.argv[2]));plan=module.prepare_source_evaluation(**payload)
module.inspect_source_evaluation(plan,**payload)
for head,nested in [('primary384','primary'),('legacy8','legacy8')]:
 reference=plan['heads'][head]['rows'][0]['reference']
 result=module.score_generation({'generated_ids':reference['token_ids'],'terminated':True,'truncated':False},reference,payload['initialization'][nested]['codec'],head)
 assert result['exact_target_match']
assert not any(name in sys.modules for name in ('torch','numpy','transformers','sentence_transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH), str(path)], check=True)
