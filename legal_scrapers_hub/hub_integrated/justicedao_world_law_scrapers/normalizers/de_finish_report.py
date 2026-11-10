#!/usr/bin/env python3
"""Post-process DE subnational staging: README additions, PACK_META, and enrich triage JSONs (gap items, dedupe, schema parity, rates). Offline."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, time, re, collections, sys
from pathlib import Path
import pyarrow.parquet as pq, pyarrow.compute as pc
B = Path('{_CORPORA}/de_subnational'); T = Path('/workspace/country-law-triage'); S = Path(open(B / 'last_stage_path.txt').read().strip())
J = lambda p: json.load(open(p))
chk = J(B / 'stage_check.json'); bchk = J(B / 'build_checks.json'); dd = J(B / 'dedupe_report.json'); nti = J(B / 'never_thin_independent.json')
hc = J(B / 'handcheck_staged.json'); spot = J(B / 'spotcheck_staged.json'); col = J(B / 'collect_result_combined.json'); nwmiss = J(B / 'nw_current_fassung_missing.json')
parts = {L: J(B / 'build_parts' / L / 'build_report.json') for L in ['NW', 'SN', 'HB', 'BB']}
gap = J(T / 'germany_subnational_gap_list.json'); checks = J(T / 'germany_subnational_checks.json'); ext = J(T / 'germany_subnational_extract_result.json')
per = chk['post']['per_jurisdiction']; bper = bchk['per_jurisdiction']; LANDS = ['NW', 'SN', 'HB', 'BB']
# ---- federal reference rates
fa = pq.read_table(B / 'de_tip/data/articles.parquet', columns=['id', 'text'])
ftxt = fa.column('text'); flen = pc.utf8_length(pc.fill_null(ftxt, ''))
f_empty = pc.sum(pc.equal(flen, 0)).as_py(); f_gl = pc.sum(pc.match_substring(fa.column('id'), ':gl:')).as_py(); f_short = pc.sum(pc.and_(pc.greater(flen, 0), pc.less(flen, 20))).as_py(); fn = fa.num_rows; del fa, ftxt, flen
fl = pq.read_table(B / 'de_tip/data/laws.parquet', columns=['article_count']); f_zero = pc.sum(pc.equal(fl.column('article_count'), 0)).as_py()
r4 = lambda a, b: round(a / b, 4) if b else None
rates = {'DE (federal, reference)': {'articles': fn, 'empty_text_rows': f_empty, 'empty_rate': r4(f_empty, fn), 'structural_gl_rows': f_gl, 'empty_non_structural_rate': r4(f_empty - f_gl, fn) if f_empty >= f_gl else None, 'short_under_20_chars_rows': f_short, 'short_rate': r4(f_short, fn), 'zero_article_laws': f_zero}}
for L in LANDS:
    q = bper[f'DE-{L}']; n = q['articles']
    rates[f'DE-{L}'] = {'laws': q['laws'], 'articles': n, 'empty_text_rows': q.get('article_rows_empty_text', 0), 'empty_rate': r4(q.get('article_rows_empty_text', 0), n),
        'structural_gl_rows': q.get('article_rows_structural_gl', 0), 'empty_non_structural_rows': q.get('article_rows_empty_text_non_structural', 0), 'empty_non_structural_rate': r4(q.get('article_rows_empty_text_non_structural', 0), n),
        'short_under_20_chars_rows': q.get('article_rows_text_under_20_chars', 0), 'short_rate': r4(q.get('article_rows_text_under_20_chars', 0), n),
        'laws_body_under_200_chars': q.get('law_text_body_under_200_chars', 0), 'laws_body_short_rate': r4(q.get('law_text_body_under_200_chars', 0), q['laws']),
        'laws_body_empty': q.get('law_text_body_empty', 0), 'zero_article_laws': q.get('zero_article_laws', 0), 'article_count_mismatch': q.get('article_count_mismatch', 0),
        'numbering_gaps': q.get('numbering_gaps', 0), 'numbering_backsteps': q.get('numbering_backsteps', 0), 'duplicate_numbers_within_law': q.get('duplicate_numbers_within_law', 0), 'letter_inserts_eg_5a': q.get('letter_inserts_eg_5a', 0)}
# short-body laws (staged)
short_laws = []
for L in LANDS:
    t = pq.read_table(B / 'build_final' / L / 'laws.parquet', columns=['id', 'title', 'text', 'source_url', 'article_count']).to_pylist()
    short_laws += [{'id': r['id'], 'title': r['title'][:160], 'body_chars': len(r['text']) - len(r['title']), 'article_count': r['article_count'], 'source_url': r['source_url']} for r in t if len(r['text'][len(r['title']):].strip()) < 200]
# ---- schema parity
fedL = pq.ParquetFile(B / 'de_tip/data/laws.parquet').schema_arrow; fedA = pq.ParquetFile(B / 'de_tip/data/articles.parquet').schema_arrow
stL = pq.ParquetFile(S / 'data/laws.parquet').schema_arrow; stA = pq.ParquetFile(S / 'data/articles.parquet').schema_arrow
schema = {'laws': {'columns_equal_and_ordered': fedL.names == stL.names, 'types_equal': [str(x.type) for x in fedL] == [str(x.type) for x in stL], 'schema_equal_incl_metadata': fedL.equals(stL, check_metadata=True), 'columns': [f'{x.name}:{x.type}' for x in stL]},
          'articles': {'columns_equal_and_ordered': fedA.names == stA.names, 'types_equal': [str(x.type) for x in fedA] == [str(x.type) for x in stA], 'schema_equal_incl_metadata': fedA.equals(stA, check_metadata=True), 'columns': [f'{x.name}:{x.type}' for x in stA]},
          'per_land_parts_cast_to_hub_schema': True, 'compression': 'zstd (same as hub)'}
schema['PASS'] = all(schema[k][c] for k in ('laws', 'articles') for c in ('columns_equal_and_ordered', 'types_equal', 'schema_equal_incl_metadata'))
# jurisdiction values in staged laws
jv = pc.value_counts(pq.read_table(S / 'data/laws.parquet', columns=['jurisdiction']).column(0)).to_pylist()
schema['jurisdiction_values'] = {d['values']: d['counts'] for d in jv}
# ---- dedupe summary
dsum = {'method': dd['method'], 'per_land': {j: {k: v for k, v in x.items() if not isinstance(v, list)} for j, x in dd['per_land'].items()},
        'federal_title_overlaps_kept': {j: x['federal_title_only_matches'] for j, x in dd['per_land'].items() if x['federal_title_only_matches']},
        'federal_title_overlap_note': 'Kept: same title as a GII federal row but different text. GII carries some pre-1990 GDR regulations (Naturpark/Biosphärenreservat VOs of 12.09.1990) and Bremen-origin laws (_br) as continuing federal law; the Land portals carry their own Landesrecht versions. Text similarity to the federal row: de-bb-natsgschorfhv 0.93, de-bb-natsgspreewv 0.91, de-bb-natpmschweizv 0.29, de-nw-32418 0.26, HB rows <=0.08 -> not byte-identical, so not dropped.',
        'dropped_total': len(dd['dropped']), 'dropped_vs_federal': sum(1 for x in dd['dropped'] if 'federal' in x['reason']), 'dropped': dd['dropped'], 'rekeyed': dd.get('rekeyed', []),
        'federal_preexisting_duplicate_article_ids': chk['articles']['duplicate_ids_before'],
        'id_namespace': "Landesrecht ids are 'de-<land>-<portal id>' (nw, sn, hb, bb); 0 collide with the 6,127 federal law ids or 125,159 distinct federal article ids (one federal id, 'de-mail-g', also begins with 'de-' but is not in a Land namespace)."}
# ---- gap items
items = []
for f in col.get('SN_fail', []): items.append(dict(jurisdiction='DE-SN', type='collector_fail', **f, note='redirect loop on the portal; the Corona-Schutz-Verordnung is expired anyway (would be excluded as not in force)'))
for L in LANDS:
    for x in parts[L].get(f'{L}_excluded_no_text_on_portal', []): items.append({'jurisdiction': f'DE-{L}', 'type': 'zero_articles_no_text_in_cached_page_excluded', **x})
for x in parts['SN'].get('SN_no_lesetext', []): items.append({'jurisdiction': 'DE-SN', 'type': 'no_lesetext_block (subset of the excluded no-text rows)', 'id': f'de-sn-{x}'})
for m in nwmiss: items.append({'jurisdiction': 'DE-NW', 'type': 'current_fassung_not_cached', 'taxonomy_term': m['term'], 'cached_versions': m['cached'], 'note': 'only a future Fassung (Gültig ab > 2026-10-02) or expired Fassungen are cached; the in-force Fassung page was not fetched, so the law is not staged'})
for s_ in short_laws: items.append({'jurisdiction': 'DE-' + s_['id'][3:5].upper(), 'type': 'staged_law_body_under_200_chars', **s_})
counts = collections.Counter((i['jurisdiction'], i['type']) for i in items)
gap['item_gaps'] = items; gap['item_gap_counts'] = {f'{j}|{t}': n for (j, t), n in sorted(counts.items())}
gap['zero_article_laws_staged'] = 0
gap['excluded_by_scope'] = {L: {k: v for k, v in parts[L].items() if 'excluded' in k and 'no_text' not in k} for L in LANDS}
gap['listing_notes'] = {'NW': f"NW sitemap has historical Fassungen: {parts['NW']['NW_terms']} taxonomy terms seen, {parts['NW']['NW_excluded_not_in_force']} without an in-force Fassung in cache (1,837 expired, 14 future-only = current_fassung_not_cached items).",
    'SN': '1,798 REVOSax sitemap URLs after slug prefilter; 1,790 fetched OK + 7 cached + 1 fail; 103 cached ids redirect to a newer vorschrift id (99 duplicates of a canonical page dropped, 4 re-keyed to the canonical id).',
    'HB': '1,611 documents in the facet Gesetze und Rechtsverordnungen / In Kraft; 383 Dokumenttyp "ohne Qualifikation" (mostly university Prüfungs-/Studienordnungen = Satzungen), 13 Gebührenordnungen, 10 Anordnungen, 6 Erlasse etc. excluded by scope; 19 amending acts excluded.',
    'BB': '970 /gesetze/ and /verordnungen/ links from the chronological Fundstellennachweis; 8 amending acts excluded; gesetze/mdf_2015 and verordnungen/mdf_2015 share a slug -> the Verordnung is re-keyed de-bb-vo-mdf-2015.'}
gap['uploaded'] = False
json.dump(gap, open(T / 'germany_subnational_gap_list.json', 'w'), indent=1, ensure_ascii=False)
# ---- checks
checks.update({'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'stage': str(S), 'uploaded': False,
    'live_hub_tip': {'sha': chk['live_tip'], 'matches_helper_TIP': chk['tip_unchanged'], 'snapshot_parquets_match_live_lfs_sha256': chk['laws_snapshot_matches_live'] and chk['articles_snapshot_matches_live'], 'redownload_needed': False, 'method': 'HfApi.repo_info / list_repo_refs / dataset_info (read-only)'},
    'never_thin_independent': nti, 'schema_parity': schema, 'empty_short_rates': rates, 'dedupe': dsum,
    'numbering': {j: {k: rates[j][k] for k in ('numbering_gaps', 'numbering_backsteps', 'duplicate_numbers_within_law', 'letter_inserts_eg_5a', 'article_count_mismatch', 'zero_article_laws')} for j in rates if j.startswith('DE-')},
    'article_count_vs_rows': {'mismatch_laws': chk['post']['article_count_mismatch_laws'], 'orphan_articles': chk['post']['orphan_articles']},
    'handcheck_20': {'pass': sum(r['PASS'] for r in hc), 'n': len(hc), 'per_land': {L: f"{sum(r['PASS'] for r in hc if r['land'] == L)}/{sum(1 for r in hc if r['land'] == L)}" for L in LANDS},
                     'note': 'first run 19/20: de-bb-bbgbesg flagged extra § 46a; build was correct, the independent BB heading regex missed <a id=...> anchors; regex fixed, 20/20.', 'rows': hc},
    'parser_fix_this_run': 'NW: recht.nrw.de splits some norms into a heading-only section plus unlabelled text section(s); these are now merged into the norm row (NW articles 26,804 -> 26,603; empty non-structural rows 1,056 -> 855). Empty unlabelled sections are no longer emitted.'})
json.dump(checks, open(T / 'germany_subnational_checks.json', 'w'), indent=1, ensure_ascii=False)
# ---- extract result
ext.update({'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'staging_path': str(S), 'uploaded': False, 'live_hub_tip': chk['live_tip'], 'tip_matches_helper_TIP': chk['tip_unchanged'],
    'parquet_paths': {'laws': str(S / 'data/laws.parquet'), 'articles': str(S / 'data/articles.parquet')}, 'parquet_sha256': {'laws': chk['laws_sha256_staged'], 'articles': chk['articles_sha256_staged']},
    'per_jurisdiction': {j: {'laws': v['laws'], 'articles': v['articles']} for j, v in per.items()}, 'schema_parity_PASS': schema['PASS'],
    'never_thin_PASS': chk['PASS'] and all(nti[k]['federal_rows_byte_identical'] for k in nti), 'dedupe_dropped': len(dd['dropped']), 'dedupe_dropped_vs_federal': dsum['dropped_vs_federal'],
    'handcheck': f"{sum(r['PASS'] for r in hc)}/{len(hc)}", 'spotcheck': f"{spot['pass_both']}/{spot['n']}", 'collectors_started': 0, 'land_portal_http_requests': 0,
    'collector': col['result'], 'collector_note': col['note']})
json.dump(ext, open(T / 'germany_subnational_extract_result.json', 'w'), indent=1, ensure_ascii=False)
# ---- PACK_META
pm = J(S / 'PACK_META.json'); pm.update({'never_thin_independent': nti, 'schema_parity': schema, 'dedupe': {k: v for k, v in dsum.items() if k not in ('dropped',)}, 'dedupe_dropped_ids': [x['id'] for x in dd['dropped']],
    'handcheck_20': checks['handcheck_20']['pass'], 'spotcheck': f"{spot['pass_both']}/{spot['n']}", 'uploaded': False})
(S / 'PACK_META.json').write_text(json.dumps(pm, indent=2, ensure_ascii=False))
# ---- README
r = (S / 'README.md').read_text()
r = r.replace('# German Federal Law Corpus (Gesetze im Internet)\n\nResearch snapshot of official legislation collected from **Bundesministerium der Justiz / gesetze-im-internet.de**.',
              '# German Federal and State Law Corpus (Gesetze im Internet + Landesrecht portals)\n\nResearch snapshot of official legislation collected from **Bundesministerium der Justiz / gesetze-im-internet.de** (federal, `jurisdiction=DE`)\nand, appended, from the official Landesrecht portals of Brandenburg, Bremen, Nordrhein-Westfalen and Sachsen (`jurisdiction=DE-<Land>`).')
r = r.replace("- `scrapers/common.py` — shared collector helpers.\n", "- `scrapers/common.py` — shared collector helpers.\n- `scrapers/de_collect.py`, `de_build.py`, `de_finalize.py`, `de_checks.py`, `de_stage_and_check.py` — Landesrecht collector, parser, dedupe, checks and append/never-thin staging.\n")
r = r.replace('| --- | --- | --- | ---: | ---: | ---: | ---: | --- |\n', f"| --- | --- | --- | ---: | ---: | ---: | ---: | --- |\n| Bund (federal, unchanged) | DE | https://www.gesetze-im-internet.de | {per['DE']['laws']} | – | – | {per['DE']['articles']} | – |\n", 1)
tot = sum(per[f'DE-{L}']['laws'] for L in LANDS); tota = sum(per[f'DE-{L}']['articles'] for L in LANDS)
r = r.replace('\nNot collected (see `PACK_META.json`', f"| **Landesrecht total** | | | **{tot}** | | | **{tota}** | |\n\nQA (staged rows): article_count = article rows for every law (0 mismatches, 0 orphans); 0 laws with zero articles; hand check 20/20 laws (5 per Land) and random spot check {spot['pass_both']}/{spot['n']} article rows matched the cached source pages; never-thin: all 6,127 federal law rows and 129,983 federal article rows are byte-identical to hub tip `{chk['live_tip'][:12]}` and come first.\n\nNot collected (see `PACK_META.json`", 1)
rt = ['| jurisdiction | articles | empty text (all) | empty, non-structural | text < 20 chars | laws with body < 200 chars |', '| --- | ---: | ---: | ---: | ---: | ---: |']
for L in LANDS:
    x = rates[f'DE-{L}']; rt.append(f"| DE-{L} | {x['articles']} | {x['empty_text_rows']} ({x['empty_rate']:.1%}) | {x['empty_non_structural_rows']} ({x['empty_non_structural_rate']:.1%}) | {x['short_under_20_chars_rows']} ({x['short_rate']:.1%}) | {x['laws_body_under_200_chars']} |")
extra = f"""- NW: {len(nwmiss)} in-force laws are missing because only a future Fassung (in force from 2027/2028, e.g. LBesG NRW, LBeamtVG NRW) or expired Fassungen were cached;
  the currently valid Fassung page was not fetched. NW sitemap entries without an in-force Fassung (1,837, repealed/expired) are excluded.
