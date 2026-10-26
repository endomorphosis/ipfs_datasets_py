#!/usr/bin/env python3
"""Senegal (sn): official laws from Archives publiques + Primature + Conseil constitutionnel + JO.

Official only:
  - https://www.sec.gouv.sn/ / https://primature.sn/ (shared Drupal; codes/lois PDFs)
  - https://www.archives.sn/  (Archives publiques du Sénégal — API documents type=law/code/official_journal)
  - https://primature.sn/     (lois/décrets/codes HTML + /sites/default/files PDFs; live + CDX)
  - https://conseilconstitutionnel.sn/  (Constitution + loi organique)
  - https://www.jo.gouv.sn/   (Journal Officiel — live often down; Wayback/CDX of official URLs)
  - http://www.assemblee-nationale.sn/  (HTTP; limited live catalog)

Filter: JO fascicules kept; other hosts require loi/ordonnance/décret/constitution/code/règlement.
Not AfricanLII / Droit-Afrique. No WAF bypass. Not legal advice.
"""
from __future__ import annotations

import html as html_lib
import json
import logging
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse, quote, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import (
    cdx_urls,
    env_int,
    fetch_official,
    live_get,
    pdf_to_text,
    save_instrument,
    setup_log,
    slug_id,
)

CC, COUNTRY, LANG = "sn", "Senegal", "fr"
SOURCE_TYPE = "jo_senegal_official"
LICENSE = (
    "République du Sénégal — Archives publiques (archives.sn) / Primature (primature.sn) / "
    "Conseil constitutionnel (conseilconstitutionnel.sn) / Journal Officiel (jo.gouv.sn). "
    "Authentic Journal Officiel / official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.archives.sn/; Senegal=sn)"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+\d+[a-zA-Zº°]?)\b")
log = logging.getLogger("sn")

ARCHIVES = "https://www.archives.sn"
ARCHIVES_API = f"{ARCHIVES}/api/documents"
ARCHIVES_FICHIER = f"{ARCHIVES}/api/fichiers/{{fid}}"
PRIMATURE = "https://primature.sn"
CCONST = "https://conseilconstitutionnel.sn"
JO = "https://www.jo.gouv.sn"
AN = "http://www.assemblee-nationale.sn"

ALLOWED_HOST_SUFFIXES = (
    "archives.sn",
    "primature.sn",
    "conseilconstitutionnel.sn",
    "jo.gouv.sn",
    "assemblee-nationale.sn",
    "assemblee.sn",
    "justice.gouv.sn",
    "finances.gouv.sn",
    "economie.gouv.sn",
    "budget.gouv.sn",
    "numerique.gouv.sn",
    "presidence.sn",
    "gouv.sn",
    "sec.gouv.sn",
)

KEEP_RE = re.compile(
    r"(loi|ordonnance|ordonn|d[eé]cret|decret|arr[eê]t[eé]|arrete|constitution|code|"
    r"journal.?officiel|\bjo\b|organique|r[eè]glement|charte|statut|"
    r"texte.?juridique|texte.?fondament)",
    re.I,
)
DROP_RE = re.compile(
    r"(discours|allocution|communique|photo|banner|logo|cv[-_]|biographie|"
    r"rapport[-_ ]annuel|presentation|organigramme|recrutement|"
    r"d[eé]claration.?de.?politique|politique.?g[eé]n[eé]rale|"
    r"code.?de.?conduite|charte.?d.?[eé]thique|ethique.?et.?de.?conduite|"
    r"miferso|somisen|deputePdf|favicon|\.png|\.jpg|\.css)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(loi|ordonnance|d[eé]cret|decret|constitution|journal\s+officiel|"
    r"code|r[eè]glement|assembl[eé]e|r[eé]publique\s+du\s+s[eé]n[eé]gal|"
    r"conseil\s+constitutionnel|pr[eé]sident\s+de\s+la\s+r[eé]publique)\b",
    re.I,
)

MAX_PDF_BYTES = 28 * 1024 * 1024

CC_PAGES = [
    f"{CCONST}/la-constitution/",
    f"{CCONST}/la-loi-organique/",
    f"{CCONST}/service/la-loi-organique-n2016-23-du-14-juillet-2016-relative-au-conseil-constitutionnel/",
]

