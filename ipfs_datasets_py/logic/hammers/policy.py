"""Allowlisted solver policy for the ITP hammer portfolio executor
(``## HAMMER-008`` in ``docs/logic/itp_hammer_taskboard.todo.md``).

This module defines *what may run and how it is bounded* — never *how it is
invoked* (that plumbing lives in :mod:`.portfolio`). It builds on top of the
:class:`~.models.HammerPolicy` operator policy already defined by HAMMER-001
and adds the finer-grained, per-solver budgets and executable-resolution
rules the portfolio executor needs:

- :class:`SolverSpec` — a fixed, in-repo description of one allowlisted
  solver family (``z3``, ``cvc5``, ``vampire``, ``e``): its translation
  target, the executable names it may be discovered under, and a pure
  function that assembles its command-line argument *list* (never a shell
  string) from an already-resolved executable path, an input file path, and
  a :class:`SolverBudget`.
- :class:`SolverBudget` — an independent wall-clock/CPU/memory budget for a
  single solver attempt.
- :class:`PortfolioPolicy` — ties a :class:`~.models.HammerPolicy` to
  per-solver budget overrides, explicit executable-path overrides, a
  process-count budget (``max_parallel_processes``), and a
  cancellation-budget switch (``cancel_on_first_conclusive``).
- :class:`PolicyError` — raised whenever a requested solver, executable, or
  budget would violate the operator's policy; the portfolio executor never
  silently substitutes a different solver or budget instead.

Security invariant
--------------------
Nothing in this module ever builds a shell command string. Every
``build_argv``/``build_command`` call returns a literal ``list[str]``
suitable for ``subprocess.Popen(argv, shell=False)`` (the only mode
:mod:`.portfolio` ever uses), and the only "content" placed into that list
is a resolved executable path, fixed CLI flags, and a *file path* the
caller already wrote goal/premise text to — never the goal/premise text
itself. This makes shell-metacharacter injection from translated theorem
content structurally impossible, not merely discouraged.
"""

from __future__ import annotations

import math
import os
import shutil
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .models import (
    SCHEMA_VERSION,
    HammerPolicy,
    TranslationTarget,
    _require_schema_version,
)

__all__ = [
    "SCHEMA_VERSION",
    "PolicyError",
    "SolverSpec",
    "SolverBudget",
    "PortfolioPolicy",
    "known_solver_names",
    "solver_spec",
    "build_preexec_fn",
]


class PolicyError(RuntimeError):
    """Raised whenever a portfolio invocation would violate operator policy:
    an unrecognized/non-allowlisted solver name, a solver not present in the
    owning :class:`~.models.HammerPolicy.allowed_solvers`, a missing/
    unresolvable executable, or a per-solver budget that exceeds the
    governing policy's bounds. Portfolio execution must fail closed with
    this error rather than silently falling back to a different solver,
    executable, or budget.
    """


def _ceil_seconds(value: float) -> int:
    """Round ``value`` seconds up to the nearest whole second, at least 1."""

    return max(1, int(math.ceil(float(value))))


def _ceil_millis(value: float) -> int:
    """Round ``value`` seconds up to the nearest whole millisecond, at
    least 1."""

    return max(1, int(math.ceil(float(value) * 1000.0)))


# ---------------------------------------------------------------------------
# Per-solver command-line argv builders
#
# Every builder returns a literal argv list. None of them ever receive or
# emit translated theorem content — only an executable path, fixed flags,
# and an input *file path* the caller already wrote that content to.
# ---------------------------------------------------------------------------


def _z3_argv(executable_path: str, input_path: str, budget: "SolverBudget") -> List[str]:
    argv = [executable_path, "-smt2", f"-T:{_ceil_seconds(budget.timeout_seconds)}"]
    if budget.memory_mb is not None:
        argv.append(f"-memory:{int(budget.memory_mb)}")
    argv.append(input_path)
    return argv


