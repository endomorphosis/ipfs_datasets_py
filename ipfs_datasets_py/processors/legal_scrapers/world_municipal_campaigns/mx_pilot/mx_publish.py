"""Mexico pilot — publish validated seed to
endomorphosis/ipfs_mexico_municipal_laws (NZ/Portugal layout).
Additive: if the dataset already exists, upload only pilot files whose
names do not clash with what's there; never delete.
Auth: vault connector surrogate via dynamic_credentials (never persisted).
"""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

PILOT = Path(__file__).resolve().parent.parent
REPO = "endomorphosis/ipfs_mexico_municipal_laws"
RETRIEVED = "2026-10-14"

manifest = json.loads((PILOT / "run_manifest.json").read_text())
munis = {k: v for k, v in manifest["municipios"].items() if v.get("valid")}
assert munis, "no valid municipios — refusing to publish"
total_rows = sum(v["rows"] for v in munis.values())
total_docs = sum(len([d for d in v["docs"] if d.get("units")]) for v in munis.values())

entry = dynamic_credential_entry("custom.huggingface")
token = str(entry["surrogate"]).strip() if entry and entry.get("surrogate") else None
if not token:
    raise RuntimeError("no HF surrogate credential")

from huggingface_hub import HfApi  # noqa: E402
api = HfApi(token=token)

try:
    info = api.dataset_info(REPO, files_metadata=True)
    existing = {s.rfilename for s in info.siblings or []}
    print(f"dataset EXISTS: {len(existing)} files: {sorted(existing)[:20]}")
    clash = {f"data/{c}_html.parquet" for c in munis} & existing
    if clash:
        raise SystemExit(f"ABORT: name clash with existing files {clash} — additive-only pilot")
except SystemExit:
    raise
except Exception as e:  # noqa: BLE001
    print("dataset does not exist yet (creating):", type(e).__name__)
    api.create_repo(REPO, repo_type="dataset", private=False)
    existing = set()

rows_tbl = "\n".join(
    f"| {c} | {v['name']} | {v['state']} | {v['platform']} | "
    f"{len([d for d in v['docs'] if d.get('units')])} | {v['rows']} |"
    for c, v in sorted(munis.items()))

coverage = f"""# Coverage report — Mexico municipal laws (PILOT SEED)

Retrieved {RETRIEVED} from the municipios' own official portals.
**Pilot status: this is a seed, not full coverage.** Mexico has
**2,475 demarcaciones** in the INEGI Catalogo Unico de Claves de Areas
Geoestadisticas (AGEEML, export 2026-09-01): 2,459 municipios plus the
16 alcaldias of Ciudad de Mexico. The full registry ships in
`jurisdictions.jsonl`.

Jurisdiction IDs are the INEGI clave geoestadistica (5 digits: 2-digit
entidad federativa 01-32 + 3-digit municipio), registered in the
program as `InegiMunicipioScheme`.

## Pilot seed — {len(munis)} of 2,475 municipios, {total_docs} documents, {total_rows} rows

| INEGI | Municipio | State | Route | Docs | Rows |
|---|---|---|---|---|---|
{rows_tbl}

## Route

No single national collection of Mexican municipal reglamentos exists
with full text. The pilot route is the municipios' own **compiled
publication**: most sizeable ayuntamientos post their vigente
reglamentos/bandos as full-text PDFs on their official portals (marco
normativo / transparencia / normatividad sections), structured by
articulo, which maps cleanly onto the program's article-level rows.
Texts were extracted from the official PDFs (PyMuPDF → pdfplumber →
pdftotext) and normalized to the program's 19-column schema, one row
per articulo.

Dead ends from the pilot survey (documented, not forced):
- **Merida, Yucatan (31050)** — the normatividad file tree on
  isla.merida.gob.mx serves the portal SPA HTML for every path from
  the harvesting network (including the PDF href embedded in its own
  index page); the reglamentos exist (search-indexed) but are
  unreachable from here. Retry from another network in tranche 1.
- **Monterrey's Reglamento de Transito** — the copy linked from the
  portal homepage returns 404 (stale link); five other Monterrey
  reglamentos are included.
- Small municipios very often publish nothing online at all, or only
  via their state Periódico Oficial gazette (reform decrees, not
  compiled texts) — the scale plan is therefore tiered by municipio
  size; see the pilot report in the program workspace.

## Schema

19-column `world_municipal` schema (see the program's legal_scrapers
dataset): one row per article-level unit; `data/{{inegi}}_html.parquet`
per municipio plus a `{{inegi}}_validation.json` gate report.
"""

