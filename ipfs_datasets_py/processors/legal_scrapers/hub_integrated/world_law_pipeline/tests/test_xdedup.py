"""NEW-row duplicate checks (xdedup.py / dedup_index.py): old-repo URL index, cross-place pointer rows,
published rows never rewritten.  Synthetic data in /tmp only; dry-run, dummy repos, temp index dir.

Run: /workspace/hf-venv/bin/python /workspace/world_law/pipeline/tests/test_xdedup.py
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

TXT = "§ 1 Geltungsbereich. Diese Satzung gilt für das gesamte Gebiet des Amtes und seiner Gemeinden. " * 5


def _db(tmp, old=(), pu=(), ph=()):
    d = tmp / "dedupdir"
    c = DX.create_db(d / "old_urls.sqlite", ["CREATE TABLE u(url TEXT PRIMARY KEY, repo TEXT) WITHOUT ROWID"])
    c.executemany("INSERT INTO u VALUES(?,?)", [(DX.norm_url(u), r) for u, r in old]); c.commit(); c.close()
    c = DX.create_db(d / "mun_published.sqlite", ["CREATE TABLE pu(url TEXT PRIMARY KEY, ref TEXT) WITHOUT ROWID",
                                                  "CREATE TABLE ph(th TEXT PRIMARY KEY, ref TEXT) WITHOUT ROWID"])
    c.executemany("INSERT INTO pu VALUES(?,?)", [(DX.norm_url(u), r) for u, r in pu])
    c.executemany("INSERT INTO ph VALUES(?,?)", list(ph)); c.commit(); c.close()
    return d


def test_norm_url():
    n = DX.norm_url
    assert n("HTTPS://WWW.Example.COM/a/b/?utm_source=x&b=2&a=1#frag") == "example.com/a/b?a=1&b=2"
    assert n("http://example.com:80/a/") == n("https://example.com/a") == "example.com/a"
    assert n("https://example.com/A") != n("https://example.com/a")          # path case kept
    assert n("https://x.de/s;jsessionid=ABC?fbclid=1&id=7") == "x.de/s?id=7"
    assert n("https://x.de/a%20b") == n("https://x.de/a b")
    assert n("https://huggingface.co/datasets/endomorphosis/ipfs_x_laws") is None
    assert n("https://web.archive.org/web/20260831093624/https://www.planalto.gov.br/a.htm") == "planalto.gov.br/a.htm"
    assert n("http://web.archive.org/web/2020id_/http:/x.de/a/") == "x.de/a"
    assert n(None) is None and n("mailto:a@b") is None and n("") is None
    assert DX.repo_slug("endomorphosis/ipfs_dominican_republic_laws") == DX.repo_slug("endomorphosis/ipfs_dominicanrepublic_laws")


def test_apply_pointer_modes():
    row = {"doc_id": "a", "text": "t", "source_policy": "noarchive_meta", "extra_metadata": json.dumps({"k": 1})}
    r = XD.apply_pointer(dict(row), "endomorphosis/ipfs_x_laws", "old_repo", "source_url", "pointer")
    em = json.loads(r["extra_metadata"])
    assert r["text"] is None and r["content_complete"] is False and em["k"] == 1
    assert em["duplicate_of"] == "endomorphosis/ipfs_x_laws" and r["source_policy"] == "noarchive_meta;duplicate_pointer"
    t = XD.apply_pointer(dict(row), "x", "old_repo", "source_url", "tag")
    assert t["text"] == "t" and "duplicate_pointer" in t["source_policy"]
    assert XD.apply_pointer(dict(row), "x", "old_repo", "source_url", "skip") is None


def test_old_repo_self_excluded():
    tmp = _tmp()
    try:
        d = _db(tmp, old=[("https://a.example/1", "endomorphosis/ipfs_dominican_republic_laws")])
        chk = XD.OldRepoCheck(d / "old_urls.sqlite")
        assert chk.match({"source_url": "http://www.a.example/1/"}) == "endomorphosis/ipfs_dominican_republic_laws"
        assert chk.match({"source_url": "https://a.example/1", "hf_dataset": "endomorphosis/ipfs_dominicanrepublic_laws"}) is None
        assert chk.match({"source_url": "https://a.example/2"}) is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_plan_published_and_amt_rules():
    tmp = _tmp()
    try:
        d = _db(tmp, pu=[("https://pub.example/x", "DE/wd_Q1/pubdoc")])
        st = tmp / "s"
        files = []
        def add(cc, key, rows):
            p = st / f"{key}.jsonl"; w(p, rows); files.append((cc, key, p))
        # new copy of a published URL in another place -> pointer to the published ref
        add("DE", "wd_Q2", [base("n1", place_id="wd:Q2", country_code="DE", source_url="https://pub.example/x/")])
        # same text on a member Gemeinde and on the Amt -> Amt is canonical
        add("DE", "wd_Q10", [base("g1", place_id="wd:Q10", country_code="DE", place_name="Gemeinde Musterdorf",
                                  text=TXT, html=None, source_url="https://gemeinde.example/s")])
        add("DE", "wd_Q11", [base("a1", place_id="wd:Q11", country_code="DE", place_name="Amt Musterland",
                                  text=TXT, html=None, source_url="https://amt.example/s")])
        # PT gazette item mentioned by two municipalities -> lands on the issuer named in the title
        u = "https://diariodarepublica.pt/dr/detalhe/aviso/123-2024-1"
        add("PT", "wd_Q20", [base("p1", place_id="wd:Q20", country_code="PT", place_name="Lisboa", source_url=u,
                                  title_native="Aviso n.º 1/2024 - Município de Sintra")])
        add("PT", "wd_Q21", [base("p2", place_id="wd:Q21", country_code="PT", place_name="Município de Sintra",
                                  source_url=u, title_native="Aviso n.º 1/2024 - Município de Sintra")])
        from run_loop import _iter_staged_tolerant
        pub = DX.PubIndex(d / "mun_published.sqlite")
        plan = XD.plan_cross_place(files, _iter_staged_tolerant, pub)
        assert plan[("DE", "wd_Q2")]["n1"] == {"duplicate_of": "DE/wd_Q1/pubdoc", "duplicate_key": "source_url"}
        assert plan[("DE", "wd_Q10")]["g1"]["duplicate_of"] == "DE/wd_Q11/a1"
        assert ("DE", "wd_Q11") not in plan
        assert plan[("PT", "wd_Q20")]["p1"]["duplicate_of"] == "PT/wd_Q21/p2" and ("PT", "wd_Q21") not in plan
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_run_loop_pointer_rows_end_to_end():
    tmp = _tmp()
    old_dir = DX.STATE_DIR
    try:
        d = _db(tmp, old=[("https://old.example/law/1", "endomorphosis/ipfs_germany_municipal_laws")])
        DX.STATE_DIR = d
        (d / "config.json").write_text(json.dumps({"old_repo": "pointer", "cross_place": "pointer"}))
        mk = lambda did, pid, **kw: base(did, place_id=pid, country_code="DE", language="de", **kw)  # noqa: E731
        w(tmp / "staging/web/DE/wd_Q11.jsonl", [mk("a1", "wd:Q11", place_name="Amt Musterland", text=TXT, html=None,
                                                    source_url="https://amt.example/s"),
                                                 mk("o1", "wd:Q11", place_name="Amt Musterland",
                                                    source_url="http://www.old.example/law/1/?utm_source=t")])
        w(tmp / "staging/web/DE/wd_Q10.jsonl", [mk("g1", "wd:Q10", place_name="Musterdorf", text=TXT, html=None,
                                                    source_url="https://gemeinde.example/s"),
                                                 mk("k1", "wd:Q10", place_name="Musterdorf")])
        scratch, summ = run(tmp, **{"national-repo": "test/nat"})
        rows = {}
        for p in (scratch / "out" / S.ROOT / "data/DE").rglob("*_html.parquet"):
            for r in pq.read_table(p).to_pylist():
                rows[r["doc_id"]] = r
        assert rows["a1"]["text"] and "duplicate_pointer" not in (rows["a1"]["source_policy"] or "")
        assert rows["g1"]["text"] is None and json.loads(rows["g1"]["extra_metadata"])["duplicate_of"].startswith("DE/wd_Q11/")
        assert rows["o1"]["text"] is None and json.loads(rows["o1"]["extra_metadata"])["duplicate_of"] == \
            "endomorphosis/ipfs_germany_municipal_laws"
        assert rows["k1"]["text"] and rows["k1"]["source_policy"] in (None, "")
        assert summ.get("xdedup_old_repo_pointer") == 1 and summ.get("xdedup_cross_place_pointer") == 1, summ
        logs = list(scratch.rglob("*.pointers.jsonl"))
        assert sum(len(p.read_text().splitlines()) for p in logs) == 2
    finally:
        DX.STATE_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_published_doc_never_rewritten():
    """A staged update of an already-published doc_id is not pointer-tagged even if its URL is in an old repo."""
    tmp = _tmp()
    old_dir = DX.STATE_DIR
    try:
        d = _db(tmp, old=[("https://old.example/2", "endomorphosis/ipfs_japan_municipal_laws")])
        DX.STATE_DIR = d
        w(tmp / "staging/web/JP/wd_Q1490.jsonl", [base("e1", source_url="https://example.jp/e1")])
        run(tmp, **{"national-repo": "test/nat"})
        # publish e1 into the real-looking out tree, then restage it with an old-repo URL
        sc = sorted((tmp / "state").glob("dryrun_*"))[-1]
        tmp2 = tmp / "second"
        shutil.copytree(sc / "out", tmp2 / "out")
        w(tmp2 / "staging/web/JP/wd_Q1490.20261019T000000Zp0001.jsonl",
          [base("e1", source_url="https://old.example/2"), base("e2", source_url="https://old.example/2")])
        scratch, summ = run(tmp2, **{"national-repo": "test/nat"})
        rows = {r["doc_id"]: r for p in (scratch / "out" / S.ROOT / "data/JP").rglob("*_html.parquet")
                for r in pq.read_table(p).to_pylist()}
        assert rows["e1"]["text"] and "duplicate_pointer" not in (rows["e1"]["source_policy"] or "")
        assert rows["e2"]["text"] is None
    finally:
        DX.STATE_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