def _cvc5_argv(executable_path: str, input_path: str, budget: "SolverBudget") -> List[str]:
    argv = [
        executable_path,
        "--lang=smt2",
        f"--tlimit={_ceil_millis(budget.timeout_seconds)}",
        input_path,
    ]
    return argv


def _vampire_argv(executable_path: str, input_path: str, budget: "SolverBudget") -> List[str]:
    argv = [
        executable_path,
        "--time_limit",
        str(_ceil_seconds(budget.timeout_seconds)),
    ]
    if budget.memory_mb is not None:
        argv += ["--memory_limit", str(int(budget.memory_mb))]
    argv += ["--proof", "tptp", input_path]
    return argv


def _eprover_argv(executable_path: str, input_path: str, budget: "SolverBudget") -> List[str]:
    argv = [
        executable_path,
        "--auto",
        "--tstp-out",
        f"--cpu-limit={_ceil_seconds(budget.timeout_seconds)}",
    ]
    if budget.memory_mb is not None:
        argv.append(f"--memory-limit={int(budget.memory_mb)}")
    argv.append(input_path)
    return argv


_ARGV_BUILDERS: Dict[str, Callable[[str, str, "SolverBudget"], List[str]]] = {
    "z3": _z3_argv,
    "cvc5": _cvc5_argv,
    "vampire": _vampire_argv,
    "e": _eprover_argv,
}


@dataclass(frozen=True)
class SolverSpec:
    """A fixed, in-repo description of one allowlisted solver family.

    Attributes:
        name: Canonical solver name (``"z3"``, ``"cvc5"``, ``"vampire"``,
            or ``"e"``) — matches
            :attr:`~.models.HammerPolicy.allowed_solvers` entries and the
            ``surface_id`` used by the HAMMER-002 environment probe.
        display_name: Human-readable solver name.
        target: The single :class:`~.models.TranslationTarget` this solver
            consumes (SMT-LIB for ``z3``/``cvc5``; TPTP for
            ``vampire``/``e``).
        candidate_executables: Executable names searched for on ``PATH``
            (in order) when no explicit override is configured.
        version_args: Arguments appended to the executable for a bounded
            ``--version``-style metadata probe.
    """

    name: str
    display_name: str
    target: TranslationTarget
    candidate_executables: Tuple[str, ...]
    version_args: Tuple[str, ...] = ("--version",)

    def build_argv(
        self, executable_path: str, input_path: str, budget: "SolverBudget"
    ) -> List[str]:
        """Build the literal argv for invoking this solver.

        Never interpolates any theorem content — only ``executable_path``
        (already resolved by :meth:`PortfolioPolicy.resolve_executable`),
        fixed CLI flags derived from ``budget``, and ``input_path`` (a file
        path the caller wrote the solver's problem text to).
        """

        return _ARGV_BUILDERS[self.name](executable_path, input_path, budget)


_SOLVER_SPECS: Dict[str, SolverSpec] = {
    "z3": SolverSpec(
        name="z3",
        display_name="Z3 SMT Solver",
        target=TranslationTarget.SMTLIB,
        candidate_executables=("z3",),
    ),
    "cvc5": SolverSpec(
        name="cvc5",
        display_name="CVC5 SMT Solver",
        target=TranslationTarget.SMTLIB,
        candidate_executables=("cvc5",),
    ),
    "vampire": SolverSpec(
        name="vampire",
        display_name="Vampire ATP",
        target=TranslationTarget.TPTP,
        candidate_executables=("vampire",),
    ),
    "e": SolverSpec(
        name="e",
        display_name="E Theorem Prover",
        target=TranslationTarget.TPTP,
        candidate_executables=("eprover", "eprover-ho"),
    ),
}


def known_solver_names() -> Tuple[str, ...]:
    """Return the sorted tuple of every solver family this pipeline knows
    how to invoke (the maximal allowlist — an operator's
    ``HammerPolicy.allowed_solvers`` must be a subset of this)."""

    return tuple(sorted(_SOLVER_SPECS.keys()))


