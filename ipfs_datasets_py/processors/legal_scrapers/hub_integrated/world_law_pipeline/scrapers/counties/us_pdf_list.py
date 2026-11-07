"""Generic county PDF-list scraper: live fetch (robots-checked), pdftotext; no OCR.
Usage: python3 us_pdf_list.py <config.json>   config: {place_id,gnis,qid,place_name,state_code,platform,source_org,urls:[...]}"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, json, re, time, urllib.parse, hashlib, datetime, subprocess, urllib.request, urllib.robotparser
from pathlib import Path
from urllib.parse import urlsplit, unquote
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline"))
from archive import StagedWriter, ArchiveFetcher, provenance_fields
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/scrapers/counties")); from county_pdfstage import text_of, ScanStager, quote_url, sniff  # 2026-10-21: no _raw
UA = "Mozilla/5.0 (world_law county lane)"
import os
# 2026-11-01 Benjamin: robots.txt no longer honoured for legal texts by default (RESPECT_ROBOTS=1 or --respect-robots restores the old behaviour).
# Still fetched + recorded in source_policy; polite delays, honest UA; WAF/Cloudflare/captcha never bypassed; no proxies.
RESPECT_ROBOTS = os.environ.get("RESPECT_ROBOTS", "0") == "1" or "--respect-robots" in sys.argv
if "--respect-robots" in sys.argv: sys.argv.remove("--respect-robots")
import shutil
def disk_ok():
    free = shutil.disk_usage("/workspace").free / 1048576  # 2026-10-30: MiB, floor 10240 = GUARD_MIN_MIB (10 GB fleet floor 2026-11-02; was 20480) (Benjamin lowered the floor to 20 GB on 2026-10-27; old 45 GB check would stop live crawls at ~43 GB free)
    if free < 10240: print("STOP: free disk %.0f MiB < 10240" % free, flush=True); return False
    return True
cfg = json.load(open(sys.argv[1])); RAW = Path((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/staging/counties/_raw")) / cfg["platform"]  # legacy name only; nothing written there since 2026-10-21
rp_cache = {}
def rfc_rules(txt):
    """RFC 9309: rules of the '*' group(s) (we send no named product token)."""
    rules, grp, in_star, last_ua = [], [], False, False
    for line in txt.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line: continue
        k, v = [x.strip() for x in line.split(":", 1)]; k = k.lower()
        if k == "user-agent":
            if not last_ua: in_star = False
            in_star = in_star or v == "*"; last_ua = True
        elif k in ("allow", "disallow"):
            last_ua = False
            if in_star and v: rules.append((k == "allow", v))
        else: last_ua = False
    return rules
def rfc_allowed(rules, u):
    sp = urlsplit(u); path = (sp.path or "/") + ("?" + sp.query if sp.query else "")
    best = (-1, True)
    for allow, pat in rules:
        rx = "^" + re.escape(pat).replace(r"\*", ".*")
        if rx.endswith(r"\$"): rx = rx[:-2] + "$"
        if re.match(rx, path) or re.match(rx, unquote(path)):
            L = len(pat)
            if L > best[0] or (L == best[0] and allow): best = (L, allow)
    return best[1]
def robots(u):
    h = urlsplit(u); base = f"{h.scheme}://{h.netloc}"
    if base not in rp_cache:
        try:
            r = urllib.request.urlopen(urllib.request.Request(base + "/robots.txt", headers={"User-Agent": UA}), timeout=30)
            rp_cache[base] = ("ok", rfc_rules(r.read().decode("utf-8", "replace")))
        except urllib.error.HTTPError as e:
            rp_cache[base] = ("404", None) if e.code in (404, 410) else ("unreach", None)
        except Exception: rp_cache[base] = ("unreach", None)
    st, rp = rp_cache[base]
    if st == "404": return "robots_404_allow_rfc9309"
    if st == "unreach": return "robots_unreachable"
    return "robots_allowed_rfc9309" if rfc_allowed(rp, u) else "robots_disallowed"
from schema import validate_record
ss = ScanStager()
w = StagedWriter((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/staging/counties"), cfg.get("country_code","US"), cfg["place_id"], batch_prefix=cfg["platform"], chunk=500)
staged = set()
import itertools  # 2026-10-21: also skip URLs the uploader already moved to processed/counties/<CC> (test-batch docs were re-fetched)
for _f in itertools.chain(Path((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/staging/counties")).rglob("*.jsonl"), (Path((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/processed/counties")) / cfg.get("country_code","US")).glob("*.jsonl*")):
    if cfg["platform"] not in str(_f): continue
    for _l in (__import__("gzip").open(_f, "rt", errors="replace") if str(_f).endswith(".gz") else open(_f, errors="replace")):
        _m = re.search(r'"source_url": ?"([^"]+)"', _l)
        if _m: staged.add(_m.group(1))
now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"); ok = fail = 0; fx = None
for i, u in enumerate(cfg["urls"]):
    if not disk_ok(): break
    u = quote_url(u)  # 2026-10-21 followup: spaces etc. percent-encoded in fetch AND source_url
    if u in staged or urllib.parse.unquote(u) in staged: print("SKIP_STAGED", u, flush=True); continue
    if sniff(b"", u) == "vcf": print("SKIP_VCF", u, flush=True); continue  # contact cards are never documents
    pol = robots(u); prov = {}
    try:
        if not RESPECT_ROBOTS and pol == "robots_disallowed": pol = "robots_disallowed;robots_ignored_live_20261101"  # tag kept: real robots policy of the site
        if pol in ("robots_allowed_rfc9309", "robots_404_allow_rfc9309") or pol.startswith("robots_disallowed;robots_ignored"):
            resp = urllib.request.urlopen(urllib.request.Request(urllib.parse.quote(u, safe=":/?&=%#;+,@!$~*()'"), headers={"User-Agent": UA}), timeout=300)
            cap = cfg.get("max_bytes"); cl = int(resp.headers.get("Content-Length") or 0)
            if cap and cl > cap: resp.close(); print("SKIP_SIZE", cl, u, flush=True); continue
            data = resp.read(cap + 1) if cap else resp.read()
            if cap and len(data) > cap: print("SKIP_SIZE", len(data), u, flush=True); continue
            ct = (resp.headers.get("Content-Type") or "").lower()
            if "application/pdf" not in ct and not data.startswith(b"%PDF"):
                # HTML download page / form: follow one level to a real PDF link, else skip
                pg = data.decode("utf-8", "replace"); nxt = None
                for h in re.findall(r'href="([^"]+?\.pdf[^"]*)"', pg, re.I):
                    nxt = urllib.parse.urljoin(resp.geturl(), h.replace("&amp;", "&")); break
                if not nxt or (RESPECT_ROBOTS and robots(nxt) not in ("robots_allowed_rfc9309", "robots_404_allow_rfc9309")) or robots(nxt) == "robots_unreachable":
                    print("SKIP_NOTPDF", ct or "?", u, flush=True); continue
                time.sleep(2); resp = urllib.request.urlopen(urllib.request.Request(urllib.parse.quote(nxt, safe=":/?&=%#;+,@!$~*()'"), headers={"User-Agent": UA}), timeout=300)
                data = resp.read(cap + 1) if cap else resp.read(); ct = (resp.headers.get("Content-Type") or "").lower()
                if (cap and len(data) > cap) or ("application/pdf" not in ct and not data.startswith(b"%PDF")):
                    print("SKIP_NOTPDF_FOLLOWED", ct or "?", nxt, flush=True); continue
                print("FOLLOWED", u, "->", nxt, flush=True); u = nxt
        else:
            fx = fx or ArchiveFetcher(cc_crawls=8); d = fx.fetch_newest(u); data = d.body; prov = provenance_fields(d); pol = "archived_" + pol
            if not data.lstrip()[:5].startswith(b"%PDF"): print("SKIP_NOTPDF archived", u, flush=True); continue
        kind = sniff(data, u)
        if kind != "pdf": print("SKIP_NOTPDF_KIND", kind, u, flush=True); continue  # never label vcf/xls/html as scanned_pdf
        name = unquote(u.split("/")[-1].split("?")[0]); p = RAW / (hashlib.sha1(u.encode()).hexdigest()[:10] + "_" + re.sub(r"[^\w.-]", "_", name))
        txt = text_of(data)  # 2026-10-21: raw bytes not kept; scans go to staging/pdf below
        scanned = len(txt.strip()) < 200
        title = re.sub(r"[_-]+", " ", name[:-4]).strip()
        rec = {"place_id": cfg["place_id"], "country_code": cfg.get("country_code","US"), "gnis": cfg.get("gnis"),
               "doc_id": cfg["platform"] + ":" + hashlib.sha1(u.split("?")[0].encode()).hexdigest()[:16] + (("~" + hashlib.sha1(u.encode()).hexdigest()[:8]) if "?" in u else ""), "doc_order": i,  # 2026-10-21: URL-hash suffix for query-string URLs (same rule as county_pdfstage)
               "source_platform": cfg["platform"], "source_url": u, "doc_type": cfg.get("doc_type","regulation"), "language": cfg.get("language","en"),
               "title_native": cfg.get("titles",{}).get(u, title), "consolidated": cfg.get("consolidated", True), "content_format": "pdf_text", "retrieved_at": now,
               "source_policy": pol, "source_official": True, "source_org": cfg["source_org"],
               "place_name": cfg["place_name"], "qid": cfg["qid"], "iso_3166_2": cfg.get("iso_3166_2") or "US-" + cfg["state_code"],
               "admin_level": cfg.get("admin_level","county"), "state_code": cfg.get("state_code"), "platform": cfg["platform"], **prov}
        if scanned:
            rec.update(content_complete=False, scanned_pdf=True, pdf_bytes=len(data))
            if not validate_record(rec): rec["pdf_path"] = ss.add(data, rec, now)
        else: rec["text"] = txt
        e = w.add(rec); print(("INVALID " + e) if e else "OK", pol, len(txt), u); ok += not e; fail += bool(e)
    except Exception as ex:
        print("FAIL", pol, u, ex); fail += 1
    time.sleep(cfg.get("crawl_delay", 3))  # 2026-10-24 fr_raa_next3: optional robots Crawl-Delay (pasdecalais.fr: 10); default unchanged
print("written:", w.flush(), "ok", ok, "fail", fail, "scan_batches", [ss.flush()] + ss.batches)
