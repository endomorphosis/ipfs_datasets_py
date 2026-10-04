from pathlib import Path
import hashlib,json,subprocess
from publication_descendant_support_v3 import validate_descendant,validate_supplement,TESTED_PARENT
P=Path('/home/barberb/lift_coding/external/ipfs_datasets');W=P.parent.parent;R=Path(__file__).resolve().parent
E=P/'docs/implementation/reports/evidence/decoder-modality-gap-r2-20261004'
def git(root,*args):return subprocess.check_output(['git',*args],cwd=root)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_bytes())
def state(root):
 index=Path(git(root,'rev-parse','--path-format=absolute','--git-path','index').decode().strip())
 return dict(head=git(root,'rev-parse','HEAD').decode().strip(),index_sha256=sha(index))
x=read(R/'publication-v3.json');assert x['package_pushed'] and x['workspace_pushed']
for root,name in ((P,'package'),(W,'workspace')):
 assert git(root,'ls-remote','--heads','origin','main').decode().split()[0]==x[name+'_commit']
 assert state(root)==x[name+'_local_before']
assert git(W,'rev-parse',x['workspace_commit']+':external/ipfs_datasets').decode().strip()==x['package_commit']
owned=read(R/'owned-files-v3.json');assert len(owned)>=9
for relative in owned:
 blob=git(P,'show',x['package_commit']+':'+relative)
 assert hashlib.sha256(blob).hexdigest()==sha(P/relative),relative
m=read(E/'manifest.json');results=read(E/'results.json');assert m['archive']==results['archive']
assert read(R/'independent-audit.json')['passed'] and read(R/'documentation-review.json')['passed']
compatibility=read(R/'publication-compatibility-v3.json')
assert compatibility['manifest_sha256']==sha(E/'manifest.json') and compatibility['results_sha256']==sha(E/'results.json')
assert m['historical_producer_sources']==compatibility['historical_producer_sources']
advance=validate_descendant(x['package_parent']);supplement=validate_supplement()
assert x['source_advance']==compatibility['source_advance']==advance
assert x['publication_supplement']==compatibility['publication_supplement']==supplement
integration=read(R/'publication-integration-review.json')
assert integration['passed'] is True and integration['findings']==[]
assert integration['publication_parent']==x['tested_parent']==TESTED_PARENT and integration['validated_base']==x['validated_code_base']
assert integration['producer_overrides']==m['publication_producer_overrides']==compatibility['producer_overrides']
assert sha(R/'publication-integration-review.json')==compatibility['integration_review_sha256']==m['publication_integration']['sha256']
assert integration['frozen_six_fit_reexecuted'] is False and integration['scoped_tests_passed'] is True and integration['semantic_gates_passed'] is True
for relative,wanted in m['publication_producer_source_sha256'].items():
 assert hashlib.sha256(git(P,'show',x['package_commit']+':'+relative)).hexdigest()==wanted
for scoped,record in m['historical_producer_sources'].items():
 scope,relative=scoped.split(':',1)
 assert scope=='parent_extension' and relative=='ipfs_datasets_py/logic/formalization/autoencoder/long_span_source_value_training.py'
 assert hashlib.sha256(git(P,'show',x['validated_code_base']+':'+relative)).hexdigest()==record['sha256']
 assert m['members'][record['archive_member']]['sha256']==record['sha256']
for relative,wanted in results['candidate_sha256'].items():assert sha(P/relative)==wanted
checkpoint=read(R/'before.json')['checkpoint'];path=Path(checkpoint['path']);metadata=path.stat()
assert sha(path)==checkpoint['sha256'] and metadata.st_size==checkpoint['bytes'] and metadata.st_ino==checkpoint['inode']
value=dict(complete=True,tested_parent=TESTED_PARENT,publication_parent=x['package_parent'],source_advance=advance,package_commit=x['package_commit'],workspace_commit=x['workspace_commit'],remote_heads_verified=True,
 local_heads_and_indexes_preserved=True,protected_checkpoint_unchanged=True,owned_file_count=len(owned),archive=m['archive'],
 numerical_resource_checks=read(R/'independent-audit.json')['checks'],documentation_checks=read(R/'documentation-review.json')['checks'],
 qualified=False,admitted=False,lake_executed=False,checkpoint_promoted=False)
(R/'final-verification-v3.json').write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value))
