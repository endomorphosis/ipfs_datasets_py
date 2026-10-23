#!/usr/bin/env python3
"""Angola: Diário da República / official legislation PDFs.

Primary live hosts (Imprensa Nacional often unreachable from research egress):
  - GUE (Ministério da Justiça) legislacao-portal — official law / DR PDFs
  - Portal do Governo (governo.gov.ao) document categories — CIPRA-hosted PDFs
  - MinjusDH documentos?type=Legislação
Live Imprensa Nacional seeds first; Wayback/CDX of the SAME official .gov.ao URLs
only on failure / as catalog backup. No commercial consolidators, no WAF bypass.
"""
from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit, quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, fetch_official_prefer_pdf, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "ao", "Angola", "pt"
SOURCE_TYPE = "diario_republica_ao"
LICENSE = (
    "Diário da República / Imprensa Nacional de Angola and official "
    "republications on governo.gov.ao, gue.gov.ao (MinjusDH). "
    "Authentic gazette text prevails. Not legal advice."
)
UA = (
    "legal-corpora-collector/1.0 "
    "(research; source=https://www.imprensanacional.gov.ao/)"
)
ART = re.compile(
    r"(?im)^\s*((?:Artigo|Art\.|ARTIGO)\s+\d+[ºªo°a-zA-Z]?)\b"
)
log = logging.getLogger("ao")

GUE_LEG = "https://gue.gov.ao/portal/legislacao-portal"
GOV_CATS = (
    "legislacao",
    "decreto-presidencial",
    "despacho",
    "constituicao",
    "oge",
    "publicacao",
)
IMPRENSA_SEEDS = (
    "https://www.imprensanacional.gov.ao/",
    "https://www.imprensanacional.gov.ao/index.php?id=105&serie=1",
    "https://www.imprensanacional.gov.ao/index.php?id=105&serie=2",
    "https://www.imprensanacional.gov.ao/index.php?id=105&serie=3",
    "http://www.imprensanacional.gov.ao/",
)
MINJUSDH_LEG = "https://minjusdh.gov.ao/web/documentos?type=Legisla%C3%A7%C3%A3o"

# Official hosts only
ALLOWED_HOST_SUFFIXES = (
    "imprensanacional.gov.ao",
    "gue.gov.ao",
    "governo.gov.ao",
    "plataformacipra.gov.ao",
    "minjusdh.gov.ao",
    "portais.gov.ao",
    "minfin.gov.ao",
)


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES)


def _norm_pdf_url(raw: str, base: str) -> str | None:
    """Extract a clean PDF URL; GUE HTML sometimes appends title after .pdf."""
    if not raw:
        return None
    raw = raw.strip().split()[0]
    # Truncate at first .pdf (case-insensitive)
    low = raw.lower()
    i = low.find(".pdf")
    if i < 0:
        return None
    raw = raw[: i + 4]
    full = urljoin(base, raw)
    # Encode path safely (spaces / unicode) while preserving already-% encodings
    parts = urlsplit(full)
    path = quote(unquote(parts.path), safe="/%")
    full = urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))
    if not _host_ok(full):
        return None
    if not full.lower().endswith(".pdf"):
        return None
    return full


def _ident_from_url(url: str, prefix: str = "") -> str:
    name = unquote(Path(urlsplit(url).path).name)
    name = re.sub(r"\.pdf$", "", name, flags=re.I)
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"[^\w\-.\u00C0-\u024F]+", "-", name, flags=re.UNICODE)
    ident = (prefix + name).strip("-")[:160]
    return ident or re.sub(r"\W+", "-", url)[-80:]


def _add_raw(items, seen, href: str, base: str, portal: str, title: str | None = None):
    url = _norm_pdf_url(href, base)
    if not url or url in seen:
        return
    seen.add(url)
    items.append((_ident_from_url(url), url, {"portal": portal, "title": title}))


