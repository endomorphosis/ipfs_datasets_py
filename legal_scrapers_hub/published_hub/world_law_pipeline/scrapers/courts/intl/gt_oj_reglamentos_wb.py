"""GT: Organismo Judicial (oj.gob.gt; origin unreachable from box) court regulations via Wayback Machine id_ snapshots (CDX found 2026-11-02):
Reglamento General de Tribunales, Reglamento Interior de Juzgados y Tribunales Penales, Reglamento de Gestión (femicidio courts),
Reglamento de funcionamiento de los Centros de Mediación del OJ, Reglamentos del Consejo de la Carrera Judicial 1-2020 / 2-2020, Reglamento
niñez y adolescencia. PDFs -> pdftotext -> article-level rows ('Artículo N'); documents whose text layer is missing are skipped.
All rows needs_review (pdftotext of archived copies). Append-only, dedupe by rule_id. Usage: gt_oj_reglamentos_wb.py [--dry]"""
import json, re, os, sys, time, hashlib, datetime, subprocess, shutil
ROOT = "/workspace/world_courts"; RAW = f"{ROOT}/rules/raw/gt_oj"; os.makedirs(RAW, exist_ok=True)
UA = "world_courts/0.1 (open court-data research; github.com/endomorphosis)"; dry = "--dry" in sys.argv
OUT = f"{ROOT}/data/gt/gt_rules.jsonl"; now = datetime.datetime.now(datetime.timezone.utc).isoformat()
POL = "archived_copy(wayback:{ts});origin_unreachable|oj.gob.gt robots not checkable (origin unreachable); official Organismo Judicial publication, no terms stated"
LIC = "Guatemala Organismo Judicial regulation (acuerdo of the Corte Suprema de Justicia / Presidencia / Consejo de la Carrera Judicial); official text, no licence stated"
DOCS = [  # (key, wayback ts, original url, rule_set title, court_id, effective/acuerdo note)
 ("rgt", "20220816093331", "http://www.oj.gob.gt/Archivos/UnidaddeInformacionPublica/IPO/Articulo%2010/Numeral-01/2021/Reglamento%20General%20de%20Tribunales.pdf", "Reglamento General de Tribunales (Acuerdo 36-2004 CSJ)", "gt-supreme-court"),
 ("rijtp", "20220816093319", "http://www.oj.gob.gt/Archivos/UnidaddeInformacionPublica/IPO/Articulo%2010/Numeral-01/2021/Reglamento%20Interior%20de%20Juzgados%20yTribunales%20Penales.pdf", "Reglamento Interior de Juzgados y Tribunales Penales (Acuerdo 24-2005 CSJ)", "gt-lower-court"),
 ("rgfem", "20180517110709", None, "Reglamento de Gestión para los Juzgados y Tribunales con competencia en delitos de Femicidio y otras formas de Violencia contra la Mujer", "gt-lower-court"),
 ("rmed", "20220719033259", "http://www.oj.gob.gt/Archivos/DMASC/ArchivosIntroduccion/Acdo.%20Pres.%20138-013%20Reglamento%20%20Funcionamiento%20Centros%20de%20Mediaci%C3%B3n%20del%20OJ.pdf", "Reglamento de Funcionamiento de los Centros de Mediación del Organismo Judicial (Acuerdo de Presidencia 138-2013)", None),

# rlccj: archived PDF has a garbled OCR layer (column offsets, broken words) -> skipped this run
 # ("rlccj", "20220719032021", "http://www.oj.gob.gt/Archivos/CCJ/Publicaciones/Documentos%20de%20Interes/Acdo.%20CCJ%201-2020%20Reglamento%20de%20la%20Ley%20del%20Consejo%20de%20la%20Carrera%20Judicial.pdf", "Reglamento de la Ley de la Carrera Judicial (Acuerdo CCJ 1-2020)", None),
 ("revd", "20220719031959", "http://www.oj.gob.gt/Archivos/CCJ/Publicaciones/Documentos%20de%20Interes/Acdo.%20CCJ%202-2020%20Reglamento%20de%20la%20Evaluaci%C3%B3n%20del%20Desempe%C3%B1o.pdf", "Reglamento de la Evaluación del Desempeño (Acuerdo CCJ 2-2020)", None),
 ("rna", "20140801201329", "http://www.oj.gob.gt:80/uci/images/leyes/otrasleyes/reglamento_ninez_adolescencia.pdf", "Reglamento de Gestión de los Juzgados y Salas con competencia en materia de Niñez y Adolescencia (Acuerdo 42-2007 CSJ)", "gt-lower-court"),
]
FEM_PREFIX = "http://www.oj.gob.gt:80/justiciadegenero/wp-content/uploads/2015/03/Reglamento-de-Gesti"
def curl(u, out):
    r = subprocess.run(["curl", "-s", "-L", "-m", "240", "-A", UA, "-o", out, "-w", "%{http_code}", u], capture_output=True, text=True); time.sleep(3); return r.stdout
