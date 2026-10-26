#!/usr/bin/env python3
"""Luxembourg communal regulations (règlements communaux) — collector.

Legilux (the Journal officiel) publishes for communal regulations only a publication NOTICE ('En séance du … le conseil communal de X a
… Ladite délibération a été publiée en due forme'), never the regulation text. The texts are published by the communes on their own
websites. This collector therefore:
  crawl    per commune website: sitemaps + keyword-prioritised breadth-first crawl inside the commune's domain (robots.txt honoured,
           1 req/s per host, page cap), collecting links to documents whose link text or file name names a regulation -> links.jsonl
  fetch    downloads the candidate documents (PDF) -> docs/, fetch_log.jsonl
  legilux  Legilux SPARQL (data.legilux.public.lu/sparqlendpoint): every act of type RC (règlement communal) / RTC with title, dates,
           ELI -> legilux_rc.jsonl (used by the build for provenance and adoption dates)
Usage: LU_BUILD=<dir> python collect_lu_communes.py communes|legilux|crawl|fetch      (communes.json in <dir>: name, lau, qid, pop, canton, sites)"""
import os, sys, re, json, html, collections, urllib.parse, concurrent.futures, shutil, time, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lu_common import Polite, BUILD
B = BUILD
MAX_PAGES = int(os.environ.get("LU_MAX_PAGES", "350")); TOP = int(os.environ.get("LU_TOP", "30"))

def disk_ok(): return shutil.disk_usage(os.path.dirname(os.path.abspath(B)) or ".").free / 2**30 >= 30

DOC = re.compile(r"\.pdf(?:$|[?#])", re.I)
REG = re.compile(r"r[eèé]glement|reglement|verordnung|statuts?\b|police|taxe|bâtisses|batisses|ordre\s+int[ée]rieur|r\.?o\.?i\b", re.I)
GOOD = re.compile(r"r[eèé]glement|reglement|verordnung|conseil.?communal|gemengerot|gemeinderat|publication|document|t[ée]l[ée]charg|download|"
                  r"l[ée]gislation|r[ée]glementation|administration|mairie|commune|vie.?politique|politique|services?", re.I)
BAD = re.compile(r"actualit|news|agenda|event|[ée]v[ée]nement|galer|photo|video|presse|jobs?|emploi|offre|kalenner|wp-json|/feed|\.(jpg|jpeg|png|gif|svg|zip|mp4|mp3|docx?|xlsx?)$|"
                 r"mailto:|tel:|javascript:|#", re.I)
A_RX = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)

def text_of(h): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()
def reg_domain(netloc):
    p = netloc.lower().split(":")[0].split("."); return ".".join(p[-2:])

def sitemap_urls(P, base, limit=40):
    out, seen, todo = [], set(), [base + "/sitemap_index.xml", base + "/wp-sitemap.xml", base + "/sitemap.xml"]
    rb = P.get(base + "/robots.txt")
    if rb and rb[0] == 200: todo = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", rb[3]) + todo
    while todo and len(seen) < limit:
        u = todo.pop(0)
        if u in seen: continue
        seen.add(u); r = P.get(u, html_only=True)
        if not r or r[0] != 200 or "<" not in r[3][:200]: continue
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r[3])
        if "<sitemapindex" in r[3]:
            # sub-sitemaps: pages/files first, posts last
            locs.sort(key=lambda x: (bool(re.search(r"post-sitemap|news|actualit|event", x)), x)); todo += locs
        else: out += [html.unescape(x) for x in locs]
    return out

