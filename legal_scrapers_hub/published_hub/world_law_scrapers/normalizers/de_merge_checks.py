#!/usr/bin/env python3
"""Merge per-Land de_checks outputs into build_checks.json."""
import json
B='/workspace/legal-corpora/de_subnational'
out={'per_jurisdiction':{},'per_land_files':{},'laws':0,'articles':0,'duplicate_article_ids':0,'duplicate_law_ids':0,'orphan_articles':0,'duplicate_titles_same_land_count':0,'samples':{},'duplicate_titles_same_land':{}}
for L in ['NW','SN','HB','BB']:
    d=json.load(open(f'{B}/build_checks_{L}.json')); out['per_land_files'][L]=f'{B}/build_checks_{L}.json'
    out['per_jurisdiction'].update(d['per_jurisdiction'])
    for k in ['laws','articles','duplicate_article_ids','duplicate_law_ids','orphan_articles','duplicate_titles_same_land_count']: out[k]+=d[k]
    out['samples'][f'DE-{L}']=d['samples']; out['duplicate_titles_same_land'][f'DE-{L}']=d['duplicate_titles_same_land'][:10]; out['notes']=d['notes']
json.dump(out,open(f'{B}/build_checks.json','w'),indent=1,ensure_ascii=False); print('merged', out['laws'], out['articles'])
