"""Routing policy for selective Leanstral LegalIR audits.

Leanstral audit time is reserved for gaps that can still add verified
information.  This module is deliberately deterministic: it evaluates clustered
LegalIR disagreements, rejects work that is stale/solved/cache-covered/noisy,
and applies per-family budgets before the worker creates provider requests.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence

from .introspection_analysis import OWNED_COMPILER_SURFACES


LEANSTRAL_AUDIT_POLICY_SCHEMA_VERSION = "legal-ir-leanstral-audit-policy-v1"


class LeanstralAuditPolicyOutcome(str, Enum):
    """Stable outcome labels emitted by the Leanstral routing policy."""

    SELECTED = "selected"
    SKIPPED = "skipped"
    ABSTAINED = "abstained"
    CACHED = "cached"
    STALE = "stale"
    MARGINAL_VALUE = "marginal_value"


@dataclass(frozen=True)
class LeanstralAuditPolicyConfig:
    """Thresholds and fairness budgets for Leanstral audit routing."""

    enabled: bool = True
    min_recurrence: int = 2
    high_formal_severity: float = 0.85
    high_uncertainty: float = 0.40
    min_heldout_impact: float = 0.12
    min_mean_normalized_score: float = 0.05
    min_rank_score: float = 0.24
    max_selected_per_family: int = 4
    max_total_selected: int = 0
    exhausted_families: Sequence[str] = field(default_factory=tuple)
    exhausted_semantic_signatures: Sequence[str] = field(default_factory=tuple)
    owned_compiler_surfaces: Sequence[str] = field(default_factory=tuple)
    expected_state_hash: str = ""
    schema_version: str = LEANSTRAL_AUDIT_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != LEANSTRAL_AUDIT_POLICY_SCHEMA_VERSION:
            raise ValueError(f"unsupported Leanstral audit policy schema: {self.schema_version}")

    def bounded_min_recurrence(self) -> int:
        return max(1, int(self.min_recurrence or 1))

    def bounded_max_selected_per_family(self) -> int:
        return max(0, int(self.max_selected_per_family or 0))

    def bounded_max_total_selected(self) -> int:
        return max(0, int(self.max_total_selected or 0))

    def normalized_owned_surfaces(self) -> tuple[str, ...]:
        values = tuple(_token(value) for value in self.owned_compiler_surfaces if _token(value))
        return values or tuple(sorted(OWNED_COMPILER_SURFACES))

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["exhausted_families"] = list(self.exhausted_families)
        payload["exhausted_semantic_signatures"] = list(self.exhausted_semantic_signatures)
        payload["owned_compiler_surfaces"] = list(self.owned_compiler_surfaces)
        return payload


@dataclass(frozen=True)
class LeanstralAuditPolicyDecision:
    """One deterministic routing decision for a clustered LegalIR gap."""

    candidate_id: str
    outcome: LeanstralAuditPolicyOutcome
    reason: str
    semantic_family: str
    compiler_surface: str
    semantic_signature: str
    recurrence: int
    heldout_impact: float
    uncertainty: float
    formal_severity: float
    mean_normalized_score: float
    rank_score: float
    triggers: Sequence[str] = field(default_factory=tuple)
    evidence_ids: Sequence[str] = field(default_factory=tuple)
    owned_code_paths: Sequence[str] = field(default_factory=tuple)
    family_budget_used: int = 0
    family_budget: int = 0
    selected_order: int = 0
    cache_key: str = ""
    schema_version: str = LEANSTRAL_AUDIT_POLICY_SCHEMA_VERSION

    @property
    def selected(self) -> bool:
        return self.outcome == LeanstralAuditPolicyOutcome.SELECTED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cache_key": self.cache_key,
            "candidate_id": self.candidate_id,
            "compiler_surface": self.compiler_surface,
            "evidence_ids": list(self.evidence_ids),
            "family_budget": int(self.family_budget),
            "family_budget_used": int(self.family_budget_used),
            "formal_severity": _stable_float(self.formal_severity),
            "heldout_impact": _stable_float(self.heldout_impact),
            "mean_normalized_score": _stable_float(self.mean_normalized_score),
            "outcome": self.outcome.value,
            "owned_code_paths": list(self.owned_code_paths),
            "rank_score": _stable_float(self.rank_score),
            "reason": self.reason,
            "recurrence": int(self.recurrence),
            "schema_version": self.schema_version,
            "selected": self.selected,
            "selected_order": int(self.selected_order),
            "semantic_family": self.semantic_family,
            "semantic_signature": self.semantic_signature,
            "triggers": list(self.triggers),
            "uncertainty": _stable_float(self.uncertainty),
        }


@dataclass(frozen=True)
class LeanstralAuditPolicyReport:
    """Summary of all selected, skipped, cached, stale, and abstained work."""

    decisions: Sequence[LeanstralAuditPolicyDecision]
    config: LeanstralAuditPolicyConfig = field(default_factory=LeanstralAuditPolicyConfig)
    source_cluster_count: int = 0
    selected_candidate_ids: Sequence[str] = field(default_factory=tuple)
    family_selection_counts: Mapping[str, int] = field(default_factory=dict)
    schema_version: str = LEANSTRAL_AUDIT_POLICY_SCHEMA_VERSION

    @property
    def outcome_counts(self) -> Dict[str, int]:
        counts = {outcome.value: 0 for outcome in LeanstralAuditPolicyOutcome}
        for decision in self.decisions:
            counts[decision.outcome.value] = counts.get(decision.outcome.value, 0) + 1
        return counts

    @property
    def selected_count(self) -> int:
        return self.outcome_counts[LeanstralAuditPolicyOutcome.SELECTED.value]

    @property
    def skipped_count(self) -> int:
        return self.outcome_counts[LeanstralAuditPolicyOutcome.SKIPPED.value]

    @property
    def abstained_count(self) -> int:
        return self.outcome_counts[LeanstralAuditPolicyOutcome.ABSTAINED.value]

    @property
    def cached_count(self) -> int:
        return self.outcome_counts[LeanstralAuditPolicyOutcome.CACHED.value]

    @property
    def stale_count(self) -> int:
        return self.outcome_counts[LeanstralAuditPolicyOutcome.STALE.value]

    @property
    def marginal_value_count(self) -> int:
        return self.outcome_counts[LeanstralAuditPolicyOutcome.MARGINAL_VALUE.value]

    def to_dict(self) -> Dict[str, Any]:
        counts = self.outcome_counts
        return {
            "abstained_count": int(self.abstained_count),
            "cached_count": int(self.cached_count),
            "config": self.config.to_dict(),
            "decisions": [decision.to_dict() for decision in self.decisions],
            "family_selection_counts": dict(sorted(self.family_selection_counts.items())),
            "marginal_value_count": int(self.marginal_value_count),
            "outcome_counts": counts,
            "schema_version": self.schema_version,
            "selected_candidate_ids": list(self.selected_candidate_ids),
            "selected_count": int(self.selected_count),
            "skipped_count": int(self.skipped_count),
            "source_cluster_count": int(self.source_cluster_count),
            "stale_count": int(self.stale_count),
        }


def select_informative_leanstral_audit_clusters(
    clusters: Sequence[Any],
    *,
    records_by_evidence_id: Optional[Mapping[str, Mapping[str, Any]]] = None,
    config: Optional[LeanstralAuditPolicyConfig] = None,
    cache_hit_candidate_ids: Sequence[str] = (),
) -> LeanstralAuditPolicyReport:
    """Select unresolved LegalIR clusters worth routing to Leanstral."""

    cfg = config or LeanstralAuditPolicyConfig()
    cache_hits = {_token(value) for value in cache_hit_candidate_ids if _token(value)}
    records = records_by_evidence_id or {}
    family_counts: Dict[str, int] = {}
    decisions: list[LeanstralAuditPolicyDecision] = []
    selected_ids: list[str] = []
    selected_total = 0
    exhausted_families = {_token(value) for value in cfg.exhausted_families if _token(value)}
    exhausted_signatures = {
        _token(value) for value in cfg.exhausted_semantic_signatures if _token(value)
    }

    for cluster in clusters:
        candidate = _candidate_from_cluster(cluster, records)
        decision = _base_decision(candidate, cfg)
        if not cfg.enabled:
            decision = replace(
                decision,
                outcome=LeanstralAuditPolicyOutcome.SELECTED,
                reason="policy_disabled",
                selected_order=selected_total + 1,
            )
        elif candidate["candidate_id"] in cache_hits:
            decision = replace(
                decision,
                outcome=LeanstralAuditPolicyOutcome.CACHED,
                reason="cache_hit",
            )
        elif _is_stale(candidate, cfg):
            decision = replace(
                decision,
                outcome=LeanstralAuditPolicyOutcome.STALE,
                reason="stale_snapshot",
            )
        elif candidate["semantic_family"] in exhausted_families:
            decision = replace(
                decision,
                outcome=LeanstralAuditPolicyOutcome.ABSTAINED,
                reason="family_exhausted",
            )
        elif candidate["semantic_signature"] in exhausted_signatures:
            decision = replace(
                decision,
                outcome=LeanstralAuditPolicyOutcome.ABSTAINED,
                reason="semantic_signature_exhausted",
            )
        elif not _has_owned_compiler_surface(candidate, cfg):
            decision = replace(
                decision,
                outcome=LeanstralAuditPolicyOutcome.SKIPPED,
                reason="unowned_compiler_surface",
            )
        elif _is_solved_obligation_noise(candidate):
            decision = replace(
                decision,
                outcome=LeanstralAuditPolicyOutcome.SKIPPED,
                reason="solved_obligation",
            )
        else:
            triggers = _selection_triggers(candidate, cfg)
            if not triggers:
                decision = replace(
                    decision,
                    outcome=LeanstralAuditPolicyOutcome.MARGINAL_VALUE,
                    reason="low_expected_information_gain",
                    triggers=(),
                )
            else:
                family = candidate["semantic_family"]
                family_budget = cfg.bounded_max_selected_per_family()
                total_budget = cfg.bounded_max_total_selected()
                used = family_counts.get(family, 0)
                if family_budget and used >= family_budget:
                    decision = replace(
                        decision,
                        outcome=LeanstralAuditPolicyOutcome.ABSTAINED,
                        reason="family_budget_exhausted",
                        triggers=triggers,
                        family_budget_used=used,
                        family_budget=family_budget,
                    )
                elif total_budget and selected_total >= total_budget:
                    decision = replace(
                        decision,
                        outcome=LeanstralAuditPolicyOutcome.ABSTAINED,
                        reason="total_budget_exhausted",
                        triggers=triggers,
                        family_budget_used=used,
                        family_budget=family_budget,
                    )
                else:
                    selected_total += 1
                    family_counts[family] = used + 1
                    selected_ids.append(candidate["candidate_id"])
                    decision = replace(
                        decision,
                        outcome=LeanstralAuditPolicyOutcome.SELECTED,
                        reason="informative_unresolved_gap",
                        triggers=triggers,
                        family_budget_used=used + 1,
                        family_budget=family_budget,
                        selected_order=selected_total,
                    )
        decisions.append(decision)

    return LeanstralAuditPolicyReport(
        decisions=tuple(decisions),
        config=cfg,
        source_cluster_count=len(clusters),
        selected_candidate_ids=tuple(selected_ids),
        family_selection_counts=dict(family_counts),
    )


def leanstral_policy_report_with_cache_hits(
    report: LeanstralAuditPolicyReport,
    candidate_ids: Sequence[str],
) -> LeanstralAuditPolicyReport:
    """Move already-selected decisions to the cached outcome."""

    cache_hits = {_token(value) for value in candidate_ids if _token(value)}
    if not cache_hits:
        return report
    decisions: list[LeanstralAuditPolicyDecision] = []
    family_counts: Dict[str, int] = {}
    selected_ids: list[str] = []
    order = 0
    for decision in report.decisions:
        if decision.candidate_id in cache_hits and decision.outcome == LeanstralAuditPolicyOutcome.SELECTED:
            decisions.append(
                replace(
                    decision,
                    outcome=LeanstralAuditPolicyOutcome.CACHED,
                    reason="cache_hit",
                    selected_order=0,
                )
            )
            continue
        if decision.outcome == LeanstralAuditPolicyOutcome.SELECTED:
            order += 1
            family_counts[decision.semantic_family] = family_counts.get(decision.semantic_family, 0) + 1
            selected_ids.append(decision.candidate_id)
            decisions.append(
                replace(
                    decision,
                    family_budget_used=family_counts[decision.semantic_family],
                    selected_order=order,
                )
            )
        else:
            decisions.append(decision)
    return LeanstralAuditPolicyReport(
        decisions=tuple(decisions),
        config=report.config,
        source_cluster_count=report.source_cluster_count,
        selected_candidate_ids=tuple(selected_ids),
        family_selection_counts=family_counts,
    )


def policy_decision_by_candidate_id(
    report: LeanstralAuditPolicyReport,
) -> Dict[str, LeanstralAuditPolicyDecision]:
    return {decision.candidate_id: decision for decision in report.decisions}


def _base_decision(
    candidate: Mapping[str, Any],
    cfg: LeanstralAuditPolicyConfig,
) -> LeanstralAuditPolicyDecision:
    return LeanstralAuditPolicyDecision(
        candidate_id=str(candidate["candidate_id"]),
        outcome=LeanstralAuditPolicyOutcome.SKIPPED,
        reason="not_evaluated",
        semantic_family=str(candidate["semantic_family"]),
        compiler_surface=str(candidate["compiler_surface"]),
        semantic_signature=str(candidate["semantic_signature"]),
        recurrence=int(candidate["recurrence"]),
        heldout_impact=float(candidate["heldout_impact"]),
        uncertainty=float(candidate["uncertainty"]),
        formal_severity=float(candidate["formal_severity"]),
        mean_normalized_score=float(candidate["mean_normalized_score"]),
        rank_score=float(candidate["rank_score"]),
        triggers=(),
        evidence_ids=tuple(candidate["evidence_ids"]),
        owned_code_paths=tuple(candidate["owned_code_paths"]),
        family_budget=cfg.bounded_max_selected_per_family(),
    )


def _candidate_from_cluster(
    cluster: Any,
    records_by_evidence_id: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    payload = _cluster_mapping(cluster)
    evidence_ids = tuple(str(value) for value in payload.get("evidence_ids", []) or [] if str(value))
    gap_payloads = _gap_payloads(payload)
    related_records = tuple(
        dict(records_by_evidence_id[evidence_id])
        for evidence_id in evidence_ids
        if evidence_id in records_by_evidence_id
    )
    candidate_id = str(payload.get("cluster_id") or "").strip()
    if not candidate_id:
        candidate_id = (
            str(getattr(cluster, "expected_cluster_id", lambda: "")() or "").strip()
            if callable(getattr(cluster, "expected_cluster_id", None))
            else ""
        )
    if not candidate_id:
        candidate_id = f"{payload.get('semantic_signature', '')}:{payload.get('compiler_surface', '')}"
    confidence = _finite_float(payload.get("confidence"), 0.0)
    uncertainty = max(
        0.0,
        min(
            1.0,
            _max_record_uncertainty(related_records, gap_payloads)
            or (1.0 - confidence),
        ),
    )
    return {
        "candidate_id": candidate_id,
        "compiler_surface": str(payload.get("compiler_surface") or ""),
        "evidence_ids": evidence_ids,
        "formal_severity": _finite_float(payload.get("formal_severity"), 0.0),
        "gap_payloads": gap_payloads,
        "heldout_impact": _finite_float(payload.get("heldout_impact"), 0.0),
        "mean_normalized_score": _finite_float(payload.get("mean_normalized_score"), 0.0),
        "owned_code_paths": tuple(str(value) for value in payload.get("owned_code_paths", []) or [] if str(value)),
        "rank_score": _finite_float(payload.get("rank_score"), 0.0),
        "records": related_records,
        "recurrence": int(_finite_float(payload.get("recurrence"), 0.0)),
        "semantic_family": str(payload.get("semantic_family") or "legal_ir"),
        "semantic_signature": str(payload.get("semantic_signature") or ""),
        "state_hashes": _candidate_state_hashes(payload, related_records),
        "uncertainty": uncertainty,
    }


def _selection_triggers(
    candidate: Mapping[str, Any],
    cfg: LeanstralAuditPolicyConfig,
) -> tuple[str, ...]:
    triggers: list[str] = []
    if int(candidate["recurrence"]) >= cfg.bounded_min_recurrence():
        triggers.append("recurrent")
    if float(candidate["formal_severity"]) >= _threshold(cfg.high_formal_severity, 0.85):
        triggers.append("high_severity")
    if float(candidate["uncertainty"]) >= _threshold(cfg.high_uncertainty, 0.40):
        triggers.append("high_uncertainty")
    if _hammer_unsolved(candidate):
        triggers.append("hammer_unsolved")
    if (
        not triggers
        and float(candidate["heldout_impact"]) >= _threshold(cfg.min_heldout_impact, 0.12)
        and float(candidate["mean_normalized_score"]) >= _threshold(cfg.min_mean_normalized_score, 0.05)
        and float(candidate["rank_score"]) >= _threshold(cfg.min_rank_score, 0.24)
    ):
        triggers.append("ranked_information_gain")
    return tuple(dict.fromkeys(triggers))


def _has_owned_compiler_surface(
    candidate: Mapping[str, Any],
    cfg: LeanstralAuditPolicyConfig,
) -> bool:
    surface = str(candidate.get("compiler_surface") or "")
    return bool(surface and surface in set(cfg.normalized_owned_surfaces()))


def _is_stale(candidate: Mapping[str, Any], cfg: LeanstralAuditPolicyConfig) -> bool:
    expected = _token(cfg.expected_state_hash)
    if not expected:
        return False
    state_hashes = set(candidate.get("state_hashes", ()) or ())
    return bool(state_hashes and expected not in state_hashes)


def _is_solved_obligation_noise(candidate: Mapping[str, Any]) -> bool:
    gap_text = " ".join(
        str(gap.get("gap_kind") or "") + " " + str(gap.get("source_key") or "")
        for gap in candidate.get("gap_payloads", ()) or ()
        if isinstance(gap, Mapping)
    ).lower()
    if not any(token in gap_text for token in ("proof", "prover", "hammer")):
        return False
    statuses = [
        _proof_status(record)
        for record in candidate.get("records", ()) or ()
        if _proof_status(record).get("attempted")
    ]
    if not statuses:
        return False
    return all(status.get("solved") for status in statuses)


def _hammer_unsolved(candidate: Mapping[str, Any]) -> bool:
    gap_text = " ".join(
        str(gap.get("gap_kind") or "") + " " + str(gap.get("source_key") or "")
        for gap in candidate.get("gap_payloads", ()) or ()
        if isinstance(gap, Mapping)
    ).lower()
    if any(token in gap_text for token in ("formal_prover_gap", "hammer", "proof_route_status")):
        return True
    for record in candidate.get("records", ()) or ():
        status = _proof_status(record)
        if status.get("attempted") and not status.get("solved"):
            return True
    return False


def _proof_status(record: Mapping[str, Any]) -> Dict[str, bool]:
    root = _root_record(record)
    proof = _mapping(root.get("proof_route_status") or root.get("hammer_status") or root.get("prover_signal"))
    if not proof:
        return {"attempted": False, "solved": False}
    attempted_count = int(_finite_float(proof.get("attempted_count"), 0.0))
    valid_count = int(_finite_float(proof.get("valid_count"), 0.0))
    failure_count = int(_finite_float(proof.get("failure_count"), 0.0))
    status = str(
        proof.get("route_status")
        or proof.get("status")
        or proof.get("hammer_status")
        or ""
    ).strip().lower()
    attempted = attempted_count > 0 or bool(status)
    solved_statuses = {"accepted", "compiled", "proved", "success", "valid", "verified"}
    failed_statuses = {
        "counterexample",
        "failed",
        "hammer_unproved",
        "invalid",
        "rejected",
        "timed_out",
        "timeout",
        "translation_failed",
        "unproved",
        "unsupported",
    }
    solved = (
        status in solved_statuses
        and failure_count == 0
        and (attempted_count == 0 or valid_count >= attempted_count)
    )
    if status in failed_statuses:
        solved = False
    return {"attempted": attempted, "solved": solved}


def _cluster_mapping(cluster: Any) -> Dict[str, Any]:
    if isinstance(cluster, Mapping):
        return dict(cluster)
    to_dict = getattr(cluster, "to_dict", None)
    if callable(to_dict):
        try:
            value = to_dict(include_gaps=True)
        except TypeError:
            value = to_dict()
        if isinstance(value, Mapping):
            return dict(value)
    return {
        key: getattr(cluster, key)
        for key in (
            "cluster_id",
            "compiler_surface",
            "confidence",
            "evidence_ids",
            "formal_severity",
            "gaps",
            "heldout_impact",
            "mean_normalized_score",
            "owned_code_paths",
            "rank_score",
            "recurrence",
            "semantic_family",
            "semantic_signature",
        )
        if hasattr(cluster, key)
    }


def _gap_payloads(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    gaps = payload.get("gaps")
    if not isinstance(gaps, Sequence) or isinstance(gaps, (str, bytes)):
        return ()
    return tuple(dict(gap) for gap in gaps if isinstance(gap, Mapping))


def _candidate_state_hashes(
    payload: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    values = {str(value) for value in payload.get("state_hashes", []) or [] if str(value)}
    for record in records:
        root = _root_record(record)
        hashes = _mapping(root.get("evidence_hashes"))
        context = _mapping(root.get("run_context"))
        for value in (
            hashes.get("state_hash"),
            context.get("state_hash"),
            root.get("state_hash"),
        ):
            if str(value or ""):
                values.add(str(value))
    return tuple(sorted(values))


def _max_record_uncertainty(
    records: Sequence[Mapping[str, Any]],
    gaps: Sequence[Mapping[str, Any]],
) -> float:
    values: list[float] = []
    for gap in gaps:
        for key in ("uncertainty", "entropy", "ambiguity"):
            value = _finite_float(gap.get(key), -1.0)
            if value >= 0.0:
                values.append(min(1.0, value))
    for record in records:
        root = _root_record(record)
        values.extend(_view_uncertainties(_mapping(root.get("legal_ir_views"))))
        values.extend(_mapping_uncertainties(_mapping(root.get("uncertainty"))))
    return max(values) if values else 0.0


def _view_uncertainties(views: Mapping[str, Any]) -> tuple[float, ...]:
    values: list[float] = []
    for view in views.values():
        if not isinstance(view, Mapping):
            continue
        distribution = view.get("family_distribution")
        if not isinstance(distribution, Mapping) or not distribution:
            continue
        probs = sorted(
            (_finite_float(value, 0.0) for value in distribution.values()),
            reverse=True,
        )
        if len(probs) == 1:
            values.append(max(0.0, 1.0 - probs[0]))
        elif len(probs) > 1:
            values.append(max(0.0, min(1.0, 1.0 - (probs[0] - probs[1]))))
    return tuple(values)


def _mapping_uncertainties(value: Mapping[str, Any]) -> tuple[float, ...]:
    values: list[float] = []
    for item in value.values():
        if isinstance(item, Mapping):
            values.extend(_mapping_uncertainties(item))
        else:
            number = _finite_float(item, -1.0)
            if number >= 0.0:
                values.append(min(1.0, number))
    return tuple(values)


def _root_record(record: Mapping[str, Any]) -> Mapping[str, Any]:
    root = dict(record)
    if isinstance(root.get("payload"), Mapping):
        root = dict(root["payload"])
    return root


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _finite_float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _threshold(value: Any, default: float) -> float:
    result = _finite_float(value, default)
    return max(0.0, min(1.0, result))


def _stable_float(value: Any) -> float:
    return round(_finite_float(value, 0.0), 6)


def _token(value: Any) -> str:
    return str(value or "").strip()


__all__ = [
    "LEANSTRAL_AUDIT_POLICY_SCHEMA_VERSION",
    "LeanstralAuditPolicyConfig",
    "LeanstralAuditPolicyDecision",
    "LeanstralAuditPolicyOutcome",
    "LeanstralAuditPolicyReport",
    "leanstral_policy_report_with_cache_hits",
    "policy_decision_by_candidate_id",
    "select_informative_leanstral_audit_clusters",
]
