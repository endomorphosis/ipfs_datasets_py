#!/usr/bin/env python3
"""Build a production knowledge-graph snapshot for the public legal corpus.

PATLAW-173 — projects an admitted public patent-law / regulations corpus into
nodes, edges, JSON-LD, and a content-addressed snapshot receipt for Hub
packaging.

PATLAW-190 — rebuilds the knowledge graph from the full-authority public legal
corpus (annual CFR Title 37, section-level MPEP, USPTO guidance PDFs):

* Document nodes cover every corpus document (fail-closed coverage check)
* Orphan edge endpoints fail closed
* Authority edges cite source spans and receipts
* Bulk nodes/edges/JSON-LD payloads stage for Hub packaging

Default mode is **dry-run**: admission, projection, orphan/authority gates, and
content addressing run in memory and a summary is printed. Local staging occurs
only with ``--stage`` (and ``--output-dir``). This script never authenticates or
uploads to Hugging Face.

Input options (one required):

* ``--full-authority`` — materialize the offline full-authority recipe
  (PATLAW-186/187) then build the graph (PATLAW-190)
* ``--default-fixture`` — materialize the built-in multi-family public recipe
  then build the graph
* ``--recipe`` — compact JSON corpus recipe (source_roots + documents)
* ``--corpus-dir`` — staged public legal corpus directory (manifest + documents)
* ``--validate-snapshot`` — load and validate an existing staged snapshot

Authority edges must cite source spans and receipts; orphan endpoints fail closed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, Final


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
    BuildMode,
    GraphIntegrityError,
    MissingAuthoritySpanError,
    OrphanEdgeError,
    PrivateGraphInputError,
    PublicLegalGraphBuild,
    PublicLegalGraphBuilder,
    PublicLegalGraphError,
    build_public_legal_knowledge_graph,
    load_snapshot,
    validate_graph_build,
    verify_graph_invariants,
    verify_no_orphan_edges,
)
from ipfs_datasets_py.processors.domains.patent.public_legal_corpus_materializer import (  # noqa: E402
    MissingSourceReceiptError,
    PrivateOrMixedInputError,
    PublicLegalCorpusMaterialization,
    PublicLegalDocument,
    UnreviewedRightsError,
    build_default_public_legal_recipe,
)

# ---------------------------------------------------------------------------
# Pins (PATLAW-190 full-authority knowledge-graph surface)
# ---------------------------------------------------------------------------

FULL_AUTHORITY_TASK_ID: Final = "PATLAW-190"
FULL_AUTHORITY_GOAL_ID: Final = "PATLAW-G218"
FULL_AUTHORITY_RECIPE_ID: Final = "patlaw-full-authority-public-legal-corpus"
FULL_AUTHORITY_FAMILIES: Final = ("cfr", "mpep", "guidance")
BASELINE_TASK_ID: Final = TASK_ID  # PATLAW-173 multi-family surface

PRODUCTION_RECIPE_SCRIPT: Final = (
    Path(__file__).resolve().parent / "build_public_legal_production_recipe.py"
)
MATERIALIZE_SCRIPT: Final = (
    Path(__file__).resolve().parent / "materialize_public_legal_corpus.py"
)

# Graph identifier charset (must match retrieval_contracts._NONEMPTY_ID_RE).
_GRAPH_ID_SAFE_RE: Final = re.compile(r"[^A-Za-z0-9._:/=+\-]+")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FullAuthorityGraphError(PublicLegalGraphError):
    """Raised when full-authority graph build/coverage gates fail."""

    code = "full_authority_graph_error"


class DocumentNodeCoverageError(FullAuthorityGraphError):
    """Raised when document nodes do not cover the corpus document set."""

    code = "document_node_coverage_error"


class GraphIdentifierSanitizeError(FullAuthorityGraphError):
    """Raised when a field cannot be sanitized into a valid graph identifier."""

    code = "graph_identifier_sanitize_error"


# ---------------------------------------------------------------------------
# Loaders (PATLAW-186 recipe + PATLAW-187 materialize helpers)
# ---------------------------------------------------------------------------


def _load_module_from_path(path: Path, module_name: str) -> ModuleType:
    if not path.is_file():
        raise FullAuthorityGraphError(f"missing co-located script: {path}")
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise FullAuthorityGraphError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_production_recipe_module() -> ModuleType:
    return _load_module_from_path(
        PRODUCTION_RECIPE_SCRIPT,
        "_patlaw190_build_public_legal_production_recipe",
    )


def _load_materialize_module() -> ModuleType:
    return _load_module_from_path(
        MATERIALIZE_SCRIPT,
        "_patlaw190_materialize_public_legal_corpus",
    )


def load_full_authority_recipe(
    *,
    assert_complete: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build the offline full-authority production recipe (PATLAW-186).

    No network I/O: consumes PATLAW-181/183/185 acquisition fixtures/catalogs.
    """

    build_mod = _load_production_recipe_module()
    recipe = build_mod.build_full_authority_recipe(
        assert_complete=assert_complete,
        **kwargs,
    )
    if not isinstance(recipe, dict):
        raise FullAuthorityGraphError("full-authority recipe must be a dict")
    return recipe


