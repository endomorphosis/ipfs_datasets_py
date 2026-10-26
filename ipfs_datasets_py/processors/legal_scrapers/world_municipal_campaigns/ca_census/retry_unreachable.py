#!/usr/bin/env python3
"""Strip site_unreachable rows from census_raw.jsonl (backing the file up
first) so census_classify.py re-attempts them on its next run. Egress
windows poisoned many classifications; genuine dead sites will simply
come back as site_unreachable again."""
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CENSUS = HERE.parent
raw = CENSUS / "census_raw.jsonl"
rows = [json.loads(l) for l in open(raw)]
keep = [r for r in rows if r.get("census_status") != "site_unreachable"]
removed = len(rows) - len(keep)
if removed == 0:
    print("no site_unreachable rows to retry")
    sys.exit(0)
backup = CENSUS / f"census_raw_backup_{time.strftime('%H%M%S')}.jsonl"
shutil.copy(raw, backup)
with open(raw, "w") as fh:
    for r in keep:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"removed {removed} site_unreachable rows (backup: {backup.name}); "
      f"{len(keep)} rows kept")