PRIMATURE_LISTINGS = [
    f"{PRIMATURE}/publications/lois-et-reglements/lois-et-decrets",
    f"{PRIMATURE}/publications/lois-et-reglements/codes",
    f"{PRIMATURE}/publications/lois-et-reglements",
]


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES)


def _norm_url(url: str) -> str:
    if not url:
        return ""
    url = html_lib.unescape(url.strip())
    url = url.replace(":80/", "/").replace(":80?", "?")
    if url.startswith("http://www.primature.sn/"):
        url = "https://primature.sn/" + url[len("http://www.primature.sn/") :]
    if url.startswith("https://www.primature.sn/"):
        url = "https://primature.sn/" + url[len("https://www.primature.sn/") :]
    if url.startswith("http://") and "assemblee-nationale.sn" not in url:
        # Prefer https except for AN which only speaks HTTP cleanly from this host
        url = "https://" + url[len("http://") :]
    try:
        p = urlsplit(url)
        parts = []
        for seg in p.path.split("/"):
            if not seg:
                parts.append(seg)
                continue
            parts.append(seg if "%" in seg else quote(seg, safe="._-()[]',°"))
        url = urlunsplit((p.scheme or "https", p.netloc, "/".join(parts), p.query, ""))
    except Exception:
        url = url.replace(" ", "%20")
    return url


def _wayback_orig(url: str) -> str:
    u = html_lib.unescape((url or "").strip())
    u = u.replace(":80/", "/").replace(":80?", "?")
    if u.startswith("https://"):
        u = "http://" + u[len("https://") :]
    return u


def _ident_from_url(url: str) -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name
    stem = Path(name).stem
    return re.sub(r"\W+", "-", stem).strip("-").lower()[:160] or re.sub(r"\W+", "-", url)[-80:]


def _title_from_url(url: str) -> str:
    name = unquote(Path(urlparse(url).path).name)
    stem = Path(name).stem
    return stem.replace("_", " ").replace("-", " ")[:240] or stem


def _is_jo(url: str, title: str | None = None, portal: str | None = None) -> bool:
    if portal and "official_journal" in portal:
        return True
    blob = unquote(urlparse(url).path) + " " + (title or "") + " " + (portal or "")
    return bool(re.search(r"(?i)(journal.?officiel|\bjo\b|official_journal)", blob))


def _keep_name(url: str, title: str | None = None, portal: str | None = None) -> bool:
    if _is_jo(url, title, portal):
        return True
    if portal and portal.startswith("archives_") and portal.endswith("_law"):
        return True
    blob = unquote(urlparse(url).path) + " " + (title or "") + " " + url
    if DROP_RE.search(blob):
        return False
    if ".pdf" not in url.lower() and "/api/fichiers/" not in url.lower() and "html" not in (portal or ""):
        # HTML pages still need keep keywords in path/title
        pass
    return bool(KEEP_RE.search(blob))


def _add(items, seen, ident, url, meta=None):
    url = _norm_url(url)
    if not url or not _host_ok(url):
        return
    key = url.lower().split("?")[0]
    if key in seen:
        return
    title = (meta or {}).get("title")
    portal = (meta or {}).get("portal")
    if not _keep_name(url, title, portal):
        return
    seen.add(key)
    ident = re.sub(r"\W+", "-", (ident or _ident_from_url(url)).strip("-")).lower()[:160]
    items.append((ident, url, meta or {}))


def text_ok(text: str, url: str, title: str | None = None, portal: str | None = None) -> bool:
    if _is_jo(url, title, portal):
        return True
    blob = (text or "")[:8000] + " " + (title or "") + " " + url
    if DROP_RE.search(title or ""):
        return False
    return bool(TEXT_KEEP_RE.search(blob))


