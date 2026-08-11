#!/usr/bin/env python3
"""Build a production vector index snapshot for the public legal corpus.

PATLAW-172 — binds the pinned local embedding model and public corpus root into
a content-addressed vector index snapshot. Private / mixed inputs fail closed.
Default mode is **dry-run** (in-memory). Local staging requires ``--stage``
and ``--output-dir``. Never authenticates or uploads to Hugging Face.

PATLAW-189 — rebuild the vector index from the full-authority public legal
corpus (PATLAW-186 recipe + PATLAW-187 materialization). Enforces
vector ``document_count`` parity with the corpus, binds the local model pin
and corpus root, and stages bulk vector rows for Hub packaging.

Input options (one required):

* ``--full-authority`` — offline full-authority recipe + materialize + embed
* ``--default-fixture`` — multi-family public legal CI recipe (via PATLAW-170)
* ``--recipe`` — compact JSON recipe (source_roots + documents)
* ``--from-corpus-dir`` — staged PATLAW-170/187 corpus directory
* ``--validate-manifest`` — load and validate an existing vector manifest
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Mapping


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
    BuildMode,
    CorpusRootError,
    ModelPinError,
    PrivateTextRejectedError,
    PublicLegalVectorBuildResult,
    PublicLegalVectorBuilder,
    PublicLegalVectorError,
    VectorIntegrityError,
    builds_are_byte_identical,
    load_manifest,
    validate_build,
    validate_build_stable,
)

# ---------------------------------------------------------------------------
# Pins (PATLAW-189 full-authority vector rebuild surface)
# ---------------------------------------------------------------------------

FULL_AUTHORITY_TASK_ID: Final = "PATLAW-189"
FULL_AUTHORITY_GOAL_ID: Final = "PATLAW-G218"
FULL_AUTHORITY_RECIPE_ID: Final = "patlaw-full-authority-public-legal-corpus"
FULL_AUTHORITY_FAMILIES: Final = ("cfr", "mpep", "guidance")
MATERIALIZE_SCRIPT: Final = (
    Path(__file__).resolve().parent / "materialize_public_legal_corpus.py"
)
PRODUCTION_RECIPE_SCRIPT: Final = (
    Path(__file__).resolve().parent / "build_public_legal_production_recipe.py"
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FullAuthorityVectorError(PublicLegalVectorError):
    """Raised when full-authority vector rebuild preconditions fail."""

    code = "full_authority_vector_error"


class DocumentCountMismatchError(FullAuthorityVectorError):
    """Raised when vector document_count does not equal corpus document_count."""

    code = "document_count_mismatch"


# ---------------------------------------------------------------------------
# Sibling script loaders (PATLAW-186 / PATLAW-187)
# ---------------------------------------------------------------------------


def _load_script_module(path: Path, module_name: str) -> ModuleType:
    if not path.is_file():
        raise FullAuthorityVectorError(f"missing required script: {path}")
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise FullAuthorityVectorError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_materialize_module() -> ModuleType:
    return _load_script_module(
        MATERIALIZE_SCRIPT, "_patlaw189_materialize_public_legal_corpus"
    )


def _load_production_recipe_module() -> ModuleType:
    return _load_script_module(
        PRODUCTION_RECIPE_SCRIPT, "_patlaw189_build_public_legal_production_recipe"
    )


def load_full_authority_recipe(
    *,
    assert_complete: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build the offline full-authority production recipe (PATLAW-186).

    Prefer the PATLAW-187 materialize surface when available so corpus root
    pins stay aligned with downstream BM25 / graph rebuilds.
    """

    try:
        mat_mod = _load_materialize_module()
        if hasattr(mat_mod, "load_full_authority_recipe"):
            recipe = mat_mod.load_full_authority_recipe(
                assert_complete=assert_complete, **kwargs
            )
            if not isinstance(recipe, dict):
                raise FullAuthorityVectorError(
                    "full-authority recipe must be a dict"
                )
            return recipe
    except FullAuthorityVectorError:
        raise
    except Exception:
        # Fall through to co-located production recipe builder.
        pass

    build_mod = _load_production_recipe_module()
    recipe = build_mod.build_full_authority_recipe(
        assert_complete=assert_complete, **kwargs
    )
    if not isinstance(recipe, dict):
        raise FullAuthorityVectorError("full-authority recipe must be a dict")
    return recipe


