"""Stdlib-only author for an immutable frozen span-comparison plan.

No package imports, model loading, training, encoding or resource mutation.
Provide the final adapter owner pin manifest explicitly after source freeze.
Historical corpus bytes are hashed here for lineage only; the numerical child
is forbidden to open corpus/target/census files.

This joint readout plan keeps the no-subprocess libdl resolution used during Torch import;
the historical scientific recipe, checkpoint states and resource caps stay fixed.
"""
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path

F = Path(__file__).resolve().parent
OLD = Path('/home/barberb/lift_coding/artifacts/legal-native-cache-20261011-01')
HISTORY = Path('/home/barberb/lift_coding/artifacts/legal-decoder-native-conditioning-20261002')
RUN_ROOT = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
NATIVE = RUN_ROOT / 'arbitrary-native-cache-20261011-02/results/source-production/native384-receipt-001.json'
IMPORT_FIX_FILES = {
    'library_pin': '/usr/lib/aarch64-linux-gnu/libdl.so.2',
    'ctypes_util_pin': '/usr/lib/python3.12/ctypes/util.py',
    'cuda_pathfinder_pin': '/home/barberb/.local/lib/python3.12/site-packages/cuda/pathfinder/_dynamic_libs/load_dl_linux.py',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, 'duplicate JSON field')
            value[key] = item
        return value
    value = json.loads(Path(path).read_bytes(), object_pairs_hook=pairs,
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
    return value


def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and path.is_file()
        and not path.is_symlink(), 'canonical regular artifact required')
    digest, size = sha256(), 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block); size += len(block)
    return dict(path=str(path), bytes=size, sha256=digest.hexdigest())


