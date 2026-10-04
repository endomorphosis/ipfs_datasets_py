"""Small real archives qualify staging mechanics, not installed Isabelle."""

import functools
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import threading
import time

import pytest

from ipfs_datasets_py.logic.backends.installers import isabelle as installer
from ipfs_datasets_py.logic.backends.installers import isabelle_install_worker as worker


def _pack(path, entries=None):
    if entries is None:
        entries = [(f"{installer.ISABELLE_VERSION}/bin/isabelle", b"not an executable: staging must never run this"),
                   (f"{installer.ISABELLE_VERSION}/etc/ISABELLE_IDENTIFIER", installer.ISABELLE_VERSION.encode())]
    with tarfile.open(path, "w:gz") as archive:
        for name, value in entries:
            member = tarfile.TarInfo(name)
            member.size = len(value)
            archive.addfile(member, io.BytesIO(value))
    return path


@pytest.fixture
def request_data(tmp_path):
    archive = _pack(tmp_path / "fixture.tar.gz")
    stage = tmp_path / ".stage"
    stage.mkdir(mode=0o700)
    return {"schema": worker.REQUEST_SCHEMA, "version": installer.ISABELLE_VERSION,
            "platform_key": "linux-aarch64", "artifact_url": archive.as_uri(),
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "cache_path": str(tmp_path / "downloads/fixture.tar.gz"),
            "staging_dir": str(stage), "timeout_seconds": 10, "allow_download": True}


