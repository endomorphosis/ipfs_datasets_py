#!/usr/bin/env python3
"""Build a batch-2 pack = pinned Hub rows (kept, never removed) + new rows, cast onto the Hub schema.
usage: merge_b2.py CC [--b1]      --b1: also bring in clean rows from the frozen (held) batch-1 pack
New-row sources: africa_me_b2/incr/<cc> (batch 2 CC increment) and optionally the batch-1 pack (read-only).
Lane repairs on Hub rows (ONLY rows whose id starts with '<cc>-cc-', i.e. this lane's batch-1 rows):
  titles (TOC/dotted-leader/first-line fragments -> document heading or file name), language misdetections,
  article splitting where the law has 0 article records and splits cleanly (exact partition).
Output: ready_africa_me_batch2_20261016/<cc>/{data/laws.parquet,data/articles.parquet,MANIFEST.json,README.md,provenance/changes.json}
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
_LS_HELPERS = Path(__file__).resolve().parents[4] / "legal_scrapers"
if _LS_HELPERS.is_dir():
    _sys.path.insert(0, str(_LS_HELPERS))
import sys, os, re, json, hashlib, time
from pathlib import Path
from urllib.parse import urlparse, unquote
import pyarrow as pa, pyarrow.parquet as pq
import build_pack as bp, check_gates as cg
from hubio import hub_file, hub_repo, pin
import quality_filters_b2 as qf  # tightened after the Verifier audit (news/press/reports/forms/bills/whole gazettes)
B2 = Path((str(_COLLECTORS) + "/africa_me_b2"))
OUT = Path((str(_COLLECTORS) + "/ready_africa_me_batch2_20261016"))
B1 = Path((str(_COLLECTORS) + "/ready_africa_me_cc_packs_20261010"))
HR = re.compile(r"civilservice\.govmu\.org|circular|/(hr|human-resources?)/|\bcircular note\b", re.I)
NEWS_TITLE = re.compile(r"news agency|breaking news|\| the gambia news|press release|communiqu[ée]", re.I)
DOTS = re.compile(r"(\.\s?){4,}|…{2,}|_{4,}|\s\d{1,3}\s*$")
TOC = re.compile(r"(?i)table of contents|arrangement of (sections|regulations|clauses)|sommaire|table des mati[eè]res|[ií]ndice|contents\b")
FRAG = re.compile(r"^\s*(\d+[.)]|\d+\s+[a-zà-ÿ]|\(|[a-zà-ÿ])")
HEAD = re.compile(r"(?i)^\s*(the\s+)?([A-Z][\w'’-]+\s+){0,10}(act|law|decree|regulations?|order|ordinance|proclamation|constitution|bill|code|rules|notice)\b|^\s*(loi|d[ée]cret|decree|royal order|arr[êe]t[ée]|ordonnance|code|lei|decreto|ley|resolu|portaria|act\s+no|act\s+\d)|^\s*(قانون|مرسوم|قرار|نظام|دستور|لائحة)")

NUM = r"[^\n]{0,60}?(\b(19|20)\d\d\b|\bno\.?\s?[A-Z]/\s?\d|م\s?/\s?\d|n\s?[°ºo]\.?\s?\d|n[úu]m(ero|\.)?\s?\d|\bno\.?\s?\d|\b\d{1,4}\s?/\s?(19|20)?\d{2}\b|\bof\s+(19|20)\d\d|\bde\s+(19|20)\d\d|\bdu\s+\d|رقم|\(\d{1,4}\))"
INSTR = re.compile(r"(?i)(^|\n)\s*(the\s+)?([\w'’(),-]+\s+){0,3}?(ley|decreto(-lei|-ley)?|lei|resolu[cç][aã]o|portaria|despacho|aviso|nap|loi( organique)?|d[ée]cret|decree|royal order|arr[êe]t[ée]|ordonnance|act|regulations?|order|ordinance|notice|proclamation|statutory instrument|rules|bill|code|c[oó]digo|constitution|constitui[cç][aã]o|قانون|مرسوم|قرار|نظام|لائحة|أمر)\b" + NUM)
INFO = re.compile(r"(?i)\bdraft\b|guidance|guideline|statistics|billdownload|/documents/bills?/|motion without notice|standing orders?|sec\.gov\.ng/documents|/images/.*(moves|inaugurat|advice)|memo|prospectus|rights[ _-]issue|pricing[ _-]supplement|public[ _-]inquir|/drafts|draft regulation|consultation|report of the|advices|order ?paper|projet de loi|proyecto de ley|projeto de lei|draft bill|lois-promulguees|faqs?\b|miembros|who we are|sobre-nosotros|relat[oó]rio|recenseamento|em n[úu]meros|nota[s]? (de )?imprensa|notas-de-prensa|press release|caderno|educa[cç][aã]o financeira|direcci[oó]n general|/directores/|estrat[ée]gia|annual report|newsletter|/ministerio/")
SITE_SUFFIX = re.compile(r"\s+[–|-]\s+(Ministerio|Minist[eè]re|Ministry|Presid|Gouvernement|Governo|Gobierno|Portal|Site|Official)[^\n]*$")
def strong_law(l, nart):
    t = l["title"] or ""; tx = l["text"] or ""; u = l["source_url"] or ""
    if re.search(r"(?i)\bbill\b|مشروع", t): return False
    if INFO.search(t) or INFO.search(u) or re.match(r"^\s*([)\]]|\S+\))", t) or t.count("(") != t.count(")") or bad_title(t): return False
    meta = json.loads(l.get("metadata_json") or "{}"); mime = ((meta.get("cc") or {}).get("mime") or "")
    html = "pdf" not in mime and "pdf" not in u.lower()
    if nart == 0 and (t.rstrip().endswith((").", ".", ".”", ")")) or not INSTR.match(t)): return False
    if html and nart == 0 and (len(tx) < 3000 or len(INSTR.findall(tx)) > 5): return False
    return bool(INSTR.search(t)) or (nart >= 3 and bool(INSTR.search(tx[:1500])))
def sha(s): return hashlib.sha256(s.encode() if isinstance(s, str) else s).hexdigest()
def bad_title(t):
    t = (t or "").strip()
    if re.match(r"(?i)^act\s+\d+\s+of\s+\d{4}\s*[–-]", t) or t[:1] in "“\"‘'": return True
    return (not t) or bool(DOTS.search(t) or TOC.search(t) or FRAG.match(t)) or len(t) < 8 or len(t) > 220
def fname_title(url):
    b = unquote(os.path.basename(urlparse(url or "").path)); b = re.sub(r"\.(pdf|html?|aspx?|php|docx?)$", "", b, flags=re.I)
    b = re.sub(r"[_+\-]+", " ", b).strip()
    return b if sum(c.isalpha() for c in b) >= 6 else None
PREAMB = re.compile(r"(?i)^\s*(vu|considérant|considerant|having|whereas|sur (le )?rapport|après avis|apres avis|en application|conformément|conformement)\b")
NONLAW = re.compile(r"(?i)\b(examen|épreuve|epreuve|exam(ination)? paper|coeff?\.?\s*:?\s*\d|dur[ée]e\s*:\s*\d|annual report|rapport annuel|management (and monitoring )?plan|plan d.action|curriculum|newsletter|tender|appel d.offres|vacancy|avis de recrutement|appendix \\d|annex \\d|request for proposals?|rfp|annual perfo\\w* report|youth policy|complaints procedure)\b")
CITED = re.compile(r"(?i)(may be cited as|shall be cited as|may be referred to as)\s+(?:the\s+)?[\"“']?([^.;]{5,200}?(?:act|order|regulations|rules|notice|decree|proclamation|law)(?:,?\s*(?:no\.?\s*\d+\s*of\s*)?\d{4})?)\b")
def is_heading(l):
    L = [c for c in l if c.isalpha()]
    if not L: return False
    if sum(c.isupper() for c in L) / len(L) >= 0.6: return True
    if l.endswith((".", ",", ";", ":")) or not l[0].isupper(): return False
    w = l.split(); cap = sum(1 for x in w if x[:1].isupper() or x[:1].isdigit() or x.lower() in {"of","the","and","de","du","des","la","le","no.","n°","to","on","for","et","da","do","em"})
    return len(w) <= 22 and cap / len(w) >= 0.8
def better_title(text, url, old):
    if not bad_title(old): return old
    m = CITED.search((text or "")[:200000])
    if m:
        t = re.sub(r"\s+", " ", m.group(2)).strip(" ,;:.\"'“”")
        if 8 <= len(t) <= 200 and not DOTS.search(t): return t
    lines = [l.strip() for l in (text or "").split("\n")[:120]]
    ok = lambda l: 12 <= len(l) <= 220 and is_heading(l) and HEAD.search(l) and not bad_title(l) and not PREAMB.match(l) and sum(c.isalpha() for c in l) > 6
    order = [i for i, l in enumerate(lines) if ok(l) and bp.STRONG.search(l)] + [i for i, l in enumerate(lines) if ok(l) and len(l) >= 15 and not bp.STRONG.search(l) and re.match(r"(?i)\s*(the\s+)?(constitution|code|loi|lei|ley|d[ée]cret|decreto|act|law|regulations?|ordonnance|قانون|مرسوم|نظام)\b", l)]
    for i in order[:1]:
        l = lines[i]
        # join a short continuation line (e.g. 'LOI N° 2019-01' + 'portant ...')
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if len(l) < 40 and nxt and not bad_title(nxt) and re.match(r"(?i)(portant|relative?|du|de|to|on|for|concernant|que|sobre|relativ)", nxt):
            l = (l + " " + nxt)[:220]
        return l
    for l in lines:
        if 10 <= len(l) <= 200 and INSTR.search(l) and not PREAMB.match(l) and not DOTS.search(l) and not FRAG.match(l): return l
    return fname_title(url) or re.sub(r"(\s?\.){4,}.*$", "", old or "").strip() or old
LANG_SETS = {"fr": {"le","la","les","des","et","du","au","aux","est","une","pour","dans","par","sont","article"},
             "en": {"the","of","and","to","in","shall","for","be","is","that","by","section"},
             "pt": {"da","do","dos","das","para","os","uma","pelo","pela","em","não","artigo","são"},
             "es": {"el","los","las","del","para","por","una","con","se","artículo","año"}}
def detect(text, default):
    s = (text or "")[:20000]; L = [c for c in s if c.isalpha()]
    if L and sum(1 for c in L if "\u0600" <= c <= "\u06ff") / len(L) > 0.4: return "ar"
    w = re.findall(r"\b[a-zà-ÿãõçíúé]+\b", s.lower()); sc = {k: sum(1 for x in w if x in v) for k, v in LANG_SETS.items()}
    b = max(sc, key=sc.get); srt = sorted(sc.values())
    if sc[b] >= 20 and sc[b] >= 2 * srt[-2]: return b
    if default in sc and sc[b] >= 5 and sc[b] >= 3 * max(sc[default], 1) and sc[b] >= 2 * srt[-2]: return b  # short text, clear misdetection
    return default

def cast(rows, schema):
    cols = {f.name: [r.get(f.name) for r in rows] for f in schema}
    arrs = []
    for f in schema:
        v = cols[f.name]
        if pa.types.is_null(f.type): v = [None] * len(rows)
        elif pa.types.is_integer(f.type): v = [None if x is None else int(x) for x in v]
        elif pa.types.is_string(f.type) or pa.types.is_large_string(f.type): v = [None if x is None else str(x) for x in v]
        arrs.append(pa.array(v, type=f.type))
    return pa.Table.from_arrays(arrs, schema=schema)

def main(code, use_b1=False):
    code = code.upper(); lc = code.lower(); t0 = time.time()
    HL = pq.read_table(hub_file(code, "data/laws.parquet")); HA = pq.read_table(hub_file(code, "data/articles.parquet"))
    hub_laws = HL.to_pylist(); hub_arts = HA.to_pylist()
    ch = {"hub_repo": hub_repo(code), "hub_commit": pin(code), "hub_laws": len(hub_laws), "hub_articles": len(hub_arts),
          "new_laws": [], "dropped_candidates": [], "title_fixes": [], "lang_fixes": [], "split_added": [], "flag_for_review": [],
          "dropped_columns": {}, "nulled_values": {}}
    default_lang = bp.C.get(code, (None, "en"))[1] if code in bp.C else "en"
    known_url = {bp.norm_url(l["source_url"]) for l in hub_laws if l.get("source_url")}
    known_txt = {sha(l["text"] or "") for l in hub_laws}; known_id = {l["id"] for l in hub_laws}
    # ---- repairs on this lane's own Hub rows
    art_by = {}
    for a in hub_arts: art_by.setdefault(a["law_id"], []).append(a)
    extra_arts = []
    for l in hub_laws:
        if not str(l["id"]).startswith(f"{lc}-cc-"): continue
        nt = better_title(l["text"], l["source_url"], l["title"])
        if nt != l["title"]: ch["title_fixes"].append({"id": l["id"], "old": l["title"], "new": nt}); l["title"] = nt
        if NONLAW.search((l["title"] or "") + " " + (l["text"] or "")[:400]): ch["flag_for_review"].append({"id": l["id"], "why": "looks_non_law (exam/report/plan/tender)", "title": (l["title"] or "")[:120], "url": l["source_url"]})
        nl = detect(l["text"], l["language"])
        if nl != l["language"]: ch["lang_fixes"].append({"id": l["id"], "old": l["language"], "new": nl}); l["language"] = nl
        if not art_by.get(l["id"]) and (l["text"] or ""):
            segs = cg.split_exact(l["text"])
            if len(segs) >= 2:
                for j, (num, pos, body) in enumerate(segs):
                    extra_arts.append({"law_id": l["id"], "id": f"{l['id']}-art-{j+1}", "title": l["text"][pos:pos+400].split("\n")[0][:200], "text": body,
                        "source_url": l["source_url"], "document_number": l["identifier"], "article_number": num, "record_type": "article",
                        "metadata_json": json.dumps({"partition": "exact", "added_by": "africa_me_b2 split repair"})})
                l["article_count"] = len(segs); ch["split_added"].append({"id": l["id"], "articles": len(segs)})
    # ---- new rows
    cands = []
    for src in ([B1 / lc] if use_b1 else []) + [B2 / "incr" / lc, B2 / "incr2" / lc]:
        f = src / "data" / "laws.parquet"
        if f.exists(): cands += [(str(src), r) for r in pq.read_table(f).to_pylist()]
    new_laws, new_arts, seen = [], [], set()
    for src, l in cands:
        why = cg.is_court_or_news(l) + qf.reject(l)
        if HR.search(l["source_url"] or "") or HR.search((l["title"] or "")[:200]): why.append("hr_circular")
        if NONLAW.search((l["title"] or "") + " " + (l["text"] or "")[:400]): why.append("non_law_doc")
        if NEWS_TITLE.search(l["title"] or "") or NEWS_TITLE.search((l["text"] or "")[:300]): why.append("news_title")
        k = bp.norm_url(l["source_url"]); h = sha(l["text"] or "")
        if l["id"] in known_id or k in known_url or h in known_txt or l["id"] in seen or h in seen: why.append("already_in_hub_or_dupe")
        if why: ch["dropped_candidates"].append({"id": l["id"], "src": src, "why": why, "title": (l["title"] or "")[:120], "url": l["source_url"]}); continue
        seen.add(l["id"]); seen.add(h)
        l["title"] = better_title(l["text"], l["source_url"], l["title"]); l["language"] = detect(l["text"], l["language"] or default_lang)
        hubc = {r["country"] for r in hub_laws[:50] if r.get("country")}
        if len(hubc) == 1: l["country"] = hubc.pop()
        if re.match(r"(?i)^\s*(issued by\s+)?royal decree no", l["title"] or ""):
            GEN = re.compile(r"(?i)^(official translation|kingdom of|bureau of experts|capital market authority|translation of|republic|r[ée]publique|government of|ministry|saudi arabian monetary|in the name of|بسم)")
            fl = next((x.strip() for x in [y for y in (l["text"] or "").split("\n") if y.strip()][:12] if not GEN.match(x.strip()) and not re.match(r"(?i)\s*(issued by|royal decree|\d|note)", x.strip()) and len(x.strip()) >= 6), "")
            if 6 <= len(fl) <= 150 and not bad_title(fl) and not re.match(r"(?i)(issued by|royal decree)", fl): l["title"] = fl
        mc = CITED.search(l["title"] or "")
        if mc: l["title"] = re.sub(r"\s+", " ", mc.group(2)).strip(" ,;:.\"'“”")
        l["title"] = SITE_SUFFIX.sub("", l["title"] or "").strip() or l["title"]
        l["title"] = re.sub(r"\s*\.{2,}\s*[A-Z]?\d+(-[A-Z]?\d+)?\s*$", "", re.sub(r"^\d{1,3}\s+(?=[A-Z])", "", l["title"])).strip() or l["title"]
        segs = cg.split_exact(l["text"])
        tkey = re.sub(r"\W+", " ", (l["title"] or "").lower()).strip()
        if qf.reject(l) or qf.title_problem(l["title"]):
            ch["dropped_candidates"].append({"id": l["id"], "src": src, "why": qf.reject(l) or qf.title_problem(l["title"]), "title": (l["title"] or "")[:120], "url": l["source_url"]}); continue
        if not strong_law(l, len(segs)):
            ch["dropped_candidates"].append({"id": l["id"], "src": src, "why": ["weak_not_a_law_instrument"], "title": (l["title"] or "")[:120], "url": l["source_url"]}); continue
        if tkey in seen and len(tkey) > 25:
            ch["dropped_candidates"].append({"id": l["id"], "src": src, "why": ["same_title_dupe"], "title": (l["title"] or "")[:120], "url": l["source_url"]}); continue
        seen.add(tkey); l["article_count"] = len(segs)
        for j, (num, pos, body) in enumerate(segs):
            new_arts.append({"law_id": l["id"], "id": f"{l['id']}-art-{j+1}", "title": l["text"][pos:pos+400].split("\n")[0][:200], "text": body,
                "source_url": l["source_url"], "document_number": l["identifier"], "article_number": num, "record_type": "article",
                "metadata_json": json.dumps({"text_extraction": json.loads(l["metadata_json"] or "{}").get("text_extraction"), "partition": "exact"})})
        new_laws.append(l); ch["new_laws"].append({"id": l["id"], "src": src, "title": l["title"][:160], "url": l["source_url"], "articles": len(segs)})
    # ---- schema accounting
    for f in HL.schema:
        if pa.types.is_null(f.type):
            vals = [{"id": l["id"], "value": l.get(f.name)} for l in new_laws if l.get(f.name) not in (None, "")]
            if vals: ch["nulled_values"][f.name] = len(vals); ch.setdefault("dropped_values", {})[f.name] = vals
    for c in (set(bp.LAW_COLS) - set(HL.schema.names)):
        ch["dropped_columns"][c] = sum(1 for l in new_laws if l.get(c) not in (None, ""))
    laws_all = hub_laws + new_laws; arts_all = hub_arts + extra_arts + new_arts
    if not new_laws and not ch["title_fixes"] and not ch["lang_fixes"] and not ch["split_added"]:
        ch["result"] = "NO_CHANGE"; (B2 / "nochange").mkdir(exist_ok=True)
        json.dump(ch, open(B2 / "nochange" / f"{lc}.json", "w"), indent=1, ensure_ascii=False); import shutil; shutil.rmtree(OUT / lc, ignore_errors=True); print(code, "NO_CHANGE", flush=True); return ch
    d = OUT / lc; tmp = OUT / f".{lc}_tmp"; import shutil; shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "data").mkdir(parents=True); (tmp / "provenance").mkdir()
    pq.write_table(cast(laws_all, HL.schema), tmp / "data" / "laws.parquet", compression="zstd")
    pq.write_table(cast(arts_all, HA.schema), tmp / "data" / "articles.parquet", compression="zstd")
    # gates on what was written (re-read to be sure)
    L2 = pq.read_table(tmp / "data" / "laws.parquet").to_pylist(); A2 = pq.read_table(tmp / "data" / "articles.parquet").to_pylist()
    g = gates(code, L2, A2, {l["id"] for l in new_laws} | {x["id"] for x in ch["split_added"]} | {x["id"] for x in ch["title_fixes"]})
    ch["gates"] = g
    json.dump(ch, open(tmp / "provenance" / "changes.json", "w"), indent=1, ensure_ascii=False)
    man = {"pack": f"{lc}-africa-me-batch2-20261016", "kind": "MERGED full repo (Hub rows kept + new rows appended; lane-row repairs)",
           "hub_repo": ch["hub_repo"], "hub_commit": ch["hub_commit"], "hub_rows": {"laws": len(hub_laws), "articles": len(hub_arts)},
           "rows": {"laws": len(L2), "articles": len(A2)}, "new": {"laws": len(new_laws), "articles": len(new_arts) + len(extra_arts)},
           "repairs": {"titles": len(ch["title_fixes"]), "language": len(ch["lang_fixes"]), "split_laws": len(ch["split_added"])},
           "schema": "Hub schema of the pinned commit (pack rows cast onto it)", "method": "Common Crawl S3 cluster.idx -> CDXJ -> ranged WARC (no live requests)",
           "upload_owner": "Chief of Staff (not uploaded)", "gates": {k: v["pass"] for k, v in g.items()}, "files": {}}
    for f in sorted(tmp.rglob("*")):
        if f.is_file(): man["files"][str(f.relative_to(tmp))] = {"bytes": f.stat().st_size, "sha256": cg.sha256(f)}
    json.dump(man, open(tmp / "MANIFEST.json", "w"), indent=1, ensure_ascii=False)
    (tmp / "README.md").write_text(f"# {code} batch 2 pack (Africa & Middle East lane)\n\nMerged on top of `{ch['hub_repo']}`@{ch['hub_commit'][:12]}: "
        f"Hub {len(hub_laws)}/{len(hub_arts)} -> {len(L2)}/{len(A2)} laws/articles. New laws {len(new_laws)}. Repairs: {man['repairs']}.\n"
        "Hub rows are kept (only this lane's own `-cc-` rows may get title/language/article-split repairs). See provenance/changes.json.\n")
    shutil.rmtree(d, ignore_errors=True); shutil.move(str(tmp), str(d))
    print(code, "PACK", len(L2), len(A2), "new", len(new_laws), man["repairs"], man["gates"], round(time.time() - t0), "s", flush=True)
    return ch

def gates(code, laws, arts, touched):
    lid = [l["id"] for l in laws]; aid = [a["id"] for a in arts]
    hub_n = HUBN.get(code, (0, 0))
    by = {}
    for a in arts: by.setdefault(a["law_id"], []).append(a)
    T = [l for l in laws if l["id"] in touched]
    def mism(ls): return [l["id"] for l in ls if (l["article_count"] or 0) != len(by.get(l["id"], []))]
    def nonc(ls): return [l["id"] for l in ls if by.get(l["id"]) and "".join(a["text"] or "" for a in by[l["id"]]) != (l["text"] or "")]
    bad = {l["id"]: cg.is_court_or_news(l) for l in T}; bad = {k: v for k, v in bad.items() if v}
    from collections import Counter
    ca = Counter(aid); cl = Counter(lid)
    new_aid = [a["id"] for a in arts if a["law_id"] in touched]
    dup_touched = sum(1 for x in new_aid if ca[x] > 1) + sum(1 for l in T if cl[l["id"]] > 1)
    pre = sum(v - 1 for v in ca.values() if v > 1)
    return {"G1_dup_ids": {"laws": len(lid) - len(set(lid)), "articles_total_dupes": pre, "dupes_involving_new_or_repaired_rows": dup_touched,
                           "pass": dup_touched == 0 and len(lid) == len(set(lid)), "note": "articles_total_dupes are pre-existing Hub article ids carried unchanged" if pre else ""},
            "G2_court_news_new_or_repaired": {"flagged": bad, "pass": not bad},
            "G3_article_count_new_or_repaired": {"mismatch": mism(T), "pass": not mism(T), "preexisting_hub_mismatch": len(mism([l for l in laws if l["id"] not in touched]))},
            "G4_concat_new_or_repaired": {"non_concat": nonc(T), "pass": not nonc(T), "preexisting_hub_nonconcat": len(nonc([l for l in laws if l["id"] not in touched]))},
            "G5_never_thin": {"hub": hub_n, "pack": [len(laws), len(arts)], "pass": len(laws) >= hub_n[0] and len(arts) >= hub_n[1]}}
HUBN = {r[0]: (r[2] or 0, r[3] or 0) for r in json.load(open(B2 / "hub_snapshot_20261016.json"))}
if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    for c in a: main(c, "--b1" in sys.argv)
