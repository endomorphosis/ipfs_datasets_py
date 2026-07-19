"""Optional, opt-in learned/graph-based premise selector (HAMMER-005).

This module implements the *gated* extension to the deterministic premise
selection baseline (HAMMER-004, ``.premise_selection``) described in
``docs/logic/itp_hammer_learned_selection.md`` and the ``## HAMMER-005``
entry of ``docs/logic/itp_hammer_taskboard.todo.md``.

The taskboard's operating rule for this module is unusually strict, and this
implementation enforces every clause of it in code, not just in prose:

- **The deterministic baseline stays the default.** Nothing in this module
  ever runs unless a caller explicitly opts in via
  :class:`LearnedSelectorConfig` *and* the run's
  :class:`~ipfs_datasets_py.logic.hammers.models.HammerPolicy` explicitly
  sets ``allow_learned_premise_selector=True``. Both gates must be open, or
  :func:`select_premises_gated` transparently falls back to
  :func:`~.premise_selection.select_premises`.
- **A learned or graph-based selector requires a pinned model digest.**
  :class:`LearnedModelArtifact` is a content-addressed record (its
  ``model_digest`` is derived from its own weights, not independently
  supplied) and :class:`LearnedSelectorConfig` requires callers to pin the
  *expected* digest up front. If the artifact actually loaded from disk does
  not hash to that pinned value, the run falls back rather than trusting an
  unexpected model.
- **Held-out recall/latency comparison.** :func:`relevant_theorem_ids_by_import_overlap`
  and :func:`compute_recall_at_k` are the reusable building blocks
  ``benchmarks/bench_itp_hammer_premise_selection.py`` uses to compare this
  module's selector against the HAMMER-004 baseline over a held-out corpus;
  see that script and ``docs/logic/itp_hammer_learned_selection.md`` §5 for
  the full methodology.
- **Reproducible feature extraction.** :func:`extract_learned_features` is a
  pure function of ``(goal, candidate, manifest)`` built entirely out of the
  same deterministic building blocks HAMMER-004 already uses
  (:func:`~.premise_selection.extract_symbols`,
  :func:`~.premise_selection.extract_types`, and the one-hop dependency-graph
  expansion) plus a handful of additional count-based features — no
  randomness, network access, or wall-clock dependence anywhere in the path.
- **Opt-in configuration.** See :class:`LearnedSelectorConfig`.
- **Fallback to the baseline when the model is missing or fails.** See
  :func:`select_premises_gated`'s documented :class:`SelectorFallbackReason`
  states: a missing model file, a model file that fails to parse, a digest
  mismatch, or an unexpected exception raised while scoring candidates all
  fall back to the HAMMER-004 baseline rather than raising to the caller or
  silently returning an empty/degenerate selection.

An honest note on "learned"
----------------------------
This module does not ship a trained neural network, gradient-boosted tree,
or embedding model — none of the ITP hammer pipeline's existing dependencies
provide a training harness, and fabricating one would violate this
project's "no LLM/ML claims without evidence" ethos more than it would
satisfy it. Instead, :func:`build_default_graph_selector_artifact` produces a
fixed, deterministic, *linear* combination of graph-based features (the
"graph-based selector" the taskboard also permits) wrapped in exactly the
same content-addressed, pinned-digest, fallback-gated artifact format a
genuinely trained model would use. Swapping in real trained weights later
requires no interface change: :meth:`LearnedModelArtifact.create` accepts any
``feature_name -> weight`` mapping, so a future model only needs to populate
that mapping (and its own ``feature_version``) — the gating, fallback, and
benchmark machinery in this module does not need to change.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple, Union

from .corpus import CorpusManifest, TheoremEntry
from .models import (
    SCHEMA_VERSION,
    HammerPolicy,
    PremiseRecord,
    _require_finite_float,
    _require_nonempty_str,
    _require_schema_version,
)
from .premise_selection import (
    ExcludedPremise,
    GoalFeatures,
    InvalidTopKError,
    PremiseExclusionReason,
    PremiseSelectionError,
    PremiseSelectionResult,
    PremiseSelectionWeights,
    ScoredCandidate,
    _expand_imports_one_hop,
    _jaccard,
    _resolve_top_k,
    extract_symbols,
    extract_types,
    select_premises,
)

__all__ = [
    "SCHEMA_VERSION",
    "LEARNED_FEATURE_VERSION",
    "LEARNED_SELECTION_METHOD_PREFIX",
    "DEFAULT_GRAPH_SELECTOR_MODEL_ID",
    "LearnedSelectorError",
    "LearnedSelectorConfigError",
    "ModelArtifactError",
    "ModelDigestMismatchError",
    "SelectorFallbackReason",
    "LearnedModelArtifact",
    "LearnedSelectorConfig",
    "LearnedSelectionResult",
    "compute_model_digest",
    "extract_learned_features",
    "score_with_model",
    "score_candidates_learned",
    "build_default_graph_selector_artifact",
    "select_premises_gated",
    "select_premises_for_theorem_gated",
    "relevant_theorem_ids_by_import_overlap",
    "compute_recall_at_k",
    "compute_reciprocal_rank",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LearnedSelectorError(PremiseSelectionError):
    """Base class for all learned-selector errors raised by this module."""


class LearnedSelectorConfigError(LearnedSelectorError):
    """Raised when :class:`LearnedSelectorConfig` itself is malformed (e.g.
    ``enabled=True`` without a ``pinned_model_digest``). This is a caller
    programming error, not a runtime "model missing/fails" condition, so it
    is raised rather than silently falling back — an operator must notice a
    misconfigured opt-in immediately."""


class ModelArtifactError(LearnedSelectorError):
    """Raised by :class:`LearnedModelArtifact` construction/validation when
    the artifact's own shape is malformed."""


