from pathlib import Path
import subprocess,sys,time,json,os,signal
HERE=Path(__file__).resolve().parent
config=json.loads((HERE/'fixture-ownership.json').read_text())
root=Path(config['path']);start=time.monotonic();peak=0;reason=None
log=(HERE/'focused-tests.log').open('xb')
child=subprocess.Popen([sys.executable,'-B',str(HERE/'run_tests.py')],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
while child.poll() is None:
 size=sum(p.stat().st_size for p in root.rglob('*') if p.is_file() and not p.is_symlink());peak=max(peak,size)
 if size>config['max_bytes'] or time.monotonic()-start>config['max_seconds']:
  reason='storage' if size>config['max_bytes'] else 'time';os.killpg(child.pid,signal.SIGTERM)
  try:child.wait(timeout=5)
  except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
  break
 time.sleep(.25)
child.wait();log.close()
config.update(returncode=child.returncode,elapsed_seconds=time.monotonic()-start,peak_sampled_bytes=peak,final_bytes=sum(p.stat().st_size for p in root.rglob('*') if p.is_file() and not p.is_symlink()),stopped_reason=reason)
(HERE/'bounded-tests-receipt.json').write_text(json.dumps(config,indent=2)+'\n')
print(json.dumps(config,sort_keys=True))
raise SystemExit(child.returncode)
