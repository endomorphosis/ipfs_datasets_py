"""Lexical reuse must retain every fresh metadata observation."""
from pathlib import Path
import stat
import pytest
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources


def _reference(root, directory):
    named = Path(root['path'])
    if resources._root_identity(named) != root:
        raise resources.DaemonResourceError('storage root identity changed')
    components = Path(directory).relative_to(named).parts
    current = named
    for component in components:
        current = current / component
        try:
            info = current.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise resources.DaemonResourceError('invalid descendant')
    return current


@pytest.mark.parametrize('depth', [0, 1, 6])
def test_precomputed_spelling_preserves_lstat_and_stat_order(tmp_path, monkeypatch, depth):
    root = tmp_path / 'named'
    target = root.joinpath(*(f'level{i}' for i in range(depth)))
    target.mkdir(parents=True)
    identity = resources._root_identity(root)
    lexical = (root, (*reversed(root.parents), root))
    original_stat = Path.stat
    observed = []
    def record(path, *, follow_symlinks=True):
        observed.append((str(path), follow_symlinks))
        return original_stat(path, follow_symlinks=follow_symlinks)
    monkeypatch.setattr(Path, 'stat', record)
    assert _reference(identity, target) == target
    reference = list(observed)
    observed.clear()
    assert resources._inventory_descendant(identity, target, lexical_root=lexical) == target
    assert observed == reference
    observed.clear()
    assert resources._inventory_descendant(identity, target, lexical_root=lexical) == target
    assert observed == reference  # Fresh observations even on an identical call.


def test_precomputed_spelling_does_not_reuse_root_identity(tmp_path):
    root = tmp_path / 'named'; target = root / 'child'; target.mkdir(parents=True)
    identity = resources._root_identity(root)
    lexical = (root, (*reversed(root.parents), root))
    assert resources._inventory_descendant(identity, target, lexical_root=lexical) == target
    root.rename(tmp_path / 'old')
    target.mkdir(parents=True)
    with pytest.raises(resources.DaemonResourceError, match='identity changed'):
        resources._inventory_descendant(identity, target, lexical_root=lexical)


@pytest.mark.parametrize('change', ['delete', 'symlink', 'file'])
def test_precomputed_spelling_rechecks_descendant_type(tmp_path, change):
    root = tmp_path / 'named'; target = root / 'child'; target.mkdir(parents=True)
    identity = resources._root_identity(root)
    lexical = (root, (*reversed(root.parents), root))
    assert resources._inventory_descendant(identity, target, lexical_root=lexical) == target
    target.rmdir()
    if change == 'delete':
        assert resources._inventory_descendant(identity, target, lexical_root=lexical) is None
    else:
        if change == 'symlink': target.symlink_to(tmp_path / 'absent')
        else: target.write_bytes(b'file')
        with pytest.raises(resources.DaemonResourceError, match='symlink|non-directory'):
            resources._inventory_descendant(identity, target, lexical_root=lexical)


def test_sibling_with_same_text_prefix_remains_outside_root(tmp_path):
    root = tmp_path / 'named'; root.mkdir()
    sibling = tmp_path / 'named-other'; sibling.mkdir()
    identity = resources._root_identity(root)
    with pytest.raises(resources.DaemonResourceError, match='outside'):
        resources._inventory_descendant(identity, sibling, lexical_root=(root, (*reversed(root.parents), root)))
