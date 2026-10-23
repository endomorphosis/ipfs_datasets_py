# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, json
TS = sys.argv[1]; R = json.load(open(f'/workspace/country-law-triage/ng_expand_review_{TS}.json'))
c = R['counts']; o = R['ocr']; s = R['sections']; wb = R['wayback_rows_live_copy']; i = R['integrity']; tr = R['text_rates']; hc = R['post_collect_handcheck']
L = [f"# NG national EXPAND: staging review ({R['generated_pt']})", '',
     f"**Verdict: {R['verdict']}.** Staging dir: `{R['staging_dir']}`. Nothing has been uploaded and no IR has been built.", '',
     f"Hub `{R['hub']['repo']}`, tip `{R['hub']['tip']}`, confirmed unchanged at {R['hub']['tip_confirmed_unchanged_pt']}.",
     f"Licence card: license `{R['hub']['licence_card']['front_matter_license']}` / `{R['hub']['licence_card']['license_name']}`. Card text: \"{R['hub']['licence_card']['card_license_section'].splitlines()[0]}\". Row `license` field: \"{R['hub']['licence_card']['row_license_field']}\"", '',
     '## Counts', '',
     f"- Laws: {c['laws_before']} → {c['laws_after']} (+{c['laws_added']})",
     f"- Articles: {c['articles_before']:,} → {c['articles_after']:,} (+{c['articles_added']:,})",
     f"- New law IDs ({R['new_law_ids']['count']}): " + ', '.join(R['new_law_ids']['ids']), '',
     '## Checks', '']
for k, v in R['checks'].items(): L.append(f"- {k}: {'PASS' if v else 'FAIL'}")
L += [f"- Never-thin detail: {R['never_thin']}",
      f"- Schema parity: laws {R['schema_parity']['laws']}, articles {R['schema_parity']['articles']}",
      f"- Orphan articles: {i['orphan_articles']}. Duplicate law IDs: {len(i['duplicate_law_ids'])}. Duplicate article IDs involving new rows: {len(i['duplicate_article_ids_involving_new_rows'])}.",
      f"- Duplicate article IDs already in the hub: {i['duplicate_article_ids_preexisting_in_hub']['count']} IDs (+{i['duplicate_article_ids_preexisting_in_hub']['extra_rows']} rows), in the ACJA 2015 and Data Protection Bill 2018 rows. Left untouched.",
      f"- article_count mismatches: {i['article_count_mismatch_all']} across all rows",
      f"- Hub laws with 0 articles: {i['laws_without_articles_hub']}. New laws with 0 articles: {len(i['laws_without_articles_new'])}.",
      f"- Field values (jurisdiction / country / language / license / source_type / law_status) match the hub: {R['field_consistency_ok']}",
      f"- New record_types: {R['record_types_new']}",
      f"- New article text: {tr['new_articles']['empty']} empty, {tr['new_articles']['lt20']} under 20 chars ({tr['new_articles']['lt20_pct']}%), {tr['new_articles']['lt50']} under 50 chars ({tr['new_articles']['lt50_pct']}%). Hub for comparison: under 20 = {tr['hub_articles']['lt20_pct']}%, under 50 = {tr['hub_articles']['lt50_pct']}%. Most short rows are one-line amendment or repeal sections.", '',
      '## Dedup', '']
for d in R['dropped']: L.append(f"- Dropped {d['law_id']} ({d['title']}): {d['reason']}")
L.append(f"- Near matches kept (different instruments, e.g. a bill vs its Act, or a 2004 Act vs its 2002 predecessor): {[(x['new'], x['hub']) for x in R['dedup']['kept_near_matches']]}")
L.append(f"- No new ID collides with a hub ID, and there are no NASS-id matches. Content matches reviewed: {[(x['new'], x['hub'], x['jaccard']) for x in R['dedup']['content_matches']]}")
L += ['', '## Text layer vs OCR', '',
      f"- Methods: {o['method_counts']}. Documents with any OCR: {o['docs_with_any_ocr']} ({o['ocr_pages']:,} pages). Engine: {o['engine']}.",
      f"- Final grades: {o['final_grade_counts']}. Raw text-layer grades before OCR: {o['text_layer_grade_counts']}.",
      f"- Dictionary-word ratio: {o['dict_word_ratio']}. Max garbage ratio: {o['garbage_char_ratio_max']}.",
      f"- Below threshold ({o['threshold']}): {len(o['below_threshold'])} ({o['below_threshold_pct']}%)"]
for x in o['below_threshold']: L.append(f"  - {x['law_id']} {x['title']}: {x['method']}, {x['grade']}, dict {x['dict_word_ratio']}")
L += ['', '## Section split', '', f"- Structure: {s['structure_counts']}. {s['note']}", '', '### Partial (sections found / document\'s own numbering)', '']
for x in s['partial']: L.append(f"- {x['law_id']} {x['title']}: {x['sections']}/{x['doc_own_numbering']}, {x['n_missing']} missing, {x['method']}")
L += ['', '### Whole-text fallback (ONE complete-text row)', '']
for x in s['whole_text_fallback']: L.append(f"- {x['law_id']} {x['title']}")
L += ['', '## Possible fragments', '']
for x in R['possible_fragments']: L.append(f"- {x['law_id']} {x['title']}: {x['pages']} p, {x['chars']} chars, type {x['doc_type']}, enactment/citation present {x['has_citation_or_enactment']}. {x['note'] or ''}")
L += ['', f"## Post-collect hand check: 20 random new laws (seed {hc['seed']}): {hc['ok']} OK / {hc['check']} CHECK", '', hc['method'], '',
      '| law_id | year | pdf pp | method | grade | dict | raw→staged cov | law→articles cov | end found | sections/own | verdict | notes |', '|---|---|---|---|---|---|---|---|---|---|---|---|']
for x in hc['docs']: L.append(f"| {x['law_id']} | {x['year']} | {x['pdf_pages']} | {x['method']} | {x['grade']} | {x['dict_word_ratio']} | {x['coverage_raw_textlayer_in_staged']} | {x['coverage_lawtext_in_articles']} | {x['document_end_found']} | {x['sections']}/{x['doc_own_numbering']} | {x['verdict']} | {x['notes']} |")
L += ['', '## EXTRA: Wayback-fetched hub rows: is there a live official copy? (no crawl)', '',
      f"- {wb['total_wayback_rows']} Wayback rows. {wb['with_live_official_copy']} have a live official copy on a gov.ng host, by confidence {wb['by_confidence']}. {wb['without_match']} have no match on disk; by document type: {wb['unmatched_by_document_type']}.",
      f"- Method: {wb['method']}", '', '| law_id | official URL | confidence | evidence |', '|---|---|---|---|']
for x in wb['matched']: L.append(f"| {x['law_id']} | {x['official_url']} | {x['confidence']} | {x['evidence']} |")
L += ['', f"Unmatched ({len(wb['unmatched'])}): " + ', '.join(x['law_id'] for x in wb['unmatched'])]
open(f'/workspace/country-law-triage/ng_expand_review_{TS}.md', 'w').write('\n'.join(L) + '\n')
print(len(L))
