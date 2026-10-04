"""Produce pinned native 768D source contexts without reading formal targets.

Sources come from the previously frozen source-only identity artifact. Matching
cache entries retain their complete upstream receipts; duplicate source texts
share one actual encoder execution. No 8D/384D vectors are padded or relabelled.
"""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
HELPERS = ROOT / 'ipfs_datasets_py/logic/formalization/autoencoder'
SPLITS = ('train', 'tuning', 'challenge', 'oov')
SCHEMA = 'legal-native768-context-preparation/v1'
SOURCE_FIELDS = {'id', 'source_text', 'source_sha256', 'family_group'}
RECEIPT_FIELDS = {'schema','id','source_sha256','profile_id','dimension','embedding',
    'token_count_including_special_tokens','token_input_sha256','truncated','normalized','asset_manifest_sha256'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
        allow_nan=False).encode()).hexdigest()


def ref(path):
    p = Path(path).resolve()
    raw = p.read_bytes()
    return {'path': str(p), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def read(reference):
    require(type(reference) is dict and set(reference) == {'path','sha256','bytes'} and ref(reference['path']) == reference,
        'closed pinned artifact changed')
    require(reference['bytes'] <= 128 * 1024**2, 'bounded JSON artifact required')
    def unique(items):
        result = {}
        for key,value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    return json.loads(Path(reference['path']).read_bytes(), object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON ' + value)))


def write(path,value):
    with Path(path).open('xb') as handle:
        handle.write(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode())
    return ref(path)


def source_splits(value):
    require(type(value) is dict and set(value) == set(SPLITS), 'four exact source-only splits required')
    seen, source_identity, result = set(), {}, {}
    for split in SPLITS:
        rows=value[split]
        require(type(rows) is list and rows and len(rows) <= 4096, 'bounded nonempty source split required')
        result[split]=[]
        for row in rows:
            require(type(row) is dict and set(row) <= SOURCE_FIELDS and {'id','source_text','source_sha256'} <= set(row),
                'source artifact must not contain targets or other fields')
            require(type(row['id']) is str and 0 < len(row['id']) <= 256 and row['id'] not in seen, 'unique bounded source ID required')
            text=row['source_text']
            require(type(text) is str and text.strip() and '\0' not in text and len(text) <= 65536, 'bounded source text required')
            sha=hashlib.sha256(text.encode()).hexdigest()
            require(sha == row['source_sha256'], 'source hash differs')
            require(sha not in source_identity or source_identity[sha] == text, 'source hash collision')
            source_identity[sha]=text
            seen.add(row['id'])
            result[split].append(deepcopy(row))
    require(sum(len(r) for r in result.values()) <= 4096, 'full source cohort exceeds producer bound')
    return result


def valid_native_receipt(receipt, *, profile_id, asset_sha256):
    require(type(receipt) is dict and set(receipt) == RECEIPT_FIELDS, 'closed native receipt required')
    require(receipt['schema'] == 'gte-multilingual-embedding-receipt/v1' and receipt['profile_id'] == profile_id
        and receipt['asset_manifest_sha256'] == asset_sha256 and type(receipt['dimension']) is int and receipt['dimension'] == 768
        and receipt['normalized'] is True and receipt['truncated'] is False, 'native source profile differs')
    require(type(receipt['id']) is str and receipt['id'] and all(type(receipt[k]) is str and re.fullmatch('[0-9a-f]{64}', receipt[k])
        for k in ('source_sha256','token_input_sha256')), 'native source identity/hash invalid')
    vector=receipt['embedding']
    require(type(vector) is list and len(vector) == 768 and all(type(v) in (int,float) and math.isfinite(v) for v in vector)
        and abs(math.hypot(*vector) - 1.) <= 1e-4, 'finite normalized768 vector required')
    require(type(receipt['token_count_including_special_tokens']) is int and 1 <= receipt['token_count_including_special_tokens'] <= 8192,
        'native token bound differs')


def cache_index(references, *, producer, asset_sha256):
    result={}
    for reference in references:
        report=read(reference)
        require(report['schema'] == producer.SCHEMA and report['status'] == 'completed' and report['model_inference_executed'] is True
            and report['training_executed'] is False and report['proof_authority'] is False and report['source_semantics_verified'] is False,
            'actual complete-checkpoint encoder production required')
        require(report['implementation'] == producer._implementation() and report['profile_id'] == producer.PROFILE_ID
            and report['assets']['manifest_sha256'] == asset_sha256 and report['receipt_count'] == report['input_row_count'] == len(report['receipts']),
            'cached producer identity/coverage differs')
        loading=report['complete_checkpoint_loading']
        require(loading['architecture'] == 'NewForTokenClassification' and loading['tensor_count'] == 138 and loading['classifier_loaded'] is True
            and not any(loading[k] for k in ('missing_keys','unexpected_keys','mismatched_keys','error_msgs'))
            and report['dense_path_verification']['encoder_and_complete_hidden_states_bitwise_equal'] is True,
            'complete checkpoint/dense-path evidence required')
        for receipt in report['receipts']:
            valid_native_receipt(receipt, profile_id=producer.PROFILE_ID, asset_sha256=asset_sha256)
            key=receipt['source_sha256']
            require(key not in result or result[key]['receipt']['embedding'] == receipt['embedding'], 'conflicting cached vectors for same source')
            result.setdefault(key, {'receipt': receipt, 'producer_report': reference})
    return result


def make_context(source, upstream, *, source_artifact, producer_sha256, reused):
    receipt=upstream['receipt']
    require(source['source_sha256'] == receipt['source_sha256'], 'context and native source differ')
    vector=deepcopy(receipt['embedding'])
    stage={'schema':'legal-native768-stage-receipt/v1','id':source['id'],'source_sha256':source['source_sha256'],
        'dimension':768,'stage':'native768','representation_id':receipt['profile_id'],'vector_sha256':digest(vector),
        'producer_sha256':producer_sha256,'source_artifact':source_artifact,'producer_report':upstream['producer_report'],
        'upstream_receipt_sha256':digest(receipt),'upstream_receipt_id':receipt['id'],
        'identity_join':'exact_source_sha256','cache_reused':reused,
        'target_access':False,'training_executed':False,'source_semantics_verified':False,'proof_authority':False}
    stage['receipt_sha256']=digest(stage)
    return {'id':source['id'],'source_sha256':source['source_sha256'],'context':vector,
        'context_sha256':digest(vector),'native_stage_receipt':stage}


def trained384_contexts(config, sources):
    """Replay authentic cached LegalIR384 stage validation, with no regeneration."""
    if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_native_conditioning as native
    bundle=read(config['trained384_bundle'])
    identities={r['id']:r for rows in sources.values() for r in rows}
    ordered=[{'id':row['id'],'source_text':identities[row['id']]['source_text']} for row in bundle['rows']]
    native.stage_rows(bundle,stage='trained384',sources=ordered)
    require(len(ordered) == len(identities),'complete trained384 source coverage required')
    require(ref(bundle['package']['path'])['sha256'] == bundle['package']['sha256'],'trained384 package bytes changed')
    raw=read(config['trained384_contexts'])
    require(set(raw) == set(SPLITS),'trained384 split coverage differs')
    vectors={row['id']:row for row in bundle['rows']}
    for split in SPLITS:
        require(len(raw[split]) == len(sources[split]),'trained384 source count differs')
        for source,row in zip(sources[split],raw[split]):
            stage=vectors[source['id']]['stages']['trained384']
            require(row == {'id':source['id'],'source_sha256':source['source_sha256'],'context':stage['vector'],
                'context_sha256':digest(stage['vector']),'native_stage_receipt':stage['receipt']},'trained384 source/stage receipt differs')
    metadata={'dimension':384,'representation_id':'actual_frozen_legal_ir/trained384/v1',
        'producer_sha256':digest({'native':ref(native.__file__)['sha256'],'package':bundle['package']['sha256'],'stage':'trained384'}),
        'lineage_artifacts':[config['trained384_bundle'],config['trained384_contexts'],ref(bundle['package']['path'])]}
    return raw,metadata


def verify_manifest(manifest_ref, *, sources=None):
    """Rejoin every supplied context to source identity and actual producer rows."""
    manifest=read(manifest_ref)
    require(manifest['schema'] == 'legal-native768-context-manifest/v1' and manifest['completed'] is True
        and manifest['target_access'] is False and manifest['training_executed'] is False and manifest['proof_authority'] is False,
        'completed source-only unqualified context manifest required')
    original=source_splits(read(manifest['source_artifact']))
    if sources is not None:
        require(source_splits(sources) == original, 'runner source identities differ')
    config=read(manifest['configuration'])
    availability=read(config['learned8_availability'])
    require(manifest['unavailable_representations'] == {'learned8':{'reason':availability['reason'],'evidence':[config['learned8_availability']]}}, 'unavailable8 evidence differs')
    require(config['sources'] == manifest['source_artifact'], 'configured source artifact differs')
    for reference in manifest['implementation_files']:
        require(ref(reference['path']) == reference, 'native context implementation changed')
    if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
    from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_768_complete as producer
    cached=cache_index(manifest['producer_reports'], producer=producer, asset_sha256=config['asset_manifest']['sha256'])
    representation=manifest['representations']['native768']
    require(representation['dimension'] == 768 and representation['representation_id'] == producer.PROFILE_ID
        and representation['producer_sha256'] == digest({r['path']:r['sha256'] for r in manifest['implementation_files']}),
        'representation identity or producer differs')
    require(set(manifest['representations']) == {'native768','trained384'},'both authentic context representations required')
    original384,metadata384=trained384_contexts(config,original)
    supplied384=manifest['representations']['trained384']
    require({k:v for k,v in supplied384.items() if k != 'contexts'} == metadata384,'trained384 representation metadata differs')
    for split in SPLITS:
        expected384=original384[split]
        if manifest['pilot_unique_sources'] is not None:
            expected384=[r for r in expected384 if r['source_sha256'] in manifest['selected_source_sha256']]
        require(read(supplied384['contexts'][split]) == expected384,'exported trained384 contexts differ')
    context_count=0
    for split in SPLITS:
        rows=read(representation['contexts'][split])
        expected=original[split]
        if manifest['pilot_unique_sources'] is not None:
            allowed=set(manifest['selected_source_sha256'])
            expected=[s for s in expected if s['source_sha256'] in allowed]
        require(len(rows) == len(expected), 'context/source split count differs')
        for source,row in zip(expected,rows):
            require(set(row) == {'id','source_sha256','context','context_sha256','native_stage_receipt'}
                and row['id'] == source['id'] and row['source_sha256'] == source['source_sha256'], 'ordered context/source identity differs')
            stage=row['native_stage_receipt']
            require(type(stage['cache_reused']) is bool and all(stage[k] is False for k in ('target_access','training_executed','source_semantics_verified','proof_authority')), 'false authority flags required')
            expected_reuse=stage['producer_report'] in config['cache_reports']
            require(stage['cache_reused'] is expected_reuse,'cache reuse origin differs')
            require(stage['receipt_sha256'] == digest({k:v for k,v in stage.items() if k != 'receipt_sha256'}), 'stage receipt hash differs')
            upstream=cached[source['source_sha256']]
            expected_row=make_context(source,upstream,source_artifact=manifest['source_artifact'],
                producer_sha256=representation['producer_sha256'],reused=stage['cache_reused'])
            require(row == expected_row, 'source/vector/producer receipt rejoin differs')
            context_count+=1
    require(context_count == manifest['context_count'], 'context total differs')
    return {'schema':'legal-native768-context-inspection/v1','status':'source_vector_producer_joins_verified',
        'context_count':context_count,'manifest':manifest_ref,'encoder_reexecuted':False,
        'target_access':False,'training_executed':False,'source_semantics_verified':False,'proof_authority':False}


def run(config_path, *, expected_sha256, output):
    configuration=ref(config_path)
    require(configuration['sha256'] == expected_sha256, 'config hash differs')
    config=read(configuration)
    require(set(config) == {'schema','sources','asset_manifest','model_directory','code_directory','cache_reports','resources','batch_size','pilot_unique_sources','trained384_bundle','trained384_contexts','learned8_availability'}
        and config['schema'] == SCHEMA, 'closed native context configuration required')
    sources=source_splits(read(config['sources']))
    availability=read(config['learned8_availability'])
    require(availability['available_for_this_source_corpus'] is False and availability['training_executed'] is False, 'explicit unavailable learned8 evidence required')
    require(type(config['batch_size']) is int and 1 <= config['batch_size'] <= 16, 'bounded native batch required')
    pilot=config['pilot_unique_sources']
    require(pilot is None or type(pilot) is int and 1 <= pilot <= 128, 'pilot bound differs')
    unique={s['source_sha256']:s['source_text'] for rows in sources.values() for s in rows}
    selected=sorted(unique)[:pilot] if pilot is not None else sorted(unique)
    spec=importlib.util.spec_from_file_location('_native_context_resources',HELPERS/'gte_worker_contract.py')
    resource_helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(resource_helper)
    resources=resource_helper.configure_cpu_process(config['resources'])
    require(len(selected) <= config['resources']['max_rows'], 'resource row bound exceeded')
    if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
    from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_768_complete as producer
    require(ref(config['asset_manifest']['path']) == config['asset_manifest'], 'asset manifest changed')
    assets=producer.reference._PROFILE.inspect_local_assets(config['asset_manifest']['path'],
        expected_sha256=config['asset_manifest']['sha256'],model_directory=config['model_directory'],code_directory=config['code_directory'])
    require(assets['status'] == 'available','pinned complete native assets unavailable')
    cache=cache_index(config['cache_reports'],producer=producer,asset_sha256=config['asset_manifest']['sha256'])
    missing=[key for key in selected if key not in cache]
    output=Path(output).resolve();require(not output.exists(),'fresh native context output required');output.mkdir(parents=True)
    implementations=[ref(__file__),ref(producer.__file__),ref(producer.reference.__file__),ref(producer.reference._PROFILE.__file__),ref(resource_helper.__file__)]
    producer_sha256=digest({r['path']:r['sha256'] for r in implementations})
    write(output/'plan.json',{'schema':'legal-native768-context-plan/v1','configuration':configuration,
        'implementation_files':implementations,'source_count':sum(map(len,sources.values())),'selected_unique_source_count':len(selected),
        'cached_unique_source_count':len(selected)-len(missing),'encoder_unique_source_count':len(missing),
        'target_access':False,'training_executed':False,'proof_authority':False})
    write(output/'resources.json',resources)
    print(json.dumps({'phase':'admitted','sources':len(selected),'encode':len(missing),'cache':len(selected)-len(missing)}),flush=True)
    start=time.monotonic();reports=list(config['cache_reports'])
    if missing:
        production=producer.embed_rows([{'id':'source-sha256:'+key,'source_text':unique[key]} for key in missing],
            manifest_path=config['asset_manifest']['path'],expected_manifest_sha256=config['asset_manifest']['sha256'],
            model_directory=config['model_directory'],code_directory=config['code_directory'],batch_size=config['batch_size'])
        production_ref=write(output/'producer-report.json',production);reports.append(production_ref)
        produced=cache_index([production_ref],producer=producer,asset_sha256=config['asset_manifest']['sha256'])
        require(set(produced) == set(missing), 'new encoder source coverage differs');cache.update(produced)
    seconds=time.monotonic()-start
    contexts={};total=0
    old384,metadata384=trained384_contexts(config,sources)
    contexts384={split:write(output/('contexts-trained384-'+split+'.json'),[r for r in old384[split] if r['source_sha256'] in selected]) for split in SPLITS}
    for split in SPLITS:
        rows=[make_context(s,cache[s['source_sha256']],source_artifact=config['sources'],producer_sha256=producer_sha256,
            reused=s['source_sha256'] not in missing) for s in sources[split] if s['source_sha256'] in selected]
        contexts[split]=write(output/('contexts-native768-'+split+'.json'),rows);total+=len(rows)
    manifest={'schema':'legal-native768-context-manifest/v1','completed':True,'configuration':configuration,
        'source_artifact':config['sources'],'implementation_files':implementations,'producer_reports':reports,
        'representations':{'native768':{'dimension':768,'representation_id':producer.PROFILE_ID,'producer_sha256':producer_sha256,
            'contexts':contexts,'lineage_artifacts':[configuration,config['asset_manifest'],*reports]},
            'trained384':{**metadata384,'contexts':contexts384}},
        'context_count':total,'unique_source_count':len(selected),'selected_source_sha256':selected,
        'new_encoder_source_count':len(missing),'reused_encoder_source_count':len(selected)-len(missing),
        'execution_seconds':seconds,'pilot_unique_sources':pilot,'target_access':False,'training_executed':False,
        'source_semantics_verified':False,'proof_authority':False,
        'unavailable_representations':{'learned8':{'reason':availability['reason'],'evidence':[config['learned8_availability']]}}}
    for reference in [configuration,config['sources'],*implementations,*reports]:
        require(ref(reference['path']) == reference,'source/config/producer changed during native production')
    manifest_ref=write(output/'manifest.json',manifest)
    inspection=verify_manifest(manifest_ref);write(output/'inspection.json',inspection)
    print(json.dumps({'phase':'completed','manifest':manifest_ref,'seconds':seconds,'contexts':total,'new_unique_sources':len(missing)}),flush=True)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--expected-config-sha256',required=True)
    parser.add_argument('--output-directory',required=True);args=parser.parse_args()
    run(args.config,expected_sha256=args.expected_config_sha256,output=args.output_directory)


if __name__ == '__main__':main()
