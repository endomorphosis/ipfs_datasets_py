#!/usr/bin/env python3
"""CZ T2 review packages (offline, read-only on data; writes only cz_sbirkapp/review/). No hub pushes.
Usage:
  nice -n 19 /workspace/venv/bin/python -u /workspace/scripts/cz_t2_review.py --auto [--trigger TEXT] [--root DIR]
      build a package if one is due: a kraj completed (cursor final_flushed) without a package yet, or packed laws crossed the next 20k multiple
      (the collector calls this detached at those events; idempotent via review/index.json)
  nice -n 19 /workspace/venv/bin/python -u /workspace/scripts/cz_t2_review.py --now [--kraj CZ-10] [--root DIR] [--no-dict]
      build a package immediately (all packed kraje, or one kraj)
Package (review/cz_t2_review_<ts>_<tag>.json + .md): counts by kraj (listing total, targets, drops, ledger docs, detail 200, with text, packed, empty text,
  OCR needed / done / pending), duplicate law ids (within T2 shards and vs T1), duplicate (IČO, druh, číslo) groups, shard sha256 verification,
  and a 20-item random hand check from the packed shards (19 law fields + 9 article fields present, id format, text non-empty, jurisdiction prefix =
  kraj, ISO dates, law_status, source_url host, article_count == rows, metadata_json parses with spp_id/kraj_iso; optional cs dictionary ratio).
Streaming / low memory: shards and ledgers are read one record at a time."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, json, gzip, re, random, hashlib, time, argparse, subprocess, collections
B = '{_CORPORA}/cz_sbirkapp'
ap = argparse.ArgumentParser(); ap.add_argument('--root', default=f'{B}/t2'); ap.add_argument('--auto', action='store_true'); ap.add_argument('--now', action='store_true')
ap.add_argument('--trigger', default='manual'); ap.add_argument('--kraj', default=None); ap.add_argument('--no-dict', action='store_true'); ap.add_argument('--seed', type=int, default=None)
a = ap.parse_args()
ROOT = a.root; RD = f'{os.path.dirname(ROOT)}/review'; os.makedirs(RD, exist_ok=True)
LAW_COLS = ['id', 'title', 'text', 'source_url', 'source_type', 'jurisdiction', 'country', 'language', 'eli', 'date', 'date_issued', 'retrieved_at',
            'license', 'law_status', 'identifier', 'official_identifier', 'article_count', 'json_path', 'metadata_json']
ART_COLS = ['law_id', 'id', 'title', 'text', 'source_url', 'document_number', 'article_number', 'record_type', 'metadata_json']
def log(*x): print(time.strftime('%Y-%m-%d %H:%M:%S'), *x, flush=True)
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
def it(p):
    if not os.path.exists(p): return
    op = gzip.open if p.endswith('.gz') else open
    with op(p, 'rt', encoding='utf-8') as f:
        for l in f:
            try: yield json.loads(l)
            except Exception: pass
def atomic_json(p, o):
    t = p + '.tmp'; json.dump(o, open(t, 'w'), indent=1, ensure_ascii=False); os.replace(t, p)
plan = json.load(open(f'{ROOT}/plan.json')); cur = json.load(open(f'{ROOT}/cursor.json')) if os.path.exists(f'{ROOT}/cursor.json') else dict(kraje={})
mp = f'{ROOT}/index/laws_shards/manifest.json'; man = json.load(open(mp)) if os.path.exists(mp) else dict(shards={}, n_laws=0)
idx_p = f'{RD}/index.json'; idx = json.load(open(idx_p)) if os.path.exists(idx_p) else dict(packages=[], kraje_reviewed=[], n20k_reviewed=0)
# ---- what is due
due = []
if a.auto:
    for o in plan['order']:
        ks = cur.get('kraje', {}).get(o['iso']) or {}
        if ks.get('final_flushed') and o['iso'] not in idx['kraje_reviewed']: due.append(('kraj', o['iso']))
    n20 = man.get('n_laws', 0) // 20000
    if n20 > idx.get('n20k_reviewed', 0): due.append(('20k', n20 * 20000))
    if not due: log('nothing due', dict(trigger=a.trigger, packed=man.get('n_laws', 0))); sys.exit(0)
elif a.now: due.append(('kraj', a.kraj) if a.kraj else ('manual', None))
else: print(__doc__); sys.exit(1)
T1_IDS = {f"CZ-SPP-{r['id']}" for r in it(f'{B}/t1/docs.jsonl')}
def build(tag, kraj_filter):
    ts = time.strftime('%Y%m%dT%H%M%S'); rnd = random.Random(a.seed if a.seed is not None else int(time.time()))
    per = collections.OrderedDict()
    for o in plan['order']:
        if kraj_filter and o['iso'] != kraj_filter: continue
        ks = cur.get('kraje', {}).get(o['iso']) or {}
        c = collections.Counter(); last = {}
        for r in it(f"{ROOT}/docs/{o['iso']}.jsonl"): last[r['id']] = (r.get('detail_http'), r.get('text_method'), bool((r.get('meta') or {}).get('has_text')))
        for i, (http, tm, has) in last.items():
            c['ledger_docs'] += 1; c['detail_200'] += http == 200; c['has_text_link'] += has
            if tm == 'pdf_ocr_pending':
                c['ocr_needed'] += 1
                if os.path.exists(f'{ROOT}/ocr/{i}.txt'): c['ocr_done'] += 1
                else: c['ocr_pending'] += 1
            if tm in ('extract_error',) or (tm or '').startswith('unsupported_'): c[f'text_method:{tm}'] += 1
        per[o['iso']] = dict(name=o['name'], probe_count=o['probe_count'], listing_total=ks.get('listing_total'), targets=ks.get('targets'), drops=ks.get('drops'),
                             fetch_done=ks.get('fetch_done'), final_flushed=ks.get('final_flushed'), **dict(c), packed=0, packed_empty_text=0, packed_articles=0)
    # ---- shards: verify sha256, stream laws, reservoir sample 20, duplicates
    ids = collections.Counter(); groups = collections.Counter(); sample = []; nseen = 0; sha_bad = []; empty = 0; methods = collections.Counter()
    for name, s in sorted(man['shards'].items()):
        if kraj_filter and s['kraj_iso'] != kraj_filter: continue
        p = f'{ROOT}/index/laws_shards/{name}'; h = hashlib.sha256()
        with open(p, 'rb') as f:
            for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
        if h.hexdigest() != s['sha256']: sha_bad.append(name)
        for rec in it(p):
            law = rec['law']; md = json.loads(law.get('metadata_json') or '{}'); sm = md.get('spp_metadata') or {}
            ids[law['id']] += 1; k = s['kraj_iso']; per.setdefault(k, dict(packed=0, packed_empty_text=0, packed_articles=0))
            per[k]['packed'] += 1; per[k]['packed_articles'] += len(rec['articles']); e = not (law.get('text') or '').strip(); per[k]['packed_empty_text'] += e; empty += e
            methods[md.get('text_method')] += 1
            if sm.get('ico') and sm.get('Číslo právního předpisu'): groups[(sm.get('ico'), sm.get('Druh právního předpisu'), sm.get('Číslo právního předpisu'))] += 1
            nseen += 1
            if len(sample) < 20: sample.append((k, rec))
            else:
                j = rnd.randrange(nseen)
                if j < 20: sample[j] = (k, rec)
    dup_t2 = sum(v - 1 for v in ids.values() if v > 1); dup_vs_t1 = sum(1 for i in ids if i in T1_IDS)
    dup_groups = sum(1 for v in groups.values() if v > 1); dup_group_extra = sum(v - 1 for v in groups.values() if v > 1)
    # ---- 20-item hand check
    use_dict = not a.no_dict and memavail() >= 4500; checks = []
    for k, rec in sample:
        law = rec['law']; arts = rec['articles']; flags = []
        miss = [c for c in LAW_COLS if c not in law]; amiss = sorted({c for x in arts for c in ART_COLS if c not in x})
        if miss: flags.append(f'law_fields_missing:{miss}')
        if amiss: flags.append(f'article_fields_missing:{amiss}')
        if not re.fullmatch(r'CZ-SPP-SPP[A-Z0-9]+', law.get('id') or ''): flags.append('bad_id')
        chars = len(re.sub(r'\s', '', law.get('text') or ''))
        if chars == 0: flags.append('empty_text')
        elif chars < 300: flags.append('short_text<300')
        if not (law.get('jurisdiction') or '').startswith(k) and law.get('jurisdiction') != 'CZ': flags.append(f"jurisdiction {law.get('jurisdiction')} not in {k}")
        if law.get('jurisdiction') == 'CZ': flags.append('jurisdiction_fallback_CZ')
        for f in ('date', 'date_issued', 'retrieved_at'):
            v = law.get(f)
            if v and not re.match(r'\d{4}-\d{2}-\d{2}', v): flags.append(f'bad_{f}')
        if not law.get('date_issued'): flags.append('no_date_issued')
        if law.get('law_status') not in ('current', 'repealed') and law.get('law_status') is not None: flags.append(f"law_status={law.get('law_status')}")
        if not (law.get('source_url') or '').startswith('https://sbirkapp.gov.cz/detail/SPP'): flags.append('bad_source_url')
        if (law.get('article_count') or 0) != len(arts): flags.append('article_count_mismatch')
        if not (law.get('title') or '').strip(): flags.append('no_title')
        try:
            md = json.loads(law.get('metadata_json') or '')
            if md.get('spp_id') != law['id'][7:] or md.get('kraj_iso') != k: flags.append('metadata_ids_inconsistent')
        except Exception: flags.append('metadata_json_unparseable'); md = {}
        if any(not (x.get('law_id') == law['id'] and (x.get('text') or '').strip()) for x in arts): flags.append('article_row_bad')
        dr = None
        if use_dict and chars:
            tf = f'/workspace/tmp/czrev_{os.getpid()}.txt'; open(tf, 'w').write(law['text'])
            r = subprocess.run(['nice', '-n', '19', sys.executable, '/workspace/scripts/cz_sbirkapp_collect.py', 'quality', tf], capture_output=True, text=True, timeout=600)
            os.remove(tf)
            try: dr = json.loads(r.stdout.strip().splitlines()[-1]).get('dict_ratio')
            except Exception: dr = None
            if dr is not None and dr < 0.6: flags.append('dict<0.60')
            elif dr is not None and dr < 0.85: flags.append('dict<0.85')
        hard = {'empty_text', 'bad_id', 'bad_source_url', 'metadata_json_unparseable', 'article_count_mismatch', 'dict<0.60'}
        verdict = 'fail' if any(f.split(':')[0] in hard or f.startswith('law_fields_missing') for f in flags) else ('warn' if flags else 'pass')
        checks.append(dict(id=law.get('id'), kraj=k, jurisdiction=law.get('jurisdiction'), title=(law.get('title') or '')[:90], status=law.get('law_status'),
                           date_issued=law.get('date_issued'), method=md.get('text_method'), chars=chars, articles=len(arts), dict_ratio=dr, verdict=verdict, flags=flags,
                           source_url=law.get('source_url')))
    rep = dict(ts=ts, tag=tag, trigger=a.trigger, root=ROOT, kraj_filter=kraj_filter, published=False, note='review only; no hub push',
               totals=dict(packed_laws=nseen, packed_articles=sum(v.get('packed_articles', 0) for v in per.values()), empty_text=empty,
                           duplicate_law_ids_in_t2=dup_t2, law_ids_also_in_t1=dup_vs_t1, duplicate_ico_druh_cislo_groups=dup_groups, duplicate_ico_druh_cislo_extra_entries=dup_group_extra,
                           ocr_needed=sum(v.get('ocr_needed', 0) for v in per.values()), ocr_done=sum(v.get('ocr_done', 0) for v in per.values()),
                           ocr_pending=sum(v.get('ocr_pending', 0) for v in per.values()), shards_checked=len([1 for n, s in man['shards'].items() if not kraj_filter or s['kraj_iso'] == kraj_filter]),
                           shard_sha256_mismatch=sha_bad, text_methods=dict(methods)),
               per_kraj=per, hand_check=dict(n=len(checks), dict_check=use_dict, verdicts=dict(collections.Counter(c['verdict'] for c in checks)), items=checks))
    base = f'{RD}/cz_t2_review_{ts}_{tag}'; atomic_json(base + '.json', rep)
    md = [f'# CZ T2 review package {ts} ({tag}; trigger {a.trigger})', '', f'Root `{ROOT}`. Not published.', '', '## Totals', '',
          '\n'.join(f'- {k}: {v}' for k, v in rep['totals'].items()), '', '## Per kraj', '',
          '| kraj | name | probe | listing | targets | ledger | detail 200 | packed | empty text | OCR need/done/pending | fetch done | complete |', '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for k, v in per.items():
        md.append(f"| {k} | {v.get('name')} | {v.get('probe_count')} | {v.get('listing_total')} | {v.get('targets')} | {v.get('ledger_docs', 0)} | {v.get('detail_200', 0)} | {v.get('packed')} | "
                  f"{v.get('packed_empty_text')} | {v.get('ocr_needed', 0)}/{v.get('ocr_done', 0)}/{v.get('ocr_pending', 0)} | {bool(v.get('fetch_done'))} | {bool(v.get('final_flushed'))} |")
    md += ['', f"## 20-item hand check: {rep['hand_check']['verdicts']} (dict check {'on' if use_dict else 'off'})", '',
           '| id | kraj | jurisdiction | status | issued | method | chars | arts | dict | verdict | flags |', '|---|---|---|---|---|---|---|---|---|---|---|']
    for c in checks: md.append(f"| {c['id']} | {c['kraj']} | {c['jurisdiction']} | {c['status']} | {c['date_issued']} | {c['method']} | {c['chars']} | {c['articles']} | {c['dict_ratio']} | {c['verdict']} | {'; '.join(c['flags'])} |")
    open(base + '.md', 'w').write('\n'.join(md) + '\n')
    log('REVIEW PACKAGE', base + '.json', rep['totals'], rep['hand_check']['verdicts'])
    return base + '.json'
for kind, val in due:
    if kind == 'kraj': out = build(f'kraj_{val}' if val else 'all', val); idx['kraje_reviewed'] = sorted(set(idx['kraje_reviewed']) | ({val} if a.auto else set()))
    elif kind == '20k': out = build(f'every20k_{val}', None); idx['n20k_reviewed'] = val // 20000
    else: out = build('manual', None)
    idx['packages'].append(dict(path=out, kind=kind, value=val, trigger=a.trigger, ts=time.strftime('%Y-%m-%dT%H:%M:%S%z')))
    atomic_json(idx_p, idx)
