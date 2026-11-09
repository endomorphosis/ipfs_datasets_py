"""Regulation kind for ``legal-corpus.regulation@1``.

Source schema ids are the ``SCHEMA_VERSION`` assignments named by the
regulation register. Three register sources assign no schema version, so
this module does not invent one for them. A row that claims the statute
schema or ``worldwide-legal-search.law-source@1`` is refused. This module
does not edit the law kind module.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

INTERFACE_ID = "legal-corpus.regulation@1"
LAW_SOURCE_SCHEMA = "worldwide-legal-search.law-source@1"
STATUTE_SCHEMA_ID = "country-laws-ir-graphrag/v1"

_PROCESSORS = Path(__file__).resolve().parents[3]
_STATUTE_SCHEMA = _PROCESSORS / "legal_scrapers" / "country_laws_ir" / "__init__.py"

# Register order. The expected string is the assignment read from that file.
_REGISTER_SOURCES: tuple[tuple[str, str], ...] = (
    ("legal_scrapers/federal_scrapers/cfr_annual_processor.py", "cfr-annual-processor-v1"),
    ("legal_scrapers/federal_scrapers/live_cfr_source_processor.py", "live-cfr-source-processor-v1"),
    ("legal_scrapers/federal_scrapers/ecfr_crosscheck_processor.py", "ecfr-crosscheck-processor-v1"),
    ("legal_scrapers/federal_scrapers/federal_register_change_processor.py", "federal-register-change-processor-v1"),
    ("legal_data/federal_register_release_schema.py", "federal-register-sparse-graphrag-release-schema-v2"),
)
_CLAIM_FIELDS = ("source_schema_id", "schema_version")


class RegulationBindingError(RuntimeError):
    """The regulation kind is not bound to the register's source files."""


class RegulationRejected(ValueError):
    """The row is not a ``legal-corpus.regulation@1`` record."""


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
    raise RegulationBindingError(f"{name} is missing from {path}")


def _bound_string(path: Path, name: str, expected: str) -> str:
    value = _module_assignment(path, name)
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        raise RegulationBindingError(f"{name} in {path} is not a string")
    if value.value != expected:
        raise RegulationBindingError(f"{name} in {path} is {value.value!r}, not {expected!r}")
    return value.value


def _bind_register() -> tuple[tuple[str, ...], dict[str, str]]:
    """Read each register source schema id from the file that assigns it."""

    schema_ids: list[str] = []
    datasets: dict[str, str] = {}
    for relative, expected in _REGISTER_SOURCES:
        path = _PROCESSORS / relative
        schema_id = _bound_string(path, "SCHEMA_VERSION", expected)
        if schema_id in datasets:
            raise RegulationBindingError(f"duplicate regulation schema id {schema_id}")
        schema_ids.append(schema_id)
        datasets[schema_id] = relative
    if LAW_SOURCE_SCHEMA in datasets or STATUTE_SCHEMA_ID in datasets:
        raise RegulationBindingError("a refused schema id was bound as a regulation source")
    return tuple(schema_ids), datasets


SOURCE_SCHEMA_IDS, SOURCE_DATASETS = _bind_register()
STATUTE_SCHEMA_ID = _bound_string(_STATUTE_SCHEMA, "SCHEMA_VERSION", STATUTE_SCHEMA_ID)
_REGISTERED = frozenset(SOURCE_SCHEMA_IDS)


