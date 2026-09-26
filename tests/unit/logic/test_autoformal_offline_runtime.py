"""Offline image inputs must be exact local RECORD bytes, never broad mounts."""
import base64
import hashlib
import importlib.util
from importlib.metadata import PackagePath
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def builder():
    scripts = Path(__file__).resolve().parents[3] / 'scripts/ops/legal_ir'
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location('offline_runtime_test', scripts / 'prepare_autoformal_offline_runtime.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(scripts))


@pytest.mark.parametrize('path', ['', '.', '../secret', '/etc/passwd', 'pkg/../../secret',
    'pkg//file.py', 'pkg\\file.py', 'pkg/../file.py', 'extra.pth', 'sitecustomize.py',
    'usercustomize.py', 'binary.so', 'pkg/line\nfile.py'])
def test_reject_unsafe_or_executable_install_layout(builder, path):
    with pytest.raises(ValueError):
        builder.safe_member(path)


@pytest.fixture
def installed(tmp_path):
    raw = b'value = 1\n'
    (tmp_path / 'pkg').mkdir()
    (tmp_path / 'pkg/__init__.py').write_bytes(raw)
    member = PackagePath('pkg/__init__.py')
    member.hash = SimpleNamespace(mode='sha256', value=base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip('='))
    member.size = len(raw)
    dist = SimpleNamespace(locate_file=lambda path: tmp_path / path, version='1.0',
                           metadata={'Name': 'pkg'}, requires=[], files=[member])
    return dist, member


def test_verify_and_manifest_exact_bytes(builder, installed):
    dist, member = installed
    path, raw, verification = builder.verified_file(dist, member)
    manifest, payload = builder.collect_bundle({'pkg': dist})
    assert payload[path] == raw
    assert verification == 'installed_RECORD_sha256'
    assert manifest['files'][0]['sha256'] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('fault', ['hash', 'size', 'unhashed', 'algorithm', 'symlink', 'changed'])
def test_reject_unverified_installed_files(builder, installed, fault):
    dist, member = installed
    if fault == 'hash': member.hash.value = 'incorrect'
    elif fault == 'size': member.size += 1
    elif fault == 'unhashed': member.hash = None
    elif fault == 'algorithm': member.hash.mode = 'md5'
    elif fault == 'changed': dist.locate_file(member).write_text('changed')
    else:
        path = dist.locate_file(member)
        saved = path.with_suffix('.saved')
        path.rename(saved)
        path.symlink_to(saved)
    with pytest.raises(ValueError):
        builder.verified_file(dist, member)


def test_closure_handles_cycles_and_version_checks_without_importing(builder):
    distributions = {
        'one': SimpleNamespace(metadata={'Name': 'one'}, version='1', requires=['two>=2']),
        'two': SimpleNamespace(metadata={'Name': 'two'}, version='2', requires=['one>=1']),
    }
    result = builder.local_closure(['one==1'], distribution=distributions.__getitem__)
    assert set(result) == {'one', 'two'}
    with pytest.raises(ValueError, match='does not satisfy'):
        builder.local_closure(['one>=3'], distribution=distributions.__getitem__)


@pytest.mark.parametrize('requirement', ['one[extra]', 'one @ https://example.invalid/wheel.whl'])
def test_no_downloads_or_optional_extras(builder, requirement):
    with pytest.raises(ValueError, match='URLs and optional extras'):
        builder.local_closure([requirement], distribution=lambda name: pytest.fail('must reject before lookup'))
