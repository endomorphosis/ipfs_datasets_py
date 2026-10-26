"""South Africa PDF-only tranche — recover the 105 Open By-laws works that
AKN tranche 1 (v2) excluded as `pdf_only_no_akn_html`, via their source PDFs.

Builds on the verified tranche-1 v2 builder's conventions (same
world_municipal 19-column schema, MdbScheme, PoliteSession pacing,
fail-closed gates). Nothing from the failed za_tranche1/ folder is used.

Route (robots verified fresh 2026-10-12 before any PDF fetch):
openbylaws.org.za robots.txt for User-agent * is `Allow: /` with
Crawl-delay 5 and disallows only /api/, /accounts/, /my/, /user/,
/purchase/, /judgments/, /gazettes/, /search/, /akn/*/provision/* and
per-place judgment/officialGazette subpaths. The source-PDF route —
/akn/<place>/act/<subtype>/<year>/<slug>/<lang>@<date>/source.pdf,
linked as `data-pdf` / `href=.../source.pdf` on every work's own public
page (including the PDF-stub pages) — matches no disallow pattern and
is therefore robots-allowed. All fetches at >=6 s pacing. The
token-gated Laws.Africa Content API is NOT used.

Source PDFs are usually Provincial Gazette issues (sometimes scanned),
so the instrument for each work is segmented out of the gazette text
before normalization: segment boundaries are municipality/by-law
heading events (the 257-name MDB registry plus generic heading
patterns). A work whose instrument cannot be located confidently
stays excluded with a reason — never forced, and no other
municipality's text is attributed to this one.

Extraction chain: PyMuPDF -> pdfplumber -> pdftotext; if total digital
text < 300 chars, OCR with tesseract at 300 dpi (eng, or afr+eng for
afr@ expressions). Section-level rows only where clean sequential
numbered headings are detectable; otherwise one document-level row.

Provenance: rows built from PDFs carry source_url = the work's public
expression page and xml_url = the source PDF URL itself, so it is
explicit in the data that these rows come from the source PDF, not
from AKN HTML (the tranche-1 convention of xml_url = AKN work URL is
deliberately NOT used for PDF rows).

Checkpointing: PDFs cached under pdfs/<MDB>/, every processed work
appended to progress.jsonl; re-running resumes without re-fetching.

Phases: download -> extract/segment/build merged parquets -> (separate
script) publish + remote verify.
"""
import gzip
import hashlib
import html as html_mod
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

import requests

REPO = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.normalize import make_row, finalize_rows, strip_tags  # noqa: E402
from world_municipal.schema import rows_to_table, validate_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report, read_html_parquet  # noqa: E402
from world_municipal.jurisdiction import get_scheme  # noqa: E402

BASE_DIR = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files"
OUT = BASE_DIR / "za_pdf_tranche"
V2 = BASE_DIR / "za_tranche1_v2"
PDFS = OUT / "pdfs"
TEXTS = OUT / "texts"
OUTD = OUT / "out"
for d in (PDFS, TEXTS, OUTD):
    d.mkdir(parents=True, exist_ok=True)

BASE = "https://openbylaws.org.za"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) world-municipal-law-pdf-tranche/0.1"}
DELAY = 6.0
RETRIEVED = "2026-10-12"
ZA = get_scheme("ZA")

PLACES = {
    "za-cpt":   ("CPT",   "City of Cape Town"),
    "za-jhb":   ("JHB",   "City of Johannesburg"),
    "za-eth":   ("ETH",   "eThekwini"),
    "za-wc013": ("WC013", "Bergrivier"),
    "za-wc033": ("WC033", "Cape Agulhas"),
    "za-wc012": ("WC012", "Cederberg"),
    "za-wc023": ("WC023", "Drakenstein"),
    "za-wc041": ("WC041", "Kannaland"),
    "za-wc011": ("WC011", "Matzikama"),
    "za-wc015": ("WC015", "Swartland"),
    "za-ec443": ("EC443", "Winnie Madikizela-Mandela"),
}
MDB_ORDER = ["CPT", "ETH", "JHB", "EC443", "WC011", "WC012", "WC013",
             "WC015", "WC023", "WC033", "WC041"]


class PoliteSession:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(UA)
        self.last_start = 0.0
        self.n_requests = 0

    def get(self, url, timeout=180):
        last_exc = None
        for attempt in range(4):
            wait = DELAY - (time.monotonic() - self.last_start)
            if self.last_start and wait > 0:
                time.sleep(wait)
            if attempt:
                time.sleep(10 * attempt)
            self.last_start = time.monotonic()
            try:
                r = self.s.get(url, timeout=timeout)
                self.n_requests += 1
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                return r
            except Exception as exc:  # noqa: BLE001
                self.n_requests += 1
                last_exc = exc
        raise last_exc


# ---------------------------------------------------------------- inputs
def load_excluded():
    """The 105 excluded works from the trusted v2 run manifest."""
    m = json.load(open(V2 / "run_manifest.json"))
    works = []
    for code in MDB_ORDER:
        v = m["municipalities"][code]
        for e in v["excluded"]:
            assert e["reason"].startswith("pdf_only_no_akn_html"), e
            works.append({"mdb": code, "name": v["name"], "place": v["place"],
                          "title": e["title"], "work": e["work"],
                          "expression": e["expression"], "lang": e["lang"],
                          "subtype": e["subtype"], "date": e["date"]})
    assert len(works) == 105, len(works)
    return works


def pdf_url_for(work):
    """Source PDF URL from the work's cached stub page (v2 cache, trusted).

    Falls back to expression + '/source.pdf' (the site's uniform pattern,
    verified on the stub markup) if no data-pdf link is found."""
    loc = work["expression"].replace(BASE, "")
    safe = loc.strip("/").replace("/", "__")
    p = V2 / "cache" / work["mdb"] / (safe + ".html.gz")
    if p.exists():
        t = gzip.open(p, "rt", encoding="utf-8", errors="replace").read()
        mm = re.search(r'data-pdf="([^"]+)"', t) or re.search(r'href="([^"]+/source\.pdf)"', t)
        if mm:
            return BASE + mm.group(1)
    return work["expression"] + "/source.pdf"


def pdf_path(work):
    loc = work["expression"].replace(BASE, "")
    safe = loc.strip("/").replace("/", "__")
    return PDFS / work["mdb"] / (safe + ".pdf")


