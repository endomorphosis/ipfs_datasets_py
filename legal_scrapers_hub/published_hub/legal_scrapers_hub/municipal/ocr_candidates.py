"""Image-only PDF lists for an OCR pass (not run: OCR is not approved). Adds MANIFEST['excluded_image_only_pdfs'] to packs whose build
did not write it (LU from its MANIFEST drops + the crawl's commune list / link texts; GR records 0 scans) and writes the combined
ocr_candidates.json next to the packs. MANIFEST is outside the sha256 list, so no data / scraper hash changes. Local only.
Usage: python ocr_candidates.py <municipal dir> [lu_build dir] [gr_build dir]"""
import json, os, re, sys, collections, urllib.parse, datetime, unicodedata
MUN = sys.argv[1] if len(sys.argv) > 1 else "."; LUB = sys.argv[2] if len(sys.argv) > 2 else "lu_build"
GRB = sys.argv[3] if len(sys.argv) > 3 else "gr_build"
cnt = lambda xs: dict(sorted(collections.Counter(x["municipality"] for x in xs).items()))
LU_REG = re.compile(r"(?i)r[eè]glement|reglement|verordnung|ordonnance|statuts?\b|taxe|tarif|geb[uü]hr")
LU_NOT = re.compile(r"(?i)\b(plan|pap|pag|carte|map|formulaire|formular|demande|antrag|avis|rapport|bericht|brochure|flyer|invitation|proc[eè]s[- ]verbal|s[eé]ance|sitzung)\b")
def block(img, bad, flag, note):
    return dict(note=note, count=len(img), likely_regulation_count=sum(x[flag] for x in img), per_municipality=cnt(img),
                per_municipality_likely_regulation=cnt([x for x in img if x[flag]]), items=img,
                broken_text_layer=dict(count=len(bad), per_municipality=cnt(bad), items=bad))
def write_manifest(pack, key_block):
    mp = f"{pack}/MANIFEST.json"; m = json.load(open(mp, encoding="utf-8"))
    m["excluded_image_only_pdfs"] = key_block
    hr = f"{pack}/HANDOFF_READY"; had = os.path.exists(hr)
    if had: os.remove(hr)
    json.dump(m, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if had: open(hr, "w").close()                                  # HANDOFF_READY last
def lu():
    pack = f"{MUN}/luxembourg_municipal"; m = json.load(open(f"{pack}/MANIFEST.json", encoding="utf-8"))
    names = {c["lau"]: c["name"] for c in json.load(open(f"{LUB}/communes.json", encoding="utf-8")) if c.get("lau")}
    lt = {}
    if os.path.exists(f"{LUB}/links.jsonl"):
        for l in open(f"{LUB}/links.jsonl", encoding="utf-8"): r = json.loads(l); lt[r["url"]] = r.get("link_text")
    def item(d):
        name = (lt.get(d["url"]) or "") + " " + urllib.parse.unquote(d["url"].split("?")[0].rsplit("/", 1)[-1]) + " " + urllib.parse.unquote(d["url"]).split("filename=")[-1]
        name = "".join(ch for ch in unicodedata.normalize("NFKD", name) if not unicodedata.combining(ch))     # NFD file names ('Re\u0300glement')
        return dict(url=d["url"], municipality=names.get(d.get("lau"), d.get("lau")), municipality_code=d.get("lau"), pages=d.get("pages"),
                    link_text=lt.get(d["url"]), reason=d["reason"],
                    likely_regulation=bool(LU_REG.search(name)) and not LU_NOT.search(name) and (d.get("pages") or 0) >= 1)
    drops = m.get("build_dropped_text_layer", [])
    img = [item(d) for d in drops if d["reason"] == "no_text_layer_scanned"]
    bad = [item(d) for d in drops if d["reason"] in ("garbled_ocr_text_layer", "bad_text_layer_replacement_chars")]
    b = block(img, bad, "likely_regulation", "Image-only PDFs excluded (no OCR). likely_regulation: link text / file name names a règlement / Verordnung / taxe "
              "and not a plan, form, notice, report or minutes. broken_text_layer: an old OCR layer that is garbled, or replacement characters.")
    write_manifest(pack, b); return b
def gr():
    pack = f"{MUN}/greece_municipal"; m = json.load(open(f"{pack}/MANIFEST.json", encoding="utf-8"))
    drops = m.get("build_dropped_text_layer", []); want = {d["ada"] for d in drops}; kal = {}; doc = {}
    if os.path.exists(f"{GRB}/candidates.jsonl"):                  # ada -> Kallikratis code / document URL, from the collector's list
        mn = {x["kal"]: x["name"] for x in json.load(open(f"{GRB}/munis.json", encoding="utf-8"))}
        for l in open(f"{GRB}/candidates.jsonl", encoding="utf-8"):
            r = json.loads(l)
            if r.get("ada") in want: kal[r["ada"]] = (r.get("_kal"), mn.get(r.get("_kal"))); doc[r["ada"]] = r.get("documentUrl")
    for d in drops: d["municipality_code"], d["municipality"] = kal.get(d["ada"], (None, "unknown"))
    img = [dict(url=doc.get(d["ada"]) or f"https://diavgeia.gov.gr/doc/{d['ada']}", ada=d["ada"], municipality=d.get("municipality"), reason=d["reason"], likely_regulation=True)
           for d in drops if d["reason"] == "no_text_layer"]
    bad = [dict(url=doc.get(d["ada"]) or f"https://diavgeia.gov.gr/doc/{d['ada']}", ada=d["ada"], municipality=d.get("municipality"),
                municipality_code=d.get("municipality_code"), reason=d["reason"])
           for d in drops if d["reason"] != "no_text_layer"]
    b = block(img, bad, "likely_regulation", "Diavgeia acts are born-digital signed PDFs: the build found no image-only scans (text_quality "
              "'no_text_layer' never fired). broken_text_layer: broken font maps the build could not decode (OCR could recover them).")
    write_manifest(pack, b); return b
def from_manifest(pack):
    p = f"{MUN}/{pack}/MANIFEST.json"
    return json.load(open(p, encoding="utf-8")).get("excluded_image_only_pdfs") if os.path.exists(p) else None
if __name__ == "__main__":
    out = dict(note="Image-only PDFs left out of the municipal packs because no OCR was run (not approved). Local list only; nothing uploaded.",
               built_utc=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), packs={})
    out["packs"]["greece_municipal"] = gr(); out["packs"]["luxembourg_municipal"] = lu()
    for p in ("ireland_municipal", "hungary_municipal"):
        b = from_manifest(p)
        if b: out["packs"][p] = b
    for p, b in out["packs"].items():
        b.setdefault("likely_regulation_count", b.get("likely_byelaw_count"))
    out["totals"] = dict(image_only=sum(b["count"] for b in out["packs"].values()),
                         likely_regulation=sum(b.get("likely_regulation_count") or 0 for b in out["packs"].values()),
                         broken_text_layer=sum(b["broken_text_layer"]["count"] for b in out["packs"].values()),
                         per_pack={p: dict(image_only=b["count"], likely_regulation=b.get("likely_regulation_count"), broken_text_layer=b["broken_text_layer"]["count"]) for p, b in out["packs"].items()})
    json.dump(out, open(f"{MUN}/ocr_candidates.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out["totals"], ensure_ascii=False))
