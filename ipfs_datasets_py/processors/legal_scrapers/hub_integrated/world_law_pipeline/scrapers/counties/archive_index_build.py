"""2026-10-21: build archive-only configs for Landkreis sites the box cannot crawl live (unreachable / 5xx robots / robots-blocked),
then run archive_retry.py on each. Index page + up to 15 law-ish sub-pages are read from Common Crawl / Wayback only (never live).
Usage: archive_index_build.py <entries.json> <platform> [max_minutes_total] [max_urls, small = test]   entries: [{"name","url","iso","qid"}]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import re, sys, json, time, html, subprocess, urllib.parse
from pathlib import Path
from urllib.parse import urljoin, urlsplit
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline"))
from archive import ArchiveFetcher, ArchiveDeferred, ArchiveError
HERE = Path(__file__).parent; ENT, PLAT = sys.argv[1], sys.argv[2]; DEADLINE = time.time() + 60 * float(sys.argv[3] if len(sys.argv) > 3 else 600)
MAXU = int(sys.argv[4]) if len(sys.argv) > 4 else 400
fx = ArchiveFetcher(cc_crawls=8)
LAWY = re.compile(r"(kreisrecht|satzung|verordnung|ortsrecht|recht|bekanntmach|amtsblatt|gebühr|gebuehr|abfall)", re.I)
PDFRX = r'<a[^>]+href="([^"]+?\.pdf[^"]*|[^"]*download[^"]*|[^"]*loadDocument\.phtml\?[^"]*Ext=PDF[^"]*)"[^>]*>(.*?)</a>'
def arch(u, tries=40):
    for _ in range(tries):
        if time.time() > DEADLINE: return None
        try:
            d = fx.fetch_newest(u); return d
        except ArchiveDeferred as e: time.sleep(max(30, min(600, e.retry_in or 60)))
        except ArchiveError as e: print("ARCHMISS", u, str(e)[:150], flush=True); return None
    return None
def unwrap(h):  # Wayback-rewritten links -> original
    m = re.match(r"(?:https?://web\.archive\.org)?/web/\d+[a-z_]*/(.+)", h); return m.group(1) if m else h
def pdfs(page, base):
    out = {}
    for h, t in re.findall(PDFRX, page, re.S | re.I):
        u = urljoin(base, unwrap(html.unescape(h)))
        if 'readspeaker' in u or 'docreader' in u: continue
        t = re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", " ", t))).strip(); t = re.sub(r"\(?\s*PDF[^)]*\)?\s*$", "", t, flags=re.I).strip(" -")
        out.setdefault(u, t or urllib.parse.unquote(u.rsplit("/", 1)[-1]))
    return out
for e in json.load(open(ENT)):
    name, url = e["name"], e["url"]; slug = re.sub(r"\W+", "_", name.lower()).strip("_"); host = urlsplit(url).netloc
    d = arch(url)
    if d is None: print(name, "no_archived_index", flush=True); continue
    page = d.text(); found = pdfs(page, url); subs = []
    for h, t in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', page, re.S):
        s = urljoin(url, unwrap(html.unescape(h)))
        if urlsplit(s).netloc == host and s != url and s not in subs and not re.search(r"\.(pdf|jpe?g|png|docx?|zip)$|loadDocument", s, re.I) \
           and (LAWY.search(s) or LAWY.search(re.sub("<[^>]+>", "", t))): subs.append(s)
    for s in subs[:15]:
        sd = arch(s, tries=6)
        if sd is not None: found.update({k: v for k, v in pdfs(sd.text(), s).items() if k not in found})
    print(name, "archived index", d.provenance().get("archive_source"), "subpages", min(len(subs), 15), "pdfs", len(found), flush=True)
    if not found: continue
    cfgp = HERE / f"de_{PLAT}_{slug}_archive.json"
    json.dump(dict(country_code="DE", place_id="wd:" + e["qid"], qid=e["qid"], place_name=name, iso_3166_2=e.get("iso"), admin_level="landkreis", language="de",
                   doc_type="ordinance", platform="de_" + PLAT, source_org=name, index_url=url, archive_policy=e.get("archive_policy", "archived_live_unreachable"),
                   max_bytes=50 * 1024 * 1024, urls=list(found)[:MAXU], titles=found), open(cfgp, "w"), ensure_ascii=False, indent=1)
    left = max(10, (DEADLINE - time.time()) / 60)
    r = subprocess.run([sys.executable, "-u", str(HERE / "archive_retry.py"), str(cfgp), str(min(left, 240))], capture_output=True, text=True)
    print(name, e["qid"], len(found), (r.stdout.strip().splitlines() or ["?"])[-1], flush=True)
