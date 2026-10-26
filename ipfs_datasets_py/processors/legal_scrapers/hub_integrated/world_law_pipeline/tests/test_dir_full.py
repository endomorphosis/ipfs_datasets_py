"""HF 10,000-files-per-directory guard (interim): DIR_FULL deferral before planning, one retry on the Hub's
'too many files per directory' error, near-limit report. Mocked Hub; synthetic data in /tmp."""
import json, shutil, sys, tempfile
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE / "tests"))
import run_loop as RL  # noqa: E402
from test_scoped_listing import HubMock, _run  # noqa: E402
import schema as _S  # noqa: E402
_S.BUCKETED_COUNTRIES = frozenset()  # flat-layout tests; hash buckets: test_buckets.py

RL.PREFIX_LISTING_BACKOFF_S = 0.0


def test_plan_dir_full_counts_new_files_only():
    hub = {f"world_law/data/FR/p{i}_html.parquet" for i in range(5)} | \
          {f"world_law/metadata/FR/p{i}.json" for i in range(5)}
    adds = {("FR", "p0"): ["world_law/data/FR/p0_html.parquet", "world_law/metadata/FR/p0.json"],  # replace: 0 new
            ("FR", "q1"): ["world_law/data/FR/q1_html.parquet", "world_law/metadata/FR/q1.json"],
            ("FR", "q2"): ["world_law/data/FR/q2_html.parquet", "world_law/metadata/FR/q2.json"],
            ("NL", "n1"): ["world_law/data/NL/n1_html.parquet", "world_law/metadata/NL/n1.json"]}
    d, per, counts = RL.plan_dir_full(adds, hub, limit=6)
    assert d == {("FR", "q2")} and per == Counter({"FR": 1})
    assert counts["data/FR"] == 6 and counts["data/NL"] == 1
    d, _, _ = RL.plan_dir_full({("FR", "p0"): adds[("FR", "p0")]}, hub, limit=5)
    assert d == set(), "replacing an existing place adds no files"


def test_parse_too_many_files():
    e = Exception("400 Bad Request: too many files per directory: world_law/data/FR has 10001 files (limit 10000)")
    assert RL.parse_too_many_files(e) == {"FR"}
    assert RL.parse_too_many_files(Exception("500 Internal")) is None
    assert RL.parse_too_many_files(Exception("Too many files per directory")) == set()


def test_near_limit_report():
    r = RL.near_limit_report(Counter({"data/FR": 9977, "metadata/FR": 9977, "data/NL": 10, "data/IT/ab": 40}))
    assert list(r) == ["data/FR", "metadata/FR"] and r["data/FR"] == {"files": 9977, "headroom": 23}


def _setup(tmp):
    from test_hold_policy import base, w
    fr = tmp / "staging/eu/FR/wd_Q90.20261012T010000Zp0001.jsonl"
    nl = tmp / "staging/eu/NL/wd_Q727.20261012T010000Zp0001.jsonl"
    w(fr, [base("m1", place_id="wd:Q90", country_code="FR", language="fr")])
    w(nl, [base("m2", place_id="wd:Q727", country_code="NL", language="nl")])
    return fr, nl


def test_dir_full_deferred_before_commit():
    tmp = Path(tempfile.mkdtemp(prefix="wl_dirfull_"))
    old = RL.DIR_FULL_LIMIT
    try:
        RL.DIR_FULL_LIMIT = 3
        fr, nl = _setup(tmp)
        hub = {f"world_law/data/FR/x{i}_html.parquet" for i in range(3)} | {"world_law/metadata/FR/x0.json"}
        api = HubMock({"test/muni": hub, "test/nat": set()})
        assert _run(tmp, api) == 0
        assert len(api.commits) == 1
        paths = {o.path_in_repo for o in api.commits[0]["operations"]}
        assert not any("/FR/" in p for p in paths) and any("/NL/" in p for p in paths)
        assert fr.exists() and not nl.exists()
        s = json.loads((tmp / "state/runs.jsonl").read_text().splitlines()[-1])
        assert s["DIR_FULL"] == {"test/muni": {"FR": 1}} and s["places_deferred_dir_full"] == 1
        assert s["files_left_staged_dir_full"] == 1
        led = [json.loads(l) for l in (tmp / "state/ledger.jsonl").read_text().splitlines()]
        assert {r["cc"] for r in led} == {"NL"}
        import pyarrow.parquet as pq
        rows = pq.read_table(tmp / "out/world_law/places.parquet").to_pylist()
        assert not any(r["country_code"] == "FR" for r in rows)
    finally:
        RL.DIR_FULL_LIMIT = old
        shutil.rmtree(tmp, ignore_errors=True)


class RejectFR(HubMock):
    def create_commit(self, **kw):
        if any("/FR/" in o.path_in_repo for o in kw["operations"]):
            self.rejected = getattr(self, "rejected", 0) + 1
            raise Exception("Bad request: too many files per directory (world_law/metadata/FR)")
        return super().create_commit(**kw)


def test_too_many_files_error_retries_once_without_country():
    tmp = Path(tempfile.mkdtemp(prefix="wl_dirfull2_"))
    try:
        fr, nl = _setup(tmp)
        api = RejectFR({"test/muni": set(), "test/nat": set()})
        assert _run(tmp, api) == 0
        assert api.rejected == 1 and len(api.commits) == 1
        assert "[dir-full retry]" in api.commits[0]["commit_message"]
        assert fr.exists() and not nl.exists()
        s = json.loads((tmp / "state/runs.jsonl").read_text().splitlines()[-1])
        assert s["DIR_FULL"] == {"test/muni": {"FR": 1}} and s["dir_full_commit_retries"] == 1
        assert "upload_failed" not in s
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL DIR-FULL TESTS PASSED")
