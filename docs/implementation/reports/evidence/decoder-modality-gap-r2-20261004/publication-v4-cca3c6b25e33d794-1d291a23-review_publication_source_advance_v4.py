"""Read-only descendant compatibility; no test/model or original evidence rewrite."""
from pathlib import Path
import hashlib,json,subprocess
F=Path(__file__).resolve().parent;P=F.parents[2];R=F/'publication-integration';C=R/'experiment-source';D=R/'source-advance-v4'
OLD='b11f2514a0180fdbebb4bcd878beef21885cb7db';NEW='da853fa837b89a4ef01fa981127cfc446158371e';PREVIOUS='ada682a45ddb76c88b73fb273abfdc8db0760a2a';BASE='8ca1ceed01f9b2b2667de5b41fb7672d917911e8'
ADDITIONS=['docs/autoencoders/pilots/intent_codebase_grounding/ir_model_publication_handoff.json','docs/autoencoders/pilots/intent_codebase_grounding/ir_model_publication_handoff.md','ipfs_datasets_py/logic/formalization/autoencoder/ir_model_hub_publish.py','ipfs_datasets_py/logic/formalization/autoencoder/ir_model_manager_import.py','tests/unit/logic/formalization/autoencoder/test_ir_model_hub_publish.py','tests/unit/logic/formalization/autoencoder/test_ir_model_manager_import.py']
EXPECTED=['ipfs_datasets_py/logic/software_contracts/codebase_inventory_lineage.py','tests/unit/logic/software_contracts/test_codebase_inventory_lineage.py','tests/unit/logic/software_contracts/test_codebase_inventory_successor_model.py']
checks=0;findings=[];artifacts={}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(value,label):
 global checks
 checks+=1
 if not value:findings.append(label)
def pin(p,wanted=None):
 p=Path(p).resolve();assert not p.is_relative_to(C)
 v={'bytes':p.stat().st_size,'sha256':sha(p)};check(wanted is None or wanted==v['sha256'],'hash/'+str(p));artifacts[str(p)]=v;return v
def read(p):pin(p);return json.loads(Path(p).read_bytes())
def git(*args):return subprocess.check_output(['git',*args],cwd=P)
def entries(commit):
 out={}
 for row in git('ls-tree','-r','-z',commit).split(b'\0'):
  if not row:continue
  meta,path=row.split(b'\t',1);mode,kind,blob=meta.decode().split();out[path.decode()]={'mode':mode,'type':kind,'blob':blob}
 return out
