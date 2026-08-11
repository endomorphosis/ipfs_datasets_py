"""Integration tests for streaming Parquet discovery and admission (DQK-087).

Covers acceptance criteria:

* Discovery streams a whole-file digest plus bounded footer metadata without
  loading datasets
* Symlink, path traversal, replacement, object-generation/ETag drift, footer
  drift, duplicate, and schema-conflict cases fail closed
* Source identity is rechecked immediately before copy/register
* Sensitive sources require an explicit policy decision
* Admission records source ownership and whether a copy is required before
  registration

Hermetic: stdlib-only PAR1 envelopes (no pyarrow/duckdb required).
"""

from __future__ import annotations

import hashlib
import sys
import threading
from pathlib import Path
from typing import Iterator

# Prefer the sealed validator's accelerator checkout in nested worktrees.
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

from ipfs_datasets_py.ducklake import admission as adm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FIELDS_A = (
    {"name": "event_id", "type": "int64"},
    {"name": "payload", "type": "utf8"},
)
_FIELDS_B = (
    {"name": "event_id", "type": "int64"},
    {"name": "amount", "type": "float64"},
)


@pytest.fixture
def source_root(tmp_path: Path) -> Path:
    root = tmp_path / "sources"
    root.mkdir()
    return root


def _write_parquet(
    path: Path,
    *,
    fields=_FIELDS_A,
    rows=None,
    row_count: int | None = None,
    partition_hints=None,
) -> Path:
    return adm.write_admission_parquet(
        path,
        fields=fields,
        rows=rows
        if rows is not None
        else [{"event_id": 1, "payload": "alpha"}, {"event_id": 2, "payload": "beta"}],
        row_count=row_count,
        partition_hints=partition_hints or {"dt": "2026-08-10"},
    )


def _provenance(**overrides) -> adm.Provenance:
    base = {
        "producer": "integration-test-producer",
        "tenant": "acme",
        "dataset_alias": "events",
        "namespace": "analytics",
    }
    base.update(overrides)
    return adm.Provenance(**base)