def _date_from(ident: str, title: str, text: str, publish_date: str | None = None) -> str | None:
    if publish_date and re.match(r"^\d{4}-\d{2}-\d{2}", publish_date):
        return publish_date[:10]
    blob = f"{ident} {title} {(text or '')[:2000]}"
    m = re.search(
        r"(?i)(\d{1,2})\s+(janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[eé]cembre)\s+(\d{4})",
        blob,
    )
    if m:
        months = {
            "janvier": "01", "fevrier": "02", "février": "02", "mars": "03", "avril": "04",
            "mai": "05", "juin": "06", "juillet": "07", "aout": "08", "août": "08",
            "septembre": "09", "octobre": "10", "novembre": "11", "decembre": "12", "décembre": "12",
        }
        mon = months.get(m.group(2).lower().replace("é", "e").replace("û", "u"))
        if mon:
            return f"{m.group(3)}-{mon}-{int(m.group(1)):02d}"
    m = re.search(r"(20\d{2}|19\d{2})[-_/](\d{2})[-_/](\d{2})", blob)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"\b(20\d{2}|19\d{2})\b", blob)
    return m.group(1) if m else None


def discover_constitution(items, seen):
    for url in CC_PAGES:
        slug = url.rstrip("/").split("/")[-1] or "constitution"
        _add(
            items,
            seen,
            f"cc-{slug}",
            url,
            {"portal": "conseilconstitutionnel_html", "title": slug.replace("-", " "), "kind": "html"},
        )


def discover_archives_type(items, seen, doc_type: str, *, max_pages: int, page_limit: int, portal: str):
    for page in range(1, max_pages + 1):
        url = f"{ARCHIVES_API}?type={doc_type}&limit={page_limit}&page={page}"
        try:
            r = live_get(url, ua=UA, verify=True, timeout=(15, 40), retries=2)
        except Exception as exc:
            log.info("archives api fail type=%s page=%s: %s", doc_type, page, exc)
            break
        if getattr(r, "status_code", 0) != 200:
            log.info("archives api http_%s type=%s page=%s", r.status_code, doc_type, page)
            break
        try:
            data = r.json()
        except Exception:
            try:
                data = json.loads(r.text or "")
            except Exception as exc:
                log.info("archives json fail type=%s: %s", doc_type, exc)
                break
        docs = data.get("documents") or []
        if not docs:
            break
        for doc in docs:
            if (doc.get("type") or "") != doc_type:
                continue
            f = doc.get("file") or {}
            fid = f.get("id")
            if not fid:
                continue
            try:
                fsize = int(f.get("filesize") or 0)
            except Exception:
                fsize = 0
            if fsize and fsize > MAX_PDF_BYTES:
                continue
            title = (doc.get("title") or "").strip()
            slug = (doc.get("slug") or f"{doc_type}-{doc.get('id')}")[:140]
            if DROP_RE.search(title) or DROP_RE.search(slug):
                continue
            if doc_type != "official_journal" and not KEEP_RE.search(title + " " + slug):
                continue
            pdf_url = ARCHIVES_FICHIER.format(fid=fid)
            page_url = f"{ARCHIVES}/docs/{doc_type}/{slug}" if doc_type != "official_journal" else f"{ARCHIVES}/docs/journal-officiel/{slug}"
            # official_journal path uses journal-officiel
            if doc_type == "official_journal":
                page_url = f"{ARCHIVES}/docs/journal-officiel/{slug}"
            elif doc_type == "law":
                page_url = f"{ARCHIVES}/docs/loi/{slug}"
            elif doc_type == "code":
                page_url = f"{ARCHIVES}/docs/code/{slug}"
            _add(
                items,
                seen,
                f"arch-{doc_type}-{slug}",
                pdf_url,
                {
                    "portal": portal,
                    "title": title,
                    "publish_date": doc.get("publish_date"),
                    "filename": f.get("filename_download"),
                    "page_url": page_url,
                    "filesize": fsize,
                    "kind": "pdf",
                },
            )
        total_pages = (data.get("pagination") or {}).get("totalPages") or page
        if page >= int(total_pages):
            break


def discover_primature_pdf_cdx(items, seen):
    for prefix in (
        "primature.sn/sites/default/files/",
        "www.primature.sn/sites/default/files/",
    ):
        try:
            hits = cdx_urls(
                prefix,
                limit=env_int("CDX_LIMIT", 200),
                match_type="prefix",
                extra_filters=["mimetype:application/pdf"],
            )
        except Exception as exc:
            log.info("cdx fail %s: %s", prefix, exc)
            continue
        for h in hits:
            orig = h.get("original") or ""
            if ".pdf" not in orig.lower():
                continue
            if DROP_RE.search(unquote(orig)):
                continue
            if not KEEP_RE.search(unquote(orig)):
                continue
            _add(
                items,
                seen,
                "prim-" + _ident_from_url(orig),
                orig,
                {
                    "portal": "primature_pdf",
                    "title": _title_from_url(orig),
                    "wayback_ts": h.get("timestamp"),
                    "kind": "pdf",
                },
            )


