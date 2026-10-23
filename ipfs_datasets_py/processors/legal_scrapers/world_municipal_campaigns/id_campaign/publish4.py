"""Publish staged tranche-4 units to endomorphosis/ipfs_indonesia_municipal_laws.

Extends publish3 (same fail-closed discipline: re-validate each
staged parquet, upload data/<BPS>_html.parquet, remote-verify by
re-download + row count; metadata rebuilt over seed + ALL published
units from every campaign state file).

Tranche-4 changes, all coordination-driven:
  - Sources additionally include id_campaign_tranche4_*state*.json
    (tranche tier 4 in winner precedence).
  - The Aceh state file (id_campaign_tranche3_aceh_state.json) is
    READ-ONLY here: the tranche-3 aceh loop is still running against
    it. It feeds metadata/totals, but it is never written back and
    units whose winning record lives in it are never published by
    this script (the loop's owner publishes those).
  - Write-back is restricted to state files named in env
    ID_PUBLISH_STATES (comma-separated basenames); a file is written
    only if one of its records changed status during this run. This
    lets a publish run proceed while unrelated drives (e.g. the OCR
    chain) hold other state files.
  - State loads retry briefly to tolerate a concurrent drive's
    non-atomic save.
Token via the HF connector only. No deletions.
"""
import glob
import json
import os
import re
import sys
import time
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

WS = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
CAMP = WS / "id_campaign"
STAGE = CAMP / "staging"
REGISTRY = WS / "id_jdih_registry_2026-10-12.json"
REPO_ID = "endomorphosis/ipfs_indonesia_municipal_laws"
ACEH_STATE = "id_campaign_tranche3_aceh_state.json"

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


def load(path):
    p = Path(path)
    if not p.exists():
        return {}
    last = None
    for i in range(4):
        try:
            return json.loads(p.read_text())
        except Exception as e:  # torn read vs a drive's save: retry
            last = e
            time.sleep(3 * (i + 1))
    raise last


def with_retries(fn, tries=4, base_sleep=20):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  hf call failed ({type(e).__name__}); retry "
                  f"{i + 1}/{tries}", flush=True)
            time.sleep(base_sleep * (i + 1))
    raise last


