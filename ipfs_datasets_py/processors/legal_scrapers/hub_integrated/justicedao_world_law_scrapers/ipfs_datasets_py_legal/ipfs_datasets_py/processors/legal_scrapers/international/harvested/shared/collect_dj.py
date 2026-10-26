#!/usr/bin/env python3
"""Djibouti (dj): official law texts from eJO (journalofficiel.dj) + Présidence.

Official only:
  - https://www.journalofficiel.dj/  (eJO / SGG — WP REST texte-juridique + journal-officiel)
  - https://journalofficiel.dj/
  - https://presidence.dj/ / https://www.presidence.dj/ (Constitution HTML; AnnexeTextes CDX PDFs)
  - Wayback/CDX of the same official *.dj / journalofficiel.dj / presidence.dj URLs

JO fascicule PDFs are not yet public (eJO "Bientôt disponible" / payment module).
Harvest uses official HTML textes juridiques (lois / ordonnances / décrets / …) via WP REST.
Filter: prefer loi/ordonnance/décret/constitution; skip PDFs >12MB; drop communiqués.
Not AfricanLII / Droit-Afrique. No WAF bypass. Not legal advice.
NOTE: country code dj = Djibouti. Leave er/et/so alone.
"""
from __future__ import annotations

import html as html_lib
import json
import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, html_to_text, log_failure, utcnow, write_summary
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

CC, COUNTRY, LANG = "dj", "Djibouti", "fr"
SOURCE_TYPE = "jo_djibouti_official"
LICENSE = (
    "République de Djibouti — Journal Officiel électronique / eJO "
    "(journalofficiel.dj / SGG) / Présidence (presidence.dj). "
    "Authentic Journal Officiel / official text prevails. Not legal advice."
)
UA = (
    "legal-corpora-collector/1.0 (research; source=https://www.journalofficiel.dj/; "
    "Djibouti=dj)"
)
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+\d+[a-zA-Zº°]?)\b")
log = logging.getLogger("dj")

JO = "https://www.journalofficiel.dj"
PRESIDENCE = "https://presidence.dj"
MAX_PDF_BYTES = 12 * 1024 * 1024

ALLOWED_SUFFIXES = (
    "journalofficiel.dj",
    "presidence.dj",
    "gouv.dj",
    "gov.dj",
)

# nature-dun-texte term IDs from eJO taxonomy (stable on live site)
NATURE_PRIORITY = [
    # (term_id, slug_hint, priority — lower = first)
    (247, "loi", 1),
    (259, "loi-organique", 1),
    (260, "loi-de-finances", 2),
    (263, "ordonnance", 3),
    (248, "decret", 4),
    (264, "decret-dapplication", 4),
    (1310, "arrete-de-promulgation", 5),
    (256, "arrete", 8),
    (269, "arrete-modificatif", 9),
    (268, "arrete-additif", 9),
    (254, "decision", 12),
    (1318, "deliberation", 14),
]

KEEP_RE = re.compile(
    r"(loi|ordonnance|ordonn|d[eé]cret|decret|arr[eê]t[eé]|arrete|constitution|code|"
    r"journal.?officiel|\bjord?\b|\bejo\b|organique|r[eè]glement|charte|statut|"
    r"texte.?juridique|promulgat)",
    re.I,
)
DROP_RE = re.compile(
    r"(africanlii|djiboutilii|droit-afrique|gazettes\.africa|law\.africa|"
    r"discours|allocution|communique|photo|banner|logo|cv[-_]|"
    r"biographie|rapport[-_ ]annuel|presentation|organigramme|"
    r"newsletter|recrutement|facebook|twitter|linkedin|"
    r"album|actualites|portrait)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(loi|ordonnance|d[eé]cret|decret|constitution|journal\s+officiel|"
    r"code|r[eé]publique\s+de\s+djibouti|assembl[eé]e\s+nationale|"
    r"pr[eé]sident\s+de\s+la\s+r[eé]publique|promulgue|article\s+\d|"
    r"vu\s+la\s+constitution|arr[eê]t[eé])\b",
    re.I,
)

CONSTITUTION_URL = f"{PRESIDENCE}/page/la-constitution-de-la-republique-de-djibouti"


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == s or host.endswith("." + s) for s in ALLOWED_SUFFIXES)


