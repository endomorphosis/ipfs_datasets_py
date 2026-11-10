#!/usr/bin/env python3
"""2026-11-04 county lane: list a conseil départemental's délibérations (+annexes, PV) from a Digitech Webdelib+ public portal
(e.g. deliberations.mondepartement04.fr) -> entries JSON for pdf_list_fetch.py.
Public pages only (role=usager, no login, no bypass): jsp/seances.jsp + jsp/seances_archives.jsp -> every seance_agenda.jsp
(date, assembly) -> rows (numéro, intitulé, links 'Délibération'/'Annexe'/'Procès-verbal', dates retour préfecture / publication).
Viewer links openfile.jsp?...&pdf=T are rewritten to the PDF itself: jsp/showFile.jsp?pdf=T (query string -> pdf_list_fetch
doc_id = platform:sha1(url)[:16], i.e. URL-hash suffix). Polite: 2 s between pages, honest UA (pdf_list_fetch.UA); robots.txt not
consulted (owner decision 2026-11-01).
usage: fr_webdelib_list.py BASE QID NAME ISO OUT.json [--since YYYY] [--max-sessions N]"""
import json, sys, time, re, html
from pathlib import Path
from urllib.parse import urljoin, urlsplit, parse_qs, quote
import requests
sys.path.insert(0, str(Path(__file__).resolve().parent)); from pdf_list_fetch import UA
a = sys.argv[1:]; base, qid, name, iso, out = a[0].rstrip("/"), a[1], a[2], a[3], Path(a[4])
since = int(a[a.index("--since") + 1]) if "--since" in a else 0
maxs = int(a[a.index("--max-sessions") + 1]) if "--max-sessions" in a else 10 ** 6
s = requests.Session(); s.headers.update({"User-Agent": UA}); s.trust_env = False
def get(u):
    for att in range(4):
        try:
            r = s.get(u, timeout=(20, 120)); time.sleep(2)
            if r.status_code == 200: r.encoding = r.encoding or "utf-8"; return r.text
            print("HTTP", r.status_code, u, flush=True)
            if r.status_code in (403, 404): return None
        except Exception as ex: print("ERR", u, ex, flush=True)
        time.sleep(30 * (att + 1))
    return None
def T(x): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x))).strip(" -\u00a0")
def iso_d(x):
    m = re.match(r"(\d{2})[/-](\d{2})[/-](\d{4})", x or ""); return f"{m[3]}-{m[2]}-{m[1]}" if m else None
sessions = {}
for idx in ("/jsp/seances.jsp?role=usager", "/jsp/seances_archives.jsp?role=usager"):
    pg = get(base + idx)
    if not pg: print("index fail", idx, flush=True); continue
    for h in re.findall(r'href="([^"]*seance_agenda\.jsp\?[^"]+)"', pg):
        u = urljoin(base + idx, html.unescape(h)); q = parse_qs(urlsplit(u).query)
        d = (q.get("date") or [""])[0]; asm = (q.get("assembly") or [""])[0]
        if not d: continue
        if since and int(d[-4:]) < since: continue
        sessions.setdefault((d, asm), u)
order = sorted(sessions, key=lambda k: (k[0][-4:], k[0][3:5], k[0][:2]), reverse=True)[:maxs]
print("sessions", len(order), flush=True)
items, seen = [], set()
for (d, asm) in order:
    u = sessions[(d, asm)]; u = u.split("?")[0] + "?" + "&".join(f"{k}={quote(v[0])}" for k, v in parse_qs(urlsplit(u).query).items())
    pg = get(u)
    if not pg: continue
    n0 = len(items)
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", pg, re.S):
        links = re.findall(r'<a[^>]+href="([^"]*openfile\.jsp\?[^"]+)"[^>]*?(?:title="([^"]*)")?[^>]*>(.*?)</a>', row, re.S)
        if not links: continue
        tds = re.findall(r"<td[^>]*>(.*?)(?=<td|</tr>|$)", row, re.S)
        num = T(tds[0]) if tds else None
        intit = T(re.split(r"<a\s", tds[1])[0]) if len(tds) > 1 else ""
        dates = [iso_d(T(x)) for x in tds[2:]]; dates = [x for x in dates if x]
        for h, ttl, lab in links:
            h = html.unescape(h); q = parse_qs(urlsplit(h).query, keep_blank_values=True)
            tok = (q.get("pdf") or [""])[0]
            if not tok: continue
            pdf = f"{base}/jsp/showFile.jsp?pdf={quote(tok, safe='')}"
            if pdf in seen: continue
            seen.add(pdf); lab = T(lab) or "Document"
            dret = iso_d((q.get("dateRetLega") or [""])[0]) or (dates[0] if dates else None)
            dpub = iso_d((q.get("datePub") or [""])[0]) or (dates[-1] if dates else None)
            kind = "procès-verbal" if re.search(r"proc[eè]s|PV", lab, re.I) else ("annexe" if re.search(r"annexe", lab, re.I) else "deliberation")
            title = f"{asm} {d} — {num + ' — ' if num else ''}{intit or lab}" + (f" — annexe: {T(ttl)}" if kind == "annexe" and ttl else "") + (" — procès-verbal" if kind == "procès-verbal" and intit else "")
            items.append(dict(url=pdf, title=title[:500], number=num or None, adopted_date=iso_d(d), published_date=dpub,
                              kind=kind, extra={"assembly": asm, "session_date": iso_d(d), "date_retour_prefecture": dret, "label": lab}))
    print(asm, d, "items", len(items) - n0, "total", len(items), flush=True)
doc = {"place_id": f"wd:{qid}", "qid": qid, "country_code": "FR", "source_platform": "fr_raa_conseil_departemental",
       "source_org": f"Conseil départemental — {name}", "language": "fr", "doc_type": "gazette_act", "place_name": name,
       "iso_3166_2": iso, "admin_level": "department", "index_url": base + "/jsp/seances.jsp?role=usager", "items": items}
out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(doc, ensure_ascii=False, indent=0))
print("DONE", out, "sessions", len(order), "items", len(items), flush=True)
