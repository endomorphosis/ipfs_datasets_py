"""Copy only independently reviewed, closed evidence into isolated checkouts."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,os
F=Path(__file__).resolve().parent
def pin(path):
 p=Path(path);assert p.is_file() and not p.is_symlink() and p.resolve()==p
 b=p.read_bytes();return {'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
parser=argparse.ArgumentParser();parser.add_argument('kind',choices=['datasets','workspace']);args=parser.parse_args()
inventory_path=F/'contribution-copy-inputs-v01.json';inventory=json.loads(inventory_path.read_bytes())
review=json.loads((F/'contribution-inventory-independent-review-v01.json').read_bytes())
assert review['passed'] is True and review['findings']==[] and review['inventory_pin']==pin(inventory_path) and review['copy_helper_pin']==pin(__file__)
root=F/args.kind
prefix='workspace/test-logs/legal-scope-family-20261011-01/evidence' if args.kind=='datasets' else 'artifacts/legal-scope-family-20261011-01/evidence'
dest=root/prefix;assert not dest.exists() and dest.resolve()==dest
assert type(inventory['entries']) is dict and inventory['entries']
for rel,value in inventory['entries'].items():
 p=PurePosixPath(rel);assert not p.is_absolute() and p.as_posix()==rel and all(v not in ('','.','..') for v in rel.split('/')) and rel.startswith(('local/','prepared/','native-build/'))
 source=Path(value['path']);assert F in source.parents and not any(v in ('datasets','workspace') for v in source.relative_to(F).parts)
 assert pin(source)==value
dest.mkdir(parents=True,exist_ok=False)
for rel,value in inventory['entries'].items():
 target=dest/rel;assert target.resolve()==target and dest in target.parents
 target.parent.mkdir(parents=True,exist_ok=True)
 with target.open('xb') as stream:stream.write(Path(value['path']).read_bytes());stream.flush();os.fsync(stream.fileno())
 assert pin(target)['sha256']==value['sha256'] and target.stat().st_size==value['bytes']
for value in inventory['entries'].values():assert pin(value['path'])==value
print(json.dumps({'kind':args.kind,'copied':len(inventory['entries']),'bytes':sum(v['bytes'] for v in inventory['entries'].values())}))
