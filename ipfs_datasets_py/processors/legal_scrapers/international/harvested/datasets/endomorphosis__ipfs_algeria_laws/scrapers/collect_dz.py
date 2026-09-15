#!/usr/bin/env python3
"""Algeria: Journal Officiel (JORADP / SGG) official PDF issues.
Live joradp.dz often hangs from collector host; prefer HTTP Wayback of official URLs.
"""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import unquote, urlparse
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id
import archive_fallbacks as af
import world_lib as wl

CC, COUNTRY, LANG = "dz", "Algeria", "fr"
SOURCE_TYPE = "joradp"
LICENSE = (
    "Journal Officiel de la République Algérienne Démocratique et Populaire "
    "(joradp.dz, Secrétariat Général du Gouvernement). JO authentic text prevails. "
    "Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=http://www.joradp.dz/)"
log = logging.getLogger("dz")

# Seed codes (also recovered via CDX)
CODES = [
    ("constitution-fr", "http://www.joradp.dz/TRV/FCons.pdf", "Constitution (FR)"),
    ("constitution-ar", "http://www.joradp.dz/TRV/ACons.pdf", "الدستور"),
    ("code-penal-fr", "http://www.joradp.dz/TRV/FPenal.pdf", "Code pénal"),
    ("code-civil-fr", "http://www.joradp.dz/TRV/FCivil.pdf", "Code civil"),
    ("code-proc-penale-fr", "http://www.joradp.dz/TRV/FPPenal.pdf", "Code de procédure pénale"),
    ("code-proc-civile-fr", "http://www.joradp.dz/TRV/FPCivile.pdf", "Code de procédure civile"),
    ("code-famille-fr", "http://www.joradp.dz/TRV/FFam.pdf", "Code de la famille"),
    ("code-commerce-fr", "http://www.joradp.dz/TRV/FCom.pdf", "Code de commerce"),
    ("code-nationalite-fr", "http://www.joradp.dz/TRV/FNat.pdf", "Code de la nationalité"),
]


def _norm_url(url: str) -> str:
    url = (url or "").split("#")[0].replace(":80/", "/").replace(":80?", "?")
    # Prefer HTTP — HTTPS to joradp often SSLEOF from this host
    if url.startswith("https://"):
        url = "http://" + url[len("https://"):]
    return url


def _ident_from_url(url: str) -> str:
    path = unquote(urlparse(url).path)
    stem = Path(path).stem
    return re.sub(r"[^\w.\-]+", "-", stem).strip("-")[:160] or "joradp"


def _title_for(ident: str, url: str) -> str:
    m = re.search(r"F(\d{4})(\d{3})$", ident, re.I)
    if m:
        return f"Journal Officiel n° {int(m.group(2))} ({m.group(1)}) — édition française"
    m = re.search(r"A(\d{4})(\d{3})$", ident, re.I)
    if m:
        return f"Journal Officiel n° {int(m.group(2))} ({m.group(1)}) — édition arabe"
    low = ident.lower()
    mapping = {
        "fcons": "Constitution (FR)",
        "acons": "الدستور",
        "fpenal": "Code pénal",
        "fcivil": "Code civil",
        "fppenal": "Code de procédure pénale",
        "fpcivile": "Code de procédure civile",
        "ffam": "Code de la famille",
        "fcom": "Code de commerce",
        "fnat": "Code de la nationalité",
    }
    return mapping.get(low, ident)


def discover():
    items, seen = [], set()

    def add(url, title=None, ts=None):
        url = _norm_url(url)
        if "joradp.dz" not in url.lower():
            return
        if ".pdf" not in url.lower():
            return
        # official JO / codes paths only
        low = url.lower()
        if not any(p in low for p in ("/trv/", "/ftp/jo", "/ftp/jo-francais", "/ftp/jo-arabe")):
            # allow JO-FRANCAIS variants
            if "/ftp/" not in low and "/trv/" not in low:
                return
        key = url.lower()
        if key in seen:
            return
        seen.add(key)
        ident = _ident_from_url(url)
        items.append((ident, url, title or _title_for(ident, url), ts))

    if not env_int("SKIP_SEED_CODES", 0):
        for ident, url, title in CODES:
            add(url, title=title)

    cdx_limit = env_int("CDX_LIMIT", 400)
    # Prefer JO issue PDFs and codes before miscellaneous TRV bulletins
    for prefix in (
        "www.joradp.dz/FTP/JO-FRANCAIS/",
        "www.joradp.dz/FTP/jo-francais/",
        "joradp.dz/FTP/JO-FRANCAIS/",
        "joradp.dz/FTP/jo-francais/",
        "www.joradp.dz/FTP/JO-ARABE/",
        "www.joradp.dz/FTP/jo-arabe/",
        "www.joradp.dz/TRV/",
        "joradp.dz/TRV/",
    ):
        for h in cdx_urls(
            prefix,
            limit=cdx_limit,
            match_type="prefix",
            extra_filters=["mimetype:application/pdf", "statuscode:200"],
        ):
            orig = h.get("original") or ""
            if orig:
                add(orig, ts=h.get("timestamp"))

    log.info("catalog %s", len(items))
    return items


def fetch_joradp(url: str, ts: str | None = None) -> dict:
    """Wayback-first for joradp (live hangs); short live probe only if no capture."""
    url = _norm_url(url)
    # Prefer known timestamp / CDX capture
    try_urls = [url]
    if url.startswith("http://www."):
        try_urls.append(url.replace("http://www.", "http://", 1))
    # Case variants for FTP path
    alt = url
    if "/FTP/jo-francais/" in alt:
        try_urls.append(alt.replace("/FTP/jo-francais/", "/FTP/JO-FRANCAIS/"))
    elif "/FTP/JO-FRANCAIS/" in alt:
        try_urls.append(alt.replace("/FTP/JO-FRANCAIS/", "/FTP/jo-francais/"))

    errors = []
    for try_url in try_urls:
        try:
            w = af.get_wayback_content(try_url, timestamp=ts)
            if w.get("status") == "success":
                raw = w.get("content") or b""
                if isinstance(raw, str):
                    raw = raw.encode("latin-1", "replace")
                if raw[:4] == b"%PDF" or b"%PDF" in raw[:8192]:
                    if raw[:4] != b"%PDF":
                        raw = raw[raw.find(b"%PDF"):]
                    text = wl.pdf_to_text(raw)
                    if len(text) >= 80 and not text.lstrip().startswith("%PDF"):
                        return {
                            "status": "success",
                            "text": text,
                            "content": raw,
                            "method": "wayback_pdf",
                            "error": "",
                            "source_url": w.get("wayback_url") or try_url,
                        }
                errors.append(f"wb_short:{try_url}")
            else:
                errors.append(f"wb:{w.get('error')}")
        except Exception as exc:
            errors.append(f"wb_exc:{exc}")

    # Short live probe (joradp usually hangs — keep tight)
    old_live = wl.live_get

    def _short_live(u, **kw):
        kw.setdefault("timeout", (6, 12))
        kw.setdefault("retries", 1)
        kw.setdefault("verify", False)
        return old_live(u, **kw)

    wl.live_get = _short_live
    try:
        got = fetch_official(url, ua=UA, verify=False, wayback=True, min_text=80)
        if got.get("status") == "success":
            return got
        errors.append(got.get("error") or "live_fail")
    finally:
        wl.live_get = old_live

    return {"status": "error", "text": "", "content": b"", "method": "", "error": ";".join(errors)[:500]}


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    items = discover()
    ok = skip = fail = 0
    for ident, url, title, ts in items:
        if max_new and ok >= max_new:
            break
        if max_seconds and (time.time() - t_start) > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_joradp(url, ts=ts)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        year = None
        m = re.search(r"[FA](\d{4})\d{3}$", ident, re.I)
        if m:
            year = f"{m.group(1)}-01-01"
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident, title=title, text=text,
            source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
            collector="collect_dz.py", date=year,
            extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident, got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="JORADP Journal Officiel PDFs",
        source_urls=["http://www.joradp.dz/", "http://www.joradp.dz/FTP/JO-FRANCAIS/"],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="codes + JO issues via CDX/Wayback of official joradp.dz URLs (incomplete)",
        notes="Live joradp.dz hangs from collector host; HTTP Wayback of official JO/code PDFs. Not Adala/Qistas. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
