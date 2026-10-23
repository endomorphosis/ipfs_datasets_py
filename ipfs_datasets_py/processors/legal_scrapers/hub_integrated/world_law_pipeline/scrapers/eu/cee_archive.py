#!/usr/bin/env python3
"""CEE municipal sites via the archive only (lane eu, 2026-10-18): target `cee` of `archive_q2.py run`.

Sites = SK/CZ/AT candidate municipalities whose own website council_docs.py (profiles sk/cz/at, live) could NOT use:
  * network_blocked  - the box gets a TLS reset / timeout / TLS name mismatch / DNS failure on the site (and its
                       robots.txt), so it is never crawled live;
  * robots_disallowed - live robots.txt (RFC 9309) disallows our UA; archived copies are tagged
                       source_policy=archived_robots_disallowed (never crawled live).
Per site (2026-10-18: Common Crawl FIRST when the CC index is up - one CC prefix listing per crawl, CC_CRAWLS newest,
<= CEE_CC_MAX_PAGES pages; Wayback only as fallback when CC is down/failed/empty): ONE Wayback CDX prefix listing
(host + www./bare variant, statuscode 200, collapse=urlkey, URL regex for the
act type: SK VZN, CZ obecně závazné vyhlášky / nařízení obce, AT Verordnungen), documents only (PDF/DOCX),
<= MAX_DOCS per site (newest first), body via the shared ArchiveFetcher (box-wide limiter + Wayback breaker).
Network-blocked hosts: the newest archived robots.txt is honoured (AJ.robots_for); a disallow there also gives
source_policy=archived_robots_disallowed.
Candidates are rebuilt from council_<cc>/done.sqlite + council_<cc>.log on every runner pass (the live runs are still
adding blocked sites). State: _state/archive/cee/{candidates.jsonl,done.txt,failed.jsonl,no_text.jsonl}.
Output: <CC>/<place_key>.<skvzn|czozv|atgvo>_archive_<UTC>p0001.jsonl (StagedWriter: validate + atomic).
Usage: python3 cee_archive.py build | test N | status
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
sys.path.insert(0, str(HERE))
os.environ.setdefault("ARCHIVE_LANE", "eu")
import archive_jobs as AJ  # noqa: E402
from archive import ArchiveFetcher, StagedWriter, provenance_fields  # noqa: E402
from archive.core import ArchiveTransient  # noqa: E402

log = AJ.log
D = AJ.STATE / "cee"
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
LOGS = AJ.STAGE / "_logs"
MAX_DOCS = 80
UA_TOKEN = "world-municipal-law-research/1.0"
CCS = {"SK": "sk", "CZ": "cz", "AT": "at"}
TAG = {"SK": "skvzn", "CZ": "czozv", "AT": "atgvo"}
LANG = {"SK": "sk", "CZ": "cs", "AT": "de"}
A, S, Z = r"(a|%c3%a1|%c3%a4)", r"(s|%c5%a1)", r"(z|%c5%be)"
URLRX = {   # Wayback CDX filter (Java regex, full match); percent-encoded diacritics included
    "SK": rf"(?i).*(vzn|v{S}eobecn[eé]?.?z{A}v{A}zn|nariaden).*\.(pdf|docx?)(\?.*)?",
    "CZ": rf"(?i).*(vyhl{A}{S}k|ozv|obecn(e|%c4%9b).?z{A}vazn|na(r|%c5%99)(i|%c3%ad)zen).*\.(pdf|docx?)(\?.*)?",
    "AT": r"(?i).*(verordnung|tarifordnung|geb(ue|u|%c3%bc)hrenordnung|abgabenordnung|satzung).*\.(pdf|docx?)(\?.*)?",
}
SKIP = re.compile(r"(?i)navrh|n%c3%a1vrh|entwurf|zapisnic|z%c3%a1pisnic|uznesen|protokoll|niederschrift")
RIGHTS = {
    "SK": "všeobecne záväzné nariadenie obce: právny predpis, excluded from copyright (zákon 185/2015 Z.z. § 5 písm. a)",
    "CZ": "obecně závazná vyhláška / nařízení obce: právní předpis, excluded from copyright (zákon 121/2000 Sb. § 3 písm. a)",
    "AT": "Verordnung des Gemeinderates: amtliches Werk, frei nach § 7 UrhG (AT)",
}
NUM = {
    "SK": re.compile(r"(?:VZN|nariadeni[ea])\s*(?:obce|mesta)?\s*(?:[čc]\.|[čc][íi]slo)?\s*(\d{1,3})\s*[/\-_]\s*((?:19|20)\d\d)", re.I),
    "CZ": re.compile(r"(?:vyhl[áa][šs]k[ay]|na[řr][íi]zen[íi])\s*(?:obce|m[ěe]sta)?[^\n]{0,40}?[čc]\.\s*(\d{1,3})\s*[/\-]\s*((?:19|20)\d\d)", re.I),
    "AT": None,
}


def host_of(u):
    u = re.split(r"[,\s]+", (u or "").strip())[0]
    return (urlparse(u if "://" in u else "https://" + u).hostname or "").lower()


def _log_reasons(cc):
    """host -> ('robots_disallowed'|'network_blocked', detail) from council_<cc>.log robots / home-failed lines."""
    rob, out = {}, {}
    p = LOGS / f"council_{CCS[cc]}.log"
    if not p.exists():
        return out
    rx_rob = re.compile(r"robots https://([^/\s]+)/robots\.txt -> (.+)$")
    rx_fail = re.compile(r"site (\S+) home failed: (.+)$")
    with p.open(encoding="utf-8", errors="replace") as f:
        for ln in f:
            m = rx_rob.search(ln)
            if m:
                rob[m.group(1).lower()] = m.group(2).strip()
                continue
            m = rx_fail.search(ln)
            if m:
                msg = m.group(2)
                h = host_of((re.findall(r"https?://\S+", msg) or [""])[0])
                st = rob.get(h, "")
                if "disallows" in msg and st.startswith(("200", "2")):
                    out[m.group(1)] = ("robots_disallowed", f"live robots.txt of {h} disallows our UA ({st})")
                else:
                    out[m.group(1)] = ("network_blocked", f"{h}: robots {st or '?'}; {msg[:120]}")
    return out


def build():
    """(Re)build candidates.jsonl from the live runs' failed sites. Idempotent; keeps done state."""
    D.mkdir(parents=True, exist_ok=True)
    cand = {}
    for r in csv.DictReader(CAND.open(encoding="utf-8")):
        if r["country_code"] in CCS and r["source_url"].strip():
            cand[r["place_id"]] = r
    rows, n = [], Counter()
    for cc, prof in CCS.items():
        db = AJ.STAGE / "_state" / f"council_{prof}" / "done.sqlite"
        if not db.exists():
            continue
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
        failed = [k[5:] for k, w in con.execute("select id, why from done where id like 'site:%'") if w == "site_home_failed"]
        con.close()
        why = _log_reasons(cc)
        for pid in failed:
            r = cand.get(pid)
            if not r:
                continue
            pol, basis = why.get(pid, ("network_blocked", "home page unreachable from the box"))
            h = host_of(r["source_url"])
            rows.append({"key": f"site:{cc}:{pid}", "cc": cc, "place_id": pid, "host": h, "policy": pol, "basis": basis})
            n[(cc, pol)] += 1
    tmp = D / ".candidates.tmp"
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, D / "candidates.jsonl")
    info = {"sites": len(rows), "by": {f"{a}/{b}": v for (a, b), v in sorted(n.items())}, "at": AJ.utcnow()}
    (D / "discover.json").write_text(json.dumps(info))
    return info


