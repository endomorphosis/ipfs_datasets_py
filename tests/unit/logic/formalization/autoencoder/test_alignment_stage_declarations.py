"""Stage association, leakage and inactive-admission checks without models."""
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import alignment_lane_bundle as lane
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_stage_declarations as subject


def seal(value):
    value["content_sha256"] = subject._digest({key: item for key, item in value.items() if key != "content_sha256"})
    return value


def role(schema, **fields):
    return seal({"schema": schema, **fields})


def pins(declaration):
    return {name: {"value_sha256": subject._digest(value),
                   "rows_sha256": subject._digest(value["rows"]) if type(value) is dict and "rows" in value else None}
            for name, value in declaration.items() if name not in {"schema", "content_sha256"}}


def lane_receipt(ids=("train_a", "train_b"), unavailable=(), ablation=()):
    profile = role(lane.PROFILE_SCHEMA, lane_id="legacy8", stage="historical_linguistic_features", dimension=8,
                   producer={"profile_id": "test-declared-historical8", "model_id": "test-fixture-no-model",
                             "model_revision": "fixture-v1", "code_sha256": "a" * 64, "model_assets_sha256": "b" * 64,
                             "checkpoint_sha256": None}, pooling={"method": "none", "endpoint": "linguistic_features"},
                   normalization={"kind": "none", "unit_tolerance": None}, precision="decimal6",
                   fit_input_recipe="exact_source_only/v1", inference_input_recipe="exact_source_only/v1")
    rows = []
    bound_rows = []
    inputs = []
    for index, identity in enumerate(ids):
        text = "Source statement for " + identity
        request = {"source_text": text, "context": {"role": "none_required", "text": "", "bindings": {},
                   "sha256": hashlib.sha256(b"").hexdigest()}}
        vector = [float(index + 1), 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        status, reason = "available", None
        if identity in unavailable:
            status, reason, vector = "unavailable", "no producer vector", None
        elif identity in ablation:
            status, reason, vector = "ablation_zero", "explicit diagnostic ablation", [0.0] * 8
        binding = {"id": identity, "input_sha256": subject._digest(request),
                   "encoder_text_sha256": hashlib.sha256(text.encode()).hexdigest(), "status": status, "reason": reason,
                   "vector_sha256": subject._digest(vector) if vector is not None else None,
                   "upstream_vector_sha256": None, "token_receipt_sha256": None}
        bound_rows.append(binding)
        rows.append({**binding, "input": request, "encoder_text": text, "vector": vector,
                     "producer_row_sha256": subject._digest(binding)})
        inputs.append({"id": identity, "input_sha256": binding["input_sha256"]})
    producer = role(lane.PRODUCER_SCHEMA, profile_sha256=subject._digest(profile), rows=bound_rows,
                    artifact_binding={"path": "never-read-fixture.json", "bytes": 1, "sha256": "c" * 64})
    bundle = role(lane.SCHEMA, profile=profile, producer_receipt=producer, rows=rows)
    return lane.validate_lane_bundle(bundle, expected_bindings={"profile_sha256": subject._digest(profile),
                                    "producer_receipt_sha256": subject._digest(producer), "inputs": inputs})


def source_rows(receipt):
    return [{"id": item["id"], "input_sha256": item["input_sha256"], "representation_sha256": item["vector_sha256"],
             "status": item["status"], "reason": item["reason"]} for item in receipt["rows"]]


def bank(receipt):
    return role("alignment-frozen-train-bank/v1", lane_validation=receipt, file_binding=None,
                rows=[{**item, "split": "train", "formal_view_sha256": str(index + 1) * 64}
                      for index, item in enumerate(source_rows(receipt))])


def fit_declaration(unavailable=()):
    receipt = lane_receipt(unavailable=unavailable)
    train = role("alignment-train-manifest/v1", file_binding=None,
                 rows=[{**item, "split": "train", "formal_view_sha256": str(index + 1) * 64,
                        "masks": dict.fromkeys(lane.MASKS, 0)} for index, item in enumerate(source_rows(receipt))])
    policy = role("alignment-fit-policy/v1", relation_policy=subject.RELATION_POLICY, checkpoint_selection="fixed_final_step",
                  budget={"trial_count": 12, "steps_per_trial": 80, "max_seconds": 180})
    return role(subject.FIT_SCHEMA, lane_validation=receipt, train_manifest=train, fit_policy=policy)


def rank_declaration(unavailable=(), ablation=(), projected=False):
    query_lane = lane_receipt(("train_a", "train_b", "query_c"), unavailable=unavailable, ablation=ablation)
    queries = role("alignment-target-free-queries/v1", file_binding=None, rows=source_rows(query_lane))
    policy = role("alignment-ranking-policy/v1", mode="projected_source_to_formal" if projected else "raw_source_to_source",
                  top_k=2, tie_break=subject.TIE_BREAK)
    checkpoint = None
    if projected:
        checkpoint = role("alignment-ranking-checkpoint-binding/v1", source_profile_sha256=query_lane["profile_sha256"],
                          formal_feature_space_sha256="d" * 64,
                          file_binding={"path": "never-read-checkpoint.json", "sha256": "e" * 64, "bytes": 10})
    return role(subject.RANK_SCHEMA, lane_validation=query_lane, queries=queries,
                frozen_bank=bank(lane_receipt()), ranking_policy=policy, checkpoint_binding=checkpoint)


def score_declaration(not_executed=False):
    rank = rank_declaration()
    saved = role("alignment-saved-ranking-bindings/v1", rank_declaration=rank, frozen_bank_sha256=subject._digest(rank["frozen_bank"]),
                 query_manifest_sha256=subject._digest(rank["queries"]), ranking_policy=rank["ranking_policy"],
                 checkpoint_binding_sha256=subject._digest(rank["checkpoint_binding"]), file_binding=None,
                 rows=[{"id": query["id"], "input_sha256": query["input_sha256"],
                        "status": "not_executed" if not_executed else "available",
                        "reason": "no ranking worker has run" if not_executed else None,
                        "hits": [] if not_executed else [{"candidate_id": "train_a", "score": 1.0},
                                                         {"candidate_id": "train_b", "score": 1.0}]}
                       for query in rank["queries"]["rows"]])
    refs = role("alignment-scoring-reference-bindings/v1", file_binding=None,
                rows=[{"id": query["id"], "input_sha256": query["input_sha256"], "reference_sha256": "f" * 64,
                       "admission_receipt_sha256": None, "fidelity_evaluation": 0,
                       "status": "declared_unadmitted", "reason": "no authenticated admission"}
                      for query in rank["queries"]["rows"]])
    policy = role("alignment-score-policy/v1", reference_policy="admitted_references_only/v1", metric_policy="not_implemented/v1")
    return role(subject.SCORE_SCHEMA, saved_rankings=saved, frozen_bank=rank["frozen_bank"], references=refs, score_policy=policy)


def refresh(declaration):
    for name, value in declaration.items():
        if name not in {"schema", "content_sha256"} and type(value) is dict:
            seal(value)
    return seal(declaration)


@pytest.mark.parametrize("factory,validator,stage", [
    (fit_declaration, subject.validate_fit_declaration, "fit"),
    (rank_declaration, subject.validate_rank_declaration, "rank"),
    (score_declaration, subject.validate_score_declaration, "score"),
])
def test_all_stages_are_deterministic_detached_and_inactive(factory, validator, stage):
    declaration = factory()
    original = deepcopy(declaration)
    expected = pins(declaration)
    result = validator(declaration, expected_bindings=expected)
    assert declaration == original
    assert result == validator(declaration, expected_bindings=expected)
    assert result["stage"] == stage
    assert all(result[name] is False for name in subject.FALSE)
    assert result["masks"] == dict.fromkeys(lane.MASKS, 0)
    assert result["optimizer_updates"] == result["model_calls"] == result["encoder_calls"] == result["prover_calls"] == 0
    assert result["content_sha256"] == subject._digest({key: item for key, item in result.items() if key != "content_sha256"})
    result["rows"][0]["id"] = "mutated-output"
    assert declaration == original
    assert expected == pins(declaration)


def test_fit_counts_proposed_budget_and_weak_identity_not_semantic_positives():
    value = fit_declaration(unavailable=("train_b",))
    result = subject.validate_fit_declaration(value, expected_bindings=pins(value))
    assert result["proposed_optimizer_updates"] == 960
    assert result["weak_structural_identity_pair_count"] == 2
    assert result["unknown_pair_count"] == 2
    assert result["permitted_negative_pair_count"] == result["semantic_positive_pair_count"] == 0
    assert result["fit_authorized"] is False
    assert result["status"] == "blocked_no_contrastive_admission"


def test_duplicate_formal_identity_only_changes_weak_pair_counts():
    value = fit_declaration()
    value["train_manifest"]["rows"][1]["formal_view_sha256"] = value["train_manifest"]["rows"][0]["formal_view_sha256"]
    refresh(value)
    result = subject.validate_fit_declaration(value, expected_bindings=pins(value))
    assert result["weak_structural_identity_pair_count"] == 4
    assert result["unknown_pair_count"] == result["semantic_positive_pair_count"] == 0


@pytest.mark.parametrize("field,inserted", [
    ("split", "validation"), ("masks", {**dict.fromkeys(lane.MASKS, 0), "contrastive_supervision": 1}),
    ("masks", {**dict.fromkeys(lane.MASKS, 0), "fidelity_evaluation": True}),
    ("input_sha256", "a" * 64), ("representation_sha256", "b" * 64),
])
def test_fit_rejects_nontrain_masks_and_source_vector_swaps_even_when_repinned(field, inserted):
    value = fit_declaration()
    value["train_manifest"]["rows"][0][field] = inserted
    refresh(value)
    with pytest.raises(ValueError):
        subject.validate_fit_declaration(value, expected_bindings=pins(value))


@pytest.mark.parametrize("field,inserted", [("checkpoint_selection", "best_DEV"), ("relation_policy", "every_unequal_id_is_negative")])
def test_fit_rejects_dev_selection_and_implicit_negatives(field, inserted):
    value = fit_declaration()
    value["fit_policy"][field] = inserted
    refresh(value)
    with pytest.raises(ValueError):
        subject.validate_fit_declaration(value, expected_bindings=pins(value))


@pytest.mark.parametrize("field,inserted", [("trial_count", True), ("steps_per_trial", 201), ("max_seconds", 0)])
def test_proposed_budget_is_closed_and_exactly_bounded(field, inserted):
    value = fit_declaration()
    value["fit_policy"]["budget"][field] = inserted
    refresh(value)
    with pytest.raises(ValueError):
        subject.validate_fit_declaration(value, expected_bindings=pins(value))


@pytest.mark.parametrize("factory,validator,role_name", [
    (fit_declaration, subject.validate_fit_declaration, "train_manifest"),
    (rank_declaration, subject.validate_rank_declaration, "queries"),
    (score_declaration, subject.validate_score_declaration, "references"),
])
def test_resealed_local_replacements_cannot_override_external_pins(factory, validator, role_name):
    value = factory()
    expected = pins(value)
    rows = value[role_name]["rows"]
    if role_name == "train_manifest":
        rows[0]["formal_view_sha256"] = "a" * 64
    elif role_name == "queries":
        value[role_name]["file_binding"] = {"path": "replacement.json", "sha256": "a" * 64, "bytes": 1}
    else:
        rows[0]["reference_sha256"] = "a" * 64
    refresh(value)
    with pytest.raises(ValueError, match="externally pinned"):
        validator(value, expected_bindings=expected)


@pytest.mark.parametrize("factory,validator", [
    (fit_declaration, subject.validate_fit_declaration), (rank_declaration, subject.validate_rank_declaration),
    (score_declaration, subject.validate_score_declaration),
])
def test_required_external_bindings_use_full_sealed_values_and_ordered_rows(factory, validator):
    value = factory()
    expected = pins(value)
    name = next(name for name, binding in expected.items() if binding["rows_sha256"] is not None)
    expected[name]["value_sha256"] = value[name]["content_sha256"]
    with pytest.raises(ValueError, match="externally pinned"):
        validator(value, expected_bindings=expected)
    expected = pins(value)
    expected[name]["rows_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="ordered rows"):
        validator(value, expected_bindings=expected)
    with pytest.raises(ValueError):
        validator(value, expected_bindings={})


def test_rank_retains_null_unavailable_and_separately_named_zero_ablation():
    value = rank_declaration(unavailable=("query_c",), ablation=("train_b",))
    value["frozen_bank"] = bank(lane_receipt(ablation=("train_b",)))
    refresh(value)
    result = subject.validate_rank_declaration(value, expected_bindings=pins(value))
    assert result["row_count"] == 3
    assert result["available_query_count"] == result["unavailable_query_count"] == result["zero_ablation_query_count"] == 1
    assert result["rows"][-1]["representation_sha256"] is None
    assert result["rows"][1]["status"] == "ablation_zero"
    assert result["ranking_authorized"] is False


@pytest.mark.parametrize("field", ["target", "reference_sha256", "group_id", "row_kind", "formal_view_sha256", "admitted"])
def test_query_reference_and_organizer_fields_are_rejected(field):
    value = rank_declaration()
    value["queries"]["rows"][0][field] = "forbidden"
    refresh(value)
    with pytest.raises(ValueError, match="closed"):
        subject.validate_rank_declaration(value, expected_bindings=pins(value))


def test_same_width_foreign_bank_profile_is_not_a_match():
    value = rank_declaration()
    other = value["frozen_bank"]["lane_validation"]
    other["profile_sha256"] = "a" * 64
    seal(other)
    refresh(value)
    with pytest.raises(ValueError, match="profiles differ"):
        subject.validate_rank_declaration(value, expected_bindings=pins(value))


def test_same_id_bank_source_swap_is_rejected_even_with_valid_local_lane_seals():
    value = rank_declaration()
    other = value["frozen_bank"]["lane_validation"]
    other["rows"][0]["input_sha256"] = "a" * 64
    binding = {key: other["rows"][0][key] for key in lane.ROW_BINDING_FIELDS}
    other["rows"][0]["producer_row_sha256"] = subject._digest(binding)
    value["frozen_bank"]["rows"][0]["input_sha256"] = "a" * 64
    seal(other)
    refresh(value)
    with pytest.raises(ValueError, match="same-id"):
        subject.validate_rank_declaration(value, expected_bindings=pins(value))


@pytest.mark.parametrize("mutation", [
    lambda value: value["queries"]["rows"].reverse(),
    lambda value: value["queries"]["rows"].pop(),
    lambda value: value["queries"]["rows"][0].update(representation_sha256="a" * 64),
    lambda value: value["frozen_bank"]["rows"][0].update(split="dev"),
    lambda value: value["ranking_policy"].update(top_k=True),
    lambda value: value["ranking_policy"].update(tie_break="insertion_order"),
])
def test_rank_rejects_ledger_bank_and_policy_drift(mutation):
    value = rank_declaration()
    mutation(value)
    refresh(value)
    with pytest.raises(ValueError):
        subject.validate_rank_declaration(value, expected_bindings=pins(value))


def test_projected_rank_checkpoint_has_its_own_exact_source_profile_and_file_pin():
    value = rank_declaration(projected=True)
    result = subject.validate_rank_declaration(value, expected_bindings=pins(value))
    assert result["status"] == "validated_reference_free_ranking_declaration_only"
    value["checkpoint_binding"]["source_profile_sha256"] = "a" * 64
    refresh(value)
    with pytest.raises(ValueError, match="checkpoint source profile"):
        subject.validate_rank_declaration(value, expected_bindings=pins(value))


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(checkpoint_binding=None),
    lambda value: value["checkpoint_binding"].update(file_binding=None),
    lambda value: value["checkpoint_binding"]["file_binding"].update(bytes=True),
    lambda value: value["checkpoint_binding"].update(qualified=True),
])
def test_projected_rank_rejects_missing_or_authoritative_checkpoint_metadata(mutation):
    value = rank_declaration(projected=True)
    mutation(value)
    refresh(value)
    with pytest.raises(ValueError):
        subject.validate_rank_declaration(value, expected_bindings=pins(value))


