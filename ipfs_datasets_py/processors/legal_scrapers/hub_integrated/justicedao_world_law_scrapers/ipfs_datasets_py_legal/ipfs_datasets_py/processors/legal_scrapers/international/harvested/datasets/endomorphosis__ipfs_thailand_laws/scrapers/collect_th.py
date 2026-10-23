#!/usr/bin/env python3
"""Thailand: พระราชบัญญัติ from Royal Gazette and Krisdika / OCS (official).

Official only (not LeadX / commercial):
  https://www.ratchakitcha.soc.go.th     ราชกิจจานุเบกษา (authentic gazette)
  https://ratchakitcha.soc.go.th
  https://www.krisdika.go.th             Office of the Council of State (if official)
  https://ocs.go.th  https://searchlaw.ocs.go.th

Acts / พระราชบัญญัติ first. Royal Gazette prevails. Not legal advice.
Live Cloudflare 403/429 uses archive_fallbacks of official URLs. No WAF bypass.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "th"
COUNTRY = "Thailand"
SOURCE_TYPE = "royal_gazette_krisdika"
LICENSE = (
    "Official Thai legislative texts from the Royal Gazette (ราชกิจจานุเบกษา, "
    "ratchakitcha.soc.go.th) and the Office of the Council of State "
    "(สำนักงานคณะกรรมการกฤษฎีกา; ocs.go.th / krisdika.go.th / searchlaw.ocs.go.th). "
    "Royal Gazette authentic text prevails. Not LeadX. Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.ratchakitcha.soc.go.th/"
RATCHA = "https://www.ratchakitcha.soc.go.th/"
RATCHA2 = "https://ratchakitcha.soc.go.th/"
OCS = "https://ocs.go.th/"
SEARCHLAW = "https://searchlaw.ocs.go.th/"
KRISDIKA = "https://www.krisdika.go.th/"
WORKERS = 3
SLEEP = 0.5
MIN_TEXT = 120
log = logging.getLogger("th")

ART_TH = re.compile(r"(?m)^\s*((?:มาตรา|มาตราที่)\s+\d+[/\-ก-ฮA-Za-z]*)\b")
ACT_HINT = re.compile(r"พระราชบัญญัติ|พระราชกำหนด|รัฐธรรมนูญ|ประมวลกฎหมาย")
PDF_HREF = re.compile(r"https?://(?:www\.)?ratchakitcha\.soc\.go\.th/documents/\d+\.pdf", re.I)


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
                check=False, capture_output=True, timeout=240,
            )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", "replace").strip()
    except Exception as exc:
        log.warning("pdftotext failed: %s", exc)
    return ""


def split_th(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(ART_TH.finditer(text or ""))
    if len(matches) < 2:
        return []
    out, seen = [], set()
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if len(chunk) < 8:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9ก-๙]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            doc_id = f"{doc_id}-{len(out)+1}"[:180]
        seen.add(doc_id)
        out.append({
            "id": doc_id,
            "title": chunk.split("\n", 1)[0][:200],
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "th_collector"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def live_get(url: str, *, accept: str = "text/html, application/json, */*", timeout=(20, 90), retries: int = 2):
    try:
        return http_get(
            url, ua=UA, sleep=SLEEP, timeout=timeout, retries=retries,
            headers={"Accept": accept, "Accept-Language": "th,en;q=0.8"},
        )
    except Exception as exc:
        log.info("live fail %s: %s", url, exc)
        return None


def get_html(url: str) -> tuple[str, str]:
    r = live_get(url)
    if r is not None and r.status_code == 200 and r.text and not af.is_challenge(r.text, r.status_code):
        if not af.is_spa_shell(r.text, html_to_text(r.text)):
            return r.text, "live"
        # SPA shell: still return; caller may parse assets / use archives
        if len(html_to_text(r.text)) >= 400:
            return r.text, "live"
        log.info("spa shell %s — archive fallback", url)
    if r is not None and r.status_code in (403, 429, 503) or (r is not None and af.is_challenge(r.text or "", r.status_code)):
        res = af.fetch_with_fallbacks(url, try_archive_is=True, try_http=False, try_cc=True)
        if res.get("status") == "success":
            text = res.get("text") or ""
            if not text and res.get("content"):
                text = res["content"].decode("utf-8", "replace")
            return text, res.get("method") or "archive"
    return "", "failed"


def get_bytes(url: str, wayback_ts: Optional[str] = None) -> tuple[bytes, str]:
    r = live_get(url, accept="application/pdf, application/octet-stream, */*", timeout=(20, 180), retries=1)
    if r is not None and r.status_code == 200 and r.content and r.content[:4] == b"%PDF":
        return r.content, "live_pdf"
    if r is not None and r.status_code in (403, 429, 503) or r is None or (r is not None and af.is_challenge(r.text or "", r.status_code)):
        if wayback_ts:
            res = af.get_wayback_content(url, timestamp=wayback_ts)
            if res.get("status") == "success" and res.get("content"):
                return res["content"], "wayback"
        res = af.fetch_with_fallbacks(url, wayback_ts=wayback_ts, try_archive_is=False, try_http=False, try_cc=True)
        if res.get("status") == "success" and res.get("content"):
            return res["content"], res.get("method") or "archive"
    return b"", "failed"


def add_item(items: list, seen: set, row: dict) -> None:
    url = (row.get("url") or "").split("?")[0]
    if not url or url in seen:
        return
    seen.add(url)
    items.append(row)
    append_catalog(CC, {k: v for k, v in row.items() if k != "cc_record"})


def discover_live_ocs(items: list, seen: set) -> None:
    for url in (
        "https://ocs.go.th/searchlaw-law",
        "https://ocs.go.th/searchlaw",
        "https://searchlaw.ocs.go.th/",
        "https://searchlaw.ocs.go.th/council-of-state/",
        "https://ratchakitcha.soc.go.th/",
        "https://www.ratchakitcha.soc.go.th/",
    ):
        html, method = get_html(url)
        log.info("probe %s method=%s bytes=%s", url, method, len(html or ""))
        if not html:
            continue
        for pdf in PDF_HREF.findall(html):
            add_item(items, seen, {
                "kind": "gazette_pdf", "url": pdf, "source": "live_html", "retrieval_hint": method,
            })
        # searchlaw asset / API hints
        for href in re.findall(r'(?:src|href)="([^"]+)"', html):
            if any(x in href.lower() for x in ("main.", "runtime", "config", "environment")):
                absu = urljoin(url, href)
                js, _ = get_html(absu) if absu.endswith((".js", ".json")) else ("", "")
                if js:
                    for api in re.findall(r"https?://[a-z0-9._/-]*(?:api|law|search)[a-z0-9._/-]*", js, re.I):
                        log.info("js api hint %s", api[:180])
        for href in re.findall(r'href="([^"]+)"', html):
            if "พระราชบัญญัติ" in href or "prb" in href.lower() or "/law" in href.lower():
                absu = urljoin(url, href)
                if "ocs.go.th" in absu or "krisdika" in absu or "ratchakitcha" in absu or "searchlaw" in absu:
                    add_item(items, seen, {
                        "kind": "ocs_html", "url": absu, "source": "live_html", "retrieval_hint": method,
                    })


def discover_wayback(items: list, seen: set) -> None:
    queries = [
        {"url": "ratchakitcha.soc.go.th/documents/", "match_type": "prefix", "limit": 1500},
        {"url": "www.ratchakitcha.soc.go.th/documents/", "match_type": "prefix", "limit": 1500},
        {"url": "ratchakitcha.soc.go.th/documents/*.pdf", "limit": 800},
        {"url": "www.krisdika.go.th/th/web/guest/law*", "limit": 400},
        {"url": "www.krisdika.go.th/librarian/get*", "limit": 600},
        {"url": "searchlaw.ocs.go.th/*", "limit": 200},
    ]
    for q in queries:
        try:
            recs = af.search_wayback_machine(
                q["url"], limit=q.get("limit", 400),
                match_type=q.get("match_type"),
                extra_filters=q.get("extra_filters"),
            )
        except Exception as exc:
            log.warning("cdx %s: %s", q["url"], exc)
            continue
        log.info("cdx %s n=%s", q["url"], len(recs))
        for rec in recs:
            orig = rec.get("original") or ""
            mime = (rec.get("mimetype") or "").lower()
            if not orig:
                continue
            if orig.startswith("http://"):
                orig = "https://" + orig[len("http://"):]
            orig = orig.replace(":80/", "/")
            kind = "gazette_pdf" if (orig.lower().endswith(".pdf") or "pdf" in mime or "/documents/" in orig) else "html"
            add_item(items, seen, {
                "kind": kind,
                "url": orig.split("?")[0],
                "source": "wayback_cdx",
                "cdx_ts": rec.get("timestamp"),
                "wayback_url": rec.get("wayback_url"),
                "mimetype": mime,
            })


def discover() -> list[dict]:
    cat = ROOT / CC / "raw" / "catalog.jsonl"
    items: list[dict] = []
    seen = set()
    if cat.exists() and cat.stat().st_size > 500:
        with cat.open(encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                url = (row.get("url") or "").split("?")[0]
                if url and url not in seen:
                    seen.add(url)
                    items.append(row)
        if len(items) > 20:
            log.info("resume catalog %s", len(items))
            return items
    discover_live_ocs(items, seen)
    discover_wayback(items, seen)
    log.info("catalog discovered %s", len(items))
    return items


def looks_like_act(text: str, title: str = "") -> bool:
    head = (title + "\n" + (text or "")[:2500])
    return bool(ACT_HINT.search(head))


def fetch_one(it: dict, done: set[str]) -> str:
    url = it.get("url") or ""
    ident = url.replace("https://", "").replace("http://", "")
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    kind = it.get("kind") or ""
    text = ""
    method = "failed"
    title = ""
    used = url
    if kind == "gazette_pdf" or url.lower().endswith(".pdf"):
        raw, method = get_bytes(url, wayback_ts=it.get("cdx_ts"))
        text = pdf_to_text(raw) if raw else ""
    else:
        html, method = get_html(url)
        if not html and it.get("cdx_ts"):
            res = af.get_wayback_content(url, timestamp=it.get("cdx_ts"))
            if res.get("status") == "success":
                html, method = res.get("text") or "", "wayback"
                if not html and res.get("content") and res["content"][:4] == b"%PDF":
                    text, method = pdf_to_text(res["content"]), "wayback_pdf"
        if html and not text:
            title_m = re.search(r"<title>\s*([^<]+)", html, re.I)
            title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else ""
            text = html_to_text(html)
            for href in re.findall(r'href="([^"]+\.pdf)"', html, re.I):
                pdfu = urljoin(url, href)
                raw, pm = get_bytes(pdfu, wayback_ts=it.get("cdx_ts"))
                pt = pdf_to_text(raw) if raw else ""
                if len(pt) > len(text):
                    text, method, used = pt, pm, pdfu
    if len(text) < MIN_TEXT:
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": "empty_text"})
        return "fail"
    if not looks_like_act(text, title):
        # keep constitutions / codes too; drop gazette notices
        if not re.search(r"มาตรา\s+\d+", text[:8000]):
            log_failure(CC, {"identifier": ident, "source_url": url, "status": "skipped", "reason": "not_act"})
            return "skip"
    if not title:
        first = text.strip().split("\n", 1)[0][:180]
        title = first or ident
    date = None
    dm = re.search(r"(20\d{2}|25\d{2})[./-](\d{1,2})[./-](\d{1,2})", text[:2000])
    if dm:
        y, mo, d = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))
        if y > 2400:
            y -= 543
        date = f"{y:04d}-{mo:02d}-{d:02d}"
    docs = split_th(text, rid, used, date)
    rec = base_record(
        cc=CC, country=COUNTRY, language="th", ident=ident,
        title=title, text=text, source_url=used, source_type=SOURCE_TYPE,
        license_text=LICENSE, collector="th-ratchakitcha-ocs",
        date=date, official_identifier=title[:120],
        document_type="statute", law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "discovery": {
                "method": it.get("source") or "mixed",
                "retrieval": method,
                "cdx_ts": it.get("cdx_ts"),
                "wayback_url": it.get("wayback_url"),
            },
        },
        extra_fields={
            "canonical_title": title,
            "citation": title,
            "canonical_document_url": used,
            "status_source": "royal_gazette",
            "status_note": "Royal Gazette authentic text prevails. Not LeadX.",
        },
    )
    rec["id"] = rid
    rec["languages"] = ["th"]
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    log.info("queue %s already_done=%s", len(items), len(done))
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch_one, it, done) for it in items]
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"status": "failed", "reason": repr(exc)})
            ok += st == "ok"
            skip += st == "skip"
            fail += st == "fail"
            if n % 30 == 0 or n == len(items):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items), ok, skip, fail)
                write_summary(
                    CC, country=COUNTRY,
                    source="Royal Gazette + OCS/Krisdika",
                    source_urls=[RATCHA, RATCHA2, OCS, SEARCHLAW, KRISDIKA],
                    license_text=LICENSE, discovered=len(items), fetched=ok,
                    skipped=skip, failed=fail, coverage="catalog-backed incomplete",
                    notes="พระราชบัญญัติ first. Royal Gazette prevails. Not LeadX.",
                    last_run=utcnow(),
                )
    coverage = "full" if fail == 0 and ok + skip >= len(items) and items else "catalog-backed incomplete"
    notes = (
        f"พระราชบัญญัติ from Royal Gazette / OCS official URLs (catalog {len(items)}). "
        "Live ratchakitcha is Cloudflare-challenged; archive_fallbacks of official URLs. "
        "Not LeadX. Royal Gazette prevails. "
        f"Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="Royal Gazette + OCS/Krisdika",
        source_urls=[RATCHA, RATCHA2, OCS, SEARCHLAW, KRISDIKA],
        license_text=LICENSE, discovered=len(items), fetched=ok,
        skipped=skip, failed=fail, coverage=coverage, notes=notes,
        last_run=utcnow(), extra=f"started {t0}",
    )
    (ROOT / CC / "logs" / "DONE").write_text(json.dumps({
        "ok": ok, "skip": skip, "fail": fail, "discovered": len(items), "coverage": coverage,
    }, indent=2) + "\n", encoding="utf-8")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, coverage)


if __name__ == "__main__":
    main()
