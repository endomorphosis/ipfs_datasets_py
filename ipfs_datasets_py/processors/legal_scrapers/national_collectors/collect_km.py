#!/usr/bin/env python3
"""Comoros (km): official law PDFs from Beit-Salam (Presidency) + Justice + Finances.

Official only:
  - https://beit-salam.km/  (Presidence de l Union des Comores — assets/Decret etc.)
  - https://www.beit-salam.km/
  - https://justice.gouv.km/
  - https://finances.gouv.km/ / https://www.finances.gouv.km/
  - https://gouv.km/ / *.gouv.km when resolvable
  - Wayback/CDX of the same official *.km / *.gouv.km URLs

Prefer loi / decret / constitution / ordonnance / arrete / code / JO. Skip PDFs >12MB.
NOT AfricanLII / Droit-Afrique. No WAF bypass. Not legal advice.
NOTE: country code km = Comoros. Leave mg/mu/sc alone.
"""
from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import (
    cdx_urls,
    env_int,
    fetch_official,
    live_get,
    save_instrument,
    setup_log,
    slug_id,
)

CC, COUNTRY, LANG = "km", "Comoros", "fr"
SOURCE_TYPE = "comoros_beit_salam_justice_finances"
LICENSE = (
    "Union des Comores — Presidence (beit-salam.km) / Justice (justice.gouv.km) / "
    "Finances (finances.gouv.km). Authentic official text / Journal Officiel prevails. "
    "Not legal advice."
)
UA = (
    "legal-corpora-collector/1.0 (research; source=https://beit-salam.km/; "
    "Comoros=km)"
)
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?|ARTICLE)\s+\d+[a-zA-Zº°]?)\b")
log = logging.getLogger("km")

BEIT = "https://beit-salam.km"
JUSTICE = "https://justice.gouv.km"
FINANCES = "https://finances.gouv.km"
MAX_PDF_BYTES = 12 * 1024 * 1024

ALLOWED_SUFFIXES = ("beit-salam.km", "gouv.km", "gov.km")
# bare union.km / gouv.km apex rarely serve law PDFs; allow *.km only if suffix match
ALLOWED_EXACT = ("gouv.km", "union.km")

KEEP_RE = re.compile(
    r"(loi|decret|d[eé]cret|ordonnance|arr[eê]t[eé]|arrete|constitution|code|"
    r"journal.?officiel|organique|r[eè]glement|charte|statut|texte.?juridique|"
    r"promulgat|loi.?des.?finances|code.?des.?imp[oô]ts|\bcgi\b|/assets/decret/)",
    re.I,
)
DROP_RE = re.compile(
    r"(africanlii|comoroslii|droit-afrique|gazettes\.africa|law\.africa|"
    r"discours|allocution|communique|photo|banner|logo|cv[-_]|"
    r"biographie|rapport[-_ ]annuel|presentation|organigramme|"
    r"newsletter|recrutement|facebook|twitter|linkedin|"
    r"album|actualites|portrait|vacancy|tender|speech|workshop|"
    r"madagascar|mauritius|seychelles|"
    r"contrat|avenant|marche[-_ ]public|manuel[-_ ]des[-_ ]procedure|"
    r"bulletin[-_]|(^|/)ami[_-]|budget[-_ ]citoyen|transparence[-_ ]fiscale|"
    r"rapport[-_ ]d.?assistance|rapport[-_ ]devaluation|appui_a_la_soutenabilite|"
    r"devises|taux[-_ ]de[-_ ]change|lettre[-_ ]de[-_ ]cadrage|"
    r"anyscan|bilan[-_ ]synthese|logisticien|"
    r"nomination|nommant|renouvellement[-_ ]mandat|mettant[-_ ]fin|"
    r"consule?[-_ ]generale|conseiller[-_ ]president|interim|interiem|"
    r"ouverture[-_ ]rassemblements|lettre[-_ ]de[-_ ]cadrage)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(loi|d[eé]cret|decret|ordonnance|constitution|journal\s+officiel|"
    r"code|union\s+des\s+como|r[eé]publique\s+(f[eé]d[eé]rale\s+)?islamique|"
    r"assembl[eé]e\s+(de\s+l.?union|nationale)|pr[eé]sident|"
    r"promulgue|article\s+\d|vu\s+la\s+constitution|arr[eê]t[eé])\b",
    re.I,
)


