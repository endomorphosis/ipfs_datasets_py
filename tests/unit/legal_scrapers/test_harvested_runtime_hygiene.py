"""run_harvested_collector finds package collectors and isolates helper modules per run."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from ipfs_datasets_py.processors.legal_scrapers.international.catalog import get_snapshot_corpus
from ipfs_datasets_py.processors.legal_scrapers.international.runtime import (
    PACKAGE_HARVESTED_ROOT,
    SIBLING_HELPER_MODULES,
    collector_path_for,
    run_harvested_collector,
)
from ipfs_datasets_py.processors.legal_scrapers.user_data_paths import is_inside_package

_FAKE_COLLECTOR = '''
import json, os
from pathlib import Path
import common
import world_lib

def main():
    out = Path(os.environ["IPFS_DATASETS_LEGAL_CORPORA_ROOT"]) / "probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "common_file": common.__file__,
        "has_map_parallel": hasattr(common, "map_parallel"),
        "world_lib_common_is_common": world_lib.http_get is common.http_get,
        "robots_guard_env": os.environ.get("IPFS_DATASETS_LEGAL_ROBOTS_GUARD"),
    }))
'''


def test_empty_collectors_root_falls_back_to_package_copy(tmp_path: Path) -> None:
    entry = get_snapshot_corpus("germany")
    path = collector_path_for(entry, dest_root=tmp_path / "empty")
    assert path.is_file()
    assert path.is_relative_to(PACKAGE_HARVESTED_ROOT)


def test_harvested_copy_in_collectors_root_wins(tmp_path: Path) -> None:
    entry = get_snapshot_corpus("germany")
    local = tmp_path / "collectors" / "shared" / entry.collector
    local.parent.mkdir(parents=True)
    local.write_text("# harvested copy\n", encoding="utf-8")
    assert collector_path_for(entry, dest_root=tmp_path / "collectors") == local.resolve()


def test_dry_run_with_empty_collectors_dir_reports_existing_package_collector(tmp_path: Path) -> None:
    result = run_harvested_collector(
        "germany",
        output_dir=tmp_path / "corpora",
        collectors_dir=tmp_path / "collectors",
        dry_run=True,
        sync_huggingface=False,
    )
    assert result.status == "dry_run"
    assert result.details["exists"] is True
    assert not is_inside_package(result.output_dir)


def test_run_isolates_sibling_helper_modules(tmp_path: Path, monkeypatch) -> None:
    entry = get_snapshot_corpus("germany")
    collectors = tmp_path / "collectors"
    fake = collectors / "shared" / entry.collector
    fake.parent.mkdir(parents=True)
    fake.write_text(_FAKE_COLLECTOR, encoding="utf-8")
    sentinel = types.ModuleType("common")
    monkeypatch.setitem(sys.modules, "common", sentinel)
    for name in SIBLING_HELPER_MODULES:
        if name != "common":
            monkeypatch.delitem(sys.modules, name, raising=False)
    path_before = list(sys.path)

    result = run_harvested_collector(
        "germany",
        output_dir=tmp_path / "corpora",
        collectors_dir=collectors,
        sync_huggingface=False,
    )

    assert result.status == "ok", result.error
    probe = json.loads((tmp_path / "corpora" / "probe.json").read_text(encoding="utf-8"))
    # The collector saw the canonical shared helper, not the stale module from sys.modules.
    assert probe["common_file"].endswith("national_collectors/common.py")
    assert probe["has_map_parallel"] is True
    assert probe["world_lib_common_is_common"] is True
    assert probe["robots_guard_env"] == "0"
    # The previous module is restored and nothing from the run leaks.
    assert sys.modules["common"] is sentinel
    for name in SIBLING_HELPER_MODULES:
        if name != "common":
            assert name not in sys.modules, name
    assert sys.path == path_before
