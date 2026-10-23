"""Source-policy hold + provenance/override/ordering/sharding tests for run_loop.py (synthetic data in /tmp only).

Run: /workspace/hf-venv/bin/python /workspace/world_law/pipeline/tests/test_hold_policy.py
Never touches /workspace/world_law/{staging,out,held,quarantine,processed,state}; never uploads (--dry-run,
--no-hub-listing, and the repo is forced to a dummy name).
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
PIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPE))
import schema as S  # noqa: E402
import run_loop  # noqa: E402

HELD_CASES = {  # doc_id -> record overrides that MUST be held
    "h_top_unreach": {"source_policy": "robots_unreachable"},
    "h_top_disallow": {"source_policy": "robots_disallowed"},
    "h_upper": {"source_policy": "ROBOTS_UNREACHABLE"},
    "h_hyphen": {"source_policy": "Robots-Disallowed"},
    "h_list": {"source_policy": ["robots_404_allow_rfc9309", "robots_unreachable"]},
    "h_em": {"extra_metadata": {"source_policy": "Robots_Unreachable"}},
    "h_em_str": {"extra_metadata": json.dumps({"source_policy": "robots_disallowed"})},
    "h_bool": {"robots_disallowed": True},
    "h_bool_em": {"extra_metadata": {"robots_disallowed": True}},
    "h_bool_str": {"robots_disallowed": "true"},
}
ALLOWED_CASES = {  # doc_id -> overrides that MUST pass
    "a_none": {},
    "a_noarchive": {"source_policy": "noarchive_meta", "archive_source": "wayback",
                    "archive_url": "https://web.archive.org/web/2024/https://x.example/a"},
    "a_noarchive_live": {"source_policy": "noarchive_meta"},
    "a_archived_disallowed": {"source_policy": "archived_robots_disallowed",
                              "extra_metadata": {"archive": {"archive_source": "wayback", "archive_url": "https://web.archive.org/x",
                                                             "archive_timestamp": "20240101000000", "content_complete": False,
                                                             "possibly_stale": True, "original_url": "https://x.example/b"}},
                              "robots_disallowed": True},   # archive-sourced -> robots flag does not hold it
    "a_404": {"source_policy": "robots_404_allow_rfc9309"},
    "a_404_upper": {"extra_metadata": {"source_policy": "ROBOTS_404_ALLOW_RFC9309"}},
    "a_allowed": {"source_policy": "robots_allowed_rfc9309"},
    "a_bool_false": {"robots_disallowed": False},
    "a_meta_only": {"content_complete": False, "html": None, "text": None,
                    "source_official": False, "source_org": "Some Aggregator", "license_note": "CC-BY 4.0",
                    "raw_path": "/home/box/secret/raw.html"},
}


def base(doc_id, **kw):
    r = {"place_id": "wd:Q1490", "country_code": "JP", "doc_id": doc_id, "source_platform": "jp_test",
         "source_url": f"https://example.jp/{doc_id}", "doc_type": "ordinance", "language": "ja",
         "title_native": f"条例 {doc_id}", "consolidated": True, "content_format": "html",
         "html": f"<p>{doc_id}</p>", "retrieved_at": "2026-10-10T22:00:00Z"}
    r.update(kw)
    return r


def w(path: Path, rows, mtime=1_700_000_000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.utime(path, (mtime, mtime))


def run(tmp: Path, **kw):
    argv = ["--once", "--dry-run", "--no-hub-listing", "--min-age", "0", "--repo", "test/not_a_repo",
            "--staging", str(tmp / "staging"), "--out", str(tmp / "out"), "--state", str(tmp / "state"),
            "--processed", str(tmp / "processed"), "--quarantine", str(tmp / "quarantine"),
            "--held", str(tmp / "held_real"), "--overrides", str(tmp / "overrides.json")]
    for k, v in kw.items():
        argv += [f"--{k}", str(v)]
    assert run_loop.main(argv) == 0
    runs = sorted((tmp / "state").glob("dryrun_*"))
    return runs[-1], json.loads((runs[-1] / "summary.json").read_text())


def read_place(scratch: Path, cc: str, key: str):
    import pyarrow.parquet as pq
    tree = "out_national" if S.is_national_key(key) else "out"   # iso_* places are routed to the national repo
    files = sorted((scratch / tree / S.ROOT / "data" / cc).glob(f"{key}*_html.parquet"))
    rows = []
    for f in files:
        assert pq.read_schema(str(f)).names == S.HTML_COLUMNS
        rows += pq.read_table(str(f)).to_pylist()
    return files, rows


def _tmp():
    d = Path(tempfile.mkdtemp(prefix="wl_hold_test_", dir="/tmp"))
    (d / "overrides.json").write_text(json.dumps({"quarantine": []}))
    return d


# ---------------------------------------------------------------------------
def test_hold_reason_unit():
    for did, kw in HELD_CASES.items():
        assert S.hold_reason(base(did, **kw)), did
    for did, kw in ALLOWED_CASES.items():
        assert S.hold_reason(base(did, **kw)) is None, did


def test_hold_end_to_end():
    tmp = _tmp()
    try:
        rows = [base(d, **kw) for d, kw in {**HELD_CASES, **ALLOWED_CASES}.items()]
        w(tmp / "staging/botx/JP/wd_Q1490.p0001-20261010T2200Z.jsonl", rows)
        # a place where EVERY row is held -> nothing published for it
        w(tmp / "staging/botx/JP/wd_Q99.p0001-20261010T2200Z.jsonl",
          [base("only", place_id="wd:Q99", source_policy="robots_unreachable")])
        scratch, summ = run(tmp)
        files, out_rows = read_place(scratch, "JP", "wd_Q1490")
        ids = {r["doc_id"] for r in out_rows}
        assert ids == set(ALLOWED_CASES), ids ^ set(ALLOWED_CASES)
        assert not ids & set(HELD_CASES)
        assert not list((scratch / "out" / S.ROOT / "data" / "JP").glob("wd_Q99*")), "all-held place written"
        assert not (scratch / "out" / S.ROOT / "metadata" / "JP" / "wd_Q99.json").exists()
        # held files with reasons
        held = [json.loads(l) for f in (scratch / "held" / "botx" / "JP").glob("*.held.jsonl") for l in f.open()]
        assert {h["doc_id"] for h in held} == set(HELD_CASES) | {"only"}
        assert all(h["reason"] and h["record"] for h in held)
        assert not (tmp / "held_real").exists(), "dry-run must not write the real held/ dir"
        # summary counts
        assert summ["rows_held"] == len(HELD_CASES) + 1
        assert summ["held_by_bot_country"] == {"botx/JP": len(HELD_CASES) + 1}
        assert sum(v for k, v in summ["held_by_country_reason"].items() if "robots_unreachable" in k) == 5
        # manifest / card / places never mention held docs or the all-held place
        man = "".join(f.read_text() for f in (scratch / "out" / S.ROOT / "manifests").glob("*.jsonl"))
        card = (scratch / "out" / "README.md").read_text()
        assert "wd_Q99" not in man and "wd_Q99" not in card
        for h in HELD_CASES:
            assert h not in man and h not in card
        # provenance columns survive on passing rows
        by = {r["doc_id"]: r for r in out_rows}
        assert by["a_noarchive"]["source_policy"] == "noarchive_meta"
        assert by["a_noarchive"]["archive_source"] == "wayback"
        assert by["a_404_upper"]["source_policy"] == "robots_404_allow_rfc9309"
        assert by["a_none"]["source_policy"] is None
        ad = by["a_archived_disallowed"]
        assert ad["source_policy"] == "archived_robots_disallowed" and ad["archive_timestamp"] == "20240101000000"
        assert ad["content_complete"] is False and ad["possibly_stale"] is True
        assert ad["original_url"] == "https://x.example/b"
        assert json.loads(ad["extra_metadata"])["robots_disallowed"] is True
        mo = by["a_meta_only"]
        assert mo["content_complete"] is False and mo["html"] is None and mo["source_official"] is False
        assert mo["source_org"] == "Some Aggregator" and mo["license_note"] == "CC-BY 4.0"
        assert all("raw_path" not in (r["extra_metadata"] or "") and "/home/box" not in json.dumps(r)
                   for r in out_rows)
        assert "archived share" in card.lower() or "archived" in card
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_held_removes_older_published_row_and_newer_allow_wins():
    tmp = _tmp()
    try:
        st = tmp / "staging/bot/JP"
        # name timestamps decide the order, NOT mtime (mtimes are deliberately reversed)
        w(st / "wd_Q1490.p0001-20261010T2200Z.jsonl", [base("d1"), base("d2"), base("d3")], mtime=1_700_000_900)
        w(st / "wd_Q1490.p0002-20261010T2300Z.jsonl", [base("d1", source_policy="robots_unreachable"),
                                                         base("d2", source_policy="robots_unreachable")], mtime=1_700_000_500)
        w(st / "wd_Q1490.p0003-20261011T0010Z.jsonl", [base("d2", source_policy="robots_404_allow_rfc9309",
                                                             title_native="new")], mtime=1_700_000_100)
        scratch, summ = run(tmp)
        _, rows = read_place(scratch, "JP", "wd_Q1490")
        by = {r["doc_id"]: r for r in rows}
        assert set(by) == {"d2", "d3"}
        assert by["d2"]["title_native"] == "new" and by["d2"]["source_policy"] == "robots_404_allow_rfc9309"
        assert summ["rows_held"] == 2 and summ["ts_from_name"] == 3
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_full_replaces_place_and_full_all_held_empties_it():
    tmp = _tmp()
    try:
        st = tmp / "staging/bot/JP"
        w(st / "wd_Q1490.p0001-20261010T2200Z.jsonl", [base("a"), base("b")])
        w(st / "wd_Q1490.full.20261010T2300Z.jsonl", [base("c")])
        w(st / "wd_Q7.p0001-20261010T2200Z.jsonl", [base("x", place_id="wd:Q7")])
        w(st / "wd_Q7.full.d1law-robots-unreachable-20261010T2235Z.jsonl",
          [base("x", place_id="wd:Q7", source_policy="robots_unreachable")])
        scratch, summ = run(tmp)
        _, rows = read_place(scratch, "JP", "wd_Q1490")
        assert {r["doc_id"] for r in rows} == {"c"}
        assert not list((scratch / "out" / S.ROOT / "data" / "JP").glob("wd_Q7*"))
        assert summ["docs_dropped_by_full"] == 2  # a, b (x was held, not 'dropped')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_doc_overrides_quarantine():
    tmp = _tmp()
    try:
        (tmp / "overrides.json").write_text(json.dumps({"quarantine": [
            {"country_code": "RU", "place_key": "iso_RU", "doc_id": "ru_pravo_ips:1", "reason": "misfiled regional law under iso:RU"}]}))
        rows = [base("ru_pravo_ips:1", place_id="iso:RU", country_code="RU", language="ru"),
                base("ru_pravo_ips:2", place_id="iso:RU", country_code="RU", language="ru")]
        w(tmp / "staging/national/RU/iso_RU.archive20261011T003234Zp0001.jsonl", rows)
        scratch, summ = run(tmp)
        _, out = read_place(scratch, "RU", "iso_RU")
        assert [r["doc_id"] for r in out] == ["ru_pravo_ips:2"]
        rej = [json.loads(l) for f in (scratch / "quarantine/national/RU").glob("*.rejects.jsonl") for l in f.open()]
        assert rej and "misfiled regional law under iso:RU" in rej[0]["reasons"][0]
        assert summ["rows_quarantined_override"] == 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_sharding_and_stale_shard_deletes():
    tmp = _tmp()
    old = (S.SHARD_MAX_ROWS,)
    try:
        S.SHARD_MAX_ROWS = 4
        # existing published layout: 4 shards for this place + a single-file leftover
        d = tmp / "out" / S.ROOT / "data" / "JP"
        d.mkdir(parents=True)
        from normalize import normalize_record, write_html_parquet
        for i in range(1, 5):
            r, _ = normalize_record(base(f"old{i}"), default_order=i, default_retrieved_at="2026-10-10T00:00:00Z")
            write_html_parquet(d / f"wd_Q1490.s{i:04d}_html.parquet", [r])
        w(tmp / "staging/bot/JP/wd_Q1490.full.20261010T2300Z.jsonl", [base(f"n{i:02d}") for i in range(10)])
        scratch, summ = run(tmp)
        files, rows = read_place(scratch, "JP", "wd_Q1490")
        names = sorted(f.name for f in files)
        assert names == ["wd_Q1490.s0001_html.parquet", "wd_Q1490.s0002_html.parquet", "wd_Q1490.s0003_html.parquet"], names
        assert len(rows) == 10 and {r["doc_id"] for r in rows} == {f"n{i:02d}" for i in range(10)}
        plan = [json.loads(l) for l in (scratch / "planned_commit.jsonl").open()]
        dels = [p["path_in_repo"] for p in plan if p["op"] == "delete"]
        assert dels == [f"{S.ROOT}/data/JP/wd_Q1490.s0004_html.parquet"], dels
        adds_commit = {p["commit"] for p in plan if p["op"] == "add" and "wd_Q1490" in p["path_in_repo"]}
        assert {p["commit"] for p in plan if p["op"] == "delete"} <= adds_commit  # same commit
        meta = json.loads((scratch / "out" / S.ROOT / "metadata/JP/wd_Q1490.json").read_text())
        assert meta["n_shards"] == 3
        assert not (tmp / "out" / S.ROOT / "data/JP/wd_Q1490.s0001_html.parquet").read_bytes() == b""  # real out untouched
        assert (tmp / "out" / S.ROOT / "data/JP/wd_Q1490.s0004_html.parquet").exists()
        for f in files:
            assert S.is_place_data_file(f"{S.ROOT}/data/JP/{f.name}", "JP", "wd_Q1490")
    finally:
        S.SHARD_MAX_ROWS = old[0]
        shutil.rmtree(tmp, ignore_errors=True)


def test_batch_order_parser():
    o = run_loop.batch_order
    assert o(".archive20261011T003234Zp0001", 0, "x")[0] > o(".20261010T2200Z", 0, "y")[0]
    assert o(".full.archive-policy20261011T021231Z", 0, "x")[4] == "name"
    assert o(".pldz_LD_b00001", 123.0, "x")[:2] == (123.0, 1)
    assert o(".caceres-p00012-20261010T101010Z", 0, "x")[1] == 12


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
            n += 1
    print(f"ALL {n} HOLD-POLICY TESTS PASSED")
