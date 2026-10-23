#!/usr/bin/env python3
"""20-law hand-check sample + 20-law spot-check (independent recount vs raw source) for CH cantonal parse."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import gzip, json, random, re, sys, glob, subprocess
sys.path.insert(0, "/workspace/scripts")
from ch_cantonal_common import strip, law_id
P = "{_CORPORA}/ch_cantonal/parsed"; R = "{_CORPORA}/ch_cantonal/raw"
CS = "BE,LU,UR,OW,NW,GL,ZG,FR,SO,BS,BL,SH,AR,SG,GR,AG,TG,VS,AI,VD,GE,TI,ZH,JU".split(",")
def laws(c):
    for ln in gzip.open(f"{P}/{c}_laws.jsonl.gz", "rt"): yield json.loads(ln)
def arts_of(c, ids):
    out = {i: [] for i in ids}
    for ln in gzip.open(f"{P}/{c}_articles.jsonl.gz", "rt"):
        a = json.loads(ln)
        if a["law_id"] in out: out[a["law_id"]].append(a)
    return out
def independent_count(c, law):
    p = law["json_path"]
    if p.endswith(".json.gz") and c not in ("VD", "GE", "TI", "ZH", "JU"):
        d = json.load(gzip.open(p))["text_of_law"]; sv = d.get("selected_version") or {}
        doc = ((sv.get("json_content") or {}).get("document") or {}).get("content")
        if not doc:
            return None, "pdf_fallback"
        n = [0]
        def w(x):
            if x.get("type") == "article": n[0] += 1; return
            for ch in x.get("children") or []: w(ch)
        w(doc); return n[0], "json article nodes"
    d = json.load(gzip.open(p))
    if c == "VD": return len(re.findall(r'<div class="akn-article-container"', d["html"])), "akn-article-container"
    if c == "GE": return len(re.findall(r"<p\s+class=\"?article\"?", d["html"], re.I)), "<p class=article>"
    if c == "TI": return len(re.findall(r"font-weight:bold[^>]*>\s*Art\.", d["html"])), "bold 'Art.' spans (approx)"
    return None, "pdf (no independent marker)"
def main(seed_h=11, seed_s=23):
    allids = {c: [l["id"] for l in laws(c)] for c in CS}
    rh = random.Random(seed_h); rs = random.Random(seed_s)
    hand_c = rh.sample(CS, 20); spot_c = rs.sample(CS, 20)
    res = {"hand_check": [], "spot_check": []}
    for kind, cs, rnd in (("hand_check", hand_c, rh), ("spot_check", spot_c, rs)):
        for c in cs:
            lid = rnd.choice(allids[c]); law = next(l for l in laws(c) if l["id"] == lid); A = arts_of(c, [lid])[lid]
            labels = [a["article_number"] for a in A]
            rec = {"canton": c, "law_id": lid, "title": law["title"][:90], "source_url": law["source_url"], "n_articles": len(A),
                   "first_labels": labels[:4], "last_labels": labels[-3:], "ids_unique": len(set(a["id"] for a in A)) == len(A),
                   "empty_article_texts": sum(1 for a in A if not a["text"].strip()),
                   "labels_start_with_marker": all(re.match(r"(Art|§|Ziff|Ch|Chiffre)", l) for l in labels)}
            if kind == "hand_check":
                rec["first_article_excerpt"] = A[0]["text"][:220] if A else ""
            else:
                n, how = independent_count(c, law); rec["independent_count"] = n; rec["independent_method"] = how
                rec["count_match"] = (n == len(A)) if n is not None else None
                lt = re.sub(r"\s+", " ", law["text"])
                rec["article_texts_in_law_text"] = sum(1 for a in A if re.sub(r"\s+", " ", a["text"])[:80] in lt)
            res[kind].append(rec)
    json.dump(res, open("/workspace/country-law-triage/switzerland_cantonal_checks.json", "w"), indent=1, ensure_ascii=False)
    for k in res:
        print("==", k)
        for r in res[k]: print(json.dumps(r, ensure_ascii=False)[:600])
if __name__ == "__main__": main()
