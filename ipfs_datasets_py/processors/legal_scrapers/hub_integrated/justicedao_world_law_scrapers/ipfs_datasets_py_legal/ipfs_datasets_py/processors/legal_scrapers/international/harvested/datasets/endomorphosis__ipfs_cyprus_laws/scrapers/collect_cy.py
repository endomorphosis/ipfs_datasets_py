#!/usr/bin/env python3
"""Cyprus: official GPO gazette PDFs (mof.gov.cy). No cylaw.org.

Discovery:
  1) Live Domino section views (Κύριο Μέρος / Παραρτήματα)
  2) Archive outline Expand=year.month.part (2004–present)
  3) Per-issue OpenDocument pages → $file PDF attachments
  4) Wayback CDX of official GPO $file / gazette.nsf URLs (fallback)

PDFs extracted via pdftotext (common.pdf_bytes_to_text). TLS verify may fail
on incomplete GPO chain from this network — official host still used.
"""
from __future__ import annotations

import html as htmlmod
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import logging
import re
import sys
import time
import warnings
from pathlib import Path
from urllib.parse import urljoin, unquote, quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *  # noqa: F401,F403
from archive_fallbacks import search_wayback_machine, get_wayback_content

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

CC, COUNTRY, SOURCE_TYPE = "cy", "Cyprus", "gpo_gazette"
LICENSE = (
    "Official Gazette of the Republic of Cyprus, Government Printing Office "
    "(mof.gov.cy/gpo). cylaw.org is unofficial and is NOT used."
)
UA = DEFAULT_UA + " source=https://www.mof.gov.cy/mof/gpo/"
BASE = "https://www.mof.gov.cy"
GAZETTE_NSF = f"{BASE}/mof/gpo/gazette.nsf"
log = logging.getLogger("cy")

# Domino All/{UNID}?OpenDocument
UNID_RE = re.compile(r"/mof/gpo/gazette\.nsf/All/([0-9A-Fa-f]{32})\?OpenDocument", re.I)
# $file PDF hrefs (spaces in filenames are common)
FILE_RE = re.compile(
    r"""(?:href|src)\s*=\s*["']([^"']*\$[Ff][Ii][Ll][Ee]/[^"']+\.pdf)["']""",
    re.I,
)
# Expand=Y.M.P outline links
EXPAND_RE = re.compile(
    r"dmlgazette_archive_gr\?OpenForm[^\"']*Expand=([0-9]+(?:\.[0-9]+){0,3})",
    re.I,
)
# Skip chrome / policy pages
SKIP_PATH_RE = re.compile(
    r"(accessibility|privacypolicy|gazetteinfo|favicon|settings\.css|"
    r"officialgazette-(?:el|en)|dmlgaz_NEW_|dmlgaz_app_|dmlprevious|"
    r"dmlgazette_archive|dmlgaz_view_sections|SearchResults|"
    r"font-awesome|icon-font|layers\.css|navigation\.css)",
    re.I,
)
CYLAW_RE = re.compile(r"cylaw\.org", re.I)

# Greek gazette instrument markers inside PDF text (Hub-compatible Αριθμός + Άρθρο)
CY_ART_RE = re.compile(
    r"(?im)^\s*((?:Άρθρο|Αρθρο|Aρθρο|Άρθρον|"
    r"Αριθμός|Aριθμός|ΑΡΙΘΜΟΣ|Αρ\.)\s+"
    r"[\dIVXLCDMΙ]+[ΙI()0-9A-Za-zΑ-Ωα-ω΄']*)\b"
)

# How far back to walk the archive outline (Expand index 1 = newest year)
MAX_YEAR_EXPAND = 23  # ~2004–2026
MAX_CDX = 2500
FETCH_SLEEP = 0.35


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )


