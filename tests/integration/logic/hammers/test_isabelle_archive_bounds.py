"""Actual local archive transactions with bounded cache, tar and lock work.

Small executable fixtures test installation mechanics, not Isabelle proofs.
"""
from concurrent.futures import ThreadPoolExecutor
import functools
import hashlib
import gzip
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import os
from pathlib import Path
import tarfile
import threading
import time

import pytest

from ipfs_datasets_py.logic.backends.installers import isabelle as installer


class Response:
    def __init__(self, data, headers=None, after_read=None):
        self.stream = io.BytesIO(data)
        self.headers = headers or {}
        self.after_read = after_read
        self.read_sizes = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, size):
        assert 0 < size <= 64 * 1024
        self.read_sizes.append(size)
        value = self.stream.read(size)
        if self.after_read:
            self.after_read()
        return value


def response(monkeypatch, value):
    def open_response(*_, **kwargs):
        assert 0 < kwargs['timeout'] <= 10
        return value
    monkeypatch.setattr(installer, 'urlopen', open_response)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def archive(path, entries):
    with tarfile.open(path, 'w:gz') as handle:
        for item in entries:
            if isinstance(item, tarfile.TarInfo):
                handle.addfile(item)
            else:
                name, data = item
                member = tarfile.TarInfo(name)
                member.size = len(data)
                member.mode = 0o755 if name.endswith('isabelle') else 0o644
                handle.addfile(member, io.BytesIO(data))
    return path


def link(name, target, *, hard=False):
    member = tarfile.TarInfo(name)
    member.type = tarfile.LNKTYPE if hard else tarfile.SYMTYPE
    member.linkname = target
    return member


def extract(path, target, **kwargs):
    installer._safe_extract_tar(path, target, min_free_bytes=0, **kwargs)


def test_streaming_download_cache_hit_and_bounded_reads(tmp_path, monkeypatch):
    data = b'bounded-download' * 40_000
    stream = Response(data, {'Content-Length': str(len(data))})
    response(monkeypatch, stream)
    target = tmp_path / 'artifact'
    assert installer.download_artifact('https://fixture.invalid/archive', target, sha256=digest(data))
    assert target.read_bytes() == data and len(stream.read_sizes) > 5
    monkeypatch.setattr(installer, 'urlopen', lambda *_a, **_k: pytest.fail('cache hit opened network'))
    assert installer.download_artifact('https://fixture.invalid/archive', target, sha256=digest(data))
    assert not list(tmp_path.glob('*.partial'))


@pytest.mark.parametrize('header,data', [
    ('33', b'small'), ('-1', b'small'), ('bad', b'small'), (' 5', b'small'),
    ('999999999999999999999999999999', b'small'), ('20', b'short'), ('2', b'longer'), (None, b'x' * 33),
])
def test_declared_and_cumulative_bounds_preserve_previous_file(tmp_path, monkeypatch, header, data):
    response(monkeypatch, Response(data, {} if header is None else {'Content-Length': header}))
    target = tmp_path / 'artifact'
    target.write_bytes(b'previous')
    assert not installer.download_artifact('https://fixture.invalid/archive', target, sha256=digest(data), max_bytes=32)
    assert target.read_bytes() == b'previous'
    assert not list(tmp_path.glob('*.partial'))


@pytest.mark.parametrize('failure', ['cancel', 'deadline', 'fsync', 'checksum', 'replace'])
def test_stream_failure_never_publishes_or_leaves_partial(tmp_path, monkeypatch, failure):
    signal = threading.Event()
    now = [10.0]
    monkeypatch.setattr(installer.time, 'monotonic', lambda: now[0])
    data = b'new'
    after = signal.set if failure == 'cancel' else (lambda: now.__setitem__(0, 12.0)) if failure == 'deadline' else None
    response(monkeypatch, Response(data, after_read=after))
    if failure == 'fsync':
        monkeypatch.setattr(installer.os, 'fsync', lambda *_: (_ for _ in ()).throw(OSError('disk error')))
    if failure == 'replace':
        monkeypatch.setattr(Path, 'replace', lambda *_: (_ for _ in ()).throw(OSError('rename error')))
    target = tmp_path / 'artifact'
    target.write_bytes(b'previous')
    assert not installer.download_artifact('https://fixture.invalid/archive', target,
        sha256='0' * 64 if failure == 'checksum' else digest(data), cancellation=signal, timeout=1)
    assert target.read_bytes() == b'previous' and not list(tmp_path.glob('*.partial'))


