"""Hammer-style bridge from interactive goals to automated provers.

The module implements the same high-level contract as ITP hammers such as
Sledgehammer/CoqHammer: select relevant premises, translate an expressive goal
to a backend solver format, run several automated solvers in parallel, and
reconstruct a native ITP proof script that can be checked by a trusted kernel.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence

from ipfs_datasets_py.logic.hammers.process_lifecycle import (
    ProcessKind,
    ProcessLimits,
    get_process_supervisor,
)


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_']*")
_IDENT_RE = re.compile(r"[^A-Za-z0-9_]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "by",
    "for",
    "from",
    "if",
    "in",
    "is",
    "it",
    "may",
    "must",
    "of",
    "or",
    "shall",
    "that",
    "the",
    "then",
    "to",
    "under",
    "when",
    "with",
}


class HammerStatus(Enum):
    """Top-level hammer outcome."""

    PROVED = "proved"
    UNPROVED = "unproved"
    NO_PREMISES = "no_premises"
    NO_BACKENDS = "no_backends"
    TRANSLATION_FAILED = "translation_failed"
    RECONSTRUCTION_FAILED = "reconstruction_failed"


class HammerBackendStatus(Enum):
    """Status from one automated backend."""

    PROVED = "proved"
    DISPROVED = "disproved"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


@dataclass(slots=True)
class HammerPremise:
    """A selectable theorem/fact from an ITP or legal-IR library."""

    name: str
    statement: str
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HammerGoal:
    """Goal to discharge through the hammer pipeline."""

    statement: str
    itp_system: str = "lean"
    name: str = "hammer_generated_goal"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PremiseSelection:
    """Premise selector output."""

    selected: List[HammerPremise]
    scores: Dict[str, float]
    considered_count: int
    max_premises: int


@dataclass(slots=True)
class HammerTranslation:
    """Translated solver problem."""

    target_format: str
    problem: str
    selected_premises: List[HammerPremise]
    transformations: List[str]
    success: bool = True
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HammerBackendResult:
    """Result from one ATP/SMT backend."""

    backend: str
    status: HammerBackendStatus
    proved: bool
    elapsed_seconds: float
    translation_format: str
    proof_trace: str = ""
    raw_output: str = ""
    error: str = ""
    timed_out: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HammerVerification:
    """Trusted-kernel reconstruction check."""

    verified: bool
    checker: str = ""
    elapsed_seconds: float = 0.0
    output: str = ""
    error: str = ""


@dataclass(slots=True)
class HammerReconstruction:
    """Native ITP proof script reconstructed from an ATP trace."""

    itp_system: str
    proof_script: str
    backend: str
    verified: bool
    status: str
    verification: Optional[HammerVerification] = None
    used_premises: List[str] = field(default_factory=list)
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HammerResult:
    """Full hammer pipeline report."""

    status: HammerStatus
    goal: HammerGoal
    premise_selection: PremiseSelection
    translations: Dict[str, HammerTranslation]
    backend_results: List[HammerBackendResult]
    reconstruction: Optional[HammerReconstruction] = None
    fallback_plan: List[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def proved(self) -> bool:
        return self.status == HammerStatus.PROVED


class HammerBackendRunner(Protocol):
    """Protocol for ATP/SMT backends used by the hammer."""

    name: str
    problem_format: str

    def run(self, translation: HammerTranslation, timeout_seconds: float) -> HammerBackendResult:
        """Run the backend against one translated problem."""


KernelVerifier = Callable[[str, str, HammerGoal, Sequence[HammerPremise]], HammerVerification]


def _tokens(text: str) -> List[str]:
    return [
        token.lower()
        for token in _TOKEN_RE.findall(str(text or ""))
        if token.lower() not in _STOPWORDS
    ]


def _normalize_identifier(value: str, *, prefix: str = "x") -> str:
    normalized = _IDENT_RE.sub("_", str(value or "")).strip("_").lower()
    if not normalized:
        normalized = prefix
    if normalized[0].isdigit():
        normalized = f"{prefix}_{normalized}"
    return normalized


def _stable_symbol(text: str, *, prefix: str) -> str:
    digest = hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:12]
    stem = "_".join(_tokens(text)[:5])
    return _normalize_identifier(f"{stem}_{digest}", prefix=prefix)


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


class HeuristicPremiseSelector:
    """Token and metadata based premise selector.

    This is intentionally deterministic. A learned selector can later replace or
    wrap it while preserving the same ``select`` contract.
    """

    def __init__(self, *, metadata_match_boost: float = 0.2) -> None:
        self.metadata_match_boost = float(metadata_match_boost)

    def select(
        self,
        goal: HammerGoal,
        premises: Sequence[HammerPremise | Mapping[str, Any] | str],
        *,
        max_premises: int = 256,
    ) -> PremiseSelection:
        normalized = [_as_premise(premise, index) for index, premise in enumerate(premises, start=1)]
        goal_tokens = set(_tokens(goal.statement))
        goal_metadata = dict(goal.metadata or {})
        scores: Dict[str, float] = {}

        for premise in normalized:
            premise_tokens = set(_tokens(premise.statement))
            if goal_tokens or premise_tokens:
                overlap = len(goal_tokens & premise_tokens)
                union = len(goal_tokens | premise_tokens) or 1
                token_score = overlap / union
            else:
                token_score = 0.0
            metadata_score = self._metadata_score(goal_metadata, premise.metadata)
            length_penalty = min(0.25, max(0, len(premise.statement) - 4000) / 20000)
            scores[premise.name] = max(
                0.0,
                (token_score + metadata_score) * float(premise.weight or 1.0) - length_penalty,
            )

        selected = sorted(
            normalized,
            key=lambda premise: (-scores.get(premise.name, 0.0), premise.name),
        )[: max(0, int(max_premises))]
        return PremiseSelection(
            selected=selected,
            scores={premise.name: round(scores.get(premise.name, 0.0), 6) for premise in selected},
            considered_count=len(normalized),
            max_premises=max(0, int(max_premises)),
        )

    def _metadata_score(self, goal_metadata: Mapping[str, Any], premise_metadata: Mapping[str, Any]) -> float:
        score = 0.0
        for key in (
            "formalism",
            "logic_family",
            "modal_family",
            "legal_ir_view",
            "program_synthesis_scope",
            "source_module",
        ):
            goal_value = str(goal_metadata.get(key) or "").strip().lower()
            premise_value = str(premise_metadata.get(key) or "").strip().lower()
            if goal_value and premise_value and goal_value == premise_value:
                score += self.metadata_match_boost
        return score


class HammerLogicTranslator:
    """Translate selected goals into backend solver formats."""

    def translate(
        self,
        goal: HammerGoal,
        premises: Sequence[HammerPremise],
        *,
        target_format: str,
    ) -> HammerTranslation:
        target = str(target_format or "smt-lib").strip().lower()
        transformations = [
            "premise_selection",
            "monomorphization",
            "lambda_elimination",
            "type_encoding",
        ]
        try:
            if target in {"smt", "smt-lib", "smt2", "z3", "cvc5"}:
                return HammerTranslation(
                    target_format="smt-lib",
                    problem=self._to_smt_lib(goal, premises),
                    selected_premises=list(premises),
                    transformations=transformations,
                    metadata={"goal_symbol": _stable_symbol(goal.statement, prefix="goal")},
                )
            if target in {"tptp", "tptp-fof", "fof", "vampire", "e", "e_prover"}:
                return HammerTranslation(
                    target_format="tptp-fof",
                    problem=self._to_tptp_fof(goal, premises),
                    selected_premises=list(premises),
                    transformations=transformations,
                    metadata={"goal_symbol": _stable_symbol(goal.statement, prefix="goal")},
                )
            return HammerTranslation(
                target_format=target,
                problem="",
                selected_premises=list(premises),
                transformations=transformations,
                success=False,
                errors=[f"Unsupported hammer translation target: {target_format}"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            return HammerTranslation(
                target_format=target,
                problem="",
                selected_premises=list(premises),
                transformations=transformations,
                success=False,
                errors=[str(exc)],
            )

    def _to_smt_lib(self, goal: HammerGoal, premises: Sequence[HammerPremise]) -> str:
        raw_goal = self._raw_solver_payload(goal.metadata, "smt_lib", "smt-lib", "smt2")
        raw_premises = [
            self._raw_solver_payload(premise.metadata, "smt_lib", "smt-lib", "smt2")
            for premise in premises
        ]
        if raw_goal or any(raw_premises):
            lines = ["; hammer generated SMT-LIB problem", "(set-logic ALL)"]
            for premise, raw in zip(premises, raw_premises):
                if raw:
                    lines.append(f"; premise {premise.name}")
                    lines.append(str(raw))
            if raw_goal:
                lines.append("; negated conjecture")
                lines.append(str(raw_goal))
            lines.append("(check-sat)")
            return "\n".join(lines) + "\n"

        lines = ["; hammer generated SMT-LIB problem", "(set-logic ALL)"]
        for premise in premises:
            symbol = _stable_symbol(premise.statement or premise.name, prefix="premise")
            lines.extend(
                [
                    f"; premise {premise.name}: {self._comment_text(premise.statement)}",
                    f"(declare-const {symbol} Bool)",
                    f"(assert {symbol})",
                ]
            )
        goal_symbol = _stable_symbol(goal.statement, prefix="goal")
        lines.extend(
            [
                f"; conjecture {goal.name}: {self._comment_text(goal.statement)}",
                f"(declare-const {goal_symbol} Bool)",
                f"(assert (not {goal_symbol}))",
                "(check-sat)",
            ]
        )
        return "\n".join(lines) + "\n"

    def _to_tptp_fof(self, goal: HammerGoal, premises: Sequence[HammerPremise]) -> str:
        raw_goal = self._raw_solver_payload(goal.metadata, "tptp", "fof")
        raw_premises = [self._raw_solver_payload(premise.metadata, "tptp", "fof") for premise in premises]
        if raw_goal or any(raw_premises):
            lines: List[str] = ["% hammer generated TPTP problem"]
            for premise, raw in zip(premises, raw_premises):
                if raw:
                    lines.append(f"% premise {premise.name}")
                    lines.append(str(raw).rstrip())
            if raw_goal:
                lines.append("% conjecture")
                lines.append(str(raw_goal).rstrip())
            return "\n".join(lines) + "\n"

        lines = ["% hammer generated TPTP FOF problem"]
        for premise in premises:
            name = _normalize_identifier(premise.name, prefix="premise")
            atom = _stable_symbol(premise.statement or premise.name, prefix="premise")
            lines.append(f"% {name}: {self._comment_text(premise.statement)}")
            lines.append(f"fof({name}, axiom, {atom}).")
        goal_name = _normalize_identifier(goal.name, prefix="goal")
        goal_atom = _stable_symbol(goal.statement, prefix="goal")
        lines.append(f"% conjecture: {self._comment_text(goal.statement)}")
        lines.append(f"fof({goal_name}, conjecture, {goal_atom}).")
        return "\n".join(lines) + "\n"

    def _raw_solver_payload(self, metadata: Mapping[str, Any], *keys: str) -> str:
        for key in keys:
            value = metadata.get(key)
            if value:
                return str(value)
        return ""

    def _comment_text(self, text: str) -> str:
        return str(text or "").replace("\n", " ")[:240]


class CallableHammerBackendRunner:
    """Small test/integration adapter around an arbitrary backend callable."""

    def __init__(
        self,
        name: str,
        problem_format: str,
        call: Callable[[HammerTranslation, float], HammerBackendResult],
    ) -> None:
        self.name = str(name)
        self.problem_format = str(problem_format)
        self._call = call

    def run(self, translation: HammerTranslation, timeout_seconds: float) -> HammerBackendResult:
        return self._call(translation, timeout_seconds)


class SubprocessHammerBackendRunner:
    """Run a solver executable against an SMT-LIB or TPTP problem."""

    def __init__(
        self,
        *,
        name: str,
        executable: str,
        problem_format: str,
        args: Optional[Sequence[str]] = None,
        suffix: str = ".p",
    ) -> None:
        self.name = name
        self.executable = executable
        self.problem_format = problem_format
        self.args = list(args or [])
        self.suffix = suffix

    def run(self, translation: HammerTranslation, timeout_seconds: float) -> HammerBackendResult:
        start = time.time()
        executable = shutil.which(self.executable) or self.executable
        if not shutil.which(executable) and not Path(executable).exists():
            return HammerBackendResult(
                backend=self.name,
                status=HammerBackendStatus.UNAVAILABLE,
                proved=False,
                elapsed_seconds=0.0,
                translation_format=translation.target_format,
                error=f"Executable not found: {self.executable}",
            )
        try:
            with tempfile.NamedTemporaryFile("w", suffix=self.suffix, delete=False) as handle:
                handle.write(translation.problem)
                problem_path = handle.name
            try:
                command = [executable, *self.args, problem_path]
                kind = (
                    ProcessKind.SMT
                    if self.problem_format.lower().startswith("smt")
                    else ProcessKind.ATP
                )
                completed = get_process_supervisor().run(
                    command,
                    kind=kind,
                    limits=ProcessLimits(
                        wall_time_seconds=max(0.001, float(timeout_seconds))
                    ),
                )
            finally:
                try:
                    os.unlink(problem_path)
                except OSError:
                    pass
            if completed.timed_out:
                return HammerBackendResult(
                    backend=self.name,
                    status=HammerBackendStatus.TIMEOUT,
                    proved=False,
                    elapsed_seconds=time.time() - start,
                    translation_format=translation.target_format,
                    error=f"Timeout after {timeout_seconds}s",
                    timed_out=True,
                    raw_output="\n".join(
                        part for part in (completed.stdout, completed.stderr) if part
                    ),
                )
            if completed.error:
                return HammerBackendResult(
                    backend=self.name,
                    status=HammerBackendStatus.ERROR,
                    proved=False,
                    elapsed_seconds=time.time() - start,
                    translation_format=translation.target_format,
                    error=completed.error,
                    raw_output="\n".join(
                        part for part in (completed.stdout, completed.stderr) if part
                    ),
                )
            output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
            status, proved = self._parse_output(output)
            return HammerBackendResult(
                backend=self.name,
                status=status,
                proved=proved,
                elapsed_seconds=time.time() - start,
                translation_format=translation.target_format,
                proof_trace=output if proved else "",
                raw_output=output,
                error=(
                    ""
                    if completed.returncode == 0 or proved
                    else completed.error or output[:1000]
                ),
                metadata={"returncode": completed.returncode},
            )
        except OSError as exc:
            return HammerBackendResult(
                backend=self.name,
                status=HammerBackendStatus.ERROR,
                proved=False,
                elapsed_seconds=time.time() - start,
                translation_format=translation.target_format,
                error=str(exc),
            )

    def _parse_output(self, output: str) -> tuple[HammerBackendStatus, bool]:
        lowered = output.lower()
        if self.problem_format == "smt-lib":
            if re.search(r"(^|\s)unsat(\s|$)", lowered):
                return HammerBackendStatus.PROVED, True
            if re.search(r"(^|\s)sat(\s|$)", lowered):
                return HammerBackendStatus.DISPROVED, False
        if "refutation found" in lowered or "szs status theorem" in lowered or "szs status unsatisfiable" in lowered:
            return HammerBackendStatus.PROVED, True
        if "timeout" in lowered:
            return HammerBackendStatus.TIMEOUT, False
        return HammerBackendStatus.UNKNOWN, False


def default_hammer_backends() -> List[HammerBackendRunner]:
    """Return conservative local ATP/SMT backend runners."""

    from .hammer_backends import default_hammer_subprocess_backends

    return default_hammer_subprocess_backends()


class HammerProofReconstructor:
    """Reconstruct solver output as a native ITP proof script."""

    def reconstruct(
        self,
        *,
        goal: HammerGoal,
        selected_premises: Sequence[HammerPremise],
        backend_result: HammerBackendResult,
        verify: bool = False,
        verifier: Optional[KernelVerifier] = None,
    ) -> HammerReconstruction:
        script = self._proof_script(goal, selected_premises, backend_result)
        verification: Optional[HammerVerification] = None
        verified = False
        status = "script_generated"
        error = ""
        if verify:
            if verifier is None:
                verifier = NativeKernelVerifier().verify
            verification = verifier(goal.itp_system, script, goal, selected_premises)
            verified = bool(verification.verified)
            status = "verified" if verified else "kernel_rejected"
            error = verification.error
        return HammerReconstruction(
            itp_system=goal.itp_system,
            proof_script=script,
            backend=backend_result.backend,
            verified=verified,
            verification=verification,
            status=status,
            used_premises=[premise.name for premise in selected_premises],
            error=error,
            metadata={
                "backend_status": backend_result.status.value,
                "translation_format": backend_result.translation_format,
            },
        )

    def _proof_script(
        self,
        goal: HammerGoal,
        selected_premises: Sequence[HammerPremise],
        backend_result: HammerBackendResult,
    ) -> str:
        system = str(goal.itp_system or "lean").strip().lower()
        if system == "lean":
            return self._lean_script(goal, selected_premises, backend_result)
        if system == "coq":
            return self._coq_script(goal, selected_premises, backend_result)
        if system == "isabelle":
            return self._isabelle_script(goal, selected_premises, backend_result)
        return self._generic_script(goal, selected_premises, backend_result)

    def _itp_statement(self, goal: HammerGoal) -> str:
        metadata = goal.metadata or {}
        for key in ("itp_statement", "lean_statement", "coq_statement", "isabelle_statement"):
            if metadata.get(key):
                return str(metadata[key])
        return str(goal.statement)

    def _lean_script(
        self,
        goal: HammerGoal,
        selected_premises: Sequence[HammerPremise],
        backend_result: HammerBackendResult,
    ) -> str:
        premise_comments = "\n".join(
            f"-- {premise.name}: {premise.statement[:180].replace(chr(10), ' ')}"
            for premise in selected_premises
        )
        imports = str(goal.metadata.get("lean_imports") or "import Mathlib")
        tactic = str(goal.metadata.get("lean_hammer_tactic") or "aesop")
        return (
            f"{imports}\n\n"
            f"-- Hammer backend: {backend_result.backend}\n"
            f"{premise_comments}\n"
            f"theorem {_normalize_identifier(goal.name, prefix='hammer_goal')} : {self._itp_statement(goal)} := by\n"
            f"  {tactic}\n"
        )

    def _coq_script(
        self,
        goal: HammerGoal,
        selected_premises: Sequence[HammerPremise],
        backend_result: HammerBackendResult,
    ) -> str:
        premise_comments = "\n".join(
            f"(* {premise.name}: {premise.statement[:180].replace(chr(10), ' ')} *)"
            for premise in selected_premises
        )
        tactic = str(goal.metadata.get("coq_hammer_tactic") or "firstorder")
        return (
            f"(* Hammer backend: {backend_result.backend} *)\n"
            f"{premise_comments}\n"
            f"Theorem {_normalize_identifier(goal.name, prefix='hammer_goal')} : {self._itp_statement(goal)}.\n"
            "Proof.\n"
            f"  {tactic}.\n"
            "Qed.\n"
        )

    def _isabelle_script(
        self,
        goal: HammerGoal,
        selected_premises: Sequence[HammerPremise],
        backend_result: HammerBackendResult,
    ) -> str:
        premise_names = " ".join(_normalize_identifier(premise.name, prefix="premise") for premise in selected_premises)
        method = str(goal.metadata.get("isabelle_hammer_method") or "metis")
        return (
            "theory HammerGenerated\n"
            "  imports Main\n"
            "begin\n\n"
            f"(* Hammer backend: {backend_result.backend} *)\n"
            f"theorem {_normalize_identifier(goal.name, prefix='hammer_goal')}: \"{self._itp_statement(goal)}\"\n"
            f"  by ({method} {premise_names})\n\n"
            "end\n"
        )

    def _generic_script(
        self,
        goal: HammerGoal,
        selected_premises: Sequence[HammerPremise],
        backend_result: HammerBackendResult,
    ) -> str:
        premise_names = ", ".join(premise.name for premise in selected_premises)
        return (
            f"# Hammer backend: {backend_result.backend}\n"
            f"# Goal: {goal.statement}\n"
            f"# Premises: {premise_names}\n"
            f"# Proof trace:\n{backend_result.proof_trace}\n"
        )


class NativeKernelVerifier:
    """Best-effort native kernel checker for reconstructed scripts."""

    def verify(
        self,
        itp_system: str,
        proof_script: str,
        goal: HammerGoal,
        selected_premises: Sequence[HammerPremise],
    ) -> HammerVerification:
        del goal, selected_premises
        start = time.time()
        system = str(itp_system or "").strip().lower()
        if system == "lean":
            return self._run_checker("lean", ".lean", proof_script, start)
        if system == "coq":
            return self._run_checker("coqc", ".v", proof_script, start)
        if system == "isabelle":
            return HammerVerification(
                verified=False,
                checker="isabelle",
                elapsed_seconds=time.time() - start,
                error="Native Isabelle batch checking requires a theory session and is not auto-run by default.",
            )
        return HammerVerification(
            verified=False,
            checker=system,
            elapsed_seconds=time.time() - start,
            error=f"No native checker registered for {itp_system}.",
        )

    def _run_checker(self, executable: str, suffix: str, proof_script: str, start: float) -> HammerVerification:
        binary = shutil.which(executable)
        if not binary:
            return HammerVerification(
                verified=False,
                checker=executable,
                elapsed_seconds=time.time() - start,
                error=f"Executable not found: {executable}",
            )
        try:
            with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False) as handle:
                handle.write(proof_script)
                proof_path = handle.name
            try:
                kind = ProcessKind.LEAN if executable == "lean" else ProcessKind.OTHER
                completed = get_process_supervisor().run(
                    [binary, proof_path],
                    kind=kind,
                    limits=ProcessLimits(wall_time_seconds=30.0),
                )
            finally:
                try:
                    os.unlink(proof_path)
                except OSError:
                    pass
            output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
            return HammerVerification(
                verified=completed.returncode == 0 and not completed.timed_out,
                checker=executable,
                elapsed_seconds=time.time() - start,
                output=output,
                error=(
                    ""
                    if completed.returncode == 0 and not completed.timed_out
                    else ("kernel_timeout" if completed.timed_out else completed.error or output[:1000])
                ),
            )
        except OSError as exc:
            return HammerVerification(
                verified=False,
                checker=executable,
                elapsed_seconds=time.time() - start,
                error=str(exc),
            )


class HammerPipeline:
    """End-to-end hammer workflow."""

    def __init__(
        self,
        *,
        premise_selector: Optional[HeuristicPremiseSelector] = None,
        translator: Optional[HammerLogicTranslator] = None,
        backends: Optional[Sequence[HammerBackendRunner]] = None,
        reconstructor: Optional[HammerProofReconstructor] = None,
        max_premises: int = 256,
        timeout_seconds: float = 10.0,
        parallel_workers: Optional[int] = None,
        verify_reconstruction: bool = False,
        kernel_verifier: Optional[KernelVerifier] = None,
    ) -> None:
        self.premise_selector = premise_selector or HeuristicPremiseSelector()
        self.translator = translator or HammerLogicTranslator()
        self.backends = list(backends) if backends is not None else default_hammer_backends()
        self.reconstructor = reconstructor or HammerProofReconstructor()
        self.max_premises = int(max_premises)
        self.timeout_seconds = float(timeout_seconds)
        self.parallel_workers = parallel_workers
        self.verify_reconstruction = bool(verify_reconstruction)
        self.kernel_verifier = kernel_verifier

    def prove(
        self,
        goal: HammerGoal | Mapping[str, Any] | str,
        premises: Sequence[HammerPremise | Mapping[str, Any] | str],
    ) -> HammerResult:
        start = time.time()
        resolved_goal = self._as_goal(goal)
        selection = self.premise_selector.select(
            resolved_goal,
            premises,
            max_premises=self.max_premises,
        )
        if not selection.selected:
            return HammerResult(
                status=HammerStatus.NO_PREMISES,
                goal=resolved_goal,
                premise_selection=selection,
                translations={},
                backend_results=[],
                fallback_plan=self._fallback_plan(resolved_goal, "no_premises"),
                elapsed_seconds=time.time() - start,
            )
        if not self.backends:
            return HammerResult(
                status=HammerStatus.NO_BACKENDS,
                goal=resolved_goal,
                premise_selection=selection,
                translations={},
                backend_results=[],
                fallback_plan=self._fallback_plan(resolved_goal, "no_backends"),
                elapsed_seconds=time.time() - start,
            )

        translations = self._translations_for_backends(resolved_goal, selection.selected)
        if not any(translation.success for translation in translations.values()):
            return HammerResult(
                status=HammerStatus.TRANSLATION_FAILED,
                goal=resolved_goal,
                premise_selection=selection,
                translations=translations,
                backend_results=[],
                fallback_plan=self._fallback_plan(resolved_goal, "translation_failed"),
                elapsed_seconds=time.time() - start,
            )

        backend_results = self._run_backends(translations)
        winner = next((result for result in backend_results if result.proved), None)
        if winner is None:
            return HammerResult(
                status=HammerStatus.UNPROVED,
                goal=resolved_goal,
                premise_selection=selection,
                translations=translations,
                backend_results=backend_results,
                fallback_plan=self._fallback_plan(resolved_goal, "no_backend_proof"),
                elapsed_seconds=time.time() - start,
            )

        reconstruction = self.reconstructor.reconstruct(
            goal=resolved_goal,
            selected_premises=selection.selected,
            backend_result=winner,
            verify=self.verify_reconstruction,
            verifier=self.kernel_verifier,
        )
        if self.verify_reconstruction and not reconstruction.verified:
            return HammerResult(
                status=HammerStatus.RECONSTRUCTION_FAILED,
                goal=resolved_goal,
                premise_selection=selection,
                translations=translations,
                backend_results=backend_results,
                reconstruction=reconstruction,
                fallback_plan=self._fallback_plan(resolved_goal, "reconstruction_failed"),
                elapsed_seconds=time.time() - start,
            )
        return HammerResult(
            status=HammerStatus.PROVED,
            goal=resolved_goal,
            premise_selection=selection,
            translations=translations,
            backend_results=backend_results,
            reconstruction=reconstruction,
            elapsed_seconds=time.time() - start,
            metadata={"winner_backend": winner.backend},
        )

    def _translations_for_backends(
        self,
        goal: HammerGoal,
        premises: Sequence[HammerPremise],
    ) -> Dict[str, HammerTranslation]:
        translations: Dict[str, HammerTranslation] = {}
        for backend in self.backends:
            target_format = str(getattr(backend, "problem_format", "smt-lib"))
            if target_format in translations:
                continue
            translations[target_format] = self.translator.translate(
                goal,
                premises,
                target_format=target_format,
            )
        return translations

    def _run_backends(self, translations: Mapping[str, HammerTranslation]) -> List[HammerBackendResult]:
        results: List[HammerBackendResult] = []
        max_workers = self.parallel_workers or max(1, len(self.backends))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="hammer-atp") as executor:
            futures = {}
            for backend in self.backends:
                target_format = str(getattr(backend, "problem_format", "smt-lib"))
                translation = translations.get(target_format)
                if translation is None or not translation.success:
                    results.append(
                        HammerBackendResult(
                            backend=getattr(backend, "name", "unknown"),
                            status=HammerBackendStatus.ERROR,
                            proved=False,
                            elapsed_seconds=0.0,
                            translation_format=target_format,
                            error="No successful translation for backend.",
                        )
                    )
                    continue
                futures[executor.submit(backend.run, translation, self.timeout_seconds)] = backend
            for future in as_completed(futures):
                backend = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(
                        HammerBackendResult(
                            backend=getattr(backend, "name", "unknown"),
                            status=HammerBackendStatus.ERROR,
                            proved=False,
                            elapsed_seconds=0.0,
                            translation_format=str(getattr(backend, "problem_format", "")),
                            error=str(exc),
                        )
                    )
        return sorted(results, key=lambda result: (not result.proved, result.elapsed_seconds, result.backend))

    def _as_goal(self, value: HammerGoal | Mapping[str, Any] | str) -> HammerGoal:
        if isinstance(value, HammerGoal):
            return value
        if isinstance(value, Mapping):
            return HammerGoal(
                statement=str(value.get("statement") or value.get("goal") or value.get("formula") or ""),
                itp_system=str(value.get("itp_system") or value.get("system") or "lean"),
                name=str(value.get("name") or "hammer_generated_goal"),
                metadata=dict(value.get("metadata") or {}),
            )
        return HammerGoal(statement=str(value))

    def _fallback_plan(self, goal: HammerGoal, reason: str) -> List[str]:
        clauses = [
            clause.strip()
            for clause in re.split(r"(?:;|\.|\band\b|\bor\b)", goal.statement)
            if len(clause.strip()) > 20
        ][:5]
        plan = [
            f"hammer_failed:{reason}",
            "increase_premise_budget_or_add_domain_specific_lemmas",
            "route_goal_to_llm_translator_for_smaller_subgoals",
            "retry_with_native_itp_automation_tactic",
        ]
        for index, clause in enumerate(clauses, start=1):
            plan.append(f"subgoal_{index}:{clause}")
        return plan


def hammer_prove(
    goal: HammerGoal | Mapping[str, Any] | str,
    premises: Sequence[HammerPremise | Mapping[str, Any] | str],
    *,
    backends: Optional[Sequence[HammerBackendRunner]] = None,
    max_premises: int = 256,
    timeout_seconds: float = 10.0,
    verify_reconstruction: bool = False,
    kernel_verifier: Optional[KernelVerifier] = None,
) -> HammerResult:
    """Convenience entry point for callers that do not need custom components."""

    return HammerPipeline(
        backends=backends,
        max_premises=max_premises,
        timeout_seconds=timeout_seconds,
        verify_reconstruction=verify_reconstruction,
        kernel_verifier=kernel_verifier,
    ).prove(goal, premises)


__all__ = [
    "CallableHammerBackendRunner",
    "HammerBackendResult",
    "HammerBackendRunner",
    "HammerBackendStatus",
    "HammerGoal",
    "HammerLogicTranslator",
    "HammerPipeline",
    "HammerPremise",
    "HammerProofReconstructor",
    "HammerReconstruction",
    "HammerResult",
    "HammerStatus",
    "HammerTranslation",
    "HammerVerification",
    "HeuristicPremiseSelector",
    "KernelVerifier",
    "NativeKernelVerifier",
    "PremiseSelection",
    "SubprocessHammerBackendRunner",
    "default_hammer_backends",
    "hammer_prove",
]