def try_get(url: str, *, accept: str = "text/html, application/pdf, */*", binary_ok: bool = True):
    """GET official GPO; retry with verify=False (incomplete cert chain)."""
    last = None
    for verify in (True, False):
        try:
            time.sleep(FETCH_SLEEP)
            r = get_session(UA).get(
                url,
                timeout=(20, 120),
                verify=verify,
                headers={"User-Agent": UA, "Accept": accept},
                allow_redirects=True,
            )
            if r.status_code == 200 and (binary_ok or r.content):
                return r, verify
            last = r
            if r.status_code in (404, 410):
                return r, verify
        except Exception as exc:
            last = exc
    return last, None


def is_official(url: str) -> bool:
    if not url or CYLAW_RE.search(url):
        return False
    u = url.lower()
    return "mof.gov.cy" in u and ("/gpo/" in u or "gazette.nsf" in u or "gpo.nsf" in u)


def extract_unids(html: str) -> list[str]:
    return list(dict.fromkeys(m.group(1).upper() for m in UNID_RE.finditer(html or "")))


def extract_pdf_hrefs(page_url: str, html: str) -> list[str]:
    out = []
    seen = set()
    for m in FILE_RE.finditer(html or ""):
        href = htmlmod.unescape(m.group(1).strip())
        full = urljoin(page_url, href)
        if not is_official(full):
            continue
        if SKIP_PATH_RE.search(full):
            continue
        if full.lower() in seen:
            continue
        seen.add(full.lower())
        out.append(full)
    # also bare $file paths without href=
    for m in re.finditer(r"(/mof/gpo/gazette\.nsf/[0-9A-Fa-f]{32}/\$file/[^\s\"'<>]+\.pdf)", html or "", re.I):
        full = urljoin(BASE, htmlmod.unescape(m.group(1)))
        if full.lower() not in seen and is_official(full):
            seen.add(full.lower())
            out.append(full)
    return out


def split_cy_articles(text: str, law_id: str, source_url: str, date: str | None) -> list[dict]:
    if not text or len(text) < 40:
        return []
    matches = list(CY_ART_RE.finditer(text))
    if len(matches) < 2:
        # fall back to common splitter (may still yield 0)
        return split_articles(text, law_id, source_url, date)
    docs = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if len(chunk) < 30:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-") or f"n{i}"
        heading = chunk.split("\n", 1)[0][:200]
        docs.append({
            "id": f"{law_id}-{aid}"[:180],
            "title": heading,
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "pdftotext"}},
        })
        if len(docs) >= 4000:
            break
    return docs


def title_from_pdf_url(url: str, text: str) -> str:
    name = unquote(url.split("/")[-1])
    name = re.sub(r"\.pdf$", "", name, flags=re.I).strip()
    name = re.sub(r"\s+", " ", name)
    if text:
        # first non-empty line that looks like gazette header
        for line in text.splitlines()[:40]:
            line = line.strip()
            if len(line) > 12 and re.search(r"(ΕΦΗΜΕΡΙΔΑ|Επίσημη|PARARTIMA|ΠΑΡΑΡΤΗΜΑ|ΚΥΡΙΟ|KYRIO)", line, re.I):
                return line[:240]
            if re.match(r"^Αριθμός\s+\d+", line, re.I) or re.match(r"^Aριθμός\s+\d+", line):
                return (name + " — " + line)[:240]
    return name[:240] or url


def date_from_name(name: str) -> str | None:
    # e.g. "5885 4 9 2026 KYRIO MEROS..." or "4597Α 6 10 2023 PARARTIMA..."
    m = re.search(r"\b(\d{1,2})\s+(\d{1,2})\s+(20\d{2})\b", name)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.search(r"\b(20\d{2})[-_/](\d{1,2})[-_/](\d{1,2})\b", name)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def pdf_ident(url: str) -> str:
    """Stable identifier from UNID + filename."""
    m = re.search(r"/gazette\.nsf/(?:All/)?([0-9A-Fa-f]{32})/", url, re.I)
    unid = (m.group(1).upper() if m else "nouid")
    fname = unquote(url.split("/")[-1])
    fname = re.sub(r"\.pdf$", "", fname, flags=re.I)
    fname = re.sub(r"\s+", "_", fname.strip())
    return f"gpo-{unid}-{fname}"[:160]


