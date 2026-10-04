"""Handcrafted raw-vector arithmetic and boundary attacks; no semantic gold."""
from __future__ import annotations

import builtins
import hashlib
import json
import math
import random
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import alignment_lane_bundle as lanes
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_raw_ranking as subject
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_stage_declarations as stages


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def text_sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def seal(value):
    value["content_sha256"] = digest({key: item for key, item in value.items() if key != "content_sha256"})
    return value


def role(schema, **fields):
    return seal({"schema": schema, **fields})


def vector(width, coordinates):
    result = [0.0] * width
    for index, value in coordinates.items():
        result[index] = float(value)
    return result


def profile(lane, stage, *, recipe="exact_source_only/v1", normalization=None):
    derived = stage in lanes.DERIVED
    hidden = stage == "final_hidden_embedding"
    width = {"legacy8": 8, "native384": 384, "native768": 768, "leanstral": 4096}[lane]
    method = "tensor_endpoint" if derived else "last_token" if hidden else {
        "legacy8": "none", "native384": "mean", "native768": "cls"}[lane]
    return role(lanes.PROFILE_SCHEMA, lane_id=lane, stage=stage, dimension=width,
                producer={"profile_id": "synthetic-unreviewed-raw-vector/v1", "model_id": "no-model-loaded",
                          "model_revision": "synthetic-revision", "code_sha256": "a" * 64,
                          "model_assets_sha256": "b" * 64, "checkpoint_sha256": "c" * 64 if derived or hidden else None},
                pooling={"method": method, "endpoint": "synthetic/" + stage},
                normalization=normalization or {"kind": "none" if derived else "l2",
                                                "unit_tolerance": None if derived else 1e-5},
                precision="decimal6" if lane == "legacy8" and not derived else "float32",
                fit_input_recipe=recipe, inference_input_recipe=recipe)


def render(request, recipe):
    if recipe == "exact_source_only/v1":
        return request["source_text"]
    forward = recipe == "role_marked_declared_context/v1"
    return raw({"schema": "role-marked-source-context/v1", "source": {"role": "source", "text": request["source_text"]},
                "assumptions": {"role": "declared_assumptions", "text": request["context"]["text"] if forward else "",
                                "bindings": request["context"]["bindings"] if forward else {}}}).decode()


def sync_bundle(bundle):
    seal(bundle["profile"])
    receipt = bundle["producer_receipt"]
    receipt["profile_sha256"] = digest(bundle["profile"])
    receipt["rows"] = []
    for row in bundle["rows"]:
        row["input"]["context"]["sha256"] = text_sha(row["input"]["context"]["text"])
        row["input_sha256"] = digest(row["input"])
        row["encoder_text"] = render(row["input"], bundle["profile"]["inference_input_recipe"])
        row["encoder_text_sha256"] = text_sha(row["encoder_text"])
        row["vector_sha256"] = digest(row["vector"]) if row["vector"] is not None else None
        bound = {key: row[key] for key in lanes.ROW_BINDING_FIELDS}
        receipt["rows"].append(bound)
        row["producer_row_sha256"] = digest(bound)
    seal(receipt)
    seal(bundle)


def lane_pins(bundle):
    return {"profile_sha256": digest(bundle["profile"]), "producer_receipt_sha256": digest(bundle["producer_receipt"]),
            "inputs": [{"id": row["id"], "input_sha256": row["input_sha256"]} for row in bundle["rows"]]}


def bundle(declared, cohort, statuses, values=None, *, same_source=False):
    width = declared["dimension"]
    rows = []
    for index, status in enumerate(statuses):
        source = "É📄 same source with two opaque contexts." if same_source else f"É📄 synthetic {cohort} source {index}."
        context_text = cohort if same_source else ""
        request = {"source_text": source, "context": {"role": "declared_context" if same_source else "none_required",
                                                       "text": context_text, "bindings": {}, "sha256": text_sha(context_text)}}
        value = vector(width, {index % width: 1.0}) if values is None else deepcopy(values[index])
        if status == "ablation_zero":
            value = [0.0] * width
        if status == "unavailable":
            value = None
        rows.append({"id": f"{cohort}-{index}", "input": request, "status": status,
                     "reason": None if status == "available" else "Synthetic declared " + status,
                     "vector": value, "upstream_vector_sha256": digest([float(index)]) if declared["stage"] in lanes.DERIVED else None,
                     "token_receipt_sha256": None if declared["lane_id"] == "legacy8" else digest({"synthetic_tokens": [index, 2]})})
    result = {"schema": lanes.SCHEMA, "profile": deepcopy(declared), "rows": rows,
              "producer_receipt": {"schema": lanes.PRODUCER_SCHEMA, "artifact_binding": {
                  "path": f"synthetic-unread-{cohort}.json", "bytes": 100, "sha256": digest(cohort)}, "rows": []}}
    sync_bundle(result)
    return result


