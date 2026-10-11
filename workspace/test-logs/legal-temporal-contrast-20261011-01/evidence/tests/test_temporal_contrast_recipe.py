"""Inert saved-report and pre-fit data custody controls for the pilot recipe.

Synthetic heads below are written by the test author.  They are never claimed
as model output, and no numerical/model/compiler function is invoked.
"""
import copy
import hashlib
import importlib.util
from pathlib import Path
import re

import pytest

from ipfs_datasets_py.logic.legal_ir import temporal_role_contrast_corpus as corpus_owner


_RUNNER = Path(__file__).resolve().parents[1] / "run_temporal_contrast_pilot.py"
_SPEC = importlib.util.spec_from_file_location("inert_temporal_contrast_recipe_under_test", _RUNNER)
subject = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(subject)


def pair_inputs(pair_number=0):
    rows, metadata = [], []
    actor = "Office" + str(pair_number)
    for present in (False, True):
        identifier = "synthetic-pair-" + str(pair_number) + ("-present" if present else "-absent")
        source = actor + " shall retain the register" + (" within 17 days" if present else "") + "."
        rows.append({"id": identifier, "source_text": source, "latent": [0.0] * 384,
                     "canonical_ir": {"rules": [{"modality": "O", "actor": actor, "action": "retain",
                     "object": "the register", "conditions": [], "exceptions": [],
                     "temporal": ["within 17 days"] if present else []}]}})
        metadata.append({"id": identifier, "class_name": "plain_deadline",
                         "group_id": "synthetic-group-" + str(pair_number),
                         "pair_id": "synthetic-pair-" + str(pair_number),
                         "pair_variant": "temporal_present" if present else "temporal_absent"})
    return rows, metadata


def saved_reports(rows, *, temporal_predictions=None, decoded=False, joint_decoded=False):
    """Construct independent head and early-abstention observations."""
    if temporal_predictions is None:
        temporal_predictions = [bool(row["canonical_ir"]["rules"][0]["temporal"]) for row in rows]
    assert len(temporal_predictions) == len(rows)
    raw_rows, occurrences, joint_rows = [], [], []
    for row, predicted in zip(rows, temporal_predictions, strict=True):
        source_hash = hashlib.sha256(row["source_text"].encode("utf-8")).hexdigest()
        tokens = [{"text": m.group(), "start": m.start(), "end": m.end()}
                  for m in re.finditer(r"\w+|[^\w\s]", row["source_text"], re.UNICODE)]
        temporal = [0.0, 0.0] if predicted is None else [0.0, 1.0] if predicted else [1.0, 0.0]
        scores = {"schema": "joint-source-span-scores/v1", "tokens": tokens,
                  "modality_logits": [1.0, 0.0, 0.0],
                  "presence_logits": {"object": [0.0, 1.0], "conditions": [1.0, 0.0],
                                      "exceptions": [1.0, 0.0], "temporal": temporal},
                  "start_logits": {field: [0.0] * len(tokens) for field in subject.FIELDS},
                  "end_logits": {field: [0.0] * len(tokens) for field in subject.FIELDS}}
        raw_rows.append({"source_sha256": source_hash, "status": "decoded" if decoded else "abstained",
                         "canonical_ir": copy.deepcopy(row["canonical_ir"]) if decoded else None,
                         "reason": None if decoded else "copied_spans_overlap",
                         "span_diagnostics": {"facets": {"actor": {"present": True}, "action": {"present": True}}}})
        occurrences.append({"id": row["id"], "source_sha256": source_hash, "scores": scores})
        joint_rows.append({"id": row["id"], "result": {
            "source_sha256": source_hash, "scores_sha256": subject.digest(scores),
            "status": "decoded" if joint_decoded else "abstained",
            "canonical_ir": copy.deepcopy(row["canonical_ir"]) if joint_decoded else None,
            "reason": None if joint_decoded else "ambiguous_or_incompatible_saved_scores"}})
    return {"inference": {"rows": raw_rows}, "occurrences": occurrences}, joint_rows


def historical_rows(prefix):
    result = []
    for index in range(96):
        actor = prefix + "Office" + str(index)
        obj = "the " + prefix.lower() + " ledger " + str(index)
        result.append({"id": prefix + "-" + str(index), "source_text": actor + " shall inspect " + obj + ".",
                       "canonical_ir": {"rules": [{"modality": "O", "actor": actor, "action": "inspect",
                        "object": obj, "conditions": [], "exceptions": [], "temporal": []}]},
                       "latent": [0.0] * 384})
    return result


