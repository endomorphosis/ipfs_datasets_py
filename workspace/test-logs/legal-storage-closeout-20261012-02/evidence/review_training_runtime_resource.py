"""Independent saved/current runtime evidence review. No live imports, replay or census."""
from pathlib import Path
from collections import Counter
import hashlib,json,os,stat,time
N=Path('/home/barberb/lift_coding/artifacts/legal-storage-closeout-20261012-02');T=N.parent/'legal-temporal-binding-20261012-01';A=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01/temporal-role-contrast-20261012-03')
def need(x,m):
 if not x:raise AssertionError(m)
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(x):return hashlib.sha256(canonical(x)).hexdigest()
def pin(p):
 p=Path(p).absolute()
 for d in (*reversed(p.parents),p):
  s=d.lstat();need(not stat.S_ISLNK(s.st_mode),'symlink refused');need(stat.S_ISDIR(s.st_mode) if d!=p else stat.S_ISREG(s.st_mode),'ordinary file/ancestor')
 h=hashlib.sha256();n=0
 with p.open('rb') as f:
  b=os.fstat(f.fileno())
  for x in iter(lambda:f.read(1024*1024),b''):h.update(x);n+=len(x)
  z=os.fstat(f.fileno())
 key=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink);need(key(b)==key(z)==key(p.lstat()),'artifact changed during opaque hash')
 return {'path':str(p),'bytes':n,'sha256':h.hexdigest()}
