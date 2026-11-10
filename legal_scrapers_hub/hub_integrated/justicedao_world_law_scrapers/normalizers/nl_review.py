#!/usr/bin/env python3
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, os, json, gzip, random, re, difflib, subprocess, time, collections
import pyarrow as pa, pyarrow.parquet as pq, pyarrow.compute as pc
sys.path.insert(0, '/workspace/scripts'); import nl_split
import xml.etree.ElementTree as ET
S, TS = sys.argv[1], sys.argv[2]
B = '{_CORPORA}/nl_extract'; TIP = f'{B}/nl_tip'
def mem():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
def guard():
    if mem() < 3584: print('MEMGUARD ABORT', mem()); sys.exit(3)
R = dict(generated_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'), stage_dir=S, hub_repo='endomorphosis/ipfs_netherlands_laws')
R['hub_tip'] = dict(base_tip=open(f'{TIP}/TIP_SHA').read().strip(), current_tip_checked=sys.argv[3], unchanged=open(f'{TIP}/TIP_SHA').read().strip() == sys.argv[3])
oL, nL, oA, nA = [pq.ParquetFile(p) for p in (f'{TIP}/data/laws.parquet', f'{S}/data/laws.parquet', f'{TIP}/data/articles.parquet', f'{S}/data/articles.parquet')]
R['counts'] = dict(laws_before=oL.metadata.num_rows, laws_after=nL.metadata.num_rows, articles_before=oA.metadata.num_rows, articles_after=nA.metadata.num_rows)
def sch(f): return [(x.name, str(x.type)) for x in f.schema_arrow]
R['schema_parity'] = {t: dict(identical=sch(a) == sch(b), before=sch(a), after=sch(b), diff=[x for x in sch(b) if x not in sch(a)] + [x for x in sch(a) if x not in sch(b)]) for t, a, b in (('laws', oL, nL), ('articles', oA, nA))}
# never-thin
old_ids = pq.read_table(oL.reader if False else f'{TIP}/data/laws.parquet', columns=['id'])['id'].to_pylist()
new_ids = pq.read_table(f'{S}/data/laws.parquet', columns=['id'])['id'].to_pylist()
cols = [c for c in oL.schema_arrow.names if c != 'article_count']
changed = collections.Counter(); same_order = old_ids == new_ids
if same_order:
    for bo, bn in zip(oL.iter_batches(batch_size=1000, columns=cols), nL.iter_batches(batch_size=1000, columns=cols)):
        for c in cols:
            a, b = bo.column(c), bn.column(c)
            eq = pc.fill_null(pc.equal(a, b), False); both_null = pc.and_(pc.is_null(a), pc.is_null(b))
            n_diff = len(a) - pc.sum(pc.cast(pc.or_(eq, both_null), pa.int64())).as_py()
            if n_diff: changed[c] += n_diff
        guard()
R['never_thin'] = dict(old_ids_subset_of_new=set(old_ids) <= set(new_ids), n_old=len(old_ids), n_new=len(new_ids), same_order=same_order,
                       new_law_ids=sorted(set(new_ids) - set(old_ids)), dropped_law_ids=sorted(set(old_ids) - set(new_ids)),
                       columns_compared=cols, changed_cells_excluding_article_count=dict(changed), pass_=(set(old_ids) <= set(new_ids) and not changed))
R['new_law_ids'] = R['never_thin']['new_law_ids']
# articles stats
per_law = collections.Counter(); ids_seen = set(); dups = []; rt = collections.Counter(); empty = collections.Counter(); lt20 = collections.Counter(); lt50 = collections.Counter(); chars = collections.Counter()
for b in nA.iter_batches(batch_size=20000, columns=['law_id', 'id', 'record_type', 'text']):
    L = pc.utf8_length(pc.fill_null(pc.utf8_trim_whitespace(b.column('text')), '')).to_pylist()
    for lid, aid, r, n in zip(b.column('law_id').to_pylist(), b.column('id').to_pylist(), b.column('record_type').to_pylist(), L):
        r = r or 'null(unsplit_hub_row)'
        per_law[lid] += 1; rt[r] += 1; chars[r] += n
        if aid in ids_seen: dups.append(aid)
        ids_seen.add(aid)
        if n == 0: empty[r] += 1
        if n < 20: lt20[r] += 1
        if n < 50: lt50[r] += 1
    guard()
tot = sum(rt.values())
def rate(c, k=None): return round((sum(c.values()) if k is None else c[k]) / max(1, tot if k is None else rt[k]), 6)
R['text_quality'] = dict(overall=dict(rows=tot, empty=sum(empty.values()), empty_rate=rate(empty), lt20=sum(lt20.values()), lt20_rate=rate(lt20), lt50=sum(lt50.values()), lt50_rate=rate(lt50)),
                         by_record_type={k: dict(rows=rt[k], empty=empty[k], empty_rate=rate(empty, k), lt20=lt20[k], lt20_rate=rate(lt20, k), lt50=lt50[k], lt50_rate=rate(lt50, k), mean_chars=round(chars[k] / rt[k])) for k in rt})
law_set = set(new_ids)
R['orphans'] = dict(articles_with_unknown_law_id=sum(v for k, v in per_law.items() if k not in law_set), laws_with_0_articles=[l for l in new_ids if per_law[l] == 0])
R['duplicate_article_ids'] = dict(n=len(dups), sample=dups[:20])
ac = dict(zip(new_ids, pq.read_table(f'{S}/data/laws.parquet', columns=['article_count'])['article_count'].to_pylist()))
mism = [(l, ac[l], per_law[l]) for l in new_ids if ac[l] != per_law[l]]
R['article_count_consistency'] = dict(mismatches=len(mism), sample=mism[:20], sum_article_count=sum(ac.values()), article_rows=tot, laws_with_article_count_1=sum(1 for v in ac.values() if v == 1))
# kept hub row(s)
kept = pq.read_table(f'{S}/data/articles.parquet', filters=[('law_id', '=', 'BWBR0052939')]).to_pylist()
oldk = pq.read_table(f'{TIP}/data/articles.parquet', filters=[('law_id', '=', 'BWBR0052939')]).to_pylist()
R['unsplit_kept'] = dict(law_id='BWBR0052939', rows=len(kept), identical_to_hub_row=kept == oldk, id=[r['id'] for r in kept], text_chars=[len(r['text'] or '') for r in kept],
                         reason='toestand XML 2026-08-04_0 returned HTTP 301 self-redirect (Location = same URL) in the original run and in the single retry 2026-10-03 13:18 PT; no 404 so no manifest fallback')
# BWBW laws
bw = pq.read_table(f'{S}/data/laws.parquet', filters=[('id', 'in', [l for l in new_ids if l.startswith('BWBW')])], columns=['id', 'title', 'article_count', 'source_url', 'law_status']).to_pylist()
for r in bw:
    rows = pq.read_table(f'{S}/data/articles.parquet', filters=[('law_id', '=', r['id'])], columns=['id', 'record_type', 'title', 'text']).to_pylist()
    r.update(article_count_before=1, record_types=dict(collections.Counter(x['record_type'] for x in rows)), first_ids=[x['id'] for x in rows[:5]],
             xml_top_artikel=nl_split.count_top_artikel(gzip.decompress(open(f"{B}/raw/{r['id']}.xml.gz", 'rb').read())))
R['bwbw_laws'] = bw
# post-split hand check: 20 random laws
random.seed(20261003); cand = [l for l in new_ids if os.path.exists(f'{B}/raw/{l}.xml.gz')]; sample = sorted(random.sample(cand, 20))
tk = lambda s: re.findall(r'\w+', s.lower()); HC = []
for lid in sample:
    raw = gzip.decompress(open(f'{B}/raw/{lid}.xml.gz', 'rb').read()); root = ET.fromstring(raw)
    rows = pq.read_table(f'{S}/data/articles.parquet', filters=[('law_id', '=', lid)]).to_pylist()
    w = root.find('wetgeving') if root.tag == 'toestand' else root
    ops = [e for e in w.iter() if e.tag in ('wettekst', 'regeling-tekst', 'circulaire-tekst')]
    xml_bij = sum(1 for e in w.iter('bijlage'))
    optoks = []
    for e in ops: optoks += tk(nl_split.text_of(e))
    # container headings (hoofdstuk/afdeling/paragraaf kop) live in metadata_json.path, not in row text -> exclude from recall base
    ckop = collections.Counter()
    for e in w.iter():
        if e.tag in nl_split.CONTAINERS or e.tag in ('divisie',):
            k = e.find('kop')
            if k is not None and not any(x.tag in ('artikel', 'bijlage') for x in [e]): ckop.update(tk(nl_split.text_of(k)))
    bij_outside = [e for e in w.iter('bijlage')]
    for e in bij_outside:
        optoks += tk(nl_split.text_of(e))
    mine = []
    for r in rows: mine += tk(r['text'])
    xall = tk(' '.join(root.itertext()))
    if len(xall) * len(mine) < 4e10:
        sm = difflib.SequenceMatcher(None, xall, mine, autojunk=False); m = sum(b.size for b in sm.get_matching_blocks()); prec = round(m / max(1, len(mine)), 4)
    else: prec = None
    so = collections.Counter(optoks) - ckop; sm_ = collections.Counter(mine)
    recall = round(sum(min(v, sm_[k]) for k, v in so.items()) / max(1, sum(so.values())), 4)
    law = pq.read_table(f'{S}/data/laws.parquet', filters=[('id', '=', lid)], columns=['metadata_json', 'article_count']).to_pylist()[0]
    bt = json.loads(law['metadata_json'])['metadata'].get('bwb_type')
    n_art = sum(1 for r in rows if r['record_type'] == 'article'); xa = nl_split.count_top_artikel(raw)
    o = dict(law_id=lid, bwb_type=bt, rows=len(rows), article_count=law['article_count'], articles=n_art, xml_top_artikel=xa,
             annexes=sum(1 for r in rows if r['record_type'] == 'annex'), xml_bijlage=xml_bij, sections=sum(1 for r in rows if r['record_type'] == 'section'),
             operative_token_recall=recall, token_precision_vs_xml=prec, ids_unique=len({r['id'] for r in rows}) == len(rows), empty=sum(1 for r in rows if not (r['text'] or '').strip()))
    o['PASS'] = bool(o['article_count'] == o['rows'] and o['articles'] == xa and o['ids_unique'] and o['empty'] == 0 and recall >= 0.95 and (prec is None or prec >= 0.98))
    HC.append(o); guard()
R['post_split_handcheck'] = dict(seed=20261003, n=len(HC), passed=sum(o['PASS'] for o in HC), criteria='article_count==rows; articles==independent top-level artikel count in XML; ids unique; no empty rows; operative-token recall (bag) >=0.95; ordered token precision vs XML >=0.98', laws=HC)
rd = open(f'{S}/README.md').read(); R['card_excerpt'] = rd.split('---')[1].strip().splitlines()[:3] + [l for l in rd.splitlines() if 'CC0' in l][:4]
R['card_license_cc0'] = 'license: cc0-1.0' in rd
du = lambda p: subprocess.run(['du', '-sb', p], capture_output=True, text=True).stdout.split()[0]
R['disk_bytes'] = {p: int(du(p)) for p in (S, f'{B}/raw', f'{B}/out/articles', f'{B}/out/articles_v2', B)}
R['files'] = {os.path.relpath(os.path.join(d, f), S): os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(S) for f in fs}
R['fetch_extra'] = json.load(open(f'{B}/extra/fetch_extra_result.json'))
R['memavail_mb_end'] = mem()
out = f'/workspace/country-law-triage/nl_extract_review_{TS}.json'; json.dump(R, open(out, 'w'), indent=1, ensure_ascii=False, default=str); print(out)
print(json.dumps({k: R[k] for k in ('hub_tip', 'counts', 'new_law_ids', 'orphans', 'duplicate_article_ids', 'article_count_consistency', 'text_quality', 'disk_bytes')}, indent=1, default=str))
print('schema identical', {t: v['identical'] for t, v in R['schema_parity'].items()}, 'never_thin', R['never_thin']['pass_'], R['never_thin']['changed_cells_excluding_article_count'])
print('HC', R['post_split_handcheck']['passed'], '/20'); [print(o) for o in HC]
print('BWBW', bw); print('kept', R['unsplit_kept'])
