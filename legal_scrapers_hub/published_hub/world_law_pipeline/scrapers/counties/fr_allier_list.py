#!/usr/bin/env python3
"""2026-11-04 county lane: list Allier FR-03 (wd:Q3113) conseil départemental acts from delib.allier.fr (public Laravel portal)
-> entries JSON for pdf_list_fetch.py.
Public, unauthenticated: GET {kind}/liste/form?year=Y (server-rendered list) then the same POST {kind}/details* call the page's own
jQuery makes when a row is expanded (CSRF token taken from the public page's <meta>, exactly as the browser does; no login, no bypass).
Kinds: arretes (arrêtés + PDF annexes), decisions, CP (Commission permanente délibérations + dossier annexes), sessions (Conseil
départemental délibérations + dossier annexes). Rapports (preparatory reports) are skipped; non-PDF/spreadsheets skipped.
PDF URLs have no query string (…/file/…/NNNNNN.pdf) -> pdf_list_fetch doc_id = platform:sha1(url)[:16].
Polite: 2 s between requests, honest UA (pdf_list_fetch.UA). Details responses cached in OUT.cache.jsonl (resume).
usage: fr_allier_list.py OUT.json [--years 2026,2025] [--max-per-kind N]"""
import json, sys, time, re, html
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).resolve().parent)); from pdf_list_fetch import UA
a = sys.argv[1:]; out = Path(a[0])
years = (a[a.index("--years") + 1] if "--years" in a else "2026,2025").split(",")
maxk = int(a[a.index("--max-per-kind") + 1]) if "--max-per-kind" in a else 10 ** 9
B = "https://delib.allier.fr"; DELAY = 2.0
KINDS = [("arretes", "detailsArrete", "arrete", "arrêté"), ("decisions", "detailsDecision", "decision", "décision"),
         ("CP", "detailsCP", "commission", "deliberation_cp"), ("sessions", "detailsSession", "session", "deliberation_cd")]
s = requests.Session(); s.headers.update({"User-Agent": UA}); s.trust_env = False
cache_p = Path(str(out) + ".cache.jsonl"); cache = {}
if cache_p.exists():
    for l in open(cache_p):
        try: d = json.loads(l); cache[d["k"]] = d["v"]
        except Exception: pass
cf = open(cache_p, "a")
def req(m, url, **kw):
    for att in range(4):
        try:
            r = s.request(m, url, timeout=(20, 90), **kw); time.sleep(DELAY)
            if r.status_code == 200: return r
            print("HTTP", r.status_code, m, url, flush=True)
            if r.status_code in (403, 404): return None
        except Exception as ex: print("ERR", m, url, ex, flush=True); time.sleep(DELAY)
        time.sleep(30 * (att + 1))
    return None
def dmy(x):
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", x or ""); return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None
items, seen, skipped = [], set(), dict(nonpdf=0, rapport=0, nolink=0, fail=0)
def add(url, title, num, adopted, pub, kind):
    if not url: skipped["nolink"] += 1; return
    url = url.replace("\\/", "/")
    if not url.lower().endswith(".pdf"): skipped["nonpdf"] += 1; return
    if url in seen: return
    seen.add(url); items.append(dict(url=url, title=re.sub(r"\s+", " ", title or "").strip()[:500], number=num, adopted_date=adopted,
                                     published_date=pub, kind=kind))
def links_in(o, ctx=None):  # (link, nearest enclosing dict carrying a libelle) pairs anywhere under o
    if isinstance(o, dict):
        if o.get("libelle") or o.get("LIBELLE"): ctx = o
        lk = o.get("link") or o.get("LINK")
        if isinstance(lk, str): yield lk, (ctx or o)
        for k, v in o.items():
            if k not in ("link", "LINK"): yield from links_in(v, ctx)
    elif isinstance(o, list):
        for v in o: yield from links_in(v, ctx)
for kind, det, key, label in KINDS:
    n_k = 0
    for y in years:
        r = req("GET", f"{B}/{kind}/liste/form", params={"year": y})
        if not r: print("list fail", kind, y, flush=True); skipped["fail"] += 1; continue
        t = r.text; tok = re.search(r'name="csrf-token" content="([^"]+)"', t).group(1)
        rows, vol = [], None   # walk volumes (recueil / réunion) and rows in document order
        for m in re.finditer(r'class="leaderboard__name">([^<]+)<|class="leaderboard__profile_second"[^>]*href="(#id_\d+)"[^>]*>.*?leaderboard__name_second">(.*?)</span>', t, re.S):
            if m.group(1): vol = html.unescape(m.group(1).strip()); continue
            rows.append((m.group(2), vol, html.unescape(re.sub(r"<[^>]+>", " ", m.group(3)))))
        print(kind, y, "rows", len(rows), flush=True)
        for rid, vol, rtitle in rows:
            if n_k >= maxk: break
            n_k += 1; ck = f"{kind}:{rid}"
            if ck in cache: d = cache[ck]
            else:
                rr = req("POST", f"{B}/{kind}/{det}", data={key: rid}, headers={"X-CSRF-TOKEN": tok, "X-Requested-With": "XMLHttpRequest",
                                                                                "Referer": f"{B}/{kind}/liste"})
                if not rr: skipped["fail"] += 1; continue
                try: d = json.loads(rr.text)
                except Exception: print("bad json", ck, rr.text[:200], flush=True); skipped["fail"] += 1; continue
                cache[ck] = d; cf.write(json.dumps(dict(k=ck, v=d), ensure_ascii=False) + "\n"); cf.flush()
            vdate = dmy(vol); rdate = dmy(rtitle)
            o = d.get(key) or {}
            if kind in ("arretes", "decisions"):
                obj = o.get("objet") or rtitle; num = (re.search(r"(?:n°\s*)?([A-Z]{2}_\d{4}_\d+\w*|\d+\s+[A-Z]{2,}\s+\d{4})", obj) or [None, None])[1] if obj else None
                add(o.get("link"), f"{label.capitalize()} — {obj}", num, rdate, vdate, label)
                for lk, ao in links_in({k: v for k, v in o.items() if k not in ("link",)}):
                    add(lk, f"{label.capitalize()} — {obj} — annexe: {ao.get('libelle') or ao.get('LIBELLE') or ''}", num, rdate, vdate, label + " (annexe)")
            else:
                obj = o.get("objet") or rtitle; sd = vdate
                if o.get("rapport"): skipped["rapport"] += 1
                for lk, do in links_in((d.get("deliberations") or o.get("deliberations") or {})):
                    num = do.get("libelle") or do.get("LIBELLE"); add(lk, f"{num} — {obj}" if num else f"Délibération — {obj}", num, sd, None, label)
                for lk, ao in links_in(o.get("annexes") or {}):
                    add(lk, f"{obj} — annexe: {ao.get('libelle') or ao.get('LIBELLE') or ''}", None, sd, None, label + " (annexe)")
    print(kind, "done, items so far", len(items), flush=True)
out.parent.mkdir(parents=True, exist_ok=True)
json.dump(dict(place_id="wd:Q3113", qid="Q3113", country_code="FR", source_platform="fr_raa_conseil_departemental",
               source_org="Conseil départemental — Allier", language="fr", doc_type="gazette_act", place_name="Allier",
               iso_3166_2="FR-03", admin_level="department", index_url=B + "/", items=items), open(out, "w"), ensure_ascii=False)
print("items", len(items), "skipped", skipped, "->", out, flush=True)
