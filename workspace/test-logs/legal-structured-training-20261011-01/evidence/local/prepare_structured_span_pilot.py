"""Pure preparation of TRAIN/TUNE-only exports and a closed four-arm recipe.

No model/package imports or resource mutations. Original corpus/context files
are inspected for exact ordered manifest reconstruction, then forbidden to the
numerical child. Authored engineering targets confer no legal authority.
"""
from hashlib import sha256
import json
import math
from pathlib import Path
import struct
import os

F = Path(__file__).resolve().parent
D = F / 'datasets'
J = F.parent / 'legal-joint-readout-20261011-01'
N = F.parent / 'legal-native-cache-20261011-01'
H = F.parent / 'legal-decoder-native-conditioning-20261002'
RUN_ROOT = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()

def digest(value):
    return sha256(canonical(value)).hexdigest()

def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            assert key not in result, 'duplicate JSON key'
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))

def pin(path):
    path = Path(path)
    assert path.is_absolute() and path.resolve() == path and path.is_file() and not path.is_symlink()
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=sha256(raw).hexdigest())

def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    return pin(path)

def export_once(path, value):
    if path.exists():
        assert read(path)==value, 'existing export differs; never overwrite'
        return pin(path)
    return write(path,value)

def main():
    old = read(J / 'experiment-plan.json')
    corpus_path, contexts_path = H/'prepared/corpus.json', H/'run-01/contexts-raw384.json'
    initial_inputs = [pin(corpus_path), pin(contexts_path)]
    assert initial_inputs[0]['sha256'] == '1480f42e29fd75ee4f78229533d727508441a2c15ed7f20aac815d66e0dce182'
    corpus, contexts = read(corpus_path), read(contexts_path)
    populations, witnesses = {}, {}
    for split, count in [('train', 1152), ('tuning', 96)]:
        rows, vectors = corpus['splits'][split], contexts[split]
        assert len(rows) == len(vectors) == count
        populations[split], witnesses[split] = [], []
        for row, vector in zip(rows, vectors, strict=True):
            source_hash = sha256(row['source_text'].encode()).hexdigest()
            assert row['id'] == vector['id'] and source_hash == row['source_sha256'] == vector['source_sha256']
            assert row['provenance'] == 'authored_synthetic_not_legal_authority'
            assert digest(vector['context']) == vector['context_sha256']
            assert len(vector['context']) == 384 and all(type(v) in (int,float) and math.isfinite(v) for v in vector['context'])
            receipt = vector['native_stage_receipt']
            assert receipt['dimension'] == 384 and receipt['admitted'] is False
            populations[split].append(dict(id=row['id'], source_text=row['source_text'],
                canonical_ir=row['canonical_ir'], latent=vector['context']))
            witnesses[split].append(dict(id=row['id'], source_sha256=source_hash,
                context_sha256=vector['context_sha256'], native_stage_receipt_sha256=digest(receipt)))
    export_pin = export_once(F/'authored-train-tune-only.json', dict(schema='authored-span-train-tune-export/v1',
        populations=populations, manifests={key:digest(rows) for key,rows in populations.items()},
        provenance='authored_synthetic_not_legal_authority', semantic_gold=False))
    export_once(F/'authored-export-receipt.json', dict(schema='ordered-authored-span-export-receipt/v1',
        export=export_pin, original_inputs=initial_inputs, row_witnesses=witnesses,
        manifests={key:digest(rows) for key,rows in populations.items()}, counts={k:len(v) for k,v in populations.items()},
        excluded_splits=['challenge','oov'], excluded_targets=True, model_imported=False,
        source_semantics_verified=False, independent_semantic_holdout=False, qualified=False))
    owners = {}
    for name, previous in read(J/'retained-owner-pins.json').items():
        target = D / Path(previous['path']).relative_to(J/'datasets')
        current = pin(target)
        assert {k:current[k] for k in ('bytes','sha256')} == {k:previous[k] for k in ('bytes','sha256')}
        owners[name] = current
    owner_pin = export_once(F/'retained-owner-pins.json', owners)
    extra = {name:pin(D/path) for name,path in {
        'ipfs_datasets_py.logic.legal_ir.structured_span_objective':'ipfs_datasets_py/logic/legal_ir/structured_span_objective.py',
        'ipfs_datasets_py.logic.formalization.autoencoder.structured_span_continuation':'ipfs_datasets_py/logic/formalization/autoencoder/structured_span_continuation.py',
        'ipfs_datasets_py.logic.legal_ir.joint_span_selection':'ipfs_datasets_py/logic/legal_ir/joint_span_selection.py',
    }.items()}
    arms = []
    for parent in old['decoder_states']:
        original = read(parent['checkpoint_pin']['path'])
        assert pin(parent['checkpoint_pin']['path']) == parent['checkpoint_pin']
        for key,split in [('training','train'),('tuning','tuning')]:
            assert digest(populations[split]) == original['base_checkpoint'][key+'_manifest_sha256']
        for weight,suffix in [(0.,'ce0'),(.1,'probability01')]:
            arms.append(dict(name=parent['name']+'-'+suffix, parent_file_pin=parent['checkpoint_pin'],
                parent_canonical_sha256=digest(original), latent_enabled=parent['latent_enabled'],
                structure_weight=weight, new_steps=32))
    requests = read(N/'source-requests.json')
    native_path = RUN_ROOT/'arbitrary-native-cache-20261011-02/results/source-production/native384-receipt-001.json'
    native = read(native_path)
    law = []
    for request in requests:
        matches=[(i,r) for i,r in zip(native['inputs'],native['results'],strict=True)
            if i['text']==request['source_text'] and i['source']==request['source']]
        assert len(matches)==1
        incoming,result = matches[0]
        assert incoming['input_id']==result['input_id'] and result['status']=='embedded'
        vector=result['vector']; assert vector['dimension']==384 and vector['encoding']=='float32-be-hex'
        raw=bytes.fromhex(vector['bits']); assert len(raw)==1536
        values=list(struct.unpack('>384f',raw)); assert all(math.isfinite(v) for v in values)
        source=request['source']; artifact=read(N/'source-artifact-pins.json')[source['artifact']['sha256']]
        assert pin(artifact['path'])==artifact
        assert Path(artifact['path']).read_bytes()[source['byte_start']:source['byte_end']].decode()==request['source_text']
        law.append(dict(id=request['id'],source_text=request['source_text'],latent=values))
    law_pin=export_once(F/'exposed-law-source-only.json',dict(schema='exposed-law-source-only-diagnostics/v1',
        rows=law, native_receipt=pin(native_path), requests=pin(N/'source-requests.json'),
        source_context_pins=read(N/'source-artifact-pins.json'), semantic_gold=False,
        source_semantics_verified=False, previously_exposed=True, used_for_updates_or_selection=False))
    paths=[Path(__file__),F/'run_structured_span_pilot.py',F/'run_scope_guardian.py',
        Path(export_pin['path']),Path(law_pin['path']),Path(owner_pin['path']),F/'authored-export-receipt.json',
        F/'structured-objective-build-v01.json', F/'structured-span-continuation-build-v01.json',
        F/'structured-objective-independent-review-v01.json']
    paths += [Path(v['path']) for v in owners.values()] + [Path(v['path']) for v in extra.values()]
    paths += [Path(v['parent_file_pin']['path']) for v in arms]
    paths += [Path(v['path']) for v in old['selected_canonical_dependency_pins'].values()]
    paths += [Path(old['ctypes_dl_resolution'][k]['path']) for k in ('library_pin','ctypes_util_pin','cuda_pathfinder_pin')]
    paths += [Path(native_path), N/'source-requests.json', N/'source-artifact-pins.json', N/'source-view-provenance.json']
    paths += [Path(v['path']) for v in read(N/'source-artifact-pins.json').values()]
    equivalence=read(J/'raw384-equivalence.json')
    assert equivalence['passed'] is True and equivalence['findings']==[]
    assert all(equivalence['historical_context_contract']==read(a['parent_file_pin']['path'])['context_contract'] for a in arms)
    equivalence_pin=pin(J/'raw384-equivalence.json');paths.append(Path(equivalence_pin['path']))
    forbidden=sorted(set(old['forbidden_reference_paths']+[str(corpus_path),str(contexts_path),
        str(J/'statutory-source-review-packet.json'),str(F/'statutory-review-pending-recording.json')]))
    assert not set(map(str,paths)) & set(forbidden)
    artifacts={str(p):{k:pin(p)[k] for k in ('bytes','sha256')} for p in paths}
    for value in initial_inputs: assert pin(value['path'])==value
    plan=dict(schema='structured-source-span-four-arm-plan/v1',package_root=str(D),runner_path=str(F/'run_structured_span_pilot.py'),
        arms=arms, train_tune_export=export_pin, law_diagnostic_export=law_pin,
        source_owner_pins=owners, additional_owner_pins=extra, artifacts=artifacts,
        ctypes_dl_resolution=old['ctypes_dl_resolution'],resource_contract=old['resource_contract'],
        raw384_equivalence_pin=equivalence_pin,
        raw384_equivalence_scope='reviewed operator/profile compatibility only; batch difference disclosed; not bit equality or statutory semantics',
        forbidden_reference_paths=forbidden, controls=['none','zero','disabled','rotate'],
        training_seconds_per_arm=32,diagnostic_deadline_scope='overall guardian300s only; no individual evaluation timer',
        tuning_exact_ceiling=96, tuning_count=96, training_count=1152, equal_schedule=True,
        seed=1729, dimension=384, historical_Adam_steps=400, total_new_updates_requested=128,
        objective='CE + weight * (validity + overlap) / 2',weights=[0.,.1],
        encoder_execution_planned=False, semantic_gold=False, independent_semantic_holdout=False,
        authored_tuning_previously_exposed=True, law_previously_exposed=True,
        checkpoint_selection_executed=False, default_promotion=False, Lake_executed=False,
        logic_family_scope='one flat copied-span O/P/F deontic rule; broader families unqualified',
        numerical_probes=['same-forward CE parity','uniform N2 order log(4/3), overlap7/9','finite backward','padding structural invariance'],
        legacy_guardian_phase='training',legacy_phase_is_actual_training=True,
        qualification_scope='bounded authored geometry experiment; real8 diagnostic-only; no legal accuracy claim')
    print(json.dumps(write(F/'experiment-plan-v02.json',plan),sort_keys=True))

if __name__=='__main__': main()
