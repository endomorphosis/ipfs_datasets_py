#!/usr/bin/env python3
"""Build ph_cities.jsonl/.csv: the 149 PH cities (HUC/ICC/CC) from Wikidata (QLever) P31 in
{Q29946056 HUC, Q106079704 ICC, Q106078286 CC} (subclasses of Q104157 city of the Philippines), with P988 PSGC,
P856 website, P625 coords, P131 province/region. Cross-checked against psgc.gitlab.io (PSA PSGC mirror) and the
PSA official total (3Q 2026: 33 HUC + 5 ICC + 111 CC = 149)."""
import csv, json, re, collections
from pathlib import Path
HERE = Path(__file__).resolve().parent; C = HERE / "cache"
CLS = {"Q29946056": "HUC", "Q106079704": "ICC", "Q106078286": "CC"}
PSA_TOTAL = {"HUC": 33, "ICC": 5, "CC": 111}
q = lambda s: re.sub(r".*/(Q\d+)>?$", r"\1", s) if s else ""
lit = lambda s: re.sub(r'^"?(.*?)"?(@[\w-]+)?$', r"\1", s or "").strip()
url = lambda s: (s or "").strip("<>")
def tsv(n):
    with (C / n).open(encoding="utf-8") as f:
        rd = csv.reader(f, delimiter="\t"); h = [x.lstrip("?") for x in next(rd)]
        return [dict(zip(h, r + [""] * (len(h) - len(r)))) for r in rd]
labels = collections.defaultdict(dict)
for r in tsv("wd_ph_labels.tsv"):
    labels[q(r["i"])][lit(r["lang"])] = lit(r["l"])
lab = lambda x: next((labels[x][k] for k in ("en", "mul", "tl", "ceb", "es") if labels[x].get(k)), "")
prov_reg = {q(r["p"]): q(r["r"]) for r in tsv("wd_ph_prov_region.tsv")}
gl = {c["psgc10DigitCode"]: c for c in json.load(open(C / "psgc_gitlab_cities.json"))}
glp = {p["code"]: p["name"] for p in json.load(open(C / "psgc_gitlab_provinces.json"))}
glr = {p["code"]: p["name"] for p in json.load(open(C / "psgc_gitlab_regions.json"))}
import unicodedata
def norm(n):
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"\b(city|of|science|island garden)\b", " ", n.replace("sto.", "santo"))
    return re.sub(r"[^a-z]", "", n)
# PSA PSGC 1Q 2026 publication datafile as parsed by github.com/alkevintan/psgc-rb (PSA xlsx is Cloudflare-gated)
psa_cm = json.load(open(C / "psgcrb_cities_municipalities.json"))
psa_city = {c["code"]: c["name"] for c in psa_cm if "City" in c["name"]}
psa_prov = {p["code"]: p["name"] for p in json.load(open(C / "psgcrb_provinces.json"))}
psa_reg = {p["code"]: p["name"] for p in json.load(open(C / "psgcrb_regions.json"))}
gl9 = {c["code"]: c for c in json.load(open(C / "psgc_gitlab_cities.json"))}
by_name = collections.defaultdict(list)
for c, n in psa_city.items(): by_name[norm(n)].append(c)
def to_psa(codes, names):
    cand = []
    for p in codes:
        if len(p) == 10: cand.append(p)
        elif len(p) == 9:
            cand.append(p[:2] + "0" + p[2:])
            if p in gl9: cand.append(gl9[p]["psgc10DigitCode"])
    for c in cand:
        if c in psa_city: return c, "code"
    for n in names:
        h = by_name.get(norm(n), [])
        if len(h) == 1: return h[0], "name"
        h2 = [x for x in h if any(len(c) == 9 and x[3:5] == c[2:4] and x[5:] == c[4:] for c in codes)]
        if len(h2) == 1: return h2[0], "name+province/city digits"
        h = [x for x in h if any(x[:2] == c[:2] for c in cand)]
        if len(h) == 1: return h[0], "name+region"
    return "", ""