def main():
    eligible_env = os.environ.get("ID_PUBLISH_STATES", "")
    eligible = {s.strip() for s in eligible_env.split(",") if s.strip()}

    def is_eligible(path):
        if path.name == ACEH_STATE:
            return False
        return not eligible or path.name in eligible

    # (state_dict, path, tranche) sources in ascending precedence
    sources = []
    t1p = CAMP / "id_campaign_tranche1_state.json"
    sources.append((load(t1p), t1p, 1))
    t2p = CAMP / "id_campaign_tranche2_state.json"
    t2 = load(t2p)
    t2bp = CAMP / "id_campaign_tranche2_swing_state.json"
    t2b = load(t2bp)
    for k, v in t2b.items():  # swing merges exactly as publish2/3 did
        if isinstance(v, dict) and v.get("status") in ("staged", "published") \
                and t2.get(k, {}).get("status") != "published":
            t2[k] = v
        elif k not in t2:
            t2[k] = v
    sources.append((t2, t2p, 2))
    for p in sorted(glob.glob(str(CAMP / "id_campaign_tranche3_*state*.json"))):
        sources.append((load(p), Path(p), 3))
    for p in sorted(glob.glob(str(CAMP / "id_campaign_tranche4_*state*.json"))):
        sources.append((load(p), Path(p), 4))

    registry = {u["bps"]: u for u in json.loads(REGISTRY.read_text())["units"]}
    for u in SEED:
        reg = registry.get(u["bps"], {})
        if reg.get("province"):
            u["province"] = reg["province"]
        if reg.get("type"):
            u["type"] = reg["type"]

    winners = {}
    for st, path, tr in sources:
        for bps, s in st.items():
            if isinstance(s, dict) and s.get("status") in ("staged", "published"):
                winners[bps] = (s, path, tr)

    changed_files = set()

    def persist(path):
        if path.name == ACEH_STATE or not is_eligible(path):
            return
        Path(path).write_text(json.dumps(
            next(st for st, p2, _ in sources if p2 == path),
            indent=1, ensure_ascii=False))
        changed_files.add(path.name)

    api, token = make_api()
    staged = [(s, path) for s, path, tr in winners.values()
              if s.get("status") == "staged" and is_eligible(path)]
    aceh_staged = [s["bps"] for s, path, tr in winners.values()
                   if s.get("status") == "staged" and path.name == ACEH_STATE]
    if aceh_staged:
        print(f"note: {len(aceh_staged)} aceh-owned staged units left "
              f"for the aceh loop's owner: {sorted(aceh_staged)}", flush=True)
    print(f"{len(staged)} staged units to publish", flush=True)
    published_now = []
    for s, path in sorted(staged, key=lambda x: x[0]["bps"]):
        bps = s["bps"]
        local = STAGE / f"{bps}_html.parquet"
        table = pq.read_table(local)
        errors = validate_table(table, jurisdiction_id=bps,
                                jurisdiction_name=s["name"], country="ID")
        if errors:
            s["status"] = "failed"
            s.setdefault("errors", []).append(f"publish-time validation: {errors}")
            print(bps, "VALIDATION FAILED at publish", errors, flush=True)
            persist(path)
            continue
        path_in_repo = f"data/{bps}_html.parquet"
        flag = " [OCR-derived]" if s.get("ocr") else ""
        with_retries(lambda: api.upload_file(
            path_or_fileobj=str(local), path_in_repo=path_in_repo,
            repo_id=REPO_ID, repo_type="dataset",
            commit_message=f"Indonesia tranche 4: {s['name']} ({bps}) — "
                           f"{s['acts']} Perda, {s['rows']} rows{flag}"))
        got = with_retries(lambda: hf_hub_download(
            REPO_ID, path_in_repo, repo_type="dataset",
            token=token, force_download=True))
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
        print(bps, s["name"], "published+verified", remote_rows, "rows", flush=True)
        persist(path)
    for name in sorted(changed_files):
        print("state written:", name, flush=True)

    # ---- rebuild metadata over seed + all published units
    all_units = {u["bps"]: dict(u) for u in SEED}
    for st, path, tr in sources:
        for s in st.values():
            if isinstance(s, dict) and s.get("status") == "published":
                reg = registry.get(s["bps"], {})
                prev = all_units.get(s["bps"], {})
                entry = {
                    "bps": s["bps"], "name": s["name"],
                    "province": reg.get("province", ""), "type": reg.get("type", ""),
                    "jdih_host": s["host"], "template": s.get("adapter", ""),
                    "acts": s["acts"], "rows": s["rows"],
                    "tranche": max(prev.get("tranche", 0), tr),
                    "ocr": bool(prev.get("ocr") or s.get("ocr")),
                    "_truncation": s.get("truncation", "") or prev.get("_truncation", ""),
                    "_family": s.get("family", "") or prev.get("_family", ""),
                }
                qa = (s.get("qanun_acts") if s.get("qanun_acts") is not None
                      else prev.get("qanun_acts"))
                if qa is not None:
                    entry["qanun_acts"] = qa
                all_units[s["bps"]] = entry
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
    unit_notes = []
    for u in units:
        if u.get("tranche", 0) < 2:
            continue
        bits = []
        if u.get("_family"):
            bits.append(f"family: {u['_family']}")
        if u.get("_truncation"):
            bits.append(u["_truncation"])
        if u.get("qanun_acts"):
            bits.append(f"includes {u['qanun_acts']} Qanun (Aceh's "
                        "Perda-equivalent instruments, accepted under "
                        "Benjamin's 2026-10-13 policy decision)")
        if u.get("ocr"):
            bits.append("**OCR-derived content included** (tesseract OCR of "
                        "scanned official PDFs; passed all validation gates)")
        if bits:
            unit_notes.append(f"- **{u['bps']} {u['name']}**: " + "; ".join(bits))
    unit_notes_txt = ("\n### Unit notes (tranche 2-4)\n\n" + "\n".join(unit_notes) + "\n"
                      if unit_notes else "")
    coverage = f"""# Coverage report — ipfs_indonesia_municipal_laws

- Status: **campaign in progress — tranche 4 published 2026-10-13**
- Source: per-region JDIH portals (official)
- Kabupaten/kota covered (≥1 act): **{n_units}/514**
- Channel: Perda (Peraturan Daerah) only — plus, for Aceh, Qanun
  Kabupaten/Kota as Perda-equivalent (see the policy note below). The 4
  pilot seed units carry recent-Perda samples (2–5 per unit); campaign
  units carry their full catalog when ≤150 Perda, else 2020–present
  (hard cap 250 per unit; truncations noted per unit in the campaign
  reports).
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
- Tranche 3 (2026-10-13): an OCR lane (per-doc fallback to tesseract OCR
  for scanned-image PDFs, flagged per unit above) opened the scanned
  catalogs that born-digital extraction could not read; swing/dokumen_view/
  dih retries recovered hosts that were down in tranche 2; produkhukum and
  wordpress family adapters and a bespoke-host census added further units.
- Tranche 4 (2026-10-13): the OCR lane worked the scanned-catalog queue
  (Paser, Way Kanan remainder, Pagar Alam, Kerinci, Bukittinggi, Sumba
  Barat, Mahakam Ulu, Pesisir Barat, Kupang and Indramayu top-ups,
  Rembang's over-cap PDFs); the dokumen_view retry tail, the Tegal
  produkhukum harvest and the Rokan Hulu wordpress rerun were completed;
  the bespoke census finished 94/94 (all one-off builds, no hidden
  template family). See the programme's tranche-4 campaign report for
  per-unit detail.
- **Aceh Qanun policy (2026-10-13):** Aceh's Perda-equivalent instruments
  are titled Qanun (Qanun Kabupaten/Kota). Under Benjamin's policy
  decision of 2026-10-13, Qanun documents on Aceh JDIH (dih-family)
  hosts are ingested as Perda-equivalent and counted per unit in the
  unit notes above (and as `qanun_acts` in jurisdictions.jsonl). All
  other instrument types (Peraturan Bupati/Wali Kota, Keputusan, etc.)
  remain excluded everywhere, and all validation gates are unchanged.
"""
    (CAMP / "coverage_report.md").write_text(coverage, encoding="utf-8")

    readme = (CAMP / "README.md").read_text(encoding="utf-8")
    start = readme.index("> **⚠️")
    end = readme.index("## Channels")
    new_banner = (
        f"> **⚠️ CAMPAIGN IN PROGRESS.** This repo currently contains "
        f"**{n_units} of 514** kabupaten/kota, published 2026-10-13 (4-unit "
        f"validated pilot seed + tranches 1-4: known JDIH templates, "
        f"recovered swing hosts, a 174-host census with portal-family "
        f"adapters, and an OCR lane for scanned catalogs). Coverage will "
        f"keep growing unit by unit as the remaining harvestable hosts "
        f"are worked. Do not treat the current contents as complete or "
        f"representative coverage of Indonesian municipal law.\n\n")
    readme = readme[:start] + new_banner + readme[end:]
    readme = re.sub(r"- \*\*Coverage: \d+/514 units\.\*\*",
                    f"- **Coverage: {n_units}/514 units.**", readme)
    (CAMP / "README.md").write_text(readme, encoding="utf-8")

    for fname in ("README.md", "coverage_report.md", "jurisdictions.jsonl"):
        with_retries(lambda f=fname: api.upload_file(
            path_or_fileobj=str(CAMP / f), path_in_repo=f,
            repo_id=REPO_ID, repo_type="dataset",
            commit_message=f"Indonesia tranche 4: coverage metadata "
                           f"({n_units}/514 units, {tot_rows} rows)"))
        print("uploaded", fname, flush=True)
    files = with_retries(lambda: api.list_repo_files(REPO_ID, repo_type="dataset"))
    print("repo files:", len(files), flush=True)
    print("DONE", json.dumps({"published_now": [s["bps"] for s in published_now],
                              "total_units": n_units, "total_rows": tot_rows}))


if __name__ == "__main__":
    main()