def discover_primature_nodes(items, seen):
    """Listing pages → decree/code HTML nodes; also harvest PDF attachments on those pages."""
    node_urls = []
    for base in PRIMATURE_LISTINGS:
        for page in range(0, env_int("PRIMATURE_PAGES", 8)):
            url = f"{base}?page={page}"
            try:
                r = live_get(url, ua=UA, verify=True, timeout=(15, 40), retries=2)
            except Exception as exc:
                log.info("primature list fail %s: %s", url, exc)
                break
            if getattr(r, "status_code", 0) != 200:
                break
            hrefs = re.findall(r'href=["\']([^"\']+)["\']', r.text or "")
            found = 0
            for href in hrefs:
                full = urljoin(url, href)
                path = urlparse(full).path
                if not path.startswith("/publications/lois-et-reglements/"):
                    continue
                if path.rstrip("/") in (
                    "/publications/lois-et-reglements",
                    "/publications/lois-et-reglements/lois-et-decrets",
                    "/publications/lois-et-reglements/codes",
                ):
                    continue
                if ".pdf" in path.lower():
                    continue
                node_urls.append(full)
                found += 1
            if found == 0 and page > 0:
                break

    # Dedup preserve order
    seen_nodes = set()
    for node in node_urls:
        key = node.lower().rstrip("/")
        if key in seen_nodes:
            continue
        seen_nodes.add(key)
        try:
            r = live_get(node, ua=UA, verify=True, timeout=(15, 40), retries=2)
        except Exception as exc:
            log.info("primature node fail %s: %s", node, exc)
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        html = r.text or ""
        # PDF attachments on node
        for href in re.findall(r'href=["\']([^"\']+)["\']', html):
            full = urljoin(node, href)
            if ".pdf" in full.lower() and "/sites/default/files/" in full.lower():
                _add(
                    items,
                    seen,
                    "prim-" + _ident_from_url(full),
                    full,
                    {
                        "portal": "primature_pdf",
                        "title": _title_from_url(full),
                        "page_url": node,
                        "kind": "pdf",
                    },
                )
        # HTML body decree/code page
        slug = urlparse(node).path.rstrip("/").split("/")[-1]
        title = slug.replace("-", " ")
        m = re.search(r"<title>([^<]+)</title>", html, re.I)
        if m:
            title = html_lib.unescape(m.group(1).split("|")[0]).strip()[:240]
        _add(
            items,
            seen,
            "prim-html-" + slug,
            node,
            {"portal": "primature_html", "title": title, "kind": "html"},
        )


def discover_jo_live(items, seen):
    for seed in (JO + "/", "http://www.jo.gouv.sn/", "http://jo.gouv.sn/"):
        try:
            r = live_get(seed, ua=UA, verify=False, timeout=(8, 20), retries=1)
        except Exception as exc:
            log.info("jo live fail %s: %s", seed, exc)
            continue
        for href in re.findall(r'href=["\']([^"\']+)["\']', r.text or ""):
            url = urljoin(seed, href)
            if ".pdf" in url.lower():
                _add(
                    items,
                    seen,
                    "jo-" + _ident_from_url(url),
                    url,
                    {"portal": "jo_gouv_live", "title": _title_from_url(url), "kind": "pdf"},
                )


def discover_jo_cdx(items, seen):
    for prefix in ("www.jo.gouv.sn/", "jo.gouv.sn/"):
        try:
            hits = cdx_urls(prefix, limit=env_int("CDX_JO_LIMIT", 80), match_type="prefix")
        except Exception as exc:
            log.info("jo cdx fail %s: %s", prefix, exc)
            continue
        for h in hits:
            orig = h.get("original") or ""
            if not orig:
                continue
            if ".pdf" in orig.lower() or "article.php" in orig.lower():
                # Prefer PDFs; skip bare index shells
                if orig.rstrip("/").endswith("jo.gouv.sn") or orig.endswith("article.php3?"):
                    continue
                _add(
                    items,
                    seen,
                    "jo-" + _ident_from_url(orig),
                    orig,
                    {
                        "portal": "jo_gouv_wayback",
                        "title": _title_from_url(orig),
                        "wayback_ts": h.get("timestamp"),
                        "kind": "pdf" if ".pdf" in orig.lower() else "html",
                    },
                )


