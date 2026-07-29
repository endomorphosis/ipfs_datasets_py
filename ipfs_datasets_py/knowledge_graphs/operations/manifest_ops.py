"""Manifest scrub, verify, and repair-preview tools (KGP-032).

Repair **never mutates** storage without an explicit bounded plan that the
operator must apply via :func:`apply_repair_plan` with ``confirm=True``.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ipfs_datasets_py.knowledge_graphs.contracts.manifest import (
    GraphRevisionManifest,
    ManifestError,
    ManifestIntegrityError,
    ManifestValidationError,
    canonical_json_bytes,
    sha256_hex,
)

from .logging import log_ops_event
from .redact import OPERATIONS_CONTRACT_VERSION, scrub_for_telemetry
from .telemetry import OpsTelemetry, get_default_telemetry

MANIFEST_OPS_SCHEMA = "kg-ops-manifest/v1"
MAX_PLAN_ACTIONS = 1_024
MAX_FINDINGS = 512


@dataclass(frozen=True, slots=True)
class ManifestFinding:
    """One integrity / scrub finding (never includes raw payload bytes)."""

    code: str
    severity: str  # info | warn | error
    path: str
    message: str
    revision_id: Optional[str] = None
    graph_id: Optional[str] = None
    tenant: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
            "revision_id": self.revision_id,
            "graph_id": self.graph_id,
            "tenant": self.tenant,
        }


@dataclass
class ManifestVerifyReport:
    ok: bool
    findings: List[ManifestFinding] = field(default_factory=list)
    checked: int = 0
    schema_version: str = MANIFEST_OPS_SCHEMA
    contract_version: str = OPERATIONS_CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_version": self.contract_version,
            "ok": self.ok,
            "checked": self.checked,
            "findings": [f.to_dict() for f in self.findings[:MAX_FINDINGS]],
        }


@dataclass(frozen=True, slots=True)
class RepairAction:
    """Single bounded repair step. Applied only via explicit plan execution."""

    action_id: str
    kind: str  # recompute_checksum | clear_invalid_manifest | set_pin_root | note
    target: Dict[str, str]
    detail: str
    mutates: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "kind": self.kind,
            "target": dict(self.target),
            "detail": self.detail,
            "mutates": self.mutates,
        }


@dataclass
class RepairPlan:
    """Bounded, content-addressed repair plan. Immutable until applied."""

    plan_id: str
    created_at: float
    actions: List[RepairAction]
    findings: List[ManifestFinding]
    source_digest: str
    dry_run: bool = True
    schema_version: str = MANIFEST_OPS_SCHEMA
    max_actions: int = MAX_PLAN_ACTIONS
    applied: bool = False

    def __post_init__(self) -> None:
        if len(self.actions) > self.max_actions:
            raise ValueError(
                f"repair plan exceeds max_actions={self.max_actions} "
                f"(got {len(self.actions)})"
            )

    @property
    def plan_digest(self) -> str:
        payload = {
            "plan_id": self.plan_id,
            "actions": [a.to_dict() for a in self.actions],
            "source_digest": self.source_digest,
            "schema_version": self.schema_version,
        }
        return sha256_hex(canonical_json_bytes(payload))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_version": OPERATIONS_CONTRACT_VERSION,
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "dry_run": self.dry_run,
            "applied": self.applied,
            "source_digest": self.source_digest,
            "plan_digest": self.plan_digest,
            "action_count": len(self.actions),
            "actions": [a.to_dict() for a in self.actions],
            "findings": [f.to_dict() for f in self.findings[:MAX_FINDINGS]],
            "mutates_without_confirm": False,
        }


@dataclass
class RepairApplyResult:
    plan_id: str
    plan_digest: str
    applied: bool
    dry_run: bool
    actions_executed: int
    actions_skipped: int
    notes: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "plan_digest": self.plan_digest,
            "applied": self.applied,
            "dry_run": self.dry_run,
            "actions_executed": self.actions_executed,
            "actions_skipped": self.actions_skipped,
            "notes": list(self.notes),
            "error": self.error,
        }


def _parse_manifest_blob(
    blob: Any,
    *,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    revision_id: Optional[str] = None,
) -> Tuple[Optional[GraphRevisionManifest], List[ManifestFinding]]:
    findings: List[ManifestFinding] = []
    if blob is None or blob == "":
        findings.append(
            ManifestFinding(
                code="MANIFEST_MISSING",
                severity="warn",
                path="manifest_json",
                message="revision has no manifest_json",
                tenant=tenant,
                graph_id=graph_id,
                revision_id=revision_id,
            )
        )
        return None, findings
    try:
        data = json.loads(blob) if isinstance(blob, str) else blob
    except Exception:
        findings.append(
            ManifestFinding(
                code="MANIFEST_PARSE_ERROR",
                severity="error",
                path="manifest_json",
                message="manifest_json is not valid JSON",
                tenant=tenant,
                graph_id=graph_id,
                revision_id=revision_id,
            )
        )
        return None, findings
    if not isinstance(data, Mapping):
        findings.append(
            ManifestFinding(
                code="MANIFEST_TYPE_ERROR",
                severity="error",
                path="manifest_json",
                message="manifest_json must be a JSON object",
                tenant=tenant,
                graph_id=graph_id,
                revision_id=revision_id,
            )
        )
        return None, findings
    try:
        manifest = GraphRevisionManifest.from_dict(data)
        return manifest, findings
    except ManifestError as exc:
        findings.append(
            ManifestFinding(
                code=getattr(exc, "code", "MANIFEST_INVALID") or "MANIFEST_INVALID",
                severity="error",
                path="manifest",
                message=str(exc)[:256],
                tenant=tenant,
                graph_id=graph_id,
                revision_id=revision_id,
            )
        )
        return None, findings


def scrub_manifest_dict(data: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a telemetry-safe view of a manifest (no property payloads)."""
    # Manifests are control-plane descriptors; still scrub unexpected secrets.
    return scrub_for_telemetry(dict(data))


