"""Japan pilot — probe 2: Reiki-Base path sweep across city domains.

Checks robots.txt once per host, then tries the Reiki-Base entry paths
(/d1w_reiki/reiki.html, /reiki/reiki.html). A hit = HTTP 200 AND the page
identifies as Gyosei Reiki-Base (title/author marker). Output JSON.
"""
import json
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

OUT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 world-municipal-law-pilot/0.1"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.5"}

# code: (name, host) — designated cities + prefectural capitals + core cities
HOSTS = {
    "02200": ("青森市", "www.city.aomori.aomori.jp"),
    "03200": ("盛岡市", "www.city.morioka.iwate.jp"),
    "04100": ("仙台市", "www.city.sendai.jp"),
    "05200": ("秋田市", "www.city.akita.akita.jp"),
    "06200": ("山形市", "www.city.yamagata-yamagata.jp"),
    "07200": ("福島市", "www.city.fukushima.fukushima.jp"),
    "08200": ("水戸市", "www.city.mito.lg.jp"),
    "09200": ("宇都宮市", "www.city.utsunomiya.tochigi.jp"),
    "10200": ("前橋市", "www.city.maebashi.gunma.jp"),
    "12100": ("千葉市", "www.city.chiba.jp"),
    "13104": ("新宿区", "www.city.shinjuku.lg.jp"),
    "14100": ("横浜市", "www.city.yokohama.lg.jp"),
    "14130": ("川崎市", "www.city.kawasaki.jp"),
    "14150": ("相模原市", "www.city.sagamihara.kanagawa.jp"),
    "15100": ("新潟市", "www.city.niigata.lg.jp"),
    "16200": ("富山市", "www.city.toyama.toyama.jp"),
    "17200": ("金沢市", "www4.city.kanazawa.lg.jp"),
    "18200": ("福井市", "www.city.fukui.lg.jp"),
    "19200": ("甲府市", "www.city.kofu.yamanashi.jp"),
    "20201": ("長野市", "www.city.nagano.nagano.jp"),
    "21100": ("岐阜市", "www.city.gifu.lg.jp"),
    "22100": ("静岡市", "www.city.shizuoka.lg.jp"),
    "22130": ("浜松市", "www.city.hamamatsu.shizuoka.jp"),
    "23100": ("名古屋市", "www.city.nagoya.jp"),
    "24200": ("津市", "www.info.city.tsu.mie.jp"),
    "25100": ("大津市", "www.city.otsu.shiga.jp"),
    "26100": ("京都市", "www.city.kyoto.lg.jp"),
    "27100": ("大阪市", "www.city.osaka.lg.jp"),
    "28100": ("神戸市", "www.city.kobe.lg.jp"),
    "28200": ("姫路市", "www.city.himeji.lg.jp"),
    "29200": ("奈良市", "www.city.nara.lg.jp"),
    "30200": ("和歌山市", "www.city.wakayama.wakayama.jp"),
    "33100": ("岡山市", "www.city.okayama.jp"),
    "34100": ("広島市", "www.city.hiroshima.lg.jp"),
    "35200": ("下関市", "www.city.shimonoseki.lg.jp"),
    "36200": ("徳島市", "www.city.tokushima.tokushima.jp"),
    "37200": ("高松市", "www.city.takamatsu.kagawa.jp"),
    "38200": ("松山市", "www.city.matsuyama.ehime.jp"),
    "39200": ("高知市", "www.city.kochi.kochi.jp"),
    "40100": ("北九州市", "www.city.kitakyushu.lg.jp"),
    "40130": ("福岡市", "www.city.fukuoka.lg.jp"),
    "41200": ("佐賀市", "www.city.saga.lg.jp"),
    "42200": ("長崎市", "www.city.nagasaki.lg.jp"),
    "43100": ("熊本市", "www.city.kumamoto.jp"),
    "44200": ("大分市", "www.city.oita.oita.jp"),
    "45200": ("宮崎市", "www.city.miyazaki.miyazaki.jp"),
    "46200": ("鹿児島市", "www.city.kagoshima.lg.jp"),
    "47200": ("那覇市", "www.city.naha.okinawa.jp"),
}

PATHS = ["/d1w_reiki/reiki.html", "/reiki/reiki.html"]


def main():
    s = requests.Session()
    results = {}
    for code, (name, host) in HOSTS.items():
        entry = {"name": name, "host": host}
        try:
            r = s.get(f"https://{host}/robots.txt", headers=HEADERS, timeout=20)
            entry["robots_status"] = r.status_code
            entry["robots_disallow"] = [
                ln.strip() for ln in (r.text or "").splitlines()
                if ln.strip().lower().startswith("disallow") and
                ("reiki" in ln.lower() or "d1w" in ln.lower())
            ]
        except Exception as e:  # noqa: BLE001
            entry["robots_error"] = type(e).__name__
        hits = []
        for p in PATHS:
            url = f"https://{host}{p}"
            try:
                r = s.get(url, headers=HEADERS, timeout=30)
                marker = ("Reiki-Base" in r.text) or ("ぎょうせい" in r.text) or ("GYOSEI" in r.text)
                if r.status_code == 200:
                    hits.append({"path": p, "status": 200, "reiki_base": marker,
                                 "bytes": len(r.content)})
            except Exception as e:  # noqa: BLE001
                hits.append({"path": p, "error": type(e).__name__})
            time.sleep(0.5)
        entry["probes"] = hits
        found = [h for h in hits if h.get("status") == 200]
        if found:
            print(code, name, "HIT", found, flush=True)
        results[code] = entry
        time.sleep(1)
    (OUT / "probe2_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    hits = {c: e for c, e in results.items()
            if any(h.get("status") == 200 for h in e["probes"])}
    print(f"\n{len(hits)} hosts with a 200 on a reiki path:")
    for c, e in hits.items():
        print(" ", c, e["name"], [(h["path"], h.get("reiki_base")) for h in e["probes"] if h.get("status") == 200])


if __name__ == "__main__":
    main()
