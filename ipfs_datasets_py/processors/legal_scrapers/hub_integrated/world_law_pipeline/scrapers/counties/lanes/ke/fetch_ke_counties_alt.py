#!/usr/bin/env python3
"""KE empty-38 repair: try each county assembly's OWN .go.ke site ONCE for a matching gazetted Act PDF.
Hosts only (never new.kenyalaw.org). robots_guard every hop; pace max(5s, Crawl-Delay) per host;
1 in-flight; TLS verify; hard-stop THAT HOST on challenge/403/429/503 and skip remaining laws there.
Budget ~6 discovery req/host + 1/matched PDF. Logs every request to requests_counties.jsonl.
rc: 0 ok | 3 global hard stop (mem/disk/RSS) | 5 start gate not met."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import hashlib, json, os, re, sys, threading, time
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse
import requests

sys.path.insert(0, _ipfs_os.path.dirname(_ipfs_os.path.abspath(__file__)))
import robots_guard as rg
rg.set_country("ke")

STAGE = Path(os.environ.get("MUNI_STAGE", "/dev/shm/muni_africa/ke/b3"))
OUT = STAGE / "counties"
PDF = OUT / "pdf"
REQLOG = STAGE / "requests_counties.jsonl"
STATUS = Path("/dev/shm/muni_africa/status_ke_b3_counties.txt")
UA = "legal-corpora-collector/1.0 (research archive of official national gazettes; polite; contact via local operator)"

# Prefer www when it resolves to same host family; Meru uses assembly.meru.go.ke
HOSTS = {
    "ke-034": {"name": "Kajiado", "hosts": ["www.kajiadoassembly.go.ke", "kajiadoassembly.go.ke"]},
    "ke-015": {"name": "Kitui", "hosts": ["www.kituiassembly.go.ke", "kituiassembly.go.ke"]},
    "ke-012": {"name": "Meru", "hosts": ["assembly.meru.go.ke"]},
    "ke-047": {"name": "Nairobi", "hosts": ["www.nairobiassembly.go.ke", "nairobiassembly.go.ke"]},
}

# Discovery path candidates (tried in order until budget / listing found)
DISCOVER_PATHS = [
    "/acts/", "/acts", "/Acts/", "/county-acts/", "/county-acts",
    "/legislation/", "/legislation", "/publications/", "/publications",
    "/downloads/", "/documents/", "/bills-and-acts/", "/acts-and-bills/",
    "/",  # homepage last among discovery (counts toward budget)
]

A_RX = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)
DOC_RX = re.compile(r"\.(?:pdf)(?:$|\?)", re.I)
CF_BODY = re.compile(r"(?i)cdn-cgi/challenge|cf-browser-verification|just a moment|attention required|enable javascript|captcha|access denied")
YEAR_RX = re.compile(r"\b(20\d{2})\b")
ACTNO_RX = re.compile(r"(?i)\b(?:no\.?\s*|act\s+)?(\d{1,3})\b")

STOP = {"reason": None}  # global (fleet)
HOST_STOP = {}  # hostname -> reason
PEAK = {"rss_mib": 0.0}
LAST_SEND = {}  # family -> epoch
CRAWL_DELAY = {}  # family -> float

def seed_robots(origin, http_status, body):
    """Populate robots_guard cache from our paced/logged robots.txt GET (no second fetch)."""
    host = urlparse(origin).hostname or ""
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if http_status == 200 and body and not re.search(r"<\s*(html|!doctype)", body[:600], re.I):
        rb = rg.parse_robots(body)
        g = rb.select()
        st = rg.HostState(origin, "ok", http_status, rb, g, float(g.crawl_delay or 0) if g else 0.0,
                          fetched_at=now_iso)
        if st.crawl_delay:
            CRAWL_DELAY[family_of(host)] = float(st.crawl_delay)
    elif http_status in (401, 403, 429) or http_status >= 500 or http_status == 0:
        st = rg.HostState(origin, "unavailable", http_status, fetched_at=now_iso, error=f"http_{http_status}")
    else:
        # 404 etc = missing = allow
        st = rg.HostState(origin, "missing", http_status, fetched_at=now_iso, error=f"http_{http_status}")
    with rg._lock:
        rg._cache[origin] = st
    return st



def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def log(msg):
    line = f"{now()} {msg}"
    print(line, flush=True)
    with open(STATUS, "a") as fh:
        fh.write(line + "\n")


def mem_gib():
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 2**20
    return 0.0


def disk_mib():
    st = os.statvfs("/")
    return st.f_bavail * st.f_frsize / 2**20


def rss_tree_mib():
    kids, rss = {}, {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            st = open(f"/proc/{d}/stat").read()
            kids.setdefault(int(st.rsplit(")", 1)[1].split()[1]), []).append(int(d))
            for line in open(f"/proc/{d}/status"):
                if line.startswith("VmRSS:"):
                    rss[int(d)] = int(line.split()[1]) / 1024
                    break
        except (OSError, ValueError, IndexError):
            continue
    tot, todo = 0.0, [os.getpid()]
    while todo:
        p = todo.pop()
        tot += rss.get(p, 0.0)
        todo.extend(kids.get(p, []))
    return tot


def watchdog():
    low = None
    while STOP["reason"] is None:
        m = mem_gib()
        low = (low or time.time()) if m < 3.0 else None
        if low and time.time() - low >= 15:
            STOP["reason"] = f"MemAvailable {m:.2f} GiB < 3 GiB held >= 15 s"
        elif disk_mib() < 12500:
            STOP["reason"] = f"disk free {disk_mib():.0f} MiB < 12500"
        r = rss_tree_mib()
        PEAK["rss_mib"] = max(PEAK["rss_mib"], r)
        if r > 1024:
            STOP["reason"] = f"RSS {r:.0f} MiB > 1024 MiB"
        time.sleep(2)


def start_gate(hold=120, max_wait=2700):
    """Wait until MemAvailable>=5.5 GiB and disk>=12600 MiB, then hold both for `hold` s.
    Fail only if not achieved within max_wait (default 45 min)."""
    deadline = time.time() + max_wait
    ok_since = None
    while time.time() < deadline:
        if STOP["reason"]:
            log(f"start gate aborted: {STOP['reason']}")
            return False
        m, d = mem_gib(), disk_mib()
        if m >= 5.5 and d >= 12600:
            ok_since = ok_since or time.time()
            held = time.time() - ok_since
            if held >= hold:
                log(f"start gate passed: MemAvailable {m:.2f} GiB, disk {d:.0f} MiB held {held:.0f}s")
                return True
            if int(held) % 30 < 6:
                log(f"start gate holding: MemAvailable {m:.2f} GiB, disk {d:.0f} MiB held {held:.0f}/{hold}s")
        else:
            if ok_since is not None:
                log(f"start gate reset: MemAvailable {m:.2f} GiB, disk {d:.0f} MiB")
            ok_since = None
            log(f"start gate waiting: MemAvailable {m:.2f} GiB, disk {d:.0f} MiB")
        time.sleep(5)
    log(f"start gate not met within {max_wait}s: MemAvailable {mem_gib():.2f} GiB, disk {disk_mib():.0f} MiB")
    return False


def family_of(host):
    h = host.lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def reqlog(row):
    row = dict(row)
    row.setdefault("at", now())
    with open(REQLOG, "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def strip_tags(html):
    t = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html or "")
    t = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = re.sub(r"&\w+;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def norm_title(s):
    s = (s or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def title_keys(title):
    """Distinctive tokens for matching (drop county boilerplate)."""
    n = norm_title(title)
    drop = {"county", "city", "council", "the", "of", "and", "act", "no", "number", "supplementary"}
    toks = [t for t in n.split() if t not in drop and not (t.isdigit() and len(t) != 4)]
    years = YEAR_RX.findall(title or "")
    return toks, years


def score_match(law_title, link_title, link_url):
    toks, years = title_keys(law_title)
    blob = norm_title(link_title) + " " + norm_title(link_url)
    if not toks:
        return 0.0
    hit = sum(1 for t in toks if t in blob)
    ratio = hit / len(toks)
    y_ok = all(y in blob for y in years) if years else True
    # require most distinctive tokens + year
    if ratio < 0.7 or not y_ok:
        return 0.0
    # prefer Act number if present in both
    m = re.search(r"act[-_/ ]?(\d{4})[-_/ ]?(\d{1,3})", law_title.lower() + " " + (""))
    return ratio + (0.1 if y_ok else 0)


def extract_act_year_from_id(law_id):
    # ke-muni-ke-047-act-2022-4
    m = re.search(r"act-(\d{4})-(\d{1,3})", law_id or "")
    return (m.group(1), m.group(2)) if m else (None, None)


def better_match(law, link_title, link_url):
    year, actno = extract_act_year_from_id(law["id"])
    toks, years = title_keys(law["title"])
    if year and year not in years:
        years = [year] + years
    blob = norm_title(link_title) + " " + norm_title(urlparse(link_url).path)
    if years and not any(y in blob for y in years):
        return 0.0
    if not toks:
        return 0.0
    # require core phrase: drop very short tokens
    core = [t for t in toks if len(t) >= 4]
    if not core:
        core = toks
    hit = sum(1 for t in core if t in blob)
    ratio = hit / len(core)
    if ratio < 0.75:
        return 0.0
    bonus = 0.0
    if actno and re.search(rf"(?:act|no)[-_/\s]*{actno}\b", blob):
        bonus += 0.15
    if year and year in blob:
        bonus += 0.05
    return ratio + bonus


class HostHardStop(Exception):
    pass


class GlobalHardStop(Exception):
    pass


def pace(host):
    fam = family_of(host)
    gap = max(5.0, float(CRAWL_DELAY.get(fam, 0.0) or 0.0))
    last = LAST_SEND.get(fam, 0.0)
    wait = gap - (time.time() - last)
    if wait > 0:
        time.sleep(wait)


def mark_sent(host):
    LAST_SEND[family_of(host)] = time.time()


def ensure_robots(origin):
    """Fetch/honor robots via robots_guard; record crawl-delay."""
    host = urlparse(origin).hostname
    fam = family_of(host)
    # use check on robots.txt URL itself first via guarded path
    robots_url = origin.rstrip("/") + "/robots.txt"
    # robots_guard.check will fetch robots if needed when we call guarded_get
    # Pre-warm: call rg.check on a harmless allowed probe after session get of robots
    # Snapshot crawl delay from cache after first guarded call.
    return robots_url


def get_html(url, session, allowed_hosts, budget):
    if STOP["reason"]:
        raise GlobalHardStop(STOP["reason"])
    host = urlparse(url).hostname or ""
    if host not in allowed_hosts:
        raise HostHardStop(f"off-host {host}")
    if host in HOST_STOP:
        raise HostHardStop(HOST_STOP[host])
    fam = family_of(host)
    pace(host)
    sent_at = now()
    mark_sent(host)
    budget["n"] += 1
    try:
        d = rg.check(url)
        if d.crawl_delay:
            CRAWL_DELAY[family_of(host)] = float(d.crawl_delay)
        if not d.allowed:
            # unavailable (e.g. robots 403) = hard-stop host; disallowed = skip URL
            if d.reason == "robots_unavailable":
                reqlog({"url": url, "status": "robots_unavailable", "sent_at": sent_at, "host": host,
                        "robots_http": d.robots_http_status})
                HOST_STOP[host] = f"robots_unavailable:http_{d.robots_http_status}"
                raise HostHardStop(HOST_STOP[host])
            reqlog({"url": url, "status": "robots_disallowed", "sent_at": sent_at, "host": host, "rule": d.rule})
            return "robots", None, url
        r = session.get(url, timeout=(20, 90), allow_redirects=True, verify=True,
                        headers={"User-Agent": UA})
    except HostHardStop:
        raise
    except Exception as e:
        reqlog({"url": url, "status": f"error {type(e).__name__}", "sent_at": sent_at, "host": host, "err": str(e)[:160]})
        HOST_STOP[host] = f"net:{type(e).__name__}"
        raise HostHardStop(HOST_STOP[host])
    # off-host redirect?
    final_host = urlparse(r.url).hostname or ""
    if final_host not in allowed_hosts:
        reqlog({"url": url, "status": "off_host_redirect", "final": r.url, "sent_at": sent_at, "http": r.status_code})
        HOST_STOP[host] = f"off_host_redirect:{final_host}"
        raise HostHardStop(HOST_STOP[host])
    head = (r.text or "")[:8000]
    sig = []
    if r.headers.get("cf-mitigated"):
        sig.append("cf-mitigated")
    if r.status_code in (403, 429, 503):
        sig.append(f"http_{r.status_code}")
    if head and CF_BODY.search(head):
        sig.append("challenge_markup")
    reqlog({
        "url": url, "final": r.url, "http": r.status_code, "sent_at": sent_at, "host": host,
        "bytes": len(r.content or b""), "ctype": r.headers.get("content-type", ""),
        "sig": sig,
    })
    # update crawl-delay from robots cache
    try:
        for origin, st in list(rg._cache.items()):
            h = urlparse(origin).hostname or ""
            if family_of(h) == fam and getattr(st, "crawl_delay", None):
                CRAWL_DELAY[fam] = float(st.crawl_delay)
    except Exception:
        pass
    if sig:
        HOST_STOP[host] = f"hard_stop:{sig}"
        raise HostHardStop(HOST_STOP[host])
    if r.status_code != 200:
        return r.status_code, None, r.url
    return 200, r.text, r.url


def get_pdf(url, dest: Path, session, allowed_hosts):
    if STOP["reason"]:
        raise GlobalHardStop(STOP["reason"])
    host = urlparse(url).hostname or ""
    if host not in allowed_hosts:
        raise HostHardStop(f"off-host pdf {host}")
    if host in HOST_STOP:
        raise HostHardStop(HOST_STOP[host])
    pace(host)
    sent_at = now()
    mark_sent(host)
    try:
        d = rg.check(url)
        if d.crawl_delay:
            CRAWL_DELAY[family_of(host)] = float(d.crawl_delay)
        if not d.allowed:
            if d.reason == "robots_unavailable":
                reqlog({"url": url, "status": "robots_unavailable", "sent_at": sent_at, "host": host, "kind": "pdf",
                        "robots_http": d.robots_http_status})
                HOST_STOP[host] = f"robots_unavailable:http_{d.robots_http_status}"
                raise HostHardStop(HOST_STOP[host])
            reqlog({"url": url, "status": "robots_disallowed", "sent_at": sent_at, "host": host, "kind": "pdf"})
            return "robots", 0
        r = session.get(url, timeout=(20, 180), stream=True, allow_redirects=True, verify=True,
                        headers={"User-Agent": UA})
    except HostHardStop:
        raise
    except Exception as e:
        reqlog({"url": url, "status": f"error {type(e).__name__}", "sent_at": sent_at, "host": host, "kind": "pdf"})
        HOST_STOP[host] = f"net:{type(e).__name__}"
        raise HostHardStop(HOST_STOP[host])
    final_host = urlparse(r.url).hostname or ""
    if final_host not in allowed_hosts:
        r.close()
        HOST_STOP[host] = f"off_host_redirect:{final_host}"
        raise HostHardStop(HOST_STOP[host])
    if r.status_code in (403, 429, 503):
        reqlog({"url": url, "http": r.status_code, "sent_at": sent_at, "host": host, "kind": "pdf"})
        HOST_STOP[host] = f"hard_stop:http_{r.status_code}"
        r.close()
        raise HostHardStop(HOST_STOP[host])
    # peek
    chunks, n = [], 0
    for ch in r.iter_content(65536):
        if not ch:
            continue
        chunks.append(ch)
        n += len(ch)
        if n > 25 * 1024 * 1024:
            r.close()
            reqlog({"url": url, "status": "too_large", "sent_at": sent_at, "host": host, "kind": "pdf"})
            return "too_large", n
    r.close()
    raw = b"".join(chunks)
    ctype = r.headers.get("content-type", "")
    reqlog({"url": url, "final": r.url, "http": r.status_code, "sent_at": sent_at, "host": host,
            "bytes": len(raw), "ctype": ctype, "kind": "pdf"})
    if r.status_code != 200 or not raw.startswith(b"%PDF-"):
        return ("not_pdf" if r.status_code == 200 else r.status_code), len(raw)
    dest.write_bytes(raw)
    return 200, len(raw)


def collect_links(html, base_url):
    out, seen = [], set()
    for href, inner in A_RX.findall(html or ""):
        t = strip_tags(inner)
        if "{{" in href:
            continue
        u = urljoin(base_url, href)
        if u in seen:
            continue
        seen.add(u)
        out.append({"url": u, "title": t, "is_pdf": bool(DOC_RX.search(urlparse(u).path))})
    return out


def pick_primary_host(hosts):
    return hosts[0]


def discover_county(mid, laws, session):
    conf = HOSTS[mid]
    hosts = conf["hosts"]
    primary = pick_primary_host(hosts)
    allowed = set(hosts)
    origin = f"https://{primary}"
    budget = {"n": 0, "max": 6}
    results = {"county": conf["name"], "municipality_id": mid, "host": primary,
               "matches": [], "exclusions": [], "host_stop": None, "pages_tried": []}
    # robots.txt first: paced+logged GET, then seed robots_guard cache (no second fetch)
    try:
        if STOP["reason"]:
            raise GlobalHardStop(STOP["reason"])
        pace(primary)
        sent_at = now(); mark_sent(primary); budget["n"] += 1
        robots_url = origin + "/robots.txt"
        try:
            rr = session.get(robots_url, timeout=(20, 60), allow_redirects=True, verify=True,
                             headers={"User-Agent": UA, "Accept": "text/plain,*/*"})
        except Exception as e:
            reqlog({"url": robots_url, "status": f"error {type(e).__name__}", "sent_at": sent_at, "host": primary, "kind": "robots"})
            results["host_stop"] = f"net:{type(e).__name__}"
            HOST_STOP[primary] = results["host_stop"]
            return results
        body = rr.text if rr.status_code == 200 else (rr.text or "")
        reqlog({"url": robots_url, "final": rr.url, "http": rr.status_code, "sent_at": sent_at, "host": primary,
                "bytes": len(rr.content or b""), "kind": "robots"})
        results["pages_tried"].append({"path": "/robots.txt", "status": rr.status_code})
        if rr.status_code in (403, 429, 503) or (body and CF_BODY.search(body[:8000])):
            results["host_stop"] = f"hard_stop:robots_http_{rr.status_code}"
            HOST_STOP[primary] = results["host_stop"]
            return results
        seed_robots(origin, rr.status_code, body if rr.status_code == 200 else "")
    except GlobalHardStop:
        raise

    listing_links = []
    paths_left = [p for p in DISCOVER_PATHS if p != "/robots.txt"]
    for path in paths_left:
        if budget["n"] >= budget["max"]:
            break
        if primary in HOST_STOP:
            results["host_stop"] = HOST_STOP[primary]
            break
        try:
            st, body, final = get_html(origin + path, session, allowed, budget)
        except HostHardStop as e:
            results["host_stop"] = str(e)
            break
        except GlobalHardStop:
            raise
        results["pages_tried"].append({"path": path, "status": st, "final": final})
        if st != 200 or not body:
            continue
        links = collect_links(body, final)
        # keep PDF links and acts-ish links for one more hop if budget allows
        pdfs = [L for L in links if L["is_pdf"]]
        listing_links.extend(pdfs)
        # also keep non-pdf links that look like acts pages (for one follow)
        actish = [L for L in links if re.search(r"(?i)act|gazett|legislat|download|publication|document", L["url"] + " " + L["title"])]
        # follow up to 2 promising subpages if budget remains
        for L in actish[:2]:
            if budget["n"] >= budget["max"]:
                break
            if L["is_pdf"]:
                continue
            uh = urlparse(L["url"]).hostname or ""
            if uh not in allowed:
                continue
            try:
                st2, body2, final2 = get_html(L["url"], session, allowed, budget)
            except HostHardStop as e:
                results["host_stop"] = str(e)
                break
            except GlobalHardStop:
                raise
            results["pages_tried"].append({"path": L["url"], "status": st2})
            if st2 == 200 and body2:
                listing_links.extend([x for x in collect_links(body2, final2) if x["is_pdf"]])
        if pdfs:
            # found a listing with PDFs; stop discovering more paths
            break

    # de-dup listing
    seen_u, uniq = set(), []
    for L in listing_links:
        if L["url"] in seen_u:
            continue
        seen_u.add(L["url"])
        uniq.append(L)
    listing_links = uniq
    results["n_pdf_links"] = len(listing_links)

    # match each law
    for law in laws:
        dest = PDF / f"{law['id']}.pdf"
        if dest.exists() and dest.read_bytes()[:5] == b"%PDF-":
            results["matches"].append({"id": law["id"], "status": "cached", "path": str(dest)})
            continue
        best, best_s = None, 0.0
        for L in listing_links:
            s = better_match(law, L["title"], L["url"])
            if s > best_s:
                best_s, best = s, L
        if not best or best_s < 0.75:
            results["exclusions"].append({"id": law["id"], "title": law["title"], "reason": "no_matching_pdf_on_assembly_site", "best_score": best_s})
            continue
        # download
        if primary in HOST_STOP:
            results["exclusions"].append({"id": law["id"], "reason": f"host_stopped:{HOST_STOP[primary]}"})
            continue
        uh = urlparse(best["url"]).hostname or ""
        if uh not in allowed:
            results["exclusions"].append({"id": law["id"], "reason": f"match_off_host:{uh}", "url": best["url"]})
            continue
        try:
            st, nbytes = get_pdf(best["url"], dest, session, allowed)
        except HostHardStop as e:
            results["host_stop"] = str(e)
            results["exclusions"].append({"id": law["id"], "reason": f"host_stopped:{e}", "url": best["url"]})
            break
        except GlobalHardStop:
            raise
        if st == 200:
            results["matches"].append({
                "id": law["id"], "status": "fetched", "url": best["url"], "title_link": best["title"],
                "score": best_s, "bytes": nbytes, "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
            })
        else:
            results["exclusions"].append({"id": law["id"], "reason": f"pdf_fetch_{st}", "url": best["url"]})
    return results


def main():
    PDF.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    # stagger
    last = Path("/dev/shm/muni_last_start")
    if last.exists():
        age = time.time() - last.stat().st_mtime
        if age < 300:
            need = 300 - age
            log(f"stagger: waiting {need:.0f}s for muni_last_start")
            time.sleep(need + 1)
    if not start_gate(120):
        return 5
    Path("/dev/shm/muni_last_start").touch()
    threading.Thread(target=watchdog, daemon=True).start()

    items = json.load(open(STAGE / "empty38.json"))
    by = {}
    for it in items:
        by.setdefault(it["municipality_id"], []).append(it)

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
                            "Connection": "close"})

    all_results = []
    try:
        for mid in ("ke-034", "ke-015", "ke-012", "ke-047"):
            if STOP["reason"]:
                raise GlobalHardStop(STOP["reason"])
            if mid not in by:
                continue
            log(f"county_start {mid} {HOSTS[mid]['name']} n={len(by[mid])} host={HOSTS[mid]['hosts'][0]}")
            res = discover_county(mid, by[mid], session)
            all_results.append(res)
            log(f"county_done {mid} matches={len(res['matches'])} excl={len(res['exclusions'])} stop={res.get('host_stop')} pages={len(res['pages_tried'])} pdf_links={res.get('n_pdf_links')}")
            (OUT / f"discover_{mid}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    except GlobalHardStop as e:
        log(f"GLOBAL_HARD_STOP {e}")
        (OUT / "discover_all.json").write_text(json.dumps(all_results, indent=1, ensure_ascii=False))
        return 3

    (OUT / "discover_all.json").write_text(json.dumps(all_results, indent=1, ensure_ascii=False))
    n_m = sum(len(r["matches"]) for r in all_results)
    log(f"fetch_complete matches={n_m} peak_rss_mib={PEAK['rss_mib']:.0f}")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception as e:
        log(f"FATAL {type(e).__name__}: {e}")
        rc = 3
    sys.exit(rc)
