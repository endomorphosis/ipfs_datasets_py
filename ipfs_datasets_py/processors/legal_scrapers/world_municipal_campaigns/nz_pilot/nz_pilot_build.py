"""New Zealand municipal-law pilot — per-council bylaw PDF harvest.

Adopt-first pilot: 5 councils x up to 4 bylaws, harvested from the PDFs
the councils publish on their own websites (no aggregator carries NZ
council bylaws: NZLII coverage is minimal and NZLII is Cloudflare-walled
from this egress; legislation.govt.nz does not cover council bylaws).

Route verification (live, 2026-10-12, from this VM):
- LGNZ (lgnz.co.nz) robots: Allow /, Disallow /admin/ only.
- Wellington (wellington.govt.nz): robots Allow / (Disallow /search/,
  /~/search/, epetition signatures). Bylaws index lists 11 bylaw detail
  pages (Sitecore); each detail page links its bylaw PDF.
- Hamilton (hamilton.govt.nz): robots "Allow: /" only. One bylaws page
  with 14 direct PDF links (Silverstripe).
- Tauranga (tauranga.govt.nz): policies-and-bylaws page (DNN) mixes
  policies and bylaws; bylaw PDFs live under
  /Portals/0/data/council/bylaws/files/.
- Selwyn (selwyn.govt.nz): robots Disallow /*?*result_page=* only.
  current-bylaws page lists ~14 PDFs under current-bylaw-files/.
- Hastings (hastingsdc.govt.nz): robots Crawl-delay 5 -> this script
  self-imposes 6.5 s between requests for every council.
- Dead ends from this egress (documented, not harvested): Auckland
  Council 406 on every request; Christchurch (ccc.govt.nz) Incapsula
  challenge stub; Palmerston North 403; Whangarei (wdc.govt.nz) 403;
  Invercargill, Nelson, Rotorua HTTP 202 WAF pages.

Jurisdiction IDs: Stats NZ TA2023 3-digit codes for territorial
authorities; "R" + ISO 3166-2:NZ for the 11 regional councils —
registered this pilot as world_municipal NzStatsScheme (NZ) in the repo
working tree (local only, no commit/push; suite 38 -> 39 tests, all
pass). Registry of all 78 councils (67 TA + 11 RC) in
jurisdictions.jsonl alongside this script, count-verified in code.

Normalization: world_municipal 19-column schema. One row per bylaw
clause-level unit split from the extracted PDF text (numbered clauses /
PART headings; page-level fallback). PDF text chain: PyMuPDF (fitz) ->
pdfplumber -> pdftotext -> tesseract OCR (eng).
"""
import html as html_mod
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, unquote

import requests
from bs4 import BeautifulSoup

REPO = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.normalize import make_row, finalize_rows, drop_empty_rows  # noqa: E402
from world_municipal.schema import rows_to_table, validate_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report, read_html_parquet  # noqa: E402
from world_municipal.jurisdiction import get_scheme  # noqa: E402

OUT = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files" / "nz_pilot"
OUT.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 world-municipal-law-pilot/0.1"}
DELAY = 6.5            # Hastings robots Crawl-delay is 5; stay above it everywhere
SAMPLE = 4             # bylaws per council
RETRIEVED = "2026-10-12"
NZ = get_scheme("NZ")

# code -> (jurisdiction_name, index_url, discovery kind)
COUNCILS = {
    "047": ("Wellington City", "https://wellington.govt.nz/your-council/plans-policies-and-bylaws/bylaws", "wellington"),
    "016": ("Hamilton City", "https://hamilton.govt.nz/your-council/policies-bylaws-and-legislation/bylaws", "hamilton"),
    "023": ("Tauranga City", "https://www.tauranga.govt.nz/Council/Policies-and-bylaws", "tauranga"),
    "030": ("Hastings District", "https://www.hastingsdc.govt.nz/documents-and-forms/bylaws/", "hastings"),
    "062": ("Selwyn District", "https://www.selwyn.govt.nz/your-council/bylaws/current-bylaws", "selwyn"),
}


