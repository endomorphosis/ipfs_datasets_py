"""Read-only ABBA census comparison; no cached filesystem observations."""
from pathlib import Path
import json,time,types,hashlib,sys
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as current
BASE=Path(__file__).resolve().parent
old_text=json.loads((BASE/'sources-before.json').read_text())['ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py']
old=types.ModuleType('resource_inventory_reference');old.__package__=current.__package__;sys.modules[old.__name__]=old
exec(compile(old_text,'captured-prechange-resources.py','exec'),old.__dict__)
ledger=Path('workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json')
roots=[Path(row['path']) for row in json.loads(ledger.read_text())['roots']]
ledger_before=hashlib.sha256(ledger.read_bytes()).hexdigest()
rows=[]
for label,module in [('before',old),('after',current),('after',current),('before',old)]:
 start=time.perf_counter();result=module._inventory(roots);duration=time.perf_counter()-start
 rows.append({'implementation':label,'wall_seconds':duration,'result':result})
static=[]
for label,module in [('before',old),('after',current)]:
 static.append({'implementation':label,'result':module._inventory([BASE/'baseline'])})
x={'schema':'fresh-inventory-abba/v1','rows':rows,'result_equality':all(r['result']==rows[0]['result'] for r in rows),'stable_completed_run_parity':static[0]['result']==static[1]['result'],'stable_completed_run_observations':static,'before_source_sha256':hashlib.sha256(old_text.encode()).hexdigest(),'after_source_sha256':hashlib.sha256(Path(current.__file__).read_bytes()).hexdigest(),'ledger_unchanged':ledger_before==hashlib.sha256(ledger.read_bytes()).hexdigest(),'roots':list(map(str,roots)),'metadata_reused':False,'admitted':False}
assert x['ledger_unchanged'] and x['stable_completed_run_parity']
(BASE/'inventory-abba.json').write_text(json.dumps(x,indent=2)+'\n');print(json.dumps(x))
