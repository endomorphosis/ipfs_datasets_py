"""
Phase B2 — Unit tests for mcp_helpers.py

3 functions: mcp_text_response, mcp_error_response, parse_json_object
All sync, pure-Python.
"""
import json
import pytest


# ---------------------------------------------------------------------------
# TestMcpTextResponse
# ---------------------------------------------------------------------------
class TestMcpTextResponse:
    def test_returns_content_list(self):
        from ipfs_datasets_py.mcp_server.tools.mcp_helpers import mcp_text_response
        result = mcp_text_response({"status": "ok"})
        assert isinstance(result, dict)
        assert "content" in result
        assert isinstance(result["content"], list)

    def test_content_has_type_text(self):
        from ipfs_datasets_py.mcp_server.tools.mcp_helpers import mcp_text_response
        result = mcp_text_response({"key": "value"})
        item = result["content"][0]
        assert item["type"] == "text"

    def test_text_is_json_serialized_payload(self):
        from ipfs_datasets_py.mcp_server.tools.mcp_helpers import mcp_text_response
        payload = {"a": 1, "b": [1, 2, 3]}
        result = mcp_text_response(payload)
        decoded = json.loads(result["content"][0]["text"])
        assert decoded == payload

    def test_nested_payload(self):
        from ipfs_datasets_py.mcp_server.tools.mcp_helpers import mcp_text_response
        payload = {"nested": {"deep": True}}
        result = mcp_text_response(payload)
        decoded = json.loads(result["content"][0]["text"])
        assert decoded["nested"]["deep"] is True


# ---------------------------------------------------------------------------
# TestMcpErrorResponse
# ---------------------------------------------------------------------------
class TestMcpErrorResponse:
    def test_returns_mcp_envelope(self):
        from ipfs_datasets_py.mcp_server.tools.mcp_helpers import mcp_error_response
        result = mcp_error_response("something went wrong")
        assert "content" in result

    def test_status_is_error(self):
        from ipfs_datasets_py.mcp_server.tools.mcp_helpers import mcp_error_response
        result = mcp_error_response("oops")
        data = json.loads(result["content"][0]["text"])
        assert data["status"] == "error"

    def test_error_message_present(self):
        from ipfs_datasets_py.mcp_server.tools.mcp_helpers import mcp_error_response
        result = mcp_error_response("the thing broke")
        data = json.loads(result["content"][0]["text"])
        assert data["error"] == "the thing broke"

    def test_custom_error_type(self):
        from ipfs_datasets_py.mcp_server.tools.mcp_helpers import mcp_error_response
        result = mcp_error_response("bad input", error_type="validation")
        data = json.loads(result["content"][0]["text"])
        assert data["error_type"] == "validation"

    def test_extra_kwargs_included(self):
        from ipfs_datasets_py.mcp_server.tools.mcp_helpers import mcp_error_response
        result = mcp_error_response("err", code=42)
        data = json.loads(result["content"][0]["text"])
        assert data["code"] == 42


# ---------------------------------------------------------------------------
# TestParseJsonObject
# ---------------------------------------------------------------------------
class TestParseJsonObject:
    def test_valid_json_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcp_helpers import parse_json_object
        data, err = parse_json_object('{"x": 1, "y": 2}')
        assert err is None
        assert data == {"x": 1, "y": 2}

    def test_empty_string_returns_error(self):
        from ipfs_datasets_py.mcp_server.tools.mcp_helpers import parse_json_object
        data, err = parse_json_object("")
        assert data is None
        assert err is not None
        payload = json.loads(err["content"][0]["text"])
        assert payload["error_type"] == "validation"

    def test_whitespace_only_returns_error(self):
        from ipfs_datasets_py.mcp_server.tools.mcp_helpers import parse_json_object
        data, err = parse_json_object("   ")
        assert data is None
        assert err is not None

    def test_non_string_returns_error(self):
        from ipfs_datasets_py.mcp_server.tools.mcp_helpers import parse_json_object
        data, err = parse_json_object({"already": "dict"})
        assert data is None
        assert err is not None

    def test_invalid_json_returns_error(self):
        from ipfs_datasets_py.mcp_server.tools.mcp_helpers import parse_json_object
        data, err = parse_json_object("{not valid json}")
        assert data is None
        assert err is not None

    def test_json_array_returns_error(self):
        from ipfs_datasets_py.mcp_server.tools.mcp_helpers import parse_json_object
        data, err = parse_json_object("[1, 2, 3]")
        assert data is None
        assert err is not None
        payload = json.loads(err["content"][0]["text"])
        # Non-dict JSON object gives validation error
        assert "error_type" in payload

    def test_nested_object_parsed(self):
        from ipfs_datasets_py.mcp_server.tools.mcp_helpers import parse_json_object
        data, err = parse_json_object('{"outer": {"inner": 99}}')
        assert err is None
        assert data["outer"]["inner"] == 99
