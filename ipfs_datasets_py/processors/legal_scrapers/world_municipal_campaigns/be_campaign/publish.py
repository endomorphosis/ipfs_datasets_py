"""Flanders campaign tranche 1 — publish validated gemeente parquets to
endomorphosis/ipfs_belgium_municipal_laws (Portugal layout)."""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

CAMP = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files/be_campaign"
REPO = "endomorphosis/ipfs_belgium_municipal_laws"
RETRIEVED = "2026-10-12"

state = json.load(open(CAMP / "campaign_state.json"))
cw = json.load(open(CAMP / "crosswalk.json"))
inv = json.load(open(CAMP / "inventory.json"))

entry = dynamic_credential_entry("custom.huggingface")
token = entry.get("surrogate") if isinstance(entry, dict) else None
if not token:
    raise RuntimeError("dynamic_credential_entry returned no surrogate")

from huggingface_hub import HfApi  # noqa: E402
api = HfApi(token=token)

try:
    info = api.dataset_info(REPO)
    existing = {s.rfilename for s in info.siblings or []}
    print(f"dataset exists: {len(existing)} files")
except Exception as e:  # noqa: BLE001
    print("dataset_info failed (creating):", type(e).__name__, str(e)[:100])
    api.create_repo(REPO, repo_type="dataset", private=False)
    existing = set()

todo = {nis: st for nis, st in state["gemeenten"].items()
        if st.get("validation") == "pass" and not st.get("published")}
print("to publish:", list(todo))

for nis, st in sorted(todo.items()):
    path_in_repo = f"data/{nis}_html.parquet"
    if path_in_repo in existing:
        print(f"{nis}: already on HF, marking published")
    else:
        api.upload_file(path_or_fileobj=str(CAMP / "parquets" / f"{nis}_html.parquet"),
                        path_in_repo=path_in_repo, repo_id=REPO, repo_type="dataset",
                        commit_message=f"Add {st['name']} ({nis}) municipal regulations — Flanders tranche 1")
        print(f"{nis}: uploaded {path_in_repo}")
    st["published"] = True
    st["hf_path"] = path_in_repo
json.dump(state, open(CAMP / "campaign_state.json", "w"), indent=2, ensure_ascii=False)

# ---------- jurisdictions.jsonl (full 285-gemeente crosswalk) ----------
jur_lines = []
for g in cw["gemeenten"]:
    jur_lines.append(json.dumps({
        "jurisdiction_id": g["nis"], "name": g["name"], "country": "BE",
        "province": g["province"], "nis_code": g["nis"],
        "lblod_eenheid_uri": g["lblod_eenheid_uri"],
    }, ensure_ascii=False))
(CAMP / "jurisdictions.jsonl").write_text("\n".join(jur_lines) + "\n")

# ---------- coverage report ----------
pub = {nis: st for nis, st in state["gemeenten"].items() if st.get("published")}
tot_b = sum(st["harvested"] for st in pub.values())
tot_rows = sum(st["rows"] for st in pub.values())
lines = [
    "# Coverage report — Belgium (Flanders) municipal laws, tranche 1",
    "",
    f"Retrieved {RETRIEVED} from the LBLOD Centrale Vindplaats register "
    "(https://centrale-vindplaats.lblod.info/sparql) and the municipalities' "
    "Gelinkt Notuleren publication environments "
    "(publicatie.gelinkt-notuleren.vlaanderen.be). Both sources are published "
    "as open data by the Flemish government (robots.txt fully permissive).",
    "",
    "## Denominator",
    "",
    "Flanders has **285 gemeenten** since the municipal fusions of 1 January 2025. "
    "The full crosswalk (NIS code ↔ name ↔ LBLOD bestuurseenheid) is in "
    "`jurisdictions.jsonl`: NIS codes from Statbel's REFNIS-2025 codelist "
    "(published as linked data by belgif, CC BY 4.0), arbitrated against the "
    "Flemish Base Register (gemeente register, status `inGebruik` = 285). "
    "All 285 gemeenten joined exactly to an LBLOD bestuurseenheid. Two REFNIS "
    "concepts are not current gemeenten and are excluded: Sint-Amands (12034, "
    "fused into Puurs-Sint-Amands in 2019) and Moerbeke (44045, fused into "
    "Lokeren in 2025).",
    "",
    "## What the register holds",
    "",
    "Within the campaign's reglement scope (the 17 regulation BesluitTypes of the "
    "LBLOD BesluitType scheme), the register holds 990 distinct besluiten: 934 "
    "attributable to 6 gemeenten and 56 attributable to provinces (Limburg, "
    "Vlaams-Brabant) — provincial regulations are out of scope for this dataset. "
    "The other 279 gemeenten have no reglement-type besluiten in the register: "
    "LBLOD coverage depends on each gemeente publishing via Gelinkt Notuleren, "
    "and most gemeenten's regulations are not (yet) in the register. That is a "
    "documented coverage finding, not a harvest failure.",
    "",
    f"## Published in this tranche: {len(pub)} gemeenten, {tot_b} besluiten, {tot_rows} rows",
    "",
    "| NIS | Gemeente | Besluiten (inline / template route) | Rows | Notes |",
    "|---|---|---|---|---|",
]
for nis, st in sorted(pub.items()):
    fails = st.get("failed", [])
    n_in_ok = st["inline_besluiten"] - sum(1 for f in fails if f.get("route") == "inline")
    n_tpl_ok = st["stub_besluiten"] - sum(1 for f in fails if f.get("route") == "template")
    notes = ""
    if fails:
        notes = f"{len(fails)} besluit(en) without published full text (see report)"
    lines.append(f"| {nis} | {st['name']} | {n_in_ok} / {n_tpl_ok} | {st['rows']} | {notes} |")
