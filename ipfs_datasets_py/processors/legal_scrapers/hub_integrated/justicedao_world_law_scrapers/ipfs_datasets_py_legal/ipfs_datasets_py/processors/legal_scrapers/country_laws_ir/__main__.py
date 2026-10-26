"""python -m country_laws_ir {build,query,batch,catalog,normalize,package-raw}"""

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
                         help="Hub dataset id (endomorphosis/ipfs_<slug>_laws), country slug, or local pack dir")
    p_build.add_argument("--out", default=None)
    p_build.add_argument(
        "--device",
        default="cuda",
        help="Embedding device (cuda by default, like US Code / Open US Law; falls back to cpu)",
    )
    p_build.add_argument("--neighbor-k", type=int, default=8)
    p_build.add_argument("--skip-vectors", action="store_true")
    p_build.add_argument("--upload", action="store_true",
                         help="Publish the packaged release to justicedao/ipfs_<slug>_laws_ir (requires HF_TOKEN)")
    p_build.add_argument("--mode", default="auto", choices=["auto", "full", "delta"],
                         help="auto skips unchanged Hub revisions and reuses embeddings by entry_cid")
    p_build.add_argument("--force", action="store_true", help="Ignore source fingerprint skip and reuse caches")
    p_build.add_argument("--prior-dir", default=None, help="Prior GraphRAG release to delta against")

    p_batch = sub.add_parser("batch")
    p_batch.add_argument("--slugs", nargs="*", default=None)
    p_batch.add_argument("--upload", action="store_true")
    p_batch.add_argument("--no-skip-done", action="store_true",
                         help="Force a full rebuild of every country (ignore unchanged fingerprints)")
    p_batch.add_argument("--mode", default="auto", choices=["auto", "full", "delta"])
    p_batch.add_argument("--skip-vectors", action="store_true")

    p_q = sub.add_parser("query")
    p_q.add_argument("--local-dir", required=True)
    p_q.add_argument("rest", nargs=argparse.REMAINDER)

    p_norm = sub.add_parser("normalize")
    p_norm.add_argument("--source-repo", "--source", dest="source", default="malta")
    p_norm.add_argument("--out", default=None, help="Optional JSON report path")

    p_cat = sub.add_parser("catalog")
    p_cat.add_argument("--refresh", action="store_true",
                       help="List public endomorphosis/ipfs_*_laws datasets and persist new slugs")

    p_cov = sub.add_parser("coverage", help="Compare endomorphosis sources vs justicedao GraphRAG releases")
    p_cov.add_argument("--gaps", action="store_true",
                       help="Scan Hub for missing, stale, and incomplete IR (downloads manifests)")
    p_cov.add_argument("--workers", type=int, default=8)

    p_re = sub.add_parser(
        "reindex",
        help="Scan endomorphosis vs justicedao and incrementally rebuild stale/missing IR",
    )
    p_re.add_argument("--upload", action="store_true",
                      help="Publish rebuilt packs to justicedao (requires HF_TOKEN)")
    p_re.add_argument("--slugs", nargs="*", default=None)
    p_re.add_argument("--limit", type=int, default=None)
    p_re.add_argument("--max-corpus-rows", type=int, default=20000,
                      help="Skip IR larger than this many rows (0 = no cap)")
    p_re.add_argument("--skip-vectors", action="store_true")
    p_re.add_argument("--workers", type=int, default=2,
                      help="Parallel country workers (default 2 to stay under MemAbort; CUDA encodes are file-locked)")
    p_re.add_argument("--device", default="cuda")
    p_re.add_argument("--mode", default="auto", choices=["auto", "full", "delta"])
    p_re.add_argument("--all", action="store_true",
                      help="Process every indexable catalog country (not only Hub gaps)")
    p_re.add_argument("--force", action="store_true",
                      help="Rebuild even when the source SHA matches, and re-encode every row")
    p_re.add_argument("--renormalize", action="store_true",
                      help="Rerun normalization, then reindex only packs whose entry rows changed")

    p_ver = sub.add_parser(
        "verify",
        help="Normalize a country pack and run admission verifiers (no GraphRAG)",
    )
    p_ver.add_argument("--source-repo", "--source", dest="source", default=None)
    p_ver.add_argument("--all", action="store_true", help="Verify every indexable catalog country")
    p_ver.add_argument("--limit", type=int, default=None)

    p_loop = sub.add_parser(
        "normalize-loop",
        help="scan residuals, improve the normalizer script with llm_router, or apply that script",
    )
    p_loop.add_argument("stage", choices=["scan", "improve", "apply", "run"])
    p_loop.add_argument("--cache", default=None)
    p_loop.add_argument("--out", default=None)
    p_loop.add_argument("--reports", default=None, help="Per-country residual JSON directory")
    p_loop.add_argument("--slug", default=None, help="One country, for a subprocess")
    p_loop.add_argument("--workers", type=int, default=None, help="Country processes (default: one per CPU)")
    p_loop.add_argument("--limit", type=int, default=None)
    p_loop.add_argument("--passes", type=int, default=40, help="Improve batches sent to llm_router")
    p_loop.add_argument("--force", action="store_true", help="Redo finished countries and retry unresolved lines")
    p_loop.add_argument("--progress", default=None, help="JSONL file appended as each country or improve pass finishes")

    p_raw = sub.add_parser("package-raw")
    p_raw.add_argument("--slug", required=True, help="Country slug used in justicedao/ipfs_<slug>_laws_ir")
    p_raw.add_argument("--instruments-dir", default=None,
                       help="Collector JSON directory (default: $LEGAL_CORPORA_ROOT/<iso-or-slug>/instruments)")
    p_raw.add_argument("--iso", default=None, help="Collector ISO directory name if different from slug")
    p_raw.add_argument("--out", default=None, help="Local pack directory (laws.parquet + pack_meta.json)")
    p_raw.add_argument("--source-dataset", default=None,
                       help="Raw Hub id (default endomorphosis/ipfs_<slug>_laws)")
    p_raw.add_argument("--prior-pack", default=None, help="Existing parquet pack to merge into")

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
            mode=args.mode,
            force=args.force,
            prior_dir=Path(args.prior_dir) if args.prior_dir else None,
        )
        print(json.dumps({k: result[k] for k in result if k != "normalization"}, indent=2, default=str))
        print(json.dumps({"normalization": result["normalization"]}, indent=2, default=str))
        return 0
    if args.cmd == "batch":
        from .build import batch

        results = batch(
            slugs=args.slugs,
            upload=args.upload,
            skip_done=not args.no_skip_done,
            mode=args.mode,
            skip_vectors=args.skip_vectors,
        )
        print(json.dumps(
            [{"country": r["country"], "out": r["out"], "skipped": r.get("skipped", False)} for r in results],
            indent=2,
        ))
        return 0
    if args.cmd == "query":
        from .query import main as qmain

        argv2 = ["--local-dir", args.local_dir] + [a for a in args.rest if a != "--"]
        return qmain(argv2)
    if args.cmd == "normalize":
        from .build import CACHE, REPORTS
        from .catalog import get_country
        from .normalize import build_corpus, load_source

        country = get_country(args.source)
        local = country.get("local_source_dir")
        laws, articles, source_meta = load_source(local or country["repo"], CACHE)
        corpus, report = build_corpus(laws, articles, source_meta)
        out = Path(args.out) if args.out else REPORTS / f"{country['slug']}_normalization.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"out": str(out), "n_out": report["n_out"], "unit": report["unit"], "drops": report["drops"]}, indent=2))
        return 0
    if args.cmd == "catalog":
        from .catalog import all_countries, refresh_from_hub

        countries = refresh_from_hub() if args.refresh else all_countries()
        print(json.dumps(
            {"n": len(countries), "indexable": len([c for c in countries if c.get("indexable")]), "countries": countries},
            indent=2,
        ))
        return 0
    if args.cmd == "coverage":
        from .coverage import coverage_report, gap_report

        report = gap_report(workers=args.workers) if args.gaps else coverage_report()
        print(json.dumps(report, indent=2, default=str))
        return 0
    if args.cmd == "reindex":
        from .build import reindex_from_gaps

        cap = None if args.all or int(args.max_corpus_rows or 0) <= 0 else int(args.max_corpus_rows)
        results = reindex_from_gaps(
            upload=args.upload,
            slugs=args.slugs or None,
            limit=args.limit,
            max_corpus_rows=cap,
            skip_vectors=args.skip_vectors,
            workers=args.workers,
            mode=args.mode,
            force=args.force,
            all_indexable=args.all,
            device=args.device,
            renormalize=args.renormalize,
        )
        print(json.dumps(
            [
                {
                    "country": r.get("country"),
                    "skipped": r.get("skipped", False),
                    "out": r.get("out"),
                    "hub": (r.get("hub") or {}).get("url") if isinstance(r.get("hub"), dict) else r.get("hub"),
                    "error": r.get("error"),
                    "kind": (r.get("incremental") or {}).get("kind"),
                    "n_added": ((r.get("incremental") or {}).get("delta") or {}).get("n_added"),
                    "n_unchanged": ((r.get("incremental") or {}).get("delta") or {}).get("n_unchanged"),
                }
                for r in results
            ],
            indent=2,
            default=str,
        ))
        return 1 if any(r.get("error") for r in results) else 0
    if args.cmd == "verify":
        from .catalog import indexable_countries
        from .verify import verify_source

        slugs = []
        if args.all:
            slugs = [c["slug"] for c in indexable_countries()]
            if args.limit:
                slugs = slugs[: int(args.limit)]
        elif args.source:
            slugs = [args.source]
        else:
            print(json.dumps({"error": "pass --source or --all"}, indent=2))
            return 2
        rows = []
        failed = 0
        for slug in slugs:
            try:
                row = verify_source(slug)
            except Exception as exc:
                row = {"slug": slug, "error": str(exc), "verification": {"admitted": False}}
            rows.append(row)
            if not (row.get("verification") or {}).get("admitted", False):
                failed += 1
        from collections import Counter

        units = Counter(str(r.get("unit") or "") for r in rows)
        mismatch = []
        latin_blocked = []
        for r in rows:
            for chk in (r.get("verification") or {}).get("checks") or []:
                if chk.get("id") != "heading_language":
                    continue
                ev = chk.get("evidence") or {}
                if chk.get("severity") == "fail" and not chk.get("passed"):
                    latin_blocked.append(r.get("slug"))
                if "review samples" in str(chk.get("message") or ""):
                    mismatch.append(
                        {
                            "slug": r.get("slug"),
                            "document_language": ev.get("document_language"),
                            "heading_language": ev.get("heading_language"),
                        }
                    )
        print(
            json.dumps(
                {
                    "n": len(rows),
                    "n_failed": failed,
                    "by_unit": dict(units),
                    "heading_mismatch": mismatch,
                    "latin_split_blocked": latin_blocked,
                    "countries": rows,
                },
                indent=2,
                default=str,
            )
        )
        return 1 if failed else 0
    if args.cmd == "normalize-loop":
        from .build import CACHE, ROOT
        from .normalize_loop import (
            _apply_job,
            _scan_job,
            append_progress,
            apply_done,
            cache_packs,
            improve_from_reports,
            load_generate_text,
            run_parallel,
            scan_done,
            worker_count,
        )

        cache = Path(args.cache) if args.cache else CACHE
        reports = Path(args.reports) if args.reports else ROOT / "reports" / "residuals"
        out = Path(args.out) if args.out else ROOT / "llm-normalized"
        packs = cache_packs(cache, slug=args.slug)
        if args.limit:
            packs = packs[: int(args.limit)]
        workers = worker_count(args.workers)
        progress = Path(args.progress) if args.progress else ROOT / "reports" / f"normalize_{args.stage}.jsonl"

        def _pending(stage: str) -> tuple[list[tuple[str, str, str]], list[str]]:
            jobs: list[tuple[str, str, str]] = []
            skipped: list[str] = []
            for slug, path in packs:
                done = scan_done(reports, slug) if stage == "scan" else apply_done(out, slug)
                if done and not args.force:
                    skipped.append(slug)
                    continue
                dest = reports if stage == "scan" else out
                jobs.append((slug, str(path), str(dest)))
            return jobs, skipped

        def _run(stage: str, worker) -> list[dict]:
            jobs, skipped = _pending(stage)
            total = len(jobs) + len(skipped)
            done = len(skipped)
            print(json.dumps({
                "event": "start",
                "stage": stage,
                "workers": workers,
                "done": done,
                "pending": len(jobs),
                "total": total,
                "progress": str(progress),
            }), flush=True)
            state = {"done": done}

            def _on_done(row: dict) -> None:
                state["done"] += 1
                print(json.dumps({
                    "event": stage,
                    "done": state["done"],
                    "total": total,
                    **row,
                }), flush=True)

            return run_parallel(jobs, worker, workers, progress_path=progress, on_done=_on_done)

        if args.stage == "scan":
            rows = _run("scan", _scan_job)
            failed = [row for row in rows if row.get("error")]
            print(json.dumps({"stage": "scan", "workers": workers, "n": len(rows), "n_failed": len(failed)}, indent=2))
            return 1 if failed else 0
        if args.stage == "apply":
            rows = _run("apply", _apply_job)
            failed = [row for row in rows if row.get("error")]
            print(json.dumps({"stage": "apply", "workers": workers, "n": len(rows), "n_failed": len(failed)}, indent=2))
            return 1 if failed else 0
        def _on_pass(row: dict) -> None:
            print(json.dumps({"event": "improve", **row}, ensure_ascii=False), flush=True)
            append_progress(progress, {"event": "improve", **row})

        def _improve():
            print(json.dumps({
                "event": "start",
                "stage": "improve",
                "passes": args.passes,
                "reports": str(reports),
            }), flush=True)
            try:
                generate = load_generate_text()
            except Exception as exc:
                print(json.dumps({"error": f"llm_router unavailable: {exc}"}), flush=True)
                return None
            return improve_from_reports(
                reports,
                generate,
                max_passes=args.passes,
                on_pass=_on_pass,
                reset_unresolved=bool(args.force),
            )

        if args.stage == "improve":
            result = _improve()
            if result is None:
                return 1
            print(json.dumps({"stage": "improve", **result}, indent=2, ensure_ascii=False))
            return 0
        # run scans, then improves the script. Applying the script to every
        # pack is the separate ``apply`` stage.
        scan_rows = _run("scan", _scan_job)
        failed = [row for row in scan_rows if row.get("error")]
        if failed:
            print(json.dumps({"stage": "run", "n_scanned": len(scan_rows), "n_failed": len(failed)}, indent=2))
            return 1
        improved = _improve()
        if improved is None:
            return 1
        print(json.dumps(
            {"stage": "run", "workers": workers, "improve": improved, "n_scanned": len(scan_rows)},
            indent=2,
            ensure_ascii=False,
            default=str,
        ))
        return 0
    if args.cmd == "package-raw":
        from .build import RELEASES
        from .raw_package import default_instruments_dir, package_instruments

        instruments = (
            Path(args.instruments_dir)
            if args.instruments_dir
            else default_instruments_dir(args.iso or args.slug)
        )
        out = Path(args.out) if args.out else RELEASES / "raw-packs" / args.slug
        meta = package_instruments(
            instruments_dir=instruments,
            out=out,
            slug=args.slug,
            source_dataset=args.source_dataset,
            prior_pack=Path(args.prior_pack) if args.prior_pack else None,
        )
        print(json.dumps(meta, indent=2, default=str))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
