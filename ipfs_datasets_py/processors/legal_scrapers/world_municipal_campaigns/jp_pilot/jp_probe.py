"""Japan pilot — homepage probe: find each city's 例規集 (reiki) entry point.

Robots-checked per host. Records homepage status, robots status, and any
links whose text or href mentions 例規 / reiki. Output: probe_results.json.
"""
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 world-municipal-law-pilot/0.1"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.5"}

CITIES = {
    "01100": ("札幌市", "https://www.city.sapporo.jp/"),
    "04100": ("仙台市", "https://www.city.sendai.jp/"),
    "11100": ("さいたま市", "https://www.city.saitama.jp/"),
    "12100": ("千葉市", "https://www.city.chiba.jp/"),
    "13100": ("東京都", "https://www.metro.tokyo.lg.jp/"),
    "14100": ("横浜市", "https://www.city.yokohama.lg.jp/"),
    "14130": ("川崎市", "https://www.city.kawasaki.jp/"),
    "15100": ("新潟市", "https://www.city.niigata.lg.jp/"),
    "22100": ("静岡市", "https://www.city.shizuoka.lg.jp/"),
    "23100": ("名古屋市", "https://www.city.nagoya.jp/"),
    "26100": ("京都市", "https://www.city.kyoto.lg.jp/"),
    "27100": ("大阪市", "https://www.city.osaka.lg.jp/"),
    "28100": ("神戸市", "https://www.city.kobe.lg.jp/"),
    "33100": ("岡山市", "https://www.city.okayama.jp/"),
    "34100": ("広島市", "https://www.city.hiroshima.lg.jp/"),
    "40100": ("北九州市", "https://www.city.kitakyushu.lg.jp/"),
    "40130": ("福岡市", "https://www.city.fukuoka.lg.jp/"),
    "43100": ("熊本市", "https://www.city.kumamoto.jp/"),
}

REIKI_RE = re.compile(r"例規|reiki", re.I)


def get(session, url, timeout=60):
    t0 = time.time()
    try:
        r = session.get(url, headers=HEADERS, timeout=timeout)
        return r, time.time() - t0, None
    except Exception as e:  # noqa: BLE001
        return None, time.time() - t0, f"{type(e).__name__}: {e}"


def main():
    session = requests.Session()
    results = {}
    for code, (name, home) in CITIES.items():
        host = urlparse(home).netloc
        entry = {"name": name, "home": home}
        robots_url = urljoin(home, "/robots.txt")
        r, dt, err = get(session, robots_url, timeout=30)
        entry["robots"] = (
            {"status": r.status_code, "secs": round(dt, 1),
             "disallow_reikiish": [ln for ln in (r.text or "").splitlines()
                                    if "reiki" in ln.lower() or "例規" in ln][:5]}
            if r is not None else {"error": err}
        )
        r, dt, err = get(session, home)
        if r is None:
            entry["home_error"] = err
            results[code] = entry
            print(code, name, "HOME FAIL", err, flush=True)
            continue
        entry["home_status"] = r.status_code
        entry["home_secs"] = round(dt, 1)
        soup = BeautifulSoup(r.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = a["href"]
            if REIKI_RE.match(text) or REIKI_RE.search(href) or "例規" in text:
                links.append({"text": text[:60], "href": urljoin(home, href)})
        entry["reiki_links"] = links[:10]
        results[code] = entry
        print(code, name, r.status_code, f"{dt:.1f}s", "reiki links:", len(links),
              links[0]["href"] if links else "-", flush=True)
        time.sleep(2)
    (OUT / "probe_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote probe_results.json")


if __name__ == "__main__":
    main()
