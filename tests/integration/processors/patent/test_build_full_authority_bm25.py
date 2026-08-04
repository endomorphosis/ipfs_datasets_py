"""Integration tests: rebuild BM25 from full-authority public legal corpus (PATLAW-188).

Acceptance:

* BM25 document_count equals corpus document_count
* Index digests bind corpus root (corpus_root_cid + index_cid/digest pins)
* Bulk JSONL/parquet payloads are staged for Hub packaging
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.public_legal_bm25_builder import (
    DOCUMENTS_FILENAME,
    INDEX_ROOT_FILENAME,
    MANIFEST_FILENAME,
    POSTINGS_FILENAME,
    RECEIPT_FILENAME,
    RELEASE_DOCUMENTS_PATTERN,
    RELEASE_POSTINGS_PATTERN,
    TERMS_FILENAME,
    BuildMode,
    CorpusPinError,
    load_bm25_snapshot,
    snapshots_are_byte_identical,
    validate_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
BUILD_SCRIPT = (
    REPO_ROOT / "scripts" / "ops" / "legal_data" / "build_public_legal_bm25_index.py"
)
MATERIALIZE_SCRIPT = (
    REPO_ROOT / "scripts" / "ops" / "legal_data" / "materialize_public_legal_corpus.py"
)
RECIPE_SCRIPT = (
    REPO_ROOT / "scripts" / "ops" / "legal_data" / "build_public_legal_production_recipe.py"
)


def _load_module(path: Path, module_name: str):
    assert path.is_file(), f"missing script at {path}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so imports / dataclasses can resolve cls.__module__.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bm25_mod():
    return _load_module(BUILD_SCRIPT, "build_public_legal_bm25_index_patlaw188")


@pytest.fixture(scope="module")
def mat_mod():
    return _load_module(MATERIALIZE_SCRIPT, "materialize_public_legal_corpus_patlaw188")


@pytest.fixture(scope="module")
def recipe_mod():
    return _load_module(RECIPE_SCRIPT, "build_public_legal_production_recipe_patlaw188")


@pytest.fixture(scope="module")
def full_recipe(recipe_mod):
    return recipe_mod.build_full_authority_recipe(assert_complete=True)


@pytest.fixture(scope="module")
def baseline(bm25_mod, full_recipe):
    snapshot, inventory, hub = bm25_mod.build_full_authority_bm25_index(
        full_recipe,
        require_full_authority=True,
        stage=False,
    )
    return snapshot, inventory, hub


# ---------------------------------------------------------------------------
# Declared outputs / pins
# ---------------------------------------------------------------------------


def test_declared_outputs_exist() -> None:
    assert BUILD_SCRIPT.is_file()
    assert MATERIALIZE_SCRIPT.is_file()
    assert RECIPE_SCRIPT.is_file()


def test_module_pins(bm25_mod) -> None:
    assert bm25_mod.FULL_AUTHORITY_TASK_ID == "PATLAW-188"
    assert bm25_mod.FULL_AUTHORITY_GOAL_ID == "PATLAW-G218"
    assert bm25_mod.FULL_AUTHORITY_RECIPE_ID == (
        "patlaw-full-authority-public-legal-corpus"
    )
    assert tuple(bm25_mod.FULL_AUTHORITY_FAMILIES) == ("cfr", "mpep", "guidance")
    assert bm25_mod.HUB_BULK_LAYOUT_VERSION.startswith("patent.public_legal_bm25")
    assert bm25_mod.HUB_DOCUMENTS_PARQUET.endswith(".parquet")
    assert bm25_mod.HUB_POSTINGS_PARQUET.endswith(".parquet")


# ---------------------------------------------------------------------------
# Full-authority BM25 rebuild: count parity + digest binding
# ---------------------------------------------------------------------------


def test_document_count_equals_corpus_document_count(
    bm25_mod, mat_mod, full_recipe, baseline
) -> None:
    snapshot, inventory, _hub = baseline
    materialization, mat_inv = mat_mod.materialize_full_authority_corpus(
        full_recipe,
        require_full_authority=True,
    )
    corpus_count = int(materialization.manifest.counts.total_documents)
    recipe_count = int(full_recipe["counts"]["documents"])

    assert corpus_count == recipe_count
    assert snapshot.manifest.counts.document_count == corpus_count
    assert len(snapshot.documents) == corpus_count
    assert snapshot.manifest.corpus_document_count == corpus_count
    assert inventory["document_count"] == corpus_count
    assert inventory["bm25_document_count"] == corpus_count
    assert inventory["bm25_bind"]["ok"] is True
    assert mat_inv["ok"] is True


def test_index_digests_bind_corpus_root(
    bm25_mod, mat_mod, full_recipe, baseline
) -> None:
    snapshot, inventory, _hub = baseline
    materialization, _ = mat_mod.materialize_full_authority_corpus(
        full_recipe,
        require_full_authority=True,
    )

    assert snapshot.corpus_root_cid == materialization.corpus_root_cid
    assert snapshot.manifest.corpus_root_cid == materialization.corpus_root_cid
    assert snapshot.index_cid.startswith("b")
    assert len(snapshot.index_digest_sha256) == 64
    assert snapshot.manifest.index_cid == snapshot.index_cid
    assert snapshot.manifest.index_digest_sha256 == snapshot.index_digest_sha256

    bind = bm25_mod.assert_bm25_binds_corpus(
        snapshot,
        corpus_document_count=materialization.manifest.counts.total_documents,
        corpus_root_cid=materialization.corpus_root_cid,
    )
    assert bind["ok"] is True
    assert bind["corpus_root_cid"] == materialization.corpus_root_cid
    assert inventory["bm25_index_cid"] == snapshot.index_cid
    assert inventory["bm25_index_digest_sha256"] == snapshot.index_digest_sha256

    receipt = validate_snapshot(snapshot)
    assert receipt["ok"] is True
    assert receipt["corpus_root_cid"] == materialization.corpus_root_cid
    assert receipt["index_cid"] == snapshot.index_cid
    assert receipt["document_count"] == len(snapshot.documents)


def test_content_address_stable_for_same_full_authority_recipe(
    bm25_mod, full_recipe, baseline
) -> None:
    first, inv1, _ = baseline
    second, inv2, _ = bm25_mod.build_full_authority_bm25_index(
        copy.deepcopy(full_recipe),
        require_full_authority=True,
        stage=False,
    )
    third, _, _ = bm25_mod.build_full_authority_bm25_index(
        require_full_authority=True,
        stage=False,
    )

    assert first.index_cid == second.index_cid == third.index_cid
    assert (
        first.index_digest_sha256
        == second.index_digest_sha256
        == third.index_digest_sha256
    )
    assert first.corpus_root_cid == second.corpus_root_cid == third.corpus_root_cid
    assert snapshots_are_byte_identical(first, second)
    assert inv1["bm25_bind"]["ok"] is True
    assert inv2["bm25_bind"]["ok"] is True


def test_expected_corpus_root_cid_pin(bm25_mod, full_recipe, baseline) -> None:
    first, _, _ = baseline
    ok, inv, _ = bm25_mod.build_full_authority_bm25_index(
        full_recipe,
        expected_corpus_root_cid=first.corpus_root_cid,
        require_full_authority=True,
        stage=False,
    )
    assert ok.index_cid == first.index_cid
    assert inv["bm25_bind"]["ok"] is True

    with pytest.raises(CorpusPinError):
        bm25_mod.build_full_authority_bm25_index(
            full_recipe,
            expected_corpus_root_cid=(
                "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
            ),
            require_full_authority=True,
            stage=False,
        )


def test_full_authority_families_present(baseline) -> None:
    snapshot, inventory, _ = baseline
    families = set(snapshot.manifest.counts.by_family)
    assert families.issuperset({"cfr", "mpep", "guidance"})
    assert sum(snapshot.manifest.counts.by_family.values()) == (
        snapshot.manifest.counts.document_count
    )
    assert inventory.get("full_authority_complete") is True


def test_every_bm25_document_joins_full_authority_corpus(
    mat_mod, full_recipe, baseline
) -> None:
    snapshot, _, _ = baseline
    materialization, _ = mat_mod.materialize_full_authority_corpus(
        full_recipe,
        require_full_authority=True,
    )
    corpus_ids = {d.record_id for d in materialization.documents}
    assert len(snapshot.documents) == len(materialization.documents)
    for doc in snapshot.documents:
        assert doc.record_id in corpus_ids
        assert doc.corpus_record_id in corpus_ids
        assert doc.source_cid.startswith("b")
        assert doc.document_cid.startswith("b")


# ---------------------------------------------------------------------------
# Hub bulk JSONL / parquet staging
# ---------------------------------------------------------------------------


def test_stage_writes_snapshot_and_hub_bulk_payloads(
    bm25_mod, full_recipe, baseline, tmp_path: Path
) -> None:
    first, _, _ = baseline
    out = tmp_path / "bm25-full-authority"
    staged, inventory, hub = bm25_mod.build_full_authority_bm25_index(
        full_recipe,
        stage=True,
        output_dir=out,
        require_full_authority=True,
        stage_hub_bulk=True,
    )

    assert staged.mode is BuildMode.STAGE
    assert staged.index_cid == first.index_cid
    assert staged.index_digest_sha256 == first.index_digest_sha256
    assert staged.corpus_root_cid == first.corpus_root_cid
    assert inventory["hub_bulk"]["ok"] is True
    assert hub is not None
    assert hub["ok"] is True
    assert hub["task_id"] == "PATLAW-188"
    assert hub["corpus_root_cid"] == first.corpus_root_cid
    assert hub["index_cid"] == first.index_cid
    assert hub["index_digest_sha256"] == first.index_digest_sha256
    assert hub["document_count"] == first.manifest.counts.document_count
    assert hub["hub_upload"] is False

    # Standard BM25 snapshot artifacts.
    for name in (
        MANIFEST_FILENAME,
        DOCUMENTS_FILENAME,
        TERMS_FILENAME,
        POSTINGS_FILENAME,
        RECEIPT_FILENAME,
        INDEX_ROOT_FILENAME,
    ):
        assert (out / name).is_file(), name

    # Hub bulk JSONL + parquet.
    for rel in (
        bm25_mod.HUB_DOCUMENTS_JSONL,
        bm25_mod.HUB_POSTINGS_JSONL,
        bm25_mod.HUB_TERMS_JSONL,
        bm25_mod.HUB_DOCUMENTS_PARQUET,
        bm25_mod.HUB_POSTINGS_PARQUET,
        bm25_mod.HUB_TERMS_PARQUET,
        bm25_mod.HUB_BULK_RECEIPT_FILENAME,
    ):
        path = out / rel
        assert path.is_file(), rel
        assert path.stat().st_size > 0, rel

    # Receipt paths match release packaging globs.
    assert RELEASE_DOCUMENTS_PATTERN == "data/bm25/documents/*.parquet"
    assert RELEASE_POSTINGS_PATTERN == "data/bm25/postings/*.parquet"
    assert (out / "data/bm25/documents/part-000000.parquet").is_file()
    assert (out / "data/bm25/postings/part-000000.parquet").is_file()

    loaded = load_bm25_snapshot(out)
    assert loaded.index_cid == first.index_cid
    assert len(loaded.documents) == len(first.documents)

    # JSONL bulk rows are parseable and count-bound.
    doc_lines = [
        ln
        for ln in (out / bm25_mod.HUB_DOCUMENTS_JSONL)
        .read_text(encoding="utf-8")
        .splitlines()
        if ln.strip()
    ]
    assert len(doc_lines) == first.manifest.counts.document_count
    first_doc = json.loads(doc_lines[0])
    for key in ("record_id", "corpus_record_id", "source_cid", "token_count"):
        assert key in first_doc

    post_lines = [
        ln
        for ln in (out / bm25_mod.HUB_POSTINGS_JSONL)
        .read_text(encoding="utf-8")
        .splitlines()
        if ln.strip()
    ]
    assert len(post_lines) == hub["release_posting_row_count"]
    assert len(post_lines) >= 1

    bulk_receipt = json.loads(
        (out / bm25_mod.HUB_BULK_RECEIPT_FILENAME).read_text(encoding="utf-8")
    )
    assert bulk_receipt["ok"] is True
    assert bulk_receipt["corpus_root_cid"] == first.corpus_root_cid
    assert set(bulk_receipt["artifacts"]) >= {
        "bm25_documents",
        "bm25_postings",
        "bm25_terms",
    }


def test_hub_parquet_round_trip_row_counts(
    bm25_mod, full_recipe, baseline, tmp_path: Path
) -> None:
    pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    first, _, _ = baseline
    out = tmp_path / "bm25-parquet"
    staged, _, hub = bm25_mod.build_full_authority_bm25_index(
        full_recipe,
        stage=True,
        output_dir=out,
        require_full_authority=True,
    )
    assert hub is not None

    docs_table = pq.read_table(out / bm25_mod.HUB_DOCUMENTS_PARQUET)
    posts_table = pq.read_table(out / bm25_mod.HUB_POSTINGS_PARQUET)
    terms_table = pq.read_table(out / bm25_mod.HUB_TERMS_PARQUET)

    assert docs_table.num_rows == first.manifest.counts.document_count
    assert posts_table.num_rows == hub["release_posting_row_count"]
    assert terms_table.num_rows == first.manifest.counts.term_count
    assert "record_id" in docs_table.column_names
    assert "term" in posts_table.column_names
    assert "document_id" in posts_table.column_names


def test_stage_hub_bulk_payloads_standalone(
    bm25_mod, baseline, tmp_path: Path
) -> None:
    snapshot, _, _ = baseline
    out = tmp_path / "hub-only"
    # Stage snapshot shell first so directory exists, then write bulk only.
    out.mkdir(parents=True)
    receipt = bm25_mod.stage_hub_bulk_payloads(snapshot, out)
    assert receipt["ok"] is True
    assert receipt["document_count"] == snapshot.manifest.counts.document_count
    assert (out / bm25_mod.HUB_DOCUMENTS_PARQUET).is_file()
    assert (out / bm25_mod.HUB_POSTINGS_JSONL).is_file()


def test_encode_rows_parquet_rejects_empty(bm25_mod) -> None:
    with pytest.raises(bm25_mod.HubBulkStagingError):
        bm25_mod.encode_rows_parquet([])


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_cli_full_authority_dry_run(bm25_mod, baseline) -> None:
    first, _, _ = baseline
    rc = bm25_mod.main(
        [
            "--full-authority",
            "--no-print-summary",
            "--print-receipt",
        ]
    )
    assert rc == 0


def test_cli_full_authority_stage(bm25_mod, baseline, tmp_path: Path) -> None:
    first, _, _ = baseline
    out = tmp_path / "cli-stage"
    rc = bm25_mod.main(
        [
            "--full-authority",
            "--stage",
            "--output-dir",
            str(out),
            "--no-print-summary",
        ]
    )
    assert rc == 0
    assert (out / MANIFEST_FILENAME).is_file()
    assert (out / bm25_mod.HUB_DOCUMENTS_PARQUET).is_file()
    assert (out / bm25_mod.HUB_POSTINGS_PARQUET).is_file()
    assert (out / bm25_mod.HUB_BULK_RECEIPT_FILENAME).is_file()

    loaded = load_bm25_snapshot(out)
    assert loaded.index_cid == first.index_cid
    assert loaded.corpus_root_cid == first.corpus_root_cid
    assert loaded.manifest.counts.document_count == first.manifest.counts.document_count


def test_cli_rejects_stage_without_output_dir(bm25_mod) -> None:
    with pytest.raises(SystemExit) as excinfo:
        bm25_mod.main(["--full-authority", "--stage"])
    assert excinfo.value.code == 2


def test_load_full_authority_recipe_offline(bm25_mod) -> None:
    recipe = bm25_mod.load_full_authority_recipe(assert_complete=True)
    assert recipe["full_authority"]["complete"] is True
    assert recipe["recipe_id"] == bm25_mod.FULL_AUTHORITY_RECIPE_ID
    assert recipe["counts"]["documents"] >= 1
    assert set(recipe["counts"]["by_family"]).issuperset(
        bm25_mod.FULL_AUTHORITY_FAMILIES
    )
