#!/usr/bin/env python3
"""Slovakia (SK): local article split of hub laws.text (NO network; slov-lex is WAF-blocked).

- Mojibake repaired on the fly (sk_textfix.fix_text) for splitting only; laws.parquet untouched.
- Body = from the act-number line followed by the type heading (ZÁKON, VYHLÁŠKA, ...) after the
  'Obsah' ToC, up to trailing footnotes ('1)' block) / 'Kontakt' footer. Header, version history,
  ToC and footer are excluded.
- Units (quote-aware on „…“ with sequence resync): '§ N' (par), 'Čl. N'/'Článok N' (cl),
  'Article N' (art), each 'Príloha' annex (pril).
- ID convention: <law_id>-<kind>-<num-slug>-<ordinal>, kind in {par, cl, art, pril}; ordinal = 0-based
  position within the law. Existing Hub ids use '<law_id>-article-<n>' so no collisions.
- 179 existing Hub article rows written first, verbatim (duplicates kept); their 23 laws not re-split.
- Streams laws in small batches; parquet written incrementally; TERM self at MemAvailable <= 3.5 GiB.
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
sys.path.insert(0, "/workspace/scripts")
from sk_textfix import fix_text

SNAP = Path(os.environ.get("SK_SNAP", "/workspace/country-laws-ir/cache/hf/datasets--endomorphosis--ipfs_slovakia_laws/snapshots/22508a5eab4b3c0ba98fe0ab32aa9fcb5ec4be9a"))
WORK = _CORPORA / "sk" / "extract"
OUT = WORK / "articles_merged.parquet"
STATS = WORK / "split_stats.json"
TOCREP = WORK / "toc_check.json"
GAP = Path("/workspace/country-law-triage/slovakia_gap_list.json")
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


# ------------------------------------------------------------------ parsing
PAR_RE = re.compile(r"^§\s?(\d+[a-z]{0,3})(?:\*{1,3}\)?)?(?:\s*[–-]\s*§\s?\d+[a-z]{0,3})?$")  # no trailing dot: "§ 12." is inline text
CL_RE = re.compile(r"^(?:Čl\.|Čl|Článok|ČLÁNOK|Čľ\.)\s*([IVXLCDM]+|\d+[a-z]?)\s?\.?$")
ART_RE = re.compile(r"^(?:Article|ARTICLE)\s+(\d+[a-z]?|[IVXLCDM]+)\.?$")
PRIL_RE = re.compile(r"^(?:Príloha|PRÍLOHA)(?:\s+(?:č\.|číslo)\s?(\d+[a-z]?))?(?:\s+(?:k|ku)\s+\S.{0,150})?\.?$")
STRUCT_RE = re.compile(r"^(?:[A-ZÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ]+\s+)?(?:ČASŤ|HLAVA|DIEL|ODDIEL)(?:\s+(?:[IVXLCDM]+|\d+)\.?)?$")
TOC_PAR = re.compile(r"^§\s?(\d+[a-z]{0,3})(?![a-z0-9])")
TOC_CL = re.compile(r"^(?:Čl\.|Článok|ČLÁNOK)\s*([IVXLCDM]+|\d+[a-z]?)(?![a-z0-9])")
FOOT_RE = re.compile(r"^\d+[a-z]{0,2}\)$")
ROM = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def rint(s):
    if s.isdigit():
        return int(s)
    m = re.match(r"^(\d+)", s)
    if m:
        return int(m.group(1))
    t = 0
    for a, b in zip(s, s[1:] + " "):
        t += -ROM[a] if b != " " and ROM.get(b, 0) > ROM[a] else ROM[a]
    return t


def locate(text: str, n: str):
    """Return (lines, body_start, body_end, toc_start, doc_type) or None-ish on failure."""
    L = [re.sub(r"[ \t]+", " ", x).strip() for x in fix_text(text).replace("\r", "").split("\n")]
    L = [x for x in L if x]
    ob = next((i for i, l in enumerate(L) if l == "Obsah"), -1)
    s = next((i for i in range(max(ob, 0), len(L) - 1) if L[i] == n and L[i + 1][:1].isupper()), -1)
    if s < 0:
        return L, -1, -1, ob, ""
    e = len(L)
    k = next((i for i in range(len(L) - 1, s, -1) if L[i] == "Kontakt"), -1)
    if k > s:
        e = k
    # trailing footnotes: last '1)' line after which every marker line is a footnote marker
    for i in range(e - 1, s, -1):
        if L[i] == "1)":
            # only a trailing footnote block: no unit marker may follow it
            if not any(PAR_RE.match(x) or CL_RE.match(x) or PRIL_RE.match(x) for x in L[i + 1:e]):
                e = i
            break
    dtype = L[s + 1].split()[0].upper().rstrip("0123456789)") if s + 1 < len(L) else ""
    return L, s + 1, e, ob, dtype


def toc_list(L, ob, s):
    out = []
    if ob < 0:
        return out
    for l in L[ob + 1:s]:
        m = TOC_PAR.match(l)
        if m:
            out.append(("par", m.group(1))); continue
        m = TOC_CL.match(l)
        if m:
            out.append(("cl", m.group(1)))
    return out


def split_units(B: list[str]):
    ctx = {}; units = []; cur = None; depth = 0; markers = []
    prev = {"par": 0, "cl": 0, "art": 0}
    prev_ln = ""
    in_annex = False
    for ln in B:
        at = depth
        depth = max(0, depth + ln.count("„") - ln.count("“") - ln.count("”") - ln.count('"'))  # closers: “ or straight "
        hit = None
        for kind, rx in (("par", PAR_RE), ("cl", CL_RE), ("art", ART_RE)):
            m = rx.match(ln)
            if m:
                hit = (kind, m.group(1)); break
        if hit:
            kind, num = hit
            ni = rint(num); suf = re.sub(r"^\d+", "", num) if num[:1].isdigit() else ""
            quoted_ctx = prev_ln.endswith(":") or prev_ln.endswith("„") or prev_ln == "„"
            resync = at > 0 and not suf and ni == prev[kind] + 1 and not quoted_ctx
            if kind == "cl" and at > 0 and not suf and prev[kind] < ni <= prev[kind] + 3:
                resync = True  # Čl. wrappers are never quoted without „ on the same line
            in_seq = kind != "par" or ni > prev[kind] or (ni == prev[kind] and suf) or ni == 1
            if (at == 0 and in_seq) or resync:
                markers.append((kind, num))
                if cur and cur["kind"] == "cl" and len(cur["lines"]) == 1:
                    ctx["cl"] = cur["lines"][0]; cur = None  # bare 'Čl. I' wrapper -> context only
                if cur:
                    units.append(cur)
                cur = {"kind": kind, "num": num, "lines": [ln], "ctx": dict(ctx), "heading": ""}
                prev[kind] = ni
                if kind == "cl":
                    prev["par"] = prev["par"]  # § numbering continues across Čl.
                if resync:
                    depth = 0
                prev_ln = ln; continue
        if at == 0 and not hit:
            m = PRIL_RE.match(ln)
            if m and not ln.endswith(":"):
                if cur:
                    units.append(cur)
                cur = {"kind": "pril", "num": m.group(1) or str(sum(1 for u in units if u["kind"] == "pril") + 1),
                       "lines": [ln], "ctx": dict(ctx), "heading": ""}
                in_annex = True
                prev_ln = ln; continue
            if STRUCT_RE.match(ln) and not in_annex and not (cur and len(cur["lines"]) == 1):
                ctx = {k: v for k, v in ctx.items() if k != "struct"}
                ctx["struct"] = ln
                if cur:
                    units.append(cur); cur = None
                prev_ln = ln; continue
        if cur:
            if len(cur["lines"]) == 1 and cur["kind"] in ("par", "cl", "art") and not cur["heading"] \
                    and len(ln) < 200 and not ln.startswith("(") and not ln.endswith(":") and not FOOT_RE.match(ln):
                cur["heading"] = ln
            cur["lines"].append(ln)
        elif ctx.get("struct") and len(ln) < 200 and "struct_title" not in ctx:
            ctx["struct_title"] = ln
        prev_ln = ln
    if cur:
        units.append(cur)
    for u in units:  # heading that continues into a lowercase line is body text, not a heading
        h = u["heading"]
        if h and ((len(u["lines"]) > 2 and u["lines"][2][:1].islower()) or len(u["lines"]) == 2
                  or (h.endswith(".") and len(h) > 30) or re.match(r"^(\(?\d+[a-z]?[.)]|[a-z]\))$", h)):
            u["heading"] = ""
    return [u for u in units if len(u["lines"]) >= 2 or len(u["lines"][0]) >= 15], markers


def slug(s):
    return re.sub(r"[^0-9a-z]+", "-", s.lower()).strip("-") or "x"


LABEL = {"par": "§ {}", "cl": "Čl. {}", "art": "Article {}", "pril": "Príloha č. {}"}


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=watchdog, daemon=True).start()
    hub = pq.read_table(SNAP / "data" / "articles.parquet")
    hub_laws = set(hub.column("law_id").to_pylist()); hub_ids = set(hub.column("id").to_pylist())
    tmp = OUT.with_suffix(".tmp")
    w = pq.ParquetWriter(tmp, SCHEMA, compression="zstd")
    w.write_table(hub.select(COLS).cast(SCHEMA)); del hub
    st = collections.Counter(); methods = collections.Counter(); kinds = collections.Counter()
    toc = collections.Counter(); toc_bad = []; gaps = []; collide = 0
    pf = pq.ParquetFile(SNAP / "data" / "laws.parquet")
    for rb in pf.iter_batches(batch_size=BATCH, columns=["id", "text", "source_url", "title"]):
        if STOP:
            break
        rows = rb.to_pylist(); del rb
        out = []
        for r in rows:
            lid = r["id"]; st["laws"] += 1
            if lid in hub_laws:
                st["hub_laws_skipped"] += 1; continue
            n = lid.split("-")[2]
            L, s, e, ob, dtype = locate(r["text"] or "", n)
            asp = r["source_url"].endswith("vyhlasene_znenie.html")
            base = {"law_id": lid, "title": (r["title"] or "")[:200], "source_url": r["source_url"], "doc_type": dtype}
            if s < 0:
                reason = "title_only" if ob < 0 and len(r["text"] or "") < 600 else "body_detect_fail"
                gaps.append(dict(base, reason=reason, as_published=asp, text_chars=len(r["text"] or ""))); continue
            B = L[s:e]
            units, markers = split_units(B)
            # ToC check
            tl = toc_list(L, ob, s - 1)
            sl = [m for m in markers if m[0] in ("par", "cl")]
            if not tl:
                toc["no_toc"] += 1
            elif tl == sl:
                toc["exact"] += 1
            elif set(tl) & set(sl):
                toc["partial"] += 1
                if len(toc_bad) < 3000:
                    toc_bad.append({"law_id": lid, "toc_n": len(tl), "split_n": len(sl),
                                    "toc_only": [f"{k}:{v}" for k, v in tl if (k, v) not in set(sl)][:15],
                                    "split_only": [f"{k}:{v}" for k, v in sl if (k, v) not in set(tl)][:15]})
            else:
                toc["no_match"] += 1
                if len(toc_bad) < 3000:
                    toc_bad.append({"law_id": lid, "toc_n": len(tl), "split_n": len(sl), "toc_head": tl[:5], "split_head": sl[:5]})
            if dtype == "NÁLEZ" and units:
                # Constitutional Court findings: §/Čl. lines are citations of the reviewed law, not structure
                units = []; base["subreason"] = "nalez_citation_markers"
            if not units:
                reason = "oznamenie_unsplit" if dtype == "OZNÁMENIE" else "other_unsplittable"
                gaps.append(dict(base, reason=reason, as_published=asp, body_chars=sum(len(x) for x in B))); continue
            st["laws_split"] += 1
            ks = sorted({u["kind"] for u in units}); methods["+".join(ks)] += 1
            for i, u in enumerate(units):
                kinds[u["kind"]] += 1
                rid = f"{lid}-{u['kind']}-{slug(u['num'])}-{i}"[:200]
                if rid in hub_ids:
                    collide += 1
                title = LABEL[u["kind"]].format(u["num"])
                if u["heading"] and u["kind"] != "pril":
                    title = f"{title} {u['heading']}"
                out.append({"law_id": lid, "id": rid, "title": title[:300], "text": "\n".join(u["lines"]),
                            "source_url": r["source_url"], "document_number": f"{n}/{lid.split('-')[1]} Z. z.",
                            "article_number": title.split(" ")[0] + " " + u["num"] if u["kind"] != "art" else f"Article {u['num']}",
                            "record_type": "article",
                            "metadata_json": json.dumps({"collector": "sk_split_hub_text", "source": "hub laws.text (static.slov-lex.sk snapshot 2026-09-02), mojibake repaired on the fly",
                                                         "unit": u["kind"], "heading": u["heading"], "context": u["ctx"], "ordinal": i, "doc_type": dtype}, ensure_ascii=False)})
        del rows
        if out:
            w.write_table(pa.Table.from_pylist(out, schema=SCHEMA)); st["new_articles"] += len(out)
        del out
    w.close()
    if STOP:
        tmp.unlink(missing_ok=True); print("STOPPED (TERM/mem guard); output discarded", flush=True); sys.exit(3)
    tmp.replace(OUT)
    gr = collections.Counter(g["reason"] for g in gaps)
    res = {"laws": st["laws"], "hub_laws_skipped": st["hub_laws_skipped"], "laws_split": st["laws_split"],
           "new_articles": st["new_articles"], "hub_articles": 179, "total_articles": 179 + st["new_articles"],
           "laws_with_articles": st["laws_split"] + len(hub_laws), "methods": dict(methods), "unit_kinds": dict(kinds),
           "id_collisions_with_hub": collide, "toc": dict(toc), "gap_count": len(gaps), "gap_reasons": dict(gr),
           "gap_as_published": sum(1 for g in gaps if g["as_published"]),
           "mem_min_kB": MEM_MIN[0], "mem_end_kB": mem_kb()}
    STATS.write_text(json.dumps(res, indent=2, ensure_ascii=False))
    TOCREP.write_text(json.dumps({"summary": dict(toc), "bad": toc_bad}, ensure_ascii=False, indent=1))
    GAP.write_text(json.dumps({"country": "SK", "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "count": len(gaps),
                               "reasons": dict(gr), "as_published_in_gap": res["gap_as_published"],
                               "note": "Laws with no article rows after hub-existing + local split. slov-lex WAF-blocked (403); not crawled.",
                               "laws": gaps}, ensure_ascii=False, indent=1))
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
