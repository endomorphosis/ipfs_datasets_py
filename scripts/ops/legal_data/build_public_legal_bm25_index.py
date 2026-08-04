#!/usr/bin/env python3
"""Build a production BM25 index snapshot for the public legal corpus.

PATLAW-171 — deterministic documents/terms/postings BM25 snapshot bound to a
pinned public patent-law / regulations corpus root (PATLAW-170).

PATLAW-188 — rebuild the same BM25 surface from the full-authority public
legal corpus (PATLAW-187 materialization of the PATLAW-186 production recipe).
Full-authority acceptance requires:

* BM25 ``document_count`` equals corpus ``document_count``
* Index digests bind the corpus root (``corpus_root_cid``)
* Bulk JSONL + parquet payloads are staged under Hub Viewer paths for packaging

Default mode is **dry-run**: admission, indexing, and content-addressing run
in memory and a summary is printed. Local staging occurs only with
``--stage`` (and ``--output-dir``). This script never authenticates or uploads
to Hugging Face.

Input options (one required):

* ``--full-authority`` — offline full-authority recipe + materialize + BM25
* ``--default-fixture`` — materialize the built-in multi-family CI corpus recipe
  and build BM25 over it
* ``--corpus-dir`` — load a staged public legal corpus directory
* ``--recipe`` — compact corpus recipe JSON (source_roots + documents)
* ``--validate-snapshot`` — load and validate an existing staged BM25 snapshot
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Mapping, Optional, Sequence, Union


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.domains.patent.public_legal_bm25_builder import (  # noqa: E402
    DOCUMENTS_FILENAME,
    INDEX_ROOT_FILENAME,
    MANIFEST_FILENAME,
    POSTINGS_FILENAME,
    RECEIPT_FILENAME,
    RELEASE_CONFIGS,
    RELEASE_DOCUMENTS_PATTERN,
    RELEASE_POSTINGS_PATTERN,
    RELEASE_REPOSITORY,
    RELEASE_ROLE,
    SCHEMA_VERSION,
    TASK_ID,
    TERMS_FILENAME,
    BuildMode,
    CorpusPinError,
    OrphanDocumentError,
    OrphanPostingError,
    OrphanTermError,
    PrivateOrMixedInputError,
    PublicLegalBm25Builder,
    PublicLegalBm25Error,
    PublicLegalBm25Snapshot,
    build_public_legal_bm25_index,
    canonical_json,
    load_bm25_manifest,
    load_bm25_snapshot,
    validate_snapshot,
)
from ipfs_datasets_py.processors.domains.patent.public_legal_corpus_materializer import (  # noqa: E402
    build_default_public_legal_recipe,
)

# ---------------------------------------------------------------------------
# Pins (PATLAW-188 full-authority BM25 rebuild surface)
# ---------------------------------------------------------------------------

FULL_AUTHORITY_TASK_ID: Final = "PATLAW-188"
FULL_AUTHORITY_GOAL_ID: Final = "PATLAW-G218"
FULL_AUTHORITY_RECIPE_ID: Final = "patlaw-full-authority-public-legal-corpus"
FULL_AUTHORITY_FAMILIES: Final = ("cfr", "mpep", "guidance")
MATERIALIZE_SCRIPT: Final = (
    Path(__file__).resolve().parent / "materialize_public_legal_corpus.py"
)
PRODUCTION_RECIPE_SCRIPT: Final = (
    Path(__file__).resolve().parent / "build_public_legal_production_recipe.py"
)

# Hub Viewer bulk layout (hf_layout_v2 / release packaging patterns).
HUB_DOCUMENTS_JSONL: Final = "data/bm25/documents/train.jsonl"
HUB_POSTINGS_JSONL: Final = "data/bm25/postings/train.jsonl"
HUB_TERMS_JSONL: Final = "data/bm25/terms/train.jsonl"
HUB_DOCUMENTS_PARQUET: Final = "data/bm25/documents/part-000000.parquet"
HUB_POSTINGS_PARQUET: Final = "data/bm25/postings/part-000000.parquet"
HUB_TERMS_PARQUET: Final = "data/bm25/terms/part-000000.parquet"
HUB_BULK_RECEIPT_FILENAME: Final = "hub-bm25-bulk-receipt.json"
HUB_BULK_LAYOUT_VERSION: Final = "patent.public_legal_bm25.hub_bulk.v1"

_FILE_MODE: Final = 0o600
_DIR_MODE: Final = 0o700

PathLike = Union[str, Path]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FullAuthorityBm25Error(PublicLegalBm25Error):
    """Raised when full-authority BM25 rebuild / hub staging fails."""

    code = "full_authority_bm25_error"


class DocumentCountMismatchError(FullAuthorityBm25Error):
    """Raised when BM25 document_count does not equal corpus document_count."""

    code = "document_count_mismatch"


class HubBulkStagingError(FullAuthorityBm25Error):
    """Raised when Hub bulk JSONL/parquet staging fails."""

    code = "hub_bulk_staging_error"


# ---------------------------------------------------------------------------
# Module loaders (PATLAW-186 / PATLAW-187)
# ---------------------------------------------------------------------------


def _load_script_module(path: Path, module_name: str) -> ModuleType:
    if not path.is_file():
        raise FullAuthorityBm25Error(f"missing required script: {path}")
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise FullAuthorityBm25Error(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_materialize_module() -> ModuleType:
    return _load_script_module(
        MATERIALIZE_SCRIPT, "_patlaw188_materialize_public_legal_corpus"
    )


def _load_production_recipe_module() -> ModuleType:
    return _load_script_module(
        PRODUCTION_RECIPE_SCRIPT, "_patlaw188_build_public_legal_production_recipe"
    )


def load_full_authority_recipe(
    *,
    assert_complete: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build the offline full-authority production recipe (PATLAW-186)."""

    build_mod = _load_production_recipe_module()
    recipe = build_mod.build_full_authority_recipe(
        assert_complete=assert_complete,
        **kwargs,
    )
    if not isinstance(recipe, dict):
        raise FullAuthorityBm25Error("full-authority recipe must be a dict")
    return recipe


