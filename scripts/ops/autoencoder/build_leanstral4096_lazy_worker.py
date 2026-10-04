#!/usr/bin/env python3
"""Build a private, CPU-only lazy-mmap backend and authorization-gated worker.

The caller must reserve resources. This program never opens a model or runs the
worker, never fetches Git objects, and never modifies the shared native checkout.
The backend is a new execution profile, not bitwise-equivalent to an older build.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import sys
import tarfile
import time

REVISION = '571d0d540df04f25298d0e159e520d9fc62ed121'
SOURCE = 'ipfs_datasets_py/logic/formalization/autoencoder/native/leanstral4096_authorized_worker.cpp'
PATCH_PATH = 'src/llama-model.cpp'
OLD = b'ml.init_mappings(true, use_mlock ? &pimpl->mlock_mmaps : nullptr);'
NEW = b'ml.init_mappings(false, use_mlock ? &pimpl->mlock_mmaps : nullptr);'
PROFILE = 'leanstral4096:cpu1:last:l2:single-sequence:tokens512:lazy-mmap:v2'
CONFIGURE = {
    'CMAKE_BUILD_TYPE': 'Release', 'BUILD_SHARED_LIBS': 'ON',
    'LLAMA_BUILD_COMMON': 'OFF', 'LLAMA_BUILD_TESTS': 'OFF',
    'LLAMA_BUILD_TOOLS': 'OFF', 'LLAMA_BUILD_EXAMPLES': 'OFF',
    'LLAMA_BUILD_SERVER': 'OFF', 'LLAMA_BUILD_APP': 'OFF',
    'LLAMA_BUILD_UI': 'OFF', 'LLAMA_USE_PREBUILT_UI': 'OFF',
    'LLAMA_BUILD_MTMD': 'OFF', 'LLAMA_OPENSSL': 'OFF',
    'GGML_CUDA': 'OFF', 'GGML_VULKAN': 'OFF', 'GGML_METAL': 'OFF',
    'GGML_BLAS': 'OFF', 'GGML_OPENMP': 'OFF', 'GGML_CPU_REPACK': 'OFF',
    'GGML_NATIVE': 'ON', 'GGML_CCACHE': 'OFF',
    'LLAMA_BUILD_NUMBER': '0', 'LLAMA_BUILD_COMMIT': REVISION + '-lazy',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def metadata(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'regular owned or authenticated file required: ' + str(path))
    before = path.stat(); value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            value.update(block)
    after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'input changed while hashing')
    return {'path': str(path.resolve()), 'bytes': after.st_size, 'sha256': value.hexdigest()}


def save(path, data):
    with Path(path).open('x') as stream:
        json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')


def tree_entries(raw):
    result = {}
    for entry in raw.split(b'\0'):
        if not entry:
            continue
        descriptor, name = entry.split(b'\t', 1)
        mode, kind, blob = descriptor.decode('ascii').split()
        relative = name.decode('utf-8')
        require(mode in ('100644', '100755') and kind == 'blob', 'only regular tracked source files supported')
        path = PurePosixPath(relative)
        require(not path.is_absolute() and '..' not in path.parts and str(path) == relative,
                'closed relative Git source path required')
        require(relative not in result, 'duplicate Git source path')
        result[relative] = {'mode': mode, 'git_blob': blob}
    require(bool(result), 'nonempty tracked source tree required')
    return result


def extract_authenticated_archive(archive, destination, entries):
    """No tar extraction semantics or filesystem links are accepted."""
    destination = Path(destination); destination.mkdir(exist_ok=False)
    seen = set(); inventory = {}
    with tarfile.open(archive, 'r:gz') as stream:
        for member in stream:
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and '..' not in path.parts and str(path) == member.name.rstrip('/'),
                    'unsafe archive member')
            if member.isdir():
                continue
            require(member.isfile() and member.name in entries, 'untracked or nonregular source member')
            require(member.name not in seen, 'duplicate source archive member'); seen.add(member.name)
            raw = stream.extractfile(member).read()
            entry = entries[member.name]
            git_blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            require(git_blob == entry['git_blob'], 'Git blob differs from archive bytes')
            out = destination / member.name; out.parent.mkdir(parents=True, exist_ok=True)
            with out.open('xb') as target: target.write(raw)
            out.chmod(0o755 if entry['mode'] == '100755' else 0o644)
            inventory[member.name] = dict(entry, bytes=len(raw), sha256=digest(raw))
    require(seen == set(entries), 'source archive omitted tracked files')
    return inventory


def patch_private_source(source):
    path = Path(source) / PATCH_PATH
    before = path.read_bytes()
    require(before.count(OLD) == 1 and NEW not in before, 'exact original eager mmap call required')
    after = before.replace(OLD, NEW)
    path.write_bytes(after)
    return {'relative_path': PATCH_PATH, 'historical_sha256': digest(before),
            'private_sha256': digest(after), 'old_literal': OLD.decode(), 'new_literal': NEW.decode(),
            'substitution_count': 1, 'shared_source_modified': False}


def materialize_internal_links(root):
    """Make owned build library aliases regular before strict resource accounting."""
    root = Path(root).resolve(); records = []
    for path in sorted(root.rglob('*')):
        if not path.is_symlink():
            continue
        target = path.resolve(strict=True)
        require(target.is_relative_to(root) and target.is_file(), 'build link leaves owned output or targets a directory')
        raw = target.read_bytes(); mode = target.stat().st_mode & 0o777
        records.append({'path': str(path.relative_to(root)), 'target': str(target.relative_to(root)),
                        'bytes': len(raw), 'sha256': digest(raw)})
        path.unlink()
        with path.open('xb') as stream: stream.write(raw)
        path.chmod(mode)
    return records



def regular_library_aliases(source, destinations):
    source=Path(source).absolute()
    require(source.is_file() and not source.is_symlink(), 'regular compiled library required')
    require(len(destinations) in (1,2), 'bounded library aliases required')
    outputs=[Path(value).absolute() for value in destinations]
    require(len(set(outputs)) == len(outputs), 'duplicate alias destination')
    for path in outputs:
        require(path.parent == source.parent and path != source and not path.is_symlink(), 'library alias must stay beside source')
        require(not path.exists() or path.is_file(), 'library alias must be regular')
    for path in outputs:
        shutil.copyfile(source,path);path.chmod(source.stat().st_mode & 0o777)


def replace_library_alias_rule(build, helper):
    path=Path(build)/'CMakeFiles/rules.ninja';before=path.read_bytes()
    old=b'command = /usr/bin/cmake -E cmake_symlink_library $in $SONAME $out && $POST_BUILD'
    require(before.count(old) == 1, 'exact generated CMake alias rule required')
    helper=Path(helper).resolve()
    require(' ' not in str(helper) and '$' not in str(helper), 'closed helper path for Ninja command required')
    new=('command = /usr/bin/python3 '+str(helper)+' --regular-library-alias $in $SONAME $out && $POST_BUILD').encode()
    after=before.replace(old,new);path.write_bytes(after)
    return {'rule_path':str(path),'before_sha256':digest(before),'after_sha256':digest(after),
            'old':old.decode(),'new':new.decode(),'native_compiler_or_linker_flags_changed':False,
            'scope':'regular byte-identical SONAME aliases replace packaging symlinks only'}


def dependency_paths(path):
    path = Path(path).resolve(); raw = path.read_text().replace('\\\n', '')
    require(':' in raw, 'compiler dependency file lacks target')
    return sorted({str((path.parent / item).resolve()) for item in shlex.split(raw.split(':', 1)[1])})


def build_worker(output_dir, source_root, native_source, *, ninja, maximum_seconds=600):
    started = time.monotonic()
    require(type(maximum_seconds) is int and 1 <= maximum_seconds <= 600, 'bounded build deadline required')
    deadline = started + maximum_seconds
    output = Path(output_dir).absolute(); source_root = Path(source_root).resolve(); native_source = Path(native_source).resolve()
    require(not output.exists() and not output.is_symlink(), 'fresh owned build output required')
    worker = source_root / SOURCE; worker_input = metadata(worker)
    require((native_source / '.git').exists(), 'existing local native Git checkout required')
    # Read immutable local Git objects; no fetch and no dependence on dirty worktree bytes.
    command = ['git', 'ls-tree', '-r', '-z', REVISION]
    entries = tree_entries(subprocess.check_output(command, cwd=native_source, timeout=20))
    tree = subprocess.check_output(['git', 'rev-parse', REVISION+'^{tree}'], cwd=native_source, timeout=20).decode().strip()
    output.mkdir(parents=True, exist_ok=False); (output/'tmp').mkdir()
    archive = output/'native-source.tar.gz'
    with archive.open('xb') as stream:
        subprocess.run(['git', 'archive', '--format=tar.gz', REVISION], cwd=native_source,
                       stdout=stream, stderr=subprocess.PIPE, timeout=60, check=True)
    private_source = output/'source/llama.cpp'; private_source.parent.mkdir()
    inventory = extract_authenticated_archive(archive, private_source, entries)
    patch = patch_private_source(private_source)
    save(output/'native-source-inventory.json', {'revision': REVISION, 'git_tree': tree, 'files': inventory, 'patch': patch})
    compiler = Path(shutil.which('g++', path='/usr/bin:/bin') or '').resolve()
    cmake = Path(shutil.which('cmake', path='/usr/bin:/bin') or '').resolve()
    ninja=Path(ninja).resolve(); ninja_input=metadata(ninja)
    require(compiler.is_file() and cmake.is_file(), 'installed compiler and CMake required')
    environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C', 'TMPDIR': str(output/'tmp'),
                   'GIT_CEILING_DIRECTORIES': str(output), 'CUDA_VISIBLE_DEVICES': '',
                   'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
                   'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'}
    commands = []
    def run(argv, logname):
        remaining = deadline-time.monotonic(); require(remaining > 0, 'build deadline expired')
        commands.append(argv)
        with (output/logname).open('xb') as log:
            process = subprocess.run(argv, cwd=output, env=environment, stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT, timeout=remaining, check=False)
        require(process.returncode == 0, 'private native build failed; inspect '+logname)
    configure = [str(cmake), '-G', 'Ninja', '-DCMAKE_MAKE_PROGRAM='+str(ninja), '-S', str(private_source), '-B', str(output/'build')]
    configure += ['-D'+key+'='+value for key, value in CONFIGURE.items()]
    run(configure, 'configure.log')
    alias_rule=replace_library_alias_rule(output/'build',__file__)
    save(output/'regular-library-alias-rule.json',alias_rule)
    run([str(ninja), '-C', str(output/'build'), '-j', '1', 'llama'], 'backend-build.log')
    libraries = output/'build/bin'
    for name in ('llama','ggml','ggml-cpu','ggml-base'):
        require((libraries/('lib'+name+'.so')).is_file(), 'required private CPU library missing: '+name)
    shutil.copyfile(worker, output/'leanstral4096_authorized_worker.cpp')
    require(metadata(worker) == worker_input, 'worker source changed before compiler launch')
    compile_command = [str(compiler), '-std=c++17', '-O2', '-Wall', '-Wextra', '-Wpedantic', '-MD',
        '-MF', str(output/'worker.d'), '-DOWNER_SOURCE_SHA256="'+worker_input['sha256']+'"',
        '-I'+str(private_source/'include'), '-I'+str(private_source/'ggml/include'),
        '-I'+str(private_source/'vendor/nlohmann'), str(output/'leanstral4096_authorized_worker.cpp'),
        '-o', str(output/'leanstral4096-authorized-worker'), '-L'+str(libraries), '-Wl,-rpath,'+str(libraries),
        '-lllama', '-lggml', '-lggml-cpu', '-lggml-base', '-lcrypto', '-pthread']
    run(compile_command, 'worker-build.log')
    aliases = materialize_internal_links(output)
    # Detect source writes by the build or a competing process; patched path has its own exact hash.
    for relative, expected in inventory.items():
        actual = metadata(private_source/relative)
        require(actual['sha256'] == (patch['private_sha256'] if relative == PATCH_PATH else expected['sha256']),
                'private source changed unexpectedly: '+relative)
    require(metadata(worker) == worker_input, 'worker source changed during build')
    dependencies = {path: metadata(path) for path in dependency_paths(output/'worker.d')}
    native_libraries = {str(path): metadata(path) for path in sorted(libraries.iterdir()) if path.is_file() and '.so' in path.name}
    require(all('cuda' not in Path(path).name for path in native_libraries), 'CPU-only private libraries required')
    result = dict(schema='native-source4096-lazy-worker-build/v1', complete=True,
        manifest_path=str(output/'build-manifest.json'), executable=metadata(output/'leanstral4096-authorized-worker'),
        worker_source_sha256=worker_input['sha256'], source_revision=REVISION, source_git_tree=tree,
        native_root=str(output), private_backend=True, profile=PROFILE, patch=patch,
        model_loader_prefetch=False, mmap_populate=False, cpu_extra_buffers=False,
        inputs={str(worker): worker_input,str(ninja):ninja_input}, compiler=metadata(compiler), cmake=metadata(cmake),ninja=ninja_input,
        compiler_arguments=compile_command, commands=commands, compiler_environment=environment,
        compiler_dependencies=dependencies, native_libraries=native_libraries, link_aliases_materialized=aliases,
        regular_library_alias_rule=metadata(output/'regular-library-alias-rule.json'),
        source_archive=metadata(archive), source_inventory=metadata(output/'native-source-inventory.json'),
        copied_source=metadata(output/'leanstral4096_authorized_worker.cpp'), build_helper=metadata(__file__),
        logs={name:metadata(output/name) for name in ('configure.log','backend-build.log','worker-build.log')},
        elapsed_seconds=time.monotonic()-started, maximum_seconds=maximum_seconds,
        native_libraries_external_and_required=True, worker_executed=False, model_opened=False,
        model_weights_loaded=False, encoder_executed=False, downloads_performed=False,
        shared_native_source_or_service_modified=False, qualified=False, admitted=False,
        previous_native_profile_bitwise_equivalence_claimed=False)
    save(output/'build-manifest.json', result); save(output/'summary.json', result)
    return result


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == '--regular-library-alias':
        require(len(sys.argv) in (4,5), 'source and one or two library aliases required')
        regular_library_aliases(sys.argv[2],sys.argv[3:]);return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--native-source', type=Path, required=True)
    parser.add_argument('--ninja', type=Path, required=True)
    parser.add_argument('--require-cgroup-memory-max', type=int)
    parser.add_argument('--maximum-seconds', type=int, default=600)
    args = parser.parse_args()
    if args.require_cgroup_memory_max is not None:
        require(args.require_cgroup_memory_max == 2*1024**3, 'fixed private-build cgroup limit required')
        relative=Path('/proc/self/cgroup').read_text().strip().split('::',1)[1]
        cgroup=Path('/sys/fs/cgroup')/Path(relative).relative_to('/')
        require(cgroup.name.startswith('native4096-build-') and cgroup.name.endswith('.scope'), 'owned private-build scope required')
        require(set((cgroup/'cgroup.procs').read_text().split()) == {str(os.getpid())}, 'private scope has foreign members')
        require((cgroup/'memory.max').read_text().strip() == str(args.require_cgroup_memory_max), 'hard memory limit differs')
        require((cgroup/'memory.swap.max').read_text().strip() == '0', 'build swap must be disabled')
        require((cgroup/'pids.max').read_text().strip() == '16', 'build PID limit differs')
        (cgroup/'memory.oom.group').write_text('1')
        require((cgroup/'memory.oom.group').read_text().strip() == '1', 'group OOM containment missing')
    result = build_worker(args.output_dir,args.source_root,args.native_source,ninja=args.ninja,maximum_seconds=args.maximum_seconds)
    if args.require_cgroup_memory_max is not None:
        save(args.output_dir/'cgroup-completed.json',dict(path=str(cgroup),memory_max_bytes=args.require_cgroup_memory_max,
            memory_peak_bytes=int((cgroup/'memory.peak').read_text()),memory_events=(cgroup/'memory.events').read_text(),
            swap_max_bytes=0,pids_max=16,scope='cgroup charge; not a universal RSS bound'))
    print(json.dumps({'manifest_path':result['manifest_path'],'elapsed_seconds':result['elapsed_seconds'],
                      'worker_executed':False,'model_opened':False}))


if __name__ == '__main__':
    main()
