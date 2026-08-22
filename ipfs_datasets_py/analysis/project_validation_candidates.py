"""Extract README/comment/package/CI/history commands as untrusted candidates (EAAEF-042).

Discovered command text is never executed.  Admission requires both an adapter
allowlist and an execution policy; matching the allowlist does not make a
candidate trusted source.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import stat
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Final

SCHEMA: Final[str] = "ipfs_datasets_py/analysis/project-validation-candidates@1"
TRUST_CLASS: Final[str] = "untrusted_candidate"
CANDIDATES_ARE_TRUSTED: Final[bool] = False
CANDIDATES_MAY_EXECUTE: Final[bool] = False

DEFAULT_MAX_FILES: Final[int] = 4_096
DEFAULT_MAX_DEPTH: Final[int] = 24
DEFAULT_MAX_FILE_BYTES: Final[int] = 65_536
DEFAULT_MAX_COMMAND_BYTES: Final[int] = 4_096
DEFAULT_MAX_ARGV: Final[int] = 32

_SKIP_DIRECTORIES: Final[frozenset[str]] = frozenset(
    {
        ".agent-supervisor",
        ".aws",
        ".bzr",
        ".cache",
        ".git",
        ".hg",
        ".mypy_cache",
        ".nox",
        ".pijul",
        ".pytest_cache",
        ".ruff_cache",
        ".ssh",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "CVS",
        "bower_components",
        "dist",
        "htmlcov",
        "node_modules",
        "site-packages",
        "target",
        "venv",
    }
)

_README_NAMES: Final[frozenset[str]] = frozenset(
    {"readme", "readme.md", "readme.rst", "readme.txt"}
)
_HISTORY_NAMES: Final[frozenset[str]] = frozenset(
    {
        "changelog",
        "changelog.md",
        "changelog.rst",
        "changelog.txt",
        "history",
        "history.md",
        "history.txt",
        "news.md",
    }
)
_PACKAGE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "package.json",
        "pyproject.toml",
        "setup.cfg",
        "tox.ini",
        "makefile",
        "gnumakefile",
    }
)
_COMMENT_SUFFIXES: Final[frozenset[str]] = frozenset({".py", ".sh", ".bash", ".zsh"})
_CI_SUFFIXES: Final[frozenset[str]] = frozenset({".yml", ".yaml"})
_CI_FILENAMES: Final[frozenset[str]] = frozenset(
    {".gitlab-ci.yml", ".travis.yml", "azure-pipelines.yml"}
)

_FENCE_RE: Final[re.Pattern[str]] = re.compile(
    r"^```(?P<lang>[^\n`]*)\n(?P<body>.*?)^```",
    re.MULTILINE | re.DOTALL,
)
_INLINE_RE: Final[re.Pattern[str]] = re.compile(r"`([^`\n]{2,240})`")
_PROMPT_RE: Final[re.Pattern[str]] = re.compile(r"^[$>]\s+")
_COMMAND_START_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:python(?:3(?:\.\d+)?)?|pypy(?:3(?:\.\d+)?)?|pytest|ruff|mypy|"
    r"nox|tox|coverage|pip|uv|hatch|poetry|make|npm|pnpm|yarn|node|go|"
    r"cargo|mvn|gradle|curl|wget|bash|sh|zsh|env|sudo)\b"
)
_COMMENT_LABELED_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:#|//|--)\s*(?:run|validate|validation|test|ci|command)\s*[:\-]\s*(.+)$",
    re.IGNORECASE,
)
_COMMENT_DIRECT_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:#|//|--)\s+(?P<cmd>(?:python(?:3(?:\.\d+)?)?|pytest|ruff)\b.+)$"
)
_YAML_RUN_RE: Final[re.Pattern[str]] = re.compile(
    r"^(\s*)(?:-\s*)?run:\s*(.*)$"
)
_TOX_COMMANDS_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*commands\s*=\s*(.*)$",
    re.IGNORECASE,
)
_SHELL_META_RE: Final[re.Pattern[str]] = re.compile(
    r"""[|&;<>`$()\n]|&&|\|\||\$\(|`|\\n"""
)
_ENV_ASSIGN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

_NETWORK_EXECUTABLES: Final[frozenset[str]] = frozenset(
    {
        "curl",
        "wget",
        "nc",
        "ncat",
        "netcat",
        "ssh",
        "scp",
        "sftp",
        "rsync",
        "ftp",
        "telnet",
        "nmap",
    }
)
_MUTATION_EXECUTABLES: Final[frozenset[str]] = frozenset(
    {
        "rm",
        "mv",
        "dd",
        "chmod",
        "chown",
        "mkfs",
        "shutdown",
        "reboot",
        "kill",
        "killall",
        "sudo",
        "su",
        "doas",
    }
)
_EVAL_EXECUTABLES: Final[frozenset[str]] = frozenset(
    {"bash", "sh", "zsh", "dash", "ksh", "csh", "fish", "eval", "source"}
)
_FENCE_LANGS: Final[frozenset[str]] = frozenset(
    {"", "bash", "sh", "shell", "console", "terminal", "zsh", "pwsh", "powershell"}
)


class CandidateSource(str, Enum):
    """Closed set of untrusted discovery surfaces."""

    README = "readme"
    COMMENT = "comment"
    PACKAGE = "package"
    CI = "ci"
    HISTORY = "history"


class AdmissionReason(str, Enum):
    ADMITTED = "admitted"
    ALLOWLIST_REQUIRED = "allowlist_required"
    NOT_ALLOWLISTED = "not_allowlisted"
    POLICY_REQUIRED = "policy_required"
    EMPTY_COMMAND = "empty_command"
    COMMAND_TOO_LONG = "command_too_long"
    SHELL_METACHARACTERS = "shell_metacharacters"
    UNSTRUCTURED_ARGV = "unstructured_argv"
    ARGV_TOO_LONG = "argv_too_long"
    NETWORK_TOOL_DENIED = "network_tool_denied"
    MUTATION_TOOL_DENIED = "mutation_tool_denied"
    EVAL_DENIED = "eval_denied"
    INLINE_PYTHON_DENIED = "inline_python_denied"
    ENV_ASSIGNMENT_DENIED = "env_assignment_denied"


@dataclass(frozen=True)
class InventoryBounds:
    max_files: int = DEFAULT_MAX_FILES
    max_depth: int = DEFAULT_MAX_DEPTH
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES

    def __post_init__(self) -> None:
        if type(self.max_files) is not int or self.max_files < 1:
            raise ValueError("max_files must be a positive integer")
        if type(self.max_depth) is not int or self.max_depth < 1:
            raise ValueError("max_depth must be a positive integer")
        if type(self.max_file_bytes) is not int or self.max_file_bytes < 1:
            raise ValueError("max_file_bytes must be a positive integer")


@dataclass(frozen=True)
class UntrustedCommandCandidate:
    """One discovered command. Always untrusted and never executed."""

    command: str
    source: CandidateSource
    path: str
    line: int = 1
    trusted: bool = False
    executed: bool = False
    schema: str = SCHEMA
    trust_class: str = TRUST_CLASS

    def __post_init__(self) -> None:
        if self.trusted:
            raise ValueError("discovered commands cannot be marked trusted")
        if self.executed:
            raise ValueError("discovered commands cannot be marked executed")
        if self.trust_class != TRUST_CLASS:
            raise ValueError("discovered commands must remain untrusted candidates")

    def as_mapping(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "trust_class": self.trust_class,
                "command": self.command,
                "source": self.source.value,
                "path": self.path,
                "line": self.line,
                "trusted": False,
                "executed": False,
            }
        )


@dataclass(frozen=True)
class AdapterAllowlist:
    """Exact argv vectors and prefixes an adapter is willing to admit."""

    prefixes: tuple[tuple[str, ...], ...] = ()
    exact: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        prefixes = tuple(tuple(str(part) for part in item) for item in self.prefixes)
        exact = tuple(tuple(str(part) for part in item) for item in self.exact)
        if any(len(item) == 0 for item in prefixes):
            raise ValueError("allowlist prefixes must be non-empty")
        if any(len(item) == 0 for item in exact):
            raise ValueError("allowlist exact argv must be non-empty")
        object.__setattr__(self, "prefixes", prefixes)
        object.__setattr__(self, "exact", exact)

    def matches(self, argv: Sequence[str]) -> bool:
        vector = tuple(argv)
        if not vector:
            return False
        if vector in self.exact:
            return True
        return any(
            len(vector) >= len(prefix) and vector[: len(prefix)] == prefix
            for prefix in self.prefixes
        )


@dataclass(frozen=True)
class ExecutionPolicy:
    """Fail-closed constraints applied after allowlist matching."""

    network: str = "deny"
    allow_shell: bool = False
    allow_eval: bool = False
    allow_mutation: bool = False
    require_structured_argv: bool = True
    max_command_bytes: int = DEFAULT_MAX_COMMAND_BYTES
    max_argv: int = DEFAULT_MAX_ARGV

    def __post_init__(self) -> None:
        if self.network not in {"deny", "allow"}:
            raise ValueError("network must be 'deny' or 'allow'")
        if type(self.max_command_bytes) is not int or self.max_command_bytes < 1:
            raise ValueError("max_command_bytes must be a positive integer")
        if type(self.max_argv) is not int or self.max_argv < 1:
            raise ValueError("max_argv must be a positive integer")


@dataclass(frozen=True)
class AdmissionDecision:
    """Allowlist plus policy verdict for one untrusted candidate."""

    candidate: UntrustedCommandCandidate
    admitted: bool
    reason: str
    argv: tuple[str, ...] = ()
    trusted: bool = False
    executed: bool = False

    def __post_init__(self) -> None:
        if self.trusted:
            raise ValueError("admitted commands remain untrusted candidates")
        if self.executed:
            raise ValueError("admission must not execute candidates")
        if self.admitted and not self.argv:
            raise ValueError("admitted commands require structured argv")

    def as_mapping(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "schema": SCHEMA,
                "command": self.candidate.command,
                "source": self.candidate.source.value,
                "path": self.candidate.path,
                "line": self.candidate.line,
                "admitted": self.admitted,
                "reason": self.reason,
                "argv": self.argv,
                "trusted": False,
                "executed": False,
            }
        )


@dataclass(frozen=True)
class AdmissionReport:
    """Extraction plus admission, still without execution."""

    candidates: tuple[UntrustedCommandCandidate, ...]
    decisions: tuple[AdmissionDecision, ...]
    executed: bool = False
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if self.executed:
            raise ValueError("validation-candidate reports cannot execute")

    @property
    def admitted(self) -> tuple[AdmissionDecision, ...]:
        return tuple(item for item in self.decisions if item.admitted)

    @property
    def rejected(self) -> tuple[AdmissionDecision, ...]:
        return tuple(item for item in self.decisions if not item.admitted)

    @property
    def admitted_argv(self) -> tuple[tuple[str, ...], ...]:
        return tuple(item.argv for item in self.admitted)


def python_adapter_allowlist() -> AdapterAllowlist:
    """Locked Python ProjectAdapter prefixes (EAAEF-041 toolchain)."""

    return AdapterAllowlist(
        prefixes=(
            ("python3.12", "-m", "pytest"),
            ("python3.12", "-m", "ruff"),
            ("python3.12", "-m", "compileall"),
            ("python3.12", "-m", "py_compile"),
        )
    )


def default_execution_policy() -> ExecutionPolicy:
    return ExecutionPolicy()


def extract_validation_candidates(
    root: str | os.PathLike[str],
    *,
    sources: Iterable[CandidateSource | str] | None = None,
    bounds: InventoryBounds | None = None,
) -> tuple[UntrustedCommandCandidate, ...]:
    """Read declared surfaces and return untrusted, never-executed candidates."""

    base = Path(root)
    selected = _selected_sources(sources)
    limit = bounds or InventoryBounds()
    files = _list_source_files(base, limit)
    found: list[UntrustedCommandCandidate] = []
    for path, relative in files:
        name = path.name.lower()
        try:
            text = _read_text(path, limit.max_file_bytes)
        except OSError:
            continue
        if CandidateSource.README in selected and name in _README_NAMES:
            found.extend(
                _candidates_from_markdown(text, CandidateSource.README, relative)
            )
        if CandidateSource.HISTORY in selected and name in _HISTORY_NAMES:
            found.extend(
                _candidates_from_markdown(text, CandidateSource.HISTORY, relative)
            )
        if CandidateSource.COMMENT in selected and _is_comment_file(path, name):
            found.extend(_candidates_from_comments(text, relative))
        if CandidateSource.PACKAGE in selected and name in _PACKAGE_NAMES:
            found.extend(_candidates_from_package(path, name, text, relative))
        if CandidateSource.CI in selected and _is_ci_file(path, name, relative):
            found.extend(_candidates_from_ci(text, relative))
    found.sort(key=lambda item: (item.source.value, item.path, item.line, item.command))
    return tuple(_unique(found))


def admit_candidates(
    candidates: Sequence[UntrustedCommandCandidate],
    *,
    allowlist: AdapterAllowlist | None,
    policy: ExecutionPolicy | None,
) -> tuple[AdmissionDecision, ...]:
    """Admit only allowlisted candidates that also pass execution policy."""

    return tuple(
        _admit_one(candidate, allowlist=allowlist, policy=policy)
        for candidate in candidates
    )


def discover_and_admit(
    root: str | os.PathLike[str],
    *,
    allowlist: AdapterAllowlist | None,
    policy: ExecutionPolicy | None = None,
    sources: Iterable[CandidateSource | str] | None = None,
    bounds: InventoryBounds | None = None,
) -> AdmissionReport:
    """Extract untrusted candidates then require allowlist plus policy."""

    candidates = extract_validation_candidates(root, sources=sources, bounds=bounds)
    decisions = admit_candidates(
        candidates,
        allowlist=allowlist,
        policy=policy if policy is not None else default_execution_policy(),
    )
    return AdmissionReport(candidates=candidates, decisions=decisions, executed=False)


def _selected_sources(
    sources: Iterable[CandidateSource | str] | None,
) -> frozenset[CandidateSource]:
    if sources is None:
        return frozenset(CandidateSource)
    selected: set[CandidateSource] = set()
    for item in sources:
        selected.add(item if isinstance(item, CandidateSource) else CandidateSource(item))
    return frozenset(selected)


def _is_comment_file(path: Path, name: str) -> bool:
    return path.suffix.lower() in _COMMENT_SUFFIXES or name in {"makefile", "gnumakefile"}


def _is_ci_file(path: Path, name: str, relative: str) -> bool:
    posix = relative.replace(os.sep, "/")
    if name in _CI_FILENAMES:
        return True
    if path.suffix.lower() not in _CI_SUFFIXES:
        return False
    return posix.startswith(".github/workflows/") or posix.startswith(".circleci/")


def _list_source_files(
    root: Path, bounds: InventoryBounds
) -> tuple[tuple[Path, str], ...]:
    try:
        root_stat = root.lstat()
    except OSError:
        return ()
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        return ()
    collected: list[tuple[Path, str]] = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    files_seen = 0
    while stack:
        current, depth = stack.pop()
        if depth > bounds.max_depth:
            continue
        try:
            entries = sorted(current.iterdir(), key=lambda item: item.name)
        except OSError:
            continue
        for entry in entries:
            try:
                info = entry.lstat()
            except OSError:
                continue
            if stat.S_ISLNK(info.st_mode):
                continue
            if stat.S_ISDIR(info.st_mode):
                if entry.name in _SKIP_DIRECTORIES:
                    continue
                stack.append((entry, depth + 1))
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            files_seen += 1
            if files_seen > bounds.max_files:
                return tuple(collected)
            relative = entry.relative_to(root).as_posix()
            collected.append((entry, relative))
    return tuple(collected)


def _read_text(path: Path, max_bytes: int) -> str:
    raw = path.read_bytes()[:max_bytes]
    return raw.decode("utf-8", errors="replace").replace("\x00", "")


def _candidates_from_markdown(
    text: str, source: CandidateSource, relative: str
) -> list[UntrustedCommandCandidate]:
    found: list[UntrustedCommandCandidate] = []
    for match in _FENCE_RE.finditer(text):
        lang = (match.group("lang") or "").strip().split()[0].lower() if match.group("lang") else ""
        if lang not in _FENCE_LANGS:
            continue
        body = match.group("body")
        start_line = text[: match.start()].count("\n") + 2
        for offset, raw_line in enumerate(body.splitlines()):
            command = _PROMPT_RE.sub("", raw_line).strip()
            if _looks_like_command(command):
                found.append(_candidate(command, source, relative, start_line + offset))
    for match in _INLINE_RE.finditer(text):
        command = match.group(1).strip()
        if _looks_like_command(command):
            line = text[: match.start()].count("\n") + 1
            found.append(_candidate(command, source, relative, line))
    return found


def _candidates_from_comments(text: str, relative: str) -> list[UntrustedCommandCandidate]:
    found: list[UntrustedCommandCandidate] = []
    for index, raw_line in enumerate(text.splitlines(), start=1):
        labeled = _COMMENT_LABELED_RE.match(raw_line)
        if labeled:
            command = labeled.group(1).strip()
            if _looks_like_command(command):
                found.append(_candidate(command, CandidateSource.COMMENT, relative, index))
            continue
        direct = _COMMENT_DIRECT_RE.match(raw_line)
        if direct:
            found.append(
                _candidate(direct.group("cmd").strip(), CandidateSource.COMMENT, relative, index)
            )
    return found


def _candidates_from_package(
    path: Path, name: str, text: str, relative: str
) -> list[UntrustedCommandCandidate]:
    if name == "package.json":
        return _candidates_from_package_json(text, relative)
    if name == "pyproject.toml":
        return _candidates_from_pyproject(text, relative)
    if name in {"makefile", "gnumakefile"}:
        return _candidates_from_makefile(text, relative)
    if name in {"tox.ini", "setup.cfg"}:
        return _candidates_from_ini_commands(text, relative)
    return []


def _candidates_from_package_json(text: str, relative: str) -> list[UntrustedCommandCandidate]:
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return []
    scripts = payload.get("scripts") if isinstance(payload, dict) else None
    if not isinstance(scripts, dict):
        return []
    found: list[UntrustedCommandCandidate] = []
    for value in scripts.values():
        if isinstance(value, str) and value.strip():
            found.append(_candidate(value.strip(), CandidateSource.PACKAGE, relative, 1))
    return found


def _candidates_from_pyproject(text: str, relative: str) -> list[UntrustedCommandCandidate]:
    try:
        payload = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    found: list[UntrustedCommandCandidate] = []
    for value in _toml_script_strings(payload):
        if _looks_like_command(value) or value.strip():
            found.append(_candidate(value.strip(), CandidateSource.PACKAGE, relative, 1))
    return found


def _toml_script_strings(value: object, *, table_name: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            name = str(key)
            if name in {"scripts", "commands"} and isinstance(nested, dict):
                for item in nested.values():
                    if isinstance(item, str) and item.strip():
                        found.append(item.strip())
            else:
                found.extend(_toml_script_strings(nested, table_name=name))
    return found


def _candidates_from_makefile(text: str, relative: str) -> list[UntrustedCommandCandidate]:
    found: list[UntrustedCommandCandidate] = []
    for index, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.startswith("\t"):
            continue
        command = raw_line.strip()
        if command.startswith(("@", "-", "+")):
            command = command[1:].strip()
        if _looks_like_command(command):
            found.append(_candidate(command, CandidateSource.PACKAGE, relative, index))
    return found


def _candidates_from_ini_commands(text: str, relative: str) -> list[UntrustedCommandCandidate]:
    found: list[UntrustedCommandCandidate] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = _TOX_COMMANDS_RE.match(lines[index])
        if match is None:
            index += 1
            continue
        rest = match.group(1).strip()
        if rest:
            found.append(_candidate(rest, CandidateSource.PACKAGE, relative, index + 1))
            index += 1
            continue
        index += 1
        while index < len(lines):
            nxt = lines[index]
            if not nxt.strip():
                index += 1
                continue
            if nxt[:1] in {" ", "\t"}:
                command = nxt.strip()
                if command:
                    found.append(
                        _candidate(command, CandidateSource.PACKAGE, relative, index + 1)
                    )
                index += 1
                continue
            break
    return found


def _candidates_from_ci(text: str, relative: str) -> list[UntrustedCommandCandidate]:
    found: list[UntrustedCommandCandidate] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = _YAML_RUN_RE.match(lines[index])
        if match is None:
            index += 1
            continue
        indent = len(match.group(1))
        rest = match.group(2).strip()
        if rest in {"|", ">", "|-", ">-", "|+", ">+"} or rest.endswith("|"):
            index += 1
            while index < len(lines):
                nxt = lines[index]
                if not nxt.strip():
                    index += 1
                    continue
                nxt_indent = len(nxt) - len(nxt.lstrip(" "))
                if nxt_indent <= indent:
                    break
                command = nxt.strip()
                if command:
                    found.append(_candidate(command, CandidateSource.CI, relative, index + 1))
                index += 1
            continue
        if rest:
            found.append(
                _candidate(rest.strip("\"'"), CandidateSource.CI, relative, index + 1)
            )
        index += 1
    return found


def _looks_like_command(command: str) -> bool:
    text = command.strip()
    if not text or text.startswith(("#", "//", "--", "*", "- ")):
        return False
    if text.startswith(("http://", "https://", "ftp://")):
        return False
    return _COMMAND_START_RE.match(text) is not None


def _candidate(
    command: str, source: CandidateSource, relative: str, line: int
) -> UntrustedCommandCandidate:
    return UntrustedCommandCandidate(
        command=_normalize_command(command),
        source=source,
        path=str(PurePosixPath(relative)),
        line=line,
        trusted=False,
        executed=False,
    )


def _normalize_command(command: str) -> str:
    return " ".join(command.strip().split())


def _unique(
    candidates: Sequence[UntrustedCommandCandidate],
) -> list[UntrustedCommandCandidate]:
    seen: set[tuple[str, str, str, int]] = set()
    unique: list[UntrustedCommandCandidate] = []
    for item in candidates:
        key = (item.source.value, item.path, item.command, item.line)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _admit_one(
    candidate: UntrustedCommandCandidate,
    *,
    allowlist: AdapterAllowlist | None,
    policy: ExecutionPolicy | None,
) -> AdmissionDecision:
    if allowlist is None:
        return _reject(candidate, AdmissionReason.ALLOWLIST_REQUIRED)
    if policy is None:
        return _reject(candidate, AdmissionReason.POLICY_REQUIRED)
    command = candidate.command.strip()
    if not command:
        return _reject(candidate, AdmissionReason.EMPTY_COMMAND)
    if len(command.encode("utf-8")) > policy.max_command_bytes:
        return _reject(candidate, AdmissionReason.COMMAND_TOO_LONG)
    if not policy.allow_shell and _SHELL_META_RE.search(command):
        return _reject(candidate, AdmissionReason.SHELL_METACHARACTERS)
    if _ENV_ASSIGN_RE.match(command):
        return _reject(candidate, AdmissionReason.ENV_ASSIGNMENT_DENIED)
    try:
        argv = tuple(shlex.split(command, posix=True))
    except ValueError:
        return _reject(candidate, AdmissionReason.UNSTRUCTURED_ARGV)
    if policy.require_structured_argv and not argv:
        return _reject(candidate, AdmissionReason.UNSTRUCTURED_ARGV)
    if len(argv) > policy.max_argv:
        return _reject(candidate, AdmissionReason.ARGV_TOO_LONG)
    if "-c" in argv[:4]:
        return _reject(candidate, AdmissionReason.INLINE_PYTHON_DENIED)
    executable = Path(argv[0]).name if argv else ""
    if policy.network == "deny" and executable in _NETWORK_EXECUTABLES:
        return _reject(candidate, AdmissionReason.NETWORK_TOOL_DENIED, argv)
    if not policy.allow_mutation and executable in _MUTATION_EXECUTABLES:
        return _reject(candidate, AdmissionReason.MUTATION_TOOL_DENIED, argv)
    if not policy.allow_eval and (
        executable in _EVAL_EXECUTABLES or argv[:2] in {("bash", "-c"), ("sh", "-c")}
    ):
        return _reject(candidate, AdmissionReason.EVAL_DENIED, argv)
    if not allowlist.matches(argv):
        return _reject(candidate, AdmissionReason.NOT_ALLOWLISTED, argv)
    return AdmissionDecision(
        candidate=candidate,
        admitted=True,
        reason=AdmissionReason.ADMITTED.value,
        argv=argv,
        trusted=False,
        executed=False,
    )


def _reject(
    candidate: UntrustedCommandCandidate,
    reason: AdmissionReason,
    argv: tuple[str, ...] = (),
) -> AdmissionDecision:
    return AdmissionDecision(
        candidate=candidate,
        admitted=False,
        reason=reason.value,
        argv=argv,
        trusted=False,
        executed=False,
    )


__all__ = (
    "SCHEMA",
    "TRUST_CLASS",
    "CANDIDATES_ARE_TRUSTED",
    "CANDIDATES_MAY_EXECUTE",
    "AdapterAllowlist",
    "AdmissionDecision",
    "AdmissionReason",
    "AdmissionReport",
    "CandidateSource",
    "ExecutionPolicy",
    "InventoryBounds",
    "UntrustedCommandCandidate",
    "admit_candidates",
    "default_execution_policy",
    "discover_and_admit",
    "extract_validation_candidates",
    "python_adapter_allowlist",
)