def source_rows(validation):
    return [{"id": row["id"], "input_sha256": row["input_sha256"], "representation_sha256": row["vector_sha256"],
             "status": row["status"], "reason": row["reason"]} for row in validation["rows"]]


def stage_pins(declaration):
    names = ("lane_validation", "queries", "frozen_bank", "ranking_policy", "checkpoint_binding")
    return {name: {"value_sha256": digest(declaration[name]),
                   "rows_sha256": digest(declaration[name]["rows"]) if isinstance(declaration[name], dict)
                   and "rows" in declaration[name] else None} for name in names}


def declaration(query, bank, *, top_k=3, mode="raw_source_to_source"):
    q_lane = lanes.validate_lane_bundle(query, expected_bindings=lane_pins(query))
    b_lane = lanes.validate_lane_bundle(bank, expected_bindings=lane_pins(bank))
    frozen = role("alignment-frozen-train-bank/v1", lane_validation=b_lane,
                  rows=[{**row, "split": "train", "formal_view_sha256": digest({"weak_opaque_view": row["id"]})}
                        for row in source_rows(b_lane)], file_binding=None)
    policy = role("alignment-ranking-policy/v1", mode=mode, top_k=top_k, tie_break=stages.TIE_BREAK)
    checkpoint = None if mode == "raw_source_to_source" else role(
        "alignment-ranking-checkpoint-binding/v1", source_profile_sha256=q_lane["profile_sha256"],
        formal_feature_space_sha256="f" * 64, file_binding={"path": "not-loaded.json", "bytes": 1, "sha256": "e" * 64})
    return role(stages.RANK_SCHEMA, lane_validation=q_lane,
                queries=role("alignment-target-free-queries/v1", rows=source_rows(q_lane), file_binding=None),
                frozen_bank=frozen, ranking_policy=policy, checkpoint_binding=checkpoint)


def case(lane="native384", stage="raw_embedding", *, query_statuses=("available",),
         bank_statuses=("available", "available", "available"), top_k=3, query_vectors=None,
         bank_vectors=None, same_source=False, recipe="exact_source_only/v1", normalization=None):
    declared = profile(lane, stage, recipe=recipe, normalization=normalization)
    q = bundle(declared, "query", query_statuses, query_vectors, same_source=same_source)
    b = bundle(declared, "train", bank_statuses, bank_vectors, same_source=same_source)
    d = declaration(q, b, top_k=top_k)
    return d, q, b, {"expected_bindings": stage_pins(d), "expected_query_lane": lane_pins(q), "expected_bank_lane": lane_pins(b)}


def run(data):
    d, q, b, pins = data
    return subject.rank_raw_source_bundles(d, q, b, **pins)


def assert_scope(result):
    assert set(result) == {"saved_rankings", "diagnostic_receipt"}
    for value in result.values():
        assert value["content_sha256"] == digest({key: item for key, item in value.items() if key != "content_sha256"})
    report = result["diagnostic_receipt"]
    assert all(report[name] is False for name in subject.FALSE)
    assert report["masks"] == dict.fromkeys(lanes.MASKS, 0)
    assert all(type(value) is int for value in report["masks"].values())
    assert report["verification_status"] == report["admission_status"] == "pending"
    assert report["ranking_operation_executed"] is True
    assert report["vector_values_modified"] is False
    assert report["exact_id_disjointness_verified"] is report["exact_full_input_disjointness_verified"] is True
    for name in ("optimizer_updates", "model_calls", "encoder_calls", "decoder_calls", "prover_calls", "checkpoint_loads",
                 "fidelity_scored_query_count"):
        assert type(report[name]) is int and report[name] == 0