def discover_section_unids(notes: list[str]) -> set[str]:
    unids: set[str] = set()
    # Main + appendix landing pages → section links
    seeds = [
        f"{GAZETTE_NSF}/dmlgaz_NEW_gr/dmlgaz_NEW_gr?OpenDocument",
        f"{GAZETTE_NSF}/dmlgaz_NEW_en/dmlgaz_NEW_en?OpenDocument",
        f"{GAZETTE_NSF}/dmlgaz_app_gr/dmlgaz_app_gr?OpenDocument",
        f"{GAZETTE_NSF}/dmlgaz_app_en/dmlgaz_app_en?OpenDocument",
        f"{GAZETTE_NSF}/officialgazette-el/officialgazette-el?OpenDocument",
    ]
    section_urls = set()
    for url in seeds:
        r, verify = try_get(url)
        if not hasattr(r, "status_code"):
            notes.append(f"seed {url} ERROR {r}")
            continue
        notes.append(f"seed {url} -> HTTP {r.status_code} bytes={len(r.content or b'')} verify={verify}")
        if r.status_code != 200 or not r.content:
            continue
        html = r.text or ""
        unids.update(extract_unids(html))
        for m in re.finditer(r'href=["\']([^"\']*dmlgaz_view_sections[^"\']+)["\']', html, re.I):
            section_urls.add(urljoin(url, htmlmod.unescape(m.group(1))))
        for m in re.finditer(r'href=["\']([^"\']*view_sections[^"\']+)["\']', html, re.I):
            section_urls.add(urljoin(url, htmlmod.unescape(m.group(1))))
    # Explicit sectionNumber sweeps (main parts 1–3; appendices often reuse)
    for sec in range(1, 8):
        for cp in ("11", "21", "22", "12", "31", "32"):
            section_urls.add(
                f"{GAZETTE_NSF}/dmlgaz_view_sections_gr/dmlgaz_view_sections_gr"
                f"?OpenDocument&OpenView&Count=1000&cp={cp}&sectionNumber={sec}"
            )
            section_urls.add(
                f"{GAZETTE_NSF}/dmlgaz_view_sections_gr/dmlgaz_view_sections_gr"
                f"?OpenDocument&sectionNumber={sec}&cp={cp}"
            )
    # Prefer Count=1000 OpenView URLs; skip redundant Start pagination when
    # Domino returns a small page (typical ~20) — use archive Expand for depth.
    prefer = [u for u in sorted(section_urls) if "Count=1000" in u or "OpenView" in u]
    rest = [u for u in sorted(section_urls) if u not in prefer]
    for url in prefer + rest[:20]:
        if not is_official(url):
            continue
        r, _ = try_get(url)
        if not hasattr(r, "status_code") or r.status_code != 200 or not r.content:
            continue
        found = extract_unids(r.text or "")
        before = len(unids)
        unids.update(found)
        # Only paginate when the view clearly has a large batch
        if len(found) >= 80 and ("OpenView" in url or "Count=" in url):
            for start in (31, 61, 91, 121, 151, 181, 211, 241, 271, 301):
                page = url
                if "Start=" in page:
                    page = re.sub(r"Start=\d+", f"Start={start}", page)
                else:
                    page = page + ("&" if "?" in page else "?") + f"Start={start}"
                r2, _ = try_get(page)
                if not hasattr(r2, "status_code") or r2.status_code != 200 or not r2.content:
                    break
                more = extract_unids(r2.text or "")
                new_n = len(set(more) - unids)
                unids.update(more)
                if new_n == 0:
                    break
        log.info("section +%s total_unids=%s url=%s", len(unids) - before, len(unids), url[-80:])
    return unids


