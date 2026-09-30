"""Explicit output columns preserve observations and immutable legacy outboxes."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import span_cache_exchange as exchange
from ipfs_datasets_py.logic.autoformal.span_evidence import SpanEvidenceError


def _observation():
    return {
        "source_span_id": "output-span",
        "legal_id": "usc:1:1",
        "text": "The agency shall not disclose records.",
        "strict_compiler_agreement": False,
        "compiler_result": {
            "status": "compiled",
            "reason": "strict_roundtrip_failed",
            "compilation_complete": True,
            "decompiled": "The agency shall not disclose records.",
            "rules": [{"norm_type": "prohibition", "action": "disclose"},
                      {"norm_type": "obligation", "action": "retain"}],
            "components": [{"text": "first clause", "status": "compiled"}],
        },
        "autoencoder_text": "",
        "autoencoder_observation": {
            "status": "diagnostic_observed",
            "raw_decoder": {"embedding": [0.3, 0.4], "cosine_similarity": 0.8,
                            "reconstruction_loss": 0.2, "safety_projection_used": False},
            "safety_projected_decoder": {"embedding": [0.5, 0.5],
                                         "target_conditioned": True},
            "embedding_representation": {"model": "mock:stable-sha256/8", "semantic": False},
        },
        "logic_target_observation": {
            "schema": "legacy-logic-target-observation/v1",
            "status": "captured", "origin": "source_bridge_target", "learned_output": False,
            "bridge_names": ["deontic_norms", "fol_tdfol"],
            "observed_families": [], "observed_views": ["deontic_norms", "fol"],
            "document": {"views": [{"name": "fol", "payload": {"formula": "P(a)"}}]},
            "admitted": False, "formalized": False,
        },
        "comparison": {"agrees": False, "reason": "inference_still_failing", "capture": {}},
    }


def _bundle(tmp_path, row=None):
    receipt = exchange.publish_compiled_exchange([row or _observation()], tmp_path)
    return receipt, exchange.load_exchange_bundle(receipt["manifest"]["path"])


def test_v3_outputs_separate_measured_vectors_rules_and_derived_bridge_targets(tmp_path):
    original = _observation()
    receipt, bundle = _bundle(tmp_path, original)
    row = bundle["census_rows"][0]
    assert row["schema_version"] == "uscode-autoformal-ae-compiler-census/v3"
    assert row["autoencoder_output_kind"] == "embedding_reconstruction"
    assert row["autoencoder_output_status"] == "diagnostic_observed"
    assert row["autoencoder_text"] == row["autoencoder_compiled"] == ""
    assert row["cosine_similarity"] is row["reconstruction_loss"] is None
    assert json.loads(row["autoencoder_raw_decoder_json"]) == original["autoencoder_observation"]["raw_decoder"]
    assert json.loads(row["autoencoder_safety_projected_decoder_json"])["target_conditioned"] is True
    assert json.loads(row["embedding_representation_json"])["semantic"] is False
    assert json.loads(row["compiler_rules_json"]) == original["compiler_result"]["rules"]
    assert json.loads(row["compiler_components_json"]) == original["compiler_result"]["components"]
    assert row["compilation_complete"] is True
    assert row["compiler_reason"] == "strict_roundtrip_failed"
    assert json.loads(row["logic_target_observation_json"])["learned_output"] is False
    assert json.loads(row["bridge_names_json"]) == ["deontic_norms", "fol_tdfol"]
    assert json.loads(row["observed_logic_views_json"]) == ["deontic_norms", "fol"]
    assert json.loads(row["observed_logic_families_json"]) == []
    assert json.loads(row["input_json"]) == original
    assert receipt["census_path_in_repo"].startswith("autoformal/uscode/census-v3/")
    assert not any(row[name] for name in ("admitted", "formalized", "wrote_compiler"))


def test_missing_outputs_are_explicit_and_single_legacy_rule_is_retained(tmp_path):
    original = _observation()
    original.pop("autoencoder_observation")
    original.pop("logic_target_observation")
    original["compiler_result"] = {"compiler_status": "compiled", "rule": {"id": "only-rule"}}
    unused, bundle = _bundle(tmp_path, original)
    row = bundle["census_rows"][0]
    assert row["autoencoder_output_kind"] == "unavailable"
    assert row["autoencoder_output_status"] == "not_observed"
    assert row["autoencoder_raw_decoder_json"] == "null"
    assert row["autoencoder_safety_projected_decoder_json"] == "null"
    assert row["logic_target_observation_json"] == "null"
    assert row["compiler_status"] == "compiled"
    assert json.loads(row["compiler_rules_json"]) == [{"id": "only-rule"}]
    assert row["compilation_complete"] is None


def test_deferred_goals_contain_bound_outputs_and_census_retrieval_without_execution(tmp_path):
    unused, bundle = _bundle(tmp_path)
    row = bundle["census_rows"][0]
    packet = bundle["repair_packets"][0]["packet"]
    evidence = packet["row"]["capture"]["observation_evidence"]
    assert evidence["census_sha256"] == row["census_sha256"]
    assert evidence["source_text_sha256"] == row["source_text_sha256"]
    assert evidence["input_json_sha256"] == hashlib.sha256(row["input_json"].encode()).hexdigest()
    assert evidence["retrieval"]["require_manifest_verification"] is True
    assert evidence["outputs"]["compiler_rules_json"]["inline"] == json.loads(row["compiler_rules_json"])
    assert evidence["outputs"]["autoencoder_raw_decoder_json"]["inline"]["embedding"] == [0.3, 0.4]
    assert packet["row"]["text"] == row["source_text"]
    assert evidence["counts_as_validation"] is False
    assert all(goal["enqueued"] is False for goal in bundle["goal_rows"])
    assert packet["allowed_edit_paths"] and packet["regression_tests"]


def test_large_formal_document_is_fully_retained_but_goals_use_bounded_hash_reference(tmp_path):
    original = _observation()
    original["logic_target_observation"]["document"]["large_formula"] = "P(a)" * 100_000
    unused, bundle = _bundle(tmp_path, original)
    row = bundle["census_rows"][0]
    assert json.loads(row["logic_target_observation_json"]) == original["logic_target_observation"]
    goal = bundle["repair_packets"][0]["packet"]
    reference = goal["row"]["capture"]["observation_evidence"]["outputs"]["logic_target_observation_json"]
    assert "inline" not in reference
    assert reference["sha256"] == hashlib.sha256(row["logic_target_observation_json"].encode()).hexdigest()
    assert len(exchange.canonical_bytes(goal)) < 64 * 1024


def _as_v2(built):
    """Produce a historical v2 bundle with the original, smaller goal capture."""
    old = copy.deepcopy(built)
    for census in old["census_rows"]:
        for name in set(census) - set(exchange.CENSUS_COLUMNS_V2):
            census.pop(name)
        census["schema_version"] = exchange.CENSUS_SCHEMA_V2
        census["census_sha256"] = exchange._row_hash(census)
    digest = old["census_rows"][0]["census_sha256"]
    for goal in old["goal_rows"]:
        packet, task = json.loads(goal["packet_json"]), json.loads(goal["task_json"])
        assert goal["record_kind"] == "repair_packet"
        capture = packet["row"]["capture"]
        capture.pop("observation_evidence")
        capture["census_sha256"] = digest
        raw = exchange.canonical_bytes(packet)
        packet_digest = hashlib.sha256(raw).hexdigest()
        task["task_id"] = "AFTD-" + packet_digest[:20]
        goal.update(census_sha256=digest, packet_json=raw.decode(), packet_sha256=packet_digest,
                    task_id=task["task_id"], task_json=exchange._json(task),
                    task_sha256=hashlib.sha256(exchange.canonical_bytes(task)).hexdigest())
    return old


def test_pending_v2_bundle_preserves_all_original_bytes_and_hashes(tmp_path):
    built = _as_v2(exchange.exchange_from_compiled([_observation()], agent_id="legacy"))
    kwargs = dict(repository_id="justicedao/uscode-autoformal-span-cache", agent_id="legacy")
    first = exchange._save_bundle(built, tmp_path / "census.parquet", tmp_path / "goals.parquet", **kwargs)
    paths = [Path(first[kind]["path"]) for kind in ("census", "goals", "manifest")]
    before = {path: path.read_bytes() for path in paths}
    assert first["census_path_in_repo"].startswith("autoformal/uscode/census/legacy/")
    loaded = exchange.load_exchange_bundle(paths[-1])
    assert loaded["manifest"]["schema"] == exchange.EXCHANGE_MANIFEST_SCHEMA_V2
    assert loaded["census_rows"] == built["census_rows"]
    assert loaded["goal_rows"] == built["goal_rows"]
    assert "observation_evidence" not in loaded["repair_packets"][0]["packet"]["row"]["capture"]
    assert exchange.pending_exchange_manifests(tmp_path) == [paths[-1]]
    repeated = exchange._save_bundle(loaded, paths[0], paths[1], **kwargs)
    assert repeated["fingerprint"] == first["fingerprint"]
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_queryable_columns_cannot_diverge_from_retained_input_even_with_new_hashes(tmp_path):
    built = exchange.exchange_from_compiled([_observation()], agent_id="test")
    built["goal_rows"] = []
    row = built["census_rows"][0]
    row["compiler_rules_json"] = '[{"invented":"rule"}]'
    row["census_sha256"] = exchange._row_hash(row)
    with pytest.raises(SpanEvidenceError, match="explicit output columns differ"):
        exchange._save_bundle(built, tmp_path / "census.parquet", tmp_path / "goals.parquet",
                              repository_id=row["repository_id"], agent_id="test")


def test_goal_inline_outputs_cannot_diverge_from_bound_census(tmp_path):
    built = exchange.exchange_from_compiled([_observation()], agent_id="test")
    goal = built["goal_rows"][0]
    packet, task = json.loads(goal["packet_json"]), json.loads(goal["task_json"])
    packet["row"]["capture"]["observation_evidence"]["outputs"]["compiler_rules_json"]["inline"] = []
    goal["packet_json"] = exchange._json(packet)
    goal["packet_sha256"] = hashlib.sha256(goal["packet_json"].encode()).hexdigest()
    task["task_id"] = "AFTD-" + goal["packet_sha256"][:20]
    goal["task_id"], goal["task_json"] = task["task_id"], exchange._json(task)
    goal["task_sha256"] = hashlib.sha256(goal["task_json"].encode()).hexdigest()
    with pytest.raises(SpanEvidenceError, match="goal output context differs"):
        exchange._save_bundle(built, tmp_path / "census.parquet", tmp_path / "goals.parquet",
                              repository_id=goal["repository_id"], agent_id="test")


def test_partial_compilation_gets_repair_and_training_without_rewriting_roundtrip(tmp_path):
    original = _observation()
    original["strict_compiler_agreement"] = True
    original["compiler_result"].update(
        reason="", roundtrip=True, compilation_complete=False,
        rules=[{"norm_type": "prohibition", "action": "disclose"}],
        components=[
            {"compiler_status": "compiled", "compilation_complete": True, "roundtrip": True},
            {"compiler_status": "abstain", "compilation_complete": False, "reason": "no_parser_elements"},
        ],
    )
    unused, bundle = _bundle(tmp_path, original)
    row = bundle["census_rows"][0]
    assert row["compiler_roundtrip"] is row["strict_compiler_agreement"] is True
    assert row["compilation_complete"] is False
    assert row["compiler_reason"] == ""
    assert row["reason"] == "strict_roundtrip_failed"
    assert row["agrees"] is False
    assert json.loads(row["input_json"]) == original
    assert len(bundle["repair_packets"]) == len(bundle["training_goals"]) == 1
    packet = bundle["repair_packets"][0]["packet"]
    assert packet["row"]["capture"]["compiler_repair_trigger"] == "incomplete_component_compilation"
    assert packet["row"]["capture"]["observed_strict_reason"] == ""
    assert any("canonical_decompiler.py" in path for path in packet["allowed_edit_paths"])
    assert any("deontic_parser.py" in path for path in packet["allowed_edit_paths"])
    assert not any(row[name] for name in ("admitted", "formalized", "wrote_compiler"))


def test_partial_component_evidence_gets_repair_even_with_good_text_metrics(tmp_path):
    original = _observation()
    original.update(strict_compiler_agreement=True, autoencoder_text=original["text"],
                    cosine_similarity=0.99, cross_entropy_loss=0.01, reconstruction_loss=0.01)
    original["comparison"] = {"agrees": True, "capture": {}}
    original["compiler_result"].update(
        reason="", rules=[], compilation_complete=False,
        components=[{"compiler_status": "compiled"}, {"compiler_status": "abstain"}],
    )
    unused, bundle = _bundle(tmp_path, original)
    assert len(bundle["repair_packets"]) == 1
    assert not bundle["training_goals"]
    assert bundle["census_rows"][0]["strict_compiler_agreement"] is True
    assert bundle["census_rows"][0]["reason"] == "strict_roundtrip_failed"


def test_full_abstention_keeps_existing_reason_without_partial_trigger(tmp_path):
    original = _observation()
    original["compiler_result"].update(
        status="abstain", reason="no_parser_elements", rules=[], compilation_complete=False,
        components=[{"compiler_status": "abstain", "compilation_complete": False}],
    )
    unused, bundle = _bundle(tmp_path, original)
    assert bundle["census_rows"][0]["reason"] == "no_parser_elements"
    packet = bundle["repair_packets"][0]["packet"]
    assert "compiler_repair_trigger" not in packet["row"]["capture"]
