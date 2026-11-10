#!/usr/bin/env python3
"""Write README.md (federal README + subnational section) and subnational_manifest.json into the staging dir. No upload."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, sys, re
from pathlib import Path
STAGE = Path(open('{_CORPORA}/ca_subnational/last_stage_path.txt').read().strip())
meta = json.loads((STAGE / 'PACK_META.json').read_text()); chk = meta['never_thin']; per = chk['post']['per_jurisdiction']
blocked = json.load(open('{_CORPORA}/ca_subnational/blocked.json'))
NAMES = {'CA-ON': 'Ontario', 'CA-QC': 'Québec', 'CA-BC': 'British Columbia', 'CA-AB': 'Alberta', 'CA-MB': 'Manitoba', 'CA-SK': 'Saskatchewan', 'CA-NS': 'Nova Scotia',
         'CA-NB': 'New Brunswick', 'CA-NL': 'Newfoundland and Labrador', 'CA-PE': 'Prince Edward Island', 'CA-YT': 'Yukon', 'CA-NT': 'Northwest Territories', 'CA-NU': 'Nunavut'}
SRC = {'CA-ON': 'e-Laws, ontario.ca/laws (JSON/HTML API)', 'CA-MB': 'Manitoba Laws, web2.gov.mb.ca/laws (HTML, English column)', 'CA-SK': 'Freelaw, publications.saskatchewan.ca (PDF)',
       'CA-NS': 'nslegislature.ca consolidated statutes (HTML) + novascotia.ca Registry of Regulations (HTML)', 'CA-NB': 'laws.gnb.ca (HTML)',
       'CA-NT': 'justice.gov.nt.ca legislation (bilingual PDF, English column)', 'CA-NU': 'nunavutlegislation.ca current consolidations (PDF)'}
LICN = {
 'CA-ON': "Open reuse including commercial: the King's Printer for Ontario permits reproduction without permission or charge if reproduced accurately, attributed ('\u00a9 King's Printer for Ontario, <year>') and marked as **not an official version** (https://www.ontario.ca/page/copyright-information).",
 'CA-NS': "**Non-commercial only.** Reproduction for non-commercial purposes if accurate and attributed; commercial use needs permission (https://nslegislature.ca/legal/copyright). Electronic versions state they are for personal use and may not be copied for resale.",
 'CA-NB': "**Non-commercial only.** Non-commercial reproduction permitted without permission if accurate and the source is identified; commercial redistribution needs the King's/Queen's Printer's written permission.",
 'CA-NT': "**Non-commercial only.** Non-commercial reproduction permitted if accurate and the GNWT is acknowledged; commercial reproduction needs consent. Consolidations are unofficial.",
 'CA-NU': "**Personal use; no resale without consent** of the Territorial Printer. Some consolidations are unofficial and flagged by the source as not up to date.",
}
fed = per['CA']
rows = []
for j in [k for k in NAMES if k in per]:
    p = per[j]
    rows.append(f"| {j} | {NAMES[j]} | {p.get('statute_laws',0):,} | {p.get('statute_articles',0):,} | {p.get('regulation_laws',0):,} | {p.get('regulation_articles',0):,} | {p['laws']:,} | {p['articles']:,} | {SRC[j]} |")
tot_l = sum(per[j]['laws'] for j in per if j != 'CA'); tot_a = sum(per[j]['articles'] for j in per if j != 'CA')
bl = '\n'.join(f"| {b['jurisdiction']} | {NAMES.get(b['jurisdiction'], b['jurisdiction'])} | {b['status']} | {b['reason']} |" for b in blocked)
fedr = (STAGE / 'README.md').read_text()
fedr = fedr.replace('pretty_name: Canada In-Force Federal Legislation (Justice Laws XML)', 'pretty_name: Canada In-Force Legislation (federal Justice Laws XML + provincial/territorial consolidations)')
fedr = fedr.replace('- Provincial and territorial legislation is **not** included.\n', '- Provincial/territorial coverage is partial; see *Provincial and territorial legislation* above and *Known limitations* below.\n')
fedr = re.sub(r'size_categories:\n- [^\n]+', 'size_categories:\n- 100K<n<1M' if fed['articles'] + tot_a < 1_000_000 else 'size_categories:\n- 1M<n<10M', fedr)
sub = f"""
## Provincial and territorial legislation (appended)

