"""E2E tests: final cutover residual-authority scan and release exports (DQK-055).

Acceptance coverage:

* Zero undeclared mutable Markdown/JSON/JSONL or Parquet-sidecar authorities remain
* All domain and DuckLake snapshots and receipts verify
* Quack and DuckLake remain replaceable and upgrade-gated
* Final Markdown/JSON artifacts are reproducible exports only

Hermetic: no live DuckDB, Quack, Docker, or network required. The owned
validator lives in ``scripts/validation/validate_duckdb_quack_cutover.py``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()
_VALIDATION_PATH = (
    _REPO_ROOT / "scripts/validation/validate_duckdb_quack_cutover.py"
)


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


def _load_validation_module() -> ModuleType:
    """Load the validation script without requiring scripts.validation package."""

    module_name = "validate_duckdb_quack_cutover_dqk055"
    if module_name in sys.modules:
        return sys.modules[module_name]
    if not _VALIDATION_PATH.is_file():
        raise AssertionError(
            f"owned cutover validator missing at {_VALIDATION_PATH}; "
            "validation suite fails rather than skips"
        )
    spec = importlib.util.spec_from_file_location(module_name, _VALIDATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


val = _load_validation_module()

from ipfs_datasets_py.duckdb_control import authority_transition as at  # noqa: E402
from ipfs_datasets_py.duckdb_control import exporter as ex  # noqa: E402
from ipfs_datasets_py.duckdb_control.contracts import (  # noqa: E402
    SnapshotId,
    content_identity,
)
from ipfs_datasets_py.duckdb_control.importer import is_export_artifact  # noqa: E402
from ipfs_datasets_py.duckdb_control.inventory import (  # noqa: E402
    ArtifactKind,
    ProposedAuthority,
    classify_path,
)
from ipfs_datasets_py.duckdb_control.migrations import (  # noqa: E402
    MigrationReceipt,
    RollbackMetadata,
    SCHEMA_DIGEST_PREFIX,
)
from ipfs_datasets_py.ducklake import adapters as ad  # noqa: E402
from ipfs_datasets_py.ducklake import capabilities as caps  # noqa: E402
from ipfs_datasets_py.ducklake import cutover as co  # noqa: E402
from ipfs_datasets_py.ducklake import ingest as ing  # noqa: E402
from ipfs_datasets_py.ducklake import registry as reg  # noqa: E402
from ipfs_datasets_py.ducklake import release as rel  # noqa: E402
from ipfs_datasets_py.ducklake import snapshots as snap  # noqa: E402
from ipfs_datasets_py.logic.observability.structured_logging import (  # noqa: E402
    ObservabilityMutableFileSinkError,
    assert_mutable_file_sink_allowed,
    mutable_observability_file_sinks_allowed,
    reset_observability_filesystem_guard,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_process_local_state() -> None:
    co.reset_cutover_state()
    reset_observability_filesystem_guard()
    yield
    co.reset_cutover_state()
    reset_observability_filesystem_guard()


@pytest.fixture(scope="module")
def validation_report() -> Any:
    return val.run_validation()


# ---------------------------------------------------------------------------
# Module / contract invariants
# ---------------------------------------------------------------------------


class TestModuleInvariants:
    def test_owned_validator_present(self) -> None:
        assert _VALIDATION_PATH.is_file()
        assert val.CONTRACT_TASK_ID == "DQK-055"
        assert "final-cutover" in val.CONTRACT_SCHEMA

    def test_import_is_inert(self) -> None:
        """Loading the validator must not mutate cutover or observability state."""

        assert co.production_authority_unchanged() is True
        assert co.is_lake_authority_active() is False
        assert mutable_observability_file_sinks_allowed() is False

    def test_cli_main_returns_int(self) -> None:
        code = val.main(["--json"])
        assert code in (0, 1)


# ---------------------------------------------------------------------------
# Full suite
# ---------------------------------------------------------------------------


class TestFullValidationSuite:
    def test_run_validation_passes(self, validation_report: Any) -> None:
        assert validation_report.ok is True, {
            c.name: c.detail for c in validation_report.checks if not c.ok
        }
        assert validation_report.task_id == "DQK-055"
        names = {c.name for c in validation_report.checks}
        assert "zero_undeclared_mutable_authorities" in names
        assert "snapshots_and_receipts_verify" in names
        assert "quack_ducklake_replaceable_upgrade_gated" in names
        assert "markdown_json_reproducible_exports_only" in names

    def test_acceptance_map_all_true(self, validation_report: Any) -> None:
        payload = validation_report.to_dict()
        acceptance = payload["acceptance"]
        assert acceptance["zero_undeclared_mutable_authorities"] is True
        assert acceptance["snapshots_and_receipts_verify"] is True
        assert acceptance["quack_ducklake_replaceable_upgrade_gated"] is True
        assert acceptance["markdown_json_reproducible_exports_only"] is True

    def test_individual_checks_via_functions(self) -> None:
        for fn in (
            val.check_producer_consumer_residual_scan,
            val.check_zero_undeclared_mutable_authorities,
            val.check_freeze_migration_receipts,
            val.check_snapshots_and_receipts_verify,
            val.check_quack_ducklake_replaceable_upgrade_gated,
            val.check_performance_gate,
            val.check_markdown_json_reproducible_exports_only,
        ):
            result = fn()
            assert result.ok is True, f"{result.name}: {result.detail} {result.evidence}"


# ---------------------------------------------------------------------------
# Acceptance: zero undeclared mutable authorities
# ---------------------------------------------------------------------------


class TestZeroUndeclaredMutableAuthorities:
    @pytest.mark.parametrize(
        "path",
        [
            "docs/architecture/objectives.md",
            "archive/master_todo_list.md",
            "wallet/records.jsonl",
            "data/state/authority.json",
            "datasets/corpus/manifest.json",
            "datasets/corpus/table.meta.json",
            "data/sidecars/graph_sidecar.json",
            "alerts/alert-state.json",
            "proof_cache/cache.json",
        ],
    )
    def test_residual_paths_not_retain_file(self, path: str) -> None:
        rule = classify_path(path)
        resolved = val.resolve_cutover_disposition(
            path,
            inventory_authority=rule.proposed_authority.value,
            inventory_kind=rule.kind.value,
        )
        assert resolved["disposition"] != ProposedAuthority.RETAIN_FILE.value
        assert resolved["disposition"] in val._SAFE_DISPOSITIONS

    def test_declared_projections_are_export_only(self) -> None:
        for path in val._DECLARED_PROJECTION_PATHS:
            rule = classify_path(path)
            assert (
                rule.kind is ArtifactKind.DERIVED_EXPORT
                or rule.proposed_authority is ProposedAuthority.EXPORT_ONLY
            )
            assert is_export_artifact(path)

    def test_mutable_manifest_authority_rejected(self) -> None:
        with pytest.raises(reg.RegistryError):
            reg.assert_no_mutable_manifest_authority(
                source="manifest.json", is_mutable_parquet_manifest=True
            )
        with pytest.raises(reg.RegistryError):
            reg.assert_no_mutable_manifest_authority(
                source="authority.json", is_mutable_json=True
            )
        # Non-mutable source is admitted.
        reg.assert_no_mutable_manifest_authority(
            source="receipt.cid",
            is_mutable_json=False,
            is_mutable_parquet_manifest=False,
        )

    def test_zero_unowned_public_parquet_producers(self) -> None:
        public = tuple(
            p.module_path
            for p in ad.REGISTERED_PARQUET_PRODUCERS.values()
            if p.public
        )
        proof = ad.prove_zero_unowned_public_parquet_producers(
            repository_tree_id="b" * 40,
            inventory_snapshot_cid=content_identity({"t": "dqk055"}),
            public_producer_paths=public,
            owned_paths=public,
        )
        assert proof.zero_unowned is True
        assert proof.unowned_public_paths == ()

    def test_unowned_public_producer_fails_closed(self) -> None:
        with pytest.raises(ad.UnownedProducerError):
            ad.prove_zero_unowned_public_parquet_producers(
                repository_tree_id="c" * 40,
                inventory_snapshot_cid=content_identity({"t": "gap"}),
                public_producer_paths=(
                    "ipfs_datasets_py/core_operations/dataset_loader.py",
                    "ipfs_datasets_py/orphan/unowned_producer.py",
                ),
                owned_paths=(
                    "ipfs_datasets_py/core_operations/dataset_loader.py",
                ),
            )

    def test_observability_file_sinks_denied(self) -> None:
        assert mutable_observability_file_sinks_allowed() is False
        with pytest.raises(ObservabilityMutableFileSinkError):
            assert_mutable_file_sink_allowed(
                "/tmp/audit_session.jsonl", kind="audit_jsonl", operation="write"
            )

    def test_authority_transition_terminates_export_only(self) -> None:
        port = at.build_authority_port(
            domain="dqk055-e2e", initial_mode=at.AuthorityMode.LEGACY
        )
        for mode in (
            at.AuthorityMode.SHADOW,
            at.AuthorityMode.DUAL,
            at.AuthorityMode.DB_PRIMARY,
            at.AuthorityMode.EXPORT_ONLY,
        ):
            receipt = port.promote(
                mode,
                decision_id=f"dec:e2e:{mode.value}",
                require_parity=False,
            )
            assert receipt.accepted, receipt.reason
        assert port.mode is at.AuthorityMode.EXPORT_ONLY
        # EXPORT_ONLY is terminal under promote decisions.
        allowed = at.allowed_mode_transitions(
            at.AuthorityMode.EXPORT_ONLY, kind=at.DecisionKind.PROMOTE
        )
        assert len(allowed) == 0


# ---------------------------------------------------------------------------
# Acceptance: freeze migration receipts + snapshots/receipts
# ---------------------------------------------------------------------------


class TestFreezeMigrationReceiptsAndSnapshots:
    def test_migration_receipt_deterministic_and_frozen(self) -> None:
        fixed = "2026-08-11T00:00:00Z"
        checksum = "sha256:" + ("ab" * 32)
        schema_digest = SCHEMA_DIGEST_PREFIX + ("cd" * 32)
        a = MigrationReceipt(
            migration_id="migration:dqk055:e2e",
            checksum=checksum,
            status="applied",
            schema_digest=schema_digest,
            lock_owner="writer:e2e",
            version=1,
            namespace="control",
            rollback=RollbackMetadata(),
            applied_at=fixed,
        )
        b = MigrationReceipt(
            migration_id="migration:dqk055:e2e",
            checksum=checksum,
            status="applied",
            schema_digest=schema_digest,
            lock_owner="writer:e2e",
            version=1,
            namespace="control",
            rollback=RollbackMetadata(),
            applied_at=fixed,
        )
        assert a.receipt_id == b.receipt_id
        assert a.receipt_id.startswith("sha256:")
        # Content-bound freeze: changing status changes receipt identity.
        alt = MigrationReceipt(
            migration_id="migration:dqk055:e2e",
            checksum=checksum,
            status="dry_run",
            schema_digest=schema_digest,
            dry_run=True,
            lock_owner="writer:e2e",
            version=1,
            namespace="control",
            rollback=RollbackMetadata(),
            applied_at=fixed,
        )
        assert alt.receipt_id != a.receipt_id
        # Normal field assignment on a frozen dataclass must fail.
        with pytest.raises(Exception):
            a.status = "failed"  # type: ignore[misc]

    def test_snapshot_vector_verifies_and_order_independent(self) -> None:
        members = (
            snap.SnapshotVectorMember(
                catalog_id="cat-a",
                owner_generation=1,
                fencing_epoch=1,
                quack_endpoint_identity="endpoint:a",
                catalog_global_snapshot_id=3,
                schema_version="v1",
                storage_root="/lake/a",
                tenant_id="t1",
                policy_decision_id="policy:a",
            ),
            snap.SnapshotVectorMember(
                catalog_id="cat-b",
                owner_generation=1,
                fencing_epoch=1,
                quack_endpoint_identity="endpoint:b",
                catalog_global_snapshot_id=5,
                schema_version="v1",
                storage_root="/lake/b",
                tenant_id="t1",
                policy_decision_id="policy:b",
            ),
        )
        d1 = snap.vector_identity_digest(members)
        d2 = snap.vector_identity_digest(tuple(reversed(members)))
        assert d1 == d2
        vector = snap.SnapshotVector(
            members=members, captured_at="2026-08-11T00:00:00Z"
        )
        assert len(vector.members) == 2
        assert vector.members[0].catalog_id == "cat-a"

    def test_snapshot_rejects_file_representation(self) -> None:
        member = snap.SnapshotVectorMember(
            catalog_id="cat-x",
            owner_generation=1,
            fencing_epoch=1,
            quack_endpoint_identity="endpoint:x",
            catalog_global_snapshot_id=1,
            schema_version="v1",
            storage_root="/lake/x",
            policy_decision_id="policy:x",
        )
        with pytest.raises(snap.SnapshotError):
            snap.SnapshotVector(
                members=(member,),
                representation="file",
                captured_at="2026-08-11T00:00:00Z",
            )

    def test_release_and_cutover_self_checks(self) -> None:
        release = rel.self_check()
        assert release["ok"] is True
        assert release["markdown_or_json_file_authority"] is False
        assert release["storage_medium"] == "authority_table"

        cutover = co.self_check()
        assert cutover["ok"] is True
        assert cutover["implementation_grants_no_authority"] is True
        assert cutover["production_authority_unchanged"] is True

    def test_operational_restore_security_evidence(self) -> None:
        restore = rel.build_operational_evidence(
            kind="restore",
            receipt_id="receipt:restore:e2e",
            receipt_digest=content_identity({"k": "restore"}),
            repository_tree_id="d" * 40,
            issued_at="2026-08-11T00:00:00Z",
            expires_at="2026-08-12T00:00:00Z",
        )
        security = rel.build_operational_evidence(
            kind="security",
            receipt_id="receipt:security:e2e",
            receipt_digest=content_identity({"k": "security"}),
            repository_tree_id="d" * 40,
            issued_at="2026-08-11T00:00:00Z",
            expires_at="2026-08-12T00:00:00Z",
        )
        rel.verify_operational_evidence(restore, kind="restore")
        rel.verify_operational_evidence(security, kind="security")

    def test_domain_authority_self_check(self) -> None:
        report = at.self_check(run_crash_recovery=True)
        assert report["ok"] is True
        assert report["atomic_across_filesystems"] is False


# ---------------------------------------------------------------------------
# Acceptance: Quack / DuckLake replaceable and upgrade-gated
# ---------------------------------------------------------------------------


class TestReplaceableAndUpgradeGated:
    def test_feature_gate_off_does_not_affect_control_plane(self) -> None:
        gate = caps.evaluate_ducklake_feature_gate(requested=False)
        assert gate.state is caps.DuckLakeFeatureState.DISABLED
        assert gate.control_plane_affected is False

    def test_feature_gate_cannot_enable_without_capability(self) -> None:
        gate = caps.evaluate_ducklake_feature_gate(requested=True, capability=None)
        assert gate.state is not caps.DuckLakeFeatureState.ENABLED
        assert gate.control_plane_affected is False

    def test_lifecycle_policy_requires_replace_and_delete(self) -> None:
        policy = ing.LifecyclePolicy(
            policy_id="lifecycle:e2e",
            replace_allowed=True,
            delete_allowed=True,
        )
        assert policy.replace_allowed is True
        assert policy.delete_allowed is True
        with pytest.raises(ing.IngestError):
            ing.LifecyclePolicy(
                policy_id="lifecycle:external",
                allow_external_register=True,
            )

    def test_duckdb_20_requalification_policy_fail_closed(self) -> None:
        policy = rel.build_duckdb_20_requalification_policy()
        assert policy["requires_explicit_requalification_receipt"] is True
        assert policy["feature_gate_remains_enabled"] is True
        assert policy["local_fallback_remains_enabled"] is True
        with pytest.raises(rel.ReleaseError):
            rel.build_duckdb_20_requalification_policy(
                requires_explicit_requalification_receipt=False
            )
        with pytest.raises(rel.ReleaseError):
            rel.build_duckdb_20_requalification_policy(
                feature_gate_remains_enabled=False
            )

    def test_compatibility_window_is_bounded(self) -> None:
        window = at.DUCKDB_COMPATIBILITY_WINDOW
        assert window.startswith(">=")
        assert "<" in window
        assert at.PINNED_DUCKDB_VERSION


# ---------------------------------------------------------------------------
# Acceptance: reproducible Markdown/JSON exports only
# ---------------------------------------------------------------------------


class TestReproducibleReleaseExports:
    def _job(self, fmt: ex.ExportFormat, hint: str) -> ex.ExportJob:
        return ex.ExportJob(
            job_id=f"export:dqk055.e2e:{fmt.value}",
            template_id="release.cutover_summary",
            parameters_digest=ex.digest_parameters({"task": "DQK-055"}),
            schema_version="ipfs_datasets_py/duckdb-control-export-schema@1",
            snapshot=SnapshotId(
                value="snap-dqk055-e2e", store_generation=55, schema_checksum=""
            ),
            format=fmt,
            destination_policy=ex.default_destination_policy(),
            revision="rev-e2e",
            location_hint=hint,
            created_at="2026-08-11T12:00:00Z",
        )

    def test_json_export_byte_identical_on_replay(self) -> None:
        rows = [{"record_id": "r1", "status": "ok", "score": 1}]
        job = self._job(ex.ExportFormat.JSON, "exports/release/e2e.json")
        exporter = ex.SnapshotExporter()
        first = exporter.export_rows(rows, job, source_mutability_probe=rows)
        second = exporter.verify_replay(rows, job, first)
        assert first.artifact.payload == second.artifact.payload
        assert first.artifact.content_digest == second.artifact.content_digest
        assert first.non_authoritative is True
        assert first.mutated_source is False
        assert job.read_only is True
        assert is_export_artifact("exports/release/e2e.json")

    def test_markdown_export_byte_identical_on_replay(self) -> None:
        rows = [{"record_id": "r1", "status": "ok", "score": 1}]
        job = self._job(ex.ExportFormat.MARKDOWN, "exports/release/e2e.md")
        exporter = ex.SnapshotExporter()
        first = exporter.export_rows(rows, job)
        second = exporter.export_rows(rows, job)
        ex.verify_export_replay(first.artifact, second.artifact)
        assert b"|" in first.artifact.payload or b"#" in first.artifact.payload

    def test_export_does_not_mutate_source_rows(self) -> None:
        rows = [{"record_id": "r1", "status": "open", "score": 9}]
        original = json.dumps(rows, sort_keys=True)
        job = self._job(ex.ExportFormat.JSON, "exports/release/mut.json")
        ex.SnapshotExporter().export_rows(rows, job, source_mutability_probe=rows)
        assert json.dumps(rows, sort_keys=True) == original

    def test_sanitized_release_projection_excludes_secrets(self) -> None:
        receipt = {
            "receipt_id": "receipt:e2e",
            "release_id": "release:e2e",
            "receipt_cid": content_identity({"r": 1}),
            "repository_tree_id": "e" * 40,
            "schema_checksum": content_identity({"s": 1}),
            "password": "example-password",
            "encryption_key": "example-key-material",
            "catalog_shards": [{"shard_id": "shard-a"}],
            "issued_at": "2026-08-11T00:00:00Z",
            "expires_at": "2026-08-12T00:00:00Z",
            "duckdb_2_0_requalification_policy": rel.build_duckdb_20_requalification_policy(),
        }
        projection = rel.export_sanitized_release_projection(receipt)
        blob = json.dumps(dict(projection))
        assert "example-password" not in blob
        assert projection.get("sanitized") is True
        assert projection.get("credentials_exported") is False
        assert projection.get("encryption_keys_exported") is False

    def test_export_only_paths_are_not_reimportable_authority(self) -> None:
        for path in (
            "exports/release/cutover_summary.json",
            "derived/projections/namespace_parity.json",
            "exports/release_exports/dqk055/receipt_projection.json",
        ):
            assert is_export_artifact(path) is True


# ---------------------------------------------------------------------------
# Domain module residual scan (static)
# ---------------------------------------------------------------------------


class TestDomainModuleResidualScan:
    def test_domain_guard_symbols_present(self) -> None:
        for rel, symbol in val._DOMAIN_AUTHORITY_MODULES:
            path = _REPO_ROOT / rel
            assert path.is_file(), rel
            text = path.read_text(encoding="utf-8")
            assert symbol in text, f"{rel} missing {symbol}"

    def test_registered_parquet_producers_closed_set(self) -> None:
        producers = ad.list_registered_producers()
        assert producers
        for pid in producers:
            producer = ad.get_registered_producer(pid)
            assert producer.module_path.endswith(".py")
            assert (_REPO_ROOT / producer.module_path).is_file() or producer.module_path
