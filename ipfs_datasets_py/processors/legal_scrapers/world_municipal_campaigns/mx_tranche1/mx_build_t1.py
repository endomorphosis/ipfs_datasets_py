"""Mexico tranche 1 — harvest + build (checkpointed per municipio).

Cloned from the pilot builder (mx_pilot/scripts/mx_build.py) 2026-10-14;
identical fetch/extract/split/validate machinery, tranche-1 config.


Route: compiled reglamentos/bandos published as full-text PDFs on the
municipios' own official portals (marco normativo / transparencia /
normatividad sections). Fetches with hard-capped curl, extracts text via
the program chain (pdfplumber -> PyMuPDF -> pdftotext -> tesseract spa),
splits to article-level rows ("Articulo N" units), builds world_municipal
19-column parquets, validates fail-closed on write and on re-read.
State lands in mx_pilot/run_manifest.json after every municipio;
parquets in mx_pilot/data/. Doc URLs were verified 2026-10-14 via the
sites' own pages and search indexes (see pilot report).
"""
import html as html_mod
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.normalize import make_row, finalize_rows, drop_empty_rows  # noqa: E402
from world_municipal.schema import rows_to_table, validate_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report, read_html_parquet  # noqa: E402
from world_municipal.jurisdiction import get_scheme  # noqa: E402

OUT = Path(__file__).resolve().parent.parent
SCRATCH = OUT / "scratch" / "pdfs"
SCRATCH.mkdir(parents=True, exist_ok=True)
DATA = OUT / "data"
RETRIEVED = "2026-10-14"
MX = get_scheme("MX")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 world-municipal-law-pilot/0.1"

MTY = "https://www.monterrey.gob.mx/pdf/reglamentos/"
GDL = ("https://difgdl.gob.mx/wp-content/uploads/Transparencia/Articulo8/"
       "Fraccion_II/Inciso_d/03.%20Reglamentos%20Municipales/")
