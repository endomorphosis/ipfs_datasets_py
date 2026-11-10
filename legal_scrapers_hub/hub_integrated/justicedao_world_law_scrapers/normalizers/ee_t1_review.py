#!/usr/bin/env python3
"""EE municipal T1 review package (offline, read-only on shards; writes only <root>/review/). No hub pushes.
Usage: nice -n 19 /workspace/venv/bin/python -u /workspace/scripts/ee_t1_review.py [--root {_CORPORA}/ee_municipal] [--seed N]
Package review/ee_t1_review_<ts>.json + .md, and review/index.json (records the manifest sha256 the package was built from; the pipeline deletes the zip
only when the last package matches the current manifest):
  counts by LG (EHAK code, county) and by status / doc type / text kind; empty-text count; duplicates by global id, by LG + act number, and by
  LG + doc type + act number + adoption date (strict); missing EHAK (LG names); shard sha256 verification; 20-item random hand check
  (19 law + 9 article fields, id format, text non-empty / short, title, issuer -> LG -> EHAK consistency, jurisdiction, ISO dates, status, source_url,
  article_count == rows, article ids unique, metadata_json parses)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, json, gzip, re, random, hashlib, time, argparse, collections
ap = argparse.ArgumentParser(); ap.add_argument('--root', default='{_CORPORA}/ee_municipal'); ap.add_argument('--seed', type=int, default=None)
a = ap.parse_args(); ROOT = a.root; SH = f'{ROOT}/index/laws_shards'; RD = f'{ROOT}/review'; os.makedirs(RD, exist_ok=True)
LAW_COLS = ['id', 'title', 'text', 'source_url', 'source_type', 'jurisdiction', 'country', 'language', 'eli', 'date', 'date_issued', 'retrieved_at',
            'license', 'law_status', 'identifier', 'official_identifier', 'article_count', 'json_path', 'metadata_json']
ART_COLS = ['law_id', 'id', 'title', 'text', 'source_url', 'document_number', 'article_number', 'record_type', 'metadata_json']
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
def atomic_json(p, o):
    t = p + '.tmp'; json.dump(o, open(t, 'w'), indent=1, ensure_ascii=False); os.replace(t, p)
mp = f'{SH}/manifest.json'
if not os.path.exists(mp): sys.exit('no manifest')
man = json.load(open(mp)); msha = sha(mp); ts = time.strftime('%Y%m%dT%H%M%S'); rnd = random.Random(a.seed if a.seed is not None else int(time.time()))
by_lg = collections.OrderedDict(); status = collections.Counter(); dtype = collections.Counter(); tkind = collections.Counter()
gids = collections.Counter(); lgno = collections.Counter(); strict = collections.Counter(); missing_ehak = collections.Counter(); empty = 0; short = 0
sample = []; n = 0; sha_bad = []; arts_total = 0
for name, s in sorted(man['shards'].items()):
    p = f'{SH}/{name}'
    if sha(p) != s['sha256']: sha_bad.append(name)
    with gzip.open(p, 'rt', encoding='utf-8') as g:
        for l in g:
            r = json.loads(l); law = r['law']; md = json.loads(law['metadata_json']); n += 1; arts_total += len(r['articles'])
            lg = md.get('lg_name') or '?'; e = by_lg.setdefault(lg, dict(ehak=md.get('ehak_code'), county=md.get('county_ehak'), acts=0, current=0, empty_text=0, articles=0))
            e['acts'] += 1; e['current'] += law['law_status'] == 'current'; e['articles'] += len(r['articles'])
            em = not (law['text'] or '').strip(); empty += em; e['empty_text'] += em; short += (not em) and len(re.sub(r'\s', '', law['text'])) < 200
            status[law['law_status']] += 1; dtype[md.get('doc_type')] += 1; tkind[md.get('text_kind')] += 1
            gids[md.get('global_id')] += 1; lgno[(lg, md.get('act_no'))] += 1; strict[(lg, md.get('doc_type'), md.get('act_no'), md.get('adopted'))] += 1
            if not md.get('ehak_code'): missing_ehak[f"{lg} [{md.get('issuer')}]"] += 1
            item = dict(law=law, articles=r['articles'][:200], n_articles=len(r['articles']))
            if len(sample) < 20: sample.append(item)
            else:
                j = rnd.randrange(n)
                if j < 20: sample[j] = item
def dups(c): return dict(groups=sum(1 for v in c.values() if v > 1), extra_entries=sum(v - 1 for v in c.values() if v > 1),
                         examples=[[list(k) if isinstance(k, tuple) else k, v] for k, v in c.most_common(8) if v > 1])
checks = []
for it in sample:
    law = it['law']; arts = it['articles']; flags = []
    miss = [c for c in LAW_COLS if c not in law]; amiss = sorted({c for x in arts for c in ART_COLS if c not in x})
    if miss: flags.append(f'law_fields_missing:{miss}')
    if amiss: flags.append(f'article_fields_missing:{amiss}')
    try: md = json.loads(law['metadata_json'])
    except Exception: md = {}; flags.append('metadata_json_unparseable')
    if not re.fullmatch(r'EE-RT-\d{9,12}', law.get('id') or ''): flags.append('bad_id')
    chars = len(re.sub(r'\s', '', law.get('text') or ''))
    if chars == 0: flags.append('empty_text')
    elif chars < 200: flags.append('short_text<200')
    if not (law.get('title') or '').strip(): flags.append('no_title')
    if not md.get('ehak_code'): flags.append('missing_ehak')
    elif law.get('jurisdiction') != f"EE-{md['ehak_code']}": flags.append('jurisdiction!=ehak')
    if md.get('issuer') and md.get('lg_name') and md['lg_name'].split()[0][:4].lower() not in md['issuer'].lower(): flags.append('issuer_lg_mismatch')
    for f in ('date', 'date_issued'):
        v = law.get(f)
        if v and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', v): flags.append(f'bad_{f}')
    if not law.get('date_issued'): flags.append('no_adoption_date')
    if law.get('law_status') not in ('current', 'historical_version', 'future_version'): flags.append(f"status={law.get('law_status')}")
    if not (law.get('source_url') or '').startswith('https://www.riigiteataja.ee/akt/'): flags.append('bad_source_url')
    if law.get('article_count') != it['n_articles']: flags.append('article_count_mismatch')
    if len({x['id'] for x in arts}) != len(arts): flags.append('article_ids_not_unique')
    if any(not (x.get('text') or '').strip() or x.get('law_id') != law['id'] for x in arts): flags.append('article_row_bad')
    if md.get('rt_part') != 'RT IV': flags.append(f"rt_part={md.get('rt_part')}")
    hard = {'empty_text', 'bad_id', 'bad_source_url', 'metadata_json_unparseable', 'article_count_mismatch', 'article_row_bad'}
    verdict = 'fail' if any(f.split(':')[0] in hard or f.startswith('law_fields_missing') for f in flags) else ('warn' if flags else 'pass')
    checks.append(dict(id=law.get('id'), lg=md.get('lg_name'), ehak=md.get('ehak_code'), issuer=md.get('issuer'), title=(law.get('title') or '')[:90], doc_type=md.get('doc_type'),
                       act_no=md.get('act_no'), adopted=law.get('date_issued'), rt=md.get('rt_reference'), status=law.get('law_status'), valid=f"{md.get('valid_from')}..{md.get('valid_to') or ''}",
                       chars=chars, articles=it['n_articles'], first_article=(arts[0]['text'][:120] if arts else None), verdict=verdict, flags=flags, source_url=law.get('source_url')))
rep = dict(ts=ts, root=ROOT, published=False, note='review only; no hub push', manifest_sha256=msha,
           totals=dict(acts=n, articles=arts_total, lgs=len(by_lg), lgs_with_ehak=sum(1 for v in by_lg.values() if v['ehak']), empty_text=empty, short_text_lt200=short,
                       missing_ehak_acts=sum(missing_ehak.values()), status=dict(status), doc_types=dict(dtype.most_common()), text_kinds=dict(tkind),
                       shards=len(man['shards']), shard_sha256_mismatch=sha_bad, parse=man.get('parse')),
           duplicates=dict(global_id=dups(gids), lg_plus_number=dups(lgno), lg_type_number_adopted=dups(strict)),
           missing_ehak=dict(missing_ehak.most_common()), by_lg=dict(sorted(by_lg.items(), key=lambda kv: -kv[1]['acts'])),
           hand_check=dict(n=len(checks), verdicts=dict(collections.Counter(c['verdict'] for c in checks)), items=checks))
base = f'{RD}/ee_t1_review_{ts}'; atomic_json(base + '.json', rep)
T = rep['totals']; md = [f'# EE municipal T1 review package {ts}', '', f'Root `{ROOT}`. Not published. Manifest sha256 `{msha[:16]}…`.', '', '## Totals', '']
md += [f'- {k}: {v}' for k, v in T.items() if k != 'parse'] + [f"- parse: {T['parse']}", '', '## Duplicates', '']
md += [f"- {k}: {v['groups']} groups, {v['extra_entries']} extra entries; examples {v['examples'][:4]}" for k, v in rep['duplicates'].items()]
md += ['', f"## Missing EHAK ({T['missing_ehak_acts']} acts)", ''] + [f'- {k}: {v}' for k, v in list(rep['missing_ehak'].items())[:40]]
md += ['', '## Acts by LG', '', '| LG | EHAK | county | acts | current | empty text | articles |', '|---|---|---|---|---|---|---|']
md += [f"| {k} | {v['ehak']} | {v['county']} | {v['acts']} | {v['current']} | {v['empty_text']} | {v['articles']} |" for k, v in rep['by_lg'].items()]
md += ['', f"## 20-item hand check: {rep['hand_check']['verdicts']}", '', '| id | LG | EHAK | type / no / adopted | RT | status | valid | chars | arts | verdict | flags |', '|---|---|---|---|---|---|---|---|---|---|---|']
md += [f"| {c['id']} | {c['lg']} | {c['ehak']} | {c['doc_type']} {c['act_no']} {c['adopted']} | {c['rt']} | {c['status']} | {c['valid']} | {c['chars']} | {c['articles']} | {c['verdict']} | {'; '.join(c['flags'])} |" for c in checks]
open(base + '.md', 'w').write('\n'.join(md) + '\n')
ip = f'{RD}/index.json'; idx = json.load(open(ip)) if os.path.exists(ip) else dict(packages=[])
idx['packages'].append(dict(path=base + '.json', manifest_sha256=msha, acts=n, ts=time.strftime('%Y-%m-%dT%H:%M:%S%z'), verdicts=rep['hand_check']['verdicts'])); atomic_json(ip, idx)
print(time.strftime('%Y-%m-%d %H:%M:%S'), 'REVIEW PACKAGE', base + '.json', {k: v for k, v in T.items() if k not in ('parse', 'doc_types')}, rep['hand_check']['verdicts'], flush=True)
