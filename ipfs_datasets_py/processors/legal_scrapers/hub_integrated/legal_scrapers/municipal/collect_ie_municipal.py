#!/usr/bin/env python3
"""Ireland local-authority bye-laws — collector.

Irish local authorities make bye-laws under Part 19 of the Local Government Act 2001 (and under the Roads, Waste, Casual Trading and
other Acts) and publish them on their own websites. There is no central register with the texts, so this collector:
  crawl  per council website: robots.txt sitemaps (recursive) + a keyword-prioritised breadth-first crawl inside the council's domain
         (robots.txt honoured, 1 request/s per host, page cap). Documents (PDF / DOCX / DOC) whose link text, file name or page names a
         bye-law -> links.jsonl; pages whose URL or title names a bye-law -> pages.jsonl (an HTML page may hold the text itself)
  fetch  downloads the candidate documents -> docs/, fetch_log.jsonl (stops below 30 GB free disk)
Usage: IE_BUILD=<dir> python collect_ie_municipal.py crawl|fetch
Council codes are the LGMA local authority codes (services.localgov.ie); Monaghan (22) answers with a Cloudflare challenge and is skipped
(no challenge solving)."""
import os, sys, re, json, html, collections, urllib.parse, concurrent.futures, shutil, time, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ie_common import Polite, BUILD
B = BUILD
MAX_PAGES = int(os.environ.get("IE_MAX_PAGES", "450"))
SKIP = {"22": "Cloudflare browser challenge (HTTP 403); not bypassed",
        "30": "Sucuri firewall JavaScript challenge (HTTP 307 \"You are being redirected\", JS required); not bypassed"}
COUNCILS = [  # (LGMA code, name, Irish name, website)
    ("5", "Carlow County Council", "Comhairle Contae Cheatharlach", "https://www.carlow.ie"),
    ("6", "Cavan County Council", "Comhairle Contae an Chabháin", "https://www.cavancoco.ie"),
    ("7", "Clare County Council", "Comhairle Contae an Chláir", "https://www.clarecoco.ie"),
    ("31", "Cork City Council", "Comhairle Cathrach Chorcaí", "https://www.corkcity.ie"),
    ("8", "Cork County Council", "Comhairle Contae Chorcaí", "https://www.corkcoco.ie"),
    ("9", "Donegal County Council", "Comhairle Contae Dhún na nGall", "https://www.donegalcoco.ie"),
    ("32", "Dublin City Council", "Comhairle Cathrach Bhaile Átha Cliath", "https://www.dublincity.ie"),
    ("10", "Dún Laoghaire-Rathdown County Council", "Comhairle Contae Dhún Laoghaire-Ráth an Dúin", "https://www.dlrcoco.ie"),
    ("11", "Fingal County Council", "Comhairle Contae Fhine Gall", "https://www.fingal.ie"),
    ("33", "Galway City Council", "Comhairle Cathrach na Gaillimhe", "https://www.galwaycity.ie"),
    ("12", "Galway County Council", "Comhairle Chontae na Gaillimhe", "https://www.galway.ie"),
    ("13", "Kerry County Council", "Comhairle Contae Chiarraí", "https://www.kerrycoco.ie"),
    ("14", "Kildare County Council", "Comhairle Contae Chill Dara", "https://www.kildarecoco.ie"),
    ("15", "Kilkenny County Council", "Comhairle Contae Chill Chainnigh", "https://www.kilkennycoco.ie"),
    ("16", "Laois County Council", "Comhairle Contae Laoise", "https://laois.ie"),
    ("17", "Leitrim County Council", "Comhairle Chontae Liatroma", "https://www.leitrimcoco.ie"),
    ("34", "Limerick City and County Council", "Comhairle Cathrach agus Contae Luimnigh", "https://www.limerick.ie"),
    ("18", "Longford County Council", "Comhairle Chontae an Longfoirt", "https://www.longfordcoco.ie"),
    ("19", "Louth County Council", "Comhairle Contae Lú", "https://www.louthcoco.ie"),
    ("20", "Mayo County Council", "Comhairle Contae Mhaigh Eo", "https://www.mayo.ie"),
    ("21", "Meath County Council", "Comhairle Chontae na Mí", "https://www.meath.ie"),
    ("22", "Monaghan County Council", "Comhairle Contae Mhuineacháin", "https://monaghan.ie"),
    ("23", "Offaly County Council", "Comhairle Chontae Uíbh Fhailí", "https://www.offaly.ie"),
    ("24", "Roscommon County Council", "Comhairle Contae Ros Comáin", "https://www.roscommoncoco.ie"),
    ("25", "Sligo County Council", "Comhairle Chontae Shligigh", "https://www.sligococo.ie"),
    ("26", "South Dublin County Council", "Comhairle Contae Átha Cliath Theas", "https://www.sdcc.ie"),
    ("27", "Tipperary County Council", "Comhairle Contae Thiobraid Árann", "https://www.tipperarycoco.ie"),
    ("35", "Waterford City and County Council", "Comhairle Cathrach agus Contae Phort Láirge", "https://waterfordcouncil.ie"),
    ("28", "Westmeath County Council", "Comhairle Chontae na hIarmhí", "https://www.westmeathcoco.ie"),
    ("29", "Wexford County Council", "Comhairle Contae Loch Garman", "https://www.wexfordcoco.ie"),
    ("30", "Wicklow County Council", "Comhairle Chontae Chill Mhantáin", "https://www.wicklow.ie"),
]