CC_MAX_PAGES = int(os.environ.get("CEE_CC_MAX_PAGES", "10"))   # CC index pages per crawl and site (bounded listing)
CC_DOWN_FAILS = 3                                               # cc_index consecutive failures => treat the index as down
SRC = Counter()                                                 # listing source per site, this process


def cc_index_up() -> bool:
    """CC index usable now? (shared limiter: < 3 consecutive cc_index failures, backoff <= 30 s, no 429/5xx cool-down)."""
    from archive import ratelimit
    st = ratelimit.status().get("cc_index", {})
    try:
        from archive import deferral
        cool = deferral.host_cooldown("index.commoncrawl.org")
    except ImportError:
        cool = 0.0
    return int(st.get("fails", 0) or 0) < CC_DOWN_FAILS and ratelimit.backoff_remaining("cc_index") <= 30 and cool <= 0


def _cc_list(fx, cand):
    """CC prefix listing of the site (SURT drops www., so one query per host), status:200 server-side, act-type URL
    regex applied locally. Page-capped (CEE_CC_MAX_PAGES per crawl: memory/time bound), so it uses the raw _cc_query
    inside the shared fetcher's call scope (round 3: at most ONE breaker failure per family for the whole listing)
    and normalises failures with the shared _as_deferral (AJ.as_deferral, typed .kind).
    Returns (caps, trunc, deferral): trunc None = every crawl listed completely; else the first reason
    ("deferred"/"timeout"/"busy"/... retryable, deferral set; "permanent" 400/404/410 crawl; "page_cap")."""
    from contextlib import nullcontext
    from archive.core import ArchiveDeferred, ArchiveError, merge_deferrals
    h = cand["host"]
    bare = h[4:] if h.startswith("www.") else h
    rx = re.compile(URLRX[cand["cc"]])
    caps, fails, trunc, defs = [], 0, None, []
    scope = getattr(fx, "_call_scope", None)
    with (scope() if scope else nullcontext()):
        try:
            crawls = fx.cc_crawls()
        except Exception as e:  # noqa: BLE001
            d = AJ.as_deferral(fx, e if isinstance(e, ArchiveError) else ArchiveError(f"crawl list: {e}"), "cc_index", bare)
            log.info("cee CC crawl list unavailable: %s", str(e)[:120])
            return [], "crawl_list_unavailable" if d is not None else "permanent", d
        flt = ["status:200"]
        for crawl in crawls:
            try:
                got = fx._cc_query(crawl, bare + "/", "prefix", limit_pages=CC_MAX_PAGES, filters=flt)
                caps += [c for c in got if rx.fullmatch(c.original_url) and c.status in (200, None)]
                fails = 0
                npg = fx.cache.cdx_get(f"CC|{crawl}|prefix|{bare}/|{'|'.join(flt)}|numpages", 3650)
                if isinstance(npg, int) and npg > CC_MAX_PAGES:
                    trunc = trunc or "page_cap"
            except Exception as e:  # noqa: BLE001
                e = e if isinstance(e, ArchiveError) else ArchiveError(f"crawl {crawl}: {type(e).__name__}: {e}")
                d = AJ.as_deferral(fx, e, "cc_index", bare)
                log.info("cee CC %s %s failed (%s): %s", crawl, bare, getattr(d, "reason", "permanent"), str(e)[:120])
                if d is None:
                    trunc = trunc or "permanent"
                    continue
                defs.append(d); trunc = trunc or getattr(d, "reason", "deferred")
                if isinstance(e, ArchiveDeferred):
                    break                     # host cooling down: the other crawls would defer too
                fails += 1
                if fails >= 2:
                    break
    return caps, trunc, (merge_deferrals(defs, f"cee CC listing {bare}") if defs else None)


