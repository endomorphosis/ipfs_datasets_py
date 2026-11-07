"""2026-10-24 de_by12: archive-only configs for Landkreise whose PDF endpoints are robots-disallowed but whose index pages are robots-allowed.
Index pages are fetched live only after an RFC 9309 robots check; PDF links (matching per-entry link_re) are written to an archive_retry config
(same format as archive_index_build.py). PDFs themselves are fetched ONLY from Common Crawl / Wayback by archive_retry.py.
Usage: de_by12_index_cfg.py <entries.json> <platform> [max_urls]   entries: [{"name","qid","iso","index_urls":[..],"link_re","archive_policy","norm":[[re,repl],..]}]"""
import re, sys, json, time, html, urllib.request, urllib.parse
from pathlib import Path
from urllib.parse import urljoin, urlsplit
HERE = Path(__file__).parent; ENT, PLAT = sys.argv[1], sys.argv[2]; MAXU = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
_argv = sys.argv[:]; sys.argv = ["x", str(HERE / "_dummy_cfg.json")]; _ns = {}; exec(open(HERE / "us_pdf_list.py").read().split("w = StagedWriter")[0], _ns); sys.argv = _argv
UA, rfc_rules, rfc_allowed = _ns["UA"], _ns["rfc_rules"], _ns["rfc_allowed"]
_rc = {}
def allowed(u):
    if not RESPECT_ROBOTS: return True  # 2026-11-01: robots ignored by default (RESPECT_ROBOTS=1 restores)
    b = "{0.scheme}://{0.netloc}".format(urlsplit(u))
    if b not in _rc:
        try: _rc[b] = rfc_rules(urllib.request.urlopen(urllib.request.Request(b + "/robots.txt", headers={"User-Agent": UA}), timeout=30).read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e: _rc[b] = [] if e.code in (404, 410) else None
        except Exception: _rc[b] = None
    return _rc[b] is not None and rfc_allowed(_rc[b], u)
for e in json.load(open(ENT)):
    name = e["name"]; slug = re.sub(r"\W+", "_", name.lower()).strip("_"); found = {}
    for iu in e["index_urls"]:
        if not allowed(iu): print(name, "INDEX_ROBOTS_DISALLOWED", iu, flush=True); continue
        time.sleep(2)
        try: page = urllib.request.urlopen(urllib.request.Request(iu, headers={"User-Agent": UA}), timeout=60).read().decode("utf-8", "replace")
        except Exception as ex: print(name, "PAGEFAIL", iu, ex, flush=True); continue
        n0 = len(found)
        for h, t in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S | re.I):
            u = urljoin(iu, html.unescape(h))
            if not re.search(e["link_re"], u, re.I): continue
            for a, b in e.get("norm", []): u = re.sub(a, b, u)
            t = re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", " ", t))).strip(); t = re.sub(r"\(?\s*PDF[^)]*\)?\s*$", "", t, flags=re.I).strip(" -")
            if len(re.sub(r"\W", "", t)) < 3: t = ""
            if not t:
                m = re.search(r"[?&]fn=([^&]+)", u); t = urllib.parse.unquote(m.group(1)).replace("_", " ") if m else ""
            if u not in found or (t and not found[u]): found[u] = t
        print(name, "index", iu, "links", len(found) - n0, flush=True)
    print(name, "total", len(found), flush=True)
    if not found: continue
    cfgp = HERE / f"de_{PLAT}_{slug}_archive.json"
    json.dump(dict(country_code="DE", place_id="wd:" + e["qid"], qid=e["qid"], place_name=name, iso_3166_2=e.get("iso"), admin_level="landkreis", language="de",
                   doc_type="ordinance", platform="de_" + PLAT, source_org=name, index_url=e["index_urls"][0], archive_policy=e.get("archive_policy", "archived_robots_disallowed"),
                   max_bytes=50 * 1024 * 1024, urls=list(found)[:MAXU], titles={k: v for k, v in found.items() if v}), open(cfgp, "w"), ensure_ascii=False, indent=1)
    print(name, "config", cfgp, "urls", min(len(found), MAXU), flush=True)