def solver_spec(solver_name: str) -> SolverSpec:
    """Look up the :class:`SolverSpec` for ``solver_name``.

    Raises:
        PolicyError: If ``solver_name`` is not one of :func:`known_solver_names`.
    """

    try:
        return _SOLVER_SPECS[solver_name]
    except KeyError as exc:
        raise PolicyError(
            f"{solver_name!r} is not an allowlisted solver family; known "
            f"families are {known_solver_names()!r}"
        ) from exc


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


@dataclass
class SolverBudget:
    """An independent wall-clock/CPU/memory budget for a single solver
    attempt.

    Attributes:
        schema_version: Schema version of this record.
        timeout_seconds: Wall-clock budget enforced both by a subprocess
            wall-clock deadline and (best-effort) by a solver-specific CLI
            timeout flag.
        cpu_seconds: Optional CPU-time budget enforced via ``RLIMIT_CPU`` on
            POSIX platforms (see :func:`build_preexec_fn`).
        memory_mb: Optional memory budget (MiB) enforced both by a
            solver-specific CLI flag (where supported) and, as the
            authoritative backstop, ``RLIMIT_AS`` on POSIX platforms.
    """

    schema_version: str = SCHEMA_VERSION
    timeout_seconds: float = 30.0
    cpu_seconds: Optional[float] = None
    memory_mb: Optional[int] = None

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="SolverBudget")
        if not isinstance(self.timeout_seconds, (int, float)) or isinstance(
            self.timeout_seconds, bool
        ):
            raise ValueError("SolverBudget.timeout_seconds must be a number")
        if self.timeout_seconds <= 0:
            raise ValueError("SolverBudget.timeout_seconds must be positive")
        if self.cpu_seconds is not None and self.cpu_seconds <= 0:
            raise ValueError("SolverBudget.cpu_seconds must be positive if set")
        if self.memory_mb is not None and self.memory_mb <= 0:
            raise ValueError("SolverBudget.memory_mb must be positive if set")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SolverBudget":
        return cls(**dict(data))


# ---------------------------------------------------------------------------
# Portfolio policy
# ---------------------------------------------------------------------------


