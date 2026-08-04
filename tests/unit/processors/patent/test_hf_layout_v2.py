"""Unit tests for Viewer-compatible JusticeDAO patent/legal Hub layout v2."""

from __future__ import annotations

import json
import re

import pytest

from ipfs_datasets_py.processors.domains.patent import hf_layout_v2 as layout_mod
from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (
    BM25_REPOSITORY,
    CORPUS_REPOSITORY,
    COVERAGE_FILENAME,
    DATASET_CONFIGS_FILENAME,
    DEFAULT_VERSION_TAG,
    HF_LAYOUT_V2_SCHEMA_VERSION,
    JSONLD_MANIFEST_FILENAME,
    KNOWLEDGE_GRAPH_REPOSITORY,
    LEGACY_V1_LOWERCASE_ID,
    LEGACY_V1_REPOSITORY_ID,
    MIGRATION_POINTER_FILENAME,
    ORGANIZATION,
    README_FILENAME,
    VECTORS_REPOSITORY,
    CoverageMetadata,
    HubConfigSpec,
    HubRepositoryIdentity,
    MigrationPointer,
    PatentHubLayoutError,
    PatentHubLayoutV2,
    PrivateConfigRejectedError,
    SourceDisclosure,
    ViewerPatternError,
    build_default_layout_bundle,
    default_public_coverage,
    legacy_repository_inventory,
    pattern_matches_path,
    validate_no_private_configs,
)


def _layout(**kwargs: object) -> PatentHubLayoutV2:
    return PatentHubLayoutV2(**kwargs)  # type: ignore[arg-type]


def _coverage(**overrides: object) -> CoverageMetadata:
    if not overrides:
        return default_public_coverage()
    base = default_public_coverage()
    data = {
        "sources": base.sources,
        "parser_versions": dict(base.parser_versions),
        "model_versions": dict(base.model_versions),
        "gaps": base.gaps,
        "responsible_use": base.responsible_use,
        "coverage_notes": base.coverage_notes,
    }
    data.update(overrides)
    return CoverageMetadata(**data)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Identities
# ---------------------------------------------------------------------------


def test_canonical_identities_are_lowercase_justicedao() -> None:
    layout = _layout()
    identities = layout.repository_identities()
    assert len(identities) == 4
    assert {item.organization for item in identities} == {ORGANIZATION}
    assert ORGANIZATION == "justicedao"
    assert ORGANIZATION == ORGANIZATION.lower()

    by_role = {item.role: item for item in identities}
    assert by_role["corpus"].dataset_id == f"justicedao/{CORPUS_REPOSITORY}"
    assert by_role["vectors"].dataset_id == f"justicedao/{VECTORS_REPOSITORY}"
    assert by_role["bm25"].dataset_id == f"justicedao/{BM25_REPOSITORY}"
    assert (
        by_role["knowledge_graph"].dataset_id
        == f"justicedao/{KNOWLEDGE_GRAPH_REPOSITORY}"
    )
    for identity in identities:
        assert identity.dataset_id == identity.dataset_id.lower()
        assert identity.organization == identity.organization.lower()
        assert identity.repository == identity.repository.lower()


def test_mixed_case_organization_rejected() -> None:
    with pytest.raises(PatentHubLayoutError, match="lowercase"):
        PatentHubLayoutV2(organization="JusticeDAO")
    with pytest.raises(PatentHubLayoutError, match="lowercase"):
        HubRepositoryIdentity(
            organization="JusticeDAO",
            repository="patent-legal-corpus",
            role="corpus",
        )


# ---------------------------------------------------------------------------
# Config catalogs and private rejection
# ---------------------------------------------------------------------------


def test_corpus_and_separate_vector_bm25_kg_configs() -> None:
    layout = _layout()
    corpus = {cfg.config_name for cfg in layout.configs_for_role("corpus")}
    vectors = {cfg.config_name for cfg in layout.configs_for_role("vectors")}
    bm25 = {cfg.config_name for cfg in layout.configs_for_role("bm25")}
    kg = {cfg.config_name for cfg in layout.configs_for_role("knowledge_graph")}

    assert "usc" in corpus and "claims" in corpus and "cfr" in corpus
    assert "vectors" in vectors and "vector_chunk_index" in vectors
    assert "bm25_documents" in bm25 and "bm25_postings" in bm25
    assert "graph_nodes" in kg and "graph_edges" in kg

    # Roles are separate: no vector config in corpus catalog, etc.
    assert vectors.isdisjoint(corpus)
    assert bm25.isdisjoint(corpus)
    assert kg.isdisjoint(corpus)