class ModelDigestMismatchError(ModelArtifactError):
    """Raised by :meth:`LearnedModelArtifact.verify_digest` when the
    artifact's recomputed content digest does not match its stamped
    ``model_digest``. Never raised across :func:`select_premises_gated`'s
    public boundary — that path catches this and falls back instead."""


# ---------------------------------------------------------------------------
# Feature-extraction / method identifiers
# ---------------------------------------------------------------------------

#: Version identifier for :func:`extract_learned_features`'s feature schema.
#: A :class:`LearnedModelArtifact` records the feature version its weights
#: were fit against so a future, incompatible feature-extraction change
#: cannot silently be scored with stale weights.
LEARNED_FEATURE_VERSION = "learned-selector-features-v1"

#: Ordered, canonical feature names produced by :func:`extract_learned_features`
#: for :data:`LEARNED_FEATURE_VERSION`. Order matters only for readability —
#: scoring looks features up by name, never by position — but keeping one
#: canonical order avoids spurious "different" artifacts that ship the same
#: model as a differently-ordered dict.
LEARNED_FEATURE_NAMES: Tuple[str, ...] = (
    "symbol_score",
    "type_score",
    "import_score",
    "graph_score",
    "goal_symbol_count",
    "candidate_symbol_count",
    "shared_symbol_count",
    "candidate_import_count",
    "one_hop_neighbor_count",
)

#: Prefix stamped onto every :class:`~ipfs_datasets_py.logic.hammers.models.PremiseRecord.selection_method`
#: produced when the learned/graph-based selector actually ran (as opposed to
#: a fallback, which is stamped with :data:`~.premise_selection.DETERMINISTIC_BASELINE_METHOD`
#: like any other baseline run). The full method string is
#: ``f"{LEARNED_SELECTION_METHOD_PREFIX}:{model_digest}"`` — the pinned model
#: digest is always part of the audit trail.
LEARNED_SELECTION_METHOD_PREFIX = "learned-selector"

#: Model identifier for :func:`build_default_graph_selector_artifact`'s fixed,
#: hand-authored (not gradient-trained) weighting scheme.
DEFAULT_GRAPH_SELECTOR_MODEL_ID = "graph-selector-default-v1"


def compute_model_digest(payload: Dict[str, Any]) -> str:
    """Compute a deterministic ``"sha256:<hex>"`` content digest for a model
    artifact's identity payload.

    Uses plain SHA-256 over canonical JSON (sorted keys, no whitespace)
    rather than :func:`~ipfs_datasets_py.logic.hammers.corpus.compute_content_digest`
    so that the pinned digest format never depends on whether the optional
    ``multiformats`` package happens to be importable in a given environment
    — a model digest must compare equal across every environment it is
    checked in.
    """

    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


# ---------------------------------------------------------------------------
# Model artifact
# ---------------------------------------------------------------------------


