#!/usr/bin/env python3
"""Re-audit staged/processed web/DE documents against RFC 9309 (rfc9309.Robots).

Checks, per document: requested_url, doc_url (source_url, final after redirects) and
section_url (page the link was found on). Policy: robots 2xx parse, 4xx allow,
5xx/unreachable disallow. Violating staged files are copied to quarantine/web/DE/ with a
reason note, removed from staging, and the place is re-written (compliant docs only)
under a new '.full' batch. Files already in processed/ are only listed.
Writes /workspace/world_law/staging/web/_robots_audit.json
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import argparse
import datetime as dt
import gzip
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from rfc9309 import Robots  # noqa: E402
import schema  # noqa: E402

UA_TOKEN = "WorldLawMunicipalBot"
USER_AGENT = (f"{UA_TOKEN}/0.3 (+https://github.com/endomorphosis/ipfs_datasets_py; research crawler collecting "
              "public municipal bylaws; robots.txt audit)")
CC = "DE"
STAGING = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/web/DE"))
PROCESSED = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/processed/web/DE"))
QUAR = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/quarantine/web/DE"))
AUDIT = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/web/_robots_audit.json"))
ROBOTS_CACHE = STAGING / "_state" / "robots_audit"


def set_country(cc: str, processed: Path | None = None) -> None:
    global CC, STAGING, PROCESSED, QUAR, AUDIT, ROBOTS_CACHE, CRAWL_ROBOTS
    CC = cc
    STAGING = Path(f"/workspace/world_law/staging/web/{cc}")
    PROCESSED = processed or Path(f"/workspace/world_law/processed/web/{cc}")
    QUAR = Path(f"/workspace/world_law/quarantine/web/{cc}")
    AUDIT = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/web/_robots_audit.json") if cc == "DE"
                 else f"/workspace/world_law/staging/web/_robots_audit_{cc}.json")
    ROBOTS_CACHE = STAGING / "_state" / "robots_audit"
    CRAWL_ROBOTS = STAGING / "_state" / "robots"


def origin(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    return f"{p.scheme}://{p.netloc.lower()}"


_robots: dict[str, tuple[str, Robots]] = {}
_lock = threading.Lock()


CRAWL_ROBOTS = STAGING / "_state" / "robots"


def fetch_robots(org: str) -> tuple[str, Robots]:
    """Prefer the robots.txt the crawler actually used (saved at crawl time); otherwise fetch
    it now (one retry on transient errors)."""
    scheme, host = org.split("://", 1)
    crawl_fn = CRAWL_ROBOTS / (re.sub(r"[^A-Za-z0-9_.-]", "_", f"{scheme}_{host}") + ".json")
    fn = ROBOTS_CACHE / (re.sub(r"[^A-Za-z0-9_.-]", "_", org) + ".json")
    if crawl_fn.exists():
        c = json.loads(crawl_fn.read_text())
        if c.get("state") == "ok":
            return "ok", Robots(c.get("text") or "")
        if c.get("state") == "allow_all":
            return f"robots_{c.get('status')}", Robots(allow_all=True)
        return "crawl_time_" + str(c.get("state")), Robots(disallow_all=True)
    if fn.exists():
        d = json.loads(fn.read_text())
        if d.get("error") and not d.get("retried"):
            fn.unlink()
    if fn.exists():
        d = json.loads(fn.read_text())
    else:
        d = {"url": org + "/robots.txt", "status": 0, "text": "", "error": "", "retried": True}
        for attempt in range(2):
            try:
                r = requests.get(org + "/robots.txt", headers={"User-Agent": USER_AGENT}, timeout=(15, 40))
                d["status"] = r.status_code
                d["text"] = r.text[:512_000] if r.status_code < 400 else ""
                d["error"] = ""
                break
            except Exception as e:
                d["error"] = f"{type(e).__name__}: {str(e)[:150]}"
                time.sleep(5)
        d["fetched_at"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ROBOTS_CACHE.mkdir(parents=True, exist_ok=True)
        fn.write_text(json.dumps(d, ensure_ascii=False))
        time.sleep(2)
    if d.get("error") or d["status"] == 0:
        return "unreachable", Robots(disallow_all=True)
    if d["status"] >= 500:
        return f"robots_{d['status']}", Robots(disallow_all=True)
    if d["status"] >= 400:
        return f"robots_{d['status']}", Robots(allow_all=True)
    return "ok", Robots(d["text"])


def allowed(url: str) -> tuple[bool, str]:
    if not url or not url.startswith(("http://", "https://")):
        return True, ""
    org = origin(url)
    st, rb = _robots[org]
    ok = rb.can_fetch(UA_TOKEN, url)
    return ok, ("" if ok else ("disallow_all:" + st if st != "ok" else "rule"))


def read_rows(p: Path) -> list:
    """Read a staged/processed JSONL file, plain or gzip-compressed (.jsonl.gz)."""
    if p.name.endswith(".gz"):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]
    with p.open(encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def final_stem(p: Path) -> str:
    """File name without .gz, e.g. wd_Q1.full.X.jsonl."""
    return p.name[:-3] if p.name.endswith(".gz") else p.name


def staged_files() -> list[tuple[str, Path]]:
    out = []
    for pat in ("*.jsonl", "*.jsonl.gz"):
        for p in sorted(STAGING.glob(pat)):
            out.append(("staging", p))
    if PROCESSED.exists():
        for pat in ("*.jsonl", "*.jsonl.gz"):
            for p in sorted(PROCESSED.rglob(pat)):
                out.append(("processed", p))
    return out


def main() -> None:
    files = staged_files()
    rows_by_file = {}
    origins = set()
    for loc, p in files:
        try:
            rows = read_rows(p)
        except FileNotFoundError:
            continue  # moved by uploader meanwhile
        # keep only the fields the audit needs (texts can be large); full rows are re-read for rewrites
        rows = [{k: r.get(k) for k in ("place_id", "doc_id", "title_native", "requested_url", "source_url",
                                       "section_url", "source_policy", "archive_source")} for r in rows]
        rows_by_file[(loc, p)] = rows
        for r in rows:
            if r.get("archive_source"):
                continue  # archived copy: never live-fetched from the original host
            for k in ("requested_url", "source_url", "section_url"):
                if r.get(k):
                    origins.add(origin(r[k]))
    doc_origins = len(origins)
    try:  # also every origin in the crawler's fetch cache (the full fetch path)
        import sqlite3
        db = sqlite3.connect(str(STAGING / "_state" / "fetch_cache.sqlite"))
        for (u,) in db.execute("SELECT url FROM fetch"):
            if u.startswith(("http://", "https://")):
                origins.add(origin(u))
    except Exception:
        pass
    print(f"files={len(rows_by_file)} doc_origins={doc_origins} all_origins={len(origins)}", flush=True)
    with ThreadPoolExecutor(8) as ex:
        for org, res in zip(sorted(origins), ex.map(fetch_robots, sorted(origins))):
            _robots[org] = res
    report = {"audited_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "parser": "scrapers/web/rfc9309.py (vendored from scrapers/asia_latam/common/rfc9309.py)",
              "policy": "robots 2xx parsed; 4xx allow-all; 5xx/unreachable disallow-all; checks requested_url, doc_url(source_url), section_url",
              "user_agent_token": UA_TOKEN,
              "files_audited": len(rows_by_file), "docs_audited": 0, "origins_checked": len(origins),
              "violating_docs": 0, "violating_files_staging": 0, "violating_files_processed": 0,
              "quarantined_files": [], "rewritten_files": [], "places_with_no_compliant_docs": [],
              "violations": []}
    QUAR.mkdir(parents=True, exist_ok=True)
    for (loc, p), rows in rows_by_file.items():
        report["docs_audited"] += len(rows)
        bad = []
        for r in rows:
            if r.get("archive_source"):
                report["archived_docs_exempt"] = report.get("archived_docs_exempt", 0) + 1
                continue  # fetched from Common Crawl / Wayback, not from the robots-governed host
            reasons = []
            for k in ("requested_url", "source_url", "section_url"):
                ok, why = allowed(r.get(k) or "")
                if not ok:
                    reasons.append({"field": k, "url": r.get(k), "why": why})
            if reasons:
                bad.append((r, reasons))
        if not bad:
            continue
        report["violating_docs"] += len(bad)
        report["violating_files_" + loc] += 1
        for r, reasons in bad:
            report["violations"].append({"file": str(p), "location": loc, "place_id": r.get("place_id"),
                                         "doc_id": r.get("doc_id"), "title": (r.get("title_native") or "")[:200],
                                         "reasons": reasons})
        if loc != "staging":
            continue
        # quarantine original (copy + note), then remove from staging and rewrite a clean .full batch
        if not p.exists():
            continue
        q = QUAR / p.name
        shutil.copy2(p, q)
        (QUAR / (p.name + ".reason.json")).write_text(json.dumps({
            "reason": "robots.txt violation found in RFC 9309 re-audit",
            "violating_doc_ids": [r.get("doc_id") for r, _ in bad],
            "details": [{"doc_id": r.get("doc_id"), "reasons": rs} for r, rs in bad],
            "audited_at": report["audited_at"]}, ensure_ascii=False, indent=1))
        p.unlink()
        report["quarantined_files"].append(str(q))
        bad_ids = {r.get("doc_id") for r, _ in bad}
        clean = [r for r in read_rows(q) if r.get("doc_id") not in bad_ids]
        pid = rows[0]["place_id"]
        if not clean:
            report["places_with_no_compliant_docs"].append(pid)
            continue
        for i, r in enumerate(clean):
            r["doc_order"] = i
        pk = schema.place_key(pid)
        batch = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-robotsaudit"
        final = STAGING / f"{pk}.full.{batch}.jsonl"
        tmp = final.with_name(final.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for r in clean:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        chk = STAGING / "_state" / "validate" / final.name
        chk.parent.mkdir(parents=True, exist_ok=True)
        chk.unlink(missing_ok=True)
        os.link(tmp, chk)
        v = schema.validate_file(chk, expect_place_key=pk)
        chk.unlink()
        if v["ok"]:
            os.rename(tmp, final)
            report["rewritten_files"].append(str(final))
        else:
            report.setdefault("rewrite_validation_failed", []).append({"file": str(tmp), "errors": [str(e) for e in v["errors"][:5]]})
    # informational: every URL in the fetch cache
    try:
        import sqlite3
        db = sqlite3.connect(str(STAGING / "_state" / "fetch_cache.sqlite"))
        urls = [u for (u,) in db.execute("SELECT url FROM fetch WHERE status IS NOT NULL AND status > 0")]
        report["fetch_cache_urls_checked_against_known_robots"] = 0
        report["fetch_cache_violations_sample"] = []
        n_bad = 0
        for u in urls:
            org = origin(u)
            if org not in _robots:
                continue
            report["fetch_cache_urls_checked_against_known_robots"] += 1
            ok, why = allowed(u)
            if not ok:
                n_bad += 1
                if len(report["fetch_cache_violations_sample"]) < 50:
                    report["fetch_cache_violations_sample"].append({"url": u, "why": why})
        report["fetch_cache_violations"] = n_bad
    except Exception as e:
        report["fetch_cache_check_error"] = str(e)
    tmp = AUDIT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    tmp.replace(AUDIT)
    print(json.dumps({k: v for k, v in report.items() if not isinstance(v, list)}, indent=1))
    print("quarantined", len(report["quarantined_files"]), "rewritten", len(report["rewritten_files"]),
          "no_compliant", len(report["places_with_no_compliant_docs"]))


def cli() -> None:
    global STAGING, PROCESSED, QUAR, AUDIT, ROBOTS_CACHE, CRAWL_ROBOTS
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--country", default="DE")
    ap.add_argument("--staging", help="override staging dir (tests)")
    ap.add_argument("--processed", help="override processed dir (tests)")
    ap.add_argument("--quarantine", help="override quarantine dir (tests)")
    ap.add_argument("--audit-out", help="override audit json path (tests)")
    a = ap.parse_args()
    set_country(a.country)
    if a.staging:
        STAGING = Path(a.staging)
        ROBOTS_CACHE = STAGING / "_state" / "robots_audit"
        CRAWL_ROBOTS = STAGING / "_state" / "robots"
    if a.processed:
        PROCESSED = Path(a.processed)
    if a.quarantine:
        QUAR = Path(a.quarantine)
    if a.audit_out:
        AUDIT = Path(a.audit_out)
    main()


if __name__ == "__main__":
    cli()