def test_root_parquet_patterns_are_viewer_shaped() -> None:
    layout = _layout()
    for role in ("corpus", "vectors", "bm25", "knowledge_graph"):
        for cfg in layout.configs_for_role(role):  # type: ignore[arg-type]
            assert cfg.visibility == "public"
            assert "*.parquet" in cfg.data_files_pattern or cfg.data_files_pattern.endswith(
                ".parquet"
            )
            assert not cfg.data_files_pattern.startswith("/")
            assert ".." not in cfg.data_files_pattern


@pytest.mark.parametrize(
    "name",
    [
        "private_claims",
        "confidential_applications",
        "privileged_notes",
        "mixed_batch",
        "secret_export",
        "internal_matter",
        "work_product",
    ],
)
def test_private_config_names_cannot_be_declared(name: str) -> None:
    with pytest.raises(PrivateConfigRejectedError, match="private configs cannot"):
        HubConfigSpec(
            config_name=name,
            data_files_pattern=f"data/{name}/*.parquet",
            role="corpus",
        )
    with pytest.raises(PrivateConfigRejectedError):
        validate_no_private_configs([name])


def test_non_public_visibility_rejected() -> None:
    with pytest.raises(PrivateConfigRejectedError):
        HubConfigSpec(
            config_name="claims",
            data_files_pattern="data/claims/*.parquet",
            role="corpus",
            visibility="private",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Cards / configs enumerate required disclosures
# ---------------------------------------------------------------------------


def test_generated_card_and_coverage_enumerate_required_fields() -> None:
    layout = _layout()
    package = layout.build_repository_package(
        role="corpus",
        coverage=_coverage(),
    )
    card = package.dataset_card_text().lower()
    coverage = package.coverage.to_dict()
    configs = package.dataset_configs()

    # Card prose disclosures
    for token in (
        "sources",
        "license",
        "official-edition",
        "current-through",
        "freshness",
        "gaps",
        "parser",
        "model",
        "responsible use",
    ):
        assert token in card, f"missing card token: {token}"

    # Machine-readable coverage
    assert coverage["sources"]
    assert coverage["licenses"]
    assert coverage["official_edition_cutoffs"]
    assert coverage["freshness"]
    assert coverage["current_through"]
    assert coverage["gaps"]
    assert coverage["parser_versions"]
    assert coverage["model_versions"]
    assert coverage["responsible_use"]

    # Configs enumerate sources of truth for Viewer patterns
    names = {item["config_name"] for item in configs["configs"]}
    assert "usc" in names
    assert all(item["visibility"] == "public" for item in configs["configs"])
    assert all(item.get("data_files") for item in configs["configs"])

    # Support artifacts present
    for path in (
        README_FILENAME,
        DATASET_CONFIGS_FILENAME,
        JSONLD_MANIFEST_FILENAME,
        COVERAGE_FILENAME,
    ):
        artifact = package.artifact(path)
        assert artifact.sha256
        assert artifact.content_cid.startswith("b")
        assert artifact.size_bytes > 0

    validation = layout.validate_package(package)
    assert validation["valid"] is True


def test_jsonld_manifest_binds_cid_join_fields() -> None:
    layout = _layout()
    package = layout.build_repository_package(
        role="vectors",
        coverage=_coverage(),
    )
    jsonld = json.loads(package.artifact(JSONLD_MANIFEST_FILENAME).text())
    assert jsonld["@context"]
    assert jsonld["dataset_id"] == "justicedao/patent-legal-vectors"
    assert jsonld["schema_version"] == HF_LAYOUT_V2_SCHEMA_VERSION
    assert jsonld["version_tag"] == DEFAULT_VERSION_TAG
    join_sets = [tuple(item["join_fields"]) for item in jsonld["configs"]]
    assert any("source_cid" in fields for fields in join_sets)
    assert all(item["visibility"] == "public" for item in jsonld["configs"])


# ---------------------------------------------------------------------------
# Viewer pattern resolution
# ---------------------------------------------------------------------------


def test_viewer_file_patterns_resolve_for_corpus_paths() -> None:
    layout = _layout()
    paths = [
        "data/usc/part-000000.parquet",
        "data/cfr/part-000000.parquet",
        "data/public_law/part-000000.parquet",
        "data/federal_register/part-000000.parquet",
        "data/projected_rules/part-000000.parquet",
        "data/applications/part-000000.parquet",
        "data/claims/part-000000.parquet",
        "data/events/part-000000.parquet",
        "data/office_actions/part-000000.parquet",
        "data/citations/part-000000.parquet",
    ]
    result = layout.resolve_viewer_patterns(
        role="corpus",
        relative_paths=paths,
    )
    assert result["viewer_patterns_resolve"] is True
    assert result["unresolved_configs"] == []
    assert result["matched"]["usc"] == ["data/usc/part-000000.parquet"]
    assert result["matched"]["claims"] == ["data/claims/part-000000.parquet"]


def test_viewer_patterns_resolve_for_vector_bm25_and_graph() -> None:
    layout = _layout()

    vector_paths = [
        "data/vectors/part-000000.parquet",
        "indexes/vector_chunks.parquet",
    ]
    bm25_paths = [
        "data/bm25/documents/part-000000.parquet",
        "data/bm25/postings/part-000000.parquet",
    ]
    kg_paths = [
        "data/graph/nodes/part-000000.parquet",
        "data/graph/edges/part-000000.parquet",
        "indexes/graph_node_chunks.parquet",
        "indexes/graph_edge_chunks.parquet",
    ]

    assert layout.resolve_viewer_patterns(
        role="vectors", relative_paths=vector_paths
    )["viewer_patterns_resolve"]
    assert layout.resolve_viewer_patterns(
        role="bm25", relative_paths=bm25_paths
    )["viewer_patterns_resolve"]
    assert layout.resolve_viewer_patterns(
        role="knowledge_graph", relative_paths=kg_paths
    )["viewer_patterns_resolve"]


def test_missing_path_for_config_raises_viewer_error() -> None:
    layout = _layout()
    with pytest.raises(ViewerPatternError, match="did not resolve"):
        layout.resolve_viewer_patterns(
            role="corpus",
            relative_paths=["data/usc/part-000000.parquet"],
        )


def test_pattern_matches_path_helpers() -> None:
    assert pattern_matches_path("data/usc/*.parquet", "data/usc/part-000001.parquet")
    assert pattern_matches_path(
        "indexes/vector_chunks.parquet", "indexes/vector_chunks.parquet"
    )
    assert not pattern_matches_path("data/usc/*.parquet", "data/cfr/part-000000.parquet")
    assert not pattern_matches_path("data/usc/*.parquet", "data/usc/nested/x.parquet")


def test_validate_package_with_paths() -> None:
    layout = _layout()
    package = layout.build_repository_package(role="bm25", coverage=_coverage())
    paths = [
        "data/bm25/documents/a.parquet",
        "data/bm25/postings/b.parquet",
    ]
    result = layout.validate_package(package, relative_paths=paths)
    assert result["valid"] is True
    assert result["viewer_resolution"]["viewer_patterns_resolve"] is True


# ---------------------------------------------------------------------------
# Migration pointers — forward without deletion
# ---------------------------------------------------------------------------


def test_legacy_repos_point_forward_without_deletion() -> None:
    layout = _layout()
    bundle = layout.build_bundle(
        coverage=_coverage(),
        include_legacy_migration=True,
    )
    corpus = bundle.package_for_role("corpus")
    assert corpus.migration_pointers
    legacy_ids = {p.legacy_dataset_id for p in corpus.migration_pointers}
    assert LEGACY_V1_REPOSITORY_ID in legacy_ids
    assert LEGACY_V1_LOWERCASE_ID in legacy_ids

    for pointer in corpus.migration_pointers:
        assert pointer.preserves_legacy_data is True
        assert pointer.deletion_allowed is False
        assert pointer.target_dataset_id == "justicedao/patent-legal-corpus"
        assert pointer.target_version_tag == layout.version_tag
        doc = pointer.to_dict()
        assert doc["preserves_legacy_data"] is True
        assert doc["deletion_allowed"] is False

    # Pointer file is emitted on the corpus package.
    pointer_file = json.loads(corpus.artifact(MIGRATION_POINTER_FILENAME).text())
    assert pointer_file["preserves_legacy_data"] is True
    assert len(pointer_file["pointers"]) >= 2

    # Other roles do not inherit legacy monorepo pointers by default.
    for role in ("vectors", "bm25", "knowledge_graph"):
        assert bundle.package_for_role(role).migration_pointers == ()  # type: ignore[arg-type]


def test_migration_pointer_rejects_deletion_authorization() -> None:
    with pytest.raises(PatentHubLayoutError, match="deletion"):
        MigrationPointer(
            legacy_dataset_id=LEGACY_V1_REPOSITORY_ID,
            target_dataset_id="justicedao/patent-legal-corpus",
            target_version_tag=DEFAULT_VERSION_TAG,
            deletion_allowed=True,
        )
    with pytest.raises(PatentHubLayoutError, match="preserve"):
        MigrationPointer(
            legacy_dataset_id=LEGACY_V1_REPOSITORY_ID,
            target_dataset_id="justicedao/patent-legal-corpus",
            target_version_tag=DEFAULT_VERSION_TAG,
            preserves_legacy_data=False,
        )


def test_build_legacy_forward_pointer_api() -> None:
    layout = _layout(version_tag="patent-legal-v2.1.0")
    pointer = layout.build_legacy_forward_pointer(
        legacy_dataset_id="JusticeDAO/patent-legal-public",
        target_role="corpus",
        target_revision="abc123",
    )
    assert pointer.legacy_dataset_id == "JusticeDAO/patent-legal-public"
    assert pointer.target_dataset_id == "justicedao/patent-legal-corpus"
    assert pointer.target_version_tag == "patent-legal-v2.1.0"
    assert pointer.target_revision == "abc123"
    assert pointer.deletion_allowed is False


def test_legacy_inventory_is_immutable_operator_input() -> None:
    inventory = legacy_repository_inventory()
    assert inventory
    assert any(
        item["dataset_id"] == LEGACY_V1_REPOSITORY_ID for item in inventory
    )
    for item in inventory:
        assert item["preserves_data"] is True
        assert item.get("viewer_failures")


# ---------------------------------------------------------------------------
# Bundle integrity / determinism
# ---------------------------------------------------------------------------


def test_default_bundle_is_deterministic() -> None:
    first = build_default_layout_bundle()
    second = build_default_layout_bundle()
    assert first.bundle_cid == second.bundle_cid
    assert first.to_dict() == second.to_dict()
    assert len(first.packages) == 4
    assert first.schema_version == HF_LAYOUT_V2_SCHEMA_VERSION
    for pkg in first.packages:
        assert pkg.layout_cid
        assert pkg.version_tag == DEFAULT_VERSION_TAG
        assert pkg.identity.organization == "justicedao"


def test_version_tag_propagates_to_cards_and_configs() -> None:
    tag = "patent-legal-v2.2.0"
    layout = _layout(version_tag=tag)
    package = layout.build_repository_package(
        role="knowledge_graph",
        coverage=_coverage(),
    )
    assert package.version_tag == tag
    assert f'version_tag: "{tag}"' in package.dataset_card_text()
    assert package.dataset_configs()["version_tag"] == tag


def test_source_disclosure_requires_cutoff_and_current_through() -> None:
    with pytest.raises(PatentHubLayoutError, match="official_edition_cutoff"):
        SourceDisclosure(
            source_id="govinfo/uscode",
            license_expression="public-domain-US-government",
            official_edition_cutoff="not-a-date",
            current_through="2026-08-01",
        )
    with pytest.raises(PatentHubLayoutError, match="current_through"):
        SourceDisclosure(
            source_id="govinfo/uscode",
            license_expression="public-domain-US-government",
            official_edition_cutoff="2026-08-01",
            current_through="",
        )


def test_extra_private_config_rejected_on_package_build() -> None:
    layout = _layout()
    with pytest.raises(PrivateConfigRejectedError):
        layout.build_repository_package(
            role="corpus",
            coverage=_coverage(),
            extra_configs=[
                HubConfigSpec(
                    config_name="secret_notes",
                    data_files_pattern="data/secret_notes/*.parquet",
                    role="corpus",
                )
            ],
        )


def test_module_has_no_upload_or_hf_api_shortcuts() -> None:
    source = layout_mod.__file__
    assert source is not None
    text = open(source, encoding="utf-8").read()
    for forbidden in (
        "HfApi",
        "upload_file",
        "huggingface_hub",
        "delete_repo",
        "move_repo",
    ):
        # Allow mentions only inside prose/docstrings about non-goals if carefully
        # worded; hard-fail on import/call patterns.
        assert not re.search(
            rf"from\s+huggingface_hub|import\s+huggingface_hub|\bHfApi\s*\(|\.upload_file\s*\(",
            text,
        )
        if forbidden in {"delete_repo", "move_repo"}:
            assert forbidden not in text


def test_card_frontmatter_lists_every_config_data_files_path() -> None:
    layout = _layout()
    package = layout.build_repository_package(role="corpus", coverage=_coverage())
    card = package.dataset_card_text()
    for cfg in package.configs:
        assert f'config_name: "{cfg.config_name}"' in card
        assert f'path: "{cfg.data_files_pattern}"' in card
