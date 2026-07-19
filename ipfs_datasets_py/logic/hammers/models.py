"""Trust contract and result schema for the ITP hammer pipeline.

This module defines the versioned records that make up the hammer trust
contract described in ``docs/logic/itp_hammer_contract.md`` and the
``## HAMMER-001`` entry of ``docs/logic/itp_hammer_taskboard.todo.md``:

- :class:`HammerRequest` — the versioned request that starts a hammer run.
- :class:`PremiseRecord` — a single premise selected from the corpus.
- :class:`TranslationRecord` — a lowering of a goal/premise to TPTP or
  SMT-LIB, including obligations for unsupported constructs.
- :class:`SolverAttemptRecord` — one bounded external solver invocation.
- :class:`ProofCandidateRecord` — an *untrusted* candidate proof/certificate
  produced by a solver attempt.
- :class:`ReconstructionRecord` — the record of feeding a candidate back
  through the target ITP kernel for an independent, trusted check.
- :class:`EnvironmentLockRecord` — the pinned tool/solver/OS environment a
  reconstruction ran under.
- :class:`HammerResult` — the final, versioned outcome that ties every other
  record together.

Trust boundary
---------------
A solver ``sat``, ``unsat``, or ``proved`` response is **never** trusted on
its own — it can only ever produce a :class:`ProofCandidateRecord`, which is
inherently unverified. The *only* way a :class:`HammerResult` may reach
``HammerResultStatus.VERIFIED`` is for it to carry a
:class:`ReconstructionRecord` whose ``kernel_accepted`` field is ``True``,
itself referencing the :class:`ProofCandidateRecord` that was checked and the
:class:`EnvironmentLockRecord` the kernel ran under. This invariant is
enforced at construction time (see :meth:`HammerResult.__post_init__`) and
cannot be bypassed by simply setting ``status=HammerResultStatus.VERIFIED``.

All records are versioned via a ``schema_version`` field so that persisted
results can be migrated as the contract evolves.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Schema versioning
# ---------------------------------------------------------------------------

#: Current schema version for every record defined in this module. Bump this
#: (and add the previous value to ``SUPPORTED_SCHEMA_VERSIONS``) whenever a
#: backward-incompatible change is made to a record's shape.
SCHEMA_VERSION = "1.0.0"

#: Schema versions that :meth:`*.validate` methods accept. Older, still
#: readable versions can be added here as the contract evolves without
#: forcing every historical record to be rewritten.
SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION})


def _utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp.

    Centralized so every record uses the same clock semantics and so tests
    can monkeypatch a single function if deterministic timestamps are ever
    required.
    """

    return datetime.now(timezone.utc)


def _require_schema_version(schema_version: str, *, owner: str) -> None:
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(
            f"{owner}.schema_version={schema_version!r} is not one of the "
            f"supported versions {sorted(SUPPORTED_SCHEMA_VERSIONS)!r}"
        )