@dataclass
class LearnedModelArtifact:
    """A pinned, content-addressed learned/graph-based scoring model.

    The model is a simple linear combination (passed through a logistic
    squashing function so its output is comparable to the baseline's
    ``[0.0, 1.0]``-ranged Jaccard scores) of the named features produced by
    :func:`extract_learned_features`: ``score = sigmoid(bias + sum(weight[f]
    * feature[f] for f in feature_names))``.

    Attributes:
        schema_version: Schema version of this record.
        model_id: Human-readable identifier of this model (e.g.
            ``"graph-selector-default-v1"`` or a training run's tag).
        feature_version: The :data:`LEARNED_FEATURE_VERSION`-style tag this
            model's weights were fit against. A caller must not score with a
            model whose ``feature_version`` predates a breaking feature
            change without re-fitting.
        feature_names: The ordered feature names this model expects
            (typically :data:`LEARNED_FEATURE_NAMES`, but a model artifact
            defines its own subset/order explicitly rather than silently
            depending on the module's current defaults).
        weights: ``feature_name -> weight`` mapping; every key must be a
            member of ``feature_names``. Missing keys default to weight 0.0
            when scoring (see :func:`score_with_model`).
        bias: Additive bias term.
        description: Free-form, human-readable description of how this
            model was produced (training data revision, method, author...).
        model_digest: The content digest of this artifact's identity payload
            (``model_id``, ``feature_version``, ``feature_names``,
            ``weights``, ``bias``) — see :meth:`compute_digest`. Always
            derived, never independently supplied by a caller outside of
            :meth:`create`/:meth:`from_dict`.
    """

    schema_version: str = SCHEMA_VERSION
    model_id: str = ""
    feature_version: str = LEARNED_FEATURE_VERSION
    feature_names: Tuple[str, ...] = LEARNED_FEATURE_NAMES
    weights: Dict[str, float] = field(default_factory=dict)
    bias: float = 0.0
    description: str = ""
    model_digest: str = ""

    # -- construction -------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        model_id: str,
        weights: Dict[str, float],
        bias: float = 0.0,
        feature_names: Sequence[str] = LEARNED_FEATURE_NAMES,
        feature_version: str = LEARNED_FEATURE_VERSION,
        description: str = "",
    ) -> "LearnedModelArtifact":
        """Build a :class:`LearnedModelArtifact`, deriving ``model_digest``
        from the artifact's own identity payload. This is the only supported
        construction path outside of deserialization via :meth:`from_dict`."""

        artifact = cls(
            model_id=model_id,
            feature_version=feature_version,
            feature_names=tuple(feature_names),
            weights=dict(weights),
            bias=float(bias),
            description=description,
        )
        artifact.model_digest = artifact.compute_digest()
        artifact.validate()
        return artifact

    def _identity_payload(self) -> Dict[str, Any]:
        """The canonical, identity-defining subset of fields used to compute
        ``model_digest``. Deliberately excludes ``model_digest`` itself
        (circular) and ``description`` (documentation should not change a
        model's identity)."""

        return {
            "model_id": self.model_id,
            "feature_version": self.feature_version,
            "feature_names": list(self.feature_names),
            "weights": {key: self.weights[key] for key in sorted(self.weights)},
            "bias": self.bias,
        }

    def compute_digest(self) -> str:
        """Recompute this artifact's content digest from its current
        identity-defining fields (independent of the stamped
        ``model_digest``)."""

        return compute_model_digest(self._identity_payload())

    def verify_digest(self) -> None:
        """Raise :class:`ModelDigestMismatchError` if ``model_digest`` does
        not match a freshly recomputed digest of this artifact's identity
        payload — i.e. if the artifact was tampered with (or corrupted) after
        being pinned."""

        recomputed = self.compute_digest()
        if recomputed != self.model_digest:
            raise ModelDigestMismatchError(
                f"LearnedModelArtifact {self.model_id!r} has model_digest="
                f"{self.model_digest!r}, but its identity payload recomputes to "
                f"{recomputed!r} — the artifact may have been tampered with or "
                "corrupted"
            )

    # -- validation -----------------------------------------------------

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="LearnedModelArtifact")
        _require_nonempty_str(self.model_id, field_name="model_id", owner="LearnedModelArtifact")
        _require_nonempty_str(
            self.feature_version, field_name="feature_version", owner="LearnedModelArtifact"
        )
        if not isinstance(self.feature_names, (tuple, list)) or not all(
            isinstance(item, str) and item for item in self.feature_names
        ):
            raise ModelArtifactError(
                "LearnedModelArtifact.feature_names must be a non-empty sequence of "
                "non-empty strings"
            )
        if len(set(self.feature_names)) != len(self.feature_names):
            raise ModelArtifactError(
                "LearnedModelArtifact.feature_names must not contain duplicates"
            )
        if not self.feature_names:
            raise ModelArtifactError("LearnedModelArtifact.feature_names must be non-empty")
        if not isinstance(self.weights, dict):
            raise ModelArtifactError("LearnedModelArtifact.weights must be a dict")
        feature_name_set = frozenset(self.feature_names)
        for key, value in self.weights.items():
            if not isinstance(key, str) or key not in feature_name_set:
                raise ModelArtifactError(
                    f"LearnedModelArtifact.weights key {key!r} is not a declared "
                    "feature_names entry"
                )
            _require_finite_float(value, field_name=f"weights[{key!r}]", owner="LearnedModelArtifact")
        _require_finite_float(self.bias, field_name="bias", owner="LearnedModelArtifact")
        if not isinstance(self.description, str):
            raise ModelArtifactError("LearnedModelArtifact.description must be a string")
        _require_nonempty_str(
            self.model_digest, field_name="model_digest", owner="LearnedModelArtifact"
        )
        if not self.model_digest.startswith("sha256:"):
            raise ModelArtifactError(
                "LearnedModelArtifact.model_digest must be a 'sha256:<hex>' digest, "
                f"got {self.model_digest!r}"
            )
        self.verify_digest()

    # -- (de)serialization ------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["feature_names"] = list(self.feature_names)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LearnedModelArtifact":
        data = dict(data)
        if "feature_names" in data:
            data["feature_names"] = tuple(data["feature_names"])
        artifact = cls(**data)
        artifact.validate()
        return artifact

    def to_json(self, *, indent: Optional[int] = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "LearnedModelArtifact":
        return cls.from_dict(json.loads(text))

    def save(self, path: Union[str, Path]) -> None:
        Path(path).write_text(self.to_json() + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Union[str, Path]) -> "LearnedModelArtifact":
        """Load and validate a :class:`LearnedModelArtifact` from ``path``.

        Raises:
            FileNotFoundError: If ``path`` does not exist — surfaced
                verbatim so :func:`select_premises_gated` can distinguish
                "model missing" from other load failures.
            ModelArtifactError: If the file exists but is not a well-formed
                artifact (malformed JSON, missing/invalid fields).
            ModelDigestMismatchError: If the artifact's stamped
                ``model_digest`` does not match its recomputed content
                digest.
        """

        resolved = Path(path)
        text = resolved.read_text(encoding="utf-8")
        try:
            return cls.from_json(text)
        except (ModelArtifactError, ModelDigestMismatchError):
            raise
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ModelArtifactError(
                f"failed to load LearnedModelArtifact from {resolved!s}: {exc}"
            ) from exc


def build_default_graph_selector_artifact(
    *,
    model_id: str = DEFAULT_GRAPH_SELECTOR_MODEL_ID,
    description: str = (
        "Fixed, hand-authored linear combination of graph/lexical overlap "
        "features (not gradient-trained). Extends the HAMMER-004 "
        "deterministic baseline's symbol/type/import/graph Jaccard scores "
        "with candidate-size and one-hop-neighbor count features."
    ),
) -> LearnedModelArtifact:
    """Build the module's default, deterministic "graph-based selector"
    artifact.

    See the module docstring's "An honest note on 'learned'" section: this
    is a fixed weighting scheme, not a trained model, but is wrapped in the
    exact same pinned-digest artifact format a genuinely trained model would
    use, and is a legitimate fallback-gated selector under the taskboard's
    "learned or graph-based selector" wording.
    """

    weights = {
        "symbol_score": 3.2,
        "type_score": 1.0,
        "import_score": 1.2,
        "graph_score": 0.8,
        "shared_symbol_count": 0.15,
        "one_hop_neighbor_count": 0.05,
        "goal_symbol_count": 0.0,
        "candidate_symbol_count": -0.01,
        "candidate_import_count": 0.0,
    }
    return LearnedModelArtifact.create(
        model_id=model_id,
        weights=weights,
        bias=-1.6,
        feature_names=LEARNED_FEATURE_NAMES,
        feature_version=LEARNED_FEATURE_VERSION,
        description=description,
    )


# ---------------------------------------------------------------------------
# Reproducible feature extraction
# ---------------------------------------------------------------------------


def extract_learned_features(
    goal: GoalFeatures,
    entry: TheoremEntry,
    manifest: CorpusManifest,
    *,
    expanded_goal_imports: Optional[FrozenSet[str]] = None,
) -> Dict[str, float]:
    """Deterministically extract the named feature vector
    (:data:`LEARNED_FEATURE_NAMES`) for one ``(goal, candidate)`` pair.

    This is a pure function of its arguments: it performs no I/O, uses no
    randomness, and depends on no wall-clock state. It deliberately reuses
    :func:`~.premise_selection.extract_symbols`,
    :func:`~.premise_selection.extract_types`, and the same one-hop
    dependency-graph expansion the HAMMER-004 baseline uses, so the learned
    selector's features are directly comparable to (and a strict superset
    of the *signal* behind) the baseline's four Jaccard scores.

    Args:
        goal: The goal's symbol/type/import features.
        entry: The candidate premise being scored.
        manifest: The corpus manifest the candidate was drawn from (used to
            compute the one-hop import expansion when
            ``expanded_goal_imports`` is not already supplied).
        expanded_goal_imports: Optional precomputed one-hop expansion of
            ``goal.imports`` over ``manifest`` (see
            :func:`~.premise_selection._expand_imports_one_hop`); callers
            scoring many candidates against the same goal should compute
            this once and pass it in to avoid ``O(#candidates * #theorems)``
            recomputation.

    Returns:
        A dict keyed by every name in :data:`LEARNED_FEATURE_NAMES`, with
        finite float values.
    """

    entry_symbols = extract_symbols(entry.statement)
    entry_types = extract_types(entry.statement)
    entry_imports = frozenset(entry.imports)
    expanded = (
        expanded_goal_imports
        if expanded_goal_imports is not None
        else _expand_imports_one_hop(goal.imports, manifest)
    )

    symbol_score = _jaccard(goal.symbols, entry_symbols)
    type_score = _jaccard(goal.types, entry_types)
    import_score = _jaccard(goal.imports, entry_imports)
    graph_score = _jaccard(entry_imports, expanded)
    shared_symbols = goal.symbols & entry_symbols

    return {
        "symbol_score": symbol_score,
        "type_score": type_score,
        "import_score": import_score,
        "graph_score": graph_score,
        "goal_symbol_count": float(len(goal.symbols)),
        "candidate_symbol_count": float(len(entry_symbols)),
        "shared_symbol_count": float(len(shared_symbols)),
        "candidate_import_count": float(len(entry_imports)),
        "one_hop_neighbor_count": float(len(entry_imports & expanded)),
    }


def score_with_model(artifact: LearnedModelArtifact, features: Dict[str, float]) -> float:
    """Score a feature vector with a :class:`LearnedModelArtifact`'s linear
    model, squashed through a logistic function into ``(0.0, 1.0)`` so the
    result is comparable in scale to the baseline's Jaccard-based scores.

    Missing feature keys (not present in ``features``) score as ``0.0``,
    rather than raising, so a model can be evaluated against a feature
    vector computed by a slightly different (but declared-compatible)
    extraction path without failing outright — mismatches are instead
    caught upstream by comparing ``feature_version``.
    """

    total = artifact.bias
    for name in artifact.feature_names:
        weight = artifact.weights.get(name, 0.0)
        total += weight * features.get(name, 0.0)
    # Clamp before exponentiating so a pathological weight/feature product
    # cannot raise OverflowError inside math.exp — the model's *output* must
    # always be a finite float in (0.0, 1.0), never an exception.
    clamped = max(-60.0, min(60.0, total))
    return 1.0 / (1.0 + math.exp(-clamped))


def score_candidates_learned(
    goal: GoalFeatures,
    manifest: CorpusManifest,
    artifact: LearnedModelArtifact,
    *,
    candidates: Optional[Sequence[TheoremEntry]] = None,
) -> List[ScoredCandidate]:
    """Score every candidate premise against ``goal`` using ``artifact``,
    returning them in the same stable ``(-score, theorem_id)`` rank order
    :func:`~.premise_selection.score_candidates` uses.

    Each returned :class:`~.premise_selection.ScoredCandidate` carries the
    model's blended ``score`` alongside the same four baseline sub-scores
    (``symbol_score``/``type_score``/``import_score``/``graph_score``) for
    debuggability/auditability, even though the model's own decision may
    also depend on the additional count-based features not represented in
    that dataclass's fixed shape.
    """

    if not isinstance(manifest, CorpusManifest):
        raise LearnedSelectorError("manifest must be a CorpusManifest")
    if not isinstance(goal, GoalFeatures):
        raise LearnedSelectorError("goal must be a GoalFeatures instance")
    if not isinstance(artifact, LearnedModelArtifact):
        raise LearnedSelectorError("artifact must be a LearnedModelArtifact")
    goal.validate()
    artifact.validate()

    pool = list(candidates) if candidates is not None else manifest.iter_theorems()
    expanded_goal_imports = _expand_imports_one_hop(goal.imports, manifest)

    scored: List[ScoredCandidate] = []
    for entry in pool:
        if not isinstance(entry, TheoremEntry):
            raise LearnedSelectorError("candidates must be TheoremEntry instances")
        features = extract_learned_features(
            goal, entry, manifest, expanded_goal_imports=expanded_goal_imports
        )
        total = score_with_model(artifact, features)
        scored.append(
            ScoredCandidate(
                theorem_id=entry.theorem_id,
                score=total,
                symbol_score=features["symbol_score"],
                type_score=features["type_score"],
                import_score=features["import_score"],
                graph_score=features["graph_score"],
            )
        )

    scored.sort(key=lambda candidate: (-candidate.score, candidate.theorem_id))
    return scored


# ---------------------------------------------------------------------------
# Opt-in configuration
# ---------------------------------------------------------------------------


@dataclass
class LearnedSelectorConfig:
    """Operator-controlled, explicit opt-in configuration for the learned
    premise selector.

    Per the taskboard's acceptance criteria, a learned/graph-based selector
    may be used only with a pinned model digest and explicit opt-in
    configuration; this record is where both are declared. It is
    deliberately a *separate* switch from
    :attr:`~ipfs_datasets_py.logic.hammers.models.HammerPolicy.allow_learned_premise_selector`
    (which is the run-level policy gate): both this config's ``enabled``
    *and* the policy's ``allow_learned_premise_selector`` must be true for
    :func:`select_premises_gated` to even attempt loading a model.

    Attributes:
        schema_version: Schema version of this record.
        enabled: Explicit opt-in switch. Defaults to ``False`` — the
            deterministic baseline is the default with no config at all.
        model_path: Filesystem path to a serialized
            :class:`LearnedModelArtifact` (see :meth:`LearnedModelArtifact.load`).
            Required when ``enabled`` is ``True``.
        pinned_model_digest: The expected ``model_digest`` of the artifact at
            ``model_path``. Required when ``enabled`` is ``True``. If the
            artifact actually loaded does not match this value,
            :func:`select_premises_gated` falls back to the baseline with
            :attr:`SelectorFallbackReason.MODEL_DIGEST_MISMATCH` rather than
            trusting an unpinned/unexpected model.
    """

    schema_version: str = SCHEMA_VERSION
    enabled: bool = False
    model_path: Optional[str] = None
    pinned_model_digest: str = ""

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="LearnedSelectorConfig")
        if not isinstance(self.enabled, bool):
            raise LearnedSelectorConfigError("LearnedSelectorConfig.enabled must be a boolean")
        if self.enabled:
            if not self.model_path or not isinstance(self.model_path, str):
                raise LearnedSelectorConfigError(
                    "LearnedSelectorConfig.model_path must be a non-empty string when "
                    "enabled=True"
                )
            if (
                not self.pinned_model_digest
                or not isinstance(self.pinned_model_digest, str)
                or not self.pinned_model_digest.startswith("sha256:")
            ):
                raise LearnedSelectorConfigError(
                    "LearnedSelectorConfig.pinned_model_digest must be a 'sha256:<hex>' "
                    "string when enabled=True (a learned/graph-based selector may only "
                    "be used with a pinned model digest)"
                )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LearnedSelectorConfig":
        return cls(**dict(data))


