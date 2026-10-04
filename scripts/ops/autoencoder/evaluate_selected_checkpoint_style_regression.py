#!/usr/bin/env python3
"""Score four fixed endpoints on an already exposed authored style cohort.

All source-only greedy outputs are durable before style references are opened.
This phase cannot train, select, promote or qualify a model.
"""
import argparse,hashlib,importlib.util,json,time
from pathlib import Path
from types import SimpleNamespace

PARENT='scripts/ops/autoencoder/observe_fresh_normative_style.py'
ROLES=('selected','last-attempt')
FALSE=dict(qualified=False,admitted=False,proof_authority=False,formalized=False,roundtrip_ok=False,
 checkpoint_promoted=False,convergence_proven=False,lake_executed=False,native_validation_executed=False,
 source_semantics_verified=False,training_executed=False,selection_performed=False,downloads_performed=False,
 fresh_holdout=False,fresh_authored_holdout=False,historical_linguistic_teacher_modified=False)
FIXED=dict(schema='selected-checkpoint-style-regression-plan/v1',dimensions=[384,768],roles=list(ROLES),panel_count=4,samples_per_panel=48,
 context_tokens=512,max_target_tokens=512,temperature=0,batch_size=8,full_vocabulary_size=32,
 source_only_generation=True,all_predictions_before_reference_load=True,style_cohort_already_exposed=True,
 used_for_selection=False,encoder_executed=False,source_vectors_reused=True,preprocessing_refitted=False,
 greedy_passes_per_endpoint=1,max_seconds_per_panel=30,max_seconds_entire_phase=600,**FALSE)

def require(v,m):
 if not v:raise ValueError(m)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def bound(m,p,expected=None):
 p=Path(p).resolve();want=m['inputs'].get(str(p));require(want is not None and(expected is None or want==expected),'unbound regression input')
 raw=p.read_bytes();require(hashlib.sha256(raw).hexdigest()==want,'regression input changed');return json.loads(raw)
def validate_plan(p):
 require(type(p) is dict and all(type(p.get(k)) is type(v) and json.dumps(p[k],sort_keys=True)==json.dumps(v,sort_keys=True) for k,v in FIXED.items()),'fixed exposed-regression plan differs')

def validate_barrier(records,expected_ids):
 require(set(expected_ids)=={384,768} and all(len(v)==len(set(v))==48 for v in expected_ids.values()),'complete source identities required')
 require(len(records)==4 and [(r['dimension'],r['role']) for r in records]==[(d,r) for d in (384,768) for r in ROLES],'all four registered predictions required')
 for r in records:
  p=Path(r['predictions_ref']['path']);require(sha(p)==r['predictions_ref']['sha256'],'persisted prediction changed')
  v=json.loads(p.read_bytes());require(v['complete'] and v['generation_reference_access'] is False and v['model_tensor_sha256']==r['state_ref']['tensor_sha256'],'incomplete or mismatched source prediction')
  require([x['id'] for x in v['predictions']]==expected_ids[r['dimension']],'prediction rows incomplete or reordered')
  require(v['generation_temperature']==0 and v['max_target_tokens']==512 and v['greedy_passes_per_row']==1,'source generation policy differs')