def historical_metadata(rows):
    return [{"id": row["id"], "class_name": "legacy_authored", "group_id": None,
             "pair_id": None, "pair_variant": None} for row in rows]


def recipe_fixture():
    corpus = corpus_owner.build_corpus()
    fresh = {key: [copy.deepcopy(row["model_example"]) for row in corpus["populations"][key]]
             for key in ("train", "tuning", "challenge")}
    metadata = {key: [{field: row[field] for field in ("id", "class_name", "group_id", "pair_id", "pair_variant")}
                      for row in corpus["populations"][key]] for key in fresh}
    old_train, old_tune = historical_rows("Rehearsal"), historical_rows("Oldtuning")
    plain = [(row, meta) for row, meta in zip(fresh["train"], metadata["train"], strict=True)
             if meta["class_name"] == "plain_deadline"]
    data = {"schema": subject.DATA_SCHEMA, "semantic_gold": False,
            "provenance": "authored_engineering_and_unreviewed_law_diagnostics_separate",
            "populations": {"control_train": copy.deepcopy(old_train) + [copy.deepcopy(row) for row, _ in plain],
                "contrast_train": copy.deepcopy(old_train) + fresh["train"], "old_tune": old_tune,
                "fresh_tune": fresh["tuning"], "fresh_challenge": fresh["challenge"],
                "law": [{"id": "unreviewed-source-" + str(index), "source_text": "Unreviewed source item " + str(index) + ".",
                         "latent": [0.0] * 384} for index in range(8)]},
            "metadata": {"control_train": historical_metadata(old_train) + [copy.deepcopy(meta) for _, meta in plain],
                "contrast_train": historical_metadata(old_train) + metadata["train"],
                "old_tune": historical_metadata(old_tune), "fresh_tune": metadata["tuning"],
                "fresh_challenge": metadata["challenge"]}}
    fake_prefix = "/nonexistent/inert-temporal-contrast-test/"
    required_paths = [str(_RUNNER), fake_prefix + "guardian.py", fake_prefix + "export.json",
                      fake_prefix + "parent.json", fake_prefix + "audit.json"]
    fake_pin = lambda path: {"path": path, "bytes": 0, "sha256": "0" * 64}
    plan = {key: None for key in subject.PLAN_FIELDS}
    plan.update({"schema": subject.SCHEMA, "package_root": fake_prefix + "package", "runner_path": str(_RUNNER),
        "guardian_path": required_paths[1], "source_owner_pins": {},
        "artifacts": {path: {"bytes": 0, "sha256": "0" * 64} for path in required_paths},
        "ctypes_dl_resolution": {}, "historical_parent_file_pin": fake_pin(required_paths[3]),
        "historical_parent_canonical_sha256": "0" * 64, "parent_base_canonical_sha256": "0" * 64,
        "parent_model_state_sha256": "0" * 64, "data_export": fake_pin(required_paths[2]),
        "arms": [{"name": name, "training_population": name + "_train", "training_manifest_sha256": "pending",
                  "training_count": count, "new_steps": 32} for name, count in (("control", 108), ("contrast", 168))],
        "tuning_population": "old_tune", "tuning_manifest_sha256": "pending",
        "diagnostic_panels": [{"name": name, "population": name, "count": count,
             "has_authored_reference": reference, "provenance": "authored_synthetic_not_legal_authority" if reference
             else "previously_exposed_unreviewed_law_source_only"}
             for name, count, reference in (("old_tune", 96, True), ("fresh_tune", 36, True),
                                           ("fresh_challenge", 36, True), ("law", 8, False))],
        "context_contract": {}, "resource_contract": {"cpu_slots": 2, "rss_mib": 1536, "child_slots": 1,
                        "storage_bytes": 200000000, "wall_seconds": 300},
        "forbidden_reference_paths": [fake_prefix + "forbidden-original-targets.json"],
        "training_seconds_per_arm": 32, "seed": 1729, "dimension": 384, "latent_enabled": False,
        "encoder_execution_planned": False, "semantic_gold": False, "independent_semantic_holdout": False,
        "checkpoint_selection_executed": False, "default_promotion": False, "Lake_executed": False,
        "inert_audit_pin": fake_pin(required_paths[4])})
    refresh_manifests(plan, data)
    return plan, data


