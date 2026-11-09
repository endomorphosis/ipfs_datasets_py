"""Court kind for ``legal-corpus.court@1``.

The court register's schema id is ``unversioned`` because the institution
constructor and the world-courts publisher assign no ``SCHEMA_VERSION``.
A row must name that schema id and a ``court_id``. Opinion text is
refused. A docket number is not written into the statute ``id`` column.
This module does not import scrapers.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

INTERFACE_ID = "legal-corpus.court@1"
UNVERSIONED_SCHEMA_ID = "unversioned"
WORLD_COURTS_REPO = "endomorphosis/world_courts"
STATUTE_SCHEMA_ID = "country-laws-ir-graphrag/v1"

_PROCESSORS = Path(__file__).resolve().parents[3]
_COURTS_COMMON = (
    "legal_scrapers/hub_integrated/world_law_pipeline/scrapers/courts/intl/courts_common.py"
)
_COURTS_UPLOAD = (
    "legal_scrapers/hub_integrated/world_law_pipeline/scrapers/courts/upload_world_courts.py"
)
_DILA = "legal_scrapers/national_collectors/collect_fr_dila.py"
_RECAP = "legal_scrapers/recap_archive_scraper.py"
_CAP = "legal_scrapers/caselaw_access_program/vector_search_integration.py"
_STATUTE_SCHEMA = "legal_scrapers/country_laws_ir/__init__.py"
_STATUTE_COLUMNS = "legal_scrapers/country_laws_ir/schema.py"

_CLAIM_FIELDS = ("source_schema_id", "schema_version")
_OPINION_BODY_NAMES = ("text", "opinion_text", "case_text")


class CourtBindingError(RuntimeError):
    """The court kind is not bound to the register's source files."""


class CourtRejected(ValueError):
    """The row is not a ``legal-corpus.court@1`` record."""


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
    raise CourtBindingError(f"{name} is missing from {path}")


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


def _bound_string(path: Path, name: str, expected: str) -> str:
    value = _module_assignment(path, name)
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        raise CourtBindingError(f"{name} in {path} is not a string")
    if value.value != expected:
        raise CourtBindingError(f"{name} in {path} is {value.value!r}, not {expected!r}")
    return value.value


def _bound_columns(path: Path, name: str) -> tuple[str, ...]:
    value = _module_assignment(path, name)
    if not isinstance(value, (ast.Tuple, ast.List)):
        raise CourtBindingError(f"{name} in {path} is not a sequence")
    columns: list[str] = []
    for item in value.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            raise CourtBindingError(f"{name} in {path} contains a non-string")
        columns.append(item.value)
    if not columns:
        raise CourtBindingError(f"{name} in {path} is empty")
    return tuple(columns)


def _unversioned(path: Path) -> str:
    """Schema id used when the source file assigns no ``SCHEMA_VERSION``."""

    if "SCHEMA_VERSION" in _names_assigned(path):
        raise CourtBindingError(f"{path} assigns SCHEMA_VERSION")
    return UNVERSIONED_SCHEMA_ID


def _find_function(path: Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise CourtBindingError(f"{name} is missing from {path}")


def _dict_keys(node: ast.Dict) -> tuple[str, ...] | None:
    keys: list[str] = []
    for key in node.keys:
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        keys.append(key.value)
    if not keys:
        return None
    return tuple(keys)


def _call_keywords(fn: ast.AST, call_name: str, required: str) -> tuple[str, ...]:
    matches: list[tuple[str, ...]] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != call_name:
            continue
        names = tuple(keyword.arg for keyword in node.keywords if keyword.arg)
        if required in names and names not in matches:
            matches.append(names)
    if len(matches) != 1:
        raise CourtBindingError(f"{call_name} keyword list count for {required} is {len(matches)}")
    return matches[0]


def _return_dict_keys(fn: ast.AST, required: str) -> tuple[str, ...]:
    matches: list[tuple[str, ...]] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
            continue
        keys = _dict_keys(node.value)
        if keys and required in keys and keys not in matches:
            matches.append(keys)
    if len(matches) != 1:
        raise CourtBindingError(f"return dict count for {required} is {len(matches)}")
    return matches[0]


def _dict_with_keys(fn: ast.AST, required: tuple[str, ...]) -> tuple[str, ...]:
    matches: list[tuple[str, ...]] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Dict):
            continue
        keys = _dict_keys(node)
        if keys and all(name in keys for name in required) and keys not in matches:
            matches.append(keys)
    if len(matches) != 1:
        raise CourtBindingError(f"dict count for {required} is {len(matches)}")
    return matches[0]


