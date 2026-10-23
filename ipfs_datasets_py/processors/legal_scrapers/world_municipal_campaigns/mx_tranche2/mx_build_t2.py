"""Mexico tranche 2 — harvest + build (checkpointed per municipio).

Cloned from the tranche-1 builder (mx_tranche1/scripts/mx_build_t1.py) 2026-10-14;
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

MUNICIPIOS = {
    "30193": {"state": "Veracruz", "platform": "gobierno abierto portal (gobiernoabierto.veracruzmunicipio.gob.mx)", "docs": [
        ("Bando de Gobierno para el Municipio de Veracruz, Veracruz de Ignacio de la Llave",
         "https://gobiernoabierto.veracruzmunicipio.gob.mx/wp-content/uploads/2026/07/BANDO-DE-GOBIERNO-ULTIMA-REFORMA.pdf"),
    ]},
    "02001": {"state": "Baja California", "platform": "transparencia portal (transparencia.ensenada.gob.mx)", "docs": [
        ("Bando de Policia y Gobierno para el Municipio de Ensenada, Baja California (texto vigente 2021)",
         "http://transparencia.ensenada.gob.mx/doc/file53140s167d87.pdf"),
    ]},
    "10007": {"state": "Durango", "platform": "transparencia portal (transparencia.gomezpalacio.gob.mx)", "docs": [
        ("Bando de Policia y Gobierno de Gomez Palacio, Durango",
         "https://transparencia.gomezpalacio.gob.mx/wp-content/uploads/2023/05/BANDO-DE-POLICIA-Y-BUEN-GOBIERNO-GOMEZ-PALACIO-MARZO-2021.pdf"),
        ("Reglamento Interior del Republicano Ayuntamiento de Gomez Palacio, Durango",
         "https://transparencia.gomezpalacio.gob.mx/wp-content/uploads/2023/05/REGLAMENTO-INTERIOR-DEL-REPUBLICACO-AYUNTAMIENTO-DE-GOMEZ-PALACIO-DURANGO.pdf"),
    ]},
    "13048": {"state": "Hidalgo", "platform": "datos abiertos portal (datos.pachuca.gob.mx)", "docs": [
        ("Bando de Policia y Gobierno del Municipio de Pachuca de Soto, Hidalgo (Decreto Municipal Numero 4)",
         "https://datos.pachuca.gob.mx/transparencia/4/PDFS/decreto_bando.pdf"),
        ("Gaceta Municipal de Pachuca de Soto, Hidalgo No. 45 extraordinaria (30-nov-2023)",
         "https://datos.pachuca.gob.mx/sipot/IIa/PDFS/Gaceta_Municipal_45_2023.pdf"),
    ]},
    "16102": {"state": "Michoacan", "platform": "transparencia portal (transparenciauruapan.gob.mx)", "docs": [
        ("Bando de Gobierno Municipal de Uruapan, Michoacan de Ocampo",
         "https://transparenciauruapan.gob.mx/wp-content/uploads/2020/10/1.-Bando-de-Gobierno-Municipal.pdf"),
        ("Reglamento de Seguridad Publica, Transito y Vialidad Municipal de Uruapan, Michoacan",
         "https://transparenciauruapan.gob.mx/wp-content/uploads/2021/05/Reglamento-de-Seguridad.pdf"),
    ]},
    "18017": {"state": "Nayarit", "platform": "municipal portal cuadro normativo (tepic.gob.mx)", "docs": [
        ("Reglamento de Policia y Buen Gobierno para el Municipio de Tepic, Nayarit (texto vigente)",
         "http://www.tepic.gob.mx/assets/img/galerias/cnormativas/16.- 1511807577_policia_y_buen_gobierno_para_el_municipio_de_tepic,_nayarit_(reglamento_de).pdf"),
    ]},
    "25012": {"state": "Sinaloa", "platform": "tramites portal (mazatlan.tramitessinaloa.gob.mx)", "docs": [
        ("Reglamento de Gobierno del H. Ayuntamiento del Municipio de Mazatlan, Sinaloa",
         "https://mazatlan.tramitessinaloa.gob.mx/Content/Archivos/095113072022REGLAMENTO DE GOBIERNO DEL H AYUNTAMIENTO DEL MUNICIPIO DE MAZATLAN.pdf"),
    ]},
    "14101": {"state": "Jalisco", "platform": "transparencia portal DOCX (portal-transparencia.tonala.gob.mx)", "docs": [
        ("Reglamento del Gobierno y la Administracion Publica del Ayuntamiento de Tonala, Jalisco (Acuerdo 334, 2026)",
         "https://portal-transparencia.tonala.gob.mx/wp-content/uploads/2026/02/ACUERDO-334-REGLAMENTO-DEL-GOBIERNO-Y-LA-ADMINISTRACION-PUBLICA.docx"),
        ("Reglamento de Policia y Buen Gobierno del Municipio de Tonala, Jalisco (Acuerdo 1203, 2024)",
         "https://portal-transparencia.tonala.gob.mx/wp-content/uploads/2024/10/ACUERDO-1203-REGLAMENTO-DE-POLICIA-Y-BUEN-GOBIERNO-DEL-MUNICIPIO-DE-TONALA-JALISCO.docx"),
    ]},
    "11007": {"state": "Guanajuato", "platform": "marco normativo via state normatividad system (celaya.gob.mx links)", "docs": [
        ("Bando de Policia y Buen Gobierno del Municipio de Celaya, Guanajuato (vigente dic 2020)",
         "https://normatividadestatalymunicipal.guanajuato.gob.mx/descarga_file.php?nombre=Bando%20De%20Polic%C3%ADa%20Y%20Buen%20Gobierno%20Del%20Municipio%20De%20Celaya,%20Guanajuato%20(dic%202020)%20vigente.pdf&archivo=488e4104520c6aab692863cc1dba45af.pdf&id_archivo=6629"),
        ("Reglamento de Administracion para el Municipio de Celaya, Guanajuato",
         "https://docs.google.com/document/d/1Iqu6P4y8YH6K92rKQk-9W9L1fphHyOju/export?format=pdf"),
    ]},
    "11017": {"state": "Guanajuato", "platform": "transparencia leyes host (77-hgo.irapuato.gob.mx)", "docs": [
        ("Bando de Policia y Buen Gobierno del Municipio de Irapuato, Guanajuato",
         "https://77-hgo.irapuato.gob.mx/transparencia/leyes/lrd/Reglamentos2025/1. Bando de Policía y Buen Gobienro del Municpio de  Irapuato, Gto.pdf"),
    ]},
    "25001": {"state": "Sinaloa", "platform": "transparencia reglamentos directory (transparencia.ahome.gob.mx)", "docs": [
        ("Bando de Policia y Gobierno del Municipio de Ahome, Sinaloa (Decreto Municipal No. 30)",
         "https://transparencia.ahome.gob.mx/aip/Reglamentos_Municipales_2018/BANDO DE POLICÍA Y GOBIERNO DEL MUNICIPIO DE AHOME/DECRETO MUNICIPAL No. 30 BANDO DE POLICIA Y GOBIERNO.pdf"),
        ("Reglamento Interior de la Administracion Publica de Ahome, Sinaloa (Decreto Municipal No. 31)",
         "https://transparencia.ahome.gob.mx/aip/Reglamentos_Municipales_2018/REGLAMENTO INTERIOR DE LA ADMINISTRACIÓN PÚBLICA/DECRETO MUNICIPAL Nº 31 REGLAMENTO INTERIOR DE LA ADMINISTRACIÓN PÚBLICA.pdf"),
    ]},
    "30087": {"state": "Veracruz", "platform": "paramunicipal CMAS gobierno abierto mirror (cmasxalapa.gob.mx); xalapa.gob.mx unreachable from this egress", "docs": [
        ("Bando de Policia y Gobierno del Municipio de Xalapa, Veracruz (ultima reforma G.O. 20-ene-2016)",
         "https://cmasxalapa.gob.mx/gobiernoabierto/info/b1/Bando_de_Policia_y_Buen_Gobierno.pdf"),
    ]},
    "28041": {"state": "Tamaulipas", "platform": "municipal portal (ciudadvictoria.gob.mx)", "docs": [
        ("Reglamento de Justicia Civica del Municipio de Victoria, Tamaulipas",
         "http://www.ciudadvictoria.gob.mx/wp-content/uploads/2026/02/REGLAMENTO-DE-JUSTICIA-CIVICA.pdf"),
    ]},
    "14098": {"state": "Jalisco", "platform": "comunicacion portal files (comucat.tlaquepaque.gob.mx)", "docs": [
        ("Reglamento del Gobierno y de la Administracion Publica del Ayuntamiento Constitucional de San Pedro Tlaquepaque, Jalisco",
         "https://comucat.tlaquepaque.gob.mx/files/topics/16463338863759.pdf"),
    ]},
    "16108": {"state": "Michoacan", "platform": "municipal portal gaceta (zamora.gob.mx)", "docs": [
        ("Gaceta Municipal de Zamora de Hidalgo, Michoacan No. 2 (2024-2027)",
         "https://www.zamora.gob.mx/wp-content/uploads/2024/10/2024-2027-Gaceta-No-2.pdf"),
    ]},
    "17007": {"state": "Morelos", "platform": "mejora regulatoria portal dmer (cuernavaca.gob.mx)", "docs": [
        ("Reglamento de Gobierno y de la Administracion Publica Municipal de Cuernavaca, Morelos",
         "https://www.cuernavaca.gob.mx/dmer/wp-content/uploads/2019/12/1-Reglamento-de-Gobierno.pdf"),
    ]},
    "11020": {"state": "Guanajuato", "platform": "normatividad municipal portal (normatividadmunicipal.leon.gob.mx)", "docs": [
        ("Reglamento de Policia y Vialidad para el Municipio de Leon, Guanajuato",
         "https://normatividadmunicipal.leon.gob.mx/archivos/Reglamento_de_Polica_y_Vialidad_para_el_-945705416-detreg-142.pdf"),
    ]},
    "02002": {"state": "Baja California", "platform": "transparencia normatividad (mexicali.gob.mx)", "docs": [
        ("Bando de Policia y Gobierno del Municipio de Mexicali, Baja California",
         "http://www.mexicali.gob.mx/transparencia/normatividad/reglamentos/pdf/bandoPoliciayGobierno.pdf"),
    ]},
}


def enc_url(url):
    """Percent-encode spaces/accents in portal URLs (several t2 hosts
    publish filenames with literal spaces, e.g. Irapuato, Tepic)."""
    from urllib.parse import urlparse, quote
    p = urlparse(url)
    path = quote(p.path, safe="/%:@&=+$,~*'()[]-._")
    q = ("?" + quote(p.query, safe="=&%+,-._~")) if p.query else ""
    return f"{p.scheme}://{p.netloc}{path}{q}"


def fetch(url, dest, max_time=180):
    t0 = time.monotonic()
    p = subprocess.run(["curl", "-sS", "-L", "--max-time", str(max_time), "-A", UA,
                        "-o", str(dest), "-w", "%{http_code}", enc_url(url)],
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
        is_docx = url.lower().split("?")[0].endswith(".docx")
        dest = SCRATCH / f"{stem}.docx" if is_docx else SCRATCH / f"{stem}.pdf"
        f = fetch(url, dest)
        rec = {"title": title, "source_url": url, "fetch": f}
        if is_docx:
            # Tonala publishes compiled reglamentos as DOCX on its own
            # transparencia portal; convert with LibreOffice headless and
            # run the identical PDF pipeline on the conversion.
            head = dest.read_bytes()[:2] if f["bytes"] else b""
            if head != b"PK":
                rec["error"] = f"fetch status {f['status']}, not a DOCX (zip)"
                docs.append(rec)
                print(f"[{code}] FAIL {title}: {rec['error']}", flush=True)
                continue
            conv = subprocess.run(
                ["soffice", "--headless", "--convert-to", "pdf", "--outdir",
                 str(SCRATCH), str(dest)], capture_output=True, timeout=300)
            pdf_dest = SCRATCH / f"{stem}.pdf"
            if conv.returncode != 0 or not pdf_dest.exists():
                rec["error"] = "DOCX->PDF conversion failed"
                docs.append(rec)
                print(f"[{code}] FAIL {title}: {rec['error']}", flush=True)
                continue
            rec["converted_from"] = "docx (LibreOffice headless)"
            dest = pdf_dest
            f = {**f, "is_pdf": True}
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
