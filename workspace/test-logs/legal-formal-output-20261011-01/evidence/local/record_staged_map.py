"""Read and bind only this contribution's staged files in an isolated checkout."""
from pathlib import Path, PurePosixPath
import argparse, subprocess, hashlib, json, os, re
F=Path(__file__).resolve().parent

def sha(raw):return hashlib.sha256(raw).hexdigest()
def git(root,*args):return subprocess.check_output(['git','-C',str(root),*args])
def main():
 p=argparse.ArgumentParser();p.add_argument('kind',choices=['datasets','workspace']);p.add_argument('--source-merge');p.add_argument('--output',required=True);a=p.parse_args();root=F/a.kind
 inventory_path=F/'contribution-copy-inputs-v01.json';inventory_bytes=inventory_path.read_bytes();inventory=json.loads(inventory_bytes)
 for rel,pin in inventory['entries'].items():
  parts=PurePosixPath(rel)
  assert not parts.is_absolute() and parts.as_posix()==rel and all(v not in ('','.','..') for v in rel.split('/'))
  assert rel.startswith(('local/','prepared/','native-build/')) and len(pin['sha256'])==64 and pin['bytes']>=0
 prefix='workspace/test-logs/legal-formal-output-20261011-01/evidence' if a.kind=='datasets' else 'artifacts/legal-formal-output-20261011-01/evidence'
 expected={prefix+'/'+rel:{'status':'A','mode':'100644','sha256':pin['sha256'],'bytes':pin['bytes']} for rel,pin in inventory['entries'].items()}
 if a.kind=='datasets':
  for pin in json.loads((F/'retained-owner-pins.json').read_bytes()).values():
   path=Path(pin['path']);assert path.is_file() and not path.is_symlink() and path.resolve()==path and root.resolve() in path.parents
   raw=path.read_bytes()
   assert sha(raw)==pin['sha256'] and len(raw)==pin['bytes'] and git(root,'show','HEAD:'+path.relative_to(root).as_posix())==raw
  stage=json.loads((F/'source-code-stage-v02.json').read_bytes())
  owners=stage.get('files',stage.get('entries'))
  assert isinstance(owners,dict),stage.keys()
  for path,pin in owners.items():
   rel=PurePosixPath(path);assert not rel.is_absolute() and rel.as_posix()==path and all(v not in ('','.','..') for v in path.split('/')) and path not in expected
   expected[path]={'status':'A','mode':'100644','sha256':pin['sha256'],'bytes':pin['bytes']}
 else:
  raw=(F/'contribution.md').read_bytes();expected['implementation_plan/docs/76-legal-formal-output-2026-10-11.md']={'status':'A','mode':'100644','sha256':sha(raw),'bytes':len(raw)}
  raw=(F/'root-publication.json').read_bytes();expected['artifacts/legal-formal-output-20261011-01/publication.json']={'status':'A','mode':'100644','sha256':sha(raw),'bytes':len(raw)}
  assert a.source_merge and len(a.source_merge)==40
  expected['external/ipfs_datasets']={'status':'M','mode':'160000','object':a.source_merge}
 raw=git(root,'diff','--cached','--name-status','-z');parts=raw.split(b'\0');assert parts[-1]==b'';parts.pop();assert len(parts)%2==0
 observed={parts[i+1].decode():parts[i].decode() for i in range(0,len(parts),2)}
 assert observed=={k:v['status'] for k,v in expected.items()},(set(observed)-set(expected),set(expected)-set(observed))
 entries={}
 for path,e in expected.items():
  index=git(root,'ls-files','--stage','--',path).decode().strip();head,tabpath=index.split('\t');mode,obj,stage=head.split();assert tabpath==path and stage=='0' and mode==e['mode']
  if mode=='160000':assert obj==e['object'];entries[path]={**e,'git_object':obj};continue
  leaf=root/path;assert leaf.is_file() and not leaf.is_symlink() and leaf.resolve()==leaf and root in leaf.parents
  b=git(root,'show',':'+path);w=leaf.read_bytes();assert b==w and sha(b)==e['sha256'] and len(b)==e['bytes'];entries[path]={**e,'git_object':obj}
 code_paths=[k for k in expected if not k.startswith(prefix+'/')]
 git(root,'diff','--cached','--check','--',*code_paths)
 full_check=subprocess.run(['git','-C',str(root),'diff','--cached','--check'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 assert full_check.returncode in (0,2) and not full_check.stderr
 permitted={prefix+'/'+rel for rel in inventory['entries'] if rel.endswith(('.log','.xml'))}
 headers=[];awaiting_excerpt=False
 for line in full_check.stdout.decode().splitlines():
  if line.startswith('+'):
   assert awaiting_excerpt,('unexpected diff-check excerpt',line)
   awaiting_excerpt=False;continue
  assert not awaiting_excerpt,('missing diff-check excerpt',line)
  match=re.fullmatch(r'(.+):([0-9]+): (trailing whitespace|new blank line at EOF)\.',line)
  assert match and match.group(1) in permitted,('unexpected or disallowed diff-check diagnostic',line)
  headers.append(match.group(1));awaiting_excerpt=match.group(3)=='trailing whitespace'
 assert not awaiting_excerpt
 gitlinks={}
 for line in git(root,'ls-tree','-r','HEAD').decode().splitlines():
  meta,path=line.split('\t');mode,kind,obj=meta.split()
  if mode=='160000':
   current=git(root,'ls-files','--stage','--',path).decode().split()[1]
   if a.kind=='workspace':assert current==(a.source_merge if path=='external/ipfs_datasets' else obj)
   gitlinks[path]={'base':obj,'index':current}
 value={'schema':'formal-output-staged-map/v1','passed':True,'findings':[],'kind':a.kind,'root':str(root),'base':git(root,'rev-parse','HEAD').decode().strip(),'branch':git(root,'symbolic-ref','HEAD').decode().strip(),'entries':entries,'count':len(entries),'base_gitlinks':gitlinks,'only_owned_changes':True,'all_staged_regular_bytes_equal_worktree':True,'inventory_sha256':sha(inventory_bytes),'weight_bodies_excluded':True,'full_foreign_ledgers_excluded':True,'source_code_doc_diff_check_passed':True,'raw_evidence_whitespace_preserved':{'returncode':full_check.returncode,'diagnostics_sha256':sha(full_check.stdout),'paths':sorted(set(headers))}}
 assert inventory_path.read_bytes()==inventory_bytes
 with Path(a.output).open('x') as s:json.dump(value,s,indent=2,sort_keys=True);s.write('\n');s.flush();os.fsync(s.fileno())
 print(json.dumps({'passed':True,'kind':a.kind,'base':value['base'],'count':len(entries)}))
if __name__=='__main__':main()
