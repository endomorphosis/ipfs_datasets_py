"""Native runtime preparation remains opt-in, bounded and fail-closed."""
import base64
import hashlib
import importlib.util
from importlib.metadata import PackagePath
from pathlib import Path
import struct
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def builder():
    scripts = Path(__file__).resolve().parents[3] / 'scripts/ops/legal_ir'
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location('native_runtime_test', scripts / 'prepare_autoformal_native_runtime.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(scripts))


def elf(machine=183, kind=3):
    raw = bytearray(64)
    raw[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHI', raw, 16, kind, machine, 1)
    return bytes(raw)


@pytest.mark.parametrize('fault', ['wrong_arch', 'executable', 'hidden', 'truncated', 'not_elf', 'wrong_python'])
def test_foreign_or_disguised_binaries_rejected(builder, fault):
    raw, path = elf(), 'pkg/native.cpython-312-aarch64-linux-gnu.so'
    if fault == 'wrong_arch': raw = elf(machine=62)
    elif fault == 'executable': raw = elf(kind=2)
    elif fault == 'hidden': path = 'pkg/innocent.py'
    elif fault == 'truncated': raw = raw[:30]
    elif fault == 'not_elf': raw = b'not native code'
    elif fault == 'wrong_python': path = path.replace('312', '311')
    with pytest.raises(ValueError):
        builder.elf_identity(raw, path, machine='aarch64')


def test_shared_libraries_and_python_data_remain_distinct(builder):
    assert builder.elf_identity(elf(), 'numpy.libs/libgfortran.so.5.0.0', machine='aarch64')['class'] == 64
    assert builder.elf_identity(b'value = 1', 'pkg/code.py', machine='aarch64') is None


@pytest.mark.parametrize('path', ['../secret', '/absolute', 'pkg/../file', 'pkg//file', 'foo.pth',
                                'sitecustomize.py', 'usercustomize.py', 'native.dll', 'native.dylib'])
def test_member_policy_does_not_admit_startup_hooks_or_escapes(builder, path):
    with pytest.raises(ValueError): builder.safe_member(path)


@pytest.fixture
def installed(tmp_path):
    raw = elf()
    member = PackagePath('pkg/native.so')
    member.hash = SimpleNamespace(mode='sha256', value=base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip('='))
    member.size = len(raw)
    path = tmp_path / str(member)
    path.parent.mkdir(); path.write_bytes(raw)
    dist = SimpleNamespace(locate_file=lambda p: tmp_path / p, version='1', metadata={'Name': 'pkg'},
                           requires=[], files=[member])
    return dist, member


def test_native_copy_requires_record_and_retains_elf_identity(builder, installed):
    dist, member = installed
    manifest, payload = builder.collect_bundle({'pkg': dist}, base_packages={}, machine='aarch64')
    assert payload[str(member)] == elf()
    assert manifest['files'][0]['elf']['machine'] == 'aarch64'
    member.hash.value = 'tampered'
    with pytest.raises(ValueError, match='RECORD'):
        builder.collect_bundle({'pkg': dist}, base_packages={}, machine='aarch64')


def test_base_versions_and_paths_cannot_be_overwritten(builder, installed):
    dist, member = installed
    manifest, payload = builder.collect_bundle({'pkg': dist}, base_packages={'pkg': '1'}, machine='aarch64')
    assert payload == {} and manifest['base_packages_reused'] == {'pkg': '1'}
    with pytest.raises(ValueError, match='existing distribution'):
        builder.collect_bundle({'pkg': dist}, base_packages={'pkg': '2'}, machine='aarch64')
    with pytest.raises(ValueError, match='overlap'):
        builder.collect_bundle({'pkg': dist}, base_packages={}, base_paths=[str(member)], machine='aarch64')


def test_only_reviewed_nonruntime_members_are_excluded(builder):
    dist = SimpleNamespace(version='82', files=[PackagePath('distutils-precedence.pth')])
    manifest, payload = builder.collect_bundle({'setuptools': dist}, base_packages={}, machine='aarch64')
    assert not payload and len(manifest['excluded']) == 1
    with pytest.raises(ValueError, match='startup hooks'):
        builder.collect_bundle({'other': dist}, base_packages={}, machine='aarch64')


@pytest.mark.parametrize('key', ['python', 'soabi', 'machine', 'libc', 'byteorder', 'pointer_bits', 'purelib'])
def test_abi_mismatch_rejected_before_build(builder, key):
    host = {'python': [3, 12], 'soabi': 'cpython-312-aarch64-linux-gnu', 'machine': 'aarch64',
            'libc': ['glibc', '2.39'], 'byteorder': 'little', 'pointer_bits': 64}
    image = dict(host, purelib=builder.PURELIB)
    builder.require_abi(host, image)
    image[key] = 'wrong'
    with pytest.raises(ValueError, match='ABI differ'): builder.require_abi(host, image)


def test_expanded_closure_does_not_weaken_v1_default(builder):
    distributions = {str(n): SimpleNamespace(metadata={'Name': str(n)}, version='1',
                     requires=[f'{n+1}==1'] if n < 20 else []) for n in range(21)}
    with pytest.raises(ValueError, match='closure exceeds'):
        builder.local_closure(['0==1'], distribution=distributions.__getitem__)
    assert len(builder.local_closure(['0==1'], distribution=distributions.__getitem__, max_distributions=96)) == 21


def test_inactive_extras_are_not_dependencies_and_active_extras_still_rejected(builder):
    def unavailable(_):
        pytest.fail('inactive optional extra must not trigger lookup')
    assert builder.local_closure(['optional[gpu]; extra == "gpu"'], distribution=unavailable) == {}
    with pytest.raises(ValueError, match='URLs and optional extras'):
        builder.local_closure(['optional[gpu]; python_version >= "3"'], distribution=unavailable)


@pytest.mark.parametrize('name,version', [('wrong', '3.0.2'), ('MarkupSafe', '0.0.0')])
def test_cached_override_cannot_select_another_package_or_version(builder, tmp_path, name, version):
    path = tmp_path / 'fixture.dist-info'
    path.mkdir()
    (path / 'METADATA').write_text(f'Name: {name}\nVersion: {version}\n')
    with pytest.raises(ValueError, match='reviewed name/version'):
        builder.cached_distribution(path, name='markupsafe')


def test_cached_override_is_metadata_only_and_keeps_host_distribution_unchanged(builder, tmp_path):
    path = tmp_path / 'MarkupSafe-3.0.2.dist-info'
    path.mkdir()
    (path / 'METADATA').write_text('Name: MarkupSafe\nVersion: 3.0.2\n')
    before = builder.metadata.version('markupsafe')
    assert builder.cached_distribution(path, name='markupsafe').version == '3.0.2'
    assert builder.metadata.version('markupsafe') == before
    alias = tmp_path / 'alias.dist-info'
    alias.symlink_to(path)
    with pytest.raises(ValueError, match='canonical'): builder.cached_distribution(alias, name='markupsafe')
