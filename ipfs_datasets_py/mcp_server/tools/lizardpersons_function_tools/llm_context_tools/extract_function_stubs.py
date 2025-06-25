import ast
import os
from typing import Any, Optional


def _quote_string_constant(node: ast.Constant) -> str:
    """Return a string constant in *double quotes*.

    Args:
        node (ast.Constant): The constant node holding the Python string value.

    Returns:
        str: The string value wrapped in double quotes (``"value"``) with any
        embedded double-quotes escaped.
    """
    text = str(node.value).replace('"', r'\"')
    return f'"{text}"'


def _to_source(node: Optional[ast.AST]) -> str:
    """Convert an ``ast`` node back into source text.

    Args:
        node (ast.AST | None): Node to convert back into valid Python source
            code. ``None`` returns an empty string.

    Returns:
        str: The source-code representation of *node* suitable for re-insertion
        into a function signature.
    """
    if node is None:
        return ""

    # Force string constants to use double quotes because the tests expect it.
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _quote_string_constant(node)

    try:
        return ast.unparse(node)
    except Exception:
        if isinstance(node, ast.Name):
            return node.id
        return ""


def _format_arg(arg: ast.arg, default: Optional[ast.AST]) -> str:
    """Render an :class:`ast.arg` to a string parameter fragment.

    Args:
        arg (ast.arg): The argument node (positional or keyword).
        default (ast.AST | None): The default-value node, or *None* if the
            parameter has no default.

    Returns:
        str: A fragment of a function signature, e.g. ``"a: int = 5"``.
    """
    text = arg.arg
    if arg.annotation is not None:
        text += f": {_to_source(arg.annotation)}"
    if default is not None:
        text += f" = {_to_source(default)}"
    return text


def _build_signature(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Re-create the complete function signature.

    The function reconstructs parameter order, default values, type
    annotations, keyword-only markers, and return annotations in a way that
    matches the expectations of the accompanying unit tests.

    Args:
        fn (ast.FunctionDef | ast.AsyncFunctionDef): The function node for
            which the textual signature should be built.

    Returns:
        str: The signature such as ``"(x: int, *args: str, **kw: Any) -> str"``.
    """
    args = fn.args

    pieces: list[str] = []

    # positional-only and regular positional arguments
    positional = args.posonlyargs + args.args
    total_positional = len(positional)
    num_pos_defaults = len(args.defaults)
    first_default = total_positional - num_pos_defaults

    for idx, arg in enumerate(positional):
        default_node = (
            args.defaults[idx - first_default] if idx >= first_default else None
        )
        pieces.append(_format_arg(arg, default_node))

    # Add the "/" marker for positional-only arguments if any were present
    if args.posonlyargs:
        pieces.insert(len(args.posonlyargs), "/")

    # *args
    if args.vararg:
        var = f"*{args.vararg.arg}"
        if args.vararg.annotation is not None:
            var += f": {_to_source(args.vararg.annotation)}"
        pieces.append(var)
    elif args.kwonlyargs:  # need bare "*" when we have keyword-only args
        pieces.append("*")

    # keyword-only args
    for kwarg, default in zip(args.kwonlyargs, args.kw_defaults):
        pieces.append(_format_arg(kwarg, default))

    # **kwargs
    if args.kwarg:
        starstar = f"**{args.kwarg.arg}"
        if args.kwarg.annotation is not None:
            starstar += f": {_to_source(args.kwarg.annotation)}"
        pieces.append(starstar)

    signature = "(" + ", ".join(pieces) + ")"
    if fn.returns is not None:
        signature += f" -> {_to_source(fn.returns)}"
    return signature


class _StubExtractor(ast.NodeVisitor):
    """AST visitor that gathers function definitions.

    The visitor walks the entire syntax-tree, capturing every ``def`` and
    ``async def`` it encounters - regardless of nesting or control-flow - and
    stores a dictionary describing each callable.

    Args:
        source (str): The original source code being analysed.  Currently
            unused beyond construction but retained for future diagnostics.
    """

    def __init__(self, source: str) -> None:
        self._stubs: list[dict[str, Any]] = []
        self._ancestry_stack: list[ast.AST] = [] # ancestry stack
        self._source = source

    # Public helper
    def results(self) -> list[dict[str, Any]]:
        """Return the list of collected stub dictionaries."""
        return self._stubs

    # Visitor overrides
    def generic_visit(self, node: ast.AST) -> None:  # type: ignore[override]
        """Push *node* on a stack so children can see their parent."""
        self._ancestry_stack.append(node)
        super().generic_visit(node)
        self._ancestry_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        """Handle nested classes while preserving ancestry."""
        # Just use the generic behaviour but keep it on the stack so its
        # children (methods / nested classes) can look back at it.
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._collect(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa:N802
        self._collect(node, is_async=True)

    # Internal helpers
    def _collect(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        is_async: bool,
    ) -> None:
        """Assemble a stub dictionary for *node*.

        Args:
            node (ast.FunctionDef | ast.AsyncFunctionDef): The function node
                being processed.
            is_async (bool): ``True`` if *node* is an ``async def``.
        """
        parent = self._ancestry_stack[-1] if self._ancestry_stack else None
        is_method = isinstance(parent, ast.ClassDef)
        class_name = parent.name if is_method else None

        stub: dict[str, Any] = {
            "name": node.name,
            "signature": _build_signature(node),
            "docstring": ast.get_docstring(node),
            "is_async": is_async,
            "is_method": is_method,
            "class_name": class_name,
        }
        self._stubs.append(stub)

        # Recurse into the function body to find nested functions
        self.generic_visit(node)


def _write_markdown(stubs: list[dict[str, Any]], file_path: str, path: str) -> None:
    """Write *stubs* to a markdown file.

    Args:
        stubs: The list returned by :func:`extract_function_stubs`.
        path: Destination path for the ``.md`` file. Will be **overwritten** if
            it already exists.
    """
    lines: list[str] = [f"# Function stubs from '{file_path}'\n"]
    three_quotes = '    """'

    for stub in stubs:
        def_ = "async def" if stub['is_async'] is True else "def"
        lines.append(f"## {stub['name']}\n")
        lines.append("```python")
        lines.append(f"{def_} {stub['name']}{stub['signature']}:")
        if stub["docstring"]:
            lines.append(three_quotes)
            lines.append(f"    {stub['docstring']}")
            lines.append(three_quotes)
        lines.append("```")
        lines.append(f"* **Async:** {stub['is_async']}")
        lines.append(f"* **Method:** {stub['is_method']}")
        lines.append(
            f"* **Class:** {stub['class_name'] if stub['class_name'] else 'N/A'}\n"
        )


    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip() + "\n")


