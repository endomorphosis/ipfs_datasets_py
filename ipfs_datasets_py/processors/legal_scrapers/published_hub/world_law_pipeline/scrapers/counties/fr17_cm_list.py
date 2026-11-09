#!/usr/bin/env python3
"""2026-11-04 county lane: Charente-Maritime FR-17 (wd:Q3278) conseil départemental 'Délibérations et actes' lister -> pdf_list_fetch.py entries.
Site: la.charente-maritime.fr/informations-officielles/deliberations-et-actes (Drupal view, ~6,400 acts 2020-2026, 10/page, ?page=N).
PDFs at /deliberation?path=<file>.pdf (robots.txt Disallows them -> previously archive-only; robots ignored since Benjamin's 2026-11-01
decision, source_policy tagged robots_disallowed_ignored by the fetcher). Same host, 2 s/request, honest WorldLawBot UA, no bypass
(challenge pages stop the lister). PDFs only (spreadsheets skipped). Query-string URLs -> fetcher doc_id is a URL hash.
Usage: fr17_cm_list.py <out.json> [--pages N] [--limit N]   (writes <out.json> atomically; prints LISTED n at the end)"""
import re, sys, json, time, html, os, urllib.parse as U, requests
UA = "WorldLawBot/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law; public-law research crawler; polite)"
HOST = "https://la.charente-maritime.fr"; BASE = HOST + "/informations-officielles/deliberations-et-actes"
out = sys.argv[1]; arg = lambda k: int(sys.argv[sys.argv.index(k)+1]) if k in sys.argv else 0
maxp, lim = arg("--pages"), arg("--limit")
s = requests.Session(); s.headers["User-Agent"] = UA; s.trust_env = False
def get(u, tries=3):
    for t in range(tries):
        time.sleep(2)
        try:
            r = s.get(u, timeout=(15, 60))
            if r.status_code in (429, 503): print("BACKOFF", r.status_code, u, flush=True); time.sleep(120 * (t + 1)); continue
            r.raise_for_status()
        except Exception as e: print("ERR", u, e, flush=True); time.sleep(30); continue
        if "cf-chl" in r.text or "captcha" in r.text.lower()[:5000]: print("CHALLENGE", u, flush=True); return None
        return r
    return None
def clean(x): return re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", " ", x))).strip()
items, seen, last, empty = [], set(), None, 0
r = get(BASE)
if r:
    m = re.findall(r'\?page=(\d+)', r.text); last = max(map(int, m)) if m else 0
    tot = re.search(r'results_informations">\s*(\d+)', r.text); print("total", tot.group(1) if tot else "?", "last_page", last, flush=True)
p = 0
while r is not None and p <= (last or 0) and (not maxp or p < maxp):
    if p: r = get(f"{BASE}?page={p}")
    if r is None: print("STOP page", p, flush=True); break
    n0 = len(items)
    for a in re.findall(r'<article class="node node--type-deliberations.*?</article>', r.text, re.S):
        h = re.search(r'<a class="document_title" href="([^"]+)"[^>]*>(.*?)</a>', a, re.S)
        if not h: continue
        raw = html.unescape(h.group(1)); path = U.unquote(raw.split("path=", 1)[-1]) if "path=" in raw else raw
        if re.search(r"\.(xlsx?|ods|csv)$", path, re.I): continue
        if not re.search(r"\.pdf$", path, re.I): continue
        url = U.urljoin(HOST, raw.split("?")[0]) + "?path=" + U.quote(path, safe="")
        if url in seen: continue
        seen.add(url)
        ds = clean(re.search(r'<div class="date_seance">(.*?)</div>', a, re.S).group(1)) if 'date_seance' in a else ""
        dm = re.search(r"(\d{2})/(\d{2})/(\d{4})", ds); dt = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}" if dm else None
        kind = clean(ds.split(" du ")[0]).lower() if ds else None
        num = re.search(r"Numéro de suivi de l'acte\s*:\s*([^<]+)<", a)
        items.append({"url": url, "title": (kind.capitalize() + " — " if kind else "") + clean(h.group(2)), "number": num.group(1).strip() if num else None,
                      "adopted_date": dt, "kind": kind, "extra": {"file_name": path}})
    empty = empty + 1 if len(items) == n0 else 0
    if p % 25 == 0: print(f"page {p}/{last} -> {len(items)} items", flush=True)
    if empty >= 5: print("STOP 5 empty pages at", p, flush=True); break
    p += 1
if lim: items = items[:lim]
meta = {"place_id": "wd:Q3278", "qid": "Q3278", "country_code": "FR", "source_platform": "fr_raa_conseil_departemental",
        "source_org": "Conseil départemental — Charente-Maritime", "language": "fr", "doc_type": "gazette_act", "place_name": "Charente-Maritime",
        "iso_3166_2": "FR-17", "admin_level": "department", "index_url": BASE, "items": items}
json.dump(meta, open(out + ".part", "w"), ensure_ascii=False, indent=1); os.replace(out + ".part", out)
print("LISTED", len(items), "pages", p, flush=True)
