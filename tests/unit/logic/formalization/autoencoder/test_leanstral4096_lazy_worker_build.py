"""Pure build-plan safety tests: no backend compilation or model execution."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import pytest

P=Path(__file__).resolve().parents[5]
SPEC=importlib.util.spec_from_file_location('lazy_native_build',P/'scripts/ops/autoencoder/build_leanstral4096_lazy_worker.py')
subject=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(subject)


def blob(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def archive(path, members):
 with tarfile.open(path,'w:gz') as out:
  for name,kind,raw in members:
   member=tarfile.TarInfo(name);member.type=kind;member.size=len(raw) if kind==tarfile.REGTYPE else 0
   if kind==tarfile.SYMTYPE:member.linkname='../outside'
   out.addfile(member,io.BytesIO(raw) if kind==tarfile.REGTYPE else None)


def test_exact_git_blob_tree_extract_and_one_literal_patch(tmp_path):
 raw=b'prefix '+subject.OLD+b' suffix\n';entries=subject.tree_entries(('100644 blob '+blob(raw)+'\tsrc/llama-model.cpp\0').encode())
 arc=tmp_path/'source.tar.gz';archive(arc,[('src/',tarfile.DIRTYPE,b''),('src/llama-model.cpp',tarfile.REGTYPE,raw)])
 result=subject.extract_authenticated_archive(arc,tmp_path/'source',entries)
 assert result['src/llama-model.cpp']['sha256']==subject.digest(raw)
 patch=subject.patch_private_source(tmp_path/'source')
 assert patch['substitution_count']==1 and not patch['shared_source_modified']
 assert (tmp_path/'source/src/llama-model.cpp').read_bytes()==raw.replace(subject.OLD,subject.NEW)


@pytest.mark.parametrize('name,kind', [('../escape',tarfile.REGTYPE),('/escape',tarfile.REGTYPE),('src/link',tarfile.SYMTYPE),('src/link',tarfile.LNKTYPE),('src/node',tarfile.FIFOTYPE)])
def test_archive_rejects_traversal_and_special_files(tmp_path,name,kind):
 arc=tmp_path/'source.tar.gz';archive(arc,[(name,kind,b'x')])
 with pytest.raises(ValueError):subject.extract_authenticated_archive(arc,tmp_path/'source',{'src/a':{'git_blob':blob(b'x'),'mode':'100644'}})


@pytest.mark.parametrize('mode,kind,name',[('120000','blob','a'),('160000','commit','a'),('100644','blob','../a'),('100644','blob','/a')])
def test_git_tree_rejects_unclosed_or_nonregular(mode,kind,name):
 with pytest.raises(ValueError):subject.tree_entries(f'{mode} {kind} {blob(b"x")}\t{name}\0'.encode())


@pytest.mark.parametrize('members',[[],[('a',tarfile.REGTYPE,b'wrong')],[('a',tarfile.REGTYPE,b'x'),('a',tarfile.REGTYPE,b'x')]])
def test_archive_requires_complete_unduplicated_exact_blobs(tmp_path,members):
 arc=tmp_path/'source.tar.gz';archive(arc,members)
 with pytest.raises(ValueError):subject.extract_authenticated_archive(arc,tmp_path/'source',{'a':{'git_blob':blob(b'x'),'mode':'100644'}})


@pytest.mark.parametrize('raw',[b'nothing',subject.OLD+subject.OLD,subject.NEW])
def test_patch_refuses_drift(tmp_path,raw):
 path=tmp_path/subject.PATCH_PATH;path.parent.mkdir();path.write_bytes(raw)
 with pytest.raises(ValueError):subject.patch_private_source(tmp_path)
 assert path.read_bytes()==raw


def test_only_owned_internal_file_aliases_are_materialized(tmp_path):
 root=tmp_path/'owned';root.mkdir();(root/'lib.so.1').write_bytes(b'private');(root/'lib.so').symlink_to('lib.so.1')
 receipt=subject.materialize_internal_links(root)
 assert (root/'lib.so').read_bytes()==b'private' and not (root/'lib.so').is_symlink()
 assert receipt==[{'path':'lib.so','target':'lib.so.1','bytes':7,'sha256':subject.digest(b'private')}]


def test_external_link_is_never_materialized(tmp_path):
 outside=tmp_path/'outside';outside.write_bytes(b'foreign');root=tmp_path/'owned';root.mkdir();(root/'link').symlink_to(outside)
 with pytest.raises(ValueError):subject.materialize_internal_links(root)
 assert (root/'link').is_symlink() and outside.read_bytes()==b'foreign'


def test_build_profile_disables_download_paths_gpu_repack_and_prefetch():
 for key in ('LLAMA_BUILD_COMMON','LLAMA_BUILD_TOOLS','LLAMA_BUILD_SERVER','LLAMA_BUILD_APP','LLAMA_BUILD_UI','LLAMA_USE_PREBUILT_UI','LLAMA_OPENSSL','GGML_CUDA','GGML_VULKAN','GGML_METAL','GGML_BLAS','GGML_OPENMP','GGML_CPU_REPACK'):
  assert subject.CONFIGURE[key]=='OFF'
 assert subject.OLD.replace(b'(true,',b'(false,')==subject.NEW
 raw=(P/subject.SOURCE).read_text()
 assert 'native-source4096-worker-description/v2' in raw
 assert raw.index('read_control(control_fd, operation)') < raw.index('llama_backend_init(); backend_initialized = true')
 assert raw.index('owner closing acknowledgement differs') < raw.index('native-source4096-worker-exit/v1')
 assert 'params.use_extra_bufts = false' in raw
 assert 'cp.n_ctx = LIMIT; cp.n_batch = LIMIT; cp.n_ubatch = LIMIT; cp.n_seq_max = 1' in raw


def test_generated_alias_rule_keeps_regular_bytes_without_symlink_interval(tmp_path):
 build=tmp_path/'build';(build/'CMakeFiles').mkdir(parents=True)
 old=b'prefix\n  command = /usr/bin/cmake -E cmake_symlink_library $in $SONAME $out && $POST_BUILD\nend\n'
 rules=build/'CMakeFiles/rules.ninja';rules.write_bytes(old)
 receipt=subject.replace_library_alias_rule(build,P/'scripts/ops/autoencoder/build_leanstral4096_lazy_worker.py')
 assert not receipt['native_compiler_or_linker_flags_changed']
 assert b'--regular-library-alias $in $SONAME $out && $POST_BUILD' in rules.read_bytes()
 source=tmp_path/'lib.so.1.0';source.write_bytes(b'compiled native bytes');source.chmod(0o755)
 aliases=[tmp_path/'lib.so.1',tmp_path/'lib.so']
 subject.regular_library_aliases(source,aliases)
 assert all(not p.is_symlink() and p.read_bytes()==source.read_bytes() for p in aliases)


@pytest.mark.parametrize('kind',['external','same','duplicate','symlink'])
def test_alias_command_rejects_unowned_or_incorrect_destination(tmp_path,kind):
 source=tmp_path/'lib.so.1';source.write_bytes(b'library')
 dest=tmp_path/'alias';outs=[dest]
 if kind=='external':outs=[tmp_path.parent/'outside-lib']
 if kind=='same':outs=[source]
 if kind=='duplicate':outs=[dest,dest]
 if kind=='symlink':dest.symlink_to(source)
 with pytest.raises(ValueError):subject.regular_library_aliases(source,outs)
 assert source.read_bytes()==b'library'
