#!/usr/bin/env python3
"""Build ES-<CCAA> law/article rows from raw BOE API XML, mirroring the existing ipfs_spain_laws row construction
(scrapers/collect_boe.py build_record + collection_record.v1 wrapping). Offline. Usage: es_build.py [ID,ID,...]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, os, json, gzip, time, collections, importlib.util, re
from pathlib import Path
from datetime import datetime, timezone
B = Path('{_CORPORA}/es_subnational'); RAW = B / 'raw'; OUTD = B / 'parsed'; INST = B / 'instruments'
OUTD.mkdir(exist_ok=True); INST.mkdir(exist_ok=True)
spec = importlib.util.spec_from_file_location('collect_boe', B / 'es_tip/scrapers/collect_boe.py'); CB = importlib.util.module_from_spec(spec); spec.loader.exec_module(CB)
DEP = {'8010': 'ES-AN', '8020': 'ES-AR', '8150': 'ES-AS', '8121': 'ES-IB', '8120': 'ES-IB', '8030': 'ES-CN', '8040': 'ES-CB', '9531': 'ES-CL',
       '8060': 'ES-CM', '8070': 'ES-CT', '8080': 'ES-EX', '8090': 'ES-GA', '8131': 'ES-MD', '8100': 'ES-MC', '8170': 'ES-NC', '8140': 'ES-PV',
       '8110': 'ES-RI', '8162': 'ES-VC', '8161': 'ES-VC'}
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
def J(o): return json.dumps(o, ensure_ascii=False, separators=(',', ':'))
def status(md):
    if md.get('estatus_derogacion') == 'S': return 'repealed'
    if md.get('vigencia_agotada') == 'S': return 'historical'
    return 'current'
def build(item):
    ident = item['identificador']; raw = RAW / f'{ident}.xml.gz'
    rec = CB.build_record(ident, item, gzip.decompress(raw.read_bytes()))
    iso = DEP[item['departamento']['codigo']]; lid = f'{iso}-{ident}'
    ret = datetime.fromtimestamp(raw.stat().st_mtime, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    md = rec['metadata']; md['retrieved_at'] = ret; md['collection'] = 'legislacion-consolidada-autonomica'
    md['schema'] = 'collection_record.v1'; md['collector'] = 'es-boe-autonomico'
    md['rights'] = {'not_legal_advice': True, 'official_reuse_url': 'https://www.boe.es/informacion/aviso_legal/index.php',
                    'attribution': 'Fuente de los datos: Agencia Estatal Boletín Oficial del Estado', 'license': CB.LICENSE}
    md['jurisdiction_iso_3166_2'] = iso; md['departamento_codigo'] = item['departamento']['codigo']; md['ambito_codigo'] = '2'
    md['rango_codigo'] = item['rango']['codigo']; md['diario_numero'] = item.get('diario_numero')
    st = status(md)
    arts = []; seen = collections.Counter(); dup = 0
    for d in rec['documents']:
        bid = d['metadata']['block_id']; seen[bid] += 1
        aid = f'{lid}/{bid}' if seen[bid] == 1 else f'{lid}/{bid}~{seen[bid]}'
        if seen[bid] > 1: dup += 1
        arts.append(dict(law_id=lid, id=aid, title=d['title'], text=d['text'], source_url=d['source_url'], document_number=bid,
                         article_number=None, record_type=None, metadata_json=J({'metadata': d['metadata']})))
    md['duplicate_block_ids_suffixed'] = dup
    jp = INST / f'{CB.safe_id(lid)}.json'; rec['id'] = lid; rec['jurisdiction'] = iso; jp.write_text(J(rec), encoding='utf-8')
    law = dict(id=lid, title=rec['title'], text=rec['text'], source_url=rec['source_url'], source_type='boe', jurisdiction=iso, country='Spain',
               language='es', eli=rec.get('eli'), date=rec.get('date_issued'), date_issued=rec.get('date_issued'), retrieved_at=ret, license=CB.LICENSE,
               law_status=st, identifier=lid, official_identifier=ident, article_count=len(arts), json_path=str(jp),
               metadata_json=J({'metadata': md, 'schema_version': 'collection_record.v1', 'record_type': 'law', 'law_identifier': lid, 'is_current': st == 'current'}))
    return law, arts
def main():
    cat = json.load(open(B / 'catalog_autonomico.json'))['data']
    only = set(sys.argv[1].split(',')) if len(sys.argv) > 1 else None
    tag = 'handcheck' if only else 'all'
    lw = gzip.open(OUTD / f'laws_{tag}.jsonl.gz', 'wt'); aw = gzip.open(OUTD / f'articles_{tag}.jsonl.gz', 'wt')
    stats = collections.Counter(); missing = []; errs = []
    for n, it in enumerate(cat, 1):
        if only and it['identificador'] not in only: continue
        if not (RAW / f"{it['identificador']}.xml.gz").exists(): missing.append(it['identificador']); continue
        while memavail() <= 4600:
            if memavail() <= 3584: print('MEM TERM', flush=True); sys.exit(3)
            time.sleep(30)
        try: law, arts = build(it)
        except Exception as e: errs.append((it['identificador'], repr(e)[:300])); continue
        lw.write(J(law) + '\n'); [aw.write(J(a) + '\n') for a in arts]
        stats['laws'] += 1; stats['articles'] += len(arts)
        if n % 500 == 0: print(time.strftime('%H:%M:%S'), n, dict(stats), flush=True)
    lw.close(); aw.close()
    json.dump(dict(stats=stats, missing_raw=missing, errors=errs), open(OUTD / f'build_stats_{tag}.json', 'w'), indent=1)
    print('BUILD DONE', dict(stats), 'missing', len(missing), 'errors', len(errs), flush=True)
if __name__ == '__main__': main()
