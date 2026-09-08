#!/usr/bin/env python3
"""Mozambique: Boletim da República / official legislation PDFs.

Primary live hosts (Imprensa Nacional Boletim is Ubercart paywalled; /download/N → 403):
  - MIREME (mireme.gov.mz) documentos/legislacao + regulamentos —
    official republications of BR / leis / decretos / diplomas
  - Assembleia da República (parlamento.mz) — Constituição, leis, BR PDFs
  - Banco de Moçambique (bancomoc.mz) — lei orgânica / normativos when PDF-linked
Live INM seeds first for any free PDFs; Wayback/CDX of the SAME official
.gov.mz / .mz URLs only when FORCE_CDX=1.
OCR (pdftoppm + tesseract por) for image-only official PDFs.
No commercial consolidators, no WAF bypass, no paywall bypass.
"""
from __future__ import annotations

import html
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit, quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "mz", "Mozambique", "pt"
SOURCE_TYPE = "boletim_republica_mz"
LICENSE = (
    "Boletim da República / Imprensa Nacional de Moçambique (inm.gov.mz) and "
    "official republications on mireme.gov.mz, parlamento.mz, bancomoc.mz. "
    "Authentic gazette text prevails. Not legal advice."
)
UA = (
    "legal-corpora-collector/1.0 "
    "(research; source=https://www.inm.gov.mz/)"
)
ART = re.compile(
    r"(?im)^\s*((?:Artigo|Art\.|ARTIGO)\s+\d+[ºªo°a-zA-Z]?)\b"
)
log = logging.getLogger("mz")

MIREME = "https://mireme.gov.mz"
PARLAMENTO = "https://www.parlamento.mz"
INM = "https://www.inm.gov.mz"
BANCO = "https://www.bancomoc.mz"

MIREME_INDEXES = (
    f"{MIREME}/documentos/legislacao/",
    f"{MIREME}/documentos/legislacao/page/2/",
    f"{MIREME}/documentos/legislacao/page/3/",
    f"{MIREME}/documentos/legislacao-diversa/",
    f"{MIREME}/documentos/legislacao-diversa/page/2/",
    f"{MIREME}/documentos/regulamentos/",
    f"{MIREME}/documentos/regulamentos/page/2/",
)
MIREME_AREAS = (
    "geologica-mineira",
    "combustiveis",
    "hidrocarbonetos",
    "energia-electrica",
    "energias-novas-e-renovaveis",
    "energia-atomica",
)
PARL_PAGES = (
    989,    # Constituição em vigor
    2940,   # Regimento
    2969,   # Constituição anterior
    2977,   # Lei Orgânica AR
    1009,   # Estatuto do Deputado
    15236,  # Projectos e Propostas de Lei
    12718,  # Projectos e Propostas de Resolução
    12967,  # PES / Orçamento
    12776,  # Programa Quinquenal
    4569,   # Conta Geral do Estado
    1018,   # Legislação / leis
    1020,   # Resoluções
    2941,   # Documentos legislativos
    12719,  # Outros projectos
    2937, 2942, 2943, 2944, 2945, 2950, 2955, 2960, 2965, 2980, 2990,
    1000, 1001, 1002, 1005, 1010, 1015, 1025, 1030,
    4500, 4510, 4520, 4550, 4560, 4570, 4580,
    12700, 12710, 12720, 12750, 12770, 12780, 12950, 12960, 12980,
    15200, 15210, 15220, 15230, 15240, 15250,
)
INM_SEEDS = (
    f"{INM}/",
    f"{INM}/pt-br/bulletin?field_tipo_de_produto_tid_br=43",  # I Série
    f"{INM}/pt-br/bulletin?field_tipo_de_produto_tid_br=44",
    f"{INM}/pt-br/bulletin?field_tipo_de_produto_tid_br=45",
)
BANCO_SEEDS = (
    f"{BANCO}/pt/o-banco/normativos/",
    f"{BANCO}/pt/o-banco/sobre-o-banco/missao-funcoes-e-lei-organica/",
)

ALLOWED_HOST_SUFFIXES = (
    "inm.gov.mz",
    "mireme.gov.mz",
    "parlamento.mz",
    "bancomoc.mz",
    "gov.mz",
    "presidencia.gov.mz",
    "portaldogoverno.gov.mz",
)

