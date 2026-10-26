#!/usr/bin/env python3
"""Build handcheck_prerun.json/.md from out/<law_id>.json.gz for the hand-check sample (no network)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, gzip, os, re, time, statistics as S
B = '{_CORPORA}/ng_expand'
ids = json.load(open(f'{B}/index/handcheck_ids.json'))
HUB_ART_COLS = ['law_id', 'id', 'title', 'text', 'source_url', 'document_number', 'article_number', 'record_type', 'metadata_json']
QTH = dict(dict_word_ratio_min=0.85, garbage_char_ratio_max=0.02, chars_per_page_min=150)
docs = []
for lid in ids:
    d = json.load(gzip.open(f'{B}/out/{lid}.json.gz'))
    q = d['quality']; st = d['split']; rows = d['rows']
    arts = [r for r in rows if r['record_type'] == 'article']
    own = st.get('arrangement_count') or st.get('max_section') or 0
    numbering_src = 'arrangement_of_sections' if st.get('arrangement_count') else ('max_section_number_in_body' if st.get('max_section') else 'none')
    ratio = round(st['n_sections'] / own, 3) if own else None
    below = (q['dict_word_ratio'] < QTH['dict_word_ratio_min'] or q['garbage_char_ratio'] > QTH['garbage_char_ratio_max'] or q['chars_per_page'] < QTH['chars_per_page_min'])
    if st.get('split_fallback_whole_text'): struct = 'NO_NUMBERS_WHOLE_TEXT'
    elif ratio is None: struct = 'NO_NUMBERING'
    elif ratio >= 0.9 and st['n_missing'] <= max(1, 0.1 * st['max_section']): struct = 'OK'
    elif ratio >= 0.5: struct = 'PARTIAL'
    else: struct = 'POOR'
    empty = (not rows) or sum(len(r['text']) for r in rows) < 200 or q['chars_per_page'] < QTH['chars_per_page_min']
    alltext = d['text']
    has_cit = bool(re.search(r'(?i)(may\s+be\s+)?cited\s+as', alltext))
    trunc_flags = []
    if st.get('arrangement_count') and st['max_section'] < 0.9 * st['arrangement_count']: trunc_flags.append(f"max_section {st['max_section']} < arrangement {st['arrangement_count']}")
    if not has_cit: trunc_flags.append('no citation clause in text')
    if d['pages'] <= 1: trunc_flags.append('source file has 1 page')
    cols_ok = all(list(r.keys()) == HUB_ART_COLS for r in rows)
    docs.append(dict(law_id=lid, title=d['title'], year=d.get('year'), host=d['host'], source_url=d['source_url'], source_format=d['source_format'], pages=d['pages'],
                     text_source=('OCR' if d['backend'] == 'ocr_tesseract' else 'text-layer+OCR pages' if d['backend'] == 'pdftotext+ocr_pages' else 'text-layer'),
                     backend=d['backend'], n_ocr_pages=len(d['ocr_pages']), ocr_seconds=d['ocr_seconds'], struct_ocr_used=bool(st.get('struct_ocr_used')),
                     grade=d['grade'], dict_word_ratio=q['dict_word_ratio'], garbage_char_ratio=q['garbage_char_ratio'], chars_per_page=q['chars_per_page'],
                     short_token_noise=q.get('short_token_noise'), grade_text_layer=d['grade_text_layer'], dict_text_layer=d['quality_text_layer']['dict_word_ratio'],
                     dict_ocr=(d['quality_ocr'] or {}).get('dict_word_ratio'), below_quality_threshold=below,
                     sections_found=st['n_sections'], doc_own_numbering=own, numbering_source=numbering_src, section_ratio=ratio, max_section=st['max_section'],
                     missing_numbers=st['missing_numbers'], annex_rows=st['n_annex'], rows=len(rows), structure=struct, empty=empty,
                     citation_clause_found=has_cit, truncation_flags=trunc_flags, hub_article_columns_ok=cols_ok))
n = len(docs)
nb = sum(x['below_quality_threshold'] for x in docs)
summary = dict(n_docs=n, hosts=sorted({x['host'] for x in docs}), years=sorted({x['year'] for x in docs if x['year']}),
               text_source=dict((k, sum(1 for x in docs if x['text_source'] == k)) for k in sorted({x['text_source'] for x in docs})),
               ocr_docs=sum(1 for x in docs if x['n_ocr_pages']), ocr_pages=sum(x['n_ocr_pages'] for x in docs), ocr_seconds=sum(x['ocr_seconds'] or 0 for x in docs),
               grade_counts=dict((g, sum(1 for x in docs if x['grade'] == g)) for g in ('good', 'fair', 'poor', 'empty')),
               text_layer_grade_counts=dict((g, sum(1 for x in docs if x['grade_text_layer'] == g)) for g in ('good', 'fair', 'poor', 'empty')),
               dict_word_ratio_min=min(x['dict_word_ratio'] for x in docs), dict_word_ratio_median=S.median(x['dict_word_ratio'] for x in docs),
               garbage_char_ratio_max=max(x['garbage_char_ratio'] for x in docs),
               below_quality_threshold=nb, below_quality_threshold_pct=round(100 * nb / n, 1),
               structure_counts=dict((k, sum(1 for x in docs if x['structure'] == k)) for k in ('OK', 'PARTIAL', 'POOR', 'NO_NUMBERS_WHOLE_TEXT', 'NO_NUMBERING')),
               empty_docs=sum(x['empty'] for x in docs), docs_with_truncation_flags=sum(1 for x in docs if x['truncation_flags']),
               total_rows=sum(x['rows'] for x in docs), hub_article_columns_ok=all(x['hub_article_columns_ok'] for x in docs),
               network_requests_this_run=0)
crit = dict(quality_threshold=QTH, ocr_gate='<=20% of sampled docs below quality threshold', yield_gate='>=~50 new acts',
            structure_note='structure OK = sections found >=90% of the document\'s own numbering (ARRANGEMENT OF SECTIONS count, else highest section number) and <=10% numbers missing')
qpass = nb <= 0.2 * n
spass = (summary['structure_counts']['OK'] + summary['structure_counts']['PARTIAL']) >= 0.75 * n and summary['empty_docs'] == 0
res = dict(generated_pt=time.strftime('%Y-%m-%dT%H:%M:%S%z'), order='cos_2026-10-03T19:49PT NG national EXPAND gov.ng only', hub_tip='955aadec57e54fbed468ab793ab40538f2a7a99a',
           criteria=crit, summary=summary, quality_gate_pass=qpass, structure_gate_pass=spass, verdict='PASS' if (qpass and spass) else 'FAIL', docs=docs)
json.dump(res, open(f'{B}/handcheck_prerun.json', 'w'), indent=1, ensure_ascii=False)
L = [f"# NG EXPAND hand check (pre-run) — {res['generated_pt']}", '', f"Order: {res['order']}; hub tip 955aadec57e5; sample 20 acts (19 nass.gov.ng, 1 justice.gov.ng), years {summary['years'][0]}–{summary['years'][-1]}. Re-processed from gz cache (0 network requests).", '',
     f"**Verdict: {res['verdict']}** (quality gate {'PASS' if qpass else 'FAIL'}: {nb}/{n} = {summary['below_quality_threshold_pct']}% below threshold dict≥0.85 & garbage≤0.02 & ≥150 chars/page; structure gate {'PASS' if spass else 'FAIL'}).", '',
     f"Text source: {summary['text_source']}; OCR'd docs {summary['ocr_docs']} ({summary['ocr_pages']} pages, {summary['ocr_seconds']} s). Final grades {summary['grade_counts']}; text-layer grades before OCR {summary['text_layer_grade_counts']}. dict ratio min {summary['dict_word_ratio_min']}, median {summary['dict_word_ratio_median']}; garbage max {summary['garbage_char_ratio_max']}.", '',
     f"Structure: {summary['structure_counts']}; empty docs {summary['empty_docs']}; truncation flags on {summary['docs_with_truncation_flags']} docs; rows {summary['total_rows']}; hub article columns match: {summary['hub_article_columns_ok']}.", '',
     '| law_id | year | pp | source | OCR pp | grade | dict | garb | ch/pg | sections / own numbering | missing | structure | flags |', '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
for x in docs:
    L.append(f"| {x['law_id'].replace('ng-fmj-the-child-rights-enforcement-procedure-rules-2015','ng-fmj-child-rights-rules-2015')} | {x['year']} | {x['pages']} | {x['text_source']}{' (struct-OCR)' if x['struct_ocr_used'] else ''} | {x['n_ocr_pages']} | {x['grade']} | {x['dict_word_ratio']} | {x['garbage_char_ratio']} | {x['chars_per_page']} | {x['sections_found']} / {x['doc_own_numbering']} ({'arr' if x['numbering_source']=='arrangement_of_sections' else 'max' if x['numbering_source']!='none' else '-'}) | {len(x['missing_numbers'])} | {x['structure']} | {'; '.join(x['truncation_flags'])} |")
open(f'{B}/handcheck_prerun.md', 'w').write('\n'.join(L) + '\n')
print(json.dumps(dict(verdict=res['verdict'], summary=summary), indent=1))