@pytest.mark.parametrize('kind', ['oversized', 'fifo', 'symlink'])
def test_invalid_cache_refused_before_network(tmp_path, monkeypatch, kind):
    target = tmp_path / 'artifact'
    if kind == 'oversized':
        target.write_bytes(b'x' * 33)
    elif kind == 'fifo':
        os.mkfifo(target)
    else:
        other = tmp_path / 'other'
        other.write_bytes(b'ok')
        target.symlink_to(other)
    monkeypatch.setattr(installer, 'urlopen', lambda *_a, **_k: pytest.fail('invalid cache opened network'))
    assert not installer.download_artifact('https://fixture.invalid/archive', target, sha256='0' * 64, max_bytes=32)
    assert target.exists()


def test_cached_growth_is_capped_after_open(tmp_path, monkeypatch):
    target = tmp_path / 'artifact'
    target.write_bytes(b'x')
    original = installer._open_regular
    def growing(path, cap):
        opened = original(path, cap)
        with path.open('ab') as append:
            append.write(b'x' * 40)
        return opened
    monkeypatch.setattr(installer, '_open_regular', growing)
    monkeypatch.setattr(installer, 'urlopen', lambda *_a, **_k: pytest.fail('overflow opened network'))
    assert not installer.download_artifact('https://fixture.invalid/archive', target, sha256=digest(b'x' * 41), max_bytes=32)
    assert target.stat().st_size == 41


def test_cached_cancellation_checked_between_chunks(tmp_path, monkeypatch):
    target = tmp_path / 'artifact'
    data = b'x' * 200_000
    target.write_bytes(data)
    signal = threading.Event()
    cached = Response(data, after_read=signal.set)
    monkeypatch.setattr(installer, '_open_regular', lambda *_: cached)
    monkeypatch.setattr(installer, 'urlopen', lambda *_a, **_k: pytest.fail('cancelled cache opened network'))
    assert not installer.download_artifact('https://fixture.invalid/archive', target, sha256=digest(data), cancellation=signal)
    assert cached.read_sizes == [64 * 1024]


@pytest.mark.parametrize('values', [{'max_bytes': True}, {'max_bytes': 0}, {'timeout': 0},
                                   {'timeout': float('inf')}, {'timeout': True}, {'cancellation': object()}])
def test_invalid_download_limits_fail_before_io(tmp_path, values):
    with pytest.raises((ValueError, TypeError)):
        installer.download_artifact('https://fixture.invalid/archive', tmp_path / 'absent/artifact', sha256='0' * 64, **values)
    assert not (tmp_path / 'absent').exists()


def test_pre_cancelled_operation_creates_no_paths(tmp_path, monkeypatch):
    signal = threading.Event()
    signal.set()
    monkeypatch.setattr(installer, 'urlopen', lambda *_a, **_k: pytest.fail('cancelled operation opened network'))
    target = tmp_path / 'absent/artifact'
    assert not installer.download_artifact('https://fixture.invalid/archive', target, sha256='0' * 64, cancellation=signal)
    result = installer.ensure_isabelle(yes=True, strict=False, install_root=tmp_path / 'absent', cancellation=signal)
    assert result.reason_codes == ['cancelled'] and not target.parent.exists()


