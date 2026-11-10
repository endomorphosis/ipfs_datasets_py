"""EC: Corte Nacional de Justicia - 'Salas Especializadas' page (cortenacional.gob.ec; robots.txt 404 => allowed). National judges listed per
specialised chamber (names + chamber only). A judge listed in several chambers gets one row with all chambers in the title."""
import json, sys, re, datetime, os, collections
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from courts_common import *
from bs4 import BeautifulSoup as B
SRC = "https://www.cortenacional.gob.ec/salas-especializadas/"; RAW = f"{ROOT}/rules/raw/ec/cnj_salas_especializadas.html"
if not os.path.exists(RAW): open(RAW, "w").write(get(SRC, delay=2))
s = B(open(RAW, errors="ignore"), "html.parser"); ch = collections.OrderedDict(); prof = {}
for it in s.select(".eael-image-accordion-item"):
    h = it.find("h2"); p = it.find("p")
    if not h: continue
    nm = re.sub(r"\s+", " ", h.get_text(" ", strip=True)); sala = re.sub(r"\s+", " ", p.get_text(" ", strip=True)) if p else None
    ch.setdefault(nm, []); 
    if sala and sala not in ch[nm]: ch[nm].append(sala)
    a = h.find_parent("a"); prof[nm] = a["href"] if a else None
OUT = f"{ROOT}/data/ec/ec_judges.jsonl"; old = rjl(OUT); oid = {x["judge_id"] for x in old}; onm = {norm(x["name"]) for x in old}
now = datetime.datetime.now(datetime.UTC).isoformat(); rows = []
for nm, salas in ch.items():
    jid = "ec-corte-nacional-de-justicia-" + slug(nm)
    if jid in oid or norm(nm) in onm: continue
    rows.append({"judge_id": jid, "court_id": "ec-corte-nacional-de-justicia", "name": nm,
        "title": "Juez/a Nacional, Sala Especializada de lo " + " / ".join(salas) if salas else "Juez/a Nacional",
        "position_type": "member", "chamber": salas, "term_start": None, "term_end": None, "status": "sitting", "roster_url": SRC,
        "source_url": prof.get(nm) or SRC, "site_policy": "robots_absent_allowed", "retrieved_at": now, "needs_review": True,
        "extraction": "Salas Especializadas page (judge cards: name + chamber)", "license": "Corte Nacional de Justicia del Ecuador public website"})
with open(OUT, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("chamber cards", sum(len(v) for v in ch.values()), "unique", len(ch), "added", len(rows))
