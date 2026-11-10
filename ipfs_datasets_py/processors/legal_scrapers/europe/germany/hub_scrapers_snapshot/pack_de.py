#!/usr/bin/env python3
"""Build an append-only densify pack of ipfs_germany_laws (DE-<Land> rows) from collect_de_laender.py records. Offline
except `ids` / `stage`, which read the public Hub API with no token.

  pack_de.py ids   --out $DE_WORK/hub_tip_ids.txt [--laws live_laws.parquet]   # law ids already on the tip
  pack_de.py build --land SN --live-laws L.parquet --live-articles A.parquet      # -> $DE_STAGE (never /dev/shm)
  pack_de.py stage --land SN                                                     # tip unchanged? -> READY file

Never-thin: live rows first, byte-identical (row-set sha256 before == after), no live id lost, no new duplicate ids,
column order/schema equal to the live tip, every article has its law. Bounds-rejected and dedup-dropped records are listed.
Exit: 0 ok, 5 tip moved, 7 secret/PII scan hit, 8 bundle file missing, 9 verify failed / collector not done, 11 finalize gate failed.
"""
import argparse, hashlib, json, os, re, shutil, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import de_lib as L  # noqa: E402

WORK = Path(os.environ.get("DE_WORK", "/workspace/de_laender/work"))
API = f"https://huggingface.co/api/datasets/{L.HUB_REPO}"
RESOLVE = f"https://huggingface.co/datasets/{L.HUB_REPO}/resolve/{L.HUB_TIP}"
BUNDLE = ["de_lib.py", "collect_de_laender.py", "pack_de.py", "robots_guard.py", "run_de_short.sh", "resume_loop_de.sh",
          "de_waiter.sh", "gate_profile.sh", "de_queue.example.txt", "requirements.txt", "README.md", "tests/test_de_laender.py",
          "short_turn.sh", "tests/test_short_turn.py", "finalize_gate.py", "tests/test_finalize_gate.py", "fix_sn.py", "tests/test_fix_sn.py", "fix_contents_titles.py", "tests/test_fix_contents_titles.py", "fix_lawtext_br.py", "tests/test_fix_lawtext_br.py",
          "refetch_de.py", "refetch_de.sh", "tests/test_sn_rework.py"]
SECRET = re.compile(r"hf_[A-Za-z0-9]{30,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY|xox[abps]-[A-Za-z0-9-]{10,}")


def stage_dir(land):
    p = Path(os.environ.get("DE_STAGE", f"/workspace/hf-staging/germany_laws_densify_{land.lower()}")).resolve()
    if str(p).startswith("/dev/shm"):
        raise SystemExit("staging under /dev/shm is forbidden (wiped on restore); use /workspace/hf-staging")
    return p


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def rowset_sha(table):
    h = hashlib.sha256()
    for r in table.to_pylist():
        h.update(json.dumps(r, ensure_ascii=False, sort_keys=True, default=str).encode()); h.update(b"\n")
    return h.hexdigest()


def norm_title(t):
    return re.sub(r"\W+", " ", (t or "").lower()).strip()


def lane_dirs(land, tags):
    return [WORK / (land.lower() + (f"_{t}" if t and t != "-" else "")) for t in tags]


def as_version(r):
    """NW tip_update record -> a new, separate version row '<id>@<valid_from>' (old tip row untouched)."""
    v = (r.get("valid_from") or (r.get("lastmod") or "")[:10] or "new").replace("-", "")
    old = r["law"]["id"]; nid = f"{old}@{v}"
    r["law"] = dict(r["law"], id=nid, identifier=nid)
    r["articles"] = [dict(a, law_id=nid, id=nid + a["id"][len(old):]) for a in r["articles"]]
    r["version_of"] = old
    return r


CLEAN_KEYS = ("footnote_rows", "footnote_law_texts", "contents_dropped", "headings_folded", "headings_dropped", "titles_trimmed",
              "norm_headings_dropped", "footnote_digit_rows_dropped", "attachment_stubs_dropped", "repealed_placeholders",
              "metadata_html_cleaned", "folded_ids")