def test_archive_regular_data_internal_links_and_executable_mode(tmp_path):
    packed = archive(tmp_path / 'a.tar.gz', [('Isabelle/bin/isabelle', b'#!/bin/sh\nexit 0\n'),
        link('Isabelle/bin/alias', 'isabelle'), link('Isabelle/bin/hard', 'Isabelle/bin/isabelle', hard=True)])
    target = tmp_path / 'out'
    extract(packed, target)
    executable = target / 'Isabelle/bin/isabelle'
    assert executable.stat().st_mode & 0o111
    assert (target / 'Isabelle/bin/alias').read_bytes() == executable.read_bytes()
    assert (target / 'Isabelle/bin/hard').stat().st_ino == executable.stat().st_ino


@pytest.mark.parametrize('limits,entries,message', [
    ({'max_file_bytes': 8}, [('a', b'x' * 9)], 'per-file'),
    ({'max_expanded_bytes': 10}, [('a', b'x' * 6), ('b', b'x' * 6)], 'expanded'),
    ({'max_members': 1}, [('a', b'x'), ('b', b'x')], 'count'),
    ({'max_path_bytes': 4}, [('long-name', b'x')], 'path'),
    ({'max_total_path_bytes': 3}, [('aa', b'x'), ('bb', b'x')], 'path'),
    ({}, [('../escape', b'x')], 'escapes'),
    ({}, [('/absolute', b'x')], 'escapes'),
    ({}, [('a/' * 65 + 'file', b'x')], 'depth'),
    ({}, [('same', b'first'), ('same', b'second')], 'duplicate'),
    ({}, [link('escape', '../outside')], 'escapes'),
    ({}, [link('directory', 'real'), ('directory/file', b'x')], 'symlink'),
    ({}, [link('hard', 'missing', hard=True)], 'earlier regular'),
])
def test_archive_refuses_expansion_and_path_violations(tmp_path, limits, entries, message):
    packed = archive(tmp_path / 'a.tar.gz', entries)
    with pytest.raises(installer.IsabelleInstallerError, match=message):
        extract(packed, tmp_path / 'out', **limits)
    assert not (tmp_path / 'escape').exists()


@pytest.mark.parametrize('kind', [tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.GNUTYPE_SPARSE])
def test_special_archive_members_refused(tmp_path, kind):
    member = tarfile.TarInfo('special')
    member.type = kind
    packed = archive(tmp_path / 'a.tar.gz', [member])
    with pytest.raises(installer.IsabelleInstallerError, match='nonregular|sparse'):
        extract(packed, tmp_path / 'out')


@pytest.mark.parametrize('kind', [tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK, tarfile.XHDTYPE, tarfile.XGLTYPE])
def test_oversized_metadata_refused_before_declared_body_is_read(tmp_path, kind):
    # A header alone declares 512 MiB of metadata. No matching body exists:
    # refusal must come from the metadata guard, not EOF after an allocation.
    member = tarfile.TarInfo('metadata')
    member.type = kind
    member.size = 512 * 1024**2
    packed = tmp_path / 'a.tar'
    packed.write_bytes(member.tobuf())
    with pytest.raises(installer.IsabelleInstallerError, match='metadata byte cap'):
        extract(packed, tmp_path / 'out')


def test_sparse_pax_metadata_refused_before_sparse_parser(tmp_path):
    member = tarfile.TarInfo('sparse')
    member.pax_headers = {'GNU.sparse.major': '1', 'GNU.sparse.minor': '0'}
    packed = archive(tmp_path / 'a.tar.gz', [member])
    with pytest.raises(installer.IsabelleInstallerError, match='sparse'):
        extract(packed, tmp_path / 'out')


def test_nested_extended_headers_have_a_recursion_cap(tmp_path):
    member = tarfile.TarInfo('longname')
    member.type = tarfile.GNUTYPE_LONGNAME
    member.size = 2
    packed = tmp_path / 'a.tar'
    packed.write_bytes((member.tobuf() + b'a\0' + b'\0' * 510) * 20)
    with pytest.raises(installer.IsabelleInstallerError, match='header count'):
        extract(packed, tmp_path / 'out')


