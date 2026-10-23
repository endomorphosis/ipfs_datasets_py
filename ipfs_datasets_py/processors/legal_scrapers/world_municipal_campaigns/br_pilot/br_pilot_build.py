"""Brazil municipal-law pilot — SAPL (Interlegis) template harvest.

Bounded pilot: 4 municípios x up to 5 Leis Ordinarias of 2025 each.
LOCAL ONLY — no uploads. Honors each SAPL instance's robots.txt
(User-agent: * -> Crawl-delay: 60; only /materia/docacessorio/{pdf,zip}
disallowed; /norma/ and /ta/ are allowed).

Normalization: world_municipal 19-column schema. Jurisdiction IDs are
IBGE 7-digit municipality codes (verified against the IBGE localidades
API). NOTE: world_municipal/jurisdiction.py has NO BR scheme registered
(SCHEMES = NL/PT/ES/PL/KR/EU/US) — this script mirrors the closest
registered pattern (INEMunicipioScheme: digit string, zero-padded) at
width 7 locally and flags the gap in the pilot report. The repo file is
NOT modified.
"""
import html as htmlmod
import json
import re
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pyarrow as pa
import requests
from bs4 import BeautifulSoup

REPO = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.normalize import make_row, finalize_rows  # noqa: E402
from world_municipal.schema import rows_to_table, validate_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report  # noqa: E402

OUT = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files" / "br_pilot"
OUT.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
DELAY = 62.0          # robots Crawl-delay: 60 (+2s margin), per host
YEAR = 2025
SAMPLE = 5
RETRIEVED = "2026-10-12"

MUNIS = [
    dict(name="Formosa",     uf="GO", ibge="5208004", host="sapl.formosa.go.leg.br"),
    dict(name="Parauapebas", uf="PA", ibge="1505536", host="sapl.parauapebas.pa.leg.br"),
    dict(name="Capanema",    uf="PR", ibge="4104501", host="sapl.capanema.pr.leg.br"),
    dict(name="Itapoá",      uf="SC", ibge="4208450", host="sapl.itapoa.sc.leg.br"),
]

MONTHS = {"janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4, "maio": 5,
          "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
          "novembro": 11, "dezembro": 12}


def ibge_normalize(code: str) -> str:
    """Closest registered pattern (INE/DICOFRE digit zfill), IBGE width 7."""
    s = str(code).strip()
    if not s.isdigit():
        raise ValueError(f"not an IBGE code: {code!r}")
    return s.zfill(7)


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


class PoliteSession:
    """requests session enforcing per-host crawl-delay between request starts."""

    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(UA)
        self.last_start = 0.0
        self.n_requests = 0
        self.fetch_seconds = 0.0

    def get(self, url, **kw):
        wait = DELAY - (time.monotonic() - self.last_start)
        if self.last_start and wait > 0:
            time.sleep(wait)
        self.last_start = time.monotonic()
        t0 = time.monotonic()
        r = self.s.get(url, timeout=60, **kw)
        dt = time.monotonic() - t0
        self.n_requests += 1
        self.fetch_seconds += dt
        return r, dt


def parse_title_date(title: str):
    m = re.search(r"n[ºo]\s*([\d.]+),\s*de\s*(\d{1,2})\s*de\s*(\w+)\s*de\s*(\d{4})", title)
    if not m:
        return "", ""
    numero = m.group(1).replace(".", "")
    month = MONTHS.get(m.group(3).lower(), 0)
    iso = f"{m.group(4)}-{month:02d}-{int(m.group(2)):02d}" if month else ""
    return numero, iso


def extract_devices(soup: BeautifulSoup):
    """Linear (label, text) device list from a SAPL texto-articulado page."""
    devices = []
    for dptt in soup.select("div.dptt"):
        link = dptt.find("a", class_="dpt-link")
        label = link.get_text(" ", strip=True) if link else ""
        dtxt = dptt.find("div", class_="dtxt")
        text = dtxt.get_text(" ", strip=True) if dtxt else ""
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            devices.append((label, text))
    return devices


