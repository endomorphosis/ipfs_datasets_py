"""New Zealand tranche 2 — driver.

Works the tranche-1 remaining worklist:
  live    — live retries for the robots-301 artifact class (050, 055)
            via the tranche-1 harvest (robots fetch now follows
            redirects).
  wairoa  — 029 fresh attempt: requests-based robots fetch (the
            pilot probe's requests fetch got 404/200 where curl
            empty-replies), then standard discovery/download/build;
            falls back to CDX if the live attempt fails.
  cdx     — Wayback CDX triage for live-phase dead ends, calling
            nz_tranche1.wayback_council() directly under ArchiveGate.
  deepen  — one extra enumeration pass for thin published councils:
            wider discovery, download only not-yet-ok documents,
            merged build, STRICT SUPERSET check against the live
            parquet (every live row must survive verbatim), only
            then supersede the council's two files; remote-verify.

All state stays in the tranche-1 state files (tranche1_manifest.json
is the 78-council ledger; fetch_manifest.json / run_manifest.json).
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# httpx (huggingface_hub) chokes on the bracketed IPv6 entries in the
# ambient no_proxy — same workaround nz_tranche1.hf_api applies, but
# needed here BEFORE any direct hf_hub_download call.
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
from urllib.parse import quote, urljoin, unquote, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

OUT = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files" / "nz_pilot"
sys.path.insert(0, str(OUT))

import nz_tranche1 as T  # noqa: E402

T.TODAY = "2026-10-14"
from nz_build3 import build_council  # noqa: E402
from nz_fetch import slugify  # noqa: E402
from nz_pilot_build import pdf_links  # noqa: E402
from nz_sites import SITES  # noqa: E402

AGENT = T.AGENT
UA = T.UA
REPO = T.REPO


def reset_rec(tm, code, note):
    rec = T.tm_record(tm, code)
    rec["status"] = "deferred"
    rec["category"] = None
    rec["evidence"] = (str(rec.get("evidence", "")) +
                       f" | tranche 2: {note}").strip(" |")
    rec["updated"] = T.TODAY
    T.tm_save(tm)
    return rec


# ------------------------------------------------------------------ live

def phase_live(codes):
    tm = T.load_tm()
    for code in codes:
        rec = T.tm_record(tm, code)
        if rec.get("status") == "published":
            print(f"[{code}] already published — skip", flush=True)
            continue
        reset_rec(tm, code, "live retry (robots-301 artifact class)")
        print(f"===== [{code}] {T.REG.get(code, code)} live retry =====", flush=True)
        try:
            T.harvest_live_council(tm, code)
        except BaseException as exc:  # noqa: BLE001
            rec = T.tm_record(tm, code)
            rec.update({"status": "dead_end", "category": "error",
                        "evidence": f"tranche 2 live retry exception: {type(exc).__name__}: {str(exc)[:200]}",
                        "updated": T.TODAY})
            T.tm_save(tm)
            print(f"[{code}] exception {exc}", flush=True)
        rec = T.tm_record(tm, code)
        print(f"[{code}] RESULT {rec.get('status')} [{rec.get('category')}] "
              f"rows={rec.get('rows')}", flush=True)
    print("LIVE RETRIES DONE")


# ------------------------------------------------------------------ wairoa

def fetch_robots_requests(base):
    """Bounded requests-based robots fetch for 029 (curl empty-replies
    on this host while requests worked in the pilot probe).
    Returns (parser_or_none, status_str, seconds)."""
    robots_url = base.rstrip("/") + "/robots.txt"
    t0 = time.monotonic()
    last = None
    for _attempt in range(2):
        try:
            r = requests.get(robots_url, headers={**UA, "Connection": "close"},
                             timeout=(20, 120))
            secs = round(time.monotonic() - t0, 1)
            if r.status_code == 200:
                rp = RobotFileParser()
                rp.set_url(robots_url)
                rp.parse(r.text.splitlines())
                return rp, "fetched", secs
            if r.status_code == 404:
                rp = RobotFileParser()
                rp.set_url(robots_url)
                rp.parse([])
                return rp, "fetched_404_allow_all", secs
            return None, f"http_{r.status_code}", secs
        except Exception as exc:  # noqa: BLE001
            last = f"error:{type(exc).__name__}"
            time.sleep(5)
    return None, last, round(time.monotonic() - t0, 1)


def wairoa_live(tm, code="029"):
    rec = T.tm_record(tm, code)
    name = T.REG.get(code, code)
    base = SITES[code][0]
    rec["base_url"] = base
    rec["status"] = "harvesting"
    T.tm_save(tm)
    t0 = time.monotonic()
    deadline = t0 + T.COUNCIL_SOFT_CAP
    sess = T.make_session()
    rp, rstatus, rsecs = fetch_robots_requests(base)
    print(f"[029] robots (requests) {rstatus} {rsecs}s", flush=True)
    if rp is None:
        rec.update({"status": "deferred", "category": "live_timeout",
                    "evidence": f"tranche 2 live attempt: requests robots fetch {rstatus} after {rsecs}s; falling back to CDX",
                    "wall_seconds": round(time.monotonic() - t0, 1), "updated": T.TODAY})
        T.tm_save(tm)
        print(f"[029] live robots failed ({rstatus}) — CDX fallback", flush=True)
        return False
    try:
        found = T.generic_discover(sess, base, deadline)
    except Exception as exc:  # noqa: BLE001
        rec.update({"status": "deferred", "category": "live_timeout",
                    "evidence": f"tranche 2 discovery failed: {type(exc).__name__}: {str(exc)[:160]}; CDX fallback",
                    "wall_seconds": round(time.monotonic() - t0, 1), "updated": T.TODAY})
        T.tm_save(tm)
        print(f"[029] discovery failed {exc} — CDX fallback", flush=True)
        return False
    print(f"[029] discovered {len(found)} bylaw PDFs", flush=True)
    if not found:
        rec.update({"status": "deferred", "category": "no_bylaws_found",
                    "evidence": "tranche 2 live discovery (requests robots OK) found no bylaw PDF links; CDX fallback",
                    "wall_seconds": round(time.monotonic() - t0, 1), "updated": T.TODAY})
        T.tm_save(tm)
        return False
    cdir = T.PDFS / code
    cdir.mkdir(exist_ok=True)
    _fm, fentry = T.fetch_entry(code)
    fentry.update({"name": name, "index_url": base,
                   "robots": {"status": rstatus, "seconds": rsecs,
                              "basis": "live re-check via requests (tranche 2)"},
                   "discovered": len(found)})
    files = []
    for i, (pdf_url, link_text) in enumerate(found, start=1):
        final_path = cdir / slugify(pdf_url, i)
        frec = {"url": pdf_url, "link_text": link_text,
                "path": str(final_path.relative_to(OUT)), "status": "failed",
                "source": None, "size": 0, "sha256": "", "seconds": 0.0,
                "attempts": 0, "errors": []}
        if rp is not None and not rp.can_fetch(AGENT, pdf_url):
            frec["status"] = "robots_disallowed"
            frec["errors"].append("robotparser can_fetch=False")
            files.append(frec)
            fentry["files"] = files
            T.save_fetch_entry(code, fentry)
            continue
        t1 = time.monotonic()
        ok, errors = T.download_live(sess, pdf_url, final_path)
        frec["errors"] = errors
        frec["seconds"] = round(time.monotonic() - t1, 1)
        frec["attempts"] = 1 + len([e for e in errors if e.startswith("live#")])
        if ok:
            data = final_path.read_bytes()
            frec.update({"status": "ok", "source": "live", "size": len(data),
                         "sha256": hashlib.sha256(data).hexdigest()})
            print(f"    DL OK {len(data)}B {pdf_url[:90]}", flush=True)
        files.append(frec)
        fentry["files"] = files
        T.save_fetch_entry(code, fentry)
    fentry["wall_seconds"] = round(time.monotonic() - t0, 1)
    T.save_fetch_entry(code, fentry)
    ok_files = [f for f in files if f["status"] == "ok"]
    rec["wall_seconds"] = round(time.monotonic() - t0, 1)
    if not ok_files:
        rec.update({"status": "deferred", "category": "live_timeout",
                    "evidence": "tranche 2 live: all PDF downloads failed; CDX fallback",
                    "updated": T.TODAY})
        T.tm_save(tm)
        print("[029] downloads failed — CDX fallback", flush=True)
        return False
    rec["docs"] = len(ok_files)
    T.tm_save(tm)
    try:
        T.build_and_publish(tm, code, "live")
    except BaseException as exc:  # noqa: BLE001
        rec.update({"status": "dead_end", "category": "build_gate_failed",
                    "evidence": f"tranche 2 build/gates failed: {str(exc)[:220]}",
                    "updated": T.TODAY})
        T.tm_save(tm)
        print(f"[029] BUILD FAILED {exc}", flush=True)
        return True  # attempted live to completion; not a CDX case
    return True


def phase_wairoa():
    tm = T.load_tm()
    rec = T.tm_record(tm, "029")
    if rec.get("status") == "published":
        print("[029] already published — skip")
        return
    reset_rec(tm, "029", "fresh attempt (live requests-robots, else CDX)")
    done = wairoa_live(tm)
    rec = T.tm_record(tm, "029")
    if not done and rec.get("status") != "published":
        gate = T.ArchiveGate(tm)
        try:
            T.wayback_council(tm, gate, "029")
        except T.ArchiveBackoff as exc:
            rec = T.tm_record(tm, "029")
            rec.update({"status": "dead_end", "category": "wayback_429_deferred",
                        "evidence": f"tranche 2 CDX fallback paused: {exc}",
                        "updated": T.TODAY})
            T.tm_save(tm)
            print(f"[029] CDX paused: {exc}", flush=True)
    rec = T.tm_record(tm, "029")
    print(f"[029] RESULT {rec.get('status')} [{rec.get('category')}] rows={rec.get('rows')}", flush=True)
    print("WAIROA DONE")


# ------------------------------------------------------------------ cdx

def phase_cdx(codes):
    tm = T.load_tm()
    gate = T.ArchiveGate(tm)
    for code in codes:
        rec = T.tm_record(tm, code)
        if rec.get("status") == "published":
            print(f"[wb {code}] already published — skip", flush=True)
            continue
        reset_rec(tm, code, "CDX triage (tranche 2 worklist B)")
        print(f"===== [wb {code}] {T.REG.get(code, code)} CDX triage =====", flush=True)
        try:
            T.wayback_council(tm, gate, code)
        except T.ArchiveBackoff as exc:
            print(f"CDX PHASE PAUSED at {code}: {exc} — remaining councils "
                  f"stay deferred for a later run", flush=True)
            rec = T.tm_record(tm, code)
            if rec.get("status") not in ("published", "dead_end"):
                rec.update({"status": "deferred", "category": "wayback_429_deferred",
                            "evidence": f"tranche 2 CDX triage paused by archive back-off: {exc}",
                            "updated": T.TODAY})
                T.tm_save(tm)
            return
        except BaseException as exc:  # noqa: BLE001
            rec = T.tm_record(tm, code)
            rec.update({"status": "dead_end", "category": "error",
                        "evidence": f"tranche 2 CDX exception: {type(exc).__name__}: {str(exc)[:200]}",
                        "updated": T.TODAY})
            T.tm_save(tm)
            print(f"[wb {code}] exception {exc}", flush=True)
        rec = T.tm_record(tm, code)
        print(f"[wb {code}] RESULT {rec.get('status')} [{rec.get('category')}] "
              f"rows={rec.get('rows')}", flush=True)
    print("CDX TRIAGE DONE")


# ------------------------------------------------------------------ deepen

def deepen_discover(sess, base, t_deadline, cap=16):
    """Wider enumeration than generic_discover: every bylaw PDF link
    across the homepage's bylaw pages + index guesses + detail hops."""
    def timed_out():
        return time.monotonic() > t_deadline

    found, seen = [], set()

    def add(url, text, page_is_bylaw_page):
        key = url.split("#")[0]
        if key in seen:
            return
        if "bylaw" in (unquote(url) + " " + (text or "")).lower() or page_is_bylaw_page:
            seen.add(key)
            found.append((url, text))

    home = T.fetch_html_curl(base.rstrip("/") + "/")
    soup = BeautifulSoup(home.text, "html.parser")
    candidates, cseen = [], set()
    for a in soup.find_all("a", href=True):
        full = urljoin(base, a["href"])
        text = a.get_text(" ", strip=True)
        if ".pdf" in full.lower():
            add(full, text, False)
        elif "bylaw" in (full + " " + text).lower() \
                and urlparse(full).netloc == urlparse(base).netloc and full not in cseen:
            cseen.add(full)
            candidates.append(full)
    for g in T.INDEX_GUESSES:
        u = base.rstrip("/") + g
        if u not in cseen:
            cseen.add(u)
            candidates.append(u)
    for cand in candidates[:6]:
        if timed_out() or len(found) >= cap:
            break
        try:
            page = T.fetch_html_curl(cand)
        except Exception:  # noqa: BLE001
            continue
        is_bylaw_page = "bylaw" in cand.lower()
        for u, t in pdf_links(cand, page.text):
            add(u, t, is_bylaw_page)
        if len(found) >= cap:
            break
        # detail hop: bylaw detail pages without direct PDFs
        soup2 = BeautifulSoup(page.text, "html.parser")
        details, dseen = [], set()
        for a in soup2.find_all("a", href=True):
            full = urljoin(cand, a["href"])
            text = a.get_text(" ", strip=True)
            if "bylaw" in (full + " " + text).lower() and ".pdf" not in full.lower() \
                    and urlparse(full).netloc == urlparse(base).netloc and full not in dseen:
                dseen.add(full)
                details.append(full)
        for d in details[:6]:
            if timed_out() or len(found) >= cap:
                break
            try:
                dp = T.fetch_html_curl(d)
            except Exception:  # noqa: BLE001
                continue
            for u, t in pdf_links(d, dp.text):
                add(u, t, True)
    return found[:cap]


