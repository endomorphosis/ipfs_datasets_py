"""Read-only guard for staged packs (no Hub/network access; pure file checks).
Fails if any executable file (.py/.sh) in a pack folder contains a Hub write call.
Exception (documented): manifest.json's 'rules' field and README.md may legitimately
mention create_commit / 'hf upload-large-folder' as prose, so README.md and .md files are
not scanned, and manifest.json is scanned with its 'rules' field removed.
Files named *.DISABLED_HAS_UPLOAD are archived originals (not executable) and are skipped."""
import os,re,json,sys
BAD=re.compile(r'create_commit|create_repo|upload_file|upload_folder|delete_|super_squash')
# Manifest sanitiser check (CoS rule): no '@' (except repo@<hex sha> refs), no /Users|/workspace|/home paths,
# no 6+ digit runs (except sha hex and numeric row/count fields), no free-text context fields.
CTXKEYS={'ctx','context','sample','samples','snippet','excerpt','text','match','matched','value','before','after','preview'}
NUMOK={'row','rows','rows_before','count','rows_source','size','secret_hits','data_secret_scan_hits','readme_secret_scan_hits'}
CNTPARENT={'quality','dropped_by_reason','by_kind','hits','natid_hits','fail','scan_v2','scan_v3'}
REF=re.compile(r'[A-Za-z0-9_./-]+@[0-9a-f]{7,40}\b')
HEX=re.compile(r'\b[0-9a-f]{40}\b|\b[0-9a-f]{64}\b')
def manifest_problems(m):
  out=[]
  def w(o,path,parents):
    if isinstance(o,dict):
      for k,v in o.items():
        if k in CTXKEYS: out.append(f'context field {path}.{k}')
        else: w(v,f'{path}.{k}',parents+[k])
    elif isinstance(o,list):
      for i,v in enumerate(o): w(v,f'{path}[{i}]',parents)
    elif isinstance(o,bool) or o is None: pass
    elif isinstance(o,(int,float)):
      if len(re.sub(r'\D','',str(o)))>=6 and not (parents and parents[-1] in NUMOK) and not any(p in CNTPARENT for p in parents): out.append(f'6+ digit number at {path}')
    elif isinstance(o,str):
      if path=='$.rules': return
      t=HEX.sub('',REF.sub('',o))
      if '@' in t: out.append(f"bare '@' at {path}")
      if re.search(r'/Users/|/workspace/|/home/',o): out.append(f'local path at {path}')
      if re.search(r'\d{6,}',t): out.append(f'6+ digit run at {path}')
  w(m,'$',[]);return out
def check_pack(d):
  hits=[]
  for a,_,fs in os.walk(d):
    for f in fs:
      p=os.path.join(a,f)
      if f.endswith(('.py','.sh')):
        for i,l in enumerate(open(p,errors='replace'),1):
          if BAD.search(l): hits.append(f'{p}:{i}: {BAD.search(l).group(0)}')
      elif f=='manifest.json' and a==d:
        m=json.load(open(p));m.pop('rules',None)
        s=json.dumps(m)
        for x in set(BAD.findall(s)): hits.append(f'{p}: {x} outside rules field')
        hits+=[f'{p}: SANITISE {e}' for e in manifest_problems(json.load(open(p)))]
  return hits
if __name__=='__main__':
  bad=[h for d in sys.argv[1:] for h in check_pack(d)]
  print('\n'.join(bad) or 'GUARD_OK');sys.exit(3 if bad else 0)
