#!/usr/bin/env python3
"""Uganda: official Acts/gazettes PDFs via parliament.go.ug / judiciary.go.ug / ulrc.go.ug / mog.go.ug.

Official *.go.ug only. ULII is NOT the official gazette — excluded.
Not AfricanLII / commercial DBs. No WAF bypass. Live-first; Wayback/CDX of official URLs OK.

Densify: Uganda Acts use Commonwealth ``1. Short title.`` section numbering (not only
``Section N``). Prefer enacting body after ``BE IT ENACTED`` / TOC to avoid double-counting.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    INDEX_FIELDS,
    ROOT,
    atomic_write,
    base_record,
    existing_ids,
    http_get,
    log_failure,
    utcnow,
    write_instrument,
    write_summary,
)
from world_lib import (
    cdx_urls,
    env_int,
    fetch_official,
    first_title,
    setup_log,
    slug_id,
    split_custom,
)

CC, COUNTRY, LANG = "ug", "Uganda", "en"
SOURCE_TYPE = "uganda_official_gazette_acts"
LICENSE = (
    "Republic of Uganda — Parliament (parliament.go.ug) / Judiciary (judiciary.go.ug) / "
    "Uganda Law Reform Commission (ulrc.go.ug) / Ministry of Gender or other *.go.ug gazette hosts. "
    "Authentic Official Gazette / Act text prevails. Not ULII as gazette source. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.parliament.go.ug/)"

# Commonwealth body sections: "1. Short title." / "12A. Interpretation." PLUS classic "Section 3"
ART = re.compile(
    r"(?im)^\s*((?:Article|Art\.?|Section|Sec\.?)\s+[0-9]+[A-Za-z]?|"
    r"\d+[A-Za-z]?\.)(?=\s+[A-Z\"'(])"
)

log = logging.getLogger("ug")
HOMES = [
    "https://www.parliament.go.ug/",
    "https://www.parliament.go.ug/documents",
    "https://www.parliament.go.ug/documents/acts",
    "https://www.parliament.go.ug/page/acts-parliament",
    "https://judiciary.go.ug/",
    "https://www.judiciary.go.ug/",
    "https://ulrc.go.ug/",
    "https://www.ulrc.go.ug/",
    "https://www.mog.go.ug/",
    "https://mog.go.ug/",
    "https://www.justice.go.ug/",
    "https://justice.go.ug/",
    "https://www.mia.go.ug/",
]
ALLOWED = ("go.ug",)

DROP_RE = re.compile(
    r"(ulii\.org|africanlii|law\.africa|ugandalaws\.com|/news/|/videos?/|interview|"
    r"facebook|youtube|logo|banner|photo|recruitment|vacancy|newsletter|"
    r"tender|procurement|budget.?speech|manifesto|strategic.?plan|"
    r"annual.?report|brochure|flyer|calendar|form[-_]|application.?form|"
    r"judicial.?officers|officers.?list|judges.?conf|magistrates.?conf|"
    r"cause.?list|causelist|press.?release|news.?release|programme|program.?fin|"
    r"members_12|bid.?notice|jlos|integrity|transfers|law.?year|"
    r"performance.?enhancement|case.?disposal|disposing.?of.?cases|"
    r"view.?from.?the.?bar|accountability.?in.?the.?judiciary|"
    r"ajc_|_ajc|presession|nocourtsclosed|newtransfers|cannonier|"
    r"concept.?paper|issues.?paper|call.?for.?abstracts|pre-enactment|"
    r"advocacy|review.?of.?the)",
    re.I,
)
KEEP_RE = re.compile(
    r"(act|acts|bill|statute|ordinance|proclamation|gazette|law|legal|"
    r"constitution|subsidiary|instrument|regulation|order|cap\.?\s*\d|"
    r"amendment|decree|supplement|rules.?of.?procedure)",
    re.I,
)
# Strong Act signal for priority / prune exemptions
ACT_URL_RE = re.compile(
    r"(?i)(?:act[_\s.-]?no|/acts?/|act\d{4}|_act\.pdf|act\.pdf|"
    r"billtrack|statute|ordinance|constitution|supplement|"
    r"statutory.?instrument|rules.?of.?procedure|gazett)",
)
ACT_TEXT_RE = re.compile(
    r"(?i)(?:BE IT ENACTED|ARRANGEMENT OF SECTIONS|STATUTORY INSTRUMENTS?|"
    r"SUPPLEMENT No\.|Act No\.|\bTHE\s+[A-Z][A-Z\s,'()/-]{6,100}\s+ACT\b)",
)
JUNK_RE = re.compile(
    r"(?i)judicial officers|judges.? ?conference|magistrates conference|"
    r"press release|news release|cause.?list|causelist|procurement plan|"
    r"strategic plan|members of the \d|progress report|annual judges|"
    r"integrity|programme|program fin|bid notice|law year|"
    r"performance enhancement|case disposal|transfers|jlos|"
    r"magazine|newsletter|vacancy|presession|nocourtsclosed|newtransfers|"
    r"ajc_|_ajc|judiciarynews|cannonier|abridged_bid|disposing_of_cases|"
    r"view_from_the_bar|accountability_in_the_judiciary|report_on_|"
    r"draft_report|officers_list|members_12|concept.?paper|issues.?paper",
)
MAX_PDF_BYTES = 12 * 1024 * 1024


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if "ulii" in host:
        return False
    return any(host == s or host.endswith("." + s) for s in ALLOWED)


def _norm_url(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    # strip :80 CDX quirk
    if url.startswith("https://") and ":80/" in url:
        url = url.replace(":80/", "/")
    return url


def prefer_enacting_body(text: str) -> str:
    """Skip arrangement/TOC so article split targets operative sections."""
    if not text:
        return text
    m = re.search(r"(?is)BE IT ENACTED[^\n]*\n", text)
    if m and m.end() < len(text) - 200:
        return text[m.end() :]
    ones = list(re.finditer(r"(?im)^\s*1\.\s+(?:Short title|Citation)\b", text))
    if len(ones) >= 2:
        # second occurrence = body start (first is usually TOC)
        return text[ones[1].start() :]
    m = re.search(r"(?i)ARRANGEMENT OF (?:SECTIONS|RULES|ORDERS)", text)
    if m:
        parts = list(re.finditer(r"(?im)^\s*PART\s+I\b", text))
        if len(parts) >= 2:
            return text[parts[1].start() :]
    return text


def _priority(url: str) -> int:
    """Lower = fetch first. Prefer clear Acts over misc downloads."""
    blob = unquote(url)
    if re.search(r"(?i)act[_\s.-]?no|/acts?/|_act\.pdf|act\.pdf|billtrack", blob):
        return 0
    if re.search(r"(?i)statute|ordinance|constitution|supplement|statutory|rules.?of.?procedure|gazett", blob):
        return 1
    if re.search(r"(?i)bill|regulation|instrument|amendment|decree", blob):
        return 2
    if re.search(r"(?i)parliament\.go\.ug", blob):
        return 3
    return 5


def discover():
    items, seen = [], set()

    def add(url: str):
        url = _norm_url(url)
        if not url.startswith("http"):
            return
        if not _host_ok(url) or DROP_RE.search(url):
            return
        if ".pdf" not in url.lower():
            return
        blob = unquote(url)
        if not KEEP_RE.search(blob) and not re.search(
            r"(?i)(gazette|/acts?/|/laws?/|/legislation|billtrack)", blob
        ):
            if not re.search(r"(?i)/(documents?|publications?|downloads?|files?)/", blob):
                return
            # path-only keep: still require mild lawish hint in path for downloads dumps
            if not ACT_URL_RE.search(blob):
                return
        if url in seen:
            return
        ident = re.sub(r"^https?://[^/]+/", "", unquote(url)).replace("/", "-").replace("?", "-")[:160]
        seen.add(url)
        items.append((ident, url, _priority(url)))

    for home in HOMES:
        try:
            r = http_get(home, ua=UA, sleep=0.3)
            if getattr(r, "status_code", 0) != 200:
                continue
            for href in re.findall(r'href=["\']([^"\']+)["\']', r.text or "", re.I):
                add(urljoin(home, href))
        except Exception as exc:
            log.info("home %s %s", home, exc)

    for prefix in (
        "www.parliament.go.ug/",
        "parliament.go.ug/",
        "www.parliament.go.ug/sites/default/files/",
        "www.parliament.go.ug/billtrack/",
        "parliament.go.ug/billtrack/",
        "publications.parliament.go.ug/",
        "judiciary.go.ug/files/downloads/Act",
        "www.judiciary.go.ug/files/downloads/Act",
        "judiciary.go.ug/files/downloads/",
        "www.judiciary.go.ug/files/downloads/",
        "ulrc.go.ug/",
        "www.ulrc.go.ug/",
        "mog.go.ug/",
        "www.mog.go.ug/",
        "justice.go.ug/",
        "www.justice.go.ug/",
        "www.mia.go.ug/",
        "mia.go.ug/",
        "www.gou.go.ug/",
        "gou.go.ug/",
        "www.statehouse.go.ug/",
        "gazette.go.ug/",
        "www.gazette.go.ug/",
        "ugandagazette.go.ug/",
        "publications.ulrc.go.ug/",
    ):
        try:
            hits = cdx_urls(
                prefix,
                limit=env_int("CDX_LIMIT", 400),
                match_type="prefix",
                extra_filters=["statuscode:200", "mimetype:application/pdf"],
            ) or []
        except Exception as exc:
            log.info("cdx %s %s", prefix, exc)
            hits = []
        for h in hits:
            orig = h.get("original") or ""
            try:
                length = int(h.get("length") or 0)
            except Exception:
                length = 0
            if length and length > MAX_PDF_BYTES:
                continue
            add(orig)

    items.sort(key=lambda t: (t[2], t[1]))
    log.info(
        "catalog %s (pri0=%s pri1=%s pri2=%s)",
        len(items),
        sum(1 for *_, p in items if p == 0),
        sum(1 for *_, p in items if p == 1),
        sum(1 for *_, p in items if p == 2),
    )
    return items


def rebuild_index() -> int:
    inst = ROOT / CC / "instruments"
    rows = []
    for p in sorted(inst.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        line = {k: rec.get(k) for k in INDEX_FIELDS if k not in ("path", "bytes", "article_count")}
        line["path"] = f"instruments/{p.name}"
        line["article_count"] = rec.get("article_count") or len(rec.get("documents") or [])
        line["bytes"] = p.stat().st_size
        line["id"] = rec.get("id") or p.stem
        rows.append(line)
    out = ROOT / CC / "index.jsonl"
    atomic_write(out, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    log.info("rebuilt index lines=%s", len(rows))
    return len(rows)


def _is_junk_record(rec: dict, name: str) -> bool:
    title = rec.get("title") or ""
    url = rec.get("source_url") or ""
    text_head = (rec.get("text") or "")[:2500]
    blob = f"{name}|{title}|{url}|{text_head}"
    if ACT_TEXT_RE.search(blob) or ACT_URL_RE.search(blob):
        # real Act/SI — keep even if URL path looks noisy
        if re.search(r"(?i)Act No\.|act_no|_act\.pdf|BE IT ENACTED|ARRANGEMENT OF SECTIONS|access.?to.?informatio|rules.?of.?procedure|SUPPLEMENT No", blob):
            return False
        if ACT_TEXT_RE.search(text_head):
            return False
    return bool(JUNK_RE.search(blob))


def prune_junk() -> int:
    inst = ROOT / CC / "instruments"
    removed = 0
    for p in list(inst.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if _is_junk_record(rec, p.name):
            p.unlink(missing_ok=True)
            removed += 1
            log.info("prune junk %s", p.name[:80])
    return removed



ART_ONLY = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+[0-9]+[A-Za-z]?)\b")


def split_ug_articles(text: str, rid: str, source_url: str, date=None) -> list:
    """Commonwealth ``1. Title.`` body split by default.

    Constitutions: prefer dense ``Article N``; vernacular without Articles stay unscored
    rather than inventing sections from bare numbers.
    """
    body = prefer_enacting_body(text)
    docs_sec = split_custom(body, rid, source_url, date, ART)
    docs_art = split_custom(body, rid, source_url, date, ART_ONLY)
    blob = f"{rid}|{source_url}"
    is_const = bool(re.search(r"(?i)constitution", blob)) and not bool(re.search(r"(?i)amm?endment", blob))
    if is_const:
        if len(docs_art) >= 20:
            return docs_art
        # Prefer sparse Article markers over inflated bare-number splits (TOC/schedules)
        if len(docs_art) >= 2 and len(docs_sec) > max(20, len(docs_art) * 3):
            return docs_art
        if len(docs_art) < 2:
            return docs_art  # vernacular / weak text layer - no num-dot padding
    # Non-constitutions: Article-only only when clearly denser and substantial
    if len(docs_art) >= 50 and len(docs_art) > len(docs_sec) * 1.2:
        return docs_art
    return docs_sec


def save_ug_instrument(*, ident: str, title: str, text: str, source_url: str, extra_meta: dict | None = None) -> bool:
    if not text or len(text) < 80:
        return False
    rid = slug_id(CC, ident)
    docs = split_ug_articles(text, rid, source_url, None)
    meta = {"fetch_method": (extra_meta or {}).get("fetch_method"), "article_split": "commonwealth-body"}
    if extra_meta:
        meta.update(extra_meta)
    rec = base_record(
        cc=CC,
        country=COUNTRY,
        language=LANG,
        ident=ident,
        title=title or first_title(text, ident),
        text=text,
        source_url=source_url,
        source_type=SOURCE_TYPE,
        license_text=LICENSE,
        collector="collect_ug.py",
        documents=docs,
        extra_meta=meta,
    )
    write_instrument(CC, rec)
    return True


def reprocess_existing() -> int:
    """Re-split articles on Act-like instruments with Commonwealth section regex."""
    inst = ROOT / CC / "instruments"
    improved = 0
    for p in sorted(inst.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        if len(text) < 200:
            continue
        name = p.name
        if _is_junk_record(rec, name):
            continue
        blob = f"{name}|{rec.get('title') or ''}|{rec.get('source_url') or ''}|{text[:2500]}"
        if not (ACT_TEXT_RE.search(blob) or ACT_URL_RE.search(blob)):
            continue
        rid = rec.get("id") or p.stem
        url = rec.get("source_url") or ""
        date = rec.get("date")
        docs = split_ug_articles(text, rid, url, date)
        old = int(rec.get("article_count") or len(rec.get("documents") or []) or 0)
        new = len(docs)
        if new <= old and old > 0:
            continue
        if new < 2 and old >= new:
            continue
        rec["documents"] = docs
        rec["article_count"] = new
        rec["article_extraction_status"] = "ok" if docs else "missing"
        meta = rec.get("metadata") or {}
        meta["article_reprocess"] = "collect_ug.py-commonwealth-sections"
        meta["article_split"] = "commonwealth-body"
        rec["metadata"] = meta
        # rewrite without appending index (rebuild later)
        atomic_write(p, json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
        improved += 1
        log.info("reprocess %s %s->%s", rid[:70], old, new)
    return improved


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 120)
    max_seconds = env_int("MAX_SECONDS", 2400)
    do_reprocess = os.environ.get("REPROCESS", "1") not in ("0", "false", "no")
    do_prune = os.environ.get("PRUNE_JUNK", "1") not in ("0", "false", "no")

    if do_reprocess:
        n = reprocess_existing()
        log.info("reprocess improved=%s", n)
    if do_prune:
        n = prune_junk()
        log.info("prune removed=%s", n)

    t_start = time.time()
    done = existing_ids(CC)
    have_urls = set()
    for p in (ROOT / CC / "instruments").glob("*.json"):
        try:
            u = _norm_url(json.loads(p.read_text(encoding="utf-8")).get("source_url") or "")
            if u:
                have_urls.add(u.lower())
        except Exception:
            pass

    ok = skip = fail = 0
    for ident, url, pri in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        nu = _norm_url(url).lower()
        if rid in done or nu in have_urls:
            skip += 1
            continue
        # after enough dense Acts, skip low-priority noise
        if pri >= 5 and ok >= max(15, max_new // 3):
            skip += 1
            continue
        got = fetch_official(url, ua=UA, min_text=200)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        # post-fetch junk / non-act filter for low-priority
        title = first_title(text, ident)
        blob = f"{ident}|{title}|{url}|{text[:2500]}"
        if pri >= 3 and JUNK_RE.search(blob) and not ACT_TEXT_RE.search(blob):
            skip += 1
            log.info("skip junk post-fetch %s", ident[:60])
            continue
        if pri >= 2 and not ACT_TEXT_RE.search(blob) and not ACT_URL_RE.search(url):
            # require Act-ish text for medium/low priority
            if not re.search(r"(?i)\b(ACT|STATUTE|ORDINANCE|CONSTITUTION|GAZETTE|REGULATION)\b", text[:3000]):
                skip += 1
                log.info("skip non-act post-fetch %s", ident[:60])
                continue
        if save_ug_instrument(
            ident=ident,
            title=title,
            text=text,
            source_url=_norm_url(url),
            extra_meta={"fetch_method": got.get("method"), "priority": pri},
        ):
            ok += 1
            done.add(rid)
            have_urls.add(nu)
            log.info("ok pri=%s %s method=%s chars=%s", pri, ident[:60], got.get("method"), len(text))
        else:
            fail += 1

    rebuild_index()
    # article totals for summary note
    arts = 0
    n_inst = 0
    for p in (ROOT / CC / "instruments").glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        n_inst += 1
        arts += int(rec.get("article_count") or len(rec.get("documents") or []) or 0)

    write_summary(
        CC,
        country=COUNTRY,
        source="Uganda official Acts/gazettes (parliament.go.ug / judiciary.go.ug / ulrc.go.ug / mog.go.ug)",
        source_urls=[
            "https://www.parliament.go.ug/",
            "https://judiciary.go.ug/",
            "https://ulrc.go.ug/",
            "https://www.mog.go.ug/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="catalog-backed incomplete (parliament/judiciary/ulrc Acts PDFs live + CDX; commonwealth section densify)",
        notes=(
            f"Official *.go.ug PDFs only. Commonwealth 1. Section split + enacting-body prefer. "
            f"instruments={n_inst} articles={arts}. Not ULII as gazette. Not AfricanLII. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s instruments=%s articles=%s", ok, skip, fail, n_inst, arts)


if __name__ == "__main__":
    main()
