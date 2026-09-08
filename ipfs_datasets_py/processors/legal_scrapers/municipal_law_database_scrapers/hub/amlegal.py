"""American Legal Publishing family (codelibrary.amlegal.com).

Uses the public unauthenticated JSON API under /api/. Implementation lives
in ``amlegal_draft.py`` until promoted after broader soak testing.
"""

from __future__ import annotations

from typing import Any

from .amlegal_draft import PUBLISHER, scrape_jurisdiction, scrape_rows  # noqa: F401

__all__ = ["PUBLISHER", "scrape_rows", "scrape_jurisdiction"]