SKIP_NAME = (
    "discurso",
    "comunicado",
    "logotipo",
    "logo",
    "banner",
    "infografic",
    "foto",
    "parecer",
    "auscultacao",
    "termos-de-referencia",
    "fundamentacao",
)


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES)


def _norm_pdf_url(raw: str, base: str) -> str | None:
    if not raw:
        return None
    raw = html.unescape(raw.strip().split()[0])
    low = raw.lower()
    # Prefer full URL when it already ends with .pdf (handles "...pdf-ARENE-1.pdf")
    if low.endswith(".pdf"):
        cut = raw
    else:
        i = low.find(".pdf")
        if i < 0:
            return None
        cut = raw[: i + 4]
    full = urljoin(base, cut)
    parts = urlsplit(full)
    path = quote(unquote(parts.path), safe="/%")
    full = urlunsplit((parts.scheme or "https", parts.netloc, path, parts.query, ""))
    if not _host_ok(full):
        return None
    if not full.lower().endswith(".pdf"):
        return None
    return full


def _ident_from_url(url: str) -> str:
    name = unquote(Path(urlsplit(url).path).name)
    name = re.sub(r"\.pdf$", "", name, flags=re.I)
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"[^\w\-.\u00C0-\u024F]+", "-", name, flags=re.UNICODE)
    ident = name.strip("-")[:160]
    return ident or re.sub(r"\W+", "-", url)[-80:]


def _skip_name(url: str) -> bool:
    fname = unquote(Path(urlsplit(url).path).name).lower()
    return any(k in fname for k in SKIP_NAME)


def _add_raw(items, seen, href: str, base: str, portal: str, title: str | None = None):
    url = _norm_pdf_url(href, base)
    if not url or url in seen:
        return
    if _skip_name(url):
        return
    seen.add(url)
    items.append((_ident_from_url(url), url, {"portal": portal, "title": title}))


def _extract_pdf_hrefs(html_text: str, base: str) -> list[str]:
    out = []
    for m in re.finditer(r'href=["\']([^"\']+)["\']', html_text or "", re.I):
        u = _norm_pdf_url(m.group(1), base)
        if u:
            out.append(u)
    for m in re.finditer(
        r'https?://(?:mireme\.gov\.mz|www\.parlamento\.mz|parlamento\.mz|'
        r'www\.inm\.gov\.mz|inm\.gov\.mz|www\.bancomoc\.mz|bancomoc\.mz)'
        r'[^"\'\s<>]*?\.pdf',
        html_text or "",
        re.I,
    ):
        u = _norm_pdf_url(m.group(0), base)
        if u:
            out.append(u)
    return list(dict.fromkeys(out))


def discover_mireme(items, seen):
    seeds = list(MIREME_INDEXES)
    for area in MIREME_AREAS:
        seeds.append(f"{MIREME}/documento?tipo=legislacao&area={area}")
        seeds.append(f"{MIREME}/documento?tipo=regulamentos&area={area}")
    n0 = len(items)
    for seed in seeds:
        try:
            r = live_get(seed, ua=UA, verify=False, timeout=(12, 35), retries=1)
        except Exception as exc:
            log.info("mireme fail %s: %s", seed[:80], exc)
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        for url in _extract_pdf_hrefs(r.text or "", r.url):
            _add_raw(items, seen, url, r.url, "mireme.gov.mz")
        log.info(
            "mireme seed ok %s pdfs_total=%s",
            seed.split("mireme.gov.mz")[-1][:60],
            len(items) - n0,
        )
    log.info(
        "mireme pdfs so far=%s (new=%s)",
        sum(1 for *_, m in items if m.get("portal") == "mireme.gov.mz"),
        len(items) - n0,
    )


