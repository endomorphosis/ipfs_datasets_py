"""Law kind for ``legal-corpus.law@1``.

The interface is bound to the statute schema and the admission-verifier
schema exported by ``country_laws_ir``. A row is accepted only when that
package's required law columns are present. Extra columns are copied
through. This module does not edit ``instrument_v1.py`` or ``query.py``.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

INTERFACE_ID = "legal-corpus.law@1"
SOURCE_SCHEMA_VERSION = "country-laws-ir-graphrag/v1"
VERIFY_SCHEMA_VERSION = "country-laws-normalize-verify/v1"

_COUNTRY_LAWS = Path(__file__).resolve().parents[2] / "country_laws_ir"
_PACKAGE_SCHEMA = _COUNTRY_LAWS / "__init__.py"
_VERIFY_SCHEMA = _COUNTRY_LAWS / "verify.py"
_COLUMN_SCHEMA = _COUNTRY_LAWS / "schema.py"


class LawBindingError(RuntimeError):
    """The law kind is not bound to the country-laws source files."""


class LawRejected(ValueError):
    """The row is not a ``legal-corpus.law@1`` record."""


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
    raise LawBindingError(f"{name} is missing from {path}")


def _bound_string(path: Path, name: str, expected: str) -> str:
    value = _module_assignment(path, name)
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        raise LawBindingError(f"{name} in {path} is not a string")
    if value.value != expected:
        raise LawBindingError(f"{name} in {path} is {value.value!r}, not {expected!r}")
    return value.value


def _bound_columns(path: Path, name: str) -> tuple[str, ...]:
    value = _module_assignment(path, name)
    if not isinstance(value, (ast.Tuple, ast.List)):
        raise LawBindingError(f"{name} in {path} is not a sequence")
    columns: list[str] = []
    for item in value.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            raise LawBindingError(f"{name} in {path} contains a non-string")
        columns.append(item.value)
    return tuple(columns)


SOURCE_SCHEMA_VERSION = _bound_string(
    _PACKAGE_SCHEMA,
    "SCHEMA_VERSION",
    SOURCE_SCHEMA_VERSION,
)
VERIFY_SCHEMA_VERSION = _bound_string(
    _VERIFY_SCHEMA,
    "SCHEMA_VERSION",
    VERIFY_SCHEMA_VERSION,
)
REQUIRED_LAW_COLUMNS = _bound_columns(_COLUMN_SCHEMA, "REQUIRED_LAW_COLUMNS")
SOURCE_DATASET = _COUNTRY_LAWS.name


def _require_register_columns() -> None:
    """Keep the column contract on the names ``schema.py`` actually assigns."""

    if REQUIRED_LAW_COLUMNS != ("id", "title", "text"):
        raise LawBindingError(
            f"required law columns are {REQUIRED_LAW_COLUMNS!r}, not ('id', 'title', 'text')"
        )


def _load_instrument_record() -> type:
    """Load the shared instrument module from the legal corpus tree."""

    path = Path(__file__).resolve().parents[1] / "instrument_v1.py"
    spec = importlib.util.spec_from_file_location("_lcm_instrument_v1", path)
    if spec is None or spec.loader is None:
        raise LawBindingError(f"instrument module is missing at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    record = getattr(module, "InstrumentRecord", None)
    interface = getattr(module, "INTERFACE_ID", "")
    if record is None or interface != "legal-corpus.instrument@1":
        raise LawBindingError("instrument_v1.py does not export legal-corpus.instrument@1")
    return record


_require_register_columns()
InstrumentRecord = _load_instrument_record()


@dataclass(frozen=True)
class LawRecord:
    """One statute row carried as ``legal-corpus.law@1``."""

    source_row: Mapping[str, Any]
    instrument: InstrumentRecord
    source_schema_version: str
    verify_schema_version: str

    def __post_init__(self) -> None:
        if self.source_schema_version != SOURCE_SCHEMA_VERSION:
            raise LawRejected("source schema is not country-laws-ir-graphrag/v1")
        if self.verify_schema_version != VERIFY_SCHEMA_VERSION:
            raise LawRejected("verify schema is not country-laws-normalize-verify/v1")
        if self.instrument.kind != "law":
            raise LawRejected("instrument kind must be law")
        if self.instrument.source_schema_version != SOURCE_SCHEMA_VERSION:
            raise LawRejected("instrument schema is not country-laws-ir-graphrag/v1")
        row = self.source_row
        if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
            raise LawRejected("law row must be a mapping")
        for column in REQUIRED_LAW_COLUMNS:
            if column not in row:
                raise LawRejected(f"missing required column {column}")

    @property
    def interface_id(self) -> str:
        return INTERFACE_ID


def accept_law_row(row: Mapping[str, Any]) -> LawRecord:
    """Accept a law row when every required column is present.

    Columns are checked in ``REQUIRED_LAW_COLUMNS`` order. The returned
    row keeps every key from the input, including keys the register does
    not list.
    """

    if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
        raise LawRejected("law row must be a mapping")
    for column in REQUIRED_LAW_COLUMNS:
        if column not in row:
            raise LawRejected(f"missing required column {column}")
    copied = {key: row[key] for key in row}
    instrument = InstrumentRecord(
        kind="law",
        source_schema_id=SOURCE_SCHEMA_VERSION,
        source_schema_version=SOURCE_SCHEMA_VERSION,
        source_dataset=SOURCE_DATASET,
        source_row=copied,
    )
    return LawRecord(
        source_row=instrument.source_row,
        instrument=instrument,
        source_schema_version=SOURCE_SCHEMA_VERSION,
        verify_schema_version=VERIFY_SCHEMA_VERSION,
    )


def _valid_fixture() -> dict[str, object]:
    return {
        "id": "law-fixture-1",
        "title": "Example statute",
        "text": "The fixture body is present.",
        "source_url": "https://example.test/laws/1",
        "note": "kept extra",
    }


class LawRowTest(unittest.TestCase):
    """One valid fixture, and one fixture missing ``text``."""

    def test_valid_fixture_keeps_extra_columns(self) -> None:
        source = _valid_fixture()
        snapshot = dict(source)
        record = accept_law_row(source)
        self.assertEqual(record.interface_id, "legal-corpus.law@1")
        self.assertEqual(record.interface_id, INTERFACE_ID)
        self.assertEqual(record.source_schema_version, "country-laws-ir-graphrag/v1")
        self.assertEqual(record.verify_schema_version, "country-laws-normalize-verify/v1")
        self.assertEqual(record.instrument.kind, "law")
        self.assertEqual(record.instrument.source_schema_id, "country-laws-ir-graphrag/v1")
        self.assertEqual(record.instrument.source_dataset, "country_laws_ir")
        self.assertEqual(list(record.source_row), list(snapshot))
        self.assertEqual(dict(record.source_row), snapshot)
        self.assertEqual(source, snapshot)
        source["text"] = "changed"
        source["note"] = "changed extra"
        self.assertEqual(record.source_row["text"], "The fixture body is present.")
        self.assertEqual(record.source_row["note"], "kept extra")
        self.assertEqual(record.source_row["source_url"], snapshot["source_url"])
        with self.assertRaises(TypeError):
            record.source_row["note"] = "rewritten"

    def test_fixture_missing_text_is_rejected(self) -> None:
        missing = _valid_fixture()
        del missing["text"]
        self.assertNotIn("text", missing)
        with self.assertRaises(LawRejected) as caught:
            accept_law_row(missing)
        self.assertIn("missing required column text", str(caught.exception))

    def test_module_does_not_import_query(self) -> None:
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        for name in names:
            self.assertNotIn("query", name.split("."))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LawRowTest)
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if outcome.wasSuccessful() else 1)
