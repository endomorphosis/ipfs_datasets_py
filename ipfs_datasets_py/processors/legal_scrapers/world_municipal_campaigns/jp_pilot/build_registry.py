"""Japan pilot — build the jurisdiction registry from the MIC code list.

Source (official): Ministry of Internal Affairs and Communications (MIC /
総務省) 全国地方公共団体コード list, Excel sheet "R6.1.1現在の団体"
(2024-01-01), downloaded from https://www.soumu.go.jp/denshijiti/code.html
into scratch/. Codes there are 6 digits (5-digit JIS X 0402 code + check
digit); the registry serializes the canonical 5-digit form.

Empirically verifies the JIS X 0402 check-digit algorithm against every
row before trusting it in the scheme. Output: data/jurisdictions.jsonl.
"""
import json
import sys
from pathlib import Path

import openpyxl

OUT = Path(__file__).resolve().parent.parent
XLSX = OUT / "scratch" / "mic_000925835.xlsx"


def check_digit_ok(code6: str) -> bool:
    """JIS X 0402 check digit: weights 6,5,4,3,2 over the 5 digits;
    check = 11 - (sum mod 11), with 10/11 mapping to 0."""
    if len(code6) != 6 or not code6.isdigit():
        return False
    s = sum(int(d) * w for d, w in zip(code6[:5], (6, 5, 4, 3, 2)))
    c = 11 - (s % 11)
    if c == 10:
        c = 0
    elif c == 11:
        c = 1
    return c == int(code6[5])


def main():
    wb = openpyxl.load_workbook(XLSX, read_only=True)
    ws = wb["R6.1.1現在の団体"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    out = []
    bad_check = []
    kinds = {}
    for r in rows:
        code6, pref, name, pref_kana, name_kana = (r[0], r[1], r[2], r[3], r[4])
        if not code6:
            continue
        code6 = str(code6).strip()
        code5 = code6[:5]
        if not check_digit_ok(code6):
            bad_check.append(code6)
        if name is None:
            kind = "prefecture"
            disp = pref
        elif name.endswith("区") and code5[2] != "0":
            kind = "ward"
            disp = name
        else:
            kind = "municipality"
            disp = name
        kinds[kind] = kinds.get(kind, 0) + 1
        out.append({
            "code": code5,
            "code6": code6,
            "name": disp,
            "name_kana": (name_kana or pref_kana or ""),
            "prefecture": pref,
            "prefecture_code": code5[:2],
            "kind": kind,
        })
    print("total rows:", len(out), "kinds:", kinds)
    print("check-digit failures:", len(bad_check), bad_check[:5])
    codes = [o["code"] for o in out]
    assert len(set(codes)) == len(codes), "duplicate 5-digit codes!"
    dest = OUT / "data" / "jurisdictions.jsonl"
    with dest.open("w", encoding="utf-8") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    print("wrote", dest)
    # sanity spot checks
    by_code = {o["code"]: o for o in out}
    for probe in ("01100", "13100", "14100", "27100", "40130", "47201"):
        print(probe, by_code.get(probe))


if __name__ == "__main__":
    sys.exit(main())
