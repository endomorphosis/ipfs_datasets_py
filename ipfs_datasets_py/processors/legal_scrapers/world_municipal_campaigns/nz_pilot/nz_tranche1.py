"""New Zealand tranche 1 — campaign driver.

Extends ipfs_new_zealand_municipal_laws from the 2-council pilot seed
toward all 78 councils. Phases (subcommands), each resumable from the
checkpointed state files in this directory:

  probe    — group A (62 unattempted councils): robots.txt + homepage
             timing probe per candidate base; results in
             tranche1_probe.json; ordering fastest-first.
  harvest  — live harvest of probe-responsive group A councils, in
             probe order: robots re-check + generic bylaw discovery
             (homepage link walk -> index page -> PDF links, one detail
             hop if needed) -> checkpointed Range-resume downloads
             (LIVE ONLY — no archive.org in this phase) -> nz_build3
             gates -> per-council publish. Council soft cap 35 min.
  wayback  — gated Wayback phase for group B (pilot-documented
             live-hostile) + probe-failed group A councils. ALL
             archive.org traffic goes through ArchiveGate: single
             thread, >=12 s between requests, any 429 sets a >=35 min
             back-off (persisted) and ends the phase for this run.
             Wellington uses its pilot-recorded CDX timestamps first.
  publish  — retry publishing staged-but-unpublished councils;
             refresh coverage_report.md; remote-verify.
  status   — print campaign summary from the manifests.

State: tranche1_manifest.json (per-council record, rewritten after
every council), the pilot's fetch_manifest.json (per-file records,
nz_build3 input) and run_manifest.json (build results). Nothing here
touches 016/023 (published pilot seed).
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, unquote, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

OUT = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files" / "nz_pilot"
sys.path.insert(0, str(OUT))
sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers"))

import nz_pilot_build  # noqa: E402
from nz_pilot_build import PoliteSession, pdf_links  # noqa: E402
from nz_fetch import stream_download, slugify  # noqa: E402
from nz_sites import SITES, DONE, WAYBACK_FIRST, JS_GROUP  # noqa: E402

TM_PATH = OUT / "tranche1_manifest.json"
PROBE_PATH = OUT / "tranche1_probe.json"
FETCH_PATH = OUT / "fetch_manifest.json"
RUN_PATH = OUT / "run_manifest.json"
PDFS = OUT / "pdfs"
REPO = "endomorphosis/ipfs_new_zealand_municipal_laws"
TODAY = "2026-10-13"
SAMPLE = 4
AGENT = "world-municipal-law-pilot"
UA = nz_pilot_build.UA
COUNCIL_SOFT_CAP = 35 * 60
ARCHIVE_MIN_GAP = 12.0
ARCHIVE_BACKOFF = 35 * 60

REG = {json.loads(ln)["jurisdiction_id"]: json.loads(ln)["jurisdiction_name"]
       for ln in (OUT / "jurisdictions.jsonl").read_text().splitlines()}


def curl_url(url):
    """Percent-encode characters curl rejects in a URL argument.
    Literal spaces in WordPress upload filenames (e.g. swdc.govt.nz
    'Part 5 Water Supply Bylaw_Current_0.pdf') caused curl exit 3
    (URL malformed) on every attempt — found in tranche 2. Existing
    %XX sequences and URL punctuation are preserved."""
    from urllib.parse import quote
    return quote(url, safe=":/?#[]@!$&'()*+,;=%~")


# ------------------------------------------------------------------ state

def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            return default
    return default


def save_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False))
    tmp.rename(path)


def load_tm():
    tm = load_json(TM_PATH, {"councils": {}, "archive_backoff_until": 0,
                             "milestones_done": [], "started": TODAY})
    return tm


def tm_record(tm, code):
    rec = tm["councils"].get(code)
    if rec is None:
        group = "B" if code in WAYBACK_FIRST else ("C" if code in JS_GROUP else "A")
        rec = {"code": code, "name": REG.get(code, code), "group": group,
               "status": "pending", "category": None, "route": None,
               "docs": 0, "rows": 0, "wall_seconds": None, "evidence": "",
               "base_url": None, "published": False, "updated": None}
        tm["councils"][code] = rec
    return rec


def tm_save(tm):
    """Merge-on-save: several campaign processes may run concurrently
    (probe + harvest + kapiti), each mutating only its own councils'
    records. Disk state wins for records this process hasn't touched;
    this process's in-memory records win for its own councils."""
    disk = load_json(TM_PATH, None)
    if disk:
        merged = dict(disk)
        dc = dict(disk.get("councils", {}))
        dc.update(tm.get("councils", {}))
        merged["councils"] = dc
        merged["archive_backoff_until"] = max(
            float(disk.get("archive_backoff_until") or 0),
            float(tm.get("archive_backoff_until") or 0))
        merged["milestones_done"] = sorted(
            set(disk.get("milestones_done", [])) | set(tm.get("milestones_done", [])))
        tm.clear()
        tm.update(merged)
    save_json(TM_PATH, tm)


def fetch_entry(code):
    fm = load_json(FETCH_PATH, {"councils": {}})
    return fm, fm["councils"].get(code, {})


def save_fetch_entry(code, entry):
    fm = load_json(FETCH_PATH, {"councils": {}})
    fm["councils"][code] = entry
    save_json(FETCH_PATH, fm)


# ------------------------------------------------------------------ probe

