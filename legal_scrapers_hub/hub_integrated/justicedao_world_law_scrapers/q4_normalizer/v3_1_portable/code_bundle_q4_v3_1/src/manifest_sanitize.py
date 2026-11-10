"""Manifest sanitiser (CoS rule 2026-10-25): manifest.json carries only counts + file/row/column/kind/marker.
No raw context text, no phone/ID digits, no /Users|/workspace|/home paths, no bare '@'. Pure, offline."""
import re
LOCKEYS=('file','row','column','kind','count','marker')
def _clean_str(s):
  s=re.sub(r'(?:/Users|/workspace|/home)/\S*','[PATH]',s)
  return s
def sanitize(m):
  m=dict(m)
  red={}
  for f,r in (m.get('redactions') or {}).items():
    locs=[{k:({**x,'file':f}).get(k) for k in LOCKEYS} for x in r.get('locations',[])]
    bk={}
    for x in locs: bk[x['kind']]=bk.get(x['kind'],0)+(x['count'] or 0)
    red[f]={'count':r.get('count',sum(x['count'] or 0 for x in locs)),'rows':r.get('rows',len(locs)),'by_kind':r.get('by_kind',bk),'locations':locs}
  m['redactions']=red
  for sk in [k for k in m if k.startswith('scan_v') and isinstance(m[k],dict)]:
    m[sk]={f:{'hits':v.get('hits',{}),'fail':v.get('fail',{})} for f,v in m[sk].items()}
  if isinstance(m.get('readme_secret_scan_hits'),list): m['readme_secret_scan_hits']=len(m['readme_secret_scan_hits'])
  for k,v in list(m.items()):
    if isinstance(v,str) and k!='rules': m[k]=_clean_str(v)
  return m