def refresh_manifests(plan, data):
    # Keep manifest hashes valid so a corruption test reaches the substantive
    # source/group/reference/subset boundary instead of just a stale digest.
    for arm in plan["arms"]:
        arm["training_manifest_sha256"] = subject.digest(data["populations"][arm["training_population"]])
    plan["tuning_manifest_sha256"] = subject.digest(data["populations"]["old_tune"])


def test_temporal_false_positive_and_negative_survive_early_greedy_abstention():
    rows, metadata = pair_inputs()
    raw, joint = saved_reports(rows, temporal_predictions=[True, False])
    assert all("temporal" not in row["span_diagnostics"]["facets"] for row in raw["inference"]["rows"])
    before = copy.deepcopy((rows, metadata, raw, joint))
    score = subject.score_panel(rows, metadata, raw, joint)
    assert score["row_count"] == score["raw_abstentions"] == 2
    assert score["temporal_false_positives"] == score["temporal_false_negatives"] == 1
    assert score["temporal_presence_correct"] == score["temporal_ambiguous"] == 0
    assert score["classes"]["plain_deadline"]["rows"] == 2
    assert score["pairwise_consistency"][0]["temporal_both_correct"] == 0
    assert (rows, metadata, raw, joint) == before


def test_full_denominator_retains_correct_wrong_and_ambiguous_presence_predictions():
    rows, metadata = [], []
    for index in range(3):
        pair_rows, pair_meta = pair_inputs(index)
        rows += pair_rows
        metadata += pair_meta
    raw, joint = saved_reports(rows, temporal_predictions=[True, False, None, None, False, True])
    score = subject.score_panel(rows, metadata, raw, joint)
    assert score["row_count"] == score["raw_abstentions"] == 6
    assert score["temporal_false_positives"] == score["temporal_false_negatives"] == 1
    assert score["temporal_ambiguous"] == score["temporal_presence_correct"] == 2
    assert sum(score[key] for key in ("temporal_false_positives", "temporal_false_negatives",
                                    "temporal_ambiguous", "temporal_presence_correct")) == 6
    assert len(score["rows"]) == 6 and len(score["pairwise_consistency"]) == 3
    assert score["classes"]["plain_deadline"]["reference_temporal_present"] == 3
    assert [row["predicted_temporal_presence"] for row in score["rows"]] == [True, False, None, None, False, True]


def test_tied_presence_is_unassessed_even_when_reference_is_temporally_absent():
    rows, metadata = pair_inputs()
    raw, joint = saved_reports(rows, temporal_predictions=[None, None])
    score = subject.score_panel(rows, metadata, raw, joint)
    assert score["temporal_ambiguous"] == 2
    assert score["temporal_presence_correct"] == score["temporal_false_positives"] == score["temporal_false_negatives"] == 0
    assert all(row["temporal_presence_correct"] is False for row in score["rows"])


def test_decoded_role_error_is_separate_from_temporal_presence_and_joint_result():
    rows, metadata = pair_inputs()
    raw, joint = saved_reports(rows, decoded=True, joint_decoded=True)
    raw["inference"]["rows"][1]["canonical_ir"]["rules"][0]["object"] = "wrong register"
    score = subject.score_panel(rows, metadata, raw, joint)
    assert score["raw_exact_ir"] == 1 and score["joint_exact_ir"] == 2
    assert score["temporal_presence_correct"] == 2 and score["raw_abstentions"] == 0
    assert score["role_exact_counts"]["object"] == 1
    assert score["joint_role_exact_counts"]["object"] == 2
    assert score["pairwise_consistency"][0]["all_raw_exact"] is False
    assert score["pairwise_consistency"][0]["all_temporal_correct"] is True
    assert score["semantic_accuracy"] is None and score["qualified"] is False


