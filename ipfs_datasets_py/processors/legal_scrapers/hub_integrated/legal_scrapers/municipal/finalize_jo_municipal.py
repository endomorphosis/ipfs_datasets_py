#!/usr/bin/env python3
"""Finalize the JO municipal supplement: scrapers/, report.json, MANIFEST.json, README.md, then HANDOFF_READY LAST
(only when the pack has rows), then remove $JO_STATE/RUNNING. Appends a PT line to PROGRESS.md."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, re, sys, json, glob, shutil, hashlib, datetime, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jo_common as C

ST = C.STATE
OUT = os.environ.get("JO_OUT", str(_CORPORA) + "/municipal/jordan_municipal")
PROGRESS = os.environ.get("JO_PROGRESS", os.path.join(os.path.dirname(ST), "PROGRESS.md"))
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = ["jo_common.py", "collect_jo_terms.py", "collect_jo_gazette.py", "collect_jo_lists.py", "build_jo_municipal.py",
           "finalize_jo_municipal.py"]
HUB = {"raw": "endomorphosis/ipfs_jordan_municipal_laws@1a7f5872 (62 laws / 1,205 articles: GAM 46, MoLA national 16)",
       "ir": "justicedao/ipfs_jordan_municipal_laws_ir@810caf12",
       "national": "endomorphosis/ipfs_jordan_laws@bd8dd9fb (1,229 lob.gov.jo rows)"}
SKIPPED = [
    ("lob.gov.jo (Legislation & Opinion Bureau)", "national corpus already on the Hub (endomorphosis/ipfs_jordan_laws); not municipal"),
    ("Muqtafi (Birzeit, muqtafi.birzeit.edu)", "excluded by instruction (host resets TLS / not an official publisher); no archive copies read"),
    ("ASEZA, Petra (PDTRA), Dead Sea and development-zone authority instruments", "special zone / development authorities, not municipalities; classified 'zone' and not collected (decision pending)"),
    ("Official Gazette 'الشؤون البلدية' section", "planning / zoning / expropriation notices, not laws"),
    ("Gazette issues below the DocuWare era (<= ~4500)", "issue pages return 'Page not found'"),
    ("www.amman.jo", "legacy GAM host; not used (media.ammancity.gov.jo serves the same list)"),
]


def sha(fn):
    h = hashlib.sha256()
    with open(fn, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def pt_now():
    return subprocess.run(["date", "+%F %H:%M"], capture_output=True, text=True, env={**os.environ, "TZ": "America/Los_Angeles"}).stdout.strip()


def sanitize(src):
    s = open(src).read()
    s = s.replace(str(_CORPORA) + "/municipal/jo_build_state", "./jo_build_state")
    s = s.replace(str(_CORPORA) + "/municipal/jordan_municipal", "./jordan_municipal")
    s = s.replace('sys.path.insert(0, "' + "/work" + 'space/legal_scrapers")\n', "")
    s = s.replace("/workspace/ipfs_datasets_fresh_venv/bin/python", "python3")
    return s


def main():
    rep = json.load(open(os.path.join(ST, "build_report.json")))
    img = json.load(open(os.path.join(ST, "image_only_pdfs.json")))
    terms = json.load(open(os.path.join(ST, "terms.json")))
    robots = json.load(open(os.path.join(ST, "robots_status.json")))
    lists = json.load(open(os.path.join(ST, "lists", "listing.json")))
    sd = os.path.join(OUT, "scrapers"); os.makedirs(sd, exist_ok=True)
    for s in SCRIPTS:
        open(os.path.join(sd, s), "w").write(sanitize(os.path.join(HERE, s)))
    open(os.path.join(sd, "schema.py"), "w").write(open(os.path.join(HERE, os.pardir, "schema.py")).read())
    open(os.path.join(sd, "collect_jo_municipal.py"), "w").write(
        '#!/usr/bin/env python3\n"""Entry point: terms -> gazette (index, scope, fetch) -> GAM/MoLA lists -> build -> finalize.\n'
        'Set JO_STATE (state dir) and JO_OUT (pack dir). Polite: >= 2 s per request, robots.txt honoured, never verify=False."""\n'
        'import os, subprocess, sys\nH = os.path.dirname(os.path.abspath(__file__))\n'
        'for args in (["collect_jo_terms.py"], ["collect_jo_gazette.py", "all"], ["collect_jo_lists.py"], ["build_jo_municipal.py"]):\n'
        '    rc = subprocess.call([sys.executable, os.path.join(H, args[0])] + args[1:])\n'
        '    if rc:\n        sys.exit(rc)\n')
    bad = [f for f in glob.glob(os.path.join(sd, "*.py")) if re.search(r"/work" + "space/", open(f).read()) and not f.endswith("schema.py")]
    secrets = [f for f in glob.glob(os.path.join(sd, "*.py")) if re.search(r"hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|api[_-]?key\s*=\s*['\"][^'\"]{8}", open(f).read())]
    assert not secrets, secrets
    data = sorted(glob.glob(os.path.join(OUT, "data", "*.parquet")))
    n_laws, n_arts = rep["laws_rows"], rep["articles_rows"]
    report = {**{k: v for k, v in rep.items() if k != "dropped"}, "dropped_count": len(rep["dropped"]), "dropped": rep["dropped"],
              "image_only_or_garbled": img["count"], "image_only_by_reason": {},
              "lists": {"items": len(lists["items"]), "counts": lists["counts"]}, "hub": HUB, "absolute_path_leftovers": bad}
    for x in img["items"]:
        k = x["reason"].split(" (")[0]
        report["image_only_by_reason"][k] = report["image_only_by_reason"].get(k, 0) + 1
    json.dump(report, open(os.path.join(OUT, "report.json"), "w"), ensure_ascii=False, indent=1)
    shutil.copy(os.path.join(ST, "image_only_pdfs.json"), os.path.join(OUT, "image_only_pdfs.json"))
    files = data + [os.path.join(OUT, "report.json"), os.path.join(OUT, "image_only_pdfs.json")] + sorted(glob.glob(os.path.join(sd, "*.py")))
    manifest = {"slug": "jordan", "country_iso": "JO", "collector": "scrapers/collect_jo_municipal.py", "built_utc": C.now_utc(),
                "mode": "add-only supplement to " + HUB["raw"], "laws_rows": n_laws, "articles_rows": n_arts,
                "municipalities": rep["municipalities"], "by_level": rep["by_level"], "languages": rep["languages"],
                "sha256": {os.path.relpath(f, OUT): sha(f) for f in files},
                "sources": [{"name": "Official Gazette (الجريدة الرسمية), Prime Ministry", "list": "https://www.pm.gov.jo/Ar/Pages/NewsPaperDetails/<issue>",
                             "documents": "https://doc.pm.gov.jo/DWWebClient/Integration.aspx (publisher's DocuWare links, download mode)",
                             "robots": {h: robots[h]["note"] for h in ("https://www.pm.gov.jo", "https://doc.pm.gov.jo")},
                             "terms_urls": [t["url"] for t in terms["pm.gov.jo"]]},
                            {"name": "Greater Amman Municipality legislation list", "list": "https://media.ammancity.gov.jo/AR/List/التشريعات",
                             "robots": robots["https://media.ammancity.gov.jo"]["note"], "terms_urls": [t["url"] for t in terms["media.ammancity.gov.jo"]],
                             "rows_contributed": 0, "note": "all in-scope items already on the Hub"},
                            {"name": "Ministry of Local Administration regulations / instructions lists", "list": "https://www.mola.gov.jo/Ar/List/الانظمة",
                             "robots": robots["https://www.mola.gov.jo"]["note"], "terms_urls": [t["url"] for t in terms["www.mola.gov.jo"]],
                             "rows_contributed": 0, "note": "all in-scope items already on the Hub"}],
                "known_gaps": {"image_only_or_garbled_pdfs": img["count"], "ocr": "not done (no-OCR rule); see image_only_pdfs.json"}}
    json.dump(manifest, open(os.path.join(OUT, "MANIFEST.json"), "w"), ensure_ascii=False, indent=1)
    T = lambda h: "\n\n".join(f"**{t['url']}** (retrieved {t['retrieved_at']}):\n\n```\n{t['text']}\n```" for t in terms[h] if t.get("status") == 200)
    sc = rep["scope"]
    readme = f"""# Jordan municipal laws: Official Gazette supplement (raw)

Add-only supplement for `endomorphosis/ipfs_jordan_municipal_laws`. Built {manifest['built_utc']} by `scrapers/collect_jo_municipal.py`.
Rows: **{n_laws} laws, {n_arts} article rows**. Schema: `MUNICIPAL_LAWS_SCHEMA` (world-laws-municipal/v1). Ids: `jo-mun-<municipality_code>-og<issue>-d<docuware id>`.

## Hub check (read-only, before building)
- Existing raw repo: {HUB['raw']}. Existing IR: {HUB['ir']}. National corpus: {HUB['national']}.
- This pack must be **added** to the existing repo, never replace it. Rows whose type/number/year matches an existing Hub row, or whose
  text is ≥ 0.90 contained (8-word shingles) in one, were dropped. Rows ≥ 0.90 contained in a national Hub text are kept and flagged
  (`extras.also_in_national_hub`).
- The GAM and MoLA lists were re-listed: {lists['counts']}. Nothing new and in scope (all in-scope items are on the Hub; the remaining items are
  central-government rules such as government procurement or the MoLA administrative organisation, which are out of scope).

## Sources
1. **Official Gazette (الجريدة الرسمية)**, Prime Ministry. Issue pages `https://www.pm.gov.jo/Ar/Pages/NewsPaperDetails/<n>`, issues
   {rep['issues_indexed']} indexed (the DocuWare era, about 2008 to issue 6083 of 22 Oct 2026). {rep['gazette_items']} instrument items classified: {sc}.
   Documents were fetched through the publisher's own DocuWare link (`doc.pm.gov.jo`, download mode).
2. GAM `media.ammancity.gov.jo/AR/List/التشريعات` and MoLA `www.mola.gov.jo` lists: checked only, 0 rows contributed.

Scope: أنظمة (regulations) and تعليمات (instructions) of Greater Amman Municipality, named municipalities, and general local-government
rules (municipalities, local and governorate councils, building and town planning), which are coded `jurisdiction_level=national`,
`municipality_code=national`. Excluded: laws (قانون), the issue index, the 'الشؤون البلدية' notice section (zoning, planning and
expropriation notices), decisions, announcements, corrections and drafts, central-government rules, and special zone / development authorities.

## Text quality (no OCR)
Gazette PDFs are DocuWare outputs. Older items are TIFF scans, and many newer PDFs embed CID fonts whose text layer does not decode to
Arabic. Every page is scored by the share of Arabic tokens found in a vocabulary built from the national Hub corpus. A document
is kept only if ≥ 90% of word-bearing pages score ≥ 0.70 and the word-weighted score is ≥ 0.75. Everything else
({img['count']} documents: {report['image_only_by_reason']}) is listed in `image_only_pdfs.json` for a later OCR pass and is not in the pack.
Kept rows were also checked as follows: cover-only or no-article text was dropped; text whose first article is not 1 was dropped as truncated; compilations
are flagged (`extras.compilation`, {rep['compilations']} rows); language is set by script ({rep['languages']}). Article rows exactly cover the text from the first
article (preamble kept as `record_type=preamble`), with char spans in `metadata_json`.

## Licence / terms
Official legislative texts. Jordanian Copyright Law No. 22 of 1992 (art. 7) excludes laws, regulations and official documents from protection. The
publisher's site terms claim ownership of site content, allow download and printing for personal or internal non-commercial use, and forbid
overloading the site. The full terms text is in every row's `license` column and is quoted in full below. Fetching was ≤ 1 request per 2 s with
backoff, no TLS bypass, and an identifying User-Agent.

### robots.txt
{chr(10).join(f'- {h}: {v["note"]}' for h, v in robots.items())}

### pm.gov.jo terms (full)
{T('pm.gov.jo')}

### media.ammancity.gov.jo terms (full)
{T('media.ammancity.gov.jo')}

### www.mola.gov.jo terms (full)
{T('www.mola.gov.jo')}

## Coverage and known gaps
- Municipality codes covered: {rep['municipalities']}; by level {rep['by_level']}.
- {img['count']} in-scope gazette documents are scans or have garbled text layers (needs OCR, see `image_only_pdfs.json`).
- Skipped sources:
{chr(10).join(f'  - {a}: {b}' for a, b in SKIPPED)}
"""
    open(os.path.join(OUT, "README.md"), "w").write(readme)
    msg = (f"JO municipal build finished: {n_laws} laws / {n_arts} articles (Official Gazette supplement, add-only vs Hub 1a7f5872); "
           f"{img['count']} image-only/garbled PDFs listed in jo_build_state/image_only_pdfs.json; disk free {C.disk_bytes()} B.")
    if n_laws > 0 and data:
        open(os.path.join(OUT, "HANDOFF_READY"), "w").close()
        msg += " HANDOFF_READY written."
    else:
        open(os.path.join(ST, "NEEDS_DECISION"), "w").write("Pack has 0 clean-text rows; no HANDOFF_READY. OCR pass needed for image_only_pdfs.json.\n")
        msg += " 0 clean rows -> NO HANDOFF_READY; jo_build_state/NEEDS_DECISION written (OCR decision)."
    if os.path.exists(os.path.join(ST, "RUNNING")):
        os.remove(os.path.join(ST, "RUNNING"))
    open(PROGRESS, "a").write(f"{pt_now()} PT: {msg}\n")
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
