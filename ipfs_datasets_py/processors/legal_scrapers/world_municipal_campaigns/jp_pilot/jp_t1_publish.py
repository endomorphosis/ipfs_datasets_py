"""Japan tranche 1 — publish full-corpus parquets, SUPERSEDING the pilot
samples in place on endomorphosis/ipfs_japan_municipal_laws.

Reads tranche1_manifest.json (written by jp_t1_build.py). Only
municipalities whose build is valid AND full (every enumerated doc built,
zero failed docs) are published. Parquets + validation sidecars are
uploaded (overwriting the pilot samples), README.md and
coverage_report.md are regenerated from the manifest, and every parquet
is re-downloaded and re-validated with row counts asserted against the
manifest. HF credential comes from the vault connector at runtime and
is never persisted.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

sys.path.insert(0, "/opt/hatch/workflow-skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

sys.path.insert(0, "/home/hatch/workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers")
from world_municipal.parquet_io import read_html_parquet  # noqa: E402
from world_municipal.schema import validate_table  # noqa: E402
from world_municipal.jurisdiction import get_scheme  # noqa: E402

from huggingface_hub import HfApi, hf_hub_download  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
DATA = OUT / "data"
REPO_ID = "endomorphosis/ipfs_japan_municipal_laws"
JP = get_scheme("JP")


def disk_entry(code, manifest_entry):
    """Ground-truth publishable entry for a code, or None.

    A city qualifies only when ALL of: staging shows the full corpus
    built with zero failed docs; the validation sidecar says valid;
    the local parquet's row count equals the sidecar's. The manifest
    entry supplies name/family/corpus when present, since concurrent
    builders can lose each other's manifest updates; otherwise the
    fields are reconstructed from staging + the MIC registry.
    """
    staging = OUT / "staging" / f"{code}_done.json"
    sidecar = DATA / f"{code}_validation.json"
    parquet = DATA / JP.file_name(code)
    if not (staging.exists() and sidecar.exists() and parquet.exists()):
        return None
    done = json.loads(staging.read_text(encoding="utf-8"))
    if not done.get("corpus_docs"):
        return None
    if len(done["docs"]) + len(done["failed"]) < done["corpus_docs"]:
        return None
    if done["failed"]:
        return None
    rep = json.loads(sidecar.read_text(encoding="utf-8"))
    if not rep.get("valid"):
        return None
    rows = read_html_parquet(parquet).num_rows
    if rows != rep.get("rows"):
        return None
    entry = dict(manifest_entry or {})
    # disk ground truth (staging + sidecar + parquet, mutually
    # consistent) wins over a stale manifest entry
    entry["rows"] = rows
    entry["corpus_docs"] = done["corpus_docs"]
    if "name" not in entry or "family" not in entry:
        sys.path.insert(0, str(HERE))
        import jp_build as B
        import jp_t1_build as T
        base = T.ENDPOINTS.get(code, "")
        entry.setdefault("name", B.REGISTRY[code]["name"])
        entry.setdefault("family", B.family_of(base, code) if base else "?")
    entry["valid"] = True
    entry["full"] = True
    entry["failed_docs"] = []
    return entry


def main():
    manifest = json.loads((OUT / "tranche1_manifest.json").read_text(encoding="utf-8"))
    munis = manifest["municipalities"]
    # candidate codes: manifest keys + any code with complete staging
    codes = set(munis)
    staging_dir = OUT / "staging"
    if staging_dir.exists():
        codes |= {p.name.split("_")[0] for p in staging_dir.glob("*_done.json")}
    publishable = {}
    for code in sorted(codes):
        m = disk_entry(code, munis.get(code))
        if m:
            publishable[code] = m
        else:
            mm = munis.get(code) or {}
            print(f"SKIP {code}: not disk-verified complete "
                  f"(manifest valid={mm.get('valid')} full={mm.get('full')})")
    munis = publishable
    if not publishable:
        print("nothing publishable")
        return 1
    # (fall through to the original upload flow with `publishable` set)
    entry = dynamic_credential_entry("custom.huggingface")
    api = HfApi(token=entry["surrogate"])
    remote = {f.rfilename for f in api.list_repo_tree(REPO_ID, repo_type="dataset",
                                                      recursive=True)
              if getattr(f, "rfilename", None)}
    print(f"remote files before: {len(remote)}")
    ops = []
    for code, m in publishable.items():
        ops.append((DATA / JP.file_name(code), JP.file_name(code)))
        ops.append((DATA / f"{code}_validation.json", f"{code}_validation.json"))
    for local, remote_path in ops:
        assert local.exists(), local
        api.upload_file(path_or_fileobj=str(local), path_in_repo=remote_path,
                        repo_id=REPO_ID, repo_type="dataset",
                        commit_message=f"JP tranche 1: full corpus {remote_path}")
        print("uploaded", remote_path)
    api.upload_file(path_or_fileobj=str(DATA / "jurisdictions.jsonl"),
                    path_in_repo="jurisdictions.jsonl", repo_id=REPO_ID,
                    repo_type="dataset", commit_message="JP tranche 1: registry")
    # coverage report + README generated from the manifest
    total_rows = sum(m["rows"] for m in publishable.values())
    total_docs = sum(m["corpus_docs"] for m in publishable.values())
    lines = ["# Coverage — Japan municipal laws (tranche 1, 2026-10-14)", "",
             f"Full-corpus harvest (every enumerated ordinance) for "
             f"{len(publishable)} municipalities on the two commercial 例規集 "
             f"(ordinance collection) publishing systems. Pilot samples "
             f"superseded in place.", "",
             "| JIS | Municipality | System | Enumerated ordinances | Article rows |",
             "|---|---|---|---|---|"]
    for code, m in sorted(publishable.items()):
        lines.append(f"| {code} | {m['name']} | {m['family']} | "
                     f"{m['corpus_docs']} | {m['rows']} |")
    lines += ["", f"**Total: {total_docs} ordinances, {total_rows} article rows "
              f"across {len(publishable)} municipalities.**", "",
              "Tenant census and dead ends: see the campaign report "
              "(japan_campaign_tranche1_2026-10-14) in the goal workspace.", ""]
    cov = "\n".join(lines)
    (OUT / "coverage_report.md").write_text(cov, encoding="utf-8")
    api.upload_file(path_or_fileobj=str(OUT / "coverage_report.md"),
                    path_in_repo="coverage_report.md", repo_id=REPO_ID,
                    repo_type="dataset", commit_message="JP tranche 1: coverage report")
    readme = f"""# Japan Municipal Laws (ipfs_japan_municipal_laws)

