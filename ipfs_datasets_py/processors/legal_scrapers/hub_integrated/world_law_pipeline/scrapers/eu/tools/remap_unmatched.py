#!/usr/bin/env python3
"""One-off, streaming re-map of staging/eu/_unmatched/* with the shared crosswalk (+ own tables as fallback).

Unmatched files are never modified. Newly matched docs are staged as NEW timestamped batches:
  <CC>/<place_key>.<source>remap_<YYYYMMDDTHHMMSSZ>p<NNNN>.jsonl   (source = cvdr | pldz | pldzarch | atgr)
Idempotent: remapped doc_ids are appended to _state/remap_done.txt and skipped next time.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse
import gc
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
import pl_dzienniki as P  # noqa: E402
import cvdr as C  # noqa: E402
import ee_rt as EE  # noqa: E402
import be_lokaalbeslist as BE  # noqa: E402
import schema  # noqa: E402
from common.xwalk import XWALK  # noqa: E402

OUT = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu"))
UNM = OUT / "_unmatched"
DONE = OUT / "_state" / "remap_done.txt"


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


_GR = {}


def gr_map():
    """Diavgeia org uid -> (row, score, via): exact gr_diavgeia_org code (place_codes) first, names only as fallback
    (same common.gr_names.assign() the live scraper uses)."""
    if not _GR:
        import csv
        from common.gr_names import GrPlaces, assign, load_additions, load_org_codes
        orgs = json.loads((OUT / "_state" / "gr" / "orgs.json").read_text())["organizations"]
        cand = [r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"), encoding="utf-8"))
                if r["country_code"] == "GR" and r["admin_level"] == "municipality"]
        _GR.update(assign(GrPlaces(cand), orgs, load_org_codes(), load_additions()))
    return _GR


def group_of(name: str) -> str:
    """files are processed per group (e.g. pl_DS, cvdr) and flushed per group: few, larger batches, bounded memory."""
    return re.sub(r"_unmatched.*$", "", name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="resolve and count only; write nothing")
    ap.add_argument("--only", default="", help="comma list of groups (pl_DS,cvdr,...); default all")
    a = ap.parse_args()
    only = set(x for x in a.only.split(",") if x)
    done = set(DONE.read_text().split()) if DONE.exists() else set()
    plm, nlm, eem, bem = P.PlaceMap(), C.PlaceMap(), EE.Places(), BE.Places()
    stats, by_src, by_level, still = Counter(), Counter(), Counter(), Counter()
    part = 0
    groups = defaultdict(list)
    for f in sorted(UNM.glob("*.jsonl")):
        groups[group_of(f.name)].append(f)
    df = None if a.dry_run else DONE.open("a", encoding="utf-8")
    for g, files in sorted(groups.items()):
        if only and g not in only:
            continue
        out = defaultdict(list)
        buf = [0]
        seen_g = set()
        if g.startswith("pl_"):    # 2026-10-17 pre-pass: signer anchors from cue-resolved same-name gmina docs
            plm.anchors = {}
            for f in files:
                for ln in f.open(encoding="utf-8"):
                    r = json.loads(ln)
                    if r.get("place_id") or r.get("doc_id") in done or r.get("level") != "gmina":
                        continue
                    plm.add_anchor(plm.resolve_ext(r.get("voivodeship"), r.get("issuing_body_name"), "gmina",
                                                   r.get("title_native") or "", r.get("text") or ""), r.get("text") or "")
        for f in files:
            for ln in f.open(encoding="utf-8"):
                r = json.loads(ln)
                did = r.get("doc_id")
                if r.get("place_id") or did in done or did in seen_g:
                    continue
                seen_g.add(did)
                stats["seen"] += 1
                new, src, cc = None, None, r.get("country_code")
                if cc == "PL":
                    src = "pldzarch" if r.get("archive_source") else "pldz"
                    pl = plm.resolve_ext(r.get("voivodeship"), r.get("issuing_body_name"), r.get("level") or "unknown",
                                        r.get("title_native") or "", r.get("text") or "")   # 2026-10-17: powiaty csv, text cues
                    pl = plm.propagate(pl, r.get("text") or "")
                    if pl.get("place_id"):
                        new = dict(place_id=pl["place_id"], qid=pl["qid"], place_name=pl["place_name"],
                                   admin_level=pl["admin_level"] or pl["level"], iso_3166_2=pl["iso_3166_2"],
                                   platform_place_id=pl["teryt"], issuing_body_code=pl["teryt"],
                                   issuing_body_qid=pl["qid"], place_match="remap:" + str(pl["match"]),
                                   **{k: pl[k] for k in ("mapped_via", "former_name", "former_code", "dissolved_date", "valid_to") if pl.get(k)})
                        if pl.get("mapped_via") == "successor" and pl.get("former_code"):   # issuer = the dissolved gmina
                            new["issuing_body_code"] = pl["former_code"]
                    else:
                        still[(g[:2], str(pl.get("level") or r.get("level")), str(pl.get("match")))] += 1
                elif cc == "NL":
                    src = "cvdr"
                    m = r.get("sru_meta") or {}
                    pl = nlm.resolve(m.get("creator", r.get("issuing_body_name", "")),
                                     m.get("creator_scheme", r.get("issuing_body_scheme", "")))
                    if pl.get("place_id"):
                        new = dict(place_id=pl["place_id"], qid=pl.get("qid") or r.get("qid"), place_name=pl["place_name"],
                                   iso_3166_2=pl.get("iso_3166_2"), admin_level=pl.get("cand_admin_level") or pl["level"],
                                   issuing_body_code=pl.get("issuing_body_code"), platform_place_id=pl.get("issuing_body_code"),
                                   successor_qid=pl.get("successor_qid"), place_match="remap:" + str(pl["match"]))
                    else:
                        still[("NL", str(r.get("issuing_body_name")), str(pl.get("match")))] += 1
                elif cc == "EE":
                    src = "eert"
                    pl = eem.resolve(r.get("issuing_body_name"))
                    if pl.get("place_id"):
                        new = dict(place_id=pl["place_id"], qid=pl["qid"], place_name=pl["place_name"],
                                   admin_level=pl["admin_level"], place_match="remap:" + str(pl["match"]),
                                   **{k: pl[k] for k in ("mapped_via", "former_name", "former_code", "dissolved_date", "ehak") if pl.get(k)})
                    else:
                        still[("EE", str(pl.get("place_name")), str(pl.get("match")))] += 1
                elif cc == "BE":
                    src = "belb"
                    pl = dict(place_id=None, match=None)
                    if not (r.get("issuing_body_name") and bem.by_name(r["issuing_body_name"], pl, "passed_by->eenheid")):
                        if not r.get("issuing_body_name"):
                            pl = bem.resolve(None, [r.get("source_url"), r.get("besluit_uri")])
                    if pl.get("place_id"):
                        new = dict(place_id=pl["place_id"], qid=pl["qid"], place_name=pl["place_name"],
                                   place_match="remap:" + str(pl["match"]),
                                   **{k: pl[k] for k in ("mapped_via", "former_name", "former_code", "dissolved_date", "nis") if pl.get(k)})
                    else:
                        still[("BE", str(r.get("issuing_body_name") or (r.get("source_url") or "")[:60]), str(pl.get("match")))] += 1
                elif cc == "AT":
                    src = "atgr"
                    pid = XWALK.get("AT", r.get("gkz") or "")
                    if pid:
                        new = dict(place_id=pid, qid=pid[3:], place_match="remap:gkz->crosswalk")
                elif cc == "GR":
                    src = "grdiav"
                    hit = gr_map().get(str(r.get("issuing_body_code") or r.get("platform_place_id") or ""))
                    if hit:
                        row, sc, via = hit
                        new = dict(place_id=row["place_id"], qid=row.get("qid") or row["place_id"].split(":")[-1],
                                   place_name=row.get("place_name"),
                                   place_match="remap:" + ("diavgeia_org->code(gr_diavgeia_org)->place" if via == "code"
                                                           else f"diavgeia_org->translit({round(sc, 2)})->candidate"))
                    else:
                        still[("GR", str(r.get("issuing_body_name")), "no_code_no_name_match")] += 1
                else:
                    still[(str(cc), g, "no_remap_rule")] += 1
                if new:
                    r.update(new)
                    for dk in ("adopted_date", "published_date", "effective_date"):   # old rows: '2012-06-01+03:00'
                        v = r.get(dk)
                        if isinstance(v, str) and len(v) > 10 and re.match(r"\d{4}-\d\d-\d\d", v):
                            r[dk] = v[:10]
                    r["remapped_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    r["remapped_from"] = f.name
                    r["_src"] = src
                    if a.dry_run:
                        stats["matched"] += 1
                        by_src[src] += 1
                        by_level[(cc, r.get("admin_level"))] += 1
                        r = {"doc_id": did}
                    out[r["place_id"] if not a.dry_run else "x"].append(r)
                    buf[0] += len(r.get("text") or "") if not a.dry_run else 0
                    if buf[0] > 64 * 1024 * 1024:     # keep RSS low: write what we have (more, smaller batches)
                        part = write_out(out, a, df, done, stats, by_src, by_level, part)
                        buf[0] = 0
                        gc.collect()
        part = write_out(out, a, df, done, stats, by_src, by_level, part)
        print(g, dict(stats), flush=True)
        del out
        gc.collect()
    if df:
        df.close()
    print(json.dumps({"stats": stats, "by_source": by_src,
                      "by_country_level": {f"{k[0]}/{k[1]}": v for k, v in by_level.items()},
                      "still_unmatched_top": [[list(k), v] for k, v in still.most_common(40)],
                      "still_unmatched_total": sum(still.values())}, default=dict, ensure_ascii=False))


def write_out(out, a, df, done, stats, by_src, by_level, part):
        if not a.dry_run:
            for pid, rs in out.items():
                bad = [x["doc_id"] for x in rs if schema.validate_record({k: v for k, v in x.items() if k != "_src"})]
                rs = [x for x in rs if x["doc_id"] not in bad]
                stats["invalid"] += len(bad)
                if not rs:
                    continue
                src = rs[0].pop("_src")
                for x in rs:
                    x.pop("_src", None)
                pk = schema.place_key(pid)
                part += 1
                path = OUT / rs[0]["country_code"] / f"{pk}.{src}remap_{ts()}p{part:04d}.jsonl"
                P.atomic_write(path, rs, pk)
                for x in rs:
                    df.write(x["doc_id"] + "\n")
                    done.add(x["doc_id"])
                    by_level[(x["country_code"], x.get("admin_level"))] += 1
                df.flush()
                stats["matched"] += len(rs)
                by_src[src] += len(rs)
        out.clear()
        return part


if __name__ == "__main__":
    main()
