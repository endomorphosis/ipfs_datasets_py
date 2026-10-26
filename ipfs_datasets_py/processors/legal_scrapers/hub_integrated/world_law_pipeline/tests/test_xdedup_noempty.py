"""No-empty rule (2026-10-20): dedup (old_repo / cross_place, skip / pointer) never leaves a place with zero
full rows; such a place keeps all its rows in full, unmodified.  Synthetic data in /tmp, dry-run only.

Run: /workspace/hf-venv/bin/python /workspace/world_law/pipeline/tests/test_xdedup_noempty.py
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
import pyarrow.parquet as pq  # noqa: E402
import dedup_index as DX  # noqa: E402
import xdedup as XD  # noqa: E402
import schema as S  # noqa: E402
from test_hold_policy import _tmp, base, run, w  # noqa: E402
from test_xdedup import TXT, _db  # noqa: E402


def _rows(scratch, cc):
    return {r["doc_id"]: r for p in (scratch / "out" / S.ROOT / "data" / cc).rglob("*_html.parquet")
            for r in pq.read_table(p).to_pylist()}


def _full(r):
    return bool(r["text"]) and "duplicate_pointer" not in (r["source_policy"] or "")


def test_would_empty_helper():
    assert XD.would_empty(0, 3) and not XD.would_empty(1, 3) and not XD.would_empty(0, 0)
    assert XD.strips_content("pointer") and XD.strips_content("skip") and not XD.strips_content("tag")


def _case(cfg):
    tmp = _tmp()
    old_dir = DX.STATE_DIR
    try:
        d = _db(tmp, old=[("https://old.example/a", "endomorphosis/ipfs_germany_municipal_laws"),
                          ("https://old.example/b", "endomorphosis/ipfs_germany_municipal_laws"),
                          ("https://old.example/c", "endomorphosis/ipfs_germany_municipal_laws")])
        DX.STATE_DIR = d
        (d / "config.json").write_text(json.dumps(cfg))
        mk = lambda did, pid, **kw: base(did, place_id=pid, country_code="DE", language="de", **kw)  # noqa: E731
        # wd_Q30: every row is an old-repo duplicate -> would be emptied -> kept in full
        w(tmp / "staging/web/DE/wd_Q30.jsonl", [mk("e1", "wd:Q30", source_url="https://old.example/a"),
                                                 mk("e2", "wd:Q30", source_url="https://old.example/b")])
        # wd_Q31: one dup + one unique row -> the dup is handled normally
        w(tmp / "staging/web/DE/wd_Q31.jsonl", [mk("m1", "wd:Q31", source_url="https://old.example/c"),
                                                 mk("m2", "wd:Q31", source_url="https://unique.example/x")])
        # cross-place: wd_Q11 (Amt) is canonical; wd_Q10 only has the duplicate -> kept in full
        w(tmp / "staging/web/DE/wd_Q11.jsonl", [mk("a1", "wd:Q11", place_name="Amt Musterland", text=TXT, html=None,
                                                    source_url="https://amt.example/s")])
        w(tmp / "staging/web/DE/wd_Q10.jsonl", [mk("g1", "wd:Q10", place_name="Musterdorf", text=TXT, html=None,
                                                    source_url="https://gemeinde.example/s")])
        scratch, summ = run(tmp, **{"national-repo": "test/nat"})
        rows = _rows(scratch, "DE")
        return rows, summ, tmp
    finally:
        DX.STATE_DIR = old_dir


def test_old_repo_skip_never_empties_place():
    rows, summ, tmp = _case({"old_repo": "skip", "cross_place": "pointer"})
    try:
        assert _full(rows["e1"]) and _full(rows["e2"]), "place wd_Q30 must keep its rows in full"
        assert "duplicate_of" not in (rows["e1"]["extra_metadata"] or "")
        assert "m1" not in rows and _full(rows["m2"]), "non-emptying dup is still skipped"
        assert _full(rows["g1"]) and _full(rows["a1"]), "cross-place-only place kept in full"
        assert summ.get("xdedup_places_kept_would_be_emptied") == 2, summ
        assert summ.get("xdedup_rows_kept_would_be_emptied") == 3, summ
        assert summ.get("xdedup_old_repo_skip") == 1 and summ.get("xdedup_rows_skipped") == 1, summ
        modes = [json.loads(l)["mode"] for p in tmp.rglob("*.pointers.jsonl") for l in p.read_text().splitlines()]
        assert modes.count("kept_place_would_be_emptied") == 3 and modes.count("skip") == 1, modes
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_pointer_mode_never_empties_place():
    rows, summ, tmp = _case({"old_repo": "pointer", "cross_place": "pointer"})
    try:
        assert _full(rows["e1"]) and _full(rows["e2"]) and _full(rows["g1"])
        assert rows["m1"]["text"] is None and "duplicate_pointer" in rows["m1"]["source_policy"]
        assert summ.get("xdedup_places_kept_would_be_emptied") == 2, summ
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_existing_published_row_counts():
    """A place whose only NEW row is a dup but that already has a published full row is not emptied:
    the dup is skipped normally and the published row stays."""
    tmp = _tmp()
    old_dir = DX.STATE_DIR
    try:
        d = _db(tmp, old=[("https://old.example/2", "endomorphosis/ipfs_japan_municipal_laws")])
        DX.STATE_DIR = d
        (d / "config.json").write_text(json.dumps({"old_repo": "skip", "cross_place": "pointer"}))
        w(tmp / "staging/web/JP/wd_Q1490.jsonl", [base("e1", source_url="https://example.jp/e1")])
        run(tmp, **{"national-repo": "test/nat"})
        sc = sorted((tmp / "state").glob("dryrun_*"))[-1]
        tmp2 = tmp / "second"
        shutil.copytree(sc / "out", tmp2 / "out")
        w(tmp2 / "staging/web/JP/wd_Q1490.20261020T000000Zp0001.jsonl", [base("e2", source_url="https://old.example/2")])
        scratch, summ = run(tmp2, **{"national-repo": "test/nat"})
        rows = _rows(scratch, "JP")
        assert _full(rows["e1"]) and "e2" not in rows, rows.keys()
        assert not summ.get("xdedup_places_kept_would_be_emptied"), summ
        # and with only the dup staged into a fresh place it is kept
        tmp3 = tmp / "third"
        w(tmp3 / "staging/web/JP/wd_Q1490.jsonl", [base("e2", source_url="https://old.example/2")])
        scratch3, summ3 = run(tmp3, **{"national-repo": "test/nat"})
        assert _full(_rows(scratch3, "JP")["e2"]) and summ3.get("xdedup_places_kept_would_be_emptied") == 1
    finally:
        DX.STATE_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
