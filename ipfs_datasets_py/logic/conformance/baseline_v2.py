"""Wave-2 baseline join and lifecycle maturity rules (LFP2-005).

``LogicRuntimeBaseline@2`` binds the four Wave-2 evidence-baseline artifacts
under one content-addressed receipt:

* ``LogicClaimRuntimeAudit@1`` — claim vs runtime lifecycle evidence
* ``RawLogicBoundaryInventory@1`` — raw formula/source/payload boundaries
* ``ReachableCapabilityGraph@1`` — sparse domain-to-provider reachability
* ``LogicConformanceCorpus@2`` — content-addressed conformance fixtures

``CapabilityLifecycle@1`` publishes the monotonic maturity vocabulary and
transition evidence obligations so declaration, parse, compile, execute,
replay, and authority states cannot be conflated.

Fail-closed acceptance (LFP2-005):

* Conflicting claims (schema/revision/source-identity drift, duplicate claim
  rows with disagreeing lifecycle, authority/lifecycle conflation) raise.
* Every reachable gap carries exactly one owner and one evidence obligation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.logic.conformance.claim_runtime_audit import (
    GOAL_ID as CLAIM_GOAL_ID,
)
from ipfs_datasets_py.logic.conformance.claim_runtime_audit import (
    LOGIC_CLAIM_RUNTIME_AUDIT_INTERFACE,
    LOGIC_CLAIM_RUNTIME_AUDIT_REPORT_SCHEMA,
    ClaimLifecycleStage,
    ClaimRuntimeAuditError,
    LogicClaimRuntimeAuditReport,
    assert_audit_acceptance,
    default_datasets_repo_root,
    lifecycle_rank,
    load_audit_baseline,
)
from ipfs_datasets_py.logic.conformance.claim_runtime_audit import (
    PROGRAM_ID as CLAIM_PROGRAM_ID,
)
from ipfs_datasets_py.logic.conformance.claim_runtime_audit import (
    TASK_ID as CLAIM_TASK_ID,
)
from ipfs_datasets_py.logic.conformance.claim_runtime_audit import (
    default_baseline_path as claim_baseline_path,
)
from ipfs_datasets_py.logic.conformance.claim_runtime_audit import (
    ensure_baseline_seal as ensure_claim_baseline_seal,
)
from ipfs_datasets_py.logic.conformance.corpus_v2 import (
    LOGIC_CONFORMANCE_CORPUS_INTERFACE,
    LOGIC_CONFORMANCE_CORPUS_SCHEMA_VERSION,
    CorpusError,
    LogicConformanceCorpus,
    default_manifest_path,
    load_corpus,
)
from ipfs_datasets_py.logic.conformance.raw_boundary_inventory import (
    INVENTORY_GOAL_ID as BOUNDARY_GOAL_ID,
)
from ipfs_datasets_py.logic.conformance.raw_boundary_inventory import (
    INVENTORY_TASK_ID as BOUNDARY_TASK_ID,
)
from ipfs_datasets_py.logic.conformance.raw_boundary_inventory import (
    RAW_LOGIC_BOUNDARY_INVENTORY_INTERFACE,
    RAW_LOGIC_BOUNDARY_INVENTORY_SCHEMA_VERSION,
    RawBoundaryInventoryError,
    curated_raw_boundary_inventory,
    load_raw_boundary_inventory,
)
from ipfs_datasets_py.logic.conformance.raw_boundary_inventory import (
    default_baseline_report_path as boundary_baseline_path,
)
from ipfs_datasets_py.logic.conformance.reachable_graph import (
    GOAL_ID as GRAPH_GOAL_ID,
)
from ipfs_datasets_py.logic.conformance.reachable_graph import (
    LIFECYCLE_STAGES as GRAPH_LIFECYCLE_STAGES,
)
from ipfs_datasets_py.logic.conformance.reachable_graph import (
    PROGRAM_ID as GRAPH_PROGRAM_ID,
)
from ipfs_datasets_py.logic.conformance.reachable_graph import (
    REACHABLE_CAPABILITY_GRAPH_INTERFACE,
    REACHABLE_CAPABILITY_GRAPH_SCHEMA,
    ReachableCapabilityGraph,
    ReachableCapabilityGraphError,
    SupportStatus,
    assert_graph_acceptance,
    build_default_graph,
    load_graph_baseline,
)
from ipfs_datasets_py.logic.conformance.reachable_graph import (
    TASK_ID as GRAPH_TASK_ID,
)
from ipfs_datasets_py.logic.conformance.reachable_graph import (
    default_baseline_path as graph_baseline_path,
)

# ---------------------------------------------------------------------------
# Interface / schema
# ---------------------------------------------------------------------------

LOGIC_RUNTIME_BASELINE_INTERFACE: Final = "LogicRuntimeBaseline@2"
LOGIC_RUNTIME_BASELINE_SCHEMA: Final = "logic-runtime-baseline/v2"
CAPABILITY_LIFECYCLE_INTERFACE: Final = "CapabilityLifecycle@1"
CAPABILITY_LIFECYCLE_SCHEMA: Final = "capability-lifecycle/v1"
GAP_ROW_SCHEMA: Final = "logic-runtime-baseline-gap/v1"
BASELINE_REPORT_VERSION: Final = "1.0.0"

TASK_ID: Final = "LFP2-005"
GOAL_ID: Final = "LFP2-G020"
PROGRAM_ID: Final = "ipfs-datasets-logic-family-parser-v2"
SOURCE_GOAL_ID: Final = "LFP2-G010"

DEFAULT_BASELINE_RELATIVE_PATH: Final = (
    "docs/architecture/logic/logic_parser_v2_baseline/baseline_join.json"
)
MATERIALIZATION_TARGET: Final = (
    "ipfs_datasets_py.logic.conformance.baseline_v2:build_default_baseline_join"
)

# Lifecycle stages: ordered, distinct, never conflated.
LIFECYCLE_STAGES: Final[tuple[str, ...]] = (
    "declared",
    "parsed",
    "elaborated",
    "translatable",
    "compilable",
    "executable",
    "replayed",
    "independently_validated",
)

# Authority is a separate axis from lifecycle maturity.
AUTHORITY_AXIS: Final[tuple[str, ...]] = (
    "none",
    "candidate",
    "advisory",
    "bounded",
    "over_approximation",
    "exact",
    "protocol_symbolic",
    "authorization_profile",
    "finite_trace",
    "kernel",
)

# Evidence obligations required to advance past each stage.
STAGE_EVIDENCE_OBLIGATIONS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "declared": "registry_or_matrix_declaration",
        "parsed": "parser_surface_with_parse_artifact",
        "elaborated": "typed_elaboration_artifact",
        "translatable": "reviewed_translation_receipt",
        "compilable": "compiled_logic_or_parsed_target_artifact",
        "executable": "non_mock_runner_execution_receipt",
        "replayed": "evidence_replay_receipt",
        "independently_validated": "official_kernel_or_independent_validator",
    }
)

# Transitions that may never be silently skipped or renamed into each other.
NON_CONFLATABLE_PAIRS: Final[tuple[tuple[str, str], ...]] = (
    ("declared", "parsed"),
    ("parsed", "elaborated"),
    ("elaborated", "compilable"),
    ("compilable", "executable"),
    ("executable", "replayed"),
    ("replayed", "independently_validated"),
    ("declared", "executable"),
    ("parsed", "executable"),
    ("executable", "authority"),
    ("declared", "authority"),
)

ARTIFACT_KEYS: Final[tuple[str, ...]] = (
    "claim_runtime_audit",
    "raw_boundary_inventory",
    "reachable_capability_graph",
    "conformance_corpus",
)

# Owner for gaps that this join itself classifies (extension payloads, etc.).
DEFAULT_JOIN_OWNER: Final = TASK_ID
EXTENSION_GAP_OWNER: Final = "LFP2-006"
GRAPH_WORK_OWNER: Final = "LFP2-003"
BOUNDARY_GAP_OWNER: Final = "LFP2-002"
CLAIM_GAP_OWNER: Final = "LFP2-001"
CORPUS_GAP_OWNER: Final = "LFP2-004"


class BaselineV2Error(ValueError):
    """Raised when Wave-2 baseline join detects drift or conflict."""


class GapSource(StrEnum):
    """Origin of a reachable gap surface."""

    CLAIM_AUDIT = "claim_audit"
    RAW_BOUNDARY = "raw_boundary"
    REACHABLE_GRAPH = "reachable_graph"
    CORPUS = "corpus"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise BaselineV2Error(
            f"{field_name} must be a non-empty trimmed string without NUL"
        )
    return value


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BaselineV2Error(f"{label} must be a mapping")
    return dict(value)


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _relative_to_datasets(path: Path, datasets_root: Path) -> str:
    try:
        return path.resolve().relative_to(datasets_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BaselineV2Error(f"missing baseline artifact: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _require_mapping(payload, path.name)


def lifecycle_stage_rank(stage: str | ClaimLifecycleStage) -> int:
    """Return the comparable rank of a lifecycle stage."""

    value = stage.value if isinstance(stage, ClaimLifecycleStage) else str(stage)
    if value not in LIFECYCLE_STAGES:
        raise BaselineV2Error(f"unknown lifecycle stage {value!r}")
    return LIFECYCLE_STAGES.index(value)


def assert_stages_not_conflated(left: str, right: str) -> None:
    """Fail closed when two distinct lifecycle axes are treated as equal."""

    left_s = _text(left, "left_stage")
    right_s = _text(right, "right_stage")
    if left_s == right_s:
        return
    if {left_s, right_s} == {"authority", "executable"} or (
        left_s == "authority" or right_s == "authority"
    ):
        # Authority is never a lifecycle stage.
        if left_s in LIFECYCLE_STAGES and right_s == "authority":
            raise BaselineV2Error(
                f"lifecycle stage {left_s!r} must not be conflated with authority"
            )
        if right_s in LIFECYCLE_STAGES and left_s == "authority":
            raise BaselineV2Error(
                f"lifecycle stage {right_s!r} must not be conflated with authority"
            )
    if (left_s, right_s) in NON_CONFLATABLE_PAIRS or (
        right_s,
        left_s,
    ) in NON_CONFLATABLE_PAIRS:
        raise BaselineV2Error(
            f"conflicting lifecycle claims: {left_s!r} must not be "
            f"conflated with {right_s!r}"
        )


# ---------------------------------------------------------------------------
# CapabilityLifecycle@1
# ---------------------------------------------------------------------------


def build_capability_lifecycle() -> dict[str, Any]:
    """Publish CapabilityLifecycle@1 maturity rules (pure, side-effect free)."""

    transitions: list[dict[str, Any]] = []
    for index, stage in enumerate(LIFECYCLE_STAGES):
        if index == 0:
            continue
        previous = LIFECYCLE_STAGES[index - 1]
        transitions.append(
            {
                "from": previous,
                "to": stage,
                "evidence_obligation": STAGE_EVIDENCE_OBLIGATIONS[stage],
                "monotonic": True,
                "skippable": stage
                in {"elaborated", "translatable", "replayed", "independently_validated"},
                "notes": (
                    "Soft gate: may be absent when a later stage is established "
                    "by independent evidence."
                    if stage
                    in {
                        "elaborated",
                        "translatable",
                        "replayed",
                        "independently_validated",
                    }
                    else "Hard gate: stage evidence is required to claim this maturity."
                ),
            }
        )

    return {
        "interface": CAPABILITY_LIFECYCLE_INTERFACE,
        "schema_version": CAPABILITY_LIFECYCLE_SCHEMA,
        "version": "1.0.0",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "description": (
            "Monotonic capability lifecycle maturity rules. Declaration, parse, "
            "compile, execute, replay, and authority remain distinct axes; "
            "mocks and metadata-only records cannot satisfy executable or later."
        ),
        "stages": list(LIFECYCLE_STAGES),
        "stage_evidence_obligations": dict(STAGE_EVIDENCE_OBLIGATIONS),
        "transitions": transitions,
        "authority_axis": list(AUTHORITY_AXIS),
        "authority_policy": {
            "authority_is_not_lifecycle": True,
            "executable_does_not_imply_kernel_authority": True,
            "advisory_never_promotes_to_kernel": True,
            "authority_bearing_requires_runtime_or_typed_gap": True,
        },
        "non_conflatable_pairs": [
            {"left": left, "right": right} for left, right in NON_CONFLATABLE_PAIRS
        ],
        "fail_closed": {
            "conflicting_claims_rejected": True,
            "stage_rename_rejected": True,
            "silent_promotion_rejected": True,
            "mock_execution_rejected": True,
        },
    }


def validate_capability_lifecycle(payload: Mapping[str, Any]) -> None:
    """Fail closed when CapabilityLifecycle@1 is malformed."""

    body = _require_mapping(payload, "capability_lifecycle")
    if body.get("interface") != CAPABILITY_LIFECYCLE_INTERFACE:
        raise BaselineV2Error(
            f"capability lifecycle interface drift: {body.get('interface')!r}"
        )
    if body.get("schema_version") != CAPABILITY_LIFECYCLE_SCHEMA:
        raise BaselineV2Error(
            f"capability lifecycle schema drift: {body.get('schema_version')!r}"
        )
    stages = body.get("stages")
    if list(stages or ()) != list(LIFECYCLE_STAGES):
        raise BaselineV2Error("capability lifecycle stages vocabulary drift")
    obligations = body.get("stage_evidence_obligations")
    if not isinstance(obligations, Mapping):
        raise BaselineV2Error("stage_evidence_obligations must be a mapping")
    for stage in LIFECYCLE_STAGES:
        if stage not in obligations or not obligations[stage]:
            raise BaselineV2Error(
                f"missing evidence obligation for lifecycle stage {stage!r}"
            )
    authority_policy = _require_mapping(
        body.get("authority_policy"), "authority_policy"
    )
    if authority_policy.get("authority_is_not_lifecycle") is not True:
        raise BaselineV2Error("authority must remain a distinct axis from lifecycle")
    if authority_policy.get("executable_does_not_imply_kernel_authority") is not True:
        raise BaselineV2Error(
            "executable maturity must not imply kernel authority"
        )


# ---------------------------------------------------------------------------
# Gap surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BaselineGap:
    """One reachable gap with a single owner and evidence obligation."""

    gap_id: str
    source: GapSource
    owner: str
    evidence_obligation: str
    subject_id: str
    stage: str
    detail: str = ""
    schema_version: str = GAP_ROW_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "gap_id", _text(self.gap_id, "gap_id"))
        if isinstance(self.source, GapSource):
            source = self.source
        else:
            try:
                source = GapSource(str(self.source))
            except ValueError as exc:
                raise BaselineV2Error(f"invalid gap source {self.source!r}") from exc
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "owner", _text(self.owner, "owner"))
        object.__setattr__(
            self,
            "evidence_obligation",
            _text(self.evidence_obligation, "evidence_obligation"),
        )
        object.__setattr__(self, "subject_id", _text(self.subject_id, "subject_id"))
        object.__setattr__(self, "stage", _text(self.stage, "stage"))
        object.__setattr__(
            self, "detail", _text(self.detail, "detail", optional=True)
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "detail": self.detail,
            "evidence_obligation": self.evidence_obligation,
            "gap_id": self.gap_id,
            "owner": self.owner,
            "schema_version": self.schema_version,
            "source": self.source.value,
            "stage": self.stage,
            "subject_id": self.subject_id,
        }


def _obligation_for_stage(stage: str) -> str:
    if stage in STAGE_EVIDENCE_OBLIGATIONS:
        return STAGE_EVIDENCE_OBLIGATIONS[stage]
    return f"evidence_for_{stage}"


def collect_claim_gaps(report: LogicClaimRuntimeAuditReport) -> list[BaselineGap]:
    """Project claim-audit gaps into the join gap surface."""

    gaps: list[BaselineGap] = []
    seen: set[str] = set()
    for claim in report.claims:
        for gap in claim.gaps:
            if gap.gap_id in seen:
                raise BaselineV2Error(
                    f"conflicting claims: duplicate claim gap_id {gap.gap_id!r}"
                )
            seen.add(gap.gap_id)
            owner = gap.owner or claim.owner or CLAIM_GAP_OWNER
            gaps.append(
                BaselineGap(
                    gap_id=gap.gap_id,
                    source=GapSource.CLAIM_AUDIT,
                    owner=owner,
                    evidence_obligation=_obligation_for_stage(gap.stage.value),
                    subject_id=gap.claim_id,
                    stage=gap.stage.value,
                    detail=gap.detail or gap.kind.value,
                )
            )
    return gaps


def collect_boundary_gaps(report: Mapping[str, Any]) -> list[BaselineGap]:
    """Classify raw-boundary reachable gaps with unique owners."""

    boundaries = report.get("boundaries") or ()
    if not isinstance(boundaries, Sequence) or isinstance(
        boundaries, (str, bytes, bytearray)
    ):
        raise BaselineV2Error("raw boundary inventory boundaries must be a sequence")

    gaps: list[BaselineGap] = []
    seen: set[str] = set()
    for row in boundaries:
        if not isinstance(row, Mapping):
            raise BaselineV2Error("raw boundary rows must be mappings")
        boundary_id = str(row.get("boundary_id") or "")
        if not boundary_id:
            raise BaselineV2Error("raw boundary missing boundary_id")
        kind = str(row.get("kind") or "")
        disposition = str(row.get("disposition") or "")
        executable = bool(row.get("executable"))
        gates = row.get("gates_crossed") or ()
        if not isinstance(gates, Sequence) or isinstance(gates, (str, bytes, bytearray)):
            raise BaselineV2Error(
                f"boundary {boundary_id!r} gates_crossed must be a sequence"
            )

        # Only reachable/executable classified gaps become work; silent bypass
        # is a hard fail handled elsewhere.
        if disposition == "silent_bypass":
            raise BaselineV2Error(
                f"raw boundary silent parser bypass is not joinable: {boundary_id!r}"
            )
        if disposition == "unclassified" and executable:
            raise BaselineV2Error(
                f"unclassified executable raw boundary: {boundary_id!r}"
            )
        if not executable and disposition not in {"known_bypass", "gated"}:
            continue
        if disposition not in {"known_bypass", "gated"}:
            continue

        if kind == "extension_payload":
            owner = EXTENSION_GAP_OWNER
            obligation = "schema_governed_extension_payload"
            stage = "elaborated"
        elif kind == "parser_bypass":
            owner = BOUNDARY_GAP_OWNER
            obligation = "typed_parse_artifact_ingress"
            stage = "parsed"
        elif kind == "target_source":
            owner = BOUNDARY_GAP_OWNER
            obligation = "compiled_or_parsed_target_receipt"
            stage = "compilable"
        elif kind in {"raw_string", "frozen_json"}:
            owner = BOUNDARY_GAP_OWNER
            obligation = "typed_boundary_gate_receipt"
            stage = "parsed" if not gates else "elaborated"
        else:
            owner = BOUNDARY_GAP_OWNER
            obligation = "classified_raw_boundary_closure"
            stage = "declared"

        gap_id = f"gap:boundary:{boundary_id}"
        if gap_id in seen:
            raise BaselineV2Error(f"duplicate boundary gap_id {gap_id!r}")
        seen.add(gap_id)
        gaps.append(
            BaselineGap(
                gap_id=gap_id,
                source=GapSource.RAW_BOUNDARY,
                owner=owner,
                evidence_obligation=obligation,
                subject_id=boundary_id,
                stage=stage,
                detail=str(row.get("notes") or disposition),
            )
        )
    return gaps


def collect_graph_work_gaps(graph: ReachableCapabilityGraph) -> list[BaselineGap]:
    """Project work-eligible reachable routes as owned gaps."""

    gaps: list[BaselineGap] = []
    seen: set[str] = set()
    for route in graph.work_items():
        gap_id = f"gap:route:{route.route_id}"
        if gap_id in seen:
            raise BaselineV2Error(f"duplicate graph gap_id {gap_id!r}")
        seen.add(gap_id)
        stage = route.explanation.lifecycle_stage.value
        if route.unimplemented:
            obligation = "native_or_translated_implementation_evidence"
        elif route.support is SupportStatus.TRANSLATED:
            obligation = "translation_preservation_and_execution_evidence"
        else:
            obligation = _obligation_for_stage(stage)
        gaps.append(
            BaselineGap(
                gap_id=gap_id,
                source=GapSource.REACHABLE_GRAPH,
                owner=GRAPH_WORK_OWNER,
                evidence_obligation=obligation,
                subject_id=route.route_id,
                stage=stage,
                detail=(
                    f"support={route.support.value}; "
                    f"unimplemented={route.unimplemented}"
                ),
            )
        )
    return gaps


def collect_corpus_unknown_gaps(corpus: LogicConformanceCorpus) -> list[BaselineGap]:
    """Surface corpus unknown labels as owned taxonomy gaps."""

    gaps: list[BaselineGap] = []
    for label in corpus.unknown_labels():
        gaps.append(
            BaselineGap(
                gap_id=f"gap:corpus:unknown_label:{label}",
                source=GapSource.CORPUS,
                owner=CORPUS_GAP_OWNER,
                evidence_obligation="canonical_family_label_disposition",
                subject_id=label,
                stage="declared",
                detail="corpus fixture label_disposition=unknown",
            )
        )
    return gaps


def assert_unique_gap_owners(gaps: Sequence[BaselineGap]) -> None:
    """Each gap_id has exactly one owner and a non-empty evidence obligation."""

    by_id: dict[str, BaselineGap] = {}
    for gap in gaps:
        if not gap.owner or not gap.evidence_obligation:
            raise BaselineV2Error(
                f"reachable gap {gap.gap_id!r} missing owner or evidence obligation"
            )
        prior = by_id.get(gap.gap_id)
        if prior is None:
            by_id[gap.gap_id] = gap
            continue
        if prior.owner != gap.owner:
            raise BaselineV2Error(
                f"conflicting claims: gap {gap.gap_id!r} has multiple owners "
                f"{prior.owner!r} and {gap.owner!r}"
            )
        if prior.evidence_obligation != gap.evidence_obligation:
            raise BaselineV2Error(
                f"conflicting claims: gap {gap.gap_id!r} has multiple evidence "
                f"obligations {prior.evidence_obligation!r} and "
                f"{gap.evidence_obligation!r}"
            )


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


def _stage_value(stage: Any) -> str:
    if isinstance(stage, ClaimLifecycleStage):
        return stage.value
    return str(stage)


def detect_claim_conflicts(report: LogicClaimRuntimeAuditReport) -> None:
    """Fail closed on conflicting or conflated claim rows."""

    seen: dict[str, str] = {}
    for claim in report.claims:
        stage = _stage_value(claim.lifecycle_stage)
        prior = seen.get(claim.claim_id)
        if prior is not None and prior != stage:
            raise BaselineV2Error(
                f"conflicting claims: {claim.claim_id!r} has lifecycle "
                f"{prior!r} and {stage!r}"
            )
        seen[claim.claim_id] = stage

        if stage not in LIFECYCLE_STAGES:
            raise BaselineV2Error(
                f"claim {claim.claim_id!r} uses unknown lifecycle stage {stage!r}"
            )

        # Authority is not a lifecycle stage and must not be treated as one.
        ceiling = (
            claim.authority_ceiling.value
            if hasattr(claim.authority_ceiling, "value")
            else str(claim.authority_ceiling)
        )
        if ceiling in LIFECYCLE_STAGES:
            raise BaselineV2Error(
                f"claim {claim.claim_id!r} conflates authority ceiling "
                f"{ceiling!r} with a lifecycle stage"
            )

        # Authority-bearing without executable maturity requires a typed gap.
        try:
            stage_rank = lifecycle_rank(stage)
        except ClaimRuntimeAuditError as exc:
            raise BaselineV2Error(str(exc)) from exc
        if bool(claim.authority_bearing) and stage_rank < lifecycle_rank(
            ClaimLifecycleStage.EXECUTABLE
        ):
            if not claim.gaps:
                raise BaselineV2Error(
                    f"conflicting claims: authority-bearing claim "
                    f"{claim.claim_id!r} lacks executable maturity and gap"
                )

        # Executable claim must not be recorded as merely declared without gap.
        if bool(claim.executable_claim) and stage == ClaimLifecycleStage.DECLARED.value:
            if not claim.gaps:
                raise BaselineV2Error(
                    f"conflicting claims: executable claim {claim.claim_id!r} "
                    "is declared-only without a typed gap"
                )


def detect_cross_artifact_conflicts(
    report: LogicClaimRuntimeAuditReport,
    graph: ReachableCapabilityGraph,
) -> None:
    """Reject lifecycle/authority conflicts between claim audit and graph."""

    # Provider claims that assert independently_validated must have at least
    # one admitted route for that provider; otherwise the claim is free-floating.
    admitted_providers = {route.provider_id for route in graph.routes}
    for claim in report.claims:
        kind_value = (
            claim.kind.value if hasattr(claim.kind, "value") else str(claim.kind)
        )
        if kind_value != "provider":
            continue
        subject = claim.subject if isinstance(claim.subject, Mapping) else {}
        provider_id = str(subject.get("provider_id") or "")
        if not provider_id:
            # Fall back to claim_id suffix "provider:<id>".
            if claim.claim_id.startswith("provider:"):
                provider_id = claim.claim_id.split(":", 1)[1]
        if not provider_id:
            continue
        if (
            _stage_value(claim.lifecycle_stage)
            == ClaimLifecycleStage.INDEPENDENTLY_VALIDATED.value
            and provider_id not in admitted_providers
            and not claim.gaps
        ):
            raise BaselineV2Error(
                f"conflicting claims: provider {provider_id!r} claims "
                "independently_validated without admitted route or gap"
            )


# ---------------------------------------------------------------------------
# Artifact loading / identity
# ---------------------------------------------------------------------------


def _assert_source_identity(
    *,
    label: str,
    program_id: str | None,
    goal_id: str | None,
    task_id: str | None,
    expected_task: str,
) -> None:
    if program_id not in (None, "", PROGRAM_ID):
        raise BaselineV2Error(
            f"{label} source identity drift: program_id expected "
            f"{PROGRAM_ID!r}, got {program_id!r}"
        )
    if goal_id not in (None, "", SOURCE_GOAL_ID):
        raise BaselineV2Error(
            f"{label} source identity drift: goal_id expected "
            f"{SOURCE_GOAL_ID!r}, got {goal_id!r}"
        )
    if task_id not in (None, "", expected_task):
        raise BaselineV2Error(
            f"{label} revision drift: task_id expected "
            f"{expected_task!r}, got {task_id!r}"
        )


def load_claim_artifact(
    path: Path,
    *,
    verify_live: bool,
    datasets_root: Path,
) -> tuple[LogicClaimRuntimeAuditReport, dict[str, Any]]:
    """Load and validate the claim-runtime audit baseline."""

    try:
        sealed = load_audit_baseline(path)
    except ClaimRuntimeAuditError as exc:
        raise BaselineV2Error(
            f"claim_runtime_audit load failure: {exc}"
        ) from exc
    if sealed.interface != LOGIC_CLAIM_RUNTIME_AUDIT_INTERFACE:
        raise BaselineV2Error(
            f"claim_runtime_audit interface drift: {sealed.interface!r}"
        )
    if sealed.schema_version != LOGIC_CLAIM_RUNTIME_AUDIT_REPORT_SCHEMA:
        raise BaselineV2Error(
            f"claim_runtime_audit schema drift: {sealed.schema_version!r}"
        )
    payload = _load_json(path)
    _assert_source_identity(
        label="claim_runtime_audit",
        program_id=str(payload.get("program_id") or sealed.metadata.get("program_id") or ""),
        goal_id=str(payload.get("goal_id") or sealed.metadata.get("goal_id") or ""),
        task_id=str(payload.get("task_id") or sealed.metadata.get("task_id") or ""),
        expected_task=CLAIM_TASK_ID,
    )
    if verify_live:
        try:
            live = ensure_claim_baseline_seal(path, datasets_root=datasets_root)
            assert_audit_acceptance(live)
        except ClaimRuntimeAuditError as exc:
            raise BaselineV2Error(
                "claim_runtime_audit drift against exact live materialization: "
                f"{exc}"
            ) from exc
    return sealed, payload


def load_boundary_artifact(
    path: Path,
    *,
    verify_live: bool,
) -> dict[str, Any]:
    """Load and validate the raw-boundary inventory baseline."""

    try:
        report = load_raw_boundary_inventory(path)
    except RawBoundaryInventoryError as exc:
        raise BaselineV2Error(
            f"raw_boundary_inventory load failure: {exc}"
        ) from exc
    if report.get("interface") != RAW_LOGIC_BOUNDARY_INVENTORY_INTERFACE:
        raise BaselineV2Error(
            f"raw_boundary_inventory interface drift: {report.get('interface')!r}"
        )
    if report.get("schema_version") != RAW_LOGIC_BOUNDARY_INVENTORY_SCHEMA_VERSION:
        raise BaselineV2Error(
            f"raw_boundary_inventory schema drift: {report.get('schema_version')!r}"
        )
    _assert_source_identity(
        label="raw_boundary_inventory",
        program_id=PROGRAM_ID,  # inventory does not embed program_id; bind join identity
        goal_id=str(report.get("goal_id") or ""),
        task_id=str(report.get("task_id") or ""),
        expected_task=BOUNDARY_TASK_ID,
    )
    if report.get("goal_id") != BOUNDARY_GOAL_ID:
        raise BaselineV2Error(
            f"raw_boundary_inventory revision drift: goal_id expected "
            f"{BOUNDARY_GOAL_ID!r}, got {report.get('goal_id')!r}"
        )
    if verify_live:
        live = curated_raw_boundary_inventory()
        if report.get("content_digest") != live.content_digest():
            raise BaselineV2Error(
                "raw_boundary_inventory content_digest disagrees with live curated inventory"
            )
    return report


def load_graph_artifact(
    path: Path,
    *,
    verify_live: bool,
) -> tuple[ReachableCapabilityGraph, dict[str, Any]]:
    """Load and validate the reachable capability graph baseline."""

    payload = _load_json(path)
    if payload.get("interface") != REACHABLE_CAPABILITY_GRAPH_INTERFACE:
        raise BaselineV2Error(
            f"reachable_capability_graph interface drift: {payload.get('interface')!r}"
        )
    if payload.get("schema_version") != REACHABLE_CAPABILITY_GRAPH_SCHEMA:
        raise BaselineV2Error(
            f"reachable_capability_graph schema drift: {payload.get('schema_version')!r}"
        )
    _assert_source_identity(
        label="reachable_capability_graph",
        program_id=str(payload.get("program_id") or ""),
        goal_id=str(payload.get("goal_id") or ""),
        task_id=str(payload.get("task_id") or ""),
        expected_task=GRAPH_TASK_ID,
    )
    try:
        graph = load_graph_baseline(path)
        if verify_live:
            live = build_default_graph()
            assert_graph_acceptance(live)
            if [item.to_dict() for item in graph.routes] != [
                item.to_dict() for item in live.routes
            ]:
                raise BaselineV2Error(
                    "reachable_capability_graph routes drift against live graph"
                )
            if graph.summary() != live.summary():
                raise BaselineV2Error(
                    "reachable_capability_graph summary drift against live graph"
                )
    except ReachableCapabilityGraphError as exc:
        raise BaselineV2Error(
            f"reachable_capability_graph load/drift failure: {exc}"
        ) from exc
    return graph, payload


def load_corpus_artifact(
    path: Path,
    *,
    verify_live: bool,
) -> LogicConformanceCorpus:
    """Load and validate the v2 conformance corpus."""

    try:
        corpus = load_corpus(path)
    except (CorpusError, ValueError) as exc:
        raise BaselineV2Error(
            f"conformance_corpus load failure: {exc}"
        ) from exc
    if corpus.interface != LOGIC_CONFORMANCE_CORPUS_INTERFACE:
        raise BaselineV2Error(
            f"conformance_corpus interface drift: {corpus.interface!r}"
        )
    if corpus.schema_version != LOGIC_CONFORMANCE_CORPUS_SCHEMA_VERSION:
        raise BaselineV2Error(
            f"conformance_corpus schema drift: {corpus.schema_version!r}"
        )
    _assert_source_identity(
        label="conformance_corpus",
        program_id=PROGRAM_ID,
        goal_id=corpus.objective or SOURCE_GOAL_ID,
        task_id=corpus.task or "LFP2-004",
        expected_task="LFP2-004",
    )
    if corpus.objective not in (None, "", SOURCE_GOAL_ID):
        raise BaselineV2Error(
            f"conformance_corpus revision drift: objective expected "
            f"{SOURCE_GOAL_ID!r}, got {corpus.objective!r}"
        )
    if verify_live:
        reloaded = load_corpus(path)
        if reloaded.content_digest() != corpus.content_digest():
            raise BaselineV2Error(
                "conformance_corpus non-deterministic content_digest"
            )
    return corpus


# ---------------------------------------------------------------------------
# Join
# ---------------------------------------------------------------------------


def join_baseline_v2(
    *,
    claim_path: Path | None = None,
    boundary_path: Path | None = None,
    graph_path: Path | None = None,
    corpus_path: Path | None = None,
    datasets_root: Path | None = None,
    verify_live: bool = True,
) -> dict[str, Any]:
    """Join the four Wave-2 baseline artifacts into LogicRuntimeBaseline@2.

    When ``verify_live`` is true (default), sealed reports are checked against
    live re-materialization. Schema, revision, source-identity, and claim
    conflicts fail closed.
    """

    root = (
        Path(datasets_root).resolve()
        if datasets_root is not None
        else default_datasets_repo_root()
    )
    c_path = Path(claim_path) if claim_path else claim_baseline_path(datasets_root=root)
    b_path = (
        Path(boundary_path)
        if boundary_path
        else boundary_baseline_path(root / "ipfs_datasets_py" / "logic")
    )
    g_path = Path(graph_path) if graph_path else graph_baseline_path(datasets_root=root)
    cor_path = Path(corpus_path) if corpus_path else default_manifest_path()

    claim_report, claim_payload = load_claim_artifact(
        c_path, verify_live=verify_live, datasets_root=root
    )
    boundary_report = load_boundary_artifact(b_path, verify_live=verify_live)
    graph, graph_payload = load_graph_artifact(g_path, verify_live=verify_live)
    corpus = load_corpus_artifact(cor_path, verify_live=verify_live)

    detect_claim_conflicts(claim_report)
    detect_cross_artifact_conflicts(claim_report, graph)

    lifecycle = build_capability_lifecycle()
    validate_capability_lifecycle(lifecycle)

    # Graph lifecycle vocabulary must match the published maturity rules.
    graph_stages = list(graph_payload.get("lifecycle_stages") or GRAPH_LIFECYCLE_STAGES)
    if graph_stages != list(LIFECYCLE_STAGES):
        raise BaselineV2Error(
            "reachable graph lifecycle stages disagree with CapabilityLifecycle@1"
        )
    claim_stages = list(claim_payload.get("lifecycle_stages") or LIFECYCLE_STAGES)
    if claim_stages != list(LIFECYCLE_STAGES):
        raise BaselineV2Error(
            "claim audit lifecycle stages disagree with CapabilityLifecycle@1"
        )

    gaps = (
        collect_claim_gaps(claim_report)
        + collect_boundary_gaps(boundary_report)
        + collect_graph_work_gaps(graph)
        + collect_corpus_unknown_gaps(corpus)
    )
    assert_unique_gap_owners(gaps)

    # Source identity seal: all four inputs bind the same program + G010 goal.
    source_identity = {
        "program_id": PROGRAM_ID,
        "goal_id": SOURCE_GOAL_ID,
        "tasks": {
            "claim_runtime_audit": CLAIM_TASK_ID,
            "raw_boundary_inventory": BOUNDARY_TASK_ID,
            "reachable_capability_graph": GRAPH_TASK_ID,
            "conformance_corpus": "LFP2-004",
        },
        "join_task_id": TASK_ID,
        "join_goal_id": GOAL_ID,
        "consistent": True,
    }
    for label, goal, program in (
        ("claim_runtime_audit", CLAIM_GOAL_ID, CLAIM_PROGRAM_ID),
        ("raw_boundary_inventory", BOUNDARY_GOAL_ID, PROGRAM_ID),
        ("reachable_capability_graph", GRAPH_GOAL_ID, GRAPH_PROGRAM_ID),
        ("conformance_corpus", corpus.objective or SOURCE_GOAL_ID, PROGRAM_ID),
    ):
        if goal != SOURCE_GOAL_ID or program != PROGRAM_ID:
            raise BaselineV2Error(
                f"source identity inconsistent for {label}: "
                f"goal={goal!r} program={program!r}"
            )

    claim_digest = claim_payload["content_digest"]
    boundary_digest = boundary_report.get("content_digest")
    graph_digest = graph_payload.get("content_digest") or graph.content_digest()
    corpus_digest = corpus.content_digest()

    artifacts = {
        "claim_runtime_audit": {
            "path": _relative_to_datasets(c_path, root),
            "interface": claim_report.interface,
            "schema_version": claim_report.schema_version,
            "task_id": CLAIM_TASK_ID,
            "goal_id": CLAIM_GOAL_ID,
            "content_digest": claim_digest,
            "claim_count": len(claim_report.claims),
            "gap_count": len(claim_report.gaps),
            "lifecycle_histogram": claim_report.lifecycle_histogram(),
        },
        "raw_boundary_inventory": {
            "path": _relative_to_datasets(b_path, root),
            "interface": boundary_report["interface"],
            "schema_version": boundary_report["schema_version"],
            "task_id": BOUNDARY_TASK_ID,
            "goal_id": BOUNDARY_GOAL_ID,
            "content_digest": boundary_digest,
            "boundary_count": boundary_report.get("boundary_count"),
            "executable_boundary_count": boundary_report.get(
                "executable_boundary_count"
            ),
            "silent_parser_bypass_count": boundary_report.get(
                "silent_parser_bypass_count", 0
            ),
        },
        "reachable_capability_graph": {
            "path": _relative_to_datasets(g_path, root),
            "interface": graph.interface,
            "schema_version": graph.schema_version,
            "task_id": GRAPH_TASK_ID,
            "goal_id": GRAPH_GOAL_ID,
            "content_digest": graph_digest,
            "admitted_count": graph.admitted_count,
            "excluded_count": graph.excluded_count,
            "work_eligible_count": len(graph.work_items()),
            "unsupported_work_eligible_count": graph.summary()[
                "unsupported_work_eligible_count"
            ],
        },
        "conformance_corpus": {
            "path": _relative_to_datasets(cor_path, root),
            "interface": corpus.interface,
            "schema_version": corpus.schema_version,
            "task_id": corpus.task or "LFP2-004",
            "goal_id": corpus.objective or SOURCE_GOAL_ID,
            "content_digest": corpus_digest,
            "fixture_count": len(corpus),
            "corpus_id": corpus.corpus_id,
            "version": corpus.version,
            "unknown_label_count": len(corpus.unknown_labels()),
        },
    }

    gap_dicts = [item.to_dict() for item in sorted(gaps, key=lambda g: g.gap_id)]
    owner_histogram: dict[str, int] = {}
    source_histogram: dict[str, int] = {}
    for item in gaps:
        owner_histogram[item.owner] = owner_histogram.get(item.owner, 0) + 1
        source_histogram[item.source.value] = (
            source_histogram.get(item.source.value, 0) + 1
        )

    receipt: dict[str, Any] = {
        "interface": LOGIC_RUNTIME_BASELINE_INTERFACE,
        "schema_version": LOGIC_RUNTIME_BASELINE_SCHEMA,
        "version": BASELINE_REPORT_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "description": (
            "Joined Wave-2 runtime baseline binding claim-runtime audit, raw "
            "boundary inventory, reachable capability graph, and conformance "
            "corpus. CapabilityLifecycle@1 publishes maturity transitions; "
            "conflicting claims fail closed; every reachable gap has one owner "
            "and one evidence obligation."
        ),
        "materialization": MATERIALIZATION_TARGET,
        "source_identity": source_identity,
        "capability_lifecycle": lifecycle,
        "artifacts": artifacts,
        "gaps": gap_dicts,
        "gap_summary": {
            "gap_count": len(gap_dicts),
            "owner_histogram": dict(sorted(owner_histogram.items())),
            "source_histogram": dict(sorted(source_histogram.items())),
            "unique_owners": sorted(owner_histogram),
            "each_gap_has_one_owner": True,
            "each_gap_has_evidence_obligation": True,
        },
        "acceptance": {
            "conflicting_claims_fail_closed": True,
            "each_reachable_gap_has_one_owner": True,
            "each_reachable_gap_has_evidence_obligation": True,
            "lifecycle_stages_not_conflated": True,
            "authority_distinct_from_lifecycle": True,
            "source_identity_consistent": True,
            "unsupported_cartesian_cells_are_not_work": graph.summary()[
                "unsupported_work_eligible_count"
            ]
            == 0,
        },
        "roots": {
            # Portable identity (never absolute checkout paths).
            "datasets_root": "ipfs_datasets_py",
            "baseline_directory": _relative_to_datasets(
                root / "docs" / "architecture" / "logic" / "logic_parser_v2_baseline",
                root,
            ),
        },
    }
    digest_body = {key: value for key, value in receipt.items() if key != "content_digest"}
    receipt["content_digest"] = _canonical_digest(digest_body)
    return receipt


def build_default_baseline_join(
    *,
    datasets_root: Path | None = None,
    verify_live: bool = True,
) -> dict[str, Any]:
    """Build the sealed LFP2-005 join receipt."""

    return join_baseline_v2(datasets_root=datasets_root, verify_live=verify_live)


def to_baseline_join_seal_dict(
    receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compact sealed baseline: policies + lifecycle + materialization pointer.

    Full gap and artifact digest bodies remain available from
    :func:`join_baseline_v2`. The seal is the durable evidence surface; live
    materialization is the authority for gap rows and digests.
    """

    if receipt is None:
        raise BaselineV2Error(
            "a validated full baseline join receipt is required to build a compact seal"
        )
    if is_compact_baseline_join_seal(receipt):
        raise BaselineV2Error("cannot compact an already compact baseline join seal")
    validate_baseline_join(receipt)

    lifecycle = build_capability_lifecycle()
    validate_capability_lifecycle(lifecycle)
    seal: dict[str, Any] = {
        "interface": LOGIC_RUNTIME_BASELINE_INTERFACE,
        "schema_version": LOGIC_RUNTIME_BASELINE_SCHEMA,
        "version": BASELINE_REPORT_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "description": (
            "Compact Wave-2 runtime baseline seal. Live materialization via "
            f"{MATERIALIZATION_TARGET} is authoritative for artifact digests "
            "and the owned gap surface."
        ),
        "materialization": MATERIALIZATION_TARGET,
        "source_identity": {
            "program_id": PROGRAM_ID,
            "goal_id": SOURCE_GOAL_ID,
            "tasks": {
                "claim_runtime_audit": CLAIM_TASK_ID,
                "raw_boundary_inventory": BOUNDARY_TASK_ID,
                "reachable_capability_graph": GRAPH_TASK_ID,
                "conformance_corpus": "LFP2-004",
            },
            "join_task_id": TASK_ID,
            "join_goal_id": GOAL_ID,
            "consistent": True,
        },
        "capability_lifecycle": lifecycle,
        "artifact_interfaces": {
            "claim_runtime_audit": LOGIC_CLAIM_RUNTIME_AUDIT_INTERFACE,
            "raw_boundary_inventory": RAW_LOGIC_BOUNDARY_INVENTORY_INTERFACE,
            "reachable_capability_graph": REACHABLE_CAPABILITY_GRAPH_INTERFACE,
            "conformance_corpus": LOGIC_CONFORMANCE_CORPUS_INTERFACE,
        },
        "lifecycle_stages": list(LIFECYCLE_STAGES),
        "acceptance": {
            "conflicting_claims_fail_closed": True,
            "each_reachable_gap_has_one_owner": True,
            "each_reachable_gap_has_evidence_obligation": True,
            "lifecycle_stages_not_conflated": True,
            "authority_distinct_from_lifecycle": True,
            "source_identity_consistent": True,
            "unsupported_cartesian_cells_are_not_work": True,
        },
        "roots": {
            "datasets_root": "ipfs_datasets_py",
            "baseline_directory": (
                "docs/architecture/logic/logic_parser_v2_baseline"
            ),
        },
    }
    summary = _require_mapping(receipt.get("gap_summary"), "receipt.gap_summary")
    seal["gap_summary"] = {
        "gap_count": summary.get("gap_count"),
        "owner_histogram": dict(summary.get("owner_histogram") or {}),
        "source_histogram": dict(summary.get("source_histogram") or {}),
        "unique_owners": list(summary.get("unique_owners") or []),
        "each_gap_has_one_owner": True,
        "each_gap_has_evidence_obligation": True,
    }
    seal["joined_content_digest"] = receipt["content_digest"]
    return seal


