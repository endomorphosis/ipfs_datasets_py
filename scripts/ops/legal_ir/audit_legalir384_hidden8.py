"""Audit a trained LegalIR384 residual hidden activation as a future8D feature.

This read-only tensor diagnostic produces no training contexts or decoder trial.
It checks exact existing checkpoint provenance and two source-bound core vectors.
The identity skip keeps384 coordinates outside the8D residual activation; this
activation is not the historical8D autoencoder or a proven sufficient encoding.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
HELPERS=ROOT/'ipfs_datasets_py/logic/formalization/autoencoder'
SCHEMA='legalir384-residual-hidden8-audit-config/v1'
REFS=('package','original_head','fit_report','conditioning_bundle','source_artifact')


def require(condition,message):
    if not condition:raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest()


def file_ref(path):
    path=Path(path).resolve();raw=path.read_bytes()
    return {'path':str(path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def read_ref(reference):
    require(type(reference) is dict and set(reference)=={'path','bytes','sha256'} and file_ref(reference['path'])==reference,
        'exact input byte binding required')
    require(reference['bytes']<=128*1024**2,'bounded input JSON required')
    def unique(items):
        result={}
        for key,value in items:
            require(key not in result,'duplicate JSON key');result[key]=value
        return result
    return json.loads(Path(reference['path']).read_bytes(),object_pairs_hook=unique,
        parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON '+x)))


def write(path,value):
    with Path(path).open('xb') as handle:
        handle.write(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode())
    return file_ref(path)


def run(config_path,expected_sha256,output):
    config_ref=file_ref(config_path)
    require(config_ref['sha256']==expected_sha256,'configuration hash differs')
    config=read_ref(config_ref)
    require(set(config)=={'schema','source_ids',*REFS} and config['schema']==SCHEMA,'closed hidden8 audit configuration required')
    require(type(config['source_ids']) is list and len(config['source_ids'])==len(set(config['source_ids']))==2,
        'two distinct predeclared source IDs required')
    spec=importlib.util.spec_from_file_location('_hidden8_cpu_resources',HELPERS/'gte_worker_contract.py')
    resource_helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(resource_helper)
    resources=resource_helper.configure_cpu_process({'device':'cpu','threads':1,'max_rows':4096,
        'memory_limit_mib':16384,'cpu_time_limit_seconds':120})
    if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_native_conditioning as native
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as formula
    import torch
    torch.set_num_threads(1)
    implementations=[file_ref(__file__),file_ref(resource_helper.__file__),file_ref(native.__file__),file_ref(formula.__file__)]
    inputs={name:read_ref(config[name]) for name in REFS}
    package,original,fit,bundle,splits=[inputs[name] for name in REFS]
    require(package['dimension']==384 and bundle['package']['sha256']==config['package']['sha256'],'published384 package differs')
    head=package['formula_checkpoint']
    require(head['binding']==package['core_binding'] and head['binding']['dimension']==384
        and head['config']['projection_width']==8 and head['progress']['optimizer_steps']==1000,'exact trained384 residual head required')
    require(original['model_state']==head['model_state'] and original['optimizer_state']==head['optimizer_state'],
        'published package changed original head weights or optimizer')
    require(fit['head']['sha256']==config['original_head']['sha256']
        and fit['training_report']['checkpoint_sha256']==config['original_head']['sha256']
        and fit['training_report']['optimizer_steps']==1000,'fit report does not bind original1000-step head')
    require(fit['training_report']['training_executed'] is True,'saved fit must record actual training')
    source_by_id={}
    require(set(splits)=={'train','tuning','challenge','oov'},'source-only four-split artifact required')
    for rows in splits.values():
        for row in rows:
            require(set(row)<={'id','source_text','source_sha256','family_group'} and row['id'] not in source_by_id,
                'unique source-only identity required')
            require(hashlib.sha256(row['source_text'].encode()).hexdigest()==row['source_sha256'],'source text hash differs')
            source_by_id[row['id']]=row
    ordered=[{'id':row['id'],'source_text':source_by_id[row['id']]['source_text']} for row in bundle['rows']]
    validated=native.stage_rows(bundle,stage='core384',sources=ordered)
    require(len(validated)==len(source_by_id),'complete cached source/core coverage required')
    require(config['source_ids']==[r['id'] for r in bundle['rows'][:2]],'diagnostic sources must be first two frozen bundle rows')
    by_id={row['id']:row for row in bundle['rows']}
    selected=[by_id[identity] for identity in config['source_ids']]
    private=formula.LatentFormulaDecoder(head,expected_binding=package['core_binding'])
    initial=formula._model(head['binding'],head['codec'],head['config'])
    initial_state={key:value.detach().tolist() for key,value in initial.state_dict().items()}
    initial_hash=formula.checkpoint_digest(initial_state)
    require(initial_hash==fit['initial_identity']['model_state'],'seeded constructor differs from archived initialization')
    tensor_evidence={}
    keys=('projection_down.weight','projection_down.bias','projection_up.weight','projection_up.bias')
    expected_shapes=((8,384),(8,),(384,8),(384,))
    for name,shape in zip(keys,expected_shapes):
        tensor=private.model.state_dict()[name];start=initial.state_dict()[name]
        require(tuple(tensor.shape)==shape,'residual tensor shape differs')
        moments=head['optimizer_state']['parameters'][name]
        require(moments['step']==1000,'residual optimizer step differs')
        delta=(tensor-start).double()
        evidence={'shape':list(shape),'trained_tensor_sha256':digest(tensor.tolist()),'initial_tensor_sha256':digest(start.tolist()),
            'changed_elements':int((tensor!=start).sum()),'element_count':tensor.numel(),
            'parameter_change_l2':float(torch.linalg.vector_norm(delta)),
            'adam_step':moments['step'],'adam_exp_avg_l2':float(torch.linalg.vector_norm(torch.tensor(moments['exp_avg'],dtype=torch.float64))),
            'adam_exp_avg_sq_sum':float(torch.tensor(moments['exp_avg_sq'],dtype=torch.float64).sum())}
        require(evidence['changed_elements']>0 and evidence['adam_exp_avg_l2']>0 and evidence['adam_exp_avg_sq_sum']>0,
            'trained residual parameter evidence missing')
        tensor_evidence[name]=evidence
    x=torch.tensor([row['stages']['core384']['vector'] for row in selected],dtype=torch.float32)
    before=formula.checkpoint_digest({key:value.tolist() for key,value in private.model.state_dict().items()})
    private._check()
    with torch.no_grad():
        hidden=torch.tanh(private.model.projection_down(x))
        reconstructed=x+private.model.projection_up(hidden)
    expected=torch.tensor([row['stages']['trained384']['vector'] for row in selected],dtype=torch.float32)
    require(tuple(hidden.shape)==(2,8) and bool(torch.isfinite(hidden).all()),'finite two-source8D activation required')
    require(torch.equal(reconstructed,expected),'residual calculation differs from cached trained384')
    difference=float(torch.linalg.vector_norm(hidden[0]-hidden[1]))
    require(difference>0,'two retained source inputs did not produce distinct hidden activations')
    private._check()
    after=formula.checkpoint_digest({key:value.tolist() for key,value in private.model.state_dict().items()})
    require(before==after,'read-only tensor diagnostic changed model')
    cases=[]
    for index,row in enumerate(selected):
        source=source_by_id[row['id']]
        cases.append({'id':row['id'],'source_text':source['source_text'],'source_sha256':row['source_sha256'],
            'core384_vector_sha256':native.digest(row['stages']['core384']['vector']),
            'core384_stage_receipt_sha256':row['stages']['core384']['receipt']['receipt_sha256'],
            'trained384_vector_sha256':native.digest(row['stages']['trained384']['vector']),
            'hidden8_values':hidden[index].tolist(),'hidden8_vector_sha256':digest(hidden[index].tolist()),
            'reconstructed384_bitwise_equal_to_cached_trained384':bool(torch.equal(reconstructed[index],expected[index]))})
    report={'schema':'legalir384-residual-hidden8-lineage-audit/v1','status':'future_candidate_inspected_not_trialed',
        'configuration':config_ref,'input_artifacts':{name:config[name] for name in REFS},'implementation_files':implementations,
        'candidate_stage':'legalir384_residual_hidden8/v1','input_stage':'authenticated source_parser_sparse_core_projection/core384',
        'source_to_input_recipe':['Pinned native GTE-small384 source embedding receipt and source text',
            'legal_384_package._rows using the bound current_v2 source parser',
            'modal_joint_formula.raw_projection with sample memory and target-aware safety reconstruction excluded',
            'Strict LatentFormulaDecoder load with exact package core binding'],
        'activation_recipe':{'operation':'tanh(linear(core384, projection_down.weight, projection_down.bias))',
            'formula':'h8 = tanh(core384 @ W_down.T + b_down)','activation':'tanh','dimension':8,
            'dtype':'float32','device':'cpu','normalization':'none; bounded tanh coordinates are not unit-normalized',
            'residual_reconstruction':'trained384 = core384 + h8 @ W_up.T + b_up',
            'no_decoder_tokens_or_targets_used':True},
        'bound_head':{'package_sha256':config['package']['sha256'],'formula_checkpoint_content_sha256':formula.checkpoint_digest(head),
            'core_binding':package['core_binding'],'optimizer_steps':1000,'training_count':head['training_count'],'tuning_count':head['tuning_count'],
            'original_head_weights_and_optimizer_unchanged_in_package':True,
            'packaging_compatibility_scope':package['provenance']['compatibility']['scope']},
        'initialization_evidence':{'seed':head['config']['seed'],'archived_initial_model_state_sha256':fit['initial_identity']['model_state'],
            'reconstructed_initial_model_state_sha256':initial_hash,'exact_match':True},
        'tensor_evidence':tensor_evidence,'archived_fit_projection_evidence':fit['training_report']['parameter_evidence']['projection'],
        'archived_formula_to_projection_gradient_norm_max':fit['training_report']['formula_projection_gradient_norm_max'],
        'numeric_probe':{'selection':'First two source identities in the already-frozen conditioning bundle; no reference selection',
            'cases':cases,'hidden_shape':[2,8],'source_activation_difference_l2':difference,
            'reconstructed384_max_abs_difference':float((reconstructed-expected).abs().max()),
            'model_state_sha256_before':before,'model_state_sha256_after':after,'model_unchanged':True,
            'activation_computation_executed':True,'decoder_generation_executed':False,'encoder_inference_executed':False},
        'limitations':['The identity skip carries all384 core coordinates outside the8D activation; hidden8 is a residual feature, not an established sufficient compression.',
            'This is not the historical linguistic8D feature profile, the original historical8D autoencoder, or the fixture-bound legacy8 formula head.',
            'Weights were trained jointly for residual reconstruction and closed-vocabulary formula decoding; usefulness as a stand-alone context requires a separate matched experiment.',
            'The numerical check covers two already-exposed sources, not independent legal accuracy or full-corpus embedding production.'],
        'current_experiment_changed':False,'new_native8_trial_run':False,'training_executed':False,'source_semantics_verified':False,
        'qualified':False,'proof_authority':False,'resources':resources,
        'reproduction':{'command':[sys.executable,str(Path(__file__).resolve()),'--config',config_ref['path'],
            '--expected-config-sha256',config_ref['sha256'],'--output','<fresh-output.json>'],
            'runtime':{'python':sys.version.split()[0],'torch':torch.__version__},
            'recipe_scope':'Exact input bytes, seeded initialization, float32 operations and values retained; writes only a fresh audit JSON.'}}
    for reference in [config_ref,*[config[name] for name in REFS],*implementations]:
        require(file_ref(reference['path'])==reference,'audit input or implementation changed')
    return write(output,report)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--expected-config-sha256',required=True)
    parser.add_argument('--output',required=True);args=parser.parse_args()
    print(json.dumps(run(args.config,args.expected_config_sha256,args.output),sort_keys=True))


if __name__=='__main__':main()