class PoliteSession:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(UA)
        # The egress proxy intermittently stalls pooled keep-alive
        # connections; one connection per request is slower but reliable.
        self.s.headers.update({"Connection": "close"})
        self.last_start = 0.0
        self.n_requests = 0
        self.fetch_seconds = 0.0

    def get(self, url, timeout=180):
        wait = DELAY - (time.monotonic() - self.last_start)
        if self.last_start and wait > 0:
            time.sleep(wait)
        last_exc = None
        for attempt in range(3):
            if attempt:
                time.sleep(5 * attempt)
            self.last_start = time.monotonic()
            t0 = time.monotonic()
            try:
                r = self.s.get(url, timeout=timeout)
                self.fetch_seconds += time.monotonic() - t0
                self.n_requests += 1
                r.raise_for_status()
                print(f"  GET {r.status_code} {len(r.content)}B "
                      f"{round(time.monotonic() - t0, 1)}s {url[:110]}", flush=True)
                return r
            except Exception as exc:  # noqa: BLE001
                self.fetch_seconds += time.monotonic() - t0
                self.n_requests += 1
                print(f"  GET FAIL {type(exc).__name__} {url[:110]}", flush=True)
                last_exc = exc
        raise last_exc

    def get_bytes(self, url, timeout=120):
        """Streamed download with Range-resume for large PDFs.

        The egress proxy intermittently drops long-lived transfers;
        resuming from the byte offset survives drops that a one-shot
        GET does not.
        """
        wait = DELAY - (time.monotonic() - self.last_start)
        if self.last_start and wait > 0:
            time.sleep(wait)
        buf = bytearray()
        last_exc = None
        for attempt in range(8):
            if attempt:
                time.sleep(4)
            self.last_start = time.monotonic()
            t0 = time.monotonic()
            headers = {"Range": f"bytes={len(buf)}-"} if buf else {}
            try:
                with self.s.get(url, timeout=timeout, stream=True,
                                headers=headers) as r:
                    self.n_requests += 1
                    if r.status_code == 200 and buf:
                        buf = bytearray()  # server ignored Range; restart
                    r.raise_for_status()
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            buf.extend(chunk)
                self.fetch_seconds += time.monotonic() - t0
                print(f"  GETBYTES {len(buf)}B {round(time.monotonic() - t0, 1)}s "
                      f"{url[:100]}", flush=True)
                return bytes(buf)
            except Exception as exc:  # noqa: BLE001
                self.fetch_seconds += time.monotonic() - t0
                self.n_requests += 1
                print(f"  GETBYTES FAIL {type(exc).__name__} at {len(buf)}B "
                      f"{url[:100]}", flush=True)
                last_exc = exc
        raise last_exc


