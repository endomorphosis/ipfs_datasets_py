#!/usr/bin/env python3
"""Switzerland municipal law collector (polite live fetches, no OCR).

Sources
  1. LexFind.ch (lexfind.ch, Swiss federal/cantonal law index) - category 9 "Gemeindeerlass"
     via its public frontend JSON API; text from the linked official PDF (pdftotext).
  2. Stadtrecht Bern (stadtrecht.bern.ch, Systematische Sammlung des Stadtrechts, BFS 351) -
     acts listed in sitemap.xml (lex-*), text from the official PDF export (<url>.pdf).
Fedlex is NOT ingested (federal law is national, not municipal); it is only context.

Usage: python3 collect_ch_municipal.py OUTDIR [--limit N]
Writes OUTDIR/raw/{laws,articles}.jsonl ; build_ch_municipal.py turns them into parquet shards.
"""
import json, os, re, subprocess, sys, tempfile, time, hashlib, datetime
import requests

UA = {"User-Agent": "world-laws-municipal-collector/0.1 (research; polite; contact via endomorphosis)"}
S = requests.Session(); S.headers.update(UA)
DELAY = float(os.environ.get("CH_DELAY", "1.0"))
LF = "https://www.lexfind.ch/api/fe/de"
# BFS municipality numbers (Bundesamt fuer Statistik)
BFS = {"Bern": "351", "Riehen": "2703", "Bettingen": "2702", "Basel": "2701"}

def now(): return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def get(url, **kw):
    for i in range(4):
        try:
            r = S.get(url, timeout=60, **kw)
            if r.status_code == 200: time.sleep(DELAY); return r
            if r.status_code in (404, 410): return None
        except requests.RequestException: pass
        time.sleep(3 * (i + 1))
    return None

def pdf_text(content):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(content); f.flush()
        p = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", f.name, "-"], capture_output=True, timeout=120)
    t = p.stdout.decode("utf-8", "ignore")
    t = re.sub(r"[ \t]+", " ", t); t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

ART = re.compile(r"(?m)^\s*(Art\.|Artikel|§)\s*(\d+[a-z]?(?:bis|ter|quater)?)\b[^\n]*")
def split_articles(text):
    ms = list(ART.finditer(text)); out = []; seen = set()
    for i, m in enumerate(ms):
        n = m.group(2)
        if n in seen: continue          # skip TOC/duplicate refs, keep first full block
        body = text[m.start(): ms[i + 1].start() if i + 1 < len(ms) else len(text)].strip()
        if len(body) < 20: continue
        seen.add(n); out.append((n, m.group(0).strip()[:300], body))
    return out

# ---------- LexFind ----------
def lexfind_tols():
    ents = [e["id"] for e in S.get(f"{LF}/entities", timeout=60).json()]
    tols = {}
    for q in "aeiou":
        d = S.post(f"{LF}/fulltext-search", json={"search_text": q, "active_only": True, "search_in_systematic_number": False,
              "search_in_title": True, "search_in_keywords": True, "search_in_content": False, "entity_filter": ents,
              "systematic_filter": [], "category_filter": [9], "use_global_systematics": True, "direct_search": False}, timeout=60).json()
        page = 1
        while True:
            r = S.get(f"{LF}/fulltext-search/{d['id']}", params={"session_id": d["session_id"], "page_no": str(page), "results_per_page": "50"}, timeout=60).json()
            for t in r.get("texts_of_law_with_matches", []): tols[t["id"]] = t
            if page >= r.get("number_of_pages", 1): break
            page += 1; time.sleep(DELAY)
    return list(tols.values())

PREFIX = {"RiE": "Riehen", "BeE": "Bettingen", "BaB": "Basel"}   # LexFind BS prefixes (BaB = Buergergemeinde Basel)
def muni_from(title, kw, entity, sysnum=""):
    pre = sysnum.split(" ")[0]
    if pre in PREFIX: return PREFIX[pre], BFS[PREFIX[pre]]
    s = f"{title} {kw}"
    for name in ("Bettingen", "Riehen", "Bern", "Basel"):
        if re.search(rf"\b{name}\b", s): return name, BFS[name]
    return None, None

def collect_lexfind(limit):
    for t in lexfind_tols()[:limit]:
        m = t["matches"][0]; ent = t["entity"]
        url = next((u.get("original_url") or "https://www.lexfind.ch" + u["url"] for u in t["dta_urls"] if u["language"] == "de"), None)
        name, code = muni_from(m.get("title", ""), m.get("keywords") or "", ent, t["systematic_number"])
        if not code:
            print("skip (no municipality):", t["systematic_number"], m.get("title"), file=sys.stderr); continue
        r = get("https://www.lexfind.ch" + next(u["url"] for u in t["dta_urls"] if u["language"] == "de"))
        if not r or not r.content.startswith(b"%PDF"): continue
        yield dict(native_id=t["systematic_number"], title=m["title"], text=pdf_text(r.content), source_url=url,
                   municipality=name, municipality_code=code, admin1="CH-" + ent["abbreviation"], language="de",
                   date=m.get("version_active_since"), source_body=("Bürgergemeinde Basel" if t["systematic_number"].startswith("BaB") else f"Gemeinde {name}"),
                   extras={"lexfind_tol_id": t["id"], "lexfind_version_id": m["id"], "lexfind_url": f"https://www.lexfind.ch/fe/de/tol/{t['id']}/de",
                           "category": "Gemeindeerlass", "family_active_since": m.get("family_active_since"), "source": "lexfind"})

# ---------- Stadtrecht Bern ----------
def collect_bern(limit):
    sm = get("https://stadtrecht.bern.ch/sitemap.xml").text
    locs = sorted(set(re.findall(r"<loc>(https://stadtrecht\.bern\.ch/lex-[^<]+)</loc>", sm)))
    for loc in locs[:limit]:
        r = get(loc + ".pdf")
        if not r or not r.content.startswith(b"%PDF"): continue
        text = pdf_text(r.content)
        num = loc.rsplit("lex-", 1)[1].replace("_", ".")
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        # title: lines after the first date line up to the "Der Stadtrat/Gemeinderat..." preamble
        tl = []
        for l in lines[1:15]:
            if re.match(r"^\d{1,2}\. \w+ \d{4}", l) or l == num: continue
            if re.match(r"^(Der|Die|Das) (Stadtrat|Gemeinderat|Gemeinde|stimmberechtigten|Stimmberechtigten)", l, re.I) or l.startswith("Art."): break
            tl.append(l)
        dm = re.search(r"(\d{1,2}\. \w+ \d{4})", "\n".join(lines[:4]))
        yield dict(native_id=num, title=" ".join(tl)[:500] or f"Stadtrecht Bern {num}", text=text, source_url=loc,
                   municipality="Bern", municipality_code=BFS["Bern"], admin1="CH-BE", language="de",
                   date=dm.group(1) if dm else None, source_body="Stadt Bern",
                   extras={"sssb_number": num, "pdf_url": loc + ".pdf", "source": "stadtrecht.bern.ch"})

def main():
    out = sys.argv[1]; limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10**9
    os.makedirs(f"{out}/raw", exist_ok=True)
    with open(f"{out}/raw/docs.jsonl", "w") as f:
        n = 0
        for gen in (collect_lexfind(limit), collect_bern(limit)):
            for d in gen:
                d["retrieved_at"] = now(); f.write(json.dumps(d, ensure_ascii=False) + "\n"); n += 1
                if n % 25 == 0: print("docs", n, flush=True)
    print("done", n)

if __name__ == "__main__": main()
