"""Japan: official courts.go.jp 'location/phone list' pages (/<court>/about/syozai/index.html) -> data/row/jp_official.jsonl (one row per physical location with the courts it hosts)."""
import sys, json, urllib.parse
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import cached, polite_get
from bs4 import BeautifulSoup
BASE = "https://www.courts.go.jp"
CIRCUIT = {"札幌": "sapporo", "仙台": "sendai", "東京": "tokyo", "名古屋": "nagoya", "大阪": "osaka", "広島": "hiroshima", "高松": "takamatsu", "福岡": "fukuoka"}
def slugs():
    b, u, pol = cached(f"{BASE}/courthouse/map/index.html", "intl_jp_map.html", delay=2)
    s = BeautifulSoup(b, "html.parser"); m = s.find("main") or s; cur = None; out = {}
    for e in m.find_all(True):
        if e.name in ("h2", "h3", "h4", "h5"):
            t = e.get_text(strip=True); mm = re.match(r"(.+?)高等裁判所管内$", t)
            if mm and mm.group(1) in CIRCUIT: cur = CIRCUIT[mm.group(1)]
        if e.name == "a" and cur and e.get("href", "").startswith("./../../") and e["href"].endswith("/index.html"):
            sl = e["href"].split("/")[3]
            if sl not in out: out[sl] = cur
    return out
def parse(b, slug, circuit, url, pol):
    s = BeautifulSoup(b, "html.parser"); rows = []
    for tr in s.find_all("tr"):
        tds = tr.find_all(["td", "th"])
        if len(tds) < 3: continue
        name = [x.strip() for x in tds[0].get_text("\n", strip=True).split("\n") if x.strip()]
        if not name or not re.search(r"裁判所|支部|庁舎", " ".join(name)): continue
        pcs = re.findall(r"\d{3}-\d{4}", tds[1].get_text(" ", strip=True)); addr = tds[2].get_text(" ", strip=True)
        if not pcs or not re.search(r"[都道府県]", addr): continue
        tel = re.findall(r"0\d{1,4}-\d{1,4}-\d{3,4}", " ".join(x.get_text(" ", strip=True) for x in tds[3:]))
        am = re.match(r"(.+?)(?:[（(]|$)", addr); street = am.group(1).strip() if am else addr
        rows.append(dict(names=name, postcode=pcs[0], address=street, address_raw=addr[:300], phone=tel[0] if tel else None, slug=slug, circuit=circuit, source_url=url, site_policy=pol))
    return rows
def main():
    sl = slugs(); print("slugs", len(sl), flush=True); allr = []
    for slug, circ in sl.items():
        url = f"{BASE}/{slug}/about/syozai/index.html"; b, u, pol = cached(url, f"intl_jp_{slug}_syozai.html", delay=2.0)
        if not b: print("skip", slug); continue
        r = parse(b, slug, circ, url, pol); allr += r; print(slug, circ, len(r), flush=True)
    b, u, pol = cached(f"{BASE}/saikosai/about/syozai/saikosai/index.html", "intl_jp_saikosai.html", delay=2.0)
    wjl(f"{ROOT}/data/row/jp_official.jsonl", allr); print("JP official locations", len(allr))
if __name__ == "__main__": main()