def pdf_links(page_url, html_text, must_contain=()):
    soup = BeautifulSoup(html_text, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ".pdf" not in href.lower():
            continue
        if any(m not in href for m in must_contain):
            continue
        full = urljoin(page_url, href)
        if full in seen:
            continue
        seen.add(full)
        out.append((full, a.get_text(" ", strip=True)))
    return out


def discover(sess, code):
    """Return up to SAMPLE (pdf_url, link_text) pairs in page order."""
    _name, index_url, kind = COUNCILS[code]
    if kind == "wellington":
        r = sess.get(index_url)
        soup = BeautifulSoup(r.text, "html.parser")
        details, seen = [], set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            full = urljoin(index_url, href)
            if "/bylaws/" in full and full.rstrip("/") != index_url.rstrip("/") \
                    and ".pdf" not in full.lower() and full not in seen:
                seen.add(full)
                details.append(full)
        out = []
        for d in details:
            if len(out) >= SAMPLE:
                break
            dr = sess.get(d)
            links = pdf_links(d, dr.text, must_contain=("bylaws/files",))
            if not links:
                links = pdf_links(d, dr.text)
            if links:
                out.append(links[0])
        return out
    r = sess.get(index_url)
    if kind == "hamilton":
        links = pdf_links(index_url, r.text, must_contain=("/assets/Uploads/Documents/Bylaws/",))
    elif kind == "tauranga":
        links = pdf_links(index_url, r.text, must_contain=("/Portals/0/data/council/bylaws/files/",))
    elif kind == "selwyn":
        links = [(u, t) for (u, t) in pdf_links(index_url, r.text, must_contain=("current-bylaw-files",))
                 if "bylaw" in unquote(u).lower()]
    elif kind == "hastings":
        all_links = [(u, t) for (u, t) in pdf_links(index_url, r.text)
                     if "bylaw" in (unquote(u) + " " + t).lower()]
        cons = [l for l in all_links if "consolidated" in (unquote(l[0]) + l[1]).lower()]
        rest = [l for l in all_links if l not in cons]
        if cons:
            chapters = [l for l in rest if re.search(r"chapter|ch-\d|ch\d", (unquote(l[0]) + l[1]).lower())]
            non_ch = [l for l in rest if l not in chapters]
            links = cons[:1] + non_ch + chapters
        else:
            links = all_links
    else:
        raise ValueError(kind)
    return links[:SAMPLE]


# ------------------------------------------------------------- PDF -> text

SCRATCH = OUT / "scratch"
SCRATCH.mkdir(exist_ok=True)


def extract_text(pdf_bytes, tmp_stem):
    """fitz -> pdfplumber -> pdftotext -> tesseract. Returns (text, method)."""
    tmp = SCRATCH / f"{tmp_stem}.pdf"
    tmp.write_bytes(pdf_bytes)
    text = ""
    try:
        import fitz
        doc = fitz.open(tmp)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        if len(text.strip()) >= 200:
            return text, "fitz"
    except Exception:  # noqa: BLE001
        pass
    try:
        import pdfplumber
        with pdfplumber.open(tmp) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        if len(text.strip()) >= 200:
            return text, "pdfplumber"
    except Exception:  # noqa: BLE001
        pass
    try:
        subprocess.run(["pdftotext", "-layout", str(tmp), "-"], capture_output=True,
                       check=True, timeout=300)
        out = subprocess.run(["pdftotext", "-layout", str(tmp), "-"], capture_output=True,
                             timeout=300)
        text = out.stdout.decode("utf-8", "replace")
        if len(text.strip()) >= 200:
            return text, "pdftotext"
    except Exception:  # noqa: BLE001
        pass
    # OCR fallback: render pages with fitz, tesseract each
    try:
        import fitz
        doc = fitz.open(tmp)
        pages = []
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=200)
            img = SCRATCH / f"{tmp_stem}_p{i}.png"
            pix.save(img)
            o = subprocess.run(["tesseract", str(img), "stdout", "-l", "eng"],
                                 capture_output=True, timeout=300)
            pages.append(o.stdout.decode("utf-8", "replace"))
            img.unlink(missing_ok=True)
        doc.close()
        text = "\n".join(pages)
        if text.strip():
            return text, "tesseract"
    except Exception:  # noqa: BLE001
        pass
    return text, "none"


UNIT_START = re.compile(
    r"^\s*(?:PART\s+\d+\b|Part\s+\d+\b|SCHEDULE\s+\d*\b|\d{1,3}\.\s+[A-Z(])")


def split_units(text):
    """Split extracted text into clause-level units."""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    units, cur = [], []
    for ln in lines:
        if UNIT_START.match(ln) and cur and sum(len(x) for x in cur) > 40:
            units.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        units.append(cur)
    out = []
    for u in units:
        body = "\n".join(u).strip()
        if len(body) < 40:
            if out:
                out[-1] = out[-1] + "\n" + body
            continue
        out.append(body)
    return out


