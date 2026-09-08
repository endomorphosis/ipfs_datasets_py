"""CLI: python -m country_laws_ir build --source endomorphosis/ipfs_malta_laws --out ..."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import catalog
from .build import batch, build_country


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="country_laws_ir")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="Normalize + BM25 + graph + vectors + package")
    b.add_argument("--source", required=True, help="endomorphosis/ipfs_<country>_laws")
    b.add_argument("--out", default=None)
    b.add_argument("--no-upload", action="store_true")
    b.add_argument("--device", default="cpu")

    ba = sub.add_parser("batch", help="Build every indexable country (Malta first)")
    ba.add_argument("--no-upload", action="store_true")
    ba.add_argument("--include", nargs="*", default=None)

    c = sub.add_parser("catalog", help="Print country catalog")
    c.add_argument("--refresh", action="store_true")
    c.add_argument("--json", action="store_true")

    q = sub.add_parser("query", help="Query a local or Hub IR release")
    q.add_argument("--local-dir")
    q.add_argument("--repo-id")
    q.add_argument("--revision")
    q.add_argument("rest", nargs=argparse.REMAINDER)

    args = p.parse_args(argv)
    if args.cmd == "build":
        result = build_country(
            args.source,
            out=Path(args.out) if args.out else None,
            upload=not args.no_upload,
            device=args.device,
        )
        print(json.dumps({k: result[k] for k in result if k != "schema_mapping"}, indent=2, default=str))
        return 0
    if args.cmd == "batch":
        results = batch(slugs=args.include, upload=not args.no_upload)
        print(json.dumps([{"country": r.get("country"), "hub": r.get("hub")} for r in results], indent=2))
        return 0
    if args.cmd == "catalog":
        rows = catalog.refresh_from_hub() if args.refresh else catalog.COUNTRIES
        if args.json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        else:
            for r in rows:
                flag = "INDEX" if r.get("indexable") else "SKIP"
                extra = f"  ({r.get('skip_reason')})" if r.get("skip_reason") else ""
                print(f"{flag:5} {r['repo']:42} {r['name']}{extra}")
        return 0
    if args.cmd == "query":
        from .query import main as qmain

        qargs = []
        if args.local_dir:
            qargs += ["--local-dir", args.local_dir]
        if args.repo_id:
            qargs += ["--repo-id", args.repo_id]
        if args.revision:
            qargs += ["--revision", args.revision]
        qargs += list(args.rest)
        return qmain(qargs)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
