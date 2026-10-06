"""Streaming source identity preserves byte-exact ordinary raw CIDs."""
import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    ContentIdentityError, cid_for_byte_chunks, cid_for_bytes,
)


@pytest.mark.parametrize("body", [b"", b"abc", bytes(range(256)), b"\x00" * 1025, "caf\u00e9\n".encode()])
@pytest.mark.parametrize("frame_size", [1, 7, 1024])
def test_streamed_identity_matches_complete_source_at_every_boundary(body, frame_size):
    seen = []
    def frames():
        for start in range(0, len(body), frame_size):
            frame = body[start:start + frame_size]
            seen.append(frame)
            yield frame
    assert cid_for_byte_chunks(frames(), max_chunk_bytes=frame_size) == cid_for_bytes(body)
    assert b"".join(seen) == body


def test_empty_frames_preserve_the_original_source_identity():
    assert cid_for_byte_chunks(iter([b"", b"ab", b"", b"c", b""]), max_chunk_bytes=2) == cid_for_bytes(b"abc")


@pytest.mark.parametrize("limit", [False, True, None, "1", 1.0, 0, -1])
def test_invalid_frame_limit_refuses_before_consuming_source(limit):
    def forbidden():
        pytest.fail("invalid frame budget consumed the source")
        yield b"abc"
    with pytest.raises(ContentIdentityError):
        cid_for_byte_chunks(forbidden(), max_chunk_bytes=limit)


@pytest.mark.parametrize("frame", ["abc", bytearray(b"abc"), memoryview(b"abc"), None, 7])
def test_non_exact_byte_frames_fail_without_a_content_identity(frame):
    with pytest.raises(TypeError):
        cid_for_byte_chunks(iter([b"a", frame]), max_chunk_bytes=3)


def test_oversized_frame_refuses_before_consuming_the_next_frame():
    def frames():
        yield b"abcd"
        pytest.fail("read beyond a rejected source frame")
    with pytest.raises(ContentIdentityError, match="exceeds"):
        cid_for_byte_chunks(frames(), max_chunk_bytes=3)


def test_incomplete_source_iteration_never_returns_a_content_identity():
    def frames():
        yield b"abc"
        raise OSError("source became unavailable")
    with pytest.raises(OSError, match="unavailable"):
        cid_for_byte_chunks(frames(), max_chunk_bytes=3)