def crawl_commune(c):
    P = Polite(); site = (c["sites"] or [None])[0]
    if not site: return c, [], dict(error="no website")
    # the Wikidata URL can be stale ('http://www.esch.lu' times out, 'https://esch.lu' answers): try https with and without www
    d0 = urllib.parse.urlsplit(site).netloc.lower(); bare = d0[4:] if d0.startswith("www.") else d0
    tried = []
    for cand in dict.fromkeys([site, f"https://{bare}/", f"https://www.{bare}/"]):
        r0 = P.get(cand, html_only=True); tried.append(f"{cand} {r0[0] if r0 else 'robots/unreachable'}")
        if r0 and r0[0] == 200: break
    if not r0 or r0[0] != 200: return c, [], dict(error="home: " + "; ".join(tried))
    home = r0[1]; u0 = urllib.parse.urlsplit(home); base = f"{u0.scheme}://{u0.netloc}"; dom = reg_domain(u0.netloc)
    sm = sitemap_urls(P, base)
    score = lambda u, t="": 6 * bool(REG.search(urllib.parse.unquote(u) + " " + t)) + 2 * bool(GOOD.search(urllib.parse.unquote(u) + " " + t)) - 4 * bool(BAD.search(u))
    links, seen, queue, pages = {}, set(), [], 0
    def add(u, t, src, ptitle):
        # a document whose link text or file name names a regulation, or any document on a page that is about a regulation
        if DOC.search(u) and (REG.search(t) or REG.search(urllib.parse.unquote(u.rsplit("/", 1)[-1])) or REG.search(urllib.parse.unquote(src) + " " + ptitle)):
            links.setdefault(u, dict(commune=c["name"], lau=c["lau"], url=u, link_text=t[:300], page=src, page_title=ptitle[:200]))
    for u in sm:
        if DOC.search(u): add(u, "", "sitemap", "")
        elif re.search(r"[?&]attachment_id=|/attachment/", u) and REG.search(urllib.parse.unquote(u)): queue.append((-10, u))
        elif u not in seen and not BAD.search(u): queue.append((-score(u), u))
    queue.append((-99, home)); queue.sort()
    while queue and pages < MAX_PAGES:
        if not disk_ok(): break
        _, u = queue.pop(0)
        if u in seen: continue
        seen.add(u); r = P.get(u, html_only=True)
        if r and r[0] == 200 and "pdf" in (r[2] or "").lower():   # an attachment page / redirect that resolves to a PDF is a document
            add(r[1] if DOC.search(r[1]) else r[1] + "#.pdf", urllib.parse.unquote(u.rstrip("/").rsplit("/", 1)[-1]).replace("-", " "), u, ""); continue
        if not r or r[0] != 200 or "html" not in (r[2] or "html"): continue
        pages += 1; h = r[3]; m = re.search(r"<title[^>]*>(.*?)</title>", h, re.S | re.I); ptitle = text_of(m.group(1)) if m else ""
        new = []
        for href, inner in A_RX.findall(h):
            href = html.unescape(href.strip())
            if not href or href.startswith(("mailto:", "tel:", "javascript:")): continue
            v = urllib.parse.urljoin(r[1], href).split("#")[0]
            nu = urllib.parse.urlsplit(v)
            if nu.scheme not in ("http", "https"): continue
            t = text_of(inner)
            if DOC.search(v): add(v, t, r[1], ptitle); continue   # documents may sit on another host (Dudelange: Azure blob storage)
            if reg_domain(nu.netloc) != dom: continue          # pages are crawled only inside the commune's domain
            if v not in seen and not BAD.search(v): new.append((-score(v, t), v))
        queue = sorted(set(queue + new))
    return c, list(links.values()), dict(pages=pages, sitemap_urls=len(sm), doc_links=len(links), base=base)

def crawl():
    cs = json.load(open(f"{B}/communes.json"))[:TOP]
    out = open(f"{B}/links.jsonl", "w"); stats = {}
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        for c, ls, st in ex.map(crawl_commune, cs):
            for l in ls: out.write(json.dumps(l, ensure_ascii=False) + "\n")
            out.flush(); stats[c["lau"]] = dict(name=c["name"], **st); print(c["name"], st, flush=True)
    json.dump(stats, open(f"{B}/crawl_stats.json", "w"), ensure_ascii=False, indent=1)

