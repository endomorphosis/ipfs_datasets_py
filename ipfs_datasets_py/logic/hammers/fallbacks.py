"""Native-automation and decomposition recovery fallbacks (HAMMER-011).

This module implements the ``## HAMMER-011`` entry of
``docs/logic/itp_hammer_taskboard.todo.md``: *"On translation, search, or
reconstruction failure, try an explicitly enabled native tactic such as Lean
automation, then return a bounded subgoal decomposition plan. Any
LLM-assisted plan is redacted, reviewed, and marked untrusted until each
resulting native subproof passes the kernel."* See
``docs/logic/itp_hammer_failure_policy.md`` for the full narrative
specification.

Where this sits in the pipeline
--------------------------------
HAMMER-007's translation layer, HAMMER-008's solver portfolio, and
HAMMER-010's :mod:`.reconstruction` are each allowed to fail closed: a
construct may be ``unsupported_translation``, a bounded solver portfolio may
exhaust its budget with no conclusive verdict (``unknown``/``timeout``), or
a reconstructed candidate may be rejected by the target ITP kernel. None of
those outcomes are errors in this pipeline's design — they are exactly the
honest, fail-closed results the trust contract (HAMMER-001) requires instead
of a fabricated proof. This module is the *recovery* step that runs after
any of those three failure modes, and it never weakens that trust contract:
every recovery path still ends at the same target ITP kernel HAMMER-010
already trusts, or at an explicit, bounded, human-reviewable plan — never at
an assumed proof.

Two recovery strategies, tried in order
----------------------------------------
1. **Native automation fallback** (:func:`attempt_native_automation`) — an
   *explicitly operator-enabled* (:attr:`~.models.HammerPolicy.
   allow_native_automation_fallback`, default ``False``) attempt to close
   the goal using nothing but the target ITP's own built-in closing
   tactics/methods (e.g. Lean's ``rfl``/``decide``/``simp_all``, Coq's
   ``reflexivity``/``lia``, Isabelle's ``simp``/``auto``/``blast``) — no
   untrusted solver candidate is involved at all. This is implemented by
   reusing HAMMER-010's own :class:`~.reconstruction.Reconstructor`
   machinery with a synthetic, *empty*-``premise_ids``
   :class:`~.models.ProofCandidateRecord`: every anti-cheating check
   (Lean's ``#print axioms``, Coq's ``Print Assumptions``, Isabelle's error/
   ``sorry`` scan) and every bounded, process-group-aware subprocess budget
   HAMMER-010 already enforces applies unchanged. A recovered
   :class:`~.reconstruction.ReconstructionRecord` from this path is exactly
   as trustworthy as any other HAMMER-010 reconstruction — it was
   independently kernel-checked, not merely proposed.
2. **Bounded subgoal decomposition plan** (:func:`build_decomposition_plan`)
   — if native automation is disabled, unavailable, or itself rejected by
   the kernel, this returns a :class:`DecompositionPlan` of at most
   :attr:`~.models.HammerPolicy.max_decomposition_subgoals`
   :class:`DecompositionSubgoal` entries. Subgoals are derived two ways:

   - **Native-structural** (:data:`DecompositionSource.NATIVE_STRUCTURAL`):
     a deterministic, bracket-depth-aware split of the goal's own top-level
     conjunction connectives (``∧``/``/\\``) — never an LLM guess.
   - **LLM-suggested** (:data:`DecompositionSource.LLM_SUGGESTED`): only
     considered at all when both an ``llm_decomposition_provider`` callable
     is supplied *and* :attr:`~.models.HammerPolicy.
     allow_llm_decomposition_hints` is ``True``. Every such subgoal is
     immediately given a :func:`redact_llm_text` placeholder
     (``redacted_suggestion``) distinct from the raw suggestion text kept
     only for the (still bounded, still kernel-checked) verification
     attempt, starts at :attr:`ReviewStatus.PENDING_REVIEW`, and can never
     reach :attr:`SubgoalStatus.VERIFIED` — the only status that means
     "trust this" — without first passing through
     :func:`review_decomposition_subgoal` (an explicit human
     approve/reject step) *and then* :func:`verify_decomposition_subgoal`
     independently reconstructing and kernel-checking a genuine native
     source built from the subgoal text. An LLM never supplies an accepted
     proof; it can only ever propose *text to attempt*, gated by review and
     the same kernel check every other candidate in this pipeline goes
     through.

Neither strategy can ever produce a :attr:`~.models.HammerResultStatus.
VERIFIED` :class:`~.models.HammerResult` on its own — a caller who recovers
via :func:`attempt_native_automation` still assembles the final
``HammerResult`` the same way HAMMER-010 callers do (using the returned
:class:`~.reconstruction.ReconstructionRecord`, :class:`~.models.
ProofCandidateRecord`, and :class:`~.models.EnvironmentLockRecord`), and a
:class:`DecompositionPlan` is, by construction, never itself a proof of the
original goal — it only records that *individual subgoals*, if and once
each independently passes its own kernel check, were shown to hold.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .corpus import compute_content_digest
from .frontends.base import GoalSnapshot, LocalHypothesis, SourcePosition
from .models import (
    SCHEMA_VERSION,
    EnvironmentLockRecord,
    HammerRequest,
    ITPKind,
    ProofCandidateRecord,
    ReconstructionRecord,
    _isoformat,
    _parse_datetime,
    _require_nonempty_str,
    _require_schema_version,
    _utcnow,
)
from .reconstruction import (
    DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS,
    KernelUnavailableError,
    ReconstructionEvidence,
    ReconstructionInputError,
    Reconstructor,
    get_reconstructor,
)

__all__ = [
    "SCHEMA_VERSION",
    "FallbackTrigger",
    "DecompositionSource",
    "ReviewStatus",
    "SubgoalStatus",
    "FallbackInputError",
    "NativeAutomationAttempt",
    "DecompositionSubgoal",
    "DecompositionPlan",
    "FallbackOutcome",
    "redact_llm_text",
    "split_top_level_conjuncts",
    "attempt_native_automation",
    "build_decomposition_plan",
    "review_decomposition_subgoal",
    "verify_decomposition_subgoal",
    "attempt_fallback",
]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class FallbackTrigger(str, Enum):
    """Which upstream pipeline stage's failure a recovery attempt is
    responding to. Purely provenance metadata: the recovery logic itself
    (native automation, then decomposition) is identical regardless of
    which of these fired, since all three leave the genuine HAMMER-006
    native goal snapshot untouched and available to retry against.
    """

    #: HAMMER-007 reported ``TranslationStatus.UNSUPPORTED`` for a required
    #: construct.
    TRANSLATION_FAILURE = "translation_failure"
    #: HAMMER-008's bounded solver portfolio exhausted its budget with no
    #: conclusive verdict (``unknown``/``timeout``), or no solver was
    #: allowlisted at all.
    SEARCH_FAILURE = "search_failure"
    #: HAMMER-010 reconstructed a candidate but the target ITP kernel
    #: rejected it (``kernel_accepted`` is ``False``).
    RECONSTRUCTION_FAILURE = "reconstruction_failure"


class DecompositionSource(str, Enum):
    """Provenance of one :class:`DecompositionSubgoal`'s statement text."""

    #: Derived deterministically from the goal's own top-level conjunction
    #: structure. Never fabricated; always a verbatim substring of the
    #: genuine goal text.
    NATIVE_STRUCTURAL = "native_structural"
    #: Proposed by an operator-supplied, policy-gated LLM callable. Always
    #: redacted, always requires explicit review, and can never be trusted
    #: until its own native subproof independently passes the kernel.
    LLM_SUGGESTED = "llm_suggested"