it = {}
for r in tsv("wd_ph_cities.tsv"):
    x = it.setdefault(q(r["i"]), {"cls": set(), "psgc": set(), "web": set(), "coord": set(), "prov": set(), "reg": set()})
    x["cls"].add(CLS[q(r["cls"])])
    if r["psgc"]: x["psgc"].add(lit(r["psgc"]))
    if r["web"]: x["web"].add(url(r["web"]))
    if r["coord"]: x["coord"].add(r["coord"])
    pc = q(r["parcls"])
    if pc == "Q24746": x["prov"].add(q(r["par"]))
    elif pc == "Q24698": x["reg"].add(q(r["par"]))
rows, gaps = [], []
for Q, x in sorted(it.items(), key=lambda kv: int(kv[0][1:])):
    cls = sorted(x["cls"]); psgc = sorted(x["psgc"])
    if len(cls) > 1: gaps.append((Q, lab(Q), "multiple_city_classes", cls))
    if len(psgc) != 1: gaps.append((Q, lab(Q), "psgc_count", psgc))
    p10, how = to_psa(psgc, [lab(Q)] + list(labels[Q].values()))
    if not p10: gaps.append((Q, lab(Q), "not_matched_to_psa_psgc", psgc))
    elif how != "code": gaps.append((Q, lab(Q), "psa_code_matched_by_" + how + " (wikidata P988 outdated/other format)", f"{psgc} -> {p10}"))
    lat = lon = None
    if x["coord"]:
        m = re.search(r"POINT\(([-\d.]+) ([-\d.]+)\)", sorted(x["coord"])[0]); lon, lat = float(m[1]), float(m[2])
    prov = sorted(x["prov"]); regs = set(x["reg"]) | {prov_reg[p] for p in prov if p in prov_reg}
    g = {"name": psa_city.get(p10, "")}
    name = lab(Q) or g["name"]
    pp = p10[:5] + "00000" if p10 else ""
    if pp in psa_prov and cls != ["HUC"]: prov_psa = psa_prov[pp]
    else: prov_psa = ""
    reg_psa = psa_reg.get(p10[:2] + "00000000", "") if p10 else ""
    if not x["web"]: gaps.append((Q, name, "no_official_website_P856", ""))
    if lat is None: gaps.append((Q, name, "no_coordinates", ""))
    pid = f"wd:{Q}"
    rows.append({"name": name, "qid": Q, "place_id": pid, "place_key": pid.replace(":", "_"), "psgc_code": p10,
                 "psgc_code_wikidata": "; ".join(psgc),
                 "province": prov_psa or "; ".join(lab(p) for p in prov), "province_wikidata": "; ".join(lab(p) for p in prov), "province_qid": "; ".join(prov),
                 "region": reg_psa or "; ".join(sorted(lab(r) for r in regs)), "region_qid": "; ".join(sorted(regs)),
                 "city_class": "/".join(cls), "official_website": "; ".join(sorted(x["web"])),
                 "official_websites": sorted(x["web"]), "lat": lat, "lon": lon,
                 "psa_name": g["name"],
                 "source": "wikidata(qlever) P31 HUC/ICC/CC + P988/P856/P625/P131; PSA PSGC 1Q 2026 (via psgc-rb parse) codes/province/region"})
seen = collections.Counter(r["psgc_code"] for r in rows)
gaps += [("", "", "duplicate_psgc", c) for c, n in seen.items() if n > 1 and c]
for c, n in psa_city.items():
    if c not in seen: gaps.append(("", n, "psa_city_without_wikidata_city_item", c))
with (HERE / "ph_cities.jsonl").open("w", encoding="utf-8") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
cols = [k for k in rows[0] if k != "official_websites"]
with (HERE / "ph_cities.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
with (HERE / "ph_cities_gaps.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["qid", "name", "issue", "detail"]); w.writerows(gaps)
cnt = collections.Counter(r["city_class"] for r in rows)
print("rows", len(rows), dict(cnt), "PSA", PSA_TOTAL, "website", sum(bool(r["official_website"]) for r in rows),
      "coords", sum(r["lat"] is not None for r in rows), "province", sum(bool(r["province"]) for r in rows),
      "region", sum(bool(r["region"]) for r in rows))
for g_ in gaps: print(" gap:", g_)