SEED_PDFS = [
    ("beit-decret-18-026-pr", "https://beit-salam.km/assets/Decret/DECRET%20N%C2%B018-026_PR.pdf", "Decret N 18-026/PR", 10),
    ("beit-decret-18-005pr-mgomri", "https://beit-salam.km/assets/Decret/Decret18-005PR-Mgomri.pdf", "Decret 18-005/PR", 12),
    ("beit-decret-18-006pr-archimed", "https://beit-salam.km/assets/Decret/Decret18-006PR-Archimed.pdf", "Decret 18-006/PR", 12),
    # densify 2026-09: live finances <12MB promulgations / LF rectificative
    ("finances-decret-23-064pr-lfr-2023", "https://finances.gouv.km/wp-content/uploads/2024/12/Decret_N%C2%B023-064PR_portant_Promulgation_de_la_loi_de_Finances_Rectificative_2023.pdf", "Decret 23-064/PR LFR 2023", 6),
    ("finances-decret-24-187pr-reglement-2023", "https://finances.gouv.km/wp-content/uploads/2025/01/Decret-N%C2%B024-187PR-du-19-decembre-2024-portant-promulgation-loi-N%C2%B024-017PR-Portant-Loi-de-Reglement-2023.pdf", "Decret 24-187/PR Loi de Reglement 2023", 6),
    ("finances-lfr-2024", "https://finances.gouv.km/wp-content/uploads/2024/12/LOI-DE-FINANCES-RECTIFICATIVES-2024.pdf", "Loi de finances rectificative 2024", 5),
]

CDX_PREFIXES = (
    "beit-salam.km/assets/Decret/",
    "www.beit-salam.km/assets/Decret/",
    "beit-salam.km/assets/",
    "www.beit-salam.km/assets/",
    "beit-salam.km/",
    "justice.gouv.km/wp-content/uploads/2025/03/",
    "justice.gouv.km/wp-content/uploads/",
    "justice.gouv.km/",
    "finances.gouv.km/wp-content/uploads/",
    "finances.gouv.km/",
    "www.finances.gouv.km/",
    "gouv.km/",
    "sgg.gouv.km/",
)

LIVE_PAGES = (
    f"{BEIT}/",
    f"{BEIT}/assets/Decret/",
    f"{BEIT}/assets/",
    "https://www.beit-salam.km/",
    f"{JUSTICE}/",
    f"{FINANCES}/",
    f"{FINANCES}/lois/",
    "https://www.finances.gouv.km/",
    "https://www.finances.gouv.km/lois/",
    "https://sgg.gouv.km/",
    "https://gouv.km/",
)

def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if any(x in host for x in ("africanlii", "droit-afrique", "gazettes.africa", "law.africa")):
        return False
    # Prefer known official suffixes; allow bare gouv.km
    if host in ALLOWED_EXACT:
        return True
    return any(host == s or host.endswith("." + s) for s in ALLOWED_SUFFIXES)

def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()

def _ident_from_url(url: str, prefix: str = "beit") -> str:
    stem = Path(unquote(urlsplit(url).path)).stem
    stem = re.sub(r"[^\w\-]+", "-", stem).strip("-").lower()
    return f"{prefix}-{stem}"[:160]

def _priority(name: str) -> int:
    low = name.lower()
    if re.search(r"constitut", low):
        return 1
    if re.search(r"(^|[/_\-])loi|organique", low):
        return 5
    if re.search(r"ordonnance", low):
        return 8
    if re.search(r"d[eé]?cret|decret", low):
        return 12
    if re.search(r"arr[eê]t|arrete|code|journal", low):
        return 18
    return 25

def _should_keep(url: str, title: str = "") -> bool:
    blob = unquote(url) + " " + (title or "")
    if not _host_ok(url):
        return False
    if DROP_RE.search(blob):
        # nominations / personnel decrees never kept even if filename has decret
        if re.search(r"(?i)(nomination|nommant|renouvellement[-_ ]mandat|mettant[-_ ]fin|"
                     r"consule?[-_ ]generale|conseiller[-_ ]president|interim|interiem|"
                     r"ouverture[-_ ]rassemblements)", blob):
            return False
        # allow only if clear enacted-law filename wins
        if not re.search(r"(?i)(loi[-_ ]|decret|d[eé]cret|constitut|ordonnance|/assets/decret/|code[-_ ])", blob):
            return False
        if re.search(r"(?i)(contrat|avenant|manuel|bulletin|ami[_-]|budget[-_ ]citoyen)", blob):
            return False
    if re.search(r"(?i)/assets/decret/", blob):
        return True
    host = (urlsplit(url).hostname or "").lower()
    if "finances" in host:
        # finances PDFs: only loi/code/decret promulgation / CGI / code impots
        return bool(re.search(
            r"(?i)(loi|decret|d[eé]cret|ordonnance|constitution|code|cgi|"
            r"imp[oô]ts|promulgat|/assets/decret/)",
            unquote(urlsplit(url).path) + " " + title,
        ))
    return bool(KEEP_RE.search(blob))

def _scrape_page_pdfs(page_url: str) -> list[tuple[str, str]]:
    """Return (url, title_guess) PDF hrefs from an HTML page."""
    try:
        r = live_get(page_url, ua=UA, timeout=(15, 45), retries=2)
    except Exception as exc:
        log.info("page %s err %s", page_url, exc)
        return []
    if getattr(r, "status_code", 0) != 200 or not getattr(r, "text", None):
        return []
    html = r.text
    found: list[tuple[str, str]] = []
    for m in re.finditer(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html, re.I):
        href = m.group(1).replace("&amp;", "&")
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            sp = urlsplit(page_url)
            href = f"{sp.scheme}://{sp.hostname}{href}"
        title = unquote(Path(urlsplit(href).path).stem).replace("-", " ").replace("_", " ")
        found.append((href, title))
    return found