def _dedupe(caps):
    seen, out = set(), []
    for c in sorted(caps, key=lambda c: c.timestamp, reverse=True):
        k = re.sub(r"^https?://(www\.)?", "", c.original_url.split("#")[0]).lower()
        if k in seen or SKIP.search(c.original_url):
            continue
        seen.add(k)
        out.append(c)
    return out


WB_MAX_ROWS = 20000


def list_docs(fx, cand):
    """Common Crawl FIRST when its index is up; the CC listing alone counts only if it is COMPLETE (no deferral, no
    failed crawl, no page cap) and found act documents. Otherwise the Wayback CDX prefix listing is added (wb_captures
    raises ArchiveDeferred on a throttle -> the site is requeued, never marked done on a partial listing).
    Returns (caps<=MAX_DOCS, n_unique_urls, source)."""
    src, cc = "wayback(cc_down)", []
    if fx.use_cc and cc_index_up():
        cc, trunc, _ccd = _cc_list(fx, cand)
        out = _dedupe(cc)
        if out and trunc is None:
            SRC["cc"] += 1
            return out[:MAX_DOCS], len(out), "cc"
        src = f"wayback+cc({trunc})" if trunc else "wayback(cc_empty)"
    h = cand["host"]
    hosts = [h, h[4:] if h.startswith("www.") else "www." + h]
    caps = list(cc)
    for x in hosts:
        try:            # round 3: transient (timeout/breaker/busy/throttle) -> ArchiveDeferred raised: site requeued
            got = AJ._wb_list(fx, x + "/", "prefix", collapse="urlkey", filters=[f"original:{URLRX[cand['cc']]}"],
                              max_rows=WB_MAX_ROWS)
        except ArchiveTransient:
            raise
        except Exception as e:  # noqa: BLE001 - permanent (403 excluded / 404): a final gap for this host
            log.info("cee Wayback listing %s permanent: %s", x, str(e)[:120])
            src += "+wb_permanent_gap"
            continue
        if len(got) >= WB_MAX_ROWS:
            src += "+wb_row_cap"            # design bound (<= MAX_DOCS docs/site anyway); logged, not a deferral
        caps += got
    out = _dedupe(caps)
    SRC[src] += 1
    return out[:MAX_DOCS], len(out), src