@pytest.mark.parametrize("corruption", ["missing_member", "duplicate_variant", "wrong_variant", "different_group", "different_class", "different_reference", "partial_pair"])
def test_scorer_rejects_incomplete_conflicting_or_noncontrast_pairs(corruption):
    rows, metadata = pair_inputs()
    raw, joint = saved_reports(rows)
    if corruption == "missing_member":
        rows, metadata = rows[:1], metadata[:1]
        raw["inference"]["rows"] = raw["inference"]["rows"][:1]
        raw["occurrences"] = raw["occurrences"][:1]
        joint = joint[:1]
    elif corruption == "duplicate_variant":
        metadata[1]["pair_variant"] = "temporal_absent"
        rows[1]["canonical_ir"]["rules"][0]["temporal"] = []
    elif corruption == "wrong_variant":
        metadata[1]["pair_variant"] = "temporal_absent"
    elif corruption == "different_group":
        metadata[1]["group_id"] += "other"
    elif corruption == "different_class":
        metadata[1]["class_name"] = "object_duration_title"
    elif corruption == "different_reference":
        rows[1]["canonical_ir"]["rules"][0]["actor"] = "AnotherOffice"
    else:
        metadata[1]["pair_id"] = None
    with pytest.raises(ValueError):
        subject.score_panel(rows, metadata, raw, joint)


@pytest.mark.parametrize("corruption", ["occurrence", "raw_hash", "capture_hash", "joint_hash", "score_identity", "tokens", "order", "truncated"])
def test_scorer_rejects_saved_report_source_geometry_and_coverage_mismatch(corruption):
    rows, metadata = pair_inputs()
    raw, joint = saved_reports(rows)
    if corruption == "occurrence":
        raw["occurrences"][0]["id"] = "wrong-id"
    elif corruption in ("raw_hash", "capture_hash", "joint_hash"):
        container = raw["inference"]["rows"][0] if corruption == "raw_hash" else raw["occurrences"][0] if corruption == "capture_hash" else joint[0]["result"]
        container["source_sha256"] = "0" * 64
    elif corruption == "score_identity":
        joint[0]["result"]["scores_sha256"] = "0" * 64
    elif corruption == "tokens":
        raw["occurrences"][0]["scores"]["tokens"][0]["start"] = 1
        joint[0]["result"]["scores_sha256"] = subject.digest(raw["occurrences"][0]["scores"])
    elif corruption == "order":
        raw["occurrences"].reverse()
    else:
        raw["inference"]["rows"].pop()
    with pytest.raises(ValueError):
        subject.score_panel(rows, metadata, raw, joint)


@pytest.mark.parametrize("head", [[0, 1], [False, True], [0.0], [0.0, 1.00000001], [0.0, float("inf")]])
def test_presence_heads_require_exact_finite_saved_float32_scalars(head):
    rows, metadata = pair_inputs()
    raw, joint = saved_reports(rows)
    raw["occurrences"][0]["scores"]["presence_logits"]["temporal"] = head
    if all(not isinstance(value, float) or value != float("inf") for value in head):
        joint[0]["result"]["scores_sha256"] = subject.digest(raw["occurrences"][0]["scores"])
    with pytest.raises(ValueError):
        subject.score_panel(rows, metadata, raw, joint)


def test_recipe_fixture_passes_with_exact_control_subset_and_full_panel_denominators():
    plan, data = recipe_fixture()
    before = copy.deepcopy((plan, data))
    subject.validate_plan(plan)
    subject.validate_data(plan, data)
    assert (plan, data) == before
    assert len(data["populations"]["control_train"]) == 108
    assert len(data["populations"]["contrast_train"]) == 168
    assert data["populations"]["control_train"][:96] == data["populations"]["contrast_train"][:96]
    contrast = {row["id"]: row for row in data["populations"]["contrast_train"]}
    assert all(contrast[row["id"]] == row for row in data["populations"]["control_train"])
    assert [(panel["name"], panel["count"]) for panel in plan["diagnostic_panels"]] == [
        ("old_tune", 96), ("fresh_tune", 36), ("fresh_challenge", 36), ("law", 8)]


@pytest.mark.parametrize("field,value", [("group_id", "wrong-group"), ("pair_id", "wrong-pair"),
                                         ("class_name", "condition_duration")])
def test_control_fresh_metadata_must_match_the_treatment_plain_subset(field, value):
    plan, data = recipe_fixture()
    data["metadata"]["control_train"][96][field] = value
    with pytest.raises(ValueError):
        subject.validate_data(plan, data)