def is_compact_baseline_join_seal(payload: Mapping[str, Any]) -> bool:
    """Return True when *payload* is a compact materialization seal."""

    return (
        payload.get("materialization") == MATERIALIZATION_TARGET
        and "artifacts" not in payload
        and "gaps" not in payload
    )


def validate_baseline_join(receipt: Mapping[str, Any]) -> None:
    """Fail closed when a join receipt is malformed or hides ownership gaps."""

    payload = _require_mapping(receipt, "receipt")
    if payload.get("interface") != LOGIC_RUNTIME_BASELINE_INTERFACE:
        raise BaselineV2Error(
            f"baseline_join interface drift: {payload.get('interface')!r}"
        )
    if payload.get("schema_version") != LOGIC_RUNTIME_BASELINE_SCHEMA:
        raise BaselineV2Error(
            f"baseline_join schema drift: {payload.get('schema_version')!r}"
        )
    if payload.get("task_id") != TASK_ID:
        raise BaselineV2Error(
            f"baseline_join revision drift: task_id expected {TASK_ID!r}, "
            f"got {payload.get('task_id')!r}"
        )
    if payload.get("goal_id") != GOAL_ID:
        raise BaselineV2Error(
            f"baseline_join revision drift: goal_id expected {GOAL_ID!r}, "
            f"got {payload.get('goal_id')!r}"
        )
    if payload.get("program_id") != PROGRAM_ID:
        raise BaselineV2Error(
            f"baseline_join program_id drift: {payload.get('program_id')!r}"
        )
    if payload.get("version") != BASELINE_REPORT_VERSION:
        raise BaselineV2Error(
            f"baseline_join version drift: {payload.get('version')!r}"
        )

    lifecycle = _require_mapping(
        payload.get("capability_lifecycle"), "receipt.capability_lifecycle"
    )
    validate_capability_lifecycle(lifecycle)

    source = _require_mapping(payload.get("source_identity"), "receipt.source_identity")
    expected_source_identity = {
        "program_id": PROGRAM_ID,
        "goal_id": SOURCE_GOAL_ID,
        "tasks": {
            "claim_runtime_audit": CLAIM_TASK_ID,
            "raw_boundary_inventory": BOUNDARY_TASK_ID,
            "reachable_capability_graph": GRAPH_TASK_ID,
            "conformance_corpus": "LFP2-004",
        },
        "join_task_id": TASK_ID,
        "join_goal_id": GOAL_ID,
        "consistent": True,
    }
    if source != expected_source_identity:
        raise BaselineV2Error("source_identity drifted from the canonical task binding")

    acceptance = _require_mapping(payload.get("acceptance"), "receipt.acceptance")
    acceptance_flags = (
        "conflicting_claims_fail_closed",
        "each_reachable_gap_has_one_owner",
        "each_reachable_gap_has_evidence_obligation",
        "lifecycle_stages_not_conflated",
        "authority_distinct_from_lifecycle",
        "source_identity_consistent",
        "unsupported_cartesian_cells_are_not_work",
    )
    for flag in acceptance_flags:
        if acceptance.get(flag) is not True:
            raise BaselineV2Error(f"acceptance flag {flag!r} must be true")

    # Compact seals omit artifact digests and gap rows; full receipts require them.
    if is_compact_baseline_join_seal(payload):
        if list(payload.get("lifecycle_stages") or ()) != list(LIFECYCLE_STAGES):
            raise BaselineV2Error("compact seal lifecycle_stages vocabulary drift")
        if lifecycle != build_capability_lifecycle():
            raise BaselineV2Error("compact seal capability_lifecycle drift")
        if acceptance != {flag: True for flag in acceptance_flags}:
            raise BaselineV2Error("compact seal acceptance contract drift")

        expected_interfaces = {
            "claim_runtime_audit": LOGIC_CLAIM_RUNTIME_AUDIT_INTERFACE,
            "raw_boundary_inventory": RAW_LOGIC_BOUNDARY_INVENTORY_INTERFACE,
            "reachable_capability_graph": REACHABLE_CAPABILITY_GRAPH_INTERFACE,
            "conformance_corpus": LOGIC_CONFORMANCE_CORPUS_INTERFACE,
        }
        interfaces = _require_mapping(
            payload.get("artifact_interfaces"), "receipt.artifact_interfaces"
        )
        if interfaces != expected_interfaces:
            raise BaselineV2Error("compact seal artifact_interfaces drift")

        expected_roots = {
            "datasets_root": "ipfs_datasets_py",
            "baseline_directory": (
                "docs/architecture/logic/logic_parser_v2_baseline"
            ),
        }
        roots = _require_mapping(payload.get("roots"), "receipt.roots")
        if roots != expected_roots:
            raise BaselineV2Error("compact seal roots drift")

        joined_digest = payload.get("joined_content_digest")
        if not isinstance(joined_digest, str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", joined_digest
        ):
            raise BaselineV2Error(
                "compact seal joined_content_digest must be a bound sha256 digest"
            )

        summary = _require_mapping(payload.get("gap_summary"), "receipt.gap_summary")
        expected_summary_fields = {
            "gap_count",
            "owner_histogram",
            "source_histogram",
            "unique_owners",
            "each_gap_has_one_owner",
            "each_gap_has_evidence_obligation",
        }
        if set(summary) != expected_summary_fields:
            raise BaselineV2Error(
                "compact seal gap_summary must contain the complete bound summary"
            )
        gap_count = summary.get("gap_count")
        if type(gap_count) is not int or gap_count < 0:
            raise BaselineV2Error("compact seal gap_summary.gap_count is invalid")

        histograms: dict[str, dict[str, Any]] = {}
        for field_name in ("owner_histogram", "source_histogram"):
            histogram = _require_mapping(
                summary.get(field_name), f"receipt.gap_summary.{field_name}"
            )
            if any(
                not isinstance(key, str)
                or not key
                or type(count) is not int
                or count < 0
                for key, count in histogram.items()
            ):
                raise BaselineV2Error(
                    f"compact seal gap_summary.{field_name} is invalid"
                )
            if sum(histogram.values()) != gap_count:
                raise BaselineV2Error(
                    f"compact seal gap_summary.{field_name} does not total gap_count"
                )
            histograms[field_name] = histogram

        unique_owners = summary.get("unique_owners")
        if (
            not isinstance(unique_owners, list)
            or any(not isinstance(owner, str) or not owner for owner in unique_owners)
            or unique_owners != sorted(histograms["owner_histogram"])
        ):
            raise BaselineV2Error("compact seal gap_summary.unique_owners is invalid")
        if summary.get("each_gap_has_one_owner") is not True:
            raise BaselineV2Error(
                "compact seal gap_summary.each_gap_has_one_owner must be true"
            )
        if summary.get("each_gap_has_evidence_obligation") is not True:
            raise BaselineV2Error(
                "compact seal gap_summary.each_gap_has_evidence_obligation must be true"
            )
        return

    artifacts = _require_mapping(payload.get("artifacts"), "receipt.artifacts")
    for key in ARTIFACT_KEYS:
        if key not in artifacts:
            raise BaselineV2Error(f"receipt missing artifact {key!r}")
        art = _require_mapping(artifacts[key], f"receipt.artifacts.{key}")
        for field in ("interface", "schema_version", "content_digest", "path", "task_id"):
            if not art.get(field):
                raise BaselineV2Error(
                    f"receipt artifact {key!r} missing required field {field!r}"
                )

    gaps = payload.get("gaps")
    if not isinstance(gaps, Sequence) or isinstance(gaps, (str, bytes, bytearray)):
        raise BaselineV2Error("receipt.gaps must be a sequence")
    seen: set[str] = set()
    for row in gaps:
        if not isinstance(row, Mapping):
            raise BaselineV2Error("gap rows must be mappings")
        gap_id = row.get("gap_id")
        owner = row.get("owner")
        obligation = row.get("evidence_obligation")
        if not gap_id or not owner or not obligation:
            raise BaselineV2Error(
                "each reachable gap must have gap_id, owner, and evidence_obligation"
            )
        if gap_id in seen:
            raise BaselineV2Error(f"duplicate gap_id {gap_id!r}")
        seen.add(str(gap_id))

    body = {key: value for key, value in payload.items() if key != "content_digest"}
    expected = _canonical_digest(body)
    if payload.get("content_digest") != expected:
        raise BaselineV2Error(
            "receipt content_digest disagrees with canonical body "
            f"(digest drift): expected {expected!r}, got "
            f"{payload.get('content_digest')!r}"
        )