def _require_nonempty_str(value: Any, *, field_name: str, owner: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{owner}.{field_name} must be a non-empty string")


def _require_finite_float(value: Any, *, field_name: str, owner: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{owner}.{field_name} must be a number")
    if not math.isfinite(float(value)):
        raise ValueError(f"{owner}.{field_name} must be finite, got {value!r}")


def _isoformat(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _parse_datetime(value: Any) -> Any:
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ITPKind(str, Enum):
    """Interactive Theorem Provers with a native frontend/reconstruction
    adapter contract (see HAMMER-006). Extend this enum only after adding a
    matching frontend adapter — never to describe a plain-text stand-in."""

    LEAN = "lean"
    COQ = "coq"
    ISABELLE = "isabelle"


class TranslationTarget(str, Enum):
    """Untrusted external solver input formats supported by the pipeline."""

    TPTP = "tptp"
    SMTLIB = "smtlib"


class TranslationStatus(str, Enum):
    """Outcome of lowering a single construct to a translation target.

    ``UNSUPPORTED`` must be produced explicitly whenever a dependent,
    higher-order, polymorphic, or lambda construct cannot be lowered —
    silently dropping such a construct to "make the translation succeed" is
    the failure mode this contract exists to prevent.
    """

    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


class SolverVerdict(str, Enum):
    """Raw, untrusted verdict returned by an external ATP/SMT solver.

    None of these values may be interpreted as a verified proof. They only
    describe what the *solver* claimed; see the module docstring for the
    trust boundary that gates :attr:`HammerResultStatus.VERIFIED`.
    """

    SAT = "sat"
    UNSAT = "unsat"
    PROVED = "proved"
    DISPROVED = "disproved"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    ERROR = "error"


class HammerResultStatus(str, Enum):
    """Final, authoritative status of a hammer run.

    ``VERIFIED`` is the only status that asserts a checked theorem. Every
    other status is either an unverified candidate, an explicit refusal, or
    an explicit failure/capability gap.
    """

    #: The reconstructed proof was independently accepted by the target ITP
    #: kernel. The *only* status that asserts a checked theorem.
    VERIFIED = "verified"
    #: A solver produced an untrusted proof/certificate that has not yet
    #: (or could not) be reconstructed and kernel-checked.
    CANDIDATE = "candidate"
    #: A solver produced an untrusted countermodel/refutation.
    COUNTEREXAMPLE = "counterexample"
    #: No solver reached a conclusive verdict within budget.
    UNKNOWN = "unknown"
    #: Every attempted solver exhausted its bounded timeout.
    TIMEOUT = "timeout"
    #: The goal or a required construct could not be lowered to any
    #: supported translation target.
    UNSUPPORTED_TRANSLATION = "unsupported_translation"
    #: A required capability (ITP, solver, frontend) was not present in the
    #: environment; nothing was executed.
    UNAVAILABLE = "unavailable"
    #: Policy configuration (timeouts, CPU/memory budget, network access,
    #: allowed solver list, disabled learned components, ...) forbade the
    #: run before any solver or kernel executed.
    POLICY_DENIED = "policy_denied"


#: Statuses that assert an untrusted, solver-produced outcome. Used by
#: :meth:`HammerResult.validate` to decide whether a
#: :class:`ProofCandidateRecord` or :class:`SolverAttemptRecord` is expected.
_SOLVER_BACKED_STATUSES = frozenset(
    {
        HammerResultStatus.CANDIDATE,
        HammerResultStatus.COUNTEREXAMPLE,
        HammerResultStatus.UNKNOWN,
        HammerResultStatus.TIMEOUT,
    }
)

#: Statuses that must precede any solver execution — nothing ran, so no
#: solver attempt, proof candidate, or reconstruction record may be present.
_PRE_EXECUTION_STATUSES = frozenset(
    {
        HammerResultStatus.UNSUPPORTED_TRANSLATION,
        HammerResultStatus.UNAVAILABLE,
        HammerResultStatus.POLICY_DENIED,
    }
)


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


@dataclass
class HammerPolicy:
    """Operator-controlled budget and capability policy for a hammer run.

    Every external executable path, timeout, CPU/memory budget, and network
    access decision must flow through this record; nothing in the pipeline
    may hard-code those values.

    Attributes:
        schema_version: Schema version of this record.
        timeout_seconds: Wall-clock budget for a single solver attempt.
        cpu_seconds: Optional CPU-time budget for a single solver attempt.
        memory_mb: Optional memory budget (MiB) for a single solver attempt.
        network_allowed: Whether a solver attempt may access the network.
        allowed_solvers: Allow-list of solver names permitted to run
            (e.g. ``["z3", "cvc5", "vampire", "eprover"]``). Empty means no
            external solver may run (translation-only / dry-run policy).
        allow_learned_premise_selector: Whether an optional learned premise
            selector (HAMMER-005) may be used instead of the deterministic
            baseline. Defaults to ``False`` per the taskboard's opt-in rule.
        allow_llm_premise_ranking: Whether an LLM may propose premise
            rankings/decomposition plans. An LLM may never supply an
            accepted proof or suppress an ``unsupported_translation`` result
            regardless of this flag.
        max_premises: Upper bound on premises selected for a single request.
        allow_native_automation_fallback: Whether the HAMMER-011 recovery
            pipeline (:mod:`.fallbacks`) may, on a translation, search, or
            reconstruction failure, try an explicitly enabled native
            automation tactic (e.g. Lean's built-in closing tactics) via the
            target ITP's own kernel. Defaults to ``False`` per the
            taskboard's "explicitly enabled" requirement; a caller must
            opt in per-request.
        allow_llm_decomposition_hints: Whether the HAMMER-011 recovery
            pipeline may fold LLM-suggested subgoal statements into its
            bounded decomposition plan. Every LLM-suggested subgoal is
            still redacted, requires explicit human review, and remains
            untrusted until its own native reconstruction independently
            passes the target ITP kernel (see
            :mod:`~ipfs_datasets_py.logic.hammers.fallbacks`) regardless of
            this flag; the flag only controls whether such suggestions are
            considered at all.
        max_decomposition_subgoals: Upper bound on the number of subgoals a
            HAMMER-011 decomposition plan may contain (native-structural and
            LLM-suggested combined).
    """

    schema_version: str = SCHEMA_VERSION
    timeout_seconds: float = 30.0
    cpu_seconds: Optional[float] = None
    memory_mb: Optional[int] = None
    network_allowed: bool = False
    allowed_solvers: List[str] = field(default_factory=list)
    allow_learned_premise_selector: bool = False
    allow_llm_premise_ranking: bool = False
    max_premises: int = 64
    allow_native_automation_fallback: bool = False
    allow_llm_decomposition_hints: bool = False
    max_decomposition_subgoals: int = 4

    def validate(self) -> None:
        """Validate field constraints, raising ``ValueError`` on failure."""

        _require_schema_version(self.schema_version, owner="HammerPolicy")
        if self.timeout_seconds <= 0:
            raise ValueError("HammerPolicy.timeout_seconds must be positive")
        if self.cpu_seconds is not None and self.cpu_seconds <= 0:
            raise ValueError("HammerPolicy.cpu_seconds must be positive if set")
        if self.memory_mb is not None and self.memory_mb <= 0:
            raise ValueError("HammerPolicy.memory_mb must be positive if set")
        if not isinstance(self.network_allowed, bool):
            raise ValueError("HammerPolicy.network_allowed must be a boolean")
        if not isinstance(self.allowed_solvers, list) or not all(
            isinstance(name, str) and name.strip() for name in self.allowed_solvers
        ):
            raise ValueError(
                "HammerPolicy.allowed_solvers must be a list of non-empty strings"
            )
        if len(set(self.allowed_solvers)) != len(self.allowed_solvers):
            raise ValueError("HammerPolicy.allowed_solvers must not contain duplicates")
        if not isinstance(self.allow_learned_premise_selector, bool):
            raise ValueError(
                "HammerPolicy.allow_learned_premise_selector must be a boolean"
            )
        if not isinstance(self.allow_llm_premise_ranking, bool):
            raise ValueError("HammerPolicy.allow_llm_premise_ranking must be a boolean")
        if self.max_premises <= 0:
            raise ValueError("HammerPolicy.max_premises must be positive")
        if not isinstance(self.allow_native_automation_fallback, bool):
            raise ValueError(
                "HammerPolicy.allow_native_automation_fallback must be a boolean"
            )
        if not isinstance(self.allow_llm_decomposition_hints, bool):
            raise ValueError(
                "HammerPolicy.allow_llm_decomposition_hints must be a boolean"
            )
        if self.max_decomposition_subgoals <= 0:
            raise ValueError(
                "HammerPolicy.max_decomposition_subgoals must be positive"
            )

    def permits_solver(self, solver_name: str) -> bool:
        """Return whether ``solver_name`` is on the allow-list."""

        return solver_name in self.allowed_solvers

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HammerPolicy":
        return cls(**dict(data))


# ---------------------------------------------------------------------------
# Environment lock
# ---------------------------------------------------------------------------


@dataclass
class EnvironmentLockRecord:
    """A pinned, versioned snapshot of the environment a reconstruction ran
    under.

    A :class:`ReconstructionRecord` may only be trusted if its
    ``environment_lock_id`` resolves to one of these records, and every field
    here is meant to be reproducible/auditable (no floating "latest" tags).

    Attributes:
        schema_version: Schema version of this record.
        lock_id: Stable identifier for this environment snapshot (e.g. a
            content digest of the fields below).
        itp: Target ITP this lock applies to.
        itp_version: Exact ITP kernel/toolchain version string.
        kernel_command_template: Template of the command used to invoke the
            ITP kernel/checker for reconstruction (with placeholders, not a
            fabricated example).
        solver_versions: Mapping of external solver name -> exact version
            string (e.g. ``{"z3": "4.13.0"}``) for every solver that may be
            invoked under this lock.
        executable_paths: Mapping of tool name -> resolved executable path
            used at lock time.
        os_info: Human-readable OS/platform description.
        container_digest: Optional content digest of a container image or
            filesystem snapshot backing this lock.
        pinned_at: When this lock was captured.
        policy_digest: Optional digest of the :class:`HammerPolicy` that was
            in effect when this lock was captured.
    """

    schema_version: str = SCHEMA_VERSION
    lock_id: str = ""
    itp: ITPKind = ITPKind.LEAN
    itp_version: str = ""
    kernel_command_template: str = ""
    solver_versions: Dict[str, str] = field(default_factory=dict)
    executable_paths: Dict[str, str] = field(default_factory=dict)
    os_info: str = ""
    container_digest: Optional[str] = None
    pinned_at: datetime = field(default_factory=_utcnow)
    policy_digest: Optional[str] = None

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="EnvironmentLockRecord")
        _require_nonempty_str(self.lock_id, field_name="lock_id", owner="EnvironmentLockRecord")
        if not isinstance(self.itp, ITPKind):
            raise ValueError("EnvironmentLockRecord.itp must be an ITPKind")
        _require_nonempty_str(
            self.itp_version, field_name="itp_version", owner="EnvironmentLockRecord"
        )
        _require_nonempty_str(
            self.kernel_command_template,
            field_name="kernel_command_template",
            owner="EnvironmentLockRecord",
        )
        if not isinstance(self.solver_versions, dict) or not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in self.solver_versions.items()
        ):
            raise ValueError(
                "EnvironmentLockRecord.solver_versions must map str -> str"
            )
        if not isinstance(self.executable_paths, dict) or not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in self.executable_paths.items()
        ):
            raise ValueError(
                "EnvironmentLockRecord.executable_paths must map str -> str"
            )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["itp"] = self.itp.value
        data["pinned_at"] = _isoformat(self.pinned_at)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EnvironmentLockRecord":
        data = dict(data)
        if isinstance(data.get("itp"), str):
            data["itp"] = ITPKind(data["itp"])
        if "pinned_at" in data:
            data["pinned_at"] = _parse_datetime(data["pinned_at"])
        return cls(**data)


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


