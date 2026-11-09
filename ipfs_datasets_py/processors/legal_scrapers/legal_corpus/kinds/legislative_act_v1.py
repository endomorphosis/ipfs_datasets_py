"""Legislative-act kind for ``legal-corpus.legislative-act@1``.

Act schema ids are the public-law processor assignments. US Code
consolidation ids are the release-processor and release-schema
assignments. A row that claims one of those ids, or a ``package``
whose prefix is written by ``us_code_scraper.py``, is refused. This
module does not edit US Code scrapers.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

INTERFACE_ID = "legal-corpus.legislative-act@1"

_PROCESSORS = Path(__file__).resolve().parents[3]
_PUBLIC_LAW = "legal_scrapers/federal_scrapers/public_law_change_processor.py"
_USCODE_PROCESSOR = "legal_scrapers/federal_scrapers/uscode_release_processor.py"
_USCODE_RELEASE = "legal_data/uscode_release_schema.py"
_USCODE_SCRAPER = "legal_scrapers/federal_scrapers/us_code_scraper.py"

# Name, then the string read from that assignment. Register order.
_ACT_SOURCES: tuple[tuple[str, str, str], ...] = (
    (_PUBLIC_LAW, "SCHEMA_VERSION", "public-law-change-processor-v1"),
    (_PUBLIC_LAW, "FIXTURE_SCHEMA_VERSION", "public-law-change-fixture-v1"),
)
_USCODE_SOURCES: tuple[tuple[str, str, str], ...] = (
    (_USCODE_PROCESSOR, "SCHEMA_VERSION", "uscode-release-processor-v1"),
    (_USCODE_PROCESSOR, "FIXTURE_SCHEMA_VERSION", "uscode-release-fixture-v1"),
    (_USCODE_RELEASE, "SCHEMA_VERSION", "uscode-sparse-graphrag-release-schema-v2"),
    (_USCODE_RELEASE, "RELEASE_PROFILE", "publicus-ir-graphrag/v2"),
)
_PACKAGE_PREFIXES = ("USHOUSE-USCODE-", "USCODE-")
_CLAIM_FIELDS = ("source_schema_id", "schema_version")


class LegislativeActBindingError(RuntimeError):
    """The legislative-act kind is not bound to the register's source files."""


class LegislativeActRejected(ValueError):
    """The row is not a ``legal-corpus.legislative-act@1`` record."""


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
    raise LegislativeActBindingError(f"{name} is missing from {path}")


def _bound_string(path: Path, name: str, expected: str) -> str:
    value = _module_assignment(path, name)
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        raise LegislativeActBindingError(f"{name} in {path} is not a string")
    if value.value != expected:
        raise LegislativeActBindingError(f"{name} in {path} is {value.value!r}, not {expected!r}")
    return value.value


def _names_assigned(path: Path) -> set[str]:
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


def _bound_package_prefixes(path: Path) -> tuple[str, ...]:
    """Keep the package prefixes that ``us_code_scraper.py`` writes."""

    if "SCHEMA_VERSION" in _names_assigned(path):
        raise LegislativeActBindingError(f"{path} assigns SCHEMA_VERSION")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr) or not node.values:
            continue
        first = node.values[0]
        if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
            continue
        for prefix in _PACKAGE_PREFIXES:
            if first.value == prefix or first.value.startswith(prefix):
                found.add(prefix)
    missing = [prefix for prefix in _PACKAGE_PREFIXES if prefix not in found]
    if missing:
        raise LegislativeActBindingError(f"{path} is missing package prefixes {missing}")
    return _PACKAGE_PREFIXES


def _bind_ids(rows: tuple[tuple[str, str, str], ...]) -> tuple[str, ...]:
    schema_ids: list[str] = []
    seen: set[str] = set()
    for relative, name, expected in rows:
        schema_id = _bound_string(_PROCESSORS / relative, name, expected)
        if schema_id in seen:
            raise LegislativeActBindingError(f"duplicate schema id {schema_id}")
        seen.add(schema_id)
        schema_ids.append(schema_id)
    return tuple(schema_ids)


