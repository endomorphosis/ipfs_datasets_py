"""Read-only descendant compatibility; no test/model or original evidence rewrite."""
from pathlib import Path
import hashlib,json,subprocess
F=Path(__file__).resolve().parent;P=F.parents[2];R=F/'publication-integration';C=R/'experiment-source';D=R/'source-advance'
OLD='b11f2514a0180fdbebb4bcd878beef21885cb7db';NEW='5621c0d47963318050dc7c31a299d10735329925';BASE='8ca1ceed01f9b2b2667de5b41fb7672d917911e8'
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
 output=F/'publication-source-advance-review.json';assert not output.exists();assert not D.exists();D.mkdir();pin(__file__)
 original_path=F/'publication-integration-review.json';original=read(original_path)
 check(original['passed'] and original['publication_parent']==OLD and original['validated_base']==BASE,'original/clean_exact_parent')
 for path,record in original['artifacts'].items():
  current=pin(path,record['sha256']);check(current['bytes']==record['bytes'],'original/artifact_size/'+path)
 manifest=read(R/'candidate-manifest-r5.json');runtime=read(R/'runtime-provenance.json')
 public=P/'docs/implementation/reports/evidence/decoder-modality-gap-r2-20261004';archive=read(public/'manifest.json');results=read(public/'results.json')
 for part in archive['archive_parts']:
  actual=pin(public/part['filename'],part['sha256']);check(actual['bytes']==part['bytes'],'archive/part_size/'+part['filename'])
 code=read(F/'code-files.json');owned=read(F/'owned-files.json')
 protected=set(code)|set(archive['publication_producer_source_sha256'])|set(runtime['retained_sources'])|set(manifest['tests'])|set(manifest['test_helpers'])|set(manifest['added_tracked_nonweight_metadata'])|{'pytest.ini'}
 ancestry=subprocess.run(['git','merge-base','--is-ancestor',OLD,NEW],cwd=P,check=False).returncode==0;check(ancestry,'git/descendant')
 changes=git('diff','--name-only',OLD,NEW).decode().splitlines();check(changes==EXPECTED,'git/exact_three_changed_paths')
 overlap=sorted(protected.intersection(changes));check(not overlap,'git/no_relevant_overlap')
 oldentries=entries(OLD);newentries=entries(NEW);identities={}
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
   raw=git('show',commit+':'+name);dst=D/label/name;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(raw);copies[label]={'path':str(dst),**pin(dst),'git_entry':(oldentries if label=='tested-parent' else newentries)[name]}
  changed_records[name]=copies
 diff=D/'source-advance.diff';diff.write_bytes(git('diff','--binary','--full-index',OLD,NEW));pin(diff)
 tokens=('codebase_inventory_lineage','codebase_inventory_successor_model');references=[]
 for name,record in runtime['retained_sources'].items():
  if name.endswith('.py'):
   content=Path(record['path']).read_text()
   references.extend({'path':name,'token':token} for token in tokens if token in content)
 check(not references,'closure/no_direct_changed_module_reference')
 check(not any('codebase_inventory_lineage' in n or 'codebase_inventory_successor_model' in n for n in runtime['modules']),'runtime/changed_modules_not_loaded')
 receipt={'schema':'source-modality-publication-source-advance/v1','passed':not findings,'checks':checks,'finding_count':len(findings),'findings':findings,'artifacts':artifacts,'tested_parent':OLD,'publication_parent':NEW,'validated_base':BASE,'original_integration_review':{'path':str(original_path),**pin(original_path)},'changed_paths':changes,'protected_paths':sorted(protected),'protected_git_entries':identities,'relevant_overlap':overlap,'tested_closure_unchanged':not overlap and not findings,'ancestor_verified':ancestry,'tests_reexecuted':False,'frozen_six_fit_reexecuted':False,'candidate_git_source_sha256':candidate_matches,'owned_candidate_sha256':original['owned_candidate_sha256'],'changed_source_records':changed_records,'completed_archive':{'manifest':{'path':str(public/'manifest.json'),**pin(public/'manifest.json')},'results':{'path':str(public/'results.json'),**pin(public/'results.json')},'archive':archive['archive'],'archive_parts':archive['archive_parts']},'direct_changed_module_references_in_retained_closure':references,'scope':['The original 3434 tests and three semantic gates ran at tested_parent with the recorded owned/frozen-test overlays. No test or model was executed at publication_parent.','Every protected Git entry (mode/type/blob, including absent entries) is identical between the two parents. Every retained Git-origin candidate byte and publication producer is authenticated at publication_parent. Owned/frozen test overlays remain separately bound.','The three changed files revise a software-contract inventory lineage migration guard and its two tests; neither their module nor their tests belong to the executed or retained compatibility closure. Their own behavior is not validated by this receipt.','The original integration receipt and historical numerical evidence remain immutable; this receipt supports publication on an unrelated descendant without claiming new numerical or semantic results.'],'admitted':False,'qualified':False,'lake_executed':False}
 output.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n');print(json.dumps({k:receipt[k] for k in ('passed','checks','finding_count','findings','changed_paths')},indent=2));raise SystemExit(bool(findings))
if __name__=='__main__':main()
