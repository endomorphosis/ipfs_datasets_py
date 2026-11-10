#!/usr/bin/env python3
"""2026-11-02 county lane: list a conseil départemental's acts from a Digitech 'Arcade' public portal (successor of Webdelib+/PubliActes,
e.g. actes.haute-garonne.fr/arcade) -> entries JSON for pdf_list_fetch.py.
Uses the portal's own public, unauthenticated JSON API (the same calls the public SPA makes; no login, no bypass):
  GET {base}/public/api/entities/search/findBySpecification?viewName=search&filter=entityType.code = ACTE|DELIB&page=N&size=100
  PDF = GET {base}/arcade/api/entities/content/{contentId}   (no query string -> pdf_list_fetch doc_id = platform:sha1(url)[:16])
ACTE folders: ACTE_FILE (the act) + ACTE_ANNEXE children (PDF annexes as separate items; spreadsheets/non-PDF skipped).
DELIB documents: the délibération PDF itself. Polite: 2 s between API pages, honest UA (pdf_list_fetch.UA), robots.txt not consulted
(owner decision 2026-11-01; actes.haute-garonne.fr/robots.txt is 404 anyway).
usage: fr_arcade_list.py BASE QID NAME OUT.json [--since YYYY] [--max-pages N]"""
import json, sys, time, re
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).resolve().parent)); from pdf_list_fetch import UA
a = sys.argv[1:]; base, qid, name, out = a[0].rstrip("/"), a[1], a[2], Path(a[3])
since = int(a[a.index("--since") + 1]) if "--since" in a else 0
maxp = int(a[a.index("--max-pages") + 1]) if "--max-pages" in a else 10 ** 6
s = requests.Session(); s.headers.update({"User-Agent": UA, "Accept": "application/json"}); s.trust_env = False
def P(e): return {p["propertyTypeCode"]: p.get("value") for p in e.get("parameters", [])}
def d8(v): return f"{v[:4]}-{v[4:6]}-{v[6:8]}" if v and re.match(r"\d{8}", v) else None
def page(etype, n):
    for att in range(4):
        try:
            r = s.get(base + "/public/api/entities/search/findBySpecification", timeout=(20, 120),
                      params={"viewName": "search", "filter": f"entityType.code = {etype}", "page": n, "size": 100, "sort": "id,desc"})
            if r.status_code == 200: return r.json()
            print("HTTP", r.status_code, etype, n, flush=True)
        except Exception as ex: print("ERR", etype, n, ex, flush=True)
        time.sleep(30 * (att + 1))
    return None
items, seen, skipped = [], set(), dict(nonpdf=0, old=0)
def add(cid, mime, title, num, adopted, pub, kind):
    if not cid: return
    if mime and "pdf" not in mime.lower(): skipped["nonpdf"] += 1; return
    yr = int((adopted or pub or "0000")[:4])
    if since and yr and yr < since: skipped["old"] += 1; return
    url = f"{base}/arcade/api/entities/content/{cid}"
    if url in seen: return
    seen.add(url); items.append(dict(url=url, title=title, number=num, adopted_date=adopted, published_date=pub, kind=kind))
for etype in ("ACTE", "DELIB"):
    n = 0
    while n < maxp:
        d = page(etype, n); time.sleep(2)
        if not d: print("give up", etype, "page", n, flush=True); break
        for e in d["content"]:
            p = P(e); pub = (e.get("publicationDate") or "")[:10] or None
            if etype == "DELIB":
                t = p.get("DELIB_TITLE") or e.get("name"); num = p.get("DELIB_NUMBER")
                add(e.get("contentId"), e.get("mimeType"), f"{num} — {t}" if num else t, num, d8(p.get("DELIB_DATE_VOTE")), d8(p.get("DELIB_LEGAL_RETURN")) or pub, "deliberation")
                continue
            t = p.get("ACTE_TITLE") or e.get("name"); num = next((x for x in (p.get("ACTE_NUMBER"), p.get("ACTE_FOLLOWER_NUMBER"), p.get("ACTE_CHRONO_NUMBER")) if x and x.strip() not in ("0", "")), None); typ = p.get("ACTE_TYPE") or "Acte"
            ad = d8(p.get("ACTE_DATE_ACT") or p.get("ACTE_CRAP_DATE_SIGN")); pb = d8(p.get("ACTE_DATE_PUB") or p.get("ACTE_CRAP_DATE_PUB")) or pub
            for c in e.get("children", []):
                cp = P(c); ct = c.get("entityTypeCode")
                if ct == "ACTE_FILE": add(c.get("contentId"), c.get("mimeType"), f"{typ} {num} — {t}" if num else f"{typ} — {t}", num, ad, pb, typ)
                elif ct == "ACTE_ANNEXE":
                    at = cp.get("ACTE_ANN_TITLE") or c.get("name")
                    add(c.get("contentId"), c.get("mimeType"), f"{typ} {num} — {t} — annexe: {at}", num, ad, pb, typ + " (annexe)")
        tp = d["page"]["totalPages"]; print(etype, "page", n + 1, "/", tp, "items", len(items), flush=True); n += 1
        if n >= tp: break
out.parent.mkdir(parents=True, exist_ok=True)
json.dump(dict(place_id="wd:" + qid, qid=qid, country_code="FR", source_platform="fr_raa_conseil_departemental",
               source_org="Conseil départemental — " + name, language="fr", doc_type="gazette_act", place_name=name,
               admin_level="department", index_url=base + "/arcade/index.html", items=items), open(out, "w"), ensure_ascii=False)
print("items", len(items), "skipped", skipped, "->", out, flush=True)
