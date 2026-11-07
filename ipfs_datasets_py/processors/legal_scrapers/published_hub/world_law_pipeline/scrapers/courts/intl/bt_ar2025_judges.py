"""Bhutan judges (public names/titles only) + individual Dzongkhag/Dungkhag court bodies from the official
Judiciary of Bhutan Annual Report 2025 (judiciary.gov.bt, pp. 12-16: Supreme Court & High Court justices, Dzongkhag Drangpons,
Dungkhag Drangpons / Drangpon Rabjams). Photo-caption layout, so names were transcribed by hand from pdftotext output;
each name is kept only if it appears in the downloaded PDF text. Judges seconded to non-court posts (BNLI, ADR centre,
Gyalpoi Zimpon office) and registrars/staff are excluded. Usage: bt_ar2025_judges.py [--dry]"""
import json, re, sys, time, hashlib, subprocess, tempfile, unicodedata, datetime, os
import requests
UA = "WorldCourtsResearchBot/1.0 (+https://huggingface.co/datasets/endomorphosis/world_courts; polite research crawl)"
D = "/workspace/world_courts/data/bt"
SRC = "https://www.judiciary.gov.bt/archives/1770270040-.pdf"; IDX = "https://www.judiciary.gov.bt/archive-content/annual_report"
POLICY = "robots_txt_names_only_specific_bots(Googlebot/Slurp/bingbot allow; no generic rule)|judiciary.gov.bt: Judiciary of Bhutan official website (no open licence stated)"
SC, HC = "bt-supreme-court", "bt-high-court-of-bhutan"
J = [  # (name, title, ptype, court_key)
 ("Norbu Tshering", "Chief Justice of Bhutan", "chief", SC), ("Pema Wangchuk", "Justice of the Supreme Court", "judge", SC),
 ("Sangay Khandu", "Justice of the Supreme Court", "judge", SC), ("Kinley Dorji", "Justice of the Supreme Court", "judge", SC),
 ("Jangchuk Norbu", "Justice (Dr.) of the Supreme Court", "judge", SC),
 ("Duba Dukpa", "Chief Justice of the High Court", "chief", HC), ("Kinley Namgay", "Justice of the High Court", "judge", HC),
 ("Lobzang Rinzin Yargay", "Justice of the High Court", "judge", HC), ("Pasang Wangmo", "Justice of the High Court", "judge", HC),
 ("Bir Bahadur", "Justice of the High Court", "judge", HC),
 ("Wangchuk Drukpa", "Chief Drangpon, Commercial Bench I", "chief", "Thimphu"), ("Tharchean", "Drangpon, Commercial Bench II", "judge", "Thimphu"),
 ("Rinchen Penjor", "Drangpon", "judge", "Haa"), ("Chador Phuntsho", "Chief Drangpon, Bench I", "chief", "Paro"),
 ("Sonam Gyeltshen", "Drangpon", "judge", "Bumthang"), ("Ugyen Jamtsho", "Chief Drangpon, Bench I", "chief", "Wangdue Phodrang"),
 ("Tashi Dorji", "Drangpon", "judge", "Gasa"), ("Norbu", "Drangpon", "judge", "Trashigang"), ("Gembo Tashi", "Drangpon", "judge", "Sarpang"),
 ("Pelden Wangmo", "Drangpon, Family & Child Bench", "judge", "Thimphu"), ("Tashi Yangzom", "Drangpon", "judge", "Tsirang"),
 ("Karma Dorji", "Drangpon", "judge", "Punakha"), ("Lhindup Zangpo", "Drangpon", "judge", "Trongsa"), ("Pema Choden", "Drangpon", "judge", "Chukha"),
 ("Kinley Tenzin", "Drangpon", "judge", "Pema Gatshel"), ("Pema Dechen", "Drangpon, Bench II", "judge", "Paro"),
 ("Kesang Choden", "Drangpon, Criminal Bench", "judge", "Thimphu"), ("Dechen Wangmo", "Drangpon, Civil Bench", "judge", "Thimphu"),
 ("Thongjay", "Drangpon", "judge", "Dagana"), ("Singye Wangdi", "Drangpon", "judge", "Samtse"), ("Jigme Lodey", "Drangpon", "judge", "Mongar"),
 ("Gyelpo", "Drangpon", "judge", "D:Gelephu"), ("Sangay Chedup", "Drangpon", "judge", "Samdrup Jongkhar"), ("Tenzin Dorji", "Drangpon", "judge", "Lhuentse"),
 ("Richa Gurung", "Drangpon, Bench II", "judge", "Wangdue Phodrang"), ("Tshoejab M. Denlen", "Drangpon (Additional Judge), Commercial Bench II", "judge", "Thimphu"),
 ("Sonam Tshering", "Drangpon", "judge", "Trashi Yangtse"), ("Phuntsho Wangchuk", "Drangpon", "judge", "Zhemgang"),
 ("Damcho Lhundup", "Dungkhag Drangpon", "judge", "D:Samdrupcholing"), ("Tobgay", "Dungkhag Drangpon", "judge", "D:Lingzhi"),
 ("Ugyen Nima", "Dungkhag Drangpon", "judge", "D:Tashicholing"), ("Bholanath Dahal", "Dungkhag Drangpon", "judge", "D:Dorokha"),
 ("Purushotam Ghimerey", "Dungkhag Drangpon", "judge", "D:Lhamoizingkha"), ("Dungay Tshering", "Dungkhag Drangpon", "judge", "D:Wamrong"),
 ("Tshering Pelden", "Drangpon Rabjam, Public Notary Office", "judge", "Thimphu"), ("Pema Yechang", "Dungkhag Drangpon, Bench I", "judge", "D:Phuentsholing"),
 ("Dawa Gyeltshen", "Dungkhag Drangpon", "judge", "D:Gelephu"), ("Jigme Gyaltshen", "Dungkhag Drangpon, Bench II", "judge", "D:Phuentsholing"),
 ("Tshering Yangdon", "Drangpon Rabjam, Enforcement Unit", "judge", "Thimphu"),
 ("Tshering Yangzom", "Acting Dungkhag Drangpon", "judge", "D:Nganglam"), ("Tshering Dorji", "Acting Dungkhag Drangpon", "judge", "D:Jomotsangkha"),
 ("Tshering Dago Wangmo", "Acting Dungkhag Drangpon", "judge", "D:Panbang"), ("Tashi Dorji", "Acting Dungkhag Drangpon", "judge", "D:Phuentsholing"),
]
def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")
def court_of(k):
    if k in (SC, HC): return k, None
    if k.startswith("D:"): n = k[2:]; return f"bt-dungkhag-court-{slug(n)}", (f"{n} Dungkhag Court", "trial_limited", "bt-dungkhag-courts", n)
    return f"bt-dzongkhag-court-{slug(k)}", (f"{k} Dzongkhag Court", "trial_general", "bt-dzongkhag-courts", k)