@dataclass
class HammerRequest:
    """A versioned request to run the hammer pipeline against one goal.

    Attributes:
        schema_version: Schema version of this record.
        request_id: Caller-assigned unique identifier for this request.
        itp: Source/target ITP the goal originates from.
        theorem_id: Identifier of the theorem/goal within its source corpus
            or ITP session (stable across reruns).
        goal_statement: Human-readable rendering of the goal being attempted
            (diagnostic only — the authoritative goal lives in the native
            frontend snapshot produced by HAMMER-006).
        corpus_revision: Revision/identity of the premise corpus manifest
            (HAMMER-003) this request is bound to.
        policy: Budget/capability policy governing this request.
        created_at: When the request was created.
        metadata: Free-form, non-authoritative caller metadata (e.g. a
            tracing correlation id). Must not carry data required for
            correctness.
    """

    schema_version: str = SCHEMA_VERSION
    request_id: str = ""
    itp: ITPKind = ITPKind.LEAN
    theorem_id: str = ""
    goal_statement: str = ""
    corpus_revision: str = ""
    policy: HammerPolicy = field(default_factory=HammerPolicy)
    created_at: datetime = field(default_factory=_utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="HammerRequest")
        _require_nonempty_str(self.request_id, field_name="request_id", owner="HammerRequest")
        if not isinstance(self.itp, ITPKind):
            raise ValueError("HammerRequest.itp must be an ITPKind")
        _require_nonempty_str(self.theorem_id, field_name="theorem_id", owner="HammerRequest")
        _require_nonempty_str(
            self.goal_statement, field_name="goal_statement", owner="HammerRequest"
        )
        _require_nonempty_str(
            self.corpus_revision, field_name="corpus_revision", owner="HammerRequest"
        )
        if not isinstance(self.policy, HammerPolicy):
            raise ValueError("HammerRequest.policy must be a HammerPolicy")
        self.policy.validate()
        if not isinstance(self.metadata, dict):
            raise ValueError("HammerRequest.metadata must be a dict")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "itp": self.itp.value,
            "theorem_id": self.theorem_id,
            "goal_statement": self.goal_statement,
            "corpus_revision": self.corpus_revision,
            "policy": self.policy.to_dict(),
            "created_at": _isoformat(self.created_at),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HammerRequest":
        data = dict(data)
        if isinstance(data.get("itp"), str):
            data["itp"] = ITPKind(data["itp"])
        if isinstance(data.get("policy"), dict):
            data["policy"] = HammerPolicy.from_dict(data["policy"])
        if "created_at" in data:
            data["created_at"] = _parse_datetime(data["created_at"])
        return cls(**data)


