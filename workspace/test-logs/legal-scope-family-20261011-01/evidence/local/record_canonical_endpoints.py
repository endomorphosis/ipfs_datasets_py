"""Read and compare canonical checkout HEAD/index endpoints; never refresh indexes."""
from pathlib import Path
import argparse,subprocess,hashlib,json,os
F=Path(__file__).resolve().parent;ROOT=F.parents[1]
def pin(p):
 p=Path(p);assert p.is_file() and not p.is_symlink() and p.resolve()==p
 b=p.read_bytes();return {'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
def git(p,*a):return subprocess.check_output(['git','--no-optional-locks','-C',str(p),*a]).decode().strip()
p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
old=json.loads((F/'canonical-intake.json').read_bytes());now={}
for k,root in [('root',ROOT),('datasets',ROOT/'external/ipfs_datasets')]:
 now[k]={'head':git(root,'rev-parse','HEAD'),'symbolic_head':git(root,'symbolic-ref','HEAD'),'index':pin(old[k]['index']['path'])}
assert now==old
v={'schema':'scope-native-canonical-endpoints/v1','passed':True,'findings':[],'before':old,'after':now,'exact_head_symbolic_head_and_index_bytes':True,'canonical_worktrees_mutated':False,'continuous_custody_claimed':False,'helper_pin':pin(__file__)}
with Path(a.output).open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
print('Canonical HEAD/index endpoints match intake exactly')
