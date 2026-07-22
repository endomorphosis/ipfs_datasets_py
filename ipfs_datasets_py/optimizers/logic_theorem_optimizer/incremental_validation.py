"""Changed-scope planning and concurrent validation for LegalIR candidates.

Incremental validation is an *early feedback* facility.  It maps a candidate's
changed files and typed AST scopes to the smallest known set of tests, semantic
family shards, replay cases, mutations, and proof obligations.  Merge and
rollout boundaries deliberately ignore that reduction and require the complete
frozen canary and promotion-proof catalogs.

The executor in this module has three trust properties which are easy to lose
in ad-hoc CI orchestration:

* every independent check is scheduled concurrently with the same recursively
  immutable baseline evidence;
* Codex candidates may opt into syntax, focused-preflight, expensive, and
  promotion stages so cheap failures do not consume expensive capacity;
* only explicitly transient outcomes are retried, within a per-check bound;
* absent checks and incomplete boundary gates are represented as failures, not
  silently omitted from an aggregate score.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import math
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Optional

from .legal_ir_family_evaluator import (
    LEGAL_IR_EVALUATION_FAMILIES,
    canonical_legal_ir_evaluation_family,
)


INCREMENTAL_VALIDATION_SCHEMA_VERSION: Final = "legal-ir-incremental-validation-v1"
CHANGED_SCOPE_PLAN_SCHEMA_VERSION: Final = "legal-ir-changed-scope-plan-v1"
FROZEN_BASELINE_EVIDENCE_SCHEMA_VERSION: Final = "legal-ir-frozen-baseline-evidence-v1"


DEFAULT_FOCUSED_TESTS: Final[tuple[str, ...]] = (
    "tests/unit_tests/logic/modal/test_leanstral_validation.py",
    "tests/unit/optimizers/logic_theorem_optimizer/test_incremental_validation.py",
    "tests/unit/logic/integration/test_hammer_failure_replay.py",
    "tests/unit/logic/integration/test_legal_ir_proof_feedback.py",
    "tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_family_evaluator.py",
)
DEFAULT_REPLAY_CASES: Final[tuple[str, ...]] = (
    "accepted-candidate",
    "source-copy-rejected",
    "syntax-rejected",
    "kg-rejected",
    "hammer-unproved",
    "reconstruction-failed",
    "backend-unavailable",
    "codex-repair-feedback",
)
DEFAULT_MUTATION_CASES: Final[tuple[str, ...]] = (
    "invert_modality",
    "remove_modal_cue",
    "remove_exception",
    "alter_deadline",
    "alter_scope",
    "remove_relation_endpoint",
    "unsupported_modal_system",
)
DEFAULT_PROOF_OBLIGATIONS: Final[tuple[str, ...]] = (
    "modal_operator_preserved",
    "source_provenance_preserved",
    "decompiler_round_trip",
    "exception_scope_preserved",
    "graph_has_no_dangling_edges",
    "frame_terms_preserved",
    "event_interval_preserved",
    "proof_route_is_distinct_from_proof",
)


class ValidationBoundary(str, Enum):
    """The authority boundary at which candidate evidence is consumed."""

    CANDIDATE = "candidate"
    MERGE = "merge"
    ROLLOUT = "rollout"

    @classmethod
    def coerce(cls, value: "ValidationBoundary | str") -> "ValidationBoundary":
        if isinstance(value, cls):
            return value
        normalized = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "candidate_feedback": cls.CANDIDATE,
            "pull_request": cls.MERGE,
            "pr": cls.MERGE,
            "promotion": cls.ROLLOUT,
            "deploy": cls.ROLLOUT,
        }
        if normalized in aliases:
            return aliases[normalized]
        try:
            return cls(normalized)
        except ValueError as exc:
            raise ValueError(f"unsupported validation boundary: {value!r}") from exc

    @property
    def requires_complete_promotion_gates(self) -> bool:
        return self in {self.MERGE, self.ROLLOUT}


class IncrementalValidationStage(str, Enum):
    """Cost-ordered stages used by the preflight-first validator.

    The ordinary :meth:`IncrementalCandidateValidator.validate` API retains its
    original all-check concurrency contract.  Codex worktree validation can use
    these stages to avoid starting semantic, replay, proof, or promotion work
    before the inexpensive syntax and focused-test preflight has succeeded.
    """

    SYNTAX = "syntax"
    FOCUSED_PREFLIGHT = "focused_preflight"
    EXPENSIVE = "expensive"
    PROMOTION = "promotion"


def _normalize_path(value: Any) -> str:
    path = str(value or "").strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    if not path or path.startswith("/") or ".." in path.split("/"):
        raise ValueError(f"changed path must be repository-relative: {value!r}")
    return path


def _identifiers(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        raw = (values,)
    elif isinstance(values, Sequence) and not isinstance(values, (bytes, bytearray, str)):
        raw = values
    else:
        raw = (values,)
    return tuple(sorted({str(item).strip() for item in raw if str(item).strip()}))


def _ordered_families(values: Iterable[str]) -> tuple[str, ...]:
    selected = {canonical_legal_ir_evaluation_family(item) for item in values}
    return tuple(item for item in LEGAL_IR_EVALUATION_FAMILIES if item in selected)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("validation evidence cannot contain non-finite numbers")
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_value(to_dict())
    raise TypeError(f"unsupported validation evidence type: {type(value).__name__}")


def _freeze(value: Any) -> Any:
    value = _json_value(value)
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _plain(to_dict())
    return value


def _digest(value: Any) -> str:
    encoded = json.dumps(
        _plain(value), allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class TypedASTScope:
    """One typed syntax-tree scope affected by a candidate patch.

    Callers may produce these from Python ``ast`` nodes, a language server, or
    a compiler-specific typed tree.  Only stable identifiers are retained.
    """

    path: str
    node_type: str
    qualified_name: str = ""
    symbols: tuple[str, ...] = ()
    legal_ir_families: tuple[str, ...] = ()
    focused_tests: tuple[str, ...] = ()
    replay_samples: tuple[str, ...] = ()
    mutation_cases: tuple[str, ...] = ()
    proof_obligations: tuple[str, ...] = ()
    start_line: Optional[int] = None
    end_line: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _normalize_path(self.path))
        node_type = str(self.node_type or "").strip()
        if not node_type:
            raise ValueError("typed AST scope node_type must not be empty")
        object.__setattr__(self, "node_type", node_type)
        object.__setattr__(self, "qualified_name", str(self.qualified_name or "").strip())
        object.__setattr__(self, "symbols", _identifiers(self.symbols))
        object.__setattr__(self, "legal_ir_families", _ordered_families(self.legal_ir_families))
        for name in ("focused_tests", "replay_samples", "mutation_cases", "proof_obligations"):
            object.__setattr__(self, name, _identifiers(getattr(self, name)))
        for name in ("start_line", "end_line"):
            value = getattr(self, name)
            if value is not None and int(value) < 1:
                raise ValueError(f"{name} must be positive when present")
            if value is not None:
                object.__setattr__(self, name, int(value))
        if self.start_line and self.end_line and self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")

    @classmethod
    def from_value(
        cls, value: "TypedASTScope | Mapping[str, Any] | str", *, path: str = ""
    ) -> "TypedASTScope":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(path=path, node_type="symbol", qualified_name=value)
        if not isinstance(value, Mapping):
            raise TypeError("typed AST scopes must be TypedASTScope, mapping, or symbol string")
        return cls(
            path=str(value.get("path") or value.get("file") or path),
            node_type=str(value.get("node_type") or value.get("kind") or value.get("type") or ""),
            qualified_name=str(
                value.get("qualified_name") or value.get("qualname") or value.get("name") or ""
            ),
            symbols=_identifiers(value.get("symbols") or value.get("semantic_symbols")),
            legal_ir_families=_identifiers(
                value.get("legal_ir_families")
                or value.get("semantic_families")
                or value.get("affected_ir_families")
                or value.get("semantic_family")
            ),
            focused_tests=_identifiers(value.get("focused_tests")),
            replay_samples=_identifiers(value.get("replay_samples") or value.get("replay_case_ids")),
            mutation_cases=_identifiers(value.get("mutation_cases")),
            proof_obligations=_identifiers(
                value.get("proof_obligations") or value.get("proof_obligation_ids")
            ),
            start_line=value.get("start_line") or value.get("lineno"),
            end_line=value.get("end_line") or value.get("end_lineno"),
        )

    @property
    def search_text(self) -> str:
        return " ".join((self.node_type, self.qualified_name, *self.symbols)).lower()

    def to_dict(self) -> dict[str, Any]:
        return {
            "end_line": self.end_line,
            "node_type": self.node_type,
            "path": self.path,
            "focused_tests": list(self.focused_tests),
            "legal_ir_families": list(self.legal_ir_families),
            "mutation_cases": list(self.mutation_cases),
            "proof_obligations": list(self.proof_obligations),
            "qualified_name": self.qualified_name,
            "replay_samples": list(self.replay_samples),
            "start_line": self.start_line,
            "symbols": list(self.symbols),
        }


@dataclass(frozen=True, slots=True)
class ValidationScopeCatalog:
    """The complete frozen validation universe used at promotion boundaries."""

    focused_tests: tuple[str, ...] = DEFAULT_FOCUSED_TESTS
    legal_ir_families: tuple[str, ...] = LEGAL_IR_EVALUATION_FAMILIES
    replay_samples: tuple[str, ...] = DEFAULT_REPLAY_CASES
    mutation_cases: tuple[str, ...] = DEFAULT_MUTATION_CASES
    proof_obligations: tuple[str, ...] = DEFAULT_PROOF_OBLIGATIONS

    def __post_init__(self) -> None:
        object.__setattr__(self, "focused_tests", _identifiers(self.focused_tests))
        object.__setattr__(self, "legal_ir_families", _ordered_families(self.legal_ir_families))
        object.__setattr__(self, "replay_samples", _identifiers(self.replay_samples))
        object.__setattr__(self, "mutation_cases", _identifiers(self.mutation_cases))
        object.__setattr__(self, "proof_obligations", _identifiers(self.proof_obligations))
        for name in (
            "focused_tests",
            "legal_ir_families",
            "replay_samples",
            "mutation_cases",
            "proof_obligations",
        ):
            if not getattr(self, name):
                raise ValueError(f"validation catalog {name} must not be empty")

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "focused_tests": list(self.focused_tests),
            "legal_ir_families": list(self.legal_ir_families),
            "mutation_cases": list(self.mutation_cases),
            "proof_obligations": list(self.proof_obligations),
            "replay_samples": list(self.replay_samples),
        }


@dataclass(frozen=True, slots=True)
class ChangedScopeRule:
    """Declarative file/AST mapping rule."""

    rule_id: str
    path_patterns: tuple[str, ...] = ()
    ast_terms: tuple[str, ...] = ()
    focused_tests: tuple[str, ...] = ()
    legal_ir_families: tuple[str, ...] = ()
    replay_samples: tuple[str, ...] = ()
    mutation_cases: tuple[str, ...] = ()
    proof_obligations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not str(self.rule_id or "").strip():
            raise ValueError("scope rule_id must not be empty")
        for name in (
            "path_patterns", "ast_terms", "focused_tests", "replay_samples",
            "mutation_cases", "proof_obligations",
        ):
            object.__setattr__(self, name, _identifiers(getattr(self, name)))
        object.__setattr__(self, "legal_ir_families", _ordered_families(self.legal_ir_families))

    def matches_path(self, path: str) -> bool:
        return any(fnmatch.fnmatchcase(path, pattern) for pattern in self.path_patterns)

    def matches_ast(self, scope: TypedASTScope) -> bool:
        return bool(self.ast_terms) and any(term.lower() in scope.search_text for term in self.ast_terms)


def _default_scope_rules() -> tuple[ChangedScopeRule, ...]:
    modal_test = "tests/unit_tests/logic/modal/test_leanstral_validation.py"
    incremental_test = "tests/unit/optimizers/logic_theorem_optimizer/test_incremental_validation.py"
    family_test = "tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_family_evaluator.py"
    replay_test = "tests/unit/logic/integration/test_hammer_failure_replay.py"
    proof_test = "tests/unit/logic/integration/test_legal_ir_proof_feedback.py"
    return (
        ChangedScopeRule(
            "modal_compiler", ("ipfs_datasets_py/logic/modal/compiler*.py", "ipfs_datasets_py/logic/modal/codec.py"),
            focused_tests=(modal_test,), legal_ir_families=("deontic", "frame_logic", "temporal", "provenance"),
            replay_samples=("accepted-candidate", "syntax-rejected"),
            mutation_cases=("invert_modality", "remove_modal_cue", "alter_scope"),
            proof_obligations=("modal_operator_preserved", "source_provenance_preserved"),
        ),
        ChangedScopeRule(
            "decompiler", ("ipfs_datasets_py/logic/modal/decompiler*.py",),
            ast_terms=("decompil", "decode", "round_trip", "reconstruct"), focused_tests=(modal_test,),
            legal_ir_families=("decompiler", "deontic", "temporal", "provenance"),
            replay_samples=("source-copy-rejected", "reconstruction-failed"),
            mutation_cases=("invert_modality", "remove_exception", "alter_deadline"),
            proof_obligations=("decompiler_round_trip", "exception_scope_preserved", "source_provenance_preserved"),
        ),
        ChangedScopeRule(
            "deontic", ("ipfs_datasets_py/logic/deontic/**",),
            ast_terms=("obligation", "permission", "prohibition", "deontic"),
            focused_tests=(modal_test, family_test, replay_test),
            legal_ir_families=("deontic", "decompiler", "provenance"),
            replay_samples=("accepted-candidate", "syntax-rejected"),
            mutation_cases=("invert_modality", "remove_exception"),
            proof_obligations=("modal_operator_preserved", "exception_scope_preserved"),
        ),
        ChangedScopeRule(
            "knowledge_graph", ("ipfs_datasets_py/logic/modal/kg_bridge.py", "ipfs_datasets_py/logic/knowledge_graphs/**", "ipfs_datasets_py/logic/flogic/**"),
            ast_terms=("graph", "triple", "flogic", "frame"), focused_tests=(modal_test, family_test),
            legal_ir_families=("knowledge_graphs", "frame_logic", "provenance"), replay_samples=("kg-rejected",),
            mutation_cases=("remove_relation_endpoint", "alter_scope"),
            proof_obligations=("graph_has_no_dangling_edges", "frame_terms_preserved", "source_provenance_preserved"),
        ),
        ChangedScopeRule(
            "tdfol_temporal", ("ipfs_datasets_py/logic/TDFOL/**", "ipfs_datasets_py/logic/bridge/fol_tdfol.py"),
            ast_terms=("tdfol", "deadline", "temporal", "quantif"), focused_tests=(family_test, replay_test),
            legal_ir_families=("tdfol", "temporal", "external_provers", "provenance"),
            replay_samples=("hammer-unproved", "codex-repair-feedback"), mutation_cases=("alter_deadline", "unsupported_modal_system"),
            proof_obligations=("proof_route_is_distinct_from_proof", "source_provenance_preserved"),
        ),
        ChangedScopeRule(
            "cec", ("ipfs_datasets_py/logic/CEC/**", "ipfs_datasets_py/logic/bridge/cec_dcec.py"),
            ast_terms=("event", "cec", "lifecycle", "interval"), focused_tests=(family_test, replay_test),
            legal_ir_families=("cec", "temporal", "provenance"), replay_samples=("reconstruction-failed",),
            mutation_cases=("alter_deadline",), proof_obligations=("event_interval_preserved", "source_provenance_preserved"),
        ),
        ChangedScopeRule(
            "external_provers", ("ipfs_datasets_py/logic/external_provers/**", "ipfs_datasets_py/optimizers/logic_theorem_optimizer/prover*.py"),
            ast_terms=("proof_route", "backend", "prover", "kernel"), focused_tests=(family_test, replay_test, proof_test),
            legal_ir_families=("external_provers", "tdfol"), replay_samples=("backend-unavailable", "hammer-unproved"),
            mutation_cases=("unsupported_modal_system",), proof_obligations=("proof_route_is_distinct_from_proof",),
        ),
        ChangedScopeRule(
            "proof_feedback", ("ipfs_datasets_py/logic/integration/reasoning/legal_ir_*proof*.py", "ipfs_datasets_py/logic/integration/reasoning/legal_ir_*obligation*.py"),
            ast_terms=("obligation", "premise", "receipt", "counterexample"), focused_tests=(proof_test, replay_test),
            legal_ir_families=LEGAL_IR_EVALUATION_FAMILIES, replay_samples=("accepted-candidate", "hammer-unproved", "reconstruction-failed"),
            proof_obligations=DEFAULT_PROOF_OBLIGATIONS,
        ),
        ChangedScopeRule(
            "family_runtime", (
                "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_family_evaluator.py",
                "ipfs_datasets_py/optimizers/logic_theorem_optimizer/incremental_validation.py",
            ),
            focused_tests=(family_test, incremental_test), legal_ir_families=LEGAL_IR_EVALUATION_FAMILIES,
            replay_samples=DEFAULT_REPLAY_CASES, mutation_cases=DEFAULT_MUTATION_CASES,
            proof_obligations=DEFAULT_PROOF_OBLIGATIONS,
        ),
        ChangedScopeRule(
            "representation_runtime", ("ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py",),
            ast_terms=("autoencoder", "loss", "embedding", "auxiliary_head"),
            focused_tests=(family_test, proof_test), legal_ir_families=LEGAL_IR_EVALUATION_FAMILIES,
            replay_samples=("accepted-candidate", "source-copy-rejected", "codex-repair-feedback"),
            mutation_cases=("invert_modality", "remove_modal_cue", "alter_scope"),
            proof_obligations=("modal_operator_preserved", "source_provenance_preserved", "decompiler_round_trip"),
        ),
        ChangedScopeRule(
            "provenance", (), ast_terms=("provenance", "source_span", "citation", "receipt"),
            focused_tests=(modal_test, proof_test), legal_ir_families=("provenance",), replay_samples=("source-copy-rejected",),
            proof_obligations=("source_provenance_preserved",),
        ),
        ChangedScopeRule(
            "exception", (), ast_terms=("exception", "unless", "prohibition", "deontic"),
            focused_tests=(modal_test,), legal_ir_families=("deontic", "decompiler"), replay_samples=("accepted-candidate",),
            mutation_cases=("invert_modality", "remove_exception"), proof_obligations=("modal_operator_preserved", "exception_scope_preserved"),
        ),
        ChangedScopeRule(
            "tests", ("tests/**/test_*.py",), focused_tests=(),
        ),
    )


DEFAULT_CHANGED_SCOPE_RULES: Final[tuple[ChangedScopeRule, ...]] = _default_scope_rules()


@dataclass(frozen=True, slots=True)
class ChangedScopeValidationPlan:
    """Deterministic validation selection for one candidate and boundary."""

    boundary: ValidationBoundary
    changed_files: tuple[str, ...]
    typed_ast_scopes: tuple[TypedASTScope, ...]
    focused_tests: tuple[str, ...]
    legal_ir_families: tuple[str, ...]
    replay_samples: tuple[str, ...]
    mutation_cases: tuple[str, ...]
    proof_obligations: tuple[str, ...]
    matched_rules: tuple[str, ...] = ()
    conservative_fallback: bool = False
    complete_frozen_canary_required: bool = False
    complete_promotion_proofs_required: bool = False
    schema_version: str = CHANGED_SCOPE_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "boundary", ValidationBoundary.coerce(self.boundary))
        object.__setattr__(self, "changed_files", tuple(sorted({_normalize_path(item) for item in self.changed_files})))
        object.__setattr__(self, "typed_ast_scopes", tuple(self.typed_ast_scopes))
        for name in ("focused_tests", "replay_samples", "mutation_cases", "proof_obligations", "matched_rules"):
            object.__setattr__(self, name, _identifiers(getattr(self, name)))
        object.__setattr__(self, "legal_ir_families", _ordered_families(self.legal_ir_families))
        if self.boundary.requires_complete_promotion_gates and not (
            self.complete_frozen_canary_required and self.complete_promotion_proofs_required
        ):
            raise ValueError("merge and rollout plans cannot disable complete promotion gates")

    @property
    def is_incremental(self) -> bool:
        return self.boundary is ValidationBoundary.CANDIDATE and not self.conservative_fallback

    @property
    def required_check_ids(self) -> tuple[str, ...]:
        values = ["syntax"]
        values.extend(f"test:{item}" for item in self.focused_tests)
        values.extend(f"family:{item}" for item in self.legal_ir_families)
        values.extend(f"replay:{item}" for item in self.replay_samples)
        values.extend(f"mutation:{item}" for item in self.mutation_cases)
        values.extend(f"proof:{item}" for item in self.proof_obligations)
        if self.complete_frozen_canary_required:
            values.append("frozen_canary")
        if self.complete_promotion_proofs_required:
            values.append("promotion_proof_set")
        return tuple(dict.fromkeys(values))

    @property
    def plan_id(self) -> str:
        return f"changed-scope-{_digest(self.to_dict(include_plan_id=False))[:20]}"

    def to_dict(self, *, include_plan_id: bool = True) -> dict[str, Any]:
        value = {
            "boundary": self.boundary.value,
            "changed_files": list(self.changed_files),
            "complete_frozen_canary_required": self.complete_frozen_canary_required,
            "complete_promotion_proofs_required": self.complete_promotion_proofs_required,
            "conservative_fallback": self.conservative_fallback,
            "focused_tests": list(self.focused_tests),
            "legal_ir_families": list(self.legal_ir_families),
            "matched_rules": list(self.matched_rules),
            "mutation_cases": list(self.mutation_cases),
            "proof_obligations": list(self.proof_obligations),
            "replay_samples": list(self.replay_samples),
            "required_check_ids": list(self.required_check_ids),
            "schema_version": self.schema_version,
            "typed_ast_scopes": [item.to_dict() for item in self.typed_ast_scopes],
        }
        if include_plan_id:
            value["plan_id"] = self.plan_id
        return value


class ChangedScopeValidationPlanner:
    """Map changed paths and typed symbols to an auditable validation plan."""

    def __init__(
        self,
        *,
        catalog: Optional[ValidationScopeCatalog] = None,
        rules: Sequence[ChangedScopeRule] = DEFAULT_CHANGED_SCOPE_RULES,
    ) -> None:
        self.catalog = catalog or ValidationScopeCatalog()
        self.rules = tuple(rules)
        if not self.rules:
            raise ValueError("at least one changed-scope rule is required")
        ids = [rule.rule_id for rule in self.rules]
        if len(set(ids)) != len(ids):
            raise ValueError("changed-scope rule ids must be unique")

    def plan(
        self,
        changed_files: Sequence[str],
        *,
        typed_ast_scopes: Sequence[TypedASTScope | Mapping[str, Any] | str] = (),
        boundary: ValidationBoundary | str = ValidationBoundary.CANDIDATE,
    ) -> ChangedScopeValidationPlan:
        selected_boundary = ValidationBoundary.coerce(boundary)
        paths = tuple(sorted({_normalize_path(item) for item in changed_files}))
        original_paths = set(paths)
        scopes: list[TypedASTScope] = []
        for value in typed_ast_scopes:
            default_path = paths[0] if paths else ""
            scopes.append(TypedASTScope.from_value(value, path=default_path))

        # A promotion boundary is intentionally not reducible.  This is done
        # before matching so no future rule can accidentally narrow the gate.
        if selected_boundary.requires_complete_promotion_gates:
            return ChangedScopeValidationPlan(
                boundary=selected_boundary,
                changed_files=paths,
                typed_ast_scopes=tuple(scopes),
                focused_tests=self.catalog.focused_tests,
                legal_ir_families=self.catalog.legal_ir_families,
                replay_samples=self.catalog.replay_samples,
                mutation_cases=self.catalog.mutation_cases,
                proof_obligations=self.catalog.proof_obligations,
                matched_rules=("complete_promotion_boundary",),
                complete_frozen_canary_required=True,
                complete_promotion_proofs_required=True,
            )

        selected: dict[str, set[str]] = {
            "focused_tests": set(), "legal_ir_families": set(), "replay_samples": set(),
            "mutation_cases": set(), "proof_obligations": set(),
        }
        for scope in scopes:
            for name in selected:
                selected[name].update(getattr(scope, name))
        matched: set[str] = set()
        unmatched_paths = set(paths)
        for rule in self.rules:
            path_matches = {path for path in paths if rule.matches_path(path)}
            ast_matches = tuple(scope for scope in scopes if rule.matches_ast(scope))
            if not path_matches and not ast_matches:
                continue
            matched.add(rule.rule_id)
            unmatched_paths.difference_update(path_matches)
            for name in selected:
                selected[name].update(getattr(rule, name))
            if rule.rule_id == "tests":
                selected["focused_tests"].update(path_matches)

        # A typed scope always maps its own file, even if it was omitted from
        # changed_files by a caller consuming a language-server notification.
        scope_paths = {scope.path for scope in scopes}
        paths = tuple(sorted(set(paths) | scope_paths))
        unmatched_paths.update(scope_paths - original_paths)
        for rule in self.rules:
            scope_path_matches = {path for path in scope_paths if rule.matches_path(path)}
            if scope_path_matches:
                matched.add(rule.rule_id)
                unmatched_paths.difference_update(scope_path_matches)
                for name in selected:
                    selected[name].update(getattr(rule, name))

        conservative = not paths or bool(unmatched_paths) or not matched
        if conservative:
            selected = {
                "focused_tests": set(self.catalog.focused_tests),
                "legal_ir_families": set(self.catalog.legal_ir_families),
                "replay_samples": set(self.catalog.replay_samples),
                "mutation_cases": set(self.catalog.mutation_cases),
                "proof_obligations": set(self.catalog.proof_obligations),
            }
            matched.add("conservative_fallback")
        return ChangedScopeValidationPlan(
            boundary=selected_boundary,
            changed_files=paths,
            typed_ast_scopes=tuple(scopes),
            focused_tests=tuple(selected["focused_tests"]),
            legal_ir_families=tuple(selected["legal_ir_families"]),
            replay_samples=tuple(selected["replay_samples"]),
            mutation_cases=tuple(selected["mutation_cases"]),
            proof_obligations=tuple(selected["proof_obligations"]),
            matched_rules=tuple(matched),
            conservative_fallback=conservative,
        )


def plan_incremental_validation(
    changed_files: Sequence[str],
    *,
    typed_ast_scopes: Sequence[TypedASTScope | Mapping[str, Any] | str] = (),
    boundary: ValidationBoundary | str = ValidationBoundary.CANDIDATE,
    catalog: Optional[ValidationScopeCatalog] = None,
    rules: Sequence[ChangedScopeRule] = DEFAULT_CHANGED_SCOPE_RULES,
) -> ChangedScopeValidationPlan:
    """Convenience function for deterministic changed-scope mapping."""

    return ChangedScopeValidationPlanner(catalog=catalog, rules=rules).plan(
        changed_files, typed_ast_scopes=typed_ast_scopes, boundary=boundary
    )


# Descriptive aliases used by scheduler and validation call sites.
map_changed_scope = plan_incremental_validation
build_incremental_validation_plan = plan_incremental_validation


@dataclass(frozen=True, slots=True)
class FrozenBaselineEvidence:
    """Content-addressed, recursively immutable evidence shared by checks."""

    version: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    frozen_canary_ids: tuple[str, ...] = ()
    promotion_proof_ids: tuple[str, ...] = ()
    schema_version: str = FROZEN_BASELINE_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not str(self.version or "").strip():
            raise ValueError("baseline evidence version must not be empty")
        if self.schema_version != FROZEN_BASELINE_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("baseline evidence schema version is stale")
        object.__setattr__(self, "version", str(self.version).strip())
        object.__setattr__(self, "payload", _freeze(self.payload))
        object.__setattr__(self, "frozen_canary_ids", _identifiers(self.frozen_canary_ids))
        object.__setattr__(self, "promotion_proof_ids", _identifiers(self.promotion_proof_ids))

    @property
    def evidence_id(self) -> str:
        return f"baseline-{_digest(self.to_dict(include_evidence_id=False))}"

    def to_dict(self, *, include_evidence_id: bool = True) -> dict[str, Any]:
        value = {
            "frozen_canary_ids": list(self.frozen_canary_ids),
            "payload": _plain(self.payload),
            "promotion_proof_ids": list(self.promotion_proof_ids),
            "schema_version": self.schema_version,
            "version": self.version,
        }
        if include_evidence_id:
            value["evidence_id"] = self.evidence_id
        return value


class TransientValidationError(RuntimeError):
    """Explicitly retryable infrastructure or transport failure."""


ValidationCallback = Callable[["IncrementalValidationRequest"], Any]


@dataclass(frozen=True, slots=True)
class IncrementalValidationCheck:
    """One independently runnable check selected by a plan."""

    check_id: str
    callback: ValidationCallback = field(compare=False, repr=False)
    description: str = ""

    def __post_init__(self) -> None:
        if not str(self.check_id or "").strip():
            raise ValueError("incremental check_id must not be empty")
        if not callable(self.callback):
            raise TypeError("incremental validation callback must be callable")


@dataclass(frozen=True, slots=True)
class IncrementalValidationRequest:
    """Immutable request passed to a validation callback."""

    check_id: str
    plan: ChangedScopeValidationPlan
    baseline_evidence: Optional[FrozenBaselineEvidence]
    attempt: int


@dataclass(frozen=True, slots=True)
class IncrementalValidationResult:
    """Terminal evidence for one required check."""

    check_id: str
    accepted: bool
    attempts: int = 1
    transient_failures: int = 0
    error: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)
    baseline_evidence_id: str = ""
    started_at_monotonic: float = 0.0
    elapsed_seconds: float = 0.0
    worker_thread_id: int = 0
    executed: bool = True

    def __post_init__(self) -> None:
        if self.executed and self.attempts < 1:
            raise ValueError("an executed check must include an initial attempt")
        if not self.executed and self.attempts != 0:
            raise ValueError("a skipped check cannot report execution attempts")
        if self.transient_failures < 0:
            raise ValueError("transient_failures must be non-negative")
        if not self.executed and (self.accepted or self.transient_failures):
            raise ValueError("a skipped check cannot be accepted or transiently failed")
        if self.accepted and self.transient_failures >= self.attempts:
            raise ValueError("an accepted result must end with a non-transient attempt")
        if not math.isfinite(float(self.elapsed_seconds)) or self.elapsed_seconds < 0:
            raise ValueError("elapsed_seconds must be finite and non-negative")
        object.__setattr__(self, "evidence", _freeze(self.evidence))

    @property
    def status(self) -> str:
        if not self.executed:
            return "skipped"
        return "passed" if self.accepted else "failed"

    def to_dict(self) -> dict[str, Any]:
        value = {
            "accepted": self.accepted,
            "attempts": self.attempts,
            "baseline_evidence_id": self.baseline_evidence_id,
            "check_id": self.check_id,
            "elapsed_seconds": round(float(self.elapsed_seconds), 9),
            "error": self.error,
            "evidence": _plain(self.evidence),
            "status": self.status,
            "transient_failures": self.transient_failures,
            "worker_thread_id": self.worker_thread_id,
        }
        # Preserve the serialized shape (and therefore report ids) of reports
        # produced by the original concurrent API.  The extra marker is emitted
        # only for the new, explicitly skipped staged results.
        if not self.executed:
            value["executed"] = False
        return value


@dataclass(frozen=True, slots=True)
class IncrementalValidationReport:
    """Complete fail-closed aggregate for a changed-scope validation run."""

    plan: ChangedScopeValidationPlan
    results: Mapping[str, IncrementalValidationResult]
    baseline_evidence_id: str = ""
    schema_version: str = INCREMENTAL_VALIDATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        frozen = MappingProxyType(dict(sorted(self.results.items())))
        object.__setattr__(self, "results", frozen)

    @property
    def missing_check_ids(self) -> tuple[str, ...]:
        return tuple(item for item in self.plan.required_check_ids if item not in self.results)

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(
            check_id for check_id in self.plan.required_check_ids
            if check_id in self.results and not self.results[check_id].accepted
        )

    @property
    def skipped_check_ids(self) -> tuple[str, ...]:
        """Required checks deliberately not started after an earlier gate failed."""

        return tuple(
            check_id for check_id in self.plan.required_check_ids
            if check_id in self.results and not self.results[check_id].executed
        )

    @property
    def transient_failure_check_ids(self) -> tuple[str, ...]:
        return tuple(
            check_id
            for check_id in self.plan.required_check_ids
            if check_id in self.results and self.results[check_id].transient_failures > 0
        )

    @property
    def transient_rescued_check_ids(self) -> tuple[str, ...]:
        return tuple(
            check_id
            for check_id in self.transient_failure_check_ids
            if self.results[check_id].accepted
        )

    @property
    def transient_unresolved_check_ids(self) -> tuple[str, ...]:
        return tuple(
            check_id
            for check_id in self.transient_failure_check_ids
            if not self.results[check_id].accepted
        )

    @property
    def semantic_failure_check_ids(self) -> tuple[str, ...]:
        non_semantic_errors = {
            "required_check_not_registered",
            "registered_check_identity_mismatch",
        }
        values: list[str] = []
        for check_id in self.failed_check_ids:
            result = self.results[check_id]
            if not result.executed:
                continue
            if result.transient_failures > 0:
                continue
            if result.error in non_semantic_errors or result.error.startswith("executor_error:"):
                continue
            values.append(check_id)
        return tuple(values)

    @property
    def semantic_statistics_update_allowed(self) -> bool:
        return not self.transient_unresolved_check_ids and not (
            set(self.failed_check_ids)
            - set(self.semantic_failure_check_ids)
            - set(self.skipped_check_ids)
        )

    @property
    def semantic_statistics_delta(self) -> Mapping[str, Any]:
        value = {
            "accepted": self.accepted,
            "accepted_check_count": sum(
                1 for check_id in self.plan.required_check_ids
                if check_id in self.results and self.results[check_id].accepted
            ),
            "deterministic_semantic_failure_count": len(self.semantic_failure_check_ids),
            "poison_semantic_statistics": False,
            "semantic_failure_check_ids": list(self.semantic_failure_check_ids),
            "transient_rescued_check_count": len(self.transient_rescued_check_ids),
            "transient_rescued_check_ids": list(self.transient_rescued_check_ids),
            "transient_unresolved_check_count": len(self.transient_unresolved_check_ids),
            "transient_unresolved_check_ids": list(self.transient_unresolved_check_ids),
            "update_allowed": self.semantic_statistics_update_allowed,
        }
        if self.skipped_check_ids:
            value["skipped_check_count"] = len(self.skipped_check_ids)
            value["skipped_check_ids"] = list(self.skipped_check_ids)
        return MappingProxyType(value)

    @property
    def promotion_gates_complete(self) -> bool:
        if not self.plan.boundary.requires_complete_promotion_gates:
            return True
        return all(
            check_id in self.results and self.results[check_id].accepted
            for check_id in ("frozen_canary", "promotion_proof_set")
        )

    @property
    def accepted(self) -> bool:
        return not self.missing_check_ids and not self.failed_check_ids and self.promotion_gates_complete

    @property
    def merge_allowed(self) -> bool:
        """Whether this report itself authorizes crossing the merge boundary."""

        return self.plan.boundary is ValidationBoundary.MERGE and self.accepted

    @property
    def transient_requeue_required(self) -> bool:
        """Whether unresolved infrastructure failure should requeue this work."""

        return bool(self.transient_unresolved_check_ids)

    @property
    def report_id(self) -> str:
        return f"incremental-validation-{_digest(self.to_dict(include_report_id=False))[:20]}"

    def to_dict(self, *, include_report_id: bool = True) -> dict[str, Any]:
        value = {
            "accepted": self.accepted,
            "baseline_evidence_id": self.baseline_evidence_id,
            "failed_check_ids": list(self.failed_check_ids),
            "missing_check_ids": list(self.missing_check_ids),
            "plan": self.plan.to_dict(),
            "promotion_gates_complete": self.promotion_gates_complete,
            "results": {key: result.to_dict() for key, result in self.results.items()},
            "schema_version": self.schema_version,
            "semantic_statistics_delta": _plain(self.semantic_statistics_delta),
            "semantic_statistics_update_allowed": self.semantic_statistics_update_allowed,
            "transient_failure_check_ids": list(self.transient_failure_check_ids),
            "transient_rescued_check_ids": list(self.transient_rescued_check_ids),
            "transient_unresolved_check_ids": list(self.transient_unresolved_check_ids),
        }
        if self.skipped_check_ids:
            value["skipped_check_ids"] = list(self.skipped_check_ids)
        if include_report_id:
            value["report_id"] = self.report_id
        return value


@dataclass(frozen=True, slots=True)
class IncrementalValidationStageResult:
    """Auditable outcome for one cost-ordered validation stage."""

    stage: IncrementalValidationStage
    check_ids: tuple[str, ...]
    results: Mapping[str, IncrementalValidationResult]
    elapsed_seconds: float = 0.0
    skip_reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.stage, IncrementalValidationStage):
            object.__setattr__(self, "stage", IncrementalValidationStage(str(self.stage)))
        check_ids = tuple(dict.fromkeys(str(item).strip() for item in self.check_ids))
        if any(not item for item in check_ids):
            raise ValueError("stage check ids must be non-empty")
        if set(check_ids) != set(self.results):
            raise ValueError("stage results must cover exactly the stage check ids")
        elapsed = float(self.elapsed_seconds)
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("stage elapsed_seconds must be finite and non-negative")
        frozen_results = MappingProxyType(
            {check_id: self.results[check_id] for check_id in check_ids}
        )
        object.__setattr__(self, "check_ids", check_ids)
        object.__setattr__(self, "results", frozen_results)
        object.__setattr__(self, "elapsed_seconds", elapsed)
        object.__setattr__(self, "skip_reason", str(self.skip_reason or "").strip())

    @property
    def executed_check_ids(self) -> tuple[str, ...]:
        return tuple(
            check_id for check_id in self.check_ids if self.results[check_id].executed
        )

    @property
    def skipped_check_ids(self) -> tuple[str, ...]:
        return tuple(
            check_id for check_id in self.check_ids if not self.results[check_id].executed
        )

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(
            check_id
            for check_id in self.executed_check_ids
            if not self.results[check_id].accepted
        )

    @property
    def accepted(self) -> bool:
        # An empty stage is not required and therefore cannot block the run.
        return not self.skipped_check_ids and not self.failed_check_ids

    @property
    def status(self) -> str:
        if not self.check_ids:
            return "not_required"
        if self.skipped_check_ids:
            return "skipped"
        return "passed" if self.accepted else "failed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "check_ids": list(self.check_ids),
            "elapsed_seconds": round(self.elapsed_seconds, 9),
            "executed_check_ids": list(self.executed_check_ids),
            "failed_check_ids": list(self.failed_check_ids),
            "results": {key: value.to_dict() for key, value in self.results.items()},
            "skip_reason": self.skip_reason,
            "skipped_check_ids": list(self.skipped_check_ids),
            "stage": self.stage.value,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class StagedIncrementalValidationReport:
    """Preflight-first report retaining the ordinary aggregate contract.

    ``report`` is a normal :class:`IncrementalValidationReport`, so existing
    merge and statistics consumers can continue to use the established
    fail-closed properties.  ``stages`` adds execution-order and skip evidence.
    """

    report: IncrementalValidationReport
    stages: tuple[IncrementalValidationStageResult, ...]

    def __post_init__(self) -> None:
        expected = tuple(IncrementalValidationStage)
        stages = tuple(self.stages)
        if tuple(item.stage for item in stages) != expected:
            raise ValueError("staged validation results must use canonical stage order")
        covered = tuple(check_id for stage in stages for check_id in stage.check_ids)
        if len(covered) != len(set(covered)):
            raise ValueError("a validation check cannot belong to multiple stages")
        if set(covered) != set(self.report.plan.required_check_ids):
            raise ValueError("stages must cover every required validation check")
        object.__setattr__(self, "stages", stages)

    @property
    def plan(self) -> ChangedScopeValidationPlan:
        return self.report.plan

    @property
    def aggregate_report(self) -> IncrementalValidationReport:
        """Descriptive alias for consumers that distinguish stage and aggregate data."""

        return self.report

    @property
    def results(self) -> Mapping[str, IncrementalValidationResult]:
        return self.report.results

    @property
    def accepted(self) -> bool:
        return self.report.accepted

    @property
    def merge_allowed(self) -> bool:
        return self.report.merge_allowed

    @property
    def semantic_statistics_update_allowed(self) -> bool:
        return self.report.semantic_statistics_update_allowed

    @property
    def semantic_statistics_delta(self) -> Mapping[str, Any]:
        return self.report.semantic_statistics_delta

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return self.report.failed_check_ids

    @property
    def semantic_failure_check_ids(self) -> tuple[str, ...]:
        return self.report.semantic_failure_check_ids

    @property
    def transient_rescued_check_ids(self) -> tuple[str, ...]:
        return self.report.transient_rescued_check_ids

    @property
    def transient_requeue_required(self) -> bool:
        return self.report.transient_requeue_required

    @property
    def transient_unresolved_check_ids(self) -> tuple[str, ...]:
        return self.report.transient_unresolved_check_ids

    @property
    def skipped_check_ids(self) -> tuple[str, ...]:
        return self.report.skipped_check_ids

    @property
    def preflight_accepted(self) -> bool:
        return all(
            stage.accepted
            for stage in self.stages
            if stage.stage in {
                IncrementalValidationStage.SYNTAX,
                IncrementalValidationStage.FOCUSED_PREFLIGHT,
            }
        )

    @property
    def preflight_failed_check_ids(self) -> tuple[str, ...]:
        return tuple(
            check_id
            for stage in self.stages
            if stage.stage in {
                IncrementalValidationStage.SYNTAX,
                IncrementalValidationStage.FOCUSED_PREFLIGHT,
            }
            for check_id in stage.failed_check_ids
        )

    @property
    def stage_results(self) -> Mapping[str, IncrementalValidationStageResult]:
        return MappingProxyType({stage.stage.value: stage for stage in self.stages})

    @property
    def expensive_validation_started(self) -> bool:
        return any(
            stage.executed_check_ids
            for stage in self.stages
            if stage.stage in {
                IncrementalValidationStage.EXPENSIVE,
                IncrementalValidationStage.PROMOTION,
            }
        )

    @property
    def report_id(self) -> str:
        return f"staged-incremental-validation-{_digest(self.to_dict(include_report_id=False))[:20]}"

    def stage(self, value: IncrementalValidationStage | str) -> IncrementalValidationStageResult:
        selected = value if isinstance(value, IncrementalValidationStage) else IncrementalValidationStage(value)
        return next(item for item in self.stages if item.stage is selected)

    def to_dict(self, *, include_report_id: bool = True) -> dict[str, Any]:
        value = {
            "accepted": self.accepted,
            "expensive_validation_started": self.expensive_validation_started,
            "merge_allowed": self.merge_allowed,
            "preflight_accepted": self.preflight_accepted,
            "report": self.report.to_dict(),
            "semantic_statistics_update_allowed": self.semantic_statistics_update_allowed,
            "skipped_check_ids": list(self.skipped_check_ids),
            "stages": [stage.to_dict() for stage in self.stages],
            "transient_requeue_required": self.transient_requeue_required,
        }
        if include_report_id:
            value["report_id"] = self.report_id
        return value


class IncrementalCandidateValidator:
    """Run the checks selected by a changed-scope plan concurrently."""

    def __init__(self, *, max_workers: int = 8, max_transient_retries: int = 1) -> None:
        if int(max_workers) < 1:
            raise ValueError("max_workers must be at least one")
        if int(max_transient_retries) < 0:
            raise ValueError("max_transient_retries must be non-negative")
        self.max_workers = int(max_workers)
        self.max_transient_retries = int(max_transient_retries)
        self._lock = threading.Lock()
        self._counters: Counter[str] = Counter()

    def _record(self, **increments: int) -> None:
        with self._lock:
            self._counters.update(increments)

    @staticmethod
    def _normalize_checks(
        checks: Mapping[str, ValidationCallback | IncrementalValidationCheck]
        | Sequence[IncrementalValidationCheck],
    ) -> dict[str, IncrementalValidationCheck]:
        if isinstance(checks, Mapping):
            return {
                str(check_id): value
                if isinstance(value, IncrementalValidationCheck)
                else IncrementalValidationCheck(str(check_id), value)
                for check_id, value in checks.items()
            }
        items = tuple(checks)
        normalized = {item.check_id: item for item in items}
        if len(normalized) != len(items):
            raise ValueError("incremental validation check ids must be unique")
        return normalized

    @staticmethod
    def _normalize_callback_result(check_id: str, value: Any) -> tuple[bool, bool, str, Mapping[str, Any]]:
        if isinstance(value, IncrementalValidationResult):
            if value.check_id != check_id:
                return False, False, "result_identity_mismatch", {}
            return value.accepted, False, value.error, value.evidence
        if isinstance(value, bool):
            return value, False, "" if value else "deterministic_check_failed", {}
        if value is None:
            return True, False, "", {}
        if isinstance(value, Mapping):
            data = dict(value)
            accepted = bool(data.pop("accepted", data.pop("passed", False)))
            # ``retryable`` alone is intentionally insufficient: deterministic
            # validation failures must not be relabelled as infrastructure
            # incidents merely to spend more candidate budget.
            transient = bool(data.pop("transient", False))
            error = str(data.pop("error", data.pop("reason", "")) or "")
            return accepted, transient and not accepted, error, data
        return False, False, f"invalid_check_result:{type(value).__name__}", {}

    def _execute(
        self,
        check: IncrementalValidationCheck,
        plan: ChangedScopeValidationPlan,
        baseline: Optional[FrozenBaselineEvidence],
    ) -> IncrementalValidationResult:
        started = time.monotonic()
        transient_failures = 0
        baseline_id = baseline.evidence_id if baseline is not None else ""
        terminal_error = ""
        terminal_evidence: Mapping[str, Any] = {}
        for attempt in range(1, self.max_transient_retries + 2):
            self._record(check_attempts=1)
            request = IncrementalValidationRequest(check.check_id, plan, baseline, attempt)
            try:
                value = check.callback(request)
                accepted, transient, error, evidence = self._normalize_callback_result(check.check_id, value)
            except (TransientValidationError, TimeoutError, ConnectionError) as exc:
                accepted, transient = False, True
                error = f"{exc.__class__.__name__}: {exc}"
                evidence = {}
            except Exception as exc:  # deterministic/programming failures are never retried
                accepted, transient = False, False
                error = f"{exc.__class__.__name__}: {exc}"
                evidence = {}
            terminal_error, terminal_evidence = error, evidence
            if accepted:
                self._record(checks_passed=1)
                return IncrementalValidationResult(
                    check_id=check.check_id, accepted=True, attempts=attempt,
                    transient_failures=transient_failures, evidence=evidence,
                    baseline_evidence_id=baseline_id, started_at_monotonic=started,
                    elapsed_seconds=time.monotonic() - started,
                    worker_thread_id=threading.get_ident(),
                )
            if not transient or attempt > self.max_transient_retries:
                self._record(checks_failed=1, retry_budget_exhausted=int(transient))
                return IncrementalValidationResult(
                    check_id=check.check_id, accepted=False, attempts=attempt,
                    transient_failures=transient_failures + int(transient), error=error,
                    evidence=evidence, baseline_evidence_id=baseline_id,
                    started_at_monotonic=started, elapsed_seconds=time.monotonic() - started,
                    worker_thread_id=threading.get_ident(),
                )
            transient_failures += 1
            self._record(transient_retries=1)
        raise AssertionError(f"unreachable validation retry state: {terminal_error} {terminal_evidence}")

    def _execute_stage(
        self,
        *,
        stage: IncrementalValidationStage,
        check_ids: tuple[str, ...],
        normalized: Mapping[str, IncrementalValidationCheck],
        plan: ChangedScopeValidationPlan,
        baseline: Optional[FrozenBaselineEvidence],
    ) -> IncrementalValidationStageResult:
        started = time.monotonic()
        baseline_id = baseline.evidence_id if baseline else ""
        selected: dict[str, IncrementalValidationCheck] = {}
        results: dict[str, IncrementalValidationResult] = {}
        for check_id in check_ids:
            check = normalized.get(check_id)
            if check is None:
                results[check_id] = IncrementalValidationResult(
                    check_id=check_id,
                    accepted=False,
                    error="required_check_not_registered",
                    baseline_evidence_id=baseline_id,
                )
            elif check.check_id != check_id:
                results[check_id] = IncrementalValidationResult(
                    check_id=check_id,
                    accepted=False,
                    error="registered_check_identity_mismatch",
                    baseline_evidence_id=baseline_id,
                )
            else:
                selected[check_id] = check

        self._record(checks_selected=len(selected), checks_missing=len(results))
        if selected:
            worker_count = min(self.max_workers, len(selected))
            with ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix=f"legal-ir-{stage.value}",
            ) as pool:
                futures = {
                    pool.submit(self._execute, check, plan, baseline): check_id
                    for check_id, check in selected.items()
                }
                for future in as_completed(futures):
                    check_id = futures[future]
                    try:
                        results[check_id] = future.result()
                    except Exception as exc:  # pragma: no cover - executor defence
                        results[check_id] = IncrementalValidationResult(
                            check_id=check_id,
                            accepted=False,
                            error=f"executor_error:{exc.__class__.__name__}: {exc}",
                            baseline_evidence_id=baseline_id,
                        )
        return IncrementalValidationStageResult(
            stage=stage,
            check_ids=check_ids,
            results=results,
            elapsed_seconds=time.monotonic() - started,
        )

    def _skip_stage(
        self,
        *,
        stage: IncrementalValidationStage,
        check_ids: tuple[str, ...],
        plan: ChangedScopeValidationPlan,
        baseline: Optional[FrozenBaselineEvidence],
        blocked_by: IncrementalValidationStageResult,
    ) -> IncrementalValidationStageResult:
        del plan  # retained in the signature to make stage construction explicit
        if not check_ids:
            return IncrementalValidationStageResult(stage, (), {})
        blocker_ids = blocked_by.failed_check_ids or blocked_by.skipped_check_ids
        reason = f"blocked_by_{blocked_by.stage.value}"
        baseline_id = baseline.evidence_id if baseline else ""
        results = {
            check_id: IncrementalValidationResult(
                check_id=check_id,
                accepted=False,
                attempts=0,
                error="skipped_due_to_prior_stage_failure",
                evidence={
                    "blocked_by_check_ids": list(blocker_ids),
                    "blocked_by_stage": blocked_by.stage.value,
                    "executed": False,
                },
                baseline_evidence_id=baseline_id,
                executed=False,
            )
            for check_id in check_ids
        }
        self._record(checks_skipped=len(results))
        return IncrementalValidationStageResult(
            stage=stage,
            check_ids=check_ids,
            results=results,
            skip_reason=reason,
        )

    def validate_staged(
        self,
        plan: ChangedScopeValidationPlan,
        checks: Mapping[str, ValidationCallback | IncrementalValidationCheck]
        | Sequence[IncrementalValidationCheck],
        *,
        baseline_evidence: Optional[FrozenBaselineEvidence] = None,
    ) -> StagedIncrementalValidationReport:
        """Validate in increasing cost order and stop after a failed gate.

        Syntax runs alone first.  Focused ``test:`` checks then run concurrently,
        followed by the semantic/replay/mutation/proof checks.  Complete frozen
        canary and promotion proof gates, when required, are always the final
        stage.  A transient failure rescued within its retry bound is a success
        and does not block the next stage; an unresolved transient does block it
        and marks the aggregate as requiring a requeue.
        """

        if not isinstance(plan, ChangedScopeValidationPlan):
            raise TypeError("plan must be ChangedScopeValidationPlan")
        normalized = self._normalize_checks(checks)
        required = plan.required_check_ids
        promotion_ids = tuple(
            item for item in required if item in {"frozen_canary", "promotion_proof_set"}
        )
        syntax_ids = tuple(item for item in required if item == "syntax")
        focused_ids = tuple(item for item in required if item.startswith("test:"))
        preclassified = set(syntax_ids) | set(focused_ids) | set(promotion_ids)
        expensive_ids = tuple(item for item in required if item not in preclassified)
        specifications = (
            (IncrementalValidationStage.SYNTAX, syntax_ids),
            (IncrementalValidationStage.FOCUSED_PREFLIGHT, focused_ids),
            (IncrementalValidationStage.EXPENSIVE, expensive_ids),
            (IncrementalValidationStage.PROMOTION, promotion_ids),
        )

        self._record(runs=1, staged_runs=1)
        stages: list[IncrementalValidationStageResult] = []
        blocker: Optional[IncrementalValidationStageResult] = None
        for stage, check_ids in specifications:
            if blocker is None:
                outcome = self._execute_stage(
                    stage=stage,
                    check_ids=check_ids,
                    normalized=normalized,
                    plan=plan,
                    baseline=baseline_evidence,
                )
                if not outcome.accepted:
                    blocker = outcome
            else:
                outcome = self._skip_stage(
                    stage=stage,
                    check_ids=check_ids,
                    plan=plan,
                    baseline=baseline_evidence,
                    blocked_by=blocker,
                )
            stages.append(outcome)

        combined_results = {
            check_id: result
            for stage in stages
            for check_id, result in stage.results.items()
        }
        report = IncrementalValidationReport(
            plan=plan,
            results=combined_results,
            baseline_evidence_id=baseline_evidence.evidence_id if baseline_evidence else "",
        )
        self._record(
            runs_accepted=int(report.accepted),
            runs_failed=int(not report.accepted),
            staged_runs_requeue_required=int(report.transient_requeue_required),
        )
        return StagedIncrementalValidationReport(report=report, stages=tuple(stages))

    # A more discoverable spelling for Codex worktree orchestration.
    validate_preflight_first = validate_staged

    def validate(
        self,
        plan: ChangedScopeValidationPlan,
        checks: Mapping[str, ValidationCallback | IncrementalValidationCheck] | Sequence[IncrementalValidationCheck],
        *,
        baseline_evidence: Optional[FrozenBaselineEvidence] = None,
    ) -> IncrementalValidationReport:
        """Execute every required check and preserve explicit missing failures."""

        if not isinstance(plan, ChangedScopeValidationPlan):
            raise TypeError("plan must be ChangedScopeValidationPlan")
        normalized = self._normalize_checks(checks)

        selected: dict[str, IncrementalValidationCheck] = {}
        results: dict[str, IncrementalValidationResult] = {}
        baseline_id = baseline_evidence.evidence_id if baseline_evidence else ""
        for check_id in plan.required_check_ids:
            check = normalized.get(check_id)
            if check is None:
                results[check_id] = IncrementalValidationResult(
                    check_id=check_id, accepted=False, error="required_check_not_registered",
                    baseline_evidence_id=baseline_id,
                )
            elif check.check_id != check_id:
                results[check_id] = IncrementalValidationResult(
                    check_id=check_id, accepted=False, error="registered_check_identity_mismatch",
                    baseline_evidence_id=baseline_id,
                )
            else:
                selected[check_id] = check

        self._record(runs=1, checks_selected=len(selected), checks_missing=len(results))
        if selected:
            worker_count = min(self.max_workers, len(selected))
            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="legal-ir-validation") as pool:
                futures = {
                    pool.submit(self._execute, check, plan, baseline_evidence): check_id
                    for check_id, check in selected.items()
                }
                for future in as_completed(futures):
                    check_id = futures[future]
                    try:
                        results[check_id] = future.result()
                    except Exception as exc:  # pragma: no cover - executor defence
                        results[check_id] = IncrementalValidationResult(
                            check_id=check_id, accepted=False,
                            error=f"executor_error:{exc.__class__.__name__}: {exc}",
                            baseline_evidence_id=baseline_id,
                        )
        report = IncrementalValidationReport(plan, results, baseline_id)
        self._record(runs_accepted=int(report.accepted), runs_failed=int(not report.accepted))
        return report

    def summary(self) -> dict[str, int]:
        with self._lock:
            return dict(sorted(self._counters.items()))


class PreflightFirstIncrementalValidator(IncrementalCandidateValidator):
    """Validator whose primary ``validate`` entry point is the staged contract."""

    def validate(  # type: ignore[override]
        self,
        plan: ChangedScopeValidationPlan,
        checks: Mapping[str, ValidationCallback | IncrementalValidationCheck]
        | Sequence[IncrementalValidationCheck],
        *,
        baseline_evidence: Optional[FrozenBaselineEvidence] = None,
    ) -> StagedIncrementalValidationReport:
        return self.validate_staged(plan, checks, baseline_evidence=baseline_evidence)


def validate_incremental_candidate(
    plan: ChangedScopeValidationPlan,
    checks: Mapping[str, ValidationCallback | IncrementalValidationCheck] | Sequence[IncrementalValidationCheck],
    *,
    baseline_evidence: Optional[FrozenBaselineEvidence] = None,
    max_workers: int = 8,
    max_transient_retries: int = 1,
) -> IncrementalValidationReport:
    """Convenience wrapper around :class:`IncrementalCandidateValidator`."""

    return IncrementalCandidateValidator(
        max_workers=max_workers, max_transient_retries=max_transient_retries
    ).validate(plan, checks, baseline_evidence=baseline_evidence)


def validate_staged_incremental_candidate(
    plan: ChangedScopeValidationPlan,
    checks: Mapping[str, ValidationCallback | IncrementalValidationCheck]
    | Sequence[IncrementalValidationCheck],
    *,
    baseline_evidence: Optional[FrozenBaselineEvidence] = None,
    max_workers: int = 8,
    max_transient_retries: int = 1,
) -> StagedIncrementalValidationReport:
    """Run syntax and focused preflight before expensive candidate checks."""

    return IncrementalCandidateValidator(
        max_workers=max_workers, max_transient_retries=max_transient_retries
    ).validate_staged(plan, checks, baseline_evidence=baseline_evidence)


# Stable descriptive aliases for callers which use the shorter runtime names.
ASTScope = TypedASTScope
IncrementalValidationPlan = ChangedScopeValidationPlan
IncrementalValidationPlanner = ChangedScopeValidationPlanner
IncrementalValidationRunner = IncrementalCandidateValidator
ImmutableBaselineEvidence = FrozenBaselineEvidence
IncrementalStagedValidationReport = StagedIncrementalValidationReport
plan_changed_scope_validation = plan_incremental_validation
validate_incremental_candidate_staged = validate_staged_incremental_candidate


__all__ = [
    "CHANGED_SCOPE_PLAN_SCHEMA_VERSION",
    "DEFAULT_CHANGED_SCOPE_RULES",
    "DEFAULT_FOCUSED_TESTS",
    "DEFAULT_MUTATION_CASES",
    "DEFAULT_PROOF_OBLIGATIONS",
    "DEFAULT_REPLAY_CASES",
    "FROZEN_BASELINE_EVIDENCE_SCHEMA_VERSION",
    "INCREMENTAL_VALIDATION_SCHEMA_VERSION",
    "ChangedScopeRule",
    "ChangedScopeValidationPlan",
    "ChangedScopeValidationPlanner",
    "FrozenBaselineEvidence",
    "ImmutableBaselineEvidence",
    "IncrementalCandidateValidator",
    "PreflightFirstIncrementalValidator",
    "IncrementalValidationCheck",
    "IncrementalValidationReport",
    "IncrementalValidationStage",
    "IncrementalValidationStageResult",
    "StagedIncrementalValidationReport",
    "IncrementalStagedValidationReport",
    "IncrementalValidationPlan",
    "IncrementalValidationPlanner",
    "IncrementalValidationRunner",
    "IncrementalValidationRequest",
    "IncrementalValidationResult",
    "TransientValidationError",
    "TypedASTScope",
    "ASTScope",
    "ValidationBoundary",
    "ValidationScopeCatalog",
    "build_incremental_validation_plan",
    "map_changed_scope",
    "plan_incremental_validation",
    "plan_changed_scope_validation",
    "validate_incremental_candidate",
    "validate_staged_incremental_candidate",
    "validate_incremental_candidate_staged",
]
