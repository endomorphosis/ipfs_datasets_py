"""Disk guard + verified processed/ pruning (synthetic data under /tmp only; no network)."""
import gzip, hashlib, io, json, os, shutil, sys, tempfile, time
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
import run_loop as RL  # noqa: E402
import prune_processed as PP  # noqa: E402
import schema as S  # noqa: E402


def sha(b):
    return hashlib.sha256(b).hexdigest()


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def test_disk_guard_levels():
    tmp = Path(tempfile.mkdtemp(prefix="wl_disk_"))
    try:
        assert RL.disk_guard(tmp, 15, 8, free_gb=40)["level"] == "ok"
        assert not (tmp / "disk_alert.json").exists()
        buf = io.StringIO()
        with redirect_stdout(buf):
            r = RL.disk_guard(tmp, 15, 8, free_gb=12.3)
        assert r["level"] == "low" and not r["skip_builds"] and "DISK_LOW free=12.3GB" in buf.getvalue()
        assert json.loads((tmp / "disk_alert.json").read_text())["level"] == "low"
        with redirect_stdout(io.StringIO()):
            r = RL.disk_guard(tmp, 15, 8, free_gb=5)
        assert r["level"] == "critical" and r["skip_builds"]
        r = RL.disk_guard(tmp, 15, 8, free_gb=30)
        assert r["level"] == "ok" and not (tmp / "disk_alert.json").exists() and (tmp / "disk_alert.cleared.json").exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_critical_disk_skips_builds():
    tmp = Path(tempfile.mkdtemp(prefix="wl_disk_"))
    try:
        st = tmp / "staging" / "eu" / "NL"
        st.mkdir(parents=True)
        (st / "wd_Q1.b_20260101T000000Z.jsonl").write_text(json.dumps({"doc_id": "x"}) + "\n")
        os.utime(st / "wd_Q1.b_20260101T000000Z.jsonl", (time.time() - 100, time.time() - 100))
        orig = RL.disk_free_gb
        RL.disk_free_gb = lambda path=None: 5.0
        try:
            with redirect_stdout(io.StringIO()) as buf:
                RL.main(["--staging", str(tmp / "staging"), "--out", str(tmp / "out"), "--state", str(tmp / "state"),
                         "--processed", str(tmp / "processed"), "--quarantine", str(tmp / "q"), "--held", str(tmp / "h"),
                         "--overrides", str(tmp / "none.json"), "--once", "--dry-run", "--no-hub-listing",
                         "--repo", "test/muni", "--national-repo", "test/nat"])
        finally:
            RL.disk_free_gb = orig
        assert "DISK_LOW" in buf.getvalue()
        summ = json.loads(next((tmp / "state").glob("dryrun_*/summary.json")).read_text())
        assert summ["disk_skipped_builds"] == 1 and summ.get("places_written", 0) == 0
        assert (st / "wd_Q1.b_20260101T000000Z.jsonl").exists()
        assert (tmp / "state" / "disk_alert.json").exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class FakeApi:
    def __init__(self, commits, files):
        self.commits, self.files = commits, files  # {repo: [ids]}, {(repo, path): (sha, size)}

    def list_repo_commits(self, repo, repo_type=None):
        return [SimpleNamespace(commit_id=c) for c in self.commits.get(repo, [])]

    def get_paths_info(self, repo, paths, repo_type=None, expand=False):
        out = []
        for p in paths:
            if (repo, p) in self.files:
                s, n = self.files[(repo, p)]
                out.append(SimpleNamespace(path=p, lfs=SimpleNamespace(sha256=s, size=n)))
        return out


