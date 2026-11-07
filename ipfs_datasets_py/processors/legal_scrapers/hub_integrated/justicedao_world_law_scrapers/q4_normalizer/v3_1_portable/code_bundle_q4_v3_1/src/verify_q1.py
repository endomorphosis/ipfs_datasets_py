"""Offline verify of a q4 pack. Bundle-local imports; configurable roots via env.
Q4_WORK_ROOT: workspace root containing fixpacks/ and quality_logs/ (default: cwd).
Q4_BUNDLE_ROOT: this code bundle root (default: parent of src/).
"""
from __future__ import annotations
import sys, json, hashlib, subprocess, glob, os, yaml
import pyarrow as pa, pyarrow.parquet as pq

def _bundle_root():
  return os.environ.get("Q4_BUNDLE_ROOT") or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def _work_root():
  return os.environ.get("Q4_WORK_ROOT") or os.getcwd()

# Prefer bundle-local modules
sys.path.insert(0, os.path.join(_bundle_root(), "src"))
import scan6, scanlib as s, quality as Q

REF = json.load(open(os.path.join(_bundle_root(), "vendor", "malta_ref_schema.json")))

def verify_pack(d: str):
  """Verify pack folder name like justicedao__ipfs_X_laws_ir__q4 under fixpacks/."""
  W = _work_root()
  P = os.path.join(W, "fixpacks", d)
  m = json.load(open(os.path.join(P, "manifest.json")))
  r = {"pack": d, "bad": [], "scan6": {}, "scan7_real": {}, "scan7_fp": {}}
  for f in m["files"]:
    p = os.path.join(P, "files", f["path"])
    h = hashlib.sha256()
    with open(p, "rb") as fh:
      for b in iter(lambda: fh.read(1 << 20), b""):
        h.update(b)
    if h.hexdigest() != f["sha256"]:
      r["bad"].append("sha " + f["path"])
    if p.endswith(".parquet"):
      if pq.read_metadata(p).num_rows != f["rows"]:
        r["bad"].append("rows " + f["path"])
      kind = "laws" if os.path.basename(f["path"]).startswith("laws") else "articles"
      sc = pq.read_schema(p)
      if [x.name for x in sc] != [x[0] for x in REF[kind]] or any(x.type != pa.string() for x in sc):
        r["bad"].append("schema " + f["path"])
      h6, _ = scan6.scan(p)
      for k in scan6.FAILK:
        r["scan6"][k] = r["scan6"].get(k, 0) + h6[k]
      re_, fp = s.scan7(p)
      for k, v in re_.items():
        r["scan7_real"][k] = r["scan7_real"].get(k, 0) + v
      for k, v in fp.items():
        r["scan7_fp"][k] = r["scan7_fp"].get(k, 0) + v
    if f["path"].endswith("README.md") or p.endswith("README.md"):
      t = open(p, encoding="utf-8").read()
      yaml.safe_load(t.split("---\n")[1])
      rh = s.scan_text4(t)[1]
      if rh:
        r["bad"].append(f"readme {list(rh)}")
  for kind in ("articles", "laws"):
    ps = sorted(glob.glob(os.path.join(P, "files", "canonical", f"{kind}*.parquet")))
    if ps:
      di, dp, hl = Q.check(ps, kind)
      r[kind + "_dup_id"], r[kind + "_dup_lawid_id"], r[kind + "_heading_left"] = di, dp, hl
      if di or dp or hl:
        r["bad"] += [f"{kind} uniq/heading {di},{dp},{hl}"]
  guard = os.path.join(_bundle_root(), "src", "readonly_guard.py")
  g = subprocess.run([sys.executable, guard, P], capture_output=True, text=True).stdout.strip()
  if g != "GUARD_OK":
    r["bad"].append("guard")
  r["scan6_missed_by_scanlib"] = {k: v for k, v in r["scan6"].items() if v and not sum(r["scan7_real"].values())}
  if any(r["scan6"].values()):
    r["bad"].append("scan6 "+str(r["scan6"]))
  if any(r["scan7_real"].values()):
    r["bad"].append("scan7 "+str(r["scan7_real"]))
  r["ok"] = not r["bad"]
  out = os.path.join(W, "quality_logs")
  os.makedirs(out, exist_ok=True)
  json.dump(r, open(os.path.join(out, f"verify_{d}.json"), "w"), indent=1)
  return r

if __name__ == "__main__":
  d = sys.argv[1]
  r = verify_pack(d)
  print(d, "OK" if r["ok"] else r["bad"], flush=True)
  sys.exit(0 if r["ok"] else 1)
