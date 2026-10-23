"""Hash-bucketed layout for big countries (schema.BUCKETED_COUNTRIES): path functions, per-bucket DIR_FULL,
a run that moves a flat place into its bucket (adds + legacy deletes in one commit), both-layout readers, card
globs, and the migration tool's pure planning/rewrite helpers. Mocked Hub; synthetic data in /tmp."""
import hashlib, json, shutil, sys, tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE / "tests")); sys.path.insert(0, str(HERE / "tools"))
import schema as S  # noqa: E402
import run_loop as RL  # noqa: E402
from test_scoped_listing import HubMock, _run  # noqa: E402

RL.PREFIX_LISTING_BACKOFF_S = 0.0
ORIG = frozenset({"FR", "IT", "DE"})
S.BUCKETED_COUNTRIES = ORIG  # test_scoped_listing (imported above) switches to the flat layout


def _b(k):
    return hashlib.sha256(k.encode()).hexdigest()[:2]


def test_config_and_paths():
    assert S.BUCKETED_COUNTRIES == ORIG
    S.BUCKETED_COUNTRIES = ORIG
    b = _b("wd_Q90")
    assert S.html_path("FR", "wd_Q90") == f"world_law/data/FR/{b}/wd_Q90_html.parquet"
    assert S.metadata_path("IT", "wd_Q90") == f"world_law/metadata/IT/{b}/wd_Q90.json"
    assert S.shard_path("DE", "wd_Q90", 2) == f"world_law/data/DE/{b}/wd_Q90.s0002_html.parquet"
    assert S.shard_glob("DE", "wd_Q90") == f"world_law/data/DE/{b}/wd_Q90.s*_html.parquet"
    assert S.html_path("ES", "wd_Q90") == "world_law/data/ES/wd_Q90_html.parquet"
    assert S.html_path("FR", "iso_FR-75") == "world_law/data/FR/iso_FR-75_html.parquet", "national never bucketed"
    assert len({S.place_bucket(f"wd_Q{i}") for i in range(20000)}) == 256
    assert S.is_place_data_file("world_law/data/FR/wd_Q90_html.parquet", "FR", "wd_Q90")  # legacy accepted
    assert not S.is_place_data_file("world_law/data/FR/wd_Q90_html.parquet", "FR", "wd_Q90", legacy=False)
    assert S.is_place_data_file(f"world_law/data/FR/{b}/wd_Q90.s0003_html.parquet", "FR", "wd_Q90")
    assert not S.is_place_data_file(f"world_law/data/FR/{b}/wd_Q900_html.parquet", "FR", "wd_Q90")
    assert S.legacy_metadata_paths("FR", "wd_Q90") == ["world_law/metadata/FR/wd_Q90.json"]
    assert S.legacy_metadata_paths("ES", "wd_Q90") == [f"world_law/metadata/ES/{b}/wd_Q90.json"]


def test_dir_counts_per_bucket():
    hub = {f"world_law/data/FR/ab/p{i}_html.parquet" for i in range(3)} | {"world_law/data/FR/x_html.parquet"}
    c = RL.hub_dir_counts(hub)
    assert c == Counter({"data/FR/ab": 3, "data/FR": 1})
    adds = {("FR", "q1"): ["world_law/data/FR/ab/q1_html.parquet"], ("FR", "q2"): ["world_law/data/FR/cd/q2_html.parquet"]}
    d, per, counts = RL.plan_dir_full(adds, hub, limit=3)
    assert d == {("FR", "q1")} and per == Counter({"FR": 1}) and counts["data/FR/cd"] == 1
    assert RL.cc_max_dir(counts, "FR") == 3


