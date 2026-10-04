#!/usr/bin/env python3
"""Compile an isolated CPU native worker against already installed pinned llama.cpp.

This helper never opens a model, executes the resulting worker, downloads assets,
or edits the shared llama.cpp source/build. The caller separately admits probes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import time

REVISION = '571d0d540df04f25298d0e159e520d9fc62ed121'
SOURCE = 'ipfs_datasets_py/logic/formalization/autoencoder/native/leanstral4096_worker.cpp'
HEADER_SHA256 = {
    'include/llama.h': '2331631b6a3567311abc0402c55aa9a867ee99759f2550bdfa261ec3693a21f6',
    'ggml/include/ggml.h': 'c65c30fdb4dce95eac71c26bb38ae8423fbc80d79db91d2b2ffaea8c4e46276a',
    'ggml/include/ggml-backend.h': 'a620e815b43a44cc72d5f216629a3a91980335b61bc37eb6b2d0813368c3704f',
    'ggml/include/ggml-cpu.h': '316279e004cdeb8e6ef78599acb602bf79a8abdf897fed9fd1914808c1518c6e',
    'vendor/nlohmann/json.hpp': 'aaf127c04cb31c406e5b04a63f1ae89369fccde6d8fa7cdda1ed4f32dfc5de63',
}
LIBRARY_SHA256 = {
    'libllama.so.0.0.1': 'ca62747307627688d0d3a5c2f647bcc631cc64c22f806c5df05cfd5b5ce3d507',
    'libggml.so.0.17.0': '6cebcbc5f3c587358f8da52a134e7360e5bbf310b2705e58ce10614d9f34c24f',
    'libggml-base.so.0.17.0': '363272849a01494d0139f2afca820ea4347a53d3bb7ad6e4cf73e5fdaa4ce2fe',
    'libggml-cpu.so.0.17.0': '92f5ecd90596ee0b3e342e860343f712aba3ed69f94903bbd64463547d06118d',
}
LINK_NAMES = {'llama': 'libllama.so.0.0.1', 'ggml': 'libggml.so.0.17.0',
              'ggml-base': 'libggml-base.so.0.17.0', 'ggml-cpu': 'libggml-cpu.so.0.17.0'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def metadata(path):
    path = Path(path)
    require(path.is_file(), 'regular existing input required: ' + str(path))
    before = path.stat()
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            value.update(block)
    after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'input changed while hashing')
    return {'path': str(path.resolve()), 'bytes': after.st_size, 'sha256': value.hexdigest()}


def source_inventory(source_root, native_root):
    source_root, native_root = Path(source_root).resolve(), Path(native_root).resolve()
    source = source_root / SOURCE
    require(source.is_file() and not source.is_symlink(), 'owned native worker source required')
    native_source, libraries = native_root / 'source/llama.cpp', native_root / 'build/bin'
    require(native_source.is_dir() and libraries.is_dir(), 'existing native source/build root required')
    inputs = {str(source): metadata(source)}
    for relative, expected in HEADER_SHA256.items():
        path = native_source / relative
        require(not path.is_symlink(), 'native header symlink is unsupported')
        current = metadata(path)
        require(current['sha256'] == expected, 'pinned native header differs: ' + relative)
        inputs[str(path)] = current
    for filename, expected in LIBRARY_SHA256.items():
        path = libraries / filename
        require(not path.is_symlink(), 'versioned native library symlink is unsupported')
        current = metadata(path)
        require(current['sha256'] == expected, 'pinned native library differs: ' + filename)
        inputs[str(path)] = current
    for name, filename in LINK_NAMES.items():
        require((libraries / ('lib'+name+'.so')).resolve() == (libraries / filename).resolve(),
                'native linker alias differs: ' + name)
    # Authenticate the rest of the public native headers too, before compiling.
    for path in sorted(set((native_source / 'include').rglob('*.h')) |
                       set((native_source / 'ggml/include').rglob('*.h'))):
        require(not path.is_symlink(), 'public native header must be regular')
        current = metadata(path)
        published = subprocess.check_output(['git', 'show', REVISION+':'+str(path.relative_to(native_source))],
                                            cwd=native_source, timeout=15)
        require(hashlib.sha256(published).hexdigest() == current['sha256'], 'native header is not the pinned revision')
        inputs[str(path)] = current
    return {'source_root': source_root, 'native_root': native_root, 'source': source,
            'native_source': native_source, 'libraries': libraries, 'inputs': inputs}


def compile_command(inventory, output_dir, compiler):
    output_dir = Path(output_dir)
    source_sha = inventory['inputs'][str(inventory['source'])]['sha256']
    return [str(compiler), '-std=c++17', '-O2', '-Wall', '-Wextra', '-Wpedantic', '-MD',
            '-MF', str(output_dir / 'worker.d'), '-DOWNER_SOURCE_SHA256="'+source_sha+'"',
            '-I'+str(inventory['native_source'] / 'include'),
            '-I'+str(inventory['native_source'] / 'ggml/include'),
            '-I'+str(inventory['native_source'] / 'vendor/nlohmann'),
            str(output_dir / 'leanstral4096_worker.cpp'), '-o', str(output_dir / 'leanstral4096-worker'),
            '-L'+str(inventory['libraries']), '-Wl,-rpath,'+str(inventory['libraries']),
            '-lllama', '-lggml', '-lggml-cpu', '-lggml-base', '-lcrypto', '-pthread']


def dependency_paths(path):
    path = Path(path).resolve()
    raw = path.read_text().replace('\\\n', '')
    require(':' in raw, 'compiler dependency file lacks target')
    return sorted({str((path.parent / item).resolve()) for item in shlex.split(raw.split(':', 1)[1])})


def build_worker(output_dir, source_root, native_root):
    """Return the saved build manifest; compile only, never execute the worker."""
    started = time.monotonic()
    output_dir = Path(output_dir).absolute()
    require(not output_dir.exists() and not output_dir.is_symlink(), 'fresh owned build directory required')
    inventory = source_inventory(source_root, native_root)
    compiler_name = shutil.which('g++', path='/usr/bin:/bin')
    require(compiler_name is not None, 'existing system C++ compiler required')
    compiler = Path(compiler_name).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / 'tmp').mkdir()
    shutil.copyfile(inventory['source'], output_dir / 'leanstral4096_worker.cpp')
    command = compile_command(inventory, output_dir, compiler)
    environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C', 'TMPDIR': str(output_dir / 'tmp')}
    with (output_dir / 'build.log').open('xb') as log:
        process = subprocess.run(command, cwd=output_dir, env=environment, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT, timeout=120, check=False)
    require(process.returncode == 0, 'native compilation failed; see retained build.log')
    for path, expected in inventory['inputs'].items():
        require(metadata(path) == expected, 'native build input changed during compilation')
    dependencies = {path: metadata(path) for path in dependency_paths(output_dir / 'worker.d')}
    executable = metadata(output_dir / 'leanstral4096-worker')
    executable_path = Path(executable['path'])
    executable_path.chmod(0o700)
    result = dict(schema='native-source4096-worker-build/v1', complete=True,
        manifest_path=str(output_dir / 'build-manifest.json'), executable=executable,
        worker_source_sha256=inventory['inputs'][str(inventory['source'])]['sha256'],
        source_revision=REVISION, native_root=str(inventory['native_root']),
        compiler=metadata(compiler), compiler_arguments=command, compiler_environment=environment,
        inputs=inventory['inputs'], compiler_dependencies=dependencies,
        build_log=metadata(output_dir / 'build.log'), dependency_file=metadata(output_dir / 'worker.d'),
        copied_source=metadata(output_dir / 'leanstral4096_worker.cpp'),
        build_helper=metadata(__file__), elapsed_seconds=time.monotonic()-started,
        native_libraries_external_and_required=True, worker_executed=False, model_opened=False,
        model_weights_loaded=False, encoder_executed=False, downloads_performed=False,
        shared_native_source_or_service_modified=False, qualified=False, admitted=False)
    with Path(result['manifest_path']).open('x') as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--native-root', type=Path, required=True)
    args = parser.parse_args()
    result = build_worker(args.output_dir, args.source_root, args.native_root)
    print(json.dumps({'manifest_path': result['manifest_path'], 'executable': result['executable'],
                      'worker_executed': False, 'model_opened': False}))


if __name__ == '__main__':
    main()
