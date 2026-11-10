#!/usr/bin/env python3
"""2026-11-04 county lane: Kreis Gütersloh (wd:Q6218) Amtsblatt lister -> pdf_list_fetch.py entries JSON.
Site: kreis-guetersloh.de/aktuelles/amtsblaetter/ ; newer years list PDFs directly, older years (<=~2019) have ONE HTML
page per issue (amtsblatt-nr-N-vom-DD-MM-YYYY/) holding the PDF. Same host, 2 s/request, honest WorldLawBot UA,
no bypass (challenge pages skipped). PDFs only (spreadsheets ignored). Dedup on URL path (cid query differs).
Usage: de_gt_list.py <out.json> [--limit N]"""
import re, sys, json, time, html, urllib.parse as U, requests
UA = "WorldLawBot/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law; public-law research crawler; polite)"
BASE = "https://www.kreis-guetersloh.de/aktuelles/amtsblaetter/"
out = sys.argv[1]; lim = int(sys.argv[sys.argv.index("--limit")+1]) if "--limit" in sys.argv else 0
s = requests.Session(); s.headers["User-Agent"] = UA; s.trust_env = False
def get(u):
    time.sleep(2)
    try: r = s.get(u, timeout=(15, 60)); r.raise_for_status()
    except Exception as e: print("ERR", u, e, flush=True); return None
    if "cf-chl" in r.text or "captcha" in r.text.lower()[:5000]: print("CHALLENGE", u, flush=True); return None
    return r
def links(r):
    for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.I | re.S):
        h = U.urljoin(r.url, html.unescape(m.group(1))).split("#")[0]
        if U.urlsplit(h).netloc != "www.kreis-guetersloh.de": continue
        yield h, re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", m.group(2))).strip()
items = {}
def add(h, t):
    k = U.urlsplit(h).path
    if k not in items: items[k] = (h, t)
r = get(BASE); years = [BASE + "aktuelle-amtsblaetter/"]
for h, t in links(r) if r else []:
    if re.search(r"/archiv-amtsblaetter/am[a-z]*-\d{4}[^/]*/$", h) and h not in years: years.append(h)
issues = []
for y in years:
    r = get(y)
    if not r: continue
    for h, t in links(r):
        if re.search(r"\.pdf($|\?)", h, re.I) and "amtsbl" in h.lower(): add(h, t)
        elif re.search(r"/amtsblatt-nr-\d+[^/]*/$", h) and h.startswith(y) and h not in issues: issues.append(h)
    print(f"year {y} -> {len(items)} pdfs, {len(issues)} issue pages", flush=True)
for i, u in enumerate(issues):
    r = get(u)
    if not r: continue
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", r.text, re.S); t1 = re.sub("<[^>]+>", " ", h1.group(1)).strip() if h1 else ""
    for h, t in links(r):
        if re.search(r"\.pdf($|\?)", h, re.I): add(h, t1 or t)
    if i % 50 == 0: print(f"issue {i}/{len(issues)} -> {len(items)} pdfs", flush=True)
its = []
for k, (h, t) in items.items():
    s2 = t + " " + U.unquote(k)
    m = re.search(r"(\d{1,2})[.-](\d{1,2})[.-](\d{4})", s2) or None
    dt = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None
    m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})-amtsblatt", k)
    if not dt and m2: dt = f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)}"
    n = re.search(r"nr[.-]?\s*-?(\d+)", s2, re.I)
    its.append({"url": h, "title": t or U.unquote(k.rsplit("/", 1)[-1]), "number": n.group(1) if n else None, "published_date": dt, "kind": "amtsblatt"})
its.sort(key=lambda x: x["published_date"] or "", reverse=True)
if lim: its = its[:lim]
meta = {"place_id": "wd:Q6218", "qid": "Q6218", "country_code": "DE", "source_platform": "de_kreis_amtsblatt", "language": "de",
        "doc_type": "gazette_act", "iso_3166_2": "DE-NW", "admin_level": "kreis", "doc_id_prefix": "de_gt",
        "source_org": "Kreis Gütersloh", "place_name": "Kreis Gütersloh", "index_url": BASE, "items": its}
json.dump(meta, open(out, "w"), ensure_ascii=False, indent=1); print("LISTED", len(its), "issue_pages", len(issues))