MUNICIPIOS = {
    "11020": {"state": "Guanajuato", "platform": "normatividad municipal portal (normatividadmunicipal.leon.gob.mx)", "docs": [
        ("Reglamento de Policia y Vialidad para el Municipio de Leon, Guanajuato",
         "https://normatividadmunicipal.leon.gob.mx/archivos/Reglamento_de_Polica_y_Vialidad_para_el_-945705416-detreg-142.pdf"),
    ]},
    "15033": {"state": "Mexico", "platform": "municipal portal (ecatepec.gob.mx)", "docs": [
        ("Bando Municipal de Ecatepec de Morelos 2026",
         "https://ecatepec.gob.mx/wp-content/uploads/2026/03/BANDO_2026.pdf"),
        ("Reglamentos Municipales de Ecatepec de Morelos 2025",
         "https://ecatepec.gob.mx/wp-content/uploads/2025/08/2025-REGLAMENTOS-3.pdf"),
    ]},
    "08037": {"state": "Chihuahua", "platform": "municipal portal transparencia (juarez.gob.mx)", "docs": [
        ("Reglamento Organico de la Administracion Publica del Municipio de Juarez",
         "https://juarez.gob.mx/transparencia/docs/reglamento-organico-de-la-administracion-publica-ult-ref-01-ene-22-vigente.pdf"),
    ]},
    "15058": {"state": "Mexico", "platform": "municipal portal /reglamentos/ (neza.gob.mx)", "docs": [
        ("Bando Municipal de Nezahualcoyotl 2026",
         "https://neza.gob.mx/bando2026/assets/pdf/Bando%20Municipal%202026.pdf"),
        ("Reglamento de Proteccion Civil del Municipio de Nezahualcoyotl",
         "https://neza.gob.mx/reglamentos/5.REGLAMENTO%20DE%20PROTECCION%20CIVIL%20DEL%20MUNICIPIO%20DE%20NEZAHUALCOYOTL.pdf"),
        ("Reglamento Municipal de Turismo Sostenible y Desarrollo Artesanal de Nezahualcoyotl",
         "https://www.neza.gob.mx/reglamentos/13.REGLAMENTO%20MUNICIPAL%20DE%20TURISMO%20SOSTENIBLE%20Y%20DESARROLLO%20ARTESANAL%20DEL%20MUNICIPIO%20DE%20NEZAHUALC%C3%93YOTL.pdf"),
    ]},
    "02002": {"state": "Baja California", "platform": "transparencia normatividad (mexicali.gob.mx)", "docs": [
        ("Bando de Policia y Gobierno del Municipio de Mexicali, Baja California",
         "http://www.mexicali.gob.mx/transparencia/normatividad/reglamentos/pdf/bandoPoliciayGobierno.pdf"),
    ]},
    "25006": {"state": "Sinaloa", "platform": "official docs host (docs.culiacan.gob.mx)", "docs": [
        ("Bando de Policia, Gobierno y Justicia Civica del Municipio de Culiacan, Sinaloa",
         "https://docs.culiacan.gob.mx/s/5eg7f4e9aoZgRBn/download/Bando%20de%20Polic%C3%ADa%20,%20Gobierno%20Y%20Justicia%20Civica..pdf"),
        ("Reglamento de la Administracion Publica del Municipio de Culiacan, Sinaloa",
         "https://docs.culiacan.gob.mx/s/q5JzMkf72Dwje3s/download/Reglamento%20de%20la%20Administraci%C3%B3n%20P%C3%BAb.%20del%20Mun.%20de%20Cul..pdf"),
    ]},
    "01001": {"state": "Aguascalientes", "platform": "municipal portal transparencia (ags.gob.mx)", "docs": [
        ("Codigo Municipal de Aguascalientes",
         "https://ags.gob.mx/transparencia/art.9/secc1/Municipal/C%C3%93DIGO%20MUNICIPAL%20DE%20AGUASCALIENTES%20A%2018%20DE%20FEBRERO%20DE%202013.pdf"),
    ]},
    "08019": {"state": "Chihuahua", "platform": "municipal portal TransparenciaArchivos (municipiochihuahua.gob.mx)", "docs": [
        ("Bando de Policia y Gobierno del Municipio de Chihuahua",
         "https://www.municipiochihuahua.gob.mx/TransparenciaArchivos/3er%20Trimestre%202018/Secretaria%20del%20Ayuntamiento/Normatividad/I/Reglamentos/Bando%20de%20Polic%C3%ADa%20y%20Gobierno%20del%20Municipio%20de%20Chihuahua.pdf"),
        ("Reglamento Interior del Municipio de Chihuahua",
         "https://www.municipiochihuahua.gob.mx/TransparenciaArchivos/DDHE%20(RETROALIMENTACION%20PNT)/Reglamento%20interior%20del%20municipio%20de%20Chihuahua/REGLAMENTO%20INTERIOR%20DEL%20MUNICIPIO%20DE%20CHIHUAHUA.pdf"),
    ]},
    "26030": {"state": "Sonora", "platform": "municipal portal (hermosillo.gob.mx)", "docs": [
        ("Bando de Policia y Gobierno para el Municipio de Hermosillo, Sonora",
         "https://www.hermosillo.gob.mx/download.aspx?r=/transparencia2014%5Carchivos%5Cleyes%5C&file=BANDO%20DE%20POLIC%C3%8DA%20Y%20GOBIERNO%20PARA%20EL%20MUNICIPIO%20DE%20HERMOSILLO.pdf"),
        ("Reglamento Interno de la Jefatura de Policia y Transito Municipal de Hermosillo",
         "https://www.hermosillo.gob.mx/download.aspx?r=/transparencia2014%5Carchivos%5Cleyes%5C&file=REGLAMENTO%20INTERNO%20DE%20LA%20JEFATURA%20DE%20POLICIA%20Y%20TRANSITO%20MUNCIPAL.pdf"),
    ]},
    "24028": {"state": "San Luis Potosi", "platform": "municipal CMS storage (sitio.sanluis.gob.mx)", "docs": [
        ("Bando de Policia y Gobierno del Municipio de San Luis Potosi, S.L.P.",
         "https://sitio.sanluis.gob.mx/pagAyuntamientoCMS/storage/Medios//2023/09/SLP%20CAPITAL%20BANDO%20DE%20POLICIA%20Y%20GOBIERNO%20(14-SEP-2023).pdf"),
    ]},
    "23005": {"state": "Quintana Roo", "platform": "transparencia portal (transparencia.cancun.gob.mx)", "docs": [
        ("Reglamento del Gobierno Interior del Ayuntamiento del Municipio de Benito Juarez, Quintana Roo",
         "https://transparencia.cancun.gob.mx/uploads/24/40/39%20-%20Reg%20Del%20Gobierno%20Interior%20Del%20Mbj%20-%2031%20Enero%202025.Pdf"),
        ("Reglamento Organico de la Administracion Publica Centralizada del Municipio de Benito Juarez, Quintana Roo",
         "https://transparencia.cancun.gob.mx/uploads/8/42/Reglamento%20Organico%20De%20La%20Administracion%20Publica%20Centralizado.pdf"),
    ]},
    "15106": {"state": "Mexico", "platform": "state legislatura library (legislacion.edomex.gob.mx)", "docs": [
        ("Bando Municipal de Toluca 2026",
         "https://legislacion.edomex.gob.mx/sites/legislacion.edomex.gob.mx/files/files/pdf/bdo/bdo2026/bdo108.pdf"),
    ]},
    "16053": {"state": "Michoacan", "platform": "transparencia archivos (morelos.morelia.gob.mx)", "docs": [
        ("Bando de Gobierno del Municipio de Morelia, Michoacan de Ocampo",
         "https://morelos.morelia.gob.mx/ArchivosTranspMorelia/Art3522/Norm/FraccI/44_bando_de_gobierno_municipio_morelia%20N.pdf"),
        ("Reglamento Interior de la Tesoreria Municipal de Morelia",
         "https://www.morelia.gob.mx/wp-content/uploads/2023/03/REGLAMENTO-INTERIOR-DE-LA-TESORERIA-MUNICIPAL-DE-MORELIA-21-FEBRERO-2023.pdf"),
    ]},
    "31050": {"state": "Yucatan", "platform": "municipal portal (isla.merida.gob.mx) -- ONE retry per brief", "docs": [
        ("Reglamento de Construcciones del Municipio de Merida",
         "https://isla.merida.gob.mx/recursos/normatividad/reglamento_de_construcciones.pdf"),
    ]},
    "12001": {"state": "Guerrero", "platform": "transparencia marco juridico (acapulco.gob.mx)", "docs": [
        ("Bando de Policia y Gobierno del Municipio de Acapulco de Juarez, Guerrero",
         "https://acapulco.gob.mx/transparencia/descargar.php?d=/transparencia/wp-content/uploads/marcojuridico/reglamentos/Bando_Policia_y_Gobierno_12jun2026.pdf"),
        ("Reglamento para el Bienestar e Incorporacion Social de las Personas con Discapacidad en el Municipio de Acapulco de Juarez",
         "https://acapulco.gob.mx/transparencia/wp-content/uploads/marcojuridico/reglamentos/Reglamento_Bienestar_e_Incorporacion_Social_de_las_Personas_con_Discapacidad_30mar2022.pdf"),
    ]},
    "14097": {"state": "Jalisco", "platform": "municipal portal transparencia/reglamentos (tlajomulco.gob.mx)", "docs": [
        ("Reglamento del Gobierno y la Administracion Publica del Municipio de Tlajomulco de Zuniga, Jalisco",
         "https://comude.tlajomulco.gob.mx/sites/default/files/documentos/VI-a/Reglamento_Municipal-Inicial.pdf"),
        ("Reglamento del Ayuntamiento del Municipio de Tlajomulco de Zuniga, Jalisco",
         "https://tlajomulco.gob.mx/sites/default/files/transparencia/reglamentos/8IIImarconormativoReglamentoDelAyuntamientoDelMunicipioDeTlajomulcoaprobadoypublicado-07abr22-6tareforma.pdf"),
    ]},
    "14120": {"state": "Jalisco", "platform": "gaceta municipal portal (servicios.zapopan.gob.mx)", "docs": [
        ("Reglamento de Policia, Justicia Civica y Buen Gobierno de Zapopan, Jalisco",
         "https://servicios.zapopan.gob.mx:8000/wwwportal/publicfiles/2022-11/Gaceta%20Vol.%20XXIX%20No.%20265_opt.pdf"),
    ]},
    "15057": {"state": "Mexico", "platform": "municipal portal / gaceta municipal (nuevo.naucalpan.gob.mx)", "docs": [
        ("Bando Municipal de Naucalpan de Juarez 2025 (Gaceta Municipal No. 5)",
         "https://nuevo.naucalpan.gob.mx/wp-content/uploads/2025/02/Gaceta-Municipal-No.-5-05-febrero-2025.pdf"),
    ]},
    "10005": {"state": "Durango", "platform": "municipal portal (municipiodurango.gob.mx)", "docs": [
        ("Bando de Policia y Gobierno de Durango",
         "https://www.municipiodurango.gob.mx/wp-content/uploads/2025/08/BANDO-1.pdf"),
    ]},
    "27004": {"state": "Tabasco", "platform": "transparencia portal (villahermosa.gob.mx)", "docs": [
        ("Bando de Policia y Gobierno del Municipio de Centro, Tabasco",
         "https://transparenciafiscal.villahermosa.gob.mx:8090/images/documentos/MarcoRegulatorio/1_BPGMC_2022.pdf"),
        ("Reglamento de la Administracion Publica del Municipio de Centro, Tabasco",
         "https://transparencia.villahermosa.gob.mx/doctos/files/2022/administracion/ley/RAPMC.pdf"),
    ]},
    "15031": {"state": "Mexico", "platform": "municipal portal (chimalhuacan.gob.mx)", "docs": [
        ("Bando Municipal de Chimalhuacan 2025",
         "https://chimalhuacan.gob.mx/wp-content/uploads/BANDO-MUNICIPAL-2025.pdf"),
    ]},
    "22014": {"state": "Queretaro", "platform": "SIMCOD / SER normatividad (ser.municipiodequeretaro.gob.mx)", "docs": [
        ("Reglamento de Proteccion Ambiental y Cambio Climatico del Municipio de Queretaro",
         "https://ser.municipiodequeretaro.gob.mx/ser/normatividad/paramunicipal/paramunicipal05.pdf"),
    ]},
    "05035": {"state": "Coahuila", "platform": "normatividad portal (torreon.gob.mx)", "docs": [
        ("Reglamento Organico del Municipio de Torreon, Coahuila de Zaragoza",
         "https://www.torreon.gob.mx/normatividad/pdf/reglamento_95.pdf"),
        ("Reglamento de Turismo del Municipio de Torreon, Coahuila",
         "https://www.torreon.gob.mx/normatividad/pdf/reglamento_103.pdf"),
    ]},
}