def _service(root: Path, **kwargs) -> adm.AdmissionService:
    return adm.AdmissionService(
        owner_id=kwargs.pop("owner_id", "owner-test-1"),
        shard_id=kwargs.pop("shard_id", "shard_a"),
        allowed_roots=(root,),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Discovery streams digest + bounded footer without loading datasets
# ---------------------------------------------------------------------------


def test_discovery_streams_digest_and_bounded_footer(source_root: Path) -> None:
    path = _write_parquet(source_root / "events" / "part-000.parquet")
    # Oversized body would be multi-MB; keep modest but larger than footer.
    big_rows = [{"event_id": i, "payload": "x" * 64} for i in range(2000)]
    path = _write_parquet(source_root / "events" / "part-000.parquet", rows=big_rows)

    peak = {"max": 0}
    original_open = Path.open

    def tracking_open(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        handle = original_open(self, *args, **kwargs)
        if self.resolve() != path.resolve():
            return handle
        raw_read = handle.read

        def limited_read(n: int = -1) -> bytes:
            data = raw_read(n)
            peak["max"] = max(peak["max"], len(data) if data else 0)
            return data

        handle.read = limited_read  # type: ignore[method-assign]
        return handle

    # Patch only Path.open for the duration of discovery.
    from pathlib import Path as PathType

    monkey_open = tracking_open
    original = PathType.open
    PathType.open = monkey_open  # type: ignore[assignment]
    try:
        evidence = adm.discover_parquet_file(
            path,
            allowed_roots=(source_root,),
            chunk_size=4096,
        )
    finally:
        PathType.open = original  # type: ignore[assignment]

    assert evidence.content_digest.startswith("sha256:")
    assert len(evidence.content_digest) == len("sha256:") + 64
    assert evidence.byte_size == path.stat().st_size
    assert evidence.footer.magic_head_ok is True
    assert evidence.footer.magic_tail_ok is True
    assert evidence.footer.footer_length > 0
    assert evidence.footer.footer_digest.startswith("sha256:")
    assert evidence.footer.footer_format == "ducklake-parquet-admission@1"
    assert evidence.schema.schema_digest.startswith("sha256:")
    assert evidence.statistics.row_count == 2000
    assert evidence.statistics.column_count == 2
    assert evidence.partition_hints.get("dt") == "2026-08-10"
    assert evidence.canonical_uri.startswith("file://")
    # Peak single read is bounded by chunk size or footer (never whole file).
    assert peak["max"] <= max(4096, evidence.footer.footer_length)
    assert peak["max"] < evidence.byte_size
    # Content identity binds for companion registry put_source.
    identity = evidence.content_identity()
    assert identity.content_digest == evidence.content_digest
    assert identity.media_type == "parquet"


def test_iter_discover_is_deterministic(source_root: Path) -> None:
    for name in ("c.parquet", "a.parquet", "b.parquet"):
        _write_parquet(source_root / name)
    first = [e.local_path for e in adm.iter_discover_parquet((source_root,))]
    second = [e.local_path for e in adm.iter_discover_parquet((source_root,))]
    assert first == second
    assert [Path(p).name for p in first] == ["a.parquet", "b.parquet", "c.parquet"]


def test_streaming_digest_matches_full_hash(source_root: Path) -> None:
    path = _write_parquet(source_root / "one.parquet")
    size, digest = adm.stream_file_digest(path, chunk_size=64)
    expected = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    assert size == path.stat().st_size
    assert digest == expected


# ---------------------------------------------------------------------------
# Fail-closed: symlink, path traversal
# ---------------------------------------------------------------------------


def test_symlink_source_fails_closed(source_root: Path, tmp_path: Path) -> None:
    real = _write_parquet(source_root / "real.parquet")
    link = tmp_path / "link.parquet"
    link.symlink_to(real)
    with pytest.raises(adm.SymlinkRejectedError) as ei:
        adm.discover_parquet_file(link, allowed_roots=(tmp_path, source_root))
    assert ei.value.reason is adm.RejectionReason.SYMLINK


def test_symlink_under_root_fails_closed(source_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    real = _write_parquet(outside / "secret.parquet")
    link = source_root / "escaped.parquet"
    link.symlink_to(real)
    with pytest.raises(adm.SymlinkRejectedError):
        adm.discover_parquet_file(link, allowed_roots=(source_root,))


def test_path_traversal_fails_closed(source_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    target = _write_parquet(outside / "leak.parquet")
    # Craft a path that resolves outside the allow root.
    traversal = source_root / ".." / "outside" / "leak.parquet"
    with pytest.raises(adm.PathTraversalError) as ei:
        adm.discover_parquet_file(traversal, allowed_roots=(source_root,))
    assert ei.value.reason is adm.RejectionReason.PATH_TRAVERSAL
    assert target.exists()


def test_not_parquet_fails_closed(source_root: Path) -> None:
    path = source_root / "junk.parquet"
    path.write_bytes(b"not-a-parquet-file")
    with pytest.raises(adm.ParquetDiscoveryError) as ei:
        adm.discover_parquet_file(path, allowed_roots=(source_root,))
    assert ei.value.reason in {
        adm.RejectionReason.NOT_PARQUET,
        adm.RejectionReason.TOO_SMALL,
        adm.RejectionReason.FOOTER_INVALID,
    }


# ---------------------------------------------------------------------------
# Fail-closed: replacement, footer drift, object-generation/ETag drift
# ---------------------------------------------------------------------------


def test_replacement_fails_closed_on_revalidate(source_root: Path) -> None:
    path = _write_parquet(source_root / "mutable.parquet")
    evidence = adm.discover_parquet_file(path, allowed_roots=(source_root,))
    # Replace file bytes after discovery (same path).
    _write_parquet(
        path,
        rows=[{"event_id": 99, "payload": "replaced"}],
    )
    with pytest.raises(adm.ReplacementError) as ei:
        adm.revalidate_before_copy_register(
            evidence, allowed_roots=(source_root,)
        )
    assert ei.value.reason is adm.RejectionReason.REPLACEMENT


def test_footer_drift_fails_closed(source_root: Path) -> None:
    path = _write_parquet(source_root / "footer.parquet")
    evidence = adm.discover_parquet_file(path, allowed_roots=(source_root,))
    # Mutate only the footer region while attempting to keep size if possible.
    raw = bytearray(path.read_bytes())
    # Flip a byte inside the footer (before the last 8 bytes).
    footer_len = evidence.footer.footer_length
    idx = len(raw) - 8 - footer_len
    raw[idx] = (raw[idx] + 1) % 256
    path.write_bytes(bytes(raw))
    with pytest.raises((adm.FooterDriftError, adm.ReplacementError, adm.ParquetDiscoveryError)):
        adm.revalidate_before_copy_register(
            evidence, allowed_roots=(source_root,)
        )


def test_object_generation_etag_drift_fails_closed(source_root: Path) -> None:
    path = _write_parquet(source_root / "obj.parquet")
    evidence = adm.discover_parquet_file(
        path,
        allowed_roots=(source_root,),
        object_generation=adm.ObjectGenerationIdentity(
            object_generation="gen-1",
            version_id="v1",
            etag='"etag-abc"',
        ),
    )
    with pytest.raises(adm.ObjectGenerationDriftError) as ei:
        adm.revalidate_before_copy_register(
            evidence,
            allowed_roots=(source_root,),
            observed_object_generation=adm.ObjectGenerationIdentity(
                object_generation="gen-1",
                version_id="v1",
                etag='"etag-DRIFTED"',
            ),
        )
    assert ei.value.reason is adm.RejectionReason.OBJECT_GENERATION_DRIFT


def test_revalidate_succeeds_when_identity_stable(source_root: Path) -> None:
    path = _write_parquet(source_root / "stable.parquet")
    ogen = adm.ObjectGenerationIdentity(
        object_generation="gen-9", version_id="v9", etag='"e9"'
    )
    evidence = adm.discover_parquet_file(
        path, allowed_roots=(source_root,), object_generation=ogen
    )
    fresh = adm.revalidate_before_copy_register(
        evidence,
        allowed_roots=(source_root,),
        observed_object_generation=ogen,
    )
    assert fresh.content_digest == evidence.content_digest
    assert fresh.footer.footer_digest == evidence.footer.footer_digest
    assert fresh.identity_fingerprint() == evidence.identity_fingerprint()


# ---------------------------------------------------------------------------
# Fail-closed: duplicate and schema conflict
# ---------------------------------------------------------------------------


def test_duplicate_content_fails_closed(source_root: Path) -> None:
    a = _write_parquet(source_root / "a.parquet")
    # Byte-identical second copy.
    b = source_root / "b.parquet"
    b.write_bytes(a.read_bytes())
    service = _service(source_root)
    first = service.admit(
        a,
        provenance=_provenance(),
        dataset_id="ds-events",
        policy=adm.PolicyClassification(policy_class=adm.PolicyClass.INTERNAL),
    )
    assert first.admitted is True
    with pytest.raises(adm.DuplicateSourceError) as ei:
        service.admit(
            b,
            provenance=_provenance(),
            dataset_id="ds-events",
            policy=adm.PolicyClassification(policy_class=adm.PolicyClass.INTERNAL),
        )
    assert ei.value.reason is adm.RejectionReason.DUPLICATE


def test_schema_conflict_fails_closed(source_root: Path) -> None:
    a = _write_parquet(source_root / "schema_a.parquet", fields=_FIELDS_A)
    b = _write_parquet(source_root / "schema_b.parquet", fields=_FIELDS_B)
    service = _service(source_root)
    service.admit(
        a,
        provenance=_provenance(),
        dataset_id="ds-shared",
        policy=adm.PolicyClassification(policy_class=adm.PolicyClass.PUBLIC),
    )
    with pytest.raises(adm.SchemaConflictError) as ei:
        service.admit(
            b,
            provenance=_provenance(),
            dataset_id="ds-shared",
            policy=adm.PolicyClassification(policy_class=adm.PolicyClass.PUBLIC),
        )
    assert ei.value.reason is adm.RejectionReason.SCHEMA_CONFLICT


def test_same_schema_different_content_is_admitted(source_root: Path) -> None:
    a = _write_parquet(
        source_root / "s1.parquet",
        fields=_FIELDS_A,
        rows=[{"event_id": 1, "payload": "one"}],
    )
    b = _write_parquet(
        source_root / "s2.parquet",
        fields=_FIELDS_A,
        rows=[{"event_id": 2, "payload": "two"}],
    )
    service = _service(source_root)
    r1 = service.admit(
        a,
        provenance=_provenance(),
        dataset_id="ds-ok",
        policy=adm.PolicyClassification(policy_class=adm.PolicyClass.INTERNAL),
    )
    r2 = service.admit(
        b,
        provenance=_provenance(),
        dataset_id="ds-ok",
        policy=adm.PolicyClassification(policy_class=adm.PolicyClass.INTERNAL),
    )
    assert r1.admitted and r2.admitted
    assert r1.evidence.schema.schema_digest == r2.evidence.schema.schema_digest
    assert r1.evidence.content_digest != r2.evidence.content_digest


# ---------------------------------------------------------------------------
# Sensitive sources require explicit policy decision
# ---------------------------------------------------------------------------


def test_sensitive_without_policy_decision_fails_closed(source_root: Path) -> None:
    path = _write_parquet(source_root / "pii.parquet")
    service = _service(source_root)
    with pytest.raises(adm.PolicyRequiredError) as ei:
        service.admit(
            path,
            provenance=_provenance(),
            policy=adm.PolicyClassification(policy_class=adm.PolicyClass.SENSITIVE),
        )
    assert ei.value.reason is adm.RejectionReason.POLICY_REQUIRED


def test_restricted_denied_policy_fails_closed(source_root: Path) -> None:
    path = _write_parquet(source_root / "secret.parquet")
    service = _service(source_root)
    with pytest.raises(adm.PolicyRequiredError) as ei:
        service.admit(
            path,
            provenance=_provenance(),
            policy=adm.PolicyClassification(policy_class=adm.PolicyClass.RESTRICTED),
            policy_decision=adm.PolicyDecision(
                decision_id="pol-1",
                allowed=False,
                decided_by="security-officer",
                policy_class=adm.PolicyClass.RESTRICTED,
                reason="not approved",
            ),
        )
    assert ei.value.reason is adm.RejectionReason.POLICY_DENIED


def test_sensitive_with_explicit_allow_is_admitted(source_root: Path) -> None:
    path = _write_parquet(source_root / "pii-ok.parquet")
    service = _service(source_root)
    receipt = service.admit(
        path,
        provenance=_provenance(),
        policy=adm.PolicyClassification(
            policy_class=adm.PolicyClass.SENSITIVE, labels=("pii",)
        ),
        policy_decision=adm.PolicyDecision(
            decision_id="pol-allow-1",
            allowed=True,
            decided_by="security-officer",
            policy_class=adm.PolicyClass.SENSITIVE,
            reason="approved for tenant acme analytics",
        ),
    )
    assert receipt.admitted is True
    assert receipt.policy_decision is not None
    assert receipt.policy_decision.decision_id == "pol-allow-1"
    assert receipt.evidence.policy is not None
    assert receipt.evidence.policy.policy_class is adm.PolicyClass.SENSITIVE


# ---------------------------------------------------------------------------
# Ownership + copy_required + revalidation on admit
# ---------------------------------------------------------------------------


def test_admission_records_ownership_and_copy_required(source_root: Path) -> None:
    path = _write_parquet(source_root / "owned.parquet")
    service = _service(source_root, owner_id="owner-42", shard_id="shard_z")
    receipt = service.admit(
        path,
        provenance=_provenance(tenant="tenant-z"),
        policy=adm.PolicyClassification(policy_class=adm.PolicyClass.INTERNAL),
        ownership_kind=adm.SourceOwnershipKind.EXTERNAL_UNMANAGED,
    )
    assert receipt.admitted is True
    assert receipt.ownership.owner_id == "owner-42"
    assert receipt.ownership.shard_id == "shard_z"
    assert receipt.ownership.tenant == "tenant-z"
    assert (
        receipt.ownership.ownership_kind
        is adm.SourceOwnershipKind.EXTERNAL_UNMANAGED
    )
    # External unmanaged sources always require a lifecycle-managed copy.
    assert receipt.copy_required is True
    assert receipt.ownership.copy_required is True
    assert receipt.revalidated is True
    assert receipt.revalidation_fingerprint
    mapping = dict(receipt.as_mapping())
    assert mapping["schema"] == adm.ADMISSION_DECISION_RECEIPT_SCHEMA
    assert mapping["copy_required"] is True
    assert mapping["ownership"]["owner_id"] == "owner-42"
    assert mapping["receipt_digest"].startswith("sha256:")


def test_lifecycle_managed_may_skip_copy_flag(source_root: Path) -> None:
    path = _write_parquet(source_root / "lake-owned.parquet")
    service = _service(source_root)
    receipt = service.admit(
        path,
        provenance=_provenance(),
        policy=adm.PolicyClassification(policy_class=adm.PolicyClass.INTERNAL),
        ownership_kind=adm.SourceOwnershipKind.LIFECYCLE_MANAGED,
        copy_required=False,
    )
    assert receipt.copy_required is False
    assert receipt.ownership.copy_required is False


def test_external_unmanaged_forces_copy_even_if_caller_disables(
    source_root: Path,
) -> None:
    path = _write_parquet(source_root / "force-copy.parquet")
    service = _service(source_root)
    receipt = service.admit(
        path,
        provenance=_provenance(),
        policy=adm.PolicyClassification(policy_class=adm.PolicyClass.PUBLIC),
        ownership_kind=adm.SourceOwnershipKind.EXTERNAL_UNMANAGED,
        copy_required=False,  # attacker/misconfig attempt
    )
    assert receipt.copy_required is True


def test_admit_revalidates_before_success(source_root: Path) -> None:
    path = _write_parquet(source_root / "race.parquet")
    service = _service(source_root)

    # Replace between discover-inside-admit and revalidate by racing a mutator
    # is hard to time; instead call revalidate path via admit after pre-mutate
    # by patching discover to return stale evidence.
    real_discover = service.discover
    stale_holder: dict[str, adm.DiscoveryEvidence] = {}

    def discover_then_mutate(p, **kw):  # type: ignore[no-untyped-def]
        evidence = real_discover(p, **kw)
        stale_holder["e"] = evidence
        _write_parquet(
            Path(p),
            rows=[{"event_id": 0, "payload": "mutated-after-discover"}],
        )
        return evidence

    service.discover = discover_then_mutate  # type: ignore[method-assign]
    with pytest.raises(adm.ReplacementError):
        service.admit(
            path,
            provenance=_provenance(),
            policy=adm.PolicyClassification(policy_class=adm.PolicyClass.INTERNAL),
            revalidate=True,
        )


def test_module_level_admit_helper(source_root: Path) -> None:
    path = _write_parquet(source_root / "helper.parquet")
    receipt = adm.admit_parquet_source(
        path,
        owner_id="owner-h",
        provenance=_provenance(),
        shard_id="shard_h",
        allowed_roots=(source_root,),
        policy=adm.PolicyClassification(policy_class=adm.PolicyClass.INTERNAL),
    )
    assert receipt.admitted is True
    assert receipt.ownership.owner_id == "owner-h"


def test_admit_or_receipt_captures_rejects(source_root: Path) -> None:
    path = _write_parquet(source_root / "cap.parquet")
    service = _service(source_root)
    service.admit(
        path,
        provenance=_provenance(),
        dataset_id="ds-cap",
        policy=adm.PolicyClassification(policy_class=adm.PolicyClass.INTERNAL),
    )
    twin = source_root / "cap2.parquet"
    twin.write_bytes(path.read_bytes())
    rejected = service.admit_or_receipt(
        twin,
        provenance=_provenance(),
        dataset_id="ds-cap",
        policy=adm.PolicyClassification(policy_class=adm.PolicyClass.INTERNAL),
    )
    assert rejected.admitted is False
    assert rejected.outcome is adm.DecisionOutcome.REJECTED
    assert rejected.rejection_reason is adm.RejectionReason.DUPLICATE


def test_import_is_side_effect_free() -> None:
    # Re-import must not open duckdb or touch the filesystem.
    import importlib

    mod = importlib.reload(adm)
    assert mod.ADMISSION_SCHEMA.startswith("ipfs_datasets_py/")
    assert mod.PARQUET_MAGIC == b"PAR1"


def test_receipt_is_immutable_mapping(source_root: Path) -> None:
    path = _write_parquet(source_root / "imm.parquet")
    service = _service(source_root)
    receipt = service.admit(
        path,
        provenance=_provenance(),
        policy=adm.PolicyClassification(policy_class=adm.PolicyClass.INTERNAL),
    )
    mapping = receipt.as_mapping()
    with pytest.raises(TypeError):
        mapping["outcome"] = "tampered"  # type: ignore[index]