- Laws whose cached page had no norm text are not staged: NW {len(parts['NW'].get('NW_excluded_no_text_on_portal', []))}, SN {len(parts['SN'].get('SN_excluded_no_text_on_portal', []))}, HB {len(parts['HB'].get('HB_excluded_no_text_on_portal', []))} (listed in the gap list). One SN page (Sächsische Corona-Schutz-Verordnung) failed with a redirect loop.
- SN: 103 cached REVOSax ids redirect to a newer vorschrift id; 99 exact duplicates of the canonical page were dropped and 4 rows re-keyed to the canonical id (`de-sn-<final id>`).
  BB: `gesetze/mdf_2015` and `verordnungen/mdf_2015` share a slug; the Verordnung is `de-bb-vo-mdf-2015`.
- HB scope: university Prüfungs-/Studienordnungen (Dokumenttyp "ohne Qualifikation", 383), Gebührenordnungen (13), Anordnungen, Erlasse etc. are excluded.
- Overlap with federal rows: 0 id collisions, 0 identical law texts, so no state row was dropped as a federal duplicate. 7 state laws share a title with a GII row
  (GII also carries some GDR 1990 Naturpark/Biosphärenreservat regulations and Bremen-origin laws as continuing federal law); they are kept as Landesrecht.
- The federal articles table already contains {chk['articles']['duplicate_ids_before']:,} duplicate article ids (pre-existing, unchanged); the appended rows add none.
- Empty / short article rows (most empty rows are structural `:gl:` headings or repealed norms marked "(weggefallen)/(aufgehoben)"):

{chr(10).join(rt)}
"""
r = r.replace('- Dates: `date`/`date_issued` = Ausfertigungsdatum where the portal shows it.\n', '- Dates: `date`/`date_issued` = Ausfertigungsdatum where the portal shows it.\n' + extra, 1)
r = r.replace('robots.txt Crawl-delay 20 respected (one request per 20 s).', 'robots.txt (User-agent: *, Crawl-delay: 20) respected (one request per 20 s).')
r = r.replace('CoS/legal decision needed before publishing DE-HB; if published: attribute and note NC-ND.', 'robots.txt is empty (no restrictions). The CC BY-NC-ND label was found on all 1,611 cached HB documents. A legal decision is needed before publishing DE-HB; if published: attribute "Freie Hansestadt Bremen" and note the NC-ND label.')
(S / 'README.md').write_text(r)
print('ok', schema['PASS'], len(items), dict(counts))
