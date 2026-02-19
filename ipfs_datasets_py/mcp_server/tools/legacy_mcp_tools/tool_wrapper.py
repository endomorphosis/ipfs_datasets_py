
from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Union, get_type_hints

from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool


class FunctionTool(ClaudeMCPTool):
    """
    Wrap a plain function (sync or async) as a ClaudeMCPTool.
    """

    def __init__(
        self,
        function: Callable,
        tool_name: str,
        category: str = "general",
        description: Optional[str] = None,
        tags: Optional[list] = None,
    ):
        super().__init__()
        self.function = function
        self.name = tool_name
        self.category = category
        self.description = description or (function.__doc__ or f"Execute {tool_name}")
        self.tags = tags or []
        self.input_schema = self._extract_input_schema()

    def _python_type_to_json_type(self, python_type) -> str:
        if python_type == inspect.Parameter.empty:
            return "string"
        mapping = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object", type(None): "null"}
        if python_type in mapping:
            return mapping[python_type]
        if hasattr(python_type, "__origin__"):
            origin = python_type.__origin__
            if origin in (list, list):
                return "array"
            if origin in (dict, dict):
                return "object"
        if isinstance(python_type, str):
            low = python_type.lower()
            if low in ("str", "string"):
                return "string"
            if low in ("int", "integer"):
                return "integer"
            if low in ("float", "number"):
                return "number"
            if low in ("bool", "boolean"):
                return "boolean"
            if low in ("list", "array"):
                return "array"
            if low in ("dict", "object"):
                return "object"
        return "string"

    def _extract_input_schema(self) -> Dict[str, Any]:
        try:
            sig = inspect.signature(self.function)
            hints = get_type_hints(self.function)
            properties: Dict[str, Any] = {}
            required = []
            for name, param in sig.parameters.items():
                ptype = hints.get(name, param.annotation)
                entry: Dict[str, Any] = {"type": self._python_type_to_json_type(ptype), "description": f"Parameter {name}"}
                if param.default is inspect.Parameter.empty:
                    required.append(name)
                else:
                    entry["default"] = param.default
                properties[name] = entry
            schema: Dict[str, Any] = {"type": "object", "properties": properties}
            if required:
                schema["required"] = required
            return schema
        except (TypeError, ValueError):
            return {"type": "object", "properties": {}}

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if inspect.iscoroutinefunction(self.function):
                result = await self.function(**parameters)
            else:
                result = self.function(**parameters)
            if not isinstance(result, dict):
                result = {"result": result}
            result.update({
                "tool_name": self.name,
                "executed_at": datetime.now(tz=timezone.utc).isoformat(),
                "success": result.get("success", True),
            })
            return result
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "tool_name": self.name,
                "executed_at": datetime.now(tz=timezone.utc).isoformat(),
            }


def wrap_function_as_tool(*args, **kwargs) -> Union[FunctionTool, Callable]:
    """
    Wrap functions as MCP tools with dual usage styles.

    Helper style:
        wrap_function_as_tool(function, tool_name, category="general", description=None, tags=None)
        -> returns FunctionTool

    Decorator style:
        @wrap_function_as_tool(name="tool_name", category="general", description=None, tags=None)
        async def my_tool(...): ...
        -> returns original function with metadata attached (for external registries)
    """
    if args and callable(args[0]):
        function: Callable = args[0]
        tool_name: str = args[1] if len(args) > 1 else function.__name__
        category: str = args[2] if len(args) > 2 else kwargs.get("category", "general")
        description: Optional[str] = kwargs.get("description")
        tags: Optional[list] = kwargs.get("tags")
        return FunctionTool(function=function, tool_name=tool_name, category=category, description=description, tags=tags)

    name: Optional[str] = kwargs.get("name") or (args[0] if args else None)
    category: str = kwargs.get("category", "general")
    description: Optional[str] = kwargs.get("description")
    tags: Optional[list] = kwargs.get("tags")

    def decorator(function: Callable):
        try:
            setattr(function, "__mcp_tool_name__", name or function.__name__)
            setattr(function, "__mcp_tool_category__", category)
            if description:
                setattr(function, "__mcp_tool_description__", description)
            if tags:
                setattr(function, "__mcp_tool_tags__", tags)
        except AttributeError:
            pass