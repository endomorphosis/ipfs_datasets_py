#!/usr/bin/env python3
"""CoS readiness gates for ready_africa_me_cc_packs_20261010/<cc>/ packs.

usage: check_gates.py [--fix] [--report OUT.json] [CC ...]      (no CC = all packs)
Gates (per pack):
  G1 no duplicate law ids / article ids
  G2 no court rulings / news pages (URL + title + html-boilerplate heuristics)
  G3 laws.article_count == number of article records for that law
  G4 where a law is split, its article records concatenate exactly to the full law text
  G5 never-thin: pack laws >= Hub laws AND pack articles >= Hub articles for endomorphosis/ipfs_*_laws of that CC
     (Hub read-only via datasets-server size API; falls back to world_coverage_audit.json)
--fix (G1-G4 only): dedupe ids, drop court/news rows, re-split articles as an exact partition of the law text
  (preamble merged into article 1, no truncation), set article_count, refresh MANIFEST.json. G5 is never auto-fixed.
Memory-light: one pack at a time.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
_COLLECTORS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors")))
import sys as _sys
_sys.path.insert(0, _ipfs_os.path.dirname(_ipfs_os.path.abspath(__file__)))
import sys, os, re, json, hashlib, argparse, time
from pathlib import Path
import requests, pyarrow as pa, pyarrow.parquet as pq
sys.path.insert(0, str(_COLLECTORS)); import build_pack as bp

ROOT = Path((str(_COLLECTORS) + "/ready_africa_me_cc_packs_20261010"))
AUDIT = json.load(open((str(_COLLECTORS) + "/world_coverage_audit.json")))
HUBMAP = {r["iso"]: r for r in AUDIT["country_table"]}
for iso, ds in [(d["iso"], d["datasets"]) for d in AUDIT.get("duplicate_country_datasets", [])]:
    HUBMAP.setdefault(iso, {})["dupes"] = ds

COURT_URL = re.compile(r"/(judg[e]?ments?|jurisprudence|case-?law|cases?|decisions?|arrets?|rulings?|tribunal|court-?decisions?|law-?reports?)(/|[-_.]|$)|%d8%a7%d9%84%d8%a7%d8%ad%d9%83%d8%a7%d9%85|الأحكام|القضايا", re.I)
COURT_TITLE = re.compile(r"^\s*(?:in the (?:matter|high court|supreme court)|in re\b|judg(?:e)?ment\b|ruling\b|arr[êe]t\b|jugement\b|الحكم\b|حكم\b|الطعن|قرار المحكمة|حكم المحكمة|القضية)|\b[A-Z][\w.'-]+ v\.? [A-Z][\w.'-]+|\bcourt of appeal\b|\bhigh court of\b", re.I)
NEWS_URL = re.compile(r"/(news|press|actualit[eé]s?|blog|media-?cent(?:er|re)|stor(?:y|ies)|events?|communiqu[eé]s?|nouvelles|noticias|notícias|أخبار|اخبار)(/|[-_.]|$)", re.I)
NEWS_BOILER = re.compile(r"(Posted on|Share this|Read more|Tweet\b|Subscribe to|Lire la suite|Publi[ée] le|Partager|Compartir|اقرأ المزيد|شارك الخبر|تابعنا)", re.I)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def hub_counts(cc):
    """Existing Hub repos for CC (read-only). Returns {'repos':[{id,laws,articles}], 'max_laws','max_articles','source'}"""
    row = HUBMAP.get(cc, {})
    ids = [row["hub_id"]] if row.get("hub_id") else []
    ids += row.get("dupes", [])
    ids = list(dict.fromkeys(ids))
    out = []
    for rid in ids:
        rec = None
        try:
            r = requests.get("https://datasets-server.huggingface.co/size", params={"dataset": rid}, timeout=30)
            if r.status_code == 200:
                js = r.json().get("size", r.json()); cf = {c["config"]: c["num_rows"] for c in js.get("configs", [])}
                if "laws" in cf:
                    rec = {"id": rid, "laws": cf.get("laws"), "articles": cf.get("articles", 0), "source": "datasets-server"}
        except Exception:
            pass
        if rec is None and rid == row.get("hub_id"):
            rec = {"id": rid, "laws": row.get("laws"), "articles": row.get("articles"), "source": "world_coverage_audit.json"}
        if rec: out.append(rec)
    return {"repos": out, "max_laws": max([r["laws"] or 0 for r in out], default=0),
            "max_articles": max([r["articles"] or 0 for r in out], default=0)}


def is_court_or_news(law):
    url, title, text = law["source_url"] or "", law["title"] or "", law["text"] or ""
    meta = json.loads(law["metadata_json"] or "{}")
    mime = (meta.get("cc") or {}).get("mime") or ""
    reasons = []
    if COURT_URL.search(url): reasons.append("court_url")
    if COURT_TITLE.search(title): reasons.append("court_title")
    if NEWS_URL.search(url): reasons.append("news_url")
    if "html" in mime and "pdf" not in mime and len(NEWS_BOILER.findall(text[:2500])) >= 2: reasons.append("news_boilerplate")
    return reasons


def split_exact(text):
    """Exact partition of text into article segments; preamble merged into article 1. [] if not splittable."""
    cands = []
    for rx in (bp.ART_LATIN, bp.ART_AR):
        cands = [(m.start(), m.group(1).strip()) for m in rx.finditer(text)]
        if len(cands) >= 2: break
    if len(cands) < 2:
        chain, exp = [], 1
        for m in bp.ART_NUM.finditer(text):
            n = int(m.group(1))
            if n == exp: chain.append((m.start(), str(n))); exp += 1
        cands = chain if len(chain) >= 5 else []
    if len(cands) < 2: return []
    cands = cands[:5000]
    keep = []
    for i, (pos, num) in enumerate(cands):  # drop markers that would give a <15-char segment
        end = cands[i + 1][0] if i + 1 < len(cands) else len(text)
        if len(text[pos:end].strip()) >= 15: keep.append((pos, num))
    if len(keep) < 2: return []
    segs = []
    for i, (pos, num) in enumerate(keep):
        start = 0 if i == 0 else pos
        end = keep[i + 1][0] if i + 1 < len(keep) else len(text)
        segs.append((num, pos, text[start:end]))
    assert "".join(s[2] for s in segs) == text
    return segs


def fix_pack(cc, laws, arts):
    rep = {"dropped_court_news": 0, "dedup_laws": 0, "dedup_articles": 0}
    seen, keep = set(), []
    for l in laws:
        if l["id"] in seen: rep["dedup_laws"] += 1; continue
        seen.add(l["id"])
        if is_court_or_news(l): rep["dropped_court_news"] += 1; continue
        keep.append(l)
    new_arts = []
    for l in keep:
        segs = split_exact(l["text"])
        l["article_count"] = len(segs)
        for j, (num, pos, body) in enumerate(segs):
            title = l["text"][pos:pos + 400].split("\n")[0][:200]
            new_arts.append({"law_id": l["id"], "id": f"{l['id']}-art-{j+1}", "title": title, "text": body, "source_url": l["source_url"],
                             "document_number": l["identifier"], "article_number": num, "record_type": "article",
                             "metadata_json": json.dumps({"text_extraction": json.loads(l["metadata_json"]).get("text_extraction"), "partition": "exact"})})
    return keep, new_arts, rep


def check(cc, laws, arts):
    g = {}
    lid = [l["id"] for l in laws]; aid = [a["id"] for a in arts]
    g["G1_duplicate_ids"] = {"laws": len(lid) - len(set(lid)), "articles": len(aid) - len(set(aid)),
                             "pass": len(lid) == len(set(lid)) and len(aid) == len(set(aid))}
    bad = {}
    for l in laws:
        r = is_court_or_news(l)
        if r: bad[l["id"]] = r
    g["G2_court_or_news"] = {"flagged": len(bad), "examples": [{"id": k, "why": v, "url": next(l["source_url"] for l in laws if l["id"] == k)} for k, v in list(bad.items())[:5]], "pass": not bad}
    by = {}
    for a in arts: by.setdefault(a["law_id"], []).append(a)
    mism = [l["id"] for l in laws if (l["article_count"] or 0) != len(by.get(l["id"], []))]
    g["G3_article_count_eq_records"] = {"mismatches": len(mism), "pass": not mism}
    nonconcat = []
    for l in laws:
        recs = by.get(l["id"])
        if recs and "".join(r["text"] for r in recs) != l["text"]: nonconcat.append(l["id"])
    g["G4_concat_equals_text"] = {"split_laws": len(by), "non_concat": len(nonconcat), "pass": not nonconcat}
    orphan = [a["id"] for a in arts if a["law_id"] not in set(lid)] if len(arts) < 200000 else []
    g["G4b_orphan_articles"] = {"orphans": len(orphan), "pass": not orphan}
    hub = hub_counts(cc)
    thin = [r for r in hub["repos"] if len(laws) < (r["laws"] or 0) or len(arts) < (r["articles"] or 0)]
    g["G5_never_thin"] = {"pack_laws": len(laws), "pack_articles": len(arts), "hub": hub["repos"],
                          "pass": not thin, "note": "pack is a Common Crawl INCREMENT; needs merge with Hub rows to satisfy" if thin else "ok"}
    return g


def write_pack(d, laws, arts, extra):
    LAW, ART = bp.LAW_COLS, bp.ART_COLS
    lt = pa.Table.from_pylist(laws, schema=pa.schema([(c, pa.int64() if c == "article_count" else pa.large_string()) for c in LAW]))
    at = pa.Table.from_pylist(arts, schema=pa.schema([(c, pa.large_string()) for c in ART]))
    pq.write_table(lt, d / "data" / "laws.parquet", compression="zstd")
    pq.write_table(at, d / "data" / "articles.parquet", compression="zstd")
    m = json.load(open(d / "MANIFEST.json"))
    m["rows"] = {"laws": len(laws), "articles": len(arts)}
    m["gates_fix"] = {"applied_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **extra}
    for rel in list(m["files"]):
        p = d / rel
        if p.exists(): m["files"][rel] = {"bytes": p.stat().st_size, "sha256": sha256(p)}
    json.dump(m, open(d / "MANIFEST.json", "w"), indent=1, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--fix", action="store_true"); ap.add_argument("--report")
    ap.add_argument("ccs", nargs="*"); a = ap.parse_args()
    ccs = [c.lower() for c in a.ccs] or sorted(p.name for p in ROOT.iterdir() if p.is_dir())
    report = {}
    for cc in ccs:
        d = ROOT / cc
        if not (d / "MANIFEST.json").exists() or not (d / "data" / "laws.parquet").exists():
            report[cc.upper()] = {"status": "FAIL", "reason": "no manifest or no laws.parquet"}; continue
        laws = pq.read_table(d / "data" / "laws.parquet").to_pylist()
        arts = pq.read_table(d / "data" / "articles.parquet").to_pylist()
        before = check(cc.upper(), laws, arts)
        fixinfo = None
        if a.fix and not all(before[k]["pass"] for k in before if k.startswith(("G1", "G2", "G3", "G4"))):
            laws, arts, fixinfo = fix_pack(cc, laws, arts)
            write_pack(d, laws, arts, fixinfo)
        res = check(cc.upper(), laws, arts)
        hard = all(res[k]["pass"] for k in res if k.startswith(("G1", "G2", "G3", "G4"))) and len(laws) > 0
        status = "PASS" if hard and res["G5_never_thin"]["pass"] else ("FAIL_NEVER_THIN" if hard else "FAIL")
        report[cc.upper()] = {"status": status, "laws": len(laws), "articles": len(arts), "gates": res,
                              "fixed": fixinfo, "before_fix_failed": [k for k in before if not before[k]["pass"]] if fixinfo else []}
        print(cc.upper(), status, len(laws), len(arts), flush=True)
    if a.report:
        json.dump(report, open(a.report, "w"), indent=1, ensure_ascii=False)
    return report


if __name__ == "__main__":
    main()
