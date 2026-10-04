"""Authored canonical source rows, split isolation and bounded corpus admission."""
import io
import json
from dataclasses import fields
from urllib.parse import parse_qs, urlsplit

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.security import security_cve_corpus as corpus
from tests.unit.logic.formalization.autoencoder.test_security_cve_canonical_export import _raw_row, _license, _cid, _exclusions


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    pin = corpus.HuggingFaceSourcePin(revision="2" * 40, manifest_sha256="3" * 64,
        release_root=_cid("authored corpus release"))
    rows, selections = {}, {}
    for index, split in enumerate(corpus.SPLITS):
        raw = _raw_row()
        raw["repo_url"] = "https://github.com/authored-fixture/" + split
        raw["vulnerable_code"] = f"def {split}_check(value):\n    return value\n"
        raw["fixed_code"] = f"def {split}_check(value):\n    return max(value, 0)\n"
        row = corpus.canonical.CVEfixesRowAdapter().adapt(raw, row_index=17 + index)
        selection = corpus.canonical.SelectedCVERow(corpus.canonical.canonical_source_row_cid(row), 17 + index,
            raw["repo_url"], _cid("authored repository " + split), _cid("authored original shard"), "data/train-00000-of-00003.parquet")
        rows[raw["repo_url"]], selections[raw["repo_url"]] = raw, selection
    splits = {name: ["https://github.com/authored-fixture/" + name] for name in corpus.SPLITS}
    profile = corpus.build_security_corpus_profile(pin=pin, repository_splits=splits,
        graph_shards=["data/graph/nodes/part-000000.parquet"], exclusions=_exclusions())
    events = []
    control = {field.name: 1 for field in fields(corpus.native.HuggingFaceCompleteReleaseReceipt)}
    control.update(dataset_id=pin.dataset_id, revision=pin.revision, manifest_sha256=pin.manifest_sha256,
        release_root=pin.release_root, derived_dataset_root=_cid("authored derived dataset"),
        graph_root=_cid("authored graph"), retrieval_index_root=_cid("authored retrieval"), offline=True,
        verified=True, raw_originals_loaded=False, grants_execution_authority=False)
    def inspect(**kwargs):
        events.append("inspect")
        return {"pin": pin.to_dict(), "native_control_receipt": control,
            "artifact_groups": {"graph_nodes": {"files": 1, "bytes": 1, "rows": 1},
                                "bm25_documents": {"files": 1, "bytes": 1, "rows": 1}},
            "canonical_rows_reconstructed_from": "CID-verified original source rows through native canonical projector/classifier",
            "retrieval_tables_are_code_training_examples": False, "original_bodies_loaded_by_inspection": False,
            "policy_and_formal_views": "classification-only candidate targets; unresolved action/scope; no proved formulas",
            "proof_authority": False, "execution_authority": False}
    def select(**kwargs):
        events.append("metadata:" + kwargs["repository_urls"][0])
        return [selections[url] for url in kwargs["repository_urls"]], {
            "pin": pin.to_dict(), "license_provenance": _license(),
            "native_control_receipt": control,
            "routing_index_sha256": "4" * 64, "graph_artifacts": [{"path": "data/graph/nodes/part-000000.parquet",
                "sha256": "5" * 64, "content_id": _cid("authored graph artifact")}]}
    def fetch(selected, maximum):
        events.append("fetch:" + selected.repository_url)
        return corpus._bytes({"rows": [{"row_idx": selected.row_index,
            "row": rows[selected.repository_url], "truncated_cells": []}]})
    monkeypatch.setattr(corpus, "inspect_security_corpus", inspect)
    monkeypatch.setattr(corpus.canonical, "_select_rows", select)
    return {"profile": profile, "metadata_root": tmp_path, "data_root": tmp_path,
        "output": tmp_path / "security-corpus", "fetcher": fetch}, events, rows, selections


def test_corpus_roundtrip_native_body_pairs_and_source_features_only(scenario):
    args, events, _, _ = scenario
    receipt = corpus.ingest_security_corpus(**args)
    loaded = corpus.load_security_corpus(args["output"], expected_manifest_sha256=receipt["manifest_sha256"])
    assert receipt["totals"]["original_rows"] == 3 and receipt["totals"]["training_pairs"] == 6
    assert all(event.startswith("metadata:") for event in events[1:4])
    assert sum(event.startswith("fetch:") for event in events) == 3
    assert loaded["legacy_train_descriptor"]["output"] == str(args["output"] / "train")
    families = []
    for split, rows in loaded["splits"].items():
        assert len(rows) == 2
        families.extend({row["source_family"] for row in rows})
        for row in rows:
            assert row["input"]["ast_samples"]
            assert row["target"]["classification_only"] is True
            assert row["target"]["effect"] == "audit"
            assert "feature_counts" not in row["input"]
            assert "target" not in row["input"] and "cwe_ids" not in row["input"]
            assert not row["proof_authority"] and not row["execution_authority"]
    assert len(set(families)) == 3
    assert loaded["holdout_evaluated"] is False