def read(p):
 p=Path(p);need(p.stat().st_size<=16*1024*1024,'bounded metadata JSON')
 def uniq(pairs):
  d={}
  for k,v in pairs:need(k not in d,'duplicate JSON');d[k]=v
  return d
 return json.loads(p.read_bytes(),object_pairs_hook=uniq,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite:'+v)))
def inventory(root):
 result={}
 for p in sorted(root.rglob('*')):
  s=p.lstat();need(not stat.S_ISLNK(s.st_mode),'attempt symlink')
  if stat.S_ISDIR(s.st_mode):continue
  need(stat.S_ISREG(s.st_mode) and s.st_nlink==1,'unaliased attempt file');result[str(p.relative_to(root))]=pin(p)
 return result
def ident(p):
 p=Path(p);s=p.lstat();need(stat.S_ISDIR(s.st_mode) and not p.is_symlink(),'ordinary directory');return {'path':str(p),'device':s.st_dev,'inode':s.st_ino}
obs_path=N/'training-runtime-resource-audit-v01.json';proc_path=N/'training-runtime-resource-audit-procedure-v01.json';obs=read(obs_path);procedure=read(proc_path);helper=pin(N/'audit_training_runtime_resources.py');need(helper['sha256']==procedure['helper_sha256']=='a6b90d6b7080da73f988b183510642e7702d50f68c739a4cfe5bf6f3c49a27e4' and helper==obs['helper'],'approved actual auditor source')
need(obs['passed'] is True and obs['findings']==[] and obs['outcome']=='completed' and obs['procedure']==pin(proc_path) and obs['physical_attempt']==str(A),'actual completed audit/procedure')
source_review=read(N/'training-runtime-auditor-source-independent-review-v01.json');proc_review=read(N/'training-runtime-procedure-independent-review-v01.json');train_review=read(N/'training-protocol-independent-review-v01.json');need(all(x['passed'] is True and x['findings']==[] for x in [source_review,proc_review,train_review]),'approved source/procedure/training reviews')
# All opening source/evidence/opaque historical weights stay byte-exact; live ledger intentionally acquires one new claim.
opening={}
for p,want in procedure['opening_artifacts'].items():
 actual=pin(p);need(actual['bytes']==want['bytes'] and actual['sha256']==want['sha256'],'opening pin drift:'+p);opening[p]=actual
actual=inventory(A);need(actual==obs['artifacts'] and sum(x['bytes'] for x in actual.values())==obs['attempt_terminal_bytes']==25_751_059 and obs['attempt_terminal_bytes']<=200_000_000,'complete terminal artifact inventory/actual25.75MB within200MB')
for field,dirname in [('prior_failed_attempt_files','temporal-role-contrast-20261011-01'),('previous_failed_attempt_files','temporal-role-contrast-20261012-01'),('second_previous_failed_attempt_files','temporal-role-contrast-20261012-02')]:
 old=inventory(A.with_name(dirname));need(old==obs[field]==procedure[field],'prior failed attempt retained:'+dirname)
pre=read(A/'pre-admission.json');terminal=read(A/'guardian-exit.json');exit=read(A/'child-exit.json');cleanup=read(A/'owned-group-final.json');rss=read(A/'group-rss-summary.json');final=read(A/'resources-final.json');identity=read(A/'child-identity.json')
need(pre['review']==obs['exact_retry03_training_review']==pin(N/'training-protocol-independent-review-v01.json'),'exact successfulattempt trainingreview binding');need(obs['exact_retry03_compatibility']==procedure['actual_compatibility']==pin(N/'resource-compatibility-v01.json'),'actualresource check binding')
need(terminal['returncode']==terminal['child_returncode']==exit['returncode']==0 and exit['leader_reaped'] is True and cleanup['leader_reaped'] is True and cleanup['live_group_processes']==0 and cleanup['identity']==identity,'success/reap/deadgroup receipts')
need(terminal['artifacts_durable'] is True and terminal['resource_reservation_released'] is True and terminal['model_phase_peak_is_sampled'] is True and terminal['kernel_hard_memory_cap'] is False,'durability/release/sampled flags')
need(exit['launch_through_reap_wall_seconds']==obs['child_launch_through_reap_wall_seconds'] and exit['launch_through_reap_wall_seconds']<=300 and terminal['elapsed_seconds']==obs['guardian_elapsed_seconds'] and rss['model_phase_wall_seconds']<=300,'actualdeadline bounds')
L=Path(obs['ledger_after']['path']);lp=pin(L);ledger=read(L);need(lp==obs['ledger_before']==obs['ledger_after'] and lp['sha256']=='a5fc077f1aee855e235ce73b9e119fa947431568aa836a6bcfdca8c0ed19ce2f','saved/current rawledger identity')
prior=procedure['prior_513_body_hashes'];need(len(prior)==513 and all(digest(ledger['reservations'][k])==v for k,v in prior.items()),'all513pretraining bodies unchanged')
owner=final['owner'];rid=obs['owned_reservation_id'];r=ledger['reservations'][rid];need(rid not in prior and len(ledger['reservations'])==514 and set(ledger['reservations'])==set(prior)|{rid} and obs['other_new_reservation_ids']==[],'only one new owned claim')
need(digest(r)==obs['owned_record_body_sha256']==digest(owner['record']) and r['status']=='released' and r['artifacts_durable_asserted'] is True and r['storage_bytes']==200_000_000 and r['memory_mb']==1536 and r['cpu_slots']==2 and r['child_process_slots']==1 and r['child']==identity and r['attempt_directory']==ident(A),'exact released200MB ownedenvelope')
need(r['attempt_exceeded_reservation'] is False and r['final_total_charged_bytes']<=200_000_000 and r['final_attempt_bytes']==obs['final_reserved_attempt_bytes']==25_743_493,'final reservationbytes bounded')
need(obs['finalized_accounting_excludes_later_terminal_receipts'] is True and obs['attempt_terminal_bytes']-r['final_attempt_bytes']==7_566,'late terminal receipt bytes explicitly accounted')
baseline=read(T/'storage-resource-endpoints-post-migration-v01.json');old=baseline['record_body_hashes'];need(len(old)==511 and [k for k,v in old.items() if digest(ledger['reservations'][k])!=v]==['474ee6b5ae784516ae1dab7ca38c8cc6'],'only approved historical4GB baseline exception')
historical=ledger['reservations']['474ee6b5ae784516ae1dab7ca38c8cc6'];rec=procedure['prior_reconciliation'];need(digest(historical)==rec['released_record_body_sha256']=='d0c6c91d9640dbda5e8e79f9d7737dcb6fcacfd04a1c868c372e7eeda5c113f2' and historical['status']=='released' and historical['explicit_reconciliation']['previous_record_sha256']=='4ca144ebfb780e5aa9e502fd7459f620052b00b20d00f8351aedaaa3829ef687','exact4GBreleasedbody retained')
need(obs['old_511_record_bodies_unchanged'] is False and obs['old_510_unselected_record_bodies_unchanged'] is True and obs['all_prior_513_record_bodies_unchanged'] is True,'truthfulbaseline scopes')
closeout=read(N/'generated-field-4gb-postclosure-independent-review-v01.json');cp=read(N/'generated-field-4gb-administrative-closeout-protocol-v01.json');G=Path(cp['attempt_identity']['path']);need(ident(G)==cp['attempt_identity'],'historicalroot retained');gi=inventory(G);files=[{'path':name,'bytes':v['bytes'],'sha256':v['sha256']} for name,v in gi.items()];need(files==cp['expected_artifacts'] and len(files)==109 and sum(x['bytes'] for x in files)==249_979_161,'all109 historicalopaquehashes retained aftertraining')
dirs=[{'path':str(p.relative_to(G)),'device':p.lstat().st_dev,'inode':p.lstat().st_ino} for p in [G,*sorted(G.rglob('*'))] if p.is_dir()];need(dirs==cp['candidate_directory_identities'],'all16historical dirs')
for v in cp['candidate_sibling_pins'].values():need(pin(v['path'])==v,'eight sibling bytes retained')
need(ledger['limit_bytes']==145_000_000_000 and ledger['roots']==baseline['root_identities'] and [ident(x['path']) for x in ledger['roots']]==ledger['roots'],'145GBcap/fourrootidentity unchanged')
lease=read(A/'lease-binding.json');leaseid=obs['lease_id'];statepath=Path(lease['state_path']);state=read(statepath);sp=pin(statepath);need(leaseid==lease['own_fields']['lease_id'] and leaseid not in state['leases'] and state['config']==baseline['scheduler_config'] and lease['capability_persisted'] is False,'actuallease absent/config fixed/no capabilitypayload')
for k,v in [('cpu_slots',2),('memory_mb',1536),('child_process_slots',1)]:need(lease['own_fields'][k]==v,'exactleaseenvelope')
levents=[json.loads(x) for x in (A/'lease-observations.jsonl').read_text().splitlines() if x];events=[x for x in levents if x['schema']=='guardian-owned-lease-observation/v1'];need(events and not any(x['schema']=='guardian-owned-lease-watchdog-failure/v1' for x in levents),'no recordedleasefailure');need(all(x['healthy'] is True and x['configuration_matches'] is True and x['continuous_coverage_claimed'] is False for x in events),'recordedleasehealthy');need({'pre_spawn','post_spawn','pre_finalize'}<={x['stage'] for x in events} and events[-1]['stage']=='post_finalize' and events[-1]['expected']=='absent' and events[-1]['lease_present'] is False and all(x.get('observation_gap_seconds',0)<=5 for x in events if x['stage'] in {'monitor','post_spawn'}),'lease stages/gap/release')
revents=[json.loads(x) for x in (A/'group-rss-observations.jsonl').read_text().splitlines() if x];need(len(revents)==33 and all(x['schema']=='guardian-owned-group-rss-observation/v1' for x in revents) and rss['failure'] is None and rss['identity']==identity,'RSSsourceevents success')
counts=dict(Counter(x['phase'] for x in revents));peak={p:max((x['group_rss_bytes'] for x in revents if x['phase']==p),default=0) for p in ['gated','model','post_model']};need(counts==rss['sample_counts_by_phase'] and peak==rss['sampled_peaks_by_phase'] and peak['model']==rss['sampled_model_phase_peak_rss_bytes']==terminal['sampled_model_phase_peak_rss_bytes']==obs['sampled_model_phase_peak_rss_bytes']==731_029_504,'independently recomputed sampledRSS counts/peak')
need(all(x['identity']==identity and x['memory_limit_bytes']==1536*1024*1024 and x['group_rss_bytes']<=1536*1024*1024 and x['sampled_only'] is True and x['kernel_hard_cap'] is False for x in revents) and rss['absolute_peak_measured'] is False and rss['continuous_coverage_claimed'] is False and counts['model']==16,'RSS1536MiB envelope/samplinglimits')
# Current process-group metadata only, never signal/create/adopt a process.
live=[]
for p in Path('/proc').iterdir():
 if not p.name.isdecimal():continue
 try:z=(p/'stat').read_text()
 except (FileNotFoundError,ProcessLookupError):continue
 f=z[z.rfind(')')+2:].split()
 if int(p.name)==identity['pid']:need(f[19]==identity['birth'],'childPID reused')
 if f[0]!='Z' and int(f[2])==identity['pid']:live.append(int(p.name))
need(live==[],'actualownedgroup absent')
summary=read(A/'results/summary.json');need(summary['status']=='completed' and summary['actual_new_updates']==64 and len(summary['arms'])==2 and {x['name'] for x in summary['arms']}=={'control','contrast'},'two complete returnedarms64updates');armrefs=[]
for arm in summary['arms']:
 need(arm['actual_new_updates']==32,'eacharm32returnedupdates');training=read(arm['training']['path']);need(training['optimizer_steps']==32 and training['stopped_reason']=='step_limit','returnedtrainingreports32');need(pin(arm['training']['path'])==arm['training'] and pin(arm['checkpoint']['path'])==arm['checkpoint'],'savedreport/checkpointopaquehashes');armrefs.append({'name':arm['name'],'returned_updates':32,'checkpoint':arm['checkpoint'],'training':arm['training']})
need(summary['latent_enabled'] is False and summary['actual_encoder_calls']==0 and summary['trained_dimensions']==[384] and summary['semantic_accuracy'] is None and summary['legal_fidelity_qualified'] is False and summary['Lake_executed'] is False and summary['promotion_performed'] is False and summary['checkpoint_selection_executed'] is False,'sourceonly nominal384 scope, no gold/Lake/promotion')
parent=Path('/home/barberb/lift_coding/artifacts/legal-decoder-native-conditioning-20261002/run-01/source_only-1729/checkpoint-400.json');pp=pin(parent);need(pp['sha256']=='5df537d8c7141578c1355af43317b9c5a327305295a11760aee2897244bc5dbb','originalparent rawcheckpoint5df unchanged')
need(pin(L)==lp and pin(statepath)==sp and inventory(A)==actual,'closing liveledger/scheduler/attempt stable');artifacts={**opening,**{v['path']:v for v in actual.values()},str(parent):pp}
for p in [obs_path,proc_path,N/'training-runtime-procedure-independent-review-v01.json',N/'training-runtime-auditor-source-independent-review-v01.json',N/'training-protocol-independent-review-v01.json',N/'generated-field-4gb-postclosure-independent-review-v01.json']:
 artifacts[str(p)]=pin(p)
report={'schema':'training-runtime-resource-independent-review/v1','phase':'actual-terminal-runtime-resource-review','observed_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'passed':True,'findings':[],'artifacts':artifacts,'physical_attempt':str(A),'actual_current_ledger':lp,'record_summary':{'records':514,'pretraining513_bodies_unchanged':True,'owned_id':rid,'owned_status':'released','owned_body_sha256':digest(r),'owned200MB_reservation_released':True,'only_new_record_is_owned':True,'old511_unchanged':False,'old510_nonselected_unchanged':True,'exact_selected4GB_release_and_c6_0350_bodies_preserved':True},'historical_retention':{'originalparent_checkpoint':pp,'candidate109files':109,'candidate_file_bytes':249_979_161,'candidate16dirs_preserved':True,'candidate8siblings_preserved':True,'all_three_prior_failed_attempts_unchanged':True,'historical_modelstates_parsed_or_replayed':False},'recorded_training_outcome':{'returned_updates':64,'arms':armrefs,'complete32_per_arm':True,'independent_optimizer_update_tracing':False,'numerical_or_checkpoint_replay':False,'latent_enabled':False,'nominal_trained_dimensions':[384],'encoder_calls':0,'Lake_executed':False,'legal_fidelity_qualified':False,'semantic_accuracy':None,'promotion_or_checkpoint_selection':False},'resource_outcome':{'guardian_returncode':0,'child_returncode':0,'guardian_elapsed_seconds':60.039145802962594,'child_launch_through_reap_seconds':31.110938062076457,'model_gate_permission_through_reap_seconds':16.14679534896277,'child_deadline_seconds':300,'cpu_slots':2,'memory_mb':1536,'child_slots':1,'storage_budget_bytes':200_000_000,'sampled_model_peak_rss_bytes':731_029_504,'rss_event_counts_by_phase':counts,'absolute_peak_measured':False,'kernel_hard_memory_cap':False,'continuous_lease_or_RSS_coverage_claimed':False,'actualterminal_bytes':25_751_059,'reserved_finalattempt_bytes':25_743_493,'later_terminal_receipt_bytes':7566,'actual_ownedgroup_live':0,'leader_reaped':True,'ownedlease_id':leaseid,'actual_ownedlease_absent':True,'scheduler_config_unchanged':True,'artifacts_durable_asserted':True},'reviewer_actions':{'liveAPI_or_resource_imports':0,'locks_or_leases':0,'claim_mutations':0,'global_censuses':0,'model_calls':0,'optimizer_updates':0,'checkpoint_restores':0,'Git_or_HF_calls':0},'limits':['64 is independently checked against saved complete childsummary and two returned32step trainingreports, not an independent optimizer-call trace or new numerical replay.','731029504B is recomputed from sampled process-group RSS events; it is not an absolute peak or kernel hard cap. Lease samples/gaps and endpoint absence do not establish continuous custody.','Reservedfinal accounting excludes7566B laterterminal receipts; actualall-terminal bytes remain within200MB.','All513 pretraining record bodies and historical109 files are unchanged; only the new owned200MB claim was created/released. Historical474 was legitimately released beforetraining, so old511 unchanged is false and old510 nonselected unchanged true.','Nominal384 source-only run keeps latent disabled and encodercalls0. No genuine8D/768D latent comparison, independent statutory gold, broaderlogic-family qualification, Lake build, semanticaccuracy or promotion is granted.','No runtimeAPI, imports, modelstate parsing/replay, locks, leases, globalcensus or numerical work occurred in this independent reviewer lane.','Ledger/scheduler/attempt/source equality are bounded endpoint observations; private rawledger bodies remain unpublished and no new HF or Git publication is asserted.']}
R=N/'training-runtime-resource-independent-review-v01.json';need(not R.exists(),'fresh runtime review');R.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');R.chmod(0o444);print(json.dumps({'receipt':pin(R),'passed':True,'artifacts':len(artifacts),'recorded_updates':64,'sampled_peak_bytes':peak['model'],'terminalbytes':25_751_059,'all513_otherbodies_and109historicalfiles_preserved':True,'no_census_or_replay':True},indent=2))
