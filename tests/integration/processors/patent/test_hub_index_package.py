"""Integration tests for multi-artifact Hub index package (PATLAW-174).

Acceptance:

* Package is byte-stable for pinned inputs
* Missing any of the three index families fails
* Rights / privacy metadata required on every artifact
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (
    BM25_REPOSITORY,
    CORPUS_REPOSITORY,
    DEFAULT_VERSION_TAG,
    KNOWLEDGE_GRAPH_REPOSITORY,
    ORGANIZATION,
    VECTORS_REPOSITORY,
)
from ipfs_datasets_py.processors.domains.patent.hub_index_package import (
    ARTIFACTS_INVENTORY_FILENAME,
    GOAL_ID,
    INDEX_FAMILIES,
    INTERFACE,
    LAYOUT_BUNDLE_FILENAME,
    MANIFEST_FILENAME,
    PACKAGE_ROOT_FILENAME,
    RECEIPT_FILENAME,
    REQUIRED_ROLES,
    SCHEMA_VERSION,
    TASK_ID,
    CorpusPinMismatchError,
    HubIndexPackage,
    HubIndexPackageArtifact,
    HubIndexPackageBuilder,
    HubIndexPackageManifest,
    IndexFamily,
    MissingIndexFamilyError,
    MissingRightsPrivacyError,
    PackageMode,
    assert_three_index_families_present,
    default_privacy_review,
    default_rights_review,
    load_package_manifest,
    package_patent_legal_hub_indexes,
    packages_are_byte_identical,
    validate_package,
)
from ipfs_datasets_py.processors.domains.patent.public_legal_bm25_builder import (
    build_public_legal_bm25_index,
)
from ipfs_datasets_py.processors.domains.patent.public_legal_corpus_materializer import (
    PublicLegalCorpusMaterializer,
    build_default_public_legal_recipe,
)
from ipfs_datasets_py.processors.domains.patent.public_legal_graph_builder import (
    build_public_legal_knowledge_graph,
)
from ipfs_datasets_py.processors.domains.patent.public_legal_vector_builder import (
    build_public_legal_vector_index,
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
    / "hub_index_package.manifest.schema.json"
)


@pytest.fixture(scope="module")
def recipe() -> dict:
    return build_default_public_legal_recipe()


@pytest.fixture(scope="module")
def corpus(recipe: dict):
    return PublicLegalCorpusMaterializer(require_all_families=True).materialize_from_recipe(
        recipe
    )


@pytest.fixture(scope="module")
def bm25(corpus):
    return build_public_legal_bm25_index(corpus)


@pytest.fixture(scope="module")
def vector(corpus):
    return build_public_legal_vector_index(corpus=corpus)


@pytest.fixture(scope="module")
def graph(corpus):
    return build_public_legal_knowledge_graph(materialization=corpus)


@pytest.fixture(scope="module")
def builder() -> HubIndexPackageBuilder:
    return HubIndexPackageBuilder()


@pytest.fixture(scope="module")
def baseline(builder: HubIndexPackageBuilder, corpus, bm25, vector, graph) -> HubIndexPackage:
    return builder.package(corpus=corpus, bm25=bm25, vector=vector, graph=graph)


# ---------------------------------------------------------------------------
# Constants / schema surface
# ---------------------------------------------------------------------------


def test_schema_pins_and_required_index_families():
    assert TASK_ID == "PATLAW-174"
    assert GOAL_ID == "PATLAW-G212"
    assert SCHEMA_VERSION == "patent.hub_index_package.v1"
    assert INTERFACE == "HubIndexPackageBuilder@1"
    assert INDEX_FAMILIES == ("bm25", "vectors", "knowledge_graph")
    assert set(REQUIRED_ROLES) == {
        "corpus",
        "bm25",
        "vectors",
        "knowledge_graph",
    }
    assert assert_three_index_families_present(INDEX_FAMILIES) == INDEX_FAMILIES


def test_schema_file_exists_and_declares_required_keys():
    assert _SCHEMA_PATH.is_file()
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    required = set(schema["required"])
    for key in (
        "package_root_cid",
        "corpus_root_cid",
        "bm25_root_cid",
        "vector_root_cid",
        "graph_root_cid",
        "index_families_present",
        "rights_summary",
        "privacy_summary",
        "artifact_descriptors",
        "families",
        "counts",
    ):
        assert key in required
    assert schema["properties"]["task_id"]["const"] == "PATLAW-174"
    assert schema["properties"]["partition"]["const"] == "public"


# ---------------------------------------------------------------------------
# Content-address stability for pinned inputs
# ---------------------------------------------------------------------------


def test_repeat_packages_are_byte_stable(
    builder: HubIndexPackageBuilder, corpus, bm25, vector, graph, baseline
):
    first = builder.package(corpus=corpus, bm25=bm25, vector=vector, graph=graph)
    second = builder.package(corpus=corpus, bm25=bm25, vector=vector, graph=graph)
    third = package_patent_legal_hub_indexes(
        corpus=corpus, bm25=bm25, vector=vector, graph=graph
    )

    assert first.package_root_cid == second.package_root_cid == baseline.package_root_cid
    assert (
        first.package_digest_sha256
        == second.package_digest_sha256
        == baseline.package_digest_sha256
    )
    assert first.to_canonical_bytes() == second.to_canonical_bytes()
    assert packages_are_byte_identical(first, third)
    assert first.corpus_root_cid == corpus.corpus_root_cid
    assert first.bm25_root_cid == bm25.index_cid
    assert first.vector_root_cid == vector.index_root_cid
    assert first.graph_root_cid == graph.graph_root_cid

    restored = HubIndexPackageManifest.from_dict(first.manifest.to_dict())
    assert restored.package_root_cid == first.package_root_cid
    assert restored.package_digest_sha256 == first.package_digest_sha256


def test_package_from_default_fixture_is_stable(builder: HubIndexPackageBuilder):
    a = builder.package_from_default_fixture()
    b = package_patent_legal_hub_indexes(default_fixture=True)
    assert a.package_root_cid == b.package_root_cid
    assert packages_are_byte_identical(a, b)
    assert set(a.manifest.index_families_present) == set(INDEX_FAMILIES)


def test_package_from_recipe_matches_materialization_path(
    builder: HubIndexPackageBuilder, recipe: dict, baseline
):
    from_recipe = builder.package_from_recipe(recipe)
    assert from_recipe.package_root_cid == baseline.package_root_cid
    assert from_recipe.corpus_root_cid == baseline.corpus_root_cid
    assert from_recipe.to_canonical_bytes() == baseline.to_canonical_bytes()


def test_changed_corpus_text_changes_package_root(
    builder: HubIndexPackageBuilder, recipe: dict, baseline
):
    altered = copy.deepcopy(recipe)
    altered["documents"][0]["text"] = altered["documents"][0]["text"] + " [amended]"
    result = builder.package_from_recipe(altered)
    assert result.corpus_root_cid != baseline.corpus_root_cid
    assert result.package_root_cid != baseline.package_root_cid


def test_dry_run_and_stage_share_package_root_cid(
    builder: HubIndexPackageBuilder,
    corpus,
    bm25,
    vector,
    graph,
    baseline,
    tmp_path: Path,
):
    staged = builder.package(
        corpus=corpus,
        bm25=bm25,
        vector=vector,
        graph=graph,
        stage=True,
        output_dir=tmp_path / "hub-package",
    )
    assert staged.mode is PackageMode.STAGE
    assert staged.package_root_cid == baseline.package_root_cid
    assert staged.package_digest_sha256 == baseline.package_digest_sha256
    assert staged.corpus_root_cid == baseline.corpus_root_cid

    out = tmp_path / "hub-package"
    for name in (
        MANIFEST_FILENAME,
        PACKAGE_ROOT_FILENAME,
        RECEIPT_FILENAME,
        LAYOUT_BUNDLE_FILENAME,
        ARTIFACTS_INVENTORY_FILENAME,
    ):
        assert (out / name).is_file(), name

    # Index pin trees and multi-repo layout cards.
    assert (out / "indexes" / "bm25").is_dir()
    assert (out / "indexes" / "vectors").is_dir()
    assert (out / "indexes" / "knowledge_graph").is_dir()
    assert (out / "indexes" / "corpus").is_dir()
    for repo in (
        CORPUS_REPOSITORY,
        BM25_REPOSITORY,
        VECTORS_REPOSITORY,
        KNOWLEDGE_GRAPH_REPOSITORY,
    ):
        assert (out / "repos" / repo / "README.md").is_file(), repo

    loaded = load_package_manifest(out / MANIFEST_FILENAME)
    assert loaded.package_root_cid == baseline.package_root_cid
    assert set(loaded.index_families_present) == set(INDEX_FAMILIES)


# ---------------------------------------------------------------------------
# Missing any of the three index families fails
# ---------------------------------------------------------------------------


def test_missing_bm25_fails(builder: HubIndexPackageBuilder, corpus, vector, graph):
    with pytest.raises(MissingIndexFamilyError) as excinfo:
        builder.package(corpus=corpus, bm25=None, vector=vector, graph=graph)
    assert "bm25" in str(excinfo.value).lower()


def test_missing_vector_fails(builder: HubIndexPackageBuilder, corpus, bm25, graph):
    with pytest.raises(MissingIndexFamilyError) as excinfo:
        builder.package(corpus=corpus, bm25=bm25, vector=None, graph=graph)
    assert "vector" in str(excinfo.value).lower()


def test_missing_graph_fails(builder: HubIndexPackageBuilder, corpus, bm25, vector):
    with pytest.raises(MissingIndexFamilyError) as excinfo:
        builder.package(corpus=corpus, bm25=bm25, vector=vector, graph=None)
    assert "knowledge_graph" in str(excinfo.value).lower() or "graph" in str(
        excinfo.value
    ).lower()


def test_assert_three_index_families_present_rejects_partial():
    with pytest.raises(MissingIndexFamilyError):
        assert_three_index_families_present(["bm25", "vectors"])
    with pytest.raises(MissingIndexFamilyError):
        assert_three_index_families_present({"bm25": True, "vectors": True})
    with pytest.raises(MissingIndexFamilyError):
        assert_three_index_families_present(None)


def test_manifest_rejects_missing_index_family_in_present_list(baseline):
    payload = baseline.manifest.to_dict()
    payload["index_families_present"] = ["bm25", "vectors"]  # missing graph
    # Clear self-pins so reconstruction re-seals or fails on family gate first.
    payload["package_root_cid"] = ""
    payload["package_digest_sha256"] = ""
    with pytest.raises(MissingIndexFamilyError):
        HubIndexPackageManifest.from_dict(payload)


def test_corpus_pin_mismatch_fails(
    builder: HubIndexPackageBuilder, recipe: dict, bm25, vector, graph
):
    # Build a different corpus so index snapshots no longer join.
    altered = copy.deepcopy(recipe)
    altered["documents"][0]["text"] = altered["documents"][0]["text"] + " [pin-break]"
    other_corpus = PublicLegalCorpusMaterializer(
        require_all_families=True
    ).materialize_from_recipe(altered)
    with pytest.raises(CorpusPinMismatchError):
        builder.package(
            corpus=other_corpus, bm25=bm25, vector=vector, graph=graph
        )


# ---------------------------------------------------------------------------
# Rights / privacy metadata required on every artifact
# ---------------------------------------------------------------------------


def test_every_artifact_has_rights_and_privacy(baseline: HubIndexPackage):
    assert baseline.artifacts
    for art in baseline.artifacts:
        assert art.rights_review is not None
        assert art.privacy_review is not None
        assert art.rights_review.review_status.value == "reviewed" or str(
            art.rights_review.review_status
        ) == "reviewed"
        assert art.rights_review.redistribution_allowed is True
        assert art.privacy_review.review_status == "reviewed"
        assert art.privacy_review.privacy_class == "public"
        assert art.classification in {"public_official", "public_user"}
        desc = art.descriptor()
        assert "rights_review" in desc
        assert "privacy_review" in desc


def test_artifact_without_rights_fails():
    rights = default_rights_review()
    privacy = default_privacy_review()
    with pytest.raises((MissingRightsPrivacyError, TypeError, Exception)):
        HubIndexPackageArtifact(
            relative_path="broken.json",
            content=b"{}",
            media_type="application/json",
            role="bm25",
            family="bm25",
            rights_review=None,  # type: ignore[arg-type]
            privacy_review=privacy,
        )
    # Missing privacy also fails.
    with pytest.raises((MissingRightsPrivacyError, TypeError, Exception)):
        HubIndexPackageArtifact(
            relative_path="broken.json",
            content=b"{}",
            media_type="application/json",
            role="bm25",
            family="bm25",
            rights_review=rights,
            privacy_review=None,  # type: ignore[arg-type]
        )


def test_artifact_non_public_privacy_fails():
    from ipfs_datasets_py.processors.domains.patent.hf_release_v2 import (
        PatentReleaseSafetyError,
    )

    rights = default_rights_review()
    with pytest.raises((MissingRightsPrivacyError, PatentReleaseSafetyError, Exception)):
        # PrivacyReview itself rejects non-public privacy_class.
        from ipfs_datasets_py.processors.domains.patent.hf_release_v2 import PrivacyReview

        bad_privacy = PrivacyReview(
            review_status="reviewed",
            reviewed_by="tester",
            reviewed_at="2026-08-01T00:00:00Z",
            privacy_class="private",
        )
        HubIndexPackageArtifact(
            relative_path="broken.json",
            content=b"{}",
            media_type="application/json",
            role="vectors",
            family="vectors",
            rights_review=rights,
            privacy_review=bad_privacy,
        )


def test_manifest_rights_privacy_summaries(baseline: HubIndexPackage):
    rights = baseline.manifest.rights_summary
    privacy = baseline.manifest.privacy_summary
    assert rights["all_reviewed"] is True
    assert rights["all_redistribution_allowed"] is True
    assert rights["partition"] == "public"
    assert privacy["privacy_class"] == "public"
    assert privacy["all_reviewed"] is True
    assert privacy["partition"] == "public"


def test_descriptor_inventory_requires_rights_privacy_on_all(baseline: HubIndexPackage):
    for item in baseline.manifest.artifact_descriptors:
        assert item["rights_review"]["review_status"] == "reviewed"
        assert item["privacy_review"]["review_status"] == "reviewed"
        assert item["privacy_review"]["privacy_class"] == "public"


# ---------------------------------------------------------------------------
# Package shape / multi-repo Viewer layouts / validation
# ---------------------------------------------------------------------------


def test_package_binds_four_repository_roles(baseline: HubIndexPackage):
    roles = {b.role for b in baseline.manifest.families}
    assert roles == set(REQUIRED_ROLES)
    assert baseline.family_binding("bm25").repository == BM25_REPOSITORY
    assert baseline.family_binding("vectors").repository == VECTORS_REPOSITORY
    assert (
        baseline.family_binding("knowledge_graph").repository
        == KNOWLEDGE_GRAPH_REPOSITORY
    )
    assert baseline.family_binding("corpus").repository == CORPUS_REPOSITORY
    for binding in baseline.manifest.families:
        assert binding.corpus_root_cid == baseline.corpus_root_cid
        assert binding.dataset_id.startswith(f"{ORGANIZATION}/")
        assert binding.layout_cid.startswith("b")
        assert binding.root_cid.startswith("b")


def test_viewer_layouts_cover_all_repos(baseline: HubIndexPackage):
    layouts = baseline.manifest.viewer_layouts
    assert layouts["version_tag"] == DEFAULT_VERSION_TAG
    repos = layouts["repositories"]
    for role in REQUIRED_ROLES:
        assert role in repos
        assert "layout_cid" in repos[role]
        assert "dataset_id" in repos[role]
        assert repos[role]["configs"]
    assert baseline.layout_bundle.bundle_cid == layouts["bundle_cid"]
    assert len(baseline.layout_bundle.packages) == 4


def test_counts_parity(baseline: HubIndexPackage, corpus, bm25, vector, graph):
    counts = baseline.manifest.counts
    assert counts.corpus_documents == len(corpus.documents)
    assert counts.bm25_documents == bm25.manifest.counts.document_count
    assert counts.vector_documents == vector.manifest.document_count
    assert counts.graph_nodes == graph.snapshot.counts.nodes
    assert counts.artifact_count == len(baseline.artifacts)
    assert counts.artifact_count >= 10


def test_validate_package_receipt(baseline: HubIndexPackage):
    receipt = validate_package(baseline)
    assert receipt["ok"] is True
    assert receipt["rights_privacy_ok"] is True
    assert receipt["task_id"] == TASK_ID
    assert set(receipt["index_families_present"]) == set(INDEX_FAMILIES)
    assert receipt["package_root_cid"] == baseline.package_root_cid


def test_manifest_round_trip_and_optional_jsonschema(baseline: HubIndexPackage):
    payload = baseline.manifest.to_dict()
    restored = HubIndexPackageManifest.from_dict(payload)
    assert restored.package_root_cid == baseline.package_root_cid
    assert restored.counts.to_dict() == baseline.manifest.counts.to_dict()

    if jsonschema is not None:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(instance=payload, schema=schema)


def test_index_family_coerce_aliases():
    assert IndexFamily.coerce("vector") is IndexFamily.VECTORS
    assert IndexFamily.coerce("graph") is IndexFamily.KNOWLEDGE_GRAPH
    assert IndexFamily.coerce("bm25") is IndexFamily.BM25
    with pytest.raises(Exception):
        IndexFamily.coerce("not-a-family")


def test_stage_requires_output_dir(
    builder: HubIndexPackageBuilder, corpus, bm25, vector, graph
):
    with pytest.raises(Exception):
        builder.package(
            corpus=corpus,
            bm25=bm25,
            vector=vector,
            graph=graph,
            stage=True,
            output_dir=None,
        )


def test_stage_refuses_nonempty_output_dir(
    builder: HubIndexPackageBuilder,
    corpus,
    bm25,
    vector,
    graph,
    tmp_path: Path,
):
    out = tmp_path / "occupied"
    out.mkdir()
    (out / "existing.txt").write_text("nope", encoding="utf-8")
    with pytest.raises(Exception):
        builder.package(
            corpus=corpus,
            bm25=bm25,
            vector=vector,
            graph=graph,
            stage=True,
            output_dir=out,
        )


def test_cli_module_importable():
    import importlib.util
    import sys

    script_path = (
        _REPO_ROOT
        / "scripts"
        / "ops"
        / "legal_data"
        / "package_patent_legal_hub_indexes.py"
    )
    assert script_path.is_file()
    spec = importlib.util.spec_from_file_location(
        "package_patent_legal_hub_indexes_cli", script_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert callable(module.main)
    assert module.main(["--list-index-families"]) == 0