def assert_recipe_is_full_authority(recipe: Mapping[str, Any]) -> None:
    """Fail closed unless *recipe* proves full-authority completeness."""

    try:
        mat_mod = _load_materialize_module()
        if hasattr(mat_mod, "assert_recipe_is_full_authority"):
            mat_mod.assert_recipe_is_full_authority(recipe)
            return
    except FullAuthorityVectorError:
        raise
    except Exception:
        pass

    build_mod = _load_production_recipe_module()
    build_mod.assert_full_authority_complete(recipe)


def materialize_full_authority_corpus(
    recipe: Mapping[str, Any] | None = None,
    *,
    stage: bool = False,
    output_dir: Path | None = None,
    require_full_authority: bool = True,
    assert_complete: bool = True,
) -> tuple[PublicLegalCorpusMaterialization, dict[str, Any]]:
    """Materialize the full-authority corpus via PATLAW-187 surface."""

    mat_mod = _load_materialize_module()
    if not hasattr(mat_mod, "materialize_full_authority_corpus"):
        raise FullAuthorityVectorError(
            "materialize script lacks materialize_full_authority_corpus"
        )
    return mat_mod.materialize_full_authority_corpus(
        recipe,
        stage=stage,
        output_dir=output_dir,
        require_full_authority=require_full_authority,
        assert_complete=assert_complete,
    )


# ---------------------------------------------------------------------------
# Full-authority vector rebuild (PATLAW-189)
# ---------------------------------------------------------------------------


