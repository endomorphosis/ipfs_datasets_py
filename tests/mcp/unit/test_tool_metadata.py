"""Tests for the tool_metadata module (ToolMetadata, ToolMetadataRegistry, decorator).

Following GIVEN-WHEN-THEN format.
"""
import pytest
from ipfs_datasets_py.mcp_server.tool_metadata import (
    ToolMetadata,
    ToolMetadataRegistry,
    tool_metadata,
    get_registry,
    get_tool_metadata,
    RUNTIME_FASTAPI,
    RUNTIME_TRIO,
    RUNTIME_AUTO,
)


# ---------------------------------------------------------------------------
# ToolMetadata dataclass
# ---------------------------------------------------------------------------

class TestToolMetadataDefaults:
    """ToolMetadata default values and basic construction."""

    def test_minimum_construction(self):
        """GIVEN only a name WHEN constructing ToolMetadata THEN defaults are applied."""
        md = ToolMetadata(name="my_tool")
        assert md.name == "my_tool"
        assert md.runtime == RUNTIME_AUTO
        assert md.requires_p2p is False
        assert md.category == "general"
        assert md.priority == 5
        assert md.timeout_seconds == 30.0
        assert md.retry_policy == "none"
        assert md.memory_intensive is False
        assert md.cpu_intensive is False
        assert md.io_intensive is False

    def test_to_dict_excludes_private_fields(self):
        """GIVEN a ToolMetadata WHEN to_dict() is called THEN _func is excluded."""
        md = ToolMetadata(name="tool_a")
        d = md.to_dict()
        assert "name" in d
        assert "_func" not in d

    def test_to_dict_includes_all_public_fields(self):
        """GIVEN a ToolMetadata WHEN to_dict() is called THEN all public fields are present."""
        md = ToolMetadata(name="tool_b", runtime=RUNTIME_TRIO, requires_p2p=True, priority=8)
        d = md.to_dict()
        assert d["name"] == "tool_b"
        assert d["runtime"] == RUNTIME_TRIO
        assert d["requires_p2p"] is True
        assert d["priority"] == 8


class TestToolMetadataValidation:
    """ToolMetadata __post_init__ validation."""

    def test_invalid_runtime_raises(self):
        """GIVEN an unknown runtime WHEN constructing ToolMetadata THEN ValueError is raised."""
        with pytest.raises(ValueError, match="Invalid runtime"):
            ToolMetadata(name="t", runtime="unknown_runtime")

    def test_priority_below_zero_raises(self):
        """GIVEN priority=-1 WHEN constructing THEN ValueError is raised."""
        with pytest.raises(ValueError, match="Priority"):
            ToolMetadata(name="t", priority=-1)

    def test_priority_above_ten_raises(self):
        """GIVEN priority=11 WHEN constructing THEN ValueError is raised."""
        with pytest.raises(ValueError, match="Priority"):
            ToolMetadata(name="t", priority=11)

    def test_invalid_retry_policy_raises(self):
        """GIVEN an unknown retry_policy WHEN constructing THEN ValueError is raised."""
        with pytest.raises(ValueError, match="Invalid retry_policy"):
            ToolMetadata(name="t", retry_policy="unknown")

    def test_valid_retry_policies_accepted(self):
        """GIVEN valid retry policies WHEN constructing THEN no error is raised."""
        for policy in ("none", "exponential", "linear"):
            md = ToolMetadata(name="t", retry_policy=policy)
            assert md.retry_policy == policy


