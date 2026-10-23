"""Japan pilot — probe 2b: parallel Reiki-Base path sweep.

Same hosts/paths as jp_probe2 but 6-way concurrent, 15 s timeouts, and
results appended per-host to probe2_results.jsonl (restart-safe).
"""
import json
import time
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
    entry = {"code": code, "name": name, "host": host, "probes": []}
    try:
        r = s.get(f"https://{host}/robots.txt", headers=HEADERS, timeout=15)
        entry["robots_status"] = r.status_code
        entry["robots_disallow"] = [
            ln.strip() for ln in (r.text or "").splitlines()
            if ln.strip().lower().startswith("disallow")
            and ("reiki" in ln.lower() or "d1w" in ln.lower())]
    except Exception as e:  # noqa: BLE001
        entry["robots_error"] = type(e).__name__
    for p in PATHS:
        url = f"https://{host}{p}"
        try:
            r = s.get(url, headers=HEADERS, timeout=15)
            marker = ("Reiki-Base" in r.text) or ("ぎょうせい" in r.text) or ("GYOSEI" in r.text)
            entry["probes"].append({"path": p, "status": r.status_code,
                                    "reiki_base": marker, "bytes": len(r.content)})
        except Exception as e:  # noqa: BLE001
            entry["probes"].append({"path": p, "error": type(e).__name__})
        time.sleep(0.3)
    return entry


def main():
    dest = OUT / "probe2_results.jsonl"
    done = set()
    if dest.exists():
        done = {json.loads(l)["code"] for l in dest.read_text().splitlines() if l.strip()}
    todo = [(c, v) for c, v in HOSTS.items() if c not in done]
    print(f"{len(todo)} hosts to probe ({len(done)} already done)", flush=True)
    with dest.open("a", encoding="utf-8") as f, ThreadPoolExecutor(max_workers=6) as ex:
        for entry in ex.map(probe, todo):
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
            hits = [h for h in entry["probes"] if h.get("status") == 200]
            if hits:
                print(entry["code"], entry["name"], "HIT", hits, flush=True)
    print("done")


if __name__ == "__main__":
    main()
