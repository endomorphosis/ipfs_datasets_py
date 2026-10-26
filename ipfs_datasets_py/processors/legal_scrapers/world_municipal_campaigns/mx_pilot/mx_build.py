"""Mexico pilot — harvest + build (checkpointed per municipio).

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
    "19039": {"state": "Nuevo Leon", "platform": "municipal portal /pdf/reglamentos/", "docs": [
        ("Reglamento para las Construcciones del Municipio de Monterrey",
         MTY + "1/Reglamento_para_las_Construcciones_del_Municipio_de_Monterrey.pdf"),
        ("Reglamento de la Administracion Publica Municipal de Monterrey",
         MTY + "Reg_admon_publica.pdf"),
        ("Reglamento de Zonificacion y Uso de Suelo del Municipio de Monterrey",
         MTY + "1/Reglamento_de_Zonificacion_y_Uso_de_Suelo_del_Municipio_de_Monterrey.pdf"),
        ("Reglamento para Regular el Acceso Vial y Mejorar la Seguridad de los Vecinos en el Municipio de Monterrey",
         MTY + "1/51%20Reglamento%20para%20Regular%20el%20Acceso%20Vial%20y%20Mejorar%20la%20Seguridad%20de%20los%20Vecinos.pdf"),
        ("Reglamento Interior de la Secretaria de Seguridad Publica y Vialidad de Monterrey",
         MTY + "1/19ReglamentoInteriordelaSecretariadeSeguridadPublicayVialidad.pdf"),
    ]},
    "21114": {"state": "Puebla", "platform": "Gaceta Municipal pueblacapital (single consolidated code)", "docs": [
        ("Codigo Reglamentario para el Municipio de Puebla (COREMUN)",
         "https://gaceta.pueblacapital.gob.mx/images/COREMUN_Octubre_2022.pdf"),
    ]},
    "02004": {"state": "Baja California", "platform": "municipal portal (Secretaria de Seguridad)", "docs": [
        ("Bando de Policia y Gobierno para el Municipio de Tijuana",
         "https://policia.tijuana.gob.mx/PDF/Reglamentos/bando%20policial%202025.pdf"),
    ]},
    "31050": {"state": "Yucatan", "platform": "normatividad portal (isla.merida.gob.mx)", "docs": [
        ("Reglamento para el Uso y Aprovechamiento del Espacio Publico en el Municipio de Merida",
         "https://isla.merida.gob.mx/serviciosinternet/normatividad/files/Reglamentos/Reglamento_para_el_Uso_y_Aprovechamiento_del_Espacio_Publico-20250717-092043.pdf"),
    ]},
    "14039": {"state": "Jalisco", "platform": "transparencia mirror (DIF Guadalajara, municipal OPD)", "docs": [
        ("Codigo de Gobierno del Municipio de Guadalajara",
         GDL + "14.%20C%C3%B3digo%20de%20Gobierno%20Municipal%20Guadalajara.pdf"),
        ("Reglamento de Patrimonio del Municipio de Guadalajara",
         GDL + "16.%20Reglamento%20de%20Patrimonio%20Municipal%20de%20Guadalajara.pdf"),
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
    r"^\s*Art[íi]culo\s+(\d{1,4})\s*(?:o|º|°)?\s*(BIS|TER|QU[ÁA]TER)?\s*[.\-–—]?\s*(.*)$",
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
