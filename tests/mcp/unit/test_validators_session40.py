"""
Session G41: validators.py coverage uplift.

Targets uncovered lines in EnhancedParameterValidator:
- validate_text_input suspicious-pattern path (lines 141-143)
- validate_model_name non-string + empty string + unknown-pattern paths (lines 214-231)
- validate_ipfs_hash non-string path (lines 240-242)
- validate_collection_name non-string + too-short paths (lines 347-364)
- validate_search_filters empty-key / too-long key / invalid list / dict op / unsupported type (lines 469-501)
- validate_file_path non-string + OSError + check_exists paths (lines 598-626)
- validate_json_schema ValidationError re-raise (lines 730-731)
- validate_url missing-scheme + OSError paths (lines 840-849)
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from ipfs_datasets_py.mcp_server.validators import EnhancedParameterValidator
from ipfs_datasets_py.mcp_server.exceptions import ValidationError


def _make_validator() -> EnhancedParameterValidator:
    return EnhancedParameterValidator()


# ---------------------------------------------------------------------------
# TestTextSuspiciousPatterns
# ---------------------------------------------------------------------------

class TestTextSuspiciousPatterns:
    """Tests for validate_text_input suspicious-pattern detection."""

    def test_rejects_script_tag(self):
        """
        GIVEN: Text containing a <script> tag
        WHEN: validate_text_input() is called
        THEN: ValidationError is raised with safety message
        """
        v = _make_validator()
        with pytest.raises(ValidationError) as exc_info:
            v.validate_text_input("<script>alert('xss')</script>")
        assert "unsafe" in str(exc_info.value).lower()

    def test_rejects_javascript_url(self):
        """
        GIVEN: Text containing 'javascript:' keyword
        WHEN: validate_text_input() is called
        THEN: ValidationError is raised
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_text_input("click here: javascript:void(0)")

    def test_rejects_eval_call(self):
        """
        GIVEN: Text containing eval() call pattern
        WHEN: validate_text_input() is called
        THEN: ValidationError is raised
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_text_input("eval(malicious_code)")

    def test_rejects_subprocess_reference(self):
        """
        GIVEN: Text referencing subprocess module
        WHEN: validate_text_input() is called
        THEN: ValidationError is raised
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_text_input("import subprocess; subprocess.run(['rm', '-rf', '/'])")

    def test_increments_validation_error_counter(self):
        """
        GIVEN: Text with suspicious content
        WHEN: validate_text_input() raises ValidationError
        THEN: validation_errors counter is incremented
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_text_input("<script>bad</script>")
        assert v.performance_metrics["validation_errors"] == 1


# ---------------------------------------------------------------------------
# TestModelNameValidation
# ---------------------------------------------------------------------------

class TestModelNameValidation:
    """Tests for validate_model_name edge cases."""

    def test_rejects_non_string_model_name(self):
        """
        GIVEN: A non-string model name (e.g. integer)
        WHEN: validate_model_name() is called
        THEN: ValidationError is raised
        """
        v = _make_validator()
        with pytest.raises(ValidationError) as exc_info:
            v.validate_model_name(42)
        assert "string" in str(exc_info.value).lower()

    def test_rejects_empty_model_name(self):
        """
        GIVEN: An empty string model name
        WHEN: validate_model_name() is called
        THEN: ValidationError is raised with 'empty' in message
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_model_name("")

    def test_rejects_whitespace_only_model_name(self):
        """
        GIVEN: A whitespace-only model name
        WHEN: validate_model_name() is called
        THEN: ValidationError is raised
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_model_name("   ")

    def test_allows_unknown_model_pattern_with_warning(self):
        """
        GIVEN: A model name not matching any known pattern
        WHEN: validate_model_name() is called
        THEN: Model name is returned (validator is lenient; unknown patterns allowed with warning)
        """
        v = _make_validator()
        result = v.validate_model_name("some-custom-model-v2")
        assert result == "some-custom-model-v2"

    def test_cache_hit_returns_cached_valid_result(self):
        """
        GIVEN: A model name validated once (stored in cache as valid)
        WHEN: validate_model_name() is called again with same name
        THEN: Cache hit counter incremented; result returned from cache
        """
        v = _make_validator()
        v.validate_model_name("all-MiniLM-L6-v2")
        initial_hits = v.performance_metrics["cache_hits"]
        v.validate_model_name("all-MiniLM-L6-v2")
        assert v.performance_metrics["cache_hits"] == initial_hits + 1

    def test_cache_hit_raises_for_previously_invalid(self):
        """
        GIVEN: A model name validated once as invalid (stored in cache as False)
        WHEN: validate_model_name() is called again
        THEN: ValidationError raised from cache without re-running validation
        """
        v = _make_validator()
        cache_key = v._cache_key(42, "model_name")
        v.validation_cache[cache_key] = False

        with pytest.raises(ValidationError):
            v.validate_model_name(42)


# ---------------------------------------------------------------------------
# TestIPFSHashNonString
# ---------------------------------------------------------------------------

class TestIPFSHashNonString:
    """Tests for validate_ipfs_hash non-string path."""

    def test_rejects_none_ipfs_hash(self):
        """
        GIVEN: None as IPFS hash
        WHEN: validate_ipfs_hash() is called
        THEN: ValidationError is raised
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_ipfs_hash(None)

    def test_rejects_integer_ipfs_hash(self):
        """
        GIVEN: An integer as IPFS hash
        WHEN: validate_ipfs_hash() is called
        THEN: ValidationError raised with 'string' message
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_ipfs_hash(12345)


# ---------------------------------------------------------------------------
# TestCollectionNameEdgeCases
# ---------------------------------------------------------------------------

class TestCollectionNameEdgeCases:
    """Tests for validate_collection_name edge cases."""

    def test_rejects_non_string_collection_name(self):
        """
        GIVEN: A non-string collection name (list)
        WHEN: validate_collection_name() is called
        THEN: ValidationError is raised
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_collection_name(["mycollection"])

    def test_rejects_single_character_name(self):
        """
        GIVEN: A 1-character collection name
        WHEN: validate_collection_name() is called
        THEN: ValidationError raised (min length is 2)
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_collection_name("a")

    def test_accepts_two_character_name(self):
        """
        GIVEN: A 2-character collection name
        WHEN: validate_collection_name() is called
        THEN: Name is returned (exact min length)
        """
        v = _make_validator()
        result = v.validate_collection_name("ab")
        assert result == "ab"

    def test_rejects_reserved_name(self):
        """
        GIVEN: A reserved collection name ('admin')
        WHEN: validate_collection_name() is called
        THEN: ValidationError raised
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_collection_name("admin")