def verify_manifest(
    data: Mapping[str, Any],
    *,
    expected_revision_id: Optional[str] = None,
    expected_checksum: Optional[str] = None,
) -> ManifestVerifyReport:
    """Validate one manifest mapping and optional identity constraints."""
    findings: List[ManifestFinding] = []
    checked = 0
    try:
        manifest = GraphRevisionManifest.from_dict(data)
        checked += 1
        if expected_revision_id and manifest.revision_id != expected_revision_id:
            findings.append(
                ManifestFinding(
                    code="REVISION_MISMATCH",
                    severity="error",
                    path="revision_id",
                    message=(
                        f"expected revision_id={expected_revision_id!r} "
                        f"got {manifest.revision_id!r}"
                    ),
                    revision_id=manifest.revision_id,
                    graph_id=manifest.graph_id,
                    tenant=manifest.tenant,
                )
            )
        if expected_checksum:
            exp = expected_checksum
            if exp.startswith("sha256:"):
                exp = exp[len("sha256:") :]
            if manifest.checksum.hex_digest != exp:
                findings.append(
                    ManifestFinding(
                        code="CHECKSUM_MISMATCH",
                        severity="error",
                        path="checksum",
                        message="declared checksum does not match expected",
                        revision_id=manifest.revision_id,
                        graph_id=manifest.graph_id,
                        tenant=manifest.tenant,
                    )
                )
        # Partition / index checksum presence
        for part in manifest.partitions:
            checked += 1
            if not part.checksum.hex_digest:
                findings.append(
                    ManifestFinding(
                        code="PARTITION_CHECKSUM_MISSING",
                        severity="error",
                        path=f"partitions.{part.partition_id}",
                        message="partition checksum empty",
                        revision_id=manifest.revision_id,
                    )
                )
        ok = not any(f.severity == "error" for f in findings)
        return ManifestVerifyReport(ok=ok, findings=findings, checked=checked)
    except ManifestError as exc:
        findings.append(
            ManifestFinding(
                code=getattr(exc, "code", "MANIFEST_INVALID") or "MANIFEST_INVALID",
                severity="error",
                path="manifest",
                message=str(exc)[:256],
            )
        )
        return ManifestVerifyReport(ok=False, findings=findings, checked=checked)


