#!/usr/bin/env python3
"""Canada census step 2: light-touch platform classification per resolved site.

Per host: robots.txt + homepage + at most ONE by-law index page. No by-law
documents/PDFs are ever downloaded. Robots-first: a disallowed by-law route
is recorded, never fetched. Platform subdomains (CivicWeb) get robots.txt
only — the platform wildcard-disallows everything else.
"""
import json, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import requests

HERE = Path(__file__).resolve().parent
CENSUS = HERE.parent
SRC = CENSUS / "sources"
UA_STR = "ca-platform-census/1.0"
UA = {"User-Agent": f"Mozilla/5.0 (X11; Linux x86_64) {UA_STR}"}
CHALLENGE = ("incapsula", "just a moment", "verifying your browser", "_incapsula_",
             "attention required", "cf-challenge", "are you a robot")
BYLAW_RE = re.compile(r"by[-\s]?laws?|r[èe]glements?|municipal code|code municipal", re.I)

def fetch(url, cap=200000, timeout=30):
    # The egress proxy rejects CONNECT bursts with fast transient errors;
    # retry those (never HTTP error statuses) with backoff.
    import time as _time
    last = (None, url, "", {"error": "no_attempt"})
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=(60, timeout), stream=True,
                             allow_redirects=True)
            body = b""
            for chunk in r.iter_content(16384):
                body += chunk
                if len(body) > cap: break
            r.close()
            return r.status_code, r.url, body.decode("utf-8", "replace"), dict(r.headers)
        except requests.RequestException as e:
            last = (None, url, "", {"error": type(e).__name__})
            if attempt < 2:
                _time.sleep(6 * (attempt + 1))
    return last

def get_robots(base):
    st, _, text, _ = fetch(base + "/robots.txt", cap=120000, timeout=45)
    if st is None: return None, None, "unreachable"
    if st == 403: return None, st, "walled"
    if st != 200: return None, st, "none"
    low = text.lower()
    if any(c in low for c in CHALLENGE): return None, st, "walled"
    rp = RobotFileParser(); rp.set_url(base + "/robots.txt"); rp.parse(text.splitlines())
    return rp, st, "ok"

def crawl_delay(rp):
    try:
        d = rp.crawl_delay(UA_STR) if rp else None
        return float(d) if d else None
    except Exception:
        return None

def platform_of(html_low, headers, host):
    sig = [
        ("CivicWeb", ("civicweb", "icompass")),
        ("eScribe", ("escribemeetings", "escribe")),
        ("CivicPlus", ("civicplus", "civicclerk")),
        ("Granicus", ("granicus", "govdelivery")),
        ("OpenCities", ("opencities",)),
        ("GovStack", ("govstack", "esolutionsgroup", "esolutions")),
        ("Cyberlex", ("cyberlex",)),
        ("MuniCode", ("municode", "municipal code corporation")),
        ("AmLegal", ("amlegal", "american legal publishing")),
        ("eCode360", ("ecode360", "generalcode", "general code")),
        ("WordPress", ("wp-content", "wp-includes", "wp-json")),
        ("Drupal", ("drupal.settings", "/sites/default/files/", 'name="generator" content="drupal')),
        ("AEM", ("/etc.clientlibs", "adobe experience manager")),
    ]
    for name, needles in sig:
        for n in needles:
            if n in html_low or n in host:
                return name, n
    srv = (headers.get("Server", "") + " " + headers.get("X-Powered-By", "")).strip()
    return "bespoke", (srv[:60] if srv else "no signature")

