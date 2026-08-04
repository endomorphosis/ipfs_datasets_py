#!/usr/bin/env python3
"""Package multi-artifact corpus + BM25 + vector + graph Hub release (PATLAW-174).

Assembles a multi-repo-compatible package binding the public legal corpus root
with production BM25, vector, and knowledge-graph index snapshots, Viewer
layout cards, counts, and rights/privacy metadata on every artifact.

Default mode is **dry-run**: packaging runs in memory and a summary is printed.
Local staging occurs only with ``--stage`` (and ``--output-dir``). This script
never authenticates or uploads to Hugging Face.

Input options (one required):

* ``--default-fixture`` — materialize the built-in multi-family CI corpus recipe
  and build BM25 / vector / graph indexes before packaging
* ``--recipe`` — compact corpus recipe JSON (source_roots + documents)
* ``--validate-manifest`` — load and validate an existing package manifest
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

from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (  # noqa: E402
    DEFAULT_VERSION_TAG,
    ORGANIZATION,
)
from ipfs_datasets_py.processors.domains.patent.hub_index_package import (  # noqa: E402
    ARTIFACTS_INVENTORY_FILENAME,
    INDEX_FAMILIES,
    LAYOUT_BUNDLE_FILENAME,
    MANIFEST_FILENAME,
    PACKAGE_ROOT_FILENAME,
    RECEIPT_FILENAME,
    SCHEMA_VERSION,
    TASK_ID,
    CorpusPinMismatchError,
    HubIndexPackageError,
    MissingIndexFamilyError,
    MissingRightsPrivacyError,
    PackageIntegrityError,
    PrivateOrMixedPackageError,
    SchemaValidationError,
    load_package_manifest,
    package_patent_legal_hub_indexes,
    validate_package,
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
            "Package multi-artifact corpus + BM25 + vector + graph Hub release "
            f"({TASK_ID}). Default: dry-run, no Hub upload."
        )
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--default-fixture",
        action="store_true",
        help=(
            "Materialize the built-in multi-family corpus fixture, build "
            "BM25/vector/graph indexes, and package them"
        ),
    )
    input_group.add_argument(
        "--recipe",
        type=Path,
        help="Path to compact public legal corpus recipe JSON",
    )
    input_group.add_argument(
        "--validate-manifest",
        type=Path,
        help="Load and validate an existing hub index package manifest JSON",
    )

    parser.add_argument(
        "--organization",
        default=ORGANIZATION,
        help=f"Lowercase Hub organization (default: {ORGANIZATION})",
    )
    parser.add_argument(
        "--version-tag",
        default=DEFAULT_VERSION_TAG,
        help=f"Layout/release version tag (default: {DEFAULT_VERSION_TAG})",
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
            "Write local staged package artifacts (manifest, layout cards, "
            "index pins, inventory). Default is dry-run only."
        ),
    )
    parser.add_argument(
        "--print-manifest",
        action="store_true",
        help="Print the package manifest JSON to stdout",
    )
    parser.add_argument(
        "--no-print-summary",
        action="store_true",
        help="Suppress the human-readable summary",
    )
    parser.add_argument(
        "--list-index-families",
        action="store_true",
        help="Print required index family names and exit",
    )
    return parser


def _print_summary(package: Any) -> None:
    manifest = package.manifest
    print(f"task_id:                 {TASK_ID}")
    print(f"schema_version:          {SCHEMA_VERSION}")
    print(f"mode:                    {package.mode.value}")
    print(f"partition:               {manifest.partition}")
    print(f"organization:            {manifest.organization}")
    print(f"version_tag:             {manifest.version_tag}")
    print(f"package_root_cid:        {manifest.package_root_cid}")
    print(f"package_digest_sha256:   {manifest.package_digest_sha256}")
    print(f"corpus_root_cid:         {manifest.corpus_root_cid}")
    print(f"bm25_root_cid:           {manifest.bm25_root_cid}")
    print(f"vector_root_cid:         {manifest.vector_root_cid}")
    print(f"graph_root_cid:          {manifest.graph_root_cid}")
    print(f"layout_bundle_cid:       {manifest.layout_bundle_cid}")
    print(
        f"index_families_present:  {', '.join(manifest.index_families_present)}"
    )
    counts = manifest.counts.to_dict()
    print(f"counts.corpus_documents: {counts['corpus_documents']}")
    print(f"counts.bm25_documents:   {counts['bm25_documents']}")
    print(f"counts.vector_documents: {counts['vector_documents']}")
    print(f"counts.graph_nodes:      {counts['graph_nodes']}")
    print(f"counts.artifact_count:   {counts['artifact_count']}")
    rights_privacy_ok = bool(manifest.rights_summary.get("all_reviewed")) and (
        manifest.privacy_summary.get("privacy_class") == "public"
    )
    print(f"rights_privacy_ok:       {rights_privacy_ok}")
    if package.output_dir:
        print(f"output_dir:              {package.output_dir}")
        print(f"  - {MANIFEST_FILENAME}")
        print(f"  - {PACKAGE_ROOT_FILENAME}")
        print(f"  - {RECEIPT_FILENAME}")
        print(f"  - {LAYOUT_BUNDLE_FILENAME}")
        print(f"  - {ARTIFACTS_INVENTORY_FILENAME}")
        print("  - indexes/{corpus,bm25,vectors,knowledge_graph}/...")
        print("  - repos/{patent-legal-*}/*")


def main(argv: Sequence[str] | None = None) -> int:
    # Support --list-index-families without requiring the exclusive input group.
    raw = list(argv) if argv is not None else sys.argv[1:]
    if "--list-index-families" in raw and not any(
        flag in raw
        for flag in (
            "--default-fixture",
            "--recipe",
            "--validate-manifest",
        )
    ):
        for name in INDEX_FAMILIES:
            print(name)
        return 0

    parser = _parser()
    args = parser.parse_args(argv)

    if args.list_index_families and args.validate_manifest is None and not (
        args.default_fixture or args.recipe is not None
    ):
        for name in INDEX_FAMILIES:
            print(name)
        return 0

    # Explicit contract: this CLI has no upload path.
    if getattr(args, "upload", None) or getattr(args, "push", None):
        parser.error("remote upload is not supported by this packager")

    if args.validate_manifest is not None:
        try:
            manifest = load_package_manifest(args.validate_manifest)
        except (HubIndexPackageError, SchemaValidationError, MissingIndexFamilyError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print("manifest_ok: true")
        print(f"package_root_cid: {manifest.package_root_cid}")
        print(f"corpus_root_cid: {manifest.corpus_root_cid}")
        print(f"bm25_root_cid: {manifest.bm25_root_cid}")
        print(f"vector_root_cid: {manifest.vector_root_cid}")
        print(f"graph_root_cid: {manifest.graph_root_cid}")
        print(f"index_families: {', '.join(manifest.index_families_present)}")
        return 0

    dry_run = not bool(args.stage)
    if not dry_run and args.output_dir is None:
        parser.error("--output-dir is required when --stage is set")

    try:
        if args.default_fixture:
            package = package_patent_legal_hub_indexes(
                default_fixture=True,
                organization=args.organization,
                version_tag=args.version_tag,
                stage=bool(args.stage),
                output_dir=args.output_dir,
            )
        else:
            recipe = _load_json_object(args.recipe)
            package = package_patent_legal_hub_indexes(
                recipe=recipe,
                organization=args.organization,
                version_tag=args.version_tag,
                stage=bool(args.stage),
                output_dir=args.output_dir,
            )
        validation = validate_package(package)
    except MissingIndexFamilyError as exc:
        print(f"ERROR: missing index family: {exc}", file=sys.stderr)
        return 2
    except MissingRightsPrivacyError as exc:
        print(f"ERROR: rights/privacy gate: {exc}", file=sys.stderr)
        return 2
    except PrivateOrMixedPackageError as exc:
        print(f"ERROR: rejected private/mixed package: {exc}", file=sys.stderr)
        return 2
    except CorpusPinMismatchError as exc:
        print(f"ERROR: corpus pin mismatch: {exc}", file=sys.stderr)
        return 2
    except PackageIntegrityError as exc:
        print(f"ERROR: package integrity: {exc}", file=sys.stderr)
        return 2
    except (HubIndexPackageError, SchemaValidationError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not args.no_print_summary:
        _print_summary(package)
        print(f"validation_ok:           {validation.get('ok')}")

    if args.print_manifest:
        print(json.dumps(package.manifest.to_dict(), indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
