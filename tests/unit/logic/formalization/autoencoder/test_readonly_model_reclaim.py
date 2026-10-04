"""Tiny Linux mmap fixtures only; no model/backend/encoder execution."""
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

P=Path(__file__).resolve().parents[5]
HEADER=P/'ipfs_datasets_py/logic/formalization/autoencoder/native/readonly_model_reclaim.hpp'
WORKER=HEADER.with_name('leanstral4096_layer_reclaim_worker.cpp')
CPP=r'''
#include "readonly_model_reclaim.hpp"
#include <iostream>
#include <cstring>
using namespace readonly_model_reclaim;
int main(int argc,char **argv) {
 try {
  check(argc>=2,"mode required");std::string mode=argv[1];
  if(mode=="account") {
   check(argc==7,"account args required");
   auto result=account_single_reset_decode(std::stoi(argv[2]),std::stoi(argv[3]),std::stoi(argv[4]),std::stod(argv[5]),std::stod(argv[6]));
   std::cout<<result.prompt<<' '<<result.single<<' '<<result.dispatch<<'\n';return 0;
  }
  if(mode=="parse") {
   struct stat st{};st.st_dev=makedev(8,2);st.st_ino=123;st.st_size=8191;
   std::string raw,line;while(std::getline(std::cin,line)){raw+=line;raw+='\n';}
   const auto result=parse_maps(raw,st,4096);std::cout<<result.size()<<'\n';return 0;
  }
  if(mode=="layer") {
   check(argc==4,"layer args required");auto index=layer_index(argv[2]);
   check_next_layer(index,std::stoul(argv[3]));std::cout<<index<<'\n';return 0;
  }
  check(argc==3,"fixture path required");const std::size_t size=16*1024*1024;
  const std::string path=argv[2];
  int writer=open(path.c_str(),O_CREAT|O_EXCL|O_RDWR,0600);check(writer>=0,"fixture create failed");
  check(ftruncate(writer,size)==0,"fixture sizing failed");
  std::vector<unsigned char> expected(size);for(std::size_t i=0;i<size;++i)expected[i]=static_cast<unsigned char>(i*31+7);
  memcpy(expected.data(),"GGUF",4);check(pwrite(writer,expected.data(),size,0)==static_cast<ssize_t>(size),"fixture write failed");
  int fd=open(path.c_str(),O_RDONLY);check(fd>=0,"readonly fixture open failed");
  if(mode=="writable-fd") {Reclaimer invalid(writer);return 0;}
  close(writer);
  int flags=mode=="private-map"?MAP_PRIVATE:MAP_SHARED;
  void * mapped=mmap(nullptr,size,PROT_READ,flags,fd,0);check(mapped!=MAP_FAILED,"fixture map failed");
  if(mode=="missing-magic") {int w=open(path.c_str(),O_WRONLY);check(pwrite(w,"BAD!",4,0)==4,"magic write failed");close(w);}
  Reclaimer reclaim(fd);
  if(mode=="changed-file") {int w=open(path.c_str(),O_WRONLY);check(pwrite(w,"!",1,100)==1,"mutation failed");close(w);reclaim.reclaim();return 0;}
  if(mode=="changed-map") {check(munmap(mapped,size)==0,"unmap failed");reclaim.reclaim();return 0;}
  if(mode=="writable-map") {check(mprotect(mapped,size,PROT_READ|PROT_EXEC)==0,"protect failed");reclaim.reclaim();return 0;}
  if(mode=="closed-fd") {close(fd);reclaim.reclaim();return 0;}
  check(mode=="roundtrip","unknown mode");
  std::uint64_t drops=0;for(int repeat=0;repeat<2;++repeat) {
   check(memcmp(mapped,expected.data(),size)==0,"initial mapped bytes differ");
   const auto event=reclaim.reclaim();check(event.syscalls==1,"exact one owned mapping expected");
   if(event.rss_before_bytes>event.rss_after_bytes)drops+=event.rss_before_bytes-event.rss_after_bytes;
   check(memcmp(mapped,expected.data(),size)==0,"reclaimed bytes differ");
  }
  check(drops>0,"fixture did not demonstrate own RSS reduction");
  std::vector<unsigned char> actual(size);check(pread(fd,actual.data(),size,0)==static_cast<ssize_t>(size),"fixture reread failed");
  check(actual==expected,"file bytes changed");
  std::cout<<"{\"repeats\":2,\"bytes_equal\":true,\"file_unchanged\":true,\"own_rss_drop_bytes\":"<<drops<<"}\n";
  munmap(mapped,size);close(fd);return 0;
 } catch(const std::exception &error){std::cerr<<error.what()<<'\n';return 2;}
}
'''

