"""Integration tests for public patent-law / regulations corpus materializer.

PATLAW-170 acceptance:

* Repeat materializations for the same source roots are content-address stable
* Private / mixed / unknown inputs fail closed
* Manifest binds source roots, counts, and CIDs suitable for BM25 / vector /
  graph builders
* Rights, current-through, and source receipts are present on every root/doc
* Default fixture covers eCFR/CFR, U.S. Code/Public Law/Federal Register, and
  MPEP/guidance without network I/O
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.public_legal_corpus_materializer import (
    CORPUS_ROOT_FILENAME,
    DOCUMENTS_FILENAME,
    GOAL_ID,
    INTERFACE,
    MANIFEST_FILENAME,
    SCHEMA_VERSION,
    SOURCE_FAMILIES,
    SOURCE_RECEIPTS_FILENAME,
    TASK_ID,
    CorpusIntegrityError,
    MaterializationMode,
    MissingSourceReceiptError,
    PrivateOrMixedInputError,
    PublicLegalCorpusManifest,
    PublicLegalCorpusMaterializer,
    PublicLegalDocument,
    SchemaValidationError,
    SourceFamily,
    SourceRootBinding,
    UnreviewedRightsError,
    build_default_public_legal_recipe,
    build_public_legal_corpus,
    load_manifest,
    materializations_are_byte_identical,
    validate_materialization,
)

# Optional JSON Schema validation when jsonschema is installed.
try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None  # type: ignore

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SCHEMA_PATH = (
    _REPO_ROOT
    / "data"
    / "release"
    / "patent_legal_intelligence"
    / "public_legal_corpus.manifest.schema.json"
)


@pytest.fixture(scope="module")
def recipe() -> dict:
    return build_default_public_legal_recipe()


@pytest.fixture(scope="module")
def materializer() -> PublicLegalCorpusMaterializer:
    return PublicLegalCorpusMaterializer(require_all_families=True)


@pytest.fixture(scope="module")
def baseline(materializer: PublicLegalCorpusMaterializer, recipe: dict):
    return materializer.materialize_from_recipe(recipe)


# ---------------------------------------------------------------------------
# Recipe / coverage
# ---------------------------------------------------------------------------


def test_default_recipe_covers_all_source_families(recipe: dict):
    families = {root["family"] for root in recipe["source_roots"]}
    assert families == set(SOURCE_FAMILIES)
    assert len(recipe["documents"]) >= recipe["expected"]["min_documents"]
    assert recipe["expected"]["task_id"] == TASK_ID
    assert recipe["expected"]["partition"] == "public"


def test_default_recipe_is_compact(recipe: dict):
    raw = json.dumps(recipe, sort_keys=True, separators=(",", ":"))
    assert len(raw.encode("utf-8")) < 200_000


# ---------------------------------------------------------------------------
# Content-address stability
# ---------------------------------------------------------------------------


def test_repeat_materializations_are_content_address_stable(
    materializer: PublicLegalCorpusMaterializer, recipe: dict, baseline
):
    first = materializer.materialize_from_recipe(recipe)
    second = materializer.materialize_from_recipe(copy.deepcopy(recipe))
    third = build_public_legal_corpus(
        source_roots=recipe["source_roots"],
        documents=recipe["documents"],
        require_all_families=True,
    )

    assert first.corpus_root_cid == second.corpus_root_cid == baseline.corpus_root_cid
    assert (
        first.corpus_digest_sha256
        == second.corpus_digest_sha256
        == baseline.corpus_digest_sha256
    )
    assert first.to_canonical_bytes() == second.to_canonical_bytes()
    assert materializations_are_byte_identical(first, third)

    # Round-trip through manifest dict is stable.
    restored = PublicLegalCorpusManifest.from_dict(first.manifest.to_dict())
    assert restored.corpus_root_cid == first.corpus_root_cid
    assert restored.corpus_digest_sha256 == first.corpus_digest_sha256


def test_document_order_does_not_affect_corpus_cid(
    materializer: PublicLegalCorpusMaterializer, recipe: dict, baseline
):
    shuffled = copy.deepcopy(recipe)
    shuffled["documents"] = list(reversed(shuffled["documents"]))
    result = materializer.materialize_from_recipe(shuffled)
    assert result.corpus_root_cid == baseline.corpus_root_cid
    assert [d.record_id for d in result.documents] == sorted(
        d.record_id for d in result.documents
    )


def test_dry_run_and_stage_share_corpus_cid(
    materializer: PublicLegalCorpusMaterializer,
    recipe: dict,
    baseline,
    tmp_path: Path,
):
    staged = materializer.materialize_from_recipe(
        recipe, stage=True, output_dir=tmp_path / "corpus"
    )
    assert staged.mode is MaterializationMode.STAGE
    assert staged.corpus_root_cid == baseline.corpus_root_cid
    assert staged.corpus_digest_sha256 == baseline.corpus_digest_sha256
    assert (tmp_path / "corpus" / MANIFEST_FILENAME).is_file()
    assert (tmp_path / "corpus" / DOCUMENTS_FILENAME).is_file()
    assert (tmp_path / "corpus" / SOURCE_RECEIPTS_FILENAME).is_file()
    assert (tmp_path / "corpus" / CORPUS_ROOT_FILENAME).is_file()

    loaded = load_manifest(tmp_path / "corpus" / MANIFEST_FILENAME)
    assert loaded.corpus_root_cid == baseline.corpus_root_cid


def test_changed_source_text_changes_corpus_cid(
    materializer: PublicLegalCorpusMaterializer, recipe: dict, baseline
):
    altered = copy.deepcopy(recipe)
    altered["documents"][0]["text"] = altered["documents"][0]["text"] + " [amended]"
    result = materializer.materialize_from_recipe(altered)
    assert result.corpus_root_cid != baseline.corpus_root_cid
    assert result.corpus_digest_sha256 != baseline.corpus_digest_sha256


# ---------------------------------------------------------------------------
# Private / mixed fail closed
# ---------------------------------------------------------------------------


def test_private_classification_fails_closed(
    materializer: PublicLegalCorpusMaterializer, recipe: dict
):
    private = copy.deepcopy(recipe)
    private["documents"][0]["classification"] = "confidential_application"
    with pytest.raises(PrivateOrMixedInputError):
        materializer.materialize_from_recipe(private)


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
    materializer: PublicLegalCorpusMaterializer,
    recipe: dict,
    classification: str,
):
    bad = copy.deepcopy(recipe)
    bad["documents"][1]["classification"] = classification
    with pytest.raises((PrivateOrMixedInputError, SchemaValidationError)):
        materializer.materialize_from_recipe(bad)


def test_mixed_public_and_private_batch_fails_closed(
    materializer: PublicLegalCorpusMaterializer, recipe: dict
):
    mixed = copy.deepcopy(recipe)
    # Keep most public; inject one private row.
    mixed["documents"][2]["classification"] = "privileged_work_product"
    with pytest.raises(PrivateOrMixedInputError):
        materializer.materialize_from_recipe(mixed)


def test_unreviewed_rights_fail_closed(
    materializer: PublicLegalCorpusMaterializer, recipe: dict
):
    unreviewed = copy.deepcopy(recipe)
    unreviewed["documents"][0]["rights_review"] = {
        "license_expression": "public-domain-US-government",
        "notes": "",
        "redistribution_allowed": False,
        "review_status": "unreviewed",
        "reviewed_at": "",
        "reviewed_by": "",
    }
    with pytest.raises(UnreviewedRightsError):
        materializer.materialize_from_recipe(unreviewed)


def test_ai_derived_as_source_bound_fails(
    materializer: PublicLegalCorpusMaterializer, recipe: dict
):
    ai_law = copy.deepcopy(recipe)
    ai_law["documents"][0]["ai_derived"] = {"summary": "AI rewrite of the statute"}
    ai_law["documents"][0]["authority_claim"] = "source_bound"
    with pytest.raises(Exception) as exc_info:
        materializer.materialize_from_recipe(ai_law)
    assert "AI-derived" in str(exc_info.value) or "ai" in str(exc_info.value).lower()


def test_hard_coded_latest_revision_fails(
    materializer: PublicLegalCorpusMaterializer, recipe: dict
):
    bad = copy.deepcopy(recipe)
    bad["source_roots"][0]["source_revision"] = "latest"
    with pytest.raises(SchemaValidationError):
        materializer.materialize_from_recipe(bad)


def test_unknown_source_root_reference_fails(
    materializer: PublicLegalCorpusMaterializer, recipe: dict
):
    bad = copy.deepcopy(recipe)
    bad["documents"][0]["source_root_id"] = "does-not-exist"
    with pytest.raises(MissingSourceReceiptError):
        materializer.materialize_from_recipe(bad)


def test_family_mismatch_fails(
    materializer: PublicLegalCorpusMaterializer, recipe: dict
):
    bad = copy.deepcopy(recipe)
    # Point an eCFR document at a uscode root.
    uscode_root = next(
        r["source_id"] for r in bad["source_roots"] if r["family"] == "uscode"
    )
    bad["documents"][0]["source_root_id"] = uscode_root
    with pytest.raises(SchemaValidationError):
        materializer.materialize_from_recipe(bad)


# ---------------------------------------------------------------------------
# Manifest bindings for builders
# ---------------------------------------------------------------------------


def test_manifest_binds_source_roots_counts_and_cids(baseline):
    manifest = baseline.manifest
    assert manifest.schema_version == SCHEMA_VERSION
    assert manifest.interface == INTERFACE
    assert manifest.task_id == TASK_ID
    assert manifest.goal_id == GOAL_ID
    assert manifest.partition == "public"
    assert manifest.corpus_root_cid.startswith("b")
    assert len(manifest.corpus_digest_sha256) == 64

    assert manifest.counts.total_documents == len(baseline.documents)
    assert manifest.counts.source_root_count == len(manifest.source_roots)
    assert sum(manifest.counts.by_family.values()) == manifest.counts.total_documents

    # Every source family present.
    root_families = {root.family.value for root in manifest.source_roots}
    assert root_families == set(SOURCE_FAMILIES)

    for root in manifest.source_roots:
        assert root.root_cid.startswith("b")
        assert len(root.root_sha256) == 64
        assert root.current_through
        assert root.official_edition_cutoff
        assert root.document_count > 0
        assert root.license_expression

    # Document joins suitable for BM25/vector/graph.
    assert len(manifest.document_joins) == len(baseline.documents)
    for join, doc in zip(
        sorted(manifest.document_joins, key=lambda j: j["record_id"]),
        sorted(baseline.documents, key=lambda d: d.record_id),
    ):
        assert join["record_id"] == doc.record_id
        assert join["document_cid"] == doc.document_cid
        assert join["source_cid"] == doc.source_cid
        assert join["source_root_id"] == doc.source_root_id
        assert join["classification"] in {"public_official", "public_user"}

    bindings = dict(manifest.builder_bindings)
    assert bindings["record_count"] == len(baseline.documents)
    assert bindings["source_manifest_cid"].startswith("b")
    for family in ("bm25", "vector", "graph"):
        assert family in bindings
        assert bindings[family]["required_partition"] == "public"
        assert "document_cid" in bindings[family]["join_fields"]
        assert "source_cid" in bindings[family]["join_fields"]

    assert manifest.rights_summary["all_reviewed"] is True
    assert manifest.rights_summary["all_redistribution_allowed"] is True
    assert manifest.rights_summary["partition"] == "public"


def test_manifest_matches_release_schema(baseline):
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    assert _SCHEMA_PATH.is_file()
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=baseline.manifest.to_dict(), schema=schema)


def test_validate_materialization_receipt(baseline):
    receipt = validate_materialization(baseline)
    assert receipt["ok"] is True
    assert receipt["stable"] is True
    assert receipt["task_id"] == TASK_ID
    assert receipt["document_count"] == len(baseline.documents)


def test_source_root_binding_is_content_address_stable():
    a = SourceRootBinding(
        source_id="ecfr-title37-2024",
        family=SourceFamily.ECFR,
        current_through="2024-06-01",
        official_edition_cutoff="2024-06-01",
        source_uri="https://www.ecfr.gov/current/title-37",
        source_revision="ecfr-2024-06-01-title37",
    )
    b = SourceRootBinding(
        source_id="ecfr-title37-2024",
        family="ecfr",
        current_through="2024-06-01",
        official_edition_cutoff="2024-06-01",
        source_uri="https://www.ecfr.gov/current/title-37",
        source_revision="ecfr-2024-06-01-title37",
    )
    assert a.root_cid == b.root_cid
    assert a.root_sha256 == b.root_sha256


def test_document_round_trip(baseline):
    original = baseline.documents[0]
    restored = PublicLegalDocument.from_dict(original.to_dict())
    assert restored.document_cid == original.document_cid
    assert restored.to_dict() == original.to_dict()


def test_mpep_cannot_claim_statute_authority(
    materializer: PublicLegalCorpusMaterializer, recipe: dict
):
    bad = copy.deepcopy(recipe)
    mpep_doc = next(d for d in bad["documents"] if d["family"] == "mpep")
    mpep_doc["authority_kind"] = "statute"
    with pytest.raises(SchemaValidationError):
        materializer.materialize_from_recipe(bad)


def test_stage_rejects_private_before_write(
    materializer: PublicLegalCorpusMaterializer,
    recipe: dict,
    tmp_path: Path,
):
    # Build a valid result then attempt to stage a mutated private batch via
    # a fresh materialize call that fails before writing.
    private = copy.deepcopy(recipe)
    private["documents"][0]["classification"] = "confidential_application"
    out = tmp_path / "should-not-exist"
    with pytest.raises(PrivateOrMixedInputError):
        materializer.materialize_from_recipe(private, stage=True, output_dir=out)
    assert not out.exists() or not any(out.iterdir())


def test_corpus_integrity_on_tampered_manifest_digest(baseline):
    payload = baseline.manifest.to_dict()
    payload["corpus_digest_sha256"] = "0" * 64
    with pytest.raises(CorpusIntegrityError):
        PublicLegalCorpusManifest.from_dict(payload)


def test_guidance_and_regulation_authority_kinds_preserved(baseline):
    kinds = {doc.authority_kind for doc in baseline.documents}
    assert "statute" in kinds
    assert "regulation" in kinds
    assert "guidance" in kinds
    assert "public_law" in kinds
    assert "federal_register" in kinds

    mpep = next(d for d in baseline.documents if d.family is SourceFamily.MPEP)
    assert mpep.authority_kind == "guidance"
    usc = next(d for d in baseline.documents if d.record_id == "usc:35:101")
    assert usc.authority_kind == "statute"
    assert usc.citation == "35 U.S.C. § 101"