def fetch(url, dest, max_time=180):
    t0 = time.monotonic()
    p = subprocess.run(["curl", "-sS", "-L", "--max-time", str(max_time), "-A", UA,
                        "-o", str(dest), "-w", "%{http_code}", url],
                       capture_output=True, timeout=max_time + 30)
    code = p.stdout.decode().strip()
    size = dest.stat().st_size if dest.exists() else 0
    head = dest.read_bytes()[:5] if size else b""
    return {"status": int(code) if code.isdigit() else 0, "bytes": size,
            "is_pdf": head == b"%PDF-", "seconds": round(time.monotonic() - t0, 1)}


def robots_status(base):
    try:
        p = subprocess.run(["curl", "-s", "--max-time", "30", "-A", UA,
                            "-o", "/dev/null", "-w", "%{http_code}",
                            base + "/robots.txt"], capture_output=True, timeout=40)
        return int(p.stdout.decode().strip() or 0)
    except Exception:  # noqa: BLE001
        return 0


def extract_text(pdf_path):
    """PyMuPDF (streaming) -> pdfplumber -> pdftotext -> tesseract spa.

    NOTE: pdfplumber-first (the AU order) OOM-killed this builder on the
    1,139-page COREMUN PDF in a 8 GB VM (2026-10-14); fitz streams pages
    at a fraction of the memory and its text layer is equivalent for
    these born-digital gazette PDFs. pdfplumber remains the fallback.
    """
    try:
        import fitz
        doc = fitz.open(pdf_path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        if len(text.strip()) >= 200:
            return text, "fitz"
    except Exception:  # noqa: BLE001
        pass
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        if len(text.strip()) >= 200:
            return text, "pdfplumber"
    except Exception:  # noqa: BLE001
        pass
    try:
        out = subprocess.run(["pdftotext", "-layout", str(pdf_path), "-"],
                             capture_output=True, timeout=600)
        text = out.stdout.decode("utf-8", "replace")
        if len(text.strip()) >= 200:
            return text, "pdftotext"
    except Exception:  # noqa: BLE001
        pass
    try:
        import fitz
        doc = fitz.open(pdf_path)
        pages = []
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=200)
            img = SCRATCH / f"{pdf_path.stem}_p{i}.png"
            pix.save(img)
            o = subprocess.run(["tesseract", str(img), "stdout", "-l", "spa"],
                               capture_output=True, timeout=300)
            pages.append(o.stdout.decode("utf-8", "replace"))
            img.unlink(missing_ok=True)
        doc.close()
        return "\n".join(pages), "tesseract"
    except Exception:  # noqa: BLE001
        return "", "failed"