# ---------------------------------------------------------------------------
# Fallback bookkeeping
# ---------------------------------------------------------------------------


class SelectorFallbackReason(str, Enum):
    """Why a :func:`select_premises_gated` call used the deterministic
    baseline instead of the learned/graph-based selector."""

    #: The learned selector actually ran; this is not a fallback.
    NONE = "none"
    #: ``LearnedSelectorConfig`` was not supplied, or ``enabled=False``.
    NOT_ENABLED = "not_enabled"
    #: ``HammerPolicy.allow_learned_premise_selector`` was ``False``.
    POLICY_DENIED = "policy_denied"
    #: ``model_path`` did not exist on disk.
    MODEL_MISSING = "model_missing"
    #: The model file existed but failed to parse/validate as a well-formed
    #: :class:`LearnedModelArtifact`.
    MODEL_LOAD_ERROR = "model_load_error"
    #: The loaded artifact's digest did not match
    #: ``LearnedSelectorConfig.pinned_model_digest``.
    MODEL_DIGEST_MISMATCH = "model_digest_mismatch"
    #: The model loaded and matched its pinned digest, but raised an
    #: unexpected exception while scoring candidates.
    SCORING_ERROR = "scoring_error"


@dataclass
class LearnedSelectionResult:
    """The outcome of one :func:`select_premises_gated` call: the actual
    :class:`~.premise_selection.PremiseSelectionResult` produced (by
    whichever selector actually ran), plus an explicit, auditable record of
    which selector that was and why.

    Attributes:
        schema_version: Schema version of this record.
        selection: The :class:`~.premise_selection.PremiseSelectionResult`
            that was actually returned — from the learned selector when
            ``used_learned_selector`` is ``True``, or from
            :func:`~.premise_selection.select_premises` (the baseline)
            otherwise. Always present and always independently valid.
        used_learned_selector: Whether the learned/graph-based selector
            actually produced ``selection`` (``True``) or whether the
            deterministic baseline was used, whether by default or via
            fallback (``False``).
        fallback_reason: Why the baseline was used instead of the learned
            selector; :attr:`SelectorFallbackReason.NONE` when
            ``used_learned_selector`` is ``True``.
        model_id: The learned model's ``model_id``, when it actually ran.
        model_digest: The learned model's pinned ``model_digest``, when it
            actually ran.
        feature_version: The learned model's ``feature_version``, when it
            actually ran.
        latency_ms: Wall-clock latency of the selection call that actually
            ran (baseline or learned), for benchmark/monitoring purposes.
    """

    schema_version: str = SCHEMA_VERSION
    selection: Optional[PremiseSelectionResult] = None
    used_learned_selector: bool = False
    fallback_reason: SelectorFallbackReason = SelectorFallbackReason.NOT_ENABLED
    model_id: Optional[str] = None
    model_digest: Optional[str] = None
    feature_version: Optional[str] = None
    latency_ms: float = 0.0

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="LearnedSelectionResult")
        if not isinstance(self.selection, PremiseSelectionResult):
            raise LearnedSelectorError(
                "LearnedSelectionResult.selection must be a PremiseSelectionResult"
            )
        self.selection.validate()
        if not isinstance(self.used_learned_selector, bool):
            raise LearnedSelectorError(
                "LearnedSelectionResult.used_learned_selector must be a boolean"
            )
        if not isinstance(self.fallback_reason, SelectorFallbackReason):
            raise LearnedSelectorError(
                "LearnedSelectionResult.fallback_reason must be a SelectorFallbackReason"
            )
        if self.used_learned_selector and self.fallback_reason != SelectorFallbackReason.NONE:
            raise LearnedSelectorError(
                "LearnedSelectionResult.used_learned_selector=True requires "
                "fallback_reason=SelectorFallbackReason.NONE"
            )
        if not self.used_learned_selector and self.fallback_reason == SelectorFallbackReason.NONE:
            raise LearnedSelectorError(
                "LearnedSelectionResult.used_learned_selector=False requires a "
                "fallback_reason other than SelectorFallbackReason.NONE"
            )
        if self.used_learned_selector:
            _require_nonempty_str(
                self.model_id or "", field_name="model_id", owner="LearnedSelectionResult"
            )
            _require_nonempty_str(
                self.model_digest or "", field_name="model_digest", owner="LearnedSelectionResult"
            )
            _require_nonempty_str(
                self.feature_version or "",
                field_name="feature_version",
                owner="LearnedSelectionResult",
            )
        _require_finite_float(self.latency_ms, field_name="latency_ms", owner="LearnedSelectionResult")
        if self.latency_ms < 0:
            raise LearnedSelectorError("LearnedSelectionResult.latency_ms must be non-negative")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "selection": self.selection.to_dict() if self.selection is not None else None,
            "used_learned_selector": self.used_learned_selector,
            "fallback_reason": self.fallback_reason.value,
            "model_id": self.model_id,
            "model_digest": self.model_digest,
            "feature_version": self.feature_version,
            "latency_ms": self.latency_ms,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LearnedSelectionResult":
        data = dict(data)
        if isinstance(data.get("selection"), dict):
            data["selection"] = PremiseSelectionResult.from_dict(data["selection"])
        if isinstance(data.get("fallback_reason"), str):
            data["fallback_reason"] = SelectorFallbackReason(data["fallback_reason"])
        result = cls(**data)
        result.validate()
        return result


