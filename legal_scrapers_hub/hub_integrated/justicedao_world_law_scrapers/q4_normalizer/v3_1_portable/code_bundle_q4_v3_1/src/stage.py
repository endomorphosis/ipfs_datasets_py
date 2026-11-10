"""Offline-capable staging helpers for q4 packs (bundle v2).
Hub mutation is prohibited (fail-closed). Local overwrite/removal is opt-in via --allow-local-overwrite.
Default ROOT is ./fixpacks under Q4_WORK_ROOT (cwd).
"""
from __future__ import annotations
import sys, os, re, json, hashlib, shutil, argparse, datetime as D, yaml
import pyarrow as pa, pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(__file__))
from norm_pure import procs, PTR
import scanlib

def _work_root():
  return os.environ.get("Q4_WORK_ROOT") or os.getcwd()

def ROOT():
  return os.environ.get("Q4_FIXPACKS") or os.path.join(_work_root(), "fixpacks")

def sha(p):
  h = hashlib.sha256()
  with open(p, "rb") as f:
    for b in iter(lambda: f.read(1 << 20), b""):
      h.update(b)
  return h.hexdigest()

def freemb():
  st = os.statvfs(_work_root())
  return (st.f_bavail * st.f_frsize) // (1024 * 1024)

def aside(d, allow=False):
  """Move a partial pack aside. Requires --allow-local-overwrite."""
  if not allow:
    raise RuntimeError("local move/overwrite refused (pass --allow-local-overwrite)")
  if not os.path.exists(d):
    return
  dest = d + ".aside_" + str(int(D.datetime.now().timestamp()))
  shutil.move(d, dest)
  return dest

def hub_mutation_prohibited(*a, **k):
  raise RuntimeError("Hub mutation prohibited in code_bundle_q4_v2 (fail-closed)")

# Explicitly do not expose write APIs
create_commit = hub_mutation_prohibited
upload_file = hub_mutation_prohibited
upload_folder = hub_mutation_prohibited
create_repo = hub_mutation_prohibited

def malta_schema():
  p = os.path.join(os.environ.get("Q4_BUNDLE_ROOT") or os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
                   "vendor", "malta_ref_schema.json")
  return json.load(open(p))

def cast_local(src_parquet, dst_parquet, kind, allow_overwrite=False):
  """Cast a local parquet to Malta all-string ZSTD. Opt-in overwrite."""
  if os.path.exists(dst_parquet) and not allow_overwrite:
    raise RuntimeError("refusing to overwrite existing file without --allow-local-overwrite")
  C = [c for c, _ in malta_schema()[kind]]
  pf = pq.ParquetFile(src_parquet)
  miss = [c for c in C if c not in pf.schema_arrow.names]
  if miss:
    raise RuntimeError(f"missing Malta cols {miss}")
  SCH = pa.schema([(c, pa.string()) for c in C])
  os.makedirs(os.path.dirname(dst_parquet), exist_ok=True)
  with pq.ParquetWriter(dst_parquet, SCH, compression="zstd") as w:
    for b in pf.iter_batches(batch_size=500, columns=C):
      w.write_table(pa.Table.from_batches([b]).cast(SCH))
  return pq.ParquetFile(dst_parquet).metadata.num_rows

def truthful_ptr(code_record_sha256: str):
  return PTR.replace("{CODE_RECORD_SHA256}", code_record_sha256)

if __name__ == "__main__":
  ap = argparse.ArgumentParser(description="Offline stage helpers (no Hub writes)")
  ap.add_argument("--allow-local-overwrite", action="store_true")
  ap.add_argument("--work-root", default=None)
  ap.add_argument("cmd", choices=["ping", "cast"])
  ap.add_argument("args", nargs="*")
  ns = ap.parse_args()
  if ns.work_root:
    os.environ["Q4_WORK_ROOT"] = ns.work_root
  if ns.cmd == "ping":
    print("stage.py offline OK; Hub mutation prohibited; ROOT=", ROOT())
  elif ns.cmd == "cast":
    kind, src, dst = ns.args
    print(cast_local(src, dst, kind, allow_overwrite=ns.allow_local_overwrite))
