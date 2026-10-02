"""Artifact-only qualification runner; leaves native admission policy unchanged."""
import datetime, hashlib, json, os, pathlib, runpy, subprocess, sys, time
ROOTS={'datasets':pathlib.Path('/tmp/ir-release-datasets-20261001'),'accelerate':pathlib.Path('/tmp/ir-release-accelerate-20261001')}
OUT=pathlib.Path(sys.argv[1]).resolve()
TEST='tests/integration/logic/software_contracts/test_codebase_obligation_portfolio.py'
def save(name,value):
    (OUT/name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
def sha(data):return hashlib.sha256(data).hexdigest()
commits={k:subprocess.check_output(['git','-C',str(p),'rev-parse','HEAD'],text=True).strip() for k,p in ROOTS.items()}
blobs={}
for name,root in ROOTS.items():
    for raw in subprocess.check_output(['git','-C',str(root),'ls-tree','-rz',commits[name]]).split(b'\0'):
        if raw:
            meta,path=raw.split(b'\t',1);mode,kind,identity=meta.split()
            if kind==b'blob':blobs[(name,path.decode())]=identity.decode()
def sources():
    rows=[]
    seen=set()
    for module in tuple(sys.modules.values()):
        filename=getattr(module,'__file__',None)
        if not filename:continue
        path=pathlib.Path(filename).resolve()
        if path.suffix!='.py' or path in seen:continue
        for name,root in ROOTS.items():
            if path.is_relative_to(root):
                relative=path.relative_to(root).as_posix();data=path.read_bytes();seen.add(path)
                blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
                rows.append(dict(repository=name,path=relative,bytes=len(data),sha256=sha(data),git_blob=blob,
                    matches_tested_commit=blobs.get((name,relative))==blob))
    # runpy imports the test without retaining a sys.modules entry.
    for name,relative in [('datasets',TEST)]:
        path=ROOTS[name]/relative;data=path.read_bytes()
        blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        rows.append(dict(repository=name,path=relative,bytes=len(data),sha256=sha(data),git_blob=blob,
            matches_tested_commit=blobs.get((name,relative))==blob))
    return sorted(rows,key=lambda r:(r['repository'],r['path']))
os.environ['IPFS_ACCELERATE_PYTEST_SEAL_DUCKDB']=str(OUT/'pytest-seal.duckdb')
os.environ.setdefault('IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI','0')
module=runpy.run_path(str(ROOTS['datasets']/TEST))
producer=module['module']._producer()
tools=module['native_tools']()
before=sources()
# Retain exact approved working bytes independently of a pending Git commit.
accepted={}
def retain(name,relative):
    path=ROOTS[name]/relative;data=path.read_bytes()
    target=OUT/'source-snapshots'/name/relative;target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(data);accepted[(name,relative)]=sha(data)
for row in before:retain(row['repository'],row['path'])
deltas=[]
for name,root in ROOTS.items():
    for relative in subprocess.check_output(['git','-C',str(root),'diff','HEAD','--name-only','--','*.py'],text=True).splitlines():
        if (root/relative).is_file():
            retain(name,relative)
            deltas.append(dict(repository=name,path=relative,sha256=accepted[(name,relative)]))
save('working-source-deltas.json',deltas)
args=['-x','-q','-o','log_cli=false','--basetemp='+str(OUT/'native-temp'),'--junitxml='+str(OUT/'tests.xml'),TEST]
save('module-source-before.json',before);save('tools-before.json',tools);save('portfolio-producer-before.json',producer)
save('invocation.json',dict(schema='codebase-obligation-native-invocation/v1',commits=commits,python=sys.executable,
    pytest_args=args,cwd=str(ROOTS['datasets']),native_default_host=True,telemetry_injected=False,
    concurrent_load='Managed supervisor and federation native qualifications may run concurrently through the shared default host scheduler; elapsed time is not a throughput comparison.',
    runner_sha256=sha(pathlib.Path(__file__).read_bytes()),started_at=datetime.datetime.now(datetime.timezone.utc).isoformat()))
import pytest
started=time.monotonic();code=int(pytest.main(args));elapsed=time.monotonic()-started
finally_sources=sources()
for row in finally_sources:
    key=(row['repository'],row['path'])
    if key not in accepted and row['matches_tested_commit']:
        retain(*key)
all_bound=all(accepted.get((row['repository'],row['path']))==row['sha256'] for row in finally_sources)
save('exact-source-snapshots.json',[dict(repository=k[0],path=k[1],sha256=v) for k,v in sorted(accepted.items())])
tools_after=module['native_tools']();producer_after=module['module']._producer()
first={(r['repository'],r['path']):r for r in before}
unchanged=all(first.get((r['repository'],r['path']),r)==r for r in finally_sources)
save('module-source-after.json',finally_sources);save('tools-after.json',tools_after);save('portfolio-producer-after.json',producer_after)
save('run-result.json',dict(schema='codebase-obligation-native-run/v1',pytest_exit_code=code,elapsed_seconds=elapsed,
    source_pins_unchanged=unchanged,all_loaded_sources_match_exact_snapshots=all_bound,all_loaded_sources_match_tested_commits=all(r['matches_tested_commit'] for r in finally_sources),
    tools_unchanged=tools==tools_after,portfolio_producers_unchanged=producer==producer_after,commits=commits,
    finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),authority_scope='Closed mathematical integer-offset and finite stuttering restriction only; no Python runtime equivalence, task completion or proof cache promotion.'))
sys.exit(code if code else (0 if unchanged and tools==tools_after and producer==producer_after and all_bound else 90))