@pytest.mark.parametrize("population", ["contrast_train", "fresh_tune", "fresh_challenge"])
@pytest.mark.parametrize("corruption", ["incomplete_pair", "duplicate_variant", "mixed_group", "role_reference_change", "wrong_presence"])
def test_prefit_validation_rejects_pair_corruption_before_any_model(population, corruption):
    plan, data = recipe_fixture()
    index = 108 if population == "contrast_train" else 0
    metadata = data["metadata"][population]
    rows = data["populations"][population]
    if corruption == "incomplete_pair":
        metadata[index]["pair_id"] += "orphan"
    elif corruption == "duplicate_variant":
        metadata[index + 1]["pair_variant"] = "temporal_absent"
        rows[index + 1]["canonical_ir"]["rules"][0]["temporal"] = []
    elif corruption == "mixed_group":
        metadata[index + 1]["group_id"] += "other"
    elif corruption == "role_reference_change":
        rows[index + 1]["canonical_ir"]["rules"][0]["actor"] += " altered"
    else:
        metadata[index + 1]["pair_variant"] = "temporal_absent"
    refresh_manifests(plan, data)
    with pytest.raises(ValueError):
        subject.validate_data(plan, data)


@pytest.mark.parametrize("kind", ["source", "id", "group", "pair"])
def test_prefit_split_check_rejects_source_occurrence_or_related_group_leakage(kind):
    plan, data = recipe_fixture()
    if kind == "source":
        data["populations"]["fresh_challenge"][0]["source_text"] = data["populations"]["fresh_tune"][0]["source_text"]
    elif kind == "id":
        identifier = data["populations"]["fresh_tune"][0]["id"]
        data["populations"]["fresh_challenge"][0]["id"] = identifier
        data["metadata"]["fresh_challenge"][0]["id"] = identifier
    elif kind == "group":
        for meta in data["metadata"]["fresh_challenge"][:6]:
            meta["group_id"] = data["metadata"]["fresh_tune"][0]["group_id"]
    else:
        for meta in data["metadata"]["fresh_challenge"][:2]:
            meta["pair_id"] = data["metadata"]["fresh_tune"][0]["pair_id"]
    with pytest.raises(ValueError):
        subject.validate_data(plan, data)


@pytest.mark.parametrize("label", ["canonical_ir", "gold", "target_labels", "reviewed_role"])
def test_unreviewed_law_rows_cannot_receive_training_or_evaluation_reference_labels(label):
    plan, data = recipe_fixture()
    data["populations"]["law"][0][label] = {"rules": []}
    with pytest.raises(ValueError, match="closed data row"):
        subject.validate_data(plan, data)


@pytest.mark.parametrize("population", ["old_tune", "fresh_tune", "fresh_challenge", "law"])
def test_data_validator_never_accepts_truncated_diagnostic_denominators(population):
    plan, data = recipe_fixture()
    data["populations"][population].pop()
    if population in data["metadata"]:
        data["metadata"][population].pop()
    refresh_manifests(plan, data)
    with pytest.raises(ValueError, match="population count"):
        subject.validate_data(plan, data)


def test_ambiguous_refusal_candidate_cannot_be_inserted_in_training_population():
    plan, data = recipe_fixture()
    candidate = corpus_owner.build_corpus()["populations"]["ambiguous_diagnostics"][0]
    data["populations"]["contrast_train"][108] = copy.deepcopy(candidate["refusal_candidate"])
    data["metadata"]["contrast_train"][108] = {key: candidate[key] for key in
                                               ("id", "class_name", "group_id", "pair_id", "pair_variant")}
    refresh_manifests(plan, data)
    with pytest.raises(ValueError):
        subject.validate_data(plan, data)


def test_same_update_budget_has_distinct_population_and_rehearsal_exposure_schedules():
    plan, data = recipe_fixture()
    control = subject.schedule(data["populations"]["control_train"], 32)
    contrast = subject.schedule(data["populations"]["contrast_train"], 32)
    assert len(control["batch_ids"]) == len(contrast["batch_ids"]) == 32
    assert control["batch_ids_sha256"] != contrast["batch_ids_sha256"]
    assert control["final_progress"]["optimizer_steps"] == contrast["final_progress"]["optimizer_steps"] == 32
    for schedule, population in ((control, "control_train"), (contrast, "contrast_train")):
        allowed = {row["id"] for row in data["populations"][population]}
        assert all(0 < len(batch) <= 12 and set(batch) <= allowed for batch in schedule["batch_ids"])
    # Equal optimizer updates must not be mislabeled as equal source exposure.
    assert control["final_progress"] != contrast["final_progress"]
