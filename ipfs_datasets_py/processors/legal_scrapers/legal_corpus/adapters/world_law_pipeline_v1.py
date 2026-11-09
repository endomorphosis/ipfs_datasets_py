"""Adapt a world-law pipeline row at schema ``1.2.0``.

``SCHEMA_VERSION``, ``DOC_TYPES``, and the ``iso_`` place-key rule are read
from ``hub_integrated/world_law_pipeline/schema.py``. Label kinds are read
from the municipal register. The source ``DOC_TYPES`` string stays on the
row. ``decision`` stays unclassified. An ``iso_`` key stays national-shaped
and is not rewritten into a municipal id. This module does not import or
edit ``schema.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "hub_integrated"
    / "world_law_pipeline"
    / "schema.py"
)
_LAW_KIND = Path(__file__).resolve().parents[1] / "kinds" / "law_v1.py"
_MUNICIPAL_KIND = Path(__file__).resolve().parents[1] / "kinds" / "municipal_instrument_v1.py"

_READ_SCHEMA_VERSION = "1.2.0"
_READ_DOC_TYPES = (
    "code_section",
    "ordinance",
    "regulation",
    "statute",
    "gazette_act",
    "decision",
)
_READ_LABELS = {
    "code_section": "law",
    "ordinance": "law",
    "regulation": "regulation",
    "statute": "law",
    "gazette_act": "act",
    "decision": "not yet classified",
}
_UNCLASSIFIED = "not yet classified"
_NATIONAL_PREFIX = "iso_"
_READ_LAW_INTERFACE = "legal-corpus.law@1"
_READ_MUNICIPAL_INTERFACE = "legal-corpus.municipal-instrument@1"
_SOURCE_SCHEMA_FILE = "hub_integrated/world_law_pipeline/schema.py"


class AdapterBindingError(RuntimeError):
    """The adapter is not bound to pipeline schema 1.2.0 or the municipal register."""


class PipelineRejected(ValueError):
    """The row is not a pipeline ``1.2.0`` record this adapter can classify."""


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
    raise AdapterBindingError(f"{name} is missing from {path}")


def _bound_string(path: Path, name: str, expected: str) -> str:
    value = _module_assignment(path, name)
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        raise AdapterBindingError(f"{name} in {path} is not a string")
    if value.value != expected:
        raise AdapterBindingError(f"{name} in {path} is {value.value!r}, not {expected!r}")
    return value.value


def _bound_tuple(path: Path, name: str, expected: tuple[str, ...]) -> tuple[str, ...]:
    value = _module_assignment(path, name)
    if not isinstance(value, (ast.Tuple, ast.List)):
        raise AdapterBindingError(f"{name} in {path} is not a sequence")
    items: list[str] = []
    for item in value.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            raise AdapterBindingError(f"{name} in {path} contains a non-string")
        items.append(item.value)
    bound = tuple(items)
    if bound != expected:
        raise AdapterBindingError(f"{name} in {path} is {bound!r}, not {expected!r}")
    return bound


def _function_source(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(text, node)
            if not isinstance(segment, str) or not segment:
                break
            return segment
    raise AdapterBindingError(f"{name} is missing from {path}")


def _register_path() -> Path:
    here = Path(__file__).resolve()
    relative = Path("implementation_plan/legal_corpus_modules/registers/municipal.md")
    for parent in here.parents:
        candidate = parent / relative
        if candidate.is_file():
            return candidate
    raise AdapterBindingError("municipal register is missing")


def _label_table(path: Path) -> dict[str, str]:
    """Read the register's label table. Kinds that are not listed are not mapped."""

    found: dict[str, str] = {}
    in_section = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "## Label classification":
            in_section = True
            continue
        if not in_section:
            continue
        if line.startswith("## "):
            break
        stripped = line.strip()
        if not stripped:
            if found:
                break
            continue
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) != 2:
            continue
        label, kind = cells
        if label in {"Source label", "---"} or set(label) <= {"-"}:
            continue
        if not (label.startswith("`") and label.endswith("`") and len(label) >= 3):
            raise AdapterBindingError(f"register label is not a code span: {label!r}")
        name = label[1:-1]
        if not kind or "`" in kind:
            raise AdapterBindingError(f"register kind for {name} is {kind!r}")
        if name in found:
            raise AdapterBindingError(f"duplicate register label {name}")
        found[name] = kind
    if found != _READ_LABELS:
        raise AdapterBindingError(
            f"municipal register labels are {found!r}, not {_READ_LABELS!r}"
        )
    return found


