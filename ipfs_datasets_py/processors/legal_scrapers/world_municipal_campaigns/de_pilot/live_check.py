#!/usr/bin/env python3
"""Live reachability + robots check for winner hosts (patient retries)."""
import json
import re
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent.parent
S = requests.Session()
S.headers["User-Agent"] = (
    "ipfs_datasets_py world-municipal pilot (open legal data research)"
)

HOSTS = [
    ("heide.de", "https://www.heide.de/fileadmin/heide.de/rathaus/pdf-dateien/ortsrecht/satzungen/2.1._Hauptsatzung_Stadt_Heide.pdf"),
    ("brunsbuettel.de", "https://www.brunsbuettel.de/rathaus/satzungen/001.pdf"),
    ("ahaus.de", "https://www.ahaus.de/fileadmin/ahaus/Rathaus/Ortsrecht/10.3.pdf"),
    ("borken.de", "https://www.borken.de/fileadmin/daten/mandanten/kreisstadt/PDF-Dokumente/Rathaus/Ortsrecht/AllgemSatzungenVerordnungen/Abfallentsorgung.pdf"),
]


def get(url, timeout=50, tries=3):
    last = None
    for i in range(tries):
        try:
            return S.get(url, timeout=timeout)
        except Exception as e:
            last = e
            time.sleep(8 * (i + 1))
    raise last


def main():
    out = []
    for host, sample in HOSTS:
        rec = {"host": host}
        try:
            rb = get(f"https://{host}/robots.txt", timeout=40)
            rec["robots_status"] = rb.status_code
            txt = rb.text
            # extract the * group rules
            rec["robots_disallow"] = re.findall(r"(?im)^\s*Disallow:\s*(\S+)", txt)[:15]
            m = re.search(r"(?im)^\s*Crawl-delay:\s*(\S+)", txt)
            rec["crawl_delay"] = m.group(1) if m else ""
            (HERE / "raw" / f"robots_{host.replace('.', '_')}.txt").write_text(
                txt, encoding="utf-8")
        except Exception as e:
            rec["robots_error"] = f"{type(e).__name__}: {str(e)[:90]}"
        try:
            r = get(sample, timeout=60)
            rec["sample_status"] = r.status_code
            rec["sample_bytes"] = len(r.content)
            rec["sample_type"] = r.headers.get("Content-Type", "")
            rec["sample_url"] = sample
        except Exception as e:
            rec["sample_error"] = f"{type(e).__name__}: {str(e)[:90]}"
        print(json.dumps(rec, ensure_ascii=False), flush=True)
        out.append(rec)
        time.sleep(3)
    (HERE / "raw" / "live_check.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
