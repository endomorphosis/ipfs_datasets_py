"""total_docs invariant: write_metadata sets total_docs = rows actually written (res["rows"], post-write parquet
row count) on a first write AND on an incremental rewrite that shrinks or grows the place; never the old value.

Run: /workspace/world_law/pipeline/venv/bin/python /workspace/world_law/pipeline/tests/test_total_docs.py
"""
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