@dataclass
class PortfolioPolicy:
    """Operator-controlled policy governing one solver-portfolio run.

    Attributes:
        schema_version: Schema version of this record.
        hammer_policy: The owning :class:`~.models.HammerPolicy` (its
            ``allowed_solvers`` allow-list, default ``timeout_seconds``/
            ``cpu_seconds``/``memory_mb``, and ``network_allowed`` govern
            every attempt in this portfolio).
        solver_budgets: Optional per-solver budget overrides, keyed by
            solver name. A solver without an entry here uses
            ``hammer_policy``'s defaults. No override may exceed
            ``hammer_policy.timeout_seconds`` (see :meth:`budget_for`).
        executable_overrides: Optional explicit executable path per solver
            name, bypassing ``PATH`` search. Still validated to exist and be
            executable; still gated by ``hammer_policy.allowed_solvers``.
        max_parallel_processes: Process-count budget — the maximum number
            of solver subprocesses the portfolio executor may run
            concurrently.
        cancel_on_first_conclusive: Cancellation budget switch. When
            ``True`` (the default "race" policy), the portfolio executor
            cancels every still-running attempt as soon as one attempt
            reaches a conclusive verdict (``sat``/``unsat``/``proved``/
            ``disproved``); a candidate result is still produced only from
            an attempt that actually ran to completion, never fabricated
            for a cancelled attempt.
    """

    schema_version: str = SCHEMA_VERSION
    hammer_policy: HammerPolicy = field(default_factory=HammerPolicy)
    solver_budgets: Dict[str, SolverBudget] = field(default_factory=dict)
    executable_overrides: Dict[str, str] = field(default_factory=dict)
    max_parallel_processes: int = 4
    cancel_on_first_conclusive: bool = True

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="PortfolioPolicy")
        if not isinstance(self.hammer_policy, HammerPolicy):
            raise ValueError("PortfolioPolicy.hammer_policy must be a HammerPolicy")
        self.hammer_policy.validate()

        for name in self.hammer_policy.allowed_solvers:
            if name not in known_solver_names():
                raise PolicyError(
                    f"HammerPolicy.allowed_solvers contains {name!r}, which is "
                    f"not one of the allowlisted solver families "
                    f"{known_solver_names()!r}"
                )

        if not isinstance(self.solver_budgets, dict):
            raise ValueError("PortfolioPolicy.solver_budgets must be a dict")
        for name, budget in self.solver_budgets.items():
            if name not in known_solver_names():
                raise PolicyError(
                    f"PortfolioPolicy.solver_budgets references unknown solver "
                    f"family {name!r}; known families are {known_solver_names()!r}"
                )
            if not isinstance(budget, SolverBudget):
                raise ValueError(
                    f"PortfolioPolicy.solver_budgets[{name!r}] must be a SolverBudget"
                )
            budget.validate()

        if not isinstance(self.executable_overrides, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and v.strip()
            for k, v in self.executable_overrides.items()
        ):
            raise ValueError(
                "PortfolioPolicy.executable_overrides must map str -> non-empty str"
            )
        for name in self.executable_overrides:
            if name not in known_solver_names():
                raise PolicyError(
                    f"PortfolioPolicy.executable_overrides references unknown "
                    f"solver family {name!r}; known families are "
                    f"{known_solver_names()!r}"
                )

        if not isinstance(self.max_parallel_processes, int) or isinstance(
            self.max_parallel_processes, bool
        ):
            raise ValueError(
                "PortfolioPolicy.max_parallel_processes must be an int"
            )
        if self.max_parallel_processes <= 0:
            raise ValueError(
                "PortfolioPolicy.max_parallel_processes must be positive"
            )
        if not isinstance(self.cancel_on_first_conclusive, bool):
            raise ValueError(
                "PortfolioPolicy.cancel_on_first_conclusive must be a boolean"
            )

    def budget_for(self, solver_name: str) -> SolverBudget:
        """Return the effective :class:`SolverBudget` for ``solver_name``:
        its override if one is configured, otherwise
        ``hammer_policy``'s defaults.

        Raises:
            PolicyError: If an override's ``timeout_seconds`` exceeds
                ``hammer_policy.timeout_seconds`` — a per-solver budget may
                only ever be *tighter* than the governing policy, never
                looser.
        """

        if solver_name not in known_solver_names():
            raise PolicyError(
                f"{solver_name!r} is not an allowlisted solver family; known "
                f"families are {known_solver_names()!r}"
            )
        if solver_name in self.solver_budgets:
            budget = self.solver_budgets[solver_name]
        else:
            budget = SolverBudget(
                timeout_seconds=self.hammer_policy.timeout_seconds,
                cpu_seconds=self.hammer_policy.cpu_seconds,
                memory_mb=self.hammer_policy.memory_mb,
            )
        budget.validate()
        if budget.timeout_seconds > self.hammer_policy.timeout_seconds + 1e-9:
            raise PolicyError(
                f"solver_budgets[{solver_name!r}].timeout_seconds="
                f"{budget.timeout_seconds!r} exceeds "
                f"HammerPolicy.timeout_seconds="
                f"{self.hammer_policy.timeout_seconds!r}"
            )
        return budget

    def resolve_executable(self, solver_name: str) -> str:
        """Resolve ``solver_name`` to an absolute, executable path.

        Resolution order: an :attr:`executable_overrides` entry (validated
        to exist and be executable) takes precedence; otherwise the first
        of :attr:`SolverSpec.candidate_executables` found on ``PATH`` via
        :func:`shutil.which` is used. Never falls back to a different
        solver family and never searches beyond ``PATH``/the configured
        override.

        Raises:
            PolicyError: If ``solver_name`` is unknown, not present in
                ``hammer_policy.allowed_solvers``, or no usable executable
                can be resolved for it.
        """

        spec = solver_spec(solver_name)
        if solver_name not in self.hammer_policy.allowed_solvers:
            raise PolicyError(
                f"solver {solver_name!r} is not present in "
                f"HammerPolicy.allowed_solvers={self.hammer_policy.allowed_solvers!r}"
            )

        override = self.executable_overrides.get(solver_name)
        if override is not None:
            if not os.path.isfile(override) or not os.access(override, os.X_OK):
                raise PolicyError(
                    f"executable_overrides[{solver_name!r}]={override!r} does not "
                    f"exist or is not executable"
                )
            return override

        for candidate in spec.candidate_executables:
            found = shutil.which(candidate)
            if found:
                return found

        raise PolicyError(
            f"no allowlisted executable found for solver {solver_name!r}: "
            f"none of {spec.candidate_executables!r} were found on PATH and no "
            f"executable_overrides entry was configured"
        )

    def build_command(
        self, solver_name: str, executable_path: str, input_path: str, budget: SolverBudget
    ) -> List[str]:
        """Build the literal argv for invoking ``solver_name`` against
        ``input_path`` under ``budget``. ``executable_path`` must already
        have been produced by :meth:`resolve_executable` — this method
        never re-resolves or searches ``PATH`` itself."""

        spec = solver_spec(solver_name)
        return spec.build_argv(executable_path, input_path, budget)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "hammer_policy": self.hammer_policy.to_dict(),
            "solver_budgets": {k: v.to_dict() for k, v in self.solver_budgets.items()},
            "executable_overrides": dict(self.executable_overrides),
            "max_parallel_processes": self.max_parallel_processes,
            "cancel_on_first_conclusive": self.cancel_on_first_conclusive,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PortfolioPolicy":
        data = dict(data)
        hammer_policy = data.get("hammer_policy")
        if isinstance(hammer_policy, dict):
            data["hammer_policy"] = HammerPolicy.from_dict(hammer_policy)
        solver_budgets = data.get("solver_budgets", {}) or {}
        data["solver_budgets"] = {
            name: (SolverBudget.from_dict(value) if isinstance(value, dict) else value)
            for name, value in solver_budgets.items()
        }
        return cls(**data)


