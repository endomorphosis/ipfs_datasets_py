"""Historical outputs become queryable without model execution or work authority."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import span_cache_exchange as exchange

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/index_span_exchange_outputs.py"
SPEC = importlib.util.spec_from_file_location("tested_span_output_index", SCRIPT)
indexer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(indexer)


@pytest.fixture
def bundle(tmp_path):
    rule = {"modality": "obligation", "actor": "officer", "action": "retain"}
    text = "The officer shall retain records."
    receipt = exchange.publish_compiled_exchange([
        {"source_span_id": "span-index-1", "legal_id": "usc:1:1", "text": text,
         "compiler_result": {"status": "ok", "rule": rule, "decompiled": text},
         "autoencoder_text": "", "decompiled": text, "agrees": False,
         "autoencoder_observation": {
             "status": "diagnostic_observed", "embedding_representation": {"kind": "mock", "dimensions": 2},
             "raw_decoder": {"embedding": [0.25, -0.5], "cosine_similarity": 0.3, "reconstruction_loss": 0.8},
             "safety_projected_decoder": {"embedding": [0.4, -0.1], "target_conditioned": True}},
         "batch_observation": {"bridges": {"evaluation_invoked": ["fol_tdfol"]}},
         "metric_scope": "diagnostic_not_semantic", "producer_capture": "retain all original evidence"}
    ], tmp_path / "bundle", upload=False, agent_id="index-test", code_identity="code:test", model_identity="model:test")
    return Path(receipt["manifest"]["path"])


def test_retained_vectors_compiler_and_goal_bindings_are_queryable(bundle, tmp_path):
    result = indexer.build_index(bundle, tmp_path / "index", revision="a" * 40)
    row = pq.read_table(result["output_path"]).to_pylist()[0]
    source = exchange.load_exchange_bundle(bundle)
    original = source["census_rows"][0]
    assert row["autoencoder_raw_embedding"] == [0.25, -0.5]
    assert row["autoencoder_raw_reconstruction_loss"] == 0.8
    assert row["autoencoder_safety_projected_embedding"] == [0.4, -0.1]
    assert row["autoencoder_text"] == ""
    assert row["compiler_rule_count"] == 1
    assert json.loads(row["compiler_rules_json"])[0]["action"] == "retain"
    assert row["compiler_decompiled"] == row["source_text"]
    assert row["input_json"] == original["input_json"]
    assert row["source_text_sha256"] == original["source_text_sha256"]
    assert row["census_sha256"] == original["census_sha256"]
    assert row["source_manifest_sha256"] == hashlib.sha256(bundle.read_bytes()).hexdigest()
    assert row["logic_target_availability"] == "not_recorded_in_source"
    refs = json.loads(row["goal_references_json"])
    assert {ref["packet_sha256"] for ref in refs} == {goal["packet_sha256"] for goal in source["goal_rows"]}
    assert all(row[field] is False for field in ("admitted", "formalized", "enqueued", "inference_executed", "training_executed"))


def test_content_addressed_replay_is_idempotent(bundle, tmp_path):
    first = indexer.build_index(bundle, tmp_path / "index", revision="a" * 40)
    second = indexer.build_index(bundle, tmp_path / "index", revision="a" * 40)
    assert first == second
    assert len(list((tmp_path / "index").iterdir())) == 2


def test_components_are_retained_and_not_mistaken_for_missing_rules():
    rules = [{"action": "retain"}, {"action": "submit"}]
    assert indexer._rules({"components": [{"rule": rule} for rule in rules]}) == rules
    assert indexer._rules({"rules": rules, "rule": rules[0]}) == rules
    assert indexer._rules({"status": "abstain"}) == []


def test_missing_decoder_stays_missing_with_typed_nullable_columns(bundle, tmp_path):
    source = exchange.load_exchange_bundle(bundle)
    row = source["census_rows"][0]
    item = json.loads(row["input_json"])
    item.pop("autoencoder_observation")
    row["input_json"] = json.dumps(item)
    row.pop("autoencoder_raw_decoder_json", None)
    row.pop("autoencoder_safety_projected_decoder_json", None)
    derived = list(indexer.derive_rows(source, revision="a" * 40))[0]
    assert derived["autoencoder_raw_embedding"] is None
    assert derived["autoencoder_raw_cosine_similarity"] is None


def test_recorded_targets_are_separate_from_model_predictions(bundle):
    source = exchange.load_exchange_bundle(bundle)
    source["census_rows"][0]["logic_target_observation_json"] = json.dumps({"origin": "source_compiler", "document": {"formula": "O(retain)"}})
    derived = list(indexer.derive_rows(source, revision="a" * 40))[0]
    assert derived["logic_target_availability"] == "retained"
    assert derived["autoencoder_compiled"] == ""
    assert json.loads(derived["logic_target_observation_json"])["origin"] == "source_compiler"


def test_historical_compiler_status_and_top_level_target_fallback(bundle):
    source = exchange.load_exchange_bundle(bundle)
    row = source["census_rows"][0]
    original = json.loads(row["input_json"])
    original["compiler_result"] = {"compiler_status": "roundtrip_ok", "rule": {"action": "retain"}}
    original["logic_target_observation"] = {"document": {"formula": "O(retain)"}}
    row["input_json"] = json.dumps(original)
    row.pop("compiler_status", None)
    row.pop("logic_target_observation_json", None)
    derived = list(indexer.derive_rows(source, revision="a" * 40))[0]
    assert derived["compiler_status"] == "roundtrip_ok"
    assert derived["logic_target_availability"] == "retained"
    assert json.loads(derived["logic_target_observation_json"])["document"]["formula"] == "O(retain)"


@pytest.mark.parametrize("revision", ["main", "", "a" * 39, "Z" * 40])
def test_mutable_source_revisions_are_refused(bundle, tmp_path, revision):
    with pytest.raises(ValueError, match="immutable"):
        indexer.build_index(bundle, tmp_path / "index", revision=revision)
    assert not (tmp_path / "index").exists()


def test_input_corruption_is_detected_before_outputs(bundle, tmp_path):
    manifest = json.loads(bundle.read_text())
    (bundle.parent / manifest["census"]["filename"]).write_bytes(b"tampered")
    with pytest.raises(ValueError):
        indexer.build_index(bundle, tmp_path / "index", revision="a" * 40)
    assert not (tmp_path / "index").exists()


def test_cumulative_output_budget_is_checked_before_writes(bundle, tmp_path):
    with pytest.raises(ValueError, match="cumulative output"):
        indexer.build_index(bundle, tmp_path / "index", revision="a" * 40, remaining_output_bytes=1)
    assert not (tmp_path / "index").exists()


def test_decoded_expansion_is_bounded(bundle, tmp_path):
    with pytest.raises(ValueError, match="decoded|footer"):
        indexer.build_index(bundle, tmp_path / "index", revision="a" * 40, max_decoded_bytes=1)
    assert not (tmp_path / "index").exists()


class Api:
    def __init__(self, result):
        self.result = result
        self.created = []
        self.remote = {item["path_in_repo"]: item for item in result["manifest"]["source_files"]}

    def repo_info(self, **kwargs):
        return SimpleNamespace(sha="b" * 40)

    def get_paths_info(self, *, paths, **kwargs):
        return [SimpleNamespace(path=path, size=self.remote[path]["bytes"], lfs={"sha256": self.remote[path]["sha256"]}) for path in paths if path in self.remote]

    def create_commit(self, **kwargs):
        self.created.append(kwargs)
        for operation in kwargs["operations"]:
            raw = operation.path_or_fileobj
            self.remote[operation.path_in_repo] = indexer._remote_descriptor(operation.path_in_repo, raw)
        return SimpleNamespace(oid="c" * 40)


def test_upload_verifies_sources_and_uses_parent_cas_then_verifies_outputs(bundle, tmp_path):
    result = indexer.build_index(bundle, tmp_path / "index", revision="a" * 40)
    api = Api(result)
    published = indexer.publish_index(result, api=api)
    assert published["commit_sha"] == "c" * 40
    assert api.created[0]["parent_commit"] == "b" * 40
    assert len(api.created[0]["operations"]) == 2
    assert all(op.path_in_repo.startswith("autoformal/uscode/outputs/") for op in api.created[0]["operations"])
    indexer.publish_index(result, api=api)
    assert len(api.created) == 1


def test_upload_refuses_missing_pinned_source(bundle, tmp_path):
    result = indexer.build_index(bundle, tmp_path / "index", revision="a" * 40)
    api = Api(result)
    api.remote.clear()
    with pytest.raises(ValueError, match="missing required evidence"):
        indexer.publish_index(result, api=api)
    assert not api.created


def test_upload_cannot_replace_an_existing_conflicting_artifact(bundle, tmp_path):
    result = indexer.build_index(bundle, tmp_path / "index", revision="a" * 40)
    api = Api(result)
    path = result["manifest"]["output"]["path_in_repo"]
    api.remote[path] = indexer._remote_descriptor(path, b"conflicting")
    with pytest.raises(ValueError, match="digest or size"):
        indexer.publish_index(result, api=api)
    assert not api.created


def test_upload_rejects_local_mutation(bundle, tmp_path):
    result = indexer.build_index(bundle, tmp_path / "index", revision="a" * 40)
    api = Api(result)
    Path(result["output_path"]).write_bytes(b"mutated")
    with pytest.raises(ValueError, match="changed before upload"):
        indexer.publish_index(result, api=api)
    assert not api.created