@pytest.fixture(scope='module')
def executable(tmp_path_factory):
 root=tmp_path_factory.mktemp('readonly-reclaim');source=root/'fixture.cpp';source.write_text(CPP)
 binary=root/'fixture'
 subprocess.run(['/usr/bin/g++','-std=c++17','-O1','-Wall','-Wextra','-Werror',f'-I{HEADER.parent}',str(source),'-o',str(binary)],check=True,capture_output=True,timeout=60)
 return binary

def run(executable,*args,input=None):
 return subprocess.run([str(executable),*map(str,args)],input=input,capture_output=True,text=True,timeout=10)

def test_two_real_readonly_shared_reclaims_preserve_every_byte(executable,tmp_path):
 result=run(executable,'roundtrip',tmp_path/'tiny.gguf');assert result.returncode==0,result.stderr
 receipt=json.loads(result.stdout)
 assert receipt['repeats']==2 and receipt['bytes_equal'] and receipt['file_unchanged']
 assert receipt['own_rss_drop_bytes']>0

@pytest.mark.parametrize('mode',['writable-fd','private-map','missing-magic','changed-file','changed-map','writable-map','closed-fd'])
def test_rejects_unsafe_real_mapping_or_identity(executable,tmp_path,mode):
 result=run(executable,mode,tmp_path/'fixture.gguf')
 assert result.returncode==2 and result.stderr

@pytest.mark.parametrize('row',[
 '1000-3000 r--s 0000 08:02 123 /tiny.gguf',
 '1000-2000 r--s 0000 08:02 123 /tiny.gguf\n3000-4000 r--s 1000 08:02 123 /tiny.gguf',
])
def test_accepts_exact_held_inode_fragments_and_last_padded_page(executable,row):
 result=run(executable,'parse',input=row);assert result.returncode==0,result.stderr

@pytest.mark.parametrize('row',[
 '', '1000-3000 r--p 0000 08:02 123 /tiny.gguf',
 '1000-3000 rw-s 0000 08:02 123 /tiny.gguf',
 '1000-3000 r-xs 0000 08:02 123 /tiny.gguf',
 '1000-3000 r--s 0000 08:03 123 /tiny.gguf',
 '1000-3000 r--s 0000 08:02 124 /tiny.gguf',
 '1001-3000 r--s 0000 08:02 123 /tiny.gguf',
 '1000-3000 r--s 0001 08:02 123 /tiny.gguf',
 '1000-4000 r--s 0000 08:02 123 /tiny.gguf',
 '1000-3000 r--s 1000 08:02 123 /tiny.gguf',
 '1000-3000 r--s 0000 08:02 123 /tiny.gguf\n4000-6000 r--s 0000 08:02 123 /tiny.gguf',
 '1000-3000 r--s 0000 08:02 123 /tiny.gguf\n2000-3000 r--s 1000 08:02 123 /tiny.gguf',
 '1000-3000 r--s 0000 08:02 +123 /tiny.gguf',
 '1000-3000 r--s 0000 08:02:03 123 /tiny.gguf',
 '0000-2000 r--s 0000 08:02 123 /tiny.gguf',
])
def test_rejects_forged_or_unsafe_mapping_inventory(executable,row):
 assert run(executable,'parse',input=row).returncode==2

@pytest.mark.parametrize('index',[0,1,18,35])
def test_exact_completed_layer_order(executable,index):
 assert run(executable,'layer',f'l_out-{index}',index).returncode==0

@pytest.mark.parametrize('name,count',[('l_out-36',36),('l_out-00',0),('l_out-1',0),('l_out-0',1),('l_out--1',0),('l_out-x',0),('result_norm',0),('l_out-0',36)])
def test_duplicate_missing_malformed_and_out_of_range_layers_abort(executable,name,count):
 assert run(executable,'layer',name,count).returncode==2