# ---------------------------------------------------------------------------
# Selection assembly (mirrors premise_selection.select_premises's exclusion /
# cutoff bookkeeping, but over an already-scored ranking rather than
# recomputing scores, so premise_selection.py itself never needs to change).
# ---------------------------------------------------------------------------


def _finalize_selection(
    ranked: List[ScoredCandidate],
    goal: GoalFeatures,
    manifest: CorpusManifest,
    *,
    top_k: int,
    policy: Optional[HammerPolicy],
    exclude_theorem_ids: Optional[Iterable[str]],
    min_score: Optional[float],
    selection_method: str,
    weights: Optional[PremiseSelectionWeights] = None,
) -> PremiseSelectionResult:
    resolved_top_k = _resolve_top_k(top_k, policy=policy)
    excluded_ids = frozenset(str(item) for item in (exclude_theorem_ids or []))
    corpus_revision = manifest.revision

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
                selection_method=selection_method,
                content_digest=entry.content_digest,
            )
        )

    result = PremiseSelectionResult(
        corpus_revision=corpus_revision,
        goal_theorem_id=goal.theorem_id,
        selection_method=selection_method,
        top_k=resolved_top_k,
        weights=weights if weights is not None else PremiseSelectionWeights(),
        selected=selected_premises,
        excluded=excluded_records,
    )
    result.validate()
    return result