CDX_PREFIXES = [
    ("sec.gouv.sn/sites/default/files/", "sec.gouv.sn_cdx"),
    ("www.sec.gouv.sn/sites/default/files/", "sec.gouv.sn_cdx"),
    ("sec.gouv.sn/IMG/pdf/", "sec.gouv.sn_cdx"),
    ("www.sec.gouv.sn/IMG/pdf/", "sec.gouv.sn_cdx"),
    ("primature.sn/sites/default/files/", "primature_pdf"),
    ("www.primature.sn/sites/default/files/", "primature_pdf"),
    ("justice.gouv.sn/droitp/", "justice.gouv.sn_cdx"),
    ("www.justice.gouv.sn/droitp/", "justice.gouv.sn_cdx"),
    ("justice.gouv.sn/sites/default/files/", "justice.gouv.sn_cdx"),
    ("www.justice.gouv.sn/sites/default/files/", "justice.gouv.sn_cdx"),
    ("finances.gouv.sn/app/uploads/", "finances.gouv.sn_cdx"),
    ("www.finances.gouv.sn/app/uploads/", "finances.gouv.sn_cdx"),
    ("finances.gouv.sn/wp-content/uploads/", "finances.gouv.sn_cdx"),
    ("www.finances.gouv.sn/wp-content/uploads/", "finances.gouv.sn_cdx"),
    ("finances.gouv.sn/images/", "finances.gouv.sn_cdx"),
    ("www.finances.gouv.sn/images/", "finances.gouv.sn_cdx"),
    ("budget.gouv.sn/documents/LFI/", "budget.gouv.sn_cdx"),
    ("www.budget.gouv.sn/documents/LFI/", "budget.gouv.sn_cdx"),
    ("numerique.gouv.sn/sites/default/files/", "numerique.gouv.sn_cdx"),
    ("www.numerique.gouv.sn/sites/default/files/", "numerique.gouv.sn_cdx"),
    ("assemblee-nationale.sn/documents/", "assemblee_cdx"),
    ("www.assemblee-nationale.sn/documents/", "assemblee_cdx"),
]


def discover_official_cdx(items, seen):
    limit = env_int("CDX_LIMIT", 200)
    for prefix, portal in CDX_PREFIXES:
        try:
            hits = cdx_urls(prefix, limit=limit, match_type="prefix", extra_filters=["mimetype:application/pdf"])
        except Exception as exc:
            log.info("cdx fail %s: %s", prefix, exc)
            continue
        if not hits:
            try:
                hits = cdx_urls(prefix, limit=limit, match_type="prefix")
            except Exception as exc:
                log.info("cdx fail2 %s: %s", prefix, exc)
                continue
        log.info("cdx %s hits=%s", prefix, len(hits))
        for h in hits:
            orig = h.get("original") or ""
            if ".pdf" not in orig.lower():
                continue
            path = unquote(urlparse(orig).path)
            if DROP_RE.search(path):
                continue
            if not KEEP_RE.search(path):
                continue
            # skip deputy PDFs from AN
            if "deputePdf" in orig or "depute" in path.lower() and "loi" not in path.lower():
                continue
            portal_use = portal
            if re.search(r"(?i)/loisetdecrets/|loi[-_ ]|code[-_ ]", path):
                if "sec.gouv" in portal:
                    portal_use = "sec.gouv.sn_loi_cdx"
            _add(
                items,
                seen,
                _ident_from_url(orig),
                orig,
                {
                    "portal": portal_use,
                    "title": _title_from_url(orig),
                    "wayback_ts": h.get("timestamp"),
                    "kind": "pdf",
                },
            )