ART_START = re.compile(
    r"^\s*[\u2022\u00b7\u25aa\u2023\-*]?\s*Art[íi]culo\s+(\d{1,4})\s*(?:o|º|°)?\s*(BIS|TER|QU[ÁA]TER)?\s*[.\-–—]?\s*(.*)$",
    re.IGNORECASE)
TRANS_START = re.compile(r"^\s*(TRANSITORIOS?|ART[ÍI]CULOS?\s+TRANSITORIOS?)\b", re.IGNORECASE)


def slugify_es(text):
    s = text.lower()
    s = (s.replace("á", "a").replace("é", "e").replace("í", "i")
          .replace("ó", "o").replace("ú", "u").replace("ñ", "n").replace("ü", "u"))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def split_articles(text):
    """Split a reglamento into (label, body) units at 'Articulo N' starts.

    Text before the first article becomes a preamble unit. A trailing
    TRANSITORIOS block becomes its own unit.
    """
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    units = []  # (label, [lines])
    cur_label, cur = None, []
    in_trans = False
    for ln in lines:
        # Article starts always split (a code with per-book numbering
        # restarts at "Articulo 1" after each book's Transitorios block).
        m = ART_START.match(ln)
        if m:
            if cur_label is not None or any(x.strip() for x in cur):
                units.append((cur_label, cur))
            num = m.group(1)
            suf = (m.group(2) or "").upper()
            cur_label = f"Articulo {num}" + (f" {suf}" if suf else "")
            rest = (m.group(3) or "").strip()
            cur = [f"Articulo {num}" + (f" {suf}" if suf else "") + (f". {rest}" if rest else ".")]
            in_trans = False
            continue
        if TRANS_START.match(ln) and not in_trans:
            if cur_label is not None or any(x.strip() for x in cur):
                units.append((cur_label, cur))
            cur_label, cur, in_trans = "Transitorios", [ln], True
            continue
        cur.append(ln)
    if cur_label is not None or any(x.strip() for x in cur):
        units.append((cur_label, cur))
    out = []
    for label, ulines in units:
        body = "\n".join(ulines).strip()
        if len(body) < 30:
            if out:
                out[-1] = (out[-1][0], out[-1][1] + "\n" + body)
            continue
        out.append((label or "Preambulo", body))
    return out


