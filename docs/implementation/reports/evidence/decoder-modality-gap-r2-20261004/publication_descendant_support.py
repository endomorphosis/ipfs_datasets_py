"""Publication-only authentication of one independently reviewed unrelated descendant.

No model execution and no rewriting of the archived b11 integration evidence.
"""
from pathlib import Path
import hashlib,json,subprocess
P=Path('/home/barberb/lift_coding/external/ipfs_datasets')
R=Path(__file__).resolve().parent
E=P/'docs/implementation/reports/evidence/decoder-modality-gap-r2-20261004'
TESTED_PARENT='b11f2514a0180fdbebb4bcd878beef21885cb7db'
PUBLICATION_PARENT='5621c0d47963318050dc7c31a299d10735329925'
EXPECTED_CHANGED={
 'ipfs_datasets_py/logic/software_contracts/codebase_inventory_lineage.py',
 'tests/unit/logic/software_contracts/test_codebase_inventory_lineage.py',
 'tests/unit/logic/software_contracts/test_codebase_inventory_successor_model.py'}
def info(raw):return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
def read(path):return json.loads(Path(path).read_bytes())
def git(*args):return subprocess.check_output(['git',*args],cwd=P)
def validate_descendant(parent):
 assert parent==PUBLICATION_PARENT, ('unreviewed_descendant',parent)
 raw=(R/'publication-source-advance-review.json').read_bytes();review=json.loads(raw)
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
 assert changed==EXPECTED_CHANGED==set(review['changed_paths'])
 manifest=read(E/'manifest.json');runtime=read(R/'publication-integration/runtime-provenance.json')
 minimum=set(read(R/'owned-files.json'))|set(manifest['publication_producer_source_sha256'])|set(runtime['retained_sources'])|{'pytest.ini'}
 protected=set(review['protected_paths']);assert len(protected)==len(review['protected_paths']) and minimum<=protected
 assert not protected&changed
 for relative in protected:
  assert isinstance(relative,str) and not Path(relative).is_absolute() and '..' not in Path(relative).parts
  assert git('ls-tree',TESTED_PARENT,'--',relative)==git('ls-tree',parent,'--',relative),relative
 for path in (E/'manifest.json',E/'results.json',R/'publication-integration/runtime-provenance.json'):
  assert str(path) in review['artifacts'] and info(path.read_bytes())==review['artifacts'][str(path)]
 assert manifest['publication_integration']['publication_parent']==TESTED_PARENT
 return dict(tested_parent=TESTED_PARENT,publication_parent=parent,source_advance_review_sha256=info(raw)['sha256'],
             changed_paths=sorted(changed),protected_path_count=len(protected),archive_unchanged=True)
def validate_supplement():
 raw=(E/'publication-supplement.json').read_bytes();value=json.loads(raw)
 assert value['schema']=='source-modality-publication-supplement/v1'
 assert value['tested_parent']==TESTED_PARENT and value['publication_parent']==PUBLICATION_PARENT
 assert value['archive_rebuilt'] is False and value['tests_reexecuted'] is False and value['frozen_six_fit_reexecuted'] is False
 review=read(R/'publication-descendant-script-review.json');assert review['passed'] is True and review['findings']==[]
 for source,expected in review['artifacts'].items():assert info(Path(source).read_bytes())==expected,source
 required={'publication_descendant_support.py','prepare_publication_support_v2.py','prepare_publication_review_v2.py','publish_v2.py','final_verify_v2.py','publication-source-advance-review.json','publication-descendant-script-review.json'}
 assert required<=set(value['files'])
 for name in required:
  assert value['source_paths'][name]==str(R/name)
  if name!='publication-descendant-script-review.json':assert review['artifacts'][str(R/name)]==value['files'][name]
 for name,expected in value['immutable_evidence'].items():assert info((E/name).read_bytes())==expected,name
 manifest=read(E/'manifest.json')
 assert set(value['immutable_evidence'])=={'manifest.json','results.json','README.md'}|{p['filename'] for p in manifest['archive_parts']}
 assert set(value['files'])==set(value['source_paths'])
 for name,expected in value['files'].items():
  assert Path(name).name==name and info((E/name).read_bytes())==expected,name
  source=value['source_paths'][name]
  assert Path(source).is_relative_to(R) and Path(source).is_file() and not Path(source).is_symlink()
  assert info(Path(source).read_bytes())==expected and Path(source).read_bytes()==(E/name).read_bytes(),name
 assert len(set(value['source_paths'].values()))==len(value['source_paths'])
 assert value['original_artifact_publication_paths']=={source:str((E/name).relative_to(P)) for name,source in value['source_paths'].items()}
 expected=set(read(R/'owned-files.json'))|{str((E/name).relative_to(P)) for name in value['files']}|{str((E/'publication-supplement.json').relative_to(P))}
 owned=read(R/'owned-files-v2.json');assert len(owned)==len(set(owned)) and set(owned)==expected
 assert set(read(R/'owned-files.json')).isdisjoint(str((E/name).relative_to(P)) for name in value['files'])
 return info(raw)
