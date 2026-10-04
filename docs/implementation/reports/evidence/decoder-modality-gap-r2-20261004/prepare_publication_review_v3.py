"""Read-only exact producer/current-main compatibility before alternate-index publication."""
from pathlib import Path
import hashlib,json,subprocess
from publication_descendant_support_v3 import validate_descendant,validate_supplement,TESTED_PARENT
P=Path('/home/barberb/lift_coding/external/ipfs_datasets');R=Path(__file__).resolve().parent
BASE=json.loads((R/'before.json').read_bytes())['package']['origin_main'];E=P/'docs/implementation/reports/evidence/decoder-modality-gap-r2-20261004'
def git(*args):return subprocess.check_output(['git',*args],cwd=P)
def sha(b):return hashlib.sha256(b).hexdigest()
remote=git('rev-parse','origin/main').decode().strip()
subprocess.check_call(['git','merge-base','--is-ancestor',BASE,remote],cwd=P)
advance=validate_descendant(remote);supplement=validate_supplement()
manifest=json.loads((E/'manifest.json').read_bytes());owned=json.loads((R/'owned-files-v3.json').read_bytes())
changed=set(git('diff','--name-only',BASE+'..'+remote).decode().splitlines())
producer_overlap=changed & set(manifest['validated_producer_source_sha256']);owned_overlap=changed & set(owned)
allowed={'ipfs_datasets_py/logic/deontic/formula_builder.py','ipfs_datasets_py/logic/deontic/utils/deontic_parser.py',
 'ipfs_datasets_py/logic/legal_ir/canonical_compiler.py','ipfs_datasets_py/logic/legal_ir/canonical_decompiler.py',
 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py'}
review_path=R/'publication-integration-review.json';review_bytes=review_path.read_bytes();review=json.loads(review_bytes)
integration=manifest['publication_integration']
assert integration['review_member']=='validation/publication-integration-review.json'
assert {k:integration[k] for k in ('bytes','sha256')}==dict(bytes=len(review_bytes),sha256=sha(review_bytes))
assert review['schema']=='source-modality-publication-integration/v1' and review['passed'] is True and review['findings']==[]
assert review['publication_parent']==integration['publication_parent']==TESTED_PARENT and review['validated_base']==BASE
assert review['scoped_tests_passed'] is True and review['semantic_gates_passed'] is True
assert review['owned_sources_unchanged'] is True and review['frozen_six_fit_reexecuted'] is False
assert producer_overlap==allowed and not owned_overlap and not allowed & set(owned)
assert set(review['producer_overrides'])==set(manifest['publication_producer_overrides'])==allowed
assert review['producer_overrides']==manifest['publication_producer_overrides']
assert review['owned_candidate_sha256']=={rel:sha((P/rel).read_bytes()) for rel in json.loads((R/'code-files.json').read_bytes()) if rel.endswith('.py')}
for name,expected in review['artifacts'].items():
 data=Path(name).read_bytes();assert expected==dict(bytes=len(data),sha256=sha(data)),name
expected_publication=dict(manifest['validated_producer_source_sha256'])
for rel,value in review['producer_overrides'].items():
 assert set(value)=={'historical_sha256','publication_sha256'}
 assert value['historical_sha256']==expected_publication[rel] and value['publication_sha256']==sha(git('show',remote+':'+rel))
 assert value['historical_sha256']!=value['publication_sha256']
 expected_publication[rel]=value['publication_sha256']
 assert integration['source_members'][rel]=='publication-source/'+rel
 assert manifest['members'][integration['source_members'][rel]]['sha256']==value['publication_sha256']
assert expected_publication==manifest['publication_producer_source_sha256']
historical=manifest['historical_producer_sources']
trainer='ipfs_datasets_py/logic/formalization/autoencoder/long_span_source_value_training.py'
assert set(historical)=={'parent_extension:'+trainer}
prior=historical['parent_extension:'+trainer]
assert prior['archive_member']=='historical-source/parent_extension/'+trainer
assert manifest['members'][prior['archive_member']]['sha256']==prior['sha256']
assert sha(git('show',BASE+':'+trainer))==prior['sha256']
for scoped,value in manifest['scoped_validated_producer_sources'].items():
 scope,relative=scoped.split(':',1)
 assert scope in ('dependency','parent_extension','extension')
 assert manifest['members'][value['archive_member']]['sha256']==value['sha256']
 if scoped in historical:
  assert value==historical[scoped]
 else:
  assert value['archive_member']=='source/'+relative
  assert manifest['validated_producer_source_sha256'][relative]==value['sha256']
intentional=set(json.loads((R/'code-files.json').read_bytes()))
comparisons={}
for rel,h in manifest['publication_producer_source_sha256'].items():
 value=subprocess.run(['git','show',remote+':'+rel],cwd=P,capture_output=True)
 old=None if value.returncode else sha(value.stdout)
 if old!=h:
  assert rel in intentional and sha((P/rel).read_bytes())==h,rel
 comparisons[rel]=dict(parent_sha256=old,validated_sha256=h,intentional_change=old!=h)
result=dict(publication_parent=remote,tested_parent=TESTED_PARENT,source_advance=advance,publication_supplement=supplement,validated_base=BASE,producer_overlap=[],reviewed_producer_overlap=sorted(producer_overlap),owned_overlap=sorted(owned_overlap),
 manifest_sha256=sha((E/'manifest.json').read_bytes()),results_sha256=sha((E/'results.json').read_bytes()),
 integration_review_sha256=sha(review_bytes),integration_review_passed=True,
 owned_files_sha256=sha((R/'owned-files-v3.json').read_bytes()),code_files_sha256=sha((R/'code-files.json').read_bytes()),
 historical_producer_sources=historical,historical_sources_verified_against_validated_base=True,
 producer_overrides=manifest['publication_producer_overrides'],
 comparisons=comparisons,producer_count=len(comparisons),changed_producers=[p for p,v in comparisons.items() if v['intentional_change']],
 passed=True,publication_performed=False,head_or_index_changed=False)
with (R/'publication-compatibility-v3.json').open('x') as output:
 output.write(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='comparisons'}))
