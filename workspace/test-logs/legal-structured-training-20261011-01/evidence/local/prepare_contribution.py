"""Copy one reviewed evidence inventory into isolated source/root checkouts.

No weights, full foreign ledgers, Hub identity cache or authored training export
enter Git. These remain local or on the immutable Hub release. Copies are exact,
exclusive and versioned; a late finalization may add only newly reviewed files.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os

F=Path(__file__).resolve().parent
R=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01/structured-probability-20261011-01')
S=F/'datasets/workspace/test-logs/legal-structured-training-20261011-01/evidence'
W=F/'workspace/artifacts/legal-structured-training-20261011-01/evidence'
EXCLUDED={'authored-train-tune-only.json','hf-observed-model-info.json'}
SUFFIXES={'.json','.py','.md','.xml','.log','.jsonl','.stdout','.txt'}

def pin(path):
    assert path.is_absolute() and path.resolve()==path and path.is_file() and not path.is_symlink()
    raw=path.read_bytes();return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def collect():
    inputs={}
    for p in sorted(F.iterdir()):
        if p.is_file() and p.suffix in SUFFIXES and p.name not in EXCLUDED and not p.name.endswith('.local.json') and not p.name.startswith('contribution-copy-'):
            inputs['local/'+p.name]=pin(p)
    for p in sorted(R.rglob('*')):
        if p.is_file() and p.suffix in SUFFIXES and not p.name.endswith('-checkpoint.json'):
            inputs['run/'+p.relative_to(R).as_posix()]=pin(p)
    return inputs

def write(path,value):
    with path.open('x') as s:json.dump(value,s,indent=2,sort_keys=True);s.write('\n');s.flush();os.fsync(s.fileno())

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--inventory');p.add_argument('--output',required=True);a=p.parse_args()
    if a.inventory is None:
        entries=collect();write(Path(a.output),dict(schema='structured-contribution-copy-inventory/v1',entries=entries,
            weight_body_files_excluded=True,foreign_full_ledgers_excluded=True,authored_training_export_excluded=True,
            destination_roots=[str(S),str(W)],file_count=len(entries),bytes=sum(v['bytes'] for v in entries.values())))
        print('Prepared exact inventory',len(entries));return
    inventory=json.loads(Path(a.inventory).read_bytes());entries=inventory['entries'];copied=[]
    for relative,expected in entries.items():
        source=Path(expected['path']);assert pin(source)==expected
        assert not Path(relative).is_absolute() and '..' not in Path(relative).parts
        for root in (S,W):
            target=root/relative;target.parent.mkdir(parents=True,exist_ok=True)
            raw=source.read_bytes()
            if target.exists():assert target.read_bytes()==raw,'existing contribution copy differs'
            else:
                with target.open('xb') as s:s.write(raw);s.flush();os.fsync(s.fileno())
            assert target.read_bytes()==raw;copied.append(dict(relative=relative,destination=str(target),**{k:expected[k] for k in ('bytes','sha256')}))
    assert all(pin(Path(v['path']))==v for v in entries.values())
    write(Path(a.output),dict(schema='structured-contribution-copy-receipt/v1',passed=True,findings=[],
        inventory=pin(Path(a.inventory)),file_count_per_tree=len(entries),copies=copied,
        no_weights_in_Git=True,no_foreign_full_ledger_bodies_in_Git=True,no_original_overwrites=True))
    print('Copied exact reviewed evidence',len(entries),'files to each isolated checkout')

if __name__=='__main__':main()
