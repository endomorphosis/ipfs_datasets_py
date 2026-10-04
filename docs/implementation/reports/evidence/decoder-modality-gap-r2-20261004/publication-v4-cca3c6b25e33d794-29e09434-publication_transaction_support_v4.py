"""Small exact-receipt publication transaction; numerical evidence stays immutable."""
from pathlib import Path
import hashlib,json,subprocess
from publication_descendant_support_v3 import validate_supplement as validate_prior_supplement
P=Path('/home/barberb/lift_coding/external/ipfs_datasets')
R=Path(__file__).resolve().parent
E=P/'docs/implementation/reports/evidence/decoder-modality-gap-r2-20261004'
TESTED_PARENT='b11f2514a0180fdbebb4bcd878beef21885cb7db'
def info(raw):return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
def read(path):return json.loads(Path(path).read_bytes())
def git(*args):return subprocess.check_output(['git',*args],cwd=P)
def key_for(path):return info(Path(path).read_bytes())['sha256'][:16]
def paths_for(path):
 key=key_for(path)
 return key,R/('owned-files-v4-'+key+'.json'),E/('publication-supplement-v4-'+key+'.json')
def validate_descendant(parent, review_path):
 assert len(parent)==40 and all(c in '0123456789abcdef' for c in parent)
 review_path=Path(review_path).resolve();assert review_path.parent==R and review_path.name.startswith('publication-source-advance-review')
 assert review_path.is_file() and not review_path.is_symlink()
 raw=review_path.read_bytes();review=json.loads(raw)
 assert review['schema']=='source-modality-publication-source-advance/v1'
 assert review['passed'] is True and review['findings']==[]
 assert review['tested_parent']==TESTED_PARENT and review['publication_parent']==parent
 base=read(R/'before.json')['package']['origin_main'];assert review['validated_base']==base
 assert review['ancestor_verified'] is True and review['tested_closure_unchanged'] is True
 assert review['tests_reexecuted'] is False and review['frozen_six_fit_reexecuted'] is False
 assert review['relevant_overlap']==[]
 for name,expected in review['artifacts'].items():assert info(Path(name).read_bytes())==expected,name
 original=review['original_integration_review'];assert original['path']==str(R/'publication-integration-review.json')
 integration_raw=Path(original['path']).read_bytes()
 assert {k:original[k] for k in ('bytes','sha256')}==info(integration_raw)
 integration=json.loads(integration_raw)
 assert integration['publication_parent']==TESTED_PARENT and integration['validated_base']==base
 assert integration['passed'] is True and integration['findings']==[]
 assert integration['scoped_tests_passed'] is True and integration['semantic_gates_passed'] is True
 assert integration['owned_sources_unchanged'] is True and integration['frozen_six_fit_reexecuted'] is False
 for name,expected in integration['artifacts'].items():assert info(Path(name).read_bytes())==expected,name
 subprocess.check_call(['git','merge-base','--is-ancestor',TESTED_PARENT,parent],cwd=P)
 changed=set(git('diff','--name-only','--no-renames',TESTED_PARENT+'..'+parent).decode().splitlines())
 assert changed==set(review['changed_paths']) and len(changed)==len(review['changed_paths'])
 manifest=read(E/'manifest.json');runtime=read(R/'publication-integration/runtime-provenance.json')
 minimum=set(read(R/'owned-files-v3.json'))|set(manifest['publication_producer_source_sha256'])|set(runtime['retained_sources'])|{'pytest.ini'}
 protected=set(review['protected_paths']);assert len(protected)==len(review['protected_paths']) and minimum<=protected
 assert not protected&changed
 for relative in protected:
  assert isinstance(relative,str) and not Path(relative).is_absolute() and '..' not in Path(relative).parts
  assert git('ls-tree',TESTED_PARENT,'--',relative)==git('ls-tree',parent,'--',relative),relative
 for path in (E/'manifest.json',E/'results.json',R/'publication-integration/runtime-provenance.json'):
  assert str(path) in review['artifacts'] and info(path.read_bytes())==review['artifacts'][str(path)]
 assert manifest['publication_integration']['publication_parent']==TESTED_PARENT
 assert review_path.read_bytes()==raw
 return dict(tested_parent=TESTED_PARENT,publication_parent=parent,source_advance_review_sha256=info(raw)['sha256'],
             changed_paths=sorted(changed),protected_path_count=len(protected),archive_unchanged=True)

def validate_supplement(review_path):
 key,owned_path,supplement_path=paths_for(review_path)
 prior=validate_prior_supplement()
 raw=supplement_path.read_bytes();value=json.loads(raw)
 assert value['schema']=='source-modality-publication-transaction-supplement/v1'
 assert value['prior_supplement']==prior and value['source_advance_review']==info(Path(review_path).read_bytes())
 assert value['archive_rebuilt'] is False and value['tests_reexecuted'] is False and value['frozen_six_fit_reexecuted'] is False
 assert value['tested_parent']==TESTED_PARENT and value['publication_parent']==read(review_path)['publication_parent']
 review=read(R/'publication-transaction-script-review-v4.json');assert review['passed'] is True and review['findings']==[]
 for source,wanted in review['artifacts'].items():assert info(Path(source).read_bytes())==wanted,source
 for name,wanted in value['files'].items():
  assert Path(name).name==name and name.startswith('publication-v4-'+key+'-') and info((E/name).read_bytes())==wanted,name
  source=Path(value['source_paths'][name]);assert source.is_file() and not source.is_symlink() and source.is_relative_to(R)
  assert source.read_bytes()==(E/name).read_bytes(),name
 assert set(value['files'])==set(value['source_paths'])
 for name,wanted in value['immutable_evidence'].items():assert info((E/name).read_bytes())==wanted,name
 assert set(value['immutable_evidence'])=={str((P/p).relative_to(E)) for p in read(R/'owned-files-v3.json') if (P/p).is_relative_to(E)}
 assert len(set(value['source_paths'].values()))==len(value['source_paths'])
 assert value['original_artifact_publication_paths']=={s:str((E/n).relative_to(P)) for n,s in value['source_paths'].items()}
 expected=set(read(R/'owned-files-v3.json'))|{str((E/n).relative_to(P)) for n in value['files']}|{str(supplement_path.relative_to(P))}
 owned=read(owned_path);assert len(owned)==len(set(owned)) and set(owned)==expected
 required={str(Path(review_path).resolve()),str(R/'publication-transaction-script-review-v4.json')}|{str(R/n) for n in SCRIPTS}
 assert required<=set(value['source_paths'].values())
 for n in SCRIPTS:assert review['artifacts'][str(R/n)]==info((R/n).read_bytes())
 return info(raw)

