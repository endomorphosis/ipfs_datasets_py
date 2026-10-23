"""Staging race: a lane moves/removes a staged file between run_loop's discovery and its read / copy / move.
run_loop must log a warning and skip that file for this run (never crash, never publish a place empty because a
vanished full snapshot was 'read' as zero rows). Synthetic data in /tmp only; Hub commit is stubbed.

Run: /workspace/hf-venv/bin/python /workspace/world_law/pipeline/tests/test_staged_vanish.py
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json
import os
import pathlib
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import schema as S  # noqa: E402
import run_loop as RL  # noqa: E402
from test_hold_policy import _tmp, base, w  # noqa: E402
S.BUCKETED_COUNTRIES = frozenset()


def _argv(tmp, *extra):
    return ["--once", "--no-hub-listing", "--no-prune", "--min-age", "0", "--repo", "test/muni",
            "--national-repo", "test/nat", "--staging", str(tmp / "staging"), "--out", str(tmp / "out"),
            "--state", str(tmp / "state"), "--processed", str(tmp / "processed"),
            "--quarantine", str(tmp / "quarantine"), "--held", str(tmp / "held"),
            "--overrides", str(tmp / "overrides.json"), *extra]


def _last_summary(tmp):
    return json.loads((tmp / "state" / "runs.jsonl").read_text().splitlines()[-1])


class _Patch:
    def __init__(self, obj, name, new):
        self.obj, self.name, self.new = obj, name, new

    def __enter__(self):
        self.old = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.new)

    def __exit__(self, *a):
        setattr(self.obj, self.name, self.old)
        RL._LOCK["f"] = None


def _stub_commit(kind, R, args, api, scratch, run_id, stats, dry, bookkeep=None):
    bookkeep({(cc, k) for cc, k in R["places_written"]} | set(R.get("places_noop") or ()), ["stubcommit"])
    return True, ["stubcommit"]


def test_move_unique_missing_src():
    tmp = _tmp()
    try:
        assert RL.move_unique(tmp / "staging/x/FR/gone.jsonl", tmp / "dst") is None
        assert not any((tmp / "dst").iterdir())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_discover_skips_file_vanishing_before_stat():
    tmp = _tmp()
    try:
        a = tmp / "staging/eu/FR/wd_Q90.20261011T010000Zp0001.jsonl"
        b = tmp / "staging/eu/FR/wd_Q91.20261011T010000Zp0001.jsonl"
        w(a, [base("a1", place_id="wd:Q90", country_code="FR")])
        w(b, [base("b1", place_id="wd:Q91", country_code="FR")])
        orig_stat = pathlib.Path.stat

        def stat(self, *k, **kw):
            if self.name == b.name and os.path.exists(b) and kw == {} and not k:
                os.unlink(b)  # the lane removes it right before discover() stats it
            return orig_stat(self, *k, **kw)
        orig_is_file = pathlib.Path.is_file
        with _Patch(pathlib.Path, "is_file", lambda self, *k, **kw: True if self == b else orig_is_file(self, *k, **kw)), \
                _Patch(pathlib.Path, "stat", stat):
            found = RL.discover(tmp / "staging", 0, None)
        assert [f["path"].name for f in found] == [a.name], found
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_run_survives_vanish_before_hash_read_and_move():
    """Four races in one real (non-dry) run: one file vanishes before hashing, one before build_place reads it,
    one bad-named file vanishes before its quarantine move (the 2026-10-18 crash), one vanishes right before its
    post-commit move to processed/. The run completes; untouched files are processed normally."""
    tmp = _tmp()
    try:
        st = tmp / "staging/sasia_ru/KG"
        ok = st / "wd_Q90.20261011T010000Zp0001.jsonl"
        gone_hash = st / "wd_Q91.20261011T010000Zp0001.jsonl"
        gone_read = st / "wd_Q92.20261011T010000Zp0001.jsonl"
        gone_q = st / "KG-kg_cbd_bad.cbdkgfull20261018T173427Zp0001.jsonl"  # bad name -> quarantine move
        gone_mv = st / "wd_Q93.20261011T010000Zp0001.jsonl"
        for p, q in ((ok, "Q90"), (gone_hash, "Q91"), (gone_read, "Q92"), (gone_mv, "Q93")):
            w(p, [base(f"d{q}", place_id=f"wd:{q}", country_code="KG", language="ky")])
        w(gone_q, [base("x", place_id="wd:Q94", country_code="KG")])

        orig_sha, orig_build, orig_move = RL.sha256_file, RL.build_place, RL.move_unique

        def sha(p):
            if Path(p) == gone_hash:
                gone_hash.unlink()
            return orig_sha(p)

        def build(job):
            if job["key"] == "wd_Q92":
                gone_read.unlink()
            return orig_build(job)

        def move(src, dst_dir):
            if Path(src) in (gone_q, gone_mv) and Path(src).exists():
                Path(src).unlink()  # vanishes after the exists() check, inside the move
            return orig_move(src, dst_dir)

        with _Patch(RL, "sha256_file", sha), _Patch(RL, "build_place", build), _Patch(RL, "move_unique", move), \
                _Patch(RL, "commit_repo", _stub_commit):
            assert RL.main(_argv(tmp)) == 0
        summ = _last_summary(tmp)
        assert summ.get("files_vanished_before_read", 0) == 2, summ   # hash + build
        assert summ.get("files_vanished_before_move", 0) == 2, summ   # quarantine + processed
        assert summ.get("files_vanished_skipped", 0) == 1, summ
        assert not summ.get("files_unreadable"), summ
        assert summ.get("places_skipped_all_files_vanished") == 1, summ  # wd_Q92: nothing rewritten
        assert not list((tmp / "out").rglob("wd_Q92*"))
        assert (tmp / "processed/sasia_ru/KG" / ok.name).exists() and not ok.exists()
        assert not (tmp / "quarantine/sasia_ru/KG" / gone_q.name).exists()
        led = [json.loads(l) for l in (tmp / "state/ledger.jsonl").read_text().splitlines()]
        rels = {Path(r["rel"]).name for r in led}
        assert ok.name in rels and gone_mv.name in rels  # committed rows -> ledgered even if the move raced
        assert gone_hash.name not in rels and gone_read.name not in rels
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_vanished_full_snapshot_does_not_empty_place():
    """A full snapshot that vanishes between the exists() check and open() must not reset the place to zero rows."""
    tmp = _tmp()
    try:
        st = tmp / "staging/eu/FR"
        first = st / "wd_Q90.20261011T010000Zp0001.jsonl"
        w(first, [base("keep1", place_id="wd:Q90", country_code="FR"), base("keep2", place_id="wd:Q90", country_code="FR")])
        full = st / "wd_Q90.full20261012T010000Zp0001.jsonl"
        w(full, [base("new1", place_id="wd:Q90", country_code="FR")], mtime=1_700_000_100)
        orig_iter = S.iter_staged_records

        def it(path):
            if Path(path) == full:
                full.unlink()
            return orig_iter(path)

        with _Patch(S, "iter_staged_records", it), _Patch(RL, "commit_repo", _stub_commit):
            assert RL.main(_argv(tmp)) == 0
        summ = _last_summary(tmp)
        assert summ.get("files_vanished_before_read") == 1, summ
        assert summ.get("rows_ok") == 2 and not summ.get("places_empty_after_hold_or_full"), summ
        import pyarrow.parquet as pq
        out = list((tmp / "out" / S.ROOT / "data").rglob("wd_Q90*_html.parquet"))
        ids = sorted(i for p in out for i in pq.read_table(str(p)).column("doc_id").to_pylist())
        assert len(ids) == 2, ids
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
