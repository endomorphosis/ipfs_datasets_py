"""Read-only, bounded named-root metadata census. No resource clients/imports."""
from pathlib import Path
from collections import defaultdict
import hashlib, heapq, json, os, stat, time

OUT=Path('/home/barberb/lift_coding/artifacts/legal-storage-recovery-20261012-01')
ROOTS=[Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs'),Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/todo-queues'),Path('/home/barberb/lift_coding/external/ipfs_datasets/docs/implementation/reports/evidence'),Path('/tmp/pytest-of-barberb')]
started=time.time(); deadline=time.monotonic()+150
report={'schema':'legal-storage-named-root-metadata/v1','started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'read_only':True,'scope':'four named roots only; lstat each regular/symlink/special pathname, exclude directories; no symlink descent','limit_entries':2_000_000,'maximum_elapsed_seconds':150,'apparent_bytes':0,'entry_count':0,'roots':[],'disappeared_entries':0,'errors':[]}
links={}; largest=[]; maxheap=100; first={}; second={}
for root in ROOTS:
 st=root.lstat(); before={'path':str(root),'device':st.st_dev,'inode':st.st_ino}
 if not stat.S_ISDIR(st.st_mode): raise RuntimeError('named root not ordinary directory')
 row={**before,'apparent_bytes':0,'entry_count':0,'regular_files':0,'directory_count':0,'directory_apparent_bytes_excluded':0,'symlink_count':0,'symlink_bytes':0,'special_file_count':0,'hardlinked_path_count':0,'hardlinked_path_bytes':0,'first_level':[],'second_level':[]}
 one=defaultdict(lambda:{'apparent_bytes':0,'regular_files':0,'symlinks':0,'hardlinked_path_count':0,'hardlinked_path_bytes':0})
 two=defaultdict(lambda:{'apparent_bytes':0,'regular_files':0,'symlinks':0,'hardlinked_path_count':0,'hardlinked_path_bytes':0})
 pending=[root]
 while pending:
  if time.monotonic()>deadline: raise TimeoutError('metadata census deadline exceeded')
  directory=pending.pop()
  try:
   ds=directory.lstat()
   if not stat.S_ISDIR(ds.st_mode):
    raise RuntimeError('directory replaced or symlink refused: '+str(directory))
   with os.scandir(directory) as entries:
    for entry in entries:
     report['entry_count']+=1;row['entry_count']+=1
     if report['entry_count']>report['limit_entries']:raise RuntimeError('metadata entry bound exceeded')
     try: info=entry.stat(follow_symlinks=False)
     except FileNotFoundError:
      report['disappeared_entries']+=1;continue
     path=Path(entry.path); rel=path.relative_to(root);parts=rel.parts
     firstkey=parts[0] if len(parts)>1 else '(root files)'
     secondkey='/'.join(parts[:2]) if len(parts)>2 else '/'.join(parts[:-1])+'/(direct files)'
     if stat.S_ISDIR(info.st_mode):
      row['directory_count']+=1;row['directory_apparent_bytes_excluded']+=info.st_size;pending.append(path);continue
     size=info.st_size;row['apparent_bytes']+=size;report['apparent_bytes']+=size
     one[firstkey]['apparent_bytes']+=size;two[secondkey]['apparent_bytes']+=size
     if stat.S_ISREG(info.st_mode):
      row['regular_files']+=1;one[firstkey]['regular_files']+=1;two[secondkey]['regular_files']+=1
      if info.st_nlink>1:
       row['hardlinked_path_count']+=1;row['hardlinked_path_bytes']+=size
       for bucket in (one[firstkey],two[secondkey]):bucket['hardlinked_path_count']+=1;bucket['hardlinked_path_bytes']+=size
       key=(info.st_dev,info.st_ino)
       value=links.setdefault(key,{'device':info.st_dev,'inode':info.st_ino,'bytes':size,'nlink_observed':info.st_nlink,'path_count':0,'sample_paths':[]})
       if size!=value['bytes']:report['errors'].append({'reason':'hardlink size changed during census','path':str(path)})
       value['path_count']+=1
       if len(value['sample_paths'])<5:value['sample_paths'].append(str(path))
      item=(size,str(path),info.st_nlink,info.st_dev,info.st_ino,info.st_blocks*512,info.st_mtime_ns)
      if len(largest)<maxheap:heapq.heappush(largest,item)
      elif item>largest[0]:heapq.heapreplace(largest,item)
     elif stat.S_ISLNK(info.st_mode):
      row['symlink_count']+=1;row['symlink_bytes']+=size;one[firstkey]['symlinks']+=1;two[secondkey]['symlinks']+=1
     else:row['special_file_count']+=1
  except FileNotFoundError:report['disappeared_entries']+=1
  current=root.lstat()
  if (current.st_dev,current.st_ino)!=(before['device'],before['inode']):raise RuntimeError('named root identity changed')
 row['first_level']=[{'relative_path':key,**value} for key,value in sorted(one.items(),key=lambda kv:kv[1]['apparent_bytes'],reverse=True)]
 row['second_level']=[{'relative_path':key,**value} for key,value in sorted(two.items(),key=lambda kv:kv[1]['apparent_bytes'],reverse=True)[:60]]
 row['identity_stable_at_end']=True
 report['roots'].append(row)
seen_aliases=sum(max(0,x['path_count']-1)*x['bytes'] for x in links.values())
report['hardlink_observation']={'distinct_linked_inodes_seen':len(links),'hardlinked_paths_seen':sum(x['path_count'] for x in links.values()),'extra_apparent_bytes_due_to_observed_alias_pathnames':seen_aliases,'largest_alias_groups':[x for x in sorted(links.values(),key=lambda x:max(0,x['path_count']-1)*x['bytes'],reverse=True)[:30]],'all_regular_file_paths_charged':True,'physical_freeing_warning':'unlinking one pathname of an inode with remaining hard links generally releases no file-data blocks; deleting paths still changes lineage and may violate evidence custody'}
report['largest_regular_files']=[{'path':p,'bytes':size,'nlink':n,'device':d,'inode':i,'allocated_bytes':b,'mtime_ns':m} for size,p,n,d,i,b,m in sorted(largest,reverse=True)]
report['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime());report['elapsed_seconds']=time.time()-started
report['limitations']=['sequential metadata snapshots, not a locked or atomic census','root identities checked, descendants may churn; disappearance count recorded','directory st_size excluded to match owner accounting; du directory sizes differ','file contents not opened and no artifacts deleted, moved, compacted or released','no source authority, training admission, retention eligibility or historical immutability conclusion from size alone']
p=OUT/'named-root-metadata-census-v02.json';p.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'output':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'total_apparent_bytes':report['apparent_bytes'],'entries':report['entry_count'],'elapsed_seconds':report['elapsed_seconds'],'disappeared_entries':report['disappeared_entries'],'errors':report['errors'],'root_totals':[(r['path'],r['apparent_bytes']) for r in report['roots']],'extra_hardlink_pathname_bytes':seen_aliases},indent=2))