def probe_one(url, attempts=2, timeout=(20, 120)):
    """Bounded timing probe: (status_or_error, seconds, bytes)."""
    t0 = time.monotonic()
    last = None
    for a in range(attempts):
        try:
            with requests.get(url, headers={**UA, "Connection": "close"},
                              timeout=timeout, stream=True) as r:
                n = 0
                for chunk in r.iter_content(chunk_size=32768):
                    n += len(chunk)
                    if n > 2_000_000:
                        break
                return r.status_code, round(time.monotonic() - t0, 1), n
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}"
            time.sleep(5)
    return f"error:{last}", round(time.monotonic() - t0, 1), 0


def _apply_probe(rec, best):
    rec["base_url"] = best.get("base")
    if best.get("score") is not None:
        rec["status"] = "probe_ok"
        rec["category"] = None
        rec["evidence"] = (f"probe: robots {best['robots_status']} in "
                           f"{best['robots_seconds']}s, home {best.get('home_status')} "
                           f"in {best.get('home_seconds')}s")
    elif isinstance(best.get("robots_status"), int):
        rec["status"] = "probe_blocked"
        rec["category"] = "waf_block"
        rec["evidence"] = f"probe: robots.txt HTTP {best['robots_status']} from this egress"
    else:
        rec["status"] = "probe_slow"
        rec["category"] = "live_timeout"
        rec["evidence"] = f"probe: robots.txt {best.get('robots_status')} after {best.get('robots_seconds')}s"
    rec["updated"] = TODAY


def phase_probe():
    tm = load_tm()
    probe = load_json(PROBE_PATH, {})
    # reconcile: re-assert tm records for councils already in probe.json
    for code, v in probe.items():
        if v.get("done"):
            rec = tm_record(tm, code)
            if rec.get("status") in ("pending", "probe_ok", "probe_blocked", "probe_slow"):
                _apply_probe(rec, v)
    tm_save(tm)
    group_a = [c for c in sorted(SITES) if c not in DONE
               and c not in WAYBACK_FIRST and c not in JS_GROUP]
    for code in group_a:
        if code in probe and probe[code].get("done"):
            continue
        rec = tm_record(tm, code)
        name = REG.get(code, code)
        best = None
        for base in SITES[code]:
            rs, rsec, _rb = probe_one(base + "/robots.txt")
            entry = {"base": base, "robots_status": rs, "robots_seconds": rsec}
            print(f"[probe {code}] {name} {base} robots={rs} {rsec}s", flush=True)
            if isinstance(rs, int) and rs in (200, 404):
                hs, hsec, _hb = probe_one(base + "/", attempts=1)
                entry.update({"home_status": hs, "home_seconds": hsec,
                              "score": round(rsec + (hsec if isinstance(hs, int) else 300), 1)})
                print(f"[probe {code}] home={hs} {hsec}s score={entry['score']}", flush=True)
                best = entry
                break
            entry["score"] = None
            if best is None:
                best = entry
        best["done"] = True
        probe[code] = best
        save_json(PROBE_PATH, probe)
        _apply_probe(rec, best)
        tm_save(tm)
    print("PROBE COMPLETE")


def probe_order():
    probe = load_json(PROBE_PATH, {})
    ok = [(v.get("score", 1e9), c) for c, v in probe.items() if v.get("score") is not None]
    return [c for _s, c in sorted(ok)]


# ------------------------------------------------------------------ HF

_api = None
_existing = None


def hf_api():
    global _api, _existing
    if _api is not None:
        return _api, _existing
    os.environ["no_proxy"] = "localhost,127.0.0.1"
    os.environ["NO_PROXY"] = "localhost,127.0.0.1"
    sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
    from dynamic_credentials import dynamic_credential_entry
    from huggingface_hub import HfApi
    token = dynamic_credential_entry("custom.huggingface")["surrogate"]
    if not token:
        raise RuntimeError("no HF surrogate from vault")
    _api = HfApi(token=token)
    info = _api.dataset_info(REPO)
    _existing = {s.rfilename for s in info.siblings or []}
    return _api, _existing


def publish_council(code):
    """Upload data/<code>_html.parquet + validation sidecar. True if live."""
    global _existing
    api, existing = hf_api()
    want = [(OUT / f"{code}_html.parquet", f"data/{code}_html.parquet"),
            (OUT / f"{code}_validation.json", f"data/{code}_validation.json")]
    for local, remote in want:
        if not local.exists():
            raise RuntimeError(f"missing local {local}")
        if remote in existing:
            continue
        api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                        repo_id=REPO, repo_type="dataset")
        existing.add(remote)
        print(f"    uploaded {remote}", flush=True)
    return True


