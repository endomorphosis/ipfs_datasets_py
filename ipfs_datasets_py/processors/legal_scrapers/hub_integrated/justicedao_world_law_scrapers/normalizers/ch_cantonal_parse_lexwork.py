#!/usr/bin/env python3
"""Parse LexWork show_as_json raw files -> cantonal law + article rows (jsonl.gz per canton). Streams per file."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import gzip, json, sys, glob, os, time, re
sys.path.insert(0, "/workspace/scripts")
from ch_cantonal_common import *
BASE = "{_CORPORA}/ch_cantonal"
def parse_file(c, path):
    d = json.load(gzip.open(path)); tol = d["text_of_law"]; lang = lang_of(c)
    sv = tol.get("selected_version") or {}; doc = (sv.get("json_content") or {}).get("document") or {}
    g = lambda x: (x or {}).get(lang) or next(iter((x or {}).values()), "") if isinstance(x, dict) else (x or "")
    sn = tol["systematic_number"]; title = re.sub(r"\s+", " ", tol.get("title") or "").strip()
    arts = []; parts = [strip(g(doc.get("header")))]; path_titles = []
    def walk(n, trail):
        t = n.get("type"); h = g(n.get("html_content"))
        if t == "article":
            texts = []
            def coll(m):
                texts.append(strip(g(m.get("html_content"))))
                for ch in m.get("children") or []: coll(ch)
            coll(n); body = "\n".join(x for x in texts if x)
            label = strip(g(n.get("number"))).replace("*", "").strip()
            mh = re.search(r"class='article_title'>(.*?)</div>", h, re.S)
            heading = strip(mh.group(1)) if mh else ""
            arts.append((label, heading if heading not in ("…", "...") else "", body,
                         {"uid": n.get("uid"), "path": trail[-4:], "repealed": body.strip().endswith("…") and len(body) < 60}))
            parts.append(body); return
        if t == "title":
            tt = strip(h)
            if tt: parts.append(tt)
            trail = trail + [tt] if tt else trail
        elif h: parts.append(strip(h))
        for ch in n.get("children") or []: walk(ch, trail)
    if doc.get("content"): walk(doc["content"], [])
    parts.append(strip(g(doc.get("footer"))))
    pdf = path.replace(".json.gz", ".pdf"); from_pdf = False
    if not arts and os.path.exists(pdf):
        import ch_cantonal_parse_other as PO
        head, parr, full = PO.split_pdf_text(PO.pdftext(pdf)); arts = [a for a in parr if a[0]]; from_pdf = True
        parts = [full]
    url = tol.get("canonical_link") or ""; date = tol.get("date_of_decision") or ""
    meta = {"publisher": f"Canton {c} official systematic law collection (LexWork)", "abbreviation": tol.get("abbreviation") or "",
            "date_entry_in_force": tol.get("enactment") or "", "version_in_force_since": tol.get("publication_enactment") or "",
            "version_dates": sv.get("version_dates_str") or "", "pdf_link": sv.get("pdf_link_tol") or tol.get("pdf_link") or "",
            "text_of_law_type_id": tol.get("text_of_law_type_id"), "text_from_pdf": from_pdf, "version_uid": tol.get("version_uid"),
            "annex_titles": [strip(g(a.get("text"))) for a in ((doc.get("annex_documents") or {}).get("children") or [])] if isinstance(doc.get("annex_documents"), dict) else []}
    retrieved = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(path)))
    law = make_law(c, sn, title, "\n\n".join(p for p in parts if p), url, "cantonal_lexwork", date, retrieved, len(arts), path, meta)
    return law, make_articles(c, sn, url, date, arts, "pdf_text_article_v1" if from_pdf else "lexwork_json_article_v1"), [a[0] for a in arts]
if __name__ == "__main__":
    cs = sys.argv[1].split(",")
    os.makedirs(f"{BASE}/parsed", exist_ok=True)
    for c in cs:
        files = sorted(glob.glob(f"{BASE}/raw/{c}/*.json.gz")); nl = na = npass = 0; checks = {}
        with gzip.open(f"{BASE}/parsed/{c}_laws.jsonl.gz", "wt") as fl, gzip.open(f"{BASE}/parsed/{c}_articles.jsonl.gz", "wt") as fa:
            for p in files:
                try: law, arts, labels = parse_file(c, p)
                except Exception as e: checks[p] = {"error": repr(e)}; continue
                fl.write(json.dumps(law, ensure_ascii=False) + "\n"); nl += 1
                for a in arts: fa.write(json.dumps(a, ensure_ascii=False) + "\n")
                na += len(arts); ck = numbering_check(labels); checks[law["id"]] = ck; npass += bool(ck["pass"])
        json.dump(checks, open(f"{BASE}/parsed/{c}_numbering.json", "w"))
        print(c, "laws", nl, "articles", na, "numbering_pass", npass, flush=True)