def _load_instrument_record() -> type:
    """Load the shared instrument module from the legal corpus tree."""

    path = Path(__file__).resolve().parents[1] / "instrument_v1.py"
    spec = importlib.util.spec_from_file_location("_lcm_instrument_v1_regulation", path)
    if spec is None or spec.loader is None:
        raise RegulationBindingError(f"instrument module is missing at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    record = getattr(module, "InstrumentRecord", None)
    interface = getattr(module, "INTERFACE_ID", "")
    if record is None or interface != "legal-corpus.instrument@1":
        raise RegulationBindingError("instrument_v1.py does not export legal-corpus.instrument@1")
    return record


InstrumentRecord = _load_instrument_record()


@dataclass(frozen=True)
class RegulationRecord:
    """One regulation row carried as ``legal-corpus.regulation@1``."""

    source_row: Mapping[str, Any]
    instrument: InstrumentRecord
    source_schema_id: str

    def __post_init__(self) -> None:
        if self.source_schema_id not in _REGISTERED:
            raise RegulationRejected("source schema id is not in the regulation register")
        if self.source_schema_id == LAW_SOURCE_SCHEMA:
            raise RegulationRejected("row claims worldwide-legal-search.law-source@1")
        if self.source_schema_id == STATUTE_SCHEMA_ID:
            raise RegulationRejected("statute schema id is rejected")
        if self.instrument.kind != "regulation":
            raise RegulationRejected("instrument kind must be regulation")
        if self.instrument.source_schema_id != self.source_schema_id:
            raise RegulationRejected("instrument schema id does not match the register")
        row = self.source_row
        if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
            raise RegulationRejected("regulation row must be a mapping")

    @property
    def interface_id(self) -> str:
        return INTERFACE_ID


def _claimed_schema(row: Mapping[str, Any]) -> str:
    """Return the schema id a row claims in a source field."""

    claims: list[str] = []
    for key in _CLAIM_FIELDS:
        if key not in row:
            continue
        value = row[key]
        if not isinstance(value, str) or value.strip() == "":
            raise RegulationRejected(f"{key} must be a source schema id")
        claims.append(value)
    if not claims:
        raise RegulationRejected("missing source schema id")
    if any(item != claims[0] for item in claims):
        raise RegulationRejected("source schema id fields disagree")
    return claims[0]


def accept_regulation_row(row: Mapping[str, Any]) -> RegulationRecord:
    """Record one registered source schema id, or refuse the row.

    ``worldwide-legal-search.law-source@1`` and the statute schema id are
    refused even though both are absent from the regulation register.
    Other columns are copied through. The register has no shared column tuple.
    """

    if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
        raise RegulationRejected("regulation row must be a mapping")
    claim = _claimed_schema(row)
    if claim == LAW_SOURCE_SCHEMA:
        raise RegulationRejected("row claims worldwide-legal-search.law-source@1")
    if claim == STATUTE_SCHEMA_ID:
        raise RegulationRejected("statute schema id is rejected")
    if claim not in _REGISTERED:
        raise RegulationRejected("source schema id is not in the regulation register")
    copied = {key: row[key] for key in row}
    instrument = InstrumentRecord(
        kind="regulation",
        source_schema_id=claim,
        source_schema_version=claim,
        source_dataset=SOURCE_DATASETS[claim],
        source_row=copied,
    )
    return RegulationRecord(
        source_row=instrument.source_row,
        instrument=instrument,
        source_schema_id=claim,
    )


class RegulationRowTest(unittest.TestCase):
    """Record a register schema id and reject a statute schema id."""

    def test_register_schema_id_is_recorded(self) -> None:
        self.assertEqual(
            SOURCE_SCHEMA_IDS,
            (
                "cfr-annual-processor-v1",
                "live-cfr-source-processor-v1",
                "ecfr-crosscheck-processor-v1",
                "federal-register-change-processor-v1",
                "federal-register-sparse-graphrag-release-schema-v2",
            ),
        )
        self.assertNotIn(LAW_SOURCE_SCHEMA, SOURCE_SCHEMA_IDS)
        self.assertNotIn(STATUTE_SCHEMA_ID, SOURCE_SCHEMA_IDS)
        saved: RegulationRecord | None = None
        for schema_id in SOURCE_SCHEMA_IDS:
            source = {
                "schema_version": schema_id,
                "citation": "37 CFR 1.1",
                "text_excerpt": "fixture body",
                "note": "kept extra",
            }
            snapshot = dict(source)
            record = accept_regulation_row(source)
            self.assertEqual(record.interface_id, "legal-corpus.regulation@1")
            self.assertEqual(record.interface_id, INTERFACE_ID)
            self.assertEqual(record.source_schema_id, schema_id)
            self.assertEqual(record.instrument.kind, "regulation")
            self.assertEqual(record.instrument.source_schema_id, schema_id)
            self.assertEqual(record.instrument.source_schema_version, schema_id)
            self.assertEqual(record.instrument.source_dataset, SOURCE_DATASETS[schema_id])
            self.assertEqual(dict(record.source_row), snapshot)
            self.assertEqual(source, snapshot)
            saved = record
        self.assertIsNotNone(saved)
        assert saved is not None
        source["note"] = "changed extra"
        self.assertEqual(saved.source_row["note"], "kept extra")
        with self.assertRaises(TypeError):
            saved.source_row["note"] = "rewritten"

    def test_statute_schema_id_is_rejected(self) -> None:
        self.assertEqual(STATUTE_SCHEMA_ID, "country-laws-ir-graphrag/v1")
        claimed = {
            "id": "statute-1",
            "title": "Example statute",
            "text": "The fixture body is present.",
            "schema_version": STATUTE_SCHEMA_ID,
        }
        with self.assertRaises(RegulationRejected) as caught:
            accept_regulation_row(claimed)
        self.assertIn("statute schema id is rejected", str(caught.exception))

    def test_law_source_schema_is_rejected(self) -> None:
        self.assertEqual(LAW_SOURCE_SCHEMA, "worldwide-legal-search.law-source@1")
        for key in _CLAIM_FIELDS:
            row = {
                "id": "law-source-row",
                "title": "Statute view",
                "text": "not a regulation",
                key: LAW_SOURCE_SCHEMA,
            }
            with self.subTest(field=key):
                with self.assertRaises(RegulationRejected) as caught:
                    accept_regulation_row(row)
                self.assertIn("worldwide-legal-search.law-source@1", str(caught.exception))

    def test_module_does_not_import_the_law_kind(self) -> None:
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        for name in names:
            parts = name.split(".")
            self.assertNotIn("law_v1", parts)
            self.assertNotIn("query", parts)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RegulationRowTest)
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if outcome.wasSuccessful() else 1)