def refresh_coverage_and_verify(sample_code):
    """Regenerate coverage_report.md from manifests, upload, verify live."""
    api, _existing = hf_api()
    run = load_json(RUN_PATH, {"councils": {}})
    tm = load_tm()
    published = {}
    for code, v in run.get("councils", {}).items():
        if v.get("valid"):
            published[code] = {"docs": len(v.get("docs", [])), "rows": v.get("rows", 0),
                               "route": "live (pilot)"}
    for code, r in tm["councils"].items():
        if r.get("published"):
            published[code] = {"docs": r.get("docs", 0), "rows": r.get("rows", 0),
                               "route": r.get("route") or "live"}
    total_rows = sum(v["rows"] for v in published.values())
    total_docs = sum(v["docs"] for v in published.values())
    dead = {c: r for c, r in tm["councils"].items() if r.get("status") == "dead_end"}
    lines = [
        "# Coverage report — New Zealand municipal laws",
        "",
        f"Updated {TODAY} (tranches 1 + 2). New Zealand has **78 local "
        "authorities**: 67 territorial authorities (Stats NZ TA2023 codes) and "
        "11 regional councils (\"R\" + ISO 3166-2:NZ). Full registry in "
        "`jurisdictions.jsonl`.",
        "",
        "## Route",
        "",
        "Per-council harvest of bylaw PDFs from councils' own websites (no "
        "aggregator carries NZ council bylaws), robots-checked per council, "
        "normalized into the world_municipal 19-column schema. Hostile/slow "
        "hosts are harvested from Wayback Machine snapshots of the same "
        "public URLs where available (route column). Fetch is checkpointed "
        "and Range-resumed; pacing 6.5 s between requests per council (or "
        "the site's longer Crawl-delay).",
        "",
        "## Status",
        "",
        f"**{len(published)} of 78 councils published** "
        f"({total_docs} bylaws, {total_rows} section rows). "
        f"{len(dead)} documented dead ends so far (below).",
        "",
        "| Code | Council | Bylaws | Rows | Route |",
        "|---|---|---|---|---|",
    ]
    for code in sorted(published):
        v = published[code]
        lines.append(f"| {code} | {REG.get(code, code)} | {v['docs']} | {v['rows']} | {v['route']} |")
    if dead:
        lines += ["", "## Dead ends (documented, tranches 1 + 2 + pilot)", ""]
        for code in sorted(dead):
            r = dead[code]
            lines.append(f"- {code} {REG.get(code, code)} — [{r.get('category')}] "
                         f"{str(r.get('evidence', ''))[:220]}")
    lines += ["", "Councils not listed are unattempted or in progress; see "
                  "the tranche reports in the program workspace."]
    (OUT / "coverage_report.md").write_text("\n".join(lines) + "\n")
    api.upload_file(path_or_fileobj=str(OUT / "coverage_report.md"),
                    path_in_repo="coverage_report.md", repo_id=REPO,
                    repo_type="dataset")
    # remote verification: fresh listing + re-download/re-validate a sample
    info = api.dataset_info(REPO)
    now = sorted(s.rfilename for s in info.siblings or [])
    from huggingface_hub import hf_hub_download
    from world_municipal.parquet_io import read_html_parquet
    from world_municipal.schema import validate_table
    p = hf_hub_download(REPO, f"data/{sample_code}_html.parquet", repo_type="dataset")
    t = read_html_parquet(p)
    errs = validate_table(t, jurisdiction_id=sample_code,
                          jurisdiction_name=REG.get(sample_code, sample_code), country="NZ")
    assert not errs, f"remote re-validation failed for {sample_code}: {errs}"
    print(f"COVERAGE REFRESHED: {len(now)} remote files; sample {sample_code} "
          f"re-validated ({t.num_rows} rows)", flush=True)
    return len(now)


def maybe_milestone(tm, code):
    n_pub = sum(1 for r in tm["councils"].values() if r.get("published"))
    total_pub = 2 + n_pub
    for m in (10, 20, 30, 40, 50, 60, 70):
        if total_pub >= m and m not in tm["milestones_done"]:
            try:
                refresh_coverage_and_verify(code)
                tm["milestones_done"].append(m)
                tm_save(tm)
            except Exception as exc:  # noqa: BLE001
                print(f"    milestone {m} refresh failed: {exc}", flush=True)
            break


# ------------------------------------------------------------------ live harvest

def make_session():
    sess = PoliteSession()
    orig_get = sess.get
    sess.get = lambda url, timeout=300, **kw: orig_get(url, timeout=timeout, **kw)
    return sess


def fetch_robots_live(sess, base):
    """(parser_or_none, status_str, seconds, raw_text).

    Deliberately NOT PoliteSession: its 3x300 s retry loop turns a
    definitive 404 into a 15-minute stall and can end on a timeout
    instead of the 404. Bounded raw requests (2 attempts, 150 s read):
    200 -> parsed rules; 404 -> no robots.txt (allow-all, empty
    parser); other HTTP codes (403/202/406...) -> WAF posture signal,
    status "http_<code>", no parser; transport errors -> status
    "error:<type>". (sess is accepted for signature compatibility.)"""
    robots_url = base.rstrip("/") + "/robots.txt"
    t0 = time.monotonic()
    last = None
    for attempt in range(2):
        # curl with --max-time: a hard TOTAL cap. A plain requests.get
        # was observed wedged >25 min on a trickling proxy read that
        # kept resetting the per-read timeout (harvest run 2, 063).
        try:
            cp = subprocess.run(
                ["curl", "-sL", "--max-time", "150", "-A", UA["User-Agent"],
                 "-w", "\n%{http_code}", robots_url],
                capture_output=True, text=True, timeout=170)
            secs = round(time.monotonic() - t0, 1)
            body, _, code_s = cp.stdout.rpartition("\n")
            code = int(code_s) if code_s.isdigit() else 0
            if cp.returncode != 0 or code == 0:
                last = f"error:curl{cp.returncode}"
                time.sleep(5)
                continue
            if code == 200:
                rp = RobotFileParser()
                rp.set_url(robots_url)
                rp.parse(body.splitlines())
                return rp, "fetched", secs, body
            if code == 404:
                rp = RobotFileParser()
                rp.set_url(robots_url)
                rp.parse([])
                return rp, "fetched_404_allow_all", secs, ""
            return None, f"http_{code}", secs, ""
        except Exception as exc:  # noqa: BLE001
            last = f"error:{type(exc).__name__}"
            time.sleep(5)
    return None, last, round(time.monotonic() - t0, 1), ""