def group_articles(devices):
    """Group devices into (node_label, [(label, text), ...]) chunks."""
    chunks = []
    current_label, current = "Preâmbulo", []
    for label, text in devices:
        if re.match(r"Art\.?\s*\d+", label):
            if current:
                chunks.append((current_label, current))
            current_label, current = label, [(label, text)]
        else:
            current.append((label, text))
    if current:
        chunks.append((current_label, current))
    return chunks


def devices_to_html(chunk):
    parts = []
    for label, text in chunk:
        t = f"{label} {text}" if label and not text.startswith(label) else text
        parts.append(f"<p>{htmlmod.escape(t)}</p>")
    return "".join(parts)


def result_rows(soup: BeautifulSoup, tipo_label: str):
    """Extract sampled norma entries from a SAPL search-results page."""
    out, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"^/norma/\d+")):
        title = a.get_text(" ", strip=True)
        if tipo_label and not title.startswith(tipo_label):
            continue
        pk = re.match(r"^/norma/(\d+)", a["href"]).group(1)
        if pk in seen:
            continue
        seen.add(pk)
        block = a.find_parent("tr") or a.parent
        pdf_url = ""
        if block:
            m = block.find("a", href=re.compile(r"/media/sapl/public/normajuridica/"))
            if m:
                pdf_url = m["href"]
        out.append(dict(pk=pk, title=title, pdf_path=pdf_url))
    return out


