"""CR: Corte Suprema de Justicia - 'Lista de Magistrados Propietarios' (Secretaría General de la Corte, robots allow). Names + official role only;
academic prefixes (Lic./Dr./M.Sc.) stripped from the name."""
import json, sys, re, datetime, os
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from courts_common import *
from bs4 import BeautifulSoup as B
SRC = "https://secretariacorte.poder-judicial.go.cr/index.php/lista-de-magistrados-propietarios"
RAW = f"{ROOT}/rules/raw/cr/lista_magistrados_propietarios.html"
if not os.path.exists(RAW): open(RAW, "w").write(get(SRC, delay=2))
s = B(open(RAW, errors="ignore"), "html.parser"); m = s.find(attrs={"itemprop": "articleBody"}) or s
L = m.get_text("\n", strip=True).split("\n")
OUT = f"{ROOT}/data/cr/cr_judges.jsonl"; old = {x["judge_id"] for x in rjl(OUT)}
CID = "cr-wd-q7644938"; now = datetime.datetime.now(datetime.UTC).isoformat(); rows = []; sala = None
for x in L:
    if re.match(r"^Sala (Primera|Segunda|Tercera|Constitucional)$", x): sala = x; continue
    if not sala: continue
    mm = re.match(r"^(Lic\.|Licda\.|Dr\.|Dra\.|M\.\s?Sc\.|MSc\.)\s*(.+?)(?:,\s*(.+))?$", x)
    if not mm: 
        if x in ("Menú",): break
        continue
    nm, role = mm.group(2).strip(), (mm.group(3) or "").strip()
    fem = mm.group(1) in ("Dra.", "Licda.") or (role and "Presidenta" in role or "Vicepresidenta" in role)
    t = ("Magistrada propietaria" if fem else "Magistrado propietario") + f", {sala}" + (f" ({re.sub(r'\s+', ' ', role)})" if role else "")
    jid = "cr-csj-" + slug(nm)
    if jid in old or jid in {r["judge_id"] for r in rows}: continue
    rows.append({"judge_id": jid, "court_id": CID, "name": nm, "title": t, "position_type": "president_of_chamber" if "President" in role and "Sala" in role else ("vice_president" if "Vicepresident" in role else "member"),
        "chamber": sala, "term_start": None, "term_end": None, "status": "sitting", "roster_url": SRC, "source_url": SRC, "site_policy": "robots_allowed",
        "retrieved_at": now, "needs_review": True, "extraction": "official roster page (Secretaría General de la Corte)", "license": "Poder Judicial de Costa Rica public website"})
with open(OUT, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(rows))
