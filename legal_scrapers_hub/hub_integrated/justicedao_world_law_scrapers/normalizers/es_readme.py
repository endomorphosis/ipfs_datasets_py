#!/usr/bin/env python3
"""Write README.md for the staged ipfs_spain_laws + ES-<CCAA> append (reads PACK_META.json)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json
from pathlib import Path
B = Path('{_CORPORA}/es_subnational'); STAGE = Path(open(B / 'last_stage_path.txt').read().strip())
meta = json.loads((STAGE / 'PACK_META.json').read_text()); chk = meta['never_thin']; post = chk['post']; per = post['per_jurisdiction']
gap = json.load(open(B / 'gap_quant.json')) if (B / 'gap_quant.json').exists() else {}
NAMES = {'ES': 'Spain — state (estatal)', 'ES-AN': 'Andalucía', 'ES-AR': 'Aragón', 'ES-AS': 'Principado de Asturias', 'ES-IB': 'Illes Balears', 'ES-CN': 'Canarias',
         'ES-CB': 'Cantabria', 'ES-CL': 'Castilla y León', 'ES-CM': 'Castilla-La Mancha', 'ES-CT': 'Cataluña', 'ES-EX': 'Extremadura', 'ES-GA': 'Galicia',
         'ES-MD': 'Comunidad de Madrid', 'ES-MC': 'Región de Murcia', 'ES-NC': 'Comunidad Foral de Navarra', 'ES-PV': 'País Vasco', 'ES-RI': 'La Rioja',
         'ES-VC': 'Comunitat Valenciana', 'ES-CE': 'Ceuta', 'ES-ML': 'Melilla'}
ORDER = ['ES'] + meta['append_order']
gp = gap.get('per_jurisdiction', {})
gap_rows = '\n'.join(f"  | `{j}` | {gp[j]['consolidated_laws']:,} | {gp[j]['est_missing_in_sequence']:,} | {gp[j]['est_coverage_pct']}% |" for j in meta['append_order'] if j in gp)
gap_tot_c = gap['totals']['consolidated_numbered_laws']; gap_tot_m = gap['totals']['est_missing_in_sequence']; gap_tot_p = gap['totals']['est_coverage_pct']
L = chk['laws']['new_rows']; A = chk['articles']['new_rows']
rows = []
for j in ORDER:
    p = per.get(j)
    if not p: rows.append(f'| `{j}` | {NAMES[j]} | 0 | 0 | — | — | — | not in BOE consolidated autonómico (see Known limitations) |'); continue
    rows.append(f"| `{j}` | {NAMES[j]} | {p['laws']:,} | {p['articles']:,} | {p.get('current_laws',0):,} | {p.get('repealed_laws',0):,} | {p.get('historical_laws',0):,} | {'existing rows, unchanged' if j=='ES' else 'appended'} |")
sub_l = L - chk['laws']['old_rows']; sub_a = A - chk['articles']['old_rows']
yaml = f"""---
pretty_name: Spanish State and Autonomous Community Law Corpus (BOE)
license: other
license_name: aeboe-reuse-attribution
language:
- es
task_categories:
- text-retrieval
tags:
- legal
- law
- spain
- boe
- estatal
- autonomico
- comunidades-autonomas
- official-texts
size_categories:
- 100K<n<1M
configs:
- config_name: laws
  data_files: data/laws.parquet
  default: true
- config_name: articles
  data_files: data/articles.parquet
---
"""
body = f"""
# Spanish State and Autonomous Community Law Corpus (BOE)

