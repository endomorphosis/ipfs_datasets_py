"""Brazil SAPL campaign, tranche 1 — first 100 municipios of the verified
SAPL census (4 pilot seed + next 96 in registry order), 2025 Leis
Ordinarias slice, publish-as-validated to
endomorphosis/ipfs_brazil_municipal_laws.

Reuses the pilot harvester (../br_pilot/br_pilot_build.py) functions and
the shared world_municipal library. Politeness: >=62 s between requests
to the SAME host (robots Crawl-delay: 60); parallelism is across hosts
only. State is checkpointed to campaign_state.json after every municipio
so an interrupted run resumes cleanly.

Modes:
  seed     create dataset, publish the 4 pilot parquets + coverage files
  run      harvest + publish the tranche (resumable; retries failed hosts
           at most twice)
  coverage regenerate + upload README/coverage_report/jurisdictions
  verify   list remote files + download-count rows for every parquet

HF auth: dynamic credential surrogate (connector custom.huggingface),
never printed or persisted.
"""
from __future__ import annotations

import os as _os

# Egress quirk (AGENTS.md): httpx chokes on the bracketed IPv6 entries in
# the ambient no_proxy/NO_PROXY — force-set before any huggingface_hub use.
_os.environ["no_proxy"] = "localhost,127.0.0.1"
_os.environ["NO_PROXY"] = "localhost,127.0.0.1"

import importlib.util
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GOAL_HIDDEN = ROOT.parent
REPO = "endomorphosis/ipfs_brazil_municipal_laws"
YEAR = 2025
RETRIEVED = "2026-10-12"
MAX_WORKERS = 8
MAX_ATTEMPTS = 3            # initial attempt + at most 2 retries per host
REQ_TRIES = 3               # per-request retries on transient proxy errors
STATE_PATH = ROOT / "campaign_state.json"
DATA_DIR = ROOT / "data"
VAL_DIR = ROOT / "validation"
FILES_DIR = ROOT / "files"          # generated README/coverage/jurisdictions
PARTIAL_DIR = ROOT / "partials"     # per-law harvest checkpoints (crash-safe)
PILOT_DIR = GOAL_HIDDEN / "br_pilot"
CENSUS_PATH = GOAL_HIDDEN / "br_sapl_instances_2026-10-12.json"

PILOTS = ["5208004", "1505536", "4104501", "4208450"]  # Formosa, Parauapebas, Capanema, Itapoa
TRANCHE_NEW = 96

# ---------------------------------------------------------------- pilot reuse
_spec = importlib.util.spec_from_file_location(
    "br_pilot", PILOT_DIR / "br_pilot_build.py")
pilot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pilot)

sys.path.insert(0, str(Path.home() / "workspace" / "ipfs_datasets_py"))
from ipfs_datasets_py.processors.legal_scrapers import world_municipal as wm  # noqa: E402
import pyarrow as pa  # noqa: E402

# ---------------------------------------------------------------- HF publish
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402


def hf_api():
    from huggingface_hub import HfApi
    tok = str(dynamic_credential_entry("custom.huggingface")["surrogate"]).strip()
    return HfApi(token=tok)


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


import requests as _rq  # noqa: E402

_TRANSIENT = (_rq.exceptions.ProxyError, _rq.exceptions.ConnectionError,
              _rq.exceptions.Timeout, _rq.exceptions.ChunkedEncodingError)


def get_retry(sess, url, **kw):
    """sess.get with retries on transient egress-proxy failures. Every
    try goes through the PoliteSession, so per-host crawl-delay spacing
    is preserved across retries."""
    last_exc = None
    for try_no in range(REQ_TRIES):
        try:
            r, dt = sess.get(url, **kw)
            if r.status_code >= 500 and try_no < REQ_TRIES - 1:
                time.sleep(20)
                continue
            return r, dt
        except _TRANSIENT as exc:
            last_exc = exc
            if try_no < REQ_TRIES - 1:
                time.sleep(20)
    raise last_exc


def fetch_pdf_bytes(sess, url: str, deadline_s: float = 900.0) -> bytes:
    """Streamed PDF fetch with a TOTAL deadline. A slow-trickle response
    otherwise never trips the per-read timeout and can park a worker
    for tens of minutes on one law. Deadline is generous (900s): under
    multi-campaign proxy contention the observed trickle drops to a
    few KB/s and multi-MB scanned PDFs legitimately need minutes —
    at 300s Acegua/Agua Boa failed 10/10 laws (2026-10-13 run 12).
    Goes through get_retry for pacing and transient-error handling;
    raises TimeoutError on deadline."""
    r, _ = get_retry(sess, url, stream=True)
    r.raise_for_status()
    chunks, got = [], 0
    t0 = time.monotonic()
    try:
        for chunk in r.iter_content(chunk_size=65536):
            if chunk:
                chunks.append(chunk)
                got += len(chunk)
            if time.monotonic() - t0 > deadline_s:
                raise TimeoutError(
                    f"pdf fetch exceeded {deadline_s:.0f}s ({got} bytes): {url}")
    finally:
        r.close()
    return b"".join(chunks)


