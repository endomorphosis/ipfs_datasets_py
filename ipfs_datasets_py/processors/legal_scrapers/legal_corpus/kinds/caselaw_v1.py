"""Caselaw kind for ``legal-corpus.caselaw@1``.

The caselaw register records schema id ``unversioned`` for each source
that assigns no ``SCHEMA_VERSION``. This module uses that id only after
it sees the assignment is absent. DILA keeps the keys ``parse`` returns.
CAP keeps the candidate names on ``CAPVectorSearchConfig``. A row is
copied with those keys. It is not rewritten onto the other source.
This module does not import CUDA code and does not start an embedding job.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

INTERFACE_ID = "legal-corpus.caselaw@1"
UNVERSIONED_SCHEMA_ID = "unversioned"

_PROCESSORS = Path(__file__).resolve().parents[3]
_DILA = "legal_scrapers/national_collectors/collect_fr_dila.py"
_RII = "legal_scrapers/national_collectors/collect_de_rii.py"
_CAP = "legal_scrapers/caselaw_access_program/vector_search_integration.py"
_RECAP = "legal_scrapers/recap_archive_scraper.py"
_WORLD = "legal_scrapers/hub_integrated/world_law_pipeline/scrapers/caselaw/amea/scrapers/caselaw"
_WORLD_UPLOAD = "legal_scrapers/hub_integrated/world_law_pipeline/scrapers/caselaw/amea/upload.py"
_PEACHJAM = f"{_WORLD}/peachjam.py"
_BR_STJ = f"{_WORLD}/br_stj.py"
_CO_CC = f"{_WORLD}/co_cc.py"
_WAYBACK = f"{_WORLD}/wayback_generic.py"

_CLAIM_FIELDS = ("source_schema_id", "schema_version")
_CAP_DATASET_ID = "justicedao/Caselaw_Access_Project_embeddings"
_WORLD_REPO = "endomorphosis/world_caselaw"


class CaselawBindingError(RuntimeError):
    """The caselaw kind is not bound to the register's source files."""


class CaselawRejected(ValueError):
    """The row is not a ``legal-corpus.caselaw@1`` record."""


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
    raise CaselawBindingError(f"{name} is missing from {path}")


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
        raise CaselawBindingError(f"{name} in {path} is not a string")
    if value.value != expected:
        raise CaselawBindingError(f"{name} in {path} is {value.value!r}, not {expected!r}")
    return value.value


def _unversioned(path: Path) -> str:
    """Schema id used when the source file assigns no ``SCHEMA_VERSION``."""

    if "SCHEMA_VERSION" in _names_assigned(path):
        raise CaselawBindingError(f"{path} assigns SCHEMA_VERSION")
    return UNVERSIONED_SCHEMA_ID


def _find_function(path: Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise CaselawBindingError(f"{name} is missing from {path}")


def _key_tuples(fn: ast.AST) -> list[tuple[str, ...]]:
    found: list[tuple[str, ...]] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Call):
            call = node.value
            func = call.func
            if isinstance(func, ast.Name) and func.id == "dict" and call.keywords:
                if any(item.arg is None for item in call.keywords):
                    continue
                found.append(tuple(item.arg for item in call.keywords if item.arg))
        if isinstance(node, ast.Dict):
            keys: list[str] = []
            good = True
            for key in node.keys:
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    good = False
                    break
                keys.append(key.value)
            if good and keys:
                found.append(tuple(keys))
    return found


def _column_list(path: Path, fn_name: str, anchor: str) -> tuple[str, ...]:
    matches: list[tuple[str, ...]] = []
    for keys in _key_tuples(_find_function(path, fn_name)):
        if anchor in keys and keys not in matches:
            matches.append(keys)
    if len(matches) != 1:
        raise CaselawBindingError(f"{path} {fn_name} column list count for {anchor} is {len(matches)}")
    return matches[0]


def _class_body(path: Path, class_name: str) -> list[ast.stmt]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return list(node.body)
    raise CaselawBindingError(f"{class_name} is missing from {path}")


