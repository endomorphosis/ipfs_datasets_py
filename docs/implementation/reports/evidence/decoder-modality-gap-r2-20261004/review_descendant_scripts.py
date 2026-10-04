"""Independent read-only descendant publication guard review and rejection tests."""
from pathlib import Path
from copy import deepcopy
import ast,hashlib,importlib.util,json,time
R=Path(__file__).resolve().parent;P=R.parents[2]
E=P/'docs/implementation/reports/evidence/decoder-modality-gap-r2-20261004'
CHECKS=0;ARTIFACTS={}
def check(ok,label):
 global CHECKS
 CHECKS+=1
 if not ok:raise ValueError(label)
def bind(path,wanted=None):
 path=Path(path).resolve();data=path.read_bytes();meta=dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
 if wanted is not None:check(meta=={k:wanted[k] for k in ('bytes','sha256')},'changed artifact '+str(path))
 if str(path) in ARTIFACTS:check(meta==ARTIFACTS[str(path)],'changed during review '+str(path))
 ARTIFACTS[str(path)]=meta;return data
def read(path):return json.loads(bind(path))
def main():
 started=time.monotonic()
 names=['publication_descendant_support.py','prepare_publication_support_v2.py','prepare_publication_review_v2.py','publish_v2.py','final_verify_v2.py']
 scripts={name:bind(R/name).decode() for name in names}
 for data in scripts.values():ast.parse(data)
 manifest=read(E/'manifest.json');results=read(E/'results.json');document=read(R/'documentation-review.json')
 check(manifest['archive']==results['archive'],'archive metadata changed')
 for name in ['manifest.json','results.json','README.md']+[v['filename'] for v in manifest['archive_parts']]:bind(E/name)
 for name in ['build_evidence.py','prepare_publication_review.py','publish.py','final_verify.py']:
  bind(R/name,manifest['members']['validation/'+name])
 check(hashlib.sha256(bind(P/'docs/autoencoders/source_modality_training.md')).hexdigest()==document['document_sha256'],
  'archived numerical guide changed')
 source=read(R/'publication-source-advance-review.json');integration=read(R/'publication-integration-review.json')
 for review in (source,integration):
  check(review['passed'] and review['findings']==[],'required source review failed')
  for path,meta in review['artifacts'].items():bind(path,meta)
 spec=importlib.util.spec_from_file_location('_independent_descendant_support',R/'publication_descendant_support.py')
 helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
 actual=helper.validate_descendant(helper.PUBLICATION_PARENT)
 check(actual['tested_parent']==helper.TESTED_PARENT and actual['publication_parent']==helper.PUBLICATION_PARENT,
  'tested and publication parents conflated')
 check(actual['protected_path_count']==301 and len(actual['changed_paths'])==3,'reviewed scope differs')
 check(actual['source_advance_review_sha256']==ARTIFACTS[str(R/'publication-source-advance-review.json')]['sha256'],
  'advance receipt not bound')
 rejected=[]
 try:helper.validate_descendant(helper.TESTED_PARENT)
 except AssertionError:rejected.append('unreviewed_parent')
 else:raise ValueError('arbitrary ancestor accepted')
 original_root=helper.R
 class ReviewPath(type(Path())):
  raw_override=None
  def read_bytes(self):
   if str(self)==str(R/'publication-source-advance-review.json') and self.raw_override is not None:return self.raw_override
   return super().read_bytes()
 def reject(name,mutate):
  changed=deepcopy(source);mutate(changed)
  ReviewPath.raw_override=json.dumps(changed).encode();helper.R=ReviewPath(R)
  try:helper.validate_descendant(helper.PUBLICATION_PARENT)
  except (AssertionError,ValueError,KeyError):rejected.append(name)
  else:raise ValueError('unsafe descendant variant accepted: '+name)
  finally:helper.R=original_root;ReviewPath.raw_override=None
 changes=[('failed_audit',lambda v:v.update(passed=False)),('findings',lambda v:v.update(findings=['unresolved'])),
  ('wrong_tested_parent',lambda v:v.update(tested_parent='0'*40)),('wrong_publication_parent',lambda v:v.update(publication_parent='0'*40)),
  ('ancestry_not_verified',lambda v:v.update(ancestor_verified=False)),('closure_not_unchanged',lambda v:v.update(tested_closure_unchanged=False)),
  ('invented_test_rerun',lambda v:v.update(tests_reexecuted=True)),('invented_fit_rerun',lambda v:v.update(frozen_six_fit_reexecuted=True)),
  ('relevant_overlap',lambda v:v.update(relevant_overlap=['pytest.ini'])),
  ('missing_changed_path',lambda v:v['changed_paths'].pop()),('missing_protection',lambda v:v['protected_paths'].remove('pytest.ini')),
  ('duplicate_protection',lambda v:v['protected_paths'].append(v['protected_paths'][0])),
  ('relevant_changed_file',lambda v:v['protected_paths'].append(v['changed_paths'][0])),
  ('artifact_drift',lambda v:v['artifacts'][next(iter(v['artifacts']))].update(sha256='0'*64)),
  ('integration_receipt_drift',lambda v:v['original_integration_review'].update(sha256='0'*64))]
 for name,mutate in changes:reject(name,mutate)
 old_git=helper.git
 def drift_git(*args):
  value=old_git(*args)
  if args[:1]==('diff',):return value+b'pytest.ini\n'
  return value
 helper.git=drift_git
 try:helper.validate_descendant(helper.PUBLICATION_PARENT)
 except AssertionError:rejected.append('actual_unreviewed_diff')
 else:raise ValueError('actual unreviewed path drift accepted')
 finally:helper.git=old_git
 def mode_drift(*args):
  value=old_git(*args)
  if args[:2]==('ls-tree',helper.PUBLICATION_PARENT) and args[-1]=='pytest.ini':return b'synthetic changed Git entry\n'
  return value
 helper.git=mode_drift
 try:helper.validate_descendant(helper.PUBLICATION_PARENT)
 except AssertionError:rejected.append('actual_protected_git_entry_drift')
 else:raise ValueError('actual protected entry drift accepted')
 finally:helper.git=old_git
 check(len(rejected)==18,'negative guard inventory differs')
 check(helper.validate_descendant(helper.PUBLICATION_PARENT)==actual,'guard changed state after synthetic tests')
 for token in ["source_paths", "original_artifact_publication_paths", "is_relative_to(R)", "publication-descendant-script-review.json"]:
  check(token in scripts['publication_descendant_support.py'],'supplement authentication missing '+token)
 prep=scripts['prepare_publication_support_v2.py']
 for token in ["review['passed'] is True", "review['artifacts']", "open('xb')", "archive_rebuilt=False", "tests_reexecuted=False", "frozen_six_fit_reexecuted=False"]:
  check(token in prep,'support preparation guard missing '+token)
 pub=scripts['publish_v2.py']
 for token in ["advance=validate_descendant(base);supplement=validate_supplement()", "base == compatibility['publication_parent']",
  "assert set(changed) == set(owned)", "assert local_state(PACKAGE) == before", "archived_review == integration_bytes", "manifest['publication_producer_source_sha256']"]:
  check(token in pub,'publisher guard missing '+token)
 check("'-v2.index'" in pub and "'publication-v2.json'" in pub,'new publication would reuse old mutable state')
 check("integration_review['publication_parent'] == TESTED_PARENT" in pub,'tested evidence relabelled as descendant execution')
 for name in names:bind(R/name)
 bind(__file__)
 output=dict(schema='source-modality-publication-descendant-script-review/v1',passed=True,findings=[],checks=CHECKS,
  artifacts=ARTIFACTS,tested_parent=helper.TESTED_PARENT,publication_parent=helper.PUBLICATION_PARENT,
  validated_actual_descendant_guard=True,negative_variants_rejected=rejected,protected_path_count=actual['protected_path_count'],
  original_archive_and_manifest_unchanged=True,original_scripts_unchanged=True,original_docs_unchanged=True,
  supplement_source_mapping_reviewed=True,tests_reexecuted=False,frozen_six_fit_reexecuted=False,
  synthetic_guard_tests_only=True,models_executed=False,archive_rebuilt=False,git_mutations=False,
  publisher_executed=False,supplement_preparation_executed=False,qualified=False,admitted=False,
  elapsed_seconds=time.monotonic()-started)
 with (R/'publication-descendant-script-review.json').open('x') as f:json.dump(output,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
 print(json.dumps(dict(passed=True,checks=CHECKS,artifacts=len(ARTIFACTS),rejected=len(rejected))))
if __name__=='__main__':main()
