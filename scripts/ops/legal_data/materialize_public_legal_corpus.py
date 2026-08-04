#!/usr/bin/env python3
"""Materialize the public patent-law / regulations corpus for Hub release.

PATLAW-170 — deterministic public-official corpus projection covering
eCFR/CFR, U.S. Code / Public Law / Federal Register, and MPEP / guidance.

Default mode is **dry-run**: admission and content-addressed materialization
run in memory and a summary is printed. Local staging occurs only with
``--stage`` (and ``--output-dir``). This script never authenticates or uploads
to Hugging Face.

Input options (one required):

* ``--recipe`` — compact JSON recipe with ``source_roots`` + ``documents``
* ``--source-roots`` + ``--documents`` — separate JSON/NDJSON files
* ``--default-fixture`` — use the built-in multi-family CI recipe

Private, mixed, unknown, or unreviewed inputs fail closed before staging.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.domains.patent.public_legal_corpus_materializer import (  # noqa: E402
    CORPUS_ROOT_FILENAME,
    DOCUMENTS_FILENAME,
    MANIFEST_FILENAME,
    SCHEMA_VERSION,
    SOURCE_FAMILIES,
    SOURCE_RECEIPTS_FILENAME,
    TASK_ID,
    MissingSourceReceiptError,
    PrivateOrMixedInputError,
    PublicLegalCorpusError,
    PublicLegalCorpusMaterializer,
    UnreviewedRightsError,
    build_default_public_legal_recipe,
    load_manifest,
    validate_materialization,
)


def _load_json_object(path: Path) -> Mapping[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise SystemExit(f"expected JSON object in {path}")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize a deterministic public patent-law/regulations corpus "
            f"({TASK_ID}). Default: dry-run, no Hub upload."
        )
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--recipe",
        type=Path,
        help="Path to compact JSON recipe (source_roots + documents)",
    )
    input_group.add_argument(
        "--default-fixture",
        action="store_true",
        help="Use the built-in multi-family public fixture recipe",
    )
    input_group.add_argument(
        "--validate-manifest",
        type=Path,
        help="Load and validate an existing staged manifest, then exit",
    )
    input_group.add_argument(
        "--from-paths",
        action="store_true",
        help="Load separate --source-roots and --documents JSON/NDJSON files",
    )

    parser.add_argument(
        "--source-roots",
        type=Path,
        default=None,
        help="JSON/NDJSON of source root bindings (requires --from-paths)",
    )
    parser.add_argument(
        "--documents",
        type=Path,
        default=None,
        help="JSON/NDJSON of public legal documents (requires --from-paths)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Local staging directory (required with --stage)",
    )
    parser.add_argument(
        "--stage",
        action="store_true",
        help=(
            "Write local staged artifacts (manifest, documents.jsonl, "
            "source receipts, corpus-root pin). Default is dry-run only."
        ),
    )
    parser.add_argument(
        "--require-all-families",
        action="store_true",
        help=(
            "Require every source family "
            f"({', '.join(SOURCE_FAMILIES)}) to be present"
        ),
    )
    parser.add_argument(
        "--print-manifest",
        action="store_true",
        help="Print the corpus manifest JSON to stdout",
    )
    parser.add_argument(
        "--print-summary",
        action="store_true",
        default=True,
        help="Print a human-readable summary (default: on)",
    )
    parser.add_argument(
        "--no-print-summary",
        action="store_true",
        help="Suppress the human-readable summary",
    )
    parser.add_argument(
        "--list-families",
        action="store_true",
        help="Print supported source families and exit",
    )
    parser.add_argument(
        "--write-default-recipe",
        type=Path,
        default=None,
        help="Write the built-in fixture recipe to PATH and exit",
    )
    return parser


def _print_summary(result: Any) -> None:
    manifest = result.manifest
    print(f"task_id:              {TASK_ID}")
    print(f"schema_version:       {SCHEMA_VERSION}")
    print(f"mode:                 {result.mode.value}")
    print(f"partition:            {manifest.partition}")
    print(f"corpus_root_cid:      {manifest.corpus_root_cid}")
    print(f"corpus_digest_sha256: {manifest.corpus_digest_sha256}")
    print(f"document_count:       {manifest.counts.total_documents}")
    print(f"source_root_count:    {manifest.counts.source_root_count}")
    print(f"by_family:            {dict(manifest.counts.by_family)}")
    print(f"by_authority_kind:    {dict(manifest.counts.by_authority_kind)}")
    if result.output_dir:
        print(f"output_dir:           {result.output_dir}")
        print(f"  - {MANIFEST_FILENAME}")
        print(f"  - {DOCUMENTS_FILENAME}")
        print(f"  - {SOURCE_RECEIPTS_FILENAME}")
        print(f"  - {CORPUS_ROOT_FILENAME}")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    if args.list_families:
        for family in SOURCE_FAMILIES:
            print(family)
        return 0

    if args.write_default_recipe is not None:
        recipe = build_default_public_legal_recipe()
        target = args.write_default_recipe
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(recipe, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"wrote default recipe: {target}")
        return 0

    if args.validate_manifest is not None:
        try:
            manifest = load_manifest(args.validate_manifest)
        except PublicLegalCorpusError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"manifest_ok: true")
        print(f"corpus_root_cid: {manifest.corpus_root_cid}")
        print(f"document_count: {manifest.counts.total_documents}")
        return 0

    if args.stage and args.output_dir is None:
        parser.error("--output-dir is required with --stage")

    materializer = PublicLegalCorpusMaterializer(
        require_all_families=bool(args.require_all_families)
    )

    try:
        if args.default_fixture:
            recipe = build_default_public_legal_recipe()
            result = materializer.materialize_from_recipe(
                recipe,
                stage=bool(args.stage),
                output_dir=args.output_dir,
            )
        elif args.recipe is not None:
            recipe = _load_json_object(args.recipe)
            result = materializer.materialize_from_recipe(
                recipe,
                stage=bool(args.stage),
                output_dir=args.output_dir,
            )
        elif args.from_paths:
            if args.source_roots is None or args.documents is None:
                parser.error(
                    "--from-paths requires both --source-roots and --documents"
                )
            result = materializer.materialize_from_paths(
                roots_path=args.source_roots,
                documents_path=args.documents,
                stage=bool(args.stage),
                output_dir=args.output_dir,
            )
        else:
            parser.error("no materialization input selected")

        # Prove content-address stability for the admitted batch.
        receipt = validate_materialization(result)
        if not receipt.get("ok"):
            print("error: materialization validation failed", file=sys.stderr)
            return 2

    except PrivateOrMixedInputError as exc:
        print(f"error (private/mixed fail-closed): {exc}", file=sys.stderr)
        return 3
    except UnreviewedRightsError as exc:
        print(f"error (unreviewed rights): {exc}", file=sys.stderr)
        return 3
    except MissingSourceReceiptError as exc:
        print(f"error (source receipt): {exc}", file=sys.stderr)
        return 3
    except PublicLegalCorpusError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.print_manifest:
        print(result.manifest.to_canonical_json())
    elif not args.no_print_summary:
        _print_summary(result)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
