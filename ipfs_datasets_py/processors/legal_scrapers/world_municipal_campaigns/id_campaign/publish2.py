"""Publish staged tranche-2 units to endomorphosis/ipfs_indonesia_municipal_laws.

Same discipline as tranche 1: re-validate each staged parquet fail-closed,
upload data/<BPS>_html.parquet, remote-verify by re-download + row count.
Then rebuild README.md / coverage_report.md / jurisdictions.jsonl over
seed + tranche-1 published + tranche-2 published. No deletions.
Token via the HF connector (dynamic credentials) only.
"""
import json
import os
import re
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

WS = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
CAMP = WS / "id_campaign"
STAGE = CAMP / "staging"
T1_STATE_PATH = CAMP / "id_campaign_tranche1_state.json"
T2_STATE_PATH = CAMP / "id_campaign_tranche2_state.json"
T2B_STATE_PATH = CAMP / "id_campaign_tranche2_swing_state.json"
REGISTRY = WS / "id_jdih_registry_2026-10-12.json"
REPO_ID = "endomorphosis/ipfs_indonesia_municipal_laws"

sys.path.insert(0, str(Path.home() / "workspace" / "ipfs_datasets_py" /
                       "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.schema import validate_table  # noqa: E402

import pyarrow.parquet as pq  # noqa: E402
from huggingface_hub import HfApi, hf_hub_download  # noqa: E402

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

EXTRA_NOTES = {}  # bps -> extra coverage note (filled at publish time)


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
    {"bps": "3507", "name": "Kabupaten Malang", "province": "Jawa Timur", "type": "kota",
     "jdih_host": "jdih.malangkab.go.id", "template": "malang", "acts": 5, "rows": 67},
]


def main():
    t1 = json.loads(T1_STATE_PATH.read_text())
    t2 = json.loads(T2_STATE_PATH.read_text())
    if T2B_STATE_PATH.exists():  # swing pass-2 ran against its own state file
        for k, v in json.loads(T2B_STATE_PATH.read_text()).items():
            if isinstance(v, dict) and v.get("status") in ("staged", "published") \
                    and t2.get(k, {}).get("status") != "published":
                t2[k] = v
            elif k not in t2:
                t2[k] = v
    registry = {u["bps"]: u for u in json.loads(REGISTRY.read_text())["units"]}
    for u in SEED:  # province/type from the authoritative registry
        reg = registry.get(u["bps"], {})
        if reg.get("province"):
            u["province"] = reg["province"]
        if reg.get("type"):
            u["type"] = reg["type"]
    api, token = make_api()
    staged = [s for s in t2.values() if isinstance(s, dict) and s.get("status") == "staged"]
    print(f"{len(staged)} staged tranche-2 units to publish", flush=True)
    published_now = []
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
        flag = " [OCR-derived]" if s.get("ocr") else ""
        api.upload_file(path_or_fileobj=str(local), path_in_repo=path_in_repo,
                        repo_id=REPO_ID, repo_type="dataset",
                        commit_message=f"Indonesia tranche 2: add {s['name']} ({bps}) — "
                                       f"{s['acts']} Perda, {s['rows']} rows{flag}")
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
        published_now.append(s)
        T2_STATE_PATH.write_text(json.dumps(t2, indent=1, ensure_ascii=False))
        print(bps, s["name"], "published+verified", remote_rows, "rows", flush=True)

    # ---- rebuild metadata over seed + all published units (t1 + t2)
    all_units = {u["bps"]: dict(u) for u in SEED}
    for st, tranche in ((t1, 1), (t2, 2)):
        for s in st.values():
            if isinstance(s, dict) and s.get("status") == "published":
                reg = registry.get(s["bps"], {})
                all_units[s["bps"]] = {
                    "bps": s["bps"], "name": s["name"],
                    "province": reg.get("province", ""), "type": reg.get("type", ""),
                    "jdih_host": s["host"], "template": s.get("adapter", ""),
                    "acts": s["acts"], "rows": s["rows"],
                    "tranche": tranche,
                    "ocr": bool(s.get("ocr")),
                    "_truncation": s.get("truncation", ""),
                    "_family": s.get("family", ""),
                }
    units = [all_units[k] for k in sorted(all_units)]
    n_units = len(units)
    tot_acts = sum(u["acts"] for u in units)
    tot_rows = sum(u["rows"] for u in units)
    t2_units = [u for u in units if u.get("tranche") == 2]
    print(f"metadata: {n_units} units ({len(t2_units)} from tranche 2), "
          f"{tot_acts} acts, {tot_rows} rows", flush=True)

    jsonl = "\n".join(json.dumps({k: v for k, v in u.items()
                                  if not k.startswith("_")}, ensure_ascii=False)
                      for u in units) + "\n"
    (CAMP / "jurisdictions.jsonl").write_text(jsonl, encoding="utf-8")

    table_rows = "\n".join(
        f"| {u['bps']} | {u['name']} | {u['province']} | {u['type']} | "
        f"{u['jdih_host']} | {u['template']} | {u['acts']} | {u['rows']} |"
        for u in units)
    unit_notes = []
    for u in t2_units:
        bits = []
        if u.get("_family"):
            bits.append(f"family: {u['_family']}")
        if u.get("_truncation"):
            bits.append(u["_truncation"])
        if u.get("ocr"):
            bits.append("**OCR-derived** (tesseract OCR of scanned official PDFs; "
                        "passed all validation gates)")
        if EXTRA_NOTES.get(u["bps"]):
            bits.append(EXTRA_NOTES[u["bps"]])
        if bits:
            unit_notes.append(f"- **{u['bps']} {u['name']}**: " + "; ".join(bits))
    unit_notes_txt = ("\n### Tranche-2 unit notes\n\n" + "\n".join(unit_notes) + "\n"
                      if unit_notes else "")
    coverage = f"""# Coverage report — ipfs_indonesia_municipal_laws

- Status: **campaign in progress — tranche 2 published 2026-10-12**
- Source: per-region JDIH portals (official)
- Kabupaten/kota covered (≥1 act): **{n_units}/514**
- Channel: Perda (Peraturan Daerah) only. The 4 pilot seed units carry
  recent-Perda samples (2–5 per unit); campaign units carry their full
  catalog when ≤150 Perda, else 2020–present (hard cap 250 per unit;
  truncations noted per unit in the campaign reports).
- Total article-level rows: {tot_rows} ({tot_acts} Perda)

## Per-unit counts

| BPS | Unit | Province | Type | JDIH host | Template | Perda | Rows |
|---|---|---|---|---|---|---:|---:|
{table_rows}
{unit_notes_txt}
## Notes

- All parquets pass the `world_municipal` fail-closed gates
  (schema/attribution/shape/uniqueness) and their jurisdiction IDs validate
  under the registered BPS scheme in `world_municipal/jurisdiction.py`.
- Denominator 514 kabupaten/kota (416 kabupaten + 98 kota), BPS/Kemendagri
  wilayah registry.
- Host registry (2026-10-12): 206/514 units harvestable from the campaign
  egress; 207 unreachable, 64 bot-walled, 20 robots-excluded (never
  harvested), 12 HTTP-error, 5 no JDIH portal found.
- Tranche 2 (2026-10-12): retried tranche 1's swing hosts (several
  recovered — including Jepara, whose real download route is an encrypted
  token endpoint its placeholder 'NO FILE' English PDFs had masked, and
  Jayapura via its Yii DokumenSearch Perda filter); ran a per-host link
  census over the 174-unit generic bucket, clustered it into portal
  families, and harvested the units matching known families; and ran a
  bounded OCR feasibility probe on scanned-image Perda PDFs (Paser).
  Scanned PDFs and intermittently unreachable hosts remain the main
  yield limiters; see the programme's tranche-2 campaign report.
"""
    (CAMP / "coverage_report.md").write_text(coverage, encoding="utf-8")

    readme = (CAMP / "README.md").read_text(encoding="utf-8")
    start = readme.index("> **⚠️")
    end = readme.index("## Channels")
    new_banner = (
        f"> **⚠️ CAMPAIGN IN PROGRESS.** This repo currently contains "
        f"**{n_units} of 514** kabupaten/kota, published 2026-10-12 (4-unit "
        f"validated pilot seed + tranche 1: registry units on known JDIH "
        f"portal templates; tranche 2: recovered swing hosts + generic-"
        f"bucket families from a 174-host link census). Coverage will keep "
        f"growing unit by unit as the remaining harvestable hosts are "
        f"worked. Do not treat the current contents as complete or "
        f"representative coverage of Indonesian municipal law.\n\n")
    readme = readme[:start] + new_banner + readme[end:]
    readme = re.sub(r"- \*\*Coverage: \d+/514 units\.\*\*",
                    f"- **Coverage: {n_units}/514 units.**", readme)
    readme = readme.replace(
        "  full catalog when ≤150 Perda, else 2020–present (hard cap 250).",
        "  full catalog when ≤150 Perda, else 2020–present (hard cap 250).\n"
        "  Tranche-2 additions are flagged in `coverage_report.md` where a\n"
        "  unit's catalog is partial or OCR-derived.")
    (CAMP / "README.md").write_text(readme, encoding="utf-8")

    for fname in ("README.md", "coverage_report.md", "jurisdictions.jsonl"):
        api.upload_file(path_or_fileobj=str(CAMP / fname), path_in_repo=fname,
                        repo_id=REPO_ID, repo_type="dataset",
                        commit_message=f"Indonesia tranche 2: coverage metadata "
                                       f"({n_units}/514 units, {tot_rows} rows)")
        print("uploaded", fname, flush=True)
    files = api.list_repo_files(REPO_ID, repo_type="dataset")
    print("repo files:", len(files), flush=True)
    print("DONE", json.dumps({"published_now": [s["bps"] for s in published_now],
                              "total_units": n_units, "total_rows": tot_rows}))


if __name__ == "__main__":
    main()
