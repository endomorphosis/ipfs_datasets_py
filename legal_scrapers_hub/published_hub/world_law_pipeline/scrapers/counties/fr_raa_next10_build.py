r"""2026-10-30 fr_raa_next10: identical copy of fr_raa_next9_build.py (Mayotte FR-976, Gers FR-32); no code changes.
--- next9 doc: 2026-10-26 fr_raa_next9: copy of fr_raa_next8_build.py (batch 9: Guadeloupe FR-971, La Réunion FR-974, Nord FR-59). New entry options:
  detail_re: href regex for listing links that point to per-act DETAIL pages (lenord.fr/espace-documentaire/<slug>); the 2026/include filters
             apply to listing title + detail URL, then each detail page is fetched (robots-checked, crawl_delay) and its PDF links taken;
  title_re: regex (group 1) picking the title inside the link HTML;
  pdf_hosts: extra hosts PDFs may live on (documents.lenord.fr); in --test mode detail fetching stops after N docs.
--- next8 doc: identical copy of fr_raa_next7_build.py (batch 8); no code changes.
--- next7 doc: 2026-10-25 fr_raa_next7: identical copy of fr_raa_next6_build.py (Alpes-Maritimes FR-06, Jura FR-39, Yvelines FR-78); no code changes.
--- next6 doc: identical copy of fr_raa_next5_build.py (Creuse FR-23, Sarthe FR-72, Seine-et-Marne FR-77).
--- next5 doc: 2026-10-25 fr_raa_next5: copy of fr_raa_next4_build.py (Cantal FR-15, Haute-Vienne FR-87). New entry options:
  link_re: href regex replacing the default \.pdf match (webdelib openfile.jsp?...&pdf=... links);  year_re: regex replacing the "2026" filter;
  href_sub: [regex, repl] applied to each link URL (webdelib viewer openfile.jsp?name=..&pdf=T -> showFile.jsp?pdf=T, the PDF itself);
  extra_urls: more index pages (robots-checked) merged in; block title falls back to the block text when no <h>/<p>.
--- next4 doc: 2026-10-25 fr_raa_next4: copy of fr_raa_next2_build.py for the next CD collections (Nièvre FR-58, Corrèze FR-19, Loiret FR-45).
Changes vs next2: per-entry crawl_delay (seconds between index/pager requests AND written into the us_pdf_list config so PDFs are paced too;
robots Crawl-Delay, when present, overrides it if larger); 'Téléchargement'/'Télécharger' link texts fall back to the file name.
--- original next2 doc: next conseil départemental RAA / actes collections after fr_raa_next1 (FR-38 blocked, FR-46 done, FR-95 archive-exhausted).
Same rules as fr_raa_next1_build.py (2026 PDFs only, robots RFC 9309 per host for index AND PDFs, 50 MB cap, us_pdf_list per département;
already-staged source_urls skipped there, so test -> full is idempotent; query-string URLs get the URL-hash doc_id suffix there).
New entry options:
  pager: {"param": "page", "max": N, "stop_empty": K}  -> also read <url>?page=1..N (robots-checked), stop after K pages with no 2026 PDFs
  block_re: regex splitting the listing into items; title = <h2> + first <p> of the item (ille-et-vilaine.fr 'Télécharger l'arrêté' links)
  pdf_archive: true  -> index read live (robots-allowed) but the PDF folder is robots-disallowed: write fr_raa_cd_<iso>_archive.json
                        (archive_retry.py format, Wayback/CC copies only, never live) instead of running us_pdf_list
  max_urls: cap per département
usage: fr_raa_next2_build.py ENTRIES.json [--test N]"""
import re, sys, json, time, html, subprocess, urllib.request, urllib.parse
from pathlib import Path
from urllib.parse import urljoin, urlsplit
ARGS = sys.argv[1:]
HERE = Path(__file__).parent; sys.argv = ["x", str(HERE / "_dummy_cfg.json")]
exec(open(HERE / "us_pdf_list.py").read().split("w = StagedWriter")[0])
ENTRIES = json.load(open(ARGS[0])); TEST = int(ARGS[ARGS.index("--test") + 1]) if "--test" in ARGS else 0
LOGS = Path("/workspace/world_law/staging/counties/_logs")
_rc = {}
def allowed(u):
    if not RESPECT_ROBOTS: return True  # 2026-11-01: robots ignored by default (RESPECT_ROBOTS=1 restores)
    b = "{0.scheme}://{0.netloc}".format(urlsplit(u))
    if b not in _rc:
        try: _rc[b] = rfc_rules(urllib.request.urlopen(urllib.request.Request(b + "/robots.txt", headers={"User-Agent": UA}), timeout=30).read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e: _rc[b] = [] if e.code in (404, 410) else None
        except Exception: _rc[b] = None
    return _rc[b] is not None and rfc_allowed(_rc[b], u)
DELAY = [3]
SEEN_DETAIL = set()
_cd = {}
def robots_delay(u):
    b = "{0.scheme}://{0.netloc}".format(urlsplit(u))
    if b not in _cd:
        try:
            t = urllib.request.urlopen(urllib.request.Request(b + "/robots.txt", headers={"User-Agent": UA}), timeout=30).read().decode("utf-8", "replace")
            _cd[b] = max([float(x) for x in re.findall(r"(?im)^\s*crawl-delay\s*:\s*([0-9.]+)", t)] or [0])
        except Exception: _cd[b] = 0
    return _cd[b]
def get(u):
    time.sleep(DELAY[0]); return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=60).read().decode("utf-8", "replace")
