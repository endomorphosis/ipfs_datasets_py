"""Semantic diffs and amendment impact analysis for LegalIR artifacts.

The diff engine compares normalized LegalIR snapshots instead of raw source
text.  It tracks legal semantic changes to obligations, plus build dimensions
that can explain why a compiler output changed: source revisions, amendments,
compiler commits, schema versions, and learned-guidance activation state.
Codex TODO projection is deliberately fail-closed and only emits work packets
for changes with verified compiler-impact regression evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final


LEGAL_IR_SEMANTIC_DIFF_SCHEMA_VERSION: Final = "legal-ir-semantic-diff-v1"
LEGAL_IR_SEMANTIC_DIFF_TODO_SCHEMA_VERSION: Final = "legal-ir-semantic-diff-codex-todo-v1"

DEFAULT_SEMANTIC_DIFF_VALIDATION_COMMAND: Final = (
    "/home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python "
    "-m pytest tests/unit/logic/integration/test_legal_ir_semantic_diff.py "
    "tests/unit/logic/integration/test_legal_ir_temporal_authority.py -q"
)


class LegalIRSemanticDiffError(ValueError):
    """Raised when a semantic diff cannot be constructed or validated."""


class LegalIRSemanticChangeKind(str, Enum):
    """Stable semantic classifications emitted by the LegalIR diff engine."""

    OBLIGATION_ADDED = "obligation_added"
    OBLIGATION_REMOVED = "obligation_removed"
    OBLIGATION_NARROWED = "obligation_narrowed"
    OBLIGATION_BROADENED = "obligation_broadened"
    TEMPORALLY_SHIFTED = "temporally_shifted"
    CITATION_CHANGED = "citation_changed"
    AMBIGUITY_CHANGED = "ambiguity_changed"
    PROOF_STATUS_CHANGED = "proof_status_changed"
    SOURCE_REVISION_CHANGED = "source_revision_changed"
    AMENDMENT_CHANGED = "amendment_changed"
    COMPILER_COMMIT_CHANGED = "compiler_commit_changed"
    SCHEMA_VERSION_CHANGED = "schema_version_changed"
    LEARNED_GUIDANCE_CHANGED = "learned_guidance_changed"


class LegalIRSemanticDiffDimension(str, Enum):
    """Version dimensions that can participate in a semantic diff."""

    SOURCE_REVISION = "source_revision"
    AMENDMENT = "amendment"
    COMPILER_COMMIT = "compiler_commit"
    SCHEMA_VERSION = "schema_version"
    LEARNED_GUIDANCE = "learned_guidance"
    OBLIGATION = "obligation"
    TEMPORAL_AUTHORITY = "temporal_authority"
    CITATION = "citation"
    AMBIGUITY = "ambiguity"
    PROOF = "proof"


class LegalIRSemanticImpactLevel(str, Enum):
    """Conservative impact levels for amendment and compiler analysis."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class LegalIRSemanticVersionBinding:
    """Before/after binding for one non-obligation diff dimension."""

    dimension: str
    before: Any = None
    after: Any = None
    changed: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "after": _json_value(self.after),
            "before": _json_value(self.before),
            "changed": bool(self.changed),
            "dimension": self.dimension,
            "metadata": _json_value(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRSemanticVersionBinding":
        return cls(
            dimension=str(data.get("dimension") or ""),
            before=data.get("before"),
            after=data.get("after"),
            changed=bool(data.get("changed")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRSemanticChange:
    """One classified semantic change between two LegalIR snapshots."""

    change_id: str
    kind: str
    target_id: str
    target_type: str = "obligation"
    before: Mapping[str, Any] = field(default_factory=dict)
    after: Mapping[str, Any] = field(default_factory=dict)
    dimensions: tuple[str, ...] = ()
    impacted_obligation_ids: tuple[str, ...] = ()
    impacted_citations: tuple[str, ...] = ()
    amendment_ids: tuple[str, ...] = ()
    source_revision_ids: tuple[str, ...] = ()
    compiler_commits: tuple[str, ...] = ()
    schema_versions: Mapping[str, Any] = field(default_factory=dict)
    learned_guidance_states: Mapping[str, Any] = field(default_factory=dict)
    impact_level: str = LegalIRSemanticImpactLevel.MEDIUM.value
    regression: bool = False
    verified_compiler_impact: bool = False
    evidence: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_SEMANTIC_DIFF_SCHEMA_VERSION

    @property
    def codex_todo_eligible(self) -> bool:
        return bool(self.regression and self.verified_compiler_impact)

    def to_dict(self) -> dict[str, Any]:
        return {
            "after": _json_value(self.after),
            "amendment_ids": list(self.amendment_ids),
            "before": _json_value(self.before),
            "change_id": self.change_id,
            "compiler_commits": list(self.compiler_commits),
            "codex_todo_eligible": self.codex_todo_eligible,
            "dimensions": list(self.dimensions),
            "evidence": _json_value(self.evidence),
            "impact_level": self.impact_level,
            "impacted_citations": list(self.impacted_citations),
            "impacted_obligation_ids": list(self.impacted_obligation_ids),
            "kind": self.kind,
            "learned_guidance_states": _json_value(self.learned_guidance_states),
            "metadata": _json_value(self.metadata),
            "regression": bool(self.regression),
            "schema_version": self.schema_version,
            "schema_versions": _json_value(self.schema_versions),
            "source_revision_ids": list(self.source_revision_ids),
            "target_id": self.target_id,
            "target_type": self.target_type,
            "verified_compiler_impact": bool(self.verified_compiler_impact),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRSemanticChange":
        return cls(
            change_id=str(data.get("change_id") or ""),
            kind=str(data.get("kind") or ""),
            target_id=str(data.get("target_id") or ""),
            target_type=str(data.get("target_type") or "obligation"),
            before=_mapping(data.get("before")),
            after=_mapping(data.get("after")),
            dimensions=tuple(_unique(_strings(data.get("dimensions", ())))),
            impacted_obligation_ids=tuple(
                _unique(_strings(data.get("impacted_obligation_ids", ())))
            ),
            impacted_citations=tuple(_unique(_strings(data.get("impacted_citations", ())))),
            amendment_ids=tuple(_unique(_strings(data.get("amendment_ids", ())))),
            source_revision_ids=tuple(_unique(_strings(data.get("source_revision_ids", ())))),
            compiler_commits=tuple(_unique(_strings(data.get("compiler_commits", ())))),
            schema_versions=_mapping(data.get("schema_versions")),
            learned_guidance_states=_mapping(data.get("learned_guidance_states")),
            impact_level=str(data.get("impact_level") or LegalIRSemanticImpactLevel.MEDIUM.value),
            regression=bool(data.get("regression")),
            verified_compiler_impact=bool(data.get("verified_compiler_impact")),
            evidence=_mapping(data.get("evidence")),
            metadata=_mapping(data.get("metadata")),
            schema_version=str(data.get("schema_version") or LEGAL_IR_SEMANTIC_DIFF_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class LegalIRAmendmentImpact:
    """Summary of semantic effects attributable to one amendment."""

    amendment_id: str
    affected_obligation_ids: tuple[str, ...]
    affected_citations: tuple[str, ...] = ()
    change_ids: tuple[str, ...] = ()
    change_kinds: tuple[str, ...] = ()
    impact_level: str = LegalIRSemanticImpactLevel.MEDIUM.value
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_SEMANTIC_DIFF_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "affected_citations": list(self.affected_citations),
            "affected_obligation_ids": list(self.affected_obligation_ids),
            "amendment_id": self.amendment_id,
            "change_ids": list(self.change_ids),
            "change_kinds": list(self.change_kinds),
            "impact_level": self.impact_level,
            "metadata": _json_value(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRAmendmentImpact":
        return cls(
            amendment_id=str(data.get("amendment_id") or ""),
            affected_obligation_ids=tuple(
                _unique(_strings(data.get("affected_obligation_ids", ())))
            ),
            affected_citations=tuple(_unique(_strings(data.get("affected_citations", ())))),
            change_ids=tuple(_unique(_strings(data.get("change_ids", ())))),
            change_kinds=tuple(_unique(_strings(data.get("change_kinds", ())))),
            impact_level=str(data.get("impact_level") or LegalIRSemanticImpactLevel.MEDIUM.value),
            metadata=_mapping(data.get("metadata")),
            schema_version=str(data.get("schema_version") or LEGAL_IR_SEMANTIC_DIFF_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class LegalIRSemanticDiffCodexTodo:
    """Path-bounded TODO packet for a verified compiler-impact regression."""

    todo_id: str
    change_id: str
    objective: str
    action: str
    target_component: str
    owned_paths: tuple[str, ...]
    validation_commands: tuple[str, ...]
    evidence: Mapping[str, Any]
    rollback_metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_SEMANTIC_DIFF_TODO_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        metadata = {
            "allowed_paths": list(self.owned_paths),
            "change_id": self.change_id,
            "evidence": _json_value(self.evidence),
            "owned_paths": list(self.owned_paths),
            "rollback_metadata": _json_value(self.rollback_metadata),
            "source": "legal_ir_semantic_diff",
            "target_component": self.target_component,
            "validation_commands": list(self.validation_commands),
        }
        return {
            "action": self.action,
            "allowed_paths": list(self.owned_paths),
            "change_id": self.change_id,
            "evidence": _json_value(self.evidence),
            "metadata": metadata,
            "objective": self.objective,
            "owned_paths": list(self.owned_paths),
            "rollback_metadata": _json_value(self.rollback_metadata),
            "schema_version": self.schema_version,
            "target_component": self.target_component,
            "todo_id": self.todo_id,
            "validation_commands": list(self.validation_commands),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRSemanticDiffCodexTodo":
        return cls(
            todo_id=str(data.get("todo_id") or ""),
            change_id=str(data.get("change_id") or ""),
            objective=str(data.get("objective") or ""),
            action=str(data.get("action") or ""),
            target_component=str(data.get("target_component") or ""),
            owned_paths=tuple(_unique(_strings(data.get("owned_paths", ())))),
            validation_commands=tuple(_unique(_strings(data.get("validation_commands", ())))),
            evidence=_mapping(data.get("evidence")),
            rollback_metadata=_mapping(data.get("rollback_metadata")),
            schema_version=str(
                data.get("schema_version") or LEGAL_IR_SEMANTIC_DIFF_TODO_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True)
class LegalIRSemanticDiffReport:
    """Auditable semantic diff receipt for two LegalIR snapshots."""

    diff_id: str
    before_digest: str
    after_digest: str
    changes: tuple[LegalIRSemanticChange, ...]
    amendment_impacts: tuple[LegalIRAmendmentImpact, ...] = ()
    codex_todos: tuple[LegalIRSemanticDiffCodexTodo, ...] = ()
    version_bindings: tuple[LegalIRSemanticVersionBinding, ...] = ()
    summary: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_SEMANTIC_DIFF_SCHEMA_VERSION

    @property
    def changed(self) -> bool:
        return bool(self.changes)

    @property
    def change_kinds(self) -> tuple[str, ...]:
        return tuple(_unique(change.kind for change in self.changes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "after_digest": self.after_digest,
            "amendment_impacts": [item.to_dict() for item in self.amendment_impacts],
            "before_digest": self.before_digest,
            "changed": self.changed,
            "change_kinds": list(self.change_kinds),
            "changes": [item.to_dict() for item in self.changes],
            "codex_todos": [item.to_dict() for item in self.codex_todos],
            "diff_id": self.diff_id,
            "metadata": _json_value(self.metadata),
            "schema_version": self.schema_version,
            "summary": _json_value(self.summary),
            "version_bindings": [item.to_dict() for item in self.version_bindings],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRSemanticDiffReport":
        return cls(
            diff_id=str(data.get("diff_id") or ""),
            before_digest=str(data.get("before_digest") or ""),
            after_digest=str(data.get("after_digest") or ""),
            changes=tuple(
                LegalIRSemanticChange.from_dict(_mapping(item))
                for item in _sequence(data.get("changes"))
            ),
            amendment_impacts=tuple(
                LegalIRAmendmentImpact.from_dict(_mapping(item))
                for item in _sequence(data.get("amendment_impacts"))
            ),
            codex_todos=tuple(
                LegalIRSemanticDiffCodexTodo.from_dict(_mapping(item))
                for item in _sequence(data.get("codex_todos"))
            ),
            version_bindings=tuple(
                LegalIRSemanticVersionBinding.from_dict(_mapping(item))
                for item in _sequence(data.get("version_bindings"))
            ),
            summary=_mapping(data.get("summary")),
            metadata=_mapping(data.get("metadata")),
            schema_version=str(data.get("schema_version") or LEGAL_IR_SEMANTIC_DIFF_SCHEMA_VERSION),
        )


class LegalIRSemanticDiffEngine:
    """Compute semantic diffs between generic LegalIR-shaped artifacts."""

    def diff(
        self,
        before: Any,
        after: Any,
        *,
        compiler_impact_evidence: Any = None,
        metadata: Mapping[str, Any] | None = None,
        include_codex_todos: bool = True,
    ) -> LegalIRSemanticDiffReport:
        before_snapshot = _snapshot(before)
        after_snapshot = _snapshot(after)
        version_bindings = _version_bindings(before_snapshot, after_snapshot)
        context = _diff_context(before_snapshot, after_snapshot, version_bindings)
        evidence_index = _compiler_impact_evidence_index(compiler_impact_evidence)

        changes: list[LegalIRSemanticChange] = []
        changes.extend(_version_changes(version_bindings, context))
        changes.extend(
            _obligation_changes(
                before_snapshot,
                after_snapshot,
                context=context,
                evidence_index=evidence_index,
            )
        )
        changes = sorted(changes, key=lambda item: (item.target_type, item.target_id, item.kind))
        amendment_impacts = _amendment_impacts(changes, before_snapshot, after_snapshot)
        codex_todos = (
            tuple(project_legal_ir_semantic_diff_to_codex_todos(changes))
            if include_codex_todos
            else ()
        )
        before_digest = _stable_hash(before_snapshot["canonical"])
        after_digest = _stable_hash(after_snapshot["canonical"])
        diff_id = "lir-semantic-diff-" + _stable_hash(
            {
                "after_digest": after_digest,
                "before_digest": before_digest,
                "change_ids": [item.change_id for item in changes],
                "schema_version": LEGAL_IR_SEMANTIC_DIFF_SCHEMA_VERSION,
            }
        )[:24]
        summary = _summary(changes, amendment_impacts, codex_todos, version_bindings)
        return LegalIRSemanticDiffReport(
            diff_id=diff_id,
            before_digest=before_digest,
            after_digest=after_digest,
            changes=tuple(changes),
            amendment_impacts=amendment_impacts,
            codex_todos=codex_todos,
            version_bindings=version_bindings,
            summary=summary,
            metadata=dict(metadata or {}),
        )


def compute_legal_ir_semantic_diff(
    before: Any,
    after: Any,
    *,
    compiler_impact_evidence: Any = None,
    metadata: Mapping[str, Any] | None = None,
    include_codex_todos: bool = True,
) -> LegalIRSemanticDiffReport:
    """Return a typed semantic diff report for two LegalIR snapshots."""

    return LegalIRSemanticDiffEngine().diff(
        before,
        after,
        compiler_impact_evidence=compiler_impact_evidence,
        metadata=metadata,
        include_codex_todos=include_codex_todos,
    )


def legal_ir_semantic_diff(
    before: Any,
    after: Any,
    *,
    compiler_impact_evidence: Any = None,
    metadata: Mapping[str, Any] | None = None,
    include_codex_todos: bool = True,
) -> dict[str, Any]:
    """Return a JSON-ready semantic diff report for two LegalIR snapshots."""

    return compute_legal_ir_semantic_diff(
        before,
        after,
        compiler_impact_evidence=compiler_impact_evidence,
        metadata=metadata,
        include_codex_todos=include_codex_todos,
    ).to_dict()


def build_legal_ir_amendment_impact_analysis(
    before: Any,
    after: Any,
    *,
    compiler_impact_evidence: Any = None,
) -> tuple[LegalIRAmendmentImpact, ...]:
    """Return only amendment impact summaries from a semantic diff."""

    return compute_legal_ir_semantic_diff(
        before,
        after,
        compiler_impact_evidence=compiler_impact_evidence,
        include_codex_todos=False,
    ).amendment_impacts


def project_legal_ir_semantic_diff_to_codex_todos(
    semantic_diff_or_changes: LegalIRSemanticDiffReport | Sequence[LegalIRSemanticChange] | Any,
) -> list[LegalIRSemanticDiffCodexTodo]:
    """Project only verified compiler-impact regressions to Codex TODOs."""

    if isinstance(semantic_diff_or_changes, LegalIRSemanticDiffReport):
        changes = semantic_diff_or_changes.changes
    else:
        changes = tuple(
            item
            if isinstance(item, LegalIRSemanticChange)
            else LegalIRSemanticChange.from_dict(_mapping(item))
            for item in _sequence(semantic_diff_or_changes)
        )
    todos = [_codex_todo(change) for change in changes if change.codex_todo_eligible]
    return sorted(todos, key=lambda item: item.todo_id)


def _snapshot(value: Any) -> dict[str, Any]:
    payload = _mapping(value)
    obligations = _obligations(payload)
    amendments = _amendments(payload)
    canonical = {
        "amendments": amendments,
        "compiler_commit": _compiler_commit(payload),
        "learned_guidance": _learned_guidance_state(payload),
        "obligations": obligations,
        "schema_versions": _schema_versions(payload),
        "source_revisions": _source_revisions(payload),
    }
    return {
        "amendments": amendments,
        "canonical": canonical,
        "compiler_commit": canonical["compiler_commit"],
        "learned_guidance": canonical["learned_guidance"],
        "obligations": obligations,
        "raw": payload,
        "schema_versions": canonical["schema_versions"],
        "source_revisions": canonical["source_revisions"],
    }


def _version_bindings(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> tuple[LegalIRSemanticVersionBinding, ...]:
    fields = (
        (
            LegalIRSemanticDiffDimension.SOURCE_REVISION.value,
            before["source_revisions"],
            after["source_revisions"],
        ),
        (LegalIRSemanticDiffDimension.AMENDMENT.value, before["amendments"], after["amendments"]),
        (
            LegalIRSemanticDiffDimension.COMPILER_COMMIT.value,
            before["compiler_commit"],
            after["compiler_commit"],
        ),
        (
            LegalIRSemanticDiffDimension.SCHEMA_VERSION.value,
            before["schema_versions"],
            after["schema_versions"],
        ),
        (
            LegalIRSemanticDiffDimension.LEARNED_GUIDANCE.value,
            before["learned_guidance"],
            after["learned_guidance"],
        ),
    )
    return tuple(
        LegalIRSemanticVersionBinding(
            dimension=dimension,
            before=before_value,
            after=after_value,
            changed=_json_value(before_value) != _json_value(after_value),
        )
        for dimension, before_value, after_value in fields
    )


def _diff_context(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    version_bindings: Sequence[LegalIRSemanticVersionBinding],
) -> dict[str, Any]:
    changed_dimensions = {
        binding.dimension for binding in version_bindings if binding.changed
    }
    return {
        "amendment_ids": _changed_amendment_ids(before["amendments"], after["amendments"]),
        "changed_dimensions": changed_dimensions,
        "compiler_commits": tuple(
            item
            for item in _unique((before["compiler_commit"], after["compiler_commit"]))
            if item
        ),
        "learned_guidance_states": {
            "before": before["learned_guidance"],
            "after": after["learned_guidance"],
        },
        "schema_versions": {
            "before": before["schema_versions"],
            "after": after["schema_versions"],
        },
        "source_revision_ids": _changed_source_revision_ids(
            before["source_revisions"], after["source_revisions"]
        ),
    }


def _version_changes(
    version_bindings: Sequence[LegalIRSemanticVersionBinding],
    context: Mapping[str, Any],
) -> list[LegalIRSemanticChange]:
    kind_by_dimension = {
        LegalIRSemanticDiffDimension.SOURCE_REVISION.value: LegalIRSemanticChangeKind.SOURCE_REVISION_CHANGED.value,
        LegalIRSemanticDiffDimension.AMENDMENT.value: LegalIRSemanticChangeKind.AMENDMENT_CHANGED.value,
        LegalIRSemanticDiffDimension.COMPILER_COMMIT.value: LegalIRSemanticChangeKind.COMPILER_COMMIT_CHANGED.value,
        LegalIRSemanticDiffDimension.SCHEMA_VERSION.value: LegalIRSemanticChangeKind.SCHEMA_VERSION_CHANGED.value,
        LegalIRSemanticDiffDimension.LEARNED_GUIDANCE.value: LegalIRSemanticChangeKind.LEARNED_GUIDANCE_CHANGED.value,
    }
    changes: list[LegalIRSemanticChange] = []
    for binding in version_bindings:
        if not binding.changed:
            continue
        kind = kind_by_dimension[binding.dimension]
        changes.append(
            _change(
                kind=kind,
                target_id=binding.dimension,
                target_type="version_binding",
                before={"value": binding.before},
                after={"value": binding.after},
                dimensions=(binding.dimension,),
                context=context,
                evidence={"version_binding": binding.to_dict()},
                impact_level=LegalIRSemanticImpactLevel.INFO.value,
                regression=False,
                verified_compiler_impact=False,
            )
        )
    return changes


def _obligation_changes(
    before_snapshot: Mapping[str, Any],
    after_snapshot: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> list[LegalIRSemanticChange]:
    before = dict(before_snapshot["obligations"])
    after = dict(after_snapshot["obligations"])
    before_keys = set(before)
    after_keys = set(after)
    changes: list[LegalIRSemanticChange] = []

    for key in sorted(after_keys - before_keys):
        obligation = after[key]
        changes.append(
            _obligation_change(
                kind=LegalIRSemanticChangeKind.OBLIGATION_ADDED.value,
                target_id=key,
                before={},
                after=obligation,
                context=context,
                evidence_index=evidence_index,
                regression=_explicit_regression({}, obligation),
            )
        )
    for key in sorted(before_keys - after_keys):
        obligation = before[key]
        changes.append(
            _obligation_change(
                kind=LegalIRSemanticChangeKind.OBLIGATION_REMOVED.value,
                target_id=key,
                before=obligation,
                after={},
                context=context,
                evidence_index=evidence_index,
                regression=_explicit_regression(obligation, {}),
            )
        )
    for key in sorted(before_keys & after_keys):
        old = before[key]
        new = after[key]
        if _json_value(old) == _json_value(new):
            continue
        changes.extend(
            _changed_obligation_semantics(
                key,
                old,
                new,
                context=context,
                evidence_index=evidence_index,
            )
        )
    return changes


def _changed_obligation_semantics(
    target_id: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> list[LegalIRSemanticChange]:
    changes: list[LegalIRSemanticChange] = []
    narrowed, broadened, scope_evidence = _scope_change(before, after)
    if narrowed:
        changes.append(
            _obligation_change(
                kind=LegalIRSemanticChangeKind.OBLIGATION_NARROWED.value,
                target_id=target_id,
                before=before,
                after=after,
                context=context,
                evidence_index=evidence_index,
                evidence=scope_evidence,
                regression=False,
            )
        )
    if broadened:
        changes.append(
            _obligation_change(
                kind=LegalIRSemanticChangeKind.OBLIGATION_BROADENED.value,
                target_id=target_id,
                before=before,
                after=after,
                context=context,
                evidence_index=evidence_index,
                evidence=scope_evidence,
                regression=_explicit_regression(before, after),
            )
        )
    if _temporal_signature(before) != _temporal_signature(after):
        changes.append(
            _obligation_change(
                kind=LegalIRSemanticChangeKind.TEMPORALLY_SHIFTED.value,
                target_id=target_id,
                before={"temporal": _temporal_signature(before)},
                after={"temporal": _temporal_signature(after)},
                context=context,
                evidence_index=evidence_index,
                dimensions=(LegalIRSemanticDiffDimension.TEMPORAL_AUTHORITY.value,),
                regression=_explicit_regression(before, after),
            )
        )
    if _citation_signature(before) != _citation_signature(after):
        changes.append(
            _obligation_change(
                kind=LegalIRSemanticChangeKind.CITATION_CHANGED.value,
                target_id=target_id,
                before={"citations": _citation_signature(before)},
                after={"citations": _citation_signature(after)},
                context=context,
                evidence_index=evidence_index,
                dimensions=(LegalIRSemanticDiffDimension.CITATION.value,),
                regression=_explicit_regression(before, after),
            )
        )
    if _ambiguity_signature(before) != _ambiguity_signature(after):
        changes.append(
            _obligation_change(
                kind=LegalIRSemanticChangeKind.AMBIGUITY_CHANGED.value,
                target_id=target_id,
                before={"ambiguity": _ambiguity_signature(before)},
                after={"ambiguity": _ambiguity_signature(after)},
                context=context,
                evidence_index=evidence_index,
                dimensions=(LegalIRSemanticDiffDimension.AMBIGUITY.value,),
                regression=_ambiguity_regression(before, after),
            )
        )
    if _proof_signature(before) != _proof_signature(after):
        changes.append(
            _obligation_change(
                kind=LegalIRSemanticChangeKind.PROOF_STATUS_CHANGED.value,
                target_id=target_id,
                before={"proof": _proof_signature(before)},
                after={"proof": _proof_signature(after)},
                context=context,
                evidence_index=evidence_index,
                dimensions=(LegalIRSemanticDiffDimension.PROOF.value,),
                regression=_proof_regression(before, after),
            )
        )
    return changes


def _obligation_change(
    *,
    kind: str,
    target_id: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    context: Mapping[str, Any],
    evidence_index: Mapping[str, Mapping[str, Any]],
    evidence: Mapping[str, Any] | None = None,
    dimensions: Sequence[str] = (),
    regression: bool = False,
) -> LegalIRSemanticChange:
    merged_evidence = dict(evidence or {})
    compiler_evidence = _matching_compiler_evidence(
        evidence_index,
        target_id=target_id,
        kind=kind,
        before=before,
        after=after,
    )
    if compiler_evidence:
        merged_evidence["compiler_impact"] = compiler_evidence
    explicit_verified = _explicit_verified_compiler_impact(before, after) or _truthy(
        compiler_evidence.get("verified")
        or compiler_evidence.get("verified_compiler_impact")
        or compiler_evidence.get("compiler_impact_verified")
    )
    explicit_regression = _explicit_regression(before, after) or _truthy(
        compiler_evidence.get("regression")
        or compiler_evidence.get("compiler_impact_regression")
    )
    final_regression = bool(regression or explicit_regression)
    final_verified = bool(explicit_verified and _compiler_dimension_changed(context))
    if final_verified and compiler_evidence:
        final_regression = final_regression or _truthy(
            compiler_evidence.get("regression")
            or compiler_evidence.get("compiler_impact_regression")
        )
    return _change(
        kind=kind,
        target_id=target_id,
        target_type="obligation",
        before=before,
        after=after,
        dimensions=(
            LegalIRSemanticDiffDimension.OBLIGATION.value,
            *tuple(dimensions),
            *tuple(sorted(context.get("changed_dimensions") or ())),
        ),
        context=context,
        evidence=merged_evidence,
        impacted_obligation_ids=(target_id,),
        impacted_citations=tuple(_unique((*_citations(before), *_citations(after)))),
        amendment_ids=_related_amendment_ids(before, after, context),
        impact_level=_impact_level(kind, final_regression, final_verified),
        regression=final_regression,
        verified_compiler_impact=final_verified,
    )


def _change(
    *,
    kind: str,
    target_id: str,
    target_type: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    dimensions: Sequence[str],
    context: Mapping[str, Any],
    evidence: Mapping[str, Any],
    impacted_obligation_ids: Sequence[str] = (),
    impacted_citations: Sequence[str] = (),
    amendment_ids: Sequence[str] = (),
    impact_level: str = LegalIRSemanticImpactLevel.MEDIUM.value,
    regression: bool = False,
    verified_compiler_impact: bool = False,
) -> LegalIRSemanticChange:
    descriptor = {
        "after": after,
        "before": before,
        "kind": kind,
        "target_id": target_id,
        "target_type": target_type,
    }
    return LegalIRSemanticChange(
        change_id="lir-semantic-change-" + _stable_hash(descriptor)[:24],
        kind=kind,
        target_id=target_id,
        target_type=target_type,
        before=_mapping(before),
        after=_mapping(after),
        dimensions=tuple(_unique(_strings(dimensions))),
        impacted_obligation_ids=tuple(_unique(_strings(impacted_obligation_ids))),
        impacted_citations=tuple(_unique(_strings(impacted_citations))),
        amendment_ids=tuple(_unique(_strings(amendment_ids))),
        source_revision_ids=tuple(context.get("source_revision_ids") or ()),
        compiler_commits=tuple(context.get("compiler_commits") or ()),
        schema_versions=_mapping(context.get("schema_versions")),
        learned_guidance_states=_mapping(context.get("learned_guidance_states")),
        impact_level=impact_level,
        regression=regression,
        verified_compiler_impact=verified_compiler_impact,
        evidence=evidence,
    )


def _amendment_impacts(
    changes: Sequence[LegalIRSemanticChange],
    before_snapshot: Mapping[str, Any],
    after_snapshot: Mapping[str, Any],
) -> tuple[LegalIRAmendmentImpact, ...]:
    amendment_ids = _changed_amendment_ids(before_snapshot["amendments"], after_snapshot["amendments"])
    grouped: dict[str, list[LegalIRSemanticChange]] = {amendment_id: [] for amendment_id in amendment_ids}
    for change in changes:
        ids = change.amendment_ids or tuple(amendment_ids)
        for amendment_id in ids:
            if amendment_id in grouped and change.target_type == "obligation":
                grouped[amendment_id].append(change)
    impacts: list[LegalIRAmendmentImpact] = []
    for amendment_id in sorted(grouped):
        related = grouped[amendment_id]
        amendment = _mapping(after_snapshot["amendments"].get(amendment_id)) or _mapping(
            before_snapshot["amendments"].get(amendment_id)
        )
        obligations = tuple(
            _unique(
                [
                    *_strings(amendment.get("affected_obligation_ids", ())),
                    *_strings(amendment.get("obligation_ids", ())),
                    *[
                        obligation_id
                        for change in related
                        for obligation_id in change.impacted_obligation_ids
                    ],
                ]
            )
        )
        citations = tuple(
            _unique(
                [
                    *_strings(amendment.get("affected_citations", ())),
                    *_strings(amendment.get("citations", ())),
                    *[citation for change in related for citation in change.impacted_citations],
                ]
            )
        )
        impacts.append(
            LegalIRAmendmentImpact(
                amendment_id=amendment_id,
                affected_obligation_ids=obligations,
                affected_citations=citations,
                change_ids=tuple(change.change_id for change in related),
                change_kinds=tuple(_unique(change.kind for change in related)),
                impact_level=_max_impact(change.impact_level for change in related),
                metadata={"amendment": _json_value(amendment)} if amendment else {},
            )
        )
    return tuple(impacts)


def _codex_todo(change: LegalIRSemanticChange) -> LegalIRSemanticDiffCodexTodo:
    evidence = {
        "change_id": change.change_id,
        "change_kind": change.kind,
        "compiler_commits": list(change.compiler_commits),
        "impact_level": change.impact_level,
        "regression": change.regression,
        "schema_versions": _json_value(change.schema_versions),
        "target_id": change.target_id,
        "verified_compiler_impact": change.verified_compiler_impact,
        **_mapping(change.evidence.get("compiler_impact")),
    }
    owned_paths = tuple(
        _unique(
            _strings(
                change.evidence.get("owned_paths")
                or _mapping(change.evidence.get("compiler_impact")).get("owned_paths")
                or _mapping(change.metadata).get("owned_paths")
                or ("ipfs_datasets_py/logic/integration/reasoning",)
            )
        )
    )
    validation_commands = tuple(
        _unique(
            _strings(
                change.evidence.get("validation_commands")
                or _mapping(change.evidence.get("compiler_impact")).get("validation_commands")
                or (DEFAULT_SEMANTIC_DIFF_VALIDATION_COMMAND,)
            )
        )
    )
    descriptor = {
        "change_id": change.change_id,
        "evidence": evidence,
        "owned_paths": owned_paths,
    }
    return LegalIRSemanticDiffCodexTodo(
        todo_id="lir-semantic-diff-codex-todo-" + _stable_hash(descriptor)[:24],
        change_id=change.change_id,
        objective=(
            f"Fix verified LegalIR compiler regression for {change.target_id}: "
            f"{change.kind}"
        ),
        action="repair_compiler_impact_regression",
        target_component=str(
            _mapping(change.evidence.get("compiler_impact")).get("target_component")
            or _mapping(change.after).get("legal_ir_view")
            or _mapping(change.before).get("legal_ir_view")
            or "legal_ir.compiler_analysis"
        ),
        owned_paths=owned_paths,
        validation_commands=validation_commands,
        evidence=evidence,
        rollback_metadata={
            "remove_todo_id": "lir-semantic-diff-codex-todo-" + _stable_hash(descriptor)[:24],
            "source_change_id": change.change_id,
        },
    )


def _summary(
    changes: Sequence[LegalIRSemanticChange],
    amendment_impacts: Sequence[LegalIRAmendmentImpact],
    codex_todos: Sequence[LegalIRSemanticDiffCodexTodo],
    version_bindings: Sequence[LegalIRSemanticVersionBinding],
) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    for change in changes:
        by_kind[change.kind] = by_kind.get(change.kind, 0) + 1
    return {
        "amendment_impact_count": len(amendment_impacts),
        "change_count": len(changes),
        "changes_by_kind": dict(sorted(by_kind.items())),
        "codex_todo_count": len(codex_todos),
        "verified_compiler_regression_count": sum(
            1 for change in changes if change.codex_todo_eligible
        ),
        "version_dimensions_changed": [
            binding.dimension for binding in version_bindings if binding.changed
        ],
    }


def _obligations(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = (
        payload.get("obligations")
        or payload.get("proof_obligations")
        or payload.get("legal_ir_obligations")
        or _mapping(payload.get("modal_ir")).get("obligations")
        or _mapping(payload.get("output_state")).get("obligations")
        or _mapping(payload.get("lowered_views")).get("obligations")
        or ()
    )
    if isinstance(rows, Mapping):
        sequence = []
        for key, value in rows.items():
            row = _mapping(value)
            row.setdefault("obligation_id", str(key))
            sequence.append(row)
    else:
        sequence = [_mapping(item) for item in _sequence(rows)]
    normalized: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(sequence):
        if not row:
            continue
        obligation = _normalize_obligation(row, index)
        normalized[obligation["obligation_id"]] = obligation
    return dict(sorted(normalized.items()))


def _normalize_obligation(row: Mapping[str, Any], index: int) -> dict[str, Any]:
    obligation_id = str(
        row.get("obligation_id")
        or row.get("formula_id")
        or row.get("id")
        or row.get("target_id")
        or ""
    )
    statement = str(row.get("statement") or row.get("text") or row.get("formula") or "")
    canonical = {
        "action": _terms(row.get("action") or row.get("verb") or _mapping(row.get("predicate")).get("name")),
        "ambiguity": _ambiguity_signature(row),
        "citations": _citation_signature(row),
        "conditions": _constraint_terms(row),
        "exceptions": _terms(row.get("exceptions") or row.get("unless")),
        "legal_ir_view": str(row.get("legal_ir_view") or row.get("target_component") or ""),
        "logic_family": str(row.get("logic_family") or row.get("family") or ""),
        "object": _terms(row.get("object") or row.get("objects")),
        "operator": _deontic_operator(row),
        "proof": _proof_signature(row),
        "statement": statement,
        "subject": _terms(row.get("subject") or row.get("subjects") or row.get("actor")),
        "temporal": _temporal_signature(row),
    }
    if not obligation_id:
        obligation_id = "lir-obligation-" + _stable_hash(canonical)[:24]
    metadata = _mapping(row.get("metadata"))
    return {
        "action": canonical["action"],
        "ambiguity": canonical["ambiguity"],
        "amendment_ids": tuple(
            _unique(
                [
                    *_strings(row.get("amendment_ids", ())),
                    *_strings(row.get("amended_by", ())),
                    *_strings(metadata.get("amendment_ids", ())),
                ]
            )
        ),
        "citations": canonical["citations"],
        "conditions": canonical["conditions"],
        "exceptions": canonical["exceptions"],
        "legal_ir_view": canonical["legal_ir_view"],
        "logic_family": canonical["logic_family"],
        "metadata": _json_value(metadata),
        "object": canonical["object"],
        "obligation_id": obligation_id,
        "operator": canonical["operator"],
        "proof": canonical["proof"],
        "raw": _json_value(row),
        "source_revision_ids": tuple(
            _unique(
                [
                    *_strings(row.get("source_revision_ids", ())),
                    *_strings(row.get("source_revisions", ())),
                    *_strings(metadata.get("source_revision_ids", ())),
                ]
            )
        ),
        "statement": statement,
        "subject": canonical["subject"],
        "temporal": canonical["temporal"],
    }


def _amendments(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = (
        payload.get("amendments")
        or payload.get("amendment_records")
        or payload.get("temporal_changes")
        or _mapping(payload.get("temporal_authority")).get("changes")
        or _mapping(payload.get("temporal_authority_graph")).get("changes")
        or ()
    )
    if isinstance(rows, Mapping):
        sequence = []
        for key, value in rows.items():
            row = _mapping(value)
            row.setdefault("amendment_id", str(key))
            sequence.append(row)
    else:
        sequence = [_mapping(item) for item in _sequence(rows)]
    normalized: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(sequence):
        if not row:
            continue
        amendment_id = str(
            row.get("amendment_id")
            or row.get("change_id")
            or row.get("id")
            or f"amendment-{index}"
        )
        normalized[amendment_id] = {
            **_json_value(row),
            "amendment_id": amendment_id,
            "affected_obligation_ids": tuple(
                _unique(
                    [
                        *_strings(row.get("affected_obligation_ids", ())),
                        *_strings(row.get("obligation_ids", ())),
                        *_strings(row.get("formula_ids", ())),
                    ]
                )
            ),
            "citations": tuple(
                _unique(
                    [
                        *_strings(row.get("affected_citations", ())),
                        *_strings(row.get("citations", ())),
                        str(row.get("canonical_citation") or ""),
                    ]
                )
            ),
        }
    return dict(sorted(normalized.items()))


def _source_revisions(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = (
        payload.get("source_revisions")
        or payload.get("source_revision")
        or payload.get("source_digests")
        or payload.get("sources")
        or payload.get("source_revision_id")
        or ""
    )
    return _id_map(value, id_fields=("source_revision_id", "revision_id", "source_id", "artifact_id", "id"))


def _schema_versions(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = payload.get("schema_versions") or {}
    if not value and payload.get("schema_version"):
        value = {"artifact": payload.get("schema_version")}
    return _json_value(_mapping(value))


def _learned_guidance_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = (
        payload.get("learned_guidance")
        or payload.get("learned_guidance_state")
        or payload.get("guidance_activation")
        or payload.get("learned_guidance_activation")
        or {}
    )
    if isinstance(value, bool):
        return {"active": value}
    return _json_value(_mapping(value))


def _compiler_commit(payload: Mapping[str, Any]) -> str:
    return str(
        payload.get("compiler_commit")
        or payload.get("commit")
        or _mapping(payload.get("build_manifest")).get("compiler_commit")
        or ""
    )


def _id_map(value: Any, *, id_fields: Sequence[str]) -> dict[str, Any]:
    if isinstance(value, str):
        return {value: value} if value else {}
    if isinstance(value, Mapping):
        if any(field in value for field in id_fields):
            item_id = next((str(value.get(field) or "") for field in id_fields if value.get(field)), "")
            return {item_id: _json_value(value)} if item_id else _json_value(dict(value))
        return {str(key): _json_value(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    rows = [_mapping(item) for item in _sequence(value)]
    mapped: dict[str, Any] = {}
    for index, row in enumerate(rows):
        if not row:
            continue
        item_id = next((str(row.get(field) or "") for field in id_fields if row.get(field)), "")
        mapped[item_id or f"item-{index}"] = _json_value(row)
    return dict(sorted(mapped.items()))


def _scope_change(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[bool, bool, dict[str, Any]]:
    before_conditions = set(_strings(before.get("conditions", ())))
    after_conditions = set(_strings(after.get("conditions", ())))
    before_exceptions = set(_strings(before.get("exceptions", ())))
    after_exceptions = set(_strings(after.get("exceptions", ())))
    before_subjects = set(_strings(before.get("subject", ())))
    after_subjects = set(_strings(after.get("subject", ())))
    before_objects = set(_strings(before.get("object", ())))
    after_objects = set(_strings(after.get("object", ())))
    before_strength = _operator_strength(before.get("operator"))
    after_strength = _operator_strength(after.get("operator"))

    narrowed = False
    broadened = False
    if after_conditions > before_conditions or after_exceptions > before_exceptions:
        narrowed = True
    if after_conditions < before_conditions or after_exceptions < before_exceptions:
        broadened = True
    if before_subjects and after_subjects:
        if after_subjects < before_subjects:
            narrowed = True
        if after_subjects > before_subjects:
            broadened = True
    if before_objects and after_objects:
        if after_objects < before_objects:
            narrowed = True
        if after_objects > before_objects:
            broadened = True
    if after_strength < before_strength:
        narrowed = True
    if after_strength > before_strength:
        broadened = True

    return narrowed, broadened, {
        "after_conditions": sorted(after_conditions),
        "after_exceptions": sorted(after_exceptions),
        "after_operator_strength": after_strength,
        "after_objects": sorted(after_objects),
        "after_subjects": sorted(after_subjects),
        "before_conditions": sorted(before_conditions),
        "before_exceptions": sorted(before_exceptions),
        "before_operator_strength": before_strength,
        "before_objects": sorted(before_objects),
        "before_subjects": sorted(before_subjects),
    }


def _deontic_operator(row: Mapping[str, Any]) -> str:
    operator = row.get("operator") or row.get("deontic_operator") or row.get("modality")
    if isinstance(operator, Mapping):
        operator = operator.get("symbol") or operator.get("name") or operator.get("value")
    if not operator:
        statement = str(row.get("statement") or row.get("text") or "").lower()
        for candidate in ("shall not", "must not", "may not", "shall", "must", "should", "may"):
            if candidate in statement:
                operator = candidate
                break
    return _atom(operator, fallback="")


def _operator_strength(value: Any) -> int:
    operator = _atom(value, fallback="")
    strengths = {
        "": 0,
        "may": 1,
        "should": 2,
        "shall": 3,
        "must": 3,
        "required": 3,
        "shall_not": 4,
        "must_not": 4,
        "may_not": 4,
        "prohibited": 4,
    }
    return strengths.get(operator, 2 if operator else 0)


def _constraint_terms(row: Mapping[str, Any]) -> tuple[str, ...]:
    terms = [
        *_strings(row.get("conditions", ())),
        *_strings(row.get("preconditions", ())),
        *_strings(row.get("qualifiers", ())),
        *_strings(row.get("scope", ())),
        *_strings(_mapping(row.get("metadata")).get("conditions", ())),
    ]
    return tuple(_unique(_atom(item, fallback="") for item in terms if _atom(item, fallback="")))


def _temporal_signature(row: Mapping[str, Any]) -> dict[str, Any]:
    temporal = _mapping(row.get("temporal") or row.get("temporal_window") or row.get("validity"))
    raw = _mapping(row.get("raw"))
    if not temporal:
        temporal = _mapping(raw.get("temporal_window") or raw.get("temporal") or raw.get("validity"))
    for key in (
        "effective_date",
        "effective_on",
        "sunset_date",
        "sunsets_on",
        "repeal_date",
        "repealed_on",
        "superseded_date",
        "superseded_on",
        "emergency_expires_on",
    ):
        if row.get(key) and key not in temporal:
            temporal[key] = row[key]
        if raw.get(key) and key not in temporal:
            temporal[key] = raw[key]
    return _json_value(temporal)


def _citation_signature(row: Mapping[str, Any]) -> tuple[str, ...]:
    return _citations(row)


def _citations(row: Mapping[str, Any]) -> tuple[str, ...]:
    raw = _mapping(row.get("raw"))
    terms = [
        *_strings(row.get("citations", ())),
        *_strings(row.get("citation_ids", ())),
        str(row.get("canonical_citation") or ""),
        str(row.get("citation") or ""),
        *_strings(raw.get("citations", ())),
        str(raw.get("canonical_citation") or ""),
        str(raw.get("citation") or ""),
    ]
    return tuple(_unique(_normalize_citation(item) for item in terms if str(item or "").strip()))


def _ambiguity_signature(row: Mapping[str, Any]) -> dict[str, Any]:
    ambiguity = row.get("ambiguity") or row.get("ambiguities") or row.get("ambiguity_report")
    raw = _mapping(row.get("raw"))
    if not ambiguity:
        ambiguity = raw.get("ambiguity") or raw.get("ambiguities") or raw.get("ambiguity_report")
    if isinstance(ambiguity, Mapping):
        return _json_value(ambiguity)
    rows = [_mapping(item) for item in _sequence(ambiguity)]
    if rows:
        return {
            "items": _json_value(rows),
            "unresolved_count": sum(
                1
                for item in rows
                if str(item.get("status") or item.get("route") or "").lower()
                in {"unresolved", "review_required", "blocked_from_proof"}
            ),
        }
    status = str(row.get("ambiguity_status") or raw.get("ambiguity_status") or "")
    return {"status": status} if status else {}


def _proof_signature(row: Mapping[str, Any]) -> dict[str, Any]:
    proof = row.get("proof") or row.get("proof_status") or row.get("route_statuses")
    raw = _mapping(row.get("raw"))
    if not proof:
        proof = raw.get("proof") or raw.get("proof_status") or raw.get("route_statuses")
    if isinstance(proof, str):
        return {"status": _atom(proof)}
    if isinstance(proof, Mapping):
        normalized = _json_value(proof)
        if "status" not in normalized:
            for key in ("proof_status", "trust_status", "route_status"):
                if key in normalized:
                    normalized["status"] = _atom(normalized[key])
                    break
        return normalized
    if proof:
        return {"value": _json_value(proof)}
    status = row.get("status") or raw.get("status")
    return {"status": _atom(status)} if status else {}


def _proof_regression(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    return _proof_rank(_proof_signature(after)) < _proof_rank(_proof_signature(before))


def _ambiguity_regression(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    return _ambiguity_rank(_ambiguity_signature(after)) > _ambiguity_rank(_ambiguity_signature(before))


def _proof_rank(value: Mapping[str, Any]) -> int:
    text = _atom(
        value.get("status")
        or value.get("trust_status")
        or value.get("route_status")
        or value.get("outcome")
        or " ".join(str(item) for item in value.values()),
        fallback="",
    )
    if any(token in text for token in ("proved", "passed", "trusted", "verified")):
        return 4
    if any(token in text for token in ("attempted", "timeout", "unknown")):
        return 2
    if any(token in text for token in ("failed", "unproved", "disproved", "unsupported", "error")):
        return 1
    return 0 if not text else 2


def _ambiguity_rank(value: Mapping[str, Any]) -> int:
    text = _atom(" ".join(str(item) for item in value.values()), fallback="")
    unresolved = int(value.get("unresolved_count") or 0)
    if any(token in text for token in ("critical", "blocked_from_proof", "review_required")):
        return 4 + unresolved
    if any(token in text for token in ("unresolved", "unsupported", "high")):
        return 3 + unresolved
    if any(token in text for token in ("competing", "medium")):
        return 2 + unresolved
    if any(token in text for token in ("resolved", "low")):
        return 1
    return unresolved


def _explicit_verified_compiler_impact(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    for source in (before, after, _mapping(before.get("metadata")), _mapping(after.get("metadata"))):
        if _truthy(
            source.get("verified_compiler_impact")
            or source.get("compiler_impact_verified")
            or source.get("impact_verified")
            or source.get("verified_regression")
        ):
            return True
    return False


def _explicit_regression(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    for source in (before, after, _mapping(before.get("metadata")), _mapping(after.get("metadata"))):
        if _truthy(
            source.get("regression")
            or source.get("compiler_impact_regression")
            or source.get("verified_regression")
        ):
            return True
    return False


def _compiler_dimension_changed(context: Mapping[str, Any]) -> bool:
    dimensions = set(context.get("changed_dimensions") or ())
    return bool(
        dimensions
        & {
            LegalIRSemanticDiffDimension.COMPILER_COMMIT.value,
            LegalIRSemanticDiffDimension.SCHEMA_VERSION.value,
            LegalIRSemanticDiffDimension.LEARNED_GUIDANCE.value,
        }
    )


def _compiler_impact_evidence_index(value: Any) -> dict[str, dict[str, Any]]:
    rows = []
    if isinstance(value, Mapping):
        explicit = value.get("compiler_impact_evidence") or value.get("evidence")
        if explicit is not None:
            rows = [_mapping(item) for item in _sequence(explicit)]
        elif any(key in value for key in ("target_id", "change_kind", "verified")):
            rows = [_mapping(value)]
        else:
            rows = [_mapping(item) for item in value.values()]
    else:
        rows = [_mapping(item) for item in _sequence(value)]
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row:
            continue
        target = str(row.get("target_id") or row.get("obligation_id") or row.get("change_id") or "*")
        kind = str(row.get("change_kind") or row.get("kind") or "*")
        index[f"{target}|{kind}"] = row
        index.setdefault(f"{target}|*", row)
        index.setdefault(f"*|{kind}", row)
    return index


def _matching_compiler_evidence(
    index: Mapping[str, Mapping[str, Any]],
    *,
    target_id: str,
    kind: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> dict[str, Any]:
    for key in (f"{target_id}|{kind}", f"{target_id}|*", f"*|{kind}", "*|*"):
        if key in index:
            return dict(index[key])
    for source in (_mapping(before.get("metadata")), _mapping(after.get("metadata"))):
        evidence = _mapping(source.get("compiler_impact") or source.get("compiler_impact_evidence"))
        if evidence:
            return evidence
    return {}


def _related_amendment_ids(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[str, ...]:
    explicit = [
        *_strings(before.get("amendment_ids", ())),
        *_strings(after.get("amendment_ids", ())),
    ]
    return tuple(_unique(explicit or _strings(context.get("amendment_ids", ()))))


def _changed_amendment_ids(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[str, ...]:
    ids = []
    for key in sorted(set(before) | set(after)):
        if _json_value(before.get(key)) != _json_value(after.get(key)):
            ids.append(key)
    return tuple(_unique(ids))


def _changed_source_revision_ids(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[str, ...]:
    ids = []
    for key in sorted(set(before) | set(after)):
        if _json_value(before.get(key)) != _json_value(after.get(key)):
            ids.append(key)
    return tuple(_unique(ids))


def _impact_level(kind: str, regression: bool, verified: bool) -> str:
    if regression and verified:
        return LegalIRSemanticImpactLevel.CRITICAL.value
    if kind in {
        LegalIRSemanticChangeKind.OBLIGATION_ADDED.value,
        LegalIRSemanticChangeKind.OBLIGATION_REMOVED.value,
        LegalIRSemanticChangeKind.PROOF_STATUS_CHANGED.value,
    }:
        return LegalIRSemanticImpactLevel.HIGH.value
    if kind in {
        LegalIRSemanticChangeKind.OBLIGATION_NARROWED.value,
        LegalIRSemanticChangeKind.OBLIGATION_BROADENED.value,
        LegalIRSemanticChangeKind.TEMPORALLY_SHIFTED.value,
    }:
        return LegalIRSemanticImpactLevel.MEDIUM.value
    return LegalIRSemanticImpactLevel.LOW.value


def _max_impact(levels: Any) -> str:
    ranks = {
        LegalIRSemanticImpactLevel.INFO.value: 0,
        LegalIRSemanticImpactLevel.LOW.value: 1,
        LegalIRSemanticImpactLevel.MEDIUM.value: 2,
        LegalIRSemanticImpactLevel.HIGH.value: 3,
        LegalIRSemanticImpactLevel.CRITICAL.value: 4,
    }
    values = list(levels)
    if not values:
        return LegalIRSemanticImpactLevel.LOW.value
    return max(values, key=lambda value: ranks.get(str(value), 0))


def _terms(value: Any) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        value = value.values()
    return tuple(_unique(_atom(item, fallback="") for item in _sequence(value) if _atom(item, fallback="")))


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, bytearray)):
        text = value.decode("utf-8", errors="replace") if not isinstance(value, str) else value
        return [text] if text else []
    if isinstance(value, Mapping):
        return [str(key) for key in value.keys()]
    if isinstance(value, Sequence):
        return [str(item) for item in value if str(item)]
    return [str(value)] if str(value) else []


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, bytearray)):
        return [value]
    if isinstance(value, Mapping):
        return list(value.values())
    if isinstance(value, Sequence):
        return list(value)
    return [value]


def _mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        try:
            converted = value.to_dict()
            if isinstance(converted, Mapping):
                return dict(converted)
        except (TypeError, ValueError):
            return {}
    if hasattr(value, "__dict__"):
        return {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return {}


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
            if item is not None
        }
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, Sequence):
        return [_json_value(item) for item in value]
    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        return _json_value(value.to_dict())
    return str(value)


def _stable_json(value: Any) -> str:
    return json.dumps(_json_value(value), ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _unique(values: Any) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        text = str(value or "")
        if text and text not in seen:
            seen[text] = None
    return tuple(seen)


def _atom(value: Any, *, fallback: str = "unknown") -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_.:-]+", "_", text).strip("_")
    return text or fallback


def _normalize_citation(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "verified", "trusted"}
    return bool(value)


__all__ = [
    "DEFAULT_SEMANTIC_DIFF_VALIDATION_COMMAND",
    "LEGAL_IR_SEMANTIC_DIFF_SCHEMA_VERSION",
    "LEGAL_IR_SEMANTIC_DIFF_TODO_SCHEMA_VERSION",
    "LegalIRAmendmentImpact",
    "LegalIRSemanticChange",
    "LegalIRSemanticChangeKind",
    "LegalIRSemanticDiffCodexTodo",
    "LegalIRSemanticDiffDimension",
    "LegalIRSemanticDiffEngine",
    "LegalIRSemanticDiffError",
    "LegalIRSemanticDiffReport",
    "LegalIRSemanticImpactLevel",
    "LegalIRSemanticVersionBinding",
    "build_legal_ir_amendment_impact_analysis",
    "compute_legal_ir_semantic_diff",
    "legal_ir_semantic_diff",
    "project_legal_ir_semantic_diff_to_codex_todos",
]