def _assert_compact_seal_matches_live(
    payload: Mapping[str, Any], live: Mapping[str, Any]
) -> None:
    """Require a compact seal to equal the seal derived from the live join."""

    expected = to_baseline_join_seal_dict(live)
    if dict(payload) != expected:
        differing_fields = sorted(
            key
            for key in set(payload) | set(expected)
            if payload.get(key) != expected.get(key)
        )
        raise BaselineV2Error(
            "compact baseline join seal drifted from exact live materialization; "
            f"differing fields={differing_fields}"
        )


def default_baseline_join_path(*, datasets_root: str | Path | None = None) -> Path:
    """Resolve the sealed baseline join path."""

    root = (
        Path(datasets_root).resolve()
        if datasets_root is not None
        else default_datasets_repo_root()
    )
    return root / DEFAULT_BASELINE_RELATIVE_PATH


def render_baseline_join_json(receipt: Mapping[str, Any]) -> str:
    """Deterministic JSON rendering with trailing newline."""

    return (
        json.dumps(
            dict(receipt),
            ensure_ascii=True,
            indent=2,
            sort_keys=False,
            allow_nan=False,
        )
        + "\n"
    )


def write_baseline_join(
    receipt: Mapping[str, Any],
    path: str | Path,
    *,
    compact: bool = False,
) -> Path:
    """Atomically write the baseline join receipt (full or compact seal)."""

    if compact:
        body: Mapping[str, Any] = to_baseline_join_seal_dict(receipt)
    else:
        body = receipt
    validate_baseline_join(body)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = render_baseline_join_json(body)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(target)
    return target