def disk_ok(): return shutil.disk_usage(os.path.dirname(os.path.abspath(B)) or ".").free / 2**30 >= 30

DOC = re.compile(r"\.(pdf|docx?)(?:$|[?#])|/media/\d+/download\b|/download/\d+|/file/\d+/download|[?&]download=|\.ashx\?", re.I)   # LocalGov Drupal: /media/1979/download?inline
DOC_TXT = re.compile(r"\.(pdf|docx?)\b|\(\s*(pdf|docx?|word)\b|\b(pdf|docx?)\s*[,(]?\s*\d+([.,]\d+)?\s*(kb|mb)\b", re.I)   # link text naming a document file
REG = re.compile(r"bye[\s_\-]*laws?|byelaws?|by[\s_\-]laws?|fodhl[ií]|fo[\s_\-]dhl[ií]", re.I)
GOOD = re.compile(r"council|governance|administration|publications?|documents?|services?|parking|casual[\s_\-]*trading|environment|waste|"
                  r"litter|roads?|traffic|beach|bathing|parks?|cemeter|burial|speed[\s_\-]*limit|horses?|dogs?|alcohol|liquor|water|"
                  r"harbou?r|pier|marina|library|leisure|your[\s_\-]*council|chomhairle|download", re.I)
BAD = re.compile(r"/news/|/events?/|/whats-on|/jobs|/careers|recruit|/gallery|/photo|video|/press|wp-json|/feed|/search|\?s=|"
                 r"\.(jpg|jpeg|png|gif|svg|webp|zip|mp4|mp3|xlsx?|pptx?|csv|ics)$|mailto:|tel:|javascript:|/user/|/login|calendar", re.I)
A_RX = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)

def text_of(h): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()
def reg_domain(netloc):
    p = netloc.lower().split(":")[0].split(".")
    return ".".join(p[-3:]) if p[-2:] in (["gov", "ie"],) else ".".join(p[-2:])

def sitemap_urls(P, base, limit=60):
    out, seen, todo = [], set(), [base + "/sitemap.xml", base + "/sitemap_index.xml", base + "/wp-sitemap.xml"]
    rb = P.get(base + "/robots.txt")
    if rb and rb[0] == 200: todo = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", rb[3]) + todo
    while todo and len(seen) < limit:
        u = todo.pop(0)
        if u in seen: continue
        seen.add(u); r = P.get(u, html_only=True)
        if not r or r[0] != 200 or "<" not in r[3][:300]: continue
        locs = [html.unescape(x) for x in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r[3])]
        if "<sitemapindex" in r[3]:
            locs.sort(key=lambda x: (bool(re.search(r"post-sitemap|news|event|notice", x)), x)); todo += locs
        else: out += locs
    return out