def assert_recipe_is_full_authority(recipe: Mapping[str, Any]) -> None:
    """Fail closed unless *recipe* proves full-authority completeness."""

    build_mod = _load_production_recipe_module()
    build_mod.assert_full_authority_complete(recipe)


# ---------------------------------------------------------------------------
# Identifier safety for graph projection
# ---------------------------------------------------------------------------


def sanitize_graph_id_token(value: str, *, field: str = "token") -> str:
    """Replace characters illegal in graph node/edge identifiers.

    Retrieval contracts accept ``[A-Za-z0-9._:/=+-]`` only. Full-authority
    guidance section ids carry ``@`` (edition cutoffs); those must be rewritten
    before projection without mutating admitted corpus content digests.
    """

    text = str(value or "").strip()
    if not text:
        return ""
    safe = _GRAPH_ID_SAFE_RE.sub("-", text).strip("-._")
    if not safe:
        raise GraphIdentifierSanitizeError(
            f"cannot sanitize empty graph identifier for {field}={value!r}"
        )
    # Collapse runs of separators introduced by multi-char replacements.
    safe = re.sub(r"-{2,}", "-", safe)
    return safe


def graph_safe_document(doc: PublicLegalDocument) -> PublicLegalDocument:
    """Return a projection copy with graph-safe ``section_id``.

    Preserves admitted ``document_cid`` / ``document_sha256`` / ``source_cid``
    so the graph continues to bind the PATLAW-187 corpus pin. Uses slot-level
    construction to avoid re-running content-digest integrity checks that would
    reject a section_id rewrite.
    """

    sid = doc.section_id or ""
    safe = sanitize_graph_id_token(sid, field="section_id") if sid else ""
    if safe == sid:
        return doc
    clone = object.__new__(PublicLegalDocument)
    for name in PublicLegalDocument.__dataclass_fields__:
        value = getattr(doc, name)
        if name == "section_id":
            value = safe
        object.__setattr__(clone, name, value)
    return clone


def graph_safe_documents(
    documents: Sequence[PublicLegalDocument],
) -> tuple[PublicLegalDocument, ...]:
    """Map admitted documents to graph-safe projection copies (stable order)."""

    return tuple(graph_safe_document(doc) for doc in documents)


# ---------------------------------------------------------------------------
# Coverage + inventory gates
# ---------------------------------------------------------------------------


def document_node_record_ids(result: PublicLegalGraphBuild) -> set[str]:
    """Return record ids present as ``kind=document`` graph nodes."""

    out: set[str] = set()
    for node in result.nodes:
        if node.kind != "document":
            continue
        record_id = node.document_id or str(
            (node.properties or {}).get("record_id") or ""
        )
        if record_id:
            out.add(record_id)
    return out


