"""Regression tests for DynamicToolRunner callable routing and arg validation."""

from __future__ import annotations

import asyncio
import sys
import types

from ipfs_datasets_cli import DynamicToolRunner


def _register_fake_module(name: str, module: types.ModuleType) -> None:
    sys.modules[name] = module


def _make_runner(module_name: str) -> DynamicToolRunner:
    runner = DynamicToolRunner()
    runner.discovered_tools = {"cat": {"tool": module_name}}
    return runner


def test_run_tool_ambiguous_callable_selection_returns_error() -> None:
    module_name = "tests.fake_dynamic_tool_runner_ambiguous"
    fake = types.ModuleType(module_name)

    def alpha(x):
        return {"status": "success", "result": x}

    def beta(x):
        return {"status": "success", "result": x}

    fake.alpha = alpha
    fake.beta = beta
    _register_fake_module(module_name, fake)

    runner = _make_runner(module_name)
    result = asyncio.run(runner.run_tool("cat", "tool", x=1))

    assert result.get("status") == "error"
    assert "Ambiguous callable selection" in str(result.get("error"))


def test_run_tool_rejects_unexpected_arguments() -> None:
    module_name = "tests.fake_dynamic_tool_runner_unexpected"
    fake = types.ModuleType(module_name)

    def tool(required):
        return {"status": "success", "required": required}

    fake.tool = tool
    _register_fake_module(module_name, fake)

    runner = _make_runner(module_name)
    result = asyncio.run(runner.run_tool("cat", "tool", required=1, extra=2))

    assert result.get("status") == "error"
    assert "Unexpected arguments" in str(result.get("error"))


def test_run_tool_rejects_missing_required_arguments() -> None:
    module_name = "tests.fake_dynamic_tool_runner_missing"
    fake = types.ModuleType(module_name)

    def tool(required, optional=3):
        return {"status": "success", "required": required, "optional": optional}

    fake.tool = tool
    _register_fake_module(module_name, fake)

    runner = _make_runner(module_name)
    result = asyncio.run(runner.run_tool("cat", "tool"))

    assert result.get("status") == "error"
    assert "Missing required arguments" in str(result.get("error"))


def test_run_tool_prefers_exact_name_over_suffix() -> None:
    module_name = "tests.fake_dynamic_tool_runner_exact"
    fake = types.ModuleType(module_name)

    def tool():
        return {"status": "success", "picked": "exact"}

    def tool_tool():
        return {"status": "success", "picked": "suffix"}

    fake.tool = tool
    fake.tool_tool = tool_tool
    _register_fake_module(module_name, fake)

    runner = _make_runner(module_name)
    result = asyncio.run(runner.run_tool("cat", "tool"))

    assert result.get("status") == "success"
    assert result.get("picked") == "exact"
