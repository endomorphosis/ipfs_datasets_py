"""Tar-shard upload mode of tools/upload_pdfs.py (+ tools/pdf_shards.py, world_law_loader.fetch_pdf): per-country
shards, place_key ordering, path format, per-CC seq continuity across batches and retries, late-landed commits,
ref round-trip, dedupe against published loose files, the missing-but-verified retry fix, and a loader byte-range
read against a local tar (mocked HTTP Range). Synthetic data in /tmp; fake Hub API (no network, no uploads).

Run: /workspace/hf-venv/bin/python /workspace/world_law/pipeline/tests/test_pdf_shards.py
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import hashlib
import io
import json
import re
import sys
import tarfile
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "tools"))
import pyarrow.parquet as pq  # noqa: E402
import schema as S  # noqa: E402
import upload_pdfs as U  # noqa: E402
import pdf_shards as PS  # noqa: E402
import world_law_loader as WLL  # noqa: E402
from test_pdfs import stage_doc, write_batch  # noqa: E402

U.time.sleep = lambda s: None          # commit retry back-off
U.ensure_gitattributes = lambda api, repo: None   # guard covered by test_pdfs
YM = "2026/10"


class BlobApi:
    """Fake Hub keeping file bytes; fail_commits: raise for the next N commits (fail_land=True: the commit still
    lands, i.e. a client-side timeout of a commit that completed server-side)."""
    def __init__(self):
        self.blobs, self.commits, self.fail_commits, self.fail_land = {}, [], 0, False

    def create_commit(self, repo_id, repo_type, operations, commit_message):
        assert repo_id not in U.FORBIDDEN
        if self.fail_commits:
            self.fail_commits -= 1
            if self.fail_land:
                for op in operations:
                    src = op.path_or_fileobj
                    self.blobs[op.path_in_repo] = src if isinstance(src, bytes) else Path(src).read_bytes()
            raise RuntimeError("403 storage quota exceeded")
        for op in operations:
            src = op.path_or_fileobj
            self.blobs[op.path_in_repo] = src if isinstance(src, bytes) else Path(src).read_bytes()
        oid = f"c{len(self.commits) + 1:04d}"
        self.commits.append((oid, commit_message, [o.path_in_repo for o in operations]))
        return SimpleNamespace(oid=oid)

    def get_paths_info(self, repo, paths, repo_type, expand):
        return [SimpleNamespace(path=p, lfs=SimpleNamespace(sha256=hashlib.sha256(self.blobs[p]).hexdigest()))
                for p in paths if p in self.blobs]


def args_for(tmp, mode="tar"):
    return SimpleNamespace(staging=str(tmp / "staging/pdf"), state=str(tmp / "state"), base=str(tmp),
                           held=str(tmp / "held"), repo="test/pdfs", dry_run=False, shard_mode=mode,
                           commit_max_bytes=U.COMMIT_MAX_BYTES, commit_max_files=100, commit_timeout=0)


def run(api, tmp, mode="tar"):
    a = args_for(tmp, mode)
    led = U.load_ledger(tmp / "state/pdf_ledger.jsonl")
    return [U.process_batch(api, a, b, led, set()) for b in U.ready_batches(Path(a.staging))]


def big(tag, n):
    return b"%PDF-1.4\n" + tag.encode() + b"\n" + bytes([len(tag) % 251]) * n


def test_grouping_and_reserve():
    items = [{"cc": cc, "place_key": pk, "sha256": f"{i:064x}", "bytes": b}
             for i, (cc, pk, b) in enumerate([("PH", "wd_Q9", 400), ("AR", "wd_Q5", 10), ("PH", "wd_Q1", 400),
                                              ("PH", "wd_Q1", 400), ("AR", "wd_Q2", 10)])]
    g = PS.group_country_shards(items, target=1000)
    assert [cc for cc, _ in g] == ["AR", "PH", "PH"]
    assert all(len({i["cc"] for i in grp}) == 1 for _, grp in g)
    flat = [(i["place_key"], i["sha256"]) for cc, grp in g if cc == "PH" for i in grp]
    assert flat == sorted(flat) and [len(grp) for _, grp in g] == [2, 2, 1]
    assert PS.shard_path("ph", 7, YM) == "shards/PH/2026/10/PH_000007.tar"
    st = Path(tempfile.mkdtemp())
    p1 = PS.reserve(st, "batch_0001", items, YM, target=1000)
    assert [p["shard_path"] for p in p1] == ["shards/AR/2026/10/AR_000001.tar", "shards/PH/2026/10/PH_000001.tar",
                                             "shards/PH/2026/10/PH_000002.tar"]
    assert p1[0]["members"][0]["member"] == "wd_Q2/" + f"{4:064x}.pdf"
    again = PS.reserve(st, "batch_0001", items, YM, target=1000)          # retry: same names, counter unchanged
    assert [p["shard_path"] for p in again] == [p["shard_path"] for p in p1]
    assert PS.load_state(st)["seq"] == {"AR": 1, "PH": 2}
    p2 = PS.reserve(st, "batch_0002", [{"cc": "PH", "place_key": "wd_Q3", "sha256": "f" * 64, "bytes": 5}], "2026/11")
    assert [p["shard_path"] for p in p2] == ["shards/PH/2026/11/PH_000003.tar"]     # continues across batches
    p1b = PS.reserve(st, "batch_0001", items + [{"cc": "AR", "place_key": "wd_Q7", "sha256": "e" * 64, "bytes": 5}], YM)
    assert p1b[-1]["shard_path"] == "shards/AR/2026/10/AR_000002.tar" and len(p1b) == 4   # new item -> next seq
    print("ok grouping / reserve / seq continuity")


def test_ref_roundtrip_and_tar():
    tmp = Path(tempfile.mkdtemp())
    mem = []
    for i, n in enumerate([10, 700, 4096 * 3 + 7]):
        b = big(f"r{i}", n)
        h = hashlib.sha256(b).hexdigest()
        (tmp / f"{i}.pdf").write_bytes(b)
        mem.append({"member": f"wd_Q{i}/{h}.pdf", "sha256": h, "local": tmp / f"{i}.pdf"})
    sp = PS.shard_path("AR", 1, YM)
    info = PS.write_shard(tmp / sp, mem)
    info2 = PS.write_shard(tmp / "again.tar", mem)
    assert info["sha256"] == info2["sha256"]                  # deterministic bytes (retries rebuild identically)
    with open(tmp / sp, "rb") as f:
        for m, e in zip(mem, info["index"]):
            ref = PS.shard_ref("endomorphosis/world_law_scanned_pdfs", sp, e["member"], e["offset"], e["size"], e["sha256"])
            r = PS.parse_ref(ref)
            w = WLL.parse_pdf_ref_full(ref)
            assert r["path"] == w["path"] == sp and r["member"] == w["member"] == m["member"]
            assert (r["offset"], r["size"], r["sha256"]) == (w["offset"], w["size"], w["sha256"]) == (e["offset"], e["size"], m["sha256"])
            assert PS.read_member(f, r["offset"], r["size"], r["sha256"]) == m["local"].read_bytes()
    with tarfile.open(tmp / sp) as tf:
        assert tf.getnames() == [m["member"] for m in mem]
    loose = S.pdf_ref("pdfs/AE/wd_Q1/" + "a" * 64 + ".pdf")
    assert WLL.parse_pdf_ref(loose) == (S.PDF_REPO_ID, "pdfs/AE/wd_Q1/" + "a" * 64 + ".pdf")
    assert WLL.parse_pdf_ref_full(loose)["sha256"] == "a" * 64
    print("ok ref round-trip + deterministic tar")


def test_loader_range_read():
    tmp = Path(tempfile.mkdtemp())
    b = big("loader", 5000)
    h = hashlib.sha256(b).hexdigest()
    (tmp / "x.pdf").write_bytes(b)
    sp = PS.shard_path("PH", 1, YM)
    info = PS.write_shard(tmp / sp, [{"member": f"wd_Q1/{h}.pdf", "sha256": h, "local": tmp / "x.pdf"},
                                     {"member": f"wd_Q2/{'0' * 64}.pdf", "sha256": hashlib.sha256(b"%PDF-z").hexdigest(),
                                      "local": (tmp / "z.pdf", (tmp / "z.pdf").write_bytes(b"%PDF-z"))[0]}])
    e = info["index"][0]
    ref = PS.shard_ref(S.PDF_REPO_ID, sp, e["member"], e["offset"], e["size"], e["sha256"])
    tar = (tmp / sp).read_bytes()
    seen = []

    def fake_get(url, headers=None, timeout=None, allow_redirects=True):
        seen.append((url, headers))
        a, z = map(int, re.match(r"bytes=(\d+)-(\d+)", headers["Range"]).groups())
        return SimpleNamespace(status_code=206, content=tar[a:z + 1])
    import requests
    orig = requests.get
    requests.get = fake_get
    try:
        assert WLL.fetch_pdf_bytes(ref, token="t0k") == b
        url, hd = seen[-1]
        assert sp in url and "world_law_scanned_pdfs" in url and hd["Authorization"] == "Bearer t0k"
        assert hd["Range"] == f"bytes={e['offset']}-{e['offset'] + e['size'] - 1}"
        local = WLL.fetch_pdf({"pdf_ref": ref, "sha256": h}, cache_dir=str(tmp / "cache"))
        assert Path(local).read_bytes() == b and Path(local).name == f"{h}.pdf"
        bad = ref.replace(f"sha256={h}", "sha256=" + "0" * 64)
        try:
            WLL.fetch_pdf_bytes(bad); assert False
        except IOError:
            pass
        assert WLL.fetch_pdf_bytes(ref, repo_id="mirror/pdfs") == b and "mirror/pdfs" in seen[-1][0]
    finally:
        requests.get = orig
    print("ok loader HTTP Range read (mocked) + sha256 check")


def test_process_batch_tar():
    tmp = Path(tempfile.mkdtemp(prefix="pdfshard_e2e_"))
    stage, state = tmp / "staging/pdf", tmp / "state"
    state.mkdir(parents=True)
    # an already-published loose PDF (and its ledger row) - a new record with the same bytes must reuse it
    old = big("old-loose", 300)
    old_sha = hashlib.sha256(old).hexdigest()
    old_path = S.pdf_path("PH", "wd_Q1", old_sha)
    U.append_jsonl(state / "pdf_ledger.jsonl", {"path_in_repo": old_path, "sha256": old_sha, "verified": True,
                                                "commit": "c0000"})
    # a verified loose PDF whose staged copy was already deleted (retry fix)
    gone = big("gone", 50)
    gone_sha = hashlib.sha256(gone).hexdigest()
    U.append_jsonl(state / "pdf_ledger.jsonl", {"path_in_repo": S.pdf_path("BR", "wd_Q7", gone_sha), "sha256": gone_sha,
                                                "verified": True, "commit": "c0001"})
    recs = [stage_doc(stage, "doc:p2", "wd:Q2", "PH", data=big("p2", 200)),
            stage_doc(stage, "doc:p1", "wd:Q1", "PH", data=big("p1", 100)),
            stage_doc(stage, "doc:p1dup", "wd:Q1", "PH", data=big("p1", 100)),
            stage_doc(stage, "doc:a1", "wd:Q5", "AR", data=big("a1", 100)),
            stage_doc(stage, "doc:reuse", "wd:Q3", "PH", data=old),
            stage_doc(stage, "doc:gone", "wd:Q7", "BR", data=gone),
            stage_doc(stage, "doc:lost", "wd:Q8", "BR", data=big("lost", 10))]
    (stage / "BR/wd_Q7/doc_gone.pdf").unlink()
    (stage / "BR/wd_Q8/doc_lost.pdf").unlink()
    write_batch(stage, 1, recs)
    api = BlobApi()
    api.fail_commits = 3                                  # quota error: every attempt of the first run fails
    r1 = run(api, tmp)[0]
    assert r1["incomplete"] and not any(k.startswith("shards/") for k in api.blobs) and r1["recovered_missing"] == 1
    st = PS.load_state(state)
    names1 = [p["shard_path"] for p in st["batches"]["batch_0001"]]
    assert len(names1) == 2 and all(re.match(r"^shards/(AR|PH)/\d{4}/\d{2}/\1_000001\.tar$", n) for n in names1), names1
    assert not (stage / "_shards").exists()                # local tars cleaned up
    r2 = run(api, tmp)[0]                                  # retry after "storage clears": same names, no new seq
    assert not r2.get("incomplete"), r2
    assert sorted(r2["shards"]) == sorted(names1) and PS.load_state(state)["seq"] == {"AR": 1, "PH": 1}
    assert {k for k in api.blobs if k.startswith("shards/")} == set(names1)
    m = {r["doc_id"]: r for r in pq.read_table(str(state / "pdf_manifest.parquet")).to_pylist()}
    for col in ("shard_path", "member", "offset", "size"):
        assert col in m["doc:p1"]
    ph = m["doc:p1"]
    assert ph["shard_path"].startswith("shards/PH/") and ph["member"] == f"wd_Q1/{ph['sha256']}.pdf"
    assert ph["pdf_path"] == ph["shard_path"] and ph["pdf_ref"].startswith(f"{S.PDF_REPO_ID}:{ph['shard_path']}#member=")
    assert m["doc:p1dup"]["pdf_ref"] == ph["pdf_ref"]                       # in-batch duplicate packed once
    with tarfile.open(fileobj=io.BytesIO(api.blobs[ph["shard_path"]])) as tf:
        names = tf.getnames()
    assert names == sorted(names) and len(names) == 2 and all(n.startswith(("wd_Q1/", "wd_Q2/")) for n in names)
    blob = api.blobs[ph["shard_path"]]
    for d in ("doc:p1", "doc:p2", "doc:a1"):
        r = PS.parse_ref(m[d]["pdf_ref"])
        assert hashlib.sha256(blob if False else api.blobs[r["path"]][r["offset"]:r["offset"] + r["size"]]).hexdigest() == m[d]["sha256"]
    assert m["doc:reuse"]["pdf_ref"] == S.pdf_ref(old_path) and m["doc:reuse"]["shard_path"] is None   # loose kept
    assert m["doc:gone"]["pdf_ref"].startswith(f"{S.PDF_REPO_ID}:pdfs/BR/wd_Q7/") and m["doc:gone"]["member"] is None
    assert "doc:lost" not in m and any(s["reason"].startswith("missing_file") for s in r2["skipped"])
    refs = json.loads((state / "pdf_refs/PH/wd_Q1.json").read_text())
    assert refs["doc:p1"] == ph["pdf_ref"]                 # what run_loop backfills into the law rows
    led = U.load_ledger(state / "pdf_ledger.jsonl")
    assert U.ledger_key(ph["shard_path"], ph["member"]) in led
    # next batch: same bytes as an already sharded PDF -> reuses the shard ref; new PDF -> PH_000002
    recs2 = [stage_doc(stage, "doc:again", "wd:Q4", "PH", data=big("p2", 200)),
             stage_doc(stage, "doc:new", "wd:Q4", "PH", data=big("new", 30))]
    write_batch(stage, 2, recs2)
    r3 = run(api, tmp)[0]
    m = {r["doc_id"]: r for r in pq.read_table(str(state / "pdf_manifest.parquet")).to_pylist()}
    assert m["doc:again"]["pdf_ref"] == m["doc:p2"]["pdf_ref"]
    assert m["doc:new"]["shard_path"].endswith("/PH_000002.tar") and r3["shards"] == [m["doc:new"]["shard_path"]]
    # old loose rows (written before sharding) keep null shard_* columns
    assert m["doc:reuse"]["offset"] is None and m["doc:reuse"]["size"] is None
    print("ok process_batch tar mode: retry reuses names, dedupe, missing-but-verified, manifest + refs")


def test_late_landed_commit():
    tmp = Path(tempfile.mkdtemp(prefix="pdfshard_late_"))
    stage = tmp / "staging/pdf"
    write_batch(stage, 1, [stage_doc(stage, "doc:x", "wd:Q1", "PH", data=big("x", 64))])
    api = BlobApi()
    api.fail_commits, api.fail_land = 3, True               # commits "time out" but land server-side
    r1 = run(api, tmp)[0]
    assert not r1.get("incomplete")                          # verified by sha256 on the Hub anyway
    assert PS.load_state(tmp / "state")["seq"] == {"PH": 1}
    print("ok late-landed commit accepted by Hub sha256")


def test_loose_fallback_and_cli_default():
    tmp = Path(tempfile.mkdtemp(prefix="pdfshard_loose_"))
    stage = tmp / "staging/pdf"
    write_batch(stage, 1, [stage_doc(stage, "doc:x", "wd:Q1", "PH", data=big("x", 64))])
    api = BlobApi()
    r = run(api, tmp, mode="loose")[0]
    assert r["shard_mode"] == "loose" and all(p.startswith("pdfs/PH/wd_Q1/") for p in api.blobs if p.endswith((".pdf", ".tar")))
    m = pq.read_table(str(tmp / "state/pdf_manifest.parquet")).to_pylist()[0]
    assert m["shard_path"] is None and m["pdf_ref"] == S.pdf_ref(m["pdf_path"])
    # loose-mode retry fix too
    tmp2 = Path(tempfile.mkdtemp(prefix="pdfshard_loose2_"))
    st2 = tmp2 / "stage"
    rec = stage_doc(tmp2 / "staging/pdf", "doc:y", "wd:Q1", "PH", data=big("y", 64))
    (tmp2 / "staging/pdf/PH/wd_Q1/doc_y.pdf").unlink()
    U.append_jsonl(tmp2 / "state/pdf_ledger.jsonl", {"path_in_repo": S.pdf_path("PH", "wd_Q1", rec["sha256"]),
                                                     "sha256": rec["sha256"], "verified": True, "commit": "c9"})
    write_batch(tmp2 / "staging/pdf", 1, [rec])
    r = run(BlobApi(), tmp2, mode="loose")[0]
    assert not r.get("incomplete") and r["recovered_missing"] == 1 and not r["skipped"]
    assert (tmp2 / "staging/pdf/_manifest/batch_0001.pushed").exists()
    import argparse  # noqa: F401
    assert U.DEFAULT_SHARD_MODE == "tar"
    assert "*.tar filter=lfs diff=lfs merge=lfs -text" in U.compact_gitattributes("")
    print("ok loose fallback, loose retry fix, CLI default tar")


if __name__ == "__main__":
    test_grouping_and_reserve()
    test_ref_roundtrip_and_tar()
    test_loader_range_read()
    test_process_batch_tar()
    test_late_landed_commit()
    test_loose_fallback_and_cli_default()
    print("ALL OK test_pdf_shards")
