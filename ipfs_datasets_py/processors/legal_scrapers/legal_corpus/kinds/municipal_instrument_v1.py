"""Municipal instrument kind for ``legal-corpus.municipal-instrument@1``.

The 19 canonical columns are ``EXPECTED_COLUMNS`` in ``world_municipal/schema.py``.
That file assigns no ``SCHEMA_VERSION``. Extra columns are accepted only
after those 19. A NULL in a string column is rejected. ``doc_order`` stays
an integer. This module does not import ``schema.py`` and does not edit it.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

INTERFACE_ID = "legal-corpus.municipal-instrument@1"
SOURCE_SCHEMA_FILE = "world_municipal/schema.py"
SOURCE_DATASET = "world_municipal"

_SCHEMA = Path(__file__).resolve().parents[2] / "world_municipal" / "schema.py"
_EXPECTED_COLUMNS = (
    "cid",
    "jurisdiction_id",
    "jurisdiction_name",
    "country",
    "doc_id",
    "regeling_id",
    "regeling_work_id",
    "doc_order",
    "title",
    "structural_path",
    "node_label",
    "html_title",
    "html",
    "text",
    "source_url",
    "xml_url",
    "date_effective",
    "date_modified",
    "retrieved",
)
_DOC_ORDER = "doc_order"
_INTEGER_FUNCTIONS = ("build_schema", "validate_table")


class MunicipalBindingError(RuntimeError):
    """The municipal kind is not bound to ``world_municipal/schema.py``."""


class MunicipalRejected(ValueError):
    """The row is not a ``legal-corpus.municipal-instrument@1`` record."""


def _module_assignment(path: Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
            value = node.value
        else:
            continue
        if value is None:
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            return value
    raise MunicipalBindingError(f"{name} is missing from {path}")


def _assigned_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _bound_columns(path: Path, name: str) -> tuple[str, ...]:
    value = _module_assignment(path, name)
    if not isinstance(value, (ast.Tuple, ast.List)):
        raise MunicipalBindingError(f"{name} in {path} is not a sequence")
    columns: list[str] = []
    for item in value.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            raise MunicipalBindingError(f"{name} in {path} contains a non-string")
        columns.append(item.value)
    if not columns:
        raise MunicipalBindingError(f"{name} in {path} is empty")
    return tuple(columns)


def _function(path: Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise MunicipalBindingError(f"{name} is missing from {path}")


def _pa_call(value: ast.AST | None, attr: str) -> bool:
    if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Attribute):
        return False
    return (
        isinstance(value.func.value, ast.Name)
        and value.func.value.id == "pa"
        and value.func.attr == attr
        and not value.args
        and not value.keywords
    )


def _doc_order_ifexp(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if not isinstance(node, ast.IfExp) or not isinstance(node.test, ast.Compare):
            continue
        test = node.test
        if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
            continue
        if len(test.comparators) != 1:
            continue
        left = test.left
        right = test.comparators[0]
        if not isinstance(left, ast.Name) or left.id != "name":
            continue
        if not isinstance(right, ast.Constant) or right.value != _DOC_ORDER:
            continue
        body = isinstance(node.body, ast.Name) and node.body.id == "_UINT32"
        orelse = isinstance(node.orelse, ast.Name) and node.orelse.id == "_STRING"
        if body and orelse:
            return True
    return False


def _trailing_extra_name(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    doc = ast.get_docstring(tree) or ""
    marker = "appends ``"
    start = doc.find(marker)
    if start < 0:
        raise MunicipalBindingError("schema docstring does not name a trailing extra column")
    rest = doc[start + len(marker):]
    end = rest.find("``")
    if end <= 0:
        raise MunicipalBindingError("trailing extra column name is missing")
    name = rest[:end]
    if any(character.isspace() for character in name):
        raise MunicipalBindingError("trailing extra column name is not one token")
    return name


def _bind_schema() -> tuple[tuple[str, ...], str]:
    """Read the 19 columns and the integer ``doc_order`` rule from the file."""

    if _SCHEMA.parts[-2:] != ("world_municipal", "schema.py"):
        raise MunicipalBindingError(f"{_SCHEMA} is not world_municipal/schema.py")
    if "SCHEMA_VERSION" in _assigned_names(_SCHEMA):
        raise MunicipalBindingError(f"{_SCHEMA} assigns SCHEMA_VERSION")
    columns = _bound_columns(_SCHEMA, "EXPECTED_COLUMNS")
    if columns != _EXPECTED_COLUMNS or len(columns) != 19:
        raise MunicipalBindingError(
            f"EXPECTED_COLUMNS in {_SCHEMA} is {columns!r}, not the 19 canonical columns"
        )
    if columns.index(_DOC_ORDER) != 7:
        raise MunicipalBindingError("doc_order is not at index 7")
    if not _pa_call(_module_assignment(_SCHEMA, "_UINT32"), "uint32"):
        raise MunicipalBindingError("_UINT32 is not pa.uint32()")
    if not _pa_call(_module_assignment(_SCHEMA, "_STRING"), "string"):
        raise MunicipalBindingError("_STRING is not pa.string()")
    for name in _INTEGER_FUNCTIONS:
        if not _doc_order_ifexp(_function(_SCHEMA, name)):
            raise MunicipalBindingError(f"{name} does not type doc_order as _UINT32")
    extra = _trailing_extra_name(_SCHEMA)
    if extra != "tipo":
        raise MunicipalBindingError(f"trailing extra column is {extra!r}, not 'tipo'")
    return columns, extra


CANONICAL_COLUMNS, TRAILING_EXTRA_EXAMPLE = _bind_schema()


def _load_instrument_record() -> type:
    """Load the shared instrument module from the legal corpus tree."""

    path = Path(__file__).resolve().parents[1] / "instrument_v1.py"
    spec = importlib.util.spec_from_file_location("_lcm_municipal_instrument_host", path)
    if spec is None or spec.loader is None:
        raise MunicipalBindingError(f"instrument module is missing at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    record = getattr(module, "InstrumentRecord", None)
    interface = getattr(module, "INTERFACE_ID", "")
    kinds = getattr(module, "KINDS", ())
    if record is None or interface != "legal-corpus.instrument@1":
        raise MunicipalBindingError("instrument_v1.py does not export legal-corpus.instrument@1")
    if "municipal_instrument" not in kinds:
        raise MunicipalBindingError("instrument kinds do not include municipal_instrument")
    return record


InstrumentRecord = _load_instrument_record()


def _validate(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Require the 19 columns first, strings without NULL, and an integer order."""

    if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
        raise MunicipalRejected("municipal row must be a mapping")
    keys = tuple(row.keys())
    width = len(CANONICAL_COLUMNS)
    if keys[:width] != CANONICAL_COLUMNS:
        raise MunicipalRejected(
            "canonical columns must be the first 19 in order; "
            "extra columns are only allowed after those 19"
        )
    for name in CANONICAL_COLUMNS:
        if name == _DOC_ORDER:
            continue
        if row[name] is None:
            raise MunicipalRejected(f"NULL in string column {name}")
        if not isinstance(row[name], str):
            raise MunicipalRejected(f"{name} must be a string")
    order = row[_DOC_ORDER]
    if isinstance(order, bool) or not isinstance(order, int):
        raise MunicipalRejected("doc_order stays an integer")
    for name in keys[width:]:
        if row[name] is None:
            raise MunicipalRejected(f"NULL in string column {name}")
        if not isinstance(row[name], str):
            raise MunicipalRejected(f"{name} must be a string")
    return keys