def _class_string(path: Path, class_name: str, field: str, expected: str) -> str:
    for stmt in _class_body(path, class_name):
        if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
            continue
        if stmt.target.id != field:
            continue
        value = stmt.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            raise CaselawBindingError(f"{field} in {path} is not a string")
        if value.value != expected:
            raise CaselawBindingError(f"{field} in {path} is {value.value!r}, not {expected!r}")
        return value.value
    raise CaselawBindingError(f"{field} is missing from {class_name} in {path}")


def _class_tuple(path: Path, class_name: str, field: str) -> tuple[str, ...]:
    for stmt in _class_body(path, class_name):
        if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
            continue
        if stmt.target.id != field or not isinstance(stmt.value, ast.Tuple):
            continue
        values: list[str] = []
        for item in stmt.value.elts:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                raise CaselawBindingError(f"{field} in {path} contains a non-string")
            values.append(item.value)
        if not values:
            raise CaselawBindingError(f"{field} in {path} is empty")
        return tuple(values)
    raise CaselawBindingError(f"{field} is missing from {class_name} in {path}")


def _bind_sources() -> dict[str, dict[str, Any]]:
    """Read each register source without importing it."""

    dila_path = _PROCESSORS / _DILA
    rii_path = _PROCESSORS / _RII
    cap_path = _PROCESSORS / _CAP
    recap_path = _PROCESSORS / _RECAP
    peach_path = _PROCESSORS / _PEACHJAM
    br_path = _PROCESSORS / _BR_STJ
    co_path = _PROCESSORS / _CO_CC
    wayback_path = _PROCESSORS / _WAYBACK
    upload_path = _PROCESSORS / _WORLD_UPLOAD
    dataset_id = _class_string(cap_path, "CAPVectorSearchConfig", "dataset_id", _CAP_DATASET_ID)
    world_repo = _bound_string(upload_path, "REPO", _WORLD_REPO)
    profiles: dict[str, dict[str, Any]] = {
        "dila": {
            "path": _DILA,
            "schema_id": _unversioned(dila_path),
            "columns": _column_list(dila_path, "parse", "dila_id"),
        },
        "rii": {
            "path": _RII,
            "schema_id": _unversioned(rii_path),
            "columns": _column_list(rii_path, "parse", "rii_doknr"),
        },
        "cap": {
            "path": _CAP,
            "schema_id": _unversioned(cap_path),
            "columns": None,
            "dataset_id": dataset_id,
        },
        "recap_search": {
            "path": _RECAP,
            "schema_id": _unversioned(recap_path),
            "columns": _column_list(recap_path, "search_recap_documents", "abstract"),
        },
        "recap_detail": {
            "path": _RECAP,
            "schema_id": _unversioned(recap_path),
            "columns": _column_list(recap_path, "get_recap_document", "metadata"),
        },
        "world_peachjam": {
            "path": _PEACHJAM,
            "schema_id": _unversioned(peach_path),
            "columns": _column_list(peach_path, "build_row", "x_akn_frbr_uri"),
            "repo": world_repo,
        },
        "world_br_stj": {
            "path": _BR_STJ,
            "schema_id": _unversioned(br_path),
            "columns": _column_list(br_path, "main", "x_registro"),
            "repo": world_repo,
        },
        "world_co_cc": {
            "path": _CO_CC,
            "schema_id": _unversioned(co_path),
            "columns": _column_list(co_path, "main", "x_proceso"),
            "repo": world_repo,
        },
        "world_wayback": {
            "path": _WAYBACK,
            "schema_id": _unversioned(wayback_path),
            "columns": _column_list(wayback_path, "main", "x_original_url"),
            "repo": world_repo,
        },
    }
    if _unversioned(upload_path) != UNVERSIONED_SCHEMA_ID:
        raise CaselawBindingError("world caselaw upload.py schema id changed")
    fixed = [name for name, profile in profiles.items() if profile["columns"] is not None]
    for left_index, left_name in enumerate(fixed):
        for right_name in fixed[left_index + 1 :]:
            if profiles[left_name]["columns"] == profiles[right_name]["columns"]:
                raise CaselawBindingError(f"{left_name} and {right_name} share one column list")
    schema_ids = {profile["schema_id"] for profile in profiles.values()}
    if dataset_id in schema_ids or world_repo in schema_ids:
        raise CaselawBindingError("a dataset or repo name was bound as a schema id")
    if profiles["cap"]["schema_id"] != profiles["dila"]["schema_id"]:
        raise CaselawBindingError("CAP and DILA schema ids diverged from the register")
    return profiles


