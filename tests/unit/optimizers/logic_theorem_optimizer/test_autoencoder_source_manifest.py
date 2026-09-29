"""Full content binding must survive faster filesystem traversal."""
import hashlib
import os

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_native_pool as pools


def reference(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*.py")) if p.is_file()}


def test_manifest_matches_full_content_reference_and_portable_fallback(tmp_path, monkeypatch):
    (tmp_path / "nested.py").mkdir()
    (tmp_path / "nested.py" / "café.py").write_bytes(b"content\n")
    (tmp_path / "empty.py").write_bytes(b"")
    (tmp_path / "ignore.txt").write_bytes(b"not source")
    expected = reference(tmp_path)
    assert pools._source_entries(tmp_path) == expected
    monkeypatch.delattr(pools.os, "fwalk")
    assert pools._source_entries(tmp_path) == expected


def test_manifest_rehashes_same_size_restored_mtime_and_detects_renames(tmp_path):
    source = tmp_path / "source.py"
    source.write_bytes(b"first")
    before = source.stat()
    initial = pools._source_entries(tmp_path)
    source.write_bytes(b"other")
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    changed = pools._source_entries(tmp_path)
    assert changed != initial and changed == reference(tmp_path)
    source.rename(tmp_path / "renamed.py")
    assert pools._source_entries(tmp_path) != changed
    (tmp_path / "renamed.py").unlink()
    assert pools._source_entries(tmp_path) == {}


@pytest.mark.parametrize("directory", [False, True])
def test_python_aliases_fail_even_when_target_is_inside_root(tmp_path, directory):
    target = tmp_path / "target"
    if directory:
        target.mkdir()
    else:
        target.write_bytes(b"content")
    (tmp_path / "alias.py").symlink_to(target, target_is_directory=directory)
    with pytest.raises(ValueError, match="aliases"):
        pools._source_entries(tmp_path)


def test_non_python_directory_alias_is_not_traversed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "hidden.py").write_bytes(b"outside")
    (root / "alias").symlink_to(outside, target_is_directory=True)
    assert pools._source_entries(root) == {}


def test_symlink_substitution_between_stat_and_open_fails(tmp_path, monkeypatch):
    source = tmp_path / "source.py"
    source.write_bytes(b"source")
    replacement = tmp_path / "replacement.txt"
    replacement.write_bytes(b"replacement")
    original = pools.os.open

    def race(path, *args, **kwargs):
        if path == "source.py":
            source.unlink()
            source.symlink_to(replacement)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(pools.os, "open", race)
    with pytest.raises(OSError):
        pools._source_entries(tmp_path)


def test_content_mutation_during_hash_fails(tmp_path, monkeypatch):
    source = tmp_path / "source.py"
    source.write_bytes(b"first")
    original = pools.hashlib.sha256

    def race(data):
        if data == b"first":
            source.write_bytes(b"other")
        return original(data)

    monkeypatch.setattr(pools.hashlib, "sha256", race)
    with pytest.raises(ValueError, match="changed during read"):
        pools._source_entries(tmp_path)


def test_nonregular_python_file_fails_without_blocking(tmp_path):
    os.mkfifo(tmp_path / "fifo.py")
    with pytest.raises(ValueError, match="not regular"):
        pools._source_entries(tmp_path)