def classify(rec):
    out = dict(rec)
    out.update(platform=None, platform_evidence=None, bylaws_presence="unknown",
               bylaw_index_url=None, pdf_links_on_index=None, robots_posture="unknown",
               robots_crawl_delay=None, homepage_status=None, census_status="classified",
               notes=None)
    url = rec.get("website_url")
    if not url:
        out.update(census_status="no_site_found", robots_posture="n/a")
        return out
    p = urlparse(url if "://" in url else "https://" + url)
    base = f"{p.scheme}://{p.netloc}"
    host = p.netloc.lower().replace("www.", "")
    out["host"] = host

    if host.endswith("civicweb.net"):
        rp, st, state = get_robots(base)
        out.update(platform="CivicWeb", platform_evidence="civicweb.net subdomain",
                   robots_posture="disallowed" if state == "ok" else state,
                   bylaws_presence="unknown_platform_excluded",
                   homepage_status=None, notes="platform robots wildcard Disallow:/ (pilot-verified)")
        return out
    if "escribemeetings.com" in host:
        rp, st, state = get_robots(base)
        out.update(platform="eScribe", platform_evidence="escribemeetings.com subdomain",
                   robots_posture="walled", bylaws_presence="portal_documents_walled",
                   notes="document endpoint Cloudflare-walled from this egress (pilot-verified)")
        return out

    rp, rst, rstate = get_robots(base)
    out["robots_crawl_delay"] = crawl_delay(rp)
    if rstate == "walled":
        out.update(robots_posture="walled", census_status="walled",
                   notes="robots.txt itself bot-walled (403/challenge)")
        return out
    if rp is not None and not rp.can_fetch(UA_STR, base + "/"):
        out.update(robots_posture="disallowed", census_status="classified",
                   bylaws_presence="unknown_robots_disallowed_homepage",
                   notes="robots disallows homepage for generic UA")
        return out
    st, final, html, headers = fetch(base + "/", cap=120000, timeout=45)
    out["homepage_status"] = st
    if st is None:
        out.update(census_status="site_unreachable", robots_posture="unknown",
                   notes="homepage fetch failed (network/timeout)")
        return out
    low = html.lower()
    if st == 403 or any(c in low for c in CHALLENGE):
        out.update(robots_posture="walled", census_status="walled",
                   notes="homepage 403 / bot-challenge page")
        return out
    if st >= 400:
        out.update(census_status="site_error", notes=f"homepage HTTP {st}")
        return out
    plat, ev = platform_of(low, headers, host)
    out.update(platform=plat, platform_evidence=ev, robots_posture="allowed")

    links = re.findall(r'href="([^"#]+)"[^>]*>([^<]{0,80})</a>', html, re.I)
    cand, direct_pdf = None, 0
    for href, text in links:
        full = urljoin(final, href)
        if BYLAW_RE.search(text or "") or BYLAW_RE.search(href):
            if full.lower().split("?")[0].endswith(".pdf"):
                direct_pdf += 1
            elif cand is None:
                cand = full
    if direct_pdf:
        out.update(bylaws_presence="direct_pdf_links_on_homepage", pdf_links_on_index=direct_pdf)
        return out
    if not cand:
        out.update(bylaws_presence="none_found_on_homepage")
        return out
    out["bylaw_index_url"] = cand
    # robots for the index URL (may be cross-host, e.g. reglements.ville.quebec.qc.ca)
    cp = urlparse(cand); cbase = f"{cp.scheme}://{cp.netloc}"
    if cbase != base:
        crp, _, cstate = get_robots(cbase)
        if cstate == "walled":
            out.update(bylaws_presence="index_found_walled", robots_posture="walled"); return out
        if crp is not None and not crp.can_fetch(UA_STR, cand):
            out.update(bylaws_presence="index_found_robots_disallowed", robots_posture="disallowed"); return out
        rp2 = crp
    else:
        rp2 = rp
        if rp is not None and not rp.can_fetch(UA_STR, cand):
            out.update(bylaws_presence="index_found_robots_disallowed", robots_posture="disallowed"); return out
    d = out["robots_crawl_delay"]
    if d: time.sleep(min(float(d), 12))
    st2, _, html2, _ = fetch(cand, timeout=45)
    if st2 is None or st2 >= 400:
        out.update(bylaws_presence="index_found_fetch_failed", notes=f"index HTTP {st2}")
        return out
    if any(c in html2.lower() for c in CHALLENGE):
        out.update(bylaws_presence="index_found_walled", robots_posture="walled"); return out
    pdfs = len(re.findall(r'href="[^"]+\.pdf[^"]*"', html2, re.I))
    out["pdf_links_on_index"] = pdfs
    out["bylaws_presence"] = "index_with_pdfs" if pdfs else "index_no_pdfs_found"
    return out

def main():
    rows = [json.loads(l) for l in open(SRC / "resolved.jsonl")]
    out_path = CENSUS / "census_raw.jsonl"
    done = set()
    if out_path.exists():
        done = {json.loads(l)["sgc"] for l in open(out_path)}
    todo = [r for r in rows if r["sgc"] not in done]
    # priority: cities/villes/towns first (tranche-relevant), then the rest
    _rank = {"CY": 0, "C": 0, "CV": 0, "V": 0, "T": 1, "DM": 2, "MÉ": 3,
             "M": 3, "CT": 4, "TP": 4, "VL": 5, "VN": 5, "VC": 5, "VK": 5,
             "PE": 6, "PAR": 6, "RM": 7, "MD": 7, "RGM": 7, "RMU": 7,
             "CU": 8, "GR": 8}
    todo.sort(key=lambda r: (_rank.get(r["csd_type"], 9), r["province"], r["name"]))
    print(f"census todo: {len(todo)} (done {len(done)})", file=sys.stderr)
    with open(out_path, "a") as fh, ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(classify, r): r for r in todo}
        n = 0
        for f in as_completed(futs):
            try: rec = f.result()
            except Exception as e:
                rec = dict(futs[f]); rec.update(census_status="error", notes=type(e).__name__)
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n"); fh.flush()
            n += 1
            if n % 250 == 0: print(f"census {n}/{len(todo)}", file=sys.stderr)
    print("DONE", file=sys.stderr)

if __name__ == "__main__":
    main()
