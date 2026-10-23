#!/usr/bin/env python3
"""Finland municipal rules collector (polite live fetches + Common Crawl index pointers; no OCR).

For each municipality (Statistics Finland code):
  1. page URLs from the city's sitemaps (robots.txt Sitemap: lines + common defaults), filtered by a rule-keyword regex
     (hallintosääntö, johtosääntö, järjestyssääntö, säännöt, taksa, maksut, määräykset, rakennusjärjestys ...);
  2. fetch those pages (capped) and harvest linked PDFs whose URL / link text matches the keywords;
  3. add Common Crawl PDF pointers from fi_pointers.py output (optional --cc file);
  4. download PDFs (size-capped), pdftotext; scanned PDFs without a text layer are skipped (no OCR).
Drafts (ehdotus/luonnos), minutes of other bodies, student/association rules are filtered out.
Usage: python3 collect_fi_municipal.py OUTDIR [--cc /tmp/fi_ptrs.json] [--limit-per-muni N]
"""
import gzip, hashlib, html, json, os, re, subprocess, sys, tempfile, time, datetime
from urllib.parse import urljoin, urlparse, unquote
from urllib import robotparser
import requests

UA = "world-laws-municipal-collector/0.1 (research; polite)"
S = requests.Session(); S.headers.update({"User-Agent": UA})
DELAY = float(os.environ.get("FI_DELAY", "1.0"))
MAX_PDF = 15 * 2**20
MUNIS = {  # code: (name, primary host, extra allowed hosts)
 "091": ("Helsinki", "www.hel.fi", ["paatokset.hel.fi"]), "049": ("Espoo", "www.espoo.fi", []),
 "837": ("Tampere", "www.tampere.fi", []), "092": ("Vantaa", "www.vantaa.fi", ["vantaa.fi", "varia.vantaa.fi"]),
 "564": ("Oulu", "www.ouka.fi", []), "853": ("Turku", "www.turku.fi", []), "179": ("Jyväskylä", "www.jyvaskyla.fi", []),
 "297": ("Kuopio", "www.kuopio.fi", []), "398": ("Lahti", "www.lahti.fi", []), "609": ("Pori", "www.pori.fi", []),
 "286": ("Kouvola", "www.kouvola.fi", []), "167": ("Joensuu", "www.joensuu.fi", []),
 "405": ("Lappeenranta", "lappeenranta.fi", ["www.lappeenranta.fi"]), "109": ("Hämeenlinna", "www.hameenlinna.fi", []),
 "905": ("Vaasa", "www.vaasa.fi", []), "743": ("Seinäjoki", "www.seinajoki.fi", []), "698": ("Rovaniemi", "www.rovaniemi.fi", []),
 "491": ("Mikkeli", "mikkeli.fi", ["www.mikkeli.fi"]), "285": ("Kotka", "www.kotka.fi", []), "734": ("Salo", "salo.fi", ["www.salo.fi"]),
}
A = r"(?:a|ä|%c3%a4|%C3%A4)"; O = r"(?:o|ö|%c3%b6|%C3%B6)"
KW = re.compile(rf"(?i)(hallintos{A}{A}nt|johtos{A}{A}nt|j{A}rjestyss{A}{A}nt|toimintas{A}{A}nt|taloussaant|taloussääntö|s{A}{A}nn{O}t|s{A}{A}nt{O}|taksa|maksut|palvelumaksu|m{A}{A}r{A}ykset|rakennusj{A}rjestys|ymp{A}rist{O}nsuojelum|j{A}tehuoltom|ohjes{A}{A}nt|hallintosaanto|jarjestyssaanto)")
BAD = re.compile(r"(?i)(ehdotus|luonnos|pelis|opiskelij|oppilaan|kayttosaann|käyttösäänn|ry-n|kilpailu|palkinno|arvonta|blog\.|/en/|_en\b|EN_|/ru/|nuorisovaltuust|kes(a|ä)ty(o|ö)setel|hakemus|liite-1-|ptk)")

def now(): return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
_rp = {}
def allowed(url):
    h = urlparse(url).netloc
    if h not in _rp:
        rp = robotparser.RobotFileParser()
        try:
            r = S.get(f"https://{h}/robots.txt", timeout=20); rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except Exception: rp.parse([])
        _rp[h] = rp
    return _rp[h].can_fetch(UA, url)
def get(url, stream=False):
    if not allowed(url): return None
    for i in range(3):
        try:
            r = S.get(url, timeout=60, stream=stream)
            time.sleep(DELAY)
            if r.status_code == 200: return r
            if r.status_code in (403, 404, 410): return None
        except requests.RequestException: time.sleep(3 * (i + 1))
    return None

