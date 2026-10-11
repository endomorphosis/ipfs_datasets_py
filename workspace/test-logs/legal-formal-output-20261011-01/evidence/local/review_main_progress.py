"""Read selected prior heads and new/changed autoformalization branches without changing shared HEAD/index."""
from pathlib import Path
import subprocess,json,re,hashlib,os
F=Path(__file__).resolve().parent;P=F.parent/'legal-structured-training-20261011-01';prior=json.loads((P/'main-progress-review.json').read_bytes());out={}
pattern=re.compile(r'autoenc|autoformal|legal|uscode|decoder|latent|gte|family|projection',re.I)
for key,name in [('source','datasets'),('root','workspace')]:
 root=F/name
 def g(*a):return subprocess.check_output(['git','--no-optional-locks','-C',str(root),*a],text=True).strip()
 heads={ref:sha for sha,ref in (line.split() for line in g('ls-remote','--heads','origin').splitlines())}
 old={r['ref']:r['sha'] for r in prior['remote_heads_observed'][key]};previous={r['ref'] for r in prior['relevant_remote_and_local_ancestry'][key]['remote_selected']}
 selected={ref:sha for ref,sha in heads.items() if ref in previous or (pattern.search(ref) and old.get(ref)!=sha)}
 if selected:
  subprocess.run(['git','-C',str(root),'fetch','--refmap=','--no-tags','--no-write-fetch-head','--no-auto-maintenance','--recurse-submodules=no','origin',*['+'+ref+':refs/remotes/legal-formal-output-20261011-01/heads/'+ref.removeprefix('refs/heads/') for ref in selected]],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 base=g('rev-parse','HEAD');rows=[]
 for ref,sha in sorted(selected.items()):
  actual=g('rev-parse','refs/remotes/legal-formal-output-20261011-01/heads/'+ref.removeprefix('refs/heads/'));assert actual==sha
  rc=subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor',sha,base]).returncode
  rows.append({'ref':ref,'sha':sha,'previously_selected':ref in previous,'new_or_changed_since_previous_audit':old.get(ref)!=sha,'in_observed_main':rc==0,'branch_only_commits':int(g('rev-list','--count',base+'..'+sha))})
 assert all(v['in_observed_main'] for v in rows),rows
 out[key]={'baseline':base,'remote_heads_observed':heads,'selected_head_ancestry':rows,'prior_selected_represented':len(previous & set(heads)),'new_or_changed_remote_refs':[ref for ref,sha in heads.items() if old.get(ref)!=sha],'worktree_metadata':g('worktree','list','--porcelain'),'foreign_uncommitted_bytes_not_inspected':True}
v={'schema':'legal-formal-output-main-progress-review/v1','passed':True,'findings':[],'scope':'Prior selected heads plus new/changed matching autoformalization remote branches; preserve prior distinct recovery histories without wholesale merge','repositories':out,'prior_review_pin':{'path':str(P/'main-progress-review.json'),'sha256':hashlib.sha256((P/'main-progress-review.json').read_bytes()).hexdigest()},'prior_distinct_old_recovery_histories_preserved':prior['distinct_old_publication_lineages'],'canonical_HEAD_or_index_changes':False,'models_or_tests_or_resource_claims_executed':False}
with (F/'main-progress-review.json').open('x') as s:json.dump(v,s,indent=2,sort_keys=True);s.write('\n');s.flush();os.fsync(s.fileno())
print(json.dumps({k:{'selected':len(v['selected_head_ancestry']),'new_or_changed_remote_refs':v['new_or_changed_remote_refs'],'all_selected_in_main':True} for k,v in out.items()},indent=2))
