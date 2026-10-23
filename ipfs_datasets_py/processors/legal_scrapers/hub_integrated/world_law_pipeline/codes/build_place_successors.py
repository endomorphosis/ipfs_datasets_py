#!/usr/bin/env python3
"""Successor table for dissolved/renumbered municipalities: codes/place_successors.csv (EE, BE).

Columns: old_place_qid, old_name, old_code, dissolved_date, successor_place_id, successor_code, source,
         country_code, successor_name, n_successors, note
  * EE: old_code = EHAK (4 digits). Sources: Maa-amet "ADS haldusreformi EHAK järgnevused" (2017 reform,
    KOV sheet incl. split municipalities -> one row per successor, n_successors > 1), EHAK 2026v1 (current list,
    Statistics Estonia via teabekeskus.tehik.ee; same municipalities as 2025v5, which merged Jõhvi + Toila -> Jõhvi vald 0250), Wikidata P1140/P576/P1366.
  * BE: old_code = NIS/INS (REFNIS, 5 digits). Sources: Statbel TU_COM_REFNIS-20250101 (validity dates),
    Statbel "Geografische indeling" merger table (02/12/2024 + 01/01/2025) and the 2019 Hainaut renumbering
    table, Wikidata P1567/P576/P1366 (2019 mergers and 1977-1987 changes; checked against REFNIS dates).
    Scope: codes that ended on/after 1977-01-01 (the 1977 fusion's 1,800+ deelgemeenten are out of scope).
  * successor_place_id: place_id in the candidate list, else wd:<QID> of the current item (added to
    place_additions.csv by build_place_additions.py via current_missing()). Chains are followed to a code that
    is current in the official list.
  * PL / GR (MANUAL_SUCCESSORS, reviewed 2026-10-17): PL old_code/successor_code = TERC (gmina Ostrowice 2019 split,
    rural gmina Zielona Góra 2015 merger into the city); GR old_code/successor_code = Diavgeia organisation uid
    (gr_diavgeia_org) for the Law 4600/2019 splits of Corfu, Kefalonia, Lesvos and Samos (new municipalities from
    2019-09-01). Successors must be candidate places (checked; rows with a missing successor are dropped as problems).
Wikidata only via QLever (https://qlever.dev/api/wikidata). `--test-unmatched` = read-only mapping test of
staging/eu/_unmatched (belb_*, eert_*).
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import argparse, collections, csv, datetime, glob, html, json, os, re, subprocess, sys, unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
OUT = HERE / "place_successors.csv"
CANDIDATE = Path(os.environ.get("GLOBAL_MUNICIPALITIES_CSV", "/workspace/global_municipalities/global_municipalities_candidate.csv"))
STAGING = Path(os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law")) / "staging"
QLEVER = "https://qlever.dev/api/wikidata"
UA = "world-law-place-codes/0.1 (Benjamin Barber; low volume; bulk via QLever)"
TODAY = datetime.date.today().isoformat()
COLS = ["old_place_qid", "old_name", "old_code", "dissolved_date", "successor_place_id", "successor_code", "source",
        "country_code", "successor_name", "n_successors", "note"]
URLS = {
    "statbel_refnis_20250101.zip": "https://statbel.fgov.be/sites/default/files/files/opendata/REFNIS%20code/TU_COM_REFNIS-20250101.zip",
    "statbel_geografie_nl.html": "https://statbel.fgov.be/nl/over-statbel/methodologie/classificaties/geografie",
    "ee_ehak_jargnevused_2017.xlsx": "https://geoportaal.maaamet.ee/docs/aadress/ADS_haldusreformi_EHAK_jargnevused_231117parandatud.xlsx",
    "tehik_ehak_2026v1.html": "https://teabekeskus.tehik.ee/et/loendid/ehak/2026v1",
}
WD = {"ee": "P1140", "be": "P1567"}
# Mergers whose official text is a decree/law rather than a Statbel table; each is checked against REFNIS dates
# (old code ends the day before the new code starts) before use.
BE_KNOWN = {
    # Flemish decree of 2018 (mergers effective 2019-01-01)
    "44001": "44084", "44029": "44084",                    # Aalter + Knesselare -> Aalter
    "44011": "44083", "44049": "44083",                    # Deinze + Nevele -> Deinze
    "44036": "44085", "44072": "44085", "44080": "44085",  # Lovendegem + Waarschoot + Zomergem -> Lievegem
    "45017": "45068", "45057": "45068",                    # Kruishoutem + Zingem -> Kruisem
    "12030": "12041", "12034": "12041",                    # Puurs + Sint-Amands -> Puurs-Sint-Amands
    "72040": "72042", "71047": "72042",                    # Meeuwen-Gruitrode + Opglabbeek -> Oudsbergen
    "72025": "72043", "72029": "72043",                    # Neerpelt + Overpelt -> Pelt
    # Law of 1982: Antwerp merger effective 1983-01-01 (now districts of Antwerpen)
    "11003": "11002", "11006": "11002", "11012": "11002", "11014": "11002", "11019": "11002", "11028": "11002",
    "11051": "11002",
}
BE_MUNI_CLS = "Q493522"
PFX = ("PREFIX wdt: <http://www.wikidata.org/prop/direct/> PREFIX wd: <http://www.wikidata.org/entity/> "
       "PREFIX p: <http://www.wikidata.org/prop/> PREFIX ps: <http://www.wikidata.org/prop/statement/> "
       "PREFIX pq: <http://www.wikidata.org/prop/qualifier/> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> ")


def refresh():
    for fn, url in URLS.items():
        subprocess.run(["curl", "-sSL", "-f", "-m", "180", "-A", "Mozilla/5.0 (world-law-place-codes)", "-o", str(CACHE / fn), url], check=True)
    subprocess.run(["unzip", "-o", "-q", str(CACHE / "statbel_refnis_20250101.zip"), "-d", str(CACHE / "statbel_refnis_20250101")], check=True)
    for cc, prop in WD.items():
        lang = "et" if cc == "ee" else "nl"
        q = (PFX + f"SELECT ?i ?code ?cend ?label ?dissolved ?succ ?sstart ?spit ?cls WHERE {{ ?i p:{prop} ?cs . ?cs ps:{prop} ?code . "
             f"OPTIONAL {{ ?cs pq:P582 ?cend }} OPTIONAL {{ ?i rdfs:label ?label FILTER(LANG(?label)=\"{lang}\") }} "
             "OPTIONAL { ?i wdt:P576 ?dissolved } OPTIONAL { ?i p:P1366 ?ss . ?ss ps:P1366 ?succ . OPTIONAL { ?ss pq:P580 ?sstart } "
             "OPTIONAL { ?ss pq:P585 ?spit } } OPTIONAL { ?i wdt:P31 ?cls } }")
        subprocess.run(["curl", "-sS", "-f", "-m", "600", "-A", UA, "-H", "Accept: text/tab-separated-values",
                        "--data-urlencode", "query=" + q, QLEVER, "-o", str(CACHE / f"wd_{cc}_{prop}_history.tsv")], check=True)


def uq(s):
    s = (s or "").strip()
    if s.startswith("<http://www.wikidata.org/entity/"):
        return s.rsplit("/", 1)[-1].rstrip(">")
    m = re.match(r'^"(.*)"(?:@[\w-]+|\^\^<[^>]+>)?$', s)
    return m.group(1) if m else s


def norm(s):
    s = unicodedata.normalize("NFKC", s or "").casefold().strip()
    return re.sub(r"\s+", " ", s.replace("’", "'"))


def wd_items(cc):
    items = collections.defaultdict(lambda: {"codes": {}, "label": "", "dissolved": "", "succ": {}, "cls": set()})
    with (CACHE / f"wd_{cc}_{WD[cc]}_history.tsv").open(encoding="utf-8") as f:
        next(f)
        for line in f:
            r = [uq(x) for x in line.rstrip("\n").split("\t")] + [""] * 9
            q, code, cend, label, diss, succ, sstart, spit, cls = r[:9]
            it = items[q]
            if code:
                prev = it["codes"].get(code)
                it["codes"][code] = cend[:10] if (prev is None or prev) else prev
            it["label"] = it["label"] or label
            it["dissolved"] = max(it["dissolved"], diss[:10])
            if succ:
                it["succ"][succ] = (sstart or spit)[:10]
            if cls:
                it["cls"].add(cls)
    return items


def candidates():
    by_qid, rows = {}, []
    with CANDIDATE.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["country_code"] in ("BE", "EE"):
                rows.append(r)
                if r["qid"]:
                    by_qid[r["qid"]] = r
    return by_qid, rows


# --------------------------------------------------------------------------- official lists
def be_refnis():
    out = {}
    fn = CACHE / "statbel_refnis_20250101" / "TU_COM_REFNIS-20250101.txt"
    with fn.open(encoding="latin-1") as f:
        for r in csv.DictReader(f, delimiter="|"):
            if r["LVL_REFNIS"] != "4":
                continue
            d0 = datetime.datetime.strptime(r["DT_VLDT_START"], "%d/%m/%Y").date().isoformat()
            d1 = datetime.datetime.strptime(r["DT_VLDT_END"], "%d/%m/%Y").date().isoformat()
            out.setdefault(r["CD_REFNIS"], []).append({"code": r["CD_REFNIS"], "arr": r["CD_SUP_REFNIS"], "nl": r["TX_REFNIS_NL"],
                                                       "fr": r["TX_REFNIS_FR"], "de": r["TX_REFNIS_DE"], "start": d0, "end": d1})
    return out


def be_statbel_tables():
    s = (CACHE / "statbel_geografie_nl.html").read_text(encoding="utf-8")
    tabs = re.findall(r"<table.*?</table>", s, re.S)
    mergers, renum = [], {}
    for t in tabs:
        for tr in re.findall(r"<tr.*?</tr>", t, re.S):
            cells = [html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c))).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
            if len(cells) == 2 and "(" in cells[0] and "(" in cells[1]:
                olds = re.findall(r"([^+()]+?)\s*\((\d{5})\)", cells[0])
                new = re.findall(r"([^+()]+?)\s*\((\d{5})\)", cells[1])
                if olds and new:
                    mergers.append(([(n.strip(), c) for n, c in olds], (new[0][0].strip(), new[0][1])))
            elif len(cells) == 3 and re.fullmatch(r"\d{5}", cells[1]) and re.fullmatch(r"\d{5}", cells[2]):
                renum[cells[1]] = (cells[0], cells[2])
    return mergers, renum


def ee_current():
    rows = json.loads((CACHE / "ehak_2026v1.json").read_text()) if (CACHE / "ehak_2026v1.json").exists() else None
    if rows is None:
        s = (CACHE / "tehik_ehak_2026v1.html").read_text(encoding="utf-8")
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", s, re.S):
            tds = [re.sub(r"<[^>]+>|<!--.*?-->", "", t).strip() for t in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if len(tds) >= 3:
                rows.append(tds[:3])
        (CACHE / "ehak_2026v1.json").write_text(json.dumps(rows, ensure_ascii=False))
    counties = {c for c, n, p in rows if p in ("—", "-", "") and n.endswith("maakond")}
    return {c: n for c, n, p in rows if p in counties}


def ee_2017():
    p = CACHE / "ee_ehak_kov_2017.json"
    if not p.exists():
        import openpyxl
        ws = openpyxl.load_workbook(CACHE / "ee_ehak_jargnevused_2017.xlsx", read_only=True)["KOV_muudatused"]
        rows = []
        for i, r in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                continue
            if not r[0]:
                break
            rows.append(list(r[:11]))
        p.write_text(json.dumps(rows, ensure_ascii=False))
    return json.loads(p.read_text())


# --------------------------------------------------------------------------- build
def current_maps():
    """{cc: {code: {"qid", "name", "place_id", "in_candidate"}}} for the official current municipalities."""
    by_qid, cand_rows = candidates()
    res = {}
    # BE
    ref = be_refnis()
    wd = wd_items("be")
    code2q = collections.defaultdict(list)
    for q, it in wd.items():
        for code, end in it["codes"].items():
            if re.fullmatch(r"\d{5}", code) and not end and not (it["dissolved"] and it["dissolved"] <= TODAY):
                code2q[code].append(q)
    be = {}
    for code, vs in ref.items():
        v = [x for x in vs if x["end"] >= TODAY]
        if not v:
            continue
        v = v[0]
        qs = code2q.get(code, [])
        qs = sorted(qs, key=lambda q: (q not in by_qid, BE_MUNI_CLS not in wd[q]["cls"], int(q[1:])))
        q = qs[0] if qs else ""
        be[code] = {"qid": q, "name": v["nl"] if v["nl"] == v["fr"] or v["arr"][:1] in "1347" else v["fr"],
                    "names": {v["nl"], v["fr"], v["de"]}, "place_id": by_qid[q]["place_id"] if q in by_qid else (f"wd:{q}" if q else ""),
                    "in_candidate": q in by_qid, "arr": v["arr"]}
    res["BE"] = be
    # EE
    cur = ee_current()
    wd = wd_items("ee")
    code2q = collections.defaultdict(list)
    for q, it in wd.items():
        for code, end in it["codes"].items():
            if not end and not (it["dissolved"] and it["dissolved"] <= TODAY):
                code2q[code.zfill(4)].append(q)
    ee = {}
    for code, name in cur.items():
        qs = sorted(code2q.get(code, []), key=lambda q: (q not in by_qid, int(q[1:])))
        q = qs[0] if qs else ""
        ee[code] = {"qid": q, "name": name, "names": {name}, "place_id": by_qid[q]["place_id"] if q in by_qid else (f"wd:{q}" if q else ""),
                    "in_candidate": q in by_qid}
    res["EE"] = ee
    return res


def current_missing():
    """Current official municipalities (BE REFNIS 2025, EE EHAK 2026v1) whose Wikidata item is not in the
    candidate list -> rows for place_additions.csv (used by build_place_additions.py)."""
    cm = current_maps()
    out = []
    for cc, m in cm.items():
        for code, v in sorted(m.items()):
            if v["in_candidate"] or not v["qid"]:
                continue
            out.append({"place_id": f"wd:{v['qid']}", "country_code": cc, "name": v["name"], "name_native": " / ".join(sorted(v["names"])),
                        "admin_level": "municipality", "parent_place_id": "", "iso_3166_2": "", "qid": v["qid"],
                        "official_code_system": "be_nis" if cc == "BE" else "ee_ehak", "official_code": code,
                        "source": "statbel TU_COM_REFNIS-20250101 + wikidata(qlever) P1567" if cc == "BE" else "EHAK 2026v1 + wikidata(qlever) P1140",
                        "note": "current municipality missing from candidate list (place_successors target)"})
    unmapped = [(cc, code, v["name"]) for cc, m in cm.items() for code, v in m.items() if not v["qid"]]
    return out, unmapped


def build():
    cm = current_maps()
    rows, problems = [], []
    # ---------------- BE
    ref = be_refnis()
    wd = wd_items("be")
    code2old = collections.defaultdict(list)
    for q, it in wd.items():
        for code, end in it["codes"].items():
            if re.fullmatch(r"\d{5}", code):
                code2old[code].append(q)
    mergers, renum = be_statbel_tables()
    official = {}  # old code -> (new code, source)
    for olds, (nname, ncode) in mergers:
        for oname, ocode in olds:
            if ocode != ncode:
                official[ocode] = (ncode, "statbel merger table 2024/2025")
    for ocode, (name, ncode) in renum.items():
        official.setdefault(ocode, (ncode, "statbel 2019 renumbering table (Hainaut)"))
    cur = cm["BE"]
    def be_current_code_of_q(q):
        it = wd.get(q)
        if not it:
            return None
        for code, end in it["codes"].items():
            if code in cur and not end:
                return code
        return None
    ended = {c: max(vs, key=lambda x: x["end"]) for c, vs in ref.items() if all(x["end"] < TODAY for x in vs)}
    for ocode, v in sorted(ended.items()):
        if v["end"] < "1977-01-01":
            continue
        dissolved = v["end"]
        succ, src = None, ""
        if ocode in official:
            succ, src = official[ocode]
        oq = sorted(code2old.get(ocode, []), key=lambda q: (BE_MUNI_CLS not in wd[q]["cls"], int(q[1:])))
        oq = oq[0] if oq else ""
        if not succ and ocode in BE_KNOWN:
            succ, src = BE_KNOWN[ocode], ("Flemish merger decree 2019" if dissolved == "2018-12-31" else "Antwerp merger law 1983")
        if not oq:
            oq = sorted((q for q, it in wd.items() if any(c[:5] == ocode for c in it["codes"])), key=lambda q: int(q[1:]))
            oq = oq[0] if oq else ""
        if not succ and oq:
            for sq, sd in wd[oq]["succ"].items():
                c = be_current_code_of_q(sq)
                if c is None and sq in wd:  # chain one more step through Wikidata
                    for sq2 in wd[sq]["succ"]:
                        c = c or be_current_code_of_q(sq2)
                if c:
                    succ, src = c, "wikidata P1366 (qlever)"
                    break
        if not succ:  # same name, code starting the day after in the same arrondissement
            nxt = (datetime.date.fromisoformat(dissolved) + datetime.timedelta(days=1)).isoformat()
            same = [c for c, vs in ref.items() for x in vs if x["start"] == nxt and x["nl"] == v["nl"]]
            if len(same) == 1:
                succ, src = same[0], "statbel REFNIS validity dates (same name, next day)"
            else:  # unique new code in the same arrondissement starting the next day (1977-1987 changes)
                same = sorted({c for c, vs in ref.items() for x in vs if x["start"] == nxt and x["arr"] == v["arr"]})
                if len(same) == 1:
                    succ, src = same[0], "statbel REFNIS validity dates (only new code in the arrondissement, next day)"
        seen = set()
        while succ and succ not in cur and succ not in seen:  # follow chains
            seen.add(succ)
            succ = official.get(succ, (None,))[0]
        if not succ or succ not in cur:
            problems.append(("BE", ocode, v["nl"], dissolved, "no successor found"))
            rows.append({"old_place_qid": oq, "old_name": v["nl"], "old_code": ocode, "dissolved_date": dissolved,
                         "successor_place_id": "", "successor_code": "", "source": "statbel REFNIS", "country_code": "BE",
                         "successor_name": "", "n_successors": 0, "note": "unresolved"})
            continue
        s = cur[succ]
        note = ""
        if True:
            nxt_ok = any(x["start"] <= (datetime.date.fromisoformat(dissolved) + datetime.timedelta(days=1)).isoformat() for x in ref[succ])
            note = "REFNIS dates consistent" if nxt_ok else "chain: successor code started later (via an intermediate code)"
        rows.append({"old_place_qid": oq, "old_name": v["nl"] if v["nl"] == v["fr"] else f"{v['nl']} / {v['fr']}", "old_code": ocode,
                     "dissolved_date": dissolved, "successor_place_id": s["place_id"], "successor_code": succ,
                     "source": src + "; statbel TU_COM_REFNIS-20250101", "country_code": "BE", "successor_name": s["name"],
                     "n_successors": 1, "note": note})
    # ---------------- EE
    wd = wd_items("ee")
    code2q = collections.defaultdict(list)
    for q, it in wd.items():
        for code in it["codes"]:
            code2q[code.zfill(4)].append(q)
    cur = cm["EE"]
    cur_by_name = collections.defaultdict(list)
    for c, v in cur.items():
        cur_by_name[norm(v["name"])].append(c)
    k17 = ee_2017()
    # 2017 interim code -> current code (same name; 2025 Jõhvi+Toila merger)
    def ee_now(code17, name17):
        c = f"{int(code17):04d}"
        if c in cur and norm(cur[c]["name"]) == norm(name17):
            return c, ""
        m = cur_by_name.get(norm(name17))
        if m and len(m) == 1:
            return m[0], "EHAK code changed after the 2017 ADS table"
        if norm(name17) == "toila vald":
            return "0250", "Jõhvi + Toila merged 2025 (EHAK 2025v5)"
        return None, ""
    succs = collections.defaultdict(list)
    names_old = {}
    for r in k17:
        oname, ocode, _mk, _mkc, _a, nname, ncode = r[:7]
        succs[f"{int(ocode):04d}"].append((nname, ncode))
        names_old[f"{int(ocode):04d}"] = oname
    for ocode, lst in sorted(succs.items()):
        oname = names_old[ocode]
        targets = []
        for nname, ncode in lst:
            c, why = ee_now(ncode, nname)
            if c:
                targets.append((c, why))
        targets = list(dict.fromkeys(targets))
        if len(targets) == 1 and targets[0][0] == ocode and not targets[0][1] and norm(cur[ocode]["name"]) == norm(oname):
            continue  # same code, same name: not dissolved
        oq = [q for q in code2q.get(ocode, []) if norm(wd[q]["label"]) in (norm(oname), norm(oname.replace(" vald", "").replace(" linn", "")))]
        oq = oq or code2q.get(ocode, [])
        oq = sorted(oq, key=lambda q: (not wd[q]["dissolved"], int(q[1:])))
        q0 = oq[0] if oq else ""
        diss = (wd[q0]["dissolved"] if q0 else "") or "2017-10-21"
        if not targets:
            problems.append(("EE", ocode, oname, diss, "no current successor"))
            continue
        for c, why in targets:
            rows.append({"old_place_qid": q0, "old_name": oname, "old_code": ocode, "dissolved_date": diss,
                         "successor_place_id": cur[c]["place_id"], "successor_code": c,
                         "source": "Maa-amet ADS haldusreformi EHAK järgnevused (2017) + EHAK 2025v5" + ("" if q0 else "") ,
                         "country_code": "EE", "successor_name": cur[c]["name"], "n_successors": len(targets),
                         "note": "; ".join(x for x in (why, "split: municipality divided between successors" if len(targets) > 1 else "") if x)})
    # pre-2017 mergers (2005-2014, e.g. Kärdla linn, Kõue vald): Wikidata P1366 chains to a 2017-table or current code
    done_old = {r["old_code"] for r in rows if r["country_code"] == "EE"} | set(succs)
    cur_items = {q: c.zfill(4) for q, it in wd.items() if not (it["dissolved"] and it["dissolved"] <= TODAY)
                 for c, end in it["codes"].items() if not end and c.zfill(4) in cur}
    for q, it in sorted(wd.items(), key=lambda kv: int(kv[0][1:])):
        codes = [c.zfill(4) for c in it["codes"]]
        gone = (it["dissolved"] and it["dissolved"] <= TODAY) or (it["succ"] and not any(c in cur for c in codes))
        if not gone or not re.search(r" (vald|linn)$", it["label"]):
            continue
        if not codes or any(c in done_old for c in codes):
            continue
        frontier, seen, hit, path = [q], {q}, None, []
        for _ in range(5):
            nxt = []
            for x in frontier:
                for sq in wd.get(x, {"succ": {}})["succ"]:
                    if sq in seen:
                        continue
                    seen.add(sq)
                    if sq in cur_items:
                        hit = ("cur", cur_items[sq], sq)
                    else:
                        for c in wd.get(sq, {"codes": {}})["codes"]:
                            if c.zfill(4) in succs:
                                hit = hit or ("2017", c.zfill(4), sq)
                    nxt.append(sq)
            if hit:
                break
            frontier = nxt
        if not hit:
            problems.append(("EE", codes[0], it["label"], it["dissolved"], "no P1366 chain to a current municipality"))
            continue
        if hit[0] == "cur":
            tgts = [(hit[1], "")]
        else:
            tgts = list(dict.fromkeys(t for t in (ee_now(nc, nn) for nn, nc in succs[hit[1]]) if t[0]))
        dd = it["dissolved"] or min((d for d in it["succ"].values() if d), default="")
        for c, why in tgts:
            rows.append({"old_place_qid": q, "old_name": it["label"], "old_code": codes[0], "dissolved_date": dd,
                         "successor_place_id": cur[c]["place_id"], "successor_code": c,
                         "source": "wikidata P576/P1366 chain (qlever)" + (" + Maa-amet 2017 EHAK järgnevused" if hit[0] == "2017" else "") + " + EHAK 2025v5",
                         "country_code": "EE", "successor_name": cur[c]["name"], "n_successors": len(tgts),
                         "note": "; ".join(x for x in (f"via {hit[2]}", why, "split" if len(tgts) > 1 else "") if x)})
        done_old.add(codes[0])
    # post-2017 EHAK changes not in the 2017 table (2017 entity -> current)
    have = {(r["old_code"], r["successor_code"]) for r in rows if r["country_code"] == "EE"}
    for r in k17:
        nname, ncode = r[5], f"{int(r[6]):04d}"
        c, why = ee_now(r[6], nname)
        if c and c != ncode and (ncode, c) not in have:
            have.add((ncode, c))
            q = sorted(code2q.get(ncode, []), key=lambda q: int(q[1:]))
            rows.append({"old_place_qid": q[0] if q else "", "old_name": nname, "old_code": ncode,
                         "dissolved_date": "2025-10-31" if "Toila" in why else "", "successor_place_id": cur[c]["place_id"],
                         "successor_code": c, "source": "EHAK 2025v5 vs 2017 ADS table", "country_code": "EE",
                         "successor_name": cur[c]["name"], "n_successors": 1, "note": why or "code renumbered"})
    for r in rows:
        if r["country_code"] == "EE" and r["old_code"] == "0803" and not r["dissolved_date"]:
            r["dissolved_date"] = "2025-11-27"  # Toila vald (2017-2025): EHAK 2025v5 (valid from 2025-11-28) merged it into Jõhvi
        r["source"] = r["source"].replace("EHAK 2025v5", "EHAK 2026v1")
    rows += manual_successors(problems)
    rows.sort(key=lambda r: (r["country_code"], r["old_code"], r["successor_code"]))
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(OUT)
    return rows, problems, cm


# PL / GR successors (reviewed 2026-10-17; Wikidata P576/P1366 via QLever, Law 4600/2019 art. 154 + YPES circular 83/2019
# for GR, pl.wikipedia/Eurostat LAU 2024 for PL TERC). Tuple: old_place_qid, old_name, old_code, dissolved_date (last day),
# successor_place_id, successor_code, successor_name, country_code, source, note
_L4600 = "Law 4600/2019 art. 154 (FEK A 43/2019), new municipalities from 2019-09-01; Wikidata P1366"
MANUAL_SUCCESSORS = [
    ("Q557603", "gmina Ostrowice", "3203042", "2018-12-31", "wd:Q558827", "3203023", "Gmina Drawsko Pomorskie", "PL",
     "Wikidata P576 2019-01-01; TERC (pl.wikipedia, NTS 4324403042/4324403023)", "split between 2 gminas"),
    ("Q557603", "gmina Ostrowice", "3203042", "2018-12-31", "wd:Q557287", "3203063", "Gmina Złocieniec", "PL",
     "Wikidata P576 2019-01-01; TERC (pl.wikipedia, Wikidata P1653 3203063)", "split between 2 gminas"),
    ("Q2426631", "gmina Zielona Góra (gmina wiejska)", "0809102", "2014-12-31", "wd:Q104720", "0862011", "Zielona Góra", "PL",
     "Wikidata P1653 0809102 (Q2426631) / 0862011 (Q104720); merger 2015-01-01",
     "rural gmina merged into the city with powiat rights (codes/proposed/PL_gmina_fill.csv)"),
    ("Q12875675", "Δήμος Κέρκυρας (Corfu)", "6147", "2019-08-31", "wd:Q64865001", "100049209",
     "Municipality of Central Corfu and Diapontia Islands", "GR", _L4600, "codes = Diavgeia org uid"),
    ("Q12875675", "Δήμος Κέρκυρας (Corfu)", "6147", "2019-08-31", "wd:Q64868574", "100049339", "Northern Corfu Municipality",
     "GR", _L4600, "codes = Diavgeia org uid"),
    ("Q12875675", "Δήμος Κέρκυρας (Corfu)", "6147", "2019-08-31", "wd:Q65273062", "100049235", "Southern Corfu Municipality",
     "GR", _L4600, "codes = Diavgeia org uid"),
    ("Q1737776", "Δήμος Κεφαλονιάς (Kefalonia)", "6148", "2019-08-31", "wd:Q12875628", "100049102", "Argostoli Municipality",
     "GR", _L4600, "codes = Diavgeia org uid"),
    ("Q1737776", "Δήμος Κεφαλονιάς (Kefalonia)", "6148", "2019-08-31", "wd:Q102144417", "100049127", "Lixouri Municipality",
     "GR", _L4600, "codes = Diavgeia org uid"),
    ("Q1737776", "Δήμος Κεφαλονιάς (Kefalonia)", "6148", "2019-08-31", "wd:Q21556096", "100049133", "Municipality of Sami",
     "GR", _L4600, "codes = Diavgeia org uid"),
    ("Q2520681", "Δήμος Λέσβου (Lesbos)", "6172", "2019-08-31", "wd:Q16737235", "100049029", "Mytilene Municipality",
     "GR", _L4600, "codes = Diavgeia org uid"),
    ("Q2520681", "Δήμος Λέσβου (Lesbos)", "6172", "2019-08-31", "wd:Q65234114", "100049040", "West Lesvos Municipality",
     "GR", _L4600, "codes = Diavgeia org uid"),
    ("Q2520687", "Δήμος Σάμου (Samos)", "6268", "2019-08-31", "wd:Q65227148", "100049544", "East Samos Municipality",
     "GR", _L4600, "codes = Diavgeia org uid"),
    ("Q2520687", "Δήμος Σάμου (Samos)", "6268", "2019-08-31", "wd:Q65234121", "100049554", "West Samos Municipality",
     "GR", _L4600, "codes = Diavgeia org uid"),
]


def manual_successors(problems):
    cand = set()
    with CANDIDATE.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["country_code"] in ("PL", "GR"):
                cand.add(r["place_id"].strip())
    n = collections.Counter(t[0] for t in MANUAL_SUCCESSORS)
    out = []
    for oq, oname, ocode, diss, spid, scode, sname, cc, src, note in MANUAL_SUCCESSORS:
        if spid not in cand:
            problems.append((cc, ocode, oname, diss, f"manual successor {spid} not a candidate place; dropped"))
            continue
        out.append({"old_place_qid": oq, "old_name": oname, "old_code": ocode, "dissolved_date": diss,
                    "successor_place_id": spid, "successor_code": scode, "source": src, "country_code": cc,
                    "successor_name": sname, "n_successors": n[oq], "note": note})
    return out


# --------------------------------------------------------------------------- read-only mapping test
def test_unmatched(rows, cm):
    by_name = {"BE": collections.defaultdict(set), "EE": collections.defaultdict(set)}
    for cc in ("BE", "EE"):
        for code, v in cm[cc].items():
            for n in v["names"]:
                by_name[cc][norm(n)].add(v["place_id"])
    old_name = {"BE": collections.defaultdict(set), "EE": collections.defaultdict(set)}
    for r in rows:
        if r["successor_place_id"]:
            for n in r["old_name"].split(" / "):
                old_name[r["country_code"]][norm(n)].add(r["successor_place_id"])
                old_name[r["country_code"]][norm(re.sub(r"\s*\(.*?\)$", "", n))].add(r["successor_place_id"])
    res = {}
    for pre, cc, fld in (("belb", "BE", "issuing_body_name"), ("eert", "EE", "place_name")):
        docs = {}
        for fn in sorted(glob.glob(str(STAGING / "eu" / "_unmatched" / f"{pre}_*.jsonl"))):
            with open(fn, encoding="utf-8") as f:
                for line in f:
                    d = json.loads(line)
                    docs[d["doc_id"]] = d
        c = collections.Counter()
        unm = collections.Counter()
        for d in docs.values():
            n = norm(d.get(fld) or "")
            if cc == "EE" and norm(d.get(fld) or "") == "tallinn linn":
                n = "tallinn"
            if cc == "BE" and (d.get("issuing_body_class") == "Provincie"):
                c["province (iso:BE-*, national repo)"] += 1
                continue
            if not n:
                c["no_name"] += 1
                continue
            cur_hit = by_name[cc].get(n)
            if cur_hit and len(cur_hit) == 1:
                c["current_name"] += 1
                continue
            old_hit = old_name[cc].get(n)
            if old_hit and len(old_hit) == 1:
                c["via_successor"] += 1
                continue
            if old_hit:
                c["via_successor_ambiguous(split)"] += 1
                continue
            c["unmapped"] += 1
            unm[d.get(fld)] += 1
        res[cc] = {"docs": len(docs), **dict(c), "mapped": c["current_name"] + c["via_successor"],
                   "unmapped_names": unm.most_common(15)}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--test-unmatched", action="store_true")
    a = ap.parse_args()
    if a.refresh:
        refresh()
    rows, problems, cm = build()
    cnt = collections.Counter((r["country_code"], bool(r["successor_place_id"])) for r in rows)
    print(f"wrote {OUT} rows={len(rows)}", dict(cnt))
    for p in problems:
        print("  problem:", p, file=sys.stderr)
    miss, unmapped = current_missing()
    print("current municipalities missing from candidate:", collections.Counter(r["country_code"] for r in miss),
          "no wikidata item:", unmapped)
    if a.test_unmatched:
        print(json.dumps(test_unmatched(rows, cm), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