def _class_body(path: Path, class_name: str) -> list[ast.stmt]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return list(node.body)
    raise CourtBindingError(f"{class_name} is missing from {path}")


def _class_tuple(path: Path, class_name: str, field: str) -> tuple[str, ...]:
    for stmt in _class_body(path, class_name):
        if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
            continue
        if stmt.target.id != field or not isinstance(stmt.value, ast.Tuple):
            continue
        values: list[str] = []
        for item in stmt.value.elts:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                raise CourtBindingError(f"{field} in {path} contains a non-string")
            values.append(item.value)
        if not values:
            raise CourtBindingError(f"{field} in {path} is empty")
        return tuple(values)
    raise CourtBindingError(f"{field} is missing from {class_name} in {path}")


def _bind_register() -> dict[str, Any]:
    """Read the court identifier and the opinion fields from the source files."""

    common_path = _PROCESSORS / _COURTS_COMMON
    upload_path = _PROCESSORS / _COURTS_UPLOAD
    dila_path = _PROCESSORS / _DILA
    recap_path = _PROCESSORS / _RECAP
    cap_path = _PROCESSORS / _CAP
    common_schema = _unversioned(common_path)
    upload_schema = _unversioned(upload_path)
    if common_schema != upload_schema:
        raise CourtBindingError("court schema ids diverged")
    repo = _bound_string(upload_path, "DS", WORLD_COURTS_REPO)
    if repo == common_schema:
        raise CourtBindingError("world courts repo id was bound as the schema id")
    rec_fields = _call_keywords(_find_function(common_path, "rec"), "dict", "court_id")
    flat_fields = _return_dict_keys(_find_function(upload_path, "flat_court"), "court_id")
    dila_fields = _return_dict_keys(_find_function(dila_path, "parse"), "text")
    document_fields = _dict_with_keys(
        _find_function(recap_path, "get_recap_document"),
        ("text", "metadata"),
    )
    docket_fields = _dict_with_keys(
        _find_function(recap_path, "get_recap_document"),
        ("docket_number",),
    )
    cap_text_fields = _class_tuple(cap_path, "CAPVectorSearchConfig", "text_field_candidates")
    statute_columns = _bound_columns(_PROCESSORS / _STATUTE_COLUMNS, "REQUIRED_LAW_COLUMNS")
    statute_schema = _bound_string(_PROCESSORS / _STATUTE_SCHEMA, "SCHEMA_VERSION", STATUTE_SCHEMA_ID)
    if statute_columns[0] != "id":
        raise CourtBindingError(f"statute id column is {statute_columns[0]!r}, not 'id'")
    opinion_fields = tuple(name for name in _OPINION_BODY_NAMES if name in cap_text_fields)
    if opinion_fields != _OPINION_BODY_NAMES:
        raise CourtBindingError(f"opinion body fields are {opinion_fields!r}")
    if "text" not in dila_fields or "text" not in document_fields:
        raise CourtBindingError("opinion text key is missing from a caselaw source")
    if "docket_number" not in docket_fields:
        raise CourtBindingError("docket_number is missing from the RECAP document")
    for label, fields in (("rec", rec_fields), ("flat_court", flat_fields)):
        if "court_id" not in fields:
            raise CourtBindingError(f"{label} is missing court_id")
        if "text" in fields or "docket_number" in fields or statute_columns[0] in fields:
            raise CourtBindingError(f"{label} carries an opinion, docket, or statute field")
    if statute_schema in {common_schema, repo}:
        raise CourtBindingError("statute schema id collided with the court register")
    return {
        "schema_id": common_schema,
        "repo": repo,
        "rec_fields": rec_fields,
        "flat_fields": flat_fields,
        "opinion_fields": opinion_fields,
        "statute_id_field": statute_columns[0],
        "statute_schema": statute_schema,
        "source_dataset": _COURTS_COMMON,
    }