def validate_saved_as_blocked_scoring(saved):
    references = role("alignment-scoring-reference-bindings/v1", rows=[{
        "id": row["id"], "input_sha256": row["input_sha256"], "reference_sha256": None,
        "admission_receipt_sha256": None, "fidelity_evaluation": 0, "status": "unavailable",
        "reason": "No semantic reference supplied in this synthetic arithmetic test."} for row in saved["rows"]], file_binding=None)
    score = role(stages.SCORE_SCHEMA, saved_rankings=saved, frozen_bank=saved["rank_declaration"]["frozen_bank"],
                 references=references, score_policy=role("alignment-score-policy/v1", reference_policy="admitted_references_only/v1",
                                                          metric_policy="not_implemented/v1"))
    pins = {name: {"value_sha256": digest(score[name]),
                   "rows_sha256": digest(score[name]["rows"]) if "rows" in score[name] else None}
            for name in ("saved_rankings", "frozen_bank", "references", "score_policy")}
    receipt = stages.validate_score_declaration(score, expected_bindings=pins)
    assert receipt["scored_query_count"] == receipt["optimizer_updates"] == 0
    assert receipt["scoring_authorized"] is False


@pytest.mark.parametrize("lane,stage", [("legacy8", "historical_linguistic_features"),
                                       ("native384", "raw_embedding"), ("native768", "raw_embedding")])
def test_all_raw_lanes_execute_exact_source_arithmetic_without_fitting(lane, stage):
    data = case(lane, stage)
    before = deepcopy(data)
    rng = random.getstate()
    result = run(data)
    assert_scope(result)
    assert random.getstate() == rng and data == before
    hits = result["saved_rankings"]["rows"][0]["hits"]
    assert [(hit["candidate_id"], hit["score"]) for hit in hits] == [("train-0", 1.0), ("train-1", 0.0), ("train-2", 0.0)]
    assert result["diagnostic_receipt"]["similarity_evaluation_count"] == 3
    assert result["diagnostic_receipt"]["cosine_computation_executed"] is True
    validate_saved_as_blocked_scoring(result["saved_rankings"])


def test_cosine_of_rounded_historical_features_uses_actual_norms_not_dot_product():
    q = vector(8, {0: 0.707107, 1: 0.707107})
    b = [vector(8, {0: 1.0}), vector(8, {1: 1.0}), vector(8, {0: -1.0})]
    data = case("legacy8", "historical_linguistic_features", query_vectors=[q], bank_vectors=b)
    result = run(data)
    scores = [hit["score"] for hit in result["saved_rankings"]["rows"][0]["hits"]]
    assert scores == pytest.approx([1 / math.sqrt(2), 1 / math.sqrt(2), -1 / math.sqrt(2)], abs=1e-15)
    assert scores[0] != q[0]
    assert data[1]["rows"][0]["vector"] == q
    assert_scope(result)


def test_hypot_normalized_operands_avoid_product_overflow_without_changing_coordinates():
    large = vector(8, {0: 1e308})
    data = case("legacy8", "historical_linguistic_features", query_vectors=[large], bank_vectors=[large],
                bank_statuses=("available",), normalization={"kind": "none", "unit_tolerance": None})
    result = run(data)
    assert result["saved_rankings"]["rows"][0]["hits"][0]["score"] == 1.0
    assert data[1]["rows"][0]["vector"][0] == 1e308
    assert_scope(result)


def test_ties_are_by_candidate_id_independent_of_bank_order_and_top_k_is_capped_by_eligible_rows():
    unit = vector(384, {0: 1.0})
    d, q, b, _ = case(bank_vectors=[unit, unit, unit], top_k=20)
    for row, identity in zip(b["rows"], ["train-z", "train-a", "train-m"], strict=True):
        row["id"] = identity
    sync_bundle(b)
    d = declaration(q, b, top_k=20)
    data = (d, q, b, {"expected_bindings": stage_pins(d), "expected_query_lane": lane_pins(q), "expected_bank_lane": lane_pins(b)})
    result = run(data)
    assert [hit["candidate_id"] for hit in result["saved_rankings"]["rows"][0]["hits"]] == ["train-a", "train-m", "train-z"]
    assert result["diagnostic_receipt"]["returned_hit_count"] == 3
    validate_saved_as_blocked_scoring(result["saved_rankings"])