def assert_document_nodes_cover_corpus(
    result: PublicLegalGraphBuild,
    documents: Sequence[PublicLegalDocument] | Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Fail closed unless every corpus document has a document node.

    Acceptance (PATLAW-190): graph document nodes cover corpus documents.
    """

    corpus_ids: set[str] = set()
    for doc in documents:
        if isinstance(doc, PublicLegalDocument):
            corpus_ids.add(doc.record_id)
        elif isinstance(doc, Mapping):
            rid = str(doc.get("record_id") or "")
            if rid:
                corpus_ids.add(rid)
        else:
            raise DocumentNodeCoverageError(
                f"unsupported document type for coverage: {type(doc).__name__}"
            )

    node_ids = document_node_record_ids(result)
    missing = sorted(corpus_ids - node_ids)
    extra = sorted(node_ids - corpus_ids)
    if missing:
        raise DocumentNodeCoverageError(
            f"document nodes missing for {len(missing)} corpus record(s); "
            f"examples={missing[:5]}"
        )
    if result.snapshot.counts.documents != len(corpus_ids):
        raise DocumentNodeCoverageError(
            f"snapshot.counts.documents={result.snapshot.counts.documents} "
            f"does not match corpus size {len(corpus_ids)}"
        )
    if int(result.snapshot.counts.by_node_kind.get("document", 0)) != len(corpus_ids):
        raise DocumentNodeCoverageError(
            "by_node_kind.document does not match corpus document count"
        )

    return {
        "ok": True,
        "corpus_documents": len(corpus_ids),
        "document_nodes": len(node_ids),
        "missing": missing,
        "extra": extra,
        "coverage": "pass",
    }


def assert_full_authority_graph_coverage(
    result: PublicLegalGraphBuild,
    *,
    materialization: PublicLegalCorpusMaterialization,
    recipe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Prove full-authority family coverage + orphan + document node gates."""

    coverage = assert_document_nodes_cover_corpus(result, materialization.documents)
    gate = verify_graph_invariants(result.nodes, result.edges)
    verify_no_orphan_edges(result.nodes, result.edges)

    by_family = dict(result.snapshot.counts.by_family)
    for family in FULL_AUTHORITY_FAMILIES:
        if int(by_family.get(family, 0)) < 1:
            raise FullAuthorityGraphError(
                f"full-authority graph missing family {family!r} "
                f"(by_family={by_family})"
            )

    mat_by_family = dict(materialization.manifest.counts.by_family)
    for family, expected in mat_by_family.items():
        got = int(by_family.get(family, 0))
        if got != int(expected):
            raise FullAuthorityGraphError(
                f"graph by_family[{family!r}]={got} does not match "
                f"materialization by_family[{family!r}]={expected}"
            )

    if result.corpus_root_cid != materialization.corpus_root_cid:
        raise FullAuthorityGraphError(
            "graph corpus_root_cid does not bind materialization corpus pin"
        )
    if result.snapshot.corpus_digest_sha256 != materialization.corpus_digest_sha256:
        raise FullAuthorityGraphError(
            "graph corpus_digest_sha256 does not bind materialization digest"
        )
    if result.snapshot.orphan_check != "pass" or gate.get("orphan_check") != "pass":
        raise FullAuthorityGraphError("orphan_check did not pass")
    if (
        result.snapshot.authority_span_check != "pass"
        or gate.get("authority_span_check") != "pass"
    ):
        raise FullAuthorityGraphError("authority_span_check did not pass")

    recipe_by_family: dict[str, int] = {}
    fa_inventory: dict[str, Any] = {}
    if recipe is not None:
        recipe_counts = dict(recipe.get("counts") or {})
        recipe_by_family = dict(recipe_counts.get("by_family") or {})
        fa_inventory = dict(recipe_counts.get("full_authority") or {})
        expected_total = int(
            recipe_counts.get("documents")
            if recipe_counts.get("documents") is not None
            else len(list(recipe.get("documents") or []))
        )
        if expected_total and expected_total != coverage["corpus_documents"]:
            raise FullAuthorityGraphError(
                f"recipe document count {expected_total} does not match "
                f"materialized corpus {coverage['corpus_documents']}"
            )
        for family, expected in recipe_by_family.items():
            if int(by_family.get(family, 0)) != int(expected):
                raise FullAuthorityGraphError(
                    f"graph by_family[{family!r}]={by_family.get(family, 0)} "
                    f"does not match recipe by_family[{family!r}]={expected}"
                )

    return {
        "ok": True,
        "task_id": FULL_AUTHORITY_TASK_ID,
        "goal_id": FULL_AUTHORITY_GOAL_ID,
        "recipe_id": (
            str((recipe or {}).get("recipe_id") or FULL_AUTHORITY_RECIPE_ID)
            if recipe is not None
            else FULL_AUTHORITY_RECIPE_ID
        ),
        "coverage": coverage,
        "orphan_check": "pass",
        "authority_span_check": "pass",
        "document_count": coverage["corpus_documents"],
        "node_count": len(result.nodes),
        "edge_count": len(result.edges),
        "by_family": by_family,
        "recipe_by_family": recipe_by_family,
        "full_authority_inventory": fa_inventory,
        "full_authority_complete": bool(
            ((recipe or {}).get("full_authority") or {}).get("complete")
        )
        if recipe is not None
        else True,
        "corpus_root_cid": result.corpus_root_cid,
        "graph_root_cid": result.graph_root_cid,
        "graph_digest_sha256": result.graph_digest_sha256,
        "nodes_cid": result.snapshot.nodes_cid,
        "edges_cid": result.snapshot.edges_cid,
        "jsonld_cid": result.snapshot.jsonld_cid,
        "staged": result.mode is BuildMode.STAGE,
        "output_dir": result.output_dir,
    }


def validate_full_authority_graph_build(
    result: PublicLegalGraphBuild,
    *,
    materialization: PublicLegalCorpusMaterialization,
    recipe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate graph integrity + full-authority coverage; return receipt."""

    base = validate_graph_build(result)
    if not base.get("ok"):
        raise FullAuthorityGraphError("graph build validation failed")
    coverage = assert_full_authority_graph_coverage(
        result, materialization=materialization, recipe=recipe
    )
    return {
        **base,
        "task_id": FULL_AUTHORITY_TASK_ID,
        "goal_id": FULL_AUTHORITY_GOAL_ID,
        "full_authority": coverage,
        "document_coverage": coverage["coverage"]["coverage"],
        "document_count": coverage["document_count"],
        "by_family": coverage["by_family"],
    }


# ---------------------------------------------------------------------------
# Full-authority build entrypoint
# ---------------------------------------------------------------------------


def materialize_full_authority_for_graph(
    recipe: Mapping[str, Any] | None = None,
    *,
    require_full_authority: bool = True,
    assert_complete: bool = True,
) -> tuple[PublicLegalCorpusMaterialization, Mapping[str, Any], dict[str, Any]]:
    """Materialize the full-authority corpus used as the graph input pin.

    Prefers the PATLAW-187 materialize helper when available so corpus pins
    match the hub corpus package path. Falls back to a local materializer with
    ``require_all_families=False`` (FA covers cfr/mpep/guidance only).
    """

    if recipe is None:
        recipe = load_full_authority_recipe(assert_complete=assert_complete)
    if not isinstance(recipe, Mapping):
        raise FullAuthorityGraphError("recipe must be a mapping")
    if require_full_authority:
        assert_recipe_is_full_authority(recipe)

    mat_mod = _load_materialize_module()
    materialization, inventory = mat_mod.materialize_full_authority_corpus(
        recipe,
        stage=False,
        require_full_authority=require_full_authority,
        assert_complete=assert_complete,
    )
    if not isinstance(inventory, dict):
        inventory = {
            "ok": True,
            "document_count": len(materialization.documents),
            "by_family": dict(materialization.manifest.counts.by_family),
            "corpus_root_cid": materialization.corpus_root_cid,
            "corpus_digest_sha256": materialization.corpus_digest_sha256,
        }
    return materialization, recipe, inventory


def build_full_authority_knowledge_graph(
    recipe: Mapping[str, Any] | None = None,
    *,
    materialization: PublicLegalCorpusMaterialization | None = None,
    require_full_authority: bool = True,
    assert_complete: bool = True,
    stage: bool = False,
    output_dir: Path | str | None = None,
    notes: str = "",
) -> tuple[PublicLegalGraphBuild, dict[str, Any]]:
    """Build a knowledge-graph snapshot from the full-authority public corpus.

    Parameters
    ----------
    recipe:
        Optional pre-built full-authority recipe. When omitted (and
        *materialization* is also omitted), builds the offline PATLAW-186 recipe.
    materialization:
        Optional admitted corpus materialization. When provided, *recipe* is
        only used for inventory tallies (optional).
    require_full_authority:
        When True (default), reject recipes that are not full-authority complete.
    stage / output_dir:
        Local staging controls for bulk nodes/edges/JSON-LD payloads (never Hub).

    Returns
    -------
    (graph_build, coverage_receipt)
    """

    inventory: dict[str, Any] | None = None
    used_recipe: Mapping[str, Any] | None = recipe

    if materialization is None:
        materialization, used_recipe, inventory = materialize_full_authority_for_graph(
            recipe,
            require_full_authority=require_full_authority,
            assert_complete=assert_complete,
        )
    elif require_full_authority and used_recipe is not None:
        assert_recipe_is_full_authority(used_recipe)

    if not isinstance(materialization, PublicLegalCorpusMaterialization):
        raise FullAuthorityGraphError(
            "materialization must be PublicLegalCorpusMaterialization"
        )
    if materialization.manifest.partition != "public":
        raise PrivateGraphInputError(
            "full-authority graph builder only accepts public materializations"
        )

    projection_docs = graph_safe_documents(materialization.documents)
    builder = PublicLegalGraphBuilder()
    fa_notes = notes or str((used_recipe or {}).get("notes") or "")
    if FULL_AUTHORITY_TASK_ID not in fa_notes:
        fa_notes = (
            f"{fa_notes} [knowledge graph under {FULL_AUTHORITY_TASK_ID} / "
            f"{FULL_AUTHORITY_GOAL_ID} from full-authority corpus "
            f"{(used_recipe or {}).get('recipe_id') or FULL_AUTHORITY_RECIPE_ID}]"
        ).strip()

    result = builder.build(
        documents=projection_docs,
        source_roots=materialization.manifest.source_roots,
        corpus_root_cid=materialization.corpus_root_cid,
        corpus_digest_sha256=materialization.corpus_digest_sha256,
        stage=stage,
        output_dir=output_dir,
        notes=fa_notes,
    )

    receipt = validate_full_authority_graph_build(
        result, materialization=materialization, recipe=used_recipe
    )
    if inventory is not None:
        receipt["materialization_inventory"] = inventory
    return result, receipt


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


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
            f"({BASELINE_TASK_ID} / {FULL_AUTHORITY_TASK_ID}). "
            "Default: dry-run, no Hub upload."
        )
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--full-authority",
        action="store_true",
        help=(
            "Materialize the offline full-authority corpus (PATLAW-186/187: "
            "annual CFR Title 37, section-level MPEP, USPTO guidance PDFs) and "
            f"build the knowledge graph ({FULL_AUTHORITY_TASK_ID}). Enforces "
            "document-node coverage and orphan checks."
        ),
    )
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
        help=(
            "Require every public legal source family (default: on for "
            "multi-family recipes; ignored for --full-authority)"
        ),
    )
    parser.add_argument(
        "--no-require-all-families",
        action="store_true",
        help="Allow incomplete family coverage in recipe mode",
    )
    parser.add_argument(
        "--require-full-authority",
        action="store_true",
        help=(
            "When loading --recipe, require full-authority completeness "
            "(PATLAW-186 acceptance), document-node coverage, and orphan gates"
        ),
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
        "--print-coverage-receipt",
        action="store_true",
        help="Print the full-authority coverage receipt JSON",
    )
    parser.add_argument(
        "--write-default-recipe",
        type=Path,
        default=None,
        help="Write the built-in corpus fixture recipe to PATH and exit",
    )
    parser.add_argument(
        "--write-full-authority-recipe",
        type=Path,
        default=None,
        help="Build and write the offline full-authority recipe to PATH and exit",
    )
    return parser


def _print_summary(
    result: Any,
    *,
    coverage: Mapping[str, Any] | None = None,
    full_authority: bool = False,
) -> None:
    snapshot = result.snapshot
    task_label = FULL_AUTHORITY_TASK_ID if full_authority else BASELINE_TASK_ID
    print(f"task_id:                {task_label}")
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
    print(f"by_family:              {dict(snapshot.counts.by_family)}")
    if coverage is not None:
        cov = coverage.get("coverage") or coverage.get("document_coverage") or {}
        if isinstance(cov, Mapping):
            print(f"document_coverage:      {cov.get('coverage', cov)}")
        else:
            print(f"document_coverage:      {cov}")
        fa_inv = coverage.get("full_authority_inventory") or {}
        if fa_inv:
            print(f"full_authority:         {fa_inv}")
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

    if args.write_full_authority_recipe is not None:
        try:
            recipe = load_full_authority_recipe(assert_complete=True)
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        target = args.write_full_authority_recipe
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(recipe, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"wrote full-authority recipe: {target}")
        print(f"documents: {recipe['counts']['documents']}")
        print(f"by_family: {recipe['counts']['by_family']}")
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
    coverage: dict[str, Any] | None = None
    full_authority_mode = bool(args.full_authority or args.require_full_authority)

    try:
        if args.full_authority:
            result, coverage = build_full_authority_knowledge_graph(
                stage=bool(args.stage),
                output_dir=args.output_dir,
                require_full_authority=True,
            )
        elif args.default_fixture:
            result = build_public_legal_knowledge_graph(
                recipe=build_default_public_legal_recipe(),
                require_all_families=require_all,
                stage=bool(args.stage),
                output_dir=args.output_dir,
            )
            receipt = validate_graph_build(result)
            if not receipt.get("ok"):
                print("error: graph build validation failed", file=sys.stderr)
                return 2
        elif args.recipe is not None:
            recipe = _load_json_object(args.recipe)
            if args.require_full_authority or bool(
                (recipe.get("full_authority") or {}).get("complete")
            ):
                result, coverage = build_full_authority_knowledge_graph(
                    recipe,
                    stage=bool(args.stage),
                    output_dir=args.output_dir,
                    require_full_authority=True,
                )
                full_authority_mode = True
            else:
                result = builder.build_from_recipe(
                    recipe,
                    require_all_families=require_all,
                    stage=bool(args.stage),
                    output_dir=args.output_dir,
                )
                receipt = validate_graph_build(result)
                if not receipt.get("ok"):
                    print("error: graph build validation failed", file=sys.stderr)
                    return 2
        elif args.corpus_dir is not None:
            # Staged corpus may be full-authority; detect via manifest family set.
            result = builder.build_from_corpus_dir(
                args.corpus_dir,
                stage=bool(args.stage),
                output_dir=args.output_dir,
            )
            receipt = validate_graph_build(result)
            if not receipt.get("ok"):
                print("error: graph build validation failed", file=sys.stderr)
                return 2
            # Optional FA coverage when the staged corpus only has FA families.
            by_family = set(result.snapshot.counts.by_family)
            if by_family and by_family.issubset(set(FULL_AUTHORITY_FAMILIES)):
                if set(FULL_AUTHORITY_FAMILIES).issubset(by_family):
                    assert_document_nodes_cover_corpus(
                        result,
                        # Reconstruct minimal coverage from snapshot joins.
                        [
                            {"record_id": j.get("record_id")}
                            for j in result.snapshot.document_joins
                        ],
                    )
        else:
            parser.error("no graph build input selected")

        if coverage is None:
            receipt = validate_graph_build(result)
            if not receipt.get("ok"):
                print("error: graph build validation failed", file=sys.stderr)
                return 2

    except DocumentNodeCoverageError as exc:
        print(f"error (document node coverage): {exc}", file=sys.stderr)
        return 2
    except FullAuthorityGraphError as exc:
        print(f"error (full-authority graph): {exc}", file=sys.stderr)
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
    except Exception as exc:
        msg = str(exc)
        code = getattr(exc, "code", "") or ""
        if (
            "full_authority" in code
            or "ecfr_only" in code
            or "chapter_only" in code
            or type(exc).__name__
            in {
                "FullAuthorityIncompleteError",
                "EcfrOnlyCompletionError",
                "ChapterOnlyMpepCompletionError",
                "ProductionRecipeError",
                "FullAuthorityMaterializeError",
                "InventoryCountMismatchError",
            }
        ):
            print(f"error (full-authority): {exc}", file=sys.stderr)
            return 2
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.print_coverage_receipt and coverage is not None:
        print(json.dumps(coverage, indent=2, sort_keys=True, ensure_ascii=False))
    elif args.print_snapshot:
        print(result.snapshot.to_canonical_json())
    elif not args.no_print_summary:
        _print_summary(
            result,
            coverage=coverage,
            full_authority=full_authority_mode,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