def ocr_pdf(raw: bytes) -> str:
    max_pages = env_int("MAX_OCR_PAGES", 12)
    dpi = env_int("OCR_DPI", 150)
    try:
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "doc.pdf"
            pdf.write_bytes(raw)
            proc = subprocess.run(
                [
                    "pdftoppm", "-png", "-r", str(dpi),
                    "-f", "1", "-l", str(max_pages),
                    str(pdf), str(Path(td) / "p"),
                ],
                check=False, capture_output=True, timeout=240,
            )
            if proc.returncode != 0:
                return ""
            chunks = []
            for img in sorted(Path(td).glob("p*.png")):
                tproc = subprocess.run(
                    ["tesseract", str(img), "stdout", "-l", "fra", "--psm", "6"],
                    check=False, capture_output=True, timeout=120,
                )
                if tproc.returncode == 0 and tproc.stdout:
                    chunks.append(tproc.stdout.decode("utf-8", "replace").strip())
            return "\n\n".join(c for c in chunks if c).strip()
    except Exception as exc:
        log.warning("ocr_pdf: %s", exc)
        return ""


def fetch_sn(url: str, *, wayback_ts: str | None = None, allow_ocr: bool = True) -> dict:
    got = fetch_official(url, ua=UA, verify=False, min_text=120, wayback=True, wayback_ts=wayback_ts)
    if got.get("status") == "success":
        return got
    body_for_ocr = got.get("content") or b""
    if wayback_ts:
        try:
            import archive_fallbacks as af
            w = af.get_wayback_content(_wayback_orig(url), timestamp=wayback_ts)
            body = w.get("content") or b""
            if w.get("status") == "success" and isinstance(body, bytes) and body[:4] == b"%PDF":
                text = pdf_to_text(body)
                if len(text) >= 120:
                    return {
                        "status": "success",
                        "text": text,
                        "content": body,
                        "method": "wayback_pdf_ts",
                        "source_url": w.get("url") or url,
                        "error": "",
                    }
                body_for_ocr = body
            else:
                got["error"] = (got.get("error") or "") + f";wb_ts:{w.get('error')}"
        except Exception as exc:
            got["error"] = (got.get("error") or "") + f";wb_ts:{exc}"
    # archives fichier direct
    if "/api/fichiers/" in url and got.get("status") != "success":
        try:
            r = live_get(url, ua=UA, verify=True, timeout=(20, 120), retries=2)
            body = r.content or b""
            if r.status_code == 200 and body[:4] == b"%PDF" and len(body) <= MAX_PDF_BYTES:
                text = pdf_to_text(body)
                if len(text) >= 120:
                    return {
                        "status": "success",
                        "text": text,
                        "content": body,
                        "method": "http_pdf_archives",
                        "source_url": url,
                        "error": "",
                    }
                body_for_ocr = body
        except Exception as exc:
            got["error"] = (got.get("error") or "") + f";archives_dl:{exc}"
    if not allow_ocr:
        return got
    body = body_for_ocr if isinstance(body_for_ocr, bytes) else b""
    if not (body and body[:4] == b"%PDF"):
        try:
            r = live_get(url, ua=UA, verify=False, timeout=(20, 90), retries=2)
            body = r.content or b""
        except Exception as exc:
            got["error"] = (got.get("error") or "") + f";ocr_dl:{exc}"
            return got
    if not (isinstance(body, bytes) and body[:4] == b"%PDF"):
        return got
    if len(body) > MAX_PDF_BYTES:
        got["error"] = (got.get("error") or "") + f";pdf_too_large:{len(body)}"
        return got
    text = pdf_to_text(body)
    if len(re.sub(r"[\x0c\s]+", "", text or "")) >= 120:
        got.update(status="success", text=text, content=body, method=got.get("method") or "http_pdf")
        return got
    if len(body) > env_int("MAX_OCR_BYTES", 8 * 1024 * 1024):
        return got
    ocr = ocr_pdf(body)
    if len(ocr) >= 120:
        return {
            "status": "success",
            "text": ocr,
            "content": body,
            "method": "ocr_fra",
            "source_url": url,
            "error": "",
        }
    return got



