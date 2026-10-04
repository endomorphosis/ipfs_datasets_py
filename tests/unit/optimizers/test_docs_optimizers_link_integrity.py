"""Guard docs/optimizers local markdown links against drift."""

from __future__ import annotations

import re
from pathlib import Path


def test_docs_optimizers_local_markdown_links_resolve() -> None:
    docs_root = Path(__file__).resolve().parents[3] / "docs" / "optimizers"
    assert docs_root.exists(), f"Missing docs root: {docs_root}"

    markdown_files = sorted(docs_root.rglob("*.md"))
    assert markdown_files, "No optimizer markdown docs found"

    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    missing: list[tuple[Path, str]] = []

    for md_file in markdown_files:
        text = md_file.read_text(encoding="utf-8", errors="ignore")
        for match in link_pattern.finditer(text):
            link = match.group(1).strip()
            if not link:
                continue
            if link.startswith(("http://", "https://", "#", "mailto:")):
                continue
            if not (link.startswith("./") or link.startswith("../") or link.endswith(".md")):
                continue

            target = (md_file.parent / link).resolve()
            if not target.exists():
                missing.append((md_file.relative_to(docs_root), link))

    assert not missing, "Broken local doc links:\n" + "\n".join(
        f"- {doc} -> {link}" for doc, link in missing
    )
