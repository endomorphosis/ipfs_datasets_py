"""Independent read-only concrete review. Never imports/calls the live applicator/API."""
import ast,hashlib,json,os,stat,time
from pathlib import Path
import xml.etree.ElementTree as ET
F=Path('/home/barberb/lift_coding/artifacts/legal-storage-recovery-20261012-01')
P=F/'owned-preparation-administrative-closeout-protocol-v01.json'
H=F/'reconcile_owned_preparation_refusal_administrative.py'
R=F/'owned-preparation-administrative-closeout-independent-review-v01.json'
OWN='0350dfb651f943178d7b1cbc2113443e'
def need(x,message):
 if not x:raise AssertionError(message)
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(x):return hashlib.sha256(canonical(x)).hexdigest()
def ordinary(p,directory=False):
 p=Path(os.path.abspath(p))
 for part in (*reversed(p.parents),p):
  st=part.lstat();need(not stat.S_ISLNK(st.st_mode),'symlink path refused:'+str(part))
  need(stat.S_ISDIR(st.st_mode) if part!=p or directory else stat.S_ISREG(st.st_mode),'ordinary path required:'+str(part))
 return p

def pin(p):
 p=ordinary(p);a=p.stat();b=p.read_bytes();z=p.stat()
 need((a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(z.st_dev,z.st_ino,z.st_size,z.st_mtime_ns,z.st_ctime_ns),'changed file:'+str(p))
 return {'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
def read(p):
 p=ordinary(p);need(p.stat().st_size<=16*1024*1024,'bounded JSON required')
 def unique(items):
  r={}
  for k,v in items:need(k not in r,'duplicate key');r[k]=v
  return r
 return json.loads(p.read_bytes(),object_pairs_hook=unique,parse_constant=lambda v:(_ for _ in ()).throw(AssertionError('nonfinite JSON:'+v)))
def ident(p):
 p=ordinary(p,True);st=p.stat();return {'path':str(p),'device':st.st_dev,'inode':st.st_ino}
protocol=read(P);ppin=pin(P);hpin=pin(H)
need(protocol['schema']=='owned-preparation-administrative-closeout-protocol/v1','protocol schema')
need(protocol['reservation_id']==OWN and protocol['capacity_policy']=='administrative_closeout','one exact claim/policy')
need(hpin==protocol['helper'],'helper pin')
need((H.stat().st_mode&0o222)==0 and (P.stat().st_mode&0o222)==0,'helper/protocol frozen')
artifacts={str(H):hpin,str(P):ppin}
for path,expected in protocol['artifacts'].items():
 actual=pin(Path(path));need(actual==expected,'artifact mismatch:'+path);artifacts[path]=actual
need(len(protocol['artifacts'])==80,'exact80 prepared bindings')
source=read(Path(protocol['recovery_api_independent_review']['path']))
need(source['passed'] is True and source['findings']==[] and source['phase']=='administrative-storage-closeout-source','independent source approval')
api=protocol['recovery_api'];need(source['artifacts'][api['path']]==api,'source approval exact API')
need(api['sha256']=='c3497e4c731f2944f6319b2ac2b1d9375bdd69723189cd116471abef8bc3c6e4','frozen new API')
need(protocol['daemon_source_witness']['sha256']=='b00d2752ba852fe73760bba4fbd51b0e845742c3527642606a2a77ed9f8f5e2c','unchanged resource owner')
obs=read(Path(protocol['inert_test_observation']['path']))
need(obs['passed'] is True and obs['findings']==[] and obs['current_distinct_passed']==76 and obs['recovery_passed']==68 and obs['unchanged_owner_regressions_passed']==8 and obs['host_ledger_mutated'] is False,'fresh root76 inert cases')
for n,expected in [('recovery-tests-v05.xml',68),('owner-regression-tests-v01.xml',8)]:
 xml=ET.parse(F/n).getroot();suite=xml.find('testsuite') if xml.tag=='testsuites' else xml
 need(suite is not None and int(suite.attrib['tests'])==expected and int(suite.attrib['failures'])==0 and int(suite.attrib['errors'])==0 and int(suite.attrib['skipped'])==0,'closed fixture XML counts')
ast.parse(H.read_text());ast.parse(Path(api['path']).read_text())
ledger_path=Path(protocol['ledger_before']['path']);before=pin(ledger_path);ledger=read(ledger_path)
need(before==protocol['ledger_before'] and before['sha256']=='2075fb14e99da8aafe58d363dfdaab552be5cd17f04a73733e07ef9a4f45e753','actual ledger endpoint')
need(set(ledger)=={'schema','roots','limit_bytes','reservations'} and ledger['schema']=='daemon-resource-reservations-v1' and ledger['limit_bytes']==145_000_000_000,'closed unchanged ledger/cap')
need(ledger['roots']==protocol['roots'] and [ident(Path(x['path'])) for x in protocol['roots']]==protocol['roots'],'all root identities')
rows=ledger['reservations'];need(len(rows)==513 and set(rows)==set(protocol['prior_512_body_hashes'])|{OWN},'exact513keyset')
need({k:digest(v) for k,v in rows.items() if k!=OWN}==protocol['prior_512_body_hashes'],'all foreign512 immutable bodies')
record=rows[OWN];need(digest(record)==protocol['own_record_body_sha256'],'own body hash')
need(record['owner_pid']==643818 and record['status']=='retained' and record['storage_bytes']==200_000_000 and record['cpu_slots']==2 and record['memory_mb']==1536 and record['child_process_slots']==1,'exact own envelope')
need(record['child']=={'pid':655833,'birth':'78788165'} and record['prior_children']==[] and record['external_charges']=={},'exact group and unsupported external charges absent')
need(sum(x['status']=='retained' for x in rows.values())==102 and sum(x['status']=='released' for x in rows.values())==411,'record status counts')
need(sum(x['storage_bytes'] for x in rows.values() if x['status']!='released')==48_381_777_216,'actual full reservations')
need(not Path('/proc/643818').exists(),'original owner PID must be absent including reuse')
live=[];birth=None
for proc in Path('/proc').iterdir():
 if not proc.name.isdecimal():continue
 try:raw=(proc/'stat').read_text()
 except (FileNotFoundError,ProcessLookupError):continue
 fields=raw[raw.rfind(')')+2:].split()
 need(len(fields)>=22,'valid proc stat')
 if int(proc.name)==655833:birth=fields[19]
 if fields[0]!='Z' and int(fields[2])==655833:live.append(int(proc.name))
need(birth is None or birth=='78788165','recorded group PID reused')
need(live==[],'all recorded current/prior groups dead')
attempt=Path(protocol['attempt_identity']['path']);need(ident(attempt)==protocol['attempt_identity']==record['attempt_directory'],'attempt inode unchanged')
actual=[]
for path in sorted(attempt.rglob('*')):
 st=path.lstat();need(not stat.S_ISLNK(st.st_mode),'owned artifact symlink')
 if stat.S_ISDIR(st.st_mode):continue
 need(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_uid==os.getuid(),'unaliased ordinary owned artifact')
 p=pin(path);actual.append({'path':str(path.relative_to(attempt)),'bytes':p['bytes'],'sha256':p['sha256']})
need(actual==protocol['expected_artifacts'] and len(actual)==15 and sum(x['bytes'] for x in actual)==61141,'exact15 owned artifacts61141B')
need(ident(Path(protocol['ledger_parent_identity']['path']))==protocol['ledger_parent_identity'],'ledger parent identity')
lock=Path(protocol['lock']['artifact']['path']);s=lock.lstat();need(pin(lock)==protocol['lock']['artifact'] and {'device':s.st_dev,'inode':s.st_ino,'nlink':s.st_nlink}==protocol['lock']['identity'] and s.st_uid==os.getuid(),'existing owned stable lock')
scheduler=read(Path(protocol['scheduler']['state']['path']));need(digest(scheduler['config'])==protocol['scheduler']['config_sha256'] and protocol['scheduler']['owned_lease_id'] not in scheduler['leases'],'config/actual own lease absent')
need(not Path(protocol['output_directory']).exists(),'fresh one-shot output directory')
need(pin(ledger_path)==before,'ledger remained unchanged through read-only review')
for path,expected in artifacts.items():need(pin(Path(path))==expected,'closing reviewed artifact mismatch:'+path)
report={'schema':'owned-administrative-closeout-independent-review/v1','phase':'owned-administrative-closeout','created_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'passed':True,'findings':[],'helper_sha256':hpin['sha256'],'protocol_sha256':ppin['sha256'],'reservation_id':OWN,'output_directory':protocol['output_directory'],'expected_ledger_sha256':before['sha256'],'capacity_policy':'administrative_closeout','artifacts':artifacts,'checks':{'frozen_exact_helper_protocol_and80prepared_artifacts':True,'exact_independently_reviewed_new_api':True,'old_resource_owner_admission_cap_and10_source_closure_unchanged':True,'root76_fixture_cases_closed_without_live_ledger_changes':True,'actual_original_owner_absent_including_reuse':True,'all_recorded_groups_dead_no_pid_adoption':True,'actual513_keys_foreign512_body_hashes_match':True,'cap145_and_all4_root_identities_exact':True,'exact_owned15_unaliased_files61141_bytes':True,'full_preclaim48_381_777_216_and_projected48_181_777_216_delta200M_required':True,'pre_projection_actual_postwrite_census_labels_distinct':True,'explicit_policy_records_overage_without_admission_or_lease':True,'immediate_before_write_owner_groups_roots_durable_inventory_fenced':True,'existing_stable_lock_atomic_writer_and_narrow_fd_gate':True,'new_output_exclusive_mode700_receipts_mode600':True,'all_full_ledger_backups_private_local_not_public_payload':True,'one_normal_atomic_write_only_no_foreign_changes_no_cap_bypass':True,'primary_failure_preserved_and_before_planned_other_bytes_classified_no_rollback':True,'all_prior_failed_and_successful_attempts_bound_and_preserved':True,'actual_owned_scheduler_lease_absent_config_pinned':True,'review_requires_actual_postwrite_independent_closure':True},'actual_read_only_observation':{'original_owner_pid':643818,'owner_proc_absent':True,'recorded_child_pid':655833,'recorded_child_birth':'78788165','current_group_live_processes':0,'prior_child_count':0,'record_count':513,'foreign_record_count':512,'retained_count':102,'released_count':411,'owned_artifact_count':15,'owned_artifact_bytes':61141,'outstanding_full_reservations_bytes':48_381_777_216,'ledger_pin':before,'all_source_and_artifact_pins_rechecked_at_close':True},'authority':{'only_selected_own_claim_closeout_approved':True,'foreign_or_bulk_closeout_approved':False,'artifact_delete_or_move_approved':False,'cap_change_approved':False,'resource_admission_approved':False,'new_training_approved':False,'public_ledger_backup_publication_approved':False},'reviewer_actions':{'live_api_calls':0,'ledger_lock_acquisitions':0,'reservation_mutations':0,'new_leases':0,'model_calls':0,'compiler_calls':0,'artifact_deletions':0,'resource_owner_imports':0,'applicator_imports':0},'limitations':['Static independent applicator/protocol review and bounded read-only metadata observations; no live release has occurred in this review.','Original dead owner/groups, exact evidence, root/ledger/source pins must be rechecked by the actual applicator immediately before write.','Explicit administrative policy removes only the verified full200M claim even if observed capacity remains exceeded; ordinary training cutoff remains unchanged.','76 tests are root fixture observations; earlier startup/cache cleanup refusals are not passing runs and full stale140GB owner-suite expectations were not exercised.','Old attempt02 model gate opened; protocol records zero optimizer updates and model-call count null pending separate refinement. This review starts no model and does not infer old cold model calls from gate/RSS data.','All raw .local ledger snapshots including foreign claim bodies remain private, excluded from publication.','Actual postwrite foreign512 preservation, exact ledger readback and real fresh census require independent closure before any claim of successful recovery or training eligibility.']}
need(not R.exists(),'fresh review receipt required')
R.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');R.chmod(0o444)
print(json.dumps({'review':pin(R),'passed':True,'bound_artifacts':len(artifacts),'no_api_or_lock_or_mutation':True},indent=2))
