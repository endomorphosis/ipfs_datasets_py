#!/usr/bin/env python3
"""Per-Land finalize of DE Landesrecht build parts (offline): within-Land dedupe, dedupe vs federal (id / normalized title / body text hash),
drop true duplicates, cast to the exact hub schema, merge into build/ (one Land at a time). Usage: de_finalize.py [LAND,...]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, json, re, hashlib, collections, unicodedata, os, time
from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq
B = Path('{_CORPORA}/de_subnational'); PARTS = B / 'build_parts'; FIN = B / 'build_final'; BUILD = B / 'build'
LANDS = sys.argv[1].split(',') if len(sys.argv) > 1 else ['NW', 'SN', 'HB', 'BB']
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
def mem_ok(tag):
    m = memavail()
    if m <= 3584: print(f'MEMGUARD STOP {tag} MemAvail={m}MB', flush=True); os._exit(3)
    return m
def ntitle(t):
    t = unicodedata.normalize('NFKC', t or '').lower()
    t = re.sub(r'\s+vom\s+\d{1,2}\.\s*\S+\s+\d{4}\W*$', '', t)          # strip a trailing "vom <date>"
    t = re.sub(r'[^\wäöüß]+', ' ', t); return re.sub(r'\s+', ' ', t).strip()
def body(r): return (r['text'] or '')[len(r['title'] or ''):].strip()
def thash(s): return hashlib.sha1(re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', s or '')).strip().encode()).hexdigest()
fedL = pq.ParquetFile(B / 'de_tip/data/laws.parquet'); fedA = pq.ParquetFile(B / 'de_tip/data/articles.parquet')
SL, SA = fedL.schema_arrow, fedA.schema_arrow
fid, ftit, fhash, fabbr = set(), {}, {}, {}
for b in fedL.iter_batches(batch_size=500, columns=['id', 'title', 'text', 'official_identifier']):
    for i, t, x, o in zip(*[b.column(c).to_pylist() for c in ['id', 'title', 'text', 'official_identifier']]):
        fid.add(i); ftit.setdefault(ntitle(t), i); bd = (x or '')[len(t or ''):].strip()
        if len(bd) >= 200: fhash.setdefault(thash(bd), i)
        if o: fabbr.setdefault(o.lower(), i)
faid = set()
for b in fedA.iter_batches(batch_size=50000, columns=['id']): faid.update(b.column('id').to_pylist())
fahash = set()
for b in fedA.iter_batches(batch_size=5000, columns=['text']):
    for x in b.column('text').to_pylist():
        if x and len(x) >= 200: fahash.add(thash(x))
print('federal ids', len(fid), 'art ids', len(faid), 'mem', memavail(), flush=True)
FIN.mkdir(exist_ok=True); BUILD.mkdir(exist_ok=True)
rep = {'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'method': {
    'normalized_title': 'NFKC, lower-case, trailing "vom <date>" removed, punctuation collapsed',
    'text_hash': 'sha1 of whitespace-collapsed NFKC law body (law text minus title); bodies <200 chars not hashed',
    'true_duplicate_rule': 'SN: old REVOSax ids that redirect are resolved to the final vorschrift id (canonical page kept; alias re-keyed if canonical not cached). Same id with different text -> re-keyed (BB de-bb-vo-<slug>). within Land: same id (keep first) or same normalized title AND same body hash (keep first). vs federal: same id, or same body hash as a federal law (identical consolidated text) -> dropped. Title-only matches are reported, not dropped.'},
    'per_land': {}, 'dropped': []}
wL = pq.ParquetWriter(BUILD / 'laws.parquet', SL, compression='zstd'); wA = pq.ParquetWriter(BUILD / 'articles.parquet', SA, compression='zstd')
for land in LANDS:
    m = mem_ok(land)
    L = pq.read_table(PARTS / land / 'laws.parquet').to_pylist(); A = pq.read_table(PARTS / land / 'articles.parquet').to_pylist()
    # assign article rows to laws by emission order (builder appends law row + its articles together); verify law_id
    pos = 0; recs = []
    for r in L:
        arts_r = A[pos:pos + r['article_count']]; pos += r['article_count']
        assert all(a['law_id'] == r['id'] for a in arts_r), r['id']
        recs.append([r, arts_r])
    assert pos == len(A)
    d = collections.Counter(); drops = []; rekeys = []
    def rekey(rec, new_id, why, new_ident=None, new_slug=None):
        r, arts_r = rec; old = r['id']
        r['id'] = new_id
        if new_ident: r['identifier'] = new_ident
        md = json.loads(r['metadata_json']); md['metadata']['official_id'] = r['identifier']
        if new_slug: md['metadata']['slug'] = new_slug
        r['metadata_json'] = json.dumps(md, ensure_ascii=False)
        for a in arts_r: a['law_id'] = new_id; a['id'] = new_id + a['id'][len(old):]
        rekeys.append({'land': land, 'old_id': old, 'new_id': new_id, 'source_url': r['source_url'], 'why': why})
    if land == 'SN':  # REVOSax: old vorschrift ids redirect to the current id -> resolve to the final_url id, prefer the canonical page
        res = lambda r: re.search(r'/vorschrift/(\d+)', r['source_url']).group(1)
        canon = {res(r) for r, _ in recs if res(r) == r['id'][6:]}
        recs.sort(key=lambda x: 0 if res(x[0]) == x[0]['id'][6:] else 1)
        seen_res = {}; out = []
        for rec in recs:
            r = rec[0]; k = res(r)
            if k in seen_res:
                same = thash(body(r)) == thash(body(seen_res[k][0]))
                d['within_by_resolved_portal_id'] += 1; d['within_by_resolved_portal_id_text_identical'] += same
                drops.append({'land': land, 'id': r['id'], 'title': r['title'][:200], 'source_url': r['source_url'], 'reason': f"old REVOSax id redirects to vorschrift/{k}, already kept as {seen_res[k][0]['id']} (text identical: {same})"}); continue
            if k != r['id'][6:]: rekey(rec, f'de-sn-{k}', f"REVOSax id {r['id'][6:]} redirects to vorschrift/{k}; canonical page not otherwise cached", f'revosax:{k}', k); d['rekeyed_redirect_alias'] += 1
            seen_res[k] = rec; out.append(rec)
        recs = out
    ids = collections.Counter(r['id'] for r, _ in recs); seen_id = {}
    for rec in recs:  # same id, different instrument (e.g. BB gesetze/mdf_2015 vs verordnungen/mdf_2015) -> distinct id
        r = rec[0]
        if ids[r['id']] > 1:
            if r['id'] in seen_id and thash(body(r)) != thash(body(seen_id[r['id']])):
                nid = r['id'].replace('de-bb-', 'de-bb-vo-', 1) if land == 'BB' and '/verordnungen/' in r['source_url'] else r['id'] + '-2'
                rekey(rec, nid, 'id collision with a different instrument of the same Land'); d['rekeyed_id_collision'] += 1
            else: seen_id.setdefault(r['id'], r)
    seen_id = {}; seen_th = {}; keep = []; keep_arts = []; title_dups = collections.defaultdict(list); fed_title_only = []; fed_abbr = []
    for r, arts_r in recs:
        bd = body(r); h = thash(bd) if len(bd) >= 200 else None; nt = ntitle(r['title'])
        reason = None
        if r['id'] in fid: d['vs_federal_by_id'] += 1; reason = f"id collides with federal id {r['id']}"
        if h and h in fhash: d['vs_federal_by_text_hash'] += 1; reason = reason or f'body text identical to federal law {fhash[h]}'
        if nt in ftit:
            d['vs_federal_by_normalized_title'] += 1
            if not (h and h in fhash): fed_title_only.append({'id': r['id'], 'title': r['title'][:160], 'federal_id': ftit[nt]})
        if r['official_identifier'] and r['official_identifier'].lower() in fabbr: d['vs_federal_by_abbreviation_info'] += 1; fed_abbr.append([r['id'], r['official_identifier'], fabbr[r['official_identifier'].lower()]])
        if not reason and r['id'] in seen_id: d['within_by_id'] += 1; reason = f"duplicate id within Land, identical text (first: {seen_id[r['id']]['source_url']})"
        if not reason and h and (nt, h) in seen_th: d['within_by_title_and_text_hash'] += 1; reason = f'same normalized title + body as {seen_th[(nt, h)]}'
        title_dups[nt].append(r['id'])
        if reason: drops.append({'land': land, 'id': r['id'], 'title': r['title'][:200], 'source_url': r['source_url'], 'reason': reason}); continue
        seen_id[r['id']] = r
        if h: seen_th[(nt, h)] = r['id']
        keep.append(r); keep_arts.extend(arts_r)
    within_th = collections.Counter(thash(body(r)) for r in keep if len(body(r)) >= 200)
    kid = {r['id'] for r in keep}
    arts = keep_arts
    aid = collections.Counter(a['id'] for a in arts)
    d.update(laws_in=len(L), laws_kept=len(keep), laws_dropped=len(drops), articles_in=len(A), articles_kept=len(arts),
             within_same_normalized_title_kept=sum(len(set(v) & kid) - 1 for v in title_dups.values() if len(set(v) & kid) > 1),
             within_same_body_hash_kept_diff_title=sum(v - 1 for v in within_th.values() if v > 1),
             article_ids_colliding_with_federal=sum(1 for a in arts if a['id'] in faid), duplicate_article_ids_within=sum(v - 1 for v in aid.values() if v > 1),
             article_text_identical_to_a_federal_article=sum(1 for a in arts if a['text'] and len(a['text']) >= 200 and thash(a['text']) in fahash))
    d.pop('_hashed', None)
    rep['per_land'][f'DE-{land}'] = dict(d, federal_title_only_matches=fed_title_only[:50], federal_abbreviation_matches_sample=fed_abbr[:20],
        same_title_kept_examples=[v for v in title_dups.values() if len(set(v) & kid) > 1][:15])
    rep['dropped'] += drops; rep.setdefault('rekeyed', []).extend(rekeys)
    assert d['duplicate_article_ids_within'] == 0 and d['article_ids_colliding_with_federal'] == 0, d
    (FIN / land).mkdir(exist_ok=True)
    tl = pa.Table.from_pylist([{c: r.get(c) for c in SL.names} for r in keep], schema=SL); ta = pa.Table.from_pylist([{c: a.get(c) for c in SA.names} for a in arts], schema=SA)
    pq.write_table(tl, FIN / land / 'laws.parquet', compression='zstd'); pq.write_table(ta, FIN / land / 'articles.parquet', compression='zstd')
    wL.write_table(tl); wA.write_table(ta)
    print(land, json.dumps({k: v for k, v in d.items()}, ensure_ascii=False), 'mem', memavail(), flush=True)
    del L, A, keep, arts, tl, ta
wL.close(); wA.close()
# merged build report
br = {'built_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'parts': {}}
for land in LANDS:
    r = json.load(open(PARTS / land / 'build_report.json')); br['parts'][land] = r
    for k, v in r.items():
        if k.startswith(land + '_'): br[k] = v
br['laws_after_dedupe'] = pq.ParquetFile(BUILD / 'laws.parquet').metadata.num_rows; br['articles_after_dedupe'] = pq.ParquetFile(BUILD / 'articles.parquet').metadata.num_rows
br['dedupe_dropped'] = len(rep['dropped'])
json.dump(br, open(BUILD / 'build_report.json', 'w'), indent=1, ensure_ascii=False)
json.dump(rep, open(B / 'dedupe_report.json', 'w'), indent=1, ensure_ascii=False)
print('DONE laws', br['laws_after_dedupe'], 'articles', br['articles_after_dedupe'], 'dropped', len(rep['dropped']))