def discover():
    items, seen = [], set()
    discover_constitution(items, seen)
    # Prefer discrete laws/codes over JO fascicules
    discover_archives_type(
        items,
        seen,
        "law",
        max_pages=env_int("ARCHIVES_LAW_PAGES", 4),
        page_limit=env_int("ARCHIVES_PAGE_LIMIT", 50),
        portal="archives_law",
    )
    discover_archives_type(
        items,
        seen,
        "code",
        max_pages=env_int("ARCHIVES_CODE_PAGES", 2),
        page_limit=env_int("ARCHIVES_PAGE_LIMIT", 50),
        portal="archives_code",
    )
    discover_primature_pdf_cdx(items, seen)
    discover_primature_nodes(items, seen)
    discover_jo_live(items, seen)
    if env_int("JO_CDX", 1):
        discover_jo_cdx(items, seen)
    discover_archives_type(
        items,
        seen,
        "official_journal",
        max_pages=env_int("ARCHIVES_JO_PAGES", 3),
        page_limit=env_int("ARCHIVES_PAGE_LIMIT", 50),
        portal="archives_official_journal",
    )
    log.info("catalog total=%s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 100)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    portals: dict[str, int] = {}
    methods: dict[str, int] = {}
    catalog = discover()

    for ident, url, meta in catalog:
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            log.info("MAX_SECONDS reached")
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue

        portal = meta.get("portal") or "unknown"
        title = (meta.get("title") or "").strip()
        wayback_ts = meta.get("wayback_ts")
        fsize = int(meta.get("filesize") or 0)
        if fsize and fsize > MAX_PDF_BYTES:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": f"too_large:{fsize}", "portal": portal})
            continue

        allow_ocr = env_int("OCR_ALL", 1) == 1
        got = fetch_sn(url, wayback_ts=wayback_ts, allow_ocr=allow_ocr)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(
                CC,
                {"identifier": ident, "source_url": url, "reason": got.get("error"), "portal": portal},
            )
            time.sleep(0.35)
            continue
        if not text_ok(text, url, title, portal):
            fail += 1
            log_failure(
                CC,
                {
                    "identifier": ident,
                    "source_url": url,
                    "reason": "filter_no_loi_ordo_decret_const_jo",
                    "portal": portal,
                },
            )
            continue

        if not title or len(title) < 8:
            for ln in text.splitlines():
                s = ln.strip()
                if len(s) > 18 and re.search(
                    r"(?i)\b(journal\s+officiel|loi|constitution|ordonnance|d[eé]cret|code|r[eè]glement)\b",
                    s,
                ):
                    title = s[:240]
                    break
            if not title or len(title) < 8:
                title = next(
                    (ln.strip()[:240] for ln in text.splitlines() if len(ln.strip()) > 18),
                    title or _title_from_url(url),
                )

        method = got.get("method") or ""
        source_url = meta.get("page_url") or got.get("source_url") or url
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title,
            text=text,
            source_url=source_url,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_sn.py",
            date=_date_from(ident, title, text, meta.get("publish_date")),
            article_re=ART,
            extra_meta={
                "fetch_method": method,
                "portal": portal,
                "wayback_ts": wayback_ts,
                "fichier_url": url if "/api/fichiers/" in url else None,
                "retrieval": "archive" if "wayback" in method else "live",
            },
        ):
            ok += 1
            done.add(rid)
            portals[portal] = portals.get(portal, 0) + 1
            methods[method] = methods.get(method, 0) + 1
            log.info("ok %s portal=%s chars=%s method=%s", ident[:70], portal, len(text), method)
        else:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "save_failed", "portal": portal})
        time.sleep(0.35)

    write_summary(
        CC,
        country=COUNTRY,
        source="archives.sn / primature.sn / conseilconstitutionnel.sn / jo.gouv.sn",
        source_urls=[
            f"{ARCHIVES}/docs/journal-officiel",
            f"{ARCHIVES}/api/documents?type=law",
            f"{PRIMATURE}/publications/lois-et-reglements",
            f"{CCONST}/la-constitution/",
            f"{JO}/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete; archives.sn laws/codes/JO + primature.sn codes/lois/décrets "
            "+ conseilconstitutionnel Constitution; jo.gouv.sn often unreachable — CDX/Wayback of official URLs"
        ),
        notes=f"Official Senegal. portals={portals} methods={methods}. Not AfricanLII. No WAF bypass. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s portals=%s methods=%s", ok, skip, fail, portals, methods)


if __name__ == "__main__":
    main()
