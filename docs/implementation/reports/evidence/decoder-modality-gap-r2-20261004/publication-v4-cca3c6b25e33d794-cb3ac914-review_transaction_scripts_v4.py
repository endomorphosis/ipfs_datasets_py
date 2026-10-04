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
 names=['publication_transaction_support_v4.py','publish_v4.py','final_verify_v4.py']

 scripts={name:bind(R/name).decode() for name in names}
 for data in scripts.values():ast.parse(data)
 manifest=read(E/'manifest.json');results=read(E/'results.json');document=read(R/'documentation-review.json')
 check(manifest['archive']==results['archive'],'archive metadata changed')
 for name in ['manifest.json','results.json','README.md']+[v['filename'] for v in manifest['archive_parts']]:bind(E/name)
 for name in ['build_evidence.py','prepare_publication_review.py','publish.py','final_verify.py']:
  bind(R/name,manifest['members']['validation/'+name])
 check(hashlib.sha256(bind(P/'docs/autoencoders/source_modality_training.md')).hexdigest()==document['document_sha256'],
  'archived numerical guide changed')
 review_path=R/'publication-source-advance-review-v4.json'
 source=json.loads(review_path.read_bytes());integration=read(R/'publication-integration-review.json')
 exercised_receipt=dict(path=str(review_path),bytes=review_path.stat().st_size,sha256=hashlib.sha256(review_path.read_bytes()).hexdigest())
 actual_parent=source['publication_parent']
 for review in (integration,):
  check(review['passed'] and review['findings']==[],'required source review failed')
  for path,meta in review['artifacts'].items():bind(path,meta)
 spec=importlib.util.spec_from_file_location('_independent_descendant_support',R/'publication_transaction_support_v4.py')
 helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
 prior_supplement=helper.validate_prior_supplement()
 prior=read(E/'publication-supplement-v3.json')
 for name,meta in prior['files'].items():bind(E/name,meta)
 bind(E/'publication-supplement-v3.json',prior_supplement)
 for predecessor in ('publication_descendant_support.py','publication_descendant_support_v3.py'):
  bind(R/predecessor)
 actual=helper.validate_descendant(actual_parent,review_path)
 check(actual['tested_parent']==helper.TESTED_PARENT and actual['publication_parent']==actual_parent,
  'tested and publication parents conflated')
 check(actual['protected_path_count']==349 and len(actual['changed_paths'])==68,'exercised reviewed scope differs')
 check(actual['source_advance_review_sha256']==exercised_receipt['sha256'],
  'advance receipt not bound')
 rejected=[]
 try:helper.validate_descendant(helper.TESTED_PARENT,review_path)
 except AssertionError:rejected.append('unreviewed_parent')
 else:raise ValueError('arbitrary ancestor accepted')
 original_path_type=helper.Path
 class ReviewPath(type(Path())):
  raw_override=None
  def read_bytes(self):
   if str(self)==str(review_path) and self.raw_override is not None:return self.raw_override
   return super().read_bytes()
 def reject(name,mutate):
  changed=deepcopy(source);mutate(changed)
  ReviewPath.raw_override=json.dumps(changed).encode();helper.Path=ReviewPath
  try:helper.validate_descendant(actual_parent,review_path)
  except (AssertionError,ValueError,KeyError):rejected.append(name)
  else:raise ValueError('unsafe descendant variant accepted: '+name)
  finally:helper.Path=original_path_type;ReviewPath.raw_override=None
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
 try:helper.validate_descendant(actual_parent,review_path)
 except AssertionError:rejected.append('actual_unreviewed_diff')
 else:raise ValueError('actual unreviewed path drift accepted')
 finally:helper.git=old_git
 def mode_drift(*args):
  value=old_git(*args)
  if args[:2]==('ls-tree',actual_parent) and args[-1]=='pytest.ini':return b'synthetic changed Git entry\n'
  return value
 helper.git=mode_drift
 try:helper.validate_descendant(actual_parent,review_path)
 except AssertionError:rejected.append('actual_protected_git_entry_drift')
 else:raise ValueError('actual protected entry drift accepted')
 finally:helper.git=old_git
 check(len(rejected)==18,'negative guard inventory differs')
 check(helper.validate_descendant(actual_parent,review_path)==actual,'guard changed state after synthetic tests')
 for token in ["source_paths", "original_artifact_publication_paths", "is_relative_to(R)", "publication-transaction-script-review-v4.json",
  "review['publication_parent']==parent", "minimum=set(read(R/'owned-files-v3.json'))", "assert not protected&changed",
  "changed==set(review['changed_paths'])", "git('ls-tree',TESTED_PARENT", "git('ls-tree',parent", "review_path.read_bytes()==raw"]:
  check(token in scripts['publication_transaction_support_v4.py'],'receipt or supplement authentication missing '+token)
 prep=scripts['publication_transaction_support_v4.py']
 for token in ["script_review['passed'] is True", "script_review['artifacts']", "open('xb')", "archive_rebuilt=False", "tests_reexecuted=False", "frozen_six_fit_reexecuted=False",
  "len(raw)<=5_000_000", "sum(map(len,contents.values()))<=30_000_000", "assert not owned_path.exists() and not supplement_path.exists()"]:
  check(token in prep,'support preparation guard missing '+token)
 pub=scripts['publish_v4.py']
 for token in ["advance,supplement,compatibility=prepare_inputs(REVIEW_PATH,base)", "base==compatibility['publication_parent']",
  "assert set(changed) == set(owned)", "assert local_state(PACKAGE) == before", "archived_review == integration_bytes", "manifest['publication_producer_source_sha256']",
  "GIT_INDEX_FILE=str(path)", "base = git(PACKAGE, 'rev-parse', 'origin/main')", "git(PACKAGE,'push','origin',commit+':refs/heads/main')"]:
  check(token in pub,'publisher guard missing '+token)
 check("'-v4-'+KEY+'.index'" in pub and "'publication-v4-'+KEY+'.json'" in pub,'new transaction would reuse old mutable state')
 check('--force' not in pub and '--force-with-lease' not in pub,'force push introduced')
 check("integration_review['publication_parent'] == TESTED_PARENT" in pub,'tested evidence relabelled as descendant execution')
 check('PUBLICATION_PARENT=' not in prep and 'ALLOWED_CHANGED_PATHS' not in prep,'head-specific publication source retained')
 check("validate_descendant(x['package_parent'],REVIEW_PATH)" in scripts['final_verify_v4.py'],'final verification does not authenticate actual receipt parent')
 for name in names:bind(R/name)
 bind(__file__)
 output=dict(schema='source-modality-publication-transaction-script-review/v1',passed=True,findings=[],checks=CHECKS,
  artifacts=ARTIFACTS,tested_parent=helper.TESTED_PARENT,exercised_publication_parent=actual_parent,exercised_source_advance_review=exercised_receipt,
  future_receipts_revalidated_at_execution=True,
  validated_actual_descendant_guard=True,negative_variants_rejected=rejected,protected_path_count=actual['protected_path_count'],
  original_archive_and_manifest_unchanged=True,original_scripts_unchanged=True,original_docs_unchanged=True,
  prior_v2_v3_supplements_verified_and_unchanged=True,prior_v3_supplement=prior_supplement,
  supplement_source_mapping_reviewed=True,supplemental_maximum_file_bytes=5000000,
  supplemental_total_byte_cap=30000000,numerical_or_resource_limits_changed=False,
  tests_reexecuted=False,frozen_six_fit_reexecuted=False,
  synthetic_guard_tests_only=True,models_executed=False,archive_rebuilt=False,git_mutations=False,
  publisher_executed=False,supplement_preparation_executed=False,qualified=False,admitted=False,
  elapsed_seconds=time.monotonic()-started)
 with (R/'publication-transaction-script-review-v4.json').open('x') as f:json.dump(output,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
 print(json.dumps(dict(passed=True,checks=CHECKS,artifacts=len(ARTIFACTS),rejected=len(rejected))))
if __name__=='__main__':main()
