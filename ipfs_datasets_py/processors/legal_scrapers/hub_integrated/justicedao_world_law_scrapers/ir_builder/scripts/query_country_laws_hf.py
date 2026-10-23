#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from country_laws_ir.query import main

if __name__ == "__main__":
    raise SystemExit(main())
