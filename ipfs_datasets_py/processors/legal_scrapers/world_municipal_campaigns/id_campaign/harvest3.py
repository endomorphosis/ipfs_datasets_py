"""Indonesia tranche-3 harvest driver.

Extends harvest2 (which extends the tranche-1 harvester; all gates
unchanged) with:

  - the OCR lane: pdf_text_ocr, a drop-in pdf_text replacement that
    downloads PDF bytes with the Range-resume fetcher and, when native
    text is below the probe threshold (<800 chars or no Pasal
    structure), falls back to per-page tesseract OCR (250 DPI, psm 3,
    ind+eng when ind.traineddata is available in ocr_probe/, else eng;
    nice'd, OMP_THREAD_LIMIT=1, globally serialized, load-aware
    pacing). Born-digital docs never touch OCR.
  - ocr_drive_unit: a per-doc checkpointed driver for scanned
    catalogs/remainders. Rows accumulate in staging/<bps>_ocr_rows.jsonl,
    progress in staging/<bps>_ocr_progress.json; on finalize the new
    rows merge with any already-staged base parquet (top-up units),
    the merged table must pass validate_table before staging.
  - new enumerators: produkhukum (multi-shape fit), wordpress
    (category archive, /view/ or post slugs, PDF on detail page),
    slug_detail_deep (Dairi: paginate past Perda-sparse pages).
  - drive3(): tranche-3 unit driver over H.harvest_unit with OCR
    accounting per host.

State: env ID_T3_STATE (default id_campaign_tranche3_state.json).
Phases: retries | rembang | ocr:<bps,...> | units:<bps:adapter,...>
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

WS = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
CAMP = WS / "id_campaign"
STAGE = CAMP / "staging"
sys.path.insert(0, str(CAMP))

import harvest as H  # noqa: E402
import harvest2 as H2  # noqa: E402  (resilient pdf_text + resolver + enumerators)
from bs4 import BeautifulSoup  # noqa: E402

import fitz  # noqa: E402

REGISTRY = WS / "id_jdih_registry_2026-10-12.json"
CENSUS_PATH = CAMP / "generic_census_tranche2.json"
STATE3_PATH = CAMP / os.environ.get("ID_T3_STATE", "id_campaign_tranche3_state.json")
RETRIEVED = H.RETRIEVED

clean_ws, nomor_tahun, is_perda_title = H.clean_ws, H.nomor_tahun, H.is_perda_title
is_qanun_title = H.is_qanun_title
slug = H.slug

# ------------------------------------------------------------------- OCR

TESSDATA_DIR = CAMP / "ocr_probe"
OCR_LANG = "ind+eng" if (TESSDATA_DIR / "ind.traineddata").exists() else "eng"
NATIVE_MIN_CHARS = 800        # probe threshold: doc-level born-digital test
PAGE_NATIVE_MIN = 200         # per-page: keep native text at/above this
OCR_DPI = 250
OCR_MAX_PAGES = int(os.environ.get("ID_OCR_MAX_PAGES", "60"))
OCR_DOC_MAX_S = float(os.environ.get("ID_OCR_DOC_MAX_S", "1500"))
OCR_LOAD_MAX = float(os.environ.get("ID_OCR_LOAD_MAX", "40"))

_OCR_SEM = threading.Semaphore(int(os.environ.get("ID_OCR_PARALLEL", "1")))
_OCR_STATS = {}               # host -> {"docs": int, "pages": int, "seconds": float}
_OCR_LOCK = threading.Lock()


def ocr_stats_snapshot():
    with _OCR_LOCK:
        return {k: dict(v) for k, v in _OCR_STATS.items()}


def _ocr_register(host, pages, seconds):
    with _OCR_LOCK:
        s = _OCR_STATS.setdefault(host, {"docs": 0, "pages": 0, "seconds": 0.0})
        s["docs"] += 1
        s["pages"] += pages
        s["seconds"] += seconds


def _load_pause():
    """Courtesy brake: while the box is saturated, wait — but never
    more than ~15 minutes for a single page, then proceed anyway."""
    waited = 0.0
    while waited < 900:
        try:
            if os.getloadavg()[0] <= OCR_LOAD_MAX:
                return
        except OSError:
            return
        time.sleep(20)
        waited += 20


TESS_BIN = os.environ.get("ID_TESSERACT_BIN", "tesseract")


def _tesseract(png_bytes):
    cmd = [TESS_BIN, "stdin", "stdout",
           "-l", OCR_LANG, "--psm", "3"]
    if OCR_LANG.startswith("ind"):
        cmd += ["--tessdata-dir", str(TESSDATA_DIR)]
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    try:
        p = subprocess.run(cmd, input=png_bytes, capture_output=True,
                           timeout=900, env=env)
    except subprocess.TimeoutExpired:
        return ""   # one starved page must not kill the whole document
    return p.stdout.decode("utf-8", "replace")


def download_bytes(sess, url):
    """Range-resume download -> (raw_bytes, err). Honors the 45 MB cap.
    Also honors an overall per-document deadline (ID_DL_DOC_MAX_S,
    default 900 s): some hosts trickle at ~1 KB/s through the shared
    proxy, and an unbounded stream would park a worker for hours on
    a single doc — fail it instead and let the unit move on."""
    dl_deadline = float(os.environ.get("ID_DL_DOC_MAX_S", "900"))
    dl_t0 = time.monotonic()
    buf = bytearray()
    expected = None
    err = ""
    for _ in range(8):
        headers = {"Accept-Encoding": "identity"}
        if buf:
            headers["Range"] = f"bytes={len(buf)}-"
        try:
            r = sess.get(url, timeout=180, stream=True, headers=headers)
            r.raise_for_status()
            if buf and r.status_code == 200:
                buf = bytearray()
            cr = r.headers.get("Content-Range", "")
            m = re.search(r"/(\d+)\s*$", cr)
            if m:
                expected = int(m.group(1))
            elif r.headers.get("Content-Length"):
                cl = int(r.headers["Content-Length"])
                expected = cl if r.status_code == 200 else len(buf) + cl
            if expected is not None and expected > H.MAX_PDF_BYTES:
                return bytes(buf), f"pdf exceeds {H.MAX_PDF_BYTES} bytes cap"
            try:
                for chunk in r.iter_content(1 << 16):
                    if chunk:
                        buf.extend(chunk)
                    if len(buf) > H.MAX_PDF_BYTES:
                        return bytes(buf), f"pdf exceeds {H.MAX_PDF_BYTES} bytes cap"
                    if time.monotonic() - dl_t0 > dl_deadline:
                        return bytes(buf), (f"download deadline {int(dl_deadline)}s "
                                            f"exceeded at {len(buf)} bytes (slow host)")
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
                time.sleep(2)
                continue
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            time.sleep(2)
            continue
        if expected is None or len(buf) >= expected:
            break
    if expected is not None and len(buf) < expected:
        return bytes(buf), f"incomplete after retries ({len(buf)}/{expected}; {err})"
    return bytes(buf), ""


def _ocr_doc(doc):
    """OCR a fitz document page by page (native text kept where dense).
    Returns (text, pages_ocrd, ocr_seconds)."""
    texts, pages, secs = [], 0, 0.0
    t_start = time.monotonic()
    for pno in range(min(doc.page_count, OCR_MAX_PAGES)):
        page = doc[pno]
        native = page.get_text()
        if len(native.strip()) >= PAGE_NATIVE_MIN:
            texts.append(native)
            continue
        _load_pause()
        pix = page.get_pixmap(matrix=fitz.Matrix(OCR_DPI / 72, OCR_DPI / 72))
        t0 = time.time()
        txt = _tesseract(pix.tobytes("png"))
        secs += time.time() - t0
        pages += 1
        texts.append(txt)
        if time.monotonic() - t_start > OCR_DOC_MAX_S:
            break
    return "\n".join(texts), pages, secs


def pdf_text_ocr(sess, url):
    """(text, n_bytes, err) — native extraction first; OCR fallback
    when the doc is a scan by the probe's test."""
    raw, err = download_bytes(sess, url)
    if err:
        return "", len(raw), err
    off = raw[:2048].find(b"%PDF")
    if off < 0:
        return "", len(raw), f"not a PDF (first bytes {raw[:20]!r})"
    try:
        doc = fitz.open(stream=raw[off:], filetype="pdf")
    except Exception as exc:
        return "", len(raw), f"fitz failed: {exc}"
    native = "\n".join(p.get_text() for p in doc).strip()
    if len(native) >= NATIVE_MIN_CHARS and H.split_pasal(native):
        return native, len(raw), ""
    with _OCR_SEM:
        text, pages, secs = _ocr_doc(doc)
    if pages:
        _ocr_register(urlparse(url).netloc, pages, secs)
    return text.strip(), len(raw), ""


