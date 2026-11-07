#!/usr/bin/env python3
"""Bulgaria: State Gazette via Wayback of official URLs (live TLS fails)."""
from __future__ import annotations
import json, logging, os, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC, COUNTRY, SOURCE_TYPE = "bg", "Bulgaria", "dv_parliament"
LICENSE = ("State Gazette of the Republic of Bulgaria (dv.parliament.bg). "
           "Live TLS often fails; corpus uses Wayback Machine snapshots of official URLs only.")
log = logging.getLogger("bg")
CAPTCHA_MARKERS = ("Validation request", "User validation required", "text you see in the image")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def is_captcha(text: str) -> bool:
    t = text or ""
    return any(m in t for m in CAPTCHA_MARKERS)


def is_plausible(text: str) -> bool:
    if not text or len(text) < 80 or is_captcha(text):
        return False
    # Official gazette pages usually mention Държавен вестник or structural markers
    if "Държавен вестник" in text or "брой:" in text or "Официален" in text:
        return True
    # Accept long non-captcha bodies (some annexes)
    return len(text) >= 400


def known_fail_ids() -> set[str]:
    p = ROOT / CC / "failures.jsonl"
    out = set()
    if not p.exists():
        return out
    for line in p.open(encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        ident = str(d.get("identifier") or "")
        if ident.isdigit():
            out.add(ident)
    return out


def quarantine_ids() -> list[int]:
    q = ROOT / CC / "raw" / "captcha_quarantine"
    out = []
    if not q.exists():
        return out
    for p in q.glob("*.json"):
        m = re.search(r"(\d{5,7})", p.stem)
        if m:
            out.append(int(m.group(1)))
    return out


def cdx_ids(limit: int = 400) -> list[tuple[int, str, str]]:
    out, seen = [], set()
    try:
        hits = af.search_wayback_machine(
            "dv.parliament.bg/DVWeb/showMaterialDV.jsp?idMat=",
            limit=limit, match_type="prefix", collapse="",
        )
    except Exception as exc:
        log.info("cdx err: %s", exc)
        hits = []
    for h in hits or []:
        orig = h.get("original") or ""
        m = re.search(r"idMat=(\d{4,7})\b", orig)
        if not m:
            continue
        i = int(m.group(1))
        if i in seen:
            continue
        seen.add(i)
        # Prefer https canonical URL; keep CDX timestamp
        out.append((i, f"https://dv.parliament.bg/DVWeb/showMaterialDV.jsp?idMat={i}", h.get("timestamp") or ""))
    log.info("cdx unique idMat=%s", len(out))
    return out


def cdx_timestamp_for(url: str) -> str:
    """Look up a concrete snapshot timestamp (avoids /2id_/ captcha interstitial)."""
    try:
        hits = af.search_wayback_machine(url, limit=5, collapse="")
    except Exception:
        return ""
    for h in hits or []:
        ts = h.get("timestamp") or ""
        if ts:
            return ts
    return ""


def archive_text(url: str, ts: str = "") -> tuple[str, str]:
    """Fetch Wayback snapshot; prefer CDX timestamp from catalog (avoid CDX storms)."""
    timestamps = []
    if ts:
        timestamps.append(ts)
    # One lookup only if no catalog timestamp
    if not timestamps:
        looked = cdx_timestamp_for(url)
        if looked:
            timestamps.append(looked)
    for tsv in timestamps:
        try:
            w = af.get_wayback_content(url, timestamp=tsv)
            if w.get("status") != "success":
                continue
            raw = w.get("text") or ""
            if not raw and isinstance(w.get("content"), bytes):
                raw = w["content"].decode("utf-8", "replace")
            text = html_to_text(raw) if "<" in (raw[:300] or "") else raw
            if is_plausible(text):
                return text, w.get("url") or url
            if is_captcha(text):
                log.info("captcha skip ts=%s %s", tsv, url[-40:])
        except Exception as exc:
            log.info("wb fail %s: %s", url[-40:], exc)
    return "", url


def window_candidates(anchors: list[int], radius: int) -> list[tuple[int, str, str]]:
    seen, out = set(), []
    for a in anchors:
        for i in range(max(1, a - radius), a + radius + 1):
            if i in seen:
                continue
            seen.add(i)
            out.append((i, f"https://dv.parliament.bg/DVWeb/showMaterialDV.jsp?idMat={i}", ""))
    return out


def main():
    setup()
    t0 = utcnow()
    max_new = int(os.environ.get("MAX_NEW", "80") or 80)
    max_seconds = int(os.environ.get("MAX_SECONDS", "1800") or 1800)
    radius = int(os.environ.get("ID_RADIUS", "8") or 8)
    skip_known_fail = os.environ.get("SKIP_KNOWN_FAIL", "1") != "0"
    t_start = time.time()
    done = existing_ids(CC)
    failed = known_fail_ids() if skip_known_fail else set()
    anchors = []
    for pth in (ROOT / CC / "instruments").glob("*.json"):
        m = re.search(r"(\d{5,7})", pth.stem)
        if m:
            anchors.append(int(m.group(1)))
    anchors.extend(quarantine_ids())
    anchors.extend([102043, 104756, 123922, 196116, 197524, 48899, 139569, 235299])
    anchors = sorted(set(anchors))

    # Priority: CDX hits with timestamps first (best Wayback success), then windows, quarantine last
    items: list[tuple[int, str, str]] = []
    items.extend(cdx_ids(int(os.environ.get("CDX_LIMIT", "2500") or 2500)))
    items.extend(window_candidates(anchors, radius=radius))
    for i in quarantine_ids():
        items.append((i, f"https://dv.parliament.bg/DVWeb/showMaterialDV.jsp?idMat={i}", ""))

    seen, uniq = set(), []
    for i, u, ts in items:
        if i in seen:
            continue
        seen.add(i)
        uniq.append((i, u, ts))
    log.info("candidates=%s anchors=%s done=%s known_fail=%s", len(uniq), len(anchors), len(done), len(failed))

    ok = skip = fail = 0
    for i, url, ts in uniq:
        if max_new and ok >= max_new:
            break
        if max_seconds and (time.time() - t_start) > max_seconds:
            break
        rid = slug_id(CC, str(i))
        if rid in done:
            skip += 1
            continue
        if str(i) in failed and i not in set(quarantine_ids()):
            skip += 1
            continue
        text, src = archive_text(url, ts)
        if not is_plausible(text):
            fail += 1
            reason = "captcha" if is_captcha(text) else "empty_archive"
            log_failure(CC, {"identifier": str(i), "source_url": url, "status": "failed", "reason": reason})
            continue
        title = f"Държавен вестник idMat={i}"
        for line in text.splitlines():
            if len(line.strip()) > 15 and "Validation" not in line:
                title = line.strip()[:240]
                break
        rec = base_record(
            cc=CC, country=COUNTRY, language="bg", ident=str(i), title=title, text=text,
            source_url=src, source_type=SOURCE_TYPE, license_text=LICENSE,
            collector="bg-dv-wayback", eli=None, date=None, official_identifier=str(i),
            document_type="gazette_act", law_status="unknown", is_current=None,
            extra_meta={"discovery": {"method": "wayback_cdx_timestamp", "idMat": i, "original_url": url}},
        )
        write_instrument(CC, rec)
        done.add(rid)
        ok += 1
        log.info("ok idMat=%s chars=%s ok=%s fail=%s", i, len(text), ok, fail)

    notes = (
        "Live dv.parliament.bg TLS fails (SSLEOF). Official showMaterialDV.jsp via Wayback "
        f"with CDX timestamps (avoids /2id_/ captcha interstitial). Anchor windows radius={radius}. "
        "Captcha bodies rejected/quarantined."
    )
    write_summary(
        CC, country=COUNTRY, source="Държавен вестник (Wayback of official URLs)",
        source_urls=["https://dv.parliament.bg/", "https://web.archive.org/"],
        license_text=LICENSE, discovered=len(uniq), fetched=ok, skipped=skip, failed=fail,
        coverage="shard", notes=notes, last_run=utcnow(), extra=f"started {t0}",
    )
    log.info("done disc=%s ok=%s fail=%s skip=%s", len(uniq), ok, fail, skip)


if __name__ == "__main__":
    main()
