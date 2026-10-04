"""Typed, bounded queries over historical conditional verification evidence.

These values bind consumption to a complete structural head and an evidence
inventory. They confer no runtime, kernel, admission or completion authority.
The catalog remains responsible for current source observations and native
artifact replay; constructing a page is not a substitute for that operation.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .codebase_catalog import CodebaseHead
from .codebase_verification_catalog import (
    CodebaseVerificationCatalogError, CodebaseVerificationProjection,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured, validate_cid,
)

SELECTOR_SCHEMA = "codebase-verification-selector@1"
CURSOR_SCHEMA = "codebase-verification-query-cursor@1"
REQUEST_SCHEMA = "codebase-verification-query-request@1"
PAGE_SCHEMA = "codebase-verification-query-page@1"
_KEY = re.compile(r"canonical-proof-cache-key:sha256:[0-9a-f]{64}\Z")
_AUTHORITY = {
    "historical_conditional_evidence": True, "kernel_checked": False,
    "source_runtime_semantics_verified": False, "behavioral_satisfaction": False,
    "authoritative_cache_eligible": False, "admission_authority": False,
    "completion_authority": False,
}


def _text(value: Any, name: str, maximum: int = 512) -> str:
    if (type(value) is not str or not value or len(value) > maximum
            or value != value.strip() or any(ord(c) < 32 for c in value)
            or len(value.encode("utf-8")) > maximum):
        raise CodebaseVerificationCatalogError(f"{name} must be a bounded nonempty string")
    return value


def _cid(value: Any) -> str:
    _text(value, "CID", 256)
    try:
        return validate_cid(value, codecs={"dag-json"})
    except (TypeError, ValueError) as exc:
        raise CodebaseVerificationCatalogError("expected a canonical structured CID") from exc


def _epoch(value: Any) -> None:
    if type(value) is not int or not 1 <= value < 2**63:
        raise CodebaseVerificationCatalogError("evidence epoch must be a positive signed 64-bit integer")


@dataclass(frozen=True, slots=True)
class CodebaseVerificationSelector:
    """Conjunctive exact filters; omitted fields do not restrict the inventory."""

    path: str | None = None
    contract_id: str | None = None
    expected_contract_cid: str | None = None
    verification_cid: str | None = None
    canonical_key_id: str | None = None
    requested_domain_id: str | None = None
    requested_domain_cid: str | None = None
    dependency_kind: str | None = None
    dependency_value: str | None = None

    def __post_init__(self) -> None:
        from pathlib import PurePosixPath

        if self.path is not None:
            value = _text(self.path, "path", 1024)
            path = PurePosixPath(value)
            if (path.is_absolute() or path.as_posix() != value or ".." in path.parts
                    or not value.endswith(".py") or "\\" in value):
                raise CodebaseVerificationCatalogError("path must be a canonical relative Python path")
        for name in ("contract_id", "requested_domain_id"):
            value = getattr(self, name)
            if value is not None:
                _text(value, name)
        for name in ("expected_contract_cid", "verification_cid", "requested_domain_cid"):
            value = getattr(self, name)
            if value is not None:
                _cid(value)
        if self.canonical_key_id is not None:
            _text(self.canonical_key_id, "canonical_key_id", 128)
            if not _KEY.fullmatch(self.canonical_key_id):
                raise CodebaseVerificationCatalogError("canonical_key_id must be a complete exact key identity")
        if (self.dependency_kind is None) != (self.dependency_value is None):
            raise CodebaseVerificationCatalogError("dependency kind and value must be supplied together")
        if self.dependency_kind is not None:
            from .codebase_verification_projection import validate_dependency
            validate_dependency(self.dependency_kind, self.dependency_value)

    def to_dict(self) -> dict[str, Any]:
        self.__post_init__()
        return {"schema": SELECTOR_SCHEMA,
                **{name: getattr(self, name) for name in self.__dataclass_fields__}}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CodebaseVerificationSelector:
        if (type(value) is not dict or set(value) != set(cls.__dataclass_fields__) | {"schema"}
                or value["schema"] != SELECTOR_SCHEMA):
            raise CodebaseVerificationCatalogError("invalid exact selector fields or schema")
        return cls(**{name: value[name] for name in cls.__dataclass_fields__})

    @property
    def cid(self) -> str:
        return cid_for_structured(self.to_dict())


@dataclass(frozen=True, slots=True)
class CodebaseVerificationQueryCursor:
    """A continuation binds the query and inventory, including same-head appends."""

    head_cid: str
    inventory_cid: str
    epoch: int
    selector_cid: str
    after: str

    def __post_init__(self) -> None:
        for value in (self.head_cid, self.inventory_cid, self.selector_cid, self.after):
            _cid(value)
        _epoch(self.epoch)

    def to_dict(self) -> dict[str, Any]:
        self.__post_init__()
        return {"schema": CURSOR_SCHEMA,
                **{name: getattr(self, name) for name in self.__dataclass_fields__}}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CodebaseVerificationQueryCursor:
        if (type(value) is not dict or set(value) != set(cls.__dataclass_fields__) | {"schema"}
                or value["schema"] != CURSOR_SCHEMA):
            raise CodebaseVerificationCatalogError("invalid continuation cursor fields or schema")
        return cls(**{name: value[name] for name in cls.__dataclass_fields__})


@dataclass(frozen=True, slots=True)
class CodebaseVerificationQueryRequest:
    """One exact page request within a bounded, atomic query operation.

    Requests carry the existing cursor and selector without changing either
    identity. Catalog limits bound the request count and total requested page
    sizes before resource admission or repository observation.
    """

    selector: CodebaseVerificationSelector
    page_size: int = 16
    cursor: CodebaseVerificationQueryCursor | None = None

    def __post_init__(self) -> None:
        if type(self.selector) is not CodebaseVerificationSelector:
            raise CodebaseVerificationCatalogError("query requires a native exact selector")
        self.selector.__post_init__()
        if type(self.page_size) is not int or not 1 <= self.page_size < 2**63:
            raise CodebaseVerificationCatalogError("query page size must be a positive signed 64-bit integer")
        if self.cursor is not None:
            if type(self.cursor) is not CodebaseVerificationQueryCursor:
                raise CodebaseVerificationCatalogError("query cursor must be a native exact continuation")
            self.cursor.__post_init__()

    def to_dict(self) -> dict[str, Any]:
        self.__post_init__()
        return {"schema": REQUEST_SCHEMA, "selector": self.selector.to_dict(),
                "page_size": self.page_size,
                "cursor": None if self.cursor is None else self.cursor.to_dict()}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CodebaseVerificationQueryRequest:
        if (type(value) is not dict or set(value) != {"schema", "selector", "page_size", "cursor"}
                or value["schema"] != REQUEST_SCHEMA):
            raise CodebaseVerificationCatalogError("invalid exact query request fields or schema")
        return cls(CodebaseVerificationSelector.from_dict(value["selector"]), value["page_size"],
                   None if value["cursor"] is None else CodebaseVerificationQueryCursor.from_dict(value["cursor"]))


@dataclass(frozen=True, slots=True)
class CodebaseVerificationQueryEntry:
    entry_id: str
    contract_id: str
    projection: CodebaseVerificationProjection

    def __post_init__(self) -> None:
        _cid(self.entry_id)
        _text(self.contract_id, "contract_id")
        if type(self.projection) is not CodebaseVerificationProjection:
            raise CodebaseVerificationCatalogError("query entries require native historical projections")
        self.projection.__post_init__()
        if self.entry_id != cid_for_structured({"projection_cid": self.projection.projection_cid,
                                                "contract_id": self.contract_id}):
            raise CodebaseVerificationCatalogError("query entry does not bind its projection and contract")
        if sum(c["contract_id"] == self.contract_id for c in self.projection.to_dict()["contracts"]) != 1:
            raise CodebaseVerificationCatalogError("query entry contract inventory is ambiguous or absent")

    def to_dict(self) -> dict[str, Any]:
        self.__post_init__()
        payload = self.projection.to_dict()
        contract = next(c for c in payload["contracts"] if c["contract_id"] == self.contract_id)
        return {
            "entry_id": self.entry_id, "contract_id": self.contract_id,
            "projection_cid": self.projection.projection_cid,
            "verification_cid": payload["verification_cid"],
            "applicability_cid": payload["applicability_cid"], "path": payload["path"],
            "contract_cid": contract["contract_cid"], "domain_id": contract["domain_id"],
            "domain_cid": contract["domain_cid"],
            "canonical_key_ids": sorted({k["key_id"] for k in
                contract["canonical_keys"] + contract["applicability_keys"]}),
        }


@dataclass(frozen=True, slots=True)
class CodebaseVerificationQueryPage:
    selector: CodebaseVerificationSelector
    head: CodebaseHead
    inventory_cid: str
    epoch: int
    entries: tuple[CodebaseVerificationQueryEntry, ...]
    next_cursor: CodebaseVerificationQueryCursor | None = None
    start_cursor: CodebaseVerificationQueryCursor | None = None

    def __post_init__(self) -> None:
        if type(self.selector) is not CodebaseVerificationSelector or type(self.head) is not CodebaseHead:
            raise CodebaseVerificationCatalogError("query page requires a native selector and complete head")
        self.selector.__post_init__()
        self.head.__post_init__()
        _cid(self.inventory_cid)
        _epoch(self.epoch)
        if type(self.entries) is not tuple or len(self.entries) > 1024:
            raise CodebaseVerificationCatalogError("query page entries must be a bounded immutable tuple")
        previous = None
        for entry in self.entries:
            if type(entry) is not CodebaseVerificationQueryEntry:
                raise CodebaseVerificationCatalogError("query page contains a non-native entry")
            row = entry.to_dict()
            if previous is not None and entry.entry_id <= previous:
                raise CodebaseVerificationCatalogError("query entries must be unique and ordered")
            previous = entry.entry_id
            if entry.projection.to_dict()["head"] != self.head.to_dict():
                raise CodebaseVerificationCatalogError("query entry belongs to another complete head")
            for query_name, row_name in (
                ("path", "path"), ("contract_id", "contract_id"),
                ("expected_contract_cid", "contract_cid"), ("verification_cid", "verification_cid"),
                ("requested_domain_id", "domain_id"), ("requested_domain_cid", "domain_cid"),
            ):
                wanted = getattr(self.selector, query_name)
                if wanted is not None and row[row_name] != wanted:
                    raise CodebaseVerificationCatalogError("query entry does not match the exact selector")
            if (self.selector.canonical_key_id is not None
                    and self.selector.canonical_key_id not in row["canonical_key_ids"]):
                raise CodebaseVerificationCatalogError("query entry lacks the exact canonical key")
        if self.next_cursor is not None:
            cursor = self.next_cursor
            if type(cursor) is not CodebaseVerificationQueryCursor:
                raise CodebaseVerificationCatalogError("query page requires a native continuation cursor")
            cursor.__post_init__()
            if (not self.entries or cursor.head_cid != cid_for_structured(self.head.to_dict())
                    or cursor.inventory_cid != self.inventory_cid or cursor.epoch != self.epoch
                    or cursor.selector_cid != self.selector.cid or cursor.after != self.entries[-1].entry_id):
                raise CodebaseVerificationCatalogError("query page continuation binding changed")
        if self.start_cursor is not None:
            cursor = self.start_cursor
            if type(cursor) is not CodebaseVerificationQueryCursor:
                raise CodebaseVerificationCatalogError("query page requires a native starting cursor")
            cursor.__post_init__()
            if (cursor.head_cid != cid_for_structured(self.head.to_dict())
                    or cursor.inventory_cid != self.inventory_cid or cursor.epoch != self.epoch
                    or cursor.selector_cid != self.selector.cid
                    or (self.entries and self.entries[0].entry_id <= cursor.after)):
                raise CodebaseVerificationCatalogError("query page starting cursor binding changed")

    @property
    def complete(self) -> bool:
        return self.next_cursor is None

    def _body(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "schema": PAGE_SCHEMA, "selector": self.selector.to_dict(),
            "selector_cid": self.selector.cid, "head": self.head.to_dict(),
            "head_cid": cid_for_structured(self.head.to_dict()),
            "inventory_cid": self.inventory_cid, "epoch": self.epoch,
            "entries": [entry.to_dict() for entry in self.entries],
            "start_cursor": None if self.start_cursor is None else self.start_cursor.to_dict(),
            "next_cursor": None if self.next_cursor is None else self.next_cursor.to_dict(),
            "complete": self.complete, "authority": dict(_AUTHORITY),
        }

    @property
    def page_cid(self) -> str:
        return cid_for_structured(self._body())

    def to_dict(self) -> dict[str, Any]:
        value = self._body()
        return {**value, "page_cid": cid_for_structured(value)}
