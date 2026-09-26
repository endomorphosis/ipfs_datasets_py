#!/usr/bin/env python3
"""Build a separate offline validator image from verified installed files.

No pip, package imports, downloads, task transitions, cache deletion, or model
calls. RECORD verification attests local bytes, not upstream authenticity.
The base image and all generated evidence/build caches are retained.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from run_autoformal_supervisor import pin_accelerate

MAX_FILE = 4 * 1024**2
MAX_BUNDLE = 16 * 1024**2
PURELIB = "/opt/pcpc-runtime/lib/python3.12/site-packages"


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def local_closure(requirements, *, distribution=metadata.distribution, max_distributions=16):
    """Resolve default-environment dependencies without importing packages."""
    if type(max_distributions) is not int or not 1 <= max_distributions <= 96:
        raise ValueError("invalid offline dependency closure bound")
    pending = list(requirements)
    selected = {}
    environment = {**default_environment(), "extra": ""}
    while pending:
        req = Requirement(pending.pop(0))
        if req.marker and not req.marker.evaluate(environment):
            continue
        if req.url or req.extras:
            raise ValueError("offline runtime forbids URLs and optional extras")
        name = canonicalize_name(req.name)
        installed = distribution(name)
        if canonicalize_name(installed.metadata['Name']) != name or Version(installed.version) not in req.specifier:
            raise ValueError("installed dependency does not satisfy runtime requirement: " + name)
        if name in selected:
            if selected[name].version != installed.version:
                raise ValueError("installed dependency changed during resolution")
            continue
        if len(selected) >= max_distributions:
            raise ValueError("offline runtime dependency closure exceeds bound")
        selected[name] = installed
        pending.extend(installed.requires or ())
    return selected


def safe_member(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (not value or value == '.' or path.is_absolute() or '..' in path.parts or str(path) != value
            or '\\' in value or any(ord(c) < 32 for c in value)):
        raise ValueError("unsafe installed distribution path")
    if path.suffix in {'.pth', '.so', '.dll', '.dylib'} or path.name in {'sitecustomize.py', 'usercustomize.py'}:
        raise ValueError("offline v1 only admits pure Python without startup hooks")
    return path


def verified_file(distribution, member) -> tuple[str, bytes, str]:
    relative = safe_member(str(member))
    root = Path(distribution.locate_file('')).absolute()
    path = Path(distribution.locate_file(member)).absolute()
    if root.resolve(strict=True) != root or path.resolve(strict=True) != path or not path.is_relative_to(root):
        raise ValueError("installed distribution file is not canonical and contained")
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE:
            raise ValueError("installed distribution file exceeds bounds")
        raw = stream.read(MAX_FILE + 1)
        after = os.fstat(stream.fileno())
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if (len(raw) > MAX_FILE or any(getattr(before, k) != getattr(after, k) for k in fields)
            or any(getattr(after, k) != getattr(path.stat(), k) for k in fields)):
        raise ValueError("installed distribution changed during read")
    is_record = relative.name == 'RECORD' and relative.parent.name.endswith('.dist-info')
    if member.hash is None:
        if not is_record:
            raise ValueError("installed distribution has an unhashed non-RECORD file")
        verification = 'record_self_hash_generated_locally'
    else:
        if member.hash.mode != 'sha256':
            raise ValueError("installed distribution does not use SHA256 RECORD hashes")
        actual = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')
        if actual != member.hash.value or member.size != len(raw):
            raise ValueError("installed distribution RECORD hash or size mismatch")
        verification = 'installed_RECORD_sha256'
    return str(relative), raw, verification


def collect_bundle(distributions):
    files, packages, payload, total = [], {}, {}, 0
    for name, dist in sorted(distributions.items()):
        if not dist.files:
            raise ValueError("installed distribution lacks RECORD inventory")
        packages[name] = dist.version
        members = list(dist.files)
        if len(members) > 4096:
            raise ValueError("installed distribution inventory exceeds bound")
        for member in members:
            relative = safe_member(str(member))
            if '__pycache__' in relative.parts or relative.suffix == '.pyc':
                continue
            path, raw, verification = verified_file(dist, member)
            if path in payload:
                raise ValueError("distribution files overlap")
            total += len(raw)
            if total > MAX_BUNDLE:
                raise ValueError("offline runtime bundle exceeds bound")
            payload[path] = raw
            files.append({'path': path, 'sha256': digest(raw), 'bytes': len(raw),
                          'distribution': name, 'verification': verification})
    manifest = {'schema': 'autoformal.offline-runtime-bundle/v1', 'packages': packages,
                'files': files, 'bytes': total, 'pycache_copied': False,
                'trust': 'local installed RECORD verification; not upstream signature verification'}
    return manifest, payload


VERIFY_IMAGE = r'''
import base64, hashlib, importlib.metadata as m, json, pathlib
root = pathlib.Path('/opt/pcpc-runtime/lib/python3.12/site-packages')
raw_manifest = pathlib.Path('/opt/autoformal-runtime/manifest.json').read_bytes()
manifest = json.loads(raw_manifest)
for name, version in manifest['packages'].items():
    assert m.version(name) == version, name
for item in manifest['files']:
    path = root / item['path']
    assert path.is_file() and not path.is_symlink(), item['path']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'], item['path']
from multiformats import CID, multihash
cid = str(CID('base32', 1, 'raw', multihash.digest(b'autoformal-runtime-probe', 'sha2-256')))
assert str(CID.decode(cid)) == cid
expected = 'b' + base64.b32encode(bytes([1, 0x55, 0x12, 0x20]) + hashlib.sha256(b'autoformal-runtime-probe').digest()).decode().rstrip('=').lower()
assert cid == expected
print(json.dumps({'files_verified': len(manifest['files']), 'packages': manifest['packages'],
    'cid_roundtrip': True, 'cid_matches_independent_bytes': True,
    'manifest_sha256': hashlib.sha256(raw_manifest).hexdigest()}))
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accelerate-root', type=Path, required=True)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--base-isolation-config', type=Path, required=True)
    args = parser.parse_args(argv)
    pin_accelerate(args.accelerate_root)
    from ipfs_accelerate_py.agent_supervisor.todo_daemon import implementation_daemon as native
    from ipfs_datasets_py.logic.autoformal.feedback_cycle import check_storage
    from ipfs_datasets_py.logic.autoformal.validator_profile import RUNTIME_REQUIREMENTS_V1
    runtime = args.runtime_root.resolve(strict=True)
    check_storage(runtime, 50_000_000_000, reserve=4 * MAX_BUNDLE + 64 * 1024**2)
    directory = Path(tempfile.mkdtemp(prefix='offline-validator-runtime-v1-', dir=runtime))
    report = {'schema': 'autoformal.offline-runtime-build/v1', 'passed': False,
              'provider_calls': 0, 'tasks_claimed': 0, 'published': False,
              'downloads': False, 'old_images_modified': False, 'caches_removed': False,
              'directory': str(directory), 'live_repair_qualified': False}
    try:
        config = native.validate_external_provider_isolation_config(json.loads(args.base_isolation_config.read_text()))
        docker = [config.runtime_executable, '--host=' + config.runtime_endpoint]
        def capture(*command):
            return subprocess.check_output([*docker, *command], text=True, timeout=30)
        if 'name=rootless' not in json.loads(capture('info', '--format', '{{json .SecurityOptions}}')):
            raise ValueError('offline image build requires rootless Docker')
        def probe(image, program):
            return json.loads(capture('run', '--pull=never', '--rm', '--network=none', '--read-only',
                '--cap-drop=ALL', '--security-opt=no-new-privileges:true', '--pids-limit=32',
                '--memory=268435456', '--cpus=1', '--entrypoint=/opt/pcpc-runtime/bin/python', image, '-I', '-c', program))
        baseline = probe(config.image_id, 'import sys,sysconfig,json,importlib.metadata as m; print(json.dumps({"python":list(sys.version_info[:2]),"purelib":sysconfig.get_path("purelib"),"packages":{d.metadata["Name"].lower().replace("_","-"):d.version for d in m.distributions()}}))')
        if baseline['python'] != [3, 12] or baseline['purelib'] != PURELIB:
            raise ValueError('base image interpreter differs from reviewed runtime')
        distributions = local_closure(RUNTIME_REQUIREMENTS_V1[1:])
        manifest, payload = collect_bundle(distributions)
        for name, version in manifest['packages'].items():
            existing = baseline['packages'].get(name)
            if existing is not None and existing != version:
                raise ValueError('offline bundle would change an existing package version: ' + name)
        report['base_image'] = config.image_id
        report['base_image_bytes'] = int(capture('image', 'inspect', '--format', '{{.Size}}', config.image_id))
        report['manifest_sha256'] = digest(canonical(manifest))
        report['packages'] = manifest['packages']
        report['file_count'] = len(payload)
        context = directory / 'context'
        context.mkdir()
        for relative, raw in payload.items():
            target = context / 'packages' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(raw)
            target.chmod(0o644)
        (context / 'manifest.json').write_bytes(canonical(manifest))
        dockerfile = (f'FROM {config.image_id}\n'
                      'LABEL org.ipfs-accelerate.pcpc-runtime="autoformal-runtime-v1"\n'
                      f'LABEL org.ipfs-accelerate.autoformal.bundle-sha256="{report["manifest_sha256"]}"\n'
                      f'COPY packages/ {PURELIB}/\n'
                      'COPY manifest.json /opt/autoformal-runtime/manifest.json\n')
        (context / 'Dockerfile').write_text(dockerfile)
        report['dockerfile_sha256'] = digest(dockerfile.encode())
        image_file = directory / 'image-id.txt'
        log = directory / 'build.log'
        with log.open('xb') as stream:
            completed = subprocess.run([*docker, 'build', '--network=none', '--pull=false', '--rm=false',
                '--iidfile', str(image_file), str(context)], stdout=stream, stderr=subprocess.STDOUT,
                env={'HOME': '/nonexistent', 'PATH': '/usr/bin:/bin', 'DOCKER_BUILDKIT': '0'},
                timeout=120, check=False)
        report['build_returncode'] = completed.returncode
        if completed.returncode:
            raise ValueError('offline image build failed; log and partial artifacts retained')
        image_id = image_file.read_text().strip()
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id) or image_id == config.image_id:
            raise ValueError('builder did not return a new immutable image')
        report['image_id'] = image_id
        report['image_bytes'] = int(capture('image', 'inspect', '--format', '{{.Size}}', image_id))
        report['incremental_image_bytes'] = report['image_bytes'] - report['base_image_bytes']
        report['verification'] = probe(image_id, VERIFY_IMAGE)
        if (report['verification']['manifest_sha256'] != report['manifest_sha256']
                or report['verification']['packages'] != manifest['packages']):
            raise ValueError('image manifest differs from verified host bundle')
        new_config = config.to_dict()
        new_config.update(image_id=image_id, image_label='autoformal-runtime-v1')
        native.validate_external_provider_isolation_config(new_config)
        config_path = directory / 'isolation-config.json'
        config_path.write_bytes(canonical(new_config))
        report['isolation_config'] = str(config_path)
        report['isolation_config_sha256'] = digest(canonical(new_config))
        report['passed'] = True
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        report['error'] = {'type': type(exc).__name__, 'message': str(exc)[:2000]}
    report['retained_runtime_bytes'] = check_storage(runtime, 50_000_000_000,
        reserve=max(0, report.get('incremental_image_bytes', 0)))
    path = directory / 'receipt.json'
    with path.open('x') as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(json.dumps({'receipt': str(path), 'passed': report['passed'], 'image_id': report.get('image_id'),
                      'isolation_config': report.get('isolation_config'), 'provider_calls': 0}))
    return 0 if report['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