class ReviewStatus(str, Enum):
    """Human-review state of one :class:`DecompositionSubgoal`.

    Only :data:`DecompositionSource.LLM_SUGGESTED` subgoals ever leave
    :attr:`NOT_REQUIRED` — a native-structural subgoal is derived from the
    goal's own text with no LLM involvement and therefore never needs
    review before its native subproof may be attempted.
    """

    #: No review is required for this subgoal (native-structural source).
    NOT_REQUIRED = "not_required"
    #: An LLM-suggested subgoal awaiting explicit human approve/reject.
    PENDING_REVIEW = "pending_review"
    #: A human reviewer approved this subgoal's text as worth attempting.
    #: Approval is *not* trust in the statement's truth — it only permits a
    #: bounded, kernel-checked verification attempt to proceed.
    REVIEWED = "reviewed"
    #: A human reviewer rejected this subgoal outright; it can never be
    #: verified.
    REJECTED = "rejected"


class SubgoalStatus(str, Enum):
    """Verification state of one :class:`DecompositionSubgoal`."""

    #: Not yet attempted (or not yet reviewed, for an LLM-suggested
    #: subgoal). Always untrusted.
    PENDING = "pending"
    #: A genuine native reconstruction was built for this subgoal and the
    #: target ITP kernel accepted it. The only status that means "trust
    #: this subgoal".
    VERIFIED = "verified"
    #: A genuine native reconstruction was built and the kernel rejected it
    #: (or a human reviewer rejected the subgoal before any kernel attempt).
    REJECTED = "rejected"
    #: Verification was not attempted because the target ITP kernel is
    #: unavailable in this environment.
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FallbackInputError(ValueError):
    """Raised for misuse of the fallback API: an unreviewed or
    review-rejected LLM-suggested subgoal submitted for verification, a
    subgoal from a different request, an already-verified subgoal
    resubmitted for verification, or an unregistered target ITP.

    Never raised for an ordinary "the kernel rejected the reconstruction"
    or "the kernel is unavailable" outcome — those are reported via
    :attr:`SubgoalStatus.REJECTED`/:attr:`SubgoalStatus.SKIPPED` and
    :attr:`NativeAutomationAttempt.skipped_reason`, matching
    :class:`~.reconstruction.ReconstructionInputError`'s own convention.
    """


# ---------------------------------------------------------------------------
# Native automation attempt
# ---------------------------------------------------------------------------


@dataclass
class NativeAutomationAttempt:
    """The outcome of one :func:`attempt_native_automation` call.

    Attributes:
        schema_version: Schema version of this record.
        request_id: Owning :class:`~.models.HammerRequest` id.
        itp: Target ITP the attempt was made against.
        attempted: Whether a real kernel invocation was actually made.
            ``False`` means the fallback was skipped entirely (disabled by
            policy, or the target kernel is unavailable) — nothing was
            executed.
        recovered: Whether the attempt independently reconstructed and
            kernel-verified the goal. Always equal to
            ``reconstruction.kernel_accepted`` when ``attempted`` is
            ``True``, and always ``False`` when ``attempted`` is ``False``.
        proof_candidate: The synthetic, empty-``premise_ids``
            :class:`~.models.ProofCandidateRecord` used to drive
            reconstruction; present iff ``attempted`` is ``True``.
        reconstruction: The genuine :class:`~.reconstruction.
            ReconstructionRecord` from a real kernel invocation; present
            iff ``attempted`` is ``True``.
        evidence: Out-of-band :class:`~.reconstruction.
            ReconstructionEvidence` (checked source, kernel stdout/stderr);
            present iff ``attempted`` is ``True``.
        environment_lock: The :class:`~.models.EnvironmentLockRecord` the
            kernel ran under; present iff ``attempted`` is ``True``.
        skipped_reason: Required, human-readable explanation when
            ``attempted`` is ``False``.
    """

    schema_version: str = SCHEMA_VERSION
    request_id: str = ""
    itp: ITPKind = ITPKind.LEAN
    attempted: bool = False
    recovered: bool = False
    proof_candidate: Optional[ProofCandidateRecord] = None
    reconstruction: Optional[ReconstructionRecord] = None
    evidence: Optional[ReconstructionEvidence] = None
    environment_lock: Optional[EnvironmentLockRecord] = None
    skipped_reason: Optional[str] = None

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="NativeAutomationAttempt")
        _require_nonempty_str(
            self.request_id, field_name="request_id", owner="NativeAutomationAttempt"
        )
        if not isinstance(self.itp, ITPKind):
            raise ValueError("NativeAutomationAttempt.itp must be an ITPKind")
        if not isinstance(self.attempted, bool):
            raise ValueError("NativeAutomationAttempt.attempted must be a boolean")
        if not isinstance(self.recovered, bool):
            raise ValueError("NativeAutomationAttempt.recovered must be a boolean")

        if self.attempted:
            if self.skipped_reason is not None:
                raise ValueError(
                    "NativeAutomationAttempt.skipped_reason must be None when "
                    "attempted is True"
                )
            if self.proof_candidate is None or self.reconstruction is None:
                raise ValueError(
                    "NativeAutomationAttempt.proof_candidate and reconstruction "
                    "are required when attempted is True"
                )
            self.proof_candidate.validate()
            self.reconstruction.validate()
            if self.reconstruction.candidate_id != self.proof_candidate.candidate_id:
                raise ValueError(
                    "NativeAutomationAttempt.reconstruction.candidate_id must "
                    "match proof_candidate.candidate_id"
                )
            if self.reconstruction.request_id != self.request_id:
                raise ValueError(
                    "NativeAutomationAttempt.reconstruction.request_id must "
                    "match request_id"
                )
            if self.recovered != self.reconstruction.kernel_accepted:
                raise ValueError(
                    "NativeAutomationAttempt.recovered must equal "
                    "reconstruction.kernel_accepted"
                )
            if self.evidence is not None and not isinstance(
                self.evidence, ReconstructionEvidence
            ):
                raise ValueError(
                    "NativeAutomationAttempt.evidence must be a "
                    "ReconstructionEvidence or None"
                )
            if self.environment_lock is not None:
                if not isinstance(self.environment_lock, EnvironmentLockRecord):
                    raise ValueError(
                        "NativeAutomationAttempt.environment_lock must be an "
                        "EnvironmentLockRecord or None"
                    )
                self.environment_lock.validate()
        else:
            _require_nonempty_str(
                self.skipped_reason,
                field_name="skipped_reason",
                owner="NativeAutomationAttempt",
            )
            if self.proof_candidate is not None or self.reconstruction is not None:
                raise ValueError(
                    "NativeAutomationAttempt.proof_candidate/reconstruction "
                    "must be None when attempted is False"
                )
            if self.evidence is not None or self.environment_lock is not None:
                raise ValueError(
                    "NativeAutomationAttempt.evidence/environment_lock must be "
                    "None when attempted is False"
                )
            if self.recovered:
                raise ValueError(
                    "NativeAutomationAttempt.recovered must be False when "
                    "attempted is False"
                )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "itp": self.itp.value,
            "attempted": self.attempted,
            "recovered": self.recovered,
            "proof_candidate": (
                self.proof_candidate.to_dict() if self.proof_candidate else None
            ),
            "reconstruction": (
                self.reconstruction.to_dict() if self.reconstruction else None
            ),
            "evidence": self.evidence.to_dict() if self.evidence else None,
            "environment_lock": (
                self.environment_lock.to_dict() if self.environment_lock else None
            ),
            "skipped_reason": self.skipped_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NativeAutomationAttempt":
        data = dict(data)
        if isinstance(data.get("itp"), str):
            data["itp"] = ITPKind(data["itp"])
        if data.get("proof_candidate"):
            data["proof_candidate"] = ProofCandidateRecord.from_dict(data["proof_candidate"])
        else:
            data["proof_candidate"] = None
        if data.get("reconstruction"):
            data["reconstruction"] = ReconstructionRecord.from_dict(data["reconstruction"])
        else:
            data["reconstruction"] = None
        if data.get("evidence"):
            data["evidence"] = ReconstructionEvidence.from_dict(data["evidence"])
        else:
            data["evidence"] = None
        if data.get("environment_lock"):
            data["environment_lock"] = EnvironmentLockRecord.from_dict(
                data["environment_lock"]
            )
        else:
            data["environment_lock"] = None
        return cls(**data)


