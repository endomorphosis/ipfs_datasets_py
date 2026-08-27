"""Artifact-preserving State Laws publication-package tests."""

from __future__ import annotations

import inspect
import json
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.huggingface import publisher as publisher_module
from ipfs_datasets_py.huggingface.publication_profile import (
    patent_legal_publication_profile,
)
from ipfs_datasets_py.huggingface.publisher import (
    HuggingFacePublicationError,
    HuggingFaceReleasePublisher,
    PublicationApproval,
)
from ipfs_datasets_py.processors.legal_data import (
    legal_corpora_publication_runtime,
    state_laws_local_release,
    state_laws_production_orchestrator,
    state_laws_publication_package,
    state_laws_publication_policy,
)
from ipfs_datasets_py.processors.legal_data.legal_source_rights_policy import (
    DEFAULT_QUARANTINED_CONTENT_SCOPES,
    STATE_STATUTORY_TEXT_RIGHTS_BASIS,
)
from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
)
from ipfs_datasets_py.processors.legal_data.state_laws_local_release import (
    MANIFEST_PATH,
    REQUIRED_INDEX_PATHS,
)
from ipfs_datasets_py.processors.legal_data.state_laws_publication_package import (
    STATE_LAWS_PLAN_SCHEMA,
    STATE_LAWS_RECEIPT_SCHEMA,
    StateLawsLivePolicyProof,
    StateLawsPublicationPackageError,
    materialize_state_laws_canonical_controls,
    plan_state_laws_publication_dry_run,
    prepare_state_laws_publication_package,
    require_state_laws_policy_binding,
    verify_state_laws_live_policy_proof,
    verify_state_laws_publication_package_identity,
)
from ipfs_datasets_py.processors.legal_data.state_laws_publication_policy import (
    DEFAULT_DATASET_REPO_ID,
    PREVIOUS_PUBLIC_PIN,
    example_authorized_main_request,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    RELEASE_PROFILE,
    SOURCE_RIGHTS_RECEIPT_RELPATH,
    SourceAuthorityClass,
    SourceReceiptRecord,
    VerificationResult,
    digest_mapping,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    SCHEMA_VERSION as RELEASE_SCHEMA_VERSION,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import write_zstd_parquet
from ipfs_datasets_py.retrieval.hf_graphrag.schema import canonical_json_bytes
from ipfs_datasets_py.retrieval.hf_graphrag.streaming_bm25 import (
    digest_sorted_bm25_term_statistics,
)

_FIXTURE_BM25_SEMANTIC_PROOF = {
    "document_count": 51,
    "document_semantics_sha256": "a" * 64,
    "posting_count": 1,
    "posting_semantics_sha256": "b" * 64,
    "term_count": 1,
    "term_statistics_sha256": "c" * 64,
    "token_instance_count": 51,
}

class _WriteTrackingApi:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def repo_info(self, **kwargs):
        self.calls.append("repo_info")
        return {"sha": "0" * 40}

    def get_paths_info(self, **kwargs):
        self.calls.append("get_paths_info")
        return []

    def create_commit(self, **kwargs):
        self.calls.append("create_commit")
        for operation in kwargs.get("operations") or ():
            handle = getattr(operation, "path_or_fileobj", None)
            assert handle is not None and not handle.closed
            handle.seek(0)
            assert handle.read()
            handle.seek(0)
        return {"commit_sha": "a" * 40}

    def auth_check(self, **kwargs):
        self.calls.append("auth_check")

    def whoami(self, **kwargs):
        self.calls.append("whoami")
        return {"name": "state-laws-test-principal"}

    def upload_file(self, **kwargs):
        self.calls.append("upload_file")
        raise AssertionError("dry-run must not upload")

    def delete_file(self, **kwargs):
        self.calls.append("delete_file")
        raise AssertionError("publisher must never delete")


def _write_descriptor(
    root: Path,
    relative: str,
    family: str,
    *,
    rows: list[dict[str, object]] | None = None,
    json_payload: dict[str, object] | None = None,
    first_key: str | None = None,
    last_key: str | None = None,
    shard_id: int | None = None,
    metadata: dict[str, object] | None = None,
    schema_id: str = "state-laws-publication-package-fixture/v1",
) -> dict[str, object]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if rows is not None:
        write_zstd_parquet(path, rows)
        row_count = len(rows)
        media_type = "application/vnd.apache.parquet"
    elif json_payload is not None:
        path.write_bytes(canonical_json_bytes(json_payload) + b"\n")
        row_count = 1
        media_type = "application/json"
    else:
        raise AssertionError("fixture descriptor needs Parquet rows or a JSON object")
    body = path.read_bytes()
    descriptor: dict[str, object] = {
        "family": family,
        "media_type": media_type,
        "relative_path": relative,
        "row_count": row_count,
        "schema_id": schema_id,
        "sha256": sha256(body).hexdigest(),
        "size_bytes": len(body),
    }
    if first_key is not None:
        descriptor["first_key"] = first_key
    if last_key is not None:
        descriptor["last_key"] = last_key
    if shard_id is not None:
        descriptor["shard_id"] = shard_id
    if metadata is not None:
        descriptor["metadata"] = metadata
    return descriptor


def _materialize_local_release(
    root: Path,
    *,
    fixture_only: bool = True,
) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, object]] = []
    chunk_cid = "sha256:" + sha256(b"fixture-chunk").hexdigest()
    document_rows = [
        {"document_index": position, "fixture": f"document-{position}"}
        for position in range(len(CANONICAL_JURISDICTION_ORDER))
    ]
    bm25_document = _write_descriptor(
        root,
        "data/bm25/documents/part-000000.parquet",
        "bm25_documents",
        rows=document_rows,
        first_key="000000000000",
        last_key="000000000050",
        shard_id=0,
        metadata={"direct_columns": True},
    )
    posting_row = {
        "chunk_cids": [chunk_cid],
        "document_frequency": 1,
        "document_indices": [0],
        "entry_cids": [chunk_cid],
        "pointer_count": 1,
        "posting_chunk_count": 1,
        "posting_chunk_index": 0,
        "term": "law",
    }
    bm25_posting = _write_descriptor(
        root,
        "data/bm25/postings/part-000000.parquet",
        "bm25_postings",
        rows=[posting_row],
        first_key="law",
        last_key="law",
        shard_id=0,
        metadata={"direct_columns": True, "pointer_count": 1, "term_count": 1},
    )
    artifacts.extend((bm25_document, bm25_posting))
    family_paths = {
        "corpus": "data/corpus/part-000000.parquet",
        "vectors": "data/vectors/part-000000.parquet",
        "centroids": "data/vectors/centroids.parquet",
        "graph_nodes": "data/graph/nodes/part-000000.parquet",
        "graph_edges": "data/graph/edges/part-000000.parquet",
        "graph_adjacency_out": "data/graph/adjacency/out/part-000000.parquet",
        "graph_adjacency_in": "data/graph/adjacency/in/part-000000.parquet",
    }
    for family, relative in family_paths.items():
        artifacts.append(
            _write_descriptor(
                root,
                relative,
                family,
                rows=[{"fixture": f"{family}-row"}],
            )
        )

    source_receipts: list[dict[str, object]] = []
    for code in CANONICAL_JURISDICTION_ORDER:
        checksum = sha256(f"fixture-source:{code}".encode()).hexdigest()
        receipt = SourceReceiptRecord(
            receipt_id=f"scrape-{code.lower()}-sealed",
            jurisdiction=code,
            official_source_url=f"https://legislature.{code.lower()}.gov/code",
            release_point="state-laws-publication-package-fixture-2026-08-24",
            observation_time="2026-08-24T00:00:00Z",
            source_authority_class=SourceAuthorityClass.OFFICIAL,
            source_checksum=checksum,
            verification_result=VerificationResult.VERIFIED,
            discovered=1,
            fetched=1,
            excluded=0,
            quarantined=0,
            failed_final=0,
            frontier_closed=True,
            relative_path=f"receipts/scrape/{code.lower()}.json",
            start_urls=(f"https://legislature.{code.lower()}.gov/code",),
            content_hashes=(checksum,),
            payload={
                "adapter_input_row_count": 1,
                "admission_eligible": True,
                "qualification_reasons": [],
                "reported_canonical_row_count": 1,
            },
        )
        descriptor = _write_descriptor(
            root,
            receipt.relative_path,
            "receipt",
            json_payload=receipt.to_dict(),
            first_key=receipt.receipt_id,
            last_key=receipt.receipt_id,
            metadata={
                "jurisdiction_code": code,
                "receipt_kind": "source_receipt",
            },
            schema_id=receipt.schema_version,
        )
        source_receipts.append(descriptor)
        artifacts.append(descriptor)

    term_proof = digest_sorted_bm25_term_statistics((("law", 1),))
    vocabulary_sha = term_proof.vocabulary_sha256
    document_frequency_sha = term_proof.document_frequency_sha256
    bm25_config_digest = sha256(b"fixture-bm25-config").hexdigest()
    bm25_root_cid = sha256(b"fixture-bm25-root").hexdigest()
    catalog_digest = sha256(b"fixture-source-catalog").hexdigest()
    admitted_ids = [
        f"{code.lower()}-official-statutory-text"
        for code in CANONICAL_JURISDICTION_ORDER
    ]
    rights_payload: dict[str, object] = {
        "admitted_count": len(admitted_ids),
        "admitted_record_ids": admitted_ids,
        "authorizing_for_publication": not fixture_only,
        "catalog_digest_sha256": catalog_digest,
        "decisions": [
            {
                "admitted": True,
                "authorizing": True,
                "content_scope": "statutory_text",
                "record_id": record_id,
                "rights_disposition": "allowed",
            }
            for record_id in admitted_ids
        ],
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "evidence_mode": "fixture" if fixture_only else "live",
        "fixture_only_non_authorizing": fixture_only,
        "mode": "fixture" if fixture_only else "live",
        "path": SOURCE_RIGHTS_RECEIPT_RELPATH,
        "prohibited_ids": [],
        "report_schema": "ipfs_datasets_py/legal-source-rights-compliance@2",
        "status": "passed",
        "unknown_ids": [],
    }
    rights_payload["report_digest_sha256"] = digest_mapping(rights_payload)
    rights_digest = str(rights_payload["report_digest_sha256"])
    rights_descriptor = _write_descriptor(
        root,
        SOURCE_RIGHTS_RECEIPT_RELPATH,
        "report",
        json_payload=rights_payload,
        first_key=rights_digest,
        last_key=rights_digest,
        metadata={
            "receipt_digest": rights_digest,
            "receipt_kind": "source_rights_receipt",
        },
        schema_id=str(rights_payload["report_schema"]),
    )
    artifacts.append(rights_descriptor)

    document_route = {
        "first_key": bm25_document["first_key"],
        "kind": "bm25_documents",
        "last_key": bm25_document["last_key"],
        "relative_path": bm25_document["relative_path"],
        "row_count": bm25_document["row_count"],
        "schema_version": "compact-index-fixture/v1",
        "sha256": bm25_document["sha256"],
        "shard_id": 0,
        "size_bytes": bm25_document["size_bytes"],
        "start_document_index": 0,
        "end_document_index": 50,
        "document_count": 51,
    }
    posting_route = {
        "first_key": bm25_posting["first_key"],
        "kind": "bm25_postings",
        "last_key": bm25_posting["last_key"],
        "relative_path": bm25_posting["relative_path"],
        "row_count": bm25_posting["row_count"],
        "schema_version": "compact-index-fixture/v1",
        "sha256": bm25_posting["sha256"],
        "shard_id": 0,
        "size_bytes": bm25_posting["size_bytes"],
        "posting_count": 1,
        "term_count": 1,
    }
    indexes: dict[str, dict[str, object]] = {}
    for name, relative in REQUIRED_INDEX_PATHS.items():
        family = "locator_index" if name == "vector_chunks" else "routing_index"
        if name == "bm25_document_chunks":
            rows = [document_route]
        elif name == "bm25_keyword_shards":
            rows = [posting_route]
        else:
            rows = [{"fixture": f"{name}-route"}]
        descriptor = _write_descriptor(root, relative, family, rows=rows)
        artifacts.append(descriptor)
        indexes[name] = descriptor

    artifacts.sort(key=lambda item: str(item["relative_path"]))
    payload: dict[str, object] = {
        "artifacts": artifacts,
        "bm25": {
            "canonical_chunk_artifact_digest": indexes["corpus_chunks"]["sha256"],
            "config_digest": bm25_config_digest,
            "document_frequency_sha256": document_frequency_sha,
            "index_root_cid": bm25_root_cid,
            "physical_vocabulary_proof": {
                "document_frequency_sha256": document_frequency_sha,
                "keyword_index_path": REQUIRED_INDEX_PATHS["bm25_keyword_shards"],
                "posting_glob": "data/bm25/postings/*.parquet",
                "posting_rows_are_lexicographic": True,
                "vocabulary_sha256": vocabulary_sha,
            },
            "vocabulary_sha256": vocabulary_sha,
        },
        "build_config_cid": sha256(b"fixture-build-config").hexdigest(),
        "counts": {
            "bm25_documents": 51,
            "bm25_keyword_shards": 1,
            "bm25_posting_rows": 1,
            "bm25_postings": 1,
            "bm25_terms": 1,
            "corpus_documents": 51,
        },
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "fixture_only": fixture_only,
        "graph": {
            "checks": {
                "bm25_neighbors_non_authoritative": True,
                "bm25_physical_vocabulary_proof": True,
                "direct_parquet_columns": True,
                "edge_identities_exact": True,
                "endpoint_integrity": True,
                "node_identities_exact": True,
                "optional_bm25_neighbors_production_ready": True,
                "term_document_edges_not_materialized": True,
                "two_way_adjacency_required": True,
            },
            "vocabulary_parity": {
                "bm25_config_digest": bm25_config_digest,
                "bm25_document_frequencies_match_physical_postings_exactly": True,
                "bm25_vocabulary_matches_overlay_exactly": True,
                "bm25_vocabulary_matches_physical_postings_exactly": True,
                "document_count": 51,
                "document_frequency_sha256": document_frequency_sha,
                "durable_term_document_edge_count": 0,
                "evidence_source": "streaming_physical_postings",
                "full_term_document_expansion_performed": False,
                "index_root_cid": bm25_root_cid,
                "optional_neighbor_edges_production_ready": True,
                "postings_parity_asserted": True,
                "production_ready": True,
                "term_count": 1,
                "term_document_pair_count": 1,
                "vocabulary_sha256": vocabulary_sha,
            },
        },
        "graph_ontology_version": "state-laws-ontology-fixture-v1",
        "indexes": indexes,
        "jurisdictions": list(CANONICAL_JURISDICTION_ORDER),
        "max_adjacency_pointers_per_row": 4096,
        "max_posting_pointers_per_row": 4096,
        "max_rows_per_physical_shard": 4096,
        "max_rows_per_vector_centroid": 4096,
        "max_vector_shards_per_centroid": 4096,
        "model_id": DEFAULT_EMBEDDING_MODEL_ID,
        "model_revision": DEFAULT_EMBEDDING_MODEL_REVISION,
        "package_version": "2",
        "release_control": {
            "authorizes_hub_upload": False,
            "authorizes_publication": False,
            "fail_closed": True,
            "local_staging_only": True,
            "network_io_performed": False,
            "publication_action_performed": False,
        },
        "release_point": (
            "state-laws-publication-package-fixture-2026-08-24"
            if fixture_only
            else "state-laws-production-2026-08-24"
        ),
        "release_profile": RELEASE_PROFILE,
        "schema_version": RELEASE_SCHEMA_VERSION,
        "source_revision": "4d62373051f2436296eb123d8c28819a91ea460a",
        "source_provenance_verifier": (
            state_laws_local_release.state_laws_source_provenance_verifier_attestation()
        ),
        "source_receipts": source_receipts,
        "source_rights_catalog_digest": catalog_digest,
        "source_rights_receipt": {
            "admitted_record_count": 51,
            "admitted_record_ids": admitted_ids,
            "catalog_digest_sha256": catalog_digest,
            "excluded_content_scopes": sorted(
                scope.value for scope in DEFAULT_QUARANTINED_CONTENT_SCOPES
            ),
            "prohibited_and_unknown_excluded_from_default": True,
            "receipt_digest": rights_digest,
            "relative_path": SOURCE_RIGHTS_RECEIPT_RELPATH,
            "status": "passed",
            "statutory_text_rights_basis": STATE_STATUTORY_TEXT_RIGHTS_BASIS,
        },
        "source_rights_receipt_digest": rights_digest,
        "source_rights_receipt_path": SOURCE_RIGHTS_RECEIPT_RELPATH,
        "tokenizer_id": "state-laws-bm25-tokenizer-fixture-v1",
        "validation": {
            **state_laws_local_release._bm25_semantic_attestation(
                _FIXTURE_BM25_SEMANTIC_PROOF
            ),
            "bm25_vocabulary_lexical_graph_exact": True,
            "default_jurisdiction_count": 51,
            "descriptor_bytes_verified": True,
            "no_quarantine": True,
            "official_source_receipt_count": 51,
            "source_provenance_verifier_current": True,
            "status": "passed",
            "term_document_edges_materialized": False,
        },
        "vector": {
            "dimension": DEFAULT_EMBEDDING_DIMENSION,
            "model_id": DEFAULT_EMBEDDING_MODEL_ID,
            "model_revision": DEFAULT_EMBEDDING_MODEL_REVISION,
            "production_ready": True,
            "projection_embeddings": False,
            "real_inference": True,
            "source_production_ready": True,
        },
        "vector_space_id": "state-laws-gte-small-fixture-space",
    }
    (root / MANIFEST_PATH).write_bytes(canonical_json_bytes(payload) + b"\n")
    return payload