readme = f"""---
license: other
language:
- es
tags:
- law
- legal
- mexico
- municipal
- ipfs
---

# IPFS Mexico Municipal Laws

Structured corpus of Mexican municipal reglamentos and bandos,
normalized into the world municipal-law program's 19-column schema
(one row per article-level unit, one parquet per municipio,
jurisdiction IDs = INEGI claves geoestadisticas).

**Pilot seed** — {len(munis)} of 2,475 municipios, {total_docs} documents,
{total_rows} rows. See `coverage_report.md` for exactly what is and is
not covered, and why.

Primary legal texts are public legal information published by the
municipios. Dataset compilation is a research artifact; always verify
against the official source before relying on a text. Not legal advice.
"""

cov_path = PILOT / "coverage_report.md"
cov_path.write_text(coverage)
(PILOT / "README.md").write_text(readme)

uploads = [(cov_path, "coverage_report.md"), (PILOT / "README.md", "README.md"),
           (PILOT / "data" / "jurisdictions.jsonl", "jurisdictions.jsonl")]
for c in sorted(munis):
    uploads.append((PILOT / "data" / f"{c}_html.parquet", f"data/{c}_html.parquet"))
    uploads.append((PILOT / "data" / f"{c}_validation.json", f"data/{c}_validation.json"))
for s in ("mx_build.py", "probe.py", "build_registry.py"):
    uploads.append((PILOT / "scripts" / s, f"scrapers/{s}"))

for local, remote in uploads:
    api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                    repo_id=REPO, repo_type="dataset",
                    commit_message=f"MX pilot seed: {remote}")
    print("uploaded", remote, flush=True)

# ---- remote verification ----
info = api.dataset_info(REPO, files_metadata=True)
remote = {s.rfilename: s.size for s in info.siblings or []}
print(f"remote files: {len(remote)}")
bad = []
for local, remote_path in uploads:
    if remote_path not in remote:
        bad.append((remote_path, "missing"))
    elif remote[remote_path] != local.stat().st_size:
        bad.append((remote_path, f"size {remote[remote_path]} != {local.stat().st_size}"))
print("upload mismatches:", bad)

sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers"))
from huggingface_hub import hf_hub_download  # noqa: E402
from world_municipal.parquet_io import read_html_parquet  # noqa: E402
from world_municipal.schema import validate_table  # noqa: E402

reg = {}
for ln in (PILOT / "data" / "jurisdictions.jsonl").read_text().splitlines():
    r = json.loads(ln)
    reg[r["jurisdiction_id"]] = r["jurisdiction_name"]
verify = {}
for c in sorted(munis):
    p = hf_hub_download(REPO, f"data/{c}_html.parquet", repo_type="dataset", token=token)
    t = read_html_parquet(p)
    errs = validate_table(t, jurisdiction_id=c, jurisdiction_name=reg[c], country="MX")
    verify[c] = {"remote_rows": t.num_rows, "local_rows": munis[c]["rows"], "errors": errs}
    print("verify", c, verify[c], flush=True)
assert all(v["remote_rows"] == v["local_rows"] and not v["errors"] for v in verify.values())
assert not bad
print("PUBLISH + REMOTE VERIFY OK:", json.dumps(verify))
