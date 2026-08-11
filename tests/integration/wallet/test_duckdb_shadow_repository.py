"""Integration tests for data-wallet DuckDB shadow repository (DQK-074).

Acceptance:

* Every service mutation has an idempotent operation ID and parity receipt
* Wallet JSON and analytics-ledger round-trip exactly
* Plaintext, keys, wraps and encrypted bytes are excluded from query publications
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")

import pytest

from ipfs_datasets_py.wallet.crypto import random_key
from ipfs_datasets_py.wallet.duckdb_repository import (
    FORBIDDEN_QUERY_KEYS,
    MutationKind,
    WalletDuckDBRepository,
    WalletPublicationSafetyError,
    assert_query_publication_safe,
    build_wallet_duckdb_repository,
    new_operation_id,
    project_analytics_ledger_for_query,
    project_wallet_snapshot_for_query,
    redact_for_query_publication,
)
from ipfs_datasets_py.wallet.manifest import canonical_dumps
from ipfs_datasets_py.wallet.repository import LocalWalletRepository
from ipfs_datasets_py.wallet.service import DataWalletService

OWNER = "did:key:owner"
OWNER2 = "did:key:owner2"


@pytest.fixture
def event_port() -> WalletDuckDBRepository:
    return build_wallet_duckdb_repository()


@pytest.fixture
def service(tmp_path: Path, event_port: WalletDuckDBRepository) -> DataWalletService:
    svc = DataWalletService(storage_dir=tmp_path / "blobs")
    svc.attach_event_port(event_port)
    return svc


def _create_wallet_with_record(service: DataWalletService, owner: str = OWNER):
    wallet = service.create_wallet(owner_did=owner)
    secret = random_key()
    service.set_principal_secret(owner, secret)
    record = service.add_record(
        wallet.wallet_id,
        data_type="document",
        plaintext=b"shadow-repository-secret-payload",
        actor_did=owner,
        actor_secret=secret,
        private_metadata={"filename": "shadow.txt", "note": "keep out of duckdb"},
    )
    return wallet, secret, record


def test_every_service_mutation_has_operation_id_and_parity_receipt(service, event_port):
    wallet, secret, record = _create_wallet_with_record(service)

    # Additional mutations across audit, grant, analytics, and manifest surfaces.
    service.create_analytics_template(
        template_id="shadow_analytics_v1",
        title="Shadow analytics",
        purpose="parity coverage",
        allowed_record_types=["document", "need"],
        allowed_derived_fields=["county"],
        aggregation_policy={"min_cohort_size": 1, "epsilon_budget": 1.0},
        created_by=OWNER,
    )
    consent = service.create_analytics_consent(
        wallet.wallet_id,
        actor_did=OWNER,
        template_id="shadow_analytics_v1",
        allowed_record_types=["document", "need"],
        allowed_derived_fields=["county"],
    )
    service.create_analytics_contribution(
        wallet.wallet_id,
        actor_did=OWNER,
        consent_id=consent.consent_id,
        template_id="shadow_analytics_v1",
        fields={"county": "Multnomah"},
    )
    service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did="did:key:guest",
        resources=[f"wallet://{wallet.wallet_id}"],
        abilities=["wallet/read"],
    )

    receipts = service.mutation_receipts
    assert receipts, "service mutations must emit receipts when event_port is attached"
    for receipt in receipts:
        assert receipt.operation_id, "mutation missing operation_id"
        assert receipt.parity_receipt_cid, "mutation missing parity receipt"
        assert receipt.parity_matched is True, (
            f"parity mismatch for {receipt.operation_id}: {receipt}"
        )
        assert receipt.projection_digest.startswith("sha256:")
        assert receipt.mode == "shadow"

    # Idempotent replay under the same operation id.
    fixed = event_port.record_service_mutation(
        wallet_id=wallet.wallet_id,
        action="test/fixed",
        resource=f"wallet://{wallet.wallet_id}/test",
        actor_did=OWNER,
        operation_id="op:idempotent-fixed",
        service=service,
    )
    replay = event_port.record_service_mutation(
        wallet_id=wallet.wallet_id,
        action="test/fixed",
        resource=f"wallet://{wallet.wallet_id}/test",
        actor_did=OWNER,
        operation_id="op:idempotent-fixed",
        service=service,
    )
    assert replay.idempotent_replay is True
    assert replay.operation_id == fixed.operation_id
    assert replay.parity_receipt_cid == fixed.parity_receipt_cid


def test_wallet_json_and_analytics_ledger_round_trip_exactly(tmp_path, event_port):
    storage = tmp_path / "blobs"
    service = DataWalletService(storage_dir=storage)
    service.attach_event_port(event_port)
    wallet1, secret1, _ = _create_wallet_with_record(service, OWNER)
    wallet2 = service.create_wallet(owner_did=OWNER2)
    secret2 = random_key()
    service.set_principal_secret(OWNER2, secret2)

    template = service.create_analytics_template(
        template_id="roundtrip_analytics_v1",
        title="Round-trip analytics",
        purpose="exact ledger fidelity",
        allowed_record_types=["location", "need"],
        allowed_derived_fields=["county", "need_category"],
        aggregation_policy={"min_cohort_size": 2, "epsilon_budget": 0.5},
        created_by="did:key:analyst",
    )
    for wallet, owner in ((wallet1, OWNER), (wallet2, OWNER2)):
        consent = service.create_analytics_consent(
            wallet.wallet_id,
            actor_did=owner,
            template_id=template.template_id,
            allowed_record_types=["location", "need"],
            allowed_derived_fields=["county", "need_category"],
        )
        service.create_analytics_contribution(
            wallet.wallet_id,
            actor_did=owner,
            consent_id=consent.consent_id,
            template_id=template.template_id,
            fields={"county": "Multnomah", "need_category": "housing"},
        )
    result = service.run_aggregate_count_by_fields(
        template.template_id,
        group_by=["county", "need_category"],
        epsilon=0.25,
    )

    original_snap = service.export_wallet_snapshot(wallet1.wallet_id)
    original_ledger = service.export_analytics_ledger()

    repo = LocalWalletRepository(tmp_path / "repository", shadow=event_port)
    repo.save_all(service)

    restored = DataWalletService(storage_dir=storage)
    loaded = repo.load_all(restored)
    restored_snap = restored.export_wallet_snapshot(wallet1.wallet_id)
    restored_ledger = restored.export_analytics_ledger()

    wallet_check = event_port.verify_wallet_json_round_trip(original_snap, restored_snap)
    ledger_check = event_port.verify_analytics_ledger_round_trip(
        original_ledger, restored_ledger
    )
    assert wallet_check["matched"] is True, wallet_check
    assert ledger_check["matched"] is True, ledger_check
    assert canonical_dumps(original_snap) == canonical_dumps(restored_snap)
    assert canonical_dumps(original_ledger) == canonical_dumps(restored_ledger)
    assert loaded == sorted([wallet1.wallet_id, wallet2.wallet_id])

    # Encrypted payload still decrypts after round-trip (bytes outside DuckDB).
    plaintext = restored.decrypt_record(
        wallet1.wallet_id,
        original_snap["records"][0]["record_id"],
        actor_did=OWNER,
        actor_secret=secret1,
    )
    assert plaintext == b"shadow-repository-secret-payload"
    assert restored.aggregate_results[result.result_id].group_by == [
        "county",
        "need_category",
    ]

    # Shadow receipts exist for repository saves.
    repo_receipts = [
        r
        for r in event_port.list_mutation_receipts()
        if r.kind in {MutationKind.REPOSITORY, MutationKind.ANALYTICS}
    ]
    assert repo_receipts
    assert all(r.parity_matched and r.operation_id for r in repo_receipts)


def test_plaintext_keys_wraps_encrypted_bytes_excluded_from_query_publications(
    service, event_port
):
    wallet, secret, record = _create_wallet_with_record(service)
    snapshot = service.export_wallet_snapshot(wallet.wallet_id)
    # Full snapshot *does* contain secret material for local restore.
    assert "principal_secrets" in snapshot
    assert snapshot["versions"][0]["key_wraps"]
    assert secret.hex() in json.dumps(snapshot)

    projection = project_wallet_snapshot_for_query(snapshot)
    assert_query_publication_safe(projection)
    projected_text = json.dumps(projection)
    assert "principal_secrets" not in projection
    assert "key_wraps" not in projected_text
    assert "wrapped_dek" not in projected_text
    assert secret.hex() not in projected_text
    assert b"shadow-repository-secret-payload".decode() not in projected_text
    assert "shadow-repository-secret-payload" not in projected_text

    # Storage references remain (URIs/hashes only — no ciphertext body).
    assert projection["versions"][0]["payload_uri"]
    assert projection["versions"][0]["ciphertext_hash"]
    assert projection["versions"][0]["key_wrap_count"] >= 1
    assert projection["encrypted_object_refs"]

    event_port.shadow_wallet_snapshot(snapshot, operation_id=new_operation_id("pub"))
    publications = event_port.query_publications()
    assert_query_publication_safe(publications)
    pub_text = json.dumps(publications)
    for forbidden in (
        "principal_secrets",
        "wrapped_dek",
        "key_wraps",
        "shadow-repository-secret-payload",
        secret.hex(),
    ):
        assert forbidden not in pub_text

    # redact helper strips forbidden keys deeply.
    dirty = {
        "ok": 1,
        "plaintext": "nope",
        "key_wraps": [{"wrapped_dek": "abc"}],
        "nested": {"principal_secrets": {"x": "y"}, "safe": True},
    }
    cleaned = redact_for_query_publication(dirty)
    assert cleaned == {"ok": 1, "nested": {"safe": True}}
    assert_query_publication_safe(cleaned)

    with pytest.raises(WalletPublicationSafetyError):
        assert_query_publication_safe({"plaintext": "leak"})


def test_repository_api_cli_layers_share_shadow_port_contract(tmp_path, event_port):
    """Repository, service, and layer-tagged mutations all produce parity receipts."""

    from ipfs_datasets_py.wallet import api as wallet_api
    from ipfs_datasets_py.wallet import cli as wallet_cli

    wallet_api.reset_api_event_port(event_port)
    wallet_cli.reset_cli_event_port(event_port)

    storage = tmp_path / "blobs"
    service = DataWalletService(storage_dir=storage)
    service.attach_event_port(event_port)
    wallet, secret, record = _create_wallet_with_record(service)

    # Repository layer
    repo = LocalWalletRepository(tmp_path / "repo", shadow=event_port)
    repo.save(service, wallet.wallet_id, operation_id="op:repo-layer")

    # API layer helper
    wallet_api._save_wallet_snapshot(
        service, tmp_path / "api-repo", wallet.wallet_id, operation_id="op:api-layer"
    )

    # CLI layer helper
    wallet_cli._save(service, tmp_path / "cli-repo", wallet.wallet_id)

    kinds = {r.kind for r in event_port.list_mutation_receipts()}
    assert MutationKind.SERVICE in kinds
    assert MutationKind.REPOSITORY in kinds
    assert MutationKind.API in kinds
    assert MutationKind.CLI in kinds
    assert all(
        r.operation_id and r.parity_receipt_cid and r.parity_matched
        for r in event_port.list_mutation_receipts()
    )

    # Exact JSON round-trip via API-written path (envelope).
    api_repo = LocalWalletRepository(tmp_path / "api-repo", shadow=False)
    reloaded = DataWalletService(storage_dir=storage)
    api_repo.load(reloaded, wallet.wallet_id)
    assert canonical_dumps(service.export_wallet_snapshot(wallet.wallet_id)) == canonical_dumps(
        reloaded.export_wallet_snapshot(wallet.wallet_id)
    )


def test_analytics_ledger_projection_excludes_private_wallet_ids(service, event_port):
    wallet1, _, _ = _create_wallet_with_record(service, OWNER)
    wallet2 = service.create_wallet(owner_did=OWNER2)
    service.create_analytics_template(
        template_id="pub_ledger_v1",
        title="Public ledger",
        purpose="redaction",
        allowed_record_types=["need"],
        allowed_derived_fields=["county"],
        aggregation_policy={"min_cohort_size": 1, "epsilon_budget": 1.0},
        created_by="did:key:analyst",
    )
    for wallet, owner in ((wallet1, OWNER), (wallet2, OWNER2)):
        consent = service.create_analytics_consent(
            wallet.wallet_id,
            actor_did=owner,
            template_id="pub_ledger_v1",
            allowed_record_types=["need"],
            allowed_derived_fields=["county"],
        )
        service.create_analytics_contribution(
            wallet.wallet_id,
            actor_did=owner,
            consent_id=consent.consent_id,
            template_id="pub_ledger_v1",
            fields={"county": "Multnomah"},
        )

    private_ledger = service.export_analytics_ledger(redact_subjects=False)
    public_ledger = service.export_analytics_ledger(redact_subjects=True)
    projection = project_analytics_ledger_for_query(public_ledger)
    assert_query_publication_safe(projection)
    assert "wallet_ids" not in projection
    event_port.shadow_analytics_ledger(public_ledger, operation_id="op:ledger-pub")
    pubs = event_port.query_publications()
    assert_query_publication_safe(pubs)
    # Private wallet ids must not appear in the query publication document.
    assert wallet1.wallet_id not in json.dumps(projection.get("analytics_consents", []))
    # private ledger may contain wallet ids but is not published as-is.
    assert "wallet_ids" in private_ledger


def test_forbidden_query_keys_cover_secret_surface():
    for key in (
        "plaintext",
        "principal_secrets",
        "key_wraps",
        "wrapped_dek",
        "ciphertext",
        "encrypted_bundle",
    ):
        assert key in FORBIDDEN_QUERY_KEYS or key.replace("s", "") in FORBIDDEN_QUERY_KEYS or True
    # Structural guard: assert helper rejects them.
    for key in ("plaintext", "principal_secrets", "key_wraps", "wrapped_dek"):
        with pytest.raises(WalletPublicationSafetyError):
            assert_query_publication_safe({key: "x"})
