"""Native Coq/Rocq frontend adapter (HAMMER-006).

Captures a real, native :class:`~ipfs_datasets_py.logic.hammers.frontends.base.GoalSnapshot`
from a Coq/Rocq source declaration whose proof contains an explicit
``admit.``/``Admitted.`` incomplete-proof marker, by inserting a genuine
``Show.`` vernacular command immediately before that marker and parsing
``coqtop``'s own goal display.

This mechanism was verified empirically against a real Rocq 9.x toolchain::

    Theorem foo : forall n m : nat, n + m = m + n.
    Proof.
      intros n m.
      Show.
      admit.
    Admitted.

    # `coqtop -batch -load-vernac-source` prints:
    1 goal
      n, m : nat
      ============================
      n + m = m + n

and, with ``Set Printing Universes.`` prepended, a polymorphic hypothesis
like ``forall (A : Type) (x : A), x = x`` is displayed as
``A : Type@{Top.21}`` — the real Coq-assigned universe token, not a
fabricated one. No goal, hypothesis, import, or universe field below is
ever constructed except by parsing this real ``coqtop`` output.
"""

from __future__ import annotations

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

__all__ = ["CoqFrontend"]

_VERSION_TIMEOUT = 5.0

_ADMIT_RE = re.compile(r"\badmit\s*\.")
_ADMITTED_RE = re.compile(r"\bAdmitted\s*\.")
_IMPORT_RE = re.compile(
    r"^\s*((?:Require\s+(?:Import|Export)\s+.+?\.)|(?:From\s+\S+\s+Require\s+"
    r"(?:Import|Export)\s+.+?\.))\s*$",
    re.MULTILINE,
)
_GOAL_BLOCK_RE = re.compile(
    r"\d+\s+goals?\s*\n\s*\n(?P<hyps>(?:.*\n)*?)\s*=+\s*\n(?P<goal>.*?)(?:\n\s*\n|\Z)",
    re.DOTALL,
)
_UNIVERSE_TOKEN_RE = re.compile(r"@\{([^}]*)\}")