INDEX_GUESSES = ["/bylaws", "/your-council/bylaws", "/council/bylaws",
                 "/policies-and-bylaws", "/your-council/policies-and-bylaws",
                 "/documents/bylaws"]


class _HtmlPage:
    def __init__(self, text):
        self.text = text


def fetch_html_curl(url, max_time=120):
    """Hard-capped HTML fetch via curl subprocess (same rationale as
    fetch_robots_live: per-read timeouts on streamed sessions can be
    evaded indefinitely by trickling hosts). 2 attempts; raises
    ConnectionError on transport failure. HTTP error statuses return
    their body (no links will be found in it — discovery moves on)."""
    last = None
    for _attempt in range(2):
        try:
            cp = subprocess.run(
                ["curl", "-sL", "--max-time", str(max_time),
                 "-A", UA["User-Agent"], curl_url(url)],
                capture_output=True, text=True, timeout=max_time + 30)
            if cp.returncode == 0 and cp.stdout:
                return _HtmlPage(cp.stdout)
            last = f"curl{cp.returncode}"
        except Exception as exc:  # noqa: BLE001
            last = type(exc).__name__
        time.sleep(5)
    raise requests.ConnectionError(f"fetch_html_curl failed for {url}: {last}")


def generic_discover(sess, base, t_deadline):
    """Find up to SAMPLE bylaw PDF (url, link_text) pairs for a council."""
    def timed_out():
        return time.monotonic() > t_deadline

    def bylaw_pdfs(page_url, html_text, page_is_bylaw_page=False):
        all_pdfs = pdf_links(page_url, html_text)
        hits = [(u, t) for (u, t) in all_pdfs
                if "bylaw" in (unquote(u) + " " + t).lower()]
        if hits:
            return hits
        return all_pdfs if page_is_bylaw_page else []

    home = fetch_html_curl(base.rstrip("/") + "/")
    soup = BeautifulSoup(home.text, "html.parser")
    candidates, seen = [], set()
    for a in soup.find_all("a", href=True):
        full = urljoin(base, a["href"])
        text = a.get_text(" ", strip=True)
        if "bylaw" in (full + " " + text).lower() and ".pdf" not in full.lower() \
                and urlparse(full).netloc == urlparse(base).netloc and full not in seen:
            seen.add(full)
            candidates.append(full)
    for g in INDEX_GUESSES:
        u = base.rstrip("/") + g
        if u not in seen:
            seen.add(u)
            candidates.append(u)
    tried = 0
    for cand in candidates:
        if tried >= 4 or timed_out():
            break
        tried += 1
        try:
            page = fetch_html_curl(cand)
        except Exception:  # noqa: BLE001
            continue
        is_bylaw_page = "bylaw" in cand.lower()
        hits = bylaw_pdfs(cand, page.text, is_bylaw_page)
        if hits:
            return hits[:SAMPLE]
        # one detail hop (Wellington pattern): follow bylaw detail pages
        soup2 = BeautifulSoup(page.text, "html.parser")
        details, dseen = [], set()
        for a in soup2.find_all("a", href=True):
            full = urljoin(cand, a["href"])
            text = a.get_text(" ", strip=True)
            if "bylaw" in (full + " " + text).lower() and ".pdf" not in full.lower() \
                    and urlparse(full).netloc == urlparse(base).netloc and full not in dseen:
                dseen.add(full)
                details.append(full)
        collected = []
        for d in details[:6]:
            if timed_out():
                break
            try:
                dp = fetch_html_curl(d)
            except Exception:  # noqa: BLE001
                continue
            sub = bylaw_pdfs(d, dp.text, True)
            if sub:
                collected.append(sub[0])
            if len(collected) >= SAMPLE:
                break
        if collected:
            return collected[:SAMPLE]
    return []


def download_live(sess, url, final_path):
    """Range-resume live download via curl. (ok, errors list).

    The requests/PoliteSession streaming path ProxyError'd at 0 B on
    every attempt for orc.govt.nz PDFs while curl pulled the same
    19 MB bylaw in 19 s — so downloads use curl with a hard --max-time
    cap and -C - resume against the .part file (same checkpoint
    contract as nz_fetch.stream_download). No archive.org here."""
    if final_path.exists() and final_path.stat().st_size > 0 \
            and final_path.open("rb").read(4) == b"%PDF":
        return True, []
    part = final_path.with_suffix(".pdf.part")
    errors = []
    for attempt in range(1, 5):
        if attempt > 1:
            time.sleep(min(60, 5 * attempt))
        have = part.stat().st_size if part.exists() else 0
        cmd = ["curl", "-sL", "--fail", "--max-time", "900",
               "-A", UA["User-Agent"], "-o", str(part)]
        if have > 0:
            cmd += ["-C", "-"]
        cmd.append(curl_url(url))
        try:
            cp = subprocess.run(cmd, capture_output=True, text=True, timeout=960)
            rc = cp.returncode
        except Exception as exc:  # noqa: BLE001
            rc = -1
            errors.append(f"live#{attempt}: {type(exc).__name__}: {str(exc)[:110]}")
            print(f"    DL FAIL #{attempt} {type(exc).__name__} at {have}B {url[:90]}", flush=True)
            continue
        if rc == 0:
            break
        errors.append(f"live#{attempt}: curl{rc} at {part.stat().st_size if part.exists() else 0}B")
        print(f"    DL FAIL #{attempt} curl{rc} at "
              f"{part.stat().st_size if part.exists() else 0}B {url[:90]}", flush=True)
        if rc == 33:  # server does not support Range resume — start fresh
            part.unlink(missing_ok=True)
    else:
        return False, errors
    if part.exists() and part.stat().st_size > 0 and part.open("rb").read(4) == b"%PDF":
        part.rename(final_path)
        return True, errors
    errors.append("live: bytes lack %PDF magic")
    part.unlink(missing_ok=True)
    return False, errors


