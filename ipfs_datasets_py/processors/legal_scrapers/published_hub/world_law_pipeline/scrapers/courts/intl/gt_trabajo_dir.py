"""GT: Organismo Judicial 'Directorio de Juzgados y Salas en materia de Trabajo y Previsión Social' (oj.gob.gt/Archivos/Laborales2019/Directorio/Directorio.pdf) via Wayback 20230610111446. Court names + official court mailbox/phone (no staff)."""
import json, sys, re, datetime, hashlib
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
P = f"{ROOT}/rules/raw/wb_dir/gt_lab.txt"; SRC = "http://www.oj.gob.gt/Archivos/Laborales2019/Directorio/Directorio.pdf"
now = datetime.datetime.now(datetime.UTC).isoformat(); OUT = f"{ROOT}/data/gt/gt_courthouses.jsonl"
old = [json.loads(l) for l in open(OUT)]; oldn = {norm(r["name"]) for r in old}
L = open(P).read().split("\n"); EM = re.compile(r"[\w.\-]+@oj\.gob\.gt"); used = set(); rows = []; dept = None
left = lambda s: re.split(r"\s{3,}", s.strip())[0].strip() if s.strip() else ""
for i, x in enumerate(L):
    h = re.match(r"^\s*\d+\.\s+(.+?)\.?\s*$", x)
    if h and not EM.search(x) and h.group(1).isupper(): dept = h.group(1).title(); continue
    m = EM.search(x)
    if not m: continue
    parts = []
    if i - 1 not in used and L[i - 1].strip() and not EM.search(L[i - 1]) and not re.match(r"^\s*(JUZGADO|SALA)\s+CORREO", L[i - 1]) and not re.match(r"^\s*\d+\.\s", L[i - 1]): parts.append(left(L[i - 1])); used.add(i - 1)
    lx = left(x[:m.start()]) if x[:m.start()].strip() else ""
    if lx: parts.append(lx)
    if i + 1 < len(L) and L[i + 1].strip() and not EM.search(L[i + 1]) and not re.match(r"^\s*\d+\.\s", L[i + 1]) and not EM.search(L[i + 2] if i + 2 < len(L) else "") or (i + 1 < len(L) and re.match(r"^\s*(de |y |en |Trabajo|Previsi)", L[i + 1].strip()) ):
        if L[i + 1].strip() and not EM.search(L[i + 1]): parts.append(left(L[i + 1])); used.add(i + 1)
    nm = re.sub(r"\s+", " ", " ".join(parts)).strip()
    if not nm: continue
    tel = re.search(r"(\d{4}-\d{4}(?:\s*(?:y|/|,)\s*\d{4}-?\d{0,4})*)", x[m.end():]); kind = "Sala" if nm.lower().startswith("sala") else "Juzgado"
    full = nm if re.match(r"(?i)^(juzgado|sala)", nm) else f"Juzgado {nm}"
    if dept and dept.lower() not in full.lower(): full = f"{full}, {dept}"
    cid = "gt-oj-trab-" + re.sub(r"[^a-z0-9]+", "-", norm(full)).strip("-")[:90]
    if norm(full) in oldn or cid in {r["court_id"] for r in rows}: continue
    rows.append({"court_id": cid, "record_type": "courthouse", "name": full, "name_local": full, "level": "appellate" if kind == "Sala" else "trial", "court_system": "national",
      "country_code": "GT", "subdivision": "GT", "jurisdiction": "Trabajo y Previsión Social", "parent_court_id": None,
      "address": {"street": None, "city": None, "postcode": None, "region": dept, "country": "GT"}, "geo": {"lat": None, "lon": None},
      "phone": tel.group(1) if tel else None, "email": m.group(0), "website": None, "wikidata": None, "place_ids": [], "source_url": SRC, "source_kind": "official",
      "site_policy": "archived_copy(wayback:20230610111446);origin_403", "retrieved_at": now, "license": "Guatemalan official public information (Ley de Acceso a la Información Pública)",
      "needs_review": True, "record_note": "Directorio OJ (labour courts), archived 2023; court mailbox, not personal"})
with open(OUT, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(rows)); [print(" ", r["name"], "|", r["email"], r["phone"]) for r in rows[::12]]
