"""Native Isabelle/HOL goal capture with the modern process_theories tool.

Capability discovery probes version and command help without installation or
heap construction. Execution loads a private theory with print_state and one
worker. Capture permits the explicit incomplete proof solely to obtain native
goal evidence; it grants no theorem authority. Optional auto_install=True
uses the admitted, checksummed installer within the same operation deadline.
"""

from __future__ import annotations

import hashlib
import re
from typing import List, Optional

from ipfs_datasets_py.logic.backends.installers.isabelle_execution import run_isabelle_operation, validate_isabelle_source
from ipfs_datasets_py.logic.external_provers.isabelle_runtime import theory_command, theory_name as validate_theory_name

from ..models import ITPKind
from .base import (
    DEFAULT_TIMEOUT_SECONDS,
    CapabilityEvidence,
    FrontendUnavailableError,
    GoalCaptureError,
    GoalSnapshot,
    LocalHypothesis,
    SourcePosition,
    UniverseContext,
)

__all__ = ["IsabelleFrontend"]

_SORRY_RE = re.compile(r"\bsorry\b")
_THEORY_NAME_RE = re.compile(r"^\s*theory\s+(\S+)", re.MULTILINE)
_IMPORTS_RE = re.compile(r"^\s*imports\s+(.+)$", re.MULTILINE)
_GOAL_BLOCK_RE = re.compile(
    r"goal\s*\((?P<count>\d+)\s+subgoals?\)\s*:\s*\n(?P<goals>(?:.*\n?)+?)(?:\n\s*\n|\Z)"
)
_ENUMERATED_GOAL_RE = re.compile(r"^\s*(\d+)\.\s+(.*)$")
_USING_THIS_RE = re.compile(r"using this:\s*\n(?P<facts>(?:\s{2,}.*\n?)+)")
_FIX_RE = re.compile(r"^\s*fix\s+(.+)$", re.MULTILINE)