if os.environ.get("ID_OCR", "1") == "1":
    H.pdf_text = pdf_text_ocr

# ------------------------------------------------------- doc -> rows block
# Faithful copy of harvest_unit's per-doc guard/row logic, factored out
# so the checkpointed OCR driver applies exactly the same gates.

def doc_rows_from_text(unit, bps, host, doc, text):
    """Returns (rows, info). Mirrors harvest.harvest_unit's doc block."""
    info = dict(title=doc.get("title", ""), nomor=doc.get("nomor", ""),
                tahun=doc.get("tahun", ""), rows=0,
                detail_url=doc.get("detail_url", ""),
                pdf_url=doc.get("pdf_url", ""), mode="")
    head_type = H.pdf_head_reg_type(text)
    if head_type and head_type != "DAERAH":
        info["mode"] = (f"wrong type: PDF head is Peraturan "
                        f"{head_type.title()}, not Perda")
        return [], info
    chunks = H.split_pasal(text)
    if not chunks:
        info["mode"] = "no Pasal structure parsed"
        return [], info
    title = doc.get("title") or info["title"]
    head_title = H.pdf_head_title(text)
    if head_title and (not is_perda_title(title) or len(title) < 60
                       or "•" in title
                       or title.lower().count("peraturan daerah") > 1):
        title, info["title"] = head_title, head_title
    if title and not is_perda_title(title) and doc.get("nomor"):
        title = (f"Peraturan Daerah Nomor {doc['nomor']} Tahun "
                 f"{doc.get('tahun', '')} — {title}")
    elif not is_perda_title(title):
        title = (f"Peraturan Daerah Nomor {doc.get('nomor', '')} "
                 f"Tahun {doc.get('tahun', '')}").strip()
    if H.head_reg_type(title) not in ("daerah", ""):
        info["mode"] = (f"wrong type: title heads with Peraturan "
                        f"{H.head_reg_type(title)}, not Perda")
        return [], info
    info["title"] = title
    base_id = (f"id-{bps}-perda-{doc.get('tahun', '')}-"
               f"{slug(str(doc.get('nomor', '')))}")
    regeling = f"jdih:{host}:{doc.get('key', '')}"
    rows = []
    for suffix, label, bab, body in chunks:
        rows.append(H.make_row(
            jurisdiction_id=bps,
            jurisdiction_name=unit["name"],
            country="ID",
            doc_id=f"{base_id}-{suffix}",
            regeling_id=regeling,
            regeling_work_id=regeling,
            title=title,
            structural_path=f"{title} > {bab}" if bab else title,
            node_label=label,
            body_html=H.text_to_html(body),
            source_url=doc["pdf_url"],
            date_effective=doc.get("date_eff", ""),
            retrieved=RETRIEVED,
        ))
        info["rows"] += 1
    info["mode"] = "pdf-pasal"
    return rows, info