def _rowset(table):
    rows = table.to_pylist()
    return {tuple(sorted((k, repr(v)) for k, v in r.items())) for r in rows}


def deepen_council(tm, code, max_docs=10):
    from huggingface_hub import hf_hub_download
    from world_municipal.parquet_io import read_html_parquet
    from world_municipal.schema import validate_table

    rec = T.tm_record(tm, code)
    name = T.REG.get(code, code)
    probe = T.load_json(T.PROBE_PATH, {})
    base = (probe.get(code) or {}).get("base") or SITES[code][0]
    live_rows_before = rec.get("rows", 0)
    print(f"===== [deepen {code}] {name} base={base} live rows={live_rows_before} =====",
          flush=True)
    t0 = time.monotonic()
    deadline = t0 + T.COUNCIL_SOFT_CAP
    sess = T.make_session()
    rp, rstatus, rsecs, _rt = T.fetch_robots_live(sess, base)
    print(f"[deepen {code}] robots {rstatus} {rsecs}s", flush=True)
    if rp is None:
        print(f"[deepen {code}] SKIP — robots {rstatus}", flush=True)
        return "robots"
    _fm, fentry = T.fetch_entry(code)
    files = list(fentry.get("files", []))
    ok_urls = {f["url"] for f in files if f.get("status") == "ok"}
    try:
        found = deepen_discover(sess, base, deadline)
    except Exception as exc:  # noqa: BLE001
        print(f"[deepen {code}] discovery failed: {exc}", flush=True)
        return "discovery_failed"
    new_cands = [(u, t) for (u, t) in found if u not in ok_urls]
    print(f"[deepen {code}] discovered {len(found)} bylaw PDFs, "
          f"{len(new_cands)} not yet ok", flush=True)
    if not new_cands:
        rec["evidence"] = (str(rec.get("evidence", "")) +
                           " | tranche 2 deepening: no new instruments found").strip(" |")
        rec["updated"] = T.TODAY
        T.tm_save(tm)
        return "no_new"
    cdir = T.PDFS / code
    cdir.mkdir(exist_ok=True)
    added = 0
    for pdf_url, link_text in new_cands:
        if len([f for f in files if f.get("status") == "ok"]) >= max_docs:
            print(f"[deepen {code}] doc cap {max_docs} reached", flush=True)
            break
        if rp is not None and not rp.can_fetch(AGENT, pdf_url):
            print(f"    ROBOTS DISALLOWED {pdf_url[:100]}", flush=True)
            continue
        # choose a fresh slug index beyond existing files in the dir
        existing_stems = {p.name for p in cdir.glob("*.pdf")}
        i = len(existing_stems) + 1
        final_path = cdir / slugify(pdf_url, i)
        while final_path.name in existing_stems:
            i += 1
            final_path = cdir / slugify(pdf_url, i)
        frec = {"url": pdf_url, "link_text": link_text,
                "path": str(final_path.relative_to(OUT)), "status": "failed",
                "source": None, "size": 0, "sha256": "", "seconds": 0.0,
                "attempts": 0, "errors": [], "tranche": 2}
        t1 = time.monotonic()
        ok, errors = T.download_live(sess, pdf_url, final_path)
        frec["errors"] = errors
        frec["seconds"] = round(time.monotonic() - t1, 1)
        frec["attempts"] = 1 + len([e for e in errors if e.startswith("live#")])
        if ok:
            data = final_path.read_bytes()
            frec.update({"status": "ok", "source": "live", "size": len(data),
                         "sha256": hashlib.sha256(data).hexdigest()})
            print(f"    DL OK {len(data)}B {pdf_url[:90]}", flush=True)
            added += 1
        # replace any prior failed record for the same URL, else append
        files = [f for f in files if f.get("url") != pdf_url]
        files.append(frec)
        fentry["files"] = files
        T.save_fetch_entry(code, fentry)
    ok_files = [f for f in files if f["status"] == "ok"]
    run_pre = T.load_json(T.RUN_PATH, {"councils": {}})
    built_docs = len((run_pre.get("councils", {}).get(code) or {}).get("docs", []))
    if not added and len(ok_files) <= built_docs:
        rec["evidence"] = (str(rec.get("evidence", "")) +
                           f" | tranche 2 deepening: {len(new_cands)} new candidates, all downloads failed").strip(" |")
        rec["updated"] = T.TODAY
        T.tm_save(tm)
        return "downloads_failed"
    if not added:
        print(f"[deepen {code}] resume: {len(ok_files)} ok files vs "
              f"{built_docs} built docs — proceeding to build", flush=True)
    return _deepen_build_publish(tm, code, name, rec, fentry, ok_files,
                                 added, live_rows_before)


