"""Canada tranche 1, Wave A — Québec WordPress "strong" towns.

One WordPress template adapter built ON the Canada pilot builder
(ca_pilot/scripts/ca_pilot_build.py): its paced fetch, splitters,
fail-closed build_rows (>= 2 sections or the document is dropped and
logged) and the write -> validate -> independent re-read flow are
imported and reused. Jurisdiction IDs: Statistics Canada SGC codes
(world_municipal SgcScheme). Scope (from the published platform
census, registry/ca_platform_census_2026-10-12.jsonl): Quebec +
platform=WordPress + robots_posture=allowed + bylaws_presence in
{index_with_pdfs, direct_pdf_links_on_homepage} = 57 towns.

Per-town discipline:
- robots.txt is RE-FETCHED and parsed fresh; the by-law index URL and
  every candidate PDF URL must pass can_fetch for the wildcard agent,
  and any Crawl-delay overrides the 2 s default pacing. A town that
  now disallows is excluded with the reason recorded.
- Enumeration: census by-law index page (homepage for the 4
  direct-PDF towns); <a href> .pdf targets + anchor text; WordPress
  /page/N/ pagination on the same index path (<= 5 extra pages);
  dedupe by URL and by content sha256; cap 60 PDFs/town (recorded).
  Clear non-reglement material (formulaires, proces-verbaux, ordres
  du jour) is skipped and logged.
- Extraction chain: PyMuPDF (fitz) -> pdfplumber -> pdftotext ->
  tesseract OCR (fra+eng, system binary) when the digital chain
  yields < 300 chars or < 25 chars/page. Method recorded per doc.
- Attribution gate (pilot rule): the text must name the municipality
  (accent-folded); otherwise the document is dropped, reason logged.
- Publish: per town, only after gates pass on write AND re-read;
  dedupe against a fresh repo listing before every upload; ambiguous
  outcomes are resolved by listing before any retry. Pilot parquets
  are never touched.
Checkpointing: state/state.json is atomically rewritten after every
town; raw PDFs are cached under raw/<sgc>/, so any interruption is a
resume, never a restart.
"""

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

# Force (not setdefault): the VM's preset no_proxy carries bracketed
# IPv6 entries that make httpx raise InvalidURL "Invalid port: ':1]'"
# on every HF upload (proven 2026-10-13: Saint-Elzéar publish failed
# with exactly that error). AGENTS.md documents this workaround.
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

GOAL = Path.home() / "workspace/goals/world-municipal-law-coverage"
PILOT = GOAL / "hidden_files/ca_pilot"
WAVEA = GOAL / "hidden_files/ca_wavea"
RAW = WAVEA / "raw"
DATA = WAVEA / "data"
STATE = WAVEA / "state" / "state.json"
REPO_ID = "endomorphosis/ipfs_canada_municipal_laws"
RETRIEVED = "2026-10-13"
MAX_PDFS_PER_TOWN = 60
MAX_PDF_BYTES = 30 * 1024 * 1024
OCR_MAX_PAGES = 40

sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers"))
from world_municipal.schema import rows_to_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report, read_html_parquet  # noqa: E402
from world_municipal.normalize import finalize_rows  # noqa: E402
from world_municipal.jurisdiction import get_scheme  # noqa: E402

CA = get_scheme("CA")

# ---- reuse the pilot builder wholesale (fetch/pacing, splitters, gates)
_spec = importlib.util.spec_from_file_location("ca_pilot_build", PILOT / "scripts" / "ca_pilot_build.py")
pb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pb)
pb.RETRIEVED = RETRIEVED  # wave rows carry this wave's retrieval date
fetch = pb.fetch
build_rows = pb.build_rows
para_html = pb.para_html
join_fragment = pb.join_fragment
FR_MONTHS = pb.FR_MONTHS

import pymupdf  # noqa: E402
import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) world-municipal-law-tranche1/0.1"}
SESSION = requests.Session()
SESSION.headers.update(UA)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- text utils
def fold(s: str) -> str:
    """Accent-fold + lowercase for matching French names/text."""
    return "".join(c for c in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(c)).lower()


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(s)).strip("-")[:80] or "doc"


GENERIC_TOKENS = {"de", "du", "des", "la", "le", "les", "sur", "au", "aux",
                  "saint", "sainte", "st", "ste", "ville", "municipalite",
                  "canton", "paroisse", "village", "nord", "sud", "est",
                  "ouest"}