def _base_id(bps, cand):
    return (f"id-{bps}-perda-{cand.get('tahun', '')}-"
            f"{slug(str(cand.get('nomor', '')))}")

# ------------------------------------------------------- OCR-lane driver

def ocr_drive_unit(unit, budget_s=None):
    """Checkpointed OCR-lane harvest for one unit. Merges new rows with
    the staged base parquet when the unit is already published."""
    import pyarrow.parquet as pq
    bps = H.BPS_SCHEME.normalize(unit["bps"])
    host, base = unit["host"], f'https://{unit["host"]}'
    adapter = unit["adapter"]
    budget_s = budget_s or float(os.environ.get("ID_OCR_UNIT_BUDGET_S", "20000"))
    man = dict(unit, bps=bps, adapter=adapter, status="ocr_harvesting",
               catalog_total=0, selected=0, acts=0, rows=0, failed_docs=[],
               requests=0, errors=[], truncation="", ocr=True)
    prog_path = STAGE / f"{bps}_ocr_progress.json"
    rows_path = STAGE / f"{bps}_ocr_rows.jsonl"
    progress = (json.loads(prog_path.read_text()) if prog_path.exists()
                else {"done": {}})
    sess = H.PoliteSession()
    t0 = time.monotonic()
    try:
        prefixes = ["/dokumen", "/peraturan", "/prokum", "/home",
                    "/produkHukum", "/pencarian", "/inventarisasi-hukum",
                    "/produk", "/category", "/common", "/storage",
                    "/dokumen.php", "/cari"]
        if H.robots_blocked(sess, base, prefixes):
            man["status"] = "skipped"
            man["errors"].append("robots.txt disallows a needed path (live check)")
            return man
        cands = H.ENUMERATORS[adapter](sess, base, unit)
        if not cands:
            man["status"] = "skipped"
            man["errors"].append("enumeration yielded 0 Perda candidates")
            return man
        selected, total, note = H.cap_candidates(cands)
        man["catalog_total"] = total
        man["selected"] = len(selected)
        man["truncation"] = note
        # base rows (top-up units): the staged parquet already holds the
        # published rows; JSONL rows not yet merged into it are the delta.
        # This stays idempotent across resumes: merged rows are detected
        # by doc_id and never double-counted.
        base_rows, base_docids = [], set()
        pq_path = STAGE / f"{bps}_html.parquet"
        if pq_path.exists():
            base_rows = pq.read_table(pq_path).to_pylist()
            base_docids = {r["doc_id"] for r in base_rows}
            man["base_rows"] = len(base_rows)
        new_rows = []
        if rows_path.exists():
            for line in rows_path.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    if r["doc_id"] not in base_docids:
                        new_rows.append(r)
        done = progress["done"]
        attempted = 0
        for cand in selected:
            key = (cand.get("detail_url") or cand.get("pdf_url")
                   or cand.get("key", ""))
            if key in done:
                continue
            if time.monotonic() - t0 > budget_s:
                man["truncation"] = ((man["truncation"] + "; ") if man["truncation"]
                                     else "") + (
                    f"OCR lane partial: budget {int(budget_s)}s hit; "
                    f"{len(done)} of {len(selected)} selected docs attempted; "
                    f"remainder resumable from checkpoint")
                break
            attempted += 1
            info = dict(title=cand.get("title", ""), nomor=cand.get("nomor", ""),
                        tahun=cand.get("tahun", ""), rows=0,
                        detail_url=cand.get("detail_url", ""),
                        pdf_url=cand.get("pdf_url", ""), mode="")
            try:
                doc = cand
                needs_detail = (adapter in H.RESOLVER_ADAPTERS
                                or not doc.get("pdf_url") or not doc.get("title"))
                if needs_detail and doc.get("detail_url"):
                    doc = H.resolve_pdf(sess, dict(cand))
                    info.update({k: doc.get(k, info.get(k, "")) for k in
                                 ("title", "nomor", "tahun", "pdf_url")})
                bid = _base_id(bps, doc)
                if any(d == bid or d.startswith(bid + "-") for d in base_docids):
                    info["mode"] = "already in base parquet (top-up skip)"
                    done[key] = {"rows": 0, "mode": info["mode"]}
                    prog_path.write_text(json.dumps(progress, indent=1,
                                                    ensure_ascii=False))
                    continue
                if not doc.get("pdf_url"):
                    info["mode"] = "no PDF link on detail page"
                    done[key] = {"rows": 0, "mode": info["mode"]}
                    man["failed_docs"].append(info)
                    prog_path.write_text(json.dumps(progress, indent=1,
                                                    ensure_ascii=False))
                    continue
                host_before = ocr_stats_snapshot().get(host, {}).get("docs", 0)
                text, nbytes, err = pdf_text_ocr(sess, doc["pdf_url"])
                info["pdf_bytes"] = nbytes
                info["ocr"] = (ocr_stats_snapshot().get(host, {}).get("docs", 0)
                               > host_before)
                if err or not text:
                    info["mode"] = f"pdf failed: {err or 'empty text (scanned?)'}"
                    done[key] = {"rows": 0, "mode": info["mode"]}
                    man["failed_docs"].append(info)
                    prog_path.write_text(json.dumps(progress, indent=1,
                                                    ensure_ascii=False))
                    continue
                rows, info2 = doc_rows_from_text(unit, bps, host, doc, text)
                info.update(info2)
                if rows:
                    with rows_path.open("a", encoding="utf-8") as fh:
                        for r in rows:
                            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    new_rows.extend(rows)
                else:
                    man["failed_docs"].append(info)
                done[key] = {"rows": info["rows"], "mode": info["mode"],
                             "ocr": info.get("ocr", False)}
            except Exception as exc:
                info["mode"] = f"failed: {exc!r}"
                done[key] = {"rows": 0, "mode": info["mode"]}
                man["failed_docs"].append(info)
            prog_path.write_text(json.dumps(progress, indent=1,
                                            ensure_ascii=False))
            print(f"[{bps}] doc {len(done)}/{len(selected)} "
                  f"rows={info['rows']} mode={info['mode'][:60]}", flush=True)
        # ---------------- finalize (merge base + new)
        all_rows = H.finalize_rows(base_rows + new_rows)
        table = H.rows_to_table(all_rows)
        errors = H.validate_table(table, jurisdiction_id=bps,
                                  jurisdiction_name=unit["name"], country="ID")
        man["validation_errors"] = errors
        report = H.validation_report(table, jurisdiction_id=bps,
                                     jurisdiction_name=unit["name"], country="ID")
        H.write_validation_report(STAGE / f"{bps}_validation.json", report)
        new_acts = len({k for k, v in done.items() if v.get("rows", 0) > 0})
        man["acts"] = len({r["regeling_id"] for r in base_rows + new_rows})
        man["new_acts"] = new_acts
        man["docs_attempted_total"] = len(done)
        if errors:
            man["status"] = "failed"
            man["errors"].append(f"validation FAILED: {errors}")
        elif table.num_rows:
            man["rows"] = H.write_html_parquet(STAGE / f"{bps}_html.parquet", table)
            man["status"] = "staged"
        else:
            man["status"] = "skipped"
            man["errors"].append("0 rows harvested (all docs failed extraction)")
    except Exception as exc:
        man["status"] = "failed"
        man["errors"].append(f"ocr harvest failed: {exc!r}")
    finally:
        man["requests"] = sess.n_requests
        man["wall_seconds"] = round(time.monotonic() - t0, 1)
        st = ocr_stats_snapshot().get(host)
        if st:
            man["ocr_docs"], man["ocr_pages"] = st["docs"], st["pages"]
            man["ocr_seconds"] = round(st["seconds"], 1)
    return man