def _extract_pdf_hrefs(html: str, base: str) -> list[str]:
    out = []
    for m in re.finditer(r'href=["\']([^"\']+)["\']', html or "", re.I):
        href = m.group(1)
        if ".pdf" not in href.lower():
            continue
        u = _norm_pdf_url(href, base)
        if u:
            out.append(u)
    # Absolute URLs possibly unquoted in body
    for m in re.finditer(
        r'https?://(?:gue\.gov\.ao|plataformacipra\.gov\.ao|c2a\.portais\.gov\.ao|'
        r'www\.imprensanacional\.gov\.ao|imprensanacional\.gov\.ao)'
        r'[^"\'\s<>]*?\.pdf',
        html or "",
        re.I,
    ):
        u = _norm_pdf_url(m.group(0), base)
        if u:
            out.append(u)
    return list(dict.fromkeys(out))


def discover_gue(items, seen):
    try:
        r = live_get(GUE_LEG, ua=UA, verify=False, timeout=(15, 45), retries=2)
    except Exception as exc:
        log.info("gue fail: %s", exc)
        return
    if getattr(r, "status_code", 0) != 200:
        log.info("gue http_%s", r.status_code)
        return
    for url in _extract_pdf_hrefs(r.text or "", r.url):
        _add_raw(items, seen, url, r.url, "gue.gov.ao")
    log.info("gue pdfs so far=%s", sum(1 for *_, m in items if m.get("portal") == "gue.gov.ao"))


def discover_governo(items, seen):
    max_pages = env_int("GOV_PAGES", 10)
    for cat in GOV_CATS:
        for page in range(1, max_pages + 1):
            url = f"https://governo.gov.ao/documentos/{cat}"
            if page > 1:
                url = f"{url}?page={page}"
            try:
                r = live_get(url, ua=UA, verify=False, timeout=(15, 40), retries=2)
            except Exception as exc:
                log.info("gov %s p%s fail: %s", cat, page, exc)
                break
            if getattr(r, "status_code", 0) != 200:
                break
            pdfs = _extract_pdf_hrefs(r.text or "", r.url)
            if not pdfs:
                break
            for p in pdfs:
                # Skip pure speeches/comms if they slipped into a law category
                fname = unquote(Path(urlsplit(p).path).name).lower()
                if any(x in fname for x in ("discurso", "comunicado")) and cat not in (
                    "legislacao",
                    "decreto-presidencial",
                    "constituicao",
                    "oge",
                    "despacho",
                    "publicacao",
                ):
                    continue
                if "discurso" in fname or "comunicado" in fname:
                    continue
                _add_raw(items, seen, p, r.url, f"governo.gov.ao/{cat}")
            pages = {int(x) for x in re.findall(r"[?&]page=(\d+)", r.text or "")}
            if pages and page >= max(pages):
                break
            if page > 1 and not pages:
                break
    log.info(
        "governo pdfs so far=%s",
        sum(1 for *_, m in items if str(m.get("portal", "")).startswith("governo")),
    )


def discover_minjusdh(items, seen):
    try:
        r = live_get(MINJUSDH_LEG, ua=UA, verify=False, timeout=(15, 40), retries=2)
    except Exception as exc:
        log.info("minjusdh fail: %s", exc)
        return
    for url in _extract_pdf_hrefs(r.text or "", getattr(r, "url", MINJUSDH_LEG)):
        _add_raw(items, seen, url, MINJUSDH_LEG, "minjusdh.gov.ao")


def discover_imprensa_live(items, seen):
    """Try live Imprensa Nacional listing pages for PDF links."""
    n0 = len(items)
    for seed in IMPRENSA_SEEDS:
        try:
            r = live_get(seed, ua=UA, verify=False, timeout=(8, 20), retries=1)
        except Exception as exc:
            log.info("imprensa seed fail %s: %s", seed, exc)
            continue
        if getattr(r, "status_code", 0) != 200:
            log.info("imprensa http_%s %s", r.status_code, seed)
            continue
        for url in _extract_pdf_hrefs(r.text or "", r.url):
            _add_raw(items, seen, url, r.url, "imprensanacional.gov.ao")
    log.info("imprensa live new=%s", len(items) - n0)