def clean(t): return re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", " ", re.sub(r"(?is)<(style|svg|script)\b.*?</\1>", " ", t)))).strip()  # next9: drop inline <svg><style> (lenord.fr icons)
def pdfs(page, base, e, need_allowed=True):
    out = {}; inc = e.get("include_re")
    _b = re.search(r'<base[^>]+href="([^"]+)"', page, re.I); jb = urljoin(base, html.unescape(_b.group(1))) if _b else base  # honour <base href> (loire-atlantique.fr)
    blocks = re.split(e["block_re"], page) if e.get("block_re") else [page]
    for b in blocks:
        bt = ""
        if e.get("block_re"):
            h = re.search(r"<h[234][^>]*>(.*?)</h[234]>", b, re.S); p = re.search(r"<p>(?!\s*<a)(.*?)</p>", b, re.S)
            bt = " — ".join(x for x in (clean(h.group(1)) if h else "", clean(p.group(1)) if p else "") if x) or re.sub(r"\s*Voir l'acte.*$", "", clean(re.sub(r"^[^<>]*>", "", b)))[:300]
        for m in re.finditer(r'<a[^>]+href="(' + (e.get("detail_re") or e.get("link_re", r'[^"]+?\.pdf[^"]*')) + r')"[^>]*>(.*?)</a>', b, re.S | re.I):
            u = urljoin(jb, html.unescape(m.group(1))).replace(" ", "%20")
            if e.get("href_sub"): u = re.sub(e["href_sub"][0], e["href_sub"][1], u)
            t = bt or re.sub(r"^Télécharger\s*", "", clean(m.group(2)))
            if not t or re.match(r"^(l'arr[êe]t[ée]|cliquez|ici|lien|pdf|t[ée]l[ée]charg)", t, re.I): t = re.sub(r"\.pdf$", "", urllib.parse.unquote(u.rsplit("/", 1)[-1].lstrip("?")), flags=re.I)
            if e.get("title_re"):  # next9: title from a sub-element of the link (lenord.fr <p class="__title">)
                _mt = re.search(e["title_re"], m.group(2), re.S | re.I); t = clean(_mt.group(1)) if _mt else t
            if not re.search(e.get("year_re", "2026"), urllib.parse.unquote(u) + " " + t): continue
            if inc and not re.search(inc, urllib.parse.unquote(u) + " " + t, re.I): continue
            if urlsplit(u).netloc not in [urlsplit(base).netloc] + e.get("pdf_hosts", []): continue
            if not e.get("detail_re") and need_allowed and not allowed(u): continue
            if e.get("detail_re"):
                if TEST and len(out) >= TEST: return out
                if u in SEEN_DETAIL or not allowed(u): continue
                SEEN_DETAIL.add(u)
                try: dp = get(u)
                except Exception as ex: print(e["name"], "detail fail", u, ex, flush=True); continue
                _db = re.search(r'<base[^>]+href="([^"]+)"', dp, re.I); djb = urljoin(u, html.unescape(_db.group(1))) if _db else u
                k = 0
                for dm in re.finditer(r'<a[^>]+href="(' + e.get("link_re", r'[^"]+?\.pdf[^"]*') + r')"', dp, re.I):
                    pu = urljoin(djb, html.unescape(dm.group(1))).replace(" ", "%20")
                    if urlsplit(pu).netloc not in [urlsplit(base).netloc] + e.get("pdf_hosts", []): continue
                    if pu in out or (need_allowed and not allowed(pu)): continue
                    k += 1; out[pu] = t if k == 1 else t + " — " + urllib.parse.unquote(pu.rsplit("/", 1)[-1])
                continue
            out.setdefault(u, t)
    return out