# The VM is shared with several other campaign workers; unbounded
# concurrent OCR (300-DPI pixmaps + tesseract subprocesses) spikes
# memory and gets this process killed under contention. Cap it.
_OCR_SEM = threading.Semaphore(2)


def ocr_pdf_text(content: bytes, max_pages: int = 100) -> str:
    """OCR a scanned-image PDF with tesseract (por). Many small camaras
    publish signed paper laws as scans with no text layer at all — the
    pilot's born-digital sample never hit this class, but at census
    scale it is common (Acegua RS, Agua Boa MT: 100% scanned). The
    year-end budget laws (LDO/LOA with annexes) run 60-100 pages, so
    the original 40-page cap rejected exactly the most significant
    laws of every host's tail; large docs render at 180 DPI to keep
    per-page cost bounded. Returns '' on any failure or if the PDF
    exceeds the page cap."""
    import subprocess
    import fitz
    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception:
        return ""
    if len(doc) == 0 or len(doc) > max_pages:
        return ""
    dpi = 250 if len(doc) <= 40 else 180
    texts = []
    ok_pages = 0
    for page in doc:
        try:
            png = page.get_pixmap(dpi=dpi).tobytes("png")
            with _OCR_SEM:
                p = subprocess.run(
                    ["tesseract", "stdin", "stdout", "-l", "por", "--psm", "6"],
                    input=png, capture_output=True, timeout=180)
            page_text = p.stdout.decode("utf-8", "replace")
        except Exception:
            # One slow/dead page must not kill a 100-page law: skip it
            # and let the 60% rule below judge the document as a whole.
            page_text = ""
        if page_text.strip():
            ok_pages += 1
        texts.append(page_text)
    if ok_pages < 0.6 * len(doc):
        return ""
    return "\n".join(texts).strip()


# ---------------------------------------------------------------- state
_state_lock = threading.Lock()


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    census = json.loads(CENSUS_PATH.read_text())
    inst = {i["ibge"]: i for i in census["instances"]}
    state = {"repo": REPO, "year": YEAR, "retrieved": RETRIEVED,
             "started": datetime.now(timezone.utc).isoformat(),
             "census_total": len(inst), "municipios": {}}
    for ibge in PILOTS:
        i = inst[ibge]
        state["municipios"][ibge] = {
            "ibge": ibge, "name": i["municipio"], "uf": i["uf"],
            "host": i["host"], "status": "seed_pending", "attempts": 0}
    taken = 0
    for i in census["instances"]:
        if i["ibge"] in PILOTS:
            continue
        if taken >= TRANCHE_NEW:
            break
        state["municipios"][i["ibge"]] = {
            "ibge": i["ibge"], "name": i["municipio"], "uf": i["uf"],
            "host": i["host"], "base_url": i["base_url"],
            "status": "pending", "attempts": 0}
        taken += 1
    save_state(state)
    return state


def save_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    tmp.replace(STATE_PATH)


def update_entry(state: dict, ibge: str, **kw) -> None:
    with _state_lock:
        state["municipios"][ibge].update(kw)
        state["municipios"][ibge]["updated"] = datetime.now(timezone.utc).isoformat()
        save_state(state)


# ---------------------------------------------------------------- coverage files
def covered_entries(state: dict) -> list[dict]:
    out = [e for e in state["municipios"].values()
           if e["status"] in ("published", "seed_published")]
    return sorted(out, key=lambda e: e["ibge"])