# ---------------------------------------------------------------- download
def phase_download():
    works = load_excluded()
    prog_path = OUT / "progress.jsonl"
    done = {}
    if prog_path.exists():
        for line in open(prog_path):
            try:
                rec = json.loads(line)
                if rec.get("phase") == "download":
                    done[rec["key"]] = rec
            except Exception:  # noqa: BLE001
                pass
    prog = open(prog_path, "a")
    sess = PoliteSession()
    ok = fail = skip = 0
    for i, w in enumerate(works):
        key = w["expression"]
        p = pdf_path(w)
        if key in done and done[key].get("status") == "downloaded" and p.exists() and p.stat().st_size > 0:
            skip += 1
            continue
        url = pdf_url_for(w)
        w["pdf_url"] = url
        try:
            r = sess.get(url)
            content = r.content
            ctype = r.headers.get("Content-Type", "")
            if not content.startswith(b"%PDF"):
                raise ValueError(f"not a PDF (ctype={ctype}, first bytes {content[:40]!r})")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
            rec = {"phase": "download", "key": key, "status": "downloaded",
                   "pdf_url": url, "bytes": len(content),
                   "sha256": hashlib.sha256(content).hexdigest()[:16]}
            ok += 1
        except Exception as exc:  # noqa: BLE001
            rec = {"phase": "download", "key": key, "status": "failed",
                   "pdf_url": url, "error": str(exc)[:200]}
            fail += 1
        prog.write(json.dumps(rec) + "\n")
        prog.flush()
        if (i + 1) % 10 == 0 or i + 1 == len(works):
            print(f"[download] {i+1}/{len(works)} ok={ok} fail={fail} skip={skip} "
                  f"req={sess.n_requests}", flush=True)
    print(f"DOWNLOAD DONE ok={ok} fail={fail} skip={skip} requests={sess.n_requests}")


# ---------------------------------------------------------------- extract
def extract_pages(pdf):
    """Returns (pages[list[str]], method). Chain: fitz -> pdfplumber ->
    pdftotext -> OCR (tesseract 300dpi)."""
    import fitz  # PyMuPDF, scraping venv
    doc = fitz.open(pdf)
    pages = [pg.get_text() for pg in doc]
    total = sum(len(p.strip()) for p in pages)
    if total >= 300:
        return pages, "fitz"
    # pdfplumber
    try:
        import pdfplumber
        with pdfplumber.open(pdf) as pl:
            pages2 = [(pg.extract_text() or "") for pg in pl.pages]
        if sum(len(p.strip()) for p in pages2) >= 300:
            return pages2, "pdfplumber"
    except Exception:  # noqa: BLE001
        pass
    # pdftotext
    try:
        out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                             capture_output=True, timeout=600)
        txt = out.stdout.decode("utf-8", errors="replace")
        pages3 = txt.split("\f")
        if sum(len(p.strip()) for p in pages3) >= 300:
            return pages3, "pdftotext"
    except Exception:  # noqa: BLE001
        pass
    return pages, "fitz_lowtext"  # caller decides OCR


def _ocr_one(job):
    """Worker (own process): render one page at 300 dpi and OCR it.
    The page text is checkpointed to a per-page file before returning,
    so an interrupted OCR run loses at most the in-flight pages."""
    pdf, i, lang, page_file = job
    import fitz
    doc = fitz.open(pdf)
    pg = doc[i]
    pix = pg.get_pixmap(dpi=300)
    png = OUT / f"_ocr_tmp_{os.getpid()}.png"
    pix.save(png)
    env = dict(os.environ, OMP_THREAD_LIMIT="2")
    out = subprocess.run(["tesseract", str(png), "stdout", "-l", lang,
                          "--psm", "6"],
                         capture_output=True, timeout=1200, env=env)
    try:
        png.unlink()
    except Exception:  # noqa: BLE001
        pass
    txt = out.stdout.decode("utf-8", errors="replace")
    Path(page_file).write_text(txt)
    return i, txt


def ocr_pages(pdf, lang):
    """OCR every page at 300 dpi (tesseract, psm 6), pages processed
    in parallel across 4 worker processes, each page checkpointed
    under texts/_ocr_pages/<pdf-sha>/ so runs resume page-wise."""
    import concurrent.futures
    import fitz
    doc = fitz.open(pdf)
    n = doc.page_count
    doc.close()
    sha = hashlib.sha256(Path(pdf).read_bytes()).hexdigest()[:16]
    pdir = TEXTS / "_ocr_pages" / sha
    pdir.mkdir(parents=True, exist_ok=True)
    pages = [None] * n
    jobs = []
    for i in range(n):
        pf = pdir / f"p{i:04d}.txt"
        if pf.exists():
            pages[i] = pf.read_text()
        else:
            jobs.append((str(pdf), i, lang, str(pf)))
    if jobs:
        print(f"    OCR pages: {n - len(jobs)}/{n} checkpointed, "
              f"{len(jobs)} to run", flush=True)
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as ex:
            for i, txt in ex.map(_ocr_one, jobs):
                pages[i] = txt
    return pages


def get_pages(work):
    """Extract (and cache) per-page text for a downloaded PDF."""
    p = pdf_path(work)
    tp = TEXTS / work["mdb"] / (p.stem + ".json")
    if tp.exists():
        d = json.load(open(tp))
        return d["pages"], d["method"]
    pages, method = extract_pages(p)
    total = sum(len(x.strip()) for x in pages)
    if total < 300:
        lang = "afr+eng" if work["lang"] == "afr" else "eng"
        print(f"  OCR {work['mdb']} {p.name} pages={len(pages)} lang={lang}", flush=True)
        pages = ocr_pages(p, lang)
        method = "ocr_tesseract300"
    tp.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"pages": pages, "method": method}, open(tp, "w"))
    return pages, method


# ---------------------------------------------------------------- streams
REG = [json.loads(l) for l in open(BASE_DIR / "za_pilot" / "jurisdictions.jsonl")]


def _short_name(name):
    n = name
    for suf in (" Metropolitan Municipality", " Local Municipality",
                " District Municipality", " Municipality"):
        if n.endswith(suf):
            n = n[: -len(suf)]
    return n.strip()


SHORT2CODE = {}
for _r in REG:
    _s = _short_name(_r["name"]).upper()
    if len(_s) >= 4:
        SHORT2CODE[_s] = _r["jurisdiction_id"]
        # gazettes often print hyphenated names without the hyphen
        if "-" in _s:
            SHORT2CODE[_s.replace("-", " ")] = _r["jurisdiction_id"]
    if _r["jurisdiction_id"] in PLACES.values():
        pass
# place display names as they appear in gazette headings
for _place, (_code, _nm) in PLACES.items():
    SHORT2CODE.setdefault(_nm.upper(), _code)
SHORT2CODE.setdefault("ETHEKWINI", "ETH")
SHORT2CODE.setdefault("CITY OF CAPE TOWN", "CPT")
SHORT2CODE.setdefault("CITY OF JOHANNESBURG", "JHB")