def discover_archive_unids(notes: list[str]) -> set[str]:
    """Walk Domino outline Expand=year[.month[.part]]."""
    unids: set[str] = set()
    archive = f"{GAZETTE_NSF}/dmlgazette_archive_gr/dmlgazette_archive_gr?OpenForm&Start=1&Count=9999"
    # First fetch root to learn year expand indices
    r, _ = try_get(archive)
    year_idxs = list(range(1, MAX_YEAR_EXPAND + 1))
    if hasattr(r, "status_code") and r.status_code == 200 and r.content:
        found_exp = {int(m.group(1).split(".")[0]) for m in EXPAND_RE.finditer(r.text or "") if "." not in m.group(1)}
        if found_exp:
            year_idxs = sorted(found_exp)[:MAX_YEAR_EXPAND]
        notes.append(f"archive root years={year_idxs[:5]}... n={len(year_idxs)}")
    for y in year_idxs:
        for m in range(1, 13):
            for p in (1, 2):  # Κύριο Μέρος / Παραρτήματα
                exp = f"{y}.{m}.{p}"
                url = f"{archive}&Expand={exp}&Seq=1"
                r, _ = try_get(url)
                if not hasattr(r, "status_code") or r.status_code != 200 or not r.content:
                    continue
                found = extract_unids(r.text or "")
                # Sometimes need deeper Expand=y.m.p.q
                if not found:
                    deeper = set()
                    for m2 in EXPAND_RE.finditer(r.text or ""):
                        key = m2.group(1)
                        if key.startswith(exp + "."):
                            deeper.add(key)
                    for key in sorted(deeper)[:8]:
                        r2, _ = try_get(f"{archive}&Expand={key}&Seq=1")
                        if hasattr(r2, "status_code") and r2.status_code == 200 and r2.content:
                            found.extend(extract_unids(r2.text or ""))
                before = len(unids)
                unids.update(found)
                if found:
                    log.info("archive Expand=%s +%s total_unids=%s", exp, len(unids) - before, len(unids))
        log.info("archive year_idx=%s total_unids=%s", y, len(unids))
    # Previous-years index form
    prev = f"{GAZETTE_NSF}/dmlprevious_Archive_gr/dmlprevious_Archive_gr?OpenForm"
    r, _ = try_get(prev)
    if hasattr(r, "status_code") and r.status_code == 200 and r.content:
        unids.update(extract_unids(r.text or ""))
        for m in re.finditer(r'href=["\']([^"\']+)["\']', r.text or ""):
            href = urljoin(prev, htmlmod.unescape(m.group(1)))
            if "gazette.nsf" in href and is_official(href) and not SKIP_PATH_RE.search(href):
                if "OpenDocument" in href or "OpenForm" in href or "Expand=" in href:
                    r2, _ = try_get(href)
                    if hasattr(r2, "status_code") and r2.status_code == 200 and r2.content:
                        unids.update(extract_unids(r2.text or ""))
    notes.append(f"archive_unids={len(unids)}")
    cache = ROOT / CC / "raw" / "discovered_unids.txt"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("\n".join(sorted(unids)) + "\n", encoding="utf-8")
    log.info("wrote unid cache n=%s path=%s", len(unids), cache)
    return unids


def discover_cdx_pdfs(notes: list[str]) -> list[dict]:
    """Wayback CDX for official GPO PDF attachments."""
    patterns = [
        "www.mof.gov.cy/mof/gpo/gazette.nsf/*$file*",
        "www.mof.gov.cy/mof/gpo/gazette.nsf/*.pdf",
        "www.mof.gov.cy/mof/gpo/gazette.nsf/*",
    ]
    out = []
    seen = set()
    for pat in patterns:
        try:
            rows = search_wayback_machine(
                pat,
                limit=MAX_CDX if "file" in pat or "pdf" in pat else 800,
                collapse="digest",
                match_type=None,
                extra_filters=["mimetype:application/pdf"],
            )
        except Exception as exc:
            notes.append(f"cdx {pat} ERROR {exc}")
            continue
        n = 0
        for rec in rows:
            orig = rec.get("original") or ""
            if not is_official(orig):
                continue
            if ".pdf" not in orig.lower() and "$file" not in orig.lower() and "$FILE" not in orig:
                continue
            if CYLAW_RE.search(orig) or SKIP_PATH_RE.search(orig):
                continue
            key = orig.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(rec)
            n += 1
        notes.append(f"cdx {pat} pdfish={n} raw={len(rows)}")
        log.info("cdx %s pdfish=%s", pat, n)
        time.sleep(2.0)
    return out