# ---------------------------------------------------------------------------
# Decomposition subgoal
# ---------------------------------------------------------------------------


@dataclass
class DecompositionSubgoal:
    """One entry of a bounded :class:`DecompositionPlan`.

    Attributes:
        schema_version: Schema version of this record.
        subgoal_id: Stable, content-derived identifier for this subgoal.
        request_id: Owning :class:`~.models.HammerRequest` id.
        rank: 0-indexed rank within the plan (stable ordering).
        source: Provenance of ``statement`` (native-structural or
            LLM-suggested).
        statement: The exact subgoal text a native reconstruction attempt
            would try to prove. Kept in full even for an LLM-suggested
            subgoal (verification needs the real text); ``redacted_suggestion``
            is what should be surfaced to anything other than the internal
            verification path until ``status`` is ``VERIFIED``.
        redacted_suggestion: A redacted, safe-to-surface placeholder for an
            LLM-suggested subgoal's raw text (see :func:`redact_llm_text`).
            Required (non-empty) when ``source`` is ``LLM_SUGGESTED``;
            forbidden when ``NATIVE_STRUCTURAL``.
        review_status: Human-review state; always ``NOT_REQUIRED`` for a
            native-structural subgoal, otherwise starts at
            ``PENDING_REVIEW``.
        reviewed_by: Identifier of the human reviewer, if reviewed.
        reviewed_at: When the review decision was recorded.
        review_notes: Optional free-form reviewer notes.
        status: Verification state; only ``VERIFIED`` means "trust this".
        reconstruction_id: :class:`~.reconstruction.ReconstructionRecord` id
            from the verification attempt, if one was made.
        content_digest: Content digest of ``statement``.
    """

    schema_version: str = SCHEMA_VERSION
    subgoal_id: str = ""
    request_id: str = ""
    rank: int = 0
    source: DecompositionSource = DecompositionSource.NATIVE_STRUCTURAL
    statement: str = ""
    redacted_suggestion: Optional[str] = None
    review_status: ReviewStatus = ReviewStatus.NOT_REQUIRED
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    status: SubgoalStatus = SubgoalStatus.PENDING
    reconstruction_id: Optional[str] = None
    content_digest: str = ""

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="DecompositionSubgoal")
        _require_nonempty_str(
            self.subgoal_id, field_name="subgoal_id", owner="DecompositionSubgoal"
        )
        _require_nonempty_str(
            self.request_id, field_name="request_id", owner="DecompositionSubgoal"
        )
        if self.rank < 0:
            raise ValueError("DecompositionSubgoal.rank must be non-negative")
        if not isinstance(self.source, DecompositionSource):
            raise ValueError("DecompositionSubgoal.source must be a DecompositionSource")
        _require_nonempty_str(
            self.statement, field_name="statement", owner="DecompositionSubgoal"
        )
        if not isinstance(self.review_status, ReviewStatus):
            raise ValueError(
                "DecompositionSubgoal.review_status must be a ReviewStatus"
            )
        if not isinstance(self.status, SubgoalStatus):
            raise ValueError("DecompositionSubgoal.status must be a SubgoalStatus")
        _require_nonempty_str(
            self.content_digest, field_name="content_digest", owner="DecompositionSubgoal"
        )

        if self.source is DecompositionSource.LLM_SUGGESTED:
            _require_nonempty_str(
                self.redacted_suggestion,
                field_name="redacted_suggestion",
                owner="DecompositionSubgoal",
            )
            if self.review_status is ReviewStatus.NOT_REQUIRED:
                raise ValueError(
                    "DecompositionSubgoal.review_status must not be NOT_REQUIRED "
                    "for an LLM_SUGGESTED subgoal — it always requires explicit "
                    "human review before any native subproof may be attempted"
                )
            if self.status is SubgoalStatus.VERIFIED and self.review_status is not (
                ReviewStatus.REVIEWED
            ):
                raise ValueError(
                    "DecompositionSubgoal.status is VERIFIED but an LLM_SUGGESTED "
                    "subgoal's review_status is not REVIEWED"
                )
        else:
            if self.redacted_suggestion is not None:
                raise ValueError(
                    "DecompositionSubgoal.redacted_suggestion must be None for a "
                    "NATIVE_STRUCTURAL subgoal"
                )
            if self.review_status is not ReviewStatus.NOT_REQUIRED:
                raise ValueError(
                    "DecompositionSubgoal.review_status must be NOT_REQUIRED for "
                    "a NATIVE_STRUCTURAL subgoal"
                )

        if self.review_status is ReviewStatus.REJECTED and self.status is (
            SubgoalStatus.VERIFIED
        ):
            raise ValueError(
                "DecompositionSubgoal.status cannot be VERIFIED when "
                "review_status is REJECTED"
            )
        if self.status is SubgoalStatus.VERIFIED:
            _require_nonempty_str(
                self.reconstruction_id,
                field_name="reconstruction_id",
                owner="DecompositionSubgoal",
            )
        if (self.reviewed_by is None) != (self.reviewed_at is None):
            raise ValueError(
                "DecompositionSubgoal.reviewed_by and reviewed_at must be set "
                "together"
            )
        if self.reviewed_by is not None and self.review_status in (
            ReviewStatus.NOT_REQUIRED,
            ReviewStatus.PENDING_REVIEW,
        ):
            raise ValueError(
                "DecompositionSubgoal.reviewed_by/reviewed_at implies "
                "review_status REVIEWED or REJECTED"
            )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["source"] = self.source.value
        data["review_status"] = self.review_status.value
        data["status"] = self.status.value
        data["reviewed_at"] = _isoformat(self.reviewed_at)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecompositionSubgoal":
        data = dict(data)
        if isinstance(data.get("source"), str):
            data["source"] = DecompositionSource(data["source"])
        if isinstance(data.get("review_status"), str):
            data["review_status"] = ReviewStatus(data["review_status"])
        if isinstance(data.get("status"), str):
            data["status"] = SubgoalStatus(data["status"])
        if "reviewed_at" in data:
            data["reviewed_at"] = _parse_datetime(data["reviewed_at"])
        return cls(**data)