def _digest(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _assert_result(result, request):
    assert result == {"schema": worker.RESULT_SCHEMA, "request_sha256": _digest(request),
                      "version": request["version"], "platform_key": request["platform_key"],
                      "sha256": request["sha256"], "archive_size_bytes": Path(request["cache_path"]).stat().st_size,
                      "candidate_relative_path": request["version"]}
    assert (Path(request["staging_dir"]) / result["candidate_relative_path"] / "bin/isabelle").is_file()


def test_real_local_download_extracts_without_any_native_or_publication_work(request_data, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("staging invoked a native probe or publication helper")
    for name in ("ensure_isabelle", "read_version_banner", "probe_theory_processor", "write_launcher"):
        monkeypatch.setattr(installer, name, forbidden)
    monkeypatch.setattr(installer.subprocess, "run", forbidden)
    original = dict(request_data)
    result = worker.stage_archive(request_data)
    _assert_result(result, original)
    assert request_data == original
    assert not (Path(request_data["staging_dir"]).parent / "bin").exists()
    assert not list(Path(request_data["cache_path"]).parent.glob("*.partial"))


def test_cached_verified_archive_never_opens_network(request_data, monkeypatch):
    cache = Path(request_data["cache_path"])
    cache.parent.mkdir()
    cache.write_bytes(Path(request_data["artifact_url"].removeprefix("file://")).read_bytes())
    monkeypatch.setattr(installer, "urlopen", lambda *_a, **_kw: pytest.fail("cache hit opened network"))
    _assert_result(worker.stage_archive(request_data), request_data)


@pytest.mark.parametrize("cached", ["verified", "missing", "corrupt"])
def test_cache_only_policy_never_calls_downloader(request_data, monkeypatch, cached):
    request_data["allow_download"] = False
    cache = Path(request_data["cache_path"])
    if cached != "missing":
        cache.parent.mkdir()
        cache.write_bytes(Path(request_data["artifact_url"].removeprefix("file://")).read_bytes()
                          if cached == "verified" else b"corrupt retained cache")
    monkeypatch.setattr(installer, "download_artifact", lambda *_a, **_kw: pytest.fail("offline policy called downloader"))
    monkeypatch.setattr(installer, "urlopen", lambda *_a, **_kw: pytest.fail("offline policy opened network"))
    if cached == "verified":
        _assert_result(worker.stage_archive(request_data), request_data)
    else:
        with pytest.raises((FileNotFoundError, worker.ArchiveStagingError)):
            worker.stage_archive(request_data)
        assert not list(Path(request_data["staging_dir"]).iterdir())
        if cached == "corrupt":
            assert cache.read_bytes() == b"corrupt retained cache"
        else:
            assert not cache.parent.exists()


def test_download_permission_is_mandatory_and_digest_bound(request_data):
    before = _digest(request_data)
    request_data["allow_download"] = False
    assert _digest(request_data) != before
    del request_data["allow_download"]
    with pytest.raises(worker.ArchiveStagingError, match="fields"):
        worker.stage_archive(request_data)


def test_fresh_interpreter_downloads_small_http_archive_and_writes_exact_receipt(request_data, tmp_path):
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass
    handler = functools.partial(QuietHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request_data["artifact_url"] = f"http://127.0.0.1:{server.server_port}/fixture.tar.gz"
        request_path, result_path = tmp_path / "request.json", tmp_path / "result.json"
        request_path.write_text(json.dumps(request_data))
        repo = Path(__file__).resolve().parents[4]
        environment = dict(os.environ, PYTHONPATH=str(repo))
        result = subprocess.run([sys.executable, "-P", "-m", worker.__name__, str(request_path), str(result_path)],
                                cwd=tmp_path, env=environment, text=True, capture_output=True, timeout=20)
        assert result.returncode == 0, result.stderr
        assert result_path.stat().st_size <= worker.MAX_MESSAGE_BYTES
        _assert_result(json.loads(result_path.read_text()), request_data)
        assert not result.stdout
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("key,value", [
    ("schema", "other@1"), ("version", "../escape"), ("version", "Isabelle2024"),
    ("platform_key", "arbitrary"), ("platform_key", ["linux-aarch64"]),
    ("sha256", "0" * 63), ("sha256", "A" * 64),
    ("timeout_seconds", 0), ("timeout_seconds", True), ("timeout_seconds", -1),
    ("timeout_seconds", 3601), ("timeout_seconds", float("inf")), ("timeout_seconds", float("nan")),
    ("artifact_url", "ftp://example.invalid/archive"), ("artifact_url", "file://remote/archive"),
    ("artifact_url", "http://user:password@example.invalid/archive"),
    ("artifact_url", "https://example.invalid/archive#fragment"), ("artifact_url", "http://\nexample.invalid/archive"),
    ("cache_path", "relative/archive"), ("cache_path", "/tmp/../archive"), ("staging_dir", "relative"),
    ("allow_download", 1), ("allow_download", "false"), ("allow_download", None),
])
def test_invalid_closed_request_refused_before_download(request_data, monkeypatch, key, value):
    request_data[key] = value
    monkeypatch.setattr(installer, "download_artifact", lambda *_a, **_kw: pytest.fail("invalid request touched network"))
    with pytest.raises((ValueError, TypeError)):
        worker.stage_archive(request_data)


@pytest.mark.parametrize("change", ["missing", "extra", "limit_override"])
def test_request_rejects_missing_extra_or_relaxed_limits(request_data, change):
    if change == "missing":
        del request_data["sha256"]
    else:
        request_data["extra" if change == "extra" else "max_download_bytes"] = 1
    with pytest.raises(worker.ArchiveStagingError, match="fields"):
        worker.stage_archive(request_data)


@pytest.mark.parametrize("kind", ["missing", "public", "populated", "symlink", "fifo", "cache_inside", "parent_symlink"])
def test_staging_requires_private_empty_direct_directory(request_data, tmp_path, kind):
    stage = Path(request_data["staging_dir"])
    if kind == "missing":
        stage.rmdir()
    elif kind == "public":
        stage.chmod(0o755)
    elif kind == "populated":
        (stage / "retained").write_text("keep")
    elif kind in ("symlink", "fifo"):
        stage.rmdir()
        if kind == "symlink":
            stage.symlink_to(tmp_path)
        else:
            os.mkfifo(stage)
    elif kind == "cache_inside":
        request_data["cache_path"] = str(stage / "archive")
    else:
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path)
        request_data["staging_dir"] = str(alias / ".stage")
    with pytest.raises((ValueError, OSError)):
        worker.stage_archive(request_data)
    assert not Path(request_data["cache_path"]).exists()


@pytest.mark.parametrize("kind", ["unwrapped", "wrong_version", "extra_top_level", "traversal", "version_file"])
def test_extraction_cannot_fallback_to_unbound_candidate(request_data, tmp_path, kind):
    entries = {
        "unwrapped": [("bin/isabelle", b"x")],
        "wrong_version": [("Isabelle2024/bin/isabelle", b"x")],
        "extra_top_level": [(f"{installer.ISABELLE_VERSION}/bin/isabelle", b"x"), ("extra", b"x")],
        "traversal": [("../escaped", b"x")],
        "version_file": [(installer.ISABELLE_VERSION, b"not a directory")],
    }[kind]
    archive = _pack(tmp_path / "fixture.tar.gz", entries)
    request_data["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises((ValueError, OSError, installer.IsabelleInstallerError)):
        worker.stage_archive(request_data)
    assert not (tmp_path / "escaped").exists()
    # Failed staging remains controller-owned; the worker never publishes it.
    assert Path(request_data["staging_dir"]).is_dir()
    assert not (tmp_path / installer.ISABELLE_VERSION).exists()


def test_wrong_checksum_preserves_previous_cache(request_data):
    cache = Path(request_data["cache_path"])
    cache.parent.mkdir()
    cache.write_bytes(b"previous")
    request_data["sha256"] = "0" * 64
    with pytest.raises(worker.ArchiveStagingError, match="checksum"):
        worker.stage_archive(request_data)
    assert cache.read_bytes() == b"previous"
    partials = Path(request_data["staging_dir"]) / ".download-partials"
    assert list(Path(request_data["staging_dir"]).iterdir()) == [partials]
    assert not list(partials.iterdir())
    assert not list(cache.parent.glob("*.partial"))


def test_changed_cache_after_download_cannot_produce_matching_receipt(request_data, monkeypatch):
    def changed(*_args, **_kwargs):
        cache = Path(request_data["cache_path"])
        cache.parent.mkdir()
        cache.write_bytes(b"replacement")
        return True
    monkeypatch.setattr(installer, "download_artifact", changed)
    with pytest.raises(worker.ArchiveStagingError, match="changed after download"):
        worker.stage_archive(request_data)
    assert not list(Path(request_data["staging_dir"]).iterdir())


def test_download_and_extraction_share_one_cooperative_deadline(request_data, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(installer.time, "monotonic", lambda: now[0])
    original = installer.download_artifact
    def download(*args, **kwargs):
        result = original(*args, **kwargs)
        now[0] += request_data["timeout_seconds"] + 1
        return result
    monkeypatch.setattr(installer, "download_artifact", download)
    monkeypatch.setattr(installer, "_safe_extract_tar", lambda *_a, **_kw: pytest.fail("expired operation extracted"))
    with pytest.raises(installer.IsabelleInstallerError, match="deadline"):
        worker.stage_archive(request_data)
    assert not list(Path(request_data["staging_dir"]).iterdir())


@pytest.mark.parametrize("kind", ["oversized", "duplicate", "fifo", "symlink", "nan"])
def test_cli_rejects_bounded_input_failures_without_result(tmp_path, kind, capsys):
    request, result = tmp_path / "request.json", tmp_path / "result.json"
    if kind == "oversized":
        request.write_bytes(b" " * (worker.MAX_MESSAGE_BYTES + 1))
    elif kind == "duplicate":
        request.write_text('{"schema": "a", "schema": "b"}')
    elif kind == "fifo":
        os.mkfifo(request)
    elif kind == "symlink":
        other = tmp_path / "other"
        other.write_text("{}")
        request.symlink_to(other)
    else:
        request.write_text('{"timeout_seconds": NaN}')
    assert worker.main([str(request), str(result)]) == 1
    assert not result.exists()
    assert "staging failed" in capsys.readouterr().err


def test_cli_request_growth_after_regular_stat_is_still_capped(tmp_path, monkeypatch):
    request = tmp_path / "request.json"
    request.write_text("{}")
    original = installer._open_regular
    def growing(path, cap):
        handle = original(path, cap)
        with path.open("ab") as append:
            append.write(b" " * (worker.MAX_MESSAGE_BYTES + 1))
        return handle
    monkeypatch.setattr(installer, "_open_regular", growing)
    with pytest.raises(worker.ArchiveStagingError, match="message cap"):
        worker._read_request(request)


def test_cli_failure_leaves_existing_result_unchanged(tmp_path):
    request, result = tmp_path / "request.json", tmp_path / "result.json"
    request.write_text("{}")
    result.write_text("historical")
    assert worker.main([str(request), str(result)]) == 1
    assert result.read_text() == "historical"


@pytest.mark.parametrize("kind", ["fifo", "symlink"])
def test_result_publication_replaces_special_path_without_following(tmp_path, kind):
    result, other = tmp_path / "result.json", tmp_path / "other"
    other.write_text("preserve")
    if kind == "fifo":
        os.mkfifo(result)
    else:
        result.symlink_to(other)
    worker._write_result(result, {"value": "done"})
    assert result.read_text() == '{"value":"done"}'
    assert not result.is_symlink()
    assert other.read_text() == "preserve"
    assert not list(tmp_path.glob(".isabelle-staging-result-*"))


@pytest.mark.parametrize("valid_checksum", [False, True])
def test_private_download_temporary_directory_preserves_atomic_cache(tmp_path, monkeypatch, valid_checksum):
    source = tmp_path / "source"
    source.write_bytes(b"replacement")
    cache = tmp_path / "cache/archive"
    cache.parent.mkdir()
    cache.write_bytes(b"previous")
    partials = tmp_path / "private-partials"
    partials.mkdir(mode=0o700)
    created = []
    original = installer.tempfile.mkstemp
    def record(*args, **kwargs):
        assert cache.read_bytes() == b"previous"
        created.append(Path(kwargs["dir"]))
        return original(*args, **kwargs)
    monkeypatch.setattr(installer.tempfile, "mkstemp", record)
    checksum = hashlib.sha256(b"replacement").hexdigest() if valid_checksum else "0" * 64
    assert installer.download_artifact(source.as_uri(), cache, sha256=checksum,
                                      _temporary_directory=partials) is valid_checksum
    assert created == [partials]
    assert cache.read_bytes() == (b"replacement" if valid_checksum else b"previous")
    assert not list(partials.iterdir())
    assert not list(cache.parent.glob("*.partial"))


def test_worker_download_partial_files_live_only_in_staging(request_data, monkeypatch):
    directories = []
    original = installer.tempfile.mkstemp
    def record(*args, **kwargs):
        directories.append(Path(kwargs["dir"]))
        return original(*args, **kwargs)
    monkeypatch.setattr(installer.tempfile, "mkstemp", record)
    _assert_result(worker.stage_archive(request_data), request_data)
    partials = Path(request_data["staging_dir"]) / ".download-partials"
    assert directories == [partials]
    assert not partials.exists()


@pytest.mark.skipif(os.name != "posix", reason="qualification requires a real SIGKILL")
def test_hard_killed_slow_download_leaves_partial_only_in_controller_staging(request_data, tmp_path):
    archive = _pack(tmp_path / "fixture.tar.gz", [(f"{installer.ISABELLE_VERSION}/payload", os.urandom(512 * 1024))])
    body = archive.read_bytes()
    request_data["sha256"] = hashlib.sha256(body).hexdigest()
    cache = Path(request_data["cache_path"])
    cache.parent.mkdir()
    cache.write_bytes(b"previous verified cache")
    release_response = threading.Event()
    class SlowHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body[:128 * 1024])
                self.wfile.flush()
                release_response.wait(10)
                self.wfile.write(body[128 * 1024:])
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    process = None
    try:
        request_data["artifact_url"] = f"http://127.0.0.1:{server.server_port}/archive"
        request_path, result_path = tmp_path / "request.json", tmp_path / "result.json"
        request_path.write_text(json.dumps(request_data))
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[4]))
        process = subprocess.Popen([sys.executable, "-P", "-m", worker.__name__, str(request_path), str(result_path)],
                                   cwd=tmp_path, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        partials = Path(request_data["staging_dir"]) / ".download-partials"
        deadline = time.monotonic() + 5
        partial = None
        while time.monotonic() < deadline and process.poll() is None:
            candidates = list(partials.glob("*.partial"))
            if candidates and candidates[0].stat().st_size > 0:
                partial = candidates[0]
                break
            time.sleep(0.01)
        assert partial is not None, "worker did not reach an incomplete staged download"
        process.kill()
        process.communicate(timeout=5)
        assert process.returncode == -9
        assert 0 < partial.stat().st_size <= 128 * 1024
        assert not list(cache.parent.glob("*.partial"))
        assert cache.read_bytes() == b"previous verified cache"
        assert not result_path.exists()
        assert not (Path(request_data["staging_dir"]) / installer.ISABELLE_VERSION).exists()
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        release_response.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
