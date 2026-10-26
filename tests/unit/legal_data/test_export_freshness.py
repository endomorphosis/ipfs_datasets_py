"""Raw scrape SHA versus the normalized justicedao export. No network."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_data.query_legal_records import query_legal_records
from ipfs_datasets_py.processors.legal_scrapers.world_law.export_norm import export_norm
from ipfs_datasets_py.processors.legal_scrapers.world_law.freshness import (
    export_freshness,
    freshness_from_manifest,
)

_RAW = "a" * 40
_NEWER = "b" * 40


def test_matching_raw_sha_is_current() -> None:
    decision = export_freshness(raw_revision=_RAW, exported_source_revision=_RAW.upper())
    assert decision["status"] == "current"
    assert decision["renormalize"] is False
    assert decision["raw_org"] == "endomorphosis"
    assert decision["retrieve_from"] == "justicedao"
    assert decision["raw_revision"] == _RAW
    assert decision["exported_source_revision"] == _RAW


def test_new_raw_sha_is_stale_and_a_missing_export_renormalizes() -> None:
    stale = export_freshness(raw_revision=_NEWER, exported_source_revision=_RAW)
    assert stale["status"] == "stale"
    assert stale["renormalize"] is True
    missing = export_freshness(raw_revision=_RAW, exported_source_revision=None)
    assert missing["status"] == "missing"
    assert missing["renormalize"] is True
    unproven = export_freshness(raw_revision=None, exported_source_revision=None)
    assert unproven["status"] == "unproven"
    assert unproven["renormalize"] is False
    short = export_freshness(raw_revision="abc", exported_source_revision=_RAW)
    assert short["status"] == "unproven"
    assert short["renormalize"] is False


def test_manifest_records_the_raw_sha_the_export_was_built_from(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    rows = source / "data"
    rows.mkdir()
    pq.write_table(
        pa.table(
            {
                "cid": ["keep"],
                "country_code": ["FR"],
                "doc_type": ["statute"],
                "title_native": ["Code"],
                "text": ["Les lois"],
                "content_complete": [True],
                "source_official": [True],
            }
        ),
        rows / "iso_FR_html.parquet",
    )
    export_norm(
        source,
        tmp_path / "out",
        family="world-national",
        source_dataset="endomorphosis/world_national_law",
        source_revision=_RAW,
    )
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    current = freshness_from_manifest(manifest, _RAW)
    assert current["status"] == "current"
    assert current["renormalize"] is False
    moved = freshness_from_manifest(manifest, _NEWER)
    assert moved["status"] == "stale"
    assert moved["renormalize"] is True
    older = {"dataset_revision": _RAW, "source": {"source_revision": _NEWER}}
    assert freshness_from_manifest(older, _RAW)["status"] == "current"


def test_query_retrieves_justicedao_and_does_not_name_the_raw_org() -> None:
    module = Path(inspect.getsourcefile(query_legal_records) or "").read_text(encoding="utf-8")
    assert "endomorphosis" not in module
    assert "justicedao/" in module
