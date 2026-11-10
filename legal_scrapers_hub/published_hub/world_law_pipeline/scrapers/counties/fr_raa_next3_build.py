"""2026-10-24 fr_raa_next3: Pas-de-Calais (FR-62, Q12689) conseil départemental 'Publicité des actes administratifs' (post-2022 reform, acts published
individually; no monthly RAA). Drupal 'kiosque' listings, newest first, 12 items/page, ?page=N. Each item: <span class="title__content">title</span>,
<p class="published-date">Publié le DD Mon. YYYY</p>, 'Extension: pdf', link /download/file/<id>?key=<token> (query string -> URL-hash doc_id suffix in us_pdf_list).
Rules: robots RFC 9309 checked for every listing page and PDF (pasdecalais.fr robots: Crawl-Delay 10 -> 10 s between ALL requests, also in us_pdf_list via
crawl_delay; Disallow /actualites* /kiosque* /*keys= /search/ ... -- none of the used paths); only items 'Publié le ... 2026'; non-pdf extensions skipped
(spreadsheets never fetched); 50 MB cap; already-staged source_urls skipped by us_pdf_list (test -> full idempotent).
usage: fr_raa_next3_build.py ENTRIES.json [--test N]"""
import re, sys, json, time, html, subprocess, urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlsplit
ARGS = sys.argv[1:]
HERE = Path(__file__).parent; sys.argv = ["x", str(HERE / "_dummy_cfg.json")]
exec(open(HERE / "us_pdf_list.py").read().split("w = StagedWriter")[0])
ENTRIES = json.load(open(ARGS[0])); TEST = int(ARGS[ARGS.index("--test") + 1]) if "--test" in ARGS else 0
LOGS = Path("/workspace/world_law/staging/counties/_logs"); DELAY = 10
_rc = {}
def allowed(u):
    if not RESPECT_ROBOTS: return True  # 2026-11-01: robots ignored by default (RESPECT_ROBOTS=1 restores)
    b = "{0.scheme}://{0.netloc}".format(urlsplit(u))
    if b not in _rc:
        try: _rc[b] = rfc_rules(urllib.request.urlopen(urllib.request.Request(b + "/robots.txt", headers={"User-Agent": UA}), timeout=30).read().decode("utf-8", "replace")); time.sleep(DELAY)
        except urllib.error.HTTPError as e: _rc[b] = [] if e.code in (404, 410) else None
        except Exception: _rc[b] = None
    return _rc[b] is not None and rfc_allowed(_rc[b], u)
def get(u):
    time.sleep(DELAY); return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=60).read().decode("utf-8", "replace")
def clean(t): return re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", " ", t))).strip()
def items(page, base):
    """-> (dict url->title for 2026 pdf items, n_items_on_page, n_2026)"""
    out = {}; blocks = re.split(r'<div class="views-row', page)[1:]; n26 = 0
    for b in blocks:
        t = re.search(r'<span\s+class="title__content"[^>]*>(.*?)</span>', b, re.S); d = re.search(r'Publié le ([^<]+)</p>', b)
        a = re.search(r'href="(/download/file/\d+\?key=[^"]+)"', b); ext = re.search(r'Extension:\s*([A-Za-z0-9]+)', b)
        if not (t and d and a): continue
        if not re.search(r"\b2026\b", d.group(1)): continue
        n26 += 1
        if ext and ext.group(1).lower() != "pdf": continue          # skip xls/xlsx/doc etc.
        u = urljoin(base, html.unescape(a.group(1)))
        if not allowed(u): print("pdf robots disallowed", u, flush=True); continue
        out.setdefault(u, clean(t.group(1)) + " (publié le " + clean(d.group(1)) + ")")
    return out, len(blocks), n26
for e in ENTRIES:
    if not disk_ok(): break
    name, iso, q = e["name"], e["iso"], e["qid"]; found = {}
    for lst in e["lists"]:
        url = "https://www.pasdecalais.fr/" + lst["path"]; empty = 0; n0 = len(found)
        for n in range(0, lst.get("max_pages", 200)):
            pu = url if n == 0 else url + f"?page={n}"
            if not allowed(pu): print(name, lst["path"], "robots disallowed", pu, flush=True); break
            try: f2, nb, n26 = items(get(pu), url)
            except Exception as ex: print(name, lst["path"], "page fail", n, ex, flush=True); empty += 1; continue
            new = {k: v for k, v in f2.items() if k not in found}; found.update(new)
            print(name, lst["path"], "page", n, "items", nb, "2026", n26, "new", len(new), "total", len(found), flush=True)
            if TEST and len(found) - n0 >= TEST: break
            empty = 0 if n26 else empty + 1
            if nb == 0 or empty >= lst.get("stop_empty", 2) or len(found) >= e.get("max_urls", 10 ** 6): break
        if TEST: found = dict(list(found.items())[:n0 + TEST])
    cfgp = HERE / f"fr_raa_cd_{iso.lower()}{'_test' if TEST else ''}.json"
    json.dump(dict(country_code="FR", place_id="wd:" + q, qid=q, place_name=name, iso_3166_2=iso, admin_level="departement", language="fr", doc_type="gazette_act",
                   consolidated=False, platform="fr_raa_conseil_departemental", source_org="Conseil départemental — " + name, issuer="conseil_departemental",
                   max_bytes=50 * 1024 * 1024, crawl_delay=DELAY, index_url="https://www.pasdecalais.fr/publicite-des-actes-administratifs",
                   urls=list(found), titles=found), open(cfgp, "w"), ensure_ascii=False, indent=1)
    print(name, q, "pdfs", len(found), "config", cfgp.name, flush=True)
    if not found: continue
    logp = LOGS / f"fr_raa_cd_{iso}{'_test' if TEST else ''}.log"
    with open(logp, "w") as lf:
        subprocess.run([sys.executable, "-u", str(HERE / "us_pdf_list.py"), str(cfgp)], stdout=lf, stderr=subprocess.STDOUT, text=True, timeout=12 * 3600)
    last = [l for l in open(logp).read().splitlines() if l.startswith(("written", "STOP"))]
    print(name, (last or ["?"])[-1], flush=True)
