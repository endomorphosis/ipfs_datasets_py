"""Publish staged tranche-1 units to endomorphosis/ipfs_indonesia_municipal_laws.

For every unit in the campaign state with status "staged":
  re-validate the staged parquet fail-closed -> upload data/<BPS>_html.parquet
  -> remote-verify by downloading the file back and comparing row counts.
Then rebuild README.md / coverage_report.md / jurisdictions.jsonl to cover
the seed units + all published units and upload them.
No deletions. Token from environment / stored HF credentials only.
"""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

WS = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
CAMP = WS / "id_campaign"
STAGE = CAMP / "staging"
STATE_PATH = CAMP / "id_campaign_tranche1_state.json"
REGISTRY = WS / "id_jdih_registry_2026-10-12.json"
REPO_ID = "endomorphosis/ipfs_indonesia_municipal_laws"

sys.path.insert(0, str(Path.home() / "workspace" / "ipfs_datasets_py" /
                       "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.schema import validate_table  # noqa: E402

import pyarrow.parquet as pq  # noqa: E402
from huggingface_hub import HfApi, hf_hub_download  # noqa: E402

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402


def make_api():
    entry = dynamic_credential_entry("custom.huggingface")
    token = entry.get("surrogate") if isinstance(entry, dict) else None
    if not token:
        raise RuntimeError("dynamic_credential_entry returned no surrogate")
    return HfApi(token=token), token

SEED = [
    {"bps": "3273", "name": "Kota Bandung", "province": "Jawa Barat", "type": "kota",
     "jdih_host": "jdih.bandung.go.id", "template": "jdihn", "acts": 2, "rows": 71},
    {"bps": "3578", "name": "Kota Surabaya", "province": "Jawa Timur", "type": "kota",
     "jdih_host": "jdih.surabaya.go.id", "template": "surabaya", "acts": 5, "rows": 367},
    {"bps": "3374", "name": "Kota Semarang", "province": "Jawa Tengah", "type": "kota",
     "jdih_host": "jdih.semarangkota.go.id", "template": "semarang", "acts": 5, "rows": 220},
    {"bps": "3507", "name": "Kabupaten Malang", "province": "Jawa Timur", "type": "kabupaten",
     "jdih_host": "jdih.malangkab.go.id", "template": "malang", "acts": 5, "rows": 67},
]


def main():
    state = json.loads(STATE_PATH.read_text())
    registry = {u["bps"]: u for u in json.loads(REGISTRY.read_text())["units"]}
    api, token = make_api()
    staged = [s for s in state.values() if s.get("status") == "staged"]
    print(f"{len(staged)} staged units to publish", flush=True)
    published = []
    for s in sorted(staged, key=lambda x: x["bps"]):
        bps = s["bps"]
        local = STAGE / f"{bps}_html.parquet"
        table = pq.read_table(local)
        errors = validate_table(table, jurisdiction_id=bps,
                                jurisdiction_name=s["name"], country="ID")
        if errors:
            s["status"] = "failed"
            s.setdefault("errors", []).append(f"publish-time validation: {errors}")
            print(bps, "VALIDATION FAILED at publish", errors, flush=True)
            continue
        path_in_repo = f"data/{bps}_html.parquet"
        api.upload_file(path_or_fileobj=str(local), path_in_repo=path_in_repo,
                        repo_id=REPO_ID, repo_type="dataset",
                        commit_message=f"Indonesia tranche 1: add {s['name']} ({bps}) — "
                                       f"{s['acts']} Perda, {s['rows']} rows")
        got = hf_hub_download(REPO_ID, path_in_repo, repo_type="dataset",
                              token=token, force_download=True)
        remote_rows = pq.read_metadata(got).num_rows
        if remote_rows != s["rows"]:
            s.setdefault("errors", []).append(
                f"remote row mismatch: {remote_rows} != {s['rows']}")
            print(bps, "REMOTE MISMATCH", remote_rows, s["rows"], flush=True)
            continue
        s["status"] = "published"
        s["hf_path"] = path_in_repo
        s["verified_rows"] = remote_rows
        published.append(s)
        STATE_PATH.write_text(json.dumps(state, indent=1, ensure_ascii=False))
        print(bps, s["name"], "published+verified", remote_rows, "rows", flush=True)

    # ---- rebuild metadata over seed + all published units in state
    all_units = {u["bps"]: dict(u) for u in SEED}
    for s in state.values():
        if s.get("status") == "published":
            reg = registry.get(s["bps"], {})
            all_units[s["bps"]] = {
                "bps": s["bps"], "name": s["name"],
                "province": reg.get("province", ""), "type": reg.get("type", ""),
                "jdih_host": s["host"], "template": s.get("adapter", ""),
                "acts": s["acts"], "rows": s["rows"],
                "_truncation": s.get("truncation", ""),
            }
    units = [all_units[k] for k in sorted(all_units)]
    n_units = len(units)
    tot_acts = sum(u["acts"] for u in units)
    tot_rows = sum(u["rows"] for u in units)
    print(f"metadata: {n_units} units, {tot_acts} acts, {tot_rows} rows", flush=True)

    jsonl = "\n".join(json.dumps({k: v for k, v in u.items()
                                  if not k.startswith("_")}, ensure_ascii=False)
                      for u in units) + "\n"
    (CAMP / "jurisdictions.jsonl").write_text(jsonl, encoding="utf-8")

    table_rows = "\n".join(
        f"| {u['bps']} | {u['name']} | {u['province']} | {u['type']} | "
        f"{u['jdih_host']} | {u['template']} | {u['acts']} | {u['rows']} |"
        for u in units)
    coverage = f"""# Coverage report — ipfs_indonesia_municipal_laws

- Status: **campaign in progress — tranche 1 published 2026-10-12**
- Source: per-region JDIH portals (official)
- Kabupaten/kota covered (≥1 act): **{n_units}/514**
- Channel: Perda (Peraturan Daerah) only. The 4 pilot seed units carry
  recent-Perda samples (2–5 per unit); tranche-1 units carry their full
  catalog when ≤150 Perda, else 2020–present (hard cap 250 per unit;
  truncations noted per unit in the campaign report).
- Total article-level rows: {tot_rows} ({tot_acts} Perda)

## Per-unit counts

| BPS | Unit | Province | Type | JDIH host | Template | Perda | Rows |
|---|---|---|---|---|---|---:|---:|
{table_rows}

## Notes

- All parquets pass the `world_municipal` fail-closed gates
  (schema/attribution/shape/uniqueness) and their jurisdiction IDs validate
  under the registered BPS scheme in `world_municipal/jurisdiction.py`.
- Denominator 514 kabupaten/kota (416 kabupaten + 98 kota), BPS/Kemendagri
  wilayah registry.
- Host registry (2026-10-12): 206/514 units harvestable from the campaign
  egress; 207 unreachable, 64 bot-walled, 20 robots-excluded (never
  harvested), 12 HTTP-error, 5 no JDIH portal found. Tranche 1 covers the
  units on known portal templates; the 174-unit generic_jdih bucket is
  scoped for tranche 2.
"""
    (CAMP / "coverage_report.md").write_text(coverage, encoding="utf-8")

    readme = (CAMP / "hf_meta" / "README.md").read_text(encoding="utf-8")
    old_banner = readme[readme.index("> **⚠️"):readme.index("## Channels")]
    new_banner = (
        f"> **⚠️ CAMPAIGN IN PROGRESS.** This repo currently contains "
        f"**{n_units} of 514** kabupaten/kota, published 2026-10-12 (4-unit "
        f"validated pilot seed + tranche 1: the registry units on known "
        f"JDIH portal templates). Coverage will keep growing unit by unit "
        f"as the remaining harvestable hosts are worked. Do not treat the "
        f"current contents as complete or representative coverage of "
        f"Indonesian municipal law.\n\n")
    readme = readme.replace(old_banner, new_banner)
    readme = readme.replace(
        "harvested from each unit's own JDIH portal as official PDFs and split to\n"
        "  article level (`Pasal N` + a Preâmbulo row per act). The seed contains the\n"
        "  most recent Perda sampled per unit in the 2026-10-12 pilot (2–5 per unit,\n"
        "  17 Perda, 725 rows) — not a unit's full back-catalog.",
        "harvested from each unit's own JDIH portal as official PDFs and split to\n"
        "  article level (`Pasal N` + a Preâmbulo row per act). Pilot seed units\n"
        "  carry recent-Perda samples (2–5 per unit); tranche-1 units carry their\n"
        "  full catalog when ≤150 Perda, else 2020–present (hard cap 250).")
    readme = readme.replace(
        "- **Coverage: 4/514 units.** The authoritative JDIHN member list sits behind\n"
        "  jdihn.go.id, unreachable from the harvest egress; the host registry is\n"
        "  being rebuilt by per-unit discovery (see the programme's registry report).",
        f"- **Coverage: {n_units}/514 units.** The authoritative JDIHN member list sits\n"
        "  behind jdihn.go.id, unreachable from the harvest egress; the host\n"
        "  registry was rebuilt by per-unit discovery (514 units verified\n"
        "  2026-10-12; 206 harvestable from this egress).")
    (CAMP / "README.md").write_text(readme, encoding="utf-8")

    for fname in ("README.md", "coverage_report.md", "jurisdictions.jsonl"):
        api.upload_file(path_or_fileobj=str(CAMP / fname), path_in_repo=fname,
                        repo_id=REPO_ID, repo_type="dataset",
                        commit_message=f"Indonesia tranche 1: coverage metadata "
                                       f"({n_units}/514 units, {tot_rows} rows)")
        print("uploaded", fname, flush=True)
    files = api.list_repo_files(REPO_ID, repo_type="dataset")
    print("repo files:", len(files), flush=True)
    print("DONE", json.dumps({"published_now": [s["bps"] for s in published],
                              "total_units": n_units, "total_rows": tot_rows}))


if __name__ == "__main__":
    main()
