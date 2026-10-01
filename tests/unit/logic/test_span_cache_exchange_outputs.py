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


def test_v4_outputs_separate_measured_vectors_rules_and_derived_bridge_targets(tmp_path):
    original = _observation()
    receipt, bundle = _bundle(tmp_path, original)
    row = bundle["census_rows"][0]
    assert row["schema_version"] == "uscode-autoformal-ae-compiler-census/v4"
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
    assert receipt["census_path_in_repo"].startswith("autoformal/uscode/census-v4/")
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


def _as_legacy(built, version):
    """Produce historical v2/v3 bundles with their original goal evidence shape."""
    old = copy.deepcopy(built)
    columns = exchange.CENSUS_COLUMNS_V2 if version == 2 else exchange.CENSUS_COLUMNS_V3
    schema = exchange.CENSUS_SCHEMA_V2 if version == 2 else exchange.CENSUS_SCHEMA_V3
    for census in old["census_rows"]:
        for name in set(census) - set(columns):
            census.pop(name)
        census["schema_version"] = schema
        census["census_sha256"] = exchange._row_hash(census)
    digest = old["census_rows"][0]["census_sha256"]
    for goal in old["goal_rows"]:
        packet, task = json.loads(goal["packet_json"]), json.loads(goal["task_json"])
        assert goal["record_kind"] == "repair_packet"
        capture = packet["row"]["capture"]
        if version == 2:
            capture.pop("observation_evidence")
        else:
            capture["observation_evidence"] = exchange._observation_evidence(old["census_rows"][0])
        capture["census_sha256"] = digest
        raw = exchange.canonical_bytes(packet)
        packet_digest = hashlib.sha256(raw).hexdigest()
        task["task_id"] = "AFTD-" + packet_digest[:20]
        goal.update(census_sha256=digest, packet_json=raw.decode(), packet_sha256=packet_digest,
                    task_id=task["task_id"], task_json=exchange._json(task),
                    task_sha256=hashlib.sha256(exchange.canonical_bytes(task)).hexdigest())
    return old


@pytest.mark.parametrize("version", [2, 3])
def test_pending_legacy_bundle_preserves_all_original_bytes_and_hashes(tmp_path, version):
    built = _as_legacy(exchange.exchange_from_compiled([_observation()], agent_id="legacy"), version)
    kwargs = dict(repository_id="justicedao/uscode-autoformal-span-cache", agent_id="legacy")
    first = exchange._save_bundle(built, tmp_path / "census.parquet", tmp_path / "goals.parquet", **kwargs)
    paths = [Path(first[kind]["path"]) for kind in ("census", "goals", "manifest")]
    before = {path: path.read_bytes() for path in paths}
    directory = "census" if version == 2 else "census-v3"
    assert first["census_path_in_repo"].startswith(f"autoformal/uscode/{directory}/legacy/")
    loaded = exchange.load_exchange_bundle(paths[-1])
    expected_schema = exchange.EXCHANGE_MANIFEST_SCHEMA_V2 if version == 2 else exchange.EXCHANGE_MANIFEST_SCHEMA_V3
    assert loaded["manifest"]["schema"] == expected_schema
    assert loaded["census_rows"] == built["census_rows"]
    assert loaded["goal_rows"] == built["goal_rows"]
    capture = loaded["repair_packets"][0]["packet"]["row"]["capture"]
    if version == 2:
        assert "observation_evidence" not in capture
    else:
        assert capture["observation_evidence"]["schema"] == "uscode-autoformal-output-evidence/v1"
        assert "autoencoder_formula_observation_json" not in capture["observation_evidence"]["outputs"]
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


