#!/usr/bin/env python3
"""States lane test batch runner.
  --dry-run (default): robots/guard checks only, no page fetches, no writes.
  --live: discover + fetch up to --limit docs per source (polite), validate, stage to staging/states/<CC>/.
Usage: /workspace/world_law/pipeline/venv/bin/python run_test.py --sources ca_on_elaws,ca_mb_ccsm,au_qld_leg [--live --limit 30]
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ARCHIVE_LANE", "states")
from common import PoliteSession, STAGING, stage_place, check_guards, rss_mb, utcnow, GuardError  # noqa: E402
from sources import ADAPTERS, PLACES  # noqa: E402

PROBE = {"ca_on_elaws": "https://www.ontario.ca/laws/statute/90h08",
         "ca_mb_ccsm": "https://web2.gov.mb.ca/laws/statutes/ccsm/a001-5.php?lang=en",
         "au_qld_leg": "https://www.legislation.qld.gov.au/view/xml/inforce/current/act-2016-001"}

ap = argparse.ArgumentParser()
ap.add_argument("--sources", default=",".join(ADAPTERS)); ap.add_argument("--limit", type=int, default=30)
ap.add_argument("--live", action="store_true"); ap.add_argument("--review", action="store_true", help="stage into _review/ (uploader-ignored)"); ap.add_argument("--on-cdx-file")
a = ap.parse_args()
logd = STAGING / "_logs"; logd.mkdir(parents=True, exist_ok=True)
logf = open(logd / f"run_test_{time.strftime('%Y%m%dT%H%M%S')}.log", "a")
def log(*x):
    s = f"{utcnow()} " + " ".join(map(str, x)); print(s); logf.write(s + "\n"); logf.flush()
sess = PoliteSession(log=log); check_guards()
report = {}
for key in a.sources.split(","):
    A = ADAPTERS[key](); ok, pol = sess.allowed(PROBE[key])
    log(f"[{key}] robots for {PROBE[key]}: allowed={ok} policy={pol} delay={sess.delay_for(PROBE[key])}s")
    if not a.live or not ok:
        report[key] = {"robots_allowed": ok, "policy": pol, "live": False}; continue
    try:
        urls = A.discover(sess, a.limit * 2, a.on_cdx_file) if key == "ca_on_elaws" else A.discover(sess, a.limit * 2)
    except PermissionError as e:
        log(f"[{key}] STOP: {e}"); report[key] = {"stopped": str(e)}; continue
    log(f"[{key}] discovered {len(urls)} urls"); rows, fails = [], []
    for u in urls:
        if len(rows) >= a.limit: break
        try:
            check_guards(); r, pol = sess.get(u)
            if r.status_code != 200: fails.append({"url": u, "status": r.status_code}); continue
            rec = A.parse(u, r)
            if not rec or len((rec.get("text") or "").strip()) < 200 or not rec.get("title_native"):
                fails.append({"url": u, "reason": "empty_text_or_title"}); continue
            rec["source_policy"] = pol; rows.append(rec)
        except GuardError as e:
            log(f"GUARD: {e}"); break
        except PermissionError as e:
            log(f"[{key}] STOP (no bypass): {e}"); fails.append({"url": u, "reason": str(e)}); break
        except Exception as e:
            fails.append({"url": u, "reason": repr(e)[:300]})
    pl = PLACES[A.place]
    path, errs = stage_place(pl["country_code"], pl["place_id"], rows, tag=key, review=a.review) if rows else (None, [])
    report[key] = {"discovered": len(urls), "staged": len(rows) - len([e for e in errs if "doc_id" in e]), "path": str(path),
                   "fetch_failures": fails, "validation_errors": errs, "rss_mb": round(rss_mb())}
    log(f"[{key}] staged -> {path}  rows={len(rows)} fails={len(fails)} val_errs={len(errs)}")
(logd / "last_report.json").write_text(json.dumps(report, indent=1, default=str))
print(json.dumps(report, indent=1, default=str)[:4000])
