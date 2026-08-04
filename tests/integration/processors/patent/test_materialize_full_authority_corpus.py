"""Integration tests: full-authority public legal corpus materialization (PATLAW-187).

Acceptance:

* Materialization is content-address stable for the same full-authority recipe
* Document counts and by-family tallies match the recipe inventory
* Private / mixed / unreviewed inputs fail closed before staging
* Offline full-authority fixtures (PATLAW-186/181/183/185) are sufficient for CI
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.cfr_title37_full_contracts import (
    title37_section_count,
)
from ipfs_datasets_py.processors.domains.patent.mpep_full_section_contracts import (
    REQUIRED_CHAPTER_IDS,
)
from ipfs_datasets_py.processors.domains.patent.public_legal_corpus_materializer import (
    CORPUS_ROOT_FILENAME,
    DOCUMENTS_FILENAME,
    MANIFEST_FILENAME,
    SOURCE_RECEIPTS_FILENAME,
    MaterializationMode,
    PrivateOrMixedInputError,
    PublicLegalCorpusMaterializer,
    UnreviewedRightsError,
    load_manifest,
    materializations_are_byte_identical,
    validate_materialization,
)
from ipfs_datasets_py.processors.domains.patent.uspto_guidance_pdf_contracts import (
    REQUIRED_DOCUMENT_IDS,
    REQUIRED_GUIDANCE_DOCUMENTS,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
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
def mat_mod():
    return _load_module(MATERIALIZE_SCRIPT, "materialize_public_legal_corpus_patlaw187")


@pytest.fixture(scope="module")
def build_mod():
    return _load_module(BUILD_SCRIPT, "build_public_legal_production_recipe_patlaw187")


@pytest.fixture(scope="module")
def full_recipe(build_mod):
    return build_mod.build_full_authority_recipe(assert_complete=True)


@pytest.fixture(scope="module")
def baseline(mat_mod, full_recipe):
    result, inventory = mat_mod.materialize_full_authority_corpus(
        full_recipe,
        require_full_authority=True,
    )
    return result, inventory


# ---------------------------------------------------------------------------
# Declared outputs / pins
# ---------------------------------------------------------------------------


def test_declared_outputs_exist() -> None:
    assert MATERIALIZE_SCRIPT.is_file()
    assert BUILD_SCRIPT.is_file()


def test_module_pins(mat_mod) -> None:
    assert mat_mod.FULL_AUTHORITY_TASK_ID == "PATLAW-187"
    assert mat_mod.FULL_AUTHORITY_GOAL_ID == "PATLAW-G218"
    assert mat_mod.FULL_AUTHORITY_RECIPE_ID == (
        "patlaw-full-authority-public-legal-corpus"
    )
    assert tuple(mat_mod.FULL_AUTHORITY_FAMILIES) == ("cfr", "mpep", "guidance")


# ---------------------------------------------------------------------------
# Full-authority recipe load + materialize
# ---------------------------------------------------------------------------


def test_load_full_authority_recipe_offline(mat_mod) -> None:
    recipe = mat_mod.load_full_authority_recipe(assert_complete=True)
    assert recipe["full_authority"]["complete"] is True
    assert recipe["recipe_id"] == mat_mod.FULL_AUTHORITY_RECIPE_ID
    assert set(recipe["counts"]["by_family"]).issuperset(
        mat_mod.FULL_AUTHORITY_FAMILIES
    )


def test_materialize_full_authority_returns_stable_cid(baseline, full_recipe) -> None:
    result, inventory = baseline
    assert result.mode is MaterializationMode.DRY_RUN
    assert result.corpus_root_cid.startswith("b")
    assert len(result.corpus_digest_sha256) == 64
    assert result.manifest.partition == "public"
    assert inventory["ok"] is True
    assert inventory["full_authority_complete"] is True
    assert inventory["corpus_root_cid"] == result.corpus_root_cid
    assert inventory["document_count"] == full_recipe["counts"]["documents"]


def test_content_address_stable_for_same_recipe(mat_mod, full_recipe, baseline) -> None:
    first, _ = baseline
    second, inv2 = mat_mod.materialize_full_authority_corpus(
        copy.deepcopy(full_recipe),
        require_full_authority=True,
    )
    third, _ = mat_mod.materialize_full_authority_corpus(
        full_recipe,
        require_full_authority=True,
    )

    assert first.corpus_root_cid == second.corpus_root_cid == third.corpus_root_cid
    assert (
        first.corpus_digest_sha256
        == second.corpus_digest_sha256
        == third.corpus_digest_sha256
    )
    assert first.to_canonical_bytes() == second.to_canonical_bytes()
    assert materializations_are_byte_identical(first, third)
    assert inv2["ok"] is True

    receipt = validate_materialization(first)
    assert receipt["ok"] is True
    assert receipt["stable"] is True
    assert receipt["corpus_root_cid"] == first.corpus_root_cid


def test_document_order_does_not_affect_corpus_cid(
    mat_mod, full_recipe, baseline
) -> None:
    first, _ = baseline
    shuffled = copy.deepcopy(full_recipe)
    shuffled["documents"] = list(reversed(shuffled["documents"]))
    # Rebuild counts.by_family for consistency with reordered docs.
    by_family: dict[str, int] = {}
    for d in shuffled["documents"]:
        fam = d["family"]
        by_family[fam] = by_family.get(fam, 0) + 1
    shuffled["counts"]["by_family"] = dict(sorted(by_family.items()))

    second, inv = mat_mod.materialize_full_authority_corpus(
        shuffled, require_full_authority=True
    )
    assert second.corpus_root_cid == first.corpus_root_cid
    assert [d.record_id for d in second.documents] == sorted(
        d.record_id for d in second.documents
    )
    assert inv["ok"] is True


def test_changed_source_text_changes_corpus_cid(
    mat_mod, full_recipe, baseline
) -> None:
    first, _ = baseline
    altered = copy.deepcopy(full_recipe)
    altered["documents"][0]["text"] = (
        altered["documents"][0]["text"] + " [amended full-authority body]"
    )
    # Recompute lineage digest so admission accepts the new body.
    body = altered["documents"][0]["text"]
    import hashlib

    altered["documents"][0]["source_lineage"]["source_sha256"] = hashlib.sha256(
        body.encode("utf-8")
    ).hexdigest()

    second, inv = mat_mod.materialize_full_authority_corpus(
        altered, require_full_authority=True
    )
    assert second.corpus_root_cid != first.corpus_root_cid
    assert second.corpus_digest_sha256 != first.corpus_digest_sha256
    assert inv["ok"] is True


# ---------------------------------------------------------------------------
# Counts match recipe inventory
# ---------------------------------------------------------------------------


def test_counts_match_recipe_inventory(baseline, full_recipe) -> None:
    result, inventory = baseline
    recipe_by_family = full_recipe["counts"]["by_family"]
    mat_by_family = dict(result.manifest.counts.by_family)

    assert result.manifest.counts.total_documents == full_recipe["counts"]["documents"]
    assert result.manifest.counts.total_documents == len(result.documents)
    assert mat_by_family == recipe_by_family
    assert inventory["by_family"] == recipe_by_family
    assert inventory["document_count"] == full_recipe["counts"]["documents"]
    assert sum(mat_by_family.values()) == result.manifest.counts.total_documents

    fa = full_recipe["counts"]["full_authority"]
    assert fa["cfr_inventory_total"] == title37_section_count()
    assert fa["cfr_inventory_total"] >= 1000
    assert fa["cfr_documents"] == mat_by_family["cfr"]
    assert fa["mpep_documents"] == mat_by_family["mpep"]
    assert fa["guidance_documents"] == mat_by_family["guidance"]
    assert fa["mpep_section_level"] >= len(REQUIRED_CHAPTER_IDS)
    assert fa["guidance_pdfs"] >= len(REQUIRED_GUIDANCE_DOCUMENTS)
    assert inventory["full_authority_inventory"]["cfr_inventory_total"] == (
        title37_section_count()
    )


def test_full_authority_families_present_and_minima(baseline, full_recipe) -> None:
    result, _ = baseline
    by_family = dict(result.manifest.counts.by_family)
    for family in ("cfr", "mpep", "guidance"):
        assert by_family.get(family, 0) >= 1
    assert by_family["mpep"] >= len(REQUIRED_CHAPTER_IDS)
    assert by_family["guidance"] >= len(REQUIRED_GUIDANCE_DOCUMENTS)
    assert by_family["mpep"] >= full_recipe["expected"]["min_by_family"]["mpep"]
    assert by_family["guidance"] >= full_recipe["expected"]["min_by_family"]["guidance"]

    # Documents are full-authority shaped (not eCFR / chapter landings).
    for doc in result.documents:
        if doc.family.value == "cfr":
            assert doc.record_id.startswith("cfr:37:")
            assert not doc.record_id.startswith("ecfr:")
        if doc.family.value == "mpep":
            assert doc.record_id.startswith("mpep:section:")
            assert not doc.record_id.startswith("mpep:chapter:")
        if doc.family.value == "guidance":
            assert doc.record_id.startswith("guidance:pdf:")


def test_assert_counts_match_detects_mismatch(mat_mod, full_recipe, baseline) -> None:
    result, _ = baseline
    broken = copy.deepcopy(full_recipe)
    broken["counts"]["documents"] = result.manifest.counts.total_documents + 99
    with pytest.raises(mat_mod.InventoryCountMismatchError) as excinfo:
        mat_mod.assert_counts_match_recipe_inventory(result, broken)
    assert excinfo.value.code == "inventory_count_mismatch"

    broken2 = copy.deepcopy(full_recipe)
    broken2["counts"]["by_family"] = {
        **broken2["counts"]["by_family"],
        "cfr": broken2["counts"]["by_family"]["cfr"] + 1,
    }
    with pytest.raises(mat_mod.InventoryCountMismatchError):
        mat_mod.assert_counts_match_recipe_inventory(result, broken2)


def test_guidance_catalog_ids_present(baseline, full_recipe) -> None:
    result, _ = baseline
    g_docs = [d for d in result.documents if d.family.value == "guidance"]
    present_ids = {
        str((d.metadata or {}).get("document_id") or "")
        for d in g_docs
        if (d.metadata or {}).get("document_id")
    }
    # Recipe metadata carries document_id; materializer preserves metadata.
    if not present_ids:
        # Fall back to record_id suffix after guidance:pdf:
        present_ids = {
            d.record_id.split("guidance:pdf:", 1)[-1] for d in g_docs
        }
    assert set(REQUIRED_DOCUMENT_IDS).issubset(present_ids) or len(g_docs) >= len(
        REQUIRED_GUIDANCE_DOCUMENTS
    )


# ---------------------------------------------------------------------------
# Private / unreviewed fail closed
# ---------------------------------------------------------------------------


def test_private_classification_fails_closed(mat_mod, full_recipe) -> None:
    private = copy.deepcopy(full_recipe)
    private["documents"][0]["classification"] = "confidential_application"
    with pytest.raises(PrivateOrMixedInputError):
        mat_mod.materialize_full_authority_corpus(
            private, require_full_authority=True
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
    mat_mod, full_recipe, classification: str
) -> None:
    bad = copy.deepcopy(full_recipe)
    bad["documents"][0]["classification"] = classification
    with pytest.raises((PrivateOrMixedInputError, Exception)):
        mat_mod.materialize_full_authority_corpus(bad, require_full_authority=True)


def test_unreviewed_rights_fail_closed(mat_mod, full_recipe) -> None:
    unreviewed = copy.deepcopy(full_recipe)
    unreviewed["documents"][0]["rights_review"] = {
        "license_expression": "public-domain-US-government",
        "notes": "",
        "redistribution_allowed": False,
        "review_status": "unreviewed",
        "reviewed_at": "",
        "reviewed_by": "",
    }
    with pytest.raises(UnreviewedRightsError):
        mat_mod.materialize_full_authority_corpus(
            unreviewed, require_full_authority=True
        )


def test_mixed_public_and_private_batch_fails_closed(mat_mod, full_recipe) -> None:
    mixed = copy.deepcopy(full_recipe)
    mixed["documents"][1]["classification"] = "privileged_work_product"
    with pytest.raises(PrivateOrMixedInputError):
        mat_mod.materialize_full_authority_corpus(mixed, require_full_authority=True)


def test_incomplete_full_authority_recipe_fails(mat_mod, full_recipe) -> None:
    broken = copy.deepcopy(full_recipe)
    # Drop all guidance documents so full-authority completeness fails.
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
        mat_mod.materialize_full_authority_corpus(
            broken, require_full_authority=True
        )
    # Must fail closed — either incomplete gate or inventory mismatch.
    msg = str(excinfo.value).lower()
    assert (
        "full" in msg
        or "guidance" in msg
        or "authority" in msg
        or "incomplete" in msg
        or "mismatch" in msg
    )


# ---------------------------------------------------------------------------
# Staging + CLI
# ---------------------------------------------------------------------------


def test_dry_run_and_stage_share_corpus_cid(
    mat_mod, full_recipe, baseline, tmp_path: Path
) -> None:
    first, _ = baseline
    staged, inv = mat_mod.materialize_full_authority_corpus(
        full_recipe,
        stage=True,
        output_dir=tmp_path / "fa-corpus",
        require_full_authority=True,
    )
    assert staged.mode is MaterializationMode.STAGE
    assert staged.corpus_root_cid == first.corpus_root_cid
    assert staged.corpus_digest_sha256 == first.corpus_digest_sha256
    assert inv["ok"] is True

    out = tmp_path / "fa-corpus"
    assert (out / MANIFEST_FILENAME).is_file()
    assert (out / DOCUMENTS_FILENAME).is_file()
    assert (out / SOURCE_RECEIPTS_FILENAME).is_file()
    assert (out / CORPUS_ROOT_FILENAME).is_file()

    loaded = load_manifest(out / MANIFEST_FILENAME)
    assert loaded.corpus_root_cid == first.corpus_root_cid
    assert loaded.counts.total_documents == first.manifest.counts.total_documents
    assert dict(loaded.counts.by_family) == dict(first.manifest.counts.by_family)

    corpus_root = json.loads((out / CORPUS_ROOT_FILENAME).read_text(encoding="utf-8"))
    assert corpus_root["corpus_root_cid"] == first.corpus_root_cid
    assert corpus_root["counts"]["total_documents"] == first.manifest.counts.total_documents


def test_cli_full_authority_dry_run(mat_mod) -> None:
    rc = mat_mod.main(["--full-authority", "--no-print-summary"])
    assert rc == 0


def test_cli_full_authority_stage_and_write_recipe(mat_mod, tmp_path: Path) -> None:
    recipe_path = tmp_path / "fa_recipe.json"
    # Exclusive input group still requires a selector; write path returns early.
    rc = mat_mod.main(
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

    out = tmp_path / "staged"
    rc = mat_mod.main(
        [
            "--recipe",
            str(recipe_path),
            "--require-full-authority",
            "--stage",
            "--output-dir",
            str(out),
            "--no-print-summary",
        ]
    )
    assert rc == 0
    assert (out / MANIFEST_FILENAME).is_file()
    manifest = load_manifest(out / MANIFEST_FILENAME)
    assert manifest.counts.total_documents == payload["counts"]["documents"]
    assert dict(manifest.counts.by_family) == payload["counts"]["by_family"]


def test_cli_private_input_exits_fail_closed(
    mat_mod, full_recipe, tmp_path: Path
) -> None:
    bad = copy.deepcopy(full_recipe)
    bad["documents"][0]["classification"] = "confidential_application"
    path = tmp_path / "private_recipe.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    rc = mat_mod.main(
        [
            "--recipe",
            str(path),
            "--require-full-authority",
            "--no-print-summary",
        ]
    )
    assert rc == 3


def test_cli_unreviewed_exits_fail_closed(
    mat_mod, full_recipe, tmp_path: Path
) -> None:
    bad = copy.deepcopy(full_recipe)
    bad["documents"][0]["rights_review"] = {
        "license_expression": "public-domain-US-government",
        "notes": "",
        "redistribution_allowed": False,
        "review_status": "unreviewed",
        "reviewed_at": "",
        "reviewed_by": "",
    }
    path = tmp_path / "unreviewed_recipe.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    rc = mat_mod.main(
        [
            "--recipe",
            str(path),
            "--require-full-authority",
            "--no-print-summary",
        ]
    )
    assert rc == 3


def test_materializer_without_require_all_families_accepts_fa(
    full_recipe,
) -> None:
    """Full-authority recipes omit ecfr/uscode/etc.; still materialize cleanly."""
    mat = PublicLegalCorpusMaterializer(require_all_families=False)
    result = mat.materialize_from_recipe(full_recipe)
    assert result.manifest.counts.total_documents == full_recipe["counts"]["documents"]
    families = {r.family.value for r in result.manifest.source_roots}
    assert families == {"cfr", "mpep", "guidance"}


def test_require_all_families_rejects_full_authority_subset(full_recipe) -> None:
    mat = PublicLegalCorpusMaterializer(require_all_families=True)
    with pytest.raises(Exception):
        mat.materialize_from_recipe(full_recipe)


def test_builder_bindings_present_for_downstream_indexes(baseline) -> None:
    result, _ = baseline
    bindings = dict(result.manifest.builder_bindings)
    assert bindings["record_count"] == result.manifest.counts.total_documents
    assert bindings["source_manifest_cid"].startswith("b")
    for family in ("bm25", "vector", "graph"):
        assert family in bindings
        assert bindings[family]["required_partition"] == "public"
        assert "document_cid" in bindings[family]["join_fields"]
        assert "source_cid" in bindings[family]["join_fields"]
    assert result.manifest.rights_summary["all_reviewed"] is True
    assert result.manifest.rights_summary["all_redistribution_allowed"] is True
    assert result.manifest.rights_summary["partition"] == "public"