def test_score_keeps_all_pending_rows_and_declared_admission_does_not_enable_mask():
    value = score_declaration(not_executed=True)
    value["references"]["rows"][0]["admission_receipt_sha256"] = "a" * 64
    value["references"]["rows"][-1].update(status="unavailable", reference_sha256=None,
                                         admission_receipt_sha256=None, reason="no reference exists")
    refresh(value)
    result = subject.validate_score_declaration(value, expected_bindings=pins(value))
    assert result["status"] == "blocked_no_admitted_fidelity_references"
    assert result["row_count"] == 3
    assert result["declared_reference_count"] == 2
    assert result["unavailable_reference_count"] == 1
    assert result["admitted_reference_count"] == result["scored_query_count"] == 0
    assert all(row["score"] is None and row["fidelity_evaluation"] == 0 for row in result["rows"])


@pytest.mark.parametrize("status", ["unavailable", "ablation_zero"])
def test_saved_available_hits_cannot_override_selected_query_availability(status):
    value = score_declaration()
    rank = rank_declaration(**{"unavailable" if status == "unavailable" else "ablation": ("query_c",)})
    value["saved_rankings"]["rank_declaration"] = rank
    value["saved_rankings"]["query_manifest_sha256"] = subject._digest(rank["queries"])
    refresh(value)
    with pytest.raises(ValueError, match="unavailable/ablation"):
        subject.validate_score_declaration(value, expected_bindings=pins(value))


