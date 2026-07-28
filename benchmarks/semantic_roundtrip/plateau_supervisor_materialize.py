"""Supervisor packet materializer for plateau-break Codex packets.

Interface: ``PlateauSupervisorMaterializer@1``

Maps sealed :class:`~benchmarks.semantic_roundtrip.plateau_codex_packet.PlateauCodexPacket`
records into agent-supervisor work items:

* ``implementable=true`` → edit tasks whose ``predicted_files`` are restricted
  to the deterministic surface (``typed_deontic`` constructor, realizers,
  unit tests under ``tests/unit/benchmarks/semantic_roundtrip/``) and whose
  ``validation_commands`` are nonempty;
* ``implementable=false`` → obligation-only notes that list
  ``proof_obligation_ids`` and never authorize a silent merge of candidate L1.

Proof pass is never promotion evidence; the materializer preserves
``semantic_authority=false`` and does not invent edit authority.

Launch doctrine (merge branch, max lanes, ``bundle_supervisor`` flags) lives
in ``docs/benchmarks/semantic_roundtrip_plateau_supervisor_launch.md`` and is
also exposed as constants / helpers here for machine consumption.

Holdout (PLAT2-030): :func:`materialize_holdout_packets` and
:func:`holdout_launch_spec` route implementable holdout residuals onto the
``semantic-roundtrip-plateau-holdout-v1`` board with ``## PLAT2-`` tasks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from benchmarks.semantic_roundtrip.constructors.autoencoder_guided import (
    CanonicalFieldChange,
)
from benchmarks.semantic_roundtrip.plateau_codex_packet import (
    DEFAULT_BASELINE_ARM_ID,
    DEFAULT_BASELINE_E2E,
    DEFAULT_HOLDOUT_VALIDATION_COMMANDS,
    DEFAULT_PREDICTED_FILES,
    DEFAULT_VALIDATION_COMMANDS,
    HOLDOUT_BASELINE_E2E,
    HOLDOUT_POPULATION_KIND,
    PLATEAU_CODEX_PACKET_INTERFACE,
    PlateauCodexPacket,
    PlateauCodexPacketError,
    ProofObligation,
    field_change_path,
)


PLATEAU_SUPERVISOR_MATERIALIZER_INTERFACE: Final = (
    "PlateauSupervisorMaterializer@1"
)
PLATEAU_SUPERVISOR_MATERIALIZER_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-plateau-supervisor-materializer.v1"
)
PLATEAU_SUPERVISOR_TASK_INTERFACE: Final = "PlateauSupervisorTask@1"
PLATEAU_SUPERVISOR_NOTE_INTERFACE: Final = "PlateauSupervisorObligationNote@1"
PLATEAU_SUPERVISOR_MATERIALIZER_EVIDENCE: Final = "PLATEV070SUP"
PLATEAU_SUPERVISOR_MATERIALIZER_HOLDOUT_EVIDENCE: Final = "PLAT2EV030PKT"

# Deterministic edit surface enforced by the materializer (stricter than the
# packet-level predicted-file allowlist, which also permits docs/ and broad
# package modules).  Acceptance for PLAT-070 / PLAT2-030: typed_deontic /
# realizer / tests only.
MATERIALIZER_PREDICTED_FILE_PREFIXES: Final = (
    "benchmarks/semantic_roundtrip/constructors/typed_deontic.py",
    "benchmarks/semantic_roundtrip/constructors/typed_deontic",
    "benchmarks/semantic_roundtrip/realizers/",
    "tests/unit/benchmarks/semantic_roundtrip/",
)

DEFAULT_MATERIALIZER_PREDICTED_FILES: Final = (
    "benchmarks/semantic_roundtrip/constructors/typed_deontic.py",
    "tests/unit/benchmarks/semantic_roundtrip/",
)

# Optional realizer path when cycle residual explicitly requires it.
DEFAULT_REALIZER_PREDICTED_FILE: Final = (
    "benchmarks/semantic_roundtrip/realizers/deterministic.py"
)

# Launch doctrine constants (mirrored in the launch doc).
DEFAULT_MERGE_TARGET_BRANCH: Final = "benchmark/semantic-roundtrip-20260726"
DEFAULT_MAX_LANES: Final = 4
DEFAULT_TASK_PREFIX: Final = "## PLAT-"
DEFAULT_BOARD_NAMESPACE: Final = "semantic-roundtrip-plateau-break-v1"
DEFAULT_BUNDLE: Final = "semantic-roundtrip/plateau-break/supervisor"
DEFAULT_RUNTIME_ROOT: Final = "/var/tmp/hssl-srt-plateau-break"
DEFAULT_TASKBOARD_RELATIVE_PATH: Final = (
    "docs/implementation/plans/semantic_roundtrip_plateau_break.taskboard.todo.md"
)
DEFAULT_SCHEDULER_CONFIG_RELATIVE_PATH: Final = (
    "config/semantic_roundtrip_plateau_break_scheduler.json"
)
BUNDLE_SUPERVISOR_MODULE: Final = (
    "ipfs_accelerate_py.agent_supervisor.bundle_supervisor"
)

# Holdout launch doctrine (PLAT2 / plateau-holdout board).
HOLDOUT_BOARD_NAMESPACE: Final = "semantic-roundtrip-plateau-holdout-v1"
HOLDOUT_BUNDLE: Final = "semantic-roundtrip/plateau-holdout/packets"
HOLDOUT_TASK_PREFIX: Final = "## PLAT2-"
HOLDOUT_RUNTIME_ROOT: Final = "/var/tmp/hssl-srt-plateau-holdout"
HOLDOUT_TASKBOARD_RELATIVE_PATH: Final = (
    "docs/implementation/plans/semantic_roundtrip_plateau_holdout.taskboard.todo.md"
)
HOLDOUT_SCHEDULER_CONFIG_RELATIVE_PATH: Final = (
    "config/semantic_roundtrip_plateau_holdout_scheduler.json"
)
HOLDOUT_MAX_LANES: Final = 2
HOLDOUT_MERGE_TARGET_BRANCH: Final = DEFAULT_MERGE_TARGET_BRANCH

# Case id → parallel edit-wave task id (PLAT-08x).
CASE_TO_EDIT_WAVE_TASK: Final = {
    "legal_doc_1": "PLAT-081",
    "construction_contract": "PLAT-082",
    "corp_policy_1": "PLAT-083",
    "exec_order_1": "PLAT-084",
}

# Holdout case id → det. compiler edit-wave task (PLAT2-050 lane).
HOLDOUT_CASE_TO_EDIT_WAVE_TASK: Final = {
    "missing_temporal": "PLAT2-050",
    "low_confidence_object": "PLAT2-050",
    "contradictory_modality": "PLAT2-050",
}

_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class PlateauSupervisorMaterializeError(ValueError):
    """Raised when packet materialization fails closed."""


class MaterializedKind(str, Enum):
    """Routing kind emitted by the materializer."""

    IMPLEMENTABLE = "implementable"
    OBLIGATION_ONLY = "obligation_only"


def _nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlateauSupervisorMaterializeError(f"{field} must be nonblank")
    return value.strip()


def _sha(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
        default=str,
    ) + "\n"


def is_materializer_allowed_path(path: str) -> bool:
    """Return whether *path* is inside the det. typed_deontic/realizer/tests surface."""

    cleaned = path.strip().replace("\\", "/")
    if not cleaned or ".." in cleaned.split("/"):
        return False
    if cleaned.startswith("/") or cleaned.startswith("\\"):
        return False
    return any(
        cleaned == prefix.rstrip("/") or cleaned.startswith(prefix)
        for prefix in MATERIALIZER_PREDICTED_FILE_PREFIXES
    )


def filter_supervisor_predicted_files(
    paths: Sequence[str] | None,
    *,
    default: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """Filter packet predicted files to the materializer allowlist.

    Paths outside typed_deontic / realizer / tests are dropped.  When the
    filtered set is empty, *default* (or
    :data:`DEFAULT_MATERIALIZER_PREDICTED_FILES`) is used so implementable
    tasks always have a nonempty, fail-closed edit surface.
    """

    if paths is None:
        source: Sequence[str] = ()
    else:
        source = paths
    seen: set[str] = set()
    kept: list[str] = []
    for raw in source:
        if not isinstance(raw, str):
            continue
        cleaned = raw.strip().replace("\\", "/")
        if not cleaned or cleaned in seen:
            continue
        if not is_materializer_allowed_path(cleaned):
            continue
        seen.add(cleaned)
        kept.append(cleaned)
    if kept:
        return tuple(kept)
    fallback = (
        tuple(default)
        if default is not None
        else DEFAULT_MATERIALIZER_PREDICTED_FILES
    )
    validated: list[str] = []
    for item in fallback:
        cleaned = _nonblank(item, "predicted_files item").replace("\\", "/")
        if not is_materializer_allowed_path(cleaned):
            raise PlateauSupervisorMaterializeError(
                "default predicted file is outside materializer allowlist: "
                f"{cleaned!r}"
            )
        if cleaned not in validated:
            validated.append(cleaned)
    if not validated:
        raise PlateauSupervisorMaterializeError(
            "materializer predicted_files must be nonempty"
        )
    return tuple(validated)


def coerce_packet(
    value: PlateauCodexPacket | Mapping[str, object] | str,
    *,
    verify_digest: bool = True,
) -> PlateauCodexPacket:
    """Coerce a packet object, mapping, or JSON string into a sealed packet.

    When *verify_digest* is true (default), any sealed ``packet_digest`` must
    match the recomputed content address (fail-closed).
    """

    if isinstance(value, PlateauCodexPacket):
        packet = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise PlateauSupervisorMaterializeError(
                "packet JSON must be nonblank"
            )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PlateauSupervisorMaterializeError(
                f"packet JSON is invalid: {exc}"
            ) from exc
        try:
            packet = PlateauCodexPacket.from_dict(payload)
        except PlateauCodexPacketError as exc:
            raise PlateauSupervisorMaterializeError(
                f"packet decode failed: {exc}"
            ) from exc
    elif isinstance(value, Mapping):
        try:
            packet = PlateauCodexPacket.from_dict(value)
        except PlateauCodexPacketError as exc:
            raise PlateauSupervisorMaterializeError(
                f"packet decode failed: {exc}"
            ) from exc
    else:
        raise PlateauSupervisorMaterializeError(
            "packet must be PlateauCodexPacket, mapping, or JSON string"
        )

    if verify_digest:
        recomputed = packet.packet_digest
        # Re-verify by round-tripping the sealed dict when digest was present.
        sealed = packet.to_dict()
        try:
            again = PlateauCodexPacket.from_dict(sealed)
        except PlateauCodexPacketError as exc:
            raise PlateauSupervisorMaterializeError(
                f"packet digest verification failed: {exc}"
            ) from exc
        if again.packet_digest != recomputed:
            raise PlateauSupervisorMaterializeError(
                "packet_digest mismatch after materializer recompute"
            )
    return packet


def _task_id_for_packet(packet: PlateauCodexPacket) -> str:
    """Stable supervisor task id derived from packet identity + digest prefix."""

    digest_prefix = packet.packet_digest[:12]
    base = f"PLAT-PKT-{packet.packet_id}-{digest_prefix}"
    # Sanitize to the task id charset.
    sanitized = re.sub(r"[^A-Za-z0-9_.:-]", "-", base)
    if not _TASK_ID_RE.match(sanitized):
        raise PlateauSupervisorMaterializeError(
            f"could not form valid task_id from packet_id {packet.packet_id!r}"
        )
    return sanitized[:128]


def _edit_wave_hint(case_id: str | None) -> str | None:
    if not case_id:
        return None
    if case_id in CASE_TO_EDIT_WAVE_TASK:
        return CASE_TO_EDIT_WAVE_TASK[case_id]
    return HOLDOUT_CASE_TO_EDIT_WAVE_TASK.get(case_id)


def is_holdout_case(case_id: str | None) -> bool:
    """Return whether *case_id* is a preregistered holdout population case."""

    if not case_id:
        return False
    return case_id in HOLDOUT_CASE_TO_EDIT_WAVE_TASK


def is_holdout_packet(packet: PlateauCodexPacket) -> bool:
    """Heuristic: holdout case id, holdout baseline e2e, or holdout detail tag."""

    if is_holdout_case(packet.case_id):
        return True
    if packet.baseline_e2e is not None and float(packet.baseline_e2e) == float(
        HOLDOUT_BASELINE_E2E
    ):
        detail = (packet.detail or "").lower()
        if HOLDOUT_POPULATION_KIND in detail or "holdout" in detail:
            return True
    detail = (packet.detail or "").lower()
    return HOLDOUT_POPULATION_KIND in detail or "holdout residual" in detail


def _field_change_summary(
    changes: Sequence[CanonicalFieldChange],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for change in changes:
        rows.append(
            {
                "path": field_change_path(change),
                "canonical_field": change.canonical_field,
                "before": change.before,
                "after": change.after,
            }
        )
    return rows


def _obligation_summary(
    obligations: Sequence[ProofObligation],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in obligations:
        rows.append(
            {
                "obligation_id": item.obligation_id,
                "constraint": item.constraint,
                "disposition": item.disposition,
                "failed_field_paths": list(item.failed_field_paths),
                "detail": item.detail,
                "semantic_authority": False,
            }
        )
    return rows


@dataclass(frozen=True, slots=True)
class MaterializedSupervisorItem:
    """One supervisor task (implementable) or obligation-only note.

    Implementable items authorize edits within ``predicted_files``.
    Obligation-only items list proof obligations and must not authorize merge
    of a candidate L1 or production path change.
    """

    kind: MaterializedKind
    task_id: str
    title: str
    body: str
    packet_id: str
    packet_digest: str
    implementable: bool
    predicted_files: tuple[str, ...]
    validation_commands: tuple[str, ...]
    proof_obligation_ids: tuple[str, ...]
    residual_ref_ids: tuple[str, ...]
    proposal_ids: tuple[str, ...]
    admitted_field_changes: tuple[dict[str, object], ...]
    proof_obligations: tuple[dict[str, object], ...]
    case_id: str | None = None
    edit_wave_task_id: str | None = None
    baseline_arm_id: str = DEFAULT_BASELINE_ARM_ID
    baseline_e2e: float | None = DEFAULT_BASELINE_E2E
    primary_disposition: str | None = None
    semantic_authority: bool = False
    authorize_merge: bool = False
    detail: str | None = None
    board_namespace: str = DEFAULT_BOARD_NAMESPACE
    bundle: str = DEFAULT_BUNDLE
    population_kind: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "task_id", _nonblank(self.task_id, "task_id")
        )
        if not _TASK_ID_RE.match(self.task_id):
            raise PlateauSupervisorMaterializeError(
                f"task_id has invalid shape: {self.task_id!r}"
            )
        object.__setattr__(
            self, "title", _nonblank(self.title, "title")
        )
        object.__setattr__(
            self, "body", _nonblank(self.body, "body")
        )
        object.__setattr__(
            self, "packet_id", _nonblank(self.packet_id, "packet_id")
        )
        object.__setattr__(
            self,
            "packet_digest",
            _nonblank(self.packet_digest, "packet_digest"),
        )
        if not isinstance(self.kind, MaterializedKind):
            try:
                object.__setattr__(
                    self, "kind", MaterializedKind(self.kind)
                )
            except (TypeError, ValueError) as exc:
                raise PlateauSupervisorMaterializeError(
                    f"invalid materialized kind: {self.kind!r}"
                ) from exc

        if self.semantic_authority is not False:
            raise PlateauSupervisorMaterializeError(
                "materialized items must not claim semantic_authority"
            )

        object.__setattr__(
            self,
            "board_namespace",
            _nonblank(self.board_namespace, "board_namespace"),
        )
        object.__setattr__(
            self, "bundle", _nonblank(self.bundle, "bundle")
        )
        if self.population_kind is not None:
            object.__setattr__(
                self,
                "population_kind",
                _nonblank(self.population_kind, "population_kind"),
            )

        if self.kind is MaterializedKind.IMPLEMENTABLE:
            if not self.implementable:
                raise PlateauSupervisorMaterializeError(
                    "implementable item must set implementable=true"
                )
            files = filter_supervisor_predicted_files(self.predicted_files)
            object.__setattr__(self, "predicted_files", files)
            if not self.validation_commands:
                raise PlateauSupervisorMaterializeError(
                    "implementable task requires validation_commands"
                )
            # Det.-only surface: every predicted file must pass the allowlist.
            for path in files:
                if not is_materializer_allowed_path(path):
                    raise PlateauSupervisorMaterializeError(
                        f"implementable predicted file outside det. surface: "
                        f"{path!r}"
                    )
            # Edit tasks never auto-merge: daemon merges only after gates.
            object.__setattr__(self, "authorize_merge", False)
        else:
            object.__setattr__(self, "implementable", False)
            object.__setattr__(self, "predicted_files", ())
            object.__setattr__(self, "authorize_merge", False)
            if not self.proof_obligation_ids and not self.proof_obligations:
                # Still allow empty-obligation non-implementable notes
                # (e.g. not_applicable with no minted obligations) but flag
                # them clearly in the body path.
                pass

    @property
    def interface(self) -> str:
        if self.kind is MaterializedKind.IMPLEMENTABLE:
            return PLATEAU_SUPERVISOR_TASK_INTERFACE
        return PLATEAU_SUPERVISOR_NOTE_INTERFACE

    def to_dict(self) -> dict[str, object]:
        return {
            "admitted_field_changes": list(self.admitted_field_changes),
            "authorize_merge": self.authorize_merge,
            "baseline_arm_id": self.baseline_arm_id,
            "baseline_e2e": self.baseline_e2e,
            "board_namespace": self.board_namespace,
            "body": self.body,
            "bundle": self.bundle,
            "case_id": self.case_id,
            "detail": self.detail,
            "edit_wave_task_id": self.edit_wave_task_id,
            "evidence": PLATEAU_SUPERVISOR_MATERIALIZER_EVIDENCE,
            "implementable": self.implementable,
            "interface": self.interface,
            "kind": self.kind.value,
            "packet_digest": self.packet_digest,
            "packet_id": self.packet_id,
            "population_kind": self.population_kind,
            "predicted_files": list(self.predicted_files),
            "primary_disposition": self.primary_disposition,
            "proof_obligation_ids": list(self.proof_obligation_ids),
            "proof_obligations": list(self.proof_obligations),
            "proposal_ids": list(self.proposal_ids),
            "residual_ref_ids": list(self.residual_ref_ids),
            "schema": PLATEAU_SUPERVISOR_MATERIALIZER_SCHEMA,
            "semantic_authority": False,
            "task_id": self.task_id,
            "title": self.title,
            "validation_commands": list(self.validation_commands),
        }

    def to_markdown(self) -> str:
        """Render a taskboard-style markdown block consumable by the supervisor."""

        lines: list[str] = [
            f"## {self.task_id} {self.title}",
            "",
            f"- Kind: {self.kind.value}",
            f"- Status: todo",
            f"- Completion: auto",
            f"- Priority: P0",
            f"- Track: supervisor-materialized",
            f"- Packet id: {self.packet_id}",
            f"- Packet digest: {self.packet_digest}",
            f"- Implementable: {str(self.implementable).lower()}",
            f"- Authorize merge: {str(self.authorize_merge).lower()}",
            f"- Semantic authority: false",
        ]
        if self.case_id:
            lines.append(f"- Case id: {self.case_id}")
        if self.population_kind:
            lines.append(f"- Population: {self.population_kind}")
        if self.edit_wave_task_id:
            lines.append(f"- Edit wave task: {self.edit_wave_task_id}")
        if self.primary_disposition:
            lines.append(
                f"- Primary disposition: {self.primary_disposition}"
            )
        if self.predicted_files:
            lines.append(
                "- Predicted files: " + ", ".join(self.predicted_files)
            )
        if self.validation_commands:
            lines.append(
                "- Validation: " + " && ".join(self.validation_commands)
            )
        if self.proof_obligation_ids:
            lines.append(
                "- Proof obligation IDs: "
                + ", ".join(self.proof_obligation_ids)
            )
        if self.residual_ref_ids:
            lines.append(
                "- Residual refs: " + ", ".join(self.residual_ref_ids)
            )
        if self.proposal_ids:
            lines.append(
                "- Proposal ids: " + ", ".join(self.proposal_ids)
            )
        lines.extend(
            [
                f"- Board namespace: {self.board_namespace}",
                f"- Bundle: {self.bundle}",
                f"- Baseline arm: {self.baseline_arm_id}",
                "",
                "### Rationale",
                "",
                self.body,
                "",
            ]
        )
        if (
            self.kind is MaterializedKind.IMPLEMENTABLE
            and self.admitted_field_changes
        ):
            lines.append("### Admitted field changes (ΔL1)")
            lines.append("")
            for change in self.admitted_field_changes:
                path = change.get("path", change.get("canonical_field"))
                lines.append(
                    f"- `{path}`: {change.get('before')!r} → "
                    f"{change.get('after')!r}"
                )
            lines.append("")
        if (
            self.kind is MaterializedKind.OBLIGATION_ONLY
            and self.proof_obligations
        ):
            lines.append("### Proof obligations")
            lines.append("")
            for obligation in self.proof_obligations:
                oid = obligation.get("obligation_id")
                constraint = obligation.get("constraint")
                disposition = obligation.get("disposition")
                lines.append(
                    f"- `{oid}` — constraint `{constraint}` "
                    f"(disposition={disposition}); semantic_authority=false"
                )
            lines.append("")
            lines.append(
                "Do **not** authorize merge of a candidate L1 or silent "
                "production change from this note."
            )
            lines.append("")
        return "\n".join(lines)


def _implementable_body(packet: PlateauCodexPacket) -> str:
    change_paths = [
        field_change_path(change)
        for change in packet.admitted_field_changes
    ]
    residual_ids = [item.residual_id for item in packet.residual_refs]
    proposal_ids = [item.proposal_id for item in packet.proposals]
    wave = _edit_wave_hint(packet.case_id)
    holdout = is_holdout_packet(packet)
    parts = [
        f"Materialized from sealed {PLATEAU_CODEX_PACKET_INTERFACE} "
        f"`{packet.packet_id}` (digest `{packet.packet_digest[:16]}…`).",
        "Edit authority is granted only for the deterministic compiler/"
        "realizer/tests surface listed under predicted_files.",
        (
            "Merge only after structural re-admission, packet validation "
            "commands, and holdout re-score gates pass."
            if holdout
            else "Merge only after structural re-admission, packet validation "
            "commands, and pilot re-score gates pass."
        ),
        "Proof pass alone is not promotion evidence "
        "(semantic_authority=false).",
    ]
    if packet.case_id:
        label = "Holdout case" if holdout else "Pilot case"
        parts.append(f"{label}: `{packet.case_id}`.")
    if wave:
        parts.append(f"Aligns with edit-wave task `{wave}`.")
    if change_paths:
        parts.append(
            "Admitted ΔL1 field paths: "
            + ", ".join(f"`{p}`" for p in change_paths)
            + "."
        )
    if residual_ids:
        parts.append(
            "Residual provenance: "
            + ", ".join(f"`{r}`" for r in residual_ids)
            + "."
        )
    if proposal_ids:
        parts.append(
            "Teacher proposal ids (non-authoritative): "
            + ", ".join(f"`{p}`" for p in proposal_ids)
            + "."
        )
    if packet.detail:
        parts.append(f"Packet detail: {packet.detail}")
    return " ".join(parts)


def _obligation_body(packet: PlateauCodexPacket) -> str:
    ids = list(packet.proof_obligation_ids)
    disposition = packet.primary_disposition.value
    parts = [
        f"Obligation-only note for non-implementable packet "
        f"`{packet.packet_id}` (digest `{packet.packet_digest[:16]}…`).",
        f"Primary disposition: `{disposition}`.",
        "Edit authority is denied; do not merge candidate L1 or change "
        "production defaults from this note.",
        "semantic_authority remains false on all prover receipts.",
    ]
    if ids:
        parts.append(
            "Proof obligation IDs: "
            + ", ".join(f"`{oid}`" for oid in ids)
            + "."
        )
    else:
        parts.append(
            "No proof_obligation_ids were minted; retain prior L1 and "
            "treat as documentation-only."
        )
    residual_ids = [item.residual_id for item in packet.residual_refs]
    if residual_ids:
        parts.append(
            "Residual refs for follow-up: "
            + ", ".join(f"`{r}`" for r in residual_ids)
            + "."
        )
    if packet.detail:
        parts.append(f"Packet detail: {packet.detail}")
    return " ".join(parts)


def materialize_packet(
    packet: PlateauCodexPacket | Mapping[str, object] | str,
    *,
    verify_digest: bool = True,
    predicted_files_override: Sequence[str] | None = None,
    validation_commands_override: Sequence[str] | None = None,
    board_namespace: str | None = None,
    bundle: str | None = None,
    force_holdout: bool = False,
) -> MaterializedSupervisorItem:
    """Materialize one sealed packet into a supervisor task or obligation note.

    * Implementable packets produce ``MaterializedKind.IMPLEMENTABLE`` tasks
      with ``predicted_files`` filtered to typed_deontic / realizer / tests
      and nonempty ``validation_commands``.
    * Non-implementable packets produce ``MaterializedKind.OBLIGATION_ONLY``
      notes listing ``proof_obligation_ids``.
    * Holdout packets (case id / detail / ``force_holdout``) route to the
      PLAT2 board namespace and packet bundle.
    """

    sealed = coerce_packet(packet, verify_digest=verify_digest)
    residual_ids = tuple(item.residual_id for item in sealed.residual_refs)
    proposal_ids = tuple(item.proposal_id for item in sealed.proposals)
    obligation_ids = sealed.proof_obligation_ids
    obligations = tuple(_obligation_summary(sealed.proof_obligations))
    changes = tuple(_field_change_summary(sealed.admitted_field_changes))
    task_id = _task_id_for_packet(sealed)
    wave = _edit_wave_hint(sealed.case_id)
    disposition = sealed.primary_disposition.value
    holdout = force_holdout or is_holdout_packet(sealed)
    namespace = (
        board_namespace
        if board_namespace is not None
        else (
            HOLDOUT_BOARD_NAMESPACE if holdout else DEFAULT_BOARD_NAMESPACE
        )
    )
    active_bundle = (
        bundle
        if bundle is not None
        else (HOLDOUT_BUNDLE if holdout else DEFAULT_BUNDLE)
    )
    population = HOLDOUT_POPULATION_KIND if holdout else None

    if sealed.implementable:
        files = filter_supervisor_predicted_files(
            predicted_files_override
            if predicted_files_override is not None
            else sealed.predicted_files
        )
        commands = tuple(
            validation_commands_override
            if validation_commands_override is not None
            else sealed.validation_commands
        )
        if not commands:
            commands = (
                DEFAULT_HOLDOUT_VALIDATION_COMMANDS
                if holdout
                else DEFAULT_VALIDATION_COMMANDS
            )
        case_label = sealed.case_id or "unknown-case"
        title = (
            f"Det. compiler edit from packet {sealed.packet_id} "
            f"({case_label})"
        )
        return MaterializedSupervisorItem(
            kind=MaterializedKind.IMPLEMENTABLE,
            task_id=task_id,
            title=title,
            body=_implementable_body(sealed),
            packet_id=sealed.packet_id,
            packet_digest=sealed.packet_digest,
            implementable=True,
            predicted_files=files,
            validation_commands=commands,
            proof_obligation_ids=obligation_ids,
            residual_ref_ids=residual_ids,
            proposal_ids=proposal_ids,
            admitted_field_changes=changes,
            proof_obligations=obligations,
            case_id=sealed.case_id,
            edit_wave_task_id=wave,
            baseline_arm_id=sealed.baseline_arm_id,
            baseline_e2e=sealed.baseline_e2e,
            primary_disposition=disposition,
            semantic_authority=False,
            authorize_merge=False,
            detail=sealed.detail,
            board_namespace=namespace,
            bundle=active_bundle,
            population_kind=population,
        )

    title = (
        f"Obligation-only note for packet {sealed.packet_id} "
        f"({disposition})"
    )
    return MaterializedSupervisorItem(
        kind=MaterializedKind.OBLIGATION_ONLY,
        task_id=task_id,
        title=title,
        body=_obligation_body(sealed),
        packet_id=sealed.packet_id,
        packet_digest=sealed.packet_digest,
        implementable=False,
        predicted_files=(),
        validation_commands=(),
        proof_obligation_ids=obligation_ids,
        residual_ref_ids=residual_ids,
        proposal_ids=proposal_ids,
        admitted_field_changes=(),
        proof_obligations=obligations,
        case_id=sealed.case_id,
        edit_wave_task_id=wave,
        baseline_arm_id=sealed.baseline_arm_id,
        baseline_e2e=sealed.baseline_e2e,
        primary_disposition=disposition,
        semantic_authority=False,
        authorize_merge=False,
        detail=sealed.detail,
        board_namespace=namespace,
        bundle=active_bundle,
        population_kind=population,
    )


@dataclass(frozen=True, slots=True)
class MaterializerReceipt:
    """Batch receipt for materializing one or more packets."""

    items: tuple[MaterializedSupervisorItem, ...]
    implementable_count: int
    obligation_only_count: int
    packet_ids: tuple[str, ...]
    packet_digests: tuple[str, ...]
    evidence: str = PLATEAU_SUPERVISOR_MATERIALIZER_EVIDENCE
    interface: str = PLATEAU_SUPERVISOR_MATERIALIZER_INTERFACE
    schema: str = PLATEAU_SUPERVISOR_MATERIALIZER_SCHEMA
    semantic_authority: bool = False
    merge_target_branch: str = DEFAULT_MERGE_TARGET_BRANCH
    max_lanes: int = DEFAULT_MAX_LANES

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        if self.semantic_authority is not False:
            raise PlateauSupervisorMaterializeError(
                "materializer receipt must not claim semantic_authority"
            )
        if self.implementable_count != sum(
            1
            for item in self.items
            if item.kind is MaterializedKind.IMPLEMENTABLE
        ):
            raise PlateauSupervisorMaterializeError(
                "implementable_count does not match items"
            )
        if self.obligation_only_count != sum(
            1
            for item in self.items
            if item.kind is MaterializedKind.OBLIGATION_ONLY
        ):
            raise PlateauSupervisorMaterializeError(
                "obligation_only_count does not match items"
            )

    @property
    def receipt_digest(self) -> str:
        return _sha(self.payload_for_digest())

    def payload_for_digest(self) -> dict[str, object]:
        return {
            "evidence": self.evidence,
            "implementable_count": self.implementable_count,
            "interface": self.interface,
            "items": [item.to_dict() for item in self.items],
            "max_lanes": self.max_lanes,
            "merge_target_branch": self.merge_target_branch,
            "obligation_only_count": self.obligation_only_count,
            "packet_digests": list(self.packet_digests),
            "packet_ids": list(self.packet_ids),
            "schema": self.schema,
            "semantic_authority": False,
        }

    def to_dict(self) -> dict[str, object]:
        payload = self.payload_for_digest()
        payload["receipt_digest"] = self.receipt_digest
        return payload

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    def implementable_items(self) -> tuple[MaterializedSupervisorItem, ...]:
        return tuple(
            item
            for item in self.items
            if item.kind is MaterializedKind.IMPLEMENTABLE
        )

    def obligation_only_items(
        self,
    ) -> tuple[MaterializedSupervisorItem, ...]:
        return tuple(
            item
            for item in self.items
            if item.kind is MaterializedKind.OBLIGATION_ONLY
        )

    def to_markdown(self) -> str:
        blocks = [item.to_markdown() for item in self.items]
        header = (
            f"# Plateau supervisor materializer receipt\n\n"
            f"- Interface: `{self.interface}`\n"
            f"- Evidence: `{self.evidence}`\n"
            f"- Implementable tasks: {self.implementable_count}\n"
            f"- Obligation-only notes: {self.obligation_only_count}\n"
            f"- Merge target branch: `{self.merge_target_branch}`\n"
            f"- Max lanes: {self.max_lanes}\n"
            f"- Semantic authority: false\n"
            f"- Receipt digest: `{self.receipt_digest}`\n\n"
            "---\n\n"
        )
        return header + "\n---\n\n".join(blocks)


def materialize_packets(
    packets: Sequence[PlateauCodexPacket | Mapping[str, object] | str],
    *,
    verify_digest: bool = True,
    merge_target_branch: str = DEFAULT_MERGE_TARGET_BRANCH,
    max_lanes: int = DEFAULT_MAX_LANES,
    force_holdout: bool = False,
    board_namespace: str | None = None,
    bundle: str | None = None,
) -> MaterializerReceipt:
    """Materialize a sequence of packets into a batch receipt.

    Emits one supervisor item per packet.  Implementable items always carry
    det.-only ``predicted_files`` and nonempty ``validation_commands``.
    """

    if not isinstance(packets, Sequence) or isinstance(
        packets, (str, bytes, bytearray)
    ):
        raise PlateauSupervisorMaterializeError(
            "packets must be a sequence of packet objects/dicts/JSON"
        )
    items: list[MaterializedSupervisorItem] = []
    for index, raw in enumerate(packets):
        try:
            items.append(
                materialize_packet(
                    raw,
                    verify_digest=verify_digest,
                    force_holdout=force_holdout,
                    board_namespace=board_namespace,
                    bundle=bundle,
                )
            )
        except PlateauSupervisorMaterializeError as exc:
            raise PlateauSupervisorMaterializeError(
                f"packet[{index}] materialization failed: {exc}"
            ) from exc
    implementable_count = sum(
        1 for item in items if item.kind is MaterializedKind.IMPLEMENTABLE
    )
    obligation_only_count = len(items) - implementable_count
    return MaterializerReceipt(
        items=tuple(items),
        implementable_count=implementable_count,
        obligation_only_count=obligation_only_count,
        packet_ids=tuple(item.packet_id for item in items),
        packet_digests=tuple(item.packet_digest for item in items),
        merge_target_branch=_nonblank(
            merge_target_branch, "merge_target_branch"
        ),
        max_lanes=int(max_lanes),
    )


def materialize_holdout_packets(
    packets: Sequence[PlateauCodexPacket | Mapping[str, object] | str],
    *,
    verify_digest: bool = True,
    merge_target_branch: str = HOLDOUT_MERGE_TARGET_BRANCH,
    max_lanes: int = HOLDOUT_MAX_LANES,
) -> MaterializerReceipt:
    """Materialize holdout residual packets onto the PLAT2 board.

    Forces holdout board namespace / packets bundle.  Each implementable packet
    becomes exactly one task with det.-only predicted files and validation
    commands; reject/timeout packets become obligation-only notes.
    """

    return materialize_packets(
        packets,
        verify_digest=verify_digest,
        merge_target_branch=merge_target_branch,
        max_lanes=max_lanes,
        force_holdout=True,
        board_namespace=HOLDOUT_BOARD_NAMESPACE,
        bundle=HOLDOUT_BUNDLE,
    )


def load_packets_from_json_path(
    path: str | Path,
) -> list[PlateauCodexPacket]:
    """Load one packet or a list of packets from a JSON file."""

    text = Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlateauSupervisorMaterializeError(
            f"invalid packet JSON file {path}: {exc}"
        ) from exc
    if isinstance(payload, Mapping):
        # Single packet or wrapper with "packets" key.
        if "packets" in payload and isinstance(payload["packets"], list):
            raw_list = payload["packets"]
        elif "packet_id" in payload or "interface" in payload:
            raw_list = [payload]
        else:
            raise PlateauSupervisorMaterializeError(
                "JSON object must be a packet or contain a 'packets' array"
            )
    elif isinstance(payload, list):
        raw_list = payload
    else:
        raise PlateauSupervisorMaterializeError(
            "packet file must be a JSON object or array"
        )
    packets: list[PlateauCodexPacket] = []
    for index, item in enumerate(raw_list):
        try:
            packets.append(coerce_packet(item))
        except PlateauSupervisorMaterializeError as exc:
            raise PlateauSupervisorMaterializeError(
                f"packets[{index}] invalid: {exc}"
            ) from exc
    return packets


@dataclass(frozen=True, slots=True)
class BundleSupervisorLaunchSpec:
    """Documented launch flags for plateau-break ``bundle_supervisor``."""

    merge_target_branch: str = DEFAULT_MERGE_TARGET_BRANCH
    max_lanes: int = DEFAULT_MAX_LANES
    task_prefix: str = DEFAULT_TASK_PREFIX
    runtime_root: str = DEFAULT_RUNTIME_ROOT
    repo_root: str = "$REPO"
    implement: bool = True
    start: bool = True
    board_namespace: str = DEFAULT_BOARD_NAMESPACE
    taskboard_path: str = DEFAULT_TASKBOARD_RELATIVE_PATH
    scheduler_config_path: str = DEFAULT_SCHEDULER_CONFIG_RELATIVE_PATH

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "merge_target_branch",
            _nonblank(self.merge_target_branch, "merge_target_branch"),
        )
        object.__setattr__(
            self, "task_prefix", _nonblank(self.task_prefix, "task_prefix")
        )
        object.__setattr__(
            self,
            "scheduler_config_path",
            _nonblank(self.scheduler_config_path, "scheduler_config_path"),
        )
        if int(self.max_lanes) < 1:
            raise PlateauSupervisorMaterializeError(
                "max_lanes must be at least 1"
            )
        object.__setattr__(self, "max_lanes", int(self.max_lanes))

    @property
    def bundle_index_path(self) -> str:
        return f"{self.runtime_root.rstrip('/')}/bundles/index.json"

    @property
    def state_root(self) -> str:
        return f"{self.runtime_root.rstrip('/')}/state"

    @property
    def worktree_root(self) -> str:
        return f"{self.runtime_root.rstrip('/')}/worktrees"

    def flags(self) -> dict[str, object]:
        """Structured flag map for launch documentation and tests."""

        return {
            "bundle_index_path": self.bundle_index_path,
            "implement": self.implement,
            "max_lanes": self.max_lanes,
            "merge_target_branch": self.merge_target_branch,
            "repo_root": self.repo_root,
            "start": self.start,
            "state_root": self.state_root,
            "task_prefix": self.task_prefix,
            "worktree_root": self.worktree_root,
            "board_namespace": self.board_namespace,
            "taskboard_path": self.taskboard_path,
            "scheduler_config_path": self.scheduler_config_path,
            "module": BUNDLE_SUPERVISOR_MODULE,
        }

    def command_lines(self) -> list[str]:
        """Shell lines for prepare + launch (operator copy-paste)."""

        prepare = (
            "python -m benchmarks.semantic_roundtrip_scheduler prepare \\\n"
            f"  --repo-root {self.repo_root} \\\n"
            f"  --config-path {self.scheduler_config_path} \\\n"
            f"  --runtime-root {self.runtime_root} \\\n"
            f"  --taskboard-path {self.taskboard_path}"
        )
        flags = [
            f"python -m {BUNDLE_SUPERVISOR_MODULE} \\",
            f"  --bundle-index-path {self.bundle_index_path} \\",
            f"  --repo-root {self.repo_root} \\",
            f"  --state-root {self.state_root} \\",
            f"  --worktree-root {self.worktree_root} \\",
            f"  --task-prefix '{self.task_prefix}' \\",
            f"  --max-lanes {self.max_lanes} \\",
            f"  --merge-target-branch {self.merge_target_branch} \\",
        ]
        tail: list[str] = []
        if self.implement:
            tail.append("--implement")
        if self.start:
            tail.append("--start")
        if tail:
            flags.append("  " + " ".join(tail))
        launch = "\n".join(flags)
        return [
            "export PYTHONPATH=ipfs_accelerate_py:.",
            prepare,
            launch,
        ]

    def to_command(self) -> str:
        return "\n\n".join(self.command_lines())

    def to_dict(self) -> dict[str, object]:
        return self.flags()


def default_launch_spec() -> BundleSupervisorLaunchSpec:
    """Return the sealed default launch specification for plateau-break."""

    return BundleSupervisorLaunchSpec()


def holdout_launch_spec() -> BundleSupervisorLaunchSpec:
    """Return launch specification for the plateau-holdout (PLAT2) board."""

    return BundleSupervisorLaunchSpec(
        merge_target_branch=HOLDOUT_MERGE_TARGET_BRANCH,
        max_lanes=HOLDOUT_MAX_LANES,
        task_prefix=HOLDOUT_TASK_PREFIX,
        runtime_root=HOLDOUT_RUNTIME_ROOT,
        board_namespace=HOLDOUT_BOARD_NAMESPACE,
        taskboard_path=HOLDOUT_TASKBOARD_RELATIVE_PATH,
        scheduler_config_path=HOLDOUT_SCHEDULER_CONFIG_RELATIVE_PATH,
    )


def render_launch_markdown(
    spec: BundleSupervisorLaunchSpec | None = None,
) -> str:
    """Render a short launch snippet (used by docs and CLI)."""

    active = spec or default_launch_spec()
    lines = [
        "# Plateau supervisor launch (generated snippet)",
        "",
        f"- Merge target branch: `{active.merge_target_branch}`",
        f"- Max lanes: `{active.max_lanes}`",
        f"- Task prefix: `{active.task_prefix}`",
        f"- Board namespace: `{active.board_namespace}`",
        f"- Module: `{BUNDLE_SUPERVISOR_MODULE}`",
        "",
        "```bash",
        active.to_command(),
        "```",
        "",
    ]
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize PlateauCodexPacket@1 records into supervisor "
            "tasks / obligation-only notes."
        )
    )
    parser.add_argument(
        "packet_path",
        nargs="?",
        type=Path,
        help="JSON file containing one packet, a list, or {packets: [...]}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write materializer receipt JSON to this path",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=None,
        help="Write taskboard-style markdown projection",
    )
    parser.add_argument(
        "--print-launch",
        action="store_true",
        help="Print bundle_supervisor launch flags and exit",
    )
    parser.add_argument(
        "--merge-target-branch",
        default=DEFAULT_MERGE_TARGET_BRANCH,
        help="Merge branch recorded on the receipt / launch snippet",
    )
    parser.add_argument(
        "--max-lanes",
        type=int,
        default=DEFAULT_MAX_LANES,
        help="Max concurrent lanes recorded on the receipt / launch snippet",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.print_launch:
        spec = BundleSupervisorLaunchSpec(
            merge_target_branch=args.merge_target_branch,
            max_lanes=args.max_lanes,
        )
        print(render_launch_markdown(spec), end="")
        return 0

    if args.packet_path is None:
        parser.error("packet_path is required unless --print-launch is set")

    packets = load_packets_from_json_path(args.packet_path)
    receipt = materialize_packets(
        packets,
        merge_target_branch=args.merge_target_branch,
        max_lanes=args.max_lanes,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(receipt.to_json(), encoding="utf-8")
    if args.markdown is not None:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(receipt.to_markdown(), encoding="utf-8")
    if args.output is None and args.markdown is None:
        print(receipt.to_json(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BUNDLE_SUPERVISOR_MODULE",
    "CASE_TO_EDIT_WAVE_TASK",
    "DEFAULT_BASELINE_ARM_ID",
    "DEFAULT_BASELINE_E2E",
    "DEFAULT_BOARD_NAMESPACE",
    "DEFAULT_BUNDLE",
    "DEFAULT_MATERIALIZER_PREDICTED_FILES",
    "DEFAULT_MAX_LANES",
    "DEFAULT_MERGE_TARGET_BRANCH",
    "DEFAULT_PREDICTED_FILES",
    "DEFAULT_REALIZER_PREDICTED_FILE",
    "DEFAULT_RUNTIME_ROOT",
    "DEFAULT_SCHEDULER_CONFIG_RELATIVE_PATH",
    "DEFAULT_TASK_PREFIX",
    "DEFAULT_TASKBOARD_RELATIVE_PATH",
    "DEFAULT_VALIDATION_COMMANDS",
    "HOLDOUT_BOARD_NAMESPACE",
    "HOLDOUT_BUNDLE",
    "HOLDOUT_CASE_TO_EDIT_WAVE_TASK",
    "HOLDOUT_MAX_LANES",
    "HOLDOUT_MERGE_TARGET_BRANCH",
    "HOLDOUT_RUNTIME_ROOT",
    "HOLDOUT_SCHEDULER_CONFIG_RELATIVE_PATH",
    "HOLDOUT_TASK_PREFIX",
    "HOLDOUT_TASKBOARD_RELATIVE_PATH",
    "MATERIALIZER_PREDICTED_FILE_PREFIXES",
    "PLATEAU_SUPERVISOR_MATERIALIZER_EVIDENCE",
    "PLATEAU_SUPERVISOR_MATERIALIZER_HOLDOUT_EVIDENCE",
    "PLATEAU_SUPERVISOR_MATERIALIZER_INTERFACE",
    "PLATEAU_SUPERVISOR_MATERIALIZER_SCHEMA",
    "PLATEAU_SUPERVISOR_NOTE_INTERFACE",
    "PLATEAU_SUPERVISOR_TASK_INTERFACE",
    "BundleSupervisorLaunchSpec",
    "MaterializedKind",
    "MaterializedSupervisorItem",
    "MaterializerReceipt",
    "PlateauSupervisorMaterializeError",
    "coerce_packet",
    "default_launch_spec",
    "filter_supervisor_predicted_files",
    "holdout_launch_spec",
    "is_holdout_case",
    "is_holdout_packet",
    "is_materializer_allowed_path",
    "load_packets_from_json_path",
    "main",
    "materialize_holdout_packets",
    "materialize_packet",
    "materialize_packets",
    "render_launch_markdown",
]
