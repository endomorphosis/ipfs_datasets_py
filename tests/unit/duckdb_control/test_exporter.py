"""Unit tests for deterministic read-only exports (DQK-045).

Acceptance coverage:

* Repeated export of one snapshot is byte-identical
* An export cannot mutate or become implicit authority
* Sensitive columns are excluded by policy

Also covers query/template ID, parameters digest, schema version,
snapshot/revision, root CID, content digest, destination policy, and
replay verification for Markdown, JSON, Parquet, Arrow, and CAR formats.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import sys
from pathlib import Path
from typing import Any, Mapping

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

from ipfs_datasets_py.duckdb_control.contracts import (
    EXPORT_RECEIPT_SCHEMA,
    SnapshotId,
    content_identity,
)
from ipfs_datasets_py.duckdb_control.query_registry import (
    SENSITIVE_COLUMN_NAMES,
    ColumnClassification,
    ColumnPolicy,
)
from ipfs_datasets_py.duckdb_control import exporter as ex


FIXED_CLOCK = "2026-08-10T15:00:00Z"
TENANT_ROWS: list[dict[str, Any]] = [
    {"record_id": "r1", "status": "open", "score": 1},
    {"record_id": "r2", "status": "closed", "score": 2},
]


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _snapshot(value: str = "snap-export-001") -> SnapshotId:
    return SnapshotId(value=value, store_generation=3, schema_checksum="")


def _policy(**kwargs: Any) -> ex.DestinationPolicy:
    return ex.default_destination_policy(**kwargs)


def _job(
    *,
    job_id: str = "export:publication.list:json",
    template_id: str = "publication.list_records",
    format: ex.ExportFormat | str = ex.ExportFormat.JSON,
    params: Mapping[str, Any] | None = None,
    location_hint: str = "exports/publication/list.json",
    column_policy: ColumnPolicy | None = None,
    schema_version: str = "ipfs_datasets_py/duckdb-control-export-schema@1",
    revision: str = "rev-1",
    destination_policy: ex.DestinationPolicy | None = None,
) -> ex.ExportJob:
    return ex.ExportJob(
        job_id=job_id,
        template_id=template_id,
        parameters_digest=ex.digest_parameters(params or {"tenant_id": "alpha"}),
        schema_version=schema_version,
        snapshot=_snapshot(),
        format=format,
        destination_policy=destination_policy or _policy(),
        revision=revision,
        template_version=1,
        location_hint=location_hint,
        column_policy=column_policy,
        renderer_version=ex.RENDERER_VERSION,
        created_at=FIXED_CLOCK,
    )


def _column_policy(
    columns: Mapping[str, ColumnClassification] | None = None,
) -> ColumnPolicy:
    if columns is None:
        columns = {
            "record_id": ColumnClassification.PUBLIC,
            "status": ColumnClassification.PUBLIC,
            "score": ColumnClassification.PUBLIC,
        }
    return ColumnPolicy(columns=columns)


# ---------------------------------------------------------------------------
# Import inertness
# ---------------------------------------------------------------------------


def test_exporter_module_is_import_inert() -> None:
    """Importing exporter must not pull duckdb or open network resources."""

    banned = {"duckdb", "pyarrow"}
    # Inspect already-imported module graph rather than reloading (reload
    # would replace Enum classes and break later tests in this process).
    loaded = set(sys.modules)
    assert "ipfs_datasets_py.duckdb_control.exporter" in loaded
    assert not (banned & loaded)
    # Fresh import of the module object is a no-op when already present.
    mod = importlib.import_module("ipfs_datasets_py.duckdb_control.exporter")
    assert mod.EXPORTER_SCHEMA.endswith("@1")
    assert mod.RENDERER_VERSION.startswith("dqk-045")
    # Confirm dependency surface does not require duckdb at import time.
    assert not hasattr(mod, "duckdb")


# ---------------------------------------------------------------------------
# Acceptance: repeated export is byte-identical
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fmt",
    [
        ex.ExportFormat.JSON,
        ex.ExportFormat.MARKDOWN,
        ex.ExportFormat.PARQUET,
        ex.ExportFormat.ARROW,
        ex.ExportFormat.CAR,
    ],
)
def test_repeated_export_of_one_snapshot_is_byte_identical(
    fmt: ex.ExportFormat,
) -> None:
    rows = copy.deepcopy(TENANT_ROWS)
    hint_ext = {
        ex.ExportFormat.JSON: "json",
        ex.ExportFormat.MARKDOWN: "md",
        ex.ExportFormat.PARQUET: "parquet",
        ex.ExportFormat.ARROW: "arrow",
        ex.ExportFormat.CAR: "car",
    }[fmt]
    job = _job(
        job_id=f"export:publication.list:{fmt.value}",
        format=fmt,
        location_hint=f"exports/publication/list.{hint_ext}",
        column_policy=_column_policy(),
    )
    exporter = ex.SnapshotExporter()
    first = exporter.export_rows(rows, job)
    second = exporter.export_rows(rows, job)

    assert first.artifact.payload == second.artifact.payload
    assert first.content_digest == second.content_digest
    assert first.root_cid == second.root_cid
    assert first.artifact.byte_size == second.artifact.byte_size
    assert first.artifact.payload  # nonempty for these fixtures
    # Digest matches exact bytes.
    expected = "sha256:" + hashlib.sha256(first.artifact.payload).hexdigest()
    assert first.content_digest == expected
    assert first.root_cid == expected


def test_verify_replay_passes_for_identical_snapshot() -> None:
    job = _job(column_policy=_column_policy())
    exporter = ex.SnapshotExporter()
    original = exporter.export_rows(TENANT_ROWS, job)
    replayed = exporter.verify_replay(TENANT_ROWS, job, original)
    assert replayed.content_digest == original.content_digest
    assert replayed.artifact.payload == original.artifact.payload


def test_verify_replay_fails_when_rows_diverge() -> None:
    job = _job(column_policy=_column_policy())
    exporter = ex.SnapshotExporter()
    original = exporter.export_rows(TENANT_ROWS, job)
    mutated_rows = copy.deepcopy(TENANT_ROWS)
    mutated_rows[0]["score"] = 99
    with pytest.raises(ex.ReplayVerificationError, match="byte-identical"):
        exporter.verify_replay(mutated_rows, job, original)


def test_input_dict_key_order_does_not_affect_bytes() -> None:
    """Canonical key ordering yields identical payloads regardless of input order."""

    job = _job(column_policy=_column_policy())
    a = [{"score": 1, "record_id": "r1", "status": "open"}]
    b = [{"status": "open", "record_id": "r1", "score": 1}]
    exporter = ex.SnapshotExporter()
    ra = exporter.export_rows(a, job)
    rb = exporter.export_rows(b, job)
    assert ra.artifact.payload == rb.artifact.payload
    assert ra.content_digest == rb.content_digest


# ---------------------------------------------------------------------------
# Acceptance: cannot mutate or become implicit authority
# ---------------------------------------------------------------------------


def test_export_does_not_mutate_source_rows() -> None:
    source: list[dict[str, Any]] = [
        {"record_id": "r1", "status": "open", "score": 1},
        {"record_id": "r2", "status": "closed", "score": 2},
    ]
    original = copy.deepcopy(source)
    job = _job(column_policy=_column_policy())
    result = ex.SnapshotExporter().export_rows(
        source, job, source_mutability_probe=source
    )
    assert source == original
    assert result.mutated_source is False
    assert result.read_only is True
    assert result.non_authoritative is True
    assert result.receipt.non_authoritative is True
    assert result.receipt.to_dict()["non_authoritative"] is True
    assert result.job.read_only is True
    assert result.job.non_authoritative is True


def test_export_job_rejects_authoritative_flags() -> None:
    with pytest.raises(ex.ExportError, match="read_only"):
        ex.ExportJob(
            job_id="export:bad",
            template_id="publication.list_records",
            parameters_digest=ex.digest_parameters({}),
            schema_version="ipfs_datasets_py/duckdb-control-export-schema@1",
            snapshot=_snapshot(),
            format=ex.ExportFormat.JSON,
            destination_policy=_policy(),
            read_only=False,
            created_at=FIXED_CLOCK,
        )
    with pytest.raises(ex.ExportError, match="non_authoritative"):
        ex.ExportJob(
            job_id="export:bad2",
            template_id="publication.list_records",
            parameters_digest=ex.digest_parameters({}),
            schema_version="ipfs_datasets_py/duckdb-control-export-schema@1",
            snapshot=_snapshot(),
            format=ex.ExportFormat.JSON,
            destination_policy=_policy(),
            non_authoritative=False,
            created_at=FIXED_CLOCK,
        )


def test_destination_policy_forbids_authority_and_mutation() -> None:
    with pytest.raises(ex.DestinationPolicyViolation, match="non_authoritative"):
        ex.DestinationPolicy(
            policy_id="bad",
            allowed_formats=frozenset({ex.ExportFormat.JSON}),
            non_authoritative=False,
        )
    with pytest.raises(ex.DestinationPolicyViolation, match="source mutation"):
        ex.DestinationPolicy(
            policy_id="bad",
            allowed_formats=frozenset({ex.ExportFormat.JSON}),
            allow_source_mutation=True,
        )
    with pytest.raises(ex.DestinationPolicyViolation, match="authority"):
        ex.DestinationPolicy(
            policy_id="bad",
            allowed_formats=frozenset({ex.ExportFormat.JSON}),
            forbid_authority_paths=False,
        )


def test_destination_policy_rejects_authority_paths() -> None:
    policy = _policy()
    with pytest.raises(ex.DestinationPolicyViolation, match="authority"):
        policy.validate_destination(
            format=ex.ExportFormat.JSON,
            location_hint="state/control/tasks.json",
        )
    with pytest.raises(ex.DestinationPolicyViolation, match="authority"):
        policy.validate_destination(
            format=ex.ExportFormat.JSON,
            location_hint="exports/../control/ledger.json",
        )
    with pytest.raises(ex.DestinationPolicyViolation, match="outside allowed"):
        policy.validate_destination(
            format=ex.ExportFormat.JSON,
            location_hint="data/scratch/out.json",
        )
    tight = ex.default_destination_policy(
        policy_id="json-only", formats=[ex.ExportFormat.JSON]
    )
    with pytest.raises(ex.DestinationPolicyViolation, match="not allowed"):
        tight.validate_destination(
            format=ex.ExportFormat.PARQUET,
            location_hint="exports/ok.parquet",
        )
    assert (
        tight.validate_destination(
            format=ex.ExportFormat.JSON, location_hint="exports/ok.json"
        )
        == "exports/ok.json"
    )


def test_result_cannot_claim_authority() -> None:
    job = _job(column_policy=_column_policy())
    result = ex.SnapshotExporter().export_rows(TENANT_ROWS, job)
    payload = result.to_dict()
    assert payload["non_authoritative"] is True
    assert payload["read_only"] is True
    assert payload["mutated_source"] is False
    assert payload["receipt"]["schema"] == EXPORT_RECEIPT_SCHEMA
    assert payload["receipt"]["non_authoritative"] is True
    # Receipt refuses authoritative construction via contracts.
    with pytest.raises(Exception):
        type(result.receipt)(
            export_id=result.receipt.export_id,
            snapshot=result.receipt.snapshot,
            content=result.receipt.content,
            created_at=result.receipt.created_at,
            renderer_version=result.receipt.renderer_version,
            non_authoritative=False,
        )


# ---------------------------------------------------------------------------
# Acceptance: sensitive columns excluded by policy
# ---------------------------------------------------------------------------


def test_sensitive_columns_are_rejected() -> None:
    rows = [
        {
            "record_id": "r1",
            "status": "open",
            "private_key": "hex-secret",
        }
    ]
    job = _job(
        column_policy=ColumnPolicy(
            columns={
                "record_id": ColumnClassification.PUBLIC,
                "status": ColumnClassification.PUBLIC,
            }
        )
    )
    with pytest.raises(ex.SensitiveColumnError, match="private_key"):
        ex.SnapshotExporter().export_rows(rows, job)


@pytest.mark.parametrize("name", sorted(SENSITIVE_COLUMN_NAMES))
def test_each_sensitive_name_is_forbidden(name: str) -> None:
    rows = [{"record_id": "r1", name: "secret-value"}]
    # Even without an explicit column policy, sensitive names fail closed.
    job = _job(column_policy=None, location_hint="exports/x.json")
    with pytest.raises(ex.SensitiveColumnError):
        ex.SnapshotExporter().export_rows(rows, job)


def test_column_policy_projects_only_allowlisted_columns() -> None:
    rows = [
        {
            "record_id": "r1",
            "status": "open",
            "score": 1,
            "internal_note": "drop-me",
        }
    ]
    policy = ColumnPolicy(
        columns={
            "record_id": ColumnClassification.PUBLIC,
            "status": ColumnClassification.PUBLIC,
        }
    )
    job = _job(column_policy=policy)
    result = ex.SnapshotExporter().export_rows(rows, job)
    assert set(result.artifact.projected_columns) == {"record_id", "status"}
    # Payload must not contain the dropped column.
    assert b"internal_note" not in result.artifact.payload
    assert b"drop-me" not in result.artifact.payload


def test_redacted_columns_are_masked() -> None:
    rows = [{"record_id": "r1", "email": "user@example.com"}]
    policy = ColumnPolicy(
        columns={
            "record_id": ColumnClassification.PUBLIC,
            "email": ColumnClassification.REDACTED,
        }
    )
    job = _job(column_policy=policy)
    result = ex.SnapshotExporter().export_rows(rows, job)
    assert b"user@example.com" not in result.artifact.payload
    assert b"***" in result.artifact.payload


# ---------------------------------------------------------------------------
# Job identity fields (template, params digest, schema, snapshot, root CID)
# ---------------------------------------------------------------------------


def test_job_binds_template_params_schema_snapshot_revision() -> None:
    params = {"tenant_id": "alpha", "limit": 10}
    job = _job(params=params, revision="rev-42", schema_version="1")
    assert job.query_id == job.template_id == "publication.list_records"
    assert job.parameters_digest == ex.digest_parameters(params)
    assert job.parameters_digest.startswith("sha256:")
    assert job.schema_version.endswith("@1")
    assert job.snapshot.value == "snap-export-001"
    assert job.snapshot.store_generation == 3
    assert job.revision == "rev-42"
    assert job.destination_policy.policy_id == "export:default"

    result = ex.SnapshotExporter().export_rows(TENANT_ROWS, job)
    d = result.to_dict()
    assert d["template_id"] == "publication.list_records"
    assert d["parameters_digest"] == job.parameters_digest
    assert d["schema_version"] == job.schema_version
    assert d["snapshot"]["value"] == "snap-export-001"
    assert d["revision"] == "rev-42"
    assert d["root_cid"].startswith("sha256:")
    assert d["content_digest"] == d["root_cid"]
    assert d["destination_policy"]["non_authoritative"] is True


def test_parameters_digest_is_order_independent() -> None:
    a = ex.digest_parameters({"b": 2, "a": 1})
    b = ex.digest_parameters({"a": 1, "b": 2})
    assert a == b == content_identity({"a": 1, "b": 2})


def test_different_snapshots_yield_different_content() -> None:
    job_a = _job()
    job_b = ex.ExportJob(
        job_id=job_a.job_id,
        template_id=job_a.template_id,
        parameters_digest=job_a.parameters_digest,
        schema_version=job_a.schema_version,
        snapshot=_snapshot("snap-other"),
        format=job_a.format,
        destination_policy=job_a.destination_policy,
        revision=job_a.revision,
        location_hint=job_a.location_hint,
        column_policy=_column_policy(),
        created_at=FIXED_CLOCK,
    )
    exporter = ex.SnapshotExporter()
    # Same rows, different snapshot envelope → different content digest.
    ra = exporter.export_rows(TENANT_ROWS, job_a)
    rb = exporter.export_rows(TENANT_ROWS, job_b)
    assert ra.content_digest != rb.content_digest
    assert ra.root_cid != rb.root_cid


def test_empty_result_is_deterministic() -> None:
    job = _job(column_policy=_column_policy())
    exporter = ex.SnapshotExporter()
    a = exporter.export_rows([], job)
    b = exporter.export_rows([], job)
    assert a.artifact.payload == b.artifact.payload
    assert a.artifact.row_count == 0
    assert a.content_digest == b.content_digest


# ---------------------------------------------------------------------------
# Format-specific smoke
# ---------------------------------------------------------------------------


def test_json_payload_is_canonical() -> None:
    job = _job(format=ex.ExportFormat.JSON, column_policy=_column_policy())
    result = ex.SnapshotExporter().export_rows(TENANT_ROWS, job)
    # Canonical JSON: sorted keys, no insignificant whitespace.
    text = result.artifact.payload.decode("utf-8")
    assert "\n" not in text
    assert result.artifact.media_type.value == "json"
    assert b'"non_authoritative":true' in result.artifact.payload
    assert b'"read_only":true' in result.artifact.payload


def test_markdown_contains_metadata_and_table() -> None:
    job = _job(
        format=ex.ExportFormat.MARKDOWN,
        location_hint="exports/publication/list.md",
        column_policy=_column_policy(),
    )
    result = ex.SnapshotExporter().export_rows(TENANT_ROWS, job)
    text = result.artifact.payload.decode("utf-8")
    assert "non_authoritative: `true`" in text
    assert "parameters_digest:" in text
    assert "| record_id |" in text or "record_id" in text
    assert "r1" in text and "r2" in text


def test_parquet_envelope_has_par1_magic() -> None:
    job = _job(
        format=ex.ExportFormat.PARQUET,
        location_hint="exports/publication/list.parquet",
        column_policy=_column_policy(),
    )
    result = ex.SnapshotExporter().export_rows(TENANT_ROWS, job)
    data = result.artifact.payload
    assert data.startswith(b"PAR1")
    assert data.endswith(b"PAR1")
    assert result.artifact.media_type.value == "parquet"


def test_arrow_stream_has_magic() -> None:
    job = _job(
        format=ex.ExportFormat.ARROW,
        location_hint="exports/publication/list.arrow",
        column_policy=_column_policy(),
    )
    result = ex.SnapshotExporter().export_rows(TENANT_ROWS, job)
    assert result.artifact.payload.startswith(b"ARROW1\x00")


def test_car_contains_root_digest() -> None:
    job = _job(
        format=ex.ExportFormat.CAR,
        location_hint="exports/publication/list.car",
        column_policy=_column_policy(),
    )
    result = ex.SnapshotExporter().export_rows(TENANT_ROWS, job)
    assert result.artifact.media_type.value == "car"
    # CAR bytes themselves are digested; payload embeds row data.
    assert b"duckdb_control_car_export" in result.artifact.payload
    assert result.root_cid.startswith("sha256:")


# ---------------------------------------------------------------------------
# Validation / fail-closed edges
# ---------------------------------------------------------------------------


def test_invalid_template_id_rejected() -> None:
    with pytest.raises(ex.ExportError, match="template_id"):
        _job(template_id="Not Valid!")


def test_export_format_parse() -> None:
    assert ex.ExportFormat.parse("JSON") is ex.ExportFormat.JSON
    assert ex.ExportFormat.parse(ex.ExportFormat.CAR) is ex.ExportFormat.CAR
    with pytest.raises(ex.ExportError, match="unsupported export format"):
        ex.ExportFormat.parse("xml")


def test_job_identity_stable_across_location_hint() -> None:
    """Location hints are non-authoritative; job identity excludes them."""

    # Destination policy allows both under exports/.
    base = dict(
        job_id="export:stable",
        template_id="publication.list_records",
        parameters_digest=ex.digest_parameters({"x": 1}),
        schema_version="ipfs_datasets_py/duckdb-control-export-schema@1",
        snapshot=_snapshot(),
        format=ex.ExportFormat.JSON,
        destination_policy=_policy(),
        revision="1",
        created_at=FIXED_CLOCK,
    )
    j1 = ex.ExportJob(**base, location_hint="exports/a.json")
    j2 = ex.ExportJob(**base, location_hint="exports/b.json")
    assert j1.identity_id == j2.identity_id


def test_verify_export_replay_helper() -> None:
    job = _job(column_policy=_column_policy())
    exporter = ex.SnapshotExporter()
    a = exporter.export_rows(TENANT_ROWS, job)
    b = exporter.export_rows(TENANT_ROWS, job)
    ex.verify_export_replay(a.artifact, b.artifact)
    other = exporter.export_rows([{"record_id": "z", "status": "x", "score": 0}], job)
    with pytest.raises(ex.ReplayVerificationError):
        ex.verify_export_replay(a.artifact, other.artifact)


def test_schema_constants_stable() -> None:
    assert ex.EXPORTER_SCHEMA == "ipfs_datasets_py/duckdb-control-exporter@1"
    assert ex.EXPORT_JOB_SCHEMA.endswith("@1")
    assert ex.EXPORT_ARTIFACT_SCHEMA.endswith("@1")
    assert frozenset(f.value for f in ex.ExportFormat) == {
        "markdown",
        "json",
        "parquet",
        "arrow",
        "car",
    }
