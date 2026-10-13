"""Prepare a bounded additive temporal-adapter archive from qualified raw pins.

No model/checkpoint parser or private global-body read. The only optional Hub
request is --snapshot-baseline; ordinary preparation is local and exclusive.
"""
import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path

F = Path(__file__).resolve().parent
REPO = 'Publicus/legal-ir-autoencoder'
PREFIX = 'releases/20261013-temporal-adapter-v1'
MAX_PAYLOAD_BYTES, MAX_FILE_BYTES = 200000000, 10000000
CELLS = ('temporal-ce-control','temporal-anchor-margin')
PANELS = ('old_tune','fresh_tune','fresh_challenge','old_authored_eval','authored_dev','authored_eval','law')
READ_PINS, PRIVATE_REFERENCE_PINS, RUNTIME_PRIVATE_AUTHORITY = {}, {}, {}
PUBLIC_RUNTIME = ('pre-admission.json','scheduler-adoption.json','lease-binding.json','command.json',
    'child-identity.json','resource-observations.json','child-exit.json','group-rss-summary.json',
    'owned-group-final.json','guardian-exit.json','lease-observations.jsonl','group-rss-observations.jsonl','child.log')
SOURCE_SHA = '95bd50a7cc6e25381ad126e3d955f0816c31470ec469fb22ceca297e35115035'
SOURCE_STATE_SHA = 'fb63e61c7e2591259d40492b5ac5c020ae77f64c08e409d16b372ff7229b9aa5'

def private(path):
    path=Path(path)
    return ('private-runtime-snapshots' in path.parts or path.name in
        {'resources-start.json','resources-final.json','disk-reservations.json'}
        or path.name.startswith('ipfs-datasets-resource-scheduler-'))

def require(condition, message):
    if not condition:
        raise ValueError(message)

def brief(record):
    require(type(record) is dict and set(record) in ({'bytes', 'sha256'}, {'path', 'bytes', 'sha256'}),
            'closed raw identity required')
    require(type(record['bytes']) is int and 0 <= record['bytes'] <= MAX_PAYLOAD_BYTES
            and type(record['sha256']) is str and len(record['sha256']) == 64
            and all(c in '0123456789abcdef' for c in record['sha256']), 'bounded raw identity required')
    return {k: record[k] for k in ('bytes', 'sha256')}

def pin(path):
    path = Path(path)
    require(not private(path), 'private global bodies remain unopened')
    require(path.is_absolute() and path.resolve() == path and path.is_file() and not path.is_symlink(),
            'exact physical absolute file required')
    before = path.stat()
    require(before.st_size <= MAX_PAYLOAD_BYTES, 'raw input byte cap exceeded')
    raw = path.read_bytes(); after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) and len(raw) == before.st_size,
            'file changed during raw pin')
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())

def read(path, expected=None):
    path = Path(path)
    require('checkpoint' not in path.name and 'reference-packet' not in path.name,
            'checkpoint/reference JSON parsing prohibited')
    captured = pin(path)
    require(expected is None or captured == expected, 'consumed metadata differs from required descriptor')
    raw = path.read_bytes()
    require(brief(captured) == dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) and pin(path) == captured,
            'consumed metadata bytes differ from opening pin')
    require(str(path) not in READ_PINS or READ_PINS[str(path)] == captured, 'previous parsed identity changed')
    READ_PINS[str(path)] = captured
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key'); result[key] = value
        return result
    def finite(raw):
        result = float(raw); require(math.isfinite(result), 'nonfinite JSON number'); return result
    return json.loads(raw, object_pairs_hook=unique, parse_float=finite,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))

def write(path, raw):
    path = Path(path)
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    path.chmod(0o444)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)
    return pin(path)

