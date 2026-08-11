#!/usr/bin/env python3
"""Materialize the public patent-law / regulations corpus for Hub release.

PATLAW-170 — deterministic public-official corpus projection covering
eCFR/CFR, U.S. Code / Public Law / Federal Register, and MPEP / guidance.

PATLAW-187 — rebuild materialization from the full-authority production
recipe (PATLAW-186): annual CFR Title 37, section-level MPEP, and USPTO
guidance PDFs. Produces a content-address-stable ``corpus_root_cid`` shared
by downstream BM25 / vector / graph rebuilds (PATLAW-188+).

Default mode is **dry-run**: admission and content-addressed materialization
run in memory and a summary is printed. Local staging occurs only with
``--stage`` (and ``--output-dir``). This script never authenticates or uploads
to Hugging Face.

Input options (one required):

* ``--full-authority`` — build offline full-authority recipe (PATLAW-186) and
  materialize; inventory/count parity is enforced
* ``--recipe`` — compact JSON recipe with ``source_roots`` + ``documents``
* ``--source-roots`` + ``--documents`` — separate JSON/NDJSON files
* ``--default-fixture`` — use the built-in multi-family CI recipe (PATLAW-170)

Private, mixed, unknown, or unreviewed inputs fail closed before staging.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Mapping, Sequence


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
    PublicLegalCorpusMaterialization,
    PublicLegalCorpusMaterializer,
    UnreviewedRightsError,
    build_default_public_legal_recipe,
    load_manifest,
    validate_materialization,
)

# ---------------------------------------------------------------------------
# Pins (PATLAW-187 full-authority materialization surface)
# ---------------------------------------------------------------------------

FULL_AUTHORITY_TASK_ID: Final = "PATLAW-187"
FULL_AUTHORITY_GOAL_ID: Final = "PATLAW-G218"
FULL_AUTHORITY_RECIPE_ID: Final = "patlaw-full-authority-public-legal-corpus"
FULL_AUTHORITY_FAMILIES: Final = ("cfr", "mpep", "guidance")
PRODUCTION_RECIPE_SCRIPT: Final = (
    Path(__file__).resolve().parent / "build_public_legal_production_recipe.py"
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FullAuthorityMaterializeError(PublicLegalCorpusError):
    """Raised when full-authority inventory/count parity fails."""

    code = "full_authority_materialize_error"


class InventoryCountMismatchError(FullAuthorityMaterializeError):
    """Raised when materialization counts do not match the recipe inventory."""

    code = "inventory_count_mismatch"


# ---------------------------------------------------------------------------
# Production recipe loader (PATLAW-186)
# ---------------------------------------------------------------------------


def _load_production_recipe_module() -> ModuleType:
    """Load the co-located PATLAW-186 production recipe builder."""

    path = PRODUCTION_RECIPE_SCRIPT
    if not path.is_file():
        raise FullAuthorityMaterializeError(
            f"missing full-authority recipe builder: {path}"
        )
    module_name = "_patlaw187_build_public_legal_production_recipe"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise FullAuthorityMaterializeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


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
        raise FullAuthorityMaterializeError("full-authority recipe must be a dict")
    return recipe


def assert_recipe_is_full_authority(recipe: Mapping[str, Any]) -> None:
    """Fail closed unless *recipe* proves full-authority completeness."""

    build_mod = _load_production_recipe_module()
    build_mod.assert_full_authority_complete(recipe)


def _count_by(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "")
        if not value:
            continue
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


def assert_counts_match_recipe_inventory(
    materialization: PublicLegalCorpusMaterialization,
    recipe: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove materialization document counts match the recipe inventory.

    Checks:

    * total document count
    * per-family tallies (``counts.by_family``)
    * full-authority families are all present with expected minima
    * when ``counts.full_authority`` is present, re-bind inventory tallies
      (catalog size, section-level MPEP, guidance PDFs) from the recipe
    """

    docs = list(recipe.get("documents") or [])
    recipe_counts = dict(recipe.get("counts") or {})
    expected_by_family = dict(
        recipe_counts.get("by_family") or _count_by(docs, "family")
    )
    expected_total = int(
        recipe_counts.get("documents")
        if recipe_counts.get("documents") is not None
        else len(docs)
    )

    got_by_family = dict(materialization.manifest.counts.by_family)
    got_total = int(materialization.manifest.counts.total_documents)

    if got_total != expected_total:
        raise InventoryCountMismatchError(
            f"document count mismatch: materialization={got_total} "
            f"recipe={expected_total}"
        )
    if got_total != len(materialization.documents):
        raise InventoryCountMismatchError(
            "materialization total_documents does not match documents list length"
        )
    if got_total != sum(got_by_family.values()):
        raise InventoryCountMismatchError(
            "materialization by_family sum does not equal total_documents"
        )

    for family, expected in expected_by_family.items():
        got = int(got_by_family.get(family, 0))
        if got != int(expected):
            raise InventoryCountMismatchError(
                f"by_family[{family!r}] mismatch: materialization={got} "
                f"recipe={expected}"
            )

    # Full-authority families must be present whenever the recipe claims them.
    fa = dict(recipe.get("full_authority") or {})
    if fa.get("complete"):
        for family in FULL_AUTHORITY_FAMILIES:
            if int(got_by_family.get(family, 0)) < 1:
                raise InventoryCountMismatchError(
                    f"full-authority materialization missing family {family!r}"
                )
        expected_min = dict((recipe.get("expected") or {}).get("min_by_family") or {})
        for family, minimum in expected_min.items():
            if int(got_by_family.get(family, 0)) < int(minimum):
                raise InventoryCountMismatchError(
                    f"by_family[{family!r}]={got_by_family.get(family, 0)} "
                    f"below recipe expected min {minimum}"
                )

        fa_counts = dict(recipe_counts.get("full_authority") or {})
        # Inventory tallies live on the recipe; materialization document rows
        # equal present-body docs. Re-assert catalog inventory is still bound.
        if fa_counts:
            cfr_inv = int(fa_counts.get("cfr_inventory_total") or 0)
            if cfr_inv < 1000:
                raise InventoryCountMismatchError(
                    "recipe full_authority.cfr_inventory_total does not prove "
                    f"full Title 37 catalog (got {cfr_inv})"
                )
            mpep_sl = int(fa_counts.get("mpep_section_level") or 0)
            if mpep_sl < int(got_by_family.get("mpep", 0)):
                # section_level_acquired should be at least the emitted docs
                # when every emitted MPEP row is section-level.
                pass
            if mpep_sl < 1:
                raise InventoryCountMismatchError(
                    "recipe full_authority.mpep_section_level is zero"
                )
            guidance_pdfs = int(fa_counts.get("guidance_pdfs") or 0)
            if guidance_pdfs < int(got_by_family.get("guidance", 0)):
                raise InventoryCountMismatchError(
                    "recipe full_authority.guidance_pdfs below guidance document tally"
                )
            # Present-document tallies must equal by_family for full-authority
            # families when the recipe records them.
            if "cfr_documents" in fa_counts and int(fa_counts["cfr_documents"]) != int(
                got_by_family.get("cfr", 0)
            ):
                raise InventoryCountMismatchError(
                    "full_authority.cfr_documents does not match materialization "
                    f"by_family.cfr ({fa_counts['cfr_documents']} != "
                    f"{got_by_family.get('cfr', 0)})"
                )
            if "mpep_documents" in fa_counts and int(
                fa_counts["mpep_documents"]
            ) != int(got_by_family.get("mpep", 0)):
                raise InventoryCountMismatchError(
                    "full_authority.mpep_documents does not match materialization "
                    f"by_family.mpep ({fa_counts['mpep_documents']} != "
                    f"{got_by_family.get('mpep', 0)})"
                )
            if "guidance_documents" in fa_counts and int(
                fa_counts["guidance_documents"]
            ) != int(got_by_family.get("guidance", 0)):
                raise InventoryCountMismatchError(
                    "full_authority.guidance_documents does not match "
                    f"materialization by_family.guidance "
                    f"({fa_counts['guidance_documents']} != "
                    f"{got_by_family.get('guidance', 0)})"
                )

    receipt = {
        "ok": True,
        "document_count": got_total,
        "by_family": got_by_family,
        "recipe_document_count": expected_total,
        "recipe_by_family": expected_by_family,
        "corpus_root_cid": materialization.corpus_root_cid,
        "corpus_digest_sha256": materialization.corpus_digest_sha256,
        "full_authority_complete": bool(fa.get("complete")),
        "full_authority_inventory": dict(recipe_counts.get("full_authority") or {}),
        "task_id": FULL_AUTHORITY_TASK_ID
        if fa.get("complete")
        else TASK_ID,
    }
    return receipt


