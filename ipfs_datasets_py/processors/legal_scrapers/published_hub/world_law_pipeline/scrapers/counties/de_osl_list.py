#!/usr/bin/env python3
"""2026-11-05 county lane: Landkreis Oberspreewald-Lausitz (wd:Q6156) Amtsblatt lister -> pdf_list_fetch.py entries.
Index www.osl-online.de/amtsblatt/index.php?ebene=496 lists every issue (Nr., date) with a public POST download form
(hidden form=gazette_N, hash=...). The same public download works as a plain GET with those two fields as query params
(no session/login/bypass), so items use that GET URL (query string -> fetcher doc_id is a URL hash).
One page request, 2 s, honest WorldLawBot UA. Usage: de_osl_list.py <out.json> [--limit N]"""
import re, sys, json, os, html, time, requests
UA = "WorldLawBot/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law; public-law research crawler; polite)"
IDX = "https://www.osl-online.de/amtsblatt/index.php?ebene=496"
out = sys.argv[1]; lim = int(sys.argv[sys.argv.index("--limit")+1]) if "--limit" in sys.argv else 0
s = requests.Session(); s.headers["User-Agent"] = UA; s.trust_env = False; time.sleep(2)
t = s.get(IDX, timeout=(15, 90)).text
items, seen = [], set()
for m in re.finditer(r'<td>\s*Nr\.\s*([^<]+?)\s*</td>\s*<td>([^<]+)</td>\s*<td>.*?name="hash" value="([0-9a-f]+)".*?name="form" value="(gazette_\d+)"', t, re.S):
    nr, d, h, f = m.group(1).strip(), html.unescape(m.group(2)).replace("\u200b", "").strip(), m.group(3), m.group(4)
    url = f"{IDX}&form={f}&hash={h}"
    if url in seen: continue
    seen.add(url); dm = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", d)
    items.append({"url": url, "title": f"Amtsblatt für den Landkreis Oberspreewald-Lausitz Nr. {nr}", "number": nr,
                  "published_date": f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}" if dm else None})
if lim: items = items[:lim]
meta = {"place_id": "wd:Q6156", "qid": "Q6156", "country_code": "DE", "source_platform": "de_kreis_amtsblatt", "language": "de",
        "doc_type": "gazette_act", "iso_3166_2": "DE-BB", "admin_level": "landkreis", "doc_id_prefix": "de_osl",
        "source_org": "Landkreis Oberspreewald-Lausitz", "place_name": "Landkreis Oberspreewald-Lausitz", "index_url": IDX, "items": items}
json.dump(meta, open(out + ".part", "w"), ensure_ascii=False, indent=1); os.replace(out + ".part", out)
print("LISTED", len(items), flush=True)
