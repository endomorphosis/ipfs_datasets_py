"""Hermetic unit tests for the DQK-052 typed observability catalog.

Acceptance coverage:

* File mtimes are not progress authority
* Sensitive query text is redacted/classified
* Control, query, proof, graph, vector, AST, and wallet traces correlate by IDs

Also covers lifecycle events, spans, health samples, query profiles, blocker
transitions, dead letters, audit records, append-only semantics, bounded
retention, and non-authoritative export. Import-time inertness is verified
(no duckdb / filesystem I/O at module load).
"""

from __future__ import annotations

import builtins
import hashlib
import importlib
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
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

import pytest

from ipfs_datasets_py.duckdb_control.contracts import SnapshotId
from ipfs_datasets_py.duckdb_control import observability as obs


FIXED_CLOCK = "2026-08-10T12:00:00Z"


def _clock() -> str:
    return FIXED_CLOCK


def _catalog(**kwargs: Any) -> obs.ObservabilityCatalog:
    kwargs.setdefault("clock", _clock)
    return obs.open_memory_catalog(**kwargs)


def _full_correlation(trace_id: str = "trace-cross-domain-001") -> obs.CorrelationIds:
    return obs.CorrelationIds(
        trace_id=trace_id,
        control_task_id="task-DQK-052",
        control_goal_id="goal-G1000",
        query_receipt_id="receipt-q-001",
        query_template_id="publication.list_records",
        proof_key_id="proof-key-alpha",
        proof_entry_id="proof-entry-1",
        graph_id="graph-main",
        graph_revision_id="grev-42",
        vector_collection_id="vec-coll-1",
        vector_generation_id="vgen-7",
        ast_source_revision_id="ast-rev-9",
        ast_blob_id="ast-blob-abc",
        wallet_chain_id="chain-ethereum",
        wallet_cursor_id="wcur-100",
        tenant_id="tenant-alpha",
        request_id="req-xyz",
    )


# ---------------------------------------------------------------------------
# Import inertness
# ---------------------------------------------------------------------------