Ordinances （条例・規則） of Japanese municipalities and prefectures,
harvested from the official 例規集 (reikishu, ordinance collection)
publishing systems — Gyosei Reiki-Base and Daiichi Hoki d1-law, cloud
and self-hosted variants — normalized to the shared world_municipal
19-column schema.

**Tranche 1 (2026-10-14): full corpora for {len(publishable)} bodies —
{total_docs} ordinances, {total_rows} article-level rows.** These
supersede the 2026-10-14 pilot samples (80 of 4,868 ordinances).

Jurisdiction IDs are JIS X 0402 codes (5-digit; the registry carries
the 6-digit check-digit form). `jurisdictions.jsonl` is the MIC
registry: 47 prefectures + 1,724 municipalities + 23 Tokyo special
wards (1,794 bodies).

Scrapers in `scrapers/` (jp_build.py adapters, jp_t1_build.py
full-corpus builder, jp_t1_census.py tenant census). Gates are
fail-closed (schema, attribution, source URL, doc_id uniqueness).
"""
    (OUT / "README_t1.md").write_text(readme, encoding="utf-8")
    api.upload_file(path_or_fileobj=str(OUT / "README_t1.md"),
                    path_in_repo="README.md", repo_id=REPO_ID, repo_type="dataset",
                    commit_message="JP tranche 1: README")
    for name in ("jp_build.py", "jp_t1_build.py", "jp_t1_build2.py",
                 "jp_t1_census.py", "jp_t1_census_par.py", "jp_t1_publish.py"):
        api.upload_file(path_or_fileobj=str(HERE / name),
                        path_in_repo=f"scrapers/{name}", repo_id=REPO_ID,
                        repo_type="dataset", commit_message=f"JP tranche 1: scraper {name}")
    # remote verification: re-download every published parquet, re-validate,
    # assert rows == manifest
    ok = True
    for code, m in publishable.items():
        p = hf_hub_download(REPO_ID, JP.file_name(code),
                            repo_type="dataset", token=entry["surrogate"])
        t = read_html_parquet(Path(p))
        errs = validate_table(t, jurisdiction_id=code,
                              jurisdiction_name=m["name"], country="JP")
        match = t.num_rows == m["rows"]
        print(code, "remote rows", t.num_rows, "manifest", m["rows"],
              "match", match, "errors", errs)
        ok = ok and match and not errs
    print("REMOTE VERIFY", "PASS" if ok else "FAIL")
    if ok:
        # remove the data/ duplicates an earlier tranche-1 publish run
        # created before the pilot's root layout was re-confirmed
        # (HF git history retains them; the repo keeps one layout).
        remote_now = {f.rfilename for f in api.list_repo_tree(
            REPO_ID, repo_type="dataset", recursive=True)
            if getattr(f, "rfilename", None)}
        for rp in sorted(r for r in remote_now if r.startswith("data/")):
            api.delete_file(rp, repo_id=REPO_ID, repo_type="dataset",
                            commit_message=f"JP tranche 1: remove duplicate {rp} (root layout)")
            print("deleted duplicate", rp)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