# ---------------------------------------------------------------------------
# Decomposition plan
# ---------------------------------------------------------------------------


@dataclass
class DecompositionPlan:
    """A bounded plan of :class:`DecompositionSubgoal` entries produced when
    native automation could not (or was not allowed to) recover the goal.

    A plan is never itself a proof of the original goal: it only records
    that decomposition was attempted and bounds how many subgoals may ever
    be considered. :meth:`is_fully_verified` is the only way to learn
    whether every subgoal in the plan has independently passed its own
    native kernel check.

    Attributes:
        schema_version: Schema version of this record.
        plan_id: Stable, content-derived identifier for this plan.
        request_id: Owning :class:`~.models.HammerRequest` id.
        trigger: Which upstream failure prompted this plan.
        max_subgoals: The bound in effect when this plan was built (from
            :attr:`~.models.HammerPolicy.max_decomposition_subgoals`).
        subgoals: The bounded list of subgoals, in stable rank order.
        created_at: When this plan was built.
        notes: Free-form, non-authoritative diagnostic notes (e.g. why no
            native-structural split was found, or why LLM suggestions were
            ignored).
    """

    schema_version: str = SCHEMA_VERSION
    plan_id: str = ""
    request_id: str = ""
    trigger: FallbackTrigger = FallbackTrigger.RECONSTRUCTION_FAILURE
    max_subgoals: int = 4
    subgoals: List[DecompositionSubgoal] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utcnow)
    notes: List[str] = field(default_factory=list)

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="DecompositionPlan")
        _require_nonempty_str(self.plan_id, field_name="plan_id", owner="DecompositionPlan")
        _require_nonempty_str(
            self.request_id, field_name="request_id", owner="DecompositionPlan"
        )
        if not isinstance(self.trigger, FallbackTrigger):
            raise ValueError("DecompositionPlan.trigger must be a FallbackTrigger")
        if self.max_subgoals <= 0:
            raise ValueError("DecompositionPlan.max_subgoals must be positive")
        if not isinstance(self.subgoals, list):
            raise ValueError("DecompositionPlan.subgoals must be a list")
        if len(self.subgoals) > self.max_subgoals:
            raise ValueError(
                f"DecompositionPlan.subgoals has {len(self.subgoals)} entries, "
                f"exceeding max_subgoals={self.max_subgoals}"
            )

        seen_ids: set = set()
        seen_ranks: set = set()
        for subgoal in self.subgoals:
            if not isinstance(subgoal, DecompositionSubgoal):
                raise ValueError(
                    "DecompositionPlan.subgoals must contain DecompositionSubgoal"
                )
            subgoal.validate()
            if subgoal.request_id != self.request_id:
                raise ValueError(
                    "DecompositionPlan.subgoals entries must share the plan's "
                    "request_id"
                )
            if subgoal.subgoal_id in seen_ids:
                raise ValueError(
                    f"DecompositionPlan.subgoals contains duplicate subgoal_id "
                    f"{subgoal.subgoal_id!r}"
                )
            seen_ids.add(subgoal.subgoal_id)
            if subgoal.rank in seen_ranks:
                raise ValueError(
                    f"DecompositionPlan.subgoals contains duplicate rank "
                    f"{subgoal.rank}"
                )
            seen_ranks.add(subgoal.rank)

        if not isinstance(self.notes, list) or not all(
            isinstance(n, str) for n in self.notes
        ):
            raise ValueError("DecompositionPlan.notes must be a list of strings")

    def is_fully_verified(self) -> bool:
        """Return whether every subgoal in this plan has ``status ==
        SubgoalStatus.VERIFIED`` — the only condition under which the
        decomposition as a whole may be treated as trusted. An empty plan
        is never "fully verified"."""

        return bool(self.subgoals) and all(
            s.status is SubgoalStatus.VERIFIED for s in self.subgoals
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "request_id": self.request_id,
            "trigger": self.trigger.value,
            "max_subgoals": self.max_subgoals,
            "subgoals": [s.to_dict() for s in self.subgoals],
            "created_at": _isoformat(self.created_at),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecompositionPlan":
        data = dict(data)
        if isinstance(data.get("trigger"), str):
            data["trigger"] = FallbackTrigger(data["trigger"])
        data["subgoals"] = [
            DecompositionSubgoal.from_dict(s) for s in data.get("subgoals", [])
        ]
        if "created_at" in data:
            data["created_at"] = _parse_datetime(data["created_at"])
        return cls(**data)


# ---------------------------------------------------------------------------
# Fallback outcome
# ---------------------------------------------------------------------------


@dataclass
class FallbackOutcome:
    """The overall result of one :func:`attempt_fallback` call.

    Attributes:
        schema_version: Schema version of this record.
        outcome_id: Stable, content-derived identifier for this outcome.
        request_id: Owning :class:`~.models.HammerRequest` id.
        trigger: Which upstream failure prompted this recovery attempt.
        native_automation: The native automation attempt (always present;
            ``attempted=False`` when skipped).
        decomposition_plan: The bounded decomposition plan, present iff
            native automation did not recover the goal.
        recovered: Whether native automation alone recovered the goal
            (always equal to ``native_automation.recovered``).
        created_at: When this outcome was produced.
        notes: Free-form, non-authoritative diagnostic notes.
        errors: Free-form, non-authoritative diagnostic error messages.
    """

    schema_version: str = SCHEMA_VERSION
    outcome_id: str = ""
    request_id: str = ""
    trigger: FallbackTrigger = FallbackTrigger.RECONSTRUCTION_FAILURE
    native_automation: NativeAutomationAttempt = field(
        default_factory=NativeAutomationAttempt
    )
    decomposition_plan: Optional[DecompositionPlan] = None
    recovered: bool = False
    created_at: datetime = field(default_factory=_utcnow)
    notes: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="FallbackOutcome")
        _require_nonempty_str(
            self.outcome_id, field_name="outcome_id", owner="FallbackOutcome"
        )
        _require_nonempty_str(
            self.request_id, field_name="request_id", owner="FallbackOutcome"
        )
        if not isinstance(self.trigger, FallbackTrigger):
            raise ValueError("FallbackOutcome.trigger must be a FallbackTrigger")
        if not isinstance(self.native_automation, NativeAutomationAttempt):
            raise ValueError(
                "FallbackOutcome.native_automation must be a NativeAutomationAttempt"
            )
        self.native_automation.validate()
        if self.native_automation.request_id != self.request_id:
            raise ValueError(
                "FallbackOutcome.native_automation.request_id must match "
                "request_id"
            )
        if not isinstance(self.recovered, bool):
            raise ValueError("FallbackOutcome.recovered must be a boolean")
        if self.recovered != self.native_automation.recovered:
            raise ValueError(
                "FallbackOutcome.recovered must equal native_automation.recovered"
            )

        if self.decomposition_plan is not None:
            if not isinstance(self.decomposition_plan, DecompositionPlan):
                raise ValueError(
                    "FallbackOutcome.decomposition_plan must be a "
                    "DecompositionPlan or None"
                )
            self.decomposition_plan.validate()
            if self.decomposition_plan.request_id != self.request_id:
                raise ValueError(
                    "FallbackOutcome.decomposition_plan.request_id must match "
                    "request_id"
                )
            if self.decomposition_plan.trigger is not self.trigger:
                raise ValueError(
                    "FallbackOutcome.decomposition_plan.trigger must match "
                    "trigger"
                )

        if self.recovered and self.decomposition_plan is not None:
            raise ValueError(
                "FallbackOutcome.decomposition_plan must be None when native "
                "automation already recovered the goal"
            )

        if not isinstance(self.notes, list) or not all(
            isinstance(n, str) for n in self.notes
        ):
            raise ValueError("FallbackOutcome.notes must be a list of strings")
        if not isinstance(self.errors, list) or not all(
            isinstance(e, str) for e in self.errors
        ):
            raise ValueError("FallbackOutcome.errors must be a list of strings")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "outcome_id": self.outcome_id,
            "request_id": self.request_id,
            "trigger": self.trigger.value,
            "native_automation": self.native_automation.to_dict(),
            "decomposition_plan": (
                self.decomposition_plan.to_dict() if self.decomposition_plan else None
            ),
            "recovered": self.recovered,
            "created_at": _isoformat(self.created_at),
            "notes": list(self.notes),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FallbackOutcome":
        data = dict(data)
        if isinstance(data.get("trigger"), str):
            data["trigger"] = FallbackTrigger(data["trigger"])
        data["native_automation"] = NativeAutomationAttempt.from_dict(
            data["native_automation"]
        )
        if data.get("decomposition_plan"):
            data["decomposition_plan"] = DecompositionPlan.from_dict(
                data["decomposition_plan"]
            )
        else:
            data["decomposition_plan"] = None
        if "created_at" in data:
            data["created_at"] = _parse_datetime(data["created_at"])
        return cls(**data)