def prepare(args):
    root = Path(args.package_root)
    require(root.is_absolute() and root.resolve() == root and root.is_dir(), 'canonical package root required')
    owner_path = Path(args.source_owners)
    owners = read(owner_path)
    require(type(owners) is dict and owners and all(type(name) is str and name.startswith('ipfs_datasets_py.')
        for name in owners), 'explicit namespace-qualified source owner manifest required')
    for name, expected in owners.items():
        require(type(expected) is dict and set(expected) == {'path', 'bytes', 'sha256'}
            and pin(expected['path']) == expected and Path(expected['path']).is_relative_to(root),
            'owner manifest must bind fixed current isolated source bytes')
    helper = root / 'scripts/ops/legal_ir/prepare_arbitrary_native_legal_sources.py'
    requests_pin = pin(OLD / 'source-requests.json')
    artifacts = read(OLD / 'source-artifact-pins.json')
    requests = read(requests_pin['path'])
    require(len(requests) == 8 and len({row['id'] for row in requests}) == 8, 'eight exact source occurrences required')
    for digest, expected in artifacts.items():
        require(expected['sha256'] == digest and pin(expected['path']) == expected, 'source artifact pin differs')
    native_pin = pin(NATIVE)
    require(native_pin['bytes'] == 38209 and native_pin['sha256'] ==
        'f35d2d17ffb2269bff0f3f7f69cc01e00c36867c4e81ab63255077cfc5f0b989',
        'exact accepted native384 receipt required')
    equivalence_pin = pin(Path(args.equivalence))
    equivalence = read(equivalence_pin['path'])
    require(equivalence['schema'] == 'raw-gte384-retained-span-equivalence/v1'
        and equivalence['passed'] is True and equivalence['findings'] == []
        and equivalence['historical_context_contract']['representation_id'] == 'actual_frozen_legal_ir/raw384/v1',
        'explicit reviewed raw384 lineage equivalence required')
    decoder_states = []
    for name, field, enabled in [('raw384-1729', 'raw384_checkpoint_pin', True),
        ('source_only-1729', 'source_only_checkpoint_pin', False)]:
        checkpoint_pin = equivalence[field]
        require(pin(checkpoint_pin['path']) == checkpoint_pin, 'retained checkpoint bytes differ')
        checkpoint = read(checkpoint_pin['path'])
        require(checkpoint['schema'] == 'warm-start-span-legal-formula-checkpoint/v1'
            and checkpoint['lineage_id'] == 'warm_start_source_span_formula_v1'
            and checkpoint['base_checkpoint']['config']['latent_dimension'] == 384
            and checkpoint['base_checkpoint']['config']['latent_enabled'] is enabled
            and checkpoint['context_contract'] == equivalence['historical_context_contract'],
            'exact raw384 versus config-disabled checkpoint profiles required')
        decoder_states.append(dict(name=name, checkpoint_pin=checkpoint_pin, latent_enabled=enabled))
    old_plan = read(HISTORY / 'run-01/plan.json')
    corpus_pin = pin(Path(old_plan['corpus']['path']))
    require(corpus_pin['sha256'] == old_plan['corpus']['sha256'], 'historical authored corpus lineage differs')
    old_native_plan = read(OLD / 'experiment-plan.json')
    forbidden = sorted(set(old_native_plan['forbidden_reference_paths'] +
        [old_plan['targets']['path'], corpus_pin['path'],
         str(F / 'statutory-source-review-packet.json'),
         str(F / 'statutory-source-review-template.json')]))
    runner_path = F / 'run_joint_readout_comparison.py'
    import_fix = dict(schema='pinned-libdl-resolution/v1', requested_library='dl',
        subprocess_fallback_allowed=False, unlisted_library_names_allowed=False,
        **{field: pin(path) for field, path in IMPORT_FIX_FILES.items()})
    readout_owners = {name: pin(root / path) for name, path in {
        "ipfs_datasets_py.logic.legal_ir.joint_span_selection": "ipfs_datasets_py/logic/legal_ir/joint_span_selection.py",
        "ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture": "ipfs_datasets_py/logic/formalization/autoencoder/retained_span_score_capture.py",
    }.items()}
    paths = [Path(value["path"]) for value in readout_owners.values()] + [Path(__file__).resolve(), runner_path, F / 'run_scope_guardian.py',
        owner_path, helper, Path(equivalence_pin['path']), Path(requests_pin['path']), NATIVE,
        OLD / 'source-artifact-pins.json', OLD / 'source-view-provenance.json',
        OLD / 'post-generation-diagnostics.json', OLD / 'diagnostic-helper-retry-review.json']
    paths += [Path(value['path']) for value in artifacts.values()]
    paths += [Path(value['path']) for value in owners.values()]
    paths += [Path(value['path']) for value in equivalence['historical_recipe_evidence'].values()]
    paths += [Path(path) for path in IMPORT_FIX_FILES.values()]
    diagnostic_inventory = read(OLD / 'post-generation-diagnostics.json')['input_byte_inventory']['before']
    canonical_dependency_pins = {}
    for path, expected in diagnostic_inventory.items():
        if '/site-packages/' in path:
            require(type(expected) is dict and set(expected) == {'path', 'bytes', 'sha256'}
                and expected['path'] == path and pin(path) == expected,
                'selected canonical supporting dependency differs from actual prior diagnostic inventory')
            canonical_dependency_pins[path] = expected
            paths.append(Path(path))
    require(any(path.endswith('/multiformats_config/multicodec-table.json') for path in canonical_dependency_pins)
        and any(path.endswith('/multiformats_config/multibase-table.json') for path in canonical_dependency_pins),
        'both exact installed canonical CID table resources required')
    bindings = {}
    for path in paths:
        require(str(path) not in forbidden, 'forbidden target/corpus cannot enter numerical child inputs')
        actual = pin(path); bindings[str(path)] = {key: actual[key] for key in ('bytes', 'sha256')}
    plan = dict(schema='retained-span-joint-readout-plan/v1', package_root=str(root),
        runner_path=str(runner_path), ctypes_dl_resolution=import_fix,
        source_count=8, dimension=384, row_ids=[row['id'] for row in requests],
        controls=['none', 'zero', 'disabled', 'rotate'], decoder_states=decoder_states,
        source_owner_pins=owners, additional_readout_owner_pins=readout_owners,
        joint_selection=dict(top_k=8, max_search_nodes=50000,
            immutable_presence_and_modality=True, original_greedy_outputs_preserved=True,
            alternative_scope="new joint readout, unqualified, no semantic gain inferred"),
        raw384_equivalence_pin=equivalence_pin, helper_path=str(helper),
        selected_canonical_dependency_pins=canonical_dependency_pins,
        full_third_party_import_graph_qualified=False,
        source_configuration=dict(schema='prepare-arbitrary-native-legal-sources/v1', mode='reuse', dimension=384,
            source_requests_pin=requests_pin, source_artifact_pins=artifacts,
            native384_receipt_refs=[native_pin], native768_report_refs=[], snapshot_path=None, batch_size=None),
        historical_corpus_pin=corpus_pin, historical_corpus_scope='hashed by pure plan author for lineage; forbidden to numerical child',
        forbidden_reference_paths=forbidden, artifacts=bindings,
        actual_optimizer_updates=0, encoder_execution_planned=False, training_executed=False,
        semantic_gold=False, source_semantics_verified=False, independent_semantic_holdout=False,
        development_cohort_previously_exposed=True, selection_executed=False,
        qualified=False, proof_authority=False, Lake_executed=False, default_promotion=False,
        legacy_guardian_phase='training', legacy_phase_is_actual_training=False,
        resource_contract=dict(cpu_slots=2, rss_mib=1536, child_slots=1, storage_bytes=200000000, wall_seconds=300),
        qualification_scope='Same-pass full score capture and separate limited-pool joint span search on eight exposed law occurrences; no statutory semantic claim')
    output = Path(args.output)
    require(output.is_absolute() and output.resolve() == output and not output.exists(), 'fresh immutable absolute plan path required')
    with output.open('x', encoding='utf-8') as stream:
        json.dump(plan, stream, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    descriptor = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return pin(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-root', default=str(F / 'datasets'))
    parser.add_argument('--source-owners', required=True)
    parser.add_argument('--equivalence', default=str(F / 'raw384-equivalence.json'))
    parser.add_argument('--output', required=True)
    print(json.dumps(prepare(parser.parse_args()), sort_keys=True))
