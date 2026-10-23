"""Mexico tranche 2 — publish additively to
endomorphosis/ipfs_mexico_municipal_laws.

Adapted from the tranche-1 publisher: uploads ONLY the tranche-2
municipios (pilot + tranche-1 files already on HF are skipped, never
clashed), regenerates README.md + coverage_report.md from the COMBINED
pilot+tranche1+tranche2 manifests, and remote-verifies EVERY parquet in
the dataset (re-download + validate_table + row counts).
Auth: vault connector surrogate via dynamic_credentials (never persisted).
"""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
sys.path.insert(0, "/opt/hatch/workflow-skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE.parent                       # mx_tranche2/
T1 = OUT.parent / "mx_tranche1"
PILOT = OUT.parent / "mx_pilot"
REPO = "endomorphosis/ipfs_mexico_municipal_laws"
RETRIEVED = "2026-10-14"


def valid_munis(path: Path) -> dict:
    m = json.loads((path / "run_manifest.json").read_text())
    return {k: v for k, v in m["municipios"].items() if v.get("valid")}


pilot_munis = valid_munis(PILOT)
t1_munis = valid_munis(T1)
new_munis = valid_munis(OUT)
assert not (set(pilot_munis) & set(new_munis)), "t2 overlaps pilot"
assert not (set(t1_munis) & set(new_munis)), "t2 overlaps tranche 1"
assert not (set(pilot_munis) & set(t1_munis)), "t1 overlaps pilot"
munis = {**pilot_munis, **t1_munis, **new_munis}
assert len(new_munis) >= 1, "no valid tranche-2 municipios — refusing to publish"
total_rows = sum(v["rows"] for v in munis.values())
total_docs = sum(len([d for d in v["docs"] if d.get("units")]) for v in munis.values())
states = sorted({v["state"] for v in munis.values()})
print(f"combined: {len(munis)} municipios ({len(new_munis)} new in t2), "
      f"{total_docs} docs, {total_rows} rows, {len(states)} states")

entry = dynamic_credential_entry("custom.huggingface")
# This environment's helper returns an hsurr:* surrogate (authd swaps it for
# the real credential on approved outbound requests); use it as the bearer.
token = entry["surrogate"]
if not token:
    raise RuntimeError("no HF surrogate credential")

from huggingface_hub import HfApi  # noqa: E402
api = HfApi(token=token)

info = api.dataset_info(REPO, files_metadata=True)
existing = {s.rfilename for s in info.siblings or []}
print(f"dataset exists: {len(existing)} files")

rows_tbl = "\n".join(
    f"| {c} | {v['name']} | {v['state']} | {v['platform']} | "
    f"{len([d for d in v['docs'] if d.get('units')])} | {v['rows']} |"
    for c, v in sorted(munis.items()))

coverage = f"""# Coverage report — Mexico municipal laws (pilot seed + tranches 1-2)

Retrieved {RETRIEVED} from the municipios' own official portals.
**Status: growing seed, not full coverage.** Mexico has
**2,475 demarcaciones** in the INEGI Catalogo Unico de Claves de Areas
Geoestadisticas (AGEEML, export 2026-09-01): 2,459 municipios plus the
16 alcaldias of Ciudad de Mexico. The full registry ships in
`jurisdictions.jsonl`.

Jurisdiction IDs are the INEGI clave geoestadistica (5 digits: 2-digit
entidad federativa 01-32 + 3-digit municipio), registered in the
program as `InegiMunicipioScheme`.

## Coverage — {len(munis)} of 2,475 municipios, {total_docs} documents, {total_rows} rows

| INEGI | Municipio | State | Route | Docs | Rows |
|---|---|---|---|---|---|
{rows_tbl}

## Route

No single national collection of Mexican municipal reglamentos exists
with full text. The route is the municipios' own **compiled
publication**: most sizeable ayuntamientos post their vigente
reglamentos/bandos as full-text PDFs on their official portals (marco
normativo / transparencia / normatividad sections), structured by
articulo, which maps cleanly onto the program's article-level rows.
Texts were extracted from the official PDFs (PyMuPDF -> pdfplumber ->
pdftotext) and normalized to the program's 19-column schema, one row
per articulo. Tranche 1 covers the next-largest municipios after the
pilot by INEGI population, state capitals first. Tranche 2 works the
next population tier (Tier B), reusing tranche 1's high-yield
patterns: Gaceta Municipal issues carrying complete texts, compilation
bundles and promulgation-decree directories, and numbered-file
directories. One route extension: Tonala (14101) publishes its
compiled reglamentos as DOCX on its own transparencia portal; those
were converted to PDF (LibreOffice headless) and run through the
identical pipeline, with the DOCX as the recorded source.

Dead ends (documented, not forced):
- **Merida, Yucatan (31050)** — pilot: the normatividad file tree on
  isla.merida.gob.mx served the portal SPA shell for every path.
  Tranche-1 retry: the Reglamento de Construcciones PDF path now
  returns 404. Still unreachable from this network.
- **Connection-stalled portals** — official compiled PDFs are
  search-indexed, but the hosts stall or refuse connections from the
  harvesting egress (post-TLS / proxy CONNECT), persistently across
  two harvest passes and two HTTP clients (curl, requests):
  Aguascalientes (01001), Hermosillo (26030), San Luis Potosi (24028),
  Benito Juarez/Cancun (23005), Toluca (15106), Morelia (16053),
  Durango (10005), Centro/Villahermosa (27004) and Queretaro (22014 —
  one reglamento was fetched and verified in a probe window, then the
  host closed). Retry from another network or a later window.
  (Tranche-2 end-of-run probes found Leon (11020) and Mexicali (02002)
  answering again; both were harvested into tranche 2. The other nine
  stalled hosts still refuse this egress.)
- **Saltillo (05030)** — the transparency portal serves reglamentos
  only through an opaque file viewer (no indexable compiled Bando
  PDF); the Gaceta carries reform diffs only.
- **Reynosa (28032)** — no compiled reglamentos on the municipal
  portal; only the state Periodico Oficial compendium lists them.
- **Tranche-2 egress-blocked portals (URLs banked, retry from a fresh
  network window)**: Victoria, Tamaulipas (28041 — compiled
  Reglamento de Justicia Civica located on ciudadvictoria.gob.mx,
  host unreachable all session) and Zamora, Michoacan (16108 —
  Gaceta Municipal No. 2 carrying the Bando de Gobierno located on
  zamora.gob.mx, host unreachable all session). Celaya's Bando
  (11007) sits on the Guanajuato state normatividad host, which
  drops this egress after TLS; Celaya is published with its
  Reglamento de Administracion (the municipio's own marco normativo
  page links it as a public Google Docs export).
- **Colima (06002)** — the compiled Reglamento del Gobierno
  Municipal sits under the old portal2016 tree of colima.gob.mx,
  whose robots.txt Disallow: /portal prefix covers that path;
  excluded on robots grounds. The current ayuntamiento portal was
  unreachable from this egress.
- **Coatzacoalcos (30039)** — main portal egress-blocked; the
  transparencia WordPress is reachable but its marco normativo
  (Ley 875 art. 15 fraccion I) is not exposed in its indexes or API.
- **Poza Rica (30131)** — every host variant unreachable from this
  egress.
- **Tampico (28038)** — tampico.gob.mx answers 403 to this egress;
  its reglamentos are otherwise only in the state Periodico Oficial
  index. **Matamoros (28022)** and **Nuevo Laredo (28027)** —
  portals unreachable or JS shells; texts located only in the state
  Periodico Oficial (same posture as Reynosa: not harvested).
- **Puerto Vallarta (14067)** — transparencia gacetas are scanned
  image issues; the /archivo/<id> viewer endpoints are not
  enumerable from this network.
- **La Paz (03003)**, **San Juan del Rio (22016)**, **Los Cabos
  (03008)** — portals load intermittently then stall under repeated
  probing from this egress; marco-normativo pages located but not
  yet harvested. Queued for a later window.
- Partial: Nezahualcoyotl's Turismo reglamento link 404s (Bando +
  Proteccion Civil included); Torreon's current Bando is not in the
  numbered normatividad series located (Organico + Turismo
  included); Queretaro's Codigo Municipal sits behind the SIMCOD web
  app (one paramunicipal reglamento verified in the probe window is
  queued behind the same connection block).

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

**Pilot seed + tranches 1-2** — {len(munis)} of 2,475 municipios in
{len(states)} states, {total_docs} documents, {total_rows} rows. See
`coverage_report.md` for exactly what is and is not covered, and why.

Primary legal texts are public legal information published by the
municipios. Dataset compilation is a research artifact; always verify
against the official source before relying on a text. Not legal advice.
"""

cov_path = OUT / "coverage_report.md"
cov_path.write_text(coverage)
(OUT / "README.md").write_text(readme)

uploads = [(cov_path, "coverage_report.md"), (OUT / "README.md", "README.md")]
for c in sorted(new_munis):
    uploads.append((OUT / "data" / f"{c}_html.parquet", f"data/{c}_html.parquet"))
    uploads.append((OUT / "data" / f"{c}_validation.json", f"data/{c}_validation.json"))
for s in ("mx_build_t2.py", "mx_publish_t2.py"):
    uploads.append((HERE / s, f"scrapers/{s}"))

uploaded = []
for local, remote in uploads:
    if remote in existing and remote.startswith("data/"):
        print("SKIP (already on HF)", remote, flush=True)
        continue
    api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                    repo_id=REPO, repo_type="dataset",
                    commit_message=f"MX tranche 2: {remote}")
    uploaded.append(remote)
    print("uploaded", remote, flush=True)