def build_municipio(code, registry):
    name = registry[code]
    jid = MX.normalize(code)
    cfg = MUNICIPIOS[code]
    t_start = time.monotonic()
    rows, docs = [], []
    for title, url in cfg["docs"]:
        slug = slugify_es(title)[:70]
        stem = f"mx_{code}_" + slug[:50]
        dest = SCRATCH / f"{stem}.pdf"
        f = fetch(url, dest)
        rec = {"title": title, "source_url": url, "fetch": f}
        if not f["is_pdf"]:
            rec["error"] = f"fetch status {f['status']}, not a PDF"
            docs.append(rec)
            print(f"[{code}] FAIL {title}: {rec['error']}", flush=True)
            continue
        text, method = extract_text(dest)
        units = split_articles(text)
        if len(units) < 2:
            units = [("Documento completo", text.strip())] if len(text.strip()) >= 200 else []
        made = 0
        for label, unit in units:
            body_html = "".join(
                f"<p>{html_mod.escape(p.strip())}</p>"
                for p in re.split(r"\n\s*\n|\n", unit) if p.strip())
            rows.append(make_row(
                jurisdiction_id=jid, jurisdiction_name=name, country="MX",
                doc_id=f"{slug}#{label}", title=title,
                structural_path=title, node_label=label,
                body_html=body_html, source_url=url, retrieved=RETRIEVED))
            made += 1
        rec.update({"method": method, "chars": len(text), "units": made})
        docs.append(rec)
        print(f"[{code}] {title}: {method}, {len(text)} chars, {made} rows, "
              f"fetch {f['seconds']}s", flush=True)
        time.sleep(2)
    rows = finalize_rows(drop_empty_rows(rows))
    if not rows:
        return {"code": jid, "name": name, "docs": docs, "rows": 0,
                "error": "no rows built"}
    table = rows_to_table(rows)
    errors = validate_table(table, jurisdiction_id=jid, jurisdiction_name=name, country="MX")
    if errors:
        return {"code": jid, "name": name, "docs": docs, "rows": len(rows),
                "error": f"VALIDATION FAILED: {errors}"}
    pq = DATA / f"{jid}_html.parquet"
    write_html_parquet(pq, table)
    back = read_html_parquet(pq)
    errors2 = validate_table(back, jurisdiction_id=jid, jurisdiction_name=name, country="MX")
    if errors2:
        return {"code": jid, "name": name, "docs": docs, "rows": len(rows),
                "error": f"RE-READ VALIDATION FAILED: {errors2}"}
    rep = validation_report(back, jurisdiction_id=jid, jurisdiction_name=name, country="MX")
    write_validation_report(DATA / f"{jid}_validation.json", rep)
    return {"code": jid, "name": name, "state": cfg["state"], "platform": cfg["platform"],
            "docs": docs, "rows": len(rows),
            "wall_seconds": round(time.monotonic() - t_start, 1),
            "parquet": pq.name, "valid": True}


def main():
    registry = {}
    for ln in (DATA / "jurisdictions.jsonl").read_text().splitlines():
        r = json.loads(ln)
        registry[r["jurisdiction_id"]] = r["jurisdiction_name"]
    codes = sys.argv[1:] or list(MUNICIPIOS)
    mpath = OUT / "run_manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {"retrieved": RETRIEVED, "municipios": {}}
    for code in codes:
        try:
            manifest["municipios"][code] = build_municipio(code, registry)
        except Exception as exc:  # noqa: BLE001
            manifest["municipios"][code] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"[{code}] BUILD FAILED: {exc}", flush=True)
        mpath.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(json.dumps({k: (v.get("rows"), v.get("error")) for k, v in manifest["municipios"].items()}, indent=1))


if __name__ == "__main__":
    main()