def main():
    dry = "--dry" in sys.argv
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    r = requests.get(SRC, headers={"User-Agent": UA}, timeout=300); r.raise_for_status(); time.sleep(2)
    sha = hashlib.sha256(r.content).hexdigest()
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(r.content); f.flush(); txt = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout
    flat = re.sub(r"\s+", " ", txt)
    courts, judges = {}, []
    for name, title, pt, k in J:
        if name not in flat: print("not in source, skipped:", name); continue
        cid, c = court_of(k)
        if c and cid not in courts:
            courts[cid] = {"court_id": cid, "record_type": "court_body", "name": c[0], "name_local": None, "level": c[1], "court_system": "national",
                "country_code": "BT", "subdivision": "BT", "jurisdiction": c[3], "parent_court_id": c[2],
                "address": {"street": None, "city": None, "postcode": None, "region": c[3], "country": "BT"}, "geo": {"lat": None, "lon": None},
                "phone": None, "website": "https://www.judiciary.gov.bt/", "wikidata": None, "place_ids": [], "source_url": SRC, "source_kind": "official",
                "site_policy": POLICY, "retrieved_at": now, "license": "Judiciary of Bhutan official publication (facts)",
                "sources": [{"source_url": SRC, "site_policy": POLICY, "source_kind": "official"}],
                "record_note": "court named in Judiciary of Bhutan Annual Report 2025 judge listing; address not stated", "added_by": "bt_ar2025_judges.py", "needs_review": True}
        judges.append({"judge_id": f"{cid}-{slug(name)}", "court_id": cid, "name": name, "title": title, "position_type": pt, "term_start": None,
            "term_end": None, "status": "sitting", "jurisdiction": "BT", "roster_url": IDX, "source_url": SRC, "source_kind": "official", "site_policy": POLICY,
            "retrieved_at": now, "needs_review": True, "extraction": "Annual Report 2025 pp.12-16 photo captions (hand-transcribed from PDF text)",
            "license": "Judiciary of Bhutan official publication (facts)", "source_sha256": sha, "language": "en"})
    def write(path, rows, key):
        have = set()
        if os.path.exists(path):
            for l in open(path):
                if l.strip(): have.add(json.loads(l)[key])
        new = []
        for x in rows:
            if x[key] not in have: have.add(x[key]); new.append(x)
        if not dry and new:
            with open(path, "a") as f:
                for x in new: f.write(json.dumps(x, ensure_ascii=False) + "\n")
        return len(new)
    print("courts new", write(f"{D}/bt_courthouses.jsonl", list(courts.values()), "court_id"), "judges new", write(f"{D}/bt_judges.jsonl", judges, "judge_id"), "of", len(judges))
main()
