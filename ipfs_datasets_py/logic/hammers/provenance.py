"""Normalize solver proof traces and counterexample evidence (HAMMER-009).

The HAMMER-008 solver portfolio (:mod:`.portfolio`) produces an untrusted
:class:`~.models.SolverAttemptRecord` plus out-of-band
:class:`~.portfolio.SolverAttemptEvidence` (raw stdout/stderr, the exact
command, an input digest, and a short trace excerpt) for every attempt. That
raw evidence is solver-specific free text: a Vampire/E TSTP derivation
listing, a Z3/CVC5 ``sat``/``unsat``/``unknown`` response, an SMT-LIB
unsat-core or model s-expression, and so on.

This module normalizes that raw, heterogeneous text into a single,
content-addressed :class:`NormalizedEvidence` record that is uniform across
solvers and translation targets:

- **Proofs** (:attr:`EvidenceKind.PROOF`) — a structural (not semantic)
  decomposition of a TSTP/TPTP derivation listing into :class:`ProofStep`
  entries (step id, role, inference rule, parent ids, and — when the
  solver's ``file(...)`` annotation names an input axiom — the original
  premise label).
- **Unsat cores** (:attr:`EvidenceKind.UNSAT_CORE`) — the input
  axioms/hypotheses actually referenced by a derivation or reported by an
  SMT-LIB ``(get-unsat-core)``-style response, captured as a
  :class:`NormalizedUnsatCore`.
- **Models** (:attr:`EvidenceKind.MODEL`) and **counterexamples**
  (:attr:`EvidenceKind.COUNTEREXAMPLE`) — a satisfying assignment or
  countermodel parsed from an SMT-LIB ``(model ...)``/``(get-value ...)``
  response (or, best-effort, a TPTP finite-model listing), captured as a
  :class:`NormalizedModel` of :class:`ModelBinding` entries.

Every normalized field that can be traced back to a caller-supplied
:class:`~.models.PremiseRecord` id or a HAMMER-007
:class:`~.translation.TranslationMap` entry is preserved verbatim
(``premise_ids``, ``translation_ids``) or cross-referenced
(``translation_map_refs``, ``NormalizedUnsatCore.matched_premise_ids``) —
never fabricated. A raw identifier that does not match anything supplied by
the caller is left unresolved rather than guessed at.

Trust boundary
--------------
This module never asserts a verified theorem. :attr:`NormalizedEvidence.
recommended_status` is restricted, by construction (see
:meth:`NormalizedEvidence.validate`), to
:attr:`~.models.HammerResultStatus.CANDIDATE`,
:attr:`~.models.HammerResultStatus.COUNTEREXAMPLE`, or
:attr:`~.models.HammerResultStatus.UNKNOWN` — constructing a
``NormalizedEvidence`` with any other status raises ``ValueError``. A
malformed proof/model s-expression, an absent trace (a solver reported a
conclusive verdict but produced no parseable certificate text), or an
unsupported certificate format (anything other than the ``"tstp"``/
``"smtlib"`` text this module can structurally parse) always resolves to
``CANDIDATE`` or ``UNKNOWN`` — never ``VERIFIED``. Only a
:class:`~.models.ReconstructionRecord` produced by the target ITP kernel
(HAMMER-010) may ever promote a run to ``VERIFIED``.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .corpus import compute_content_digest
from .models import (
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    HammerResultStatus,
    SolverAttemptRecord,
    SolverVerdict,
    TranslationTarget,
    ProofCandidateRecord,
)
from .portfolio import PortfolioRunResult, SolverAttemptEvidence
from .translation import TranslationMap, TranslationMapEntry

__all__ = [
    "EvidenceKind",
    "ProofStep",
    "NormalizedUnsatCore",
    "ModelBinding",
    "NormalizedModel",
    "NormalizedEvidence",
    "MalformedEvidenceError",
    "ALLOWED_RECOMMENDED_STATUSES",
    "parse_tstp_proof",
    "unsat_core_from_proof_steps",
    "parse_all_sexprs",
    "parse_smtlib_unsat_core",
    "parse_smtlib_model",
    "parse_tptp_model",
    "normalize_solver_evidence",
    "normalize_certificate",
    "normalize_portfolio_run",
    "build_proof_candidate_record",
    "aggregate_recommended_status",
]


# ---------------------------------------------------------------------------
# Small local validators (kept self-contained rather than importing models.py's
# underscore-prefixed helpers, which are private to that module).
# ---------------------------------------------------------------------------


def _require_nonempty_str(value: Any, *, field_name: str, owner: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{owner}.{field_name} must be a non-empty string")


def _require_schema_version(schema_version: str, *, owner: str) -> None:
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(
            f"{owner}.schema_version={schema_version!r} is not one of the "
            f"supported versions {sorted(SUPPORTED_SCHEMA_VERSIONS)!r}"
        )


class MalformedEvidenceError(ValueError):
    """Raised for programmer errors while constructing normalized evidence.

    Malformed *solver* traces are never raised as exceptions — they are
    reported as data via :attr:`EvidenceKind.MALFORMED` and
    :attr:`NormalizedEvidence.malformed_reason` so a caller always gets a
    well-formed, inspectable result. This exception is reserved for misuse of
    this module's own API (e.g. requesting a
    :class:`~.models.ProofCandidateRecord` from evidence that does not
    recommend ``CANDIDATE``).
    """


# ---------------------------------------------------------------------------
# Normalized record types
# ---------------------------------------------------------------------------


class EvidenceKind:
    """What kind of normalized artifact :class:`NormalizedEvidence` carries.

    Not an :class:`enum.Enum` subclassing ``str`` like the rest of the
    package's enums for a subtle but important reason: plain string
    constants keep the malformed/absent/unsupported *values* trivially
    round-trippable through ``to_dict``/``from_dict`` without an extra enum
    import cycle, while still being usable with ``==`` and in ``frozenset``
    membership checks exactly like the ``str, Enum`` types elsewhere in this
    package.
    """

    PROOF = "proof"
    UNSAT_CORE = "unsat_core"
    MODEL = "model"
    COUNTEREXAMPLE = "counterexample"
    ABSENT = "absent"
    MALFORMED = "malformed"
    UNSUPPORTED = "unsupported"

    _ALL = frozenset({PROOF, UNSAT_CORE, MODEL, COUNTEREXAMPLE, ABSENT, MALFORMED, UNSUPPORTED})

    @classmethod
    def is_valid(cls, value: Any) -> bool:
        return value in cls._ALL


#: The only :class:`~.models.HammerResultStatus` values this module may ever
#: recommend. Constructing a :class:`NormalizedEvidence` with any other
#: status (in particular ``VERIFIED``) raises ``ValueError`` — see the
#: module docstring's trust boundary.
ALLOWED_RECOMMENDED_STATUSES = frozenset(
    {
        HammerResultStatus.CANDIDATE,
        HammerResultStatus.COUNTEREXAMPLE,
        HammerResultStatus.UNKNOWN,
    }
)


@dataclass
class ProofStep:
    """One structurally-decomposed step of a TSTP/TPTP derivation listing.

    The formula text is preserved verbatim as opaque text — this module
    never attempts to re-parse it into a semantic term (that would require
    understanding whatever fragment of TPTP the *solver*, not this
    pipeline's own renderer, chose to emit).

    Attributes:
        step_id: The solver-assigned clause/formula name (e.g. ``"f4"``).
        role: The TPTP role (e.g. ``"axiom"``, ``"plain"``,
            ``"negated_conjecture"``), if present.
        rule: The inference rule name from an ``inference(rule, ...)``
            annotation; ``None`` for an un-derived (leaf/input) step.
        formula: The raw formula text between the role and the annotation.
        parent_ids: Step ids this step's ``inference(...)`` annotation
            cites as parents; empty for a leaf/input step.
        source_name: The original input label from a ``file('src', name)``
            annotation, when present — this is what lets a leaf step be
            traced back to the premise it came from.
    """

    step_id: str
    role: Optional[str] = None
    rule: Optional[str] = None
    formula: Optional[str] = None
    parent_ids: List[str] = field(default_factory=list)
    source_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProofStep":
        data = dict(data)
        data.setdefault("parent_ids", [])
        return cls(**data)


@dataclass
class NormalizedUnsatCore:
    """The set of input axioms/hypotheses a solver actually used.

    Attributes:
        core_ids: Raw solver-side identifiers (a TSTP leaf step's
            ``source_name`` if available else its ``step_id``, or the
            tokens from an SMT-LIB unsat-core response) naming the used
            premises.
        matched_premise_ids: The subset of a caller-supplied
            ``premise_ids`` list that exactly matches an entry in
            ``core_ids`` — the *verified-by-string-match* correspondence
            between "premises we selected" and "premises the solver says it
            used". Never a fuzzy or inferred match.
    """

    core_ids: List[str] = field(default_factory=list)
    matched_premise_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NormalizedUnsatCore":
        data = dict(data)
        data.setdefault("core_ids", [])
        data.setdefault("matched_premise_ids", [])
        return cls(**data)


@dataclass
class ModelBinding:
    """One symbol/value binding of a satisfying assignment or countermodel.

    Attributes:
        symbol: The target-format (TPTP/SMT-LIB) symbol name as printed by
            the solver.
        value: The raw printed value/definition text (kept as opaque text).
        source_name: The original source-level name this symbol maps back
            to, resolved via a :class:`~.translation.TranslationMap`, when a
            match is found; ``None`` when no mapping is available.
    """

    symbol: str
    value: str
    source_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelBinding":
        return cls(**dict(data))


@dataclass
class NormalizedModel:
    """A satisfying assignment (model) or countermodel (counterexample)."""

    bindings: List[ModelBinding] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"bindings": [b.to_dict() for b in self.bindings]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NormalizedModel":
        return cls(bindings=[ModelBinding.from_dict(b) for b in data.get("bindings", [])])


@dataclass
class NormalizedEvidence:
    """Content-addressed, normalized candidate evidence for one solver attempt.

    Attributes:
        schema_version: Schema version of this record.
        evidence_id: Stable identifier of this record — always equal to
            ``content_digest`` (this record *is* content-addressed).
        request_id: Owning ``HammerRequest`` id.
        attempt_id: The :class:`~.models.SolverAttemptRecord` id this
            evidence was normalized from.
        candidate_id: The :class:`~.models.ProofCandidateRecord` id this
            evidence backs, if one has been built (``None`` otherwise).
        kind: What kind of artifact was normalized; see :class:`EvidenceKind`.
        format: The certificate/output format normalized (``"tstp"`` or
            ``"smtlib"``), or ``"unknown"``/the raw unsupported format
            string when nothing could be structurally parsed.
        verdict: The raw, untrusted :class:`~.models.SolverVerdict` this
            evidence was normalized from.
        premise_ids: Caller-supplied premise ids in scope for this attempt,
            preserved verbatim (never filtered or reordered by this module).
        translation_ids: Caller-supplied/attempt-derived
            :class:`~.models.TranslationRecord` ids in scope, preserved
            verbatim.
        translation_map_refs: :class:`~.translation.TranslationMapEntry`
            records whose ``source_name``/``target_name`` exactly matched an
            identifier found in the normalized trace.
        proof_steps: Structural decomposition of a TSTP/TPTP derivation
            listing; empty unless ``kind`` is ``PROOF``.
        unsat_core: The normalized unsat core; set for ``PROOF`` (derived
            from the leaf steps) and ``UNSAT_CORE`` kinds.
        model: The normalized model/countermodel; set for ``MODEL`` and
            ``COUNTEREXAMPLE`` kinds.
        raw_trace_digest: Content digest of the raw stdout/stderr or
            certificate text this evidence was normalized from, when any
            text was available.
        malformed_reason: Required, human-readable explanation when
            ``kind`` is ``MALFORMED`` or ``UNSUPPORTED``.
        recommended_status: The :class:`~.models.HammerResultStatus` this
            evidence recommends. Restricted to
            :data:`ALLOWED_RECOMMENDED_STATUSES` — never ``VERIFIED``.
        content_digest: Deterministic content digest of every field above
            (computed automatically; overriding it is only meant for
            ``from_dict`` round-trips).
    """

    schema_version: str = SCHEMA_VERSION
    evidence_id: str = ""
    request_id: str = ""
    attempt_id: str = ""
    candidate_id: Optional[str] = None
    kind: str = EvidenceKind.ABSENT
    format: str = "unknown"
    verdict: SolverVerdict = SolverVerdict.UNKNOWN
    premise_ids: List[str] = field(default_factory=list)
    translation_ids: List[str] = field(default_factory=list)
    translation_map_refs: List[TranslationMapEntry] = field(default_factory=list)
    proof_steps: List[ProofStep] = field(default_factory=list)
    unsat_core: Optional[NormalizedUnsatCore] = None
    model: Optional[NormalizedModel] = None
    raw_trace_digest: Optional[str] = None
    malformed_reason: Optional[str] = None
    recommended_status: HammerResultStatus = HammerResultStatus.UNKNOWN
    content_digest: str = ""

    def __post_init__(self) -> None:
        # Validation (including the hard "never VERIFIED" trust invariant)
        # runs eagerly at construction time, exactly like HammerResult, so it
        # cannot be bypassed by building an instance and never calling
        # validate().
        self.validate()
        if not self.content_digest:
            self.content_digest = compute_content_digest(self._digest_payload())
        if not self.evidence_id:
            self.evidence_id = self.content_digest

    def validate(self) -> None:  # noqa: C901 - one flat, readable check list
        _require_schema_version(self.schema_version, owner="NormalizedEvidence")
        _require_nonempty_str(self.request_id, field_name="request_id", owner="NormalizedEvidence")
        _require_nonempty_str(self.attempt_id, field_name="attempt_id", owner="NormalizedEvidence")

        if not EvidenceKind.is_valid(self.kind):
            raise ValueError(f"NormalizedEvidence.kind={self.kind!r} is not a known EvidenceKind")
        if not isinstance(self.format, str) or not self.format:
            raise ValueError("NormalizedEvidence.format must be a non-empty string")
        if not isinstance(self.verdict, SolverVerdict):
            raise ValueError("NormalizedEvidence.verdict must be a SolverVerdict")
        if not isinstance(self.recommended_status, HammerResultStatus):
            raise ValueError(
                "NormalizedEvidence.recommended_status must be a HammerResultStatus"
            )

        # --- The core trust-boundary invariant -----------------------------
        if self.recommended_status not in ALLOWED_RECOMMENDED_STATUSES:
            raise ValueError(
                "NormalizedEvidence.recommended_status must be one of "
                f"{sorted(s.value for s in ALLOWED_RECOMMENDED_STATUSES)!r}, got "
                f"{self.recommended_status.value!r} — normalized solver evidence may "
                "never claim a verified result; only a kernel-checked "
                "ReconstructionRecord may do that"
            )

        if not isinstance(self.premise_ids, list) or not all(
            isinstance(p, str) and p.strip() for p in self.premise_ids
        ):
            raise ValueError(
                "NormalizedEvidence.premise_ids must be a list of non-empty strings"
            )
        if not isinstance(self.translation_ids, list) or not all(
            isinstance(t, str) and t.strip() for t in self.translation_ids
        ):
            raise ValueError(
                "NormalizedEvidence.translation_ids must be a list of non-empty strings"
            )
        if not isinstance(self.translation_map_refs, list) or not all(
            isinstance(e, TranslationMapEntry) for e in self.translation_map_refs
        ):
            raise ValueError(
                "NormalizedEvidence.translation_map_refs must contain TranslationMapEntry"
            )
        if not isinstance(self.proof_steps, list) or not all(
            isinstance(s, ProofStep) for s in self.proof_steps
        ):
            raise ValueError("NormalizedEvidence.proof_steps must contain ProofStep")
        if self.unsat_core is not None and not isinstance(self.unsat_core, NormalizedUnsatCore):
            raise ValueError(
                "NormalizedEvidence.unsat_core must be a NormalizedUnsatCore or None"
            )
        if self.model is not None and not isinstance(self.model, NormalizedModel):
            raise ValueError("NormalizedEvidence.model must be a NormalizedModel or None")

        if self.kind in (EvidenceKind.MALFORMED, EvidenceKind.UNSUPPORTED):
            _require_nonempty_str(
                self.malformed_reason, field_name="malformed_reason", owner="NormalizedEvidence"
            )
        if self.kind is EvidenceKind.COUNTEREXAMPLE:
            if self.recommended_status is not HammerResultStatus.COUNTEREXAMPLE:
                raise ValueError(
                    "NormalizedEvidence.kind is COUNTEREXAMPLE but recommended_status is "
                    f"{self.recommended_status.value!r}, not COUNTEREXAMPLE"
                )
        if self.recommended_status is HammerResultStatus.COUNTEREXAMPLE:
            if self.kind is not EvidenceKind.COUNTEREXAMPLE:
                raise ValueError(
                    "NormalizedEvidence.recommended_status is COUNTEREXAMPLE but kind is "
                    f"{self.kind!r}, not COUNTEREXAMPLE"
                )

    def _digest_payload(self) -> Dict[str, Any]:
        payload = self.to_dict()
        payload.pop("evidence_id", None)
        payload.pop("content_digest", None)
        return payload

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "request_id": self.request_id,
            "attempt_id": self.attempt_id,
            "candidate_id": self.candidate_id,
            "kind": self.kind,
            "format": self.format,
            "verdict": self.verdict.value,
            "premise_ids": list(self.premise_ids),
            "translation_ids": list(self.translation_ids),
            "translation_map_refs": [e.to_dict() for e in self.translation_map_refs],
            "proof_steps": [s.to_dict() for s in self.proof_steps],
            "unsat_core": self.unsat_core.to_dict() if self.unsat_core is not None else None,
            "model": self.model.to_dict() if self.model is not None else None,
            "raw_trace_digest": self.raw_trace_digest,
            "malformed_reason": self.malformed_reason,
            "recommended_status": self.recommended_status.value,
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NormalizedEvidence":
        data = dict(data)
        data["verdict"] = SolverVerdict(data["verdict"])
        data["recommended_status"] = HammerResultStatus(data["recommended_status"])
        data["translation_map_refs"] = [
            TranslationMapEntry.from_dict(e) for e in data.get("translation_map_refs", [])
        ]
        data["proof_steps"] = [ProofStep.from_dict(s) for s in data.get("proof_steps", [])]
        data["unsat_core"] = (
            NormalizedUnsatCore.from_dict(data["unsat_core"])
            if data.get("unsat_core")
            else None
        )
        data["model"] = (
            NormalizedModel.from_dict(data["model"]) if data.get("model") else None
        )
        return cls(**data)


# ---------------------------------------------------------------------------
# TSTP/TPTP structural proof-trace normalization
# ---------------------------------------------------------------------------

_TSTP_HEAD_RE = re.compile(r"\b(cnf|fof|tff)\s*\(")


def _find_matching_paren(text: str, open_idx: int) -> Optional[int]:
    """Return the index of the ``)`` matching the ``(`` at ``open_idx``.

    Respects nested ``()``/``[]`` and single/double-quoted strings so a
    formula body containing e.g. ``'input.p'`` or ``[X, Y]`` does not
    prematurely close the outer statement. Returns ``None`` if the text ends
    before the matching close is found (an unbalanced/truncated trace).
    """

    depth = 0
    in_quote: Optional[str] = None
    i = open_idx
    n = len(text)
    while i < n:
        ch = text[i]
        if in_quote is not None:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == in_quote:
                in_quote = None
        elif ch in ("'", '"'):
            in_quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _split_top_level(text: str) -> List[str]:
    """Split ``text`` on top-level commas only (respecting nesting/quotes)."""

    parts: List[str] = []
    current: List[str] = []
    depth = 0
    in_quote: Optional[str] = None
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_quote is not None:
            current.append(ch)
            if ch == "\\" and i + 1 < n:
                current.append(text[i + 1])
                i += 2
                continue
            if ch == in_quote:
                in_quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            in_quote = ch
            current.append(ch)
        elif ch in "([":
            depth += 1
            current.append(ch)
        elif ch in ")]":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    parts.append("".join(current))
    return [p.strip() for p in parts]


def _parse_tstp_annotation(
    annotation: Optional[str],
) -> Tuple[Optional[str], List[str], Optional[str]]:
    """Parse a TSTP annotation into ``(rule, parent_ids, source_name)``."""

    if annotation is None or not annotation.strip():
        return None, [], None
    annotation = annotation.strip()

    file_match = re.match(r"^file\s*\((.*)\)$", annotation, re.DOTALL)
    if file_match:
        inner = _split_top_level(file_match.group(1))
        source_name = None
        if len(inner) > 1:
            source_name = inner[1].strip().strip("'\"") or None
        return None, [], source_name

    inference_match = re.match(r"^inference\s*\((.*)\)$", annotation, re.DOTALL)
    if inference_match:
        inner = _split_top_level(inference_match.group(1))
        rule = inner[0].strip().strip("'\"") if inner and inner[0].strip() else None
        parent_ids: List[str] = []
        if len(inner) > 2:
            plist = inner[2].strip()
            if plist.startswith("[") and plist.endswith("]"):
                parent_ids = [
                    p.strip() for p in _split_top_level(plist[1:-1]) if p.strip()
                ]
        return rule, parent_ids, None

    introduced_match = re.match(r"^introduced\s*\(", annotation)
    if introduced_match:
        return "introduced", [], None

    # Unrecognized annotation shape: keep the raw text as an opaque "rule"
    # for audit rather than silently discarding it.
    return annotation, [], None


def parse_tstp_proof(text: str) -> Tuple[List[ProofStep], Optional[str]]:
    """Structurally normalize a TSTP/TPTP derivation listing.

    This is a *structural* normalizer: it recovers the clause/formula id,
    role, inference rule, parent references, and (for a ``file(...)``
    annotated leaf) the original input label — it never attempts to
    semantically parse the formula body itself, which is kept as opaque
    text.

    Args:
        text: Raw stdout (or a standalone certificate) containing zero or
            more ``cnf(...)``, ``fof(...)``, or ``tff(...)`` statements.

    Returns:
        A ``(steps, malformed_reason)`` pair. ``malformed_reason`` is
        ``None`` and ``steps`` may be empty when no derivation statements are
        present at all (an *absent* trace, not a malformed one — the
        caller distinguishes the two). ``malformed_reason`` is set (and
        ``steps`` is empty) when a statement is present but its
        parentheses are unbalanced, its terminating ``.`` is missing, or it
        does not have at least a name, a role, and a formula.
    """

    steps: List[ProofStep] = []
    n = len(text)
    pos = 0
    while True:
        match = _TSTP_HEAD_RE.search(text, pos)
        if match is None:
            break
        start = match.start()
        open_paren = match.end() - 1
        end_paren = _find_matching_paren(text, open_paren)
        if end_paren is None:
            return [], (
                f"unbalanced parentheses in TSTP statement starting at offset {start}"
            )
        j = end_paren + 1
        while j < n and text[j].isspace():
            j += 1
        if j >= n or text[j] != ".":
            return [], (
                f"missing terminating '.' for TSTP statement starting at offset {start}"
            )

        inner = text[open_paren + 1 : end_paren]
        parts = _split_top_level(inner)
        if len(parts) < 3:
            return [], (
                f"malformed TSTP statement starting at offset {start}: expected at "
                "least a name, a role, and a formula"
            )

        step_id = parts[0].strip()
        role = parts[1].strip() or None
        formula = parts[2].strip() or None
        annotation = parts[3] if len(parts) > 3 else None
        rule, parent_ids, source_name = _parse_tstp_annotation(annotation)

        if not step_id:
            return [], f"TSTP statement starting at offset {start} has an empty name"

        steps.append(
            ProofStep(
                step_id=step_id,
                role=role,
                rule=rule,
                formula=formula,
                parent_ids=parent_ids,
                source_name=source_name,
            )
        )
        pos = j + 1

    return steps, None


def unsat_core_from_proof_steps(steps: Sequence[ProofStep]) -> NormalizedUnsatCore:
    """Derive the used-premise unsat core from a parsed derivation listing.

    A TSTP derivation listing only ever contains clauses that were actually
    used to reach the refutation, so the "core" is simply every un-derived
    (leaf, ``rule is None``) step — preferring its original ``source_name``
    (from a ``file(...)`` annotation) over the solver-internal ``step_id``
    when one is available, so the core names match what the caller
    originally supplied wherever possible.
    """

    core_ids: List[str] = []
    seen = set()
    for step in steps:
        if step.rule is not None:
            continue
        identifier = step.source_name or step.step_id
        if identifier and identifier not in seen:
            seen.add(identifier)
            core_ids.append(identifier)
    return NormalizedUnsatCore(core_ids=core_ids)


def parse_tptp_model(text: str) -> Tuple[Optional[NormalizedModel], Optional[str]]:
    """Best-effort normalization of a TPTP finite-model/countermodel listing.

    Reuses :func:`parse_tstp_proof`'s structural scanner (a finite-model
    listing is emitted with the same ``cnf(...)``/``fof(...)`` clause
    syntax, just with different roles such as ``fi_domain``/
    ``fi_functors``/``fi_predicates``) and reinterprets each recovered step
    as one binding whose ``value`` is the clause's own formula text.
    """

    steps, reason = parse_tstp_proof(text)
    if reason is not None:
        return None, reason
    if not steps:
        return None, None
    bindings = [ModelBinding(symbol=s.step_id, value=s.formula or "") for s in steps]
    return NormalizedModel(bindings=bindings), None


# ---------------------------------------------------------------------------
# SMT-LIB s-expression normalization
# ---------------------------------------------------------------------------

_SEXPR_TOKEN_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\(|\)|[^\s()]+')


def _tokenize_sexpr(text: str) -> List[str]:
    return _SEXPR_TOKEN_RE.findall(text)


def _parse_sexpr_at(tokens: List[str], idx: int) -> Tuple[Any, int]:
    if idx >= len(tokens):
        raise ValueError("unexpected end of input while parsing an s-expression")
    tok = tokens[idx]
    if tok == "(":
        items: List[Any] = []
        idx += 1
        while idx < len(tokens) and tokens[idx] != ")":
            item, idx = _parse_sexpr_at(tokens, idx)
            items.append(item)
        if idx >= len(tokens):
            raise ValueError("unbalanced parentheses in s-expression")
        return items, idx + 1
    if tok == ")":
        raise ValueError("unexpected ')' in s-expression")
    return tok, idx + 1


def parse_all_sexprs(text: str) -> List[Any]:
    """Parse ``text`` into a list of top-level s-expressions.

    Each s-expression is either an atom (``str``) or a (possibly nested)
    ``list``. Raises ``ValueError`` for unbalanced parentheses — callers
    catch this and report the trace as :attr:`EvidenceKind.MALFORMED`
    rather than propagating an exception.
    """

    tokens = _tokenize_sexpr(text)
    exprs: List[Any] = []
    idx = 0
    while idx < len(tokens):
        expr, idx = _parse_sexpr_at(tokens, idx)
        exprs.append(expr)
    return exprs


def _render_sexpr(expr: Any) -> str:
    if isinstance(expr, list):
        return "(" + " ".join(_render_sexpr(e) for e in expr) + ")"
    return str(expr)


def parse_smtlib_unsat_core(text: str) -> Tuple[Optional[NormalizedUnsatCore], Optional[str]]:
    """Normalize an SMT-LIB ``(get-unsat-core)``-style response.

    Looks for a flat top-level list of atoms (e.g. ``(a1 a2 a3)``), the
    literal shape a conforming solver prints in response to
    ``(get-unsat-core)``.

    Returns:
        ``(core, None)`` on success, ``(None, None)`` when nothing that
        looks like a core is present (an *absent* core, not malformed), or
        ``(None, reason)`` when the text cannot even be parsed as balanced
        s-expressions.
    """

    if not text.strip():
        return None, None
    try:
        exprs = parse_all_sexprs(text)
    except ValueError as exc:
        return None, f"malformed SMT-LIB unsat-core response: {exc}"

    for expr in exprs:
        if isinstance(expr, list) and expr and all(isinstance(e, str) for e in expr):
            return NormalizedUnsatCore(core_ids=[str(e) for e in expr]), None
    return None, None


def _bindings_from_define_funs(forms: Sequence[Any]) -> List[ModelBinding]:
    bindings: List[ModelBinding] = []
    for form in forms:
        if isinstance(form, list) and len(form) >= 2 and form[0] == "define-fun":
            name = str(form[1])
            value = _render_sexpr(form[-1]) if len(form) > 1 else ""
            bindings.append(ModelBinding(symbol=name, value=value))
    return bindings


def parse_smtlib_model(text: str) -> Tuple[Optional[NormalizedModel], Optional[str]]:
    """Normalize an SMT-LIB ``(get-model)``/``(get-value ...)``-style response.

    Recognizes three shapes: a ``(model (define-fun ...) ...)`` wrapper, a
    bare top-level list of ``(define-fun ...)`` forms (no ``model``
    wrapper), and a ``((name value) ...)`` list as printed by
    ``(get-value (...))``.

    Returns:
        ``(model, None)`` on success, ``(None, None)`` when nothing that
        looks like a model is present, or ``(None, reason)`` when the text
        cannot be parsed as balanced s-expressions.
    """

    if not text.strip():
        return None, None
    try:
        exprs = parse_all_sexprs(text)
    except ValueError as exc:
        return None, f"malformed SMT-LIB model response: {exc}"

    for expr in exprs:
        if not isinstance(expr, list) or not expr:
            continue
        if expr[0] == "model":
            bindings = _bindings_from_define_funs(expr[1:])
            if bindings:
                return NormalizedModel(bindings=bindings), None
            continue
        if all(isinstance(e, list) and e and e[0] == "define-fun" for e in expr):
            bindings = _bindings_from_define_funs(expr)
            if bindings:
                return NormalizedModel(bindings=bindings), None
            continue
        if all(isinstance(e, list) and len(e) == 2 and isinstance(e[0], str) for e in expr):
            bindings = [
                ModelBinding(symbol=str(e[0]), value=_render_sexpr(e[1])) for e in expr
            ]
            return NormalizedModel(bindings=bindings), None
    return None, None


# ---------------------------------------------------------------------------
# Translation-map / premise cross-referencing
# ---------------------------------------------------------------------------


def _match_premise_ids(identifiers: Iterable[str], premise_ids: Sequence[str]) -> List[str]:
    """Return the subset of ``premise_ids`` that literally appears in
    ``identifiers``. A conservative, exact-string-match cross-reference —
    never a fuzzy or inferred one."""

    id_set = set(identifiers)
    return sorted({p for p in premise_ids if p in id_set})


def _translation_map_refs(
    identifiers: Iterable[str],
    translation_map: Optional[TranslationMap],
    target: TranslationTarget,
) -> List[TranslationMapEntry]:
    """Return every :class:`~.translation.TranslationMapEntry` for
    ``target`` whose ``source_name`` or ``target_name`` exactly matches one
    of ``identifiers``."""

    if translation_map is None:
        return []
    id_set = set(identifiers)
    refs = []
    for entry in translation_map.entries:
        if entry.target is not target:
            continue
        if entry.source_name in id_set or entry.target_name in id_set:
            refs.append(entry)
    return refs


def _attach_source_names(
    model: NormalizedModel,
    translation_map: Optional[TranslationMap],
    target: TranslationTarget,
) -> None:
    """Resolve each binding's ``source_name`` via a reverse lookup (solver
    symbols are target-format names, so this matches against
    ``target_name``, falling back to ``source_name`` for exact echoes)."""

    if translation_map is None:
        return
    for binding in model.bindings:
        for entry in translation_map.entries:
            if entry.target is not target:
                continue
            if entry.target_name == binding.symbol or entry.source_name == binding.symbol:
                binding.source_name = entry.source_name
                break


# ---------------------------------------------------------------------------
# Top-level normalization entry points
# ---------------------------------------------------------------------------

_TARGET_FORMAT: Dict[TranslationTarget, str] = {
    TranslationTarget.TPTP: "tstp",
    TranslationTarget.SMTLIB: "smtlib",
}
_SUPPORTED_FORMATS = frozenset(_TARGET_FORMAT.values())
_FORMAT_TARGET: Dict[str, TranslationTarget] = {v: k for k, v in _TARGET_FORMAT.items()}

#: Verdicts that claim a proof/refutation (never trusted on their own).
_PROOF_VERDICTS = frozenset({SolverVerdict.PROVED, SolverVerdict.UNSAT})
#: Verdicts that claim a satisfying model without disproving a conjecture.
_MODEL_VERDICTS = frozenset({SolverVerdict.SAT})
#: Verdicts that claim a countermodel to a conjecture (TPTP ``CounterSatisfiable``).
_COUNTEREXAMPLE_VERDICTS = frozenset({SolverVerdict.DISPROVED})
#: Verdicts with no conclusive claim at all — nothing to normalize.
_NO_EVIDENCE_VERDICTS = frozenset(
    {SolverVerdict.UNKNOWN, SolverVerdict.TIMEOUT, SolverVerdict.ERROR}
)

assert (
    _PROOF_VERDICTS | _MODEL_VERDICTS | _COUNTEREXAMPLE_VERDICTS | _NO_EVIDENCE_VERDICTS
    == frozenset(SolverVerdict)
), "every SolverVerdict must be classified exactly once"


def _normalize(
    *,
    request_id: str,
    attempt_id: str,
    text: str,
    fmt: str,
    verdict: SolverVerdict,
    premise_ids: Sequence[str],
    translation_ids: Sequence[str],
    translation_map: Optional[TranslationMap],
    candidate_id: Optional[str],
    raw_trace_digest: Optional[str],
) -> NormalizedEvidence:
    common: Dict[str, Any] = dict(
        request_id=request_id,
        attempt_id=attempt_id,
        candidate_id=candidate_id,
        format=fmt or "unknown",
        verdict=verdict,
        premise_ids=list(premise_ids),
        translation_ids=list(translation_ids),
        raw_trace_digest=raw_trace_digest,
    )

    if verdict in _NO_EVIDENCE_VERDICTS:
        return NormalizedEvidence(
            kind=EvidenceKind.ABSENT, recommended_status=HammerResultStatus.UNKNOWN, **common
        )

    if fmt not in _SUPPORTED_FORMATS:
        return NormalizedEvidence(
            kind=EvidenceKind.UNSUPPORTED,
            malformed_reason=(
                f"evidence format {fmt!r} is not structurally normalizable by this module "
                f"(supported: {sorted(_SUPPORTED_FORMATS)!r})"
            ),
            recommended_status=HammerResultStatus.UNKNOWN,
            **common,
        )

    if not text.strip():
        # An absent trace is *never* reported as COUNTEREXAMPLE, even when the
        # raw verdict was DISPROVED: EvidenceKind.COUNTEREXAMPLE means an
        # actual countermodel was normalized, and HammerResultStatus.
        # COUNTEREXAMPLE requires that kind (see NormalizedEvidence.
        # validate). Per the HAMMER-009 acceptance contract, an absent trace
        # always resolves to CANDIDATE (there was still a solver claim, just
        # nothing to show for it) rather than UNKNOWN, so downstream
        # reconstruction/fallback logic still has something to work with.
        return NormalizedEvidence(
            kind=EvidenceKind.ABSENT,
            recommended_status=HammerResultStatus.CANDIDATE,
            **common,
        )

    if verdict in _PROOF_VERDICTS:
        return _normalize_proof(text, fmt, translation_map, common)
    return _normalize_model(text, fmt, verdict, translation_map, common)


def _normalize_proof(
    text: str,
    fmt: str,
    translation_map: Optional[TranslationMap],
    common: Dict[str, Any],
) -> NormalizedEvidence:
    if fmt == "tstp":
        steps, reason = parse_tstp_proof(text)
        if reason is not None:
            return NormalizedEvidence(
                kind=EvidenceKind.MALFORMED,
                malformed_reason=reason,
                recommended_status=HammerResultStatus.UNKNOWN,
                **common,
            )
        if not steps:
            return NormalizedEvidence(
                kind=EvidenceKind.ABSENT, recommended_status=HammerResultStatus.CANDIDATE, **common
            )
        core = unsat_core_from_proof_steps(steps)
        core.matched_premise_ids = _match_premise_ids(core.core_ids, common["premise_ids"])
        refs = _translation_map_refs(core.core_ids, translation_map, TranslationTarget.TPTP)
        return NormalizedEvidence(
            kind=EvidenceKind.PROOF,
            proof_steps=steps,
            unsat_core=core,
            translation_map_refs=refs,
            recommended_status=HammerResultStatus.CANDIDATE,
            **common,
        )

    # fmt == "smtlib"
    core, reason = parse_smtlib_unsat_core(text)
    if reason is not None:
        return NormalizedEvidence(
            kind=EvidenceKind.MALFORMED,
            malformed_reason=reason,
            recommended_status=HammerResultStatus.UNKNOWN,
            **common,
        )
    if core is None:
        return NormalizedEvidence(
            kind=EvidenceKind.ABSENT, recommended_status=HammerResultStatus.CANDIDATE, **common
        )
    core.matched_premise_ids = _match_premise_ids(core.core_ids, common["premise_ids"])
    refs = _translation_map_refs(core.core_ids, translation_map, TranslationTarget.SMTLIB)
    return NormalizedEvidence(
        kind=EvidenceKind.UNSAT_CORE,
        unsat_core=core,
        translation_map_refs=refs,
        recommended_status=HammerResultStatus.CANDIDATE,
        **common,
    )


def _normalize_model(
    text: str,
    fmt: str,
    verdict: SolverVerdict,
    translation_map: Optional[TranslationMap],
    common: Dict[str, Any],
) -> NormalizedEvidence:
    is_counterexample = verdict in _COUNTEREXAMPLE_VERDICTS
    recommended_present = (
        HammerResultStatus.COUNTEREXAMPLE if is_counterexample else HammerResultStatus.CANDIDATE
    )
    target = _FORMAT_TARGET[fmt]

    if fmt == "tstp":
        model, reason = parse_tptp_model(text)
    else:
        model, reason = parse_smtlib_model(text)

    if reason is not None:
        return NormalizedEvidence(
            kind=EvidenceKind.MALFORMED,
            malformed_reason=reason,
            recommended_status=HammerResultStatus.UNKNOWN,
            **common,
        )
    if model is None:
        # Same rule as the empty-text case in `_normalize`: an absent model
        # is reported as ABSENT/CANDIDATE, never as COUNTEREXAMPLE — that
        # kind is reserved for an actually-normalized countermodel.
        return NormalizedEvidence(
            kind=EvidenceKind.ABSENT, recommended_status=HammerResultStatus.CANDIDATE, **common
        )

    _attach_source_names(model, translation_map, target)
    refs = _translation_map_refs([b.symbol for b in model.bindings], translation_map, target)
    kind = EvidenceKind.COUNTEREXAMPLE if is_counterexample else EvidenceKind.MODEL
    return NormalizedEvidence(
        kind=kind,
        model=model,
        translation_map_refs=refs,
        recommended_status=recommended_present,
        **common,
    )


def normalize_solver_evidence(
    *,
    request_id: str,
    attempt: SolverAttemptRecord,
    evidence: Optional[SolverAttemptEvidence] = None,
    raw_stdout: str = "",
    raw_stderr: str = "",
    premise_ids: Sequence[str] = (),
    translation_ids: Optional[Sequence[str]] = None,
    translation_map: Optional[TranslationMap] = None,
    candidate_id: Optional[str] = None,
) -> NormalizedEvidence:
    """Normalize one HAMMER-008 solver attempt's raw output into evidence.

    Args:
        request_id: Owning ``HammerRequest`` id.
        attempt: The untrusted :class:`~.models.SolverAttemptRecord` (its
            ``target`` selects the TPTP/SMT-LIB parser and its ``verdict``
            selects the proof/model/absent branch).
        evidence: The matching :class:`~.portfolio.SolverAttemptEvidence`
            carrying the raw stdout/stderr, when available. Takes
            precedence over ``raw_stdout``/``raw_stderr`` if both are given.
        raw_stdout: Raw solver stdout, used when ``evidence`` is ``None``
            (e.g. when normalizing evidence outside of a live portfolio
            run, such as from a persisted receipt).
        raw_stderr: Raw solver stderr, same caveat as ``raw_stdout``.
        premise_ids: The :class:`~.models.PremiseRecord` ids that were in
            scope for this attempt's translation; preserved verbatim on the
            result and cross-referenced against any parsed unsat core.
        translation_ids: :class:`~.models.TranslationRecord` ids in scope;
            defaults to ``[attempt.translation_id]``.
        translation_map: The HAMMER-007 :class:`~.translation.TranslationMap`
            to cross-reference parsed identifiers against.
        candidate_id: A :class:`~.models.ProofCandidateRecord` id this
            evidence will back, if already known.

    Returns:
        A :class:`NormalizedEvidence` whose ``recommended_status`` is
        always one of ``CANDIDATE``/``COUNTEREXAMPLE``/``UNKNOWN``.
    """

    stdout = evidence.raw_stdout if evidence is not None else raw_stdout
    stderr = evidence.raw_stderr if evidence is not None else raw_stderr
    resolved_translation_ids = (
        list(translation_ids) if translation_ids is not None else [attempt.translation_id]
    )
    raw_trace_digest = (
        compute_content_digest({"stdout": stdout, "stderr": stderr})
        if (stdout or stderr)
        else None
    )
    fmt = _TARGET_FORMAT.get(attempt.target, "")

    return _normalize(
        request_id=request_id,
        attempt_id=attempt.attempt_id,
        text=stdout,
        fmt=fmt,
        verdict=attempt.verdict,
        premise_ids=premise_ids,
        translation_ids=resolved_translation_ids,
        translation_map=translation_map,
        candidate_id=candidate_id,
        raw_trace_digest=raw_trace_digest,
    )


def normalize_certificate(
    *,
    request_id: str,
    attempt_id: str,
    verdict: SolverVerdict,
    certificate: Optional[str],
    certificate_format: Optional[str],
    premise_ids: Sequence[str] = (),
    translation_ids: Sequence[str] = (),
    translation_map: Optional[TranslationMap] = None,
    candidate_id: Optional[str] = None,
) -> NormalizedEvidence:
    """Normalize a standalone certificate string (e.g. from an already
    persisted :class:`~.models.ProofCandidateRecord`) rather than a live
    solver attempt's raw stdout/stderr.

    Any ``certificate_format`` other than ``"tstp"``/``"smtlib"`` (for
    example ``"lfsc"``, ``"alethe"``, or an unset/unknown format) always
    resolves to :attr:`EvidenceKind.UNSUPPORTED` /
    :attr:`~.models.HammerResultStatus.UNKNOWN` — this module has no
    structural parser for those formats and refuses to guess.
    """

    fmt = (certificate_format or "").strip().lower()
    text = certificate or ""
    raw_trace_digest = compute_content_digest({"certificate": certificate}) if certificate else None

    return _normalize(
        request_id=request_id,
        attempt_id=attempt_id,
        text=text,
        fmt=fmt,
        verdict=verdict,
        premise_ids=premise_ids,
        translation_ids=translation_ids,
        translation_map=translation_map,
        candidate_id=candidate_id,
        raw_trace_digest=raw_trace_digest,
    )


def normalize_portfolio_run(
    run_result: PortfolioRunResult,
    *,
    request_id: Optional[str] = None,
    premise_ids: Sequence[str] = (),
    translation_map: Optional[TranslationMap] = None,
) -> Dict[str, NormalizedEvidence]:
    """Normalize every attempt in a HAMMER-008 :class:`~.portfolio.PortfolioRunResult`.

    Returns:
        A mapping of ``attempt_id -> NormalizedEvidence`` covering every
        attempt in ``run_result.attempts`` (denied/never-executed attempts,
        which carry no :class:`~.models.SolverAttemptRecord`, are not
        included).
    """

    resolved_request_id = request_id or run_result.request_id
    normalized: Dict[str, NormalizedEvidence] = {}
    for attempt in run_result.attempts:
        attempt_evidence = run_result.evidence.get(attempt.attempt_id)
        normalized[attempt.attempt_id] = normalize_solver_evidence(
            request_id=resolved_request_id,
            attempt=attempt,
            evidence=attempt_evidence,
            premise_ids=premise_ids,
            translation_map=translation_map,
        )
    return normalized


def build_proof_candidate_record(
    normalized: NormalizedEvidence,
    *,
    candidate_id: str,
    request_id: str,
    solver_attempt_id: str,
    certificate: Optional[str] = None,
    certificate_format: Optional[str] = None,
) -> ProofCandidateRecord:
    """Build an untrusted :class:`~.models.ProofCandidateRecord` from
    ``normalized`` evidence that recommends ``CANDIDATE``.

    The candidate's ``premise_ids`` prefers the unsat core's
    ``matched_premise_ids`` (the premises the solver is corroborated to
    have actually used) and falls back to ``normalized.premise_ids`` (the
    full selection in scope) when no core was parsed.

    Raises:
        MalformedEvidenceError: If ``normalized.recommended_status`` is not
            :attr:`~.models.HammerResultStatus.CANDIDATE` — this module
            deliberately refuses to build a "candidate proof" record out of
            evidence that only recommends ``COUNTEREXAMPLE`` or ``UNKNOWN``,
            since :class:`~.models.ProofCandidateRecord` specifically means
            "an untrusted candidate *proof*".
    """

    if normalized.recommended_status is not HammerResultStatus.CANDIDATE:
        raise MalformedEvidenceError(
            "build_proof_candidate_record requires normalized.recommended_status to be "
            f"CANDIDATE, got {normalized.recommended_status.value!r}"
        )

    premise_ids: List[str]
    if normalized.unsat_core is not None and normalized.unsat_core.matched_premise_ids:
        premise_ids = list(normalized.unsat_core.matched_premise_ids)
    else:
        premise_ids = list(normalized.premise_ids)

    return ProofCandidateRecord(
        candidate_id=candidate_id,
        request_id=request_id,
        solver_attempt_id=solver_attempt_id,
        premise_ids=premise_ids,
        certificate=certificate,
        certificate_format=certificate_format,
    )


#: Ascending priority among the statuses this module ever recommends, used
#: by :func:`aggregate_recommended_status` to pick the "most informative"
#: outcome across multiple normalized attempts for the same request.
_STATUS_PRIORITY: Dict[HammerResultStatus, int] = {
    HammerResultStatus.CANDIDATE: 0,
    HammerResultStatus.COUNTEREXAMPLE: 1,
    HammerResultStatus.UNKNOWN: 2,
}


def aggregate_recommended_status(
    evidences: Iterable[NormalizedEvidence],
) -> HammerResultStatus:
    """Pick the single most informative recommended status across several
    normalized attempts (e.g. every attempt in one portfolio run).

    Preference order is ``CANDIDATE`` > ``COUNTEREXAMPLE`` > ``UNKNOWN``
    (a usable candidate proof is more actionable than a countermodel, which
    in turn is more actionable than "nothing conclusive"). Returns
    ``UNKNOWN`` for an empty input — never ``VERIFIED``, by construction,
    since every ``NormalizedEvidence.recommended_status`` is already
    restricted to this same three-value set.
    """

    best: Optional[HammerResultStatus] = None
    best_priority = None
    for ev in evidences:
        priority = _STATUS_PRIORITY[ev.recommended_status]
        if best_priority is None or priority < best_priority:
            best = ev.recommended_status
            best_priority = priority
    return best if best is not None else HammerResultStatus.UNKNOWN