def main():
 output=F/'publication-source-advance-review-v4.json';assert not output.exists();assert not D.exists();D.mkdir();pin(__file__)
 prior=read(F/'publication-source-advance-review-v3.json');pin(F/'review_publication_source_advance_v3.py')
 for path,record in prior['artifacts'].items():check(pin(path,record['sha256'])['bytes']==record['bytes'],'prior_v2/immutable/'+path)
 original_path=F/'publication-integration-review.json';original=read(original_path)
 check(original['passed'] and original['publication_parent']==OLD and original['validated_base']==BASE,'original/clean_exact_parent')
 for path,record in original['artifacts'].items():
  current=pin(path,record['sha256']);check(current['bytes']==record['bytes'],'original/artifact_size/'+path)
 manifest=read(R/'candidate-manifest-r5.json');runtime=read(R/'runtime-provenance.json')
 public=P/'docs/implementation/reports/evidence/decoder-modality-gap-r2-20261004';archive=read(public/'manifest.json');results=read(public/'results.json')
 for part in archive['archive_parts']:
  actual=pin(public/part['filename'],part['sha256']);check(actual['bytes']==part['bytes'],'archive/part_size/'+part['filename'])
 code=read(F/'code-files.json');owned=read(F/'owned-files-v3.json')
 for supplement_name in ('publication-supplement.json','publication-supplement-v3.json'):
  supplement=read(public/supplement_name)
  for section in ('files','immutable_evidence'):
   for name,record in supplement[section].items():check(pin(public/name,record['sha256'])['bytes']==record['bytes'],'prior_supplements/immutable/'+name)
 protected=set(owned)|set(code)|set(archive['publication_producer_source_sha256'])|set(runtime['retained_sources'])|set(manifest['tests'])|set(manifest['test_helpers'])|set(manifest['added_tracked_nonweight_metadata'])|{'pytest.ini'}
 ancestry=subprocess.run(['git','merge-base','--is-ancestor',OLD,NEW],cwd=P,check=False).returncode==0;check(ancestry,'git/descendant')
 changes=git('diff','--name-only',OLD,NEW).decode().splitlines();step_changes=git('diff','--name-status',PREVIOUS,NEW).decode().splitlines();step_records=[row.split('\t') for row in step_changes]
 check(len(step_records)==59 and [row for row in step_records if row[0]!='A']==[['M','ipfs_datasets_py/logic/software_contracts/ast_ir.py']],'git/exact_step_modified_path')
 check(sum(row[0]=='A' and row[1].startswith('docs/software_contracts/evidence/ast-text-printability-20261004/') for row in step_records)==57 and ['A','tests/unit/logic/software_contracts/test_ast_text_validation.py'] in step_records,'git/exact_step_added_scope')
 check(changes==sorted(set(prior['changed_paths'])|{row[1] for row in step_records}) and len(changes)==68,'git/exact_cumulative_changed_paths')
 overlap=sorted(protected.intersection(changes));check(not overlap,'git/no_relevant_overlap')
 oldentries=entries(OLD);newentries=entries(NEW);identities={}
 check(all(name not in oldentries and name in newentries for name in ADDITIONS),'git/six_additions_only')
 for name in sorted(protected):
  old,new=oldentries.get(name),newentries.get(name);check(old==new,'git/protected_entry_unchanged/'+name);identities[name]={'tested_parent':old,'publication_parent':new}
 candidate_matches={}
 for name,record in runtime['retained_sources'].items():
  check(sha(record['path'])==record['sha256']==manifest['sources'][name]['sha256'],'retained/source_binding/'+name)
  if manifest['sources'][name]['origin'] in ('git','git_nonweight_metadata'):
   raw=git('show',NEW+':'+name);actual=hashlib.sha256(raw).hexdigest();check(actual==record['sha256'],'candidate/unchanged_git_bytes/'+name);candidate_matches[name]=actual
 for name,wanted in original['owned_candidate_sha256'].items():check(pin(P/name,wanted)['sha256']==manifest['owned_candidate_sha256'][name],'owned/exact_overlay/'+name)
 for name,wanted in archive['publication_producer_source_sha256'].items():
  if name in original['owned_candidate_sha256']:check(wanted==original['owned_candidate_sha256'][name],'producer/owned_overlay/'+name)
  else:check(hashlib.sha256(git('show',NEW+':'+name)).hexdigest()==wanted,'producer/actual_publication_bytes/'+name)
 check(hashlib.sha256(git('show',NEW+':pytest.ini')).hexdigest()==sha(R/'pytest-current-main.ini'),'config/exact_pytest_bytes')
 external=manifest['statement_lock'];check(pin(external['path'],external['sha256'])['bytes']==external['bytes'],'external/statement_lock_unchanged')
 changed_records={}
 for name in changes:
  copies={}
  for label,commit in [('tested-parent',OLD),('publication-parent',NEW)]:
   entry=(oldentries if label=='tested-parent' else newentries).get(name)
   if entry is None:copies[label]={'absent':True,'git_entry':None};continue
   raw=git('show',commit+':'+name);copies[label]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'git_entry':entry}
   if name in ('ipfs_datasets_py/logic/software_contracts/ast_ir.py','tests/unit/logic/software_contracts/test_ast_text_validation.py'):
    dst=D/label/name;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(raw);copies[label].update(path=str(dst));pin(dst)
  changed_records[name]=copies
 small_diff=D/'ast-printability-source.diff';small_diff.write_bytes(git('diff','--full-index',PREVIOUS,NEW,'--','ipfs_datasets_py/logic/software_contracts/ast_ir.py'));pin(small_diff)
 raw_delta=small_diff.read_text();check('-    if any(not character.isprintable() for character in value):' in raw_delta and '+    if value and not value.isprintable():' in raw_delta,'source/exact_small_printability_delta')
 tokens=('codebase_inventory_lineage','codebase_inventory_successor_model','ir_model_hub_publish','ir_model_manager_import','software_contracts.ast_ir','test_ast_text_validation');references=[]
 for name,record in runtime['retained_sources'].items():
  if name.endswith('.py'):
   content=Path(record['path']).read_text()
   references.extend({'path':name,'token':token} for token in tokens if token in content)
 check(not references,'closure/no_direct_changed_module_reference')
 check(not any(token in n for n in runtime['modules'] for token in tokens),'runtime/changed_modules_not_loaded')
 receipt={'schema':'source-modality-publication-source-advance/v1','passed':not findings,'checks':checks,'finding_count':len(findings),'findings':findings,'artifacts':artifacts,'tested_parent':OLD,'publication_parent':NEW,'validated_base':BASE,'original_integration_review':{'path':str(original_path),**pin(original_path)},'changed_paths':changes,'added_paths':[name for name in changes if name not in oldentries],'step_changed_paths':[row[1] for row in step_records],'step_parent':PREVIOUS,'git_tree_identities':{commit:git('rev-parse',commit+'^{tree}').decode().strip() for commit in (OLD,PREVIOUS,NEW)},'previous_publication_parent':prior['publication_parent'],'existing_supplements':{name:{'path':str(public/name),**pin(public/name)} for name in ('publication-supplement.json','publication-supplement-v3.json')},'protected_paths':sorted(protected),'protected_git_entries':identities,'relevant_overlap':overlap,'tested_closure_unchanged':not overlap and not findings,'ancestor_verified':ancestry,'tests_reexecuted':False,'frozen_six_fit_reexecuted':False,'candidate_git_source_sha256':candidate_matches,'owned_candidate_sha256':original['owned_candidate_sha256'],'changed_source_records':changed_records,'completed_archive':{'manifest':{'path':str(public/'manifest.json'),**pin(public/'manifest.json')},'results':{'path':str(public/'results.json'),**pin(public/'results.json')},'archive':archive['archive'],'archive_parts':archive['archive_parts']},'direct_changed_module_references_in_retained_closure':references,'audit_revision':{'prior_receipt':str(F/'publication-source-advance-review-v3.json'),'reason':'Authenticate one unimported printability optimization, one new test and57 evidence paths at the next descendant; preserve original tests/archive and both prior supplements. No full evidence diff is copied.'},'scope':['The original 3434 tests and three semantic gates ran at tested_parent with the recorded owned/frozen-test overlays. No test or model was executed at publication_parent.','Every protected Git entry (mode/type/blob, including absent entries) is identical between the two parents. Every retained Git-origin candidate byte and publication producer is authenticated at publication_parent. Owned/frozen test overlays remain separately bound.','Since the previous reviewed parent, software_contracts/ast_ir.py replaces a per-character printability predicate with a native string predicate; one test and57 evidence files are added. The cumulative68changed paths remain outside protected closure. Their behavior is not validated by this receipt. Exact tree/blob/mode/content hashes are retained; only the small new code/test blobs and source diff are copied.','The original integration receipt and historical numerical evidence remain immutable; this receipt supports publication on an unrelated descendant without claiming new numerical or semantic results.'],'admitted':False,'qualified':False,'lake_executed':False}
 output.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n');print(json.dumps({k:receipt[k] for k in ('passed','checks','finding_count','findings','changed_paths')},indent=2));raise SystemExit(bool(findings))
if __name__=='__main__':main()
