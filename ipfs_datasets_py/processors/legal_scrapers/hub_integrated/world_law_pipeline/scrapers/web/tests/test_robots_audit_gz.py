"""robots_audit.py must read .jsonl.gz as well as .jsonl (staging and processed)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import gzip, json, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SCRATCH = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/web/_test_robots_audit_gz"))


def _row(pid, url, did):
    return {"place_id": pid, "country_code": "DE", "doc_id": did, "source_platform": "de_municipal_web",
            "source_url": url, "requested_url": url, "section_url": "https://example.test/ortsrecht/",
            "doc_type": "ordinance", "language": "de", "title_native": "Satzung " + did,
            "consolidated": False, "content_format": "pdf_text", "text": "§ 1 Text",
            "retrieved_at": "2026-10-11T00:00:00Z"}


def test_audit_reads_gz(tmp_path=None):
    shutil.rmtree(SCRATCH, ignore_errors=True)
    st, pr, q = SCRATCH / "staging", SCRATCH / "processed", SCRATCH / "quarantine"
    (st / "_state" / "robots").mkdir(parents=True)
    pr.mkdir(parents=True)
    (st / "_state" / "robots" / "https_example.test.json").write_text(json.dumps(
        {"state": "ok", "status": 200, "text": "User-agent: *\nDisallow: /private/\n"}))
    good = _row("wd:Q1", "https://example.test/ok/a.pdf", "a")
    bad = _row("wd:Q1", "https://example.test/private/b.pdf", "b")
    # processed: gz with one violation, plain clean file
    with gzip.open(pr / "wd_Q1.full.1.jsonl.gz", "wt", encoding="utf-8") as fh:
        fh.write(json.dumps(good) + "\n" + json.dumps(bad) + "\n")
    (pr / "wd_Q2.full.1.jsonl").write_text(json.dumps({**good, "place_id": "wd:Q2"}) + "\n")
    # staging: gz with one violation -> quarantined + clean rewrite
    with gzip.open(st / "wd_Q3.full.1.jsonl.gz", "wt", encoding="utf-8") as fh:
        for r in (good, bad):
            fh.write(json.dumps({**r, "place_id": "wd:Q3"}) + "\n")
    out = SCRATCH / "audit.json"
    subprocess.run([sys.executable, str(HERE / "robots_audit.py"), "--staging", str(st), "--processed", str(pr),
                    "--quarantine", str(q), "--audit-out", str(out)], check=True, capture_output=True)
    a = json.loads(out.read_text())
    assert a["files_audited"] == 3, a["files_audited"]
    assert a["docs_audited"] == 5
    assert a["violating_docs"] == 2
    assert a["violating_files_processed"] == 1 and a["violating_files_staging"] == 1
    assert (pr / "wd_Q1.full.1.jsonl.gz").exists()          # processed files are never touched
    assert (q / "wd_Q3.full.1.jsonl.gz").exists() and not (st / "wd_Q3.full.1.jsonl.gz").exists()
    rewritten = list(st.glob("wd_Q3.full.*-robotsaudit.jsonl"))
    assert len(rewritten) == 1 and len(rewritten[0].read_text().splitlines()) == 1
    shutil.rmtree(SCRATCH, ignore_errors=True)
