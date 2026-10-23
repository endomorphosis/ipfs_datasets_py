#!/usr/bin/env python3
"""Greece: Diavgeia (diavgeia.gov.gr, Law 3861/2010 transparency portal) - municipal regulatory decisions.

API (OpenData, no key, documented at diavgeia.gov.gr/api/help; robots.txt only disallows /decision/view, /doc/*,
/luminapi/api/decisions/*, /f/all/ada/* - none are used):
  orgs     /opendata/organizations?category=MUNICIPALITY                       (336 δήμοι)
  search   /opendata/search?subject=<term>&from_issue_date=&to_issue_date=&size=500&page=N
           (server caps a query at a ~6-month issueDate window, so we walk half-years 2010-10 -> today)
  document /opendata/decisions/<ADA>/document                                  (signed PDF -> pdftotext)
Scope: subject contains κανονισμ* or κανονιστικ*, issuing organisation is a municipality, decision type Α.2
(ΚΑΝΟΝΙΣΤΙΚΗ ΠΡΑΞΗ) or 2.4.7.1 (other council/mayor acts); obvious non-regulatory hits (works price protocols,
fine write-offs) are dropped by NOISE. Scanned PDFs without a text layer go to failed.jsonl (reason no_text_layer).
Usage: python3 gr_diavgeia.py catalog | fetch [--limit N] [--test N] | all | status
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
import csv
import gc
import json
import random
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.live import _STOP, STAGE, Done, PoliteSession, Stager, get_logger, utcnow  # noqa: E402
from common.gr_names import GrPlaces, assign, load_additions, load_org_codes  # noqa: E402

BASE = "https://diavgeia.gov.gr/opendata"
STATE = STAGE / "_state" / "gr"
CAT = STATE / "catalog.jsonl"
ORGS = STATE / "orgs.json"
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
log = get_logger("gr_diavgeia")
TERMS = ["κανονισμ", "κανονιστικ"]
TYPES = {"Α.2", "2.4.7.1"}
NOISE = re.compile(r"Πρωτοκόλλου Κανονισμού Νέων Τιμών|ΠΚΝΤ|Ανακεφαλαιωτικ|διαγραφ\w* ποσ|πράξη βεβαίωσης παράβασης|"
                   r"Επιτροπής Επίλυσης Φορολογικών", re.I)
FIRST = date(2010, 10, 1)
OLD_HOST = "static.old.diavgeia.gov.gr"     # pre-2013 ADA PDFs: /opendata/decisions/<ADA>/document -> 302 http://OLD_HOST/doc/<ADA>
DEFERRED = STATE / "deferred_oldhost.jsonl"
BLOCKED = STAGE / "_logs" / "blocked_sources.jsonl"
ROBOTS_AUDIT = STAGE / "_logs" / "robots_audit.json"


class HostBreaker:
    """Per-host circuit breaker for the old static host: one attempt per doc (no retry ladder); after `threshold`
    consecutive connect failures (incl. an unreachable robots.txt) the host is skipped for the rest of the run.
    Skipped/failed old-host docs go to _state/gr/deferred_oldhost.jsonl (NOT failed.jsonl, NOT done) so a later run
    (or an archive pass) can pick them up."""

    def __init__(self, host, threshold=3):
        self.host, self.threshold, self.fails, self.open, self.n_deferred = host, threshold, 0, False, 0
        self.seen = set()
        if DEFERRED.exists():
            for ln in DEFERRED.open(encoding="utf-8"):
                try:
                    self.seen.add(json.loads(ln)["ada"])
                except Exception:  # noqa: BLE001
                    pass

    def defer(self, a, loc, pl, why):
        self.n_deferred += 1
        if a["ada"] in self.seen:
            return
        self.seen.add(a["ada"])
        with DEFERRED.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ada": a["ada"], "pdf_url": loc, "api_url": f"{BASE}/decisions/{a['ada']}/document",
                                "org": a["organizationId"], "place_id": (pl or {}).get("place_id"),
                                "title": a.get("subject"), "issue_date": iso(a.get("issueDate")), "why": why,
                                "at": utcnow()}, ensure_ascii=False) + "\n")

    def failed(self, err):
        self.fails += 1
        if self.fails >= self.threshold and not self.open:
            self.open = True
            log.warning("breaker OPEN for %s after %d consecutive connect failures (%s); skipping it for this run",
                        self.host, self.fails, str(err)[:160])
            with BLOCKED.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"source": "gr_diavgeia:old_static", "url": f"http://{self.host}/doc/",
                                    "status": "network_blocked", "detail": f"{self.fails} consecutive connect failures: "
                                    f"{str(err)[:200]}", "at": utcnow(),
                                    "action": "breaker: skip host for the run; docs -> _state/gr/deferred_oldhost.jsonl"},
                                   ensure_ascii=False) + "\n")
            try:   # robots.txt of the host is unreachable too -> RFC 9309 'disallow all'; record it in the audit
                d = json.loads(ROBOTS_AUDIT.read_text()) if ROBOTS_AUDIT.exists() else {"robots_status": {}, "report": {}}
                d.setdefault("robots_status", {})[f"http://{self.host}"] = "unreachable (connect timeout)"
                tmp = ROBOTS_AUDIT.with_name("." + ROBOTS_AUDIT.name + ".tmp")
                tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1))
                tmp.replace(ROBOTS_AUDIT)
            except Exception as e:  # noqa: BLE001
                log.warning("robots_audit update failed: %s", e)

    def ok(self):
        self.fails = 0


def get_document(sess, osess, brk, a, pl):
    """GET /opendata/decisions/<ADA>/document; a redirect to OLD_HOST goes through the breaker.
    Returns the response, or None when the doc was deferred."""
    import requests
    from urllib.parse import urljoin, urlsplit
    url = f"{BASE}/decisions/{a['ada']}/document"
    r = sess.get(url, allow_redirects=False, ok=(200, 301, 302, 303, 307, 308))
    hops = 0
    while r.status_code in (301, 302, 303, 307, 308) and hops < 5:
        hops += 1
        loc = urljoin(r.url, r.headers.get("Location", ""))
        if (urlsplit(loc).hostname or "") != OLD_HOST:
            r = sess.get(loc, allow_redirects=False, ok=(200, 301, 302, 303, 307, 308))
            continue
        if brk.open:
            brk.defer(a, loc, pl, "breaker_open")
            return None
        try:
            r = osess.get(loc, allow_redirects=False, ok=(200, 301, 302, 303, 307, 308))
            brk.ok()
        except PermissionError as e:   # robots.txt of the old host: unreachable -> disallow all (counts as a connect failure)
            st = (osess.robots.cache.get(f"{urlsplit(loc).scheme}://{urlsplit(loc).netloc}") or (None, 0, None))[2]
            if str(st).startswith("error"):
                brk.failed(f"robots.txt {st}")
                brk.defer(a, loc, pl, "old_host_unreachable")
                return None
            raise
        except (requests.ConnectionError, requests.Timeout) as e:
            brk.failed(e)
            brk.defer(a, loc, pl, "old_host_unreachable")
            return None
    return r


def windows():
    y, h = FIRST.year, 2
    t = date.today()
    while True:
        a = date(y, 1 if h == 1 else 7, 1)
        if a > t:
            return
        b = date(y, 6, 30) if h == 1 else date(y, 12, 31)
        yield a.isoformat(), min(b, t).isoformat()
        y, h = (y, 2) if h == 1 else (y + 1, 1)


def orgs(sess):
    if not ORGS.exists():
        STATE.mkdir(parents=True, exist_ok=True)
        d = sess.get(f"{BASE}/organizations", params={"category": "MUNICIPALITY"}, headers={"Accept": "application/json"}).json()
        ORGS.write_text(json.dumps(d, ensure_ascii=False))
    return json.loads(ORGS.read_text())["organizations"]


def catalog(sess, max_windows=None):
    STATE.mkdir(parents=True, exist_ok=True)
    muni = {o["uid"] for o in orgs(sess)}
    stp = STATE / "catalog.state.json"
    st = json.loads(stp.read_text()) if stp.exists() else {"done": {}}
    nw = 0
    last = list(windows())[-1][0]
    with CAT.open("a", encoding="utf-8") as f:
        for a, b in windows():
            for term in TERMS:
                k = f"{a}|{term}"
                if k in st["done"] and a != last:
                    continue
                if max_windows and nw >= max_windows:
                    break
                nw += 1
                page, kept, total = 0, 0, None
                while True:
                    d = sess.get(f"{BASE}/search", params={"subject": term, "from_issue_date": a, "to_issue_date": b,
                                                            "size": 500, "page": page},
                                 headers={"Accept": "application/json"}).json()
                    total = d["info"]["total"]
                    for x in d["decisions"]:
                        if x["organizationId"] in muni and x["decisionTypeId"] in TYPES and not NOISE.search(x["subject"] or ""):
                            f.write(json.dumps({k2: x.get(k2) for k2 in ("ada", "protocolNumber", "subject", "issueDate",
                                    "organizationId", "unitIds", "signerIds", "decisionTypeId", "thematicCategoryIds",
                                    "publishTimestamp", "versionId", "documentUrl", "extraFieldValues")} | {"term": term},
                                    ensure_ascii=False) + "\n")
                            kept += 1
                    f.flush()
                    page += 1
                    if page * 500 >= total or not d["decisions"]:
                        break
                st["done"][k] = {"total": total, "kept": kept}
                stp.write_text(json.dumps(st))
                log.info("catalog %s..%s %s: kept %d of %d", a, b, term, kept, total)
    st["complete"] = all(f"{a}|{t}" in st["done"] for a, _ in windows() for t in TERMS)
    stp.write_text(json.dumps(st))


def pdf_text(content: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", dir="/tmp") as tf:
        tf.write(content)
        tf.flush()
        p = subprocess.run(["pdftotext", "-q", "-enc", "UTF-8", tf.name, "-"], capture_output=True, timeout=180)
    t = p.stdout.decode("utf-8", "replace")
    t = re.sub(r"[ \t\u00a0]+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def body_len(t):
    """characters after removing the digital-signature stamp / ADA header lines."""
    t = re.sub(r"(?im)^.*(signed by|digitally|informatics|development|agency|reason:|location:|date:|ΑΔΑ:|EEST|EET).*$", "", t)
    return len(re.sub(r"\s+", "", t))


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat() if ms else None


def build(a, text, pl, org):
    url = f"https://diavgeia.gov.gr/decision/view/{a['ada']}"
    return {
        "place_id": pl["place_id"] if pl else None, "country_code": "GR", "doc_id": f"gr_diavgeia:{a['ada']}",
        "source_platform": "gr_diavgeia", "source_url": f"{BASE}/decisions/{a['ada']}/document",
        "doc_type": "regulation" if a["decisionTypeId"] == "Α.2" else "decision", "language": "el",
        "title_native": a.get("subject"), "number": a.get("protocolNumber") or a["ada"],
        "adopted_date": iso(a.get("issueDate")), "published_date": iso(a.get("publishTimestamp")),
        "effective_date": None, "in_force": None, "consolidated": False, "content_format": "pdf_text", "text": text,
        "retrieved_at": utcnow(), "place_name": pl["place_name"] if pl else org.get("label"),
        "qid": pl["qid"] if pl else None, "iso_3166_2": None, "admin_level": "municipality",
        "platform": "diavgeia.gov.gr", "platform_place_id": a["organizationId"], "issuing_body_name": org.get("label"),
        "issuing_body_code": a["organizationId"], "level": "municipality",
        "place_match": (("diavgeia_org->code(gr_diavgeia_org)->place" if pl.get("via") == "code"
                         else f"diavgeia_org->translit({pl['score']})->candidate") if pl else "diavgeia_org_not_matched"),
        "ada": a["ada"], "decision_type": a["decisionTypeId"], "unit_ids": a.get("unitIds"),
        "thematic_category_ids": a.get("thematicCategoryIds"), "version_id": a.get("versionId"),
        "kanonistiki_praxi_type": (a.get("extraFieldValues") or {}).get("kanonistikipraxitype"),
        "fek": (a.get("extraFieldValues") or {}).get("fek"), "decision_page_url": url,
        "rights": "public-sector information, free reuse (Ν. 3861/2010 art. 1, Ν. 4727/2020 open data)",
    }


def fetch(sess, limit=None, test=None):
    done = Done(STATE / ("done_test.sqlite" if test else "done.sqlite"))
    ol = orgs(sess)
    om = {o["uid"]: o for o in ol}
    cand = [r for r in csv.DictReader(CAND.open(encoding="utf-8")) if r["country_code"] == "GR" and r["admin_level"] == "municipality"]
    asg = assign(GrPlaces(cand), ol, load_org_codes(), load_additions())   # exact gr_diavgeia_org code first, names only as fallback
    pmap = {uid: dict(place_id=r["place_id"], qid=r["qid"], place_name=r["place_name"], score=round(sc, 2), via=via)
            for uid, (r, sc, via) in asg.items()}
    log.info("place map: %d orgs, %d by code, %d by name", len(ol), sum(v["via"] == "code" for v in pmap.values()),
             sum(v["via"] == "name" for v in pmap.values()))
    osess = PoliteSession(log, min_interval=1.0, retries=1)    # old static host: single attempt, breaker decides
    brk = HostBreaker(OLD_HOST)
    stg = Stager("GR", "grdiav", log, max_docs=200, stage=(STAGE / "_test_gr") if test else STAGE).graceful(done)
    it = random.Random(11).sample(CAT.read_text(encoding="utf-8").splitlines(), test) if test else CAT.open(encoding="utf-8")
    n, seen = 0, set()
    for ln in it:
        if _STOP[0]:   # SIGTERM while docs keep failing (no add() call): flush here and exit
            log.info("SIGTERM: flushing %d buffered docs and exiting (resume with the same command)", len(stg.keys))
            stg.flush(done)
            sys.exit(0)
        a = json.loads(ln)
        did = a["ada"]
        if did in seen or done.has(did):
            continue
        seen.add(did)
        if limit and n >= limit:
            break
        n += 1
        url = f"{BASE}/decisions/{did}/document"
        try:
            r = get_document(sess, osess, brk, a, pmap.get(a["organizationId"]))
            if r is None:          # deferred (old static host unreachable / breaker open): not done, not failed
                continue
            text = pdf_text(r.content) if r.content[:4] == b"%PDF" else ""
            del r
            if body_len(text) < 80:
                with (STATE / "failed.jsonl").open("a", encoding="utf-8") as ff:
                    ff.write(json.dumps({"id": did, "pdf_url": url, "source_url": url, "host": "diavgeia.gov.gr",
                                         "place_id": (pmap.get(a["organizationId"]) or {}).get("place_id"),
                                         "org": a["organizationId"], "title": a.get("subject"),
                                         "reason": "no_text_layer", "at": utcnow()}, ensure_ascii=False) + "\n")
                stg.add(None, did, "no_text_layer")
            else:
                stg.add(build(a, text, pmap.get(a["organizationId"]), om.get(a["organizationId"], {})), did)
        except PermissionError as e:
            log.warning("robots skip %s: %s", did, e)
            stg.add(None, did, "robots_disallowed")
        except Exception as e:  # noqa: BLE001
            log.warning("FAIL %s: %s", did, str(e)[:200])
            with (STATE / "failed.jsonl").open("a", encoding="utf-8") as ff:
                ff.write(json.dumps({"id": did, "pdf_url": url, "source_url": url, "host": "diavgeia.gov.gr",
                                     "reason": str(e)[:300], "at": utcnow()}, ensure_ascii=False) + "\n")
        if stg.due():
            s = stg.flush(done)
            log.info("flush %s | done %d", dict(s), done.count())
            gc.collect()
    if stg.keys:
        s = stg.flush(done)
        log.info("flush %s | done %d", dict(s), done.count())
    log.info("fetch finished: %s places=%d deferred_oldhost=%d", dict(stg.total), len(stg.places), brk.n_deferred)


def status():
    stp = STATE / "catalog.state.json"
    st = json.loads(stp.read_text()) if stp.exists() else {"done": {}}
    ncat = sum(1 for _ in CAT.open()) if CAT.exists() else 0
    print("windows", len(st["done"]), "kept", sum(v["kept"] for v in st["done"].values()), "catalog rows", ncat,
          "complete", st.get("complete"), "done", Done(STATE / "done.sqlite").count())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["catalog", "fetch", "all", "status"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--test", type=int)
    ap.add_argument("--max-windows", type=int)
    a = ap.parse_args()
    if a.cmd == "status":
        return status()
    sess = PoliteSession(log, min_interval=1.0)
    stp = STATE / "catalog.state.json"
    if a.cmd == "catalog" or (a.cmd == "all" and not (stp.exists() and json.loads(stp.read_text()).get("complete"))):
        catalog(sess, a.max_windows)
    if a.cmd in ("fetch", "all"):
        fetch(sess, a.limit, a.test)


if __name__ == "__main__":
    main()
