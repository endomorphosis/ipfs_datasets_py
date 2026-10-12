"""Independent concrete operation review; opaque hashes only, no live imports/API/locks."""
from pathlib import Path
import ast,hashlib,json,os,stat,time
N=Path('/home/barberb/lift_coding/artifacts/legal-storage-closeout-20261012-02');P=N/'generated-field-4gb-administrative-closeout-protocol-v01.json';OWN='474ee6b5ae784516ae1dab7ca38c8cc6'
def need(x,m):
 if not x:raise AssertionError(m)
def raw(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(x):return hashlib.sha256(raw(x)).hexdigest()
def ordinary(p,directory=False):
 p=Path(p).absolute()
 for x in (*reversed(p.parents),p):
  s=x.lstat();need(not stat.S_ISLNK(s.st_mode),'symlink refused');need(stat.S_ISDIR(s.st_mode) if x!=p or directory else stat.S_ISREG(s.st_mode),'ordinary path required')
 return p
stat_key=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink)
def pin(p):
 p=ordinary(p);before=p.lstat();h=hashlib.sha256();count=0
 with p.open('rb') as f:
  opened=os.fstat(f.fileno());need(stat_key(opened)==stat_key(before),'opened identity differs')
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block);count+=len(block)
  after=os.fstat(f.fileno())
 current=p.lstat();need(stat_key(opened)==stat_key(after)==stat_key(current),'file changed during opaque hash')
 return {'path':str(p),'bytes':count,'sha256':h.hexdigest()},stat_key(current)
