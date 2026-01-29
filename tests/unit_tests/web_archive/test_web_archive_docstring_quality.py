#!/usr/bin/env python3
import pytest
import os

# Make sure the input file and documentation file exist.
# assert os.path.exists('web_archive.py'), "web_archive.py does not exist at the specified directory."
# assert os.path.exists('web_archive_stubs.md'), "Documentation for web_archive.py does not exist at the specified directory."

from ipfs_datasets_py.web_archiving.web_archive import (
    WebArchive,
    WebArchiveProcessor,
    _is_valid_http_url,
    archive_web_content,
    retrieve_web_content,
    create_web_archive
)

from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)


class TestWebArchiveDocstringQuality:
    """Test docstring quality for all web archive callables."""

    def test_web_archive_init_docstring_quality(self):
        """
        Ensure that the docstring of the WebArchive.__init__ method meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(WebArchive.__init__)
        except Exception as e:
            pytest.fail(f"Callable metadata in WebArchive.__init__ does not meet standards: {e}")

    def test_web_archive_processor_init_docstring_quality(self):
        """
        Ensure that the docstring of the WebArchiveProcessor.__init__ method meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(WebArchiveProcessor.__init__)
        except Exception as e:
            pytest.fail(f"Callable metadata in WebArchiveProcessor.__init__ does not meet standards: {e}")

    def test_archive_url_docstring_quality(self):
        """
        Ensure that the docstring of the WebArchive.archive_url method meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(WebArchive.archive_url)
        except Exception as e:
            pytest.fail(f"Callable metadata in WebArchive.archive_url does not meet standards: {e}")

    def test_retrieve_archive_docstring_quality(self):
        """
        Ensure that the docstring of the WebArchive.retrieve_archive method meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(WebArchive.retrieve_archive)
        except Exception as e:
            pytest.fail(f"Callable metadata in WebArchive.retrieve_archive does not meet standards: {e}")

    def test_list_archives_docstring_quality(self):
        """
        Ensure that the docstring of the WebArchive.list_archives method meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(WebArchive.list_archives)
        except Exception as e:
            pytest.fail(f"Callable metadata in WebArchive.list_archives does not meet standards: {e}")

    def test_process_urls_docstring_quality(self):
        """
        Ensure that the docstring of the WebArchiveProcessor.process_urls method meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(WebArchiveProcessor.process_urls)
        except Exception as e:
            pytest.fail(f"Callable metadata in WebArchiveProcessor.process_urls does not meet standards: {e}")

    def test_extract_text_from_html_docstring_quality(self):
        """
        Ensure that the docstring of the WebArchiveProcessor.extract_text_from_html method meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(WebArchiveProcessor.extract_text_from_html)
        except Exception as e:
            pytest.fail(f"Callable metadata in WebArchiveProcessor.extract_text_from_html does not meet standards: {e}")

    def test_search_archives_docstring_quality(self):
        """
        Ensure that the docstring of the WebArchiveProcessor.search_archives method meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(WebArchiveProcessor.search_archives)
        except Exception as e:
            pytest.fail(f"Callable metadata in WebArchiveProcessor.search_archives does not meet standards: {e}")

    def test_create_warc_docstring_quality(self):
        """
        Ensure that the docstring of the WebArchiveProcessor.create_warc method meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(WebArchiveProcessor.create_warc)
        except Exception as e:
            pytest.fail(f"Callable metadata in WebArchiveProcessor.create_warc does not meet standards: {e}")

    def test_extract_text_from_warc_docstring_quality(self):
        """
        Ensure that the docstring of the WebArchiveProcessor.extract_text_from_warc method meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(WebArchiveProcessor.extract_text_from_warc)
        except Exception as e:
            pytest.fail(f"Callable metadata in WebArchiveProcessor.extract_text_from_warc does not meet standards: {e}")

    def test_extract_links_from_warc_docstring_quality(self):
        """
        Ensure that the docstring of the WebArchiveProcessor.extract_links_from_warc method meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(WebArchiveProcessor.extract_links_from_warc)
        except Exception as e:
            pytest.fail(f"Callable metadata in WebArchiveProcessor.extract_links_from_warc does not meet standards: {e}")

    def test_extract_metadata_from_warc_docstring_quality(self):
        """
        Ensure that the docstring of the WebArchiveProcessor.extract_metadata_from_warc method meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(WebArchiveProcessor.extract_metadata_from_warc)
        except Exception as e:
            pytest.fail(f"Callable metadata in WebArchiveProcessor.extract_metadata_from_warc does not meet standards: {e}")

    def test_index_warc_docstring_quality(self):
        """
        Ensure that the docstring of the WebArchiveProcessor.index_warc method meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(WebArchiveProcessor.index_warc)
        except Exception as e:
            pytest.fail(f"Callable metadata in WebArchiveProcessor.index_warc does not meet standards: {e}")

    def test_extract_dataset_from_cdxj_docstring_quality(self):
        """
        Ensure that the docstring of the WebArchiveProcessor.extract_dataset_from_cdxj method meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(WebArchiveProcessor.extract_dataset_from_cdxj)
        except Exception as e:
            pytest.fail(f"Callable metadata in WebArchiveProcessor.extract_dataset_from_cdxj does not meet standards: {e}")

    def test_process_html_content_docstring_quality(self):
        """
        Ensure that the docstring of the WebArchiveProcessor.process_html_content method meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(WebArchiveProcessor.process_html_content)
        except Exception as e:
            pytest.fail(f"Callable metadata in WebArchiveProcessor.process_html_content does not meet standards: {e}")

    def test_is_valid_http_url_docstring_quality(self):
        """
        Ensure that the docstring of the _is_valid_http_url function meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(_is_valid_http_url)
        except Exception as e:
            pytest.fail(f"Callable metadata in _is_valid_http_url does not meet standards: {e}")

    def test_archive_web_content_docstring_quality(self):
        """
        Ensure that the docstring of the archive_web_content function meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(archive_web_content)
        except Exception as e:
            pytest.fail(f"Callable metadata in archive_web_content does not meet standards: {e}")

    def test_retrieve_web_content_docstring_quality(self):
        """
        Ensure that the docstring of the retrieve_web_content function meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(retrieve_web_content)
        except Exception as e:
            pytest.fail(f"Callable metadata in retrieve_web_content does not meet standards: {e}")

    def test_create_web_archive_docstring_quality(self):
        """
        Ensure that the docstring of the create_web_archive function meets the standards set forth in `_example_docstring_format.md`.
        """
        try:
            has_good_callable_metadata(create_web_archive)
        except Exception as e:
            pytest.fail(f"Callable metadata in create_web_archive does not meet standards: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])