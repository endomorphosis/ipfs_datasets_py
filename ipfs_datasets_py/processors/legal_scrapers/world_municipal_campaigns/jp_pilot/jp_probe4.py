"""Japan pilot — probe 4: Reiki-Base/d1-law sweep over core cities (中核市).

Same two paths as probe2/3, plus redirect capture. Results appended to
probe4_results.jsonl (restart-safe).
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 world-municipal-law-pilot/0.1"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.5"}
PATHS = ["/d1w_reiki/reiki.html", "/reiki/reiki.html"]

HOSTS = {
    "01202": ("函館市", "www.city.hakodate.hokkaido.jp"),
    "01203": ("小樽市", "www.city.otaru.lg.jp"),
    "01204": ("旭川市", "www.city.asahikawa.hokkaido.jp"),
    "01213": ("苫小牧市", "www.city.tomakomai.hokkaido.jp"),
    "07204": ("いわき市", "www.city.iwaki.lg.jp"),
    "07203": ("郡山市", "www.city.koriyama.lg.jp"),
    "10202": ("高崎市", "www.city.takasaki.gunma.jp"),
    "11201": ("川越市", "www.city.kawagoe.saitama.jp"),
    "11203": ("川口市", "www.city.kawaguchi.lg.jp"),
    "11208": ("所沢市", "www.city.tokorozawa.saitama.jp"),
    "11222": ("越谷市", "www.city.koshigaya.saitama.jp"),
    "12204": ("船橋市", "www.city.funabashi.lg.jp"),
    "12217": ("柏市", "www.city.kashiwa.lg.jp"),
    "13201": ("八王子市", "www.city.hachioji.tokyo.jp"),
    "13209": ("町田市", "www.city.machida.tokyo.jp"),
    "14201": ("横須賀市", "www.city.yokosuka.kanagawa.jp"),
    "14205": ("藤沢市", "www.city.fujisawa.kanagawa.jp"),
    "20202": ("松本市", "www.city.matsumoto.nagano.jp"),
    "23201": ("豊橋市", "www.city.toyohashi.lg.jp"),
    "23202": ("岡崎市", "www.city.okazaki.lg.jp"),
    "23203": ("一宮市", "www.city.ichinomiya.aichi.jp"),
    "23211": ("豊田市", "www.city.toyota.aichi.jp"),
    "28202": ("尼崎市", "www.city.amagasaki.hyogo.jp"),
    "28204": ("西宮市", "www.city.nishinomiya.hyogo.jp"),
    "28214": ("姫路市", "www.city.himeji.lg.jp"),
    "33202": ("倉敷市", "www.city.kurashiki.okayama.jp"),
    "34202": ("福山市", "www.city.fukuyama.hiroshima.jp"),
    "34203": ("呉市", "www.city.kure.lg.jp"),
    "40202": ("久留米市", "www.city.kurume.fukuoka.jp"),
    "40206": ("大牟田市", "www.city.omuta.lg.jp"),
}


def probe(item):
    code, (name, host) = item
    s = requests.Session()
    entry = {"code": code, "name": name, "host": host, "probes": []}
    for p in PATHS:
        url = f"https://{host}{p}"
        try:
            r0 = s.get(url, headers=HEADERS, timeout=15, allow_redirects=False)
            rec = {"path": p, "status": r0.status_code,
                   "location": r0.headers.get("Location", "")}
            if r0.status_code == 200:
                rec["reiki_base"] = ("Reiki-Base" in r0.text) or ("ぎょうせい" in r0.text)
                rec["bytes"] = len(r0.content)
            entry["probes"].append(rec)
        except Exception as e:  # noqa: BLE001
            entry["probes"].append({"path": p, "error": type(e).__name__})
        time.sleep(0.3)
    return entry


def main():
    dest = OUT / "probe4_results.jsonl"
    with dest.open("w", encoding="utf-8") as f, ThreadPoolExecutor(max_workers=6) as ex:
        for entry in ex.map(probe, HOSTS.items()):
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
            for r in entry["probes"]:
                if r.get("status") == 200 or r.get("location"):
                    print(entry["code"], entry["name"], r, flush=True)
    print("done")


if __name__ == "__main__":
    main()
