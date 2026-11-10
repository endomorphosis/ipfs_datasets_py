#!/usr/bin/env python3
"""List Loire (FR-42, wd:Q12569) Conseil départemental arrêtés from Webdelib+ (webdelib-citoyens.loire.fr),
monthly summary_orders.jsp pages 01-2025 .. current month -> entries JSON for pdf_list_fetch.py.
PDF url = jsp/showFile.jsp?pdf=<token> (same as the 1,774 already published)."""
import html, json, re, sys, time, urllib.parse
from datetime import date
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).resolve().parent)); from pdf_list_fetch import UA
BASE = "https://webdelib-citoyens.loire.fr/webdelibplus/jsp/"
out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent / "entries/fr_raa_cd_fr-42.json")
s = requests.Session(); s.headers["User-Agent"] = UA; s.trust_env = False
items, seen = [], set(); today = date.today()
ROW = re.compile(r'<tr style="width:100%"><td[^>]*>(.*?)</td></td><td class="tableActe"[^>]*>(.*?)<a href="\.\./jsp/openfile\.jsp\?([^"]+)"[^>]*>(.*?)</a>(.*?)<td[^>]*>(.*?)</td><td[^>]*>(.*?)</td></tr>', re.S)
def iso(d):
    m = re.match(r"(\d\d)/(\d\d)/(\d{4})", d.strip()); return f"{m[3]}-{m[2]}-{m[1]}" if m else None
for y in (2025, 2026):
    for mo in range(1, 13):
        if (y, mo) > (today.year, today.month): break
        r = s.get(BASE + f"summary_orders.jsp?role=usager&date={mo:02d}-{y}", timeout=60); time.sleep(1.5)
        c = 0
        for num, obj, q, kind, tail, d_acte, d_pub in ROW.findall(r.text):
            qs = urllib.parse.parse_qs(html.unescape(q)); tok = qs.get("pdf", [None])[0]
            if not tok: continue
            url = BASE + "showFile.jsp?pdf=" + urllib.parse.quote(tok, safe="")
            if url in seen: continue
            seen.add(url); c += 1
            clean = lambda x: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(x))).strip(" -")
            title = f"{clean(num)} {clean(obj)} - {clean(kind)} - {clean(tail)} {clean(d_acte)} {clean(d_pub)}".strip()
            items.append(dict(url=url, title=title, number=clean(num) or None, adopted_date=iso(d_acte), published_date=iso(d_pub)))
        print(f"{mo:02d}-{y}: {c}", flush=True)
# séances (délibérations + annexes) from 2025 on, from the seances.jsp agenda links
A = re.compile(r'<a href="\.\./jsp/openfile\.jsp\?([^"]+)"[^>]*>(.*?)</a>', re.S)
idx = s.get(BASE + "seances.jsp?role=usager", timeout=60).text; time.sleep(1.5)
ags = sorted(set(html.unescape(x) for x in re.findall(r'seance_agenda\.jsp\?([^"]+)', idx)))
for q in ags:
    d = urllib.parse.parse_qs(q).get("date", ["0"])[0]
    if d < "20250101": continue
    r = s.get(BASE + "seance_agenda.jsp?" + q.replace(" ", "%20"), timeout=60); time.sleep(1.5); c = 0
    for row in r.text.split('<tr style="width:100%">')[1:]:
        tds = re.findall(r'<td[^>]*>(.*?)(?=</td>|<td)', row, re.S)
        if len(tds) < 4: continue
        clean = lambda x: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(x))).strip(" -")
        num = clean(tds[0]); obj = clean(A.sub("", tds[1])); d1, d2 = clean(tds[-2]), clean(tds[-1])
        for qq, kind in A.findall(row):
            tok = urllib.parse.parse_qs(html.unescape(qq)).get("pdf", [None])[0]
            if not tok: continue
            url = BASE + "showFile.jsp?pdf=" + urllib.parse.quote(tok, safe="")
            if url in seen: continue
            seen.add(url); c += 1
            items.append(dict(url=url, title=f"{num} {obj} - {clean(kind)} {d1} {d2}".strip(), number=num or None,
                              adopted_date=f"{d[:4]}-{d[4:6]}-{d[6:]}", published_date=iso(d2)))
    print("seance", d, c, flush=True)
out.parent.mkdir(parents=True, exist_ok=True)
json.dump(dict(place_id="wd:Q12569", country_code="FR", source_platform="fr_raa_conseil_departemental",
               source_org="Conseil départemental — Loire", doc_id_prefix="5f2e063b131ab994", language="fr",
               doc_type="gazette_act", place_name="Loire", admin_level="department", items=items), open(out, "w"), ensure_ascii=False)
print("items", len(items), "->", out)