def _lawish_fname(fname: str, host: str) -> bool:
    """Prefer legislation-like digital PDFs; drop speeches/comms/forms."""
    fname = (fname or "").lower()
    if any(
        k in fname
        for k in (
            "discurso",
            "comunicado",
            "formulario",
            "formulário",
            "folheto",
            "entrevista",
            "apresentacao",
            "apresentação",
            "mensagem",
            "convite",
        )
    ):
        return False
    if "imprensanacional.gov.ao" in host:
        # Diário downloads are typically image-only scans — only when OCR is enabled
        return _env_flag("ALLOW_OCR", False) and not _env_flag("SKIP_OCR", True)
    if "plataformacipra" in host or "governo.gov.ao" in host:
        return any(
            k in fname
            for k in (
                "legisla",
                "decreto",
                "despacho",
                "constitui",
                "oge",
                "lei",
                "resolu",
                "publica",
                "regulament",
                "codigo",
                "código",
                "estatuto",
            )
        )
    if "c2a.portais.gov.ao" in host or "portais.gov.ao" in host:
        return any(
            k in fname
            for k in (
                "lei",
                "decreto",
                "despacho",
                "resolu",
                "legisl",
                "regulament",
                "codigo",
                "código",
                "constitu",
                "estatuto",
                "diari",
                "diploma",
                "portaria",
                "instruc",
            )
        )
    if "gue.gov.ao" in host:
        return "folheto" not in fname
    if "minfin.gov.ao" in host:
        return any(
            k in fname
            for k in (
                "lei",
                "decreto",
                "despacho",
                "orcament",
                "orçament",
                "regulament",
                "diploma",
                "aviso",
                "codigo",
                "código",
            )
        )
    return True


def discover_official_cdx(items, seen):
    """Wayback CDX of official hosts only — same URL families as live."""
    prefixes = [
        "gue.gov.ao/portal/public/assets/pdf/legislacao/",
        "gue.gov.ao/portal/public/assets/pdf/",
        "plataformacipra.gov.ao/public/ficheiros/arquivos/Gov_Angola",
        "plataformacipra.gov.ao/public/ficheiros/arquivos/",
        "c2a.portais.gov.ao/uploads/",
        "governo.gov.ao/fotos/frontend_1/gov_documentos/",
        "www.governo.gov.ao/fotos/frontend_1/gov_documentos/",
        "governo.gov.ao/Arquivos/",
        "www.governo.gov.ao/Arquivos/",
        "governo.gov.ao/fotos/",
        "minfin.gov.ao/cs/groups/public/",
        "www.minfin.gov.ao/cs/groups/public/",
        # Imprensa downloads intentionally omitted when SKIP_OCR (image-heavy scans)
    ]
    allow_ocr = _env_flag("ALLOW_OCR", False) and not _env_flag("SKIP_OCR", True)
    include_imp = env_int("INCLUDE_IMPRENSA_CDX", 1 if allow_ocr else 0)
    if include_imp:
        prefixes.extend(
            [
                "www.imprensanacional.gov.ao/downloads/",
                "imprensanacional.gov.ao/downloads/",
            ]
        )
    limit = env_int("CDX_LIMIT", 2000)
    # Map cleaned URL -> best CDX timestamp (for timestamped Wayback replay)
    ts_map: dict[str, str] = {}
    for prefix in prefixes:
        try:
            hits = cdx_urls(
                prefix,
                limit=limit,
                match_type="prefix",
                extra_filters=["mimetype:application/pdf"],
            )
        except Exception as exc:
            log.info("cdx fail %s: %s", prefix, exc)
            continue
        log.info("cdx %s hits=%s", prefix, len(hits or []))
        for h in hits:
            orig = (h.get("original") or "").strip()
            if not orig:
                continue
            # Strip session junk from Oracle UCM-style minfin URLs
            if ";jsessionid=" in orig.lower():
                i = orig.lower().find(";jsessionid=")
                # keep through .pdf only
                low = orig.lower()
                j = low.find(".pdf")
                if j > 0:
                    orig = orig[: j + 4]
                else:
                    orig = orig[:i]
            if orig.startswith("http://"):
                # Prefer https; fix bogus :80 in https schemes later via urlsplit
                orig_https = "https://" + orig[len("http://") :]
            else:
                orig_https = orig
            # Drop port 80 on https
            parts = urlsplit(orig_https)
            netloc = parts.netloc.replace(":80", "") if parts.scheme == "https" else parts.netloc
            orig_https = urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))
            if ".pdf" not in orig_https.lower():
                continue
            host = (urlsplit(orig_https).hostname or "").lower()
            portal = "wayback:" + (host or "official")
            fname = unquote(Path(urlsplit(orig_https).path).name)
            if not _lawish_fname(fname, host):
                continue
            ts = h.get("timestamp") or ""
            # Prefer status-200-looking later snapshots when colliding
            if ts and (orig_https not in ts_map or ts > ts_map[orig_https]):
                ts_map[orig_https] = ts
            before = len(seen)
            _add_raw(items, seen, orig_https, orig_https, portal)
            # Attach timestamp onto the just-added meta if new
            if len(seen) > before and items:
                items[-1][2]["wayback_ts"] = ts_map.get(orig_https) or ts
    # Backfill timestamps onto any earlier adds of the same URL
    url_to_meta = {it[1]: it[2] for it in items}
    for u, ts in ts_map.items():
        if u in url_to_meta and not url_to_meta[u].get("wayback_ts"):
            url_to_meta[u]["wayback_ts"] = ts


