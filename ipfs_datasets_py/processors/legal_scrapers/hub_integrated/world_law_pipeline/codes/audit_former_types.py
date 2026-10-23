#!/usr/bin/env python3
"""Audit places that clean_abolished.py dropped only because a P31 class label starts with
'former|dissolved|abolished|defunct' (removal_reason 'former_class:*').

An item is judged CURRENT (status=restore) when ALL of:
  * no past-dated P576 (dissolved/abolished date)  [future or absent is fine]
  * no past-dated P1366 (replaced by)              [an undated P1366 makes it 'unsure']
  * it is on an official current list: either its current (no P582) national code from Wikidata is in
    the official list for that system, or (no code in Wikidata) its name matches exactly one entry of
    the official list of its country.
Official lists: the ones build_place_codes.load_official() uses, plus the BFS commune snapshot of today
for CH (Eurostat LAU 2024 is stale for CH mergers of 2025/2026).
Items with no P576 and no official/code evidence are 'not_current' unless listed in UNSURE (manual,
documented reasons) — those are reported but NOT restored.

Data: QLever (https://qlever.dev/api/wikidata), never query.wikidata.org. --refresh re-queries.
Output: former_type_audit.csv (consumed by build_place_additions.py: status=restore rows are added
with note 'restored: former-type false positive').
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import argparse, collections, csv, datetime, json, os, subprocess, sys, unicodedata
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_place_codes as B  # noqa: E402

CACHE = HERE / "cache"
OUT = HERE / "former_type_audit.csv"
REMOVED = Path(os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities")) / "removed_abolished.csv"
QLEVER = "https://qlever.dev/api/wikidata"
UA = "world-law-place-codes/0.1 (Benjamin Barber; low volume; bulk via QLever)"
TODAY = datetime.date.today().isoformat()
BFS_URL = "https://www.agvchapp.bfs.admin.ch/api/communes/snapshot?date={d}"
BFS_FILE = CACHE / "bfs_communes_snapshot.csv"
OFFICIAL_PROPS = {"P382": "nl_cbs_gemeente", "P7606": "cz_ruian_obec", "P939": "hu_ksh", "P964": "at_gkz",
                  "P772": "es_ine", "P635": "it_istat", "P374": "fr_insee_cog", "P439": "de_ags",
                  "P771": "ch_bfs", "P429": "jp_dantai", "P782": "eu_lau"}
WD_ONLY_PROPS = {"P1653": "pl_teryt_terc", "P442": "cn_admin_code", "P8828": "ua_katottg",
                 "P3801": "mx_inegi", "P1588": "id_bps", "P2588": "id_kemendagri"}
# Manual 'unsure' annotations (not restored; no official list available here to confirm).
UNSURE = {
    "Q16651102": "KZ district re-created 2022 (Abai region)? no official KATO list loaded",
    "Q16533250": "KZ district re-created 2022 (Abai region)? no official KATO list loaded",
    "Q16673400": "KZ district re-created 2022 (Abai region)? no official KATO list loaded",
    "Q3462044": "QC municipality (ex-parish municipality); no StatCan/MAMH list loaded",
    "Q5471972": "SK resort village; no StatCan list loaded",
    "Q12786568": "SI local community (krajevna skupnost, sub-municipal); no official list",
    "Q2008686": "SI local community (sub-municipal); no official list",
    "Q60481086": "SI local community (sub-municipal); no official list",
    "Q8082836": "SI local community (sub-municipal); no official list",
    "Q60481090": "SI local community (sub-municipal); no official list",
    "Q2455024": "RU rural settlement (also ex-Finnish municipality); no OKTMO list loaded",
    "Q2642406": "RU rural settlement (also ex-Finnish municipality); no OKTMO list loaded",
    "Q15215899": "GB civil parish; no ONS parish list loaded",
    "Q133809297": "GB civil parish (Wales community?); no ONS list loaded",
    "Q6707107": "PK town abolished 2011, possibly re-created 2023; no official list",
    "Q2138709": "VN commune; 2025 commune reform may have merged it",
    "Q7396574": "GT municipality vs department ambiguity",
    "Q4134759": "BY selsoviet; no official list, many merged 2013-2024",
    "Q124629917": "BY selsoviet; no official list, many merged 2013-2024",
    "Q116789182": "BY selsoviet; no official list, many merged 2013-2024",
    "Q6467064": "BY selsoviet; no official list, many merged 2013-2024",
}
PFX = ("PREFIX wdt: <http://www.wikidata.org/prop/direct/> PREFIX wd: <http://www.wikidata.org/entity/> "
       "PREFIX p: <http://www.wikidata.org/prop/> PREFIX pq: <http://www.wikidata.org/prop/qualifier/> "
       "PREFIX wikibase: <http://wikiba.se/ontology#> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> ")


def candidates():
    with REMOVED.open(encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["removal_reason"].startswith("former_class") and r["qid"]]


def qlever(query, fn):
    subprocess.run(["curl", "-sS", "-f", "-m", "600", "-A", UA, "-H", "Accept: text/tab-separated-values",
                    "--data-urlencode", "query=" + query, QLEVER, "-o", str(CACHE / fn)], check=True)


def refresh(rows):
    vals = " ".join("wd:" + r["qid"] for r in rows)
    props = " ".join("p:" + p for p in ["P576", "P1366", "P31", "P17", *OFFICIAL_PROPS, *WD_ONLY_PROPS])
    qlever(PFX + f"SELECT ?i ?prop ?v ?rank ?end ?start ?pit WHERE {{ VALUES ?i {{ {vals} }} VALUES ?prop {{ {props} }} "
           "?i ?prop ?st . ?st ?ps ?v . ?psp wikibase:statementProperty ?ps . ?psp wikibase:claim ?prop . "
           "?st wikibase:rank ?rank . OPTIONAL { ?st pq:P582 ?end } OPTIONAL { ?st pq:P580 ?start } "
           "OPTIONAL { ?st pq:P585 ?pit } }", "wd_former_items_claims.tsv")
    qlever(PFX + f"SELECT ?i ?en ?native ?cls ?clsl WHERE {{ VALUES ?i {{ {vals} }} OPTIONAL {{ ?i rdfs:label ?en "
           'FILTER(LANG(?en)="en") } OPTIONAL { ?i wdt:P31 ?cls . ?cls rdfs:label ?clsl FILTER(LANG(?clsl)="en") } }',
           "wd_former_items_labels.tsv")
    subprocess.run(["curl", "-sS", "-f", "-m", "120", "-A", UA, BFS_URL.format(d=datetime.date.today().strftime("%d-%m-%Y")),
                    "-o", str(BFS_FILE)], check=True)


def norm(s):
    return unicodedata.normalize("NFKC", s or "").casefold().strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    cand = candidates()
    if args.refresh:
        refresh(cand)
    claims = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in B.read_tsv(CACHE / "wd_former_items_claims.tsv"):
        r += [""] * 7
        q, prop, v, rank, end, start, pit = r[:7]
        if "Deprecated" not in rank:
            claims[q][prop].append((v, end[:10], start[:10], pit[:10]))
    label, ocls = {}, collections.defaultdict(set)
    for r in B.read_tsv(CACHE / "wd_former_items_labels.tsv"):
        r += [""] * 5
        label[r[0]] = r[1]
        if r[4]:
            ocls[r[0]].add(r[4])
    off, _meta, _lau = B.load_official()
    with BFS_FILE.open(encoding="utf-8-sig") as f:
        bfs = {r["BfsCode"]: (r["Name"], f"bfs_communes_snapshot_{TODAY}") for r in csv.DictReader(f) if r["Level"] == "3"}
    off = dict(off)
    off["ch_bfs"] = bfs  # current list beats LAU 2024 for CH
    names = collections.defaultdict(lambda: collections.defaultdict(list))
    for sysn, o in off.items():
        if sysn.startswith("_") or sysn == "eu_lau" or not isinstance(o, dict):
            continue
        for code, v in o.items():
            names[sysn[:2].upper()][norm(v[0])].append((sysn, code))
    norm_code = {s[2]: s[3] for s in B.SYSTEMS}
    out = []
    for r in cand:
        q, c = r["qid"], claims.get(r["qid"], {})
        past576 = sorted(d for d in (x[0][:10] for x in c.get("P576", [])) if d and d <= TODAY)
        rep = c.get("P1366", [])
        rep_past = sorted((x[2] or x[3]) for x in rep if (x[2] or x[3]) and (x[2] or x[3]) <= TODAY)
        rep_undated = [x[0] for x in rep if not (x[2] or x[3])]
        hits, wd_codes, missing = [], [], []
        for P, sysn in {**OFFICIAL_PROPS, **WD_ONLY_PROPS}.items():
            for v, end, _s, _p in c.get(P, []):
                if end and end <= TODAY:
                    continue
                code = norm_code[P](v) if P in norm_code else v
                if P in OFFICIAL_PROPS and sysn in off:
                    (hits if code in off[sysn] else missing).append((sysn, code))
                else:
                    wd_codes.append((sysn, code))
        if not hits and not missing:
            nm = names.get(r["country_code"], {})
            m = nm.get(norm(r["place_name"])) or nm.get(norm(label.get(q)))
            if m and len(m) == 1:
                hits = [(m[0][0], m[0][1])]
        sysn, code = hits[0] if hits else ("", "")
        if past576 or rep_past:
            st, ev = "not_current", (f"P576 {','.join(past576)}" if past576 else f"P1366 dated {','.join(rep_past)}")
        elif hits and not rep_undated:
            st, ev = "restore", "official list: " + "; ".join(f"{s}:{k}={off[s][k][0]} ({off[s][k][1]})" for s, k in hits)
        elif hits:
            st, ev = "unsure", f"official list hit but undated P1366 -> {','.join(rep_undated)}"
        elif missing:
            st, ev = "not_current", "Wikidata code not in current official list: " + "; ".join(f"{s}:{k}" for s, k in missing)
        elif q in UNSURE:
            st, ev = "unsure", UNSURE[q] + (f"; wikidata codes {wd_codes}" if wd_codes else "")
        elif wd_codes:
            st, ev = "unsure", "current Wikidata code but no official list: " + "; ".join(f"{s}:{k}" for s, k in wd_codes)
        else:
            st, ev = "not_current", "no P576, but no current code and not on an official current list" + (
                f"; undated P1366 -> {','.join(rep_undated)}" if rep_undated else "")
        out.append({"qid": q, "place_id": r["place_id"], "country_code": r["country_code"], "name": r["place_name"],
                    "admin_level": r["admin_level"], "iso_3166_2": r["iso_3166_2"], "removal_reason": r["removal_reason"],
                    "other_p31": ";".join(sorted(x for x in ocls.get(q, ()) if not x.lower().startswith(("former", "dissolved", "abolished", "defunct", "historical")))),
                    "status": st, "evidence": ev, "official_code_system": sysn if st == "restore" else "",
                    "official_code": code if st == "restore" else ""})
    out.sort(key=lambda o: (o["status"], o["country_code"], o["qid"]))
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    tmp.replace(OUT)
    print(f"wrote {OUT} rows={len(out)}", dict(collections.Counter(o["status"] for o in out)))
    print("by country/status:", dict(sorted(collections.Counter((o["country_code"] or "--", o["status"]) for o in out).items())))


if __name__ == "__main__":
    main()
