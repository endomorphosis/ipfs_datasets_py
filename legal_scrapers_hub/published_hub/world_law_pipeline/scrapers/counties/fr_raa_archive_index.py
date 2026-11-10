"""2026-10-24 fr_raa_next1: archive-only config for French conseil départemental RAA pages the box cannot read live
(e.g. isere.fr now answers every request, incl. PDFs, with a JS cookie 'shield' challenge -> we do NOT solve it; archive copies only).
Index page read from Common Crawl / Wayback only (never live); 2026 PDF links (+ optional include_re) -> fr_raa_cd_<iso>_archive.json
in archive_retry.py format. Usage: fr_raa_archive_index.py <entries.json> [max_minutes] [max_urls]"""
import re, sys, json, time, html, urllib.parse
from pathlib import Path
from urllib.parse import urljoin, urlsplit
sys.path.insert(0, "/workspace/world_law/pipeline")
from archive import ArchiveFetcher, ArchiveDeferred, ArchiveError
HERE = Path(__file__).parent; DEADLINE = time.time() + 60 * float(sys.argv[2] if len(sys.argv) > 2 else 120)
MAXU = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
fx = ArchiveFetcher(cc_crawls=8)
def arch(u, tries=40):
    for _ in range(tries):
        if time.time() > DEADLINE: return None
        try: return fx.fetch_newest(u)
        except ArchiveDeferred as e: time.sleep(max(30, min(600, e.retry_in or 60)))
        except ArchiveError as e: print("ARCHMISS", u, str(e)[:150], flush=True); return None
    return None
def unwrap(h):
    m = re.match(r"(?:https?://web\.archive\.org)?/web/\d+[a-z_]*/(.+)", h); return m.group(1) if m else h
for e in json.load(open(sys.argv[1])):
    if not e.get("archive_only"): continue
    name, iso, url = e["name"], e["iso"], e["url"]; host = urlsplit(url).netloc
    d = arch(url)
    if d is None: print(name, "no_archived_index", flush=True); continue
    page = d.text(); found = {}
    for h, t in re.findall(r'<a[^>]+href="([^"]+?\.pdf[^"]*)"[^>]*>(.*?)</a>', page, re.S | re.I):
        u = urljoin(url, unwrap(html.unescape(h))).replace(" ", "%20")
        t = re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", " ", t))).strip()
        if urlsplit(u).netloc != host or "2026" not in urllib.parse.unquote(u) + t: continue
        if e.get("include_re") and not re.search(e["include_re"], urllib.parse.unquote(u) + " " + t, re.I): continue
        found.setdefault(u, t or urllib.parse.unquote(u.rsplit("/", 1)[-1]))
    print(name, "archived index", d.provenance().get("archive_source"), d.provenance().get("archive_timestamp") or "", "pdfs", len(found), flush=True)
    if not found: continue
    issuer = e.get("issuer", "conseil_departemental"); q = e.get("qid")
    cfgp = HERE / f"fr_raa_cd_{iso.lower()}_archive.json"
    json.dump(dict(country_code="FR", place_id=("wd:" + q) if q else "iso:" + iso, qid=q, place_name=name, iso_3166_2=iso, admin_level="departement",
                   language="fr", doc_type="gazette_act", consolidated=False, platform="fr_raa_" + issuer, source_org="Conseil départemental — " + name,
                   issuer=issuer, max_bytes=50 * 1024 * 1024, index_url=url, archive_policy=e.get("archive_policy", "archived_live_download_refused"),
                   urls=list(found)[:MAXU], titles=found), open(cfgp, "w"), ensure_ascii=False, indent=1)
    print(name, "config", cfgp.name, "urls", min(len(found), MAXU), flush=True)
