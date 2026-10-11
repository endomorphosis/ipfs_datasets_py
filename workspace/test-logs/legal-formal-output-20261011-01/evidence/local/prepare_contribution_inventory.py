"""Declare the exact static evidence selection; no weights or foreign ledgers."""
from pathlib import Path,PurePosixPath
import hashlib,json,os
F=Path(__file__).resolve().parent
NAMES='''
audit_git_integration.py
authored-development-cue-declarations-v02.json
authored-development-cue-declarations.json
authored-development-source-only-v02.json
authored-development-source-only.json
baseline-heads.json
bootstrap_inert.py
canonical-intake.json
compiler-execution-protocol-v01.json
compiler-protocol-independent-review-v01.json
contribution.md
contribution_draft_v01.md
copy_contribution.py
development-fixture-independent-review-v02.json
family-adapter-independent-review-v01.json
inert-test-harness-independent-review-v01.json
integration-helper-independent-review-v01.json
inert-tests-v01.log
inert-tests-v01.xml
inert-tests-v02.log
inert-tests-v02.xml
inert-tests-v03.log
inert-tests-v03.xml
inert-tests-v04.log
inert-tests-v04.xml
inert-tests-v05.log
inert-tests-v05.xml
intake-independent-review-v01.json
main-progress-review.json
native-build-execution-v01.log
native-build-result-v01.json
native-result-independent-review-v01.json
native-result-independent-review-v02.json
preparation-execution-v01.log
preparation-observation-v01.json
preparation-result-independent-review-v01.json
prepare_compiler_protocol.py
prepare_contribution_inventory.py
prepare_development_inputs.py
prepare_development_inputs_draft_v01.py
prepare_development_inputs_v02.py
prepare_formal_output_pilot.py
prepare_formal_output_pilot_draft_v01.py
prepare_formal_output_pilot_draft_v02.py
record_github_checks.py
record_staged_map.py
record_staged_map_draft_v01.py
record_staged_map_draft_v02.py
retained-owner-pins.json
review_main_progress.py
run_inert_tests.py
run_inert_tests_draft_v01.py
run_inert_tests_draft_v02.py
run_native_build.py
saved-span-family-adapter-build-v01.json
selected-inert-tests-observation-v01.json
source-code-stage-v01.json
source-code-stage-v02.json
source-guide_draft_v01.md
statutory-declaration-preflight-build-v01.json
statutory-preflight-independent-review-v01.json
statutory-source-only-inputs.json
'''.split()
assert len(NAMES)==len(set(NAMES))
def pin(p):
 assert p.is_file() and not p.is_symlink() and p.resolve()==p
 b=p.read_bytes();return {'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
entries={'local/'+n:pin(F/n) for n in NAMES}
for directory,prefix in [('prepared-pilot-v01','prepared'),('native-build-v01','native-build')]:
 root=F/directory;assert root.is_dir() and not root.is_symlink()
 for p in sorted(root.rglob('*')):
  assert not p.is_symlink() and (p.is_dir() or p.is_file())
  if p.is_dir():continue
  assert p.suffix in ('.json','.lean','.toml') or p.name=='lean-toolchain',p
  rel=prefix+'/'+p.relative_to(root).as_posix();assert rel not in entries;entries[rel]=pin(p)
for rel in entries:
 p=PurePosixPath(rel);assert not p.is_absolute() and p.as_posix()==rel and all(v not in ('','.','..') for v in rel.split('/'))
 assert not any(other.startswith(rel+'/') for other in entries)
value={'schema':'formal-output-contribution-copy-inventory/v1','passed':True,'findings':[],
 'entries':dict(sorted(entries.items())),'count':len(entries),'bytes':sum(v['bytes'] for v in entries.values()),
 'selected_top_level_names':NAMES,'prepared_directories':['prepared-pilot-v01','native-build-v01'],
 'weight_bodies_excluded':True,'full_foreign_ledgers_excluded':True,'full_training_archive_excluded':True,
 'failed_attempts_and_correction_drafts_retained':True,'inventory_itself_excluded_to_avoid_self_digest':True,
 'later_staged_review_and_publication_observations_remain_separate':True,'new_semantic_labels':0}
with (F/'contribution-copy-inputs-v01.json').open('x') as stream:
 json.dump(value,stream,indent=2,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())
print(json.dumps({'files':value['count'],'bytes':value['bytes']}))