SCRIPTS=('publication_transaction_support_v4.py','publish_v4.py','final_verify_v4.py')
def prepare_inputs(review_path,parent):
 """Create one append-only supplement and compatibility receipt before staging."""
 review_path=Path(review_path).resolve();advance=validate_descendant(parent,review_path)
 prior_info=validate_prior_supplement();script_review_path=R/'publication-transaction-script-review-v4.json'
 script_review=read(script_review_path);assert script_review['passed'] is True and script_review['findings']==[]
 for source,wanted in script_review['artifacts'].items():assert info(Path(source).read_bytes())==wanted,source
 for n in SCRIPTS:assert script_review['artifacts'][str(R/n)]==info((R/n).read_bytes()),n
 key,owned_path,supplement_path=paths_for(review_path)
 assert not owned_path.exists() and not supplement_path.exists(), 'use a new independently reviewed receipt for a new attempt'
 manifest=read(E/'manifest.json');results=read(E/'results.json');original_owned=read(R/'owned-files-v3.json')
 original=set(manifest['original_artifact_archive_paths'])|set(manifest['referenced_artifacts'])
 for prior_name in ('publication-supplement.json','publication-supplement-v3.json'):
  previous=read(E/prior_name);original.update(previous['source_paths'].values())
 immutable={str((P/p).relative_to(E)):info((P/p).read_bytes()) for p in original_owned if (P/p).is_relative_to(E)}
 original.update(str(E/n) for n in immutable)
 needed={str(R/n) for n in SCRIPTS}|{str(script_review_path),str(review_path)}
 for receipt in (script_review,read(review_path)):needed.update(receipt['artifacts'])
 needed.difference_update(original)
 contents={};sources={}
 for source in sorted(needed):
  path=Path(source);assert path.is_relative_to(R) and path.is_file() and not path.is_symlink(),source
  raw=path.read_bytes();assert len(raw)<=5_000_000,source
  name='publication-v4-'+key+'-'+info(source.encode())['sha256'][:8]+'-'+path.name
  assert not (E/name).exists() and name not in contents
  contents[name]=raw;sources[name]=source
 assert sum(map(len,contents.values()))<=30_000_000
 value=dict(schema='source-modality-publication-transaction-supplement/v1',tested_parent=TESTED_PARENT,publication_parent=parent,
  source_advance=advance,source_advance_review=info(review_path.read_bytes()),prior_supplement=prior_info,
  files={n:info(raw) for n,raw in contents.items()},source_paths=sources,immutable_evidence=immutable,
  original_artifact_publication_paths={s:str((E/n).relative_to(P)) for n,s in sources.items()},
  archive_rebuilt=False,tests_reexecuted=False,frozen_six_fit_reexecuted=False,qualified=False,admitted=False,lake_executed=False)
 owned=original_owned+[str((E/n).relative_to(P)) for n in sorted(contents)]+[str(supplement_path.relative_to(P))]
 assert len(owned)==len(set(owned))
 # Check current parent collision before any supplemental write.
 changes=set(git('diff','--name-only','--no-renames',read(R/'before.json')['package']['origin_main']+'..'+parent).decode().splitlines())
 assert not changes&set(owned)
 for n,raw in contents.items():
  with (E/n).open('xb') as stream:stream.write(raw)
 with supplement_path.open('x') as stream:stream.write(json.dumps(value,indent=2,sort_keys=True)+'\n')
 with owned_path.open('x') as stream:stream.write(json.dumps(owned,indent=2)+'\n')
 supplement=validate_supplement(review_path)
 allowed=set(manifest['publication_producer_overrides']);assert changes&set(manifest['validated_producer_source_sha256'])==allowed
 historical=manifest['historical_producer_sources'];base=read(R/'before.json')['package']['origin_main']
 for scoped,record in historical.items():assert info(git('show',base+':'+scoped.split(':',1)[1]))['sha256']==record['sha256']
 compatibility=dict(publication_parent=parent,tested_parent=TESTED_PARENT,source_advance=advance,publication_supplement=supplement,
  producer_overlap=[],owned_overlap=[],passed=True,historical_sources_verified_against_validated_base=True,
  integration_review_passed=True,integration_review_sha256=info((R/'publication-integration-review.json').read_bytes())['sha256'],
  results_sha256=info((E/'results.json').read_bytes())['sha256'],manifest_sha256=info((E/'manifest.json').read_bytes())['sha256'],
  owned_files_sha256=info(owned_path.read_bytes())['sha256'],code_files_sha256=info((R/'code-files.json').read_bytes())['sha256'],
  producer_overrides=manifest['publication_producer_overrides'],historical_producer_sources=historical)
 with (R/('publication-compatibility-v4-'+key+'.json')).open('x') as stream:stream.write(json.dumps(compatibility,indent=2,sort_keys=True)+'\n')
 return advance,supplement,compatibility