# ---------------------------------------------------------------------------
# Premise
# ---------------------------------------------------------------------------


@dataclass
class PremiseRecord:
    """A single premise selected from the content-addressed corpus.

    Attributes:
        schema_version: Schema version of this record.
        premise_id: Stable identifier of the premise within the corpus.
        statement: Rendered statement of the premise (diagnostic; the
            authoritative form lives in the corpus manifest of HAMMER-003).
        source_itp: ITP the premise's identity/statement is native to.
        corpus_revision: Corpus manifest revision this premise was drawn
            from; must match the owning request's ``corpus_revision``.
        rank: 0-indexed rank within the selection (0 = highest priority);
            enforces the taskboard's "stable ordering" requirement.
        score: Deterministic selection score (unbounded but finite; higher
            is not required to mean "better" — selectors define their own
            scale, but it must be reproducible for identical input).
        selection_method: Identifier of the selector that produced this
            record (e.g. ``"deterministic-baseline"`` or a pinned learned
            selector's model digest per HAMMER-005's opt-in gate).
        content_digest: Optional content digest/CID of the premise.
    """

    schema_version: str = SCHEMA_VERSION
    premise_id: str = ""
    statement: str = ""
    source_itp: ITPKind = ITPKind.LEAN
    corpus_revision: str = ""
    rank: int = 0
    score: float = 0.0
    selection_method: str = "deterministic-baseline"
    content_digest: Optional[str] = None

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="PremiseRecord")
        _require_nonempty_str(self.premise_id, field_name="premise_id", owner="PremiseRecord")
        _require_nonempty_str(self.statement, field_name="statement", owner="PremiseRecord")
        if not isinstance(self.source_itp, ITPKind):
            raise ValueError("PremiseRecord.source_itp must be an ITPKind")
        _require_nonempty_str(
            self.corpus_revision, field_name="corpus_revision", owner="PremiseRecord"
        )
        if self.rank < 0:
            raise ValueError("PremiseRecord.rank must be non-negative")
        _require_finite_float(self.score, field_name="score", owner="PremiseRecord")
        _require_nonempty_str(
            self.selection_method, field_name="selection_method", owner="PremiseRecord"
        )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["source_itp"] = self.source_itp.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PremiseRecord":
        data = dict(data)
        if isinstance(data.get("source_itp"), str):
            data["source_itp"] = ITPKind(data["source_itp"])
        return cls(**data)


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------


@dataclass
class TranslationRecord:
    """The result of lowering one goal/premise construct to a translation
    target.

    Attributes:
        schema_version: Schema version of this record.
        translation_id: Stable identifier of this translation record.
        request_id: Owning :class:`HammerRequest` id.
        target: Translation target format.
        status: Whether the construct was fully, partially, or not lowered.
        source_construct: Identifier/description of the source construct
            being translated (e.g. a goal id or premise id).
        translated_text: The produced TPTP/SMT-LIB text. Required when
            ``status`` is ``SUPPORTED``; forbidden when ``UNSUPPORTED``.
        obligations: Side conditions/assumptions introduced by the
            translation (e.g. monomorphization instances, lambda-lifted
            definitions) that a reconstruction must discharge or account
            for. Required (non-empty) when ``status`` is ``PARTIAL``.
        unsupported_reason: Human-readable explanation of why the construct
            could not be translated. Required when ``status`` is
            ``UNSUPPORTED``; this is what prevents unsupported constructs
            from silently vanishing.
        content_digest: Optional content digest of the translated text.
    """

    schema_version: str = SCHEMA_VERSION
    translation_id: str = ""
    request_id: str = ""
    target: TranslationTarget = TranslationTarget.TPTP
    status: TranslationStatus = TranslationStatus.SUPPORTED
    source_construct: str = ""
    translated_text: Optional[str] = None
    obligations: List[str] = field(default_factory=list)
    unsupported_reason: Optional[str] = None
    content_digest: Optional[str] = None

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="TranslationRecord")
        _require_nonempty_str(
            self.translation_id, field_name="translation_id", owner="TranslationRecord"
        )
        _require_nonempty_str(
            self.request_id, field_name="request_id", owner="TranslationRecord"
        )
        if not isinstance(self.target, TranslationTarget):
            raise ValueError("TranslationRecord.target must be a TranslationTarget")
        if not isinstance(self.status, TranslationStatus):
            raise ValueError("TranslationRecord.status must be a TranslationStatus")
        _require_nonempty_str(
            self.source_construct,
            field_name="source_construct",
            owner="TranslationRecord",
        )
        if not isinstance(self.obligations, list) or not all(
            isinstance(o, str) and o.strip() for o in self.obligations
        ):
            raise ValueError(
                "TranslationRecord.obligations must be a list of non-empty strings"
            )

        if self.status is TranslationStatus.SUPPORTED:
            _require_nonempty_str(
                self.translated_text,
                field_name="translated_text",
                owner="TranslationRecord",
            )
            if self.unsupported_reason is not None:
                raise ValueError(
                    "TranslationRecord.unsupported_reason must be None when "
                    "status is SUPPORTED"
                )
        elif self.status is TranslationStatus.PARTIAL:
            _require_nonempty_str(
                self.translated_text,
                field_name="translated_text",
                owner="TranslationRecord",
            )
            if not self.obligations:
                raise ValueError(
                    "TranslationRecord.obligations must be non-empty when "
                    "status is PARTIAL, documenting what remains unhandled"
                )
        elif self.status is TranslationStatus.UNSUPPORTED:
            _require_nonempty_str(
                self.unsupported_reason,
                field_name="unsupported_reason",
                owner="TranslationRecord",
            )
            if self.translated_text is not None:
                raise ValueError(
                    "TranslationRecord.translated_text must be None when "
                    "status is UNSUPPORTED — a rejected construct must not "
                    "also carry translated output"
                )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["target"] = self.target.value
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TranslationRecord":
        data = dict(data)
        if isinstance(data.get("target"), str):
            data["target"] = TranslationTarget(data["target"])
        if isinstance(data.get("status"), str):
            data["status"] = TranslationStatus(data["status"])
        return cls(**data)


