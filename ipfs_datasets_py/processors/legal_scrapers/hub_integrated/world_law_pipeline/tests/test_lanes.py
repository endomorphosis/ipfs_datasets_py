"""New lanes (states, ukie) and id_jdih are discovered, built and routed like every other lane; prune/compress
lane lists include them (synthetic data in /tmp only; --dry-run, --no-hub-listing, dummy repos).

Run: /workspace/hf-venv/bin/python /workspace/world_law/pipeline/tests/test_lanes.py
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "tools"))
import pyarrow.parquet as pq  # noqa: E402
import schema as S  # noqa: E402
import run_loop  # noqa: E402
from test_hold_policy import _tmp, base, run, w  # noqa: E402
S.BUCKETED_COUNTRIES = frozenset()  # flat layout for this test

NEW_LANES = ("states", "ukie", "id_jdih")


def _stage(tmp):
    w(tmp / "staging/states/CA/iso_CA-ON.20261017T220000Zp0001.jsonl",
      [base("s1", place_id="iso:CA-ON", country_code="CA", doc_type="statute", language="en")])
    w(tmp / "staging/states/AU/iso_AU-QLD.20261017T220000Zp0001.jsonl",
      [base("s2", place_id="iso:AU-QLD", country_code="AU", doc_type="statute", language="en")])
    w(tmp / "staging/ukie/GB/wd_Q84.20261017T220000Zp0001.jsonl",
      [base("u1", place_id="wd:Q84", country_code="GB", language="en")])
    w(tmp / "staging/ukie/IE/wd_Q1761.20261017T220000Zp0001.jsonl",
      [base("u2", place_id="wd:Q1761", country_code="IE", language="en")])
    w(tmp / "staging/id_jdih/ID/wd_Q3630.20261017T220000Zp0001.jsonl",
      [base("j1", place_id="wd:Q3630", country_code="ID", language="id")])
    (tmp / "staging/ukie/_state").mkdir(parents=True, exist_ok=True)  # lane-private dirs are ignored
    (tmp / "staging/ukie/_state/progress.json").write_text("{}")


def test_discover_new_lanes():
    tmp = _tmp()
    try:
        _stage(tmp)
        found = run_loop.discover(tmp / "staging", 0, None)
        assert not any(f["bad_name"] for f in found)
        assert {f["bot"] for f in found} == set(NEW_LANES)
        assert {(f["bot"], f["cc"]) for f in found} == {("states", "CA"), ("states", "AU"), ("ukie", "GB"),
                                                        ("ukie", "IE"), ("id_jdih", "ID")}
        only = run_loop.discover(tmp / "staging", 0, ["ukie"])
        assert {f["bot"] for f in only} == {"ukie"} and len(only) == 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_new_lanes_build_and_route():
    tmp = _tmp()
    try:
        _stage(tmp)
        scratch, summ = run(tmp, **{"repo": "test/muni", "national-repo": "test/nat"})
        mun, nat = scratch / "out" / S.ROOT, scratch / "out_national" / S.ROOT
        assert sorted(p.name for p in (nat / "data").glob("*/*.parquet")) == ["iso_AU-QLD_html.parquet",
                                                                              "iso_CA-ON_html.parquet"]
        assert sorted(p.name for p in (mun / "data").glob("*/*.parquet")) == ["wd_Q1761_html.parquet",
                                                                              "wd_Q3630_html.parquet",
                                                                              "wd_Q84_html.parquet"]
        assert sorted(pq.read_table(str(mun / "places.parquet")).column("country_code").to_pylist()) == ["GB", "ID", "IE"]
        assert summ["places_written_by_repo"] == {"test/muni": 3, "test/nat": 2}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_lane_lists_include_new_lanes():
    import prune_processed as PP
    for b in NEW_LANES:
        assert b in PP.DEFAULT_BOTS
    cfg = json.loads((Path(PP.BASE) / "state" / "prune_config.json").read_text())  # read-only
    for b in NEW_LANES + ("eu", "national", "web", "asia_latam", "afme", "sasia_ru", "eap", "ph", "ocr"):
        assert b in cfg["bots"], b
    src = (HERE.parent / "tools" / "compress_processed.py").read_text()
    assert '"id_jdih", "states", "ukie"]' in src


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
