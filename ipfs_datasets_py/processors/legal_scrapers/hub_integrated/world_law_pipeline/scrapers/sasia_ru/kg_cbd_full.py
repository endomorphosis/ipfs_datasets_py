"""Full KG local-acts scrape from cbd.minjust.gov.kg (robots: allow all; site's own public API; 1 req/s; no proxies).
Mapped organs (strict unique, _kg/kg_organ_map.jsonl) -> staged via StagedWriter into staging/sasia_ru/KG/.
Unmapped local organs -> _kg/pending/<organ_code>.jsonl (NOT staged: SCHEMA has no place_key for unresolved places),
each record carries cbd_issuing_body_id for re-matching after the Normalizer merges codes/proposed/KG_aiyl_aimaks.csv.
Resumable via _kg/full_done.jsonl (one line per organ)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, json, re, time, datetime, shutil, resource, collections
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline')); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/scrapers/sasia_ru'))
from kg_cbd_local import call, strip, d10, dtype
from archive.staging import StagedWriter
from schema import validate_record
B = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru'); W = B + '/_kg'; PEND = W + '/pending'; DONE = W + '/full_done.jsonl'
def mem_mb(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
def recs_for(organ, qid):
    pg = 1; seen = set()
    while True:
        d = call('POST', f'/GetDocuments?pageNumber={pg}&pageSize=100', json={'authoritiesId': organ['code'], 'includeInvalid': True})
        if not d or not d.get('data'): return
        for x in d['data']:
            c = x['documentCode']
            if c in seen: continue
            seen.add(c)
            doc = call('GET', f'/GetDocument?DocumentCode={c}')
            if not doc or not doc.get('editions'): continue
            # CBD authoritiesId filter is a prefix match ('2' also returns 2f12..., 21, ...): keep only this organ's own docs
            _ac = str(((doc.get('authoritiesId') or {}).get('code')) or '').strip()
            if _ac not in {str(organ['code']).strip(), str(organ.get('canon') or organ['code']).strip()}: continue
            ed = doc['editions'][-1]
            langs = [('ky', 'kg', 'nameKyr')] + ([('ru', 'ru', 'nameRus')] if (doc.get('nameRus') or '').strip() else [])
            for lang, ql, nm in langs:
                e = call('GET', f'/GetEdition?editionId={ed["id"]}&lang={ql}')
                html = (e or {}).get('contentRu') or (e or {}).get('contentKg') or ''
                text = strip(html)
                if len(text) < 200: continue
                r = {'country_code': 'KG', 'doc_id': f'cbdkg:{c}' + ('' if lang == 'ru' else ':ky'), 'source_platform': 'cbd_minjust_kg',
                     'source_url': f'https://cbd.minjust.gov.kg/{c}/edition/{ed["id"]}/{ql}', 'doc_type': dtype((doc.get('refTypeId') or {}).get('nameRus')),
                     'language': lang, 'content_format': 'html', 'html': html, 'text': text,
                     'title_native': re.sub(r'\s+', ' ', doc.get(nm) or '').strip()[:1000], 'number': doc.get('number'),
                     'adopted_date': d10(doc.get('dateAdopted')), 'published_date': d10(doc.get('datePublication')),
                     'in_force': {'Действует': True, 'Утратил силу': False}.get((doc.get('status') or {}).get('nameRus')),
                     'consolidated': len(doc['editions']) > 1, 'retrieved_at': datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
                     'source_official': True, 'source_org': 'Министерство юстиции Кыргызской Республики (ЦБД НПА)', 'source_policy': 'robots_allowed_rfc9309',
                     'issuing_body': (doc.get('authoritiesId') or {}).get('nameRus') or organ['name'], 'cbd_issuing_body_id': organ['code'],
                     'registration_number': doc.get('numberRegistration'), 'edition_id': ed['id']}
                if organ.get('canon') and organ['canon'] != organ['code']: r['cbd_canonical_body_id'] = organ['canon']
                if qid: r.update(place_id=qid, qid=qid[3:] if qid.startswith('wd:') else None, place_name=organ.get('place_ru'), place_match=organ.get('src'))
                yield r
        if pg * 100 >= d.get('totalResultsCount', 0): return
        pg += 1

def _dotted_alias(live):
    # dotted CBD organ ids -> live dashed KG-kg_cbd ids (codes/proposed/KG_aiyl_aimaks_dotted.csv); typo variants are not listed
    import csv as _c
    return {r['cbd_organ_id'].strip(): r['proposed_place_id'].strip() for r in _c.DictReader(open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/codes/proposed/KG_aiyl_aimaks_dotted.csv')))
            if r['proposed_place_id'].strip() in live}
def main():
    os.makedirs(PEND, exist_ok=True)
    mapped = {}
    for l in open(W + '/kg_organ_map.jsonl'): x = json.loads(l); mapped[x['code']] = x
    import csv
    ext = collections.defaultdict(set)
    EXT = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/codes_ext/kg_body_to_place.csv')
    if os.path.exists(EXT):
        for r in csv.DictReader(open(EXT)):
            if r['place_id'].startswith('wd:Q'): ext[r['cbd_issuing_body_id'].strip()].add(r['place_id'].strip())
    merge = json.load(open(W + '/body_id_merge.json')) if os.path.exists(W + '/body_id_merge.json') else {}
    drop = json.load(open(W + '/body_id_drop.json')) if os.path.exists(W + '/body_id_drop.json') else {}
    AMB = {r['cbd_issuing_body_id'].strip() for r in csv.DictReader(open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/codes_ext/kg_body_ambiguous.csv')))}
    kgcbd = {r['code'].strip(): r['place_id'] for r in csv.DictReader(open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/codes/place_codes.csv')))
             if r['code_system'] == 'kg_cbd_body' and r['place_id'].startswith('KG-kg_cbd:') and r['code'].strip() not in AMB}
    for _d, _p in _dotted_alias(set(kgcbd.values())).items(): kgcbd.setdefault(_d, _p)
    organs = [o for o in json.load(open(W + '/kg_local_organs.json')) if o['code'] not in drop]
    for o in organs:
        canon = merge.get(o['code'], o['code']); o['canon'] = canon
        cand = set(ext.get(canon, set()) | ext.get(o['code'], set()))
        for c in (o['code'], canon):
            if c in mapped: cand.add(mapped[c]['qid'])
        if len(cand) == 1:
            q = next(iter(cand)); base = mapped.get(o['code']) or mapped.get(canon) or {}
            mapped[o['code']] = {'qid': q, 'place_ru': base.get('place_ru') if base.get('qid') == q else None, 'src': 'organ_map' if base.get('qid') == q else 'normalizer_kg_body_to_place'}
        elif len(cand) > 1: mapped.pop(o['code'], None); print('CONFLICT', o['code'], sorted(cand), flush=True)
        elif canon in kgcbd and o['code'] not in mapped: mapped[o['code']] = {'qid': kgcbd[canon], 'place_ru': None, 'src': 'normalizer_kg_cbd_body'}
    done = {json.loads(l)['code'] for l in open(DONE)} if os.path.exists(DONE) else set()
    order = [o for o in organs if o['code'] in mapped] + [o for o in organs if o['code'] not in mapped]
    for o in order:
        if o['code'] in done: continue
        if shutil.disk_usage('/workspace').free < 35e9: print('DISK LOW <35GB; stopping', flush=True); return
        if mem_mb() > 450: print('MEM HIGH; stopping for restart', flush=True); return
        m = mapped.get(o['code']); res = {'code': o['code'], 'organ': o['name']}; n = 0
        try:
            if m:
                o2 = dict(o, place_ru=m.get('place_ru'), src=m.get('src', 'organ_map')); w = StagedWriter(B, 'KG', m['qid'], batch_prefix='cbdkgfull', chunk=200)
                for r in recs_for(o2, m['qid']):
                    err = w.add(r); n += 1
                    if err: print('INVALID', r['doc_id'], err, flush=True)
                w.flush(); res.update(status='staged', place_id=m['qid'], records=n, rejected=w.rejected, files=len(w.written))
            else:
                fin = f'{PEND}/{o["canon"]}.jsonl' if o['canon'] == o['code'] else f'{PEND}/{o["canon"]}__{o["code"]}.jsonl'; tmp = fin + '.tmp'
                with open(tmp, 'w') as f:
                    for r in recs_for(o, None):
                        f.write(json.dumps(r, ensure_ascii=False) + '\n'); n += 1
                if n: os.rename(tmp, fin)
                else: os.remove(tmp)
                res.update(status='pending', records=n)
        except Exception as e:
            res.update(status='error', error=f'{type(e).__name__}: {e}'[:200]); print(datetime.datetime.now().strftime('%H:%M:%S'), json.dumps(res, ensure_ascii=False), flush=True); continue
        print(datetime.datetime.now().strftime('%H:%M:%S'), json.dumps(res, ensure_ascii=False), flush=True)
        with open(DONE, 'a') as f: f.write(json.dumps(res, ensure_ascii=False) + '\n')
    print('finished', flush=True)
if __name__ == '__main__': main()