def load_baseline_join(
    path: str | Path,
    *,
    datasets_root: str | Path | None = None,
    verify_live: bool = True,
) -> dict[str, Any]:
    """Load and validate a previously written join receipt.

    Compact seals re-materialize through :func:`join_baseline_v2` and validate
    that sealed identity fields still match.
    """

    payload = _load_json(Path(path))
    validate_baseline_join(payload)
    if is_compact_baseline_join_seal(payload):
        root = (
            Path(datasets_root).resolve()
            if datasets_root is not None
            else default_datasets_repo_root()
        )
        live = join_baseline_v2(datasets_root=root, verify_live=verify_live)
        validate_baseline_join(live)
        _assert_compact_seal_matches_live(payload, live)
        return live
    return payload


def ensure_baseline_join_seal(
    path: str | Path | None = None,
    *,
    datasets_root: str | Path | None = None,
    verify_live: bool = True,
) -> dict[str, Any]:
    """Re-materialize the join and verify it matches the sealed baseline."""

    root = (
        Path(datasets_root).resolve()
        if datasets_root is not None
        else default_datasets_repo_root()
    )
    target = (
        Path(path) if path is not None else default_baseline_join_path(datasets_root=root)
    )
    live = join_baseline_v2(datasets_root=root, verify_live=verify_live)
    validate_baseline_join(live)
    if not target.is_file():
        raise BaselineV2Error(f"baseline join missing: {target}")
    payload = _load_json(target)
    validate_baseline_join(payload)
    if is_compact_baseline_join_seal(payload):
        _assert_compact_seal_matches_live(payload, live)
        return live

    sealed = payload
    for key in (
        "interface",
        "schema_version",
        "task_id",
        "goal_id",
        "program_id",
        "version",
    ):
        if sealed.get(key) != live.get(key):
            raise BaselineV2Error(
                f"baseline join field {key!r} drifted from live materialization"
            )
    if sealed.get("content_digest") != live.get("content_digest"):
        raise BaselineV2Error(
            "baseline join content_digest drifted from live materialization"
        )
    if sealed.get("gap_summary") != live.get("gap_summary"):
        raise BaselineV2Error(
            "baseline join gap_summary drifted from live materialization"
        )
    return live


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: write the Wave-2 baseline join receipt."""

    import argparse

    parser = argparse.ArgumentParser(
        description="Materialize LogicRuntimeBaseline@2 join receipt"
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output path (default: docs/architecture/logic/logic_parser_v2_baseline/baseline_join.json)",
    )
    parser.add_argument(
        "--root",
        default="",
        help="Datasets repository root (default: auto-detect)",
    )
    parser.add_argument(
        "--no-verify-live",
        action="store_true",
        help="Skip live re-materialization checks",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Write the full join receipt (default: compact seal)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = Path(args.root).resolve() if args.root else None
    receipt = join_baseline_v2(
        datasets_root=root,
        verify_live=not args.no_verify_live,
    )
    target = (
        Path(args.output)
        if args.output
        else default_baseline_join_path(
            datasets_root=root if root is not None else default_datasets_repo_root()
        )
    )
    write_baseline_join(receipt, target, compact=not args.full)
    summary = receipt["gap_summary"]
    print(
        f"wrote {target} gaps={summary['gap_count']} "
        f"digest={receipt['content_digest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_KEYS",
    "AUTHORITY_AXIS",
    "BASELINE_REPORT_VERSION",
    "BaselineGap",
    "BaselineV2Error",
    "CAPABILITY_LIFECYCLE_INTERFACE",
    "CAPABILITY_LIFECYCLE_SCHEMA",
    "DEFAULT_BASELINE_RELATIVE_PATH",
    "GAP_ROW_SCHEMA",
    "GOAL_ID",
    "GapSource",
    "LIFECYCLE_STAGES",
    "LOGIC_RUNTIME_BASELINE_INTERFACE",
    "LOGIC_RUNTIME_BASELINE_SCHEMA",
    "MATERIALIZATION_TARGET",
    "NON_CONFLATABLE_PAIRS",
    "PROGRAM_ID",
    "SOURCE_GOAL_ID",
    "STAGE_EVIDENCE_OBLIGATIONS",
    "TASK_ID",
    "assert_stages_not_conflated",
    "assert_unique_gap_owners",
    "build_capability_lifecycle",
    "build_default_baseline_join",
    "collect_boundary_gaps",
    "collect_claim_gaps",
    "collect_corpus_unknown_gaps",
    "collect_graph_work_gaps",
    "default_baseline_join_path",
    "detect_claim_conflicts",
    "detect_cross_artifact_conflicts",
    "ensure_baseline_join_seal",
    "is_compact_baseline_join_seal",
    "join_baseline_v2",
    "lifecycle_stage_rank",
    "load_baseline_join",
    "main",
    "render_baseline_join_json",
    "to_baseline_join_seal_dict",
    "validate_baseline_join",
    "validate_capability_lifecycle",
    "write_baseline_join",
]
