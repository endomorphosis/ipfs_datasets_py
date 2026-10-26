"""Stage _kg/pending/ docs of bodies accepted under KG-kg_cbd:<organ id> (pipeline/codes/place_codes.csv, code_system kg_cbd_body).
Skips placeholder bodies (file _placeholder__* or cbd_placeholder_body=true), ambiguous bodies, held-back ids, and anything
already in _kg/kgcbd_staged.jsonl or _kg/rematched.jsonl. Validated via StagedWriter (schema.validate_record/validate_file)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv, glob, json, os, sys, shutil, collections, datetime
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline'))
from archive.staging import StagedWriter
from schema import kg_cbd_place_id
B = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru'); W = B + '/_kg'; DONE = W + '/kgcbd_staged.jsonl'; RM = W + '/rematched.jsonl'

def _dotted_alias(live):
    # dotted CBD organ ids -> live dashed KG-kg_cbd ids (codes/proposed/KG_aiyl_aimaks_dotted.csv); typo variants are not listed
    import csv as _c
    return {r['cbd_organ_id'].strip(): r['proposed_place_id'].strip() for r in _c.DictReader(open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/codes/proposed/KG_aiyl_aimaks_dotted.csv')))
            if r['proposed_place_id'].strip() in live}
def accepted():
    live = {r['place_id'] for r in csv.DictReader(open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/codes/place_codes.csv')))
            if r['code_system'] == 'kg_cbd_body' and r['place_id'].startswith('KG-kg_cbd:')}
    a = {pid[len('KG-kg_cbd:'):]: pid for pid in live}
    a.update(_dotted_alias(live)); return a
AMB = {r['cbd_issuing_body_id'].strip() for r in csv.DictReader(open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/codes_ext/kg_body_ambiguous.csv')))}
def done_ids():
    s = set()
    for f in (DONE, RM):
        if os.path.exists(f): s |= {json.loads(l)['code'] for l in open(f) if l.strip()}
    return s
def main():
    acc = accepted(); dn = done_ids(); st = collections.Counter()
    for f in sorted(glob.glob(W + '/pending/*.jsonl')):
        fid = os.path.basename(f)[:-6]; code = fid.split('__')[0]
        if fid.startswith('_placeholder'): st['skip_placeholder'] += 1; continue
        if fid in dn: st['already'] += 1; continue
        if code in AMB: st['skip_ambiguous'] += 1; continue
        if code not in acc: st['not_accepted'] += 1; continue
        if shutil.disk_usage('/workspace').free < 35e9: print('DISK LOW; stopping', flush=True); break
        q = kg_cbd_place_id(acc[code][len('KG-kg_cbd:'):]); w = StagedWriter(B, 'KG', q, batch_prefix='cbdkgcbd', chunk=200); n = rej = ph = 0
        for l in open(f):
            r = json.loads(l)
            if r.get('cbd_placeholder_body'): ph += 1; continue
            r['place_id'] = q; r.pop('qid', None); r.setdefault('cbd_issuing_body_id', code); r['place_match'] = 'normalizer_kg_cbd_body'
            e = w.add(r)
            if e: rej += 1; print('INVALID', r.get('doc_id'), e, flush=True)
            else: n += 1
        w.flush(); st['bodies'] += 1; st['docs'] += n; st['rejected'] += rej
        with open(DONE, 'a') as o: o.write(json.dumps({'code': fid, 'canonical': code, 'place_id': q, 'staged': n, 'rejected': rej, 'placeholder_skipped': ph, 'files': w.written, 'at': datetime.datetime.now().strftime('%F %T')}) + '\n')
        print(datetime.datetime.now().strftime('%T'), fid, q, 'staged', n, 'rejected', rej, flush=True)
    print(datetime.datetime.now().strftime('%F %T'), dict(st), flush=True)
if __name__ == '__main__': main()
