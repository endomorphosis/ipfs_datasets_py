"""Shared instrument record for ``legal-corpus.instrument@1``.

A record names one instrument kind and the source schema it was read from,
and stores that source row without dropping or rewriting its fields. This
module does not import scrapers and does not replace ``interfaces.py``.
"""

from __future__ import annotations

import ast
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

INTERFACE_ID = "legal-corpus.instrument@1"

KINDS: tuple[str, ...] = (
    "law",
    "regulation",
    "legislative_act",
    "caselaw",
    "court",
    "municipal_instrument",
)

_KINDS = frozenset(KINDS)


class InstrumentRejected(ValueError):
    """The values are not a ``legal-corpus.instrument@1`` record."""


def _string_field(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise InstrumentRejected(f"{field} must be a string")
    return value


@dataclass(frozen=True)
class InstrumentRecord:
    """One source row carried as ``legal-corpus.instrument@1``."""

    kind: str
    source_schema_id: str
    source_schema_version: str
    source_dataset: str
    source_row: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in _KINDS:
            raise InstrumentRejected(f"unknown kind {self.kind!r}")
        schema_id = _string_field(self.source_schema_id, "source_schema_id")
        if schema_id.strip() == "":
            raise InstrumentRejected("empty source schema id")
        version = _string_field(self.source_schema_version, "source_schema_version")
        dataset = _string_field(self.source_dataset, "source_dataset")
        row = self.source_row
        if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
            raise InstrumentRejected("source row must be a mapping")
        copied = {key: row[key] for key in row}
        object.__setattr__(self, "source_schema_id", schema_id)
        object.__setattr__(self, "source_schema_version", version)
        object.__setattr__(self, "source_dataset", dataset)
        object.__setattr__(self, "source_row", MappingProxyType(copied))

    @property
    def interface_id(self) -> str:
        """Interface id exported by this module."""

        return INTERFACE_ID


def _sample_row() -> dict[str, object]:
    return {"text": "kept", "extra": 1}


class InstrumentRejectionTest(unittest.TestCase):
    """Reject an unknown kind and an empty source schema id."""

    def test_unknown_kind_is_rejected(self) -> None:
        with self.assertRaises(InstrumentRejected) as caught:
            InstrumentRecord(
                kind="statute",
                source_schema_id="schema-under-test",
                source_schema_version="version-under-test",
                source_dataset="dataset-under-test",
                source_row=_sample_row(),
            )
        self.assertIn("unknown kind", str(caught.exception))

    def test_empty_source_schema_id_is_rejected(self) -> None:
        for schema_id in ("", "   "):
            with self.subTest(schema_id=repr(schema_id)):
                with self.assertRaises(InstrumentRejected) as caught:
                    InstrumentRecord(
                        kind="law",
                        source_schema_id=schema_id,
                        source_schema_version="version-under-test",
                        source_dataset="dataset-under-test",
                        source_row=_sample_row(),
                    )
                self.assertIn("empty source schema id", str(caught.exception))

    def test_known_kinds_keep_the_source_row(self) -> None:
        source = _sample_row()
        snapshot = dict(source)
        saved: InstrumentRecord | None = None
        for kind in KINDS:
            record = InstrumentRecord(
                kind=kind,
                source_schema_id="schema-under-test",
                source_schema_version="version-under-test",
                source_dataset="dataset-under-test",
                source_row=source,
            )
            self.assertEqual(record.interface_id, "legal-corpus.instrument@1")
            self.assertEqual(record.interface_id, INTERFACE_ID)
            self.assertEqual(record.kind, kind)
            self.assertEqual(dict(record.source_row), snapshot)
            self.assertEqual(source, snapshot)
            saved = record
        self.assertIsNotNone(saved)
        assert saved is not None
        source["text"] = "changed"
        self.assertEqual(saved.source_row["text"], "kept")
        self.assertEqual(saved.source_row["extra"], 1)
        with self.assertRaises(TypeError):
            saved.source_row["extra"] = 2

    def test_module_does_not_import_scrapers_or_sibling_contracts(self) -> None:
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        banned = ("interfaces", "document_role", "registry", "scraper")
        for name in names:
            for part in banned:
                self.assertNotIn(part, name)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(InstrumentRejectionTest)
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if outcome.wasSuccessful() else 1)