# ---- remote verification: every parquet in the dataset ----
info = api.dataset_info(REPO, files_metadata=True)
remote = {s.rfilename: s.size for s in info.siblings or []}
print(f"remote files: {len(remote)}")
bad = []
for local, remote_path in uploads:
    if remote_path not in remote:
        bad.append((remote_path, "missing"))
    elif remote_path.startswith("data/") and remote[remote_path] != local.stat().st_size:
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
    src = PILOT if c in pilot_munis else (T1 if c in t1_munis else OUT)
    local_rows = munis[c]["rows"]
    verify[c] = {"remote_rows": t.num_rows, "local_rows": local_rows, "errors": errs}
    print("verify", c, verify[c], flush=True)
assert all(v["remote_rows"] == v["local_rows"] and not v["errors"] for v in verify.values())
assert not bad
(OUT / "publish_result.json").write_text(json.dumps(
    {"repo": REPO, "files": sorted(remote), "uploaded": uploaded,
     "total_rows": sum(v["remote_rows"] for v in verify.values()),
     "verify": verify}, indent=1))
print("PUBLISH + REMOTE VERIFY OK:", json.dumps(
    {c: v["remote_rows"] for c, v in verify.items()}))
print(f"REMOTE TOTAL: {len(remote)} files, "
      f"{sum(v['remote_rows'] for v in verify.values())} rows")
