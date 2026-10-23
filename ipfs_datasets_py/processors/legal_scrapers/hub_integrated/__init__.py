"""Scrapers and normalizers vendored from the Hugging Face legal repos.

The catalogued national collectors stay in ``national_collectors``.
The 19-column municipal normalizer stays in ``world_municipal``.
This package holds the remaining Hub sources that were not already modules
the query path imports.

Sources read on 2026-10-21. The 2026-10-17 pins were
``c3a8fc1e90888312f6dc3d76e04604936f1e02f3`` and
``a37e6c1f9bbff47f3a3c175668f1f737110209f1``.

- dataset ``endomorphosis/legal_scrapers`` at ``8295eebd6fb75202e89fdeefe423bd3ba6bf9cc6``
- model ``endomorphosis/world_law_pipeline`` at ``da0447c4adeb6a134cd539a8a9d23c9d80fe59c1``
- dataset ``justicedao/world_law_scrapers`` at ``1b6274b536baf8cd0657f6a04694760f96822836``

Paths under ``/workspace/legal-corpora``, ``/workspace/legal_scrapers``, and
``/home/box/tessdata`` are rewritten to env roots. Several pipeline scrapers
still default ``WORLD_LAW_ROOT`` to ``/workspace/world_law`` when that variable
is unset. Importing this package does not import those collectors and does
not read ``endomorphosis`` at query time.
"""

from __future__ import annotations

from pathlib import Path

LEGAL_SCRAPERS_DATASET = "endomorphosis/legal_scrapers"
LEGAL_SCRAPERS_SHA = "8295eebd6fb75202e89fdeefe423bd3ba6bf9cc6"
WORLD_LAW_PIPELINE_MODEL = "endomorphosis/world_law_pipeline"
WORLD_LAW_PIPELINE_SHA = "da0447c4adeb6a134cd539a8a9d23c9d80fe59c1"
JUSTICEDAO_WORLD_LAW_SCRAPERS = "justicedao/world_law_scrapers"
JUSTICEDAO_WORLD_LAW_SCRAPERS_SHA = "1b6274b536baf8cd0657f6a04694760f96822836"


def vendored_python_files() -> tuple[Path, ...]:
    """Return vendored Python files under this package, excluding this module."""

    root = Path(__file__).resolve().parent
    return tuple(sorted(path for path in root.rglob("*.py") if path.name != "__init__.py"))
