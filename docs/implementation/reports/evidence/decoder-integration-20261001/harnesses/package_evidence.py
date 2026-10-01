from pathlib import Path
import base64, hashlib, json
import pyarrow.parquet as pq
root = Path.cwd()
base = root/'workspace/test-logs/decoder-integration-20261001'
out = root/'docs/implementation/reports/evidence/decoder-integration-20261001'
out.mkdir(parents=True, exist_ok=True)
originals = []
def data(p):
    b=p.read_bytes();originals.append({'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)});return b
def read(p): return json.loads(data(p))
def default(value):
    if isinstance(value, bytes): return {'__bytes_base64__':base64.b64encode(value).decode()}
    raise TypeError(type(value).__name__)
def write(name,v): (out/name).write_text(json.dumps(v,sort_keys=True,separators=(',',':'),default=default,allow_nan=False)+'\n')
# Exact census rows, formulas and goals; all sources in this smoke are authored.
p=base/'census-final-20261001T0258'
report=read(p/'report.json')
items=[]
for f in sorted(p.rglob('*')):
    if f.is_file() and f.suffix in ('.json','.parquet'):
        if f.suffix=='.json': value=read(f)
        else: data(f);value=pq.read_table(f).to_pylist()
        items.append({'path':str(f.relative_to(p)),'value':value})
write('census.json',{'report':report,'artifacts':items,'scope':'actual canonical working-tree source-only inference/compiler/export/import planning; no uploads or admission'})
old=root/'workspace/census-schema-v4-20261001/historical-v1-report.json'
write('historical-paired-v1.json',read(old))
# Preserve the successfully completed real CLI lifecycle, excluding checkpoint
# parameters, private connection assignments, and gateway tokens.
candidates=[]
for f in Path('/tmp/pytest-of-barberb').glob('pytest-*/test_resource_backed_cli_finis0/state/owner-*/report.json'):
    if 'current' not in str(f):
        v=json.loads(f.read_text())
        if v['jobs'] and all(x['status']=='completed' for x in v['jobs']):candidates.append(f)
assert candidates
f=max(candidates,key=lambda p:p.stat().st_mtime_ns);state=f.parent.parent
fleet={'scope':'actual two-process Quack and DuckDB owner; isolated test scheduler/resource ledger, actual hardware probes and Lake; authored native reconstruction fixtures',
       'owner_runs':[read(x) for x in sorted(state.glob('owner-*/report.json'))], 'workers':[]}
for d in sorted((state/'attempts').iterdir()):
    if not (d/'worker.json').exists():continue
    result=read(d/'result.json')
    training={k:v for k,v in result['report'].items() if k not in {'epoch_reports','batch_losses'}}
    for key in ['training_before','training_after','selected_tuning']:
        if key in training:training[key]={k:v for k,v in training[key].items() if k!='facets'}
    row={'attempt':d.name,'training_report':training,'checkpoint_digest':result['report']['checkpoint_sha256'],
         'worker_receipt':read(d/'worker.json'),'owner_receipt':read(d/'owner-receipt.json'),
         'worker_schema':read(d/'schema.json'),'owner_schema':read(d/'owner-schema.json'),
         'inference':read(d/'decoded-schema/inference.json'),'owner_inference':read(d/'owner-decoded-schema/inference.json')}
    row['retained_projects']=[]
    for lean in sorted(d.rglob('DecoderSchema.lean')):
        saved={}
        for name in ['DecoderSchema.lean','artifact.json','lake.log','lakefile.lean','lean-toolchain','toolchain.log']:
            q=lean.parent/name
            if q.is_file():
                b=data(q);saved[name]={'text':b.decode(),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
        row['retained_projects'].append({'directory':str(lean.parent.relative_to(d)),'files':saved})
    fleet['workers'].append(row)
write('fleet.json',fleet)
write('originals.json',originals)
print(json.dumps({'files':[(f.name,f.stat().st_size) for f in out.iterdir() if f.is_file()], 'fleet_state':str(state)}))