GAP_KEYS = {"norm_headings_dropped": "empty norm heading (Artikel/§ with no body of its own on the revosax page, e.g. an Artikel that enacts a separate act); not merged into the next Artikel",
            "footnote_digit_rows_dropped": "heading plus only a footnote number/marker, no body",
            "attachment_stubs_dropped": "attachment stub (e.g. 'Anlagen' -> 'Karte'): the attachment itself is not on the page",
            "headings_dropped": "trailing heading-only row (no following article to fold into)",
            "contents_dropped": "contents-list row"}


def load_records(land, tags=("-",), include_updates=False, clean_stats=None):
    """Every record passes de_lib.clean_record (footnote HTML, contents rows, heading-only rows, title body text)."""
    out, rejected, updates = [], [], []
    cs = clean_stats if clean_stats is not None else {}
    for d in lane_dirs(land, tags):
        for p in sorted((d / "records").glob("*.json")):
            r = json.loads(p.read_text())
            if r.get("tip_update"):
                updates.append(r["law"]["id"])
                if not include_updates:
                    continue
                r = as_version(r)
            r, st = L.clean_record(r); r["_clean"] = st
            for k in CLEAN_KEYS:
                cs[k] = cs.get(k, [] if isinstance(st.get(k, 0), list) else 0) + st.get(k, 0)
            (rejected if r.get("bounds") else out).append(r)
    return out, rejected, updates


def merge(live_laws, live_arts, records, land):
    """Pure: returns (laws_table, articles_table, report). Raises ValueError on a never-thin failure."""
    import pyarrow as pa
    jur = L.LANDS[land]["jurisdiction"]
    live_ids = set(live_laws.column("id").to_pylist())
    land_titles = {norm_title(r["title"]) for r in live_laws.to_pylist() if r["jurisdiction"] == jur}
    new_laws, new_arts, dropped = [], [], []
    for r in records:
        law = r["law"]
        if law["id"] in live_ids:
            dropped.append({"id": law["id"], "why": "id_on_tip"}); continue
        if norm_title(law["title"]) in land_titles and not r.get("version_of"):
            dropped.append({"id": law["id"], "why": "same_title_same_land_on_tip"}); continue
        live_ids.add(law["id"]); land_titles.add(norm_title(law["title"]))
        new_laws.append(law); new_arts += r["articles"]
    new_laws.sort(key=lambda x: (x["date_issued"] or "", x["id"]))
    order = {x["id"]: i for i, x in enumerate(new_laws)}
    new_arts.sort(key=lambda a: order[a["law_id"]])  # stable: keeps in-law order
    ls, as_ = live_laws.schema, live_arts.schema
    add_l = pa.Table.from_pylist([{c: x.get(c) for c in ls.names} for x in new_laws], schema=ls)
    add_a = pa.Table.from_pylist([{c: x.get(c) for c in as_.names} for x in new_arts], schema=as_)
    laws = pa.concat_tables([live_laws, add_l]); arts = pa.concat_tables([live_arts, add_a])
    rep = {"land": jur, "tip": L.HUB_TIP, "laws_old": live_laws.num_rows, "laws_new": laws.num_rows, "laws_added": add_l.num_rows,
           "articles_old": live_arts.num_rows, "articles_new": arts.num_rows, "articles_added": add_a.num_rows, "dropped": dropped}
    if rowset_sha(laws.slice(0, live_laws.num_rows)) != rowset_sha(live_laws):
        raise ValueError("live law rows changed")
    if rowset_sha(arts.slice(0, live_arts.num_rows)) != rowset_sha(live_arts):
        raise ValueError("live article rows changed")
    ids = laws.column("id").to_pylist()
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate law ids")
    old_a = live_arts.column("id").to_pylist()
    if len(set(arts.column("id").to_pylist())) - len(set(old_a)) != add_a.num_rows:
        raise ValueError("new duplicate article ids")
    if set(add_a.column("law_id").to_pylist()) - set(ids):
        raise ValueError("orphan articles")
    cnt = {}
    for a in add_a.column("law_id").to_pylist():
        cnt[a] = cnt.get(a, 0) + 1
    if any(cnt.get(x["id"], 0) != x["article_count"] for x in new_laws):
        raise ValueError("article_count mismatch")
    rep["kinds"] = kinds_of(new_laws)  # only the rows this pack adds, after every drop
    return laws, arts, rep


def kinds_of(law_rows):
    out = {}
    for x in law_rows:
        k = (json.loads(x.get("metadata_json") or "{}").get("metadata") or {}).get("kind") or "?"
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