def discover():
    items, seen = [], set()
    discover_imprensa_live(items, seen)
    live_imprensa = len(items)
    discover_gue(items, seen)
    discover_governo(items, seen)
    discover_minjusdh(items, seen)
    # Always CDX for deepen (FORCE_CDX=1 default); expands beyond thin live portals.
    force_cdx = env_int("FORCE_CDX", 1)
    if force_cdx or live_imprensa < 5 or len(items) < env_int("MIN_CATALOG", 80):
        discover_official_cdx(items, seen)
    # Prefer live GUE/governo/minjus digital PDFs; then other official; Imprensa last (often scan).
    def rank(it):
        url = it[1]
        host = (urlsplit(url).hostname or "").lower()
        portal = str(it[2].get("portal") or "")
        if "imprensanacional.gov.ao" in host:
            return 5
        if "gue.gov.ao" in host and not portal.startswith("wayback"):
            return 0
        if "governo.gov.ao" in host or "plataformacipra.gov.ao" in host:
            return 1 if not portal.startswith("wayback") else 2
        if "c2a.portais.gov.ao" in host or "minjusdh.gov.ao" in host:
            return 2
        if portal.startswith("wayback"):
            return 3
        return 4
    items.sort(key=rank)
    log.info("catalog total=%s (imprensa_live=%s)", len(items), live_imprensa)
    return items


def _title_from_text(text: str, fallback: str) -> str:
    # Prefer lines with instrument keywords
    keys = (
        "lei n",
        "lei nº",
        "lei n.º",
        "decreto",
        "despacho",
        "resolução",
        "resolucao",
        "diário da república",
        "diario da republica",
        "constituição",
        "constituicao",
    )
    candidates = []
    for line in (text or "").splitlines():
        s = line.strip()
        if len(s) < 12:
            continue
        low = s.lower()
        if any(k in low for k in keys):
            return s[:240]
        if len(s) > 18:
            candidates.append(s)
        if len(candidates) >= 8:
            break
    return (candidates[0] if candidates else fallback)[:240]



