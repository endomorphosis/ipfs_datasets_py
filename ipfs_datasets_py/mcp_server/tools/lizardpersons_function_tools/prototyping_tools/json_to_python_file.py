
from mcp_server.utils import python_builtins
from typing import Any

class _UnKnownNodeException(Exception):
    pass

# class MissingArgumentException(Exception):
#     pass

class _JsonToAst:

    def __init__(self):
        self.ast = python_builtins.ast
        self._AST = self.ast.AST

    @property
    def _NODE_MAP(self) -> dict[str, dict[str, Any]]:
        return {
        "Constant": {
            "node": self.ast.Constant,
            "args": ["value"]
        },
        "FormattedValue": {
            "node": self.ast.FormattedValue,
            "args": ["value, conversion, format_spec"]
        },
        "JoinedStr": {
            "node": self.ast.JoinedStr,
            "args": ["values"]
        },
        "List": {
            "node": self.ast.List,
            "args": ["elts, ctx"]
        },
        "Tuple": {
            "node": self.ast.Tuple,
            "args": ["elts", "ctx"]
        },
        "Set": {
            "node": self.ast.Set,
            "args": ["elts"]
        },
        "Dict": {
            "node": self.ast.Dict,
            "args": ["keys", "values"]
        },
        "Name": {
            "node": self.ast.Name,
            "args": ["id", "ctx"]
        },
        "Load": {
            "node": self.ast.Load,
            "args": []
        },
        "Store": {
            "node": self.ast.Store,
            "args": []
        },
        "Del": {
            "node": self.ast.Del,
            "args": []
        },
        "Starred": {
            "node": self.ast.Starred,
            "args": ['value, ctx']
        },
        "Expr": {
            "node": self.ast.Expr,
            "args": ["value"]
        },
        "UnaryOp": {
            "node": self.ast.UnaryOp,
            "args": ["op, operand"]
        },
        "UAdd": {
            "node": self.ast.UAdd,
            "args": []
        },
        "USub": {
            "node": self.ast.USub,
            "args": []
        },
        "Not": {
            "node": self.ast.Not,
            "args": []
        },
        "Invert": {
            "node": self.ast.Invert,
            "args": []
        },
        "BinOp": {
            "node": self.ast.BinOp,
            "args": ["left", "op", "right"]
        },
        "Add": {
            "node": self.ast.Add,
            "args": []
        },
        "Sub": {
            "node": self.ast.Sub,
            "args": []
        },
        "Mult": {
            "node": self.ast.Mult,
            "args": []
        },
        "Div": {
            "node": self.ast.Div,
            "args": []
        },
        "FloorDiv": {
            "node": self.ast.FloorDiv,
            "args": []
        },
        "Mod": {
            "node": self.ast.Mod,
            "args": []
        },
        "Pow": {
            "node": self.ast.Pow,
            "args": []
        },
        "LShift": {
            "node": self.ast.LShift,
            "args": []
        },
        "RShift": {
            "node": self.ast.RShift,
            "args": []
        },
        "BitOr": {
            "node": self.ast.BitOr,
            "args": []
        },
        "BitXor": {
            "node": self.ast.BitXor,
            "args": []
        },
        "BitAnd": {
            "node": self.ast.BitAnd,
            "args": []
        },
        "MatMult": {
            "node": self.ast.MatMult,
            "args": []
        },
        "BoolOp": {
            "node": self.ast.BoolOp,
            "args": ["op, values"]
        },
        "And": {
            "node": self.ast.And,
            "args": []
        },
        "Or": {
            "node": self.ast.Or,
            "args": []
        },
        "Compare": {
            "node": self.ast.Compare,
            "args": ["left", "ops", "comparators"]
        },
        "Eq": {
            "node": self.ast.Eq,
            "args": []
        },
        "NotEq": {
            "node": self.ast.NotEq,
            "args": []
        },
        "Lt": {
            "node": self.ast.Lt,
            "args": []
        },
        "LtE": {
            "node": self.ast.LtE,
            "args": [],
        },
        "Gt": {
            "node": self.ast.Gt,
            "args": [],
        },
        "GtE": {
            "node": self.ast.GtE,
            "args": [],
        },
        "Is": {
            "node": self.ast.Is,
            "args": [],
        },
        "IsNot": {
            "node": self.ast.IsNot,
            "args": [],
        },
        "In": {
            "node": self.ast.In,
            "args": [],
        },
        "NotIn": {
            "node": self.ast.NotIn,
            "args": [],
        },
        "Call": {
            "node": self.ast.Call,
            "args": ["func", "args", "keywords", "starargs", "kwargs"]
        },
        "keyword": {
            "node": self.ast.keyword,
            "args": ["arg", "value"]
        },
        "IfExp": {
            "node": self.ast.IfExp,
            "args": ["test", "body", "orelse"]
        },
        "Attribute": {
            "node": self.ast.Attribute,
            "args": ["value", "attr", "ctx"]
        },
        "NamedExpr": {
            "node": self.ast.NamedExpr,
            "args": ["target", "value"]
        },
        "Subscript": {
            "node": self.ast.Subscript,
            "args": ["value", "slice", "ctx"]
        },
        "Slice": {
            "node": self.ast.Slice,
            "args": ["lower", "upper", "step"]
        },
        "ListComp": {
            "node": self.ast.ListComp,
            "args": ["elt", "generators"]
        },
        "SetComp": {
            "node": self.ast.SetComp,
            "args": ["elt", "generators"]
        },
        "GeneratorExp": {
            "node": self.ast.GeneratorExp,
            "args": ["elt", "generators"]
        },
        "DictComp": {
            "node": self.ast.DictComp,
            "args": ["key", "value", "generators"]
        },
        "comprehension": {
            "node": self.ast.comprehension,
            "args": ["target", "iter", "ifs", "is_async"]
        },
        "Assign": {
            "node": self.ast.Assign,
            "args": ["targets", "value", "type_comment"]
        },
        "AnnAssign": {
            "node": self.ast.AnnAssign,
            "args": ["target", "annotation", "value", "simple"]
        },
        "AugAssign": {
            "node": self.ast.AugAssign,
            "args": ["target", "op", "value"]
        },
        "Raise": {
            "node": self.ast.Raise,
            "args": ["exc", "cause"]
        },
        "Assert": {
            "node": self.ast.Assert,
            "args": ["test", "msg"]
        },
        "Delete": {
            "node": self.ast.Delete,
            "args": ["targets"]
        },
        "Pass": {
            "node": self.ast.Pass,
            "args": []
        },
        "Import": {
            "node": self.ast.Import,
            "args": ["names"],
        },
        "ImportFrom": {
            "node": self.ast.ImportFrom,
            "args": ["module", "names", "level"]
        },
        "alias": {
            "node": self.ast.alias,
            "args": ["name", "asname"]
        },
        "If": {
            "node": self.ast.If,
            "args": ["test", "body", "orelse"]
        },
        "For": {
            "node": self.ast.For,
            "args": ["target", "iter", "body", "orelse", "type_comment"]
        },
        "While": {
            "node": self.ast.While,
            "args": ["test", "body", "orelse"]
        },
        "Break": {
            "node": self.ast.Break,
            "args": []
        },
        "Continue": {
            "node": self.ast.Continue,
            "args": []
        },
        "Try": {
            "node": self.ast.Try,
            "args": ["body", "handlers", "orelse", "finalbody"]
        },
        "ExceptHandler": {
            "node": self.ast.ExceptHandler,
            "args": ["type", "name", "body"]
        },
        "With": {
            "node": self.ast.With,
            "args": ["items", "body", "type_comment"]
        },
        "withitem": {
            "node": self.ast.withitem,
            "args": ["context_expr", "optional_vars"]
        },
        "Match": {
            "node": self.ast.Match,
            "args": ["subject", "cases"]
        },
        "match_case": {
            "node": self.ast.match_case,
            "args": ["pattern", "guard", "body"]
        },
        "MatchValue": {
            "node": self.ast.MatchValue,
            "args": ["value"]
        },
        "MatchSingleton": {
            "node": self.ast.MatchSingleton,
            "args": ["value"]
        },
        "MatchSequence": {
            "node": self.ast.MatchSequence,
            "args": ["patterns"],
        },
        "MatchStar": {
            "node": self.ast.MatchStar,
            "args": ["name"],
        },
        "MatchMapping": {
            "node": self.ast.MatchMapping,
            "args": ["keys", "patterns", "rest"]
        },
        "MatchClass": {
            "node": self.ast.MatchClass,
            "args": ["cls", "patterns", "kwd_attrs", "kwd_patterns"]
        },
        "MatchAs": {
            "node": self.ast.MatchAs,
            "args": ["pattern", "name"]
        },
        "MatchOr": {
            "node": self.ast.MatchOr,
            "args": ["patterns"]
        },
        "FunctionDef": {
            "node": self.ast.FunctionDef,
            "args": ["name", "args", "body", "decorator_list", "returns", "type_comment"]
        },
        "Lambda": {
            "node": self.ast.Lambda,
            "args": ["args", "body"]
        },
        "arguments": {
            "node": self.ast.arguments,
            "args": ["posonlyargs", "args", "vararg", "kwonlyargs", "kw_defaults", "kwarg", "defaults"]
        },
        "arg": {
            "node": self.ast.arg,
            "args": ["arg", "annotation", "type_comment"]
        },
        "Return": {
            "node": self.ast.Return,
            "args": ["value"]
        },
        "Yield": {
            "node": self.ast.Yield,
            "args": ["value"]
        },
        "YieldFrom": {
            "node": self.ast.YieldFrom,
            "args": ["value"]
        },
        "Global": {
            "node": self.ast.Global,
            "args": ["names"]
        },
        "Nonlocal": {
            "node": self.ast.Nonlocal,
            "args": ["names"]
        },
        "ClassDef": {
            "node": self.ast.ClassDef,
            "args": ["name", "bases", "keywords", "starargs", "kwargs", "body", "decorator_list"]
        },
        "AsyncFunctionDef": {
            "node": self.ast.AsyncFunctionDef,
            "args": ["name", "args", "body", "decorator_list", "returns", "type_comment"]
        },
        "AsyncFor": {
            "node": self.ast.AsyncFor,
            "args": ["target", "iter", "body", "orelse", "type_comment"]
        },
        "AsyncWith": {
            "node": self.ast.AsyncWith,
            "args": ["items", "body", "type_comment"]
        },
        # Top Level Nodes
        "Module": {
            "node": self.ast.Module,
            "args": ["body"]
        },
        "Expression": {
            "node": self.ast.Expression,
            "args": ["body"]
        },
    }

    def _resolve_argument(self, arg: Any):
        match arg:
            case list():
                return [self._resolve_argument(item) for item in arg]
            case dict() if "_type" in arg:
                return self._resolve_node(arg)
            case _:
                return arg


    def _resolve_node(self, node: dict) -> Any:
        if "_type" not in node:
            return None
        
        node_type = node['_type']

        if node_type not in self._NODE_MAP:
            raise _UnKnownNodeException(f"Unknown node type: {node_type}")

        args = {}

        # Organize necessary args in the proper order
        '''
        for arg in NODE_MAP[node_type]["args"]:
            try:
                args[arg] = node[arg]
            except KeyError:
                args[arg] = None
        '''

        # Iterate over arguments and resolve any child nodes that we find
        for arg in node:
            args[arg] = self._resolve_argument(node[arg])

        # Create node with properly resolved arguments
        return self._NODE_MAP[node_type]["node"](**args)