def harvest(muni: dict) -> dict:
    host, base = muni["host"], f'https://{muni["host"]}'
    ibge = ibge_normalize(muni["ibge"])
    man = dict(muni, ibge=ibge, requests=0, fetch_seconds=0.0, wall_seconds=0.0,
               tipo_options=[], total_found=None, sampled=[], rows=0, errors=[])
    t_start = time.monotonic()
    sess = PoliteSession()
    try:
        # 1. search form -> this instance's own tipo id for Lei Ordinaria
        r, _ = sess.get(f"{base}/norma/pesquisar")
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        sel = soup.find("select", attrs={"name": "tipo"})
        lei_id = None
        if sel:
            for opt in sel.find_all("option"):
                if not opt.get("value"):
                    continue
                label = opt.get_text(strip=True)
                man["tipo_options"].append((opt["value"], label))
                if strip_accents(label).lower() == "lei ordinaria":
                    lei_id = opt["value"]
        if lei_id is None:
            man["errors"].append("no 'Lei Ordinaria' tipo option in search form")
            return man

        # 2. results for YEAR. The 'pesquisar' submit param is required for
        #    the filters to bind on some instances; a client-side year check
        #    on the parsed law date is applied regardless (run 1 showed the
        #    ano filter silently ignored on 2 of 4 instances without it).
        entries, seen_pk = [], set()
        man["pages_scanned"] = 0
        for page in (1, 2):
            r, _ = sess.get(f"{base}/norma/pesquisar",
                            params={"tipo": lei_id, "ano": YEAR,
                                    "pesquisar": "", "page": page})
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            if page == 1:
                m = re.search(r"Foram encontradas\s*([\d.]+)\s*normas",
                              soup.get_text(" "))
                man["total_found"] = int(m.group(1).replace(".", "")) if m else None
            man["pages_scanned"] = page
            for e in result_rows(soup, "Lei Ordinária"):
                if e["pk"] in seen_pk:
                    continue
                seen_pk.add(e["pk"])
                _, iso = parse_title_date(e["title"])
                if iso.startswith(str(YEAR)):
                    entries.append(e)
            if len(entries) >= SAMPLE:
                break
        entries = entries[:SAMPLE]
        if not entries:
            man["errors"].append("no 2025 Lei Ordinaria rows parsed in 2 pages")
            return man

        # 3. per-norma articulated text
        rows = []
        for e in entries:
            numero, iso_date = parse_title_date(e["title"])
            info = dict(pk=e["pk"], title=e["title"], numero=numero,
                        date=iso_date, rows=0, source_url="", mode="")
            try:
                r, _ = sess.get(f"{base}/norma/{e['pk']}")
                info["source_url"] = r.url
                ta_soup = BeautifulSoup(r.text, "html.parser")
                devices = extract_devices(ta_soup)
                chunks = group_articles(devices) if devices else []
                chunks = [(lab, ch) for lab, ch in chunks
                          if any(t.strip() for _, t in ch)]
                if chunks:
                    info["mode"] = "ta-html"
                    for i, (lab, ch) in enumerate(chunks):
                        suffix = "preambulo" if lab == "Preâmbulo" else f"art{i}"
                        rows.append(make_row(
                            jurisdiction_id=ibge,
                            jurisdiction_name=muni["name"],
                            country="BR",
                            doc_id=f"br-{ibge}-{e['pk']}-{suffix}",
                            regeling_id=f"sapl:{host}:norma-{e['pk']}",
                            title=e["title"],
                            structural_path=e["title"],
                            node_label=lab,
                            body_html=devices_to_html(ch),
                            source_url=r.url,
                            date_effective=iso_date,
                            retrieved=RETRIEVED,
                            tipo="Lei Ordinária",
                        ))
                        info["rows"] += 1
                else:
                    raise ValueError("no TA devices parsed")
            except Exception as exc:
                # fallback: original-text PDF via the existing PDF chain
                if e["pdf_path"]:
                    try:
                        import fitz
                        rp, _ = sess.get(base + e["pdf_path"])
                        doc = fitz.open(stream=rp.content, filetype="pdf")
                        text = "\n".join(p.get_text() for p in doc).strip()
                        if text:
                            info["mode"] = "pdf-fallback"
                            info["source_url"] = base + e["pdf_path"]
                            rows.append(make_row(
                                jurisdiction_id=ibge,
                                jurisdiction_name=muni["name"],
                                country="BR",
                                doc_id=f"br-{ibge}-{e['pk']}-doc",
                                regeling_id=f"sapl:{host}:norma-{e['pk']}",
                                title=e["title"],
                                structural_path=e["title"],
                                node_label=e["title"],
                                body_html="<pre>" + htmlmod.escape(text) + "</pre>",
                                source_url=base + e["pdf_path"],
                                date_effective=iso_date,
                                retrieved=RETRIEVED,
                                tipo="Lei Ordinária",
                            ))
                            info["rows"] = 1
                        else:
                            info["mode"] = f"failed: {exc}; pdf empty"
                    except Exception as exc2:
                        info["mode"] = f"failed: {exc}; pdf: {exc2}"
                else:
                    info["mode"] = f"failed: {exc}"
            man["sampled"].append(info)

        # 4. normalize + fail-closed validation + local parquet
        rows = finalize_rows(rows)
        table = rows_to_table(rows, extra_columns=[("tipo", pa.string())])
        errors = validate_table(table, jurisdiction_id=ibge,
                                jurisdiction_name=muni["name"], country="BR")
        man["validation_errors"] = errors
        report = validation_report(table, jurisdiction_id=ibge,
                                   jurisdiction_name=muni["name"], country="BR")
        write_validation_report(OUT / f"{ibge}_validation.json", report)
        if errors:
            man["errors"].append(f"validation FAILED: {errors}")
        else:
            n = write_html_parquet(OUT / f"{ibge}_html.parquet", table)
            man["rows"] = n
    except Exception as exc:
        man["errors"].append(f"harvest failed: {exc!r}")
    finally:
        man["requests"] = sess.n_requests
        man["fetch_seconds"] = round(sess.fetch_seconds, 1)
        man["wall_seconds"] = round(time.monotonic() - t_start, 1)
    return man


def main():
    results = {}
    with ThreadPoolExecutor(max_workers=len(MUNIS)) as ex:
        for muni, man in zip(MUNIS, ex.map(harvest, MUNIS)):
            results[muni["name"]] = man
            print(json.dumps({k: man[k] for k in
                              ("name", "total_found", "rows", "requests",
                               "fetch_seconds", "wall_seconds", "errors")},
                             ensure_ascii=False), flush=True)
    (OUT / "run_manifest.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print("manifest ->", OUT / "run_manifest.json", flush=True)


if __name__ == "__main__":
    main()