# ------------------------------------------------------- new enumerators

def _drive_table_rows(html, page_url, unit):
    """Parse a listing table whose rows link straight to Google
    Drive (Indramayu shape): cells are No | Nomor | Tahun | Judul |
    Status | Tanggal | actions. The page is the /perda catalog, so
    every row is a Perda; the full title is rebuilt from the catalog
    columns and the PDF-head gate still verifies the document."""
    import re as _re
    soup = BeautifulSoup(html, "html.parser")
    name = clean_ws(str(unit.get("kabupaten_kota") or ""))
    found = {}
    for tr in soup.find_all("tr"):
        a = tr.find("a", href=_re.compile(r"drive\.google\.com/file/d/"))
        if not a:
            continue
        fid = _re.search(r"/file/d/([^/]+)/", a["href"])
        if not fid:
            continue
        cells = [clean_ws(td.get_text(" ", strip=True))
                 for td in tr.find_all(["td", "th"])]
        tahun = ""
        judul = ""
        nomor = ""
        for i, c in enumerate(cells):
            if _re.fullmatch(r"(19|20)\d{2}", c) and not tahun:
                tahun = c
                if i >= 1:
                    nomor = cells[i - 1]
                judul = max(cells, key=len) if cells else ""
                break
        if not (tahun and judul):
            continue
        title = (f"Peraturan Daerah {name + ' ' if name else ''}"
                 f"Nomor {nomor} Tahun {tahun} tentang {judul}")
        detail = page_url
        for x in tr.find_all("a", href=True):
            if "drive.google" not in x["href"]:
                detail = urljoin(page_url, x["href"])
                break
        found[fid.group(1)] = dict(
            detail_url=detail,
            pdf_url=("https://drive.google.com/uc?export=download&id="
                     + fid.group(1)),
            title=title, nomor=nomor, tahun=tahun, key=fid.group(1))
    return found


