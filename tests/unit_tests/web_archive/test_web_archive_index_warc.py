#!/usr/bin/env python3
import os


import pytest
from ipfs_datasets_py.web_archiving.web_archive import WebArchiveProcessor


IDX_EXTENSION = ".idx"
TEST_WARC = "test.warc"
TEST_OUTPUT_NAME = "test.idx"
ENCRYPTION_KEY = "secret_key_123"


@pytest.fixture
def processor():
    return WebArchiveProcessor()


@pytest.fixture
def temp_warc(tmp_path):
    warc = tmp_path / TEST_WARC
    warc.write_text("WARC/1.0\r\n")
    return str(warc)


class TestWebArchiveProcessorIndexWarc:
    """Tests for WebArchiveProcessor.index_warc."""

    def test_when_default_output_then_creates_idx_file(self, processor, temp_warc):
        """
        Given a valid WARC file with default output path.
        When index_warc is called.
        Then index file is created at warc path plus idx.
        """
        result = processor.index_warc(temp_warc)
        assert result == f"{temp_warc}{IDX_EXTENSION}", f"Expected {temp_warc}{IDX_EXTENSION}, got {result}"

    @pytest.mark.parametrize(
        "kwargs, description",
        [
            ({}, "default output"),
            ({"output_path": "__TMP__"}, "custom output path"),
            ({"encryption_key": ENCRYPTION_KEY}, "encryption enabled"),
        ],
    )
    def test_when_various_options_then_returns_string(self, processor, temp_warc, tmp_path, kwargs, description):
        """
        Given a valid WARC file.
        When index_warc is called with various options.
        Then the result is a string.
        """
        resolved_kwargs = dict(kwargs)
        if resolved_kwargs.get("output_path") == "__TMP__":
            resolved_kwargs["output_path"] = str(tmp_path / TEST_OUTPUT_NAME)
        result = processor.index_warc(temp_warc, **resolved_kwargs)
        assert isinstance(result, str), f"For {description}, expected str type, got {type(result)}"

    def test_when_creating_file_then_exists_at_path(self, processor, temp_warc):
        """
        Given a valid WARC file.
        When index_warc is called.
        Then index file is created at returned path.
        """
        result = processor.index_warc(temp_warc)
        assert os.path.exists(result), f"Expected '{result}' to exist, but it does not."

    def test_when_custom_output_then_returns_custom_path(self, processor, temp_warc, tmp_path):
        """
        Given a valid WARC file with custom output path.
        When index_warc is called.
        Then return path matches custom output path.
        """
        output_path = str(tmp_path / TEST_OUTPUT_NAME)
        result = processor.index_warc(temp_warc, output_path=output_path)
        assert result == output_path, f"Expected {output_path}, got {result}"

    def test_when_nonexistent_file_then_raises_error(self, processor):
        """
        Given a nonexistent WARC file path.
        When index_warc is called.
        Then FileNotFoundError is raised.
        """
        with pytest.raises(FileNotFoundError, match=r'nonexistent.warc') as exc_info:
            processor.index_warc("nonexistent.warc")

    def test_when_valid_file_then_contains_filesystem_path(self, processor, temp_warc):
        """
        Given a valid WARC file.
        When index_warc is called.
        Then string contains valid filesystem path.
        """
        result = processor.index_warc(temp_warc)
        assert len(result) > 0, f"Expected non-empty path, got {result}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
