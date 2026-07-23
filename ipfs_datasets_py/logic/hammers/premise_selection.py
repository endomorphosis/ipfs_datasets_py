"""Deterministic premise selection baselines for the ITP hammer pipeline
(HAMMER-004).

This module implements the deterministic, auditable premise selector
described in ``docs/logic/itp_hammer_premise_selection.md`` and the
``## HAMMER-004`` entry of ``docs/logic/itp_hammer_taskboard.todo.md``: given
a goal (its symbols, types, imports, and, when the goal is itself a corpus
theorem, its identity) and a :class:`~ipfs_datasets_py.logic.hammers.corpus.CorpusManifest`
snapshot, rank every candidate premise by a purely deterministic,
reproducible score derived from symbol overlap, type overlap, import
overlap, and a one-hop dependency-graph proximity signal over the corpus's
theorem/import bipartite graph.

This is a *baseline*: no machine-learned model, embedding, or LLM is
involved (see HAMMER-005 for the opt-in, gated learned selector that must
fall back to this baseline). The design goals are:

- **Determinism.** Identical ``(manifest, goal, weights, top_k, ...)`` input
  always produces byte-identical output, including tie-break ordering when
  two candidates score equally.
- **Auditability.** Every selected premise carries its score, the corpus
  revision it was drawn from, and its rank. Every candidate that was
  *considered but not selected* is reported too, with an explicit exclusion
  reason (self-reference, explicit caller exclusion, below a configured
  score floor, or beyond the ``top_k`` cutoff) — nothing is silently
  dropped.
- **Bounded cost.** ``top_k`` is always enforced, and, when a
  :class:`~ipfs_datasets_py.logic.hammers.models.HammerPolicy` is supplied,
  a request for more premises than ``policy.max_premises`` permits is
  rejected outright (:class:`InvalidTopKError`) rather than silently
  clamped, so a caller can never observe a "budget" that quietly differs
  from what it asked for.

Building blocks
----------------
- :func:`extract_symbols` / :func:`extract_types` — cheap, ITP-agnostic
  lexical feature extraction over a raw statement string (no parsing of
  Lean/Coq/Isabelle syntax, mirroring :func:`~ipfs_datasets_py.logic.hammers.corpus.normalize_statement`'s
  ITP-agnostic design).
- :class:`GoalFeatures` — the symbols/types/imports (and, optionally, the
  corpus identity) of the goal being attempted.
- :class:`PremiseSelectionWeights` — the (validated, finite, non-negative)
  weights combining the four feature scores into one deterministic total.
- :class:`ScoredCandidate` — one candidate premise's full score breakdown,
  produced by :func:`score_candidates`.
- :class:`PremiseExclusionReason` / :class:`ExcludedPremise` — the record of
  a candidate that was considered but not selected, and why.
- :class:`PremiseSelectionResult` — the final, versioned selection outcome
  tying selected :class:`~ipfs_datasets_py.logic.hammers.models.PremiseRecord`
  entries, excluded candidates, the corpus revision, and the enforced
  ``top_k`` cutoff together.
- :func:`select_premises` / :func:`select_premises_for_theorem` — the
  top-level entry points.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence

from .corpus import CorpusManifest, TheoremEntry
from .models import (
    SCHEMA_VERSION,
    HammerPolicy,
    PremiseRecord,
    _isoformat,
    _parse_datetime,
    _require_finite_float,
    _require_nonempty_str,
    _require_schema_version,
    _utcnow,
)

__all__ = [
    "SCHEMA_VERSION",
    "DETERMINISTIC_BASELINE_METHOD",
    "PremiseSelectionError",
    "InvalidTopKError",
    "PremiseExclusionReason",
    "GoalFeatures",
    "PremiseSelectionWeights",
    "ScoredCandidate",
    "ExcludedPremise",
    "PremiseSelectionResult",
    "extract_symbols",
    "extract_types",
    "score_candidates",
    "select_premises",
    "select_premises_for_theorem",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PremiseSelectionError(ValueError):
    """Base class for all premise-selection errors raised by this module."""


class InvalidTopKError(PremiseSelectionError):
    """Raised when a requested ``top_k`` is not a positive integer, or
    exceeds the ``max_premises`` bound of a supplied
    :class:`~ipfs_datasets_py.logic.hammers.models.HammerPolicy`.

    This is the mechanism that enforces "bounded ``top_k``": a caller can
    never silently receive a larger (or smaller, clamped-without-signal)
    selection than it asked for — an out-of-policy request fails closed.
    """


# ---------------------------------------------------------------------------
# Selection method identifier
# ---------------------------------------------------------------------------

#: Identifier stamped onto every :class:`~ipfs_datasets_py.logic.hammers.models.PremiseRecord`
#: produced by this module's deterministic baseline (see
#: :attr:`~ipfs_datasets_py.logic.hammers.models.PremiseRecord.selection_method`).
DETERMINISTIC_BASELINE_METHOD = "deterministic-baseline"


# ---------------------------------------------------------------------------
# Lexical feature extraction (symbols / types)
# ---------------------------------------------------------------------------

#: Identifier token pattern shared across Lean4/Coq/Rocq/Isabelle statement
#: text: a leading letter or underscore, followed by letters, digits,
#: underscores, dots (qualified names such as ``Nat.add_comm``), or a
#: trailing prime (``'``), which is common in Isabelle/HOL and Coq variable
#: names (``x'``).
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*'*")

#: Keywords, binders, and tactic/proof-structure vocabulary shared across
#: Lean4, Coq/Rocq, and Isabelle/HOL statement and proof text. These are
#: deliberately excluded from the extracted "symbol" feature set because
#: they carry essentially no discriminative information about which
#: premises are topically relevant to a goal (every statement mentions
#: ``forall``/``let``/``by`` regardless of subject matter). This list is a
#: heuristic, ITP-agnostic vocabulary filter — it does not parse or
#: understand any ITP's grammar, mirroring the design of
#: :func:`~ipfs_datasets_py.logic.hammers.corpus.normalize_statement`.
_STOPWORDS = frozenset(
    word.lower()
    for word in [
        # Shared / cross-ITP
        "forall", "exists", "fun", "let", "in", "if", "then", "else", "do",
        "match", "with", "end", "where", "class", "instance", "structure",
        "open", "import", "using", "from", "as", "return", "case", "of",
        # Lean4
        "theorem", "lemma", "def", "definition", "example", "by", "have",
        "show", "suffices", "this", "sorry", "admit", "variable",
        "variables", "section", "namespace", "obtain", "rcases", "rintro",
        "intro", "intros", "apply", "exact", "simp", "rw", "calc",
        "noncomputable", "mutual", "deriving", "attribute",
        # Coq / Rocq
        "proof", "qed", "fixpoint", "inductive", "context", "module",
        "require", "export", "axiom", "hypothesis", "corollary", "remark",
        "fact", "record", "notation", "begin", "assumption", "induction",
        "destruct", "reflexivity", "unfold", "auto",
        # Isabelle/HOL
        "primrec", "datatype", "locale", "assumes", "shows", "obtains",
        "hence", "thus", "fix", "next", "moreover", "ultimately", "value",
        "true", "false",
    ]
)


def extract_symbols(statement: str) -> FrozenSet[str]:
    """Extract a deterministic, ITP-agnostic set of "content symbol" tokens
    from a raw statement string.

    This performs no real parsing: it tokenizes on :data:`_IDENTIFIER_RE`,
    drops common cross-ITP keywords/tactic vocabulary (see
    :data:`_STOPWORDS`) and single-character tokens (a cheap heuristic proxy
    for bound variables such as ``a``, ``b``, ``n``, which carry little
    topical signal), and returns the remaining identifiers as a frozenset.

    Args:
        statement: The raw statement text (goal or premise), as authored.

    Returns:
        A frozenset of lower-cased content symbol tokens. Empty if
        ``statement`` is empty or contains no qualifying tokens.
    """

    if not statement:
        return frozenset()

    symbols = set()
    for match in _IDENTIFIER_RE.finditer(statement):
        token = match.group(0)
        if len(token) <= 1:
            continue
        if token.lower() in _STOPWORDS:
            continue
        symbols.add(token.lower())
    return frozenset(symbols)


def extract_types(statement: str) -> FrozenSet[str]:
    """Extract a deterministic, ITP-agnostic set of "type-like" tokens from
    a raw statement string.

    Heuristic: any extracted identifier (see :func:`extract_symbols`, before
    lower-casing) whose first character is uppercase is treated as
    type-like. This mirrors the widespread Lean/Coq/Isabelle convention of
    capitalizing type and sort names (``Nat``, ``List``, ``Prop``, ``Set``,
    qualified as ``Nat.succ``) while lower-case identifiers are typically
    functions, lemma names, or bound variables. It is a lexical heuristic,
    not a type checker.

    Args:
        statement: The raw statement text (goal or premise), as authored.

    Returns:
        A frozenset of type-like tokens (original case preserved). Empty if
        ``statement`` is empty or contains no qualifying tokens.
    """

    if not statement:
        return frozenset()

    types = set()
    for match in _IDENTIFIER_RE.finditer(statement):
        token = match.group(0)
        if len(token) <= 1:
            continue
        if token.lower() in _STOPWORDS:
            continue
        if token[0].isupper():
            types.add(token)
    return frozenset(types)


def _normalize_imports(imports: Optional[Iterable[str]]) -> FrozenSet[str]:
    if not imports:
        return frozenset()
    return frozenset(str(item) for item in imports if str(item).strip())


# ---------------------------------------------------------------------------
# Goal features
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoalFeatures:
    """The symbol/type/import feature set of a goal being attempted.

    Attributes:
        symbols: Content symbols occurring in (or explicitly supplied for)
            the goal statement — see :func:`extract_symbols`.
        types: Type-like tokens occurring in (or explicitly supplied for)
            the goal statement — see :func:`extract_types`.
        imports: Module/theory/file dependencies the goal requires.
        theorem_id: If the goal is itself a corpus theorem (e.g. a held-out
            evaluation goal), its identity within the manifest, so it can be
            excluded from its own candidate pool
            (:attr:`PremiseExclusionReason.SELF_REFERENCE`). ``None`` for a
            genuinely new, not-yet-ingested goal.
    """

    symbols: FrozenSet[str] = field(default_factory=frozenset)
    types: FrozenSet[str] = field(default_factory=frozenset)
    imports: FrozenSet[str] = field(default_factory=frozenset)
    theorem_id: Optional[str] = None

    @classmethod
    def from_statement(
        cls,
        goal_statement: str,
        *,
        theorem_id: Optional[str] = None,
        imports: Optional[Iterable[str]] = None,
        extra_symbols: Optional[Iterable[str]] = None,
        extra_types: Optional[Iterable[str]] = None,
    ) -> "GoalFeatures":
        """Build :class:`GoalFeatures` by lexically extracting symbols and
        types from ``goal_statement`` (see :func:`extract_symbols` /
        :func:`extract_types`), optionally unioned with caller-supplied
        ``extra_symbols`` / ``extra_types`` (e.g. symbols recovered from a
        native frontend snapshot rather than the diagnostic text form).

        Args:
            goal_statement: The raw (diagnostic) goal statement text.
            theorem_id: Optional corpus identity of the goal, for
                self-exclusion.
            imports: The goal's module/theory/file dependencies.
            extra_symbols: Additional content symbols to union in.
            extra_types: Additional type-like tokens to union in.
        """

        symbols = set(extract_symbols(goal_statement))
        symbols.update(str(s).lower() for s in (extra_symbols or []))
        types = set(extract_types(goal_statement))
        types.update(extra_types or [])
        return cls(
            symbols=frozenset(symbols),
            types=frozenset(types),
            imports=_normalize_imports(imports),
            theorem_id=theorem_id,
        )

    @classmethod
    def from_theorem_entry(cls, entry: TheoremEntry) -> "GoalFeatures":
        """Build :class:`GoalFeatures` from an existing corpus
        :class:`~ipfs_datasets_py.logic.hammers.corpus.TheoremEntry` —
        typically used for held-out evaluation ("given every other theorem
        in the corpus, would selection have ranked this theorem's actual
        dependencies highly?") or for :func:`select_premises_for_theorem`.
        """

        return cls.from_statement(
            entry.statement,
            theorem_id=entry.theorem_id,
            imports=entry.imports,
        )

    def validate(self) -> None:
        if not isinstance(self.symbols, frozenset) or not all(
            isinstance(item, str) for item in self.symbols
        ):
            raise ValueError("GoalFeatures.symbols must be a frozenset of strings")
        if not isinstance(self.types, frozenset) or not all(
            isinstance(item, str) for item in self.types
        ):
            raise ValueError("GoalFeatures.types must be a frozenset of strings")
        if not isinstance(self.imports, frozenset) or not all(
            isinstance(item, str) for item in self.imports
        ):
            raise ValueError("GoalFeatures.imports must be a frozenset of strings")
        if self.theorem_id is not None and not isinstance(self.theorem_id, str):
            raise ValueError("GoalFeatures.theorem_id must be a string or None")


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------

#: Default weight combining the goal/premise symbol-overlap score into the
#: total deterministic score. Symbols dominate the default weighting because
#: shared content symbols (function/constant names) are the strongest cheap
#: signal of topical relevance between a goal and a candidate premise.
DEFAULT_SYMBOL_WEIGHT = 0.45

#: Default weight for the type-overlap score.
DEFAULT_TYPE_WEIGHT = 0.20

#: Default weight for the direct import-overlap score.
DEFAULT_IMPORT_WEIGHT = 0.20

#: Default weight for the one-hop dependency-graph proximity score.
DEFAULT_GRAPH_WEIGHT = 0.15


@dataclass
class PremiseSelectionWeights:
    """Deterministic, validated weights combining the four per-candidate
    feature scores (symbol/type/import overlap and dependency-graph
    proximity — see :class:`ScoredCandidate`) into one total score.

    Weights need not sum to 1.0 (callers may over- or under-weight a
    feature freely), but must all be finite and non-negative, and at least
    one must be strictly positive (an all-zero weighting would make every
    candidate score 0.0, which is a degenerate configuration this class
    rejects rather than silently accepting).
    """

    symbol_weight: float = DEFAULT_SYMBOL_WEIGHT
    type_weight: float = DEFAULT_TYPE_WEIGHT
    import_weight: float = DEFAULT_IMPORT_WEIGHT
    graph_weight: float = DEFAULT_GRAPH_WEIGHT

    def validate(self) -> None:
        for name in ("symbol_weight", "type_weight", "import_weight", "graph_weight"):
            value = getattr(self, name)
            _require_finite_float(value, field_name=name, owner="PremiseSelectionWeights")
            if value < 0:
                raise ValueError(f"PremiseSelectionWeights.{name} must be non-negative")
        if (
            self.symbol_weight == 0
            and self.type_weight == 0
            and self.import_weight == 0
            and self.graph_weight == 0
        ):
            raise ValueError(
                "PremiseSelectionWeights must have at least one strictly positive weight"
            )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PremiseSelectionWeights":
        return cls(**dict(data))


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _jaccard(left: FrozenSet[str], right: FrozenSet[str]) -> float:
    """Deterministic Jaccard similarity in ``[0.0, 1.0]``; ``0.0`` when both
    sets are empty (rather than an undefined ``0/0``)."""

    if not left and not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _expand_imports_one_hop(
    goal_imports: FrozenSet[str], manifest: CorpusManifest
) -> FrozenSet[str]:
    """Expand ``goal_imports`` by one hop over the corpus's theorem/import
    bipartite graph: for every theorem that shares at least one import with
    the goal, union in *all* of that theorem's imports too.

    This is the module's "dependency graph feature": it lets a candidate
    premise score well via *transitive* proximity (sharing an import with a
    theorem that itself shares an import with the goal) even when it has
    zero direct import overlap with the goal, which a plain import-Jaccard
    score cannot express. The expansion is a single, bounded hop (not a full
    transitive closure) to keep the signal local and the computation
    ``O(#theorems)`` rather than requiring a general graph-reachability
    fixpoint.

    Args:
        goal_imports: The goal's direct imports.
        manifest: The corpus manifest supplying the theorem/import graph.

    Returns:
        ``goal_imports`` unioned with every import of every theorem that
        shares at least one import with ``goal_imports``.
    """

    expanded = set(goal_imports)
    if not goal_imports:
        return frozenset(expanded)
    for entry in manifest.iter_theorems():
        entry_imports = frozenset(entry.imports)
        if entry_imports & goal_imports:
            expanded |= entry_imports
    return frozenset(expanded)


@dataclass(frozen=True)
class ScoredCandidate:
    """The full, deterministic score breakdown for one candidate premise
    against one goal.

    Attributes:
        theorem_id: The candidate's identity within the corpus manifest.
        score: The final weighted total (see :class:`PremiseSelectionWeights`).
        symbol_score: Jaccard overlap between goal and candidate symbols.
        type_score: Jaccard overlap between goal and candidate types.
        import_score: Jaccard overlap between goal and candidate imports.
        graph_score: Jaccard overlap between the candidate's imports and the
            goal's one-hop-expanded import set (see
            :func:`_expand_imports_one_hop`).
    """

    theorem_id: str
    score: float
    symbol_score: float
    type_score: float
    import_score: float
    graph_score: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def score_candidates(
    goal: GoalFeatures,
    manifest: CorpusManifest,
    *,
    weights: Optional[PremiseSelectionWeights] = None,
    candidates: Optional[Sequence[TheoremEntry]] = None,
) -> List[ScoredCandidate]:
    """Score every candidate premise against ``goal`` and return them in
    stable, deterministic rank order.

    Ordering is by descending ``score``, then ascending ``theorem_id`` as an
    explicit tie-break — this guarantees byte-identical ordering across runs
    for identical input regardless of dict/hash-set iteration order
    elsewhere in the process, which is exactly the "stable ordering for
    identical input" requirement this module must satisfy.

    Args:
        goal: The goal's symbol/type/import features.
        manifest: The corpus manifest to draw candidates from.
        weights: Feature weights; defaults to :class:`PremiseSelectionWeights`'s
            defaults if omitted.
        candidates: Optional explicit candidate pool (e.g. a pre-filtered
            subset of the manifest); defaults to every theorem in the
            manifest (:meth:`~ipfs_datasets_py.logic.hammers.corpus.CorpusManifest.iter_theorems`).

    Returns:
        Every candidate's :class:`ScoredCandidate`, sorted deterministically.
    """

    if not isinstance(manifest, CorpusManifest):
        raise PremiseSelectionError("manifest must be a CorpusManifest")
    if not isinstance(goal, GoalFeatures):
        raise PremiseSelectionError("goal must be a GoalFeatures instance")
    goal.validate()

    resolved_weights = weights if weights is not None else PremiseSelectionWeights()
    resolved_weights.validate()

    pool = list(candidates) if candidates is not None else manifest.iter_theorems()

    expanded_goal_imports = _expand_imports_one_hop(goal.imports, manifest)

    scored: List[ScoredCandidate] = []
    for entry in pool:
        if not isinstance(entry, TheoremEntry):
            raise PremiseSelectionError(
                "candidates must be TheoremEntry instances"
            )
        entry_symbols = extract_symbols(entry.statement)
        entry_types = extract_types(entry.statement)
        entry_imports = frozenset(entry.imports)

        symbol_score = _jaccard(goal.symbols, entry_symbols)
        type_score = _jaccard(goal.types, entry_types)
        import_score = _jaccard(goal.imports, entry_imports)
        graph_score = _jaccard(entry_imports, expanded_goal_imports)

        total = (
            resolved_weights.symbol_weight * symbol_score
            + resolved_weights.type_weight * type_score
            + resolved_weights.import_weight * import_score
            + resolved_weights.graph_weight * graph_score
        )
        scored.append(
            ScoredCandidate(
                theorem_id=entry.theorem_id,
                score=total,
                symbol_score=symbol_score,
                type_score=type_score,
                import_score=import_score,
                graph_score=graph_score,
            )
        )

    scored.sort(key=lambda candidate: (-candidate.score, candidate.theorem_id))
    return scored


# ---------------------------------------------------------------------------
# Exclusion / selection result records
# ---------------------------------------------------------------------------


class PremiseExclusionReason(str, Enum):
    """Why a considered candidate premise was *not* selected.

    Every candidate that enters selection but is not returned in
    ``selected`` must be reported in ``excluded`` with exactly one of these
    reasons — nothing is silently dropped.
    """

    #: The candidate *is* the goal itself (``goal.theorem_id`` matched).
    SELF_REFERENCE = "self_reference"
    #: The caller explicitly excluded this ``theorem_id`` via
    #: ``exclude_theorem_ids``.
    EXPLICITLY_EXCLUDED = "explicitly_excluded"
    #: The candidate's score was below the configured ``min_score`` floor.
    BELOW_SCORE_FLOOR = "below_score_floor"
    #: The candidate ranked below the enforced ``top_k`` cutoff.
    BELOW_CUTOFF = "below_cutoff"


@dataclass
class ExcludedPremise:
    """A candidate premise that was considered but not selected.

    Attributes:
        schema_version: Schema version of this record.
        premise_id: The excluded candidate's ``theorem_id``.
        score: The candidate's deterministic total score.
        reason: Why the candidate was excluded (see
            :class:`PremiseExclusionReason`).
        corpus_revision: Corpus manifest revision the candidate was drawn
            from.
    """

    schema_version: str = SCHEMA_VERSION
    premise_id: str = ""
    score: float = 0.0
    reason: PremiseExclusionReason = PremiseExclusionReason.BELOW_CUTOFF
    corpus_revision: str = ""

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="ExcludedPremise")
        _require_nonempty_str(self.premise_id, field_name="premise_id", owner="ExcludedPremise")
        _require_finite_float(self.score, field_name="score", owner="ExcludedPremise")
        if not isinstance(self.reason, PremiseExclusionReason):
            raise ValueError("ExcludedPremise.reason must be a PremiseExclusionReason")
        _require_nonempty_str(
            self.corpus_revision, field_name="corpus_revision", owner="ExcludedPremise"
        )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["reason"] = self.reason.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExcludedPremise":
        data = dict(data)
        if isinstance(data.get("reason"), str):
            data["reason"] = PremiseExclusionReason(data["reason"])
        return cls(**data)


@dataclass
class PremiseSelectionResult:
    """The final, versioned outcome of one deterministic premise selection
    run.

    Attributes:
        schema_version: Schema version of this record.
        corpus_revision: The :class:`~ipfs_datasets_py.logic.hammers.corpus.CorpusManifest`
            revision every ``selected``/``excluded`` entry was drawn from.
        goal_theorem_id: The goal's own corpus identity, if it has one
            (``None`` for a genuinely new goal).
        selection_method: Identifier of the selector that produced this
            result; always :data:`DETERMINISTIC_BASELINE_METHOD` for this
            module.
        top_k: The enforced selection cutoff (bound on ``len(selected)``).
        weights: The feature weights used to compute every score.
        selected: The selected premises, in stable rank order (``rank`` 0 =
            highest priority), each a
            :class:`~ipfs_datasets_py.logic.hammers.models.PremiseRecord`.
        excluded: Every candidate that was considered but not selected, with
            its exclusion reason (see :class:`PremiseExclusionReason`), in
            the same deterministic score order as ``selected``.
        created_at: When this selection was computed.
    """

    schema_version: str = SCHEMA_VERSION
    corpus_revision: str = ""
    goal_theorem_id: Optional[str] = None
    selection_method: str = DETERMINISTIC_BASELINE_METHOD
    top_k: int = 0
    weights: PremiseSelectionWeights = field(default_factory=PremiseSelectionWeights)
    selected: List[PremiseRecord] = field(default_factory=list)
    excluded: List[ExcludedPremise] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utcnow)

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="PremiseSelectionResult")
        _require_nonempty_str(
            self.corpus_revision, field_name="corpus_revision", owner="PremiseSelectionResult"
        )
        if self.goal_theorem_id is not None and not isinstance(self.goal_theorem_id, str):
            raise ValueError("PremiseSelectionResult.goal_theorem_id must be a string or None")
        _require_nonempty_str(
            self.selection_method,
            field_name="selection_method",
            owner="PremiseSelectionResult",
        )
        if not isinstance(self.top_k, int) or self.top_k <= 0:
            raise ValueError("PremiseSelectionResult.top_k must be a positive integer")
        if not isinstance(self.weights, PremiseSelectionWeights):
            raise ValueError("PremiseSelectionResult.weights must be a PremiseSelectionWeights")
        self.weights.validate()
        if not isinstance(self.selected, list) or not all(
            isinstance(item, PremiseRecord) for item in self.selected
        ):
            raise ValueError("PremiseSelectionResult.selected must be a list of PremiseRecord")
        if len(self.selected) > self.top_k:
            raise ValueError(
                f"PremiseSelectionResult.selected has {len(self.selected)} entries, "
                f"exceeding the enforced top_k cutoff of {self.top_k}"
            )
        for index, premise in enumerate(self.selected):
            premise.validate()
            if premise.rank != index:
                raise ValueError(
                    f"PremiseSelectionResult.selected[{index}] has rank={premise.rank}, "
                    f"expected {index} (stable, 0-indexed rank order)"
                )
            if premise.corpus_revision != self.corpus_revision:
                raise ValueError(
                    f"PremiseSelectionResult.selected[{index}].corpus_revision "
                    f"{premise.corpus_revision!r} does not match "
                    f"{self.corpus_revision!r}"
                )
        selected_ids = [premise.premise_id for premise in self.selected]
        if len(set(selected_ids)) != len(selected_ids):
            raise ValueError("PremiseSelectionResult.selected must not contain duplicate premise_id")

        if not isinstance(self.excluded, list) or not all(
            isinstance(item, ExcludedPremise) for item in self.excluded
        ):
            raise ValueError("PremiseSelectionResult.excluded must be a list of ExcludedPremise")
        for excluded_premise in self.excluded:
            excluded_premise.validate()
            if excluded_premise.corpus_revision != self.corpus_revision:
                raise ValueError(
                    f"PremiseSelectionResult excluded premise "
                    f"{excluded_premise.premise_id!r} has corpus_revision "
                    f"{excluded_premise.corpus_revision!r}, expected "
                    f"{self.corpus_revision!r}"
                )
        excluded_ids = [item.premise_id for item in self.excluded]
        if len(set(excluded_ids)) != len(excluded_ids):
            raise ValueError("PremiseSelectionResult.excluded must not contain duplicate premise_id")
        if set(selected_ids) & set(excluded_ids):
            raise ValueError(
                "PremiseSelectionResult.selected and .excluded must be disjoint"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "corpus_revision": self.corpus_revision,
            "goal_theorem_id": self.goal_theorem_id,
            "selection_method": self.selection_method,
            "top_k": self.top_k,
            "weights": self.weights.to_dict(),
            "selected": [premise.to_dict() for premise in self.selected],
            "excluded": [item.to_dict() for item in self.excluded],
            "created_at": _isoformat(self.created_at),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PremiseSelectionResult":
        data = dict(data)
        if isinstance(data.get("weights"), dict):
            data["weights"] = PremiseSelectionWeights.from_dict(data["weights"])
        data["selected"] = [
            PremiseRecord.from_dict(item) for item in data.get("selected", []) or []
        ]
        data["excluded"] = [
            ExcludedPremise.from_dict(item) for item in data.get("excluded", []) or []
        ]
        if "created_at" in data:
            data["created_at"] = _parse_datetime(data["created_at"])
        result = cls(**data)
        result.validate()
        return result


# ---------------------------------------------------------------------------
# Top-level selection entry points
# ---------------------------------------------------------------------------


def _resolve_top_k(top_k: int, *, policy: Optional[HammerPolicy]) -> int:
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
        raise InvalidTopKError(f"top_k must be a positive integer, got {top_k!r}")
    if policy is not None:
        policy.validate()
        if top_k > policy.max_premises:
            raise InvalidTopKError(
                f"requested top_k={top_k} exceeds policy.max_premises="
                f"{policy.max_premises}"
            )
    return top_k


def select_premises(
    manifest: CorpusManifest,
    goal: GoalFeatures,
    *,
    top_k: int,
    policy: Optional[HammerPolicy] = None,
    weights: Optional[PremiseSelectionWeights] = None,
    exclude_theorem_ids: Optional[Iterable[str]] = None,
    min_score: Optional[float] = None,
    candidates: Optional[Sequence[TheoremEntry]] = None,
) -> PremiseSelectionResult:
    """Deterministically rank and select premises for ``goal`` from
    ``manifest``.

    Args:
        manifest: The corpus manifest to draw candidates from; its
            ``revision`` is stamped onto every selected and excluded record.
        goal: The goal's symbol/type/import features (and, optionally, its
            own corpus identity for self-exclusion).
        top_k: The maximum number of premises to select. Must be a positive
            integer; enforced verbatim (never silently clamped) — see
            :class:`InvalidTopKError`.
        policy: Optional :class:`~ipfs_datasets_py.logic.hammers.models.HammerPolicy`.
            When given, ``top_k`` must not exceed ``policy.max_premises``.
        weights: Feature weights; defaults to :class:`PremiseSelectionWeights`'s
            defaults.
        exclude_theorem_ids: Additional caller-specified ``theorem_id``\\ s
            to always exclude (e.g. premises a prior attempt already tried
            and that the caller wants to avoid re-selecting), reported with
            :attr:`PremiseExclusionReason.EXPLICITLY_EXCLUDED`.
        min_score: Optional score floor; candidates scoring strictly below
            this value are excluded
            (:attr:`PremiseExclusionReason.BELOW_SCORE_FLOOR`) before the
            ``top_k`` cutoff is applied, so they never consume a selection
            slot.
        candidates: Optional explicit candidate pool; defaults to every
            theorem in ``manifest``.

    Returns:
        A validated :class:`PremiseSelectionResult`.

    Raises:
        InvalidTopKError: If ``top_k`` is not a positive integer, or
            exceeds ``policy.max_premises`` when ``policy`` is given.
        PremiseSelectionError: If ``manifest``/``goal``/``candidates`` are
            malformed.
    """

    resolved_top_k = _resolve_top_k(top_k, policy=policy)

    if not isinstance(manifest, CorpusManifest):
        raise PremiseSelectionError("manifest must be a CorpusManifest")
    if not isinstance(goal, GoalFeatures):
        raise PremiseSelectionError("goal must be a GoalFeatures instance")

    excluded_ids = frozenset(str(item) for item in (exclude_theorem_ids or []))
    corpus_revision = manifest.revision

    ranked = score_candidates(goal, manifest, weights=weights, candidates=candidates)
    resolved_weights = weights if weights is not None else PremiseSelectionWeights()

    excluded_records: List[ExcludedPremise] = []
    ranking_pool: List[ScoredCandidate] = []

    for candidate in ranked:
        if goal.theorem_id is not None and candidate.theorem_id == goal.theorem_id:
            excluded_records.append(
                ExcludedPremise(
                    premise_id=candidate.theorem_id,
                    score=candidate.score,
                    reason=PremiseExclusionReason.SELF_REFERENCE,
                    corpus_revision=corpus_revision,
                )
            )
            continue
        if candidate.theorem_id in excluded_ids:
            excluded_records.append(
                ExcludedPremise(
                    premise_id=candidate.theorem_id,
                    score=candidate.score,
                    reason=PremiseExclusionReason.EXPLICITLY_EXCLUDED,
                    corpus_revision=corpus_revision,
                )
            )
            continue
        if min_score is not None and candidate.score < min_score:
            excluded_records.append(
                ExcludedPremise(
                    premise_id=candidate.theorem_id,
                    score=candidate.score,
                    reason=PremiseExclusionReason.BELOW_SCORE_FLOOR,
                    corpus_revision=corpus_revision,
                )
            )
            continue
        ranking_pool.append(candidate)

    selected_candidates = ranking_pool[:resolved_top_k]
    beyond_cutoff = ranking_pool[resolved_top_k:]
    for candidate in beyond_cutoff:
        excluded_records.append(
            ExcludedPremise(
                premise_id=candidate.theorem_id,
                score=candidate.score,
                reason=PremiseExclusionReason.BELOW_CUTOFF,
                corpus_revision=corpus_revision,
            )
        )

    # `ranked` (and therefore `ranking_pool`/`beyond_cutoff`) is already in
    # stable (-score, theorem_id) order; re-sort the merged exclusion list
    # (self-reference / explicit / score-floor / cutoff, interleaved in
    # discovery order above) into that same deterministic order so
    # `excluded` never depends on which exclusion reason fired first.
    excluded_records.sort(key=lambda item: (-item.score, item.premise_id))

    selected_premises: List[PremiseRecord] = []
    for rank, candidate in enumerate(selected_candidates):
        entry = manifest.get_theorem(candidate.theorem_id)
        selected_premises.append(
            PremiseRecord(
                premise_id=entry.theorem_id,
                statement=entry.statement,
                source_itp=entry.source_itp,
                corpus_revision=corpus_revision,
                rank=rank,
                score=candidate.score,
                selection_method=DETERMINISTIC_BASELINE_METHOD,
                content_digest=entry.content_digest,
            )
        )

    result = PremiseSelectionResult(
        corpus_revision=corpus_revision,
        goal_theorem_id=goal.theorem_id,
        selection_method=DETERMINISTIC_BASELINE_METHOD,
        top_k=resolved_top_k,
        weights=resolved_weights,
        selected=selected_premises,
        excluded=excluded_records,
    )
    result.validate()
    return result


def select_premises_for_theorem(
    manifest: CorpusManifest,
    theorem_id: str,
    *,
    top_k: int,
    policy: Optional[HammerPolicy] = None,
    weights: Optional[PremiseSelectionWeights] = None,
    exclude_theorem_ids: Optional[Iterable[str]] = None,
    min_score: Optional[float] = None,
    candidates: Optional[Sequence[TheoremEntry]] = None,
) -> PremiseSelectionResult:
    """Convenience wrapper: select premises for an existing corpus theorem,
    using its own statement/imports as the goal (see
    :meth:`GoalFeatures.from_theorem_entry`) and automatically excluding it
    from its own candidate pool.

    This is the typical shape of a held-out evaluation: "given every other
    theorem currently in the corpus, which would the deterministic baseline
    select as premises for proving ``theorem_id``?"

    Args:
        manifest: The corpus manifest ``theorem_id`` must already exist in.
        theorem_id: The corpus identity of the theorem to select premises
            for.
        top_k: See :func:`select_premises`.
        policy: See :func:`select_premises`.
        weights: See :func:`select_premises`.
        exclude_theorem_ids: See :func:`select_premises`.
        min_score: See :func:`select_premises`.
        candidates: See :func:`select_premises`.

    Returns:
        A validated :class:`PremiseSelectionResult`.

    Raises:
        KeyError: If ``theorem_id`` does not exist in ``manifest``.
    """

    entry = manifest.get_theorem(theorem_id)
    goal = GoalFeatures.from_theorem_entry(entry)
    return select_premises(
        manifest,
        goal,
        top_k=top_k,
        policy=policy,
        weights=weights,
        exclude_theorem_ids=exclude_theorem_ids,
        min_score=min_score,
        candidates=candidates,
    )