def prettify_title(url, link_text):
    stem = unquote(url.split("/")[-1])
    stem = re.sub(r"\.pdf$", "", stem, flags=re.I)
    if link_text and len(link_text) >= 8 and "pdf" not in link_text.lower()[:4]:
        t = re.sub(r"\s*\(PDF[^)]*\)\s*", " ", link_text, flags=re.I).strip()
        t = re.sub(r"\s+", " ", t)
        if len(t) >= 8:
            return t
    t = re.sub(r"[-_]+", " ", stem).strip()
    return t[:1].upper() + t[1:] if t else stem


def build_council(sess, code):
    name = COUNCILS[code][0]
    jid = NZ.normalize(code)
    t_start = time.monotonic()
    found = discover(sess, code)
    print(f"[{code}] discovered {len(found)} bylaws")
    rows = []
    docs = []
    for pdf_url, link_text in found:
        title = prettify_title(pdf_url, link_text)
        pdf_bytes = sess.get_bytes(pdf_url)
        text, method = extract_text(pdf_bytes, f"nz_{code}_{abs(hash(pdf_url)) % 99999}")
        units = split_units(text)
        if len(units) < 2:  # page-level fallback: whole doc as one unit if long
            units = [text.strip()] if len(text.strip()) >= 200 else []
        year = ""
        m = re.search(r"(19|20)\d\d", title + " " + unquote(pdf_url))
        if m:
            year = m.group(0)
        slug = re.sub(r"[^a-z0-9]+", "-", unquote(pdf_url).split("/")[-1].lower())
        slug = re.sub(r"\.pdf$", "", slug).strip("-")
        made = 0
        for i, unit in enumerate(units):
            first = unit.split("\n")[0].strip()
            label = first[:120] if i else (first[:120] or title)
            body_html = "".join(
                f"<p>{html_mod.escape(p.strip())}</p>"
                for p in re.split(r"\n\s*\n|\n", unit) if p.strip())
            rows.append(make_row(
                jurisdiction_id=jid, jurisdiction_name=name, country="NZ",
                doc_id=f"{slug}#{i + 1}", title=title,
                structural_path=title, node_label=label,
                body_html=body_html, source_url=pdf_url,
                date_effective=year, retrieved=RETRIEVED))
            made += 1
        docs.append({"title": title, "source_url": pdf_url, "method": method,
                     "chars": len(text), "units": made})
        print(f"[{code}]  {title}: {method}, {len(text)} chars, {made} rows")
    rows = drop_empty_rows(finalize_rows(rows))
    table = rows_to_table(rows)
    errors = validate_table(table, jurisdiction_id=jid, jurisdiction_name=name, country="NZ")
    if errors:
        raise SystemExit(f"[{code}] VALIDATION FAILED: {errors}")
    pq = OUT / f"{jid}_html.parquet"
    write_html_parquet(pq, table)
    back = read_html_parquet(pq)
    errors2 = validate_table(back, jurisdiction_id=jid, jurisdiction_name=name, country="NZ")
    if errors2:
        raise SystemExit(f"[{code}] RE-READ VALIDATION FAILED: {errors2}")
    rep = validation_report(back, jurisdiction_id=jid, jurisdiction_name=name, country="NZ")
    write_validation_report(OUT / f"{jid}_validation.json", rep)
    wall = time.monotonic() - t_start
    return {"code": jid, "name": name, "docs": docs, "rows": len(rows),
            "requests": sess.n_requests, "fetch_seconds": round(sess.fetch_seconds, 1),
            "wall_seconds": round(wall, 1), "parquet": pq.name, "valid": True}


def main():
    codes = sys.argv[1:] or list(COUNCILS)
    manifest_path = OUT / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else \
        {"retrieved": RETRIEVED, "councils": {}}
    for code in codes:
        sess = PoliteSession()
        try:
            res = build_council(sess, code)
            manifest["councils"][code] = res
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001
            manifest["councils"][code] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"[{code}] FAILED: {exc}")
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(json.dumps({k: (v.get("rows"), v.get("error")) for k, v in manifest["councils"].items()}, indent=1))


if __name__ == "__main__":
    main()
