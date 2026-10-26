#!/usr/bin/env python3
"""Bulgaria State Gazette via Wayback CDX ONLY (live dv.parliament.bg is SSLEOF/captcha).

Discovers official showMaterialDV.jsp?idMat=* captures from web.archive.org CDX,
dedupes by idMat, fetches raw snapshots (id_ modifier), writes instruments.
Never hits the live portal.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *  # noqa: F401,F403
from archive_fallbacks import (  # noqa: E402
    search_wayback_machine,
    get_wayback_content,
    is_spa_shell,
)

CC, COUNTRY, SOURCE_TYPE = "bg", "Bulgaria", "dv_parliament"
LICENSE = (
    "State Gazette of the Republic of Bulgaria (dv.parliament.bg). "
    "Official texts; reuse per public-sector / gazette terms. "
    "Snapshots via Wayback Machine of official URLs only."
)
log = logging.getLogger("bg")

MIN_TEXT = 280
MIN_CDX_LENGTH = 1500
CDX_LIMIT_PER_SHARD = 2500
QUEUE_PATH = ROOT / CC / "raw" / "cdx_fetch_queue.jsonl"
USABLE_PATH = ROOT / CC / "raw" / "cdx_usable.json"


def setup():
    ensure_dirs(CC)
    (ROOT / CC / "raw").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )


def _idmat(url: str) -> str | None:
    m = re.search(r"idMat=(\d+)", url or "", re.I)
    return m.group(1) if m else None


def build_cdx_catalog(force: bool = False) -> list[dict]:
    """Year-sharded Wayback CDX → best capture per idMat (by WARC record length)."""
    if QUEUE_PATH.exists() and not force:
        rows = []
        for line in QUEUE_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        if rows:
            log.info("reusing existing CDX queue n=%s", len(rows))
            return rows

    best: dict[str, dict] = {}
    if USABLE_PATH.exists() and not force:
        try:
            best = {k: v for k, v in json.loads(USABLE_PATH.read_text(encoding="utf-8")).items()}
            log.info("seeded usable catalog n=%s", len(best))
        except Exception:
            best = {}

    years = [(f"{y}0101", f"{y}1231") for y in range(2008, 2027)]
    queries: list[tuple[str | None, str | None, int]] = [(None, None, 5000)]
    queries += [(a, b, CDX_LIMIT_PER_SHARD) for a, b in years]

    for fr, to, lim in queries:
        t0 = time.time()
        hits = search_wayback_machine(
            "dv.parliament.bg/DVWeb/showMaterialDV.jsp?idMat=*",
            limit=lim,
            collapse="urlkey",
            from_date=fr,
            to_date=to,
        )
        improved = 0
        for h in hits:
            iid = _idmat(h.get("original") or "")
            if not iid:
                continue
            try:
                length = int(h.get("length") or 0)
            except Exception:
                length = 0
            prev = best.get(iid)
            if prev is None or length > int(prev.get("length") or 0):
                best[iid] = {
                    "original": h.get("original"),
                    "timestamp": h.get("timestamp"),
                    "length": str(length),
                    "digest": h.get("digest"),
                    "wayback_url": h.get("wayback_url"),
                    "mimetype": h.get("mimetype"),
                }
                improved += 1
        log.info(
            "cdx shard %s-%s hits=%s best=%s improved=%s t=%.1fs",
            fr, to, len(hits), len(best), improved, time.time() - t0,
        )

    usable = {
        k: v for k, v in best.items() if int(v.get("length") or 0) >= MIN_CDX_LENGTH
    }
    USABLE_PATH.write_text(json.dumps(usable, ensure_ascii=False), encoding="utf-8")
    rows = []
    for iid, h in sorted(usable.items(), key=lambda kv: -int(kv[1].get("length") or 0)):
        rows.append(
            {
                "idMat": iid,
                "original": h.get("original"),
                "timestamp": h.get("timestamp"),
                "length": h.get("length"),
                "digest": h.get("digest"),
                "wayback_url": h.get("wayback_url"),
            }
        )
    QUEUE_PATH.write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n",
        encoding="utf-8",
    )
    log.info("catalog unique=%s usable>=%s=%s", len(best), MIN_CDX_LENGTH, len(rows))
    return rows


def discover() -> list[dict]:
    return build_cdx_catalog(force=False)


def _alternate_timestamps(url: str, primary_ts: str | None) -> list[str]:
    """Fetch a few alternate CDX timestamps for one URL when primary replay 404s."""
    hits = search_wayback_machine(url, limit=12, collapse="", from_date="20050101")
    out = []
    seen = set()
    # prefer longer records
    hits = sorted(hits, key=lambda h: int(h.get("length") or 0), reverse=True)
    for h in hits:
        ts = h.get("timestamp") or ""
        if not ts or ts in seen or ts == primary_ts:
            continue
        seen.add(ts)
        out.append(ts)
        if len(out) >= 4:
            break
    return out


def fetch_one(row: dict, done: set[str]) -> str:
    iid = str(row.get("idMat") or _idmat(row.get("original") or "") or "")
    if not iid:
        return "fail"
    rid = slug_id(CC, iid)
    if rid in done:
        return "skip"

    url = row.get("original") or f"https://dv.parliament.bg/DVWeb/showMaterialDV.jsp?idMat={iid}"
    # normalize to https official host form for metadata
    canon = f"https://dv.parliament.bg/DVWeb/showMaterialDV.jsp?idMat={iid}"
    timestamps = [row.get("timestamp")] if row.get("timestamp") else []
    timestamps.append(None)  # latest available via /web/2id_/

    payload = None
    last_err = None
    tried = set()
    for ts in timestamps:
        key = ts or "latest"
        if key in tried:
            continue
        tried.add(key)
        res = get_wayback_content(url, timestamp=ts)
        if res.get("status") == "success" and (res.get("text") or res.get("content")):
            payload = res
            break
        last_err = res.get("error")
        # http:// vs https://
        if url.startswith("https://"):
            alt = "http://" + url[len("https://") :]
        else:
            alt = "https://" + url[len("http://") :]
        res2 = get_wayback_content(alt, timestamp=ts)
        if res2.get("status") == "success" and (res2.get("text") or res2.get("content")):
            payload = res2
            url = alt
            break
        last_err = f"{last_err}; {res2.get('error')}"

    if payload is None or payload.get("status") != "success":
        # one more CDX lookup for alternate captures
        for ts in _alternate_timestamps(canon, row.get("timestamp")):
            if ts in tried:
                continue
            tried.add(ts)
            res = get_wayback_content(canon, timestamp=ts)
            if res.get("status") == "success" and (res.get("text") or res.get("content")):
                payload = res
                break
            res = get_wayback_content(
                "http://dv.parliament.bg/DVWeb/showMaterialDV.jsp?idMat=" + iid,
                timestamp=ts,
            )
            if res.get("status") == "success" and (res.get("text") or res.get("content")):
                payload = res
                break
            last_err = res.get("error")

    if payload is None or payload.get("status") != "success":
        log_failure(
            CC,
            {
                "identifier": iid,
                "source_url": canon,
                "status": "failed",
                "reason": f"wayback_only:{last_err}",
                "method_used": "wayback",
            },
        )
        return "fail"

    html = payload.get("text") or ""
    text = html_to_text(html) if html else ""
    if not text and payload.get("content"):
        raw = payload["content"]
        if isinstance(raw, bytes):
            try:
                text = html_to_text(raw.decode("utf-8", "replace"))
            except Exception:
                text = ""
    if is_spa_shell(html, text) or len(text) < MIN_TEXT:
        log_failure(
            CC,
            {
                "identifier": iid,
                "source_url": canon,
                "status": "failed",
                "reason": f"empty_or_chrome:{len(text)}",
                "method_used": "wayback",
            },
        )
        return "fail"

    title = iid
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
        title = re.sub(r"\s*\|\s*Wayback Machine$", "", title)
        title = re.sub(r"^Wayback Machine\s*", "", title)
    # try to pull act heading from body
    for pat in (
        r"(?:ЗАКОН|УКАЗ|ПОСТАНОВЛЕНИЕ|НАРЕДБА|РЕШЕНИЕ)[^\n<]{5,200}",
        r"<h1[^>]*>([^<]{8,240})</h1>",
    ):
        mm = re.search(pat, html if "h1" in pat else text, re.I)
        if mm:
            cand = re.sub(r"\s+", " ", mm.group(0 if "ЗАКОН" in pat or "УКАЗ" in pat else 1)).strip()
            if 8 < len(cand) < 240:
                title = cand
                break

    cap_ts = payload.get("capture_timestamp") or row.get("timestamp") or ""
    date = None
    if cap_ts and len(str(cap_ts)) >= 8:
        date = iso_date(str(cap_ts)[:8])

    rec = base_record(
        cc=CC,
        country=COUNTRY,
        language="bg",
        ident=iid,
        title=title,
        text=text,
        source_url=canon,
        source_type=SOURCE_TYPE,
        license_text=LICENSE,
        collector="bg-wayback-cdx",
        eli=None,
        date=date,
        official_identifier=iid,
        document_type="gazette_act",
        law_status="unknown",
        is_current=None,
        extra_meta={
            "method_used": "wayback",
            "discovery": {"method": "wayback_cdx", "idMat": iid, "cdx_length": row.get("length")},
            "archive_url": payload.get("wayback_url"),
            "capture_timestamp": cap_ts,
            "text_extraction": {"source": "archive", "backend": "html"},
        },
    )
    rec["canonical_document_url"] = payload.get("wayback_url") or canon
    rec["information_url"] = canon
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    # Prefer new-only queue if present (cdx_new_queue.jsonl), else full catalog
    new_q = ROOT / CC / "raw" / "cdx_new_queue.jsonl"
    if new_q.exists():
        items = []
        for line in new_q.read_text(encoding="utf-8").splitlines():
            if line.strip():
                items.append(json.loads(line))
        log.info("loaded new-only queue n=%s", len(items))
    else:
        items = discover()

    done = existing_ids(CC)
    ok = skip = fail = 0
    for i, it in enumerate(items, 1):
        try:
            st = fetch_one(it, done)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"status": "failed", "reason": repr(exc), "row": it})
            log.exception("fetch fail")
        ok += st == "ok"
        skip += st == "skip"
        fail += st == "fail"
        if i % 25 == 0 or i == len(items):
            log.info("progress %s/%s ok=%s skip=%s fail=%s instruments=%s",
                     i, len(items), ok, skip, fail, len(existing_ids(CC)))
            write_summary(
                CC,
                country=COUNTRY,
                source="Wayback CDX of Държавен вестник (dv.parliament.bg) — live portal skipped (SSLEOF)",
                source_urls=[
                    "https://dv.parliament.bg/DVWeb/showMaterialDV.jsp",
                    "https://web.archive.org/cdx/search/cdx?url=dv.parliament.bg/DVWeb/showMaterialDV.jsp*",
                ],
                license_text=LICENSE,
                discovered=len(items),
                fetched=ok,
                skipped=skip,
                failed=fail,
                coverage="shard" if ok else "catalog-backed incomplete",
                notes="Wayback-only expansion; no live portal; official URLs only.",
                last_run=utcnow(),
            )

    n = len(list((ROOT / CC / "instruments").glob("*.json")))
    notes = (
        "Live dv.parliament.bg skipped (SSLEOF/captcha/503). "
        "Expanded via Wayback CDX + id_ replay of official showMaterialDV.jsp?idMat=* only. "
        f"Queue={len(items)} ok={ok} fail={fail} skip={skip} instruments_on_disk={n}. "
        f"started {t0}"
    )
    write_summary(
        CC,
        country=COUNTRY,
        source="Wayback CDX of Държавен вестник (dv.parliament.bg) — live portal skipped (SSLEOF)",
        source_urls=[
            "https://dv.parliament.bg/DVWeb/showMaterialDV.jsp",
            "https://web.archive.org/cdx/search/cdx?url=dv.parliament.bg/DVWeb/showMaterialDV.jsp*",
        ],
        license_text=LICENSE,
        discovered=len(items),
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="shard",
        notes=notes,
        last_run=utcnow(),
        extra="Wayback-only; no unofficial aggregators.",
    )
    log.info("DONE ok=%s fail=%s skip=%s instruments=%s", ok, fail, skip, n)


if __name__ == "__main__":
    main()
