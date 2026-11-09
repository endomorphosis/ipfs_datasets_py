#!/usr/bin/env python3
"""Scope filter + pre-fetch dedupe of catalog.json for ZA provincial pack1.
In scope: ENACTED provincial Acts (listing label / filename says 'Act', no Bill / memo / notice / advert / presentation /
submission / schedule / isiZulu / Afrikaans / isiXhosa version). National Acts and anything the masthead does not confirm as an
Act of the Western Cape or KwaZulu-Natal legislature are dropped again post-fetch in stage. Dedupe vs the national repo
endomorphosis/ipfs_southafrica_laws (national/laws.parquet @ fdf0f845) on (core title, year) and (act_no, year) is applied in
stage on the masthead, and here on the listing label where an Act number + year are visible. Env ZA_WORK."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import json, os, re, unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import unquote
import pyarrow.parquet as pq
W = Path(os.environ.get("ZA_WORK", (str(_LEGAL_WS) + "/world_laws/za_prov")))
NAT = W / "national/laws.parquet"
def fold(s): return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
def year(s):
    y = re.findall(r"(?<!\d)(19[5-9]\d|20[0-3]\d)(?!\d)", s or ""); return int(y[-1]) if y else None
def actno(s):
    m = re.search(r"(?i)\bact\b[^0-9]{0,12}?(?:no\.?\s*)?(\d{1,3})\s*(?:of|[-/])\s*((?:19|20)\d\d)", fold(unquote(s or "")))
    return (int(m.group(1)), int(m.group(2))) if m else None
STOP = r"\b(western cape|wc|kwazulu natal|kzn|kwazulu|provincial|province|of|the|and|to|act|no|final|english|version|signed|gazette|pdf)\b"
def core(s):
    f = re.sub(r"[_\-%\[\]]+", " ", fold(unquote(s or ""))); f = re.sub(r"\.pdf$", "", f)
    f = re.sub(r"(?<!\d)(19|20)\d\d(?!\d)", " ", f); f = re.sub(r"\(.*?\)", " ", f); f = re.sub(STOP, " ", f)
    f = re.sub(r"[^a-z ]+", " ", f); return " ".join(x for x in f.split() if len(x) > 1)
NONACT = re.compile(r"\bbills?\b|memo|notice|advert|presentation|submission|schedule of|process of|hearing|booklet|report|"
                    r"isizulu|zulu|afrikaans|isixhosa|xhosa|procedure manual|guide|\bb\d{1,2}[a-d]?\s*-\s*20\d\d\b|\bb\s?\d{1,2}[a-d]?-?20\d\d|draft|\bprop\b", re.I)
NATIONAL = re.compile(r"(?i)division of revenue|public service|public administration|national|older persons|electricity regulation|"
                      r"basic education|public procurement|marine oil|demarcation|upstream petroleum|climate change|small enterprise")
def nat_keys():
    keys, nos = {}, {}
    for r in pq.read_table(NAT, columns=["id", "title"]).to_pylist():
        keys[(core(r["title"]), year(r["title"]))] = r["id"]
        a = actno(r["title"])
        if a: nos[a] = r["id"]
    return keys, nos
def main():
    keys, nos = nat_keys(); todo, exc, seen = [], [], {}
    for it in json.load(open(W / "catalog.json")):
        lab = it.get("title") or ""; fn = it["filename"]; both = f"{lab} {fn}"
        r = None
        if not re.search(r"(?i)\bact\b|\bwet\b|\bconstitution\b", fold(unquote(both))) and not re.search(r"(?i)act[-_ ]?\d", fn): r = "out_of_scope_not_act"
        elif NONACT.search(fold(unquote(both))): r = "out_of_scope_bill_memo_notice_or_other"
        elif NATIONAL.search(both) and not re.search(r"(?i)western cape|kwazulu|kzn|\bwc\b", both): r = "out_of_scope_national_act"
        else:
            a = actno(both); y = year(both); k = core(lab)
            if a and a in nos and NATIONAL.search(both): r = "dup_national_actno_year"
            elif (k, y) in keys: r = "dup_national_title_year"
            elif (it["src"], k, y) in seen: r = "dup_in_catalog"
        if r:
            exc.append({"ident": it["ident"], "url": it["url"], "filename": fn, "listing_title": lab, "reason": r}); continue
        seen[(it["src"], core(lab), year(both))] = it["ident"]; todo.append(it["ident"])
    json.dump(todo, open(W / "todo.json", "w"), indent=0)
    with open(W / "listing_exclusions.jsonl", "w") as fh:
        for e in exc: fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    print("todo", len(todo), dict(Counter(i.split("-")[0] for i in todo)), dict(Counter(e["reason"] for e in exc)), "national_keys", len(keys))
if __name__ == "__main__": main()