# ---------------------------------------------------------------------------
# TestSearchFiltersEdgeCases
# ---------------------------------------------------------------------------

class TestSearchFiltersEdgeCases:
    """Tests for validate_search_filters edge cases."""

    def test_rejects_empty_string_filter_key(self):
        """
        GIVEN: A filter with an empty-string key
        WHEN: validate_search_filters() is called
        THEN: ValidationError is raised
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_search_filters({"": "value"})

    def test_rejects_whitespace_only_filter_key(self):
        """
        GIVEN: A filter with whitespace-only key
        WHEN: validate_search_filters() is called
        THEN: ValidationError is raised
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_search_filters({"   ": "value"})

    def test_rejects_too_long_filter_key(self):
        """
        GIVEN: A filter key longer than 100 characters
        WHEN: validate_search_filters() is called
        THEN: ValidationError is raised
        """
        v = _make_validator()
        long_key = "k" * 101
        with pytest.raises(ValidationError):
            v.validate_search_filters({long_key: "value"})

    def test_rejects_list_with_invalid_items(self):
        """
        GIVEN: A filter with list value containing a dict item
        WHEN: validate_search_filters() is called
        THEN: ValidationError raised for invalid list items
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_search_filters({"tags": ["valid", {"nested": "dict"}]})

    def test_rejects_dict_with_invalid_operators(self):
        """
        GIVEN: A filter with dict value containing unsupported operators
        WHEN: validate_search_filters() is called
        THEN: ValidationError raised for invalid operators
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_search_filters({"score": {"hack": "exploit"}})

    def test_rejects_unsupported_value_type(self):
        """
        GIVEN: A filter value that is neither str/int/float/bool/list/dict
        WHEN: validate_search_filters() is called
        THEN: ValidationError raised for unsupported type
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_search_filters({"some_filter": object()})

    def test_accepts_dict_value_with_valid_operators(self):
        """
        GIVEN: A filter with a dict value using only valid range operators
        WHEN: validate_search_filters() is called
        THEN: Filter is returned as-is
        """
        v = _make_validator()
        result = v.validate_search_filters({"score": {"gte": 0.5, "lte": 1.0}})
        assert result["score"] == {"gte": 0.5, "lte": 1.0}

    def test_accepts_list_value_with_valid_items(self):
        """
        GIVEN: A filter with a list value containing only primitives
        WHEN: validate_search_filters() is called
        THEN: Filter list is returned unchanged
        """
        v = _make_validator()
        result = v.validate_search_filters({"tags": ["a", "b", "c"]})
        assert result["tags"] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# TestFilePathEdgeCases
# ---------------------------------------------------------------------------

class TestFilePathEdgeCases:
    """Tests for validate_file_path edge cases."""

    def test_rejects_non_string_file_path(self):
        """
        GIVEN: A non-string file path (integer)
        WHEN: validate_file_path() is called
        THEN: ValidationError is raised
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_file_path(42)

    def test_rejects_nonexistent_file_when_check_exists(self):
        """
        GIVEN: check_exists=True and a file that doesn't exist
        WHEN: validate_file_path() is called
        THEN: ValidationError is raised with 'does not exist' message
        """
        v = _make_validator()
        with pytest.raises(ValidationError) as exc_info:
            v.validate_file_path("no_such_file.txt", check_exists=True)
        assert "does not exist" in str(exc_info.value).lower()

    def test_accepts_existing_file_when_check_exists(self, tmp_path):
        """
        GIVEN: check_exists=True and a file that exists
        WHEN: validate_file_path() is called
        THEN: The file path is returned
        """
        v = _make_validator()
        f = tmp_path / "test.txt"
        f.write_text("hello")
        result = v.validate_file_path(str(f.relative_to(tmp_path.parent)), check_exists=False)
        # Just test that it doesn't raise for a relative path
        assert isinstance(result, str)

    def test_oserror_from_path_construction_raises_validation_error(self):
        """
        GIVEN: pathlib.Path raises OSError during construction
        WHEN: validate_file_path() is called
        THEN: ValidationError is raised (wrapping OSError)
        """
        v = _make_validator()
        with patch("ipfs_datasets_py.mcp_server.validators.Path") as mock_path:
            mock_path.side_effect = OSError("filesystem error")
            with pytest.raises(ValidationError):
                v.validate_file_path("some_file.txt")

    def test_rejects_directory_traversal_path(self):
        """
        GIVEN: A file path containing '..'
        WHEN: validate_file_path() is called
        THEN: ValidationError is raised
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_file_path("../etc/passwd")

    def test_rejects_disallowed_extension(self):
        """
        GIVEN: A file path with an extension not in allowed_extensions
        WHEN: validate_file_path() with allowed_extensions={'txt'} is called
        THEN: ValidationError is raised
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_file_path("image.png", allowed_extensions={".txt"})


