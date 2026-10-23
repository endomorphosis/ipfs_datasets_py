"""US pointer rows: building, daily caching, failure keeps the cache, schema round-trip (mocked Hub)."""
import json, shutil, sys, tempfile, time
from pathlib import Path
from types import SimpleNamespace
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import pyarrow as pa  # noqa: E402
import schema as S  # noqa: E402
import us_pointers as U  # noqa: E402


def test_build_rows_dedup_and_levels():
    files = {"american_law/data/1_html.parquet": {"rows": 10}, "american_law/data_3/1_html.parquet": {"rows": 12},
             "2_html.parquet": {"rows": 5}}
    meta = {"american_law/metadata/1.json": {"place_name": "Nash County", "state_code": "NC", "last_updated": 5},
            "metadata/2.json": {"place_name": "Borough of Dauphin", "state_code": "PA", "last_updated": 7}}
    rows = U.build_rows(files, meta)
    assert [r["place_id"] for r in rows] == ["gnis:1", "gnis:2"]
    r1 = rows[0]
    assert r1["html_path"] == "american_law/data_3/1_html.parquet" and r1["total_docs"] == 12
    assert r1["source_paths"] == ["american_law/data/1_html.parquet", "american_law/data_3/1_html.parquet"] and r1["has_local_data"] is False
    assert r1["admin_level"] == "county" and r1["iso_3166_2"] == "US-NC" and rows[1]["admin_level"] == "municipality"
    t = pa.Table.from_pylist(rows, schema=S.places_schema())
    assert t.num_rows == 2 and t.column("source_paths").type == pa.list_(pa.string())


def test_refresh_cached_daily_and_failure_keeps_cache():
    tmp = Path(tempfile.mkdtemp())
    try:
        cp = tmp / "us_pointers.json"
        cp.write_text(json.dumps({"built_ts": time.time() - 3600, "rows": [{"place_id": "gnis:9"}]}))
        class Boom:
            def dataset_info(self, *a, **k): raise RuntimeError("no network")
        assert U.refresh(cp, api=Boom())["rows"] == [{"place_id": "gnis:9"}]          # fresh: no Hub call
        cp.write_text(json.dumps({"built_ts": time.time() - 2 * 86400, "rows": [{"place_id": "gnis:9"}]}))
        assert U.refresh(cp, api=Boom())["rows"] == [{"place_id": "gnis:9"}]          # stale + failure: kept
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("ALL US POINTER TESTS PASSED")