def build_and_publish(tm, code, route):
    """Build from fetch_manifest ok files; publish; update manifests."""
    from nz_build3 import build_council
    _fm, entry = fetch_entry(code)
    ok_files = [f for f in entry.get("files", []) if f.get("status") == "ok"]
    if not ok_files:
        return False
    res = build_council(code, ok_files)
    res["fetch_wall_seconds"] = entry.get("wall_seconds")
    run = load_json(RUN_PATH, {"retrieved": TODAY, "councils": {}})
    run["councils"][code] = res
    save_json(RUN_PATH, run)
    rec = tm_record(tm, code)
    rec.update({"status": "built", "route": route, "docs": len(res.get("docs", [])),
                "rows": res.get("rows", 0)})
    try:
        publish_council(code)
        rec["status"] = "published"
        rec["published"] = True
        print(f"[{code}] PUBLISHED {res.get('rows')} rows", flush=True)
    except Exception as exc:  # noqa: BLE001
        rec["status"] = "staged"
        rec["evidence"] = (rec.get("evidence", "") +
                           f" | publish failed (egress?): {type(exc).__name__}: {str(exc)[:120]}").strip(" |")
        print(f"[{code}] built but publish failed: {exc}", flush=True)
    rec["updated"] = TODAY
    tm_save(tm)
    maybe_milestone(tm, code)
    return True


def harvest_live_council(tm, code):
    rec = tm_record(tm, code)
    name = REG.get(code, code)
    probe = load_json(PROBE_PATH, {})
    base = (probe.get(code) or {}).get("base") or SITES[code][0]
    rec["base_url"] = base
    rec["status"] = "harvesting"
    tm_save(tm)
    t0 = time.monotonic()
    deadline = t0 + COUNCIL_SOFT_CAP
    sess = make_session()
    rp, rstatus, rsecs, rtext = fetch_robots_live(sess, base)
    print(f"[{code}] {name} robots {rstatus} {rsecs}s base={base}", flush=True)
    if rp is not None:
        cd = None
        try:
            cd = rp.crawl_delay(AGENT)
        except Exception:  # noqa: BLE001
            cd = None
        if cd and cd > nz_pilot_build.DELAY:
            nz_pilot_build.DELAY = float(cd)
            print(f"[{code}] respecting Crawl-delay {cd}s", flush=True)
    elif rstatus.startswith("error"):
        # A transport failure at the robots step is NOT evidence about
        # the council (the 2026-10-13 egress-proxy degradation killed 23
        # consecutive councils this way). Record as retryable deferred.
        rec.update({"status": "deferred", "category": "live_timeout",
                    "evidence": f"robots.txt re-check in harvest: {rstatus} after {rsecs}s — transport failure (egress or host); retryable, not a dead end",
                    "wall_seconds": round(time.monotonic() - t0, 1), "updated": TODAY})
        tm_save(tm)
        print(f"[{code}] DEFERRED live_timeout (robots {rstatus})", flush=True)
        return "transport_fail"
    elif rstatus.startswith("http_"):
        rec.update({"status": "dead_end", "category": "waf_block",
                    "evidence": f"robots.txt re-check in harvest: {rstatus} after {rsecs}s; deferred to Wayback triage",
                    "wall_seconds": round(time.monotonic() - t0, 1), "updated": TODAY})
        tm_save(tm)
        print(f"[{code}] DEAD_END waf_block (robots {rstatus})", flush=True)
        return
    # discovery
    try:
        found = generic_discover(sess, base, deadline)
    except Exception as exc:  # noqa: BLE001
        rec.update({"status": "dead_end", "category": "live_timeout",
                    "evidence": f"discovery failed: {type(exc).__name__}: {str(exc)[:160]}",
                    "wall_seconds": round(time.monotonic() - t0, 1), "updated": TODAY})
        tm_save(tm)
        print(f"[{code}] DEAD_END discovery {exc}", flush=True)
        return "transport_fail"
    print(f"[{code}] discovered {len(found)} bylaw PDFs", flush=True)
    if not found:
        rec.update({"status": "dead_end", "category": "no_bylaws_found",
                    "evidence": "homepage + bylaw-link walk + path guesses yielded no bylaw PDF links (pages loaded)",
                    "wall_seconds": round(time.monotonic() - t0, 1), "updated": TODAY})
        tm_save(tm)
        print(f"[{code}] DEAD_END no_bylaws_found", flush=True)
        return
    cdir = PDFS / code
    cdir.mkdir(exist_ok=True)
    _fm, fentry = fetch_entry(code)
    fentry.update({"name": name, "index_url": base,
                   "robots": {"status": rstatus, "seconds": rsecs, "basis": "live re-check (tranche 1)"},
                   "discovered": len(found)})
    files = []
    disallowed = 0
    for i, (pdf_url, link_text) in enumerate(found, start=1):
        final_path = cdir / slugify(pdf_url, i)
        frec = {"url": pdf_url, "link_text": link_text,
                "path": str(final_path.relative_to(OUT)), "status": "failed",
                "source": None, "size": 0, "sha256": "", "seconds": 0.0,
                "attempts": 0, "errors": []}
        if rp is not None and not rp.can_fetch(AGENT, pdf_url):
            frec["status"] = "robots_disallowed"
            frec["errors"].append("robotparser can_fetch=False")
            disallowed += 1
            print(f"    ROBOTS DISALLOWED {pdf_url[:100]}", flush=True)
            files.append(frec)
            fentry["files"] = files
            save_fetch_entry(code, fentry)
            continue
        t1 = time.monotonic()
        ok, errors = download_live(sess, pdf_url, final_path)
        frec["errors"] = errors
        frec["seconds"] = round(time.monotonic() - t1, 1)
        frec["attempts"] = 1 + len([e for e in errors if e.startswith("live#")])
        if ok:
            data = final_path.read_bytes()
            frec.update({"status": "ok", "source": "live", "size": len(data),
                         "sha256": hashlib.sha256(data).hexdigest()})
            print(f"    DL OK {len(data)}B {frec['seconds']}s {pdf_url[:90]}", flush=True)
        files.append(frec)
        fentry["files"] = files
        save_fetch_entry(code, fentry)
    fentry["wall_seconds"] = round(time.monotonic() - t0, 1)
    save_fetch_entry(code, fentry)
    ok_files = [f for f in files if f["status"] == "ok"]
    rec["wall_seconds"] = round(time.monotonic() - t0, 1)
    if not ok_files:
        if disallowed == len(files):
            cat, ev = "robots_disallowed", "robots.txt disallows all discovered bylaw PDF paths"
        else:
            errs = " ;; ".join(files[0]["errors"][-2:]) if files else ""
            if "403" in errs or "406" in errs or "202" in errs:
                cat = "waf_block"
            elif "ReadTimeout" in errs or "ConnectTimeout" in errs:
                cat = "transfer_stall"
            else:
                cat = "live_timeout"
            ev = f"all {len(files)} PDF downloads failed live: {errs[:220]}"
        rec.update({"status": "dead_end", "category": cat, "evidence": ev, "updated": TODAY})
        tm_save(tm)
        print(f"[{code}] DEAD_END {cat}", flush=True)
        return
    rec["docs"] = len(ok_files)
    tm_save(tm)
    try:
        build_and_publish(tm, code, "live")
    except BaseException as exc:  # noqa: BLE001 — build3 raises SystemExit on gate failure
        rec.update({"status": "dead_end", "category": "build_gate_failed",
                    "evidence": f"build/gates failed: {str(exc)[:220]}", "updated": TODAY})
        tm_save(tm)
        print(f"[{code}] BUILD FAILED {exc}", flush=True)