def meta(e, url):
    q = e.get("qid"); issuer = e.get("issuer", "conseil_departemental")
    return dict(country_code="FR", place_id=("wd:" + q) if q else "iso:" + e["iso"], qid=q, place_name=e["name"], iso_3166_2=e["iso"], admin_level="departement",
                language="fr", doc_type="gazette_act", consolidated=False, platform="fr_raa_" + issuer, source_org="Conseil départemental — " + e["name"],
                issuer=issuer, max_bytes=50 * 1024 * 1024, index_url=url)
for e in ENTRIES:
    if not disk_ok(): break
    if e.get("archive_only"): print(e["name"], "archive_only (see fr_raa_archive_index.py)", flush=True); continue
    name, iso, url = e["name"], e["iso"], e["url"]
    DELAY[0] = max(float(e.get("crawl_delay", 3)), robots_delay(url)); print(name, "crawl_delay", DELAY[0], flush=True)
    if not allowed(url): print(name, "index robots disallowed/unreachable", flush=True); continue
    try: page = get(url)
    except Exception as ex: print(name, "index fail", ex, flush=True); continue
    pa = not e.get("pdf_archive") or not RESPECT_ROBOTS; found = pdfs(page, url, e, pa); pg = e.get("pager"); empty = 0
    for xu in e.get("extra_urls", []):
        if not allowed(xu): print(name, "extra robots disallowed", xu, flush=True); continue
        try: f2 = pdfs(get(xu), url, e, pa)
        except Exception as ex: print(name, "extra fail", xu, ex, flush=True); continue
        new = {k: v for k, v in f2.items() if k not in found}; found.update(new); print(name, "extra", xu, "pdfs", len(f2), "new", len(new), flush=True)
    if pg and not TEST:
        for n in range(1, pg["max"] + 1):
            pu = url + ("&" if "?" in url else "?") + f"{pg.get('param', 'page')}={n}"
            if not allowed(pu): print(name, "pager robots disallowed", pu, flush=True); break
            try: f2 = pdfs(get(pu), url, e, pa)
            except Exception as ex: print(name, "page fail", n, ex, flush=True); continue
            new = {k: v for k, v in f2.items() if k not in found}; found.update(new)
            print(name, "page", n, "pdfs", len(f2), "new", len(new), "total", len(found), flush=True)
            empty = 0 if f2 else empty + 1
            if empty >= pg.get("stop_empty", 2) or len(found) >= e.get("max_urls", 10 ** 6): break
    if e.get("max_urls"): found = dict(list(found.items())[:e["max_urls"]])
    if TEST: found = dict(list(found.items())[:TEST])
    if not pa:
        cfgp = HERE / f"fr_raa_cd_{iso.lower()}_archive{'_test' if TEST else ''}.json"
        json.dump(dict(meta(e, url), archive_policy="archived_robots_disallowed", urls=list(found), titles=found), open(cfgp, "w"), ensure_ascii=False, indent=1)
        print(name, e.get("qid"), "pdfs", len(found), "archive config", cfgp.name, "(PDF folder robots-disallowed -> archive_retry.py)", flush=True); continue
    cfgp = HERE / f"fr_raa_cd_{iso.lower()}{'_test' if TEST else ''}.json"
    json.dump(dict(meta(e, url), crawl_delay=DELAY[0], urls=list(found), titles=found), open(cfgp, "w"), ensure_ascii=False, indent=1)
    print(name, e.get("qid"), "pdfs", len(found), "config", cfgp.name, flush=True)
    if not found: continue
    logp = LOGS / f"fr_raa_cd_{iso}{'_test' if TEST else ''}.log"
    with open(logp, "w") as lf:
        subprocess.run([sys.executable, "-u", str(HERE / "us_pdf_list.py"), str(cfgp)], stdout=lf, stderr=subprocess.STDOUT, text=True, timeout=12 * 3600)
    last = [l for l in open(logp).read().splitlines() if l.startswith(("written", "STOP"))]
    print(name, (last or ["?"])[-1], flush=True)
