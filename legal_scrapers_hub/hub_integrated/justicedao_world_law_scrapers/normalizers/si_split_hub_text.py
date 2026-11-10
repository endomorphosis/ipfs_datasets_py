#!/usr/bin/env python3
"""Slovenia (SI): local article split of hub laws.text (NO network).

- Hub text = uradni-list.si act page dump: chrome ... 'Kopiraj povezavo' | act heading 'N. Title, stran X.' |
  BODY | last 'Kazalo' / 'Na vrh' + cookie footer. Body = between those markers (heading line excluded).
- Units: 'N. člen' / 'N.a člen' / 'N. ČLEN' (clen; strict sequence 1,2,3.., inserted N.a with same N),
  each 'Priloga' / 'PRILOGA N' annex (priloga). Roman 'XI. člen' / 'Article I' (embedded treaty text) and quoted
  člen inside amending acts (lines opening with » „ " or inside an open quote) are NOT structure.
  Structural headings (DEL, poglavje, oddelek, odsek, roman 'I. SPLOŠNE DOLOČBE', 'PREHODNE IN KONČNE DOLOČBE')
  -> context metadata. Trailing signature block ('Št. ...', 'Ljubljana, dne ...', EVA) after the last člen is cut.
- Quote-aware: » „ “(open) / « “ ” (close); straight " toggles on odd count; sequence resync as in HR/SK/LV.
- IDs: <law_id>-<clen|priloga>-<num-slug>-<ordinal>; hub ids use '-article-' so no collisions (verified).
- Existing 43533 hub article rows written first, verbatim (duplicates kept); their laws not re-split.
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

SNAP = Path(os.environ.get("SI_SNAP", "/workspace/country-laws-ir/cache/hf/hub/datasets--endomorphosis--ipfs_slovenia_laws/snapshots/93611719fbb1ee0a9f21051f8f74ed1a2cbb9f16"))
WORK = _CORPORA / "si" / "extract"
OUT = WORK / "articles_merged.parquet"
STATS = WORK / "split_stats.json"
NUMREP = WORK / "numbering_check.json"
GAP = Path("/workspace/country-law-triage/slovenia_gap_list.json")
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


START_MARK = "Kopiraj povezavo"
CLEN_RE = re.compile(r"^(\d{1,4})\s?\.?\s?([a-z])?\s?\.?\s?(?:člen|ČLEN|Člen)(?:\s*(\(.{1,200}\)))?\s*$")
PRIL_RE = re.compile(r"^(?:Priloga|PRILOGA|Priloge|PRILOGE)(?:\s+(?:št\.\s?)?([0-9IVX]+[a-z]?|[A-Z]))?(?:\s*[:.–-].{0,200})?$")
STRUCT_RE = re.compile(r"^(?:(?:[IVXLC]+|\d+)\.\s?(?:DEL|del|POGLAVJE|poglavje|ODDELEK|oddelek|ODSEK|odsek|PODPOGLAVJE|podpoglavje)\b.{0,150}"
                       r"|(?:PRVI|DRUGI|TRETJI|ČETRTI|PETI|ŠESTI|SEDMI|OSMI|DEVETI|DESETI)\s+DEL\b.{0,150}"
                       r"|[IVXLC]+\.\s+[A-ZČŠŽĆĐ][A-ZČŠŽĆĐ ,\-–]{3,150}"
                       r"|(?:PREHODN|KONČN|KAZENSK|SPLOŠN|TEMELJN|UVODN)[A-ZČŠŽ]{1,2}(?:\s+IN\s+(?:PREHODN|KONČN)[A-ZČŠŽ]{1,2})?\s+DOLOČB[A-ZČŠŽ]{1,2}\.?)$")
SIG_RE = re.compile(r"^(?:Št\.|Številka:?|EVA\s|Ljubljana, dne|Ljubljana, \d)")
HEAD_RE = re.compile(r"^\(.{1,200}\)$")


def locate(text):
    L = [re.sub(r"[ \t\u00a0]+", " ", x).strip() for x in (text or "").replace("\r", "").split("\n")]
    L = [x for x in L if x]
    s = next((i for i, l in enumerate(L) if l == START_MARK), -1)
    e = next((i for i in range(len(L) - 1, -1, -1) if L[i] == "Kazalo"), -1)
    ref = next((l for l in L[:60] if l.startswith("Uradni list RS, št.")), "")
    if s < 0 and "Vstopna stran" in L[:5]:
        # pisrs.si page layout: ... title / 'Uradni list RS, št. ...' / metadata / 'Besedilo' | BODY | 'Pomagajte nam izboljšati ...'
        b = next((i for i, l in enumerate(L) if l == "Besedilo"), -1)
        f = next((i for i in range(max(b, 0), len(L)) if L[i].startswith("Pomagajte nam izboljšati")), -1)
        if b > 0 and f > b + 1:
            ti = next((i for i, l in enumerate(L[:b]) if l.startswith("Uradni list RS, št.")), -1)
            title = L[ti - 1] if ti > 0 else ""
            L = L[:b] + [title] + L[b + 1:]  # replace 'Besedilo' marker by the act title (keeps s+1 = heading)
            return L, b - 1, f, ref
    return L, s, e, ref


def qdelta(ln, sq):
    d = ln.count("»") + ln.count("„") - ln.count("«") - ln.count("“") - ln.count("”")
    if ln.count('"') % 2:
        sq = not sq
    return d, sq


def apply_pending(ctx, pending):
    keep = {k: v for k, v in ctx.items() if k in ("sequence", "upb_provision_of")}
    for kind, ln in pending:
        if kind == "struct":
            if re.search(r"DEL\b|del\b", ln) and not re.search(r"poglavje|POGLAVJE|oddelek|ODDELEK|odsek|ODSEK", ln):
                ctx = dict(keep); ctx["del"] = ln
            else:
                ctx = {k: v for k, v in ctx.items() if k in ("del", "sequence", "upb_provision_of")}; ctx["section"] = ln
        elif kind == "title":
            ctx["section_title"] = ln
    return ctx


def split_units(B):
    ctx = {}; units = []; cur = None; depth = 0; sq = False; markers = []
    prev = 0; prev_sub = ""; prev_ln = ""; in_annex = False; in_sig = False; pending = []
    for ln in B:
        at = depth + (1 if sq else 0)
        d, sq = qdelta(ln, sq); depth = max(0, depth + d)
        quoted_ctx = prev_ln.endswith(":") or prev_ln.endswith("»") or prev_ln.endswith("„")
        new = None
        m = CLEN_RE.match(ln)
        if m and not in_annex:
            ni = int(m.group(1)); sub = m.group(2) or ""
            upb_prov = at == 0 and re.search(r"(?:določb[oe]|določba|besedilo):$", prev_ln) is not None
            if at == 0 and not quoted_ctx:
                ok = (ni > prev and not sub) or (ni == prev and sub and sub > prev_sub) or (ni == 1 and not sub)
            elif upb_prov:
                ok = not sub  # UPB: final/transitional provisions of amending acts quoted after '... vsebuje naslednje končne določbe:'
            else:
                ok = ni == prev + 1 and not sub  # resync inside a (possibly unbalanced) quote
            if ok:
                if (ni <= prev and not sub) and prev > 0:
                    ctx["sequence"] = ctx.get("sequence", 1) + 1
                    if upb_prov:
                        ctx["upb_provision_of"] = prev_ln[:200]
                new = ("clen", f"{ni}{('.' + sub) if sub else ''}", m.group(3) or "")
                prev = ni; prev_sub = sub
        if not new and at == 0:
            m = PRIL_RE.match(ln)
            if m and not ln.endswith(":") and (len(ln) < 120):
                npri = sum(1 for u in units if u["kind"] == "priloga") + (1 if cur and cur["kind"] == "priloga" else 0) + 1
                new = ("priloga", m.group(1) or str(npri), "")
        if new:
            kind, num, head = new
            if cur and pending:
                del cur["lines"][len(cur["lines"]) - len(pending):]  # trailing heading lines belong to the next unit's context
                ctx = apply_pending(ctx, pending)
            pending = []
            if cur:
                units.append(cur)
            cur = {"kind": kind, "num": num, "lines": [ln], "ctx": dict(ctx), "heading": head.strip("()") if head else ""}
            markers.append((kind, num))
            in_annex = kind == "priloga"; in_sig = False
            depth = 0; sq = False; prev_ln = ln; continue
        if at == 0 and not in_annex and STRUCT_RE.match(ln) and len(ln) < 160:
            # heading: provisional until the next unit starts; if body text follows first, it stays unit content
            if cur and len(cur["lines"]) >= 1:
                if len(pending) >= 3:
                    pending = []
                pending.append(("struct", ln)); cur["lines"].append(ln)
            else:
                ctx = apply_pending(ctx, [("struct", ln)])
            prev_ln = ln; continue
        if at == 0 and cur and cur["kind"] == "clen" and SIG_RE.match(ln):
            in_sig = True  # signature block after the last člen: not part of the unit
        if in_sig:
            prev_ln = ln; continue
        if cur and pending:
            if pending[-1][0] == "struct" and len(ln) < 160 and not ln.endswith((".", ":", ";", ",")) and not in_sig:
                pending.append(("title", ln)); cur["lines"].append(ln); prev_ln = ln; continue
            pending = []
        if cur:
            if len(cur["lines"]) == 1 and cur["kind"] == "clen" and not cur["heading"] and HEAD_RE.match(ln):
                cur["heading"] = ln[1:-1].strip()
            cur["lines"].append(ln)
        elif "section" in ctx and "section_title" not in ctx and len(ln) < 160 and not CLEN_RE.match(ln):
            ctx["section_title"] = ln
        prev_ln = ln
    if cur:
        units.append(cur)
    units = [u for u in units if len(u["lines"]) >= 2]
    return units, markers


def slug(s):
    return re.sub(r"[^0-9a-z]+", "-", s.lower()).strip("-") or "x"


def process_law(r, hub_ids, st):
    lid = r["id"]
    L, s, e, ref = locate(r["text"])
    head = L[s + 1] if 0 <= s < len(L) - 1 else ""
    base = {"law_id": lid, "act": head[:200], "source_url": r["source_url"]}
    if s < 0 or e <= s + 1:
        return None, dict(base, reason="body_detect_fail", text_chars=len(r["text"] or "")), None
    B = L[s + 2:e]
    units, markers = split_units(B)
    st["raw_" + raw_check(B, markers)] += 1
    bchars = sum(len(x) for x in B)
    kind_hint = "razglasni_del" if head.startswith("Št.") or "Ob-" in head[:40] else "act"
    if not units:
        if kind_hint == "razglasni_del":
            reason = "notice_razglasni_del"
        else:
            reason = "unstructured_short" if bchars < 1500 else "unstructured_long"
        return None, dict(base, reason=reason, body_chars=bchars), markers
    rows = []
    for i, u in enumerate(units):
        rid = f"{lid}-{u['kind']}-{slug(u['num'])}-{i}"[:300]
        if rid in hub_ids:
            st["collide"] += 1
        label = f"{u['num']}. člen" if u["kind"] == "clen" else f"Priloga {u['num']}"
        title = f"{label} ({u['heading']})" if u["heading"] else label
        rows.append({"law_id": lid, "id": rid, "title": title[:300], "text": "\n".join(u["lines"]),
                     "source_url": r["source_url"], "document_number": (ref or r.get("official_identifier") or "")[:200],
                     "article_number": label, "record_type": "article",
                     "metadata_json": json.dumps({"collector": "si_split_hub_text", "source": "hub laws.text (uradni-list.si snapshot)",
                                                  "unit": u["kind"], "heading": u["heading"], "context": u["ctx"], "ordinal": i,
                                                  "act": head[:300]}, ensure_ascii=False)})
    return rows, None, markers


def numbering_ok(markers):
    """1..N per sequence (restart at <= prev starts a new sequence)."""
    ints = [int(n) for k, n in markers if k == "clen" and "." not in n]
    if not ints:
        return None
    exp = ints[0]
    if exp != 1:
        return False
    for x in ints:
        if x == exp:
            exp += 1
        elif x < exp:
            exp = x + 1
        else:
            return False
    return True


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=watchdog, daemon=True).start()
    hub = pq.read_table(SNAP / "data" / "articles.parquet")
    n_hub = hub.num_rows
    hub_laws = set(hub.column("law_id").to_pylist()); hub_ids = set(hub.column("id").to_pylist())
    tmp = OUT.with_suffix(".tmp")
    w = pq.ParquetWriter(tmp, SCHEMA, compression="zstd")
    w.write_table(hub.select(COLS).cast(SCHEMA)); del hub
    st = collections.Counter(); kinds = collections.Counter(); methods = collections.Counter()
    num = collections.Counter(); gaps = []
    pf = pq.ParquetFile(SNAP / "data" / "laws.parquet")
    for rb in pf.iter_batches(batch_size=BATCH, columns=["id", "text", "source_url", "official_identifier"]):
        if STOP:
            break
        rows = rb.to_pylist(); del rb
        out = []
        for r in rows:
            st["laws"] += 1
            if r["id"] in hub_laws:
                st["hub_laws_skipped"] += 1; continue
            new, gap, markers = process_law(r, hub_ids, st)
            if markers is not None or gap is None:
                pass
            if gap:
                gaps.append(gap); continue
            st["laws_split"] += 1
            ok = numbering_ok(markers)
            num["no_clen" if ok is None else ("contiguous" if ok else "gapped")] += 1
            ks = sorted({x["id"][len(r["id"]) + 1:].split("-")[0] for x in new}); methods["+".join(ks)] += 1
            for x in new:
                kinds[x["id"][len(r["id"]) + 1:].split("-")[0]] += 1
            out.extend(new)
        del rows
        if out:
            w.write_table(pa.Table.from_pylist(out, schema=SCHEMA)); st["new_articles"] += len(out)
        del out
        if st["laws"] % 10000 < BATCH:
            print(f"{st['laws']} laws, {st['new_articles']} new arts, mem {mem_kb()//1024} MB", flush=True)
    w.close()
    if STOP:
        tmp.unlink(missing_ok=True); print("STOPPED (TERM/mem guard); output discarded", flush=True); sys.exit(3)
    tmp.replace(OUT)
    gr = collections.Counter(g["reason"] for g in gaps)
    wc = num["contiguous"] + num["gapped"]
    res = {"laws": st["laws"], "hub_laws_skipped": st["hub_laws_skipped"], "laws_split": st["laws_split"],
           "new_articles": st["new_articles"], "hub_articles": n_hub, "total_articles": n_hub + st["new_articles"],
           "laws_with_articles": st["laws_split"] + len(hub_laws), "methods": dict(methods), "unit_kinds": dict(kinds),
           "id_collisions_with_hub": st["collide"], "numbering": dict(num),
           "raw_vs_split": {k[4:]: v for k, v in st.items() if k.startswith("raw_")},
           "numbering_contiguous_pct": round(100 * num["contiguous"] / wc, 2) if wc else None,
           "gap_count": len(gaps), "gap_reasons": dict(gr), "mem_min_kB": MEM_MIN[0], "mem_end_kB": mem_kb()}
    STATS.write_text(json.dumps(res, indent=2, ensure_ascii=False))
    GAP.write_text(json.dumps({"country": "SI", "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "count": len(gaps),
                               "reasons": dict(gr),
                               "note": "Instruments with no article rows after hub-existing + local split of hub laws.text. notice_razglasni_del = public notices/tenders (Ob-...); unstructured_* = acts with no 'N. člen' / Priloga units (single-paragraph sklepi, odloki, obvestila).",
                               "laws": gaps}, ensure_ascii=False, indent=1))
    print(json.dumps(res, indent=2, ensure_ascii=False))



def raw_check(B, markers):
    """Independent numbering check: distinct arabic 'N. člen' line-starts in the raw body (quote-agnostic) vs split."""
    raw = sorted({int(m.group(1)) for m in (CLEN_RE.match(x) for x in B) if m and not m.group(2)})
    sp = sorted({int(n) for k, n in markers if k == "clen" and "." not in n})
    if not raw and not sp:
        return "none"
    if raw == sp:
        return "match"
    if sp and set(sp) <= set(raw):
        return "raw_superset"   # raw has extra numbers beyond the split (quoted amendments or missed units)
    return "differ"


if __name__ == "__main__":
    main()