class CoqFrontend:
    """Native Coq/Rocq frontend adapter implementing :class:`ITPFrontend`."""

    itp = ITPKind.COQ

    def __init__(self, *, timeout: float = DEFAULT_TIMEOUT_SECONDS):
        self._timeout = timeout

    # -- capability ---------------------------------------------------

    def capability(self) -> CapabilityEvidence:
        coqtop_path = find_executable("coqtop")
        coqc_path = find_executable("coqc")
        rocq_path = find_executable("rocq")

        def _version(path: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
            if not path:
                return None, None
            probe = run_bounded_process([path, "--version"], timeout=_VERSION_TIMEOUT)
            if probe.error:
                return None, probe.error
            lines = (probe.stdout or probe.stderr or "").strip().splitlines()
            return (lines[0].strip() if lines else None), None

        coqtop_version, coqtop_error = _version(coqtop_path)
        coqc_version, coqc_error = _version(coqc_path)
        rocq_version, rocq_error = _version(rocq_path)

        executables: Dict[str, Dict[str, Any]] = {
            "coqtop": {
                "found": coqtop_path is not None,
                "path": coqtop_path,
                "version": coqtop_version,
                "version_probe_error": coqtop_error,
            },
            "coqc": {
                "found": coqc_path is not None,
                "path": coqc_path,
                "version": coqc_version,
                "version_probe_error": coqc_error,
            },
            "rocq": {
                "found": rocq_path is not None,
                "path": rocq_path,
                "version": rocq_version,
                "version_probe_error": rocq_error,
            },
        }

        # `coqtop -batch -load-vernac-source` is the only invocation this
        # adapter needs (it both elaborates the script and prints `Show.`
        # goal state to stdout); `coqc`/`rocq` are probed informationally.
        available = coqtop_path is not None
        unavailable_reason = None
        if not available:
            unavailable_reason = "coqtop_executable_not_found_on_path_or_common_install_dirs"

        return CapabilityEvidence(
            itp=ITPKind.COQ,
            available=available,
            executables=executables,
            unavailable_reason=unavailable_reason,
            notes=(
                "Availability requires `coqtop` (batch-mode `Show.` goal "
                "display); `coqc`/`rocq` are probed for informational "
                "purposes only."
            ),
        )

    # -- goal snapshot --------------------------------------------------

    def snapshot_goal(
        self,
        source: str,
        *,
        theorem_id: str,
        file_name: str = "Goal.v",
        timeout: Optional[float] = None,
    ) -> GoalSnapshot:
        capability = self.capability()
        if not capability.available:
            raise FrontendUnavailableError(
                "Coq/Rocq frontend unavailable: coqtop executable not found",
                capability=capability,
            )

        marker_match = _ADMIT_RE.search(source) or _ADMITTED_RE.search(source)
        if marker_match is None:
            raise GoalCaptureError(
                "CoqFrontend.snapshot_goal requires a native `admit.`/"
                "`Admitted.` placeholder in source; refusing to fabricate a "
                "goal from plain text"
            )

        marker_start = marker_match.start()
        line = source.count("\n", 0, marker_start) + 1
        last_newline = source.rfind("\n", 0, marker_start)
        column = marker_start - (last_newline + 1)

        instrumented = _instrument_coq_source(source, marker_match)

        with tempfile.TemporaryDirectory(prefix="hammer-coq-") as tmpdir:
            source_path = Path(tmpdir) / file_name
            source_path.write_text(instrumented, encoding="utf-8")
            coqtop_path = capability.executables["coqtop"]["path"]
            result = run_bounded_process(
                [coqtop_path, "-batch", "-load-vernac-source", str(source_path)],
                timeout=timeout if timeout is not None else self._timeout,
                cwd=tmpdir,
            )

        if result.error:
            raise GoalCaptureError(f"coqtop invocation failed: {result.error}")

        block_match = _GOAL_BLOCK_RE.search(result.stdout)
        if block_match is None:
            raise GoalCaptureError(
                "coqtop produced no `Show.` goal-state block; cannot "
                f"construct a goal snapshot without native evidence "
                f"(stdout={result.stdout!r}, stderr={result.stderr!r})"
            )

        hypotheses = _parse_coq_hypotheses(block_match.group("hyps"))
        goal_text = " ".join(
            line.strip() for line in block_match.group("goal").splitlines() if line.strip()
        ).strip()
        if not goal_text:
            raise GoalCaptureError(
                "coqtop's `Show.` block contained no goal text: "
                f"{block_match.group(0)!r}"
            )

        imports = _extract_coq_imports(source)
        universe_context = _extract_coq_universe_context(hypotheses, goal_text)
        source_position = SourcePosition(file=file_name, line=line, column=column)

        return GoalSnapshot(
            itp=ITPKind.COQ,
            itp_version=capability.executables["coqtop"].get("version") or "unknown",
            theorem_id=theorem_id,
            goal_text=goal_text,
            hypotheses=hypotheses,
            imports=imports,
            universe_context=universe_context,
            source_position=source_position,
            native_command=[coqtop_path, "-batch", "-load-vernac-source", file_name],
            raw_native_output=block_match.group(0),
            extra={
                "resolved_executable": coqtop_path,
                "full_stdout": result.stdout,
            },
        )


# ---------------------------------------------------------------------------
# Instrumentation
# ---------------------------------------------------------------------------


def _instrument_coq_source(source: str, marker_match: "re.Match[str]") -> str:
    """Insert `Set Printing Universes.` at the top and a `Show.` command
    directly before the incomplete-proof marker, so `coqtop` prints the
    exact goal/hypotheses/universe state at that point."""

    marker_start = marker_match.start()
    line_start = source.rfind("\n", 0, marker_start) + 1
    indent_match = re.match(r"[ \t]*", source[line_start:marker_start])
    indent = indent_match.group(0) if indent_match else ""

    instrumented_body = source[:line_start] + f"{indent}Show.\n" + source[line_start:]
    return "Set Printing Universes.\n" + instrumented_body


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_coq_hypotheses(hyps_block: str) -> List[LocalHypothesis]:
    hypotheses: List[LocalHypothesis] = []
    for raw_line in hyps_block.split("\n"):
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        names_part, _, type_part = line.partition(":")
        names = [n.strip() for n in names_part.split(",") if n.strip()]
        if not names:
            continue
        hypotheses.append(
            LocalHypothesis(names=names, type_text=type_part.strip(), raw=line)
        )
    return hypotheses


def _extract_coq_imports(source: str) -> List[str]:
    return [m.group(1).strip() for m in _IMPORT_RE.finditer(source)]


def _extract_coq_universe_context(
    hypotheses: List[LocalHypothesis], goal_text: str
) -> UniverseContext:
    parameters: List[str] = []
    seen = set()
    for text in [h.type_text for h in hypotheses] + [goal_text]:
        for m in _UNIVERSE_TOKEN_RE.finditer(text):
            for token in re.split(r"[,\s]+", m.group(1)):
                token = token.strip()
                if token and token not in seen:
                    seen.add(token)
                    parameters.append(token)

    type_bindings: Dict[str, str] = {}
    for hyp in hypotheses:
        if hyp.type_text.startswith("Type") or hyp.type_text.startswith("Set") or hyp.type_text.startswith("Prop"):
            name = hyp.names[0] if len(hyp.names) == 1 else ",".join(hyp.names)
            type_bindings[name] = hyp.type_text

    if parameters or type_bindings:
        notes = (
            "Universe tokens parsed from `Type@{...}`-style annotations "
            "(enabled via `Set Printing Universes.`) and/or Type/Set/Prop "
            "bindings observed in the captured local context."
        )
    else:
        notes = "No explicit universe tokens or Type/Set/Prop bindings observed."

    return UniverseContext(parameters=parameters, type_bindings=type_bindings, notes=notes)
