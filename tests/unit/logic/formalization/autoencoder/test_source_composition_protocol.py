"""Protect the benchmark's split and target-free timing contracts."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[5]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, REPO / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


panel = load("composition_test_fixture", "tests/fixtures/logic/source_reconstruction_v2.py")
driver = load("structured_benchmark_test", "scripts/ops/autoencoder/benchmark_structured_source_384.py")


@pytest.mark.parametrize("domain", panel.DOMAINS)
def test_development_splits_keep_polarities_and_wordings_together(domain):
    train, tuning = [panel.rows(domain, part) for part in ("train", "validation")]
    assert len(train) == 180 and len(tuning) == 60
    for key in ("id", "group_id", "source_sha256"):
        assert not {row[key] for row in train} & {row[key] for row in tuning}
    for rows in (train, tuning):
        groups = {row["group_id"] for row in rows}
        for group in groups:
            block = [row for row in rows if row["group_id"] == group]
            assert len(block) == 12
            assert {row["wording_style"] for row in block} == {0, 1}
        assert all(row["source_semantics_verified"] is False and row["proof_authority"] is False for row in rows)


@pytest.mark.parametrize("domain", panel.DOMAINS)
def test_exposed_panel_holds_out_compositions_without_unknown_scalar_labels(domain):
    # Added after candidate freeze and the one-time evaluation. Future campaigns
    # must use new groups: this regression panel is now deliberately exposed.
    from ipfs_datasets_py.logic.formalization.autoencoder.source_training_v2 import _leaves
    train, tune, test, canary = [panel.rows(domain, part)
                               for part in ("train", "validation", "test", "canary")]
    groups = [{row["group_id"] for row in rows} for rows in (train, tune, test)]
    assert all(not a & b for i, a in enumerate(groups) for b in groups[i + 1:])
    assert {row["group_id"] for row in canary} == groups[2]
    targets = [{json.dumps(row["target"], sort_keys=True) for row in rows} for rows in (train, tune, test)]
    assert all(not a & b for i, a in enumerate(targets) for b in targets[i + 1:])
    vocabulary = {}
    for row in train:
        for path, value in _leaves(row["target"]).items():
            vocabulary.setdefault(path, set()).add(json.dumps(value, sort_keys=True))
    for row in tune + test + canary:
        assert all(json.dumps(value, sort_keys=True) in vocabulary[path]
                   for path, value in _leaves(row["target"]).items())


def test_inference_timing_strips_targets_and_metadata():
    calls = []

    class Runtime:
        def __init__(self, checkpoint):
            assert checkpoint == {"test": "checkpoint"}

        def infer(self, rows):
            assert all(set(row) == {"id", "source_text", "embedding"} for row in rows)
            calls.append(rows)

    result = driver.timed_inference(SimpleNamespace(Runtime=Runtime), {"test": "checkpoint"},
        [{"id": "x", "source_text": "example", "embedding": [0.0] * 384,
          "target": {"secret": "answer"}, "reference_metadata": {"also": "forbidden"}}], 3)
    assert len(calls) == 4  # One warmup, then three measured calls.
    assert result["count"] == 1
    assert result["includes_embedding"] is False
    assert result["includes_loading"] is False


def test_baseline_guard_checks_hash_before_models_or_holdouts(tmp_path, monkeypatch):
    (tmp_path / "freeze.json").write_text("{}")
    monkeypatch.setattr(driver.base, "guard_preparation", lambda _: {})
    with pytest.raises(ValueError, match="freeze SHA differs"):
        driver.guard_baseline(tmp_path, "0" * 64)


def test_baseline_guard_rejects_mutated_artifacts(tmp_path, monkeypatch):
    driver.base.save(tmp_path / "freeze.json", {"fit.json": "0" * 64})
    (tmp_path / "fit.json").write_text("tampered")
    monkeypatch.setattr(driver.base, "guard_preparation", lambda _: {})
    with pytest.raises(ValueError, match="artifact changed"):
        driver.guard_baseline(tmp_path, driver.base.sha(tmp_path / "freeze.json"))