def execute(args):
 started=time.monotonic();m=json.loads(args.manifest.read_bytes());p=json.loads(args.plan.read_bytes());validate_plan(p)
 require(sha(args.plan)==m['plan_sha256'] and p['input_sha256']==m['inputs'],'regression seal differs')
 for path,wanted in m['inputs'].items():require(sha(path)==wanted,'bound regression input changed')
 for rel,wanted in m['extensions'].items():require(sha(args.extension_root/rel)==wanted,'frozen regression source changed')
 original=bound(m,m['observation_manifest']);bound(m,m['observation_plan']);root=Path(m['observation_extension_root'])
 require(sha(root/PARENT)==original['extensions'][PARENT],'frozen observation driver changed')
 spec=importlib.util.spec_from_file_location('_exposed_style_parent',root/PARENT);parent=importlib.util.module_from_spec(spec);spec.loader.exec_module(parent)
 oldargs=SimpleNamespace(**vars(args));oldargs.extension_root=root;oldargs.manifest=Path(m['observation_manifest']);oldargs.plan=Path(m['observation_plan'])
 ctx=parent.load_context(oldargs);ctx['fresh_manifest']=m
 require(not args.output.exists(),'fresh regression output required');args.output.mkdir(parents=True);save=ctx['helpers'].save
 before=parent.source_inventory(args,m);save(args.output/'sealed-recipe.json',dict(plan=p,manifest=m,**FALSE))
 training=bound(m,m['training_summary']);require(training['complete'] and training['dimensions_actually_trained']==[384,768] and len(training['runs'])==2,'two complete training runs required')
 runs={}
 for item in training['runs']:
  run=bound(m,item['summary_path'],item['summary_sha256']);require(run['budget_completed'] and run['recipe']=={'name':'continue-lr0001','learning_rate':.0001},'fixed selected continuation endpoint required');runs[run['dimension']]=run
 require(set(runs)=={384,768},'closed followup dimension inventory')
 records=[];expected_ids={};generator=ctx['exposed_evaluator']
 for dimension in (384,768):
  lane=parent.prepare_lane(ctx,dimension);expected_ids[dimension]=[r['id'] for r in lane['fresh_rows']];run=runs[dimension]
  for role in ROLES:
   state=run['states'][role];bound(m,state['path'],state['sha256'])
   model=ctx['fresh_parent'].restore_model(lane,state,run['recipe'],role)
   panel=generator.generate_panel(ctx,lane,model,time.monotonic()+30)
   panel.update(schema='selected-checkpoint-style-regression-predictions/v1',style_cohort_already_exposed=True,used_for_selection=False,**FALSE)
   records.append(dict(dimension=dimension,arm=run['arm'],role=role,state_ref=state,predictions_ref=save(args.output/f'{dimension}-{role}-predictions.json',panel)))
   del model,panel
 validate_barrier(records,expected_ids)
 save(args.output/'predictions-complete.json',dict(complete=True,panels=records,style_reference_json_loaded=False,all_predictions_persisted_before_reference_load=True,**FALSE))
 # Existing two-width reference authentication is reused only after all FOUR
 # endpoints have passed the stronger closed barrier above.
 refs,receipt=parent.load_references(ctx,[r for r in records if r['role']=='selected'])
 scored=[]
 for r in records:
  lane=parent.prepare_lane(ctx,r['dimension']);run=runs[r['dimension']]
  require(receipt['source_rows_sha256']==ctx['core'].digest([{k:s[k] for k in ('id','source_text')} for s in lane['fresh_rows']]),'source/reference alignment differs')
  model=ctx['fresh_parent'].restore_model(lane,r['state_ref'],run['recipe'],r['role'])
  prediction=json.loads(Path(r['predictions_ref']['path']).read_bytes());score=generator.score_panel(ctx,lane,model,prediction,refs,time.monotonic()+30)
  score.update(schema='selected-checkpoint-style-regression-score/v1',style_cohort_already_exposed=True,used_for_selection=False,**FALSE)
  scored.append(dict(r,score_ref=save(args.output/f'{r["dimension"]}-{r["role"]}-score.json',score),ordered_exact=score['fidelity']['metrics']['ordered_exact'],syntax_valid=score['fidelity']['metrics']['syntax_valid'],teacher_forced_cross_entropy=score['teacher_forced']['token_cross_entropy']))
  del model,score
 after=parent.source_inventory(args,m);require(all(after.get(k)==v for k,v in before.items()),'loaded source changed')
 for path,wanted in m['inputs'].items():require(sha(path)==wanted,'regression input changed during scoring')
 for rel,wanted in m['extensions'].items():require(sha(args.extension_root/rel)==wanted,'regression source changed during scoring')
 require(time.monotonic()-started<600,'regression phase deadline exceeded')
 result=dict(schema='selected-checkpoint-style-regression/v1',complete=True,panels=scored,source_dependencies=after,elapsed_seconds=time.monotonic()-started,encoder_executed=False,style_cohort_already_exposed=True,used_for_selection=False,**FALSE)
 save(args.output/'summary.json',result);print(json.dumps(dict(complete=True,panels=[{k:x[k] for k in ('dimension','role','ordered_exact','teacher_forced_cross_entropy')} for x in scored])));return result

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('dependency-root','extension-root','manifest','plan','output'):p.add_argument('--'+name,type=Path,required=True)
 p.add_argument('--phase',choices=['evaluation'],required=True);execute(p.parse_args())
if __name__=='__main__':main()
