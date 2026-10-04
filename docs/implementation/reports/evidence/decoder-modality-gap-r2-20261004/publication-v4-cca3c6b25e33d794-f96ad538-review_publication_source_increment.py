"""Append a read-only compatibility review for explicitly requested unimported additions."""
from pathlib import Path
import argparse,hashlib,json,subprocess
R=Path(__file__).resolve().parent;P=R.parents[2]
def info(raw):return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def git(*args):return subprocess.check_output(['git',*args],cwd=P)
def tree(commit):
 result={}
 for row in git('ls-tree','-rz',commit).split(b'\0'):
  if row:
   metadata,name=row.split(b'\t');mode,kind,blob=metadata.decode().split();result[name.decode()]={'mode':mode,'type':kind,'blob':blob}
 return result

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--prior',type=Path,required=True);ap.add_argument('--parent',required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--added',action='append',required=True);a=ap.parse_args()
 assert a.prior.resolve().parent==R and a.output.resolve().parent==R and not a.output.exists()
 priorraw=a.prior.read_bytes();prior=json.loads(priorraw);assert prior['passed'] and not prior['findings'];old=prior['publication_parent'];new=a.parent;tested=prior['tested_parent'];checks=0;findings=[];artifacts=dict(prior['artifacts'])
 def check(value,label):
  nonlocal checks
  checks+=1
  if not value:findings.append(label)
 artifacts[str(a.prior.resolve())]=info(priorraw);artifacts[str(Path(__file__).resolve())]=info(Path(__file__).read_bytes())
 for name,wanted in artifacts.items():check(info(Path(name).read_bytes())==wanted,'immutable/'+name)
 check(subprocess.run(['git','merge-base','--is-ancestor',old,new],cwd=P,check=False).returncode==0,'git/previous_ancestor')
 check(subprocess.run(['git','merge-base','--is-ancestor',tested,new],cwd=P,check=False).returncode==0,'git/tested_ancestor')
 step=[row.split('\t') for row in git('diff','--no-renames','--name-status',old,new).decode().splitlines()]
 check(step==[['A',name] for name in sorted(a.added)] and len(a.added)==len(set(a.added)),'git/exact_requested_additions')
 changed=git('diff','--no-renames','--name-only',tested,new).decode().splitlines();check(changed==sorted(set(prior['changed_paths'])|set(a.added)),'git/cumulative_paths')
 protected=prior['protected_paths'];owned=json.loads((R/'owned-files-v3.json').read_bytes());check(set(owned)<=set(protected),'owned/all63_protected')
 overlap=sorted(set(protected)&set(changed));check(not overlap,'git/no_protected_overlap')
 oldtree,newtree=tree(tested),tree(new)
 for name in protected:check(oldtree.get(name)==newtree.get(name),'git/protected_entry_unchanged/'+name)
 runtime=json.loads((R/'publication-integration/runtime-provenance.json').read_bytes());new_module='ipfs_datasets_py.logic.formalization.autoencoder.ir_legal_text_roundtrip'
 check(new_module not in runtime['modules'],'runtime/new_module_not_loaded')
 refs=[]
 for name,record in runtime['retained_sources'].items():
  if name.endswith('.py') and 'ir_legal_text_roundtrip' in Path(record['path']).read_text():refs.append(name)
 check(not refs,'closure/new_module_not_referenced')
 added_records={name:{'commit':new,'relative_path':name,'git_entry':newtree[name],**info(git('show',new+':'+name)),'absent_at_previous_parent':name not in tree(old)} for name in a.added}
 receipt={'schema':prior['schema'],'passed':not findings,'findings':findings,'finding_count':len(findings),'checks':checks,'artifacts':artifacts,'tested_parent':tested,'publication_parent':new,'validated_base':prior['validated_base'],'original_integration_review':prior['original_integration_review'],'prior_review':{'path':str(a.prior.resolve()),**info(priorraw)},'previous_publication_parent':old,'changed_paths':changed,'step_changed_paths':sorted(a.added),'protected_paths':protected,'relevant_overlap':overlap,'tested_closure_unchanged':not findings,'ancestor_verified':not findings,'tests_reexecuted':False,'frozen_six_fit_reexecuted':False,'new_added_git_sources':added_records,'git_tree_identities':{commit:git('rev-parse',commit+'^{tree}').decode().strip() for commit in (tested,old,new)},'direct_new_module_references_in_retained_closure':refs,'scope':['Append-only compatibility review of three unimported additions. Prior source-advance receipt and all its evidence are rehashed unchanged.','All349protected paths retain exact tested-parent Git entry modes/types/blob identities. The85explicit test files and imported/retained runtime closure are unchanged.','No tests, numerical fits, native encoder operations, staging or publication executed. New added behavior is not validated.'],'admitted':False,'qualified':False,'lake_executed':False}
 with a.output.open('x') as stream:stream.write(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
 print(json.dumps({k:receipt[k] for k in ('passed','checks','findings','publication_parent')},indent=2));raise SystemExit(bool(findings))
if __name__=='__main__':main()