_BOUND = _bind_register()
SOURCE_SCHEMA_ID = str(_BOUND["schema_id"])
WORLD_COURTS_REPO = str(_BOUND["repo"])
REC_FIELDS = tuple(_BOUND["rec_fields"])
FLAT_COURT_FIELDS = tuple(_BOUND["flat_fields"])
OPINION_BODY_FIELDS = tuple(_BOUND["opinion_fields"])
STATUTE_ID_FIELD = str(_BOUND["statute_id_field"])
STATUTE_SCHEMA_ID = str(_BOUND["statute_schema"])
SOURCE_DATASET = str(_BOUND["source_dataset"])


def _load_instrument_record() -> type:
    """Load the shared instrument module from the legal corpus tree."""

    path = Path(__file__).resolve().parents[1] / "instrument_v1.py"
    spec = importlib.util.spec_from_file_location("_lcm_instrument_v1_court", path)
    if spec is None or spec.loader is None:
        raise CourtBindingError(f"instrument module is missing at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    record = getattr(module, "InstrumentRecord", None)
    interface = getattr(module, "INTERFACE_ID", "")
    if record is None or interface != "legal-corpus.instrument@1":
        raise CourtBindingError("instrument_v1.py does not export legal-corpus.instrument@1")
    return record


InstrumentRecord = _load_instrument_record()


@dataclass(frozen=True)
class CourtRecord:
    """One court row carried as ``legal-corpus.court@1``."""

    source_row: Mapping[str, Any]
    instrument: InstrumentRecord
    source_schema_id: str
    court_id: str

    def __post_init__(self) -> None:
        if self.source_schema_id != SOURCE_SCHEMA_ID:
            raise CourtRejected("source schema id is not in the court register")
        if self.source_schema_id == STATUTE_SCHEMA_ID:
            raise CourtRejected("statute schema id is rejected")
        if not isinstance(self.court_id, str) or self.court_id.strip() == "":
            raise CourtRejected("court identifier is required")
        if self.instrument.kind != "court":
            raise CourtRejected("instrument kind must be court")
        if self.instrument.source_schema_id != self.source_schema_id:
            raise CourtRejected("instrument schema id does not match the register")
        row = self.source_row
        if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
            raise CourtRejected("court row must be a mapping")
        if _opinion_key(row):
            raise CourtRejected("opinion text is refused")
        if _docket_number(row) and _statute_id(row) == _docket_number(row):
            raise CourtRejected("docket number is not a statute id")
        if row.get("court_id") != self.court_id:
            raise CourtRejected("court identifier does not match the row")

    @property
    def interface_id(self) -> str:
        return INTERFACE_ID


def _opinion_key(row: Mapping[str, Any]) -> str:
    for key in OPINION_BODY_FIELDS:
        if key not in row:
            continue
        value = row[key]
        if isinstance(value, str) and value.strip() != "":
            return key
    return ""


def _docket_number(row: Mapping[str, Any]) -> str:
    value = row.get("docket_number")
    if isinstance(value, str) and value.strip() != "":
        return value
    metadata = row.get("metadata")
    if isinstance(metadata, Mapping) and not isinstance(metadata, (str, bytes)):
        nested = metadata.get("docket_number")
        if isinstance(nested, str) and nested.strip() != "":
            return nested
    return ""


def _statute_id(row: Mapping[str, Any]) -> str:
    value = row.get(STATUTE_ID_FIELD)
    if isinstance(value, str):
        return value
    return ""


def _claimed_schema(row: Mapping[str, Any]) -> str:
    """Return the schema id a row names in a source field."""

    claims: list[str] = []
    for key in _CLAIM_FIELDS:
        if key not in row:
            continue
        value = row[key]
        if not isinstance(value, str) or value.strip() == "":
            raise CourtRejected(f"{key} must be a source schema id")
        claims.append(value)
    if not claims:
        raise CourtRejected("missing source schema id")
    if any(item != claims[0] for item in claims):
        raise CourtRejected("source schema id fields disagree")
    return claims[0]


def _court_identifier(row: Mapping[str, Any]) -> str:
    """Return ``court_id``. A docket number is not a substitute."""

    if "court_id" not in row:
        raise CourtRejected("court identifier is required")
    value = row.get("court_id")
    if not isinstance(value, str) or value.strip() == "":
        raise CourtRejected("court identifier is required")
    return value


def accept_court_row(row: Mapping[str, Any]) -> CourtRecord:
    """Record one court identifier and the register schema id.

    Opinion text is refused. ``docket_number`` is never copied into the
    statute ``id`` column, and it is never used as ``court_id``. Other
    institution fields are copied through.
    """

    if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
        raise CourtRejected("court row must be a mapping")
    if _opinion_key(row):
        raise CourtRejected("opinion text is refused")
    docket = _docket_number(row)
    if docket and _statute_id(row) == docket:
        raise CourtRejected("docket number is not a statute id")
    claim = _claimed_schema(row)
    if claim == STATUTE_SCHEMA_ID:
        raise CourtRejected("statute schema id is rejected")
    if claim == WORLD_COURTS_REPO:
        raise CourtRejected("world courts repo id is not the schema id")
    if claim != SOURCE_SCHEMA_ID:
        raise CourtRejected("source schema id is not in the court register")
    court_id = _court_identifier(row)
    if court_id == docket and docket:
        raise CourtRejected("docket number is not a court identifier")
    copied = {key: row[key] for key in row}
    if docket and copied.get(STATUTE_ID_FIELD) == docket:
        raise CourtRejected("docket number is not a statute id")
    instrument = InstrumentRecord(
        kind="court",
        source_schema_id=claim,
        source_schema_version=claim,
        source_dataset=SOURCE_DATASET,
        source_row=copied,
    )
    return CourtRecord(
        source_row=instrument.source_row,
        instrument=instrument,
        source_schema_id=claim,
        court_id=court_id,
    )


def _court_fixture() -> dict[str, object]:
    """One institution row using fields ``rec`` assigns."""

    return {
        "source_schema_id": SOURCE_SCHEMA_ID,
        "court_id": "example-court",
        "record_type": "courthouse",
        "name": "Example Courthouse",
        "country_code": "US",
        "level": "other",
        "court_system": "state",
        "note": "kept extra",
    }


def _opinion_fixture() -> dict[str, object]:
    """One opinion row whose body is the ``text`` key ``parse`` returns."""

    return {
        "source_schema_id": SOURCE_SCHEMA_ID,
        "court": "Cour de cassation",
        "court_id": "example-court",
        "text": "The fixture decision body.",
        "docket_number": "19-12.345",
        "id": "19-12.345",
    }


class CourtRowTest(unittest.TestCase):
    """Accept a court identifier and reject an opinion body."""

    def test_court_row_exports_the_interface(self) -> None:
        self.assertEqual(INTERFACE_ID, "legal-corpus.court@1")
        self.assertEqual(SOURCE_SCHEMA_ID, "unversioned")
        self.assertEqual(WORLD_COURTS_REPO, "endomorphosis/world_courts")
        self.assertNotEqual(SOURCE_SCHEMA_ID, WORLD_COURTS_REPO)
        self.assertIn("court_id", REC_FIELDS)
        self.assertIn("court_id", FLAT_COURT_FIELDS)
        self.assertNotIn("text", REC_FIELDS)
        self.assertNotIn("text", FLAT_COURT_FIELDS)
        self.assertNotIn("docket_number", REC_FIELDS)
        self.assertNotIn("docket_number", FLAT_COURT_FIELDS)
        self.assertNotIn(STATUTE_ID_FIELD, REC_FIELDS)
        self.assertNotIn(STATUTE_ID_FIELD, FLAT_COURT_FIELDS)
        self.assertEqual(STATUTE_ID_FIELD, "id")
        self.assertEqual(STATUTE_SCHEMA_ID, "country-laws-ir-graphrag/v1")
        source = _court_fixture()
        snapshot = dict(source)
        record = accept_court_row(source)
        self.assertEqual(record.interface_id, "legal-corpus.court@1")
        self.assertEqual(record.interface_id, INTERFACE_ID)
        self.assertEqual(record.court_id, "example-court")
        self.assertEqual(record.source_schema_id, "unversioned")
        self.assertEqual(record.instrument.kind, "court")
        self.assertEqual(record.instrument.source_schema_id, SOURCE_SCHEMA_ID)
        self.assertEqual(record.instrument.source_schema_version, SOURCE_SCHEMA_ID)
        self.assertEqual(record.instrument.source_dataset, _COURTS_COMMON)
        self.assertEqual(dict(record.source_row), snapshot)
        self.assertNotIn(STATUTE_ID_FIELD, record.source_row)
        self.assertNotIn("docket_number", record.source_row)
        self.assertEqual(source, snapshot)
        source["note"] = "changed extra"
        self.assertEqual(record.source_row["note"], "kept extra")
        with self.assertRaises(TypeError):
            record.source_row["note"] = "rewritten"

    def test_opinion_body_is_rejected(self) -> None:
        self.assertIn("text", OPINION_BODY_FIELDS)
        self.assertIn("opinion_text", OPINION_BODY_FIELDS)
        opinion = _opinion_fixture()
        with self.assertRaises(CourtRejected) as caught:
            accept_court_row(opinion)
        self.assertIn("opinion text is refused", str(caught.exception))
        named = {
            "source_schema_id": SOURCE_SCHEMA_ID,
            "court_id": "example-court",
            "opinion_text": "The fixture opinion.",
        }
        with self.assertRaises(CourtRejected) as caught:
            accept_court_row(named)
        self.assertIn("opinion text is refused", str(caught.exception))
        case_text = {
            "source_schema_id": SOURCE_SCHEMA_ID,
            "court_id": "example-court",
            "case_text": "The fixture case text.",
        }
        with self.assertRaises(CourtRejected) as caught:
            accept_court_row(case_text)
        self.assertIn("opinion text is refused", str(caught.exception))

    def test_docket_number_is_not_a_statute_id(self) -> None:
        self.assertEqual(STATUTE_ID_FIELD, "id")
        docket = "1:20-cv-00001"
        claimed = {
            "source_schema_id": SOURCE_SCHEMA_ID,
            "court_id": "example-court",
            "name": "Example Courthouse",
            STATUTE_ID_FIELD: docket,
            "docket_number": docket,
        }
        with self.assertRaises(CourtRejected) as caught:
            accept_court_row(claimed)
        self.assertIn("docket number is not a statute id", str(caught.exception))
        nested = {
            "source_schema_id": SOURCE_SCHEMA_ID,
            STATUTE_ID_FIELD: docket,
            "metadata": {"docket_number": docket, "court_id": "nysd"},
        }
        with self.assertRaises(CourtRejected) as caught:
            accept_court_row(nested)
        self.assertIn("docket number is not a statute id", str(caught.exception))
        substitute = {
            "source_schema_id": SOURCE_SCHEMA_ID,
            "docket_number": docket,
            "name": "Example Courthouse",
        }
        with self.assertRaises(CourtRejected) as caught:
            accept_court_row(substitute)
        self.assertIn("court identifier is required", str(caught.exception))
        statute = {
            "source_schema_id": STATUTE_SCHEMA_ID,
            "court_id": "example-court",
            "name": "Example Courthouse",
        }
        with self.assertRaises(CourtRejected) as caught:
            accept_court_row(statute)
        self.assertIn("statute schema id is rejected", str(caught.exception))

    def test_missing_schema_id_and_blank_court_id_are_rejected(self) -> None:
        missing_schema = {"court_id": "example-court", "name": "Example Courthouse"}
        with self.assertRaises(CourtRejected) as caught:
            accept_court_row(missing_schema)
        self.assertIn("missing source schema id", str(caught.exception))
        blank = {
            "source_schema_id": SOURCE_SCHEMA_ID,
            "court_id": "   ",
            "name": "Example Courthouse",
        }
        with self.assertRaises(CourtRejected) as caught:
            accept_court_row(blank)
        self.assertIn("court identifier is required", str(caught.exception))
        repo = {
            "source_schema_id": WORLD_COURTS_REPO,
            "court_id": "example-court",
        }
        with self.assertRaises(CourtRejected) as caught:
            accept_court_row(repo)
        self.assertIn("not the schema id", str(caught.exception))

    def test_module_does_not_import_scrapers(self) -> None:
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        banned = (
            "courts_common",
            "upload_world_courts",
            "collect_fr_dila",
            "recap_archive",
            "courtlistener",
            "country_laws",
            "law_v1",
            "caselaw_v1",
            "torch",
            "cuda",
        )
        for name in names:
            for part in banned:
                self.assertNotIn(part, name)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CourtRowTest)
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if outcome.wasSuccessful() else 1)