def _baseline_result(
    manifest: CorpusManifest,
    goal: GoalFeatures,
    *,
    top_k: int,
    policy: Optional[HammerPolicy],
    weights: Optional[PremiseSelectionWeights],
    exclude_theorem_ids: Optional[Iterable[str]],
    min_score: Optional[float],
    candidates: Optional[Sequence[TheoremEntry]],
    fallback_reason: SelectorFallbackReason,
) -> LearnedSelectionResult:
    start = time.perf_counter()
    selection = select_premises(
        manifest,
        goal,
        top_k=top_k,
        policy=policy,
        weights=weights,
        exclude_theorem_ids=exclude_theorem_ids,
        min_score=min_score,
        candidates=candidates,
    )
    latency_ms = (time.perf_counter() - start) * 1000.0
    result = LearnedSelectionResult(
        selection=selection,
        used_learned_selector=False,
        fallback_reason=fallback_reason,
        latency_ms=latency_ms,
    )
    result.validate()
    return result


# ---------------------------------------------------------------------------
# Top-level gated entry points
# ---------------------------------------------------------------------------


def select_premises_gated(
    manifest: CorpusManifest,
    goal: GoalFeatures,
    *,
    top_k: int,
    policy: Optional[HammerPolicy] = None,
    learned_config: Optional[LearnedSelectorConfig] = None,
    weights: Optional[PremiseSelectionWeights] = None,
    exclude_theorem_ids: Optional[Iterable[str]] = None,
    min_score: Optional[float] = None,
    candidates: Optional[Sequence[TheoremEntry]] = None,
    model_artifact: Optional[LearnedModelArtifact] = None,
) -> LearnedSelectionResult:
    """Select premises for ``goal``, using the learned/graph-based selector
    only when every opt-in gate is open, and falling back to the
    deterministic HAMMER-004 baseline otherwise — this function never raises
    due to a missing, corrupt, mismatched, or misbehaving model.

    Gates, checked in order:

    1. ``learned_config`` must be given and ``learned_config.enabled`` must
       be ``True``, or the baseline runs immediately
       (:attr:`SelectorFallbackReason.NOT_ENABLED`).
    2. If ``policy`` is given, ``policy.allow_learned_premise_selector`` must
       be ``True``, or the baseline runs
       (:attr:`SelectorFallbackReason.POLICY_DENIED`). (A caller that omits
       ``policy`` entirely is trusted to have made that decision
       out-of-band; every hammer entry point that matters supplies a real
       policy.)
    3. The model artifact at ``learned_config.model_path`` (or the
       caller-supplied ``model_artifact``, when given, which skips the disk
       read but is still digest-checked) must load/validate successfully, or
       the baseline runs (:attr:`SelectorFallbackReason.MODEL_MISSING` for a
       missing file, :attr:`SelectorFallbackReason.MODEL_LOAD_ERROR` for a
       malformed one).
    4. The artifact's ``model_digest`` must equal
       ``learned_config.pinned_model_digest``, or the baseline runs
       (:attr:`SelectorFallbackReason.MODEL_DIGEST_MISMATCH`).
    5. Scoring every candidate must not raise, or the baseline runs
       (:attr:`SelectorFallbackReason.SCORING_ERROR`).

    Only once every gate above is satisfied does the learned selector's own
    :class:`~.premise_selection.PremiseSelectionResult` (with
    ``selection_method`` stamped
    ``f"{LEARNED_SELECTION_METHOD_PREFIX}:{model_digest}"``) come back with
    ``used_learned_selector=True``.

    Args:
        manifest: The corpus manifest to draw candidates from.
        goal: The goal's symbol/type/import features.
        top_k: See :func:`~.premise_selection.select_premises`. Enforced
            identically on both the learned and baseline paths (an invalid
            ``top_k`` raises :class:`~.premise_selection.InvalidTopKError`
            regardless of which selector would otherwise have run).
        policy: Optional :class:`~ipfs_datasets_py.logic.hammers.models.HammerPolicy`;
            also gates ``top_k`` against ``policy.max_premises`` exactly like
            the baseline.
        learned_config: Opt-in learned-selector configuration. ``None`` (the
            default) is equivalent to a not-``enabled`` config.
        weights: Baseline feature weights, used only on the baseline path.
        exclude_theorem_ids: See :func:`~.premise_selection.select_premises`.
        min_score: See :func:`~.premise_selection.select_premises`.
        candidates: See :func:`~.premise_selection.select_premises`.
        model_artifact: Optional pre-loaded :class:`LearnedModelArtifact`,
            bypassing the disk read in ``learned_config.model_path`` (e.g.
            for tests or a caller that already cached the artifact). Its
            digest is still checked against ``learned_config.pinned_model_digest``.

    Returns:
        A validated :class:`LearnedSelectionResult`.

    Raises:
        LearnedSelectorConfigError: If ``learned_config.enabled`` is
            ``True`` but the config itself is malformed (missing
            ``model_path``/``pinned_model_digest``) — a caller
            configuration error, not a runtime fallback condition.
        InvalidTopKError: If ``top_k`` is invalid, on either path.
        PremiseSelectionError: If ``manifest``/``goal``/``candidates`` are
            malformed, on either path.
    """

    resolved_config = learned_config if learned_config is not None else LearnedSelectorConfig()
    resolved_config.validate()

    if not resolved_config.enabled:
        return _baseline_result(
            manifest,
            goal,
            top_k=top_k,
            policy=policy,
            weights=weights,
            exclude_theorem_ids=exclude_theorem_ids,
            min_score=min_score,
            candidates=candidates,
            fallback_reason=SelectorFallbackReason.NOT_ENABLED,
        )

    if policy is not None:
        policy.validate()
        if not policy.allow_learned_premise_selector:
            return _baseline_result(
                manifest,
                goal,
                top_k=top_k,
                policy=policy,
                weights=weights,
                exclude_theorem_ids=exclude_theorem_ids,
                min_score=min_score,
                candidates=candidates,
                fallback_reason=SelectorFallbackReason.POLICY_DENIED,
            )

    # Load (or accept a pre-supplied) model artifact.
    artifact: Optional[LearnedModelArtifact]
    if model_artifact is not None:
        if not isinstance(model_artifact, LearnedModelArtifact):
            raise LearnedSelectorError("model_artifact must be a LearnedModelArtifact")
        artifact = model_artifact
    else:
        try:
            artifact = LearnedModelArtifact.load(resolved_config.model_path)  # type: ignore[arg-type]
        except FileNotFoundError:
            return _baseline_result(
                manifest,
                goal,
                top_k=top_k,
                policy=policy,
                weights=weights,
                exclude_theorem_ids=exclude_theorem_ids,
                min_score=min_score,
                candidates=candidates,
                fallback_reason=SelectorFallbackReason.MODEL_MISSING,
            )
        except ModelDigestMismatchError:
            return _baseline_result(
                manifest,
                goal,
                top_k=top_k,
                policy=policy,
                weights=weights,
                exclude_theorem_ids=exclude_theorem_ids,
                min_score=min_score,
                candidates=candidates,
                fallback_reason=SelectorFallbackReason.MODEL_DIGEST_MISMATCH,
            )
        except (ModelArtifactError, OSError):
            return _baseline_result(
                manifest,
                goal,
                top_k=top_k,
                policy=policy,
                weights=weights,
                exclude_theorem_ids=exclude_theorem_ids,
                min_score=min_score,
                candidates=candidates,
                fallback_reason=SelectorFallbackReason.MODEL_LOAD_ERROR,
            )

    try:
        artifact.verify_digest()
    except ModelDigestMismatchError:
        return _baseline_result(
            manifest,
            goal,
            top_k=top_k,
            policy=policy,
            weights=weights,
            exclude_theorem_ids=exclude_theorem_ids,
            min_score=min_score,
            candidates=candidates,
            fallback_reason=SelectorFallbackReason.MODEL_DIGEST_MISMATCH,
        )

    if artifact.model_digest != resolved_config.pinned_model_digest:
        return _baseline_result(
            manifest,
            goal,
            top_k=top_k,
            policy=policy,
            weights=weights,
            exclude_theorem_ids=exclude_theorem_ids,
            min_score=min_score,
            candidates=candidates,
            fallback_reason=SelectorFallbackReason.MODEL_DIGEST_MISMATCH,
        )

    # `top_k`/manifest/goal validity is enforced by _finalize_selection via
    # `_resolve_top_k` and PremiseSelectionResult.validate(); those failures
    # (InvalidTopKError, PremiseSelectionError) are genuine caller errors and
    # must propagate on both paths, not be treated as "model failure".
    try:
        start = time.perf_counter()
        ranked = score_candidates_learned(goal, manifest, artifact, candidates=candidates)
        selection = _finalize_selection(
            ranked,
            goal,
            manifest,
            top_k=top_k,
            policy=policy,
            exclude_theorem_ids=exclude_theorem_ids,
            min_score=min_score,
            selection_method=f"{LEARNED_SELECTION_METHOD_PREFIX}:{artifact.model_digest}",
        )
        latency_ms = (time.perf_counter() - start) * 1000.0
    except (InvalidTopKError, PremiseSelectionError):
        raise
    except Exception:
        return _baseline_result(
            manifest,
            goal,
            top_k=top_k,
            policy=policy,
            weights=weights,
            exclude_theorem_ids=exclude_theorem_ids,
            min_score=min_score,
            candidates=candidates,
            fallback_reason=SelectorFallbackReason.SCORING_ERROR,
        )

    result = LearnedSelectionResult(
        selection=selection,
        used_learned_selector=True,
        fallback_reason=SelectorFallbackReason.NONE,
        model_id=artifact.model_id,
        model_digest=artifact.model_digest,
        feature_version=artifact.feature_version,
        latency_ms=latency_ms,
    )
    result.validate()
    return result


