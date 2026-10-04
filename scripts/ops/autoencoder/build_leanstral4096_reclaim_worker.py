#!/usr/bin/env python3
"""Compile only the V3 worker against authenticated existing private CPU libraries.

The caller reserves resources. No backend rebuild, model open, or encoder call.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time

PROFILE='leanstral4096:cpu1:last:l2:single-sequence:tokens512:layer-reclaim:v3'
OLD_PROFILE='leanstral4096:cpu1:last:l2:single-sequence:tokens512:lazy-mmap:v2'
NATIVE='ipfs_datasets_py/logic/formalization/autoencoder/native'
WORKER=NATIVE+'/leanstral4096_layer_reclaim_worker.cpp'
HEADER=NATIVE+'/readonly_model_reclaim.hpp'

def require(ok,message):
 if not ok:raise ValueError(message)

def metadata(path):
 path=Path(path);require(path.is_file() and not path.is_symlink(),'regular authenticated file required')
 before=path.stat();h=hashlib.sha256()
 with path.open('rb') as stream:
  for data in iter(lambda:stream.read(1<<20),b''):h.update(data)
 after=path.stat()
 require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
         (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),'input changed while hashing')
 return {'path':str(path.resolve()),'bytes':after.st_size,'sha256':h.hexdigest()}

def checked(path,expected):
 actual=metadata(path);require(actual==expected,'authenticated artifact differs: '+str(path));return actual

def read_bound(path,sha):
 item=metadata(path);require(item['sha256']==sha,'manifest hash differs')
 raw=Path(path).read_bytes();require(hashlib.sha256(raw).hexdigest()==sha and len(raw)==item['bytes'],'manifest changed before parse')
 return json.loads(raw),item

def save(path,value):
 with Path(path).open('x') as stream:json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')

def validate_parent(value):
 require(type(value) is dict and value.get('schema')=='native-source4096-lazy-worker-build/v1' and value.get('complete') is True,'complete authenticated private build required')
 require(value.get('profile')==OLD_PROFILE and value.get('source_revision')=='571d0d540df04f25298d0e159e520d9fc62ed121','exact pinned lazy backend required')
 for key in ('model_loader_prefetch','mmap_populate','cpu_extra_buffers','worker_executed','model_opened','model_weights_loaded','encoder_executed','downloads_performed','shared_native_source_or_service_modified'):
  require(value.get(key) is False,'private backend safety contract differs: '+key)
 require(value.get('private_backend') is True and value.get('native_libraries_external_and_required') is True,'private CPU library ownership required')
 backend=Path(value['native_root'])/'source/llama.cpp/ggml/src/ggml-backend.cpp'
 require(metadata(backend)['sha256']=='a96b54377e2b66732dcc5ed7ede82b6e0e873de53d515ac9fd6aa118b716bdd3','exact CPU buffer identity implementation required')
 context=Path(value['native_root'])/'source/llama.cpp/src/llama-context.cpp'
 require(metadata(context)['sha256']=='7e5a6656cf1b4b24c6bc825d90fcab4c0aab677c53a868f51a61c742b8361c76','exact performance-counter implementation required')
 checked(value['source_inventory']['path'],value['source_inventory'])
 inventory,_=read_bound(value['source_inventory']['path'],value['source_inventory']['sha256'])
 require(inventory['files']['src/llama-context.cpp']['sha256']==metadata(context)['sha256'],'native source inventory differs')
 require(inventory['files']['ggml/src/ggml-backend.cpp']['sha256']==metadata(backend)['sha256'],'CPU buffer source inventory differs')
 require(value['patch']['substitution_count']==1 and value['patch']['new_literal']=='ml.init_mappings(false, use_mlock ? &pimpl->mlock_mmaps : nullptr);','exact lazy mapping patch required')
 require(type(value['native_libraries']) is dict and value['native_libraries'],'native libraries absent')
 for path,item in value['native_libraries'].items():
  require('cuda' not in Path(path).name and Path(path).is_relative_to(Path(value['native_root'])/'build/bin'),'foreign native library')
  checked(path,item)
 checked(value['compiler']['path'],value['compiler'])
 for path,item in value['compiler_dependencies'].items():checked(path,item)

def dependency_arguments(command,worker,output):
 # Optimization, macro definitions and -pthread alter the preprocessor closure.
 # Keep the real compiler flags; replace only dependency/output control switches.
 prefix=command[:command.index(str(worker))]
 index=prefix.index('-MD');require(prefix[index+1]=='-MF','expected compiler dependency flags')
 prefix=prefix[:index]+prefix[index+3:]
 return prefix+['-M','-MF',str(Path(output)/'before.d'),str(worker),'-pthread']

def build(output_dir,source_root,parent_manifest,parent_sha256,maximum_seconds=120):
 require(type(maximum_seconds) is int and 1<=maximum_seconds<=120,'bounded compiler deadline required')
 started=time.monotonic();deadline=started+maximum_seconds
 parent,parent_pin=read_bound(parent_manifest,parent_sha256);validate_parent(parent)
 root=Path(source_root).resolve();output=Path(output_dir).absolute()
 require(not output.exists() and not output.is_symlink(),'fresh compiler output required')
 sources={str(root/path):metadata(root/path) for path in (WORKER,HEADER)}
 output.mkdir(parents=True,exist_ok=False);(output/'tmp').mkdir()
 for path in (WORKER,HEADER):shutil.copyfile(root/path,output/Path(path).name)
 native=Path(parent['native_root'])/'source/llama.cpp';libraries=Path(parent['native_root'])/'build/bin'
 worker=output/Path(WORKER).name;binary=output/'leanstral4096-layer-reclaim-worker'
 command=[parent['compiler']['path'],'-std=c++17','-O2','-Wall','-Wextra','-Wpedantic','-MD','-MF',str(output/'worker.d'),
          '-DOWNER_SOURCE_SHA256="'+sources[str(root/WORKER)]['sha256']+'"',
          '-I'+str(native/'include'),'-I'+str(native/'ggml/include'),'-I'+str(native/'vendor/nlohmann'),
          str(worker),'-o',str(binary),'-L'+str(libraries),'-Wl,-rpath,'+str(libraries),
          '-lllama','-lggml','-lggml-cpu','-lggml-base','-lcrypto','-pthread']
 environment={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C','TMPDIR':str(output/'tmp'),'CUDA_VISIBLE_DEVICES':'',
              'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
 dependency_command=dependency_arguments(command,worker,output)
 remaining=deadline-time.monotonic();require(remaining>0,'compiler deadline expired before dependency discovery')
 subprocess.run(dependency_command,cwd=output,env=environment,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=remaining,check=True)
 dependency_raw=(output/'before.d').read_text().replace('\\\n','')
 require(':' in dependency_raw,'precompile dependency list missing')
 before_dependencies={str(Path(path).resolve()):metadata(path) for path in shlex.split(dependency_raw.split(':',1)[1])}
 for path,item in before_dependencies.items():
  if path in parent['compiler_dependencies']:require(item==parent['compiler_dependencies'][path],'inherited compiler dependency drifted')
  else:require(path in (str(worker),str(output/Path(HEADER).name)) or path.startswith('/usr/include/') or path.startswith('/usr/lib/gcc/'),'unexpected new compiler dependency')
 remaining=deadline-time.monotonic();require(remaining>0,'compiler deadline expired before launch')
 with (output/'compile.log').open('xb') as log:
  process=subprocess.run(command,cwd=output,env=environment,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,timeout=remaining,check=False)
 require(process.returncode==0,'worker compilation failed; retained compile.log')
 require(time.monotonic()<deadline,'compiler deadline expired')
 for path,item in sources.items():checked(path,item)
 checked(parent_manifest,parent_pin);validate_parent(parent)
 raw=(output/'worker.d').read_text().replace('\\\n','');require(':' in raw,'compiler dependency list missing')
 dependencies={str(Path(path).resolve()):metadata(path) for path in shlex.split(raw.split(':',1)[1])}
 require(dependencies==before_dependencies,'compiler dependency inventory changed during compilation')
 result={'schema':'native-source4096-layer-reclaim-worker-build/v1','complete':True,'profile':PROFILE,
         'parent_build':parent_pin,'native_root':parent['native_root'],'backend_rebuilt':False,
         'backend_cpu_buffer_source':metadata(Path(parent['native_root'])/'source/llama.cpp/ggml/src/ggml-backend.cpp'),
         'backend_context':metadata(Path(parent['native_root'])/'source/llama.cpp/src/llama-context.cpp'),
         'worker_source_sha256':sources[str(root/WORKER)]['sha256'],'executable':metadata(binary),
         'copied_source':metadata(worker),'copied_header':metadata(output/Path(HEADER).name),
         'inputs':sources,'compiler':parent['compiler'],'compiler_dependencies':dependencies,
         'native_libraries':parent['native_libraries'],'command':command,'dependency_command':dependency_command,'environment':environment,
         'compile_log':metadata(output/'compile.log'),'build_helper':metadata(__file__),
         'elapsed_seconds':time.monotonic()-started,'maximum_seconds':maximum_seconds,
         'model_opened':False,'worker_executed':False,'encoder_executed':False,'model_weights_loaded':False,
         'downloads_performed':False,'shared_native_source_or_service_modified':False,'shared_filecache_eviction':False,
         'qualified':False,'admitted':False}
 save(output/'build-manifest.json',result);save(output/'summary.json',result);return result

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--output-dir',type=Path,required=True);parser.add_argument('--source-root',type=Path,required=True)
 parser.add_argument('--parent-manifest',type=Path,required=True);parser.add_argument('--parent-sha256',required=True)
 parser.add_argument('--maximum-seconds',type=int,default=120)
 parser.add_argument('--require-cgroup-memory-max',type=int);args=parser.parse_args()
 if args.require_cgroup_memory_max is not None:
  require(args.require_cgroup_memory_max==1024**3,'fixed worker-only compiler memory bound required')
  relative=Path('/proc/self/cgroup').read_text().strip().split('::',1)[1]
  group=Path('/sys/fs/cgroup')/Path(relative).relative_to('/')
  require(group.name.startswith('native4096-reclaim-build-') and group.name.endswith('.scope'),'owned compiler scope required')
  require(set((group/'cgroup.procs').read_text().split())=={str(os.getpid())},'compiler scope has foreign members')
  require((group/'memory.max').read_text().strip()==str(1024**3) and (group/'memory.swap.max').read_text().strip()=='0','compiler memory bounds differ')
  require((group/'pids.max').read_text().strip()=='16','compiler PID bound differs')
  (group/'memory.oom.group').write_text('1')
  require((group/'memory.oom.group').read_text().strip()=='1','compiler group OOM containment missing')
 build(args.output_dir,args.source_root,args.parent_manifest,args.parent_sha256,args.maximum_seconds)

if __name__=='__main__':main()
