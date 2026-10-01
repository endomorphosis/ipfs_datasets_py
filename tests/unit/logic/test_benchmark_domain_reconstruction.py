"""The heldout phase requires the complete frozen experiment, including heads."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("benchmark_domain_reconstruction", ROOT / "scripts/ops/autoencoder/benchmark_domain_reconstruction.py")
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


def _freeze(tmp_path, fits):
    api._write(tmp_path / "fits.json", fits)
    raw = (tmp_path / "fits.json").read_bytes()
    api._write(tmp_path / "freeze.json", {"files": {"fits.json": api._sha(raw)}})
    return api._sha((tmp_path / "freeze.json").read_bytes())


def test_explicit_freeze_identity_required_before_any_model_load(tmp_path, monkeypatch):
    sha = _freeze(tmp_path, [])
    monkeypatch.setattr(api, "_backend", lambda *a: pytest.fail("loaded head before freeze validation"))
    with pytest.raises(ValueError, match="explicit matching"):
        api.frozen_fits(tmp_path, None)
    with pytest.raises(ValueError, match="explicit matching"):
        api.frozen_fits(tmp_path, "0" * 64)
    with pytest.raises(ValueError, match="all predeclared"):
        api.frozen_fits(tmp_path, sha)


def test_tampered_artifacts_reject_before_native_target_preparation(tmp_path, monkeypatch):
    sha = _freeze(tmp_path, [])
    with (tmp_path / "fits.json").open("ab") as stream:
        stream.write(b" ")
    monkeypatch.setattr(api, "_guard", lambda directory: {})
    monkeypatch.setattr(api.panel, "prepare_partition", lambda *a: pytest.fail("exposed heldout after corruption"))
    with pytest.raises(ValueError, match="frozen artifact changed"):
        api.evaluate(tmp_path, sha)
    assert not (tmp_path / "evaluation-started").exists()


def test_every_checkpoint_loaded_before_any_heldout_is_generated(tmp_path, monkeypatch):
    arms = [(domain, backend, seed) for domain in api.panel.DOMAINS
            for backend in ("reference", "prepared") for seed in api.SEEDS]
    fits = [{"domain_id": domain, "backend": backend, "seed": seed, "descriptor": {"index": index},
             "report": {"settings": {"seed": seed}}, "parameters_sha256": api.panel.digest([])}
            for index, (domain, backend, seed) in enumerate(arms)]
    sha = _freeze(tmp_path, fits)
    loaded = []
    class Backend:
        @staticmethod
        def _read(descriptor):
            loaded.append(descriptor["index"])
            if len(loaded) == len(fits):
                raise ValueError("last checkpoint has stale provenance")
            row = fits[descriptor["index"]]
            return {"space": {"domain_id": row["domain_id"]}, "report": row["report"], "parameters": []}, []
    monkeypatch.setattr(api, "_guard", lambda directory: {})
    monkeypatch.setattr(api, "_backend", lambda name: (Backend, None, None))
    monkeypatch.setattr(api.panel, "prepare_partition", lambda *a: pytest.fail("opened heldout before checking all heads"))
    with pytest.raises(ValueError, match="last checkpoint"):
        api.evaluate(tmp_path, sha)
    assert loaded == list(range(len(fits)))
    assert not (tmp_path / "evaluation-started").exists()


def test_duplicate_arm_cannot_satisfy_complete_freeze_barrier(tmp_path, monkeypatch):
    fits = [{"domain_id": "intent_ir", "backend": "reference", "seed": 1729}] * 24
    sha = _freeze(tmp_path, fits)
    monkeypatch.setattr(api, "_backend", lambda *a: pytest.fail("duplicates reached model loading"))
    with pytest.raises(ValueError, match="all predeclared"):
        api.frozen_fits(tmp_path, sha)


def test_repeat_evaluation_cannot_overwrite_exposed_holdouts(tmp_path, monkeypatch):
    (tmp_path / "evaluation-started").write_text("already exposed")
    monkeypatch.setattr(api, "_guard", lambda directory: {})
    monkeypatch.setattr(api, "frozen_fits", lambda *args: [])
    monkeypatch.setattr(api.panel, "prepare_partition", lambda *a: pytest.fail("reopened holdout"))
    with pytest.raises(FileExistsError):
        api.evaluate(tmp_path, "previous-freeze")