def build_coverage_files(state: dict) -> dict:
    cov = covered_entries(state)
    total_rows = sum(e.get("rows", 0) for e in cov)
    total_acts = sum(e.get("laws_harvested", 0) for e in cov)
    published = [e for e in cov if e["status"] == "published"]
    seeds = [e for e in cov if e["status"] == "seed_published"]
    failed = [e for e in state["municipios"].values() if e["status"] == "failed"]
    zero = [e for e in state["municipios"].values() if e["status"] == "zero_acts"]
    pending = [e for e in state["municipios"].values()
               if e["status"] in ("pending", "seed_pending", "harvesting")]

    readme = f"""# ipfs_brazil_municipal_laws

Municipal law of Brazil, harvested from **SAPL** (Sistema de Apoio ao
Processo Legislativo, Interlegis / Senado Federal) instances run by
camaras municipais. Part of the world municipal-law coverage programme
(one repo per country, `<IBGE>_html.parquet` per jurisdiction, shared
world_municipal schema).

## Status — campaign tranche 1 (in progress)

- Census: **1,186 verified SAPL instances** of Brazil's 5,570 municipios
  (21.3%); this dataset is being filled tranche by tranche from that
  census.
- Tranche 1 target: the first 100 census municipios, **Leis Ordinarias
  of {YEAR}** only.
- Covered so far: **{len(cov)} municipios, {total_acts} acts, {total_rows} rows**
  ({len(published)} full-{YEAR} harvests + {len(seeds)} pilot seed files).

## Source and route

Each SAPL instance exposes a Normas Juridicas search (`/norma/pesquisar`).
Per law, the structured *texto articulado* (article-level HTML) is taken
where the instance provides it; otherwise the official original-text PDF
is extracted as one document-level row. Instance content is published by
the camaras under CC BY-SA 4.0 (instance footers). Harvest honors each
instance's robots.txt (Crawl-delay: 60; per-host pacing, parallel across
hosts).

## Schema (19 shared columns + `tipo`)

`cid`, `jurisdiction_id` (IBGE 7-digit municipio code),
`jurisdiction_name`, `country` = BR, `doc_id`, `regeling_id`
(`sapl:<host>:norma-<pk>`), `regeling_work_id`, `doc_order` (uint32,
sequential within the municipio file), `title`, `structural_path`,
`node_label`, `html_title`, `html`, `text`, `source_url` (SAPL norma /
texto-articulado page, or the official PDF), `xml_url`,
`date_effective` (law date), `date_modified`, `retrieved`,
plus **`tipo`**: `Lei Ordinaria` in this tranche.

Rows are article-level for texto-articulado laws (a `Preambulo` row plus
one row per article chunk) and document-level for PDF-only laws.

## Jurisdictions

`jurisdictions.jsonl`: IBGE code, name, UF, SAPL host, act/row counts.
Denominator: 5,570 municipios; SAPL-census denominator: 1,186.

## Known gaps

- The 4 pilot seed files (Formosa GO, Parauapebas PA, Capanema PR,
  Itapoa SC) carry the pilot's 5-law sample of {YEAR}, not the full year;
  their full-{YEAR} harvest is pending a later tranche.
- Only Leis Ordinarias of {YEAR} in this tranche; other tipos (Lei
  Complementar, Lei Organica, Decreto Legislativo, ...) and other years
  are later tranches.
- LeisMunicipais.com.br (~1,800 governments) is not harvested: it is
  Cloudflare-blocked from the harvest network (separate decision).
- Municipios whose SAPL instance failed or returned no {YEAR} Lei
  Ordinaria are named with reasons in `coverage_report.md`.
"""

    lines = [f"# Coverage report — {REPO}", "",
             f"- Slice: Leis Ordinarias, {YEAR}, SAPL instances only",
             f"- Census denominator: 1,186 verified instances / 5,570 municipios",
             f"- Tranche 1 target: 100 municipios "
             f"(4 pilot seed + {TRANCHE_NEW} new)",
             f"- Covered: **{len(cov)}/100** ({len(published)} full harvests, "
             f"{len(seeds)} pilot seed files)",
             f"- Acts: {total_acts}; rows: {total_rows}",
             f"- Zero-{YEAR}-act municipios in tranche: {len(zero)}",
             f"- Failed municipios in tranche: {len(failed)}",
             f"- Pending: {len(pending)}", "",
             "## Per-municipio counts", "",
             "| IBGE | Municipio | UF | Acts | TA | PDF | Rows | Status |",
             "|---|---|---|---:|---:|---:|---:|---|"]
    for e in cov:
        lines.append(
            f"| {e['ibge']} | {e['name']} | {e['uf']} | "
            f"{e.get('laws_harvested', 0)} | {e.get('laws_ta', 0)} | "
            f"{e.get('laws_pdf', 0)} | {e.get('rows', 0)} | {e['status']} |")
    if zero:
        lines += ["", f"## Zero {YEAR} Lei Ordinaria found", ""]
        for e in sorted(zero, key=lambda x: x["ibge"]):
            lines.append(f"- {e['ibge']} {e['name']} ({e['uf']}) — "
                         f"{e.get('note', 'enumeration returned no 2025 entries')}")
    if failed:
        lines += ["", "## Failed (named, with reason)", ""]
        for e in sorted(failed, key=lambda x: x["ibge"]):
            lines.append(f"- {e['ibge']} {e['name']} ({e['uf']}) — "
                         f"{e.get('error', 'unknown')}")
    cov_md = "\n".join(lines) + "\n"

    jsonl = "".join(json.dumps(
        {"ibge": e["ibge"], "name": e["name"], "uf": e["uf"],
         "host": e["host"], "source": "SAPL", "acts": e.get("laws_harvested", 0),
         "rows": e.get("rows", 0), "status": e["status"]},
        ensure_ascii=False) + "\n" for e in cov)

    FILES_DIR.mkdir(parents=True, exist_ok=True)
    (FILES_DIR / "README.md").write_text(readme)
    (FILES_DIR / "coverage_report.md").write_text(cov_md)
    (FILES_DIR / "jurisdictions.jsonl").write_text(jsonl)
    return {"covered": len(cov), "rows": total_rows, "acts": total_acts}


def upload_coverage(api, state: dict) -> dict:
    stats = build_coverage_files(state)
    for fn in ("README.md", "coverage_report.md", "jurisdictions.jsonl"):
        api.upload_file(path_or_fileobj=str(FILES_DIR / fn), path_in_repo=fn,
                        repo_id=REPO, repo_type="dataset",
                        commit_message=f"BR tranche 1: coverage files "
                                       f"({stats['covered']} municipios, "
                                       f"{stats['rows']} rows)")
    return stats