def sitemap_urls(host, cap=30000):
    seeds = []
    try:
        r = S.get(f"https://{host}/robots.txt", timeout=20)
        seeds = re.findall(r"(?im)^sitemap:\s*(\S+)", r.text) if r.status_code == 200 else []
    except Exception: pass
    seeds = [s for s in seeds if urlparse(s).netloc.replace("www.", "") == host.replace("www.", "")] or \
            [f"https://{host}/sitemap.xml", f"https://{host}/sitemap_index.xml", f"https://{host}/wp-sitemap.xml"]
    todo, seen, pages = list(seeds), set(), []
    while todo and len(pages) < cap and len(seen) < 300:
        sm = todo.pop(0)
        if sm in seen: continue
        seen.add(sm); r = get(sm)
        if not r: continue
        body = r.content
        if sm.endswith(".gz"):
            try: body = gzip.decompress(body)
            except Exception: pass
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body.decode("utf-8", "ignore"))
        for l in locs:
            l = html.unescape(l)
            (todo if re.search(r"sitemap[^/]*\.xml", l) else pages).append(l)
    return pages

def pdf_text(content):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(content); f.flush()
        p = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", f.name, "-"], capture_output=True, timeout=180)
    t = p.stdout.decode("utf-8", "ignore").replace("\f", "\n")
    t = re.sub(r"[ \t]+", " ", t); t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

def doc_type(s):
    s = unquote(s).lower()
    for k, v in [("hallintos", "hallintosääntö"), ("johtos", "johtosääntö"), ("järjestyssää", "järjestyssääntö"), ("jarjestyssaa", "järjestyssääntö"),
                 ("rakennusj", "rakennusjärjestys"), ("ympäristönsuojelum", "ympäristönsuojelumääräykset"), ("ymparistonsuojelum", "ympäristönsuojelumääräykset"),
                 ("jätehuoltom", "jätehuoltomääräykset"), ("jatehuoltom", "jätehuoltomääräykset"), ("taksa", "taksa"), ("maksu", "maksut"),
                 ("taloussää", "taloussääntö"), ("taloussaa", "taloussääntö"), ("toimintasää", "toimintasääntö"), ("toimintasaa", "toimintasääntö")]:
        if k in s: return v
    return "sääntö/määräys"

def lang_of(t):
    w = re.findall(r"\w+", t.lower()[:20000]); n = max(1, len(w))
    sv = sum(x in ("och", "för", "att", "som", "med") for x in w) / n
    fi = sum(x in ("ja", "tai", "sekä", "on", "kaupungin", "kunnan") for x in w) / n
    return "sv" if sv > fi else "fi"

