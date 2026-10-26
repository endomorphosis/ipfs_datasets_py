"""Build au_tranche2/config.json from the survey probe files.

Doc selection follows tranche-1 practice: law texts only — registers,
summaries, resolutions, consultations, notices, undertakings, impact
statements, application forms, superseded versions and amendment-only
docs (where a consolidated text exists) are excluded. Every exclusion
is a per-council predicate below, auditable against the probe files.
"""
import html as H
import json, re
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
HF = HERE.parent


def clean(t, url):
    t = H.unescape(t or "").replace("​", "").strip()
    t = re.sub(r"\(PDF[^)]*\)", "", t)
    t = re.sub(r"^\s*(Download|View|Read the)\s+", "", t, flags=re.I)
    t = re.sub(r"\s+\d+(\.\d+)?\s*(KB|MB)\s*$", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" -")
    if re.fullmatch(r"\[?\s*pdf\s*[-–].*\]?", t, flags=re.I):
        t = ""  # link text was only a file-size label (e.g. South Perth)
    if len(t) < 4:
        fn = unquote(urlparse(url).path.rsplit("/", 1)[-1])
        t = re.sub(r"\.pdf$", "", fn, flags=re.I).replace("-", " ").replace("_", " ")
        t = re.sub(r"\s+", " ", t).strip()
    return t[:110]


def docs_from(entries, keep):
    out, seen = [], set()
    for e in entries:
        u = e["url"]
        key = u.split("?")[0]
        if key in seen:
            continue
        t = clean(e.get("text", ""), u)
        if keep(t, u):
            seen.add(key)
            out.append([t, u])
    return out


ALL = lambda t, u: True  # noqa: E731

KEEP = {
    "40700": lambda t, u: t.startswith("By-Law No"),                       # Burnside: numbered by-laws only
    "57840": lambda t, u: ("undertaking" not in u and "sealed-document" not in u
                           and "2024" not in u),                            # South Perth: latest versions, no undertakings/sealed amendments
    "58570": lambda t, u: ("Local Law" in t and not t.startswith("List of")
                           and "Parking Stations" not in t),                # Vincent
    "53800": lambda t, u: ("Amendment" not in t and "SPECIAL_GAZETTE" not in u),  # Geraldton (family-dedupe below)
    "57280": lambda t, u: ("Undertaking" not in t and "Amendment" not in t),      # Port Hedland
    "54200": lambda t, u: ("/local-laws/" in u and "as-2187" not in u),           # Kalamunda: law library only, no AS reference
    "40120": lambda t, u: "2025.pdf" in u,                                        # Adelaide Hills: current 2025 set
    "26810": lambda t, u: "as Amended" in t,                                      # Wellington: current consolidated only
    "41060": lambda t, u: False,                                                  # Charles Sturt: register/conditions only — excluded
    "32810": lambda t, u: False,                                                  # Douglas: application forms only — excluded
    "63010": lambda t, u: False,                                                  # Huon Valley: media release + draft notice — excluded
}

ORDER = ["64810", "60410", "60810", "65810", "45040", "44340", "40700", "44550",
         "40310", "40120", "57840", "51330", "58570", "50420", "50210", "54200",
         "54310", "57280", "53800", "54280", "27350", "21450", "26810", "34880"]


def family_dedupe(docs):
    """Geraldton: prefer the CONSOLIDATED variant within each law family."""
    def fam(t):
        t = re.sub(r"\b(Local Law|Consolidated|City of Greater Geraldton)\b", "", t, flags=re.I)
        return re.sub(r"[^a-z]", "", t.lower())[:14]
    best = {}
    for t, u in docs:
        f = fam(t)
        cur = best.get(f)
        if cur is None or ("consolidat" in u.lower() and "consolidat" not in cur[1].lower()):
            best[f] = (t, u)
    return [[t, u] for t, u in best.values()]


def main():
    surf = json.loads((HERE / "survey" / "probe.json").read_text())
    deep = json.loads((HERE / "survey" / "probe_deep.json").read_text())
    surf2 = json.loads((HERE / "survey" / "probe2.json").read_text())
    deep2p = HERE / "survey" / "probe_deep2.json"
    deep2 = json.loads(deep2p.read_text()) if deep2p.exists() else {}
    reg = {}
    for ln in (HF / "au_pilot" / "data" / "jurisdictions.jsonl").read_text().splitlines():
        r = json.loads(ln)
        if r["kind"] == "lga":
            reg[r["code"]] = r
    cfg = {}
    for code in ORDER:
        src = None
        for book in (deep2, deep, surf, surf2):
            if code in book and book[code].get("law_pdfs"):
                src = book[code]
                if book[code].get("law_pdf_count"):
                    break
        if src is None:
            print(f"{code}: NO SOURCE — skipped"); continue
        keep = KEEP.get(code, ALL)
        docs = docs_from(src["law_pdfs"], keep)
        if code == "53800":
            docs = family_dedupe(docs)
        if not docs:
            print(f"{code}: 0 docs after filter — skipped"); continue
        base = src.get("base", "")
        cfg[code] = {"state": reg[code]["state_name21"],
                     "platform": f"council site ({urlparse(base).netloc})" if base else "council site",
                     "docs": docs}
        print(f"{code} {reg[code]['name']}: {len(docs)} docs")
    (HERE / "config.json").write_text(json.dumps(cfg, indent=1, ensure_ascii=False))
    print("config councils:", len(cfg))


if __name__ == "__main__":
    main()