Rows with `jurisdiction` = `CA-<PROV>` are **appended after** the unchanged federal rows (`jurisdiction` = `CA`).
Federal rows, fields and ids are identical to base tip `{meta['base_tip'][:12]}` (never-thin check: {'PASS' if chk['PASS'] else 'FAIL'}).
Provincial/territorial law ids are `ca-<prov>-<source-id>`; article ids are `<law_id>-s-<section>` (or `-sch-<n>` for schedules),
so they cannot collide with federal `ca-en-…`/`ca-fr-…` ids. `language` = `en` for all provincial/territorial rows
(English text only; for bilingual NT/NU PDFs only the English column was kept). `source_type` = `ca_<prov>_legislation`;
`metadata_json.document_type` is `statute` or `regulation`. Current consolidations only.

| Jurisdiction | Name | Statutes | Statute articles | Regulations | Regulation articles | Laws | Articles | Official source |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
{chr(10).join(rows)}
| **Total sub-national** | | | | | | **{tot_l:,}** | **{tot_a:,}** | |
| CA (federal, unchanged) | Canada | | | | | {fed['laws']:,} | {fed['articles']:,} | Justice Laws XML |

### Not collected (blocked / unavailable official sources)

| Jurisdiction | Name | Status | Evidence |
| --- | --- | --- | --- |
{bl}

## Known limitations

- **Licences differ by jurisdiction and are stricter than the federal SI/97-5 regime.** Per jurisdiction (also in each row's `license` field):
{chr(10).join(f'  - **{j}** ({NAMES[j]}): {LICN[j]}' for j in LICN if j in per)}
- **Manitoba (CA-MB) and Saskatchewan (CA-SK) were collected but are held out of this dataset** pending a licence decision
  (Manitoba: copies without permission only for study/research, legal proceedings or legal advice; Saskatchewan: reproduction on another
  website needs a written copyright release from the King's Printer). Their rows are not included here.
- Québec, British Columbia, Alberta, Prince Edward Island and Yukon are blocked at source or by robots.txt, and Newfoundland and Labrador was unavailable
  (see the table above). No CanLII, mirrors or bot-challenge workarounds were used.
- **English only.** All provincial/territorial rows have `language` = `en`; for bilingual NT/NU PDFs only the English column was kept.
- All provincial/territorial texts are **unofficial** reproductions of official-site consolidations; the official sites prevail. Not legal advice.
- Ontario: amendments not yet in force (e-Laws `Y*` paragraphs) are excluded so rows reflect in-force text; numbered paragraphs inside
  schedules/agreements are stored as schedule articles. The e-Laws search reported 857 current statutes; 856 unique current statutes were listed and collected.
- Nova Scotia: regulations with no numbered sections (orders in council, park/beach designations, protected-area orders) are stored as full text
  with 0 articles. One listed regulation (`reg-sppghostantler`, Ghost Antler Nature Reserve) returned HTTP 404 and is missing.
  The consolidation currency date is not exposed on NS pages, so `date` is null for NS rows.
- Northwest Territories and Nunavut texts come from PDF (pdftotext). Section splitting is heuristic (line-start numbering with a monotonic filter);
  marginal notes are interleaved with the body text, tables/forms may be flattened, and some French fragments may remain in bilingual forms.
- Nunavut: one listed instrument (`nunavut-criminal-code-review-board-establishment`) is a scanned PDF with no text layer and is missing.
  Several consolidations are flagged by the source as *not up to date* (see `metadata_json.metadata.official_metadata.note`).
- Laws with 0 articles keep their full text on the law row (as for federal SI/orders).
"""
fedr = fedr.replace('## Known gaps', sub + '\n## Known gaps')
(STAGE / 'README.md').write_text(fedr)
man = {'base_tip': meta['base_tip'], 'append_order': meta['append_order'], 'per_jurisdiction': per, 'blocked': blocked,
       'licence_notes': LICN, 'subnational_laws_added': meta['subnational_laws_added'], 'subnational_articles_added': meta['subnational_articles_added'], 'uploaded': False}
(STAGE / 'subnational_manifest.json').write_text(json.dumps(man, indent=2, ensure_ascii=False))
print('README + manifest written to', STAGE)