@dataclass(frozen=True)
class MunicipalRecord:
    """One municipal row carried as ``legal-corpus.municipal-instrument@1``."""

    source_row: Mapping[str, Any]
    instrument: InstrumentRecord
    doc_order: int

    def __post_init__(self) -> None:
        _validate(self.source_row)
        if self.instrument.kind != "municipal_instrument":
            raise MunicipalRejected("instrument kind must be municipal_instrument")
        if self.instrument.source_schema_id != SOURCE_SCHEMA_FILE:
            raise MunicipalRejected("source schema does not cite world_municipal/schema.py")
        if self.instrument.source_schema_version != SOURCE_SCHEMA_FILE:
            raise MunicipalRejected("source schema does not cite world_municipal/schema.py")
        if self.instrument.source_dataset != SOURCE_DATASET:
            raise MunicipalRejected("source dataset must be world_municipal")
        if type(self.doc_order) is not int or self.source_row[_DOC_ORDER] != self.doc_order:
            raise MunicipalRejected("doc_order stays an integer")
        if type(self.source_row[_DOC_ORDER]) is not int:
            raise MunicipalRejected("doc_order stays an integer")

    @property
    def interface_id(self) -> str:
        return INTERFACE_ID


def accept_municipal_row(row: Mapping[str, Any]) -> MunicipalRecord:
    """Accept a municipal row when the 19 columns are first and ``doc_order`` is an int.

    A column named in the schema docstring may follow those 19. A NULL in a
    string column is rejected. ``doc_order`` is not coerced to a string.
    """

    keys = _validate(row)
    copied = {key: row[key] for key in keys}
    instrument = InstrumentRecord(
        kind="municipal_instrument",
        source_schema_id=SOURCE_SCHEMA_FILE,
        source_schema_version=SOURCE_SCHEMA_FILE,
        source_dataset=SOURCE_DATASET,
        source_row=copied,
    )
    return MunicipalRecord(
        source_row=instrument.source_row,
        instrument=instrument,
        doc_order=instrument.source_row[_DOC_ORDER],
    )


