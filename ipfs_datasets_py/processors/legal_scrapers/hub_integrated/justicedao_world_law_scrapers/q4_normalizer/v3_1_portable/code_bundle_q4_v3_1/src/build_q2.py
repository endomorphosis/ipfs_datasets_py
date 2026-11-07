"""Build <base>__q4 pack from a source pack folder (quality rules). Hub: READ-ONLY tip check only.
Local overwrite of an existing dest requires --allow-local-overwrite. Never Hub-writes.
"""
from __future__ import annotations
import sys, os, json, shutil, hashlib, datetime, csv, glob, resource, re, yaml, argparse
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(__file__))
import quality as Q, manifest_sanitize as MS

def _work_root():
  return os.environ.get("Q4_WORK_ROOT") or os.getcwd()

def FP():
  return os.environ.get("Q4_FIXPACKS") or os.path.join(_work_root(), "fixpacks")

def sha(p):
  h = hashlib.sha256()
  with open(p, "rb") as f:
    for b in iter(lambda: f.read(1 << 20), b""):
      h.update(b)
  return h.hexdigest()

def build(src, sfx=None, qrule=None, allow_local_overwrite=False, skip_hub=False):
  SFX = sfx or os.environ.get("QSFX", "q4")
  if qrule:
    os.environ["QRULE"] = qrule
  base = re.sub(r"__r\d+$", "", src)
  dst = f"{FP()}/{base}__{SFX}"
  if os.path.exists(dst):
    if not allow_local_overwrite:
      raise SystemExit("exists " + dst + " (pass --allow-local-overwrite to replace)")
    shutil.rmtree(dst)
  m = json.load(open(f"{FP()}/{src}/manifest.json"))
  tip = m.get("parent_commit") or m.get("live_tip_at_staging") or "offline"
  if not skip_hub:
    try:
      from huggingface_hub import HfApi
      api = HfApi()
      tip = api.repo_info(m["repo"], repo_type="dataset").sha
      live = api.list_repo_files(m["repo"], repo_type="dataset", revision=tip)
      if any(f.startswith("canonical/") for f in live):
        print("LIVE_HAS_CANONICAL", src)
        sys.exit(2)
    except Exception as e:
      if os.environ.get("Q4_REQUIRE_HUB"):
        raise
      print("HUB_READ_SKIP", type(e).__name__, str(e)[:120])
  art = sorted(glob.glob(f"{FP()}/{src}/files/canonical/articles*.parquet"))
  if not art:
    print("SOURCE_MISSING_ARTICLES", src)
    sys.exit(3)
  tmp = dst + ".building"
  shutil.rmtree(tmp, ignore_errors=True)
  os.makedirs(tmp + "/files/canonical")
  shutil.copy(f"{FP()}/{src}/files/README.md", tmp + "/files/README.md")
  if os.path.exists(f"{FP()}/{src}/readback.py"):
    shutil.copy(f"{FP()}/{src}/readback.py", tmp + "/readback.py")
  ql = os.path.join(_work_root(), "quality_logs")
  os.makedirs(ql, exist_ok=True)
  gp = tmp + "/files/canonical/known_gaps.csv"
  stats = {}
  samples = []
  with open(gp, "w", newline="") as g:
    gw = csv.writer(g)
    gw.writerow(["law_id", "original_id", "reason"])
    for kind in ("articles", "laws"):
      ps = sorted(glob.glob(f"{FP()}/{src}/files/canonical/{kind}*.parquet"))
      if ps:
        stats[kind] = Q.apply(ps, tmp + "/files/canonical", kind, gw, samples)
      if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 > 1536:
        print("STOP_RSS", src)
        shutil.rmtree(tmp)
        sys.exit(4)
  open(f"{ql}/{base}__{SFX}_dropped_samples.txt", "w").write("\n".join(map(repr, samples)))
  if "articles" not in stats:
    print("SOURCE_MISSING_ARTICLES", src)
    sys.exit(3)
  a = stats["articles"]
  dr = sum(a["dropped"].values())
  sx = a["id_suffixed"] + stats.get("laws", {}).get("id_suffixed", 0)
  rd = tmp + "/files/README.md"
  t = open(rd, encoding="utf-8").read()
  # Ensure truthful scrapers line (no false 'published in')
  t = re.sub(
    r"The scrapers and normalizer that produced this dataset are published in \[[^\]]+\]\([^\)]+\)[^\n]*",
    "Code bundle staged for review; publication pending.",
    t,
  )
  t += (
    f"\n\n## Normalization notes\nCanonical articles: {a['rows_after']} rows (source {a['rows_before']}). "
    f"{dr} rows that are only a short heading (text identical to the title), a table-of-contents line, or an empty/bare label were dropped"
    f" and are listed in `canonical/known_gaps.csv` (law_id, original_id, reason; no text). "
    f"Rows marked repealed/deleted are kept. {sx} rows with a repeated id got a stable `#k` suffix; the original id is in `metadata_json.original_id`."
    + (f" Canonical laws: {stats['laws']['rows_after']} rows." if "laws" in stats else "")
    + "\n"
  )
  if t.startswith("---"):
    yaml.safe_load(t.split("---\n")[1])
  open(rd, "w", encoding="utf-8").write(t)
  old = {f["path"]: f for f in m.get("files", [])}
  files = []
  for p in sorted(glob.glob(tmp + "/files/**/*", recursive=True)):
    if os.path.isdir(p):
      continue
    rel = os.path.relpath(p, tmp + "/files")
    o = dict(old.get(rel, {"path": rel, "op": "add"}))
    o.update(path=rel, size=os.path.getsize(p), sha256=sha(p))
    if rel.endswith(".parquet"):
      o["rows_before"] = o.get("rows")
      o["rows"] = pq.read_metadata(p).num_rows
    if rel.endswith(".csv"):
      o["rows"] = sum(1 for _ in open(p)) - 1
    files.append(o)
  m.update(
    files=files,
    parent_commit=tip,
    live_tip_at_staging=tip,
    restage=f"{SFX} quality build rules ({os.environ.get('QRULE', 'q4')}) from {src}",
    restaged_at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    quality={
      "rule": "quality.py q4 keep rule",
      "articles_rows_before": a["rows_before"],
      "articles_rows_after": a["rows_after"],
      "dropped_by_reason": a["dropped"],
      "kept_repealed_tagged": a["protected_repealed"],
      "articles_id_suffixed": a["id_suffixed"],
      "laws_id_suffixed": stats.get("laws", {}).get("id_suffixed", 0),
      "known_gaps_rows": dr,
    },
  )
  json.dump(MS.sanitize(m), open(tmp + "/manifest.json", "w"), indent=1)
  os.rename(tmp, dst)
  print("BUILT", dst, json.dumps(m["quality"]))
  import field_completeness as FC
  FC.apply_to_pack(f"{base}__{SFX}")
  print("COMPLETENESS", f"{base}__{SFX}")
  return dst

if __name__ == "__main__":
  ap = argparse.ArgumentParser()
  ap.add_argument("src")
  ap.add_argument("--allow-local-overwrite", action="store_true")
  ap.add_argument("--skip-hub", action="store_true")
  ap.add_argument("--work-root", default=None)
  ns = ap.parse_args()
  if ns.work_root:
    os.environ["Q4_WORK_ROOT"] = ns.work_root
  os.environ.setdefault("QRULE", "q4")
  os.environ.setdefault("QSFX", "q4")
  build(ns.src, allow_local_overwrite=ns.allow_local_overwrite, skip_hub=ns.skip_hub)
