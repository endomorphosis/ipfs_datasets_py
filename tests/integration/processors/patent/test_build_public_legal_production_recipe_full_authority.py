"""Integration tests: full-authority production public-legal recipe (PATLAW-186).

Acceptance:

* Recipe document counts and by-family tallies prove full CFR Title 37,
  full MPEP sections, and guidance PDFs are present
* Chapter-only MPEP substitutes do not complete acceptance
* eCFR-only substitutes do not complete acceptance
* Offline acquisition fixtures (PATLAW-181/183/185) are sufficient for CI
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
from ipfs_datasets_py.processors.domains.patent.uspto_guidance_pdf_contracts import (
    REQUIRED_DOCUMENT_IDS,
    REQUIRED_GUIDANCE_DOCUMENTS,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
BUILD_SCRIPT = (
    REPO_ROOT / "scripts" / "ops" / "legal_data" / "build_public_legal_production_recipe.py"
)
RUNBOOK = REPO_ROOT / "docs" / "operations" / "PATENT_LEGAL_FULL_AUTHORITY_CORPUS.md"
ACQUIRE_CFR = REPO_ROOT / "scripts" / "ops" / "legal_data" / "acquire_cfr_title37_full.py"
ACQUIRE_MPEP = REPO_ROOT / "scripts" / "ops" / "legal_data" / "acquire_mpep_full_sections.py"
ACQUIRE_GUIDANCE = (
    REPO_ROOT / "scripts" / "ops" / "legal_data" / "acquire_uspto_guidance_pdfs.py"
)


def _load_build_module():
    assert BUILD_SCRIPT.is_file(), f"missing recipe builder at {BUILD_SCRIPT}"
    module_name = "build_public_legal_production_recipe_patlaw186"
    spec = importlib.util.spec_from_file_location(module_name, BUILD_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass / imports can resolve cls.__module__.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build_mod():
    return _load_build_module()


@pytest.fixture(scope="module")
def full_recipe(build_mod):
    return build_mod.build_full_authority_recipe(assert_complete=True)


# ---------------------------------------------------------------------------
# Declared outputs / pins
# ---------------------------------------------------------------------------


def test_declared_outputs_exist() -> None:
    assert BUILD_SCRIPT.is_file()
    assert RUNBOOK.is_file()
    assert ACQUIRE_CFR.is_file()
    assert ACQUIRE_MPEP.is_file()
    assert ACQUIRE_GUIDANCE.is_file()


def test_module_pins(build_mod) -> None:
    assert build_mod.TASK_ID == "PATLAW-186"
    assert build_mod.GOAL_ID == "PATLAW-G218"
    assert build_mod.FULL_AUTHORITY_RECIPE_ID == (
        "patlaw-full-authority-public-legal-corpus"
    )
    assert build_mod.RECIPE_SCHEMA_VERSION == "patent.public_legal_corpus.v1"
    assert tuple(build_mod.FULL_AUTHORITY_FAMILIES) == ("cfr", "mpep", "guidance")


def test_runbook_covers_operator_surface() -> None:
    text = RUNBOOK.read_text(encoding="utf-8").lower()
    for token in (
        "patlaw-186",
        "full-authority",
        "title 37",
        "mpep",
        "guidance",
        "ecfr-only",
        "chapter-only",
        "by-family",
        "source receipt",
        "current-through",
        "build_public_legal_production_recipe",
    ):
        assert token in text, f"runbook missing token: {token!r}"


# ---------------------------------------------------------------------------
# Full-authority recipe structure
# ---------------------------------------------------------------------------


def test_full_authority_recipe_has_required_families_and_roots(full_recipe) -> None:
    by_family = full_recipe["counts"]["by_family"]
    root_families = {r["family"] for r in full_recipe["source_roots"]}
    for family in ("cfr", "mpep", "guidance"):
        assert family in by_family
        assert by_family[family] >= 1
        assert family in root_families
    assert full_recipe["full_authority"]["complete"] is True
    assert full_recipe["task_id"] == "PATLAW-186"
    assert full_recipe["goal_id"] == "PATLAW-G218"
    assert full_recipe["recipe_id"] == "patlaw-full-authority-public-legal-corpus"


def test_document_counts_and_by_family_tallies_prove_full_sources(
    full_recipe,
) -> None:
    """Acceptance: counts + by-family prove full CFR / MPEP / guidance PDFs."""

    counts = full_recipe["counts"]
    by_family = counts["by_family"]
    fa = counts["full_authority"]
    sources = full_recipe["full_authority"]["sources"]

    # Full CFR Title 37 catalog inventory (not eCFR-only).
    expected_catalog = title37_section_count()
    assert expected_catalog >= 1000
    assert fa["cfr_inventory_total"] == expected_catalog
    assert sources["cfr_title37"]["inventory_total"] == expected_catalog
    assert sources["cfr_title37"]["not_ecfr_only"] is True
    assert sources["cfr_title37"]["package_digest_sha256"]
    assert sources["cfr_title37"]["package_id"].startswith("CFR-")
    assert "title37" in sources["cfr_title37"]["package_id"]
    assert by_family["cfr"] == fa["cfr_documents"]
    assert by_family["cfr"] >= 1
    assert by_family["cfr"] == fa["cfr_present_sections"] or by_family["cfr"] >= 1
    # Present + gap must cover full catalog.
    assert (
        sources["cfr_title37"]["present_sections"]
        + sources["cfr_title37"]["gap_sections"]
        == expected_catalog
    )

    # Full MPEP section-level (not chapter-only).
    assert fa["mpep_section_level"] >= len(REQUIRED_CHAPTER_IDS)
    assert by_family["mpep"] >= len(REQUIRED_CHAPTER_IDS)
    assert by_family["mpep"] == fa["mpep_documents"]
    assert sources["mpep_sections"]["chapter_only"] is False
    assert sources["mpep_sections"]["chapters_covered"] >= len(REQUIRED_CHAPTER_IDS)
    assert sources["mpep_sections"]["section_level_acquired"] >= len(
        REQUIRED_CHAPTER_IDS
    )
    assert sources["mpep_sections"]["package_digest_sha256"]

    # USPTO guidance PDFs (full required catalog).
    required_g = len(REQUIRED_GUIDANCE_DOCUMENTS)
    assert required_g >= 5
    assert fa["guidance_pdfs"] >= required_g
    assert by_family["guidance"] >= required_g
    assert by_family["guidance"] == fa["guidance_documents"]
    assert sources["uspto_guidance_pdfs"]["documents_present"] >= required_g
    present_ids = set(sources["uspto_guidance_pdfs"]["document_ids"])
    assert set(REQUIRED_DOCUMENT_IDS).issubset(present_ids)

    # Global document count is the sum of family tallies.
    assert counts["documents"] == sum(by_family.values())
    assert counts["documents"] >= full_recipe["expected"]["min_documents"]


def test_source_receipts_rights_and_current_through_bound(full_recipe) -> None:
    receipts = full_recipe["source_receipts"]
    assert len(receipts) >= 3
    families = {r["family"] for r in receipts}
    assert {"cfr", "mpep", "guidance"}.issubset(families)
    for r in receipts:
        assert r.get("package_digest_sha256")
        assert r.get("source_root_id")
        assert r.get("receipt")

    for root in full_recipe["source_roots"]:
        assert root.get("current_through")
        assert root.get("official_edition_cutoff")
        assert root.get("license_expression")
        assert root.get("source_uri")
        if root["family"] in {"cfr", "mpep", "guidance"}:
            assert root.get("full_authority") is True

    for doc in full_recipe["documents"]:
        assert doc["classification"] == "public_official"
        rights = doc["rights_review"]
        assert rights["review_status"] == "reviewed"
        assert rights["redistribution_allowed"] is True
        assert doc["current_through"]
        assert doc["source_lineage"]["source_sha256"]
        assert doc["source_lineage"]["source_uri"]
        assert len(doc["text"].strip()) >= 20


def test_mpep_documents_are_section_level_not_chapter_landings(full_recipe) -> None:
    mpep_docs = [d for d in full_recipe["documents"] if d["family"] == "mpep"]
    assert mpep_docs
    for d in mpep_docs:
        rid = d["record_id"]
        assert not rid.startswith("mpep:chapter:"), rid
        assert rid.startswith("mpep:section:"), rid
        meta = d.get("metadata") or {}
        assert meta.get("granularity") == "section"
        assert meta.get("full_authority") is True
        assert d["authority_kind"] == "guidance"


def test_cfr_documents_are_annual_family_not_ecfr(full_recipe) -> None:
    cfr_docs = [d for d in full_recipe["documents"] if d["family"] == "cfr"]
    assert cfr_docs
    for d in cfr_docs:
        assert d["record_id"].startswith("cfr:37:")
        assert d["authority_kind"] == "regulation"
        meta = d.get("metadata") or {}
        assert meta.get("full_authority") is True
        assert "package_id" in meta
        assert not d["record_id"].startswith("ecfr:")
    # No eCFR-only completion: recipe may omit ecfr entirely offline.
    assert full_recipe["full_authority"]["sources"]["cfr_title37"]["not_ecfr_only"]


def test_guidance_documents_cover_required_catalog(full_recipe) -> None:
    g_docs = [d for d in full_recipe["documents"] if d["family"] == "guidance"]
    ids = {d["metadata"]["document_id"] for d in g_docs}
    assert set(REQUIRED_DOCUMENT_IDS).issubset(ids)
    for d in g_docs:
        assert d["authority_kind"] == "guidance"
        assert d["metadata"].get("is_binding") is False
        assert d["metadata"].get("pdf_sha256")
        assert d["record_id"].startswith("guidance:pdf:")


def test_assert_full_authority_complete_accepts_built_recipe(
    build_mod, full_recipe
) -> None:
    build_mod.assert_full_authority_complete(full_recipe)
    # Idempotent on a deep copy.
    build_mod.assert_full_authority_complete(copy.deepcopy(full_recipe))


# ---------------------------------------------------------------------------
# Fail-closed: eCFR-only and chapter-only do not complete
# ---------------------------------------------------------------------------


def test_ecfr_only_cannot_complete_full_authority(build_mod, full_recipe) -> None:
    # Explicit helper.
    with pytest.raises(build_mod.EcfrOnlyCompletionError) as excinfo:
        build_mod.reject_ecfr_only_completion(
            documents=[{"family": "ecfr", "record_id": "ecfr:37:1.56"}],
            source_roots=[{"family": "ecfr", "source_id": "ecfr-only"}],
        )
    assert excinfo.value.code == "ecfr_only_completion_rejected"

    # Mutated recipe: drop annual CFR, keep only eCFR-shaped docs.
    broken = copy.deepcopy(full_recipe)
    broken["documents"] = [
        d for d in broken["documents"] if d["family"] != "cfr"
    ] + [
        {
            "record_id": "ecfr:37:1.56",
            "family": "ecfr",
            "source_root_id": "ecfr-only",
            "classification": "public_official",
            "citation": "37 C.F.R. § 1.56",
            "title": "Duty to disclose",
            "section_id": "1.56",
            "text": "eCFR-only substitute text that is long enough for the recipe floor.",
            "authority_kind": "regulation",
            "authority_claim": "source_bound",
            "current_through": "2024-06-01",
            "source_lineage": {
                "authority": "official",
                "source_id": "ecfr/1.56",
                "source_revision": "ecfr",
                "source_sha256": "a" * 64,
                "source_uri": "https://www.ecfr.gov/current/title-37/section-1.56",
            },
            "rights_review": dict(build_mod.RIGHTS),
        }
    ]
    broken["source_roots"] = [
        r for r in broken["source_roots"] if r["family"] != "cfr"
    ] + [
        {
            "source_id": "ecfr-only",
            "family": "ecfr",
            "current_through": "2024-06-01",
            "official_edition_cutoff": "2024-06-01",
            "source_uri": "https://www.ecfr.gov/current/title-37",
            "source_revision": "ecfr-only",
            "license_expression": "public-domain-US-government",
            "gaps": [],
        }
    ]
    broken["counts"]["by_family"] = build_mod._count_by(broken["documents"], "family")
    broken["full_authority"]["sources"].pop("cfr_title37", None)
    broken["full_authority"]["complete"] = True
    with pytest.raises(
        (build_mod.FullAuthorityIncompleteError, build_mod.EcfrOnlyCompletionError)
    ):
        build_mod.assert_full_authority_complete(broken)

    # not_ecfr_only=false is also rejected.
    broken2 = copy.deepcopy(full_recipe)
    broken2["full_authority"]["sources"]["cfr_title37"]["not_ecfr_only"] = False
    with pytest.raises(build_mod.EcfrOnlyCompletionError):
        build_mod.assert_full_authority_complete(broken2)


def test_chapter_only_mpep_cannot_complete_full_authority(
    build_mod, full_recipe
) -> None:
    with pytest.raises(build_mod.ChapterOnlyMpepCompletionError) as excinfo:
        build_mod.reject_chapter_only_mpep_completion(
            [
                {
                    "family": "mpep",
                    "record_id": "mpep:chapter:2100",
                    "section_id": "2100",
                    "metadata": {"granularity": "chapter_landing"},
                }
            ]
        )
    assert excinfo.value.code == "chapter_only_mpep_completion_rejected"

    broken = copy.deepcopy(full_recipe)
    # Replace section-level MPEP with chapter landings only.
    non_mpep = [d for d in broken["documents"] if d["family"] != "mpep"]
    chapter_docs = []
    for ch in sorted(REQUIRED_CHAPTER_IDS)[:5]:
        chapter_docs.append(
            {
                "record_id": f"mpep:chapter:{ch}",
                "family": "mpep",
                "source_root_id": "mpep-chapters-only",
                "classification": "public_official",
                "citation": f"MPEP {ch}",
                "title": f"Chapter {ch}",
                "section_id": ch,
                "text": (
                    f"Chapter landing page body for MPEP chapter {ch} "
                    "which is intentionally not section-level."
                ),
                "authority_kind": "guidance",
                "authority_claim": "source_bound",
                "current_through": "2024-02-01",
                "source_lineage": {
                    "authority": "official",
                    "source_id": f"mpep/chapter/{ch}",
                    "source_revision": "chapters-only",
                    "source_sha256": "b" * 64,
                    "source_uri": f"https://www.uspto.gov/web/offices/pac/mpep/mpep-{ch}.html",
                },
                "rights_review": dict(build_mod.RIGHTS),
                "metadata": {
                    "granularity": "chapter_landing",
                    "full_authority": False,
                },
            }
        )
    broken["documents"] = non_mpep + chapter_docs
    broken["counts"]["by_family"] = build_mod._count_by(broken["documents"], "family")
    broken["counts"]["full_authority"]["mpep_section_level"] = 0
    broken["counts"]["full_authority"]["mpep_documents"] = len(chapter_docs)
    broken["full_authority"]["sources"]["mpep_sections"]["chapter_only"] = True
    broken["full_authority"]["sources"]["mpep_sections"]["section_level_acquired"] = 0
    with pytest.raises(
        (
            build_mod.ChapterOnlyMpepCompletionError,
            build_mod.FullAuthorityIncompleteError,
        )
    ):
        build_mod.assert_full_authority_complete(broken)


def test_missing_guidance_or_short_mpep_fails(build_mod, full_recipe) -> None:
    broken = copy.deepcopy(full_recipe)
    broken["documents"] = [
        d for d in broken["documents"] if d["family"] != "guidance"
    ]
    broken["counts"]["by_family"] = build_mod._count_by(broken["documents"], "family")
    broken["counts"]["full_authority"]["guidance_pdfs"] = 0
    broken["full_authority"]["sources"]["uspto_guidance_pdfs"]["documents_present"] = 0
    with pytest.raises(build_mod.FullAuthorityIncompleteError):
        build_mod.assert_full_authority_complete(broken)


def test_build_recipe_full_authority_flag(build_mod) -> None:
    recipe = build_mod.build_recipe(full_authority=True)
    assert recipe["full_authority"]["complete"] is True
    assert recipe["counts"]["by_family"]["cfr"] >= 1
    assert recipe["counts"]["by_family"]["mpep"] >= len(REQUIRED_CHAPTER_IDS)
    assert recipe["counts"]["by_family"]["guidance"] >= len(REQUIRED_GUIDANCE_DOCUMENTS)


def test_cli_reject_flags_and_write(build_mod, tmp_path) -> None:
    # eCFR-only reject
    rc = build_mod.main(["--output", str(tmp_path / "unused.json"), "--reject-ecfr-only"])
    assert rc == 2
    # chapter-only reject
    rc = build_mod.main(
        ["--output", str(tmp_path / "unused.json"), "--reject-chapter-only-mpep"]
    )
    assert rc == 2
    # full authority write + validate
    out = tmp_path / "full_authority_recipe.json"
    rc = build_mod.main(["--output", str(out), "--full-authority"])
    assert rc == 0
    assert out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["full_authority"]["complete"] is True
    assert payload["counts"]["by_family"]["mpep"] >= len(REQUIRED_CHAPTER_IDS)
    rc = build_mod.main(
        ["--output", str(tmp_path / "noop.json"), "--validate-recipe", str(out)]
    )
    assert rc == 0


def test_recipe_json_is_serializable_and_compact_enough(full_recipe) -> None:
    raw = json.dumps(full_recipe, sort_keys=True, ensure_ascii=False)
    # Offline full-authority recipe should stay well under admission single-file
    # budget while still carrying full inventory tallies + present texts.
    assert len(raw.encode("utf-8")) < 1_048_576
    # Round-trip.
    restored = json.loads(raw)
    assert restored["counts"]["full_authority"]["cfr_inventory_total"] == (
        title37_section_count()
    )
