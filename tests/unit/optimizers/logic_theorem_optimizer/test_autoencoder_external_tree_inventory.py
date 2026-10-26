"""Small, disposable metadata trees; no native receipt or admission authority.

These tests exercise the real descriptor inventory. No provider, database,
external payload or host resource catalog is used.
"""
import builtins
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat

import pytest

PACKAGE = os.environ.get('IPFS_RECOVERY_TEST_PACKAGE',
    'ipfs_datasets_py.optimizers.logic_theorem_optimizer')
inventory = importlib.import_module(PACKAGE + '.autoencoder_external_tree_inventory')


def observe(root, **changes):
    bounds = dict(max_entries=128, max_bytes=1024**2, max_depth=16, max_symlink_hops=8)
    bounds.update(changes)
    return inventory.observe_external_tree(root, **bounds)


def body_digest(value):
    body = dict(value)
    body.pop('inventory_sha256')
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'),
        ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def rows(value):
    return {row['path']: row for row in value['entries']}


def test_empty_tree_is_bounded_current_metadata_without_payload_or_authority(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    result = observe(root, max_entries=0, max_bytes=0)
    assert result['schema'] == 'autoencoder-external-tree-descriptor-inventory@1'
    assert result['root_path'] == str(root)
    assert result['entry_count'] == result['apparent_bytes'] == 0
    assert result['entries'] == []
    assert result['root_identity']['inode'] == root.lstat().st_ino
    assert result['root_identity']['mode'] == root.lstat().st_mode
    assert result['metadata_only'] is True
    assert result['payload_files_opened'] is result['symlink_directories_enqueued'] is False
    assert result['directory_open_no_follow'] is True
    assert result['atomic_snapshot'] is result['continuous_custody_proved'] is False
    assert result['inventory_sha256'] == body_digest(result)


def test_internal_file_and_directory_aliases_are_preserved_and_not_recursed(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    sub = root / 'sub'
    sub.mkdir()
    (root / 'plain').write_bytes(b'123')
    (sub / 'data').write_bytes(b'45678')
    (root / 'alias-dir').symlink_to('sub', target_is_directory=True)
    (root / 'alias-file').symlink_to('sub/data')
    before = {p: (p.lstat().st_ino, p.lstat().st_size) for p in root.rglob('*')}
    result = observe(root)
    got = rows(result)
    assert set(got) == {'sub', 'plain', 'sub/data', 'alias-dir', 'alias-file'}
    assert result['entry_count'] == 5
    assert result['apparent_bytes'] == 3 + 5 + len('sub') + len('sub/data')
    assert got['alias-dir']['kind'] == got['alias-file']['kind'] == 'symlink'
    assert got['alias-dir']['link_target'] == 'sub'
    assert got['alias-file']['link_target'] == 'sub/data'
    assert all(not name.startswith('alias-dir/') for name in got)
    assert before == {p: (p.lstat().st_ino, p.lstat().st_size) for p in root.rglob('*')}
    assert result['inventory_sha256'] == body_digest(result)


def test_regular_hardlinks_count_each_path_and_disclose_link_count(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'first').write_bytes(b'linked')
    os.link(root / 'first', root / 'second')
    result = observe(root)
    first, second = rows(result)['first'], rows(result)['second']
    assert first['inode'] == second['inode']
    assert first['nlink'] == second['nlink'] == 2
    assert result['entry_count'] == 2
    assert result['apparent_bytes'] == 2 * len(b'linked')


def test_repeated_alias_with_different_remaining_components_is_not_a_cycle(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'payload').write_bytes(b'x')
    (root / 'dot').symlink_to('.', target_is_directory=True)
    (root / 'selected').symlink_to('dot/dot/payload')
    result = observe(root)
    assert rows(result)['selected']['kind'] == 'symlink'
    assert result['entry_count'] == 3
    assert result['apparent_bytes'] == 1 + len('.') + len('dot/dot/payload')


def test_dotdot_is_applied_after_expanding_directory_alias(tmp_path):
    root = tmp_path / 'root'
    (root / 'sub' / 'inner').mkdir(parents=True)
    (root / 'sub' / 'payload').write_bytes(b'inside-sub')
    (root / 'payload').write_bytes(b'root-file')
    (root / 'hop').symlink_to('sub/inner', target_is_directory=True)
    (root / 'selected').symlink_to('hop/../payload')
    result = observe(root)
    # The resolver must not collapse hop/.. lexically to the root file.
    selected = rows(result)['selected']
    assert selected['link_target'] == 'hop/../payload'
    assert selected['resolved_target'] == 'sub/payload'


@pytest.mark.parametrize('kind', ['relative_escape', 'absolute_escape', 'self_cycle',
    'two_link_cycle', 'dangling', 'file_dotdot'])
def test_unsafe_or_nonexistent_alias_targets_are_refused_without_following_payload(tmp_path, kind):
    root = tmp_path / 'root'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.write_bytes(b'outside payload is never opened')
    (root / 'file').write_bytes(b'not a directory')
    if kind == 'relative_escape':
        (root / 'bad').symlink_to('../outside')
    elif kind == 'absolute_escape':
        (root / 'bad').symlink_to(outside)
    elif kind == 'self_cycle':
        (root / 'bad').symlink_to('bad')
    elif kind == 'two_link_cycle':
        (root / 'bad').symlink_to('other')
        (root / 'other').symlink_to('bad')
    elif kind == 'dangling':
        (root / 'bad').symlink_to('missing')
    else:
        (root / 'bad').symlink_to('file/../file')
    with pytest.raises((ValueError, OSError)):
        observe(root)
    assert outside.read_bytes() == b'outside payload is never opened'
    assert (root / 'bad').is_symlink()


def test_inventory_never_opens_db_wal_auth_or_model_payloads(tmp_path, monkeypatch):
    root = tmp_path / 'root'
    root.mkdir()
    for name in ('metadata.duckdb', 'metadata.duckdb.wal', 'auth.json', 'model.safetensors'):
        (root / name).write_bytes(b'payload is opaque')
    original_open = os.open
    directory_opens = []

    def directories_only(path, flags, *args, **kwargs):
        assert flags & os.O_DIRECTORY, 'inventory opened a payload file'
        assert flags & os.O_NOFOLLOW
        directory_opens.append(path)
        return original_open(path, flags, *args, **kwargs)

    def no_payload(*args, **kwargs):
        raise AssertionError('inventory attempted a payload read')

    with monkeypatch.context() as patch:
        patch.setattr(os, 'open', directories_only)
        patch.setattr(os, 'read', no_payload)
        patch.setattr(builtins, 'open', no_payload)
        patch.setattr(Path, 'open', no_payload)
        result = observe(root)
    assert directory_opens
    assert result['apparent_bytes'] == 4 * len(b'payload is opaque')
    assert result['payload_files_opened'] is False


@pytest.mark.parametrize('boundary', ['entries', 'bytes', 'depth', 'hops'])
def test_entry_byte_depth_and_symlink_hop_limits_fail_closed(tmp_path, boundary):
    root = tmp_path / 'root'
    root.mkdir()
    if boundary == 'depth':
        (root / 'one' / 'two').mkdir(parents=True)
        changes = {'max_depth': 1}
    elif boundary == 'hops':
        (root / 'file').write_bytes(b'x')
        (root / 'alias').symlink_to('file')
        changes = {'max_symlink_hops': 0}
    else:
        (root / 'file').write_bytes(b'xy')
        changes = {'max_entries': 0} if boundary == 'entries' else {'max_bytes': 1}
    with pytest.raises((ValueError, OSError)):
        observe(root, **changes)


def test_entry_and_byte_limits_are_inclusive_and_include_link_inode_bytes(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'file').write_bytes(b'abc')
    (root / 'alias').symlink_to('file')
    result = observe(root, max_entries=2, max_bytes=3 + len('file'))
    assert result['entry_count'] == 2
    assert result['apparent_bytes'] == 7
    with pytest.raises(ValueError):
        observe(root, max_entries=2, max_bytes=6)


@pytest.mark.parametrize('field,value', [('max_entries', True), ('max_entries', -1),
    ('max_entries', 65537), ('max_bytes', 1.0), ('max_bytes', 2**63),
    ('max_depth', False), ('max_depth', 257), ('max_symlink_hops', '2')])
def test_invalid_bounds_refuse_before_opening_any_tree(monkeypatch, field, value):
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid bound reached filesystem')
    monkeypatch.setattr(os, 'open', forbidden)
    with pytest.raises(ValueError):
        observe(Path('/not-opened'), **{field: value})


def test_fifo_is_refused_and_only_test_owned_special_entry_is_cleaned(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    fifo = root / 'pipe'
    os.mkfifo(fifo)
    try:
        with pytest.raises(ValueError):
            observe(root)
    finally:
        fifo.unlink()


def test_replaced_opened_directory_cannot_be_reported_as_same_generation(tmp_path, monkeypatch):
    root = tmp_path / 'root'
    (root / 'sub').mkdir(parents=True)
    (root / 'sub' / 'payload').write_bytes(b'old')
    original = inventory._open_directory
    swapped = False

    def replace(parent_fd, name, expected):
        nonlocal swapped
        fd = original(parent_fd, name, expected)
        if name == 'sub' and not swapped:
            swapped = True
            (root / 'sub').rename(root / 'old-sub')
            (root / 'sub').mkdir()
        return fd

    monkeypatch.setattr(inventory, '_open_directory', replace)
    with pytest.raises((ValueError, OSError)):
        observe(root)
    assert swapped
    assert (root / 'old-sub' / 'payload').read_bytes() == b'old'


def test_root_alias_is_refused_instead_of_changing_the_charged_root(tmp_path):
    real = tmp_path / 'real'
    real.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        observe(alias)
    assert alias.is_symlink()


def test_two_unchanged_observations_match_but_real_metadata_change_changes_digest(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    path = root / 'payload'
    path.write_bytes(b'first')
    first = observe(root)
    assert observe(root) == first
    path.write_bytes(b'changed length')
    second = observe(root)
    assert second['inventory_sha256'] != first['inventory_sha256']
    assert second['inventory_sha256'] == body_digest(second)


@pytest.mark.parametrize('target', ['/not-observed-opaque-target/payload',
    'not-observed-opaque-target', 'opaque'])
def test_explicit_opaque_leaf_records_literal_without_target_resolution_or_access(tmp_path, monkeypatch, target):
    root = tmp_path / 'root'
    root.mkdir()
    link = root / 'opaque'
    link.symlink_to(target)
    manifest = [{'path': 'opaque', 'link_target': target}]
    original_open, original_stat = os.open, os.stat
    operations = []

    def directories_only(path, flags, *args, **kwargs):
        assert flags & os.O_DIRECTORY and flags & os.O_NOFOLLOW
        assert os.fsdecode(path) != 'opaque'
        assert 'not-observed-opaque-target' not in os.fsdecode(path)
        operations.append('directory-open')
        return original_open(path, flags, *args, **kwargs)

    def leaf_metadata_only(path, *args, **kwargs):
        assert kwargs.get('follow_symlinks') is False
        assert 'not-observed-opaque-target' not in os.fsdecode(path)
        operations.append('nofollow-stat')
        return original_stat(path, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError('opaque target resolution or payload access attempted')

    with monkeypatch.context() as patch:
        patch.setattr(os, 'open', directories_only)
        patch.setattr(os, 'stat', leaf_metadata_only)
        patch.setattr(os, 'read', forbidden)
        patch.setattr(builtins, 'open', forbidden)
        patch.setattr(Path, 'open', forbidden)
        patch.setattr(inventory._Observation, '_resolve', forbidden)
        result = observe(root, opaque_symlinks=manifest)
    assert operations
    assert result['schema'] == 'autoencoder-external-tree-descriptor-inventory@2'
    assert result['symlink_resolution'] == 'internal_except_explicit_opaque'
    assert result['opaque_symlinks'] == manifest
    assert result['opaque_link_referents_observed'] is False
    assert result['opaque_link_target_custody_asserted'] is False
    assert result['opaque_link_target_durability_asserted'] is False
    assert result['entry_count'] == 1
    assert result['apparent_bytes'] == len(os.fsencode(target))
    assert rows(result)['opaque']['link_target'] == target
    assert rows(result)['opaque']['resolved_target'] is None
    assert result['inventory_sha256'] == body_digest(result)
    manifest[0]['link_target'] = 'caller mutation must not alter sealed observation'
    assert result['opaque_symlinks'][0]['link_target'] == target


@pytest.mark.parametrize('manifest', [[], (), 'opaque',
    [{'path': '../opaque', 'link_target': 'outside'}],
    [{'path': '/opaque', 'link_target': 'outside'}],
    [{'path': 'sub/../opaque', 'link_target': 'outside'}],
    [{'path': 'opaque', 'link_target': ''}],
    [{'path': 'opaque', 'link_target': True}],
    [{'path': 'opaque', 'link_target': 'outside', 'extra': False}],
    [{'path': 'opaque', 'link_target': 'outside'}, {'path': 'opaque', 'link_target': 'outside'}]])
def test_opaque_opt_in_requires_nonempty_closed_canonical_manifest_before_tree_open(monkeypatch, manifest):
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid opaque manifest reached a filesystem open')
    monkeypatch.setattr(os, 'open', forbidden)
    with pytest.raises(ValueError):
        observe(Path('/not-opened'), opaque_symlinks=manifest)


@pytest.mark.parametrize('fault', ['missing_leaf', 'wrong_kind', 'changed_literal'])
def test_opaque_manifest_must_match_existing_symlink_exactly(tmp_path, fault):
    root = tmp_path / 'root'
    root.mkdir()
    if fault == 'wrong_kind':
        (root / 'opaque').write_bytes(b'regular file is not an opaque link')
    elif fault == 'changed_literal':
        (root / 'opaque').symlink_to('/actual-target')
    with pytest.raises((ValueError, OSError)):
        observe(root, opaque_symlinks=[{'path': 'opaque', 'link_target': '/declared-target'}])


def test_opaque_opt_in_does_not_allow_an_unlisted_escape_or_chain_through_opaque(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'opaque').symlink_to('/unobserved-target')
    manifest = [{'path': 'opaque', 'link_target': '/unobserved-target'}]
    ordinary = root / 'ordinary'
    ordinary.symlink_to('../outside')
    with pytest.raises((ValueError, OSError)):
        observe(root, opaque_symlinks=manifest)
    ordinary.unlink()
    ordinary.symlink_to('opaque')
    with pytest.raises((ValueError, OSError)):
        observe(root, opaque_symlinks=manifest)


def test_opaque_leaf_bytes_are_still_charged_and_generation_rechecked(tmp_path, monkeypatch):
    root = tmp_path / 'root'
    root.mkdir()
    link = root / 'opaque'
    target = '/unobserved-target'
    link.symlink_to(target)
    manifest = [{'path': 'opaque', 'link_target': target}]
    with pytest.raises(ValueError):
        observe(root, max_bytes=len(os.fsencode(target)) - 1, opaque_symlinks=manifest)
    original = os.readlink
    changed = False

    def replace_after_read(path, *args, **kwargs):
        nonlocal changed
        value = original(path, *args, **kwargs)
        if os.fsdecode(path) == 'opaque' and not changed:
            changed = True
            link.unlink()
            link.symlink_to(target + '-changed')
        return value

    monkeypatch.setattr(os, 'readlink', replace_after_read)
    with pytest.raises((ValueError, OSError)):
        observe(root, opaque_symlinks=manifest)
    assert changed