def extract_streams(pdf):
    """Returns (streams dict name->list[page text], method).

    Two-column gazettes (English left / Afrikaans right) get separate
    left/right streams so segmentation can work on one language.
    """
    import fitz
    doc = fitz.open(pdf)
    linear, left, right = [], [], []
    twocol_pages = 0
    for pg in doc:
        linear.append(pg.get_text())
        width = pg.rect.width or 595.0
        mid = width / 2.0
        blocks = [b for b in pg.get_text("blocks") if b[6] == 0 and b[4].strip()]
        lb = sorted([b for b in blocks if (b[0] + b[2]) / 2 < mid and (b[2] - b[0]) <= 0.62 * width],
                    key=lambda b: (round(b[1] / 6), b[0]))
        rb = sorted([b for b in blocks if (b[0] + b[2]) / 2 >= mid and (b[2] - b[0]) <= 0.62 * width],
                    key=lambda b: (round(b[1] / 6), b[0]))
        fw = sorted([b for b in blocks if (b[2] - b[0]) > 0.62 * width],
                    key=lambda b: (round(b[1] / 6), b[0]))
        if lb and rb:
            twocol_pages += 1
        left.append("\n".join(b[4] for b in fw + lb))
        right.append("\n".join(b[4] for b in rb))
    total = sum(len(p.strip()) for p in linear)
    if total >= 300:
        streams = {"linear": linear}
        if doc.page_count and twocol_pages / max(1, doc.page_count) >= 0.3:
            streams["left"] = left
            streams["right"] = right
        return streams, "fitz"
    # fallbacks produce linear only
    pages, method = extract_pages(pdf)
    return {"linear": pages}, method


def get_streams(work):
    p = pdf_path(work)
    tp = TEXTS / work["mdb"] / (p.stem + ".streams.json")
    if tp.exists():
        d = json.load(open(tp))
        return d["streams"], d["method"]
    # identical source PDFs (same gazette issue serving several works)
    # share one extraction/OCR via a content-hash cache
    sha = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    hp = TEXTS / "_by_hash" / (sha + ".streams.json")
    if hp.exists():
        d = json.load(open(hp))
        tp.parent.mkdir(parents=True, exist_ok=True)
        json.dump(d, open(tp, "w"))
        return d["streams"], d["method"]
    streams, method = extract_streams(p)
    total = sum(len(x.strip()) for x in streams.get("linear", []))
    npages = max(1, len(streams.get("linear", [])))
    # OCR also when the PDF is mostly scanned images with only a
    # digital cover/contents layer (very low text density per page)
    if total < 300 or (npages >= 3 and total / npages < 200):
        lang = "afr+eng" if work["lang"] == "afr" else "eng"
        print(f"  OCR {work['mdb']} {p.name} lang={lang}", flush=True)
        pages = ocr_pages(p, lang)
        streams, method = {"linear": pages}, "ocr_tesseract300"
    tp.parent.mkdir(parents=True, exist_ok=True)
    payload = {"streams": streams, "method": method}
    json.dump(payload, open(tp, "w"))
    hp.parent.mkdir(parents=True, exist_ok=True)
    json.dump(payload, open(hp, "w"))
    return streams, method


# ---------------------------------------------------------------- segment
def _is_heading(s):
    s = s.strip()
    if not (4 <= len(s) <= 110):
        return False
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 4:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) > 0.8


def _stem(w):
    # 'repeals' -> 'repeal', 'meters' -> 'meter' (overlap regex adds S?)
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _distinctive(work):
    parts = work["work"].split("/")
    slug = "-".join(parts[6:]) if len(parts) > 6 else ""
    stop = {"by", "law", "bylaw", "the", "of", "and", "for", "act", "no"}
    dist = [_stem(w) for w in slug.split("-")
            if w not in stop and (len(w) >= 3 or w.isdigit())]
    if not dist or all(w.isdigit() for w in dist):
        # numeric-only slugs (notice numbers) carry no topic signal:
        # merge in title words
        tw = re.findall(r"[a-z0-9]+", work["title"].lower())
        for w in tw:
            if w not in stop and len(w) >= 4 and _stem(w) not in dist:
                dist.append(_stem(w))
    return dist


def _overlap(text_upper, dist):
    n = 0
    for w in dist:
        if re.search(r"\b" + re.escape(w.upper()) + r"S?\b", text_upper):
            n += 1
    return n


INTRO_EN = "Notice is hereby given in terms of section 13"
INTRO_AF = ("Kennis geskied hiermee ingevolge die bepalings van artikel 13",
            "Kennis geskied hiermee ingevolge artikel 13")


def _events(pages):
    """Boundary/title events: (page, offset, kind, detail)."""
    ev = []
    for pi, text in enumerate(pages):
        lines = text.split("\n")
        offs = []
        o = 0
        for ln in lines:
            offs.append(o)
            o += len(ln) + 1
        i = 0
        while i < len(lines):
            s = lines[i].strip()
            if ("appears every Friday" in s or "Subscription Rates" in s
                    or "Subscription per annum" in s
                    or s.upper().startswith(("ADVERTISEMENTS",
                                             "ADVERTENSIES"))):
                # gazette back matter (advertisement/subscription
                # notices and the advertisements section itself) is
                # never part of a promulgated instrument; checked
                # before heading consumption because the section
                # headers are themselves heading lines
                ev.append((pi, offs[i], "backmatter", ""))
            if _is_heading(s):
                # title block: up to 4 consecutive heading lines
                block = [s]
                j = i + 1
                while j < len(lines) and len(block) < 4 and _is_heading(lines[j]):
                    block.append(lines[j].strip())
                    j += 1
                joined = " ".join(block)
                ju = joined.upper()
                muni = None
                for name, code in SHORT2CODE.items():
                    # word-boundary match: raw substring matching
                    # misattributes blocks (e.g. 'NALA' inside
                    # 'KANNALAND' stole Kannaland's heading for FS185)
                    if re.search(r"\b" + re.escape(name) + r"\b", ju):
                        muni = code
                        break
                if muni:
                    ev.append((pi, offs[i], "muni", muni))
                elif "MUNISIPALITEIT" in ju or ju.startswith("STAD "):
                    ev.append((pi, offs[i], "muni", "GENERIC_AFR"))
                if ("BY-LAW" in ju or "BYLAW" in ju or "BY LAW" in ju
                        or "VERORDENING" in ju):
                    ev.append((pi, offs[i], "title", ju))
                i = j
                continue
            if INTRO_EN in s or any(p in s for p in INTRO_AF):
                ev.append((pi, offs[i], "intro", ""))
            i += 1
    ev.sort(key=lambda e: (e[0], e[1]))
    return ev