def publish_parquet(api, ibge: str, parquet: Path) -> str:
    path_in_repo = f"data/{ibge}_html.parquet"
    info = api.upload_file(path_or_fileobj=str(parquet), path_in_repo=path_in_repo,
                           repo_id=REPO, repo_type="dataset",
                           commit_message=f"BR tranche 1: {ibge} Leis "
                                          f"Ordinarias {YEAR}")
    oid = getattr(info, "oid", None) or getattr(info, "commit_oid", None)
    files = api.list_repo_files(REPO, repo_type="dataset", revision=oid)
    if path_in_repo not in files:
        raise RuntimeError(f"verify failed: {path_in_repo} not at commit {oid}")
    return oid


# ---------------------------------------------------------------- enumeration
LEI_LABELS = {"lei ordinaria", "lei", "lei municipal"}
DATE_RE = re.compile(
    r"n[ºo]\s*([\d.]+),?\s*de\s*(\d{1,2})\s*de\s*(\w+)\s*de\s*(\d{4})",
    re.IGNORECASE)


def norm_label(s: str) -> str:
    return re.sub(r"\s+", " ", pilot.strip_accents(s or "").lower()).strip()


def parse_date2(title: str):
    m = DATE_RE.search(title or "")
    if not m:
        return "", ""
    numero = m.group(1).replace(".", "")
    month = pilot.MONTHS.get(m.group(3).lower(), 0)
    iso = f"{m.group(4)}-{month:02d}-{int(m.group(2)):02d}" if month else ""
    return numero, iso


def find_date_in_text(text: str):
    """Fallback: find a law date anywhere in a page's text."""
    m = DATE_RE.search(text or "")
    if not m:
        return ""
    month = pilot.MONTHS.get(m.group(3).lower(), 0)
    return f"{m.group(4)}-{month:02d}-{int(m.group(2)):02d}" if month else ""


def find_title_in_page(soup):
    """The norma detail page carries the full law title in a heading
    (e.g. 'LEI ORDINÁRIA nº 1.338, de 09 de outubro de 2025')."""
    for tag in soup.find_all(["h1", "h2", "h3"]):
        t = re.sub(r"\s+", " ", tag.get_text(" ", strip=True))
        if DATE_RE.search(t) or ("nº" in t and "lei" in norm_label(t)):
            return t
    return ""


def constructed_title(e: dict) -> str:
    desc = e.get("tipo_desc") or "Lei Ordinária"
    num = str(e.get("numero") or "").replace(".", "")
    return f"{desc} nº {num} de {YEAR}" if num else f"{desc} de {YEAR}"


def result_rows2(soup, tipo_desc_norm: str):
    """Listing entries; title filter is case/accent-insensitive and keyed
    to the instance's own tipo label (pilot's version was case-sensitive
    and dropped ALL-CAPS titles — e.g. Alexandria RN)."""
    out, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"^/norma/\d+")):
        title = a.get_text(" ", strip=True)
        nt = norm_label(title)
        if not (nt.startswith(tipo_desc_norm) or nt.startswith("lei ordinaria")
                or re.match(r"lei\s+n", nt)):
            continue
        pk = re.match(r"^/norma/(\d+)", a["href"]).group(1)
        if pk in seen:
            continue
        seen.add(pk)
        block = a.find_parent("tr") or a.parent
        pdf_url = ""
        if block:
            mm = block.find("a", href=re.compile(r"/media/sapl/public/normajuridica/"))
            if mm:
                pdf_url = mm["href"]
        out.append(dict(pk=pk, title=title, pdf_path=pdf_url))
    return out