def test_truncated_regular_member_is_never_accepted(tmp_path):
    member = tarfile.TarInfo('file')
    member.size = 1000
    packed = tmp_path / 'a.tar'
    packed.write_bytes(member.tobuf() + b'truncated')
    with pytest.raises((installer.IsabelleInstallerError, tarfile.ReadError)):
        extract(packed, tmp_path / 'out')


def test_metadata_has_a_cumulative_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, '_MAX_TOTAL_TAR_METADATA_BYTES', 100)
    first = tarfile.TarInfo('first')
    second = tarfile.TarInfo('second')
    first.pax_headers = second.pax_headers = {'comment': 'x' * 60}
    packed = archive(tmp_path / 'a.tar.gz', [first, second])
    with pytest.raises(installer.IsabelleInstallerError, match='metadata byte cap'):
        extract(packed, tmp_path / 'out')


@pytest.mark.parametrize('compression', ['bz2', 'xz'])
def test_unbounded_decoder_formats_refused_before_tar_parser(tmp_path, monkeypatch, compression):
    packed = tmp_path / 'a.tar.compressed'
    with tarfile.open(packed, 'w:' + compression) as handle:
        member = tarfile.TarInfo('file')
        member.size = 1
        handle.addfile(member, io.BytesIO(b'x'))
    monkeypatch.setattr(installer.tarfile, 'open', lambda *_a, **_k: pytest.fail('unsupported decoder reached parser'))
    with pytest.raises(installer.IsabelleInstallerError, match='only gzip or plain'):
        extract(packed, tmp_path / 'out')


def test_gzip_trailing_zero_expansion_honors_decompressed_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, '_MAX_TOTAL_TAR_METADATA_BYTES', 128)
    packed = tmp_path / 'a.tar.gz'
    packed.write_bytes(gzip.compress(b'\0' * 256_000))
    with pytest.raises(installer.IsabelleInstallerError, match='decompressed stream byte cap'):
        extract(packed, tmp_path / 'out', max_expanded_bytes=16, max_members=1)


@pytest.mark.parametrize('corruption', ['crc', 'truncated', 'hidden_data'])
def test_gzip_trailer_and_tar_terminator_are_checked(tmp_path, corruption):
    packed = archive(tmp_path / 'a.tar.gz', [('file', b'data')])
    data = packed.read_bytes()
    if corruption == 'crc':
        packed.write_bytes(data[:-8] + bytes([data[-8] ^ 1]) + data[-7:])
    elif corruption == 'truncated':
        packed.write_bytes(data[:-4])
    else:
        packed.write_bytes(gzip.compress(gzip.decompress(data) + b'hidden-data'))
    with pytest.raises((installer.IsabelleInstallerError, gzip.BadGzipFile, EOFError, tarfile.ReadError)):
        extract(packed, tmp_path / 'out')


