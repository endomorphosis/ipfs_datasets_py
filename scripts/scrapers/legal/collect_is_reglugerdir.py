#!/usr/bin/env python3
"""Iceland: reglugerðir ONLY (api.reglugerd.is) — never touches lagasafn 917 pack.

Official sources only:
  https://island.is/reglugerdir          (Reglugerðasafn UI)
  https://api.reglugerd.is/api/v1/       (official regulations API)
  Search: GET /search?q=*&page=N         (~2511 current regulations)
  Text:   GET /regulation/{nr}-{year}/current
  PDF:    GET /regulation/{nr}-{year}/current/pdf/

Safety vs primary pack (/workspace/legal-corpora/is, 917 lagasafn instruments):
  - Writes ONLY ids matching is-reg-* (prefix reg- before slug).
  - Never deletes or renames existing instruments.
  - Skips any id that already exists (including lagasafn).
  - Does NOT call write_summary() (would overwrite is/SUMMARY.md).
  - Writes is/SUMMARY_reglugerdir.md instead.

B-deild Stjórnartíðindi prevails on conflict with Reglugerðasafn. Not legal advice.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC, COUNTRY, SOURCE_TYPE = "is", "Iceland", "reglugerd_api"
LICENSE = (
    "Icelandic regulations (reglugerðir) as published via Reglugerðasafn / "
    "api.reglugerd.is (Stafrænt Ísland). If text conflicts with B-deild "
    "Stjórnartíðinda, the latter prevails. Not legal advice. Separate from "
    "Althingi lagasafn primary pack."
)
UA = DEFAULT_UA + " source=https://api.reglugerd.is/"
API = "https://api.reglugerd.is/api/v1"
SEARCH = f"{API}/search"
SLEEP = 0.25
PER_PAGE = 30  # API caps ~30
# Starter: first N pages (full run ~84 pages / 2511 items)
MAX_PAGES = 84  # full catalog ~2511 / 84 pages (was starter 15)
IDENT_PREFIX = "reg-"
log = logging.getLogger("is_reg")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "reglugerdir_collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def reg_ident(name: str) -> str:
    """name like '1010/2012' → 'reg-1010-2012' (slug → is-reg-1010-2012)."""
    n = (name or "").strip().replace("/", "-")
    n = re.sub(r"[^0-9A-Za-z._-]+", "-", n).strip("-")
    return f"{IDENT_PREFIX}{n}"


def discover() -> list[dict]:
    items, seen = [], set()
    page = 1
    total_pages = MAX_PAGES
    while page <= min(total_pages, MAX_PAGES):
        url = f"{SEARCH}?q=*&page={page}&perPage={PER_PAGE}"
        r = http_get(url, ua=UA, sleep=SLEEP, retries=3, timeout=(15, 60))
        if r.status_code != 200:
            log.error("search HTTP %s page %s", r.status_code, page)
            break
        try:
            data = r.json()
        except Exception as exc:
            log.error("search json fail: %s", exc)
            break
        total_pages = int(data.get("totalPages") or total_pages)
        rows = data.get("data") or []
        if not rows:
            break
        for row in rows:
            name = (row.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            # API name is NR/YEAR with possible leading zeros → path uses no slash
            path_name = name.replace("/", "-")
            # normalize 0740/2026 → 740-2026 for API path? API sample used 1010-2012
            # Try both: keep zero-padded as listed
            m = re.match(r"^0*(\d+)/(\d{4})$", name)
            api_key = f"{int(m.group(1))}-{m.group(2)}" if m else path_name
            item = {
                "name": name,
                "api_key": api_key,
                "ident": reg_ident(name),
                "title": row.get("title") or name,
                "date": row.get("publishedDate"),
                "ministry": row.get("ministry"),
                "url": f"{API}/regulation/{api_key}/current",
            }
            items.append(item)
            append_catalog(CC, {**item, "pack": "reglugerdir"})
        log.info("search page %s/%s items=%s totalItems=%s", page, total_pages, len(items), data.get("totalItems"))
        page += 1
    log.info("discovered %s (cap pages=%s)", len(items), MAX_PAGES)
    return items


def fetch_one(item: dict, done: set[str]) -> str:
    ident = item["ident"]
    if not ident.startswith(IDENT_PREFIX):
        log.error("refusing non-reg ident %s", ident)
        return "fail"
    rid = slug_id(CC, ident)
    if not rid.startswith("is-reg-"):
        log.error("refusing unexpected slug %s", rid)
        return "fail"
    if rid in done:
        return "skip"
    # Hard guard: never overwrite an on-disk file (lagasafn or prior)
    dest = ROOT / CC / "instruments" / f"{rid}.json"
    if dest.exists():
        return "skip"
    url = item["url"]
    r = http_get(url, ua=UA, sleep=SLEEP, retries=3, timeout=(20, 90))
    if r.status_code != 200 or not r.content:
        # try zero-padded api key variant
        alt = item["name"].replace("/", "-")
        if alt != item["api_key"]:
            url = f"{API}/regulation/{alt}/current"
            r = http_get(url, ua=UA, sleep=SLEEP, retries=2, timeout=(20, 90))
        if r.status_code != 200 or not r.content:
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": f"http_{r.status_code}", "pack": "reglugerdir"})
            return "fail"
    try:
        payload = r.json()
    except Exception:
        log_failure(CC, {"identifier": ident, "source_url": url, "reason": "bad_json", "pack": "reglugerdir"})
        return "fail"
    html = payload.get("text") or ""
    title = payload.get("title") or item["title"]
    text = html_to_text(html)
    if not text or len(text) < 80:
        log_failure(CC, {"identifier": ident, "source_url": url, "reason": "empty_text", "pack": "reglugerdir"})
        return "fail"
    rec = base_record(
        cc=CC, country=COUNTRY, language="is", ident=ident, title=title, text=text,
        source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="is-reglugerd-api", date=item.get("date"),
        official_identifier=item["name"], document_type="regulation",
        law_status="current",
        extra_meta={
            "discovery": {"method": "api_reglugerd_search", "ministry": item.get("ministry")},
            "pack": "reglugerdir",
            "api_name": item["name"],
            "never_overwrite_lagasafn": True,
        },
    )
    write_instrument(CC, rec)
    return "ok"


def write_reg_summary(*, discovered: int, fetched: int, skipped: int, failed: int, started: str) -> None:
    """Separate summary — does not overwrite is/SUMMARY.md (lagasafn)."""
    path = ROOT / CC / "SUMMARY_reglugerdir.md"
    n_reg = len(list((ROOT / CC / "instruments").glob("is-reg-*.json"))) if (ROOT / CC / "instruments").exists() else 0
    n_all = len(list((ROOT / CC / "instruments").glob("*.json"))) if (ROOT / CC / "instruments").exists() else 0
    lines = [
        "# Iceland reglugerðir corpus (secondary pack)",
        "",
        f"- jurisdiction: IS",
        f"- source: api.reglugerd.is Reglugerðasafn",
        f"- last_run_retrieved_at: {utcnow()} (PT: {pt_from_iso(utcnow())})",
        f"- reglugerdir_instruments_json: {n_reg}",
        f"- all_is_instruments_json_on_disk: {n_all} (includes lagasafn; do not thin)",
        f"- discovered: {discovered}",
        f"- fetched: {fetched}",
        f"- skipped: {skipped}",
        f"- failed: {failed}",
        f"- coverage: api search q=* pages 1..{MAX_PAGES} (full catalog ~2511 / ~84 pages)",
        f"- license: {LICENSE}",
        "- source_urls:",
        "  - https://island.is/reglugerdir",
        "  - https://api.reglugerd.is/api/v1/search?q=*",
        "- notes:",
        "  ONLY writes is-reg-* instruments. Never deletes lagasafn files.",
        "  Does not overwrite SUMMARY.md. B-deild Stjórnartíðindi prevails on conflict.",
        "  Not legal advice.",
        "",
        f"started {started}",
        "",
    ]
    atomic_write(path, "\n".join(lines))


def main():
    setup()
    t0 = utcnow()
    # Refuse to run if someone pointed CC elsewhere
    assert CC == "is"
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for i, item in enumerate(items, 1):
        try:
            st = fetch_one(item, done)
            if st == "ok":
                done.add(slug_id(CC, item["ident"]))
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"source_url": item.get("url"), "reason": repr(exc), "pack": "reglugerdir"})
        ok += st == "ok"
        skip += st == "skip"
        fail += st == "fail"
        if i % 40 == 0:
            log.info("progress %s/%s ok=%s skip=%s fail=%s", i, len(items), ok, skip, fail)
    write_reg_summary(discovered=len(items), fetched=ok, skipped=skip, failed=fail, started=t0)
    # Verify lagasafn count not reduced
    n_all = len(list((ROOT / CC / "instruments").glob("*.json")))
    n_lag = len([p for p in (ROOT / CC / "instruments").glob("*.json") if not p.stem.startswith("is-reg-")])
    log.info("done disc=%s ok=%s skip=%s fail=%s lagasafn_files=%s total=%s", len(items), ok, skip, fail, n_lag, n_all)


if __name__ == "__main__":
    main()
