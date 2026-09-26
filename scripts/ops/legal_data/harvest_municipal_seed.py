#!/usr/bin/env python3
"""Harvest the US GNIS/Wikidata crosswalk and the Netherlands pilot seed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def _bootstrap_pythonpath() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


_bootstrap_pythonpath()

from ipfs_datasets_py.processors.legal_scrapers.municipal.seed_harvest import (  # noqa: E402
    harvest_netherlands,
    harvest_us,
    seed_root,
    summarize,
    write_report,
)

DEFAULT_US_SEED = (
    Path(__file__).resolve().parents[3]
    / "ipfs_datasets_py"
    / "processors"
    / "legal_scrapers"
    / "us_towns_and_counties_urls.jsonl"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Harvest municipal jurisdiction seeds from Wikidata.")
    parser.add_argument("--us-seed", default=str(DEFAULT_US_SEED), help="Existing US GNIS JSONL seed.")
    parser.add_argument("--dest", default="", help="Seed directory. Defaults to municipal/seeds.")
    parser.add_argument("--batch-size", type=int, default=80)
    parser.add_argument("--delay", type=float, default=0.6)
    parser.add_argument("--limit", type=int, default=0, help="US rows to harvest. 0 means all.")
    parser.add_argument("--skip-us", action="store_true")
    parser.add_argument("--skip-nl", action="store_true")
    parser.add_argument(
        "--world",
        action="store_true",
        help="Harvest municipality subclasses from Wikidata for every country.",
    )
    parser.add_argument(
        "--gap",
        action="store_true",
        help="Harvest local-government classes that are not municipality subclasses. Does not replace the US or Netherlands seeds.",
    )
    parser.add_argument(
        "--provinces",
        action="store_true",
        help="Harvest states, provinces, and other first-level divisions, then any new municipality classes. Does not replace the US or Netherlands seeds.",
    )
    parser.add_argument(
        "--catalog",
        action="store_true",
        help="Walk Wikidata classes for municipalities and first-level divisions and write class_catalog.json. Does not fetch places.",
    )
    parser.add_argument(
        "--relevel",
        action="store_true",
        help="Retag class_catalog.json so districts and parishes are their own levels. Does not fetch places.",
    )
    parser.add_argument(
        "--traverse",
        action="store_true",
        help="Fetch catalog classes that are not done. Ambiguous labels go to llm_router. Does not replace the US or Netherlands seeds.",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Find government classes for mapped countries with fewer than 20 places and fetch them.",
    )
    parser.add_argument("--class-limit", type=int, default=0, help="Stop after this many Wikidata classes. 0 means all.")
    parser.add_argument("--only-class", default="", help="Fetch one municipality class QID.")
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Fill missing country codes and retry classes Wikidata timed out on.",
    )
    parser.add_argument(
        "--code-links",
        default="",
        help="Comma-separated country codes whose homepages should be sampled for code links.",
    )
    parser.add_argument("--sample-limit", type=int, default=36)
    parser.add_argument(
        "--all-homepages",
        action="store_true",
        help="Scan every remaining homepage for the --code-links countries, resuming from the existing file.",
    )
    parser.add_argument(
        "--retag-vendors",
        action="store_true",
        help="Relabel stored code-host links with the current vendor map. Does not fetch pages.",
    )
    parser.add_argument(
        "--list-platforms",
        default="",
        help="sede, saturn, saturn-notices, sede-retry. Lists links and current notices. Does not download files.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=4,
        help="Sede board pages per town, including the first page.",
    )
    parser.add_argument("--workers", type=int, default=6)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    dest = Path(args.dest).expanduser() if args.dest else seed_root()
    if args.retag_vendors:
        from ipfs_datasets_py.processors.legal_scrapers.municipal.code_links import refresh_stored_links

        out_dir = dest / "code_hosts"
        wanted = {
            part.strip().upper()
            for part in str(args.code_links).split(",")
            if part.strip()
        }
        paths = sorted(out_dir.glob("*.jsonl"))
        if wanted:
            paths = [path for path in paths if path.stem.upper() in wanted]
        report = {path.stem: refresh_stored_links(path) for path in paths}
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    if args.list_platforms:
        from ipfs_datasets_py.processors.legal_scrapers.municipal.code_docs import (
            refresh_sede_incomplete,
            scan_saturn_notices,
            scan_saturn_types,
            scan_sede_boards,
            summarize_listed,
        )
        from ipfs_datasets_py.processors.legal_scrapers.municipal.code_links import load_country_rows

        wanted = {part.strip().lower() for part in str(args.list_platforms).split(",") if part.strip()}
        out_dir = dest / "code_docs"
        out_dir.mkdir(parents=True, exist_ok=True)
        limit = args.limit or None
        report: dict[str, object] = {}
        if "sede" in wanted:
            rows = load_country_rows(dest / "code_hosts" / "ES.jsonl")
            path = out_dir / "ES_sede_board.jsonl"
            scan_sede_boards(
                rows,
                path,
                workers=min(4, args.workers),
                delay=args.delay,
                max_pages=args.max_pages,
                limit=limit,
            )
            report["sede"] = summarize_listed(path)
        if "saturn" in wanted:
            rows = load_country_rows(dest / "code_hosts" / "IT.jsonl")
            path = out_dir / "IT_saturnweb_types.jsonl"
            scan_saturn_types(rows, path, workers=args.workers, delay=max(args.delay, 0.3), limit=limit)
            report["saturn"] = summarize_listed(path)
        if "saturn-notices" in wanted:
            rows = load_country_rows(dest / "code_hosts" / "IT.jsonl")
            path = out_dir / "IT_saturnweb_notices.jsonl"
            scan_saturn_notices(rows, path, workers=args.workers, delay=max(args.delay, 0.25), limit=limit)
            report["saturn-notices"] = summarize_listed(path)
        if "sede-retry" in wanted:
            path = out_dir / "ES_sede_board.jsonl"
            report["sede-retry"] = refresh_sede_incomplete(
                path,
                workers=min(4, args.workers),
                delay=args.delay,
                max_pages=max(args.max_pages, 12),
            )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    if args.code_links:
        from ipfs_datasets_py.processors.legal_scrapers.municipal.code_links import (
            discover_country,
            load_country_rows,
            scan_homepages,
            summarize_discoveries,
        )
        from ipfs_datasets_py.processors.legal_scrapers.regions.mapping import region_for_country

        out_dir = dest / "code_hosts"
        out_dir.mkdir(parents=True, exist_ok=True)
        report: dict[str, object] = {}
        for iso in [part.strip().upper() for part in str(args.code_links).split(",") if part.strip()]:
            region = region_for_country(iso)
            path = dest / region / f"{iso}.jsonl"
            rows = load_country_rows(path)
            dest_path = out_dir / f"{iso}.jsonl"
            if args.all_homepages:
                report[iso] = scan_homepages(
                    rows,
                    iso,
                    dest_path,
                    workers=args.workers,
                    delay=args.delay,
                )
                continue
            found = discover_country(rows, iso, limit=args.sample_limit, delay=args.delay)
            with dest_path.open("w", encoding="utf-8") as handle:
                for row in found:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            report[iso] = {"path": str(dest_path), **summarize_discoveries(found)}
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    if args.repair:
        from ipfs_datasets_py.processors.legal_scrapers.municipal.world_seed import (
            fill_country_codes,
            finalize_world,
            parts_root,
            refetch_failed_classes,
        )

        part_dir = parts_root()
        filled = fill_country_codes(part_dir, delay=args.delay)
        recovered = refetch_failed_classes(part_dir, delay=args.delay)
        summary = finalize_world(dest, part_dir)
        summary["countries_filled"] = filled
        summary["recovered"] = recovered
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0
    if args.audit:
        import importlib.util

        from ipfs_datasets_py.processors.legal_scrapers.municipal.traverse import (
            _fetch_queue,
            audit_targets,
            country_class_histogram,
            country_qids,
            journal_qids,
            select_audit_classes,
        )
        from ipfs_datasets_py.processors.legal_scrapers.municipal.world_seed import (
            _load_progress,
            finalize_world,
            parts_root,
        )

        mapping_path = Path(__file__).resolve().parents[3] / "ipfs_datasets_py/processors/legal_scrapers/regions/mapping.py"
        spec = importlib.util.spec_from_file_location("region_mapping", mapping_path)
        mapping = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mapping)
        summary_path = dest / "world_summary.json"
        counts = {}
        if summary_path.is_file():
            counts = json.loads(summary_path.read_text(encoding="utf-8")).get("by_country") or {}
        targets = audit_targets(counts, sorted(mapping.COUNTRY_TO_REGION))
        print(f"audit countries {len(targets)}", flush=True)
        qids = country_qids(targets)
        print(f"audit qids {len(qids)}", flush=True)
        histograms: list[dict[str, object]] = []
        for index, iso in enumerate(targets, start=1):
            country = qids.get(iso)
            if not country:
                print(f"NOQID {index}/{len(targets)} {iso}", flush=True)
                continue
            try:
                rows = country_class_histogram(country)
            except Exception as exc:
                print(f"FAIL {index}/{len(targets)} {iso} {type(exc).__name__}", flush=True)
                continue
            print(f"HIST {index}/{len(targets)} {iso} classes {len(rows)}", flush=True)
            histograms.extend(rows)
        part_dir = parts_root()
        progress = _load_progress(part_dir / "progress.json")
        done = set(progress.get("done") or []) | journal_qids(dest / "traverse_journal.jsonl")
        chosen = select_audit_classes(histograms, done)
        print(f"audit fetch {len(chosen)}", flush=True)
        fetched, places, errors = _fetch_queue(chosen, part_dir, progress, done, dest / "traverse_journal.jsonl", args.delay)
        summary = finalize_world(dest, part_dir) if fetched else {"countries": 0, "rows": 0}
        print(json.dumps({"fetched_classes": fetched, "places": places, "errors": errors, "countries": summary.get("countries"), "rows": summary.get("rows")}, indent=2))
        return 0
    if args.relevel:
        from ipfs_datasets_py.processors.legal_scrapers.municipal.world_seed import assemble_catalog

        catalog_path = dest / "class_catalog.json"
        records = json.loads(catalog_path.read_text(encoding="utf-8"))
        releveled = assemble_catalog(
            [
                {
                    "qid": row["qid"],
                    "label": row["label"],
                    "role": row.get("role") or "municipality",
                    "depth": row.get("depth") or 0,
                    "root": row.get("root") or "",
                }
                for row in records
            ],
            done=[row["qid"] for row in records if row.get("done")],
        )
        catalog_path.write_text(json.dumps(releveled, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        new = [row for row in releveled if not row.get("done")]
        levels: dict[str, int] = {}
        for row in new:
            key = str(row.get("admin_level") or "")
            levels[key] = levels.get(key, 0) + 1
        print(json.dumps({"classes": len(releveled), "new": len(new), "new_levels": levels}, indent=2))
        return 0
    if args.traverse:
        from ipfs_datasets_py.processors.legal_scrapers.municipal.traverse import traverse_catalog

        def generate(prompt: str) -> str:
            from ipfs_datasets_py.llm_router import generate_text

            from ipfs_datasets_py.processors.legal_scrapers.municipal.traverse import reply_text

            return reply_text(generate_text(prompt, max_tokens=500))

        summary = traverse_catalog(dest, generate=generate, delay=args.delay, limit=args.limit or None)
        print(json.dumps({key: summary[key] for key in ("fetched_classes", "places", "dropped", "still_open", "journal", "countries", "rows") if key in summary}, indent=2))
        return 0
    if args.catalog:
        from ipfs_datasets_py.processors.legal_scrapers.municipal.world_seed import write_class_catalog

        summary = write_class_catalog(dest)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0
    if args.provinces:
        from ipfs_datasets_py.processors.legal_scrapers.municipal.world_seed import (
            GAP_CLASSES,
            harvest_named_classes,
            province_classes,
        )

        summary = harvest_named_classes(
            dest,
            province_classes(),
            delay=args.delay,
            admin_level="from-label",
        )
        summary["municipal_gap"] = harvest_named_classes(dest, GAP_CLASSES, delay=args.delay)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0
    if args.gap:
        from ipfs_datasets_py.processors.legal_scrapers.municipal.world_seed import (
            GAP_CLASSES,
            harvest_named_classes,
        )

        summary = harvest_named_classes(dest, GAP_CLASSES, delay=args.delay)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0
    if args.world or args.only_class:
        from ipfs_datasets_py.processors.legal_scrapers.municipal.world_seed import harvest_world

        summary = harvest_world(
            dest,
            delay=args.delay,
            class_limit=args.class_limit or None,
            only_class=str(args.only_class or ""),
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0
    us_rows: list[dict] = []
    nl_rows: list[dict] = []
    us_seeds: list[dict] = []
    paths: dict[str, str] = {}
    if not args.skip_us:
        from ipfs_datasets_py.processors.legal_scrapers.municipal.seed_harvest import load_us_seed

        us_seeds = load_us_seed(Path(args.us_seed))
        if args.limit:
            us_seeds = us_seeds[: args.limit]
        result = harvest_us(
            Path(args.us_seed),
            dest,
            batch_size=args.batch_size,
            delay=args.delay,
            limit=args.limit or None,
        )
        us_rows = result["rows"]
        paths["us"] = str(result["us_path"])
        paths["crosswalk"] = str(result["crosswalk_path"])
    if not args.skip_nl:
        result = harvest_netherlands(dest, delay=args.delay)
        nl_rows = result["rows"]
        paths["nl"] = str(result["path"])
    report = summarize(us_rows, nl_rows, us_seeds=us_seeds)
    report["paths"] = paths
    report_path = write_report(dest, report)
    print(json.dumps({"report": str(report_path), **report}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