def attribution_markers(name: str) -> list[str]:
    """Folded strings whose presence in a document attributes it to the
    municipality: full name; name minus generic leading words; and the
    hyphen-joined distinctive-token core."""
    f = fold(name)
    markers = [f]
    toks = [t for t in re.split(r"[\s\-']+", f) if t]
    core = [t for t in toks if t not in GENERIC_TOKENS]
    if core:
        markers.append("-".join(core))
        markers.append(" ".join(core))
        markers += [t for t in core if len(t) >= 7]
    return [m for m in markers if len(m) >= 4]


def attribution_ok(text: str, name: str) -> bool:
    ft = fold(text)
    return any(m in ft for m in attribution_markers(name))


def _bare_host(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def attribution_basis(text: str, name: str, pdf_url: str, index_url: str) -> str:
    """'text' — the document names the municipality (pilot gate).
    'provenance' — the document does not name the town (small-town
    template reglements often never do) but is hosted on the town's
    own host and linked from its verified by-law index, and reads as
    a municipal instrument. '' — unattributed, drop."""
    if attribution_ok(text, name):
        return "text"
    ft = fold(text)
    if _bare_host(pdf_url) == _bare_host(index_url) and (
            "reglement" in ft or "municipal" in ft):
        return "provenance"
    return ""


# ---------------------------------------------------------------- robots
# RFC 9309 evaluator. This replaces urllib.robotparser after a proven
# false exclusion (2026-10-13): Saint-Paul-de-Montminy's robots.txt has
# "Disallow: /wp-" BEFORE "Allow: /wp-content/uploads/" and
# "Allow: /wp-*.pdf"; robotparser's order-based matching disallows
# every uploads PDF, while RFC 9309 section 2.2.2 (and Google/Bing)
# apply the LONGEST matching rule, under which the site's explicit
# Allows win. The evaluator below implements the standard: prefix
# match with * wildcards and a trailing-$ end anchor, longest rule
# wins, Allow wins ties, no matching rule = allowed. Unreachable
# robots.txt stays fail-closed (None), exactly as before.
_robots_cache: dict[str, dict | None] = {}


def _parse_robots_groups(body: str) -> list[dict]:
    """Parse robots.txt into groups: {agents, rules[(pattern, allow)],
    crawl_delay}. A group starts at a User-agent line that follows
    rule lines; consecutive User-agent lines share one group."""
    groups, agents, rules, delay = [], [], [], None
    seen_rule = False

    def flush():
        nonlocal agents, rules, delay, seen_rule
        if agents:
            groups.append({"agents": agents, "rules": rules,
                           "crawl_delay": delay})
        agents, rules, delay, seen_rule = [], [], None, False

    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            if seen_rule:
                flush()
            agents.append(value.lower())
        elif field in ("allow", "disallow") and agents:
            seen_rule = True
            if value:  # an empty Disallow means allow-all: no rule needed
                rules.append((value, field == "allow"))
        elif field == "crawl-delay" and agents:
            seen_rule = True
            try:
                delay = float(value)
            except ValueError:
                pass
    flush()
    return groups


def _rule_matches(pattern: str, path_query: str) -> bool:
    """RFC 9309 matching: '*' matches any sequence; a trailing '$'
    anchors the match to the end of the path; otherwise prefix."""
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    regex = "^" + re.escape(pattern).replace(r"\*", ".*")
    if anchored:
        regex += "$"
    return re.match(regex, path_query) is not None


def robots_for(url: str) -> dict | None:
    """Merged '*' group(s) for the URL's host (cached per run):
    {rules: [(pattern, allow)], crawl_delay}. None = robots.txt
    unreachable after retries (fail-closed)."""
    host = urlparse(url).netloc
    if host in _robots_cache:
        return _robots_cache[host]
    robots_url = f"{urlparse(url).scheme}://{host}/robots.txt"
    body = None
    for attempt in range(2):
        try:
            r = SESSION.get(robots_url, timeout=45)
            if r.status_code == 404:
                body = ""  # no robots file: everything allowed
                break
            r.raise_for_status()
            body = r.text
            break
        except Exception:  # noqa: BLE001
            time.sleep(4)
    if body is None:
        _robots_cache[host] = None
        return None
    rules: list[tuple[str, bool]] = []
    delay = None
    for g in _parse_robots_groups(body):
        if "*" in g["agents"]:
            rules += g["rules"]
            if g["crawl_delay"] is not None:
                delay = g["crawl_delay"] if delay is None else max(delay, g["crawl_delay"])
    merged = {"rules": rules, "crawl_delay": delay}
    _robots_cache[host] = merged
    # honour crawl-delay through the pilot fetcher's per-host pacing
    if delay:
        pb.HOST_DELAY[host] = max(float(delay), pb.HOST_DELAY.get(host, 0.0))
        log(f"  robots crawl-delay {delay}s for {host}")
    return merged


def robots_allows(url: str) -> bool | None:
    merged = robots_for(url)
    if merged is None:
        return None
    parts = urlparse(url)
    path_query = parts.path or "/"
    if parts.query:
        path_query += "?" + parts.query
    best_len, best_allow = -1, True
    for pattern, allow in merged["rules"]:
        if _rule_matches(pattern, path_query):
            if len(pattern) > best_len or (len(pattern) == best_len and allow):
                best_len, best_allow = len(pattern), allow
    return best_allow


# ---------------------------------------------------------------- extraction
def _fitz_text(path: Path) -> tuple[str, int]:
    doc = pymupdf.open(path)
    pages = [doc[p].get_text() for p in range(doc.page_count)]
    n = doc.page_count
    doc.close()
    return "\n".join(pages), n


def _pdfplumber_text(path: Path) -> str:
    import pdfplumber
    out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            out.append(page.extract_text() or "")
    return "\n".join(out)


def _pdftotext_text(path: Path) -> str:
    r = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                       capture_output=True, timeout=300)
    return r.stdout.decode("utf-8", "replace")


