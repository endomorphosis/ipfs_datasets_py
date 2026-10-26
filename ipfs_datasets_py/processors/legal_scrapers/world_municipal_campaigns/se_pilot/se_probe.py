"""Sweden pilot — route probe.

For each sampled kommun: resolve the official site, fetch robots.txt
(posture recorded BEFORE any content fetch), fetch the homepage, and
look for a författningssamling / föreskrifter collection link.
Checkpoints probe_state.json after every kommun.
"""
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

OUT = Path(__file__).resolve().parent
STATE = OUT / "probe_state.json"
RETRIEVED = "2026-10-14"

SAMPLE = [
    ("0180", "Stockholm"), ("1480", "Göteborg"), ("1280", "Malmö"),
    ("0380", "Uppsala"), ("0580", "Linköping"), ("1880", "Örebro"),
    ("2480", "Umeå"), ("2580", "Luleå"), ("0680", "Jönköping"),
    ("1980", "Västerås"), ("0980", "Gotland"), ("2180", "Gävle"),
]

UA = {"User-Agent": "world-municipal-law-pilot/1.0 (research; polite harvest)"}


def slug(name):
    s = unicodedata.normalize("NFKD", name.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s)


def fetch(session, url, timeout=60):
    t0 = time.monotonic()
    try:
        r = session.get(url, timeout=timeout, headers=UA)
        return {"url": url, "status": r.status_code, "final_url": r.url,
                "seconds": round(time.monotonic() - t0, 1),
                "bytes": len(r.content), "text": r.text}
    except Exception as e:  # noqa: BLE001
        return {"url": url, "status": None, "error": f"{type(e).__name__}: {e}",
                "seconds": round(time.monotonic() - t0, 1), "text": ""}


def main():
    state = json.loads(STATE.read_text()) if STATE.exists() else {"kommuner": {}}
    s = requests.Session()
    for code, name in SAMPLE:
        if code in state["kommuner"]:
            print(f"[{code}] already probed, skip", flush=True)
            continue
        print(f"[{code}] {name} ...", flush=True)
        entry = {"name": name, "candidates": [], "site": None}
        sl = slug(name)
        cands = [f"https://www.{sl}.se", f"https://{sl}.se",
                 f"https://www.{sl}.se/", f"https://{sl}.se/"]
        home = None
        for cand in dict.fromkeys(cands):
            res = fetch(s, cand)
            entry["candidates"].append({k: res.get(k) for k in
                                        ("url", "status", "final_url", "error", "seconds")})
            if res.get("status") and res["status"] < 400 and res.get("text"):
                home = res
                break
            time.sleep(2)
        if home is None:
            entry["error"] = "no candidate homepage responded <400"
            state["kommuner"][code] = entry
            STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False))
            continue
        base = home["final_url"]
        entry["site"] = base
        entry["platform_hints"] = sorted({
            h for h in ("episerver", "optimizely", "sitevision", "wordpress",
                        "drupal", "typo3", "sharepoint")
            if h in home["text"].lower()})
        # robots posture BEFORE content harvest
        robots_url = urljoin(base, "/robots.txt")
        rob = fetch(s, robots_url)
        entry["robots"] = {k: rob.get(k) for k in ("url", "status", "error", "seconds")}
        if rob.get("status") == 200:
            (OUT / "scratch" / f"robots_{code}.txt").write_text(rob["text"], encoding="utf-8")
            entry["robots_disallow_all"] = bool(
                re.search(r"User-agent:\s*\*\s*\n\s*Disallow:\s*/\s*$", rob["text"], re.M))
            entry["robots_sitemap"] = re.findall(r"(?im)^Sitemap:\s*(\S+)", rob["text"])[:3]
        time.sleep(2)
        # find författningssamling links on homepage
        links = []
        for href, txt in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                                    home["text"], re.S | re.I):
            t = re.sub(r"<[^>]+>", " ", txt).strip().lower()
            h = href.lower()
            if ("forfattning" in h or "forfattning" in t or "föreskrift" in t
                    or "foreskrift" in h or "reglemente" in t):
                links.append({"href": urljoin(base, href), "text": t[:80]})
        entry["home_collection_links"] = links[:10]
        entry["home_bytes"] = home["bytes"]
        state["kommuner"][code] = entry
        STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False))
        print(f"[{code}] site={base} platform={entry['platform_hints']} "
              f"robots={entry['robots'].get('status')} links={len(links)}", flush=True)
        time.sleep(2)
    print("probe done")


if __name__ == "__main__":
    main()