def _learned_observation():
    """An authored wire fixture, not an attestation that a model generated it."""
    from ipfs_datasets_py.logic.autoformal.learned_formula_observation import (
        RUNTIME_ID, SCHEMA, learned_formula_model_identity,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_formula_learning import FALSE
    original = _observation()
    rule = {"actor": "agency", "action": "disclose", "object": "records", "modality": "F",
            "conditions": [], "exceptions": [], "temporal": []}
    formula = 'F(disclose(agency, "records"))'
    source_hash = hashlib.sha256(original["text"].encode()).hexdigest()
    policy = {**FALSE, "source_input_conditioned": True, "independent_text_to_logic": True,
              "learned_formula_generation": True, "training_executed": False,
              "teacher_forcing": False, "target_access": False}
    decoded = {**policy, "source_sha256": source_hash, "status": "decoded", "reason": None,
               "canonical_ir": {"rules": [rule]}, "formula_text": formula,
               "sample_memory_used": False, "family_syntax_checked": False, "temperature": 0,
               "generated_token_ids": [1, 3, 2], "minimum_decision_logit_margin": 0.5,
               "syntax_scope": "canonical_rule_schema_and_decoder_grammar",
               "formal_outputs": [{**FALSE, "family": "deontic", "format": "typed-deontic-rule/v1",
                   "origin": "learned_source_conditioned_formula_decoder", "payload": rule,
                   "formula_text": formula, "formula_text_role": "display_only_full_ast_is_authoritative",
                   "syntax_scope": "canonical_rule_schema_and_decoder_grammar"}]}
    receipt = {**policy, "schema": "learned-legal-formula-inference/v1",
               "lineage_id": "source_conditioned_formula_v1", "checkpoint_sha256": "a" * 64,
               "checkpoint_optimizer_steps": 1, "trained_checkpoint": True, "status": "decoded",
               "decoded_count": 1, "decoded_formulas_generated": True, "rows": [decoded]}
    files = {"fixture/runtime.py": "b" * 64}
    observation = {"schema": SCHEMA, "runtime_id": RUNTIME_ID,
        "model_identity": learned_formula_model_identity("a" * 64), "checkpoint_sha256": "a" * 64,
        "runtime_source_identity": {"files": files, "sha256": exchange._sha(exchange.canonical_bytes(files)),
            "scope": "listed_runtime_files_only_not_transitive_dependency_provenance"},
        "capture_source_sha256": "c" * 64, "source_text_sha256": source_hash,
        "source_span_id": original["source_span_id"], "row_index": 0, "inference": receipt,
        "inference_sha256": exchange._sha(exchange.canonical_bytes(receipt)),
        "provenance_scope": "local_runtime_capture_not_external_execution_attestation"}
    original["learned_formula_observation"] = observation
    return original


def _rehash_inference(original):
    observation = original["learned_formula_observation"]
    observation["inference_sha256"] = exchange._sha(exchange.canonical_bytes(observation["inference"]))


def test_full_learned_formula_and_provenance_survive_verified_export_and_goal_binding(tmp_path):
    original = _learned_observation()
    identity = original["learned_formula_observation"]["runtime_source_identity"]
    identity["files"].update({f"fixture/runtime_dependency_{index}.py": "d" * 64 for index in range(100)})
    identity["sha256"] = exchange._sha(exchange.canonical_bytes(identity["files"]))
    unused, bundle = _bundle(tmp_path, original)
    row = bundle["census_rows"][0]
    observation = original["learned_formula_observation"]
    decoded = observation["inference"]["rows"][0]
    assert row["autoencoder_output_kind"] == "learned_source_conditioned_formula"
    assert row["autoencoder_formula_status"] == "decoded"
    assert json.loads(row["autoencoder_formal_outputs_json"]) == decoded["formal_outputs"]
    assert json.loads(row["autoencoder_canonical_ir_json"]) == decoded["canonical_ir"]
    assert row["autoencoder_formula_text"] == decoded["formula_text"]
    assert json.loads(row["autoencoder_formula_observation_json"]) == observation
    assert json.loads(row["input_json"]) == original
    assert row["model_identity"] == observation["model_identity"]
    assert json.loads(row["autoencoder_formula_provenance_json"]) == {
        key: value for key, value in observation.items() if key != "inference"}
    # Legacy diagnostics are still retained, not overwritten by the new formula.
    assert json.loads(row["autoencoder_raw_decoder_json"])["embedding"] == [0.3, 0.4]
    evidence = bundle["repair_packets"][0]["packet"]["row"]["capture"]["observation_evidence"]
    assert evidence["schema"] == "uscode-autoformal-output-evidence/v2"
    ref = evidence["outputs"]["autoencoder_formula_observation_json"]
    assert "inline" not in ref
    assert ref["sha256"] == hashlib.sha256(row["autoencoder_formula_observation_json"].encode()).hexdigest()
    assert evidence["outputs"]["autoencoder_formal_outputs_json"]["inline"] == decoded["formal_outputs"]
    assert all(row[key] is False for key in ("admitted", "formalized", "wrote_compiler"))


@pytest.mark.parametrize("level,key", [
    ("receipt", "admitted"), ("row", "qualified"), ("row", "semantic_correctness_verified"),
    ("row", "target_access"), ("row", "teacher_forcing"), ("row", "training_executed"),
    ("row", "roundtrip_ok"), ("output", "proof_authority"), ("output", "formalized"),
])
def test_learned_false_authority_and_target_claims_are_rejected_even_after_rehash(tmp_path, level, key):
    original = _learned_observation()
    receipt = original["learned_formula_observation"]["inference"]
    value = receipt if level == "receipt" else receipt["rows"][0]
    if level == "output":
        value = value["formal_outputs"][0]
    value[key] = True
    _rehash_inference(original)
    with pytest.raises(SpanEvidenceError, match="invalid learned formula"):
        _bundle(tmp_path, original)
    assert not list(tmp_path.glob("*.parquet"))


@pytest.mark.parametrize("mutation", ["wrong_source", "wrong_span", "wrong_checkpoint", "wrong_schema", "bad_ast", "non_object"])
def test_learned_malformed_and_cross_source_receipts_are_rejected(tmp_path, mutation):
    original = _learned_observation()
    observation = original["learned_formula_observation"]
    if mutation == "wrong_source":
        original["text"] += " unless emergency."
    elif mutation == "wrong_span":
        original["source_span_id"] = "another-span"
    elif mutation == "wrong_checkpoint":
        observation["inference"]["checkpoint_sha256"] = "d" * 64
    elif mutation == "wrong_schema":
        observation["schema"] = "invented/v1"
    elif mutation == "bad_ast":
        observation["inference"]["rows"][0]["canonical_ir"]["rules"][0]["temporal"] = "ten days"
    _rehash_inference(original)
    if mutation == "non_object":
        original["learned_formula_observation"] = []
    with pytest.raises(SpanEvidenceError, match="invalid learned formula"):
        _bundle(tmp_path, original)


def test_learned_abstention_retains_raw_receipt_without_fabricated_outputs(tmp_path):
    original = _learned_observation()
    receipt = original["learned_formula_observation"]["inference"]
    receipt.update(status="abstained", decoded_count=0, decoded_formulas_generated=False)
    receipt["rows"][0].update(status="abstained", reason="unsupported source", canonical_ir=None,
                              formula_text=None, formal_outputs=[])
    _rehash_inference(original)
    unused, bundle = _bundle(tmp_path, original)
    row = bundle["census_rows"][0]
    assert row["autoencoder_formula_status"] == "abstained"
    assert row["autoencoder_formal_outputs_json"] == "[]"
    assert row["autoencoder_canonical_ir_json"] == "null"
    assert row["autoencoder_formula_text"] == ""
    assert json.loads(row["autoencoder_formula_observation_json"])["inference"] == receipt


def test_rehashed_census_cannot_rebind_a_learned_receipt_to_another_model(tmp_path):
    built = exchange.exchange_from_compiled([_learned_observation()], agent_id="test")
    built["goal_rows"] = []
    row = built["census_rows"][0]
    row["model_identity"] = "another-model"
    row["census_sha256"] = exchange._row_hash(row)
    with pytest.raises(SpanEvidenceError, match="census model identity differs"):
        exchange._save_bundle(built, tmp_path / "census.parquet", tmp_path / "goals.parquet",
                              repository_id=row["repository_id"], agent_id="test")


@pytest.mark.parametrize("agrees", [False, True])
def test_learned_paired_comparison_does_not_require_fabricated_text_or_vector_scores(tmp_path, agrees):
    original = _learned_observation()
    original.pop("strict_compiler_agreement")
    original["comparison"] = {"agrees": agrees, "comparable": True,
        "reason": "identical_formal_representations" if agrees else "formal_output_mismatch",
        "status": "agree" if agrees else "disagree", "capture": {}}
    unused, bundle = _bundle(tmp_path, original)
    row = bundle["census_rows"][0]
    assert json.loads(row["comparison_json"]) == original["comparison"]
    assert row["comparison_kind"] == "retained_formula_comparison_not_semantic_equivalence"
    assert row["autoencoder_text"] == ""
    assert row["cosine_similarity"] is row["cross_entropy_loss"] is row["reconstruction_loss"] is None
    assert row["agrees"] is (None if agrees else False)
    if agrees:
        assert not bundle["goal_rows"]
    else:
        assert len(bundle["repair_packets"]) == len(bundle["training_goals"]) == 1
        capture = bundle["repair_packets"][0]["packet"]["row"]["capture"]
        assert capture["observed_formula_comparison_reason"] == "formal_output_mismatch"
        assert row["reason"] == "strict_roundtrip_failed"


@pytest.mark.parametrize("lost_exception", [False, True])
def test_metadata_only_comparison_is_recomputed_before_suppressing_work(tmp_path, lost_exception):
    original = _learned_observation()
    original.pop("strict_compiler_agreement")
    decoded = original["learned_formula_observation"]["inference"]["rows"][0]
    rule = decoded["canonical_ir"]["rules"][0]
    rule["temporal"] = ["within 10 days"]
    # Fixture payload and canonical IR intentionally share the same rule.
    compiler_rule = {**copy.deepcopy(rule), "temporal_records": [
        {"temporal_kind": "within_duration", "quantity": 10, "value": "10 days"}]}
    if lost_exception:
        compiler_rule["exceptions"] = ["emergency"]
    original["compiler_result"]["rules"] = [compiler_rule]
    original["comparison"] = {"agrees": False, "comparable": True,
        "method": "exact_ast_and_validated_canonical_core/v2", "canonical_core_agrees": True,
        "difference_kind": "validated_temporal_metadata_only", "reason": "validated_temporal_metadata_only"}
    _rehash_inference(original)
    unused, bundle = _bundle(tmp_path, original)
    row = bundle["census_rows"][0]
    assert json.loads(row["comparison_json"]) == original["comparison"]
    if lost_exception:
        assert len(bundle["repair_packets"]) == len(bundle["training_goals"]) == 1
        assert row["agrees"] is False
    else:
        assert row["agrees"] is None
        assert row["reason"] == "validated_temporal_metadata_only"
        assert not bundle["goal_rows"]