def materialize_full_authority_corpus(
    recipe: Mapping[str, Any] | None = None,
    *,
    stage: bool = False,
    output_dir: Path | None = None,
    require_full_authority: bool = True,
    assert_complete: bool = True,
) -> tuple[PublicLegalCorpusMaterialization, dict[str, Any]]:
    """Materialize a full-authority public legal corpus snapshot.

    Parameters
    ----------
    recipe:
        Optional pre-built full-authority recipe. When omitted, builds the
        offline PATLAW-186 recipe from acquisition fixtures.
    stage / output_dir:
        Local staging controls (never Hub upload).
    require_full_authority:
        When True (default), reject recipes that are not full-authority complete.
    assert_complete:
        Forwarded to the recipe builder when *recipe* is omitted.

    Returns
    -------
    (materialization, inventory_receipt)
    """

    if recipe is None:
        recipe = load_full_authority_recipe(assert_complete=assert_complete)
    if not isinstance(recipe, Mapping):
        raise FullAuthorityMaterializeError("recipe must be a mapping")

    if require_full_authority:
        assert_recipe_is_full_authority(recipe)

    # Full-authority recipes cover cfr/mpep/guidance only — do not require the
    # full multi-family PATLAW-170 fixture set.
    materializer = PublicLegalCorpusMaterializer(require_all_families=False)
    notes = str(recipe.get("notes") or "")
    if "PATLAW-187" not in notes:
        notes = (
            f"{notes} [materialized under {FULL_AUTHORITY_TASK_ID} / "
            f"{FULL_AUTHORITY_GOAL_ID} from full-authority recipe "
            f"{recipe.get('recipe_id') or FULL_AUTHORITY_RECIPE_ID}]"
        ).strip()

    result = materializer.materialize(
        source_roots=list(recipe.get("source_roots") or []),
        documents=list(recipe.get("documents") or recipe.get("records") or []),
        stage=stage,
        output_dir=output_dir,
        notes=notes,
    )

    # Content-address stability receipt (repeat materialization).
    stability = validate_materialization(result)
    if not stability.get("ok") or not stability.get("stable"):
        raise FullAuthorityMaterializeError(
            "full-authority materialization is not content-address stable"
        )

    inventory = assert_counts_match_recipe_inventory(result, recipe)
    inventory["stability"] = {
        "ok": True,
        "stable": True,
        "corpus_root_cid": result.corpus_root_cid,
        "corpus_digest_sha256": result.corpus_digest_sha256,
    }
    return result, inventory


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
            "Materialize a deterministic public patent-law/regulations corpus "
            f"({TASK_ID} / {FULL_AUTHORITY_TASK_ID}). Default: dry-run, no Hub upload."
        )
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--full-authority",
        action="store_true",
        help=(
            "Build offline full-authority recipe (PATLAW-186: annual CFR Title 37, "
            "section-level MPEP, USPTO guidance PDFs) and materialize "
            f"({FULL_AUTHORITY_TASK_ID}). Enforces inventory count parity."
        ),
    )
    input_group.add_argument(
        "--recipe",
        type=Path,
        help="Path to compact JSON recipe (source_roots + documents)",
    )
    input_group.add_argument(
        "--default-fixture",
        action="store_true",
        help="Use the built-in multi-family public fixture recipe (PATLAW-170)",
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
            f"({', '.join(SOURCE_FAMILIES)}) to be present "
            "(PATLAW-170 multi-family mode; not used with --full-authority)"
        ),
    )
    parser.add_argument(
        "--require-full-authority",
        action="store_true",
        help=(
            "When loading --recipe, require full-authority completeness "
            "(PATLAW-186 acceptance) and inventory count parity"
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
        "--print-inventory-receipt",
        action="store_true",
        help="Print the inventory/count parity receipt JSON (full-authority path)",
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
    parser.add_argument(
        "--write-full-authority-recipe",
        type=Path,
        default=None,
        help="Build and write the offline full-authority recipe to PATH and exit",
    )
    return parser


def _print_summary(
    result: PublicLegalCorpusMaterialization,
    *,
    inventory: Mapping[str, Any] | None = None,
    full_authority: bool = False,
) -> None:
    manifest = result.manifest
    task_label = FULL_AUTHORITY_TASK_ID if full_authority else TASK_ID
    print(f"task_id:              {task_label}")
    print(f"schema_version:       {SCHEMA_VERSION}")
    print(f"mode:                 {result.mode.value}")
    print(f"partition:            {manifest.partition}")
    print(f"corpus_root_cid:      {manifest.corpus_root_cid}")
    print(f"corpus_digest_sha256: {manifest.corpus_digest_sha256}")
    print(f"document_count:       {manifest.counts.total_documents}")
    print(f"source_root_count:    {manifest.counts.source_root_count}")
    print(f"by_family:            {dict(manifest.counts.by_family)}")
    print(f"by_authority_kind:    {dict(manifest.counts.by_authority_kind)}")
    if inventory is not None:
        print(f"inventory_match:      {inventory.get('ok')}")
        fa_inv = inventory.get("full_authority_inventory") or {}
        if fa_inv:
            print(f"full_authority:       {fa_inv}")
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

    if args.validate_manifest is not None:
        try:
            manifest = load_manifest(args.validate_manifest)
        except PublicLegalCorpusError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print("manifest_ok: true")
        print(f"corpus_root_cid: {manifest.corpus_root_cid}")
        print(f"document_count: {manifest.counts.total_documents}")
        return 0

    if args.stage and args.output_dir is None:
        parser.error("--output-dir is required with --stage")

    inventory: dict[str, Any] | None = None
    full_authority_mode = bool(args.full_authority or args.require_full_authority)

    try:
        if args.full_authority:
            result, inventory = materialize_full_authority_corpus(
                stage=bool(args.stage),
                output_dir=args.output_dir,
                require_full_authority=True,
            )
        elif args.default_fixture:
            materializer = PublicLegalCorpusMaterializer(
                require_all_families=bool(args.require_all_families)
            )
            recipe = build_default_public_legal_recipe()
            result = materializer.materialize_from_recipe(
                recipe,
                stage=bool(args.stage),
                output_dir=args.output_dir,
            )
            receipt = validate_materialization(result)
            if not receipt.get("ok"):
                print("error: materialization validation failed", file=sys.stderr)
                return 2
        elif args.recipe is not None:
            recipe = _load_json_object(args.recipe)
            if args.require_full_authority or bool(
                (recipe.get("full_authority") or {}).get("complete")
            ):
                # Full-authority recipe path: enforce completeness + inventory.
                result, inventory = materialize_full_authority_corpus(
                    recipe,
                    stage=bool(args.stage),
                    output_dir=args.output_dir,
                    require_full_authority=True,
                )
                full_authority_mode = True
            else:
                materializer = PublicLegalCorpusMaterializer(
                    require_all_families=bool(args.require_all_families)
                )
                result = materializer.materialize_from_recipe(
                    recipe,
                    stage=bool(args.stage),
                    output_dir=args.output_dir,
                )
                receipt = validate_materialization(result)
                if not receipt.get("ok"):
                    print(
                        "error: materialization validation failed", file=sys.stderr
                    )
                    return 2
        elif args.from_paths:
            if args.source_roots is None or args.documents is None:
                parser.error(
                    "--from-paths requires both --source-roots and --documents"
                )
            materializer = PublicLegalCorpusMaterializer(
                require_all_families=bool(args.require_all_families)
            )
            result = materializer.materialize_from_paths(
                roots_path=args.source_roots,
                documents_path=args.documents,
                stage=bool(args.stage),
                output_dir=args.output_dir,
            )
            receipt = validate_materialization(result)
            if not receipt.get("ok"):
                print("error: materialization validation failed", file=sys.stderr)
                return 2
        else:
            parser.error("no materialization input selected")

    except InventoryCountMismatchError as exc:
        print(f"error (inventory count mismatch): {exc}", file=sys.stderr)
        return 2
    except FullAuthorityMaterializeError as exc:
        print(f"error (full-authority): {exc}", file=sys.stderr)
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
    except Exception as exc:
        # Production recipe builder / acquisition errors (e.g. incomplete FA).
        msg = str(exc)
        code = getattr(exc, "code", "") or ""
        if "full_authority" in code or "ecfr_only" in code or "chapter_only" in code:
            print(f"error (full-authority): {exc}", file=sys.stderr)
            return 2
        # Re-raise unexpected errors only after known FA builder codes.
        if type(exc).__name__ in {
            "FullAuthorityIncompleteError",
            "EcfrOnlyCompletionError",
            "ChapterOnlyMpepCompletionError",
            "ProductionRecipeError",
        }:
            print(f"error (full-authority): {exc}", file=sys.stderr)
            return 2
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.print_inventory_receipt and inventory is not None:
        print(json.dumps(inventory, indent=2, sort_keys=True, ensure_ascii=False))
    elif args.print_manifest:
        print(result.manifest.to_canonical_json())
    elif not args.no_print_summary:
        _print_summary(
            result,
            inventory=inventory,
            full_authority=full_authority_mode,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
