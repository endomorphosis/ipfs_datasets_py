"""Japan pilot — probe 3: redirect map for reiki entry paths (no following).

For each host, GET /d1w_reiki/reiki.html and /reiki/reiki.html with
allow_redirects=False; record status + Location. Reveals which vendor
platform each city points at (d1-law.com, g-reiki.net, self-hosted...).
"""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 world-municipal-law-pilot/0.1"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.5"}
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from jp_probe2 import HOSTS, PATHS  # noqa: E402


def probe(item):
    code, (name, host) = item
    s = requests.Session()
    out = {"code": code, "name": name, "host": host, "results": []}
    for p in PATHS:
        try:
            r = s.get(f"https://{host}{p}", headers=HEADERS, timeout=15,
                      allow_redirects=False)
            out["results"].append({"path": p, "status": r.status_code,
                                   "location": r.headers.get("Location", "")})
        except Exception as e:  # noqa: BLE001
            out["results"].append({"path": p, "error": type(e).__name__})
    return out


def main():
    dest = OUT / "probe3_results.jsonl"
    with dest.open("w", encoding="utf-8") as f, ThreadPoolExecutor(max_workers=6) as ex:
        for entry in ex.map(probe, HOSTS.items()):
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
            for r in entry["results"]:
                loc = r.get("location", "")
                if r.get("status") in (301, 302, 307, 308) and loc:
                    print(entry["code"], entry["name"], r["path"], "->", loc, flush=True)
    print("done")


if __name__ == "__main__":
    main()