def test_callback_latches_failure_and_checks_all_layers_before_reading_output():
 raw=WORKER.read_text();header=HEADER.read_text()
 assert 'noexcept' in raw and 'operation.callback_error=' in raw
 assert 'if (!callback_error.empty()) throw std::runtime_error(callback_error)' in raw
 assert raw.index('const auto reclaim_receipt=reclaim_report(operation)')<raw.index('llama_get_embeddings_seq(context,0)')
 assert 'operation.reclaim_events.size()==36' in raw
 assert 'if (ask || !operation.reclaim_active) return true' in raw
 assert 'check_next_layer(layer,operation.reclaim_events.size())' in raw
 assert 'MAP_SHARED' not in raw  # Model mappings are owned by the already authenticated native backend.
 assert 'MADV_DONTNEED' in header and 'posix_fadvise(' not in header and 'madvise(' not in raw
 assert 'params.use_extra_bufts = false' in raw and 'cp.n_ctx = LIMIT; cp.n_batch = LIMIT; cp.n_ubatch = LIMIT' in raw
 assert 'tokens512:layer-reclaim:v3' in raw and 'native-source4096-worker-description/v3' in raw


@pytest.fixture
def builder():
 import importlib.util
 path=P/'scripts/ops/autoencoder/build_leanstral4096_reclaim_worker.py'
 spec=importlib.util.spec_from_file_location('reclaim_worker_build_test',path)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

@pytest.mark.parametrize('seconds',[True,0,121,1.5,float('nan')])
def test_builder_rejects_unbounded_deadline_before_inputs(builder,tmp_path,seconds):
 with pytest.raises(ValueError,match='bounded compiler deadline'):
  builder.build(tmp_path/'out',tmp_path,tmp_path/'missing','0'*64,seconds)
 assert not (tmp_path/'out').exists()

@pytest.mark.parametrize('value',[{},None,{'schema':'other'},{'schema':'native-source4096-lazy-worker-build/v1','complete':1}])
def test_builder_requires_exact_prior_authenticated_profile(builder,value):
 with pytest.raises(ValueError):builder.validate_parent(value)


def test_builder_manifest_parse_uses_exact_bound_bytes(builder,tmp_path):
 path=tmp_path/'manifest.json';path.write_text('{"complete":true}')
 with pytest.raises(ValueError):builder.read_bound(path,'0'*64)
 item=builder.metadata(path);parsed,pin=builder.read_bound(path,item['sha256'])
 assert parsed=={'complete':True} and pin==item
 path.write_text('{"complete":false}')
 with pytest.raises(ValueError):builder.checked(path,item)


def test_builder_does_not_rebuild_or_open_weights(builder):
 text=Path(builder.__file__).read_text()
 assert 'cmake' not in text and 'ninja' not in text
 assert 'llama_model_load_from_file' not in text and 'subprocess.run(command' in text
 assert 'dependencies==before_dependencies' in text
 assert 'maximum_seconds<=120' in text


def test_dependency_scan_keeps_optimization_defines_and_thread_preprocessor_flags(builder,tmp_path):
 worker=tmp_path/'worker.cpp'
 command=['/usr/bin/g++','-std=c++17','-O2','-Wall','-Wextra','-Wpedantic','-MD','-MF',str(tmp_path/'worker.d'),'-DOWNER_SOURCE_SHA256="abc"','-I/native/include',str(worker),'-o',str(tmp_path/'worker'),'-L/native/lib','-lllama','-pthread']
 actual=builder.dependency_arguments(command,worker,tmp_path)
 assert actual==['/usr/bin/g++','-std=c++17','-O2','-Wall','-Wextra','-Wpedantic','-DOWNER_SOURCE_SHA256="abc"','-I/native/include','-M','-MF',str(tmp_path/'before.d'),str(worker),'-pthread']
 assert '-O2' in actual and '-pthread' in actual and '-o' not in actual


@pytest.mark.parametrize('n,prompt,single,tp,ts,expected',[(1,1,1,0,1.2,'0 1 single_token'),(8,8,1,3.4,0,'8 0 prompt_batch'),(512,512,1,9,0,'512 0 prompt_batch')])
def test_raw_counter_floor_accounting_is_exact_dispatch_only(executable,n,prompt,single,tp,ts,expected):
 result=run(executable,'account',n,prompt,single,tp,ts)
 assert result.returncode==0,result.stderr
 assert result.stdout.strip()==expected

