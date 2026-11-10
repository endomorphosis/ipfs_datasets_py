#!/usr/bin/env python3
"""Write /workspace/country-law-triage/spain_subnational_{extract_result,gap_list,checks}.json from staged pack + local artifacts."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, time, collections, gzip
from pathlib import Path
B = Path('{_CORPORA}/es_subnational'); STAGE = Path(open(B / 'last_stage_path.txt').read().strip()); T = Path('/workspace/country-law-triage')
meta = json.loads((STAGE / 'PACK_META.json').read_text()); chk = meta['never_thin']; post = chk['post']; per = post['per_jurisdiction']
coll = json.load(open(B / 'collect_result_full.json')); build = json.load(open(B / 'parsed/build_stats_all.json'))
hc_pre = json.load(open(B / 'handcheck_20_pre.json')); hc = json.load(open(B / 'handcheck_20_staged.json'))
gapq = json.load(open(B / 'gap_quant.json')) if (B / 'gap_quant.json').exists() else {}
dedupe = json.load(open(B / 'dedupe_overlap.json')); spot = json.load(open(B / 'spot_check.json')) if (B / 'spot_check.json').exists() else {}
num = json.load(open(B / 'numbering_checks.json'))
ORDER = meta['append_order']
LIC = {'boe.es (AEBOE open data, legislacion-consolidada API)': {
    'terms_url': 'https://www.boe.es/informacion/aviso_legal/index.php',
    'licence': 'AEBOE licencia tipo (Resolución 27 junio 2024, effective 28 June 2024): commercial and non-commercial reuse incl. derived works',
    'conditions': ['cite source with link to https://www.boe.es ("Fuente de los datos: Agencia Estatal Boletín Oficial del Estado" / "Basado en datos de la Agencia Estatal Boletín Oficial del Estado")',
                   'do not distort meaning', 'do not suggest official character; each consolidated text must state it is "texto consolidado de carácter meramente informativo"',
                   'do not suggest AEBOE sponsorship/endorsement', 'mention last-update date; keep update-date and reuse-condition metadata', 'identify modifications as such', 'GDPR/LOPDGDD for personal data']},
    'CCAA portals/gazettes': {'used': False, 'note': 'No CCAA portal was used; no CCAA portal terms apply. Authentic texts are in each regional gazette.'}}
ext = dict(task='ES subnational collect+stage (NO publish, NO IR)', order='CoS 2026-10-01 20:22 PT + Watchdog GO 20:24 PT', repo=meta['repo'], old_tip=meta['base_tip'],
           old_totals=dict(laws=chk['laws']['old_rows'], articles=chk['articles']['old_rows']), new_totals=dict(laws=chk['laws']['new_rows'], articles=chk['articles']['new_rows']),
           added=dict(laws=chk['laws']['new_rows'] - chk['laws']['old_rows'], articles=chk['articles']['new_rows'] - chk['articles']['old_rows']),
           staging_path=str(STAGE), uploaded=False, source=meta['source'], catalog_listed=len(json.load(open(B / 'catalog_autonomico.json'))['data']),
           collect=coll['stats'], build=build['stats'], build_missing_raw=len(build['missing_raw']), build_errors=build['errors'],
           per_jurisdiction={j: per.get(j, {'laws': 0, 'articles': 0}) for j in ['ES'] + ORDER}, rango_per_jurisdiction=post['rango_per_jurisdiction'],
           dedupe_overlap=dedupe, handcheck_pre_run=dict(passed=hc_pre['passed'], n=hc_pre['n']), handcheck_staged=dict(passed=hc['passed'], n=hc['n'], jurisdictions=hc['jurisdictions']),
           blocked=[], licence_terms_per_source=LIC, language='es (BOE Spanish versions only)', ts=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
json.dump(ext, open(T / 'spain_subnational_extract_result.json', 'w'), indent=1, ensure_ascii=False)
gaps = [dict(jurisdiction='ES-CE', gap='0 rows', reason='Ceuta is an autonomous city without legislative power; no instrument in BOE consolidated autonómico; Statute of Autonomy (LO 1/1995) already in ES rows'),
        dict(jurisdiction='ES-ML', gap='0 rows', reason='Melilla is an autonomous city without legislative power; no instrument in BOE consolidated autonómico; Statute of Autonomy (LO 2/1995) already in ES rows'),
        dict(jurisdiction='ALL CCAA', gap='regulations (decretos, órdenes) not included', reason='BOE consolidates only autonomic norms with rank of law; regulations would need CCAA portals (not used)'),
        dict(jurisdiction='ALL CCAA', gap='laws without a BOE consolidated version', reason='BOE consolidates the main autonomic laws only', quantification=gapq or 'not quantified'),
        dict(jurisdiction='ALL CCAA', gap='consolidation lag / Desactualizado texts', count=sum(1 for x in json.load(open(B / 'catalog_autonomico.json'))['data'] if x['estado_consolidacion']['texto'] == 'Desactualizado'),
             reason='BOE consolidations of autonomic laws reflect only amendments by rank-of-law norms and are prepared after BOE publication'),
        dict(jurisdiction='ALL CCAA', gap='co-official language versions not included', reason='Spanish BOE versions only'),
        dict(jurisdiction='ALL CCAA', gap='245 instruments keyed by regional-gazette ids, null ELI', reason='BOE metadata has no url_eli for them')]
gaps += [dict(jurisdiction=r['jurisdiction'], gap='zero-article law', id=r['id']) for r in num.get('zero_article_laws', [])]
gaps += [dict(jurisdiction=r['jurisdiction'], gap='body under 200 chars after notice', id=r['id'], chars=r['chars']) for r in num.get('short_body_laws', [])]
json.dump(dict(gaps=gaps, collect_failures={k: v for k, v in coll['results'].items() if v not in ('ok', 'cached')}, build_missing_raw=build['missing_raw'], build_errors=build['errors']),
          open(T / 'spain_subnational_gap_list.json', 'w'), indent=1, ensure_ascii=False)
json.dump(dict(never_thin=chk, numbering_checks=num, handcheck_pre_run=hc_pre, handcheck_staged=hc, spot_check=spot, dedupe_overlap=dedupe,
               robots=dict(file=str(B / 'robots/boe.es_robots.txt'), api_urls_checked=ext['catalog_listed'], disallowed=coll['stats'].get('robots_skip', 0)),
               http403=coll['stats'].get('http403', 0), PASS=chk['PASS'] and hc['passed'] == hc['n']),
          open(T / 'spain_subnational_checks.json', 'w'), indent=1, ensure_ascii=False)
print('triage written; PASS', chk['PASS'], 'handcheck', hc['passed'], '/', hc['n'])
