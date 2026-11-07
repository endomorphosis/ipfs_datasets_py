"""total_docs invariant: write_metadata sets total_docs = rows actually written (res["rows"], post-write parquet
row count) on a first write AND on an incremental rewrite that shrinks or grows the place; never the old value.

Run: ~/.ipfs_datasets/world_law/pipeline/venv/bin/python ~/.ipfs_datasets/world_law/pipeline/tests/test_total_docs.py
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, shutil, sys, tempfile
from pathlib import Path
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import run_loop as RL  # noqa: E402
import schema as S  # noqa: E402


def _res(n):
    return {"rows": n, "written": [(S.html_path("DE", "wd_Q10408"), None)],
            "first": {"place_id": "wd:Q10408", "gnis": None, "source_platform": "x"},
            "place": {"place_name": "T"}, "doc_stats": {"docs": n}}


def test_total_docs_follows_rows_on_rewrite():
    tmp = Path(tempfile.mkdtemp())
    try:
        for n in (41, 357, 347, 5):  # first write, growth, shrink, big shrink
            _, _, m = RL.write_metadata(tmp, "DE", "wd_Q10408", _res(n), 1)
            disk = json.loads((tmp / S.metadata_path("DE", "wd_Q10408")).read_text())
            assert m["total_docs"] == disk["total_docs"] == disk["doc_stats"]["docs"] == n, (n, disk)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_total_docs_follows_rows_on_rewrite(); print("ok"); print("ALL TOTAL-DOCS TESTS PASSED")
