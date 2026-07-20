"""Native Lean 4 frontend adapter (HAMMER-006).

Captures a real, native :class:`~ipfs_datasets_py.logic.hammers.frontends.base.GoalSnapshot`
from a Lean 4 source declaration whose proof contains an explicit ``sorry``
placeholder, by instrumenting that source with a genuine Lean elaboration
hole (``_``) and parsing Lean's own ``don't know how to synthesize
placeholder`` / ``context:`` diagnostic (emitted via ``lean --json``).

This mechanism was verified empirically against a real Lean 4 toolchain::

    theorem foo (n : Nat) (h : n > 0) : n ≠ 0 := _

    # `lean --json` emits:
    {"data": "don't know how to synthesize placeholder\\n
              context:\\nn : Nat\\nh : n > 0\\n⊢ n ≠ 0",
     "kind": "Elab.synthPlaceholder", "severity": "error", ...}

and, for a tactic-mode proof, replacing the trailing ``sorry`` tactic with
``exact _`` produces the same ``Elab.synthPlaceholder`` diagnostic carrying
the tactic-mode local context. No goal, hypothesis, import, or universe
field below is ever constructed except by parsing this real diagnostic text.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

__all__ = ["LeanFrontend"]

_VERSION_TIMEOUT = 5.0

_SORRY_RE = re.compile(r"\bsorry\b")
_IMPORT_RE = re.compile(r"^\s*import\s+(\S+)\s*$", re.MULTILINE)
_UNIVERSE_BINDER_RE = re.compile(r"(?:theorem|lemma|def|example)\s+\S*\.\{([^}]*)\}")
_TYPE_SORT_RE = re.compile(r"\b(?:Type|Sort)\b(?:\s+[\w'.]+)?")
_CONTEXT_SPLIT_RE = re.compile(r"context:\n", re.MULTILINE)
_GOAL_LINE_RE = re.compile(r"^⊢\s?(.*)$")


class LeanFrontend:
    """Native Lean 4 frontend adapter implementing :class:`ITPFrontend`."""

    itp = ITPKind.LEAN

    def __init__(self, *, timeout: float = DEFAULT_TIMEOUT_SECONDS):
        self._timeout = timeout

    # -- capability ---------------------------------------------------

    def capability(self) -> CapabilityEvidence:
        lean_path = find_executable("lean")
        lake_path = find_executable("lake")

        lean_version: Optional[str] = None
        lean_version_error: Optional[str] = None
        if lean_path:
            probe = run_bounded_process([lean_path, "--version"], timeout=_VERSION_TIMEOUT)
            if probe.error:
                lean_version_error = probe.error
            else:
                lines = (probe.stdout or probe.stderr or "").strip().splitlines()
                lean_version = lines[0].strip() if lines else None

        lake_version: Optional[str] = None
        lake_version_error: Optional[str] = None
        if lake_path:
            probe = run_bounded_process([lake_path, "--version"], timeout=_VERSION_TIMEOUT)
            if probe.error:
                lake_version_error = probe.error
            else:
                lines = (probe.stdout or probe.stderr or "").strip().splitlines()
                lake_version = lines[0].strip() if lines else None

        executables: Dict[str, Dict[str, Any]] = {
            "lean": {
                "found": lean_path is not None,
                "path": lean_path,
                "version": lean_version,
                "version_probe_error": lean_version_error,
            },
            "lake": {
                "found": lake_path is not None,
                "path": lake_path,
                "version": lake_version,
                "version_probe_error": lake_version_error,
            },
        }

        available = lean_path is not None
        unavailable_reason = None
        if not available:
            unavailable_reason = "lean_executable_not_found_on_path_or_common_install_dirs"

        return CapabilityEvidence(
            itp=ITPKind.LEAN,
            available=available,
            executables=executables,
            unavailable_reason=unavailable_reason,
            notes=(
                "Availability requires only the `lean` executable (used to "
                "elaborate the instrumented source and parse its native "
                "`Elab.synthPlaceholder` diagnostic); `lake` is probed for "
                "informational purposes but is not required for a snapshot."
            ),
        )

    # -- goal snapshot --------------------------------------------------

    def snapshot_goal(
        self,
        source: str,
        *,
        theorem_id: str,
        file_name: str = "Goal.lean",
        timeout: Optional[float] = None,
    ) -> GoalSnapshot:
        capability = self.capability()
        if not capability.available:
            raise FrontendUnavailableError(
                "Lean frontend unavailable: lean executable not found",
                capability=capability,
            )

        if not _SORRY_RE.search(source):
            raise GoalCaptureError(
                "LeanFrontend.snapshot_goal requires a native `sorry` "
                "placeholder in source; refusing to fabricate a goal from "
                "plain text"
            )

        instrumented, marker_line, marker_col = _instrument_lean_source(source)

        with tempfile.TemporaryDirectory(prefix="hammer-lean-") as tmpdir:
            source_path = Path(tmpdir) / file_name
            source_path.write_text(instrumented, encoding="utf-8")
            lean_path = capability.executables["lean"]["path"]
            result = run_bounded_process(
                [lean_path, "--json", str(source_path)],
                timeout=timeout if timeout is not None else self._timeout,
                cwd=tmpdir,
            )

        if result.error:
            raise GoalCaptureError(f"lean invocation failed: {result.error}")

        messages = _parse_json_lines(result.stdout)
        goal_message = _select_goal_message(messages)
        if goal_message is None:
            raise GoalCaptureError(
                "lean produced no `Elab.synthPlaceholder` diagnostic; "
                "cannot construct a goal snapshot without native evidence "
                f"(stdout={result.stdout!r}, stderr={result.stderr!r})"
            )

        hypotheses, goal_text = _parse_lean_context_block(goal_message["data"])
        if goal_text is None:
            raise GoalCaptureError(
                "lean's placeholder diagnostic did not contain a `context:` "
                f"block with a `⊢` goal line: {goal_message['data']!r}"
            )

        imports = _extract_lean_imports(source)
        universe_context = _extract_lean_universe_context(source, hypotheses)
        source_position = SourcePosition(file=file_name, line=marker_line, column=marker_col)

        return GoalSnapshot(
            itp=ITPKind.LEAN,
            itp_version=capability.executables["lean"].get("version") or "unknown",
            theorem_id=theorem_id,
            goal_text=goal_text,
            hypotheses=hypotheses,
            imports=imports,
            universe_context=universe_context,
            source_position=source_position,
            native_command=[lean_path, file_name],
            raw_native_output=goal_message["data"],
            extra={
                "lean_message_kind": goal_message.get("kind"),
                "lean_message_severity": goal_message.get("severity"),
                "resolved_executable": lean_path,
                "other_messages": [m for m in messages if m is not goal_message],
            },
        )


# ---------------------------------------------------------------------------
# Instrumentation
# ---------------------------------------------------------------------------


def _instrument_lean_source(source: str) -> Tuple[str, int, int]:
    """Replace the last ``sorry`` occurrence with a genuine elaboration hole
    (``_``) that Lean will report `Elab.synthPlaceholder` for, in both term
    and tactic position. Returns the instrumented source plus the 1-indexed
    line and 0-indexed column of the *original* ``sorry`` token (i.e. the
    goal's real position in the caller's source, independent of our
    instrumentation)."""

    matches = list(_SORRY_RE.finditer(source))
    if not matches:
        raise GoalCaptureError("no `sorry` token found to instrument")
    match = matches[-1]
    start, end = match.span()

    line = source.count("\n", 0, start) + 1
    last_newline = source.rfind("\n", 0, start)
    column = start - (last_newline + 1)

    # `sorry` is valid in both term position (`:= sorry`) and tactic
    # position (`by ... sorry`); `exact _` is a valid tactic-position
    # replacement and `_` alone is a valid term-position replacement. Detect
    # mode by checking whether a `by` keyword appears between the nearest
    # preceding `:=` and this occurrence.
    preceding = source[:start]
    last_assign = preceding.rfind(":=")
    between = preceding[last_assign + 2 :] if last_assign != -1 else preceding
    tactic_mode = re.search(r"\bby\b", between) is not None

    replacement = "exact _" if tactic_mode else "_"
    instrumented = source[:start] + replacement + source[end:]
    return instrumented, line, column


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_json_lines(stdout: str) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    for raw_line in stdout.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            messages.append(payload)
    return messages


def _select_goal_message(messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for message in messages:
        if message.get("kind") == "Elab.synthPlaceholder" and "context:" in str(
            message.get("data", "")
        ):
            return message
    return None


def _parse_lean_context_block(
    data: str,
) -> Tuple[List[LocalHypothesis], Optional[str]]:
    parts = _CONTEXT_SPLIT_RE.split(data, maxsplit=1)
    if len(parts) != 2:
        return [], None
    context_block = parts[1]
    lines = context_block.split("\n")

    hypotheses: List[LocalHypothesis] = []
    goal_text: Optional[str] = None
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line:
            continue
        goal_match = _GOAL_LINE_RE.match(line)
        if goal_match:
            goal_text = goal_match.group(1).strip()
            continue
        if ":" not in line:
            continue
        names_part, _, type_part = line.partition(":")
        names = [n.strip() for n in names_part.strip().split() if n.strip()]
        if not names:
            continue
        hypotheses.append(
            LocalHypothesis(names=names, type_text=type_part.strip(), raw=line.strip())
        )

    return hypotheses, goal_text


def _extract_lean_imports(source: str) -> List[str]:
    return [m.group(1) for m in _IMPORT_RE.finditer(source)]


def _extract_lean_universe_context(
    source: str, hypotheses: List[LocalHypothesis]
) -> UniverseContext:
    binder_match = _UNIVERSE_BINDER_RE.search(source)
    parameters: List[str] = []
    if binder_match:
        parameters = [
            p.strip() for p in re.split(r"[,\s]+", binder_match.group(1)) if p.strip()
        ]

    type_bindings: Dict[str, str] = {}
    for hyp in hypotheses:
        if _TYPE_SORT_RE.match(hyp.type_text):
            name = hyp.names[0] if len(hyp.names) == 1 else ",".join(hyp.names)
            type_bindings[name] = hyp.type_text

    if parameters or type_bindings:
        notes = (
            "Universe parameters parsed from the declaration's `.{...}` "
            "binder and/or `Type`/`Sort` bindings observed in the captured "
            "local context."
        )
    else:
        notes = "No explicit universe parameters or Type/Sort bindings observed."

    return UniverseContext(parameters=parameters, type_bindings=type_bindings, notes=notes)
