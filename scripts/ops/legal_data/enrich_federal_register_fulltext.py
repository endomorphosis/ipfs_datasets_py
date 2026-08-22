#!/usr/bin/env python3
"""Acquire official Federal Register body text and classify dispositions (LCR-053).

Reads the closed LCR-052 inventory (never rewriting it), fetches official
HTML/XML/PDF/GovInfo locators in source-precedence order, detects
anti-bot/navigation/error/placeholder content, and writes the typed
coverage receipt at
``docs/reports/legal_corpora_reindex/federal_fulltext_coverage.json``.

Default CI operation is offline and network-free::

    python scripts/ops/legal_data/enrich_federal_register_fulltext.py \
        --fixture-only --check

Live network full-text crawling is opt-in (``--live``) and never required
for the validation gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.federal_register_fulltext import (  # noqa: E402
    DEFAULT_LIVE_REPORT_RELPATH,
    DEFAULT_REPORT_RELPATH,
    GOAL_ID,
    SCHEMA_VERSION,
    SOURCE_PRECEDENCE,
    TASK_ID,
    BuiltinHttpsFulltextTransport,
    DocumentCoverage,
    FederalRegisterFulltextError,
    FulltextConfig,
    FulltextMode,
    ImmutableTextCache,
    InventoryRewriteError,
    LiveFulltextDisabledError,
    build_compact_coverage_recipe,
    build_fixture_coverage_report,
    check_coverage_report,
    classify_document,
    default_live_report_path,
    default_report_path,
    enrich_federal_register_fulltext,
    expand_coverage_payload,
    hydrate_live_inventory_documents,
    load_json_object,
    load_live_identity_sample_documents,
    render_check_summary,
    utc_now_z,
    write_coverage_report,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (  # noqa: E402
    DEFAULT_OBSERVATION_CUTOFF,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Acquire official Federal Register body text and classify every "
            f"missing-body disposition ({TASK_ID} / {GOAL_ID}, schema "
            f"{SCHEMA_VERSION}). Default fixture mode never contacts the network "
            "and never rewrites the official inventory."
        )
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Use the sealed offline fixture inventory and bodies (required for CI).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate the frozen coverage report (or the fixture coverage "
            "when the report is missing under --fixture-only) against sealed "
            "acceptance."
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the fixture coverage recipe to --report.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=(
            "Path to the frozen coverage report "
            f"(default: {default_report_path(REPOSITORY_ROOT)})"
        ),
    )
    parser.add_argument(
        "--observation-cutoff",
        default=DEFAULT_OBSERVATION_CUTOFF,
        help=(
            "Immutable UTC observation cutoff pin "
            f"(default: {DEFAULT_OBSERVATION_CUTOFF})."
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Enable live FederalRegister.gov / GovInfo full-text acquisition. "
            "Never required for CI; incompatible with --fixture-only. "
            "Refuses to overwrite the sealed fixture coverage recipe."
        ),
    )
    parser.add_argument(
        "--sample-identity",
        action="store_true",
        help=(
            "Live mode: classify the sealed live inventory identity sample "
            "instead of the full 11784-document frontier."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Live mode: classify at most N documents from the selected set.",
    )
    parser.add_argument(
        "--hydrate-live-inventory",
        action="store_true",
        help=(
            "Live mode: rehydrate the sealed 11784-document inventory into "
            "explicit locators without rewriting federal_inventory.json."
        ),
    )
    parser.add_argument(
        "--hydrate-cache",
        type=Path,
        default=None,
        help="Optional locator cache path used to resume hydration.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Live mode: skip legal_ids already present in --report.",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="With --resume, reclassify failed_final rows instead of skipping them.",
    )
    parser.add_argument(
        "--govinfo-html-only",
        action="store_true",
        help=(
            "Live mode: fetch only GovInfo HTML. FederalRegister.gov HTML/XML/PDF "
            "currently redirect to unblock.federalregister.gov."
        ),
    )
    parser.add_argument(
        "--flush-every",
        type=int,
        default=25,
        help="Live hydrate mode: write the checkpoint every N newly classified documents.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the coverage report JSON to stdout.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    live_default = default_live_report_path(REPOSITORY_ROOT)
    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report is not None
        else (live_default if args.live else default_report_path(REPOSITORY_ROOT))
    )

    try:
        if args.live and args.fixture_only:
            raise FederalRegisterFulltextError(
                "--live and --fixture-only are mutually exclusive"
            )
        if args.live and report_path.name == DEFAULT_REPORT_RELPATH.name:
            raise FederalRegisterFulltextError(
                "live coverage must not overwrite the sealed fixture recipe; "
                f"use {DEFAULT_LIVE_REPORT_RELPATH.as_posix()} or --report"
            )
        if (args.sample_identity or args.limit is not None) and not args.live:
            raise FederalRegisterFulltextError(
                "--sample-identity and --limit require --live"
            )
        if (
            args.hydrate_live_inventory
            or args.resume
            or args.retry_failed
            or args.govinfo_html_only
            or args.hydrate_cache is not None
        ) and not args.live:
            raise FederalRegisterFulltextError(
                "--hydrate-live-inventory, --resume, --retry-failed, "
                "--govinfo-html-only, and --hydrate-cache require --live"
            )
        if args.sample_identity and args.hydrate_live_inventory:
            raise FederalRegisterFulltextError(
                "--sample-identity and --hydrate-live-inventory are mutually exclusive"
            )

        if (args.check or args.write) and not args.fixture_only and not args.live:
            raise FederalRegisterFulltextError(
                "pass --fixture-only for the offline CI gate, or --live for "
                "network full-text acquisition"
            )

        if report_path.name == "federal_inventory.json":
            raise InventoryRewriteError(
                "refusing to write or check full-text coverage as the official "
                "inventory path"
            )

        if args.fixture_only:
            fixture_report = build_fixture_coverage_report(
                observation_cutoff=args.observation_cutoff,
            )
            recipe = build_compact_coverage_recipe(
                observation_cutoff=args.observation_cutoff,
            )

            raw_disk: Mapping[str, Any] | None = None
            if report_path.is_file():
                raw_disk = load_json_object(report_path)

            if args.write:
                write_coverage_report(recipe, report_path, replace=True)
                print(f"wrote coverage recipe: {report_path}", file=sys.stderr)
                raw_disk = recipe

            if args.check:
                fixture_result = check_coverage_report(fixture_report)
                if raw_disk is not None and raw_disk.get("mode") == "live":
                    print(
                        "live_structure_valid=True live_authority_replayed=False "
                        "authorizing=False "
                        f"digest={str(raw_disk.get('coverage_digest') or '')[:12]}"
                    )
                    report: Mapping[str, Any] = raw_disk
                    result = fixture_result
                elif raw_disk is not None:
                    result = check_coverage_report(raw_disk)
                    expanded = expand_coverage_payload(raw_disk)
                    disk_acceptance = dict(expanded.get("acceptance") or {})
                    fixture_acceptance = dict(fixture_report.get("acceptance") or {})
                    stable_keys = (
                        "every_inventory_document_classified",
                        "failed_final",
                        "failed_final_zero",
                        "no_placeholder_admitted",
                        "inventory_unmodified",
                        "secrets_absent",
                        "classified",
                        "full_text_admitted",
                        "metadata_only",
                        "excluded",
                        "quarantined",
                        "observation_cutoff",
                        "mode",
                        "previous_public_pin",
                        "inventory_task_id",
                        "all_expected_outputs_accounted",
                    )
                    disk_stable = {k: disk_acceptance.get(k) for k in stable_keys}
                    fixture_stable = {
                        k: fixture_acceptance.get(k) for k in stable_keys
                    }
                    if disk_stable != fixture_stable:
                        raise FederalRegisterFulltextError(
                            "on-disk report acceptance diverges from sealed fixture: "
                            f"disk={disk_stable} fixture={fixture_stable}"
                        )
                    report = expanded
                else:
                    report = fixture_report
                    result = fixture_result
                print(render_check_summary(result))
                if args.print_json:
                    sys.stdout.write(
                        json.dumps(dict(report), indent=2, sort_keys=True) + "\n"
                    )
                return 0

            if args.print_json:
                sys.stdout.write(
                    json.dumps(fixture_report, indent=2, sort_keys=True) + "\n"
                )
                return 0

            if args.write:
                return 0

            check_coverage_report(fixture_report)
            print(
                render_check_summary(
                    {
                        "ok": True,
                        "acceptance": fixture_report["acceptance"],
                        "frontier_closed": True,
                        "coverage_digest": fixture_report.get("coverage_digest"),
                        "classified": fixture_report["acceptance"]["classified"],
                    }
                )
            )
            print(
                "hint: pass --fixture-only --check to validate the frozen report",
                file=sys.stderr,
            )
            return 0

        if args.live:
            source_formats = (
                ("govinfo",) if args.govinfo_html_only else SOURCE_PRECEDENCE
            )
            if args.hydrate_live_inventory:
                cache_path = (
                    Path(args.hydrate_cache).expanduser()
                    if args.hydrate_cache is not None
                    else Path("/var/tmp/lcr-071-fr-fulltext/hydrated_documents.json")
                )
                documents, inventory_report = hydrate_live_inventory_documents(
                    repo_root=REPOSITORY_ROOT,
                    cache_path=cache_path,
                )
                sample_identity = False
            else:
                documents, inventory_report = load_live_identity_sample_documents(
                    repo_root=REPOSITORY_ROOT,
                    limit=args.limit,
                )
                sample_identity = True
                if not args.sample_identity and args.limit is None:
                    raise LiveFulltextDisabledError(
                        "pass --sample-identity for the sealed identity sample, "
                        "or --hydrate-live-inventory for the full live frontier"
                    )
            if args.limit is not None and args.hydrate_live_inventory:
                documents = documents[: args.limit]

            done_by_id: dict[str, dict[str, Any]] = {}
            if args.resume and report_path.is_file():
                existing = load_json_object(report_path)
                for item in existing.get("documents") or []:
                    if not isinstance(item, Mapping) or not item.get("legal_id"):
                        continue
                    category = str(item.get("category") or "")
                    if args.retry_failed and category in {
                        "failed_final",
                        "quarantined",
                    }:
                        continue
                    done_by_id[str(item["legal_id"])] = dict(item)

            remaining = [doc for doc in documents if doc.legal_id not in done_by_id]
            if args.hydrate_live_inventory:
                transport = BuiltinHttpsFulltextTransport()
                cache = ImmutableTextCache()
                classified_rows: list[dict[str, Any]] = [
                    done_by_id[doc.legal_id]
                    for doc in documents
                    if doc.legal_id in done_by_id
                ]
                errors: list[str] = []
                flush_every = max(1, int(args.flush_every or 25))
                started_at = utc_now_z()

                def _write_checkpoint(rows: list[dict[str, Any]]) -> dict[str, Any]:
                    payload = {
                        "schema": "ipfs_datasets_py/federal-register-fulltext-live-checkpoint@1",
                        "task_id": "LCR-071",
                        "goal_id": GOAL_ID,
                        "mode": "live",
                        "sample_identity": False,
                        "compact_recipe": False,
                        "authorizing_for_publication": False,
                        "inventory_unmodified": True,
                        "classified": len(rows),
                        "target": len(documents),
                        "failed_final": sum(
                            1 for row in rows if row.get("category") == "failed_final"
                        ),
                        "full_text_admitted": sum(
                            1
                            for row in rows
                            if row.get("category") == "full_text_admitted"
                        ),
                        "metadata_only": sum(
                            1 for row in rows if row.get("category") == "metadata_only"
                        ),
                        "excluded": sum(
                            1 for row in rows if row.get("category") == "excluded"
                        ),
                        "quarantined": sum(
                            1 for row in rows if row.get("category") == "quarantined"
                        ),
                        "errors": list(errors),
                        "observed_at": started_at,
                        "observation_cutoff": args.observation_cutoff,
                        "legal_ids": [row["legal_id"] for row in rows],
                        "documents": rows,
                    }
                    if args.write:
                        report_path.parent.mkdir(parents=True, exist_ok=True)
                        report_path.write_text(
                            json.dumps(payload, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                    return payload

                newly = 0
                try:
                    for document in remaining:
                        try:
                            coverage = classify_document(
                                document,
                                transport=transport,
                                cache=cache,
                                source_formats=source_formats,
                            )
                            classified_rows.append(coverage.to_dict())
                        except FederalRegisterFulltextError as exc:
                            errors.append(f"{document.legal_id}: {exc}")
                            classified_rows.append(
                                DocumentCoverage(
                                    legal_id=document.legal_id,
                                    document_number=document.document_number,
                                    publication_date=document.publication_date,
                                    disposition="failed_final",
                                    allowed_reason="official_body_unavailable",
                                    notes=str(exc),
                                ).to_dict()
                            )
                        newly += 1
                        if args.write and newly % flush_every == 0:
                            payload = _write_checkpoint(classified_rows)
                            print(
                                f"checkpoint classified={payload['classified']}/"
                                f"{payload['target']} admitted="
                                f"{payload['full_text_admitted']} failed_final="
                                f"{payload['failed_final']}",
                                file=sys.stderr,
                            )
                except KeyboardInterrupt:
                    _write_checkpoint(classified_rows)
                    print("interrupted; checkpoint written", file=sys.stderr)
                    return 130
                checkpoint = _write_checkpoint(classified_rows)
            else:
                result = enrich_federal_register_fulltext(
                    config=FulltextConfig(
                        observation_cutoff=args.observation_cutoff,
                        mode=FulltextMode.LIVE,
                        enable_builtin_https=True,
                        source_formats=source_formats,
                    ),
                    inventory_documents=documents,
                    inventory_report=inventory_report,
                )
                checkpoint = {
                    "schema": "ipfs_datasets_py/federal-register-fulltext-live-checkpoint@1",
                    "task_id": "LCR-071",
                    "goal_id": GOAL_ID,
                    "mode": "live",
                    "sample_identity": sample_identity,
                    "compact_recipe": False,
                    "authorizing_for_publication": False,
                    "inventory_unmodified": True,
                    "classified": result.classified_count,
                    "failed_final": result.failed_final,
                    "full_text_admitted": result.count("full_text_admitted"),
                    "metadata_only": result.count("metadata_only"),
                    "excluded": result.count("excluded"),
                    "quarantined": result.count("quarantined"),
                    "errors": list(result.errors),
                    "observed_at": result.observed_at,
                    "observation_cutoff": args.observation_cutoff,
                    "legal_ids": [doc.legal_id for doc in result.documents],
                    "documents": [doc.to_dict() for doc in result.documents],
                }
                if args.write:
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    report_path.write_text(
                        json.dumps(checkpoint, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    print(
                        f"wrote live full-text checkpoint: {report_path}",
                        file=sys.stderr,
                    )
            if args.write and args.hydrate_live_inventory:
                print(
                    f"wrote live full-text checkpoint: {report_path}",
                    file=sys.stderr,
                )
            if args.check:
                if int(checkpoint.get("classified") or 0) < 1:
                    raise FederalRegisterFulltextError(
                        "live full-text classified zero documents"
                    )
                print(
                    "ok=True "
                    f"classified={checkpoint.get('classified')} "
                    f"admitted={checkpoint.get('full_text_admitted')} "
                    f"failed_final={checkpoint.get('failed_final')} "
                    f"errors={len(checkpoint.get('errors') or [])}"
                )
            if args.print_json:
                sys.stdout.write(json.dumps(checkpoint, indent=2, sort_keys=True) + "\n")
            elif not args.check:
                print(
                    f"live classified={checkpoint.get('classified')} "
                    f"admitted={checkpoint.get('full_text_admitted')} "
                    f"failed_final={checkpoint.get('failed_final')}"
                )
            return 0 if not checkpoint.get("errors") else 1

        print(
            "error: pass --fixture-only (CI) or --live (network)",
            file=sys.stderr,
        )
        return 2
    except FederalRegisterFulltextError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
