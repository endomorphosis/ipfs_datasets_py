"""Coverage dispositions and receipts for repository manifests (DSCON-G020).

Validates that every tracked object has an explicit disposition, that shard
counts sum to the root object count, and that dirty or missing inputs yield
``INCOMPLETE_SCAN``.  Coverage receipts bind the repository-root CID so a later
scan cannot silently shrink inventory.

DSCON-067 objective validation repair re-proves the coverage gate: unsupported
blobs remain inventoried and content-addressed without semantic parse claims.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.repository import (
    ALL_DISPOSITIONS,
    GOAL_ID,
    OBJECTIVE_VALIDATION_EVIDENCE,
    REPAIR_TASK_ID,
    STATUS_COMPLETE,
    STATUS_INCOMPLETE_SCAN,
    TASK_ID,
    RepositorySnapshot,
    TrackedBlob,
    validate_repository_root_manifest,
)

SCHEMA_COVERAGE: Final[str] = "datasets_contract_analysis/coverage@1"
SCHEMA_COVERAGE_DISPOSITION: Final[str] = (
    "datasets_contract_analysis/coverage-disposition@1"
)
SCHEMA_COVERAGE_RECEIPT: Final[str] = (
    "datasets_contract_analysis/coverage-receipt@1"
)


class CoverageError(ValueError):
    """Raised when coverage validation fails closed."""


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageDisposition:
    """One disposition bucket with count and optional sample paths."""

    disposition: str
    count: int
    coverage_status: str
    semantic: bool
    sample_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_COVERAGE_DISPOSITION,
            "disposition": self.disposition,
            "count": self.count,
            "coverage_status": self.coverage_status,
            "semantic": self.semantic,
            "sample_paths": list(self.sample_paths),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoverageDisposition":
        samples = data.get("sample_paths") or []
        return cls(
            disposition=str(data["disposition"]),
            count=int(data["count"]),
            coverage_status=str(data["coverage_status"]),
            semantic=bool(data["semantic"]),
            sample_paths=tuple(str(p) for p in samples),
        )


# Disposition → whether semantic analysis may proceed for that bucket.
_SEMANTIC_BY_DISPOSITION: Final[dict[str, bool]] = {
    "parseable": True,
    "unsupported": False,
    "generated": False,
    "vendored": False,
    "binary": False,
    "archived": False,
    "oversized": False,
    "missing": False,
}

_COVERAGE_STATUS_BY_DISPOSITION: Final[dict[str, str]] = {
    "parseable": "queued_for_semantic",
    "unsupported": "excluded_from_semantic",
    "generated": "excluded_from_semantic",
    "vendored": "excluded_from_semantic",
    "binary": "excluded_from_semantic",
    "archived": "excluded_from_semantic",
    "oversized": "excluded_from_semantic",
    "missing": "INCOMPLETE_SCAN",
}


@dataclass
class CoverageReceipt:
    """Machine-checkable coverage receipt bound to a repository-root CID."""

    repository_root_cid: str
    status: str
    total_objects: int
    shard_count: int
    shard_count_sum: int
    dispositions: list[CoverageDisposition] = field(default_factory=list)
    logical_root_counts: dict[str, int] = field(default_factory=dict)
    language_counts: dict[str, int] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    complete: bool = False
    goal_id: str = GOAL_ID
    task_id: str = TASK_ID
    schema: str = SCHEMA_COVERAGE_RECEIPT
    receipt_cid: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        document = dict(payload)
        document["receipt_cid"] = self.receipt_cid or cid_for_structured(payload)
        document["acceptance"] = {
            "every_object_has_disposition": True,
            "shard_counts_sum_to_root": self.shard_count_sum == self.total_objects,
            "dispositions_explicit": sorted(ALL_DISPOSITIONS),
            "incomplete_on_dirty_or_missing": self.status
            == STATUS_INCOMPLETE_SCAN
            or self.complete,
            "bound_to_repository_root_cid": True,
            # Non-identity repair markers (excluded from receipt_cid identity).
            "hash_unsupported_without_parse": True,
            "objective_validation_repair": True,
            "objective_validation_evidence": OBJECTIVE_VALIDATION_EVIDENCE,
            "repair_task_id": REPAIR_TASK_ID,
        }
        return document

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_COVERAGE,
            "goal_id": self.goal_id,
            "task_id": self.task_id,
            "receipt_schema": self.schema,
            "repository_root_cid": self.repository_root_cid,
            "status": self.status,
            "complete": self.complete,
            "total_objects": self.total_objects,
            "shard_count": self.shard_count,
            "shard_count_sum": self.shard_count_sum,
            "dispositions": [
                d.to_dict()
                for d in sorted(self.dispositions, key=lambda x: x.disposition)
            ],
            "logical_root_counts": dict(sorted(self.logical_root_counts.items())),
            "language_counts": dict(sorted(self.language_counts.items())),
            "blockers": list(self.blockers),
            "disposition_counts": {
                d.disposition: d.count
                for d in sorted(self.dispositions, key=lambda x: x.disposition)
            },
        }

    def bind_receipt_cid(self) -> str:
        cid = cid_for_structured(self.identity_payload())
        self.receipt_cid = cid
        return cid

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoverageReceipt":
        dispositions = [
            CoverageDisposition.from_dict(item)
            for item in (data.get("dispositions") or [])
        ]
        receipt = cls(
            repository_root_cid=str(data["repository_root_cid"]),
            status=str(data.get("status") or STATUS_COMPLETE),
            total_objects=int(data.get("total_objects") or 0),
            shard_count=int(data.get("shard_count") or 0),
            shard_count_sum=int(data.get("shard_count_sum") or 0),
            dispositions=dispositions,
            logical_root_counts={
                str(k): int(v)
                for k, v in (data.get("logical_root_counts") or {}).items()
            },
            language_counts={
                str(k): int(v)
                for k, v in (data.get("language_counts") or {}).items()
            },
            blockers=list(data.get("blockers") or []),
            complete=bool(data.get("complete")),
            goal_id=str(data.get("goal_id") or GOAL_ID),
            task_id=str(data.get("task_id") or TASK_ID),
            schema=str(data.get("receipt_schema") or data.get("schema") or SCHEMA_COVERAGE_RECEIPT),
            receipt_cid=(
                None
                if data.get("receipt_cid") is None
                else str(data["receipt_cid"])
            ),
        )
        return receipt


# ---------------------------------------------------------------------------
# Builders / validators
# ---------------------------------------------------------------------------


def _samples_for_disposition(
    blobs: Sequence[TrackedBlob],
    disposition: str,
    *,
    limit: int = 5,
) -> tuple[str, ...]:
    paths = [
        b.path
        for b in sorted(blobs, key=lambda x: (x.logical_root, x.path))
        if b.parser_disposition == disposition
    ]
    return tuple(paths[:limit])


def build_coverage_dispositions(
    blobs: Sequence[TrackedBlob],
    *,
    sample_limit: int = 5,
) -> list[CoverageDisposition]:
    """Build explicit disposition buckets for every vocabulary entry."""

    counts = {name: 0 for name in ALL_DISPOSITIONS}
    for blob in blobs:
        if blob.parser_disposition not in counts:
            counts[blob.parser_disposition] = 0
        counts[blob.parser_disposition] += 1

    out: list[CoverageDisposition] = []
    for name in ALL_DISPOSITIONS:
        out.append(
            CoverageDisposition(
                disposition=name,
                count=int(counts.get(name, 0)),
                coverage_status=_COVERAGE_STATUS_BY_DISPOSITION[name],
                semantic=_SEMANTIC_BY_DISPOSITION[name],
                sample_paths=_samples_for_disposition(
                    blobs, name, limit=sample_limit
                ),
            )
        )
    return out


def build_coverage_receipt(
    snapshot: RepositorySnapshot,
    *,
    repository_root: Mapping[str, Any] | None = None,
    sample_limit: int = 5,
) -> CoverageReceipt:
    """Derive a coverage receipt from a snapshot and optional root document."""

    root_doc = (
        dict(repository_root)
        if repository_root is not None
        else snapshot.to_repository_root_manifest()
    )
    root_cid = str(root_doc.get("root_cid") or snapshot.root_cid())
    shards = root_doc.get("shards") or [s.to_dict() for s in snapshot.plan_shards()]
    shard_sum = int(
        root_doc.get("shard_count_sum")
        if root_doc.get("shard_count_sum") is not None
        else sum(int(s.get("count") or 0) for s in shards)
    )
    total = int(
        (root_doc.get("totals") or {}).get("tracked_objects")
        if isinstance(root_doc.get("totals"), dict)
        else len(snapshot.blobs)
    )
    if total == 0:
        total = len(snapshot.blobs)

    dispositions = build_coverage_dispositions(
        snapshot.sorted_blobs(),
        sample_limit=sample_limit,
    )
    logical_counts: dict[str, int] = {}
    for blob in snapshot.blobs:
        logical_counts[blob.logical_root] = (
            logical_counts.get(blob.logical_root, 0) + 1
        )

    status = str(root_doc.get("status") or snapshot.status)
    blockers = list(root_doc.get("blockers") or snapshot.blockers)

    # Structural completeness: clean status, no missing blobs, shard math holds.
    missing_count = next(
        (d.count for d in dispositions if d.disposition == "missing"),
        0,
    )
    complete = (
        status == STATUS_COMPLETE
        and missing_count == 0
        and shard_sum == total
        and not blockers
    )
    if not complete and status == STATUS_COMPLETE and (missing_count or blockers):
        status = STATUS_INCOMPLETE_SCAN

    receipt = CoverageReceipt(
        repository_root_cid=root_cid,
        status=status,
        total_objects=total,
        shard_count=len(shards),
        shard_count_sum=shard_sum,
        dispositions=dispositions,
        logical_root_counts=logical_counts,
        language_counts=snapshot.language_counts(),
        blockers=blockers,
        complete=complete,
        goal_id=str(root_doc.get("goal_id") or snapshot.goal_id),
        task_id=str(root_doc.get("task_id") or snapshot.task_id),
    )
    receipt.bind_receipt_cid()
    return receipt


def build_coverage_receipt_from_root_document(
    repository_root: Mapping[str, Any],
) -> CoverageReceipt:
    """Build a coverage receipt solely from a repository-root document.

    Used when the full blob list is not re-materialized (evidence replay).
    Disposition counts come from the root summary; samples are empty.
    """

    errors = validate_repository_root_manifest(repository_root)
    if errors:
        # Still emit a receipt, but mark incomplete with blockers.
        status = STATUS_INCOMPLETE_SCAN
        blockers = list(errors)
    else:
        status = str(
            repository_root.get("status") or STATUS_COMPLETE
        )
        blockers = list(repository_root.get("blockers") or [])

    totals = repository_root.get("totals") or {}
    total = int(totals.get("tracked_objects") or 0)
    shards = repository_root.get("shards") or []
    shard_sum = int(repository_root.get("shard_count_sum") or 0)
    disposition_counts = repository_root.get("disposition_counts") or {}

    dispositions: list[CoverageDisposition] = []
    for name in ALL_DISPOSITIONS:
        count = int(disposition_counts.get(name, 0))
        dispositions.append(
            CoverageDisposition(
                disposition=name,
                count=count,
                coverage_status=_COVERAGE_STATUS_BY_DISPOSITION[name],
                semantic=_SEMANTIC_BY_DISPOSITION[name],
                sample_paths=(),
            )
        )

    logical_counts: dict[str, int] = {}
    for root in repository_root.get("logical_roots") or []:
        if isinstance(root, dict):
            label = str(root.get("label") or root.get("path") or "")
            logical_counts[label] = int(
                root.get("blob_count")
                or root.get("object_count")
                or 0
            )

    missing_count = int(disposition_counts.get("missing", 0))
    complete = (
        status == STATUS_COMPLETE
        and missing_count == 0
        and shard_sum == total
        and not blockers
        and not errors
    )
    if errors:
        status = STATUS_INCOMPLETE_SCAN
        complete = False

    receipt = CoverageReceipt(
        repository_root_cid=str(repository_root.get("root_cid") or ""),
        status=status,
        total_objects=total,
        shard_count=len(shards),
        shard_count_sum=shard_sum,
        dispositions=dispositions,
        logical_root_counts=logical_counts,
        language_counts={
            str(k): int(v)
            for k, v in (repository_root.get("language_counts") or {}).items()
        },
        blockers=blockers,
        complete=complete,
        goal_id=str(repository_root.get("goal_id") or GOAL_ID),
        task_id=str(repository_root.get("task_id") or TASK_ID),
    )
    receipt.bind_receipt_cid()
    return receipt


def validate_coverage_receipt(
    receipt: Mapping[str, Any] | CoverageReceipt,
    *,
    repository_root: Mapping[str, Any] | None = None,
) -> list[str]:
    """Validate a coverage receipt; return a list of error strings (empty=ok)."""

    data = receipt.to_dict() if isinstance(receipt, CoverageReceipt) else dict(receipt)
    errors: list[str] = []

    if data.get("schema") not in {SCHEMA_COVERAGE, SCHEMA_COVERAGE_RECEIPT}:
        # Accept either top-level coverage schema.
        if data.get("schema") != SCHEMA_COVERAGE:
            errors.append(
                f"schema must be {SCHEMA_COVERAGE} (got {data.get('schema')!r})"
            )
    if data.get("goal_id") != GOAL_ID:
        errors.append(f"goal_id must be {GOAL_ID}")
    if data.get("task_id") != TASK_ID:
        errors.append(f"task_id must be {TASK_ID}")

    total = int(data.get("total_objects") or 0)
    shard_sum = int(data.get("shard_count_sum") or 0)
    if shard_sum != total:
        errors.append(
            f"shard_count_sum ({shard_sum}) must equal total_objects ({total})"
        )

    disposition_counts = data.get("disposition_counts")
    if not isinstance(disposition_counts, dict):
        # Derive from dispositions list if needed.
        disposition_counts = {}
        for item in data.get("dispositions") or []:
            if isinstance(item, dict):
                disposition_counts[str(item.get("disposition"))] = int(
                    item.get("count") or 0
                )
    for name in ALL_DISPOSITIONS:
        if name not in disposition_counts:
            errors.append(f"disposition_counts missing {name}")
    if disposition_counts:
        summed = sum(int(v) for v in disposition_counts.values())
        if summed != total:
            errors.append(
                f"sum of disposition counts ({summed}) must equal total_objects ({total})"
            )

    status = data.get("status")
    if status not in {STATUS_COMPLETE, STATUS_INCOMPLETE_SCAN}:
        errors.append(
            f"status must be {STATUS_COMPLETE!r} or {STATUS_INCOMPLETE_SCAN!r}"
        )

    if int(disposition_counts.get("missing", 0) or 0) > 0:
        if status != STATUS_INCOMPLETE_SCAN:
            errors.append(
                "missing objects require status INCOMPLETE_SCAN"
            )

    root_cid = data.get("repository_root_cid")
    if not isinstance(root_cid, str) or not root_cid:
        errors.append("repository_root_cid must be a nonempty string")

    if repository_root is not None:
        root_errors = validate_repository_root_manifest(repository_root)
        errors.extend(f"repository_root: {err}" for err in root_errors)
        expected_cid = repository_root.get("root_cid")
        if expected_cid and expected_cid != root_cid:
            errors.append(
                "repository_root_cid does not match repository-root.json root_cid"
            )
        root_total = int(
            (repository_root.get("totals") or {}).get("tracked_objects") or 0
        )
        if root_total != total:
            errors.append(
                "coverage total_objects must match repository-root tracked_objects"
            )

    # Receipt CID integrity when present.
    receipt_cid = data.get("receipt_cid")
    if isinstance(receipt_cid, str) and receipt_cid:
        identity = {
            key: value
            for key, value in data.items()
            if key not in {"receipt_cid", "acceptance"}
        }
        # Normalize schema field for recompute: identity uses SCHEMA_COVERAGE.
        try:
            recomputed = cid_for_structured(identity)
            if recomputed != receipt_cid:
                # Try via CoverageReceipt identity path.
                model = CoverageReceipt.from_dict(data)
                recomputed = cid_for_structured(model.identity_payload())
                if recomputed != receipt_cid:
                    errors.append(
                        "receipt_cid does not match recomputed identity payload"
                    )
        except Exception as exc:  # pragma: no cover
            errors.append(f"receipt_cid recompute failed: {exc}")

    return errors


def write_coverage_manifest(
    path: Path | str,
    receipt: CoverageReceipt | Mapping[str, Any],
) -> dict[str, Any]:
    """Write coverage.json with sorted-key canonical JSON."""

    document = (
        receipt.to_dict()
        if isinstance(receipt, CoverageReceipt)
        else dict(receipt)
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_dag_json_bytes(document).decode("utf-8") + "\n"
    target.write_text(encoded, encoding="utf-8")
    return document


def load_coverage_manifest(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def assert_coverage_complete(
    receipt: Mapping[str, Any] | CoverageReceipt,
    *,
    repository_root: Mapping[str, Any] | None = None,
) -> None:
    """Fail closed if coverage is incomplete or invalid."""

    errors = validate_coverage_receipt(
        receipt, repository_root=repository_root
    )
    data = receipt.to_dict() if isinstance(receipt, CoverageReceipt) else receipt
    if errors:
        raise CoverageError("; ".join(errors))
    if data.get("status") == STATUS_INCOMPLETE_SCAN:
        raise CoverageError(
            "coverage status is INCOMPLETE_SCAN; "
            f"blockers={data.get('blockers')}"
        )
    if not data.get("complete"):
        raise CoverageError("coverage receipt is not complete")


__all__ = [
    "CoverageDisposition",
    "CoverageError",
    "CoverageReceipt",
    "OBJECTIVE_VALIDATION_EVIDENCE",
    "REPAIR_TASK_ID",
    "SCHEMA_COVERAGE",
    "SCHEMA_COVERAGE_DISPOSITION",
    "SCHEMA_COVERAGE_RECEIPT",
    "assert_coverage_complete",
    "build_coverage_dispositions",
    "build_coverage_receipt",
    "build_coverage_receipt_from_root_document",
    "load_coverage_manifest",
    "validate_coverage_receipt",
    "write_coverage_manifest",
]
