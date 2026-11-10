"""PE: Poder Judicial 'Formatos' page (Orientación jurídica al usuario) forms, via Wayback id_ snapshots (pj.gob.pe unreachable from box)."""
import json, sys, re, datetime, hashlib, os, time, gzip, requests
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
now = datetime.datetime.now(datetime.UTC).isoformat(); OUT = f"{ROOT}/data/pe/pe_forms.jsonl"; FD = f"{ROOT}/forms/pe"; os.makedirs(FD, exist_ok=True)
IDX = "https://www.pj.gob.pe/wps/wcm/connect/CorteSuprema/s_cortes_suprema_home/as_servicios/as_enlaces_de_interes/as_orientacion_juridica_usuario/as_formatos/"
T = {"DEMANDA+DE+ALIMENTOS+PARA+MENORES+DE+EDAD": "Formulario de Demanda de Alimentos para personas menores de edad",
 "DEMANDA+DE+ALIMENTOS+PARA+MAYORES+DE+EDAD": "Formulario de Demanda de Alimentos para personas mayores de edad",
 "AUMENTO+DE+PENSION+DE+ALIMENTOS+PARA+MAYOR+DE+EDAD": "Formato de demanda de aumento de pensión de alimentos para mayores de edad",
 "FILIACION+EXTRAMATRIMONIAL+Y+EN+ACUMULADO+LA+PENSION+DE+ALIMENTOS": "Formulario de Demanda Acumulada de Filiación Judicial de paternidad extramatrimonial y de alimentos para niñas, niños y adolescentes",
 "AUMENTO+DE+PENSION+DE+ALIMENTOS": "Formato de demanda de aumento de pensión de alimentos para niñas, niños y adolescentes",
 "FORMATO_SOL_ACCESO_INF_190607": "Formato solicitud de acceso a la información pública",
 "FORMATO_DEMANDA_LABORAL-JUZG.PAZ.LETR": "Formato demanda laboral juzgado de paz letrado",
 "FORMATO_DEMANDA_LABORAL-JUZG.ES": "Formato demanda laboral juzgado especializado",
 "RA_182-2004_CE_PJ": "Formato auxilio judicial (R.A. 182-2004-CE-PJ)"}
CACHE = "/tmp/pe_fmt2.html"
if os.path.exists(CACHE): raw = open(CACHE, errors="ignore").read()
else:  # index page itself via Wayback (origin unreachable from box)
    raw = requests.get("https://web.archive.org/web/2026/" + IDX, timeout=120, headers={"User-Agent": UA}).text; open(CACHE, "w").write(raw)
links = sorted(set(re.findall(r'href="(/wps/wcm/connect/[0-9a-f]{32}/([^"/?]+)\.pdf\?MOD=AJPERES&CACHEID=[0-9a-f]{32})"', raw)))
old = {json.loads(l)["pdf_sha256"] for l in open(OUT)} if os.path.exists(OUT) else set(); rows = []; fail = []
for path, base in links:
    if base not in T: continue
    if any(('/'+base+'.pdf') in json.loads(l)['source_url'] for l in open(OUT)) if os.path.exists(OUT) else False: continue
    src = "https://www.pj.gob.pe" + path
    for k in range(3):
        try: r = requests.get("https://web.archive.org/web/2026id_/" + src, timeout=120, headers={"User-Agent": UA})
        except requests.RequestException as e: r = type("R", (), {"status_code": str(e)[:60], "content": b""})()
        time.sleep(15)
        if r.status_code == 200: break
        time.sleep(60)
    if r.status_code != 200 or not r.content.startswith(b"%PDF"): fail.append((base, r.status_code)); continue
    sha = hashlib.sha256(r.content).hexdigest()
    if sha in old: continue
    open(f"{FD}/{sha}.pdf", "wb").write(r.content)
    row=({"form_id": f"pe-{sha[:16]}", "court_id": None, "jurisdiction": "PE", "form_number": None, "title": T[base], "category": "poder-judicial-formatos",
      "language": "es", "file_format": "pdf", "pdf_path": f"forms/pe/{sha}.pdf", "pdf_sha256": sha, "file_bytes": len(r.content), "source_url": src, "index_url": IDX,
      "license": "Poder Judicial del Perú official forms; official texts excluded from copyright (D.Leg. 822 art. 9)",
      "site_policy": "archived_copy(wayback:2026);origin_unreachable", "retrieved_at": now})
    rows.append(row); open(OUT, "a").write(json.dumps(row, ensure_ascii=False) + "\n"); old.add(sha)
print("added", len(rows), "fail", fail)
