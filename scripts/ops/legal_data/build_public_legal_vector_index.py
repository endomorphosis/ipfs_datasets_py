#!/usr/bin/env python3
"""Build a production vector index snapshot for the public legal corpus.

PATLAW-172 — binds the pinned local embedding model and public corpus root into
a content-addressed vector index snapshot. Private / mixed inputs fail closed.
Default mode is **dry-run** (in-memory). Local staging requires ``--stage``
and ``--output-dir``. Never authenticates or uploads to Hugging Face.

Input options (one required):

* ``--default-fixture`` — multi-family public legal CI recipe (via PATLAW-170)
* ``--recipe`` — compact JSON recipe (source_roots + documents)
* ``--from-corpus-dir`` — staged PATLAW-170 corpus directory
* ``--validate-manifest`` — load and validate an existing vector manifest
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
    DOCUMENTS_FILENAME,
    MANIFEST_FILENAME as CORPUS_MANIFEST_FILENAME,
    MaterializationMode,
    PublicLegalCorpusError,
    PublicLegalCorpusMaterialization,
    PublicLegalDocument,
    load_manifest as load_corpus_manifest,
)
from ipfs_datasets_py.processors.domains.patent.public_legal_vector_builder import (  # noqa: E402
    DEFAULT_CREATED_UTC,
    DEFAULT_MODEL_PIN,
    EMBEDDING_RECEIPT_FILENAME,
    MANIFEST_FILENAME,
    SCHEMA_VERSION,
    SNAPSHOT_FILENAME,
    TASK_ID,
    VECTORS_FILENAME,
    VECTOR_ROOT_FILENAME,
    CorpusRootError,
    ModelPinError,
    PrivateTextRejectedError,
    PublicLegalVectorBuilder,
    PublicLegalVectorError,
    load_manifest,
    validate_build,
    validate_build_stable,
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


def _load_documents_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"invalid NDJSON on line {line_no} of {path}: {exc}"
            ) from exc
        if not isinstance(value, Mapping):
            raise SystemExit(f"documents.jsonl line {line_no} must be an object")
        rows.append(dict(value))
    return rows


def _materialization_from_staged_corpus(
    corpus_dir: Path,
) -> PublicLegalCorpusMaterialization:
    manifest_path = corpus_dir / CORPUS_MANIFEST_FILENAME
    docs_path = corpus_dir / DOCUMENTS_FILENAME
    if not manifest_path.is_file():
        raise SystemExit(f"corpus manifest not found: {manifest_path}")
    if not docs_path.is_file():
        raise SystemExit(f"corpus documents not found: {docs_path}")
    manifest = load_corpus_manifest(manifest_path)
    documents = tuple(
        PublicLegalDocument.from_dict(row) for row in _load_documents_jsonl(docs_path)
    )
    mode_raw = str(getattr(manifest, "mode", "") or MaterializationMode.STAGE.value)
    try:
        mode = MaterializationMode(mode_raw)
    except ValueError:
        mode = MaterializationMode.STAGE
    return PublicLegalCorpusMaterialization(
        documents=documents,
        manifest=manifest,
        mode=mode,
        output_dir=str(corpus_dir.resolve()),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a production public legal vector index snapshot "
            f"({TASK_ID}). Default: dry-run, no Hub upload."
        )
    )
    input_group = parser.add_mutually_exclusive_group(required=False)
    input_group.add_argument(
        "--default-fixture",
        action="store_true",
        help="Use the built-in multi-family public legal fixture recipe",
    )
    input_group.add_argument(
        "--recipe",
        type=Path,
        help="Path to compact JSON recipe (source_roots + documents)",
    )
    input_group.add_argument(
        "--from-corpus-dir",
        type=Path,
        help=(
            "Directory with staged PATLAW-170 corpus artifacts "
            f"({CORPUS_MANIFEST_FILENAME} + {DOCUMENTS_FILENAME})"
        ),
    )
    input_group.add_argument(
        "--validate-manifest",
        type=Path,
        help="Load and validate an existing staged vector manifest, then exit",
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
            "Write local staged artifacts (manifest, vectors.jsonl, "
            "vector-root pin, snapshot). Default is dry-run only."
        ),
    )
    parser.add_argument(
        "--created-utc",
        default=DEFAULT_CREATED_UTC,
        help=(
            "Fixed ISO-8601 UTC timestamp for snapshot manifests "
            f"(default: {DEFAULT_CREATED_UTC})"
        ),
    )
    parser.add_argument(
        "--print-manifest",
        action="store_true",
        help="Print the vector manifest JSON to stdout",
    )
    parser.add_argument(
        "--no-print-summary",
        action="store_true",
        help="Suppress the human-readable summary",
    )
    parser.add_argument(
        "--prove-stable",
        action="store_true",
        help="Rebuild once and require identical index root under fixed pins",
    )
    parser.add_argument(
        "--list-model-pin",
        action="store_true",
        help="Print the production model pin and exit",
    )
    return parser


def _print_summary(result: Any) -> None:
    manifest = result.manifest
    print(f"task_id:              {TASK_ID}")
    print(f"schema_version:       {SCHEMA_VERSION}")
    print(f"mode:                 {result.mode.value}")
    print(f"partition:            {manifest.partition}")
    print(f"model_pin:            {manifest.model_pin}")
    print(f"dimension:            {manifest.dimension}")
    print(f"corpus_root_cid:      {manifest.corpus_root_cid}")
    print(f"corpus_digest_sha256: {manifest.corpus_digest_sha256}")
    print(f"index_root_cid:       {manifest.index_root_cid}")
    print(f"index_digest_sha256:  {manifest.index_digest_sha256}")
    print(f"snapshot_root_cid:    {manifest.snapshot_root_cid}")
    print(f"document_count:       {manifest.document_count}")
    print(f"vector_count:         {manifest.vector_count}")
    if result.output_dir:
        print(f"output_dir:           {result.output_dir}")
        print(f"  - {MANIFEST_FILENAME}")
        print(f"  - {VECTORS_FILENAME}")
        print(f"  - {VECTOR_ROOT_FILENAME}")
        print(f"  - {SNAPSHOT_FILENAME}")
        print(f"  - {EMBEDDING_RECEIPT_FILENAME}")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    if args.list_model_pin:
        print(DEFAULT_MODEL_PIN)
        return 0

    if args.validate_manifest is not None:
        try:
            manifest = load_manifest(args.validate_manifest)
        except PublicLegalVectorError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print("manifest_ok: true")
        print(f"model_pin: {manifest.model_pin}")
        print(f"corpus_root_cid: {manifest.corpus_root_cid}")
        print(f"index_root_cid: {manifest.index_root_cid}")
        print(f"document_count: {manifest.document_count}")
        return 0

    if not (
        args.default_fixture
        or args.recipe is not None
        or args.from_corpus_dir is not None
    ):
        parser.error(
            "one of --default-fixture, --recipe, --from-corpus-dir, "
            "--validate-manifest, or --list-model-pin is required"
        )

    if args.stage and args.output_dir is None:
        parser.error("--output-dir is required with --stage")

    builder = PublicLegalVectorBuilder(require_all_families=True)
    recipe: Mapping[str, Any] | None = None
    materialization = None

    try:
        if args.default_fixture:
            result = builder.build_from_default_fixture(
                stage=bool(args.stage),
                output_dir=args.output_dir,
                created_utc=str(args.created_utc),
            )
        elif args.recipe is not None:
            recipe = _load_json_object(args.recipe)
            result = builder.build(
                recipe=recipe,
                stage=bool(args.stage),
                output_dir=args.output_dir,
                created_utc=str(args.created_utc),
            )
        elif args.from_corpus_dir is not None:
            materialization = _materialization_from_staged_corpus(args.from_corpus_dir)
            result = builder.build_from_materialization(
                materialization,
                stage=bool(args.stage),
                output_dir=args.output_dir,
                created_utc=str(args.created_utc),
            )
        else:
            parser.error("no vector build input selected")

        receipt = validate_build(result)
        if not receipt.get("ok"):
            print("error: vector build validation failed", file=sys.stderr)
            return 2

        if args.prove_stable:
            if recipe is not None:
                stable = validate_build_stable(
                    result,
                    recipe=recipe,
                    created_utc=str(args.created_utc),
                )
            elif materialization is not None:
                second = builder.build_from_materialization(
                    materialization,
                    created_utc=str(args.created_utc),
                )
                if second.index_root_cid != result.index_root_cid:
                    print(
                        "error: rebuild index_root_cid diverged under fixed pins",
                        file=sys.stderr,
                    )
                    return 2
                stable = {"rebuild_stable": True, **receipt}
            else:
                stable = validate_build_stable(
                    result, created_utc=str(args.created_utc)
                )
            if not stable.get("rebuild_stable"):
                print("error: rebuild stability check failed", file=sys.stderr)
                return 2

    except PrivateTextRejectedError as exc:
        print(f"error (private text fail-closed): {exc}", file=sys.stderr)
        return 3
    except ModelPinError as exc:
        print(f"error (model pin): {exc}", file=sys.stderr)
        return 3
    except CorpusRootError as exc:
        print(f"error (corpus root): {exc}", file=sys.stderr)
        return 3
    except (PublicLegalVectorError, PublicLegalCorpusError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.print_manifest:
        print(result.manifest.to_canonical_json())
    elif not args.no_print_summary:
        _print_summary(result)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
