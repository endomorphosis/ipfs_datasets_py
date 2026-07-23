"""Deterministic, source-free premise ranking for LegalIR hammer goals.

The generic hammer selector uses lexical overlap.  That is useful for ordinary
interactive theorem proving, but it is the wrong signal for legal compiler
artifacts: source wording must not become a premise-selection feature.  This
module ranks only typed compiler/contract metadata and stable identifiers.

In particular, neither a goal statement nor a premise statement is tokenized,
and metadata fields capable of containing copied source text are ignored.  A
source-span *hash* may be compared as provenance, while the corresponding span
can never affect the score or appear in a ranking receipt.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from .hammer import HammerGoal, HammerPremise, PremiseSelection
from .legal_ir_obligations import LegalIRProofObligation
from .legal_ir_premise_security import scan_hammer_premise
from .legal_ir_view_contracts import LegalIRViewContract, legal_ir_view_contract


LEGAL_IR_PREMISE_SELECTION_SCHEMA_VERSION: Final = "legal-ir-premise-selection-v1"

# These keys may contain source material.  They are intentionally broader than
# the contract registry's forbidden fields because hammer feedback and model
# candidates use a few additional spellings.
_SOURCE_TEXT_KEYS: Final = frozenset(
    {
        "copied_source",
        "copied_source_span",
        "copied_text",
        "draft_text",
        "full_text",
        "legal_text",
        "normalized_text",
        "proof_text",
        "raw_output",
        "raw_source",
        "source",
        "source_excerpt",
        "source_span",
        "source_text",
        "source_text_excerpt",
        "statement",
        "text",
    }
)
_HASH_KEYS: Final = frozenset(
    {
        "citation_hash",
        "citation_hashes",
        "document_hash",
        "evidence_hash",
        "modal_ir_hash",
        "provenance_ids",
        "provenance_hash",
        "provenance_hashes",
        "registry_hash",
        "source_cid",
        "source_hash",
        "source_id",
        "source_references",
        "source_span_hash",
        "theorem_registry_hash",
    }
)
_FIELD_KEYS: Final = frozenset(
    {
        "contract_field",
        "contract_fields",
        "field_path",
        "field_paths",
        "missing_required_fields",
        "required_field",
        "required_fields",
    }
)
_FAMILY_KEYS: Final = frozenset(
    {
        "kind",
        "logic_family",
        "obligation_family",
        "obligation_families",
        "obligation_kind",
        "premise_hints",
    }
)
_VIEW_KEYS: Final = frozenset(
    {
        "contract_view",
        "legal_ir_view",
        "related_views",
        "target_component",
        "target_view",
        "view",
    }
)
_VERIFIED_FAILURE_KEYS: Final = frozenset(
    {
        "verified_failure_reason",
        "verified_failure_reasons",
        "verified_failures",
    }
)
_FAILURE_KEYS: Final = frozenset(
    {
        "failure_code",
        "failure_reason",
        "failure_reasons",
        "reconstruction_failure_reason",
        "validation_failure",
        "validation_failures",
    }
)
_TRUE_VALUES: Final = frozenset({"accepted", "checked", "proved", "trusted", "verified"})


class LegalIRPremiseKind(str, Enum):
    """Stable premise classes consumed by ranking metrics and guidance."""

    COMPILER_FACT = "compiler_fact"
    THEOREM_TEMPLATE = "theorem_template"
    SAMPLE_LOCAL_ASSUMPTION = "sample_local_assumption"
    VERIFIED_LEANSTRAL_THEOREM = "verified_leanstral_theorem"
    LEANSTRAL_THEOREM = "leanstral_theorem"


@dataclass(frozen=True)
class LegalIRPremiseScore:
    """Auditable score for one premise, containing no source text."""

    premise_name: str
    score: float
    premise_kind: str
    components: Mapping[str, float] = field(default_factory=dict)
    matched_contract_fields: tuple[str, ...] = ()
    matched_failure_reasons: tuple[str, ...] = ()
    matched_hashes: tuple[str, ...] = ()
    matched_obligation_families: tuple[str, ...] = ()
    matched_views: tuple[str, ...] = ()
    schema_version: str = LEGAL_IR_PREMISE_SELECTION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "components": {
                key: round(float(value), 6)
                for key, value in sorted(self.components.items())
            },
            "matched_contract_fields": list(self.matched_contract_fields),
            "matched_failure_reasons": list(self.matched_failure_reasons),
            "matched_hashes": list(self.matched_hashes),
            "matched_obligation_families": list(self.matched_obligation_families),
            "matched_views": list(self.matched_views),
            "premise_kind": self.premise_kind,
            "premise_name": self.premise_name,
            "schema_version": self.schema_version,
            "score": round(float(self.score), 6),
        }


@dataclass(frozen=True)
class RankedLegalIRPremise:
    """A premise paired with its source-free score receipt."""

    premise: HammerPremise
    ranking: LegalIRPremiseScore

    @property
    def score(self) -> float:
        return self.ranking.score

    def to_dict(self) -> dict[str, Any]:
        # Statements and arbitrary premise metadata are deliberately omitted.
        return self.ranking.to_dict()


@dataclass(frozen=True)
class _RankingContext:
    obligation_families: frozenset[str]
    views: frozenset[str]
    contract_ids: frozenset[str]
    contract_fields: frozenset[str]
    verified_failure_reasons: frozenset[str]
    failure_reasons: frozenset[str]
    hashes: frozenset[str]
    sample_ids: frozenset[str]
    formula_ids: frozenset[str]


def _stable_json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            converted = to_dict()
        except (TypeError, ValueError):
            converted = None
        if isinstance(converted, Mapping):
            return dict(converted)
    return {}


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _atom(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9_.:/-]+", "_", text).strip("_")


def _identifier(value: Any) -> str:
    """Accept bounded metadata identifiers, never free-form text as a feature."""

    text = str(value or "").strip().lower()
    if len(text) > 160 or not re.fullmatch(r"[a-z0-9_.:/-]+", text):
        return ""
    return text


def _values(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        result: set[str] = set()
        for key, child in value.items():
            # For {view: [fields]} telemetry, both the view and fields matter.
            normalized_key = _identifier(key)
            if normalized_key:
                result.add(normalized_key)
            result.update(_values(child))
        return result
    return {
        _identifier(item)
        for item in _sequence(value)
        if _identifier(item)
    }


def _safe_metadata(value: Any) -> dict[str, Any]:
    """Recursively discard source-bearing fields before feature extraction."""

    result: dict[str, Any] = {}
    for key, child in _mapping(value).items():
        normalized = _atom(key)
        if normalized in _SOURCE_TEXT_KEYS or (
            (normalized.endswith("_text") or normalized.endswith("_excerpt"))
            and not normalized.endswith("_text_hash")
        ):
            continue
        if isinstance(child, Mapping):
            result[str(key)] = _safe_metadata(child)
        elif isinstance(child, Sequence) and not isinstance(child, (str, bytes, bytearray)):
            result[str(key)] = [
                _safe_metadata(item) if isinstance(item, Mapping) else item for item in child
            ]
        else:
            result[str(key)] = child
    return result


def _collect_keyed_values(value: Any, keys: frozenset[str]) -> set[str]:
    result: set[str] = set()

    def walk(current: Any) -> None:
        if isinstance(current, Mapping):
            for key, child in current.items():
                normalized = _atom(key)
                if normalized in _SOURCE_TEXT_KEYS:
                    continue
                if normalized in keys:
                    result.update(_values(child))
                elif isinstance(child, (Mapping, list, tuple)):
                    walk(child)
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            for child in current:
                walk(child)

    walk(value)
    return result


def _collect_hash_values(value: Any) -> set[str]:
    """Return identifiers plus their hashes so raw IDs match stored digests."""

    identifiers = _collect_keyed_values(value, _HASH_KEYS)
    return identifiers | {_stable_hash(identifier) for identifier in identifiers}


def _canonical_contract(value: Any) -> LegalIRViewContract | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return legal_ir_view_contract(text)
    except KeyError:
        return None


def _canonical_views(values: set[str]) -> set[str]:
    result: set[str] = set()
    for value in values:
        contract = _canonical_contract(value)
        if contract is None:
            result.add(_atom(value))
        else:
            result.update(
                {
                    _atom(contract.view.value),
                    _atom(contract.target_component),
                    _atom(contract.contract_id),
                }
            )
    return result


def _explicitly_verified(metadata: Mapping[str, Any]) -> bool:
    for key in (
        "accepted",
        "verified",
        "trusted",
        "proof_checked",
        "kernel_verified",
        "is_verified",
    ):
        value = metadata.get(key)
        if isinstance(value, bool) and value:
            return True
        if _atom(value) in _TRUE_VALUES:
            return True
    for key in (
        "verification_status",
        "trust_status",
        "proof_status",
        "kernel_status",
        "reconstruction_status",
        "status",
    ):
        if _atom(metadata.get(key)) in _TRUE_VALUES:
            return True
    return False


def _premise_kind(metadata: Mapping[str, Any]) -> LegalIRPremiseKind:
    explicit = _atom(metadata.get("premise_kind") or metadata.get("source_kind"))
    aliases = {
        "compiler": LegalIRPremiseKind.COMPILER_FACT,
        "compiler_fact": LegalIRPremiseKind.COMPILER_FACT,
        "theorem_template": LegalIRPremiseKind.THEOREM_TEMPLATE,
        "template": LegalIRPremiseKind.THEOREM_TEMPLATE,
        "sample_local": LegalIRPremiseKind.SAMPLE_LOCAL_ASSUMPTION,
        "sample_local_assumption": LegalIRPremiseKind.SAMPLE_LOCAL_ASSUMPTION,
        "verified_leanstral_theorem": LegalIRPremiseKind.VERIFIED_LEANSTRAL_THEOREM,
        "leanstral_theorem": LegalIRPremiseKind.LEANSTRAL_THEOREM,
    }
    if explicit in aliases:
        kind = aliases[explicit]
        if kind is LegalIRPremiseKind.LEANSTRAL_THEOREM and _explicitly_verified(metadata):
            return LegalIRPremiseKind.VERIFIED_LEANSTRAL_THEOREM
        return kind

    source = _atom(metadata.get("source_module"))
    if "theorem_registry" in source or metadata.get("theorem_id"):
        return (
            LegalIRPremiseKind.VERIFIED_LEANSTRAL_THEOREM
            if _explicitly_verified(metadata)
            else LegalIRPremiseKind.LEANSTRAL_THEOREM
        )
    if source in {"legal_ir_document", "legal_ir_compiler"} or "compiler" in source:
        return LegalIRPremiseKind.COMPILER_FACT
    if source in {"legal_ir_premise_library", "legal_ir_theorem_templates"} or metadata.get("template_id"):
        return LegalIRPremiseKind.THEOREM_TEMPLATE
    return LegalIRPremiseKind.SAMPLE_LOCAL_ASSUMPTION


def _as_premise(value: HammerPremise | Mapping[str, Any] | str, index: int) -> HammerPremise:
    if isinstance(value, HammerPremise):
        return value
    if isinstance(value, Mapping):
        return HammerPremise(
            name=str(value.get("name") or f"premise_{index}"),
            statement=str(value.get("statement") or value.get("formula") or ""),
            weight=float(value.get("weight", 1.0) or 1.0),
            metadata=dict(value.get("metadata") or {}),
        )
    return HammerPremise(name=f"premise_{index}", statement=str(value))


def _goal_mapping(goal: HammerGoal | LegalIRProofObligation | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(goal, Mapping):
        top = dict(goal)
    else:
        top = {
            key: getattr(goal, key)
            for key in (
                "formula_id",
                "kind",
                "legal_ir_view",
                "name",
                "sample_id",
            )
            if hasattr(goal, key)
        }
        top["metadata"] = getattr(goal, "metadata", {})
    metadata = _safe_metadata(top.get("metadata"))
    return {**_safe_metadata(top), **metadata}


def _telemetry_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    projection = getattr(value, "guidance_projection", None)
    if callable(projection):
        try:
            return _safe_metadata(projection())
        except (TypeError, ValueError):
            return {}
    return _safe_metadata(value)


def _context(
    goal: HammerGoal | LegalIRProofObligation | Mapping[str, Any],
    telemetry: Any = None,
) -> _RankingContext:
    data = _goal_mapping(goal)
    embedded_telemetry = (
        data.get("legal_ir_contract_telemetry")
        or data.get("contract_telemetry")
        or telemetry
    )
    telemetry_data = _telemetry_mapping(embedded_telemetry)

    families = _collect_keyed_values(data, _FAMILY_KEYS)
    views = _collect_keyed_values(data, _VIEW_KEYS)
    contract_ids = _collect_keyed_values(data, frozenset({"contract_id", "related_contract_ids"}))
    fields = _collect_keyed_values(data, _FIELD_KEYS)
    verified_failures = _collect_keyed_values(data, _VERIFIED_FAILURE_KEYS)
    failures = _collect_keyed_values(data, _FAILURE_KEYS)
    hashes = _collect_hash_values(data)
    sample_ids = _collect_keyed_values(data, frozenset({"sample_id"}))
    formula_ids = _collect_keyed_values(data, frozenset({"formula_id", "input_formula_id"}))

    # Contract telemetry is deterministic compiler output, so its reasons are
    # verified failure signals rather than free-form model labels.  Formula
    # failures are filtered to the current formula when both sides identify it.
    verified_failures.update(
        _collect_keyed_values(telemetry_data, _VERIFIED_FAILURE_KEYS)
    )
    goal_views = _canonical_views(views)
    for collection_name in (
        "cross_view_mismatches",
        "decompiler_preservation_failures",
    ):
        for item in _sequence(telemetry_data.get(collection_name)):
            item_data = _mapping(item)
            item_formulas = _collect_keyed_values(
                item_data, frozenset({"formula_id", "input_formula_id"})
            )
            if formula_ids and item_formulas and not formula_ids.intersection(item_formulas):
                continue
            verified_failures.update(
                _collect_keyed_values(item_data, frozenset({"code", "reason"}))
            )
            fields.update(_collect_keyed_values(item_data, frozenset({"field_path"})))
            hashes.update(_collect_hash_values(item_data))
            views.update(_collect_keyed_values(item_data, _VIEW_KEYS))

    missing_by_view = _mapping(telemetry_data.get("missing_required_fields"))
    for view, missing_fields in missing_by_view.items():
        telemetry_view = _canonical_views({_atom(view)})
        if goal_views and not goal_views.intersection(telemetry_view):
            continue
        fields.update(_values(missing_fields))
        views.add(_atom(view))
        verified_failures.add("missing_required_field")
    for key, count in _mapping(telemetry_data.get("validation_issue_counts")).items():
        try:
            present = int(count) > 0
        except (TypeError, ValueError):
            present = bool(count)
        if present and _atom(key):
            verified_failures.add(_atom(key))
    for key, count in _mapping(
        telemetry_data.get("legal_ir_contract_failure_counts")
    ).items():
        try:
            present = int(count) > 0
        except (TypeError, ValueError):
            present = bool(count)
        if present and _atom(key):
            verified_failures.add(_atom(key))
    hashes.update(_collect_hash_values(telemetry_data))

    contracts: list[LegalIRViewContract] = []
    for value in sorted(views | contract_ids):
        contract = _canonical_contract(value)
        if contract is not None and contract not in contracts:
            contracts.append(contract)
    # For a general family obligation all required fields are useful.  For a
    # field-specific obligation, the explicit field remains the sharper signal.
    if not fields:
        fields.update(_atom(name) for contract in contracts for name in contract.required_field_names)
    contract_ids.update(_atom(contract.contract_id) for contract in contracts)

    return _RankingContext(
        obligation_families=frozenset(families),
        views=frozenset(_canonical_views(views)),
        contract_ids=frozenset(contract_ids),
        contract_fields=frozenset(fields),
        verified_failure_reasons=frozenset(verified_failures),
        failure_reasons=frozenset(failures),
        hashes=frozenset(hashes),
        sample_ids=frozenset(sample_ids),
        formula_ids=frozenset(formula_ids),
    )


def _bounded_weight(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(result):
        return 1.0
    return min(4.0, max(0.0, result))


class LegalIRPremiseSelector:
    """Rank LegalIR premises by typed evidence, contracts, and failures.

    ``select`` implements the protocol expected by :class:`HammerPipeline`.
    ``rank`` exposes source-free score receipts for telemetry and tests.
    """

    _KIND_PRIOR: Final = {
        LegalIRPremiseKind.COMPILER_FACT: 0.35,
        LegalIRPremiseKind.THEOREM_TEMPLATE: 0.30,
        LegalIRPremiseKind.SAMPLE_LOCAL_ASSUMPTION: 0.40,
        LegalIRPremiseKind.VERIFIED_LEANSTRAL_THEOREM: 0.75,
        LegalIRPremiseKind.LEANSTRAL_THEOREM: 0.10,
    }

    def __init__(self, *, contract_telemetry: Any = None) -> None:
        self.contract_telemetry = contract_telemetry

    def score(
        self,
        goal: HammerGoal | LegalIRProofObligation | Mapping[str, Any],
        premise: HammerPremise | Mapping[str, Any] | str,
    ) -> LegalIRPremiseScore:
        """Return the source-free score receipt for a single premise."""

        return self._score(
            _context(goal, self.contract_telemetry),
            _as_premise(premise, 1),
        ).ranking

    def rank(
        self,
        goal: HammerGoal | LegalIRProofObligation | Mapping[str, Any],
        premises: Sequence[HammerPremise | Mapping[str, Any] | str],
    ) -> list[RankedLegalIRPremise]:
        context = _context(goal, self.contract_telemetry)
        ranked: list[RankedLegalIRPremise] = []
        for index, premise in enumerate(premises, start=1):
            resolved = _as_premise(premise, index)
            if scan_hammer_premise(resolved).rejected:
                continue
            ranked.append(self._score(context, resolved))
        return sorted(
            ranked,
            key=lambda item: (
                -item.score,
                item.premise.name,
                item.ranking.premise_kind,
            ),
        )

    def select(
        self,
        goal: HammerGoal | LegalIRProofObligation | Mapping[str, Any],
        premises: Sequence[HammerPremise | Mapping[str, Any] | str],
        *,
        max_premises: int = 256,
    ) -> PremiseSelection:
        ranked = self.rank(goal, premises)
        limit = max(0, int(max_premises))
        selected_rankings = ranked[:limit]
        return PremiseSelection(
            selected=[item.premise for item in selected_rankings],
            scores={item.premise.name: item.score for item in selected_rankings},
            considered_count=len(ranked),
            max_premises=limit,
        )

    def _score(self, context: _RankingContext, premise: HammerPremise) -> RankedLegalIRPremise:
        metadata = _safe_metadata(premise.metadata)
        kind = _premise_kind(metadata)
        premise_families = _collect_keyed_values(metadata, _FAMILY_KEYS)
        premise_views = _canonical_views(_collect_keyed_values(metadata, _VIEW_KEYS))
        premise_contract_ids = _collect_keyed_values(
            metadata, frozenset({"contract_id", "related_contract_ids"})
        )
        premise_fields = _collect_keyed_values(metadata, _FIELD_KEYS)
        premise_verified_failures = _collect_keyed_values(metadata, _VERIFIED_FAILURE_KEYS)
        premise_failures = _collect_keyed_values(metadata, _FAILURE_KEYS)
        premise_hashes = _collect_hash_values(metadata)
        premise_samples = _collect_keyed_values(metadata, frozenset({"sample_id"}))
        premise_formulas = _collect_keyed_values(
            metadata, frozenset({"formula_id", "input_formula_id"})
        )

        matched_families = context.obligation_families & premise_families
        matched_views = context.views & premise_views
        matched_contracts = context.contract_ids & premise_contract_ids
        matched_fields = context.contract_fields & premise_fields
        matched_verified_failures = context.verified_failure_reasons & (
            premise_verified_failures | premise_failures
        )
        matched_failures = context.failure_reasons & (
            premise_verified_failures | premise_failures
        )
        matched_hashes = context.hashes & premise_hashes
        matched_samples = context.sample_ids & premise_samples
        matched_formulas = context.formula_ids & premise_formulas

        components: dict[str, float] = {"premise_kind": self._KIND_PRIOR[kind]}
        if matched_families:
            components["obligation_family"] = 3.0
        if matched_views:
            components["target_view"] = 2.5
        if matched_contracts:
            components["contract_id"] = 1.25
        if matched_fields:
            denominator = max(1, len(context.contract_fields))
            components["contract_field_overlap"] = min(2.0, 2.0 * len(matched_fields) / denominator)
        if matched_verified_failures:
            components["verified_failure_reason"] = 2.25
        elif matched_failures:
            components["failure_reason"] = 0.75
        if matched_hashes:
            components["provenance_hash"] = 1.75
        if matched_samples:
            components["sample_locality"] = 1.0
        elif premise_samples and context.sample_ids:
            components["different_sample_penalty"] = -1.0
        if matched_formulas:
            components["formula_locality"] = 0.75
        if kind is LegalIRPremiseKind.VERIFIED_LEANSTRAL_THEOREM:
            components["verified_registry"] = 1.0
        # Existing premise weights remain a small, bounded prior rather than a
        # multiplier that could overwhelm contract correctness.
        components["premise_weight"] = 0.15 * (_bounded_weight(premise.weight) - 1.0)

        score = round(max(0.0, sum(components.values())), 6)
        failure_matches = matched_verified_failures or matched_failures
        receipt = LegalIRPremiseScore(
            premise_name=premise.name,
            score=score,
            premise_kind=kind.value,
            components=components,
            matched_contract_fields=tuple(sorted(matched_fields)),
            matched_failure_reasons=tuple(sorted(failure_matches)),
            # Emit only digests of identifiers, not even identifier values.
            matched_hashes=tuple(sorted(_stable_hash(value)[:16] for value in matched_hashes)),
            matched_obligation_families=tuple(sorted(matched_families)),
            matched_views=tuple(sorted(matched_views)),
        )
        return RankedLegalIRPremise(premise=premise, ranking=receipt)


def rank_legal_ir_premises(
    goal: HammerGoal | LegalIRProofObligation | Mapping[str, Any],
    premises: Sequence[HammerPremise | Mapping[str, Any] | str],
    *,
    max_premises: int = 256,
    contract_telemetry: Any = None,
) -> PremiseSelection:
    """Convenience entry point returning the hammer's selection contract."""

    return LegalIRPremiseSelector(contract_telemetry=contract_telemetry).select(
        goal,
        premises,
        max_premises=max_premises,
    )


def score_legal_ir_premises(
    goal: HammerGoal | LegalIRProofObligation | Mapping[str, Any],
    premises: Sequence[HammerPremise | Mapping[str, Any] | str],
    *,
    contract_telemetry: Any = None,
) -> list[RankedLegalIRPremise]:
    """Return every premise with its score receipt in deterministic rank order."""

    return LegalIRPremiseSelector(contract_telemetry=contract_telemetry).rank(
        goal, premises
    )


select_legal_ir_premises = rank_legal_ir_premises


# A descriptive compatibility alias for callers that use ``Ranker`` naming.
LegalIRPremiseRanker = LegalIRPremiseSelector


__all__ = [
    "LEGAL_IR_PREMISE_SELECTION_SCHEMA_VERSION",
    "LegalIRPremiseKind",
    "LegalIRPremiseRanker",
    "LegalIRPremiseScore",
    "LegalIRPremiseSelector",
    "RankedLegalIRPremise",
    "rank_legal_ir_premises",
    "score_legal_ir_premises",
    "select_legal_ir_premises",
]
