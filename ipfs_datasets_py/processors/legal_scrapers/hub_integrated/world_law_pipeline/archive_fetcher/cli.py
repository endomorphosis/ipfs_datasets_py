#!/usr/bin/env python3
"""CLI for the shared archive fetcher.

  python cli.py captures <url|prefix*> [--match exact|prefix|host|domain] [--sources commoncrawl,wayback]
                 [--cc-crawls 12] [--newest-per-url] [--limit 50] [--json]
  python cli.py fetch <url> [--out FILE] [--policy cc_first|newest] [--meta]
  python cli.py cache-stats
  python cli.py evict [--max-gb 8] [--include-cdx]   (default: DEFAULT_CACHE_MAX_BYTES = 8 GB)
"""
import argparse, json, logging, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from archive.core import ArchiveFetcher, DEFAULT_CACHE, DEFAULT_CACHE_MAX_BYTES  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="archive")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE))
    ap.add_argument("--cc-crawls", type=int, default=12, help="newest N CC crawls to query (0 = all)")
    ap.add_argument("--no-cc", action="store_true"); ap.add_argument("--no-wayback", action="store_true")
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--lane", default=None, help="fair-share lane for the box-wide limiter (default $ARCHIVE_LANE)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("captures"); c.add_argument("url"); c.add_argument("--match", default="exact")
    c.add_argument("--sources", default="commoncrawl,wayback"); c.add_argument("--newest-per-url", action="store_true")
    c.add_argument("--wb-collapse", default=None); c.add_argument("--limit", type=int, default=50)
    c.add_argument("--json", action="store_true")
    f = sub.add_parser("fetch"); f.add_argument("url"); f.add_argument("--out")
    f.add_argument("--policy", default="cc_first"); f.add_argument("--meta", action="store_true")
    sub.add_parser("cache-stats")
    e = sub.add_parser("evict"); e.add_argument("--max-gb", type=float, default=DEFAULT_CACHE_MAX_BYTES / 1024**3); e.add_argument("--include-cdx", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.v else logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    fx = ArchiveFetcher(a.cache, cc_crawls=a.cc_crawls, use_cc=not a.no_cc, use_wayback=not a.no_wayback,
                        lane=a.lane)
    if a.cmd == "captures":
        caps = fx.list_captures(a.url, a.match, sources=a.sources.split(","), newest_per_url=a.newest_per_url,
                                wb_collapse=a.wb_collapse)
        print(f"# {len(caps)} captures (newest first)", file=sys.stderr)
        for cap in caps[: a.limit if a.limit > 0 else None]:
            if a.json:
                print(json.dumps(cap.to_dict()))
            else:
                print(cap.timestamp, cap.source, cap.crawl_id, cap.status, cap.mime, cap.original_url)
    elif a.cmd == "fetch":
        doc = fx.fetch_newest(a.url, policy=a.policy)
        if doc is None:
            print("no good capture found", file=sys.stderr); return 2
        print(json.dumps({**doc.provenance(), "http_status": doc.http_status, "content_type": doc.content_type,
                          "bytes": len(doc.body), "incomplete_reason": doc.incomplete_reason,
                          "from_cache": doc.from_cache}, ensure_ascii=False), file=sys.stderr)
        if a.out:
            Path(a.out).write_bytes(doc.body)
        elif not a.meta:
            sys.stdout.write(doc.text())
    elif a.cmd == "cache-stats":
        root = Path(a.cache)
        print(json.dumps({"cache_dir": str(root), "bytes": fx.cache.size(),
                          "bodies": sum(1 for _ in (root / "body").rglob("*.bin.gz")),
                          "cdx_pages": sum(1 for _ in (root / "cdx").glob("*.json")),
                          "ratelimit": __import__("archive.ratelimit", fromlist=["x"]).status()}, indent=1))
    elif a.cmd == "evict":
        print(json.dumps(fx.cache.evict(int(a.max_gb * 1024**3), include_cdx=a.include_cdx)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