def enum_produkhukum(sess, base, unit):
    """produkhukum CMS family — multi-shape fit, first shape that yields
    wins: (a) Banjarmasin shape /produkHukum?tipe_dokumen=1 with
    /produkHukum/download/<id> links; (b) /jdih/all/perda listing with
    /jdih/detail|view|produkhukum links; (c) /produk-hukum/... slug
    listings (peraturan-daerah category)."""
    # (b0) Drive-table catalog at /jdih/all/perda (Indramayu shape)
    for path in ("/jdih/all/perda", "/jdih/all/produk-hukum",
                 "/jdih/produk-hukum/all/perda"):
        try:
            r = sess.get(base + path, timeout=300)
        except Exception:
            continue
        if r.status_code == 200:
            got = _drive_table_rows(r.text, base + path, unit)
            if got:
                return got
    # (d) /ProdukHukum/kategori/<uuid> at site root (Tegal shape):
    # discover category links on the homepage whose label names
    # Peraturan Daerah, then walk the category collecting
    # /ProdukHukum/detail/<id> links with Perda titles.
    try:
        r = sess.get(base + "/", timeout=180)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            cats = []
            for a in soup.find_all("a", href=True):
                href = urljoin(base + "/", a["href"])
                if ("/produkhukum/kategori/" in href.lower()
                        and "peraturan daerah" in
                        clean_ws(a.get_text(" ", strip=True)).lower()):
                    cats.append(href)
            for cat in cats:
                got = _archive_walk(
                    sess, base, cat,
                    lambda n, c=cat: f"{c}?page={n}")
                got = {k: v for k, v in got.items()
                       if "/detail/" in k.lower()}
                if got:
                    return got
    except Exception:
        pass
    # (a) banjarmasin shape
    try:
        cands = H.ENUMERATORS["banjarmasin"](sess, base, unit)
        if cands:
            return cands
    except Exception:
        pass
    # (b) /jdih/all/perda
    for path in ("/jdih/all/perda", "/jdih/all/peraturan-daerah",
                 "/jdih/produkhukum", "/produkhukum"):
        try:
            cands = H._detail_enum(
                sess, base + path,
                r"/(jdih/(detail|view|produkhukum)|produk-?hukum|detail)[^\"']*$")
            cands = {k: v for k, v in cands.items()
                     if is_perda_title(v.get("title", ""))
                     or "perda" in k.lower() or "peraturan-daerah" in k.lower()}
            if cands:
                for c in cands.values():
                    if not c.get("nomor"):
                        c["nomor"], c["tahun"] = nomor_tahun(c.get("title", ""))
                return cands
        except Exception:
            continue
    # (c) slug listings
    for path in ("/produk-hukum/peraturan-daerah", "/produk-hukum",
                 "/peraturan-daerah"):
        try:
            cands = H._detail_enum(sess, base + path,
                                   r"/(produk-hukum|peraturan-daerah)/[^/]+$")
            cands = {k: v for k, v in cands.items()
                     if "peraturan-daerah" in k.lower()
                     or is_perda_title(v.get("title", ""))}
            if cands:
                for c in cands.values():
                    if not c.get("nomor"):
                        c["nomor"], c["tahun"] = nomor_tahun(c.get("title", ""))
                return cands
        except Exception:
            continue
    return {}


def _archive_walk(sess, base, first_url, page_url_fn, max_pages=60):
    """Walk an archive listing collecting Perda-titled anchors as
    candidates. Tolerates up to 3 consecutive dry/failed pages."""
    got = {}
    dry = 0
    for n in range(1, max_pages + 1):
        url = first_url if n == 1 else page_url_fn(n)
        try:
            r = sess.get(url, timeout=180)
        except Exception:
            dry += 1
            if dry >= 3:
                break
            time.sleep(20)
            continue
        if r.status_code != 200:
            dry += 1
            if dry >= 3:
                break
            time.sleep(20)
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        fresh = 0
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"])
            if urlparse(href).netloc != urlparse(base).netloc:
                continue
            path = urlparse(href).path
            if "/category/" in path or path.endswith(("/feed/", "/feed")):
                continue
            txt = clean_ws(a.get_text(" ", strip=True))
            if not is_perda_title(txt):
                continue
            prev = got.get(href, {})
            if len(txt) > len(prev.get("title", "")):
                got[href] = dict(detail_url=href, pdf_url="", title=txt,
                                 nomor="", tahun="",
                                 key=path.rstrip("/").split("/")[-1])
                fresh += 1
        if fresh == 0:
            dry += 1
            if dry >= 3:
                break
        else:
            dry = 0
    return got


