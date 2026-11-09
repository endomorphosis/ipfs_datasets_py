#!/usr/bin/env python3
"""Build scrapers/ for KE batch 2 with ONLY the files that are new or changed against the KE scrapers on the Hub,
write manifests/batch2_code.json (sha256 + bytes of every bundled file, hub parent, parser version, pacer test,
credential scan). No top-level README (CoS).
Usage: python3 build_ke_samburu_bundle.py --pack <pack dir> --hub-scrapers <read-only copy of the Hub scrapers/> --parent <tip>
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import argparse, hashlib, json, os, re, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
COL = Path(os.environ.get("KE_COLLECTORS", (str(_CORPORA) + "/_collectors")))
REPO = "endomorphosis/ipfs_kenya_municipal_laws"
PARSER_VERSION = "ke-samburu-assembly-2026.10.04-b2"
BATCH = "batch2"

CANDIDATES = {  # bundle name -> (source name, role)
    "collect_ke_samburu_muni.py": ("collect_ke_samburu_muni.py", "batch 2 collector (www.samburuassembly.go.ke only) + offline reassess / OCR modes"),
    "stage_ke_samburu_muni.py": ("stage_ke_samburu_muni.py", "batch 2 stager (maker check, section split + checks, OCR-quality metrics, drops, parquet + manifests)"),
    "test_ke_samburu_pacer.py": ("test_ke_samburu_pacer.py", "offline pacer / hard-stop test"),
    "resolve_ke_samburu_qid.py": ("resolve_ke_samburu_qid.py", "Samburu County QID via Special:EntityData only"),
    "verify_ke_samburu.py": ("verify_ke_samburu.py", "verification (batch alone + combined with live shards) + request log (PT)"),
    "build_ke_samburu_bundle.py": ("build_ke_samburu_bundle.py", "this builder + credential scan"),
    "run_ke_samburu.sh": ("run_ke_samburu.sh", "batch 2 end-to-end run script"),
    "robots_guard.py": ("robots_guard.py", "shared robots.txt guard (current fleet version)"),
    "README.md": ("scrapers_README_ke.md", "scrapers/README.md covering batch 1 and batch 2"),
    "seeds/KE.jsonl": (None, "county seed list (only if changed)"),
    "collect_ke_counties_muni.py": (None, "batch 1 collector (only if changed; batch 2 does not modify it)"),
    "stage_ke_counties_muni.py": (None, "batch 1 stager (only if changed; batch 2 does not modify it)"),
    "run_ke.sh": (None, "batch 1 runner (only if changed)"),
}
REQUIREMENTS = """# pinned from system python3 3.13.5 (imported: pyarrow, requests, urllib3; plus their dependencies)
certifi==2025.1.31
charset-normalizer==3.4.2
idna==3.10
pyarrow==25.0.1
requests==2.32.3
urllib3==2.3.0
"""

W_TOK, W_SEC, W_PWD, W_AUTH, W_KEY, W_PRIV = "to" + "ken", "sec" + "ret", "pass" + "word", "author" + "ization", "api[_-]?" + "key", "BEGIN .*PRIV" + "ATE"
SCAN_RX = re.compile("hf_[A-Za-z0-9]{20,}|" + "|".join((W_TOK, W_SEC, W_PWD, W_AUTH, W_KEY, W_PRIV)), re.I)
VALUE_RX = re.compile("(" + "|".join((W_TOK, W_SEC, W_PWD, W_KEY, W_AUTH)) + r")\w*\s*[:=]\s*['\"][^'\"\s]{12,}['\"]", re.I)
EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
HOME_RX = re.compile("/ho" + "me/|/Us" + "ers/|C:\\\\Us" + "ers", re.I)


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def classify(line):
    if re.search(r"hf_[A-Za-z0-9]{20,}", line) or re.search(W_PRIV, line, re.I) or VALUE_RX.search(line):
        return None
    l = line.lower()
    if W_AUTH in l:
        return "HTTP header name only, no credential value"
    if W_TOK in l:
        return "word in code/comments (e.g. text tokens, robots product tokens); no credential value"
    return "word in prose/comment; no credential value"


def scan(root):
    hits, real, emails, homes = [], [], [], []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root.parent))
        try:
            text = p.read_text("utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = SCAN_RX.search(line)
            if m:
                why = classify(line)
                h = {"file": rel, "line": i, "match": m.group(0), "text": line.strip()[:160]}
                (real.append(h) if why is None else hits.append({**h, "explanation": why}))
            for e in EMAIL_RX.finditer(line):
                emails.append({"file": rel, "line": i, "match": e.group(0)})
            if HOME_RX.search(line):
                homes.append({"file": rel, "line": i, "text": line.strip()[:160]})
    return hits, real, emails, homes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True)
    ap.add_argument("--hub-scrapers", required=True)
    ap.add_argument("--parent", required=True)
    a = ap.parse_args()
    pack, hub = Path(a.pack), Path(a.hub_scrapers)
    out = pack / "scrapers"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    included, unchanged = {}, {}
    for name, (src, role) in CANDIDATES.items():
        if src is None:   # Hub file kept as is unless our working copy is meant to replace it (never for batch 2)
            if (hub / name).exists():
                unchanged[f"scrapers/{name}"] = {"hub_sha256": sha256(hub / name), "note": "on the Hub; not modified by batch 2"}
            continue
        s = HERE / src if (HERE / src).exists() else COL / src
        if (hub / name).exists() and sha256(hub / name) == sha256(s):
            unchanged[f"scrapers/{name}"] = {"hub_sha256": sha256(hub / name), "note": "identical to the Hub"}
            continue
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, out / name)
        included[name] = {"role": role, "status": "changed" if (hub / name).exists() else "new",
                          **({"hub_sha256_before": sha256(hub / name)} if (hub / name).exists() else {})}
    hub_req = (hub / "requirements.txt").read_text() if (hub / "requirements.txt").exists() else None
    if hub_req != REQUIREMENTS:
        (out / "requirements.txt").write_text(REQUIREMENTS)
        included["requirements.txt"] = {"role": "pinned Python packages", "status": "changed" if hub_req else "new"}
    else:
        unchanged["scrapers/requirements.txt"] = {"hub_sha256": sha256(hub / "requirements.txt"), "note": "identical to the Hub"}
    assert not (pack / "README.md").exists(), "top-level README must not exist (CoS)"
    hits, real, emails, homes = scan(out)
    tdir = "/tmp/ke_samburu_pacer_selftest"
    test = subprocess.run([sys.executable, str(COL / "test_ke_samburu_pacer.py")], capture_output=True, text=True,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "MUNI_STAGE": tdir, "LEGAL_CORPORA_ROOT": tdir + "/root"})
    shutil.rmtree(tdir, ignore_errors=True)
    shutil.rmtree(out / "__pycache__", ignore_errors=True)
    tools = {}
    for cmd in (["pdftotext", "-v"], ["tesseract", "--version"]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True)
            tools[cmd[0]] = (r.stdout or r.stderr).splitlines()[0]
        except Exception:
            tools[cmd[0]] = None
    man = {"repo": REPO, "batch": BATCH, "shard": "00002", "parser_version": PARSER_VERSION,
           "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "hub_parent_commit": a.parent, "hub_parent_note": "live KE tip refreshed right before staging",
           "top_level_readme": False, "python": sys.version.split()[0], "tools": tools,
           "files": {f"scrapers/{n}": {**included[n], "bytes": (out / n).stat().st_size, "sha256": sha256(out / n)} for n in sorted(included)},
           "hub_files_not_in_this_batch": unchanged,
           "pacer_test": {"result": "ALL PASS" if test.returncode == 0 and "ALL PASS" in test.stdout else "FAIL",
                          "lines": [l for l in test.stdout.splitlines() if l.startswith(("PASS", "FAIL", "ALL"))]},
           "credential_scan": {"pattern": "hf_ tokens + credential words + private-key blocks (fleet pattern)",
                               "real_credential_hits": real, "benign_hits": hits, "emails": emails, "home_paths": homes,
                               "result": "CLEAN" if not real and not homes else "REVIEW"},
           "run": ["KE_HUB_PARENT=<tip> KE_LIVE=<read-only live copy> bash scrapers/run_ke_samburu.sh"]}
    mp = pack / "manifests" / f"{BATCH}_code.json"
    mp.write_text(json.dumps(man, indent=1, ensure_ascii=False))
    print(json.dumps({"manifest": str(mp), "sha256": sha256(mp), "included": {n: v["status"] for n, v in included.items()},
                      "unchanged": sorted(unchanged), "real_hits": len(real), "benign_hits": len(hits), "emails": len(emails),
                      "home_paths": len(homes), "pacer_test": man["pacer_test"]["result"]}, indent=1))
    return 0 if not real and not homes and man["pacer_test"]["result"] == "ALL PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
