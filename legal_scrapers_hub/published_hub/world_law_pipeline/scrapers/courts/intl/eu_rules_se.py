"""Swedish procedural statutes from the official Riksdag open-data SFS feed (data.riksdagen.se; Regeringskansliet/Lagrummet; public domain, Upphovsrättslagen 9 §) -> data/se/se_rules.jsonl"""
import sys, hashlib, urllib.request
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW
CODES = [("se-rb", "Rättegångsbalk (1942:740)", "1942-740"), ("se-fpl", "Förvaltningsprocesslag (1971:291)", "1971-291"), ("se-domstolsarenden", "Lag (1996:242) om domstolsärenden", "1996-242"),
         ("se-arbetstvister", "Lag (1974:371) om rättegången i arbetstvister", "1974-371"), ("se-allm-fd", "Lag (1971:289) om allmänna förvaltningsdomstolar", "1971-289")]
def ws(s): return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()
def main():
    rows = []
    for sid, name, dok in CODES:
        p = f"{RAW}/intl_se_{dok}.txt"; url = f"https://data.riksdagen.se/dokument/sfs-{dok}.text"
        if not os.path.exists(p):
            time.sleep(2.0)
            try: open(p, "wb").write(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=90).read())
            except Exception as e: print("miss", sid, e); continue
        raw = open(p, "rb").read(); sha = hashlib.sha256(raw).hexdigest(); txt = raw.decode("utf-8", "replace").replace("\r", "")
        m = re.search(r"Ändrad:\s*t\.o\.m\. SFS (\S+)", txt); amended = m.group(1) if m else None
        body = txt.split("Källa: Regeringskansliet / Lagrummet", 1)[-1]
        chap = None; chap_t = None; cur = None; n = 0; seen = {}
        def flush():
            nonlocal cur, n
            if cur and len(cur["t"].strip()) > 8:
                num = (f"{cur['kap']} kap. " if cur["kap"] else "") + cur["sec"] + " §"
                seen[num] = seen.get(num, 0) + 1
                rows.append(dict(rule_id=f"{sid}:{num}" + (f"~{seen[num]}" if seen[num] > 1 else ""), rule_set_id=sid, court_id=None, jurisdiction="SE", rule_set=name, rule_number=num, title=cur["ct"], text=ws(cur["t"]),
                                 effective_date=None, pdf_path=None, pdf_sha256=None, source_sha256=sha, source_url=f"https://data.riksdagen.se/dokument/sfs-{dok}", site_policy="robots_allowed:open_data_api", retrieved_at=NOW(),
                                 license="public domain (Upphovsrättslagen 9 §: författningar); consolidated through SFS " + str(amended), language="sv")); n += 1
            cur = None
        for line in body.split("\n"):
            mc = re.match(r"^(\d+\s?[a-z]?) kap\. (.*)$", line.strip())
            if mc and not line.startswith(" "):
                flush(); chap = mc.group(1).replace(" ", ""); chap_t = ws(mc.group(2)); continue
            ms = re.match(r"^(\d+(?: [a-z])?) § (.*)$", line)
            if ms:
                flush(); cur = dict(kap=chap, ct=chap_t, sec=ms.group(1), t=ms.group(2)); continue
            if re.match(r"^(\S+ avdelningen|Övergångsbestämmelser|Bilaga)", line.strip(), re.I) and cur:
                flush(); continue
            if cur is not None: cur["t"] += " " + line
        flush(); print(sid, n, "amended thru", amended, flush=True)
    os.makedirs(f"{ROOT}/data/se", exist_ok=True); wjl(f"{ROOT}/data/se/se_rules.jsonl", rows); print("SE rules", len(rows))
if __name__ == "__main__": main()