def issue_pdfs_from_unid(unid: str) -> list[str]:
    page = f"{GAZETTE_NSF}/All/{unid}?OpenDocument"
    r, _ = try_get(page)
    if not hasattr(r, "status_code") or r.status_code != 200 or not r.content:
        return []
    return extract_pdf_hrefs(page, r.text or "")


def fetch_pdf_bytes(url: str, wayback_ts: str | None = None) -> tuple[bytes, str, str]:
    """Return (bytes, resolved_url, method)."""
    # Live first
    r, _ = try_get(url, accept="application/pdf, */*")
    if hasattr(r, "status_code") and r.status_code == 200 and r.content and r.content[:4] == b"%PDF":
        return r.content, url, "live_gpo"
    # URL-encode spaces if needed
    if " " in url:
        parts = url.split("/$file/", 1)
        if len(parts) == 2:
            enc = parts[0] + "/$file/" + quote(parts[1], safe="/()")
            r2, _ = try_get(enc, accept="application/pdf, */*")
            if hasattr(r2, "status_code") and r2.status_code == 200 and r2.content and r2.content[:4] == b"%PDF":
                return r2.content, enc, "live_gpo_encoded"
    # Wayback
    try:
        wb = get_wayback_content(url, timestamp=wayback_ts)
    except Exception:
        wb = {"status": "error"}
    if wb.get("status") in (None, "ok", "success") or wb.get("content") or wb.get("body"):
        body = wb.get("content") or wb.get("body") or b""
        if isinstance(body, str):
            body = body.encode("utf-8", "replace")
        if body[:4] == b"%PDF":
            return body, wb.get("wayback_url") or url, "wayback"
    # Direct wayback id_ URL if we have ts
    if wayback_ts:
        wb_url = f"https://web.archive.org/web/{wayback_ts}id_/{url}"
        try:
            time.sleep(1.0)
            r3 = get_session(UA).get(wb_url, timeout=(20, 120), headers={"User-Agent": UA})
            if r3.status_code == 200 and r3.content[:4] == b"%PDF":
                return r3.content, wb_url, "wayback_direct"
        except Exception:
            pass
    return b"", url, "fail"


def save_pdf_instrument(url: str, raw: bytes, method: str, done: set[str]) -> str:
    ident = pdf_ident(url)
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    text = pdf_bytes_to_text(raw, timeout=240)
    if not text or len(text) < 80:
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": "pdf_empty_text"})
        return "fail"
    fname = unquote(url.split("/")[-1])
    date = date_from_name(fname) or date_from_name(text[:500])
    title = title_from_pdf_url(url, text)
    docs = split_cy_articles(text, rid, url, date)
    rec = base_record(
        cc=CC,
        country=COUNTRY,
        language="el",
        ident=ident,
        title=title,
        text=text,
        source_url=url,
        source_type=SOURCE_TYPE,
        license_text=LICENSE,
        collector="cy-gpo-pdf",
        eli=None,
        date=date,
        official_identifier=ident,
        document_type="gazette_pdf",
        law_status="unknown",
        is_current=None,
        documents=docs if docs else None,
        extra_meta={
            "discovery": {"method": method},
            "text_extraction": {"backend": "pdftotext", "source": "official_gpo_pdf"},
            "pdf_bytes": len(raw),
        },
    )
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"



def existing_source_urls(cc: str) -> set[str]:
    """URLs already stored for cross-slug dedup with cy_fetch_discovery."""
    out: set[str] = set()
    d = ROOT / cc / "instruments"
    if not d.exists():
        return out
    for path in d.glob("*.json"):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for key in ("source_url", "canonical_law_url", "original_url"):
            u = (rec.get(key) or "").strip()
            if u:
                out.add(u.split("?")[0].lower())
        meta = rec.get("metadata") or {}
        if isinstance(meta, dict):
            for key in ("canonical_law_url", "original_url"):
                u = (meta.get(key) or "").strip()
                if u:
                    out.add(u.split("?")[0].lower())
            disc = meta.get("discovery") or {}
            if isinstance(disc, dict):
                u = (disc.get("original_url") or "").strip()
                if u:
                    out.add(u.split("?")[0].lower())
            ef = meta.get("extra_fields") or rec.get("extra_fields") or {}
            if isinstance(ef, dict):
                u = (ef.get("canonical_law_url") or "").strip()
                if u:
                    out.add(u.split("?")[0].lower())
    return out