def fetch():
    P = Polite(); os.makedirs(f"{B}/docs", exist_ok=True)
    links = [json.loads(l) for l in open(f"{B}/links.jsonl")]
    done = {json.loads(l)["url"] for l in open(f"{B}/fetch_log.jsonl")} if os.path.exists(f"{B}/fetch_log.jsonl") else set()
    log = open(f"{B}/fetch_log.jsonl", "a")
    def one(l):
        if l["url"] in done or not disk_ok(): return None
        r = P.get(l["url"], binary=True, store_body=False)
        rec = dict(url=l["url"], lau=l["lau"], retrieved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        if r is None: rec.update(ok=False, error="robots.txt disallows")
        else:
            st, fu, ct, body = r
            ok = st == 200 and body[:5] == b"%PDF-"
            rec.update(ok=ok, status=st, final_url=fu, ctype=ct, bytes=len(body), error=None if ok else f"status {st} / {ct} / not a PDF")
            if ok:
                h = hashlib.sha256(body).hexdigest(); fn = f"{B}/docs/{h[:20]}.pdf"
                if not os.path.exists(fn): open(fn, "wb").write(body)
                rec.update(sha256=h, file=os.path.basename(fn))
        return rec
    by = collections.defaultdict(list)
    for l in links: by[urllib.parse.urlsplit(l["url"]).netloc].append(l)
    def host_run(ls): return [one(l) for l in ls]
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        for recs in ex.map(host_run, by.values()):
            for rec in recs:
                if rec: log.write(json.dumps(rec, ensure_ascii=False) + "\n")
            log.flush()

WIKIDATA = "https://query.wikidata.org/sparql"
def communes():
    """communes.json: the 100 communes of Luxembourg from Wikidata (instance of 'commune of Luxembourg' Q2919801, not dissolved), with
    the LAU code (P782, without the 'LU' prefix), latest population (P1082), canton (P131), official websites (P856); sorted by population"""
    import requests
    q = """SELECT ?c ?cLabel ?lau ?pop ?popdate ?cantonLabel ?site WHERE {
      ?c wdt:P31 wd:Q2919801 . FILTER NOT EXISTS { ?c wdt:P576 ?end }
      OPTIONAL { ?c wdt:P782 ?lau } OPTIONAL { ?c p:P1082 ?ps . ?ps ps:P1082 ?pop . OPTIONAL { ?ps pq:P585 ?popdate } }
      OPTIONAL { ?c wdt:P131 ?canton . ?canton wdt:P31 wd:Q1146429 } OPTIONAL { ?c wdt:P856 ?site }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "fr,lb,de,en". } }"""
    r = requests.get(WIKIDATA, params=dict(query=q, format="json"), timeout=120,
                     headers={"User-Agent": "legal-corpora-research/0.1 (municipal regulations corpus)"})
    r.raise_for_status(); by = {}
    for b in r.json()["results"]["bindings"]:
        g = lambda k: b.get(k, {}).get("value")
        qid = g("c").rsplit("/", 1)[-1]; c = by.setdefault(qid, dict(name=g("cLabel"), lau=None, qid=qid, pop=None, canton=None, sites=[], _pd=""))
        if g("lau"): c["lau"] = re.sub(r"^LU", "", g("lau"))
        if g("pop") and (g("popdate") or "") >= c["_pd"]: c["pop"], c["_pd"] = int(float(g("pop"))), g("popdate") or ""
        if g("cantonLabel"): c["canton"] = g("cantonLabel")
        if g("site") and g("site") not in c["sites"]: c["sites"].append(g("site"))
    out = sorted((dict((k, v) for k, v in c.items() if k != "_pd") for c in by.values() if c["lau"]), key=lambda c: -(c["pop"] or 0))
    os.makedirs(B, exist_ok=True); json.dump(out, open(f"{B}/communes.json", "w"), ensure_ascii=False, indent=1); print(len(out), "communes")

SPARQL = "https://data.legilux.public.lu/sparqlendpoint"
def legilux():
    """All RC / RTC acts, one query per type and ELI year ('/rc/<year>/'), so no query needs a deep OFFSET (the endpoint answers
    HTTP 500 beyond OFFSET 10000). Rows are ordered inside the year and paged by PAGE."""
    import requests
    s = requests.Session(); s.headers["User-Agent"] = "Mozilla/5.0 (compatible; legal-corpora-research/0.1)"
    PAGE = 5000; y1 = int(time.strftime("%Y")) + 1
    out = open(f"{B}/legilux_rc.jsonl.part", "w"); n = 0; per = {}
    def run(q):
        for k in range(4):
            try:
                r = s.get(SPARQL, params={"query": q}, headers={"Accept": "application/sparql-results+json"}, timeout=180)
                r.raise_for_status(); return r.json()["results"]["bindings"]
            except Exception as e:
                err = e; time.sleep(5 * (k + 1))
        raise err
    for typ in ("RC", "RTC"):
        for y in range(1830, y1):
            off = 0
            while True:
                q = f"""PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
SELECT ?act ?e ?t ?dd ?pd ?ef ?st WHERE {{ ?act jolux:typeDocument <http://data.legilux.public.lu/resource/authority/resource-type/{typ}> .
 FILTER(CONTAINS(STR(?act), "/{typ.lower()}/{y}/")) ?act jolux:isRealizedBy ?e . ?e jolux:title ?t .
 OPTIONAL {{ ?act jolux:dateDocument ?dd }} OPTIONAL {{ ?act jolux:publicationDate ?pd }} OPTIONAL {{ ?act jolux:dateEntryInForce ?ef }}
 OPTIONAL {{ ?act jolux:inForceStatus ?st }} }} ORDER BY ?act ?e LIMIT {PAGE} OFFSET {off}"""
                bs = run(q); time.sleep(1)
                for b in bs:
                    g = lambda k: b[k]["value"] if k in b else None
                    out.write(json.dumps(dict(type=typ, eli=g("act"), expression=g("e"), title=g("t"), date_document=g("dd"), publication_date=g("pd"),
                                              entry_into_force=g("ef"), status=(g("st") or "").rsplit("/", 1)[-1] or None), ensure_ascii=False) + "\n"); n += 1
                per[f"{typ}/{y}"] = per.get(f"{typ}/{y}", 0) + len(bs)
                if len(bs) < PAGE: break
                off += PAGE
            if per.get(f"{typ}/{y}"): print(typ, y, per[f"{typ}/{y}"], flush=True)
    out.close(); os.replace(f"{B}/legilux_rc.jsonl.part", f"{B}/legilux_rc.jsonl")
    json.dump(per, open(f"{B}/legilux_counts.json", "w"), indent=0)
    print("legilux rows", n)

if __name__ == "__main__":
    {"communes": communes, "crawl": crawl, "fetch": fetch, "legilux": legilux}[sys.argv[1]]()
