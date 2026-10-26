#!/usr/bin/env python3
"""Convert collector `collection_record.v1` instruments (in staging/national/_work/<CC>/)
into SCHEMA.md §2 staged JSONL files at staging/national/<CC>/<place_key>.<batch>.jsonl.

- one place per file (iso:<CC> national; iso:<CC>-<SUB> if a record's jurisdiction is an ISO 3166-2 code)
- write .tmp -> fsync -> schema.validate_file -> os.rename; finished files are never touched again
- incremental: ids already emitted are tracked in _work/<CC>/_emitted_ids.txt
Usage: emit_staged.py [CC ...]   (no args = all _work/* dirs)
       emit_staged.py --loop 600  (repeat every N seconds)
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, os, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from schema import place_key, validate_file, validate_record  # noqa

STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national"))
WORK = STAGE / "_work"
HERE = Path(__file__).resolve().parent
CHUNK = int(os.environ.get("EMIT_CHUNK", "1000"))
MAX_BYTES = int(os.environ.get("EMIT_MAX_BYTES", str(400 * 1024 * 1024)))
CAT = {e["country_code"]: e for e in json.load(open(HERE / "snapshot_catalog.json"))["entries"] if not e.get("alias_of")}
DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$")
SUB_RE = re.compile(r"^([A-Z]{2})-([A-Z0-9]{1,3})$")
CC_FIX = {"UK": "GB"}


def log(*a):
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def norm_date(v):
    if not v: return None
    s = str(v).strip()[:10]
    if DATE_RE.match(s): return s
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m: return f"{m[1]}-{m[2]}-{m[3]}"
    m = re.match(r"^(\d{4})", s)
    return m[1] if m and 1000 < int(m[1]) < 2100 else None


def doc_type_of(r):
    blob = " ".join(str(r.get(k) or "") for k in ("document_type", "record_type", "source_type")).lower()
    if re.search(r"gazette|issue|journal|bulletin", blob): return "gazette_act"
    if re.search(r"regul|decree|order|rule|instrument|\bsro\b|\bsi\b|forskrift|by-?law|statutory|subsidiary|resolution|directive", blob):
        return "regulation"
    if re.search(r"decision|ruling", blob): return "decision"
    return "statute"


def content_format_of(r):
    md = r.get("metadata") or {}
    blob = " ".join(str(x or "") for x in (md.get("format"), md.get("source_format"), md.get("content_type"),
                                           r.get("source_url"), r.get("source_type"), md.get("extraction"))).lower()
    if "pdf" in blob: return "pdf_text"
    if "docx" in blob or ".doc" in blob: return "docx_text"
    if "xml" in blob or "akoma" in blob or "akn" in blob: return "xml"
    return "html"


def convert(r, cc, cat):
    text = r.get("text") or ""
    if not text.strip() and isinstance(r.get("documents"), list):
        text = "\n\n".join((d.get("title") or "") + "\n" + (d.get("text") or "") for d in r["documents"] if isinstance(d, dict))
    if not text.strip():
        return None, None, "empty_text"
    jur = str(r.get("jurisdiction") or cc).upper()
    jur = CC_FIX.get(jur, jur)
    m = SUB_RE.match(jur)
    country = cc
    if m and m[1] == cc:
        place_id, admin = f"iso:{jur}", "adm1"
    else:
        place_id, admin = f"iso:{cc}", ("supranational" if cc == "EU" else "country")
    dt = doc_type_of(r)
    status = str(r.get("law_status") or "").lower()
    in_force = r.get("is_current") if isinstance(r.get("is_current"), bool) else (
        True if status in ("current", "in_force", "in force", "valid") else False if status in ("repealed", "expired", "revoked") else None)
    cf = content_format_of(r)
    consolidated = bool(r.get("consolidated")) if isinstance(r.get("consolidated"), bool) else (
        dt != "gazette_act" and cf != "pdf_text" and in_force is True)
    lang = str(r.get("language") or cat.get("language") or "und").strip().replace("_", "-")
    lang = lang.split("-")[0].lower() + ("-" + "-".join(lang.split("-")[1:]) if "-" in lang else "")
    if not re.match(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$", lang): lang = "und"
    ra = str(r.get("retrieved_at") or "")
    if not TS_RE.match(ra): ra = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    st = re.sub(r"[^a-z0-9_]+", "_", str(r.get("source_type") or cat.get("slug") or "src").lower()).strip("_")
    platform = st if st.startswith(cc.lower() + "_") else f"{cc.lower()}_{st}"
    url = r.get("source_url") or r.get("canonical_law_url") or ""
    rec = {
        "place_id": place_id, "country_code": country, "doc_id": str(r["id"]),
        "source_platform": platform, "source_url": url, "doc_type": dt, "language": lang,
        "title_native": (r.get("title") or "").strip() or None,
        "number": str(r.get("official_identifier") or r.get("identifier") or r.get("eli") or "") or None,
        "adopted_date": norm_date(r.get("date_issued") or r.get("date")),
        "published_date": norm_date(r.get("date_published") or r.get("publication_date")),
        "effective_date": norm_date(r.get("date_in_force") or r.get("effective_date")),
        "in_force": in_force, "consolidated": consolidated, "content_format": cf,
        "text": text, "retrieved_at": ra,
        "place_name": cat.get("display_name") if admin != "adm1" else jur,
        "admin_level": admin, "platform": platform,
    }
    if admin == "adm1": rec["iso_3166_2"] = jur
    rec = {k: v for k, v in rec.items() if v is not None}
    return place_id, rec, None


def flush(cc_dir_cc, pid, rows, part):
    pk = place_key(pid)
    outdir = STAGE / cc_dir_cc
    outdir.mkdir(parents=True, exist_ok=True)
    batch = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"p{part:04d}"
    final = outdir / f"{pk}.{batch}.jsonl"
    tmp = final.with_name(final.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())
    # validate_file() dispatches on suffix (.tmp unsupported), so validate rows with
    # validate_record() before the rename and re-check with validate_file() after.
    bad = [(i, e) for i, r in enumerate(rows) if (e := validate_record(r))]
    if bad:
        log(cc_dir_cc, "VALIDATION FAILED, keeping tmp", tmp, bad[:3])
        os.rename(tmp, tmp.with_name("_invalid_" + tmp.name))
        return 0
    os.rename(tmp, final)
    v = validate_file(final, expect_place_key=pk)
    if not v["ok"]:
        log(cc_dir_cc, "post-rename validate_file not ok (file left for uploader to quarantine)", final, v["errors"][:2])
    log(cc_dir_cc, "wrote", final.name, len(rows), "docs")
    return len(rows)


def emit(cc):
    wd = WORK / cc
    if not wd.is_dir(): return 0
    cat = CAT.get(cc, {"display_name": cc, "language": "und", "slug": cc.lower()})
    done_f = wd / "_emitted_ids.txt"
    done = set(done_f.read_text().split("\n")) if done_f.exists() else set()
    files = sorted(p for p in wd.rglob("*.json") if p.parent.name == "instruments" and p.stem not in done)
    if not files: return 0
    buckets, sizes, total, part, skipped = {}, {}, 0, 0, 0
    newly = []
    def drain(pid):
        nonlocal total, part
        rows = buckets.pop(pid, []); sizes.pop(pid, None)
        if rows:
            part += 1
            n = flush(cc, pid, rows, part)
            if n:
                total += n
                with done_f.open("a") as f:
                    f.write("\n".join(r["doc_id"] for r in rows) + "\n"); f.flush(); os.fsync(f.fileno())
    for p in files:
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue  # possibly mid-write; next pass
        if not r.get("id"): r["id"] = p.stem
        pid, rec, why = convert(r, cc, cat)
        if rec is None:
            skipped += 1
            with done_f.open("a") as f: f.write(p.stem + "\n")
            continue
        buckets.setdefault(pid, []).append(rec)
        sizes[pid] = sizes.get(pid, 0) + len(rec.get("text", ""))
        if len(buckets[pid]) >= CHUNK or sizes[pid] >= MAX_BYTES:
            drain(pid)
    for pid in list(buckets): drain(pid)
    if skipped: log(cc, "skipped(empty text)", skipped)
    return total


def main():
    args = sys.argv[1:]
    loop = None
    if args[:1] == ["--loop"]:
        loop = int(args[1]); args = args[2:]
    while True:
        ccs = args or sorted(p.name for p in WORK.iterdir() if p.is_dir() and re.match(r"^[A-Z]{2}$", p.name))
        for cc in ccs:
            try: emit(cc)
            except Exception as e: log(cc, "emit error", repr(e))
        if not loop: break
        time.sleep(loop)

if __name__ == "__main__":
    main()