def _strip_html_title(s: str) -> str:
    s = html_lib.unescape(s or "")
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _compose_texte(item: dict) -> tuple[str, str, str, str]:
    """Return (ident, title, text, date) from WP texte-juridique JSON."""
    slug = item.get("slug") or str(item.get("id") or "")
    title = _strip_html_title((item.get("title") or {}).get("rendered") or slug)
    acf = item.get("acf") or {}
    parts: list[str] = []
    if title:
        parts.append(title)
    ref = (acf.get("reference") or "").strip()
    if ref:
        parts.append(f"Référence : {ref}")
    comment = _strip_html_title(acf.get("comment") or "")
    if comment and comment.lower() not in title.lower():
        parts.append(comment)
    visas = acf.get("visas") or ""
    if visas:
        parts.append(html_to_text(visas) if "<" in visas else visas.strip())
    body = (item.get("content") or {}).get("rendered") or ""
    if body:
        parts.append(html_to_text(body))
    sig = acf.get("signature") or ""
    if sig:
        parts.append(html_to_text(sig) if "<" in sig else sig.strip())
    text = "\n\n".join(p for p in parts if p and p.strip())
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    date = (item.get("date") or "")[:10] or None
    # Prefer ACF JO date if present via linked journal — not always available
    ident = f"ejo-{slug}"[:160]
    return ident, title, text, date


def _wp_pages(nature_id: int, *, per_page: int, max_pages: int) -> list[dict]:
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        url = (
            f"{JO}/wp-json/wp/v2/texte-juridique"
            f"?nature-dun-texte={nature_id}&per_page={per_page}&page={page}"
            f"&orderby=date&order=desc"
        )
        try:
            r = live_get(url, ua=UA, timeout=(15, 60), retries=3)
        except Exception as exc:
            log.info("wp nature=%s page=%s err %s", nature_id, page, exc)
            break
        if getattr(r, "status_code", 0) != 200:
            log.info("wp nature=%s page=%s status=%s", nature_id, page, getattr(r, "status_code", None))
            break
        try:
            rows = r.json()
        except Exception as exc:
            log.info("wp json err %s", exc)
            break
        if not isinstance(rows, list) or not rows:
            break
        out.extend(rows)
        total_pages = int(r.headers.get("X-WP-TotalPages") or "1")
        if page >= total_pages:
            break
        time.sleep(0.15)
    return out


def _constitution_text() -> tuple[str, str, str] | None:
    try:
        r = live_get(CONSTITUTION_URL, ua=UA, timeout=(15, 60), retries=3)
    except Exception as exc:
        log.info("constitution live err %s", exc)
        return None
    if getattr(r, "status_code", 0) != 200 or not r.text:
        return None
    html = r.text
    # Prefer main article / entry content
    m = re.search(
        r'(?is)<(?:article|div)[^>]*(?:entry-content|post-content|elementor-widget-theme-post-content|page-content)[^>]*>(.*)</(?:article|div)>',
        html,
    )
    chunk = m.group(1) if m else html
    # Trim nav chrome: cut at first TITRE / Article if present
    text = html_to_text(chunk)
    if len(text) < 500:
        text = html_to_text(html)
    if not re.search(r"(?i)constitution", text[:2000]):
        # still accept if long enough and mentions République de Djibouti
        if not (len(text) > 2000 and re.search(r"(?i)djibouti", text[:3000])):
            return None
    title = "Constitution de la République de Djibouti"
    return "constitution-republique-djibouti", title, text


