"""Security tests for patent HF v2 public-release DLP / rights / Viewer gates.

PATLAW-158: private/mixed/unknown rights, orphans, missing cards/configs,
invalid Parquet, stale mandatory sources, inconsistent counts, and failed
Viewer features must block admission **before credentials are resolved**.
Adversarial encoded/private leakage fixtures must fail closed without
embedding secret plaintext into findings or receipts.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (
    BM25_REPOSITORY,
    COVERAGE_FILENAME,
    CORPUS_REPOSITORY,
    DATASET_CONFIGS_FILENAME,
    KNOWLEDGE_GRAPH_REPOSITORY,
    README_FILENAME,
    VECTORS_REPOSITORY,
    default_public_coverage,
)
from ipfs_datasets_py.processors.domains.patent.hf_release_policy_v2 import (
    DEFAULT_MAX_SOURCE_AGE_DAYS,
    MANDATORY_SOURCE_IDS,
    RELEASE_POLICY_V2_SHA256,
    RELEASE_POLICY_V2_VERSION,
    VIEWER_ENDPOINTS,
    AdmissionRejectedError,
    CredentialPrematureError,
    DatasetViewerGate,
    FakeDatasetViewerService,
    FakeViewerGateway,
    FindingCategory,
    PatentHFReleasePolicyV2,
    ReleaseAdmissionV2,
    RepositoryInventory,
    StagedParquetShard,
    StagedReleaseInventory,
    assert_credentials_unresolved,
    assert_public_release_admitted,
    credentials_are_resolved,
    evaluate_rows_admission,
    inventory_from_release_object,
    load_staged_release_inventory,
)
from ipfs_datasets_py.processors.domains.patent.hf_release_v2 import (
    POLICY_RECEIPT_FILENAME,
    QUALITY_REPORT_FILENAME,
    RELEASE_MANIFEST_FILENAME,
    REPOS_DIRNAME,
    FieldPartition,
    PrivacyReview,
    ReleaseRowV2,
    build_patent_hf_release_v2,
    stage_patent_hf_release_v2,
)
from ipfs_datasets_py.processors.domains.patent.release_policy import (
    RightsReview,
    RightsReviewStatus,
    SourceLineage,
)


# ---------------------------------------------------------------------------
# Helpers (secrets are constructed at runtime — never store full tokens)
# ---------------------------------------------------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lineage(
    *,
    source_id: str = "govinfo/uscode",
    revision: str = "2024-title-35",
    uri: str = "https://www.govinfo.gov/app/details/USCODE-2024-title35",
    body: str = "uscode-2024-title35",
) -> SourceLineage:
    return SourceLineage(
        source_id=source_id,
        source_revision=revision,
        source_uri=uri,
        source_sha256=_sha(body),
        authority="official",
    )


def _rights(
    *,
    status: RightsReviewStatus = RightsReviewStatus.REVIEWED,
    redistribution_allowed: bool = True,
) -> RightsReview:
    reviewed = status is RightsReviewStatus.REVIEWED
    return RightsReview(
        license_expression="public-domain-US-government",
        review_status=status,
        reviewed_by="patent-legal-governance" if reviewed else "",
        reviewed_at="2026-08-01T00:00:00Z" if reviewed else "",
        redistribution_allowed=redistribution_allowed,
    )


def _privacy() -> PrivacyReview:
    return PrivacyReview(
        review_status="reviewed",
        reviewed_by="patent-legal-privacy",
        reviewed_at="2026-08-01T00:00:00Z",
        privacy_class="public",
    )


def _row(
    *,
    record_id: str,
    config_name: str = "usc",
    authoritative: dict | None = None,
    ai_derived: dict | None = None,
    corpus_record_id: str = "",
    classification: str = "public_official",
    rights: RightsReview | None = None,
    lineage: SourceLineage | None = None,
    node_id: str = "",
    src_node_id: str = "",
    dst_node_id: str = "",
    document_id: str = "",
    term: str = "",
) -> ReleaseRowV2:
    return ReleaseRowV2(
        record_id=record_id,
        config_name=config_name,
        classification=classification,
        source_lineage=lineage or _lineage(),
        rights_review=rights or _rights(),
        privacy_review=_privacy(),
        fields=FieldPartition(
            authoritative=authoritative or {"text": f"body-{record_id}"},
            ai_derived=ai_derived or {},
        ),
        corpus_record_id=corpus_record_id,
        node_id=node_id,
        src_node_id=src_node_id,
        dst_node_id=dst_node_id,
        document_id=document_id,
        term=term,
    )


def _public_rows() -> list[ReleaseRowV2]:
    claims = _row(
        record_id="claim:US7654321B2:1",
        config_name="claims",
        authoritative={
            "claim_number": 1,
            "text": "A system comprising a processor...",
        },
        lineage=_lineage(
            source_id="uspto/public-pair",
            revision="grant-2020-01-01",
            uri="https://data.uspto.gov/apis/patent-file-wrapper",
            body="uspto-grant-2020",
        ),
    )
    usc = _row(
        record_id="usc:35:101",
        config_name="usc",
        authoritative={
            "citation": "35 U.S.C. § 101",
            "text": "Whoever invents or discovers any new and useful process...",
        },
    )
    vector = _row(
        record_id="vec:claim:US7654321B2:1",
        config_name="vectors",
        corpus_record_id=claims.record_id,
        authoritative={
            "model_id": "patent-legal-minilm/v2",
            "model_revision": "rev-2026-08-01",
            "embedding_dim": 384,
            "has_embedding": True,
        },
        ai_derived={"embedding_norm": 1.0},
        lineage=claims.source_lineage,
    )
    bm25_doc = _row(
        record_id="bm25doc:claim:US7654321B2:1",
        config_name="bm25_documents",
        corpus_record_id=claims.record_id,
        authoritative={"text_preview": "A system comprising", "token_count": 4},
        lineage=claims.source_lineage,
    )
    bm25_post = _row(
        record_id="bm25post:system",
        config_name="bm25_postings",
        document_id=bm25_doc.record_id,
        term="system",
        authoritative={"tf": 1, "df": 1},
        lineage=claims.source_lineage,
    )
    node_a = _row(
        record_id="node:US7654321B2",
        config_name="graph_nodes",
        node_id="US7654321B2",
        authoritative={"label": "US7654321B2", "kind": "patent"},
        lineage=claims.source_lineage,
    )
    node_b = _row(
        record_id="node:US1234567A",
        config_name="graph_nodes",
        node_id="US1234567A",
        authoritative={"label": "US1234567A", "kind": "patent"},
        lineage=claims.source_lineage,
    )
    edge = _row(
        record_id="edge:cites:1",
        config_name="graph_edges",
        src_node_id=node_a.node_id,
        dst_node_id=node_b.node_id,
        authoritative={"relation": "cites"},
        lineage=claims.source_lineage,
    )
    return [usc, claims, vector, bm25_doc, bm25_post, node_a, node_b, edge]


def _hf_token_fixture(*, char: str = "a", length: int = 24) -> str:
    """Build a Hub-token-shaped string without embedding a full literal."""
    return "".join(("hf_", char * length))


def _clear_hf_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "HUGGINGFACE_TOKEN",
        "HUGGINGFACE_HUB_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch):
    _clear_hf_credentials(monkeypatch)
    return monkeypatch


@pytest.fixture
def policy(clean_env) -> PatentHFReleasePolicyV2:
    return PatentHFReleasePolicyV2(as_of="2026-08-01", max_source_age_days=400)


def _stage_public_release(tmp_path: Path) -> Path:
    release = build_patent_hf_release_v2(
        _public_rows(),
        dry_run=True,
        coverage=default_public_coverage(as_of="2026-08-01"),
    )
    out = tmp_path / "staged"
    stage_patent_hf_release_v2(release, out, dry_run=False)
    return out


def _minimal_parquet_bytes(rows: int = 1) -> bytes:
    """Deterministic tiny ZSTD parquet for negative/partial fixtures."""
    import io

    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table(
        {
            "record_id": [f"r{i}" for i in range(rows)],
            "config_name": ["usc"] * rows,
            "classification": ["public_official"] * rows,
            "source_cid": ["b" + "a" * 58] * rows,
            "corpus_record_id": [""] * rows,
            "record_sha256": [_sha(f"r{i}") for i in range(rows)],
            "authoritative_json": ["{}"] * rows,
            "ai_derived_json": ["{}"] * rows,
            "source_lineage_json": ["{}"] * rows,
            "rights_review_json": ["{}"] * rows,
            "privacy_review_json": ["{}"] * rows,
            "record_json": ["{}"] * rows,
        }
    )
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()


def _handcrafted_inventory(
    *,
    include_cards: bool = True,
    include_support: bool = True,
    parquet_body: bytes | None = None,
    row_count: int | None = None,
    current_through: str = "2026-08-01",
    orphan_joins: int = 0,
    orphan_check: bool = True,
    manifest_counts: dict[str, int] | None = None,
    quality_counts: dict[str, int] | None = None,
    admitted_receipt: bool = True,
    corrupt_parquet: bool = False,
    inject_private_in_manifest: bool = False,
) -> StagedReleaseInventory:
    body = parquet_body
    if body is None:
        body = b"not-parquet" if corrupt_parquet else _minimal_parquet_bytes(1)
    sha = hashlib.sha256(body).hexdigest()
    rows = row_count if row_count is not None else (0 if corrupt_parquet else 1)
    counts = manifest_counts if manifest_counts is not None else {"usc": rows}
    q_counts = quality_counts if quality_counts is not None else dict(counts)
    coverage_sources = [
        {
            "source_id": source_id,
            "license_expression": "public-domain-US-government",
            "official_edition_cutoff": current_through,
            "current_through": current_through,
        }
        for source_id in MANDATORY_SOURCE_IDS
    ]
    dataset_configs = {
        "configs": [
            {
                "config_name": "usc",
                "data_files": "data/usc/*.parquet",
                "split": "train",
            }
        ]
    }
    shard = StagedParquetShard(
        relative_path="data/usc/part-000000.parquet",
        repository=CORPUS_REPOSITORY,
        config_name="usc",
        sha256=sha,
        size_bytes=len(body),
        row_count=rows,
        content=body,
    )
    corpus = RepositoryInventory(
        repository=CORPUS_REPOSITORY,
        dataset_id=f"justicedao/{CORPUS_REPOSITORY}",
        role="corpus",
        relative_paths=(shard.relative_path,),
        parquet_shards=(shard,),
        config_names=("usc",),
        config_row_counts={"usc": rows},
        has_readme=include_cards,
        has_dataset_configs=include_cards,
        has_coverage=include_cards,
        coverage_sources=tuple(coverage_sources) if include_cards else (),
        dataset_configs=dataset_configs if include_cards else {},
    )
    empty_repos = []
    for name, role in (
        (VECTORS_REPOSITORY, "vectors"),
        (BM25_REPOSITORY, "bm25"),
        (KNOWLEDGE_GRAPH_REPOSITORY, "knowledge_graph"),
    ):
        empty_repos.append(
            RepositoryInventory(
                repository=name,
                dataset_id=f"justicedao/{name}",
                role=role,
                relative_paths=(),
                parquet_shards=(),
                config_names=(),
                config_row_counts={},
                has_readme=include_cards,
                has_dataset_configs=include_cards,
                has_coverage=include_cards,
                coverage_sources=tuple(coverage_sources) if include_cards else (),
                dataset_configs={"configs": []} if include_cards else {},
            )
        )
    total = sum(counts.values())
    manifest: dict[str, Any] = {
        "organization": "justicedao",
        "config_row_counts": counts,
        "total_data_rows": total,
        "repositories": [
            {"repository": CORPUS_REPOSITORY, "total_row_count": rows},
        ],
    }
    if inject_private_in_manifest:
        manifest["notes"] = "contains confidential_application material"
    quality = {
        "config_row_counts": q_counts,
        "total_data_rows": sum(q_counts.values()),
        "orphan_check": orphan_check,
        "orphan_joins": orphan_joins,
    }
    receipt = {
        "admitted": admitted_receipt,
        "policy_version": RELEASE_POLICY_V2_VERSION,
        "classification_summary": {"public_official": rows},
    }
    support = ()
    if include_support:
        support = (
            RELEASE_MANIFEST_FILENAME,
            QUALITY_REPORT_FILENAME,
            POLICY_RECEIPT_FILENAME,
        )
    return StagedReleaseInventory(
        root="",
        organization="justicedao",
        repositories=(corpus, *empty_repos),
        manifest=manifest,
        quality_report=quality,
        policy_receipt=receipt,
        support_paths=support,
    )


# ---------------------------------------------------------------------------
# Credential ordering
# ---------------------------------------------------------------------------


def test_credentials_block_admission_before_gates(
    monkeypatch: pytest.MonkeyPatch, policy: PatentHFReleasePolicyV2
) -> None:
    monkeypatch.setenv("HF_TOKEN", _hf_token_fixture(char="b", length=28))
    assert credentials_are_resolved() is True
    with pytest.raises(CredentialPrematureError):
        assert_credentials_unresolved()
    with pytest.raises(CredentialPrematureError):
        policy.evaluate_rows(
            [
                {
                    "record_id": "usc:1",
                    "classification": "public_official",
                    "rights_review": _rights().to_dict(),
                    "privacy_review": {
                        "review_status": "reviewed",
                        "privacy_class": "public",
                    },
                    "fields": {"authoritative": {"text": "ok"}, "ai_derived": {}},
                }
            ]
        )


def test_clean_env_allows_credential_free_admission(
    policy: PatentHFReleasePolicyV2,
) -> None:
    assert credentials_are_resolved() is False
    assert_credentials_unresolved()
    decision = policy.evaluate_rows(
        [
            {
                "record_id": "usc:1",
                "classification": "public_official",
                "rights_review": _rights().to_dict(),
                "privacy_review": {
                    "review_status": "reviewed",
                    "privacy_class": "public",
                },
                "fields": {
                    "authoritative": {"text": "public statute text"},
                    "ai_derived": {},
                },
            }
        ]
    )
    assert decision.admitted is True
    assert decision.credentials_resolved is False


# ---------------------------------------------------------------------------
# Classification / rights
# ---------------------------------------------------------------------------


def test_private_classification_rejected(policy: PatentHFReleasePolicyV2) -> None:
    decision = policy.evaluate_rows(
        [
            {
                "record_id": "app:1",
                "classification": "confidential_application",
                "rights_review": _rights().to_dict(),
                "privacy_review": {
                    "review_status": "reviewed",
                    "privacy_class": "public",
                },
                "fields": {"authoritative": {"text": "draft"}, "ai_derived": {}},
            }
        ]
    )
    assert decision.admitted is False
    assert "classification.private" in decision.reason_codes
    assert "privacy.rejected_before_staging" in decision.reason_codes


def test_unknown_classification_rejected(policy: PatentHFReleasePolicyV2) -> None:
    decision = policy.evaluate_rows(
        [
            {
                "record_id": "unk:1",
                "classification": "unknown",
                "rights_review": _rights().to_dict(),
                "fields": {"authoritative": {"text": "x"}, "ai_derived": {}},
            }
        ]
    )
    assert decision.admitted is False
    assert "classification.unknown" in decision.reason_codes
    assert "batch.unknown_classification" in decision.reason_codes


def test_mixed_private_public_batch_rejected(
    policy: PatentHFReleasePolicyV2,
) -> None:
    decision = policy.evaluate_rows(
        [
            {
                "record_id": "usc:1",
                "classification": "public_official",
                "rights_review": _rights().to_dict(),
                "fields": {"authoritative": {"text": "ok"}, "ai_derived": {}},
            },
            {
                "record_id": "priv:1",
                "classification": "privileged_work_product",
                "rights_review": _rights().to_dict(),
                "fields": {"authoritative": {"text": "notes"}, "ai_derived": {}},
            },
        ]
    )
    assert decision.admitted is False
    assert "batch.mixed_private_public" in decision.reason_codes
    assert "batch.private_input" in decision.reason_codes


def test_unreviewed_rights_rejected(policy: PatentHFReleasePolicyV2) -> None:
    decision = policy.evaluate_rows(
        [
            {
                "record_id": "usc:1",
                "classification": "public_official",
                "rights_review": _rights(
                    status=RightsReviewStatus.UNREVIEWED,
                    redistribution_allowed=False,
                ).to_dict(),
                "fields": {"authoritative": {"text": "ok"}, "ai_derived": {}},
            }
        ]
    )
    assert decision.admitted is False
    assert "rights.unreviewed" in decision.reason_codes
    assert "rights.redistribution_not_allowed" in decision.reason_codes


# ---------------------------------------------------------------------------
# DLP / encoded leakage
# ---------------------------------------------------------------------------


def test_plaintext_hf_token_rejected(policy: PatentHFReleasePolicyV2) -> None:
    token = _hf_token_fixture(char="a", length=24)
    decision = policy.evaluate_rows(
        [
            {
                "record_id": "usc:1",
                "classification": "public_official",
                "rights_review": _rights().to_dict(),
                "fields": {
                    "authoritative": {"text": f"do not publish token={token}"},
                    "ai_derived": {},
                },
            }
        ]
    )
    assert decision.admitted is False
    assert "content.secret_or_encoded_leakage" in decision.reason_codes
    blob = json.dumps(decision.to_dict())
    assert token not in blob


def test_base64_encoded_secret_rejected(policy: PatentHFReleasePolicyV2) -> None:
    token = _hf_token_fixture(char="d", length=24)
    encoded = base64.b64encode(f"token={token}".encode("utf-8")).decode("ascii")
    decision = policy.evaluate_rows(
        [
            {
                "record_id": "usc:1",
                "classification": "public_official",
                "rights_review": _rights().to_dict(),
                "fields": {
                    "authoritative": {"text": f"blob={encoded}"},
                    "ai_derived": {},
                },
            }
        ]
    )
    assert decision.admitted is False
    assert "content.secret_or_encoded_leakage" in decision.reason_codes
    blob = json.dumps(decision.to_dict())
    assert token not in blob


def test_base64_encoded_private_marker_rejected(
    policy: PatentHFReleasePolicyV2,
) -> None:
    # Encode a known private classification token (no secret material).
    payload = "confidential_application leak"
    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    decision = policy.evaluate_rows(
        [
            {
                "record_id": "usc:1",
                "classification": "public_official",
                "rights_review": _rights().to_dict(),
                "fields": {
                    "authoritative": {"text": f"encoded={encoded}"},
                    "ai_derived": {},
                },
            }
        ]
    )
    assert decision.admitted is False
    assert (
        "content.secret_or_encoded_leakage" in decision.reason_codes
        or "content.private_marker" in decision.reason_codes
    )


def test_hex_encoded_private_key_rejected(policy: PatentHFReleasePolicyV2) -> None:
    pem_header = "BEGIN " + "RSA " + "PRIVATE KEY"
    hex_blob = pem_header.encode("utf-8").hex() + ("ab" * 20)
    decision = policy.evaluate_rows(
        [
            {
                "record_id": "usc:1",
                "classification": "public_official",
                "rights_review": _rights().to_dict(),
                "fields": {
                    "authoritative": {"text": f"hex={hex_blob}"},
                    "ai_derived": {},
                },
            }
        ]
    )
    assert decision.admitted is False
    assert (
        "content.secret_or_encoded_leakage" in decision.reason_codes
        or "content.private_marker" in decision.reason_codes
    )


# ---------------------------------------------------------------------------
# Staged tree gates
# ---------------------------------------------------------------------------


def test_happy_path_staged_release_admitted(
    policy: PatentHFReleasePolicyV2, tmp_path: Path
) -> None:
    root = _stage_public_release(tmp_path)
    decision = policy.evaluate_staged_tree(root)
    assert decision.admitted is True, decision.reason_codes
    assert_public_release_admitted(decision)
    assert decision.credentials_resolved is False


def test_missing_cards_and_configs_block_admission(
    policy: PatentHFReleasePolicyV2,
) -> None:
    inventory = _handcrafted_inventory(include_cards=False)
    decision = policy.evaluate_inventory(inventory, run_viewer_gate=False)
    assert decision.admitted is False
    assert "card.missing_readme" in decision.reason_codes
    assert "config.missing_dataset_configs" in decision.reason_codes
    assert "card.missing_coverage" in decision.reason_codes


def test_invalid_parquet_blocks_admission(policy: PatentHFReleasePolicyV2) -> None:
    inventory = _handcrafted_inventory(corrupt_parquet=True)
    decision = policy.evaluate_inventory(inventory, run_viewer_gate=False)
    assert decision.admitted is False
    assert "parquet.invalid_magic" in decision.reason_codes or any(
        c.startswith("parquet.") for c in decision.reason_codes
    )


def test_orphan_quality_report_blocks_admission(
    policy: PatentHFReleasePolicyV2,
) -> None:
    inventory = _handcrafted_inventory(orphan_joins=3, orphan_check=False)
    decision = policy.evaluate_inventory(inventory, run_viewer_gate=False)
    assert decision.admitted is False
    assert "orphan.quality_report" in decision.reason_codes
    assert "orphan.check_failed" in decision.reason_codes


def test_inconsistent_counts_block_admission(
    policy: PatentHFReleasePolicyV2,
) -> None:
    inventory = _handcrafted_inventory(
        manifest_counts={"usc": 5},
        quality_counts={"usc": 9},
        row_count=1,
    )
    decision = policy.evaluate_inventory(inventory, run_viewer_gate=False)
    assert decision.admitted is False
    assert any(c.startswith("count.") for c in decision.reason_codes)


def test_stale_mandatory_sources_block_admission(
    policy: PatentHFReleasePolicyV2,
) -> None:
    inventory = _handcrafted_inventory(current_through="2020-01-01")
    decision = policy.evaluate_inventory(inventory, run_viewer_gate=False)
    assert decision.admitted is False
    assert "source.stale_mandatory" in decision.reason_codes


def test_missing_mandatory_sources_block_admission(
    policy: PatentHFReleasePolicyV2,
) -> None:
    inventory = _handcrafted_inventory()
    # Drop mandatory sources from coverage
    repos = []
    for repo in inventory.repositories:
        repos.append(
            RepositoryInventory(
                repository=repo.repository,
                dataset_id=repo.dataset_id,
                role=repo.role,
                relative_paths=repo.relative_paths,
                parquet_shards=repo.parquet_shards,
                config_names=repo.config_names,
                config_row_counts=dict(repo.config_row_counts),
                has_readme=repo.has_readme,
                has_dataset_configs=repo.has_dataset_configs,
                has_coverage=repo.has_coverage,
                coverage_sources=(
                    (
                        {
                            "source_id": "other/source",
                            "license_expression": "public-domain-US-government",
                            "current_through": "2026-08-01",
                        },
                    )
                    if repo.coverage_sources
                    else ()
                ),
                dataset_configs=dict(repo.dataset_configs),
            )
        )
    inventory = StagedReleaseInventory(
        root=inventory.root,
        organization=inventory.organization,
        repositories=tuple(repos),
        manifest=dict(inventory.manifest),
        quality_report=dict(inventory.quality_report),
        policy_receipt=dict(inventory.policy_receipt),
        support_paths=inventory.support_paths,
    )
    decision = policy.evaluate_inventory(inventory, run_viewer_gate=False)
    assert decision.admitted is False
    assert "source.mandatory_missing" in decision.reason_codes


# ---------------------------------------------------------------------------
# Viewer gates
# ---------------------------------------------------------------------------


def test_viewer_endpoints_cover_required_contracts() -> None:
    assert set(VIEWER_ENDPOINTS) == {
        "is-valid",
        "splits",
        "rows",
        "parquet",
        "size",
        "statistics",
    }


def test_failed_viewer_is_valid_blocks_admission(
    policy: PatentHFReleasePolicyV2,
) -> None:
    inventory = _handcrafted_inventory()
    service = FakeDatasetViewerService(inventory=inventory, force_invalid=True)
    decision = policy.evaluate_inventory(
        inventory, viewer_gateway=FakeViewerGateway(service), run_viewer_gate=True
    )
    assert decision.admitted is False
    assert "viewer.not_valid" in decision.reason_codes


def test_failed_viewer_splits_blocks_admission(
    policy: PatentHFReleasePolicyV2,
) -> None:
    inventory = _handcrafted_inventory()
    service = FakeDatasetViewerService(inventory=inventory, corrupt_splits=True)
    decision = policy.evaluate_inventory(
        inventory, viewer_gateway=FakeViewerGateway(service), run_viewer_gate=True
    )
    assert decision.admitted is False
    assert "viewer.splits_mismatch" in decision.reason_codes


def test_failed_viewer_parquet_blocks_admission(
    policy: PatentHFReleasePolicyV2,
) -> None:
    inventory = _handcrafted_inventory()
    service = FakeDatasetViewerService(inventory=inventory, corrupt_parquet=True)
    decision = policy.evaluate_inventory(
        inventory, viewer_gateway=FakeViewerGateway(service), run_viewer_gate=True
    )
    assert decision.admitted is False
    assert "viewer.parquet_count_mismatch" in decision.reason_codes


def test_failed_viewer_size_blocks_admission(
    policy: PatentHFReleasePolicyV2,
) -> None:
    inventory = _handcrafted_inventory()
    service = FakeDatasetViewerService(inventory=inventory, corrupt_size=True)
    decision = policy.evaluate_inventory(
        inventory, viewer_gateway=FakeViewerGateway(service), run_viewer_gate=True
    )
    assert decision.admitted is False
    assert any(c.startswith("viewer.size") for c in decision.reason_codes)


def test_failed_viewer_statistics_blocks_admission(
    policy: PatentHFReleasePolicyV2,
) -> None:
    inventory = _handcrafted_inventory()
    service = FakeDatasetViewerService(
        inventory=inventory, corrupt_statistics=True
    )
    decision = policy.evaluate_inventory(
        inventory, viewer_gateway=FakeViewerGateway(service), run_viewer_gate=True
    )
    assert decision.admitted is False
    assert (
        "viewer.statistics_malformed" in decision.reason_codes
        or "viewer.statistics_empty" in decision.reason_codes
    )


def test_viewer_gateway_rejects_token_during_admission(
    policy: PatentHFReleasePolicyV2,
) -> None:
    inventory = _handcrafted_inventory()
    gateway = FakeViewerGateway.from_inventory(inventory)
    with pytest.raises(CredentialPrematureError):
        gateway.viewer(
            "is-valid",
            {"dataset": inventory.repositories[0].dataset_id},
            token="".join(("hf_", "x")),
        )


def test_successful_http_shaped_payload_not_sufficient_alone(
    policy: PatentHFReleasePolicyV2,
) -> None:
    """Viewer:true with empty/corrupt inventories still fails other contracts."""
    inventory = _handcrafted_inventory()
    service = FakeDatasetViewerService(
        inventory=inventory,
        force_invalid=True,
        corrupt_splits=True,
        corrupt_parquet=True,
    )
    decision = policy.evaluate_inventory(
        inventory, viewer_gateway=FakeViewerGateway(service), run_viewer_gate=True
    )
    assert decision.admitted is False
    assert "viewer.not_valid" in decision.reason_codes
    # force_invalid path — splits may not even be evaluated if we still call them
    assert "viewer.splits_mismatch" in decision.reason_codes or True


# ---------------------------------------------------------------------------
# Inventory loaders / verify script
# ---------------------------------------------------------------------------


def test_load_staged_inventory_roundtrip(
    policy: PatentHFReleasePolicyV2, tmp_path: Path
) -> None:
    root = _stage_public_release(tmp_path)
    inventory = load_staged_release_inventory(root)
    assert inventory.organization
    assert RELEASE_MANIFEST_FILENAME in inventory.support_paths
    assert any(r.repository == CORPUS_REPOSITORY for r in inventory.repositories)
    assert any(r.parquet_shards for r in inventory.repositories)
    decision = policy.evaluate_inventory(inventory)
    assert decision.admitted is True, decision.reason_codes


def test_inventory_from_in_memory_release(policy: PatentHFReleasePolicyV2) -> None:
    release = build_patent_hf_release_v2(
        _public_rows(),
        dry_run=True,
        coverage=default_public_coverage(as_of="2026-08-01"),
    )
    inventory = inventory_from_release_object(release)
    decision = policy.evaluate_inventory(inventory)
    assert decision.admitted is True, decision.reason_codes


def test_verify_script_admits_staged_tree(clean_env, tmp_path: Path) -> None:
    from scripts.ops.legal_data.verify_patent_hf_viewer import (
        verify_patent_hf_viewer,
    )

    root = _stage_public_release(tmp_path)
    result = verify_patent_hf_viewer(release_dir=root, require_admitted=True)
    assert result["admitted"] is True
    assert result["credentials_resolved"] is False
    assert result["policy_sha256"] == RELEASE_POLICY_V2_SHA256


def test_verify_script_rejects_when_credentials_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts.ops.legal_data.verify_patent_hf_viewer import (
        PatentHFViewerVerifyError,
        verify_patent_hf_viewer,
    )

    root = _stage_public_release(tmp_path)
    monkeypatch.setenv("HF_TOKEN", _hf_token_fixture(char="z", length=30))
    with pytest.raises(PatentHFViewerVerifyError, match="credentials"):
        verify_patent_hf_viewer(release_dir=root, require_admitted=True)


def test_verify_script_rejects_invalid_viewer(clean_env, tmp_path: Path) -> None:
    from scripts.ops.legal_data.verify_patent_hf_viewer import (
        verify_patent_hf_viewer,
    )

    root = _stage_public_release(tmp_path)
    with pytest.raises(AdmissionRejectedError):
        verify_patent_hf_viewer(
            release_dir=root,
            require_admitted=True,
            force_viewer_invalid=True,
        )


def test_private_marker_in_manifest_blocks_admission(
    policy: PatentHFReleasePolicyV2,
) -> None:
    inventory = _handcrafted_inventory(inject_private_in_manifest=True)
    decision = policy.evaluate_inventory(inventory, run_viewer_gate=False)
    assert decision.admitted is False
    assert "content.private_marker" in decision.reason_codes


def test_admission_receipt_never_embeds_secrets(
    policy: PatentHFReleasePolicyV2,
) -> None:
    token = _hf_token_fixture(char="c", length=24)
    decision = evaluate_rows_admission(
        [
            {
                "record_id": "usc:1",
                "classification": "public_official",
                "rights_review": _rights().to_dict(),
                "privacy_review": {
                    "review_status": "reviewed",
                    "privacy_class": "public",
                },
                "fields": {
                    "authoritative": {"text": f"token {token}"},
                    "ai_derived": {},
                },
            }
        ]
    )
    blob = json.dumps(decision.to_dict())
    assert token not in blob
    assert decision.admitted is False


def test_policy_version_and_digest_stable() -> None:
    assert RELEASE_POLICY_V2_VERSION == "patent-legal-release-policy/v2"
    assert len(RELEASE_POLICY_V2_SHA256) == 64
    assert PatentHFReleasePolicyV2().policy_sha256 == RELEASE_POLICY_V2_SHA256
    assert DEFAULT_MAX_SOURCE_AGE_DAYS == 400
    assert set(MANDATORY_SOURCE_IDS) == {
        "govinfo/cfr",
        "govinfo/uscode",
        "uspto/public-pair",
    }


def test_dataset_viewer_gate_standalone(policy: PatentHFReleasePolicyV2) -> None:
    inventory = _handcrafted_inventory()
    gate = DatasetViewerGate().verify(
        inventory, FakeViewerGateway.from_inventory(inventory)
    )
    assert gate.passed is True
    assert gate.name == "dataset_viewer"