def scrub_catalog_manifests(
    catalog: Any,
    *,
    tenant: str,
    graph_id: Optional[str] = None,
    max_revisions: int = 1_024,
) -> ManifestVerifyReport:
    """Scrub/verify all manifests for a tenant (optionally one graph)."""
    findings: List[ManifestFinding] = []
    checked = 0
    graphs: List[Any]
    if graph_id is not None:
        graphs = [catalog.get_graph(tenant, graph_id)]
    else:
        graphs = catalog.list_graphs(tenant)

    for g in graphs:
        gid = g.graph_id if hasattr(g, "graph_id") else g["graph_id"]
        revs = catalog.list_revisions(tenant, gid)
        for rev in revs[:max_revisions]:
            rid = rev.revision_id if hasattr(rev, "revision_id") else rev["revision_id"]
            blob = rev.manifest_json if hasattr(rev, "manifest_json") else rev.get(
                "manifest_json"
            )
            checksum = rev.checksum if hasattr(rev, "checksum") else rev.get("checksum")
            man, local = _parse_manifest_blob(
                blob, tenant=tenant, graph_id=gid, revision_id=rid
            )
            findings.extend(local)
            if man is None:
                checked += 1
                continue
            checked += 1
            if checksum:
                exp = checksum[len("sha256:") :] if checksum.startswith("sha256:") else checksum
                if man.checksum.hex_digest != exp and exp != man.checksum.hex_digest:
                    # Catalog may store the identity checksum directly.
                    if exp != man.checksum.hex_digest:
                        findings.append(
                            ManifestFinding(
                                code="CATALOG_CHECKSUM_DRIFT",
                                severity="error",
                                path="revision.checksum",
                                message="catalog checksum differs from manifest",
                                tenant=tenant,
                                graph_id=gid,
                                revision_id=rid,
                            )
                        )
            if man.tenant != tenant or man.graph_id != gid:
                findings.append(
                    ManifestFinding(
                        code="IDENTITY_DRIFT",
                        severity="error",
                        path="manifest.identity",
                        message="manifest tenant/graph_id does not match catalog row",
                        tenant=tenant,
                        graph_id=gid,
                        revision_id=rid,
                    )
                )
            if man.revision_id != rid:
                findings.append(
                    ManifestFinding(
                        code="REVISION_ID_DRIFT",
                        severity="error",
                        path="manifest.revision_id",
                        message="manifest revision_id does not match catalog row",
                        tenant=tenant,
                        graph_id=gid,
                        revision_id=rid,
                    )
                )

    ok = not any(f.severity == "error" for f in findings)
    report = ManifestVerifyReport(ok=ok, findings=findings, checked=checked)
    log_ops_event(
        "manifest.scrub",
        ok=ok,
        checked=checked,
        finding_count=len(findings),
        tenant=tenant,
        graph_id=graph_id,
    )
    return report


def preview_repair(
    catalog: Any,
    *,
    tenant: str,
    graph_id: Optional[str] = None,
    max_actions: int = MAX_PLAN_ACTIONS,
    telemetry: Optional[OpsTelemetry] = None,
) -> RepairPlan:
    """Build a bounded dry-run repair plan. Does **not** mutate the catalog."""
    tel = telemetry or get_default_telemetry()
    started = time.perf_counter()
    report = scrub_catalog_manifests(catalog, tenant=tenant, graph_id=graph_id)
    actions: List[RepairAction] = []
    source = {
        "tenant": tenant,
        "graph_id": graph_id,
        "findings": [f.to_dict() for f in report.findings],
        "checked": report.checked,
    }
    source_digest = sha256_hex(canonical_json_bytes(source))

    for finding in report.findings:
        if len(actions) >= max_actions:
            break
        target = {
            k: v
            for k, v in {
                "tenant": finding.tenant or tenant,
                "graph_id": finding.graph_id or "",
                "revision_id": finding.revision_id or "",
                "path": finding.path,
            }.items()
            if v
        }
        if finding.code in {
            "MANIFEST_PARSE_ERROR",
            "MANIFEST_TYPE_ERROR",
            "MANIFEST_INVALID",
            "UNKNOWN_REQUIRED_FIELD",
            "NONCANONICAL_VALUE",
            "CHECKSUM_CID_MISMATCH",
        }:
            actions.append(
                RepairAction(
                    action_id=f"act-{len(actions)+1:04d}",
                    kind="clear_invalid_manifest",
                    target=target,
                    detail=f"clear invalid manifest_json ({finding.code})",
                    mutates=True,
                )
            )
        elif finding.code in {"CATALOG_CHECKSUM_DRIFT", "CHECKSUM_MISMATCH"}:
            actions.append(
                RepairAction(
                    action_id=f"act-{len(actions)+1:04d}",
                    kind="recompute_checksum",
                    target=target,
                    detail="align catalog checksum to verified manifest identity",
                    mutates=True,
                )
            )
        elif finding.code == "MANIFEST_MISSING":
            actions.append(
                RepairAction(
                    action_id=f"act-{len(actions)+1:04d}",
                    kind="note",
                    target=target,
                    detail="manifest missing; restore from immutable backup",
                    mutates=False,
                )
            )
        else:
            actions.append(
                RepairAction(
                    action_id=f"act-{len(actions)+1:04d}",
                    kind="note",
                    target=target,
                    detail=f"manual review required for {finding.code}",
                    mutates=False,
                )
            )

    plan = RepairPlan(
        plan_id=f"repair-{uuid.uuid4().hex[:12]}",
        created_at=time.time(),
        actions=actions,
        findings=list(report.findings),
        source_digest=source_digest,
        dry_run=True,
        max_actions=max_actions,
    )
    duration_ms = (time.perf_counter() - started) * 1000.0
    tel.record_operation("manifest.repair_preview", duration_ms, success=True)
    log_ops_event(
        "manifest.repair_preview",
        plan_id=plan.plan_id,
        plan_digest=plan.plan_digest,
        action_count=len(actions),
        dry_run=True,
    )
    return plan


