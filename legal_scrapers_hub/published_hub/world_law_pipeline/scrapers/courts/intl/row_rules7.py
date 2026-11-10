"""Depth-pass-5 rules: ID (UU 20/2025 Kitab Undang-Undang Hukum Acara Pidana, JDIH BPK official copy; main text only, the elucidation is excluded).
usage: row_rules7.py CC.. -> data/<cc>/<cc>_rules.jsonl + crosswalk"""
import sys
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_rules6 import *
def idn():
    p = f"{RAW}/id/kuhap2025.txt"; raw = open(p, errors="ignore").read(); sh = sha(f"{RAW}/id/kuhap2025.pdf")
    t = raw[:raw.find("PENJELASAN")] if "PENJELASAN" in raw else raw
    t = t[t.find("Pasal 2\n") - 50:]
    t = "\n".join(l for l in t.split("\n") if not re.search(r"SK No \d+|^\s*(PRESIDEN|REPUBLIK INDONESIA|PEPUELIK INDONESIA|FRESIDEN|REPUEUK INDONESIA)\s*$|^\s*_?\s*-?\s*\d{1,3}\s*-?\s*_?\s*$|^\s*SALINAN\s*$", l))
    lst = seq_split(t, re.compile(r"(?m)^[ \t]{6,}Pasal (\d{1,3})[ \t]*$"), lambda m: m.group(1))
    url = "https://peraturan.bpk.go.id/Download/400351/UU%20Nomor%2020%20Tahun%202025.pdf"; name = "Undang-Undang Nomor 20 Tahun 2025 tentang Kitab Undang-Undang Hukum Acara Pidana (KUHAP)"
    rows = [row("id-kuhap-2025", "ID", name, f"Pasal {k}", b, url, sh, "allowed_by_robots (peraturan.bpk.go.id robots.txt disallows only /Admin/, /Identity/, /Account/, /Manage/; the Details page sits behind a Cloudflare challenge and was NOT fetched, only the public Download PDF link); pdftotext of an OCR'd official copy (SALINAN), OCR errors possible; Pasal 1 (definitions) heading lost in OCR so it is missing", "Indonesian legislation (UU 28/2014 art. 43 excludes laws and official texts from copyright)", "id", "2026-01-02") for k, b in lst]
    print("id-kuhap-2025", len(rows)); return rows, xwalk("ID", "id-kuhap-2025", name, ["id-mahkamah-agung", "id-pengadilan-tinggi", "id-pengadilan-negeri"], url, "national criminal procedure code applying to this court (in force 2 January 2026, replacing UU 8/1981)")
B.update(ID=idn)
if __name__ == "__main__":
    for cc in sys.argv[1:]:
        rows, xw = B[cc.upper()](); rows = dedupe(rows); d = f"{ROOT}/data/{cc.lower()}"; os.makedirs(d, exist_ok=True)
        wjl(f"{d}/{cc.lower()}_rules.jsonl", rows); wjl(f"{d}/{cc.lower()}_rules_crosswalk.jsonl", xw); print(cc, "rules", len(rows), flush=True)
