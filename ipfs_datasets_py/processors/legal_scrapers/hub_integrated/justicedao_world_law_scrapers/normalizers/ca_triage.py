#!/usr/bin/env python3
"""Write /workspace/country-law-triage/canada_subnational_{extract_result,gap_list,checks}.json from parsed stats, staging PACK_META, hand check, blocked list."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, gzip, collections, time, random
from pathlib import Path
B = Path('{_CORPORA}/ca_subnational'); OUT = Path('/workspace/country-law-triage'); OUT.mkdir(exist_ok=True)
JURS = ['ON', 'NS', 'NB', 'NT', 'NU']
STAGE = Path((B / 'last_stage_path.txt').read_text().strip()); meta = json.loads((STAGE / 'PACK_META.json').read_text())
blocked = json.load(open(B / 'blocked.json')); hand = json.load(open(B / 'handcheck_20_staged.json'))
listed = {st: sum(1 for _ in open(B / f'index/{st}_list.jsonl')) for st in JURS}
per = {}; gaps = []; numbering = {}; spot = []
random.seed(20261001)
for st in JURS:
    s = json.load(open(B / f'parsed/{st}_stats.json'))
    gaps += s['gaps']; numbering[f'CA-{st}'] = s['numbering']
    k = collections.Counter(); z = collections.Counter(); sh = collections.Counter(); all_ids = []
    for l in gzip.open(B / f'parsed/{st}_laws.jsonl.gz', 'rt'):
        L = json.loads(l); all_ids.append(L['id'])
        dt = json.loads(L['metadata_json'])['document_type']; k[dt] += 1
        if L['article_count'] == 0: z[dt] += 1
        if len(L['text']) < 200: sh[dt] += 1
    st_stats = s['stats']; n = len(all_ids)
    per[f'CA-{st}'] = dict(listed=listed[st], laws=n, articles=st_stats.get('articles', 0),
        statutes=k['statute'], statute_articles=st_stats.get('statute_articles', 0), regulations=k['regulation'], regulation_articles=st_stats.get('regulation_articles', 0),
        zero_article_laws=sum(z.values()), zero_article_rate=round(sum(z.values()) / n, 4) if n else None, zero_article_by_kind=dict(z),
        text_under_200_chars=sum(sh.values()), text_under_200_rate=round(sum(sh.values()) / n, 4) if n else None, short_by_kind=dict(sh),
        not_fetched=st_stats.get('not_fetched', 0), parse_errors=st_stats.get('parse_error', 0), empty_text_dropped=st_stats.get('empty_text', 0),
        exact_duplicate_units_dropped=st_stats.get('exact_duplicate_units_dropped', 0), duplicate_law_ids_dropped=st_stats.get('dup_law_id', 0),
        coverage_vs_listing=round(n / listed[st], 4) if listed[st] else None)
    arts = collections.defaultdict(list)
    pick = set(random.sample(all_ids, min(3, len(all_ids)))); laws = []
    for l in gzip.open(B / f'parsed/{st}_articles.jsonl.gz', 'rt'):
        a = json.loads(l)
        if a['law_id'] in pick: arts[a['law_id']].append(a)
    for l in gzip.open(B / f'parsed/{st}_laws.jsonl.gz', 'rt'):
        L = json.loads(l)
        if L['id'] in pick:
            A = arts[L['id']]
            spot.append(dict(jurisdiction=L['jurisdiction'], law_id=L['id'], title=L['title'], identifier=L['identifier'], source_url=L['source_url'], article_count=L['article_count'],
                             article_rows=len(A), first_article=A[0]['title'][:100] if A else None, last_article=A[-1]['title'][:100] if A else None,
                             text_head=L['text'][:300], ok=L['article_count'] == len(A) and len(L['text']) > 200))
fed = meta['never_thin']['post']['per_jurisdiction']['CA']
ts = time.strftime('%Y-%m-%dT%H:%M:%S%z')
extract = dict(task='CA subnational collect+stage (NO publish)', generated_at=ts, repo=meta['repo'], old_tip=meta['base_tip'], staging_path=str(STAGE), uploaded=False,
               append_order=meta['append_order'], per_jurisdiction=per, totals=dict(laws=sum(p['laws'] for p in per.values()), articles=sum(p['articles'] for p in per.values())),
               federal_before=dict(laws=meta['never_thin']['laws']['old_rows'], articles=meta['never_thin']['articles']['old_rows']),
               federal_after=dict(laws=fed['laws'], articles=fed['articles']),
               staged_totals=dict(laws=meta['never_thin']['laws']['new_rows'], articles=meta['never_thin']['articles']['new_rows']),
               blocked=[dict(jurisdiction=b['jurisdiction'], status=b['status'], host=b['host']) for b in blocked],
               staged_per_jurisdiction=meta['never_thin']['post']['per_jurisdiction'],
               held_out_local_only={'CA-MB': dict(reason='licence decision pending (study/research/legal use only without King\'s Printer consent)', parsed_laws=1607, parsed_articles=42292, statutes=516, regulations=1091, path=str(B / 'parsed/MB_*.jsonl.gz')),
                                    'CA-SK': dict(reason='licence decision pending (website reproduction needs written copyright release); collection incomplete after 14:43 PT memory self-TERM', raw_pdfs_on_disk=553, listed=1161, path=str(B / 'raw/SK'))},
               old_vs_new_totals=dict(old=dict(laws=meta['never_thin']['laws']['old_rows'], articles=meta['never_thin']['articles']['old_rows']), new=dict(laws=meta['never_thin']['laws']['new_rows'], articles=meta['never_thin']['articles']['new_rows'])),
               languages='en only (ON/NS/NB English HTML; NT/NU bilingual PDFs -> English column). QC not collected (BLOCKED_SOURCE).')
gap = dict(generated_at=ts, blocked_or_unavailable=blocked, item_gaps=gaps, item_gap_counts=dict(collections.Counter((g['jurisdiction'], g['reason'].split(' ')[0]) for g in gaps).most_common()) if False else
           {f"{j}|{r}": c for (j, r), c in collections.Counter((g['jurisdiction'], g['reason'].split(' ')[0]) for g in gaps).items()},
           listing_notes={'CA-ON': 'e-Laws browse-search hits.total: statutes 857, regulations 2217 (09:31 PT); 856 unique current statutes + 2217 regulations listed (1 statute hit not present as a current unique alias in the aggregation buckets)',
                          'CA-NB': 'repealed chapters excluded at listing', 'CA-NS': 'date null (no currency date on NS pages)', 'CA-NT/NU': 'PDF text: marginal notes interleaved with body text', 'CA-NU': 'many consolidations flagged by source as not up to date (official_metadata.note)'})
checks = dict(generated_at=ts, never_thin=meta['never_thin'], numbering=numbering, handcheck_20=hand, spot_check=spot,
              article_count_vs_rows=dict(mismatch_laws=meta['never_thin']['post']['article_count_mismatch_laws'], orphan_articles=meta['never_thin']['post']['orphan_articles']),
              dedupe=dict(exact_duplicate_units_dropped={j: p['exact_duplicate_units_dropped'] for j, p in per.items()}, duplicate_law_ids_dropped={j: p['duplicate_law_ids_dropped'] for j, p in per.items()},
                          id_collisions_with_federal=meta['never_thin']['id_collisions_skipped']))
for nm, obj in (('extract_result', extract), ('gap_list', gap), ('checks', checks)):
    (OUT / f'canada_subnational_{nm}.json').write_text(json.dumps(obj, indent=1, ensure_ascii=False))
print(json.dumps(dict(per=per, totals=extract['totals'], fed_before=extract['federal_before'], fed_after=extract['federal_after'], PASS=meta['never_thin']['PASS'],
                      n_gaps=len(gaps), spot_ok=sum(1 for s in spot if s['ok']), spot_n=len(spot)), indent=1))
