"""Native Isabelle/HOL frontend adapter (HAMMER-006).

Captures a real, native :class:`~ipfs_datasets_py.logic.hammers.frontends.base.GoalSnapshot`
from an Isabelle/HOL theory whose proof contains an explicit ``sorry``
incomplete-proof marker, by inserting a genuine Isar ``print_state``
diagnostic command immediately before that marker and parsing
``isabelle process``'s own goal-state output (the Isar reference manual's
documented mechanism for dumping the current proof state — the direct
analogue of Lean's placeholder-hole diagnostic and Coq/Rocq's ``Show.``).

Environment status
-------------------
Per ``docs/logic/itp_hammer_capability_inventory.md`` (HAMMER-002), this
repository's probed environments have **no** ``isabelle`` executable and no
prior Isabelle bridge module at all — Isabelle is the one ITP confirmed
fully ``unavailable`` there. This adapter therefore cannot be exercised
against a live Isabelle toolchain in this checkout; :meth:`capability`
reflects that honestly (``available=False`` with a structured reason) rather
than ever short-circuiting to a fabricated snapshot. The instrumentation and
parsing logic below is written to the same non-fabrication contract as
:mod:`.lean` and :mod:`.coq` (never invents a goal from plain text; only
ever parses genuine ``isabelle process`` diagnostic output) and its unit
coverage in ``tests/integration/logic/hammers/test_itp_frontends.py``
exercises it against a synthetic, format-accurate ``isabelle process``
transcript with the real subprocess call replaced — never against invented
"available" behavior in this environment.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.logic.external_provers.lazy_installer import find_executable

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
    run_bounded_process,
)

__all__ = ["IsabelleFrontend"]

_VERSION_TIMEOUT = 5.0

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

    def __init__(self, *, timeout: float = DEFAULT_TIMEOUT_SECONDS):
        self._timeout = timeout

    # -- capability ---------------------------------------------------

    def capability(self) -> CapabilityEvidence:
        isabelle_path = find_executable("isabelle")

        version: Optional[str] = None
        version_error: Optional[str] = None
        if isabelle_path:
            probe = run_bounded_process([isabelle_path, "version"], timeout=_VERSION_TIMEOUT)
            if probe.error:
                version_error = probe.error
            else:
                lines = (probe.stdout or probe.stderr or "").strip().splitlines()
                version = lines[0].strip() if lines else None

        executables: Dict[str, Dict[str, Any]] = {
            "isabelle": {
                "found": isabelle_path is not None,
                "path": isabelle_path,
                "version": version,
                "version_probe_error": version_error,
            }
        }

        available = isabelle_path is not None
        unavailable_reason = None
        if not available:
            unavailable_reason = (
                "isabelle_executable_not_found_on_path_or_common_install_dirs"
            )

        return CapabilityEvidence(
            itp=ITPKind.ISABELLE,
            available=available,
            executables=executables,
            unavailable_reason=unavailable_reason,
            notes=(
                "Availability requires the `isabelle` launcher (`isabelle "
                "process -T <theory> -d <dir>`, used to elaborate the "
                "instrumented theory and parse its native `print_state` "
                "goal display). No Isabelle bridge/frontend previously "
                "existed in this repository (HAMMER-002 capability "
                "inventory); this is the first."
            ),
        )

    # -- goal snapshot --------------------------------------------------

    def snapshot_goal(
        self,
        source: str,
        *,
        theorem_id: str,
        file_name: str = "Goal.thy",
        timeout: Optional[float] = None,
    ) -> GoalSnapshot:
        capability = self.capability()
        if not capability.available:
            raise FrontendUnavailableError(
                "Isabelle frontend unavailable: isabelle executable not found",
                capability=capability,
            )

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
        theory_name = theory_match.group(1)
        resolved_file_name = f"{theory_name}.thy"

        instrumented, marker_line, marker_col = _instrument_isabelle_source(source)

        with tempfile.TemporaryDirectory(prefix="hammer-isabelle-") as tmpdir:
            source_path = Path(tmpdir) / resolved_file_name
            source_path.write_text(instrumented, encoding="utf-8")
            isabelle_path = capability.executables["isabelle"]["path"]
            result = run_bounded_process(
                [isabelle_path, "process", "-T", theory_name, "-d", tmpdir],
                timeout=timeout if timeout is not None else self._timeout,
                cwd=tmpdir,
            )

        if result.error:
            raise GoalCaptureError(f"isabelle process invocation failed: {result.error}")

        combined_output = result.stdout + "\n" + result.stderr
        block_match = _GOAL_BLOCK_RE.search(combined_output)
        if block_match is None:
            raise GoalCaptureError(
                "isabelle process produced no `goal (N subgoals):` block "
                "after `print_state`; cannot construct a goal snapshot "
                f"without native evidence (stdout={result.stdout!r}, "
                f"stderr={result.stderr!r})"
            )

        goal_text = _first_enumerated_goal(block_match.group("goals"))
        if goal_text is None:
            raise GoalCaptureError(
                f"isabelle process goal block had no enumerated subgoal: "
                f"{block_match.group(0)!r}"
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
            native_command=[isabelle_path, "process", "-T", theory_name, "-d", "."],
            raw_native_output=block_match.group(0),
            extra={
                "resolved_executable": isabelle_path,
                "theory_name": theory_name,
                "full_output": combined_output,
            },
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
