"""Independent actual write/retention closure, hashes only; no global scan or live API."""
from pathlib import Path
import hashlib,json,os,stat,time
N=Path('/home/barberb/lift_coding/artifacts/legal-storage-closeout-20261012-02');O=N/'generated-field-4gb-administrative-closeout-attempt-01';OWN='474ee6b5ae784516ae1dab7ca38c8cc6'
def need(x,m):
 if not x:raise AssertionError(m)
def raw(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(x):return hashlib.sha256(raw(x)).hexdigest()
def ordinary(p,directory=False):
 p=Path(p).absolute()
 for x in (*reversed(p.parents),p):
  s=x.lstat();need(not stat.S_ISLNK(s.st_mode),'symlink refused');need(stat.S_ISDIR(s.st_mode) if x!=p or directory else stat.S_ISREG(s.st_mode),'ordinary artifact')
 return p
identity_stat=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink)
def pin(p):
 p=ordinary(p);h=hashlib.sha256();count=0
 with p.open('rb') as f:
  a=os.fstat(f.fileno())
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b);count+=len(b)
  z=os.fstat(f.fileno())
 need(identity_stat(a)==identity_stat(z)==identity_stat(p.lstat()),'opaque file hash changed');return {'path':str(p),'bytes':count,'sha256':h.hexdigest()}