def card_counts(card):
    """Numbers as printed on CARD_SECTION.md."""
    m = re.search(r"\((\d+) laws / (\d+) articles", card); k = re.search(r"- Kinds: (\{.*\})", card)
    out = {"laws_added": int(m.group(1)) if m else None, "articles_added": int(m.group(2)) if m else None}
    for kk, v in (json.loads(k.group(1)) if k else {}).items():
        out[f"kind:{kk}"] = v
    return out


def finalize_gate(pack, n_old_laws, n_old_arts):
    """Re-reads the written parquet + card; the three CoS checks over the rows this pack adds."""
    import pyarrow.parquet as pq
    import finalize_gate as G
    laws = pq.read_table(pack / "data" / "laws.parquet"); arts = pq.read_table(pack / "data" / "articles.parquet")
    nl = laws.slice(n_old_laws).to_pylist(); na = arts.slice(n_old_arts).to_pylist()
    data = {"laws_added": len(nl), "articles_added": len(na)}
    data.update({f"kind:{k}": v for k, v in kinds_of(nl).items()})
    cnt = {}
    for a in na:
        cnt[a["law_id"]] = cnt.get(a["law_id"], 0) + 1
    card = card_counts((pack / "CARD_SECTION.md").read_text())
    rd = pack / "README.md"
    if rd.exists():  # cumulative README: its totals table must equal the written parquet
        rc = readme_counts(rd.read_text(encoding="utf-8"))
        card.update({f"readme:{k}": v for k, v in rc.items()})
        jur = {x: j for x, j in zip(laws.column("id").to_pylist(), laws.column("jurisdiction").to_pylist())}
        data.update({"readme:laws_total": laws.num_rows, "readme:laws_federal": sum(1 for j in jur.values() if j == "DE"),
                     "readme:articles_total": arts.num_rows,
                     "readme:articles_federal": sum(1 for x in arts.column("law_id").to_pylist() if jur.get(x) == "DE")})
    res = G.gate(nl, na, card, data, bodyless_check=True)
    res["article_count_mismatch"] = sum(1 for x in nl if x["article_count"] != cnt.get(x["id"], 0))
    mfs = sorted((pack / "manifests").glob("*_added_ids.jsonl")) if (pack / "manifests").exists() else []
    mf = mfs[0] if len(mfs) == 1 else None
    if mf is not None:  # manifest lists exactly the added law + article ids
        man = [json.loads(x) for x in mf.read_text(encoding="utf-8").splitlines() if x.strip()]
        res["manifest_matches_data"] = (sorted(m["id"] for m in man if m["table"] == "laws") == sorted(x["id"] for x in nl)
                                        and sorted(m["id"] for m in man if m["table"] == "articles") == sorted(a["id"] for a in na))
    else:
        res["manifest_matches_data"] = False
    res["ok"] = res["ok"] and res["article_count_mismatch"] == 0 and res["manifest_matches_data"]
    return res


def readme_counts(text):
    m1 = re.search(r"\| Laws / instruments \| (\d+) \(federal (\d+) \+ Landesrecht (\d+)\)", text or "")
    m2 = re.search(r"\| Articles \| (\d+) \(federal (\d+) \+ Landesrecht (\d+)\)", text or "")
    return {"laws_total": int(m1.group(1)) if m1 else None, "laws_federal": int(m1.group(2)) if m1 else None,
            "articles_total": int(m2.group(1)) if m2 else None, "articles_federal": int(m2.group(2)) if m2 else None}


def scan_tree(root):
    hits = []
    for p in Path(root).rglob("*"):
        if p.is_file() and p.suffix in (".py", ".sh", ".md", ".txt", ".json"):
            for m in SECRET.finditer(p.read_text("utf-8", "replace")):
                hits.append(f"{p}:{m.group(0)[:12]}")
    return hits


def cmd_ids(a):
    import pyarrow.parquet as pq
    src = a.laws
    if not src:
        import requests
        src = str(WORK / "_tip_laws.parquet")
        with requests.get(f"{RESOLVE}/data/laws.parquet", stream=True, timeout=(30, 600)) as r:
            r.raise_for_status()
            with open(src, "wb") as f:
                shutil.copyfileobj(r.raw, f)
    ids = pq.read_table(src, columns=["id"]).column("id").to_pylist()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(sorted(ids)) + "\n")
    print(f"{len(ids)} ids -> {a.out}"); return 0


