#!/usr/bin/env python3
"""Build a production knowledge-graph snapshot for the public legal corpus.

PATLAW-173 — projects an admitted public patent-law / regulations corpus into
nodes, edges, JSON-LD, and a content-addressed snapshot receipt for Hub
packaging.

Default mode is **dry-run**: admission, projection, orphan/authority gates, and
content addressing run in memory and a summary is printed. Local staging occurs
only with ``--stage`` (and ``--output-dir``). This script never authenticates or
uploads to Hugging Face.

Input options (one required):

* ``--default-fixture`` — materialize the built-in multi-family public recipe
  then build the graph
* ``--recipe`` — compact JSON corpus recipe (source_roots + documents)
* ``--corpus-dir`` — staged public legal corpus directory (manifest + documents)
* ``--validate-snapshot`` — load and validate an existing staged snapshot

Authority edges must cite source spans and receipts; orphan endpoints fail closed.
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

from ipfs_datasets_py.processors.domains.patent.public_legal_graph_builder import (  # noqa: E402
    EDGES_FILENAME,
    GRAPH_ROOT_FILENAME,
    GRAPH_SCHEMA_VERSION,
    JSONLD_FILENAME,
    NODES_FILENAME,
    RECEIPT_FILENAME,
    SCHEMA_VERSION,
    SNAPSHOT_FILENAME,
    TASK_ID,
    GraphIntegrityError,
    MissingAuthoritySpanError,
    OrphanEdgeError,
    PrivateGraphInputError,
    PublicLegalGraphBuilder,
    PublicLegalGraphError,
    build_public_legal_knowledge_graph,
    load_snapshot,
    validate_graph_build,
)
from ipfs_datasets_py.processors.domains.patent.public_legal_corpus_materializer import (  # noqa: E402
    MissingSourceReceiptError,
    PrivateOrMixedInputError,
    UnreviewedRightsError,
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
            "Build a deterministic public legal knowledge-graph snapshot "
            f"({TASK_ID}). Default: dry-run, no Hub upload."
        )
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--default-fixture",
        action="store_true",
        help="Materialize the built-in multi-family public fixture then build",
    )
    input_group.add_argument(
        "--recipe",
        type=Path,
        help="Path to compact JSON corpus recipe (source_roots + documents)",
    )
    input_group.add_argument(
        "--corpus-dir",
        type=Path,
        help="Path to a staged public legal corpus directory",
    )
    input_group.add_argument(
        "--validate-snapshot",
        type=Path,
        help="Load and validate an existing staged snapshot receipt, then exit",
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
            "Write local staged artifacts (nodes, edges, JSON-LD, snapshot, "
            "receipt, graph-root pin). Default is dry-run only."
        ),
    )
    parser.add_argument(
        "--require-all-families",
        action="store_true",
        default=True,
        help="Require every public legal source family (default: on for recipes)",
    )
    parser.add_argument(
        "--no-require-all-families",
        action="store_true",
        help="Allow incomplete family coverage in recipe mode",
    )
    parser.add_argument(
        "--print-snapshot",
        action="store_true",
        help="Print the snapshot receipt JSON to stdout",
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
        "--write-default-recipe",
        type=Path,
        default=None,
        help="Write the built-in corpus fixture recipe to PATH and exit",
    )
    return parser


def _print_summary(result: Any) -> None:
    snapshot = result.snapshot
    print(f"task_id:                {TASK_ID}")
    print(f"schema_version:         {SCHEMA_VERSION}")
    print(f"graph_schema_version:   {GRAPH_SCHEMA_VERSION}")
    print(f"mode:                   {result.mode.value}")
    print(f"partition:              {snapshot.partition}")
    print(f"corpus_root_cid:        {snapshot.corpus_root_cid}")
    print(f"graph_root_cid:         {snapshot.graph_root_cid}")
    print(f"graph_digest_sha256:    {snapshot.graph_digest_sha256}")
    print(f"nodes:                  {snapshot.counts.nodes}")
    print(f"edges:                  {snapshot.counts.edges}")
    print(f"authority_edges:        {snapshot.counts.authority_edges}")
    print(f"documents:              {snapshot.counts.documents}")
    print(f"orphan_check:           {snapshot.orphan_check}")
    print(f"authority_span_check:   {snapshot.authority_span_check}")
    print(f"by_node_kind:           {dict(snapshot.counts.by_node_kind)}")
    print(f"by_edge_relation:       {dict(snapshot.counts.by_edge_relation)}")
    if result.output_dir:
        print(f"output_dir:             {result.output_dir}")
        print(f"  - {NODES_FILENAME}")
        print(f"  - {EDGES_FILENAME}")
        print(f"  - {JSONLD_FILENAME}")
        print(f"  - {SNAPSHOT_FILENAME}")
        print(f"  - {RECEIPT_FILENAME}")
        print(f"  - {GRAPH_ROOT_FILENAME}")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

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

    if args.validate_snapshot is not None:
        try:
            snapshot = load_snapshot(args.validate_snapshot)
        except PublicLegalGraphError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print("snapshot_ok: true")
        print(f"graph_root_cid: {snapshot.graph_root_cid}")
        print(f"corpus_root_cid: {snapshot.corpus_root_cid}")
        print(f"nodes: {snapshot.counts.nodes}")
        print(f"edges: {snapshot.counts.edges}")
        print(f"orphan_check: {snapshot.orphan_check}")
        print(f"authority_span_check: {snapshot.authority_span_check}")
        return 0

    if args.stage and args.output_dir is None:
        parser.error("--output-dir is required with --stage")

    require_all = bool(args.require_all_families) and not bool(
        args.no_require_all_families
    )
    builder = PublicLegalGraphBuilder()

    try:
        if args.default_fixture:
            result = build_public_legal_knowledge_graph(
                recipe=build_default_public_legal_recipe(),
                require_all_families=require_all,
                stage=bool(args.stage),
                output_dir=args.output_dir,
            )
        elif args.recipe is not None:
            recipe = _load_json_object(args.recipe)
            result = builder.build_from_recipe(
                recipe,
                require_all_families=require_all,
                stage=bool(args.stage),
                output_dir=args.output_dir,
            )
        elif args.corpus_dir is not None:
            result = builder.build_from_corpus_dir(
                args.corpus_dir,
                stage=bool(args.stage),
                output_dir=args.output_dir,
            )
        else:
            parser.error("no graph build input selected")

        receipt = validate_graph_build(result)
        if not receipt.get("ok"):
            print("error: graph build validation failed", file=sys.stderr)
            return 2

    except PrivateGraphInputError as exc:
        print(f"error (private/mixed fail-closed): {exc}", file=sys.stderr)
        return 3
    except PrivateOrMixedInputError as exc:
        print(f"error (private/mixed fail-closed): {exc}", file=sys.stderr)
        return 3
    except UnreviewedRightsError as exc:
        print(f"error (unreviewed rights): {exc}", file=sys.stderr)
        return 3
    except MissingSourceReceiptError as exc:
        print(f"error (source receipt): {exc}", file=sys.stderr)
        return 3
    except OrphanEdgeError as exc:
        print(f"error (orphan edge): {exc}", file=sys.stderr)
        return 2
    except MissingAuthoritySpanError as exc:
        print(f"error (authority span/receipt): {exc}", file=sys.stderr)
        return 2
    except GraphIntegrityError as exc:
        print(f"error (graph integrity): {exc}", file=sys.stderr)
        return 2
    except PublicLegalGraphError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.print_snapshot:
        print(result.snapshot.to_canonical_json())
    elif not args.no_print_summary:
        _print_summary(result)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
