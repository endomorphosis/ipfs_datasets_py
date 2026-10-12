"""Independent read-only saved/current closeout audit, no live owner/API import."""
from pathlib import Path
import hashlib,json,os,stat,time
F=Path('/home/barberb/lift_coding/artifacts/legal-storage-recovery-20261012-01');O=F/'owned-preparation-administrative-closeout-attempt-01';OWN='0350dfb651f943178d7b1cbc2113443e'
def need(x,msg):
 if not x:raise AssertionError(msg)
def raw(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(x):return hashlib.sha256(raw(x)).hexdigest()
def pin(p):
 p=Path(p).absolute()
 for x in (*reversed(p.parents),p):
  s=x.lstat();need(not stat.S_ISLNK(s.st_mode),'symlink path')
  need(stat.S_ISDIR(s.st_mode) if x!=p else stat.S_ISREG(s.st_mode),'ordinary artifact')
 before=p.stat();b=p.read_bytes();after=p.stat()
 need((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),'artifact changed while read')
 return {'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
def read(p):
 need(Path(p).stat().st_size<16*1024*1024,'bounded JSON')
 def unique(items):
  d={}
  for k,v in items:need(k not in d,'duplicate key');d[k]=v
  return d
 return json.loads(Path(p).read_bytes(),object_pairs_hook=unique,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite:'+v)))
def identity(p):
 p=Path(p);s=p.lstat();need(stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode),'ordinary directory');return {'path':str(p),'device':s.st_dev,'inode':s.st_ino}
def census(x,outstanding):
 need(x['additional_requested_bytes']==0 and x['limit_bytes']==145_000_000_000,'unchanged census scope/cap')
 need(x['observed_apparent_bytes']==x['inventory']['apparent_bytes'] and x['outstanding_full_reservations_bytes']==outstanding and x['charged_bytes']==x['observed_apparent_bytes']+outstanding,'exact census formula')
 need(x['over_limit_bytes']==max(0,x['charged_bytes']-145_000_000_000) and x['filesystem_free_shortfall_bytes']==max(0,outstanding-x['minimum_filesystem_free_bytes']) and x['capacity_satisfied']==(x['over_limit_bytes']==0 and x['filesystem_free_shortfall_bytes']==0),'honest capacity flags')
protocol=read(F/'owned-preparation-administrative-closeout-protocol-v01.json');review=read(F/'owned-preparation-administrative-closeout-independent-review-v02.json');complete=read(O/'completion.json');post=read(O/'actual-postwrite-census.json')
need(complete['complete'] is True and complete['schema']=='owned-preparation-administrative-closeout-result/v1' and complete['reservation_id']==OWN,'completed exact claim')
need(complete['helper']==protocol['helper'] and complete['protocol']==pin(F/'owned-preparation-administrative-closeout-protocol-v01.json') and complete['independent_review']==pin(F/'owned-preparation-administrative-closeout-independent-review-v02.json'),'actual concrete protocol/review source joins')
need(review['passed'] is True and review['findings']==[] and review['phase']=='owned-administrative-closeout','approved concrete review')
need(complete['before']==protocol['ledger_before'] and complete['before_local_backup']==pin(O/'ledger-before.local.json'),'exact private original backup')
old=read(O/'ledger-before.local.json');planned=read(O/'ledger-after-planned.local.json');after=read(O/'ledger-after.local.json');live_path=Path(complete['after']['path']);live=read(live_path);live_pin=pin(live_path)
need(complete['after']==live_pin and complete['planned_after_local_backup']==pin(O/'ledger-after-planned.local.json') and complete['after_local_backup']==pin(O/'ledger-after.local.json'),'saved/current raw joins')
need(complete['planned_after_local_backup']['sha256']==complete['after_local_backup']['sha256']==complete['after']['sha256']=='1f93e0ca70ea6199f16d58834e30d60d127f9891e380454e470df352720bb824','planned actual current rawbyte equality')
need(planned==after==live,'parsed after/current equality')
need(pin(O/'ledger-before.local.json')['sha256']=='2075fb14e99da8aafe58d363dfdaab552be5cd17f04a73733e07ef9a4f45e753','original ledger endpoint')
for value in (old,planned,after,live):
 need(value['schema']=='daemon-resource-reservations-v1' and value['limit_bytes']==145_000_000_000 and value['roots']==protocol['roots'],'schema cap roots preserved')
 need(len(value['reservations'])==513 and set(value['reservations'])==set(old['reservations']),'all513 exact keys preserved')
 need({k:digest(v) for k,v in value['reservations'].items() if k!=OWN}==protocol['prior_512_body_hashes'],'all512 foreignbodies preserved')
need([identity(x['path']) for x in protocol['roots']]==protocol['roots'],'actual roots still exact')
old_record=old['reservations'][OWN];new=live['reservations'][OWN]
need(digest(old_record)==protocol['own_record_body_sha256'] and old_record['status']=='retained' and new['status']=='released' and new['artifacts_durable_asserted'] is True,'only exact selected retained claim closed')
allowed={'status','artifacts_durable_asserted','released_at','final_accounting','final_attempt_bytes','final_external_charged_bytes','final_total_charged_bytes','attempt_exceeded_reservation','explicit_reconciliation'}
changed={k for k in set(old_record)|set(new) if old_record.get(k)!=new.get(k)};need(changed<=allowed,'unexpected own record changes')
need(new['owner_pid']==old_record['owner_pid']==643818 and new['child']==old_record['child']=={'pid':655833,'birth':'78788165'} and new['prior_children']==[] and new['storage_bytes']==200_000_000 and new['external_charges']=={},'owner not adopted/cpu budget/child/history retained')
need(new['final_attempt_bytes']==new['final_total_charged_bytes']==61141 and new['final_external_charged_bytes']==0 and new['attempt_exceeded_reservation'] is False,'owned failed artifacts bounded')
event=new['explicit_reconciliation'];need(event['schema']=='explicit-retained-reservation-reconciliation/v2' and event['capacity_policy']=='administrative_closeout' and event['reservation_id']==OWN and event['previous_record_sha256']==protocol['own_record_body_sha256'] and event['artifacts']==protocol['expected_artifacts'],'explicit new policy event exact')
need(event['final_accounting_is_prewrite_projection'] is True and event['actual_postwrite_census_required'] is True and event['fresh_global_inventory_count']==2 and event['outputs_deleted'] is False and event['automatic_expiry'] is False and event['admitted'] is False and event['cap_changed'] is False and event['new_reservation_created'] is False and event['new_resource_lease_acquired'] is False,'v2 noadmission/projection fields')
need(event['other_reservations_sha256']==digest({k:v for k,v in old['reservations'].items() if k!=OWN}),'foreign aggregate joined')
census(event['full_claim_accounting'],48_381_777_216);census(event['final_accounting'],48_181_777_216)
need(event['full_claim_accounting']==complete['full_claim_accounting'] and event['final_accounting']==complete['final_accounting']==new['final_accounting'],'pre/projection equality')
need(event['full_claim_accounting']['outstanding_full_reservations_bytes']-event['final_accounting']['outstanding_full_reservations_bytes']==200_000_000,'only200M full reservation released')
need(post['actual_postwrite_observation'] is True and post['prewrite_projection'] is False and post['ledger']==live_pin and post['own_claim_status']=='released' and post['training_admitted'] is False and post['new_reservations']==0 and post['new_resource_leases']==0,'actualpostwrite receipt separately bound')
need(complete['actual_postwrite_census_receipt']==pin(O/'actual-postwrite-census.json') and complete['actual_postwrite_accounting']==post['actual_accounting'],'real actual postwrite receipt join')
census(post['actual_accounting'],48_181_777_216)
need(sum(x['status']=='retained' for x in live['reservations'].values())==101 and sum(x['status']=='released' for x in live['reservations'].values())==412 and sum(x['storage_bytes'] for x in live['reservations'].values() if x['status']!='released')==48_181_777_216,'after inventory101retained412released')
attempt=Path(protocol['attempt_identity']['path']);need(identity(attempt)==protocol['attempt_identity'],'actual failedattempt identity')
files=[]
for p in sorted(attempt.rglob('*')):
 s=p.lstat();need(not stat.S_ISLNK(s.st_mode),'failedartifact symlink')
 if stat.S_ISDIR(s.st_mode):continue
 need(stat.S_ISREG(s.st_mode) and s.st_nlink==1,'failedartifact unaliased ordinary')
 v=pin(p);files.append({'path':str(p.relative_to(attempt)),'bytes':v['bytes'],'sha256':v['sha256']})
need(files==protocol['expected_artifacts'] and len(files)==15 and sum(x['bytes'] for x in files)==61141,'actual owned15files immutable')
need(not Path('/proc/643818').exists(),'original owner absent')
live_group=[]
for p in Path('/proc').iterdir():
 if not p.name.isdecimal():continue
 try:val=(p/'stat').read_text()
 except (FileNotFoundError,ProcessLookupError):continue
 fields=val[val.rfind(')')+2:].split()
 if int(p.name)==655833:need(fields[19]=='78788165','child PID reused')
 if fields[0]!='Z' and int(fields[2])==655833:live_group.append(int(p.name))
need(live_group==[],'group still dead')
scheduler=read(protocol['scheduler']['state']['path']);need(digest(scheduler['config'])==protocol['scheduler']['config_sha256'] and protocol['scheduler']['owned_lease_id'] not in scheduler['leases'],'actual ownlease absent/schedulerconfig unchanged')
need(identity(protocol['ledger_parent_identity']['path'])==protocol['ledger_parent_identity'],'ledgerparent identity')
lock=Path(protocol['lock']['artifact']['path']);s=lock.lstat();need(pin(lock)==protocol['lock']['artifact'] and {'device':s.st_dev,'inode':s.st_ino,'nlink':s.st_nlink}==protocol['lock']['identity'],'lock metadata unchanged')
need((O.stat().st_mode&0o777)==0o700,'private output directory mode')
private={}
for name in ['ledger-before.local.json','ledger-after-planned.local.json','ledger-after.local.json']:
 p=O/name;need((p.stat().st_mode&0o777)==0o600 and p.stat().st_nlink==1,'private backup mode and link count');private[name]=pin(p)
artifacts={str(O/'completion.json'):pin(O/'completion.json'),str(O/'actual-postwrite-census.json'):pin(O/'actual-postwrite-census.json'),str(O/'attempt-started.json'):pin(O/'attempt-started.json'),str(O/'planned-mutation.json'):pin(O/'planned-mutation.json'),str(F/'administrative-closeout-execution-v01.log'):pin(F/'administrative-closeout-execution-v01.log'),str(F/'owned-preparation-administrative-closeout-protocol-v01.json'):pin(F/'owned-preparation-administrative-closeout-protocol-v01.json'),str(F/'owned-preparation-administrative-closeout-independent-review-v02.json'):pin(F/'owned-preparation-administrative-closeout-independent-review-v02.json')}
for p,expected in protocol['artifacts'].items():
 if p==str(live_path):continue
 need(pin(p)==expected,'source/evidence changed after closeout:'+p);artifacts[p]=expected
need(pin(live_path)==live_pin,'closing actual ledger endpoint unchanged')
pre=event['full_claim_accounting'];projection=event['final_accounting'];actual=post['actual_accounting'];headroom=145_000_000_000-actual['charged_bytes']
out={'schema':'owned-administrative-closeout-postclosure-independent-review/v1','phase':'actual-owned-administrative-closeout-closure','created_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'passed':True,'findings':[],'reservation_id':OWN,'artifacts':artifacts,'private_full_ledger_backup_metadata_only':private,'actual_current_ledger':live_pin,'checks':{'raw_planned_actual_current_after_agree':True,'exact_old_ledger_saved_before':True,'all513_records_preserved_only_selected_released':True,'all512_foreign_body_hashes_identical':True,'old511_plus_prior_c6_released_claim_preserved':True,'selected_original_owner_not_adopted':True,'all15_failed_artifacts61141B_unchanged':True,'cap145_roots_lock_config_unchanged':True,'actual_ownlease_absent_owner_and_group_dead':True,'private_backups_mode600_directory700_excluded_from_publication':True,'pre_full200M_claim_and_fresh_projection_honest':True,'real_separate_actualpostwrite_census_receipt_matches_completion':True,'actual_above_cap_pre_and_projection_observations_recorded_without_new_admission':True,'exact_fullreservation_delta200M_only':True,'no_models_leases_deletions_new_work_observed_in_closeout':True,'source_review_api_and_applicator_closure_unchanged':True},'actual_ledger_summary':{'total_records':513,'retained':101,'released':412,'active_or_reserved':0,'outstanding_full_reservations_bytes':48_181_777_216,'selected_released_bytes':200_000_000,'selected_artifact_bytes':61141},'storage_observations':{'full_preclaim':pre,'released_record_prewrite_projection':projection,'actual_postwrite':actual,'actual_postwrite_headroom_bytes':headroom,'headroom_after_hypothetical_new200M_request_bytes':headroom-200_000_000,'projection_to_actual_observed_bytes_delta':actual['observed_apparent_bytes']-projection['observed_apparent_bytes'],'unrelated_global_observed_change_is_not_our_reclamation':True,'current_capacity_snapshot_is_not_future_training_admission':True},'reviewer_actions':{'live_api_calls':0,'ledger_lock_acquisitions':0,'claim_mutations':0,'resource_leases':0,'model_calls':0,'compiler_calls':0,'artifact_deletions':0},'limitations':['Actual helper full preclaim and fresh projection were both above cap; independent current raw readback proves closeout succeeded while preserving cap/admission owner.','The saved actual postwrite census is a real owner observation, separate from the prewrite projection. It is not a persistent or future headroom guarantee.','Observed global pathname bytes dropped by5.31GB between projection and actual observation; only200M fullclaim delta belongs to this cleanup.','Current ledger/source/artifact equality are bounded endpoint checks, not continuous custody of foreign working files.','No foreign claim release or deletion approved. Existing fullclaim policy and hardlink-path accounting remain unchanged.','Our raw ledger snapshots contain foreign claim bodies and must remain local private; metadata hashes can be published.','No model training or proof/compiler qualification is inferred from administrative recovery.']}
p=F/'owned-preparation-administrative-closeout-postclosure-independent-review-v01.json';need(not p.exists(),'fresh postclosure receipt');p.write_text(json.dumps(out,sort_keys=True,indent=2)+'\n');p.chmod(0o444)
print(json.dumps({'review':pin(p),'passed':True,'artifacts':len(artifacts),'current':live_pin,'headroom':headroom,'actual_pre_overcap':pre['over_limit_bytes'],'projection_overcap':projection['over_limit_bytes']},indent=2))