Research snapshot of **Spanish state (estatal) legislation** plus **consolidated legislation of the autonomous communities**
(*legislación consolidada autonómica*), collected from the
[Boletín Oficial del Estado](https://www.boe.es/) (BOE) open-data API.

**Not legal advice.** The official gazettes prevail over this corpus. This snapshot is **not the official consolidada**:
every text is a *texto consolidado de carácter meramente informativo*.

## Snapshot

| Field | Value |
| --- | --- |
| State snapshot date | 2026-09-02 (rows unchanged) |
| Autonomous-community append | {meta['staged_at'][:10]} |
| Source | BOE open data, `legislacion-consolidada` (ámbito Estatal + Autonómico) |
| Collectors | `scrapers/collect_boe.py` (estatal), `scrapers/es_collect.py` + `scrapers/es_build.py` (autonómico) |
| Laws | {L:,} (estatal {chk['laws']['old_rows']:,} + autonómico {sub_l:,}) |
| Blocks (articles table) | {A:,} (estatal {chk['articles']['old_rows']:,} + autonómico {sub_a:,}) |
| Language | Spanish (`es`) |
| Jurisdiction | `ES` (state) and `ES-<CCAA>` (ISO 3166-2) |

## Contents

- `data/laws.parquet` — one row per instrument. State rows come first and are unchanged; autonomous-community rows are appended
  ordered by jurisdiction, then `date_issued`, then BOE identifier.
- `data/articles.parquet` — text blocks (artículos, disposiciones, preámbulo, firma, anexos, headings), one row per current consolidated block.
- `scrapers/` — collectors used to build this snapshot.
- `PACK_META.json` — build/append metadata and never-thin check results.

## Jurisdictions

| jurisdiction | Name | Laws | Blocks | current | repealed | historical (vigencia agotada) | Note |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
{chr(10).join(rows)}

Autonomous-community rows use `id = '<ES-CCAA>-<BOE identifier>'` (e.g. `ES-CT-BOE-A-1997-9499`), so they cannot collide with the
state rows (whose `id` is the bare BOE identifier); `official_identifier` keeps the bare BOE/regional-gazette identifier and
`metadata_json.metadata` adds `jurisdiction_iso_3166_2`, `departamento_codigo`, `ambito_codigo` and `rango_codigo`.
Article ids are `<law id>/<BOE block id>`. Row construction (law text with the informative notice, current version of each block,
`law_status` from `estatus_derogacion` / `vigencia_agotada`) is identical to the state rows.

## License / reuse

Only one source is used for every row: the **AEBOE** (Agencia Estatal Boletín Oficial del Estado) open-data API. Reuse follows
the AEBOE general reuse conditions (*licencia tipo*, Resolución de 27 de junio de 2024, in force since 28 June 2024),
https://www.boe.es/informacion/aviso_legal/index.php :

- commercial and non-commercial reuse is permitted (copy, distribute, modify, combine, create derived products);
- cite the source with a link to https://www.boe.es — "Fuente de los datos: Agencia Estatal Boletín Oficial del Estado" for copies,
  or "Basado en datos de la Agencia Estatal Boletín Oficial del Estado" for modified/derived works;
- do not distort the meaning; do not suggest official character — **each consolidated text must state that it is a texto consolidado
  de carácter meramente informativo** (every `text` in `laws.parquet` starts with that notice);
- do not suggest AEBOE participation, sponsorship or endorsement; mention the last-update date (kept in
  `metadata_json.metadata.fecha_actualizacion`); identify modifications as such; keep the update-date and reuse-condition metadata;
- respect GDPR / LOPDGDD for any personal data.

**Autonomous-community portals and gazettes:** none were used (no CCAA portal terms therefore apply to this dataset). The texts of
autonomous-community laws reproduced here are BOE's informative consolidations; the authentic text is the one published in each
community's official gazette (BOJA, BOA, BOPA, BOIB, BOC, BOC(antabria), BOCYL, DOCM, DOGC, DOE, DOG, BOCM, BORM, BON, BOPV, BOR, DOGV),
which determines legal effect (see the AEBOE notice that BOE consolidations of autonomic laws are prepared after BOE publication,
which always follows publication in the regional gazette).

This dataset is **not legal advice**. The official gazettes prevail.

## Known limitations

- **Scope = BOE consolidated autonómico only.** BOE consolidates the *main* autonomous-community norms with rank of law
  (leyes, leyes forales, decretos legislativos, decretos-leyes, plus a few resoluciones/acuerdos): {sub_l:,} instruments listed by the API
  under `ambito@codigo:2`, all collected. Autonomous-community **regulations** (decretos, órdenes) are not consolidated by BOE and are not
  included. Not every regional law has a BOE consolidated version{(': ' + gap['summary']) if gap.get('summary') else ''}.
  Many of the unconsolidated numbers are expected to be amending, budget (*presupuestos*) and accompanying-measures laws whose
  provisions are already merged into the consolidated texts of the laws they amend, so this is not a measure of missing in-force
  content; laws not consolidated by BOE would have to come from the official CCAA portals (not used in this snapshot).
- **Coverage gap table** (offline estimate from Ley / Ley Foral numbering N/YYYY per community and year among BOE-consolidated laws;
  "missing in sequence" = numbers in 1..max(N) with no BOE consolidated version; lower bound, and many are amending/budget laws already merged into consolidated texts):

  | jurisdiction | Consolidated numbered laws | Est. missing in sequence | Est. coverage |
  | --- | ---: | ---: | ---: |
{gap_rows}
  | **total** | **{gap_tot_c:,}** | **{gap_tot_m:,}** | **{gap_tot_p}%** |
  | `ES-CE` / `ES-ML` | 0 | — | n/a (no legislative power) |

- **BOE consolidations of autonomic norms only reflect amendments made by norms with rank of law** (not by regional regulations),
  only express (not tacit) amendments/repeals, and are prepared after the amendment appears in BOE, so they can lag the regional gazette.
  `estado_consolidacion = 'Desactualizado'` marks texts whose newest amendment is still being incorporated
  ({gap.get('desactualizado', '?')} autonomic texts at collection time).
- **Ceuta (ES-CE) and Melilla (ES-ML): 0 rows.** They are autonomous cities without legislative power (no regional laws); BOE's
  consolidated autonómico set contains no instrument for them. Their Statutes of Autonomy (Ley Orgánica 1/1995 and 2/1995) are state
  organic laws and are already present as `ES` rows, as are all other Statutes of Autonomy and their reforms.
- **Spanish only.** Texts are BOE's Spanish versions; co-official-language versions (català/valencià, galego, euskara, aranés) are not included.
- **Dedupe vs state rows:** 0 overlap — none of the autonomic identifiers, ELIs or titles exist among the state rows, so nothing was
  double-inserted.
- **Historical/repealed texts are included** (as for the state rows) and flagged by `law_status` (`current` / `repealed` /
  `historical` = vigencia agotada); filter on `law_status == 'current'` for in-force law.
- {sum(v.get('zero_article_laws',0) for k,v in per.items() if k!='ES')} autonomic laws have 0 blocks;
  {sum(v.get('body_under_200_chars_excl_notice',0) for k,v in per.items() if k!='ES')} have under 200 characters of body text after the informative notice (see `country-law-triage` checks).
- 245 autonomic instruments are keyed by regional-gazette identifiers (e.g. `BOJA-b-…`, `DOGC-f-…`, `BOIB-i-…`) rather than `BOE-A-…`,
  because BOE consolidates them from the regional publication; exactly these 245 have no ELI in the BOE metadata (`eli` is null).
- No duplicate ids: 0 duplicate law or article ids before or after the append ({chk['articles']['duplicate_ids_before']} pre-existing article-id duplicates in the state rows; 0 new). Block ids are BOE's own (`a1`, `dtprimera`, `a9-4` for articles inside annexed texts, …).
- {sum(v.get('empty_article_texts',0) for k,v in per.items() if k!='ES')} autonomic block rows have empty text (BOE block with an empty current version), as with the 3 such rows among the state rows.

## Source

- Portal: https://www.boe.es/
- API: https://www.boe.es/datosabiertos/api/legislacion-consolidada (docs: https://www.boe.es/datosabiertos/documentos/APIconsolidada.pdf)
- Publisher: Agencia Estatal Boletín Oficial del Estado (AEBOE)
- robots.txt of www.boe.es checked for every API URL before fetching (0 disallowed); 0 HTTP 403s.
"""
(STAGE / 'README.md').write_text(yaml + body, encoding='utf-8'); print('README written', STAGE / 'README.md')
