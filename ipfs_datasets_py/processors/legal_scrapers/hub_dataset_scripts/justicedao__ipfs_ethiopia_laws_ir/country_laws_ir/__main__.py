"""python -m country_laws_ir {build,query,batch,catalog}"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="country_laws_ir")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build")
    p_build.add_argument("--source-repo", "--source", dest="source", default="malta",
                         help="Hub dataset id (endomorphosis/ipfs_<slug>_laws) or country slug")
    p_build.add_argument("--out", default=None)
    p_build.add_argument("--device", default="cpu")
    p_build.add_argument("--neighbor-k", type=int, default=8)
    p_build.add_argument("--skip-vectors", action="store_true")
    p_build.add_argument("--upload", action="store_true")

    p_batch = sub.add_parser("batch")
    p_batch.add_argument("--slugs", nargs="*", default=None)
    p_batch.add_argument("--upload", action="store_true")
    p_batch.add_argument("--no-skip-done", action="store_true")

    p_q = sub.add_parser("query")
    p_q.add_argument("--local-dir", required=True)
    p_q.add_argument("rest", nargs=argparse.REMAINDER)

    p_norm = sub.add_parser("normalize")
    p_norm.add_argument("--source-repo", "--source", dest="source", default="malta")
    p_norm.add_argument("--out", default=None, help="Optional JSON report path")

    sub.add_parser("catalog")

    args = ap.parse_args(argv)
    if args.cmd == "build":
        from .build import build_country

        result = build_country(
            args.source,
            out=Path(args.out) if args.out else None,
            upload=args.upload,
            device=args.device,
            neighbor_k=args.neighbor_k,
            skip_vectors=args.skip_vectors,
        )
        print(json.dumps({k: result[k] for k in result if k != "normalization"}, indent=2, default=str))
        print(json.dumps({"normalization": result["normalization"]}, indent=2, default=str))
        return 0
    if args.cmd == "batch":
        from .build import batch

        results = batch(slugs=args.slugs, upload=args.upload, skip_done=not args.no_skip_done)
        print(json.dumps([{"country": r["country"], "out": r["out"]} for r in results], indent=2))
        return 0
    if args.cmd == "query":
        from .query import main as qmain

        argv2 = ["--local-dir", args.local_dir] + [a for a in args.rest if a != "--"]
        return qmain(argv2)
    if args.cmd == "normalize":
        from .build import CACHE, REPORTS, ROOT
        from .catalog import get_country
        from .normalize import build_corpus, load_source

        country = get_country(args.source)
        laws, articles, source_meta = load_source(country["repo"], CACHE)
        corpus, report = build_corpus(laws, articles, source_meta)
        out = Path(args.out) if args.out else REPORTS / f"{country['slug']}_normalization.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"out": str(out), "n_out": report["n_out"], "unit": report["unit"], "drops": report["drops"]}, indent=2))
        return 0
    if args.cmd == "catalog":
        from .catalog import COUNTRIES, indexable_countries

        print(json.dumps({"n": len(COUNTRIES), "indexable": len(indexable_countries()), "countries": COUNTRIES}, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
