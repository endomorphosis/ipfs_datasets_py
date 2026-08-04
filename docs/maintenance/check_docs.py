#!/usr/bin/env python3
"""Deterministic offline documentation validator (DocumentationValidator@1).

Validates Markdown documentation without network access, without treating
filesystem mtimes as freshness proof, and without deleting generated output.

Checks (selectable via --checks):

* markdown_paths   – inventory of Markdown files under the scan root
* links            – relative Markdown links resolve to existing files
* anchors          – fragment anchors resolve to headings (or explicit ids)
* repo_paths       – backtick-cited repository paths resolve on the tree
* python_modules   – dotted module names and fence imports resolve on the tree
* metadata         – required metadata on pages declaring Status=canonical
                     (and evidence/plan as specified by the page contract)
* duplicates       – duplicate Interface ids among Status=canonical pages
* python_syntax    – fenced Python blocks parse under ast (stdlib)

Explicit allowlists cover archive trees and before-migration examples so
historical material does not fail the gate the same way maintained pages do.
Allowlisted findings are still reported when --report is used; they do not
fail the process unless --strict-allowlist is set.

Interface: DocumentationValidator@1
Task: IPFSDOC-006

Side-effect policy
------------------
* Read-only against the repository except optional report write (--report /
  --json-report). Report write creates or overwrites only the named report
  path(s); it never deletes other generated artifacts (site/, build outputs).
* External http(s)/mailto/etc. links are classified and skipped (no fetch).
* Freshness uses the in-document ``Last verified`` field only; mtime/ctime
  are never used as proof of currency.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

__version__ = "1.0.0"
INTERFACE_ID = "DocumentationValidator@1"
TASK_ID = "IPFSDOC-006"

# ---------------------------------------------------------------------------
# Allowlists (explicit; do not expand casually — see VALIDATION_RUNBOOK.md)
# ---------------------------------------------------------------------------

# Path prefixes relative to the repository root (POSIX-style, trailing slash).
DEFAULT_ARCHIVE_ALLOWLIST_PREFIXES: Tuple[str, ...] = (
    "docs/archive/",
    "docs/archived_stubs/",
    "archive/",
    "docs/knowledge_graphs/archive/",
    "docs/logic/archive/",
    "docs/tdfol/",  # generated/build-adjacent historical surface
)

# Directory name segments that mark a path as archived/historical for soft checks.
ARCHIVE_PATH_SEGMENTS: frozenset = frozenset(
    {
        "archive",
        "archived_stubs",
        "ARCHIVE",
        "completion_reports",
        "PHASE_REPORTS",
        "refactoring_history",
    }
)

# Path substrings (case-insensitive) that mark migration / before-after material.
# Path and module resolution failures inside these files are allowlisted when the
# surrounding prose or fence meta also signals historical intent, or always for
# path/module soft checks (see is_migration_example_path).
DEFAULT_MIGRATION_ALLOWLIST_SUBSTRINGS: Tuple[str, ...] = (
    "migration",
    "before-migration",
    "before_migration",
    "deprecat",
    "legacy",
)

# Fence info-string tokens that mark intentional non-current / incomplete code.
FENCE_ALLOW_TOKENS: frozenset = frozenset(
    {
        "before-migration",
        "before_migration",
        "historical",
        "legacy",
        "incomplete",
        "pseudo",
        "not-executable",
        "allow-broken",
        "allow_broken",
        "no-check",
        "nocheck",
    }
)

# Known top-level roots used to decide whether a backtick string is a repo path.
REPO_PATH_ROOTS: Tuple[str, ...] = (
    "docs/",
    "ipfs_datasets_py/",
    "tests/",
    "test/",
    "scripts/",
    "examples/",
    "benchmarks/",
    "archive/",
    "config/",
    ".github/",
)

REPO_PATH_EXTENSIONS: frozenset = frozenset(
    {
        ".py",
        ".md",
        ".rst",
        ".toml",
        ".yml",
        ".yaml",
        ".json",
        ".txt",
        ".ini",
        ".cfg",
        ".sh",
        ".feature",
        ".html",
        ".css",
        ".js",
        ".ts",
        ".svg",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ipynb",
        ".proto",
        ".sql",
        ".lock",
        ".gitignore",
        ".dockerignore",
    }
)

# Explicit single-file citations often used without a directory prefix.
ROOT_FILE_CITATIONS: frozenset = frozenset(
    {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "README.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "LICENSE.md",
        "mkdocs.yml",
        "Makefile",
        "Dockerfile",
        "docker-compose.yml",
        "requirements.txt",
        "tox.ini",
        "pytest.ini",
        "mypy.ini",
        ".gitignore",
        ".pre-commit-config.yaml",
    }
)

VALID_STATUS_VALUES: frozenset = frozenset(
    {
        "canonical",
        "generated",
        "plan",
        "evidence",
        "historical",
        "draft",
        "deprecated",
    }
)

# Status values that require the full IA §4 metadata set (subset differs).
METADATA_REQUIRED_BY_STATUS: Dict[str, Tuple[str, ...]] = {
    "canonical": ("owner", "source", "last_verified", "audience"),
    "evidence": ("owner", "source", "last_verified"),
    "plan": ("owner",),
}

# Checks that may be selected via --checks.
ALL_CHECKS: Tuple[str, ...] = (
    "markdown_paths",
    "links",
    "anchors",
    "repo_paths",
    "python_modules",
    "metadata",
    "duplicates",
    "python_syntax",
)

SEVERITY_ORDER = {"error": 0, "warning": 1, "allowlisted": 2, "info": 3}

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """One validation finding."""

    severity: str  # error | warning | allowlisted | info
    check: str
    path: str  # repo-relative POSIX path of the doc (or target)
    message: str
    line: Optional[int] = None
    detail: Optional[str] = None
    allowlist_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PageRecord:
    """Parsed facts about one Markdown page."""

    path: Path  # absolute
    rel_posix: str
    text: str
    lines: List[str]
    metadata: Dict[str, str] = field(default_factory=dict)
    status: Optional[str] = None
    interface: Optional[str] = None
    h1: Optional[str] = None
    anchors: Set[str] = field(default_factory=set)
    allowlisted: bool = False
    allowlist_reason: Optional[str] = None


@dataclass
class Summary:
    files_scanned: int = 0
    findings: List[Finding] = field(default_factory=list)
    checks_run: List[str] = field(default_factory=list)
    repo_root: str = ""
    scan_root: str = ""
    started_at_utc: str = ""
    finished_at_utc: str = ""
    git_head: Optional[str] = None
    allowlist_prefixes: List[str] = field(default_factory=list)
    counts_by_severity: Dict[str, int] = field(default_factory=dict)
    counts_by_check: Dict[str, int] = field(default_factory=dict)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def finalize_counts(self) -> None:
        by_sev: Dict[str, int] = defaultdict(int)
        by_check: Dict[str, int] = defaultdict(int)
        for f in self.findings:
            by_sev[f.severity] += 1
            by_check[f.check] += 1
        self.counts_by_severity = dict(by_sev)
        self.counts_by_check = dict(by_check)

    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")


# ---------------------------------------------------------------------------
# Path / root helpers
# ---------------------------------------------------------------------------


def discover_repo_root(start: Optional[Path] = None) -> Path:
    """Walk up from *start* (or this file) looking for pyproject.toml / .git."""
    here = (start or Path(__file__).resolve()).resolve()
    if here.is_file():
        here = here.parent
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file() or (candidate / ".git").exists():
            return candidate
    # Fallback: two levels above docs/maintenance/
    return Path(__file__).resolve().parents[2]


def to_repo_rel(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def normalize_prefix(prefix: str) -> str:
    p = prefix.replace("\\", "/").lstrip("./")
    if p and not p.endswith("/"):
        # Allow exact file prefixes and directory prefixes.
        if "." in Path(p).name and not p.endswith("/"):
            return p
        p = p + "/"
    return p


def path_has_archive_segment(rel_posix: str) -> bool:
    parts = rel_posix.replace("\\", "/").split("/")
    return any(part in ARCHIVE_PATH_SEGMENTS for part in parts)


def is_archive_allowlisted(
    rel_posix: str, prefixes: Sequence[str]
) -> Tuple[bool, Optional[str]]:
    rel = rel_posix.replace("\\", "/").lstrip("./")
    for prefix in prefixes:
        pref = normalize_prefix(prefix).lstrip("./")
        if pref.endswith("/"):
            if rel.startswith(pref) or rel + "/" == pref:
                return True, f"archive-prefix:{pref}"
        elif rel == pref or rel.startswith(pref + "/"):
            return True, f"archive-prefix:{pref}"
    if path_has_archive_segment(rel):
        return True, "archive-path-segment"
    return False, None


def is_migration_example_path(
    rel_posix: str, substrings: Sequence[str]
) -> Tuple[bool, Optional[str]]:
    lower = rel_posix.replace("\\", "/").lower()
    for sub in substrings:
        if sub.lower() in lower:
            return True, f"migration-substring:{sub}"
    return False, None


def classify_page_allowlist(
    rel_posix: str,
    archive_prefixes: Sequence[str],
    migration_substrings: Sequence[str],
) -> Tuple[bool, Optional[str]]:
    ok, reason = is_archive_allowlisted(rel_posix, archive_prefixes)
    if ok:
        return True, reason
    ok, reason = is_migration_example_path(rel_posix, migration_substrings)
    if ok:
        return True, reason
    return False, None


# ---------------------------------------------------------------------------
# Markdown parsing helpers
# ---------------------------------------------------------------------------

# Markdown links: [text](target) — ignore images handled separately if needed.
LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)")
# Reference-style definitions: [id]: url
REFLINK_DEF_RE = re.compile(r"^\s*\[([^\]]+)\]:\s*(\S+)", re.MULTILINE)
# Inline backticks
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
# Fenced code blocks
FENCE_RE = re.compile(
    r"^```([^\n`]*)\n(.*?)^```\s*$",
    re.MULTILINE | re.DOTALL,
)
# ATX headings
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)
# Explicit HTML anchors / ids in headings {#id} or <a id="...">
EXPLICIT_ID_RE = re.compile(
    r"""(?:\{#([A-Za-z0-9_.:-]+)\}|<(?:a|span)\s+[^>]*(?:id|name)=["']([^"']+)["'])""",
    re.IGNORECASE,
)
# YAML front matter
FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
# Metadata table rows: | Field | Value |
META_ROW_RE = re.compile(
    r"^\|\s*(?P<field>[^|]+?)\s*\|\s*(?P<value>[^|]*?)\s*\|?\s*$",
    re.MULTILINE,
)
# Dotted module-ish tokens (reject egg-info / attribute tails via trailing boundary)
MODULE_NAME_RE = re.compile(
    r"(?<![A-Za-z0-9_])(ipfs_datasets_py(?:\.[A-Za-z_][A-Za-z0-9_]*)+)(?![A-Za-z0-9_.-])"
)
# import / from lines inside fences
IMPORT_FROM_RE = re.compile(
    r"^\s*(?:from\s+([A-Za-z_][A-Za-z0-9_.]*)\s+import|import\s+([A-Za-z_][A-Za-z0-9_.]*))",
    re.MULTILINE,
)
# Last verified date
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Metadata field name normalization
FIELD_ALIASES: Dict[str, str] = {
    "status": "status",
    "owner": "owner",
    "source": "source",
    "source of truth": "source",
    "source-of-truth": "source",
    "last verified": "last_verified",
    "last-verified": "last_verified",
    "lastverified": "last_verified",
    "audience": "audience",
    "interface": "interface",
    "task": "task",
    "title": "title",
}


def github_slug(heading: str) -> str:
    """Approximate GitHub/Python-Markdown header slug."""
    text = heading.strip().lower()
    # Drop explicit {#id} suffix if present
    text = re.sub(r"\s*\{#[^}]+\}\s*$", "", text)
    # Strip inline markdown
    text = re.sub(r"[`*_~\[\]()]", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    # Keep alnum, spaces, hyphens
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text


def slug_variants(slug: str) -> Set[str]:
    """Return accepted anchor variants for a heading slug.

    Numbered headings like ``## 11. Reproducible commands`` slug to
    ``11-reproducible-commands``; authors often link ``#reproducible-commands``.
    Accept both the full slug and a single leading ``<digits>-`` strip.
    """
    variants = {slug, slug.lower()}
    m = re.match(r"^\d+-(.+)$", slug)
    if m:
        variants.add(m.group(1))
        variants.add(m.group(1).lower())
    return variants


def extract_front_matter(text: str) -> Dict[str, str]:
    m = FRONT_MATTER_RE.match(text)
    if not m:
        return {}
    meta: Dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key_n = FIELD_ALIASES.get(key.strip().lower())
        if key_n:
            meta[key_n] = val.strip().strip("\"'")
    return meta


def extract_metadata_table(text: str) -> Dict[str, str]:
    """Parse the first Field/Value-style table near the top of the page."""
    # Limit search to the preamble (before the second H2 or 80 lines).
    preamble_lines = text.splitlines()[:120]
    preamble = "\n".join(preamble_lines)
    meta: Dict[str, str] = {}
    in_table = False
    for line in preamble.splitlines():
        if re.match(r"^\|\s*[-:]+", line):
            in_table = True
            continue
        m = META_ROW_RE.match(line)
        if not m:
            if in_table and line.strip() and not line.strip().startswith("|"):
                break
            continue
        field_raw = m.group("field").strip()
        value_raw = m.group("value").strip()
        # Skip header row
        if field_raw.lower() in {"field", "key", "name"} and value_raw.lower() in {
            "value",
            "content",
        }:
            in_table = True
            continue
        # Strip markdown bold/code
        field_clean = re.sub(r"[`*_]", "", field_raw).strip().lower()
        value_clean = value_raw.strip().strip("`")
        value_clean = re.sub(r"^`+|`+$", "", value_clean).strip()
        key = FIELD_ALIASES.get(field_clean)
        if key and value_clean and value_clean.lower() not in {"value", "---", "–"}:
            meta[key] = value_clean
            in_table = True
    return meta


def extract_h1(text: str) -> Optional[str]:
    for m in HEADING_RE.finditer(text):
        if len(m.group(1)) == 1:
            title = m.group(2).strip()
            title = re.sub(r"\s*\{#[^}]+\}\s*$", "", title)
            return title
    return None


def extract_anchors(text: str) -> Set[str]:
    anchors: Set[str] = set()
    slug_counts: Dict[str, int] = defaultdict(int)
    for m in HEADING_RE.finditer(text):
        raw = m.group(2).strip()
        explicit = re.search(r"\{#([A-Za-z0-9_.:-]+)\}", raw)
        if explicit:
            anchors.update(slug_variants(explicit.group(1)))
            continue
        base = github_slug(raw)
        if not base:
            continue
        slug_counts[base] += 1
        n = slug_counts[base]
        primary = base if n == 1 else f"{base}-{n - 1}"
        anchors.update(slug_variants(primary))
    for m in EXPLICIT_ID_RE.finditer(text):
        for g in m.groups():
            if g:
                anchors.update(slug_variants(g))
    return anchors


def strip_fences_for_link_scan(text: str) -> str:
    """Remove fenced code blocks so we do not treat example links as live."""
    return FENCE_RE.sub("", text)


def iter_fences(text: str) -> Iterator[Tuple[int, str, str]]:
    """Yield (start_line, info_string, body) for each fenced block."""
    # Line-based scan for accurate line numbers
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            info = line[3:].strip()
            start_line = i + 1  # 1-based line of opening fence
            body_lines: List[str] = []
            i += 1
            while i < len(lines):
                if lines[i].startswith("```"):
                    yield start_line, info, "\n".join(body_lines)
                    break
                body_lines.append(lines[i])
                i += 1
        i += 1


def fence_is_python(info: str) -> bool:
    lang = (info or "").strip().split()[0].lower() if info.strip() else ""
    return lang in {"python", "py", "python3", "py3", "pycon"}


def fence_allowlisted(info: str) -> Tuple[bool, Optional[str]]:
    tokens = {t.lower() for t in re.split(r"[\s,;|]+", (info or "").strip()) if t}
    for tok in FENCE_ALLOW_TOKENS:
        if tok in tokens:
            return True, f"fence-token:{tok}"
    # Common pattern: ```python historical
    return False, None


def split_link_target(raw: str) -> Tuple[str, Optional[str]]:
    """Return (path_part, anchor) from a markdown link target."""
    target = raw.strip()
    # Angle brackets <path>
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    # Title in quotes after path: path "title"
    if " " in target:
        # Keep first token if it looks like a path; drop title
        first, _, rest = target.partition(" ")
        if rest.startswith('"') or rest.startswith("'"):
            target = first
    if target.startswith("#"):
        return "", target[1:]
    if "#" in target:
        path_part, _, frag = target.partition("#")
        return path_part, frag or None
    return target, None


def is_external_link(target: str) -> bool:
    t = target.strip().lower()
    return bool(
        re.match(
            r"^(https?://|mailto:|ftp://|//|tel:|data:|javascript:)",
            t,
        )
    )


def is_probable_repo_path(token: str) -> bool:
    """Return True when *token* looks like a concrete repository path citation.

    Rejects globs, bare basenames (ambiguous without a directory), pure
    dotted modules (handled by the python_modules check), and site-style
    absolute URL paths (``/vectors/``).
    """
    t = token.strip().strip("\"'")
    if not t or any(c.isspace() for c in t):
        return False
    if is_external_link(t):
        return False
    if t.startswith("#") or t.startswith("@"):
        return False
    # Globs / inventory patterns are not concrete paths
    if any(ch in t for ch in "*?[]{}"):
        return False
    # Web/API path fragments, not repository paths
    if t.startswith("/") and not any(
        t.lstrip("/").startswith(root.rstrip("/")) for root in REPO_PATH_ROOTS
    ):
        return False
    if t in ROOT_FILE_CITATIONS:
        return True
    # Require a directory separator for ordinary path citations so bare names
    # like ``index.md`` or ``config.py`` (prose, not paths) are not flagged.
    if "/" not in t and not t.startswith("./") and not t.startswith("../"):
        return False
    if any(t.startswith(root) for root in REPO_PATH_ROOTS):
        return True
    if t.startswith("./") or t.startswith("../"):
        return True
    # Nested path with a known file extension (may be package-relative)
    lower = t.lower()
    if any(lower.endswith(ext) for ext in REPO_PATH_EXTENSIONS):
        return True
    # Directory-like citations with a trailing slash and at least one segment
    if t.endswith("/") and t.rstrip("/").count("/") >= 1:
        # Prefer known roots or package-looking paths; skip single-segment
        # site paths already rejected above.
        first = t.lstrip("./").split("/", 1)[0]
        if first in {
            "docs",
            "ipfs_datasets_py",
            "tests",
            "test",
            "scripts",
            "examples",
            "benchmarks",
            "archive",
            "config",
            "mcp_server",
            "processors",
            "optimizers",
            "architecture",
            "guides",
            "api",
            "implementation",
            "media_tools",
            "core_operations",
        }:
            return True
    return False


def looks_like_module_name(token: str) -> bool:
    t = token.strip().strip("`")
    if not t or "/" in t or "\\" in t:
        return False
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$", t):
        return False
    # Prefer package-rooted names; also accept tests.*
    if not (t.startswith("ipfs_datasets_py") or t.startswith("tests.")):
        return False
    # Leaf CamelCase is usually a class/attribute, not a module path.
    leaf = t.rsplit(".", 1)[-1]
    if leaf[:1].isupper():
        return False
    return True


def module_to_candidate_paths(module: str) -> List[str]:
    """Map dotted module name to filesystem candidates (relative)."""
    parts = module.split(".")
    # If leaf looks like a class (CamelCase), resolve the parent package/module.
    if parts and parts[-1][:1].isupper():
        parts = parts[:-1]
    if not parts:
        return []
    base = "/".join(parts)
    return [
        base + ".py",
        base + "/__init__.py",
    ]


def resolve_local_link(
    source_rel: str, link_path: str, repo_root: Path
) -> Optional[Path]:
    """Resolve a relative link from source_rel against the repo root."""
    if not link_path or link_path.startswith("#"):
        return None
    # Absolute-from-repo links occasionally start with /
    if link_path.startswith("/"):
        candidate = repo_root / link_path.lstrip("/")
        return candidate if candidate.exists() else None

    source_dir = (repo_root / source_rel).parent
    # MkDocs-style absolute-from-docs links are rare; try relative first.
    candidate = (source_dir / link_path).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError:
        # Escaped the repo — treat as missing
        return None
    if candidate.exists():
        return candidate
    # Retry as repo-root-relative
    alt = (repo_root / link_path).resolve()
    try:
        alt.relative_to(repo_root.resolve())
    except ValueError:
        return None
    if alt.exists():
        return alt
    return None


def load_page(
    path: Path,
    repo_root: Path,
    archive_prefixes: Sequence[str],
    migration_substrings: Sequence[str],
) -> PageRecord:
    rel = to_repo_rel(path, repo_root)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        text = ""
        # Caller may record read errors
        _ = exc
    lines = text.splitlines()
    meta = extract_front_matter(text)
    table_meta = extract_metadata_table(text)
    # Table values fill gaps; front matter wins on conflict for status-like keys
    for k, v in table_meta.items():
        meta.setdefault(k, v)
    status_raw = (meta.get("status") or "").strip().strip("`").lower()
    status = status_raw if status_raw in VALID_STATUS_VALUES else (status_raw or None)
    # Normalize status if it contains extra prose e.g. `canonical` already stripped
    if status and status not in VALID_STATUS_VALUES:
        for vs in VALID_STATUS_VALUES:
            if status.startswith(vs):
                status = vs
                break
    interface = (meta.get("interface") or "").strip().strip("`") or None
    allowlisted, reason = classify_page_allowlist(
        rel, archive_prefixes, migration_substrings
    )
    return PageRecord(
        path=path,
        rel_posix=rel,
        text=text,
        lines=lines,
        metadata=meta,
        status=status if status in VALID_STATUS_VALUES else status,
        interface=interface,
        h1=extract_h1(text),
        anchors=extract_anchors(text),
        allowlisted=allowlisted,
        allowlist_reason=reason,
    )


def iter_markdown_files(scan_root: Path) -> List[Path]:
    if not scan_root.exists():
        return []
    if scan_root.is_file() and scan_root.suffix.lower() == ".md":
        return [scan_root]
    results: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(scan_root):
        # Skip hidden and common generated dirs
        dirnames[:] = [
            d
            for d in dirnames
            if d not in {".git", ".venv", "venv", "node_modules", "__pycache__", "site"}
            and not d.startswith(".")
        ]
        for name in filenames:
            if name.lower().endswith(".md"):
                results.append(Path(dirpath) / name)
    results.sort(key=lambda p: p.as_posix())
    return results


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_markdown_paths(pages: Sequence[PageRecord], summary: Summary) -> None:
    summary.add(
        Finding(
            severity="info",
            check="markdown_paths",
            path=summary.scan_root,
            message=f"Scanned {len(pages)} Markdown file(s) under scan root",
        )
    )
    for page in pages:
        if not page.text.strip():
            sev = "allowlisted" if page.allowlisted else "warning"
            summary.add(
                Finding(
                    severity=sev,
                    check="markdown_paths",
                    path=page.rel_posix,
                    message="Markdown file is empty",
                    allowlist_reason=page.allowlist_reason if page.allowlisted else None,
                )
            )


def check_links_and_anchors(
    pages: Sequence[PageRecord],
    repo_root: Path,
    summary: Summary,
    do_links: bool,
    do_anchors: bool,
    page_index: Dict[str, PageRecord],
) -> None:
    for page in pages:
        scan_text = strip_fences_for_link_scan(page.text)
        for m in LINK_RE.finditer(scan_text):
            raw_target = m.group(2).strip()
            # Compute approximate line number
            line_no = scan_text.count("\n", 0, m.start()) + 1
            if is_external_link(raw_target):
                if do_links:
                    summary.add(
                        Finding(
                            severity="info",
                            check="links",
                            path=page.rel_posix,
                            message="External link skipped (no network fetch)",
                            line=line_no,
                            detail=raw_target[:200],
                        )
                    )
                continue
            path_part, frag = split_link_target(raw_target)
            # Pure anchor on self
            if not path_part and frag is not None:
                if do_anchors:
                    if frag.lower() not in page.anchors and frag not in page.anchors:
                        sev = _sev_for_page(page, default="error")
                        summary.add(
                            Finding(
                                severity=sev,
                                check="anchors",
                                path=page.rel_posix,
                                message=f"In-page anchor not found: #{frag}",
                                line=line_no,
                                allowlist_reason=page.allowlist_reason
                                if page.allowlisted
                                else None,
                            )
                        )
                continue
            if not path_part:
                continue
            # Ignore bare scheme-less weirdness
            if path_part.startswith("{{") or path_part.startswith("<"):
                continue
            resolved = resolve_local_link(page.rel_posix, path_part, repo_root)
            if do_links:
                if resolved is None:
                    sev = _sev_for_page(page, default="error")
                    summary.add(
                        Finding(
                            severity=sev,
                            check="links",
                            path=page.rel_posix,
                            message=f"Relative link target missing: {path_part}",
                            line=line_no,
                            detail=raw_target[:200],
                            allowlist_reason=page.allowlist_reason
                            if page.allowlisted
                            else None,
                        )
                    )
                    continue
            if do_anchors and frag and resolved is not None:
                target_rel = to_repo_rel(resolved, repo_root)
                target_page = page_index.get(target_rel)
                if target_page is None and resolved.suffix.lower() == ".md":
                    # Outside scan root but in repo — load anchors lightly
                    try:
                        ttext = resolved.read_text(encoding="utf-8", errors="replace")
                        tanchors = extract_anchors(ttext)
                    except OSError:
                        tanchors = set()
                elif target_page is not None:
                    tanchors = target_page.anchors
                else:
                    tanchors = set()
                if tanchors and frag.lower() not in tanchors and frag not in tanchors:
                    sev = _sev_for_page(page, default="error")
                    summary.add(
                        Finding(
                            severity=sev,
                            check="anchors",
                            path=page.rel_posix,
                            message=f"Anchor #{frag} not found in {target_rel}",
                            line=line_no,
                            allowlist_reason=page.allowlist_reason
                            if page.allowlisted
                            else None,
                        )
                    )


def _sev_for_page(page: PageRecord, default: str = "error") -> str:
    if page.allowlisted:
        return "allowlisted"
    return default


def _repo_path_candidates(token: str, page_rel: str, repo_root: Path) -> List[Path]:
    """Build candidate filesystem paths for a cited token."""
    norm = token.lstrip("./")
    page_dir = (repo_root / page_rel).parent
    candidates = [
        repo_root / norm,
        page_dir / token,
        page_dir / norm,
        repo_root / "docs" / norm,
        repo_root / "ipfs_datasets_py" / norm,
        repo_root / "tests" / norm,
        repo_root / "scripts" / norm,
    ]
    # Absolute-from-repo style /docs/...
    if token.startswith("/") and not token.startswith("//"):
        candidates.append(repo_root / token.lstrip("/"))
    return candidates


def check_repo_paths(
    pages: Sequence[PageRecord],
    repo_root: Path,
    summary: Summary,
) -> None:
    seen_per_page: Dict[str, Set[str]] = defaultdict(set)
    for page in pages:
        for m in BACKTICK_RE.finditer(page.text):
            token = m.group(1).strip()
            if not is_probable_repo_path(token):
                continue
            norm = token.lstrip("./")
            if norm in seen_per_page[page.rel_posix]:
                continue
            seen_per_page[page.rel_posix].add(norm)
            line_no = page.text.count("\n", 0, m.start()) + 1
            candidates = _repo_path_candidates(token, page.rel_posix, repo_root)
            exists = any(c.exists() for c in candidates)
            if not exists:
                sev = _sev_for_page(page, default="error")
                if not page.allowlisted:
                    mig, _ = is_migration_example_path(
                        page.rel_posix, DEFAULT_MIGRATION_ALLOWLIST_SUBSTRINGS
                    )
                    if mig:
                        sev = "allowlisted"
                summary.add(
                    Finding(
                        severity=sev,
                        check="repo_paths",
                        path=page.rel_posix,
                        message=f"Referenced repository path not found: {token}",
                        line=line_no,
                        allowlist_reason=page.allowlist_reason
                        if sev == "allowlisted"
                        else None,
                    )
                )


# Prefer import citations over backtick/prose when the same module is first
# seen on the same line so report detail is deterministic across runs.
_MODULE_ORIGIN_PRIORITY: Dict[str, int] = {
    "import": 0,
    "backtick": 1,
    "prose": 2,
}


def check_python_modules(
    pages: Sequence[PageRecord],
    repo_root: Path,
    summary: Summary,
) -> None:
    for page in pages:
        modules: Set[Tuple[str, int, str]] = set()  # module, line, origin
        # Backtick dotted modules
        for m in BACKTICK_RE.finditer(page.text):
            token = m.group(1).strip()
            if looks_like_module_name(token):
                line_no = page.text.count("\n", 0, m.start()) + 1
                modules.add((token, line_no, "backtick"))
        for m in MODULE_NAME_RE.finditer(page.text):
            token = m.group(1)
            line_no = page.text.count("\n", 0, m.start()) + 1
            modules.add((token, line_no, "prose"))
        # Imports inside python fences
        for start_line, info, body in iter_fences(page.text):
            if not fence_is_python(info):
                continue
            allow, _reason = fence_allowlisted(info)
            if allow:
                continue
            for im in IMPORT_FROM_RE.finditer(body):
                mod = im.group(1) or im.group(2)
                if not mod:
                    continue
                # Only resolve first segment path for third-party; full for local
                if mod.startswith("ipfs_datasets_py") or mod.startswith("tests"):
                    # line offset within fence
                    sub_line = body.count("\n", 0, im.start())
                    modules.add((mod, start_line + 1 + sub_line, "import"))

        # One finding per module: earliest line, then stable origin priority.
        best: Dict[str, Tuple[int, str]] = {}
        for mod, line_no, origin in modules:
            prev = best.get(mod)
            if prev is None:
                best[mod] = (line_no, origin)
                continue
            prev_line, prev_origin = prev
            if line_no < prev_line:
                best[mod] = (line_no, origin)
            elif line_no == prev_line:
                if _MODULE_ORIGIN_PRIORITY.get(origin, 9) < _MODULE_ORIGIN_PRIORITY.get(
                    prev_origin, 9
                ):
                    best[mod] = (line_no, origin)

        for mod, (line_no, origin) in sorted(best.items(), key=lambda x: (x[1][0], x[0])):
            if _module_exists_on_tree(mod, repo_root):
                continue
            sev = _sev_for_page(page, default="error")
            summary.add(
                Finding(
                    severity=sev,
                    check="python_modules",
                    path=page.rel_posix,
                    message=f"Python module not found on tree: {mod}",
                    line=line_no,
                    detail=f"origin={origin}",
                    allowlist_reason=page.allowlist_reason
                    if page.allowlisted
                    else None,
                )
            )


def _module_exists_on_tree(module: str, repo_root: Path) -> bool:
    parts = module.split(".")
    if parts and parts[-1][:1].isupper():
        # Class or constant reference: require parent module only.
        parts = parts[:-1]
        module = ".".join(parts)
        if not module:
            return True
    for rel in module_to_candidate_paths(module):
        if (repo_root / rel).exists():
            return True
    # Namespace packages: directory exists even without __init__.py
    dir_path = repo_root / "/".join(module.split("."))
    if dir_path.is_dir():
        return True
    return False


def check_metadata(pages: Sequence[PageRecord], summary: Summary) -> None:
    for page in pages:
        status = page.status
        if not status:
            # Legacy pages without metadata: info only (review-needed), not fail
            if not page.allowlisted and page.rel_posix.startswith("docs/"):
                # Only note maintained tree leaves that look like program outputs
                if page.metadata:
                    # Has some metadata but no valid status
                    summary.add(
                        Finding(
                            severity="warning",
                            check="metadata",
                            path=page.rel_posix,
                            message="Metadata present but Status missing or not a known lifecycle value",
                            detail=f"raw={page.metadata.get('status')!r}",
                        )
                    )
            continue
        required = METADATA_REQUIRED_BY_STATUS.get(status)
        if not required:
            continue
        missing: List[str] = []
        for field_name in required:
            if field_name == "source":
                if not (page.metadata.get("source") or "").strip():
                    missing.append("Source / Source of truth")
            elif field_name == "last_verified":
                val = (page.metadata.get("last_verified") or "").strip()
                if not val:
                    missing.append("Last verified")
                elif not ISO_DATE_RE.match(val[:10] if len(val) >= 10 else val):
                    # Allow ISO date as prefix of a longer string
                    if not ISO_DATE_RE.match(val):
                        missing.append("Last verified (expected YYYY-MM-DD)")
            elif field_name == "owner":
                if not (page.metadata.get("owner") or "").strip():
                    missing.append("Owner")
            elif field_name == "audience":
                if not (page.metadata.get("audience") or "").strip():
                    missing.append("Audience")
        if missing:
            sev = _sev_for_page(page, default="error")
            summary.add(
                Finding(
                    severity=sev,
                    check="metadata",
                    path=page.rel_posix,
                    message=(
                        f"Status={status} page missing required metadata: "
                        + ", ".join(missing)
                    ),
                    allowlist_reason=page.allowlist_reason if page.allowlisted else None,
                )
            )
        # Never treat mtime as freshness: only document the rule via info once
        # per canonical page if Last verified is present (content-based).
        if status == "canonical" and page.metadata.get("last_verified"):
            # Deliberate no-op: we do not compare to filesystem mtime.
            pass


def check_duplicate_canonicals(
    pages: Sequence[PageRecord], summary: Summary
) -> None:
    """Flag duplicate Interface ids and duplicate H1 among canonical pages."""
    by_interface: Dict[str, List[PageRecord]] = defaultdict(list)
    by_h1: Dict[str, List[PageRecord]] = defaultdict(list)
    for page in pages:
        if page.status != "canonical":
            continue
        if page.interface:
            by_interface[page.interface.strip()].append(page)
        if page.h1:
            by_h1[page.h1.strip().lower()].append(page)

    for interface, group in sorted(by_interface.items()):
        # Allowlist-aware: if all are allowlisted, mark allowlisted
        if len(group) <= 1:
            continue
        paths = [p.rel_posix for p in group]
        all_allow = all(p.allowlisted for p in group)
        sev = "allowlisted" if all_allow else "error"
        summary.add(
            Finding(
                severity=sev,
                check="duplicates",
                path=paths[0],
                message=(
                    f"Duplicate canonical Interface declaration: {interface!r} "
                    f"used by {len(group)} pages"
                ),
                detail="; ".join(paths),
                allowlist_reason="all-sources-allowlisted" if all_allow else None,
            )
        )

    for h1, group in sorted(by_h1.items()):
        if len(group) <= 1:
            continue
        # Many pages can share generic titles; only flag when Interface also empty
        # and paths are both non-allowlisted in the same directory sense — still
        # useful signal for true duplicates of maintained pages.
        non_allow = [p for p in group if not p.allowlisted]
        if len(non_allow) <= 1:
            continue
        # Require at least two without interface id (interface duplicates handled above)
        no_iface = [p for p in non_allow if not p.interface]
        if len(no_iface) <= 1:
            continue
        paths = [p.rel_posix for p in no_iface]
        summary.add(
            Finding(
                severity="warning",
                check="duplicates",
                path=paths[0],
                message=(
                    f"Multiple Status=canonical pages share H1 {group[0].h1!r} "
                    f"without distinct Interface ids"
                ),
                detail="; ".join(paths),
            )
        )


def check_python_syntax(
    pages: Sequence[PageRecord], summary: Summary
) -> None:
    for page in pages:
        for start_line, info, body in iter_fences(page.text):
            if not fence_is_python(info):
                continue
            allow, allow_reason = fence_allowlisted(info)
            if allow:
                summary.add(
                    Finding(
                        severity="allowlisted",
                        check="python_syntax",
                        path=page.rel_posix,
                        message="Python fence skipped by fence allow token",
                        line=start_line,
                        allowlist_reason=allow_reason,
                    )
                )
                continue
            source = _normalize_pycon(body)
            if not source.strip():
                continue
            if _looks_incomplete_snippet(source):
                # Try parse; if fails, allowlist/warn rather than hard-fail
                ok, err = _try_parse_python(source)
                if ok:
                    continue
                sev = "allowlisted" if page.allowlisted else "warning"
                summary.add(
                    Finding(
                        severity=sev,
                        check="python_syntax",
                        path=page.rel_posix,
                        message="Incomplete Python snippet failed parse (warning)",
                        line=start_line,
                        detail=err,
                        allowlist_reason=page.allowlist_reason
                        if page.allowlisted
                        else "incomplete-snippet",
                    )
                )
                continue
            ok, err = _try_parse_python(source)
            if not ok:
                sev = _sev_for_page(page, default="error")
                summary.add(
                    Finding(
                        severity=sev,
                        check="python_syntax",
                        path=page.rel_posix,
                        message="Fenced Python block has syntax error",
                        line=start_line,
                        detail=err,
                        allowlist_reason=page.allowlist_reason
                        if page.allowlisted
                        else None,
                    )
                )


def _normalize_pycon(body: str) -> str:
    """Strip pycon prompts and continuation prompts."""
    out: List[str] = []
    for line in body.splitlines():
        if line.startswith(">>> "):
            out.append(line[4:])
        elif line.startswith("..."):
            # continuation or ellipsis placeholder
            if line.startswith("... "):
                out.append(line[4:])
            else:
                out.append(line[3:])
        elif line.startswith(">>>"):
            out.append(line[3:].lstrip())
        else:
            out.append(line)
    return "\n".join(out)


def _looks_incomplete_snippet(source: str) -> bool:
    s = source.strip()
    if not s:
        return True
    if re.search(r"\bEllipsis\b|\.\.\.|pass\s*#\s*\.\.\.", s):
        # May still be complete; heuristic: trailing colon with no body often incomplete
        pass
    # Single-line fragments without import/def/class/control often incomplete
    lines = [ln for ln in s.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not lines:
        return True
    if any(ln.rstrip().endswith("\\") for ln in lines):
        return True
    # Explicit placeholder comments
    if re.search(r"#\s*(\.\.\.|…|your code here|TODO|FIXME)", s, re.I):
        return True
    return False


def _try_parse_python(source: str) -> Tuple[bool, Optional[str]]:
    try:
        ast.parse(source)
        return True, None
    except SyntaxError as exc:
        msg = f"{exc.msg} (line {exc.lineno})"
        return False, msg


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def _classify_p0_p1(summary: Summary) -> Tuple[List[Finding], List[Finding]]:
    """Split error findings into P0 (gate/authority) vs P1 (tree debt).

    P0: metadata gaps on canonical pages, duplicate Interface authority,
    and link/anchor breaks on primary entry/navigation surfaces.
    P1: remaining non-allowlisted errors (stale paths, modules, fences, …).
    """
    p0_checks = {"metadata", "duplicates"}
    p0_path_prefixes = (
        "docs/index.md",
        "docs/README.md",
        "docs/DOCUMENTATION_INDEX.md",
        "docs/getting_started.md",
        "docs/user_guide.md",
        "docs/installation.md",
        "docs/configuration.md",
        "docs/FEATURES.md",
        "docs/CHANGELOG.md",
        "docs/GLOSSARY.md",
        "docs/faq.md",
        "docs/architecture/README.md",
        "docs/tutorials/",
        "docs/maintenance/completion_receipts/",
    )
    p0: List[Finding] = []
    p1: List[Finding] = []
    for f in summary.findings:
        if f.severity != "error":
            continue
        if f.check in p0_checks:
            p0.append(f)
            continue
        path = f.path or ""
        if f.check in {"links", "anchors"} and any(
            path == pref or path.startswith(pref) for pref in p0_path_prefixes
        ):
            p0.append(f)
            continue
        p1.append(f)
    return p0, p1


def render_markdown_report(summary: Summary) -> str:
    lines: List[str] = []
    p0, p1 = _classify_p0_p1(summary)
    lines.append("# Documentation quality report")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    lines.append("| Interface | `DocumentationQualityReport@1` |")
    lines.append(f"| Validator | `{INTERFACE_ID}` |")
    lines.append(f"| Generator | `docs/maintenance/check_docs.py` v{__version__} |")
    lines.append("| Quality task | `IPFSDOC-096` |")
    lines.append(f"| Tool task | `{TASK_ID}` |")
    lines.append(f"| Started (UTC) | `{summary.started_at_utc}` |")
    lines.append(f"| Finished (UTC) | `{summary.finished_at_utc}` |")
    lines.append(f"| Repo root | `{summary.repo_root}` |")
    lines.append(f"| Scan root | `{summary.scan_root}` |")
    lines.append(f"| Git HEAD | `{summary.git_head or 'unavailable'}` |")
    lines.append(f"| Files scanned | {summary.files_scanned} |")
    lines.append(f"| Checks run | {', '.join(summary.checks_run)} |")
    lines.append(f"| Errors | {summary.error_count()} |")
    lines.append(f"| Warnings | {summary.warning_count()} |")
    lines.append(
        f"| Allowlisted | {summary.counts_by_severity.get('allowlisted', 0)} |"
    )
    lines.append(f"| P0 (authority/entry) | {len(p0)} |")
    lines.append(f"| P1 (tree debt) | {len(p1)} |")
    lines.append("")
    lines.append("## Command and tree")
    lines.append("")
    lines.append(
        "```bash\n"
        "python docs/maintenance/check_docs.py --root docs "
        "--report docs/maintenance/QUALITY_REPORT.md\n"
        "```"
    )
    lines.append("")
    lines.append(
        "Report publishing uses process exit policy **fail-on never** when "
        "`--report` is set (unless `--fail-on` is passed explicitly), so the "
        "quality artifact can be written and disclosed even when the integrated "
        "tree still has non-allowlisted findings. Failures are **not** hidden by "
        "expanding allowlists."
    )
    lines.append("")
    lines.append("## Side-effect and authority notes")
    lines.append("")
    lines.append(
        "- This report was produced offline: **no network fetches** were performed."
    )
    lines.append(
        "- **Filesystem mtimes were not used** as freshness proof; only "
        "in-document `Last verified` metadata is considered for metadata checks."
    )
    lines.append(
        "- The checker **does not delete** generated output (`site/`, build "
        "artifacts). It only writes this report path when requested."
    )
    lines.append(
        "- Allowlisted archive and before-migration findings are listed below "
        "but do not fail the gate unless `--strict-allowlist` is set."
    )
    lines.append(
        "- Optional MkDocs build / external link liveness / live services are "
        "**out of scope** for this offline gate (deferred unless separately "
        "provisioned)."
    )
    lines.append("")
    lines.append("## Priority summary (P0 / P1)")
    lines.append("")
    lines.append("| Priority | Count | Meaning |")
    lines.append("| --- | ---: | --- |")
    lines.append(
        f"| **P0** | {len(p0)} | Canonical metadata gaps, duplicate "
        "`Interface` authority, or broken links/anchors on entry/spine pages |"
    )
    lines.append(
        f"| **P1** | {len(p1)} | Remaining non-allowlisted debt (repo paths, "
        "modules, fence syntax, secondary links/anchors, …) |"
    )
    lines.append(
        f"| Allowlisted | {summary.counts_by_severity.get('allowlisted', 0)} | "
        "Archive / migration / historical paths (reported, non-gating) |"
    )
    lines.append("")
    if p0:
        lines.append("### P0 samples (up to 40)")
        lines.append("")
        lines.append("| Check | Path | Line | Message |")
        lines.append("| --- | --- | ---: | --- |")
        for f in p0[:40]:
            path = f.path.replace("|", "\\|")
            msg = f.message.replace("|", "\\|")
            line = f.line if f.line is not None else ""
            lines.append(f"| `{f.check}` | `{path}` | {line} | {msg} |")
        if len(p0) > 40:
            lines.append("")
            lines.append(f"_… and {len(p0) - 40} more P0 findings in the tables below._")
        lines.append("")
    lines.append("## Counts by check")
    lines.append("")
    lines.append("| Check | Findings |")
    lines.append("| --- | ---: |")
    for check in summary.checks_run:
        lines.append(f"| `{check}` | {summary.counts_by_check.get(check, 0)} |")
    lines.append("")
    lines.append("## Allowlist prefixes")
    lines.append("")
    for pref in summary.allowlist_prefixes:
        lines.append(f"- `{pref}`")
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    if not summary.findings:
        lines.append("No findings.")
        lines.append("")
        return "\n".join(lines)

    # Group by severity
    for severity in ("error", "warning", "allowlisted", "info"):
        group = [f for f in summary.findings if f.severity == severity]
        if not group:
            continue
        lines.append(f"### {severity} ({len(group)})")
        lines.append("")
        lines.append("| Check | Path | Line | Message | Detail |")
        lines.append("| --- | --- | ---: | --- | --- |")
        for f in group:
            path = f.path.replace("|", "\\|")
            msg = f.message.replace("|", "\\|")
            detail = (f.detail or f.allowlist_reason or "").replace("|", "\\|")
            line = f.line if f.line is not None else ""
            lines.append(
                f"| `{f.check}` | `{path}` | {line} | {msg} | {detail} |"
            )
        lines.append("")
    return "\n".join(lines)


def _resolve_gitdir(repo_root: Path) -> Optional[Path]:
    """Return the git directory for repo_root (handles plain repos and worktrees)."""
    git_path = repo_root / ".git"
    try:
        if git_path.is_dir():
            return git_path
        if git_path.is_file():
            content = git_path.read_text(encoding="utf-8").strip()
            if content.startswith("gitdir:"):
                gitdir = content.split(":", 1)[1].strip()
                resolved = Path(gitdir)
                if not resolved.is_absolute():
                    resolved = (repo_root / resolved).resolve()
                return resolved
    except OSError:
        return None
    return None


def _git_common_dir(gitdir: Path) -> Path:
    """Resolve commondir for linked worktrees; otherwise the gitdir itself."""
    try:
        common = gitdir / "commondir"
        if common.is_file():
            raw = common.read_text(encoding="utf-8").strip()
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = (gitdir / candidate).resolve()
            if candidate.is_dir():
                return candidate
    except OSError:
        pass
    return gitdir


def _read_git_ref(gitdir: Path, ref: str) -> Optional[str]:
    """Resolve a ref name to an object id via loose refs or packed-refs."""
    common = _git_common_dir(gitdir)
    for base in (gitdir, common):
        ref_path = base / ref
        try:
            if ref_path.is_file():
                return ref_path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    packed = common / "packed-refs"
    try:
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("^"):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[1] == ref:
                    return parts[0]
    except OSError:
        pass
    return None


def read_git_head(repo_root: Path) -> Optional[str]:
    """Read resolved HEAD object id without invoking git or the network.

    Prefer the commit SHA over a symbolic ref name so quality reports stay
    stable across worktree branch renames when the tree object is unchanged.
    """
    try:
        gitdir = _resolve_gitdir(repo_root)
        if gitdir is None:
            return None
        head_path = gitdir / "HEAD"
        if not head_path.is_file():
            return None
        text = head_path.read_text(encoding="utf-8").strip()
        if text.startswith("ref:"):
            ref = text.split(":", 1)[1].strip()
            resolved = _read_git_ref(gitdir, ref)
            if resolved:
                return resolved
            return text
        return text
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_checks(
    repo_root: Path,
    scan_root: Path,
    checks: Sequence[str],
    archive_prefixes: Sequence[str],
    migration_substrings: Sequence[str],
    strict_allowlist: bool = False,
    exclude_paths: Optional[Sequence[Path]] = None,
) -> Summary:
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    summary = Summary(
        repo_root=str(repo_root.resolve()),
        scan_root=to_repo_rel(scan_root, repo_root)
        if scan_root.is_absolute()
        else scan_root.as_posix(),
        started_at_utc=started,
        allowlist_prefixes=list(archive_prefixes),
        checks_run=list(checks),
        git_head=read_git_head(repo_root),
    )

    exclude_resolved = {
        p.resolve() for p in (exclude_paths or ()) if p is not None
    }
    md_files = iter_markdown_files(scan_root)
    pages: List[PageRecord] = []
    for path in md_files:
        try:
            if path.resolve() in exclude_resolved:
                continue
        except OSError:
            pass
        page = load_page(path, repo_root, archive_prefixes, migration_substrings)
        pages.append(page)
    summary.files_scanned = len(pages)

    page_index = {p.rel_posix: p for p in pages}

    check_set = set(checks)
    if "markdown_paths" in check_set:
        check_markdown_paths(pages, summary)
    if "links" in check_set or "anchors" in check_set:
        check_links_and_anchors(
            pages,
            repo_root,
            summary,
            do_links="links" in check_set,
            do_anchors="anchors" in check_set,
            page_index=page_index,
        )
    if "repo_paths" in check_set:
        check_repo_paths(pages, repo_root, summary)
    if "python_modules" in check_set:
        check_python_modules(pages, repo_root, summary)
    if "metadata" in check_set:
        check_metadata(pages, summary)
    if "duplicates" in check_set:
        check_duplicate_canonicals(pages, summary)
    if "python_syntax" in check_set:
        check_python_syntax(pages, summary)

    if strict_allowlist:
        for f in summary.findings:
            if f.severity == "allowlisted":
                f.severity = "error"
                f.detail = (
                    (f.detail + "; " if f.detail else "")
                    + "promoted by --strict-allowlist"
                )

    summary.finished_at_utc = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    summary.finalize_counts()
    return summary


def parse_checks_arg(value: str) -> List[str]:
    value = (value or "all").strip().lower()
    if value in {"all", "*"}:
        return list(ALL_CHECKS)
    parts = [p.strip() for p in value.split(",") if p.strip()]
    unknown = [p for p in parts if p not in ALL_CHECKS]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"Unknown check(s): {', '.join(unknown)}. "
            f"Choose from: {', '.join(ALL_CHECKS)} or 'all'"
        )
    return parts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_docs.py",
        description=(
            "Deterministic offline documentation validator "
            f"({INTERFACE_ID}). Checks Markdown paths, relative "
            "links/anchors, repository path and Python module references, "
            "required metadata on canonical pages, duplicate canonical "
            "declarations, and fenced Python syntax. "
            "No network access; no mtime-based freshness; does not delete "
            "generated output."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
examples:
  python docs/maintenance/check_docs.py --help
  python docs/maintenance/check_docs.py --root docs
  python docs/maintenance/check_docs.py --root docs --report docs/maintenance/QUALITY_REPORT.md
  python docs/maintenance/check_docs.py --root docs --checks links,metadata,python_syntax
  python docs/maintenance/check_docs.py --root docs/maintenance --fail-on warning

interface: {INTERFACE_ID}
task:      {TASK_ID}
version:   {__version__}
""".rstrip(),
    )
    parser.add_argument(
        "--root",
        default="docs",
        help="Scan root (directory or single .md), relative to repo root or absolute "
        "(default: docs)",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root (default: auto-detect via pyproject.toml / .git)",
    )
    parser.add_argument(
        "--report",
        default=None,
        metavar="PATH",
        help="Write a Markdown quality report to PATH (creates/overwrites only this file)",
    )
    parser.add_argument(
        "--json-report",
        default=None,
        metavar="PATH",
        help="Write a JSON report to PATH (creates/overwrites only this file)",
    )
    parser.add_argument(
        "--checks",
        type=parse_checks_arg,
        default=list(ALL_CHECKS),
        help=(
            "Comma-separated checks to run, or 'all' (default: all). "
            f"Available: {', '.join(ALL_CHECKS)}"
        ),
    )
    parser.add_argument(
        "--allowlist-prefix",
        action="append",
        default=[],
        metavar="PREFIX",
        help="Extra archive/historical path prefix (repo-relative). Repeatable.",
    )
    parser.add_argument(
        "--migration-substring",
        action="append",
        default=[],
        metavar="SUBSTR",
        help="Extra path substring marking before-migration examples. Repeatable.",
    )
    parser.add_argument(
        "--strict-allowlist",
        action="store_true",
        help="Promote allowlisted findings to errors (fail archives/migration too)",
    )
    parser.add_argument(
        "--fail-on",
        choices=("error", "warning", "never"),
        default=None,
        help=(
            "Exit non-zero when findings at this severity or worse exist. "
            "Default: 'error' for ordinary scans; 'never' when --report is set "
            "(report publishing discloses failures without failing the process). "
            "Pass --fail-on error with --report to keep a strict gate."
        ),
    )
    parser.add_argument(
        "--max-print",
        type=int,
        default=50,
        help="Max findings to print to stdout (default: 50; report has full set)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print summary counts",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print all non-info findings up to --max-print",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__} ({INTERFACE_ID})",
    )
    return parser


# Header fields that embed wall-clock time or branch names and must not cause
# re-validation to rewrite an otherwise identical quality artifact (supervisor
# gate: candidate_changed_during_validation).
_EPHEMERAL_REPORT_LINE_PREFIXES: Tuple[str, ...] = (
    "| Started (UTC) |",
    "| Finished (UTC) |",
    "| Git HEAD |",
)


def stable_report_fingerprint(content: str) -> str:
    """Fingerprint report body excluding wall-clock / branch ephemera."""
    lines = [
        line
        for line in content.splitlines()
        if not any(line.startswith(prefix) for prefix in _EPHEMERAL_REPORT_LINE_PREFIXES)
    ]
    body = "\n".join(lines)
    if content.endswith("\n"):
        body += "\n"
    return body


def write_report(path: Path, content: str) -> bool:
    """Write report content. Never deletes other files; parents may be created.

    Returns True when bytes were written, False when an existing report with the
    same stable fingerprint was preserved (idempotent re-validation).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            existing = None
        if (
            existing is not None
            and stable_report_fingerprint(existing) == stable_report_fingerprint(content)
        ):
            return False
    path.write_text(content, encoding="utf-8")
    return True


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    # Report publishing discloses tree debt; do not fail the process unless
    # the caller explicitly opts into a strict gate with --fail-on.
    fail_on = args.fail_on
    if fail_on is None:
        fail_on = "never" if args.report else "error"

    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        repo_root = discover_repo_root()

    scan_root = Path(args.root)
    if not scan_root.is_absolute():
        scan_root = (repo_root / scan_root).resolve()
    else:
        scan_root = scan_root.resolve()

    if not scan_root.exists():
        print(f"error: scan root does not exist: {scan_root}", file=sys.stderr)
        return 2

    archive_prefixes = list(DEFAULT_ARCHIVE_ALLOWLIST_PREFIXES) + list(
        args.allowlist_prefix or []
    )
    migration_substrings = list(DEFAULT_MIGRATION_ALLOWLIST_SUBSTRINGS) + list(
        args.migration_substring or []
    )

    # Resolve report path early so we can exclude it from the scan (avoids
    # self-citing a prior QUALITY_REPORT as path/module findings).
    report_path: Optional[Path] = None
    if args.report:
        report_path = Path(args.report)
        if not report_path.is_absolute():
            report_path = (repo_root / report_path).resolve()
        else:
            report_path = report_path.resolve()

    summary = run_checks(
        repo_root=repo_root,
        scan_root=scan_root,
        checks=args.checks,
        archive_prefixes=archive_prefixes,
        migration_substrings=migration_substrings,
        strict_allowlist=args.strict_allowlist,
        exclude_paths=[report_path] if report_path is not None else None,
    )

    if report_path is not None:
        report_rel = to_repo_rel(report_path, repo_root)
        wrote = write_report(report_path, render_markdown_report(summary))
        if not args.quiet:
            if wrote:
                print(f"Wrote report: {report_rel}")
            else:
                print(f"Report unchanged: {report_rel}")

    if args.json_report:
        json_path = Path(args.json_report)
        if not json_path.is_absolute():
            json_path = repo_root / json_path
        payload = {
            "interface": INTERFACE_ID,
            "version": __version__,
            "task": TASK_ID,
            "repo_root": summary.repo_root,
            "scan_root": summary.scan_root,
            "started_at_utc": summary.started_at_utc,
            "finished_at_utc": summary.finished_at_utc,
            "git_head": summary.git_head,
            "files_scanned": summary.files_scanned,
            "checks_run": summary.checks_run,
            "allowlist_prefixes": summary.allowlist_prefixes,
            "counts_by_severity": summary.counts_by_severity,
            "counts_by_check": summary.counts_by_check,
            "findings": [f.to_dict() for f in summary.findings],
            "policies": {
                "network_access": False,
                "mtime_as_freshness": False,
                "deletes_generated_output": False,
            },
            "fail_on": fail_on,
        }
        # JSON reports always rewrite (machine consumers expect fresh stamps).
        path = Path(json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if not args.quiet:
            print(f"Wrote JSON report: {to_repo_rel(json_path, repo_root)}")

    # Stdout summary
    errors = summary.error_count()
    warnings = summary.warning_count()
    allowlisted = summary.counts_by_severity.get("allowlisted", 0)
    infos = summary.counts_by_severity.get("info", 0)

    print(
        f"check_docs {__version__}: scanned {summary.files_scanned} file(s); "
        f"errors={errors} warnings={warnings} allowlisted={allowlisted} info={infos}"
    )

    if not args.quiet:
        printable = [
            f
            for f in summary.findings
            if f.severity in {"error", "warning"}
            or (args.verbose and f.severity != "info")
        ]
        # Prefer errors first
        printable.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.path, f.line or 0))
        for f in printable[: max(0, args.max_print)]:
            loc = f"{f.path}" + (f":{f.line}" if f.line else "")
            print(f"  [{f.severity}] {f.check}: {loc}: {f.message}")
        remaining = len(printable) - max(0, args.max_print)
        if remaining > 0:
            print(f"  ... and {remaining} more (see --report for full list)")

    if fail_on == "never":
        return 0
    if fail_on == "warning":
        if errors or warnings:
            return 1
        return 0
    # default: error
    if errors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
