"""Integration tests: durable matter state stores (PATLAW-124).

Covers restart without duplicate events/downloads, key-reference stability,
tenant separation, and least-privilege file modes.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.durable_stores import (
    DURABLE_STORES_SCHEMA_VERSION,
    DurableMatterState,
    IdempotencyDisposition,
    TenantSeparationError,
    stat_mode,
)
from ipfs_datasets_py.processors.domains.uspto.runtime import (
    RuntimeMode,
    RuntimeProfile,
    bootstrap_runtime,
)
from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    RecordedExchange,
    RecordedHttpTransport,
    RetryPolicy,
)
from ipfs_datasets_py.processors.domains.uspto.providers.credential_resolver import (
    CredentialResolver,
)


APP = "16123456"


def test_status_put_is_idempotent_on_restart(tmp_path: Path) -> None:
    root = tmp_path / "state"
    store = DurableMatterState(root, tenant_id="tenant-x")
    snapshot = {
        "application_number": APP,
        "content_digest": "a" * 64,
        "status_code": "150",
        "sync_key": f"status:{APP}",
    }
    first = store.put_status_snapshot(
        sync_key=f"status:{APP}",
        snapshot=snapshot,
        content_digest="a" * 64,
    )
    assert first.created is True
    assert first.disposition is IdempotencyDisposition.CREATED

    # Restart: reopen same root
    store2 = DurableMatterState(root, tenant_id="tenant-x")
    second = store2.put_status_snapshot(
        sync_key=f"status:{APP}",
        snapshot=snapshot,
        content_digest="a" * 64,
    )
    assert second.created is False
    assert second.disposition is IdempotencyDisposition.DUPLICATE
    loaded = store2.get_status_snapshot(f"status:{APP}")
    assert loaded is not None
    assert loaded["content_digest"] == "a" * 64


def test_event_append_no_duplicates_after_restart(tmp_path: Path) -> None:
    root = tmp_path / "events"
    store = DurableMatterState(root, tenant_id="t-events")
    event = {
        "event_id": "tx:16123456:APP.FILE.REC:deadbeef",
        "event_code": "APP.FILE.REC",
        "application_number": APP,
    }
    r1 = store.append_event(event_id=event["event_id"], event=event)
    r2 = store.append_event(event_id=event["event_id"], event=event)
    assert r1.disposition is IdempotencyDisposition.CREATED
    assert r2.disposition is IdempotencyDisposition.DUPLICATE

    store2 = DurableMatterState(root, tenant_id="t-events")
    r3 = store2.append_event(event_id=event["event_id"], event=event)
    assert r3.disposition is IdempotencyDisposition.DUPLICATE
    assert store2.list_event_ids() == (event["event_id"],)


def test_document_inventory_idempotent_download_marker(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    store = DurableMatterState(root, tenant_id="t-docs")
    docs = [
        {
            "document_identifier": "DOC-1",
            "document_code": "CTNF",
            "sha256": "b" * 64,
        }
    ]
    a = store.put_document_inventory(application_number=APP, documents=docs)
    b = store.put_document_inventory(application_number=APP, documents=docs)
    assert a.created is True
    assert b.disposition is IdempotencyDisposition.DUPLICATE
    inv = store.get_document_inventory(APP)
    assert inv is not None
    assert inv["document_count"] == 1


def test_idempotency_claim_survives_restart(tmp_path: Path) -> None:
    root = tmp_path / "idem"
    store = DurableMatterState(root, tenant_id="t-idem")
    claim = store.claim_idempotency(
        operation="download_document",
        idempotency_key=f"{APP}:DOC-1",
        payload_digest="c" * 64,
    )
    assert claim.created is True
    store2 = DurableMatterState(root, tenant_id="t-idem")
    assert store2.has_idempotency(
        operation="download_document", idempotency_key=f"{APP}:DOC-1"
    )
    again = store2.claim_idempotency(
        operation="download_document",
        idempotency_key=f"{APP}:DOC-1",
        payload_digest="c" * 64,
    )
    assert again.disposition is IdempotencyDisposition.DUPLICATE


def test_cursor_checkpoint_round_trip(tmp_path: Path) -> None:
    store = DurableMatterState(tmp_path / "cursors", tenant_id="t-cur")
    cp = {"resource": "search", "offset": 25, "limit": 25, "exhausted": False}
    store.put_cursor(resource="search", checkpoint=cp)
    store2 = DurableMatterState(tmp_path / "cursors", tenant_id="t-cur")
    loaded = store2.get_cursor("search")
    assert loaded is not None
    assert loaded["offset"] == 25


def test_key_reference_stable_and_secret_free(tmp_path: Path) -> None:
    store = DurableMatterState(tmp_path / "keys", tenant_id="t-keys")
    ref = {
        "kind": "credential_reference",
        "reference_id": "env:USPTO_ODP_API_KEY",
        "scheme": "env",
        "reference_digest": "abc123",
    }
    store.put_key_reference(reference_id="env:USPTO_ODP_API_KEY", reference=ref)
    store2 = DurableMatterState(tmp_path / "keys", tenant_id="t-keys")
    loaded = store2.get_key_reference("env:USPTO_ODP_API_KEY")
    assert loaded is not None
    assert loaded["reference_id"] == "env:USPTO_ODP_API_KEY"
    assert store2.list_key_reference_ids() == ("env:USPTO_ODP_API_KEY",)

    with pytest.raises(Exception) as excinfo:
        store2.put_key_reference(
            reference_id="bad",
            reference={"reference_id": "bad", "api_key": "super-secret"},
        )
    assert "secret" in str(excinfo.value).lower() or "api_key" in str(excinfo.value).lower()


def test_tenant_separation_enforced(tmp_path: Path) -> None:
    root = tmp_path / "multi"
    a = DurableMatterState(root, tenant_id="alice")
    b = DurableMatterState(root, tenant_id="bob")
    a.put_status_snapshot(
        sync_key="status:shared-key",
        snapshot={"owner": "alice", "content_digest": "d" * 64},
        content_digest="d" * 64,
    )
    # Bob must not see Alice's records under the same logical key path space
    # (paths are tenant-scoped).
    assert b.get_status_snapshot("status:shared-key") is None
    b.put_status_snapshot(
        sync_key="status:shared-key",
        snapshot={"owner": "bob", "content_digest": "e" * 64},
        content_digest="e" * 64,
    )
    alice_snap = a.get_status_snapshot("status:shared-key")
    bob_snap = b.get_status_snapshot("status:shared-key")
    assert alice_snap is not None and bob_snap is not None
    assert alice_snap["owner"] == "alice"
    assert bob_snap["owner"] == "bob"

    # Tenant directories are distinct
    assert (root / "tenants" / "alice").is_dir()
    assert (root / "tenants" / "bob").is_dir()
    assert a.tenant_id != b.tenant_id


def test_least_privilege_file_modes(tmp_path: Path) -> None:
    store = DurableMatterState(tmp_path / "modes", tenant_id="t-mode")
    store.put_status_snapshot(
        sync_key="status:mode",
        snapshot={"x": 1, "content_digest": "f" * 64},
        content_digest="f" * 64,
    )
    report = store.verify_least_privilege_modes()
    obs = report["observations"]
    # Directories should be owner rwx only (0o700) when chmod is honored.
    for key in ("tenant_dir", "status_dir"):
        if key in obs:
            mode = obs[key]
            # Reject group/other write bits.
            assert mode & stat.S_IWGRP == 0
            assert mode & stat.S_IWOTH == 0
            assert mode & stat.S_IRUSR
            assert mode & stat.S_IXUSR
    if "meta" in obs:
        fmode = obs["meta"]
        assert fmode & stat.S_IWGRP == 0
        assert fmode & stat.S_IWOTH == 0
        assert fmode & stat.S_IRUSR
    if "sample_status_file" in obs:
        fmode = obs["sample_status_file"]
        assert fmode & stat.S_IWGRP == 0
        assert fmode & stat.S_IWOTH == 0

    # Direct path checks
    tenant_dir = tmp_path / "modes" / "tenants" / "t-mode"
    assert stat_mode(tenant_dir) == 0o700 or (
        stat_mode(tenant_dir) & 0o077 == 0
    )


def test_continuity_and_foreign_priority_immutable(tmp_path: Path) -> None:
    store = DurableMatterState(tmp_path / "fam", tenant_id="t-fam")
    continuity = {
        "application_number": APP,
        "parents": [{"related_application_number": "15000000", "relation_role": "parent"}],
        "children": [],
        "receipt": {"endpoint": "https://api.uspto.gov/.../continuity"},
    }
    foreign = {
        "application_number": APP,
        "claims": [
            {
                "priority_country": "JP",
                "priority_application_number": "2020-000001",
                "priority_date": "2020-01-02",
            }
        ],
        "receipt": {"endpoint": "https://api.uspto.gov/.../foreign-priority"},
    }
    c1 = store.put_continuity(application_number=APP, snapshot=continuity)
    c2 = store.put_continuity(application_number=APP, snapshot=continuity)
    assert c1.created is True
    assert c2.disposition is IdempotencyDisposition.DUPLICATE
    f1 = store.put_foreign_priority(application_number=APP, snapshot=foreign)
    f2 = store.put_foreign_priority(application_number=APP, snapshot=foreign)
    assert f1.created is True
    assert f2.disposition is IdempotencyDisposition.DUPLICATE
    assert store.get_continuity(APP)["parents"][0]["related_application_number"] == "15000000"
    assert store.get_foreign_priority(APP)["claims"][0]["priority_country"] == "JP"


def test_runtime_wires_durable_state_on_restart(tmp_path: Path) -> None:
    root = tmp_path / "runtime-state"
    transport = RecordedHttpTransport([])
    resolver = CredentialResolver.from_mapping(vault={"rk": "v" * 12})
    profile = RuntimeProfile(
        mode=RuntimeMode.PRODUCTION,
        credential_ref="vault:rk",
        store_root=root,
        tenant_id="rt",
        transport=transport,
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
    )
    r1 = bootstrap_runtime(profile, credential_resolver=resolver)
    assert r1.durable_state is not None
    r1.durable_state.append_event(
        event_id="e1",
        event={"event_id": "e1", "kind": "status"},
    )
    r2 = bootstrap_runtime(profile, credential_resolver=resolver)
    assert r2.durable_state is not None
    assert r2.durable_state.get_event("e1") is not None
    assert r2.reload_key_reference() is not None
    assert r2.durable_state.schema_version == DURABLE_STORES_SCHEMA_VERSION


def test_encryption_metadata_tenant_bound(tmp_path: Path) -> None:
    store = DurableMatterState(
        tmp_path / "enc",
        tenant_id="enc-tenant",
        key_id="k1",
        encryption_suite="AES-256-GCM",
    )
    assert store.encryption.tenant_id == "enc-tenant"
    assert store.encryption.key_id == "k1"
    assert "enc-tenant" in store.encryption.namespace
    cfg = store.safe_config()
    assert "key_bytes" not in str(cfg).lower()
    assert cfg["encryption"]["suite"] == "AES-256-GCM"