def _bind_national_rule(path: Path) -> None:
    """Require the ``iso_`` predicate and the colon-to-underscore key rule."""

    national = _function_source(path, "is_national_key")
    if 'return str(pkey).startswith("iso_")' not in national:
        raise AdapterBindingError("is_national_key does not test the iso_ prefix")
    place = _function_source(path, "place_key")
    if "iso:US-CA -> iso_US-CA" not in place:
        raise AdapterBindingError("place_key does not keep iso:US-CA national-shaped")
    if 'return pid.replace(":", "_")' not in place:
        raise AdapterBindingError("place_key does not replace ':' with '_'")
    if 'return pid.split(":", 1)[1]' not in place:
        raise AdapterBindingError("place_key does not keep a gnis id unscoped")


SCHEMA_VERSION = _bound_string(_SCHEMA, "SCHEMA_VERSION", _READ_SCHEMA_VERSION)
DOC_TYPES = _bound_tuple(_SCHEMA, "DOC_TYPES", _READ_DOC_TYPES)
REPO_ID = _bound_string(_SCHEMA, "REPO_ID", "endomorphosis/world_municipal_law")
NATIONAL_REPO_ID = _bound_string(
    _SCHEMA,
    "NATIONAL_REPO_ID",
    "endomorphosis/world_national_law",
)
_bind_national_rule(_SCHEMA)
CLASSIFICATION = _label_table(_register_path())
LAW_INTERFACE_ID = _bound_string(_LAW_KIND, "INTERFACE_ID", _READ_LAW_INTERFACE)
MUNICIPAL_INTERFACE_ID = _bound_string(
    _MUNICIPAL_KIND,
    "INTERFACE_ID",
    _READ_MUNICIPAL_INTERFACE,
)
SOURCE_SCHEMA_FILE = _SOURCE_SCHEMA_FILE
if CLASSIFICATION["decision"] != _UNCLASSIFIED:
    raise AdapterBindingError("municipal register classifies decision")
if set(CLASSIFICATION) != set(DOC_TYPES):
    raise AdapterBindingError("register labels do not match DOC_TYPES")


def _is_national_key(pkey: str) -> bool:
    """Same predicate ``is_national_key`` returns in ``schema.py``."""

    return str(pkey).startswith(_NATIONAL_PREFIX)


def _derived_place_key(row: Mapping[str, Any]) -> str:
    """Derive a key only when the row does not already carry ``place_key``.

    ``iso:US-CA`` becomes ``iso_US-CA``. A stored ``iso_`` key is not passed
    through this function.
    """

    place_id = row.get("place_id")
    pid = place_id.strip() if isinstance(place_id, str) else ""
    gnis = row.get("gnis")
    gnis_text = "" if gnis in (None, "") else str(gnis).strip()
    if pid.startswith("gnis:"):
        return pid.split(":", 1)[1]
    country = row.get("country_code")
    country_text = country.strip() if isinstance(country, str) else ""
    if not pid and gnis_text and (country_text or "US").upper() == "US":
        return gnis_text
    if not pid:
        raise PipelineRejected("place_key needs place_id (or a US gnis)")
    return pid.replace(":", "_")


def _place_key(row: Mapping[str, Any]) -> str:
    """Keep a stored key. Reject an ``iso:`` id whose key is no longer ``iso_``."""

    stored = row.get("place_key")
    place_id = row.get("place_id")
    national_from_id = ""
    if isinstance(place_id, str) and place_id.strip().startswith("iso:"):
        national_from_id = place_id.strip().replace(":", "_")
        if not _is_national_key(national_from_id):
            raise PipelineRejected("iso place id did not stay national-shaped")
    if isinstance(stored, str) and stored.strip():
        key = stored
        if national_from_id and key != national_from_id:
            raise PipelineRejected("iso_ key was rewritten into a municipal id")
        return key
    if stored is not None:
        raise PipelineRejected("place_key must be a non-empty string")
    if national_from_id:
        return national_from_id
    return _derived_place_key(row)