# ---------------------------------------------------------------------------
# LLM redaction
# ---------------------------------------------------------------------------


def redact_llm_text(text: str) -> str:
    """Return a redacted, safe-to-surface placeholder for raw LLM-suggested
    subgoal text.

    The placeholder never contains the raw text itself — only its length
    and a deterministic content digest (so two identical suggestions
    produce the same placeholder, without ever revealing what they say).
    Anything that renders a :class:`DecompositionSubgoal` to a human or a
    publishable receipt before its ``status`` is ``VERIFIED`` should use
    this placeholder (``redacted_suggestion``) instead of ``statement``.
    """

    digest = compute_content_digest({"llm_suggestion": text})
    return (
        f"<llm-suggested subgoal redacted pending review; length={len(text)}; "
        f"digest={digest}>"
    )


# ---------------------------------------------------------------------------
# Native-structural decomposition
# ---------------------------------------------------------------------------

#: Conjunction connectives recognized at the top level of a goal's native
#: text (Lean/Isabelle unicode ``∧``, Coq/ASCII ``/\``). Checked longest-first
#: so ``/\`` is never partially matched.
_CONJUNCTION_TOKENS: Tuple[str, ...] = ("∧", "/\\")

_OPEN_BRACKETS = "([{"
_CLOSE_BRACKETS = ")]}"


def split_top_level_conjuncts(goal_text: str, *, max_parts: int) -> List[str]:
    """Deterministically split ``goal_text`` on its own top-level
    conjunction connectives (``∧``/``/\\``), bounded to at most
    ``max_parts`` conjuncts.

    A connective nested inside ``()``/``[]``/``{}`` is never split on. If
    fewer than two top-level conjuncts are found (including the case of no
    connective at all), returns ``[]`` — this is an honest "no
    native-structural decomposition available for this goal", never a
    fabricated split.

    When more than ``max_parts`` top-level conjuncts are present, the first
    ``max_parts - 1`` are returned as their own subgoals and every remaining
    conjunct is folded, verbatim (rejoined with ``" ∧ "``), into the final
    subgoal — bounding the plan size without ever silently dropping part of
    the goal.
    """

    if max_parts < 2:
        return []
    text = goal_text.strip()
    if not text:
        return []

    depth = 0
    parts: List[str] = []
    current_start = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in _OPEN_BRACKETS:
            depth += 1
            i += 1
            continue
        if ch in _CLOSE_BRACKETS:
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth == 0 and len(parts) < max_parts - 1:
            matched_token: Optional[str] = None
            for token in _CONJUNCTION_TOKENS:
                if text.startswith(token, i):
                    matched_token = token
                    break
            if matched_token is not None:
                parts.append(text[current_start:i].strip())
                i += len(matched_token)
                current_start = i
                continue
        i += 1

    parts.append(text[current_start:].strip())
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return []
    return parts


# ---------------------------------------------------------------------------
# Synthetic native subgoal source builders
# ---------------------------------------------------------------------------

_IDENTIFIER_SANITIZE_RE = re.compile(r"[^A-Za-z0-9_]")
_COLLAPSE_UNDERSCORES_RE = re.compile(r"_+")


def _safe_identifier(seed: str, *, max_len: int = 48) -> str:
    """Derive a deterministic, native-identifier-safe name from ``seed``
    (e.g. a content digest or free-form label). Guarantees a non-empty
    result starting with a letter or underscore, using only
    ``[A-Za-z0-9_]``."""

    sanitized = _IDENTIFIER_SANITIZE_RE.sub("_", seed)
    sanitized = _COLLAPSE_UNDERSCORES_RE.sub("_", sanitized).strip("_")
    if not sanitized:
        sanitized = "g"
    if not (sanitized[0].isalpha() or sanitized[0] == "_"):
        sanitized = f"g_{sanitized}"
    return sanitized[:max_len] or "g"


def _render_binder_groups(hypotheses: Sequence[LocalHypothesis]) -> str:
    """Render ``hypotheses`` as Lean/Coq-style space-separated binder
    groups (``(n : Nat) (h : n = n)``), reusing each hypothesis's own
    native names/type text verbatim — never inventing a binder."""

    return " ".join(
        f"({' '.join(h.names)} : {h.type_text})" for h in hypotheses
    )


def _build_lean_subgoal_source(
    decl_name: str, hypotheses: Sequence[LocalHypothesis], statement: str
) -> str:
    binders = _render_binder_groups(hypotheses)
    header = f"theorem {decl_name} "
    if binders:
        header += f"{binders} "
    header += f": {statement} := by"
    return f"{header}\n  sorry\n"


def _build_coq_subgoal_source(
    decl_name: str, hypotheses: Sequence[LocalHypothesis], statement: str
) -> str:
    binders = _render_binder_groups(hypotheses)
    header = f"Theorem {decl_name} "
    if binders:
        header += f"{binders} "
    header += f": {statement}."
    return f"{header}\nProof.\n  intros.\nAdmitted.\n"


