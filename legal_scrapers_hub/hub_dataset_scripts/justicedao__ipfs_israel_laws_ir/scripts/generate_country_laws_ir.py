#!/usr/bin/env python3
"""Generation entrypoint copied into Hub dataset repos."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from country_laws_ir.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
