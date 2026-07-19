"""Policy-controlled parallel ATP/SMT portfolio execution (HAMMER-008).

This module implements the ``## HAMMER-008`` entry of
``docs/logic/itp_hammer_taskboard.todo.md``: *"Execute an allowlisted
Z3/CVC5/Vampire/E portfolio with independent time, memory, process-count,
and cancellation budgets. Capture command version, input digest,
stdout/stderr digest, exit status, timeout, and solver trace. Never
interpolate user content into a shell command or expose a solver result as
verified."*

Pipeline
---------
1. :func:`build_solver_input_text` turns one
   :class:`~.models.TranslationRecord` (produced by the HAMMER-007
   translation pipeline) into the literal solver input text — the TPTP
   renderer already emits a complete ``.p`` problem, while the SMT-LIB
   renderer emits declarations plus a single ``assert`` that still needs the
   fixed, content-independent ``(check-sat)``/``(exit)`` driver commands
   appended.
2. :class:`SolverPortfolio` partitions the requested (translation, solver)
   pairs into policy-permitted and policy-denied attempts via
   :class:`~.policy.PortfolioPolicy`, writes each permitted attempt's input
   text to its own temporary file, and runs every permitted attempt through
   :func:`run_bounded_solver_process` under a
   :class:`concurrent.futures.ThreadPoolExecutor` bounded by
   ``policy.max_parallel_processes`` (the process-count budget).
3. Each attempt's raw process outcome is parsed into an untrusted
   :class:`~.models.SolverVerdict` (never a "proved"/"verified" claim beyond
   what the raw solver output actually said) and recorded as a
   :class:`~.models.SolverAttemptRecord`, alongside an out-of-band
   :class:`SolverAttemptEvidence` record carrying the exact argv, the input
   digest, the raw stdout/stderr text the record's ``raw_output_digest``
   refers to, and a short solver-trace excerpt.
4. When ``policy.cancel_on_first_conclusive`` is set (the default), the
   moment any attempt reaches a conclusive verdict (``sat``/``unsat``/
   ``proved``/``disproved``) every other still-running attempt's process
   group is killed (the cancellation budget) — a cancelled attempt is
   still recorded (verdict ``unknown``, never fabricated as conclusive),
   never silently dropped.

Trust boundary
---------------
Nothing produced by this module is, or can be mistaken for, a verified
theorem: :class:`~.models.SolverAttemptRecord` and :class:`PortfolioRunResult`
carry no "verified"/"kernel_accepted" field at all. Per the HAMMER-001
contract (:mod:`.models`), only a :class:`~.models.ReconstructionRecord`
with ``kernel_accepted=True`` — produced by a later, independent ITP kernel
check — may promote a run to ``HammerResultStatus.VERIFIED``.

Security invariant
--------------------
Every subprocess this module runs is invoked via ``subprocess.Popen`` with a
literal ``argv`` list and ``shell=False`` (the implicit default); no
translated theorem text, premise text, or any other caller-supplied content
is ever formatted into a command string. Content only ever reaches a
solver by being written to a temporary file whose *path* (never its
contents) appears in ``argv``.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from tempfile import TemporaryDirectory
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .corpus import compute_content_digest
from .models import (
    SCHEMA_VERSION,
    SolverAttemptRecord,
    SolverVerdict,
    TranslationRecord,
    TranslationStatus,
    TranslationTarget,
    _require_nonempty_str,
    _require_schema_version,
    _utcnow,
)
from .policy import (
    PolicyError,
    PortfolioPolicy,
    SolverBudget,
    build_preexec_fn,
    known_solver_names,
    solver_spec,
)

__all__ = [
    "SCHEMA_VERSION",
    "PolicyError",
    "SolverProcessOutcome",
    "SolverAttemptEvidence",
    "PortfolioAttemptSpec",
    "PortfolioRunResult",
    "build_solver_input_text",
    "parse_smtlib_verdict",
    "parse_tptp_verdict",
    "run_bounded_solver_process",
    "SolverPortfolio",
]

#: Verdicts that count as "conclusive" for the cancellation budget: once any
#: attempt reaches one of these, every other still-running attempt is
#: cancelled when ``PortfolioPolicy.cancel_on_first_conclusive`` is set.
_CONCLUSIVE_VERDICTS = frozenset(
    {SolverVerdict.SAT, SolverVerdict.UNSAT, SolverVerdict.PROVED, SolverVerdict.DISPROVED}
)

#: File suffix used for each translation target's temporary solver-input file.
_SOLVER_INPUT_SUFFIX: Dict[TranslationTarget, str] = {
    TranslationTarget.TPTP: ".p",
    TranslationTarget.SMTLIB: ".smt2",
}

#: How often (seconds) the bounded process runner polls for the wall-clock
#: deadline or an external cancellation request while a solver subprocess is
#: still running.
_POLL_INTERVAL_SECONDS = 0.05

#: Bounded timeout (seconds) for the ``--version`` metadata probe run once
#: per resolved executable.
_VERSION_PROBE_TIMEOUT_SECONDS = 5.0


# ---------------------------------------------------------------------------
# Solver input assembly
# ---------------------------------------------------------------------------


def build_solver_input_text(translation: TranslationRecord) -> str:
    """Build the literal solver-input text for ``translation``.

    ``TranslationRecord.translated_text`` (HAMMER-007) is a *fragment*, not
    a runnable solver script: the TPTP renderer emits type declarations plus
    a single ``tff(goal, conjecture, ...)`` clause — already a complete
    ``.p`` problem file that Vampire/E consume as-is — while the SMT-LIB
    renderer emits ``declare-sort``/``declare-fun`` plus a single ``assert``,
    missing the trailing ``check-sat``/``exit`` commands Z3/CVC5 need to
    actually run a check and terminate. This function only appends those
    fixed, content-independent SMT-LIB driver commands; it never edits,
    negates, or otherwise derives new logical content from
    ``translated_text``.

    Raises:
        ValueError: If ``translation.status`` is
            :attr:`~.models.TranslationStatus.UNSUPPORTED` (nothing to run)
            or ``translated_text`` is ``None``.
    """

    if translation.status is TranslationStatus.UNSUPPORTED:
        raise ValueError(
            f"translation {translation.translation_id!r} is UNSUPPORTED "
            f"({translation.unsupported_reason!r}); there is no solver input to build"
        )
    if translation.translated_text is None:
        raise ValueError(
            f"translation {translation.translation_id!r} has no translated_text"
        )

    text = translation.translated_text
    if translation.target is TranslationTarget.SMTLIB:
        text = f"{text}\n(check-sat)\n(exit)\n"
    return text


def _input_filename(attempt_id: str, suffix: str) -> str:
    """Derive a filesystem-safe temporary filename from ``attempt_id``.

    ``attempt_id`` is built from caller-supplied ``request_id``/
    ``translation_id`` strings that may contain characters unsafe for a
    filename (path separators, etc.); hashing sidesteps that entirely
    rather than trying to sanitize arbitrary caller text.
    """

    digest = hashlib.sha256(attempt_id.encode("utf-8")).hexdigest()[:32]
    return f"{digest}{suffix}"


# ---------------------------------------------------------------------------
# Verdict parsing
#
# These parsers only ever report what the solver's own output literally
# said (a raw SolverVerdict) — they never upgrade a result to "verified".
# ---------------------------------------------------------------------------

_SZS_STATUS_RE = re.compile(r"SZS status (\w+)")

_SZS_STATUS_TO_VERDICT: Dict[str, SolverVerdict] = {
    "Theorem": SolverVerdict.PROVED,
    "Unsatisfiable": SolverVerdict.PROVED,
    "ContradictoryAxioms": SolverVerdict.PROVED,
    "CounterSatisfiable": SolverVerdict.DISPROVED,
    "Satisfiable": SolverVerdict.SAT,
    "Timeout": SolverVerdict.TIMEOUT,
    "ResourceOut": SolverVerdict.TIMEOUT,
    "GaveUp": SolverVerdict.UNKNOWN,
    "Unknown": SolverVerdict.UNKNOWN,
    "Error": SolverVerdict.ERROR,
    "InputError": SolverVerdict.ERROR,
    "OSError": SolverVerdict.ERROR,
}


def parse_tptp_verdict(stdout: str, stderr: str) -> Tuple[SolverVerdict, Optional[str]]:
    """Parse a Vampire/E TPTP/TSTP-style ``stdout``/``stderr`` pair into a
    raw :class:`~.models.SolverVerdict` plus a short trace excerpt.

    Prefers the standard SZS ontology's ``SZS status <Token>`` line (emitted
    by both Vampire and E); falls back to plain-text heuristics only when no
    SZS line is present.
    """

    match = _SZS_STATUS_RE.search(stdout) or _SZS_STATUS_RE.search(stderr)
    if match:
        token = match.group(1)
        return _SZS_STATUS_TO_VERDICT.get(token, SolverVerdict.UNKNOWN), match.group(0)

    lowered = stdout.lower()
    if "refutation found" in lowered:
        return SolverVerdict.PROVED, "refutation found"
    if "time limit reached" in lowered or "time out" in lowered or "timeout" in lowered:
        return SolverVerdict.TIMEOUT, None
    if "satisfiable" in lowered:
        return SolverVerdict.SAT, None
    return SolverVerdict.UNKNOWN, None


_SMTLIB_TOKEN_RE = re.compile(r"^(sat|unsat|unknown)\b", re.MULTILINE)

_SMTLIB_TOKEN_TO_VERDICT: Dict[str, SolverVerdict] = {
    "sat": SolverVerdict.SAT,
    "unsat": SolverVerdict.UNSAT,
    "unknown": SolverVerdict.UNKNOWN,
}


def parse_smtlib_verdict(stdout: str, stderr: str) -> Tuple[SolverVerdict, Optional[str]]:
    """Parse a Z3/CVC5-style SMT-LIB ``stdout`` response into a raw
    :class:`~.models.SolverVerdict` plus a short trace excerpt.

    Looks for the literal ``sat``/``unsat``/``unknown`` response token a
    conforming SMT-LIB solver prints in reply to ``(check-sat)``. Anything
    else (a parse error, an unexpected error message, empty output) is
    reported as :attr:`~.models.SolverVerdict.ERROR` rather than guessed at.
    """

    match = _SMTLIB_TOKEN_RE.search(stdout.strip())
    if match:
        token = match.group(1)
        return _SMTLIB_TOKEN_TO_VERDICT[token], match.group(0)
    return SolverVerdict.ERROR, None


_VERDICT_PARSERS: Dict[
    TranslationTarget, Callable[[str, str], Tuple[SolverVerdict, Optional[str]]]
] = {
    TranslationTarget.TPTP: parse_tptp_verdict,
    TranslationTarget.SMTLIB: parse_smtlib_verdict,
}


# ---------------------------------------------------------------------------
# Bounded, cancellable subprocess execution
# ---------------------------------------------------------------------------


@dataclass
class SolverProcessOutcome:
    """Raw, untrusted outcome of one bounded solver subprocess invocation."""

    command: List[str]
    returncode: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    cancelled: bool = False
    wall_time_seconds: float = 0.0
    cpu_seconds: Optional[float] = None
    max_rss_mb: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _kill_process_group(process: "subprocess.Popen[str]") -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except OSError:
            pass


def run_bounded_solver_process(
    command: List[str],
    *,
    budget: SolverBudget,
    cancel_event: Optional[threading.Event] = None,
    cwd: Optional[str] = None,
) -> SolverProcessOutcome:
    """Run ``command`` (a literal argv list — never a shell string) under
    ``budget``'s wall-clock deadline, killing the whole process group the
    moment either the deadline passes or ``cancel_event`` is set. Never
    raises; every failure mode is reported via the returned
    :class:`SolverProcessOutcome`.
    """

    if not command or not isinstance(command, list):
        return SolverProcessOutcome(command=list(command or []), error="empty command")

    if cancel_event is not None and cancel_event.is_set():
        # Already cancelled before this attempt even got a chance to start —
        # never spawn a subprocess we know we will immediately kill.
        return SolverProcessOutcome(command=list(command), cancelled=True)

    preexec_fn = build_preexec_fn(budget)
    start_rusage = None
    if os.name == "posix":
        import resource

        start_rusage = resource.getrusage(resource.RUSAGE_CHILDREN)

    start = time.monotonic()
    popen_kwargs: Dict[str, Any] = dict(
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
    )
    if preexec_fn is not None:
        popen_kwargs["preexec_fn"] = preexec_fn

    try:
        process = subprocess.Popen(command, **popen_kwargs)
    except OSError as exc:
        return SolverProcessOutcome(
            command=list(command),
            wall_time_seconds=time.monotonic() - start,
            error=str(exc),
        )

    timed_out = False
    cancelled = False
    stdout = ""
    stderr = ""
    deadline = start + float(budget.timeout_seconds)

    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                _kill_process_group(process)
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    stdout, stderr = "", ""
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                _kill_process_group(process)
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    stdout, stderr = "", ""
                break
            try:
                stdout, stderr = process.communicate(
                    timeout=min(_POLL_INTERVAL_SECONDS, remaining)
                )
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        returncode = process.poll()

    wall_time = time.monotonic() - start
    cpu_seconds: Optional[float] = None
    max_rss_mb: Optional[float] = None
    if os.name == "posix" and start_rusage is not None:
        import resource

        end_rusage = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_seconds = (end_rusage.ru_utime + end_rusage.ru_stime) - (
            start_rusage.ru_utime + start_rusage.ru_stime
        )
        # ru_maxrss is KiB on Linux, bytes on macOS/BSD.
        rss_delta_raw = max(end_rusage.ru_maxrss - start_rusage.ru_maxrss, 0)
        max_rss_mb = (
            rss_delta_raw / (1024.0 * 1024.0)
            if sys.platform == "darwin"
            else rss_delta_raw / 1024.0
        )

    return SolverProcessOutcome(
        command=list(command),
        returncode=returncode,
        stdout=stdout or "",
        stderr=stderr or "",
        timed_out=timed_out,
        cancelled=cancelled,
        wall_time_seconds=wall_time,
        cpu_seconds=cpu_seconds,
        max_rss_mb=max_rss_mb,
    )


def _probe_solver_version(executable_path: str, spec, *, timeout: float = _VERSION_PROBE_TIMEOUT_SECONDS):
    """Run a single bounded ``--version``-style metadata query against an
    already-resolved executable. Never raises; returns ``None`` on any
    failure."""

    try:
        completed = subprocess.run(
            [executable_path, *spec.version_args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (completed.stdout or completed.stderr or "").strip().splitlines()
    return output[0].strip() if output else None


# ---------------------------------------------------------------------------
# Attempt specs, evidence, and results
# ---------------------------------------------------------------------------


@dataclass
class PortfolioAttemptSpec:
    """One requested (translation, solver) pairing to execute inside a
    portfolio run."""

    translation: TranslationRecord
    solver_name: str


@dataclass
class SolverAttemptEvidence:
    """Out-of-band evidence for one :class:`~.models.SolverAttemptRecord`
    that does not belong on the trust-contract record itself: the exact
    argv actually executed (already free of any shell interpolation by
    construction), a content digest of the exact input text sent to the
    solver, the raw stdout/stderr text that
    :attr:`~.models.SolverAttemptRecord.raw_output_digest` is a digest of,
    and a short solver-trace excerpt (e.g. an SZS status line or an SMT-LIB
    ``sat``/``unsat``/``unknown`` response token).
    """

    attempt_id: str
    command: List[str]
    input_digest: str
    raw_stdout: str
    raw_stderr: str
    solver_trace: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SolverAttemptEvidence":
        return cls(**dict(data))


@dataclass
class PortfolioRunResult:
    """The full outcome of one :meth:`SolverPortfolio.run` call.

    Attributes:
        schema_version: Schema version of this record.
        request_id: Owning ``HammerRequest`` id every attempt in this run
            belongs to.
        attempts: One :class:`~.models.SolverAttemptRecord` per attempt that
            actually executed (denied attempts never appear here).
        evidence: Out-of-band :class:`SolverAttemptEvidence`, keyed by
            ``attempt_id``, for every entry in ``attempts``.
        denied: Requested attempts that never ran because policy denied
            them (unknown/non-allowlisted solver, unresolved executable, a
            translation whose target does not match the solver, or an
            ``UNSUPPORTED`` translation) — each entry is a
            ``{"solver_name", "translation_id", "reason"}`` mapping.
        cancelled_attempt_ids: ``attempt_id``s that were cancelled before
            completing (as opposed to running to a timeout or a genuine
            verdict) because another attempt reached a conclusive verdict
            first.
    """

    schema_version: str = SCHEMA_VERSION
    request_id: str = ""
    attempts: List[SolverAttemptRecord] = field(default_factory=list)
    evidence: Dict[str, SolverAttemptEvidence] = field(default_factory=dict)
    denied: List[Dict[str, str]] = field(default_factory=list)
    cancelled_attempt_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "evidence": {k: v.to_dict() for k, v in self.evidence.items()},
            "denied": [dict(entry) for entry in self.denied],
            "cancelled_attempt_ids": list(self.cancelled_attempt_ids),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PortfolioRunResult":
        data = dict(data)
        _require_schema_version(
            data.get("schema_version", SCHEMA_VERSION), owner="PortfolioRunResult"
        )
        attempts = [
            SolverAttemptRecord.from_dict(entry) for entry in data.get("attempts", [])
        ]
        evidence = {
            k: SolverAttemptEvidence.from_dict(v)
            for k, v in (data.get("evidence") or {}).items()
        }
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            request_id=data.get("request_id", ""),
            attempts=attempts,
            evidence=evidence,
            denied=[dict(entry) for entry in data.get("denied", [])],
            cancelled_attempt_ids=list(data.get("cancelled_attempt_ids", [])),
        )


# ---------------------------------------------------------------------------
# Portfolio executor
# ---------------------------------------------------------------------------

#: One resolved, ready-to-run attempt: the requested spec plus its resolved
#: executable path.
_ResolvedAttempt = Tuple[PortfolioAttemptSpec, str]


class SolverPortfolio:
    """Executes an allowlisted Z3/CVC5/Vampire/E solver portfolio under a
    :class:`~.policy.PortfolioPolicy`.

    ``process_runner`` and ``version_prober`` are injectable purely so tests
    can exercise the full orchestration (parallelism, the process-count
    budget, cancellation) deterministically without needing real solver
    binaries installed; production callers should leave both at their
    defaults.
    """

    def __init__(
        self,
        policy: PortfolioPolicy,
        *,
        process_runner: Callable[
            [List[str]], SolverProcessOutcome
        ] = run_bounded_solver_process,
        version_prober: Callable[[str, Any], Optional[str]] = _probe_solver_version,
    ) -> None:
        policy.validate()
        self.policy = policy
        self._process_runner = process_runner
        self._version_prober = version_prober
        self._version_cache: Dict[str, Optional[str]] = {}
        self._version_cache_lock = threading.Lock()

    def resolve_attempts(
        self, attempts: Sequence[PortfolioAttemptSpec]
    ) -> Tuple[List[_ResolvedAttempt], List[Dict[str, str]]]:
        """Partition ``attempts`` into policy-permitted
        ``(spec, executable_path)`` pairs and policy-denied
        ``{"solver_name", "translation_id", "reason"}`` mappings. Never
        executes anything."""

        permitted: List[_ResolvedAttempt] = []
        denied: List[Dict[str, str]] = []

        for spec in attempts:
            translation_id = spec.translation.translation_id
            if spec.solver_name not in known_solver_names():
                denied.append(
                    {
                        "solver_name": spec.solver_name,
                        "translation_id": translation_id,
                        "reason": (
                            f"{spec.solver_name!r} is not an allowlisted solver "
                            f"family; known families are {known_solver_names()!r}"
                        ),
                    }
                )
                continue

            if spec.translation.status is TranslationStatus.UNSUPPORTED:
                denied.append(
                    {
                        "solver_name": spec.solver_name,
                        "translation_id": translation_id,
                        "reason": (
                            "translation status is UNSUPPORTED "
                            f"({spec.translation.unsupported_reason!r}); nothing "
                            "to execute"
                        ),
                    }
                )
                continue

            expected_target = solver_spec(spec.solver_name).target
            if spec.translation.target is not expected_target:
                denied.append(
                    {
                        "solver_name": spec.solver_name,
                        "translation_id": translation_id,
                        "reason": (
                            f"solver {spec.solver_name!r} expects target "
                            f"{expected_target.value!r} but translation target is "
                            f"{spec.translation.target.value!r}"
                        ),
                    }
                )
                continue

            try:
                executable_path = self.policy.resolve_executable(spec.solver_name)
            except PolicyError as exc:
                denied.append(
                    {
                        "solver_name": spec.solver_name,
                        "translation_id": translation_id,
                        "reason": str(exc),
                    }
                )
                continue

            permitted.append((spec, executable_path))

        return permitted, denied

    def _solver_version(self, executable_path: str, solver_name: str) -> Optional[str]:
        with self._version_cache_lock:
            if executable_path in self._version_cache:
                return self._version_cache[executable_path]
        version = self._version_prober(executable_path, solver_spec(solver_name))
        with self._version_cache_lock:
            self._version_cache[executable_path] = version
        return version

    def run(
        self, request_id: str, attempts: Sequence[PortfolioAttemptSpec]
    ) -> PortfolioRunResult:
        """Execute every policy-permitted entry of ``attempts`` in parallel,
        bounded by ``policy.max_parallel_processes`` concurrently-running
        subprocesses, honoring per-solver time/CPU/memory budgets and the
        portfolio's cancellation-on-first-conclusive-verdict policy.
        """

        _require_nonempty_str(request_id, field_name="request_id", owner="SolverPortfolio.run")

        permitted, denied = self.resolve_attempts(attempts)
        if not permitted:
            return PortfolioRunResult(request_id=request_id, denied=denied)

        cancel_event = threading.Event()
        records: List[SolverAttemptRecord] = []
        evidence: Dict[str, SolverAttemptEvidence] = {}
        cancelled_ids: List[str] = []

        with TemporaryDirectory(prefix="itp_hammer_portfolio_") as tmp_dir:
            work_items = []
            for index, (spec, executable_path) in enumerate(permitted):
                budget = self.policy.budget_for(spec.solver_name)
                attempt_id = (
                    f"{request_id}:{spec.translation.translation_id}:"
                    f"{spec.solver_name}:{index}"
                )
                work_items.append((spec, executable_path, budget, attempt_id, tmp_dir))

            max_workers = max(1, int(self.policy.max_parallel_processes))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(self._run_one, request_id, item, cancel_event)
                    for item in work_items
                ]
                for future in concurrent.futures.as_completed(futures):
                    attempt_id, record, attempt_evidence, was_cancelled = future.result()
                    records.append(record)
                    evidence[attempt_id] = attempt_evidence
                    if was_cancelled:
                        cancelled_ids.append(attempt_id)
                    if (
                        self.policy.cancel_on_first_conclusive
                        and record.verdict in _CONCLUSIVE_VERDICTS
                    ):
                        cancel_event.set()

        records.sort(key=lambda r: r.attempt_id)
        return PortfolioRunResult(
            request_id=request_id,
            attempts=records,
            evidence=evidence,
            denied=denied,
            cancelled_attempt_ids=sorted(cancelled_ids),
        )

    def _run_one(
        self,
        request_id: str,
        item: Tuple[PortfolioAttemptSpec, str, SolverBudget, str, str],
        cancel_event: threading.Event,
    ) -> Tuple[str, SolverAttemptRecord, SolverAttemptEvidence, bool]:
        spec, executable_path, budget, attempt_id, tmp_dir = item
        translation = spec.translation

        input_text = build_solver_input_text(translation)
        input_digest = compute_content_digest(
            {
                "solver_name": spec.solver_name,
                "target": translation.target.value,
                "text": input_text,
            }
        )
        suffix = _SOLVER_INPUT_SUFFIX[translation.target]
        input_path = os.path.join(tmp_dir, _input_filename(attempt_id, suffix))
        with open(input_path, "w", encoding="utf-8") as fh:
            fh.write(input_text)

        # `command` is a literal argv list built only from a resolved
        # executable path, fixed CLI flags, and this file *path* — never
        # from `input_text` itself.
        command = self.policy.build_command(
            spec.solver_name, executable_path, input_path, budget
        )
        solver_version = self._solver_version(executable_path, spec.solver_name)

        started_at = _utcnow()
        outcome = self._process_runner(command, budget=budget, cancel_event=cancel_event)
        finished_at = _utcnow()

        raw_output_digest = compute_content_digest(
            {"stdout": outcome.stdout, "stderr": outcome.stderr}
        )

        solver_trace: Optional[str]
        if outcome.error is not None:
            verdict = SolverVerdict.ERROR
            solver_trace = outcome.error
        elif outcome.cancelled:
            verdict = SolverVerdict.UNKNOWN
            solver_trace = None
        elif outcome.timed_out:
            verdict = SolverVerdict.TIMEOUT
            solver_trace = None
        else:
            parser = _VERDICT_PARSERS[translation.target]
            verdict, solver_trace = parser(outcome.stdout, outcome.stderr)

        wall_time_seconds = outcome.wall_time_seconds
        # Guard the model's TIMEOUT-implies-wall-time-at-least-the-budget
        # invariant even if the OS scheduler let the kill land a hair early.
        if verdict is SolverVerdict.TIMEOUT and wall_time_seconds < budget.timeout_seconds:
            wall_time_seconds = budget.timeout_seconds

        resource_usage: Dict[str, Any] = {}
        if outcome.cpu_seconds is not None:
            resource_usage["cpu_seconds"] = outcome.cpu_seconds
        if outcome.max_rss_mb is not None:
            resource_usage["max_rss_mb"] = outcome.max_rss_mb
        if outcome.cancelled:
            resource_usage["cancelled"] = True

        record = SolverAttemptRecord(
            attempt_id=attempt_id,
            request_id=request_id,
            translation_id=translation.translation_id,
            solver_name=spec.solver_name,
            solver_version=solver_version,
            target=translation.target,
            timeout_seconds=budget.timeout_seconds,
            verdict=verdict,
            exit_code=outcome.returncode,
            wall_time_seconds=wall_time_seconds,
            raw_output_digest=raw_output_digest,
            started_at=started_at,
            finished_at=finished_at,
            resource_usage=resource_usage,
            network_used=False,
        )
        record.validate()

        attempt_evidence = SolverAttemptEvidence(
            attempt_id=attempt_id,
            command=command,
            input_digest=input_digest,
            raw_stdout=outcome.stdout,
            raw_stderr=outcome.stderr,
            solver_trace=solver_trace,
        )

        return attempt_id, record, attempt_evidence, outcome.cancelled
