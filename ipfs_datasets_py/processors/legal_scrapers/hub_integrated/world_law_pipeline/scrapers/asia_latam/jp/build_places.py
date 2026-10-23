"""Map uub.jp reiki seed list -> JIS dantai code (Wikidata P429) -> place_id (candidate CSV)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv, json, re, collections
PREFS = "北海道 青森県 岩手県 宮城県 秋田県 山形県 福島県 茨城県 栃木県 群馬県 埼玉県 千葉県 東京都 神奈川県 新潟県 富山県 石川県 福井県 山梨県 長野県 岐阜県 静岡県 愛知県 三重県 滋賀県 京都府 大阪府 兵庫県 奈良県 和歌山県 鳥取県 島根県 岡山県 広島県 山口県 徳島県 香川県 愛媛県 高知県 福岡県 佐賀県 長崎県 熊本県 大分県 宮崎県 鹿児島県 沖縄県".split()
PREF_CODE = {p: f"{i+1:02d}" for i, p in enumerate(PREFS)}
def norm(s): return s.replace("ヶ", "ケ").replace("ヵ", "カ").replace("ケ", "ケ").replace(" ", "").replace("　", "").replace("檮", "梼")
cand = {}
for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))):
    if r["country_code"] == "JP":
        cand[r["qid"]] = r
wd = collections.defaultdict(list)
for r in csv.DictReader(open("wd_p429.csv")):
    q = r["item"].rsplit("/", 1)[1]; code = r["code"].strip()
    if not re.match(r"^\d{5,6}$", code) or not r["label"]: continue
    code = code.zfill(6)
    wd[(code[:2], norm(r["label"]))].append((q, code, bool(r["end"])))
seeds = json.load(open("seeds_raw.json"))
out = []; stats = collections.Counter()
for i, s in enumerate(seeds):
    pc = PREF_CODE[s["pref"]]
    rec = dict(seed_id=f"jp{i:04d}", pref=s["pref"], pref_code=pc, name=s["name"], url=s["urls"][0],
               is_pref=s["is_pref"], jis_code=None, qid=None, place_id=None, admin_level=None, match="unmatched")
    if s["is_pref"]:
        rec.update(place_id=f"iso:JP-{pc}", admin_level="adm1", jis_code=f"{pc}0000", match="iso_pref")
        c = [x for x in wd.get((pc, norm(s["name"])), [])]
        if c: rec["qid"] = c[0][0]; rec["jis_code"] = c[0][1]
    else:
        c = wd.get((pc, norm(s["name"])), [])
        c = sorted(set(c), key=lambda x: (x[0] not in cand, x[2]))
        if c:
            q, code, ended = c[0]
            rec.update(qid=q, jis_code=code)
            if q in cand:
                rec.update(place_id=cand[q]["place_id"], admin_level=cand[q]["admin_level"] or "municipality", match="wikidata_p429")
            else:
                rec["match"] = "jis_found_not_in_candidate"
    stats[rec["match"]] += 1
    out.append(rec)
json.dump(out, open("seeds_places.json", "w"), ensure_ascii=False, indent=0)
print(stats)
for r in out:
    if r["match"] not in ("wikidata_p429", "iso_pref"): print(r["seed_id"], r["pref"], r["name"], r["match"], r["qid"])
