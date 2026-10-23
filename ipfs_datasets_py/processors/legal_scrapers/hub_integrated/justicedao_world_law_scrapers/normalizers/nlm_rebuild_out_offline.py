#!/usr/bin/env python3
"""OFFLINE rebuild of out/{articles,laws} from cached raw (manifest + xml) for s=ok scan rows.
Replicates nl_municipal_collect.process_id (from manifest parse onward) using the collector's own helpers
(parse_manifest, nlm_split.parse_meta/split_cvdr, Authorities.match, build_law, gz_write) but:
  - NO network (cache-only; missing raw -> skip), NO raw deletion, NO scan-chunk writes.
  - existing out files are kept unless --force.
Usage: nlm_rebuild_out_offline.py [--limit N] [--force]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, os, json, gzip, time, datetime, importlib.util, collections
spec = importlib.util.spec_from_file_location('nlc', '/workspace/scripts/nl_municipal_collect.py'); C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
def nonet(*a, **k): raise RuntimeError('network disabled in offline rebuild')
C.F.get = nonet
C.AUTH = C.Authorities()
for d in (C.OUTA, C.OUTL): d.mkdir(parents=True, exist_ok=True)
limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else None; force = '--force' in sys.argv
recs = {}
for r in C.load_scan(): recs.setdefault(r['id'], r)
ok = sorted([r for r in recs.values() if r.get('s') == 'ok'], key=lambda r: -r['id'])
if limit: ok = ok[:limit]
cnt = collections.Counter(); mism = []; t0 = time.time(); today = datetime.date.today().isoformat()
for n, r in enumerate(ok, 1):
    i = r['id']; lid = f'CVDR{i}'
    if not force and (C.OUTL / f'{lid}.json.gz').exists() and (C.OUTA / f'{lid}.jsonl.gz').exists(): cnt['exists'] += 1; continue
    pm = C.RAWM / f'{lid}.xml.gz'
    if not pm.exists(): cnt['skip_no_manifest'] += 1; continue
    try: man = C.parse_manifest(gzip.decompress(pm.read_bytes()))
    except Exception as e: cnt['skip_manifest_bad'] += 1; mism.append((lid, 'manifest_bad', repr(e)[:100])); continue
    cands = [e for e in man['exprs'] if not e['deleted']]; chosen = None; why = None
    for e in cands[:4]:
        px = C.RAWX / f"{lid}_{e['expr']}.xml.gz"
        if not px.exists(): why = f"raw_xml_missing_expr{e['expr']}"; break
        raw = gzip.decompress(px.read_bytes()); meta = C.nlm_split.parse_meta(raw)
        if meta.get('inwerkingtreding') and meta['inwerkingtreding'] > today: continue
        chosen = (e, f"{C.BASE}/cvdr/{lid}/{e['expr']}/xml/{e['item']}", raw, meta); break
    if chosen is None: cnt['skip_' + (why.split('_expr')[0] if why else 'no_inforce_expr')] += 1; mism.append((lid, why or 'no_inforce_expr')); continue
    e, url, raw, meta = chosen
    if e['expr'] != r.get('expr'): cnt['expr_differs_from_scan'] += 1; mism.append((lid, 'expr', r.get('expr'), e['expr']))
    uit = meta.get('uitwerkingtreding')
    if uit and uit <= today: cnt['now_expired'] += 1; mism.append((lid, 'now_expired', uit)); continue
    auth, method, conflict = C.AUTH.match(man['owms'], meta.get('creator_scheme'), meta.get('creator'))
    if auth is None or not auth['current']: cnt['now_out_of_scope'] += 1; mism.append((lid, 'out_of_scope')); continue
    if auth['tooi_code'] != r.get('auth') or auth['jurisdiction'] != r.get('jur') or auth['type'] != r.get('atype'): cnt['auth_differs_from_scan'] += 1; mism.append((lid, 'auth', r.get('auth'), auth['tooi_code']))
    try: rows, st, full = C.nlm_split.split_cvdr(raw, lid, url, e['expr'])
    except Exception as ex: cnt['split_fail'] += 1; mism.append((lid, 'split_fail', repr(ex)[:100])); continue
    if not rows: cnt['no_rows'] += 1; mism.append((lid, 'no_rows')); continue
    if len(rows) != r.get('rows'): cnt['rows_differ_from_scan'] += 1; mism.append((lid, 'rows', r.get('rows'), len(rows)))
    # NOTE: raw mtime is the copy-in restore time, not the original fetch time (retrieved_at is approximate for rebuilt rows)
    fetched_at = datetime.datetime.fromtimestamp((C.RAWX / f"{lid}_{e['expr']}.xml.gz").stat().st_mtime, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    law = C.build_law(i, man, e, url, raw, meta, auth, method, rows, st, full, today, fetched_at)
    tmp = C.OUTA / f'{lid}.jsonl.gz.tmp'
    with gzip.open(tmp, 'wt', encoding='utf-8') as f:
        for x in rows: f.write(json.dumps(x, ensure_ascii=False) + '\n')
    os.replace(tmp, C.OUTA / f'{lid}.jsonl.gz'); C.gz_write(C.OUTL / f'{lid}.json.gz', json.dumps(law, ensure_ascii=False).encode())
    cnt['rebuilt'] += 1; cnt['rebuilt_' + auth['type']] += 1
    if n % 100 == 0:  # gentle: short pause every 100 rebuilt rows; pause (not stop) while MemAvail < 4200MiB until >= 4400MiB (max 10 min, then stop)
        time.sleep(0.5); m = C.memavail(); waited = 0
        while m < 4200 and waited < 600: time.sleep(5); waited += 5; m2 = C.memavail(); m = m2 if m2 >= 4400 else min(m2, 4199)
        if waited >= 600: C.log('MemAvail stayed < 4400MB for 10 min -> stop (resume-safe)'); break
        if waited: C.log(f'paused {waited}s for MemAvail, now {C.memavail()}MB')
    if n % 1000 == 0:
        m = C.memavail(); C.log('rebuild progress', n, '/', len(ok), dict(cnt), f'{time.time()-t0:.0f}s', f'mem={m}MB rss={C.rss_mb()}MB')
C.log('REBUILD DONE', len(ok), dict(cnt), f'{time.time()-t0:.0f}s', f'mem={C.memavail()}MB rss={C.rss_mb()}MB')
json.dump(dict(generated=C.now_pt(), n_ok_rows=len(ok), counts=dict(cnt), mismatches=mism[:500], n_mismatches=len(mism)),
          open('/workspace/logs/nlm_rebuild_out_offline_20261005.json', 'w'), indent=1)
