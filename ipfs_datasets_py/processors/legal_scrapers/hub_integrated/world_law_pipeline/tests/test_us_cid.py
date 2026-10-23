"""US CIDs must be byte-identical between the ORIGINAL hub code and the world copy.

Run: /workspace/hf-venv/bin/python -m pytest -q /workspace/world_law/pipeline/tests
(or plain: /workspace/hf-venv/bin/python tests/test_us_cid.py)
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import glob
import importlib.util
import sys as _sys
_sys.dont_write_bytecode = True  # never write into the original repo
import sys
from pathlib import Path

PIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPE))
ORIG = Path("/workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers/"
            "municipal_law_database_scrapers/hub")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


orig_pw = _load("orig_parquet_writer", ORIG / "parquet_writer.py")   # read-only import
orig_common = _load("orig_common", ORIG / "common.py")
from world import parquet_writer as new_pw, common as new_common  # noqa: E402
import schema  # noqa: E402

US_ROWS = [
    {"gnis": "1008538", "place_id": "gnis:1008538", "country_code": "US"},
    {"gnis": "2410877", "place_id": "gnis:2410877", "country_code": "US"},
    {"gnis": "428803"},                                   # legacy todo row: no place_id/country
    {"gnis": "2395220", "place_id": "", "country_code": "US"},
]
DOC_IDS = ["PTIIICOOR_CH1GEPR_S1-1", "12345", "0", "Ä/ü §1", "doc with spaces"]


def test_us_cid_identical_to_original():
    n = 0
    for row in US_ROWS:
        g = row["gnis"]
        for pk in (new_common.place_key(row), schema.place_key(row.get("place_id"), g, row.get("country_code"))):
            assert pk == g
            for d in DOC_IDS:
                want = orig_pw.html_cid(g, d)
                assert want == orig_common.law_cid(g, d)
                assert new_pw.html_cid(pk, d) == want
                assert new_common.law_cid(pk, d) == want
                assert schema.html_cid(pk, d) == want
                n += 1
    return n


def test_docs_to_html_rows_identical():
    docs = [{"Id": "A1", "Title": "Sec. 1-1. Title", "Content": "<p>x</p>", "DocOrderId": 2},
            {"Id": "B2", "TitleHtml": "<b>Ch 2</b>", "Content": "", "DocOrderId": 1}]
    a = orig_pw.docs_to_html_rows(docs, "1008538")
    b = new_pw.docs_to_html_rows(docs, new_common.place_key({"place_id": "gnis:1008538"}))
    assert a == b


def test_against_published_hub_files():
    """Recompute cid for rows of real american_municipal_law parquets on disk."""
    import pyarrow.parquet as pq
    files = sorted(glob.glob("/workspace/municipal_law/_verify_tmp/american_law/data/*_html.parquet"))[:5]
    checked = 0
    for f in files:
        g = Path(f).name.replace("_html.parquet", "")
        t = pq.read_table(f, columns=["cid", "doc_id"]).to_pylist()
        pk = schema.place_key(f"gnis:{g}")
        for r in t:
            assert schema.html_cid(pk, str(r["doc_id"])) == r["cid"], (f, r)
            checked += 1
    return len(files), checked


def test_non_us_keys():
    assert new_common.place_key({"place_id": "wd:Q90", "country_code": "FR"}) == "wd_Q90"
    assert schema.place_key("iso:US-CA") == "iso_US-CA"
    assert schema.html_cid("wd_Q90", "x") == orig_pw.cid_v1_raw_sha256("wd_Q90_x.json")


def test_us_metadata_unchanged(tmp_path=None):
    import json, tempfile
    d = Path(tmp_path or tempfile.mkdtemp())
    orig_pw.write_metadata(d / "a.json", "City X", "CA", 5, 123)
    new_pw.write_metadata(d / "b.json", "City X", "CA", 5, 123)
    assert (d / "a.json").read_bytes() == (d / "b.json").read_bytes()
    new_pw.write_metadata(d / "c.json", "Paris", None, 5, 123, country_code="FR",
                          iso_3166_2="FR-75", admin_level="municipality")
    m = json.loads((d / "c.json").read_text())
    assert "state_code" not in m and m["country_code"] == "FR" and m["admin_level"] == "municipality"


if __name__ == "__main__":
    print("cid comparisons:", test_us_cid_identical_to_original())
    test_docs_to_html_rows_identical()
    print("published files/rows verified:", test_against_published_hub_files())
    test_non_us_keys()
    test_us_metadata_unchanged()
    print("ALL US CID TESTS PASSED")