def select_premises_for_theorem_gated(
    manifest: CorpusManifest,
    theorem_id: str,
    *,
    top_k: int,
    policy: Optional[HammerPolicy] = None,
    learned_config: Optional[LearnedSelectorConfig] = None,
    weights: Optional[PremiseSelectionWeights] = None,
    exclude_theorem_ids: Optional[Iterable[str]] = None,
    min_score: Optional[float] = None,
    candidates: Optional[Sequence[TheoremEntry]] = None,
    model_artifact: Optional[LearnedModelArtifact] = None,
) -> LearnedSelectionResult:
    """Convenience wrapper mirroring
    :func:`~.premise_selection.select_premises_for_theorem`: builds the goal
    from an existing corpus entry and self-excludes it, then delegates to
    :func:`select_premises_gated`. This is the shape both
    ``tests/unit_tests/logic/hammers/test_learned_selector.py`` and
    ``benchmarks/bench_itp_hammer_premise_selection.py`` use for held-out
    baseline-vs-learned comparisons.

    Raises:
        KeyError: If ``theorem_id`` does not exist in ``manifest``.
    """

    entry = manifest.get_theorem(theorem_id)
    goal = GoalFeatures.from_theorem_entry(entry)
    return select_premises_gated(
        manifest,
        goal,
        top_k=top_k,
        policy=policy,
        learned_config=learned_config,
        weights=weights,
        exclude_theorem_ids=exclude_theorem_ids,
        min_score=min_score,
        candidates=candidates,
        model_artifact=model_artifact,
    )