def discover_parlamento(items, seen):
    n0 = len(items)
    for pid in PARL_PAGES:
        url = f"{PARLAMENTO}/?page_id={pid}"
        try:
            r = live_get(url, ua=UA, verify=False, timeout=(12, 35), retries=1)
        except Exception as exc:
            log.info("parlamento fail %s: %s", pid, exc)
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        for pdf in _extract_pdf_hrefs(r.text or "", r.url):
            fname = unquote(Path(urlsplit(pdf).path).name).lower()
            keep = any(
                k in fname
                for k in (
                    "lei",
                    "decreto",
                    "resolu",
                    "diploma",
                    "br_",
                    "boletim",
                    "constitui",
                    "regimento",
                    "estatuto",
                    "organica",
                    "legislacao",
                    "orcamento",
                    "pes",
                    "pesoe",
                    "programa",
                    "pqg",
                    "conta",
                    "proposta",
                )
            )
            if not keep and "proposta" not in fname:
                if not re.search(r"\d{4}", fname) and "/uploads/" not in pdf.lower():
                    continue
            _add_raw(items, seen, pdf, r.url, "parlamento.mz")
        # One-hop: follow same-site page_id links for more legislative PDFs
        for m in re.finditer(r'href=["\']([^"\']*page_id=\d[^"\']*)["\']', r.text or "", re.I):
            child = urljoin(r.url, html.unescape(m.group(1)))
            host = (urlsplit(child).hostname or "").lower()
            if "parlamento.mz" not in host:
                continue
            key = "parlpage:" + child.split("#")[0]
            if key in seen:
                continue
            seen.add(key)
            try:
                r2 = live_get(child, ua=UA, verify=False, timeout=(10, 25), retries=1)
            except Exception:
                continue
            if getattr(r2, "status_code", 0) != 200:
                continue
            for pdf in _extract_pdf_hrefs(r2.text or "", r2.url):
                _add_raw(items, seen, pdf, r2.url, "parlamento.mz")
    try:
        r = live_get(PARLAMENTO + "/", ua=UA, verify=False, timeout=(12, 35), retries=1)
        if getattr(r, "status_code", 0) == 200:
            for pdf in _extract_pdf_hrefs(r.text or "", r.url):
                _add_raw(items, seen, pdf, r.url, "parlamento.mz")
    except Exception as exc:
        log.info("parlamento home fail: %s", exc)
    # Media library / document listing fallbacks
    for seed in (
        f"{PARLAMENTO}/?s=lei+filetype%3Apdf",
        f"{PARLAMENTO}/?s=boletim",
        f"{PARLAMENTO}/?s=constitui%C3%A7%C3%A3o",
    ):
        try:
            r = live_get(seed, ua=UA, verify=False, timeout=(10, 25), retries=1)
        except Exception:
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        for pdf in _extract_pdf_hrefs(r.text or "", r.url):
            _add_raw(items, seen, pdf, r.url, "parlamento.mz")
    log.info("parlamento pdfs new=%s", len(items) - n0)


def discover_inm_live(items, seen):
    """Any free PDF links on INM (most Boletim content is paid Ubercart; /download/N → 403)."""
    n0 = len(items)
    for seed in INM_SEEDS:
        try:
            r = live_get(seed, ua=UA, verify=False, timeout=(10, 25), retries=1)
        except Exception as exc:
            log.info("inm seed fail %s: %s", seed[:60], exc)
            continue
        if getattr(r, "status_code", 0) != 200:
            log.info("inm http_%s %s", r.status_code, seed[:60])
            continue
        for url in _extract_pdf_hrefs(r.text or "", r.url):
            _add_raw(items, seen, url, r.url, "inm.gov.mz")
    log.info("inm live new=%s (paywalled downloads skipped)", len(items) - n0)


def discover_bancomoc(items, seen):
    n0 = len(items)
    for seed in BANCO_SEEDS:
        try:
            r = live_get(seed, ua=UA, verify=False, timeout=(12, 30), retries=1)
        except Exception as exc:
            log.info("bancomoc fail %s: %s", seed[:60], exc)
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        for url in _extract_pdf_hrefs(r.text or "", r.url):
            _add_raw(items, seen, url, r.url, "bancomoc.mz")
        for m in re.finditer(r'href=["\']([^"\']+)["\']', r.text or "", re.I):
            href = html.unescape(m.group(1))
            full = urljoin(r.url, href)
            host = (urlsplit(full).hostname or "").lower()
            if "bancomoc.mz" not in host:
                continue
            path = (urlsplit(full).path or "").lower()
            if not any(k in path for k in ("normativ", "lei-organica", "aviso", "instruc", "circul")):
                continue
            key = "page:" + full
            if key in seen:
                continue
            seen.add(key)
            try:
                r2 = live_get(full, ua=UA, verify=False, timeout=(10, 25), retries=1)
            except Exception:
                continue
            if getattr(r2, "status_code", 0) != 200:
                continue
            for url in _extract_pdf_hrefs(r2.text or "", r2.url):
                _add_raw(items, seen, url, r2.url, "bancomoc.mz")
    log.info("bancomoc new=%s", len(items) - n0)


