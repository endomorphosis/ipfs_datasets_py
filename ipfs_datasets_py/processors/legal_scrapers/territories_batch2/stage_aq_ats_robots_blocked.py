#!/usr/bin/env python3
"""Antarctic Treaty System (AQ) — robots block staging.

https://www.ats.aq/robots.txt has `User-agent: * Disallow: /`.
Per standing crawl rules we do NOT fetch Treaty/Protocol/Annex HTML from ats.aq.
This stages scrapers_and_normalizers + README/validation only (no 0-row parquet).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("MALLOC_ARENA_MAX", "2")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from wave2b_common import ROOT, utcnow, write_json  # noqa: E402


def main() -> int:
    out = ROOT / "AQ" / "upload_ready"
    scrapers = out / "scrapers_and_normalizers"
    scrapers.mkdir(parents=True, exist_ok=True)
    src = Path(__file__).resolve()
    (scrapers / src.name).write_bytes(src.read_bytes())
    (scrapers / "wave2b_common.py").write_bytes((src.parent / "wave2b_common.py").read_bytes())
    stub = '''#!/usr/bin/env python3
"""Future ATS collector — gated on robots.txt Allow for User-agent *."""
ATS = "https://www.ats.aq/"
TARGETS = [
    "The Antarctic Treaty (1959)",
    "Protocol on Environmental Protection (Madrid Protocol)",
    "Annexes I-VI",
]
def main():
    raise SystemExit("Blocked: ats.aq robots.txt Disallow:/ for User-agent *")
if __name__ == "__main__":
    main()
'''
    (scrapers / "collect_aq_ats.py").write_text(stub, encoding="utf-8")
    (out / "README.md").write_text(
        f"""# Antarctica (AQ) — code-only staging

Official portal candidate: https://www.ats.aq/

**Network collection skipped**: `robots.txt` for User-agent * is `Disallow: /`.
Standing Country-law-scraper rules forbid captcha/WAF/login bypass and require
respecting robots.txt.

When ATS robots allow machine retrieval of the Antarctic Treaty, Madrid
Protocol, and Annexes, run `scrapers_and_normalizers/collect_aq_ats.py`.

Retrieved: {utcnow()}
Push: NOT_PUSHED
""",
        encoding="utf-8",
    )
    write_json(
        out / "validation.json",
        {
            "jurisdiction": "AQ",
            "target_hf_repo": "endomorphosis/ipfs_antarctica_laws",
            "laws": 0,
            "articles": 0,
            "network_fetch": False,
            "robots_block": "https://www.ats.aq/robots.txt User-agent:* Disallow:/",
            "push": "NOT_PUSHED",
            "parquet_written": False,
        },
    )
    print("AQ code-only staged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