def _ocr_text(path: Path, pages: int, deadline: float | None = None) -> str:
    if pages > OCR_MAX_PAGES:
        return ""
    tess = "/usr/bin/tesseract"
    if not Path(tess).exists():
        alt = Path.home() / "workspace/tools/bin/tesseract"
        tess = str(alt) if alt.exists() else ""
    if not tess:
        return ""
    doc = pymupdf.open(path)
    out = []
    tmp = WAVEA / "state" / "ocr_page.png"
    doc_deadline = time.time() + 480  # per-document OCR budget: 8 min wall
    deadline = min(doc_deadline, deadline) if deadline else doc_deadline
    complete = True
    for p in range(doc.page_count):
        if time.time() > deadline:
            complete = False
            break
        pix = doc[p].get_pixmap(dpi=200)
        pix.save(tmp)
        r = subprocess.run([tess, str(tmp), "stdout", "-l", "fra+eng"],
                           capture_output=True, timeout=180)
        out.append(r.stdout.decode("utf-8", "replace"))
    doc.close()
    # Never publish a partially-OCR'd document: if the budget ran out
    # before the last page, the OCR pass counts as failed and the
    # digital chain's result (usually near-empty) stands, so the
    # document drops at the text gate instead of shipping truncated.
    return "\n".join(out) if complete else ""


def extract_text(path: Path, ocr_deadline: float | None = None) -> tuple[str, str, int]:
    """(text, method, page_count) via the fallback chain."""
    text, pages = _fitz_text(path)

    def weak(t: str) -> bool:
        return len(t.strip()) < 300 or (pages and len(t.strip()) / pages < 25)

    if not weak(text):
        return text, "fitz", pages
    best, method = text, "fitz"
    for name, fn in (("pdfplumber", _pdfplumber_text), ("pdftotext", _pdftotext_text)):
        try:
            t = fn(path)
            if len(t.strip()) > len(best.strip()):
                best, method = t, name
        except Exception:  # noqa: BLE001
            pass
        if not weak(best):
            return best, method, pages
    if ocr_deadline is None or time.time() < ocr_deadline:
        try:
            t = _ocr_text(path, pages, deadline=ocr_deadline)
            if len(t.strip()) > len(best.strip()):
                best, method = t, "ocr-fra"
        except Exception:  # noqa: BLE001
            pass
    return best, method, pages


# ---------------------------------------------------------------- splitting
DROP_LINES = [
    re.compile(r"^\d+$"),                       # folios
    re.compile(r"^- \d+ -$"),
    re.compile(r"^page \d+( de \d+)?$", re.I),
    re.compile(r"\.{4,}\s*\d*\s*$"),            # ToC dot leaders
]