def _descriptor_surfaces(
    payload: dict[str, object], relative_path: str
) -> list[dict[str, object]]:
    surfaces: list[dict[str, object]] = []
    for value in payload["artifacts"]:
        if value.get("relative_path") == relative_path:
            surfaces.append(value)
    for value in payload["indexes"].values():
        if value.get("relative_path") == relative_path:
            surfaces.append(value)
    for value in payload["source_receipts"]:
        if value.get("relative_path") == relative_path:
            surfaces.append(value)
    unique: list[dict[str, object]] = []
    seen: set[int] = set()
    for value in surfaces:
        if id(value) not in seen:
            unique.append(value)
            seen.add(id(value))
    return unique


def _rebind_file_bytes(
    root: Path,
    payload: dict[str, object],
    relative_path: str,
    body: bytes,
) -> None:
    (root / relative_path).write_bytes(body)
    for descriptor in _descriptor_surfaces(payload, relative_path):
        descriptor["sha256"] = sha256(body).hexdigest()
        descriptor["size_bytes"] = len(body)
    (root / MANIFEST_PATH).write_bytes(canonical_json_bytes(payload) + b"\n")


@pytest.fixture(autouse=True)
def _stub_authoritative_live_rights(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep package-shape tests independent of expiring live observations."""

    def verifier(value):
        return dict(value)

    monkeypatch.setattr(
        state_laws_local_release, "require_live_source_rights_receipt", verifier
    )
    monkeypatch.setattr(
        state_laws_publication_package,
        "require_live_source_rights_receipt",
        verifier,
    )

    # This fixture deliberately uses tiny, shape-only Parquet rows rather
    # than the canonical chunk/BM25 schemas.  Keep the pre-existing physical
    # closure check for these package-shape tests; canonical semantic forgery
    # coverage lives in test_state_laws_local_release.py with real writers.
    def semantic_verifier(root, *, payload, descriptors):
        state_laws_local_release._verify_completed_bm25_physical_closure(
            root,
            payload=payload,
            descriptors=descriptors,
        )
        return dict(_FIXTURE_BM25_SEMANTIC_PROOF)

    monkeypatch.setattr(
        state_laws_local_release,
        "_verify_completed_bm25_semantics",
        semantic_verifier,
    )

@pytest.fixture
def local_release(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "release"
    return root, _materialize_local_release(root, fixture_only=False)


def _sealed_live_policy_fixture(root: Path):
    dry_run = plan_state_laws_publication_dry_run(
        root,
        audited_parent_commit="0" * 40,
    )
    request = example_authorized_main_request(
        manifest_digest=dry_run.package.manifest_digest
    )
    proof = require_state_laws_policy_binding(
        dry_run.package,
        request,
        plan=dry_run.plan,
        environ={},
    )
    approval = PublicationApproval(
        approver="state-laws-ops",
        plan_digest=dry_run.plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=int(dry_run.plan.cost_receipt["upload_bytes"]),
        credentials_scope=f"dataset:write:{DEFAULT_DATASET_REPO_ID}",
        approval_id="state-laws-policy-proof-test",
    )
    return dry_run, proof, approval


def test_canonical_controls_reach_real_runtime_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.unit.processors.legal_data.test_legal_corpora_publication_runtime import (
        _git,
        _request,
        _seed_repo,
    )

    release_root = tmp_path / "verified-release"
    _materialize_local_release(release_root, fixture_only=False)
    dry_run, proof, _ = _sealed_live_policy_fixture(release_root)

    canonical_root = _seed_repo(tmp_path / "runtime", "state_main")
    canonical_rights = canonical_root / SOURCE_RIGHTS_RECEIPT_RELPATH
    canonical_rights.write_bytes(
        (release_root / SOURCE_RIGHTS_RECEIPT_RELPATH).read_bytes()
    )
    bundle = materialize_state_laws_canonical_controls(
        dry_run.package,
        dry_run.plan,
        proof,
        repository_root=canonical_root,
        sealed_at="2020-01-01T00:00:00Z",
    )
    first_control_bytes = {
        path: (canonical_root / path).read_bytes()
        for path in (
            bundle.candidate_path,
            bundle.dataset_card_path,
            bundle.seal_path,
        )
    }
    repeated = materialize_state_laws_canonical_controls(
        dry_run.package,
        dry_run.plan,
        proof,
        repository_root=canonical_root,
        sealed_at="2020-01-01T00:00:00Z",
    )
    assert repeated == bundle
    assert first_control_bytes == {
        path: (canonical_root / path).read_bytes()
        for path in first_control_bytes
    }
    assert not list(canonical_root.rglob("*.tmp-*"))
    assert bundle.release_manifest_digest == dry_run.plan.release_sha256
    assert bundle.source_rights_receipt_digest == json.loads(
        canonical_rights.read_text(encoding="utf-8")
    )["report_digest_sha256"]
    candidate = json.loads(
        (canonical_root / bundle.candidate_path).read_text(encoding="utf-8")
    )
    assert candidate["schema"] == (
        legal_corpora_publication_runtime.MANIFEST_SCHEMA_V1
    )
    assert candidate["manifest_digest"] == dry_run.plan.release_sha256
    assert candidate["canonical_digest"] == bundle.candidate_manifest_digest

    _git(canonical_root, "add", "-A")
    _git(canonical_root, "commit", "-m", "canonical State controls")
    request = _request(
        canonical_root,
        "state_main",
        extra={
            "expected_dataset_repo_id": dry_run.plan.repository_id,
            "expected_plan_digest": dry_run.plan.plan_digest,
            "expected_policy_proof_digest": proof.proof_digest,
            "expected_release_manifest_digest": (
                dry_run.plan.release_sha256
            ),
        },
    )
    calls: list[object] = []

    def callback(decision):
        calls.append(decision)
        return decision

    decision = (
        legal_corpora_publication_runtime.authorize_and_mutate_canonical(
            request,
            callback,
        )
    )
    assert len(calls) == 1
    assert decision.final_manifest_digest == bundle.candidate_manifest_digest
    assert decision.details["candidate_release_manifest_digest"] == (
        dry_run.plan.release_sha256
    )
    assert decision.details["expected_plan_digest"] == dry_run.plan.plan_digest


def test_canonical_controls_refuse_fixture_release(
    tmp_path: Path,
) -> None:
    root = tmp_path / "fixture-release"
    _materialize_local_release(root, fixture_only=True)
    dry_run, proof, _ = _sealed_live_policy_fixture(root)
    canonical_root = tmp_path / "canonical"
    (canonical_root / SOURCE_RIGHTS_RECEIPT_RELPATH).parent.mkdir(
        parents=True,
    )
    (canonical_root / SOURCE_RIGHTS_RECEIPT_RELPATH).write_bytes(
        (root / SOURCE_RIGHTS_RECEIPT_RELPATH).read_bytes()
    )
    with pytest.raises(StateLawsPublicationPackageError, match="fixture"):
        materialize_state_laws_canonical_controls(
            dry_run.package,
            dry_run.plan,
            proof,
            repository_root=canonical_root,
            sealed_at="2020-01-01T00:00:00Z",
        )


def test_canonical_controls_refuse_nonauthorizing_proof(
    local_release: tuple[Path, dict[str, object]],
    tmp_path: Path,
) -> None:
    root, _ = local_release
    dry_run, proof, _ = _sealed_live_policy_fixture(root)
    decision = dict(proof.decision)
    decision["authorized"] = False
    forged = replace(
        proof,
        decision=decision,
        decision_digest=sha256(canonical_json_bytes(decision)).hexdigest(),
        proof_digest="",
    )
    with pytest.raises(
        StateLawsPublicationPackageError,
        match="decision|authorized",
    ):
        materialize_state_laws_canonical_controls(
            dry_run.package,
            dry_run.plan,
            forged,
            repository_root=tmp_path,
            sealed_at="2020-01-01T00:00:00Z",
        )


def test_atomic_canonical_control_writer_rejects_symlink_targets(
    tmp_path: Path,
) -> None:
    relative = (
        legal_corpora_publication_runtime.STATE_CANDIDATE_MANIFEST_RELPATH
    )
    root = tmp_path / "root"
    target = root / relative
    target.parent.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"outside")
    target.symlink_to(outside)
    with pytest.raises(StateLawsPublicationPackageError, match="regular file"):
        state_laws_publication_package._atomic_write_canonical_controls(
            root,
            {relative: b"replacement"},
        )
    assert outside.read_bytes() == b"outside"
    assert target.is_symlink()

    parent_root = tmp_path / "parent-root"
    outside_directory = tmp_path / "outside-directory"
    outside_directory.mkdir()
    parent_root.mkdir()
    (parent_root / "docs").symlink_to(outside_directory, target_is_directory=True)
    with pytest.raises(
        StateLawsPublicationPackageError,
        match="parent.*symlink",
    ):
        state_laws_publication_package._atomic_write_canonical_controls(
            parent_root,
            {relative: b"replacement"},
        )
    assert list(outside_directory.iterdir()) == []


def test_publication_package_replays_final_authoritative_live_rights_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "release"
    _materialize_local_release(root)

    def reject(_value):
        raise ValueError("stale policy_module_sha256")

    monkeypatch.setattr(
        state_laws_publication_package,
        "require_live_source_rights_receipt",
        reject,
    )
    with pytest.raises(
        StateLawsPublicationPackageError,
        match="final live verification.*policy_module",
    ):
        prepare_state_laws_publication_package(root)


def test_package_preserves_descriptors_and_exact_manifest_bytes(
    local_release: tuple[Path, dict[str, object]],
) -> None:
    root, payload = local_release
    before = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }

    package = prepare_state_laws_publication_package(root)
    publisher_manifest = package.to_publisher_manifest()
    by_path = {
        str(item["relative_path"]): item
        for item in publisher_manifest["descriptors"]
    }
    original = {
        str(item["relative_path"]): item for item in payload["artifacts"]
    }
    assert set(by_path) == set(original) | {MANIFEST_PATH}
    assert by_path[SOURCE_RIGHTS_RECEIPT_RELPATH]["family"] == "report"
    for relative, descriptor in original.items():
        assert by_path[relative] == descriptor

    manifest_bytes = (root / MANIFEST_PATH).read_bytes()
    assert by_path[MANIFEST_PATH]["sha256"] == sha256(manifest_bytes).hexdigest()
    assert by_path[MANIFEST_PATH]["size_bytes"] == len(manifest_bytes)
    assert package.manifest_digest == digest_mapping(payload)
    assert package.release_id == f"sha256-{digest_mapping(payload)}"
    assert package.manifest_file_sha256 != package.manifest_digest

    after = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_publication_verifier_rejects_syntactically_valid_wrong_release_id(
    local_release: tuple[Path, dict[str, object]],
) -> None:
    root, _ = local_release
    package = prepare_state_laws_publication_package(root)
    wrong_release_id = "sha256-" + "e" * 64
    assert wrong_release_id != package.release_id
    forged = replace(package, release_id=wrong_release_id)

    with pytest.raises(
        StateLawsPublicationPackageError,
        match="release_id does not match.*manifest digest",
    ):
        verify_state_laws_publication_package_identity(forged)
    with pytest.raises(StateLawsPublicationPackageError, match="release_id"):
        forged.to_publisher_manifest()


def test_publication_verifier_rejects_manifest_path_swap_after_packaging(
    local_release: tuple[Path, dict[str, object]],
) -> None:
    root, payload = local_release
    package = prepare_state_laws_publication_package(root)
    swapped = deepcopy(payload)
    swapped["release_point"] = "adversarial-path-swap"
    assert digest_mapping(swapped) != package.manifest_digest
    (root / MANIFEST_PATH).write_bytes(canonical_json_bytes(swapped) + b"\n")

    with pytest.raises(
        StateLawsPublicationPackageError,
        match="manifest content identity does not match",
    ):
        verify_state_laws_publication_package_identity(package)
    with pytest.raises(StateLawsPublicationPackageError):
        package.to_publisher_manifest()


def test_adapter_reuses_shared_release_verifier_and_generic_publisher() -> None:
    adapter_source = inspect.getsource(state_laws_publication_package)
    orchestrator_source = inspect.getsource(state_laws_production_orchestrator)

    assert "verify_state_laws_local_release_manifest(output_root)" in adapter_source
    assert "HuggingFaceReleasePublisher(profile=profile" in adapter_source
    assert "verify_state_laws_local_release_manifest(root)" in orchestrator_source
    for duplicated_builder in (
        "write_state_laws_bm25_physical_layout",
        "write_state_laws_vector_physical_layout",
        "write_state_laws_streaming_graph_layout",
        "state_laws_hf_release",
        "embeddings_router",
    ):
        assert duplicated_builder not in adapter_source


def test_dry_run_is_deterministic_and_never_contacts_write_api(
    local_release: tuple[Path, dict[str, object]],
) -> None:
    root, _ = local_release
    api = _WriteTrackingApi()
    first = plan_state_laws_publication_dry_run(root, api=api)
    second = plan_state_laws_publication_dry_run(root, api=api)

    assert first.plan.to_dict() == second.plan.to_dict()
    assert first.plan.schema_version == STATE_LAWS_PLAN_SCHEMA
    assert first.receipt["schema_version"] == STATE_LAWS_RECEIPT_SCHEMA
    assert first.plan.release_id == first.package.release_id
    assert first.plan.release_sha256 == first.package.manifest_digest
    assert first.plan.repository_id == DEFAULT_DATASET_REPO_ID
    assert first.plan.release_prefix.startswith("data/state_laws/sha256-")
    assert first.receipt["remote_write_performed"] is False
    assert first.to_dict()["physical_artifacts_reencoded"] is False
    assert first.to_dict()["network_io_performed"] is False
    assert api.calls == []


def test_package_fails_closed_on_artifact_or_manifest_drift(
    local_release: tuple[Path, dict[str, object]],
) -> None:
    root, payload = local_release
    artifact_path = root / str(payload["artifacts"][0]["relative_path"])
    artifact_path.write_bytes(artifact_path.read_bytes() + b"drift")
    with pytest.raises(StateLawsPublicationPackageError, match="differs"):
        prepare_state_laws_publication_package(root)


def test_package_rejects_digest_bound_text_masquerading_as_parquet(
    tmp_path: Path,
) -> None:
    root = tmp_path / "fake-parquet"
    payload = _materialize_local_release(root)
    relative = "data/vectors/part-000000.parquet"
    _rebind_file_bytes(root, payload, relative, b"arbitrary text, not parquet\n")

    with pytest.raises(
        StateLawsPublicationPackageError,
        match="Parquet integrity|Parquet magic",
    ):
        prepare_state_laws_publication_package(root)


def test_package_reopens_and_recomputes_bm25_posting_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bm25-semantic-drift"
    payload = _materialize_local_release(root)
    relative = "data/bm25/postings/part-000000.parquet"
    chunk_cid = "sha256:" + sha256(b"fixture-chunk").hexdigest()
    write_zstd_parquet(
        root / relative,
        [
            {
                "chunk_cids": [chunk_cid],
                "document_frequency": 1,
                "document_indices": [0],
                "entry_cids": [chunk_cid],
                "pointer_count": 1,
                "posting_chunk_count": 1,
                "posting_chunk_index": 0,
                "term": "unsealed-term",
            }
        ],
    )
    _rebind_file_bytes(root, payload, relative, (root / relative).read_bytes())

    with pytest.raises(
        StateLawsPublicationPackageError,
        match="BM25 posting descriptor|BM25 vocabulary/posting",
    ):
        prepare_state_laws_publication_package(root)


def test_package_rejects_malformed_and_jurisdiction_mismatched_receipt_json(
    tmp_path: Path,
) -> None:
    root = tmp_path / "malformed-receipt"
    payload = _materialize_local_release(root)
    relative = "receipts/scrape/ak.json"
    _rebind_file_bytes(root, payload, relative, b"this is not JSON\n")
    with pytest.raises(StateLawsPublicationPackageError, match="not valid JSON"):
        prepare_state_laws_publication_package(root)

    root = tmp_path / "jurisdiction-mismatch"
    payload = _materialize_local_release(root)
    receipt_path = root / relative
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["jurisdiction"] = "AL"
    _rebind_file_bytes(
        root,
        payload,
        relative,
        canonical_json_bytes(receipt) + b"\n",
    )
    with pytest.raises(
        StateLawsPublicationPackageError,
        match="jurisdiction mismatch",
    ):
        prepare_state_laws_publication_package(root)


def test_package_rejects_source_receipt_identity_not_bound_by_descriptor(
    tmp_path: Path,
) -> None:
    root = tmp_path / "receipt-identity-mismatch"
    payload = _materialize_local_release(root)
    relative = "receipts/scrape/ak.json"
    receipt_path = root / relative
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["receipt_id"] = "unrelated-admitted-receipt"
    _rebind_file_bytes(
        root,
        payload,
        relative,
        canonical_json_bytes(receipt) + b"\n",
    )
    with pytest.raises(
        StateLawsPublicationPackageError,
        match="descriptor identity",
    ):
        prepare_state_laws_publication_package(root)


def test_package_requires_in_tree_rights_receipt_and_its_declared_digest(
    tmp_path: Path,
) -> None:
    root = tmp_path / "missing-rights"
    _materialize_local_release(root)
    (root / SOURCE_RIGHTS_RECEIPT_RELPATH).unlink()
    with pytest.raises(StateLawsPublicationPackageError, match="differs|lacks"):
        prepare_state_laws_publication_package(root)

    root = tmp_path / "rights-digest-mismatch"
    payload = _materialize_local_release(root)
    rights_path = root / SOURCE_RIGHTS_RECEIPT_RELPATH
    rights = json.loads(rights_path.read_text(encoding="utf-8"))
    rights["report_digest_sha256"] = "0" * 64
    _rebind_file_bytes(
        root,
        payload,
        SOURCE_RIGHTS_RECEIPT_RELPATH,
        canonical_json_bytes(rights) + b"\n",
    )
    with pytest.raises(
        StateLawsPublicationPackageError,
        match="declared digest",
    ):
        prepare_state_laws_publication_package(root)


def test_package_rejects_unrelated_rights_admission_ids(tmp_path: Path) -> None:
    root = tmp_path / "unrelated-rights-admission"
    payload = _materialize_local_release(root)
    rights_path = root / SOURCE_RIGHTS_RECEIPT_RELPATH
    rights = json.loads(rights_path.read_text(encoding="utf-8"))
    rights.pop("report_digest_sha256")
    rights["admitted_record_ids"].append("unrelated-source-statutory-text")
    rights["decisions"].append(
        {
            "admitted": True,
            "authorizing": True,
            "content_scope": "statutory_text",
            "record_id": "unrelated-source-statutory-text",
            "rights_disposition": "allowed",
        }
    )
    rights["admitted_count"] = len(rights["admitted_record_ids"])
    rights["report_digest_sha256"] = digest_mapping(rights)
    rights_digest = rights["report_digest_sha256"]
    for descriptor in _descriptor_surfaces(payload, SOURCE_RIGHTS_RECEIPT_RELPATH):
        descriptor["first_key"] = rights_digest
        descriptor["last_key"] = rights_digest
        descriptor["metadata"]["receipt_digest"] = rights_digest
    payload["source_rights_receipt"]["receipt_digest"] = rights_digest
    payload["source_rights_receipt_digest"] = rights_digest
    _rebind_file_bytes(
        root,
        payload,
        SOURCE_RIGHTS_RECEIPT_RELPATH,
        canonical_json_bytes(rights) + b"\n",
    )
    with pytest.raises(
        StateLawsPublicationPackageError,
        match="unrelated admitted IDs",
    ):
        prepare_state_laws_publication_package(root)


def test_package_fails_closed_on_exact_51_and_rights_binding_drift(
    tmp_path: Path,
) -> None:
    root = tmp_path / "jurisdiction-drift"
    payload = _materialize_local_release(root)
    drifted = deepcopy(payload)
    drifted["jurisdictions"] = list(CANONICAL_JURISDICTION_ORDER[:-1])
    (root / MANIFEST_PATH).write_bytes(canonical_json_bytes(drifted) + b"\n")
    with pytest.raises(
        StateLawsPublicationPackageError,
        match="exact 51|exact-51|jurisdiction",
    ):
        prepare_state_laws_publication_package(root)

    root = tmp_path / "rights-drift"
    payload = _materialize_local_release(root)
    drifted = deepcopy(payload)
    drifted["source_rights_receipt_digest"] = sha256(b"drift").hexdigest()
    (root / MANIFEST_PATH).write_bytes(canonical_json_bytes(drifted) + b"\n")
    with pytest.raises(
        StateLawsPublicationPackageError,
        match="source-rights digest|receipt binding",
    ):
        prepare_state_laws_publication_package(root)


def test_live_policy_request_must_bind_the_exact_verified_package(
    local_release: tuple[Path, dict[str, object]],
) -> None:
    root, _ = local_release
    dry_run = plan_state_laws_publication_dry_run(root)
    package = dry_run.package
    assert package.policy_binding["final_manifest_digest"] == package.manifest_digest
    assert package.policy_binding["previous_public_pin"] == PREVIOUS_PUBLIC_PIN
    assert package.policy_binding["live_mutation_authorized"] is False
    assert package.policy_binding["remote_mutation_attempted"] is False

    request = example_authorized_main_request(
        manifest_digest=package.manifest_digest
    )
    proof = require_state_laws_policy_binding(
        package,
        request,
        plan=dry_run.plan,
        environ={},
    )
    assert proof.authorized is True
    assert proof.final_manifest_digest == package.manifest_digest
    assert proof.dataset_repo_id == DEFAULT_DATASET_REPO_ID
    assert proof.plan_digest == dry_run.plan.plan_digest

    drifted = dict(request)
    drifted["final_manifest_digest"] = sha256(b"different-manifest").hexdigest()
    with pytest.raises(StateLawsPublicationPackageError, match="not bound"):
        require_state_laws_policy_binding(
            package,
            drifted,
            plan=dry_run.plan,
            environ={},
        )


def test_live_policy_proof_roundtrip_and_generic_boundary(
    local_release: tuple[Path, dict[str, object]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.unit.processors.legal_data.test_legal_corpora_publication_runtime import (
        _git,
        _seed_repo,
    )

    root, _ = local_release
    dry_run, proof, approval = _sealed_live_policy_fixture(root)
    round_tripped = StateLawsLivePolicyProof.from_mapping(proof.to_dict())
    assert round_tripped.to_dict() == proof.to_dict()
    assert verify_state_laws_live_policy_proof(
        round_tripped,
        plan=dry_run.plan,
        profile=dry_run.profile,
        local_root=root,
    ).proof_digest == proof.proof_digest

    canonical_root = _seed_repo(tmp_path / "publisher-runtime", "state_main")
    (canonical_root / SOURCE_RIGHTS_RECEIPT_RELPATH).write_bytes(
        (root / SOURCE_RIGHTS_RECEIPT_RELPATH).read_bytes()
    )
    materialize_state_laws_canonical_controls(
        dry_run.package,
        dry_run.plan,
        round_tripped,
        repository_root=canonical_root,
        sealed_at="2020-01-01T00:00:00Z",
    )
    _git(canonical_root, "add", "-A")
    _git(canonical_root, "commit", "-m", "publisher canonical controls")

    real_publisher_source = Path(publisher_module.__file__).read_bytes()
    synthetic_publisher_path = (
        canonical_root / "ipfs_datasets_py/huggingface/publisher.py"
    )
    synthetic_publisher_path.parent.mkdir(parents=True)
    synthetic_publisher_path.write_bytes(real_publisher_source)
    monkeypatch.setattr(
        publisher_module,
        "__file__",
        str(synthetic_publisher_path),
    )
    for token_name in legal_corpora_publication_runtime.TOKEN_ENV_ALLOWLIST:
        monkeypatch.delenv(token_name, raising=False)
    monkeypatch.setenv("HF_TOKEN", "state-laws-synthetic-runtime-token")

    api = _WriteTrackingApi()
    commit = HuggingFaceReleasePublisher(
        profile=dry_run.profile,
        api=api,
    ).publish_append_only(
        dry_run.plan,
        approval=approval,
        local_root=root,
        live_policy_proof=round_tripped,
    )
    assert commit.plan_digest == dry_run.plan.plan_digest
    assert api.calls == [
        "auth_check",
        "whoami",
        "auth_check",
        "whoami",
        "repo_info",
        "get_paths_info",
        "get_paths_info",
        "create_commit",
    ]


def test_generic_state_laws_boundary_rejects_missing_forged_and_mismatched_proof(
    local_release: tuple[Path, dict[str, object]],
) -> None:
    root, _ = local_release
    dry_run, proof, approval = _sealed_live_policy_fixture(root)

    for bad_proof in (
        None,
        {
            **proof.to_dict(),
            "decision": {**proof.decision, "authorized": False},
        },
        StateLawsLivePolicyProof.from_mapping(
            {
                **proof.to_dict(),
                "repository_id": "justicedao/not-the-state-laws-repo",
                "proof_digest": "",
            }
        ),
    ):
        api = _WriteTrackingApi()
        with pytest.raises(HuggingFacePublicationError, match="policy proof|policy"):
            HuggingFaceReleasePublisher(
                profile=dry_run.profile,
                api=api,
            ).publish_append_only(
                dry_run.plan,
                approval=approval,
                local_root=root,
                live_policy_proof=bad_proof,
            )
        assert api.calls == []


def test_generic_state_laws_boundary_rejects_stale_plan_proof_before_api(
    local_release: tuple[Path, dict[str, object]],
) -> None:
    root, _ = local_release
    dry_run, proof, _ = _sealed_live_policy_fixture(root)
    advanced_plan = replace(dry_run.plan, audited_parent_commit="1" * 40)
    approval = PublicationApproval(
        approver="state-laws-ops",
        plan_digest=advanced_plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=int(advanced_plan.cost_receipt["upload_bytes"]),
        credentials_scope=f"dataset:write:{DEFAULT_DATASET_REPO_ID}",
        approval_id="state-laws-stale-proof-test",
    )
    api = _WriteTrackingApi()
    with pytest.raises(HuggingFacePublicationError, match="policy proof|policy"):
        HuggingFaceReleasePublisher(
            profile=dry_run.profile,
            api=api,
        ).publish_append_only(
            advanced_plan,
            approval=approval,
            local_root=root,
            live_policy_proof=proof,
        )
    assert api.calls == []


def test_generic_state_laws_boundary_rejects_fixture_drift_before_api(
    local_release: tuple[Path, dict[str, object]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = local_release
    fixture = tmp_path / "authorization.json"
    fixture.write_bytes(
        state_laws_publication_policy.default_authorization_fixture_path().read_bytes()
    )
    monkeypatch.setattr(
        state_laws_publication_policy,
        "DEFAULT_AUTHORIZATION_FIXTURE_RELATIVE_PATH",
        fixture,
    )
    dry_run, proof, approval = _sealed_live_policy_fixture(root)
    fixture.write_bytes(fixture.read_bytes() + b"\n")

    api = _WriteTrackingApi()
    with pytest.raises(HuggingFacePublicationError, match="fixture drifted"):
        HuggingFaceReleasePublisher(
            profile=dry_run.profile,
            api=api,
        ).publish_append_only(
            dry_run.plan,
            approval=approval,
            local_root=root,
            live_policy_proof=proof,
        )
    assert api.calls == []


def test_fresh_authorization_fixture_rejects_duplicate_json_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = tmp_path / "duplicate-authorization.json"
    fixture.write_text('{"schema":"first","schema":"second"}', encoding="utf-8")
    monkeypatch.setattr(
        state_laws_publication_policy,
        "DEFAULT_AUTHORIZATION_FIXTURE_RELATIVE_PATH",
        fixture,
    )
    with pytest.raises(StateLawsPublicationPackageError, match="duplicate JSON key"):
        state_laws_publication_package._fresh_policy_authorization()


def test_generic_state_laws_boundary_rejects_loaded_verifier_drift_before_api(
    local_release: tuple[Path, dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = local_release
    dry_run, proof, approval = _sealed_live_policy_fixture(root)
    original = state_laws_publication_policy.require_live_mutation

    def replaced_verifier(*args, **kwargs):
        return original(*args, **kwargs)

    monkeypatch.setattr(
        state_laws_publication_policy,
        "require_live_mutation",
        replaced_verifier,
    )
    api = _WriteTrackingApi()
    with pytest.raises(HuggingFacePublicationError, match="source|correspondence"):
        HuggingFaceReleasePublisher(
            profile=dry_run.profile,
            api=api,
        ).publish_append_only(
            dry_run.plan,
            approval=approval,
            local_root=root,
            live_policy_proof=proof,
        )
    assert api.calls == []


def test_live_policy_proof_rejects_tampered_nested_request(
    local_release: tuple[Path, dict[str, object]],
) -> None:
    root, _ = local_release
    _, proof, _ = _sealed_live_policy_fixture(root)
    payload = deepcopy(proof.to_dict())
    payload["request"]["jurisdictions"][0] = "ZZ"
    with pytest.raises(StateLawsPublicationPackageError, match="request digest"):
        StateLawsLivePolicyProof.from_mapping(payload)

    boundary_payload = deepcopy(proof.to_dict())
    boundary_payload["final_boundary_identity"]["dispatch"][
        "source_sha256"
    ] = "0" * 64
    with pytest.raises(
        StateLawsPublicationPackageError,
        match="boundary identity digest",
    ):
        StateLawsLivePolicyProof.from_mapping(boundary_payload)


def test_state_laws_plan_binding_rejects_duplicate_relative_operation(
    local_release: tuple[Path, dict[str, object]],
) -> None:
    root, _ = local_release
    dry_run = plan_state_laws_publication_dry_run(root)
    first = dry_run.plan.operations[0]
    duplicate = replace(
        first,
        remote_path=f"{dry_run.plan.release_prefix}/shadow/{first.relative_path}",
    )
    forged = replace(
        dry_run.plan,
        operations=(*dry_run.plan.operations, duplicate),
    )
    with pytest.raises(
        StateLawsPublicationPackageError,
        match="operations differ",
    ):
        state_laws_publication_package._verify_state_laws_plan_binding(
            dry_run.package,
            forged,
            dry_run.profile,
        )


def test_state_laws_plan_cannot_be_relabelled_through_patent_publisher(
    local_release: tuple[Path, dict[str, object]],
) -> None:
    root, _ = local_release
    dry_run = plan_state_laws_publication_dry_run(
        root,
        audited_parent_commit="0" * 40,
    )
    api = _WriteTrackingApi()
    relabelled = HuggingFaceReleasePublisher(
        profile=patent_legal_publication_profile(
            repository_id=DEFAULT_DATASET_REPO_ID
        ),
        api=api,
    )
    approval = PublicationApproval(
        approver="state-laws-ops",
        plan_digest=dry_run.plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=int(dry_run.plan.cost_receipt["upload_bytes"]),
        credentials_scope=f"dataset:write:{DEFAULT_DATASET_REPO_ID}",
        approval_id="state-laws-cross-profile-test",
    )
    with pytest.raises(HuggingFacePublicationError, match="exact publisher/profile"):
        relabelled.publish_append_only(
            dry_run.plan,
            approval=approval,
            local_root=root,
        )
    assert api.calls == []


def test_state_laws_final_boundary_rejects_monkeypatched_dispatch_and_verifier(
    local_release: tuple[Path, dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = local_release
    dry_run, proof, approval = _sealed_live_policy_fixture(root)
    mutations = (
        (
            state_laws_publication_package,
            "verify_state_laws_live_policy_proof",
            lambda *args, **kwargs: proof,
        ),
        (
            state_laws_publication_package._StateLawsLivePolicyProofVerifier,
            "current_executable_identities",
            classmethod(lambda cls: dict(cls.EXECUTABLE_IMPORT_SHA256)),
        ),
        (
            publisher_module._StateLawsLivePolicyBoundary,
            "verify",
            classmethod(lambda cls, *args, **kwargs: None),
        ),
        (
            publisher_module._StateLawsLivePolicyBoundary,
            "attest_target",
            staticmethod(lambda *args, **kwargs: proof.final_boundary_identity),
        ),
        (
            legal_corpora_publication_runtime,
            "capture_canonical_snapshot",
            lambda *args, **kwargs: {},
        ),
        (
            legal_corpora_publication_runtime,
            "evaluate_publication_gate",
            lambda *args, **kwargs: SimpleNamespace(authorized=True),
        ),
        (
            legal_corpora_publication_runtime._CanonicalPublicationRuntimeExecutable,
            "assert_current",
            classmethod(lambda cls: None),
        ),
    )
    for target, attribute, replacement in mutations:
        with monkeypatch.context() as patcher:
            patcher.setattr(target, attribute, replacement)
            api = _WriteTrackingApi()
            with pytest.raises(
                HuggingFacePublicationError,
                match="source|correspondence|identity|policy proof|runtime",
            ):
                HuggingFaceReleasePublisher(
                    profile=dry_run.profile,
                    api=api,
                ).publish_append_only(
                    dry_run.plan,
                    approval=approval,
                    local_root=root,
                    live_policy_proof=proof,
                )
            assert api.calls == []

    with monkeypatch.context() as patcher:
        patcher.setattr(
            legal_corpora_publication_runtime,
            "authorize_and_mutate_canonical",
            lambda request, callback: callback(
                SimpleNamespace(
                    authorized=True,
                    dataset_repo_id=DEFAULT_DATASET_REPO_ID,
                    final_manifest_digest="0" * 64,
                    network_mutation_permitted=True,
                    operation="additive_main_upload",
                    phase="state_main",
                    details={
                        "candidate_release_manifest_digest": "0" * 64,
                    },
                )
            ),
        )
        api = _WriteTrackingApi()
        with pytest.raises(
            HuggingFacePublicationError,
            match="canonical.*bound|runtime executable identity",
        ):
            HuggingFaceReleasePublisher(
                profile=dry_run.profile,
                api=api,
            ).publish_append_only(
                dry_run.plan,
                approval=approval,
                local_root=root,
                live_policy_proof=proof,
                )
        assert api.calls == []

    with monkeypatch.context() as patcher:
        patcher.setattr(
            legal_corpora_publication_runtime,
            "authorize_and_mutate_canonical",
            lambda request, callback: callback(
                SimpleNamespace(
                    authorized=True,
                    dataset_repo_id=DEFAULT_DATASET_REPO_ID,
                    final_manifest_digest="c" * 64,
                    network_mutation_permitted=True,
                    operation="additive_main_upload",
                    phase="state_main",
                    details={
                        "candidate_release_manifest_digest": (
                            dry_run.plan.release_sha256
                        ),
                    },
                )
            ),
        )
        api = _WriteTrackingApi()
        with pytest.raises(
            HuggingFacePublicationError,
            match="canonical.*runtime|must enter",
        ):
            HuggingFaceReleasePublisher(
                profile=dry_run.profile,
                api=api,
            ).publish_append_only(
                dry_run.plan,
                approval=approval,
                local_root=root,
                live_policy_proof=proof,
            )
        assert api.calls == []


def test_authorization_fixture_final_and_parent_symlinks_fail_before_api(
    local_release: tuple[Path, dict[str, object]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = local_release
    fixture_directory = tmp_path / "fixture-directory"
    fixture_directory.mkdir()
    fixture = fixture_directory / "authorization.json"
    fixture.write_bytes(
        state_laws_publication_policy.default_authorization_fixture_path().read_bytes()
    )
    monkeypatch.setattr(
        state_laws_publication_policy,
        "DEFAULT_AUTHORIZATION_FIXTURE_RELATIVE_PATH",
        fixture,
    )
    dry_run, proof, approval = _sealed_live_policy_fixture(root)

    final_target = tmp_path / "authorization-target.json"
    fixture.rename(final_target)
    fixture.symlink_to(final_target)
    api = _WriteTrackingApi()
    with pytest.raises(HuggingFacePublicationError, match="symlink"):
        HuggingFaceReleasePublisher(
            profile=dry_run.profile,
            api=api,
        ).publish_append_only(
            dry_run.plan,
            approval=approval,
            local_root=root,
            live_policy_proof=proof,
        )
    assert api.calls == []
    fixture.unlink()
    final_target.rename(fixture)

    outside_directory = tmp_path / "outside-fixture-directory"
    fixture_directory.rename(outside_directory)
    fixture_directory.symlink_to(outside_directory, target_is_directory=True)
    api = _WriteTrackingApi()
    with pytest.raises(HuggingFacePublicationError, match="symlink"):
        HuggingFaceReleasePublisher(
            profile=dry_run.profile,
            api=api,
        ).publish_append_only(
            dry_run.plan,
            approval=approval,
            local_root=root,
            live_policy_proof=proof,
        )
    assert api.calls == []


def test_package_refuses_noncanonical_manifest_bytes(
    local_release: tuple[Path, dict[str, object]],
) -> None:
    root, payload = local_release
    # Same JSON value, but pretty-printing would make the reviewed bytes differ
    # from the canonical local-release contract.
    (root / MANIFEST_PATH).write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    with pytest.raises(StateLawsPublicationPackageError, match="not canonical"):
        prepare_state_laws_publication_package(root)