# ---------------------------------------------------------------------------
# Held-out recall/latency comparison helpers
# ---------------------------------------------------------------------------


def relevant_theorem_ids_by_import_overlap(
    manifest: CorpusManifest, theorem_id: str
) -> FrozenSet[str]:
    """A reproducible, ground-truth-free proxy for "which premises are
    actually relevant to ``theorem_id``": every *other* theorem in
    ``manifest`` that shares at least one import with it.

    The corpus manifest (HAMMER-003) does not record an explicit
    theorem-to-theorem dependency graph (only each theorem's own
    ``imports``), so this is the same "topically related" proxy the
    HAMMER-004 documentation already describes for held-out evaluation:
    theorems that live in the same import/module neighborhood as
    ``theorem_id`` are treated as the positive set a good selector should
    rank highly. This is intentionally conservative — it never uses
    randomness, network access, or any information not already present in
    the manifest.

    Args:
        manifest: The corpus manifest.
        theorem_id: The (held-out) theorem to compute the relevant set for.

    Returns:
        The ``theorem_id``\\ s (excluding ``theorem_id`` itself) of every
        other manifest theorem sharing at least one import with it.
    """

    target = manifest.get_theorem(theorem_id)
    target_imports = frozenset(target.imports)
    if not target_imports:
        return frozenset()
    relevant = set()
    for entry in manifest.iter_theorems():
        if entry.theorem_id == theorem_id:
            continue
        if frozenset(entry.imports) & target_imports:
            relevant.add(entry.theorem_id)
    return frozenset(relevant)


def compute_recall_at_k(selected_ids: Sequence[str], relevant_ids: Iterable[str]) -> float:
    """Recall@k: the fraction of ``relevant_ids`` that appear anywhere in
    ``selected_ids``.

    Returns ``1.0`` (vacuously — there is nothing to miss) when
    ``relevant_ids`` is empty, rather than raising or returning ``0/0``.
    """

    relevant = frozenset(relevant_ids)
    if not relevant:
        return 1.0
    selected = frozenset(selected_ids)
    return len(relevant & selected) / len(relevant)


def compute_reciprocal_rank(ranked_ids: Sequence[str], relevant_ids: Iterable[str]) -> float:
    """Reciprocal rank of the first relevant id in ``ranked_ids`` (1-indexed
    position), or ``0.0`` if none of ``relevant_ids`` appear in
    ``ranked_ids`` at all.

    Returns ``1.0`` (vacuously) when ``relevant_ids`` is empty.
    """

    relevant = frozenset(relevant_ids)
    if not relevant:
        return 1.0
    for index, candidate_id in enumerate(ranked_ids):
        if candidate_id in relevant:
            return 1.0 / (index + 1)
    return 0.0