def read(p):
 p=ordinary(p);need(p.stat().st_size<=16*1024*1024,'bounded metadata JSON')
 def unique(items):
  d={}
  for k,v in items:need(k not in d,'duplicate metadata key');d[k]=v
  return d
 return json.loads(p.read_bytes(),object_pairs_hook=unique,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite metadata:'+v)))
def ident(p):
 p=ordinary(p,True);s=p.stat();return {'path':str(p),'device':s.st_dev,'inode':s.st_ino}
protocol=read(P);pp,ps=pin(P);H=Path(protocol['helper']['path']);hp,hs=pin(H)
need(pp['sha256']=='f3c79aeb53be19ad37e72074151685ab0fb1893f25ee842aca82d6e415e1a4b4' and hp['sha256']=='30edc6fd4e466464892aabdd4d895ff3d15403bc17ee501ee418986b478e8ed0','corrected frozen helper/protocol')
need(hp==protocol['helper'] and protocol['schema']=='generated-field-4gb-administrative-closeout-protocol/v1' and protocol['phase']=='selected-claim-administrative-closeout' and protocol['reservation_id']==OWN and protocol['capacity_policy']=='administrative_closeout','exact selected protocol')
need(H.stat().st_mode&0o222==0 and P.stat().st_mode&0o222==0,'frozen helper/protocol')
artifacts={str(P):pp,str(H):hp};statpins={str(P):ps,str(H):hs}
need(len(protocol['artifacts'])==165,'exact165 prepared source/metadata/opaque artifact bindings')
for path,want in protocol['artifacts'].items():
 actual,s=pin(path);need(actual==want,'prepared pin mismatch:'+path);artifacts[path]=actual;statpins[path]=s
source=read(protocol['applicator_source_independent_review']['path']);need(source['passed'] is True and source['findings']==[] and source['phase']=='generated-field-4gb-applicator-source' and source['artifacts'][str(H)]['sha256']==hp['sha256'] and source['artifacts'][str(H)]['bytes']==hp['bytes'],'corrected independent helper-source approval')
api=protocol['recovery_api'];apireview=read(protocol['recovery_api_independent_review']['path']);need(apireview['passed'] is True and apireview['findings']==[] and apireview['phase']=='administrative-storage-closeout-source' and apireview['artifacts'][api['path']]==api,'exact independently reviewed c349 API')
need(api['sha256']=='c3497e4c731f2944f6319b2ac2b1d9375bdd69723189cd116471abef8bc3c6e4' and protocol['daemon_source_witness']['sha256']=='b00d2752ba852fe73760bba4fbd51b0e845742c3527642606a2a77ed9f8f5e2c','unchanged current145GB owner/API')
ast.parse(H.read_text());need(protocol['historical_guardian_140GB_import_or_execution_permitted'] is False and protocol['model_state_JSON_parsing_or_replay_permitted'] is False and protocol['new_admissions_leases_or_claims_permitted'] is False and protocol['source_or_candidate_payload_changes_permitted'] is False and protocol['scope_extends_to_generic_cleanup'] is False and protocol['other_512_claim_changes_permitted'] is False,'strict selected operation scope')
L=Path(protocol['ledger_before']['path']);lp,ls=pin(L);ledger=read(L);need(lp==protocol['ledger_before'] and lp['sha256']=='1f93e0ca70ea6199f16d58834e30d60d127f9891e380454e470df352720bb824','actual current exact1f93 ledger')
need(set(ledger)=={'schema','roots','limit_bytes','reservations'} and ledger['schema']=='daemon-resource-reservations-v1' and ledger['limit_bytes']==145_000_000_000 and ledger['roots']==protocol['roots'],'unchanged closed145GB scope')
rows=ledger['reservations'];need(len(rows)==513 and set(rows)==set(protocol['prior_512_body_hashes'])|{OWN},'exact513keyset');need({k:digest(v) for k,v in rows.items() if k!=OWN}==protocol['prior_512_body_hashes'],'all512 other bodies exact')
r=rows[OWN];need(digest(r)==protocol['own_record_body_sha256']=='4ca144ebfb780e5aa9e502fd7459f620052b00b20d00f8351aedaaa3829ef687','selected exact4ca body');need(r['status']=='retained' and r['storage_bytes']==4_000_000_000 and r['owner_pid']==1421156 and r['memory_mb']==4096 and r['cpu_slots']==1 and r['child_process_slots']==1 and r['child']=={'pid':1434010,'birth':'7454855'} and r['prior_children']==[] and r['external_charges']=={},'exact historical envelope and no external obligations')
need(sum(x['status']=='retained' for x in rows.values())==101 and sum(x['status']=='released' for x in rows.values())==412 and not any(x['status'] in {'active','reserved'} for x in rows.values()),'exact current status aggregate');need(sum(x['storage_bytes'] for x in rows.values() if x['status']!='released')==48_181_777_216,'full first claim inventory')
for pid,expected in protocol['previous_released_record_body_hashes'].items():need(rows[pid]['status']=='released' and digest(rows[pid])==expected,'prior200MB closeout preserved')
need([ident(x['path']) for x in protocol['roots']]==protocol['roots'],'actual four roots unchanged');A=Path(protocol['attempt_identity']['path']);need(ident(A)==protocol['attempt_identity']==r['attempt_directory'],'exact retained attempt identity')
paths=[A,*sorted(A.rglob('*'))];need(len(paths)==125,'exact109files+16dirs');dirs=[];files=[]
for p in paths:
 s=p.lstat();need(not stat.S_ISLNK(s.st_mode),'candidate symlink')
 if stat.S_ISDIR(s.st_mode):dirs.append({'path':str(p.relative_to(A)),'device':s.st_dev,'inode':s.st_ino});continue
 need(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_uid==os.getuid(),'candidate unaliased ordinary file');v=artifacts.get(str(p));need(v is not None,'all109 raw file hashes included in protocol');need(stat_key(s)==statpins[str(p)],'candidate changed after opaque hash');files.append({'path':str(p.relative_to(A)),'bytes':v['bytes'],'sha256':v['sha256']})
need(dirs==protocol['candidate_directory_identities'] and len(dirs)==16 and files==protocol['expected_artifacts'] and len(files)==109 and sum(x['bytes'] for x in files)==249_979_161,'all109 files/16directory identities and249979161B exact')
need(len(protocol['candidate_sibling_pins'])==len(protocol['candidate_sibling_identities'])==8,'eight sibling fences')
for name,v in protocol['candidate_sibling_pins'].items():
 p=ordinary(v['path']);s=p.lstat();need({'device':s.st_dev,'inode':s.st_ino,'nlink':s.st_nlink,'bytes':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns}==protocol['candidate_sibling_identities'][name] and s.st_nlink==1 and artifacts[str(p)]==v,'sibling bytes/identity exact')
need(not Path('/proc/1421156').exists(),'original owner must be absent including PID reuse');live=[];birth=None
for p in Path('/proc').iterdir():
 if not p.name.isdecimal():continue
 try:body=(p/'stat').read_text()
 except (FileNotFoundError,ProcessLookupError):continue
 f=body[body.rfind(')')+2:].split();need(len(f)>=22,'valid process metadata')
 if int(p.name)==1434010:birth=f[19]
 if f[0]!='Z' and int(f[2])==1434010:live.append(int(p.name))
need(birth is None or birth=='7454855','recorded leader PID reused');need(live==[],'all current/prior groups dead')
scheduler=read(protocol['scheduler']['state']['path']);need(digest(scheduler['config'])==protocol['scheduler']['config_sha256'] and protocol['scheduler']['owned_lease_id'] not in scheduler['leases'],'actual historical lease absent/config exact')
need(ident(protocol['ledger_parent_identity']['path'])==protocol['ledger_parent_identity'],'ledger parent identity');lock=Path(protocol['lock']['artifact']['path']);s=lock.lstat();need(artifacts[str(lock)]==protocol['lock']['artifact'] and {'device':s.st_dev,'inode':s.st_ino,'nlink':s.st_nlink}==protocol['lock']['identity'] and s.st_uid==os.getuid(),'existing stable lock')
need(not Path(protocol['output_directory']).exists(),'fresh exclusive output directory');need(protocol['full_pre_outstanding_claims_bytes']==48_181_777_216 and protocol['prospective_post_outstanding_claims_bytes']==44_181_777_216 and protocol['own_claim_bytes']==4_000_000_000,'exact full4GB first/prospective discount')
# Closing file-metadata fences avoid a second unrelated global census or JSON parsing of models.
for p,s in statpins.items():need(stat_key(Path(p).lstat())==s,'reviewed artifact metadata changed at close:'+p)
need(pin(L)[0]==lp,'ledger raw endpoint unchanged through review')
preflight=N/'generated-field-4gb-preflight-v01.log';pf,pfs=pin(preflight);need(pf['sha256']=='128a66c42c371e3d39e55ba8d0a8052e71cfc58d292c2ca0bf48574e1ad97572','root read-only preflight exact');artifacts[str(preflight)]=pf
report={'schema':'generated-field-selected-4gb-operation-independent-review/v1','phase':'selected-claim-administrative-closeout','observed_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'passed':True,'findings':[],'helper_sha256':hp['sha256'],'protocol_sha256':pp['sha256'],'reservation_id':OWN,'output_directory':protocol['output_directory'],'expected_ledger_sha256':lp['sha256'],'capacity_policy':'administrative_closeout','artifacts':artifacts,'actual_prerequisites':{'ledger':lp,'selected_retained_body_sha256':protocol['own_record_body_sha256'],'record_count':513,'retained_count':101,'released_count':412,'other_record_bodies_exact':512,'original_owner_pid':1421156,'actual_original_owner_absent':True,'child_pid':1434010,'expected_child_birth':'7454855','actual_current_group_live_non_zombies':0,'prior_child_count':0,'attempt_identity':protocol['attempt_identity'],'file_count':109,'file_bytes':249_979_161,'directory_count_including_root':16,'unchanged_sibling_count':8,'all_candidate_hashes_opaque_not_JSON_parsed':True,'current_full_claim_bytes':48_181_777_216,'prospective_full_claim_bytes':44_181_777_216,'prospective_values_not_actual_result':True,'root_lease_absent':True},'checks':{'corrected30ed_helper_source_approval58e1_exact':True,'current_b00_145GB_owner_and_c349_API_approval_exact':True,'165preparedpins_and_all109_opaque_hashes_match':True,'actual513keyset_other512bodies_unchanged':True,'old510_nonselected_historical_bodies_and_prior_c6_0350_releases_preserved':True,'exact109_unaliased_files16dirs8siblings_preserved':True,'dead_owner_and_allgroups_no_PID_adoption':True,'actual4roots_lock_parent_config_and_historical_lease_absence_exact':True,'full4GB_still_charged_first_census_and_new_prospective_postscan_required':True,'actual_postwrite_census_separate_required':True,'only_selected_bookkeeping_fields_may_change':True,'final_source_directory_sibling_root_ledger_lock_fences_repeat_after249MB_hash':True,'existing_owner_lock_single_atomic_writer_narrow_descriptor_gate':True,'private_before_planned_actual_and_uncertainty_ledgers_local_only':True,'no_automatic_expiry_retry_rollback_or_generic_cleanup':True,'old140GB_guardian_never_imported_and_no_model_state_parse':True},'operation_authority':{'only_exact_selected4GB_closeout_approved':True,'other_claim_mutation_approved':False,'output_or_weight_mutation_or_delete_approved':False,'cap_schema_roots_config_change_approved':False,'lease_admission_newclaim_training_or_HF_approved':False,'private_ledger_publication_approved':False},'reviewer_actions':{'applicator_or_resource_imports':0,'live_API_calls':0,'ledger_locks':0,'claim_mutations':0,'model_state_JSON_parses':0,'model_calls':0,'compiler_calls':0,'Git_or_HF_calls':0,'global_censuses':0},'limits':['Concrete approval binds current immutable helper/protocol, exact selected claim and bounded fresh read-only prerequisites. Root alone may apply; no release occurred in this review.','Actual applicator must hash/fsync109 regular files and16 directories, recheck owner/groups and allfences before its one existing atomic write. Hash consistency and prior read-only preparation durability are prerequisites, not a claim this reviewer invoked live fsync/API.','Full4GB reservation remains charged in first fresh owner-compatible scan. Projected postscan and actual postwrite observations must be labeled separately even if cap remains exceeded.','All109 output/weight files remain in place; no modelstate parsed/replayed, new training, final18fit comparison, HF decoder archive or legal/proof qualification inferred.','All512 other claim bodies, including previousc6/0350 releases, remain exact. The selected old511 member will intentionally change, so only old510 nonselected historical bodies can be described as unchanged afterapply.','Private raw ledger snapshots contain foreign bodies and must remain local; this receipt publishes only hashes/aggregates.','Future closeout success requires exact readback, other512 body preservation and one actual postwrite census; no automatic rollback or retry after uncertain writes.']}
R=N/'generated-field-4gb-administrative-closeout-independent-review-v01.json';need(not R.exists(),'new concrete review');R.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');R.chmod(0o444);print(json.dumps({'review':pin(R)[0],'passed':True,'artifacts':len(artifacts),'actual_candidate_files':109,'no_API_locks_or_state_parse':True},indent=2))
