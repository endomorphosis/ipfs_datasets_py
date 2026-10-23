"""Hong Kong e-Legislation current Cap. ordinances + subsidiary legislation from DoJ PSI open data
(data.gov.hk 'hk-doj-hkel-legislation-current'; zips on resource.data.one.gov.hk, robots 404 => allow).
No HTML crawl of www.elegislation.gov.hk (robots Disallow: / for *). One doc per Cap, English. place iso:HK."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, os, re, json, time, zipfile, hashlib
from xml.etree import ElementTree as ET
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national/us"))
from stage_util import write_part, utcstamp, check_space
C = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national/HK/_cache"); NS = "{http://www.xml.gov.hk/schemas/hklm/1.0}"
BLOCK = {"section","subsection","paragraph","subparagraph","part","division","subdivision","schedule","longTitle","enactingFormula",
         "heading","docTitle","def","leadIn","content","sourceNote","crossHeading","table","tr","p","note","text","num"}
def log(*a): print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)
def text_of(el):
    out = []
    def w(e):
        tag = e.tag.split("}")[-1]
        if tag == "meta": return
        blk = tag in BLOCK
        if blk and tag != "num": out.append("\n")
        if e.text: out.append(re.sub(r"\s+", " ", e.text))
        for c in e: w(c);  out.append(re.sub(r"\s+", " ", c.tail or ""))
        if blk and tag not in ("num",): out.append("\n")
        elif tag == "num": out.append(" ")
    w(el); t = "".join(out)
    t = re.sub(r"[ \t\r\f\v]+", " ", t); t = re.sub(r" *\n *", "\n", t); return re.sub(r"\n{2,}", "\n\n", t).strip()
def main():
    L = json.load(open(f"{C}/list_en.json")); upd = L["UpdatedDateTime"]; ts = utcstamp()
    zips = {}
    for c in L["Chapter"]:
        v = c["Version"][0]; zips.setdefault(v["DataResourceUrl"], []).append((c, v))
    part, buf, tot = 1, [], 0
    def flush():
        nonlocal part, buf, tot
        if buf: check_space(); p, n = write_part("HK", "iso:HK", f"hkelpsi{ts}p{part:04d}", buf, log); tot += n; part += 1; buf = []
    for zurl, items in zips.items():
        zp = f"{C}/{zurl.rsplit('/',1)[1]}"
        if not os.path.exists(zp): log("MISSING zip", zurl, len(items)); continue
        z = zipfile.ZipFile(zp); idx = {m.replace("\\", "/").split("/")[-1]: m for m in z.namelist()}
        for c, v in items:
            m = idx.get(v["FileName"])
            if not m: log("not in zip", c["CapNo"], v["FileName"]); continue
            raw = z.read(m); root = ET.fromstring(raw)
            meta = {e.tag.split("}")[-1]: (e.text or "").strip() for e in root.find(f"{NS}meta")} if root.find(f"{NS}meta") is not None else {}
            txt = text_of(root)
            if not txt: log("empty", c["CapNo"]); continue
            title = re.sub(r"\s+", " ", c.get("ChapterTitleEnglish") or "").strip()
            st = meta.get("docStatus") or v["VersionDate"].get("statusCategory")
            dt = {"O": "statute", "S": "regulation", "I": "statute"}.get(c["LegislationType"], "statute")
            buf.append({"place_id": "iso:HK", "country_code": "HK", "doc_id": f"hk_cap_{c['CapNo']}_en",
                "source_platform": "hk_elegislation", "source_url": v.get("Web") or f"https://www.elegislation.gov.hk/hk/cap{c['CapNo']}!en",
                "doc_type": dt, "language": "en", "title_native": title, "html_title": f"{c['CapNoDisplay']} {title}", "number": c["CapNoDisplay"],
                "text": txt, "effective_date": v["VersionDate"]["value"][:10], "in_force": {"InEffect": True, "NoLongerInEffect": False, "NotYetInEffect": False}.get(v["VersionDate"].get("statusCategory")),
                "consolidated": True, "content_format": "xml", "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "extra_metadata": {"legislation_type": c["LegislationType"], "principal_ordinance": c.get("PrincipalOrdinance"), "doc_status": st,
                    "status_category": v["VersionDate"].get("statusCategory"), "psi_zip": zurl, "psi_file": v["FileName"], "psi_list_updated": upd,
                    "xml_sha256": hashlib.sha256(raw).hexdigest(), "dc_identifier": meta.get("identifier")}})
            if len(buf) >= 300: flush()
        log("zip done", zurl)
    flush(); log("TOTAL staged", tot)
if __name__ == "__main__": main()