def discover() -> list[tuple]:
    """Return list of (priority, ident, kind, payload)."""
    items: list[tuple] = []
    seen: set[str] = set()

    # 1) Constitution (Présidence)
    const = _constitution_text()
    if const:
        ident, title, text = const
        seen.add(ident)
        items.append((0, ident, "html", {"title": title, "text": text, "url": CONSTITUTION_URL, "date": None}))

    # 2) eJO textes juridiques by nature priority
    per_nature = env_int("PER_NATURE", 40)
    max_pages = env_int("WP_MAX_PAGES", 3)
    per_page = min(20, per_nature)  # WP max typically 20-100; keep lean
    for nature_id, slug_hint, pri in NATURE_PRIORITY:
        rows = _wp_pages(nature_id, per_page=per_page, max_pages=max_pages)
        log.info("nature %s/%s rows=%s", nature_id, slug_hint, len(rows))
        for row in rows[:per_nature]:
            ident, title, text, date = _compose_texte(row)
            if not ident or ident in seen:
                continue
            link = row.get("link") or f"{JO}/texte-juridique/{row.get('slug')}/"
            if not _host_ok(link):
                continue
            blob = f"{title} {ident} {text[:500]}"
            if DROP_RE.search(blob):
                continue
            if not KEEP_RE.search(title + " " + ident) and not TEXT_KEEP_RE.search(text[:4000]):
                continue
            # Soft-drop pure nomination arrêtés/décisions when we already have better stock
            if pri >= 8 and re.search(
                r"(?i)portant\s+nomination|portant\s+affectation|"
                r"portant\s+d[eé]l[eé]gation\s+de\s+signature|"
                r"portant\s+avancement",
                title,
            ):
                continue
            if len(text) < 120:
                continue
            seen.add(ident)
            items.append((pri, ident, "html", {"title": title, "text": text, "url": link, "date": date}))

    # 3) Optional CDX AnnexeTextes / uploads PDFs from Présidence (legacy)
    if env_int("INCLUDE_CDX_PDF", 1):
        for prefix in (
            "www.presidence.dj/AnnexeTextes/",
            "presidence.dj/AnnexeTextes/",
            "www.presidence.dj/wp-content/uploads/",
            "presidence.dj/wp-content/uploads/",
        ):
            try:
                hits = cdx_urls(
                    prefix,
                    limit=env_int("CDX_LIMIT", 60),
                    match_type="prefix",
                    extra_filters=["statuscode:200", "mimetype:application/pdf"],
                ) or []
            except Exception as exc:
                log.info("cdx %s %s", prefix, exc)
                hits = []
            for h in hits:
                orig = h.get("original") or ""
                ts = (h.get("timestamp") or "")[:14] or None
                try:
                    length = int(h.get("length") or 0)
                except Exception:
                    length = 0
                if length and length > MAX_PDF_BYTES:
                    continue
                if not _host_ok(orig):
                    continue
                low = unquote(orig).lower()
                if DROP_RE.search(low):
                    continue
                # AnnexeTextes filenames are opaque hashes — keep; text filter later
                if "/annexetextes/" not in low and not KEEP_RE.search(low):
                    continue
                stem = Path(unquote(urlsplit(orig).path)).stem.lower()
                ident = f"presidence-{stem}"[:160]
                if ident in seen:
                    continue
                seen.add(ident)
                pri = 20 if "/annexetextes/" in low else 25
                if "constitut" in low:
                    pri = 1
                items.append(
                    (
                        pri,
                        ident,
                        "pdf",
                        {"url": orig, "ts": ts, "size_hint": length or None, "title": stem},
                    )
                )

    items.sort(key=lambda x: (x[0], x[1]))
    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 2400)
    t_start = time.time()
    done = existing_ids(CC)
    already = len(done)
    target_total = env_int("TARGET_TOTAL", 0)
    ok = skip = fail = 0

    for pri, ident, kind, payload in discover():
        if max_new and ok >= max_new:
            break
        if target_total and (already + ok) >= target_total:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue

        if kind == "html":
            text = payload.get("text") or ""
            url = payload.get("url") or ""
            title = payload.get("title") or ident
            date = payload.get("date")
            if not TEXT_KEEP_RE.search(text[:8000]):
                fail += 1
                log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_not_legal"})
                continue
            if len(text) > 2_500_000:
                fail += 1
                log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_too_large", "chars": len(text)})
                continue
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
                collector="collect_dj.py",
                date=date,
                article_re=ART,
                extra_meta={"fetch_method": "wp_rest_html", "priority": pri},
            ):
                ok += 1
                done.add(rid)
                log.info("ok %s chars=%s", ident[:70], len(text))
            else:
                fail += 1
            continue

        # PDF path (CDX / live Présidence)
        url = payload.get("url") or ""
        ts = payload.get("ts")
        size_hint = payload.get("size_hint")
        if size_hint and size_hint > MAX_PDF_BYTES:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, wayback=True, wayback_ts=ts)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error"), "wayback_ts": ts})
            continue
        if len(text) > 2_500_000:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_too_large"})
            continue
        if not TEXT_KEEP_RE.search(text[:8000]):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_not_legal"})
            continue
        use_title = payload.get("title") or ident
        for line in text.splitlines():
            if len(line.strip()) > 18:
                use_title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=use_title,
            text=text,
            source_url=url,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_dj.py",
            article_re=ART,
            extra_meta={"fetch_method": got.get("method"), "wayback_ts": ts, "size_hint": size_hint, "priority": pri},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:60], got.get("method"), len(text))
        else:
            fail += 1

    write_summary(
        CC,
        country=COUNTRY,
        source="Djibouti Journal Officiel électronique (journalofficiel.dj / eJO) / Présidence",
        source_urls=[
            "https://www.journalofficiel.dj/",
            "https://www.journalofficiel.dj/journaux-officiels/",
            "https://www.journalofficiel.dj/texte-juridique/",
            "https://presidence.dj/",
            "https://presidence.dj/page/la-constitution-de-la-republique-de-djibouti",
            "https://presidence.dj/page/ejo",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (eJO WP REST texte-juridique HTML live; "
            "JO fascicule PDFs not yet public; Présidence Constitution HTML; "
            "AnnexeTextes CDX PDFs optional)"
        ),
        notes=(
            "Official *.dj / journalofficiel.dj / presidence.dj only. "
            "HTML textes juridiques via official WP REST. Not AfricanLII. "
            "No WAF bypass. Not legal advice. dj=Djibouti (not er/et/so)."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s total_instruments=%s", ok, skip, fail, len(done))


if __name__ == "__main__":
    main()