def json_to_python_file(data: dict | str, output_path: str) -> None:
    """
    Convert a JSON file or JSON-like dictionary representation of a Python file into an actual Python file.

    Args:
        data (dict | str): The JSON data representing the Python file. If a string is provided, it is parsed as path to JSON file.
        output_path (str): The path where the Python file will be saved.

    Returns:
        None: A python file of the converted code.
    """
    if not isinstance(output_path, str):
        raise TypeError(f"'output_path' argument must be a string representing the file path, not {type(e).__name__}.")
    if not output_path.endswith('.py'):
        raise ValueError("'output_path' must output to a python file (e.g. ends with .py).")

    if not isinstance(data, (dict, str)):
        raise TypeError("'data' argument must be a dictionary or a path to a JSON file.")
    else:
        # If it's a string, see if it's a path to a JSON file.
        if isinstance(data, str):
            from pathlib import Path
            path = Path(data)
            if not path.exists() or not path.is_file():
                raise FileNotFoundError(f"JSON file not found at '{data}'")
            if path.suffix.lower() not in {".json", ".jsonl", ".jsonlines"}:
                raise ValueError(f"Path is not a json or jsonl file, but {path.suffix.lower()}.")

            # Try to load the JSON file.
            import json
            output = None
            for func in [json.load, json.loads]:
                try:
                    with open(path, 'r') as file:
                        output = func(file)
                    break
                except Exception:
                    continue
            if output is None:
                raise ValueError(f"Failed to read JSON data from {data}. Ensure it is a valid JSON file.")
            data = dict(output)

    # Get the AST tree from the JSON data
    try:
        ast_tree = _JsonToAst()._resolve_node(data)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise ValueError(f"Failed to convert JSON data to AST: {e}") from e

    # Turn ths AST tree back into a string representation of Python code
    try:
        file_content = _JsonToAst().ast.unparse(ast_tree)
    except Exception as e:
        import traceback
        raise ValueError(f"Failed to unparse AST tree to Python code: {e}") from e

    try:
        with open(Path(output_path).resolve(), 'w') as file:
            file.write(file_content)
    except Exception as e:
        raise IOError(f"Failed to write Python file to '{output_path}': {e}") from e