@dataclass
class RepairJournal:
    """Durable ledger of authorized repair outcomes (content-addressed).

    Catalog revision rows are immutable. Mutating field-level fixes are
    recorded here and applied by restore-from-backup or a new revision publish,
    never by silent in-place rewrite.
    """

    plan_id: str
    plan_digest: str
    entries: List[Dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        body = {
            "plan_id": self.plan_id,
            "plan_digest": self.plan_digest,
            "created_at": self.created_at,
            "entries": list(self.entries),
        }
        body["journal_digest"] = sha256_hex(canonical_json_bytes(body))
        return body


def apply_repair_plan(
    catalog: Any,
    plan: RepairPlan,
    *,
    confirm: bool = False,
    expected_plan_digest: Optional[str] = None,
    journal_path: Optional[str] = None,
    telemetry: Optional[OpsTelemetry] = None,
) -> RepairApplyResult:
    """Apply a repair plan only when *confirm* is True and digest matches.

    Without ``confirm=True`` this function is a pure no-op (preview semantics)
    and the catalog is never touched.

    With confirmation, allowed live mutations are limited to additive pin
    registration. Field-level revision fixes are written to a
    :class:`RepairJournal` for restore/publish — catalog revision rows remain
    immutable.
    """
    tel = telemetry or get_default_telemetry()
    digest = plan.plan_digest
    if expected_plan_digest is not None and expected_plan_digest != digest:
        return RepairApplyResult(
            plan_id=plan.plan_id,
            plan_digest=digest,
            applied=False,
            dry_run=True,
            actions_executed=0,
            actions_skipped=len(plan.actions),
            error="PLAN_DIGEST_MISMATCH",
            notes=["refusing to apply: plan digest does not match expected"],
        )

    if not confirm:
        log_ops_event(
            "manifest.repair_refused",
            plan_id=plan.plan_id,
            reason="confirm_required",
            action_count=len(plan.actions),
        )
        return RepairApplyResult(
            plan_id=plan.plan_id,
            plan_digest=digest,
            applied=False,
            dry_run=True,
            actions_executed=0,
            actions_skipped=len(plan.actions),
            notes=[
                "repair never mutates without confirm=True and explicit bounded plan"
            ],
        )

    if plan.applied:
        return RepairApplyResult(
            plan_id=plan.plan_id,
            plan_digest=digest,
            applied=False,
            dry_run=False,
            actions_executed=0,
            actions_skipped=len(plan.actions),
            error="PLAN_ALREADY_APPLIED",
            notes=["plan was already applied"],
        )

    executed = 0
    skipped = 0
    notes: List[str] = []
    journal = RepairJournal(plan_id=plan.plan_id, plan_digest=digest)
    started = time.perf_counter()
    try:
        for action in plan.actions:
            if not action.mutates:
                skipped += 1
                notes.append(f"skipped_non_mutating:{action.action_id}")
                continue
            tenant = action.target.get("tenant")
            graph_id = action.target.get("graph_id")
            revision_id = action.target.get("revision_id")
            if not (tenant and graph_id and revision_id):
                skipped += 1
                notes.append(f"skipped_incomplete_target:{action.action_id}")
                continue

            if action.kind == "set_pin_root":
                root_cid = action.target.get("root_cid")
                if not root_cid:
                    skipped += 1
                    notes.append(
                        f"set_pin_root_requires_explicit_cid:{action.action_id}"
                    )
                    continue
                if hasattr(catalog, "set_pin_root"):
                    catalog.set_pin_root(
                        tenant,
                        graph_id,
                        revision_id,
                        root_cid=root_cid,
                        pin_kind=action.target.get("pin_kind") or "repair",
                    )
                    executed += 1
                    journal.entries.append(
                        {"action_id": action.action_id, "kind": action.kind, "status": "applied"}
                    )
                else:
                    skipped += 1
                    notes.append(f"catalog_missing_set_pin_root:{action.action_id}")
                continue

            # Immutable revision rows: record authorized correction for restore.
            if action.kind in {"clear_invalid_manifest", "recompute_checksum"}:
                correction = _planned_revision_correction(
                    catalog, action.kind, tenant, graph_id, revision_id
                )
                journal.entries.append(
                    {
                        "action_id": action.action_id,
                        "kind": action.kind,
                        "status": "journaled_requires_restore",
                        "correction": correction,
                    }
                )
                executed += 1
                notes.append(
                    f"journaled_immutable_fix:{action.action_id}:apply_via_restore"
                )
                continue

            skipped += 1
            notes.append(f"unknown_action_kind:{action.kind}")

        if journal_path and journal.entries:
            from pathlib import Path

            path = Path(journal_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(journal.to_dict(), sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            notes.append(f"journal_written:{path}")

        plan.applied = True
        plan.dry_run = False
        duration_ms = (time.perf_counter() - started) * 1000.0
        tel.record_operation("manifest.repair_apply", duration_ms, success=True)
        log_ops_event(
            "manifest.repair_applied",
            plan_id=plan.plan_id,
            plan_digest=digest,
            actions_executed=executed,
            actions_skipped=skipped,
        )
        return RepairApplyResult(
            plan_id=plan.plan_id,
            plan_digest=digest,
            applied=True,
            dry_run=False,
            actions_executed=executed,
            actions_skipped=skipped,
            notes=notes,
        )
    except Exception as exc:
        duration_ms = (time.perf_counter() - started) * 1000.0
        tel.record_operation("manifest.repair_apply", duration_ms, success=False)
        return RepairApplyResult(
            plan_id=plan.plan_id,
            plan_digest=digest,
            applied=False,
            dry_run=False,
            actions_executed=executed,
            actions_skipped=skipped + max(0, len(plan.actions) - executed - skipped),
            error=type(exc).__name__,
            notes=notes + [f"error:{type(exc).__name__}"],
        )


def _planned_revision_correction(
    catalog: Any,
    kind: str,
    tenant: str,
    graph_id: str,
    revision_id: str,
) -> Dict[str, Any]:
    """Describe the authorized correction without rewriting the revision row."""
    rev = catalog.get_revision(tenant, graph_id, revision_id)
    base = {
        "tenant": tenant,
        "graph_id": graph_id,
        "revision_id": revision_id,
        "parent_revision": rev.parent_revision,
        "storage_profile": rev.storage_profile,
        "existing_checksum": rev.checksum,
        "existing_pin_root": rev.pin_root,
        "existing_manifest_cid": rev.manifest_cid,
    }
    if kind == "clear_invalid_manifest":
        base["proposed_manifest_json"] = None
        base["rationale"] = "clear invalid manifest_json; republish or restore"
        return base
    if kind == "recompute_checksum":
        blob = rev.manifest_json
        if blob:
            try:
                data = json.loads(blob) if isinstance(blob, str) else blob
                man = GraphRevisionManifest.from_dict(data)
                base["proposed_checksum"] = man.checksum.hex_digest
                base["proposed_manifest_cid"] = man.root_cid
                base["proposed_manifest_json"] = man.to_json()
            except ManifestError as exc:
                base["error"] = getattr(exc, "code", type(exc).__name__)
        base["rationale"] = "align catalog checksum to verified manifest identity"
        return base
    base["rationale"] = kind
    return base


__all__ = [
    "MANIFEST_OPS_SCHEMA",
    "MAX_PLAN_ACTIONS",
    "ManifestFinding",
    "ManifestVerifyReport",
    "RepairAction",
    "RepairApplyResult",
    "RepairJournal",
    "RepairPlan",
    "apply_repair_plan",
    "preview_repair",
    "scrub_catalog_manifests",
    "scrub_manifest_dict",
    "verify_manifest",
]