def enumerate_year(sess, base: str, lei_id: str):
    """All 2025 Lei Ordinaria entries for one instance.

    Primary: the SAPL JSON export (server-side tipo+ano filtered,
    complete in one request, carries the official PDF URL). The HTML
    listing is fetched in parallel as the title/date source and as a
    fallback if the JSON export is unavailable.
    Returns (entries, info). Each entry: pk, title, date, pdf_url."""
    info = {"enum_source": "", "json_count": None, "total_found_raw": None,
            "pages_scanned": 0, "unparsed_dates": 0}
    json_by_pk = {}
    json_error = None
    try:
        r, _ = get_retry(sess, f"{base}/norma/pesquisar",
                         params={"tipo": lei_id, "ano": YEAR, "pesquisar": "",
                                 "format": "json"})
        r.raise_for_status()
        data = r.json()
        for res in data.get("results", []):
            if str(res.get("ano")) != str(YEAR):
                continue
            json_by_pk[str(res["id"])] = res
        info["json_count"] = len(json_by_pk)
    except Exception as exc:
        json_error = f"{type(exc).__name__}: {exc}"
        info["json_error"] = json_error
    tipo_desc = ""
    if json_by_pk:
        tipo_desc = norm_label(next(iter(json_by_pk.values()))
                               .get("tipo__descricao", ""))

    listing = {}
    for page in range(1, 13):
        r, _ = get_retry(sess, f"{base}/norma/pesquisar",
                         params={"tipo": lei_id, "ano": YEAR, "pesquisar": "",
                                 "o": "dataD", "page": page})
        r.raise_for_status()
        info["pages_scanned"] = page
        soup = pilot.BeautifulSoup(r.text, "html.parser")
        if page == 1:
            m = re.search(r"Foram encontradas\s*([\d.]+)\s*normas",
                          soup.get_text(" "))
            info["total_found_raw"] = int(m.group(1).replace(".", "")) if m else None
        new = 0
        for e in result_rows2(soup, tipo_desc or "lei ordinaria"):
            if e["pk"] not in listing:
                listing[e["pk"]] = e
                new += 1
        if json_by_pk and all(pk in listing for pk in json_by_pk):
            break
        if new == 0:
            break

    pks = list(json_by_pk) or list(listing)
    info["enum_source"] = "json+html" if json_by_pk else "html-only"
    if not pks and json_error:
        # Both channels empty AND the JSON channel errored: this is a
        # transient failure, not evidence of zero acts — fail retryably.
        raise RuntimeError(f"enumeration inconclusive (json: {json_error})")
    entries = []
    for pk in pks:
        li = listing.get(pk, {})
        js = json_by_pk.get(pk, {})
        title = li.get("title", "")
        _, iso = parse_date2(title)
        if title and not iso:
            info["unparsed_dates"] += 1
        pdf_url = js.get("texto_integral") or (
            (base + li["pdf_path"]) if li.get("pdf_path") else "")
        entries.append(dict(pk=pk, title=title, date=iso, pdf_url=pdf_url,
                            numero=js.get("numero", ""),
                            tipo_desc=js.get("tipo__descricao", "")))
    return entries, info


# ---------------------------------------------------------------- harvest
def resolve_and_enumerate(sess, base: str, entry: dict):
    """Steps 1-2 of a harvest: resolve the instance's Lei Ordinaria tipo
    and enumerate the year. Returns (entries, einfo, terminal) where
    terminal is a finished state-update dict for the empty-base and
    no-tipo outcomes (entries is None in that case)."""
    # 1. this instance's own tipo id for Lei Ordinaria — the label is
    #    "Lei Ordinária" on most instances but plain "Lei" on some
    #    (e.g. Arinos MG); both are exact-label matches, never
    #    "Lei Complementar"/"Lei Orgânica".
    r, _ = get_retry(sess, f"{base}/norma/pesquisar")
    r.raise_for_status()
    soup = pilot.BeautifulSoup(r.text, "html.parser")
    sel = soup.find("select", attrs={"name": "tipo"})
    if sel is None:
        raise RuntimeError("search form has no tipo select "
                           "(transient or non-SAPL response)")
    options = [(opt["value"], opt.get_text(strip=True))
               for opt in sel.find_all("option") if opt.get("value")]
    lei_id = None
    for value, label in options:
        if norm_label(label) in LEI_LABELS:
            lei_id = value
            break
    if lei_id is None and not options:
        # Empty tipo list: some instances run SAPL with a completely
        # empty norma base (no tipos, no normas). One JSON probe
        # decides: 0 results = genuine zero; >0 = real failure.
        r, _ = get_retry(sess, f"{base}/norma/pesquisar",
                         params={"pesquisar": "", "format": "json"})
        r.raise_for_status()
        n_all = len(r.json().get("results", []))
        if n_all == 0:
            return None, None, {"status": "zero_acts", "rows": 0,
                                "laws_found_2025": 0,
                                "note": "empty norma base: no tipos configured, "
                                        "JSON export returns 0 normas",
                                "requests": sess.n_requests}
        return None, None, {"status": "failed",
                            "error": f"tipo select empty but JSON export has "
                                     f"{n_all} normas",
                            "requests": sess.n_requests}
    if lei_id is None:
        labels = "; ".join(f"{v}={lab}" for v, lab in options)
        return None, None, {"status": "failed",
                            "error": f"no Lei/Lei Ordinaria tipo; options: {labels}",
                            "requests": sess.n_requests}
    # 2. enumerate the full year (JSON export primary, HTML listing
    #    for titles/dates)
    entries, einfo = enumerate_year(sess, base, lei_id)
    return entries, einfo, None