lines += [
    "",
    "Inline = full text carried in the register itself (prov:value / eli:has_part "
    "articles). Template route = full text extracted from the gemeente's Gelinkt "
    "Notuleren publication pages (uittreksel documents), matched to the register "
    "besluit by its RDFa resource URI.",
    "",
    "## Remaining work",
    "",
    "- The register's remaining ~34,600 non-reglement besluiten (other BesluitTypes) "
    "and any reglement besluiten published after this tranche.",
    "- Gemeenten whose regulations live outside LBLOD (their own publication "
    "systems) are not covered by this route.",
]
(CAMP / "coverage_report.md").write_text("\n".join(lines) + "\n")

# ---------- README (dataset card) ----------
readme = f"""---
license: other
language:
- nl
pretty_name: Belgium Municipal Laws (Flanders)
tags:
- law
- legal
- belgium
- flanders
- municipal
- open-data
---

# Belgium Municipal Laws — Flanders (LBLOD)

Municipal regulations (*reglementen*) of Flemish *gemeenten*, harvested from
**LBLOD** (Lokale Besluiten als Gelinkt Open Data), the Flemish government's
central register of local-government decisions, and from the municipalities'
**Gelinkt Notuleren** publication environments. Normalized with the
`world_municipal` library from
[endomorphosis/legal_scrapers](https://huggingface.co/datasets/endomorphosis/legal_scrapers)
into the shared 19-column schema used across the world municipal-law program
(one row per article/section; `html` + plain `text`).

## Coverage (tranche 1, {RETRIEVED})

- **{len(pub)} of 285 gemeenten** published — every gemeente that has
  reglement-type besluiten in the LBLOD register: {", ".join(f"{st['name']} ({nis})" for nis, st in sorted(pub.items()))}.
- **{tot_b} besluiten, {tot_rows} rows.** See `coverage_report.md` for the full
  accounting, including why the other 279 gemeenten have no register content
  (they do not publish regulations via LBLOD/Gelinkt Notuleren).
- `jurisdictions.jsonl` lists all 285 Flemish gemeenten with Statbel NIS codes
  and their LBLOD bestuurseenheid URIs, including the 279 without register
  content in this tranche.

## Files

- `data/<nis>_html.parquet` — one file per gemeente (NIS = Statbel municipality code).
- `jurisdictions.jsonl` — the full gemeente crosswalk.
- `coverage_report.md` — coverage accounting and method notes.

## Sources & attribution

- LBLOD Centrale Vindplaats (Agentschap Informatie Vlaanderen / Digitaal
  Vlaanderen): https://centrale-vindplaats.lblod.info — linked open data.
- Gelinkt Notuleren publication environments:
  https://publicatie.gelinkt-notuleren.vlaanderen.be
- NIS codes: Statbel REFNIS-2025 codelist (CC BY 4.0), cross-checked against
  the Flemish Base Register (basisregisters).
"""
(CAMP / "README.md").write_text(readme)

for fname in ["README.md", "coverage_report.md", "jurisdictions.jsonl"]:
    if fname in existing and not os.environ.get("BE_FORCE_ROOT"):
        print(f"{fname}: exists, skipping (no overwrite)")
        continue
    api.upload_file(path_or_fileobj=str(CAMP / fname), path_in_repo=fname,
                    repo_id=REPO, repo_type="dataset",
                    commit_message=f"Flanders tranche 1: {fname}")
    print(f"uploaded {fname}")

# ---------- remote verification ----------
info = api.dataset_info(REPO, files_metadata=True)
remote = {s.rfilename: s.size for s in info.siblings or []}
expected = {f"data/{nis}_html.parquet" for nis in pub} | {"README.md", "coverage_report.md", "jurisdictions.jsonl"}
missing = expected - set(remote)
print("remote files:", len(remote), "| missing:", missing or "none")
import pyarrow.parquet as pq
for nis in sorted(pub):
    local_n = pq.read_metadata(CAMP / "parquets" / f"{nis}_html.parquet").num_rows
    print(f"  {nis} local rows {local_n} (remote size {remote.get(f'data/{nis}_html.parquet')})")
print("PUBLISH DONE")