@pytest.mark.parametrize('args',[
 (0,1,1,0,1),(513,513,1,1,0),(8,7,1,1,0),(8,9,1,1,0),
 (8,8,0,1,0),(8,8,2,1,0),(8,8,1,0,0),(8,8,1,1,1),
 (8,8,1,-1,0),(8,8,1,'nan',0),(8,8,1,'inf',0),(8,8,1,1,'nan'),
 (1,0,1,0,1),(1,1,0,0,1),(1,2,1,0,1),(1,1,2,0,1),
 (1,1,1,1,1),(1,1,1,0,0),(1,1,1,0,-1),
])
def test_counter_clamp_does_not_hide_incorrect_counts_or_branch_times(executable,args):
 assert run(executable,'account',*args).returncode==2


def test_worker_keeps_raw_counter_evidence_and_checks_before_embedding_read():
 source=WORKER.read_text()
 assert '"raw_n_p_eval",perf.n_p_eval' in source and '"raw_n_eval",perf.n_eval' in source
 assert '"raw_t_p_eval_ms",perf.t_p_eval_ms' in source and '"raw_t_eval_ms",perf.t_eval_ms' in source
 assert '7e5a6656cf1b4b24c6bc825d90fcab4c0aab677c53a868f51a61c742b8361c76' in source
 assert source.index('account_single_reset_decode(')<source.index('llama_get_embeddings_seq(context,0)')
 assert '"native_tokens_evaluated",accounted.prompt+accounted.single' in source
 assert 'perf.n_p_eval+perf.n_eval' not in source


def test_cpu_observation_requires_exact_registry_owned_pointer_not_host_or_name():
 source=WORKER.read_text();start=source.index('static bool observe_node_buffer(');end=source.index('static constexpr const char * CPU_OBSERVATION_POLICY',start)
 observer=source[start:end]
 assert 'type==operation.canonical_cpu_type' in observer
 assert 'type==ggml_backend_cpu_buffer_type()' in observer
 assert 'type==ggml_backend_dev_buffer_type(operation.authenticated_cpu)' in observer
 assert 'ggml_backend_buft_is_host(type)' in observer
 assert 'ggml_backend_buft_name' not in observer
 assert 'else ++operation.unrecognized_buffer_type_nodes' in observer
 assert 'ggml_backend_dev_type(device)!=GGML_BACKEND_DEVICE_TYPE_CPU' in observer


def test_cpu_categories_and_positive_evidence_checked_before_model_vector():
 source=WORKER.read_text()
 assert 'operation.cpu_device_pointer_nodes+operation.canonical_cpu_buffer_type_nodes>0' in source
 assert 'operation.evaluated_nodes==operation.nodes_without_buffer+operation.cpu_device_pointer_nodes' in source
 assert '+operation.canonical_cpu_buffer_type_nodes+operation.unrecognized_buffer_type_nodes' in source
 assert source.index('const auto cpu_observations=cpu_observation_report(operation)')<source.index('llama_get_embeddings_seq(context,0)')
 assert 'a96b54377e2b66732dcc5ed7ede82b6e0e873de53d515ac9fd6aa118b716bdd3' in source


def test_real_graph_control_is_model_free_uses_same_callback_and_negative_buffers():
 source=WORKER.read_text();start=source.index('static json cpu_buffer_control()');end=source.index('static std::string model_metadata',start)
 control=source[start:end]
 assert 'llama_model_load' not in control and 'model_fd' not in control
 assert 'ggml_backend_sched_set_eval_callback(scheduler.get(),observe_node,&operation)' in control
 assert 'ggml_backend_sched_graph_compute(scheduler.get(),graph)' in control
 assert 'ggml_backend_sched_synchronize(scheduler.get())' in control
 assert 'for(int repeat=0;repeat<2;++repeat)' in control
 assert 'operation.canonical_cpu_buffer_type_null_device_nodes>0' in control
 assert 'operation.unrecognized_buffer_type_nodes==1 && !has_cpu_observations(operation)' in control
 assert 'operation.nodes_without_buffer==1' in control and 'out[j]==float(10+2*j)' in control
 assert 'ggml_backend_cpu_buffer_from_ptr(memory,4096)' in control


def test_build_authenticates_cpu_buffer_implementation_and_inventory(builder):
 source=Path(builder.__file__).read_text()
 assert 'a96b54377e2b66732dcc5ed7ede82b6e0e873de53d515ac9fd6aa118b716bdd3' in source
 assert "inventory['files']['ggml/src/ggml-backend.cpp']['sha256']" in source
 assert "'backend_cpu_buffer_source':metadata(" in source