def main():
    out = sys.argv[1]; os.makedirs(f"{out}/raw", exist_ok=True)
    cc = json.load(open(sys.argv[sys.argv.index("--cc") + 1])) if "--cc" in sys.argv else {}
    lim = int(sys.argv[sys.argv.index("--limit-per-muni") + 1]) if "--limit-per-muni" in sys.argv else 80
    only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
    fo = open(f"{out}/raw/docs_fi.jsonl", "a"); stats = {}
    for code, (name, host, extra) in MUNIS.items():
        if only and code not in only: continue
        hosts = {host, host.replace("www.", ""), "www." + host.replace("www.", ""), *extra}
        cand = {}  # pdf url -> link text
        pages = [u for u in sitemap_urls(host) if KW.search(unquote(u)) and not BAD.search(u)]
        for u in pages:
            if u.lower().endswith(".pdf"): cand.setdefault(u, ""); continue
        for u in [p for p in pages if not p.lower().endswith(".pdf")][:40]:
            r = get(u)
            if not r or "html" not in r.headers.get("content-type", ""): continue
            for href, txt in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, flags=re.S):
                href = urljoin(u, html.unescape(href)); txt = re.sub(r"<[^>]+>", " ", txt); txt = " ".join(html.unescape(txt).split())
                if urlparse(href).netloc not in hosts: continue
                if not re.search(r"(?i)\.pdf($|\?)|/documents/|/tiedostot/", href): continue
                if (KW.search(unquote(href)) or KW.search(txt)) and not BAD.search(href + " " + txt):
                    cand.setdefault(href, txt)
        for x in (cc.get(code, {}).get("pointers", [])):
            u = x["url"]
            if urlparse(u).netloc in hosts and "paatokset.hel.fi" not in u and not BAD.search(u): cand.setdefault(u, "")
        prio = lambda kv: (0 if re.search(r"(?i)hallintos|johtos|j(a|ä|%c3%a4)rjestyss|rakennusj|taloussa|ymp(a|ä|%c3%a4)rist(o|ö|%c3%b6)nsuojelum|j(a|ä|%c3%a4)tehuoltom", unquote(kv[0]) + kv[1]) else 1)
        n = 0; hashes = set(); stem5 = name.lower()[:5]
        for u, txt in sorted(cand.items(), key=prio):
            if n >= lim: break
            r = get(u, stream=True)
            if not r: continue
            if int(r.headers.get("content-length") or 0) > MAX_PDF: continue
            body = r.raw.read(MAX_PDF + 1, decode_content=True)
            if len(body) > MAX_PDF or not body.startswith(b"%PDF"): continue
            t = pdf_text(body).replace("\xad", "")
            txt = txt.replace("\xad", "")
            other = re.findall(r"(?i)\b([a-zåäö]+?)n (?:kaupungin|kunnan)\b", unquote(u) .replace("-", " ") + " " + txt + " " + t[:300])
            if other and not any(o.lower().startswith(stem5[:4]) for o in other):
                continue                                            # document of another municipality
            if len(re.sub(r"\s", "", t)) < 300: continue          # scanned / empty -> no OCR
            h = hashlib.sha256(t.encode()).hexdigest()
            if h in hashes: continue
            hashes.add(h)
            fn = unquote(urlparse(u).path.rstrip("/").rsplit("/", 1)[-1])
            if re.fullmatch(r"[0-9a-f-]{20,}", fn): fn = unquote(urlparse(u).path.rstrip("/").rsplit("/", 2)[-2])
            stem = re.sub(r"\.pdf$", "", fn, flags=re.I)
            lines = [l.strip() for l in t.splitlines() if len(l.strip()) > 3][:12]
            title = txt if len(txt) > 8 else next((l for l in lines if KW.search(l) or re.search(r"(?i)sääntö|taksa|määräy|järjestys", l)), lines[0] if lines else stem)
            fo.write(json.dumps(dict(native_id=stem, title=title[:400], text=t, source_url=u, municipality=name, municipality_code=code,
                admin1=None, language=lang_of(t), date=None, source_body=f"{name} (kaupunki)", retrieved_at=now(),
                extras={"doc_type": doc_type(u + " " + title), "link_text": txt or None, "via": "sitemap/page" if u not in [p["url"] for p in cc.get(code, {}).get("pointers", [])] else "commoncrawl-index+live",
                        "source": host}), ensure_ascii=False) + "\n"); fo.flush(); n += 1
        stats[name] = {"pages": len(pages), "candidates": len(cand), "docs": n}
        print(code, name, stats[name], flush=True)
    json.dump(stats, open(f"{out}/raw/fi_stats.json", "w"), ensure_ascii=False, indent=1)



# ---------- HTML rule pages (e.g. Espoo säännökokoelma publishes rule texts inline) ----------
def main_text(page_html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(page_html, "html.parser")
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "form"]): t.decompose()
    node = soup.find("main") or soup.find("article") or soup.body or soup
    lines = [" ".join(l.split()) for l in node.get_text("\n").splitlines()]
    t = "\n".join(l for l in lines if l)
    title = (soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else "")
    return title, t

def html_pass(out, only=None, max_pages=200):
    fo = open(f"{out}/raw/docs_fi_html.jsonl", "a")
    for code, (name, host, extra) in MUNIS.items():
        if only and code not in only: continue
        pages = [u for u in sitemap_urls(host) if KW.search(unquote(u)) and not BAD.search(u) and not u.lower().endswith(".pdf")]
        n = 0
        for u in pages[:max_pages]:
            r = get(u)
            if not r or "html" not in r.headers.get("content-type", ""): continue
            title, t = main_text(r.text)
            if len(re.findall(r"(?m)^\d{1,3} ?[a-z]? ?§", t)) < 3 or len(t) < 1500: continue
            slug = urlparse(u).path.rstrip("/").rsplit("/", 1)[-1]
            fo.write(json.dumps(dict(native_id=slug, title=title or slug, text=t, source_url=u, municipality=name, municipality_code=code,
                admin1=None, language=lang_of(t), date=None, source_body=f"{name} (kaupunki)", retrieved_at=now(),
                extras={"doc_type": doc_type(u + " " + title), "via": "sitemap/html-page", "source": host}), ensure_ascii=False) + "\n"); fo.flush(); n += 1
        print("html", code, name, len(pages), n, flush=True)

if __name__ == "__main__":
    if "--html-pass" in sys.argv:
        html_pass(sys.argv[1], sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None)
    else:
        main()
