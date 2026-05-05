"""Reusable prompt context selection helpers for todo daemons."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .engine import read_text


DEFAULT_CONTEXT_STOPWORDS = frozenset(
    {
        "and",
        "the",
        "with",
        "for",
        "into",
        "from",
        "full",
        "port",
        "initial",
        "browser",
        "native",
        "typescript",
        "python",
        "parity",
    }
)

DEFAULT_CONTEXT_SUFFIXES = (".ts", ".tsx", ".json", ".py", ".md")


def task_title_tokens(
    task_or_title: Any,
    *,
    stopwords: Iterable[str] = DEFAULT_CONTEXT_STOPWORDS,
    min_length: int = 3,
) -> list[str]:
    """Return stable search tokens from a task title or task-like object."""

    if task_or_title is None:
        return []
    title = task_or_title if isinstance(task_or_title, str) else getattr(task_or_title, "title", "")
    ignored = {str(word).lower() for word in stopwords}
    return [
        token
        for token in re.findall(r"[A-Za-z0-9]+", str(title).lower())
        if len(token) >= min_length and token not in ignored
    ]


def rank_relevant_context_file(
    path: str,
    tokens: Sequence[str],
    *,
    path_token_bonus: int = 5,
    basename_exact_bonus: int = 12,
    basename_contains_bonus: int = 8,
    test_file_bonus: int = 2,
    preferred_path_fragments: Sequence[str] = (),
    preferred_path_bonus: int = 1,
) -> int:
    """Score a candidate file path against task tokens."""

    normalized = path.lower()
    score = 0
    for token in tokens:
        if token in normalized:
            score += path_token_bonus
    basename = Path(path).stem.lower()
    for token in tokens:
        if token == basename:
            score += basename_exact_bonus
        elif token in basename:
            score += basename_contains_bonus
    if path.endswith(".test.ts"):
        score += test_file_bonus
    if any(fragment.lower() in normalized for fragment in preferred_path_fragments):
        score += preferred_path_bonus
    return score


def select_relevant_context_paths(
    tracked_files: str,
    tokens: Sequence[str],
    *,
    allowed_prefixes: Sequence[str] = (),
    suffixes: Sequence[str] = DEFAULT_CONTEXT_SUFFIXES,
    max_files: int = 6,
    preferred_path_fragments: Sequence[str] = (),
) -> list[str]:
    """Select tracked files most relevant to a task token set."""

    if not tokens or max_files <= 0:
        return []
    candidates: list[tuple[int, str]] = []
    prefixes = tuple(prefix for prefix in allowed_prefixes if prefix)
    for raw in tracked_files.splitlines():
        path = raw.strip()
        if not path:
            continue
        if prefixes and not path.startswith(prefixes):
            continue
        if suffixes and not path.endswith(tuple(suffixes)):
            continue
        score = rank_relevant_context_file(
            path,
            tokens,
            preferred_path_fragments=preferred_path_fragments,
        )
        if score > 0:
            candidates.append((score, path))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    selected: list[str] = []
    seen: set[str] = set()
    for _score, path in candidates:
        if path in seen:
            continue
        seen.add(path)
        selected.append(path)
        if len(selected) >= max_files:
            break
    return selected


def render_relevant_file_context(
    *,
    repo_root: Path,
    tracked_files: str,
    task_or_title: Any,
    allowed_prefixes: Sequence[str] = (),
    suffixes: Sequence[str] = DEFAULT_CONTEXT_SUFFIXES,
    max_files: int = 6,
    max_file_chars: int = 12000,
    preferred_path_fragments: Sequence[str] = (),
    no_tokens_message: str = "[No selected task tokens available.]",
    no_files_message: str = "[No relevant current file contents selected.]",
    read_text_fn: Callable[[Path], str] | None = None,
) -> str:
    """Render focused file contents for prompt context."""

    tokens = task_title_tokens(task_or_title)
    if not tokens:
        return no_tokens_message
    paths = select_relevant_context_paths(
        tracked_files,
        tokens,
        allowed_prefixes=allowed_prefixes,
        suffixes=suffixes,
        max_files=max_files,
        preferred_path_fragments=preferred_path_fragments,
    )
    sections: list[str] = []
    reader = read_text_fn or (lambda path: read_text(path, limit=max_file_chars))
    for path_text in paths:
        path = repo_root / path_text
        if not path.exists() or not path.is_file():
            continue
        sections.append(f"### {path_text}\n```\n{reader(path)}\n```")
    return "\n\n".join(sections) if sections else no_files_message
