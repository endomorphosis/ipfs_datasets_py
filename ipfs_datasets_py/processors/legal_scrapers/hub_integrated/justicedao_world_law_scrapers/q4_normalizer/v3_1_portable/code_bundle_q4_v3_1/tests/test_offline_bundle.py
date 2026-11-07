"""Synthetic offline tests for code_bundle_q4_v3. No network, no /workspace on PYTHONPATH."""
from __future__ import annotations
import json, os, sys, hashlib, subprocess, textwrap
from pathlib import Path

import pytest
import pyarrow as pa, pyarrow.parquet as pq

BUNDLE = Path(__file__).resolve().parents[1]
SRC = BUNDLE / "src"

@pytest.fixture(scope="module")
def env_bundle(tmp_path_factory):
  work = tmp_path_factory.mktemp("q4work")
  (work / "fixpacks").mkdir()
  (work / "quality_logs").mkdir()
  env = os.environ.copy()
  env["Q4_BUNDLE_ROOT"] = str(BUNDLE)
  env["BUNDLE_ROOT"] = str(BUNDLE)
  env["Q4_WORK_ROOT"] = str(work)
  env["WORK_ROOT"] = str(work)
  env["Q4_FIXPACKS"] = str(work / "fixpacks")
  env["QRULE"] = "q4"
  env["QSFX"] = "q4"
  env["PYTHONPATH"] = str(SRC)
  env["GATE_HOLD_SECONDS"] = "5"
  env["STAGGER_SECONDS"] = "0"  # same thresholds; short hold for synthetic offline only
  return work, env

def _make_tiny_source(fp: Path):
  src = fp / "demo__ipfs_tiny_laws_ir"
  (src / "files" / "canonical").mkdir(parents=True, exist_ok=True)
  laws_cols = ["id","title","text","source_url","source_type","jurisdiction","country","language","eli","date","date_issued","retrieved_at","license","law_status","identifier","official_identifier","article_count","json_path","metadata_json"]
  pq.write_table(pa.table({
    "law_id":["L1","L1"], "id":["a1","a2"], "title":["Heading Only","Real"],
    "text":["Heading Only","Body text with content here."],
    "source_url":["",""], "document_number":["",""], "article_number":["1","2"],
    "record_type":["article","article"], "metadata_json":["{}","{}"],
  }), src / "files" / "canonical" / "articles.parquet")
  pq.write_table(pa.table({c: [("L1" if c=="id" else ("Law" if c=="title" else ("Law body." if c=="text" else ("1" if c=="article_count" else ""))))] for c in laws_cols}),
                 src / "files" / "canonical" / "laws.parquet")
  readme = "---\nlicense: other\n---\n\n# Tiny\n\n## Scrapers & normalizer\nThe scrapers and normalizer that produced this dataset are published in [justicedao/world_law_scrapers](https://huggingface.co/datasets/justicedao/world_law_scrapers) (canonical schema: `law_id`).\n"
  (src / "files" / "README.md").write_text(readme)
  (src / "readback.py").write_text("print('readback')\n")
  manifest = {
    "repo": "justicedao/ipfs_tiny_laws_ir",
    "parent_commit": "deadbeef",
    "files": [
      {"path": "README.md", "sha256": hashlib.sha256(readme.encode()).hexdigest(), "size": len(readme), "rows": None},
      {"path": "canonical/articles.parquet", "sha256": "x", "rows": 2, "size": 1},
      {"path": "canonical/laws.parquet", "sha256": "y", "rows": 1, "size": 1},
    ],
    "redactions": {},
  }
  for rel in ("canonical/articles.parquet", "canonical/laws.parquet"):
    p = src / "files" / rel
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    for f in manifest["files"]:
      if f["path"] == rel:
        f["sha256"] = h
        f["size"] = p.stat().st_size
        f["rows"] = pq.read_metadata(p).num_rows
  (src / "manifest.json").write_text(json.dumps(manifest, indent=1))
  return src

def test_imports(env_bundle):
  work, env = env_bundle
  code = (
    "import scan6, scanlib, quality, manifest_sanitize, field_completeness, norm_pure, stage, verify_q1, build_q2; "
    "print('OK', hasattr(verify_q1,'verify_pack'), norm_pure.PTR[:20])"
  )
  r = subprocess.run([sys.executable, "-c", code], cwd=str(SRC), env=env, capture_output=True, text=True)
  assert r.returncode == 0, r.stderr
  assert "OK" in r.stdout

def test_scan6_and_schema(env_bundle):
  work, env = env_bundle
  ref = json.load(open(BUNDLE / "vendor" / "malta_ref_schema.json"))
  assert ref["articles"][0][0] == "law_id"
  assert ["article_count", "string"] in ref["laws"]
  arts = work / "t_articles.parquet"
  pq.write_table(pa.table({
    "law_id": ["L1"], "id": ["a1"], "title": ["T"], "text": ["hello world"],
    "source_url": [""], "document_number": [""], "article_number": ["1"],
    "record_type": ["article"], "metadata_json": ["{}"],
  }), arts)
  code = f"import scan6; h,s=scan6.scan(r'{arts}'); print(h['webmail'], h['secret'], h['path'])"
  r = subprocess.run([sys.executable, "-c", code], cwd=str(SRC), env=env, capture_output=True, text=True)
  assert r.returncode == 0, r.stderr
  assert r.stdout.strip().startswith("0 0 0")

