"""Freeze a closed evidence snapshot, excluding weights and foreign archives."""
from pathlib import Path,PurePosixPath
import json,hashlib,os
F=Path(__file__).resolve().parent
EXCLUDED={'contribution-copy-inputs-v01.json','source-staged-map-v01.json','root-staged-map-v01.json','root-publication.json'}
def pin(p):
 assert p.is_file() and not p.is_symlink() and p.resolve()==p
 b=p.read_bytes();return {'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
# The resulting sorted names and pins are reviewed before the copy helper runs.
selected=[];entries={}
for p in sorted(F.iterdir()):
 if p.is_dir():continue
 assert not p.is_symlink() and p.is_file()
 if p.name in EXCLUDED:continue
 assert p.suffix in {'.json','.py','.md','.log','.xml'},p
 assert 'checkpoint' not in p.name and 'weights' not in p.name
 selected.append(p.name);entries['local/'+p.name]=pin(p)
for directory,prefix in [('prepared-native-views-v02','prepared'),('prepared-native-views-v01','prepared/failed-attempt-v01'),('actual-scope-pilot-v01','prepared/actual-scope'),('native-build-v01','native-build')]:
 root=F/directory;assert root.is_dir() and not root.is_symlink()
 for p in sorted(root.rglob('*')):
  assert not p.is_symlink() and (p.is_file() or p.is_dir())
  if p.is_dir():continue
  assert p.suffix in {'.json','.lean','.toml'} or p.name=='lean-toolchain'
  rel=prefix+'/'+p.relative_to(root).as_posix();assert rel not in entries;entries[rel]=pin(p)
for rel in entries:
 p=PurePosixPath(rel);assert not p.is_absolute() and p.as_posix()==rel and all(v not in ('','.','..') for v in rel.split('/'))
 assert not any(other.startswith(rel+'/') for other in entries)
v={'schema':'scope-native-contribution-copy-inventory/v1','passed':True,'findings':[],'entries':dict(sorted(entries.items())),'count':len(entries),'bytes':sum(x['bytes'] for x in entries.values()),'selected_top_level_names':selected,'prepared_directories':['prepared-native-views-v02','prepared-native-views-v01','actual-scope-pilot-v01','native-build-v01'],'weight_bodies_excluded':True,'full_foreign_ledgers_excluded':True,'full_training_archive_excluded':True,'failed_attempts_and_correction_drafts_retained':True,'inventory_itself_excluded_to_avoid_self_digest':True,'later_staged_review_and_publication_observations_remain_separate':True,'new_semantic_labels':0}
with (F/'contribution-copy-inputs-v01.json').open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
print(json.dumps({'files':v['count'],'bytes':v['bytes']}))