# ---------------------------------------------------------------------------
# Solver attempt
# ---------------------------------------------------------------------------


@dataclass
class SolverAttemptRecord:
    """One bounded, policy-controlled external solver invocation.

    Attributes:
        schema_version: Schema version of this record.
        attempt_id: Stable identifier of this attempt.
        request_id: Owning :class:`HammerRequest` id.
        translation_id: :class:`TranslationRecord` id this attempt consumed.
        solver_name: Name of the external solver (must be present in the
            owning request's ``policy.allowed_solvers``).
        solver_version: Exact solver version string, if known.
        target: Translation target format the solver consumed.
        timeout_seconds: Wall-clock budget enforced for this attempt (must
            not exceed the owning policy's ``timeout_seconds``).
        verdict: Raw, untrusted verdict reported by the solver.
        exit_code: Process exit code, if applicable.
        wall_time_seconds: Observed wall-clock duration.
        raw_output_digest: Content digest of the solver's raw stdout/stderr
            (kept out-of-band to bound record size; store full logs
            separately, addressed by this digest).
        started_at: When the attempt started.
        finished_at: When the attempt finished (``None`` while running).
        resource_usage: Observed resource usage (e.g. ``{"cpu_seconds":
            1.2, "max_rss_mb": 128}``).
        network_used: Whether the attempt used network access (must be
            ``False`` unless the owning policy set ``network_allowed``).
    """

    schema_version: str = SCHEMA_VERSION
    attempt_id: str = ""
    request_id: str = ""
    translation_id: str = ""
    solver_name: str = ""
    solver_version: Optional[str] = None
    target: TranslationTarget = TranslationTarget.TPTP
    timeout_seconds: float = 30.0
    verdict: SolverVerdict = SolverVerdict.UNKNOWN
    exit_code: Optional[int] = None
    wall_time_seconds: Optional[float] = None
    raw_output_digest: Optional[str] = None
    started_at: datetime = field(default_factory=_utcnow)
    finished_at: Optional[datetime] = None
    resource_usage: Dict[str, Any] = field(default_factory=dict)
    network_used: bool = False

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="SolverAttemptRecord")
        _require_nonempty_str(
            self.attempt_id, field_name="attempt_id", owner="SolverAttemptRecord"
        )
        _require_nonempty_str(
            self.request_id, field_name="request_id", owner="SolverAttemptRecord"
        )
        _require_nonempty_str(
            self.translation_id, field_name="translation_id", owner="SolverAttemptRecord"
        )
        _require_nonempty_str(
            self.solver_name, field_name="solver_name", owner="SolverAttemptRecord"
        )
        if not isinstance(self.target, TranslationTarget):
            raise ValueError("SolverAttemptRecord.target must be a TranslationTarget")
        if self.timeout_seconds <= 0:
            raise ValueError("SolverAttemptRecord.timeout_seconds must be positive")
        if not isinstance(self.verdict, SolverVerdict):
            raise ValueError("SolverAttemptRecord.verdict must be a SolverVerdict")
        if self.wall_time_seconds is not None and self.wall_time_seconds < 0:
            raise ValueError(
                "SolverAttemptRecord.wall_time_seconds must be non-negative"
            )
        if not isinstance(self.network_used, bool):
            raise ValueError("SolverAttemptRecord.network_used must be a boolean")
        if (
            self.finished_at is not None
            and self.started_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValueError(
                "SolverAttemptRecord.finished_at must not precede started_at"
            )
        # A timed-out attempt reporting a conclusive verdict is self-contradictory.
        if self.verdict is SolverVerdict.TIMEOUT and self.wall_time_seconds is not None:
            if self.wall_time_seconds < self.timeout_seconds - 1e-9:
                raise ValueError(
                    "SolverAttemptRecord.verdict is TIMEOUT but "
                    "wall_time_seconds is less than timeout_seconds"
                )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["target"] = self.target.value
        data["verdict"] = self.verdict.value
        data["started_at"] = _isoformat(self.started_at)
        data["finished_at"] = _isoformat(self.finished_at)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SolverAttemptRecord":
        data = dict(data)
        if isinstance(data.get("target"), str):
            data["target"] = TranslationTarget(data["target"])
        if isinstance(data.get("verdict"), str):
            data["verdict"] = SolverVerdict(data["verdict"])
        if "started_at" in data:
            data["started_at"] = _parse_datetime(data["started_at"])
        if "finished_at" in data:
            data["finished_at"] = _parse_datetime(data["finished_at"])
        return cls(**data)


# ---------------------------------------------------------------------------
# Proof candidate
# ---------------------------------------------------------------------------


@dataclass
class ProofCandidateRecord:
    """An *untrusted* candidate proof/certificate produced by a solver.

    A ``ProofCandidateRecord`` on its own never establishes a verified
    theorem — it is exactly the artifact that :class:`ReconstructionRecord`
    exists to independently check. There is deliberately no "verified" or
    "kernel_accepted" field on this record: that state can only be recorded
    on a :class:`ReconstructionRecord`, keeping the untrusted candidate and
    the trusted check as two distinct, separately auditable records.

    Attributes:
        schema_version: Schema version of this record.
        candidate_id: Stable identifier of this candidate.
        request_id: Owning :class:`HammerRequest` id.
        solver_attempt_id: :class:`SolverAttemptRecord` id that produced
            this candidate.
        premise_ids: Ids of the :class:`PremiseRecord` entries the solver
            reported using (may be empty if the solver used none/emitted no
            such information).
        certificate: Raw proof term/certificate/trace text, if available.
        certificate_format: Format of ``certificate`` (e.g. ``"tstp"``,
            ``"lfsc"``, ``"alethe"``).
    """

    schema_version: str = SCHEMA_VERSION
    candidate_id: str = ""
    request_id: str = ""
    solver_attempt_id: str = ""
    premise_ids: List[str] = field(default_factory=list)
    certificate: Optional[str] = None
    certificate_format: Optional[str] = None

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="ProofCandidateRecord")
        _require_nonempty_str(
            self.candidate_id, field_name="candidate_id", owner="ProofCandidateRecord"
        )
        _require_nonempty_str(
            self.request_id, field_name="request_id", owner="ProofCandidateRecord"
        )
        _require_nonempty_str(
            self.solver_attempt_id,
            field_name="solver_attempt_id",
            owner="ProofCandidateRecord",
        )
        if not isinstance(self.premise_ids, list) or not all(
            isinstance(p, str) and p.strip() for p in self.premise_ids
        ):
            raise ValueError(
                "ProofCandidateRecord.premise_ids must be a list of non-empty strings"
            )
        if self.certificate_format is not None and self.certificate is None:
            raise ValueError(
                "ProofCandidateRecord.certificate_format requires certificate to be set"
            )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProofCandidateRecord":
        return cls(**dict(data))