def enum_wordpress(sess, base, unit):
    """WordPress-family JDIH: Perda live as posts in the
    peraturan-daerah category; detail pages (post URL or /view/<slug>)
    embed the PDF. Enumerate the category archive via WP path-style
    pagination (/page/N/). Self-contained loop: the stock paginate()
    raises on a flaky page and would discard page 1's results, which
    is exactly how this family fit-tested 0 in tranche 3's first pass."""
    out = {}
    for cat_path in ("/category/peraturan-daerah", "/category/perda"):
        got = _archive_walk(
            sess, base, base + cat_path,
            lambda n, cp=cat_path: f"{base}{cp}/page/{n}")
        if got:
            out.update(got)
            break
    if not out:
        # katalog variants seen in the family: query-kategori archive,
        # produk-hukum listing with numeric detail ids, dokumen-hukum
        extras = [
            ("/produk-hukum/?kategori=peraturan-daerah",
             lambda n: (f"{base}/produk-hukum/?kategori=peraturan-daerah"
                        f"&page={n}")),
            ("/produk-hukum/peraturan-perundang-undangan",
             lambda n: (f"{base}/produk-hukum/peraturan-perundang-"
                        f"undangan?page={n}")),
            ("/dokumen-hukum/perda",
             lambda n: f"{base}/dokumen-hukum/perda?page={n}"),
            ("/katalog-produk-hukum/",
             lambda n: f"{base}/katalog-produk-hukum/?page={n}"),
        ]
        for first, fn in extras:
            got = _archive_walk(sess, base, base + first, fn)
            if got:
                out.update(got)
                break
    for c in out.values():
        if not c.get("nomor"):
            c["nomor"], c["tahun"] = nomor_tahun(c.get("title", ""))
    return out


def enum_slug_detail_deep(sess, base, unit):
    """Dairi-family CMS with Perda sparse in a recency-sorted catalog:
    walk /peraturan pages until the listing itself runs dry, keeping
    only peraturan-daerah detail slugs (the stock paginate() stops at
    the first page with no NEW Perda links, which is the failure this
    fixes)."""
    out = {}
    seen_pages = 0
    dry = 0
    for n in range(1, 61):
        url = base + "/peraturan" + (f"?page={n}" if n > 1 else "")
        try:
            r = sess.get(url, timeout=240)
        except Exception:
            dry += 1
            if dry >= 2:
                break
            continue
        if r.status_code != 200:
            dry += 1
            if dry >= 2:
                break
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        page_details = 0
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"])
            if "/detail/peraturan/" not in href:
                continue
            page_details += 1
            if "/detail/peraturan/peraturan-daerah" not in href:
                continue
            txt = clean_ws(a.get_text(" ", strip=True))
            prev = out.get(href, {})
            if len(txt) > len(prev.get("title", "")):
                out[href] = dict(detail_url=href, pdf_url="", title=txt,
                                 nomor="", tahun="",
                                 key=href.rstrip("/").split("/")[-1])
        seen_pages += 1
        if page_details == 0:
            dry += 1
            if dry >= 2:
                break
        else:
            dry = 0
    for c in out.values():
        if not c.get("nomor"):
            c["nomor"], c["tahun"] = nomor_tahun(c.get("title", ""))
    unit["slug_pages_walked"] = seen_pages
    return out


H.ENUMERATORS["produkhukum"] = enum_produkhukum
H.ENUMERATORS["wordpress"] = enum_wordpress
H.ENUMERATORS["slug_detail_deep"] = enum_slug_detail_deep


def enum_dih_qanun(sess, base, unit):
    """Aceh DIH enumerator with the Qanun policy applied (Benjamin
    2026-10-13): identical to harvest2.enum_dih — the 'Peraturan
    Daerah' category of the DIH DataTables endpoint — except
    Qanun-headed rows are INCLUDED as Perda-equivalent instead of
    counted-and-skipped. Other instrument types (Perbup/Perwali/
    Keputusan) remain excluded by is_perda_title/is_qanun_title."""
    r = sess.get(base + "/dih/kategori/Peraturan%20Daerah", timeout=150)
    r.raise_for_status()
    kat = "15"
    m = re.search(r'\{display:\s*"Peraturan Daerah[^"]*",\s*value:\s*"(\d+)"\}',
                  r.text)
    if m:
        kat = m.group(1)
    out = {}
    qanun = 0
    start, total = 0, None
    while start < 600:
        u = f"{base}/dih/jsondata?draw=1&start={start}&length=100&kat_dok={kat}"
        rr = sess.get(u, timeout=150)
        rr.raise_for_status()
        d = rr.json()
        if total is None:
            total = d.get("recordsFiltered", 0)
        rows = d.get("data", [])
        if not rows:
            break
        for row in rows:
            snippet = row[0] if isinstance(row, list) else str(row)
            dm = re.search(r'href="([^"]*/dih/detail/[0-9a-fA-F-]{36})"', snippet)
            if not dm:
                continue
            detail = urljoin(base, dm.group(1))
            tm = re.search(r'<a[^>]*class="news-title"[^>]*>(.*?)</a>', snippet, re.S)
            title = clean_ws(re.sub(r"<[^>]+>", " ", tm.group(1))) if tm else ""
            ym = re.search(r"Tahun\s*:\s*(\d{4})", snippet)
            nm = re.search(r"No\.\s*Peraturan\s*:\s*([0-9A-Za-z./-]+)", snippet)
            if is_qanun_title(title):
                qanun += 1
            elif not is_perda_title(title):
                continue
            out[detail] = dict(detail_url=detail, pdf_url="", title=title,
                               title_locked=True,
                               nomor=nm.group(1) if nm else "",
                               tahun=ym.group(1) if ym else "",
                               key=detail.rstrip("/").split("/")[-1])
        start += len(rows)
        if total is not None and start >= total:
            break
    unit["dih_qanun_included"] = qanun
    unit["dih_catalog_total"] = total
    return out