def test_saved_query_manifest_hash_must_match_received_full_generation():
    value = score_declaration()
    value["saved_rankings"]["query_manifest_sha256"] = "a" * 64
    refresh(value)
    with pytest.raises(ValueError, match="query manifest"):
        subject.validate_score_declaration(value, expected_bindings=pins(value))


def test_saved_projected_checkpoint_profile_is_checked_inside_generation():
    value = score_declaration()
    rank = rank_declaration(projected=True)
    rank["checkpoint_binding"]["source_profile_sha256"] = "a" * 64
    refresh(rank)
    saved = value["saved_rankings"]
    saved["rank_declaration"] = rank
    saved["ranking_policy"] = rank["ranking_policy"]
    saved["checkpoint_binding_sha256"] = subject._digest(rank["checkpoint_binding"])
    refresh(value)
    with pytest.raises(ValueError, match="checkpoint source profile"):
        subject.validate_score_declaration(value, expected_bindings=pins(value))


@pytest.mark.parametrize("mutation", [
    lambda value: value["references"]["rows"].reverse(),
    lambda value: value["references"]["rows"][0].update(input_sha256="a" * 64),
    lambda value: value["references"]["rows"][0].update(fidelity_evaluation=1),
    lambda value: value["references"]["rows"][0].update(fidelity_evaluation=False),
    lambda value: value["references"]["rows"][0].update(status="admitted"),
    lambda value: value["references"]["rows"][0].update(identity_authenticated=True),
    lambda value: value["saved_rankings"].update(frozen_bank_sha256="a" * 64),
    lambda value: value["saved_rankings"].update(checkpoint_binding_sha256="a" * 64),
])
def test_score_rejects_crossjoins_authority_and_foreign_bank(mutation):
    value = score_declaration()
    mutation(value)
    refresh(value)
    with pytest.raises(ValueError):
        subject.validate_score_declaration(value, expected_bindings=pins(value))