def _build_isabelle_subgoal_source(
    decl_name: str, hypotheses: Sequence[LocalHypothesis], statement: str
) -> str:
    # Isabelle is confirmed unavailable in this repository's probed
    # environment (docs/logic/itp_hammer_capability_inventory.md), exactly
    # like ipfs_datasets_py.logic.hammers.reconstructors.isabelle. This
    # builder therefore cannot be validated against a live Isabelle kernel
    # here; it is a conservative, best-effort Isar rendering (every local
    # hypothesis folded into a ``fixes``/``shows`` lemma), exercised in this
    # module's tests only against a mocked kernel-check call.
    theory_name = _safe_identifier(f"{decl_name}_thy")
    theory_name = theory_name[0].upper() + theory_name[1:] if theory_name else "Thy"

    lines = [f"theory {theory_name}", "imports Main", "begin", ""]
    if hypotheses:
        fixes_clause = " and ".join(
            f'{name} :: "{h.type_text}"' for h in hypotheses for name in h.names
        )
        lines.append(f"lemma {decl_name}:")
        lines.append(f"  fixes {fixes_clause}")
        lines.append(f'  shows "{statement}"')
    else:
        lines.append(f'lemma {decl_name}: "{statement}"')
    lines.append("  sorry")
    lines.append("")
    lines.append("end")
    lines.append("")
    return "\n".join(lines)


def _build_native_subgoal_source(
    itp: ITPKind,
    decl_name: str,
    hypotheses: Sequence[LocalHypothesis],
    statement: str,
) -> str:
    if itp is ITPKind.LEAN:
        return _build_lean_subgoal_source(decl_name, hypotheses, statement)
    if itp is ITPKind.COQ:
        return _build_coq_subgoal_source(decl_name, hypotheses, statement)
    if itp is ITPKind.ISABELLE:
        return _build_isabelle_subgoal_source(decl_name, hypotheses, statement)
    raise FallbackInputError(
        f"no synthetic subgoal source builder is registered for {itp!r}"
    )


# ---------------------------------------------------------------------------
# Native automation fallback
# ---------------------------------------------------------------------------


def attempt_native_automation(
    *,
    request: HammerRequest,
    goal_snapshot: GoalSnapshot,
    native_source: str,
    reconstructor: Optional[Reconstructor] = None,
    environment_lock: Optional[EnvironmentLockRecord] = None,
    timeout: Optional[float] = None,
) -> NativeAutomationAttempt:
    """Try to close ``request``'s goal using only the target ITP's own
    built-in closing tactics/methods, gated by
    :attr:`~.models.HammerPolicy.allow_native_automation_fallback`.

    Reuses HAMMER-010's :class:`~.reconstruction.Reconstructor` machinery
    with a synthetic, empty-``premise_ids``
    :class:`~.models.ProofCandidateRecord` — no untrusted solver candidate
    is involved, and every one of HAMMER-010's anti-cheating checks and
    bounded subprocess budgets applies unchanged. A ``recovered=True``
    result carries a genuine, independently kernel-checked
    :class:`~.reconstruction.ReconstructionRecord`.

    Never raises for an expected "could not run" outcome (policy disabled,
    kernel unavailable, or a call-site :class:`~.reconstruction.
    ReconstructionInputError`) — all three are reported via
    ``attempted=False`` and a populated ``skipped_reason``.
    """

    if not request.policy.allow_native_automation_fallback:
        attempt = NativeAutomationAttempt(
            request_id=request.request_id,
            itp=request.itp,
            attempted=False,
            recovered=False,
            skipped_reason=(
                "native automation fallback is disabled by policy "
                "(HammerPolicy.allow_native_automation_fallback is False); an "
                "operator must explicitly opt in per HAMMER-011's "
                "'explicitly enabled' requirement"
            ),
        )
        attempt.validate()
        return attempt

    resolved_reconstructor = reconstructor or get_reconstructor(
        request.itp, timeout=timeout or DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS
    )
    capability = resolved_reconstructor.capability()
    if not capability.available:
        attempt = NativeAutomationAttempt(
            request_id=request.request_id,
            itp=request.itp,
            attempted=False,
            recovered=False,
            skipped_reason=(
                f"native automation fallback skipped: {request.itp.value} "
                f"kernel unavailable ({capability.unavailable_reason})"
            ),
        )
        attempt.validate()
        return attempt

    candidate = ProofCandidateRecord(
        candidate_id=compute_content_digest(
            {
                "kind": "native-automation-fallback",
                "request_id": request.request_id,
                "theorem_id": request.theorem_id,
                "native_source": native_source,
            }
        ),
        request_id=request.request_id,
        solver_attempt_id="native-automation-fallback",
        premise_ids=[],
    )
    candidate.validate()

    try:
        record, evidence, lock = resolved_reconstructor.reconstruct(
            request=request,
            candidate=candidate,
            goal_snapshot=goal_snapshot,
            native_source=native_source,
            environment_lock=environment_lock,
            timeout=timeout,
        )
    except (ReconstructionInputError, KernelUnavailableError) as exc:
        attempt = NativeAutomationAttempt(
            request_id=request.request_id,
            itp=request.itp,
            attempted=False,
            recovered=False,
            skipped_reason=f"native automation fallback could not run: {exc}",
        )
        attempt.validate()
        return attempt

    attempt = NativeAutomationAttempt(
        request_id=request.request_id,
        itp=request.itp,
        attempted=True,
        recovered=record.kernel_accepted,
        proof_candidate=candidate,
        reconstruction=record,
        evidence=evidence,
        environment_lock=lock,
    )
    attempt.validate()
    return attempt


# ---------------------------------------------------------------------------
# Decomposition plan construction
# ---------------------------------------------------------------------------


