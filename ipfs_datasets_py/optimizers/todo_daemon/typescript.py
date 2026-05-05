"""Reusable TypeScript proposal repair helpers for optimizer todo daemons."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from .engine import CommandResult, run_command


def repair_common_typescript_text_damage(content: str) -> str:
    """Repair recurring low-risk TypeScript damage from JSON file proposals."""

    if not isinstance(content, str) or not content:
        return content
    repaired = content
    generic_defaults = {
        "Array": "Array<unknown>",
        "Record": "Record<string, unknown>",
        "Map": "Map<string, unknown>",
        "Set": "Set<unknown>",
        "ReadonlySet": "ReadonlySet<unknown>",
        "Promise": "Promise<unknown>",
    }
    for name, replacement in generic_defaults.items():
        repaired = re.sub(rf"\b{name}\s*>(?!>)", replacement, repaired)
        repaired = re.sub(rf"\b{name}\b(?!\s*<)(?=\s*(?:[;=,){{}}]|$))", replacement, repaired)
    repaired = re.sub(r"\bOmit\s*>(?!>)", "Omit<Record<string, unknown>, string>", repaired)
    repaired = re.sub(r"\bOmit\b(?!\s*<)(?=\s*(?:[;=,){}]|$))", "Omit<Record<string, unknown>, string>", repaired)

    repaired = re.sub(r"\|\|\s*position\s+left\s*-\s*right\);", "|| position < 0) {", repaired)
    repaired = re.sub(r"\|\|\s*position\s+\{", "|| position < 0) {", repaired)
    repaired = re.sub(r"\|\|\s*Number\(([^)]+)\)\s+typeof\b", r"|| Number(\1) < 0 || typeof", repaired)
    repaired = re.sub(r"\|\|\s*Number\(([^)]+)\)\s+\{", r"|| Number(\1) < 0) {", repaired)
    repaired = re.sub(r"\|\|\s*weight\s+\)", "|| weight < 0)", repaired)
    repaired = re.sub(
        r"(?P<prefix>!\s*Number\.isInteger\((?P<var>[A-Za-z_$][\w$]*)\)\s*\|\|\s*)"
        r"(?P=var)\s+(?P<bound>[A-Z_$][A-Z0-9_$]*)",
        r"\g<prefix>\g<var> > \g<bound>",
        repaired,
    )
    repaired = re.sub(
        r"!\((?P<var>[A-Za-z_$][\w$]*)\s+(?P<bound>[A-Z_$][A-Z0-9_$]*)\)",
        r"!(\g<var> > \g<bound>)",
        repaired,
    )
    repaired = re.sub(
        r"for \(let index = 0; index = ([A-Za-z_$][\w$.]*\.length);",
        r"for (let index = 0; index < \1;",
        repaired,
    )
    repaired = re.sub(
        r"for \(let (?P<var>[A-Za-z_$][\w$]*) = (?P<start>\d+); "
        r"(?P=var)\s+(?P<bound>[A-Za-z_$][\w$.]*\.length);",
        r"for (let \g<var> = \g<start>; \g<var> < \g<bound>;",
        repaired,
    )
    repaired = re.sub(
        r"while \((?P<var>[A-Za-z_$][\w$]*)\s+(?P<bound>[A-Za-z_$][\w$.]*\.length)\)",
        r"while (\g<var> < \g<bound>)",
        repaired,
    )
    repaired = re.sub(
        r"while \((?P<var>[A-Za-z_$][\w$]*)\s+(?P<bound>[A-Za-z_$][\w$.]*\.length)\s+&&",
        r"while (\g<var> < \g<bound> &&",
        repaired,
    )
    repaired = re.sub(
        r"if \((?P<var>[A-Za-z_$][\w$]*) = (?P<bound>[A-Za-z_$][\w$.]*\.length) \|\|",
        r"if (\g<var> >= \g<bound> ||",
        repaired,
    )
    repaired = re.sub(
        r"for \(let index = 1; index \): number \{",
        "for (let index = 1; index < utterances.length; index += 1) {",
        repaired,
    )
    repaired = re.sub(r"for \(let index = 0; index >> 0\)\.toString", "return (hash >>> 0).toString", repaired)
    repaired = re.sub(
        r"(?P<prefix>\b(?:const|let)\s+"
        r"(?:parts|tokens|lines|symbols|orderedSymbols|sortedSymbols|errors|warnings|commands|logics)"
        r"\s*:\s*)Array<unknown>(?P<suffix>\s*=\s*\[\s*\])",
        r"\g<prefix>Array<string>\g<suffix>",
        repaired,
    )
    repaired = re.sub(
        r"(?P<prefix>\b(?:const|let)\s+[A-Za-z_$][\w$]*\s*:\s*)"
        r"Array<unknown>(?P<suffix>\s*=\s*\[(?:\s*['\"][^'\"]*['\"]\s*,?)*\s*\])",
        r"\g<prefix>Array<string>\g<suffix>",
        repaired,
    )
    repaired = re.sub(
        r"(?P<prefix>\b(?:const|let)\s+[A-Za-z_$][\w$]*\s*:\s*)"
        r"Array<unknown>(?P<suffix>\s*=\s*Object\.keys\()",
        r"\g<prefix>Array<string>\g<suffix>",
        repaired,
    )
    return repaired


def repair_common_typescript_file_edits(edits: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    """Repair TypeScript/TSX complete-file edits while preserving non-TS edits."""

    repaired: List[Dict[str, str]] = []
    for edit in edits:
        path = str(edit.get("path", ""))
        content = edit.get("content", "")
        if path.endswith((".ts", ".tsx")) and isinstance(content, str):
            repaired.append({**edit, "content": repair_common_typescript_text_damage(content)})
        else:
            repaired.append(dict(edit))
    return repaired


def typescript_format_pathspecs(paths: Sequence[str | Path], *, root: Optional[Path] = None) -> List[str]:
    """Return unique TS/TSX pathspecs suitable for formatting commands."""

    pathspecs: List[str] = []
    seen: set[str] = set()
    for path in paths:
        candidate = Path(path)
        if root is not None and candidate.is_absolute():
            try:
                text = candidate.relative_to(root).as_posix()
            except ValueError:
                text = candidate.as_posix()
        else:
            text = str(path).replace("\\", "/").strip()
        if not text or not text.endswith((".ts", ".tsx")) or text in seen:
            continue
        seen.add(text)
        pathspecs.append(text)
    return pathspecs


def format_typescript_paths(
    root: Path,
    paths: Sequence[str | Path],
    *,
    timeout_seconds: int = 120,
    run_command_fn: Callable[..., CommandResult] = run_command,
) -> Optional[CommandResult]:
    """Run Prettier for TS/TSX paths relative to ``root`` when there is work to format."""

    pathspecs = typescript_format_pathspecs(paths, root=root)
    if not pathspecs:
        return None
    return run_command_fn(
        ("npx", "prettier", "--write", *pathspecs),
        cwd=root,
        timeout_seconds=timeout_seconds,
    )


def obvious_typescript_text_damage(content: str) -> List[str]:
    """Return deterministic diagnostics for recurring malformed TS proposal text."""

    if not isinstance(content, str) or not content:
        return []
    findings: List[str] = []
    patterns = (
        (
            "missing comparison operator before .length",
            re.compile(r"\b(?:index|offset|position|cursor|start|end|count|arity)\s{2,}[A-Za-z_$][\w$.]*\.length\b"),
        ),
        (
            "missing comparison operator before a numeric bound",
            re.compile(r"\b(?:index|offset|position|cursor|start|end|count|arity|weight|score)\s{2,}\d+\b"),
        ),
        (
            "missing comparison operator before a string literal",
            re.compile(r"\b(?:arity|sort|kind|type|name|label|operation)\s{2,}['\"][^'\"]+['\"]"),
        ),
        (
            "bare TypeScript generic alias",
            re.compile(r"\b(?:Record|Array|Promise|Omit|Pick|Map|Set|ReadonlySet)\s*(?=[=;,){}]|$)"),
        ),
    )
    for line_number, line in enumerate(content.splitlines(), start=1):
        for label, pattern in patterns:
            if pattern.search(line):
                findings.append(f"line {line_number}: {label}: {line.strip()[:220]}")
                break
        if len(findings) >= 12:
            break
    return findings
