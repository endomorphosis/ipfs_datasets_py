"""2026-10-24 fr_raa_next1: conseil départemental RAA collections, next départements after FR-05 (fr_cd05_raa) and FR-36 (fr_raa_build).
Generalised from fr_raa_cd_build.py: entries come from a JSON file (name, iso, qid, url, issuer, optional include_re title/url filter),
2026 PDFs only (same rule as before), robots.txt checked per host (RFC 9309), 50 MB/file cap, then us_pdf_list per département
(skips source_urls already staged/processed, so test -> full is idempotent; query-string URLs get the URL-hash doc_id suffix there).
usage: fr_raa_next1_build.py ENTRIES.json [--test N]   (--test: only the first N PDFs per département, config suffix _test)"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import re, sys, json, time, html, subprocess, urllib.request, urllib.parse
from pathlib import Path
from urllib.parse import urljoin, urlsplit
ARGS = sys.argv[1:]
HERE = Path(__file__).parent; sys.argv = ["x", str(HERE / "_dummy_cfg.json")]
exec(open(HERE / "us_pdf_list.py").read().split("w = StagedWriter")[0])
ENTRIES = json.load(open(ARGS[0])); TEST = int(ARGS[ARGS.index("--test") + 1]) if "--test" in ARGS else 0
LOGS = Path((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/staging/counties/_logs"))
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
    time.sleep(2); return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=60).read().decode("utf-8", "replace")
def pdfs(page, base, inc):
    out = {}
    for m in re.finditer(r'<a[^>]+href="([^"]+?(?:\.pdf|/file/[^"]+))"[^>]*>(.*?)</a>', page, re.S | re.I):
        h, t = m.group(1), m.group(2)
        u = urljoin(base, html.unescape(h)).replace(" ", "%20")
        t = re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", " ", t))).strip(); t = re.sub(r"^Télécharger\s*", "", t)
        if re.match(r"^(cliquez|ici|t[ée]l[ée]charger|lien|pdf)\b", t, re.I) or not t:  # generic link text (lot.fr "cliquez ici"): use the text just before the link + file name
            pre = re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", "|", page[max(0, m.start() - 300):m.start()]))).split("|")[-1].strip(" :-")
            t = ((pre + " — ") if pre else "") + urllib.parse.unquote(u.rsplit("/", 1)[-1])
        if "2026" not in urllib.parse.unquote(u) + t: continue
        if inc and not re.search(inc, urllib.parse.unquote(u) + " " + t, re.I): continue
        if urlsplit(u).netloc != urlsplit(base).netloc or not allowed(u): continue
        out.setdefault(u, t or urllib.parse.unquote(u.rsplit("/", 1)[1]))
    return out
for e in ENTRIES:
    if not disk_ok(): break
    if e.get("archive_only"): print(e["name"], "archive_only (see fr_raa_archive_index.py)", flush=True); continue
    name, iso, url = e["name"], e["iso"], e["url"]; issuer = e.get("issuer", "conseil_departemental")
    if not allowed(url): print(name, "index robots disallowed/unreachable", flush=True); continue
    try: page = get(url)
    except Exception as ex: print(name, "index fail", ex, flush=True); continue
    found = pdfs(page, url, e.get("include_re"))
    if TEST: found = dict(list(found.items())[:TEST])
    q = e.get("qid")
    cfgp = HERE / f"fr_raa_cd_{iso.lower()}{'_test' if TEST else ''}.json"
    json.dump(dict(country_code="FR", place_id=("wd:" + q) if q else "iso:" + iso, qid=q, place_name=name, iso_3166_2=iso, admin_level="departement",
                   language="fr", doc_type="gazette_act", consolidated=False, platform="fr_raa_" + issuer, source_org="Conseil départemental — " + name,
                   issuer=issuer, max_bytes=50 * 1024 * 1024, index_url=url, urls=list(found), titles=found), open(cfgp, "w"), ensure_ascii=False, indent=1)
    print(name, q, "pdfs", len(found), "config", cfgp.name, flush=True)
    if not found: continue
    logp = LOGS / f"fr_raa_cd_{iso}{'_test' if TEST else ''}.log"
    with open(logp, "w") as lf:
        r = subprocess.run([sys.executable, "-u", str(HERE / "us_pdf_list.py"), str(cfgp)], stdout=lf, stderr=subprocess.STDOUT, text=True, timeout=14400)
    last = [l for l in open(logp).read().splitlines() if l.startswith(("written", "STOP"))]
    print(name, (last or ["?"])[-1], flush=True)