def test_run_moves_flat_place_into_bucket():
    from test_hold_policy import base, w
    tmp = Path(tempfile.mkdtemp(prefix="wl_bucket_"))
    try:
        S.BUCKETED_COUNTRIES = frozenset()  # run 1: legacy flat layout
        w(tmp / "staging/eu/FR/wd_Q90.20261011T010000Zp0001.jsonl",
          [base("m1", place_id="wd:Q90", country_code="FR", language="fr")])
        api = HubMock({"test/muni": set(), "test/nat": set()})
        assert _run(tmp, api) == 0
        flat = {o.path_in_repo for o in api.commits[0]["operations"] if "/FR/" in o.path_in_repo}
        assert flat == {"world_law/data/FR/wd_Q90_html.parquet", "world_law/metadata/FR/wd_Q90.json"}
        S.BUCKETED_COUNTRIES = frozenset({"FR"})  # run 2: FR bucketed, hub still flat
        w(tmp / "staging/eu/FR/wd_Q90.20261012T010000Zp0001.jsonl",
          [base("m2", place_id="wd:Q90", country_code="FR", language="fr")])
        api = HubMock({"test/muni": set(flat), "test/nat": set()})
        assert _run(tmp, api) == 0
        assert ("test/muni", "world_law/data/FR", "recursive") in api.tree_calls
        ops = api.commits[0]["operations"]
        dels = {o.path_in_repo for o in ops if type(o).__name__ == "CommitOperationDelete"}
        adds = {o.path_in_repo for o in ops if type(o).__name__ == "CommitOperationAdd"}
        b = _b("wd_Q90")
        assert dels == flat, dels
        assert {f"world_law/data/FR/{b}/wd_Q90_html.parquet", f"world_law/metadata/FR/{b}/wd_Q90.json"} <= adds
        out = tmp / "out"
        assert not (out / "world_law/data/FR/wd_Q90_html.parquet").exists()
        assert not (out / "world_law/metadata/FR/wd_Q90.json").exists()
        m = json.loads((out / f"world_law/metadata/FR/{b}/wd_Q90.json").read_text())
        assert m["html_files"] == [f"world_law/data/FR/{b}/wd_Q90_html.parquet"] and m["total_docs"] == 2
        import pyarrow.parquet as pq
        r = [x for x in pq.read_table(out / "world_law/places.parquet").to_pylist() if x["place_key"] == "wd_Q90"]
        assert r[0]["html_path"] == m["html_files"][0] and r[0]["metadata_path"].endswith(f"FR/{b}/wd_Q90.json")
    finally:
        S.BUCKETED_COUNTRIES = ORIG
        shutil.rmtree(tmp, ignore_errors=True)


def test_dir_full_per_bucket_in_run():
    from test_hold_policy import base, w
    tmp = Path(tempfile.mkdtemp(prefix="wl_bucket_full_"))
    old = RL.DIR_FULL_LIMIT
    try:
        S.BUCKETED_COUNTRIES = frozenset({"FR"})
        RL.DIR_FULL_LIMIT = 2
        b90 = _b("wd_Q90")
        # Q90's bucket is full; the flat FR dir is huge but no longer matters for bucketed places
        hub = {f"world_law/data/FR/{b90}/x{i}_html.parquet" for i in range(2)} | \
              {f"world_law/data/FR/y{i}_html.parquet" for i in range(50)}
        k2 = next(f"wd_Q{i}" for i in range(91, 999) if _b(f"wd_Q{i}") != b90)
        w(tmp / "staging/eu/FR/wd_Q90.20261012T010000Zp0001.jsonl", [base("a", place_id="wd:Q90", country_code="FR")])
        w(tmp / f"staging/eu/FR/{k2}.20261012T010000Zp0001.jsonl", [base("b", place_id="wd:" + k2[3:], country_code="FR")])
        api = HubMock({"test/muni": hub, "test/nat": set()})
        assert _run(tmp, api) == 0
        paths = {o.path_in_repo for o in api.commits[0]["operations"]}
        assert any(k2 in p for p in paths) and not any("wd_Q90" in p for p in paths)
        s = json.loads((tmp / "state/runs.jsonl").read_text().splitlines()[-1])
        assert s["DIR_FULL"] == {"test/muni": {"FR": 1}}
    finally:
        RL.DIR_FULL_LIMIT = old
        S.BUCKETED_COUNTRIES = ORIG
        shutil.rmtree(tmp, ignore_errors=True)