def build_decomposition_plan(
    *,
    request: HammerRequest,
    trigger: FallbackTrigger,
    goal_snapshot: GoalSnapshot,
    llm_decomposition_provider: Optional[
        Callable[[GoalSnapshot], Sequence[str]]
    ] = None,
) -> DecompositionPlan:
    """Build a bounded :class:`DecompositionPlan` for ``goal_snapshot``.

    Native-structural subgoals (from :func:`split_top_level_conjuncts`) are
    always considered first. If room remains under
    :attr:`~.models.HammerPolicy.max_decomposition_subgoals` and both
    ``llm_decomposition_provider`` is supplied and
    :attr:`~.models.HammerPolicy.allow_llm_decomposition_hints` is ``True``,
    up to the remaining budget of its suggestions are folded in as
    :data:`DecompositionSource.LLM_SUGGESTED` subgoals — each immediately
    redacted (:func:`redact_llm_text`) and left at
    :attr:`ReviewStatus.PENDING_REVIEW`, never trusted until
    :func:`review_decomposition_subgoal` and then
    :func:`verify_decomposition_subgoal` both succeed.
    """

    if not isinstance(trigger, FallbackTrigger):
        raise FallbackInputError("trigger must be a FallbackTrigger")

    max_subgoals = request.policy.max_decomposition_subgoals
    notes: List[str] = []
    subgoals: List[DecompositionSubgoal] = []

    native_statements = split_top_level_conjuncts(
        goal_snapshot.goal_text, max_parts=max_subgoals
    )
    if not native_statements:
        notes.append(
            "no top-level conjunction connective (∧ / /\\) was found in "
            "goal_text; no native-structural decomposition is available for "
            "this goal"
        )
    for text in native_statements:
        rank = len(subgoals)
        digest = compute_content_digest({"statement": text})
        subgoal_id = compute_content_digest(
            {
                "request_id": request.request_id,
                "theorem_id": request.theorem_id,
                "rank": rank,
                "source": DecompositionSource.NATIVE_STRUCTURAL.value,
                "statement": text,
            }
        )
        subgoal = DecompositionSubgoal(
            subgoal_id=subgoal_id,
            request_id=request.request_id,
            rank=rank,
            source=DecompositionSource.NATIVE_STRUCTURAL,
            statement=text,
            content_digest=digest,
        )
        subgoal.validate()
        subgoals.append(subgoal)

    remaining = max_subgoals - len(subgoals)
    if llm_decomposition_provider is not None:
        if not request.policy.allow_llm_decomposition_hints:
            notes.append(
                "an LLM decomposition provider was supplied but "
                "HammerPolicy.allow_llm_decomposition_hints is False; its "
                "suggestions were ignored"
            )
        elif remaining <= 0:
            notes.append(
                "an LLM decomposition provider was supplied but the plan "
                f"already reached its max_decomposition_subgoals bound "
                f"({max_subgoals}); its suggestions were ignored"
            )
        else:
            raw_suggestions = [
                text for text in (llm_decomposition_provider(goal_snapshot) or [])
                if isinstance(text, str) and text.strip()
            ]
            accepted = raw_suggestions[:remaining]
            for text in accepted:
                rank = len(subgoals)
                digest = compute_content_digest({"statement": text})
                subgoal_id = compute_content_digest(
                    {
                        "request_id": request.request_id,
                        "theorem_id": request.theorem_id,
                        "rank": rank,
                        "source": DecompositionSource.LLM_SUGGESTED.value,
                        "content_digest": digest,
                    }
                )
                subgoal = DecompositionSubgoal(
                    subgoal_id=subgoal_id,
                    request_id=request.request_id,
                    rank=rank,
                    source=DecompositionSource.LLM_SUGGESTED,
                    statement=text,
                    redacted_suggestion=redact_llm_text(text),
                    review_status=ReviewStatus.PENDING_REVIEW,
                    content_digest=digest,
                )
                subgoal.validate()
                subgoals.append(subgoal)
            if len(raw_suggestions) > len(accepted):
                notes.append(
                    f"LLM decomposition provider proposed "
                    f"{len(raw_suggestions)} subgoal(s); only "
                    f"{len(accepted)} were accepted to respect "
                    f"max_decomposition_subgoals={max_subgoals}"
                )

    plan_id = compute_content_digest(
        {
            "request_id": request.request_id,
            "theorem_id": request.theorem_id,
            "trigger": trigger.value,
            "subgoal_ids": [s.subgoal_id for s in subgoals],
        }
    )
    plan = DecompositionPlan(
        plan_id=plan_id,
        request_id=request.request_id,
        trigger=trigger,
        max_subgoals=max_subgoals,
        subgoals=subgoals,
        notes=notes,
    )
    plan.validate()
    return plan


# ---------------------------------------------------------------------------
# Subgoal review
# ---------------------------------------------------------------------------


def review_decomposition_subgoal(
    subgoal: DecompositionSubgoal,
    *,
    approve: bool,
    reviewer: str,
    notes: str = "",
) -> DecompositionSubgoal:
    """Record an explicit human review decision for an LLM-suggested
    ``subgoal``, mutating and returning it in place.

    This is the mandatory gate between an LLM proposing subgoal text and
    that text ever being handed to :func:`verify_decomposition_subgoal` for
    a native kernel-check attempt — approval does not make the subgoal
    trusted (only a passing kernel check, via ``status == VERIFIED``, does
    that); it only permits the attempt to proceed.

    Raises:
        FallbackInputError: If ``subgoal.source`` is not
            :data:`DecompositionSource.LLM_SUGGESTED` (native-structural
            subgoals never require review), if it has already been
            reviewed, or if ``reviewer`` is empty.
    """

    if subgoal.source is not DecompositionSource.LLM_SUGGESTED:
        raise FallbackInputError(
            "review_decomposition_subgoal only applies to LLM_SUGGESTED "
            "subgoals; NATIVE_STRUCTURAL subgoals never require review"
        )
    if subgoal.review_status in (ReviewStatus.REVIEWED, ReviewStatus.REJECTED):
        raise FallbackInputError(
            f"subgoal {subgoal.subgoal_id!r} has already been reviewed "
            f"(review_status={subgoal.review_status.value!r})"
        )
    if not reviewer or not reviewer.strip():
        raise FallbackInputError("reviewer must be a non-empty string")

    subgoal.review_status = ReviewStatus.REVIEWED if approve else ReviewStatus.REJECTED
    subgoal.reviewed_by = reviewer
    subgoal.reviewed_at = _utcnow()
    subgoal.review_notes = notes or None
    if not approve:
        subgoal.status = SubgoalStatus.REJECTED
    subgoal.validate()
    return subgoal


# ---------------------------------------------------------------------------
# Subgoal verification
# ---------------------------------------------------------------------------