def _fixture() -> dict[str, object]:
    row: dict[str, object] = {}
    for name in CANONICAL_COLUMNS:
        row[name] = 0 if name == _DOC_ORDER else name
    return row


class MunicipalRowTest(unittest.TestCase):
    """Column order, one trailing extra, and a NULL string rejection."""

    def test_column_order_rejects_a_reorder_and_a_middle_extra(self) -> None:
        self.assertEqual(INTERFACE_ID, "legal-corpus.municipal-instrument@1")
        self.assertEqual(len(CANONICAL_COLUMNS), 19)
        self.assertEqual(CANONICAL_COLUMNS[7], "doc_order")
        self.assertEqual(TRAILING_EXTRA_EXAMPLE, "tipo")
        source = _fixture()
        items = list(source.items())
        items[0], items[1] = items[1], items[0]
        with self.assertRaises(MunicipalRejected) as caught:
            accept_municipal_row(dict(items))
        self.assertIn("only allowed after those 19", str(caught.exception))
        inserted = list(source.items())
        inserted.insert(3, (TRAILING_EXTRA_EXAMPLE, "kept extra"))
        with self.assertRaises(MunicipalRejected) as caught:
            accept_municipal_row(dict(inserted))
        self.assertIn("only allowed after those 19", str(caught.exception))

    def test_trailing_extra_column_keeps_doc_order_as_an_integer(self) -> None:
        source = _fixture()
        source[TRAILING_EXTRA_EXAMPLE] = "kept extra"
        snapshot = dict(source)
        record = accept_municipal_row(source)
        self.assertEqual(record.interface_id, "legal-corpus.municipal-instrument@1")
        self.assertEqual(record.interface_id, INTERFACE_ID)
        self.assertEqual(record.instrument.kind, "municipal_instrument")
        self.assertEqual(record.instrument.source_schema_id, "world_municipal/schema.py")
        self.assertEqual(record.instrument.source_schema_version, "world_municipal/schema.py")
        self.assertEqual(record.instrument.source_dataset, "world_municipal")
        self.assertEqual(tuple(record.source_row), tuple(snapshot))
        self.assertEqual(record.source_row[TRAILING_EXTRA_EXAMPLE], "kept extra")
        self.assertIs(type(record.doc_order), int)
        self.assertEqual(record.doc_order, 0)
        self.assertIs(type(record.source_row["doc_order"]), int)
        self.assertEqual(source, snapshot)
        source["title"] = "changed"
        source["doc_order"] = 4
        self.assertEqual(record.source_row["title"], "title")
        self.assertEqual(record.doc_order, 0)
        with self.assertRaises(TypeError):
            record.source_row["title"] = "rewritten"

    def test_null_in_a_string_column_is_rejected(self) -> None:
        missing = _fixture()
        missing["title"] = None
        with self.assertRaises(MunicipalRejected) as caught:
            accept_municipal_row(missing)
        self.assertIn("NULL in string column title", str(caught.exception))
        extra_null = _fixture()
        extra_null[TRAILING_EXTRA_EXAMPLE] = None
        with self.assertRaises(MunicipalRejected) as caught:
            accept_municipal_row(extra_null)
        self.assertIn("NULL in string column tipo", str(caught.exception))

    def test_doc_order_string_bool_and_null_are_rejected(self) -> None:
        for value in ("0", True, None, 1.0):
            with self.subTest(value=repr(value)):
                row = _fixture()
                row["doc_order"] = value
                with self.assertRaises(MunicipalRejected) as caught:
                    accept_municipal_row(row)
                self.assertIn("doc_order stays an integer", str(caught.exception))

    def test_module_does_not_import_the_schema_module(self) -> None:
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        banned = ("world_municipal", "schema", "pyarrow", "normalize", "torch", "cuda")
        for name in names:
            for part in banned:
                self.assertNotIn(part, name.split("."))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MunicipalRowTest)
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if outcome.wasSuccessful() else 1)