def phase_harvest():
    tm = load_tm()
    order = probe_order()
    if not order:
        print("no probe results — run probe first")
        return
    consec_transport = 0
    for code in order:
        rec = tm_record(tm, code)
        if rec.get("status") in ("published", "built", "staged", "dead_end"):
            continue
        print(f"===== [{code}] {REG.get(code, code)} =====", flush=True)
        try:
            outcome = harvest_live_council(tm, code)
        except BaseException as exc:  # noqa: BLE001
            rec = tm_record(tm, code)
            rec.update({"status": "dead_end", "category": "error",
                        "evidence": f"driver exception: {type(exc).__name__}: {str(exc)[:200]}",
                        "updated": TODAY})
            tm_save(tm)
            print(f"[{code}] driver exception: {exc}", flush=True)
            outcome = None
        if outcome == "transport_fail":
            consec_transport += 1
            if consec_transport >= 3:
                print("CIRCUIT BREAKER: 3 consecutive transport failures — "
                      "egress presumed degraded; aborting phase with the "
                      "remaining councils untouched.", flush=True)
                break
        else:
            consec_transport = 0
    print("HARVEST COMPLETE")


# ------------------------------------------------------------------ wayback

class ArchiveBackoff(Exception):
    pass


class ArchiveGate:
    """Single gate for ALL archive.org traffic in this process."""

    def __init__(self, tm):
        self.tm = tm
        self.last = 0.0

    def wait(self):
        until = float(self.tm.get("archive_backoff_until") or 0)
        if time.time() < until:
            raise ArchiveBackoff(f"archive back-off until {time.strftime('%H:%M', time.localtime(until))}")
        gap = ARCHIVE_MIN_GAP - (time.monotonic() - self.last)
        if gap > 0:
            time.sleep(gap)

    def stamp(self):
        self.last = time.monotonic()

    def hit_429(self):
        self.tm["archive_backoff_until"] = time.time() + ARCHIVE_BACKOFF
        tm_save(self.tm)
        raise ArchiveBackoff("archive.org HTTP 429 — back-off set")


# Wellington's pilot-recorded CDX snapshots (nz_wellington_dl.py DOCS)
WELLINGTON_DOCS = [
    ("https://wellington.govt.nz/-/media/your-council/plans-policies-and-bylaws/bylaws/files/animal-bylaw-2024.pdf", "20250331210634", "Animal Bylaw 2024"),
    ("https://wellington.govt.nz/-/media/your-council/plans-policies-and-bylaws/bylaws/files/alcohol-fees-bylaw-2024.pdf", "20250404023842", "Alcohol Fees Bylaw 2024"),
    ("https://wellington.govt.nz/-/media/your-council/plans-policies-and-bylaws/bylaws/files/public-places/public-places-bylaw-2022.pdf", "20240612182418", "Public Places Bylaw 2022"),
    ("https://wellington.govt.nz/-/media/your-council/plans-policies-and-bylaws/bylaws/files/public-health-bylaw-2019-06-28.pdf", "20220320052838", "Public Health Bylaw 2019"),
]