_PROFILES = _bind_sources()
SOURCE_SCHEMA_IDS = {name: str(profile["schema_id"]) for name, profile in _PROFILES.items()}
SOURCE_DATASETS = {name: str(profile["path"]) for name, profile in _PROFILES.items()}
DILA_COLUMNS = tuple(_PROFILES["dila"]["columns"])
RII_COLUMNS = tuple(_PROFILES["rii"]["columns"])
RECAP_SEARCH_COLUMNS = tuple(_PROFILES["recap_search"]["columns"])
RECAP_DETAIL_COLUMNS = tuple(_PROFILES["recap_detail"]["columns"])
WORLD_PEACHJAM_COLUMNS = tuple(_PROFILES["world_peachjam"]["columns"])
WORLD_BR_STJ_COLUMNS = tuple(_PROFILES["world_br_stj"]["columns"])
WORLD_CO_CC_COLUMNS = tuple(_PROFILES["world_co_cc"]["columns"])
WORLD_WAYBACK_COLUMNS = tuple(_PROFILES["world_wayback"]["columns"])
CAP_TEXT_FIELDS = _class_tuple(_PROCESSORS / _CAP, "CAPVectorSearchConfig", "text_field_candidates")
CAP_EMBEDDING_FIELDS = _class_tuple(_PROCESSORS / _CAP, "CAPVectorSearchConfig", "embedding_field_candidates")
CAP_ID_FIELDS = _class_tuple(_PROCESSORS / _CAP, "CAPVectorSearchConfig", "id_field_candidates")
CAP_METADATA_FIELDS = _class_tuple(_PROCESSORS / _CAP, "CAPVectorSearchConfig", "metadata_priority_fields")
CAP_DATASET_ID = str(_PROFILES["cap"]["dataset_id"])
WORLD_REPO = str(_PROFILES["world_peachjam"]["repo"])
_FIXED_COLUMNS = {
    name: tuple(profile["columns"])
    for name, profile in _PROFILES.items()
    if profile["columns"] is not None
}
_CAP_ALLOWED = frozenset(CAP_TEXT_FIELDS + CAP_EMBEDDING_FIELDS + CAP_ID_FIELDS + CAP_METADATA_FIELDS)
_FIXED_KEYS = frozenset(key for columns in _FIXED_COLUMNS.values() for key in columns)
_CAP_ONLY = _CAP_ALLOWED - _FIXED_KEYS
_EXCLUSIVE: dict[str, frozenset[str]] = {}
for _name, _columns in _FIXED_COLUMNS.items():
    _owners: dict[str, set[str]] = {}
    for _other, _other_columns in _FIXED_COLUMNS.items():
        for _key in _other_columns:
            _owners.setdefault(_key, set()).add(_other)
    _EXCLUSIVE[_name] = frozenset(
        key for key in _columns if _owners[key] == {_name} and key not in _CAP_ALLOWED
    )
_REGISTERED_SCHEMA_IDS = frozenset(SOURCE_SCHEMA_IDS.values())


