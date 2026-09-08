#!/usr/bin/env python3
"""Bulgaria: State Gazette via Wayback/Common Crawl (live TLS fails)."""
from __future__ import annotations
import logging, os, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC, COUNTRY, SOURCE_TYPE = "bg", "Bulgaria", "dv_parliament"
LICENSE = ("State Gazette of the Republic of Bulgaria (dv.parliament.bg). "
           "Live TLS often fails; corpus uses Wayback Machine snapshots of official URLs only.")
log = logging.getLogger("bg")
ANCHORS = [102043, 104756, 123922, 130338, 196116, 197524, 197543, 109484, 120000, 150000, 180000, 200000, 210000, 220000]


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def cdx_ids(limit: int = 400):
    out, seen = [], set()
    try:
        hits = af.search_wayback_machine("dv.parliament.bg/DVWeb/showMaterialDV.jsp", limit=limit, match_type="prefix", collapse="")
    except Exception as exc:
        log.info("cdx err: %s", exc); hits = []
    for h in hits or []:
        orig = h.get("original") or ""
        m = re.search(r"idMat=(\d{4,7})\b", orig)
        if not m: continue
        i = int(m.group(1))
        if i in seen: continue
        seen.add(i)
        out.append((i, f"https://dv.parliament.bg/DVWeb/showMaterialDV.jsp?idMat={i}", h.get("timestamp") or ""))
    log.info("cdx unique idMat=%s", len(out))
    return out


def window_ids(anchors, radius=40):
    seen, out = set(), []
    for a in anchors:
        for i in range(max(1, a - radius), a + radius + 1):
            if i in seen: continue
            seen.add(i)
            out.append((i, f"https://dv.parliament.bg/DVWeb/showMaterialDV.jsp?idMat={i}", ""))
    return out


def archive_text(url: str, ts: str = ""):
    try:
        w = af.get_wayback_content(url, timestamp=ts or None)
        if w.get("status") == "success":
            raw = w.get("text") or ""
            if not raw and isinstance(w.get("content"), bytes):
                raw = w["content"].decode("utf-8", "replace")
            text = html_to_text(raw) if "<" in (raw[:300] or "") else raw
            if len(text) >= 80:
                return text, w.get("url") or url
    except Exception as exc:
        log.info("wb fail %s: %s", url[-40:], exc)
    return "", url


def main():
    setup(); t0 = utcnow()
    max_new = int(os.environ.get("MAX_NEW", "80") or 80)
    max_seconds = int(os.environ.get("MAX_SECONDS", "1800") or 1800)
    radius = int(os.environ.get("ID_RADIUS", "40") or 40)
    t_start = time.time()
    done = existing_ids(CC)
    anchors = []
    for pth in (ROOT / CC / "instruments").glob("*.json"):
        m = re.search(r"(\d{5,7})", pth.stem)
        if m: anchors.append(int(m.group(1)))
    # only a few speculative mid-range anchors known to have snapshots
    anchors.extend([102043, 104756, 123922, 196116, 197524])
    anchors = sorted(set(anchors))
    # Prefer CDX-proven URLs only (neighbor windows mostly miss in Wayback)
    items = cdx_ids(2000)
    if len(items) < 30:
        items = items + window_ids(anchors, radius=min(5, radius))
    seen, uniq = set(), []
    for i, u, ts in items:
        if i in seen: continue
        seen.add(i); uniq.append((i, u, ts))
    log.info("candidates=%s anchors=%s done=%s", len(uniq), len(anchors), len(done))
    ok = skip = fail = 0
    for i, url, ts in uniq:
        if max_new and ok >= max_new: break
        if max_seconds and (time.time() - t_start) > max_seconds: break
        rid = slug_id(CC, str(i))
        if rid in done:
            skip += 1; continue
        text, src = archive_text(url, ts)
        if len(text) < 80:
            fail += 1
            log_failure(CC, {"identifier": str(i), "source_url": url, "status": "failed", "reason": "empty_archive"})
            continue
        title = f"Държавен вестник idMat={i}"
        for line in text.splitlines():
            if len(line.strip()) > 15:
                title = line.strip()[:240]; break
        rec = base_record(
            cc=CC, country=COUNTRY, language="bg", ident=str(i), title=title, text=text,
            source_url=src, source_type=SOURCE_TYPE, license_text=LICENSE,
            collector="bg-dv-wayback", eli=None, date=None, official_identifier=str(i),
            document_type="gazette_act", law_status="unknown", is_current=None,
            extra_meta={"discovery": {"method": "wayback_cdx_and_anchor_windows", "idMat": i, "original_url": url}},
        )
        write_instrument(CC, rec)
        done.add(rid); ok += 1
        log.info("ok idMat=%s chars=%s ok=%s fail=%s", i, len(text), ok, fail)
    notes = ("Live dv.parliament.bg TLS fails (SSLEOF). Official showMaterialDV.jsp via Wayback/CC. "
             f"Anchor windows radius={radius}.")
    write_summary(CC, country=COUNTRY, source="Държавен вестник (Wayback of official URLs)",
                  source_urls=["https://dv.parliament.bg/", "https://web.archive.org/"],
                  license_text=LICENSE, discovered=len(uniq), fetched=ok, skipped=skip, failed=fail,
                  coverage="shard", notes=notes, last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s fail=%s skip=%s", len(uniq), ok, fail, skip)


if __name__ == "__main__":
    main()