def _seg_text(pages, start, end):
    (sp, so), (ep, eo) = start, end
    if sp == ep:
        return pages[sp][so:eo]
    parts = [pages[sp][so:]]
    parts.extend(pages[sp + 1:ep])
    if ep < len(pages):
        parts.append(pages[ep][:eo])
    return "\n".join(parts)


def _normalize_page(t):
    # some gazette PDFs encode spaces as \x03 and hyphens as U+0370 etc.
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", t)
    t = t.replace("Ͳ", "-").replace("‐", "-").replace("‑", "-")
    return t


# Municipal-notice header lines in KZN-style gazettes open with
# '*M.N. <num>, <year> <day Month year>' (the Afrikaans '*M.K.' twin
# follows on the same line). OCR renders the 'M.N.' token loosely —
# 'MLN.', 'M.LN.', '*MLN.' — so the anchor tolerates a stray L and
# loose punctuation, but requires the ', <year>' that follows the
# number in a genuine header (in-text citations spell the reference
# out as 'Municipal Notice No. <num> of <year>').
_MN_HEAD = re.compile(r"M[.,\s]*L?N[.,\s]*\s*(\d{1,4})\s*,\s*(\d{4})\b")
_MK_HEAD = re.compile(r"M[.,\s]*L?K[.,\s]*\s*(\d{1,4})\s*,\s*(\d{4})\b")
_MN_LINE_NOISE = re.compile(r"^[\s|*!:;•]*[iIl]?[\s|*!:;•]*$")


def _mn_headers(pages):
    """Municipal-notice header events: (page, line_start_offset, num,
    year). Only line-initial matches count — a header opens its notice
    at the start of a line (behind at most OCR noise), while body
    citations sit mid-line. First match per line only: the bilingual
    twin header shares the line and the number.

    Twin-shared-line fallback: in two-column bilingual gazettes
    (e.g. the 1996 Durban issue) OCR merges the side-by-side columns
    into one line with the AFRIKAANS twin first — '*M.K. 104, 1996
    <date> *M.N. 104, 1996 <date>' — so the English token is not
    line-initial and the clean rule misses the header entirely (that
    issue's M.N. 104 and M.N. 105 were both invisible, while M.N. 103
    survived only because its English header sits alone on its own
    line). A line whose first token is a line-initial '*M.K.' header
    followed on the same line by the '*M.N.' twin of the SAME
    number+year (only the date between them) is therefore accepted
    as that notice's header line — but only when the stream has no
    clean line-initial event for that number+year, so streams whose
    headers the clean rule already finds (the 1998/1999 issues) keep
    exactly their previous event sets."""
    ev = []
    twin = {}
    for pi, text in enumerate(pages):
        off = 0
        for ln in text.split("\n"):
            hit = False
            for m in _MN_HEAD.finditer(ln):
                if _MN_LINE_NOISE.match(ln[:m.start()]):
                    ev.append((pi, off, int(m.group(1)), m.group(2)))
                    hit = True
                    break
            if not hit:
                mk = None
                for m in _MK_HEAD.finditer(ln):
                    if _MN_LINE_NOISE.match(ln[:m.start()]):
                        mk = m
                        break
                if mk is not None:
                    num, yr = int(mk.group(1)), mk.group(2)
                    for m in _MN_HEAD.finditer(ln):
                        if m.start() <= mk.start():
                            continue
                        if int(m.group(1)) != num or m.group(2) != yr:
                            continue
                        between = ln[mk.end():m.start()]
                        if len(between) <= 48 \
                                and not _MN_HEAD.search(between) \
                                and not _MK_HEAD.search(between):
                            twin.setdefault((num, yr), (pi, off, num, yr))
                            break
            off += len(ln) + 1
    have = {(n, y) for (_, _, n, y) in ev}
    for key, cand in twin.items():
        if key not in have:
            ev.append(cand)
    ev.sort(key=lambda e: (e[0], e[1]))
    return ev