def assert_vector_document_count_matches_corpus(
    result: PublicLegalVectorBuildResult,
    materialization: PublicLegalCorpusMaterialization,
    *,
    recipe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Prove vector document_count equals corpus document_count.

    Acceptance for PATLAW-189: every corpus document receives exactly one
    bulk vector row; counts stay aligned with the full-authority inventory.
    """

    corpus_count = int(materialization.manifest.counts.total_documents)
    if corpus_count != len(materialization.documents):
        raise DocumentCountMismatchError(
            "corpus total_documents does not match documents list length "
            f"({corpus_count} != {len(materialization.documents)})"
        )

    vector_count = int(result.manifest.document_count)
    if vector_count != int(result.manifest.vector_count):
        raise DocumentCountMismatchError(
            f"vector document_count {vector_count} != vector_count "
            f"{result.manifest.vector_count}"
        )
    if vector_count != len(result.rows):
        raise DocumentCountMismatchError(
            f"vector document_count {vector_count} != len(rows) {len(result.rows)}"
        )
    if vector_count != corpus_count:
        raise DocumentCountMismatchError(
            f"vector document_count {vector_count} != corpus document_count "
            f"{corpus_count}"
        )

    # Every corpus record_id must appear exactly once among vector rows.
    corpus_ids = sorted(d.record_id for d in materialization.documents)
    row_ids = sorted(r.record_id for r in result.rows)
    if row_ids != corpus_ids:
        missing = sorted(set(corpus_ids) - set(row_ids))
        extra = sorted(set(row_ids) - set(corpus_ids))
        raise DocumentCountMismatchError(
            "vector row record_id set diverges from corpus documents "
            f"(missing={missing[:5]!r} extra={extra[:5]!r})"
        )

    receipt: dict[str, Any] = {
        "ok": True,
        "document_count": vector_count,
        "corpus_document_count": corpus_count,
        "vector_count": int(result.manifest.vector_count),
        "corpus_root_cid": result.manifest.corpus_root_cid,
        "corpus_digest_sha256": result.manifest.corpus_digest_sha256,
        "model_pin": result.manifest.model_pin,
        "index_root_cid": result.manifest.index_root_cid,
        "by_family": dict(materialization.manifest.counts.by_family),
        "task_id": FULL_AUTHORITY_TASK_ID,
        "goal_id": FULL_AUTHORITY_GOAL_ID,
    }

    if recipe is not None:
        recipe_counts = dict(recipe.get("counts") or {})
        expected_total = int(
            recipe_counts.get("documents")
            if recipe_counts.get("documents") is not None
            else len(list(recipe.get("documents") or []))
        )
        if vector_count != expected_total:
            raise DocumentCountMismatchError(
                f"vector document_count {vector_count} != recipe inventory "
                f"{expected_total}"
            )
        receipt["recipe_document_count"] = expected_total
        receipt["recipe_by_family"] = dict(recipe_counts.get("by_family") or {})
        fa = dict(recipe.get("full_authority") or {})
        receipt["full_authority_complete"] = bool(fa.get("complete"))
        receipt["full_authority_inventory"] = dict(
            recipe_counts.get("full_authority") or {}
        )

    return receipt


def assert_model_pin_and_corpus_root_bound(
    result: PublicLegalVectorBuildResult,
    materialization: PublicLegalCorpusMaterialization,
) -> dict[str, Any]:
    """Prove model pin and corpus root identities are bound on the snapshot."""

    manifest = result.manifest
    if not manifest.model_pin:
        raise ModelPinError("vector build missing model pin")
    if manifest.model_pin != DEFAULT_MODEL_PIN:
        raise ModelPinError(
            f"model pin {manifest.model_pin!r} is not the production pin "
            f"{DEFAULT_MODEL_PIN!r}"
        )
    if not manifest.corpus_root_cid:
        raise CorpusRootError("vector build missing corpus_root_cid")
    if manifest.corpus_root_cid != materialization.corpus_root_cid:
        raise CorpusRootError(
            f"vector corpus_root_cid {manifest.corpus_root_cid!r} != "
            f"materialization {materialization.corpus_root_cid!r}"
        )
    if manifest.corpus_digest_sha256 != materialization.corpus_digest_sha256:
        raise CorpusRootError(
            "vector corpus_digest_sha256 diverged from materialization"
        )

    snap = result.snapshot
    if snap.manifest.identities.model is None:
        raise ModelPinError("snapshot missing model identity")
    if snap.manifest.identities.model.model_pin != DEFAULT_MODEL_PIN:
        raise ModelPinError("snapshot model pin is not the production pin")
    if snap.manifest.identities.corpus.corpus_cid != materialization.corpus_root_cid:
        raise CorpusRootError("snapshot corpus identity diverged")
    if (
        snap.manifest.identities.corpus.corpus_digest
        != materialization.corpus_digest_sha256
    ):
        raise CorpusRootError("snapshot corpus digest diverged")

    for row in result.rows:
        if row.model_pin != DEFAULT_MODEL_PIN:
            raise ModelPinError(
                f"row {row.record_id!r} model pin {row.model_pin!r} is not "
                f"the production pin"
            )

    return {
        "ok": True,
        "model_pin": manifest.model_pin,
        "corpus_root_cid": manifest.corpus_root_cid,
        "corpus_digest_sha256": manifest.corpus_digest_sha256,
        "dimension": manifest.dimension,
        "index_root_cid": manifest.index_root_cid,
        "task_id": FULL_AUTHORITY_TASK_ID,
    }


def build_full_authority_vectors(
    recipe: Mapping[str, Any] | None = None,
    *,
    stage: bool = False,
    output_dir: Path | None = None,
    created_utc: str = DEFAULT_CREATED_UTC,
    require_full_authority: bool = True,
    assert_complete: bool = True,
    materialization: PublicLegalCorpusMaterialization | None = None,
    include_vectors_in_stage: bool = True,
) -> tuple[PublicLegalVectorBuildResult, PublicLegalCorpusMaterialization, dict[str, Any]]:
    """Rebuild the pinned local vector index over the full-authority corpus.

    Parameters
    ----------
    recipe:
        Optional pre-built full-authority recipe. When omitted (and
        *materialization* is also None), builds the offline PATLAW-186 recipe.
    stage / output_dir:
        Local staging controls for bulk vector rows (never Hub upload).
    materialization:
        Optional already-materialized full-authority corpus. When provided,
        *recipe* inventory parity is still checked when *recipe* is given.
    include_vectors_in_stage:
        When staging, write full float vectors into ``vectors.jsonl`` so Hub
        packaging has bulk payload rows (PATLAW-189 acceptance).

    Returns
    -------
    (vector_result, materialization, inventory_receipt)
    """

    inventory: dict[str, Any] | None = None
    resolved_recipe: Mapping[str, Any] | None = recipe

    if materialization is None:
        if resolved_recipe is None:
            resolved_recipe = load_full_authority_recipe(
                assert_complete=assert_complete
            )
        if require_full_authority:
            assert_recipe_is_full_authority(resolved_recipe)
        materialization, inventory = materialize_full_authority_corpus(
            resolved_recipe,
            stage=False,  # corpus stage is independent; vector stage is explicit
            require_full_authority=require_full_authority,
            assert_complete=assert_complete,
        )
    elif require_full_authority and resolved_recipe is not None:
        assert_recipe_is_full_authority(resolved_recipe)

    # Full-authority corpora cover cfr/mpep/guidance only — do not require the
    # multi-family PATLAW-170 fixture set.
    builder = PublicLegalVectorBuilder(require_all_families=False)
    notes = (
        f"{FULL_AUTHORITY_TASK_ID} / {FULL_AUTHORITY_GOAL_ID} full-authority "
        f"vector rebuild over recipe "
        f"{(resolved_recipe or {}).get('recipe_id') or FULL_AUTHORITY_RECIPE_ID} "
        f"corpus_root={materialization.corpus_root_cid}"
    )
    result = builder.build_from_materialization(
        materialization,
        stage=stage,
        output_dir=output_dir,
        created_utc=created_utc,
        notes=notes,
        include_vectors_in_stage=include_vectors_in_stage,
    )

    base_receipt = validate_build(result)
    if not base_receipt.get("ok"):
        raise FullAuthorityVectorError("vector build validation failed")

    pin_receipt = assert_model_pin_and_corpus_root_bound(result, materialization)
    count_receipt = assert_vector_document_count_matches_corpus(
        result, materialization, recipe=resolved_recipe
    )

    receipt: dict[str, Any] = {
        "ok": True,
        "task_id": FULL_AUTHORITY_TASK_ID,
        "goal_id": FULL_AUTHORITY_GOAL_ID,
        "recipe_id": (resolved_recipe or {}).get("recipe_id")
        or FULL_AUTHORITY_RECIPE_ID,
        "mode": result.mode.value,
        "document_count": count_receipt["document_count"],
        "corpus_document_count": count_receipt["corpus_document_count"],
        "vector_count": count_receipt["vector_count"],
        "model_pin": pin_receipt["model_pin"],
        "corpus_root_cid": pin_receipt["corpus_root_cid"],
        "corpus_digest_sha256": pin_receipt["corpus_digest_sha256"],
        "index_root_cid": pin_receipt["index_root_cid"],
        "index_digest_sha256": result.manifest.index_digest_sha256,
        "dimension": pin_receipt["dimension"],
        "by_family": count_receipt.get("by_family") or {},
        "full_authority_complete": count_receipt.get(
            "full_authority_complete",
            bool((resolved_recipe or {}).get("full_authority", {}).get("complete")),
        ),
        "full_authority_inventory": count_receipt.get("full_authority_inventory")
        or {},
        "families": list(FULL_AUTHORITY_FAMILIES),
        "staged": result.mode is BuildMode.STAGE,
        "output_dir": result.output_dir,
        "bulk_vectors_staged": bool(
            stage and include_vectors_in_stage and result.output_dir
        ),
        "corpus_inventory": inventory,
        "validate": base_receipt,
    }
    return result, materialization, receipt


def validate_full_authority_vector_stable(
    result: PublicLegalVectorBuildResult,
    materialization: PublicLegalCorpusMaterialization,
    *,
    created_utc: str = DEFAULT_CREATED_UTC,
) -> dict[str, Any]:
    """Prove rebuild stability under fixed model + full-authority corpus pins."""

    base = validate_build(result)
    builder = PublicLegalVectorBuilder(require_all_families=False)
    second = builder.build_from_materialization(
        materialization, created_utc=created_utc
    )
    if second.index_root_cid != result.index_root_cid:
        raise VectorIntegrityError(
            "full-authority rebuild index_root_cid diverged under fixed pins"
        )
    if second.index_digest_sha256 != result.index_digest_sha256:
        raise VectorIntegrityError(
            "full-authority rebuild index_digest diverged under fixed pins"
        )
    if second.model_pin != result.model_pin:
        raise ModelPinError("full-authority rebuild model pin diverged")
    if second.corpus_root_cid != result.corpus_root_cid:
        raise CorpusRootError("full-authority rebuild corpus root diverged")
    if not builds_are_byte_identical(result, second):
        # Byte-level check may include mode/output_dir; fall back to digests
        # when one side is staged and the other is dry-run.
        if result.mode is second.mode and result.output_dir == second.output_dir:
            raise VectorIntegrityError(
                "full-authority rebuild is not byte-identical under fixed pins"
            )
    base["rebuild_index_root_cid"] = second.index_root_cid
    base["rebuild_stable"] = True
    base["task_id"] = FULL_AUTHORITY_TASK_ID
    return base


# ---------------------------------------------------------------------------
# Shared helpers
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
            f"({TASK_ID} / {FULL_AUTHORITY_TASK_ID}). Default: dry-run, no Hub upload."
        )
    )
    input_group = parser.add_mutually_exclusive_group(required=False)
    input_group.add_argument(
        "--full-authority",
        action="store_true",
        help=(
            "Rebuild vector index from offline full-authority recipe "
            f"(PATLAW-186/187 → {FULL_AUTHORITY_TASK_ID}). Enforces document "
            "count parity, model pin, and corpus root binding."
        ),
    )
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
            "Directory with staged PATLAW-170/187 corpus artifacts "
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
            "Write local staged artifacts (manifest, vectors.jsonl bulk rows, "
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
        "--require-full-authority",
        action="store_true",
        help=(
            "When loading --recipe or --from-corpus-dir, require full-authority "
            "completeness and document-count parity (PATLAW-189)"
        ),
    )
    parser.add_argument(
        "--print-manifest",
        action="store_true",
        help="Print the vector manifest JSON to stdout",
    )
    parser.add_argument(
        "--print-inventory-receipt",
        action="store_true",
        help="Print the full-authority inventory/parity receipt JSON",
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
    inventory: Mapping[str, Any] | None = None,
    full_authority: bool = False,
) -> None:
    manifest = result.manifest
    task_label = FULL_AUTHORITY_TASK_ID if full_authority else TASK_ID
    print(f"task_id:              {task_label}")
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
    if inventory is not None:
        print(f"inventory_match:      {inventory.get('ok')}")
        print(
            f"corpus_document_count:{inventory.get('corpus_document_count')}"
        )
        by_family = inventory.get("by_family") or {}
        if by_family:
            print(f"by_family:            {dict(by_family)}")
        fa_inv = inventory.get("full_authority_inventory") or {}
        if fa_inv:
            print(f"full_authority:       {fa_inv}")
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
        args.full_authority
        or args.default_fixture
        or args.recipe is not None
        or args.from_corpus_dir is not None
    ):
        parser.error(
            "one of --full-authority, --default-fixture, --recipe, "
            "--from-corpus-dir, --validate-manifest, --list-model-pin, "
            "or --write-full-authority-recipe is required"
        )

    if args.stage and args.output_dir is None:
        parser.error("--output-dir is required with --stage")

    inventory: dict[str, Any] | None = None
    full_authority_mode = bool(args.full_authority or args.require_full_authority)
    materialization: PublicLegalCorpusMaterialization | None = None
    recipe: Mapping[str, Any] | None = None
    result: PublicLegalVectorBuildResult | None = None

    try:
        if args.full_authority:
            result, materialization, inventory = build_full_authority_vectors(
                stage=bool(args.stage),
                output_dir=args.output_dir,
                created_utc=str(args.created_utc),
                require_full_authority=True,
            )
            full_authority_mode = True
        elif args.default_fixture:
            builder = PublicLegalVectorBuilder(require_all_families=True)
            result = builder.build_from_default_fixture(
                stage=bool(args.stage),
                output_dir=args.output_dir,
                created_utc=str(args.created_utc),
            )
        elif args.recipe is not None:
            recipe = _load_json_object(args.recipe)
            fa_complete = bool((recipe.get("full_authority") or {}).get("complete"))
            if args.require_full_authority or fa_complete:
                result, materialization, inventory = build_full_authority_vectors(
                    recipe,
                    stage=bool(args.stage),
                    output_dir=args.output_dir,
                    created_utc=str(args.created_utc),
                    require_full_authority=True,
                )
                full_authority_mode = True
            else:
                builder = PublicLegalVectorBuilder(require_all_families=True)
                result = builder.build(
                    recipe=recipe,
                    stage=bool(args.stage),
                    output_dir=args.output_dir,
                    created_utc=str(args.created_utc),
                )
        elif args.from_corpus_dir is not None:
            materialization = _materialization_from_staged_corpus(args.from_corpus_dir)
            if args.require_full_authority:
                # Treat staged corpus as full-authority source; parity against
                # corpus counts only (recipe optional).
                builder = PublicLegalVectorBuilder(require_all_families=False)
                result = builder.build_from_materialization(
                    materialization,
                    stage=bool(args.stage),
                    output_dir=args.output_dir,
                    created_utc=str(args.created_utc),
                    notes=(
                        f"{FULL_AUTHORITY_TASK_ID} rebuild from staged corpus "
                        f"{args.from_corpus_dir}"
                    ),
                )
                receipt = validate_build(result)
                if not receipt.get("ok"):
                    print("error: vector build validation failed", file=sys.stderr)
                    return 2
                pin_receipt = assert_model_pin_and_corpus_root_bound(
                    result, materialization
                )
                count_receipt = assert_vector_document_count_matches_corpus(
                    result, materialization
                )
                inventory = {
                    "ok": True,
                    **count_receipt,
                    **{
                        k: v
                        for k, v in pin_receipt.items()
                        if k not in count_receipt
                    },
                }
                full_authority_mode = True
            else:
                builder = PublicLegalVectorBuilder(require_all_families=True)
                result = builder.build_from_materialization(
                    materialization,
                    stage=bool(args.stage),
                    output_dir=args.output_dir,
                    created_utc=str(args.created_utc),
                )
        else:
            parser.error("no vector build input selected")

        assert result is not None
        if not full_authority_mode:
            receipt = validate_build(result)
            if not receipt.get("ok"):
                print("error: vector build validation failed", file=sys.stderr)
                return 2

        if args.prove_stable:
            if full_authority_mode and materialization is not None:
                stable = validate_full_authority_vector_stable(
                    result,
                    materialization,
                    created_utc=str(args.created_utc),
                )
            elif recipe is not None:
                stable = validate_build_stable(
                    result,
                    recipe=recipe,
                    created_utc=str(args.created_utc),
                )
            elif materialization is not None:
                second = PublicLegalVectorBuilder(
                    require_all_families=False
                ).build_from_materialization(
                    materialization,
                    created_utc=str(args.created_utc),
                )
                if second.index_root_cid != result.index_root_cid:
                    print(
                        "error: rebuild index_root_cid diverged under fixed pins",
                        file=sys.stderr,
                    )
                    return 2
                stable = {"rebuild_stable": True, **validate_build(result)}
            else:
                stable = validate_build_stable(
                    result, created_utc=str(args.created_utc)
                )
            if not stable.get("rebuild_stable"):
                print("error: rebuild stability check failed", file=sys.stderr)
                return 2

    except DocumentCountMismatchError as exc:
        print(f"error (document count mismatch): {exc}", file=sys.stderr)
        return 2
    except FullAuthorityVectorError as exc:
        print(f"error (full-authority): {exc}", file=sys.stderr)
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
    except Exception as exc:
        msg = str(exc)
        code = getattr(exc, "code", "") or ""
        if "full_authority" in code or "ecfr_only" in code or "chapter_only" in code:
            print(f"error (full-authority): {exc}", file=sys.stderr)
            return 2
        if type(exc).__name__ in {
            "FullAuthorityIncompleteError",
            "EcfrOnlyCompletionError",
            "ChapterOnlyMpepCompletionError",
            "ProductionRecipeError",
            "FullAuthorityMaterializeError",
            "InventoryCountMismatchError",
        }:
            print(f"error (full-authority): {exc}", file=sys.stderr)
            return 2
        print(f"error: {exc}", file=sys.stderr)
        return 2

    assert result is not None

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
