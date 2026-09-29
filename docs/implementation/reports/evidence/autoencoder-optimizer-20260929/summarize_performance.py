"""Summarize sealed wall-time observations; never infer admission from timing."""
import json,hashlib
from pathlib import Path
BASE=Path(__file__).resolve().parent

def desc(p):return {'path':str(p.relative_to(BASE)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
rows=[]
for label in ['baseline','optimized','scaled','refined','shared']:
 command=BASE/(label+'-command.json');audit=BASE/(label+'-audit.json')
 if not command.exists() or not audit.exists():continue
 c=json.loads(command.read_text());a=json.loads(audit.read_text());assert a['passed']
 assert a['command']['sha256']==hashlib.sha256(command.read_bytes()).hexdigest()
 events=[];native_builds=0;hydration=0.0;receipts=[]
 for p in sorted((BASE/label/'progress/outputs').glob('*/receipt.json')):
  x=json.loads(p.read_text());receipts.append(desc(p));hydration+=x['target_hydration_seconds']
  for event in x['training_report']['projection_profile']['events']:
   e=event.get('metadata',{}).get('evaluation_profile')
   if not e:continue
   native_builds+=e['target_observation']['native_evaluation_attempt_count']
   if event['stage']=='before_holdout_evaluation':
    events.append({'training_source':x['job_spec']['samples'][0]['text'],'evaluation_role':'before_holdout_evaluation','evaluated_sources':[row['text'] for row in x['job_spec']['validation_samples']],'total_seconds':e['total_seconds'],'sample_count':e['sample_count'],**e['target_observation']})
 cycle=next((BASE/label/'cycles').glob('*/cycle.json'));z=json.loads(cycle.read_text())
 resource=next((BASE/label/'cycles').glob('*/resources.json'));r=json.loads(resource.read_text())
 observations=next((BASE/label/'cycles').glob('*/process-observations.json'));o=json.loads(observations.read_text())
 first_times=[e['total_seconds'] for e in events]
 rows.append({'label':label,'wall_seconds':c['wall_seconds'],'wall_seconds_per_input_span':c['wall_seconds']/len(events),
 'input_count':len(events),'validation_count':1,'qualified_count':a['counts']['qualified'],
 'first_bridge_evaluations':events,'first_bridge_seconds_range':[min(first_times),max(first_times)],
 'native_builds_in_profiled_training_evaluations':native_builds,'worker_target_hydration_seconds_sum':hydration,
 'sampled_peak_group_rss_bytes':max(sum(v['rss_bytes'] for v in sample['processes']) for sample in o),
 'sampled_peak_group_processes':max(len(sample['processes']) for sample in o),
 'reserved_cpu_slots':r['record']['cpu_slots'],'reserved_child_process_slots':r['record']['child_process_slots'],
 'reserved_memory_mb':r['record']['memory_mb'],'resource_status':r['status'],
 'resource_finalization_profile':r['record'].get('finalization_profile'),
 'dispatch_widths':[v['workers'] for v in z['training']['capacity_reports']],
 'receipts':receipts,'command':desc(command),'audit':desc(audit),'use_sample_memory':False,'admitted':False})
result={'schema':'autoencoder-optimizer-performance/v1','runs':rows,'admitted':False,'scope':'Four synthetic numeric training spans, one repeated tuning row, existing mock embeddings. First fresh-worker evaluations are process-cold; target cache status is recorded separately. Single sequential measurements, not a repeated benchmark.'}
if len(rows)>1:
 before=next(x for x in rows if x['label']=='baseline');after=next(x for x in rows if x['label']=='optimized')
 result['baseline_to_optimized_wall_reduction_fraction']=1-after['wall_seconds']/before['wall_seconds']
if (BASE/'shared-targets/receipt.json').exists() and any(x['label']=='shared' for x in rows):
 prep=json.loads((BASE/'shared-targets/receipt.json').read_text())
 result['shared_preparation_receipt']=prep
output=BASE/'performance-summary.json';output.write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n')
print(json.dumps({'runs':[{k:v for k,v in row.items() if k in ['label','wall_seconds','qualified_count','first_bridge_seconds_range','sampled_peak_group_rss_bytes','dispatch_widths']} for row in rows],'output':str(output)}))