def find_segment(pages, work):
    """Locate the work's instrument in one stream. Returns
    (segment_text, tier, start, end) or (None, reason, None, None)."""
    pages = [_normalize_page(p) for p in pages]
    code = work["mdb"]
    dist = _distinctive(work)
    if not dist:
        return None, "no_distinctive_terms", None, None
    need = max(1, -(-len(dist) // 2))  # ceil(0.5*len)
    ev = _events(pages)
    full_len = sum(len(p) for p in pages)

    def global_off(pi, off):
        return sum(len(pages[k]) + 1 for k in range(pi)) + off

    start = None
    tier = None
    def _guarded(pi, off):
        """True if the nearest preceding municipality heading (within
        2000 chars) belongs to a DIFFERENT municipality — i.e. this
        title sits inside another municipality's instrument and must
        not be attributed to this work."""
        g = global_off(pi, off)
        nearest = None
        for (p2, o2, k2, d2) in ev:
            if k2 != "muni":
                continue
            g2 = global_off(p2, o2)
            # <= : a municipality heading in the SAME heading block as
            # the title identifies whose instrument the title is
            if g2 <= g and g - g2 <= 2000:
                if nearest is None or g2 > nearest[0]:
                    nearest = (g2, d2)
        return bool(nearest and nearest[1] not in (code, "GENERIC_AFR"))

    # P0: municipal-notice header anchor. A work identified by a
    # gazette notice number (/act/mn/<year>/<num>) is keyed to the
    # '*M.N. <num>, <year>' header line that opens its notice: notice
    # numbers run sequentially across a gazette issue, so number+year
    # identifies the work even when sibling notices share one title
    # and identical heading wording (mn/1998/50-52, indistinguishable
    # to the title tiers) and when the gazette's own heading diverges
    # from the AKN title (mn/1999/7: 'ELECTRICITY BYLAWS: CORRECTION'
    # carries neither 'supply' nor the council name the title needs,
    # and the pre-2000 council name matches no registry short name,
    # so no muni event exists for the title tiers to key on). No
    # _guarded check: number+year identity is stronger than the
    # municipality-proximity heuristic. The segment runs to the next
    # notice header (mn_end cap) or the first boundary the generic
    # end scan finds, whichever is earlier.
    parts = work["work"].split("/")
    mn_end = None
    if len(parts) >= 7 and parts[4] == "mn" and parts[6].isdigit():
        mnum, myear = int(parts[6]), parts[5]
        mn_ev = _mn_headers(pages)
        topic = [d for d in dist if d != str(mnum)]
        for (pi, off, num, yr) in mn_ev:
            if num != mnum or yr != myear:
                continue
            after = pages[pi][off:off + 2000].upper()
            if topic and _overlap(after, topic) < 1:
                continue
            start = (pi, off)
            tier = "mn-header"
            gstart0 = global_off(pi, off)
            later = [(p2, o2) for (p2, o2, n2, y2) in mn_ev
                     if global_off(p2, o2) > gstart0]
            if later:
                mn_end = min(later)
            break

    # P0b: title-anchored notice binding. A by-law work promulgated
    # in a multi-notice gazette carries no notice number in its id
    # (water-supply is /act/by-law/1996/water-supply, so P0's id test
    # never engages), but the gazette still keys it to exactly one
    # notice: the promulgation preamble — the text between the
    # notice header and the instrument's own heading — names the
    # instrument in full ('hereby publishes the following Water
    # Supply Bylaws'), while a sibling notice's preamble names its
    # own instrument (M.N. 103's preamble names the Durban
    # Metropolitan Tariffs, even though M.N. 103's Schedule I is
    # HEADED 'DURBAN METROPOLITAN WATER SUPPLY BYLAWS'). So a header
    # of the work's year binds the work when (a) the first
    # full-overlap title heading after it (before the next header,
    # within preamble reach) is the instrument's heading and (b) the
    # text between header and heading itself carries the work's full
    # distinctive terms. Full overlap — every distinctive term — is
    # required at both points: the loose half-threshold is what let
    # M.N. 103's 'WATER' tariff heading open the water-supply
    # segment under tier title and run through M.N. 105. If more
    # than one header qualifies, the binding is ambiguous and this
    # tier abstains (fail safe, as P0 does on a missing header).
    if not start and len(dist) >= 2 and len(parts) >= 6 \
            and len(parts[5]) == 4 and parts[5].isdigit():
        wyear = parts[5]
        mn_ev = _mn_headers(pages)
        heads = [(p2, o2) for (p2, o2, n2, y2) in mn_ev if y2 == wyear]
        bound = []
        if len(heads) >= 2:
            for (hpi, hoff) in heads:
                gh = global_off(hpi, hoff)
                nxt = [global_off(p2, o2) for (p2, o2) in heads
                       if global_off(p2, o2) > gh]
                gcap = min(nxt) if nxt else None
                for (pi, off, kind, det) in ev:
                    if kind != "title":
                        continue
                    g = global_off(pi, off)
                    if g <= gh or (gcap is not None and g >= gcap):
                        continue
                    if g - gh > 4000:
                        break
                    if _overlap(det, dist) < len(dist):
                        continue
                    between = _seg_text(pages, (hpi, hoff), (pi, off))
                    if _overlap(between.upper(), dist) >= len(dist):
                        bound.append((hpi, hoff))
                    break
        if len(bound) == 1:
            start = bound[0]
            tier = "mn-header-title"
            gstart0 = global_off(*start)
            later = [(p2, o2) for (p2, o2, n2, y2) in mn_ev
                     if global_off(p2, o2) > gstart0]
            if later:
                mn_end = min(later)

    # P1: title block with muni/intro proximity; P2: title block alone
    for strict in (True, False):
        if start:
            break
        for (pi, off, kind, det) in ev:
            if kind != "title" or _overlap(det, dist) < need:
                continue
            if _guarded(pi, off):
                continue
            if strict:
                g = global_off(pi, off)
                near = any(
                    (k2 == "muni" and d2 == code) or k2 == "intro"
                    for (p2, o2, k2, d2) in ev
                    if 0 <= g - global_off(p2, o2) <= 1600)
                if not near:
                    continue
                # back up to the nearby muni/intro/title start, but
                # only on the title's own page or the one before it:
                # gazette half-page columns are short, so a bare
                # 1600-char reach can span 3 pages and land on a
                # sibling instrument's heading block
                cands = [(p2, o2) for (p2, o2, k2, d2) in ev
                         if ((k2 == "muni" and d2 == code) or k2 == "intro")
                         and 0 <= g - global_off(p2, o2) <= 1600
                         and pi - p2 <= 1]
                start = min(cands + [(pi, off)])
                tier = "title+muni/intro"
            else:
                start = (pi, off)
                tier = "title"
            break
        if start:
            break
    # P3: our muni heading + a matching title event shortly after
    if not start:
        for (pi, off, kind, det) in ev:
            if kind == "muni" and det == code and not _guarded(pi, off):
                g = global_off(pi, off)
                near_title = any(
                    k2 == "title" and _overlap(d2, dist) >= 1
                    and 0 <= global_off(p2, o2) - g <= 2600
                    for (p2, o2, k2, d2) in ev)
                if near_title:
                    start = (pi, off)
                    tier = "muni+terms"
                    break
    # P3b: loose fallback — our muni heading + distinctive terms in the
    # following text (for notices whose heading carries no BY-LAW title
    # line); scored with a penalty at selection time
    if not start:
        for (pi, off, kind, det) in ev:
            if kind == "muni" and det == code and not _guarded(pi, off):
                seg = pages[pi][off:off + 2600]
                if _overlap(seg.upper(), dist) >= max(1, min(2, len(dist))):
                    start = (pi, off)
                    tier = "muni+terms-loose"
                    break
    # P4: whole document fallback
    if not start:
        whole = "\n".join(pages)
        other_muni = any(k == "muni" and d not in (code, "GENERIC_AFR")
                         for (_, _, k, d) in ev)
        if (len(pages) <= 30 and not other_muni
                and _overlap(whole.upper(), dist) >= need):
            return whole, "whole_document", (0, 0), (len(pages), 0)
        return None, "instrument_not_located_in_source_pdf", None, None

    # end: first boundary after start (+1000 chars grace for stacked
    # bilingual promulgation blocks on the same page). Title-identity
    # tracking: the first matching title after the start is the
    # instrument's own; a later DIFFERENT title (incl. a sibling
    # amendment of the same municipality that merely shares a generic
    # word like 'amendment') opens a new instrument.
    gstart = global_off(*start)
    end = (len(pages), 0)
    seen_title = None
    _GENERIC = {"amendment", "correction", "commencement", "repeal",
                "substitution", "further", "second", "first", "annual",
                "special", "general"}
    topic = [w for w in dist if w not in _GENERIC]

    def _foreign_title(det):
        """A title is foreign if it shares no topic (non-generic)
        distinctive word with this work — running heads and preamble
        headings of the SAME instrument share its topic words, while
        sibling instruments (tariff vs property-rates amendments)
        share only generic words."""
        if topic:
            return not any(re.search(r"\b" + re.escape(w) + r"s?\b",
                                     det, re.I) for w in topic)
        return _overlap(det, dist) == 0

    for (pi, off, kind, det) in ev:
        g = global_off(pi, off)
        if g <= gstart + 1000:
            if kind == "title" and _overlap(det, dist) >= 1 and seen_title is None:
                seen_title = det
            continue
        if kind in ("intro", "backmatter"):
            end = (pi, off)
            break
        if kind == "muni" and det != code:
            end = (pi, off)
            break
        if kind == "muni" and det == code:
            nxt = [d2 for (p2, o2, k2, d2) in ev
                   if k2 == "title" and 0 < global_off(p2, o2) - g <= 2000]
            if not nxt:
                # running heads repeat the municipality name on every
                # page of a long instrument; if the text right after
                # the heading still carries this work's topic words it
                # is the same instrument, not a new one
                peek = pages[pi][off:off + 400].upper()
                if topic and any(re.search(r"\b" + re.escape(t) + r"s?\b",
                                           peek, re.I) for t in topic):
                    continue
                end = (pi, off)
                break
            if seen_title is not None and nxt[0] != seen_title \
                    and _foreign_title(nxt[0]):
                end = (pi, off)
                break
            if seen_title is None and _overlap(nxt[0], dist) == 0:
                end = (pi, off)
                break
            continue
        if kind == "title":
            if seen_title is None and _overlap(det, dist) >= 1:
                seen_title = det
                continue
            if det != seen_title and _foreign_title(det):
                end = (pi, off)
                break
    if mn_end is not None and global_off(*mn_end) < global_off(*end):
        end = mn_end
    seg = _seg_text(pages, start, end)
    # backward extension: if the segment opens mid-instrument (first
    # numbered item > 1), try to extend back to a nearby heading block
    first_nums = [n for n in (_num_of(ln) for ln in seg.split("\n")[:80])
                  if n is not None]
    # an mn-header start (P0/P0b) is the notice's first line by
    # construction — never extend it back into the previous notice
    if not tier.startswith("mn-header") and first_nums and first_nums[0] > 1:
        gstart = global_off(*start)
        cands = [(p2, o2) for (p2, o2, k2, d2) in ev
                 if 0 < gstart - global_off(p2, o2)
                 and start[0] - p2 <= 3
                 and ((k2 == "muni" and d2 == code)
                      or (k2 == "title" and _overlap(d2, dist) >= 1))]
        for cand in reversed(cands):
            if _guarded(*cand):
                continue
            gc = global_off(*cand)
            blocked = any(
                gc < global_off(p3, o3) < gstart
                and (k3 in ("intro", "backmatter")
                     or (k3 == "muni" and d3 != code)
                     or (k3 == "title" and _overlap(d3, dist) == 0))
                for (p3, o3, k3, d3) in ev)
            if not blocked:
                start = cand
                tier += "+extended"
                seg = _seg_text(pages, start, end)
                break
    seg = _trim_foreign_prefix(seg, work)
    return seg, tier, start, end


def _trim_foreign_prefix(seg, work):
    """Gazette items are often preceded (in reading order) by the
    parallel-language version of the same instrument. If the segment
    opens in a different language than the work's expression and a
    heading carrying the work's full distinctive title appears shortly
    after, cut everything before that heading."""
    want = "afr" if work.get("lang") == "afr" else "eng"
    if _dominant_lang(seg[:400]) == want:
        return seg
    dist = _distinctive(work)
    need = max(2, -(-len(dist) // 2))
    lines = seg.split("\n")
    for i, ln in enumerate(lines):
        if _is_heading(ln) and _overlap(ln.upper(), dist) >= need:
            prefix = "\n".join(lines[:i])
            if 0 < len(prefix) < 4000 and _dominant_lang(prefix) != want:
                return "\n".join(lines[i:])
            return seg
    return seg


_EN_WORDS = (" the ", " of ", " and ", " to ", " in ", " is ", " shall ",
             " council ", " by-law ")
_AF_WORDS = (" die ", " van die ", " 'n ", " en ", " verordening ",
             " munisipaliteit ", " raad ")
_XH_WORDS = ("umasipala", "umthetho", "ngokwe", "isihlomelo", "kwe")


def _dominant_lang(text):
    t = " " + text.lower() + " "
    en = sum(t.count(w) for w in _EN_WORDS)
    af = sum(t.count(w) for w in _AF_WORDS)
    xh = sum(t.count(w) for w in _XH_WORDS)
    best = max(en, af, xh)
    if best == 0:
        return "eng"
    return "eng" if best == en else ("afr" if best == af else "xho")


def score_segment(seg, work):
    """Plausibility score for choosing among streams' segments."""
    if not seg:
        return -99
    s = 0.0
    head = seg[:1200]
    if any(_is_heading(ln) for ln in head.split("\n") if ln.strip()):
        s += 2
    dist = _distinctive(work)
    if _overlap(head.upper(), dist) >= max(1, len(dist) // 2):
        s += 1
    head_lines = [ln for ln in head.split("\n") if ln.strip()]
    if len(dist) >= 2 and any(
            _is_heading(ln) and _overlap(ln.upper(), dist) == len(dist)
            for ln in head_lines):
        s += 1
    # a title heading for a DIFFERENT topic inside the head marks a
    # grab-bag segment spanning neighbouring instruments
    _GEN = {"amendment", "correction", "commencement", "repeal",
            "substitution", "further", "second", "first", "annual",
            "special", "general"}
    topic = [w for w in dist if w not in _GEN]
    if topic:
        for ln in head_lines:
            u = ln.upper()
            if _is_heading(ln) and ("BY-LAW" in u or "BYLAW" in u
                                    or "BY LAW" in u or "VERORDENING" in u) \
                    and not any(re.search(r"\b" + re.escape(w) + r"s?\b",
                                          u, re.I) for w in topic):
                s -= 2
                break
    nums = [n for n in (_num_of(ln) for ln in seg.split("\n")[:120])
            if n is not None]
    if nums:
        s += 2 if nums[0] == 1 else -2
    if len(seg) > 200000:
        s -= 2
    # language: prefer the stream whose dominant language matches the
    # work's expression language (gazettes print parallel versions).
    # Judged on the OPENING 1000 chars: a segment can open in a
    # parallel version and still contain our language later (embedded
    # sibling text), which must not earn it the language bonus.
    want = "afr" if work.get("lang") == "afr" else "eng"
    dom = _dominant_lang(seg[:1000])
    s += 2 if dom == want else -2
    s += min(len(seg) / 30000.0, 1.0)
    return s


_FOOTER_RES = [
    re.compile(r"^\d{3,5}$"),
    re.compile(r"^\d{1,3}$"),
    re.compile(r"^(Province of|Provinsie).{0,60}Provincial Gazette.*$", re.I),
    re.compile(r"^Provincial Gazette\s+\d+.*$", re.I),
    re.compile(r"^\d{1,2}\s+(January|February|March|April|May|June|July|August|"
               r"September|October|November|December|Januarie|Februarie|Maart|"
               r"April|Mei|Junie|Julie|Augustus|September|Oktober|November|"
               r"Desember)\s+\d{4}$"),
    re.compile(r"^(The|Die)\s+.{0,40}Provincial Gazette.{0,80}$", re.I),
]


def clean_segment(text):
    out = []
    for ln in text.split("\n"):
        s = ln.strip()
        if s and any(r.match(s) for r in _FOOTER_RES):
            continue
        out.append(ln)
    txt = "\n".join(out)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


# ---------------------------------------------------------------- units
_NUM_START = re.compile(r"^\s*(\d{1,3})[.)]\s+(\S.*)$")
_NUM_ALONE = re.compile(r"^\s*(\d{1,3})[.)]\s*$")
_HEAD_LINE = re.compile(r"^[A-Z][A-Za-z0-9 ,.'’&/()\-]{2,70}$")


def _num_of(line):
    m = _NUM_START.match(line) or _NUM_ALONE.match(line)
    return int(m.group(1)) if m else None


def split_units(text):
    """Split a segment into units on sequential numbered items.
    Returns list of (uid, label, body_text). Falls back to a single
    document-level unit when no clean sequence exists.

    Gazette instruments often open with an ARRANGEMENT OF SECTIONS
    (contents) whose entries mimic section starts. All candidate
    starts are collected; every run of 1,2,3,... is scored by the
    text it covers, and the best-scoring run (the body, not the
    contents) is used."""
    lines = text.split("\n")
    cands = []
    for i, ln in enumerate(lines):
        n = _num_of(ln)
        if n is not None and len(ln.strip()) >= 2:
            cands.append((i, n))
    starts = []
    best_score = -1
    for j, (idx, n) in enumerate(cands):
        if n != 1:
            continue
        # greedy sequential run to EOF (like a contents-free scan):
        # non-matching candidates are skipped, never break the run
        run = [(idx, 1)]
        exp = 2
        for (i2, n2) in cands[j + 1:]:
            if n2 == exp:
                run.append((i2, n2))
                exp += 1
        if len(run) < 3:
            continue
        # substance score: contents entries have one-line bodies and
        # score ~nothing; real sections carry text (capped per item
        # so one giant tail cannot dominate)
        score = 0
        for k, (i4, _n4) in enumerate(run):
            nxt = run[k + 1][0] if k + 1 < len(run) else len(lines)
            body = sum(len(lines[m]) for m in range(i4, nxt))
            score += min(body, 4000)
        if score > best_score:
            best_score = score
            starts = [(i, num, lines[i].strip()) for (i, num) in run]
    if len(starts) >= 3:
        units = []
        first_idx = starts[0][0]
        # preamble: heading line(s) right before item 1 are its label;
        # anything earlier with real content becomes a preamble unit
        pre_end = first_idx
        lbl = None
        if first_idx >= 1 and _HEAD_LINE.match(lines[first_idx - 1].strip()) \
                and not _NUM_START.match(lines[first_idx - 1]):
            lbl = lines[first_idx - 1].strip()
            pre_end = first_idx - 1
        pre = "\n".join(lines[:pre_end]).strip()
        if len(pre) >= 300:
            units.append(("preamble", "preamble", pre))
        for k, (idx, num, _rest) in enumerate(starts):
            end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
            label = f"Section {num}"
            # named heading directly above this item (within 1 line)
            if idx >= 1:
                cand = lines[idx - 1].strip()
                if _HEAD_LINE.match(cand) and not _NUM_START.match(lines[idx - 1]) \
                        and len(cand) >= 3:
                    label = cand
            if k == 0 and lbl:
                label = lbl
            body = "\n".join(lines[idx:end]).strip()
            if len(body) >= 40:
                units.append((f"sec-{num}", label, body))
        if len(units) >= 3:
            return units
    return [("document", "document", text)]


def _body_html(text):
    paras = []
    for chunk in re.split(r"\n\s*\n", text):
        chunk = chunk.strip()
        if chunk:
            paras.append("<p>" + html_mod.escape(chunk).replace("\n", "<br/>") + "</p>")
    if not paras:
        paras = ["<p>" + html_mod.escape(text.strip()).replace("\n", "<br/>") + "</p>"]
    return "".join(paras)


# ---------------------------------------------------------------- build
def phase_build():
    import pyarrow.parquet as pq
    from huggingface_hub import HfApi, hf_hub_download

    works = load_excluded()
    # download checkpoint
    dl = {}
    prog_path = OUT / "progress.jsonl"
    if prog_path.exists():
        for line in open(prog_path):
            try:
                rec = json.loads(line)
                if rec.get("phase") == "download":
                    dl[rec["key"]] = rec
            except Exception:  # noqa: BLE001
                pass

    # live baseline parquets (fresh download)
    live_dir = OUT / "live"
    live_dir.mkdir(exist_ok=True)
    api = HfApi()
    REPO_ID = "endomorphosis/ipfs_south_africa_municipal_laws"
    old_rows, old_tables = {}, {}
    for code in MDB_ORDER:
        p = hf_hub_download(REPO_ID, f"data/{code}_html.parquet",
                            repo_type="dataset", local_dir=str(live_dir))
        t = pq.read_table(p)
        old_tables[code] = t
        old_rows[code] = t.to_pylist()
    baseline = {c: len(r) for c, r in old_rows.items()}
    print("baseline:", baseline, "total", sum(baseline.values()), flush=True)
    assert sum(baseline.values()) == 15439, baseline

    # cumulative manifest: municipalities processed in earlier runs
    # (e.g. CPT) are preserved when this run covers a subset
    mf_path = OUT / "run_manifest.json"
    manifest = {"retrieved": RETRIEVED, "baseline_rows": baseline,
                "baseline_total": 15439, "municipalities": {}}
    if mf_path.exists():
        prev = json.load(open(mf_path))
        if prev.get("baseline_total") == 15439:
            manifest["municipalities"] = prev.get("municipalities", {})
    prog = open(prog_path, "a")

    order = MDB_ORDER
    if len(sys.argv) > 2 and sys.argv[2]:
        order = [c.strip() for c in sys.argv[2].split(",") if c.strip()]
    for code in order:
        jname = PLACES[[k for k, v in PLACES.items() if v[0] == code][0]][1]
        code_norm = ZA.normalize(code)
        mworks = [w for w in works if w["mdb"] == code]
        new_rows = []
        recovered, excluded = [], []
        overrides = {}
        ov_path = OUT / "excluded_overrides.json"
        if ov_path.exists():
            overrides = json.load(open(ov_path))
        for w in mworks:
            key = w["expression"]
            if w["work"] in overrides:
                excluded.append({"work": w["work"], "title": w["title"],
                                 "status": "excluded",
                                 "reason": overrides[w["work"]]})
                continue
            rec_dl = dl.get(key, {})
            if rec_dl.get("status") != "downloaded" or not pdf_path(w).exists():
                info = {"work": w["work"], "title": w["title"],
                        "status": "excluded",
                        "reason": f"pdf_download_failed: {rec_dl.get('error', 'not downloaded')}"}
                excluded.append(info)
                continue
            w["pdf_url"] = rec_dl.get("pdf_url") or pdf_url_for(w)
            try:
                streams, method = get_streams(w)
            except Exception as exc:  # noqa: BLE001
                excluded.append({"work": w["work"], "title": w["title"],
                                 "status": "excluded",
                                 "reason": f"pdf_extract_failed: {str(exc)[:160]}"})
                continue
            total_chars = sum(len(x.strip()) for x in streams.get("linear", []))
            if total_chars < 300:
                excluded.append({"work": w["work"], "title": w["title"],
                                 "status": "excluded", "method": method,
                                 "reason": f"no_usable_text: {total_chars} chars after full extraction chain incl. OCR"})
                continue
            # stream preference by language
            order = (["right", "linear", "left"] if w["lang"] == "afr"
                     else ["left", "linear", "right"])
            seg = tier = sname = None
            seg_start = seg_end = None
            best_score = -99
            for nm in order:
                if nm not in streams:
                    continue
                s, t, st, en = find_segment(streams[nm], w)
                if s:
                    sc = score_segment(clean_segment(s), w)
                    if t == "muni+terms-loose":
                        sc -= 1.0
                    if sc > best_score:
                        seg, tier, sname, seg_start, seg_end = s, t, nm, st, en
                        best_score = sc
            if not seg:
                excluded.append({"work": w["work"], "title": w["title"],
                                 "status": "excluded", "method": method,
                                 "reason": "instrument_not_located_in_source_pdf"})
                continue
            seg = clean_segment(seg)
            if len(seg) < 200:
                excluded.append({"work": w["work"], "title": w["title"],
                                 "status": "excluded", "method": method,
                                 "reason": f"segment_too_short: {len(seg)} chars"})
                continue
            units = split_units(seg)
            parts = w["work"].split("/")
            year = parts[5] if len(parts) > 5 else ""
            slug = "-".join(parts[6:]) if len(parts) > 6 else ""
            wrows = []
            for uid, label, body in units:
                if len(body.strip()) < 20:
                    continue
                wrows.append(make_row(
                    jurisdiction_id=code_norm, jurisdiction_name=jname,
                    country="ZA",
                    doc_id=f"{year}-{slug}-{uid}".replace("_", "-"),
                    regeling_id=w["work"], regeling_work_id=w["work"],
                    title=w["title"],
                    structural_path=f"{jname} > {w['title']} > {label}",
                    node_label=label, body_html=_body_html(body),
                    source_url=w["expression"], xml_url=w["pdf_url"],
                    date_effective=w["date"], retrieved=RETRIEVED,
                ))
            if not wrows:
                excluded.append({"work": w["work"], "title": w["title"],
                                 "status": "excluded", "method": method,
                                 "reason": "segment_yielded_no_rows"})
                continue
            new_rows.extend(wrows)
            info = {"work": w["work"], "title": w["title"],
                    "status": "recovered", "rows": len(wrows),
                    "units": "section" if len(units) > 1 or units[0][0] != "document" else "document",
                    "method": method, "stream": sname, "tier": tier,
                    "seg_pages": [seg_start[0] if seg_start else None,
                                  seg_end[0] if seg_end else None],
                    "seg_chars": len(seg), "pdf_url": w["pdf_url"],
                    "pdf_bytes": rec_dl.get("bytes")}
            recovered.append(info)
            prog.write(json.dumps({"phase": "build", "key": key, **info}) + "\n")
            prog.flush()
            print(f"[{code}] recovered {w['work']} rows={len(wrows)} "
                  f"method={method} stream={sname} tier={tier}", flush=True)

        combined = old_rows[code] + new_rows
        combined = finalize_rows(combined)
        # preservation check: first N rows identical to live rows
        assert len(combined) == len(old_rows[code]) + len(new_rows)
        for a, b in zip(old_rows[code], combined):
            for kkey in a:
                assert str(a[kkey]) == str(b[kkey]), (code, kkey, a.get("doc_id"))
        table = rows_to_table(combined)
        errors = validate_table(table, jurisdiction_id=code_norm,
                                jurisdiction_name=jname, country="ZA")
        if errors:
            print(f"{code}: VALIDATION FAILED {errors}", flush=True)
            manifest["municipalities"][code] = {
                "name": jname, "valid": False, "errors": errors,
                "recovered": recovered, "excluded": excluded}
            json.dump(manifest, open(OUT / "run_manifest.json", "w"),
                      indent=2, ensure_ascii=False)
            continue
        outp = OUTD / f"{code}_html.parquet"
        write_html_parquet(outp, table)
        reread = read_html_parquet(outp)
        report = validation_report(reread, jurisdiction_id=code_norm,
                                   jurisdiction_name=jname, country="ZA")
        write_validation_report(OUTD / f"{code}_validation.json", report)
        assert report["valid"], report
        manifest["municipalities"][code] = {
            "name": jname, "valid": True,
            "rows_before": baseline[code], "rows_after": table.num_rows,
            "works_recovered": len(recovered),
            "works_excluded": len(excluded),
            "new_rows": len(new_rows),
            "recovered": recovered, "excluded": excluded}
        json.dump(manifest, open(OUT / "run_manifest.json", "w"),
                  indent=2, ensure_ascii=False)
        print(f"{code}: before={baseline[code]} after={table.num_rows} "
              f"recovered={len(recovered)}/{len(mworks)} OK", flush=True)

    tot_rec = sum(v.get("works_recovered", 0) for v in manifest["municipalities"].values())
    tot_ex = sum(v.get("works_excluded", 0) for v in manifest["municipalities"].values())
    tot_after = sum(v.get("rows_after", 0) for v in manifest["municipalities"].values())
    print(f"BUILD DONE recovered={tot_rec} excluded={tot_ex} rows {15439} -> {tot_after}")


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "download"
    if phase == "download":
        phase_download()
    elif phase == "build":
        phase_build()
    else:
        raise SystemExit(f"unknown phase {phase}")