def wb_download(gate, sess, wb_url, final_path):
    """One gated wayback download with Range-resume, via curl (the
    requests streaming layer ProxyErrors at 0 B on some hosts through
    this egress; curl is uniformly reliable here). The ArchiveGate
    still enforces pacing, and the HTTP status is read explicitly so
    a 429 triggers the mandated long back-off. (ok, errors)."""
    if final_path.exists() and final_path.stat().st_size > 0 \
            and final_path.open("rb").read(4) == b"%PDF":
        return True, []
    part = final_path.with_suffix(".pdf.part")
    errors = []
    for attempt in range(1, 4):
        gate.wait()
        gate.stamp()
        have = part.stat().st_size if part.exists() else 0
        cmd = ["curl", "-s", "--max-time", "900", "-A", UA["User-Agent"],
               "-o", str(part), "-w", "\n%{http_code}"]
        if have > 0:
            cmd += ["-C", "-"]
        cmd.append(curl_url(wb_url))
        try:
            cp = subprocess.run(cmd, capture_output=True, text=True, timeout=960)
            _body, _, code_s = cp.stdout.rpartition("\n")
            code = int(code_s) if code_s.isdigit() else 0
            rc = cp.returncode
        except Exception as exc:  # noqa: BLE001
            errors.append(f"wayback#{attempt}: {type(exc).__name__}: {str(exc)[:110]}")
            print(f"    WB DL FAIL #{attempt} {type(exc).__name__} {wb_url[:90]}", flush=True)
            time.sleep(20 * attempt)
            continue
        if code == 429:
            errors.append(f"wayback#{attempt}: HTTP 429")
            gate.hit_429()  # persists back-off, raises ArchiveBackoff
        if rc == 0 and code == 200:
            break
        errors.append(f"wayback#{attempt}: HTTP {code} curl{rc}")
        print(f"    WB DL FAIL #{attempt} HTTP {code} curl{rc} {wb_url[:90]}", flush=True)
        if rc == 33:  # range resume unsupported — restart the file
            part.unlink(missing_ok=True)
        time.sleep(20 * attempt)
    else:
        return False, errors
    if part.exists() and part.stat().st_size > 0 and part.open("rb").read(4) == b"%PDF":
        part.rename(final_path)
        return True, errors
    errors.append("wayback: bytes lack %PDF magic")
    part.unlink(missing_ok=True)
    return False, errors


def wb_cdx_bylaw_pdfs(gate, domain):
    """One gated CDX query: archived bylaw PDFs under a council domain.
    Returns list of (original_url, timestamp) client-filtered."""
    q = (f"https://web.archive.org/cdx/search/cdx?url={domain}"
         "&matchType=domain&filter=original:.*\\.pdf&collapse=urlkey"
         "&output=json&limit=600")
    gate.wait()
    gate.stamp()
    cp = subprocess.run(["curl", "-s", "--max-time", "240", "-A", UA["User-Agent"],
                         "-w", "\n%{http_code}", q],
                        capture_output=True, text=True, timeout=270)
    body, _, code_s = cp.stdout.rpartition("\n")
    code = int(code_s) if code_s.isdigit() else 0
    if code == 429:
        gate.hit_429()
    if cp.returncode != 0 or code != 200:
        raise requests.ConnectionError(f"CDX query failed: HTTP {code} curl{cp.returncode}")
    rows = json.loads(body) if body.strip() else []
    out = {}
    for row in rows[1:]:
        ts, orig = row[1], row[2]
        if "bylaw" not in orig.lower():
            continue
        key = re.sub(r"\?.*$", "", orig.lower())
        if key not in out or ts > out[key][1]:
            out[key] = (orig, ts)
    return sorted(out.values())


