"""Verify saved contribution bytes in the actual Git merge objects (no execution)."""
from pathlib import Path
import argparse, subprocess, hashlib, json, os
F=Path(__file__).resolve().parent

def git(root,*args):return subprocess.check_output(['git','-C',str(root),*args])
def sha(raw):return hashlib.sha256(raw).hexdigest()
def tree(root,ref):
 out={}
 for row in git(root,'ls-tree','-r','-z',ref).split(b'\0'):
  if not row:continue
  meta,path=row.split(b'\t');mode,kind,obj=meta.decode().split();out[path.decode()]={'mode':mode,'kind':kind,'object':obj}
 return out

def ancestor(root,old,new):
 subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor',old,new],check=True)

def one(kind,own,merge,map_name):
 root=F/kind;stage=json.loads((F/map_name).read_bytes());base=stage['base'];expected=stage['entries']
 ancestor(root,base,own);ancestor(root,own,merge)
 own_parents=git(root,'rev-list','--parents','-n','1',own).decode().split()[1:];assert own_parents==[base]
 merge_parents=git(root,'rev-list','--parents','-n','1',merge).decode().split()[1:];assert len(merge_parents)==2 and own in merge_parents;first=merge_parents[0];ancestor(root,base,first)
 base_tree=tree(root,base);own_tree=tree(root,own);first_tree=tree(root,first);final_tree=tree(root,merge)
 changed=lambda before,after:{k for k in set(before)|set(after) if before.get(k)!=after.get(k)}
 assert changed(base_tree,own_tree)==set(expected)
 assert changed(first_tree,final_tree)==set(expected)
 for path,pin in expected.items():
  for objmap in (own_tree,final_tree):
   assert objmap[path]['mode']==pin['mode'] and objmap[path]['object']==pin['git_object']
   if pin['mode']!='160000':
    raw=git(root,'show',merge+':'+path);assert sha(raw)==pin['sha256'] and len(raw)==pin['bytes']
  if pin['status']=='A':assert path not in base_tree and path not in first_tree
  else:assert pin['status']=='M' and path=='external/ipfs_datasets'
 permitted_modified={k for k,v in expected.items() if v['status']=='M'}
 assert all(final_tree[k]==v for k,v in first_tree.items() if k not in permitted_modified)
 links={k:{'first_parent':v['object'],'merged':final_tree[k]['object'],'changed':v!=final_tree[k]} for k,v in first_tree.items() if v['mode']=='160000'}
 preserved={}
 if kind=='datasets':
  for module,pin in json.loads((F/'retained-owner-pins.json').read_bytes()).items():
   path=Path(pin['path']).relative_to(root).as_posix();raw=git(root,'show',merge+':'+path);assert sha(raw)==pin['sha256'] and len(raw)==pin['bytes'];preserved[path]=pin['sha256']
 else:
  assert len(links)==9 and sum(v['changed'] for v in links.values())==1 and links['external/ipfs_datasets']['changed']
  ancestor(F/'datasets',links['external/ipfs_datasets']['first_parent'],links['external/ipfs_datasets']['merged'])
 return {'kind':kind,'own_commit':own,'merge_commit':merge,'base':base,'merge_parents':merge_parents,'expected_changed_paths':len(expected),'all_expected_objects_exact':True,'all_existing_first_parent_paths_preserved_except_source_gitlink':True,'gitlinks':links,'retained_source_owners':preserved,'staged_map_sha256':sha((F/map_name).read_bytes())}

def main():
 p=argparse.ArgumentParser();p.add_argument('--source-own',required=True);p.add_argument('--source-merge',required=True);p.add_argument('--root-own');p.add_argument('--root-merge');p.add_argument('--output',required=True);a=p.parse_args()
 out={'schema':'formal-output-git-object-integration-audit/v1','passed':True,'findings':[],'source':one('datasets',a.source_own,a.source_merge,'source-staged-map-v01.json')}
 if a.root_own or a.root_merge:
  assert a.root_own and a.root_merge
  out['root']=one('workspace',a.root_own,a.root_merge,'root-staged-map-v01.json')
  assert out['root']['gitlinks']['external/ipfs_datasets']['merged']==a.source_merge
 with Path(a.output).open('x') as s:json.dump(out,s,indent=2,sort_keys=True);s.write('\n');s.flush();os.fsync(s.fileno())
 print(json.dumps({'passed':True,'source_merge':a.source_merge,'root_merge':a.root_merge}))
if __name__=='__main__':main()
