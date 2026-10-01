import hashlib, json, time, subprocess
from pathlib import Path
import torch
torch.set_num_threads(1)
from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_learning as learning
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_checkpoint as storage
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as interface
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_decoded_schema import validate_decoded_outputs
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span, vocabulary_from_clause
from ipfs_datasets_py.logic.autoformal.family_qualification import qualify_logic_families
from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalAtomVocabulary, CompilerRequest
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_candidate_qualification as qualification
ROOT=Path.cwd(); OUT=Path(__file__).resolve().parent
started=time.monotonic()
def write(name, value):
    (OUT/name).write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n')
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
pin=require_workspace_logic_tree(); hashes={k:digest(v) for k,v in pin.items()}
corpus=json.loads((ROOT/'tests/fixtures/legal_formula_learning/v1.json').read_text())
training=json.loads((OUT/'train/report.json').read_text())
checkpoint=learning.load_checkpoint(training['checkpoint']['path'],expected_sha256=training['checkpoint']['sha256'])
result={'checkpoint':checkpoint,'report':training['training']}
with AutoencoderRegistry(OUT/'control.duckdb',OUT/'artifacts') as registry:
    first=storage.register_candidate(registry,result,OUT/'registered-first')
write('registered-first.json',first)
with AutoencoderRegistry(OUT/'control.duckdb',OUT/'artifacts') as registry:
    runtime=interface.load_version(registry,first['version_id'],domain='legal_ir',version=interface.LEARNED_FORMULA_VERSION)
    assert runtime.checkpoint==checkpoint
    before=runtime.checkpoint
    sources=[x['source_text'] for x in corpus['heldout']]
    infer_started=time.monotonic(); inference=runtime.infer(sources); infer_wall=time.monotonic()-infer_started
    write('heldout-inference.json',inference)
    assert runtime.checkpoint==before
    schema_started=time.monotonic()
    schemas=validate_decoded_outputs(runtime,sources,output_directory=OUT/'heldout-lake',timeout_seconds=60)
    schema_wall=time.monotonic()-schema_started
    rows=[]
    for target,prediction in zip(corpus['heldout'],inference['rows']):
        rows.append({'id':target['id'],'source_text':target['source_text'],'source_sha256':prediction['source_sha256'],
            'expected':target['canonical_ir'],'actual':prediction['canonical_ir'],
            'exact_match':target['canonical_ir']==prediction['canonical_ir'],'full_inference':prediction})
    write('heldout-comparison.json',rows)
    resume_started=time.monotonic()
    resumed=runtime.train(corpus['train'],validation_samples=corpus['tuning'],epochs=1,max_seconds=60,batch_size=8,learning_rate=.008,seed=1729)
    second=runtime.register_candidate(registry,OUT/'registered-second')
    recovered=interface.load_version(registry,second['version_id'],domain='legal_ir',version=interface.LEARNED_FORMULA_VERSION)
    assert recovered.checkpoint==resumed['checkpoint']
    assert registry.get_version(second['version_id'])['parent_version_id']==first['version_id']
    assert resumed['checkpoint']['parent_checkpoint_sha256']==learning.checkpoint_digest(checkpoint)
    expected=learning.train_decoder(corpus['train'],corpus['tuning'],checkpoint=checkpoint,epochs=1,max_seconds=60,batch_size=8,learning_rate=.008,seed=1729)
    assert expected['checkpoint']==resumed['checkpoint'], 'resumed full model/Adam/cursor state differs'
    resume_wall=time.monotonic()-resume_started