class IsabelleFrontend:
    """Native Isabelle/HOL frontend adapter implementing
    :class:`ITPFrontend`."""

    itp = ITPKind.ISABELLE

    def __init__(self, *, timeout: float = DEFAULT_TIMEOUT_SECONDS, executable: str = "isabelle",
                 auto_install: bool = False, install_root=None, parent_lease=None,
                 scheduler=None, cancellation=None, memory_mb: int = 2048):
        self._timeout = timeout
        self._executable = None if executable == "isabelle" else executable
        self._auto_install = auto_install
        self._install_root = install_root
        self._parent_lease = parent_lease
        self._scheduler = scheduler
        self._cancellation = cancellation
        self._memory_mb = memory_mb

    def _operation_options(self):
        return dict(executable=self._executable, install_root=self._install_root,
                    parent_lease=self._parent_lease, scheduler=self._scheduler,
                    cancellation=self._cancellation, memory_mb=self._memory_mb)

    # -- capability ---------------------------------------------------

    def capability(self) -> CapabilityEvidence:
        operation = run_isabelle_operation(mode="command", timeout_seconds=self._timeout,
                                           **self._operation_options())
        return _capability_from_operation(operation)

    # -- goal snapshot --------------------------------------------------

    def snapshot_goal(
        self,
        source: str,
        *,
        theorem_id: str,
        file_name: str = "Goal.thy",
        timeout: Optional[float] = None,
    ) -> GoalSnapshot:
        try:
            validate_isabelle_source(source)
        except ValueError as exc:
            raise GoalCaptureError(str(exc)) from exc
        if not _SORRY_RE.search(source):
            raise GoalCaptureError(
                "IsabelleFrontend.snapshot_goal requires a native `sorry` "
                "placeholder in source; refusing to fabricate a goal from "
                "plain text"
            )

        theory_match = _THEORY_NAME_RE.search(source)
        if theory_match is None:
            raise GoalCaptureError(
                "IsabelleFrontend.snapshot_goal requires a `theory NAME` "
                "header in source to derive the required matching file name"
            )
        try:
            theory_name = validate_theory_name(source)
        except ValueError as exc:
            raise GoalCaptureError(str(exc)) from exc
        resolved_file_name = f"{theory_name}.thy"
        instrumented, marker_line, marker_col = _instrument_isabelle_source(source)
        try:
            validate_isabelle_source(instrumented)
        except ValueError as exc:
            raise GoalCaptureError(str(exc)) from exc
        operation = run_isabelle_operation(
            mode="capture", source=instrumented, auto_install=self._auto_install,
            timeout_seconds=timeout if timeout is not None else self._timeout,
            **self._operation_options(),
        )
        capability = _capability_from_operation(operation)
        result = operation.observation
        if result is None:
            raise FrontendUnavailableError(
                f"Isabelle frontend unavailable: {capability.unavailable_reason}", capability=capability,
            )
        if (operation.status != "completed" or result.error or result.returncode != 0
                or result.cancelled or result.timed_out or result.unavailable
                or result.resource_exhausted or result.output_truncated
                or result.workspace_limit_exceeded or not result.workspace_cleaned):
            raise _operation_failure(
                f"isabelle process_theories invocation failed (exit {result.returncode}, "
                f"{operation.reason_code}): {result.error or (result.stderr + result.stdout)[-2000:]}",
                operation,
            )
        isabelle_path = capability.executables["isabelle"]["path"]
        expected_command = tuple(theory_command(isabelle_path, theory_name, "{workspace}", capture=True))
        if (not capability.available or not operation.runtime_unchanged
                or operation.source_sha256 != hashlib.sha256(instrumented.encode("utf-8")).hexdigest()
                or operation.theory_name != theory_name or result.command != expected_command):
            raise _operation_failure("Isabelle execution receipt does not match the requested theory/runtime", operation)

        combined_output = result.stdout + "\n" + result.stderr
        block_match = _GOAL_BLOCK_RE.search(combined_output)
        if block_match is None:
            raise GoalCaptureError(
                "isabelle process_theories produced no `goal (N subgoals):` block "
                "after `print_state`; cannot construct a goal snapshot "
                f"without native evidence (stdout={result.stdout!r}, "
                f"stderr={result.stderr!r})"
            )

        goal_text = _first_enumerated_goal(block_match.group("goals"))
        if goal_text is None:
            raise GoalCaptureError(
                f"isabelle process_theories goal block had no enumerated subgoal: {block_match.group(0)!r}"
            )

        hypotheses = _parse_isabelle_hypotheses(combined_output, source)
        imports = _extract_isabelle_imports(source)
        universe_context = _extract_isabelle_universe_context(hypotheses, goal_text)
        source_position = SourcePosition(
            file=file_name if file_name != "Goal.thy" else resolved_file_name,
            line=marker_line,
            column=marker_col,
        )

        return GoalSnapshot(
            itp=ITPKind.ISABELLE,
            itp_version=capability.executables["isabelle"].get("version") or "unknown",
            theorem_id=theorem_id,
            goal_text=goal_text,
            hypotheses=hypotheses,
            imports=imports,
            universe_context=universe_context,
            source_position=source_position,
            native_command=theory_command(isabelle_path, theory_name, ".", capture=True),
            raw_native_output=block_match.group(0),
            extra={
                "resolved_executable": isabelle_path,
                "theory_name": theory_name,
                "full_output": combined_output,
                "execution": operation.to_dict(),
            },
        )


def _operation_failure(message, operation) -> GoalCaptureError:
    error = GoalCaptureError(message)
    error.execution = operation.to_dict()
    return error


def _capability_from_operation(operation) -> CapabilityEvidence:
    """Project current admitted runtime observations without another probe."""
    runtime = operation.native_runtime or {}
    if hasattr(runtime, "to_dict"):
        runtime = runtime.to_dict()
    preparation = operation.preparation
    available = bool(operation.status == "completed" and preparation is not None
                     and preparation.command_available)
    reason = {"installed_artifact_missing": "isabelle_executable_not_found_on_path_or_common_install_dirs",
              "isabelle_theory_processor_unavailable": "isabelle_process_theories_not_ready"}.get(
                  operation.reason_code, operation.reason_code)
    return CapabilityEvidence(
        itp=ITPKind.ISABELLE, available=available,
        executables={"isabelle": {
            "found": bool(runtime.get("executable")), "path": runtime.get("executable"),
            "version": runtime.get("version"),
            "version_probe_error": None if available else reason,
            "theory_processing_ready": available, "execution": operation.to_dict(),
        }},
        unavailable_reason=None if available else reason,
        notes="Runtime checks and theory execution use shared pressure-aware admission, "
              "private workspaces and one total deadline. Capability checks never install "
              "or build HOL. Resource observations confer no proof authority.",
    )