class PipelineAdaptation:
    """One pipeline row, its source label, and the register classification."""

    __slots__ = (
        "schema_version",
        "doc_type",
        "classification",
        "place_key",
        "national",
        "repo_id",
        "source_row",
    )

    def __init__(
        self,
        *,
        schema_version: str,
        doc_type: str,
        classification: str,
        place_key: str,
        national: bool,
        repo_id: str,
        source_row: Mapping[str, Any],
    ) -> None:
        if schema_version != SCHEMA_VERSION:
            raise PipelineRejected(f"schema_version {schema_version!r} is not {SCHEMA_VERSION!r}")
        if doc_type not in DOC_TYPES:
            raise PipelineRejected(f"doc_type {doc_type!r} is not a DOC_TYPES value")
        if CLASSIFICATION.get(doc_type) != classification:
            raise PipelineRejected("classification is not the municipal register label")
        if doc_type == "decision" and classification != _UNCLASSIFIED:
            raise PipelineRejected("decision must stay unclassified")
        if national != _is_national_key(place_key):
            raise PipelineRejected("national flag does not follow the iso_ prefix")
        if national and not str(place_key).startswith(_NATIONAL_PREFIX):
            raise PipelineRejected("iso_ key was rewritten into a municipal id")
        expected_repo = NATIONAL_REPO_ID if national else REPO_ID
        if repo_id != expected_repo:
            raise PipelineRejected("repo id does not follow the iso_ rule")
        if isinstance(source_row, (str, bytes)) or not isinstance(source_row, Mapping):
            raise PipelineRejected("pipeline row must be a mapping")
        if source_row.get("schema_version") != SCHEMA_VERSION:
            raise PipelineRejected("row schema_version is not 1.2.0")
        if source_row.get("doc_type") != doc_type:
            raise PipelineRejected("row doc_type was rewritten")
        if source_row.get("place_key") != place_key:
            raise PipelineRejected("row place_key was rewritten")
        if MUNICIPAL_INTERFACE_ID in source_row.values():
            raise PipelineRejected("iso_ or pipeline row was given a municipal instrument id")
        self.schema_version = schema_version
        self.doc_type = doc_type
        self.classification = classification
        self.place_key = place_key
        self.national = national
        self.repo_id = repo_id
        self.source_row = source_row

    @property
    def classified(self) -> bool:
        """False when the register kind is ``not yet classified``."""

        return self.classification != _UNCLASSIFIED


def adapt_world_law_pipeline_row(row: Mapping[str, Any]) -> PipelineAdaptation:
    """Copy one pipeline row. Preserve ``1.2.0`` and the source ``doc_type``.

    Classified labels are only the municipal register's kinds. ``decision``
    stays ``not yet classified``. A stored ``iso_`` place key is copied
    unchanged and selects ``NATIONAL_REPO_ID``.
    """

    if isinstance(row, (str, bytes)) or not isinstance(row, Mapping):
        raise PipelineRejected("pipeline row must be a mapping")
    doc_type = row.get("doc_type")
    if not isinstance(doc_type, str) or doc_type not in DOC_TYPES:
        raise PipelineRejected(f"doc_type {doc_type!r} is not a DOC_TYPES value")
    version = row.get("schema_version")
    if version is not None and version != SCHEMA_VERSION:
        raise PipelineRejected(f"schema_version {version!r} is not {SCHEMA_VERSION!r}")
    place_key = _place_key(row)
    if _is_national_key(place_key) and place_key != str(row.get("place_key", place_key)):
        raise PipelineRejected("iso_ key was rewritten into a municipal id")
    copied = {key: row[key] for key in row}
    if "schema_version" not in copied:
        copied["schema_version"] = SCHEMA_VERSION
    if "place_key" not in copied:
        copied["place_key"] = place_key
    if copied.get("doc_type") != doc_type:
        raise PipelineRejected("row doc_type was rewritten")
    if copied.get("place_key") != place_key:
        raise PipelineRejected("row place_key was rewritten")
    national = _is_national_key(place_key)
    return PipelineAdaptation(
        schema_version=SCHEMA_VERSION,
        doc_type=doc_type,
        classification=CLASSIFICATION[doc_type],
        place_key=place_key,
        national=national,
        repo_id=NATIONAL_REPO_ID if national else REPO_ID,
        source_row=MappingProxyType(copied),
    )
