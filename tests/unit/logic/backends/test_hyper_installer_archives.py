"""Bounded archive acquisition/extraction with no external network or builds."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import io
from pathlib import Path
import tarfile
import threading

import pytest

from ipfs_datasets_py.logic.backends.installers import hyperproperty as hp
from ipfs_datasets_py.logic.backends.installers import install_control as control
from ipfs_datasets_py.logic.backends.smt.operation_budget import ProofOperationCancelled


COMMIT = "1" * 40
ROOT_NAME = "fixture-" + COMMIT
URL = "https://fixture.invalid/source.tar.gz"


def digest(body):
    return hashlib.sha256(body).hexdigest()


def limits(**changes):
    return replace(control.HyperInstallLimits(), operation_timeout_ms=3000, **changes)


class Response(io.BytesIO):
    def __init__(self, body, *, final_url=URL, content_length=True, chunk_size=8, on_read=None):
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body))} if content_length else {}
        self.final_url, self.chunk_size, self.on_read = final_url, chunk_size, on_read
        self.read_sizes = []

    def geturl(self):
        return self.final_url

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self, size=-1):
        self.read_sizes.append(size)
        assert size > 0, "archive transfer must request bounded chunks"
        if self.on_read is not None:
            self.on_read(self)
        return super().read(min(size, self.chunk_size))


def install_response(monkeypatch, response):
    calls = []
    def open_fixture(request, timeout):
        calls.append((request.full_url, timeout))
        return response
    monkeypatch.setattr(hp, "urlopen", open_fixture)
    return calls


def archive(tmp_path, entries):
    path = tmp_path / "source.tar.gz"
    with tarfile.open(path, "w:gz") as bundle:
        for name, body, kind, link in entries:
            member = tarfile.TarInfo(name)
            member.type, member.mode = kind, 0o755 if kind == tarfile.DIRTYPE else 0o644
            member.linkname = link
            member.size = len(body) if kind == tarfile.REGTYPE else 0
            bundle.addfile(member, io.BytesIO(body) if kind == tarfile.REGTYPE else None)
    return path


def regular(name, body=b"x"):
    return (name, body, tarfile.REGTYPE, "")


def assert_only_cache(root, destination=None):
    files = [path for path in root.rglob('*') if path.is_file()]
    assert files == ([] if destination is None else [destination])


@pytest.mark.parametrize("content_length", [True, False])
def test_fresh_download_accepts_exact_byte_ceiling_and_cleans_temporary_file(tmp_path, monkeypatch, content_length):
    body = b"a" * 64
    response = Response(body, content_length=content_length)
    calls = install_response(monkeypatch, response)
    destination = tmp_path / "cache" / "source.tar.gz"
    with control.installation_scope(limits=limits(max_download_bytes=64)):
        result = hp._download_verified_archive(URL, destination, digest(body))
    assert result == destination and destination.read_bytes() == body
    assert calls and 0 < calls[0][1] <= 3 and response.read_sizes
    assert_only_cache(destination.parent, destination)


@pytest.mark.parametrize("content_length", [True, False])
def test_download_limit_failure_preserves_old_cache(tmp_path, monkeypatch, content_length):
    body = b"a" * 65
    destination = tmp_path / "cache" / "source.tar.gz"
    destination.parent.mkdir(); destination.write_bytes(b"old cache")
    install_response(monkeypatch, Response(body, content_length=content_length))
    with control.installation_scope(limits=limits(max_download_bytes=64)):
        with pytest.raises(hp.HyperpropertyInstallBlocked) as failure:
            hp._download_verified_archive(URL, destination, digest(body))
    assert "source_archive_download_limit" in failure.value.block_reasons
    assert destination.read_bytes() == b"old cache"
    assert_only_cache(destination.parent, destination)


def test_download_digest_mismatch_cannot_replace_existing_cache(tmp_path, monkeypatch):
    destination = tmp_path / "source.tar.gz"; destination.write_bytes(b"old")
    install_response(monkeypatch, Response(b"unreviewed"))
    with control.installation_scope(limits=limits()):
        with pytest.raises(hp.HyperpropertyInstallBlocked) as failure:
            hp._download_verified_archive(URL, destination, digest(b"reviewed"))
    assert "source_archive_digest_mismatch" in failure.value.block_reasons
    assert destination.read_bytes() == b"old"
    assert_only_cache(tmp_path, destination)


def test_verified_cache_reuse_never_opens_network(tmp_path, monkeypatch):
    body = b"reviewed cache"
    destination = tmp_path / "source.tar.gz"; destination.write_bytes(body)
    monkeypatch.setattr(hp, "urlopen", lambda *args, **kwargs: pytest.fail("verified cache opened network"))
    with control.installation_scope(limits=limits()):
        assert hp._download_verified_archive(URL, destination, digest(body)) == destination
    assert destination.read_bytes() == body


def test_corrupt_cache_is_replaced_only_after_verified_transfer(tmp_path, monkeypatch):
    body = b"reviewed replacement"
    destination = tmp_path / "source.tar.gz"; destination.write_bytes(b"corrupt")
    install_response(monkeypatch, Response(body))
    with control.installation_scope(limits=limits()):
        hp._download_verified_archive(URL, destination, digest(body))
    assert destination.read_bytes() == body
    assert_only_cache(tmp_path, destination)


def test_interrupted_stream_removes_partial_download(tmp_path, monkeypatch):
    def drop(response):
        if response.tell() >= 8:
            raise OSError("fixture connection dropped")
    body = b"a" * 32
    install_response(monkeypatch, Response(body, on_read=drop))
    with control.installation_scope(limits=limits()):
        with pytest.raises(hp.HyperpropertyInstallBlocked) as failure:
            hp._download_verified_archive(URL, tmp_path / "source.tar.gz", digest(body))
    assert "source_archive_fetch_failed" in failure.value.block_reasons
    assert_only_cache(tmp_path)


def test_download_cancellation_propagates_and_removes_partial(tmp_path, monkeypatch):
    cancellation = threading.Event()
    response = Response(b"a" * 32, on_read=lambda _: cancellation.set())
    install_response(monkeypatch, response)
    with pytest.raises(ProofOperationCancelled):
        with control.installation_scope(limits=limits(), cancellation=cancellation):
            hp._download_verified_archive(URL, tmp_path / "source.tar.gz", digest(b"a" * 32))
    assert_only_cache(tmp_path)


@pytest.mark.parametrize("url", ["http://example.com/source", "file:///tmp/source", "ftp://example.com/source", "data:text/plain,test"])
def test_unapproved_download_scheme_is_rejected_before_network(tmp_path, monkeypatch, url):
    monkeypatch.setattr(hp, "urlopen", lambda *args, **kwargs: pytest.fail("unapproved URL opened"))
    with control.installation_scope(limits=limits()):
        with pytest.raises(hp.HyperpropertyInstallerError):
            hp._download_verified_archive(url, tmp_path / "source.tar.gz", digest(b"data"))
    assert_only_cache(tmp_path)


@pytest.mark.parametrize("url", ["http://127.0.0.1:8123/source", "http://[::1]:8123/source"])
def test_numeric_loopback_http_is_available_for_controlled_fixtures(tmp_path, monkeypatch, url):
    body = b"local controlled archive"
    calls = install_response(monkeypatch, Response(body, final_url=url))
    destination = tmp_path / "source.tar.gz"
    with control.installation_scope(limits=limits()):
        hp._download_verified_archive(url, destination, digest(body))
    assert calls[0][0] == url and destination.read_bytes() == body


def test_redirect_to_unapproved_scheme_cannot_publish(tmp_path, monkeypatch):
    install_response(monkeypatch, Response(b"data", final_url="http://example.com/unreviewed"))
    with control.installation_scope(limits=limits()):
        with pytest.raises(hp.HyperpropertyInstallerError):
            hp._download_verified_archive(URL, tmp_path / "source.tar.gz", digest(b"data"))
    assert_only_cache(tmp_path)


@pytest.mark.parametrize("expected", ["0" * 63, "G" * 64, "A" * 64])
def test_invalid_checksum_rejected_before_network(tmp_path, monkeypatch, expected):
    monkeypatch.setattr(hp, "urlopen", lambda *args, **kwargs: pytest.fail("invalid digest opened network"))
    with pytest.raises(hp.HyperpropertyInstallerError):
        hp._download_verified_archive(URL, tmp_path / "source.tar.gz", expected)


def test_parallel_downloads_use_distinct_owned_temporary_files(tmp_path, monkeypatch):
    body, barrier, observed, lock = b"reviewed concurrent archive", threading.Barrier(2), [], threading.Lock()
    destination = tmp_path / "source.tar.gz"
    def open_fixture(request, timeout):
        def inspect(response):
            if response.tell() == 0:
                barrier.wait(timeout=2)
                with lock:
                    observed.append(tuple(sorted(path.name for path in tmp_path.iterdir() if path.is_file())))
                barrier.wait(timeout=2)
        return Response(body, on_read=inspect)
    monkeypatch.setattr(hp, "urlopen", open_fixture)
    def acquire():
        with control.installation_scope(limits=limits()):
            return hp._download_verified_archive(URL, destination, digest(body))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(acquire) for _ in range(2)]
        assert [future.result(timeout=4) for future in futures] == [destination, destination]
    assert any(len(names) == 2 and names[0] != names[1] for names in observed)
    assert destination.read_bytes() == body
    assert_only_cache(tmp_path, destination)


def test_extract_exact_file_and_aggregate_limits(tmp_path):
    source = archive(tmp_path, [regular(ROOT_NAME + '/a', b'a' * 64), regular(ROOT_NAME + '/b', b'b' * 64)])
    with control.installation_scope(limits=limits(max_member_bytes=64, max_extract_bytes=128, max_archive_members=2)):
        root = hp._safe_extract_source_archive(source, tmp_path / 'out', COMMIT)
    assert root.name == ROOT_NAME and (root/'a').read_bytes() == b'a' * 64 and (root/'b').read_bytes() == b'b' * 64


@pytest.mark.parametrize('kind,body,link', [(tarfile.SYMTYPE,b'', '../outside'), (tarfile.LNKTYPE,b'',ROOT_NAME+'/file'),
    (tarfile.FIFOTYPE,b'',''), (tarfile.CHRTYPE,b'','')])
def test_archive_special_objects_are_rejected(tmp_path, kind, body, link):
    source = archive(tmp_path, [regular(ROOT_NAME+'/file'), (ROOT_NAME+'/object',body,kind,link)])
    with control.installation_scope(limits=limits()):
        with pytest.raises(hp.HyperpropertyInstallBlocked) as failure:
            hp._safe_extract_source_archive(source, tmp_path/'out', COMMIT)
    assert 'source_archive_extraction_failed' in failure.value.block_reasons
    assert not (tmp_path/'outside').exists()


@pytest.mark.parametrize('name', ['../escaped', ROOT_NAME+'/../../escaped', '/absolute/escaped'])
def test_archive_path_escape_is_rejected(tmp_path, name):
    source = archive(tmp_path, [regular(name)])
    with control.installation_scope(limits=limits()):
        with pytest.raises(hp.HyperpropertyInstallBlocked) as failure:
            hp._safe_extract_source_archive(source, tmp_path/'out', COMMIT)
    assert 'source_archive_extraction_failed' in failure.value.block_reasons
    assert not (tmp_path/'escaped').exists()


def test_duplicate_archive_members_cannot_overwrite(tmp_path):
    source = archive(tmp_path, [regular(ROOT_NAME+'/same',b'first'),regular(ROOT_NAME+'/same',b'second')])
    with control.installation_scope(limits=limits()):
        with pytest.raises(hp.HyperpropertyInstallBlocked) as failure:
            hp._safe_extract_source_archive(source,tmp_path/'out',COMMIT)
    assert 'source_archive_extraction_failed' in failure.value.block_reasons


@pytest.mark.parametrize('entries', [
    [regular(ROOT_NAME+'/file'),regular('extra-file')],
    [regular(ROOT_NAME+'/file'),regular('other-'+COMMIT+'/file')],
    [regular('fixture-'+'2'*40+'/file')],
])
def test_archive_requires_exactly_one_commit_bound_root(tmp_path, entries):
    source = archive(tmp_path, entries)
    with control.installation_scope(limits=limits()):
        with pytest.raises(hp.HyperpropertyInstallBlocked) as failure:
            hp._safe_extract_source_archive(source,tmp_path/'out',COMMIT)
    assert set(failure.value.block_reasons) & {'source_archive_commit_mismatch','source_archive_extraction_failed'}


@pytest.mark.parametrize('overrides,entries', [
    ({'max_member_bytes':64}, [regular(ROOT_NAME+'/file',b'x'*65)]),
    ({'max_extract_bytes':128}, [regular(ROOT_NAME+'/a',b'x'*64),regular(ROOT_NAME+'/b',b'x'*65)]),
    ({'max_archive_members':2}, [regular(ROOT_NAME+'/'+str(index)) for index in range(3)]),
    ({'max_archive_depth':2}, [regular(ROOT_NAME+'/nested/file')]),
    ({'max_path_bytes':64}, [regular(ROOT_NAME+'/'+'x'*64)]),
])
def test_archive_expansion_has_finite_limits(tmp_path, overrides, entries):
    source = archive(tmp_path, entries)
    with control.installation_scope(limits=limits(**overrides)):
        with pytest.raises(hp.HyperpropertyInstallBlocked) as failure:
            hp._safe_extract_source_archive(source,tmp_path/'out',COMMIT)
    assert 'source_archive_extraction_limit' in failure.value.block_reasons


def test_extract_cancellation_propagates_without_publication(tmp_path):
    source = archive(tmp_path,[regular(ROOT_NAME+'/file')])
    cancelled = threading.Event(); cancelled.set()
    with pytest.raises(ProofOperationCancelled):
        with control.installation_scope(limits=limits(),cancellation=cancelled):
            hp._safe_extract_source_archive(source,tmp_path/'out',COMMIT)
    assert not (tmp_path/'out'/ROOT_NAME/'file').exists()