@pytest.mark.parametrize("mutation", [
    lambda hits: hits.reverse(),
    lambda hits: hits[0].update(candidate_id="foreign"),
    lambda hits: hits[0].update(candidate_id=hits[1]["candidate_id"]),
    lambda hits: hits.pop(),
    lambda hits: hits[0].update(score=True),
    lambda hits: hits[0].update(score=1),
])
def test_saved_hits_are_finite_complete_unique_and_deterministically_ordered(mutation):
    value = score_declaration()
    mutation(value["saved_rankings"]["rows"][0]["hits"])
    refresh(value)
    with pytest.raises(ValueError):
        subject.validate_score_declaration(value, expected_bindings=pins(value))


@pytest.mark.parametrize("number", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_saved_scores_reject_before_hashing(number):
    value = score_declaration()
    value["saved_rankings"]["rows"][0]["hits"][0]["score"] = number
    with pytest.raises(ValueError):
        subject.validate_score_declaration(value, expected_bindings={})


@pytest.mark.parametrize("factory,validator", [
    (fit_declaration, subject.validate_fit_declaration), (rank_declaration, subject.validate_rank_declaration),
    (score_declaration, subject.validate_score_declaration),
])
def test_stage_roles_are_mutually_exclusive_and_not_caller_authenticated(factory, validator):
    value = factory()
    value["foreign_stage_role"] = {"accepted": True}
    seal(value)
    with pytest.raises(ValueError, match="closed"):
        validator(value, expected_bindings=pins(value))


@pytest.mark.parametrize("field,inserted", [("model_calls", True), ("optimizer_updates", 1),
                                           ("source_fidelity_established", True), ("row_count", False)])
def test_lane_receipt_cannot_smuggle_execution_authority_or_numeric_aliases(field, inserted):
    value = fit_declaration()
    value["lane_validation"][field] = inserted
    refresh(value)
    with pytest.raises(ValueError):
        subject.validate_fit_declaration(value, expected_bindings=pins(value))


def test_plain_json_utf8_node_and_stage_byte_bounds_fail_closed():
    value = fit_declaration()
    value["fit_policy"]["budget"]["max_seconds"] = object()
    with pytest.raises(ValueError):
        subject.validate_fit_declaration(value, expected_bindings={})
    value = fit_declaration()
    value["train_manifest"]["file_binding"] = {"path": "\ud800", "bytes": 1, "sha256": "a" * 64}
    with pytest.raises(ValueError):
        subject.validate_fit_declaration(value, expected_bindings={})
    value = fit_declaration()
    value["oversized"] = "x" * (subject.MAX_BYTES + 1)
    with pytest.raises(ValueError, match="byte bound"):
        subject.validate_fit_declaration(value, expected_bindings={})


def test_import_and_validation_access_no_numerical_owner_or_file(tmp_path):
    declaration = score_declaration(not_executed=True)
    payload = tmp_path / "selected-values.json"
    payload.write_text(json.dumps({"declaration": declaration, "expected": pins(declaration)}), encoding="utf-8")
    code = r"""
import importlib.abc
import json
import sys
class RejectNumerics(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch','numpy','transformers','spacy','sentence_transformers'}:
            raise AssertionError('numerical dependency imported: '+fullname)
        if fullname.endswith(('.alignment_projection','.alignment_experiment','.legal_native_conditioning')):
            raise AssertionError('numerical owner imported: '+fullname)
sys.meta_path.insert(0, RejectNumerics())
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_stage_declarations as subject
with open(sys.argv[1], encoding='utf-8') as stream:
    values=json.load(stream)
def deny_io(event,args):
    if event in {'open','os.listdir','os.scandir','subprocess.Popen','socket.__new__'}:
        raise AssertionError('validator accessed I/O: '+event)
sys.addaudithook(deny_io)
result=subject.validate_score_declaration(values['declaration'],expected_bindings=values['expected'])
assert result['scored_query_count']==result['optimizer_updates']==0
"""
    repository = Path(subject.__file__).resolve().parents[4]
    completed = subprocess.run([sys.executable, "-c", code, str(payload)], cwd=repository,
                               capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
