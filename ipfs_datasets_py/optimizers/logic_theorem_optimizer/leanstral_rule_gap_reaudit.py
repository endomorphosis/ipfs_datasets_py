"""Re-audit historical Leanstral rule gaps at the current trust boundary.

Historical Leanstral reports are investigation inputs, not labels.  This
module deduplicates them by structural gap identity, preserves every
supporting, rejecting, unsupported, and abstaining report as provenance, and
starts every re-audit from an explicit zero-guidance baseline.

Non-zero guidance is possible only when a *fresh* failure-branch candidate:

* passed the current strict Leanstral candidate sanitizer;
* is bound to current deterministic extraction and schema receipts;
* passed the current candidate-local deterministic checks;
* has a trusted, proved Hammer obligation; and
* satisfies the current native reconstruction policy.

The persisted result intentionally omits candidate text, prompts, source
spans, solver payloads, and free-form historical rule descriptions.  A
candidate is represented only by a content hash and verifier-owned structural
IDs.  Consequently this audit can never turn Leanstral prose into canonical
LegalIR or compiler code.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_hammer import (
    LEGAL_IR_HAMMER_REPORT_SCHEMA_VERSION,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_hammer_translation import (
    LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
)
from ipfs_datasets_py.logic.modal.leanstral import (
    LEANSTRAL_FAILURE_BRANCH_RESPONSE_SCHEMA_VERSION,
    LEANSTRAL_HAMMER_CANDIDATE_SCHEMA_VERSION,
    LegalIRLeanTask,
    sanitize_leanstral_failure_branch_candidates,
)
from ipfs_datasets_py.logic.modal.leanstral_reporting import (
    LEANSTRAL_RULE_GAP_REPORT_SCHEMA_VERSION,
)
from ipfs_datasets_py.logic.modal.leanstral_verifier import (
    LEANSTRAL_HAMMER_VERIFIER_SCHEMA_VERSION,
    LEANSTRAL_VERIFIER_SCHEMA_VERSION,
)


LEANSTRAL_RULE_GAP_REAUDIT_SCHEMA_VERSION = (
    "legal-ir-leanstral-rule-gap-reaudit-v1"
)
LEANSTRAL_RULE_GAP_FRESH_EVIDENCE_SCHEMA_VERSION = (
    "legal-ir-leanstral-rule-gap-current-evidence-v1"
)
LEANSTRAL_RULE_GAP_GUIDANCE_SCHEMA_VERSION = (
    "legal-ir-leanstral-rule-gap-bounded-guidance-v1"
)
LEANSTRAL_DETERMINISTIC_EXTRACTION_RECEIPT_SCHEMA_VERSION = (
    "legal-ir-leanstral-current-extraction-receipt-v1"
)
LEANSTRAL_CANDIDATE_SCHEMA_RECEIPT_VERSION = (
    "legal-ir-leanstral-candidate-schema-receipt-v1"
)

CANONICAL_HISTORICAL_REPORT_RELATIVE_PATHS = (
    "leanstral-local-compact-20260718T075226Z/rule-gaps.json",
    "leanstral-local-compact-racefix-20260718T080542Z/rule-gaps.json",
    "leanstral-local-json-smoke-20260718T073902Z/rule-gaps.json",
    "leanstral-local-normalized-20260718T081318Z/rule-gaps.json",
    "leanstral-local-normalized-fullverify-20260718T081551Z/rule-gaps.json",
    "leanstral-local-normalized-reference-20260718T081524Z/rule-gaps.json",
    "leanstral-local-parse-smoke-20260718T074238Z/rule-gaps.json",
    "leanstral-local-smoke-20260718T072926Z/rule-gaps.json",
    "leanstral-local-smoke-20260718T073126Z/rule-gaps.json",
)
CANONICAL_HISTORICAL_REPORT_COUNT = len(
    CANONICAL_HISTORICAL_REPORT_RELATIVE_PATHS
)
CANONICAL_UNIQUE_GAP_COUNT = 1
CANONICAL_FRAME_LOGIC_COMPONENT = "modal.frame_logic"
CANONICAL_FRAME_LOGIC_FAMILY = "frame_logic"
ZERO_GUIDANCE_ID = "leanstral-rule-gap-zero-guidance-baseline"

_SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_TYPED_ATOM_RE = re.compile(
    r"(?:not\s+)?[A-Za-z_][A-Za-z0-9_.:-]*\s*\([^()\n]*\)"
)
_TYPED_CONNECTOR_RE = re.compile(
    r"\s+(?:and|or|unless|implies|until|before|after)\s+",
    re.IGNORECASE,
)
_FREEFORM_OR_CODE_RE = re.compile(
    r"(?:```|\bby\s+(?:simp|aesop|omega|exact)\b|\btheorem\b|\bdef\s+\w+|"
    r"\bimport\s+\w+|\bclass\s+\w+|\breturn\b|\n)",
    re.IGNORECASE,
)
_REASON_TOKEN_RE = re.compile(r"[^a-z0-9]+")

_HISTORICAL_REPORT_FIELDS = frozenset(
    {
        "accepted_supporting_audit_count",
        "conflicting_audit_count",
        "gaps",
        "max_examples_per_gap",
        "max_gaps",
        "rejected_audits",
        "schema_version",
        "source_audit_count",
    }
)
_HISTORICAL_GAP_FIELDS = frozenset(
    {
        "action",
        "affected_ir_families",
        "conflicting_evidence",
        "gap_id",
        "missing_semantic_rule",
        "normalized_rule_key",
        "priority",
        "status",
        "supporting_evidence",
        "target_component",
        "target_surface",
        "title",
        "validation_set",
    }
)
_HISTORICAL_REJECTION_FIELDS = frozenset(
    {
        "audit_id",
        "classification",
        "proposed_surfaces",
        "reasons",
        "request_id",
        "response_hash",
        "status",
        "verification_outcome",
    }
)
_STRICT_CANDIDATE_FIELDS = frozenset(
    {
        "candidate",
        "compiler_surface",
        "confidence",
        "contract_id",
        "expected_failure_mode",
        "logic_family",
        "premise_hints",
        "proof_obligation_id",
        "proof_obligation_ids",
        "repair_scope",
        "schema_version",
        "source_copy_policy",
        "source_copy_rejected",
        "target_view",
    }
)


class LeanstralRuleGapReauditError(ValueError):
    """Raised when historical or current evidence fails closed."""


def canonical_historical_rule_gap_report_paths(
    reports_root: str | os.PathLike[str],
) -> tuple[Path, ...]:
    """Return the lineage-bound report inventory beneath ``reports_root``."""

    root = Path(reports_root)
    paths = tuple(
        root / relative
        for relative in CANONICAL_HISTORICAL_REPORT_RELATIVE_PATHS
    )
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise LeanstralRuleGapReauditError(
            "canonical historical rule-gap inventory is incomplete: "
            + ", ".join(missing)
        )
    return paths


@dataclass(frozen=True, slots=True)
class LeanstralRuleGapReauditPolicy:
    """Trust and boundedness policy for one re-audit."""

    expected_historical_reports: int | None = None
    expected_unique_gaps: int | None = None
    target_component: str = CANONICAL_FRAME_LOGIC_COMPONENT
    target_family: str = CANONICAL_FRAME_LOGIC_FAMILY
    max_guidance_influence: float = 0.1
    require_native_reconstruction: bool = True
    require_historical_conflict: bool = False
    max_report_bytes: int = 8 * 1024 * 1024

    @classmethod
    def canonical(cls) -> "LeanstralRuleGapReauditPolicy":
        """Return the fail-closed policy for the canonical nine-report audit."""

        return cls(
            expected_historical_reports=CANONICAL_HISTORICAL_REPORT_COUNT,
            expected_unique_gaps=CANONICAL_UNIQUE_GAP_COUNT,
            require_historical_conflict=True,
        )

    def __post_init__(self) -> None:
        if (
            self.expected_historical_reports is not None
            and self.expected_historical_reports < 0
        ):
            raise ValueError("expected_historical_reports must be non-negative")
        if self.expected_unique_gaps is not None and self.expected_unique_gaps < 0:
            raise ValueError("expected_unique_gaps must be non-negative")
        if (
            not math.isfinite(float(self.max_guidance_influence))
            or not 0.0 <= float(self.max_guidance_influence) <= 1.0
        ):
            raise ValueError("max_guidance_influence must be finite and in [0, 1]")
        if self.max_report_bytes <= 0:
            raise ValueError("max_report_bytes must be positive")


@dataclass(frozen=True, slots=True)
class HistoricalRuleGapSource:
    """A validated historical report and its content-addressed identity."""

    source_id: str
    report_sha256: str
    report: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class HistoricalGapIdentity:
    """One structural gap identity recovered from historical decisions."""

    identity_id: str
    target_components: tuple[str, ...]
    affected_ir_families: tuple[str, ...]
    request_ids: tuple[str, ...]
    proof_obligation_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    historical_gap_ids: tuple[str, ...]
    classifications: tuple[str, ...]
    report_sha256s: tuple[str, ...]
    decision_counts: Mapping[str, int]
    conflict: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "affected_ir_families": list(self.affected_ir_families),
            "classifications": list(self.classifications),
            "conflict": bool(self.conflict),
            "decision_counts": dict(sorted(self.decision_counts.items())),
            "evidence_ids": list(self.evidence_ids),
            "historical_gap_ids": list(self.historical_gap_ids),
            "identity_id": self.identity_id,
            "proof_obligation_ids": list(self.proof_obligation_ids),
            "report_sha256s": list(self.report_sha256s),
            "request_ids": list(self.request_ids),
            "target_components": list(self.target_components),
        }


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LeanstralRuleGapReauditError("non-finite numeric evidence")
        return value
    if isinstance(value, Enum):
        return _json_ready(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return _json_ready(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=str)]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    raise LeanstralRuleGapReauditError(
        f"unsupported evidence type: {type(value).__name__}"
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Return strict deterministic JSON for hashing."""

    return json.dumps(
        _json_ready(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def content_sha256(value: Any) -> str:
    """Return a prefixed SHA-256 over canonical JSON."""

    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def _strict_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LeanstralRuleGapReauditError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> Any:
    raise LeanstralRuleGapReauditError(f"non-finite JSON number: {value}")


def _mapping(value: Any, *, label: str) -> dict[str, Any]:
    ready = _json_ready(value)
    if not isinstance(ready, Mapping):
        raise LeanstralRuleGapReauditError(f"{label} must be a JSON object")
    return dict(ready)


def _sequence(value: Any, *, label: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise LeanstralRuleGapReauditError(f"{label} must be a JSON array")
    return list(value)


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, (list, tuple, set, frozenset)) else (value,)
    return tuple(
        sorted(
            {
                str(item).strip()
                for item in values
                if isinstance(item, str) and str(item).strip()
            }
        )
    )


def _strict_fields(
    value: Mapping[str, Any],
    allowed: frozenset[str] | set[str],
    *,
    label: str,
) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise LeanstralRuleGapReauditError(
            f"{label} contains unknown fields: {', '.join(unknown)}"
        )


def _valid_sha256(value: Any) -> bool:
    return bool(_SHA256_RE.fullmatch(str(value or "").strip().lower()))


def _reason_code(value: Any) -> str:
    normalized = _REASON_TOKEN_RE.sub("_", str(value or "").strip().lower()).strip("_")
    return normalized[:120] or "unspecified"


def _source_id(path: Path, digest: str) -> str:
    parent = path.parent.name.strip()
    return f"{parent}/{path.name}" if parent else f"historical-{digest[7:23]}"


def _validate_historical_report(report: Mapping[str, Any], *, label: str) -> None:
    _strict_fields(report, _HISTORICAL_REPORT_FIELDS, label=label)
    if report.get("schema_version") != LEANSTRAL_RULE_GAP_REPORT_SCHEMA_VERSION:
        raise LeanstralRuleGapReauditError(
            f"{label} has unsupported schema_version"
        )
    for count_field in (
        "accepted_supporting_audit_count",
        "conflicting_audit_count",
        "source_audit_count",
    ):
        count = report.get(count_field)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise LeanstralRuleGapReauditError(
                f"{label}.{count_field} must be a non-negative integer"
            )
    gaps = _sequence(report.get("gaps"), label=f"{label}.gaps")
    rejected = _sequence(
        report.get("rejected_audits"), label=f"{label}.rejected_audits"
    )
    for index, raw_gap in enumerate(gaps):
        gap = _mapping(raw_gap, label=f"{label}.gaps[{index}]")
        _strict_fields(gap, _HISTORICAL_GAP_FIELDS, label=f"{label}.gaps[{index}]")
        for evidence_field in ("supporting_evidence", "conflicting_evidence"):
            _sequence(
                gap.get(evidence_field, ()),
                label=f"{label}.gaps[{index}].{evidence_field}",
            )
    for index, raw_rejection in enumerate(rejected):
        rejection = _mapping(
            raw_rejection, label=f"{label}.rejected_audits[{index}]"
        )
        _strict_fields(
            rejection,
            _HISTORICAL_REJECTION_FIELDS,
            label=f"{label}.rejected_audits[{index}]",
        )


def load_historical_rule_gap_report(
    source: str | os.PathLike[str] | Mapping[str, Any] | Any,
    *,
    max_bytes: int = 8 * 1024 * 1024,
) -> HistoricalRuleGapSource:
    """Load one strict historical report without importing its decisions."""

    if isinstance(source, (str, os.PathLike)):
        path = Path(source)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise LeanstralRuleGapReauditError(
                f"cannot stat historical report: {path}"
            ) from exc
        if size > max_bytes:
            raise LeanstralRuleGapReauditError(
                f"historical report exceeds {max_bytes} bytes: {path}"
            )
        try:
            raw_bytes = path.read_bytes()
            report = json.loads(
                raw_bytes,
                object_pairs_hook=_strict_pairs,
                parse_constant=_reject_nonfinite,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LeanstralRuleGapReauditError(
                f"cannot parse historical report: {path}"
            ) from exc
        digest = f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"
        source_id = _source_id(path, digest)
    else:
        report = _json_ready(source)
        digest = content_sha256(report)
        source_id = f"historical-{digest[7:23]}"
    report_map = _mapping(report, label=source_id)
    _validate_historical_report(report_map, label=source_id)
    return HistoricalRuleGapSource(
        source_id=source_id,
        report_sha256=digest,
        report=report_map,
    )


def load_historical_rule_gap_reports(
    sources: Iterable[str | os.PathLike[str] | Mapping[str, Any] | Any],
    *,
    policy: LeanstralRuleGapReauditPolicy | None = None,
) -> tuple[HistoricalRuleGapSource, ...]:
    """Load, content-address, and deterministically order historical reports."""

    selected_policy = policy or LeanstralRuleGapReauditPolicy()
    entries = [
        (
            load_historical_rule_gap_report(
                source, max_bytes=selected_policy.max_report_bytes
            ),
            isinstance(source, (str, os.PathLike)),
        )
        for source in sources
    ]
    entries.sort(key=lambda item: (item[0].source_id, item[0].report_sha256))
    seen: dict[tuple[str, str], int] = {}
    loaded_items: list[HistoricalRuleGapSource] = []
    for item, is_path_source in entries:
        key = (item.source_id, item.report_sha256)
        occurrence = seen.get(key, 0) + 1
        seen[key] = occurrence
        if occurrence > 1:
            if is_path_source:
                raise LeanstralRuleGapReauditError(
                    "duplicate historical report source"
                )
            # Mapping inputs have no path identity.  Preserve repeated
            # no-decision runs as distinct, deterministic corpus members.
            item = HistoricalRuleGapSource(
                source_id=f"{item.source_id}#{occurrence}",
                report_sha256=item.report_sha256,
                report=item.report,
            )
        loaded_items.append(item)
    loaded = tuple(loaded_items)
    if (
        selected_policy.expected_historical_reports is not None
        and len(loaded) != selected_policy.expected_historical_reports
    ):
        raise LeanstralRuleGapReauditError(
            "historical report count mismatch: "
            f"expected {selected_policy.expected_historical_reports}, got {len(loaded)}"
        )
    return loaded


def _surface_components(value: Any) -> tuple[str, ...]:
    components: set[str] = set()
    for raw in value if isinstance(value, (list, tuple)) else ():
        if isinstance(raw, Mapping):
            component = str(raw.get("component") or "").strip()
            if component:
                components.add(component)
    return tuple(sorted(components))


def _safe_evidence_ids(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    values: set[str] = set()
    evidence_id = str(evidence.get("evidence_id") or "").strip()
    if evidence_id:
        values.add(evidence_id)
    metric = evidence.get("metric_attribution")
    if isinstance(metric, Mapping):
        values.update(_strings(metric.get("evidence_ids")))
    examples = evidence.get("examples")
    if isinstance(examples, Sequence) and not isinstance(examples, (str, bytes)):
        for raw in examples:
            if isinstance(raw, Mapping):
                values.update(_strings(raw.get("evidence_id")))
    return tuple(sorted(values))


def _historical_records(
    sources: Sequence[HistoricalRuleGapSource],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    for source in sources:
        report = source.report
        report_decisions: list[str] = []
        report_decision_details: list[dict[str, Any]] = []
        for raw_gap in report.get("gaps", ()):
            gap = dict(raw_gap)
            component = str(
                gap.get("target_component")
                or (
                    gap.get("target_surface", {}).get("component")
                    if isinstance(gap.get("target_surface"), Mapping)
                    else ""
                )
                or ""
            ).strip()
            families = _strings(gap.get("affected_ir_families"))
            for role, field in (
                ("accepted", "supporting_evidence"),
                ("conflicting", "conflicting_evidence"),
            ):
                for raw_evidence in gap.get(field, ()):
                    evidence = dict(raw_evidence) if isinstance(raw_evidence, Mapping) else {}
                    outcome = str(evidence.get("verification_outcome") or role).strip()
                    decision = (
                        "accepted"
                        if role == "accepted" and outcome == "accepted"
                        else _reason_code(outcome or role)
                    )
                    record = {
                        "classifications": _strings(evidence.get("classification")),
                        "decision": decision,
                        "evidence_ids": _safe_evidence_ids(evidence),
                        "families": _strings(evidence.get("affected_ir_families"))
                        or families,
                        "gap_ids": _strings(gap.get("gap_id")),
                        "proof_ids": _strings(evidence.get("proof_obligation_ids")),
                        "report_sha256": source.report_sha256,
                        "request_ids": _strings(evidence.get("request_id")),
                        "response_hashes": _strings(evidence.get("response_hash")),
                        "target_components": _strings(component),
                    }
                    records.append(record)
                    report_decisions.append(decision)
                    report_decision_details.append(
                        {
                            "classification": str(
                                evidence.get("classification") or ""
                            ),
                            "decision": decision,
                            "historical_gap_id": str(gap.get("gap_id") or ""),
                            "reason_codes": [
                                _reason_code(reason)
                                for reason in _strings(evidence.get("reasons"))
                            ],
                            "request_id": str(evidence.get("request_id") or ""),
                            "response_hash": str(
                                evidence.get("response_hash") or ""
                            ),
                            "role": role,
                            "target_component": component,
                        }
                    )
        for raw_rejection in report.get("rejected_audits", ()):
            rejection = dict(raw_rejection)
            outcome = _reason_code(
                rejection.get("verification_outcome")
                or rejection.get("status")
                or "rejected"
            )
            decision = "rejected" if outcome == "rejected" else outcome
            components = _surface_components(rejection.get("proposed_surfaces"))
            record = {
                "classifications": _strings(rejection.get("classification")),
                "decision": decision,
                "evidence_ids": (),
                "families": (),
                "gap_ids": (),
                "proof_ids": (),
                "report_sha256": source.report_sha256,
                "request_ids": _strings(rejection.get("request_id")),
                "response_hashes": _strings(rejection.get("response_hash")),
                "target_components": components,
            }
            records.append(record)
            report_decisions.append(decision)
            report_decision_details.append(
                {
                    "audit_id": str(rejection.get("audit_id") or ""),
                    "classification": str(
                        rejection.get("classification") or ""
                    ),
                    "decision": decision,
                    "reason_codes": [
                        _reason_code(reason)
                        for reason in _strings(rejection.get("reasons"))
                    ],
                    "request_id": str(rejection.get("request_id") or ""),
                    "response_hash": str(rejection.get("response_hash") or ""),
                    "role": "conflicting",
                    "target_components": list(components),
                }
            )
        if not report_decisions:
            report_decisions.append("abstained")
            report_decision_details.append(
                {
                    "decision": "abstained",
                    "reason_codes": ["no_historical_decision_records"],
                    "role": "abstention",
                }
            )
        provenance.append(
            {
                "decision_counts": {
                    decision: report_decisions.count(decision)
                    for decision in sorted(set(report_decisions))
                },
                "decisions": report_decision_details,
                "report_sha256": source.report_sha256,
                "source_audit_count": int(report.get("source_audit_count") or 0),
                "source_id": source.source_id,
                "status": (
                    "abstained"
                    if report_decisions == ["abstained"]
                    else "historical_evidence_only"
                ),
            }
        )
    return records, provenance


def _record_tokens(record: Mapping[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for prefix, field in (
        ("request", "request_ids"),
        ("obligation", "proof_ids"),
        ("evidence", "evidence_ids"),
        ("gap", "gap_ids"),
    ):
        tokens.update(f"{prefix}:{value}" for value in record.get(field, ()))
    return tokens


def _structural_fallback(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        tuple(record.get("target_components", ())),
        tuple(record.get("families", ())),
        tuple(record.get("classifications", ())),
    )


def deduplicate_historical_rule_gaps(
    sources: Sequence[HistoricalRuleGapSource]
    | Iterable[str | os.PathLike[str] | Mapping[str, Any] | Any],
    *,
    policy: LeanstralRuleGapReauditPolicy | None = None,
) -> tuple[tuple[HistoricalGapIdentity, ...], tuple[dict[str, Any], ...]]:
    """Collapse report-level decisions into structural gap identities.

    Free-form ``title``, ``missing_semantic_rule``, ``normalized_rule_key``,
    rationale, examples, and drafted text are deliberately excluded from the
    identity.  Request, obligation, evidence, family, and owned-component IDs
    are the only clustering inputs.
    """

    selected_policy = policy or LeanstralRuleGapReauditPolicy()
    source_list = list(sources)
    if source_list and isinstance(source_list[0], HistoricalRuleGapSource):
        loaded = tuple(source_list)  # type: ignore[arg-type]
        if (
            selected_policy.expected_historical_reports is not None
            and len(loaded) != selected_policy.expected_historical_reports
        ):
            raise LeanstralRuleGapReauditError(
                "historical report count mismatch: "
                f"expected {selected_policy.expected_historical_reports}, got {len(loaded)}"
            )
    else:
        loaded = load_historical_rule_gap_reports(source_list, policy=selected_policy)
    records, provenance = _historical_records(loaded)

    parents = list(range(len(records)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parents[max(root_left, root_right)] = min(root_left, root_right)

    token_owners: dict[str, int] = {}
    for index, record in enumerate(records):
        for token in sorted(_record_tokens(record)):
            owner = token_owners.setdefault(token, index)
            union(index, owner)

    # Rejected reports sometimes lost obligation/family fields before they
    # reached the reporter.  Merge such a record only when its owned component
    # and classification identify exactly one already-linked cluster.
    for index, record in enumerate(records):
        if _record_tokens(record):
            continue
        fallback = _structural_fallback(record)
        matches = [
            other
            for other, candidate in enumerate(records)
            if other != index and _structural_fallback(candidate) == fallback
        ]
        roots = {find(other) for other in matches}
        if len(roots) == 1:
            union(index, next(iter(roots)))

    groups: dict[int, list[dict[str, Any]]] = {}
    for index, record in enumerate(records):
        groups.setdefault(find(index), []).append(record)

    identities: list[HistoricalGapIdentity] = []
    for group in groups.values():
        target_components = tuple(
            sorted(
                {
                    value
                    for record in group
                    for value in record["target_components"]
                }
            )
        )
        families = tuple(
            sorted({value for record in group for value in record["families"]})
        )
        request_ids = tuple(
            sorted({value for record in group for value in record["request_ids"]})
        )
        proof_ids = tuple(
            sorted({value for record in group for value in record["proof_ids"]})
        )
        evidence_ids = tuple(
            sorted({value for record in group for value in record["evidence_ids"]})
        )
        gap_ids = tuple(
            sorted({value for record in group for value in record["gap_ids"]})
        )
        classifications = tuple(
            sorted(
                {value for record in group for value in record["classifications"]}
            )
        )
        report_hashes = tuple(
            sorted({str(record["report_sha256"]) for record in group})
        )
        decision_counts = {
            decision: sum(1 for record in group if record["decision"] == decision)
            for decision in sorted({str(record["decision"]) for record in group})
        }
        accepted = decision_counts.get("accepted", 0) > 0
        nonaccepted = sum(
            count
            for decision, count in decision_counts.items()
            if decision != "accepted"
        ) > 0
        conflict = accepted and nonaccepted
        identity_payload = {
            "affected_ir_families": list(families),
            "evidence_ids": list(evidence_ids),
            "proof_obligation_ids": list(proof_ids),
            "request_ids": list(request_ids),
            "target_components": list(target_components),
        }
        identity_id = f"leanstral-gap-identity-{content_sha256(identity_payload)[7:23]}"
        identities.append(
            HistoricalGapIdentity(
                identity_id=identity_id,
                target_components=target_components,
                affected_ir_families=families,
                request_ids=request_ids,
                proof_obligation_ids=proof_ids,
                evidence_ids=evidence_ids,
                historical_gap_ids=gap_ids,
                classifications=classifications,
                report_sha256s=report_hashes,
                decision_counts=decision_counts,
                conflict=conflict,
            )
        )
    identities.sort(key=lambda item: item.identity_id)
    if (
        selected_policy.expected_unique_gaps is not None
        and len(identities) != selected_policy.expected_unique_gaps
    ):
        raise LeanstralRuleGapReauditError(
            "unique historical gap count mismatch: "
            f"expected {selected_policy.expected_unique_gaps}, got {len(identities)}"
        )
    if selected_policy.require_historical_conflict and not any(
        identity.conflict for identity in identities
    ):
        raise LeanstralRuleGapReauditError(
            "canonical historical gap does not preserve accepted/rejected conflict"
        )
    return tuple(identities), tuple(provenance)


def _typed_candidate(candidate: str) -> bool:
    text = str(candidate or "").strip()
    if not text or len(text) > 4096 or _FREEFORM_OR_CODE_RE.search(text):
        return False
    position = 0
    while position < len(text):
        atom = _TYPED_ATOM_RE.match(text, position)
        if atom is None:
            return False
        position = atom.end()
        if position == len(text):
            return True
        connector = _TYPED_CONNECTOR_RE.match(text, position)
        if connector is None:
            return False
        position = connector.end()
    return False


def _candidate_summary(candidate: Mapping[str, Any]) -> dict[str, Any]:
    candidate_text = str(candidate.get("candidate") or "")
    return {
        "candidate_sha256": content_sha256(candidate_text),
        "compiler_surface": str(candidate.get("compiler_surface") or ""),
        "contract_id": str(candidate.get("contract_id") or ""),
        "logic_family": str(candidate.get("logic_family") or ""),
        "premise_hint_ids": list(_strings(candidate.get("premise_hints"))),
        "proof_obligation_id": str(candidate.get("proof_obligation_id") or ""),
        "schema_version": str(candidate.get("schema_version") or ""),
        "target_view": str(candidate.get("target_view") or ""),
    }


def _zero_guidance(reason: str) -> dict[str, Any]:
    return {
        "active": False,
        "candidate_sha256": "",
        "guidance_id": ZERO_GUIDANCE_ID,
        "influence": 0.0,
        "reason": reason,
        "schema_version": LEANSTRAL_RULE_GAP_GUIDANCE_SCHEMA_VERSION,
        "source": "accepted_state_zero_guidance",
    }


def _check_fresh_evidence(
    raw_evidence: Any,
    *,
    identity: HistoricalGapIdentity,
    policy: LeanstralRuleGapReauditPolicy,
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any]]:
    evidence = _mapping(raw_evidence, label="fresh_evidence")
    allowed_evidence_fields = {
        "audit_run_id",
        "candidate_sanitization",
        "deterministic_extraction",
        "fresh",
        "gap_identity_id",
        "hammer_verification",
        "schema_validation",
        "schema_version",
    }
    reasons: list[str] = []
    unknown = sorted(set(evidence) - allowed_evidence_fields)
    if unknown:
        reasons.append("unknown_fresh_evidence_fields")
    if evidence.get("schema_version") != LEANSTRAL_RULE_GAP_FRESH_EVIDENCE_SCHEMA_VERSION:
        reasons.append("unexpected_fresh_evidence_schema_version")
    if evidence.get("fresh") is not True:
        reasons.append("fresh_evidence_required")
    if not str(evidence.get("audit_run_id") or "").strip():
        reasons.append("missing_audit_run_id")
    if evidence.get("gap_identity_id") not in {"", None, identity.identity_id}:
        reasons.append("gap_identity_mismatch")

    sanitization = (
        dict(evidence.get("candidate_sanitization"))
        if isinstance(evidence.get("candidate_sanitization"), Mapping)
        else {}
    )
    if sanitization.get("accepted") is not True:
        reasons.append("candidate_sanitization_rejected")
    if sanitization.get("schema_version") != LEANSTRAL_FAILURE_BRANCH_RESPONSE_SCHEMA_VERSION:
        reasons.append("unexpected_sanitizer_schema_version")
    candidates = sanitization.get("candidates")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        candidates = []
    if len(candidates) != 1:
        reasons.append("exactly_one_sanitized_candidate_required")
        candidate: dict[str, Any] = {}
    elif not isinstance(candidates[0], Mapping):
        reasons.append("sanitized_candidate_must_be_object")
        candidate = {}
    else:
        candidate = dict(candidates[0])
    if candidate:
        if set(candidate) != _STRICT_CANDIDATE_FIELDS:
            reasons.append("candidate_schema_fields_mismatch")
        if candidate.get("schema_version") != LEANSTRAL_HAMMER_CANDIDATE_SCHEMA_VERSION:
            reasons.append("unexpected_candidate_schema_version")
        if not _typed_candidate(str(candidate.get("candidate") or "")):
            reasons.append("candidate_not_typed_logic")
        if candidate.get("repair_scope") != "failed_obligation_subtree":
            reasons.append("invalid_repair_scope")
        if candidate.get("source_copy_policy") != "reject_full_span_copy":
            reasons.append("invalid_source_copy_policy")
        if candidate.get("source_copy_rejected") is not False:
            reasons.append("source_copy_rejected")
        obligation_id = str(candidate.get("proof_obligation_id") or "")
        if _strings(candidate.get("proof_obligation_ids")) != _strings(obligation_id):
            reasons.append("candidate_obligation_scope_mismatch")
    summary = _candidate_summary(candidate) if candidate else {}

    extraction = (
        dict(evidence.get("deterministic_extraction"))
        if isinstance(evidence.get("deterministic_extraction"), Mapping)
        else {}
    )
    if (
        extraction.get("schema_version")
        != LEANSTRAL_DETERMINISTIC_EXTRACTION_RECEIPT_SCHEMA_VERSION
    ):
        reasons.append("unexpected_extraction_receipt_schema_version")
    if extraction.get("accepted") is not True:
        reasons.append("deterministic_extraction_rejected")
    if extraction.get("deterministic") is not True:
        reasons.append("nondeterministic_extraction")
    if extraction.get("current") is not True:
        reasons.append("stale_extraction")
    modal_ir_hash = str(extraction.get("modal_ir_hash") or "")
    if not _valid_sha256(modal_ir_hash):
        reasons.append("missing_current_modal_ir_hash")
    component = str(extraction.get("target_component") or "")
    family = str(extraction.get("target_family") or "")
    if component != policy.target_component:
        reasons.append("unexpected_target_component")
    if family != policy.target_family:
        reasons.append("unexpected_target_family")
    obligations = extraction.get("proof_obligations")
    if not isinstance(obligations, Sequence) or isinstance(obligations, (str, bytes)):
        obligations = []
    obligation_records = [
        dict(item) for item in obligations if isinstance(item, Mapping)
    ]
    obligation_ids = {
        str(item.get("obligation_id") or "") for item in obligation_records
    }
    contract_ids = {str(item.get("contract_id") or "") for item in obligation_records}
    if candidate:
        if summary["proof_obligation_id"] not in obligation_ids:
            reasons.append("candidate_not_bound_to_current_obligation")
        if summary["contract_id"] not in contract_ids:
            reasons.append("candidate_not_bound_to_current_contract")
        if summary["compiler_surface"] != component:
            reasons.append("candidate_component_mismatch")
        if summary["logic_family"] != family:
            reasons.append("candidate_family_mismatch")

    schema_validation = (
        dict(evidence.get("schema_validation"))
        if isinstance(evidence.get("schema_validation"), Mapping)
        else {}
    )
    if (
        schema_validation.get("schema_version")
        != LEANSTRAL_CANDIDATE_SCHEMA_RECEIPT_VERSION
    ):
        reasons.append("unexpected_schema_receipt_version")
    if schema_validation.get("accepted") is not True:
        reasons.append("current_schema_validation_rejected")
    if schema_validation.get("current") is not True:
        reasons.append("stale_candidate_schema")
    if (
        schema_validation.get("candidate_schema_version")
        != LEANSTRAL_HAMMER_CANDIDATE_SCHEMA_VERSION
    ):
        reasons.append("candidate_schema_binding_mismatch")
    if str(schema_validation.get("target_modal_ir_hash") or "") != modal_ir_hash:
        reasons.append("schema_modal_ir_hash_mismatch")

    hammer = (
        dict(evidence.get("hammer_verification"))
        if isinstance(evidence.get("hammer_verification"), Mapping)
        else {}
    )
    if hammer.get("schema_version") != LEANSTRAL_HAMMER_VERIFIER_SCHEMA_VERSION:
        reasons.append("unexpected_hammer_verifier_schema_version")
    if hammer.get("accepted") is not True or hammer.get("trusted") is not True:
        reasons.append("trusted_hammer_proof_required")
    results = hammer.get("candidate_results")
    if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
        results = []
    trusted_results = [
        dict(item)
        for item in results
        if isinstance(item, Mapping)
        and item.get("accepted") is True
        and item.get("trusted") is True
    ]
    if len(trusted_results) != 1:
        reasons.append("exactly_one_trusted_candidate_result_required")
    hammer_report: dict[str, Any] = {}
    proof_receipt_ids: list[str] = []
    if trusted_results:
        trusted_result = trusted_results[0]
        hammer_candidate = trusted_result.get("candidate")
        if isinstance(hammer_candidate, Mapping) and candidate:
            if content_sha256(dict(hammer_candidate)) != content_sha256(candidate):
                reasons.append("hammer_candidate_binding_mismatch")
        checks = trusted_result.get("deterministic_checks")
        if not isinstance(checks, Sequence) or isinstance(checks, (str, bytes)) or not checks:
            reasons.append("missing_current_deterministic_candidate_checks")
        else:
            for raw_check in checks:
                check = dict(raw_check) if isinstance(raw_check, Mapping) else {}
                if (
                    str(check.get("status") or "") != "accepted"
                    or check.get("route_available") is not True
                    or check.get("theorem_valid") is not True
                ):
                    reasons.append("deterministic_candidate_check_failed")
                    break
        hammer_report = (
            dict(trusted_result.get("hammer_report"))
            if isinstance(trusted_result.get("hammer_report"), Mapping)
            else {}
        )
    if hammer_report.get("schema_version") != LEGAL_IR_HAMMER_REPORT_SCHEMA_VERSION:
        reasons.append("unexpected_hammer_report_schema_version")
    obligation_count = hammer_report.get("obligation_count")
    if (
        isinstance(obligation_count, bool)
        or not isinstance(obligation_count, int)
        or obligation_count <= 0
        or hammer_report.get("proved_count") != obligation_count
        or hammer_report.get("trusted_count") != obligation_count
    ):
        reasons.append("hammer_obligations_not_all_trusted")
    artifacts = hammer_report.get("artifacts")
    if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
        artifacts = []
    matching_artifacts = [
        dict(item)
        for item in artifacts
        if isinstance(item, Mapping)
        and str(item.get("obligation_id") or "") == summary.get("proof_obligation_id")
    ]
    if not matching_artifacts:
        reasons.append("missing_matching_hammer_artifact")
    elif any(
        item.get("trusted") is not True
        or item.get("proved") is not True
        or item.get("proof_checked") is not True
        for item in matching_artifacts
    ):
        reasons.append("hammer_artifact_not_trusted_and_proof_checked")

    receipts = hammer_report.get("reconstruction_receipts")
    if not isinstance(receipts, Sequence) or isinstance(receipts, (str, bytes)):
        receipts = []
    matching_receipts = [
        dict(item)
        for item in receipts
        if isinstance(item, Mapping)
        and str(item.get("obligation_id") or "") == summary.get("proof_obligation_id")
    ]
    if not matching_receipts:
        reasons.append("missing_reconstruction_receipt")
    for receipt in matching_receipts:
        if (
            receipt.get("schema_version")
            != LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION
        ):
            reasons.append("unexpected_reconstruction_receipt_schema")
        if (
            receipt.get("trusted") is not True
            or receipt.get("trust_status") != "trusted"
            or receipt.get("backend_proved") is not True
        ):
            reasons.append("untrusted_reconstruction_receipt")
        if (
            policy.require_native_reconstruction
            and receipt.get("native_reconstruction_verified") is not True
        ):
            reasons.append("native_reconstruction_required")
        receipt_id = str(receipt.get("receipt_id") or "")
        if receipt_id:
            proof_receipt_ids.append(receipt_id)

    reasons = list(dict.fromkeys(reasons))
    safe_review = {
        "audit_run_id": str(evidence.get("audit_run_id") or ""),
        "candidate_summary": summary,
        "deterministic_extraction": {
            "modal_ir_hash": modal_ir_hash,
            "proof_obligation_count": len(obligation_records),
            "schema_version": str(extraction.get("schema_version") or ""),
            "target_component": component,
            "target_family": family,
        },
        "hammer": {
            "native_reconstruction_required": bool(
                policy.require_native_reconstruction
            ),
            "obligation_count": int(obligation_count or 0),
            "proof_receipt_ids": sorted(set(proof_receipt_ids)),
            "trusted_candidate_count": len(trusted_results),
        },
        "schema_validation": {
            "candidate_schema_version": str(
                schema_validation.get("candidate_schema_version") or ""
            ),
            "current": schema_validation.get("current") is True,
            "status": (
                "accepted"
                if schema_validation.get("accepted") is True
                else "rejected"
            ),
        },
        "status": "accepted" if not reasons else "rejected",
    }
    if reasons:
        return None, tuple(reasons), safe_review

    guidance_payload = {
        "candidate_sha256": summary["candidate_sha256"],
        "contract_ids": [summary["contract_id"]],
        "proof_obligation_ids": [summary["proof_obligation_id"]],
        "proof_receipt_ids": sorted(set(proof_receipt_ids)),
        "target_component": component,
        "target_family": family,
    }
    guidance = {
        "active": True,
        "candidate_sha256": summary["candidate_sha256"],
        "contract_ids": [summary["contract_id"]],
        "forbidden_uses": [
            "canonical_ir",
            "compiler_code",
            "proof_fact_without_receipt",
            "source_text_target",
        ],
        "guidance_id": (
            f"leanstral-rule-gap-guidance-{content_sha256(guidance_payload)[7:23]}"
        ),
        "influence": float(policy.max_guidance_influence),
        "premise_hint_ids": summary["premise_hint_ids"],
        "proof_obligation_ids": [summary["proof_obligation_id"]],
        "proof_receipt_ids": sorted(set(proof_receipt_ids)),
        "schema_version": LEANSTRAL_RULE_GAP_GUIDANCE_SCHEMA_VERSION,
        "source": "fresh_sanitized_deterministic_trusted_reconstruction",
        "target_component": component,
        "target_family": family,
    }
    return guidance, (), safe_review


def build_current_rule_gap_evidence(
    task: LegalIRLeanTask,
    candidate_response: Any,
    failures: Any,
    hammer_verification: Any,
    *,
    audit_run_id: str,
    gap_identity_id: str = "",
    extraction_verification: Any = None,
) -> dict[str, Any]:
    """Build fresh evidence from current in-process verifier results.

    The strict sanitizer is executed here rather than trusting a caller's
    ``accepted`` flag.  ``hammer_verification`` must be the result of the
    current :class:`LeanstralHammerCandidateVerifier`; it is rechecked again by
    :func:`reaudit_leanstral_rule_gaps`.
    """

    if not str(audit_run_id or "").strip():
        raise LeanstralRuleGapReauditError("audit_run_id is required")
    sanitization = sanitize_leanstral_failure_branch_candidates(
        task, candidate_response, failures
    )
    hammer = _mapping(hammer_verification, label="hammer_verification")
    # The sanitizer already resolved arbitrary Hammer report/failure shapes
    # against the task's deterministic obligations.  Reuse only its accepted
    # obligation IDs instead of interpreting the caller's failure payload a
    # second time.
    failed_ids = {
        obligation_id
        for candidate in sanitization.candidates
        for obligation_id in _strings(candidate.get("proof_obligation_ids"))
    }
    proof_obligations: list[dict[str, str]] = []
    for raw in task.proof_obligations:
        if not isinstance(raw, Mapping):
            continue
        obligation_id = str(raw.get("obligation_id") or "")
        if obligation_id not in failed_ids:
            continue
        metadata = raw.get("metadata")
        contract_id = (
            str(metadata.get("contract_id") or "")
            if isinstance(metadata, Mapping)
            else ""
        )
        proof_obligations.append(
            {
                "contract_id": contract_id,
                "logic_family": str(raw.get("logic_family") or ""),
                "obligation_id": obligation_id,
                "target_view": str(raw.get("legal_ir_view") or ""),
            }
        )

    verification = (
        _mapping(extraction_verification, label="extraction_verification")
        if extraction_verification is not None
        else {}
    )
    extraction_accepted = True
    if verification:
        extraction_accepted = (
            verification.get("schema_version") == LEANSTRAL_VERIFIER_SCHEMA_VERSION
            and verification.get("accepted") is True
            and all(
                isinstance(item, Mapping) and item.get("accepted") is True
                for item in verification.get("compiler_checks", ())
            )
        )
    candidate = (
        dict(sanitization.candidates[0])
        if sanitization.accepted and len(sanitization.candidates) == 1
        else {}
    )
    target_components = {
        item["target_view"] for item in proof_obligations if item["target_view"]
    }
    target_families = {
        item["logic_family"] for item in proof_obligations if item["logic_family"]
    }
    target_component = (
        next(iter(target_components))
        if len(target_components) == 1
        else ""
    )
    target_family = (
        next(iter(target_families))
        if len(target_families) == 1
        else ""
    )
    return {
        "audit_run_id": str(audit_run_id),
        "candidate_sanitization": sanitization.to_dict(),
        "deterministic_extraction": {
            "accepted": bool(extraction_accepted and task.modal_ir_hash),
            "current": True,
            "deterministic": True,
            "modal_ir_hash": str(task.modal_ir_hash),
            "proof_obligations": proof_obligations,
            "schema_version": LEANSTRAL_DETERMINISTIC_EXTRACTION_RECEIPT_SCHEMA_VERSION,
            "target_component": target_component,
            "target_family": target_family,
        },
        "fresh": True,
        "gap_identity_id": str(gap_identity_id),
        "hammer_verification": hammer,
        "schema_validation": {
            "accepted": bool(sanitization.accepted),
            "candidate_schema_version": LEANSTRAL_HAMMER_CANDIDATE_SCHEMA_VERSION,
            "current": True,
            "schema_version": LEANSTRAL_CANDIDATE_SCHEMA_RECEIPT_VERSION,
            "target_modal_ir_hash": str(task.modal_ir_hash),
        },
        "schema_version": LEANSTRAL_RULE_GAP_FRESH_EVIDENCE_SCHEMA_VERSION,
    }


def reaudit_leanstral_rule_gaps(
    historical_reports: Iterable[
        str | os.PathLike[str] | Mapping[str, Any] | HistoricalRuleGapSource | Any
    ],
    *,
    fresh_evidence: Any = None,
    policy: LeanstralRuleGapReauditPolicy | None = None,
) -> dict[str, Any]:
    """Deduplicate historical reports and apply the current trust policy."""

    selected_policy = policy or LeanstralRuleGapReauditPolicy()
    raw_sources = list(historical_reports)
    if raw_sources and isinstance(raw_sources[0], HistoricalRuleGapSource):
        sources = tuple(raw_sources)  # type: ignore[assignment]
    else:
        sources = load_historical_rule_gap_reports(
            raw_sources, policy=selected_policy
        )
    identities, provenance = deduplicate_historical_rule_gaps(
        sources, policy=selected_policy
    )
    target_identities = [
        identity
        for identity in identities
        if selected_policy.target_component in identity.target_components
        and (
            not identity.affected_ir_families
            or selected_policy.target_family in identity.affected_ir_families
        )
    ]
    if len(target_identities) != 1:
        raise LeanstralRuleGapReauditError(
            "expected exactly one structurally identified target frame-logic gap, "
            f"got {len(target_identities)}"
        )
    target = target_identities[0]
    baseline = _zero_guidance("fresh_candidate_not_yet_accepted")
    if fresh_evidence is None:
        decision = "abstained"
        reasons = ("fresh_candidate_missing",)
        current_review = {
            "status": "abstained",
            "reason": "fresh_candidate_missing",
        }
        selected_guidance = baseline
    else:
        guidance, reasons, current_review = _check_fresh_evidence(
            fresh_evidence,
            identity=target,
            policy=selected_policy,
        )
        if guidance is None:
            decision = "rejected"
            selected_guidance = _zero_guidance("fresh_candidate_rejected")
        else:
            decision = "accepted"
            selected_guidance = guidance

    report: dict[str, Any] = {
        "authority": {
            "canonical_ir": "current_deterministic_extraction_only",
            "compiler_code": "reviewed_deterministic_implementation_only",
            "free_form_leanstral_is_canonical": False,
            "historical_decisions_are_labels": False,
            "historical_reports": "investigation_evidence_only",
        },
        "baseline_guidance": baseline,
        "current_review": current_review,
        "decision": decision,
        "gap_identities": [identity.to_dict() for identity in identities],
        "historical_conflict_provenance": list(provenance),
        "historical_report_count": len(sources),
        "historical_report_sha256s": sorted(
            source.report_sha256 for source in sources
        ),
        "historical_unique_gap_count": len(identities),
        "reaudit_policy": {
            "max_guidance_influence": float(
                selected_policy.max_guidance_influence
            ),
            "require_native_reconstruction": bool(
                selected_policy.require_native_reconstruction
            ),
            "target_component": selected_policy.target_component,
            "target_family": selected_policy.target_family,
        },
        "reaudit_reasons": list(reasons),
        "schema_version": LEANSTRAL_RULE_GAP_REAUDIT_SCHEMA_VERSION,
        "selected_guidance": selected_guidance,
        "target_gap_identity_id": target.identity_id,
        "zero_guidance_baseline_preserved": True,
    }
    report["report_sha256"] = content_sha256(report)
    return report


def verify_reaudit_report(report: Mapping[str, Any]) -> None:
    """Verify the embedded report digest and the zero-baseline invariant."""

    payload = dict(_mapping(report, label="reaudit_report"))
    expected = str(payload.pop("report_sha256", "") or "")
    if not _valid_sha256(expected) or content_sha256(payload) != expected:
        raise LeanstralRuleGapReauditError("reaudit report digest mismatch")
    if payload.get("schema_version") != LEANSTRAL_RULE_GAP_REAUDIT_SCHEMA_VERSION:
        raise LeanstralRuleGapReauditError("unexpected re-audit report schema")
    baseline = _mapping(payload.get("baseline_guidance"), label="baseline_guidance")
    if (
        baseline.get("guidance_id") != ZERO_GUIDANCE_ID
        or baseline.get("active") is not False
        or baseline.get("influence") != 0.0
    ):
        raise LeanstralRuleGapReauditError("zero-guidance baseline was not preserved")
    selected = _mapping(payload.get("selected_guidance"), label="selected_guidance")
    influence = selected.get("influence")
    if (
        isinstance(influence, bool)
        or not isinstance(influence, (int, float))
        or not math.isfinite(float(influence))
        or not 0.0 <= float(influence) <= 1.0
    ):
        raise LeanstralRuleGapReauditError("invalid selected guidance influence")
    serialized = canonical_json_bytes(payload).decode("ascii")
    for forbidden_field in (
        '"candidate":',
        '"missing_semantic_rule":',
        '"normalized_rule_key":',
        '"python_patch":',
        '"source_text":',
    ):
        if forbidden_field in serialized:
            raise LeanstralRuleGapReauditError(
                f"unsafe free-form field persisted: {forbidden_field}"
            )


def leanstral_rule_gap_reaudit_to_json(report: Mapping[str, Any]) -> str:
    """Serialize a verified re-audit report with stable key ordering."""

    verify_reaudit_report(report)
    return json.dumps(
        _json_ready(report),
        allow_nan=False,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    )


def write_reaudit_report_atomic(
    path: str | os.PathLike[str], report: Mapping[str, Any]
) -> None:
    """Atomically persist a verified, source-free re-audit report."""

    verify_reaudit_report(report)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(leanstral_rule_gap_reaudit_to_json(report))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


# Readable compatibility aliases for callers that use the task's shorter name.
reaudit_rule_gaps = reaudit_leanstral_rule_gaps
write_reaudit_atomic = write_reaudit_report_atomic


__all__ = [
    "CANONICAL_FRAME_LOGIC_COMPONENT",
    "CANONICAL_FRAME_LOGIC_FAMILY",
    "CANONICAL_HISTORICAL_REPORT_COUNT",
    "CANONICAL_HISTORICAL_REPORT_RELATIVE_PATHS",
    "CANONICAL_UNIQUE_GAP_COUNT",
    "HistoricalGapIdentity",
    "HistoricalRuleGapSource",
    "LEANSTRAL_CANDIDATE_SCHEMA_RECEIPT_VERSION",
    "LEANSTRAL_DETERMINISTIC_EXTRACTION_RECEIPT_SCHEMA_VERSION",
    "LEANSTRAL_RULE_GAP_FRESH_EVIDENCE_SCHEMA_VERSION",
    "LEANSTRAL_RULE_GAP_GUIDANCE_SCHEMA_VERSION",
    "LEANSTRAL_RULE_GAP_REAUDIT_SCHEMA_VERSION",
    "LeanstralRuleGapReauditError",
    "LeanstralRuleGapReauditPolicy",
    "ZERO_GUIDANCE_ID",
    "build_current_rule_gap_evidence",
    "canonical_historical_rule_gap_report_paths",
    "canonical_json_bytes",
    "content_sha256",
    "deduplicate_historical_rule_gaps",
    "leanstral_rule_gap_reaudit_to_json",
    "load_historical_rule_gap_report",
    "load_historical_rule_gap_reports",
    "reaudit_leanstral_rule_gaps",
    "reaudit_rule_gaps",
    "verify_reaudit_report",
    "write_reaudit_atomic",
    "write_reaudit_report_atomic",
]
