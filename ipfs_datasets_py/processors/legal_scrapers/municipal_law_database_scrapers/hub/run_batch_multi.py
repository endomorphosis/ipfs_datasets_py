#!/usr/bin/env python3
"""Batch-scrape Municode / eCode360 / AmLegal jurisdictions into snappy parquet.

Examples:
  python3 scrapers/run_batch_multi.py --todo ecode360_todo.json --publisher ecode360 --limit 2
  python3 scrapers/run_batch_multi.py --todo amlegal_todo.json --publisher amlegal --limit 2
  python3 scrapers/run_batch_multi.py --todo municode_todo.json --publisher municode --limit 10
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_here = Path(__file__).resolve().parent
ROOT = _here.parent if _here.name == "scrapers" else _here
sys.path.insert(0, str(ROOT))

from scrapers.municode import (  # noqa: E402
    MunicodeClient,
    municode_url_from_row,
    scrape_jurisdiction as scrape_municode,
)
from scrapers.ecode360 import scrape_jurisdiction as scrape_ecode360  # noqa: E402
from scrapers.amlegal import scrape_jurisdiction as scrape_amlegal  # noqa: E402
from scrapers.parquet_writer import (  # noqa: E402
    docs_to_html_rows,
    validate_html_schema,
    write_jurisdiction,
)


def load_todo(path: Path) -> dict:
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return {"count": len(data), "items": data}
    return data


def already_done(out_root: Path, gnis: str) -> bool:
    p = out_root / "american_law" / "data" / f"{gnis}_html.parquet"
    return p.exists() and p.stat().st_size > 0


def append_log(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = dict(rec)
    rec["ts"] = datetime.now(timezone.utc).isoformat()
    with path.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def detect_publisher(row: dict) -> str | None:
    if row.get("publisher"):
        return str(row["publisher"]).lower()
    urls = list(row.get("source_urls") or [])
    if row.get("source_url"):
        urls.append(row["source_url"])
    blob = " ".join(urls).lower()
    if "municode.com" in blob:
        return "municode"
    if "ecode360.com" in blob:
        return "ecode360"
    if "amlegal.com" in blob:
        return "amlegal"
    return None


def pick_url(row: dict, publisher: str) -> str | None:
    urls = list(row.get("source_urls") or [])
    if row.get("source_url"):
        urls.append(row["source_url"])
    # also split comma-joined
    expanded: list[str] = []
    for u in urls:
        expanded.extend([p.strip() for p in str(u).split(",") if p.strip()])
    needles = {
        "municode": "municode.com",
        "ecode360": "ecode360.com",
        "amlegal": "amlegal.com",
    }
    needle = needles[publisher]
    for u in expanded:
        if needle in u.lower():
            return u
    if publisher == "municode":
        return municode_url_from_row(row)
    return expanded[0] if expanded else None


def scrape_one(
    publisher: str,
    *,
    url: str,
    gnis: str,
    place_name: str,
    state_code: str,
    delay: float,
    municode_client: MunicodeClient | None,
    max_chapters: int | None,
    max_nodes: int | None,
) -> dict[str, Any]:
    if publisher == "municode":
        assert municode_client is not None
        return scrape_municode(
            municode_client,
            url=url,
            gnis=gnis,
            place_name=place_name,
            state_code=state_code,
        )
    if publisher == "ecode360":
        return scrape_ecode360(url, sleep=delay, max_chapters=max_chapters)
    if publisher == "amlegal":
        return scrape_amlegal(url, sleep=delay, max_nodes=max_nodes)
    return {"ok": False, "error": f"unknown publisher {publisher}", "docs": []}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Multi-publisher municipal scrape to parquet")
    ap.add_argument("--todo", required=True)
    ap.add_argument("--out", default=str(ROOT / "out"))
    ap.add_argument("--sample", default=str(ROOT / "1008538_html.parquet"))
    ap.add_argument("--limit", type=int, default=1)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.0, help="0 = publisher default")
    ap.add_argument("--publisher", choices=["auto", "municode", "ecode360", "amlegal"], default="auto")
    ap.add_argument("--skip-existing", action="store_true", default=True)
    ap.add_argument("--no-skip-existing", action="store_false", dest="skip_existing")
    ap.add_argument("--gnis", action="append", default=[])
    ap.add_argument("--max-chapters", type=int, default=None, help="ecode360 only")
    ap.add_argument("--max-nodes", type=int, default=None, help="amlegal only")
    ap.add_argument("--validate", action="store_true", default=True)
    args = ap.parse_args(argv)

    out_root = Path(args.out)
    log_path = out_root / "scrape_log.jsonl"
    todo = load_todo(Path(args.todo))
    items = list(todo.get("items") or [])
    if args.gnis:
        want = {str(g) for g in args.gnis}
        items = [r for r in items if str(r.get("gnis")) in want]
    items = items[args.offset :]

    defaults = {"municode": 1.15, "ecode360": 0.75, "amlegal": 0.5}
    municode_client = MunicodeClient(delay=args.delay or defaults["municode"])

    done = 0
    results = []
    for row in items:
        if args.limit and done >= args.limit:
            break
        gnis = str(row.get("gnis"))
        place = row.get("place_name") or ""
        state = row.get("state_code") or ""
        pub = args.publisher if args.publisher != "auto" else detect_publisher(row)
        if not pub:
            rec = {"gnis": gnis, "place_name": place, "ok": False, "error": "unknown publisher"}
            append_log(log_path, rec)
            print(f"FAIL {gnis} {place}: unknown publisher")
            continue
        if args.skip_existing and already_done(out_root, gnis):
            print(f"SKIP existing {gnis} {place}")
            continue
        url = pick_url(row, pub)
        if not url:
            rec = {"gnis": gnis, "place_name": place, "ok": False, "error": f"no {pub} url", "publisher": pub}
            append_log(log_path, rec)
            print(f"FAIL {gnis} {place}: no {pub} url")
            continue
        delay = args.delay or defaults[pub]
        print(f"SCRAPE[{pub}] {gnis} {place} {state} {url}", flush=True)
        try:
            scraped = scrape_one(
                pub,
                url=url,
                gnis=gnis,
                place_name=place,
                state_code=state,
                delay=delay,
                municode_client=municode_client,
                max_chapters=args.max_chapters,
                max_nodes=args.max_nodes,
            )
            if not scraped.get("ok"):
                rec = {
                    "gnis": gnis,
                    "place_name": place,
                    "ok": False,
                    "error": scraped.get("error"),
                    "publisher": pub,
                }
                append_log(log_path, rec)
                print(f"FAIL {gnis} {place}: {scraped.get('error')}")
                continue
            html_rows = docs_to_html_rows(scraped["docs"], gnis)
            if not html_rows:
                rec = {"gnis": gnis, "place_name": place, "ok": False, "error": "zero docs", "publisher": pub}
                append_log(log_path, rec)
                print(f"FAIL {gnis} {place}: zero docs")
                continue
            written = write_jurisdiction(
                out_root,
                gnis,
                html_rows,
                place_name=place or scraped.get("place_name") or "",
                state_code=state,
                last_updated_ms=scraped.get("last_updated_ms"),
            )
            schema = None
            sample = Path(args.sample)
            if args.validate and sample.exists():
                schema = validate_html_schema(Path(written["html_path"]), sample)
                print(f"  schema ok={schema['ok']} cols={schema['columns']} notes={schema['notes']}")
            rec = {
                "gnis": gnis,
                "place_name": place,
                "state_code": state,
                "ok": True,
                "publisher": pub,
                "html_rows": written["html_rows"],
                "citation_rows": written["citation_rows"],
                "html_path": written["html_path"],
                "citation_path": written["citation_path"],
                "metadata_path": written["metadata_path"],
                "schema": schema,
            }
            append_log(log_path, rec)
            results.append(rec)
            done += 1
            print(f"OK {gnis} {place} html={written['html_rows']} cite={written['citation_rows']}")
        except Exception as e:
            rec = {
                "gnis": gnis,
                "place_name": place,
                "ok": False,
                "publisher": pub,
                "error": f"{type(e).__name__}: {e}",
                "trace": traceback.format_exc()[-1500:],
            }
            append_log(log_path, rec)
            print(f"ERROR {gnis} {place}: {type(e).__name__}: {e}")
            traceback.print_exc()

    summary = {"attempted_ok": done, "results": results}
    print(json.dumps({"attempted_ok": done, "results": [{k: r[k] for k in ('gnis','place_name','publisher','html_rows') if k in r} for r in results]}, indent=2))
    (out_root / "last_run_summary_multi.json").write_text(json.dumps(summary, indent=2, default=str))
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