def harvest_muni(entry: dict) -> dict:
    """Full-2025 harvest of one municipio. Returns the state update dict."""
    ibge = pilot.ibge_normalize(entry["ibge"])
    base = entry["base_url"].rstrip("/")
    host = entry["host"]
    name = entry["name"]
    sess = pilot.PoliteSession()
    t_start = time.monotonic()
    upd = {"status": "harvesting"}
    try:
        # Steps 1-2 (tipo resolution + enumeration) cost 3-12 paced
        # requests and are re-paid on EVERY attempt — with this VM's
        # reboot cadence that tax dominated. The enumeration of a
        # closed year slice is static, so cache it next to the law
        # checkpoints (partials/<ibge>.enum.json) and reuse it.
        entries = einfo = None
        PARTIAL_DIR.mkdir(parents=True, exist_ok=True)
        enum_cache = PARTIAL_DIR / f"{ibge}.enum.json"
        if enum_cache.exists():
            try:
                cached = json.loads(enum_cache.read_text(encoding="utf-8"))
                entries, einfo = cached["entries"], cached["einfo"]
                log(f"  … {name}: enumeration cache hit "
                    f"({len(entries)} laws)")
            except Exception:
                entries = einfo = None
        if entries is None:
            entries, einfo, terminal = resolve_and_enumerate(sess, base, entry)
            if terminal is not None:
                return terminal
            try:
                tmp = enum_cache.with_suffix(".tmp")
                tmp.write_text(json.dumps({"entries": entries, "einfo": einfo},
                                          ensure_ascii=False), encoding="utf-8")
                tmp.replace(enum_cache)
            except Exception:
                pass
        upd.update({"laws_found_2025": len(entries), **einfo})
        if not entries:
            upd.update({"status": "zero_acts", "rows": 0,
                        "note": f"enumeration ({einfo['enum_source']}): "
                                f"json_count={einfo['json_count']}, "
                                f"total_found={einfo['total_found_raw']}, "
                                f"no {YEAR} Lei Ordinaria entries"})
            return upd

        # 3. per-law text: texto articulado first, PDF fallback.
        #    Pilot finding: most instances have NO texto articulado for
        #    current-year leis. After 3 consecutive TA misses with zero
        #    TA hits on an instance, stop probing and go PDF-direct —
        #    halves the requests on PDF-only instances.
        #    PER-LAW CHECKPOINTING: every harvested law is appended to
        #    partials/<ibge>.jsonl the moment it succeeds and reloaded
        #    on the next attempt, so a VM reboot / OOM kill loses at
        #    most the one law in flight instead of up to ~110 laws of
        #    whole-host staging (three near-complete hosts were lost
        #    that way on 2026-10-13).
        import html as htmlmod
        PARTIAL_DIR.mkdir(parents=True, exist_ok=True)
        partial_path = PARTIAL_DIR / f"{ibge}.jsonl"
        done_laws = {}
        if partial_path.exists():
            for line in partial_path.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                    done_laws[rec["pk"]] = rec
                except Exception:
                    pass
        rows = []
        n_ta = n_pdf = n_ocr = n_failed = 0
        for rec in done_laws.values():
            rows.extend(rec["rows"])
            if rec["mode"] == "ta":
                n_ta += 1
            else:
                n_pdf += 1
                if rec.get("ocr"):
                    n_ocr += 1
        ta_misses = 0
        pdf_first = n_ta == 0 and n_pdf >= 3
        failed_pks = []
        if done_laws:
            log(f"  … {name}: resuming — {len(done_laws)} laws already "
                f"checkpointed")
        for idx, e in enumerate(entries):
            if e["pk"] in done_laws:
                continue
            if idx and idx % 5 == 0:
                log(f"  … {name}: {n_ta + n_pdf + n_failed}/{len(entries)} laws "
                    f"(TA {n_ta} / PDF {n_pdf} / failed {n_failed})")
            title = e["title"]
            iso_date = e["date"]
            done = False
            detail_soup = None
            law_rows = []
            mode = None
            ocr_used = False
            if not pdf_first:
                try:
                    r, _ = get_retry(sess, f"{base}/norma/{e['pk']}")
                    page_soup = pilot.BeautifulSoup(r.text, "html.parser")
                    devices = pilot.extract_devices(page_soup)
                    chunks = pilot.group_articles(devices) if devices else []
                    chunks = [(lab, ch) for lab, ch in chunks
                              if any(t.strip() for _, t in ch)]
                    if chunks:
                        if not title:
                            title = find_title_in_page(page_soup) or \
                                constructed_title(e)
                            _, iso_date = parse_date2(title)
                        if not iso_date:
                            iso_date = find_date_in_text(page_soup.get_text(" "))
                        for i, (lab, ch) in enumerate(chunks):
                            suffix = "preambulo" if lab == "Preâmbulo" else f"art{i}"
                            law_rows.append(pilot.make_row(
                                jurisdiction_id=ibge, jurisdiction_name=name,
                                country="BR",
                                doc_id=f"br-{ibge}-{e['pk']}-{suffix}",
                                regeling_id=f"sapl:{host}:norma-{e['pk']}",
                                title=title, structural_path=title,
                                node_label=lab,
                                body_html=pilot.devices_to_html(ch),
                                source_url=r.url, date_effective=iso_date,
                                retrieved=RETRIEVED, tipo="Lei Ordinária"))
                        mode = "ta"
                        ta_misses = 0
                        done = True
                    else:
                        detail_soup = page_soup  # /norma/<pk> IS the detail page
                        raise ValueError("no TA devices parsed")
                except Exception:
                    ta_misses += 1
                    if n_ta == 0 and ta_misses >= 3:
                        pdf_first = True
                        log(f"  … {name}: no TA on first {ta_misses} laws — "
                            f"switching to PDF-direct")
            if not done and e["pdf_url"]:
                try:
                    import fitz
                    pdf_url = e["pdf_url"]
                    try:
                        content = fetch_pdf_bytes(sess, pdf_url)
                    except TimeoutError:
                        raise  # same host, same trickle — https retry is futile
                    except Exception:
                        if pdf_url.startswith("http://"):
                            pdf_url = "https://" + pdf_url[len("http://"):]
                            content = fetch_pdf_bytes(sess, pdf_url)
                        else:
                            raise
                    doc = fitz.open(stream=content, filetype="pdf")
                    text = "\n".join(p.get_text() for p in doc).strip()
                    ocr_used = False
                    if len(text) < 50:
                        ocr_text = ocr_pdf_text(content)
                        if len(ocr_text) > len(text):
                            text = ocr_text
                            ocr_used = True
                    if text:
                        if not title and detail_soup is not None:
                            title = find_title_in_page(detail_soup) or \
                                constructed_title(e)
                            _, iso_date = parse_date2(title)
                        if not title:
                            title = constructed_title(e)
                        if not iso_date:
                            iso_date = find_date_in_text(text[:2000])
                        law_rows.append(pilot.make_row(
                            jurisdiction_id=ibge, jurisdiction_name=name,
                            country="BR",
                            doc_id=f"br-{ibge}-{e['pk']}-doc",
                            regeling_id=f"sapl:{host}:norma-{e['pk']}",
                            title=title, structural_path=title,
                            node_label=title,
                            body_html="<pre>" + htmlmod.escape(text) + "</pre>",
                            source_url=pdf_url,
                            date_effective=iso_date, retrieved=RETRIEVED,
                            tipo="Lei Ordinária"))
                        mode = "pdf"
                        done = True
                except Exception:
                    pass
            if done:
                if mode == "ta":
                    n_ta += 1
                else:
                    n_pdf += 1
                    if ocr_used:
                        n_ocr += 1
                rec = {"pk": e["pk"], "mode": mode, "ocr": bool(ocr_used),
                       "rows": law_rows}
                try:
                    with open(partial_path, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                except Exception:
                    pass  # checkpointing is best-effort; rows live in memory
                done_laws[e["pk"]] = rec
                rows.extend(law_rows)
            else:
                n_failed += 1
                failed_pks.append(e["pk"])
        upd.update({"laws_harvested": n_ta + n_pdf, "laws_ta": n_ta,
                    "laws_pdf": n_pdf, "laws_ocr": n_ocr,
                    "laws_failed": n_failed,
                    "failed_pks": failed_pks[:50]})
        if not rows:
            return {**upd, "status": "failed",
                    "error": f"all {len(entries)} laws failed TA+PDF extraction"}

        # 4. normalize + fail-closed validation + staged parquet
        rows = pilot.finalize_rows(rows)
        table = pilot.rows_to_table(rows, extra_columns=[("tipo", pa.string())])
        errors = wm.validate_table(table, jurisdiction_id=ibge,
                                   jurisdiction_name=name, country="BR")
        report = wm.validation_report(table, jurisdiction_id=ibge,
                                      jurisdiction_name=name, country="BR")
        wm.write_validation_report(VAL_DIR / f"{ibge}_validation.json", report)
        if errors:
            return {**upd, "status": "validation_failed",
                    "error": "; ".join(errors[:5]), "rows": 0}
        n = wm.write_html_parquet(DATA_DIR / f"{ibge}_html.parquet", table)
        return {**upd, "status": "validated", "rows": n}
    except Exception as exc:
        return {**upd, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        upd["requests"] = sess.n_requests
        upd["fetch_seconds"] = round(sess.fetch_seconds, 1)
        upd["wall_seconds"] = round(time.monotonic() - t_start, 1)


def run_muni(state: dict, api, entry: dict) -> None:
    ibge = entry["ibge"]
    with _state_lock:
        state["municipios"][ibge]["attempts"] += 1
        attempt = state["municipios"][ibge]["attempts"]
        save_state(state)
    log(f"== {entry['name']} ({ibge}, {entry['uf']}) attempt {attempt} ==")
    # publish-only resume: a previous attempt validated the parquet but
    # the upload failed — don't re-harvest the host for that.
    if entry.get("status") == "validated" and \
            (DATA_DIR / f"{ibge}_html.parquet").exists():
        try:
            oid = publish_parquet(api, ibge, DATA_DIR / f"{ibge}_html.parquet")
            update_entry(state, ibge, status="published", commit=oid,
                         verified=True)
            (PARTIAL_DIR / f"{ibge}.jsonl").unlink(missing_ok=True)
            (PARTIAL_DIR / f"{ibge}.enum.json").unlink(missing_ok=True)
            log(f"  ✓ {entry['name']}: published (resume) {entry.get('rows')} rows")
        except Exception as exc:
            update_entry(state, ibge,
                         publish_error=f"{type(exc).__name__}: {exc}")
            log(f"  ! {entry['name']}: publish resume failed: {exc}")
        return
    upd = harvest_muni(entry)
    if upd.get("status") == "validated":
        try:
            oid = publish_parquet(api, ibge, DATA_DIR / f"{ibge}_html.parquet")
            upd.update({"status": "published", "commit": oid, "verified": True})
            (PARTIAL_DIR / f"{ibge}.jsonl").unlink(missing_ok=True)
            (PARTIAL_DIR / f"{ibge}.enum.json").unlink(missing_ok=True)
            log(f"  ✓ {entry['name']}: published {upd['rows']} rows "
                f"({upd.get('laws_harvested')} laws: {upd.get('laws_ta')} TA / "
                f"{upd.get('laws_pdf')} PDF)")
        except Exception as exc:
            upd.update({"status": "validated",
                        "publish_error": f"{type(exc).__name__}: {exc}"})
            log(f"  ! {entry['name']}: publish failed (kept local): {exc}")
    elif upd.get("status") == "failed":
        log(f"  ✗ {entry['name']}: {upd.get('error')}")
    elif upd.get("status") == "zero_acts":
        log(f"  ○ {entry['name']}: zero {YEAR} acts")
        (PARTIAL_DIR / f"{ibge}.enum.json").unlink(missing_ok=True)
    update_entry(state, ibge, **upd)


# ---------------------------------------------------------------- modes
def mode_seed() -> None:
    api = hf_api()
    from huggingface_hub import create_repo
    create_repo(REPO, repo_type="dataset", exist_ok=True)
    log(f"dataset ready: {REPO}")
    state = load_state()
    # pilot parquet row counts come from their validation sidecars
    man = json.loads((PILOT_DIR / "run_manifest.json").read_text())
    by_ibge = {v["ibge"]: v for v in man.values()}
    for ibge in PILOTS:
        pq = PILOT_DIR / f"{ibge}_html.parquet"
        oid = publish_parquet(api, ibge, pq)
        m = by_ibge[ibge]
        modes = [s["mode"] for s in m["sampled"]]
        update_entry(state, ibge, status="seed_published", commit=oid,
                     verified=True, rows=m["rows"],
                     laws_harvested=len(m["sampled"]),
                     laws_found_2025=m.get("total_found"),
                     laws_ta=sum(1 for x in modes if x == "ta-html"),
                     laws_pdf=sum(1 for x in modes if x == "pdf-fallback"),
                     laws_failed=sum(1 for x in modes if x.startswith("failed")),
                     note="pilot 5-law sample; full-2025 harvest pending")
        log(f"  ✓ seed {ibge} {m['name']}: {m['rows']} rows published")
    stats = upload_coverage(api, state)
    log(f"seed complete: {stats}")


def mode_run() -> None:
    api = hf_api()
    state = load_state()
    t0 = time.monotonic()
    round_no = 0
    while True:
        round_no += 1
        todo = [e for e in state["municipios"].values()
                if (e["status"] in ("pending", "validated")
                    or (e["status"] == "failed"
                        and e.get("attempts", 0) < MAX_ATTEMPTS))
                and e["ibge"] not in PILOTS]
        if not todo:
            break
        log(f"--- pass {round_no}: {len(todo)} municipios ---")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(run_muni, state, api, e): e["ibge"] for e in todo}
            done_n = 0
            for fut in as_completed(futs):
                fut.result()
                done_n += 1
                pub = sum(1 for e in state["municipios"].values()
                          if e["status"] in ("published", "seed_published"))
                if pub and pub % 10 == 0 and done_n % 5 == 0:
                    try:
                        upload_coverage(api, state)
                    except Exception as exc:
                        log(f"coverage upload skipped: {exc}")
        # loop again only to retry failures (attempts permitting)
        still = [e for e in state["municipios"].values()
                 if e["status"] == "failed" and e.get("attempts", 0) < MAX_ATTEMPTS]
        if not still:
            break
    stats = upload_coverage(api, state)
    wall = round(time.monotonic() - t0, 1)
    log(f"run complete in {wall}s: {stats}")


def mode_verify() -> None:
    api = hf_api()
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download
    files = sorted(api.list_repo_files(REPO, repo_type="dataset"))
    parquets = [f for f in files if f.endswith(".parquet")]
    print(f"remote files: {len(files)}; parquets: {len(parquets)}")
    total = 0
    for f in parquets:
        p = hf_hub_download(REPO, f, repo_type="dataset",
                            local_dir="/tmp/br_verify")
        n = pq.read_metadata(p).num_rows
        total += n
        print(f"  {f}: {n}")
    print(f"total remote rows: {total}")
    for f in files:
        if not f.endswith(".parquet"):
            print("  other:", f)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"
    {"seed": mode_seed, "run": mode_run, "verify": mode_verify,
     "coverage": lambda: print(upload_coverage(hf_api(), load_state()))}[mode]()
