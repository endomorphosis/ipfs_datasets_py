"""Integration tests: full-authority public legal vector rebuild (PATLAW-189).

Acceptance:

* Vector document_count equals corpus document_count
* Model pin and corpus root are bound
* Bulk vector rows are staged for packaging
* Offline full-authority fixtures (PATLAW-186/187) are sufficient for CI
* Private / mixed inputs fail closed before embedding
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.embedding_runtime import (
    PINNED_DIMENSION,
    pinned_runtime_identity,
)
from ipfs_datasets_py.processors.domains.patent.index_snapshot_contracts import (
    IndexFamily,
    KNOWN_MODEL_PINS,
)
from ipfs_datasets_py.processors.domains.patent.public_legal_vector_builder import (
    DEFAULT_CREATED_UTC,
    DEFAULT_MODEL_PIN,
    EMBEDDING_RECEIPT_FILENAME,
    MANIFEST_FILENAME,
    SNAPSHOT_FILENAME,
    VECTORS_FILENAME,
    VECTOR_ROOT_FILENAME,
    BuildMode,
    PrivateTextRejectedError,
    load_manifest,
    validate_build,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
VECTOR_SCRIPT = (
    REPO_ROOT / "scripts" / "ops" / "legal_data" / "build_public_legal_vector_index.py"
)
MATERIALIZE_SCRIPT = (
    REPO_ROOT / "scripts" / "ops" / "legal_data" / "materialize_public_legal_corpus.py"
)
BUILD_SCRIPT = (
    REPO_ROOT / "scripts" / "ops" / "legal_data" / "build_public_legal_production_recipe.py"
)


def _load_module(path: Path, module_name: str):
    assert path.is_file(), f"missing script at {path}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass / imports can resolve cls.__module__.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def vec_mod():
    return _load_module(VECTOR_SCRIPT, "build_public_legal_vector_index_patlaw189")


@pytest.fixture(scope="module")
def mat_mod():
    return _load_module(MATERIALIZE_SCRIPT, "materialize_public_legal_corpus_patlaw189")


@pytest.fixture(scope="module")
def build_mod():
    return _load_module(BUILD_SCRIPT, "build_public_legal_production_recipe_patlaw189")


@pytest.fixture(scope="module")
def full_recipe(build_mod):
    return build_mod.build_full_authority_recipe(assert_complete=True)


@pytest.fixture(scope="module")
def baseline(vec_mod, full_recipe):
    result, materialization, receipt = vec_mod.build_full_authority_vectors(
        full_recipe,
        require_full_authority=True,
        created_utc=DEFAULT_CREATED_UTC,
    )
    return result, materialization, receipt


# ---------------------------------------------------------------------------
# Declared outputs / pins
# ---------------------------------------------------------------------------


def test_declared_outputs_exist() -> None:
    assert VECTOR_SCRIPT.is_file()
    assert MATERIALIZE_SCRIPT.is_file()
    assert BUILD_SCRIPT.is_file()


def test_module_pins(vec_mod) -> None:
    assert vec_mod.FULL_AUTHORITY_TASK_ID == "PATLAW-189"
    assert vec_mod.FULL_AUTHORITY_GOAL_ID == "PATLAW-G218"
    assert vec_mod.FULL_AUTHORITY_RECIPE_ID == (
        "patlaw-full-authority-public-legal-corpus"
    )
    assert tuple(vec_mod.FULL_AUTHORITY_FAMILIES) == ("cfr", "mpep", "guidance")
    assert DEFAULT_MODEL_PIN in KNOWN_MODEL_PINS
    assert DEFAULT_MODEL_PIN == vec_mod.DEFAULT_MODEL_PIN


# ---------------------------------------------------------------------------
# Acceptance: document_count parity
# ---------------------------------------------------------------------------


def test_vector_document_count_equals_corpus_document_count(
    baseline, full_recipe
) -> None:
    result, materialization, receipt = baseline
    corpus_count = materialization.manifest.counts.total_documents
    recipe_count = full_recipe["counts"]["documents"]

    assert result.manifest.document_count == corpus_count
    assert result.manifest.vector_count == corpus_count
    assert len(result.rows) == corpus_count
    assert corpus_count == recipe_count
    assert receipt["ok"] is True
    assert receipt["document_count"] == corpus_count
    assert receipt["corpus_document_count"] == corpus_count
    assert receipt["vector_count"] == corpus_count

    # Record-id sets are identical (sorted join).
    corpus_ids = sorted(d.record_id for d in materialization.documents)
    row_ids = sorted(r.record_id for r in result.rows)
    assert row_ids == corpus_ids


def test_assert_document_count_parity_helper(vec_mod, baseline, full_recipe) -> None:
    result, materialization, _ = baseline
    receipt = vec_mod.assert_vector_document_count_matches_corpus(
        result, materialization, recipe=full_recipe
    )
    assert receipt["ok"] is True
    assert receipt["document_count"] == len(result.rows)
    assert receipt["task_id"] == "PATLAW-189"

    # Detect mismatch when recipe inventory is wrong.
    broken = copy.deepcopy(full_recipe)
    broken["counts"]["documents"] = result.manifest.document_count + 99
    with pytest.raises(vec_mod.DocumentCountMismatchError) as excinfo:
        vec_mod.assert_vector_document_count_matches_corpus(
            result, materialization, recipe=broken
        )
    assert excinfo.value.code == "document_count_mismatch"


def test_full_authority_families_covered(baseline, full_recipe) -> None:
    result, materialization, receipt = baseline
    by_family = dict(materialization.manifest.counts.by_family)
    for family in ("cfr", "mpep", "guidance"):
        assert by_family.get(family, 0) >= 1
    assert by_family == full_recipe["counts"]["by_family"]
    assert receipt["by_family"] == by_family

    # Rows inherit family-shaped record_ids from full-authority corpus.
    families_seen: set[str] = set()
    for row in result.rows:
        rid = row.record_id
        if rid.startswith("cfr:37:"):
            families_seen.add("cfr")
        elif rid.startswith("mpep:section:"):
            families_seen.add("mpep")
        elif rid.startswith("guidance:pdf:"):
            families_seen.add("guidance")
    assert families_seen == {"cfr", "mpep", "guidance"}


# ---------------------------------------------------------------------------
# Acceptance: model pin + corpus root bound
# ---------------------------------------------------------------------------


def test_model_pin_and_corpus_root_bound(baseline) -> None:
    result, materialization, receipt = baseline
    manifest = result.manifest

    assert manifest.model_pin == DEFAULT_MODEL_PIN
    assert manifest.model_pin in KNOWN_MODEL_PINS
    assert manifest.corpus_root_cid == materialization.corpus_root_cid
    assert manifest.corpus_digest_sha256 == materialization.corpus_digest_sha256
    assert manifest.dimension == PINNED_DIMENSION
    assert manifest.partition == "public"
    assert IndexFamily.VECTOR.value in manifest.families

    # Contract snapshot identities.
    snap = result.snapshot
    assert snap.manifest.identities.model is not None
    assert snap.manifest.identities.model.model_pin == DEFAULT_MODEL_PIN
    assert snap.manifest.identities.corpus.corpus_cid == materialization.corpus_root_cid
    assert (
        snap.manifest.identities.corpus.corpus_digest
        == materialization.corpus_digest_sha256
    )
    assert list(snap.manifest.families) == [IndexFamily.VECTOR]

    assert receipt["model_pin"] == DEFAULT_MODEL_PIN
    assert receipt["corpus_root_cid"] == materialization.corpus_root_cid


def test_assert_pins_bound_helper(vec_mod, baseline) -> None:
    result, materialization, _ = baseline
    pin_receipt = vec_mod.assert_model_pin_and_corpus_root_bound(
        result, materialization
    )
    assert pin_receipt["ok"] is True
    assert pin_receipt["model_pin"] == DEFAULT_MODEL_PIN
    assert pin_receipt["corpus_root_cid"] == materialization.corpus_root_cid


def test_each_row_binds_model_pin_and_source_join(baseline) -> None:
    result, _, _ = baseline
    for row in result.rows:
        assert row.model_pin == DEFAULT_MODEL_PIN
        assert row.dimension == PINNED_DIMENSION
        assert row.source_cid
        assert row.source_version
        assert row.vector_digest
        assert len(row.vector) == PINNED_DIMENSION
        assert row.classification == "public_official"


def test_default_model_identity_matches_runtime(vec_mod) -> None:
    runtime = pinned_runtime_identity()
    assert DEFAULT_MODEL_PIN == vec_mod.DEFAULT_MODEL_PIN
    assert runtime.dimension == PINNED_DIMENSION


# ---------------------------------------------------------------------------
# Acceptance: bulk vector rows staged for packaging
# ---------------------------------------------------------------------------


def test_bulk_vector_rows_staged_for_packaging(
    vec_mod, full_recipe, baseline, tmp_path: Path
) -> None:
    dry, materialization, dry_receipt = baseline
    out = tmp_path / "fa-vector-index"
    staged, mat2, receipt = vec_mod.build_full_authority_vectors(
        full_recipe,
        stage=True,
        output_dir=out,
        require_full_authority=True,
        created_utc=DEFAULT_CREATED_UTC,
        include_vectors_in_stage=True,
    )

    assert staged.mode is BuildMode.STAGE
    assert staged.output_dir is not None
    assert Path(staged.output_dir) == out.resolve()
    assert receipt["bulk_vectors_staged"] is True
    assert receipt["staged"] is True

    # Content address stable across dry-run / stage.
    assert staged.index_root_cid == dry.index_root_cid
    assert staged.corpus_root_cid == materialization.corpus_root_cid
    assert mat2.corpus_root_cid == materialization.corpus_root_cid
    assert staged.manifest.document_count == dry.manifest.document_count

    for name in (
        MANIFEST_FILENAME,
        VECTORS_FILENAME,
        VECTOR_ROOT_FILENAME,
        SNAPSHOT_FILENAME,
        EMBEDDING_RECEIPT_FILENAME,
    ):
        assert (out / name).is_file(), name

    # Bulk vectors.jsonl: one row per corpus document with float vectors.
    lines = [
        line
        for line in (out / VECTORS_FILENAME).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == staged.manifest.document_count
    assert len(lines) == materialization.manifest.counts.total_documents

    parsed_rows = [json.loads(line) for line in lines]
    for row in parsed_rows:
        assert row["model_pin"] == DEFAULT_MODEL_PIN
        assert row["dimension"] == PINNED_DIMENSION
        assert isinstance(row.get("vector"), list)
        assert len(row["vector"]) == PINNED_DIMENSION
        assert row.get("vector_digest")
        assert row.get("record_id")
        assert row.get("document_id")

    # vector-root pin binds model + corpus + counts for packaging consumers.
    root_payload = json.loads((out / VECTOR_ROOT_FILENAME).read_text(encoding="utf-8"))
    assert root_payload["model_pin"] == DEFAULT_MODEL_PIN
    assert root_payload["corpus_root_cid"] == staged.corpus_root_cid
    assert root_payload["index_root_cid"] == staged.index_root_cid
    assert root_payload["document_count"] == staged.manifest.document_count
    assert root_payload["dimension"] == PINNED_DIMENSION

    loaded = load_manifest(out / MANIFEST_FILENAME)
    assert loaded.index_root_cid == staged.index_root_cid
    assert loaded.model_pin == DEFAULT_MODEL_PIN
    assert loaded.document_count == dry.manifest.document_count
    assert dry_receipt["ok"] is True


# ---------------------------------------------------------------------------
# Rebuild stability under fixed pins
# ---------------------------------------------------------------------------


def test_rebuild_stable_under_fixed_pins(vec_mod, full_recipe, baseline) -> None:
    first, materialization, _ = baseline
    second, mat2, receipt2 = vec_mod.build_full_authority_vectors(
        copy.deepcopy(full_recipe),
        require_full_authority=True,
        created_utc=DEFAULT_CREATED_UTC,
    )
    third, _, _ = vec_mod.build_full_authority_vectors(
        full_recipe,
        require_full_authority=True,
        created_utc=DEFAULT_CREATED_UTC,
    )

    assert first.index_root_cid == second.index_root_cid == third.index_root_cid
    assert (
        first.index_digest_sha256
        == second.index_digest_sha256
        == third.index_digest_sha256
    )
    assert first.model_pin == second.model_pin == DEFAULT_MODEL_PIN
    assert (
        first.corpus_root_cid
        == second.corpus_root_cid
        == third.corpus_root_cid
        == materialization.corpus_root_cid
        == mat2.corpus_root_cid
    )
    assert receipt2["ok"] is True

    stable = vec_mod.validate_full_authority_vector_stable(
        first, materialization, created_utc=DEFAULT_CREATED_UTC
    )
    assert stable["ok"] is True
    assert stable["rebuild_stable"] is True
    assert stable["rebuild_index_root_cid"] == first.index_root_cid

    base = validate_build(first)
    assert base["ok"] is True
    assert base["document_count"] == first.manifest.document_count


def test_document_order_does_not_affect_index_cid(
    vec_mod, full_recipe, baseline
) -> None:
    first, _, _ = baseline
    shuffled = copy.deepcopy(full_recipe)
    shuffled["documents"] = list(reversed(shuffled["documents"]))
    by_family: dict[str, int] = {}
    for d in shuffled["documents"]:
        fam = d["family"]
        by_family[fam] = by_family.get(fam, 0) + 1
    shuffled["counts"]["by_family"] = dict(sorted(by_family.items()))

    second, _, inv = vec_mod.build_full_authority_vectors(
        shuffled, require_full_authority=True, created_utc=DEFAULT_CREATED_UTC
    )
    assert second.index_root_cid == first.index_root_cid
    assert second.corpus_root_cid == first.corpus_root_cid
    assert [r.record_id for r in second.rows] == sorted(
        r.record_id for r in second.rows
    )
    assert inv["ok"] is True


# ---------------------------------------------------------------------------
# Private / incomplete fail closed
# ---------------------------------------------------------------------------


def test_private_classification_fails_closed(vec_mod, full_recipe) -> None:
    private = copy.deepcopy(full_recipe)
    private["documents"][0]["classification"] = "confidential_application"
    with pytest.raises((PrivateTextRejectedError, Exception)):
        vec_mod.build_full_authority_vectors(
            private, require_full_authority=True, created_utc=DEFAULT_CREATED_UTC
        )


@pytest.mark.parametrize(
    "classification",
    [
        "privileged_work_product",
        "restricted_export_review",
        "credential_or_payment",
        "unknown",
        "mixed",
    ],
)
def test_disallowed_classifications_fail_closed(
    vec_mod, full_recipe, classification: str
) -> None:
    bad = copy.deepcopy(full_recipe)
    bad["documents"][0]["classification"] = classification
    with pytest.raises(Exception):
        vec_mod.build_full_authority_vectors(
            bad, require_full_authority=True, created_utc=DEFAULT_CREATED_UTC
        )


def test_incomplete_full_authority_recipe_fails(vec_mod, full_recipe) -> None:
    broken = copy.deepcopy(full_recipe)
    broken["documents"] = [
        d for d in broken["documents"] if d["family"] != "guidance"
    ]
    broken["counts"]["by_family"] = {
        k: v for k, v in broken["counts"]["by_family"].items() if k != "guidance"
    }
    broken["counts"]["documents"] = len(broken["documents"])
    broken["counts"]["full_authority"]["guidance_pdfs"] = 0
    broken["counts"]["full_authority"]["guidance_documents"] = 0
    broken["full_authority"]["sources"]["uspto_guidance_pdfs"][
        "documents_present"
    ] = 0
    with pytest.raises(Exception) as excinfo:
        vec_mod.build_full_authority_vectors(
            broken, require_full_authority=True, created_utc=DEFAULT_CREATED_UTC
        )
    msg = str(excinfo.value).lower()
    assert (
        "full" in msg
        or "guidance" in msg
        or "authority" in msg
        or "incomplete" in msg
        or "mismatch" in msg
    )


# ---------------------------------------------------------------------------
# Load path + CLI
# ---------------------------------------------------------------------------


def test_load_full_authority_recipe_offline(vec_mod) -> None:
    recipe = vec_mod.load_full_authority_recipe(assert_complete=True)
    assert recipe["full_authority"]["complete"] is True
    assert recipe["recipe_id"] == vec_mod.FULL_AUTHORITY_RECIPE_ID
    assert set(recipe["counts"]["by_family"]).issuperset(
        vec_mod.FULL_AUTHORITY_FAMILIES
    )


def test_build_from_materialization_path(
    vec_mod, mat_mod, full_recipe, baseline
) -> None:
    first, _, _ = baseline
    materialization, inv = mat_mod.materialize_full_authority_corpus(
        full_recipe, require_full_authority=True
    )
    assert inv["ok"] is True

    result, mat2, receipt = vec_mod.build_full_authority_vectors(
        full_recipe,
        materialization=materialization,
        require_full_authority=True,
        created_utc=DEFAULT_CREATED_UTC,
    )
    assert result.index_root_cid == first.index_root_cid
    assert result.corpus_root_cid == materialization.corpus_root_cid
    assert mat2.corpus_root_cid == materialization.corpus_root_cid
    assert receipt["document_count"] == materialization.manifest.counts.total_documents


def test_cli_full_authority_dry_run(vec_mod) -> None:
    rc = vec_mod.main(["--full-authority", "--no-print-summary"])
    assert rc == 0


def test_cli_full_authority_stage_and_prove_stable(
    vec_mod, tmp_path: Path
) -> None:
    out = tmp_path / "staged-fa-vectors"
    rc = vec_mod.main(
        [
            "--full-authority",
            "--stage",
            "--output-dir",
            str(out),
            "--prove-stable",
            "--no-print-summary",
        ]
    )
    assert rc == 0
    assert (out / VECTORS_FILENAME).is_file()
    assert (out / MANIFEST_FILENAME).is_file()
    assert (out / VECTOR_ROOT_FILENAME).is_file()

    lines = [
        line
        for line in (out / VECTORS_FILENAME).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    manifest = load_manifest(out / MANIFEST_FILENAME)
    assert len(lines) == manifest.document_count
    assert manifest.model_pin == DEFAULT_MODEL_PIN
    assert manifest.document_count == manifest.vector_count
    # Bulk payload must include vectors for packaging.
    sample = json.loads(lines[0])
    assert isinstance(sample.get("vector"), list)
    assert len(sample["vector"]) == PINNED_DIMENSION


def test_cli_write_full_authority_recipe(vec_mod, tmp_path: Path) -> None:
    recipe_path = tmp_path / "fa_recipe.json"
    rc = vec_mod.main(
        [
            "--full-authority",
            "--write-full-authority-recipe",
            str(recipe_path),
        ]
    )
    assert rc == 0
    assert recipe_path.is_file()
    payload = json.loads(recipe_path.read_text(encoding="utf-8"))
    assert payload["full_authority"]["complete"] is True
    assert payload["recipe_id"] == "patlaw-full-authority-public-legal-corpus"


def test_cli_list_model_pin(vec_mod, capsys) -> None:
    rc = vec_mod.main(["--list-model-pin"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out == DEFAULT_MODEL_PIN


def test_cli_from_corpus_dir_require_full_authority(
    vec_mod, mat_mod, full_recipe, tmp_path: Path
) -> None:
    corpus_dir = tmp_path / "fa-corpus"
    staged_corpus, inv = mat_mod.materialize_full_authority_corpus(
        full_recipe,
        stage=True,
        output_dir=corpus_dir,
        require_full_authority=True,
    )
    assert inv["ok"] is True
    assert staged_corpus.mode.value == "stage"

    vector_dir = tmp_path / "fa-vectors-from-corpus"
    rc = vec_mod.main(
        [
            "--from-corpus-dir",
            str(corpus_dir),
            "--require-full-authority",
            "--stage",
            "--output-dir",
            str(vector_dir),
            "--no-print-summary",
        ]
    )
    assert rc == 0
    manifest = load_manifest(vector_dir / MANIFEST_FILENAME)
    assert manifest.document_count == staged_corpus.manifest.counts.total_documents
    assert manifest.corpus_root_cid == staged_corpus.corpus_root_cid
    assert manifest.model_pin == DEFAULT_MODEL_PIN
    lines = [
        line
        for line in (vector_dir / VECTORS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(lines) == manifest.document_count
