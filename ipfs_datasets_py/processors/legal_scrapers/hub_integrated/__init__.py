"""Scrapers and normalizers vendored from the Hugging Face legal repos.

The catalogued national collectors stay in ``national_collectors``.
The 19-column municipal normalizer stays in ``world_municipal``.
This package holds the remaining Hub sources that were not already modules
the query path imports.

Sources re-read on 2026-11-07. The 2026-11-06 pins were
``a32341327caac8ef45bf86f39a8a5f7a39d8f306``,
``e751144482c93924004ef42bf38ea1598a9a9b12``, and
``e8169767dcb69aff9e09e27f13e7450a031d95dc``.
The pipeline tip moved to the county-lane sync at ``26004b9f7963``.
The legal_scrapers and world_law_scrapers tips added a
``scrapers_and_normalizers`` overlay and did not change existing files.
That overlay was not copied again. Nested ``ipfs_datasets_py`` copies,
a broken virtualenv, and county entry dumps were not vendored.

- dataset ``endomorphosis/legal_scrapers`` at ``752ba7c010802563d6a0d277592d4f92a812c83e``
- model ``endomorphosis/world_law_pipeline`` at ``26004b9f79637373bd8dc0dffb7dbc36aa09c595``
- dataset ``justicedao/world_law_scrapers`` at ``6b0cef28733436be7a0ea554ab30dcd81834a64e``

Paths under ``/workspace/legal-corpora``, ``/workspace/legal_scrapers``,
``/workspace/world_law``, and ``/home/box/tessdata`` are rewritten to env
roots on files this refresh wrote. Importing this package does not import
those collectors and does not read ``endomorphosis`` at query time.
"""

from __future__ import annotations

from pathlib import Path

LEGAL_SCRAPERS_DATASET = "endomorphosis/legal_scrapers"
LEGAL_SCRAPERS_SHA = "752ba7c010802563d6a0d277592d4f92a812c83e"
WORLD_LAW_PIPELINE_MODEL = "endomorphosis/world_law_pipeline"
WORLD_LAW_PIPELINE_SHA = "26004b9f79637373bd8dc0dffb7dbc36aa09c595"
JUSTICEDAO_WORLD_LAW_SCRAPERS = "justicedao/world_law_scrapers"
JUSTICEDAO_WORLD_LAW_SCRAPERS_SHA = "6b0cef28733436be7a0ea554ab30dcd81834a64e"


def vendored_python_files() -> tuple[Path, ...]:
    """Return vendored Python files under this package, excluding this module."""

    root = Path(__file__).resolve().parent
    return tuple(sorted(path for path in root.rglob("*.py") if path.name != "__init__.py"))