def verify_decomposition_subgoal(
    subgoal: DecompositionSubgoal,
    *,
    request: HammerRequest,
    goal_snapshot: GoalSnapshot,
    reconstructor: Optional[Reconstructor] = None,
    environment_lock: Optional[EnvironmentLockRecord] = None,
    timeout: Optional[float] = None,
) -> Tuple[DecompositionSubgoal, Optional[ReconstructionRecord], Optional[ReconstructionEvidence]]:
    """Attempt a genuine native reconstruction/kernel-check of ``subgoal``,
    mutating and returning it (plus the reconstruction record/evidence, if
    a kernel invocation was actually made) in place.

    Builds a self-contained native source for ``subgoal.statement`` (using
    ``goal_snapshot.hypotheses`` as parameter binders, following each
    target ITP's own declaration syntax — see the ``_build_*_subgoal_source``
    helpers) and reuses HAMMER-010's reconstructor machinery with a
    synthetic, empty-``premise_ids`` candidate, exactly like
    :func:`attempt_native_automation`.

    ``subgoal.status`` becomes :attr:`SubgoalStatus.VERIFIED` only if the
    target ITP kernel genuinely accepted the reconstruction —
    :attr:`SubgoalStatus.REJECTED` otherwise (kernel ran and rejected it, or
    a human reviewer already rejected the subgoal) or
    :attr:`SubgoalStatus.SKIPPED` when the target kernel is unavailable in
    this environment (no attempt was made).

    Raises:
        FallbackInputError: If ``subgoal.request_id`` does not match
            ``request.request_id``, if ``subgoal`` is already
            :attr:`SubgoalStatus.VERIFIED`, if ``subgoal.review_status`` is
            :attr:`ReviewStatus.REJECTED`, or if an LLM-suggested
            ``subgoal`` has not yet been reviewed and approved via
            :func:`review_decomposition_subgoal`. In every one of these
            cases no kernel invocation is made.
    """

    if subgoal.request_id != request.request_id:
        raise FallbackInputError(
            "subgoal.request_id does not match request.request_id"
        )
    if subgoal.status is SubgoalStatus.VERIFIED:
        raise FallbackInputError(
            f"subgoal {subgoal.subgoal_id!r} has already been verified"
        )
    if subgoal.review_status is ReviewStatus.REJECTED:
        raise FallbackInputError(
            f"subgoal {subgoal.subgoal_id!r} was rejected during review and "
            "cannot be verified"
        )
    if (
        subgoal.source is DecompositionSource.LLM_SUGGESTED
        and subgoal.review_status is not ReviewStatus.REVIEWED
    ):
        raise FallbackInputError(
            f"subgoal {subgoal.subgoal_id!r} is LLM-suggested and must be "
            "explicitly reviewed and approved (see "
            "review_decomposition_subgoal) before its native subproof may "
            "even be attempted"
        )

    resolved_reconstructor = reconstructor or get_reconstructor(
        request.itp, timeout=timeout or DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS
    )
    capability = resolved_reconstructor.capability()
    if not capability.available:
        subgoal.status = SubgoalStatus.SKIPPED
        subgoal.validate()
        return subgoal, None, None

    decl_name = _safe_identifier(
        f"hammer_fallback_subgoal_{subgoal.rank}_{subgoal.subgoal_id}"
    )
    synthetic_source = _build_native_subgoal_source(
        request.itp, decl_name, goal_snapshot.hypotheses, subgoal.statement
    )
    synthetic_snapshot = GoalSnapshot(
        itp=request.itp,
        itp_version=goal_snapshot.itp_version,
        theorem_id=request.theorem_id,
        goal_text=subgoal.statement,
        hypotheses=list(goal_snapshot.hypotheses),
        imports=list(goal_snapshot.imports),
        source_position=SourcePosition(file=f"<synthetic-decomposition:{decl_name}>", line=1, column=0),
        native_command=["synthetic-decomposition-subgoal", decl_name],
        raw_native_output=(
            f"synthetic decomposition subgoal (rank {subgoal.rank}) derived "
            f"from parent theorem {request.theorem_id!r}'s goal_text via "
            "bounded structural/LLM-suggested decomposition; not "
            "independently captured via a native ITP diagnostic invocation"
        ),
        extra={
            "synthetic_decomposition": True,
            "parent_theorem_id": request.theorem_id,
            "subgoal_id": subgoal.subgoal_id,
            "subgoal_rank": subgoal.rank,
            "subgoal_source": subgoal.source.value,
        },
    )
    synthetic_snapshot.validate()

    candidate = ProofCandidateRecord(
        candidate_id=compute_content_digest(
            {
                "kind": "decomposition-subgoal",
                "subgoal_id": subgoal.subgoal_id,
                "request_id": request.request_id,
            }
        ),
        request_id=request.request_id,
        solver_attempt_id=f"decomposition-subgoal::{subgoal.subgoal_id}",
        premise_ids=[],
    )
    candidate.validate()

    record, evidence, _lock = resolved_reconstructor.reconstruct(
        request=request,
        candidate=candidate,
        goal_snapshot=synthetic_snapshot,
        native_source=synthetic_source,
        environment_lock=environment_lock,
        timeout=timeout,
    )

    subgoal.reconstruction_id = record.reconstruction_id
    subgoal.status = (
        SubgoalStatus.VERIFIED if record.kernel_accepted else SubgoalStatus.REJECTED
    )
    subgoal.validate()
    return subgoal, record, evidence


# ---------------------------------------------------------------------------
# Top-level recovery orchestrator
# ---------------------------------------------------------------------------


def attempt_fallback(
    *,
    request: HammerRequest,
    trigger: FallbackTrigger,
    goal_snapshot: GoalSnapshot,
    native_source: str,
    reconstructor: Optional[Reconstructor] = None,
    environment_lock: Optional[EnvironmentLockRecord] = None,
    timeout: Optional[float] = None,
    llm_decomposition_provider: Optional[
        Callable[[GoalSnapshot], Sequence[str]]
    ] = None,
) -> FallbackOutcome:
    """Run the full HAMMER-011 recovery pipeline for one translation,
    search, or reconstruction failure.

    First tries :func:`attempt_native_automation`; if that recovers the
    goal, returns immediately with no decomposition plan (there is nothing
    left to recover). Otherwise builds a bounded
    :func:`build_decomposition_plan` recording why native automation did
    not recover the goal.

    Raises:
        FallbackInputError: If ``trigger`` is not a :class:`FallbackTrigger`,
            or ``goal_snapshot`` does not genuinely belong to ``request``
            (mismatched ``itp``/``theorem_id``).
    """

    if not isinstance(trigger, FallbackTrigger):
        raise FallbackInputError("trigger must be a FallbackTrigger")
    if goal_snapshot.itp is not request.itp:
        raise FallbackInputError(
            f"goal_snapshot.itp={goal_snapshot.itp.value!r} does not match "
            f"request.itp={request.itp.value!r}"
        )
    if goal_snapshot.theorem_id != request.theorem_id:
        raise FallbackInputError(
            f"goal_snapshot.theorem_id={goal_snapshot.theorem_id!r} does not "
            f"match request.theorem_id={request.theorem_id!r}"
        )

    native_automation = attempt_native_automation(
        request=request,
        goal_snapshot=goal_snapshot,
        native_source=native_source,
        reconstructor=reconstructor,
        environment_lock=environment_lock,
        timeout=timeout,
    )

    notes: List[str] = []
    errors: List[str] = []
    decomposition_plan: Optional[DecompositionPlan] = None
    recovered = native_automation.recovered

    if recovered:
        notes.append(
            "native automation fallback independently reconstructed and "
            f"kernel-verified the goal via {request.itp.value}; no "
            "decomposition plan was needed"
        )
    else:
        if native_automation.attempted:
            assert native_automation.reconstruction is not None
            errors.append(
                "native automation fallback ran but the kernel rejected the "
                "reconstructed proof: "
                f"{native_automation.reconstruction.failure_reason}"
            )
        else:
            notes.append(
                "native automation fallback was not attempted: "
                f"{native_automation.skipped_reason}"
            )

        decomposition_plan = build_decomposition_plan(
            request=request,
            trigger=trigger,
            goal_snapshot=goal_snapshot,
            llm_decomposition_provider=llm_decomposition_provider,
        )

    outcome_id = compute_content_digest(
        {
            "request_id": request.request_id,
            "theorem_id": request.theorem_id,
            "trigger": trigger.value,
            "native_automation_attempted": native_automation.attempted,
            "native_automation_recovered": native_automation.recovered,
            "decomposition_plan_id": (
                decomposition_plan.plan_id if decomposition_plan else None
            ),
        }
    )

    outcome = FallbackOutcome(
        outcome_id=outcome_id,
        request_id=request.request_id,
        trigger=trigger,
        native_automation=native_automation,
        decomposition_plan=decomposition_plan,
        recovered=recovered,
        notes=notes,
        errors=errors,
    )
    outcome.validate()
    return outcome