# ---------------------------------------------------------------------------
# Instrumentation
# ---------------------------------------------------------------------------


def _instrument_isabelle_source(source: str) -> "tuple[str, int, int]":
    """Insert a `print_state` Isar diagnostic command directly before the
    last `sorry` occurrence, so `isabelle process` dumps the exact goal
    state at that point. Returns the instrumented source plus the
    1-indexed line / 0-indexed column of the *original* `sorry` token."""

    matches = list(_SORRY_RE.finditer(source))
    if not matches:
        raise GoalCaptureError("no `sorry` token found to instrument")
    match = matches[-1]
    start = match.start()

    line = source.count("\n", 0, start) + 1
    last_newline = source.rfind("\n", 0, start)
    column = start - (last_newline + 1)

    line_start = last_newline + 1
    indent_match = re.match(r"[ \t]*", source[line_start:start])
    indent = indent_match.group(0) if indent_match else ""

    instrumented = source[:line_start] + f"{indent}print_state\n" + source[line_start:]
    return instrumented, line, column


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _first_enumerated_goal(goals_block: str) -> Optional[str]:
    for raw_line in goals_block.split("\n"):
        match = _ENUMERATED_GOAL_RE.match(raw_line)
        if match and match.group(1) == "1":
            return match.group(2).strip()
    return None


def _parse_isabelle_hypotheses(combined_output: str, source: str) -> List[LocalHypothesis]:
    hypotheses: List[LocalHypothesis] = []

    using_match = _USING_THIS_RE.search(combined_output)
    if using_match:
        for raw_line in using_match.group("facts").split("\n"):
            fact = raw_line.strip()
            if not fact:
                continue
            hypotheses.append(LocalHypothesis(names=["this"], type_text=fact, raw=raw_line))

    for fix_match in _FIX_RE.finditer(source):
        raw = fix_match.group(0).strip()
        body = fix_match.group(1).strip()
        if "::" in body:
            names_part, _, type_part = body.partition("::")
        elif ":" in body:
            names_part, _, type_part = body.partition(":")
        else:
            names_part, type_part = body, ""
        names = [n.strip() for n in names_part.split() if n.strip()]
        if not names:
            continue
        hypotheses.append(
            LocalHypothesis(names=names, type_text=type_part.strip() or "(fixed)", raw=raw)
        )

    return hypotheses


def _extract_isabelle_imports(source: str) -> List[str]:
    imports: List[str] = []
    for match in _IMPORTS_RE.finditer(source):
        imports.extend(part.strip() for part in match.group(1).split() if part.strip())
    return imports


def _extract_isabelle_universe_context(
    hypotheses: List[LocalHypothesis], goal_text: str
) -> UniverseContext:
    # Isabelle/HOL is simply typed (no dependent universes); "Type"/"Sort"
    # style polymorphism is expressed through type variables (`'a`, `'b`)
    # rather than universe levels. We surface those type variables (parsed
    # directly from the captured hypotheses/goal, never invented) as the
    # closest analogue of a "universe/type context" for this ITP.
    type_vars: List[str] = []
    seen = set()
    for text in [h.type_text for h in hypotheses] + [goal_text]:
        for token in re.findall(r"'\w+", text):
            if token not in seen:
                seen.add(token)
                type_vars.append(token)

    if type_vars:
        notes = (
            "Isabelle/HOL has no dependent universe hierarchy; the type "
            "variables above were observed directly in the captured "
            "hypotheses/goal text (Isabelle's polymorphism mechanism)."
        )
    else:
        notes = (
            "No polymorphic type variables observed; Isabelle/HOL has no "
            "dependent universe hierarchy."
        )

    return UniverseContext(parameters=type_vars, type_bindings={}, notes=notes)
