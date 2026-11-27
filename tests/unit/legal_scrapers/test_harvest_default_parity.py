"""Offline parity checks for harvest defaults, the CC offline index list and runtime __file__."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_scrapers.international import api, harvest
from ipfs_datasets_py.processors.legal_scrapers.international.catalog import get_snapshot_corpus
from ipfs_datasets_py.processors.legal_scrapers.international.runtime import (
    PACKAGE_HARVESTED_ROOT,
    run_harvested_collector,
)


def _forbid_network_harvest(monkeypatch, calls):
    def _record(name):
        def _fn(*args, **kwargs):
            calls.append((name, args, kwargs))
            return harvest.HarvestResult(collectors_root=str(kwargs.get("dest_root")), corpora_root="")
        return _fn

    monkeypatch.setattr(api, "harvest_dataset_collectors", _record("dataset"))
    monkeypatch.setattr(api, "harvest_legal_scrapers_repo", _record("legal_scrapers"))
    monkeypatch.setattr(harvest, "harvest_dataset_collectors", _record("dataset"))


def test_default_harvest_counts_package_collectors_as_present(tmp_path, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(tmp_path / "collectors"))
    calls: list = []
    _forbid_network_harvest(monkeypatch, calls)
    payload = api.harvest_legal_collectors()
    assert payload["missing_collectors"] == []
    assert calls == []


def test_explicit_dest_root_still_reports_and_harvests_what_it_lacks(tmp_path, monkeypatch):
    calls: list = []
    _forbid_network_harvest(monkeypatch, calls)
    payload = api.harvest_legal_collectors(dest_root=tmp_path / "empty", limit=2)
    assert payload["missing_collectors"], "an empty explicit destination lacks every catalog collector"
    assert any(name == "dataset" for name, _, _ in calls)


def test_missing_catalog_collectors_fallback_roots():
    assert harvest.missing_catalog_collectors(dest_root=Path("/nonexistent-collectors"), fallback_roots=(PACKAGE_HARVESTED_ROOT,)) == []
    assert harvest.missing_catalog_collectors(dest_root=Path("/nonexistent-collectors"))


def test_cc_offline_indexes_include_2025_18(monkeypatch):
    sys.path.insert(0, str(Path(harvest.__file__).resolve().parents[1] / "national_collectors"))
    try:
        import archive_fallbacks as af
    finally:
        sys.path.pop(0)

    class _Boom:
        def get(self, *a, **k):
            raise OSError("offline")

    monkeypatch.setattr(af, "session", lambda: _Boom())
    monkeypatch.setattr(af, "_cc_indexes", None)
    indexes = af.cc_indexes(10)
    assert any("CC-MAIN-2025-18" in item for item in indexes)
    assert indexes == list(af.CC_OFFLINE_INDEXES)


def test_runtime_sets_collector_file(tmp_path):
    entry = get_snapshot_corpus("germany")
    fake = tmp_path / "collectors" / "shared" / entry.collector
    fake.parent.mkdir(parents=True)
    fake.write_text(
        "import json, os\nfrom pathlib import Path\n"
        "HERE = Path(__file__).resolve().parent\n"
        "def main():\n"
        "    out = Path(os.environ['IPFS_DATASETS_LEGAL_CORPORA_ROOT']) / 'file.json'\n"
        "    out.parent.mkdir(parents=True, exist_ok=True)\n"
        "    out.write_text(json.dumps({'here': str(HERE)}))\n",
        encoding="utf-8",
    )
    result = run_harvested_collector(
        "germany", output_dir=tmp_path / "corpora", collectors_dir=tmp_path / "collectors", sync_huggingface=False
    )
    assert result.status == "ok", result.error
    data = json.loads((tmp_path / "corpora" / "file.json").read_text())
    assert data["here"] == str(fake.parent.resolve())
