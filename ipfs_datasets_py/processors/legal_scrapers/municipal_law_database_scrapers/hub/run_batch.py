#!/usr/bin/env python3
"""Batch-scrape remaining Municode jurisdictions into snappy parquet.

Examples:
  python3 /workspace/muni/scrapers/run_batch.py --limit 1 --prefer-small
  python3 /workspace/muni/scrapers/run_batch.py --limit 50 --skip-existing
  python3 /workspace/muni/scrapers/run_batch.py --gnis 2413426
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

_here = Path(__file__).resolve().parent
ROOT = _here.parent if _here.name == "scrapers" else _here
SITE = ROOT / ".venv" / "lib" / "python3.13" / "site-packages"
if SITE.exists():
    sys.path.insert(0, str(SITE))
sys.path.insert(0, str(ROOT))

from scrapers.municode import (  # noqa: E402
    MunicodeClient,
    municode_url_from_row,
    scrape_jurisdiction,
)
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


def is_small(row: dict) -> bool:
    name = row.get("place_name") or ""
    if "Township" in name:
        return False
    return bool(re.match(r"^(Village|Town|Borough) of ", name))


def already_done(out_root: Path, gnis: str) -> bool:
    p = out_root / "american_law" / "data" / f"{gnis}_html.parquet"
    p2 = out_root / f"{gnis}_html.parquet"
    return (p.exists() and p.stat().st_size > 0) or (p2.exists() and p2.stat().st_size > 0)


def append_log(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = dict(rec)
    rec["ts"] = datetime.now(timezone.utc).isoformat()
    with path.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scrape Municode codes to snappy parquet")
    ap.add_argument("--todo", default=str(ROOT / "municode_todo.json"))
    ap.add_argument("--out", default=str(ROOT / "out"))
    ap.add_argument("--sample", default=str(ROOT / "1008538_html.parquet"))
    ap.add_argument("--limit", type=int, default=1)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--delay", type=float, default=1.15)
    ap.add_argument("--skip-existing", action="store_true", default=True)
    ap.add_argument("--no-skip-existing", action="store_false", dest="skip_existing")
    ap.add_argument("--prefer-small", action="store_true")
    ap.add_argument("--gnis", action="append", default=[])
    ap.add_argument("--validate", action="store_true", default=True)
    args = ap.parse_args(argv)

    out_root = Path(args.out)
    log_path = out_root / "scrape_log.jsonl"
    todo = load_todo(Path(args.todo))
    items = list(todo.get("items") or [])
    if args.gnis:
        want = {str(g) for g in args.gnis}
        items = [r for r in items if str(r.get("gnis")) in want]
    if args.prefer_small:
        items = sorted(
            items,
            key=lambda r: (0 if is_small(r) else 1, len(r.get("place_name") or ""), r.get("place_name") or ""),
        )
    items = items[args.offset :]

    client = MunicodeClient(delay=args.delay)
    done = 0
    results = []
    for row in items:
        if args.limit and done >= args.limit:
            break
        gnis = str(row.get("gnis"))
        place = row.get("place_name") or ""
        state = row.get("state_code") or ""
        url = municode_url_from_row(row)
        if args.skip_existing and already_done(out_root, gnis):
            print(f"SKIP existing {gnis} {place}")
            continue
        if not url:
            rec = {"gnis": gnis, "place_name": place, "ok": False, "error": "no municode url"}
            append_log(log_path, rec)
            print(f"FAIL {gnis} {place}: no municode url")
            continue
        print(f"SCRAPE {gnis} {place} {state} {url}", flush=True)
        try:
            scraped = scrape_jurisdiction(
                client, url=url, gnis=gnis, place_name=place, state_code=state
            )
            if not scraped.get("ok"):
                rec = {
                    "gnis": gnis,
                    "place_name": place,
                    "ok": False,
                    "error": scraped.get("error"),
                }
                append_log(log_path, rec)
                print(f"FAIL {gnis} {place}: {scraped.get('error')}")
                continue
            html_rows = docs_to_html_rows(scraped["docs"], gnis)
            if not html_rows:
                rec = {"gnis": gnis, "place_name": place, "ok": False, "error": "zero docs"}
                append_log(log_path, rec)
                print(f"FAIL {gnis} {place}: zero docs")
                continue
            written = write_jurisdiction(
                out_root,
                gnis,
                html_rows,
                place_name=place,
                state_code=state,
                last_updated_ms=scraped.get("last_updated_ms"),
            )
            schema = None
            sample = Path(args.sample)
            if args.validate and sample.exists():
                schema = validate_html_schema(Path(written["html_path"]), sample)
                print(
                    f"  schema ok={schema['ok']} cols={schema['columns']} notes={schema['notes']}"
                )
            rec = {
                "gnis": gnis,
                "place_name": place,
                "state_code": state,
                "ok": True,
                "html_rows": written["html_rows"],
                "citation_rows": written["citation_rows"],
                "html_path": written["html_path"],
                "citation_path": written["citation_path"],
                "metadata_path": written["metadata_path"],
                "schema": schema,
                "product": (scraped.get("product") or {}).get("ProductName"),
                "client": (scraped.get("client") or {}).get("ClientName"),
            }
            append_log(log_path, rec)
            results.append(rec)
            done += 1
            print(
                f"OK {gnis} {place} html={written['html_rows']} cite={written['citation_rows']}"
            )
        except Exception as e:
            rec = {
                "gnis": gnis,
                "place_name": place,
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "trace": traceback.format_exc()[-1500:],
            }
            append_log(log_path, rec)
            print(f"ERROR {gnis} {place}: {type(e).__name__}: {e}")
            traceback.print_exc()

    summary = {
        "attempted_ok": done,
        "results": [
            {
                k: r[k]
                for k in (
                    "gnis",
                    "place_name",
                    "state_code",
                    "html_rows",
                    "citation_rows",
                    "html_path",
                )
                if k in r
            }
            for r in results
        ],
    }
    print(json.dumps(summary, indent=2))
    (out_root / "last_run_summary.json").write_text(json.dumps(summary, indent=2))
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
