"""Scanned-PDF lane: staging contract, upload/verify/ledger/idempotency, hold policy, pdf_ref in run_loop,
loader helpers. Synthetic data in /tmp only; the Hub is a fake API (no network, no uploads).

Run: /workspace/hf-venv/bin/python /workspace/world_law/pipeline/tests/test_pdfs.py
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "tools"))
import schema as S  # noqa: E402
import upload_pdfs as U  # noqa: E402
import run_loop  # noqa: E402
import world_law_loader as WLL  # noqa: E402
from test_hold_policy import base, read_place, w  # noqa: E402
from test_hold_policy import run as _run  # noqa: E402


class FakeApi:
    def __init__(self, corrupt=()):
        self.files, self.commits, self.corrupt = {}, [], set(corrupt)

    def create_commit(self, repo_id, repo_type, operations, commit_message):
        assert repo_id not in U.FORBIDDEN
        for op in operations:
            src = op.path_or_fileobj
            data = src if isinstance(src, (bytes, bytearray)) else Path(src).read_bytes()
            self.files[op.path_in_repo] = hashlib.sha256(data).hexdigest()
        oid = f"c{len(self.commits) + 1:04d}"
        self.commits.append((oid, commit_message, [o.path_in_repo for o in operations]))
        return SimpleNamespace(oid=oid)

    def get_paths_info(self, repo, paths, repo_type, expand):
        return [SimpleNamespace(path=p, lfs=SimpleNamespace(sha256="0" * 64 if p in self.corrupt else self.files[p]))
                for p in paths if p in self.files]


def pdf_bytes(tag):
    return b"%PDF-1.4\n% scanned " + tag.encode() + b"\n%%EOF\n"


def stage_doc(stage, doc_id, place_id, cc, policy="noarchive_meta;content_signal_ai_train_no", data=None, **kw):
    pk = S.place_key(place_id, None, cc)
    data = data if data is not None else pdf_bytes(doc_id)
    p = stage / cc / pk / f"{U.sanitize_doc_id(doc_id)}.pdf"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    rec = {"doc_id": doc_id, "place_id": place_id, "place_key": pk, "country_code": cc,
           "source_url": f"https://example.org/{doc_id}", "sha256": hashlib.sha256(data).hexdigest(),
           "bytes": len(data), "fetched_at": "2026-10-14T10:00:00Z", "source_policy": policy, "lane": "live"}
    rec.update(kw)
    return rec


def write_batch(stage, n, recs, ready=True):
    md = stage / "_manifest"
    md.mkdir(parents=True, exist_ok=True)
    (md / f"batch_{n:04d}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
    if ready:
        (md / f"batch_{n:04d}.ready").write_text("")


def args_for(tmp):
    return SimpleNamespace(staging=str(tmp / "staging/pdf"), state=str(tmp / "state"), base=str(tmp),
                           held=str(tmp / "held"), repo="test/pdfs", dry_run=False,
                           commit_max_bytes=U.COMMIT_MAX_BYTES, commit_max_files=2)


def run_batches(api, tmp):
    a = args_for(tmp)
    led = U.load_ledger(tmp / "state/pdf_ledger.jsonl")
    return [U.process_batch(api, a, b, led, set()) for b in U.ready_batches(Path(a.staging))]


def test_paths_and_sanitize():
    assert U.sanitize_doc_id("eli:fr/loi/2019:7") == "eli_fr_loi_2019_7"
    sha = "ab" * 32
    assert S.pdf_path("PH", "wd_Q1", sha) == f"pdfs/PH/wd_Q1/{sha}.pdf"
    b = S.place_bucket("wd_Q90")
    assert S.pdf_path("FR", "wd_Q90", sha) == f"pdfs/FR/{b}/wd_Q90/{sha}.pdf"
    assert S.pdf_path("FR", "iso_FR", sha) == f"pdfs/FR/iso_FR/{sha}.pdf"  # national never bucketed
    assert S.pdf_path("PH", "wd_Q1", sha, split=True) == f"pdfs/PH/wd_Q1/ab/{sha}.pdf"
    assert WLL.parse_pdf_ref(S.pdf_ref(f"pdfs/PH/wd_Q1/{sha}.pdf")) == (S.PDF_REPO_ID, f"pdfs/PH/wd_Q1/{sha}.pdf")
    assert U.is_ignored("_x") and U.is_ignored(".y") and U.is_ignored("a.pdf.tmp") and not U.is_ignored("a.pdf")


def test_upload_verify_hold_idempotent():
    tmp = Path(tempfile.mkdtemp(prefix="wl_pdf_test_", dir="/tmp"))
    try:
        stage = tmp / "staging/pdf"
        recs = [stage_doc(stage, "doc:1", "wd:Q1", "PH"), stage_doc(stage, "doc/2", "wd:Q1", "PH"),
                stage_doc(stage, "a3", "wd:Q90", "FR", lane="archive"),
                stage_doc(stage, "held1", "wd:Q1", "PH", policy="robots_unreachable"),
                stage_doc(stage, "held2", "wd:Q1", "PH", policy=None, robots_disallowed=True),
                stage_doc(stage, "badsha", "wd:Q1", "PH", sha256="f" * 64),
                {"doc_id": "nofile", "place_id": "wd:Q5", "place_key": "wd_Q5", "country_code": "PH",
                 "source_url": "u", "sha256": "e" * 64, "bytes": 3, "fetched_at": "x", "source_policy": None,
                 "lane": "live"}]
        write_batch(stage, 1, recs)
        write_batch(stage, 2, [stage_doc(stage, "later", "wd:Q1", "PH")], ready=False)  # not ready -> untouched
        (stage / "PH/wd_Q1/_partial.pdf").write_bytes(b"x")
        api = FakeApi()
        reps = run_batches(api, tmp)
        assert len(reps) == 1
        r = reps[0]
        assert r["uploaded"] == 3 and r["verified"] == 3 and not r.get("incomplete")
        assert len(r["commits"]) == 2  # commit_max_files=2 -> 2 data commits (+ 1 manifest commit)
        assert sorted(h["doc_id"] for h in r["held"]) == ["held1", "held2"]
        assert sorted(s["doc_id"] for s in r["skipped"]) == ["badsha", "nofile"]
        pushed = json.loads((stage / "_manifest/batch_0001.pushed").read_text())
        assert pushed["manifest_commit"] and pushed["commits"] == r["commits"]
        assert (stage / "_manifest/batch_0001.jsonl").exists()          # manifest jsonl kept
        assert not (stage / "PH/wd_Q1/doc_1.pdf").exists()              # verified -> deleted
        assert (stage / "PH/wd_Q1/badsha.pdf").exists()                 # not verified -> kept
        assert (stage / "PH/wd_Q1/_partial.pdf").exists() and (stage / "PH/wd_Q1/later.pdf").exists()
        assert (tmp / "held/pdf/PH/wd_Q1/held1.pdf").exists()           # held locally, never uploaded
        assert not any("held" in p for p in api.files)
        b = S.place_bucket("wd_Q90")
        assert any(p.startswith(f"pdfs/FR/{b}/wd_Q90/") for p in api.files)
        assert "manifest.parquet" in api.files and "README.md" in api.files
        import pyarrow.parquet as pq
        m = pq.read_table(str(tmp / "state/pdf_manifest.parquet"))
        need = ["doc_id", "place_id", "country_code", "source_url", "sha256", "bytes", "fetched_at",
                "source_policy", "lane", "law_repo", "law_path"]
        assert all(c in m.column_names for c in need)
        rows = {x["doc_id"]: x for x in m.to_pylist()}
        assert set(rows) == {"doc:1", "doc/2", "a3"}
        assert rows["doc:1"]["source_policy"] == "noarchive_meta;content_signal_ai_train_no"
        assert rows["a3"]["lane"] == "archive" and rows["doc:1"]["law_repo"] is None
        refs = json.loads((tmp / "state/pdf_refs/PH/wd_Q1.json").read_text())
        assert refs["doc:1"].startswith(S.PDF_REPO_ID + ":pdfs/PH/wd_Q1/")
        led = [json.loads(l) for l in (tmp / "state/pdf_ledger.jsonl").read_text().splitlines()]
        assert len(led) == 3 and all(x["verified"] for x in led)
        # rerun: nothing new is ready
        n_commits = len(api.commits)
        assert run_batches(api, tmp) == [] and len(api.commits) == n_commits
        # crash-resume: drop .pushed + re-stage the same PDF -> no re-upload (ledger), still deleted
        (stage / "_manifest/batch_0001.pushed").unlink()
        stage_doc(stage, "doc:1", "wd:Q1", "PH")
        r2 = run_batches(api, tmp)[0]
        # doc:1 re-staged -> already; doc/2 + a3 were verified and deleted -> done too (2026-10-18 retry fix), not missing_file
        assert r2["uploaded"] == 0 and r2["commits"] == [] and r2["already_on_hub"] == 3 and r2["recovered_missing"] == 2
        assert not any(s["reason"].startswith("missing_file") and s["doc_id"] in ("doc/2", "a3") for s in r2["skipped"])
        assert not (stage / "PH/wd_Q1/doc_1.pdf").exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_verify_failure_keeps_file_and_not_pushed():
    tmp = Path(tempfile.mkdtemp(prefix="wl_pdf_test_", dir="/tmp"))
    try:
        stage = tmp / "staging/pdf"
        rec = stage_doc(stage, "x1", "wd:Q1", "PH")
        write_batch(stage, 7, [rec])
        api = FakeApi(corrupt={S.pdf_path("PH", "wd_Q1", rec["sha256"])})
        r = run_batches(api, tmp)[0]
        assert r.get("incomplete") and not (stage / "_manifest/batch_0007.pushed").exists()
        assert (stage / "PH/wd_Q1/x1.pdf").exists()
        api.corrupt.clear()
        r = run_batches(api, tmp)[0]
        assert r["verified"] == 1 and (stage / "_manifest/batch_0007.pushed").exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_dry_run_and_run_loop_ignores_pdf_staging():
    tmp = Path(tempfile.mkdtemp(prefix="wl_pdf_test_", dir="/tmp"))
    try:
        stage = tmp / "staging/pdf"
        write_batch(stage, 1, [stage_doc(stage, "d", "wd:Q1", "PH")])
        a = args_for(tmp)
        a.dry_run = True
        rep = U.process_batch(FakeApi(), a, "batch_0001", {}, set())
        assert rep["would_upload"] == 1 and (stage / "PH/wd_Q1/d.pdf").exists()
        assert run_loop.discover(tmp / "staging", 0, None) == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_rl(tmp, **kw):
    time.sleep(1.1)
    try:
        return _run(tmp, **kw)
    finally:
        if run_loop._LOCK.get("f") is not None:
            run_loop._LOCK["f"].close()
        run_loop._LOCK["f"] = None


def test_pdf_ref_new_rows_and_backfill_rebuild():
    tmp = Path(tempfile.mkdtemp(prefix="wl_hold_test_", dir="/tmp"))
    (tmp / "overrides.json").write_text(json.dumps({"quarantine": []}))
    try:
        ref = S.pdf_ref(S.pdf_path("JP", "wd_Q1490", "ab" * 32))
        # 1) published before the PDF exists -> pdf_ref null, 35 columns
        w(tmp / "staging/jp/JP/wd_Q1490.20261014T000000Zp0001.jsonl", [base("a"), base("b")])
        scratch, _ = _run_rl(tmp)
        _, rows = read_place(scratch, "JP", "wd_Q1490")
        assert all(r["pdf_ref"] is None for r in rows) and len(S.HTML_COLUMNS) == 35
        shutil.copytree(scratch / "out", tmp / "out")
        shutil.rmtree(tmp / "staging")
        (tmp / "staging").mkdir()
        # 2) PDF uploaded later -> pdf_refs; rebuild via CC/place_key backfills only that doc
        p = tmp / "state/pdf_refs/JP/wd_Q1490.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"a": ref}))
        lst = tmp / "rb.txt"
        lst.write_text("JP/wd_Q1490\n")
        scratch, summ = _run_rl(tmp, **{"rebuild-places-file": lst, "bot": "__pdf_backfill__"})
        _, rows = read_place(scratch, "JP", "wd_Q1490")
        by = {r["doc_id"]: r for r in rows}
        assert by["a"]["pdf_ref"] == ref and by["b"]["pdf_ref"] is None and summ["pdf_ref_set"] == 1
        meta = json.loads(next((scratch / "out").rglob("wd_Q1490.json")).read_text())
        assert meta["schema_version"] == "1.2.0"
        # 3) a new staged row of a place with refs gets pdf_ref at normalize/build time
        w(tmp / "staging/jp/JP/wd_Q1490.20261014T010000Zp0001.jsonl", [base("c")])
        p.write_text(json.dumps({"a": ref, "c": ref}))
        scratch, _ = _run_rl(tmp)
        _, rows = read_place(scratch, "JP", "wd_Q1490")
        assert {r["doc_id"]: r["pdf_ref"] for r in rows} == {"a": ref, "b": None, "c": ref}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_loader_handles_old_files_without_pdf_ref():
    import pyarrow as pa
    old = pa.table({n: pa.nulls(2, pa.string()) for n, _ in WLL.WORLD_COLUMNS if n != "pdf_ref"})
    t = WLL._to_world(old)
    assert t.column_names[-1] == "pdf_ref" and t.num_columns == 35 and t.column("pdf_ref").null_count == 2


def test_card_and_law_location():
    import pdf_card
    txt = pdf_card.card(None)
    for s in ("image-only", "manifest.parquet", "content_signal", "pdf_ref", "robots_unreachable"):
        assert s in txt
    assert U.law_location(Path("/nonexistent"), "PH", "wd_Q1", "x") == (None, None)


def test_hub_sha256_plain_git_blob():
    """small PDFs stored as plain git blobs (no LFS info) verify via blob_id sha1 + size (+ download)."""
    tmp = Path(tempfile.mkdtemp())
    try:
        good, bad = tmp / "a.pdf", tmp / "b.pdf"
        good.write_bytes(pdf_bytes("small-a"))
        bad.write_bytes(pdf_bytes("small-b"))
        g = good.read_bytes()

        class BlobApi:
            def get_paths_info(self, repo, paths, repo_type, expand):
                return [SimpleNamespace(path="x/a.pdf", lfs=None, blob_id=U.git_blob_sha1(g), size=len(g)),
                        SimpleNamespace(path="x/b.pdf", lfs=None, blob_id="0" * 40, size=len(g)),
                        SimpleNamespace(path="x/c.pdf", lfs=None, blob_id=U.git_blob_sha1(g), size=len(g) + 1)]
        loc = {"x/a.pdf": good, "x/b.pdf": bad, "x/c.pdf": good}
        h = U.hub_sha256(BlobApi(), "r", list(loc), local=loc, download_small=False)
        assert h["x/a.pdf"] == hashlib.sha256(g).hexdigest()
        assert h["x/b.pdf"] is None and h["x/c.pdf"] is None
        assert U.hub_sha256(BlobApi(), "r", ["x/a.pdf"])["x/a.pdf"] is None  # no local file -> unverified
        orig = U._download_sha256
        try:
            U._download_sha256 = lambda api, repo, path: hashlib.sha256(g).hexdigest()
            assert U.hub_sha256(BlobApi(), "r", ["x/a.pdf"], local=loc)["x/a.pdf"] == hashlib.sha256(g).hexdigest()
            U._download_sha256 = lambda api, repo, path: None
            assert U.hub_sha256(BlobApi(), "r", ["x/a.pdf"], local=loc)["x/a.pdf"] is None
        finally:
            U._download_sha256 = orig
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_gitattributes_guard():
    default = "*.zip filter=lfs diff=lfs merge=lfs -text\n# Image files\n*.png filter=lfs diff=lfs merge=lfs -text\n" \
              "custom/dir/** filter=lfs diff=lfs merge=lfs -text\n"
    per_file = "".join(f"pdfs/RO/wd_Q{i}/{i:064x}.pdf filter=lfs diff=lfs merge=lfs -text\n" for i in range(20000))
    big = default + per_file + "data/x.parquet filter=lfs diff=lfs merge=lfs -text\n"
    assert len(big.encode()) > U.GITATTR_MAX_BYTES
    out = U.compact_gitattributes(big)
    lines = out.splitlines()
    assert "pdfs/" not in out and "data/x.parquet" not in out
    assert lines[:4] == default.splitlines()  # defaults, comments and custom rules kept in order
    assert lines[-len(U.LFS_RULES):] == U.LFS_RULES and len(out) < 1024   # *.pdf, *.parquet, *.tar (2026-10-18)
    assert U.compact_gitattributes(out) == out  # idempotent

    tmp = Path(tempfile.mkdtemp())

    class GAApi(FakeApi):
        def __init__(self, text):
            super().__init__()
            self.text = text
            self.files[".gitattributes"] = "x"

        def get_paths_info(self, repo, paths, repo_type, expand):
            if paths == [".gitattributes"]:
                return [SimpleNamespace(path=".gitattributes", size=len(self.text.encode()), lfs=None)]
            return super().get_paths_info(repo, paths, repo_type, expand)

        def hf_hub_download(self, repo_id, filename, repo_type, local_dir):
            f = Path(local_dir) / filename
            f.write_text(self.text)
            return str(f)

        def create_commit(self, repo_id, repo_type, operations, commit_message):
            for op in operations:
                if op.path_in_repo == ".gitattributes":
                    self.text = bytes(op.path_or_fileobj).decode()
            return super().create_commit(repo_id, repo_type, operations, commit_message)
    try:
        api = GAApi(big)
        assert U.ensure_gitattributes(api, "test/pdfs") is not None
        assert api.text == out and len(api.commits) == 1
        assert U.ensure_gitattributes(api, "test/pdfs") is None and len(api.commits) == 1  # compact: no-op
        # a missing *.pdf rule is fixed even when small (otherwise the Hub appends one line per PDF)
        api2 = GAApi(default)
        assert U.ensure_gitattributes(api2, "test/pdfs") and "*.pdf filter=lfs" in api2.text
        # the guard runs before PDF uploads in process_batch
        api3 = GAApi(big)
        stage = tmp / "staging/pdf"
        write_batch(stage, 1, [stage_doc(stage, "ga:1", "wd:Q90", "FR")])
        rep = run_batches(api3, tmp)[0]
        assert rep.get("gitattributes_commit") and api3.commits[0][2] == [".gitattributes"]
        assert len(api3.text.encode()) < U.GITATTR_MAX_BYTES
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
            n += 1
    print(f"ALL {n} PDF TESTS PASSED")