def cdx_full(prefix, ts):
    r = subprocess.run(["curl", "-s", "-m", "120", "-A", UA, f"https://web.archive.org/cdx/search/cdx?url={prefix}*&output=txt&filter=statuscode:200&limit=5"], capture_output=True, text=True); time.sleep(3)
    for l in r.stdout.splitlines():
        p = l.split()
        if len(p) > 2 and p[1] == ts: return p[2]
    return None
old = [json.loads(l) for l in open(OUT) if l.strip()]; ids = {r["rule_id"] for r in old}; rows = []; report = []
for key, ts, url, title, cid in DOCS:
    if url is None: url = cdx_full(FEM_PREFIX, ts)
    if not url: report.append((key, "no url")); continue
    p = f"{RAW}/{key}.pdf"
    if not os.path.exists(p) or os.path.getsize(p) < 1000:
        if shutil.disk_usage("/workspace").free < 20 * 2**30: raise SystemExit("disk < 20 GB, pausing downloads")
        st = curl(f"https://web.archive.org/web/{ts}id_/{url}", p)
        if st != "200" or not open(p, "rb").read(4) == b"%PDF": report.append((key, "fetch", st)); continue
    sha = hashlib.sha256(open(p, "rb").read()).hexdigest()
    txt = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout
    if len(txt.strip()) < 1000: report.append((key, "no text layer")); continue
    txt = txt.replace("\f", "\n")
    hs = [(m.start(), m.group(1)) for m in re.finditer(r"(?m)^\s*ART[IÍ]CULO\s+(\d+(?:\s*BIS)?)\s*[\.\-:ºo°]*", txt, re.I)]
    # keep a monotonic sequence (drop references inside text that happen to start a line)
    seq = []; last = 0
    for pos, n in hs:
        k = int(re.match(r"\d+", n).group(0))
        if k >= last and k <= last + 3 or (not seq and k == 1): seq.append((pos, n.replace(" ", "").upper())); last = k
    if len(seq) < 5: report.append((key, "articles", len(seq))); continue
    sid = f"gt-oj-{key}"; nrow = 0
    for i, (pos, n) in enumerate(seq):
        end = seq[i + 1][0] if i + 1 < len(seq) else len(txt)
        body = re.sub(r"[ \t]+", " ", txt[pos:end]); body = re.sub(r"\n\s*\n+", "\n", body).strip()
        rid = f"{sid}:art-{n.lower()}"
        if rid in ids: continue
        ids.add(rid); nrow += 1
        rows.append({"rule_id": rid, "rule_set_id": sid, "court_id": cid, "jurisdiction": "GT", "rule_set": title, "rule_number": f"Art. {n}", "title": None,
            "part": None, "text": body[:150000], "effective_date": None, "pdf_path": f"rules/raw/gt_oj/{key}.pdf", "pdf_sha256": sha, "source_sha256": sha,
            "source_url": url, "archive_url": f"https://web.archive.org/web/{ts}/{url}", "source_kind": "official_archived", "site_policy": POL.format(ts=ts[:8]),
            "license": LIC, "retrieved_at": now, "language": "es", "needs_review": True, "version_note": f"Wayback snapshot {ts}; pdftotext article split; may not reflect later amendments"})
    report.append((key, "articles", len(seq), "new", nrow))
if not dry and rows:
    with open(OUT, "a") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("rules new", len(rows)); [print(x) for x in report]