# ---------------------------------------------------------------------------
# Reconstruction
# ---------------------------------------------------------------------------


@dataclass
class ReconstructionRecord:
    """The record of feeding a proof candidate back through the target ITP
    kernel for an independent, trusted check.

    This is the *only* record type whose acceptance can promote a hammer run
    to :attr:`HammerResultStatus.VERIFIED`.

    Attributes:
        schema_version: Schema version of this record.
        reconstruction_id: Stable identifier of this reconstruction attempt.
        request_id: Owning :class:`HammerRequest` id.
        candidate_id: :class:`ProofCandidateRecord` id being reconstructed.
        target_itp: ITP whose kernel performed the check.
        environment_lock_id: :class:`EnvironmentLockRecord` id pinning the
            exact kernel/toolchain version used.
        kernel_command: Exact command/invocation used to run the kernel
            check (for audit/reproducibility).
        kernel_accepted: Whether the target ITP kernel accepted the
            reconstructed proof. This is the single bit of ground truth the
            whole trust contract is built around.
        kernel_output_digest: Content digest of the kernel's raw output.
        started_at: When the reconstruction attempt started.
        finished_at: When the reconstruction attempt finished.
        failure_reason: Required, human-readable explanation when
            ``kernel_accepted`` is ``False``.
    """

    schema_version: str = SCHEMA_VERSION
    reconstruction_id: str = ""
    request_id: str = ""
    candidate_id: str = ""
    target_itp: ITPKind = ITPKind.LEAN
    environment_lock_id: str = ""
    kernel_command: str = ""
    kernel_accepted: bool = False
    kernel_output_digest: Optional[str] = None
    started_at: datetime = field(default_factory=_utcnow)
    finished_at: Optional[datetime] = None
    failure_reason: Optional[str] = None

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="ReconstructionRecord")
        _require_nonempty_str(
            self.reconstruction_id,
            field_name="reconstruction_id",
            owner="ReconstructionRecord",
        )
        _require_nonempty_str(
            self.request_id, field_name="request_id", owner="ReconstructionRecord"
        )
        _require_nonempty_str(
            self.candidate_id, field_name="candidate_id", owner="ReconstructionRecord"
        )
        if not isinstance(self.target_itp, ITPKind):
            raise ValueError("ReconstructionRecord.target_itp must be an ITPKind")
        _require_nonempty_str(
            self.environment_lock_id,
            field_name="environment_lock_id",
            owner="ReconstructionRecord",
        )
        _require_nonempty_str(
            self.kernel_command, field_name="kernel_command", owner="ReconstructionRecord"
        )
        if not isinstance(self.kernel_accepted, bool):
            raise ValueError("ReconstructionRecord.kernel_accepted must be a boolean")
        if (
            self.finished_at is not None
            and self.started_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValueError(
                "ReconstructionRecord.finished_at must not precede started_at"
            )

        if self.kernel_accepted:
            if self.failure_reason is not None:
                raise ValueError(
                    "ReconstructionRecord.failure_reason must be None when "
                    "kernel_accepted is True"
                )
        else:
            _require_nonempty_str(
                self.failure_reason,
                field_name="failure_reason",
                owner="ReconstructionRecord",
            )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["target_itp"] = self.target_itp.value
        data["started_at"] = _isoformat(self.started_at)
        data["finished_at"] = _isoformat(self.finished_at)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReconstructionRecord":
        data = dict(data)
        if isinstance(data.get("target_itp"), str):
            data["target_itp"] = ITPKind(data["target_itp"])
        if "started_at" in data:
            data["started_at"] = _parse_datetime(data["started_at"])
        if "finished_at" in data:
            data["finished_at"] = _parse_datetime(data["finished_at"])
        return cls(**data)


# ---------------------------------------------------------------------------
# Final result
# ---------------------------------------------------------------------------


@dataclass
class HammerResult:
    """The final, versioned outcome of a hammer run.

    Construction eagerly validates the full record graph, including the
    hard trust-boundary invariant: ``status`` may only be ``VERIFIED`` if
    ``reconstruction`` is present with ``kernel_accepted is True``, and
    conversely any ``reconstruction`` with ``kernel_accepted is True`` must
    be reflected as ``status == VERIFIED``. This makes it impossible to
    construct a "verified" result without a successful kernel check, and
    impossible to bury a successful kernel check under a non-verified
    status.

    Attributes:
        schema_version: Schema version of this record.
        result_id: Stable identifier of this result.
        request: The :class:`HammerRequest` this result answers.
        status: Final :class:`HammerResultStatus`.
        corpus_revision: Corpus revision in effect for this result; must
            match ``request.corpus_revision``.
        environment_lock: Environment lock in effect, if any solver or
            kernel executed.
        premises: Premises selected for this run.
        translations: Translation attempts performed for this run.
        solver_attempts: Solver attempts performed for this run.
        proof_candidate: The untrusted candidate produced, if any.
        reconstruction: The kernel reconstruction/check record, if any.
        created_at: When the result record was created.
        completed_at: When the run completed.
        notes: Free-form, non-authoritative diagnostic notes.
        errors: Free-form, non-authoritative diagnostic error messages
            (e.g. policy-denial explanations or capability-gap details).
    """

    schema_version: str = SCHEMA_VERSION
    result_id: str = ""
    request: HammerRequest = field(default_factory=HammerRequest)
    status: HammerResultStatus = HammerResultStatus.UNKNOWN
    corpus_revision: str = ""
    environment_lock: Optional[EnvironmentLockRecord] = None
    premises: List[PremiseRecord] = field(default_factory=list)
    translations: List[TranslationRecord] = field(default_factory=list)
    solver_attempts: List[SolverAttemptRecord] = field(default_factory=list)
    proof_candidate: Optional[ProofCandidateRecord] = None
    reconstruction: Optional[ReconstructionRecord] = None
    created_at: datetime = field(default_factory=_utcnow)
    completed_at: Optional[datetime] = None
    notes: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Validation runs at construction time (not just on demand) so the
        # ``VERIFIED`` trust invariant cannot be bypassed by building an
        # otherwise-unvalidated HammerResult and never calling validate().
        self.validate()

    def validate(self) -> None:  # noqa: C901 - the invariant matrix is inherently branchy
        """Validate the full record graph and the result-state contract.

        Raises:
            ValueError: If any nested record is invalid, or if the
                combination of ``status`` and the presence/content of
                ``proof_candidate``/``reconstruction``/``solver_attempts``
                violates the hammer trust contract.
        """

        _require_schema_version(self.schema_version, owner="HammerResult")
        _require_nonempty_str(self.result_id, field_name="result_id", owner="HammerResult")

        if not isinstance(self.request, HammerRequest):
            raise ValueError("HammerResult.request must be a HammerRequest")
        self.request.validate()

        if not isinstance(self.status, HammerResultStatus):
            raise ValueError("HammerResult.status must be a HammerResultStatus")

        _require_nonempty_str(
            self.corpus_revision, field_name="corpus_revision", owner="HammerResult"
        )
        if self.corpus_revision != self.request.corpus_revision:
            raise ValueError(
                "HammerResult.corpus_revision must match request.corpus_revision "
                f"({self.corpus_revision!r} != {self.request.corpus_revision!r})"
            )

        if self.environment_lock is not None:
            if not isinstance(self.environment_lock, EnvironmentLockRecord):
                raise ValueError(
                    "HammerResult.environment_lock must be an EnvironmentLockRecord"
                )
            self.environment_lock.validate()

        for premise in self.premises:
            if not isinstance(premise, PremiseRecord):
                raise ValueError("HammerResult.premises must contain PremiseRecord")
            premise.validate()
        _validate_unique_ids(self.premises, attr="premise_id", owner="HammerResult.premises")

        for translation in self.translations:
            if not isinstance(translation, TranslationRecord):
                raise ValueError(
                    "HammerResult.translations must contain TranslationRecord"
                )
            translation.validate()
        _validate_unique_ids(
            self.translations, attr="translation_id", owner="HammerResult.translations"
        )

        for attempt in self.solver_attempts:
            if not isinstance(attempt, SolverAttemptRecord):
                raise ValueError(
                    "HammerResult.solver_attempts must contain SolverAttemptRecord"
                )
            attempt.validate()
        _validate_unique_ids(
            self.solver_attempts, attr="attempt_id", owner="HammerResult.solver_attempts"
        )

        if self.proof_candidate is not None:
            if not isinstance(self.proof_candidate, ProofCandidateRecord):
                raise ValueError(
                    "HammerResult.proof_candidate must be a ProofCandidateRecord"
                )
            self.proof_candidate.validate()

        if self.reconstruction is not None:
            if not isinstance(self.reconstruction, ReconstructionRecord):
                raise ValueError(
                    "HammerResult.reconstruction must be a ReconstructionRecord"
                )
            self.reconstruction.validate()

        if (
            self.completed_at is not None
            and self.created_at is not None
            and self.completed_at < self.created_at
        ):
            raise ValueError("HammerResult.completed_at must not precede created_at")

        self._validate_status_invariants()

    def _validate_status_invariants(self) -> None:
        status = self.status

        # --- The core trust-boundary invariant -----------------------------------
        # VERIFIED requires a successful kernel reconstruction, and a successful
        # kernel reconstruction requires the status to be VERIFIED. Neither side
        # may exist without the other.
        reconstruction_accepted = (
            self.reconstruction is not None and self.reconstruction.kernel_accepted
        )
        if status is HammerResultStatus.VERIFIED:
            if self.reconstruction is None:
                raise ValueError(
                    "HammerResult.status is VERIFIED but reconstruction is None: "
                    "only a successful kernel check may create a verified result"
                )
            if not self.reconstruction.kernel_accepted:
                raise ValueError(
                    "HammerResult.status is VERIFIED but "
                    "reconstruction.kernel_accepted is False"
                )
            if self.proof_candidate is None:
                raise ValueError(
                    "HammerResult.status is VERIFIED but proof_candidate is None"
                )
            if self.reconstruction.candidate_id != self.proof_candidate.candidate_id:
                raise ValueError(
                    "HammerResult.reconstruction.candidate_id must match "
                    "proof_candidate.candidate_id when status is VERIFIED"
                )
            if self.environment_lock is None:
                raise ValueError(
                    "HammerResult.status is VERIFIED but environment_lock is None"
                )
            if self.reconstruction.environment_lock_id != self.environment_lock.lock_id:
                raise ValueError(
                    "HammerResult.reconstruction.environment_lock_id must match "
                    "environment_lock.lock_id when status is VERIFIED"
                )
        elif reconstruction_accepted:
            # A reconstruction was accepted by the kernel but the status does not
            # say VERIFIED — this would silently downgrade a checked theorem.
            raise ValueError(
                "HammerResult.reconstruction.kernel_accepted is True but "
                f"status is {status.value!r}, not VERIFIED"
            )

        if status is HammerResultStatus.CANDIDATE:
            if self.proof_candidate is None:
                raise ValueError(
                    "HammerResult.status is CANDIDATE but proof_candidate is None"
                )

        elif status in (HammerResultStatus.COUNTEREXAMPLE, HammerResultStatus.TIMEOUT):
            if not self.solver_attempts:
                raise ValueError(
                    f"HammerResult.status is {status.value!r} but "
                    "solver_attempts is empty"
                )

        elif status is HammerResultStatus.UNSUPPORTED_TRANSLATION:
            if not any(
                t.status is TranslationStatus.UNSUPPORTED for t in self.translations
            ):
                raise ValueError(
                    "HammerResult.status is UNSUPPORTED_TRANSLATION but no "
                    "translation record has status UNSUPPORTED"
                )

        if status in _PRE_EXECUTION_STATUSES:
            if self.solver_attempts:
                raise ValueError(
                    f"HammerResult.status is {status.value!r} but solver_attempts "
                    "is non-empty (nothing should have executed)"
                )
            if self.proof_candidate is not None:
                raise ValueError(
                    f"HammerResult.status is {status.value!r} but proof_candidate "
                    "is set (nothing should have executed)"
                )
            if self.reconstruction is not None:
                raise ValueError(
                    f"HammerResult.status is {status.value!r} but reconstruction "
                    "is set (nothing should have executed)"
                )

        if status is HammerResultStatus.POLICY_DENIED and not self.errors:
            raise ValueError(
                "HammerResult.status is POLICY_DENIED but errors is empty; "
                "record why the policy denied the run"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain, JSON-compatible dictionary."""

        return {
            "schema_version": self.schema_version,
            "result_id": self.result_id,
            "request": self.request.to_dict(),
            "status": self.status.value,
            "corpus_revision": self.corpus_revision,
            "environment_lock": (
                self.environment_lock.to_dict() if self.environment_lock else None
            ),
            "premises": [p.to_dict() for p in self.premises],
            "translations": [t.to_dict() for t in self.translations],
            "solver_attempts": [a.to_dict() for a in self.solver_attempts],
            "proof_candidate": (
                self.proof_candidate.to_dict() if self.proof_candidate else None
            ),
            "reconstruction": (
                self.reconstruction.to_dict() if self.reconstruction else None
            ),
            "created_at": _isoformat(self.created_at),
            "completed_at": _isoformat(self.completed_at),
            "notes": list(self.notes),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HammerResult":
        """Deserialize from a plain dictionary produced by :meth:`to_dict`."""

        data = dict(data)
        data["request"] = HammerRequest.from_dict(data["request"])
        data["status"] = HammerResultStatus(data["status"])
        if data.get("environment_lock"):
            data["environment_lock"] = EnvironmentLockRecord.from_dict(
                data["environment_lock"]
            )
        else:
            data["environment_lock"] = None
        data["premises"] = [PremiseRecord.from_dict(p) for p in data.get("premises", [])]
        data["translations"] = [
            TranslationRecord.from_dict(t) for t in data.get("translations", [])
        ]
        data["solver_attempts"] = [
            SolverAttemptRecord.from_dict(a) for a in data.get("solver_attempts", [])
        ]
        if data.get("proof_candidate"):
            data["proof_candidate"] = ProofCandidateRecord.from_dict(
                data["proof_candidate"]
            )
        else:
            data["proof_candidate"] = None
        if data.get("reconstruction"):
            data["reconstruction"] = ReconstructionRecord.from_dict(
                data["reconstruction"]
            )
        else:
            data["reconstruction"] = None
        if "created_at" in data:
            data["created_at"] = _parse_datetime(data["created_at"])
        if "completed_at" in data:
            data["completed_at"] = _parse_datetime(data["completed_at"])
        return cls(**data)

    def is_verified(self) -> bool:
        """Return whether this result asserts a kernel-checked theorem."""

        return self.status is HammerResultStatus.VERIFIED


def _validate_unique_ids(records: List[Any], *, attr: str, owner: str) -> None:
    seen: set = set()
    for record in records:
        value = getattr(record, attr)
        if value in seen:
            raise ValueError(f"{owner} contains duplicate {attr}={value!r}")
        seen.add(value)


__all__ = [
    "SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "ITPKind",
    "TranslationTarget",
    "TranslationStatus",
    "SolverVerdict",
    "HammerResultStatus",
    "HammerPolicy",
    "EnvironmentLockRecord",
    "HammerRequest",
    "PremiseRecord",
    "TranslationRecord",
    "SolverAttemptRecord",
    "ProofCandidateRecord",
    "ReconstructionRecord",
    "HammerResult",
]