def _deepen_build_publish(tm, code, name, rec, fentry, ok_files, added,
                          live_rows_before):
    """Shared deepening tail: snapshot live parquet, merged build,
    strict-superset gate, supersede upload, remote verify."""
    from huggingface_hub import hf_hub_download
    from world_municipal.parquet_io import read_html_parquet
    from world_municipal.schema import validate_table

    # snapshot live parquet for the superset check
    live_p = hf_hub_download(REPO, f"data/{code}_html.parquet",
                             repo_type="dataset", force_download=True)
    live_table = read_html_parquet(live_p)
    live_set = _rowset(live_table)
    try:
        res = build_council(code, ok_files)
    except BaseException as exc:  # noqa: BLE001
        print(f"[deepen {code}] BUILD FAILED {exc}", flush=True)
        return "build_failed"
    run = T.load_json(T.RUN_PATH, {"councils": {}})
    res["fetch_wall_seconds"] = fentry.get("wall_seconds")
    run["councils"][code] = res
    T.save_json(T.RUN_PATH, run)
    new_table = read_html_parquet(OUT / f"{code}_html.parquet")
    new_set = _rowset(new_table)
    if not live_set.issubset(new_set):
        missing = len(live_set - new_set)
        print(f"[deepen {code}] ABORT — new build is NOT a superset of live "
              f"({missing} live rows missing); not publishing", flush=True)
        return "not_superset"
    gain = new_table.num_rows - live_table.num_rows
    if gain <= 0:
        print(f"[deepen {code}] no row gain ({live_table.num_rows} -> "
              f"{new_table.num_rows}); not publishing", flush=True)
        return "no_gain"
    api, _existing = T.hf_api()
    for local, remote in [(OUT / f"{code}_html.parquet", f"data/{code}_html.parquet"),
                          (OUT / f"{code}_validation.json", f"data/{code}_validation.json")]:
        api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                        repo_id=REPO, repo_type="dataset")
        print(f"    uploaded {remote} (deepening supersede)", flush=True)
    # remote verify
    back_p = hf_hub_download(REPO, f"data/{code}_html.parquet",
                             repo_type="dataset", force_download=True)
    back = read_html_parquet(back_p)
    errs = validate_table(back, jurisdiction_id=code,
                          jurisdiction_name=name, country="NZ")
    assert not errs and back.num_rows == new_table.num_rows, \
        f"remote verify failed: rows {back.num_rows} vs {new_table.num_rows}, errs {errs}"
    rec.update({"docs": len(res.get("docs", [])), "rows": res.get("rows", 0),
                "status": "published", "published": True, "updated": T.TODAY})
    rec["evidence"] = (str(rec.get("evidence", "")) +
                       f" | tranche 2 deepening: +{added} docs, rows "
                       f"{live_rows_before} -> {res.get('rows')} (superset-verified, remote-verified)").strip(" |")
    T.tm_save(tm)
    print(f"[deepen {code}] PUBLISHED deepening: rows {live_rows_before} -> "
          f"{res.get('rows')} (+{gain})", flush=True)
    T.maybe_milestone(tm, code)
    return "published"