def cmd_build(a):
    import pyarrow.parquet as pq
    tags = a.tags.split(",")
    for d in lane_dirs(a.land, tags):
        st = d / "state.json"
        if not (st.exists() and json.loads(st.read_text()).get("done")):
            print("collector not done", d); return 9
    cs = {}
    recs, rejected, updates = load_records(a.land, tags, a.include_updates, cs)
    laws, arts, rep = merge(pq.read_table(a.live_laws), pq.read_table(a.live_articles), recs, a.land)
    out = stage_dir(a.land); pack = out / "pack"
    if pack.exists():
        shutil.rmtree(pack)
    (pack / "data").mkdir(parents=True); (pack / "scrapers" / "tests").mkdir(parents=True); (pack / "manifests").mkdir()
    pq.write_table(laws, pack / "data" / "laws.parquet", compression="zstd")
    pq.write_table(arts, pack / "data" / "articles.parquet", compression="zstd")
    for f in BUNDLE:
        if not (HERE / f).exists():
            print("bundle file missing", f); return 8
        shutil.copy2(HERE / f, pack / "scrapers" / f)
    rep["bounds_rejected"] = [r["law"]["id"] for r in rejected]
    rep["pii_redactions_all_records"] = sum(r.get("pii_hits", 0) for r in recs)  # every collected record, incl. ones not added
    _mark = re.compile(r"\[REDACTED-[a-z_]+\]")
    rep["pii_redactions"] = sum(len(_mark.findall(v or "")) for t, n0 in ((laws, rep["laws_old"]), (arts, rep["articles_old"]))
                                for c in ("title", "text", "metadata_json") if c in t.column_names
                                for v in t.column(c).to_pylist()[n0:])  # markers in the rows this pack adds
    rep["tip_updates_seen"] = updates; rep["tip_updates_included"] = bool(a.include_updates)
    added = set(laws.column("id").to_pylist()[rep["laws_old"]:]); ca = {}
    for r in recs:
        if r["law"]["id"] in added:
            for k in CLEAN_KEYS:
                ca[k] = ca.get(k, [] if isinstance(r["_clean"].get(k, 0), list) else 0) + r["_clean"].get(k, 0)
    rep["clean_up"] = {k: (len(v) if isinstance(v, list) else v) for k, v in ca.items()}  # rows this pack adds
    rep["clean_up_ids"] = {k: v for k, v in ca.items() if isinstance(v, list)}
    rep["clean_up_all_records"] = {k: (len(v) if isinstance(v, list) else v) for k, v in cs.items()}
    rep["source_terms_note"] = L.SOURCE_TERMS_NOTE
    rep["built_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    # 'dropped' = records NOT added because the row is already live (same id, or same title in the same Land): duplicates of live
    # rows, not bounds rejections. bounds_rejected = pages with no norm text of their own (text < min_text_chars).
    rep["not_added_duplicates_of_live_rows"] = {"total": len(rep["dropped"]),
                                                "by_reason": {w: sum(1 for d in rep["dropped"] if d["why"] == w) for w in sorted({d["why"] for d in rep["dropped"]})}}
    rep["bounds_rejected_reasons"] = {}
    for r in rejected:
        for b in r.get("bounds") or []:
            rep["bounds_rejected_reasons"][b] = rep["bounds_rejected_reasons"].get(b, 0) + 1
    rep["refetched_pages"] = sum(1 for r in recs if r["law"]["id"] in set(laws.column("id").to_pylist()[rep["laws_old"]:]) and refetched(a.land, r["law"]["id"]))
    prefix = os.environ.get("DE_MANIFEST_PREFIX") or ("densify_" + a.land.lower() + "".join(f"_{t}" for t in tags if t and t != "-"))
    rep["manifest_prefix"] = prefix
    write_manifests(pack, prefix, laws, arts, rep, recs, rejected)
    (pack / "DENSIFY_REPORT.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    (pack / "CARD_SECTION.md").write_text(card_section(a.land, rep))
    if getattr(a, "readme", None):
        rep["_pack"] = str(pack)  # read by cumulative_readme only; never written to DENSIFY_REPORT.json
        try:
            (pack / "README.md").write_text(cumulative_readme(Path(a.readme).read_text(encoding="utf-8"), a.land, rep, laws, arts), encoding="utf-8")
        finally:
            rep.pop("_pack", None)
    g = finalize_gate(pack, rep["laws_old"], rep["articles_old"])
    rep["finalize_gate"] = g
    (pack / "DENSIFY_REPORT.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    print("finalize_gate", json.dumps(g, ensure_ascii=False))
    if not g["ok"]:
        print("finalize gate FAILED"); return 11
    hits = scan_tree(pack)
    if hits:
        print("secret scan hits", hits[:5]); return 7
    code = {f: sha256(pack / "scrapers" / f) for f in BUNDLE}
    code["_notes"] = {"robots_guard.py": "robots_guard fa882316 (CoS 2026-10-17): adds 'rejected request|support id' to _CHALLENGE and a VERIFY_X509_STRICT-only TLS relax for 4 Taiwan hosts; no German host affected. Earlier DE packs were fetched with 1c9f28bc (one-hop, 2026-10-14)."}
    (pack / "scrapers" / "code.json").write_text(json.dumps(code, indent=1))
    sums = [f"{sha256(p)}  {p.relative_to(pack)}" for p in sorted(pack.rglob("*")) if p.is_file()]
    (pack / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    print(json.dumps({k: v for k, v in rep.items() if k != "dropped"}), "dropped", len(rep["dropped"])); return 0


def refetched(land, lid):
    """True when the record was rebuilt from a page re-fetched by refetch_de.py (a records_prev/ copy exists)."""
    rid = lid.split("-", 2)[2]
    return any((d / "records_prev" / f"{lid}.json").exists() for d in WORK.glob(land.lower() + "*")) and bool(rid)


def write_manifests(pack, prefix, laws, arts, rep, recs, rejected):
    """manifests/<prefix>_added_ids.jsonl  every added law and article id (table, id[, law_id]);
    <prefix>_known_gaps.jsonl  rows of the added laws that were dropped by the clean-up (id, law_id, reason) and the repeal
    placeholders kept with metadata_json.body_status; <prefix>_not_added.jsonl  collected records not added: duplicates of live
    rows (same id / same title in the same Land) and bounds rejections (no norm text of their own)."""
    md = pack / "manifests"; md.mkdir(exist_ok=True)
    nl, na = rep["laws_old"], rep["articles_old"]
    with open(md / f"{prefix}_added_ids.jsonl", "w", encoding="utf-8") as f:
        for i in laws.column("id").to_pylist()[nl:]:
            f.write(json.dumps({"table": "laws", "id": i}, ensure_ascii=False) + "\n")
        for i, l in zip(arts.column("id").to_pylist()[na:], arts.column("law_id").to_pylist()[na:]):
            f.write(json.dumps({"table": "articles", "id": i, "law_id": l}, ensure_ascii=False) + "\n")
    added = set(laws.column("id").to_pylist()[nl:])
    gaps = []
    for r in recs:
        if r["law"]["id"] not in added:
            continue
        c = r["_clean"]
        for k, why in GAP_KEYS.items():
            for i in c.get(k) or []:
                gaps.append({"id": i, "law_id": r["law"]["id"], "action": "dropped", "reason": k, "why": why})
        for i in c.get("repealed_placeholders") or []:
            gaps.append({"id": i, "law_id": r["law"]["id"], "action": "kept", "reason": "repealed_placeholder",
                         "why": "repeal placeholder kept; metadata_json.body_status='repealed_placeholder'; stray footnote digits stripped"})
    with open(md / f"{prefix}_known_gaps.jsonl", "w", encoding="utf-8") as f:
        for g in gaps:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    with open(md / f"{prefix}_not_added.jsonl", "w", encoding="utf-8") as f:
        for d in rep["dropped"]:
            f.write(json.dumps({"id": d["id"], "reason": "duplicate_of_live_row", "detail": d["why"]}, ensure_ascii=False) + "\n")
        for r in rejected:
            f.write(json.dumps({"id": r["law"]["id"], "reason": "no_norm_text", "detail": ",".join(r.get("bounds") or []),
                                "title": (r["law"].get("title") or "")[:200], "text_chars": len(r["law"].get("text") or "")}, ensure_ascii=False) + "\n")
    rep["known_gaps"] = {k: sum(1 for g in gaps if g["reason"] == k) for k in list(GAP_KEYS) + ["repealed_placeholder"]}
    return gaps


def _fmt(n):
    return f"{n:,}"


def cumulative_readme(live, land, rep, laws, arts):
    """Full live README (as at the tip) + this batch: snapshot/totals rows updated, contents bullet, new section at the end."""
    cfg = L.LANDS[land]; jur = cfg["jurisdiction"]; prefix = rep["manifest_prefix"]; day = rep["built_at"][:10]
    ids = laws.column("id").to_pylist(); js = laws.column("jurisdiction").to_pylist()
    jmap = dict(zip(ids, js)); fed_l = sum(1 for j in js if j == "DE")
    fed_a = sum(1 for x in arts.column("law_id").to_pylist() if jmap.get(x) == "DE")
    s = live
    s = re.sub(r"(\| Snapshot date \| [^|\n]*?)( \|)", lambda m: m.group(1) + (f"; {jur} amending acts {day}" if f"{jur} amending acts" not in m.group(1) else "") + m.group(2), s, count=1)
    s = re.sub(r"\| Laws / instruments \| \d+ \(federal \d+ \+ Landesrecht \d+\)", f"| Laws / instruments | {laws.num_rows} (federal {fed_l} + Landesrecht {laws.num_rows - fed_l})", s, count=1)
    s = re.sub(r"\| Articles \| \d+ \(federal \d+ \+ Landesrecht \d+\)", f"| Articles | {arts.num_rows} (federal {fed_a} + Landesrecht {arts.num_rows - fed_a})", s, count=1)
    bullet = (f"- `manifests/{prefix}_added_ids.jsonl` — every law and article id added by the {jur} amending-acts densify ({day}); "
              f"`manifests/{prefix}_known_gaps.jsonl` — rows of those laws dropped by the clean-up (with reason) and the repeal placeholders kept; "
              f"`manifests/{prefix}_not_added.jsonl` — collected records not added (duplicates of live rows; pages with no norm text).")
    anchor = None
    for anchor in re.finditer(r"^- `manifests/[^\n]*$", s, re.M):
        pass
    s = s[:anchor.end()] + "\n" + bullet + s[anchor.end():] if anchor else s.rstrip("\n") + "\n\n" + bullet + "\n"
    k = rep.get("kinds", {}); cu = rep.get("clean_up", {}); kg = rep.get("known_gaps", {}); nd = rep["not_added_duplicates_of_live_rows"]
    jl_old = sum(1 for j in js[:rep["laws_old"]] if j == jur)
    ja_old = sum(1 for x in arts.column("law_id").to_pylist()[:rep["articles_old"]] if jmap.get(x) == jur)
    gap_ids = {}
    for g in (json.loads(x) for x in (Path(rep["_pack"]) / "manifests" / f"{prefix}_known_gaps.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()):
        gap_ids.setdefault(g["reason"], []).append(g["id"])
    def ids_line(key):
        v = gap_ids.get(key, [])
        return ", ".join(f"`{i}`" for i in v)
    sec = (f"\n## {jur} amending acts densify — {day} ({_fmt(rep['laws_added'])} laws / {_fmt(rep['articles_added'])} articles, append-only at {L.HUB_TIP[:8]})\n\n"
           f"- Source: {cfg['host']} ({cfg['source_type']}); licence: {cfg['license']}\n"
           f"- Kinds: {json.dumps(k, ensure_ascii=False)} — Änderungs-/Aufhebungsgesetze and -verordnungen (`metadata_json.metadata.kind` = `amending`), which the 2026-10-02 append and the 2026-10-15 densify excluded.\n"
           f"- Every live row is byte-identical and comes first; only rows are appended (no live row changed or removed). New law and article ids are unique and disjoint from the tip; `article_count` = article rows for every added law.\n"
           f"- Not added: {_fmt(nd['total'])} collected records are **duplicates of live rows** "
           f"({', '.join(f'{_fmt(v)} {w}' for w, v in nd['by_reason'].items())}); listed in `manifests/{prefix}_not_added.jsonl`. "
           f"(Earlier build logs called these 'dropped'; they are not bounds rejections.)\n"
           f"- Not added: {_fmt(len(rep['bounds_rejected']))} REVOSax pages carry no norm text of their own (text under {L.BOUNDS['min_text_chars']} characters; "
           f"stub pages that only point to a parent act, e.g. `Gesetz zum Zehnten Rundfunkänderungsstaatsvertrag`); listed in the same manifest.\n"
           f"- Clean-up (pipeline, added rows only): revosax footnotes are `[n]` markers plus a plain-text `Fußnoten:` block ({cu.get('footnote_rows', 0)} article rows, "
           f"{cu.get('footnote_law_texts', 0)} law texts converted at pack time); {cu.get('headings_folded', 0)} structural heading rows (Teil/Abschnitt/Zustimmungsgesetz, or an "
           f"`Artikel N` heading over the § rows of the act it contains) folded into the next row; {cu.get('titles_trimmed', 0)} titles cleaned; "
           f"{cu.get('metadata_html_cleaned', 0)} metadata fields cleaned of HTML. An empty `Artikel N` heading is never merged into Artikel N+1: each Artikel keeps its own text.\n"
           f"- Repeal placeholders kept: {kg.get('repealed_placeholder', 0)} rows such as `Artikel 7 (außer Kraft)` / `(aufgehoben)` stay as rows, with stray footnote digits removed "
           f"and `metadata_json.body_status` = `repealed_placeholder` (no new column; the dataset schema is unchanged): {ids_line('repealed_placeholder')}.\n"
           f"- Personal data: only personal data of private individuals is redacted (`[REDACTED-<kind>]`); official accounts (Bundesbank / public cash offices), "
           f"functional and authority mailboxes (e.g. `@sachsen.de`) and table numbers stay verbatim. Redaction markers in the added rows: {rep.get('pii_redactions', 0)}.\n"
           f"- Pages re-fetched for this rebuild (robots-checked, gated, polite delay) and cached so later parser fixes re-parse offline: {rep.get('refetched_pages', 0)}.\n\n"
           f"### Known gaps ({jur} amending acts)\n\n"
           f"Rows of the added laws that are not in the data (every id with its reason is in `manifests/{prefix}_known_gaps.jsonl`):\n\n"
           f"- {kg.get('norm_headings_dropped', 0)} empty `Artikel` headings with no body on the REVOSax page (mostly an Artikel that enacts a separate act, whose text "
           f"REVOSax keeps under that act's own page): {ids_line('norm_headings_dropped')}.\n"
           f"- {kg.get('footnote_digit_rows_dropped', 0)} heading rows with only a footnote number: {ids_line('footnote_digit_rows_dropped')}.\n"
           f"- {kg.get('attachment_stubs_dropped', 0)} attachment stubs (the map / Anhang itself is not on the page): {ids_line('attachment_stubs_dropped')}.\n"
           f"- {kg.get('headings_dropped', 0)} trailing heading-only rows (`Anlage`, `Anhang`, `Übersichtskarte` … with no content after them): listed in the manifest.\n\n"
           f"### source_terms_note\n\n{L.SOURCE_TERMS_NOTE}\n\nEvery added row also carries `source_terms_note` inside `metadata_json.metadata`.\n\n"
           f"{jur} totals after this batch: {_fmt(jl_old + rep['laws_added'])} laws ({_fmt(jl_old)} + {_fmt(rep['laws_added'])}) / "
           f"{_fmt(ja_old + rep['articles_added'])} articles ({_fmt(ja_old)} + {_fmt(rep['articles_added'])}). "
           f"Dataset totals: {_fmt(laws.num_rows)} laws / {_fmt(arts.num_rows)} articles.\n"
           f"- The bundled `scrapers/de_lib.py` has default `HUB_TIP` {L.HUB_TIP[:8]} (the parent of this batch); set `DE_HUB_TIP` to the current tip before building a new pack.\n")
    return s.rstrip("\n") + "\n" + sec


def card_section(land, rep):
    cfg = L.LANDS[land]
    return (f"## {cfg['jurisdiction']} densify ({rep['laws_added']} laws / {rep['articles_added']} articles, append-only at {L.HUB_TIP[:8]})\n\n"
            f"- Source: {cfg['host']} ({cfg['source_type']}); licence: {cfg['license']}\n"
            f"- Kinds: {json.dumps(rep.get('kinds', {}), ensure_ascii=False)}\n"
            + (f"- Not added: {rep['not_added_duplicates_of_live_rows']['total']} records that are duplicates of live rows "
               f"({', '.join(f'{v} {w}' for w, v in rep['not_added_duplicates_of_live_rows']['by_reason'].items())}); "
               f"{len(rep.get('bounds_rejected', []))} stub pages with no norm text of their own (they only point to a parent act)\n"
               if "not_added_duplicates_of_live_rows" in rep else "")
            + (f"- Clean-up (pipeline, added rows only): {cu.get('contents_dropped', 0)} contents-list rows dropped; revosax footnote HTML converted "
               f"to plain-text 'Fußnoten:' blocks in {cu.get('footnote_rows', 0)} article rows and {cu.get('footnote_law_texts', 0)} law texts; "
               f"{cu.get('headings_folded', 0)} heading-only rows folded into the next article, {cu.get('headings_dropped', 0)} trailing ones dropped; "
               f"{cu.get('titles_trimmed', 0)} titles cleaned; known gaps (dropped, listed in manifests/): {cu.get('norm_headings_dropped', 0)} empty Artikel headings, "
               f"{cu.get('footnote_digit_rows_dropped', 0)} footnote-number-only rows, {cu.get('attachment_stubs_dropped', 0)} attachment stubs; "
               f"{cu.get('repealed_placeholders', 0)} repeal placeholders kept (metadata_json.body_status)\n" if (cu := rep.get("clean_up")) else "") + "\n"
            f"### source_terms_note\n\n{L.SOURCE_TERMS_NOTE}\n\n"
            "Every added row also carries `source_terms_note` inside `metadata_json.metadata`.\n")


def cmd_stage(a):
    import requests
    out = stage_dir(a.land)
    sha = requests.get(API, timeout=60).json().get("sha")
    if sha != L.HUB_TIP:
        print(f"tip moved {sha} != {L.HUB_TIP}; rebuild on the new tip"); return 5
    if not (out / "pack" / "SHA256SUMS").exists():
        print("no built pack"); return 9
    g = finalize_gate(out / "pack", *(json.loads((out / "pack" / "DENSIFY_REPORT.json").read_text())[k] for k in ("laws_old", "articles_old")))
    if not g["ok"]:
        print("finalize gate FAILED", json.dumps(g, ensure_ascii=False)); return 11
    ready = out.parent / f"READY_germany_laws_densify_{a.land.lower()}"
    ready.write_text(json.dumps({"repo": L.HUB_REPO, "expected_parent": L.HUB_TIP, "pack": str(out / "pack"),
                                 "sums_sha256": sha256(out / "pack" / "SHA256SUMS"), "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}) + "\n")
    print("READY", ready); return 0


def queue_pack_args(land, queue=None):
    """'#PACK <LAND> <tags> [--include-updates]' lines in de_queue.txt -> default build args for that Land."""
    q = Path(queue or WORK / "de_queue.txt")
    if not q.exists():
        return None
    for ln in q.read_text().splitlines():
        f = ln.split()
        if len(f) >= 3 and f[0] == "#PACK" and f[1] == land:
            return {"tags": f[2], "include_updates": "--include-updates" in f[3:]}
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("ids"); p.add_argument("--out", default=str(WORK / "hub_tip_ids.txt")); p.add_argument("--laws", default="")
    p = sp.add_parser("build"); p.add_argument("--land", required=True); p.add_argument("--live-laws", required=True); p.add_argument("--live-articles", required=True)
    p.add_argument("--readme", default="", help="live README.md at the tip (read-only copy); the pack README = it + this batch's section")
    p.add_argument("--tags", default=None, help="comma list of sub-lanes, '-' = main (e.g. SN: '-,amending'; BB: vwv; NW: delta)")
    p.add_argument("--include-updates", action="store_true", help="NW: add tip_update records as separate '<id>@<valid_from>' version rows")
    p = sp.add_parser("stage"); p.add_argument("--land", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        qa = queue_pack_args(a.land) or {}
        if a.tags is None:
            a.tags = qa.get("tags", "-")
        a.include_updates = a.include_updates or qa.get("include_updates", False)
    return {"ids": cmd_ids, "build": cmd_build, "stage": cmd_stage}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