def discover_official_cdx(items, seen):
    """Wayback CDX of official hosts only — same URL families as live."""
    prefixes = [
        "mireme.gov.mz/wp-content/uploads/",
        "www.mireme.gov.mz/wp-content/uploads/",
        "www.parlamento.mz/wp-content/uploads/",
        "parlamento.mz/wp-content/uploads/",
        "www.inm.gov.mz/sites/default/files/",
        "inm.gov.mz/sites/default/files/",
    ]
    limit = env_int("CDX_LIMIT", 200)
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
        for h in hits:
            orig = (h.get("original") or "").strip()
            if not orig or ".pdf" not in orig.lower():
                continue
            if orig.startswith("http://"):
                orig_https = "https://" + orig[len("http://") :]
            else:
                orig_https = orig
            if not _host_ok(orig_https):
                continue
            portal = "wayback:" + (urlsplit(orig_https).hostname or "official")
            _add_raw(items, seen, orig_https, orig_https, portal)


def discover():
    items, seen = [], set()
    # Parlamento first (beyond MIREME foothold), then free INM, bancomoc, mireme
    discover_parlamento(items, seen)
    discover_inm_live(items, seen)
    live_inm = sum(1 for *_, m in items if (m or {}).get("portal") == "inm.gov.mz")
    discover_bancomoc(items, seen)
    discover_mireme(items, seen)
    # CDX of official hosts when asked, or when catalog still thin beyond mireme
    n_parl = sum(1 for *_, m in items if "parlamento" in ((m or {}).get("portal") or ""))
    if os.environ.get("FORCE_CDX") == "1" or n_parl < env_int("MIN_PARL", 15):
        discover_official_cdx(items, seen)

    def rank(it):
        url = it[1]
        host = (urlsplit(url).hostname or "").lower()
        portal = (it[2] or {}).get("portal") or ""
        # Prefer parlamento.mz + non-paywalled BR/INM free PDFs over MIREME foothold
        if portal.startswith("wayback"):
            return 3
        if "parlamento.mz" in host:
            return 0
        if "inm.gov.mz" in host:
            return 1
        if "bancomoc.mz" in host:
            return 2
        return 3  # mireme after parlamento / free INM / bancomoc

    items.sort(key=rank)
    log.info("catalog total=%s (inm_live=%s)", len(items), live_inm)
    return items


def pdf_ocr_text(raw: bytes, *, max_pages: int = 25, dpi: int = 180) -> str:
    """OCR scanned / image-only official PDFs via pdftoppm + tesseract (por)."""
    if not raw or raw[:4] != b"%PDF":
        return ""
    max_pages = env_int("OCR_MAX_PAGES", max_pages)
    try:
        with tempfile.TemporaryDirectory() as d:
            pdf = Path(d) / "in.pdf"
            pdf.write_bytes(raw)
            subprocess.run(
                [
                    "pdftoppm",
                    "-png",
                    "-r",
                    str(dpi),
                    "-f",
                    "1",
                    "-l",
                    str(max_pages),
                    str(pdf),
                    str(Path(d) / "p"),
                ],
                check=False,
                capture_output=True,
                timeout=300,
            )
            pages = sorted(Path(d).glob("p*.png"))
            chunks = []
            for page in pages:
                proc = subprocess.run(
                    ["tesseract", str(page), "stdout", "-l", "por", "--psm", "6"],
                    capture_output=True,
                    timeout=90,
                )
                if proc.stdout:
                    chunks.append(proc.stdout.decode("utf-8", "replace"))
            return "\n".join(chunks).strip()
    except Exception as exc:
        log.info("ocr fail: %s", exc)
        return ""