class TestToolMetadataValidateComplete:
    """ToolMetadata.validate_complete() logic."""

    def test_complete_metadata_returns_no_warnings(self):
        """GIVEN fully-specified metadata WHEN validate_complete() THEN empty list."""
        md = ToolMetadata(
            name="full_tool",
            mcp_description="Does something",
            mcp_schema={"type": "object"},
        )
        assert md.validate_complete() == []

    def test_missing_description_produces_warning(self):
        """GIVEN no mcp_description WHEN validate_complete() THEN warning included."""
        md = ToolMetadata(name="t")
        warnings = md.validate_complete()
        assert any("description" in w.lower() for w in warnings)

    def test_p2p_tool_on_fastapi_runtime_produces_warning(self):
        """GIVEN requires_p2p=True and fastapi runtime WHEN validate_complete() THEN warning."""
        md = ToolMetadata(name="t", requires_p2p=True, runtime=RUNTIME_FASTAPI)
        warnings = md.validate_complete()
        assert any("trio" in w.lower() or "p2p" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# ToolMetadataRegistry
# ---------------------------------------------------------------------------

class TestToolMetadataRegistry:
    """ToolMetadataRegistry CRUD and queries."""

    def setup_method(self):
        self.registry = ToolMetadataRegistry()

    def test_register_and_get(self):
        """GIVEN registered metadata WHEN get() THEN returns it."""
        md = ToolMetadata(name="reg_tool", runtime=RUNTIME_FASTAPI)
        self.registry.register(md)
        result = self.registry.get("reg_tool")
        assert result is md

    def test_get_unknown_returns_none(self):
        """GIVEN empty registry WHEN get('unknown') THEN None."""
        assert self.registry.get("no_such_tool") is None

    def test_list_by_runtime_fastapi(self):
        """GIVEN two fastapi and one trio tool WHEN list_by_runtime('fastapi') THEN two results."""
        self.registry.register(ToolMetadata(name="fa_1", runtime=RUNTIME_FASTAPI))
        self.registry.register(ToolMetadata(name="fa_2", runtime=RUNTIME_FASTAPI))
        self.registry.register(ToolMetadata(name="tr_1", runtime=RUNTIME_TRIO))
        fastapi_tools = self.registry.list_by_runtime(RUNTIME_FASTAPI)
        assert len(fastapi_tools) == 2
        assert all(t.runtime == RUNTIME_FASTAPI for t in fastapi_tools)

    def test_list_by_category(self):
        """GIVEN tools in different categories WHEN list_by_category THEN correct subset."""
        self.registry.register(ToolMetadata(name="ds1", category="dataset"))
        self.registry.register(ToolMetadata(name="ds2", category="dataset"))
        self.registry.register(ToolMetadata(name="vec1", category="vector"))
        dataset_tools = self.registry.list_by_category("dataset")
        assert len(dataset_tools) == 2

    def test_list_all_returns_all(self):
        """GIVEN 3 registered tools WHEN list_all() THEN 3 items."""
        for i in range(3):
            self.registry.register(ToolMetadata(name=f"tool_{i}"))
        assert len(self.registry.list_all()) == 3

    def test_get_statistics_counts(self):
        """GIVEN mixed tools WHEN get_statistics() THEN correct counts."""
        self.registry.register(ToolMetadata(name="t1", runtime=RUNTIME_TRIO, requires_p2p=True))
        self.registry.register(ToolMetadata(name="t2", runtime=RUNTIME_FASTAPI))
        stats = self.registry.get_statistics()
        assert stats["total_tools"] == 2
        assert stats["p2p_tools"] == 1
        assert stats["by_runtime"][RUNTIME_TRIO] == 1
        assert stats["by_runtime"][RUNTIME_FASTAPI] == 1

    def test_clear_empties_registry(self):
        """GIVEN registered tools WHEN clear() THEN registry is empty."""
        self.registry.register(ToolMetadata(name="temp"))
        self.registry.clear()
        assert self.registry.list_all() == []
        assert self.registry.get_statistics()["total_tools"] == 0

    def test_re_registering_different_runtime_logs_warning(self, caplog):
        """GIVEN registered tool WHEN re-registered with different runtime THEN warning logged."""
        import logging
        self.registry.register(ToolMetadata(name="dup", runtime=RUNTIME_FASTAPI))
        with caplog.at_level(logging.WARNING):
            self.registry.register(ToolMetadata(name="dup", runtime=RUNTIME_TRIO))
        assert any("dup" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# tool_metadata decorator
# ---------------------------------------------------------------------------

class TestToolMetadataDecorator:
    """The @tool_metadata decorator registers metadata and attaches attributes."""

    def setup_method(self):
        # Reset the global registry before each test to avoid pollution.
        get_registry().clear()

    def test_decorator_attaches_mcp_metadata(self):
        """GIVEN decorated function WHEN accessed THEN _mcp_metadata is a ToolMetadata."""
        @tool_metadata(runtime=RUNTIME_TRIO, category="test_cat", priority=7)
        def my_func():
            """My function."""
            pass

        assert hasattr(my_func, "_mcp_metadata")
        assert isinstance(my_func._mcp_metadata, ToolMetadata)
        assert my_func._mcp_metadata.runtime == RUNTIME_TRIO
        assert my_func._mcp_metadata.category == "test_cat"
        assert my_func._mcp_metadata.priority == 7

    def test_decorator_attaches_runtime_shortcut(self):
        """GIVEN decorated function WHEN accessed THEN _mcp_runtime matches runtime arg."""
        @tool_metadata(runtime=RUNTIME_FASTAPI)
        def another_func():
            """A function."""
            pass

        assert another_func._mcp_runtime == RUNTIME_FASTAPI

    def test_decorator_registers_in_global_registry(self):
        """GIVEN decorated function WHEN get_registry().get() THEN metadata found."""
        @tool_metadata(runtime=RUNTIME_AUTO)
        def registered_func():
            """Registered."""
            pass

        meta = get_registry().get("registered_func")
        assert meta is not None
        assert meta.name == "registered_func"

    def test_decorator_uses_docstring_as_description(self):
        """GIVEN function with docstring and no mcp_description WHEN decorated THEN docstring used."""
        @tool_metadata()
        def doc_func():
            """This is the docstring."""
            pass

        assert "docstring" in doc_func._mcp_metadata.mcp_description

    def test_decorator_explicit_description_overrides_docstring(self):
        """GIVEN mcp_description provided WHEN decorated THEN explicit description used."""
        @tool_metadata(mcp_description="Explicit description")
        def explicit_func():
            """Ignored docstring."""
            pass

        assert explicit_func._mcp_metadata.mcp_description == "Explicit description"

    def test_decorator_preserves_function_callable(self):
        """GIVEN decorated function WHEN called THEN original behaviour preserved."""
        @tool_metadata()
        def add(a, b):
            """Add two numbers."""
            return a + b

        assert add(2, 3) == 5


# ---------------------------------------------------------------------------
# get_tool_metadata helper
# ---------------------------------------------------------------------------

class TestGetToolMetadata:
    """get_tool_metadata() finds metadata via attribute or registry."""

    def setup_method(self):
        get_registry().clear()

    def test_returns_metadata_from_attribute(self):
        """GIVEN function with _mcp_metadata WHEN get_tool_metadata() THEN returns it."""
        @tool_metadata()
        def fn_with_attr():
            """Function."""
            pass

        result = get_tool_metadata(fn_with_attr)
        assert result is fn_with_attr._mcp_metadata

    def test_returns_none_for_undecorated_function(self):
        """GIVEN plain function with no registry entry WHEN get_tool_metadata() THEN None."""
        def plain():
            pass

        assert get_tool_metadata(plain) is None