def _setup(tmp, now):
    """5 processed files: old+verified (plain), old+verified (.gz), young, hub mismatch, commit missing;
    plus a web/ file that must never be touched."""
    state, out, proc = tmp / "state", tmp / "out", tmp / "processed"
    state.mkdir(parents=True)
    ledger, files, commits = [], {}, {"m": ["c1", "c2"]}
    runs = [{"at": iso(now - 3 * 3600), "dry_run": False, "repo": "m", "commit_ids": ["c1"],
             "commit_ids_by_repo": {"m": ["c1"]}},
            {"at": iso(now - 600), "dry_run": False, "repo": "m", "commit_ids_by_repo": {"m": ["c2"]}}]
    specs = [("wd_Q1", "old_ok", now - 3 * 3600 - 60, True, False),
             ("wd_Q2", "old_gz", now - 3 * 3600 - 60, True, True),
             ("wd_Q3", "young", now - 700, True, False),
             ("wd_Q4", "mismatch", now - 3 * 3600 - 60, False, False),
             ("wd_Q5", "nocommit", now - 3 * 3600 - 60, True, False)]
    for key, batch, t, hub_ok, gz in specs:
        name = f"{key}.{batch}_20260101T000000Z.jsonl"
        body = "".join(json.dumps({"doc_id": f"{key}-{i}"}) + "\n" for i in range(3)).encode()
        d = proc / "eu" / "NL"
        d.mkdir(parents=True, exist_ok=True)
        if gz:
            with gzip.open(d / (name + ".gz"), "wb") as f:
                f.write(body)
        else:
            (d / name).write_bytes(body)
        e = {"bot": "eu", "rel": f"eu/NL/{name}", "sha256": sha(body), "rows": 3, "held": 0, "rejected": 0,
             "at": iso(t), "repo": "m"}
        if batch == "nocommit":
            e["commit_ids"] = ["c-missing"]
        ledger.append(e)
        pq_rel = f"{S.ROOT}/data/NL/{key}_html.parquet"
        (out / pq_rel).parent.mkdir(parents=True, exist_ok=True)
        pb = b"PAR1" + key.encode() + b"PAR1"
        (out / pq_rel).write_bytes(pb)
        files[("m", pq_rel)] = (sha(pb) if hub_ok else sha(b"other"), len(pb))
    (proc / "web" / "DE").mkdir(parents=True)
    (proc / "web" / "DE" / "wd_Q9.x.jsonl").write_text("{}\n")
    (state / "ledger.jsonl").write_text("".join(json.dumps(e) + "\n" for e in ledger))
    (state / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
    return state, out, proc, FakeApi(commits, files)


def test_prune_eligibility():
    tmp = Path(tempfile.mkdtemp(prefix="wl_prune_"))
    now = time.time()
    try:
        state, out, proc, api = _setup(tmp, now)
        ledger_before = (state / "ledger.jsonl").read_bytes()
        kw = dict(state=state, out_dir=out, out_national=tmp / "out_national", processed=proc, repo="m",
                  national_repo="n", api=api, now=now, log=lambda *a: None)
        dry = PP.prune(apply=False, **kw)
        assert dry["eligible"] == 2 and dry["confirmed"] == 3 and dry.get("pruned", 0) == 0
        assert len(list((proc / "eu" / "NL").iterdir())) == 5
        assert not (state / "confirmed_batches" / "eu.jsonl").exists()
        res = PP.prune(apply=True, **kw)
        left = sorted(p.name for p in (proc / "eu" / "NL").iterdir())
        assert res["pruned"] == 2 and res["bytes_freed"] > 0, res
        assert left == sorted(["wd_Q3.young_20260101T000000Z.jsonl", "wd_Q4.mismatch_20260101T000000Z.jsonl",
                               "wd_Q5.nocommit_20260101T000000Z.jsonl"]), left
        assert res["skip_too_young"] == 1 and res["skip_hub_sha_or_size_mismatch"] == 1 and res["skip_commit_not_on_hub"] == 1
        man = [json.loads(l) for l in (state / "pruned_manifest.jsonl").open()]
        assert {m["place_key"] for m in man} == {"wd_Q1", "wd_Q2"}
        for m in man:
            assert m["rows"] == 3 and m["hub_commit"] == "c1" and m["hub_files"][0]["sha256"] and m["doc_ids_sha256"]
        conf = [json.loads(l) for l in (state / "confirmed_batches" / "eu.jsonl").open()]
        assert {c["place_key"] for c in conf} == {"wd_Q1", "wd_Q2", "wd_Q3"}
        assert (proc / "web" / "DE" / "wd_Q9.x.jsonl").exists()  # web/ excluded by default config
        assert (state / "ledger.jsonl").read_bytes() == ledger_before  # ledger untouched
        # re-staged identical file: still in ledger -> run_loop skips it by (bot, rel, sha256)
        led = RL.load_ledger(state / "ledger.jsonl")
        body = "".join(json.dumps({"doc_id": f"wd_Q1-{i}"}) + "\n" for i in range(3)).encode()
        assert ("eu", "eu/NL/wd_Q1.old_ok_20260101T000000Z.jsonl", sha(body)) in led
        # second apply: nothing more to prune, confirmed list keeps pruned batches
        res2 = PP.prune(apply=True, **kw)
        assert res2.get("pruned", 0) == 0
        assert len((state / "confirmed_batches" / "eu.jsonl").read_text().splitlines()) == 3
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_original_name():
    assert PP.original_name("a.b_x.jsonl.gz") == "a.b_x.jsonl"
    assert PP.original_name("a.b.jsonl.20261011T010203Z") == "a.b.jsonl"
    assert PP.original_name("a.b.jsonl.20261011T010203Z.2") == "a.b.jsonl"
    assert PP.original_name("a.parquet") == "a.parquet"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL DISK/PRUNE TESTS PASSED")