def _prefix_for(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if "justice" in host:
        return "justice"
    if "finance" in host:
        return "finances"
    if "beit-salam" in host:
        return "beit"
    return "gouv"

def discover():
    """Return list of (priority, ident, url, ts|None, title, size_hint|None)."""
    items: list[tuple] = []
    seen: set[str] = set()

    def add(url: str, *, ident: str | None = None, title: str = "", ts: str | None = None,
            size_hint: int | None = None, priority: int | None = None, prefix: str | None = None):
        url = (url or "").split("#")[0].strip()
        if url.startswith("http://"):
            url = "https://" + url[len("http://") :]
        if "web.archive.org/web/" in url:
            m = re.search(r"https?://web\.archive\.org/web/\d+(?:id_)?/(https?://.*)", url)
            if m:
                url = m.group(1)
        if not url.startswith("http") or not _should_keep(url, title):
            return
        if ".pdf" not in url.lower():
            return
        key = url.lower()
        if key in seen:
            return
        seen.add(key)
        if size_hint and size_hint > MAX_PDF_BYTES:
            log.info("catalog skip >12MB sz=%s %s", size_hint, url.split("/")[-1][:60])
            return
        pfx = prefix or _prefix_for(url)
        iid = ident or _ident_from_url(url, prefix=pfx)
        pri = priority if priority is not None else _priority(url + " " + title)
        items.append((pri, iid, url, ts, title or iid, size_hint))

    for ident, url, title, pri in SEED_PDFS:
        add(url, ident=ident, title=title, priority=pri, prefix="beit")

    for page in LIVE_PAGES:
        for href, title in _scrape_page_pdfs(page):
            add(href, title=title, prefix=_prefix_for(href))
        time.sleep(0.15)

    for base, pfx in ((BEIT, "beit"), (JUSTICE, "justice"), (FINANCES, "finances")):
        for page in range(1, 4):
            api = (
                f"{base}/wp-json/wp/v2/media"
                f"?per_page=100&page={page}&mime_type=application/pdf"
                f"&orderby=date&order=desc"
            )
            try:
                r = live_get(api, ua=UA, timeout=(15, 45), retries=2)
            except Exception as exc:
                log.info("wp media %s %s", base, exc)
                break
            if getattr(r, "status_code", 0) != 200:
                break
            try:
                rows = r.json()
            except Exception:
                break
            if not isinstance(rows, list) or not rows:
                break
            for it in rows:
                src = it.get("source_url") or ""
                title = _strip_html((it.get("title") or {}).get("rendered") or "")
                sz = None
                try:
                    sz = int((it.get("media_details") or {}).get("filesize") or 0) or None
                except Exception:
                    sz = None
                add(src, title=title, size_hint=sz, prefix=pfx)
            total_pages = int(r.headers.get("X-WP-TotalPages") or "1")
            if page >= total_pages:
                break
            time.sleep(0.12)

    if env_int("INCLUDE_CDX_PDF", 1):
        for prefix in CDX_PREFIXES:
            try:
                hits = cdx_urls(
                    prefix,
                    limit=env_int("CDX_LIMIT", 250),
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
                stem = Path(unquote(urlsplit(orig).path)).stem
                add(orig, title=stem, ts=ts, size_hint=length or None, prefix=_prefix_for(orig))

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

    for pri, ident, url, ts, title, size_hint in discover():
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
        if size_hint and size_hint > MAX_PDF_BYTES:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, wayback=True, wayback_ts=ts)
        text = got.get("text") or ""
        raw_len = int(got.get("raw_bytes") or got.get("content_length") or 0)
        if raw_len and raw_len > MAX_PDF_BYTES:
            skip += 1
            log.info("skip >12MB raw=%s %s", raw_len, ident[:50])
            continue
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
        use_title = title or ident
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
            collector="collect_km.py",
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
        source="Union des Comores Presidence (beit-salam.km) / Justice / Finances",
        source_urls=[
            "https://beit-salam.km/",
            "https://www.beit-salam.km/",
            "https://justice.gouv.km/",
            "https://finances.gouv.km/",
            "https://www.finances.gouv.km/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (beit-salam.km assets/Decret live+CDX; "
            "justice.gouv.km / finances.gouv.km lean; PDFs >12MB skipped)"
        ),
        notes=(
            "Official *.km / *.gouv.km / beit-salam.km only. Live-first; "
            "Wayback/CDX of same official URLs. Not AfricanLII. No WAF bypass. "
            "Not legal advice. km=Comoros (not mg/mu/sc)."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s total_instruments=%s", ok, skip, fail, len(done))


if __name__ == "__main__":
    main()

