"""
Tests for lizardpersons_function_tools/meta_tools/:
- list_tools_in_functions_dir — lists Python tool files in ../functions/
- list_tools_in_cli_dir — lists argparse-based CLI tools in ../cli/
"""
import pytest

from ipfs_datasets_py.mcp_server.tools.lizardpersons_function_tools.meta_tools.list_tools_in_functions_dir import (
    list_tools_in_functions_dir,
)
from ipfs_datasets_py.mcp_server.tools.lizardpersons_function_tools.meta_tools.list_tools_in_cli_dir import (
    list_tools_in_cli_dir,
)


class TestListToolsInFunctionsDir:
    """Tests for list_tools_in_functions_dir."""

    def test_returns_list(self):
        """GIVEN default args THEN returns a list."""
        result = list_tools_in_functions_dir()
        assert isinstance(result, list)

    def test_get_docstring_false_returns_list_of_dicts(self):
        """GIVEN get_docstring=False THEN each item is a dict with at least 'name' key."""
        result = list_tools_in_functions_dir(get_docstring=False)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, dict)
            assert "name" in item

    def test_raises_value_error_for_non_bool(self):
        """GIVEN get_docstring='yes' (non-bool) THEN raises ValueError."""
        with pytest.raises(ValueError):
            list_tools_in_functions_dir(get_docstring="yes")

    def test_get_docstring_true_returns_list(self):
        """GIVEN get_docstring=True THEN returns a list (items may have 'docstring' key)."""
        result = list_tools_in_functions_dir(get_docstring=True)
        assert isinstance(result, list)

    def test_returns_list_of_dicts_when_tools_present(self):
        """GIVEN tools in the functions dir THEN result items are dicts."""
        result = list_tools_in_functions_dir()
        for item in result:
            assert isinstance(item, dict)


class TestListToolsInCliDir:
    """Tests for list_tools_in_cli_dir."""

    def test_returns_list(self):
        """GIVEN default args THEN returns a list (may be empty — no argparse subdirs)."""
        result = list_tools_in_cli_dir()
        assert isinstance(result, list)

    def test_returns_list_of_dicts_when_tools_present(self):
        """GIVEN any CLI tools in cli dir THEN each item is a dict."""
        result = list_tools_in_cli_dir()
        for item in result:
            assert isinstance(item, dict)

    def test_get_help_menu_false_accepted(self):
        """GIVEN get_help_menu=False THEN returns a list without help menus."""
        result = list_tools_in_cli_dir(get_help_menu=False)
        assert isinstance(result, list)