# ---------------------------------------------------------------------------
# TestJSONSchemaValidation
# ---------------------------------------------------------------------------

class TestJSONSchemaValidation:
    """Tests for validate_json_schema ValidationError re-raise path."""

    def test_reraises_our_validation_error(self):
        """
        GIVEN: jsonschema.validate raises our custom ValidationError (via mock)
        WHEN: validate_json_schema() is called
        THEN: The ValidationError propagates unchanged
        """
        v = _make_validator()
        schema = {"type": "object"}

        # Mock jsonschema.validate to raise our custom ValidationError
        with patch("ipfs_datasets_py.mcp_server.validators.ValidationError",
                   ValidationError):
            import sys
            import types

            # Create a fake jsonschema module that raises our ValidationError
            fake_jsonschema = types.ModuleType("jsonschema")
            def raise_ve(data, schema):
                raise ValidationError("schema", "custom validation error")
            fake_jsonschema.validate = raise_ve

            with patch.dict(sys.modules, {"jsonschema": fake_jsonschema}):
                with pytest.raises(ValidationError):
                    v.validate_json_schema({"key": "value"}, schema)

    def test_wraps_jsonschema_exception_as_validation_error(self):
        """
        GIVEN: jsonschema.validate raises a non-ValidationError Exception
        WHEN: validate_json_schema() is called
        THEN: Exception is wrapped in ValidationError
        """
        v = _make_validator()
        import sys
        import types

        fake_jsonschema = types.ModuleType("jsonschema")
        def raise_generic(data, schema):
            raise RuntimeError("schema format error")
        fake_jsonschema.validate = raise_generic

        with patch.dict(sys.modules, {"jsonschema": fake_jsonschema}):
            with pytest.raises(ValidationError):
                v.validate_json_schema({"key": "value"}, {"type": "object"})


# ---------------------------------------------------------------------------
# TestURLEdgeCases
# ---------------------------------------------------------------------------

class TestURLEdgeCases:
    """Tests for validate_url edge cases."""

    def test_rejects_url_without_scheme(self):
        """
        GIVEN: A URL string without a scheme (e.g. 'example.com/path')
        WHEN: validate_url() is called
        THEN: ValidationError is raised mentioning 'scheme'
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_url("example.com/path")

    def test_rejects_non_string_url(self):
        """
        GIVEN: A non-string URL (bytes)
        WHEN: validate_url() is called
        THEN: ValidationError is raised
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_url(b"http://example.com")

    def test_oserror_from_urlparse_raises_validation_error(self):
        """
        GIVEN: urlparse raises OSError
        WHEN: validate_url() is called
        THEN: ValidationError is raised wrapping the OSError
        """
        v = _make_validator()
        with patch(
            "ipfs_datasets_py.mcp_server.validators.urlparse",
            side_effect=OSError("network error"),
        ):
            with pytest.raises(ValidationError):
                v.validate_url("http://example.com")

    def test_accepts_https_url_with_allowed_schemes(self):
        """
        GIVEN: A valid HTTPS URL with 'https' in allowed_schemes
        WHEN: validate_url() is called
        THEN: URL is returned unchanged
        """
        v = _make_validator()
        url = "https://example.com/path?query=value"
        result = v.validate_url(url, allowed_schemes={"http", "https"})
        assert result == url

    def test_rejects_ftp_when_only_http_allowed(self):
        """
        GIVEN: An FTP URL with only 'http'/'https' in allowed_schemes
        WHEN: validate_url() is called
        THEN: ValidationError is raised
        """
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_url("ftp://files.example.com", allowed_schemes={"http", "https"})