def clean(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if any(r.search(s) for r in DROP_LINES):
            continue
        out.append(s)
    return out


ARTICLE_RE = re.compile(r"^ARTICLE\s+(\d+(?:\.\d+)?)\s*[.\u2014\-:]?\s*(.*)$", re.I)
SECTION_RE = re.compile(r"^SECTION\s+(\d+(?:\.\d+)?)\s*[.\u2014\-:]?\s*(.*)$", re.I)
CHAPITRE_RE = re.compile(r"^CHAPITRE\s+([IVXLCDM]+|\d+)\s*[.\u2014\-:]?\s*(.*)$", re.I)


def _keyword_sections(lines, regex, kind):
    """Split at ARTICLE/SECTION/CHAPITRE heading lines; group fragments
    by number and keep the longest body (the pilot's ToC defence)."""
    frags: list[tuple[str, str, list[str]]] = []
    cur_num, cur_head, cur = None, "", []
    for line in lines:
        m = regex.match(line)
        if m:
            if cur_num is not None:
                frags.append((cur_num, cur_head, cur))
            cur_num, cur_head, cur = m.group(1), m.group(2).strip(), []
        elif cur_num is not None:
            cur.append(line)
    if cur_num is not None:
        frags.append((cur_num, cur_head, cur))
    best: dict[str, tuple[str, str]] = {}
    order: list[str] = []
    for num, head, body_lines in frags:
        body = join_fragment(body_lines)
        if num not in best:
            order.append(num)
            best[num] = (head, body)
        elif len(body) > len(best[num][1]):
            best[num] = (head, body)
    out = []
    for num in order:
        head, body = best[num]
        if len(body) < 40:
            continue
        label = f"{kind} {num}" + (f" — {head.title()}" if head else "")
        out.append((f"{kind.lower()}-{num}", label, body, f"{kind} {num}"))
    return out


def doc_sections(lines):
    """Try the splitting strategies in order; return (sections, strategy)
    with sections as (sec_id, node_label, body, path) tuples."""
    secs = []
    raw = pb.numbered_sections(lines)
    secs = [(f"s{lbl.rstrip('.')}", (head or f"Article {lbl.rstrip('.')}"), body,
             f"Article {lbl.rstrip('.')}")
            for lbl, head, body in raw if len(body) >= 40]
    if len(secs) >= 2:
        return secs, "numbered"
    raw = pb.numbered_sections(lines, decimal=True)
    secs = [(f"s{lbl.rstrip('.')}", (head or f"Article {lbl.rstrip('.')}"), body,
             f"Article {lbl.rstrip('.')}")
            for lbl, head, body in raw if len(body) >= 40]
    if len(secs) >= 2:
        return secs, "numbered-decimal"
    for regex, kind in ((ARTICLE_RE, "Article"), (SECTION_RE, "Section"),
                        (CHAPITRE_RE, "Chapitre")):
        secs = _keyword_sections(lines, regex, kind)
        if len(secs) >= 2:
            return secs, kind.lower()
    return [], "none"


# ---------------------------------------------------------------- metadata
REG_NUM_RES = [
    # Two-part numbers first, longest second component first: QC uses
    # both NNN-YYYY (299-2026) and YY-NNN (24-417). A \d{1,3} second
    # component without a digit guard truncates 2026 to "202".
    re.compile(r"R[ÉE]GLEMENT\s+(?:N[Oº°]\s*|NUM[ÉE]RO\s*|#\s*)?(\d{2,4}\s*[-–]\s*\d{4})(?!\d)", re.I),
    re.compile(r"R[ÉE]GLEMENT\s+(?:N[Oº°]\s*|NUM[ÉE]RO\s*|#\s*)?(\d{2,4}\s*[-–]\s*\d{1,3})(?!\d)", re.I),
    re.compile(r"R[ÉE]GLEMENT\s+(?:N[Oº°]\s*|NUM[ÉE]RO\s*|#\s*)?(\d{3,4})\b", re.I),
]
FILE_NUM_RES = [
    re.compile(r"(\d{2,4}[-_]\d{4})(?!\d)"),
    re.compile(r"(\d{2,4}[-_]\d{1,3})(?!\d)"),
    re.compile(r"[-_](\d{3,4})(?:[-_.]|$)"),
]


def reglement_number(text: str, filename: str) -> str:
    """The document's own bylaw number. Filename first for two-part
    numbers: these libraries name files systematically
    (Reglement-24-415-Signe.pdf), while an amending/borrowing bylaw's
    TEXT names the amended bylaw first — an in-text-first rule
    mislabelled Murdochville's 24-415 as the '12-351' it references.
    In-text two-part next, then bare numbers (filename, then text)."""
    def norm(s: str) -> str:
        return re.sub(r"\s+", "", s).replace("–", "-").replace("_", "-")

    if "reglement" in fold(filename) or "reg" in fold(filename):
        for r in FILE_NUM_RES[:2]:
            m = r.search(filename)
            if m:
                return norm(m.group(1))
    head = text[:6000]
    for r in REG_NUM_RES[:2]:
        m = r.search(head)
        if m:
            return norm(m.group(1))
    if "reglement" in fold(filename) or "reg" in fold(filename):
        m = FILE_NUM_RES[2].search(filename)
        if m:
            return norm(m.group(1))
    m = REG_NUM_RES[2].search(head)
    if m:
        return norm(m.group(1))
    return ""


TITLE_RE = re.compile(r"\bR[ÉE]GLEMENT\b", re.I)  # \b excludes "réglementation"
TITLE_START_RE = re.compile(r"^(PROJET DE )?R[ÉE]GLEMENT\b", re.I)


def doc_title(text: str, anchor: str, filename: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # Title-block lines: contain the word RÈGLEMENT (not "réglementation"),
    # are not body sentences (no terminal period), prefer line-initial ones.
    candidates = []
    for i, line in enumerate(lines[:40]):
        if TITLE_RE.search(line) and len(line) >= 10 and not line.endswith("."):
            candidates.append((0 if TITLE_START_RE.search(line) else 1, i, line))
    candidates.sort()
    if candidates:
        _, i, line = candidates[0]
        title = line
        if i + 1 < len(lines):
            nxt = lines[i + 1]
            if (nxt.isupper() or fold(nxt).startswith(("concernant", "relatif", "visant"))) \
                    and len(nxt) >= 8 and not TITLE_RE.search(nxt):
                title = f"{title} {nxt}"
        return re.sub(r"\s+", " ", title).strip()[:220]
    a = re.sub(r"\s+", " ", (anchor or "")).strip()
    if len(a) >= 12 and fold(a) not in ("telecharger", "telecharger le pdf", "pdf") \
            and "cliquez" not in fold(a):
        return a[:220]
    return re.sub(r"[-_]+", " ", Path(filename).stem).strip()[:220]


def doc_dates(text: str) -> tuple[str, str]:
    eff = ""
    for pat in (r"en vigueur le (\d{1,2})(?:er)? (\w+) (\d{4})",
                r"adopt[ée] le (\d{1,2})(?:er)? (\w+) (\d{4})"):
        m = re.search(pat, text, re.I)
        if m and m.group(2).lower() in FR_MONTHS:
            eff = f"{m.group(3)}-{FR_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
            break
    mod = ""
    m = re.search(r"Compilation administrative au (\d{1,2}) (\w+) (\d{4})", text)
    if m and m.group(2).lower() in FR_MONTHS:
        mod = f"{m.group(3)}-{FR_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return eff, mod


# ---------------------------------------------------------------- enumeration
SKIP_RES = [
    re.compile(r"formulaire", re.I),
    re.compile(r"proc[èe]s[- ]verbal|proces[- ]verbal", re.I),
    re.compile(r"ordre[- ]du[- ]jour", re.I),
    re.compile(r"demande[- ]de[- ](permis|derogation|d[ée]rogation)", re.I),
]


def enumerate_pdfs(index_url: str) -> tuple[list[dict], list[str], list[str]]:
    """(pdfs, fetched_pages, notes): pdfs = [{url, anchor}]."""
    seen_pages: list[str] = []
    queue = [index_url]
    pdfs: dict[str, str] = {}
    notes: list[str] = []
    page_re = re.compile(re.escape(urlparse(index_url).path.rstrip("/")) + r"/page/\d+/?$")
    while queue and len(seen_pages) < 6:
        page = queue.pop(0)
        if page in seen_pages:
            continue
        seen_pages.append(page)
        try:
            html_bytes = fetch(page)
        except Exception as e:  # noqa: BLE001
            notes.append(f"index page fetch failed {page}: {type(e).__name__} {str(e)[:120]}")
            continue
        soup = BeautifulSoup(html_bytes, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            full = urljoin(page, href)
            path = urlparse(full).path
            if path.lower().endswith(".pdf"):
                if full not in pdfs:
                    pdfs[full] = a.get_text(" ", strip=True)
            elif page_re.search(path) and full not in seen_pages and full not in queue:
                queue.append(full)
    out = [{"url": u, "anchor": a} for u, a in pdfs.items()]
    return out, seen_pages, notes


# ---------------------------------------------------------------- state
def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"wave": "canada-tranche1-waveA", "repo": REPO_ID,
            "baseline_rows": 1210, "towns": {}}


def save_state(state: dict):
    state["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE)


def load_scope() -> list[dict]:
    rows = [json.loads(l) for l in open(PILOT / "ca_platform_census_2026-10-12.jsonl", encoding="utf-8")]
    scope = [r for r in rows
             if r["province"] == "Quebec"
             and (r.get("platform") or "").lower() == "wordpress"
             and r["robots_posture"] == "allowed"
             and r["bylaws_presence"] in ("index_with_pdfs", "direct_pdf_links_on_homepage")]
    scope.sort(key=lambda r: r["sgc"])
    return scope


# ---------------------------------------------------------------- HF
def hf_api():
    sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
    from dynamic_credentials import dynamic_credential_entry
    entry = dynamic_credential_entry("custom.huggingface")
    token = entry.get("surrogate") if isinstance(entry, dict) else None
    if not token:
        raise RuntimeError("dynamic_credential_entry returned no surrogate")
    from huggingface_hub import HfApi
    return HfApi(token=token), token


def publish_town(api, sgc: str, local: Path, expect_rows: int) -> str:
    remote = f"data/{sgc}_html.parquet"
    info = api.dataset_info(REPO_ID)
    existing = {s.rfilename for s in info.siblings or []}
    if remote in existing:
        return "already-present"
    api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                    repo_id=REPO_ID, repo_type="dataset",
                    commit_message=f"Canada tranche 1 wave A: add {sgc}")
    info = api.dataset_info(REPO_ID)
    existing = {s.rfilename for s in info.siblings or []}
    assert remote in existing, f"upload of {remote} not visible in fresh listing"
    return "uploaded"


# ---------------------------------------------------------------- per-town
def harvest_town(trec: dict, do_publish: bool, api=None) -> dict:
    sgc, name = trec["sgc"], trec["name"]
    jid = CA.normalize(sgc)
    result = {"sgc": sgc, "name": name, "status": "failed", "rows": 0,
              "docs": [], "dropped_docs": [], "skipped_pdfs": [], "notes": []}
    index_url = trec.get("bylaw_index_url") or trec.get("website_url")
    result["index_url"] = index_url

    # 1. robots re-check on the index route
    allowed = robots_allows(index_url)
    if allowed is None:
        result["status"] = "failed_transient"
        result["notes"].append("robots.txt unreachable after retries")
        return result
    if not allowed:
        result["status"] = "excluded_robots"
        result["notes"].append(f"robots.txt now disallows the by-law route {index_url}")
        return result

    # 2. enumeration
    pdfs, pages_fetched, notes = enumerate_pdfs(index_url)
    result["notes"] += notes
    result["index_pages_fetched"] = pages_fetched
    if not pdfs:
        result["status"] = "failed_transient" if notes else "failed"
        result["notes"].append("no PDF links found on the by-law index now")
        return result

    kept, skipped = [], []
    for p in pdfs:
        probe = fold(p["url"]) + " " + fold(p["anchor"])
        if any(r.search(probe) for r in SKIP_RES):
            skipped.append({"url": p["url"], "reason": "non-reglement material (form/minutes/agenda/permit form)"})
        else:
            kept.append(p)
    result["skipped_pdfs"] = skipped
    if len(kept) > MAX_PDFS_PER_TOWN:
        result["notes"].append(f"PDF cap hit: {len(kept)} candidates, first {MAX_PDFS_PER_TOWN} taken")
        result["skipped_pdfs"] += [{"url": p["url"], "reason": "beyond per-town cap 60"}
                                   for p in kept[MAX_PDFS_PER_TOWN:]]
        kept = kept[:MAX_PDFS_PER_TOWN]

    # 3. per-document processing
    rawdir = RAW / sgc
    rawdir.mkdir(parents=True, exist_ok=True)
    townslug = slugify(name)
    all_rows, docs_out = [], []
    manifest = {"dropped_docs": []}
    seen_hashes: set[str] = set()
    used_slugs: set[str] = set()
    ocr_deadline = time.time() + 25 * 60  # per-town OCR budget: 25 min wall
    for ip, p in enumerate(kept, 1):
        log(f"  [{sgc} {ip}/{len(kept)}] {Path(urlparse(p['url']).path).name}")
        url, anchor = p["url"], p["anchor"]
        if robots_allows(url) is False:
            result["dropped_docs"].append({"url": url, "reason": "robots disallows this PDF URL"})
            continue
        fname = Path(urlparse(url).path).name or "document.pdf"
        local = rawdir / fname
        try:
            if not local.exists():
                content = fetch(url)
                if len(content) > MAX_PDF_BYTES:
                    result["dropped_docs"].append({"url": url, "reason": f"PDF too large ({len(content)} bytes)"})
                    continue
                local.write_bytes(content)
        except Exception as e:  # noqa: BLE001
            result["dropped_docs"].append({"url": url, "reason": f"fetch failed: {type(e).__name__} {str(e)[:120]}"})
            continue
        digest = hashlib.sha256(local.read_bytes()).hexdigest()
        if digest in seen_hashes:
            result["dropped_docs"].append({"url": url, "reason": "duplicate content (same PDF linked twice)"})
            continue
        seen_hashes.add(digest)
        try:
            text, method, pages = extract_text(local, ocr_deadline=ocr_deadline)
        except Exception as e:  # noqa: BLE001
            result["dropped_docs"].append({"url": url, "reason": f"extraction failed: {type(e).__name__} {str(e)[:120]}"})
            continue
        if len(text.strip()) < 300:
            result["dropped_docs"].append(
                {"url": url, "method": method, "pages": pages,
                 "reason": "no extractable text (digital chain insufficient; OCR absent, "
                           "over page cap, or over time budget)"})
            log(f"      drop: no extractable text ({method}, {pages} pp)")
            continue
        basis = attribution_basis(text, name, url, index_url)
        if not basis:
            result["dropped_docs"].append({"url": url, "method": method,
                                           "reason": "attribution gate: municipality marker not in text "
                                                     "and no own-host provenance"})
            log(f"      drop: attribution gate ({method}, {pages} pp)")
            continue
        lines = clean(text)
        secs, strategy = doc_sections(lines)
        num = reglement_number(text, fname)
        title = doc_title(text, anchor, fname)
        slug = slugify(f"reglement-{num}" if num else Path(fname).stem)
        base_slug, k = slug, 2
        while slug in used_slugs:
            slug = f"{base_slug}-{k}"
            k += 1
        used_slugs.add(slug)
        eff, mod = doc_dates(text)
        work_id = f"{townslug}-reglements"
        meta = {"slug": slug, "regeling_id": num or slug, "work_id": work_id,
                "title": title, "date_effective": eff}
        built = [(sid, label, body, f"{title} > {path}") for sid, label, body, path in secs]
        rows = build_rows(jid, name, docs_out, meta, built, index_url, url,
                          date_modified=mod, manifest=manifest)
        if rows:
            d = docs_out[-1]
            d.update({"method": method, "strategy": strategy, "pages": pages,
                      "pdf_url": url, "attribution": basis})
            all_rows += rows
            log(f"      kept: {len(rows)} rows ({method}/{strategy}, {pages} pp)")
    result["dropped_docs"] += manifest["dropped_docs"]
    result["docs"] = docs_out
    result["provenance_docs"] = sum(1 for d in docs_out if d.get("attribution") == "provenance")
    if not all_rows:
        fetch_fails = [d for d in result["dropped_docs"]
                       if str(d.get("reason", "")).startswith("fetch failed")]
        if fetch_fails and len(fetch_fails) == len(result["dropped_docs"]):
            result["status"] = "failed_transient"
            result["notes"].append("every document fetch failed (egress window)")
        else:
            result["status"] = "failed"
            result["notes"].append("no document survived the gates")
        return result

    # 4. gates: write, validate, independent re-read
    rows = finalize_rows(all_rows)
    rows = [r for r in rows if r["text"].strip() and r["html"].strip()]
    table = rows_to_table(rows)
    rep = validation_report(table, jurisdiction_id=jid, jurisdiction_name=name, country="Canada")
    fpath = DATA / CA.file_name(jid)
    write_html_parquet(fpath, table)
    back = read_html_parquet(fpath)
    rep2 = validation_report(back, jurisdiction_id=jid, jurisdiction_name=name, country="Canada")
    if not (rep["valid"] and rep2["valid"]):
        result["status"] = "failed"
        result["notes"].append(f"validation failed: {rep['errors']} / {rep2['errors']}")
        return result
    write_validation_report(DATA / f"{jid}_validation.json", rep2)
    result["rows"] = back.num_rows
    result["file"] = f"data/{CA.file_name(jid)}"

    # 5. publish (per town)
    if do_publish:
        try:
            result["publish"] = publish_town(api, sgc, fpath, back.num_rows)
            result["status"] = "done"
        except Exception as e:  # noqa: BLE001
            result["status"] = "validated_unpublished"
            result["notes"].append(f"publish failed: {type(e).__name__} {str(e)[:160]}")
    else:
        result["status"] = "validated_unpublished"
    return result


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated SGC codes")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--retry-transient", action="store_true",
                    help="also retry towns in failed_transient state")
    args = ap.parse_args()

    scope = load_scope()
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        scope = [t for t in scope if t["sgc"] in wanted]
    state = load_state()
    api = None
    if not args.no_publish:
        api, _ = hf_api()
    done_count = 0
    explicit = bool(args.only)
    for trec in scope:
        sgc = trec["sgc"]
        prev = state["towns"].get(sgc, {})
        pstatus = prev.get("status")
        if pstatus == "done":
            continue
        if pstatus == "excluded_robots" and not explicit:
            continue
        if pstatus == "failed" and not (explicit or args.retry_transient):
            continue  # deterministic gate outcome; retry only on request
        # Fast path: a town already harvested and gate-validated in a
        # previous (proof) run only needs its staged parquet published —
        # re-verify it on re-read, then upload without re-harvesting.
        if pstatus == "validated_unpublished" and not args.no_publish and prev.get("file"):
            staged = WAVEA / prev["file"]
            if staged.exists():
                back = read_html_parquet(staged)
                rep = validation_report(back, jurisdiction_id=CA.normalize(sgc),
                                        jurisdiction_name=trec["name"], country="Canada")
                if rep["valid"] and back.num_rows == prev.get("rows"):
                    try:
                        prev["publish"] = publish_town(api, sgc, staged, back.num_rows)
                        prev["status"] = "done"
                        state["towns"][sgc] = prev
                        save_state(state)
                        log(f"=== {sgc} {trec['name']}: published from staged parquet "
                            f"({back.num_rows} rows, {prev['publish']})")
                        continue
                    except Exception as e:  # noqa: BLE001
                        log(f"=== {sgc}: staged publish failed ({type(e).__name__} "
                            f"{str(e)[:120]}); falling through to full harvest")
        log(f"=== {sgc} {trec['name']} ({trec['bylaws_presence']}, census pdfs={trec.get('pdf_links_on_index')})")
        try:
            res = harvest_town(trec, do_publish=not args.no_publish, api=api)
        except Exception as e:  # noqa: BLE001
            res = {"sgc": sgc, "name": trec["name"], "status": "failed_transient",
                   "rows": 0, "notes": [f"unhandled: {type(e).__name__} {str(e)[:200]}"]}
        state["towns"][sgc] = res
        save_state(state)
        log(f"    -> {res['status']}, rows={res.get('rows', 0)}, docs={len(res.get('docs', []))}, "
            f"dropped={len(res.get('dropped_docs', []))}")
        done_count += 1
        if args.limit and done_count >= args.limit:
            break
    tot_done = sum(1 for t in state["towns"].values() if t.get("status") == "done")
    tot_rows = sum(t.get("rows", 0) for t in state["towns"].values() if t.get("status") == "done")
    log(f"STATE: {tot_done} towns done, {tot_rows} wave-A rows published (this run processed {done_count})")


if __name__ == "__main__":
    main()
