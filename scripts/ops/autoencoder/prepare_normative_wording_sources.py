#!/usr/bin/env python3
"""Guarded local native preparation for new TRAIN and prospective development.

Future development references are an already sealed separate handoff. This
producer never parses them. Its encoder calls receive closed source rows only.
The historical numerical/setup owners remain explicitly hash pinned.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

AUTO = 'ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX = 'ipfs_datasets_py.logic.formalization.autoencoder.'
PARENT = 'scripts/ops/autoencoder/prepare_training_paraphrases.py'
FRESH = 'scripts/ops/autoencoder/observe_fresh_normative_style.py'
FIXED = dict(schema='normative-wording-preparation-plan/v1', dimensions=[384,768],
    original_train_sources=180, original_train_rules=90, train_paragraphs=48,
    train_unique_clauses=180, train_unique_sources=216, development_single_sources=60,
    unique_sources_per_width=276, seed=20261006, batch_size=4, context_tokens=512,
    output_tokens=512, temperature=0, workers=1, max_seconds_per_encoder=600,
    max_seconds_total=1400, training_executed=False, model_scoring_executed=False,
    development_reference_json_parsed=False, downloads_performed=False,
    preprocessing_fitted=False, qualified=False, admitted=False, lake_executed=False,
    checkpoint_promoted=False, fresh_holdout=False, bridge_names=[],
    legal_ir_evaluate_provers=False, metric_disk_cache_used=False)


def require(ok, message):
    if not ok: raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda:stream.read(1048576), b''): h.update(data)
    return h.hexdigest()


def bound(manifest, path):
    path = Path(path).resolve()
    require(manifest['inputs'].get(str(path)) == sha(path), 'unbound or changed preparation input: '+str(path))
    return json.loads(path.read_bytes())


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v) and plan[k] == v
        for k,v in FIXED.items()), 'fixed normative preparation recipe differs')


def helper(path, wanted, name):
    require(sha(path) == wanted, 'frozen preparation helper differs')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def execute(args):
    started = time.monotonic(); deadline = started + FIXED['max_seconds_total']
    manifest = json.loads(args.manifest.read_bytes()); plan = json.loads(args.plan.read_bytes())
    validate_plan(plan); manifest_sha = sha(args.manifest)
    require(plan['input_sha256'] == manifest['inputs'] and sha(args.plan) == manifest['plan_sha256'], 'sealed preparation inputs differ')
    def recheck():
        require(time.monotonic() < deadline and sha(args.manifest) == manifest_sha
            and sha(args.plan) == manifest['plan_sha256'], 'preparation deadline or seal changed')
        for path,wanted in manifest['inputs'].items():
            require(time.monotonic() < deadline and sha(path) == wanted, 'sealed input changed: '+path)
        for rel,wanted in manifest['extensions'].items():
            require(sha(args.extension_root/rel) == wanted, 'frozen owned preparation source changed')
    recheck(); require(not args.output.exists(), 'fresh preparation output required')
    original = bound(manifest, manifest['parent_manifest'])
    root = Path(manifest['parent_extension_root'])
    old = helper(root/PARENT, original['extensions'][PARENT], '_normative_source_r4')
    fresh_manifest = bound(manifest, original['parent_manifest'])
    fresh_root = Path(original['parent_extension_root'])
    owner = helper(fresh_root/FRESH, fresh_manifest['extensions'][FRESH], '_normative_source_fresh')
    previous = SimpleNamespace(**vars(args)); previous.extension_root = fresh_root
    previous.manifest = Path(original['parent_manifest']); previous.plan = Path(original['parent_plan'])
    owners = {}
    def validate_sources(ctx):
        package = sys.modules[PREFIX[:-1]]
        for name in ('authored_training_paraphrases','training_paraphrase_source_inputs'):
            owners[name] = ctx['helpers'].extension(root, AUTO+name+'.py', PREFIX+name, original['extensions'])
            setattr(package, name, owners[name])
        for name in ('normative_wording_training_sources','prospective_wording_source_inputs'):
            owners[name] = ctx['helpers'].extension(args.extension_root, AUTO+name+'.py', PREFIX+name, manifest['extensions'])
            setattr(package, name, owners[name])
        return old.source_inventory(args, manifest)
    ctx,before = old.initialize_preparation(owner, previous, validate_sources)
    save = ctx['helpers'].save; builder = owners['normative_wording_training_sources']
    bank = bound(manifest, manifest['training_bank'])
    training = [{k:r[k] for k in ('id','source_text','target_ids')} for r in bank]
    prior = bound(manifest, manifest['prior_sources'])
    prior.pop('new_training_wordings', None)
    development = bound(manifest, manifest['development_sources'])
    dev_seal = bound(manifest, manifest['development_seal'])
    dev_source_ref = dev_seal['artifact_files']['source_rows']
    require(dev_source_ref['path'] == manifest['development_sources'] and dev_source_ref['sha256'] == sha(manifest['development_sources'])
        and dev_seal['complete'] is True and dev_seal['encoder_executed'] is False
        and dev_seal['checkpoint_promoted'] is False, 'pre-model development source seal differs')
    require(len(development) == 60 and all(set(r) == {'id','source_text'} for r in development), 'closed sixty development sources required')
    prior['prospective_development_sources'] = development
    built = builder.build(training_bank=training, prior_sources_by_dataset=prior, codec=ctx['donor']['codec'],
        sealed_recipe_sha256=manifest['recipe_seal'], seed=20261006, validate_rule=ctx['validate_rule'])
    expected_train = bound(manifest, manifest['independent_training_sources'])
    require(built['source_rows'] == expected_train, 'new TRAIN wording differs from independently authored exclusions')
    save(args.output/'original-training-bank-used.json', training)
    save(args.output/'prior-source-inventories.json', prior)
    for filename,key in (('source-rows.json','source_rows'),('training-references.json','references'),
                         ('clause-training-references.json','clause_references'),('training-corpus-receipt.json','receipt')):
        save(args.output/filename, built[key])
    train_producer = owners['training_paraphrase_source_inputs']; dev_producer = owners['prospective_wording_source_inputs']
    train_plan = train_producer.source_plan(built['source_rows'], expected_source_rows_sha256=built['receipt']['source_rows_sha256'],
        sealed_recipe_sha256=manifest['recipe_seal'])
    dev_plan = dev_producer.source_plan(development, expected_source_rows_sha256=dev_producer.digest(development),
        sealed_recipe_sha256=dev_seal['sealed_recipe_sha256'])
    save(args.output/'source-plan.json', train_plan); save(args.output/'development-source-plan.json', dev_plan)
    save(args.output/'pre-native-source-seal.json', dict(complete=True, train_source_sha256=builder.digest(built['source_rows']),
        train_reference_sha256=builder.digest(built['references']), development_source_sha256=dev_producer.digest(development),
        development_seal_sha256=sha(manifest['development_seal']), development_reference_json_parsed=False,
        encoder_executed=False, training_executed=False, qualified=False, admitted=False))
    assets = bound(manifest, manifest['asset_config']); outputs = {}
    for d in FIXED['dimensions']:
        recheck(); old_vectors, old_rows = old.prior_vectors(manifest, d)
        train_report = train_producer.produce_width(train_plan, dimension=d, asset_config=assets[str(d)],
            source_artifact_directory=args.output/'train-source384-artifacts' if d == 384 else None,
            batch_size=4, max_seconds=min(600,deadline-time.monotonic()))
        train_report_ref = save(args.output/f'production-{d}.json', train_report)
        require(train_producer.validate_report(train_plan,train_report) == d, 'new TRAIN native report differs')
        vectors = {r['source_sha256']:r['vector'] for r in train_report['vectors']}
        rows = [dict(r,input=vectors[builder.base.text_sha(r['source_text'])]) for r in built['source_rows']]
        cache = []; seen = set()
        for row in built['source_rows']:
            for text in row['source_text'].split('\n\n'):
                key = builder.base.text_sha(text)
                if key not in seen:
                    seen.add(key); cache.append(dict(id='clause:'+key,source_text=text,input=vectors[key]))
        clause_owner = ctx['owners']['clause_source_context']
        contexts = clause_owner.build_source_contexts(built['source_rows'],cache)
        require(clause_owner.validate_contexts(rows,contexts)['dimension'] == d, 'new TRAIN source contexts differ')
        payload = dict(schema='training-paraphrase-source-inputs/v1', complete=True, role='train_augmentation', dimension=d,
            rows=rows,clause_cache=cache,source_contexts=contexts,production_sha256=train_report['production_sha256'],
            source_plan_sha256=train_plan['plan_sha256'],targets_attached=False,preprocessing_fitted=False,
            qualified=False,admitted=False,checkpoint_promoted=False)
        payload['inputs_sha256'] = builder.digest(payload)
        train_inputs_ref = save(args.output/f'dimension-inputs-{d}.json', payload)
        recheck()
        dev_report = dev_producer.produce_width(dev_plan, dimension=d, asset_config=assets[str(d)],
            source_artifact_directory=args.output/'dev-source384-artifacts' if d == 384 else None,
            batch_size=4,max_seconds=min(600,deadline-time.monotonic()))
        dev_report_ref = save(args.output/f'development-production-{d}.json', dev_report)
        dev_inputs = dev_producer.assemble(dev_plan, dev_report, dimension=d)
        dev_inputs_ref = save(args.output/f'development-inputs-{d}.json', dev_inputs)
        new_vectors = [tuple(r['vector']) for report in (train_report,dev_report) for r in report['vectors']]
        require(len(new_vectors) == len(set(new_vectors)) == 276 and not old_vectors.intersection(new_vectors),
            'new native vector duplicates or prior overlap; no fallback')
        outputs[str(d)] = dict(production=train_report_ref, source_inputs=train_inputs_ref,
            development_production=dev_report_ref, development_source_inputs=dev_inputs_ref,
            train_encoder_seconds=train_report['elapsed_seconds'],dev_encoder_seconds=dev_report['elapsed_seconds'],
            encoder_seconds_per_unique_source=(train_report['elapsed_seconds']+dev_report['elapsed_seconds'])/276,
            prior_vector_rows=old_rows,prior_unique_vectors=len(old_vectors),vector_identity_overlap=0)
        print(json.dumps(dict(dimension=d,complete=True,unique_sources=276,outputs=outputs[str(d)])),flush=True)
    after = old.source_inventory(args,manifest)
    require(all(after.get(k)==v for k,v in before.items()), 'resident source producer changed')
    recheck()
    save(args.output/'summary.json',dict(**FIXED,complete=True,phase='preparation',outputs=outputs,
        encoder_executed=True,source_dependencies=after,elapsed_seconds=time.monotonic()-started,
        cache_scope='new verified local forward outputs; OS asset page-cache warmth uncontrolled; metric cache off'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['preparation'],required=True)
    execute(parser.parse_args())


if __name__ == '__main__': main()