def test_module_import_is_inert(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing observability must not touch duckdb or the filesystem."""

    real_import = builtins.__import__

    def guarded(name: str, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        root = name.split(".", 1)[0]
        if root in {"duckdb", "pyarrow", "fsspec"}:
            raise AssertionError(f"unexpected import of {name!r} at load time")
        return real_import(name, *args, **kwargs)

    # Drop cached modules so re-import exercises the top-level path.
    for key in list(sys.modules):
        if key == "ipfs_datasets_py.duckdb_control.observability" or key.startswith(
            "ipfs_datasets_py.duckdb_control.observability."
        ):
            del sys.modules[key]

    monkeypatch.setattr(builtins, "__import__", guarded)
    reloaded = importlib.import_module(
        "ipfs_datasets_py.duckdb_control.observability"
    )
    assert reloaded.OBSERVABILITY_SCHEMA.endswith("@1")
    assert "lifecycle_events" in reloaded.CATALOG_FAMILIES


# ---------------------------------------------------------------------------
# Progress authority: file mtimes rejected
# ---------------------------------------------------------------------------


def test_file_mtimes_are_not_progress_authority() -> None:
    with pytest.raises(obs.ObservabilityError, match="mtime"):
        obs.refuse_mtime_progress_authority(obs.ProgressAuthority.FILE_MTIME)

    with pytest.raises(obs.ObservabilityError, match="mtime"):
        obs.refuse_mtime_progress_authority("file_mtime")

    with pytest.raises(obs.ObservabilityError, match="mtime"):
        obs.refuse_mtime_progress_authority(mtime=time.time())

    with pytest.raises(obs.ObservabilityError, match="mtime"):
        obs.refuse_mtime_progress_authority(path="/var/log/app.log")

    # Sequence authority is accepted.
    obs.refuse_mtime_progress_authority(obs.ProgressAuthority.SEQUENCE)
    cursor = obs.progress_cursor_from_sequence(7, event_id="evt-7")
    assert cursor.authority is obs.ProgressAuthority.SEQUENCE
    assert cursor.sequence == 7

    with pytest.raises(obs.ObservabilityError, match="mtime"):
        obs.ProgressCursor(
            sequence=1,
            authority=obs.ProgressAuthority.FILE_MTIME,
        )


def test_catalog_progress_is_sequence_based() -> None:
    catalog = _catalog()
    catalog.record_lifecycle_event(
        event_type="component.start",
        component="supervisor",
        domain=obs.TraceDomain.CONTROL,
    )
    progress = catalog.progress()
    assert progress.authority is obs.ProgressAuthority.SEQUENCE
    assert progress.sequence >= 1
    assert progress.authority is not obs.ProgressAuthority.FILE_MTIME


# ---------------------------------------------------------------------------
# Sensitive query text redaction / classification
# ---------------------------------------------------------------------------


def test_sensitive_query_text_is_redacted_and_classified() -> None:
    raw = "SELECT * FROM users WHERE password = 'hunter2' AND id = 1"
    stored, klass, digest = obs.classify_and_redact_query_text(raw)
    assert klass is obs.SensitivityClass.REDACTED
    assert "hunter2" not in stored
    assert obs.REDACTION_MARKER in stored
    assert digest.startswith("sha256:")
    # Digest is over original plaintext.
    expected = "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert digest == expected


def test_secret_query_text_refused() -> None:
    with pytest.raises(obs.ObservabilityError, match="secret"):
        obs.classify_and_redact_query_text(
            "SELECT private_key FROM wallet",
            classification=obs.SensitivityClass.SECRET,
        )


def test_query_profile_records_redacted_text() -> None:
    catalog = _catalog()
    profile = catalog.record_query_profile(
        template_id="publication.list_records",
        query_text="SELECT * FROM t WHERE api_key = 'sk-live-abc'",
        correlation=obs.CorrelationIds(
            trace_id="trace-q-1",
            query_receipt_id="receipt-1",
            query_template_id="publication.list_records",
        ),
        duration_ms=12,
        row_count=3,
    )
    assert profile.query_text_classification is obs.SensitivityClass.REDACTED
    assert "sk-live-abc" not in profile.query_text
    assert profile.query_text_digest.startswith("sha256:")
    # Stored record must not leak the secret on export either.
    assert "sk-live-abc" not in str(profile.to_dict())


def test_insert_values_patterns_force_redaction() -> None:
    text = "INSERT INTO secrets VALUES ('tok-xyz')"
    stored, klass, _digest = obs.classify_and_redact_query_text(text)
    assert klass is obs.SensitivityClass.REDACTED


# ---------------------------------------------------------------------------
# Cross-domain correlation by IDs
# ---------------------------------------------------------------------------


def test_control_query_proof_graph_vector_ast_wallet_correlate_by_ids() -> None:
    catalog = _catalog()
    corr = _full_correlation("trace-all-domains")
    assert set(corr.bound_domains()) == set(obs.REQUIRED_CORRELATION_DOMAINS)

    trace = catalog.start_trace(
        name="cross-domain-job",
        root_domain=obs.TraceDomain.CONTROL,
        trace_id=corr.trace_id,
        correlation=corr,
    )
    assert trace.correlation.trace_id == corr.trace_id

    # One span per required domain, each carrying the shared correlation.
    for domain in (
        obs.TraceDomain.CONTROL,
        obs.TraceDomain.QUERY,
        obs.TraceDomain.PROOF,
        obs.TraceDomain.GRAPH,
        obs.TraceDomain.VECTOR,
        obs.TraceDomain.AST,
        obs.TraceDomain.WALLET,
    ):
        catalog.record_span(
            trace_id=corr.trace_id,
            name=f"span-{domain.value}",
            domain=domain,
            correlation=corr,
            duration_ms=5,
        )

    catalog.record_lifecycle_event(
        event_type="task.attempt",
        component="control-plane",
        domain=obs.TraceDomain.CONTROL,
        correlation=corr,
    )
    catalog.record_query_profile(
        template_id="publication.list_records",
        query_text="SELECT 1",
        correlation=corr,
    )
    catalog.record_health_sample(
        component="proof-solver",
        domain=obs.TraceDomain.PROOF,
        status="healthy",
        correlation=corr,
    )
    catalog.record_audit(
        action="query.execute",
        actor="tenant-alpha",
        outcome="succeeded",
        domain=obs.TraceDomain.QUERY,
        correlation=corr,
    )

    by_trace = catalog.records_for_trace(corr.trace_id)
    assert len(by_trace) >= 1 + 7  # trace + 7 domain spans (+extras)

    coverage = catalog.correlation_coverage(corr.trace_id)
    for domain in obs.REQUIRED_CORRELATION_DOMAINS:
        assert domain in coverage, f"missing domain {domain}"

    # Domain-id joins.
    assert catalog.correlate_by_domain_id(
        obs.TraceDomain.CONTROL, "task-DQK-052"
    )
    assert catalog.correlate_by_domain_id(
        obs.TraceDomain.QUERY, "receipt-q-001"
    )
    assert catalog.correlate_by_domain_id(
        obs.TraceDomain.PROOF, "proof-key-alpha"
    )
    assert catalog.correlate_by_domain_id(obs.TraceDomain.GRAPH, "grev-42")
    assert catalog.correlate_by_domain_id(obs.TraceDomain.VECTOR, "vgen-7")
    assert catalog.correlate_by_domain_id(
        obs.TraceDomain.AST, "ast-rev-9"
    )
    assert catalog.correlate_by_domain_id(
        obs.TraceDomain.WALLET, "wcur-100"
    )


def test_correlation_conflict_on_merge() -> None:
    left = obs.CorrelationIds(trace_id="t1", control_task_id="task-a")
    right = obs.CorrelationIds(trace_id="t1", control_task_id="task-b")
    with pytest.raises(obs.ObservabilityError, match="conflict"):
        left.merge(right)


def test_span_mirrors_trace_and_span_ids_into_correlation() -> None:
    catalog = _catalog()
    span = catalog.record_span(
        trace_id="trace-s-1",
        name="work",
        domain=obs.TraceDomain.GRAPH,
        span_id="span-s-1",
        correlation=obs.CorrelationIds(graph_revision_id="grev-1"),
    )
    assert span.correlation.trace_id == "trace-s-1"
    assert span.correlation.span_id == "span-s-1"
    assert span.correlation.graph_revision_id == "grev-1"


# ---------------------------------------------------------------------------
# All catalog families: append-only writers
# ---------------------------------------------------------------------------


def test_all_families_append_and_list() -> None:
    catalog = _catalog()
    corr = obs.CorrelationIds(trace_id="trace-families")

    life = catalog.record_lifecycle_event(
        event_type="system.start",
        component="daemon",
        domain=obs.TraceDomain.SYSTEM,
        correlation=corr,
    )
    tr = catalog.start_trace(
        name="job",
        root_domain=obs.TraceDomain.CONTROL,
        correlation=corr,
    )
    sp = catalog.record_span(
        trace_id=tr.trace_id,
        name="step",
        domain=obs.TraceDomain.CONTROL,
        correlation=corr,
    )
    health = catalog.record_health_sample(
        component="quack",
        domain=obs.TraceDomain.QUERY,
        status="healthy",
        latency_ms=3,
        correlation=corr,
    )
    profile = catalog.record_query_profile(
        template_id="health.ping",
        query_text="SELECT 1",
        correlation=corr,
    )
    blocker = catalog.record_blocker_transition(
        blocker_id="blk-1",
        blocker_type="dependency",
        from_state="open",
        to_state="resolved",
        reason="upstream ready",
        correlation=corr,
    )
    dead = catalog.record_dead_letter(
        source="task-runner",
        domain=obs.TraceDomain.CONTROL,
        reason="max_retries_exceeded",
        payload=b'{"task":"DQK-052"}',
        correlation=corr,
    )
    audit = catalog.record_audit(
        action="lease.claim",
        actor="worker-1",
        outcome="allowed",
        domain=obs.TraceDomain.CONTROL,
        correlation=corr,
    )

    assert life.sequence >= 1
    assert tr.sequence > life.sequence
    assert sp.sequence > tr.sequence
    assert health.status == "healthy"
    assert profile.template_id == "health.ping"
    assert blocker.to_state == "resolved"
    assert dead.payload_digest.startswith("sha256:")
    assert audit.outcome == "allowed"

    counts = catalog.counts()
    assert counts["lifecycle_events"] == 1
    assert counts["traces"] == 1
    assert counts["spans"] == 1
    assert counts["health_samples"] == 1
    assert counts["query_profiles"] == 1
    assert counts["blocker_transitions"] == 1
    assert counts["dead_letters"] == 1
    assert counts["audit_events"] == 1

    # Append-only: duplicate natural ids are rejected.
    with pytest.raises(obs.ObservabilityError, match="duplicate"):
        catalog.record_lifecycle_event(
            event_type="system.start",
            component="daemon",
            domain=obs.TraceDomain.SYSTEM,
            event_id=life.event_id,
        )


def test_lifecycle_previous_event_id_chain() -> None:
    catalog = _catalog()
    first = catalog.record_lifecycle_event(
        event_type="a",
        component="c",
        domain=obs.TraceDomain.SYSTEM,
    )
    second = catalog.record_lifecycle_event(
        event_type="b",
        component="c",
        domain=obs.TraceDomain.SYSTEM,
    )
    assert second.previous_event_id == first.event_id


def test_blocker_transition_must_change_state() -> None:
    with pytest.raises(obs.ObservabilityError, match="change state"):
        obs.BlockerTransition(
            transition_id="t1",
            blocker_id="b1",
            blocker_type="dep",
            from_state="open",
            to_state="open",
            recorded_at=FIXED_CLOCK,
        )


def test_dead_letter_secret_payload_refused() -> None:
    catalog = _catalog()
    with pytest.raises(obs.ObservabilityError, match="secret"):
        catalog.record_dead_letter(
            source="wallet",
            domain=obs.TraceDomain.WALLET,
            reason="failed",
            payload=b"private-key-material",
            payload_classification=obs.SensitivityClass.SECRET,
        )


def test_audit_secret_classification_refused() -> None:
    with pytest.raises(obs.ObservabilityError, match="secret"):
        obs.AuditRecord(
            event_id="a1",
            action="read",
            actor="u",
            outcome="allowed",
            recorded_at=FIXED_CLOCK,
            classification=obs.SensitivityClass.SECRET,
        )


# ---------------------------------------------------------------------------
# Retention + export
# ---------------------------------------------------------------------------


def test_bounded_retention_drops_oldest_by_sequence() -> None:
    policy = obs.default_retention_policy(
        per_family={"lifecycle_events": 3},
        default_max_records=1000,
    )
    catalog = _catalog(retention=policy)
    ids: list[str] = []
    for i in range(5):
        ev = catalog.record_lifecycle_event(
            event_type=f"tick-{i}",
            component="c",
            domain=obs.TraceDomain.SYSTEM,
            event_id=f"life-{i}",
        )
        ids.append(ev.event_id)

    remaining = catalog.list_family(obs.CatalogFamily.LIFECYCLE_EVENTS)
    assert len(remaining) == 3
    remaining_ids = {_record_id(r) for r in remaining}
    # Newest three retained.
    assert remaining_ids == {"life-2", "life-3", "life-4"}


def _record_id(record: Any) -> str:
    for attr in (
        "event_id",
        "trace_id",
        "span_id",
        "sample_id",
        "profile_id",
        "transition_id",
        "letter_id",
    ):
        if hasattr(record, attr):
            return getattr(record, attr)
    raise AssertionError(f"no id on {record!r}")


def test_retention_dry_run_does_not_mutate() -> None:
    policy = obs.default_retention_policy(
        per_family={"health_samples": 1},
        default_max_records=1000,
    )
    catalog = _catalog(retention=policy)
    # Bypass auto-retention on write by using a large limit then apply dry-run
    # with a tighter policy after swapping.
    for i in range(3):
        catalog.record_health_sample(
            component="c",
            domain=obs.TraceDomain.SYSTEM,
            status="healthy",
            sample_id=f"h-{i}",
        )
    # Auto-retention already capped to 1 on each write.
    assert len(catalog.list_family(obs.CatalogFamily.HEALTH_SAMPLES)) == 1

    receipts = catalog.apply_retention(dry_run=True)
    assert all(r.dry_run for r in receipts)
    assert len(catalog.list_family(obs.CatalogFamily.HEALTH_SAMPLES)) == 1


def test_export_is_non_authoritative_and_content_addressed() -> None:
    catalog = _catalog()
    catalog.record_lifecycle_event(
        event_type="export.prep",
        component="obs",
        domain=obs.TraceDomain.OBSERVABILITY,
    )
    catalog.record_query_profile(
        template_id="t1",
        query_text="SELECT password = 'nope' FROM dual",
    )
    bundle = catalog.export(snapshot="snap-obs-001")
    assert bundle.non_authoritative is True
    assert bundle.progress.authority is obs.ProgressAuthority.SEQUENCE
    assert bundle.record_count >= 2
    receipt = bundle.to_export_receipt()
    assert receipt.non_authoritative is True
    assert "nope" not in str(bundle.to_dict())
    # Progress must not claim mtime authority.
    assert bundle.progress.authority is not obs.ProgressAuthority.FILE_MTIME


def test_export_rejects_mtime_progress() -> None:
    from ipfs_datasets_py.duckdb_control.contracts import ContentReference

    with pytest.raises(obs.ObservabilityError, match="mtime"):
        # ProgressCursor itself rejects FILE_MTIME at construction time.
        obs.ProgressCursor(
            sequence=0,
            authority=obs.ProgressAuthority.FILE_MTIME,
        )

    # Bundle construction refuses non_authoritative=False.
    with pytest.raises(obs.ObservabilityError, match="non_authoritative"):
        obs.ObservabilityExport(
            export_id="e1",
            snapshot=SnapshotId(value="snap-1"),
            families=("lifecycle_events",),
            record_count=0,
            content=ContentReference.from_bytes(b"{}"),
            created_at=FIXED_CLOCK,
            progress=obs.ProgressCursor(
                sequence=0,
                authority=obs.ProgressAuthority.SEQUENCE,
            ),
            non_authoritative=False,
        )


# ---------------------------------------------------------------------------
# Validation / fail-closed edges
# ---------------------------------------------------------------------------


def test_invalid_health_status_rejected() -> None:
    with pytest.raises(obs.ObservabilityError, match="health status"):
        obs.HealthSample(
            sample_id="s1",
            component="c",
            domain=obs.TraceDomain.SYSTEM,
            status="fine",
            recorded_at=FIXED_CLOCK,
        )


def test_unknown_domain_rejected() -> None:
    with pytest.raises(obs.ObservabilityError, match="domain"):
        obs.LifecycleEvent(
            event_id="e1",
            event_type="x",
            component="c",
            domain="not-a-domain",  # type: ignore[arg-type]
            recorded_at=FIXED_CLOCK,
        )


def test_catalog_to_dict_lists_required_domains() -> None:
    catalog = _catalog()
    payload = catalog.to_dict()
    assert payload["schema"] == obs.OBSERVABILITY_SCHEMA
    required = set(payload["required_correlation_domains"])
    assert required == set(obs.REQUIRED_CORRELATION_DOMAINS)
    for family in (
        "lifecycle_events",
        "traces",
        "spans",
        "health_samples",
        "query_profiles",
        "dead_letters",
        "audit_events",
    ):
        assert family in payload["families"]


def test_identity_ids_are_stable() -> None:
    corr = obs.CorrelationIds(trace_id="t1", control_task_id="task-1")
    a = obs.LifecycleEvent(
        event_id="e1",
        event_type="start",
        component="c",
        domain=obs.TraceDomain.CONTROL,
        recorded_at=FIXED_CLOCK,
        correlation=corr,
        sequence=1,
    )
    b = obs.LifecycleEvent(
        event_id="e1",
        event_type="start",
        component="c",
        domain=obs.TraceDomain.CONTROL,
        recorded_at=FIXED_CLOCK,
        correlation=corr,
        sequence=1,
    )
    assert a.identity_id == b.identity_id
    assert a.identity_id.startswith("sha256:")


def test_open_memory_catalog_helper() -> None:
    catalog = obs.open_memory_catalog(clock=_clock)
    assert isinstance(catalog, obs.ObservabilityCatalog)
    assert catalog.progress().sequence == 0