# ---------------------------------------------------------------------------
# POSIX resource-limit enforcement
# ---------------------------------------------------------------------------


def build_preexec_fn(budget: SolverBudget) -> Optional[Callable[[], None]]:
    """Build a ``preexec_fn`` for :class:`subprocess.Popen` that applies
    ``budget``'s CPU/memory ``rlimit``s in the forked child and starts a new
    session (so the whole solver process tree can later be killed
    atomically via ``os.killpg``).

    Returns ``None`` on non-POSIX platforms, where neither ``os.setsid``
    nor the ``resource`` module are available; callers must treat process
    cancellation/kill as best-effort (single-process, not process-group) on
    those platforms.

    Note on safety: ``preexec_fn`` runs in the forked child between
    ``fork()`` and ``exec()``. The callable returned here only calls
    ``os.setsid`` and ``resource.setrlimit`` — no locks, no I/O, no
    allocation beyond what those calls need — and the child image is
    replaced by the solver binary immediately afterward, which is the
    documented safe usage pattern for ``preexec_fn``.
    """

    if os.name != "posix":
        return None

    def _apply() -> None:
        import resource

        try:
            os.setsid()
        except OSError:
            pass
        if budget.cpu_seconds is not None:
            cpu_limit = _ceil_seconds(budget.cpu_seconds)
            try:
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit))
            except (ValueError, OSError):
                pass
        if budget.memory_mb is not None:
            mem_bytes = int(budget.memory_mb) * 1024 * 1024
            try:
                resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            except (ValueError, OSError):
                pass

    return _apply