def assert_recipe_is_full_authority(recipe: Mapping[str, Any]) -> None:
    """Fail closed unless *recipe* proves full-authority completeness."""

    build_mod = _load_production_recipe_module()
    build_mod.assert_full_authority_complete(recipe)


# ---------------------------------------------------------------------------
# Hub bulk encoding / staging
# ---------------------------------------------------------------------------


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, _DIR_MODE)
    except OSError:
        pass


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    _ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(payload)
    try:
        os.chmod(tmp, _FILE_MODE)
    except OSError:
        pass
    tmp.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        return b""
    lines = [canonical_json(dict(row)) for row in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


def encode_rows_parquet(rows: Sequence[Mapping[str, Any]]) -> bytes:
    """Encode tabular rows as deterministic ZSTD Parquet bytes (Hub bulk).

    Requires the optional ``pyarrow`` package (present in the sealed validation
    environment). Empty row sets fail closed — Hub bulk payloads must be
    non-vacuous for an admitted full-authority corpus.
    """

    if not rows:
        raise HubBulkStagingError("parquet bulk payload requires at least one row")
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise HubBulkStagingError(
            "parquet encoding requires the optional 'pyarrow' package"
        ) from exc

    # Stable column union: first-seen key order across all rows.
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    columns: dict[str, list[Any]] = {key: [] for key in keys}
    for row in rows:
        for key in keys:
            value = row.get(key)
            # Parquet-friendly scalars; nested structures become canonical JSON.
            if isinstance(value, (dict, list, tuple)):
                columns[key].append(canonical_json(value))
            else:
                columns[key].append(value)

    table = pa.table(columns)
    buffer = io.BytesIO()
    pq.write_table(
        table,
        buffer,
        compression="zstd",
        compression_level=6,
        row_group_size=max(len(rows), 1),
        use_dictionary=True,
        write_statistics=True,
        write_page_index=False,
        data_page_version="1.0",
    )
    return buffer.getvalue()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def stage_hub_bulk_payloads(
    snapshot: PublicLegalBm25Snapshot,
    output_dir: PathLike,
) -> dict[str, Any]:
    """Stage Hub-packaging bulk JSONL + parquet under Viewer-aligned paths.

    Layout (relative to *output_dir*):

    * ``data/bm25/documents/train.jsonl`` + ``part-000000.parquet``
    * ``data/bm25/postings/train.jsonl`` + ``part-000000.parquet``
    * ``data/bm25/terms/train.jsonl`` + ``part-000000.parquet``
    * ``hub-bm25-bulk-receipt.json`` binding corpus root + index digests

    Never uploads to Hugging Face.
    """

    root = Path(output_dir)
    _ensure_dir(root)

    doc_rows = [dict(r) for r in snapshot.release_document_rows()]
    post_rows = [dict(r) for r in snapshot.release_posting_rows()]
    term_rows = [t.to_dict() for t in snapshot.terms]

    if len(doc_rows) != snapshot.manifest.counts.document_count:
        raise HubBulkStagingError(
            "release document rows do not match BM25 document_count"
        )
    if not doc_rows:
        raise HubBulkStagingError("cannot stage empty documents bulk payload")
    if not post_rows:
        raise HubBulkStagingError("cannot stage empty postings bulk payload")
    if not term_rows:
        raise HubBulkStagingError("cannot stage empty terms bulk payload")

    artifacts: dict[str, dict[str, Any]] = {}

    def _write_pair(
        *,
        rel_jsonl: str,
        rel_parquet: str,
        rows: Sequence[Mapping[str, Any]],
        config_name: str,
    ) -> None:
        jsonl_blob = _jsonl_bytes(rows)
        parquet_blob = encode_rows_parquet(rows)
        _atomic_write_bytes(root / rel_jsonl, jsonl_blob)
        _atomic_write_bytes(root / rel_parquet, parquet_blob)
        artifacts[config_name] = {
            "config_name": config_name,
            "jsonl_path": rel_jsonl,
            "jsonl_sha256": _sha256_bytes(jsonl_blob),
            "jsonl_bytes": len(jsonl_blob),
            "parquet_path": rel_parquet,
            "parquet_sha256": _sha256_bytes(parquet_blob),
            "parquet_bytes": len(parquet_blob),
            "row_count": len(rows),
        }

    _write_pair(
        rel_jsonl=HUB_DOCUMENTS_JSONL,
        rel_parquet=HUB_DOCUMENTS_PARQUET,
        rows=doc_rows,
        config_name="bm25_documents",
    )
    _write_pair(
        rel_jsonl=HUB_POSTINGS_JSONL,
        rel_parquet=HUB_POSTINGS_PARQUET,
        rows=post_rows,
        config_name="bm25_postings",
    )
    _write_pair(
        rel_jsonl=HUB_TERMS_JSONL,
        rel_parquet=HUB_TERMS_PARQUET,
        rows=term_rows,
        config_name="bm25_terms",
    )

    # Prove release packaging path patterns remain bound.
    if not RELEASE_DOCUMENTS_PATTERN.endswith("*.parquet"):
        raise HubBulkStagingError("documents release pattern is not parquet-glob")
    if not RELEASE_POSTINGS_PATTERN.endswith("*.parquet"):
        raise HubBulkStagingError("postings release pattern is not parquet-glob")

    receipt: dict[str, Any] = {
        "ok": True,
        "layout_version": HUB_BULK_LAYOUT_VERSION,
        "task_id": FULL_AUTHORITY_TASK_ID,
        "goal_id": FULL_AUTHORITY_GOAL_ID,
        "schema_version": SCHEMA_VERSION,
        "role": RELEASE_ROLE,
        "repository": RELEASE_REPOSITORY,
        "release_configs": list(RELEASE_CONFIGS),
        "corpus_root_cid": snapshot.corpus_root_cid,
        "index_cid": snapshot.index_cid,
        "index_digest_sha256": snapshot.index_digest_sha256,
        "document_count": snapshot.manifest.counts.document_count,
        "term_count": snapshot.manifest.counts.term_count,
        "posting_count": snapshot.manifest.counts.posting_count,
        "release_document_row_count": len(doc_rows),
        "release_posting_row_count": len(post_rows),
        "artifacts": artifacts,
        "data_files_patterns": {
            "bm25_documents": RELEASE_DOCUMENTS_PATTERN,
            "bm25_postings": RELEASE_POSTINGS_PATTERN,
        },
        "hub_upload": False,
    }
    _atomic_write_text(
        root / HUB_BULK_RECEIPT_FILENAME,
        canonical_json(receipt) + "\n",
    )
    return receipt


def assert_bm25_binds_corpus(
    snapshot: PublicLegalBm25Snapshot,
    *,
    corpus_document_count: int,
    corpus_root_cid: str,
) -> dict[str, Any]:
    """Fail closed unless BM25 counts and digests bind the corpus root."""

    bm25_count = int(snapshot.manifest.counts.document_count)
    if bm25_count != int(corpus_document_count):
        raise DocumentCountMismatchError(
            f"BM25 document_count={bm25_count} does not equal "
            f"corpus document_count={corpus_document_count}"
        )
    if bm25_count != len(snapshot.documents):
        raise DocumentCountMismatchError(
            "BM25 counts.document_count does not match documents list length"
        )
    if snapshot.corpus_root_cid != corpus_root_cid:
        raise FullAuthorityBm25Error(
            f"index corpus_root_cid={snapshot.corpus_root_cid!r} does not bind "
            f"materialization corpus_root_cid={corpus_root_cid!r}"
        )
    if snapshot.manifest.corpus_root_cid != corpus_root_cid:
        raise FullAuthorityBm25Error(
            "manifest.corpus_root_cid does not bind materialization root"
        )
    if snapshot.manifest.corpus_document_count != corpus_document_count:
        raise DocumentCountMismatchError(
            "manifest.corpus_document_count does not equal corpus document_count"
        )
    if not snapshot.index_cid or not snapshot.index_cid.startswith("b"):
        raise FullAuthorityBm25Error("index_cid missing or invalid")
    digest = snapshot.index_digest_sha256
    if not isinstance(digest, str) or len(digest) != 64:
        raise FullAuthorityBm25Error("index_digest_sha256 missing or invalid")
    # Digest must be bound through the manifest pin as well.
    if snapshot.manifest.index_digest_sha256 != digest:
        raise FullAuthorityBm25Error("manifest index digest does not match snapshot")
    if snapshot.manifest.index_cid != snapshot.index_cid:
        raise FullAuthorityBm25Error("manifest index_cid does not match snapshot")

    return {
        "ok": True,
        "document_count": bm25_count,
        "corpus_document_count": int(corpus_document_count),
        "corpus_root_cid": corpus_root_cid,
        "index_cid": snapshot.index_cid,
        "index_digest_sha256": digest,
        "task_id": FULL_AUTHORITY_TASK_ID,
    }


# ---------------------------------------------------------------------------
# Full-authority rebuild entrypoint
# ---------------------------------------------------------------------------


def build_full_authority_bm25_index(
    recipe: Mapping[str, Any] | None = None,
    *,
    stage: bool = False,
    output_dir: PathLike | None = None,
    expected_corpus_root_cid: str | None = None,
    require_full_authority: bool = True,
    assert_complete: bool = True,
    stage_hub_bulk: bool = True,
    k1: float = 1.5,
    b: float = 0.75,
) -> tuple[PublicLegalBm25Snapshot, dict[str, Any], Optional[dict[str, Any]]]:
    """Rebuild BM25 from the full-authority public legal corpus (PATLAW-188).

    Parameters
    ----------
    recipe:
        Optional pre-built full-authority recipe. When omitted, builds the
        offline PATLAW-186 recipe via the PATLAW-187 materializer surface.
    stage / output_dir:
        Local staging controls (never Hub upload). When *stage* is True,
        writes the standard BM25 snapshot plus Hub bulk JSONL/parquet.
    expected_corpus_root_cid:
        Optional pin; fail closed on mismatch with the materialization root.
    stage_hub_bulk:
        When staging, also write Viewer-aligned bulk JSONL + parquet payloads
        (default True for full-authority rebuilds).

    Returns
    -------
    (snapshot, inventory_receipt, hub_bulk_receipt_or_None)
    """

    mat_mod = _load_materialize_module()

    if recipe is None:
        materialization, inventory = mat_mod.materialize_full_authority_corpus(
            stage=False,
            output_dir=None,
            require_full_authority=require_full_authority,
            assert_complete=assert_complete,
        )
    else:
        if not isinstance(recipe, Mapping):
            raise FullAuthorityBm25Error("recipe must be a mapping")
        if require_full_authority:
            assert_recipe_is_full_authority(recipe)
        materialization, inventory = mat_mod.materialize_full_authority_corpus(
            recipe,
            stage=False,
            output_dir=None,
            require_full_authority=require_full_authority,
            assert_complete=assert_complete,
        )

    corpus_root_cid = materialization.corpus_root_cid
    corpus_document_count = int(materialization.manifest.counts.total_documents)
    if corpus_document_count < 1:
        raise FullAuthorityBm25Error("full-authority corpus is empty")

    if expected_corpus_root_cid is not None:
        pin = str(expected_corpus_root_cid).strip()
        if pin != corpus_root_cid:
            raise CorpusPinError(
                f"expected corpus_root_cid={pin!r} but materialization produced "
                f"{corpus_root_cid!r}"
            )

    notes = (
        f"[{FULL_AUTHORITY_TASK_ID} / {FULL_AUTHORITY_GOAL_ID}] full-authority "
        f"BM25 rebuild bound to corpus_root_cid={corpus_root_cid} "
        f"recipe_id={FULL_AUTHORITY_RECIPE_ID}"
    )

    # Build in-memory first so we can enforce count parity before any write.
    snapshot = build_public_legal_bm25_index(
        materialization,
        stage=False,
        output_dir=None,
        notes=notes,
        expected_corpus_root_cid=corpus_root_cid,
        k1=float(k1),
        b=float(b),
    )

    bind_receipt = assert_bm25_binds_corpus(
        snapshot,
        corpus_document_count=corpus_document_count,
        corpus_root_cid=corpus_root_cid,
    )
    inventory = dict(inventory)
    inventory["bm25_bind"] = bind_receipt
    inventory["bm25_document_count"] = snapshot.manifest.counts.document_count
    inventory["bm25_index_cid"] = snapshot.index_cid
    inventory["bm25_index_digest_sha256"] = snapshot.index_digest_sha256

    # Snapshot integrity (orphans, packaging schema, digest round-trip).
    validation = validate_snapshot(snapshot)
    if not validation.get("ok"):
        raise FullAuthorityBm25Error("full-authority BM25 snapshot validation failed")
    inventory["snapshot_validation"] = validation

    hub_receipt: Optional[dict[str, Any]] = None
    if stage:
        if output_dir is None:
            raise FullAuthorityBm25Error("output_dir is required when stage=True")
        builder = PublicLegalBm25Builder(k1=float(k1), b=float(b))
        snapshot = builder.stage(snapshot, output_dir=output_dir)
        # Re-assert bind after stage (content-address must be stable).
        assert_bm25_binds_corpus(
            snapshot,
            corpus_document_count=corpus_document_count,
            corpus_root_cid=corpus_root_cid,
        )
        if stage_hub_bulk:
            hub_receipt = stage_hub_bulk_payloads(snapshot, output_dir)
            inventory["hub_bulk"] = {
                "ok": True,
                "receipt_path": HUB_BULK_RECEIPT_FILENAME,
                "document_rows": hub_receipt["release_document_row_count"],
                "posting_rows": hub_receipt["release_posting_row_count"],
                "artifacts": sorted(hub_receipt["artifacts"].keys()),
            }

    return snapshot, inventory, hub_receipt


# ---------------------------------------------------------------------------
# CLI
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
            "Build a deterministic public legal BM25 index snapshot "
            f"({TASK_ID} / {FULL_AUTHORITY_TASK_ID}). Default: dry-run, no Hub upload."
        )
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--full-authority",
        action="store_true",
        help=(
            "Materialize the offline full-authority public legal corpus "
            f"(PATLAW-187) and rebuild BM25 ({FULL_AUTHORITY_TASK_ID}). "
            "Enforces document_count parity, corpus root digests, and stages "
            "Hub bulk JSONL/parquet when --stage is set."
        ),
    )
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
            "JSONL, snapshot receipt, index-root pin; full-authority also "
            "stages Hub bulk JSONL/parquet). Default is dry-run only."
        ),
    )
    parser.add_argument(
        "--no-stage-hub-bulk",
        action="store_true",
        help="With --full-authority --stage, skip Hub bulk JSONL/parquet writes",
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
        "--require-full-authority",
        action="store_true",
        help=(
            "When loading --recipe, require full-authority completeness and "
            "inventory count parity (PATLAW-188 path)."
        ),
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
        "--print-inventory-receipt",
        action="store_true",
        help="Print the full-authority inventory + bind receipt JSON to stdout",
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


def _print_summary(
    result: PublicLegalBm25Snapshot,
    *,
    inventory: Mapping[str, Any] | None = None,
    hub_receipt: Mapping[str, Any] | None = None,
    full_authority: bool = False,
) -> None:
    manifest = result.manifest
    task_label = FULL_AUTHORITY_TASK_ID if full_authority else TASK_ID
    print(f"task_id:              {task_label}")
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
    if inventory is not None:
        print(f"inventory_match:      {inventory.get('ok')}")
        print(
            f"corpus_document_count:{inventory.get('document_count')}"
        )
        bind = inventory.get("bm25_bind") or {}
        if bind:
            print(f"bm25_bind_ok:         {bind.get('ok')}")
        fa_inv = inventory.get("full_authority_inventory") or {}
        if fa_inv:
            print(f"full_authority:       {fa_inv}")
    if hub_receipt is not None:
        print(f"hub_bulk_ok:          {hub_receipt.get('ok')}")
        arts = hub_receipt.get("artifacts") or {}
        for name, meta in sorted(arts.items()):
            print(
                f"  hub[{name}]: rows={meta.get('row_count')} "
                f"jsonl={meta.get('jsonl_path')} parquet={meta.get('parquet_path')}"
            )
    if result.output_dir:
        print(f"output_dir:           {result.output_dir}")
        print(f"  - {MANIFEST_FILENAME}")
        print(f"  - {DOCUMENTS_FILENAME}")
        print(f"  - {TERMS_FILENAME}")
        print(f"  - {POSTINGS_FILENAME}")
        print(f"  - {RECEIPT_FILENAME}")
        print(f"  - {INDEX_ROOT_FILENAME}")
        if hub_receipt is not None:
            print(f"  - {HUB_BULK_RECEIPT_FILENAME}")
            print(f"  - {HUB_DOCUMENTS_JSONL}")
            print(f"  - {HUB_DOCUMENTS_PARQUET}")
            print(f"  - {HUB_POSTINGS_JSONL}")
            print(f"  - {HUB_POSTINGS_PARQUET}")
            print(f"  - {HUB_TERMS_JSONL}")
            print(f"  - {HUB_TERMS_PARQUET}")


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

    inventory: dict[str, Any] | None = None
    hub_receipt: Optional[dict[str, Any]] = None
    full_authority_mode = bool(
        args.full_authority or args.require_full_authority
    )
    result: PublicLegalBm25Snapshot

    try:
        if args.full_authority:
            result, inventory, hub_receipt = build_full_authority_bm25_index(
                stage=bool(args.stage),
                output_dir=args.output_dir,
                expected_corpus_root_cid=args.expected_corpus_root_cid,
                require_full_authority=True,
                stage_hub_bulk=not bool(args.no_stage_hub_bulk),
                k1=float(args.k1),
                b=float(args.b),
            )
            full_authority_mode = True
        elif args.default_fixture:
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
            fa_complete = bool((recipe.get("full_authority") or {}).get("complete"))
            if args.require_full_authority or fa_complete:
                result, inventory, hub_receipt = build_full_authority_bm25_index(
                    recipe,
                    stage=bool(args.stage),
                    output_dir=args.output_dir,
                    expected_corpus_root_cid=args.expected_corpus_root_cid,
                    require_full_authority=True,
                    stage_hub_bulk=not bool(args.no_stage_hub_bulk),
                    k1=float(args.k1),
                    b=float(args.b),
                )
                full_authority_mode = True
            else:
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

    except DocumentCountMismatchError as exc:
        print(f"error (document count mismatch): {exc}", file=sys.stderr)
        return 2
    except HubBulkStagingError as exc:
        print(f"error (hub bulk staging): {exc}", file=sys.stderr)
        return 2
    except FullAuthorityBm25Error as exc:
        print(f"error (full-authority bm25): {exc}", file=sys.stderr)
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
    except Exception as exc:
        code = getattr(exc, "code", "") or ""
        name = type(exc).__name__
        if (
            "full_authority" in str(code)
            or "ecfr_only" in str(code)
            or "chapter_only" in str(code)
            or name
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

    if args.print_inventory_receipt and inventory is not None:
        print(json.dumps(inventory, indent=2, sort_keys=True, ensure_ascii=False))
    elif args.print_manifest:
        print(result.manifest.to_canonical_json())
    elif args.print_receipt:
        print(
            json.dumps(
                result.manifest.to_receipt(), sort_keys=True, separators=(",", ":")
            )
        )
    elif not args.no_print_summary:
        _print_summary(
            result,
            inventory=inventory,
            hub_receipt=hub_receipt,
            full_authority=full_authority_mode,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
