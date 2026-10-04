"""Streaming artifact limits, publication failure and real HTTP transport."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
from pathlib import Path
import threading

import pytest

from ipfs_datasets_py.logic.backends.installers import state_model as installer


class Response:
    def __init__(self, payload, headers=None, after_read=None):
        self.stream = io.BytesIO(payload)
        self.headers = headers or {}
        self.read_sizes = []
        self.after_read = after_read

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, size):
        assert 0 < size <= 64 * 1024
        self.read_sizes.append(size)
        data = self.stream.read(size)
        if self.after_read:
            self.after_read()
        return data


def install_response(monkeypatch, response):
    def open_response(*_, **kwargs):
        assert 0 < kwargs["timeout"] <= 10
        return response
    monkeypatch.setattr(installer, "urlopen", open_response)


def test_large_download_is_streamed_and_exact_cache_hit_avoids_network(monkeypatch, tmp_path):
    payload = b"bounded-chunk" * 200_000
    response = Response(payload, {"Content-Length": str(len(payload))})
    install_response(monkeypatch, response)
    path = tmp_path / "artifact"
    expected = hashlib.sha256(payload).hexdigest()
    assert installer.download_artifact("https://fixture.invalid/a", path, sha256=expected) == (True, expected)
    assert path.read_bytes() == payload and len(response.read_sizes) > 30
    monkeypatch.setattr(installer, "urlopen", lambda *_a, **_k: pytest.fail("cache hit opened network"))
    assert installer.download_artifact("https://fixture.invalid/a", path, sha256=expected) == (True, expected)
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize("headers,payload", [
    ({"Content-Length": "33"}, b"small"),
    ({}, b"x" * 33),
    ({"Content-Length": "-1"}, b"small"),
    ({"Content-Length": "x"}, b"small"),
    ({"Content-Length": "99999999999999999999999999999999999999"}, b"small"),
    ({"Content-Length": "20"}, b"short"),
    ({"Content-Length": "2"}, b"longer"),
])
def test_overflow_and_length_mismatch_preserve_destination_and_clean_partial(monkeypatch, tmp_path, headers, payload):
    response = Response(payload, headers)
    install_response(monkeypatch, response)
    path = tmp_path / "artifact"
    path.write_bytes(b"previous")
    assert installer.download_artifact("https://fixture.invalid/a", path,
        sha256="0" * 64, max_download_bytes=32) == (False, None)
    assert path.read_bytes() == b"previous"
    assert not list(tmp_path.glob("*.partial"))
    if headers.get("Content-Length") == "33":
        assert not response.read_sizes


def test_cancellation_during_read_withholds_publication(monkeypatch, tmp_path):
    signal = threading.Event()
    install_response(monkeypatch, Response(b"new", after_read=signal.set))
    path = tmp_path / "artifact"
    path.write_bytes(b"previous")
    assert installer.download_artifact("https://fixture.invalid/a", path,
        sha256=hashlib.sha256(b"new").hexdigest(), cancellation=signal) == (False, None)
    assert path.read_bytes() == b"previous"
    assert not list(tmp_path.glob("*.partial"))


def test_pre_cancelled_download_does_not_create_directory_or_open_network(monkeypatch, tmp_path):
    signal = threading.Event()
    signal.set()
    monkeypatch.setattr(installer, "urlopen", lambda *_a, **_k: pytest.fail("cancelled download opened network"))
    path = tmp_path / "absent" / "artifact"
    assert installer.download_artifact("https://fixture.invalid/a", path, cancellation=signal) == (False, None)
    assert not path.parent.exists()


def test_deadline_checked_after_read_before_publication(monkeypatch, tmp_path):
    now = [100.0]
    monkeypatch.setattr(installer.time, "monotonic", lambda: now[0])
    response = Response(b"new", after_read=lambda: now.__setitem__(0, 102.0))
    install_response(monkeypatch, response)
    path = tmp_path / "artifact"
    assert installer.download_artifact("https://fixture.invalid/a", path, timeout=1) == (False, None)
    assert not path.exists() and not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize("failure", ["checksum", "fsync", "read"])
def test_failed_stream_never_replaces_existing_artifact(monkeypatch, tmp_path, failure):
    response = Response(b"new")
    if failure == "read":
        response.after_read = lambda: (_ for _ in ()).throw(OSError("lost transport"))
    if failure == "fsync":
        monkeypatch.setattr(installer.os, "fsync", lambda *_: (_ for _ in ()).throw(OSError("disk failure")))
    install_response(monkeypatch, response)
    path = tmp_path / "artifact"
    path.write_bytes(b"previous")
    expected = "0" * 64 if failure == "checksum" else hashlib.sha256(b"new").hexdigest()
    assert installer.download_artifact("https://fixture.invalid/a", path, sha256=expected) == (False, None)
    assert path.read_bytes() == b"previous" and not list(tmp_path.glob("*.partial"))


def test_cached_artifact_byte_cap_precedes_hash_or_network(monkeypatch, tmp_path):
    path = tmp_path / "artifact"
    path.write_bytes(b"x" * 33)
    monkeypatch.setattr(installer, "content_sha256", lambda *_: pytest.fail("oversized cache was hashed"))
    assert installer.download_artifact("https://fixture.invalid/a", path, max_download_bytes=32) == (False, None)


def test_cached_file_growth_after_stat_still_honors_cumulative_cap(monkeypatch, tmp_path):
    path = tmp_path / "artifact"
    path.write_bytes(b"initial")
    original = Path.open
    def growing_open(self, mode="r", *args, **kwargs):
        if self == path and mode == "rb":
            with original(self, "ab") as append:
                append.write(b"x" * 40)
        return original(self, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", growing_open)
    monkeypatch.setattr(installer, "urlopen", lambda *_a, **_k: pytest.fail("oversized cache opened network"))
    assert installer.download_artifact("https://fixture.invalid/a", path, max_download_bytes=32) == (False, None)


def test_cached_hash_checks_cancellation_between_bounded_reads(monkeypatch, tmp_path):
    path = tmp_path / "artifact"
    path.write_bytes(b"x" * 200_000)
    signal = threading.Event()
    response = Response(path.read_bytes(), after_read=signal.set)
    original = Path.open
    monkeypatch.setattr(Path, "open", lambda self, mode="r", *args, **kwargs:
                        response if self == path and mode == "rb" else original(self, mode, *args, **kwargs))
    monkeypatch.setattr(installer, "urlopen", lambda *_a, **_k: pytest.fail("cancelled cache opened network"))
    assert installer.download_artifact("https://fixture.invalid/a", path, cancellation=signal) == (False, None)
    assert response.read_sizes == [64 * 1024]


@pytest.mark.parametrize("values", [
    {"max_download_bytes": True}, {"max_download_bytes": 0}, {"max_download_bytes": -1},
    {"timeout": True}, {"timeout": 0}, {"timeout": float("inf")}, {"cancellation": object()},
])
def test_invalid_limits_fail_before_io(tmp_path, values):
    with pytest.raises((ValueError, TypeError)):
        installer.download_artifact("https://fixture.invalid/a", tmp_path / "artifact", **values)


def test_fresh_download_through_real_http_response_and_atomic_publication(tmp_path):
    payload = b"real-http-stream\x00" * 80_000
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            for offset in range(0, len(payload), 16 * 1024):
                self.wfile.write(payload[offset:offset + 16 * 1024])

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        path = tmp_path / "new" / "artifact"
        expected = hashlib.sha256(payload).hexdigest()
        assert installer.download_artifact(f"http://127.0.0.1:{server.server_port}/artifact", path,
            sha256=expected, max_download_bytes=len(payload), timeout=5) == (True, expected)
        assert path.read_bytes() == payload and not list(path.parent.glob("*.partial"))
    finally:
        server.shutdown()
        server.server_close()
        worker.join(3)
    assert not worker.is_alive()