def test_existing_destination_link_cannot_be_followed(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    target = tmp_path / 'out'
    target.symlink_to(outside, target_is_directory=True)
    packed = archive(tmp_path / 'a.tar.gz', [('file', b'data')])
    with pytest.raises(installer.IsabelleInstallerError, match='symlink'):
        extract(packed, target)
    assert not list(outside.iterdir())


def test_disk_pressure_during_extraction_stops_bounded_copy(tmp_path, monkeypatch):
    packed = archive(tmp_path / 'a.tar.gz', [('large', b'x' * 200_000)])
    checks = [0]
    def remaining(_):
        checks[0] += 1
        return 1_000_000 if checks[0] <= 3 else 50
    monkeypatch.setattr(installer, 'free_storage_bytes', remaining)
    with pytest.raises(installer.IsabelleInstallerError, match='disk headroom'):
        installer._safe_extract_tar(packed, tmp_path / 'out', min_free_bytes=100)
    assert (tmp_path / 'out/large').stat().st_size <= 64 * 1024


@pytest.mark.parametrize('interruption', ['cancel', 'deadline'])
def test_extraction_interruptions_stop_between_payload_copies(tmp_path, monkeypatch, interruption):
    packed = archive(tmp_path / 'a.tar.gz', [('large', b'x' * 200_000)])
    signal = threading.Event()
    now = [10.0]
    checks = [0]
    monkeypatch.setattr(installer.time, 'monotonic', lambda: now[0])
    def remaining(_):
        checks[0] += 1
        if checks[0] == 4:
            if interruption == 'cancel':
                signal.set()
            else:
                now[0] = 12.0
        return 1_000_000
    monkeypatch.setattr(installer, 'free_storage_bytes', remaining)
    with pytest.raises(installer.IsabelleInstallerError, match='cancelled|deadline'):
        extract(packed, tmp_path / 'out', cancellation=signal, timeout=1)
    assert (tmp_path / 'out/large').stat().st_size <= 64 * 1024


@pytest.fixture
def local_archive(tmp_path, monkeypatch):
    script = b'#!/bin/sh\nif [ "$1" = version ]; then echo Isabelle2025-2; exit 0; fi\nif [ "$1" = process_theories ]; then echo "Usage: isabelle process_theories [OPTIONS]"; exit 1; fi\nexit 1\n'
    packed = archive(tmp_path / 'archive.tar.gz', [('Isabelle2025-2/bin/isabelle', script),
        ('Isabelle2025-2/data', b'x' * 150_000), link('Isabelle2025-2/link', 'data')])
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    pin = installer.ToolPin('isabelle', installer.ISABELLE_VERSION, installer.detect_platform_key(),
        f'http://127.0.0.1:{server.server_port}/archive.tar.gz', digest(packed.read_bytes()))
    monkeypatch.setattr(installer, 'select_strict_pin', lambda *_a, **_k: pin)
    try:
        yield pin, packed
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_fresh_real_http_download_extract_publish_and_exact_reuse(tmp_path, local_archive):
    root = tmp_path / 'install'
    result = installer.ensure_isabelle(yes=True, install_root=root, max_expanded_bytes=200_000)
    assert result.installed and result.download_attempted and result.checksum_verified
    assert result.bindings['archive_limits']['expanded_bytes'] == 200_000
    assert (root / 'Isabelle2025-2/link').read_bytes() == b'x' * 150_000
    again = installer.ensure_isabelle(yes=True, install_root=root)
    assert again.already_present and not again.download_attempted
    assert not list(root.rglob('*.partial')) and not list(root.glob('.extract-*'))


def test_extraction_failure_keeps_old_tree_and_cleans_staging(tmp_path, local_archive):
    root = tmp_path / 'install'
    old = root / 'Isabelle2025-2/keep'
    old.parent.mkdir(parents=True)
    old.write_text('original')
    with pytest.raises(installer.IsabelleInstallerError, match='expanded'):
        installer.ensure_isabelle(yes=True, force=True, install_root=root, max_expanded_bytes=1000)
    assert old.read_text() == 'original' and not (root / 'bin/isabelle').exists()
    assert not list(root.glob('.extract-*'))


def test_nonstrict_expansion_refusal_returns_failed_receipt(tmp_path, local_archive):
    root = tmp_path / 'install'
    result = installer.ensure_isabelle(yes=True, strict=False, install_root=root, max_expanded_bytes=1000)
    assert result.status == 'failed' and not result.installed
    assert result.reason_codes == ['archive_extraction_failed']
    assert not list(root.glob('.extract-*')) and not (root / 'bin/isabelle').exists()


@pytest.mark.parametrize('failure', ['version', 'theory', 'cancel', 'launcher_write'])
def test_late_publication_failure_restores_both_previous_paths(tmp_path, local_archive, monkeypatch, failure):
    root = tmp_path / 'install'
    old = root / 'Isabelle2025-2/keep'
    old.parent.mkdir(parents=True)
    old.write_text('original-tree')
    launcher = root / 'bin/isabelle'
    launcher.parent.mkdir()
    launcher.write_text('original-launcher')
    signal = threading.Event()
    original_version = installer.read_version_banner
    original_theory = installer.probe_theory_processor
    if failure in ('version', 'cancel'):
        def version(path, **kwargs):
            if path == str(launcher):
                if failure == 'cancel':
                    signal.set()
                return 'WrongVersion'
            return original_version(path, **kwargs)
        monkeypatch.setattr(installer, 'read_version_banner', version)
    elif failure == 'theory':
        monkeypatch.setattr(installer, 'probe_theory_processor', lambda path:
            False if path == str(launcher) else original_theory(path))
    else:
        monkeypatch.setattr(installer, 'write_launcher', lambda *_a, **_k:
            (_ for _ in ()).throw(OSError('failed launcher write')))
    with pytest.raises((installer.IsabelleInstallerError, OSError)):
        installer.ensure_isabelle(yes=True, force=True, install_root=root, cancellation=signal)
    assert old.read_text() == 'original-tree' and launcher.read_text() == 'original-launcher'
    assert not list(root.glob('.previous-*')) and not list(root.glob('.extract-*'))
    assert not (launcher.parent / '.isabelle.previous').exists()


@pytest.mark.parametrize('lock_type', ['thread', 'file'])
def test_lock_wait_honors_overall_deadline(tmp_path, lock_type):
    root = tmp_path / 'install'
    root.mkdir()
    release = threading.Event()
    held = threading.Event()
    def holder():
        if lock_type == 'thread':
            with installer._INSTALL_MUTEX:
                held.set()
                release.wait(2)
        else:
            import fcntl
            with (root / '.isabelle-install.lock').open('a') as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                held.set()
                release.wait(2)
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    thread = threading.Thread(target=holder)
    thread.start()
    assert held.wait(1)
    started = time.monotonic()
    try:
        result = installer.ensure_isabelle(yes=True, strict=False, install_root=root, timeout_seconds=0.06)
        assert result.reason_codes == ['deadline_exceeded']
        assert time.monotonic() - started < 0.5
    finally:
        release.set()
        thread.join(timeout=2)


@pytest.mark.parametrize('kind', ['fifo', 'symlink'])
def test_nonregular_install_lock_refused_without_waiting(tmp_path, kind):
    root = tmp_path / 'install'
    root.mkdir()
    path = root / '.isabelle-install.lock'
    if kind == 'fifo':
        os.mkfifo(path)
    else:
        path.symlink_to(root / 'missing')
    with pytest.raises((OSError, installer.IsabelleInstallerError)):
        installer.ensure_isabelle(yes=True, install_root=root, timeout_seconds=0.1)


@pytest.mark.parametrize('kind', ['fifo', 'symlink'])
def test_launcher_uses_private_temp_and_never_opens_stale_predictable_name(tmp_path, kind):
    root = tmp_path / 'install'
    (root / 'bin').mkdir(parents=True)
    sentinel = root / 'bin/isabelle.new'
    outside = tmp_path / 'outside'
    outside.write_text('preserved')
    if kind == 'fifo':
        os.mkfifo(sentinel)
    else:
        sentinel.symlink_to(outside)
    target = tmp_path / 'tool'
    target.write_text('#!/bin/sh\nexit 0\n')
    launcher = installer.write_launcher('isabelle', target, install_root=root)
    assert launcher.is_file() and launcher.stat().st_mode & 0o111
    assert outside.read_text() == 'preserved' and sentinel.exists()
    assert not list((root / 'bin').glob('.isabelle.*.new'))


def test_parallel_downloads_use_private_partials(tmp_path, monkeypatch):
    data = b'concurrent'
    barrier = threading.Barrier(2)
    partials = []
    original = installer.tempfile.mkstemp
    def create(*args, **kwargs):
        result = original(*args, **kwargs)
        partials.append(result[1])
        barrier.wait(timeout=2)
        return result
    monkeypatch.setattr(installer.tempfile, 'mkstemp', create)
    monkeypatch.setattr(installer, 'urlopen', lambda *_a, **_k: Response(data))
    target = tmp_path / 'artifact'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: installer.download_artifact('https://fixture.invalid/archive', target, sha256=digest(data)), range(2)))
    assert all(results) and len(set(partials)) == 2
    assert target.read_bytes() == data and not list(tmp_path.glob('*.partial'))
