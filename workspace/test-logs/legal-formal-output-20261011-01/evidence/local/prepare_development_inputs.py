"""Export three already-exposed authored sources and explicit DEVELOPMENT cue declarations."""
from pathlib import Path
import hashlib,json,os
F=Path(__file__).resolve().parent;H=F.parent/'legal-structured-training-20261011-01';R=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01/structured-probability-20261011-01/results')
def rawparse(raw):
 def pairs(items):
  d={}
  for k,v in items:
   if k in d:raise ValueError('duplicate key')
   d[k]=v
  return d
 return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=lambda v:(_ for _ in ()).throw(ValueError(v)))
def pin(p):
 assert p.is_file() and not p.is_symlink() and p.resolve()==p
 raw=p.read_bytes();return {'path':str(p),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def write(p,v):
 if p.exists():
  assert p.read_bytes()==(json.dumps(v,indent=2,sort_keys=True,allow_nan=False,ensure_ascii=False)+'\n').encode('utf-8')
  return
 with p.open('x') as s:json.dump(v,s,indent=2,sort_keys=True,allow_nan=False,ensure_ascii=False);s.write('\n');s.flush();os.fsync(s.fileno())
report_path=R/'source_only-1729-ce0-tuning-greedy.json';report=rawparse(report_path.read_bytes());export_path=H/'authored-train-tune-only.json';export=rawparse(export_path.read_bytes())
assert report['schema']=='objective-resumed-source-span-inference/v1' and len(report['rows'])==96 and report['target_access'] is False and report['optimizer_updates']==0
source_rows={r['id']:r for r in export['populations']['tuning']}
expected=[('native-tuning-begonia-t0-q0-o','Begonia Authority shall inspect the certified begonia public register.','O',18,23),('native-tuning-begonia-t0-q0-p','Begonia Authority may inspect the certified begonia public register.','P',18,21),('native-tuning-begonia-t0-q0-f','Begonia Authority shall not inspect the certified begonia public register.','F',18,27)]
rows=[];declarations=[]
for pos,(identity,text,modality,start,end) in enumerate(expected):
 row=source_rows[identity];assert row['source_text']==text
 saved=report['rows'][pos];assert saved['id']==identity and saved['decoder_row']['status']=='decoded' and saved['source_sha256']==hashlib.sha256(text.encode()).hexdigest()
 assert saved['decoder_row']['canonical_ir']['rules'][0]['modality']==modality
 rows.append({'id':identity,'source_text':text,'source_sha256':saved['source_sha256']})
 declarations.append({'id':identity,'occurrence_id':'development-'+identity,'start_char':0,'end_char':len(text),'modality_span':{'start_char':start,'end_char':end,'source_text':text[start:end],'canonical_value':modality},'scope':'explicit DEVELOPMENT caller declaration, not reviewed legal meaning'})
write(F/'authored-development-source-only.json',{'schema':'authored-development-source-only/v1','role':'Previously exposed synthetic engineering typecheck; not statute, independent holdout or semantic gold','parent_authored_export':pin(export_path),'parent_saved_inference_report':pin(report_path),'checkpoint_canonical_sha256':report['checkpoint_sha256'],'full_report_rows_preserved':96,'selected_original_positions':[0,1,2],'rows':rows,'target_labels_exported':False,'latent_vectors_exported':False,'new_model_calls':0,'semantic_gold':False})
write(F/'authored-development-cue-declarations.json',{'schema':'explicit-development-cue-declarations/v1','role':'Caller-supplied interpretation hypothesis only','rows':declarations,'reviewer_authentication':False,'source_semantics_verified':False,'training_or_evaluation_admission':False})
print('Exported3 O/P/F sources only; full96 saved inference report remains unchanged')
