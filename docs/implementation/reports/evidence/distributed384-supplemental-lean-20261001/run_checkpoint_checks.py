"""Actual merged-checkpoint predictions plus explicitly authored supplemental models."""
import argparse,json
from pathlib import Path
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import contracts as c
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import projection_inputs,legal_ui_inputs
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.qualification import qualify_round,CONTEXTS_SCHEMA
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.projection_context_contract import bind_context
from ipfs_datasets_py.logic.formalization.autoencoder.structured_source_384 import Runtime
from ipfs_datasets_py.logic.formalization.autoencoder.family_training_v7 import supplemental_source_ref
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.authored_semantic_projection_panel import FORMULAS
from tests.unit.logic.formalization.autoencoder.test_distributed_384_projection_inputs import security_inputs
from tests.unit.logic.formalization.autoencoder.test_distributed_384_supplemental_native_lake import bound_protocol
from tests.unit.logic.formalization.autoencoder.test_family_training_v2 import policy
from tests.unit.logic.formalization.autoencoder.test_native_concurrency_lean import fixture as concurrency_fixture
from tests.unit.logic.formalization.autoencoder.test_native_refinement_lean import fixture as refinement_fixture
from tests.unit.logic.formalization.autoencoder.test_native_protocol_lean import fixture as protocol_fixture
p=argparse.ArgumentParser();p.add_argument('--previous-run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
p.add_argument('--lake',required=True);p.add_argument('--java',required=True);p.add_argument('--sany-jar',required=True);a=p.parse_args()
records=[]
for domain in ('intent_ir','security_ir','ui_ux_ir','legal_ir'):
 old=a.previous_run/domain
 checkpoint_path=json.loads((old/'merged-result.json').read_text())['checkpoint_path']
 checkpoint,checkpoint_ref=c.read_json_bound(checkpoint_path)
 plan=json.loads((old/'coordinator/plan.json').read_text())
 raw=json.loads((old/'coordinator/validation.json').read_text())[0]
 row={key:raw[key] for key in ('id','source_text','embedding')}
 predicted=Runtime(checkpoint).infer([row])['rows'][0]
 candidate=predicted['candidate_ir']
 if domain=='security_ir':
  inputs=security_inputs({'source_text':row['source_text'],'target':candidate})
  source=projection_inputs.security_source_ref(inputs['code_unit'],row['source_text'])
  inputs['supplemental_inputs'] += [dict(kind='concurrency',document=concurrency_fixture()),
    dict(kind='refinement',document=refinement_fixture().to_dict()),
    dict(kind='protocol',document=bound_protocol(protocol_fixture(),source,row['source_text']))]
  families=None
 else:
  owner=projection_inputs if domain=='intent_ir' else legal_ui_inputs
  native=owner.prepare_source_inputs(domain,candidate,row['source_text'])
  source=supplemental_source_ref(domain,**native)
  inputs={'supplemental_inputs':[dict(kind='authorization',document=policy(source).to_dict())]}
  families=['first_order','deontic','temporal','tdfol','event_calculus','dcec','frame_logic','propositional','authorization']
 inputs['formula_inputs']=[dict(requirement_id=key,formula=value) for key,value in FORMULAS.items()]
 context=bind_context(domain,candidate,row['source_text'],inputs)
 batch=dict(schema=CONTEXTS_SCHEMA,plan_id=plan['plan_id'],checkpoint_sha256=checkpoint_ref['sha256'],
            rows=[dict(id=row['id'],context=context)],**c.FALSE)
 context_path=c.write_json(a.output/domain/'declared-context.json',batch)
 summary=qualify_round(old/'coordinator',checkpoint_path,a.output/domain/'checks',contexts_path=context_path,
   row_ids=[row['id']],required_families=families,lake_executable=a.lake,java_executable=a.java,tla2tools_jar=a.sany_jar)
 report=c.read_json(summary['records'][0]['report_path']);execution=report['native_execution']
 record=dict(domain_id=domain,rows=summary['rows'],checkpoint=summary['checkpoint'],
  supported_families=sum(x['supported'] for x in summary['family_counts'].values()),required_families=len(summary['family_counts']),
  family_counts=summary['family_counts'],all_requested_dependencies_supported=summary['all_requested_dependencies_supported'],
  all_requested_native_checks_passed=summary['all_requested_native_checks_passed'],
  native_projections=len(execution['per_projection']),complete_checks=sum(x['lake_status']=='passed' and x['parser_status']=='passed' for x in execution['per_projection']),
  summary_path=str(a.output/domain/'checks/summary.json'),scope='one tuning prediction; new supplemental models and formulas are authored context, not learned output')
 records.append(record);print(json.dumps(record),flush=True)
 del checkpoint
c.write_json(a.output/'results.json',dict(schema='distributed384-supplemental-checkpoint-replay/v1',records=records,
 training_executed=False,weights_changed=False,new_holdout_evaluation=False,context_inferred_by_model=False,**c.FALSE))
