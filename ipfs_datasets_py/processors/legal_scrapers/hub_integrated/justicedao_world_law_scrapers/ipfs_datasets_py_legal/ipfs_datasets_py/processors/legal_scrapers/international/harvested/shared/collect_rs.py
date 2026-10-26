#!/usr/bin/env python3
"""Serbia: Constitution + закони from Pravno-informacioni sistem / Službeni glasnik.

Official only (free register of in-force regulations, Zakon o objavljivanju…):
  https://www.pravno-informacioni-sistem.rs
  ELI (robots Allow): /eli/rep/* and /SLGlasnikPortal/eli/rep/*
  Constitution also from the President of the Republic (predsednik.rs) if PISRS is SPA.

Live PISRS pages are a Vue SPA shell from this host. Texts come from Wayback /
Common Crawl of those same official ELI URLs (archive_fallbacks on 429 / shell).
Not Paragraf Lex commercial. No WAF bypass.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "rs"
COUNTRY = "Serbia"
SOURCE_TYPE = "pisrs_sluzbeni_glasnik"
LICENSE = (
    "Official texts of the Republic of Serbia as published in the Pravno-informacioni "
    "sistem (JP Službeni glasnik). Unofficial consolidations in the free register; "
    "the authentic Službeni glasnik PDF prevails. Not legal advice. Not Paragraf Lex."
)
UA = DEFAULT_UA + " source=https://www.pravno-informacioni-sistem.rs/"
PORTAL = "https://www.pravno-informacioni-sistem.rs"
ELI_ZAKON = f"{PORTAL}/eli/rep/sgrs/skupstina/zakon/"
ELI_USTAV = [
    f"{PORTAL}/eli/rep/sgrs/skupstina/ustav/2006/98/1/reg",
    f"{PORTAL}/SlGlasnikPortal/eli/rep/sgrs/skupstina/ustav/2006/98/1/reg",
    f"{PORTAL}/eli/rep/sgrs/narodna-skupstina/ustav/2006/98/1/reg",
    "https://pravno-informacioni-sistem.rs/eli/rep/sgrs/skupstina/ustav/2006/98/1/reg",
]
PREDSEDNIK = "https://www.predsednik.rs/dokumenta/ustav-republike-srbije"
PREDSEDNIK_LAT = "https://www.predsednik.rs/lat/dokumenta/ustav-republike-srbije"
SLEEP = 0.5
log = logging.getLogger("rs")
ELI_ZAKON_RE = re.compile(
    r"/eli/rep/sgrs/(?:skupstina|narodna-skupstina)/zakon/(\d{4})/(\d+)/(\d+)",
    re.I,
)
ELI_USTAV_RE = re.compile(
    r"/eli/rep/sgrs/(?:skupstina|narodna-skupstina)/ustav/",
    re.I,
)
ART_RS = re.compile(
    r"(?im)^\s*((?:Члан|Član)\s+\d+[a-zа-я]?)\b"
)


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def pdf_to_text(raw: bytes) -> str:
    if not raw or raw[:4] != b"%PDF":
        return ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(raw)
            tmp.flush()
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", tmp.name, "-"],
                check=False, capture_output=True, timeout=180,
            )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", "replace").strip()
    except Exception as exc:
        log.warning("pdftotext: %s", exc)
    return ""


def is_spa(html: str) -> bool:
    if not html:
        return False
    if "pis-vue" in html or 'id=app>' in html or 'id="app">' in html:
        if len(html_to_text(html)) < 500:
            return True
    return af.is_spa_shell(html, html_to_text(html))


def get_official(url: str, *, timeout=(20, 90), retries: int = 3) -> dict:
    r = None
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=timeout, retries=retries)
    except Exception as exc:
        log.info("live fail %s: %s — archive of official URL", url, exc)
        res = af.fetch_with_fallbacks(url, try_http=False, try_cc=False)
        res.setdefault("retrieval", "archive")
        return res
    status = r.status_code
    body = r.content or b""
    ctype = (r.headers.get("content-type") or "").lower()
    text = ""
    if body[:4] == b"%PDF":
        return {
            "status": "success", "content": body, "text": "", "content_type": ctype or "application/pdf",
            "original_url": url, "http_status": 200, "method": "http", "final_url": r.url or url,
            "retrieval": "live",
        }
    if body and ("html" in ctype or "xml" in ctype or "text/" in ctype or not ctype):
        text = body.decode(r.encoding or "utf-8", "replace")
    if status == 429 or (status in (403, 503) and text and af.is_challenge(text, status)):
        log.info("HTTP %s %s — archive_fallbacks", status, url)
        res = af.fetch_with_fallbacks(url, try_http=False, try_cc=False)
        res.setdefault("retrieval", "archive")
        return res
    if status == 200 and text and (is_spa(text) or af.is_challenge(text, status)):
        log.info("SPA/challenge %s — archive_fallbacks of official URL", url)
        res = af.fetch_with_fallbacks(url, try_http=False, try_cc=False)
        res.setdefault("retrieval", "archive")
        return res
    if status == 200 and body:
        return {
            "status": "success", "content": body, "text": text, "content_type": ctype,
            "original_url": url, "http_status": status, "method": "http",
            "final_url": r.url or url, "retrieval": "live",
        }
    if status in (404, 410):
        return {"status": "error", "error": f"http_{status}", "http_status": status, "retrieval": "live"}
    res = af.fetch_with_fallbacks(url, try_http=False, try_cc=False)
    res.setdefault("retrieval", "archive")
    return res


def catalog_path() -> Path:
    return ROOT / CC / "raw" / "catalog.jsonl"


def load_catalog() -> list[dict]:
    p = catalog_path()
    if not p.exists() or p.stat().st_size < 40:
        return []
    items = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items


def save_catalog(items: list[dict]) -> None:
    atomic_write(catalog_path(), "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items))


def eli_work(url: str) -> Optional[str]:
    m = ELI_ZAKON_RE.search(url or "")
    if m:
        return f"zakon/{m.group(1)}/{m.group(2)}/{m.group(3)}"
    if ELI_USTAV_RE.search(url or "") or "ustav" in (url or "").lower():
        return "ustav/2006/98/1"
    return None


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 20:
        log.info("resume catalog n=%s", len(existing))
        return existing
    best: dict[str, dict] = {}
    prefixes = [
        f"{PORTAL}/eli/rep/sgrs/skupstina/zakon/",
        f"{PORTAL}/SlGlasnikPortal/eli/rep/sgrs/skupstina/zakon/",
        "https://pravno-informacioni-sistem.rs/eli/rep/sgrs/skupstina/zakon/",
        "https://pravno-informacioni-sistem.rs/SlGlasnikPortal/eli/rep/sgrs/skupstina/zakon/",
    ]
    recs: list[dict] = []
    for pfx in prefixes:
        chunk = af.search_wayback_machine(
            pfx, match_type="prefix", limit=1500,
            from_date="20180101", to_date="20231231",
        )
        log.info("cdx 2018-2023 %s n=%s", pfx, len(chunk))
        recs.extend(chunk)
        chunk2 = af.search_wayback_machine(pfx, match_type="prefix", limit=800)
        log.info("cdx all %s n=%s", pfx, len(chunk2))
        recs.extend(chunk2)
    for rec in recs:
        orig = rec.get("original") or ""
        work = eli_work(orig)
        if not work or not work.startswith("zakon/"):
            continue
        ts = rec.get("timestamp") or ""
        prev = best.get(work)
        mime = (rec.get("mimetype") or "").lower()
        try:
            ln = int(rec.get("length") or 0)
        except Exception:
            ln = 0
        year = int(ts[:4]) if ts[:4].isdigit() else 0
        era = 2 if 2018 <= year <= 2023 else (0 if year >= 2024 else 1)
        htmlish = 1 if "html" in mime or "xml" in mime or not mime else 0
        score = (era, htmlish, ln, ts)
        prev_score = tuple(prev.get("score") or (0, 0, 0, "")) if prev else (-1, 0, 0, "")
        if prev is None or score > prev_score:
            url = orig.split("?")[0].rstrip("/")
            if not url.endswith("/reg") and "/eli/" in url:
                if re.search(r"/\d+$", url):
                    url = url + "/reg"
            best[work] = {
                "work": work,
                "url": url if url.startswith("http") else urljoin(PORTAL, url),
                "title": f"Закон {work}",
                "document_type": "statute",
                "wayback_ts": ts,
                "cdx_original": orig,
                "score": list(score),
            }
    # Constitution first
    ustav_ts = "20190901000000"
    for pfx in ELI_USTAV:
        uchunk = af.search_wayback_machine(
            pfx, limit=40, from_date="20180101", to_date="20231231",
        )
        for rec in uchunk:
            ts = rec.get("timestamp") or ""
            if ts and ts < ustav_ts or (ts and int(ts[:4]) <= 2022 and ts > ustav_ts and int((ustav_ts or "0")[:4]) >= 2019):
                # keep a mid-era HTML capture
                mime = (rec.get("mimetype") or "").lower()
                if "html" in mime or not mime:
                    ustav_ts = ts
                    break
        if uchunk:
            break
    best["ustav/2006/98/1"] = {
        "work": "ustav/2006/98/1",
        "url": ELI_USTAV[0],
        "title": "Устав Републике Србије",
        "document_type": "constitution",
        "fallbacks": ELI_USTAV[1:] + [PREDSEDNIK, PREDSEDNIK_LAT],
        "wayback_ts": ustav_ts,
    }
    items = list(best.values())
    items.sort(key=lambda x: (0 if x.get("document_type") == "constitution" else 1, x.get("work") or ""))
    save_catalog(items)
    log.info("catalog n=%s (incl constitution)", len(items))
    return items


def extract_body(html: str) -> str:
    if not html:
        return ""
    if is_spa(html):
        return ""
    chunk = html
    m = re.search(r"(<(?:h1|div)[^>]*(?:class|id)=\"[^\"]*(?:act|reg|tekst|content)[^\"]*\"[^>]*>)", html, re.I)
    if m:
        chunk = html[m.start(): m.start() + 1_200_000]
    text = html_to_text(chunk)
    if len(text) < 200:
        text = html_to_text(html)
    return text.strip()


def split_rs(text: str, law_id: str, source_url: str, date: Optional[str], constitution: bool) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(ART_RS.finditer(text or ""))
    if len(matches) < 2:
        return []
    out, seen = [], set()
    for i, m in enumerate(matches):
        chunk = text[m.start(): (matches[i + 1].start() if i + 1 < len(matches) else len(text))].strip()
        if len(chunk) < 12:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9а-я]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        out.append({
            "id": doc_id, "title": chunk.split("\n", 1)[0][:200], "text": chunk,
            "date_filed": date, "document_number": num, "source_url": source_url,
            "record_type": "article", "article_number": num, "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "pisrs"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def title_from(html: str, text: str, fallback: str) -> str:
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html or "", re.I | re.S)
    if h1:
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h1.group(1))).strip()
        if t and t.lower() not in ("правно-информациони систем рс",):
            return t[:240]
    m = re.search(r"(?m)^\s*(УСТАВ РЕПУБЛИКЕ СРБИЈЕ|ЗАКОН[^\n]{0,160})", text or "")
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:240]
    return fallback


def fetch_one(it: dict, done: set[str]) -> str:
    work = it["work"]
    ident = "rs-" + work.replace("/", "-")
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    urls = [it["url"]] + list(it.get("fallbacks") or [])
    html, text, retrieval, used = "", "", "fail", it["url"]
    body = b""
    ts = it.get("wayback_ts")
    # Prefer dated Wayback of official ELI (live portal is a Vue shell).
    for u in urls:
        if "/eli/" in u or "pravno-informacioni-sistem" in u:
            res = af.get_wayback_content(u, timestamp=ts)
            body = res.get("content") or b""
            html = res.get("text") or ""
            retrieval = "archive"
            used = res.get("wayback_url") or u
            if body[:4] == b"%PDF":
                text = pdf_to_text(body)
            else:
                text = extract_body(html)
            if len(text) >= 200:
                break
            html, text = "", ""
    if len(text) < 200:
        for u in urls:
            if "/eli/" not in u and "pravno-informacioni-sistem" not in u:
                res = get_official(u)
                body = res.get("content") or b""
                html = res.get("text") or ""
                retrieval = res.get("retrieval") or res.get("method") or "live"
                used = res.get("final_url") or res.get("wayback_url") or u
                if body[:4] == b"%PDF":
                    text = pdf_to_text(body)
                    if len(text) >= 200:
                        break
                text = extract_body(html)
                if len(text) >= 200:
                    break
                html, text = "", ""
                continue
            recs = af.search_wayback_machine(
                u, limit=15, from_date="20180101", to_date="20231231",
            )
            recs.sort(key=lambda r: int(r.get("length") or 0), reverse=True)
            for rec in recs[:4]:
                orig = rec.get("original") or u
                rts = rec.get("timestamp")
                res = af.get_wayback_content(orig, timestamp=rts)
                body = res.get("content") or b""
                html = res.get("text") or ""
                retrieval = "archive"
                used = res.get("wayback_url") or orig
                if body[:4] == b"%PDF":
                    text = pdf_to_text(body)
                else:
                    text = extract_body(html)
                if len(text) >= 200:
                    break
            if len(text) >= 200:
                break
    min_chars = 5000 if (it.get("document_type") == "constitution" or "ustav" in work) else 200
    if len(text) < min_chars:
        log_failure(CC, {"id": rid, "url": it["url"], "status": "failed", "reason": "empty_or_spa", "chars": len(text)})
        return "fail"
    is_const = it.get("document_type") == "constitution" or "ustav" in work
    title = title_from(html, text, it.get("title") or ident)
    date = "2006-11-08" if is_const else None
    ym = re.search(r"zakon/(\d{4})/", work)
    if ym and not date:
        date = f"{ym.group(1)}-01-01"
    docs = split_rs(text, rid, used, date, constitution=is_const)
    rec = base_record(
        cc=CC, country=COUNTRY, language="sr", ident=ident, title=title,
        text=text, source_url=it["url"], source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_rs.py", date=date, official_identifier=work,
        document_type="constitution" if is_const else "statute",
        law_status="current", is_current=True, documents=docs, eli=it["url"] if "/eli/" in it["url"] else None,
        extra_meta={
            "discovery": {"method": "wayback_cdx_official_eli", "work": work, "cdx_original": it.get("cdx_original")},
            "text_extraction": {"source": "official", "backend": "html-or-pdf"},
            "retrieval": {"method": retrieval, "used_url": used},
        },
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def write_progress(items, counters, coverage, extra=""):
    notes = (
        "Constitution + закони from Pravno-informacioni sistem RS (JP Službeni glasnik). "
        "robots.txt Allow /eli/rep/* and /SLGlasnikPortal/eli/rep/*. Live portal is a Vue "
        "SPA from this host; full texts from Wayback/Common Crawl of those official ELI URLs "
        "(archive_fallbacks on 429/shell). Constitution ELI 2006/98 plus predsednik.rs fallback. "
        "Not Paragraf Lex. Free register consolidations; authentic Službeni glasnik prevails. "
        + extra
    )
    write_summary(
        CC, country=COUNTRY,
        source="Pravno-informacioni sistem RS / JP Službeni glasnik",
        source_urls=[PORTAL + "/", ELI_ZAKON, ELI_USTAV[0], PREDSEDNIK],
        license_text=LICENSE, discovered=len(items), fetched=counters["ok"],
        skipped=counters["skip"], failed=counters["fail"], coverage=coverage, notes=notes,
    )


def main():
    setup()
    t0 = utcnow()
    items = discover()
    counters = {"ok": 0, "skip": 0, "fail": 0}
    done = existing_ids(CC)
    log.info("queue n=%s already=%s", len(items), len(done))
    for n, it in enumerate(items, 1):
        try:
            st = fetch_one(it, done)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"url": it.get("url"), "status": "failed", "reason": repr(exc)})
        counters[st] = counters.get(st, 0) + 1
        if n % 15 == 0 or n == len(items):
            log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items),
                     counters["ok"], counters["skip"], counters["fail"])
            write_progress(items, counters, "catalog-backed incomplete")
    cov = "snapshot"
    if counters["ok"] + counters["skip"] >= 1:
        cov = "official-eli-archive-snapshot"
    if counters["fail"] == 0 and counters["ok"] + counters["skip"] >= len(items):
        cov = "full-eli-zakon-catalog"
    write_progress(items, counters, cov, extra=f"Started {t0}.")
    atomic_write(ROOT / CC / "raw" / "stats.json", json.dumps({
        "discovered": len(items), **counters, "coverage": cov,
        "started": t0, "finished": utcnow(),
    }, indent=2) + "\n")
    log.info("done %s", counters)


if __name__ == "__main__":
    main()
