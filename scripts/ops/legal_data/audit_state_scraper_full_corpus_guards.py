#!/usr/bin/env python3
"""Audit state scrapers for full-corpus truncation hazards.

This is a static tripwire for the failure mode where a scraper returns a tiny
seed/direct recovery set while the daemon is running in full-corpus mode. It is
intentionally conservative: it reports suspicious returns and hard discovery
caps so maintainers can either fix them or document why they are safe.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


STATE_MODULES = {
    "AL": "alabama",
    "AK": "alaska",
    "AZ": "arizona",
    "AR": "arkansas",
    "CA": "california",
    "CO": "colorado",
    "CT": "connecticut",
    "DE": "delaware",
    "FL": "florida",
    "GA": "georgia",
    "HI": "hawaii",
    "ID": "idaho",
    "IL": "illinois",
    "IN": "indiana",
    "IA": "iowa",
    "KS": "kansas",
    "KY": "kentucky",
    "LA": "louisiana",
    "ME": "maine",
    "MD": "maryland",
    "MA": "massachusetts",
    "MI": "michigan",
    "MN": "minnesota",
    "MS": "mississippi",
    "MO": "missouri",
    "MT": "montana",
    "NE": "nebraska",
    "NV": "nevada",
    "NH": "new_hampshire",
    "NJ": "new_jersey",
    "NM": "new_mexico",
    "NY": "new_york",
    "NC": "north_carolina",
    "ND": "north_dakota",
    "OH": "ohio",
    "OK": "oklahoma",
    "OR": "oregon",
    "PA": "pennsylvania",
    "RI": "rhode_island",
    "SC": "south_carolina",
    "SD": "south_dakota",
    "TN": "tennessee",
    "TX": "texas",
    "UT": "utah",
    "VT": "vermont",
    "VA": "virginia",
    "WA": "washington",
    "WV": "west_virginia",
    "WI": "wisconsin",
    "WY": "wyoming",
}

DEFAULT_STATE_LIST = ",".join(STATE_MODULES)
SUSPICIOUS_RETURN_NAMES = (
    "seed",
    "direct",
    "recovery",
    "archival",
    "fallback",
    "api_statutes",
    "live",
)


@dataclass
class Finding:
    state: str
    path: str
    line: int
    kind: str
    detail: str
    severity: str = "warning"

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "path": self.path,
            "line": self.line,
            "kind": self.kind,
            "severity": self.severity,
            "detail": self.detail,
        }


class ParentAnnotator(ast.NodeVisitor):
    def visit(self, node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            setattr(child, "_parent", node)
        super().visit(node)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _scraper_root(repo_root: Path) -> Path:
    return repo_root / "ipfs_datasets_py" / "processors" / "legal_scrapers" / "state_scrapers"


def _states(value: str) -> list[str]:
    if value.strip().lower() == "all":
        return list(STATE_MODULES)
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def _expr_text(source: str, node: ast.AST) -> str:
    try:
        return ast.get_source_segment(source, node) or ast.unparse(node)
    except Exception:
        return ""


def _nameish(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Subscript):
        return _nameish(node.value)
    if isinstance(node, ast.Call):
        return _nameish(node.func)
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.BoolOp):
        return " ".join(_nameish(value) for value in node.values)
    if isinstance(node, ast.IfExp):
        return f"{_nameish(node.body)} {_nameish(node.orelse)}"
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return " ".join(_nameish(value) for value in node.elts)
    return ""


def _mentions_suspicious_seed(node: ast.AST) -> bool:
    text = _nameish(node).lower()
    return any(token in text for token in SUSPICIOUS_RETURN_NAMES)


def _is_full_corpus_guard(source: str, node: ast.AST) -> bool:
    text = _expr_text(source, node).replace(" ", "")
    return (
        "notself._full_corpus_enabled()" in text
        or "notself._full_corpus_enabled()ormax_statutesisnotNone" in text
        or "self._full_corpus_enabled()else" in text
        or "max_statutesisnotNone" in text
        or "limitisnotNone" in text
        or "max_statutesisNone" in text
        or "limitisNone" in text
        or "return_threshold<" in text
        or "len(" in text and ">=return_threshold" in text
    )


def _ancestor_ifs(node: ast.AST) -> Iterable[ast.If]:
    parent = getattr(node, "_parent", None)
    while parent is not None:
        if isinstance(parent, ast.If):
            yield parent
        parent = getattr(parent, "_parent", None)


def _guarded_for_non_full_corpus(source: str, node: ast.AST) -> bool:
    return any(_is_full_corpus_guard(source, item.test) for item in _ancestor_ifs(node))


def _safe_unbounded_api_return(source: str, node: ast.Return) -> bool:
    """Recognize API walks whose max_statutes becomes None in full-corpus mode."""
    detail = _expr_text(source, node).replace(" ", "")
    if detail != "returnapi_statutes":
        return False
    function = getattr(node, "_parent", None)
    while function is not None and not isinstance(function, (ast.AsyncFunctionDef, ast.FunctionDef)):
        function = getattr(function, "_parent", None)
    if function is None:
        return False
    body = _expr_text(source, function).replace(" ", "")
    return (
        "limit=self._effective_scrape_limit(" in body
        and "max_api_statutes=limitiflimitisnotNoneelseNone" in body
        and "self._scrape_statutes_api(" in body
        and "max_statutes=max_api_statutes" in body
    )


def _iter_scrape_code_returns(tree: ast.AST) -> Iterable[ast.Return]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "scrape_code":
            for child in ast.walk(node):
                if isinstance(child, ast.Return):
                    yield child


def _line_has_full_corpus_branch(line: str) -> bool:
    compact = line.replace(" ", "")
    return (
        "self._full_corpus_enabled()else" in compact
        or "ifnotself._full_corpus_enabled()" in compact
        or "iflimitisNoneelse" in compact
    )


def audit_file(*, state: str, path: Path, repo_root: Path) -> list[Finding]:
    source = path.read_text(encoding="utf-8")
    rel = str(path.relative_to(repo_root))
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [
            Finding(
                state=state,
                path=rel,
                line=int(exc.lineno or 1),
                kind="syntax_error",
                severity="error",
                detail=str(exc),
            )
        ]

    ParentAnnotator().visit(tree)
    findings: list[Finding] = []
    for ret in _iter_scrape_code_returns(tree):
        if ret.value is None or not _mentions_suspicious_seed(ret.value):
            continue
        if _guarded_for_non_full_corpus(source, ret):
            continue
        if _safe_unbounded_api_return(source, ret):
            continue
        detail = _expr_text(source, ret).strip()
        lowered = detail.lower()
        severity = "error" if "direct" in lowered or "seed" in lowered else "warning"
        findings.append(
            Finding(
                state=state,
                path=rel,
                line=int(getattr(ret, "lineno", 1) or 1),
                kind="unguarded_seed_or_recovery_return",
                severity=severity,
                detail=detail,
            )
        )

    lines = source.splitlines()
    hard_slice_re = re.compile(r"\[[^\\]]*:\s*[0-9]{1,4}\]")
    literal_keyword_re = re.compile(r"\b(?:max_sections|max_statutes|limit)\s*=\s*[0-9]{1,5}\b")
    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "section_name" in stripped or "full_text" in stripped or "[:1200]" in stripped or "[:14000]" in stripped:
            continue
        if hard_slice_re.search(stripped) and not _line_has_full_corpus_branch(stripped):
            findings.append(
                Finding(
                    state=state,
                    path=rel,
                    line=line_number,
                    kind="hard_slice_cap",
                    detail=stripped,
                )
            )
        if literal_keyword_re.search(stripped) and not _line_has_full_corpus_branch(stripped):
            findings.append(
                Finding(
                    state=state,
                    path=rel,
                    line=line_number,
                    kind="literal_discovery_cap",
                    detail=stripped,
                )
            )
    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--states", default=DEFAULT_STATE_LIST, help="Comma-separated states or 'all'.")
    parser.add_argument("--repo-root", default="", help="Repository root override.")
    parser.add_argument("--json", action="store_true", help="Emit JSON report.")
    parser.add_argument("--fail-on-warnings", action="store_true", help="Exit nonzero for warning findings too.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve() if args.repo_root else _repo_root()
    scraper_root = _scraper_root(repo_root)
    requested_states = _states(str(args.states))

    findings: list[Finding] = []
    missing: list[str] = []
    for state in requested_states:
        module = STATE_MODULES.get(state)
        if not module:
            missing.append(state)
            continue
        path = scraper_root / f"{module}.py"
        if not path.exists():
            missing.append(state)
            continue
        findings.extend(audit_file(state=state, path=path, repo_root=repo_root))

    error_count = sum(1 for item in findings if item.severity == "error")
    warning_count = sum(1 for item in findings if item.severity == "warning")
    report = {
        "status": "fail" if error_count or (warning_count and args.fail_on_warnings) or missing else "pass",
        "states_checked": len(requested_states) - len(missing),
        "missing_states": missing,
        "error_count": error_count,
        "warning_count": warning_count,
        "findings": [item.to_dict() for item in findings],
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"status: {report['status']}")
        print(f"states_checked: {report['states_checked']}")
        print(f"missing_states: {','.join(missing) if missing else '-'}")
        print(f"errors: {error_count}")
        print(f"warnings: {warning_count}")
        for item in findings:
            print(f"{item.severity.upper()} {item.state} {item.path}:{item.line} {item.kind}: {item.detail}")

    if missing or error_count:
        return 1
    if warning_count and args.fail_on_warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
