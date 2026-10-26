#!/usr/bin/env python3
"""Canada census step 1: resolve municipal website URLs for the 3,489
municipal-government CSDs in the pilot SGC registry.

Sources, in priority order:
  1. pilot_seed      — hosts verified live by the pilot (probe files / report)
  2. qc_mamh         — Quebec MAMH repertoire MUN.csv (mweb), name-matched
  3. on_fippa        — Ontario FIPPA/MFIPPA Directory of Institutions (Website col)
  4. pattern_http    — systematic name-pattern domain candidates, accepted only
                       when the fetched homepage names the municipality
Every resolved row records url_source. Unresolved rows -> status no_site_found.
"""
import csv, io, json, re, sys, unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests

HERE = Path(__file__).resolve().parent
CENSUS = HERE.parent
PILOT = CENSUS.parent / "ca_pilot"
SRC = CENSUS / "sources"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) ca-platform-census/1.0"}

def norm(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

def slug(s):
    return norm(s).replace(" ", "")

LEAD = re.compile(r"^(city|town|township|village|municipality|municipal district|"
                  r"rural municipality|district|county|regional municipality|"
                  r"resort village|northern village|summer village|specialized municipality) of ")
def core_name(name):
    n = norm(name)
    n = LEAD.sub("", n)
    # StatCan sometimes appends the type in parens; norm() already flattened them
    return n

# ---------- source 1: pilot seeds (name keys are norm(name), province) ----------
PILOT_SEEDS = {
    ("toronto", "Ontario"): "https://www.toronto.ca",
    ("surrey", "British Columbia"): "https://www.surrey.ca",
    ("halifax", "Nova Scotia"): "https://www.halifax.ca",
    ("gatineau", "Quebec"): "https://www.gatineau.ca",
    ("mississauga", "Ontario"): "https://www.mississauga.ca",
    ("brampton", "Ontario"): "https://www.brampton.ca",
    ("hamilton", "Ontario"): "https://www.hamilton.ca",
    ("ottawa", "Ontario"): "https://ottawa.ca",
    ("winnipeg", "Manitoba"): "https://winnipeg.ca",
    ("calgary", "Alberta"): "https://www.calgary.ca",
    ("edmonton", "Alberta"): "https://www.edmonton.ca",
    ("vancouver", "British Columbia"): "https://vancouver.ca",
    ("guelph", "Ontario"): "https://www.guelph.ca",
    ("kingston", "Ontario"): "https://www.cityofkingston.ca",
    ("moncton", "New Brunswick"): "https://www.moncton.ca",
    ("regina", "Saskatchewan"): "https://www.regina.ca",
    ("saskatoon", "Saskatchewan"): "https://www.saskatoon.ca",
    ("victoria", "British Columbia"): "https://www.victoria.ca",
    ("charlottetown", "Prince Edward Island"): "https://www.charlottetown.ca",
}

# ---------- source 2: QC MAMH ----------
def qc_map():
    raw = (SRC / "qc_mun.csv").read_bytes().decode("utf-8-sig", "replace")
    rows = list(csv.reader(io.StringIO(raw), delimiter=","))
    hdr = [h.strip().strip('"') for h in rows[0][0].split(",")] if rows else []
    out = {}
    # the file is comma-delimited with a quoted super-header quirk; parse properly:
    rd = csv.DictReader(io.StringIO(raw))
    for r in rd:
        keys = {k.strip().strip('\ufeff"'): v for k, v in r.items() if k}
        name = keys.get("munnom", "").strip().strip('"')
        web = keys.get("mweb", "").strip().strip('"')
        if name and web:
            out.setdefault(norm(name), web if web.startswith("http") else "https://" + web)
    return out

# ---------- source 3: ON FIPPA ----------
def on_map():
    raw = (SRC / "on_fippa_en.csv").read_bytes().decode("utf-8-sig", "replace")
    rd = csv.DictReader(io.StringIO(raw))
    out = {}
    types = {}
    for r in rd:
        itype = (r.get("Institution type") or "").strip()
        types[itype] = types.get(itype, 0) + 1
        web = (r.get("Website") or "").strip()
        name = re.sub(r"<[^>]+>", "", r.get("Name of institution") or "").strip()
        if web and web.lower() != "not available" and (
            "municip" in itype.lower() or "county" in itype.lower() or "region" in itype.lower()):
            out.setdefault(norm(name), web if web.startswith("http") else "https://" + web)
    print("ON FIPPA institution types:", types, file=sys.stderr)
    return out

# ---------- source 4: pattern candidates ----------
TYPE_PREFIX = {
    "T": "townof", "TV": "townof", "CY": "cityof", "C": "cityof",
    "VL": "villageof", "V": "ville", "TP": "townshipof", "RM": "rmof",
    "MD": "mdof", "DM": "districtof", "MU": "municipalityof",
    "MÉ": "municipalite", "RGM": "municipalityof", "CT": "canton",
    "RV": "resortvillageof", "NV": "northernvillageof", "SV": "summervillageof",
}
def candidates(row, short=False):
    core = core_name(row["name"])
    s = core.replace(" ", "")
    hyph = core.replace(" ", "-")
    if not s:
        return []
    pref = TYPE_PREFIX.get(row["csd_type"])
    if short:
        # pass 1: two highest-yield guesses, order tuned by province/type
        if row["province"] == "Quebec":
            return [f"ville.{s}.qc.ca", f"{s}.qc.ca"]
        plain = f"{s}.ca"
        prefixed = f"{pref}{s}.ca" if pref else f"{s}.com"
        if row["province"] == "Newfoundland and Labrador" and pref == "townof":
            return [prefixed, plain]
        if row["csd_type"] in ("RM", "VL") and pref:
            return [prefixed, plain]
        return [plain, prefixed]
    doms = []
    if row["province"] == "Quebec":
        doms += [f"ville.{s}.qc.ca", f"{s}.qc.ca", f"ville{s}.qc.ca",
                 f"municipalite.{s}.qc.ca", f"www.ville.{s}.qc.ca"]
    doms.append(f"{s}.ca")
    if pref and row["province"] != "Quebec":
        doms.append(f"{pref}{s}.ca")
    doms += [f"{hyph}.ca"]
    if pref and row["province"] == "Quebec":
        doms.append(f"{pref}{s}.qc.ca")
    doms += [f"{s}.com", f"{s}.org"]
    doms.append(f"{s}.civicweb.net")
    doms.append(f"pub-{s}.escribemeetings.com")
    # de-dupe, keep order
    seen, out = set(), []
    for d in doms:
        if d not in seen:
            seen.add(d); out.append(d)
    return out

TOKEN_BAD = {"facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com"}
def verify(domain, core, quick=False):
    """Return final URL if domain serves a page naming the municipality."""
    token = max(core.split(), key=len) if core.split() else ""
    if quick:
        schemes = (f"https://www.{domain}", f"https://{domain}")
        tout = (20, 25)
    else:
        schemes = (f"https://www.{domain}", f"https://{domain}",
                   f"http://www.{domain}")
        tout = (30, 30)
    for scheme_host in schemes:
        try:
            r = requests.get(scheme_host, headers=UA, timeout=tout, stream=True,
                             allow_redirects=True)
            final = r.url
            host = re.sub(r"^www\.", "", requests.utils.urlparse(final).netloc.lower())
            if any(b in host for b in TOKEN_BAD):
                r.close(); return None
            if r.status_code >= 400:
                r.close(); continue
            body = b""
            for chunk in r.iter_content(8192):
                body += chunk
                if len(body) > 40000: break
            r.close()
            text = unicodedata.normalize("NFKD", body.decode("utf-8", "replace"))
            text = "".join(c for c in text if not unicodedata.combining(c)).lower()
            if token and len(token) >= 4 and (token in text or core.replace(" ", "") in re.sub(r"[^a-z0-9]", "", text)):
                return final
            return None  # resolved host but doesn't name the town: wrong site
        except requests.RequestException:
            continue
    return None

def resolve_pattern(row, short=False):
    core = core_name(row["name"])
    for dom in candidates(row, short=short):
        if dom.endswith("civicweb.net") or "escribemeetings.com" in dom:
            # platform subdomains: existence via robots.txt only, no page fetch
            try:
                r = requests.get(f"https://{dom}/robots.txt", headers=UA, timeout=(30, 30))
                if r.status_code == 200 and len(r.content) > 10:
                    kind = "civicweb_pattern" if dom.endswith("civicweb.net") else "escribe_pattern"
                    return f"https://{dom}", kind
            except requests.RequestException:
                pass
            continue
        url = verify(dom, core, quick=short)
        if url:
            return url, "pattern_http"
    return None, None

def main():
    reg = [json.loads(l) for l in open(PILOT / "sgc_registry_2021.jsonl")]
    muni = [r for r in reg if r["municipal_government"]]
    print(f"municipal CSDs: {len(muni)}", file=sys.stderr)
    qc = qc_map(); print(f"QC MAMH names with web: {len(qc)}", file=sys.stderr)
    on = on_map(); print(f"ON FIPPA names with web: {len(on)}", file=sys.stderr)

    out_path = SRC / "resolved.jsonl"
    done = {}
    if out_path.exists():
        for l in open(out_path):
            d = json.loads(l); done[d["sgc"]] = d
    todo = []
    with open(out_path, "a") as fh:
        for row in muni:
            if row["sgc"] in done: continue
            key = (norm(row["name"]), row["province"])
            rec = {"sgc": row["sgc"], "name": row["name"], "csd_type": row["csd_type"],
                   "province": row["province"]}
            if key in PILOT_SEEDS:
                rec.update(website_url=PILOT_SEEDS[key], url_source="pilot_seed")
            elif row["province"] == "Quebec" and norm(row["name"]) in qc:
                rec.update(website_url=qc[norm(row["name"])], url_source="qc_mamh_repertoire")
            elif row["province"] == "Ontario" and norm(row["name"]) in on:
                rec.update(website_url=on[norm(row["name"])], url_source="on_fippa_directory")
            else:
                # ON FIPPA names carry type prefixes ("Township of X"); try core match
                hit = None
                if row["province"] == "Ontario":
                    for k, v in on.items():
                        if core_name(k) == core_name(row["name"]):
                            hit = v; break
                if hit:
                    rec.update(website_url=hit, url_source="on_fippa_directory")
                else:
                    todo.append((row, rec)); continue
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n"); fh.flush()
            done[row["sgc"]] = rec
    print(f"directory-resolved: {len(done)}, pattern todo: {len(todo)}", file=sys.stderr)
    _rank = {"CY": 0, "C": 0, "CV": 0, "V": 0, "T": 1, "DM": 2, "MÉ": 3,
             "M": 3, "CT": 4, "TP": 4, "VL": 5, "VN": 5, "VC": 5, "VK": 5,
             "PE": 6, "PAR": 6, "RM": 7, "MD": 7, "RGM": 7, "RMU": 7,
             "CU": 8, "GR": 8}
    todo.sort(key=lambda it: (_rank.get(it[0]["csd_type"], 9),
                              it[0]["province"], it[0]["name"]))

    short = "--pass1" in sys.argv

    def work(item):
        row, rec = item
        url, src = resolve_pattern(row, short=short)
        if url: rec.update(website_url=url, url_source=src)
        else: rec.update(website_url=None, url_source=None)
        return rec
    with open(out_path, "a") as fh, ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(work, it): it for it in todo}
        n = 0
        for f in as_completed(futs):
            rec = f.result()
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n"); fh.flush()
            n += 1
            if n % 200 == 0: print(f"pattern {n}/{len(todo)}", file=sys.stderr)
    print("DONE", file=sys.stderr)

if __name__ == "__main__":
    main()
