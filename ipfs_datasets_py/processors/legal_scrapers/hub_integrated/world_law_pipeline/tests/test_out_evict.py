"""On-demand local parquet (out_store): eviction + verified rehydrate from a MOCK Hub (synthetic data in /tmp only).

Run: /workspace/hf-venv/bin/python /workspace/world_law/pipeline/tests/test_out_evict.py
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import hashlib, json, os, shutil, sys, tempfile, time
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
PIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPE))
sys.path.insert(0, str(PIPE / "tools"))
sys.path.insert(0, str(PIPE / "tests"))
import schema as S  # noqa: E402
import run_loop as RL  # noqa: E402
import out_store as OST  # noqa: E402
from test_hold_policy import base, w  # noqa: E402

REPO, CC, KEY = "test/muni", "JP", "wd_Q1490"
OLD = time.time() - 3 * 3600


class MockHub:
    """Serves files from a directory as if it were the Hub repo (get_paths_info + download)."""
    def __init__(self, root: Path):
        self.root, self.downloads, self.fail, self.corrupt = root, [], 0, False

    def get_paths_info(self, repo, paths, repo_type=None, expand=False):
        out = []
        for p in paths:
            f = self.root / p
            if not f.exists():
                continue
            if p.endswith(".parquet"):
                out.append(SimpleNamespace(path=p, lfs=SimpleNamespace(sha256=OST.sha256_file(f), size=f.stat().st_size)))
            else:
                out.append(SimpleNamespace(path=p, lfs=None, blob_id=OST.git_blob_id(f), size=f.stat().st_size))
        return out

    def download(self, repo, rel, local_dir):
        self.downloads.append(rel)
        if self.fail:
            self.fail -= 1
            raise ConnectionError("mock hub 503")
        dst = Path(local_dir) / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.root / rel, dst)
        if self.corrupt:
            with dst.open("ab") as f:
                f.write(b"x")
        return str(dst)

    def listing(self):
        return sorted(str(p.relative_to(self.root)) for p in (self.root / S.ROOT / "data").rglob("*.parquet"))


def job(tmp, out_dir, staged, hub_files, state, download=True):
    files = []
    for p in staged:
        st = p.stat()
        batch = p.name[len(KEY) + 1:].rsplit(".", 1)[0]
        files.append({"path": str(p), "rel": str(p.relative_to(tmp / "staging")), "bot": "eu", "sha256": RL.sha256_file(p),
                      "order": RL.batch_order(batch, st.st_mtime, p.name), "mtime": st.st_mtime, "full": False})
    (tmp / "scratch").mkdir(exist_ok=True)
    return {"cc": CC, "key": KEY, "out_dir": str(out_dir), "scratch": str(tmp / "scratch"), "quarantine": str(tmp / "q"),
            "held": str(tmp / "held"), "run_id": "20261014T000000Z", "overrides": {}, "hub_files": hub_files,
            "hub_download": download, "repo": REPO, "state": str(state), "primary_index": None, "files": files}


def publish(tmp, out_dir, res, hub: Path):
    """Write metadata like run_loop does and 'commit' data + metadata to the mock hub dir."""
    assert not res.get("error"), res.get("traceback")
    meta_local, meta_rel, _ = RL.write_metadata(out_dir, CC, KEY, res, 1_700_000_000_000)
    for rel in [r for r, _ in res["written"]] + [meta_rel]:
        d = hub / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out_dir / rel, d)


def setup():
    tmp = Path(tempfile.mkdtemp(prefix="wl_evict_"))
    state, hubdir = tmp / "state", tmp / "hub"
    state.mkdir()
    out = tmp / "out"
    a = tmp / "staging/eu/JP/wd_Q1490.20261011T010000Zp0001.jsonl"
    w(a, [base(f"d{i}", html=f"<p>{'x' * 50} {i}</p>") for i in range(40)])
    res = RL.build_place(job(tmp, out, [a], [], state))
    publish(tmp, out, res, hubdir)
    for p in (out / S.ROOT / "data").rglob("*.parquet"):
        os.utime(p, (OLD, OLD))
    b = tmp / "staging/eu/JP/wd_Q1490.20261012T010000Zp0001.jsonl"
    w(b, [base("d3", html="<p>changed</p>"), base("new1"), base("new2")])
    return tmp, state, out, MockHub(hubdir), b


def data_files(out):
    return sorted((out / S.ROOT / "data").rglob("*.parquet"))


def test_evict_then_missing_local_triggers_verified_download_and_matches_bytes():
    tmp, state, out, hub, b = setup()
    try:
        ref = tmp / "out_ref"  # same tree, local parquet kept: the reference rebuild
        shutil.copytree(out, ref)
        r = OST.evict(out, REPO, state, hub, apply=True, log=lambda m: None)
        assert r["places_evicted"] == 1 and r["bytes_evicted"] > 0 and not data_files(out), r
        assert (out / S.metadata_path(CC, KEY)).exists()  # metadata stays local
        RL._REHYDRATE_DL["fn"] = hub.download
        res = RL.build_place(job(tmp, out, [b], hub.listing(), state))
        assert not res.get("error"), res.get("traceback")
        assert hub.downloads == [S.html_path(CC, KEY)] and res["stats"]["places_rehydrated"] == 1
        assert res["stats"]["rows_existing"] == 40
        res_ref = RL.build_place(job(tmp, ref, [b], hub.listing(), state))
        assert res_ref["stats"]["rows_existing"] == 40 and res_ref["stats"].get("places_rehydrated", 0) == 0
        got, want = data_files(out), data_files(ref)
        assert [p.name for p in got] == [p.name for p in want] and got
        for g, x in zip(got, want):
            assert g.read_bytes() == x.read_bytes(), "rebuilt place differs from the local-parquet rebuild"
        assert res["rows"] == res_ref["rows"] == 42
        assert not (out / ".rehydrate_tmp").exists() or not any((out / ".rehydrate_tmp").iterdir())
    finally:
        RL._REHYDRATE_DL.clear()
        shutil.rmtree(tmp, ignore_errors=True)


def test_failed_download_skips_place_never_partial():
    tmp, state, out, hub, b = setup()
    try:
        OST.evict(out, REPO, state, hub, apply=True, log=lambda m: None)
        hub.fail = 99
        RL._REHYDRATE_DL["fn"] = hub.download
        orig_sleep = OST.time.sleep
        OST.time.sleep = lambda s: None
        try:
            res = RL.build_place(job(tmp, out, [b], hub.listing(), state))
        finally:
            OST.time.sleep = orig_sleep
        assert res["error"] and "RehydrateError" in res["error"], res
        assert len(hub.downloads) == 3  # retried
        assert not data_files(out) and not res["written"]
        assert b.exists()  # staged file untouched (run_loop only moves/ledgers committed places)
        # retries recover from transient failures
        hub.fail, hub.downloads = 2, []
        OST.time.sleep = lambda s: None
        try:
            res = RL.build_place(job(tmp, out, [b], hub.listing(), state))
        finally:
            OST.time.sleep = orig_sleep
        assert not res.get("error") and len(hub.downloads) == 3 and res["stats"]["rows_existing"] == 40
    finally:
        RL._REHYDRATE_DL.clear()
        shutil.rmtree(tmp, ignore_errors=True)


def test_sha_mismatch_is_rejected():
    tmp, state, out, hub, b = setup()
    try:
        OST.evict(out, REPO, state, hub, apply=True, log=lambda m: None)
        hub.corrupt = True
        RL._REHYDRATE_DL["fn"] = hub.download
        OST_sleep = OST.time.sleep
        OST.time.sleep = lambda s: None
        try:
            res = RL.build_place(job(tmp, out, [b], hub.listing(), state))
        finally:
            OST.time.sleep = OST_sleep
        assert res["error"] and "mismatch" in res["error"] and not data_files(out)
    finally:
        RL._REHYDRATE_DL.clear()
        shutil.rmtree(tmp, ignore_errors=True)


def test_missing_local_without_downloads_or_expected_sha_fails():
    tmp, state, out, hub, b = setup()
    try:
        for p in data_files(out):
            p.unlink()  # lost without an eviction record and no manifest
        RL._REHYDRATE_DL["hub"] = lambda repo, rels: {}  # hermetic: no real Hub sha lookup (not LFS-listed)
        res = RL.build_place(job(tmp, out, [b], hub.listing(), state, download=True))
        RL._REHYDRATE_DL["fn"] = hub.download
        res = RL.build_place(job(tmp, out, [b], hub.listing(), state))
        assert res["error"] and "no expected sha256" in res["error"] and not hub.downloads
        res = RL.build_place(job(tmp, out, [b], hub.listing(), state, download=False))
        assert res["error"] and "partial" in res["error"]
        # a manifest line is an accepted expected sha
        rel = S.html_path(CC, KEY)
        m = out / S.ROOT / "manifests/drop_20261013T000000Z_manifest.jsonl"
        m.parent.mkdir(parents=True, exist_ok=True)
        f = hub.root / rel
        m.write_text(json.dumps({"path_in_repo": rel, "sha256": OST.sha256_file(f), "bytes": f.stat().st_size}) + "\n")
        res = RL.build_place(job(tmp, out, [b], hub.listing(), state))
        assert not res.get("error") and res["stats"]["rows_existing"] == 40
    finally:
        RL._REHYDRATE_DL.clear()
        shutil.rmtree(tmp, ignore_errors=True)


def test_evict_requires_age_and_hub_identity():
    tmp, state, out, hub, b = setup()
    try:
        f = data_files(out)[0]
        os.utime(f, None)
        assert OST.evict(out, REPO, state, hub, apply=True, log=lambda m: None)["skips"] == {"too_young": 1}
        os.utime(f, (OLD, OLD))
        (hub.root / S.html_path(CC, KEY)).write_bytes(b"different")
        r = OST.evict(out, REPO, state, hub, apply=True, log=lambda m: None)
        assert r["places_evicted"] == 0 and f.exists() and r["skips"] == {"hub_missing_or_size": 1}
        shutil.copyfile(f, hub.root / S.html_path(CC, KEY))
        (hub.root / S.metadata_path(CC, KEY)).write_text("{}")
        r = OST.evict(out, REPO, state, hub, apply=True, log=lambda m: None)
        assert f.exists() and r["skips"] == {"hub_metadata_differs": 1}
        assert not (state / OST.EVICT_LOG).exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_eviction_record_indexes_missing_files():
    tmp, state, out, hub, b = setup()
    try:
        OST.evict(out, REPO, state, hub, apply=True, log=lambda m: None)
        ev = OST.load_evicted(state)
        assert list(ev) == [(REPO, S.html_path(CC, KEY))]
        assert OST.evicted_missing(out, state, REPO, CC) == {(CC, KEY): [S.html_path(CC, KEY)]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _hub_rebuilt_after_eviction(tmp, out, state, hub):
    """Evict, then the place is rebuilt + recommitted elsewhere: the Hub file changes, the eviction record is stale."""
    OST.evict(out, REPO, state, hub, apply=True, log=lambda m: None)
    other = tmp / "out_other"
    c = tmp / "staging/eu/JP/wd_Q1490.20261013T010000Zp0001.jsonl"
    w(c, [base(f"e{i}", html=f"<p>{'y' * 60} {i}</p>") for i in range(7)])
    res = RL.build_place(job(tmp, other, [c], [], state, download=False))
    assert not res.get("error"), res.get("traceback")
    rel = S.html_path(CC, KEY)
    shutil.copyfile(other / rel, hub.root / rel)
    c.unlink()
    return rel


def _no_sleep():
    orig = OST.time.sleep
    OST.time.sleep = lambda s: None
    return orig


def test_stale_eviction_record_loses_to_hub_sha():
    tmp, state, out, hub, b = setup()
    orig = _no_sleep()
    try:
        rel = _hub_rebuilt_after_eviction(tmp, out, state, hub)
        RL._REHYDRATE_DL["fn"] = hub.download
        res = RL.build_place(job(tmp, out, [b], hub.listing(), state))  # records only: stale record -> mismatch
        assert res["error"] and "mismatch" in res["error"], res
        logs = []
        RL._REHYDRATE_DL["hub"] = lambda repo, rels: OST.hub_lfs_expected(repo, rels, api=hub)
        got = OST.rehydrate(REPO, out, state, [rel], download=hub.download, log=logs.append,
                            hub_lookup=RL._REHYDRATE_DL["hub"])
        assert got and OST.sha256_file(got[0]) == OST.sha256_file(hub.root / rel)
        assert any("stale" in m for m in logs), logs
        got[0].unlink()
        res = RL.build_place(job(tmp, out, [b], hub.listing(), state))
        assert not res.get("error"), res.get("traceback")
        assert res["stats"]["places_rehydrated"] == 1 and res["stats"]["rows_existing"] == 7
    finally:
        OST.time.sleep = orig
        RL._REHYDRATE_DL.clear()
        shutil.rmtree(tmp, ignore_errors=True)


def test_newer_manifest_beats_stale_eviction_record_without_hub_lookup():
    tmp, state, out, hub, b = setup()
    orig = _no_sleep()
    try:
        rel = _hub_rebuilt_after_eviction(tmp, out, state, hub)
        f = hub.root / rel
        m = out / S.ROOT / "manifests/drop_29991231T000000Z_manifest.jsonl"  # built after the eviction
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text(json.dumps({"path_in_repo": rel, "sha256": OST.sha256_file(f), "bytes": f.stat().st_size,
                                 "built_at": "2999-12-31T00:00:00Z"}) + "\n")
        RL._REHYDRATE_DL["fn"] = hub.download
        res = RL.build_place(job(tmp, out, [b], hub.listing(), state))
        assert not res.get("error"), res.get("traceback")
        assert res["stats"]["rows_existing"] == 7
    finally:
        OST.time.sleep = orig
        RL._REHYDRATE_DL.clear()
        shutil.rmtree(tmp, ignore_errors=True)


def test_older_manifest_does_not_override_eviction_record():
    tmp, state, out, hub, b = setup()
    try:
        OST.evict(out, REPO, state, hub, apply=True, log=lambda m: None)
        rel = S.html_path(CC, KEY)
        ev = OST.load_evicted(state, REPO)[(REPO, rel)]
        m = out / S.ROOT / "manifests/drop_20000101T000000Z_manifest.jsonl"
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text(json.dumps({"path_in_repo": rel, "sha256": "0" * 64, "bytes": 1,
                                 "built_at": "2000-01-01T00:00:00Z"}) + "\n")
        assert OST.expected_shas(state, out, REPO, [rel]) == {rel: (ev["sha256"], ev["bytes"])}
        # the Hub sha always wins when known
        assert OST.expected_shas(state, out, REPO, [rel], hub={rel: ("f" * 64, 9)}) == {rel: ("f" * 64, 9)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL OUT-EVICT TESTS PASSED")