def phase_deepen(codes):
    tm = T.load_tm()
    for code in codes:
        try:
            outcome = deepen_council(tm, code)
        except BaseException as exc:  # noqa: BLE001
            outcome = f"exception: {type(exc).__name__}: {str(exc)[:200]}"
        print(f"[deepen {code}] OUTCOME {outcome}", flush=True)
    print("DEEPENING DONE")


def phase_deepen063wb():
    """063 Ashburton targeted recovery: live is WAF-blocked at robots
    now, so fetch the one failed instrument (Alcohol Control Bylaw
    2023) from its Wayback snapshot, then run the shared deepening
    build/publish tail (superset-gated)."""
    code = "063"
    tm = T.load_tm()
    gate = T.ArchiveGate(tm)
    rec = T.tm_record(tm, code)
    name = T.REG.get(code, code)
    live_rows_before = rec.get("rows", 0)
    _fm, fentry = T.fetch_entry(code)
    files = list(fentry.get("files", []))
    failed = [f for f in files if f.get("status") != "ok"]
    if not failed:
        print("[063wb] no failed files — nothing to recover", flush=True)
        return
    sess = T.make_session()
    recovered = 0
    for frec in failed:
        url = frec["url"]
        q = ("https://web.archive.org/cdx/search/cdx?url=" +
             quote(url, safe="") + "&output=json&filter=statuscode:200")
        try:
            gate.wait()
            gate.stamp()
            cp = subprocess.run(
                ["curl", "-s", "--max-time", "240", "-A", UA["User-Agent"],
                 "-w", "\n%{http_code}", q],
                capture_output=True, text=True, timeout=270)
        except Exception as exc:  # noqa: BLE001
            print(f"[063wb] CDX query failed: {exc}", flush=True)
            continue
        body, _, code_s = cp.stdout.rpartition("\n")
        http = int(code_s) if code_s.isdigit() else 0
        if http == 429:
            gate.hit_429()  # raises ArchiveBackoff
        rows = []
        try:
            rows = json.loads(body) if body.strip() else []
        except Exception:  # noqa: BLE001
            rows = []
        snaps = [r for r in rows[1:] if len(r) > 4 and r[4] == "200"] \
            if len(rows) > 1 else []
        if not snaps:
            print(f"[063wb] no 200 snapshots for {url[:90]} (HTTP {http})",
                  flush=True)
            continue
        ts = max(r[1] for r in snaps)
        final_path = OUT / frec["path"]
        ok, errors = T.wb_download(gate, sess,
                                    f"https://web.archive.org/web/{ts}id_/{url}",
                                    final_path)
        if ok:
            data = final_path.read_bytes()
            frec.update({"status": "ok", "source": "wayback",
                         "size": len(data),
                         "sha256": hashlib.sha256(data).hexdigest(),
                         "wayback_timestamp": ts, "errors": errors})
            recovered += 1
            print(f"[063wb] recovered {len(data)}B snapshot {ts} {url[:80]}",
                  flush=True)
        fentry["files"] = files
        T.save_fetch_entry(code, fentry)
    if not recovered:
        print("[063wb] nothing recovered — 063 stays as published", flush=True)
        return
    ok_files = [f for f in files if f["status"] == "ok"]
    outcome = _deepen_build_publish(tm, code, name, rec, fentry, ok_files,
                                    recovered, live_rows_before)
    print(f"[063wb] OUTCOME {outcome}", flush=True)


if __name__ == "__main__":
    phase = sys.argv[1]
    codes = sys.argv[2:]
    {"live": phase_live, "wairoa": lambda c: phase_wairoa(),
     "cdx": phase_cdx, "deepen": phase_deepen,
     "deepen063wb": lambda c: phase_deepen063wb()}[phase](codes)