def load_cdx_discovery_file() -> list[tuple[str, str | None]]:
    path = ROOT / CC / "raw" / "cdx_discovery.jsonl"
    out: list[tuple[str, str | None]] = []
    if not path.exists():
        return out
    seen = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        url = (rec.get("original") or rec.get("url") or "").strip()
        if not url or not is_official(url):
            continue
        low = url.lower()
        if ".pdf" not in low and "$file" not in low:
            continue
        key = url.split("?")[0].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((url, rec.get("timestamp")))
    return out


def main():
    setup()
    t0 = utcnow()
    notes: list[str] = []
    done = existing_ids(CC)
    have_urls = existing_source_urls(CC)
    ok = skip = fail = 0

    log.info("=== CY GPO PDF harvest start existing=%s urls=%s ===", len(done), len(have_urls))

    # --- Discovery: UNIDs from live site (or cache) ---
    unids: set[str] = set()
    cache = ROOT / CC / "raw" / "discovered_unids.txt"
    use_cache = cache.exists() and cache.stat().st_size > 10000 and not os.environ.get("CY_FORCE_REDISCOVER")
    if use_cache:
        unids = {ln.strip().upper() for ln in cache.read_text(encoding="utf-8").splitlines() if ln.strip()}
        notes.append(f"loaded_unid_cache={len(unids)}")
        log.info("loaded unid cache n=%s", len(unids))
    else:
        try:
            unids |= discover_section_unids(notes)
        except Exception as exc:
            notes.append(f"section_discover ERROR {exc}")
            log.exception("section_discover")
        log.info("after sections unids=%s", len(unids))
        try:
            unids |= discover_archive_unids(notes)
        except Exception as exc:
            notes.append(f"archive_discover ERROR {exc}")
            log.exception("archive_discover")
        log.info("after archive unids=%s", len(unids))

    # Skip UNIDs already represented in existing instrument URLs
    known_unids = set()
    for u in have_urls:
        m = re.search(r"/([0-9a-f]{32})/", u, re.I)
        if m:
            known_unids.add(m.group(1).upper())
        m = re.search(r"gazette\.nsf-([0-9a-f]{32})", u, re.I)
        if m:
            known_unids.add(m.group(1).upper())
    todo_unids = sorted(u for u in unids if u.upper() not in known_unids)
    log.info("unids total=%s known=%s todo=%s", len(unids), len(known_unids), len(todo_unids))
    notes.append(f"unids_total={len(unids)} known={len(known_unids)} todo={len(todo_unids)}")

    # Resolve UNIDs → PDF URLs (parallel)
    pdf_jobs: list[tuple[str, str | None]] = []  # (url, wayback_ts)
    seen_pdf = set(have_urls)
    workers = int(os.environ.get("CY_RESOLVE_WORKERS", "8"))

    def _resolve(unid: str) -> list[str]:
        try:
            return issue_pdfs_from_unid(unid)
        except Exception as exc:
            log.warning("issue %s fail %s", unid, exc)
            return []

    done_n = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_resolve, u): u for u in todo_unids}
        for fut in as_completed(futs):
            done_n += 1
            pdfs = fut.result() or []
            for u in pdfs:
                key = u.split("?")[0].lower()
                if key in seen_pdf:
                    continue
                seen_pdf.add(key)
                pdf_jobs.append((u, None))
            if done_n % 100 == 0 or done_n == len(todo_unids):
                log.info("resolved issues %s/%s pdfs=%s", done_n, len(todo_unids), len(pdf_jobs))

    notes.append(f"live_unids={len(unids)} live_pdfs={len(pdf_jobs)}")

    # --- Prior CDX discovery file ---
    for url, ts in load_cdx_discovery_file():
        key = url.split("?")[0].lower()
        if key in seen_pdf:
            continue
        seen_pdf.add(key)
        pdf_jobs.append((url, ts))
    notes.append(f"after_cdx_file pdfs={len(pdf_jobs)}")

    # --- CDX fallback PDFs ---
    try:
        cdx_rows = discover_cdx_pdfs(notes)
    except Exception as exc:
        cdx_rows = []
        notes.append(f"cdx ERROR {exc}")
    for rec in cdx_rows:
        orig = rec.get("original") or ""
        key = orig.lower()
        if key in seen_pdf:
            continue
        seen_pdf.add(key)
        pdf_jobs.append((orig, rec.get("timestamp")))

    discovered = len(pdf_jobs)
    log.info("=== fetch phase discovered_pdfs=%s ===", discovered)
    notes.append(f"discovered_pdfs={discovered}")

    # Persist discovery list for resume/debug
    disc_path = ROOT / CC / "raw" / "discovered_pdfs.txt"
    disc_path.parent.mkdir(parents=True, exist_ok=True)
    disc_path.write_text("\n".join(u for u, _ in pdf_jobs) + "\n", encoding="utf-8")

    for i, (url, ts) in enumerate(pdf_jobs):
        ident = pdf_ident(url)
        rid = slug_id(CC, ident)
        url_key = url.split("?")[0].lower()
        if rid in done or url_key in have_urls:
            skip += 1
            continue
        try:
            raw, resolved, method = fetch_pdf_bytes(url, wayback_ts=ts)
        except Exception as exc:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": repr(exc)})
            continue
        if not raw:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": "pdf_fetch_fail"})
            continue
        st = save_pdf_instrument(resolved, raw, method, done)
        if st == "ok":
            have_urls.add(url_key)
            have_urls.add(resolved.split("?")[0].lower())
        ok += st == "ok"
        skip += st == "skip"
        fail += st == "fail"
        if (ok + fail) % 10 == 0 or i < 3:
            log.info("progress i=%s/%s ok=%s skip=%s fail=%s last=%s", i + 1, discovered, ok, skip, fail, method)
        if (ok + fail) % 50 == 0:
            write_summary(
                CC,
                country=COUNTRY,
                source="Cyprus Government Printing Office gazette PDFs",
                source_urls=[
                    f"{GAZETTE_NSF}/officialgazette-el/officialgazette-el?OpenDocument",
                    f"{GAZETTE_NSF}/dmlgazette_archive_gr/dmlgazette_archive_gr?OpenForm",
                ],
                license_text=LICENSE,
                discovered=discovered,
                fetched=ok,
                skipped=skip,
                failed=fail,
                coverage="catalog-backed incomplete",
                notes="\n".join(notes[-40:]),
                last_run=utcnow(),
            )

    # Also keep any useful HTML-only pages already present; do not re-scrape shallow seeds as instruments.
    notes.append(
        "GPO PDF harvest via live Domino archive/sections + Wayback CDX of official mof.gov.cy URLs. "
        "cylaw.org unused. legislation.gov.cy NXDOMAIN."
    )
    write_summary(
        CC,
        country=COUNTRY,
        source="Cyprus Government Printing Office gazette PDFs",
        source_urls=[
            f"{GAZETTE_NSF}/officialgazette-el/officialgazette-el?OpenDocument",
            f"{GAZETTE_NSF}/dmlgazette_archive_gr/dmlgazette_archive_gr?OpenForm",
            "https://www.gov.cy/en/service/episimi-efimerida-tis-dimokratias/",
        ],
        license_text=LICENSE,
        discovered=discovered,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="catalog-backed incomplete",
        notes="\n".join(notes),
        last_run=utcnow(),
        extra=f"started {t0} instruments_on_disk={len(existing_ids(CC))}",
    )
    log.info("done disc=%s ok=%s skip=%s fail=%s instruments=%s", discovered, ok, skip, fail, len(existing_ids(CC)))


if __name__ == "__main__":
    main()