H.ENUMERATORS["dih_qanun"] = enum_dih_qanun


# ------------------------------------------------------------- resolve3
_resolve_prev = H.resolve_pdf


def resolve_pdf3(sess, cand):
    """Tranche-3 resolver wrap: Rembang-style inventarisasi detail
    pages embed the act PDF in an <iframe> (plus an 'abstrak'
    abstract PDF that is NOT the act) — neither the stock resolver
    nor the tranche-2 dispatcher looks at iframe srcs, which is why
    38/49 Rembang docs resolved to 'no PDF link on detail page'."""
    detail = cand.get("detail_url", "")
    if "/inventarisasi-hukum/detail/" in detail and not cand.get("pdf_url"):
        try:
            r = sess.get(detail, timeout=150)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            srcs = []
            for tag in soup.find_all(["iframe", "embed"]):
                s = tag.get("src", "")
                if s and ".pdf" in s.lower():
                    srcs.append(urljoin(detail, s))
            acts = [s for s in srcs if "abstrak" not in s.lower()]
            if acts:
                cand["pdf_url"] = acts[0]
                return H2._polish_from_detail(cand, soup)
            if srcs and not acts:
                return _resolve_prev(sess, cand)
        except Exception:
            pass
    return _resolve_prev(sess, cand)


H.resolve_pdf = resolve_pdf3
H.RESOLVER_ADAPTERS.update({"produkhukum", "wordpress", "slug_detail_deep"})

# ------------------------------------------------------- unit tables

REG = {u["bps"]: u for u in json.loads(REGISTRY.read_text())["units"]}
CENSUS = json.loads(CENSUS_PATH.read_text()) if CENSUS_PATH.exists() else {}


def reg_unit(bps, adapter, family=""):
    reg = REG.get(bps, {})
    return dict(bps=bps, name=reg.get("name", bps),
                host=reg.get("best_host", ""), adapter=adapter, family=family)


DOKVIEW_RETRY = ["5308", "5371", "6405", "6501", "7173", "7302", "7318",
                 "7410", "7413", "7472", "7503", "7603", "7604", "8207",
                 "9171", "9471"]
DIH_RETRY = ["1101", "1102", "1104", "1105", "1106", "1107", "1108",
             "1109", "1110", "1111", "1112", "1114", "1118",
             "1173", "1174", "1175"]
CHEAP_REINCLUDE = ["3604", "3306", "9104", "1813", "6311"]

SWING_HOST = {b: (n, h, a) for b, n, h, a in H2.SWING_UNITS}


def retry_units():
    # Order matters under this box's restart cadence: quick wins
    # first, slow grinders last. drive3 consumes results in list
    # order (executor map), so a single hanging unit at the head
    # blocks every later unit's state save. 6405 is a known 0-yield
    # full-catalog grinder — it goes last.
    out = []
    for b in CHEAP_REINCLUDE:
        if b in SWING_HOST:
            n, h, a = SWING_HOST[b]
            out.append(dict(bps=b, name=n, host=h, adapter=a, family="swing_t1"))
        else:
            out.append(reg_unit(b, "generic_probe", "unreachable_now"))
    out.append(reg_unit("6303", "banjar", "swing_t1"))
    out += [reg_unit(b, "dokumen_view", "dokumen_view")
            for b in DOKVIEW_RETRY if b != "6405"]
    out += [reg_unit(b, "dih", "dih") for b in DIH_RETRY]
    out.append(reg_unit("6405", "dokumen_view", "dokumen_view"))
    return out


def load_state3():
    if STATE3_PATH.exists():
        return json.loads(STATE3_PATH.read_text())
    return {}


def save_state3(state):
    STATE3_PATH.write_text(json.dumps(state, indent=1, ensure_ascii=False))


_PUBLISHED_CACHE = None


def already_published():
    global _PUBLISHED_CACHE
    if _PUBLISHED_CACHE is None:
        _PUBLISHED_CACHE = H2.published_bps()
        for p in CAMP.glob("id_campaign_tranche3_*state*.json"):
            st = json.loads(p.read_text())
            for bps, s in st.items():
                if isinstance(s, dict) and s.get("status") in ("published", "staged"):
                    _PUBLISHED_CACHE.add(bps)
    return _PUBLISHED_CACHE


def drive3(units, label):
    state = load_state3()
    pub = already_published()
    todo = []
    for u in units:
        cur = state.get(u["bps"], {})
        if cur.get("status") in ("staged", "published"):
            print(f"[{u['bps']}] t3-state {cur['status']}, skip", flush=True)
            continue
        if u["bps"] in pub and u["bps"] not in state:
            print(f"[{u['bps']}] already published, skip", flush=True)
            continue
        todo.append(u)
    print(f"{label}: {len(todo)} units to harvest", flush=True)
    workers = int(os.environ.get("ID_WORKERS", "4"))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for man in ex.map(lambda u: H.harvest_unit(u, state), todo):
            snap = ocr_stats_snapshot().get(man["host"])
            if snap and snap["docs"]:
                man["ocr"] = True
                man["ocr_docs"] = snap["docs"]
                man["ocr_pages"] = snap["pages"]
                man["ocr_seconds"] = round(snap["seconds"], 1)
            state[man["bps"]] = dict(man)
            save_state3(state)
            print(json.dumps({k: man.get(k) for k in
                              ("bps", "name", "adapter", "status", "catalog_total",
                               "selected", "acts", "rows", "requests", "errors")},
                             ensure_ascii=False), flush=True)
    print(f"{label}: done", flush=True)