def test_completeness_and_build_verify_smoke(env_bundle):
  work, env = env_bundle
  fp = work / "fixpacks"
  _make_tiny_source(fp)
  r = subprocess.run(
    [sys.executable, str(SRC / "build_q2.py"), "demo__ipfs_tiny_laws_ir", "--skip-hub", "--allow-local-overwrite"],
    cwd=str(work), env=env, capture_output=True, text=True,
  )
  assert r.returncode == 0, r.stdout + "\n" + r.stderr
  assert "BUILT" in r.stdout
  pack = fp / "demo__ipfs_tiny_laws_ir__q4"
  assert (pack / "manifest.v2.json").exists()
  readme2 = (pack / "files" / "README.md").read_text()
  assert "published in" not in readme2
  r2 = subprocess.run(
    [sys.executable, str(SRC / "verify_q1.py"), "demo__ipfs_tiny_laws_ir__q4"],
    cwd=str(work), env=env, capture_output=True, text=True,
  )
  assert r2.returncode == 0, r2.stdout + "\n" + r2.stderr
  assert "OK" in r2.stdout

def test_hub_mutation_fail_closed(env_bundle):
  work, env = env_bundle
  r = subprocess.run(
    [sys.executable, "-c",
     "import stage\n"
     "try:\n"
     "  stage.create_commit('x')\n"
     "except RuntimeError as e:\n"
     "  assert 'prohibited' in str(e).lower(); print('FAIL_CLOSED_OK')\n"
     "else:\n"
     "  raise SystemExit('should have failed')\n"],
    cwd=str(SRC), env=env, capture_output=True, text=True,
  )
  assert r.returncode == 0, r.stderr
  assert "FAIL_CLOSED_OK" in r.stdout

def test_build_refuses_overwrite_without_flag(env_bundle):
  """Existing dest pack: default refuse; succeed only with --allow-local-overwrite."""
  work, env = env_bundle
  fp = work / "fixpacks"
  # isolate under a distinct source name so we don't clash with smoke test dest
  src = _make_tiny_source(fp)
  # rename source folder to overwrite_demo
  demo = fp / "overwrite_demo__ipfs_tiny_laws_ir"
  if demo.exists():
    subprocess.run(["rm", "-rf", str(demo)], check=True)
  src.rename(demo)
  # first build
  r1 = subprocess.run(
    [sys.executable, str(SRC / "build_q2.py"), "overwrite_demo__ipfs_tiny_laws_ir", "--skip-hub", "--allow-local-overwrite"],
    cwd=str(work), env=env, capture_output=True, text=True,
  )
  assert r1.returncode == 0, r1.stdout + r1.stderr
  dest = fp / "overwrite_demo__ipfs_tiny_laws_ir__q4"
  assert dest.is_dir()
  marker = dest / "SENTINEL_NO_OVERWRITE"
  marker.write_text("keep")
  # second build WITHOUT flag must refuse and leave sentinel
  r2 = subprocess.run(
    [sys.executable, str(SRC / "build_q2.py"), "overwrite_demo__ipfs_tiny_laws_ir", "--skip-hub"],
    cwd=str(work), env=env, capture_output=True, text=True,
  )
  assert r2.returncode != 0
  assert "exists" in (r2.stdout + r2.stderr).lower() or r2.returncode == 1
  assert marker.exists(), "refused overwrite must leave existing dest intact"
  # third build WITH flag succeeds and replaces
  r3 = subprocess.run(
    [sys.executable, str(SRC / "build_q2.py"), "overwrite_demo__ipfs_tiny_laws_ir", "--skip-hub", "--allow-local-overwrite"],
    cwd=str(work), env=env, capture_output=True, text=True,
  )
  assert r3.returncode == 0, r3.stdout + r3.stderr
  assert "BUILT" in r3.stdout
  assert not marker.exists(), "allow-local-overwrite should replace dest"

def test_run_v2_wrapper_build_and_verify(env_bundle):
  """run_v2.sh with --bundle-root/--work-root drives build then verify entry points."""
  work, env = env_bundle
  fp = work / "fixpacks"
  wrap = fp / "wrap_demo__ipfs_tiny_laws_ir"
  if wrap.exists():
    subprocess.run(["rm", "-rf", str(wrap)], check=True)
  _make_tiny_source(fp)
  src = fp / "demo__ipfs_tiny_laws_ir"
  subprocess.run(["cp", "-a", str(src), str(wrap)], check=True)
  run = SRC / "run_v2.sh"
  # Soften gate for synthetic offline: wrap gate with a no-wait shim via GATE override?
  # gate_v2 waits for 4.5GiB/120s — on a healthy box it returns quickly if already met.
  # Use run_v2 with python build directly.
  env2 = env.copy()
  r = subprocess.run(
    ["bash", str(run), "--bundle-root", str(BUNDLE), "--work-root", str(work),
     "test_build", sys.executable, str(SRC / "build_q2.py"),
     "wrap_demo__ipfs_tiny_laws_ir", "--skip-hub", "--allow-local-overwrite"],
    cwd=str(work), env=env2, capture_output=True, text=True, timeout=600,
  )
  assert r.returncode == 0, r.stdout + "\n" + r.stderr
  assert (fp / "wrap_demo__ipfs_tiny_laws_ir__q4" / "manifest.json").exists()
  r2 = subprocess.run(
    ["bash", str(run), "--bundle-root", str(BUNDLE), "--work-root", str(work),
     "test_verify", sys.executable, str(SRC / "verify_q1.py"),
     "wrap_demo__ipfs_tiny_laws_ir__q4"],
    cwd=str(work), env=env2, capture_output=True, text=True, timeout=600,
  )
  assert r2.returncode == 0, r2.stdout + "\n" + r2.stderr
  assert "OK" in r2.stdout
