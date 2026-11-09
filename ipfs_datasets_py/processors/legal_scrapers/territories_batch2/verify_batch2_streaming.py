"""Use the existing /workspace/venv datasets runtime; no installs or deletes."""
import os,sys,pathlib,tempfile,json,resource,time
R=pathlib.Path('/workspace/staging/territories_batch2_20261105');mem=int(pathlib.Path('/proc/meminfo').read_text().split('MemAvailable:')[1].split()[0])/1024**2
if mem<4.2:raise SystemExit('MEMORY_START_HOLD')
tmp=R/'validation_runtime';tmp.mkdir(parents=True,exist_ok=True);tempfile.tempdir=str(tmp)
os.environ.update(HF_DATASETS_CACHE=str(tmp/'datasets_cache'),HF_HUB_CACHE=str(tmp/'hub_cache'),HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',USE_TORCH='0',USE_TF='0',USE_JAX='0')
def no_delete(event,args):
 if event in ['os.remove','os.rmdir','os.rename']:raise RuntimeError('ZERO_DELETE_REPLACE_GUARD')
sys.addaudithook(no_delete)
import datasets,pyarrow.parquet as pq
results=[]
for code in ['CX','CC','HM','BQ','TK','MP','VI','SJ','BV','AQ']:
 paths=[R/code/'upload_ready_v2',R/code/'upload_ready'];ready=next((p for p in paths if p.is_dir() and (p/'data').is_dir() and not (p/'HOLD_DO_NOT_UPLOAD.md').exists()),None)
 if ready is None:continue
 for p in sorted((ready/'data').glob('*.parquet')):
  if int(pathlib.Path('/proc/meminfo').read_text().split('MemAvailable:')[1].split()[0])/1024**2<3.2:raise SystemExit('MEMORY_STOP_HOLD')
  rows=pq.read_metadata(p).num_rows
  if rows<=0:raise SystemExit('ZERO_ROW_PARQUET_HOLD '+str(p))
  ds=datasets.load_dataset('parquet',data_files=str(p),split='train',streaming=True);count=0
  for record in ds:
   count+=1
   if count%1000==0 and resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024>290:raise SystemExit('RSS_HOLD')
  if count!=rows:raise SystemExit('ROW_COUNT_MISMATCH')
  result={'territory':code,'path':str(p),'pyarrow_rows':rows,'datasets_streaming_rows':count,'datasets_version':datasets.__version__};results.append(result);print('VERIFIED',result,flush=True)
  sidecar=ready/('streaming_validation_'+p.stem+'.json')
  with sidecar.open('x') as f:json.dump(result,f,indent=2)
with (R/'verified_datasets_streaming.json').open('x') as f:json.dump({'results':results,'peak_rss_mb':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'completed_local':time.strftime('%Y-%m-%d %H:%M:%S %Z')},f,indent=2)
print('VALIDATION_DONE',resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,flush=True)
