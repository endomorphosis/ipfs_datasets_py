
from __future__ import annotations

from pathlib import Path


def _find_repo_root(start: Path) -> Path:
	for candidate in (start, *start.parents):
		if (candidate / "pyproject.toml").exists() or (candidate / "__pyproject.toml").exists():
			return candidate
	return start


REPO_ROOT: Path = _find_repo_root(Path(__file__).resolve())

