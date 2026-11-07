"""Build one us_pdf_list config per Lower Saxony Landkreis from kommunalfinanzen-niedersachsen.de Kreisrecht links,
then run us_pdf_list on each. Index pages are robots-checked (RFC 9309) too."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import re, sys, json, time, html, subprocess, urllib.request, urllib.parse
from pathlib import Path
from urllib.parse import urljoin, urlsplit
HERE = Path(__file__).parent; sys.argv = ["x", str(HERE / "_dummy_cfg.json")]
src = open(HERE / "us_pdf_list.py").read().split("w = StagedWriter")[0]; exec(src)   # UA, rfc_rules, rfc_allowed, disk_ok
import urllib.robotparser
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
def pdfs(page, base):
    out = {}
    for h, t in re.findall(r'<a[^>]+href="([^"]+\.pdf[^"]*)"[^>]*>(.*?)</a>', page, re.S | re.I):
        u = urllib.parse.quote(urljoin(base, html.unescape(h)), safe=":/?&=%#;+,@!$~*()'[]")  # 2026-10-21 followup: encode spaces
        if re.search(r"\.vcf(\?|$)|/visitenkarte/", u, re.I): continue  # 2026-10-21 followup: contact cards
        t = re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", " ", t))).strip()
        t = re.sub(r"\(?\s*PDF[^)]*\)?\s*$", "", t).strip(" -")
        out.setdefault(u, t or urllib.parse.unquote(u.rsplit("/", 1)[1]))
    return out
nds = get("https://www.kommunalfinanzen-niedersachsen.de/rechtsnavigator/kreis-und-ortsrecht/")
seg = nds.split('id="landkreise"', 1)[-1] if 'id="landkreise"' in nds else nds
links = list(dict.fromkeys(re.findall(r'<a href="(https?://[^"]+)"[^>]*>((?:Landkreis|Region|Heidekreis)[^<]*)</a>', seg)))
summary = []
for url, name in links:
    if not disk_ok(): break
    name = html.unescape(name).strip(); slug = re.sub(r"\W+", "_", name.lower()).strip("_")
    if not allowed(url): summary.append((name, "index_robots_disallowed_or_unreachable", 0)); continue
    try: page = get(url)
    except Exception as e: summary.append((name, "index_fail " + str(e)[:60], 0)); continue
    found = pdfs(page, url)
    if len(found) < 5:   # follow sub-pages under the same path
        pre = url.split("?")[0].rsplit("/", 1)[0] if not url.endswith("/") else url
        subs = [urljoin(url, h) for h in re.findall(r'href="([^"#]+)"', page)]
        subs = [s for s in dict.fromkeys(subs) if s.startswith(pre) and s != url and not s.lower().endswith(".pdf")][:15]
        for s in subs:
            if allowed(s):
                try: found.update({k: v for k, v in pdfs(get(s), s).items() if k not in found})
                except Exception: pass
    if not found: summary.append((name, "no_pdfs", 0)); continue
    try:
        q = json.load(urllib.request.urlopen(urllib.request.Request("https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&language=de&limit=1&search=" + urllib.parse.quote(name), headers={"User-Agent": "worldlaw/1.0"}), timeout=30))["search"][0]["id"]
    except Exception: summary.append((name, "no_qid", len(found))); continue
    cfgp = HERE / f"de_nds_{slug}.json"
    json.dump(dict(country_code="DE", place_id="wd:" + q, qid=q, place_name=name, iso_3166_2="DE-NI", admin_level="landkreis", language="de",
                   doc_type="ordinance", platform="de_nds_kreisrecht", source_org=name, index_url=url, urls=list(found)[:300], titles=found),
              open(cfgp, "w"), ensure_ascii=False, indent=1)
    r = subprocess.run([sys.executable, "-u", str(HERE / "us_pdf_list.py"), str(cfgp)], capture_output=True, text=True, timeout=7200)
    open(f"{_WORLD}/staging/counties/_logs/de_nds_{slug}.log", "w").write(r.stdout + r.stderr[-5000:])
    last = (r.stdout.strip().splitlines() or ["?"])[-1]; print(name, q, len(found), last, flush=True); summary.append((name, last, len(found)))
print(json.dumps(summary, ensure_ascii=False, indent=0))
