"""doc_overrides apply to already-published rows when a place is rebuilt (--rebuild-places), counted as
override_removed_existing; a rebuild with nothing staged keeps every other row.

Run: /workspace/hf-venv/bin/python /workspace/world_law/pipeline/tests/test_override_existing.py  (/tmp only)
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
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import run_loop  # noqa: E402
from test_hold_policy import _tmp, base, read_place, w  # noqa: E402
from test_hold_policy import run as _run  # noqa: E402


def run(tmp, **kw):
    time.sleep(1.1)  # run ids are per-second
    try:
        return _run(tmp, **kw)
    finally:  # release the in-process lock between runs
        if run_loop._LOCK.get("f") is not None:
            run_loop._LOCK["f"].close()
        run_loop._LOCK["f"] = None


def us(doc_id, **kw):
    return base(doc_id, place_id="iso:US-CA", country_code="US", doc_type="regulation", language="en", **kw)


def test_cc_of_key():
    assert run_loop._cc_of_key("iso_US-CA") == "US" and run_loop._cc_of_key("iso_FR") == "FR"
    assert run_loop._cc_of_key("JP_wd_Q1490") == "JP"


def test_override_removes_existing_on_rebuild():
    tmp = _tmp()
    try:
        w(tmp / "staging/national/US/iso_US-CA.20261014T000000Zp0001.jsonl", [us(d) for d in ("a", "b", "c", "keep")])
        scratch, _ = run(tmp, **{"national-repo": "test/nat"})
        # publish: the dry-run output becomes the "existing" national tree
        shutil.copytree(scratch / "out_national", tmp / "out_national")
        shutil.rmtree(tmp / "staging")
        (tmp / "staging").mkdir()
        (tmp / "overrides.json").write_text(json.dumps({"quarantine": [
            {"country_code": "US", "place_key": "iso_US-CA", "doc_id": d, "reason": "test junk"} for d in ("a", "b", "zz")]}))
        # without --rebuild-places nothing is staged -> nothing is built
        scratch0, summ0 = run(tmp, **{"national-repo": "test/nat"})
        assert summ0.get("places_written", 0) == 0
        scratch, summ = run(tmp, **{"national-repo": "test/nat", "rebuild-places": "iso_US-CA"})
        _, rows = read_place(scratch, "US", "iso_US-CA")
        assert sorted(r["doc_id"] for r in rows) == ["c", "keep"], rows
        assert summ["override_removed_existing"] == 2 and summ["rows_existing"] == 2
        assert summ["rebuild_places_requested"] == 1 and summ["places_written"] == 1
        logs = [json.loads(l) for p in scratch.rglob("*.removed.jsonl") for l in p.read_text().splitlines()]
        assert sorted(x["doc_id"] for x in logs) == ["a", "b"]
        # staged rows + rebuild together: staged new row added, override still applied to existing
        w(tmp / "staging/national/US/iso_US-CA.20261014T010000Zp0001.jsonl", [us("new")])
        scratch, summ = run(tmp, **{"national-repo": "test/nat", "rebuild-places": "iso_US-CA,iso_US-ZZ"})
        _, rows = read_place(scratch, "US", "iso_US-CA")
        assert sorted(r["doc_id"] for r in rows) == ["c", "keep", "new"]
        assert summ["override_removed_existing"] == 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