def write_json(path, value):
    return write(path, (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode())

def clean(review, schema):
    require(type(review) is dict and review.get('schema') == schema and review.get('findings') == []
            and (review.get('passed') is True or review.get('status') == 'PASS')
            and ('passed' not in review or review['passed'] is True)
            and ('status' not in review or review['status'] == 'PASS'), 'clean exact qualification required')

def approved_map(review):
    require((review.get('passed') is True or review.get('status') == 'PASS') and review.get('findings') == [],
            'clean independent review required')
    require(type(review.get('artifacts')) is dict and review['artifacts'], 'raw review artifact map required')
    result = {}
    for path, expected in review['artifacts'].items():
        require(type(path) is str and ('path' not in expected or expected['path'] == path), 'review path identity differs')
        expected = brief(expected)
        if private(path):
            require(RUNTIME_PRIVATE_AUTHORITY.get(path) == expected,
                    'private identity reference must join qualified runtime metadata')
            require(path not in PRIVATE_REFERENCE_PINS or PRIVATE_REFERENCE_PINS[path] == expected,
                    'conflicting qualified private identity reference')
            PRIVATE_REFERENCE_PINS[path] = expected
            continue
        result[path] = expected
        require(brief(pin(path)) == expected, 'independently reviewed public bytes changed')
    return result

def checked_review(path, schema):
    captured = pin(path); review = read(path, captured)
    clean(review, schema)
    approved = approved_map(review)
    require(pin(path) == captured, 'independent review changed while checking')
    return review, captured, approved

def fence(approved):
    for path, expected in approved.items():
        require(brief(pin(path)) == expected, 'closing approved source identity changed')
    for path, expected in READ_PINS.items():
        require(pin(path) == expected, 'closing consumed metadata identity changed')

def identities(info):
    result = {}
    for item in info.siblings:
        require(item.rfilename not in result, 'duplicate Hub sibling path')
        result[item.rfilename] = dict(size=item.size, blob_id=item.blob_id,
            lfs=None if item.lfs is None else dict(sha256=item.lfs.sha256, size=item.lfs.size, pointer_size=item.lfs.pointer_size))
    return result


def merge(approved, values):
    for path, expected in values.items():
        expected=brief(expected)
        require(path not in approved or approved[path]==expected, 'conflicting approved raw identity')
        approved[path]=expected


def expected_names():
    names={'summary.json','cell-checkpoint.json','cell-training.json','data-schedule-before-models.json',
        'initial-parent-head-parity.json','trained-frozen-head-retention.json','trained-training168-raw.json'}
    for stage in ('baseline','trained'):
        names.update(stage+'-'+panel+'-'+kind+'.json' for panel in PANELS for kind in ('raw','joint'))
    for stage in ('initial','trained'):
        names.add(stage+'-parity.json')
        names.update(stage+'-parity-'+control+'.json' for control in ('zeros','alternate_placeholders','disabled','rotated_placeholders'))
    require(len(names)==45, 'exact45 actual result geometry required')
    return names


def owned(descriptor, pattern):
    require(set(descriptor)=={'path','bytes','sha256'}, 'closed owned descriptor required')
    path=Path(descriptor['path'])
    require(path.parent==F and re.fullmatch(pattern,path.name) and pin(path)==descriptor,
        'exact owned qualified producer descriptor required')
    return path


def validate_spec(spec):
    require(type(spec) is dict and set(spec)=={'schema','repository','release_prefix','freeze','analysis',
        'result_review','runtime_review','model_card','public_summary','publisher','public_files'}
        and spec['schema']=='temporal-adapter-Hub-release-spec/v1'
        and spec['repository']==REPO and spec['release_prefix']==PREFIX, 'closed actual release spec required')
    require(type(spec['public_files']) is list and len(spec['public_files'])<=100,
        'finite explicitly qualified additional public files required')
    seen=set()
    for row in spec['public_files']:
        require(type(row) is dict and set(row)=={'source','destination'}
            and type(row['destination']) is str and row['destination'].startswith(('source/','recipe/','evidence/'))
            and '..' not in Path(row['destination']).parts
            and Path(row['destination']).as_posix()==row['destination'] and row['destination'] not in seen,
            'unique bounded extra public destination required')
        brief(row['source']);seen.add(row['destination'])


def qualified_analyzer(analysis, approved, result_review):
    clean(analysis,'temporal-presence-adapter-exposed-result-analysis/v1')
    source, approval=analysis['analyzer'],analysis['independent_source_review']
    owned(source,r'analyze_temporal_adapter(?:_v[0-9]{2})?\.py')
    owned(approval,r'analyzer-source-independent-review-v[0-9]{2}\.json')
    for value in (source,approval):
        require(approved.get(value['path'])==brief(value)
            and brief(result_review['artifacts'][value['path']])==brief(value),
            'actual analyzer/qualification must have independent result provenance')
    review=read(approval['path'],approval)
    clean(review,'temporal-adapter-analyzer-source-independent-review/v1')
    require(review['analyzer']==source,'qualified inner analyzer descriptor differs')
    # The clean approval itself is already raw-bound by the result review.
    # Merge its complete closure rather than silently dropping control pins.
    merge(approved,approved_map(review))
    require(type(analysis.get('input_pins')) is dict and analysis['input_pins'],
        'actual analysis must expose its consumed raw input closure')
    for path,expected in analysis['input_pins'].items():
        if private(path):
            require(RUNTIME_PRIVATE_AUTHORITY.get(path)==brief(expected),
                'analysis private reference must join qualified runtime metadata')
            PRIVATE_REFERENCE_PINS[path]=brief(expected)
        else:
            require(approved.get(path)==brief(expected) and brief(pin(path))==brief(expected),
                'every analysis input needs independently bound closing raw provenance')
    return source,approval


def snapshot_baseline():
    from huggingface_hub import HfApi
    info=HfApi().model_info(REPO,files_metadata=True); files=identities(info)
    require(type(info.sha) is str and re.fullmatch(r'[0-9a-f]{40}',info.sha) and files
        and '.gitattributes' in files and not any(name.startswith(PREFIX+'/') for name in files),
        'fresh nonempty baseline with absent prefix required')
    write_json(F/'hf-before-file-identities-v01.json',dict(repo=REPO,revision=info.sha,files=files))
    print(json.dumps(dict(status='baseline_metadata_saved',revision=info.sha,files=len(files))))


def main(args):
    spec_path=Path(args.spec); helper_path=Path(args.helper_review)
    require(spec_path.parent==helper_path.parent==F
        and re.fullmatch(r'hf-release-spec-v[0-9]{2}\.json',spec_path.name)
        and re.fullmatch(r'hf-helper-source-independent-review-v[0-9]{2}\.json',helper_path.name),
        'owned versioned release spec and source qualification required')
    spec_pin=pin(spec_path);spec=read(spec_path,spec_pin);validate_spec(spec)
    helper_pin=pin(helper_path);helper=read(helper_path,helper_pin)
    clean(helper,'temporal-adapter-Hub-helper-source-independent-review/v1')
    require(brief(helper['artifacts'][str(spec_path)])==brief(spec_pin),
        'actual release spec must be independently source-qualified')
    runtime=read(spec['runtime_review']['path'],spec['runtime_review'])
    clean(runtime,'temporal-adapter-runtime-independent-review/v1')
    RUNTIME_PRIVATE_AUTHORITY.update({path:brief(value) for path,value in runtime['artifacts'].items() if private(path)})
    result=read(spec['result_review']['path'],spec['result_review'])
    clean(result,'temporal-adapter-result-independent-review/v1')
    approved={}
    for review,descriptor in ((helper,helper_pin),(runtime,spec['runtime_review']),(result,spec['result_review'])):
        merge(approved,approved_map(review));merge(approved,{descriptor['path']:descriptor})
    require(approved.get(str(spec_path))==brief(spec_pin) and approved.get(str(Path(__file__).resolve()))==brief(pin(Path(__file__).resolve())),
        'spec/preparer actual source identity not approved')
    def consumed(value):
        require(approved.get(value['path'])==brief(value), 'parsed actual input lacks approved raw identity')
        return read(value['path'],value)
    freeze=consumed(spec['freeze']);analysis=consumed(spec['analysis'])
    require(freeze['schema']=='temporal-adapter-two-cell-freeze/v1' and freeze['all_outputs_frozen'] is True
        and freeze['authorizes_authored_eval_scoring'] is True and [c['cell'] for c in freeze['cells']]==list(CELLS),
        'both actual fixed cells must be frozen and independently reviewed')
    analyzer,analyzer_review=qualified_analyzer(analysis,approved,result)
    require(analysis['default_promotion'] is False and analysis['semantic_accuracy'] is None
        and analysis['actual_returned_optimizer_updates_from_saved_reports']==64,
        'experimental two-cell64-update analysis required')
    summary=consumed(spec['public_summary'])
    require(summary['schema']=='temporal-adapter-public-result-summary/v1'
        and summary['analysis']==spec['analysis'] and summary['independent_result_review']==spec['result_review']
        and summary['default_promotion'] is False, 'qualified compact summary must bind actual analysis/review')
    publisher=owned(spec['publisher'],r'publish_hf_temporal_adapter_release_v[0-9]{2}\.py')
    require(approved.get(str(publisher))==brief(spec['publisher']), 'actual publisher source not approved')
    require(approved.get(spec['model_card']['path'])==brief(spec['model_card']), 'actual model card not qualified')
    cells=[];recipe_sources={}
    for row in freeze['cells']:
        cell=row['cell'];plan=consumed(row['plan']);envelope=consumed(row['summary']);terminal=consumed(row['guardian_terminal'])
        root=Path(row['summary']['path']).parent;attempt=root.parent
        require(set(Path(name).name for name in row['results'])==expected_names() and len(row['results'])==45
            and all(Path(name).parent==root for name in row['results']), 'closed45 actual cell files required')
        require(brief(READ_PINS[row['summary']['path']])==brief(row['results'][row['summary']['path']]), 'consumed summary differs from frozen inventory')
        for path,value in row['results'].items():
            require(approved.get(path)==brief(value) and brief(result['artifacts'][path])==brief(value)
                and brief(pin(path))==brief(value), 'every frozen actual result needs independent raw provenance')
        require(plan['cell']==envelope['cell']==cell and plan['attempt_name']==envelope['attempt_name']==attempt.name
            == 'temporal-adapter-20261013-'+cell+'-01' and root==attempt/'results'
            and envelope['schema']=='temporal-adapter-cell-results/v1' and envelope['status']=='completed'
            and envelope['actual_new_updates']==32 and envelope['actual_external_encoder_calls']==0
            and envelope['latent_enabled'] is False and envelope['fresh_Adam'] is True
            and envelope['inherited_optimizer_moments'] is False and envelope['training_count']==168
            and envelope['source_checkpoint']['sha256']==SOURCE_SHA and envelope['source_model_state_sha256']==SOURCE_STATE_SHA
            and envelope['default_promotion'] is False, 'exact successful source-only N4 adapter envelope required')
        report=consumed(envelope['training']);part=report['parameter_partition']
        require(report['schema']=='bounded-temporal-presence-adapter-training/v1' and report['optimizer_steps']==32
            and report['training_policy']['objective']==cell and len(part['model_parameter_names'])==36
            and len(part['frozen_parameter_names'])==34 and part['trainable_parameter_names']==['temporal_presence.weight','temporal_presence.bias']
            and part['optimizer_parameter_order']==part['trainable_parameter_names']
            and report['frozen_base34_sha256_initial']==report['frozen_base34_sha256_final']==SOURCE_STATE_SHA
            and report['inactive_head_rows_sha256_initial']==report['inactive_head_rows_sha256_final'], 'closed36/34/2 completed adapter training required')
        for key,initial in (('initial_parent_head_parity',True),('frozen_head_retention',False)):
            parity=consumed(envelope[key]);require(parity['source_rows']==392 and parity['initial'] is initial
                and parity['all_compared_components_bit_equal'] is True and parity['compared_temporal_presence'] is initial,
                'complete392 actual initial/frozen-head parity required')
        require(type(terminal['returncode']) is int and type(terminal['child_returncode']) is int
            and terminal['returncode']==terminal['child_returncode']==0 and terminal['artifacts_durable'] is True
            and terminal['resource_reservation_released'] is True, 'durable released guardian success required')
        pre_path=attempt/'pre-admission.json';require(str(pre_path) in approved,'actual admission provenance required')
        pre=read(pre_path,pin(pre_path));require(pre['plan']==row['plan'],'admitted plan identity differs')
        consumed(pre['review'])
        for key in ('runner','guardian'):
            descriptor=pre[key];require(approved.get(descriptor['path'])==brief(descriptor),'actual runtime producer not qualified')
            require(key not in recipe_sources or recipe_sources[key]==descriptor,'two-cell runtime producer mismatch')
            recipe_sources[key]=descriptor
        cells.append((row,attempt,pre))
    baseline_path=F/'hf-before-file-identities-v01.json';baseline_pin=pin(baseline_path);baseline=read(baseline_path,baseline_pin)
    require(baseline['repo']==REPO and re.fullmatch(r'[0-9a-f]{40}',baseline['revision']) and baseline['files']
        and '.gitattributes' in baseline['files'] and not any(name.startswith(PREFIX+'/') for name in baseline['files']),
        'fresh absent-prefix immutable baseline required')
    fence(approved)
    upload_root=F/'hf-upload-v02';require(not os.path.lexists(upload_root),'exclusive new upload tree required')
    upload_root.mkdir(mode=0o700);release_root=upload_root/PREFIX;release_root.mkdir(parents=True)
    entries={}
    def copy_file(source,relative):
        source=Path(source);captured=pin(source)
        require(approved.get(str(source))==brief(captured) and captured['bytes']<MAX_FILE_BYTES,
            'every bounded copied public byte source must be qualified')
        require(str(source) not in READ_PINS or READ_PINS[str(source)]==captured,'parsed/copied source identity differs')
        relative=Path(relative);target=release_root/relative
        require(not relative.is_absolute() and '..' not in relative.parts and target.resolve().is_relative_to(release_root.resolve())
            and not os.path.lexists(target),'unique prefix-only ordinary copy target required')
        raw=source.read_bytes();require(brief(captured)==dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
            and pin(source)==captured,'copied consumed bytes differ from qualified pin')
        require(sum(v['bytes'] for v in entries.values())+len(raw)<=MAX_PAYLOAD_BYTES,'bounded full payload required')
        target.parent.mkdir(parents=True,exist_ok=True);write(target,raw);entries[target.relative_to(upload_root).as_posix()]=pin(target)
    for row,attempt,pre in cells:
        cell=row['cell']
        for path,value in sorted(row['results'].items()):copy_file(path,'cells/'+cell+'/results/'+Path(path).name)
        copy_file(row['plan']['path'],'cells/'+cell+'/plan.json')
        copy_file(pre['review']['path'],'cells/'+cell+'/training-protocol-review.json')
        for name in PUBLIC_RUNTIME:copy_file(attempt/name,'cells/'+cell+'/runtime/'+name)
    for key in ('freeze','result_review','runtime_review'):copy_file(spec[key]['path'],'evidence/'+Path(spec[key]['path']).name)
    copy_file(spec_path,'evidence/'+spec_path.name);copy_file(helper_path,'evidence/'+helper_path.name)
    copy_file(spec['public_summary']['path'],'evidence/'+Path(spec['public_summary']['path']).name)
    copy_file(spec['model_card']['path'],'README.md')
    for descriptor in (analyzer,pin(Path(__file__).resolve()),spec['publisher'],*recipe_sources.values()):
        copy_file(descriptor['path'],'recipe/'+Path(descriptor['path']).name)
    copy_file(analyzer_review['path'],'evidence/'+Path(analyzer_review['path']).name)
    for row in spec['public_files']:copy_file(row['source']['path'],row['destination'])
    for relative in ('ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_temporal_adapter.py',
        'tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_temporal_adapter_contracts.py'):
        destination=PREFIX+'/source/'+relative
        require(destination in entries and brief(entries[destination])==brief(pin(F/'datasets'/relative)),
            'new trainer and inert test code must be included exactly')
    manifest=dict(schema='temporal-adapter-Hub-release-manifest/v1',repository=REPO,release_prefix=PREFIX,cells=list(CELLS),
        actual_new_updates_per_cell=32,actual_new_updates_total=64,actual_frozen_results_per_cell=45,
        model_tensors=36,frozen_tensors=34,trainable_tensors=2,source_checkpoint_sha256=SOURCE_SHA,
        source_model_state_sha256=SOURCE_STATE_SHA,source_optimizer_steps=32,fresh_Adam=True,inherited_optimizer_moments=False,
        configured_dimension=384,latent_enabled=False,actual_external_latent_encoder_calls=0,feature_paths_per_source_forward=2,
        initial_parent_head_score_rows_per_cell=392,final_frozen_head_score_rows_per_cell=392,final_training_source_rows_per_cell=168,
        separate_historical_N4_parent_files_uploaded=False,opaque_checkpoint_parent_provenance_embeddings_retained=True,
        prior_parent_release='https://huggingface.co/Publicus/legal-ir-autoencoder/tree/70525bcf70e801e78f4882b4834494d67ec0d2b6/releases/20261013-split-feature-v1',
        private_global_bodies_uploaded=False,default_promotion=False,semantic_accuracy=None,independent_statutory_gold=False,
        genuine_latent_semantics_qualified=False,broader_logic_families_qualified=False,Lake_executed=False,
        actual_analysis=spec['analysis'],actual_analyzer=analyzer,actual_analyzer_source_review=analyzer_review,
        public_summary=spec['public_summary'],sources=entries.copy())
    descriptor=write_json(release_root/'release-manifest.json',manifest);entries[PREFIX+'/release-manifest.json']=descriptor
    total=sum(v['bytes'] for v in entries.values())
    require(len(entries)<=1000 and total<=MAX_PAYLOAD_BYTES and all(v['bytes']<MAX_FILE_BYTES for v in entries.values()),
        'closed bounded final upload inventory required')
    fence(approved)
    for name,value in entries.items():require(pin(upload_root/name)==value,'closing prepared byte identity changed')
    receipt=dict(schema='temporal-adapter-Hub-preparation/v1',repository=REPO,release_prefix=PREFIX,
        expected_parent_revision=baseline['revision'],upload_root=str(upload_root),complete_upload_files=entries,
        payload_files=len(entries),payload_bytes=total,baseline_pin=baseline_pin,freeze_manifest=spec['freeze'],
        result_review=spec['result_review'],runtime_review=spec['runtime_review'],helper_review=helper_pin,
        release_spec=spec_pin,source_preparer=pin(Path(__file__).resolve()),source_publisher=spec['publisher'],
        approved_source_artifacts=approved,qualified_runtime_private_identity_references=PRIVATE_REFERENCE_PINS,
        default_promotion=False,additive_only=True)
    write_json(F/'hf-preparation-receipt-v02.json',receipt)
    print(json.dumps(dict(status='prepared_only',files=len(entries),bytes=total)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--snapshot-baseline',action='store_true')
    parser.add_argument('--spec',default=str(F/'hf-release-spec-v02.json'))
    parser.add_argument('--helper-review',default=str(F/'hf-helper-source-independent-review-v02.json'))
    args=parser.parse_args();snapshot_baseline() if args.snapshot_baseline else main(args)
