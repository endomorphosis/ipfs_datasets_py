#!/usr/bin/env python3
"""Build a production BM25 index snapshot for the public legal corpus.

PATLAW-171 — deterministic documents/terms/postings BM25 snapshot bound to a
pinned public patent-law / regulations corpus root (PATLAW-170).

Default mode is **dry-run**: admission, indexing, and content-addressing run
in memory and a summary is printed. Local staging occurs only with
``--stage`` (and ``--output-dir``). This script never authenticates or uploads
to Hugging Face.

Input options (one required):

* ``--default-fixture`` — materialize the built-in multi-family CI corpus recipe
  and build BM25 over it
* ``--corpus-dir`` — load a staged public legal corpus directory
* ``--recipe`` — compact corpus recipe JSON (source_roots + documents)
* ``--validate-snapshot`` — load and validate an existing staged BM25 snapshot
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

from ipfs_datasets_py.processors.domains.patent.public_legal_bm25_builder import (  # noqa: E402
    DOCUMENTS_FILENAME,
    INDEX_ROOT_FILENAME,
    MANIFEST_FILENAME,
    POSTINGS_FILENAME,
    RECEIPT_FILENAME,
    SCHEMA_VERSION,
    TASK_ID,
    TERMS_FILENAME,
    CorpusPinError,
    OrphanDocumentError,
    OrphanPostingError,
    OrphanTermError,
    PrivateOrMixedInputError,
    PublicLegalBm25Builder,
    PublicLegalBm25Error,
    build_public_legal_bm25_index,
    load_bm25_manifest,
    load_bm25_snapshot,
    validate_snapshot,
)
from ipfs_datasets_py.processors.domains.patent.public_legal_corpus_materializer import (  # noqa: E402
    build_default_public_legal_recipe,
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
            "Build a deterministic public legal BM25 index snapshot "
            f"({TASK_ID}). Default: dry-run, no Hub upload."
        )
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--default-fixture",
        action="store_true",
        help="Materialize the built-in multi-family corpus fixture and build BM25",
    )
    input_group.add_argument(
        "--corpus-dir",
        type=Path,
        help="Path to a staged public legal corpus directory",
    )
    input_group.add_argument(
        "--recipe",
        type=Path,
        help="Path to compact public legal corpus recipe JSON",
    )
    input_group.add_argument(
        "--validate-snapshot",
        type=Path,
        help="Load and validate an existing staged BM25 snapshot directory",
    )
    input_group.add_argument(
        "--validate-manifest",
        type=Path,
        help="Load and validate an existing BM25 manifest JSON, then exit",
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
            "Write local staged artifacts (manifest, documents/terms/postings "
            "JSONL, snapshot receipt, index-root pin). Default is dry-run only."
        ),
    )
    parser.add_argument(
        "--expected-corpus-root-cid",
        type=str,
        default=None,
        help="Fail closed if the corpus root CID does not match this pin",
    )
    parser.add_argument(
        "--require-all-families",
        action="store_true",
        default=True,
        help="Require every public legal source family (default: on for fixtures)",
    )
    parser.add_argument(
        "--no-require-all-families",
        action="store_true",
        help="Allow a subset of source families",
    )
    parser.add_argument(
        "--k1",
        type=float,
        default=1.5,
        help="Okapi BM25 k1 parameter (default: 1.5)",
    )
    parser.add_argument(
        "--b",
        type=float,
        default=0.75,
        help="Okapi BM25 b parameter (default: 0.75)",
    )
    parser.add_argument(
        "--print-manifest",
        action="store_true",
        help="Print the BM25 snapshot manifest JSON to stdout",
    )
    parser.add_argument(
        "--print-receipt",
        action="store_true",
        help="Print the compact snapshot receipt JSON to stdout",
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
    return parser


def _print_summary(result: Any) -> None:
    manifest = result.manifest
    print(f"task_id:              {TASK_ID}")
    print(f"schema_version:       {SCHEMA_VERSION}")
    print(f"mode:                 {result.mode.value}")
    print(f"partition:            {manifest.partition}")
    print(f"corpus_root_cid:      {manifest.corpus_root_cid}")
    print(f"index_cid:            {manifest.index_cid}")
    print(f"index_digest_sha256:  {manifest.index_digest_sha256}")
    print(f"document_count:       {manifest.counts.document_count}")
    print(f"term_count:           {manifest.counts.term_count}")
    print(f"posting_count:        {manifest.counts.posting_count}")
    print(f"total_tokens:         {manifest.counts.total_tokens}")
    print(f"tokenizer_version:    {manifest.tokenizer_version}")
    print(f"by_family:            {dict(manifest.counts.by_family)}")
    print(f"by_field:             {dict(manifest.counts.by_field)}")
    if result.output_dir:
        print(f"output_dir:           {result.output_dir}")
        print(f"  - {MANIFEST_FILENAME}")
        print(f"  - {DOCUMENTS_FILENAME}")
        print(f"  - {TERMS_FILENAME}")
        print(f"  - {POSTINGS_FILENAME}")
        print(f"  - {RECEIPT_FILENAME}")
        print(f"  - {INDEX_ROOT_FILENAME}")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    if args.validate_manifest is not None:
        try:
            manifest = load_bm25_manifest(args.validate_manifest)
        except PublicLegalBm25Error as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print("manifest_ok: true")
        print(f"index_cid: {manifest.index_cid}")
        print(f"corpus_root_cid: {manifest.corpus_root_cid}")
        print(f"document_count: {manifest.counts.document_count}")
        print(f"term_count: {manifest.counts.term_count}")
        print(f"posting_count: {manifest.counts.posting_count}")
        return 0

    if args.validate_snapshot is not None:
        try:
            snapshot = load_bm25_snapshot(args.validate_snapshot)
            receipt = validate_snapshot(snapshot)
        except PublicLegalBm25Error as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print("snapshot_ok: true")
        print(f"index_cid: {receipt['index_cid']}")
        print(f"corpus_root_cid: {receipt['corpus_root_cid']}")
        print(f"document_count: {receipt['document_count']}")
        print(f"term_count: {receipt['term_count']}")
        print(f"posting_count: {receipt['posting_count']}")
        return 0

    if args.stage and args.output_dir is None:
        parser.error("--output-dir is required with --stage")

    require_all = bool(args.require_all_families) and not bool(
        args.no_require_all_families
    )

    try:
        if args.default_fixture:
            result = build_public_legal_bm25_index(
                recipe=build_default_public_legal_recipe(),
                require_all_families=require_all,
                stage=bool(args.stage),
                output_dir=args.output_dir,
                expected_corpus_root_cid=args.expected_corpus_root_cid,
                k1=float(args.k1),
                b=float(args.b),
            )
        elif args.recipe is not None:
            recipe = _load_json_object(args.recipe)
            result = build_public_legal_bm25_index(
                recipe=recipe,
                require_all_families=require_all,
                stage=bool(args.stage),
                output_dir=args.output_dir,
                expected_corpus_root_cid=args.expected_corpus_root_cid,
                k1=float(args.k1),
                b=float(args.b),
            )
        elif args.corpus_dir is not None:
            result = PublicLegalBm25Builder(
                k1=float(args.k1), b=float(args.b)
            ).build_from_corpus_dir(
                args.corpus_dir,
                stage=bool(args.stage),
                output_dir=args.output_dir,
                expected_corpus_root_cid=args.expected_corpus_root_cid,
            )
        else:
            parser.error("no build input selected")

        receipt = validate_snapshot(result)
        if not receipt.get("ok"):
            print("error: snapshot validation failed", file=sys.stderr)
            return 2

    except (OrphanTermError, OrphanPostingError, OrphanDocumentError) as exc:
        print(f"error (orphan fail-closed): {exc}", file=sys.stderr)
        return 3
    except PrivateOrMixedInputError as exc:
        print(f"error (private/mixed fail-closed): {exc}", file=sys.stderr)
        return 3
    except CorpusPinError as exc:
        print(f"error (corpus pin): {exc}", file=sys.stderr)
        return 3
    except PublicLegalBm25Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.print_manifest:
        print(result.manifest.to_canonical_json())
    elif args.print_receipt:
        print(json.dumps(result.manifest.to_receipt(), sort_keys=True, separators=(",", ":")))
    elif not args.no_print_summary:
        _print_summary(result)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
