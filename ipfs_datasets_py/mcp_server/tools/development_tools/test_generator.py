"""
Test Generator MCP Tool — thin wrapper around the canonical engine.

Business logic lives in:
    ``ipfs_datasets_py.processors.development.test_generator_engine``

This file only provides the MCP-facing ``TestGeneratorTool`` class and the
``test_generator()`` convenience function that the MCP server registers.
"""

from __future__ import annotations

import anyio
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Union

from .base_tool import (
    BaseDevelopmentTool,
    DevelopmentToolExecutionError,
    DevelopmentToolValidationError,
)
from .config import get_config

# Canonical engine (all Jinja2 / template logic lives here)
from ipfs_datasets_py.processors.development.test_generator_engine import (  # noqa: F401
    TestGeneratorCore,
    TestGeneratorConfig as _EngineConfig,
    TestGeneratorValidationError,
    TestGeneratorExecutionError,
    generate_test_file,
    UNITTEST_TEMPLATE,
    PYTEST_TEMPLATE,
)

logger = logging.getLogger(__name__)


class TestGeneratorTool(BaseDevelopmentTool):
    """
    MCP tool for generating test files from JSON specifications.

    Core generation logic lives in
    :class:`ipfs_datasets_py.processors.development.test_generator_engine.TestGeneratorCore`.
    """

    def __init__(self) -> None:
        super().__init__(
            name="test_generator",
            description="Generate unittest or pytest test files from JSON specifications",
            category="testing",
        )
        cfg = get_config().test_generator
        engine_cfg = _EngineConfig(
            output_dir=cfg.output_dir,
            harness=cfg.harness,
        )
        self._engine = TestGeneratorCore(config=engine_cfg)

    async def _execute_core(self, **kwargs: Any) -> Dict[str, Any]:
        """Delegate to the canonical engine and wrap results."""
        name = kwargs.get("name")
        description = kwargs.get("description", "")
        test_spec = kwargs.get("test_specification")
        output_dir = kwargs.get("output_dir")
        harness = kwargs.get("harness")

        if not name:
            raise DevelopmentToolValidationError("Test name is required")
        if not test_spec:
            raise DevelopmentToolValidationError("Test specification is required")

        try:
            result = self._engine.generate(
                name=name,
                description=description,
                test_specification=test_spec,
                output_dir=output_dir,
                harness=harness,
            )
        except TestGeneratorValidationError as exc:
            raise DevelopmentToolValidationError(str(exc)) from exc
        except TestGeneratorExecutionError as exc:
            raise DevelopmentToolExecutionError(str(exc)) from exc

        return self._create_success_result(
            result,
            {"tool": "test_generator", "timestamp": datetime.now().isoformat()},
        )


# ---------------------------------------------------------------------------
# MCP-registered function wrapper
# ---------------------------------------------------------------------------


def test_generator(
    name: str,
    description: str = "",
    test_specification: Union[str, Dict[str, Any], None] = None,
    output_dir: Optional[str] = None,
    harness: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate test files from JSON specifications.

    Args:
        name: Name of the test suite.
        description: Description of what the tests cover.
        test_specification: JSON specification as string or dict.
        output_dir: Directory to output test files (defaults to config).
        harness: Test framework — ``"unittest"`` or ``"pytest"``.

    Returns:
        Dict containing generation results and metadata.
    """
    tool = TestGeneratorTool()
    try:
        try:
            import sniffio
            sniffio.current_async_library()
            in_async = True
        except (ImportError, AttributeError):
            in_async = False

        if in_async:
            from concurrent.futures import ThreadPoolExecutor

            def _run() -> Dict[str, Any]:
                return anyio.run(
                    tool.execute,
                    name=name,
                    description=description,
                    test_specification=test_specification,
                    output_dir=output_dir,
                    harness=harness,
                )

            with ThreadPoolExecutor() as executor:
                return executor.submit(_run).result()

        return anyio.run(
            tool.execute,
            name=name,
            description=description,
            test_specification=test_specification,
            output_dir=output_dir,
            harness=harness,
        )
    except Exception as exc:
        return {
            "success": False,
            "error": "execution_error",
            "message": f"Failed to execute test generator: {exc}",
            "metadata": {
                "tool": "test_generator",
                "timestamp": datetime.now().isoformat(),
            },
        }
