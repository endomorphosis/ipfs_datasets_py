"""Supreme-court rosters (names + titles only; secretariat e-mails/bios NOT stored): UY SCJ 'Integración', CU TSP 'Consejo de Gobierno'."""
import json, sys, re, datetime, hashlib, html, os
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
RAW = f"{ROOT}/rules/raw/judges_latam"; now = datetime.datetime.now(datetime.UTC).isoformat()
def txt(f):
    t = open(f"{RAW}/{f}", errors="ignore").read(); t = re.sub(r"(?s)<(script|style|head|nav|footer).*?</\1>", "", t)
    return [l.strip() for l in html.unescape(re.sub(r"<[^>]+>", "\n", t)).split("\n") if l.strip()]
def slug(s): return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")
def add(cc, court, items, src, f):
    p = f"{ROOT}/data/{cc}/{cc}_judges.jsonl"; old = [json.loads(l) for l in open(p)] if os.path.exists(p) else []
    seen = {norm(j["name"]) for j in old}; new = []
    for name, title in items:
        if norm(name) in seen: continue
        seen.add(norm(name))
        new.append({"judge_id": f"{court}-{slug(name)}", "court_id": court, "name": name, "title": title, "position_type": "chief" if title.lower().startswith("president") and "sala" not in title.lower() else "appellate",
          "term_start": None, "term_end": None, "status": "sitting", "roster_url": src, "source_url": src, "site_policy": "robots_allowed", "retrieved_at": now, "needs_review": False,
          "extraction": "official supreme court roster page (names and titles only)", "license": "official judiciary website (facts)", "source_sha256": hashlib.sha256(open(f"{RAW}/{f}", "rb").read()).hexdigest()})
    with open(p, "a") as fo:
        for j in new: fo.write(json.dumps(j, ensure_ascii=False) + "\n")
    print(cc, "+", len(new), [j["name"] for j in new])
L = txt("uy_sc.html"); it = []
for i, l in enumerate(L):
    if l == "Nombre" and i + 1 < len(L): it.append((re.sub(r"^(Dra?\.)\s+", "", L[i + 1]), L[i - 3] if L[i - 2] == "Imagen" else L[i - 1]))
if len(sys.argv) == 1: add("uy", "uy-supreme-court", it, "https://www.poderjudicial.gub.uy/suprema-corte-de-justicia/integrantes", "uy_sc.html")
L = txt("cu_int.html"); it = []
for i, l in enumerate(L[1:], 1):
    if re.match(r"^(Presidente?a?|Vicepresident[ea]|Secretari[oa])\b", l) and re.fullmatch(r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+( [A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,4}", L[i - 1]):
        it.append((L[i - 1], l + " del Tribunal Supremo Popular" if l in ("Presidente", "Presidenta", "Vicepresidente", "Vicepresidenta") else l))
if len(sys.argv) == 1: add("cu", "cu-supreme-court", it, "https://www.tsp.gob.cu/integracion-del-consejo-de-gobierno", "cu_int.html")
# PA CSJ table
t = open(f"{RAW}/pa_csj.html", errors="ignore").read(); it = []
for tr in re.findall(r"(?s)<tr.*?</tr>", t):
    td = [html.unescape(re.sub(r"<[^>]+>|\s+", " ", x)).strip() for x in re.findall(r"(?s)<t[dh].*?</t[dh]>", tr)]
    if len(td) >= 2 and re.match(r"Magistrad[oa] ", td[0]): it.append((re.sub(r"^Magistrad[oa]\s+", "", td[0]), f"Magistrado/a — {td[1]}"))
if len(sys.argv) > 1 and sys.argv[1] == "pa": add("pa", "pa-supreme-court", it, "https://www.organojudicial.gob.pa/corte-suprema-de-justicia-1", "pa_csj.html")