def wayback_council(tm, gate, code, docs=None):
    """docs: optional preset [(url, timestamp, link_text)]. Else CDX enum."""
    rec = tm_record(tm, code)
    name = REG.get(code, code)
    sess = make_session()
    t0 = time.monotonic()
    base = SITES[code][0]
    domain = urlparse(base).netloc
    if docs is None:
        pairs = wb_cdx_bylaw_pdfs(gate, domain)
        # prefer substantive bylaws: skip pure schedules/forms when plenty
        docs = []
        for orig, ts in pairs:
            docs.append((orig, ts, ""))
        docs = docs[:SAMPLE]
        print(f"[wb {code}] CDX: {len(pairs)} bylaw PDFs archived, taking {len(docs)}", flush=True)
    if not docs:
        rec.update({"status": "dead_end", "category": "no_bylaws_found",
                    "evidence": "Wayback CDX: no archived bylaw PDFs under council domain",
                    "wall_seconds": round(time.monotonic() - t0, 1), "updated": TODAY})
        tm_save(tm)
        print(f"[wb {code}] DEAD_END no_bylaws_found (CDX empty)", flush=True)
        return
    cdir = PDFS / code
    cdir.mkdir(exist_ok=True)
    _fm, fentry = fetch_entry(code)
    fentry.update({"name": name, "index_url": base,
                   "robots": {"status": "documented/waf",
                              "basis": "live host WAF/timeout from this egress (pilot + tranche probe); "
                                       "Wayback snapshots of the same public URLs used",
                              "seconds": None},
                   "discovered": len(docs)})
    files = []
    for i, (url, ts, link_text) in enumerate(docs, start=1):
        final_path = cdir / slugify(url, i)
        wb_url = f"https://web.archive.org/web/{ts}id_/{url}"
        frec = {"url": url, "link_text": link_text or url,
                "path": str(final_path.relative_to(OUT)), "status": "failed",
                "source": None, "size": 0, "sha256": "", "seconds": 0.0,
                "attempts": 0, "errors": [], "wayback_url": wb_url,
                "wayback_timestamp": ts}
        t1 = time.monotonic()
        ok, errors = wb_download(gate, sess, wb_url, final_path)
        frec["errors"] = errors
        frec["seconds"] = round(time.monotonic() - t1, 1)
        if ok:
            data = final_path.read_bytes()
            frec.update({"status": "ok", "source": "wayback", "size": len(data),
                         "sha256": hashlib.sha256(data).hexdigest()})
            print(f"    WB DL OK {len(data)}B {url[:90]}", flush=True)
        files.append(frec)
        fentry["files"] = files
        save_fetch_entry(code, fentry)
    fentry["wall_seconds"] = round(time.monotonic() - t0, 1)
    save_fetch_entry(code, fentry)
    ok_files = [f for f in files if f["status"] == "ok"]
    rec["wall_seconds"] = round(time.monotonic() - t0, 1)
    if not ok_files:
        rec.update({"status": "dead_end", "category": "live_timeout",
                    "evidence": f"Wayback downloads failed for all {len(files)} archived bylaw PDFs: "
                                f"{(files[0]['errors'][-1] if files and files[0]['errors'] else '')[:180]}",
                    "updated": TODAY})
        tm_save(tm)
        print(f"[wb {code}] DEAD_END wayback downloads failed", flush=True)
        return
    rec["docs"] = len(ok_files)
    tm_save(tm)
    try:
        build_and_publish(tm, code, "wayback")
    except BaseException as exc:  # noqa: BLE001
        rec.update({"status": "dead_end", "category": "build_gate_failed",
                    "evidence": f"build/gates failed: {str(exc)[:220]}", "updated": TODAY})
        tm_save(tm)
        print(f"[wb {code}] BUILD FAILED {exc}", flush=True)


def phase_wayback():
    tm = load_tm()
    gate = ArchiveGate(tm)
    probe = load_json(PROBE_PATH, {})
    targets = []
    # Wellington first (preset CDX snapshots), then group B, then probe failures
    targets.append(("047", WELLINGTON_DOCS))
    for code in WAYBACK_FIRST:
        if code != "047":
            targets.append((code, None))
    for code, v in sorted(probe.items()):
        if v.get("score") is None and code not in WAYBACK_FIRST:
            targets.append((code, None))
    try:
        for code, docs in targets:
            rec = tm_record(tm, code)
            if rec.get("status") in ("published", "built", "staged", "dead_end"):
                continue
            print(f"===== [wb {code}] {REG.get(code, code)} =====", flush=True)
            try:
                wayback_council(tm, gate, code, docs)
            except ArchiveBackoff:
                raise  # a 429/back-off must pause the phase, not dead-end councils
            except BaseException as exc:  # noqa: BLE001
                rec = tm_record(tm, code)
                rec.update({"status": "dead_end", "category": "error",
                            "evidence": f"wayback driver exception: {type(exc).__name__}: {str(exc)[:200]}",
                            "updated": TODAY})
                tm_save(tm)
                print(f"[wb {code}] exception {exc}", flush=True)
    except ArchiveBackoff as exc:
        print(f"WAYBACK PHASE PAUSED: {exc}", flush=True)
        return
    print("WAYBACK COMPLETE")


# ------------------------------------------------------------------ publish retry / status

def phase_publish():
    tm = load_tm()
    staged = [c for c, r in tm["councils"].items() if r.get("status") in ("staged", "built")]
    for code in staged:
        try:
            publish_council(code)
            rec = tm_record(tm, code)
            rec["status"] = "published"
            rec["published"] = True
            rec["updated"] = TODAY
            tm_save(tm)
            print(f"[{code}] publish retry OK", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[{code}] publish retry failed: {exc}", flush=True)
    # refresh coverage if anything is published by tranche
    pubs = [c for c, r in tm["councils"].items() if r.get("published")]
    if pubs:
        try:
            refresh_coverage_and_verify(sorted(pubs)[-1])
        except Exception as exc:  # noqa: BLE001
            print(f"coverage refresh failed: {exc}", flush=True)
    print("PUBLISH PHASE DONE")


def phase_status():
    tm = load_tm()
    run = load_json(RUN_PATH, {"councils": {}})
    done = [c for c, v in run.get("councils", {}).items() if v.get("valid")]
    print(f"published total (run_manifest valid): {len(done)} councils, "
          f"{sum(v.get('rows', 0) for v in run['councils'].values() if v.get('valid'))} rows")
    by_status = {}
    for c, r in sorted(tm["councils"].items()):
        by_status.setdefault(r.get("status"), []).append(c)
    for s, cs in sorted(by_status.items()):
        print(f"  {s}: {len(cs)} — {', '.join(cs)}")
    dead = [(c, r.get("category")) for c, r in tm["councils"].items() if r.get("status") == "dead_end"]
    for c, cat in dead:
        print(f"  dead_end {c} [{cat}]")


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"probe": phase_probe, "harvest": phase_harvest, "wayback": phase_wayback,
     "publish": phase_publish, "status": phase_status}[phase]()