OCR_UNITS = {
    "6401": ("dokumen_view", "paser"),
    "1807": ("waykanan", "waykanan"),
    "5202": ("lomboktengah", "lomboktengah"),
    "1673": ("dokumen_view", "dokumen_view"),
    "5301": ("dokumen_view", "dokumen_view"),
    "1375": ("dokumen_view", "dokumen_view"),
    "1501": ("dokumen_view", "dokumen_view"),
}


# ------------------------------------------------------------- aceh (Qanun)
ACEH_DIH = ["1115", "1116", "1118", "1173", "1174", "1175",
            "1101", "1102", "1104", "1105", "1106", "1107", "1108",
            "1109", "1110", "1111", "1112", "1114"]


def aceh_units():
    """All 18 Aceh dih units under the Qanun policy. The two
    already-published units (1115, 1116) come first: they are
    re-harvested in full (Perda + Qanun) and publish3 supersedes
    their Perda-only parquets in place."""
    return [dict(reg_unit(b, "dih_qanun", "dih"), qanun_equivalent=True)
            for b in ACEH_DIH]


def _qanun_acts_in_parquet(bps):
    """Ground-truth Qanun count: distinct document titles in the
    staged parquet that head with Qanun."""
    import pyarrow.parquet as pq
    p = STAGE / f"{bps}_html.parquet"
    if not p.exists():
        return 0
    t = pq.read_table(p, columns=["title", "regeling_id"])
    pairs = set(zip(t.column("title").to_pylist(),
                    t.column("regeling_id").to_pylist()))
    return len({rid for title, rid in pairs if is_qanun_title(title or "")})


def drive_aceh():
    """Dedicated driver: unlike drive3 it does NOT skip units that
    are already published elsewhere (rebuild semantics for 1115/
    1116); it skips only units already staged/published in the
    aceh state file, and consumes results as they complete."""
    from concurrent.futures import as_completed
    state = load_state3()
    todo = []
    for u in aceh_units():
        cur = state.get(u["bps"], {})
        if cur.get("status") in ("staged", "published"):
            print(f"[{u['bps']}] aceh-state {cur['status']}, skip", flush=True)
            continue
        todo.append(u)
    print(f"aceh: {len(todo)} units to harvest", flush=True)
    workers = int(os.environ.get("ID_WORKERS", "3"))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(H.harvest_unit, u, state): u for u in todo}
        for fut in as_completed(futs):
            u = futs[fut]
            try:
                man = fut.result()
            except Exception as exc:
                man = dict(u, status="failed", acts=0, rows=0,
                           errors=[f"driver exception: {exc!r}"],
                           failed_docs=[])
            man["qanun_equivalent"] = True
            if u.get("dih_qanun_included") is not None:
                man["qanun_catalog"] = u["dih_qanun_included"]
            if man.get("status") == "staged":
                man["qanun_acts"] = _qanun_acts_in_parquet(man["bps"])
            state[man["bps"]] = dict(man)
            save_state3(state)
            print(json.dumps({k: man.get(k) for k in
                              ("bps", "name", "adapter", "status", "catalog_total",
                               "selected", "acts", "rows", "qanun_acts",
                               "qanun_catalog", "requests", "errors")},
                             ensure_ascii=False), flush=True)
    print("aceh: done", flush=True)


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "retries"
    if phase == "retries":
        drive3(retry_units(), "retries")
    elif phase == "aceh":
        drive_aceh()
    elif phase == "rembang":
        n, h, a = SWING_HOST["3317"]
        drive3([dict(bps="3317", name=n, host=h, adapter=a, family="swing_t1")],
               "rembang")
    elif phase.startswith("ocr:"):
        want = phase.split(":", 1)[1].split(",")
        state = load_state3()
        for b in want:
            adapter, fam = OCR_UNITS[b]
            reg = REG.get(b, {})
            unit = dict(bps=b, name=reg.get("name", b),
                        host=reg.get("best_host", ""), adapter=adapter,
                        family=fam)
            if b == "6401":
                unit["host"] = "jdih.paserkab.go.id"
            man = ocr_drive_unit(unit)
            state[b] = dict(man)
            save_state3(state)
            print(json.dumps({k: man.get(k) for k in
                              ("bps", "name", "status", "catalog_total",
                               "selected", "acts", "rows", "errors")},
                             ensure_ascii=False), flush=True)
    elif phase.startswith("units:"):
        units = []
        for spec in phase.split(":", 1)[1].split(","):
            b, a = spec.split(":")
            fam = CENSUS.get(b, {}).get("family", "")
            units.append(reg_unit(b, a, fam))
        drive3(units, "units")
    else:
        print("unknown phase", phase)


if __name__ == "__main__":
    main()
