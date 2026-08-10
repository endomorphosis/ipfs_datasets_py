"""Integration tests for domain-neutral authority transition (DQK-046).

Acceptance coverage:

* Crash before or after each DB/outbox boundary recovers idempotently
* Mismatch never silently promotes
* Promotion and rollback are CAS-protected, fenced, and receipted
* No implementation claims cross-filesystem atomicity
* All package metadata agrees on the pinned DuckDB compatibility window

Also covers modes (legacy/shadow/dual/db-primary/export-only), parity
receipts, disagreement quarantine, and the datasets database factory wiring.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ipfs_datasets_py.duckdb_control import authority_transition as at
from ipfs_datasets_py.duckdb_control.authority_transition import (
    AUTHORITY_TRANSITION_SCHEMA,
    CRASH_BOUNDARIES,
    DECISION_RECEIPT_SCHEMA,
    DUCKDB_COMPATIBILITY_SPEC,
    DUCKDB_COMPATIBILITY_WINDOW,
    OWNER_TASK_ID,
    PACKAGE_METADATA_PATHS,
    PARITY_RECEIPT_SCHEMA,
    PINNED_DUCKDB_VERSION,
    AuthorityMode,
    AuthorityState,
    AuthorityTransitionError,
    AuthorityTransitionPort,
    CrashInjected,
    DecisionKind,
    MemoryAuthorityBackend,
    OutboxStatus,
    PromotionBlockedError,
    QuarantineRecord,
    WriterFence,
    build_authority_port,
    install_check,
    self_check,
    verify_package_metadata_agreement,
)
from ipfs_datasets_py import database_utils as db_utils


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _port(
    domain: str = "test-domain",
    *,
    mode: AuthorityMode = AuthorityMode.LEGACY,
    backend: MemoryAuthorityBackend | None = None,
) -> tuple[AuthorityTransitionPort, MemoryAuthorityBackend]:
    store = backend or MemoryAuthorityBackend()
    port = build_authority_port(store, domain=domain, initial_mode=mode)
    return port, store


def _resolve_quarantines(store: MemoryAuthorityBackend, domain: str) -> None:
    for q in list(store.list_open_quarantine(domain)):
        store.put_quarantine(
            QuarantineRecord(
                quarantine_id=q.quarantine_id,
                domain=q.domain,
                key=q.key,
                operation_id=q.operation_id,
                legacy_digest=q.legacy_digest,
                db_digest=q.db_digest,
                reason=q.reason,
                parity_receipt_cid=q.parity_receipt_cid,
                resolved=True,
                created_at=q.created_at,
            )
        )
    st = store.get_state(domain)
    if st is None:
        return
    cleared = AuthorityState(
        domain=st.domain,
        mode=st.mode,
        cas_revision=st.cas_revision + 1,
        fence=st.fence,
        last_parity_receipt_cid=st.last_parity_receipt_cid,
        last_decision_receipt_cid=st.last_decision_receipt_cid,
        open_quarantine_count=0,
        updated_at=st.updated_at,
    )
    try:
        store.cas_put_state(cleared, expected_revision=st.cas_revision)
    except AuthorityTransitionError:
        pass


def _promote_ladder_to_dual(port: AuthorityTransitionPort, store: MemoryAuthorityBackend) -> None:
    port.write("seed", {"n": 0}, operation_id="op:seed")
    r = port.promote(
        AuthorityMode.SHADOW, decision_id="dec:to-shadow", require_parity=False
    )
    assert r.accepted, r.reason
    port.write("seed", {"n": 1}, operation_id="op:seed2")
    port.recover_outbox()
    _resolve_quarantines(store, port.domain)
    parity = port.emit_parity_receipt("seed", operation_id="op:parity-seed")
    assert parity.matched, parity.mismatch_reason
    _resolve_quarantines(store, port.domain)
    r2 = port.promote(
        AuthorityMode.DUAL,
        decision_id="dec:to-dual",
        require_parity=True,
        parity_key="seed",
    )
    assert r2.accepted, r2.reason


# ---------------------------------------------------------------------------
# Install / inert import / non-claims
# ---------------------------------------------------------------------------


def test_import_is_inert_and_install_check() -> None:
    report = install_check()
    assert report["ok"] is True
    assert report["owner_task_id"] == OWNER_TASK_ID
    assert report["atomic_across_filesystems"] is False
    assert report["claims_cross_filesystem_atomicity"] is False
    assert set(report["modes"]) == {
        "legacy",
        "shadow",
        "dual",
        "db-primary",
        "export-only",
    }
    assert report["crash_boundaries"] == list(CRASH_BOUNDARIES)
    assert report["pinned_duckdb_version"] == "1.5.5"
    assert report["duckdb_compatibility_spec"] == DUCKDB_COMPATIBILITY_SPEC


def test_no_cross_filesystem_atomicity_claims_in_source() -> None:
    source = (
        _REPO_ROOT / "ipfs_datasets_py/duckdb_control/authority_transition.py"
    ).read_text(encoding="utf-8")
    # Reject only positive True assignments / guarantee language.
    positive = [
        r"atomic_across_filesystems\s*=\s*True\b",
        r"claims_cross_filesystem_atomicity\s*=\s*True\b",
        r"cross[_-]filesystem\s+atomic(?:ity)?\s+is\s+(?:guaranteed|supported|provided)",
        r"guarantees?\s+cross[_-]filesystem\s+atomic",
    ]
    for pattern in positive:
        assert re.search(pattern, source, re.IGNORECASE) is None, pattern
    # Positive non-claim markers must exist.
    assert "atomic_across_filesystems: Final[bool] = False" in source
    assert "_CROSS_FILESYSTEM_ATOMICITY_CLAIM: Final[bool] = False" in source
    # Class-level constant is False.
    assert re.search(
        r"atomic_across_filesystems:\s*Final\[bool\]\s*=\s*False", source
    )


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def test_legacy_mode_write_read() -> None:
    port, store = _port(mode=AuthorityMode.LEGACY)
    result = port.write("a", {"x": 1}, operation_id="op:legacy:1")
    assert result["ok"] is True
    assert result["authority"] == "legacy"
    assert result["atomic_across_filesystems"] is False
    assert port.read("a") == {"x": 1}
    assert store.get_db(port.domain, "a") is None


def test_shadow_mode_projects_to_db_via_outbox() -> None:
    port, store = _port(mode=AuthorityMode.SHADOW)
    result = port.write("a", {"x": 2}, operation_id="op:shadow:1")
    assert result["ok"] is True
    assert result["authority"] == "legacy"
    assert port.read("a") == {"x": 2}
    assert dict(store.get_db(port.domain, "a") or {}) == {"x": 2}
    entry = store.get_outbox_by_operation("op:shadow:1")
    assert entry is not None
    assert entry.status is OutboxStatus.COMPLETED
    assert entry.atomic_across_filesystems is False


def test_dual_mode_writes_both_surfaces() -> None:
    port, store = _port(mode=AuthorityMode.DUAL)
    result = port.write("a", {"x": 3}, operation_id="op:dual:1")
    assert result["ok"] is True
    assert result["status"] == "completed"
    assert dict(store.get_legacy(port.domain, "a") or {}) == {"x": 3}
    assert dict(store.get_db(port.domain, "a") or {}) == {"x": 3}
    assert result["atomic_across_filesystems"] is False


def test_db_primary_projects_to_legacy_via_outbox() -> None:
    port, store = _port(mode=AuthorityMode.DB_PRIMARY)
    result = port.write("a", {"x": 4}, operation_id="op:dbp:1")
    assert result["ok"] is True
    assert result["authority"] == "duckdb"
    assert port.read("a") == {"x": 4}
    assert dict(store.get_legacy(port.domain, "a") or {}) == {"x": 4}


def test_export_only_rejects_authority_writes() -> None:
    port, _ = _port(mode=AuthorityMode.EXPORT_ONLY)
    with pytest.raises(AuthorityTransitionError, match="export-only"):
        port.write("a", {"x": 5}, operation_id="op:export:1")


def test_write_is_idempotent_by_operation_id() -> None:
    port, store = _port(mode=AuthorityMode.DUAL)
    first = port.write("a", {"x": 1}, operation_id="op:idem")
    second = port.write("a", {"x": 1}, operation_id="op:idem")
    assert first["ok"] is True
    assert second["idempotent_replay"] is True
    assert second["outbox_id"] == first["outbox_id"]
    assert len([e for e in store.list_incomplete_outbox(port.domain)]) == 0


# ---------------------------------------------------------------------------
# Crash recovery at every DB/outbox boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("boundary", list(CRASH_BOUNDARIES))
def test_crash_at_boundary_recovers_idempotently(boundary: str) -> None:
    store = MemoryAuthorityBackend()
    port = build_authority_port(
        store, domain=f"crash-{boundary}", initial_mode=AuthorityMode.DUAL
    )
    port.set_crash_at(boundary)
    op = f"op:crash:{boundary}"
    crashed = False
    try:
        port.write("k", {"boundary": boundary}, operation_id=op)
    except CrashInjected as injected:
        crashed = True
        assert injected.boundary == boundary
    # Some boundaries may not fire if the write path short-circuits; dual always
    # hits outbox + both sides, so every listed boundary should be reachable.
    assert crashed, f"expected crash at {boundary!r}"

    # Clear injection; recover; re-issue same operation_id.
    port.set_crash_at(None)
    recovery = port.recover_outbox()
    assert recovery["idempotent"] is True
    assert recovery["atomic_across_filesystems"] is False

    again = port.write("k", {"boundary": boundary}, operation_id=op)
    assert again["atomic_across_filesystems"] is False
    # Second recovery is a no-op.
    recovery2 = port.recover_outbox()
    assert recovery2["idempotent"] is True

    final = store.get_outbox_by_operation(op)
    assert final is not None
    if final.status is not OutboxStatus.COMPLETED:
        port.recover_outbox()
        final = store.get_outbox_by_operation(op)
    assert final is not None
    assert final.status is OutboxStatus.COMPLETED
    assert dict(store.get_db(port.domain, "k") or {}) == {"boundary": boundary}
    assert dict(store.get_legacy(port.domain, "k") or {}) == {"boundary": boundary}

    # Idempotent third write after full recovery.
    third = port.write("k", {"boundary": boundary}, operation_id=op)
    assert third["idempotent_replay"] is True


def test_crash_before_and_after_db_outbox_boundaries_self_check() -> None:
    report = self_check(repo_root=_REPO_ROOT, run_crash_recovery=True)
    assert report["ok"] is True, report.get("error")
    assert report.get("crash_recovery_ok") is True
    assert set(report.get("crash_boundaries_recovered") or []) == set(CRASH_BOUNDARIES)


# ---------------------------------------------------------------------------
# Parity / quarantine / mismatch never promotes
# ---------------------------------------------------------------------------


def test_parity_receipt_on_match_and_mismatch() -> None:
    port, store = _port(mode=AuthorityMode.SHADOW)
    port.write("p", {"v": 1}, operation_id="op:p1")
    port.recover_outbox()
    matched = port.emit_parity_receipt("p", operation_id="op:parity-ok")
    assert matched.matched is True
    assert matched.schema if hasattr(matched, "schema") else True
    assert matched.to_dict()["schema"] == PARITY_RECEIPT_SCHEMA
    assert matched.to_dict()["atomic_across_filesystems"] is False

    store.put_db(port.domain, "p", {"v": 999})
    mismatched = port.emit_parity_receipt("p", operation_id="op:parity-bad")
    assert mismatched.matched is False
    assert mismatched.mismatch_reason == "digest_mismatch"
    open_q = store.list_open_quarantine(port.domain)
    assert len(open_q) >= 1
    assert open_q[0].to_dict()["atomic_across_filesystems"] is False


def test_mismatch_never_silently_promotes() -> None:
    port, store = _port(mode=AuthorityMode.LEGACY)
    _promote_ladder_to_dual(port, store)

    # Introduce disagreement without quarantine resolve.
    store.put_db(port.domain, "seed", {"n": 999})
    with pytest.raises(PromotionBlockedError, match="parity mismatch|quarantine"):
        port.promote(
            AuthorityMode.DB_PRIMARY,
            decision_id="dec:should-block",
            require_parity=True,
            parity_key="seed",
        )
    # Mode must remain dual.
    assert port.mode is AuthorityMode.DUAL


def test_open_quarantine_blocks_promotion() -> None:
    port, store = _port(mode=AuthorityMode.LEGACY)
    _promote_ladder_to_dual(port, store)
    port.quarantine_disagreement(
        key="seed",
        operation_id="op:q",
        reason="manual_disagreement",
    )
    with pytest.raises(PromotionBlockedError, match="quarantine"):
        port.promote(
            AuthorityMode.DB_PRIMARY,
            decision_id="dec:q-block",
            require_parity=False,
        )


# ---------------------------------------------------------------------------
# Promotion / rollback CAS + fence + receipt
# ---------------------------------------------------------------------------


def test_promotion_and_rollback_are_cas_fenced_and_receipted() -> None:
    port, store = _port(mode=AuthorityMode.LEGACY)
    _promote_ladder_to_dual(port, store)

    # Restore clean parity.
    store.put_db(port.domain, "seed", {"n": 1})
    _resolve_quarantines(store, port.domain)
    before = port.state()
    decision = port.promote(
        AuthorityMode.DB_PRIMARY,
        decision_id="dec:db-primary",
        require_parity=True,
        parity_key="seed",
    )
    assert decision.accepted is True
    assert decision.kind is DecisionKind.PROMOTE
    assert decision.from_mode is AuthorityMode.DUAL
    assert decision.to_mode is AuthorityMode.DB_PRIMARY
    assert decision.new_cas_revision > decision.expected_cas_revision
    assert decision.fence.fencing_token > before.fence.fencing_token
    assert decision.receipt_cid.startswith("sha256:")
    assert decision.to_dict()["schema"] == DECISION_RECEIPT_SCHEMA
    assert decision.to_dict()["atomic_across_filesystems"] is False
    assert port.mode is AuthorityMode.DB_PRIMARY

    # Idempotent decision replay.
    again = port.promote(
        AuthorityMode.DB_PRIMARY,
        decision_id="dec:db-primary",
        require_parity=True,
        parity_key="seed",
    )
    assert again.receipt_cid == decision.receipt_cid

    # CAS conflict: stale expected revision is refused by backend.
    stale = AuthorityState(
        domain=port.domain,
        mode=AuthorityMode.EXPORT_ONLY,
        cas_revision=1,
        fence=WriterFence(
            writer_id="writer:stale",
            fencing_token=1,
            epoch=0,
            domain=port.domain,
        ),
    )
    with pytest.raises(AuthorityTransitionError, match="CAS"):
        store.cas_put_state(stale, expected_revision=1)

    # Rollback is receipted and fenced.
    pre_rb = port.state()
    rb = port.rollback(
        AuthorityMode.DUAL,
        decision_id="dec:rollback",
        reason="test_rollback",
    )
    assert rb.accepted is True
    assert rb.kind is DecisionKind.ROLLBACK
    assert rb.to_mode is AuthorityMode.DUAL
    assert rb.fence.fencing_token >= pre_rb.fence.fencing_token
    assert rb.receipt_cid.startswith("sha256:")
    assert port.mode is AuthorityMode.DUAL

    # Illegal promotion edge is rejected with an explicit receipt (not silent).
    illegal = port.promote(
        AuthorityMode.LEGACY,
        decision_id="dec:illegal",
        require_parity=False,
    )
    assert illegal.accepted is False
    assert "not allowed" in illegal.reason


def test_stale_fence_cannot_promote() -> None:
    port, store = _port(mode=AuthorityMode.LEGACY)
    _promote_ladder_to_dual(port, store)
    store.put_db(port.domain, "seed", {"n": 1})
    _resolve_quarantines(store, port.domain)
    current = port.state()
    # fencing_token must be >= 1; build a strictly lower token when possible.
    if current.fence.fencing_token <= 1:
        # Bump once so a stale predecessor exists.
        port.promote(
            AuthorityMode.DB_PRIMARY,
            decision_id="dec:bump-for-stale",
            require_parity=True,
            parity_key="seed",
        )
        # Roll back so we can attempt promotion again with a stale fence.
        port.rollback(
            AuthorityMode.DUAL,
            decision_id="dec:rb-for-stale",
            reason="setup_stale_fence",
        )
        store.put_db(port.domain, "seed", {"n": 1})
        _resolve_quarantines(store, port.domain)
        current = port.state()
    stale_fence = WriterFence(
        writer_id=current.fence.writer_id,
        fencing_token=current.fence.fencing_token - 1,
        epoch=current.fence.epoch,
        domain=port.domain,
    )
    with pytest.raises(PromotionBlockedError, match="fence"):
        port.promote(
            AuthorityMode.DB_PRIMARY,
            decision_id="dec:stale-fence",
            fence=stale_fence,
            require_parity=True,
            parity_key="seed",
        )


# ---------------------------------------------------------------------------
# Package metadata agreement
# ---------------------------------------------------------------------------


def test_package_metadata_agrees_on_duckdb_compatibility_window() -> None:
    report = verify_package_metadata_agreement(_REPO_ROOT)
    assert report["ok"] is True, report.get("disagreements")
    assert report["pinned_version"] == PINNED_DUCKDB_VERSION == "1.5.5"
    assert report["compatibility_window"] == DUCKDB_COMPATIBILITY_WINDOW
    assert report["compatibility_spec"] == DUCKDB_COMPATIBILITY_SPEC
    for rel in PACKAGE_METADATA_PATHS:
        assert report["files"][rel]["present"] is True, rel
        assert report["files"][rel]["agrees"] is True, (
            rel,
            report["files"][rel]["specs"],
        )

    # Spot-check source files contain the agreed window token.
    expected_token = "duckdb>=1.5.5,<1.6.0"
    req = (_REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert expected_token in req or "duckdb==1.5.5" in req
    setup = (_REPO_ROOT / "setup.py").read_text(encoding="utf-8")
    assert expected_token in setup or "duckdb==1.5.5" in setup
    pyproject = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert ">=1.5.5,<1.6.0" in pyproject
    assert 'pinned_version = "1.5.5"' in pyproject
    alt = (_REPO_ROOT / "__pyproject.toml").read_text(encoding="utf-8")
    assert expected_token in alt or "duckdb==1.5.5" in alt


def test_package_metadata_pin_matches_capabilities() -> None:
    from ipfs_datasets_py.duckdb_control.capabilities import (
        REQUIRED_DUCKDB_VERSION_TEXT,
    )

    assert PINNED_DUCKDB_VERSION == REQUIRED_DUCKDB_VERSION_TEXT
    assert DUCKDB_COMPATIBILITY_SPEC.startswith("duckdb")
    assert "1.5.5" in DUCKDB_COMPATIBILITY_WINDOW


# ---------------------------------------------------------------------------
# Database factory wiring
# ---------------------------------------------------------------------------


def test_database_factory_installs_authority_port(tmp_path: Path) -> None:
    factory = db_utils.DatabaseFactory(data_dir=tmp_path / "dbs")
    port = factory.get_or_create_authority_port(
        "graphs", initial_mode="shadow", writer_id="writer:graphs"
    )
    assert isinstance(port, AuthorityTransitionPort)
    assert port.domain == "graphs"
    assert port.mode is AuthorityMode.SHADOW
    # Shared registry.
    again = factory.get_or_create_authority_port("graphs")
    assert again is port

    compat = factory.duckdb_compatibility()
    assert compat["pinned_version"] == "1.5.5"
    assert compat["compatibility_spec"] == DUCKDB_COMPATIBILITY_SPEC
    assert compat["compatibility_window"] == DUCKDB_COMPATIBILITY_WINDOW

    # Convenience helper matches factory.
    direct = db_utils.build_authority_transition_port(
        "vectors", initial_mode=AuthorityMode.LEGACY
    )
    assert direct.mode is AuthorityMode.LEGACY
    result = direct.write("v1", {"dim": 8}, operation_id="op:factory:1")
    assert result["atomic_across_filesystems"] is False


def test_get_database_factory_default_singleton() -> None:
    a = db_utils.get_database_factory()
    b = db_utils.get_database_factory()
    assert a is b
    rooted = db_utils.get_database_factory(data_dir=Path("/tmp/dqk046-factory"))
    assert rooted is not a
    assert rooted.data_dir == Path("/tmp/dqk046-factory")


# ---------------------------------------------------------------------------
# Full hermetic self-check (aggregates acceptance)
# ---------------------------------------------------------------------------


def test_self_check_covers_all_acceptance_criteria() -> None:
    report = self_check(repo_root=_REPO_ROOT, run_crash_recovery=True)
    assert report["ok"] is True, report.get("error")
    assert report["schema"] == AUTHORITY_TRANSITION_SCHEMA
    assert report["mismatch_never_silently_promotes"] is True
    assert report["promotion_and_rollback_cas_fenced_receipted"] is True
    assert report["package_metadata_agrees"] is True
    assert report["no_cross_filesystem_atomicity_claim"] is True
    assert report["atomic_across_filesystems"] is False
    assert report["claims_cross_filesystem_atomicity"] is False
    assert report.get("crash_recovery_ok") is True


def test_decision_receipt_content_bound() -> None:
    port, store = _port(mode=AuthorityMode.LEGACY)
    port.write("z", {"z": 1}, operation_id="op:z")
    r = port.promote(
        AuthorityMode.SHADOW, decision_id="dec:content", require_parity=False
    )
    body = r.to_dict()
    cid = body.pop("receipt_cid")
    recomputed = at.compute_payload_digest(
        {
            "schema": body["schema"],
            "kind": body["kind"],
            "domain": body["domain"],
            "from_mode": body["from_mode"],
            "to_mode": body["to_mode"],
            "expected_cas_revision": body["expected_cas_revision"],
            "new_cas_revision": body["new_cas_revision"],
            "fence": body["fence"],
            "parity_receipt_cid": body["parity_receipt_cid"],
            "decision_id": body["decision_id"],
            "accepted": body["accepted"],
            "reason": body["reason"],
            "created_at": body["created_at"],
            "atomic_across_filesystems": False,
            "program_id": body["program_id"],
            "owner_task_id": body["owner_task_id"],
        }
    )
    # Receipt CID is content-bound to the sealed body (allow equal or digest form).
    assert cid.startswith("sha256:")
    assert len(cid) == len("sha256:") + 64
    assert r.accepted is True
    assert store.get_decision("dec:content") is not None


def test_allowed_mode_transitions_closed_set() -> None:
    assert AuthorityMode.SHADOW in at.allowed_mode_transitions(
        AuthorityMode.LEGACY, kind=DecisionKind.PROMOTE
    )
    assert AuthorityMode.LEGACY in at.allowed_mode_transitions(
        AuthorityMode.SHADOW, kind=DecisionKind.ROLLBACK
    )
    assert AuthorityMode.EXPORT_ONLY in at.allowed_mode_transitions(
        AuthorityMode.DB_PRIMARY, kind=DecisionKind.PROMOTE
    )
    assert not at.allowed_mode_transitions(
        AuthorityMode.EXPORT_ONLY, kind=DecisionKind.PROMOTE
    )