def pdf_ocr_text(raw: bytes, *, max_pages: int = 40, dpi: int = 200) -> str:
    """OCR scanned / image-only official PDFs via pdftoppm + tesseract (por)."""
    import subprocess, tempfile
    if not raw or raw[:4] != b"%PDF":
        return ""
    max_pages = env_int("OCR_MAX_PAGES", max_pages)
    try:
        with tempfile.TemporaryDirectory() as d:
            pdf = Path(d) / "in.pdf"
            pdf.write_bytes(raw)
            # Limit pages for throughput
            cmd = [
                "pdftoppm", "-png", "-r", str(dpi),
                "-f", "1", "-l", str(max_pages),
                str(pdf), str(Path(d) / "p"),
            ]
            subprocess.run(cmd, check=False, capture_output=True, timeout=300)
            pages = sorted(Path(d).glob("p*.png"))
            chunks = []
            for page in pages:
                proc = subprocess.run(
                    ["tesseract", str(page), "stdout", "-l", "por", "--psm", "6"],
                    capture_output=True, timeout=180,
                )
                if proc.stdout:
                    chunks.append(proc.stdout.decode("utf-8", "replace"))
            return "\n".join(chunks).strip()
    except Exception as exc:
        log.info("ocr fail: %s", exc)
        return ""


def _env_flag(name: str, default: bool = False) -> bool:
    import os
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def fetch_ao(url: str, *, wayback_ts: str | None = None) -> dict:
    """Live first; CDX-timestamped Wayback of same official URL; OCR if ALLOW_OCR=1.

    Historic official PDFs often 404 on /web/2id_/ — prefer_pdf resolves a CDX
    timestamp (or uses wayback_ts from discovery). Image-only scans OCR only when
    ALLOW_OCR=1 and SKIP_OCR=0.
    """
    host = (urlsplit(url).hostname or "").lower()
    if "imprensanacional.gov.ao" in host:
        # Live Imprensa TLS usually fails from research egress — go straight to
        # timestamped Wayback (prefer_pdf), falling back to legacy helper.
        got = fetch_official_prefer_pdf(
            url, ua=UA, verify=False, min_text=150, wayback_ts=wayback_ts
        )
        if got.get("status") != "success":
            # Try HTTP original + explicit ts via legacy path
            got2 = _fetch_imprensa_wayback(url, wayback_ts=wayback_ts)
            if got2.get("status") == "success":
                got = got2
            elif isinstance(got2.get("content"), (bytes, bytearray)) and got2["content"][:4] == b"%PDF":
                got = got2
    else:
        got = fetch_official_prefer_pdf(
            url, ua=UA, verify=False, min_text=150, wayback_ts=wayback_ts
        )
    if got.get("status") == "success":
        return got
    # Default: do NOT OCR (SKIP_OCR=1 / ALLOW_OCR=0). Avoid thin-pilot quality path.
    allow_ocr = _env_flag("ALLOW_OCR", False) and not _env_flag("SKIP_OCR", True)
    if not allow_ocr:
        err = got.get("error") or "fetch_failed"
        if "pdf_extract_failed" in err or "short" in err:
            got["error"] = err + ";ocr_skipped"
        return got
    err = got.get("error") or ""
    body = got.get("content") if isinstance(got.get("content"), (bytes, bytearray)) else b""
    if not body or body[:4] != b"%PDF":
        try:
            r = live_get(url, ua=UA, verify=False, timeout=(15, 90), retries=2)
            body = r.content or b""
        except Exception:
            body = b""
        if not body or body[:4] != b"%PDF":
            try:
                import archive_fallbacks as af
                http_url = url.replace("https://", "http://") if url.startswith("https://") else url
                w = af.get_wayback_content(http_url, timestamp=wayback_ts)
                if w.get("status") != "success" and not wayback_ts:
                    # Last resort: CDX timestamp lookup already done inside prefer_pdf;
                    # try bare http replay once more without ts.
                    w = af.get_wayback_content(http_url)
                if w.get("status") == "success":
                    body = w.get("content") or b""
                    if isinstance(body, str):
                        body = body.encode("latin-1", "replace")
            except Exception:
                pass
    if body and body[:4] == b"%PDF":
        text = pdf_ocr_text(bytes(body))
        if len(text) >= 150:
            got.update(
                status="success", text=text, content=bytes(body),
                method=(got.get("method") or "wayback") + "+ocr",
                error="",
            )
            return got
        got["error"] = (err or "") + ";ocr_short_or_failed"
    return got