def test_unavailable_and_ablation_queries_are_preserved_and_never_compared(monkeypatch):
    data = case(query_statuses=("available", "unavailable", "ablation_zero"),
                bank_statuses=("available", "unavailable", "ablation_zero"))
    original = subject._cosine
    calls = []

    def observed(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(subject, "_cosine", observed)
    result = run(data)
    rows = result["saved_rankings"]["rows"]
    assert [row["status"] for row in rows] == ["available", "unavailable", "unavailable"]
    assert [row["reason"] for row in rows] == [None, "query_representation_unavailable", "query_representation_ablation_zero"]
    assert rows[1]["hits"] == rows[2]["hits"] == []
    assert len(calls) == result["diagnostic_receipt"]["similarity_evaluation_count"] == 1
    report = result["diagnostic_receipt"]
    assert (report["query_count"], report["ranked_query_count"], report["unavailable_ranking_count"]) == (3, 1, 2)
    assert (report["bank_row_count"], report["eligible_candidate_count"], report["unavailable_candidate_count"],
            report["zero_ablation_candidate_count"]) == (3, 1, 1, 1)
    assert_scope(result)
    validate_saved_as_blocked_scoring(result["saved_rankings"])


@pytest.mark.parametrize("bank_statuses", [("unavailable",), ("ablation_zero",), ("unavailable", "ablation_zero")])
def test_empty_eligible_bank_preserves_all_queries_without_cosine_calls(bank_statuses, monkeypatch):
    data = case(query_statuses=("available", "unavailable", "ablation_zero"), bank_statuses=bank_statuses)
    monkeypatch.setattr(subject, "_cosine", lambda *args: pytest.fail("unavailable/ablation candidate was numerically used"))
    result = run(data)
    assert all(row["status"] == "unavailable" and row["hits"] == [] for row in result["saved_rankings"]["rows"])
    assert result["saved_rankings"]["rows"][0]["reason"] == "no_available_train_candidates"
    assert result["diagnostic_receipt"]["cosine_computation_executed"] is False
    assert result["diagnostic_receipt"]["similarity_evaluation_count"] == result["diagnostic_receipt"]["ranked_query_count"] == 0
    assert_scope(result)
    validate_saved_as_blocked_scoring(result["saved_rankings"])


@pytest.mark.parametrize("recipe", sorted(lanes.RECIPES))
def test_same_source_or_encoder_text_with_distinct_declared_context_inputs_does_not_fabricate_self_overlap(recipe):
    data = case(same_source=True, recipe=recipe)
    d, q, b, _ = data
    assert q["rows"][0]["input"]["source_text"] == b["rows"][0]["input"]["source_text"]
    assert q["rows"][0]["input_sha256"] != b["rows"][0]["input_sha256"]
    if recipe != "role_marked_declared_context/v1":
        assert q["rows"][0]["encoder_text_sha256"] == b["rows"][0]["encoder_text_sha256"]
    result = run(data)
    assert result["diagnostic_receipt"]["ranked_query_count"] == 1
    assert result["diagnostic_receipt"]["derivative_provenance_exclusion_verified"] is False
    assert_scope(result)


@pytest.mark.parametrize("overlap", ["id", "full_input"])
def test_self_overlap_is_rejected_for_any_status_before_arithmetic(overlap, monkeypatch):
    _, q, b, _ = case(query_statuses=("unavailable",))
    if overlap == "id":
        b["rows"][0]["id"] = q["rows"][0]["id"]
        # Same-ID ledger association must agree before the stricter raw gate.
        b["rows"][0]["input"] = deepcopy(q["rows"][0]["input"])
        b["rows"][0]["status"] = "unavailable"
        b["rows"][0]["reason"] = q["rows"][0]["reason"]
        b["rows"][0]["vector"] = None
    else:
        b["rows"][0]["input"] = deepcopy(q["rows"][0]["input"])
    sync_bundle(b)
    d = declaration(q, b)
    monkeypatch.setattr(subject, "_cosine", lambda *args: pytest.fail("self ranking was attempted"))
    with pytest.raises(ValueError, match="overlap"):
        run((d, q, b, {"expected_bindings": stage_pins(d), "expected_query_lane": lane_pins(q), "expected_bank_lane": lane_pins(b)}))


@pytest.mark.parametrize("stage", ["learned_latent", "learned_projection", "reconstruction", "decoder_condition"])
def test_learned_same_width_views_do_not_enter_the_raw_worker(stage, monkeypatch):
    data = case(stage=stage)
    monkeypatch.setattr(subject, "_cosine", lambda *args: pytest.fail("learned endpoint entered raw ranking"))
    with pytest.raises(ValueError, match="learned/final-hidden"):
        run(data)


def test_leanstral_hidden_declaration_is_outside_the_raw_worker(monkeypatch):
    data = case("leanstral", "final_hidden_embedding")
    monkeypatch.setattr(subject, "_cosine", lambda *args: pytest.fail("Leanstral was used"))
    with pytest.raises(ValueError, match="learned/final-hidden"):
        run(data)


@pytest.mark.parametrize("mode", ["projected_source_to_source", "projected_source_to_formal"])
def test_projected_modes_are_rejected_without_loading_the_checkpoint(mode, monkeypatch):
    _, q, b, _ = case()
    d = declaration(q, b, mode=mode)
    monkeypatch.setattr(subject, "_cosine", lambda *args: pytest.fail("unsupported projected mode performed arithmetic"))
    with pytest.raises(ValueError, match="only checkpoint-free raw"):
        run((d, q, b, {"expected_bindings": stage_pins(d), "expected_query_lane": lane_pins(q), "expected_bank_lane": lane_pins(b)}))


@pytest.mark.parametrize("cohort", ["query", "bank"])
@pytest.mark.parametrize("attack", ["vector", "source", "profile", "token"])
def test_fully_rehashed_local_bundle_substitutions_cannot_replace_external_producer_pins(cohort, attack, monkeypatch):
    d, q, b, pins = case()
    target = q if cohort == "query" else b
    if attack == "vector":
        target["rows"][0]["vector"] = vector(384, {2: 1.0})
    elif attack == "source":
        target["rows"][0]["input"]["source_text"] += " A foreign exact source."
    elif attack == "profile":
        target["profile"]["producer"]["model_revision"] = "foreign-same-width-revision"
    else:
        target["rows"][0]["token_receipt_sha256"] = "e" * 64
    sync_bundle(target)
    monkeypatch.setattr(subject, "_cosine", lambda *args: pytest.fail("unpinned producer entered arithmetic"))
    with pytest.raises(ValueError, match="externally pinned"):
        run((d, q, b, pins))


@pytest.mark.parametrize("cohort", ["query", "bank"])
def test_newly_selected_bundle_still_must_equal_the_declared_lane_generation(cohort, monkeypatch):
    d, q, b, pins = case()
    target = q if cohort == "query" else b
    target["rows"][0]["vector"] = vector(384, {2: 1.0})
    sync_bundle(target)
    pins["expected_query_lane" if cohort == "query" else "expected_bank_lane"] = lane_pins(target)
    monkeypatch.setattr(subject, "_cosine", lambda *args: pytest.fail("different lane generation entered arithmetic"))
    with pytest.raises(ValueError, match="bundle differs from declared lane receipt"):
        run((d, q, b, pins))


@pytest.mark.parametrize("role_name", ["lane_validation", "queries", "frozen_bank", "ranking_policy", "checkpoint_binding"])
def test_resealed_stage_role_substitution_is_rejected_against_selected_generation(role_name, monkeypatch):
    d, q, b, pins = case()
    if role_name == "lane_validation":
        d[role_name]["bundle_sha256"] = "e" * 64
        seal(d[role_name])
    elif role_name == "queries":
        d[role_name]["file_binding"] = {"path": "foreign.json", "bytes": 1, "sha256": "e" * 64}
        seal(d[role_name])
    elif role_name == "frozen_bank":
        d[role_name]["rows"][0]["formal_view_sha256"] = "e" * 64
        seal(d[role_name])
    elif role_name == "ranking_policy":
        d[role_name]["top_k"] = 1
        seal(d[role_name])
    else:
        # This becomes an invalid raw-mode checkpoint association rather than
        # an executable projection, even with a newly valid local checksum.
        d[role_name] = role("alignment-ranking-checkpoint-binding/v1", source_profile_sha256="e" * 64,
                             formal_feature_space_sha256="f" * 64, file_binding=None)
    seal(d)
    monkeypatch.setattr(subject, "_cosine", lambda *args: pytest.fail("foreign stage generation entered arithmetic"))
    with pytest.raises(ValueError):
        run((d, q, b, pins))


@pytest.mark.parametrize("location", ["query", "query_row", "bank", "bank_row", "bundle_row", "profile", "declaration"])
@pytest.mark.parametrize("field", ["reference_sha256", "target", "proof_authority"])
def test_reference_or_authority_fields_are_not_accepted_by_raw_input_schemas(location, field, monkeypatch):
    d, q, b, pins = case()
    targets = {"query": d["queries"], "query_row": d["queries"]["rows"][0], "bank": d["frozen_bank"],
               "bank_row": d["frozen_bank"]["rows"][0], "bundle_row": q["rows"][0],
               "profile": q["profile"], "declaration": d}
    targets[location][field] = True if field == "proof_authority" else "e" * 64 if field == "reference_sha256" else {"rules": []}
    if location in {"query", "query_row"}:
        seal(d["queries"])
    elif location in {"bank", "bank_row"}:
        seal(d["frozen_bank"])
    if location == "profile":
        seal(q["profile"])
    seal(q)
    seal(d)
    monkeypatch.setattr(subject, "_cosine", lambda *args: pytest.fail("reference-bearing input entered arithmetic"))
    with pytest.raises(ValueError):
        run((d, q, b, pins))


def test_dev_candidate_and_foreign_width_fail_before_any_arithmetic(monkeypatch):
    d, q, b, pins = case()
    d["frozen_bank"]["rows"][0]["split"] = "validation"
    seal(d["frozen_bank"])
    seal(d)
    pins["expected_bindings"] = stage_pins(d)
    monkeypatch.setattr(subject, "_cosine", lambda *args: pytest.fail("DEV row entered TRAIN bank arithmetic"))
    with pytest.raises(ValueError, match="non-TRAIN"):
        run((d, q, b, pins))
    d, q, b, pins = case()
    b["rows"][0]["vector"].pop()
    sync_bundle(b)
    pins["expected_bank_lane"] = lane_pins(b)
    with pytest.raises(ValueError, match="exact-width"):
        run((d, q, b, pins))


@pytest.mark.parametrize("coordinate", [True, 1, float("nan"), float("inf"), 0.1])
def test_bad_native_coordinates_never_reach_cosine(coordinate, monkeypatch):
    d, q, b, pins = case()
    q["rows"][0]["vector"][0] = coordinate
    if type(coordinate) is float and not math.isfinite(coordinate):
        # Ordinary JSON validation must fail even before local seals exist.
        pass
    else:
        sync_bundle(q)
        pins["expected_query_lane"] = lane_pins(q)
    monkeypatch.setattr(subject, "_cosine", lambda *args: pytest.fail("invalid native coordinates reached cosine"))
    with pytest.raises(ValueError):
        run((d, q, b, pins))


def test_zero_available_vector_and_empty_bank_are_rejected_before_arithmetic(monkeypatch):
    d, q, b, pins = case()
    q["rows"][0]["vector"] = [0.0] * 384
    sync_bundle(q)
    pins["expected_query_lane"] = lane_pins(q)
    monkeypatch.setattr(subject, "_cosine", lambda *args: pytest.fail("zero available vector reached cosine"))
    with pytest.raises(ValueError, match="zero/nonfinite norm"):
        run((d, q, b, pins))
    d, q, b, pins = case()
    b["rows"] = []
    sync_bundle(b)
    pins["expected_bank_lane"] = lane_pins(b)
    with pytest.raises(ValueError):
        run((d, q, b, pins))


def test_saved_generations_are_detached_repeatable_and_not_file_or_runtime_attestations(monkeypatch):
    data = case()
    before = deepcopy(data)

    def forbidden(*args, **kwargs):
        raise AssertionError("pure ranking helper attempted filesystem/model access")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    result = run(data)
    assert result == run(data)
    assert data == before
    assert_scope(result)
    result["saved_rankings"]["rank_declaration"]["queries"]["rows"][0]["id"] = "mutated-returned-generation"
    result["diagnostic_receipt"]["masks"]["contrastive_supervision"] = 1
    assert data == before
    assert run(data)["diagnostic_receipt"]["masks"]["contrastive_supervision"] == 0


def test_helper_import_requires_no_optional_model_or_proof_stack():
    code = r"""
import importlib, importlib.abc, sys
class Reject(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch','numpy','spacy','transformers','sentence_transformers','z3','lean'}:
            raise AssertionError('optional stack import: '+fullname)
sys.meta_path.insert(0,Reject())
subject=importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.alignment_raw_ranking')
try:
    subject.rank_raw_source_bundles({}, {}, {}, expected_bindings={}, expected_query_lane={}, expected_bank_lane={})
except ValueError:
    pass
else:
    raise AssertionError('empty declarations accepted')
assert all(name not in sys.modules for name in ('torch','numpy','spacy','transformers','z3','lean'))
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20,
                            cwd=Path(subject.__file__).resolve().parents[4])
    assert result.returncode == 0, result.stderr
