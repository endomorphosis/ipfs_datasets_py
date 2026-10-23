#!/usr/bin/env python3
"""CLI wrapper for country_laws_ir.query."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from country_laws_ir.query import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
