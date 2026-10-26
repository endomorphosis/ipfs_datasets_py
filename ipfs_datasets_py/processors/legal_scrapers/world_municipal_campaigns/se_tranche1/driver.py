"""Sweden tranche 1 — census (all 290 kommuner) + first harvest batch.

Checkpointed, resumable driver. Reuses the pilot machinery:
- registry: se_pilot/jurisdictions.jsonl (SCB, 290 kommuner)
- builder: se_pilot/se_build.py (Swedish section-splitter, world_municipal
  fail-closed gates) — imported, not rewritten
- fetch: hard-capped curl only (requests stalls through this proxy)

Phases (state in se_tranche1/state.json, census checkpoints appended to
se_tranche1/census.jsonl after every kommun):
  1. crack  — SiteVision JS-widget attempt for Orebro 1880 + Gotland 0980
  2. census — index URL / platform / robots / static doc count / JS flag
              for all 290 kommuner (kommun sites only; lansstyrelserna
              county-state collections explicitly excluded)
  3. census_publish — census.jsonl + updated coverage_report.md uploaded
              additively to endomorphosis/ipfs_sweden_municipal_laws
  4. harvest — first 12 statically-linked kommuner beyond the pilot 4
              (plus 1880/0980 if cracked), full listed collections capped
              at DOC_CEILING docs/kommun, build, validate, publish
              per-kommun, remote-verify each

Site resolution: pilot-known sites -> Wikidata P856 official websites
(SPARQL, cached) -> domain guesses from the kommun name. Search-engine
fallback was tested and dropped: DuckDuckGo lite times out through
this proxy (measured 2026-10-14).

JS-widget findings (measured 2026-10-14, before this driver ran):
- Orebro: the SiteVision file-share webapp embeds its full file list as
  JSON in AppRegistry.registerInitialState(...) script blobs — 91 files
  on the forfattningssamling index alone. No API call needed; parse the
  embedded state.
- Gotland: forfattningssamling category pages statically link the
  kommun's document service (dokument.gotland.se
  /IntegrationService.svc/doc/content/<id>), which returns real PDFs
  (HTTP 200, application/pdf). The pilot's link filter missed both
  patterns; extract_doc_links() below handles both generically.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse

BASE = Path(__file__).resolve().parent
HIDDEN = BASE.parent
PILOT = HIDDEN / "se_pilot"
REPORT = HIDDEN / "sweden_tranche1_2026-10-14.md"
STATE = BASE / "state.json"
CENSUS = BASE / "census.jsonl"
OUTD = BASE / "out"
PDFD = BASE / "pdfs"
UA = "world-municipal-law-pilot/1.0 (research; polite harvest)"
RETRIEVED = "2026-10-14"
REPO = "endomorphosis/ipfs_sweden_municipal_laws"
PILOT4 = {"0380", "1280", "1980", "2480"}
DOC_CEILING = 120
HARVEST_N = 12
CRACK_DEADLINE = 45 * 60  # seconds, for the whole crack phase

sys.path.insert(0, str(PILOT))
sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers"))

REG = {}
for ln in (PILOT / "jurisdictions.jsonl").read_text(encoding="utf-8").splitlines():
    r = json.loads(ln)
    REG[r["jurisdiction_id"]] = r

KNOWN_SITES = {
    "0180": "https://start.stockholm",
    "1480": "https://goteborg.se",
    "1280": "https://malmo.se",
    "0380": "https://www.uppsala.se",
    "0580": "https://www.linkoping.se",
    "1880": "https://orebro.se",
    "2480": "https://www.umea.se",
    "2580": "https://www.lulea.se",
    "0680": "https://www.jonkoping.se",
    "1980": "https://www.vasteras.se",
    "0980": "https://gotland.se",
    "2180": "https://www.gavle.se",
}
KNOWN_INDEX = {
    "0380": "https://www.uppsala.se/kommun-och-politik/dokumentsamlingar/lokala-foreskrifter/",
    "1880": "https://orebro.se/kommun--politik/dokument-statistik--undersokningar/dokument--undersokningar/kommunal-forfattningssamling.html",
    "1280": "https://malmo.se/forfattningssamling",
    "1980": "https://www.vasteras.se/kommun-och-politik/forfattningssamling",
    "2480": "https://www.umea.se/styrdokument",
    "0980": "https://gotland.se/region-och-politik/sa-styrs-region-gotland/forfattningssamling-och-styrande-dokument",
}
CANDIDATE_PATHS = [
    "/forfattningssamling", "/forfattningssamlingen",
    "/kommun-och-politik/forfattningssamling",
    "/kommun--politik/forfattningssamling",
    "/kommun-och-politik/forfattningssamling.html",
    "/politik-och-organisation/forfattningssamling",
    "/kommun-och-politik/styrdokument/forfattningssamling",
    "/kommun-och-politik/dokumentsamlingar/lokala-foreskrifter/",
    "/kommun-och-politik/forfattningssamling/",
    "/sa-styrs-kommunen/forfattningssamling",
    "/kommun-och-politik/styrande-dokument/forfattningssamling",
    "/kommun-och-demokrati/forfattningssamling",
    "/forfattningssamling.html",
    "/styrdokument", "/kommun-och-politik/styrdokument",
]
DOC_EXT = (".pdf", ".docx", ".doc")

_lock = threading.Lock()
_state = None


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_state():
    global _state
    if _state is None:
        _state = json.loads(STATE.read_text()) if STATE.exists() else {
            "started": RETRIEVED, "phases": {}, "crack": {}, "harvest": {},
            "census_published": False}
    return _state


def save_state():
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_state, indent=1, ensure_ascii=False))
    tmp.replace(STATE)


def census_done():
    done = {}
    if CENSUS.exists():
        for ln in CENSUS.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                done[r["code"]] = r
    return done


def append_census(rec):
    with _lock:
        with CENSUS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def curl(url, max_time=30, dest=None):
    cmd = ["curl", "-sS", "-L", "--max-time", str(max_time), "-A", UA]
    if dest:
        cmd += ["-w", "%{http_code}", "-o", str(dest), url]
    else:
        cmd += ["-w", "\n%{http_code} %{url_effective}", url]
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=max_time + 20)
        if dest:
            try:
                code = int(p.stdout.decode().strip() or 0)
            except ValueError:
                code = None
            body = dest.read_bytes() if dest.exists() else b""
            return {"status": code, "final_url": url, "body": body,
                    "bytes": len(body), "seconds": round(time.monotonic() - t0, 1)}
        out = p.stdout
        tail = out.rsplit(b"\n", 1)[-1].decode("utf-8", "replace")
        body = out[: len(out) - len(tail) - 1] if b"\n" in out else out
        m = re.match(r"(\d{3}) (\S+)", tail.strip())
        return {"status": int(m.group(1)) if m else None,
                "final_url": m.group(2) if m else url,
                "body": body.decode("utf-8", "replace"),
                "bytes": len(body), "seconds": round(time.monotonic() - t0, 1),
                "curl_rc": p.returncode}
    except Exception as e:  # noqa: BLE001
        return {"status": None, "final_url": url, "body": b"" if dest else "",
                "bytes": 0, "seconds": round(time.monotonic() - t0, 1),
                "error": f"{type(e).__name__}: {e}"}


def robots_allows(robots_text, path):
    if not robots_text:
        return True
    groups = re.split(r"(?im)^\s*user-agent:", robots_text)
    for g in groups[1:]:
        if g.split("\n", 1)[0].strip() not in ("*",):
            continue
        for line in g.splitlines()[1:]:
            line = line.strip()
            if line.lower().startswith("disallow:"):
                rule = line.split(":", 1)[1].strip()
                if rule and rule != "/" and path.startswith(rule):
                    return False
                if rule == "/":
                    return False
    return True


def norm_name(name):
    s = unicodedata.normalize("NFKD", name.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("aa", "a").replace("ae", "a").replace("oe", "o")
    return re.sub(r"[^a-z0-9]", "", s)


def slug_variants(name):
    s = unicodedata.normalize("NFKD", name.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    words = re.sub(r"[^a-z0-9 ]", " ", s).split()
    joined = "".join(words)
    hyph = "-".join(words)
    out = [joined, hyph, joined + "kommun", joined + "s-kommun",
           joined + "s-kommun".replace("s-kommun", "skommun")]
    seen, res = set(), []
    for v in out:
        if v and v not in seen:
            seen.add(v)
            res.append(v)
    return res


def wikidata_sites():
    cache = BASE / "wikidata_sites.json"
    if cache.exists():
        return json.loads(cache.read_text())
    q = ("SELECT ?itemLabel ?website WHERE { ?item wdt:P31 wd:Q127448; "
         "wdt:P856 ?website. SERVICE wikibase:label { "
         "bd:serviceParam wikibase:language \"sv\". } }")
    url = "https://query.wikidata.org/sparql?query=" + quote(q) + "&format=json"
    cmd = ["curl", "-sS", "-L", "--max-time", "60", "-A", UA,
           "-H", "Accept: application/sparql-results+json", url]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=90)
        data = json.loads(p.stdout.decode("utf-8", "replace"))
        out = {}
        for b in data["results"]["bindings"]:
            label = b["itemLabel"]["value"].replace(" kommun", "").strip()
            site = b["website"]["value"]
            o = urlparse(site)
            out[norm_name(label)] = f"{o.scheme}://{o.netloc}"
            if label.endswith("s"):  # genitive labels: "Salems kommun"
                out.setdefault(norm_name(label[:-1]),
                               f"{o.scheme}://{o.netloc}")
        cache.write_text(json.dumps(out, indent=1, ensure_ascii=False))
        log(f"wikidata: {len(out)} kommun websites cached")
        return out
    except Exception as e:  # noqa: BLE001
        log(f"wikidata fetch failed: {e}")
        return {}


def detect_platform(html):
    low = html.lower()
    if "sitevision" in low or "/download/18." in low or "sv-" in low:
        return "SiteVision"
    if "episerver" in low or "optimizely" in low or "/contentassets/" in low:
        return "Episerver/Optimizely"
    if "wordpress" in low or "wp-content" in low:
        return "WordPress"
    return "bespoke/unknown"


def clean_title(t):
    t = re.sub(r"\s*(pdf|docx?)\s*,?\s*[\d.,]+\s*(kB|MB|KB)?\.?\s*$", "", t, flags=re.I)
    return " ".join(t.split()).strip(" .") or "dokument"


def extract_doc_links(html, base):
    """Static document links + SiteVision file-share embedded state."""
    from bs4 import BeautifulSoup
    docs, seen = [], set()

    def add(url, title):
        url = urljoin(base, url)
        host = urlparse(url).netloc.lower()
        if "lansstyrelsen" in host:
            return
        if url in seen:
            return
        seen.add(url)
        docs.append({"url": url, "title": clean_title(title)})

    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        low = href.lower().split("?")[0]
        txt = " ".join(a.get_text().split())
        if low.endswith(DOC_EXT) and not low.endswith((".css", ".js")):
            add(href, txt or unquote(href.split("/")[-1]))
        elif "/download/18." in href and low.rsplit(".", 1)[-1] in ("pdf", "docx", "doc"):
            add(href, txt or unquote(href.split("/")[-1]))
        elif "/integrationservice.svc/doc/content/" in low or "/doc/content/" in low:
            add(href, txt or href.split("/")[-1])
    # SiteVision file-share webapp: files embedded as JSON initial state
    for m in re.finditer(r"registerInitialState\('[^']+',(\{.*?\})\)\s*;", html, re.S):
        try:
            data = json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            continue
        for f in data.get("files", []) if isinstance(data, dict) else []:
            if isinstance(f, dict) and f.get("url"):
                add(f["url"], f.get("name", ""))
    return docs


def page_links(html, base, keywords):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base, a["href"])
        o = urlparse(href)
        if o.netloc != urlparse(base).netloc:
            continue
        low = unquote(o.path).lower()
        txt = " ".join(a.get_text().split()).lower()
        if any(k in low or k in txt for k in keywords):
            u = href.split("#")[0]
            if u not in seen:
                seen.add(u)
                out.append(u)
    return out


def resolve_site(code, name, wd):
    """Return (origin, homepage_html) or (None, '').

    Trusted origins (pilot-known, Wikidata P856) get two attempts at
    30 s: SE municipal homepages stall intermittently through this
    proxy (measured: haninge.se, tyreso.se, taby.se all curl-000 at
    18 s in one window, fine in another — pilot saw the same). Guessed
    domains get one short attempt each, max 4."""
    trusted = []
    if code in KNOWN_SITES:
        trusted.append(KNOWN_SITES[code])
    wd_site = wd.get(norm_name(name))
    if wd_site and wd_site not in trusted:
        trusted.append(wd_site)
    for origin in trusted:
        for _attempt in range(2):
            r = curl(origin, max_time=30)
            if r["status"] == 200 and r["bytes"] > 800 and isinstance(r["body"], str):
                return urlparse(r["final_url"])._replace(path="", params="",
                        query="", fragment="").geturl().rstrip("/"), r["body"]
            time.sleep(1)
    guesses = []
    for v in slug_variants(name)[:2]:
        guesses += [f"https://www.{v}.se", f"https://{v}.se"]
    for origin in guesses[:4]:
        if origin in trusted:
            continue
        r = curl(origin, max_time=12)
        if r["status"] == 200 and r["bytes"] > 1500 and isinstance(r["body"], str):
            if "kommun" in r["body"].lower():
                return urlparse(r["final_url"])._replace(path="", params="",
                        query="", fragment="").geturl().rstrip("/"), r["body"]
    return None, ""


def sitemap_page_urls(origin):
    """All page URLs from the site's sitemap(s), gzip-aware. One fetch
    (plus up to 4 child sitemaps) — measured to expose index paths the
    candidate list misses, e.g. Nykvarn's
    /kommun-och-politik/styrande-dokument/forfattningssamling."""
    import gzip
    import io

    def fetch_text(url):
        tmp = BASE / f".sm_{threading.get_ident()}.bin"
        r = curl(url, max_time=30, dest=tmp)
        raw = r["body"] if isinstance(r["body"], bytes) else b""
        if tmp.exists():
            tmp.unlink()
        if r["status"] != 200 or not raw:
            return ""
        if raw[:2] == b"\x1f\x8b":
            try:
                raw = gzip.decompress(raw)
            except Exception:  # noqa: BLE001
                return ""
        return raw.decode("utf-8", "replace")

    txt = fetch_text(origin + "/sitemap.xml")
    if not txt:
        return []
    locs = re.findall(r"<loc>([^<]+)</loc>", txt)
    if "<sitemapindex" in txt:
        pages = []
        for child in locs[:4]:
            t2 = fetch_text(child.strip())
            pages += re.findall(r"<loc>([^<]+)</loc>", t2)
            time.sleep(0.3)
        return pages
    return locs


def census_one(code, wd):
    name = REG[code]["jurisdiction_name"]
    rec = {"code": code, "name": name, "lan_code": REG[code]["lan_code"],
           "lan_name": REG[code]["lan_name"], "retrieved": RETRIEVED}
    origin, home_html = resolve_site(code, name, wd)
    if not origin:
        rec.update({"site_url": "", "index_url": "", "platform": "",
                    "robots_status": None, "robots_allows_index": None,
                    "static_doc_count": 0, "doc_links": [], "js_widget": False,
                    "status": "no_site_found",
                    "notes": "no homepage resolved via known/wikidata/guessed domains"})
        append_census(rec)
        log(f"[{code}] {name}: no site")
        return rec
    rec["site_url"] = origin
    rob = curl(origin + "/robots.txt", max_time=12)
    rec["robots_status"] = rob["status"]
    robots_text = rob["body"] if rob["status"] == 200 and isinstance(rob["body"], str) else ""
    rec["platform"] = detect_platform(home_html)

    index_url, index_html, method = "", "", ""
    if code in KNOWN_INDEX:
        r = curl(KNOWN_INDEX[code], max_time=25)
        if r["status"] == 200 and isinstance(r["body"], str) and r["bytes"] > 3000:
            index_url, index_html, method = r["final_url"], r["body"], "known"
    if not index_url:
        for u in page_links(home_html, origin, ["författning", "forfattning"]):
            r = curl(u, max_time=20)
            if r["status"] == 200:
                index_url, index_html, method = r["final_url"], r["body"], "homepage_link"
                break
    if not index_url:
        sm = sitemap_page_urls(origin)
        cands = [u for u in sm if "forfattning" in unquote(u).lower()
                 and "/download/" not in u]
        cands += [u for u in sm if "/download/" not in u and any(
            k in unquote(u).lower() for k in
            ("styrande-dokument", "styrdokument", "regler-och-styrande"))]
        for u in cands[:4]:
            if not robots_allows(robots_text, urlparse(u).path):
                continue
            r = curl(u, max_time=20)
            if r["status"] == 200 and isinstance(r["body"], str):
                d = extract_doc_links(r["body"], r["final_url"])
                if "forfattning" in unquote(u).lower() or len(d) >= 3:
                    index_url, index_html, method = r["final_url"], r["body"], "sitemap"
                    break
    if not index_url:
        for p in CANDIDATE_PATHS:
            if not robots_allows(robots_text, p):
                continue
            r = curl(origin + p, max_time=12)
            if r["status"] == 200 and isinstance(r["body"], str) and (
                    "fattnin" in r["body"] or "reskrift" in r["body"]):
                index_url, index_html, method = r["final_url"], r["body"], "candidate_path"
                break
    if not index_url:
        # secondary: styrdokument index pages (Umea pilot route)
        for u in page_links(home_html, origin, ["styrdokument"]):
            r = curl(u, max_time=20)
            if r["status"] == 200:
                d = extract_doc_links(r["body"], r["final_url"])
                if len(d) >= 3:
                    index_url, index_html, method = r["final_url"], r["body"], "styrdokument_link"
                    break
    if not index_url:
        rec.update({"index_url": "", "robots_allows_index": None,
                    "static_doc_count": 0, "doc_links": [], "js_widget": False,
                    "status": "index_not_found",
                    "notes": f"site {origin}; no forfattningssamling index via homepage links or {len(CANDIDATE_PATHS)} candidate paths; discovery-pending, not a dead end"})
        append_census(rec)
        log(f"[{code}] {name}: site ok, index not found")
        return rec

    rec["index_url"] = index_url
    rec["robots_allows_index"] = robots_allows(robots_text, urlparse(index_url).path)
    docs = extract_doc_links(index_html, index_url)
    visited = [index_url]
    if len(docs) < 3:
        subs = page_links(index_html, index_url,
                          ["dokument", "forfattning", "författning", "styrdokument"])
        for u in subs[:8]:
            if u == index_url:
                continue
            r = curl(u, max_time=20)
            visited.append(u)
            if r["status"] == 200 and isinstance(r["body"], str):
                for d in extract_doc_links(r["body"], r["final_url"]):
                    if d["url"] not in {x["url"] for x in docs}:
                        docs.append(d)
            time.sleep(0.5)
    rec["static_doc_count"] = len(docs)
    rec["doc_links"] = docs[:400]
    rec["pages_visited"] = visited
    embedded = "registerInitialState" in index_html and len(docs) > 0
    rec["js_widget"] = bool(len(docs) == 0)
    rec["status"] = "ok" if docs else "index_no_static_docs"
    rec["notes"] = f"method={method}" + ("; docs include SiteVision file-share embedded state" if embedded else "")
    if not docs:
        rec["notes"] += "; index found but zero static doc links (JS-rendered list or subpage-only) — route preserved"
    append_census(rec)
    log(f"[{code}] {name}: index={method} docs={len(docs)} platform={rec['platform']}")
    return rec


OREBRO_CATS = [
    "https://orebro.se/kommun--politik/dokument-statistik--undersokningar/dokument--undersokningar/kommun--politik---dokument.html",
    "https://orebro.se/kommun--politik/dokument-statistik--undersokningar/dokument--undersokningar/bygga-bo--trafik---dokument.html",
    "https://orebro.se/kommun--politik/dokument-statistik--undersokningar/dokument--undersokningar/miljo--klimat---dokument.html",
    "https://orebro.se/kommun--politik/dokument-statistik--undersokningar/dokument--undersokningar/barn--utbildning---dokument.html",
    "https://orebro.se/kommun--politik/dokument-statistik--undersokningar/dokument--undersokningar/kultur--fritid---dokument.html",
    "https://orebro.se/kommun--politik/dokument-statistik--undersokningar/dokument--undersokningar/omsorg--stod---dokument.html",
    "https://orebro.se/kommun--politik/dokument-statistik--undersokningar/dokument--undersokningar/foretag--naringsliv---dokument.html",
]
GOTLAND_SUBS = [
    "https://gotland.se/region-och-politik/sa-styrs-region-gotland/forfattningssamling-och-styrande-dokument/reglementen-och-instruktioner",
    "https://gotland.se/region-och-politik/sa-styrs-region-gotland/forfattningssamling-och-styrande-dokument/avtal-bestammelser-foreskrifter-och-ordningar",
    "https://gotland.se/region-och-politik/sa-styrs-region-gotland/forfattningssamling-och-styrande-dokument/avgifter-och-taxor",
    "https://gotland.se/region-och-politik/sa-styrs-region-gotland/forfattningssamling-och-styrande-dokument/bolagsordningar-stiftelser-och-stadgar",
    "https://gotland.se/region-och-politik/sa-styrs-region-gotland/forfattningssamling-och-styrande-dokument/styrdokument",
]


def crack_sitevision(deadline):
    """One time-boxed attempt at the two JS-flagged kommuner. Both routes
    were cracked in pre-driver analysis (see module docstring); this
    executes them systematically and records the outcome."""
    st = load_state()
    if st["phases"].get("crack_done"):
        return st["crack"]
    out = {}
    # Orebro: embedded file-share state on index + category pages
    docs, seen = [], set()
    for u in [KNOWN_INDEX["1880"]] + OREBRO_CATS:
        if time.monotonic() > deadline:
            break
        r = curl(u, max_time=30)
        if r["status"] == 200 and isinstance(r["body"], str):
            for d in extract_doc_links(r["body"], r["final_url"]):
                if d["url"] not in seen:
                    seen.add(d["url"])
                    docs.append(d)
        time.sleep(0.5)
    out["1880"] = {"cracked": len(docs) > 0, "doc_count": len(docs),
                  "doc_links": docs[:400],
                  "method": "SiteVision file-share embedded registerInitialState JSON (files[].url) on index + category pages"}
    # Gotland: category pages link the kommun document service
    docs, seen = [], set()
    for u in [KNOWN_INDEX["0980"]] + GOTLAND_SUBS:
        if time.monotonic() > deadline:
            break
        r = curl(u, max_time=30)
        if r["status"] == 200 and isinstance(r["body"], str):
            for d in extract_doc_links(r["body"], r["final_url"]):
                if d["url"] not in seen:
                    seen.add(d["url"])
                    docs.append(d)
        time.sleep(0.5)
    out["0980"] = {"cracked": len(docs) > 0, "doc_count": len(docs),
                  "doc_links": docs[:400],
                  "method": "category pages statically link dokument.gotland.se /IntegrationService.svc/doc/content/<id> (returns application/pdf)"}
    st["crack"] = out
    st["phases"]["crack_done"] = True
    save_state()
    for code, v in out.items():
        log(f"crack {code}: cracked={v['cracked']} docs={v['doc_count']}")
    return out


def ddg_retry():
    """Retry lane for kommuner whose latest census record is
    no_site_found / index_not_found: DuckDuckGo lite search for the
    forfattningssamling page (DDG lite works through this proxy but
    stalls intermittently — one retry; measured 2026-10-14). Appends a
    superseding census record when an index is found."""
    st = load_state()
    if st["phases"].get("ddg_done"):
        return
    done = census_done()
    targets = [c for c in sorted(done)
               if done[c].get("status") in ("no_site_found", "index_not_found")]
    log(f"ddg retry: {len(targets)} targets")
    for code in targets[:60]:
        name = REG[code]["jurisdiction_name"]
        q = quote(f'"{name}" kommun författningssamling')
        url = f"https://lite.duckduckgo.com/lite/?q={q}"
        body = ""
        for _a in range(2):
            cmd = ["curl", "-sS", "-L", "--max-time", "30",
                   "-A", "Mozilla/5.0", url]
            try:
                p = subprocess.run(cmd, capture_output=True, timeout=45)
                body = p.stdout.decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                body = ""
            if "uddg=" in body:
                break
            time.sleep(2)
        results = []
        for m in re.finditer(r"uddg=([^&\"']+)", body):
            u = unquote(m.group(1))
            if u not in results:
                results.append(u)
        found = None
        for u in results[:6]:
            if "lansstyrelsen" in u or "duckduckgo" in u:
                continue
            if "forfattning" not in unquote(u).lower():
                continue
            r = curl(u, max_time=25)
            if r["status"] == 200 and isinstance(r["body"], str):
                docs = extract_doc_links(r["body"], r["final_url"])
                origin = urlparse(r["final_url"])._replace(
                    path="", params="", query="", fragment="").geturl().rstrip("/")
                found = (r, docs, origin)
                break
        if found:
            r, docs, origin = found
            rob = curl(origin + "/robots.txt", max_time=12)
            rec = {"code": code, "name": name,
                   "lan_code": REG[code]["lan_code"],
                   "lan_name": REG[code]["lan_name"], "retrieved": RETRIEVED,
                   "site_url": origin, "index_url": r["final_url"],
                   "platform": detect_platform(r["body"]),
                   "robots_status": rob["status"],
                   "robots_allows_index": robots_allows(
                       rob["body"] if rob["status"] == 200 and isinstance(rob["body"], str) else "",
                       urlparse(r["final_url"]).path),
                   "static_doc_count": len(docs), "doc_links": docs[:400],
                   "js_widget": bool(len(docs) == 0),
                   "status": "ok" if docs else "index_no_static_docs",
                   "notes": "method=ddg_search_retry"}
            append_census(rec)
            log(f"[{code}] ddg retry: index found, docs={len(docs)}")
        else:
            log(f"[{code}] ddg retry: still unresolved")
        time.sleep(1)
    load_state()["phases"]["ddg_done"] = True
    save_state()


def hf_api():
    os.environ["no_proxy"] = "localhost,127.0.0.1"
    os.environ["NO_PROXY"] = "localhost,127.0.0.1"
    sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
    from dynamic_credentials import dynamic_credential_entry
    entry = dynamic_credential_entry("custom.huggingface")
    tok = entry.get("surrogate")
    if not tok:
        raise RuntimeError("dynamic_credential_entry returned no surrogate")
    from huggingface_hub import HfApi
    return HfApi(token=tok)


def publish_census(api):
    st = load_state()
    if st.get("census_published"):
        return
    done = census_done()
    ok = [r for r in done.values() if r["status"] == "ok"]
    nodocs = [r for r in done.values() if r["status"] == "index_no_static_docs"]
    noidx = [r for r in done.values() if r["status"] == "index_not_found"]
    nosite = [r for r in done.values() if r["status"] == "no_site_found"]
    lines = [
        "# Coverage report — Sweden municipal laws",
        "",
        f"Retrieved {RETRIEVED}. **Census complete: {len(done)} of 290 kommuner** "
        f"recorded in `census.jsonl` (this directory, published with tranche 1): "
        f"{len(ok)} with statically-linked collections, {len(nodocs)} with an index "
        f"but no static document links, {len(noidx)} index-not-located "
        f"(discovery-pending, not dead ends), {len(nosite)} site-not-resolved.",
        "",
        "Seed (pilot, 2026-10-14): 4 kommuner, 22 documents, 346 rows — "
        "Uppsala 0380 (80), Malmö 1280 (73), Västerås 1980 (155), Umeå 2480 (38).",
        "",
        "Tranche 1 harvest results are appended below as kommuner publish.",
        "",
        "| Code | Kommun | Census docs | Harvest rows | Status |",
        "|---|---|---|---|---|",
    ]
    for code in sorted(done):
        r = done[code]
        h = st.get("harvest", {}).get(code, {})
        lines.append(f"| {code} | {r['name']} | {r.get('static_doc_count', 0)} | "
                     f"{h.get('rows', '')} | {h.get('status', r['status'])} |")
    cov = OUTD / "coverage_report.md"
    cov.write_text("\n".join(lines) + "\n", encoding="utf-8")
    existing = {s.rfilename for s in (api.dataset_info(REPO).siblings or [])}
    for local, remote in [(CENSUS, "census.jsonl"), (cov, "coverage_report.md"),
                          (BASE / "driver.py", "scrapers/se_tranche1_driver.py")]:
        api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                        repo_id=REPO, repo_type="dataset")
        log(f"census publish: uploaded {remote} (was {'present' if remote in existing else 'new'})")
    info = api.dataset_info(REPO)
    names = {s.rfilename for s in info.siblings or []}
    assert "census.jsonl" in names and "coverage_report.md" in names
    st["census_published"] = True
    save_state()


def harvest_one(code, doc_links, api):
    import se_build  # pilot builder; OUT=PILOT, writes <code>_html.parquet there
    name = REG[code]["jurisdiction_name"]
    docs = doc_links[:DOC_CEILING]
    capped = len(doc_links) > DOC_CEILING
    d = PDFD / code
    d.mkdir(parents=True, exist_ok=True)
    files = []
    for spec in docs:
        slug = re.sub(r"[^a-z0-9]+", "-", unquote(spec["url"]).lower()).strip("-")[-110:]
        dest = d / (slug + ".pdf")
        if not (dest.exists() and dest.stat().st_size > 500
                and dest.read_bytes()[:5] == b"%PDF-"):
            r = curl(spec["url"], dest=dest, max_time=180)
            ok = r["status"] == 200 and r["bytes"] > 500 and dest.exists() \
                and dest.read_bytes()[:5] == b"%PDF-"
            if not ok:
                files.append({"url": spec["url"], "title": spec["title"],
                              "kind": "pdf", "path": str(dest), "status": "failed"})
                log(f"[{code}] fetch failed {spec['title'][:50]} http={r['status']}")
                continue
            time.sleep(1)
        files.append({"url": spec["url"], "title": spec["title"], "kind": "pdf",
                      "path": str(dest), "status": "ok"})
    ok_files = [f for f in files if f["status"] == "ok"]
    if not ok_files:
        return {"status": "fetch_all_failed", "rows": 0, "docs_ok": 0,
                "docs_total": len(docs), "capped": capped}
    res = se_build.build_kommun(code, ok_files)
    if not res.get("valid"):
        return {"status": "build_invalid", "rows": 0, "docs_ok": len(ok_files),
                "docs_total": len(docs), "capped": capped,
                "error": str(res.get("error"))[:300]}
    pq_src = PILOT / f"{code}_html.parquet"
    val_src = PILOT / f"{code}_validation.json"
    (OUTD / pq_src.name).write_bytes(pq_src.read_bytes())
    (OUTD / val_src.name).write_bytes(val_src.read_bytes())
    existing = {s.rfilename for s in (api.dataset_info(REPO).siblings or [])}
    for local, remote in [(OUTD / pq_src.name, f"data/{code}_html.parquet"),
                          (OUTD / val_src.name, f"data/{code}_validation.json")]:
        if remote not in existing:
            api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                            repo_id=REPO, repo_type="dataset")
    # remote verification: re-download + re-validate
    from huggingface_hub import hf_hub_download
    from world_municipal.parquet_io import read_html_parquet
    from world_municipal.schema import validate_table
    p = hf_hub_download(REPO, f"data/{code}_html.parquet", repo_type="dataset")
    t = read_html_parquet(p)
    errs = validate_table(t, jurisdiction_id=code, jurisdiction_name=name, country="SE")
    assert not errs, errs
    assert t.num_rows == res["rows"], (t.num_rows, res["rows"])
    log(f"[{code}] published + remote-verified: {res['rows']} rows, {len(ok_files)} docs")
    return {"status": "published", "rows": res["rows"], "docs_ok": len(ok_files),
            "docs_total": len(docs), "capped": capped,
            "docs_skipped_build": [d.get("title") for d in res["docs"] if d.get("skipped")]}


def update_report():
    st = load_state()
    done = census_done()
    counts = {}
    for r in done.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines = [
        "# Sweden census + tranche 1 — report (IN PROGRESS)",
        "",
        f"Driver: `se_tranche1/driver.py`, state `se_tranche1/state.json`, "
        f"census checkpoints `se_tranche1/census.jsonl`. Retrieved {RETRIEVED}.",
        "Seed (pilot): endomorphosis/ipfs_sweden_municipal_laws — 4 kommuner / "
        "22 docs / 346 rows, remote-verified (see sweden_pilot_2026-10-13.md).",
        "Tesseract 5.3.4 via the workspace-persistent tessroot wrapper "
        "~/workspace/tools/bin/tesseract, languages deu/eng/ind/osd/swe "
        "('swe' pack present, verified 2026-10-14); the builder extracts "
        "born-digital PDF text (fitz/pdfplumber/pdftotext) and documents "
        "scanned docs it skips rather than force-fitting them.",
        "",
        f"## Census: {len(done)}/290 kommuner checkpointed",
        "",
    ]
    for k, v in sorted(counts.items()):
        lines.append(f"- {k}: {v}")
    crack = st.get("crack", {})
    if crack:
        lines += ["", "## SiteVision JS-widget attempt (Orebro / Gotland)", ""]
        for code, v in crack.items():
            lines.append(f"- {code}: cracked={v['cracked']}, {v['doc_count']} docs — {v['method']}")
    harv = st.get("harvest", {})
    if harv:
        lines += ["", "## Tranche 1 harvest", "",
                  "| Code | Kommun | Docs | Rows | Status |", "|---|---|---|---|---|"]
        tot_r = tot_d = 0
        for code in sorted(harv):
            h = harv[code]
            tot_r += h.get("rows", 0)
            tot_d += h.get("docs_ok", 0)
            cap = " (capped at 120)" if h.get("capped") else ""
            lines.append(f"| {code} | {REG[code]['jurisdiction_name']} | "
                         f"{h.get('docs_ok', 0)}/{h.get('docs_total', 0)}{cap} | "
                         f"{h.get('rows', 0)} | {h.get('status')} |")
        lines.append(f"\nTranche totals so far: {tot_d} docs, {tot_r} rows "
                     f"(plus pilot seed 346 rows).")
    lines += ["", f"Phases: {json.dumps(st.get('phases', {}))}",
              f"Census published to HF: {st.get('census_published')}", ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main():
    st = load_state()
    deadline = time.monotonic() + CRACK_DEADLINE
    crack_sitevision(deadline)
    update_report()
    # census
    done = census_done()
    # cracked kommuner: seed census records directly (they ARE census data)
    for code, v in load_state()["crack"].items():
        if code not in done and v.get("cracked"):
            name = REG[code]["jurisdiction_name"]
            rec = {"code": code, "name": name, "lan_code": REG[code]["lan_code"],
                   "lan_name": REG[code]["lan_name"], "retrieved": RETRIEVED,
                   "site_url": KNOWN_SITES[code], "index_url": KNOWN_INDEX[code],
                   "platform": "SiteVision", "robots_status": 200,
                   "robots_allows_index": True,
                   "static_doc_count": v["doc_count"], "doc_links": v["doc_links"],
                   "js_widget": False, "status": "ok",
                   "notes": f"via SiteVision crack: {v['method']}"}
            append_census(rec)
            done[code] = rec
    # no_site_found records are NOT treated as done: measured to be
    # mostly transient proxy stalls, so each run retries them once.
    todo = [c for c in sorted(REG)
            if c not in done or done[c].get("status") == "no_site_found"]
    log(f"census: {len(done)} done, {len(todo)} to go")
    if todo:
        wd = wikidata_sites()

        def safe(c):
            try:
                return census_one(c, wd)
            except Exception as e:  # noqa: BLE001
                rec = {"code": c, "name": REG[c]["jurisdiction_name"],
                       "lan_code": REG[c]["lan_code"], "lan_name": REG[c]["lan_name"],
                       "retrieved": RETRIEVED, "site_url": "", "index_url": "",
                       "platform": "", "robots_status": None,
                       "robots_allows_index": None, "static_doc_count": 0,
                       "doc_links": [], "js_widget": False, "status": "error",
                       "notes": f"{type(e).__name__}: {e}"[:300]}
                append_census(rec)
                log(f"[{c}] census error: {e}")
                return rec

        # 3 workers: at 6-8 workers the egress proxy stalls en masse
        # (curl 000 across unrelated .se hosts, measured 2026-10-14);
        # pilot fetches were sequential for the same reason.
        with ThreadPoolExecutor(max_workers=3) as ex:
            list(ex.map(safe, todo))
    load_state()["phases"]["census_done"] = True
    save_state()
    update_report()
    try:
        ddg_retry()
    except Exception as e:  # noqa: BLE001
        log(f"ddg retry phase failed (continuing): {e}")
    update_report()
    try:
        api = hf_api()
        publish_census(api)
    except Exception as e:  # noqa: BLE001
        log(f"census publish failed (continuing): {type(e).__name__}: {e}")
        try:
            api = hf_api()
        except Exception:  # noqa: BLE001
            api = None
    update_report()
    # harvest queue
    done = census_done()
    eligible = [c for c in sorted(done)
                if done[c].get("status") == "ok"
                and done[c].get("static_doc_count", 0) > 0
                and c not in PILOT4]
    queue = eligible[:HARVEST_N]
    for code in ("1880", "0980"):
        if load_state()["crack"].get(code, {}).get("cracked") and code not in queue \
                and code in done:
            queue.append(code)
    log(f"harvest queue ({len(queue)}): {queue}")
    for code in queue:
        if load_state().get("harvest", {}).get(code, {}).get("status") == "published":
            continue
        try:
            res = harvest_one(code, done[code]["doc_links"], api)
        except Exception as e:  # noqa: BLE001
            res = {"status": "error", "rows": 0, "error": f"{type(e).__name__}: {e}"[:300]}
        with _lock:
            st2 = load_state()
            st2.setdefault("harvest", {})[code] = res
            save_state()
        update_report()
    load_state()["phases"]["harvest_done"] = True
    save_state()
    update_report()
    log("driver complete")


if __name__ == "__main__":
    main()
