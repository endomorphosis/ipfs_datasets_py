"""Common native ITP frontend adapter protocol and goal-snapshot records.

This module implements the shared contract described in the ``## HAMMER-006``
entry of ``docs/logic/itp_hammer_taskboard.todo.md``: *"Define a common
adapter protocol that captures the exact goal, local hypotheses, imports,
universe/type context, source position, target ITP version, and native
command needed for reconstruction. Each unavailable frontend returns
structured capability evidence; no adapter fabricates a native goal from
plain text."*

Building blocks
----------------
- :class:`SourcePosition` — a file/line/column anchor into the *original*
  native source a goal was captured from.
- :class:`LocalHypothesis` — one local hypothesis line as pretty-printed by
  the target ITP's own kernel/elaborator (never synthesized by this code).
- :class:`UniverseContext` — universe parameters and ``Type``/``Sort``
  bindings actually observed in the native goal/hypothesis text.
- :class:`GoalSnapshot` — the full, versioned native goal-state capture: the
  exact goal, local hypotheses, imports, universe/type context, source
  position, target ITP version, and the native command needed to reconstruct
  or independently re-check the surrounding proof.
- :class:`CapabilityEvidence` — a structured, machine-readable record of
  whether a frontend's native tooling is available in this environment, and
  exactly what evidence backs that determination (mirrors the
  ``SurfaceReport``/``CapabilityNote`` shape used by the HAMMER-002 probe).
- :class:`ITPFrontend` — the :class:`typing.Protocol` every concrete frontend
  (:mod:`.lean`, :mod:`.coq`, :mod:`.isabelle`) implements.

Non-fabrication invariant
--------------------------
A :class:`GoalSnapshot` may only be constructed from ``raw_native_output``
text that a real invocation of the target ITP's own executable actually
produced (e.g. Lean's ``don't know how to synthesize placeholder`` /
``context:`` diagnostic, or Coq/Rocq's ``Show.`` goal display). Every
concrete frontend enforces this by:

1. Refusing to run at all when :meth:`ITPFrontend.capability` reports the
   frontend unavailable (raising :class:`FrontendUnavailableError` with the
   :class:`CapabilityEvidence` attached — never guessing).
2. Requiring the caller's *native* source text to already contain a genuine
   incomplete-proof marker (Lean/Coq ``sorry``, Coq ``admit.``/``Admitted.``)
   rather than accepting a plain-text goal description as sufficient input.
3. Parsing the goal/hypotheses/imports/universe context strictly out of the
   ITP's own diagnostic output, never out of the caller-supplied
   ``goal_statement`` string used elsewhere in the pipeline for display only
   (see :class:`ipfs_datasets_py.logic.hammers.models.HammerRequest`).
4. Raising :class:`GoalCaptureError` — never silently degrading to a
   fabricated snapshot — whenever the native invocation fails, times out, or
   produces output that cannot be parsed into a genuine goal state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from ..models import (
    SCHEMA_VERSION,
    ITPKind,
    _isoformat,
    _parse_datetime,
    _require_nonempty_str,
    _require_schema_version,
    _utcnow,
)
from ..process_lifecycle import ProcessKind, ProcessLimits, get_process_supervisor

__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_TIMEOUT_SECONDS",
    "BoundedProcessResult",
    "run_bounded_process",
    "SourcePosition",
    "LocalHypothesis",
    "UniverseContext",
    "GoalSnapshot",
    "CapabilityEvidence",
    "FrontendUnavailableError",
    "GoalCaptureError",
    "ITPFrontend",
]

#: Default wall-clock budget (seconds) for a single native frontend
#: subprocess invocation. Concrete frontends accept an override at
#: construction time; nothing hard-codes a different value at call sites.
DEFAULT_TIMEOUT_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Bounded subprocess execution
# ---------------------------------------------------------------------------


@dataclass
class BoundedProcessResult:
    """Outcome of a single bounded, non-shell subprocess invocation.

    Every native frontend invokes its target ITP through this helper so that
    every call site shares the same bounded-timeout, no-shell-interpolation,
    and structured-error behavior.
    """

    command: List[str]
    returncode: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def run_bounded_process(
    command: List[str],
    *,
    timeout: float,
    cwd: Optional[str] = None,
) -> BoundedProcessResult:
    """Run ``command`` (a literal argv list — never a shell string) with a
    bounded wall-clock ``timeout``. Never raises; failures are reported as a
    populated :attr:`BoundedProcessResult.error`/``timed_out``."""

    if not command or not isinstance(command, list):
        return BoundedProcessResult(command=list(command or []), error="empty command")
    executable = command[0].rsplit("/", 1)[-1].lower()
    if executable == "lean":
        kind = ProcessKind.LEAN
    elif executable == "lake":
        kind = ProcessKind.LAKE
    else:
        kind = ProcessKind.OTHER
    completed = get_process_supervisor().run(
        command,
        kind=kind,
        limits=ProcessLimits(wall_time_seconds=max(0.001, float(timeout))),
        cwd=cwd,
    )
    error = completed.error
    if completed.timed_out:
        error = f"timed out after {timeout}s"
    return BoundedProcessResult(
        command=list(command),
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        timed_out=completed.timed_out,
        error=error,
    )


# ---------------------------------------------------------------------------
# Source position
# ---------------------------------------------------------------------------


@dataclass
class SourcePosition:
    """An anchor into the *original* (uninstrumented) native source a goal
    snapshot was captured from.

    Attributes:
        file: Path or logical name of the native source file.
        line: 1-indexed line number of the captured goal marker.
        column: 0-indexed column number of the captured goal marker.
        end_line: Optional 1-indexed end line of the marker span.
        end_column: Optional 0-indexed end column of the marker span.
    """

    file: str = ""
    line: int = 1
    column: int = 0
    end_line: Optional[int] = None
    end_column: Optional[int] = None

    def validate(self) -> None:
        _require_nonempty_str(self.file, field_name="file", owner="SourcePosition")
        if self.line < 1:
            raise ValueError("SourcePosition.line must be >= 1")
        if self.column < 0:
            raise ValueError("SourcePosition.column must be >= 0")
        if self.end_line is not None and self.end_line < self.line:
            raise ValueError("SourcePosition.end_line must be >= line")
        if self.end_column is not None and self.end_column < 0:
            raise ValueError("SourcePosition.end_column must be >= 0")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SourcePosition":
        return cls(**dict(data))


# ---------------------------------------------------------------------------
# Local hypothesis
# ---------------------------------------------------------------------------


@dataclass
class LocalHypothesis:
    """One local hypothesis exactly as pretty-printed by the target ITP.

    Attributes:
        names: One or more binder names sharing ``type_text`` (e.g.
            ``["n", "m"]`` for a native ``n m : Nat`` context line).
        type_text: The exact, native pretty-printed type/proposition text.
        raw: The untouched native context line this hypothesis was parsed
            from — kept for audit so a reviewer can verify ``names`` and
            ``type_text`` were not embellished beyond what the ITP printed.
    """

    names: List[str] = field(default_factory=list)
    type_text: str = ""
    raw: str = ""

    def validate(self) -> None:
        if not isinstance(self.names, list) or not self.names or not all(
            isinstance(n, str) and n.strip() for n in self.names
        ):
            raise ValueError(
                "LocalHypothesis.names must be a non-empty list of non-empty strings"
            )
        _require_nonempty_str(self.type_text, field_name="type_text", owner="LocalHypothesis")
        _require_nonempty_str(self.raw, field_name="raw", owner="LocalHypothesis")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocalHypothesis":
        return cls(**dict(data))


# ---------------------------------------------------------------------------
# Universe / type context
# ---------------------------------------------------------------------------


@dataclass
class UniverseContext:
    """Universe/type parameters actually observed in a captured goal.

    Attributes:
        parameters: Universe parameter names declared on the theorem's own
            signature (e.g. ``["u", "v"]`` parsed from a native ``.{u,v}``
            binder) or, for Coq/Rocq, opaque universe tokens Coq itself
            assigned (e.g. ``["Top.21"]`` from a ``Type@{Top.21}`` display
            enabled by ``Set Printing Universes.``).
        type_bindings: Mapping of a hypothesis/binder name to the exact
            native ``Type``/``Sort`` (or ``Type@{...}``) text it was bound
            at, drawn directly from parsed hypotheses — never invented.
        notes: Human-readable note, always populated (including the
            "no explicit universe parameters observed" case) so an absent
            universe context is explicit rather than silently omitted.
    """

    parameters: List[str] = field(default_factory=list)
    type_bindings: Dict[str, str] = field(default_factory=dict)
    notes: str = ""

    def validate(self) -> None:
        if not isinstance(self.parameters, list) or not all(
            isinstance(p, str) and p.strip() for p in self.parameters
        ):
            raise ValueError("UniverseContext.parameters must be a list of non-empty strings")
        if not isinstance(self.type_bindings, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in self.type_bindings.items()
        ):
            raise ValueError("UniverseContext.type_bindings must map str -> str")
        if not isinstance(self.notes, str):
            raise ValueError("UniverseContext.notes must be a string")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UniverseContext":
        return cls(**dict(data))


# ---------------------------------------------------------------------------
# Goal snapshot
# ---------------------------------------------------------------------------


@dataclass
class GoalSnapshot:
    """A versioned, native goal-state capture produced by an
    :class:`ITPFrontend`.

    Attributes:
        schema_version: Schema version of this record.
        itp: Source ITP this snapshot was captured from.
        itp_version: Exact target ITP version string (e.g. ``"Lean (version
            4.31.0, ...)"``) resolved at capture time — never a floating
            "latest" label.
        theorem_id: Identifier of the theorem/declaration snapshotted.
        goal_text: The exact native pretty-printed goal statement (the text
            following Lean's ``⊢``, Coq's ``====...====`` separator, or
            Isabelle's ``goal (1 subgoal):`` marker).
        hypotheses: Local hypotheses in native display order.
        imports: Import/require statements parsed from the *original* native
            source (Lean ``import X``, Coq ``Require Import X.``/``From X
            Require Import Y.``, Isabelle ``imports X``).
        universe_context: Universe/type parameters observed in the capture.
        source_position: Anchor into the original native source.
        native_command: Exact argv needed to reconstruct/independently
            re-check the surrounding proof (e.g.
            ``["lean", "/path/Goal.lean"]``) — a template with concrete
            values filled in, never a fabricated example command.
        raw_native_output: The untouched diagnostic text the target ITP's
            own executable produced and that every other field above was
            parsed from. Required and non-empty — this is the evidence that
            backs the non-fabrication invariant.
        captured_at: When this snapshot was captured.
        extra: Free-form, non-authoritative additional evidence (e.g. the
            resolved executable path, other diagnostic messages emitted in
            the same invocation). Must not carry data required for
            correctness of the fields above.
    """

    schema_version: str = SCHEMA_VERSION
    itp: ITPKind = ITPKind.LEAN
    itp_version: str = ""
    theorem_id: str = ""
    goal_text: str = ""
    hypotheses: List[LocalHypothesis] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    universe_context: UniverseContext = field(default_factory=UniverseContext)
    source_position: SourcePosition = field(default_factory=SourcePosition)
    native_command: List[str] = field(default_factory=list)
    raw_native_output: str = ""
    captured_at: datetime = field(default_factory=_utcnow)
    extra: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="GoalSnapshot")
        if not isinstance(self.itp, ITPKind):
            raise ValueError("GoalSnapshot.itp must be an ITPKind")
        _require_nonempty_str(self.itp_version, field_name="itp_version", owner="GoalSnapshot")
        _require_nonempty_str(self.theorem_id, field_name="theorem_id", owner="GoalSnapshot")
        _require_nonempty_str(self.goal_text, field_name="goal_text", owner="GoalSnapshot")
        if not isinstance(self.hypotheses, list):
            raise ValueError("GoalSnapshot.hypotheses must be a list")
        for hyp in self.hypotheses:
            if not isinstance(hyp, LocalHypothesis):
                raise ValueError(
                    "GoalSnapshot.hypotheses entries must be LocalHypothesis instances"
                )
            hyp.validate()
        if not isinstance(self.imports, list) or not all(
            isinstance(i, str) and i.strip() for i in self.imports
        ):
            raise ValueError("GoalSnapshot.imports must be a list of non-empty strings")
        if not isinstance(self.universe_context, UniverseContext):
            raise ValueError("GoalSnapshot.universe_context must be a UniverseContext")
        self.universe_context.validate()
        if not isinstance(self.source_position, SourcePosition):
            raise ValueError("GoalSnapshot.source_position must be a SourcePosition")
        self.source_position.validate()
        if not isinstance(self.native_command, list) or not self.native_command or not all(
            isinstance(c, str) and c.strip() for c in self.native_command
        ):
            raise ValueError(
                "GoalSnapshot.native_command must be a non-empty list of non-empty strings"
            )
        _require_nonempty_str(
            self.raw_native_output, field_name="raw_native_output", owner="GoalSnapshot"
        )
        if not isinstance(self.extra, dict):
            raise ValueError("GoalSnapshot.extra must be a dict")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "itp": self.itp.value,
            "itp_version": self.itp_version,
            "theorem_id": self.theorem_id,
            "goal_text": self.goal_text,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "imports": list(self.imports),
            "universe_context": self.universe_context.to_dict(),
            "source_position": self.source_position.to_dict(),
            "native_command": list(self.native_command),
            "raw_native_output": self.raw_native_output,
            "captured_at": _isoformat(self.captured_at),
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GoalSnapshot":
        data = dict(data)
        if isinstance(data.get("itp"), str):
            data["itp"] = ITPKind(data["itp"])
        if isinstance(data.get("hypotheses"), list):
            data["hypotheses"] = [
                h if isinstance(h, LocalHypothesis) else LocalHypothesis.from_dict(h)
                for h in data["hypotheses"]
            ]
        if isinstance(data.get("universe_context"), dict):
            data["universe_context"] = UniverseContext.from_dict(data["universe_context"])
        if isinstance(data.get("source_position"), dict):
            data["source_position"] = SourcePosition.from_dict(data["source_position"])
        if "captured_at" in data:
            data["captured_at"] = _parse_datetime(data["captured_at"])
        return cls(**data)


# ---------------------------------------------------------------------------
# Capability evidence
# ---------------------------------------------------------------------------


@dataclass
class CapabilityEvidence:
    """Structured, machine-readable evidence for whether a frontend's native
    tooling is available in this environment right now.

    Mirrors the ``SurfaceReport``/``CapabilityNote`` shape produced by
    ``scripts/ops/logic/probe_itp_hammer_environment.py`` (HAMMER-002) so the
    two capability surfaces stay consistent, without importing that
    standalone script (which is intentionally import-free).

    Attributes:
        schema_version: Schema version of this record.
        itp: The ITP this evidence describes.
        available: Whether the frontend can actually snapshot a goal right
            now (executable found; nothing more is claimed).
        executables: Mapping of executable name -> discovery evidence
            (``found``, ``path``, ``version``, ``version_probe_error``).
        unavailable_reason: Machine-readable reason, required (non-empty)
            when ``available`` is ``False`` and forbidden when ``True``.
        checked_at: When this evidence was gathered.
        notes: Free-form human-readable context.
    """

    schema_version: str = SCHEMA_VERSION
    itp: ITPKind = ITPKind.LEAN
    available: bool = False
    executables: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    unavailable_reason: Optional[str] = None
    checked_at: datetime = field(default_factory=_utcnow)
    notes: str = ""

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="CapabilityEvidence")
        if not isinstance(self.itp, ITPKind):
            raise ValueError("CapabilityEvidence.itp must be an ITPKind")
        if not isinstance(self.available, bool):
            raise ValueError("CapabilityEvidence.available must be a boolean")
        if not isinstance(self.executables, dict):
            raise ValueError("CapabilityEvidence.executables must be a dict")
        if self.available:
            if self.unavailable_reason is not None:
                raise ValueError(
                    "CapabilityEvidence.unavailable_reason must be None when available is True"
                )
        else:
            _require_nonempty_str(
                self.unavailable_reason,
                field_name="unavailable_reason",
                owner="CapabilityEvidence",
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "itp": self.itp.value,
            "available": self.available,
            "executables": self.executables,
            "unavailable_reason": self.unavailable_reason,
            "checked_at": _isoformat(self.checked_at),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapabilityEvidence":
        data = dict(data)
        if isinstance(data.get("itp"), str):
            data["itp"] = ITPKind(data["itp"])
        if "checked_at" in data:
            data["checked_at"] = _parse_datetime(data["checked_at"])
        return cls(**data)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FrontendUnavailableError(RuntimeError):
    """Raised when a frontend's native tooling is not available.

    Always carries the :class:`CapabilityEvidence` that backs the refusal so
    a caller never has to guess *why* a snapshot could not be produced.
    """

    def __init__(self, message: str, *, capability: CapabilityEvidence):
        super().__init__(message)
        self.capability = capability


class GoalCaptureError(RuntimeError):
    """Raised when a native invocation fails, times out, or produces output
    that cannot be parsed into a genuine goal state.

    This is the explicit failure mode the non-fabrication invariant relies
    on: a frontend must raise this rather than ever falling back to a
    plain-text stand-in for the goal.
    """


# ---------------------------------------------------------------------------
# Adapter protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ITPFrontend(Protocol):
    """Common protocol every native ITP frontend adapter implements.

    Attributes:
        itp: The :class:`ITPKind` this frontend targets.
    """

    itp: ITPKind

    def capability(self) -> CapabilityEvidence:
        """Return structured evidence for whether this frontend's native
        tooling is available in this environment right now. Must never run
        a proof search and must never raise for the "not available" case —
        that is a normal, expected, structured outcome."""

        ...

    def snapshot_goal(
        self,
        source: str,
        *,
        theorem_id: str,
        file_name: str = "Goal",
        timeout: Optional[float] = None,
    ) -> GoalSnapshot:
        """Capture a native :class:`GoalSnapshot` for the incomplete goal
        found in ``source``.

        Args:
            source: The *native* source text (Lean/Coq/Isabelle) containing
                exactly the imports, declaration, and an explicit
                incomplete-proof marker (``sorry``/``admit.``/``Admitted.``)
                whose goal state should be captured. Plain-text goal
                descriptions are not accepted input — the native ITP must
                genuinely elaborate this source for a snapshot to exist.
            theorem_id: Stable identifier for the declaration being
                snapshotted.
            file_name: Logical file name recorded in the resulting
                :class:`SourcePosition` (a temporary file is used for the
                actual invocation; this name is cosmetic/traceable only).
            timeout: Optional override of the bounded wall-clock budget for
                the underlying native invocation.

        Raises:
            FrontendUnavailableError: If :meth:`capability` reports this
                frontend unavailable.
            GoalCaptureError: If the native invocation fails, times out, or
                its output cannot be parsed into a genuine goal state.
        """

        ...
