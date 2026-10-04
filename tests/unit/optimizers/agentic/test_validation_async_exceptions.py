"""Typed-exception regression tests for async agentic validators."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from ipfs_datasets_py.optimizers.agentic.validation import (
    ValidationLevel,
    _AsyncOptimizationValidator,
    _AsyncPerformanceValidator,
    _AsyncSyntaxValidator,
    _AsyncTestValidator,
    _AsyncTypeValidator,
)


@pytest.mark.anyio
async def test_async_syntax_validator_handles_typed_parse_error(monkeypatch):
    validator = _AsyncSyntaxValidator()

    def _raise_type_error(*_args, **_kwargs):
        raise TypeError("bad parse input")

    monkeypatch.setattr("ast.parse", _raise_type_error)
    result = await validator.validate("x = 1", [], {})
    assert result["passed"] is False
    assert any("Parse error:" in err for err in result["errors"])


@pytest.mark.anyio
async def test_async_syntax_validator_propagates_base_exception(monkeypatch):
    validator = _AsyncSyntaxValidator()

    def _raise_interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt("stop")

    monkeypatch.setattr("ast.parse", _raise_interrupt)
    with pytest.raises(KeyboardInterrupt):
        await validator.validate("x = 1", [], {})


@pytest.mark.anyio
async def test_async_type_validator_handles_typed_runtime_error(monkeypatch):
    validator = _AsyncTypeValidator(strict=False)

    def _subprocess_run(*args, **kwargs):
        return Mock(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("subprocess.run", _subprocess_run)

    class _FailingTempFile:
        def __init__(self, *_args, **_kwargs):
            raise OSError("tempfile unavailable")

    monkeypatch.setattr("tempfile.NamedTemporaryFile", _FailingTempFile)
    result = await validator.validate("x = 1", [Path("x.py")], {})
    assert any("Type checking error:" in w for w in result["warnings"])


@pytest.mark.anyio
async def test_async_type_validator_propagates_base_exception(monkeypatch):
    validator = _AsyncTypeValidator(strict=False)

    def _subprocess_run(*args, **kwargs):
        return Mock(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("subprocess.run", _subprocess_run)

    class _InterruptingTempFile:
        def __init__(self, *_args, **_kwargs):
            raise KeyboardInterrupt("stop")

    monkeypatch.setattr("tempfile.NamedTemporaryFile", _InterruptingTempFile)
    with pytest.raises(KeyboardInterrupt):
        await validator.validate("x = 1", [Path("x.py")], {})


@pytest.mark.anyio
async def test_async_test_validator_handles_typed_runtime_error(monkeypatch, tmp_path):
    validator = _AsyncTestValidator()

    target_file = tmp_path / "module.py"
    target_file.write_text("x = 1")
    test_file = tmp_path / "test_module.py"
    test_file.write_text("def test_ok():\n    assert True\n")

    def _subprocess_run(*args, **kwargs):
        return Mock(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("subprocess.run", _subprocess_run)

    async def _raise_value_error(*_args, **_kwargs):
        raise ValueError("runner failed")

    monkeypatch.setattr("anyio.to_thread.run_sync", _raise_value_error)
    result = await validator.validate("x = 1", [target_file], {})
    assert any("Test execution error:" in w for w in result["warnings"])


@pytest.mark.anyio
async def test_async_test_validator_propagates_base_exception(monkeypatch, tmp_path):
    validator = _AsyncTestValidator()

    target_file = tmp_path / "module.py"
    target_file.write_text("x = 1")
    test_file = tmp_path / "test_module.py"
    test_file.write_text("def test_ok():\n    assert True\n")

    def _subprocess_run(*args, **kwargs):
        return Mock(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("subprocess.run", _subprocess_run)

    async def _raise_interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt("stop")

    monkeypatch.setattr("anyio.to_thread.run_sync", _raise_interrupt)
    with pytest.raises(KeyboardInterrupt):
        await validator.validate("x = 1", [target_file], {})


@pytest.mark.anyio
async def test_async_performance_validator_handles_typed_runtime_error(monkeypatch):
    validator = _AsyncPerformanceValidator()

    class _FailingTempFile:
        def __init__(self, *_args, **_kwargs):
            raise OSError("tempfile unavailable")

    monkeypatch.setattr("tempfile.NamedTemporaryFile", _FailingTempFile)
    metrics = await validator._benchmark_code("x = 1")
    assert metrics["execution_time"] == 0.0
    assert metrics["compile_time"] == 0.0


@pytest.mark.anyio
async def test_async_performance_validator_propagates_base_exception(monkeypatch):
    validator = _AsyncPerformanceValidator()

    class _InterruptingTempFile:
        def __init__(self, *_args, **_kwargs):
            raise KeyboardInterrupt("stop")

    monkeypatch.setattr("tempfile.NamedTemporaryFile", _InterruptingTempFile)
    with pytest.raises(KeyboardInterrupt):
        await validator._benchmark_code("x = 1")


@pytest.mark.anyio
async def test_async_optimization_validator_enhanced_path_typed_fallback(monkeypatch):
    validator = _AsyncOptimizationValidator(
        level=ValidationLevel.BASIC,
        parallel=True,
        use_enhanced_parallel=True,
    )

    class _GoodValidator:
        async def validate(self, *_args, **_kwargs):
            return {"passed": True, "errors": [], "warnings": []}

    validator.validators = {"syntax": _GoodValidator()}  # type: ignore[assignment]

    class _FailingParallel:
        async def run_async(self, *_args, **_kwargs):
            raise ValueError("parallel backend failed")

    validator.parallel_validator = _FailingParallel()  # type: ignore[assignment]
    results = await validator._validate_parallel("x = 1", [], {})
    assert results["syntax"]["passed"] is True


@pytest.mark.anyio
async def test_async_optimization_validator_enhanced_path_propagates_base_exception(
    monkeypatch,
):
    validator = _AsyncOptimizationValidator(
        level=ValidationLevel.BASIC,
        parallel=True,
        use_enhanced_parallel=True,
    )

    class _GoodValidator:
        async def validate(self, *_args, **_kwargs):
            return {"passed": True, "errors": [], "warnings": []}

    validator.validators = {"syntax": _GoodValidator()}  # type: ignore[assignment]

    class _InterruptingParallel:
        async def run_async(self, *_args, **_kwargs):
            raise KeyboardInterrupt("stop")

    validator.parallel_validator = _InterruptingParallel()  # type: ignore[assignment]
    with pytest.raises(KeyboardInterrupt):
        await validator._validate_parallel("x = 1", [], {})


@pytest.mark.anyio
async def test_async_optimization_validator_sequential_typed_fallback():
    validator = _AsyncOptimizationValidator(
        level=ValidationLevel.BASIC,
        parallel=False,
        use_enhanced_parallel=False,
    )

    class _FailingValidator:
        async def validate(self, *_args, **_kwargs):
            raise ValueError("validator failed")

    validator.validators = {"syntax": _FailingValidator()}  # type: ignore[assignment]
    results = await validator._validate_sequential("x = 1", [], {})
    assert results["syntax"]["passed"] is False
    assert "validator failed" in results["syntax"]["errors"][0]


@pytest.mark.anyio
async def test_async_optimization_validator_sequential_propagates_base_exception():
    validator = _AsyncOptimizationValidator(
        level=ValidationLevel.BASIC,
        parallel=False,
        use_enhanced_parallel=False,
    )

    class _InterruptingValidator:
        async def validate(self, *_args, **_kwargs):
            raise KeyboardInterrupt("stop")

    validator.validators = {"syntax": _InterruptingValidator()}  # type: ignore[assignment]
    with pytest.raises(KeyboardInterrupt):
        await validator._validate_sequential("x = 1", [], {})
