"""Reproduction recipe assembled after the retained run; not another result.

Usage: python reproduce_dependency_pair.py NEW_DIRECTORY
Requires the recorded host dependencies to be installed. Never changes them.
"""
import hashlib
import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

B = Path(__file__).parent
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=False)
probe = out / 'dependency_timing_probe.py'
probe.write_bytes((B / 'dependency_timing_probe.py').read_bytes())
rows = [(f'r{i:06}', f'blob-{i // 17}', f'symbol-{i}', 'café_函数',
         f'module.Class.method_{i}', 'function', None if i % 3 == 0 else 'scope',
         i, bool(i % 2), '{"args":["request","headers"],"return":"str"}',
         None if i % 5 == 0 else '{"allow":"unicode Ω"}', '["public"]',
         i * 19, i * 19 + 18, i + 1, 0, i + 1, 18) for i in range(2048)]
fixture = out / 'mixed-36864-scalars.json'
body = json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode()
assert hashlib.sha256(body).hexdigest() == 'd3e7687eebb86d6443cd94a370fced3fdaf86602bd4f926e4fb889beae8fe3ba'
fixture.write_bytes(body)
links = {}
for mode in ('available', 'missing'):
    root = out / ('deps-' + mode)
    root.mkdir()
    links[mode] = {}
    names = ['duckdb', '_duckdb', 'numpy', 'dateutil', 'six'] + (['pandas'] if mode == 'available' else [])
    for name in names:
        spec = importlib.util.find_spec(name)
        source = Path(next(iter(spec.submodule_search_locations))) if spec.submodule_search_locations else Path(spec.origin)
        (root / source.name).symlink_to(source, target_is_directory=source.is_dir())
        links[mode][source.name] = str(source)
        libraries = source.parent / (name + '.libs')
        if libraries.is_dir():
            (root / libraries.name).symlink_to(libraries, target_is_directory=True)
            links[mode][libraries.name] = str(libraries)
    # DuckDB's version loader requires its actual distribution metadata.
    for name in ['duckdb', 'numpy', 'python-dateutil', 'six'] + (['pandas'] if mode == 'available' else []):
        source = Path(metadata.distribution(name)._path)
        if not (root / source.name).exists():
            (root / source.name).symlink_to(source, target_is_directory=True)
        links[mode][source.name] = str(source)
(out / 'dependency-links.json').write_text(json.dumps(links, indent=2) + '\n')
input_sha = hashlib.sha256(body).hexdigest()
for index, mode in enumerate(('available', 'missing', 'missing', 'available')):
    args = [sys.executable, '-I', '-S', '-B', str(probe), str(out / ('deps-' + mode)), str(fixture), input_sha, mode]
    start = time.monotonic()
    result = subprocess.run(args, text=True, capture_output=True, timeout=20)
    prefix = out / f'dependency-{index:02}-{mode}'
    prefix.with_suffix('.stdout').write_text(result.stdout)
    prefix.with_suffix('.stderr').write_text(result.stderr)
    Path(str(prefix) + '-exit.json').write_text(json.dumps(dict(argv=args,
        returncode=result.returncode, process_seconds=time.monotonic() - start,
        script_sha256=hashlib.sha256(probe.read_bytes()).hexdigest(), input_sha256=input_sha), indent=2) + '\n')
    if result.returncode:
        raise SystemExit(result.returncode)
