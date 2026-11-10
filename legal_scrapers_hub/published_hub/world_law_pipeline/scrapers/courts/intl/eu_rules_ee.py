"""Estonian procedure codes from Riigi Teataja (official gazette, riigiteataja.ee): consolidated texts via the documented public API (oigusakt_otsing for ids, public-api/api/v1/akt/<id>/blob-html for text):
TsMS, KrMS, HKMS (version in force on retrieval date). -> data/ee/ee_rules.jsonl"""
import sys, hashlib, urllib.request, urllib.parse, json
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW
from bs4 import BeautifulSoup
ACTS = [("ee-tsms", "Tsiviilkohtumenetluse seadustik (TsMS)", "Tsiviilkohtumenetluse seadustik"), ("ee-krms", "Kriminaalmenetluse seadustik (KrMS)", "Kriminaalmenetluse seadustik"), ("ee-hkms", "Halduskohtumenetluse seadustik (HKMS)", "Halduskohtumenetluse seadustik")]
H = {"User-Agent": UA}
def find_id(title):
    out = []; p = 1
    while True:
        d = json.load(urllib.request.urlopen(urllib.request.Request("https://www.riigiteataja.ee/api/oigusakt_otsing/1/otsi?leht=%d&limiit=100&pealkiri=%s" % (p, urllib.parse.quote(title)), headers=H), timeout=40))
        out += d.get("aktid", [])
        if p * 100 >= d["metaandmed"]["kokku"]: break
        p += 1; time.sleep(2)
    today = time.strftime("%Y-%m-%d")
    cur = [a for a in out if a["pealkiri"] == title and a["liik"] == "seadus" and (a["kehtivus"].get("algus") or "9") <= today and (a["kehtivus"].get("lopp") or "9999") >= today and a["kehtivus"].get("algus")]
    return str(sorted(cur, key=lambda a: a["kehtivus"]["algus"])[-1]["globaalID"])
def tx(e): return re.sub(r"\s+", " ", e.get_text(" ")).strip()
def main():
    rows = []
    for sid, name, title in ACTS:
        idp = f"{RAW}/intl_ee_{sid}.id"
        if os.path.exists(idp): gid = open(idp).read().strip()
        else: gid = find_id(title); open(idp, "w").write(gid); time.sleep(2)
        p = f"{RAW}/intl_ee_{sid}_{gid}.html"
        if not os.path.exists(p): time.sleep(2.0); open(p, "wb").write(urllib.request.urlopen(urllib.request.Request(f"https://www.riigiteataja.ee/public-api/api/v1/akt/{gid}/blob-html", headers=H), timeout=120).read())
        raw = open(p, "rb").read(); sha = hashlib.sha256(raw).hexdigest(); s = BeautifulSoup(raw.decode("utf8", "replace"), "lxml")
        m = re.search(r"Sõnastuse jõustumise kp:</span><span>([\d.]+)", raw.decode("utf8", "replace")); eff = None
        if m: d, mo, y = m.group(1).split("."); eff = f"{y}-{mo}-{d}"
        cur = None; n = 0; head = None; seen = {}
        def flush():
            nonlocal cur, n
            if cur and len(cur["t"].strip()) > 8:
                num = cur["n"]; seen[num] = seen.get(num, 0) + 1
                rows.append(dict(rule_id=f"{sid}:{num}" + (f"~{seen[num]}" if seen[num] > 1 else ""), rule_set_id=sid, court_id=None, jurisdiction="EE", rule_set=name, rule_number=num, title=" — ".join(x for x in (cur["h"], cur["ti"]) if x) or None,
                                 text=re.sub(r"\s+", " ", cur["t"]).strip(), effective_date=eff, pdf_path=None, pdf_sha256=None, source_sha256=sha, source_url=f"https://www.riigiteataja.ee/akt/{gid}", site_policy="robots_allowed:public_api", retrieved_at=NOW(),
                                 license="Estonian official legislation (Autoriõiguse seadus § 5: legal acts not protected); Riigi Teataja open data", language="et")); n += 1
            cur = None
        for d in s.find_all("div", class_="act-part"):
            dt = d.get("data-type") or ""
            if dt == "paragrahv":
                flush(); st = d.find_all("strong"); num = tx(st[0]).rstrip(".") if st else tx(d); cur = dict(n=num, ti=tx(st[1]) if len(st) > 1 else None, t="", h=head)
            elif dt in ("peatykk", "osa", "jagu", "jaotis"):
                if dt == "peatykk": head = tx(d)
                flush()
            elif cur is not None and dt in ("loige", "punkt", "alampunkt", "tekst", "lisa", "alapunkt"): cur["t"] += " " + tx(d)
        flush(); print(sid, gid, eff, n, flush=True)
    os.makedirs(f"{ROOT}/data/ee", exist_ok=True); wjl(f"{ROOT}/data/ee/ee_rules.jsonl", rows); print("EE rules", len(rows))
if __name__ == "__main__": main()