def read(p):
 p=ordinary(p);need(p.stat().st_size<=16*1024*1024,'bounded metadata JSON')
 def unique(items):
  d={}
  for k,v in items:need(k not in d,'duplicate JSON');d[k]=v
  return d
 return json.loads(p.read_bytes(),object_pairs_hook=unique,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite:'+v)))
def ident(p):
 p=ordinary(p,True);s=p.stat();return {'path':str(p),'device':s.st_dev,'inode':s.st_ino}
def check_census(x,full):
 need(x['additional_requested_bytes']==0 and x['limit_bytes']==145_000_000_000 and x['outstanding_full_reservations_bytes']==full and x['observed_apparent_bytes']==x['inventory']['apparent_bytes'] and x['charged_bytes']==x['observed_apparent_bytes']+full,'census exactformula')
 need(x['over_limit_bytes']==max(0,x['charged_bytes']-145_000_000_000) and x['filesystem_free_shortfall_bytes']==max(0,full-x['minimum_filesystem_free_bytes']) and x['capacity_satisfied']==(x['over_limit_bytes']==0 and x['filesystem_free_shortfall_bytes']==0),'honest capacityflag')
protocol=read(N/'generated-field-4gb-administrative-closeout-protocol-v01.json');review=read(N/'generated-field-4gb-administrative-closeout-independent-review-v01.json');complete=read(O/'completion.json');post=read(O/'actual-postwrite-census.json')
need(review['passed'] is True and review['findings']==[] and review['phase']=='selected-claim-administrative-closeout','concrete approved operation')
need(complete['complete'] is True and complete['schema']=='generated-field-4gb-administrative-closeout-result/v1' and complete['reservation_id']==OWN and complete['helper']==protocol['helper'] and complete['protocol']==pin(N/'generated-field-4gb-administrative-closeout-protocol-v01.json') and complete['independent_review']==pin(N/'generated-field-4gb-administrative-closeout-independent-review-v01.json'),'actual exact source/protocol/review joins')
oldpin=pin(O/'ledger-before.local.json');planpin=pin(O/'ledger-after-planned.local.json');afterpin=pin(O/'ledger-after.local.json');L=Path(complete['after']['path']);livepin=pin(L)
need(oldpin==complete['before_local_backup'] and oldpin['sha256']=='1f93e0ca70ea6199f16d58834e30d60d127f9891e380454e470df352720bb824' and complete['before']==protocol['ledger_before'],'private original raw ledger exact')
need(planpin==complete['planned_after_local_backup'] and afterpin==complete['after_local_backup'] and livepin==complete['after'] and planpin['sha256']==afterpin['sha256']==livepin['sha256']=='a50b21493d6e19541c51ffda214dcba79014a9e1b0df542a35bc812ea518b0d7','planned actual current after raw bytes agree')
before=read(O/'ledger-before.local.json');planned=read(O/'ledger-after-planned.local.json');after=read(O/'ledger-after.local.json');live=read(L);need(planned==after==live,'actual parsed after equals planned')
for value in (before,planned,after,live):
 need(value['schema']=='daemon-resource-reservations-v1' and value['roots']==protocol['roots'] and value['limit_bytes']==145_000_000_000,'cap roots schema preserved');need(len(value['reservations'])==513 and set(value['reservations'])==set(before['reservations']),'all513records exact');need({k:digest(v) for k,v in value['reservations'].items() if k!=OWN}==protocol['prior_512_body_hashes'],'all512otherbodies preserved')
a=before['reservations'][OWN];b=live['reservations'][OWN];need(digest(a)==protocol['own_record_body_sha256'] and a['status']=='retained' and b['status']=='released' and b['artifacts_durable_asserted'] is True,'exact selected retained record released')
allowed={'status','artifacts_durable_asserted','released_at','final_accounting','final_attempt_bytes','final_external_charged_bytes','final_total_charged_bytes','attempt_exceeded_reservation','explicit_reconciliation'};changed={k for k in set(a)|set(b) if a.get(k)!=b.get(k)};need(changed<=allowed,'selected bookkeeping fields only')
need(b['owner_pid']==a['owner_pid']==1421156 and b['child']==a['child']=={'pid':1434010,'birth':'7454855'} and b['prior_children']==[] and b['external_charges']=={} and b['storage_bytes']==4_000_000_000,'original owner/envelope/child not adopted')
need(b['final_attempt_bytes']==b['final_total_charged_bytes']==249_979_161 and b['final_external_charged_bytes']==0 and b['attempt_exceeded_reservation'] is False,'bounded existing outputs finalaccounting')
e=b['explicit_reconciliation'];need(e['schema']=='explicit-retained-reservation-reconciliation/v2' and e['capacity_policy']=='administrative_closeout' and e['reservation_id']==OWN and e['previous_record_sha256']==protocol['own_record_body_sha256'] and e['artifacts']==protocol['expected_artifacts'],'exact modern administrative event')
need(e['outputs_deleted'] is False and e['automatic_expiry'] is False and e['admitted'] is False and e['cap_changed'] is False and e['final_accounting_is_prewrite_projection'] is True and e['actual_postwrite_census_required'] is True and e['fresh_global_inventory_count']==2 and e['new_reservation_created'] is False and e['new_resource_lease_acquired'] is False,'event scope/projection flags')
need(e['other_reservations_sha256']==digest({k:v for k,v in before['reservations'].items() if k!=OWN}),'foreign aggregate')
check_census(e['full_claim_accounting'],48_181_777_216);check_census(e['final_accounting'],44_181_777_216);need(e['full_claim_accounting']==complete['full_claim_accounting'] and e['final_accounting']==complete['final_accounting']==b['final_accounting'],'savedpre/projected accounting');need(e['full_claim_accounting']['outstanding_full_reservations_bytes']-e['final_accounting']['outstanding_full_reservations_bytes']==4_000_000_000,'exact4GBdiscount')
need(post['actual_postwrite_observation'] is True and post['prewrite_projection'] is False and post['ledger']==livepin and post['own_claim_status']=='released' and post['training_admitted'] is False and post['new_reservations']==0 and post['new_resource_leases']==0 and complete['actual_postwrite_census_receipt']==pin(O/'actual-postwrite-census.json') and complete['actual_postwrite_accounting']==post['actual_accounting'],'actualpostwrite separate snapshot exactlyjoined');check_census(post['actual_accounting'],44_181_777_216)
need(sum(x['status']=='retained' for x in live['reservations'].values())==100 and sum(x['status']=='released' for x in live['reservations'].values())==413 and sum(x['storage_bytes'] for x in live['reservations'].values() if x['status']!='released')==44_181_777_216,'actual100retained413released')
for pid,sha in protocol['previous_released_record_body_hashes'].items():need(digest(live['reservations'][pid])==sha and live['reservations'][pid]['status']=='released','priorc6/0350unchanged')
need([ident(x['path']) for x in protocol['roots']]==protocol['roots'],'all4roots unchanged');A=Path(protocol['attempt_identity']['path']);need(ident(A)==protocol['attempt_identity'],'historical attempt root');dirs=[];files=[]
for p in [A,*sorted(A.rglob('*'))]:
 s=p.lstat();need(not stat.S_ISLNK(s.st_mode),'retained symlink')
 if stat.S_ISDIR(s.st_mode):dirs.append({'path':str(p.relative_to(A)),'device':s.st_dev,'inode':s.st_ino});continue
 need(stat.S_ISREG(s.st_mode) and s.st_nlink==1,'retainedartifact unaliased');v=pin(p);files.append({'path':str(p.relative_to(A)),'bytes':v['bytes'],'sha256':v['sha256']})
need(dirs==protocol['candidate_directory_identities'] and len(dirs)==16 and files==protocol['expected_artifacts'] and len(files)==109 and sum(x['bytes'] for x in files)==249_979_161,'all109files249979161B/16dirs exact')
for name,v in protocol['candidate_sibling_pins'].items():
 p=Path(v['path']);s=p.lstat();need(pin(p)==v and {'device':s.st_dev,'inode':s.st_ino,'nlink':s.st_nlink,'bytes':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns}==protocol['candidate_sibling_identities'][name],'eight sibling bytes/identity')
need(not Path('/proc/1421156').exists(),'original owner still absent');groups=[]
for p in Path('/proc').iterdir():
 if not p.name.isdecimal():continue
 try:z=(p/'stat').read_text()
 except (FileNotFoundError,ProcessLookupError):continue
 f=z[z.rfind(')')+2:].split()
 if int(p.name)==1434010:need(f[19]=='7454855','old child PID reused')
 if f[0]!='Z' and int(f[2])==1434010:groups.append(int(p.name))
need(groups==[],'recordedgroup still dead');state=read(protocol['scheduler']['state']['path']);need(digest(state['config'])==protocol['scheduler']['config_sha256'] and protocol['scheduler']['owned_lease_id'] not in state['leases'],'config historicallease absence');need(ident(protocol['ledger_parent_identity']['path'])==protocol['ledger_parent_identity'],'ledgerparent identity');lock=Path(protocol['lock']['artifact']['path']);s=lock.lstat();need(pin(lock)==protocol['lock']['artifact'] and {'device':s.st_dev,'inode':s.st_ino,'nlink':s.st_nlink}==protocol['lock']['identity'],'stablelock identity')
need((O.stat().st_mode&511)==0o700,'private outputdir mode');private={}
for name in ['ledger-before.local.json','ledger-after-planned.local.json','ledger-after.local.json']:
 p=O/name;need((p.stat().st_mode&511)==0o600 and p.stat().st_nlink==1,'private backupmode');private[name]=pin(p)
artifacts={}
for path,want in protocol['artifacts'].items():
 if path==str(L):continue
 need(pin(path)==want,'prepared source/input/candidate drift:'+path);artifacts[path]=want
for p in [N/'generated-field-4gb-administrative-closeout-protocol-v01.json',N/'generated-field-4gb-administrative-closeout-independent-review-v01.json',O/'completion.json',O/'actual-postwrite-census.json',O/'attempt-started.json',O/'planned-mutation.json',N/'generated-field-4gb-application-execution-v01.log']:
 artifacts[str(p)]=pin(p)
need(pin(L)==livepin,'closing liveledger unchanged');actual=post['actual_accounting'];headroom=145_000_000_000-actual['charged_bytes'];releasedhash=digest(b)
report={'schema':'generated-field-selected-4gb-postclosure-independent-review/v1','phase':'actual-selected4GB-closeout-closure','observed_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'passed':True,'findings':[],'reservation_id':OWN,'artifacts':artifacts,'actual_current_ledger':livepin,'private_full_ledger_backup_metadata_only':private,'actual_selected_record':{'previous_body_sha256':protocol['own_record_body_sha256'],'released_body_sha256':releasedhash,'status':'released','full_discount_bytes':4_000_000_000,'outputs_retained_bytes':249_979_161,'files_retained':109,'directories_retained':16,'siblings_retained':8},'actual_record_aggregate':{'record_count':513,'retained':100,'released':413,'active_or_reserved':0,'outstanding_full_claims_bytes':44_181_777_216,'other512_body_hashes_exact':True,'old510_nonselected_historical_bodies_unchanged':True,'priorc6_and0350_released_bodies_unchanged':True},'checks':{'corrected_helper_protocol_source_and_concrete_review_exact':True,'private_before1f93_planned_actual_current_after_a50_raw_agree':True,'only_selected_bookkeeping_fields_changed':True,'all512_other_claim_bodies_and_keyset_preserved':True,'all109files249979161B16dirs8siblings_unchanged':True,'actual_owner_group_absent_no_adoption':True,'current145GBcap4roots_lock_config_and_historical_leaseabsence_unchanged':True,'fullclaim_pre_and_projection_discount_exact4GB':True,'one_actualpostwrite_census_receipt_separatefrom_projection':True,'raw_privatebackups_mode600_directory700_excludedfrom_publication':True,'no_models_updates_leases_admission_outputdeletion_or140GBguardian_adoption':True},'accounting_observations':{'full_preclaim':e['full_claim_accounting'],'prospective_postclaim':e['final_accounting'],'actual_postwrite':actual,'actual_postwrite_headroom_bytes':headroom,'hypothetical200MB_request_remaining_headroom_bytes':headroom-200_000_000,'extra_relief_for5GB_after200MB_request_bytes':max(0,5_000_000_000-headroom+200_000_000),'actual_vs_projected_observed_delta_bytes':actual['observed_apparent_bytes']-e['final_accounting']['observed_apparent_bytes'],'ledger_size_growth_bytes':livepin['bytes']-oldpin['bytes'],'actual_census_reused_from_root_helper_no_global_scan_here':True},'reviewer_actions':{'global_censuses':0,'live_API_calls':0,'ledger_locks':0,'claim_mutations':0,'model_state_JSON_parses':0,'model_calls':0,'optimizer_updates':0,'Git_or_HF_calls':0},'limits':['This actual closure authenticates successful exact selected4GB administrative write while retaining all outputs/weights and512 other records. It grants no additional claim cleanup.','The helper performed its one required actualpostwrite census; this reviewer verifies saved provenance/arithmetic and runs no redundant global scan.','Actual headroom5.738670969GB is a sequential snapshot, not guaranteed future capacity or training admission; a fresh separately reviewed guardian admission remains required.','Fullpre/projected observations were below145GB for this operation. The historical0350 over-cap recovery proof is separate; no false actualover-cap assertion here.','All249.979161MB old outputs remain counted. The4GB relief removes the full retained reservation, not data/weights or a claimed completed18fit comparison.','Private before/planned/actual rawledgers remain local; published evidence contains only hashes/aggregates and existing source/artifact hash metadata.','No modelstate parsing/replay, semanticUSCode accuracy, logicfamily/Lake qualification, new trainedweights or HFpublication is inferred.']}
R=N/'generated-field-4gb-postclosure-independent-review-v01.json';need(not R.exists(),'fresh closure receipt');R.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');R.chmod(0o444);print(json.dumps({'review':pin(R),'passed':True,'current_ledger':livepin,'selected_released_body_sha256':releasedhash,'headroom':headroom,'after_hypothetical200MB':headroom-200_000_000,'no_extra_census':True},indent=2))