def _doc(fx, cap):
    """Fetch one listed document: its own capture first. A CC capture that yields nothing (genuine miss) or is deferred
    (cc_data 429/5xx) falls back to the newest Wayback captures of the same URL. Shared v3: fetch_best raises
    ArchiveDeferred when throttled; a CC deferral with no Wayback copy is re-raised (not a miss)."""
    from archive.core import ArchiveDeferred, ArchiveError, merge_deferrals
    ok = lambda d: d.body[:4] == b"%PDF" or d.body[:2] == b"PK"   # noqa: E731
    cc_def = None
    try:
        d = AJ.fbest(fx, [cap], max_tries=1, validator=ok)
    except ArchiveDeferred as e:
        if cap.source != "commoncrawl" or not fx.use_wayback:
            raise
        d, cc_def = None, e
    if d is None and cap.source == "commoncrawl" and fx.use_wayback:
        try:
            wb = fx.wb_captures(cap.original_url, "exact", limit=-3)
        except ArchiveError as e:     # round 3: transient -> ArchiveDeferred (prefer the CC one if any); permanent -> none
            dd = AJ.as_deferral(fx, e, "wayback", cap.original_url)
            if dd is not None:
                raise (merge_deferrals([cc_def, dd], "cee doc") if cc_def is not None else dd)
            wb = []
        d = AJ.fbest(fx, wb, max_tries=2, validator=ok) if wb else None
    if d is None and cc_def is not None:
        raise cc_def
    return d


def doc_text(d):
    b = d.body or b""
    if b[:4] == b"%PDF":
        return AJ.pdf_to_text(b), "pdf_text"
    if b[:2] == b"PK":
        import io
        import zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(b)) as z:
                x = z.read("word/document.xml").decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return "", "docx_text"
        from html import unescape
        return unescape(re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n", x))).strip(), "docx_text"
    return "", "unknown"


def record(cand, prow, d, text, fmt, policy, basis):
    cc = cand["cc"]
    u = d.original_url
    title = unquote(u.rsplit("/", 1)[-1].split("?")[0])
    title = re.sub(r"\.(pdf|docx?)$", "", title, flags=re.I).replace("_", " ").replace("-", " ").strip()
    first = next((ln.strip() for ln in text.splitlines() if len(ln.strip()) > 25), "")
    num = None
    if NUM[cc]:
        m = NUM[cc].search(title + " " + text[:600])
        if m:
            num = f"{m.group(1)}/{m.group(2)}"
    yr = re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", title) or re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", text[:1500])
    rec = {
        "place_id": cand["place_id"], "country_code": cc,
        "doc_id": f"{TAG[cc]}:{hashlib.sha1(re.sub(r'^https?://(www[.])?', '', u).lower().encode()).hexdigest()[:20]}",
        "source_platform": f"council_site_{cc.lower()}", "source_url": u, "doc_type": "ordinance", "language": LANG[cc],
        "title_native": (first if len(title) < 8 else title)[:500], "number": num, "adopted_date": None,
        "published_date": None, "effective_date": None, "in_force": None, "consolidated": False,
        "content_format": fmt, "text": text, "retrieved_at": AJ.utcnow(), "place_name": prow["place_name"],
        "qid": prow["qid"], "iso_3166_2": prow.get("iso_3166_2") or None, "admin_level": "municipality",
        "level": "municipality", "platform": "official_council_website", "platform_place_id": cand["host"],
        "place_match": "candidate_source_url_host", "year_hint": yr.group(1) if yr else None, "source_official": True,
        "rights": RIGHTS[cc], "access_basis": basis,
    }
    pf = provenance_fields(d, source_policy="archived_robots_disallowed", robots_basis=basis) if policy == "robots_disallowed" \
        else provenance_fields(d)
    rec.update(pf)
    if policy != "robots_disallowed":
        rec["extra_metadata"]["archive"]["live_access"] = f"network_blocked: {basis}"[:300]
    return rec