def _load_instrument_record() -> type:
    """Load the shared instrument module from the legal corpus tree."""

    path = Path(__file__).resolve().parents[1] / "instrument_v1.py"
    spec = importlib.util.spec_from_file_location("_lcm_instrument_v1_caselaw", path)
    if spec is None or spec.loader is None:
        raise CaselawBindingError(f"instrument module is missing at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    record = getattr(module, "InstrumentRecord", None)
    interface = getattr(module, "INTERFACE_ID", "")
    if record is None or interface != "legal-corpus.instrument@1":
        raise CaselawBindingError("instrument_v1.py does not export legal-corpus.instrument@1")
    return record


InstrumentRecord = _load_instrument_record()


@dataclass(frozen=True)
class CaselawRecord:
    """One caselaw row carried as ``legal-corpus.caselaw@1``."""

    source_row: Mapping[str, Any]
    instrument: InstrumentRecord
    source_schema_id: str
    source_name: str

    def __post_init__(self) -> None:
        if self.source_name not in SOURCE_SCHEMA_IDS:
            raise CaselawRejected("source is not in the caselaw register")
        if self.source_schema_id != SOURCE_SCHEMA_IDS[self.source_name]:
            raise CaselawRejected("source schema id is not in the caselaw register")
        if self.instrument.kind != "caselaw":
            raise CaselawRejected("instrument kind must be caselaw")
        if self.instrument.source_schema_id != self.source_schema_id:
            raise CaselawRejected("instrument schema id does not match the register")
        row = self.source_row
        if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
            raise CaselawRejected("caselaw row must be a mapping")

    @property
    def interface_id(self) -> str:
        return INTERFACE_ID


def _body_keys(row: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(key for key in row if key not in _CLAIM_FIELDS)


def _claimed_schema(row: Mapping[str, Any]) -> str:
    """Return the schema id a row names in a source field."""

    claims: list[str] = []
    for key in _CLAIM_FIELDS:
        if key not in row:
            continue
        value = row[key]
        if not isinstance(value, str) or value.strip() == "":
            raise CaselawRejected(f"{key} must be a source schema id")
        claims.append(value)
    if not claims:
        raise CaselawRejected("missing source schema id")
    if any(item != claims[0] for item in claims):
        raise CaselawRejected("source schema id fields disagree")
    return claims[0]


def _matches_cap(keys: tuple[str, ...]) -> bool:
    """CAP rows keep their own keys. They are not a fixed column tuple."""

    keyset = set(keys)
    if not keyset.intersection(CAP_TEXT_FIELDS + CAP_ID_FIELDS):
        return False
    for key in keys:
        if key in _CAP_ALLOWED:
            continue
        if key in _FIXED_KEYS:
            return False
    return True


def _coerced(keys: tuple[str, ...]) -> bool:
    keyset = set(keys)
    owners = [name for name, exclusive in _EXCLUSIVE.items() if keyset.intersection(exclusive)]
    cap_only = keyset.intersection(_CAP_ONLY)
    if len(owners) > 1:
        return True
    return bool(owners and cap_only)


def _match_source(keys: tuple[str, ...]) -> str:
    exact = [name for name, columns in _FIXED_COLUMNS.items() if keys == columns]
    if len(exact) > 1:
        raise CaselawRejected("two caselaw sources were coerced into the same columns")
    if len(exact) == 1:
        return exact[0]
    if _coerced(keys):
        raise CaselawRejected("two caselaw sources were coerced into the same columns")
    if _matches_cap(keys):
        return "cap"
    raise CaselawRejected("row does not match one caselaw source")


def accept_caselaw_row(row: Mapping[str, Any]) -> CaselawRecord:
    """Record one registered source schema id and keep that source's columns.

    Claim fields name the schema id. The other keys are not renamed and
    are not filled from a second source. CAP and DILA therefore stay on
    the column lists their own files write.
    """

    if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
        raise CaselawRejected("caselaw row must be a mapping")
    claim = _claimed_schema(row)
    if claim not in _REGISTERED_SCHEMA_IDS:
        raise CaselawRejected("source schema id is not in the caselaw register")
    source_name = _match_source(_body_keys(row))
    if claim != SOURCE_SCHEMA_IDS[source_name]:
        raise CaselawRejected("source schema id is not in the caselaw register")
    copied = {key: row[key] for key in row}
    instrument = InstrumentRecord(
        kind="caselaw",
        source_schema_id=claim,
        source_schema_version=claim,
        source_dataset=SOURCE_DATASETS[source_name],
        source_row=copied,
    )
    return CaselawRecord(
        source_row=instrument.source_row,
        instrument=instrument,
        source_schema_id=claim,
        source_name=source_name,
    )


_DILA_VALUES: dict[str, object] = {
    "ecli": "ECLI:FR:CCASS:2020:FIXTURE",
    "jurisdiction": "FR",
    "court": "Cour de cassation",
    "chamber": "civile",
    "date": "2020-01-15",
    "number": "19-12.345",
    "title": "Fixture decision",
    "text": "The fixture decision body.",
    "source_url": "https://example.test/dila/1",
    "archive_name": "CASS_fixture.tar.gz",
    "is_archive": False,
    "licence": "Licence Ouverte 2.0",
    "retrieved_at": "2020-01-16T00:00:00+00:00",
    "court_id": None,
    "dila_id": "CASS-fixture",
    "config": "fr_cass",
}


def _dila_fixture() -> dict[str, object]:
    if set(_DILA_VALUES) != set(DILA_COLUMNS):
        raise AssertionError("DILA fixture keys are not the columns parse writes")
    row: dict[str, object] = {"source_schema_id": SOURCE_SCHEMA_IDS["dila"]}
    for key in DILA_COLUMNS:
        row[key] = _DILA_VALUES[key]
    return row


def _cap_fixture() -> dict[str, object]:
    return {
        "source_schema_id": SOURCE_SCHEMA_IDS["cap"],
        "opinion_text": "The fixture opinion.",
        "case_id": "cap-fixture-1",
        "citation": "1 F. Cas. 1",
        "court": "Example Court",
        "decision_date": "2020-01-15",
        "cluster_id": "cluster-1",
        "embedding": [0.25, 0.5],
    }


class CaselawRowTest(unittest.TestCase):
    """Accept a DILA-shaped row and a CAP-shaped row on their own schema ids."""

    def test_dila_and_cap_rows_keep_their_schema_ids(self) -> None:
        self.assertEqual(INTERFACE_ID, "legal-corpus.caselaw@1")
        self.assertEqual(SOURCE_SCHEMA_IDS["dila"], "unversioned")
        self.assertEqual(SOURCE_SCHEMA_IDS["cap"], "unversioned")
        self.assertEqual(CAP_DATASET_ID, "justicedao/Caselaw_Access_Project_embeddings")
        self.assertNotIn(CAP_DATASET_ID, SOURCE_SCHEMA_IDS.values())
        self.assertEqual(WORLD_REPO, "endomorphosis/world_caselaw")
        self.assertNotIn(WORLD_REPO, SOURCE_SCHEMA_IDS.values())
        self.assertIn("opinion_text", CAP_TEXT_FIELDS)
        self.assertIn("case_id", CAP_ID_FIELDS)
        self.assertIn("embedding", CAP_EMBEDDING_FIELDS)
        dila_source = _dila_fixture()
        cap_source = _cap_fixture()
        dila_snapshot = dict(dila_source)
        cap_snapshot = dict(cap_source)
        dila = accept_caselaw_row(dila_source)
        cap = accept_caselaw_row(cap_source)
        self.assertEqual(dila.interface_id, "legal-corpus.caselaw@1")
        self.assertEqual(cap.interface_id, INTERFACE_ID)
        self.assertEqual(dila.source_name, "dila")
        self.assertEqual(cap.source_name, "cap")
        self.assertEqual(dila.source_schema_id, SOURCE_SCHEMA_IDS["dila"])
        self.assertEqual(cap.source_schema_id, SOURCE_SCHEMA_IDS["cap"])
        self.assertEqual(dila.source_row["source_schema_id"], "unversioned")
        self.assertEqual(cap.source_row["source_schema_id"], "unversioned")
        self.assertEqual(dila.instrument.kind, "caselaw")
        self.assertEqual(cap.instrument.kind, "caselaw")
        self.assertEqual(dila.instrument.source_schema_id, dila.source_schema_id)
        self.assertEqual(cap.instrument.source_schema_id, cap.source_schema_id)
        self.assertEqual(dila.instrument.source_schema_version, "unversioned")
        self.assertEqual(cap.instrument.source_schema_version, "unversioned")
        self.assertEqual(dila.instrument.source_dataset, _DILA)
        self.assertEqual(cap.instrument.source_dataset, _CAP)
        self.assertNotEqual(dila.instrument.source_dataset, cap.instrument.source_dataset)
        self.assertEqual(_body_keys(dila.source_row), DILA_COLUMNS)
        self.assertEqual(_body_keys(cap.source_row), _body_keys(cap_snapshot))
        self.assertEqual(dict(dila.source_row), dila_snapshot)
        self.assertEqual(dict(cap.source_row), cap_snapshot)
        self.assertIn("dila_id", dila.source_row)
        self.assertNotIn("dila_id", cap.source_row)
        self.assertNotIn("ecli", cap.source_row)
        self.assertIn("opinion_text", cap.source_row)
        self.assertNotIn("opinion_text", dila.source_row)
        self.assertNotIn("embedding", dila.source_row)
        self.assertEqual(list(cap.source_row["embedding"]), [0.25, 0.5])
        self.assertEqual(dila_source, dila_snapshot)
        self.assertEqual(cap_source, cap_snapshot)
        dila_source["text"] = "changed"
        cap_source["opinion_text"] = "changed"
        self.assertEqual(dila.source_row["text"], "The fixture decision body.")
        self.assertEqual(cap.source_row["opinion_text"], "The fixture opinion.")
        with self.assertRaises(TypeError):
            dila.source_row["text"] = "rewritten"

    def test_registered_column_lists_stay_separate(self) -> None:
        self.assertNotEqual(DILA_COLUMNS, RII_COLUMNS)
        self.assertNotEqual(RECAP_SEARCH_COLUMNS, RECAP_DETAIL_COLUMNS)
        self.assertNotEqual(WORLD_PEACHJAM_COLUMNS, WORLD_BR_STJ_COLUMNS)
        self.assertNotEqual(WORLD_PEACHJAM_COLUMNS, WORLD_CO_CC_COLUMNS)
        self.assertNotEqual(WORLD_PEACHJAM_COLUMNS, WORLD_WAYBACK_COLUMNS)
        self.assertEqual(DILA_COLUMNS[0], "ecli")
        self.assertEqual(DILA_COLUMNS[-2:], ("dila_id", "config"))
        self.assertIn("rii_doknr", RII_COLUMNS)
        self.assertNotIn("dila_id", RII_COLUMNS)
        self.assertNotIn("rii_doknr", DILA_COLUMNS)
        self.assertIn("abstract", RECAP_SEARCH_COLUMNS)
        self.assertIn("metadata", RECAP_DETAIL_COLUMNS)
        self.assertNotIn("abstract", RECAP_DETAIL_COLUMNS)
        self.assertIn("x_akn_frbr_uri", WORLD_PEACHJAM_COLUMNS)
        self.assertNotIn("x_akn_frbr_uri", WORLD_BR_STJ_COLUMNS)
        for schema_id in SOURCE_SCHEMA_IDS.values():
            self.assertEqual(schema_id, "unversioned")

    def test_mixed_columns_are_rejected(self) -> None:
        mixed = _dila_fixture()
        mixed["opinion_text"] = "added from CAP"
        with self.assertRaises(CaselawRejected) as caught:
            accept_caselaw_row(mixed)
        self.assertIn("coerced", str(caught.exception))
        unknown = {
            "source_schema_id": "country-laws-ir-graphrag/v1",
            "opinion_text": "not a registered caselaw schema id",
            "case_id": "cap-foreign",
        }
        with self.assertRaises(CaselawRejected) as caught:
            accept_caselaw_row(unknown)
        self.assertIn("not in the caselaw register", str(caught.exception))

    def test_module_does_not_import_cuda_or_embeddings(self) -> None:
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        banned = (
            "torch",
            "cuda",
            "cupy",
            "vector_search",
            "embedding",
            "recap_archive",
            "collect_fr_dila",
            "collect_de_rii",
            "peachjam",
        )
        for name in names:
            for part in banned:
                self.assertNotIn(part, name)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CaselawRowTest)
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if outcome.wasSuccessful() else 1)