def extract_function_stubs(file_path: str, markdown_path: Optional[str] = None) -> list[dict[str, Any]]:
    """Extract function stubs from a Python file.
    
    Parses a Python file to identify all callable definitions and extracts
    their signatures, type hints, and docstrings to create function stubs.

    Args:
        file_path (str): Path to the Python file to analyze.
        markdown_path (Optional[str]): If provided, the function will write
            the extracted stubs to a markdown file at this path. If not
            specified, no markdown file will be created.

    Returns:
        list[dict[str, Any]]: A list of dictionaries, each containing:
            - 'name' (str): The function/class name
            - 'signature' (str): Complete function signature with type hints
            - 'docstring' (Optional[str]): The function's docstring if present
            - 'is_async' (bool): Whether the function is an async function
            - 'is_method' (bool): Whether the function is a class method
            - 'class_name' (Optional[str]): Name of containing class if is_method is True

    Raises:
        FileNotFoundError: If the specified file does not exist.
        PermissionError: If the file cannot be read due to permission issues.
        SyntaxError: If the Python file contains syntax errors.
        ValueError: If the file_path is empty or invalid.
        OSError: If there are other file system related errors.
    
    Example:
        >>> stubs = extract_function_stubs('my_module.py')
        >>> for stub in stubs:
        ...     print(f"Function: {stub['name']}")
        ...     print(f"Signature: {stub['signature']}")
        ...     if stub['docstring']:
        ...         print(f"Docstring: {stub['docstring'][:50]}...")
        >>> # Example usage in a script:
        >>> stubs = extract_function_stubs('./src/utils.py')
        >>> async_funcs = [s for s in stubs if s['is_async']]
    """
    # validation & file-system checks
    if not file_path:
        raise ValueError("file_path must be a non-empty string")

    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    if not os.path.isfile(file_path):
        # Could be a directory or special file; let the caller decide.
        raise IsADirectoryError(file_path)

    # read source (raises PermissionError et al.)
    with open(file_path, "r", encoding="utf-8") as fh:
        source = fh.read()

    # Empty / comment-only files should simply return an empty list
    if not source.strip():
        return []

    # parse the module
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:  # re-raise verbatim (tests expect exact type)
        raise

    # walk the AST
    extractor = _StubExtractor(source)
    extractor.visit(tree)
    stubs =  extractor.results()

    # optional markdown
    if markdown_path is not None:
        _write_markdown(stubs, file_path, markdown_path)

    return stubs