def test_local_readers_both_layouts():
    import out_store as OS_
    tmp = Path(tempfile.mkdtemp(prefix="wl_bucket_rd_"))
    try:
        b = _b("wd_Q90")
        for rel in ["world_law/data/FR/wd_Q90_html.parquet", f"world_law/data/FR/{b}/wd_Q90.s0001_html.parquet",
                    "world_law/data/ES/wd_Q1_html.parquet", f"world_law/metadata/FR/{b}/wd_Q90.json",
                    "world_law/metadata/ES/wd_Q1.json"]:
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp / rel).write_text("{}")
        got = [p.relative_to(tmp).as_posix() for p in OS_.local_place_files(tmp, "FR", "wd_Q90")]
        assert got == [f"world_law/data/FR/{b}/wd_Q90.s0001_html.parquet", "world_law/data/FR/wd_Q90_html.parquet"]
        assert [p.name for p in S.iter_local_metadata(tmp / "world_law")] == ["wd_Q1.json", "wd_Q90.json"]
        assert sorted(c for c, _ in S.iter_local_data(tmp / "world_law")) == ["ES", "FR", "FR"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_loader_and_card():
    import world_law_loader as W, card
    b = _b("wd_Q90")
    assert W.bucket("wd_Q90") == b
    assert W.layout_alternatives("world_law/data/FR/wd_Q90_html.parquet")[1] == f"world_law/data/FR/{b}/wd_Q90_html.parquet"
    assert W.layout_alternatives(f"world_law/data/FR/{b}/wd_Q90.s*_html.parquet")[1] == "world_law/data/FR/wd_Q90.s*_html.parquet"
    assert W.layout_alternatives("world_law/places.parquet") == ["world_law/places.parquet"]
    c = card.build_card(["FR", "NO"])
    assert '- config_name: "NO"' in c and "    - world_law/data/FR/*/*_html.parquet" in c
    assert "    - world_law/data/*/*_html.parquet" in c and "    - world_law/data/*/*/*_html.parquet" in c


def test_migration_plan_and_rewrites():
    import migrate_buckets as MB
    b = _b("wd_Q90")
    hub = {"world_law/data/FR/wd_Q90_html.parquet", "world_law/metadata/FR/wd_Q90.json",
           "world_law/data/FR/wd_Q91.s0001_html.parquet", "world_law/data/FR/wd_Q91.s0002_html.parquet",
           "world_law/metadata/FR/wd_Q91.json", f"world_law/data/FR/{_b('wd_Q92')}/wd_Q92_html.parquet",
           "world_law/data/FR/iso_FR-75_html.parquet"}
    plan = MB.plan_moves(hub, "FR")
    assert plan[("FR", "wd_Q90")] == {"data": [("world_law/data/FR/wd_Q90_html.parquet", f"world_law/data/FR/{b}/wd_Q90_html.parquet")],
                                      "metadata": [("world_law/metadata/FR/wd_Q90.json", f"world_law/metadata/FR/{b}/wd_Q90.json")]}
    assert len(plan[("FR", "wd_Q91")]["data"]) == 2
    assert ("FR", "wd_Q92") not in plan and ("FR", "iso_FR-75") not in plan
    raw = json.dumps({"place_key": "wd_Q90", "html_files": ["world_law/data/FR/wd_Q90_html.parquet"], "n_shards": 1},
                     ensure_ascii=False, separators=(",", ":")) + "\n"
    new = MB.rewrite_meta_bytes(raw.encode(), "FR", "wd_Q90").decode()
    assert json.loads(new)["html_files"] == [f"world_law/data/FR/{b}/wd_Q90_html.parquet"]
    assert new.endswith("\n") and list(json.loads(new)) == ["place_key", "html_files", "n_shards"]
    recs = [{"repo": "r", "rel": "world_law/data/FR/wd_Q90_html.parquet", "cc": "FR", "place_key": "wd_Q90"},
            {"repo": "r", "rel": "world_law/data/ES/wd_Q1_html.parquet", "cc": "ES", "place_key": "wd_Q1"},
            {"repo": "other", "rel": "world_law/data/FR/wd_Q90_html.parquet", "cc": "FR", "place_key": "wd_Q90"}]
    out, n = MB.rewrite_evicted(recs, "r", {("FR", "wd_Q90")})
    assert n == 1 and out[0]["rel"] == f"world_law/data/FR/{b}/wd_Q90_html.parquet" and out[1] == recs[1] and out[2] == recs[2]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL BUCKET TESTS PASSED")