def crawl_council(c):
    code, name, ga, site = c
    if code in SKIP: return c, [], [], dict(skipped=SKIP[code])
    P = Polite()
    d0 = urllib.parse.urlsplit(site).netloc.lower(); bare = d0[4:] if d0.startswith("www.") else d0
    tried = []
    for cand in dict.fromkeys([site + "/", f"https://{bare}/", f"https://www.{bare}/"]):
        r0 = P.get(cand, html_only=True); tried.append(f"{cand} {r0[0] if r0 else 'robots/unreachable'}")
        if r0 and r0[0] == 200: break
    if not r0 or r0[0] != 200: return c, [], [], dict(error="home: " + "; ".join(tried))
    home = r0[1]; u0 = urllib.parse.urlsplit(home); base = f"{u0.scheme}://{u0.netloc}"; dom = reg_domain(u0.netloc)
    sm = sitemap_urls(P, base)
    def score(u, t=""):
        s = urllib.parse.unquote(u) + " " + t
        return 8 * bool(REG.search(s)) + 2 * bool(GOOD.search(s)) - 5 * bool(BAD.search(u))
    links, pages_out, seen, queue, pages = {}, {}, set(), [], 0
    def add(u, t, src, ptitle):
        fn = urllib.parse.unquote(u.split("?")[0].rsplit("/", 1)[-1])
        if REG.search(t) or REG.search(fn) or REG.search(urllib.parse.unquote(src) + " " + ptitle):
            links.setdefault(u, dict(code=code, council=name, url=u, link_text=t[:300], page=src, page_title=ptitle[:200]))
    for u in sm:
        if DOC.search(u): add(u, "", "sitemap", "")
        elif not BAD.search(u) or REG.search(urllib.parse.unquote(u)): queue.append((-score(u), u))
    queue.append((-99, home)); queue = sorted(set(queue))
    while queue and pages < MAX_PAGES:
        if not disk_ok(): break
        sc, u = queue.pop(0)
        if u in seen: continue
        if sc > -2 and pages > 150: break            # only weak candidates left after a reasonable crawl
        seen.add(u); r = P.get(u, html_only=True)
        if r and r[0] == 200 and re.search(r"pdf|msword|officedocument", r[2] or "", re.I):   # a redirect that resolves to a document
            add(r[1], urllib.parse.unquote(u.rstrip("/").rsplit("/", 1)[-1]).replace("-", " "), u, ""); continue
        if not r or r[0] != 200 or "html" not in (r[2] or "html"): continue
        pages += 1; h = r[3]; m = re.search(r"<title[^>]*>(.*?)</title>", h, re.S | re.I); ptitle = text_of(m.group(1)) if m else ""
        if REG.search(urllib.parse.unquote(r[1]) + " " + ptitle): pages_out.setdefault(r[1], dict(code=code, council=name, url=r[1], title=ptitle[:300]))
        new = []
        for href, inner in A_RX.findall(h):
            href = html.unescape(href.strip())
            if not href or href.startswith(("mailto:", "tel:", "javascript:")): continue
            v = urllib.parse.urljoin(r[1], href).split("#")[0]; nu = urllib.parse.urlsplit(v)
            if nu.scheme not in ("http", "https"): continue
            t = text_of(inner)
            if DOC.search(v) or (DOC_TXT.search(t) and not re.search(r"(?i)\.(html?|aspx?|php)$", nu.path)):
                add(v, t, r[1], ptitle); continue                          # documents may sit on another host (CDN / blob storage)
            if reg_domain(nu.netloc) != dom: continue
            if v not in seen and (not BAD.search(v) or REG.search(urllib.parse.unquote(v) + " " + t)): new.append((-score(v, t), v))
        queue = sorted(set(queue + new))
    return c, list(links.values()), list(pages_out.values()), dict(pages=pages, sitemap_urls=len(sm), doc_links=len(links), byelaw_pages=len(pages_out), base=base)

def crawl():
    out = open(f"{B}/links.jsonl", "w"); pout = open(f"{B}/pages.jsonl", "w"); stats = {}
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        for c, ls, ps, st in ex.map(crawl_council, COUNCILS):
            for l in ls: out.write(json.dumps(l, ensure_ascii=False) + "\n")
            for p in ps: pout.write(json.dumps(p, ensure_ascii=False) + "\n")
            out.flush(); pout.flush(); stats[c[0]] = dict(name=c[1], **st); print(c[1], st, flush=True)
    json.dump(stats, open(f"{B}/crawl_stats.json", "w"), ensure_ascii=False, indent=1)

MAGIC = {b"%PDF-": "pdf", b"PK\x03\x04": "docx", b"\xd0\xcf\x11\xe0": "doc"}
def fetch():
    P = Polite(); os.makedirs(f"{B}/docs", exist_ok=True)
    links = [json.loads(l) for l in open(f"{B}/links.jsonl")]
    done = {json.loads(l)["url"] for l in open(f"{B}/fetch_log.jsonl")} if os.path.exists(f"{B}/fetch_log.jsonl") else set()
    log = open(f"{B}/fetch_log.jsonl", "a")
    def one(l):
        if l["url"] in done or not disk_ok(): return None
        r = P.get(l["url"], binary=True, store_body=False)
        rec = dict(url=l["url"], code=l["code"], retrieved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        if r is None: rec.update(ok=False, error="robots.txt disallows"); return rec
        st, fu, ct, body = r
        kind = next((k for m, k in MAGIC.items() if body[:len(m)] == m), None)
        if kind == "docx" and b"word/" not in body[:4000] and b"[Content_Types].xml" not in body[:4000]: kind = None
        ok = st == 200 and kind is not None
        rec.update(ok=ok, status=st, final_url=fu, ctype=ct, bytes=len(body), kind=kind, error=None if ok else f"status {st} / {ct} / not a document")
        if ok:
            h = hashlib.sha256(body).hexdigest(); fn = f"{B}/docs/{h[:20]}.{kind}"
            if not os.path.exists(fn): open(fn, "wb").write(body)
            rec.update(sha256=h, file=os.path.basename(fn))
        return rec
    by = collections.defaultdict(list)
    for l in links: by[urllib.parse.urlsplit(l["url"]).netloc].append(l)
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        for recs in ex.map(lambda ls: [one(l) for l in ls], by.values()):
            for rec in recs:
                if rec: log.write(json.dumps(rec, ensure_ascii=False) + "\n")
            log.flush()

if __name__ == "__main__":
    {"crawl": crawl, "fetch": fetch}[sys.argv[1]]()
