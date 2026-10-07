#!/usr/bin/env python3
"""Build a fresh read-only replay seal; never construct or execute a model."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path('/home/barberb/lift_coding')
HERE = Path(__file__).resolve().parent
COPIES = ('reconcile_retained_dual_bank_outputs.py',
    'evaluate_dual_bank_wording_continuation.py', 'build_retained_parent_reconciliation_manifest.py')
PREFIX = Path('scripts/ops/autoencoder')


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            value.update(block)
    return value.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def join_pin(pins, path, wanted=None):
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError('canonical retained locator required: ' + str(path))
    actual = sha(path)
    if wanted is not None and actual != wanted:
        raise ValueError('retained pin changed: ' + str(path))
    if pins.get(str(path), actual) != actual:
        raise ValueError('conflicting retained pin: ' + str(path))
    pins[str(path)] = actual
    return str(path)


def collect_refs(value, pins, pending):
    """Walk report metadata references, avoiding tensor and row payloads."""
    if type(value) is dict:
        if type(value.get('path')) is str and type(value.get('sha256')) is str:
            path = join_pin(pins, value['path'], value['sha256'])
            if 'bytes' in value and (type(value['bytes']) is not int or value['bytes'] != Path(path).stat().st_size):
                raise ValueError('typed exact retained reference bytes required')
            pending.add(path)
        for key, item in value.items():
            if key not in ('model_state', 'vectors', 'rows', 'clause_cache', 'paragraph_features', 'clause_features'):
                collect_refs(item, pins, pending)
    elif type(value) is list:
        for item in value:
            collect_refs(item, pins, pending)


def build(args):
    args.output = args.output.resolve()
    if args.output.exists():
        raise ValueError('fresh phase-seal output required')
    extension_root = args.extension_root.resolve(strict=True)
    initialization = args.initialization_root.resolve(strict=True)
    old_manifest = initialization / 'phase-seal-r2/training-manifest.json'
    old_plan = initialization / 'phase-seal-r2/training-plan.json'
    old = read(old_manifest)
    helper = load(extension_root / PREFIX / COPIES[1], '_retained_parent_seal_helper')
    runtime = load(extension_root / PREFIX / COPIES[0], '_retained_parent_seal_contract')
    helper.require(sha(old_plan) == old['plan_sha256'], 'original initialization plan changed')
    pins = dict(old['inputs'])
    dual = ROOT / 'external/ipfs_datasets/workspace/test-logs/decoder-dual-bank-replay-20261007'
    control = ROOT / 'external/ipfs_datasets/workspace/test-logs/decoder-balanced-wording-20261007'
    prior_eval = [dual / 'evaluation-manifest.json', control / 'evaluation-manifest.json']
    for path in prior_eval:
        value = read(path)
        for locator, wanted in value['inputs'].items():
            if pins.get(locator, wanted) != wanted:
                raise ValueError('prior manifest input conflict')
            pins[locator] = wanted
        join_pin(pins, path)
        plan_path = path.with_name('evaluation-plan.json')
        join_pin(pins, plan_path, value['plan_sha256'])
    locations = dict(initialization_manifest=str(old_manifest), initialization_plan=str(old_plan),
        initialization_extension_root=str(initialization / 'experiment-source'),
        numeric_source=str(initialization / 'experiment-source/scripts/ops/autoencoder/benchmark_dual_bank_wording_continuation.py'),
        evaluation_helper_source=str(extension_root / PREFIX / COPIES[1]),
        parallel_training_summary=str(dual / 'training-384-r1/results/summary.json'),
        parallel_evaluation_summary=str(dual / 'evaluation-r1/results/summary.json'),
        archived_control_training_summary=str(control / 'training-384-r2/results/summary.json'),
        archived_control_evaluation_summary=str(control / 'evaluation-r1/results/summary.json'),
        v3_references=read(prior_eval[0])['v3_references'])
    helper.require(read(prior_eval[0])['source_inventories'] == old['source_inventories']
        == read(prior_eval[1])['source_inventories'], 'same unchanged two source inventories required')
    for name, path in locations.items():
        if name != 'initialization_extension_root':
            join_pin(pins, path)
    for rel, wanted in old['extensions'].items():
        join_pin(pins, initialization / 'experiment-source' / rel, wanted)
    for path in old['source_inventories'].values():
        join_pin(pins, path)
    pending, seen = set(), set()
    for name in ('parallel_training_summary', 'parallel_evaluation_summary',
        'archived_control_training_summary', 'archived_control_evaluation_summary'):
        collect_refs(read(locations[name]), pins, pending)
    while pending - seen:
        path = sorted(pending - seen)[0]
        seen.add(path)
        if path.endswith('.json'):
            helper.require(Path(path).stat().st_size <= 100000000,
                'bounded retained JSON reference required')
            collect_refs(read(path), pins, pending)
    extensions = {str(PREFIX / name): sha(extension_root / PREFIX / name) for name in COPIES}
    for relative, wanted in extensions.items():
        join_pin(pins, extension_root / relative, wanted)
        # Keep the canonical reviewed source and its detached execution copy.
        if args.canonical_source_root is not None:
            join_pin(pins, args.canonical_source_root.resolve(strict=True) / Path(relative).name, wanted)
    witness = {path: helper._capture(path, wanted) for path, wanted in pins.items()}
    for path, identity in witness.items():
        helper.require(helper._file_identity(path) == identity, 'closing seal identity drift')
    helper.require('torch' not in sys.modules and 'transformers' not in sys.modules,
        'seal build must remain metadata-only')
    args.output.mkdir(parents=True)
    save = helper.compact_writer(args.output, 10000000)
    plan = dict(runtime.PROFILE, input_sha256=pins)
    plan_ref = helper.durable(save, args.output / 'evaluation-plan.json', plan)
    manifest = dict(schema='retained-dual-bank-parent-reconciliation-manifest/v1',
        inputs=pins, extensions=extensions, plan_sha256=plan_ref['sha256'],
        source_inventories=old['source_inventories'], **locations)
    runtime.validate_plan(plan, manifest)
    manifest_ref = helper.durable(save, args.output / 'evaluation-manifest.json', manifest)
    receipt = helper.durable(save, args.output / 'manifest-build-receipt.json', dict(
        schema='retained-parent-reconciliation-seal-build/v1', manifest=manifest_ref, plan=plan_ref,
        total_input_pins=len(pins), retained_initialization_pins=len(old['inputs']),
        recursive_saved_report_references=len(seen), numerical_library_imported=False,
        models_executed=False, admission_granted=False, **runtime.FALSE))
    return dict(manifest=manifest_ref, plan=plan_ref, receipt=receipt)


def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extension-root', type=Path, required=True)
    parser.add_argument('--canonical-source-root', type=Path,
        default=ROOT / 'artifacts/autoencoder-dual-bank-fit-20261007/evaluation-source')
    parser.add_argument('--initialization-root', type=Path,
        default=ROOT / 'external/ipfs_datasets/workspace/test-logs/decoder-dual-bank-wording-20261007')
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(build(parser.parse_args()), sort_keys=True))


if __name__ == '__main__':
    main()
