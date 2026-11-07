"""Romanian county council (CJ) decisions; derived from de_kreisrecht_build. Generic German Landkreis Kreisrecht crawler: index page + same-host sub-pages (depth<=2, law-ish paths, <=60 pages),
honours <base href>, RFC 9309 robots for index pages; then us_pdf_list per county (per-county log).
Usage: de_kreisrecht_build.py <entries.json> <platform> [max_urls per county, default 400; small value = test batch]   entries: [{"name","url","iso"}]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
# 2026-10-21: per-county us_pdf_list.py subprocess now sends scans straight to staging/pdf + _manifest (county_pdfstage.py) and keeps no _raw files.
import re, sys, json, time, html, subprocess, urllib.request, urllib.parse
from pathlib import Path
from urllib.parse import urljoin, urlsplit
HERE = Path(__file__).parent; ENT, PLAT = sys.argv[1], sys.argv[2]; MAXU = int(sys.argv[3]) if len(sys.argv) > 3 else 400; sys.argv = ["x", str(HERE / "_dummy_cfg.json")]
exec(open(HERE / "us_pdf_list.py").read().split("w = StagedWriter")[0])
YEARS = r"202[4-6]"
LOG = Path((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/staging/counties/_logs"))
_rc = {}
def allowed(u):
    if not RESPECT_ROBOTS: return True  # 2026-11-01: robots ignored by default (RESPECT_ROBOTS=1 restores)
    b = "{0.scheme}://{0.netloc}".format(urlsplit(u))
    if b not in _rc:
        try: _rc[b] = rfc_rules(urllib.request.urlopen(urllib.request.Request(b + "/robots.txt", headers={"User-Agent": UA}), timeout=30).read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e: _rc[b] = [] if e.code in (404, 410) else None
        except Exception: _rc[b] = None
    return _rc[b] is not None and rfc_allowed(_rc[b], u)
def get(u):
    time.sleep(2); r = urllib.request.urlopen(urllib.request.Request(urllib.parse.quote(u, safe=":/?&=%#;+,@!$~*()'"), headers={"User-Agent": UA}), timeout=60)
    return r.geturl(), r.read().decode("utf-8", "replace")
def base_of(page, url):
    m = re.search(r'<base[^>]+href="([^"]+)"', page, re.I); return urljoin(url, m.group(1)) if m else url
LAWY = re.compile(r"(hot[aă]r|hcj|monitor|decizi|registr|arhiv|20[0-9][0-9])", re.I)
def pdfs(page, base):
    out = {}
    _all = {}
    for h, t in re.findall(r'<a[^>]+href="([^"]+?\.pdf[^"]*|[^"]*download[^"]*)"[^>]*>(.*?)</a>', page, re.S | re.I):
        if not re.search(r"\.pdf|download", h, re.I): continue
        u = urllib.parse.quote(urljoin(base, html.unescape(h)), safe=":/?&=%#;+,@!$~*()'[]")  # 2026-10-21 followup: encode spaces
        if re.search(r"\.vcf(\?|$)|/visitenkarte/", u, re.I): continue  # 2026-10-21 followup: contact cards
        if 'readspeaker' in u or 'docreader' in u: continue
        if e.get("force_https") and u.startswith("http://"): u = "https://" + u[7:]  # site links http:// but port 80 hangs
        t = re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", " ", t))).strip()
        t = re.sub(r"\(?\s*PDF[^)]*\)?\s*$", "", t, flags=re.I).strip(" -")
        if re.search(r"anex", u + " " + t, re.I): continue
        if e.get("pdf_re") and not re.search(e["pdf_re"], urllib.parse.unquote(u) + " " + t, re.I): continue  # 2026-10-22: optional per-entry filter (site-wide menu PDFs on WP/Joomla CJ sites)
        if YEARS and not re.search(YEARS, urllib.parse.unquote(u) + " " + t): continue
        out.setdefault(u, t or urllib.parse.unquote(u.rsplit("/", 1)[-1]))
    return out
for e in json.load(open(ENT)):
    if not disk_ok(): break
    name, url = e["name"], e["url"]; slug = e.get("slug") or re.sub(r"\W+", "_", name.lower()).strip("_"); log = open(LOG / f"{PLAT}_{slug}.log", "w")
    host = urlsplit(url).netloc; seen, queue, found = set(), [(url, 0)], {}
    queue += [(_s, 0) for _s in e.get("seeds", [])]  # 2026-10-24 ro_next11: optional extra depth-0 seed URLs (e.g. per-decision pages listed in a WP sitemap)
    _fre = re.compile(e["follow_re"], re.I) if e.get("follow_re") else None  # 2026-10-23 ro_next10: optional "slug" (keeps earlier cfg/log), "follow_re" sub-page filter, "max_pages" cap
    while queue and len(seen) < e.get("max_pages", 60):
        u, d = queue.pop(0)
        if u in seen or not allowed(u): continue
        seen.add(u)
        try: fu, page = get(u)
        except Exception as ex: print("PAGEFAIL", u, ex, file=log); continue
        b = base_of(page, fu); found.update({k: v for k, v in pdfs(page, b).items() if k not in found})
        if d < 2:
            for h, t in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', page, re.S):
                s = urljoin(b, html.unescape(h))
                if urlsplit(s).netloc == host and s not in seen and not re.search(r"\.(pdf|jpe?g|png|docx?|zip)$", s, re.I) \
                   and (LAWY.search(s) or LAWY.search(re.sub("<[^>]+>", "", t))) and (not _fre or _fre.search(s)): queue.append((s, d + 1))
    print(name, "pages", len(seen), "pdfs", len(found), file=log, flush=True)
    if not found: print(name, "no_pdfs pages", len(seen), flush=True); continue
    q = e.get("qid")
    for _try in range(4):
        if q: break
        for _s in [e.get("qsearch", name)]:  # 2026-10-21: explicit "qid" in the entry wins; search retried (transient no_qid on Wunsiedel/Freising)
            try:
                _r = json.load(urllib.request.urlopen(urllib.request.Request("https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&language=en&limit=1&search=" + urllib.parse.quote(_s), headers={"User-Agent": "worldlaw/1.0"}), timeout=30)).get("search") or []
                if _r: q = _r[0]["id"]; break
            except Exception as _ex: print(name, "qid_lookup_err", _s, _ex, flush=True)
        if not q: time.sleep(20 * (_try + 1))
    if not q: print(name, "no_qid", flush=True); continue
    cfgp = HERE / f"{PLAT}_{slug}.json"
    json.dump(dict(country_code=e.get("cc","RO"), place_id="wd:" + q, qid=q, place_name=name, iso_3166_2=e.get("iso"), admin_level=e.get("admin_level","judet"), language=e.get("lang","ro"),
                   doc_type=e.get("doc_type","decision"), consolidated=False, platform=PLAT, source_org=name, index_url=url, max_bytes=50 * 1024 * 1024, urls=list(found)[:MAXU], titles=found),
              open(cfgp, "w"), ensure_ascii=False, indent=1)
    # 2026-10-23: stream us_pdf_list stdout into the per-county log line by line (progress visible while running); stderr tail appended at end
    _p = subprocess.Popen([sys.executable, "-u", str(HERE / "us_pdf_list.py"), str(cfgp)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    import threading; _err = []; _t = threading.Thread(target=lambda: _err.append(_p.stderr.read()), daemon=True); _t.start()
    _last = "?"; _t0 = time.time()
    for _line in _p.stdout:
        log.write(_line); log.flush(); _last = _line.strip() or _last
        if time.time() - _t0 > 14400: _p.kill(); break
    _p.wait(); _t.join(5); log.write((_err[0] if _err else "")[-5000:]); log.close()
    print(name, q, len(found), _last, flush=True)
