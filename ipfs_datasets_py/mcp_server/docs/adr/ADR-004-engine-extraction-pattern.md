# ADR-004: Engine Extraction Pattern

**Status:** Accepted  
**Date:** 2026-02-20  
**Author:** MCP Server Team

---

## Context

After ADR-001 established the thin-wrapper pattern, a consistent naming and
placement convention was needed for the extracted engine modules to keep the
codebase navigable as refactoring scaled to 190+ files.

## Decision

Extracted engine modules follow a **canonical location** convention:

| Source domain | Canonical package |
|---|---|
| Multimedia (FFmpeg, yt-dlp, email, Discord) | `ipfs_datasets_py.processors.multimedia.*_engine` |
| Legal scrapers | `ipfs_datasets_py.processors.legal_scrapers.*_engine` |
| Development tools (DAG, Kubernetes, GitHub Actions…) | `ipfs_datasets_py.processors.development.*_engine` |
| PDF processing | `ipfs_datasets_py.processors.specialized.pdf.*_engine` |
| Embeddings | `ipfs_datasets_py.embeddings.*_engine` |
| Web archiving | `ipfs_datasets_py.web_archiving.*_engine` |
| Analytics | `ipfs_datasets_py.analytics.*_engine` |
| Monitoring | `ipfs_datasets_py.monitoring_engine` (root) |

**Naming convention:**  `<feature>_engine.py` — always suffixed with `_engine`.

**`__init__.py` re-exports:**  Each canonical package's `__init__.py` re-exports
the public functions of every engine it contains so callers can use:
```python
from ipfs_datasets_py.processors.multimedia import ffmpeg_edit_media
```

**Compat shims:**  The old MCP tool file becomes a 3–15 line shim that imports
and re-exports from the canonical location.  Old callers continue to work.

## Consequences

### Positive
- Any function can be called from CLI, tests, or library code without importing
  the MCP layer.
- Grep / IDE navigation is predictable: "all engine code is in `processors/`".
- New contributors follow a clear template.

### Negative
- Large one-time refactoring effort (mitigated by automation across 24 sessions).
- Some engine locations feel counterintuitive (e.g., monitoring at root level).

### Neutral
- `processors/__init__.py` does **not** re-export all engines to avoid circular
  imports; callers must use sub-package imports.

## References

- `ipfs_datasets_py/processors/` directory tree
- Sessions 1–21 commit history on branch `copilot/refactor-markdown-files-again`
