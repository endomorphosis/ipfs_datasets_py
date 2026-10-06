#!/usr/bin/env python3
"""Matched TRAIN wording auxiliary over the authenticated M2/R13 runtime.

Only the separately prepared TRAIN clause bank changes. Original decoder rows,
optimizer schedule, selection, full-vocabulary losses and frozen producers are
owned by the immutable M2 closure. The zero arm must replay its saved tensors
and original numerical updates exactly. Imports perform no model work.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import time
from types import SimpleNamespace

AUTO = 'ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX = 'ipfs_datasets_py.logic.formalization.autoencoder.'
BASE_FILE = 'scripts/ops/autoencoder/benchmark_paraphrase_modality_training.py'
BASE_SHA256 = 'd84974df896df766794069da01319ef0d7473eb2907f4a6a540a0661f6b193e8'
ARMS = [dict(name='normative-wording-zero', weight=0.), dict(name='normative-wording-ce', weight=.05)]
TEMPLATES = ('explicit_actor_status_v1', 'regulation_norm_operator_v1')


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def load_base(path):
    path = Path(path)
    require(sha(path) == BASE_SHA256, 'immutable M2 training adapter pin differs')
    spec = importlib.util.spec_from_file_location('_normative_wording_m2_core', path)
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    return owner


def fixed_recipe():
    base = load_base(Path(__file__).resolve().parents[3]/BASE_FILE)
    return dict(base.FIXED, schema='normative-wording-training-plan/v1', arms=ARMS,
        paraphrase_auxiliary_strata=[m+':'+t for m in ('O','P','F') for t in TEMPLATES],
        source_bank='180 unique clauses; two new renderings of original90 TRAIN rules',
        previous_development_targets_used_for_training=False,
        zero_arm_exact_m2_zero_replay=True,
        private_renderer_profile=True, package_aliases_modified=False,
        cache_scope='warm authenticated normative TRAIN vectors;metric disk cache disabled')


FIXED = fixed_recipe()


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v) and
        json.dumps(plan[k], sort_keys=True, allow_nan=False) ==
        json.dumps(v, sort_keys=True, allow_nan=False) for k,v in FIXED.items()),
        'fixed normative wording training recipe differs')


def load_training_owner(base_path=None):
    """Configure a private M2 runner; keep imported defaults untouched."""
    base = load_base(base_path or Path(__file__).resolve().parents[3]/BASE_FILE)
    base.FIXED = FIXED
    base.ARMS = ARMS
    base.validate_plan = validate_plan

    def source_inventory(args, ctx):
        manifest = ctx['paraphrase_manifest']
        allowed = dict(manifest['producer_pins'])
        allowed.update({str((args.extension_root/rel).resolve()): value
            for rel,value in manifest['extensions'].items()})
        found = base.package_inventory()
        for path,value in found.items():
            require(allowed.get(path) == value, 'unbound normative resident producer: '+path)
        return found

    def envelope(ctx, width, policy):
        manifest = ctx['paraphrase_manifest']
        artifacts = manifest['normative_preparation_artifacts']
        read = lambda name: base.bound(manifest, artifacts[name])
        result = dict(policy=policy, training_bank=read('original-training-bank-used.json'),
            prior_sources_by_dataset=read('prior-source-inventories.json'),
            corpus=dict(source_rows=read('source-rows.json'), references=read('training-references.json'),
                receipt=read('training-corpus-receipt.json')),
            clause_training_references=read('clause-training-references.json'),
            source_plan=read('source-plan.json'), source_inputs=read(f'dimension-inputs-{width}.json'),
            production_report=read(f'production-{width}.json'),
            evaluation_vectors_by_dataset=ctx['paraphrase_parent_original'].evaluation_vectors(
                ctx['mixture_manifest'], ctx['mixture_preparation'], width,
                read('prior-source-inventories.json')))
        result['payload_sha256'] = ctx['core'].digest(result)
        return result

    def load_context(args, deadline):
        require(not args.output.exists(), 'fresh output must remain absent through parent initialization')
        manifest = json.loads(args.manifest.read_bytes())
        plan = json.loads(args.plan.read_bytes())
        validate_plan(plan)
        require(plan['input_sha256'] == manifest['inputs'], 'normative input plan differs')
        manifest_sha = sha(args.manifest)
        base.recheck(args, manifest, manifest_sha, deadline)
        parent = base.bound(manifest, manifest['parent_manifest'])
        base.bound(manifest, manifest['parent_plan'])
        root = Path(manifest['parent_extension_root'])
        require(sha(root/BASE_FILE) == BASE_SHA256 == parent['extensions'][BASE_FILE],
            'authenticated immutable M2 runner differs')
        # Use a distinct, unconfigured instance to initialize the frozen parent.
        parent_owner = load_base(root/BASE_FILE)
        previous = SimpleNamespace(**vars(args))
        previous.manifest = Path(manifest['parent_manifest'])
        previous.plan = Path(manifest['parent_plan'])
        previous.extension_root = root
        ctx = parent_owner.load_context(previous, deadline)
        parent_owner.source_inventory(previous, ctx)
        authored = ctx['helpers'].extension(args.extension_root,
            AUTO+'normative_wording_training_sources.py',
            PREFIX+'normative_wording_training_sources', manifest['extensions'])
        adapter = ctx['helpers'].extension(args.extension_root,
            AUTO+'normative_wording_modality_auxiliary.py',
            PREFIX+'normative_wording_modality_auxiliary', manifest['extensions'])
        helper = adapter.configure(auxiliary_owner=ctx['paraphrase_helper'],
            mixture_owner=ctx['mixture_helper'], authored_owner=authored)
        ctx['owners']['long_span_source_value_training'] = adapter.configure_trainer(
            ctx['owners']['long_span_source_value_training'], helper)
        original_parent = ctx['paraphrase_parent']
        configured_parent = adapter.private_module(original_parent, envelope=envelope)
        baselines = {}
        for width,path in manifest['baseline_summaries'].items():
            run = base.bound(manifest, path)
            require(run['dimension'] == int(width) and run['arm'] == 'paraphrase-modality-zero'
                and run['budget_completed'] is True and run['zero_arm_archived_replay_verified'] is True,
                'completed exact M2 zero baseline required')
            base.bound(manifest, run['training_ref']['path'], run['training_ref']['sha256'])
            baselines[width] = run
        require(set(baselines) == {'384','768'}, 'both M2 zero baselines required')
        ctx.update(paraphrase_manifest=manifest, paraphrase_plan=plan,
            paraphrase_manifest_sha=manifest_sha, paraphrase_helper=helper,
            paraphrase_parent=configured_parent, paraphrase_parent_original=original_parent,
            paraphrase_baselines=baselines, normative_adapter=adapter,
            normative_parent_args=previous, normative_parent_owner=parent_owner)
        source_inventory(args, ctx)
        base.check_deadline(deadline)
        return ctx

    def validate_independent_inputs(ctx, lane, bank, declared, baseline):
        manifest = ctx['paraphrase_manifest']
        clauses = base.bound(manifest,
            manifest['normative_preparation_artifacts']['clause-training-references.json'])
        native = base.bound(manifest,
            manifest['normative_preparation_artifacts'][f'production-{lane["dimension"]}.json'])
        by_text = {row['source_text']: row for row in clauses}
        by_sha = {row['source_sha256']: row for row in native['vectors']}
        require(len(clauses) == len(by_text) == len(bank['rows']) == 180,
            'complete independently bound normative clauses required')
        for row in bank['rows']:
            reference = by_text[row['source_text']]
            require(reference['target'] == {'rules':[row['target']]} and
                reference['source_sha256'] == row['source_sha256'] and
                reference['template'] == row['template'], 'bound normative clause differs')
            vector = by_sha[row['source_sha256']]['vector']
            require(struct.pack('<'+'f'*lane['dimension'], *row['input']) ==
                struct.pack('<'+'f'*lane['dimension'], *vector), 'bound native TRAIN vector differs')
        paths = manifest['independent_inputs']
        require(declared['draws'] == base.bound(manifest, paths['auxiliary_schedule']),
            'independent normative auxiliary draw schedule differs')
        primary = base.bound(manifest, paths['primary_schedules'][str(lane['dimension'])])
        require(len(primary) == len(baseline['committed_updates']) == 170,
            'complete independent original schedule required')
        for update,item in zip(baseline['committed_updates'], primary):
            require(update['decoder_row_ids'] == item['decoder_ids'] and
                update['count_row_ids'] == item['count_ids'], 'original schedule changed')
            if lane['dimension'] == 384:
                require(update['auxiliary_source_modality']['receipt'] ==
                    item['original_auxiliary_source_modality'], 'original384 auxiliary changed')
        declared['independent_inputs_verified'] = True

    def bank_readout(ctx, lane, model, bank, deadline):
        base.check_deadline(deadline)
        before = lane['core'].tensor_digest(model)
        cache = base.tensor_cache(ctx, lane, model, bank, deadline)
        value = ctx['paraphrase_helper'].evaluate_bank(lane['core']._torch(), model, cache,
            deadline=min(deadline, time.monotonic()+30.))
        require(value['complete'] and len(value['rows']) == 180 and
            value['groups']['all']['rows'] == 180 and value['model_tensor_sha256'] == before
            and lane['core'].tensor_digest(model) == before, 'full180 TRAIN readout differs')
        for modality in ('O','P','F'):
            require(value['groups']['modality:'+modality]['rows'] == 60, 'TRAIN modality readout incomplete')
            for template in TEMPLATES:
                require(value['groups']['stratum:'+modality+':'+template]['rows'] == 30
                    and value['groups']['template:'+template]['rows'] == 90, 'TRAIN template readout incomplete')
        require(value['used_for_selection'] is False and value['optimizer_steps'] == 0,
            'TRAIN readout changed selection or model')
        value.update(schema='normative-wording-modality-readout/v1',
            private_renderer_profile=True, helper_defaults_modified=False)
        base.check_deadline(deadline)
        return value

    base.load_context = load_context
    base.source_inventory = source_inventory
    base.validate_independent_inputs = validate_independent_inputs
    base.bank_readout = bank_readout
    inherited_execute = base.execute
    def execute(args):
        result = inherited_execute(args)
        result.update(schema='normative-wording-training-comparison/v1',
            zero_replay_baseline='completed immutable M2 zero arm',
            private_renderer_profile=True, helper_defaults_modified=False,
            package_aliases_modified=False)
        # The existing save owner uses this exact JSON formatting. Replacing
        # only the terminal summary does not change any state or report ref.
        path = args.output/'summary.json'
        with path.open('w', encoding='utf-8') as stream:
            json.dump(result, stream, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
            stream.flush()
            import os
            os.fsync(stream.fileno())
        return result
    base.execute = execute
    # The unmodified M2 execute loop owns fit/deadline/state/postfit behavior.
    return base


def load_context(args, deadline):
    return load_training_owner().load_context(args, deadline)


def source_inventory(args, ctx):
    return load_training_owner().source_inventory(args, ctx)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--phase', choices=['preflight','training'], required=True)
    parser.add_argument('--dimension', type=int, choices=[384,768], required=True)
    load_training_owner().execute(parser.parse_args())


if __name__ == '__main__':
    main()