def live_runs_active() -> bool:
    import subprocess
    o = subprocess.run(["pgrep", "-f", r"council_docs.py (sk|cz|at) run"], capture_output=True, text=True)
    return bool(o.stdout.strip())


def fetch(limit=None, test=None, skip=frozenset()):
    """Same contract as archive_q2.fetch: {"todo", "deferred", "stopped"}."""
    import random
    info = build()
    log.info("cee candidates: %s", info)
    fx = AJ.new_fx()          # EU Wayback policy (common/eu_wayback.py)
    sfx = "_test" if test else ""
    done_p = D / f"done{sfx}.txt"
    done = AJ.load_done(done_p)
    cands = [json.loads(l) for l in (D / "candidates.jsonl").open(encoding="utf-8")]
    todo = [c for c in cands if c["key"] not in done and c["key"] not in skip]
    if test:
        todo = random.Random(9).sample(todo, min(test, len(todo)))
    if limit:
        todo = todo[:limit]
    prows = {r["place_id"]: r for r in csv.DictReader(CAND.open(encoding="utf-8")) if r["country_code"] in CCS}
    stage = AJ.STAGE / "_test_archive" if test else AJ.STAGE
    log.info("cee fetch: todo=%d done=%d", len(todo), len(done))
    deferred, why = [], Counter()
    paused, dnb = 0.0, {}       # 2026-10-18 v3: Wayback deferral -> pause the pass; deferred sites requeued for not_before

    def _defer(key, e, what):
        """Requeue `key` for e.not_before. Returns True instead (done-with-gaps, caller marks it done) once the key has
        been deferred EU_UNKNOWN_ERROR_CAP times for unknown_error only (shared module has no retry cap)."""
        nonlocal paused
        if AJ.unknown_capped("cee", key, e):
            why["unknown_error_cap"] += 1
            ff.write(json.dumps({"key": key, "why": "unknown_error_cap", "error": str(e)[:300], "at": AJ.utcnow()}) + "\n")
            ff.flush()
            return True
        nb, wbk = AJ.defer_info(e)
        deferred.append(key); dnb[key] = nb; why[what] += 1
        AJ.defer_log("cee", key, f"until {time.strftime('%H:%M:%S', time.localtime(nb))} {str(e)[:110]}")
        if wbk and not paused:
            paused = nb
            log.info("cee: Wayback deferred until %s; pausing pass", time.strftime("%H:%M:%S %Z", time.localtime(nb)))
        return False
    with done_p.open("a") as df, (D / f"failed{sfx}.jsonl").open("a") as ff, (D / f"no_text{sfx}.jsonl").open("a") as nf:
        for i, c in enumerate(todo, 1):
            if AJ.STOP[0] or paused:
                break
            AJ.item_reset()
            try:
                caps, nurl, lsrc = list_docs(fx, c)
            except ArchiveTransient as e:
                if _defer(c["key"], e, "deferred_listing"):
                    df.write(c["key"] + "\n"); df.flush(); done.add(c["key"])
                continue
            except Exception as e:  # noqa: BLE001
                why["listing_error"] += 1
                ff.write(json.dumps({"key": c["key"], "error": str(e)[:300], "at": AJ.utcnow()}) + "\n"); ff.flush()
                continue
            policy, basis = c["policy"], c["basis"]
            rb = None
            if policy == "network_blocked" and caps:
                try:
                    rb, rb_src = AJ.robots_for(fx, c["host"])
                except ArchiveTransient as e:   # archived robots.txt unknown (deferred): defer the site, nothing fetched
                    if _defer(c["key"], e, "deferred_robots"):
                        df.write(c["key"] + "\n"); df.flush(); done.add(c["key"])
                    continue
            rows, site_def, keys, site_e = [], 0, [], None
            for cap in caps:
                if AJ.STOP[0] or (site_e is not None and AJ.defer_info(site_e)[1]):
                    site_def += 1          # remaining docs of this site stay pending (SIGTERM / Wayback deferred)
                    break
                dk = "doc:" + hashlib.sha1(cap.original_url.encode()).hexdigest()[:20]
                if dk in done:
                    continue
                pol, bas = policy, basis
                if rb is not None and not rb.can_fetch(UA_TOKEN, cap.original_url):
                    pol, bas = "robots_disallowed", f"archived robots.txt ({rb_src}) disallows; live: {basis}"[:300]
                AJ.item_reset()
                try:
                    d = _doc(fx, cap)
                except ArchiveTransient as e:
                    site_def += 1
                    if site_e is None or AJ.defer_info(e)[0] < AJ.defer_info(site_e)[0]:
                        site_e = e
                    continue
                except Exception as e:  # noqa: BLE001
                    ff.write(json.dumps({"key": dk, "url": cap.original_url, "error": str(e)[:200]}) + "\n")
                    keys.append(dk)
                    continue
                if not d:
                    if AJ.ITEM_DEF[0]:
                        site_def += 1
                    else:
                        keys.append(dk); why["no_good_capture"] += 1
                    continue
                text, fmt = doc_text(d)
                keys.append(dk)
                if len(text.strip()) < 200:
                    why["no_text"] += 1
                    nf.write(json.dumps({"key": dk, "place_id": c["place_id"], "cc": c["cc"], "pdf_url": d.original_url,
                                         "archive_url": getattr(d, "archive_url", None), "reason": "no_text_layer"}) + "\n")
                    continue
                rows.append(record(c, prows[c["place_id"]], d, text, fmt, pol, bas))
                why["ok"] += 1
            ok = 0
            if rows:
                w = StagedWriter(stage, c["cc"], c["place_id"], batch_prefix=f"{TAG[c['cc']]}_archive_", chunk=10 ** 9)
                for r in rows:
                    err = w.add(r)
                    if err:
                        log.warning("invalid %s: %s", r["doc_id"], err)
                    else:
                        ok += 1
                w.flush()
            if site_def:
                if site_e is not None:
                    if _defer(c["key"], site_e, "site_deferred"):
                        keys.append(c["key"])
                else:              # breaker-open skips / SIGTERM: deferred, no not_before
                    deferred.append(c["key"]); why["site_deferred"] += 1
            else:
                keys.append(c["key"])
            for k in keys:
                df.write(k + "\n")
                done.add(k)
            df.flush(); os.fsync(df.fileno())
            log.info("cee %d/%d %s %s src=%s urls=%d fetched=%d staged=%d deferred_docs=%d | %s", i, len(todo), c["key"],
                     c["host"], lsrc, nurl, len(caps), ok, site_def, dict(why))
    stopped = AJ.STOP[0]
    if not test and live_runs_active():   # sites are still being added by the live runs: stay pending in the runner
        deferred.append("live_runs_active")
        if not todo and not paused:      # nothing to do yet: don't let the runner spin (<= 10 min, SIGTERM-aware)
            for _ in range(60):
                if AJ.STOP[0]:
                    break
                time.sleep(10)
    log.info("cee fetch %s (deferred %d) %s listing_src=%s", "stopped" if stopped else "finished", len(deferred), dict(why), dict(SRC))
    return {"todo": len(todo), "deferred": deferred, "stopped": stopped, "paused_until": paused, "deferred_nb": dnb}


if __name__ == "__main__":
    AJ.setup_logging("cee")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "build":
        print(build())
    elif cmd == "test":
        print(fetch(test=int(sys.argv[2]) if len(sys.argv) > 2 else 3))
    else:
        print((D / "discover.json").read_text() if (D / "discover.json").exists() else "-",
              "done", len(AJ.load_done(D / "done.txt")) if (D / "done.txt").exists() else 0)