@pytest.mark.parametrize("change", ["same_family", "alias_family", "benchmark", "empty_test", "row_budget", "byte_budget", "mutable_pin"])
def test_invalid_profile_refuses_before_inspection_or_fetch(scenario, change):
    args, events, _, _ = scenario
    profile = args["profile"]
    if change == "same_family": profile["repository_splits"]["test"] = profile["repository_splits"]["train"]
    elif change == "alias_family": profile["repository_splits"]["test"] = ["http://GITHUB.COM/Authored-Fixture/TRAIN.git/"]
    elif change == "benchmark": profile["repository_splits"]["test"] = ["https://github.com/bottlepy/bottle"]
    elif change == "empty_test": profile["repository_splits"]["test"] = []
    elif change == "row_budget": profile["budget"]["max_original_rows"] = 2
    elif change == "byte_budget": profile["budget"]["max_total_response_bytes"] = 0
    else: profile["pin"]["revision"] = "main"
    with pytest.raises(ValueError): corpus.ingest_security_corpus(**args)
    assert events == [] and not args["output"].exists()


def test_declared_response_budget_enforced_even_when_transport_ignores_limit(scenario):
    args, events, _, _ = scenario
    args["profile"]["budget"]["max_response_bytes"] = 20
    with pytest.raises(ValueError, match="response exceeds"):
        corpus.ingest_security_corpus(**args)
    assert sum(event.startswith("fetch:") for event in events) == 1
    assert not args["output"].exists()


def test_upstream_transport_uses_only_selected_row_and_response_bound(scenario, monkeypatch):
    _, _, _, selections = scenario
    selection = next(iter(selections.values()))
    calls = []
    def open_url(url, timeout):
        calls.append((url, timeout))
        return io.BytesIO(b"x" * 21)
    monkeypatch.setattr(corpus, "urlopen", open_url)
    with pytest.raises(ValueError, match="response exceeds"):
        corpus.fetch_corpus_cve_row(selection, 20)
    parsed = urlsplit(calls[0][0]); query = parse_qs(parsed.query)
    assert parsed.netloc == "datasets-server.huggingface.co" and parsed.path == "/rows"
    assert query["dataset"] == [corpus.canonical.CVEFIXES_DATASET_ID]
    assert query["config"] == ["default"]
    assert query["offset"] == [str(selection.row_index)] and query["length"] == ["1"]
    assert len(calls) == 1


def test_cross_family_duplicate_body_fails_before_publishing_any_corpus(scenario):
    args, _, rows, selections = scenario
    train_url, test_url = [args["profile"]["repository_splits"][split][0] for split in ("train", "test")]
    rows[test_url]["vulnerable_code"] = rows[train_url]["vulnerable_code"]
    row = corpus.canonical.CVEfixesRowAdapter().adapt(rows[test_url], row_index=selections[test_url].row_index)
    old = selections[test_url]
    selections[test_url] = corpus.canonical.SelectedCVERow(corpus.canonical.canonical_source_row_cid(row), old.row_index,
        old.repository_url, old.repository_node_cid, old.source_shard_cid, old.source_shard_path)
    with pytest.raises(ValueError, match="cross-split code-body"):
        corpus.ingest_security_corpus(**args)
    assert not args["output"].exists()


@pytest.mark.parametrize("change", ["proof", "holdout", "target_features", "split_path", "budget_total", "family_assignment", "graph_assignment", "inspection_raw_body", "inspection_authority"])
def test_rebound_corpus_manifest_cannot_change_closed_semantics(scenario, change):
    args, _, _, _ = scenario
    receipt = corpus.ingest_security_corpus(**args)
    path = args["output"] / "corpus-manifest.json"
    manifest = json.loads(path.read_bytes())
    if change == "proof": manifest["proof_authority"] = True
    elif change == "holdout": manifest["holdout_evaluated"] = True
    elif change == "target_features": manifest["input_semantics"] = "policy and graph labels"
    elif change == "split_path": manifest["exports"]["train"]["path"] = "../test"
    elif change == "budget_total": manifest["totals"]["original_rows"] = 1
    elif change == "family_assignment":
        manifest["profile"]["repository_splits"]["train"] = ["https://github.com/another/family"]
        manifest["profile_sha256"] = corpus._sha(corpus._bytes(manifest["profile"]))
    elif change == "graph_assignment":
        manifest["profile"]["graph_shards"] = ["data/graph/nodes/part-999999.parquet"]
        manifest["profile_sha256"] = corpus._sha(corpus._bytes(manifest["profile"]))
    elif change == "inspection_raw_body": manifest["source_inspection"]["raw_body"] = "def unapproved_body(): return 17"
    else: manifest["source_inspection"]["proof_authority"] = True
    raw = corpus._bytes(manifest); path.write_bytes(raw)
    with pytest.raises(ValueError):
        corpus.load_security_corpus(args["output"], expected_manifest_sha256=corpus._sha(raw))