USCODE_SCHEMA_IDS = _bind_ids(_USCODE_SOURCES)
USCODE_PACKAGE_PREFIXES = _bound_package_prefixes(_PROCESSORS / _USCODE_SCRAPER)
ACT_SCHEMA_IDS = _bind_ids(_ACT_SOURCES)
if set(ACT_SCHEMA_IDS) & set(USCODE_SCHEMA_IDS):
    raise LegislativeActBindingError("an act schema id is also a US Code schema id")
SOURCE_DATASETS = {schema_id: _PUBLIC_LAW for schema_id in ACT_SCHEMA_IDS}
_ACT_REGISTERED = frozenset(ACT_SCHEMA_IDS)
_USCODE_REGISTERED = frozenset(USCODE_SCHEMA_IDS)


def _load_instrument_record() -> type:
    """Load the shared instrument module from the legal corpus tree."""

    path = Path(__file__).resolve().parents[1] / "instrument_v1.py"
    spec = importlib.util.spec_from_file_location("_lcm_instrument_v1_legislative_act", path)
    if spec is None or spec.loader is None:
        raise LegislativeActBindingError(f"instrument module is missing at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    record = getattr(module, "InstrumentRecord", None)
    interface = getattr(module, "INTERFACE_ID", "")
    if record is None or interface != "legal-corpus.instrument@1":
        raise LegislativeActBindingError("instrument_v1.py does not export legal-corpus.instrument@1")
    return record


InstrumentRecord = _load_instrument_record()


@dataclass(frozen=True)
class LegislativeActRecord:
    """One legislative-act row carried as ``legal-corpus.legislative-act@1``."""

    source_row: Mapping[str, Any]
    instrument: InstrumentRecord
    source_schema_id: str

    def __post_init__(self) -> None:
        if self.source_schema_id not in _ACT_REGISTERED:
            raise LegislativeActRejected("source schema id is not in the legislative-act register")
        if self.source_schema_id in _USCODE_REGISTERED:
            raise LegislativeActRejected("US Code consolidation is rejected")
        if self.instrument.kind != "legislative_act":
            raise LegislativeActRejected("instrument kind must be legislative_act")
        if self.instrument.source_schema_id != self.source_schema_id:
            raise LegislativeActRejected("instrument schema id does not match the register")
        row = self.source_row
        if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
            raise LegislativeActRejected("legislative-act row must be a mapping")
        if _uscode_package(row):
            raise LegislativeActRejected("US Code consolidation is rejected")

    @property
    def interface_id(self) -> str:
        return INTERFACE_ID


def _uscode_package(row: Mapping[str, Any]) -> bool:
    package = row.get("package")
    return isinstance(package, str) and package.startswith(USCODE_PACKAGE_PREFIXES)


def _claimed_schema(row: Mapping[str, Any]) -> str:
    """Return the schema id a row claims in a source field."""

    claims: list[str] = []
    for key in _CLAIM_FIELDS:
        if key not in row:
            continue
        value = row[key]
        if not isinstance(value, str) or value.strip() == "":
            raise LegislativeActRejected(f"{key} must be a source schema id")
        claims.append(value)
    if any(item in _USCODE_REGISTERED for item in claims):
        raise LegislativeActRejected("US Code consolidation is rejected")
    if not claims:
        raise LegislativeActRejected("missing source schema id")
    if any(item != claims[0] for item in claims):
        raise LegislativeActRejected("source schema id fields disagree")
    return claims[0]


def accept_legislative_act_row(row: Mapping[str, Any]) -> LegislativeActRecord:
    """Record one public-law schema id, or refuse US Code consolidation.

    Other columns are copied through. ``gazette_act`` is not claimed here.
    """

    if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
        raise LegislativeActRejected("legislative-act row must be a mapping")
    if _uscode_package(row):
        raise LegislativeActRejected("US Code consolidation is rejected")
    claim = _claimed_schema(row)
    if claim not in _ACT_REGISTERED:
        raise LegislativeActRejected("source schema id is not in the legislative-act register")
    copied = {key: row[key] for key in row}
    instrument = InstrumentRecord(
        kind="legislative_act",
        source_schema_id=claim,
        source_schema_version=claim,
        source_dataset=SOURCE_DATASETS[claim],
        source_row=copied,
    )
    return LegislativeActRecord(
        source_row=instrument.source_row,
        instrument=instrument,
        source_schema_id=claim,
    )


def _act_fixture(schema_id: str) -> dict[str, object]:
    """One public-law row shaped like the processor's appropriations fixture."""

    return {
        "schema_version": schema_id,
        "congress": "118",
        "law_number": "47",
        "package_id": "PLAW-118publ47",
        "citation": "Pub. L. 118-47",
        "title": "Further Consolidated Appropriations Act, 2024 (fixture)",
        "text_excerpt": (
            "Making further consolidated appropriations for the fiscal year "
            "ending September 30, 2024."
        ),
        "note": "kept extra",
    }


def _uscode_fixture(schema_id: str) -> dict[str, object]:
    """One consolidated section row from the US Code scraper shape."""

    return {
        "schema_version": schema_id,
        "section_number": "122",
        "heading": "fixture heading",
        "text": "consolidated section body",
        "body_text": "consolidated section body",
        "citations": [],
        "title_number": "35",
        "package": "USCODE-2024-title35",
    }


class LegislativeActRowTest(unittest.TestCase):
    """Accept an act-shaped fixture and reject a US Code fixture."""

    def test_act_fixture_exports_the_interface(self) -> None:
        self.assertEqual(INTERFACE_ID, "legal-corpus.legislative-act@1")
        self.assertEqual(
            ACT_SCHEMA_IDS,
            (
                "public-law-change-processor-v1",
                "public-law-change-fixture-v1",
            ),
        )
        self.assertEqual(
            USCODE_SCHEMA_IDS,
            (
                "uscode-release-processor-v1",
                "uscode-release-fixture-v1",
                "uscode-sparse-graphrag-release-schema-v2",
                "publicus-ir-graphrag/v2",
            ),
        )
        saved: LegislativeActRecord | None = None
        for schema_id in ACT_SCHEMA_IDS:
            source = _act_fixture(schema_id)
            snapshot = dict(source)
            record = accept_legislative_act_row(source)
            self.assertEqual(record.interface_id, "legal-corpus.legislative-act@1")
            self.assertEqual(record.interface_id, INTERFACE_ID)
            self.assertEqual(record.source_schema_id, schema_id)
            self.assertEqual(record.instrument.kind, "legislative_act")
            self.assertEqual(record.instrument.source_schema_id, schema_id)
            self.assertEqual(record.instrument.source_schema_version, schema_id)
            self.assertEqual(record.instrument.source_dataset, _PUBLIC_LAW)
            self.assertEqual(dict(record.source_row), snapshot)
            self.assertEqual(source, snapshot)
            saved = record
        self.assertIsNotNone(saved)
        assert saved is not None
        source["note"] = "changed extra"
        self.assertEqual(saved.source_row["note"], "kept extra")
        with self.assertRaises(TypeError):
            saved.source_row["note"] = "rewritten"

    def test_uscode_fixture_is_rejected(self) -> None:
        for schema_id in USCODE_SCHEMA_IDS:
            row = _uscode_fixture(schema_id)
            with self.subTest(schema_id=schema_id):
                with self.assertRaises(LegislativeActRejected) as caught:
                    accept_legislative_act_row(row)
                self.assertIn("US Code consolidation is rejected", str(caught.exception))
        scraper_row = {
            "section_number": "122",
            "heading": "fixture heading",
            "text": "consolidated section body",
            "body_text": "consolidated section body",
            "citations": [],
            "package": "USCODE-2024-title35",
        }
        with self.assertRaises(LegislativeActRejected) as caught:
            accept_legislative_act_row(scraper_row)
        self.assertIn("US Code consolidation is rejected", str(caught.exception))
        house_row = dict(scraper_row)
        house_row["package"] = "USHOUSE-USCODE-118-2024-title35"
        with self.assertRaises(LegislativeActRejected) as caught:
            accept_legislative_act_row(house_row)
        self.assertIn("US Code consolidation is rejected", str(caught.exception))

    def test_module_does_not_import_uscode_scrapers(self) -> None:
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        for name in names:
            parts = name.split(".")
            self.assertNotIn("us_code_scraper", parts)
            self.assertNotIn("uscode_release_processor", parts)
            self.assertNotIn("uscode_release_schema", parts)
            self.assertNotIn("public_law_change_processor", parts)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LegislativeActRowTest)
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if outcome.wasSuccessful() else 1)