def _watermark_only(text: str) -> bool:
    if not text:
        return True
    low = text.lower()
    if "pandora box" in low or "scanned by camscanner" in low:
        # real body usually much longer than footer-only extracts
        if len(text) < 4000:
            return True
    # mostly form-feed / repeated short footer lines
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines and len(text) < 3000 and all(len(ln) < 120 for ln in lines[:12]):
        if any("pandora" in ln.lower() or "camscanner" in ln.lower() or "edi" in ln.lower()[:8] for ln in lines[:8]):
            return True
    return False


def fetch_mz(url: str) -> dict:
    """Live (+Wayback) then OCR for image-only official PDFs."""
    got = fetch_official(url, ua=UA, verify=False, min_text=150, wayback=os.environ.get("FORCE_WAYBACK","0")=="1")
    force_ocr = os.environ.get("OCR", "0") == "1" and _watermark_only(got.get("text") or "")
    if got.get("status") == "success" and not force_ocr:
        return got
    if os.environ.get("OCR", "0") != "1":
        return got
    if force_ocr and got.get("status") == "success":
        # keep PDF bytes for OCR when extract was footer-only
        got["error"] = (got.get("error") or "") + ";watermark_only_force_ocr"
    def _as_pdf(blob):
        if not blob:
            return b""
        if isinstance(blob, str):
            blob = blob.encode("latin-1", "replace")
        else:
            blob = bytes(blob)
        if blob[:4] == b"%PDF":
            return blob
        idx = blob.find(b"%PDF", 0, 8192)
        return blob[idx:] if idx >= 0 else b""

    err = got.get("error") or ""
    body = _as_pdf(got.get("content") if isinstance(got.get("content"), (bytes, bytearray, str)) else b"")
    if not body:
        try:
            r = live_get(url, ua=UA, verify=False, timeout=(15, 90), retries=2)
            body = _as_pdf(r.content or b"")
        except Exception:
            body = b""
        if not body:
            try:
                import archive_fallbacks as af

                w = af.get_wayback_content(url)
                if w.get("status") == "success":
                    body = _as_pdf(w.get("content") or b"")
            except Exception:
                pass
    if body and body[:4] == b"%PDF":
        text = pdf_ocr_text(bytes(body))
        if len(text) >= 150:
            got.update(
                status="success",
                text=text,
                content=bytes(body),
                method=(got.get("method") or "http") + "+ocr",
                error="",
            )
            return got
        got["error"] = (err or "") + ";ocr_short_or_failed"
    return got


def _title_from_text(text: str, fallback: str) -> str:
    keys = (
        "lei n",
        "lei nº",
        "lei n.º",
        "decreto",
        "diploma",
        "resolução",
        "resolucao",
        "boletim da república",
        "boletim da republica",
        "constituição",
        "constituicao",
        "aviso",
        "regulamento",
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


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = ocr_used = 0
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
        got = fetch_mz(url)
        text = got.get("text") or ""
        method = got.get("method") or ""
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
        if "+ocr" in method:
            ocr_used += 1
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
            collector="collect_mz.py",
            article_re=ART,
            extra_meta={"fetch_method": method, "portal": portal},
        ):
            ok += 1
            done.add(rid)
            portals[portal] = portals.get(portal, 0) + 1
            log.info("ok %s portal=%s chars=%s method=%s", ident[:70], portal, len(text), method)
        else:
            fail += 1
    write_summary(
        CC,
        country=COUNTRY,
        source="Boletim da República / MIREME / Parlamento (Moçambique)",
        source_urls=[
            "https://www.inm.gov.mz/",
            "https://mireme.gov.mz/documentos/legislacao/",
            "https://www.parlamento.mz/",
            "https://www.bancomoc.mz/pt/o-banco/normativos/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete; INM Boletim Ubercart-paywalled — "
            "MIREME + Parlamento official PDFs primary; OCR for scans"
        ),
        notes=(
            f"Official Mozambique legislation PDFs. portals={portals} "
            f"ocr_used={ocr_used}. Not legal advice."
        ),
        last_run=t0,
    )
    log.info(
        "done ok=%s skip=%s fail=%s ocr=%s portals=%s",
        ok,
        skip,
        fail,
        ocr_used,
        portals,
    )


if __name__ == "__main__":
    main()
