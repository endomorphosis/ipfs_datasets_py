#!/usr/bin/env python3
"""Latvia (LV): local article split of hub laws.text (NO network).

- Hub text is a likumi.lv page dump: chrome ... 'Kādēļ autorizēties vai reģistrēties?' | BODY | 'Tiesību akta pase'
  (passport, optional 'Satura rādītājs' ToC, related docs, footer). Body = between those markers.
- Modes (per law): 'N. pants' (pants) if any depth-0 pants heading; else 'Article N' (art); else top-level
  numbered points 'N.' / inserted 'N.M ' (pt, strict sequence 1,2,3.. ; sub-points N.M. stay in parent).
  'Pielikums' / 'N. pielikums' annexes -> separate units (piel); 'Pārejas noteikumi' and
  'Informatīva atsauce uz ES ...' -> separate units (sec). Chapters (nodaļa / roman 'I. ...') -> context.
- Quote-aware: „ opens, ” “ close; straight " toggles on odd count; sequence resync as in HR/SK.
- IDs: <law_id>-<kind>-<num-slug>-<ordinal>, kind in {pants, pt, art, piel, sec}; hub ids use
  -article-/-paragraph-/-N so no collisions (verified at run time).
- 25128 existing hub article rows written first, verbatim (duplicates kept); their 923 laws not re-split.
- Streams laws in batches of 100; parquet written incrementally; TERM self at MemAvailable <= 3.5 GiB.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, re, signal, sys, threading, time, collections
from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq

SNAP = Path(os.environ.get("LV_SNAP", "/workspace/country-laws-ir/cache/hf/datasets--endomorphosis--ipfs_latvia_laws/snapshots/d3b4679db9d0cf50a2e5d7362d0750365588542f"))
WORK = _CORPORA / "lv" / "extract"
OUT = WORK / "articles_merged.parquet"
STATS = WORK / "split_stats.json"
TOCREP = WORK / "toc_check.json"
GAP = Path("/workspace/country-law-triage/latvia_gap_list.json")
MEM_STOP_KB = int(3.5 * 1024 * 1024)
BATCH = 100
COLS = ["law_id", "id", "title", "text", "source_url", "document_number", "article_number", "record_type", "metadata_json"]
SCHEMA = pa.schema([(c, pa.string()) for c in COLS])
STOP = False


def _sig(*_):
    global STOP
    STOP = True


signal.signal(signal.SIGTERM, _sig)


def mem_kb():
    for ln in open("/proc/meminfo"):
        if ln.startswith("MemAvailable:"):
            return int(ln.split()[1])
    return 0


MEM_MIN = [mem_kb()]


def watchdog():
    while not STOP:
        m = mem_kb(); MEM_MIN[0] = min(MEM_MIN[0], m)
        if m <= MEM_STOP_KB:
            print(f"MEM GUARD {m} kB <= 3.5G -> TERM self (no restart)", flush=True)
            os.kill(os.getpid(), signal.SIGTERM); return
        time.sleep(2)


START_MARK = "Kādēļ autorizēties vai reģistrēties?"
END_MARK = "Tiesību akta pase"
PANTS_RE = re.compile(r"^(\d+(?:\.\d+)?)\.?\s?pants(?:\.|\b)\s*(.*)$")
ART_RE = re.compile(r"^(?:Article|ARTICLE)\s+(\d+[a-z]?|[IVXLCDM]+)\.?$")
PT_RE = re.compile(r"^(\d{1,4})\.(?:\s+(\S.*)|([A-ZĀČĒĢĪĶĻŅŠŪŽ„“\"(].*))?$")
INS_RE = re.compile(r"^(\d{1,4})\.(\d{1,2})\s+(\S.*)$")
PIEL_RE = re.compile(r"^(?:(\d+)\.\s?)?(?:pielikums|PIELIKUMS|Pielikums)(?:\s+Nr\.\s?(\d+))?\.?(?:\s+(?:svītrots|\[XLSX\]|\[PDF\]|\[DOCX?\]))?$")
SEC_RE = re.compile(r"^(Pārejas noteikumi|PĀREJAS NOTEIKUMI|Paskaidrojuma raksts|Informatīva atsauce uz Eiropas Savienības direktīv\w*|Informatīvā atsauce uz Eiropas Savienības direktīv\w*)$")
CH_RE = re.compile(r"^(?:([IVXLCDM]+|\d+)\.?\s?(?:nodaļa|NODAĻA|sadaļa|SADAĻA|apakšnodaļa|daļa|DAĻA)\b.{0,150}|[IVXLCDM]+\.\s+[A-ZĀČĒĢĪĶĻŅŠŪŽ].{0,150})$")
DIGITS = re.compile(r"^\d{1,4}$")
TOC_PANTS = re.compile(r"^(\d+(?:\.\d+)?)\.?\s?pants\.?$")
TOC_PT = re.compile(r"^(\d+(?:\.\d+)?)\.?\s?punkts\.?$")
TOC_PIEL = re.compile(r"^(?:(\d+)\.\s?)?pielikums(?:[.\s]|$)", re.I)
ROM = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def rint(s):
    m = re.match(r"^(\d+)", s)
    if m:
        return int(m.group(1))
    t = 0
    for a, b in zip(s, s[1:] + " "):
        t += -ROM[a] if b != " " and ROM.get(b, 0) > ROM[a] else ROM[a]
    return t


def locate(text):
    L = [re.sub(r"[ \t\u00a0]+", " ", x).strip() for x in (text or "").replace("\r", "").split("\n")]
    L = [x for x in L if x]
    s = next((i for i, l in enumerate(L) if l == START_MARK), -1)
    e = next((i for i in range(len(L) - 1, -1, -1) if L[i] == END_MARK), -1)
    return L, s, e


def toc_list(L, e):
    a = next((i for i in range(max(e, 0), len(L)) if L[i] == "Satura rādītājs"), -1)
    if a < 0:
        return None
    b = next((i for i in range(a, len(L)) if L[i] == "Saistītie dokumenti"), len(L))
    out = []
    for l in L[a + 1:b]:
        m = TOC_PANTS.match(l)
        if m:
            out.append(("pants", m.group(1))); continue
        m = TOC_PT.match(l)
        if m:
            out.append(("pt", m.group(1))); continue
        m = TOC_PIEL.match(l)
        if m:
            out.append(("piel", m.group(1) or "")); continue
    return out


def qdelta(ln, sq):
    d = ln.count("„") - ln.count("”") - ln.count("“")
    if ln.count('"') % 2:
        sq = not sq
    return d, sq


def split_units(B):
    # mode detection (depth-0 pants lines)
    has_pants = has_art = False; depth = 0; sq = False
    for ln in B:
        at = depth + (1 if sq else 0)
        d, sq = qdelta(ln, sq); depth = max(0, depth + d)
        if at == 0 and PANTS_RE.match(ln):
            has_pants = True; break
        if at == 0 and ART_RE.match(ln):
            has_art = True
    mode = "pants" if has_pants else ("art" if has_art else "pt")
    ctx = {}; units = []; cur = None; depth = 0; sq = False; markers = []
    prev = 0; prev_ins = 0; prev_ln = ""; in_block = False  # in annex / sec block: no unit detection
    for ln in B:
        at = depth + (1 if sq else 0)
        d, sq = qdelta(ln, sq); depth = max(0, depth + d)
        quoted_ctx = prev_ln.endswith(":") or prev_ln.endswith("„") or prev_ln.endswith('"')
        new = None
        if at == 0 or not quoted_ctx:
            m = PIEL_RE.match(ln)
            if m and at == 0:
                new = ("piel", m.group(1) or m.group(2) or str(sum(1 for u in units if u["kind"] == "piel") + (1 if cur and cur["kind"] == "piel" else 0) + 1), ln)
            elif at == 0 and SEC_RE.match(ln):
                new = ("sec", "parejas" if ln.lower().startswith("pārejas") else ("paskaidrojuma-raksts" if ln.startswith("Paskaidrojuma") else "es-atsauce"), ln)
            elif not in_block:
                if mode == "pants":
                    m = PANTS_RE.match(ln)
                    if m:
                        ni = rint(m.group(1)); sub = "." in m.group(1)
                        ok = ni > prev or ni == 1 or (ni == prev and sub)
                        if (at == 0 and ok) or (at > 0 and ni == prev + 1 and not sub):
                            if ni == 1 and prev >= 1 and not sub:
                                ctx["sequence"] = ctx.get("sequence", 1) + 1  # numbering restarts (e.g. attached convention text)
                            new = ("pants", m.group(1), ln); prev = ni
                elif mode == "art":
                    m = ART_RE.match(ln)
                    if m:
                        ni = rint(m.group(1))
                        if (at == 0 and (ni > prev or ni == 1)) or (at > 0 and ni == prev + 1):
                            new = ("art", m.group(1), ln); prev = ni
                else:
                    m = PT_RE.match(ln)
                    if m and not CH_RE.match(ln):
                        ni = int(m.group(1))
                        if ni == prev + 1:
                            new = ("pt", m.group(1), ln); prev = ni; prev_ins = 0
                    else:
                        m = INS_RE.match(ln)
                        if m and int(m.group(1)) == prev and prev > 0 and int(m.group(2)) > prev_ins:
                            new = ("pt", f"{m.group(1)}.{m.group(2)}", ln); prev_ins = int(m.group(2))
        if new:
            kind, num, _ = new
            pre = []
            if cur and len(cur["lines"]) > 1:
                # likumi.lv block-index marker line ('3') + that unit's own amendment notes '(Grozīts ar ...)'
                k = next((j for j in range(len(cur["lines"]) - 1, 0, -1) if DIGITS.match(cur["lines"][j])), -1)
                tail = cur["lines"][k + 1:] if k > 0 else []
                if k > 0 and not tail:
                    del cur["lines"][k:]  # bare marker line
                elif tail and tail[0].startswith("(") and tail[-1].endswith(")") and sum(map(len, tail)) < 600:
                    pre = tail; del cur["lines"][k:]
            if cur:
                units.append(cur)
            cur = {"kind": kind, "num": num, "lines": [ln], "pre": pre, "ctx": dict(ctx), "heading": ""}
            if kind in ("pants", "art", "pt"):
                markers.append((kind, num))
            in_block = kind in ("piel",) or (kind == "sec" and (num == "paskaidrojuma-raksts" or (num == "parejas" and mode != "pt")))
            depth = 0; sq = False; prev_ln = ln; continue
        if at == 0 and not in_block and CH_RE.match(ln) and len(ln) < 160 and not ln.endswith(":") and not ln.endswith(";"):
            if cur and cur["lines"] and DIGITS.match(cur["lines"][-1]) and len(cur["lines"]) > 1:
                cur["lines"].pop()
            if cur:
                units.append(cur); cur = None
            ctx = {k: v for k, v in ctx.items() if k == "sequence"}; ctx["chapter"] = ln
            prev_ln = ln; continue
        if cur:
            if len(cur["lines"]) == 1 and cur["kind"] in ("pants", "art") and not cur["heading"]:
                m = PANTS_RE.match(cur["lines"][0])
                inline = m.group(2).strip() if (m and cur["kind"] == "pants") else ""
                if inline:
                    cur["heading"] = inline if len(inline) <= 160 and not inline.startswith("(") else ""
                elif len(ln) < 200 and not ln.startswith("(") and not ln.endswith(":") and not DIGITS.match(ln):
                    cur["heading"] = ln
            cur["lines"].append(ln)
        prev_ln = ln
    if cur:
        units.append(cur)
    for u in units:
        h = u["heading"]
        if h and u["kind"] == "pants" and not PANTS_RE.match(u["lines"][0]).group(2).strip():
            if len(u["lines"]) == 2 or (len(u["lines"]) > 2 and u["lines"][2][:1].islower()) or (h.endswith(".") and len(h) > 120):
                u["heading"] = ""
        if u["kind"] == "pants" and h and len(u["lines"]) >= 1 and PANTS_RE.match(u["lines"][0]).group(2).strip():
            pass
    units = [u for u in units if len(u["lines"]) >= 2 or len(u["lines"][0]) >= 15]
    return units, markers, mode


def slug(s):
    return re.sub(r"[^0-9a-z]+", "-", s.lower()).strip("-") or "x"


LABEL = {"pants": "{}. pants", "art": "Article {}", "pt": "{}. punkts", "piel": "{}. pielikums", "sec": "{}"}
SECT = {"parejas": "Pārejas noteikumi", "paskaidrojuma-raksts": "Paskaidrojuma raksts", "es-atsauce": "Informatīva atsauce uz Eiropas Savienības direktīvām"}


def process_law(r, hub_ids, st):
    lid = r["id"]; n = lid.split("-", 1)[1]
    L, s, e = locate(r["text"])
    base = {"law_id": lid, "title": (r["title"] or "")[:200], "source_url": r["source_url"]}
    if s < 0 or e < 0 or e <= s:
        return None, dict(base, reason="body_detect_fail", text_chars=len(r["text"] or "")), None, None
    B = L[s + 1:e]
    units, markers, mode = split_units(B)
    tl = toc_list(L, e)
    bchars = sum(len(x) for x in B)
    memo_only = bool(units) and all(u["kind"] == "sec" and u["num"] == "paskaidrojuma-raksts" for u in units)
    if memo_only:
        units = []  # only the explanatory memo is structured; the act itself is a single unnumbered text
    if not units:
        repealed = any(x.startswith("Tiesību akts ir zaudējis spēku") for x in B[:3])
        reason = "unstructured_short" if bchars < 1500 else "unstructured_long"
        return None, dict(base, reason=reason, repealed=repealed, memo_only=memo_only, body_chars=bchars), (tl, markers, units), mode
    rows = []
    docno = (r.get("official_identifier") or r.get("identifier") or f"likumi.lv {n}")
    for i, u in enumerate(units):
        rid = f"{lid}-{u['kind']}-{slug(u['num'])}-{i}"[:200]
        if rid in hub_ids:
            st["collide"] += 1
        label = SECT.get(u["num"], u["num"]) if u["kind"] == "sec" else LABEL[u["kind"]].format(u["num"])
        if u["kind"] == "piel" and not u["num"]:
            label = "Pielikums"
        title = f"{label} {u['heading']}" if u["heading"] and u["kind"] in ("pants", "art") else label
        rows.append({"law_id": lid, "id": rid, "title": title[:300], "text": "\n".join(u.get("pre", []) + u["lines"]),
                     "source_url": r["source_url"], "document_number": str(docno)[:200], "article_number": label,
                     "record_type": "article",
                     "metadata_json": json.dumps({"collector": "lv_split_hub_text", "source": "hub laws.text (likumi.lv snapshot)",
                                                  "unit": u["kind"], "mode": mode, "heading": u["heading"], "context": u["ctx"], "ordinal": i}, ensure_ascii=False)})
    return rows, None, (tl, markers, units), mode


def toc_eval(tl, markers, units):
    if tl is None:
        return "no_toc", None
    if any(x[0] == "pants" for x in tl):  # ToC 'punkts' entries of a law are transitional-provision points
        tu = [x[1] for x in tl if x[0] == "pants"]
    else:
        tu = [x[1] for x in tl if x[0] == "pt"]
    sp = [x[1] for x in markers if x[0] in ("pants", "pt")]  # compare numbers (some noteikumi label units 'pants')
    tp = sum(1 for x in tl if x[0] == "piel"); upc = sum(1 for u in units if u["kind"] == "piel")
    if not tu:
        return "toc_without_unit_entries", (tp, upc)
    if tu == sp and tp == upc:
        return "exact", None
    if tu == sp:
        return "units_exact_annex_diff", (tp, upc)
    if set(tu) <= set(sp):
        return "toc_subset_of_split", None  # every ToC unit found; split has extra (attached treaty text / ToC truncated)
    if set(tu) & set(sp):
        return "partial", None
    return "no_match", None


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=watchdog, daemon=True).start()
    hub = pq.read_table(SNAP / "data" / "articles.parquet")
    n_hub = hub.num_rows
    hub_laws = set(hub.column("law_id").to_pylist()); hub_ids = set(hub.column("id").to_pylist())
    tmp = OUT.with_suffix(".tmp")
    w = pq.ParquetWriter(tmp, SCHEMA, compression="zstd")
    w.write_table(hub.select(COLS).cast(SCHEMA)); del hub
    st = collections.Counter(); methods = collections.Counter(); kinds = collections.Counter()
    toc = collections.Counter(); toc_bad = []; gaps = []
    pf = pq.ParquetFile(SNAP / "data" / "laws.parquet")
    for rb in pf.iter_batches(batch_size=BATCH, columns=["id", "text", "source_url", "title", "official_identifier", "identifier"]):
        if STOP:
            break
        rows = rb.to_pylist(); del rb
        out = []
        for r in rows:
            st["laws"] += 1
            if r["id"] in hub_laws:
                st["hub_laws_skipped"] += 1; continue
            new, gap, tocdata, mode = process_law(r, hub_ids, st)
            if tocdata is not None:
                verdict, extra = toc_eval(*tocdata)
                toc[verdict] += 1
                if verdict not in ("exact", "no_toc") and len(toc_bad) < 3000:
                    tl, mk, _ = tocdata
                    tu = [f"{k}:{v}" for k, v in tl if k != "piel"]; sp = [f"{k}:{v}" for k, v in mk]
                    toc_bad.append({"law_id": r["id"], "verdict": verdict, "toc_n": len(tu), "split_n": len(sp), "annex": extra,
                                    "toc_only": [x for x in tu if x not in set(sp)][:12], "split_only": [x for x in sp if x not in set(tu)][:12]})
            if gap:
                gaps.append(gap); continue
            st["laws_split"] += 1
            methods["+".join(sorted({x["id"].split("-")[2] for x in new}))] += 1
            for x in new:
                kinds[x["id"].split("-")[2]] += 1
            out.extend(new)
        del rows
        if out:
            w.write_table(pa.Table.from_pylist(out, schema=SCHEMA)); st["new_articles"] += len(out)
        del out
        if st["laws"] % 5000 < BATCH:
            print(f"{st['laws']} laws, {st['new_articles']} new arts, mem {mem_kb()//1024} MB", flush=True)
    w.close()
    if STOP:
        tmp.unlink(missing_ok=True); print("STOPPED (TERM/mem guard); output discarded", flush=True); sys.exit(3)
    tmp.replace(OUT)
    gr = collections.Counter(g["reason"] for g in gaps)
    with_toc = sum(v for k, v in toc.items() if k != "no_toc")
    res = {"laws": st["laws"], "hub_laws_skipped": st["hub_laws_skipped"], "laws_split": st["laws_split"],
           "new_articles": st["new_articles"], "hub_articles": n_hub, "total_articles": n_hub + st["new_articles"],
           "laws_with_articles": st["laws_split"] + len(hub_laws), "methods": dict(methods), "unit_kinds": dict(kinds),
           "id_collisions_with_hub": st["collide"], "toc": dict(toc),
           "toc_exact_pct_of_laws_with_toc": round(100 * toc["exact"] / with_toc, 2) if with_toc else None,
           "toc_units_exact_pct": round(100 * (toc["exact"] + toc["units_exact_annex_diff"]) / with_toc, 2) if with_toc else None,
           "toc_all_found_pct": round(100 * (toc["exact"] + toc["units_exact_annex_diff"] + toc["toc_subset_of_split"]) / with_toc, 2) if with_toc else None,
           "gap_count": len(gaps), "gap_reasons": dict(gr), "mem_min_kB": MEM_MIN[0], "mem_end_kB": mem_kb()}
    STATS.write_text(json.dumps(res, indent=2, ensure_ascii=False))
    TOCREP.write_text(json.dumps({"summary": dict(toc), "bad": toc_bad}, ensure_ascii=False, indent=1))
    GAP.write_text(json.dumps({"country": "LV", "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "count": len(gaps),
                               "reasons": dict(gr),
                               "repealed_in_gap": sum(1 for g in gaps if g.get("repealed")),
                               "note": "Laws with no article rows after hub-existing + local split of hub laws.text. unstructured_* = body has no pants/Article/numbered-point/Pielikums units (e.g. single-paragraph rikojumi, lemumi, pazinojumi).",
                               "laws": gaps}, ensure_ascii=False, indent=1))
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