write('registered-second.json',second);write('resume-training-report.json',resumed['report'])
lock,lockpath,lockhash=qualification._statement_lock()
gates=[]
for i,text in enumerate(['Company A shall submit backup report within 10 days unless emergency.', 'The agency shall not disclose records.', 'The officer shall retain the file for at least 20 days.']):
    start=time.monotonic(); vocab=vocabulary_from_clause(text); vocab_seconds=time.monotonic()-start
    assert vocab and all(isinstance(atom,str) for group in vocab.values() for atom in group)
    start=time.monotonic(); direct=TypedDeonticCanonicalCompiler().compile(CompilerRequest(source_text=text,request_id=f'gate-direct-{i}',atom_vocabulary=CanonicalAtomVocabulary(**vocab))); compile_seconds=time.monotonic()-start
    direct_payload=direct.to_dict()
    empty=TypedDeonticCanonicalCompiler().compile(CompilerRequest(source_text=text,request_id=f'gate-empty-{i}',atom_vocabulary=CanonicalAtomVocabulary())).to_dict()
    start=time.monotonic(); outcome=compile_span(AutoformalSession(),text,f'gate-{i}'); span_seconds=time.monotonic()-start
    assert outcome['compiler_status']=='compiled'
    rule=outcome['rule'];pattern=lock.pattern_from_rule(rule)
    if i==0:
        assert rule['modality']=='O' and '10 days' in outcome['decompiled'] and 'emergency' in outcome['decompiled']
        assert any(x['temporal_kind']=='within_duration' for x in rule['temporal_records'])
        assert pattern is None
    elif i==1: assert rule['modality']=='F'
    else:
        assert any(x['temporal_kind']=='minimum_duration' and x['quantity']==20 for x in rule['temporal_records'])
        assert 'at least 20 days' in outcome['decompiled'] and 'at least days' not in outcome['decompiled']
    assert direct_payload['status']=='success' and direct_payload['canonical_ir'] is not None
    assert empty['status']=='abstained' and empty['canonical_ir'] is None and empty['error']['code']=='unsupported_semantics', empty
    family=qualify_logic_families(text,rule,source_id=f'gate-{i}')
    gates.append({'source_text':text,'source_sha256':hashlib.sha256(text.encode()).hexdigest(),'vocabulary':vocab,
        'vocabulary_seconds':vocab_seconds,'direct_compiler_seconds':compile_seconds,'compile_span_seconds':span_seconds,
        'direct_compiler':direct_payload,'empty_vocabulary':empty,'compile_span':outcome,'family_syntax':family,'lean_pattern':pattern})
    write('compiler-gates.json',gates)
legal_lake=qualification._lake_gate(gates[2]['compile_span']['rule'],roundtrip_ok=gates[2]['compile_span']['roundtrip'],output_directory=OUT/'numeric-lake-legal',timeout_seconds=60,statement_lock=lock)
write('numeric-lake-legal.json',legal_lake)
assert legal_lake['passed'] and legal_lake['admitted'] and legal_lake['command']==['lake','build','Legal']
assert hashes=={k:digest(v) for k,v in pin.items()}, 'canonical logic source changed during observation'
report={'schema':'fresh-legal-decoder-e2e-smoke/v1','git_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
 'canonical_tree':str(ROOT),'tree_pin':pin,'logic_source_sha256':hashes,'logic_source_unchanged':True,
 'fixture_provenance':corpus['provenance'],'fixture_sha256':digest(ROOT/'tests/fixtures/legal_formula_learning/v1.json'),
 'training_rows':len(corpus['train']),'tuning_rows':len(corpus['tuning']),'heldout_rows':len(rows),'heldout_used_for_training_or_selection':False,
 'training':{k:v for k,v in training['training'].items() if k!='batch_losses'},'full_training_report':str(OUT/'train/report.json'),
 'heldout_decoded_count':inference['decoded_count'],'heldout_exact_count':sum(r['exact_match'] for r in rows),
 'heldout_mismatches':[r for r in rows if not r['exact_match']],'heldout_inference_wall_seconds':infer_wall,'heldout_inference_seconds_per_span':infer_wall/len(rows),
 'schema_lake_pass_count':schemas['schema_pass_count'],'schema_lake_build_count':schemas['lake_build_count'],'schema_lake_wall_seconds':schema_wall,
 'duckdb_registered_versions':[first['version_id'],second['version_id']],'duckdb_reload_equal':True,'resume_exact_state_equal':True,'resume_wall_seconds':resume_wall,
 'resume_progress':resumed['checkpoint']['progress'],'compiler_gate_count':len(gates),'compiler_gates_pass':True,
 'numeric_lake_scope':'source_locked_numeric_pattern_only_not_whole_rule_semantics','numeric_lake_pass':legal_lake['passed'],
 'bridge_names':[],'legal_ir_target_count':0,'legal_ir_evaluate_provers':False,'legal_ir_parallel_workers':1,'metric_disk_cache':False,'bridge_on_measurement':False,
 'cache_scope':'fresh_checkpoints_and_lake_projects_metric_bridge_cache_not_invoked','temperature':0,'torch_threads':1,'device':'cpu',
 'weights_downloaded':False,'constitution_formalized':False,'qualified':False,'formalized':False,'admitted':False,'elapsed_seconds':time.monotonic()-started}
write('summary.json',report)
print(json.dumps({k:report[k] for k in ['heldout_decoded_count','heldout_exact_count','schema_lake_pass_count','resume_exact_state_equal','compiler_gates_pass','elapsed_seconds']}))
