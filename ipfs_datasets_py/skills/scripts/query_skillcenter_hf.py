#!/usr/bin/env python3
"""Run the canonical SkillCenter remote query client from repo or release."""

from __future__ import annotations

from pathlib import Path
import runpy


ROOT = Path(__file__).resolve().parents[3]
CANDIDATES = (
    ROOT / "scripts" / "query_skillcenter_hf.py",
    ROOT / "scripts" / "ops" / "intent_ir" / "query_skillcenter_hf.py",
)
for candidate in CANDIDATES:
    if candidate.is_file():
        runpy.run_path(str(candidate), run_name="__main__")
        break
else:
    raise SystemExit("SkillCenter query client is missing from this package")