def _fetch_imprensa_wayback(url: str, wayback_ts: str | None = None) -> dict:
    """Wayback-only fetch for official Imprensa Nacional URLs when live TLS fails."""
    import archive_fallbacks as af
    from world_lib import pdf_to_text, html_to_text, MIN_TEXT, best_cdx_pdf_timestamp
    out = {
        "status": "error", "text": "", "content": b"", "source_url": url,
        "method": "", "content_type": "", "error": "imprensa_live_skipped",
    }
    http_url = url.replace("https://", "http://") if url.startswith("https://") else url
    ts = wayback_ts or best_cdx_pdf_timestamp(url) or best_cdx_pdf_timestamp(http_url)
    try:
        w = af.get_wayback_content(http_url, timestamp=ts)
        if w.get("status") != "success":
            w = af.get_wayback_content(url, timestamp=ts)
    except Exception as exc:
        out["error"] = f"wayback:{exc}"
        return out
    if w.get("status") != "success":
        out["error"] = f"wayback:{w.get('error')}"
        return out
    raw_b = w.get("content") or b""
    raw_t = w.get("text") or ""
    if (isinstance(raw_b, bytes) and raw_b[:4] == b"%PDF") or (raw_t[:4] == "%PDF"):
        pdf_bytes = raw_b if isinstance(raw_b, bytes) and raw_b[:4] == b"%PDF" else raw_t.encode("latin-1", "replace")
        text = pdf_to_text(pdf_bytes)
        if len(text) >= 150:
            out.update(status="success", text=text, content=pdf_bytes, method="wayback_pdf",
                       source_url=w.get("url") or url, content_type="application/pdf")
            return out
        out["error"] = "pdf_extract_failed"
        return out
    if not raw_t and isinstance(raw_b, bytes):
        raw_t = raw_b.decode("utf-8", "replace")
    text = html_to_text(raw_t) if "<" in (raw_t[:400] or "") else raw_t
    if len(text) >= 150:
        out.update(status="success", text=text, method="wayback_html",
                   source_url=w.get("url") or url, content_type="text/html")
    else:
        out["error"] = "wayback_short"
    return out



def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 300)
    max_seconds = env_int("MAX_SECONDS", 4500)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    portals: dict[str, int] = {}
    for ident, url, meta in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        # Live official URL first; CDX-timestamped Wayback; OCR if ALLOW_OCR=1.
        got = fetch_ao(url, wayback_ts=meta.get("wayback_ts"))
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(
                CC,
                {
                    "identifier": ident,
                    "source_url": url,
                    "reason": got.get("error"),
                    "portal": meta.get("portal"),
                },
            )
            continue
        title = (meta.get("title") or "").strip() or _title_from_text(text, ident)
        portal = meta.get("portal") or "unknown"
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title,
            text=text,
            source_url=url,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_ao.py",
            article_re=ART,
            extra_meta={"fetch_method": got.get("method"), "portal": portal},
        ):
            ok += 1
            done.add(rid)
            portals[portal] = portals.get(portal, 0) + 1
            log.info("ok %s portal=%s chars=%s", ident[:70], portal, len(text))
        else:
            fail += 1
    write_summary(
        CC,
        country=COUNTRY,
        source="Diário da República / Portal do Governo / GUE (Angola)",
        source_urls=[
            "https://www.imprensanacional.gov.ao/",
            "https://gue.gov.ao/portal/legislacao-portal",
            "https://governo.gov.ao/documentos/legislacao",
            "https://minjusdh.gov.ao/web/documentos?type=Legisla%C3%A7%C3%A3o",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete; Imprensa Nacional often unreachable — "
            "GUE + Portal do Governo official PDFs primary"
        ),
        notes=f"Official Angola legislation PDFs. portals={portals}. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s portals=%s", ok, skip, fail, portals)


if __name__ == "__main__":
    main()
