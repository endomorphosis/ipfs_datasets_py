"""
Tests for lizardpersons_function_tools/prototyping_tools/:
- json_to_pydantic  (generates Pydantic model files from JSON)

Note: python_file_to_json.py uses ``from mcp_server.utils import python_builtins``
which is only importable when the package is installed as ``mcp_server`` (not the
fully-qualified ``ipfs_datasets_py.mcp_server`` path used in tests).  Its tests are
therefore omitted here.
"""
import os

import pytest

from ipfs_datasets_py.mcp_server.tools.lizardpersons_function_tools.prototyping_tools.json_to_pydantic import (
    json_to_pydantic,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cleanup(path: str) -> None:
    if os.path.exists(path):
        os.unlink(path)


# ---------------------------------------------------------------------------
# json_to_pydantic
# ---------------------------------------------------------------------------

class TestJsonToPydantic:
    """Tests for json_to_pydantic — generates Pydantic model files from JSON."""

    def test_raises_file_not_found_for_missing_output_dir(self):
        """GIVEN a non-existent output_dir THEN FileNotFoundError is raised."""
        with pytest.raises(FileNotFoundError):
            json_to_pydantic({"name": "Alice"}, "/nonexistent_dir_session36/")

    def test_raises_type_error_for_list_input(self):
        """GIVEN a list as json_data THEN TypeError is raised."""
        with pytest.raises(TypeError):
            json_to_pydantic([1, 2, 3], "/tmp")

    def test_raises_value_error_for_invalid_json_string(self):
        """GIVEN an unparseable string THEN ValueError is raised."""
        with pytest.raises(ValueError):
            json_to_pydantic("not valid json {{{{{", "/tmp")

    def test_success_with_dict_returns_str(self):
        """GIVEN a valid dict and /tmp THEN returns a success string."""
        out = "/tmp/TestPersonModel36.py"
        try:
            result = json_to_pydantic(
                {"name": "Alice", "age": 30},
                "/tmp",
                model_name="TestPersonModel36",
            )
            assert isinstance(result, str)
        finally:
            _cleanup(out)

    def test_success_with_json_string(self):
        """GIVEN a valid JSON string THEN returns a success string."""
        out = "/tmp/TestCountModel36.py"
        try:
            result = json_to_pydantic(
                '{"title": "test", "count": 5}',
                "/tmp",
                model_name="TestCountModel36",
            )
            assert isinstance(result, str)
        finally:
            _cleanup(out)

    def test_output_path_mentioned_in_result(self):
        """GIVEN a successful call THEN result string mentions the model or path."""
        out = "/tmp/TestKeyModel36.py"
        try:
            result = json_to_pydantic(
                {"key": "val"}, "/tmp", model_name="TestKeyModel36"
            )
            assert "TestKeyModel36" in result or "/tmp" in result
        finally:
            _cleanup(out)

    def test_output_file_is_created(self):
        """GIVEN a successful call THEN the .py model file exists on disk."""
        out = "/tmp/TestFileCreated36.py"
        _cleanup(out)
        try:
            json_to_pydantic({"x": 1}, "/tmp", model_name="TestFileCreated36")
            assert os.path.exists(out)
        finally:
            _cleanup(out)
